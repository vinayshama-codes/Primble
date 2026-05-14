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
from config.settings import TEMPLATE_DIR, UPLOAD_DIR, SUPPORTED_IMG, MAX_UPLOAD_SIZE_BYTES, MAX_FILES_PER_UPLOAD, ENABLE_ASYNC_PROCESSING
from utils.crypto import decrypt_field
from utils.json_logging import get_trace_id
from utils.helpers import safe_join, check_payment_access
from services.job_queue import get_job_queue, JOB_TYPE_EXTRACTION, JOB_TYPE_FORM_GENERATION, STATUS_PROCESSING, STATUS_COMPLETED, STATUS_FAILED
from models.schemas import BulkFormSelectionRequest, FormSelectionRequest, PDFUpdateRequest
from repositories.session_repository import (
    get_processing_session, new_processing_session, upd_processing_session,
)
from services.auth_service import get_current_user
from services.extraction_pipeline import run_extraction_pipeline, ProcessingIntegrityError
from services.extraction_service import extract_facts_long, identify_doc_type, merge_facts, select_primary_truth
from services.form_service import (
    filter_available_forms, load_all_forms, match_forms, process_single_form,
    score_extra_forms,
)
from services.ocr_service import extract_text, extract_zip
from services.pdf_service import (
    extract_form_fields_with_positions, get_page_dims_pikepdf, regenerate_pdf_for_form,
    fill_pdf, _is_signature_field, _load_fieldmap,
    apply_acord125_missing_field_highlights,
)
from services.sqs_service import (
    check_tier1, check_tier2, cross_validate, evaluate_stops, calculate_sqs,
    check_doc_consistency, calculate_package_sqs, SQS_MODEL_VERSION,
)
from services.audit_service import (
    log_recommendations_presented,
    log_field_change,
    mark_recommendation_resolved,
)
from utils.rate_limiter import check_upload_rate_limit
from utils.concurrency import try_acquire_heavy, release_heavy
from utils.mime_validator import validate_file_mime
from utils.virus_scanner import scan_file_bytes

router = APIRouter(tags=["forms"])
logger = logging.getLogger(__name__)


# ASYNC-SAFE
@router.post("/api/upload-declaration")
async def upload_declaration(
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    check_upload_rate_limit(current_user["id"])

    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payment_status, subscription_tier, downloads_used FROM users WHERE id = $1",
            current_user["id"],
        )
    if row:
        r = dict(row)
        ps = r.get("payment_status", "ok") or "ok"
        if ps == "suspended":   raise HTTPException(403, "Account suspended due to non-payment.")
        if ps == "archived":    raise HTTPException(403, "Account archived. Contact support@acordly.ai.")
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

        if not all_paths:
            raise HTTPException(400, "No supported files found")

        _sem_token = await try_acquire_heavy()
        if not _sem_token:
            raise HTTPException(
                429,
                "Server busy — too many concurrent requests. Please retry in 30 seconds.",
                headers={"Retry-After": "30"},
            )

        if ENABLE_ASYNC_PROCESSING:
            from services.s3_service import upload_source_file, is_configured as _s3_ok
            if not _s3_ok():
                raise HTTPException(
                    503,
                    "Async processing requires S3 storage. Set AWS_S3_BUCKET or disable ENABLE_ASYNC_PROCESSING.",
                )
            _upload_id = uuid.uuid4().hex
            s3_keys    = []
            for path in all_paths:
                fname = os.path.basename(path)
                try:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda p=path: open(p, "rb").read()
                    )
                    key = await asyncio.get_event_loop().run_in_executor(
                        None, upload_source_file, data, fname, _upload_id
                    )
                    if key is None:
                        raise HTTPException(503, "Failed to upload files to S3 for async processing.")
                    s3_keys.append(key)
                except HTTPException:
                    raise
                except Exception:
                    raise HTTPException(503, "Failed to stage files for async processing.")

            _queue       = get_job_queue()
            _in_flight = await _queue.count_user_active_jobs(current_user["id"])
            if _in_flight >= 5:
                raise HTTPException(429, "Too many jobs in progress. Please wait.")
            _job_payload = {
                "s3_keys": s3_keys,
                "user_id": str(current_user["id"]),
            }
            _job_id     = await _queue.enqueue(JOB_TYPE_EXTRACTION, _job_payload, str(current_user["id"]))
            _async_mode = True
            return JSONResponse(
                status_code=202,
                content={"job_id": _job_id, "session_id": None, "poll_url": f"/api/jobs/{_job_id}/status"},
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
        hard_stops         = pipeline_result["hard_stops"]
        soft_stops         = pipeline_result["soft_stops"]
        doc_conflicts      = pipeline_result["doc_conflicts"]
        recommendations    = pipeline_result["recommendations"]
        extra_forms_scored = pipeline_result["extra_forms_scored"]
        unique_low_conf    = pipeline_result["unique_low_conf"]
        sid                = pipeline_result["session_id"]

        if not tier1_ok:
            if _job_id:
                await _queue.update_status(_job_id, STATUS_FAILED, error="tier1_validation_failed")
            return JSONResponse({"success": False, "gate": "tier1_fail",
                                  "message": "Submission missing required fields",
                                  "missing_fields": tier1_missing, "flags": mflags})

        if _job_id:
            await _queue.update_status(_job_id, STATUS_COMPLETED, result={"session_id": sid})

        truncation_warnings = [
            {"filename": d["filename"], "warning": d["truncation_warning"]}
            for d in processed_docs if d.get("truncation_warning")
        ]

        return JSONResponse({
            "success": True, "session_id": sid,
            "doc_summary": [{"filename": d["filename"], "doc_type": d["doc_type"],
                              "is_primary": d["filename"] == primary["filename"],
                              "low_confidence_tokens": d.get("low_confidence_tokens", []),
                              "truncation_warning": d.get("truncation_warning")} for d in processed_docs],
            "primary_doc": primary["filename"], "flags": mflags,
            "tier2_score": tier2_score, "tier2_missing": tier2_missing,
            "hard_stops": hard_stops, "soft_stops": soft_stops,
            "doc_conflicts": doc_conflicts,
            "recommendations": recommendations,
            "low_confidence_tokens": unique_low_conf,
            "truncation_warnings": truncation_warnings,
            "all_available_forms": extra_forms_scored,
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
            release_heavy(_sem_token)
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

    check_upload_rate_limit(str(current_user["id"]))

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

    _sem_token = await try_acquire_heavy()
    if not _sem_token:
        raise HTTPException(
            429,
            "Server busy — too many concurrent requests. Please retry in 30 seconds.",
            headers={"Retry-After": "30"},
        )
    results     = {}
    combined_ids = req.form_ids

    try:
        loop = asyncio.get_event_loop()
        for form_id in req.form_ids:
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
                logger.error(f"Error processing {form_id}: {ex}")

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
        if _sem_token:
            release_heavy(_sem_token)


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
    avg_score = int(sum(s.get("sqs_score", 0) for s in sqs_list) / max(len(sqs_list), 1)) if sqs_list else 0
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
        updated_facts = dict(session["facts"])
        for pdf_field, new_val in req.field_updates.items():
            val_str = str(new_val).strip() if new_val is not None else ""
            for pattern, fact_key in _ACORD_FIELD_RULES:
                if fact_key and not fact_key.startswith("_") and pattern in pdf_field:
                    updated_facts[fact_key] = val_str if val_str not in ("", "null", "None") else None
                    break

        sqs = calculate_sqs(
            facts=updated_facts, flags=session["flags"],
            mapped_data=current_state, form_schema=r.get("schema", {}),
            selected_form_ids=session.get("selected_form_ids", []),
            hard_stops=session.get("hard_stops", []), soft_stops=session.get("soft_stops", []),
            tier2_score=session.get("tier2_score", 50),
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
        await upd_processing_session(req.session_id, {"generated_forms": generated, "facts": updated_facts})
        return JSONResponse({"success": True, "sqs": sqs, "confidence": confidence})
    except HTTPException:
        raise
    except Exception as ex:
        logger.error(f"update_pdf error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "PDF update failed. Please try again.")
    finally:
        if _sem_token:
            release_heavy(_sem_token)


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
                         "cross_issues": proc_session.get("cross_issues_last", [])})


@router.get("/api/sessions/stats")
async def session_stats(current_user: dict = Depends(get_current_user)):
    check_payment_access(current_user.get("payment_status", "ok"), "form")
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
                    SELECT ROUND(AVG((sqs_obj->>'sqs_score')::numeric))::int
                    FROM processing_sessions ps3,
                         jsonb_each(COALESCE(ps3.data->'generated_forms', '{}'::jsonb)) gf,
                         LATERAL (SELECT gf.value->'sqs' AS sqs_obj) sq
                    WHERE ps3.user_id = $1
                      AND (gf.value->'sqs'->>'sqs_score') IS NOT NULL
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
        raise HTTPException(403, "Account archived due to non-payment. Contact support@acordly.ai to reactivate.")
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
    from services.form_service import match_forms_deterministic

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

    matched           = match_forms_deterministic(facts, flags)
    selected_form_ids = [f["form_id"] for f in matched]

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

    cross_hard_msgs      = [i["message"] for i in cross_issues if i.get("type") == "hard_stop"]
    effective_hard_stops = list(hard_stops) + [m for m in cross_hard_msgs if m not in hard_stops]

    await upd_processing_session(session_id, {
        "selected_form_ids": selected_form_ids,
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


_PRESIGN_ALLOWED_EXTS = {".pdf", ".zip", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
_EXT_TO_CONTENT_TYPE = {
    ".pdf":  "application/pdf",
    ".zip":  "application/zip",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".bmp":  "image/bmp",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
    ".webp": "image/webp",
}


@router.post("/api/upload/presign")
async def get_presigned_upload_url(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Return a presigned S3 POST URL for direct browser-to-S3 upload.
    """
    from services.s3_service import generate_presigned_upload_url, is_configured as _s3_ok

    if not _s3_ok():
        raise HTTPException(503, "S3 is not configured. Use the multipart upload endpoint instead.")

    check_payment_access(current_user.get("payment_status", "ok"), "upload")
    check_upload_rate_limit(str(current_user["id"]))

    body     = await request.json()
    filename = (body.get("filename") or "").strip()
    if not filename:
        raise HTTPException(400, "filename is required")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in _PRESIGN_ALLOWED_EXTS:
        raise HTTPException(400, f"File type '{ext}' is not supported. Allowed: {', '.join(sorted(_PRESIGN_ALLOWED_EXTS))}")

    content_type = _EXT_TO_CONTENT_TYPE.get(ext, "application/octet-stream")
    upload_id    = uuid.uuid4().hex
    result       = generate_presigned_upload_url(filename, upload_id, content_type)
    if result is None:
        raise HTTPException(503, "Could not generate upload URL. Please try again.")

    return JSONResponse({"success": True, **result})
