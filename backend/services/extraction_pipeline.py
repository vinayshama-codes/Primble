"""Single source of truth for the OCR → extraction → form-matching pipeline.

Called by both form_routes.py (inline route handler) and worker.py
(background job). Returns a plain dict so callers can use the results
without importing any extra types.

Return keys
-----------
session_id          : str
processed_docs      : list[dict]
primary             : dict
merged_facts        : dict
mflags              : dict
tier1_ok            : bool
tier1_missing       : list
tier2_score         : float | int
tier2_missing       : list
hard_stops          : list
soft_stops          : list
doc_conflicts       : list[dict]  — structured conflicts parsed from consistency issues
recommendations     : list[dict]
extra_forms_scored  : list[dict]
unique_low_conf     : list
available_forms     : list[dict]
"""
import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from services.ocr_service import extract_text
from services.extraction_service import (
    extract_facts_long, classify_document, merge_facts, select_primary_truth,
    detect_source_conflicts, ALLOWED_DOC_TYPES,
)
from utils.table_extractor import extract_tables_from_pdf
from services.form_service import (
    filter_available_forms, load_all_forms, match_forms, score_extra_forms,
    derive_account_profile,
)
from services.sqs_service import (
    check_tier1, check_tier2, evaluate_stops, check_doc_consistency,
)
from services.cross_form_validator import run_cross_form_validation, split_cross_form_issues
from services.submission_integrity import assess_submission_integrity
from services.underwriting_consistency import (
    assess_underwriting_consistency, apply_confirmations, validate_confirmation,
    RECONCILABLE_FIELDS, RECONCILABLE_FIELD_KEYS,
)
from repositories.session_repository import new_processing_session, upd_processing_session

logger = logging.getLogger(__name__)


def _unwrap_scalar(v: Any) -> Any:
    """Unwrap the annotated {value, confidence} envelope to its scalar value."""
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


class ProcessingIntegrityError(RuntimeError):
    """Raised when LLM extraction output fails schema validation before DB persist."""


class _ExtractionOutput(BaseModel):
    """Minimal schema guard on extract_facts_long output before it reaches the DB.

    Facts and flags are open dicts — we only enforce that both keys are present
    and are dicts.  Field-level constraints live in extraction_service._validate_parsed;
    this layer catches any structural regression that bypasses that validator.

    extra="allow" preserves top-level keys produced by extract_facts() beyond
    facts/flags (e.g. manual_confirmation_required) so they are not silently
    dropped by Pydantic before the result reaches processed_docs.
    """
    model_config = ConfigDict(extra="allow")

    facts: Dict[str, Any]
    flags: Dict[str, Any]

    @field_validator("facts", "flags", mode="before")
    @classmethod
    def _must_be_dict(cls, v: Any, info: Any) -> Any:
        if not isinstance(v, dict):
            raise ValueError(f"'{info.field_name}' must be a dict, got {type(v).__name__}")
        return v


def _validate_extraction_output(raw: dict, doc_type: str) -> dict:
    """Validate extract_facts_long output with Pydantic before persisting to DB.

    On failure: logs the raw output, raises ProcessingIntegrityError.
    """
    try:
        validated = _ExtractionOutput.model_validate(raw)
        # Attribute access (not .model_dump()) so Pydantic's serializer never
        # runs over the annotated envelopes inside facts.
        result = {"facts": validated.facts, "flags": validated.flags}
        # Forward any extra top-level keys (e.g. manual_confirmation_required).
        if validated.model_extra:
            result.update(validated.model_extra)
        return result
    except Exception as exc:
        logger.error(
            "extract_facts_long output failed schema validation for doc_type=%r. "
            "Raw output (truncated): %.2000s — error: %s",
            doc_type,
            json.dumps(raw, default=str),
            exc,
        )
        raise ProcessingIntegrityError(
            f"Extraction output for doc_type={doc_type!r} failed integrity check: {exc}"
        ) from exc


def _format_tables_as_text(tables: list) -> str:
    """Convert pdfplumber/camelot table rows into a readable block for the LLM.

    Each table row is rendered as pipe-separated cells so the LLM can
    identify repeating-row schedules (vehicles, WC class codes, locations).
    This text is appended to the OCR output — the LLM sees both raw OCR
    and the structured table data and can reconcile them.
    """
    if not tables:
        return ""
    lines = ["\n\n=== STRUCTURED TABLE DATA (extracted from PDF layout) ==="]
    for idx, tbl in enumerate(tables, 1):
        lines.append(f"\n--- Table {idx} (page {tbl.get('page', '?')}, source: {tbl.get('source', '?')}) ---")
        for row in (tbl.get("rows") or []):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if any(c for c in cells):  # skip fully-empty rows
                lines.append(" | ".join(cells))
    lines.append("\n=== END TABLE DATA ===")
    return "\n".join(lines)


async def run_extraction_pipeline(file_paths: list[str], user_id: Any) -> dict:
    """Run OCR, extraction, validation, and form-matching for *file_paths*.

    Raises ``ValueError`` when no readable text is found (callers translate
    this into an appropriate error response or job failure).
    """
    processed_docs: list[dict] = []
    all_low_conf:   list       = []

    for path in file_paths:
        text, low_conf = await extract_text(path)
        if len(text) < 30:
            continue
        all_low_conf += low_conf

        # Append structured table data so the LLM sees schedule rows as proper
        # row-by-row data rather than unstructured OCR noise.  Only attempted for
        # PDFs; non-fatal if pdfplumber/camelot is unavailable.
        if path.lower().endswith(".pdf"):
            try:
                # Run the sync pdfplumber/camelot table extraction in a thread so it
                # does not freeze the asyncio event loop (would otherwise block
                # health checks and other in-flight requests for the duration of
                # table parsing on large PDFs).
                _loop = asyncio.get_running_loop()
                tables = await _loop.run_in_executor(None, extract_tables_from_pdf, path)
                if tables:
                    text = text + _format_tables_as_text(tables)
                    logger.info(
                        "table_extractor: %d table(s) appended for %s",
                        len(tables), os.path.basename(path),
                    )
            except Exception as _tbl_err:
                logger.warning("table_extractor: skipped %s — %s", os.path.basename(path), _tbl_err)

        # Strip the UUID prefix (added in form_routes.py for storage safety) so the
        # user sees the original filename, not "abc123_originalname.pdf". Computed
        # BEFORE classification so the filename can serve as a supporting signal
        # (Beta Report §4.2 action item #3).
        _raw_basename = os.path.basename(path)
        _parts = _raw_basename.split("_", 1)
        _display_name = _parts[1] if len(_parts) == 2 and len(_parts[0]) == 32 and _parts[0].isalnum() else _raw_basename

        # Document classification (Beta Report §4.2): content keywords + narrative
        # detection rules + filename signals. Returns the canonical type plus the
        # confidence/source/signals used (surfaced to the UI + audit).
        classification = classify_document(text, filename=_display_name)
        doc_type  = classification["doc_type"]
        raw       = await extract_facts_long(text, doc_type, low_confidence_tokens=low_conf)
        extracted = _validate_extraction_output(raw, doc_type)

        processed_docs.append({
            "doc_id":                uuid.uuid4().hex,
            "filename":              _display_name,
            "path":                  path,
            "doc_type":              doc_type,
            "classification":        classification,
            "doc_type_source":       classification.get("source"),
            "doc_type_confidence":   classification.get("confidence"),
            "doc_type_overridden":   False,
            "text":                  text,
            "facts":                 extracted.get("facts", {}),
            "flags":                 extracted.get("flags", {}),
            "low_confidence_tokens": low_conf,
            "manual_confirmation_required": extracted.get("manual_confirmation_required") or [],
            "truncation_warning":    extracted.get("truncation_warning"),
        })

    if not processed_docs:
        raise ValueError("no_readable_text")

    return await _finalize_pipeline(processed_docs, user_id)


async def _finalize_pipeline(
    processed_docs: list[dict],
    user_id: Any,
    *,
    session_id: Optional[str] = None,
    integrity_override: Optional[dict] = None,
    confirmations: Optional[dict] = None,
    submission_label: Optional[str] = None,
) -> dict:
    """Run everything AFTER per-document extraction: merge facts, cross-doc
    consistency, Submission Integrity Validation, and — only when integrity
    does not require review — form recommendations + cross-form validation.

    Reused by:
      • run_extraction_pipeline()       — fresh upload (session_id=None)
      • resolve_submission_integrity()  — 'Remove documents' / 'Continue anyway'
        re-runs on the docs already stored in the session (NO re-OCR).

    When ``session_id`` is provided the existing session is updated in place;
    otherwise a new session is created. When the integrity verdict is LOW and
    no ``integrity_override`` is supplied, downstream recommendations and
    cross-form validation are SKIPPED and ``integrity.review_required`` is
    surfaced so the caller can pause for the user-facing review step.
    """
    # Active docs = those included in scoring. Documents the user excluded from
    # scoring (Beta Report §4.2 item #6 — "Exclude from scoring") are kept in the
    # session for display but contribute no facts, conflicts, integrity identity,
    # or recommendations. We never score an empty package, so an all-excluded
    # package falls back to scoring everything.
    active_docs = [d for d in processed_docs if not d.get("excluded")] or processed_docs

    # Low-confidence OCR tokens are carried on each doc; aggregate for the
    # response + the manual-confirmation soft stops below.
    all_low_conf: list = []
    for d in active_docs:
        all_low_conf += d.get("low_confidence_tokens") or []

    # "Include as supporting document only" (Beta Report §4.2 item #6): a
    # supporting-only doc STILL contributes its facts to the merge, but must
    # never be selected as the primary truth document. Fall back to all active
    # docs when every doc is supporting-only so we never score an empty package.
    _primary_candidates  = [d for d in active_docs if not d.get("supporting_only")] or active_docs
    primary              = select_primary_truth(_primary_candidates)
    merged_facts, mflags = merge_facts(active_docs, primary)
    mflags["_doc_type"]  = primary.get("doc_type", "unknown")

    # ── Wire loss-history flags that the scoring pillars depend on ───────────
    # Fix: no_prior_losses / narrative_states_no_losses were never set by the
    # pipeline — root cause of "score didn't move" after loss remediation (§6.4).
    _npl = merged_facts.get("loss_history_no_prior_losses_indicator")
    if isinstance(_npl, dict):
        _npl = _npl.get("value")
    if _npl:
        mflags["no_prior_losses"] = True

    _no_loss_phrases = (
        "no prior losses", "no losses", "no prior claims",
        "no claims", "clean loss history", "favorable loss history",
    )
    # M5 fix: collect which fact keys were contributed by narrative docs so
    # _derive_evidence_labels can emit "stated_in_narrative" for them.
    _narrative_fact_keys: set = set()
    for _ndoc in active_docs:
        if _ndoc.get("doc_type") == "narrative" and not _ndoc.get("excluded"):
            _ndoc_text = str(_ndoc.get("text", "") or "").lower()
            if any(p in _ndoc_text for p in _no_loss_phrases):
                mflags["narrative_states_no_losses"] = True
            _ndoc_facts = _ndoc.get("facts") or {}
            for _nk, _nv in _ndoc_facts.items():
                # Only credit keys that actually have a value in this narrative doc.
                _scalar = _nv.get("value") if isinstance(_nv, dict) else _nv
                if _scalar not in (None, "", "null", "none"):
                    _narrative_fact_keys.add(_nk)
    if _narrative_fact_keys:
        mflags["_narrative_fact_keys"] = list(_narrative_fact_keys)

    # ── Umbrella underlying-schedule + follow-form text fallback ─────────────
    # The Umbrella Adequacy pillar deducts -15 (no Schedule of Underlying
    # Insurance) and -10 (no follow-form evidence). Those facts rarely extract
    # as discrete fields, so when an umbrella is present and the fact is still
    # absent we scan the raw document text for explicit evidence and set it from
    # the source (Option B: follow-form is only credited when the documents
    # explicitly state it - never inferred). This is purely additive: it can only
    # ADD evidence the scorer already knows how to read, never remove it.
    if mflags.get("has_umbrella"):
        def _fact_present(_key: str) -> bool:
            _v = merged_facts.get(_key)
            if isinstance(_v, dict):
                _v = _v.get("value")
            return _v not in (None, "", "null", "none")

        _schedule_phrases = (
            "schedule of underlying", "underlying insurance schedule",
            "schedule of underlying insurance",
        )
        _follow_form_phrases = (
            "follow form", "follows form", "follow the form",
            "following form", "follows the underlying",
        )
        _need_schedule    = not _fact_present("schedule_of_underlying_insurance")
        _need_follow_form = not _fact_present("umbrella_follow_form")
        if _need_schedule or _need_follow_form:
            for _udoc in active_docs:
                if _udoc.get("excluded"):
                    continue
                _utext = str(_udoc.get("text", "") or "").lower()
                if not _utext:
                    continue
                if _need_schedule and any(p in _utext for p in _schedule_phrases):
                    merged_facts["schedule_of_underlying_insurance"] = {
                        "value": "Schedule of Underlying Insurance referenced in submitted documents",
                        "confidence": "filled", "source": "policy_doc_text",
                    }
                    _need_schedule = False
                if _need_follow_form and any(p in _utext for p in _follow_form_phrases):
                    merged_facts["umbrella_follow_form"] = {
                        # Value intentionally contains "follows form" so the umbrella
                        # scorer's phrase detection credits it (parity with extraction).
                        "value": "Umbrella follows form over the underlying coverages (per submitted documents)",
                        "confidence": "filled", "source": "policy_doc_text",
                    }
                    _need_follow_form = False
                if not _need_schedule and not _need_follow_form:
                    break

    # ── Core Underwriting Data Consistency (Beta Report §4.3) ───────────────
    # Apply any user-confirmed reconcilable values (e.g. Gross Sales) to the
    # merged facts BEFORE tier checks, stops, recommendations, and form fill so
    # the confirmed value flows consistently into every relevant form and into
    # SQS scoring.
    confirmations = confirmations or {}
    if confirmations:
        merged_facts = apply_confirmations(merged_facts, confirmations)

    tier1_ok, tier1_missing = check_tier1(merged_facts, mflags)

    tier2_score, tier2_missing = check_tier2(merged_facts)
    hard_stops, soft_stops     = evaluate_stops(merged_facts, mflags)

    # DEBUG (Beta Report §5): dump each document's extracted identity/policy
    # values. The cross-doc detectors compare EXACTLY these per-doc values, so a
    # conflict that fails to surface (e.g. only Gross Sales shows a picker) is
    # traceable here — if two docs log identical values, the LLM extraction
    # collapsed them upstream, not the conflict logic.
    if len(active_docs) > 1:
        for _d in active_docs:
            _df = _d.get("facts") or {}
            logger.info(
                "doc_consistency_input file=%s type=%s | name=%r entity=%r "
                "carrier=%r eff=%r exp=%r mailing=%r fein=%r revenue=%r",
                _d.get("filename"), _d.get("doc_type"),
                _unwrap_scalar(_df.get("applicant_name")),
                _unwrap_scalar(_df.get("entity_type")),
                _unwrap_scalar(_df.get("carrier_name")),
                _unwrap_scalar(_df.get("effective_date")),
                _unwrap_scalar(_df.get("expiration_date")),
                _unwrap_scalar(_df.get("mailing_address")),
                _unwrap_scalar(_df.get("fein")),
                _unwrap_scalar(_df.get("total_revenue")),
            )

    # Fields the user already RESOLVED via the Data Consistency picker
    # (underwriting_consistency confirmations) are no longer cross-doc conflicts:
    # their confirmed value is applied below and they must not keep blocking here.
    _confirmed_keys = set((confirmations or {}).keys())
    consistency_issues = check_doc_consistency(active_docs, _confirmed_keys)
    doc_conflicts: list[dict] = []
    normalized_differences: list[str] = []
    if consistency_issues:
        logger.warning("Doc consistency issues: %s", consistency_issues)
        for issue in consistency_issues:
            if issue.startswith("[hard_stop]"):
                rest      = issue[len("[hard_stop]"):].strip()
                code_part, _, msg = rest.partition(" ")
                code      = code_part.split("=", 1)[1] if "=" in code_part else "conflict"
                doc_conflicts.append({"code": code, "message": msg, "hard_stop": True})
                hard_stops = list(hard_stops) + [msg]
            elif issue.startswith("[warning]"):
                # Spec: DBAs/address/LOB/revenue mismatches are warnings, not blockers.
                rest = issue[len("[warning]"):].strip()
                # Strip the leading machine token (field=foo / code=foo) so the
                # user sees only the plain-language message (Beta Report P2 #28).
                rest = re.sub(r"^(?:field|code)=\S+\s*", "", rest)
                soft_stops = list(soft_stops) + [rest]
            elif issue.startswith("[info]"):
                # Normalization notice: values differed in format but were treated
                # as equivalent. Surface to the user as an informational notice
                # (Beta Report §5.1: "Raw values remain visible to the user").
                rest = issue[len("[info]"):].strip()
                rest = re.sub(r"^(?:field|code)=\S+\s*", "", rest)
                normalized_differences.append(rest)
            else:
                # Unknown prefix — treat as warning so it does not silently cap SQS at 60.
                soft_stops = list(soft_stops) + [issue]

    # ── Core Underwriting Data Consistency (Beta Report §4.3) ───────────────
    # Normalization-aware reconciliation of Gross Sales (and similar fields):
    # groups each value by its normalized form, attributes it to the source
    # document(s), and flags a non-blocking review when values materially
    # differ. Owns RECONCILABLE_FIELD_KEYS so the crude raw-string detector
    # below does not double-report them as formatting conflicts.
    underwriting = assess_underwriting_consistency(active_docs, merged_facts, confirmations)
    if underwriting.get("review_required"):
        for f in underwriting["fields"]:
            if f.get("review_required"):
                soft_stops = list(soft_stops) + [
                    f"{f['label']}: documents disagree "
                    f"({', '.join(v['display'] for v in f['values'])}). "
                    "Confirm the correct value to apply it across forms."
                ]

    # ── Cross-document source conflicts ─────────────────────────────────────
    # Surface field-level discrepancies between uploaded documents so the
    # broker can reconcile before submission rather than silently overwriting.
    if len(active_docs) > 1:
        # check_doc_consistency() above already compares these identity/date/LOB
        # fields in a normalization-aware way (Beta Report §5). Excluding them
        # here keeps detect_source_conflicts from (a) re-flagging a value that
        # normalizes equal and (b) double-reporting a genuine conflict the
        # consistency check already raised.
        _consistency_owned = {
            "applicant_name", "dba_name", "entity_type", "mailing_address",
            "physical_address", "fein", "effective_date", "expiration_date",
            "lines_of_business",
        }
        source_conflicts = detect_source_conflicts(
            active_docs,
            skip_fields=set(RECONCILABLE_FIELD_KEYS) | _consistency_owned,
        )
        if source_conflicts:
            logger.info("Source conflicts detected across docs: %d", len(source_conflicts))
            soft_stops = list(soft_stops) + source_conflicts

    # ── Submission Integrity Validation (Beta Report §4.1) ──────────────────
    # Runs AFTER extraction/classification and BEFORE form recommendations,
    # SQS scoring, cross-form validation, questionnaire, and form generation.
    # When the verdict is LOW (likely multiple insureds) we pause the workflow
    # for a user-facing review instead of treating the package as clean.
    integrity = assess_submission_integrity(active_docs)
    if integrity_override:
        integrity = {
            **integrity,
            "review_required": False,
            "overridden":      True,
            "override":        integrity_override,
        }
    review_required = bool(integrity.get("review_required"))

    # ── OCR low-confidence gate (applies on every path) ─────────────────────
    # Critical fields (business name, address, FEIN, policy dates, property
    # values) at OCR confidence below threshold are surfaced for manual
    # confirmation as soft warnings.
    _ocr_review_fields: list[str] = []
    for d in active_docs:
        for fld in d.get("manual_confirmation_required") or []:
            if fld not in _ocr_review_fields:
                _ocr_review_fields.append(fld)
    if _ocr_review_fields:
        soft_stops = list(soft_stops) + [
            f"Low OCR confidence on critical field — confirm: {fld}"
            for fld in _ocr_review_fields
        ]

    unique_low_conf = list(dict.fromkeys(all_low_conf))
    available_forms = filter_available_forms(load_all_forms())

    if review_required:
        # SHORT-CIRCUIT: do not run form recommendations or cross-form
        # validation on a package that may belong to multiple insureds. These
        # run after the user resolves the review ('Remove documents' / 'Continue
        # anyway'). all_forms metadata is still stored so the downstream select
        # path works unchanged once the review is cleared.
        recommendations    = []
        extra_forms_scored = []
        cross_form_issues  = []
        account_profile    = {}
        logger.warning(
            "Submission integrity LOW — pausing pipeline for review "
            "(entities=%s, session_id=%s)",
            integrity.get("detected_entities"), session_id,
        )
    else:
        combined_text   = " ".join(d.get("text", "") for d in active_docs)
        recommendations = match_forms(merged_facts, mflags, available_forms, text=combined_text)

        # Account profile (business class / account type / coverage goals) —
        # Beta Report §7.2 item 5. Read-only context for filtering/labelling.
        account_profile = derive_account_profile(merged_facts, mflags, text=combined_text)

        triggered_ids      = {r["form_id"] for r in recommendations}
        extra_forms_scored = score_extra_forms(merged_facts, triggered_ids, available_forms)

        # ── Cross-form validation ────────────────────────────────────────────
        cross_form_issues = run_cross_form_validation(merged_facts, mflags, triggered_ids)
        cf_hard, cf_soft, cf_advisories = split_cross_form_issues(cross_form_issues)
        if cf_hard:
            logger.warning("Cross-form hard stops: %s", cf_hard)
            hard_stops = list(hard_stops) + cf_hard
        if cf_soft:
            soft_stops = list(soft_stops) + cf_soft

    # Human-friendly label for the submissions history (Beta Report §4.1). Prefer
    # an explicit label (e.g. a split cluster's insured name from "Create separate
    # submissions") over the merged applicant name so a split child never falls
    # back to "Unknown Applicant" when its own applicant_name failed to extract.
    _applicant_lbl = _unwrap_scalar(merged_facts.get("applicant_name"))
    _applicant_lbl = str(_applicant_lbl).strip() if _applicant_lbl else ""
    session_label  = (str(submission_label).strip() if submission_label else "") or _applicant_lbl or None

    session_payload = {
        "user_id":              user_id,
        "docs":                 processed_docs,
        "primary_doc":          primary["filename"],
        "submission_label":     session_label,
        "facts":                merged_facts,
        "flags":                mflags,
        "tier2_score":          tier2_score,
        "tier2_missing":        tier2_missing,
        "hard_stops":           hard_stops,
        "soft_stops":           soft_stops,
        "normalized_differences": normalized_differences,
        "cross_form_issues":    cross_form_issues,
        "all_forms":            available_forms,
        "recommendations":      recommendations,
        "account_profile":      account_profile,
        "selected_form_ids":    [],
        "generated_forms":      {},
        "low_confidence_tokens": unique_low_conf,
        "integrity":            integrity,
        "underwriting_consistency":   underwriting,
        "underwriting_confirmations": confirmations,
    }

    if session_id:
        await upd_processing_session(session_id, session_payload)
        sid = session_id
    else:
        sid = await new_processing_session(session_payload)

    return {
        "session_id":         sid,
        "processed_docs":     processed_docs,
        "primary":            primary,
        "merged_facts":       merged_facts,
        "mflags":             mflags,
        "tier1_ok":           tier1_ok,
        "tier1_missing":      tier1_missing,
        "tier2_score":        tier2_score,
        "tier2_missing":      tier2_missing,
        "hard_stops":           hard_stops,
        "soft_stops":           soft_stops,
        "doc_conflicts":        doc_conflicts,
        "normalized_differences": normalized_differences,
        "cross_form_issues":    cross_form_issues,
        "recommendations":      recommendations,
        "account_profile":      account_profile,
        "extra_forms_scored":   extra_forms_scored,
        "unique_low_conf":      unique_low_conf,
        "available_forms":      available_forms,
        "integrity":            integrity,
        "underwriting_consistency": underwriting,
    }


async def resolve_submission_integrity(
    session: dict,
    session_id: str,
    *,
    action: str,
    remove_doc_ids: Optional[List[str]] = None,
    user_id: Any = None,
) -> dict:
    """Resolve a pending Submission Integrity review for an existing session.

    action == 'remove_documents':
        Drop the documents in ``remove_doc_ids`` from the session and re-run the
        post-extraction pipeline on the REMAINING documents (no re-OCR — reuses
        the per-document facts already stored under session['docs']). The
        integrity verdict is re-assessed; if the package is now clean the review
        clears and recommendations + cross-form validation are produced.

    action == 'continue_anyway':
        Keep all documents but record an override (who/when/acknowledged
        entities) and proceed: recommendations + cross-form validation run and
        the review is cleared.

    Returns the same dict shape as run_extraction_pipeline().
    """
    from services.submission_integrity import build_override_record, cluster_documents

    docs = list(session.get("docs") or [])
    if not docs:
        raise ValueError("integrity_resolve_no_docs")

    if action == "remove_documents":
        remove = set(remove_doc_ids or [])
        if not remove:
            raise ValueError("integrity_resolve_no_doc_ids")
        remaining = [d for d in docs if str(d.get("doc_id")) not in remove]
        if not remaining:
            raise ValueError("integrity_resolve_all_removed")
        return await _finalize_pipeline(
            remaining, user_id or session.get("user_id"),
            session_id=session_id,
            confirmations=session.get("underwriting_confirmations") or {},
        )

    if action == "continue_anyway":
        prior_integrity = session.get("integrity") or {}
        override = build_override_record(
            user_id or session.get("user_id"),
            prior_integrity.get("detected_entities") or [],
        )
        return await _finalize_pipeline(
            docs, user_id or session.get("user_id"),
            session_id=session_id, integrity_override=override,
            confirmations=session.get("underwriting_confirmations") or {},
        )

    if action == "create_separate_submissions":
        # Split the package by likely insured into one processing session per
        # cluster (Beta Report §4.1 action item 5). The CURRENT session is reused
        # for the first cluster (so the user's existing session_id stays valid and
        # lands on a clean package); each additional cluster becomes a new session
        # the user can open from their submission history. Splitting IS the
        # resolution, so every resulting submission proceeds without re-pausing.
        uid = user_id or session.get("user_id")
        confirmations = session.get("underwriting_confirmations") or {}
        groups = cluster_documents(docs)
        identified = [g for g in groups if not g["unidentified"]]
        unident_ids = [i for g in groups if g["unidentified"] for i in g["doc_ids"]]

        # Nothing meaningful to split (single insured / unsplittable): fall back to
        # a recorded override so the user still proceeds cleanly on this session.
        if len(identified) < 2:
            override = build_override_record(
                uid, (session.get("integrity") or {}).get("detected_entities") or [],
            )
            result = await _finalize_pipeline(
                docs, uid, session_id=session_id, integrity_override=override,
                confirmations=confirmations,
            )
            result["created_submissions"] = [{
                "session_id": result["session_id"], "label": "All documents",
                "doc_count": len(docs), "primary": True,
            }]
            return result

        by_id = {str(d.get("doc_id")): d for d in docs}
        # Nameless supporting docs ride along with the FIRST identified insured
        # (they most often belong to the primary submission) — never dropped.
        if unident_ids:
            identified[0]["doc_ids"] = list(identified[0]["doc_ids"]) + unident_ids

        override = build_override_record(uid, [])
        created: List[dict] = []
        primary_result: Optional[dict] = None

        for g in identified:
            gdocs = [by_id[did] for did in g["doc_ids"] if did in by_id]
            if not gdocs:
                continue
            if primary_result is None:
                res = await _finalize_pipeline(
                    gdocs, uid, session_id=session_id, integrity_override=override,
                    confirmations=confirmations, submission_label=g["label"],
                )
                primary_result = res
                created.append({
                    "session_id": res["session_id"], "label": g["label"],
                    "doc_count": len(gdocs), "primary": True,
                })
            else:
                res = await _finalize_pipeline(
                    gdocs, uid, session_id=None, integrity_override=override,
                    submission_label=g["label"],
                )
                created.append({
                    "session_id": res["session_id"], "label": g["label"],
                    "doc_count": len(gdocs), "primary": False,
                })

        primary_result = dict(primary_result or {})
        primary_result["created_submissions"] = created
        logger.info(
            "create_separate_submissions: session=%s split into %d submissions %s",
            session_id, len(created), [c["session_id"] for c in created],
        )
        return primary_result

    raise ValueError(f"integrity_resolve_unknown_action:{action}")


async def reclassify_document(
    session: dict,
    session_id: str,
    *,
    doc_id: str,
    action: str,
    new_doc_type: Optional[str] = None,
    user_id: Any = None,
) -> dict:
    """Apply a manual document-classification correction and re-run downstream
    scoring/recommendations (Beta Report §4.2 action items #4–#6).

    Actions:
      • set_type — set the document's type to ``new_doc_type`` (manual
                   correction; e.g. Unknown → Underwriting Narrative). Clears any
                   prior scoring exclusion.
      • exclude  — exclude the document from scoring; it stays in the session for
                   display ("Exclude from scoring").
      • include  — re-include a document as a normal scoring participant (clears
                   both the exclusion and the supporting-only flag).
      • supporting_only — "Include as supporting document only": its facts
                   contribute to the merge but it is never selected as the
                   primary truth document.

    Re-runs _finalize_pipeline on the STORED documents (no re-OCR), so SQS, the
    narrative/loss-history pillars, recommendations, cross-form validation, and
    the integrity verdict all reflect the corrected classification. Mirrors
    resolve_submission_integrity()'s reuse pattern.
    """
    docs = list(session.get("docs") or [])
    if not docs:
        raise ValueError("reclassify_no_docs")

    target = next((d for d in docs if str(d.get("doc_id")) == str(doc_id)), None)
    if target is None:
        raise ValueError("reclassify_doc_not_found")

    prev_type = target.get("doc_type")

    if action == "set_type":
        nt = (new_doc_type or "").strip()
        if nt not in ALLOWED_DOC_TYPES:
            raise ValueError("reclassify_invalid_type")
        target["doc_type"]            = nt
        target["doc_type_overridden"] = True
        target["doc_type_source"]     = "manual"
        target["doc_type_confidence"] = "high"
        target["excluded"]            = False
        cls = dict(target.get("classification") or {})
        cls.update({"doc_type": nt, "source": "manual", "confidence": "high"})
        target["classification"] = cls
    elif action == "exclude":
        target["excluded"] = True
    elif action == "include":
        # Normal include: facts contribute AND the doc is eligible to be primary.
        target["excluded"]        = False
        target["supporting_only"] = False
    elif action == "supporting_only":
        # "Include as supporting document only" (Beta Report §4.2 item #6): facts
        # contribute to the merge, but the doc is never chosen as primary truth.
        target["excluded"]        = False
        target["supporting_only"] = True
    else:
        raise ValueError(f"reclassify_unknown_action:{action}")

    logger.info(
        "reclassify_document: session=%s doc=%s action=%s %s->%s (user=%s)",
        session_id, doc_id, action, prev_type,
        target.get("doc_type"), user_id or session.get("user_id"),
    )

    # Preserve a prior integrity override so a user who already chose "Continue
    # anyway" is not re-prompted by the re-assessment (doc_type changes never
    # alter the identity signatures the integrity check uses).
    prior_integrity = session.get("integrity") or {}
    override = prior_integrity.get("override") if prior_integrity.get("overridden") else None

    result = await _finalize_pipeline(
        docs, user_id or session.get("user_id"),
        session_id=session_id, integrity_override=override,
        confirmations=session.get("underwriting_confirmations") or {},
    )
    # Surface the before/after classification so the route can record an accurate
    # §4.2 audit row without re-deriving the previous type.
    result["reclassified"] = {
        "doc_id":            str(doc_id),
        "action":            action,
        "previous_doc_type": prev_type,
        "new_doc_type":      target.get("doc_type"),
    }
    return result


async def confirm_underwriting_value(
    session: dict,
    session_id: str,
    *,
    fact_key: str,
    value: Any,
    user_id: Any = None,
) -> dict:
    """Record a user-confirmed Core Underwriting Data value (Beta Report §4.3)
    and re-run the post-extraction pipeline so the confirmed value is applied
    consistently across every relevant form and into SQS scoring.

    Validates ``fact_key`` is reconcilable and ``value`` normalizes to a usable
    number, merges it into the session's confirmation map, then re-runs
    _finalize_pipeline on the STORED documents (no re-OCR), mirroring
    resolve_submission_integrity / reclassify_document. A prior integrity
    override is preserved so the user is not re-prompted for the review.
    """
    docs = list(session.get("docs") or [])
    if not docs:
        raise ValueError("underwriting_no_docs")

    # Raises ValueError(code) on unknown field / empty / unparseable value.
    canonical = validate_confirmation(fact_key, value)

    confirmations = dict(session.get("underwriting_confirmations") or {})
    confirmations[fact_key] = canonical

    logger.info(
        "confirm_underwriting_value: session=%s field=%s value=%r (user=%s)",
        session_id, fact_key, canonical, user_id or session.get("user_id"),
    )

    prior_integrity = session.get("integrity") or {}
    override = prior_integrity.get("override") if prior_integrity.get("overridden") else None

    return await _finalize_pipeline(
        docs, user_id or session.get("user_id"),
        session_id=session_id, integrity_override=override,
        confirmations=confirmations,
    )


async def apply_marketing_reason(
    session: dict,
    session_id: str,
    *,
    reason: str,
    user_id: Any = None,
) -> dict:
    """Apply the producer's "Why are you marketing this account?" answer and
    re-run FORM RECOMMENDATIONS so ACORD 101 escalates to its correct tier
    (DOUBTS-Workstream4 / Brent).

    Deliberately lightweight: it sets carrier_marketing_reason + derives
    prior_carrier_adverse_action on the already-merged session facts/flags, then
    recomputes ONLY the recommendation outputs (match_forms + account profile +
    extra-form scores). It does NOT re-run extraction or the hard/soft-stop
    pipeline, so cross-document and cross-form stops are left exactly as they
    were - the only stop this answer would add (a carrier-narrative advisory)
    surfaces on the next full SQS compute. The answer persists in the session
    facts/flags, so it also flows into later SQS scoring and Narrative Quality.
    """
    from services.form_service import (
        match_forms_deterministic, derive_account_profile, score_extra_forms,
        filter_available_forms, load_all_forms,
    )
    from services.arq_service import (
        _ADVERSE_CARRIER_REASONS, _CARRIER_MARKETING_OPTIONS, CARRIER_MARKETING_FIELD,
    )

    reason = (reason or "").strip()[:200]
    if not reason or not (reason in _CARRIER_MARKETING_OPTIONS or reason.startswith("Other")):
        raise ValueError("marketing_invalid_reason")

    facts = dict(session.get("facts") or {})
    flags = dict(session.get("flags") or {})

    facts[CARRIER_MARKETING_FIELD] = {
        "value": reason, "confidence": "client_arq", "source": "client_arq",
    }
    is_adverse = reason.lower() in _ADVERSE_CARRIER_REASONS
    flags["prior_carrier_adverse_action"] = is_adverse

    active_docs   = [d for d in (session.get("docs") or []) if not d.get("excluded")]
    combined_text = " ".join(d.get("text", "") for d in active_docs)

    recommendations = match_forms_deterministic(facts, flags, text=combined_text)
    account_profile = derive_account_profile(facts, flags, text=combined_text)
    triggered_ids   = {r["form_id"] for r in recommendations}
    extra_forms     = score_extra_forms(facts, triggered_ids, filter_available_forms(load_all_forms()))

    logger.info(
        "apply_marketing_reason: session=%s reason=%r adverse=%s (user=%s)",
        session_id, reason, is_adverse, user_id or session.get("user_id"),
    )

    await upd_processing_session(session_id, {
        "facts":           facts,
        "flags":           flags,
        "recommendations": recommendations,
        "account_profile": account_profile,
    })

    return {
        "session_id":                   session_id,
        "recommendations":              recommendations,
        "account_profile":              account_profile,
        "extra_forms_scored":           extra_forms,
        "mflags":                       flags,
        "prior_carrier_adverse_action": is_adverse,
        "carrier_marketing_reason":     reason,
    }
