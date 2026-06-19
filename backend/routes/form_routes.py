import asyncio
import logging
import os
import uuid
import zipfile
from fastapi import Request

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, File, Response
from fastapi.responses import JSONResponse, Response
from typing import List

from config.database import get_pool
from config.settings import TEMPLATE_DIR, UPLOAD_DIR, SUPPORTED_IMG, MAX_UPLOAD_SIZE_BYTES, MAX_FILES_PER_UPLOAD, ENABLE_ASYNC_PROCESSING, ENABLE_COMBINED_GAP_FILL
from utils.crypto import decrypt_field
from utils.json_logging import get_trace_id
from utils.helpers import safe_join, check_payment_access
from services.job_queue import get_job_queue, JOB_TYPE_EXTRACTION, JOB_TYPE_FORM_GENERATION, STATUS_PROCESSING, STATUS_COMPLETED, STATUS_FAILED
from models.schemas import (
    BulkFormSelectionRequest, FormSelectionRequest, PDFUpdateRequest,
    SubmissionIntegrityResolveRequest, DocumentReclassifyRequest,
    UnderwritingConfirmRequest, MarketingReasonRequest,
)
from repositories.session_repository import (
    get_processing_session, new_processing_session, upd_processing_session,
)
from services.auth_service import get_current_user
from services.extraction_pipeline import (
    run_extraction_pipeline, resolve_submission_integrity, reclassify_document,
    confirm_underwriting_value, apply_marketing_reason, ProcessingIntegrityError,
)
from services.extraction_service import (
    extract_facts_long, merge_facts, select_primary_truth,
    DOC_TYPE_LABELS, ALLOWED_DOC_TYPES,
)
from services.form_service import (
    filter_available_forms, load_all_forms, match_forms, process_single_form,
    score_extra_forms,
)
from services.ocr_service import extract_text, extract_zip
from services.pdf_service import (
    extract_form_fields_with_positions, get_page_dims_pikepdf, regenerate_pdf_for_form,
    fill_pdf, _is_signature_field, _load_fieldmap,
    apply_acord125_missing_field_highlights,
    extract_form_schema, compute_form_gaps, combined_gap_fill,
)
from services.sqs_service import (
    check_tier1, check_tier2, cross_validate, evaluate_stops, calculate_sqs,
    check_doc_consistency, calculate_package_sqs, SQS_MODEL_VERSION, classify_stops,
    _check_loss_run_insured_match, _extract_narrative_doc_text,
)
from services.audit_service import (
    log_recommendations_presented,
    log_field_change,
    mark_recommendation_resolved,
    log_integrity_assessed,
    log_integrity_resolution,
    log_document_reclassified,
    log_underwriting_confirmation,
)
from utils.rate_limiter import check_upload_rate_limit
from utils.concurrency import try_acquire_heavy, release_heavy
from utils.mime_validator import validate_file_mime
from utils.virus_scanner import scan_file_bytes

router = APIRouter(tags=["forms"])
logger = logging.getLogger(__name__)


def _humanize_fact(v):
    """Render an extracted fact value as a readable string for the
    'Review extracted data' view. Unwraps {value, confidence} envelopes and
    flattens lists/dicts (e.g. locations) into a compact human-readable form."""
    if isinstance(v, dict) and "value" in v:
        v = v.get("value")
    if isinstance(v, list):
        return ", ".join(s for s in (_humanize_fact(i) for i in v) if s)
    if isinstance(v, dict):
        parts = []
        for kk, vv in v.items():
            sv = _humanize_fact(vv)
            if sv:
                parts.append(f"{str(kk).replace('_', ' ')}: {sv}")
        return "; ".join(parts)
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("", "null", "none") else s


def _doc_summary_entry(d: dict, primary_filename: str = "") -> dict:
    """Build a uniform per-document summary for the frontend (Beta Report §4.2).

    Carries the canonical doc_type plus the classification metadata the UI needs
    to show confidence, the reason it was classified, and the manual-correction
    affordance (doc_id + whether the type was user-overridden).
    """
    dt  = d.get("doc_type") or "unknown"
    cls = d.get("classification") or {}
    return {
        "doc_id":                d.get("doc_id"),
        "filename":              d.get("filename", ""),
        "doc_type":              dt,
        "doc_type_label":        DOC_TYPE_LABELS.get(dt, dt.replace("_", " ").title()),
        "doc_type_confidence":   d.get("doc_type_confidence") or cls.get("confidence"),
        "doc_type_source":       d.get("doc_type_source") or cls.get("source"),
        "doc_type_overridden":   bool(d.get("doc_type_overridden")),
        "excluded":              bool(d.get("excluded")),
        "supporting_only":       bool(d.get("supporting_only")),
        "narrative_categories":  cls.get("narrative_categories", []),
        "is_primary":            bool(primary_filename) and d.get("filename") == primary_filename,
        "low_confidence_tokens": d.get("low_confidence_tokens", []),
        "truncation_warning":    d.get("truncation_warning"),
    }

# Dedicated pool for sync form-processing work (process_single_form, fill_pdf).
# Explicit size prevents the default pool from growing unbounded under burst load.
# 6 = 2 forms per user × 3 concurrent users; keep below WEB_CONCURRENCY × cpu_count.
import concurrent.futures as _cf
_FORM_EXECUTOR = _cf.ThreadPoolExecutor(
    max_workers=int(os.getenv("FORM_EXECUTOR_WORKERS", "6")),
    thread_name_prefix="form-gen",
)


async def _bg_lite_generate(session_id: str) -> None:
    """Background task: generate the top recommended form for essentials users and store SQS in session."""
    try:
        session = await get_processing_session(session_id)
        recommendations = session.get("recommendations", [])
        form_ids = [r["form_id"] for r in recommendations][:1]
        if not form_ids:
            logger.info("bg_lite: session=%s no recommendations — skipping", session_id)
            return

        loop = asyncio.get_event_loop()
        results = {}
        for form_id in form_ids:
            form_meta = next((f for f in session.get("all_forms", []) if f["form_id"] == form_id), None)
            if not form_meta:
                continue
            try:
                tpl = safe_join(TEMPLATE_DIR, form_meta["template_file"])
            except ValueError:
                continue
            if not os.path.exists(tpl):
                continue
            try:
                result = await loop.run_in_executor(None, process_single_form, form_meta, session)
                results[form_id] = result
            except Exception as ex:
                logger.error("bg_lite: form generation error form=%s session=%s: %s", form_id, session_id, ex)

        if not results:
            logger.warning("bg_lite: no forms generated for session=%s", session_id)
            return

        cross_issues_raw = cross_validate(session.get("facts", {}), session.get("flags", {}), form_ids)
        seen_msgs, cross_issues = set(), []
        for issue in cross_issues_raw:
            msg = issue.get("message", "")
            if msg not in seen_msgs:
                seen_msgs.add(msg)
                cross_issues.append(issue)

        await upd_processing_session(session_id, {
            "selected_form_ids": form_ids,
            "generated_forms": results,
            "active_form_id": form_ids[0] if form_ids else None,
            "cross_issues_last": cross_issues,
        })
        sqs_list = [r["sqs"] for r in results.values() if r.get("sqs")]
        avg_score = round(sum(s.get("sqs_score", 0) for s in sqs_list) / max(len(sqs_list), 1)) if sqs_list else 0
        logger.info("bg_lite: session=%s form=%s sqs=%d", session_id, form_ids[0], avg_score)
    except Exception as ex:
        logger.error("bg_lite: unexpected error session=%s: %s", session_id, ex)


# ASYNC-SAFE
@router.post("/api/upload-declaration")
async def upload_declaration(
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    await check_upload_rate_limit(current_user["id"])

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payment_status, subscription_tier, downloads_used FROM users WHERE id = $1",
            current_user["id"],
        )
    if row:
        r = dict(row)
        ps = r.get("payment_status", "ok") or "ok"
        if ps == "suspended":   raise HTTPException(403, "Account suspended due to non-payment.")
        if ps == "archived":    raise HTTPException(403, "Account archived. Contact support@primble.ai.")
        if ps == "soft_locked": raise HTTPException(403, "Account disabled. Please update your billing.")
        if r.get("subscription_tier", "free") == "free" and int(r.get("downloads_used", 0) or 0) >= 3:
            from fastapi.responses import JSONResponse as _JSONResponse
            return _JSONResponse(
                {"success": False, "upgrade_required": True,
                 "message": "You've used all 3 free submissions. Upgrade to continue."},
                status_code=403,
            )

    uploaded_paths: list = []
    all_paths: list      = []
    _sem_token           = False
    _job_id              = None
    _async_mode          = False
    try:
        if len(files) > MAX_FILES_PER_UPLOAD:
            raise HTTPException(400, f"Too many files — maximum {MAX_FILES_PER_UPLOAD} per upload.")

        # Read all file bytes first so we can enforce the aggregate size cap before
        # touching the filesystem.  10 × 50 MB = 500 MB per request without this guard.
        contents = []
        for f in files:
            contents.append((f, await f.read(MAX_UPLOAD_SIZE_BYTES + 1)))

        total_bytes = sum(len(c) for _, c in contents)
        if total_bytes > MAX_UPLOAD_SIZE_BYTES * MAX_FILES_PER_UPLOAD:
            raise HTTPException(
                413,
                f"Total upload size exceeds the aggregate limit "
                f"({MAX_UPLOAD_SIZE_BYTES * MAX_FILES_PER_UPLOAD // 1024 // 1024} MB).",
            )

        for f, content in contents:
            if len(content) > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    413,
                    f"File '{f.filename}' exceeds the "
                    f"{MAX_UPLOAD_SIZE_BYTES // 1024 // 1024} MB limit.",
                )
            ext = os.path.splitext((f.filename or "upload").lower())[1]
            mime_ok, mime_err = validate_file_mime(content, ext)
            if not mime_ok:
                raise HTTPException(400, mime_err)
            scan_file_bytes(content, f.filename or "upload")
            safe_name = f"{uuid.uuid4().hex}_{os.path.basename(f.filename or 'upload')}"
            path = os.path.join(UPLOAD_DIR, safe_name)
            await asyncio.get_event_loop().run_in_executor(
                None, lambda p=path, c=content: open(p, "wb").write(c)
            )
            uploaded_paths.append(path)
            if ext == ".zip":
                try:
                    with zipfile.ZipFile(path, "r") as zf:
                        for info in zf.infolist():
                            inner_ext = os.path.splitext(info.filename.lower())[1]
                            if inner_ext not in ({".pdf"} | set(SUPPORTED_IMG)):
                                continue
                            inner_data = zf.read(info.filename)
                            inner_mime_ok, inner_mime_err = validate_file_mime(inner_data, inner_ext)
                            if not inner_mime_ok:
                                logger.warning(f"ZIP inner file failed MIME validation, skipping: {info.filename} — {inner_mime_err}")
                                continue
                            scan_file_bytes(inner_data, info.filename)
                            safe_inner = f"{uuid.uuid4().hex}_{os.path.basename(info.filename)}"
                            inner_path = os.path.join(UPLOAD_DIR, safe_inner)
                            await asyncio.get_event_loop().run_in_executor(
                                None, lambda p=inner_path, d=inner_data: open(p, "wb").write(d)
                            )
                            all_paths.append(inner_path)
                except zipfile.BadZipFile:
                    raise HTTPException(400, f"File '{f.filename}' is not a valid ZIP archive.")
            elif ext == ".pdf" or ext in SUPPORTED_IMG:
                all_paths.append(path)

        # Release the in-memory upload buffer now that every file is on disk.
        # The extraction pipeline reads from `all_paths`; the raw bytes are no
        # longer needed and holding them costs up to ~500 MB of heap on a
        # 10-file × 50 MB upload while the pipeline runs.
        contents = None

        if not all_paths:
            raise HTTPException(400, "No supported files found")

        # Acquire the heavy semaphore for synchronous processing.
        _sem_token = await try_acquire_heavy()
        if not _sem_token:
            raise HTTPException(
                429,
                "Server busy — too many concurrent requests. Please retry in 30 seconds.",
                headers={"Retry-After": "30"},
            )

        _queue = get_job_queue()
        _in_flight = await _queue.count_user_active_jobs(current_user["id"])
        if _in_flight >= 5:
            raise HTTPException(429, "Too many jobs in progress. Please wait.")
        _job_payload = {
            "file_paths": all_paths,
            "user_id":    str(current_user["id"]),
        }
        _job_id = await _queue.enqueue(JOB_TYPE_EXTRACTION, _job_payload, str(current_user["id"]))
        await _queue.update_status(_job_id, STATUS_PROCESSING, progress_message="Extracting text from documents...")

        try:
            pipeline_result = await run_extraction_pipeline(all_paths, current_user["id"])
        except ValueError:
            raise HTTPException(400, "No readable text found in uploaded files")
        except ProcessingIntegrityError:
            raise HTTPException(422, "Document processing failed an integrity check. Please re-upload your files or contact support.")

        processed_docs     = pipeline_result["processed_docs"]
        primary            = pipeline_result["primary"]
        merged_facts       = pipeline_result["merged_facts"]
        mflags             = pipeline_result["mflags"]
        tier1_ok           = pipeline_result["tier1_ok"]
        tier1_missing      = pipeline_result["tier1_missing"]
        tier2_score        = pipeline_result["tier2_score"]
        tier2_missing      = pipeline_result["tier2_missing"]
        hard_stops           = pipeline_result["hard_stops"]
        soft_stops           = pipeline_result["soft_stops"]
        doc_conflicts        = pipeline_result["doc_conflicts"]
        normalized_differences = pipeline_result.get("normalized_differences") or []
        recommendations    = pipeline_result["recommendations"]
        account_profile    = pipeline_result.get("account_profile") or {}
        extra_forms_scored = pipeline_result["extra_forms_scored"]
        unique_low_conf    = pipeline_result["unique_low_conf"]
        integrity          = pipeline_result.get("integrity") or {}
        sid                = pipeline_result["session_id"]

        # NOTE: Tier-1 / ACORD 125 baseline is no longer a hard gate.
        # When required fields are missing, we surface them as soft warnings
        # on the recommendations / SQS screens and let the broker continue.
        if not tier1_ok and tier1_missing:
            _tier1_warnings = [f"ACORD 125 minimum field missing: {m}" for m in tier1_missing]
            soft_stops = list(soft_stops) + _tier1_warnings

        # Record the Submission Integrity verdict (Beta Report §4.1). Best-effort:
        # captures whether a multi-insured warning was raised so a later override
        # can be traced to the warning that prompted it.
        await log_integrity_assessed(sid, str(current_user["id"]), integrity)

        if _job_id:
            await _queue.update_status(_job_id, STATUS_COMPLETED, result={"session_id": sid})

        # For essentials tier — auto-generate top form in background so SQS/ARQ are ready.
        # Suppressed while a Submission Integrity review is pending: we must not
        # auto-generate on a package that may belong to multiple insureds.
        if (current_user.get("subscription_tier") == "essentials"
                and recommendations
                and not integrity.get("review_required")):
            asyncio.ensure_future(_bg_lite_generate(sid))

        truncation_warnings = [
            {"filename": d["filename"], "warning": d["truncation_warning"]}
            for d in processed_docs if d.get("truncation_warning")
        ]

        _can_proceed_warn, _remaining_hard, _downgraded = classify_stops(hard_stops, mflags)

        return JSONResponse({
            "success": True, "session_id": sid,
            "doc_summary": [_doc_summary_entry(d, primary["filename"]) for d in processed_docs],
            "available_doc_types": [{"value": t, "label": DOC_TYPE_LABELS[t]} for t in ALLOWED_DOC_TYPES],
            "primary_doc": primary["filename"], "flags": mflags,
            "tier2_score": tier2_score, "tier2_missing": tier2_missing,
            "hard_stops": _remaining_hard,
            "soft_stops": soft_stops + _downgraded,
            "can_proceed_with_warning": _can_proceed_warn,
            "warning_stops": _downgraded,
            "doc_conflicts": doc_conflicts,
            "normalized_differences": normalized_differences,
            "recommendations": recommendations,
            "account_profile": account_profile,
            "low_confidence_tokens": unique_low_conf,
            "truncation_warnings": truncation_warnings,
            "all_available_forms": extra_forms_scored,
            # Submission Integrity Validation (Beta Report §4.1). When
            # review_required is true the frontend must show the integrity
            # review step BEFORE form selection/generation.
            "integrity": integrity,
            "integrity_review_required": bool(integrity.get("review_required")),
            # Core Underwriting Data Consistency (Beta Report §4.3) — Gross Sales
            # and similar normalized fields, with source attribution + conflicts.
            "underwriting_consistency": pipeline_result.get("underwriting_consistency") or {},
        })
    except HTTPException as ex:
        if _job_id:
            try:
                await get_job_queue().update_status(_job_id, STATUS_FAILED, error=str(ex.detail))
            except Exception:
                pass
        raise
    except Exception as ex:
        logger.error(f"Upload error [trace={get_trace_id()}]: {ex}", exc_info=True)
        if _job_id:
            try:
                await get_job_queue().update_status(_job_id, STATUS_FAILED, error=type(ex).__name__)
            except Exception:
                pass
        raise HTTPException(500, "Processing failed. Please try again.")
    finally:
        if _sem_token:
            await release_heavy(_sem_token)
        if not _async_mode:
            for _p in set(uploaded_paths) | set(all_paths):
                try:
                    os.remove(_p)
                except OSError:
                    pass
        elif _async_mode:
            for _p in set(uploaded_paths) | set(all_paths):
                try:
                    os.remove(_p)
                except OSError:
                    pass


# ASYNC-SAFE
def enforce_integrity_gate(session: dict) -> None:
    """Block downstream processing while a Submission Integrity review is pending.

    Raises HTTP 409 with the integrity verdict when the package was flagged as
    likely multi-insured and the user has not yet removed documents or chosen to
    continue. This is the server-side guarantee that unrelated documents are not
    silently processed as one clean submission (Beta Report §4.1 acceptance
    criteria). The override is recorded on the session, so once 'Continue
    anyway' is chosen this gate stays open.
    """
    integrity = session.get("integrity") or {}
    if integrity.get("review_required") and not integrity.get("overridden"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "submission_integrity_review_required",
                "message": integrity.get("message")
                or "Submission integrity review required before continuing.",
                "integrity": integrity,
            },
        )


# ASYNC-SAFE
def enforce_building_value_gate(session: dict) -> None:
    """Block form generation while a building-value conflict is unresolved.

    Client Property Integrity directive: when building values appear duplicated,
    inflated, or inconsistent across documents, "require review before forms are
    generated." The cross-document reconciler (underwriting_consistency) already
    detects the conflict and surfaces the picker; this gate makes that review
    mandatory before generation. Confirming the correct value (the existing
    underwriting-confirm flow) clears review_required and opens the gate. Scoring
    and recommendations are unaffected — only generation is gated.
    """
    from services.underwriting_consistency import GENERATION_BLOCKING_RECONCILABLE_KEYS
    uw = session.get("underwriting_consistency") or {}
    blocking = [
        f for f in (uw.get("fields") or [])
        if f.get("fact_key") in GENERATION_BLOCKING_RECONCILABLE_KEYS
        and f.get("review_required")
    ]
    if blocking:
        _label = blocking[0].get("label") or "Building Value"
        raise HTTPException(
            status_code=409,
            detail={
                "error": "building_value_review_required",
                "message": f"{_label} differs across the submitted documents. "
                "Confirm the correct value before generating forms.",
                "underwriting_consistency": uw,
                "fields": blocking,
            },
        )


@router.post("/api/submission-integrity/resolve")
async def submission_integrity_resolve(
    req: SubmissionIntegrityResolveRequest,
    current_user: dict = Depends(get_current_user),
):
    """Resolve a pending Submission Integrity review (Beta Report §4.1).

    Actions:
      • remove_documents — drop the selected documents and re-assess on the rest
        (no re-OCR; reuses stored per-document facts).
      • continue_anyway  — keep all documents, record the override, and proceed.
    """
    session = await get_processing_session(req.session_id)
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")

    if req.action not in ("remove_documents", "continue_anyway", "create_separate_submissions"):
        raise HTTPException(
            400,
            "Unsupported action. Use 'remove_documents', 'continue_anyway', "
            "or 'create_separate_submissions'.",
        )

    try:
        result = await resolve_submission_integrity(
            session,
            req.session_id,
            action=req.action,
            remove_doc_ids=req.remove_doc_ids,
            user_id=str(current_user["id"]),
        )
    except ValueError as ve:
        code = str(ve)
        if code == "integrity_resolve_all_removed":
            raise HTTPException(400, "You cannot remove every document. Keep at least one.")
        if code in ("integrity_resolve_no_doc_ids",):
            raise HTTPException(400, "Select at least one document to remove.")
        if code in ("integrity_resolve_no_docs",):
            raise HTTPException(409, "This submission has no stored documents to re-assess.")
        logger.error(f"submission_integrity_resolve invalid request [trace={get_trace_id()}]: {ve}")
        raise HTTPException(400, "Could not resolve the submission integrity review.")
    except Exception as ex:
        logger.error(f"submission_integrity_resolve error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "Failed to resolve submission integrity review.")

    integrity = result.get("integrity") or {}

    # Record how the user resolved the integrity review (Beta Report §4.1) —
    # including whether they overrode the multi-insured warning. Uses the PRIOR
    # verdict (the one shown to the user) for status/entities, since the result's
    # verdict is the post-resolution re-assessment.
    await log_integrity_resolution(
        result["session_id"], str(current_user["id"]), req.action,
        integrity=session.get("integrity") or integrity,
        removed_doc_ids=req.remove_doc_ids,
        created_submissions=result.get("created_submissions") or [],
    )

    _can_proceed_warn, _remaining_hard, _downgraded = classify_stops(
        result.get("hard_stops") or [], result.get("mflags") or {}
    )
    return JSONResponse({
        "success": True,
        "session_id": result["session_id"],
        "action": req.action,
        "integrity": integrity,
        "integrity_review_required": bool(integrity.get("review_required")),
        "recommendations": result.get("recommendations") or [],
        "account_profile": result.get("account_profile") or {},
        "all_available_forms": result.get("extra_forms_scored") or [],
        "hard_stops": _remaining_hard,
        "soft_stops": (result.get("soft_stops") or []) + _downgraded,
        "can_proceed_with_warning": _can_proceed_warn,
        "doc_conflicts": result.get("doc_conflicts") or [],
        "normalized_differences": result.get("normalized_differences") or [],
        "doc_summary": [
            _doc_summary_entry(d, (result.get("primary") or {}).get("filename", ""))
            for d in (result.get("processed_docs") or [])
        ],
        "available_doc_types": [{"value": t, "label": DOC_TYPE_LABELS[t]} for t in ALLOWED_DOC_TYPES],
        "underwriting_consistency": result.get("underwriting_consistency") or {},
        # Populated only for the 'create_separate_submissions' action: the list of
        # submissions the package was split into (first entry is this session).
        "created_submissions": result.get("created_submissions") or [],
    })


@router.post("/api/document/reclassify")
async def document_reclassify(
    req: DocumentReclassifyRequest,
    current_user: dict = Depends(get_current_user),
):
    """Manually correct a document's classification and recalculate downstream
    scoring/recommendations (Beta Report §4.2 action items #4–#6).

    Re-runs the post-extraction pipeline on the stored documents (no re-OCR), so
    the corrected type updates merged facts, SQS (narrative & loss-history
    pillars), recommendations, cross-form validation, and the integrity verdict.
    """
    if req.action not in ("set_type", "exclude", "include", "supporting_only"):
        raise HTTPException(400, "Unsupported action. Use 'set_type', 'exclude', 'include', or 'supporting_only'.")

    session = await get_processing_session(req.session_id)
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")

    try:
        result = await reclassify_document(
            session, req.session_id,
            doc_id=req.doc_id, action=req.action,
            new_doc_type=req.new_doc_type, user_id=str(current_user["id"]),
        )
    except ValueError as ve:
        code = str(ve)
        if code == "reclassify_doc_not_found":
            raise HTTPException(404, "Document not found in this submission.")
        if code == "reclassify_no_docs":
            raise HTTPException(409, "This submission has no stored documents to reclassify.")
        if code == "reclassify_invalid_type":
            raise HTTPException(400, "Unsupported document type.")
        logger.error(f"document_reclassify invalid request [trace={get_trace_id()}]: {ve}")
        raise HTTPException(400, "Could not apply the document classification change.")
    except Exception as ex:
        logger.error(f"document_reclassify error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "Failed to reclassify the document.")

    # Record the manual classification correction (Beta Report §4.2) with the
    # before/after document type surfaced by reclassify_document().
    _reclass = result.get("reclassified") or {}
    await log_document_reclassified(
        result["session_id"], str(current_user["id"]),
        doc_id=_reclass.get("doc_id") or req.doc_id,
        action=req.action,
        previous_doc_type=_reclass.get("previous_doc_type"),
        new_doc_type=_reclass.get("new_doc_type"),
    )

    integrity = result.get("integrity") or {}
    _can_proceed_warn, _remaining_hard, _downgraded = classify_stops(
        result.get("hard_stops") or [], result.get("mflags") or {}
    )
    return JSONResponse({
        "success": True,
        "session_id": result["session_id"],
        "action": req.action,
        "doc_summary": [
            _doc_summary_entry(d, (result.get("primary") or {}).get("filename", ""))
            for d in (result.get("processed_docs") or [])
        ],
        "available_doc_types": [{"value": t, "label": DOC_TYPE_LABELS[t]} for t in ALLOWED_DOC_TYPES],
        "recommendations": result.get("recommendations") or [],
        "account_profile": result.get("account_profile") or {},
        "all_available_forms": result.get("extra_forms_scored") or [],
        "flags": result.get("mflags") or {},
        "hard_stops": _remaining_hard,
        "soft_stops": (result.get("soft_stops") or []) + _downgraded,
        "can_proceed_with_warning": _can_proceed_warn,
        "warning_stops": _downgraded,
        "doc_conflicts": result.get("doc_conflicts") or [],
        "normalized_differences": result.get("normalized_differences") or [],
        "tier2_score": result.get("tier2_score"),
        "tier2_missing": result.get("tier2_missing") or [],
        "integrity": integrity,
        "integrity_review_required": bool(integrity.get("review_required")),
        "underwriting_consistency": result.get("underwriting_consistency") or {},
    })


@router.post("/api/session/{session_id}/marketing-reason")
async def session_marketing_reason(
    session_id: str,
    req: MarketingReasonRequest,
    current_user: dict = Depends(get_current_user),
):
    """Capture the producer's "Why are you marketing this account?" answer on the
    recommendation screen and re-run form recommendations so ACORD 101 escalates
    to its correct tier (DOUBTS-Workstream4 / Brent).

    The answer persists into the session facts/flags, so it also flows into later
    SQS scoring and Narrative Quality. Lightweight: it recomputes only the
    recommendation outputs (no re-OCR, hard/soft stops left untouched).

    NOTE: session_id is a PATH segment (not the body) so this never collides with
    GET /api/session/{session_id}, which previously caught the POST and 405'd it.
    """
    session = await get_processing_session(session_id)
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")

    try:
        result = await apply_marketing_reason(
            session, session_id,
            reason=req.reason, user_id=str(current_user["id"]),
        )
    except ValueError as ve:
        if str(ve) == "marketing_invalid_reason":
            raise HTTPException(400, "Unsupported marketing reason.")
        logger.error(f"session_marketing_reason invalid request [trace={get_trace_id()}]: {ve}")
        raise HTTPException(400, "Could not apply the marketing reason.")
    except Exception as ex:
        logger.error(f"session_marketing_reason error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "Failed to update recommendations.")

    return JSONResponse({
        "success": True,
        "session_id": result["session_id"],
        "recommendations": result.get("recommendations") or [],
        "account_profile": result.get("account_profile") or {},
        "all_available_forms": result.get("extra_forms_scored") or [],
        "flags": result.get("mflags") or {},
        "prior_carrier_adverse_action": bool(result.get("prior_carrier_adverse_action")),
    })


@router.post("/api/underwriting/confirm-value")
async def underwriting_confirm_value(
    req: UnderwritingConfirmRequest,
    current_user: dict = Depends(get_current_user),
):
    """Confirm the correct value for a Core Underwriting Data element
    (Beta Report §4.3, e.g. Gross Sales) when source documents disagree.

    Records the confirmation and re-runs the post-extraction pipeline on the
    stored documents (no re-OCR), applying the confirmed value consistently
    across every relevant form and into SQS scoring.
    """
    session = await get_processing_session(req.session_id)
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")

    try:
        result = await confirm_underwriting_value(
            session, req.session_id,
            fact_key=req.fact_key, value=req.value, user_id=str(current_user["id"]),
        )
    except ValueError as ve:
        code = str(ve)
        if code == "underwriting_unknown_field":
            raise HTTPException(400, "This field is not a reconcilable underwriting data element.")
        if code == "underwriting_empty_value":
            raise HTTPException(400, "Enter a value to confirm.")
        if code == "underwriting_invalid_value":
            raise HTTPException(400, "Enter a valid value (e.g. a dollar amount like $1,000,000).")
        if code == "underwriting_no_docs":
            raise HTTPException(409, "This submission has no stored documents.")
        logger.error(f"underwriting_confirm_value invalid request [trace={get_trace_id()}]: {ve}")
        raise HTTPException(400, "Could not confirm the value.")
    except Exception as ex:
        logger.error(f"underwriting_confirm_value error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "Failed to confirm the underwriting value.")

    # Resolve the human label for this fact key so the audit row is readable
    # without joining to another table. Imported lazily to avoid a circular import.
    from services.underwriting_consistency import RECONCILABLE_FIELDS
    _uw_label = (RECONCILABLE_FIELDS.get(req.fact_key) or {}).get("label", req.fact_key)
    # Previous value: what was in merged_facts BEFORE this confirmation (from
    # the session loaded at the top of this handler, before confirm_underwriting_value ran).
    from services.extraction_service import _fv as _efv
    _prev_facts = session.get("facts") or {}
    _prev_val = _efv(_prev_facts, req.fact_key)
    _prev_str = str(_prev_val).strip() if _prev_val is not None else None
    await log_underwriting_confirmation(
        req.session_id,
        str(current_user["id"]),
        fact_key=req.fact_key,
        label=_uw_label,
        confirmed_value=req.value,
        previous_value=_prev_str,
    )

    integrity = result.get("integrity") or {}
    _can_proceed_warn, _remaining_hard, _downgraded = classify_stops(
        result.get("hard_stops") or [], result.get("mflags") or {}
    )
    return JSONResponse({
        "success": True,
        "session_id": result["session_id"],
        "fact_key": req.fact_key,
        "underwriting_consistency": result.get("underwriting_consistency") or {},
        "recommendations": result.get("recommendations") or [],
        "account_profile": result.get("account_profile") or {},
        "all_available_forms": result.get("extra_forms_scored") or [],
        "flags": result.get("mflags") or {},
        "hard_stops": _remaining_hard,
        "soft_stops": (result.get("soft_stops") or []) + _downgraded,
        "can_proceed_with_warning": _can_proceed_warn,
        "warning_stops": _downgraded,
        "tier2_score": result.get("tier2_score"),
        "tier2_missing": result.get("tier2_missing") or [],
        "normalized_differences": result.get("normalized_differences") or [],
        "doc_conflicts": result.get("doc_conflicts") or [],
        "integrity": integrity,
        "integrity_review_required": bool(integrity.get("review_required")),
    })


@router.post("/api/select-forms-bulk")
async def select_forms_bulk(req: BulkFormSelectionRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("subscription_tier") == "free":
        used = int(current_user.get("downloads_used", 0) or 0)
        if used >= 3:
            raise HTTPException(403, "Upgrade required to access form generation.")

    if current_user.get("subscription_tier") == "essentials":
        raise HTTPException(403, "Form generation is not included in the Essentials tier. Use lite analysis instead.")

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payment_status FROM users WHERE id = $1", current_user["id"]
        )
    if row:
        ps = dict(row).get("payment_status", "ok") or "ok"
        if ps in ("soft_locked", "suspended", "archived"):
            raise HTTPException(403, "Account disabled. Please update your billing.")

    session = await get_processing_session(req.session_id)
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")

    # Submission Integrity gate (Beta Report §4.1): do not generate forms on a
    # package that may belong to multiple insureds until the user has reviewed.
    enforce_integrity_gate(session)
    # Building-value review gate (client Property Integrity): do not generate forms
    # while building values conflict across documents and remain unconfirmed.
    enforce_building_value_gate(session)

    await check_upload_rate_limit(str(current_user["id"]))

    _queue = get_job_queue()
    _in_flight = await _queue.count_user_active_jobs(current_user["id"])
    if _in_flight >= 5:
        raise HTTPException(429, "Too many jobs in progress. Please wait.")
    _fg_payload = {
        "session_id": req.session_id,
        "form_ids":   req.form_ids,
        "user_id":    str(current_user["id"]),
    }
    _job_id = await _queue.enqueue(JOB_TYPE_FORM_GENERATION, _fg_payload, str(current_user["id"]), session_id=req.session_id)
    await _queue.update_status(_job_id, STATUS_PROCESSING, progress_message="Generating ACORD forms...")

    if ENABLE_ASYNC_PROCESSING:
        return JSONResponse(
            status_code=202,
            content={"job_id": _job_id, "session_id": req.session_id, "poll_url": f"/api/jobs/{_job_id}/status"},
        )

    # NOTE: We no longer acquire the global heavy-ops semaphore here.
    # Concurrency is bounded per-user (count_user_active_jobs >= 5 above) and
    # globally by the LLM rate-limit semaphore (utils/llm_limiter.py) which
    # caps simultaneous OpenAI calls. Holding a heavy-ops slot for the whole
    # multi-form request serialised users behind a 3-wide gate and made the
    # 4th concurrent user receive HTTP 429 even though there was free capacity.
    _sem_token = None
    results      = {}
    combined_ids = req.form_ids

    try:
        loop = asyncio.get_event_loop()

        # ── Stages 4-6: Combined cross-form gap fill (opt-in via flag) ───────
        # Phase A — compute Pass 1 + 1.5 gaps per form in parallel (no LLM).
        # Phase B — run ONE shared GPT pass across the union of gap fields.
        # Phase C — generate each form, feeding it its slice of the shared
        #            GPT result so Pass 2 is replaced by a dict lookup.
        # When the flag is off, this whole block is skipped and the historic
        # per-form path runs unchanged.
        per_form_pre_filled: dict = {}
        if ENABLE_COMBINED_GAP_FILL:
            try:
                async def _compute_gaps_one(form_id: str):
                    form_meta = next((f for f in session["all_forms"] if f["form_id"] == form_id), None)
                    if not form_meta:
                        return form_id, None, None
                    try:
                        tpl = safe_join(TEMPLATE_DIR, form_meta["template_file"])
                    except ValueError:
                        return form_id, None, None
                    if not os.path.exists(tpl):
                        return form_id, None, None
                    schema = await loop.run_in_executor(
                        _FORM_EXECUTOR, extract_form_schema, tpl, form_id,
                    )
                    facts_with_flags = {**session["facts"], **session.get("flags", {})}
                    _mapped, unmatched, _det = await loop.run_in_executor(
                        _FORM_EXECUTOR, compute_form_gaps, form_id, schema, facts_with_flags,
                    )
                    return form_id, schema, unmatched

                gap_previews = await asyncio.gather(
                    *[_compute_gaps_one(fid) for fid in req.form_ids],
                    return_exceptions=True,
                )

                forms_to_unmatched: dict = {}
                for item in gap_previews:
                    if isinstance(item, Exception):
                        logger.warning("combined_gap_fill: gap preview exception: %s", item)
                        continue
                    fid, _schema, unmatched = item
                    if unmatched:
                        forms_to_unmatched[fid] = unmatched

                if forms_to_unmatched:
                    raw_text = " ".join(d.get("text", "") for d in session.get("docs", []))
                    facts_with_flags = {**session["facts"], **session.get("flags", {})}
                    per_form_pre_filled = await loop.run_in_executor(
                        _FORM_EXECUTOR,
                        combined_gap_fill,
                        forms_to_unmatched, facts_with_flags, raw_text,
                    )
                else:
                    logger.info("combined_gap_fill: no gaps after Pass 1 + 1.5 — skipping shared GPT pass")
            except Exception as ex:
                # Any failure in the combined path falls back to the historic
                # per-form GPT path (process_single_form with pre_filled_gpt=None).
                logger.error("combined_gap_fill: fatal error, falling back per-form: %s", ex)
                per_form_pre_filled = {}

        async def _generate_one(form_id: str):
            form_meta = next((f for f in session["all_forms"] if f["form_id"] == form_id), None)
            if not form_meta:
                return form_id, None
            try:
                tpl = safe_join(TEMPLATE_DIR, form_meta["template_file"])
            except ValueError:
                logger.warning("form_routes: unsafe template path blocked for form %s", form_id)
                return form_id, None
            if not os.path.exists(tpl):
                return form_id, None
            try:
                pre_filled = per_form_pre_filled.get(form_id) if per_form_pre_filled else None
                result = await loop.run_in_executor(
                    _FORM_EXECUTOR, process_single_form, form_meta, session, pre_filled,
                )
                return form_id, result
            except Exception as ex:
                logger.error(f"Error processing {form_id}: {ex}")
                return form_id, None

        gen_results = await asyncio.gather(
            *[_generate_one(fid) for fid in req.form_ids],
            return_exceptions=True,
        )
        for item in gen_results:
            if isinstance(item, Exception):
                logger.error(f"select_forms_bulk: gather exception: {item}")
                continue
            fid, result = item
            if result is not None:
                results[fid] = result

        if not results:
            await _queue.update_status(_job_id, STATUS_FAILED, error="No forms could be generated")
            raise HTTPException(400, "No forms could be generated")

        cross_issues_raw     = cross_validate(session["facts"], session["flags"], combined_ids)
        seen_msgs            = set()
        cross_issues_deduped = []
        for issue in cross_issues_raw:
            msg = issue.get("message", "")
            if msg not in seen_msgs:
                seen_msgs.add(msg)
                cross_issues_deduped.append(issue)

        await upd_processing_session(req.session_id, {
            "selected_form_ids": combined_ids, "generated_forms": results,
            "active_form_id": combined_ids[0] if combined_ids else None,
            "cross_issues_last": cross_issues_deduped,
        })

        summary = {}
        for fid, r in results.items():
            summary[fid] = {"form_id": r["form_id"], "form_name": r["form_name"], "form": r["form"],
                             "sqs": r["sqs"], "fields_mapped": sum(1 for v in r["mapped"].values() if v is not None),
                             "schema_size": len(r["schema"])}

        sqs_results_list = [r["sqs"] for r in results.values() if r.get("sqs")]
        try:
            package_sqs = calculate_package_sqs(
                facts=session["facts"],
                flags=session["flags"],
                form_results=sqs_results_list,
                cross_issues=cross_issues_deduped,
                hard_stops=session.get("hard_stops", []),
                soft_stops=session.get("soft_stops", []),
                session_data=session,
                session_id=req.session_id,
                user_id=str(current_user["id"]),
                calculation_stage="form_generated",
            )
            logger.info(f"package_sqs calculated: score={package_sqs.get('package_sqs_score')}, tier={package_sqs.get('tier')}")
        except Exception as _pkg_ex:
            logger.error(f"calculate_package_sqs failed: {_pkg_ex}", exc_info=True)
            package_sqs = None

        # Persist so the async (202) refetch path and page reloads can recover it.
        try:
            await upd_processing_session(req.session_id, {"package_sqs": package_sqs})
        except Exception as _persist_ex:
            logger.warning(f"persist package_sqs failed: {_persist_ex}")

        for fid, r in results.items():
            sqs_data = r.get("sqs")
            if sqs_data and sqs_data.get("recommendations"):
                try:
                    await log_recommendations_presented(
                        session_id=req.session_id,
                        user_id=str(current_user["id"]),
                        sqs_result=sqs_data,
                        model_version=SQS_MODEL_VERSION,
                    )
                except Exception as _audit_ex:
                    logger.warning(f"Audit log failed for {fid}: {_audit_ex}")

        await _queue.update_status(_job_id, STATUS_COMPLETED, result={"session_id": req.session_id, "form_ids": combined_ids})

        return JSONResponse({
            "success": True,
            "generated": summary,
            "form_ids": combined_ids,
            "cross_issues": cross_issues_deduped,
            "package_sqs": package_sqs,
        })
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"select_forms_bulk error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "Form generation failed. Please try again.")
    finally:
        # _sem_token is None in the new flow; release_heavy is a no-op then.
        # Kept for safety in case future code paths re-acquire it.
        if _sem_token:
            await release_heavy(_sem_token)


@router.post("/api/select-form")
async def select_form(req: FormSelectionRequest, current_user: dict = Depends(get_current_user)):
    return await select_forms_bulk(BulkFormSelectionRequest(session_id=req.session_id, form_ids=[req.selected_form_id]), current_user)


@router.post("/api/lite/generate-internal/{session_id}")
async def lite_generate_internal(session_id: str, current_user: dict = Depends(get_current_user)):
    """Silently generate forms for scoring/ARQ — forms are never exposed or downloadable."""
    if current_user.get("subscription_tier") == "free":
        used = int(current_user.get("downloads_used", 0) or 0)
        if used >= 3:
            raise HTTPException(403, "Upgrade required.")

    session = await get_processing_session(session_id)
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    recommendations = session.get("recommendations", [])
    form_ids = [r["form_id"] for r in recommendations][:1]  # essentials: top form only

    if not form_ids:
        raise HTTPException(400, "No recommended forms found in session.")

    results = {}
    loop = asyncio.get_event_loop()
    for form_id in form_ids:
        form_meta = next((f for f in session["all_forms"] if f["form_id"] == form_id), None)
        if not form_meta:
            continue
        try:
            tpl = safe_join(TEMPLATE_DIR, form_meta["template_file"])
        except ValueError:
            logger.warning("form_routes: unsafe template path blocked for form %s", form_id)
            continue
        if not os.path.exists(tpl):
            continue
        try:
            result = await loop.run_in_executor(None, process_single_form, form_meta, session)
            results[form_id] = result
        except Exception as ex:
            logger.error(f"Lite internal generation error for {form_id}: {ex}")

    if not results:
        raise HTTPException(400, "No forms could be generated internally.")

    cross_issues_raw = cross_validate(session["facts"], session["flags"], form_ids)
    seen_msgs, cross_issues_deduped = set(), []
    for issue in cross_issues_raw:
        msg = issue.get("message", "")
        if msg not in seen_msgs:
            seen_msgs.add(msg); cross_issues_deduped.append(issue)

    await upd_processing_session(session_id, {
        "selected_form_ids": form_ids,
        "generated_forms": results,
        "active_form_id": form_ids[0] if form_ids else None,
        "cross_issues_last": cross_issues_deduped,
    })

    sqs_list  = [r["sqs"] for r in results.values() if r.get("sqs")]
    avg_score = round(sum(s.get("sqs_score", 0) for s in sqs_list) / max(len(sqs_list), 1)) if sqs_list else 0
    first_sqs = sqs_list[0] if sqs_list else {}
    return JSONResponse({
        "success": True,
        "sqs": {**first_sqs, "sqs_score": avg_score},
        "hard_stops": session.get("hard_stops", []),
        "soft_stops": session.get("soft_stops", []),
        "flags": session.get("flags", {}),
        "compliance_checklist": first_sqs.get("compliance_checklist", []),
    })


@router.get("/api/fields/{session_id}/{form_id}")
async def get_form_fields(
    session_id: str, form_id: str,
    current_user: dict = Depends(get_current_user),
):
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form '{form_id}' not found")
    r   = generated[form_id]
    try:
        tpl = safe_join(TEMPLATE_DIR, r["form"]["template_file"])
    except ValueError:
        raise HTTPException(400, "Invalid template path")
    if not os.path.exists(tpl):
        raise HTTPException(404, "Template not found")
    _loop   = asyncio.get_event_loop()
    fields    = await _loop.run_in_executor(None, extract_form_fields_with_positions, tpl)
    page_dims = await _loop.run_in_executor(None, get_page_dims_pikepdf, tpl)
    field_state = r.get("field_state") or r.get("mapped", {})
    confidence  = dict(r.get("confidence", {}))
    client_filled = set(r.get("client_filled_fields", []))

    # Correct stale "filled" labels for AI-mapped fields. Sessions processed before
    # the __ai_mapped__ fix stored "filled" instead of "low_confidence" for LLM-mapped
    # fields. Re-derive the correct label now so highlights appear without re-processing.
    _, ai_set = await _loop.run_in_executor(None, _load_fieldmap, form_id)
    needs_save = False
    for field_name, conf_label in list(confidence.items()):
        if conf_label == "filled" and field_name in ai_set:
            val = field_state.get(field_name)
            has_val = val is not None and str(val).strip() not in ("", "null", "None")
            if has_val:
                confidence[field_name] = "low_confidence"
                needs_save = True

    if needs_save:
        generated[form_id]["confidence"] = confidence
        await upd_processing_session(session_id, {"generated_forms": generated})

    confidence = apply_acord125_missing_field_highlights(
        form_id, proc_session.get("facts", {}), field_state, confidence
    )

    for f in fields:
        name = f["name"]
        if name in field_state:
            sv = field_state[name]
            f["value"] = str(sv) if sv is not None and str(sv) not in ("null", "None") else ""
        else:
            f["value"] = ""
        f["confidence_label"] = confidence.get(name, "")
        f["client_filled"]    = name in client_filled
    return JSONResponse({"success": True, "fields": fields, "page_dims": page_dims})


@router.post("/api/mark-client-filled/{session_id}/{form_id}")
async def mark_client_filled(
    session_id: str, form_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """After client fills ARQ, mark those fields as 'filled' confidence and store client_filled list."""
    body        = await request.json()
    field_names = body.get("field_names", [])
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form '{form_id}' not found")
    r = generated[form_id]
    confidence = r.get("confidence", {})
    for fn in field_names:
        confidence[fn] = "client_arq"
    r["confidence"]           = confidence
    r["client_filled_fields"] = list(set(r.get("client_filled_fields", []) + field_names))
    generated[form_id] = r
    await upd_processing_session(session_id, {"generated_forms": generated})
    return JSONResponse({"success": True})


@router.get("/api/get-pdf/{session_id}/{form_id}")
async def get_pdf(
    session_id: str, form_id: str,
    current_user: dict = Depends(get_current_user),
):
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form {form_id} not generated")
    pdf_bytes = await asyncio.get_event_loop().run_in_executor(
        None, regenerate_pdf_for_form, proc_session, form_id
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={form_id}_preview.pdf",
                 "Cache-Control": "no-store, no-cache, must-revalidate"},
    )


# ASYNC-SAFE
@router.post("/api/update-pdf")
async def update_pdf(req: PDFUpdateRequest, current_user: dict = Depends(get_current_user)):
    import hashlib, json
    session   = await get_processing_session(req.session_id)
    if session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = session.get("generated_forms", {})
    active_id = session.get("active_form_id")

    form_id = req.field_updates.pop("__form_id__", active_id)
    req.field_updates.pop("__signed__", None)
    cleared_sig_fields_raw = req.field_updates.pop("__cleared_sig_fields__", "[]")
    try:
        cleared_sig_fields = set(json.loads(cleared_sig_fields_raw))
    except Exception:
        cleared_sig_fields = set()

    if not form_id or form_id not in generated:
        raise HTTPException(400, "No active form to update")

    _sem_token = await try_acquire_heavy()
    if not _sem_token:
        raise HTTPException(
            429,
            "Server busy — too many concurrent requests. Please retry in 30 seconds.",
            headers={"Retry-After": "30"},
        )

    try:
        r             = generated[form_id]
        current_state = r.get("field_state", dict(r.get("mapped", {})))
        prev_state    = dict(current_state)
        current_state.update(req.field_updates)
        confidence = dict(r.get("confidence", {}))

        # Correct stale "filled" labels for AI-mapped fields before applying edits.
        _, ai_set = _load_fieldmap(form_id)
        for field_name, conf_label in list(confidence.items()):
            if conf_label == "filled" and field_name in ai_set:
                val = current_state.get(field_name)
                has_val = val is not None and str(val).strip() not in ("", "null", "None")
                if has_val:
                    confidence[field_name] = "low_confidence"

        for k, v in req.field_updates.items():
            val = str(v).strip() if v is not None else ""
            if val and val not in ("null", "None"):
                # Only promote missing_required → filled when user fills the field.
                # Leave low_confidence fields as-is so pink highlights persist —
                # AI-guessed fields stay pink until explicitly reviewed/refreshed.
                if confidence.get(k) == "missing_required":
                    confidence[k] = "filled"
            else:
                # Field cleared — demote to low_confidence unless ARQ-filled
                if confidence.get(k) not in ("client_arq", "missing_required"):
                    confidence[k] = "low_confidence"

        confidence = apply_acord125_missing_field_highlights(
            form_id, session.get("facts", {}), current_state, confidence
        )

        from services.pdf_service import _ACORD_FIELD_RULES
        updated_facts = dict(session.get("facts") or {})
        for pdf_field, new_val in req.field_updates.items():
            val_str = str(new_val).strip() if new_val is not None else ""
            for pattern, fact_key in _ACORD_FIELD_RULES:
                if fact_key and not fact_key.startswith("_") and pattern in pdf_field:
                    updated_facts[fact_key] = val_str if val_str not in ("", "null", "None") else None
                    break

        # Re-evaluate stops against the LATEST facts so SQS can actually improve
        # when the producer fixes a field. Without this, stale hard_stops from
        # extraction would keep capping the score regardless of user edits.
        from services.cross_form_validator import (
            run_cross_form_validation, split_cross_form_issues,
        )

        # Recompute coverage flags from the latest facts (downgrade-only).
        # When the user clears the last fact backing a coverage flag, the
        # flag must drop so its dependent hard stops (e.g. property COPE)
        # don't keep the score capped. We never RAISE a flag here — raising
        # requires a fresh extraction pass.
        fresh_flags = dict(session.get("flags") or {})

        def _fact(k):
            return updated_facts.get(k) if updated_facts.get(k) not in ("", "null", "None") else None

        if fresh_flags.get("has_property_coverage") and not (
            _fact("property_building_value")
            or _fact("property_bpp_value")
            or _fact("locations")
        ):
            fresh_flags["has_property_coverage"] = False
        if fresh_flags.get("has_umbrella") and not (
            _fact("umbrella_limit")
            or _fact("umbrella_attachment_point")
            or _fact("umbrella_sir")
        ):
            fresh_flags["has_umbrella"] = False
        if fresh_flags.get("has_auto_coverage") and not (
            _fact("auto_liability_limit")
            or _fact("auto_vin_schedule")
            or _fact("vehicle_schedule")
        ):
            fresh_flags["has_auto_coverage"] = False
        if fresh_flags.get("has_workers_comp") and not (
            _fact("wc_payroll")
            or _fact("wc_class_codes")
            or _fact("total_payroll")
        ):
            fresh_flags["has_workers_comp"] = False

        _re_hard, _re_soft = evaluate_stops(updated_facts, fresh_flags)
        _triggered_ids = set(session.get("selected_form_ids") or []) | {form_id}
        _cf_issues = run_cross_form_validation(updated_facts, fresh_flags, _triggered_ids)
        _cf_hard, _cf_soft, _cf_advisories = split_cross_form_issues(_cf_issues)
        fresh_hard_stops = list(_re_hard) + list(_cf_hard)
        fresh_soft_stops = list(_re_soft) + list(_cf_soft)

        # Pass confidence_dict so structural completeness reflects producer edits
        # (1.00) vs AI-high (0.85) vs AI-low (0.50) per spec.
        # H2 fix: also pass doc-presence params so the narrative/loss-history floors
        # are not dropped on every field edit (regression introduced by missing params).
        _edit_docs    = session.get("docs", []) or []
        _edit_present = {str(d.get("doc_type") or "").strip()
                         for d in _edit_docs if isinstance(d, dict) and not d.get("excluded")}
        _edit_app_name = (updated_facts.get("applicant_name") or {})
        if isinstance(_edit_app_name, dict):
            _edit_app_name = _edit_app_name.get("value") or ""
        _edit_app_name = str(_edit_app_name).strip() or None
        sqs = calculate_sqs(
            facts=updated_facts, flags=fresh_flags,
            mapped_data=current_state, form_schema=r.get("schema", {}),
            selected_form_ids=session.get("selected_form_ids", []),
            # SQS design: cross-form stops cap the PACKAGE only, never individual
            # forms - so per-form SQS uses field-level (global) stops only. The
            # cross-form stops (_cf_*) still cap the package score recomputed below.
            hard_stops=list(_re_hard), soft_stops=list(_re_soft),
            tier2_score=session.get("tier2_score", 50),
            confidence_dict=confidence,
            has_narrative_doc="narrative" in _edit_present,
            has_loss_run_doc="loss_run" in _edit_present,
            loss_run_match=_check_loss_run_insured_match(_edit_docs, _edit_app_name),
            cross_issues_full=_cf_issues,
            narrative_doc_text=_extract_narrative_doc_text(_edit_docs),
        )

        was_signed      = bool(r.get("signature_applied")) and len(cleared_sig_fields) == 0
        new_pdf_bytes   = None
        new_sig_applied = False

        try:
            tpl = safe_join(TEMPLATE_DIR, r["form"]["template_file"])
        except ValueError:
            raise HTTPException(400, "Invalid template path")
        _pdf_loop = asyncio.get_event_loop()
        if os.path.exists(tpl):
            new_pdf_bytes = await _pdf_loop.run_in_executor(None, fill_pdf, tpl, current_state, confidence)
            if was_signed:
                async with get_pool().acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT signature_data FROM users WHERE id = $1", current_user["id"]
                    )
                sig = decrypt_field(dict(row).get("signature_data")) if row else None
                if sig:
                    from services.pdf_service import inject_signature_into_pdf
                    field_data_for_sig = dict(current_state)
                    for fn in list(field_data_for_sig.keys()):
                        if _is_signature_field(fn) and fn not in cleared_sig_fields:
                            field_data_for_sig[fn] = ""
                            confidence[fn] = "filled"
                    try:
                        new_pdf_bytes   = await _pdf_loop.run_in_executor(
                            None, inject_signature_into_pdf, tpl, field_data_for_sig, confidence, sig
                        )
                        new_sig_applied = True
                    except Exception as ex:
                        logger.error(f"update_pdf: signature re-injection failed: {ex}")

        cache_hash = hashlib.md5(new_pdf_bytes).hexdigest() if new_pdf_bytes else None

        for field_name, new_val in req.field_updates.items():
            prev_val = prev_state.get(field_name)
            new_str  = str(new_val).strip() if new_val is not None else ""
            prev_str = str(prev_val).strip() if prev_val is not None else ""
            if new_str == prev_str:
                continue
            try:
                await log_field_change(
                    session_id=req.session_id,
                    user_id=str(current_user["id"]),
                    form_id=form_id,
                    field_name=field_name,
                    fact_key=field_name,
                    source="producer",
                    previous_value=prev_str or None,
                    new_value=new_str,
                    confidence="filled" if new_str else None,
                    model_version=SQS_MODEL_VERSION,
                )
            except Exception as _fe:
                logger.warning(f"field_source_audit log failed for {field_name}: {_fe}")

        old_rec_ids = {
            r2.get("rec_id") for r2 in (r.get("sqs") or {}).get("recommendations", [])
            if isinstance(r2, dict) and r2.get("rec_id")
        }
        new_rec_ids = {
            r2.get("rec_id") for r2 in sqs.get("recommendations", [])
            if isinstance(r2, dict) and r2.get("rec_id")
        }
        for resolved_rec_id in old_rec_ids - new_rec_ids:
            try:
                await mark_recommendation_resolved(
                    session_id=req.session_id,
                    rec_id=resolved_rec_id,
                    sqs_score_at_action=sqs.get("sqs_score") or 0,
                    model_version=SQS_MODEL_VERSION,
                )
            except Exception as _re:
                logger.warning(f"mark_recommendation_resolved failed for {resolved_rec_id}: {_re}")

        generated[form_id].update({
            "field_state": current_state, "confidence": confidence, "sqs": sqs,
            "_pdf_cache_hash": cache_hash, "pdf_bytes": new_pdf_bytes, "signature_applied": new_sig_applied,
        })

        # Recompute package SQS from the now-updated per-form SQS results so
        # the package score, pillars, top recommendations, and cross-form
        # validation update live as the producer edits fields.
        _sqs_results_live = [r2.get("sqs") for r2 in generated.values() if r2.get("sqs")]
        # Dedup cross_issues by message to match select_forms_bulk behavior.
        _seen_cf_msgs, _cf_deduped = set(), []
        for _iss in (_cf_issues or []):
            _m = _iss.get("message", "") if isinstance(_iss, dict) else ""
            if _m and _m not in _seen_cf_msgs:
                _seen_cf_msgs.add(_m)
                _cf_deduped.append(_iss)
        try:
            pkg_sqs = calculate_package_sqs(
                facts=updated_facts,
                flags=fresh_flags,
                form_results=_sqs_results_live,
                cross_issues=_cf_deduped,
                hard_stops=fresh_hard_stops,
                soft_stops=fresh_soft_stops,
                session_data=session,
                session_id=req.session_id,
                user_id=str(current_user["id"]),
                calculation_stage="form_edited",
            )
        except Exception as _pkg_ex:
            logger.error(f"package_sqs recompute (edit) failed: {_pkg_ex}", exc_info=True)
            pkg_sqs = None

        await upd_processing_session(req.session_id, {
            "generated_forms": generated,
            "facts": updated_facts,
            "flags": fresh_flags,
            "hard_stops": fresh_hard_stops,
            "soft_stops": fresh_soft_stops,
            "package_sqs": pkg_sqs,
            "cross_issues_last": _cf_deduped,
        })
        return JSONResponse({"success": True, "sqs": sqs, "confidence": confidence,
                             "package_sqs": pkg_sqs, "cross_issues": _cf_deduped})
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"update_pdf error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "PDF update failed. Please try again.")
    finally:
        if _sem_token:
            await release_heavy(_sem_token)


@router.get("/api/session/{session_id}")
async def get_session(session_id: str, current_user: dict = Depends(get_current_user)):
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = proc_session.get("generated_forms", {})
    # Omit the full `form` field data — it can be megabytes and is not needed to
    # restore the editor shell. The PDF viewer fetches form data lazily per-form.
    summary   = {fid: {"form_id": r.get("form_id", fid), "form_name": r.get("form_name", fid),
                        "sqs": r.get("sqs", {})} for fid, r in generated.items()}
    return JSONResponse({"session_id": session_id, "generated_forms": summary,
                         "cross_issues": proc_session.get("cross_issues_last", []),
                         "package_sqs": proc_session.get("package_sqs")})


@router.get("/api/session/{session_id}/extraction-result")
async def get_extraction_result(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return extraction data for a session after async processing completes.

    Called by the frontend after polling a job to completion. Returns the same
    shape as the synchronous /api/upload-declaration success response so the
    frontend can use a single code path for both sync and async modes.
    """
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")

    docs        = proc_session.get("docs", [])
    primary_doc = proc_session.get("primary_doc", "")

    doc_summary = [_doc_summary_entry(d, primary_doc) for d in docs]

    hard_stops = proc_session.get("hard_stops", [])
    mflags     = proc_session.get("flags", {})
    _can_proceed_warn, _remaining_hard, _downgraded = classify_stops(hard_stops, mflags)
    integrity  = proc_session.get("integrity") or {}

    return JSONResponse({
        "success":               True,
        "session_id":            session_id,
        "doc_summary":           doc_summary,
        "available_doc_types":   [{"value": t, "label": DOC_TYPE_LABELS[t]} for t in ALLOWED_DOC_TYPES],
        "primary_doc":           primary_doc,
        "flags":                 mflags,
        "hard_stops":            _remaining_hard,
        "soft_stops":            proc_session.get("soft_stops", []) + _downgraded,
        "can_proceed_with_warning": _can_proceed_warn,
        "warning_stops":         _downgraded,
        "tier2_score":           proc_session.get("tier2_score"),
        "tier2_missing":         proc_session.get("tier2_missing", []),
        "recommendations":       proc_session.get("recommendations", []),
        "account_profile":       proc_session.get("account_profile", {}),
        "all_available_forms":   score_extra_forms(
            proc_session.get("facts", {}),
            {r["form_id"] for r in proc_session.get("recommendations", [])},
            filter_available_forms(load_all_forms()),
        ),
        "low_confidence_tokens": proc_session.get("low_confidence_tokens", []),
        # Submission Integrity Validation (Beta Report §4.1) — mirror the sync
        # upload response so the async polling path uses the same review flow.
        "integrity":                 integrity,
        "integrity_review_required": bool(integrity.get("review_required")),
        "underwriting_consistency":  proc_session.get("underwriting_consistency") or {},
    })


@router.get("/api/session/{session_id}/document/{doc_id}/extracted-data")
async def get_document_extracted_data(
    session_id: str,
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return the data extracted from a single uploaded document (Beta Report
    §4.2 item #6 — "Review extracted data").

    Read-only view so a user can verify what Primble pulled from an Unknown /
    low-confidence document before deciding to confirm its type, exclude it, or
    include it as a supporting document only.
    """
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")

    docs = proc_session.get("docs", []) or []
    doc = next((d for d in docs if str(d.get("doc_id")) == str(doc_id)), None)
    if doc is None:
        raise HTTPException(404, "Document not found in this submission.")

    facts = doc.get("facts") or {}
    fields = []
    for key, raw in facts.items():
        confidence = raw.get("confidence") if isinstance(raw, dict) and "value" in raw else None
        display = _humanize_fact(raw)
        if not display:
            continue
        fields.append({
            "key":        key,
            "label":      str(key).replace("_", " ").title(),
            "value":      display,
            "confidence": confidence,
        })
    fields.sort(key=lambda f: f["label"])

    dt = doc.get("doc_type") or "unknown"
    return JSONResponse({
        "success":               True,
        "doc_id":                str(doc.get("doc_id")),
        "filename":              doc.get("filename", ""),
        "doc_type":              dt,
        "doc_type_label":        DOC_TYPE_LABELS.get(dt, dt.replace("_", " ").title()),
        "fields":                fields,
        "field_count":           len(fields),
        "narrative_categories":  (doc.get("classification") or {}).get("narrative_categories", []),
        "low_confidence_tokens": doc.get("low_confidence_tokens", []),
    })


@router.get("/api/sessions/stats")
async def session_stats(current_user: dict = Depends(get_current_user)):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*)::int                                          AS total_packages,
                (
                    SELECT COUNT(*)::int
                    FROM processing_sessions ps2,
                         jsonb_each(COALESCE(ps2.data->'generated_forms', '{}'::jsonb)) gf
                    WHERE ps2.user_id = $1
                )                                                      AS total_forms,
                (
                    SELECT ROUND(AVG(session_avg))::int
                    FROM (
                        SELECT AVG((gf.value->'sqs'->>'sqs_score')::numeric) AS session_avg
                        FROM processing_sessions ps3,
                             jsonb_each(COALESCE(ps3.data->'generated_forms', '{}'::jsonb)) gf
                        WHERE ps3.user_id = $1
                          AND (gf.value->'sqs'->>'sqs_score') IS NOT NULL
                        GROUP BY ps3.id
                    ) per_session
                )                                                      AS avg_sqs_score
            FROM processing_sessions
            WHERE user_id = $1
            """,
            str(current_user["id"]),
        )
    return JSONResponse({
        "total_packages": row["total_packages"] or 0,
        "total_forms":    row["total_forms"] or 0,
        "avg_sqs_score":  row["avg_sqs_score"],
    })


@router.get("/api/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    if (current_user.get("payment_status") or "ok") == "archived":
        raise HTTPException(403, "Account archived due to non-payment. Contact support@primble.ai to reactivate.")
    from repositories.session_repository import list_sessions_for_user
    sessions = await list_sessions_for_user(str(current_user["id"]))
    return JSONResponse({"success": True, "sessions": sessions})


# ASYNC-SAFE
@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, current_user: dict = Depends(get_current_user)):
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    async with get_pool().acquire() as conn:
        await conn.execute(
            "DELETE FROM processing_sessions WHERE id = $1 AND user_id = $2",
            session_id, str(current_user["id"]),
        )
        await conn.execute(
            "DELETE FROM session_pdf_bytes WHERE session_id = $1", session_id
        )
    return JSONResponse({"success": True})


@router.get("/api/send-to-epic/{session_id}/{form_id}")
async def send_to_epic(session_id: str, form_id: str, current_user: dict = Depends(get_current_user)):
    import json
    from datetime import datetime, timezone
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = proc_session.get("generated_forms", {})
    facts     = proc_session.get("facts", {})
    org_name  = current_user.get("organization_name") or current_user.get("full_name") or "Unknown Org"
    timestamp = datetime.now(timezone.utc).isoformat() + "Z"

    def _build_payload(fid, r):
        field_data = r.get("field_state") or r.get("mapped", {})
        sqs        = r.get("sqs", {})
        return {"form_id": fid, "form_name": r.get("form_name", fid),
                "sqs": {"score": sqs.get("sqs_score"), "grade": sqs.get("grade"),
                        "tier": sqs.get("tier"), "routing_decision": sqs.get("routing_decision"), "breakdown": sqs.get("breakdown", {})},
                "fields": {k: v for k, v in field_data.items() if v is not None and str(v).strip() not in ("", "null", "None")}}

    if form_id == "all":
        epic_payload = {"source": "acordly", "version": "12.3.1", "export_type": "bulk",
                        "timestamp": timestamp, "session_id": session_id,
                        "user_email": current_user.get("email"), "organization": org_name,
                        "applicant": facts.get("applicant_name"), "forms": {fid: _build_payload(fid, r) for fid, r in generated.items()}}
    elif form_id in generated:
        epic_payload = {"source": "acordly", "version": "12.3.1", "export_type": "single_form",
                        "timestamp": timestamp, "session_id": session_id,
                        "user_email": current_user.get("email"), "organization": org_name,
                        "applicant": facts.get("applicant_name"), "effective_date": facts.get("effective_date"),
                        "lines_of_business": facts.get("lines_of_business", []), **_build_payload(form_id, generated[form_id])}
    else:
        raise HTTPException(404, f"Form '{form_id}' not found")

    logger.info("EPIC EXPORT: form=%s session=%s forms=%d", form_id, session_id[:8], len(epic_payload.get("forms", {epic_payload.get("form_id"): 1})))

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    return JSONResponse({"success": True, "message": f"Exported to terminal ({form_id}). EPIC integration coming soon.", "form_id": form_id, "payload": epic_payload})


@router.get("/api/send-to-vertafore/{session_id}/{form_id}")
async def send_to_vertafore(session_id: str, form_id: str, current_user: dict = Depends(get_current_user)):
    import json
    from datetime import datetime, timezone
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    generated = proc_session.get("generated_forms", {})
    facts     = proc_session.get("facts", {})
    org_name  = current_user.get("organization_name") or current_user.get("full_name") or "Unknown Org"
    timestamp = datetime.now(timezone.utc).isoformat() + "Z"

    def _build_payload(fid, r):
        field_data = r.get("field_state") or r.get("mapped", {})
        sqs        = r.get("sqs", {})
        return {"form_id": fid, "form_name": r.get("form_name", fid),
                "sqs": {"score": sqs.get("sqs_score"), "grade": sqs.get("grade"),
                        "tier": sqs.get("tier"), "routing_decision": sqs.get("routing_decision"), "breakdown": sqs.get("breakdown", {})},
                "fields": {k: v for k, v in field_data.items() if v is not None and str(v).strip() not in ("", "null", "None")}}

    if form_id == "all":
        payload = {"source": "acordly", "version": "12.3.1", "export_type": "bulk",
                   "timestamp": timestamp, "session_id": session_id,
                   "user_email": current_user.get("email"), "organization": org_name,
                   "applicant": facts.get("applicant_name"), "forms": {fid: _build_payload(fid, r) for fid, r in generated.items()}}
    elif form_id in generated:
        payload = {"source": "acordly", "version": "12.3.1", "export_type": "single_form",
                   "timestamp": timestamp, "session_id": session_id,
                   "user_email": current_user.get("email"), "organization": org_name,
                   "applicant": facts.get("applicant_name"), "effective_date": facts.get("effective_date"),
                   "lines_of_business": facts.get("lines_of_business", []), **_build_payload(form_id, generated[form_id])}
    else:
        raise HTTPException(404, f"Form '{form_id}' not found")

    logger.info("VERTAFORE EXPORT: form=%s session=%s forms=%d", form_id, session_id[:8], len(payload.get("forms", {payload.get("form_id"): 1})))

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    return JSONResponse({"success": True, "message": f"Exported to terminal ({form_id}). Vertafore integration coming soon.", "form_id": form_id, "payload": payload})


# ---------------------------------------------------------------------------
# Clarity pipeline — SQS + ARQ without form generation
# ---------------------------------------------------------------------------

@router.post("/api/clarity/analyze/{session_id}")
async def clarity_analyze(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Clarity pipeline: produce SQS scoring, ARQ questions, and cross-validation
    without generating ACORD PDF forms.
    """
    from services.pipeline_router import is_assembly
    from services.sqs_service import calculate_sqs_from_facts, cross_validate
    from services.arq_service import generate_arq_questions_from_facts
    from services.form_service import match_forms_deterministic, derive_account_profile

    check_payment_access(current_user.get("payment_status", "ok"), "form")
    tier = current_user.get("subscription_tier", "free") or "free"

    if is_assembly(tier):
        raise HTTPException(
            403,
            "This endpoint is for Clarity/Lite plan users. "
            "Assembly plan users should use /api/select-forms-bulk.",
        )

    session     = await get_processing_session(session_id)
    facts       = session.get("facts", {})
    flags       = session.get("flags", {})
    hard_stops  = session.get("hard_stops", [])
    soft_stops  = session.get("soft_stops", [])
    tier2_score = session.get("tier2_score", 50)

    if session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")

    # Submission Integrity gate (Beta Report §4.1): pause SQS scoring + client
    # questionnaire generation while a multi-insured review is pending.
    enforce_integrity_gate(session)

    # Pass the uploaded document text so the dec-page line-item recall paths fire
    # here too (parity with the Assembly pipeline, extraction_pipeline.match_forms).
    # Without it, coverage lines that appear only on a dec page would be silently
    # dropped for Clarity/Lite users while Assembly users see them.
    combined_text     = " ".join(
        d.get("text", "") for d in (session.get("docs") or []) if isinstance(d, dict)
    )
    matched           = match_forms_deterministic(facts, flags, text=combined_text)
    selected_form_ids = [f["form_id"] for f in matched]
    account_profile    = derive_account_profile(facts, flags, text=combined_text)
    triggered_ids      = {f["form_id"] for f in matched}
    extra_forms_scored = score_extra_forms(facts, triggered_ids, filter_available_forms(load_all_forms()))

    sqs_per_form: dict = {}
    for fid in selected_form_ids:
        try:
            sqs_per_form[fid] = calculate_sqs_from_facts(
                facts=facts,
                flags=flags,
                selected_form_ids=selected_form_ids,
                hard_stops=hard_stops,
                soft_stops=soft_stops,
                tier2_score=tier2_score,
                form_id=fid,
                session_data=session,
            )
        except Exception as ex:
            logger.error(f"Clarity SQS error for {fid}: {ex}")

    sqs_scores   = [s.get("sqs_score", 0) for s in sqs_per_form.values()]
    avg_score    = int(sum(sqs_scores) / max(len(sqs_scores), 1)) if sqs_scores else 0
    first_sqs    = next(iter(sqs_per_form.values()), {})
    sqs_combined = {**first_sqs, "sqs_score": avg_score, "form_id": "combined"}

    arq_questions = generate_arq_questions_from_facts(
        facts=facts,
        flags=flags,
        selected_form_ids=selected_form_ids,
        hard_stops=hard_stops,
        soft_stops=soft_stops,
    )

    cross_issues_raw = cross_validate(facts, flags, selected_form_ids)
    seen_msgs, cross_issues = set(), []
    for issue in cross_issues_raw:
        msg = issue.get("message", "")
        if msg not in seen_msgs:
            seen_msgs.add(msg)
            cross_issues.append(issue)

    # Combined SQS comes from the package scorer (the same engine the Assembly and
    # ARQ-remediation paths use) so the client-tuned pillar logic - not a plain
    # average of the simplified per-form checklists - drives the Clarity headline
    # too. The averaged fallback built above is retained only if the scorer raises.
    try:
        _clarity_pkg = calculate_package_sqs(
            facts=facts, flags=flags,
            form_results=list(sqs_per_form.values()),
            cross_issues=cross_issues,
            hard_stops=hard_stops, soft_stops=soft_stops,
            session_data=session,
            session_id=session_id, user_id=str(current_user["id"]),
            calculation_stage="initial_extract",
        )
        sqs_combined = {
            **sqs_combined,
            "sqs_score":          _clarity_pkg["package_sqs_score"],
            "breakdown":          _clarity_pkg["pillars"],
            "tier":               _clarity_pkg["tier"],
            "routing_decision":   _clarity_pkg["routing_decision"],
            "category_breakdown": _clarity_pkg.get("category_breakdown", sqs_combined.get("category_breakdown")),
        }
    except Exception as _clarity_pkg_ex:
        logger.error(f"Clarity package SQS failed, keeping per-form average: {_clarity_pkg_ex}")

    cross_hard_msgs      = [i["message"] for i in cross_issues if i.get("type") == "hard_stop"]
    effective_hard_stops = list(hard_stops) + [m for m in cross_hard_msgs if m not in hard_stops]

    await upd_processing_session(session_id, {
        "selected_form_ids": selected_form_ids,
        "recommendations":   matched,
        "account_profile":   account_profile,
        "clarity_result": {
            "sqs_per_form":   sqs_per_form,
            "sqs_combined":   sqs_combined,
            "arq_questions":  arq_questions,
            "cross_issues":   cross_issues,
            "selected_forms": [{"form_id": f["form_id"], "form_name": f.get("form_name", f["form_id"])} for f in matched],
        },
        "cross_issues_last": cross_issues,
    })

    return JSONResponse({
        "success":         True,
        "session_id":      session_id,
        "selected_forms":  [{"form_id": f["form_id"], "form_name": f.get("form_name", f["form_id"])} for f in matched],
        "recommendations": matched,
        "account_profile": account_profile,
        "all_available_forms": extra_forms_scored,
        "sqs_per_form":    sqs_per_form,
        "sqs_combined":    sqs_combined,
        "arq_questions":      arq_questions,
        "arq_count":          len(arq_questions),
        "cross_issues":       cross_issues,
        "hard_stops":         effective_hard_stops,
        "soft_stops":         soft_stops,
        "flags":              flags,
        "compliance_checklist": sqs_combined.get("compliance_checklist", []),
    })


