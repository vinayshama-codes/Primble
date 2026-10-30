"""session_documents.py - documents ADDED to, or CHANGED on, an existing package
(7 Oct 2026, Choice Electric #25).

Brent: "Unable to upload a narrative or additional supporting docs after form
generation." Until today the only upload created a NEW package, and the actions
that re-read the documents (reclassify, exclude, supporting only) refused once
forms existed (the 1 Oct lock): they re-ran the pipeline, which never touched
forms that already existed, so the forms - and their score - kept the old values.

THE DOOR - `remerge_package` - is the one way a package's DOCUMENT SET changes:
  * a document added (before or after forms), and
  * a document's type / exclusion / supporting-only changed after forms.

What it does, in order:
  1. Submission integrity over every active document (pure). A verdict needing
     review that the prior "continue anyway" does not cover, and that the
     producer did not confirm, is never merged silently: before forms the
     existing integrity review step takes over (the pipeline stores the
     verdict); after forms the change is refused (`IntegrityReviewRequired`,
     a 409) and NOTHING is stored.
  2. The re-merge - `extraction_pipeline._finalize_pipeline`, the same recipe
     as every re-run: every stored per-document fact (no OCR, no extraction
     call for an old document), human answers and person-saved tables carried,
     confirmations re-applied, Data Consistency re-assessed, the stops scored
     on the facts the row will hold (`stops_now.facts_as_stored`). A fact some
     document stated before and none states after (an excluded document's own
     values) is retracted - the facts write is additive and kept it otherwise.
  3. Once forms exist: the re-merge is computed WITHOUT being written
     (`persist=False`), every box whose ENGINE value moved is re-stamped
     (`arq_service._restamp_changed_boxes`, no own keys -> the engine's own
     "filled" label, never "producer"); a box a person typed and a box edited
     since generation stay. The engine is handed what generation stamps from:
     facts, flags merged over them, the package's form list - and on the
     before side the declarations index the forms were stamped with (rebuilt
     from the documents when production purged it). Moved boxes then get
     generation's own label rules; the PDF caches of changed forms are busted
     by the re-stamp. Then ONE write: the re-merged row, the forms, the offers,
     the index purged again - a failure before it changes nothing. Then the
     package is re-scored and its cards synced (`recalculate_session_scores`);
     field QA and the mapping check refresh; an audit event records it.
     Measured on the client's own package (Choice Electric, 7 documents, 6
     forms): adding the Package policy last, excluding the Excess or the Auto
     policy moved 57 / 6 / 76 boxes - exactly the boxes a from-scratch
     regeneration over the same documents changes, none missed, none wrong.
  4. Reports: boxes moved per form, applicant signatures the change made stale
     (the existing fingerprint rule - `signature_boxes.applicant_signature_state`),
     and the forms a newly evidenced line needs (`document_form_offers` on the
     session - OFFERED, never added; `add_offered_form` adds one on request).
  5. A document ADDED after forms is then read into the forms by the AI - the
     NEW document only (improving-ll.md C103, `run_new_document_fill`): the
     one shared gap fill generation uses, over the new document's text, then
     every post-fill guard exactly as at generation. A blank box it answers is
     filled; a box the AI filled at generation that it answers differently is
     a SUGGESTION, never overwritten; a box a person typed or a rule owns is
     never touched. Runs in the background after the add answers (it can take
     minutes), locks document changes while alive, and writes the forms once.
"""
from __future__ import annotations

import asyncio
import copy
import functools
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from repositories.session_repository import get_processing_session, upd_processing_session

logger = logging.getLogger(__name__)

# The session key holding the forms a newly evidenced line needs (never auto-added).
OFFERS_KEY = "document_form_offers"

# The declarations index - purged from the session after generation
# (form_routes.select_forms_bulk), rebuilt by every re-merge from the
# per-document copies the purge never touches.
_DEC_INDEX = "dec_page_entries"

_FAMILY_LABELS = {
    "general_liab": "General Liability",
    "auto": "Commercial Auto",
    "workers_comp": "Workers Compensation",
}


class IntegrityReviewRequired(Exception):
    """After forms exist, the changed document set names an insured nobody
    acknowledged. Carries the verdict and the documents that were NOT applied."""

    def __init__(self, verdict: dict, documents: List[str], other_insured: Optional[str] = None):
        super().__init__("submission_integrity_review_required")
        self.verdict = verdict or {}
        self.documents = list(documents or [])
        # The insured(s) the changed documents name that are NOT the package's
        # applicant (`other_insured_named`) - what the refusal names. None when
        # none can be told (the refusal then names nobody but the applicant's
        # rivals in the verdict).
        self.other_insured = other_insured


class AlreadyInPackage(Exception):
    """Every document added reads exactly like one the package already holds."""

    def __init__(self, documents: List[str]):
        super().__init__("documents_already_in_package")
        self.documents = list(documents or [])


class _HoldDone:
    """A progress reporter whose `done` waits for the door: the pipeline calls
    it when the row is stored, but after forms the door still re-stamps."""

    def __init__(self, inner: Any):
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def done(self, *_a, **_k) -> None:
        return None


# ── Small pure helpers ───────────────────────────────────────────────────────

def active_documents(docs: Iterable[dict]) -> List[dict]:
    """The pipeline's own rule: every document not excluded - or all of them
    when every one is excluded (a package is never scored empty)."""
    docs = [d for d in (docs or []) if isinstance(d, dict)]
    return [d for d in docs if not d.get("excluded")] or docs


def _states_a_value(value: Any) -> bool:
    if isinstance(value, dict) and "value" in value:
        value = value.get("value")
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip().lower() not in ("null", "none")
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def stated_fact_keys(docs: Iterable[dict]) -> set:
    """Public fact keys some ACTIVE document states a value for."""
    out: set = set()
    for d in active_documents(docs):
        for key, value in (d.get("facts") or {}).items():
            if key and not str(key).startswith("_") and _states_a_value(value):
                out.add(str(key))
    return out


def merge_only_keys(docs_before: Iterable[dict], docs_after: Iterable[dict]) -> set:
    """Facts the MERGE derives from the old document set and no longer derives
    from the new one (15 Oct 2026, live `0353c36b`): the Harborline 125 said
    "renewal", so the merge marked the umbrella's ended term as expiring
    (`renewal_lines_expiring`); excluding the 125 retracted "renewal" itself -
    a value it STATED - but kept the mark the merge had DERIVED from it, an 85
    cap with no document behind it. Both merges run on the current code over
    the documents alone (no person's answers), so their difference is exactly
    what the change of documents changed; `_document_retractions` still keeps
    a person's answer and anything the re-merge produces. Empty when the merge
    cannot run."""
    try:
        from services.extraction_service import merge_facts, select_primary_truth
    except Exception:                                          # noqa: BLE001
        return set()

    def _keys(docs: Iterable[dict]) -> set:
        active = [copy.deepcopy(d) for d in active_documents(docs)]
        if not active:
            return set()
        facts, _flags = merge_facts(active, select_primary_truth(active))
        return {str(k) for k, v in (facts or {}).items()
                if k and not str(k).startswith("_") and _states_a_value(v)}

    try:
        return _keys(docs_before) - _keys(docs_after)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: derived-fact comparison skipped: %s", ex)
        return set()


def _box_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def _family_label(family: str) -> str:
    return _FAMILY_LABELS.get(family) or str(family or "").replace("_", " ").title()


def _form_families(form_id: str) -> set:
    """The line families a SECTION form belongs to (by its base form - an
    instance like ACORD_131__excess is the 131's line). Empty for a package
    form (125, 101) or a form we cannot place."""
    try:
        from services.form_instances import base_form_id
        from services.lob_canon import canon_line
        from services.pdf_service import _SECTION_FORM_LINE_PHRASES
    except Exception:                                          # noqa: BLE001
        return set()
    phrases = _SECTION_FORM_LINE_PHRASES.get(base_form_id(form_id)) or ()
    return {f for f in (canon_line(p) for p in phrases) if f}


def _line_families(facts: Optional[dict], flags: Optional[dict]) -> set:
    try:
        from services.lob_canon import evidenced_line_families
        families, _rows = evidenced_line_families(facts or {}, flags or {})
        return set(families or ())
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: line families unavailable: %s", ex)
        return set()


def _form_label(form_id: str) -> str:
    try:
        from services.form_instances import instance_label
        return instance_label(form_id)
    except Exception:                                          # noqa: BLE001
        return str(form_id or "").replace("_", " ")


# ── 1. Submission integrity ──────────────────────────────────────────────────

def _override_covers(override: Optional[dict], verdict: dict) -> bool:
    """Every insured the verdict names was acknowledged by this override."""
    if not isinstance(override, dict):
        return False
    named = [e for e in (verdict.get("detected_entities") or []) if str(e or "").strip()]
    acknowledged = [e for e in (override.get("acknowledged_entities") or []) if str(e or "").strip()]
    if not named or not acknowledged:
        return False
    try:
        from services.normalization import same_entity_name
    except Exception:                                          # noqa: BLE001
        return False
    return all(any(same_entity_name(e, a) for a in acknowledged) for e in named)


def integrity_plan(prior_integrity: Optional[dict], docs_after: Iterable[dict], *,
                   confirm_same_insured: bool, user_id: str) -> dict:
    """How the changed document set goes through Submission Integrity:
    {verdict, override, review_needed, override_recorded}.

      * no review needed            -> the prior override (if any) is kept;
      * review needed, every named insured acknowledged by the prior
        "continue anyway"           -> kept, no review;
      * review needed, the producer confirmed these documents belong to this
        insured                     -> a NEW override record;
      * otherwise                   -> review needed (no override).
    """
    from services.submission_integrity import (
        assess_submission_integrity, build_override_record,
    )
    verdict = assess_submission_integrity(active_documents(docs_after))
    prior = prior_integrity if isinstance(prior_integrity, dict) else {}
    prior_override = prior.get("override") if prior.get("overridden") else None
    if not verdict.get("review_required"):
        return {"verdict": verdict, "override": prior_override,
                "review_needed": False, "override_recorded": False}
    if _override_covers(prior_override, verdict):
        return {"verdict": verdict, "override": prior_override,
                "review_needed": False, "override_recorded": False}
    if confirm_same_insured:
        return {"verdict": verdict,
                "override": build_override_record(user_id, verdict.get("detected_entities") or []),
                "review_needed": False, "override_recorded": True}
    return {"verdict": verdict, "override": None, "review_needed": True,
            "override_recorded": False}


def other_insured_named(session: Optional[dict], verdict: Optional[dict],
                        changed_documents: Iterable[dict] = ()) -> Optional[str]:
    """The insured(s) the CHANGED documents name that are not the package's
    applicant - judged over the FRESH verdict (the stored record does not hold
    them yet) by the Documents list's own rule (`document_tags`), the
    applicant decided without them. Failing that, every insured the verdict
    detected except the applicant. None when nobody can be named.

    15 Oct 2026, owner's run `0353c36b`: adding control_dec.pdf answered
    "These documents name a different insured (CHOICE ELECTRIC LLC, MERIDIAN
    FABRICATION INC)" - the verdict's whole entity list, the package's own
    applicant first."""
    try:
        from services.document_tags import (
            _same as _same_insured, document_insured_statuses, other_insured_of, package_applicant,
        )
        session = session if isinstance(session, dict) else {}
        verdict = verdict if isinstance(verdict, dict) else {}
        ids = [str(d.get("doc_id") or "").strip() for d in (changed_documents or ())
               if isinstance(d, dict)]
        ids = [i for i in ids if i]
        confirmations = session.get("underwriting_confirmations")
        consistency = session.get("underwriting_consistency")
        statuses = document_insured_statuses(verdict, confirmations, consistency, judge_without=ids)
        named = other_insured_of(statuses, ids)
        if named:
            return named
        applicant = (package_applicant(verdict, confirmations, consistency, judge_without=ids)
                     or {}).get("name")
        if not applicant:
            return None
        rivals = [str(e).strip() for e in (verdict.get("detected_entities") or [])
                  if str(e or "").strip() and not _same_insured(e, applicant)]
        return ", ".join(dict.fromkeys(rivals)) or None
    except Exception:                                          # noqa: BLE001
        return None


# ── 3. The forms: what the engine prints before and after ────────────────────

def _engine_view(facts: Optional[dict], flags: Optional[dict], package_ids: List[str],
                 dec_index: Any = None) -> dict:
    """The input generation stamps from (`form_service.process_single_form`):
    the facts with the flags merged over them, and the package's form list."""
    view = {**(facts or {}), **(flags or {})}
    if package_ids:
        view["_package_form_ids"] = list(package_ids)
    if dec_index and not view.get(_DEC_INDEX):
        view[_DEC_INDEX] = dec_index
    return view


def _generation_index(facts_before: dict, docs_before: List[dict]) -> Any:
    """The declarations index the forms were stamped with, when the session no
    longer holds it (production purges it after generation): rebuilt from the
    documents the forms reflect THROUGH THE MERGE ITSELF - one recipe, never a
    second copy of it. None when the session still holds it, or it cannot be
    rebuilt (both sides then read the same, and nothing moves for it)."""
    if (facts_before or {}).get(_DEC_INDEX):
        return None
    act = active_documents(docs_before)
    if not act:
        return None
    try:
        from services.extraction_service import merge_facts, select_primary_truth
        docs = copy.deepcopy(act)
        candidates = [d for d in docs if not d.get("supporting_only")] or docs
        merged, _flags = merge_facts(docs, select_primary_truth(candidates))
        return merged.get(_DEC_INDEX) or None
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: generation index not rebuilt (%s) - "
                       "index-dependent boxes keep their values", ex)
        return None


def _label_moved_boxes(generated: dict, moved: Dict[str, List[str]], facts_after: dict) -> None:
    """A moved box carries the label GENERATION would give it: the engine's
    "filled", then the fact-state labels (Not Applicable / explicit No /
    conflicted) and the "Please verify" of a calculated value - applied to the
    moved boxes only, so nothing a person or a later fix labelled is touched.
    The forms' missing-field highlights are refreshed, as a save refreshes them."""
    try:
        from services.form_instances import base_form_id, facts_for_form
        from services.pdf_service import (
            apply_acord125_missing_field_highlights, apply_acord126_missing_field_highlights,
            apply_acord140_missing_field_highlights, apply_derived_value_labels, apply_transcriber_labels,
            apply_fact_state_confidence_labels,
        )
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: label rules unavailable: %s", ex)
        return
    for fid, boxes in (moved or {}).items():
        form = generated.get(fid)
        if not isinstance(form, dict):
            continue
        state = form.get("field_state") or {}
        conf = dict(form.get("confidence") or {})
        base = base_form_id(fid)
        facts = facts_for_form(facts_after, fid)
        try:
            sub = {b: conf[b] for b in boxes
                   if conf.get(b) == "filled" and _box_text(state.get(b))}
            if sub:
                sub = apply_fact_state_confidence_labels(base, facts, state, sub)
                sub = apply_derived_value_labels(base, facts, state, sub)
                sub = apply_transcriber_labels(base, facts, state, sub)
                conf.update(sub)
            for highlight in (apply_acord125_missing_field_highlights,
                              apply_acord126_missing_field_highlights,
                              apply_acord140_missing_field_highlights):
                conf = highlight(base, facts, state, conf)
        except Exception as ex:                                # noqa: BLE001
            logger.warning("documents door: labels on %s skipped: %s", fid, ex)
            continue
        form["confidence"] = conf


def restamp_forms(generated: dict, facts_before: dict, facts_after: dict, *,
                  raw_text_before: Optional[str] = None,
                  raw_text_after: Optional[str] = None) -> Tuple[List[str], Dict[str, List[str]]]:
    """Move every box whose engine value changed (see the module note).
    Synchronous and CPU-bound - the door runs it in an executor. Returns
    (forms changed, {form: boxes whose printed value moved}).

    Premium boxes are non-fillable, so `_restamp_changed_boxes` skips them; the
    one door generation runs for them (`policy_lines.restamp_nonfillable_boxes`
    -> `pdf_service.nonfillable_box_value`) re-stamps the ones the change moved
    (7 Oct 2026: a document added after forms that brings a premium reaches the
    125 line / OTHER rows, the prior-carrier grid and the 130's WC premium).
    Each side reads its OWN documents' text: the presence backstop must judge
    the old value against what the forms were generated from."""
    from services.arq_service import _restamp_changed_boxes
    before = {fid: dict((fd.get("field_state") or fd.get("mapped") or {}))
              for fid, fd in (generated or {}).items() if isinstance(fd, dict)}
    touched = list(_restamp_changed_boxes(generated, facts_before, facts_after,
                                          own_keys=(), own_value=None, provenance="filled") or [])
    if raw_text_after is not None:
        try:
            from services.policy_lines import restamp_nonfillable_boxes
            _np = restamp_nonfillable_boxes(generated, facts_before, facts_after, raw_text_after,
                                            raw_text_before=raw_text_before) or []
            touched = list(dict.fromkeys(touched + list(_np)))
        except Exception as exc:                               # noqa: BLE001
            logger.warning("documents door: premium re-stamp skipped: %s", exc)
    moved: Dict[str, List[str]] = {}
    for fid in touched:
        now = (generated.get(fid) or {}).get("field_state") or {}
        was = before.get(fid) or {}
        boxes = sorted(b for b in set(now) | set(was) if _box_text(now.get(b)) != _box_text(was.get(b)))
        if boxes:
            moved[fid] = boxes
    _label_moved_boxes(generated, moved, facts_after)
    return touched, moved


# ── 4. Offers ────────────────────────────────────────────────────────────────

def form_offers(recommendations: Iterable[dict], package_ids: Iterable[str],
                recommended_before: Iterable[str], lines_before: set, lines_after: set,
                prior_offers: Iterable[dict] = ()) -> List[dict]:
    """The forms the changed documents call for that the package does not
    have - OFFERED, never added. A SECTION form whose line the documents now
    evidence and that the recommender now recommends (anything but its own
    "optional" tier), when either its line is newly evidenced or the
    recommendation is new (an excess layer's own 131). A previous offer stays
    while its line is still evidenced, its form is still missing and the
    recommender still recommends it (15 Oct 2026, live `0353c36b`: excluding
    the Harborline 125 kept "Add ACORD 186", which only that document's
    contractor facts had called for - the GL line was still there). With no
    recommendations to judge by, a previous offer is kept."""
    try:
        from services.form_service import TIER_OPTIONAL
    except Exception:                                          # noqa: BLE001
        TIER_OPTIONAL = "optional"
    recommendations = [r for r in (recommendations or ()) if isinstance(r, dict)]
    present = {str(f) for f in (package_ids or []) if f}
    before_ids = {str(f) for f in (recommended_before or []) if f}
    new_lines = set(lines_after or ()) - set(lines_before or ())
    judged = any(r.get("form_id") for r in recommendations)
    still_recommended = {str(r.get("form_id")) for r in recommendations
                         if r.get("form_id") and r.get("tier") != TIER_OPTIONAL}
    out: List[dict] = []
    seen: set = set()
    for offer in prior_offers or ():
        if not isinstance(offer, dict):
            continue
        fid = str(offer.get("form_id") or "")
        if fid and fid not in present and fid not in seen and offer.get("line") in (lines_after or ()) \
                and (not judged or fid in still_recommended):
            out.append(dict(offer))
            seen.add(fid)
    now = datetime.now(timezone.utc).isoformat()
    for rec in recommendations or ():
        if not isinstance(rec, dict):
            continue
        fid = str(rec.get("form_id") or "")
        if not fid or fid in present or fid in seen or rec.get("tier") == TIER_OPTIONAL:
            continue
        families = _form_families(fid) & set(lines_after or ())
        if not families:
            continue
        newly_evidenced = sorted(families & new_lines)
        if not newly_evidenced and fid in before_ids:
            continue
        line = (newly_evidenced or sorted(families))[0]
        out.append({
            "form_id": fid,
            "label": _form_label(fid),
            "form_name": str(rec.get("form_name") or _form_label(fid)),
            "line": line,
            "line_label": _family_label(line),
            "tier": str(rec.get("tier") or ""),
            "reason": str(rec.get("reason_label") or rec.get("trigger_reason") or ""),
            "offered_at": now,
        })
        seen.add(fid)
    return out


def forms_without_their_line(package_ids: Iterable[str], lines_before: set,
                             lines_after: set, recommended_before: Iterable[str] = (),
                             recommended_after: Iterable[str] = ()) -> List[dict]:
    """Forms in the package the documents stopped calling for (an excluded
    policy). Informational - nothing is removed:
      * a section form whose ONLY line is no longer evidenced (reason "line");
      * a second copy of a form (an instance, e.g. an excess layer's 131) the
        recommender asked for before the change and no longer does - its own
        policy left the package (reason "policy")."""
    try:
        from services.form_instances import is_instance
    except Exception:                                          # noqa: BLE001
        is_instance = lambda _f: False                         # noqa: E731
    gone = set(lines_before or ()) - set(lines_after or ())
    before_ids = {str(f) for f in (recommended_before or ()) if f}
    after_ids = {str(f) for f in (recommended_after or ()) if f}
    out = []
    for fid in package_ids or ():
        fams = _form_families(fid)
        if fams and fams <= gone:
            fam = sorted(fams)[0]
            out.append({"form_id": fid, "label": _form_label(fid), "line": fam,
                        "line_label": _family_label(fam), "reason": "line"})
        elif is_instance(fid) and fid in before_ids and fid not in after_ids:
            out.append({"form_id": fid, "label": _form_label(fid), "line": "",
                        "line_label": "", "reason": "policy"})
    return out


# ── 2 + 3. THE DOOR ──────────────────────────────────────────────────────────

async def remerge_package(
    session: dict,
    session_id: str,
    docs_before: List[dict],
    docs_after: List[dict],
    *,
    user_id: Any,
    reason: str,
    changed_documents: Iterable[dict] = (),
    confirm_same_insured: bool = False,
    purge_dec_index: bool = True,
    reporter: Any = None,
) -> dict:
    """Re-merge the package after its document set changed - see the module
    note. Returns the pipeline's result plus `door` (what moved). Raises
    `IntegrityReviewRequired` after forms when a new insured is unacknowledged."""
    session = session if isinstance(session, dict) else {}
    uid = str(user_id or session.get("user_id") or "")
    changed_names = [str(d.get("filename") or "") for d in (changed_documents or ())
                     if isinstance(d, dict)]
    plan = integrity_plan(session.get("integrity"), docs_after,
                          confirm_same_insured=confirm_same_insured, user_id=uid)
    forms_exist = bool(session.get("generated_forms"))
    if forms_exist and plan["review_needed"]:
        raise IntegrityReviewRequired(plan["verdict"], changed_names,
                                      other_insured=other_insured_named(
                                          session, plan["verdict"], changed_documents))

    from services.extraction_pipeline import _finalize_pipeline
    # What a document STATED and no active document states any more, and what
    # the merge DERIVED from the old set and no longer derives (a renewal mark
    # the excluded document caused) - `_document_retractions` keeps a person's
    # answer and anything the re-merge still produces.
    loop0 = asyncio.get_event_loop()
    derived_gone = await loop0.run_in_executor(
        None, functools.partial(merge_only_keys, docs_before, docs_after))
    retract = sorted((stated_fact_keys(docs_before) - stated_fact_keys(docs_after)) | set(derived_gone))
    common = dict(
        session_id=session_id,
        integrity_override=plan["override"],
        confirmations=session.get("underwriting_confirmations") or {},
        client_answer_conflicts=session.get("client_answer_conflicts") or {},
        prior_facts=session.get("facts") or {},
        prior_flags=session.get("flags") or {},
        progress_reporter=_HoldDone(reporter) if reporter is not None else None,
        retract_document_keys=retract,
    )
    door: Dict[str, Any] = {
        "reason": reason,
        "forms_exist": forms_exist,
        "integrity_review_required": False,
        "integrity_override_recorded": bool(plan["override_recorded"]),
        "integrity_verdict": plan["verdict"],
        "forms_updated": [],
        "boxes_updated": 0,
        "boxes_by_form": {},
        "stale_signatures": [],
        "form_offers": [],
        "forms_without_line": [],
        "retracted_facts": [],
        "boxes_taken_back": 0,
        "held_back_dropped": 0,
        "score_before": None,
        "score_after": None,
    }

    if not forms_exist:
        # Before forms: exactly a pre-form re-run of the stored documents (no
        # probe - it would send every document's text to the model again).
        result = await _finalize_pipeline(docs_after, uid, **common)
        door["integrity_review_required"] = bool((result.get("integrity") or {}).get("review_required"))
        door["retracted_facts"] = list(result.get("retracted_facts") or [])
        result["door"] = door
        return result

    # ── After forms ──────────────────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    facts_before = copy.deepcopy(session.get("facts") or {})
    flags_before = copy.deepcopy(session.get("flags") or {})
    recommended_before = [str(r.get("form_id")) for r in (session.get("recommendations") or [])
                          if isinstance(r, dict) and r.get("form_id")]
    lines_before = _line_families(facts_before, flags_before)
    generation_index = await loop.run_in_executor(
        None, functools.partial(_generation_index, facts_before, docs_before))

    if reporter is not None:
        try:
            await reporter.package_phase("normalized", "Re-reading the package with your documents…")
        except Exception:                                      # noqa: BLE001
            pass
    # The re-merge, NOT written yet: its row update is written below in ONE
    # update together with the re-stamped forms - a failure before that write
    # leaves the package exactly as it was, never new facts beside old forms.
    result = await _finalize_pipeline(docs_after, uid, keep_forms=True, persist=False, **common)
    door["retracted_facts"] = list(result.get("retracted_facts") or [])
    row_update = dict(result.get("session_payload") or {})
    row_deletes = list(result.get("delete_facts") or [])
    # The stop caches the pipeline built are the PRE-FORM view (cross-form hard
    # stops demoted, scoped to the recommended forms). After generation the
    # re-score below rebuilds them for the generated forms; if it ever failed,
    # the previous post-generation lists stay rather than a demoted copy.
    for _pre_form_cache in ("hard_stops", "soft_stops", "cross_form_issues"):
        row_update.pop(_pre_form_cache, None)

    # The facts the row will hold (the store's additive write, then the
    # retractions) - exactly what the pipeline scored its stops on.
    from services.stops_now import facts_as_stored
    facts_after = copy.deepcopy(facts_as_stored(session.get("facts") or {},
                                                row_update.get("facts") or {}, row_deletes))
    flags_after = row_update.get("flags") or {}
    generated = copy.deepcopy(session.get("generated_forms") or {})
    try:
        from services.form_service import package_form_ids
        package_ids = package_form_ids(session)
    except Exception:                                          # noqa: BLE001
        package_ids = list(session.get("selected_form_ids") or []) or list(generated)
    package_ids = list(dict.fromkeys(list(package_ids) + [f for f in generated if f not in package_ids]))

    try:
        from services.signature_boxes import STATE_SIGNED, STATE_STALE, applicant_signature_state
    except Exception:                                          # noqa: BLE001
        applicant_signature_state, STATE_SIGNED, STATE_STALE = None, "signed", "stale"
    signed_before = {fid: applicant_signature_state(fd) if applicant_signature_state else None
                     for fid, fd in generated.items()}

    if reporter is not None:
        try:
            await reporter.package_phase("scored", "Updating your forms…")
        except Exception:                                      # noqa: BLE001
            pass
    before_view = _engine_view(facts_before, flags_before, package_ids, generation_index)
    after_view = _engine_view(facts_after, flags_after, package_ids)
    _text_before = "\n".join(str(d.get("text") or "") for d in active_documents(docs_before))
    _text_after = "\n".join(str(d.get("text") or "") for d in active_documents(docs_after))
    touched, moved = await loop.run_in_executor(
        None, functools.partial(restamp_forms, generated, before_view, after_view,
                                raw_text_before=_text_before, raw_text_after=_text_after))

    # What the AI reading of a document that has now LEFT the package wrote or
    # held back is taken back too (see `take_back_document_fills`).
    receipts_before = [r for r in (session.get(RECEIPTS_KEY) or []) if isinstance(r, dict)]
    taken, receipts_left, held_dropped = take_back_document_fills(generated, receipts_before, docs_after)
    for fid, boxes in taken.items():
        if fid not in touched:
            touched.append(fid)
        if boxes:
            moved[fid] = sorted(set(moved.get(fid) or []) | set(boxes))
    door["boxes_taken_back"] = sum(len(v) for v in taken.values())
    door["held_back_dropped"] = held_dropped
    # A document still in the package that said something ELSE for a box just
    # taken back keeps its say: its suggestion now reads against a blank box.
    suggestions_after = offers_on_emptied_boxes(session.get(SUGGESTIONS_KEY) or [], taken)

    stale = []
    for fid, fd in generated.items():
        if signed_before.get(fid) == STATE_SIGNED and applicant_signature_state \
                and applicant_signature_state(fd) == STATE_STALE:
            stale.append({"form_id": fid, "label": _form_label(fid)})

    lines_after = _line_families(facts_after, flags_after)
    offers = form_offers(result.get("recommendations") or [], package_ids, recommended_before,
                         lines_before, lines_after, prior_offers=session.get(OFFERS_KEY) or [])

    # ONE write: the re-merged row, the re-stamped forms, the offers - and the
    # declarations index purged again (it was rebuilt by the re-merge).
    row_update[OFFERS_KEY] = offers
    if receipts_left != receipts_before:
        row_update[RECEIPTS_KEY] = receipts_left
    if suggestions_after is not None:
        row_update[SUGGESTIONS_KEY] = suggestions_after
    if touched:
        row_update["generated_forms"] = {fid: generated[fid] for fid in touched}
    if purge_dec_index and _DEC_INDEX not in row_deletes:
        row_deletes.append(_DEC_INDEX)
    await upd_processing_session(session_id, row_update, delete_facts=row_deletes or None)
    # Written - the caller never needs the raw row update (every document's text).
    result.pop("session_payload", None)
    result.pop("delete_facts", None)

    # Scores, the stop cache, the issue list and the stored cards follow the
    # forms - the one post-generation recalculation every answer goes through.
    try:
        from services.arq_service import recalculate_session_scores
        impact = await recalculate_session_scores(session_id) or {}
    except Exception as ex:                                    # noqa: BLE001
        logger.error("documents door: re-score failed [session=%s]: %s", session_id, ex,
                     exc_info=True)
        impact = {}
    await _refresh_after_restamp(session_id, uid)

    door.update({
        "forms_updated": list(moved.keys()),
        "boxes_updated": sum(len(v) for v in moved.values()),
        "boxes_by_form": {fid: len(v) for fid, v in moved.items()},
        "stale_signatures": stale,
        "form_offers": offers,
        "forms_without_line": forms_without_their_line(
            package_ids, lines_before, lines_after, recommended_before,
            [r.get("form_id") for r in (result.get("recommendations") or []) if isinstance(r, dict)]),
        "score_before": impact.get("score_before"),
        "score_after": impact.get("score_after"),
    })
    try:
        from services.audit_service import log_audit_event
        await log_audit_event(session_id, uid, "forms_updated_from_documents", {
            "reason": reason,
            "documents": changed_names,
            "forms_updated": door["forms_updated"],
            "boxes_updated": door["boxes_updated"],
            "stale_signatures": [s["form_id"] for s in stale],
            "forms_offered": [o["form_id"] for o in offers],
            "facts_retracted": door["retracted_facts"],
            "boxes_taken_back": door["boxes_taken_back"],
            "held_back_dropped": door["held_back_dropped"],
        })
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: audit event failed: %s", ex)
    logger.info("documents door: session=%s reason=%s forms=%s boxes=%d stale=%s offers=%s",
                session_id, reason, door["forms_updated"], door["boxes_updated"],
                [s["form_id"] for s in stale], [o["form_id"] for o in offers])
    result["door"] = door
    return result


async def _refresh_after_restamp(session_id: str, user_id: str) -> None:
    """What a save refreshes after the forms change (`form_routes.update_pdf`):
    the stamped-value consistency advisory beside the cross-form issues, field
    QA and the field-mapping warnings. Each step is best-effort."""
    try:
        sess = await get_processing_session(session_id)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: refresh skipped (%s)", ex)
        return
    generated = sess.get("generated_forms") or {}
    facts = sess.get("facts") or {}
    confirmations = sess.get("underwriting_confirmations") or {}
    try:
        from services.underwriting_consistency import (
            stamp_mismatch_issues, verify_stamped_consistency,
        )
        check = verify_stamped_consistency(generated, merged_facts=facts,
                                           confirmations=confirmations)
        issues = stamp_mismatch_issues(check)
        update: Dict[str, Any] = {"underwriting_stamp_consistency": check}
        if issues:
            update["cross_issues_last"] = list(sess.get("cross_issues_last") or []) + list(issues)
        await upd_processing_session(session_id, update)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: stamped-consistency check skipped: %s", ex)
    try:
        from config.settings import ENABLE_FIELD_QA
        from services.audit_service import run_and_log_field_mapping_check, run_and_log_field_qa
        await run_and_log_field_qa(session_id, user_id, generated, facts, confirmations,
                                   ENABLE_FIELD_QA, flags=sess.get("flags") or {},
                                   docs=sess.get("docs"))
        await run_and_log_field_mapping_check(session_id, user_id, generated, facts, confirmations)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("documents door: field QA refresh skipped: %s", ex)


# ── The two entry points ─────────────────────────────────────────────────────
#
# ONE CHANGE AT A TIME PER PACKAGE. Each change writes the package's whole
# document list, so two at once (an add still running in one tab, an exclude
# in another) would drop the first one's document. The entry points take the
# package's id, wait for any other change to it in this process, and only then
# read the row they change - never a copy read before they waited.

_LOCKS: Dict[str, Tuple[Any, asyncio.Lock]] = {}


class _Serialized:
    """`async with _Serialized(session_id):` - one documents change at a time
    per package, in this process. The lock belongs to the running event loop;
    the map entry is dropped when nobody else is waiting."""

    def __init__(self, session_id: str):
        self.key = str(session_id)
        self.entry = None

    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        entry = _LOCKS.get(self.key)
        if entry is None or entry[0] is not loop:
            entry = (loop, asyncio.Lock())
            _LOCKS[self.key] = entry
        self.entry = entry
        await entry[1].acquire()
        return self

    async def __aexit__(self, *_exc):
        lock = self.entry[1]
        lock.release()
        if not lock.locked() and not getattr(lock, "_waiters", None) \
                and _LOCKS.get(self.key) is self.entry:
            _LOCKS.pop(self.key, None)
        return False


async def add_documents(
    session_id: str,
    new_docs: List[dict],
    *,
    user_id: Any,
    confirm_same_insured: bool = False,
    purge_dec_index: bool = True,
    reporter: Any = None,
) -> dict:
    """Append processed documents (from `extraction_pipeline.extract_document`)
    to the package and re-merge it through the door. A document reading
    exactly like one the package now holds (two uploads of one file racing)
    is skipped - it would only vote twice in the merge; all of them skipped
    raises `AlreadyInPackage`."""
    from services.extraction_pipeline import stored_text_key
    async with _Serialized(session_id):
        session = await get_processing_session(session_id)
        stored = [d for d in (session.get("docs") or []) if isinstance(d, dict)]
        held = {stored_text_key(d) for d in stored} - {""}
        adding, skipped = [], []
        for d in new_docs or []:
            if not isinstance(d, dict):
                continue
            key = stored_text_key(d)
            if key and key in held:
                skipped.append(str(d.get("filename") or ""))
                continue
            held.add(key)
            adding.append(d)
        if not adding:
            raise AlreadyInPackage(skipped)
        result = await remerge_package(
            session, session_id, stored, list(stored) + adding,
            user_id=user_id, reason="documents_added", changed_documents=adding,
            confirm_same_insured=confirm_same_insured, purge_dec_index=purge_dec_index,
            reporter=reporter,
        )
        result.setdefault("door", {})["duplicates_skipped"] = skipped
        result["documents_added"] = adding
        return result


async def change_document(
    session_id: str,
    *,
    doc_id: str,
    action: str,
    new_doc_type: Optional[str] = None,
    user_id: Any = None,
    confirm_same_insured: bool = False,
    purge_dec_index: bool = True,
) -> dict:
    """A document's type / exclusion / supporting-only changed AFTER forms:
    the same change `reclassify_document` applies (`apply_document_action`),
    then the door. Raises ValueError(code) like the pre-form path."""
    async with _Serialized(session_id):
        session = await get_processing_session(session_id)
        stored = [d for d in (session.get("docs") or []) if isinstance(d, dict)]
        if not stored:
            raise ValueError("reclassify_no_docs")
        from services.extraction_pipeline import apply_document_action
        docs_after = [dict(d) for d in stored]        # the stored dicts stay as they were
        target, prev_type = await apply_document_action(docs_after, doc_id, action, new_doc_type)
        logger.info("documents door: change doc=%s action=%s %s->%s (session=%s)",
                    doc_id, action, prev_type, target.get("doc_type"), session_id)
        result = await remerge_package(
            session, session_id, stored, docs_after,
            user_id=user_id, reason=f"document_{action}", changed_documents=[target],
            confirm_same_insured=confirm_same_insured, purge_dec_index=purge_dec_index,
        )
    result["reclassified"] = {
        "doc_id": str(doc_id),
        "action": action,
        "previous_doc_type": prev_type,
        "new_doc_type": target.get("doc_type"),
    }
    return result


async def add_offered_form(session_id: str, form_id: str) -> Tuple[str, Dict[str, Any]]:
    """Add ONE form the door offered (`document_form_offers`) - through the
    one add-form door (`form_addition.add_form_to_session`). The SERVER
    decides: a form the stored offers do not name is refused. The offer is
    retired once the form is in the package. Returns (outcome, payload)."""
    from services.form_addition import OK, ALREADY_PRESENT, add_form_to_session
    session = await get_processing_session(session_id)
    offers = [o for o in (session.get(OFFERS_KEY) or []) if isinstance(o, dict)]
    form_id = str(form_id or "").strip()
    if not form_id or form_id not in {str(o.get("form_id")) for o in offers}:
        return "not_offered", {}
    outcome, payload = await add_form_to_session(session_id, form_id, enforce_requested=False)
    if outcome in (OK, ALREADY_PRESENT):
        await upd_processing_session(session_id, {
            OFFERS_KEY: [o for o in offers if str(o.get("form_id")) != form_id]})
    return outcome, payload


# ── 5. The AI reading of a document added AFTER forms (C103, 7 Oct 2026) ─────
#
# Until today an added document reached the forms only through its FACTS: the
# door above re-stamps the boxes a deterministic rule prints, and nothing asked
# the AI the questions generation asks it (the narrative's "how many years in
# business", a loss run's "any losses?" ...). Now, once the door has answered,
# the SAME shared gap fill generation runs (`form_service.shared_gap_fill`:
# line scopes, private layer groups, the cross-form Yes/No reconciliation) is
# run with the NEW documents as its only text - the package's merged facts are
# the facts block, as at generation. An old document is never sent again.
# Every answer then goes through `map_facts_to_form(..., pre_filled_gpt=...)`
# - every post-fill guard, the evidence gate and the evidence judge (C97), the
# ungrounded-identifier drop - with the WHOLE package's text as the presence
# backstop, exactly as generation stamps. What the answers change is measured
# against the same stamp with no answers (the baseline), so a box moves only
# because the new document answered it. Then, box by box:
#   * blank now (nobody typed it, no rule owns it)  -> filled, with the label
#     generation gives an AI value ("ai_verified" / "low_confidence");
#   * filled by the AI before, answered DIFFERENTLY now -> a suggestion
#     (`SUGGESTIONS_KEY`), never an overwrite - the producer chooses
#     (`needs_attention.document_suggestion_rows`; "Use this value" goes through
#     the producer-edit door, `/api/update-pdf`, and is labelled "producer" like
#     any value a person chose; "Keep current" retires it);
#   * typed by a person (producer / client, or edited since generation) or
#     printed by a rule -> never touched;
#   * the new document names ANOTHER insured than the package's applicant
#     (`document_tags`, the Documents list's own rule, the applicant decided
#     without the new documents; 14 Oct 2026) -> the AI writes nothing: every
#     value it offers that the document prints - a blank box's too - is a
#     suggestion. NOT covered here: the documents door above has already
#     merged that document's facts and re-stamped the boxes they move
#     (`insured_scope` scopes only the applicant's own identity facts) - on
#     `f83757cf` that door printed MERIDIAN's carrier, policy numbers, mortgagee
#     and vehicle on the Choice Electric forms (57 boxes); an owner decision.
# Crash-safe: the forms are written ONCE, at the end, after re-checking every
# box against the row as it stands then (a box a person typed meanwhile wins).
# A failure before that write leaves the forms exactly as the door left them
# and the status says so. Kill switch: NEW_DOCUMENT_AI_FILL=0.

FILL_KEY = "document_ai_fill"                    # = generation_state.DOCUMENT_FILL_KEY
FILL_BEAT_KEY = "document_ai_fill_beat_at"       # = generation_state.DOCUMENT_FILL_BEAT_KEY
SUGGESTIONS_KEY = "document_fill_suggestions"
# Every box the AI reading of an added document WROTE (15 Oct 2026): which
# document, and a hash of the value (never the value - the box holds it), so
# excluding that document takes the box back (`take_back_document_fills`).
RECEIPTS_KEY = "document_fill_receipts"
FILL_RUNNING, FILL_DONE, FILL_FAILED, FILL_OFF = "running", "done", "failed", "off"
FILL_FAILED_TEXT = ("Reading the new document into your forms did not finish. Your forms keep "
                    "the values its facts gave them.")
from services.fact_state import PERSON_BOX_LABELS as _PERSON_LABELS   # noqa: E402 - the one door
# The labels generation gives a gap-filled value (`map_facts_to_form`).
_AI_LABELS = frozenset({"ai_verified", "low_confidence"})
_TASKS: set = set()


def ai_fill_enabled() -> bool:
    """NEW_DOCUMENT_AI_FILL (default on). Read at call time."""
    return os.getenv("NEW_DOCUMENT_AI_FILL", "1").strip().lower() not in ("0", "false", "no", "off")


def _same(a: Any, b: Any) -> bool:
    return _box_text(a).casefold() == _box_text(b).casefold()


def _box_value(form: Optional[dict], field: str) -> Any:
    form = form if isinstance(form, dict) else {}
    state = form.get("field_state")
    if not isinstance(state, dict):
        state = form.get("mapped") or {}
    return state.get(field)


def box_owner(form: Optional[dict], field: str) -> str:
    """Who a generated box belongs to: "person" (a producer / client value, or
    a box edited since generation), "rule" (a value a deterministic rule
    printed), "ai" (a value the AI filled) or "blank" (nobody's yet)."""
    form = form if isinstance(form, dict) else {}
    label = (form.get("confidence") or {}).get(field)
    if label in _PERSON_LABELS or field in set(form.get("client_filled_fields") or []):
        return "person"
    state = form.get("field_state")
    mapped = form.get("mapped") or {}
    # An edit is saved into `field_state`; `mapped` is what generation stamped.
    # The documents door re-stamps `field_state` only, always labelled
    # "filled" - so a difference under any other label (or none, a cleared
    # box) is a person's, whatever label an older save left behind.
    if isinstance(state, dict) and label != "filled" and not _same(state.get(field), mapped.get(field)):
        return "person"
    if not _box_text(_box_value(form, field)):
        return "blank"
    return "ai" if label in _AI_LABELS else "rule"


def review_counts(page: Optional[dict]) -> dict:
    """The open items the review page shows: its grouped view's own `counts`
    (the numbers the Hard Stops / Warnings sections print - the stop arrays
    as the fallback, as `packageIssueCounts` reads them) and the Data
    Consistency values that need confirming (status "conflict")."""
    page = page if isinstance(page, dict) else {}
    # Every shape is checked: the add route builds its answer from this after
    # the documents door has already changed the package - a malformed page
    # must never turn that answer into a 500.
    grouped = page.get("grouped_issues")
    counts = grouped.get("counts") if isinstance(grouped, dict) else None
    counts = counts if isinstance(counts, dict) else {}
    hard, warn = counts.get("hard_stops"), counts.get("warnings")
    if not isinstance(hard, int) or not isinstance(warn, int):
        hs, ss = page.get("hard_stops"), page.get("soft_stops")
        hard = len(hs) if isinstance(hs, list) else 0
        warn = len(ss) if isinstance(ss, list) else 0
    uc = page.get("underwriting_consistency")
    fields = uc.get("fields") if isinstance(uc, dict) else None
    dc = sum(1 for f in (fields if isinstance(fields, list) else [])
             if isinstance(f, dict) and f.get("status") == "conflict")
    return {"hard_stops": int(hard), "warnings": int(warn), "data_consistency": int(dc)}


_REVIEW_KINDS = ("hard_stops", "warnings", "data_consistency")
# Codes the grouped view gives a sentence no rule claims - two such items are
# never "the same rule under new words".
_CATCH_ALL_CODES = frozenset({"uncovered_hard_stop", "uncovered_soft_stop", "uncategorized"})


def _cluster_items(clusters: Any) -> List[Tuple[str, Optional[str]]]:
    """(issue id, rule code) for every item a list of grouped-view clusters
    lists - each item's own id, the cluster's when it carries no items (the
    review page's `clusterItems` rule). An item the view sent without an id
    gets the one the view stamps (`issue_registry.issue_id_for`)."""
    out: List[Tuple[str, Optional[str]]] = []
    for cluster in clusters if isinstance(clusters, list) else []:
        if not isinstance(cluster, dict):
            continue
        raw = cluster.get("items")
        items = [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []
        for item in items or [cluster]:
            iid = str(item.get("issue_id") or "").strip()
            if not iid:
                message = str(item.get("message") or item.get("primary_message") or "").strip()
                if not message:
                    continue
                try:
                    from services.issue_registry import issue_id_for
                    forms = item.get("forms") if isinstance(item.get("forms"), list) else []
                    iid = issue_id_for(message, [str(f) for f in forms])
                except Exception:                              # noqa: BLE001
                    continue
            code = str(item.get("code") or "").strip()
            out.append((iid, code if code and code not in _CATCH_ALL_CODES else None))
    return out


def _package_score(page: dict) -> Optional[int]:
    pkg = page.get("package_sqs")
    score = pkg.get("package_sqs_score") if isinstance(pkg, dict) else None
    if isinstance(score, bool):
        return None
    try:
        return int(score) if score is not None else None
    except (TypeError, ValueError):
        return None


def review_snapshot(page: Optional[dict], dismissed: Iterable[str] = ()) -> Optional[dict]:
    """The review page's open items BY IDENTITY, plus the package score
    (Choice Electric #25, 14 Oct 2026). `review_counts` plus:
      * `ids`: the hard stops and warnings by the issue id the review page
        files their statuses under (each grouped-view item's `issue_id`),
        minus the ones it hides (`dismissed` - a dismissed item leaves its
        list; a resolved one that still fires stays listed); the Data
        Consistency values that need confirming by fact key;
      * `rules`: each listed hard stop's / warning's rule code, so a rule
        that fires under NEW words (a part-fixed card renames what is still
        missing - a new id) is not read as a new item (`new_on_review`);
      * `score`: the package score the page shows.
    None for a page that carries no review data at all (it could not be
    built) - "unknown", never "nothing open".
    Counting alone reads a new warning plus one that went away as "No new
    issues". On `f83757cf` (14 Oct, 00:36 UTC) adding the Business Auto Policy
    raised "Driver schedule not provided" (score 99 -> 85, its ceiling reason)
    in the same recalculation that retired the one warning the page held
    ("Employee Count appears inconsistently across generated forms") - one in,
    one out, and the screen said "No new issues on the review page". Replayed
    from the stored rows, the identity diff says "New on the review page: 1
    warning. Your score went from 99 to 85." instead."""
    if not isinstance(page, dict):
        return None
    grouped = page.get("grouped_issues")
    has_view = isinstance(grouped, dict) and (isinstance(grouped.get("hard_stops"), list)
                                              or isinstance(grouped.get("warnings"), dict))
    if not has_view and not isinstance(grouped, dict) \
            and not isinstance(page.get("hard_stops"), list) and not isinstance(page.get("soft_stops"), list):
        return None
    hide = {str(i) for i in (dismissed or ()) if i}
    out: dict = dict(review_counts(page))
    if has_view:
        warnings = grouped.get("warnings") if isinstance(grouped.get("warnings"), dict) else {}
        warning_clusters = [c for tier in warnings.values() if isinstance(tier, list) for c in tier]
        hard = [(i, r) for i, r in _cluster_items(grouped.get("hard_stops")) if i not in hide]
        warn = [(i, r) for i, r in _cluster_items(warning_clusters) if i not in hide]
        fields = (page.get("underwriting_consistency") or {}).get("fields") \
            if isinstance(page.get("underwriting_consistency"), dict) else None
        out["ids"] = {
            "hard_stops": sorted({i for i, _r in hard}),
            "warnings": sorted({i for i, _r in warn}),
            "data_consistency": sorted({str(f.get("fact_key")) for f in (fields if isinstance(fields, list) else [])
                                        if isinstance(f, dict) and f.get("status") == "conflict"
                                        and f.get("fact_key")}),
        }
        out["rules"] = {i: r for i, r in hard + warn if r}
    score = _package_score(page)
    if score is not None:
        out["score"] = score
    return out


def _new_by_identity(before_ids: Iterable[str], after_ids: Iterable[str],
                     before_rules: dict, after_rules: dict) -> int:
    """Items listed after that were not listed before. One that is NEW only
    in its words - its rule's item went away in the same change - is the same
    item renamed (`fixProgress.fixLeftOpen`'s rule on the review page), one
    pair per item that went away."""
    before_set, after_set = set(before_ids or ()), set(after_ids or ())
    gone: Dict[str, int] = {}
    for iid in before_set - after_set:
        rule = (before_rules or {}).get(iid)
        if rule:
            gone[rule] = gone.get(rule, 0) + 1
    new = 0
    for iid in sorted(after_set - before_set):
        rule = (after_rules or {}).get(iid)
        if rule and gone.get(rule, 0) > 0:
            gone[rule] -= 1
            continue
        new += 1
    return new


def new_on_review(before: Optional[dict], after: Optional[dict]) -> Optional[dict]:
    """NEW open items on the review page. Both sides carry `ids`
    (`review_snapshot`): the items listed after that were not listed before -
    a swap (one new, one gone) is one new item, never "nothing new"; a rule
    firing under new words is not new. An older side without ids (a fill
    started before this change): after minus before, never below 0. Adds
    `score_before` / `score_after` when both sides know the package score.
    None when either side is unknown."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    b_ids, a_ids = before.get("ids"), after.get("ids")
    if isinstance(b_ids, dict) and isinstance(a_ids, dict):
        b_rules = before.get("rules") if isinstance(before.get("rules"), dict) else {}
        a_rules = after.get("rules") if isinstance(after.get("rules"), dict) else {}
        out = {k: _new_by_identity(b_ids.get(k) or [], a_ids.get(k) or [],
                                   b_rules if k != "data_consistency" else {},
                                   a_rules if k != "data_consistency" else {})
               for k in _REVIEW_KINDS}
    else:
        def _n(side: dict, k: str) -> int:
            try:
                return int(side.get(k) or 0)
            except (TypeError, ValueError):
                return 0
        out = {k: max(0, _n(after, k) - _n(before, k)) for k in _REVIEW_KINDS}
    out["total"] = sum(out.values())
    sb, sa = before.get("score"), after.get("score")
    if isinstance(sb, int) and isinstance(sa, int) and not isinstance(sb, bool) and not isinstance(sa, bool):
        out["score_before"], out["score_after"] = sb, sa
    return out


def _generation_schema(session: dict, form_id: str) -> dict:
    """The schema generation stamps a form with - read from its TEMPLATE in
    layout order (`extract_form_schema`), never the JSONB-sorted copy on the
    session row (position-based pairing on it is wrong). The stored copy only
    when the template cannot be found."""
    from services import form_instances as _fi
    from services.pdf_service import extract_form_schema
    from config.settings import TEMPLATE_DIR
    fd = (session.get("generated_forms") or {}).get(form_id) or {}
    meta = fd.get("form") if isinstance(fd.get("form"), dict) else None
    if not (meta or {}).get("template_file"):
        meta = _fi.form_meta_for(session.get("all_forms") or [], form_id, session.get("facts") or {})
    tpl = os.path.join(TEMPLATE_DIR, (meta or {}).get("template_file") or "")
    if (meta or {}).get("template_file") and os.path.exists(tpl):
        return extract_form_schema(tpl, form_id=_fi.base_form_id(form_id))
    return fd.get("schema") if isinstance(fd.get("schema"), dict) else {}


def _stamp_with_answers(session: dict, form_id: str, answers: dict, raw_text: str,
                        schema: dict) -> Tuple[dict, dict, list]:
    """One form stamped as `form_service.process_single_form` stamps it, with
    `answers` as the shared gap fill's answers. No other model call: the
    whole-document umbrella-period probe is skipped (`allow_llm=False` - it
    would send every document again); the evidence judge, which reads only the
    answers' own quotes, still runs."""
    from services import form_instances as _fi
    from services.form_service import package_form_ids
    from services.pdf_service import map_facts_to_form
    facts = {**(session.get("facts") or {}), **(session.get("flags") or {})}
    try:
        facts["_package_form_ids"] = package_form_ids(session, form_id)
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("document fill: package form list unavailable: %s", ex)
    # The package's documents ride the stamping facts EXACTLY as generation
    # attaches them (`form_service.process_single_form`). Without them every
    # scoped guard stands down: a coverage section no document carries
    # (spoilage, blanket), a value printed only by ANOTHER policy's documents.
    # Live 8 Oct 2026 (505bf394): adding the Business Auto Policy wrote 17
    # wrong ACORD 140 boxes - the buildings' limits as spoilage and blanket
    # limits, the WC credit as a guard, the vehicle garaging as the building's
    # front exposure - that generation's own stamp had refused.
    try:
        from services.scoped_evidence import attach_documents
        attach_documents(facts, session.get("docs") or [])
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("document fill: documents not attached: %s", ex)
    guard: list = []
    mapped, conf = map_facts_to_form(
        _fi.facts_for_form(facts, form_id), schema, form_id=_fi.base_form_id(form_id),
        raw_text=raw_text, pre_filled_gpt=answers, guard_report=guard, allow_llm=False)
    return mapped or {}, conf or {}, guard


def _new_document_answers(session: dict, new_docs: List[dict], form_ids: List[str]) -> Dict[str, dict]:
    """THE call (C103): the one shared gap fill, with the NEW documents as the
    package's only documents - its text, its line scopes and every layer's own
    text come from them alone. Facts and flags are the package's."""
    from services.form_service import shared_gap_fill
    view = dict(session)
    view["docs"] = [dict(d, excluded=False) for d in new_docs]
    return shared_gap_fill(view, list(form_ids)) or {}


def _words_only(value: Any) -> str:
    """A box's text with only its letters and digits - "Prem. #: 001" and
    "Prem #: 001" are the same words."""
    return re.sub(r"[^0-9a-z]", "", _box_text(value).casefold())


def _says_it(value: Any, new_text: Optional[str]) -> bool:
    """Does the new document's own text print this value? A short answer (a
    tick, "Y", a code) is not looked for - the evidence gate judges those. No
    text to look in: not judged (True)."""
    if new_text is None or len(_words_only(value)) < 4:
        return True
    try:
        from services.pdf_service import _value_in_raw_text
        return bool(_value_in_raw_text(_box_text(value), new_text))
    except Exception:                                           # noqa: BLE001
        return True


def plan_form_fill(form_id: str, stored: dict, new_mapped: dict, new_conf: dict,
                   base_mapped: dict, new_guard: Iterable[dict] = (),
                   base_guard: Iterable[dict] = (), *, documents: Iterable[str] = (),
                   doc_ids: Iterable[str] = (),
                   document_texts: Optional[Dict[str, Tuple[str, Optional[str]]]] = None,
                   new_text: Optional[str] = None, other_insured: Optional[str] = None) -> dict:
    """What the new document's answers do to ONE stored form (pure).
    {"fills": {field: {value, label, doc_ids, documents}}, "suggestions": [...],
     "held_back": [...], "confirms": [...]}
    - a box moves only where the stamp WITH the answers differs from the stamp
    without them, and only with an AI label (a rule's box is the door's).

    Whose value is it (15 Oct 2026, review of Z23)? `document_texts` {doc_id:
    (file name, folded text)} for each document of the run: every fill,
    suggestion and held-back row names the documents whose OWN text prints its
    value - several files added in one upload are told apart, so excluding one
    takes back only what it printed. A value no single document prints (or too
    short to look for - a tick, a code) names every document of the run.
    `confirms`: an AI box this reading answers with the value it already shows
    - the run joins that box's receipt, so excluding the document that first
    wrote it keeps the value while this one is still in the package.

    A SUGGESTION reads "the new document says X" - so X must be printed in the
    new document's own text (`new_text`, folded like the stamper folds it) and
    differ from the box by more than punctuation (owner's run `18ecbfa8`, 12 Oct
    2026: adding the Cyber policy offered "Prem #: 001 Bldg #: 001" against the
    box's "Prem. #: 001 Bldg #: 001" - text the Cyber policy does not contain,
    which the AI read from the package's facts).

    `other_insured` (14 Oct 2026, owner's run `f83757cf`): the new document
    names a DIFFERENT insured than the package's applicant
    (`document_tags`). Another company's document never speaks for the
    applicant (`insured_scope`), so nothing is written: a blank box it
    answers is a suggestion too (current "") when the document prints the
    value (`_says_it`) and it shows something (an unticked checkbox on a blank
    box shows nothing), and nothing it read is listed as "AI held back" on
    the applicant's forms. Adding control_dec.pdf (MERIDIAN FABRICATION INC)
    to the Choice Electric package wrote 8 boxes on ACORD 28 / 127 / 131
    before this - mostly unticked "No"s and values the document does not
    print; replayed, none is written and at most one is offered."""
    docs = [str(d) for d in (documents or ()) if str(d or "").strip()]
    ids = [str(d) for d in (doc_ids or ()) if str(d or "").strip()]
    hold = bool(str(other_insured or "").strip())
    fills: Dict[str, dict] = {}
    suggestions: List[dict] = []
    confirms: List[dict] = []

    def _sources(value: Any) -> Dict[str, List[str]]:
        """The documents whose own text prints `value` - every document of the
        run when none (or all) can be told apart."""
        texts = document_texts if isinstance(document_texts, dict) else {}
        if value is not None and _box_text(value) and texts:
            hits = [(str(i), str(name or "")) for i, (name, text) in texts.items()
                    if str(i or "").strip() and _says_it(value, text)]
            if hits:
                return {"doc_ids": [i for i, _n in hits], "documents": [n for _i, n in hits if n]}
        return {"doc_ids": list(ids), "documents": list(docs)}

    def _suggest(field: str, current: Any, new: Any, label: str) -> None:
        row = {"form_id": form_id, "field": field,
               "current": _box_text(current), "suggested": new if isinstance(new, str) else str(new),
               "label": label, **_sources(new)}
        if hold:
            row["other_insured"] = str(other_insured).strip()
        suggestions.append(row)

    for field, new in (new_mapped or {}).items():
        if not _box_text(new) or _same(new, (base_mapped or {}).get(field)):
            continue
        label = (new_conf or {}).get(field)
        if label not in _AI_LABELS:
            continue
        owner = box_owner(stored, field)
        current = _box_value(stored, field)
        if owner == "blank":
            if not hold:
                fills[field] = {"value": new, "label": label, **_sources(new)}
            elif _says_it(new, new_text) and not _unticked_checkbox(stored, field, new):
                _suggest(field, "", new, label)
        elif owner == "ai" and (_same(new, current) or _words_only(new) == _words_only(current)):
            if not hold:
                confirms.append({"field": field, "value_hash": _value_hash(current), **_sources(new)})
        elif owner == "ai" and _says_it(new, new_text):
            _suggest(field, current, new, label)
    held = []
    if not hold:
        base_fields = {g.get("field") for g in (base_guard or ()) if isinstance(g, dict)}
        for g in new_guard or ():
            f = g.get("field") if isinstance(g, dict) else None
            if f and f not in base_fields and f not in fills and box_owner(stored, f) == "blank":
                held.append(dict(g, form_id=form_id, **_sources(g.get("removed_value"))))
    return {"fills": fills, "suggestions": suggestions, "held_back": held, "confirms": confirms}


def names_another_insured(session: Optional[dict], docs: Iterable[dict]) -> Optional[dict]:
    """{"name": <the insured(s) named>, "documents": [filenames]} when any of
    `docs` names an insured that is NOT the package's applicant - e.g.
    "MERIDIAN FABRICATION INC" from control_dec.pdf - judged by the Documents
    list's own rule over the session's Submission Integrity record
    (`document_tags`), with the applicant decided WITHOUT `docs` (two of
    another company's documents cannot outvote the package's own). None when
    every one of them names the applicant or nobody (positive evidence only),
    or the package has no integrity record."""
    try:
        from services.document_tags import (
            different_insured_ids, other_insured_of, session_insured_statuses,
        )
        docs = [d for d in (docs or ()) if isinstance(d, dict)]
        ids = [str(d.get("doc_id") or "").strip() for d in docs]
        ids = [i for i in ids if i]
        statuses = session_insured_statuses(session, judge_without=ids)
        name = other_insured_of(statuses, ids)
        if not name:
            return None
        hit = set(different_insured_ids(statuses, ids))
        files = [str(d.get("filename") or "") for d in docs
                 if str(d.get("doc_id") or "").strip() in hit and str(d.get("filename") or "").strip()]
        return {"name": name, "documents": files}
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("document fill: insured check skipped: %s", ex)
        return None


def _unticked_checkbox(form: Optional[dict], field: str, value: Any) -> bool:
    """A checkbox (per the form's own schema) the value leaves unticked - on a
    blank box that changes nothing the form shows, so it is no suggestion."""
    schema = (form or {}).get("schema") if isinstance(form, dict) else None
    meta = schema.get(field) if isinstance(schema, dict) else None
    if not isinstance(meta, dict) or meta.get("ft") != "/Btn":
        return False
    try:
        from services.needs_attention import _is_ticked
        return not _is_ticked(value)
    except Exception:                                          # noqa: BLE001
        return False


def _suggestion_stands(form: Optional[dict], suggestion: dict) -> bool:
    """A suggestion is live while its box still shows what it was measured
    against: the AI value it would replace, or - a value another insured's
    document offered for a blank box - still blank and nobody's."""
    field = suggestion.get("field")
    if not field:
        return False
    owner = box_owner(form, field)
    if not _box_text(suggestion.get("current")):
        return owner == "blank"
    return owner == "ai" and _same(_box_value(form, field), suggestion.get("current"))


def _suggestion_id(form_id: str, field: str, suggested: Any) -> str:
    import hashlib
    raw = f"{form_id}|{field}|{_box_text(suggested).casefold()}"
    return "docsug_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def apply_form_fills(generated: dict, snapshot: dict, plans: Dict[str, dict]) -> dict:
    """Apply the plans to the forms AS THEY STAND NOW (in place). A box is
    filled only while it is still blank, nobody's, and shows what it showed
    when the plan was made; a suggestion stands only while the box still shows
    the AI value it was measured against. Returns
    {"filled": {form: [boxes]}, "suggestions": [...], "held_back": n,
     "stale_signatures": [...], "receipts": [...]} - one receipt per box
    written (`fill_receipt`: what the box showed before, its hash after)."""
    try:
        from services.signature_boxes import STATE_SIGNED, STATE_STALE, applicant_signature_state
    except Exception:                                          # noqa: BLE001
        applicant_signature_state, STATE_SIGNED, STATE_STALE = None, "signed", "stale"
    filled: Dict[str, List[str]] = {}
    receipts: List[dict] = []
    suggestions: List[dict] = []
    held_total = 0
    stale: List[dict] = []
    for fid, plan in (plans or {}).items():
        form = (generated or {}).get(fid)
        snap = (snapshot or {}).get(fid)
        if not isinstance(form, dict) or not isinstance(snap, dict):
            continue
        signed_before = applicant_signature_state(form) if applicant_signature_state else None
        state = form.get("field_state")
        if not isinstance(state, dict):
            state = dict(form.get("mapped") or {})
        mapped = dict(form.get("mapped") or {})
        conf = dict(form.get("confidence") or {})
        done: List[str] = []
        for field, fill in (plan.get("fills") or {}).items():
            if box_owner(form, field) != "blank" or not _same(_box_value(form, field), _box_value(snap, field)):
                continue                       # a person or a re-stamp got there first
            receipt = fill_receipt(fid, field, state.get(field), mapped.get(field),
                                   conf.get(field), fill["value"])
            for key in ("doc_ids", "documents"):
                if fill.get(key):
                    receipt[key] = list(fill[key])
            receipts.append(receipt)
            state[field] = fill["value"]
            mapped[field] = fill["value"]      # machine-stamped, as generation stamps
            conf[field] = fill["label"]
            done.append(field)
        for s in plan.get("suggestions") or []:
            if _suggestion_stands(form, s):
                suggestions.append(dict(s, id=_suggestion_id(fid, s["field"], s["suggested"]),
                                        created_at=datetime.now(timezone.utc).isoformat()))
        held = [g for g in (plan.get("held_back") or [])
                if g.get("field") not in done and box_owner(form, g.get("field")) == "blank"]
        if held:
            have = {g.get("field") for g in (form.get("guard_blanks") or []) if isinstance(g, dict)}
            form["guard_blanks"] = list(form.get("guard_blanks") or []) + [
                g for g in held if g.get("field") not in have]
            held_total += len(held)
        if done:
            form["field_state"] = state
            form["mapped"] = mapped
            form["confidence"] = conf
            form["_pdf_cache_hash"] = ""
            form["pdf_bytes"] = None
            form["_applicant_render"] = None
            filled[fid] = done
            if signed_before == STATE_SIGNED and applicant_signature_state \
                    and applicant_signature_state(form) == STATE_STALE:
                stale.append({"form_id": fid, "label": _form_label(fid)})
    return {"filled": filled, "suggestions": suggestions, "held_back": held_total,
            "stale_signatures": stale, "receipts": receipts}


def merge_suggestions(existing: Iterable[dict], new: Iterable[dict], generated: dict) -> List[dict]:
    """The package's open suggestions: the new ones, then every older one still
    live (its box still shows the value it was measured against) that the new
    ones do not replace (one per box - the latest document's)."""
    out: List[dict] = []
    seen: set = set()
    for s in list(new or []) + list(existing or []):
        if not isinstance(s, dict) or not s.get("form_id") or not s.get("field"):
            continue
        key = (s["form_id"], s["field"])
        if key in seen:
            continue
        form = (generated or {}).get(s["form_id"])
        if not isinstance(form, dict) or not _suggestion_stands(form, s):
            continue
        seen.add(key)
        out.append(s)
    return out


# ── What an added document's AI reading leaves behind, and taking it back ────
#
# 15 Oct 2026 (owner, run `0353c36b`): "after removing that doc, will it also
# reverse the data or warnings it has added, and will the forms be updated?"
# The documents door already reverses its FACTS: a fact only it stated is
# retracted, every box those facts moved is re-stamped, the stops, the score
# and Data Consistency are re-scored. Its AI READING left three things nobody
# took back: the "New document says" rows (excluding ACORD_125_FILLED 2.pdf
# kept its 42 listed), the boxes it wrote into blank boxes, and the "AI held
# back" rows it added. Each now carries the document's id (rows stored before
# 15 Oct carry its file name, which is matched instead), and:
#   * a suggestion or held-back row speaks only while one of its documents is
#     in the package - read-time for suggestions (`suggestions_from_active_
#     documents`, so including the document again lists them again), at the
#     door for the held-back rows;
#   * a box its reading wrote is blanked again by the door when every document
#     behind it has left the package - only while it still shows exactly the
#     value written and is still the AI's (a person who typed over it, or a
#     rule that re-stamped it since, keeps it). The box returns to what it
#     showed before (it was blank - the reading writes blank boxes only).
# NOT covered, by measurement: an AI value written at GENERATION is not traced
# to a document. The presence check cannot stand in for that trace - on
# `0353c36b` it called the owner's own typed "Material and equipment storage"
# (a location-table answer, ACORD 140) a value only the Harborline 125 printed.

def fill_receipt(form_id: str, field: str, before_state: Any, before_mapped: Any,
                 label_before: Any, written: Any) -> dict:
    """One box an added document's reading wrote: where, what the box showed
    before (blank by the reading's own rule - nothing private), and a hash of
    what it wrote. The documents are added by the caller."""
    return {"form_id": form_id, "field": field, "before_state": before_state,
            "before_mapped": before_mapped, "label_before": label_before,
            "value_hash": _value_hash(written)}


def _value_hash(value: Any) -> str:
    import hashlib
    return hashlib.sha1(_box_text(value).casefold().encode("utf-8")).hexdigest()[:16]


def _document_refs(docs: Iterable[dict]) -> Tuple[set, set]:
    """(ids, file names) of the package's ACTIVE documents (`active_documents`
    - excluded and evidence-only documents are out)."""
    active = active_documents(docs)
    ids = {str(d.get("doc_id") or "").strip() for d in active} - {""}
    names = {str(d.get("filename") or "").strip() for d in active} - {""}
    return ids, names


def speaks_for_active_document(row: Optional[dict], ids: set, names: set) -> bool:
    """Is a row an added document's reading made still backed by a document in
    the package? By id when it carries ids, by file name otherwise; a row
    naming no document (an older shape) is kept - no evidence either way."""
    row = row if isinstance(row, dict) else {}
    row_ids = [str(x).strip() for x in (row.get("doc_ids") or []) if str(x or "").strip()]
    if row_ids:
        return bool(ids.intersection(row_ids))
    row_names = [str(x).strip() for x in (row.get("documents") or []) if str(x or "").strip()]
    if row_names:
        return bool(names.intersection(row_names))
    return True


def suggestions_from_active_documents(suggestions: Iterable[dict],
                                      docs: Optional[Iterable[dict]]) -> List[dict]:
    """The stored suggestions whose documents are still in the package. `docs`
    None = not judged (every row kept)."""
    rows = [s for s in (suggestions or ()) if isinstance(s, dict)]
    if docs is None:
        return rows
    ids, names = _document_refs(docs)
    return [s for s in rows if speaks_for_active_document(s, ids, names)]


def take_back_document_fills(generated: dict, receipts: Iterable[dict],
                             docs_after: Iterable[dict]) -> Tuple[Dict[str, List[str]], List[dict], int]:
    """Blank again (in place) every box a reading wrote from documents no
    longer in the package, while it still shows the value written and is still
    the AI's; drop those documents' "AI held back" rows. Returns ({form: boxes
    taken back}, the receipts still standing, held-back rows dropped)."""
    ids, names = _document_refs(docs_after)
    taken: Dict[str, List[str]] = {}
    standing: List[dict] = []
    for r in receipts or ():
        if not isinstance(r, dict) or not r.get("form_id") or not r.get("field"):
            continue
        form = (generated or {}).get(r["form_id"])
        field = r["field"]
        ours = (isinstance(form, dict) and box_owner(form, field) == "ai"
                and _value_hash(_box_value(form, field)) == r.get("value_hash"))
        if speaks_for_active_document(r, ids, names):
            if ours:
                standing.append(r)
            continue
        if not ours:
            continue                       # a person or a rule has the box now
        state = form.get("field_state")
        if not isinstance(state, dict):
            state = dict(form.get("mapped") or {})
        mapped = dict(form.get("mapped") or {})
        conf = dict(form.get("confidence") or {})
        state[field] = r.get("before_state")
        mapped[field] = r.get("before_mapped")
        if r.get("label_before") is None:
            conf.pop(field, None)
        else:
            conf[field] = r.get("label_before")
        form["field_state"], form["mapped"], form["confidence"] = state, mapped, conf
        form["_pdf_cache_hash"] = ""
        form["pdf_bytes"] = None
        form["_applicant_render"] = None
        taken.setdefault(r["form_id"], []).append(field)
    dropped = 0
    for fid, form in (generated or {}).items():
        if not isinstance(form, dict) or not isinstance(form.get("guard_blanks"), list):
            continue
        rows = form["guard_blanks"]
        keep = [g for g in rows if not isinstance(g, dict)
                or not (g.get("doc_ids") or g.get("documents"))
                or speaks_for_active_document(g, ids, names)]
        if len(keep) != len(rows):
            dropped += len(rows) - len(keep)
            form["guard_blanks"] = keep
            taken.setdefault(fid, [])
    return taken, standing, dropped


def offers_on_emptied_boxes(suggestions: Iterable[dict],
                            taken: Dict[str, List[str]]) -> Optional[List[dict]]:
    """After a take-back empties a box, another document's "New document says
    X - the form says Y" row for it would vanish (it no longer matches the
    box). It now reads against the blank box ("this box is empty"), so a value
    a document still in the package gives is still offered - never written
    (an exclusion takes back; it never adds). None when nothing changed."""
    emptied = {(fid, f) for fid, fields in (taken or {}).items() for f in (fields or [])}
    if not emptied:
        return None
    out: List[dict] = []
    changed = False
    for s in suggestions or ():
        if not isinstance(s, dict):
            continue
        if (s.get("form_id"), s.get("field")) in emptied and _box_text(s.get("current")):
            s = dict(s, current="")
            changed = True
        out.append(s)
    return out if changed else None


def join_confirming_documents(receipts: Iterable[dict], plans: Dict[str, dict],
                              generated: dict) -> Tuple[List[dict], bool]:
    """A later reading that answers an AI box with the value it already shows
    (`plan_form_fill` "confirms") joins that box's receipt: the value then
    stands while ANY document that printed it is in the package (review of
    Z23: excluding the first document blanked a value the second still
    gave). Only while the box still shows the receipt's value. Returns (the
    receipts, whether any changed)."""
    out = [dict(r) for r in (receipts or ()) if isinstance(r, dict)]
    changed = False
    for fid, plan in (plans or {}).items():
        form = (generated or {}).get(fid)
        for c in (plan or {}).get("confirms") or []:
            if not isinstance(c, dict) or not c.get("field") or not isinstance(form, dict):
                continue
            if _value_hash(_box_value(form, c["field"])) != c.get("value_hash"):
                continue
            for r in out:
                if r.get("form_id") != fid or r.get("field") != c["field"] \
                        or r.get("value_hash") != c.get("value_hash"):
                    continue
                for key in ("doc_ids", "documents"):
                    merged = list(dict.fromkeys(list(r.get(key) or []) + list(c.get(key) or [])))
                    if merged != list(r.get(key) or []):
                        r[key] = merged
                        changed = True
    return out, changed


class _BeatQueue:
    """`generation_state.GenerationHeartbeat` beats a queue's `touch`; the
    document fill beats its session row instead."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    async def touch(self, _job_id: str) -> None:
        await upd_processing_session(self.session_id, {
            FILL_BEAT_KEY: datetime.now(timezone.utc).isoformat()})


async def start_new_document_fill(session_id: str, added_docs: Iterable[dict], user_id: Any, *,
                                  review_counts_before: Optional[dict] = None) -> dict:
    """Record a RUNNING fill for the documents just added (the lock starts
    now) and return its status - the caller schedules `launch_new_document_fill`
    once it has answered. {"state": "off"} when the kill switch is off or
    nothing was added."""
    docs = [d for d in (added_docs or ()) if isinstance(d, dict)]
    if not ai_fill_enabled() or not docs:
        return {"state": FILL_OFF}
    now = datetime.now(timezone.utc).isoformat()
    names = [str(d.get("filename") or "") for d in docs]
    status = {
        "run_id": uuid.uuid4().hex,
        "state": FILL_RUNNING,
        "documents": names,
        "doc_ids": [str(d.get("doc_id") or "") for d in docs],
        "started_at": now,
        "review_counts_before": review_counts_before,
        "message": f"Reading {', '.join(n for n in names if n) or 'your document'} into your forms...",
    }
    await upd_processing_session(session_id, {FILL_KEY: status, FILL_BEAT_KEY: now})
    return status


async def launch_new_document_fill(session_id: str, status: dict, user_id: Any) -> None:
    """Start the run detached from the request (it can take minutes). Held in
    `_TASKS` so it is never collected mid-run.

    ── WHY THIS IS `async def` (8 Oct 2026) ────────────────────────────────
    It is handed to Starlette as `BackgroundTask(launch_new_document_fill, ...)`.
    Starlette awaits an async callable on the event loop, but a PLAIN `def` it
    sends to `run_in_threadpool` - an AnyIO worker thread, which has no event
    loop. `asyncio.ensure_future` there raises

        RuntimeError: There is no current event loop in thread 'AnyIO worker thread'
        RuntimeWarning: coroutine 'run_new_document_fill' was never awaited

    so the coroutine was created and dropped. Measured on the owner's run
    `b4d18e8e`: adding a document re-stamped the forms deterministically, the
    AI reading of that document never ran, and `document_ai_fill` sat on
    `{"state": "running"}` for ever - the screen kept saying "Reading
    <file> into your forms..." with nothing behind it. C103's whole point,
    broken at the seam rather than in the logic.

    The one-word change (`def` -> `async def`) puts it back on the loop, where
    `ensure_future` is valid and the task really is detached. The function is
    still the same object the route schedules, so the route is unchanged.
    """
    if not isinstance(status, dict) or status.get("state") != FILL_RUNNING:
        return
    task = asyncio.ensure_future(run_new_document_fill(
        session_id, status.get("doc_ids") or [], user_id, run_id=status.get("run_id")))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _write_status(session_id: str, run_id: str, status: dict) -> None:
    """Write the final status - unless a newer run has replaced this one."""
    try:
        sess = await get_processing_session(session_id)
        if (sess.get(FILL_KEY) or {}).get("run_id") not in (None, run_id):
            return
        await upd_processing_session(session_id, {FILL_KEY: status})
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("document fill: status not written [session=%s]: %s", session_id, ex)


async def run_new_document_fill(session_id: str, doc_ids: Iterable[str], user_id: Any, *,
                                run_id: Optional[str]) -> dict:
    """THE AI READING of documents added after forms - see the section note.
    Never raises; returns the final status (also written to the row)."""
    from services.generation_state import GenerationHeartbeat
    uid = str(user_id or "")
    beat = GenerationHeartbeat(_BeatQueue(session_id), str(run_id or "fill"))
    await beat.start()
    base: dict = {}
    try:
        base = dict((await get_processing_session(session_id)).get(FILL_KEY) or {})
        status = await _fill_once(session_id, [str(d) for d in (doc_ids or ())], uid, run_id, base)
    except Exception as ex:                                    # noqa: BLE001
        logger.error("document fill failed [session=%s run=%s]: %s", session_id, run_id, ex,
                     exc_info=True)
        status = {**base, "run_id": run_id, "state": FILL_FAILED, "message": FILL_FAILED_TEXT,
                  "finished_at": datetime.now(timezone.utc).isoformat()}
        await _write_status(session_id, str(run_id or ""), status)
    finally:
        await beat.stop()
    return status


async def _fill_once(session_id: str, doc_ids: List[str], uid: str, run_id: Optional[str],
                     base: dict) -> dict:
    loop = asyncio.get_event_loop()
    session = await get_processing_session(session_id)
    if (session.get(FILL_KEY) or {}).get("run_id") not in (None, run_id):
        return dict(session.get(FILL_KEY) or {})                # a newer run owns the package
    generated = copy.deepcopy(session.get("generated_forms") or {})
    docs = [d for d in (session.get("docs") or []) if isinstance(d, dict)]
    wanted = set(doc_ids)
    new_docs = [d for d in docs if str(d.get("doc_id") or "") in wanted
                and not d.get("excluded") and str(d.get("text") or "").strip()]
    names = [str(d.get("filename") or "") for d in new_docs]
    # Whose documents are these? The package's integrity record (re-assessed
    # by the documents door with them in it) answers through the Documents
    # list's own rule. Another insured's document only ever suggests.
    another = names_another_insured(session, new_docs)
    other = (another or {}).get("name")
    status = {**base, "run_id": run_id, "state": FILL_DONE, "boxes_filled": 0,
              "filled_by_form": {}, "suggestions": 0, "held_back": 0, "stale_signatures": [],
              "message": "", "other_insured": other,
              "other_insured_documents": (another or {}).get("documents") or []}
    if generated and new_docs:
        per_form = await loop.run_in_executor(
            None, functools.partial(_new_document_answers, session, new_docs, list(generated)))
        # The presence backstop reads the package's text, as at generation.
        raw_all = " ".join(str(d.get("text") or "") for d in active_documents(docs))
        # A suggestion must be printed in the NEW documents themselves.
        try:
            from services.needs_attention import document_haystack
            new_text = document_haystack(new_docs)
        except Exception:                                      # noqa: BLE001
            new_text = None
        empty = {"filled_values": {}, "raw_text_fields": set(), "question_grounding": {}}
        # Each new document's own text, so every row names the documents that
        # print its value (several files added in one upload are told apart).
        try:
            from services.needs_attention import document_haystack as _haystack
            document_texts = {str(d.get("doc_id") or ""): (str(d.get("filename") or ""), _haystack([d]))
                              for d in new_docs if str(d.get("doc_id") or "").strip()}
        except Exception:                                      # noqa: BLE001
            document_texts = None
        plans: Dict[str, dict] = {}
        for fid in generated:
            answers = per_form.get(fid) or {}
            if not answers.get("filled_values"):
                continue
            schema = await loop.run_in_executor(None, functools.partial(_generation_schema, session, fid))
            if not schema:
                continue
            new_m, new_c, new_g = await loop.run_in_executor(None, functools.partial(
                _stamp_with_answers, session, fid, answers, raw_all, schema))
            base_m, _bc, base_g = await loop.run_in_executor(None, functools.partial(
                _stamp_with_answers, session, fid, empty, raw_all, schema))
            plan = plan_form_fill(fid, generated[fid], new_m, new_c, base_m, new_g, base_g,
                                  other_insured=other,
                                  doc_ids=[str(d.get("doc_id") or "") for d in new_docs],
                                  document_texts=document_texts,
                                  documents=names, new_text=new_text)
            if plan["fills"] or plan["suggestions"] or plan["held_back"] or plan.get("confirms"):
                plans[fid] = plan
        if plans:
            async with _Serialized(session_id):
                fresh = await get_processing_session(session_id)
                if (fresh.get(FILL_KEY) or {}).get("run_id") not in (None, run_id):
                    return dict(fresh.get(FILL_KEY) or {})
                forms_now = fresh.get("generated_forms") or {}
                applied = apply_form_fills(forms_now, generated, plans)
                touched = sorted(set(applied["filled"]) | {
                    fid for fid, p in plans.items() if p.get("held_back")})
                suggestions = merge_suggestions(fresh.get(SUGGESTIONS_KEY) or [],
                                                applied["suggestions"], forms_now)
                update: Dict[str, Any] = {SUGGESTIONS_KEY: suggestions}
                receipts, joined = join_confirming_documents(
                    fresh.get(RECEIPTS_KEY) or [], plans, forms_now)
                if applied.get("receipts") or joined:
                    _ids = [str(d.get("doc_id") or "") for d in new_docs]
                    update[RECEIPTS_KEY] = receipts + [
                        dict(r, doc_ids=r.get("doc_ids") or _ids, documents=r.get("documents") or names,
                             run_id=run_id)
                        for r in applied.get("receipts") or []]
                if touched:
                    update["generated_forms"] = {fid: {
                        k: forms_now[fid].get(k) for k in (
                            "field_state", "mapped", "confidence", "guard_blanks",
                            "_pdf_cache_hash", "pdf_bytes", "_applicant_render")
                        if k in forms_now[fid]} for fid in touched}
                await upd_processing_session(session_id, update)
            filled = applied["filled"]
            status.update({
                "boxes_filled": sum(len(v) for v in filled.values()),
                "filled_by_form": {fid: len(v) for fid, v in filled.items()},
                "forms_filled": [{"form_id": fid, "label": _form_label(fid), "boxes": len(v)}
                                 for fid, v in filled.items()],
                "suggestions": len(applied["suggestions"]),
                "held_back": applied["held_back"],
                "stale_signatures": applied["stale_signatures"],
            })
            if filled or applied["held_back"]:
                # Scores, the stop cache and the stored cards follow the forms;
                # field QA and the mapping check refresh (best-effort each).
                try:
                    from services.arq_service import recalculate_session_scores
                    await recalculate_session_scores(session_id)
                except Exception as ex:                        # noqa: BLE001
                    logger.error("document fill: re-score failed [session=%s]: %s", session_id, ex,
                                 exc_info=True)
                await _refresh_after_restamp(session_id, uid)
    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        from services.audit_service import log_audit_event
        await log_audit_event(session_id, uid, "forms_filled_from_new_documents", {
            "documents": names,
            "boxes_filled": status["boxes_filled"],
            "filled_by_form": status["filled_by_form"],
            "suggestions": status["suggestions"],
            "held_back": status["held_back"],
            "stale_signatures": [s["form_id"] for s in status["stale_signatures"]],
            "other_insured": status.get("other_insured"),
        })
    except Exception as ex:                                    # noqa: BLE001
        logger.warning("document fill: audit event failed: %s", ex)
    logger.info("document fill: session=%s docs=%s filled=%s suggestions=%d held=%d other_insured=%s",
                session_id, names, status["filled_by_form"], status["suggestions"],
                status["held_back"], status.get("other_insured"))
    await _write_status(session_id, str(run_id or ""), status)
    return status


async def keep_current_value(session_id: str, suggestion_id: str) -> Optional[dict]:
    """"Keep current": retire one suggestion. Returns it, or None when the
    package holds no such suggestion."""
    async with _Serialized(session_id):
        session = await get_processing_session(session_id)
        held = [s for s in (session.get(SUGGESTIONS_KEY) or []) if isinstance(s, dict)]
        gone = next((s for s in held if s.get("id") == suggestion_id), None)
        if gone is None:
            return None
        await upd_processing_session(session_id, {
            SUGGESTIONS_KEY: [s for s in held if s.get("id") != suggestion_id]})
        return gone
