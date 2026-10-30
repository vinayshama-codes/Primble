"""stops_now.py - ONE door for "which stops hold this package RIGHT NOW"
(6 Oct 2026, Choice Electric item 18).

WHY THIS EXISTS. The hard / soft stop lists were computed once - at extraction
or at a pipeline re-run - and PERSISTED, and the scorers then read the stored
lists back: form generation (`select_forms_bulk`), every per-form score
(`form_service.process_single_form`), the async worker, the pre-form door
(`sqs_service.score_package_pre_generation`) and the Clarity / Lite routes.
A stored list describes the facts AS THEY WERE when it was written. Live
(session ca93ed8f): a Data Consistency confirm at 18:21 re-ran the pipeline,
the re-run lost the producer's answers in memory (the `_fv` NameError, fixed
5 Oct) and stored "Property Minimum Viable COPE incomplete - missing: occupancy
type" - while the STORED facts, merged additively, still held the producer's
occupancy. Generation then capped the package at 60 for a gap that did not
exist, and the producer had to type the answer a second time.

THE RULE NOW: a stored stop list is a DISPLAY CACHE. Every scorer asks this
door, which rebuilds the lists from the stored facts with the SAME recipe the
extraction pipeline uses, and returns the same message text (issue ids,
dedupe and resolution marks key off the text). `tests/test_choice_electric_
flow_6oct.py` fails the build if a scorer is handed `session["hard_stops"]`
again, and pins pipeline / door parity.

The recipe, in the pipeline's own order:
  1. field-level: `evaluate_stops` on the facts, shaped exactly as the
     pipeline shapes them (`_ensure_fix_hint`, `_enrich_stops_with_source`);
  2. cross-DOCUMENT identity conflicts (`doc_consistency_stops`);
  3. open Data Consistency picker conflicts, read off the stored assessment
     (`underwriting_consistency`) - the same assessment that draws the cards,
     so the cap and the card cannot disagree;
  4. field-level source conflicts between documents;
  5. OCR "confirm this field" warnings, until a person supplies the field;
  6. cross-form rules for `form_ids`; every cross-form hard stop is a
     WARNING - before forms AND after them (`cross_form_severity`).

ONE STATUS FROM START TO FINISH (14 Oct 2026, owner; Brent: "Why do we have
something flagged as a warning pre-form that is re-flagged as a hard stop once
the form exists?"). C75 demoted a cross-form hard stop before forms (a form we
merely suggested may not become a blocker) and generation re-promoted it at
full force, so a package the Review screen called "warnings only" was capped at
60 the moment its forms existed. The demotion is now permanent: a check keeps
the status it had before forms, at generation and on every re-score after
(answers, saves, re-stamps, added documents, the worker). Field-level stops,
cross-DOCUMENT identity conflicts and blocking Data Consistency conflicts are
untouched - hard before forms, hard after. `pre_form` now decides only the
forms the rules are scoped to and whether a form choice is deferred.

Pure: no I/O, no LLM. Every piece fails open to "no stops from this piece"
and logs, so a scorer is never broken by one detector.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Byte-identical to the message `extraction_pipeline` has always emitted - the
# stored structured issue and its resolution status key off this text.
OCR_STOP_TEMPLATE = "Low OCR confidence on critical field — confirm: {field}"

# Identity / date / LOB fields `check_doc_consistency` owns, so the field-level
# source-conflict detector never reports them twice (same set the pipeline used).
_CONSISTENCY_OWNED = frozenset({
    "applicant_name", "dba_name", "entity_type", "mailing_address",
    "physical_address", "fein", "effective_date", "expiration_date",
    "lines_of_business",
})

# A conflict about a property value can only block when property coverage is
# carried (C75 relevance, 2026-09-23) - the same map the pipeline applied.
_RELEVANCE_FLAG = {
    "property_building_value": "has_property_coverage",
    "property_bpp_value":      "has_property_coverage",
}


def active_documents(session: Optional[dict]) -> List[dict]:
    """The documents that score: every document the producer did not exclude;
    all of them when every one is excluded (an empty package is never scored)."""
    docs = [d for d in ((session or {}).get("docs") or []) if isinstance(d, dict)]
    return [d for d in docs if not d.get("excluded")] or docs


def facts_as_stored(prior_facts: Optional[dict], incoming: dict,
                    delete_keys: Iterable[str] = ()) -> dict:
    """The facts a session will hold after `incoming` is written over
    `prior_facts` - the store's ADDITIVE merge (`resolve_facts_write`: an empty
    incoming value never erases a stored one), then the explicit retractions.

    A pipeline re-run scores THIS, so the stops it stores can never disagree
    with the facts it stores. No prior facts (a first upload) -> `incoming`."""
    if not isinstance(prior_facts, dict) or not prior_facts:
        return incoming
    try:
        from repositories.session_repository import resolve_facts_write
        stored = resolve_facts_write({"facts": dict(prior_facts)}, incoming or {})
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("facts_as_stored: merge preview failed (%s) - scoring the new facts", exc)
        return incoming
    if not isinstance(stored, dict):
        return incoming
    for key in delete_keys or ():
        stored.pop(key, None)
    return stored


def field_level_stops(facts: dict, flags: dict, docs: List[dict]) -> Tuple[List[str], List[str]]:
    """`evaluate_stops`, worded exactly as the extraction pipeline stores it."""
    from services.sqs_service import evaluate_stops
    hard, soft = evaluate_stops(facts or {}, flags or {})
    try:
        from services.extraction_pipeline import _enrich_stops_with_source, _ensure_fix_hint
        hard = _ensure_fix_hint(list(hard))
        soft = _ensure_fix_hint(_enrich_stops_with_source(list(soft), docs or []))
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("stops_now: message shaping skipped (%s)", exc)
    return list(hard), list(soft)


def _settled_by_confirmation(field: dict, confirmations: Optional[dict]) -> bool:
    """Has a person's Data Consistency pick settled this conflict row?

    A CONFIRMED PICK RETIRES ITS CONFLICT, ALWAYS (29 Oct 2026, review of
    614c3211). The assessment answers it when re-run with the confirmations
    (`status: "confirmed"`), but every reader here takes the STORED assessment,
    and a stored one older than the pick - a copy the answer preview edits, a
    row written before the re-run - kept the conflict and its 85 hold with the
    pick made. The same test `underwriting_consistency.unresolved_conflict_keys`
    applies (the bare key, read through `usable_confirmations` - a form number
    confirmed as a policy number is no answer), plus a line-scoped pick that
    answers every line the row asks about (SYS-06)."""
    if not confirmations:
        return False
    try:
        from services.underwriting_consistency import (
            scoped_confirmation_key, usable_confirmations,
        )
        usable = usable_confirmations(confirmations)
    except Exception:                                         # noqa: BLE001
        return False
    key = str(field.get("fact_key") or "")
    if not key:
        return False
    if key in usable:
        return True
    lines = [str(x) for x in (field.get("conflict_scope") or []) if x]
    if not lines or not all(scoped_confirmation_key(key, ln) in usable for ln in lines):
        return False
    # Every disputed line has a pick. Settled only when no candidate is left to
    # disagree - the assessment's own rule (`_drop_answered_line_candidates`): a
    # value is ruled out only when EVERY line it is stated on is answered and no
    # answer agrees with it; a value on an unanswered line (or with no line) still
    # stands (review, 29 Oct 2026 - a rival on an unpicked line kept the card
    # while its stop and hold vanished).
    try:
        from services.underwriting_consistency import _door_values_agree
    except Exception:                                         # noqa: BLE001
        return False
    picks = {ln: usable[scoped_confirmation_key(key, ln)] for ln in lines}
    for g in field.get("values") or []:
        if not isinstance(g, dict):
            continue
        val = g.get("display") if g.get("display") is not None else g.get("normalized")
        on = {str(x) for x in (g.get("scope") or []) if x}
        mine = [picks[ln] for ln in on if ln in picks] if on else list(picks.values())
        if any(_door_values_agree(key, val, p) for p in mine):
            continue                          # the value a pick chose for its line
        if on and on <= set(picks):
            continue                          # ruled out on every line it is stated on
        return False                          # a rival on an unanswered line still stands
    return True


def underwriting_conflict_stops(underwriting: Optional[dict],
                                flags: Optional[dict],
                                docs: Optional[List[dict]] = None,
                                confirmations: Optional[dict] = None) -> List[Tuple[str, str, bool]]:
    """[(fact_key, message, blocking)] for every OPEN Data Consistency conflict.

    BLOCKING MEANS HARD STOP, AND RELEVANCE IS A PRECONDITION (C75): a key in
    the declared blocking set (`READY_BLOCKING_RECONCILABLE_KEYS`, 19 Oct 2026)
    blocks, unless the coverage it belongs to is absent or the reconciler
    downgraded it as contract-scoped.

    VERIFIED SOURCES ONLY (21 Oct 2026, Brent 20 Oct): with the package's
    `docs`, a name / FEIN conflict blocks only when at least two of its rival
    values are each stated by a verified source (`document_tags.
    conflict_sources_verified`, over the ONE definition `is_verified_source`);
    otherwise it is a warning whose sentence ends by naming the unverified
    document(s). Every production caller passes its documents; without them
    the stored answer stands, exactly as before.

    `confirmations`: the session's Data Consistency picks - a row they settle
    is not open, whatever the stored assessment says (`_settled_by_confirmation`)."""
    uw = underwriting or {}
    if not uw.get("review_required"):
        return []
    try:
        # Only documents naming different companies block (Brent, 19 Oct 2026):
        # the applicant's name and FEIN. Dates and building value are warnings.
        from services.underwriting_consistency import READY_BLOCKING_RECONCILABLE_KEYS
        blocking_keys = set(READY_BLOCKING_RECONCILABLE_KEYS)
    except Exception:                                         # noqa: BLE001
        blocking_keys = set()
    try:
        from services.document_tags import (
            conflict_sources_verified as _sources_verified, unverified_note as _unverified_note,
        )
    except Exception:                                         # noqa: BLE001
        _sources_verified = None
    out: List[Tuple[str, str, bool]] = []
    for f in uw.get("fields") or []:
        if not isinstance(f, dict) or not f.get("review_required"):
            continue
        if _settled_by_confirmation(f, confirmations):
            continue                         # the pick is made (see the helper)
        key = f.get("fact_key", "field")
        _shown = ', '.join(str(v.get('display')) for v in (f.get('values') or []))
        if f.get("one_document") and key not in blocking_keys:
            # ONE document contradicting its own figure (Michelle review item
            # 2, 29 Oct 2026) is not "documents disagree": it names the file.
            msg = (f"{f.get('one_document')} states more than one amount for "
                   f"{f.get('label')} ({_shown}) - confirm which one is right.")
        else:
            msg = (
                f"{f.get('label')}: documents disagree ({_shown}). "
                "Fix: Confirm the correct value to apply it across forms."
            )
        needs_flag = _RELEVANCE_FLAG.get(key)
        relevant = (not needs_flag) or bool((flags or {}).get(needs_flag))
        downgraded = bool(f.get("blocking_downgraded"))
        if downgraded:
            msg += (" This package evidences more than one policy, "
                    "and each policy carries its own term.")
        blocking = key in blocking_keys and relevant and not downgraded
        if blocking and docs is not None and _sources_verified is not None:
            try:
                _verified, _descs = _sources_verified(f.get("values") or [], docs, key)
            except Exception as exc:                          # noqa: BLE001
                logger.warning("stops_now: source verification skipped for %s (%s)", key, exc)
                _verified, _descs = True, []
            if not _verified:
                blocking = False
                msg += _unverified_note(_descs)
        out.append((key, msg, blocking))
    return out


def source_conflict_stops(docs: List[dict],
                          underwriting: Optional[dict]) -> List[Tuple[str, str, bool]]:
    """[(fact_key, message, is_carrier)] - field-level disagreements between
    documents that neither the identity check nor the picker owns."""
    if len(docs or []) <= 1:
        return []
    try:
        from services.extraction_service import detect_source_conflicts
        from services.underwriting_consistency import RECONCILABLE_FIELD_KEYS
        found = list(detect_source_conflicts(
            docs,
            skip_fields=set(RECONCILABLE_FIELD_KEYS) | set(_CONSISTENCY_OWNED)
            | set((underwriting or {}).get("assessed_keys") or []),
            return_fields=True,
        ) or [])
        # The producer's contact details are the submitting agency's (the login
        # account): two documents printing different producer offices - often
        # a carrier's head office - is never a conflict to settle here (owner,
        # 24 Oct 2026, package 6a535b39). The producer NAME stays with the
        # picker's own rule.
        return [f for f in found if not (str(f[0]).startswith("producer_")
                                         and f[0] != "producer_name")]
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("stops_now: source conflicts skipped (%s)", exc)
        return []


def ocr_review_stops(docs: List[dict], facts: Optional[dict],
                     confirmations: Optional[dict] = None) -> List[Tuple[str, str]]:
    """[(field, message)] for critical fields OCR read with low confidence.
    Satisfied - and so not listed - once a person supplied the field or
    confirmed it in the Data Consistency picker (the same test
    `issue_registry.drop_confirmed_ocr_issues` applies to the card)."""
    fields: List[str] = []
    for d in docs or []:
        for fld in d.get("manual_confirmation_required") or []:
            if fld not in fields:
                fields.append(fld)
    if not fields:
        return []
    try:
        from services.issue_registry import _is_human_supplied
    except Exception:                                         # noqa: BLE001
        _is_human_supplied = lambda _v: False                 # noqa: E731
    try:
        from services.underwriting_consistency import confirmed_fact_keys
        confirmed = set(confirmed_fact_keys(confirmations or {}))
    except Exception:                                         # noqa: BLE001
        confirmed = set((confirmations or {}).keys())
    out = []
    for fld in fields:
        if fld in confirmed or _is_human_supplied((facts or {}).get(fld)):
            continue
        out.append((fld, OCR_STOP_TEMPLATE.format(field=fld)))
    return out


def recommended_form_ids(session: Optional[dict]) -> List[str]:
    return [str(r.get("form_id")) for r in ((session or {}).get("recommendations") or [])
            if isinstance(r, dict) and r.get("form_id")]


def cross_form_run(facts: dict, flags: dict, form_ids: Iterable[str]) -> List[dict]:
    """The cross-form rules for `form_ids`, each sentence once - the door's one
    read of `run_cross_form_validation` (raises what the validator raises; the
    callers decide what a failure means)."""
    from services.cross_form_validator import run_cross_form_validation
    out: List[dict] = []
    seen = set()
    for issue in run_cross_form_validation(facts, flags, set(form_ids or ())) or []:
        if not isinstance(issue, dict):
            continue
        msg = issue.get("message", "")
        if msg and msg in seen:
            continue
        seen.add(msg)
        out.append(issue)
    return out


# ── ONE STATUS FROM START TO FINISH (14 Oct 2026, owner) ─────────────────────
# The ONE answer to "what severity does a cross-form rule's hard stop carry?":
# a warning, before forms and after. Every path that runs the cross-form rules
# for scoring asks this function - this door, the post-form recalculation
# (`arq_service.recalculate_session_scores`) and the field-edit re-score
# (`form_routes.update_pdf`) - so the severity is decided once, one way.
#
# Replaces round 5 #15's `becomes_hard_at_generation` / `generation_tag`
# ("Becomes a hard stop when ACORD 140 is generated"): nothing becomes a hard
# stop at generation any more, so there is nothing to announce. Both, and the
# `with_generation_hard_stops` shim, were removed once nothing called them.

def cross_form_severity(issues: Optional[Iterable[Any]]) -> List[Any]:
    """`issues` with every cross-form `hard_stop` as a `soft_warning` (a copy
    of each changed issue; everything else, advisories and form choices
    included, unchanged)."""
    return [dict(i, type="soft_warning") if isinstance(i, dict) and i.get("type") == "hard_stop"
            else i for i in (issues or [])]


def conflict_stop_issues(session: Optional[dict]) -> List[Dict[str, Any]]:
    """Every stop a Data Consistency row settles, as the card the review screen
    draws for it: [{message, code, fact, picker}] - the documents' identity
    disagreements (`doc_conflict_(hard|warn)_<code>`, `issue_registry.
    doc_conflict_code`'s derivation) and the picker's own open conflicts
    (`underwriting_reconciliation_<fact>`). Same doors as `stops_now`, so the
    messages match its lists. Never raises."""
    session = session or {}
    out: List[Dict[str, Any]] = []
    try:
        from services.sqs_service import doc_consistency_stops
        from services.issue_registry import _DOC_CONFLICT_CODE_TO_FACT
        for c in doc_consistency_stops(session, with_conflicts=True)[2] or []:
            code = str((c or {}).get("code") or "")
            if code and (c or {}).get("message"):
                out.append({"message": str(c["message"]),
                            "code": f"doc_conflict_{'hard' if c.get('hard_stop') else 'warn'}_{code}",
                            "fact": _DOC_CONFLICT_CODE_TO_FACT.get(code, code), "picker": False})
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("conflict_stop_issues: document conflicts skipped (%s)", exc)
    flags = session.get("flags") if isinstance(session.get("flags"), dict) else {}
    for key, msg, _blocking in underwriting_conflict_stops(session.get("underwriting_consistency") or {}, flags,
                                                           active_documents(session),
                                                           session.get("underwriting_confirmations")):
        out.append({"message": str(msg), "code": f"underwriting_reconciliation_{key}",
                    "fact": str(key), "picker": True})
    return out


def conflict_stop_facts(session: Optional[dict]) -> Dict[str, str]:
    """{stop message: fact} for every stop a Data Consistency row settles - the
    documents' identity disagreements and the picker's own open conflicts (15 Oct
    2026: the review screen prints their points on that row, or on the card whose
    "Fix in Data Consistency" button leads there). Never raises."""
    return {i["message"]: i["fact"] for i in conflict_stop_issues(session)}


# ONE READING, ONE STOPS RUN (Z38 lane F, 24 Oct 2026). Reading the review page
# once runs this door twice on the SAME row (the package scorer and the cards,
# `sqs_service.review_page_grouped_view`) - 0.5-0.7 s each on a real package.
# Inside `stops_memo()` (the answer preview's page reading) a second call with
# the same session / facts / flags OBJECTS and the same scope returns a copy of
# the first result. Outside it nothing changes: no memo, every call recomputes.
import contextlib as _contextlib
import contextvars as _contextvars
import copy as _copy

_STOPS_MEMO: "_contextvars.ContextVar[Optional[dict]]" = _contextvars.ContextVar(
    "stops_now_memo", default=None)


@_contextlib.contextmanager
def stops_memo():
    """Memoise `stops_now` for the duration of the block (one page reading)."""
    token = _STOPS_MEMO.set({})
    try:
        yield
    finally:
        _STOPS_MEMO.reset(token)


def stops_now(session: Optional[dict], form_ids: Optional[Iterable[str]] = None, *,
              pre_form: bool, facts: Optional[dict] = None,
              flags: Optional[dict] = None) -> Dict[str, Any]:
    """The stops as they stand on the STORED session (or on `facts` / `flags`
    when the caller holds newer ones it is about to store).

    `form_ids`: the forms cross-form rules are scoped to - the forms being
    generated, or before forms exist the recommended forms (the default).
    `pre_form`: True before any form is generated - the rules are then scoped
    to the recommended forms (the default) and a check whose only fix is
    choosing a form is deferred. Required on purpose: it picks the scope. It
    no longer picks the severity - a cross-form hard stop is a warning either
    way (`cross_form_severity`, 14 Oct 2026).

    Returns:
      hard / soft          - the package scorer's stop lists (field-level +
                             document + picker + source + OCR + cross-form)
      form_hard / form_soft - what ONE form is scored with: field-level and
                             cross-document identity stops only (spec 10:
                             cross-form conflicts never cap an individual form)
      evaluate_hard / evaluate_soft - `evaluate_stops` alone, shaped
      cross_issues         - the cross-form issue dicts (hard stops demoted)
      form_ids             - the scope used
    """
    session = session or {}
    facts = session.get("facts") if facts is None else facts
    flags = session.get("flags") if flags is None else flags
    # Inside `stops_memo()` only: the same row, facts and flags OBJECTS and the
    # same scope as an earlier call in this reading -> a copy of its result.
    memo, memo_key = _STOPS_MEMO.get(), None
    if memo is not None:
        form_ids = None if form_ids is None else list(form_ids)   # never consume an iterator twice
        _scope = (tuple(str(x) for x in form_ids if x) if form_ids is not None
                  else tuple(recommended_form_ids(session)) if pre_form else None)
        if _scope is not None:
            memo_key = (id(session), id(facts), id(flags), _scope, bool(pre_form))
            hit = memo.get(memo_key)
            if hit is not None and hit[0] is session and hit[1] is facts and hit[2] is flags:
                return _copy.deepcopy(hit[3])
            memo_objs = (session, facts, flags)
    facts = facts if isinstance(facts, dict) else {}
    flags = flags if isinstance(flags, dict) else {}
    docs = active_documents(session)
    if form_ids is None:
        form_ids = recommended_form_ids(session) if pre_form else (
            list(session.get("selected_form_ids") or [])
            + [f for f in (session.get("generated_forms") or {}) if f not in (session.get("selected_form_ids") or [])])
    form_ids = [str(f) for f in form_ids if f]

    ev_hard, ev_soft = field_level_stops(facts, flags, docs)
    hard: List[str] = list(ev_hard)
    soft: List[str] = list(ev_soft)

    try:
        from services.sqs_service import doc_consistency_stops
        doc_hard, doc_soft = doc_consistency_stops(session)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("stops_now: document consistency skipped (%s)", exc)
        doc_hard, doc_soft = [], []
    hard += list(doc_hard)
    soft += list(doc_soft)
    form_hard, form_soft = list(hard), list(soft)

    underwriting = session.get("underwriting_consistency") or {}
    for _key, msg, blocking in underwriting_conflict_stops(underwriting, flags, docs,
                                                           session.get("underwriting_confirmations")):
        (hard if blocking else soft).append(msg)
    try:
        from services.issue_registry import explained_issue_codes, person_settled_fact
        _explained = explained_issue_codes(facts)
    except Exception:                                         # noqa: BLE001
        _explained, person_settled_fact = set(), (lambda _f, _k: False)
    for _key, msg, _carrier in source_conflict_stops(docs, underwriting):
        # Settled by a person's value, or explained (15 Oct 2026).
        _code = f"source_conflict_{'carrier_' if _carrier else ''}{_key}"
        if _code in _explained or person_settled_fact(facts, _key):
            continue
        soft.append(msg)
    for _fld, msg in ocr_review_stops(docs, facts, session.get("underwriting_confirmations")):
        soft.append(msg)

    cross: List[dict] = []
    if not (pre_form and (session.get("integrity") or {}).get("review_required")):
        try:
            from services.cross_form_validator import defer_form_choices, split_cross_form_issues
            cross = cross_form_run(facts, flags, form_ids)
            # THE PACKAGE NEVER DEPENDS ON THE FORMS (owner, 30 Oct 2026): after
            # forms the PACKAGE checks are read on the same scope as before
            # forms (the recommended forms), so the same facts give the same
            # package stops; the FORM checks are read on the forms generated
            # (they hold only those forms - `issue_registry.issue_scope`).
            if not pre_form:
                _rec = recommended_form_ids(session)
                if _rec and sorted(set(_rec)) != sorted(set(form_ids)):
                    from services.issue_registry import issue_scope as _scope_of
                    cross = ([i for i in cross_form_run(facts, flags, _rec)
                              if _scope_of(i) == "package"]
                             + [i for i in cross if _scope_of(i) == "form"])
            # A check whose only fix is choosing a form is a form choice, not a
            # stop (13 Oct 2026, the SQS without forms) - outside both lists,
            # marked `form_choice`. AFTER forms too (25 Oct 2026, Brent 23 Oct
            # "the package score is independent of the forms"): generating
            # without ACORD 186 dropped a finished package 100 -> 85. It stays
            # offered as a form to add.
            cross = defer_form_choices(cross)
            cf_hard, cf_soft, _adv = split_cross_form_issues(cross)
            # ONE STATUS FROM START TO FINISH (14 Oct 2026): C75's demotion,
            # before forms and after, in the pipeline's own order - the
            # demoted hard stops first, then the warnings not already listed.
            # Generation no longer re-promotes them (a 60 cap the pre-form
            # screen never showed).
            soft += list(cf_hard)
            soft += [m for m in cf_soft if m not in soft]
            cross = cross_form_severity(cross)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("stops_now: cross-form validation skipped (%s)", exc)

    out = {
        "hard": hard, "soft": soft,
        "form_hard": form_hard, "form_soft": form_soft,
        "evaluate_hard": list(ev_hard), "evaluate_soft": list(ev_soft),
        "cross_issues": cross,
        "form_ids": form_ids,
        "pre_form": bool(pre_form),
    }
    if memo_key is not None:
        memo[memo_key] = (*memo_objs, _copy.deepcopy(out))
    return out
