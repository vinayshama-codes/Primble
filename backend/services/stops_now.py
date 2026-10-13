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
  6. cross-form rules for `form_ids`; before forms exist (`pre_form=True`)
     every cross-form hard stop is demoted to a warning (owner C75 - a form
     we merely suggested may not become a blocker). That severity rule is
     unchanged here; this door only stops reading a stale list.

Pure: no I/O, no LLM. Every piece fails open to "no stops from this piece"
and logs, so a scorer is never broken by one detector.

`becomes_hard_at_generation` (7 Oct 2026, round 5 #15) is the other half of
step 6: before forms, which demoted warnings generation will make hard stops,
and on which forms - so the pre-form screen can say so (Brent #18).
"""
from __future__ import annotations

import logging
import re
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


def underwriting_conflict_stops(underwriting: Optional[dict],
                                flags: Optional[dict]) -> List[Tuple[str, str, bool]]:
    """[(fact_key, message, blocking)] for every OPEN Data Consistency conflict.

    BLOCKING MEANS HARD STOP, AND RELEVANCE IS A PRECONDITION (C75): a key in
    the two declared blocking sets blocks, unless the coverage it belongs to
    is absent or the reconciler downgraded it as contract-scoped."""
    uw = underwriting or {}
    if not uw.get("review_required"):
        return []
    try:
        from services.underwriting_consistency import (
            HARD_STOP_RECONCILABLE_KEYS, GENERATION_BLOCKING_RECONCILABLE_KEYS,
        )
        blocking_keys = set(HARD_STOP_RECONCILABLE_KEYS) | set(GENERATION_BLOCKING_RECONCILABLE_KEYS)
    except Exception:                                         # noqa: BLE001
        blocking_keys = set()
    out: List[Tuple[str, str, bool]] = []
    for f in uw.get("fields") or []:
        if not isinstance(f, dict) or not f.get("review_required"):
            continue
        key = f.get("fact_key", "field")
        msg = (
            f"{f.get('label')}: documents disagree "
            f"({', '.join(str(v.get('display')) for v in (f.get('values') or []))}). "
            "Fix: Confirm the correct value to apply it across forms."
        )
        needs_flag = _RELEVANCE_FLAG.get(key)
        relevant = (not needs_flag) or bool((flags or {}).get(needs_flag))
        downgraded = bool(f.get("blocking_downgraded"))
        if downgraded:
            msg += (" This package evidences more than one policy, "
                    "and each policy carries its own term.")
        out.append((key, msg, key in blocking_keys and relevant and not downgraded))
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
        return list(detect_source_conflicts(
            docs,
            skip_fields=set(RECONCILABLE_FIELD_KEYS) | set(_CONSISTENCY_OWNED)
            | set((underwriting or {}).get("assessed_keys") or []),
            return_fields=True,
        ) or [])
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


# ── WHAT GENERATION WILL MAKE A HARD STOP (7 Oct 2026, round 5 #15) ─────────
# Brent #18: "There were no Hard Stops in the initial SQS prior to form
# selection, but there's Hard Stops now. Why? This should all be addressable
# prior to forms." Before forms, C75 shows a cross-form hard stop as a warning
# (a form we merely suggested may not block - Brent's pending call, unchanged
# here); generation re-runs the same rules on the forms being generated at full
# force. The pre-form screen now says which warnings that will promote, and on
# which forms - read off the SAME run the demotion reads (`cross_form_run` on
# the recommended forms), never a second rule list.
#
# WHICH FORMS: the rules gate on the form set in different ways (ACORD 140;
# ACORD 140 or 160; no form at all), so the forms are MEASURED, never read off
# the issue's own "Affects" list (it names ACORD 125 beside ACORD 130 on a
# rule only ACORD 130 triggers). In order:
#   * fires with NO form chosen   -> any generation ("when forms are generated");
#   * forms whose removal from the recommended set retires it -> each is needed
#     ("when ACORD 127 and ACORD 131 are generated");
#   * else the forms that fire it on their own ("ACORD 140 or ACORD 160");
#   * else "when forms are generated".
# ~3 ms a run once warm; at most 1 + 2 x (recommended forms) runs.

def _forms_text(labels: List[str], joiner: str) -> str:
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" {joiner} " + labels[-1]


def _form_order(form_id: str) -> tuple:
    """ACORD 130 before ACORD 140 before ACORD 160, whatever order the
    recommender listed them in."""
    m = re.search(r"\d+", str(form_id or ""))
    return (int(m.group(0)) if m else 10 ** 6, str(form_id or ""))


def generation_tag(form_ids: List[str], all_needed: bool = True) -> str:
    """"Becomes a hard stop when ACORD 140 is generated" (no em-dash: UI copy)."""
    if not form_ids:
        return "Becomes a hard stop when forms are generated"
    try:
        from services.form_instances import instance_label
        labels = [instance_label(f) for f in form_ids]
    except Exception:                                         # noqa: BLE001
        labels = [str(f).replace("_", " ") for f in form_ids]
    verb = "are" if (all_needed and len(labels) > 1) else "is"
    return (f"Becomes a hard stop when {_forms_text(labels, 'and' if all_needed else 'or')} "
            f"{verb} generated")


def becomes_hard_at_generation(session: Optional[dict],
                               form_ids: Optional[Iterable[str]] = None, *,
                               facts: Optional[dict] = None,
                               flags: Optional[dict] = None) -> List[dict]:
    """[{code, message, forms, tag}] - the cross-form hard stops C75 shows as
    warnings before forms, i.e. the warnings generation will promote (see the
    note above). Empty once forms exist, while a Submission Integrity review is
    pending (the door runs no cross-form rule then) or when the run fails.
    Display only: nothing here adds, removes or re-ranks a stop."""
    session = session or {}
    if session.get("generated_forms") or (session.get("integrity") or {}).get("review_required"):
        return []
    facts = session.get("facts") if facts is None else facts
    flags = session.get("flags") if flags is None else flags
    facts = facts if isinstance(facts, dict) else {}
    flags = flags if isinstance(flags, dict) else {}
    scope = [str(f) for f in (recommended_form_ids(session) if form_ids is None else form_ids) if f]
    if not scope:
        return []
    try:
        hard = [i for i in cross_form_run(facts, flags, scope) if i.get("type") == "hard_stop"]
        if not hard:
            return []
        from services.form_instances import base_form_id
        bases: List[str] = []
        for f in scope:
            b = base_form_id(f)
            if b not in bases:
                bases.append(b)
        runs: Dict[Any, set] = {}

        def _hard_codes(ids: tuple) -> set:
            if ids not in runs:
                runs[ids] = {str(i.get("code") or "") for i in cross_form_run(facts, flags, list(ids))
                             if i.get("type") == "hard_stop"}
            return runs[ids]

        out: List[dict] = []
        for issue in hard:
            code = str(issue.get("code") or "")
            if code and code in _hard_codes(()):
                forms, all_needed = [], True
            else:
                forms = [b for b in bases
                         if code not in _hard_codes(tuple(f for f in scope if base_form_id(f) != b))]
                all_needed = True
                if not forms:
                    forms = [b for b in bases if code in _hard_codes((b,))]
                    all_needed = False
            forms = sorted(forms, key=_form_order)
            out.append({"code": code, "message": issue.get("message") or "",
                        "forms": forms, "tag": generation_tag(forms, all_needed)})
        return out
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("stops_now: generation hard stops skipped (%s)", exc)
        return []


def with_generation_hard_stops(pkg: Optional[dict], session: Optional[dict], *,
                               facts: Optional[dict] = None,
                               flags: Optional[dict] = None) -> Optional[dict]:
    """The pre-form package payload plus `becomes_hard_at_generation` - a COPY
    when there is anything to add, the same object otherwise (so a package with
    nothing to promote keeps its exact shape). `issue_registry.
    grouped_with_package_caps` tags the Review cards from it; every pre-form
    response and the resolve / reopen card come through here (one shape)."""
    if not isinstance(pkg, dict):
        return pkg
    items = becomes_hard_at_generation(session, facts=facts, flags=flags)
    if not items:
        return pkg
    return {**pkg, "becomes_hard_at_generation": items}


def stops_now(session: Optional[dict], form_ids: Optional[Iterable[str]] = None, *,
              pre_form: bool, facts: Optional[dict] = None,
              flags: Optional[dict] = None) -> Dict[str, Any]:
    """The stops as they stand on the STORED session (or on `facts` / `flags`
    when the caller holds newer ones it is about to store).

    `form_ids`: the forms cross-form rules are scoped to - the forms being
    generated, or before forms exist the recommended forms (the default).
    `pre_form`: True before any form is generated; cross-form hard stops are
    then warnings (C75). Required on purpose - a generation call that forgot
    to say so would silently demote its blockers.

    Returns:
      hard / soft          - the package scorer's stop lists (field-level +
                             document + picker + source + OCR + cross-form)
      form_hard / form_soft - what ONE form is scored with: field-level and
                             cross-document identity stops only (spec 10:
                             cross-form conflicts never cap an individual form)
      evaluate_hard / evaluate_soft - `evaluate_stops` alone, shaped
      cross_issues         - the cross-form issue dicts (demoted pre-form)
      form_ids             - the scope used
    """
    session = session or {}
    facts = session.get("facts") if facts is None else facts
    flags = session.get("flags") if flags is None else flags
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
    for _key, msg, blocking in underwriting_conflict_stops(underwriting, flags):
        (hard if blocking else soft).append(msg)
    for _key, msg, _carrier in source_conflict_stops(docs, underwriting):
        soft.append(msg)
    for _fld, msg in ocr_review_stops(docs, facts, session.get("underwriting_confirmations")):
        soft.append(msg)

    cross: List[dict] = []
    if not (pre_form and (session.get("integrity") or {}).get("review_required")):
        try:
            from services.cross_form_validator import defer_form_choices, split_cross_form_issues
            cross = cross_form_run(facts, flags, form_ids)
            if pre_form:
                # A check whose only fix is choosing a form is a form choice
                # before forms exist, not a stop (13 Oct 2026, the SQS without
                # forms) - outside both lists, marked `form_choice`.
                cross = defer_form_choices(cross)
            cf_hard, cf_soft, _adv = split_cross_form_issues(cross)
            if pre_form:
                # C75, in the pipeline's own order: the demoted hard stops
                # first, then the warnings not already listed.
                soft += list(cf_hard)
                soft += [m for m in cf_soft if m not in soft]
                cross = [dict(i, type="soft_warning") if i.get("type") == "hard_stop" else i
                         for i in cross]
            else:
                hard += list(cf_hard)
                soft += [m for m in cf_soft if m not in soft]
        except Exception as exc:                              # noqa: BLE001
            logger.warning("stops_now: cross-form validation skipped (%s)", exc)

    return {
        "hard": hard, "soft": soft,
        "form_hard": form_hard, "form_soft": form_soft,
        "evaluate_hard": list(ev_hard), "evaluate_soft": list(ev_soft),
        "cross_issues": cross,
        "form_ids": form_ids,
        "pre_form": bool(pre_form),
    }
