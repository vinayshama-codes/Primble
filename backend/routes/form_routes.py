import logging
import os
from typing import Optional
from fastapi import Request

from fastapi import APIRouter, Depends, File, Header, Query, UploadFile, HTTPException, File, Response
from fastapi.responses import JSONResponse, Response
from typing import List

from config.database import get_db
from config.settings import TEMPLATE_DIR, UPLOAD_DIR, SUPPORTED_IMG
from models.schemas import BulkFormSelectionRequest, FormSelectionRequest, PDFUpdateRequest
from repositories.session_repository import (
    get_processing_session, new_processing_session, upd_processing_session,
)
from services.auth_service import get_current_user, validate_token_from_request
from services.extraction_service import extract_facts_long, identify_doc_type, merge_facts, select_primary_truth
from services.form_service import (
    filter_available_forms, load_all_forms, match_forms, process_single_form,
)
from services.ocr_service import extract_text, extract_zip
from services.pdf_service import (
    extract_form_fields_with_positions, get_page_dims_pikepdf, regenerate_pdf_for_form,
    fill_pdf, _is_signature_field,
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

router = APIRouter(tags=["forms"])
logger = logging.getLogger(__name__)


@router.post("/api/upload-declaration")
async def upload_declaration(
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT payment_status FROM users WHERE id = %s", (current_user["id"],))
    row = cur.fetchone(); cur.close(); conn.close()
    if row:
        ps = dict(row).get("payment_status", "ok") or "ok"
        from fastapi import HTTPException
        if ps == "suspended":   raise HTTPException(403, "Account suspended due to non-payment.")
        if ps == "archived":    raise HTTPException(403, "Account archived. Contact support@acordly.ai.")
        if ps == "soft_locked": raise HTTPException(403, "Account disabled. Please update your billing.")

    try:
        all_paths = []
        for f in files:
            path = os.path.join(UPLOAD_DIR, f.filename)
            with open(path, "wb") as fp:
                fp.write(await f.read())
            ext = os.path.splitext(f.filename.lower())[1]
            if ext == ".zip":
                all_paths.extend(extract_zip(path))
            elif ext == ".pdf" or ext in SUPPORTED_IMG:
                all_paths.append(path)

        if not all_paths:
            from fastapi import HTTPException
            raise HTTPException(400, "No supported files found")

        processed_docs = []
        all_low_conf:  list = []
        for path in all_paths:
            text, low_conf = extract_text(path)
            if len(text) < 30:
                continue
            all_low_conf  += low_conf
            doc_type       = identify_doc_type(text)
            extracted      = extract_facts_long(text, doc_type, low_confidence_tokens=low_conf)
            processed_docs.append({
                "filename": os.path.basename(path), "path": path, "doc_type": doc_type,
                "text": text, "facts": extracted.get("facts", {}), "flags": extracted.get("flags", {}),
                "low_confidence_tokens": low_conf,
                "truncation_warning": extracted.get("truncation_warning"),
            })

        if not processed_docs:
            from fastapi import HTTPException
            raise HTTPException(400, "No readable text found in uploaded files")

        primary              = select_primary_truth(processed_docs)
        merged_facts, mflags = merge_facts(processed_docs, primary)
        # Expose primary doc type in flags so check_tier1 can relax producer/contact
        # requirements for carrier-issued declaration pages.
        mflags["_doc_type"] = primary.get("doc_type", "unknown")
        tier1_ok, tier1_missing = check_tier1(merged_facts, mflags)

        if not tier1_ok:
            return JSONResponse({"success": False, "gate": "tier1_fail",
                                  "message": "Submission missing required fields",
                                  "missing_fields": tier1_missing, "flags": mflags})

        tier2_score, tier2_missing = check_tier2(merged_facts)
        hard_stops, soft_stops     = evaluate_stops(merged_facts, mflags)

        # Cross-document consistency: flag mismatched applicant_name / FEIN / effective_date
        consistency_issues = check_doc_consistency(processed_docs)
        doc_conflicts = []
        if consistency_issues:
            logger.warning(f"Doc consistency issues: {consistency_issues}")
            for issue in consistency_issues:
                if issue.startswith("[hard_stop]"):
                    rest = issue[len("[hard_stop]"):].strip()
                    code_part, _, msg = rest.partition(" ")
                    code = code_part.split("=", 1)[1] if "=" in code_part else "conflict"
                    doc_conflicts.append({"code": code, "message": msg, "hard_stop": True})
                    hard_stops = list(hard_stops) + [msg]
                else:
                    hard_stops = list(hard_stops) + [issue]

        all_forms                  = load_all_forms()
        available_forms            = filter_available_forms(all_forms)
        # Combine raw OCR text from all docs for keyword-based form triggers
        # (builders risk, inland marine, certificate, evidence of property).
        combined_ocr_text          = " ".join(d.get("text", "") for d in processed_docs)
        recommendations            = match_forms(merged_facts, mflags, available_forms, text=combined_ocr_text)

        # Deduplicate across all files, preserve insertion order
        unique_low_conf = list(dict.fromkeys(all_low_conf))

        sid = new_processing_session({
            "user_id": current_user["id"], "docs": processed_docs,
            "primary_doc": primary["filename"], "facts": merged_facts, "flags": mflags,
            "tier2_score": tier2_score, "tier2_missing": tier2_missing,
            "hard_stops": hard_stops, "soft_stops": soft_stops,
            "all_forms": available_forms, "recommendations": recommendations,
            "selected_form_ids": [], "generated_forms": {},
            "low_confidence_tokens": unique_low_conf,
        })

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
            "all_available_forms": [{"form_id": f["form_id"], "form_name": f["form_name"],
                                      "description": f.get("description","")} for f in available_forms],
        })
    except Exception as ex:
        logger.error(f"Upload error: {ex}")
        from fastapi import HTTPException
        raise HTTPException(500, str(ex))


@router.post("/api/select-forms-bulk")
async def select_forms_bulk(req: BulkFormSelectionRequest, current_user: dict = Depends(get_current_user)):
    from fastapi import HTTPException
    if current_user.get("subscription_tier") == "lite":
        raise HTTPException(403, "Form generation is not included in the Lite plan.")

    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT payment_status FROM users WHERE id = %s", (current_user["id"],))
    row = cur.fetchone(); cur.close(); conn.close()
    if row:
        ps = dict(row).get("payment_status", "ok") or "ok"
        if ps in ("soft_locked", "suspended", "archived"):
            raise HTTPException(403, "Account disabled. Please update your billing.")

    session = get_processing_session(req.session_id)
    results = {}
    combined_ids = req.form_ids

    for form_id in req.form_ids:
        form_meta = next((f for f in session["all_forms"] if f["form_id"] == form_id), None)
        if not form_meta:
            continue
        tpl = os.path.join(TEMPLATE_DIR, form_meta["template_file"])
        if not os.path.exists(tpl):
            continue
        try:
            result = process_single_form(form_meta, session)
            results[form_id] = result
        except Exception as ex:
            logger.error(f"Error processing {form_id}: {ex}")

    if not results:
        raise HTTPException(400, "No forms could be generated")

    cross_issues_raw     = cross_validate(session["facts"], session["flags"], combined_ids)
    seen_msgs            = set()
    cross_issues_deduped = []
    for issue in cross_issues_raw:
        msg = issue.get("message", "")
        if msg not in seen_msgs:
            seen_msgs.add(msg)
            cross_issues_deduped.append(issue)

    upd_processing_session(req.session_id, {
        "selected_form_ids": combined_ids, "generated_forms": results,
        "active_form_id": combined_ids[0] if combined_ids else None,
        "cross_issues_last": cross_issues_deduped,
    })

    summary = {}
    for fid, r in results.items():
        summary[fid] = {"form_id": r["form_id"], "form_name": r["form_name"], "form": r["form"],
                         "sqs": r["sqs"], "fields_mapped": sum(1 for v in r["mapped"].values() if v is not None),
                         "schema_size": len(r["schema"])}

    # Package-level SQS across all generated forms
    sqs_results_list = [r["sqs"] for r in results.values() if r.get("sqs")]
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

    # Log all per-form recommendations for E&O audit trail
    for fid, r in results.items():
        sqs_data = r.get("sqs")
        if sqs_data and sqs_data.get("recommendations"):
            try:
                log_recommendations_presented(
                    session_id=req.session_id,
                    user_id=str(current_user["id"]),
                    sqs_result=sqs_data,
                    model_version=SQS_MODEL_VERSION,
                )
            except Exception as _audit_ex:
                logger.warning(f"Audit log failed for {fid}: {_audit_ex}")

    return JSONResponse({
        "success": True,
        "generated": summary,
        "form_ids": combined_ids,
        "cross_issues": cross_issues_deduped,
        "package_sqs": package_sqs,
    })


@router.post("/api/select-form")
async def select_form(req: FormSelectionRequest, current_user: dict = Depends(get_current_user)):
    return await select_forms_bulk(BulkFormSelectionRequest(session_id=req.session_id, form_ids=[req.selected_form_id]), current_user)


@router.post("/api/lite/generate-internal/{session_id}")
async def lite_generate_internal(session_id: str, current_user: dict = Depends(get_current_user)):
    """Silently generate forms for Lite users to power ARQ and SQS — forms are never exposed or downloadable."""
    from fastapi import HTTPException
    if current_user.get("subscription_tier") != "lite":
        raise HTTPException(403, "This endpoint is for Lite plan users only.")

    session = get_processing_session(session_id)
    recommendations = session.get("recommendations", [])
    form_ids = [r["form_id"] for r in recommendations]

    if not form_ids:
        raise HTTPException(400, "No recommended forms found in session.")

    results = {}
    for form_id in form_ids:
        form_meta = next((f for f in session["all_forms"] if f["form_id"] == form_id), None)
        if not form_meta:
            continue
        tpl = os.path.join(TEMPLATE_DIR, form_meta["template_file"])
        if not os.path.exists(tpl):
            continue
        try:
            result = process_single_form(form_meta, session)
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

    upd_processing_session(session_id, {
        "selected_form_ids": form_ids,
        "generated_forms": results,
        "active_form_id": form_ids[0] if form_ids else None,
        "cross_issues_last": cross_issues_deduped,
    })

    # Return SQS summary across all generated forms — no form content exposed
    sqs_list = [r["sqs"] for r in results.values() if r.get("sqs")]
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
    token: Optional[str] = Query(default=None),
    authorization: str   = Header(default=None),
):
    from fastapi import HTTPException
    if not validate_token_from_request(token, authorization):
        raise HTTPException(401, "Not authenticated")
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form '{form_id}' not found")
    r   = generated[form_id]
    tpl = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    if not os.path.exists(tpl):
        raise HTTPException(404, "Template not found")
    fields      = extract_form_fields_with_positions(tpl)
    page_dims   = get_page_dims_pikepdf(tpl)
    field_state = r.get("field_state") or r.get("mapped", {})
    confidence  = r.get("confidence", {})
    client_filled = set(r.get("client_filled_fields", []))
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
    token: Optional[str] = Query(default=None),
    authorization: str   = Header(default=None),
):
    """After client fills ARQ, mark those fields as 'filled' confidence and store client_filled list."""
    from fastapi import HTTPException
    if not validate_token_from_request(token, authorization):
        raise HTTPException(401, "Not authenticated")
    body       = await request.json()
    field_names = body.get("field_names", [])
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form '{form_id}' not found")
    r = generated[form_id]
    # Update confidence to "filled" for client-filled fields
    confidence = r.get("confidence", {})
    for fn in field_names:
        confidence[fn] = "filled"
    r["confidence"]          = confidence
    r["client_filled_fields"] = list(set(r.get("client_filled_fields", []) + field_names))
    generated[form_id] = r
    upd_processing_session(session_id, {"generated_forms": generated})
    return JSONResponse({"success": True})


@router.get("/api/get-pdf/{session_id}/{form_id}")
async def get_pdf(
    session_id: str, form_id: str,
    token: Optional[str] = Query(default=None),
    authorization: str = Header(default=None),
):
    from fastapi import HTTPException
    if not validate_token_from_request(token, authorization):
        raise HTTPException(401, "Not authenticated")
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form {form_id} not generated")
    r = generated[form_id]
    pdf_bytes = regenerate_pdf_for_form(proc_session, form_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={form_id}_preview.pdf",
                             "Cache-Control": "no-store, no-cache, must-revalidate"})


@router.post("/api/update-pdf")
async def update_pdf(req: PDFUpdateRequest, current_user: dict = Depends(get_current_user)):
    import hashlib, json
    from fastapi import HTTPException
    session   = get_processing_session(req.session_id)
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

    r             = generated[form_id]
    current_state = r.get("field_state", dict(r.get("mapped", {})))
    prev_state    = dict(current_state)   # snapshot before mutation for audit diff
    current_state.update(req.field_updates)
    confidence = r.get("confidence", {})
    for k, v in req.field_updates.items():
        val = str(v).strip() if v is not None else ""
        if val and val not in ("null", "None"):
            confidence[k] = "filled"
        # If user cleared a field, restore to low_confidence so it shows up in ARQ again
        elif confidence.get(k) == "filled":
            confidence[k] = "low_confidence"

    sqs = calculate_sqs(
        facts=session["facts"], flags=session["flags"],
        mapped_data=current_state, form_schema=r.get("schema", {}),
        selected_form_ids=session.get("selected_form_ids", []),
        hard_stops=session.get("hard_stops", []), soft_stops=session.get("soft_stops", []),
        tier2_score=session.get("tier2_score", 50),
    )

    was_signed    = bool(r.get("signature_applied")) and len(cleared_sig_fields) == 0
    new_pdf_bytes = None
    new_sig_applied = False

    tpl = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    if os.path.exists(tpl):
        new_pdf_bytes = fill_pdf(tpl, current_state, confidence)
        if was_signed:
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT signature_data FROM users WHERE id = %s", (current_user["id"],))
            row = cur.fetchone(); cur.close(); conn.close()
            sig = dict(row).get("signature_data") if row else None
            if sig:
                from services.pdf_service import inject_signature_into_pdf
                field_data_for_sig = dict(current_state)
                for fn in list(field_data_for_sig.keys()):
                    if _is_signature_field(fn) and fn not in cleared_sig_fields:
                        field_data_for_sig[fn] = ""
                        confidence[fn] = "filled"
                try:
                    new_pdf_bytes   = inject_signature_into_pdf(tpl, field_data_for_sig, confidence, sig)
                    new_sig_applied = True
                except Exception as ex:
                    logger.error(f"update_pdf: signature re-injection failed: {ex}")

    cache_hash = hashlib.md5(new_pdf_bytes).hexdigest() if new_pdf_bytes else None

    # ── Audit: log only fields whose value actually changed ──────────────────
    for field_name, new_val in req.field_updates.items():
        prev_val = prev_state.get(field_name)
        new_str  = str(new_val).strip() if new_val is not None else ""
        prev_str = str(prev_val).strip() if prev_val is not None else ""
        if new_str == prev_str:
            continue  # value unchanged — skip, do not log
        try:
            log_field_change(
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

    # ── Audit: auto-resolve recs whose field was just filled ─────────────────
    # Compare old rec_ids vs new rec_ids — any that disappeared were fixed.
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
            mark_recommendation_resolved(
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
    upd_processing_session(req.session_id, {"generated_forms": generated})
    return JSONResponse({"success": True, "sqs": sqs})


@router.get("/api/session/{session_id}")
async def get_session(session_id: str, current_user: dict = Depends(get_current_user)):
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    summary      = {fid: {"form_id": r.get("form_id", fid), "form_name": r.get("form_name", fid),
                           "form": r.get("form", {}), "sqs": r.get("sqs", {})} for fid, r in generated.items()}
    return JSONResponse({"session_id": session_id, "generated_forms": summary,
                         "cross_issues": proc_session.get("cross_issues_last", [])})

@router.get("/api/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    from repositories.session_repository import list_sessions_for_user
    sessions = list_sessions_for_user(str(current_user["id"]))
    return JSONResponse({"success": True, "sessions": sessions})


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, current_user: dict = Depends(get_current_user)):
    conn = get_db(); cur = conn.cursor()
    cur.execute(
        "DELETE FROM processing_sessions WHERE id = %s AND user_id = %s",
        (session_id, str(current_user["id"])),
    )
    cur.execute("DELETE FROM session_pdf_bytes WHERE session_id = %s", (session_id,))
    conn.commit(); cur.close(); conn.close()
    return JSONResponse({"success": True})

@router.get("/api/send-to-epic/{session_id}/{form_id}")
async def send_to_epic(session_id: str, form_id: str, current_user: dict = Depends(get_current_user)):
    import json
    from fastapi import HTTPException
    from datetime import datetime, timezone
    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    facts        = proc_session.get("facts", {})
    org_name     = current_user.get("organization_name") or current_user.get("full_name") or "Unknown Org"
    timestamp    = datetime.now(timezone.utc).isoformat() + "Z"

    def _build_payload(fid, r):
        field_data = r.get("field_state") or r.get("mapped", {})
        sqs        = r.get("sqs", {})
        return {"form_id": fid, "form_name": r.get("form_name", fid),
                "sqs": {"score": sqs.get("sqs_score"), "grade": sqs.get("grade"),
                        "tier": sqs.get("tier"), "routing_decision": sqs.get("routing_decision"), "breakdown": sqs.get("breakdown",{})},
                "fields": {k: v for k, v in field_data.items() if v is not None and str(v).strip() not in ("","null","None")}}

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
                        "lines_of_business": facts.get("lines_of_business",[]), **_build_payload(form_id, generated[form_id])}
    else:
        raise HTTPException(404, f"Form '{form_id}' not found")

    logger.info(f"EPIC EXPORT: form={form_id} session={session_id[:8]} user={current_user.get('email')}\n{json.dumps(epic_payload, indent=2, default=str)}")

    # Mark session as completed — EPIC export counts the same as a download
    upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    return JSONResponse({"success": True, "message": f"Exported to terminal ({form_id}). EPIC integration coming soon.", "form_id": form_id, "payload": epic_payload})


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

    Cost: 0 batch LLM calls (form field mapping is skipped entirely).
    Form matching (stage1 + stage2) still runs to identify which ACORD forms
    are relevant so SQS is scored per-form correctly.

    Replaces /api/lite/generate-internal + /api/lite/analyze for Lite users.
    When the Clarity product line launches this will also serve Clarity tiers.
    """
    from fastapi import HTTPException
    from services.pipeline_router import is_assembly
    from services.sqs_service import calculate_sqs_from_facts, cross_validate
    from services.arq_service import generate_arq_questions_from_facts
    from services.form_service import match_forms_deterministic

    tier = current_user.get("subscription_tier", "free") or "free"

    # Block Assembly tier users — they should use the full form generation pipeline
    if is_assembly(tier):
        raise HTTPException(
            403,
            "This endpoint is for Clarity/Lite plan users. "
            "Assembly plan users should use /api/select-forms-bulk.",
        )

    session     = get_processing_session(session_id)
    facts       = session.get("facts", {})
    flags       = session.get("flags", {})
    hard_stops  = session.get("hard_stops", [])
    soft_stops  = session.get("soft_stops", [])
    tier2_score = session.get("tier2_score", 50)

    if session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")

    # --- Form matching (deterministic — zero LLM calls) ---
    matched = match_forms_deterministic(facts, flags)

    selected_form_ids = [f["form_id"] for f in matched]

    # --- SQS per form — zero LLM calls ---
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

    # Combined SQS: average score across all forms, carry first form's metadata
    sqs_scores = [s.get("sqs_score", 0) for s in sqs_per_form.values()]
    avg_score   = int(sum(sqs_scores) / max(len(sqs_scores), 1)) if sqs_scores else 0
    first_sqs   = next(iter(sqs_per_form.values()), {})
    sqs_combined = {**first_sqs, "sqs_score": avg_score, "form_id": "combined"}

    # --- ARQ questions — zero LLM calls ---
    arq_questions = generate_arq_questions_from_facts(
        facts=facts,
        flags=flags,
        selected_form_ids=selected_form_ids,
        hard_stops=hard_stops,
        soft_stops=soft_stops,
    )

    # --- Cross-validation — deterministic, zero LLM calls ---
    cross_issues_raw = cross_validate(facts, flags, selected_form_ids)
    seen_msgs, cross_issues = set(), []
    for issue in cross_issues_raw:
        msg = issue.get("message", "")
        if msg not in seen_msgs:
            seen_msgs.add(msg)
            cross_issues.append(issue)

    # Propagate hard_stop-typed cross-issues into the hard_stops list so the
    # frontend receives a single authoritative list and can block submission.
    cross_hard_msgs = [i["message"] for i in cross_issues if i.get("type") == "hard_stop"]
    effective_hard_stops = list(hard_stops) + [m for m in cross_hard_msgs if m not in hard_stops]

    # --- Persist results into session (no generated_forms — Clarity never produces PDFs) ---
    upd_processing_session(session_id, {
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