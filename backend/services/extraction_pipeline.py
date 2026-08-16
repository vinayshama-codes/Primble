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
    detect_source_conflicts, ALLOWED_DOC_TYPES, apply_declared_absent_downgrades,
)
from utils.table_extractor import extract_tables_from_pdf
from services.form_service import (
    filter_available_forms, load_all_forms, match_forms, score_extra_forms,
    derive_account_profile,
)
from services.sqs_service import (
    check_tier1, check_tier2, evaluate_stops, check_doc_consistency,
    _has_explicit_follow_form,
)
from services.cross_form_validator import run_cross_form_validation, split_cross_form_issues
from services.issue_registry import make_issue, classify_legacy
from services.submission_integrity import assess_submission_integrity
from services.underwriting_consistency import (
    assess_underwriting_consistency, apply_confirmations, validate_confirmation,
    RECONCILABLE_FIELDS, RECONCILABLE_FIELD_KEYS, unresolved_withheld_keys,
)
from repositories.session_repository import new_processing_session, upd_processing_session

logger = logging.getLogger(__name__)


def _unwrap_scalar(v: Any) -> Any:
    """Unwrap the annotated {value, confidence} envelope to its scalar value."""
    if isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


# ── Attribution brackets for evaluate_stops() output (client feedback: "which
# document created the issue... and how to fix it") ──────────────────────────
# evaluate_stops() only ever sees the already-MERGED facts/flags (it has three
# call sites - here, arq_service.py, and the field-edit path in form_routes.py -
# none currently thread the source documents through), so it cannot attribute a
# stop to a document itself. These are narrow, POST-PROCESSING enrichments for
# the specific messages where an honest attribution is actually derivable from
# active_docs, applied only here (the fresh-upload path) where active_docs is
# already in scope. Anything not matched is left untouched rather than guessed.
_ADDRESS_FORMAT_PREFIXES = ("Address missing valid US state:", "Address missing ZIP code:")


def _enrich_stops_with_source(stops: list[str], active_docs: list) -> list[str]:
    out = []
    for msg in stops:
        if msg.startswith(_ADDRESS_FORMAT_PREFIXES):
            m = re.search(r": '(.+)'$", msg)
            quoted = m.group(1).strip().lower() if m else None
            srcs = list(dict.fromkeys(
                d.get("filename") for d in active_docs
                if quoted and str(_unwrap_scalar((d.get("facts") or {}).get("mailing_address")) or "").strip().lower() == quoted
            ))
            src_txt = ", ".join(s for s in srcs if s) or "the uploaded documents"
            out.append(
                f"{msg} (Source: {src_txt}. "
                "Fix: Correct the mailing address in the source document, or edit the address field directly.)"
            )
        elif msg == "Workers Comp detected but payroll is missing":
            # No document HAS this value (that is the whole issue) - honest
            # remediation only, no fabricated source.
            out.append(f"{msg} (Fix: Provide WC or total payroll - not present in any uploaded document.)")
        else:
            out.append(msg)
    return out


def _ensure_fix_hint(messages: list[str]) -> list[str]:
    """Guarantee every evaluate_stops()/run_field_validations() message carries
    a "Fix: ..." remediation line, matching the other stop sources (which all
    already include one - check_doc_consistency via its own _bracket() helper,
    cross_form_validator via split_cross_form_issues(), detect_source_conflicts
    and the underwriting reconciler directly). This is the one source with no
    built-in remediation text for most of its messages, which is what produced
    the "some warnings have a Fix line, most don't" inconsistency - so every
    message lacking one gets the same generic line appended, never overwriting
    a message that already has its own (e.g. the two _enrich_stops_with_source
    cases, which run before this and are left untouched)."""
    out = []
    for msg in messages:
        if "Fix: " in msg:
            out.append(msg)
        else:
            out.append(f"{msg} Fix: Review and correct this before proceeding.")
    return out


def _display_name_from_path(path: str) -> str:
    """Original filename for display: strip the UUID storage prefix added in
    form_routes.py (``<32-hex>_originalname.pdf`` → ``originalname.pdf``)."""
    raw = os.path.basename(path)
    parts = raw.split("_", 1)
    return parts[1] if len(parts) == 2 and len(parts[0]) == 32 and parts[0].isalnum() else raw


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


async def run_extraction_pipeline(
    file_paths: list[str],
    user_id: Any,
    *,
    progress_token: Optional[str] = None,
) -> dict:
    """Run OCR, extraction, validation, and form-matching for *file_paths*.

    Raises ``ValueError`` when no readable text is found (callers translate
    this into an appropriate error response or job failure).

    ``progress_token`` (optional) enables the live per-file progress overlay
    (Figure 1): each phase transition is written to a Redis side-channel the
    frontend polls. It is best-effort and never affects extraction. Callers that
    do not supply one (worker path, integrity/reclassify re-runs) get a no-op
    reporter, so their behaviour is unchanged.
    """
    from utils.progress_tracker import make_reporter

    processed_docs: list[dict] = []
    all_low_conf:   list       = []

    filenames = [_display_name_from_path(p) for p in file_paths]
    reporter = make_reporter(progress_token, user_id, filenames)
    await reporter.begin()

    for i, path in enumerate(file_paths):
        _display_name = filenames[i]
        await reporter.active(f"Reading {_display_name}…", stage="reading")
        text, low_conf = await extract_text(path)
        if len(text) < 30:
            # OCR produced nothing usable — mark this file's row complete so it
            # does not hang in the overlay, then skip extraction for it.
            await reporter.file_phase(i, "extracted")
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

        # OCR (and table parsing) complete for this file → advance its row to
        # "parsed" first (a real, distinct moment the overlay shows once, before
        # any per-file extraction row goes active), then to "extracting" right
        # before the fact-extraction LLM call begins.
        await reporter.file_phase(i, "parsed")

        # Document classification (Beta Report §4.2): content keywords + narrative
        # detection rules + filename signals. Returns the canonical type plus the
        # confidence/source/signals used (surfaced to the UI + audit).
        classification = classify_document(text, filename=_display_name)
        doc_type  = classification["doc_type"]
        await reporter.file_phase(i, "extracting", active=f"Extracting facts from {_display_name}…")
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
        await reporter.file_phase(i, "extracted")

    if not processed_docs:
        raise ValueError("no_readable_text")

    # The ONE first-extraction path: document text is new here, so this is the
    # only place the umbrella-date probe can learn anything (see its default).
    return await _finalize_pipeline(processed_docs, user_id, progress_reporter=reporter,
                                    probe_umbrella=True)


async def _finalize_pipeline(
    processed_docs: list[dict],
    user_id: Any,
    *,
    session_id: Optional[str] = None,
    integrity_override: Optional[dict] = None,
    confirmations: Optional[dict] = None,
    submission_label: Optional[str] = None,
    # DEFAULT OFF, and opted INTO by the one true first-extraction call site.
    # There are eight `_finalize_pipeline` callers and seven of them are
    # RE-RUNS (confirm a value, resolve, reclassify, exclude a doc, marketing
    # reason). Defaulting this ON meant every one of them re-ran the optional
    # whole-document umbrella-date LLM probe in the request path - which is the
    # multi-second wait on "Open to fix". Opt-in is the safe polarity: a re-run
    # added later is fast by default, and the probe can only be lost by
    # deliberately removing it from the extraction path.
    probe_umbrella: bool = False,
    progress_reporter: Any = None,
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
    # Progress reporter (Figure 1). Present only on a fresh upload; re-run callers
    # (integrity resolve / reclassify / confirm) and the worker path pass none →
    # a no-op reporter, so their behaviour is unchanged.
    from utils.progress_tracker import make_reporter
    reporter = progress_reporter if progress_reporter is not None else make_reporter(None, user_id, [])

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
    await reporter.package_phase("normalized", "Normalizing data across documents…")

    # ── Deterministic has_umbrella safety net (Umbrella / Excess Adequacy) ────
    # The umbrella pillar is EXCLUDED (scored N/A) whenever has_umbrella is false,
    # so a single missed LLM flag silently drops the entire umbrella evaluation -
    # the client's original "100% with no umbrella" complaint, inverted. When the
    # LLM did not set the flag, re-derive it from raw text using the SAME standard
    # the extraction prompt enforces: a distinct umbrella/excess section with a
    # STATED dollar amount (an umbrella/excess phrase in close proximity to a $
    # figure) - never the bare words "excess"/"limits"/"SIR" alone. Purely
    # additive (only ever sets the flag True), and intentionally scoped to this
    # one flag so no other pillar's behaviour changes. Runs BEFORE the umbrella
    # schedule / follow-form text fallback below, which is gated on this flag.
    if not mflags.get("has_umbrella"):
        _umb_scan = " ".join(
            str(d.get("text", "") or "") for d in active_docs if not d.get("excluded")
        ).lower()
        if re.search(
            r"(umbrella|excess)\s+(liability|coverage|policy)[^.\n]{0,60}\$\s*[\d,]+"
            r"|\$\s*[\d,]+[^.\n]{0,60}(umbrella|excess)\s+(liability|coverage|policy)",
            _umb_scan,
        ):
            mflags["has_umbrella"] = True

    # ── Declared-absent coverage lines (client report: Property / Crime / Cyber)
    # The mirror of the safety net above, and the ONLY thing allowed to turn a
    # coverage flag off. The flags are keyword-presence booleans OR'd across
    # every chunk, so a declarations page reading "PROPERTY - NO COVERAGE" set
    # has_property_coverage TRUE and the client got three lines ticked on a
    # policy that explicitly excludes all three. See
    # `apply_declared_absent_downgrades` for why it is hard to trigger: tight
    # proximity, unambiguous denial phrases only, and `coverage_lines` vetoes it.
    # Silence never downgrades anything.
    try:
        _absent_scan = " ".join(
            str(d.get("text", "") or "") for d in active_docs if not d.get("excluded")
        )
        _downgraded = apply_declared_absent_downgrades(mflags, merged_facts, _absent_scan)
        if _downgraded:
            logger.info(
                "declared-absent downgrade: %s — the document states these lines "
                "are not covered", ", ".join(sorted(_downgraded)),
            )
    except Exception as _ex:                       # noqa: BLE001 — advisory only
        logger.warning("declared-absent downgrade skipped: %s", _ex)

    # ── Dedicated umbrella-period pass (Umbrella / Excess period-alignment) ──
    # umbrella_effective_date / umbrella_expiration_date feed the cross-form
    # period-misalignment checks (cross_form_validator._check_umbrella_
    # attachment_stack, sqs_service.evaluate_stops) below and MUST be present
    # in merged_facts before those run - the main extraction prompt asks for
    # both (extraction_service.py RULE 1 + _EXTRACT_SCHEMA) but has been
    # observed on real documents to drop them under the weight of ~150 other
    # requested fields, even reading the umbrella's stated date correctly into
    # an adjacent field (a retroactive date) instead. One small, standalone
    # question - same fix already proven for map_facts_to_form's per-form
    # stamping of Policy_EffectiveDate_A/Policy_ExpirationDate_A on ACORD 131 -
    # closes the same gap here, one call for the whole document instead of
    # duplicating it per form. Gated on has_umbrella so a non-umbrella
    # submission never spends the call; only fills a fact the extraction
    # genuinely missed (never overrides one it got right); any failure is
    # logged and swallowed - this is advisory, must never block the pipeline.
    # SKIPPED ON A RE-RUN (C75). This probe reads DOCUMENT TEXT, and a
    # confirmation / reclassification / marketing-reason re-run changes FACTS,
    # never the text - so re-scanning can only ever produce the answer it
    # already produced. It was running on every "Open to fix": a whole-document
    # LLM scan (chunked at 60k chars) in the request path, which is the
    # multi-second delay the owner reported when resolving a stop. First
    # extraction is untouched, so nothing that works today stops working.
    if mflags.get("has_umbrella") and probe_umbrella:
        from services.pdf_service import _fetch_umbrella_period, _is_empty_llm_value
        _has_umb_eff = not _is_empty_llm_value(merged_facts.get("umbrella_effective_date"))
        _has_umb_exp = not _is_empty_llm_value(merged_facts.get("umbrella_expiration_date"))
        if not (_has_umb_eff and _has_umb_exp):
            _umb_text = " ".join(
                str(d.get("text", "") or "") for d in active_docs if not d.get("excluded")
            )
            if _umb_text.strip():
                try:
                    _umb_dates = await _fetch_umbrella_period(_umb_text)
                except Exception as exc:                          # noqa: BLE001 — advisory only
                    logger.warning("_finalize_pipeline: umbrella-period pass failed — %s", exc)
                    _umb_dates = None
                if _umb_dates:
                    if not _has_umb_eff and _umb_dates.get("umbrella_effective_date"):
                        merged_facts["umbrella_effective_date"] = _umb_dates["umbrella_effective_date"]
                    if not _has_umb_exp and _umb_dates.get("umbrella_expiration_date"):
                        merged_facts["umbrella_expiration_date"] = _umb_dates["umbrella_expiration_date"]

    # ── Wire loss-history flags that the scoring pillars depend on ───────────
    # Fix: no_prior_losses / narrative_states_no_losses were never set by the
    # pipeline — root cause of "score didn't move" after loss remediation (§6.4).
    # Use _attested_true (not raw truthiness) so a stored "No"/"false"/"0" is NOT
    # misread as an attestation - bool("No") is True in Python, which would have
    # wrongly credited a no-loss attestation for an insured that DOES have losses.
    from services.sqs_service import _attested_true
    from services.normalization import detect_no_loss_assertion
    _npl = merged_facts.get("loss_history_no_prior_losses_indicator")
    if isinstance(_npl, dict):
        _npl = _npl.get("value")
    if _attested_true(_npl):
        mflags["no_prior_losses"] = True

    # M5 fix: collect which fact keys were contributed by narrative docs so
    # _derive_evidence_labels can emit "stated_in_narrative" for them.
    _narrative_fact_keys: set = set()
    for _ndoc in active_docs:
        if _ndoc.get("excluded"):
            continue
        _ndoc_text = str(_ndoc.get("text", "") or "").lower()
        # Scan ALL non-excluded docs for no-loss phrases — not just narrative-typed ones.
        # A PDF containing both a narrative section ("no prior losses") and a loss run
        # table is classified as loss_run, so the old narrative-only gate missed it.
        # The conflict guard in _loss_history_conflict() (claims > 0 or incurred > 0)
        # prevents false positives: a clean loss run mentioning "no losses" won't fire
        # conflict because num_claims = 0. Threshold phrasing ("no losses exceed $10,000")
        # is excluded up front by detect_no_loss_assertion - see its docstring
        # (services/normalization.py) - the same detector pdf_service.py uses to
        # decide the LossHistory_NoPriorLossesIndicator_A checkbox, so the two
        # can never disagree with each other.
        if detect_no_loss_assertion(_ndoc_text):
            mflags["narrative_states_no_losses"] = True
        # Fact provenance attribution stays narrative-only — we only label facts as
        # "stated in narrative" when the source document is actually a narrative.
        if _ndoc.get("doc_type") == "narrative":
            _ndoc_facts = _ndoc.get("facts") or {}
            for _nk, _nv in _ndoc_facts.items():
                # Only credit keys that actually have a value in this narrative doc.
                _scalar = _nv.get("value") if isinstance(_nv, dict) else _nv
                if _scalar not in (None, "", "null", "none"):
                    _narrative_fact_keys.add(_nk)
    if _narrative_fact_keys:
        mflags["_narrative_fact_keys"] = list(_narrative_fact_keys)

    # AI-judged fallback for the literal phrase scan above. The keyword list can only
    # catch exact wordings; the extraction LLM (RULE 6: asserts_no_known_losses) reads
    # each document semantically and flags paraphrases the list misses ("loss-free",
    # "no adverse claim experience", "clean record", "claims-free for 5 years", ...).
    # Treated as narrative/document evidence - NOT a user attestation (no_prior_losses
    # stays reserved for the explicit questionnaire answer, preserving evidence-type
    # differentiation). The conflict guard in _loss_history_conflict still caps the
    # score when actual claims are present, so a false positive degrades into a
    # conflict prompt rather than wrongful credit - same safety property as the scan.
    if mflags.get("asserts_no_known_losses"):
        mflags["narrative_states_no_losses"] = True

    # §6.3: narrative_components are detected inside every extraction call (RULE 11
    # in the extraction prompt) and OR-merged across chunks and documents during
    # merge_facts. Promote from mflags into narrative_profile here so all
    # downstream paths (scoring, suppression, labelling, recommendations) read one
    # authoritative source. No extra LLM call — detection is free.
    try:
        from services.sqs_service import narrative_profile_fact_keys
        _narr_profile = mflags.get("narrative_components") or {}
        if _narr_profile:
            mflags["narrative_profile"] = _narr_profile
            _narrative_fact_keys |= narrative_profile_fact_keys(_narr_profile)
            mflags["_narrative_fact_keys"] = list(_narrative_fact_keys)
    except Exception as _narr_ex:  # pragma: no cover - defensive
        logger.warning("narrative profile aggregation skipped: %s", _narr_ex)

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
                if _need_follow_form and _has_explicit_follow_form(_utext):
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
        merged_facts = apply_confirmations(merged_facts, confirmations, docs=active_docs)

    tier1_ok, tier1_missing = check_tier1(merged_facts, mflags)

    tier2_score, tier2_missing = check_tier2(merged_facts, mflags)
    hard_stops, soft_stops     = evaluate_stops(merged_facts, mflags)
    # A run with NO stops looks identical to a run where the engine never fired,
    # and the owner asked exactly that question of a clean live package
    # (2026-08-13: "check why i am not getting expected warnings"). The answer
    # was "the facts satisfied every check", but proving it required
    # reconstructing the facts by hand. One line makes the next run answer it.
    logger.info(
        "evaluate_stops: hard=%d soft=%d%s", len(hard_stops), len(soft_stops),
        "" if (hard_stops or soft_stops) else
        " - every field-level check passed on the merged facts",
    )
    for _stop in hard_stops:
        logger.info("evaluate_stops HARD: %s", str(_stop)[:160])
    for _stop in soft_stops:
        logger.info("evaluate_stops SOFT: %s", str(_stop)[:160])

    # Structured, code-tagged mirror of every issue added to hard_stops/soft_stops
    # below (Figures 4/5: clustering + Required/Recommended/Binder-followup tiers).
    # Purely additive - never read by SQS capping or dismiss-credit logic, which
    # continue to use hard_stops/soft_stops exactly as before.
    #
    # evaluate_stops() (sqs_service.py, which itself starts from
    # utils/validators.py::run_field_validations()) is the ORIGINAL field-level
    # stop source and predates cross_form_validator.py - it returns plain,
    # uncoded strings, including the exact "Property Minimum Viable COPE
    # incomplete" hard stop. It carries no `code`, so each message is matched
    # against known phrases via classify_legacy_message() instead of a code
    # lookup - this must happen HERE, immediately, before any further stops are
    # appended below, so only what evaluate_stops() itself produced is tagged.
    # classify_legacy() returns the rule's REAL code (e.g.
    # "legacy_carrier_grade_cope"), which is what make_issue() needs to attach an
    # inline resolution and render "Open to fix". The f-string index code is only
    # a fallback for a message no rule matches - it stays unique per message so
    # two unclassified stops can never collapse onto one code.
    structured_issues: list[dict] = []
    hard_stops = _ensure_fix_hint(hard_stops)
    for _i, _msg in enumerate(hard_stops):
        _code, _cluster, _tier = classify_legacy(_msg, "hard_stop")
        structured_issues.append(make_issue(
            _code or f"legacy_hard_{_i}", "hard_stop", _msg, cluster=_cluster, tier=_tier))

    soft_stops = _ensure_fix_hint(_enrich_stops_with_source(soft_stops, active_docs))
    for _i, _msg in enumerate(soft_stops):
        _code, _cluster, _tier = classify_legacy(_msg, "soft_warning")
        structured_issues.append(make_issue(
            _code or f"legacy_soft_{_i}", "soft_warning", _msg, cluster=_cluster, tier=_tier))

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
                structured_issues.append(make_issue(f"doc_conflict_hard_{code}", "hard_stop", msg))
            elif issue.startswith("[warning]"):
                # Spec: DBAs/address/LOB/revenue mismatches are warnings, not blockers.
                rest = issue[len("[warning]"):].strip()
                # Capture the machine token before stripping it, so the warning can
                # still be clustered/tiered even though the user only sees plain text.
                _wcode_match = re.match(r"^(?:field|code)=(\S+)", rest)
                _wcode = _wcode_match.group(1) if _wcode_match else "conflict"
                # Strip the leading machine token (field=foo / code=foo) so the
                # user sees only the plain-language message (Beta Report P2 #28).
                rest = re.sub(r"^(?:field|code)=\S+\s*", "", rest)
                soft_stops = list(soft_stops) + [rest]
                structured_issues.append(make_issue(f"doc_conflict_warn_{_wcode}", "soft_warning", rest))
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
                structured_issues.append(make_issue("doc_conflict_warn_unknown", "soft_warning", issue))

    # ── Core Underwriting Data Consistency (Beta Report §4.3) ───────────────
    # Normalization-aware reconciliation of Gross Sales (and similar fields):
    # groups each value by its normalized form, attributes it to the source
    # document(s), and flags a non-blocking review when values materially
    # differ. Owns RECONCILABLE_FIELD_KEYS so the crude raw-string detector
    # below does not double-report them as formatting conflicts.
    underwriting = assess_underwriting_consistency(active_docs, merged_facts, confirmations)
    # Client 2026-08-15 ("unresolved conflicts must remain unresolved"): facts
    # whose cross-document conflict is unresolved are listed on the session
    # facts so the stamping layer withholds their value until the picker
    # confirms one (pdf_service._resolve_conflicted_fact_blank). Recomputed
    # every pipeline run - the confirm endpoint re-runs this pipeline, so a
    # confirmation clears the withhold with no extra wiring. The fact itself
    # stays in facts: scoring, warnings and the picker keep reading it.
    try:
        # UNION, never replace: merge_facts may already have withheld a limit
        # whose conflict is INSIDE one document (extraction_service.
        # _flag_intra_document_limit_conflicts). Overwriting here would silently
        # release exactly the value the client asked us to hold. A key the user
        # has now CONFIRMED is dropped from both sources.
        _confirmed = set((confirmations or {}).keys())
        _withheld = set(unresolved_withheld_keys(underwriting, confirmations))
        _withheld |= {
            k for k in (merged_facts.get("_uw_conflicted_keys") or [])
            if k not in _confirmed
        }
        if _withheld:
            merged_facts["_uw_conflicted_keys"] = sorted(_withheld)
            logger.info("underwriting: stamped-value withhold active for %s", sorted(_withheld))
        else:
            merged_facts.pop("_uw_conflicted_keys", None)
    except Exception as _wex:  # noqa: BLE001 — never block the pipeline
        logger.warning("underwriting: withheld-key computation failed: %s", _wex)
    if underwriting.get("review_required"):
        # ── BLOCKING MEANS HARD STOP, AND RELEVANCE IS A PRECONDITION (C75) ───
        # Two owner rules applied here, both to the same loop.
        #
        # SEVERITY. The client's Property Integrity directive - quoted verbatim
        # in underwriting_consistency.GENERATION_BLOCKING_RECONCILABLE_KEYS -
        # is "generate a warning and require review BEFORE FORMS ARE
        # GENERATED". That is blocking, and `calculate_package_sqs` has always
        # treated it as a hard stop (it caps the score at 60). The display
        # called it a warning, so the producer saw a soft item that was
        # actually costing 8 points and holding up generation. Owner's rule:
        # "if anything can be blocking, put it in hard stop". The two
        # DECLARED sets in underwriting_consistency are the authority - no
        # local list, so adding a key there is still a one-line change.
        #
        # RELEVANCE. Owner: "this is not a mandatory hard stop, it should only
        # be shown if declaration page has some relevant data". A building
        # value the documents disagree about cannot block anything on a
        # package that has no property coverage - there is no ACORD 140 to
        # generate and no box for the number. The flag is the dec page's own
        # statement (and it is already downgraded by the declared-absent scan
        # when the document says "No Coverage"), so this gates on evidence
        # rather than on a guess. Irrelevant conflicts stay a warning; they are
        # never silently dropped.
        try:
            from services.underwriting_consistency import (
                HARD_STOP_RECONCILABLE_KEYS, GENERATION_BLOCKING_RECONCILABLE_KEYS,
            )
            _blocking_keys = set(HARD_STOP_RECONCILABLE_KEYS) | set(
                GENERATION_BLOCKING_RECONCILABLE_KEYS)
        except Exception:                                  # noqa: BLE001
            _blocking_keys = set()
        # Keys whose conflict only matters when that coverage actually exists.
        _relevance_flag = {
            "property_building_value": "has_property_coverage",
            "property_bpp_value":      "has_property_coverage",
        }
        for f in underwriting["fields"]:
            if f.get("review_required"):
                _key = f.get("fact_key", "field")
                _uw_msg = (
                    f"{f['label']}: documents disagree "
                    f"({', '.join(v['display'] for v in f['values'])}). "
                    "Fix: Confirm the correct value to apply it across forms."
                )
                _needs_flag = _relevance_flag.get(_key)
                _relevant = (not _needs_flag) or bool(mflags.get(_needs_flag))
                _blocking = _key in _blocking_keys and _relevant
                if _blocking:
                    hard_stops = list(hard_stops) + [_uw_msg]
                else:
                    soft_stops = list(soft_stops) + [_uw_msg]
                    if _needs_flag and not _relevant:
                        logger.info(
                            "underwriting %s conflict kept as a warning - %s is "
                            "false, so this cannot block form generation",
                            _key, _needs_flag,
                        )
                structured_issues.append(make_issue(
                    f"underwriting_reconciliation_{_key}",
                    "hard_stop" if _blocking else "soft_warning", _uw_msg,
                ))

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
            # Union the keys the reconciler actually assessed (curated + any
            # auto-discovered scalar fields when full-field reconciliation is on)
            # so a field owned by the picker is never double-reported here.
            skip_fields=set(RECONCILABLE_FIELD_KEYS)
            | _consistency_owned
            | set(underwriting.get("assessed_keys") or []),
            # Carry the real fact key back (client #1: the display message no
            # longer contains it, so the old `for '<field>'` regex-scrape is gone -
            # the code is now derived from the actual key, structurally).
            return_fields=True,
        )
        if source_conflicts:
            logger.info("Source conflicts detected across docs: %d", len(source_conflicts))
            for _sc_field, _sc_msg, _sc_is_carrier in source_conflicts:
                soft_stops = list(soft_stops) + [_sc_msg]
                _sc_code = f"source_conflict_{'carrier_' if _sc_is_carrier else ''}{_sc_field}"
                structured_issues.append(make_issue(_sc_code, "soft_warning", _sc_msg))

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
        for fld in _ocr_review_fields:
            _ocr_msg = f"Low OCR confidence on critical field — confirm: {fld}"
            soft_stops = list(soft_stops) + [_ocr_msg]
            structured_issues.append(make_issue(f"ocr_low_confidence_{fld}", "soft_warning", _ocr_msg))

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
        # ── A SUGGESTION MAY NOT BECOME A BLOCKER (owner's decision, C75) ─────
        # `triggered_ids` here is the RECOMMENDED forms - nothing is selected
        # yet at extraction time. So a cross-form rule scoped to a form the
        # producer never chose could raise a HARD STOP about that form's own
        # missing data. Client report: "there should not be any Builders Risk
        # questions or an ACORD 133 - there is no builders risk exposure", and
        # the ACORD 133 rule fires purely because ACORD_133 landed in
        # `triggered_ids`. Compounded by the fact that a hard stop caps the
        # score, so a form we merely SUGGESTED cost the producer 8 points.
        #
        # Generic by construction: every cross-form rule is form-scoped, so
        # this demotes the whole class rather than special-casing builders
        # risk. The issue is NOT discarded - it becomes a warning, stays
        # visible with its own card, and returns to full hard-stop force the
        # moment the producer actually selects that form (the post-selection
        # path re-runs this validation with the SELECTED ids).
        if cf_hard:
            logger.info(
                "Cross-form hard stops demoted to warnings pre-selection "
                "(no form chosen yet): %s", cf_hard,
            )
            soft_stops = list(soft_stops) + cf_hard
            cf_soft = list(cf_soft) + cf_hard
            cf_hard = []
        if cf_soft:
            soft_stops = list(soft_stops) + [m for m in cf_soft if m not in soft_stops]
        for _cf_issue in cross_form_issues:
            _t = _cf_issue.get("type", "soft_warning")
            # Same demotion on the structured (card) copy, so the card's
            # severity matches the array it now lives in.
            if _t == "hard_stop":
                _t = "soft_warning"
            structured_issues.append(make_issue(
                _cf_issue.get("code", "cross_form_issue"),
                _t,
                _cf_issue.get("message", ""),
                _cf_issue.get("forms"),
            ))

    # Human-friendly label for the submissions history (Beta Report §4.1). Prefer
    # an explicit label (e.g. a split cluster's insured name from "Create separate
    # submissions") over the merged applicant name so a split child never falls
    # back to "Unknown Applicant" when its own applicant_name failed to extract.
    _applicant_lbl = _unwrap_scalar(merged_facts.get("applicant_name"))
    _applicant_lbl = str(_applicant_lbl).strip() if _applicant_lbl else ""
    session_label  = (str(submission_label).strip() if submission_label else "") or _applicant_lbl or None

    await reporter.package_phase("scored", "Scoring the submission…")

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
        "structured_issues":    structured_issues,
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

    # Session is persisted → the submission is form-ready. Marking done AFTER the
    # DB write means a poll that sees done=true can rely on the session existing.
    await reporter.done(sid)

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
        "structured_issues":    structured_issues,
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
            session_id=session_id, probe_umbrella=False,
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


# Corrected types whose extraction differs from the default path. Re-running
# extraction on a correction TO one of these recovers behaviour the first
# (mis-classified) pass skipped — Loss Runs get the claim-count text backstop and
# a larger page budget; Schedules get a larger page budget. Every other type uses
# the default extraction path, so a re-run would only repeat identical work and is
# skipped to avoid a needless LLM call (Beta Report §4.2 item #5).
_REEXTRACT_DOC_TYPES = {"loss_run", "schedule"}


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
                   prior scoring exclusion. When the corrected type uses
                   type-specific extraction (Loss Runs / Schedules), the document
                   is re-extracted from its stored text (no re-OCR) so the new
                   type's extraction behaviour is applied.
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

        # §4.2 item #5: re-run extraction when the corrected type uses
        # type-specific extraction behaviour the first (mis-classified) pass
        # skipped. Reuses the stored OCR text (no re-OCR). Non-fatal — on failure
        # we keep the previously extracted facts so the correction still applies.
        if nt in _REEXTRACT_DOC_TYPES and target.get("text"):
            try:
                _raw = await extract_facts_long(
                    target["text"], nt,
                    low_confidence_tokens=target.get("low_confidence_tokens") or [],
                )
                _ex = _validate_extraction_output(_raw, nt)
                target["facts"] = _ex.get("facts", {})
                target["flags"] = _ex.get("flags", {})
                target["manual_confirmation_required"] = _ex.get("manual_confirmation_required") or []
                target["truncation_warning"] = _ex.get("truncation_warning")
                logger.info("reclassify: re-extracted doc=%s as %s", doc_id, nt)
            except Exception as _reex:
                logger.warning(
                    "reclassify: re-extraction failed doc=%s type=%s — keeping prior facts: %s",
                    doc_id, nt, _reex,
                )
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
    active_docs = [d for d in docs if not d.get("excluded")] or docs

    # Raises ValueError(code) on unknown field / empty / unparseable value.
    # docs=active_docs lets an auto-discovered (non-curated) field validate too
    # — see underwriting_consistency._resolve_reconcilable_cfg.
    canonical = validate_confirmation(fact_key, value, docs=active_docs)

    confirmations = dict(session.get("underwriting_confirmations") or {})

    # Figure 3 "apply to all": look up linked fields using the PRE-confirm state
    # (so fact_key is still assessed as an open conflict and carries its
    # linked_fields) and apply the SAME confirmed value to every linked field
    # that (a) is itself an open conflict right now and (b) has no confirmation
    # yet - never overwrite an explicit prior choice on another field. Best-effort:
    # any failure here just skips the auto-apply, it never blocks the primary
    # confirmation below.
    linked_applied: List[str] = []
    try:
        pre = assess_underwriting_consistency(active_docs, session.get("facts") or {}, confirmations)
        target = next((f for f in pre.get("fields") or [] if f["fact_key"] == fact_key), None)
        for link in (target.get("linked_fields") if target else None) or []:
            lk = link["fact_key"]
            if lk in confirmations:
                continue
            try:
                confirmations[lk] = validate_confirmation(lk, canonical, docs=active_docs)
                linked_applied.append(lk)
            except ValueError:
                continue  # not a valid value for this field's kind - skip, never fail the request
    except Exception as exc:                              # pragma: no cover - defensive
        logger.warning("confirm_underwriting_value: linked-field lookup skipped for %s - %s", fact_key, exc)

    confirmations[fact_key] = canonical

    logger.info(
        "confirm_underwriting_value: session=%s field=%s value=%r linked_applied=%s (user=%s)",
        session_id, fact_key, canonical, linked_applied, user_id or session.get("user_id"),
    )

    prior_integrity = session.get("integrity") or {}
    override = prior_integrity.get("override") if prior_integrity.get("overridden") else None

    return await _finalize_pipeline(
        docs, user_id or session.get("user_id"),
        session_id=session_id, integrity_override=override,
        confirmations=confirmations, probe_umbrella=False,
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

    # Figure 6 NOTE: once forms have been generated the producer can no longer
    # return to this screen, so the answer is locked - re-answering here would
    # silently rewrite the audit trail for a submission that already shipped.
    if session.get("generated_forms"):
        raise ValueError("marketing_reason_locked")

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

    # Figure 6: persist a controlled reason_code + free-text reason_note as a
    # DURABLE audit row (separate from the session facts blob above, which is
    # nulled out by the facts-retention job and would not survive for an
    # underwriter to review later). "Other: <text>" splits into code="Other" +
    # the typed note; every other option is stored as its own code with no note.
    if reason.startswith("Other"):
        _reason_code = "Other"
        _reason_note = reason[len("Other"):].lstrip(":").strip() or None
    else:
        _reason_code = reason
        _reason_note = None
    from services.audit_service import upsert_marketing_reason
    await upsert_marketing_reason(
        session_id, str(user_id or session.get("user_id") or ""),
        _reason_code, _reason_note, is_adverse,
    )

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
