"""Documents added to an EXISTING package (7 Oct 2026, Choice Electric #25).

Brent: "Unable to upload a narrative or additional supporting docs after form
generation." The only upload (`/api/upload-declaration`) always starts a NEW
package. These endpoints add to the package the producer is in, before or after
its forms exist:

  POST /api/session/{session_id}/documents
      multipart: files (one or more, the upload route's limits), optional
      progress_token (the upload progress channel), as_supporting (the files
      are "supporting only" - their facts count, they are never the primary
      document), doc_type (the producer states the type, e.g. a narrative;
      applied before extraction), confirm_same_insured (after forms: these
      documents belong to this insured even though their name differs).
      Only the NEW files are read (OCR + extraction); every stored document is
      re-merged from its stored facts through the documents door
      (`services/session_documents`), which re-stamps the generated forms.

  POST /api/session/{session_id}/documents/add-form
      Adds a form the door OFFERED (a line the added documents evidence that no
      generated form covers). Never automatic; a form not offered is refused.

  GET  /api/session/{session_id}/documents/ai-fill[?form_id=]
      The AI reading of documents added after forms (C103): its status, the
      open "new document says X - the form says Y" suggestions (one form's with
      `form_id`), and - once it has finished - what is NEW on the review page.

  POST /api/session/{session_id}/documents/suggestions/keep
      "Keep current" on one suggestion. ("Use this value" is an ordinary box
      edit through /api/update-pdf - the producer chose it.)

After forms, an add answers once the documents door has re-stamped the forms
and then the AI reading runs in the background (`session_documents.
run_new_document_fill`); document changes are refused (409) while it is alive.

The same checks as the upload route (one intake door, `services/upload_intake`;
the same rate limit, busy and in-flight limits), plus: the package's owner only,
an account that may upload, and never while a form generation is running.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from repositories.session_repository import get_processing_session
from services.auth_service import get_current_user
from services.extraction_pipeline import ProcessingIntegrityError
from services.session_documents import (
    AlreadyInPackage, IntegrityReviewRequired, add_documents, add_offered_form,
)
from utils.helpers import check_payment_access
from utils.json_logging import get_trace_id

router = APIRouter(tags=["session-documents"])
logger = logging.getLogger(__name__)


class AddOfferedFormRequest(BaseModel):
    form_id: str


class KeepSuggestionRequest(BaseModel):
    suggestion_id: str


def _refuse_while_filling(session: dict) -> None:
    """409 while the AI is reading an added document into the forms (C103):
    it writes its answers onto the forms the documents door left."""
    from services.generation_state import DOCUMENT_FILL_LOCKED, document_fill_running
    if document_fill_running(session):
        raise HTTPException(409, DOCUMENT_FILL_LOCKED)


async def _owned_session(session_id: str, current_user: dict) -> dict:
    session = await get_processing_session(session_id)
    if str(session.get("user_id")) != str(current_user["id"]):
        raise HTTPException(403, "Access denied")
    return session


async def _refuse_while_generating(session: dict) -> None:
    """409 while a form generation is live (it stamps from the facts it read
    when it started). Forms that exist never lock documents any more."""
    from routes.audit_routes import _refuse_while_generating as _refuse
    await _refuse(session)


async def _package_page(session_id: str, current_user: dict) -> dict:
    """The package page as a reload builds it (`/extraction-result`), so the
    screen after an add is exactly the screen after a refresh."""
    from routes.form_routes import get_extraction_result
    resp = await get_extraction_result(session_id, current_user=current_user)
    try:
        return json.loads(resp.body)
    except Exception:                                          # noqa: BLE001
        return {"success": True, "session_id": session_id}


def _integrity_refusal(ex: IntegrityReviewRequired, change: str = "added") -> HTTPException:
    # Only the OTHER insured(s) - never the package's own applicant (15 Oct
    # 2026: the verdict's entity list put CHOICE ELECTRIC LLC first in "These
    # documents name a different insured (...)" on Choice Electric's package).
    other = str(getattr(ex, "other_insured", None) or "").strip()
    who = f" ({other})" if other else ""
    if change == "added":
        # Two answers since 14 Oct 2026 (owner): keep them as evidence only, or
        # use their values because they ARE this insured (the panel's buttons).
        subject = "This document names" if len(ex.documents or []) == 1 else "These documents name"
        message = (subject + " a different insured" + who + ". Nothing was added yet.")
    else:
        message = ("This document names a different insured" + who + ". Nothing was changed. "
                   "Include it only if it belongs to this insured.")
    return HTTPException(409, detail={
        "error": "submission_integrity_review_required",
        "message": message,
        "integrity": ex.verdict,
        "documents": ex.documents,
        "other_insured": other or None,
        "can_confirm": True,
    })


def _door_fields(door: dict) -> dict:
    """What the documents door changed, for the package page's result line."""
    return {
        "after_forms": bool(door.get("forms_exist")),
        "forms_updated": door.get("forms_updated") or [],
        "boxes_updated": int(door.get("boxes_updated") or 0),
        "boxes_by_form": door.get("boxes_by_form") or {},
        "stale_signatures": door.get("stale_signatures") or [],
        "form_offers": door.get("form_offers") or [],
        "forms_without_line": door.get("forms_without_line") or [],
        "integrity_override_recorded": bool(door.get("integrity_override_recorded")),
        "boxes_taken_back": int(door.get("boxes_taken_back") or 0),
    }


async def reclassify_after_forms(req, session: dict, current_user: dict) -> JSONResponse:
    """`form_routes.document_reclassify` once forms exist (7 Oct 2026): the
    same change (`apply_document_action`), then the documents door, which
    re-stamps the forms. Errors read exactly as the pre-form route's."""
    from routes.form_routes import _PURGE_DEC_INDEX_AFTER_GENERATION
    from services.session_documents import change_document
    _refuse_while_filling(session)
    uid = str(current_user["id"])
    try:
        result = await change_document(
            req.session_id, doc_id=req.doc_id, action=req.action,
            new_doc_type=req.new_doc_type, user_id=uid,
            confirm_same_insured=bool(getattr(req, "confirm_same_insured", False)),
            purge_dec_index=_PURGE_DEC_INDEX_AFTER_GENERATION,
        )
    except IntegrityReviewRequired as ex:
        raise _integrity_refusal(ex, change="changed")
    except ValueError as ve:
        code = str(ve)
        if code == "reclassify_doc_not_found":
            raise HTTPException(404, "Document not found in this submission.")
        if code == "reclassify_no_docs":
            raise HTTPException(409, "This submission has no stored documents to reclassify.")
        if code == "reclassify_invalid_type":
            raise HTTPException(400, "Unsupported document type.")
        logger.error(f"reclassify after forms invalid request [trace={get_trace_id()}]: {ve}")
        raise HTTPException(400, "Could not apply the document classification change.")
    except Exception as ex:                                    # noqa: BLE001
        logger.error(f"reclassify after forms error [trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "Failed to reclassify the document.")

    door = result.get("door") or {}
    _reclass = result.get("reclassified") or {}
    try:
        from services.audit_service import log_document_reclassified
        await log_document_reclassified(
            req.session_id, uid, doc_id=_reclass.get("doc_id") or req.doc_id,
            action=req.action, previous_doc_type=_reclass.get("previous_doc_type"),
            new_doc_type=_reclass.get("new_doc_type"),
        )
        if door.get("integrity_override_recorded"):
            from services.audit_service import log_integrity_resolution
            await log_integrity_resolution(req.session_id, uid, "continue_anyway",
                                           integrity=door.get("integrity_verdict") or {})
    except Exception as _ev:                                   # noqa: BLE001
        logger.warning(f"reclassify after forms: audit failed: {_ev}")
    page = await _package_page(req.session_id, current_user)
    page.update({"action": req.action, **_door_fields(door)})
    return JSONResponse(page)


def _facts_count(docs: List[dict]) -> int:
    n = 0
    for d in docs or []:
        for k, v in (d.get("facts") or {}).items():
            if str(k).startswith("_"):
                continue
            if isinstance(v, dict) and "value" in v:
                v = v.get("value")
            if v not in (None, "", [], {}):
                n += 1
    return n


@router.post("/api/session/{session_id}/documents")
async def add_session_documents(
    session_id: str,
    files: List[UploadFile] = File(...),
    progress_token: Optional[str] = Form(None),
    as_supporting: bool = Form(False),
    doc_type: Optional[str] = Form(None),
    confirm_same_insured: bool = Form(False),
    as_evidence: bool = Form(False),
    current_user: dict = Depends(get_current_user),
):
    from utils.rate_limiter import check_upload_rate_limit
    # Only a real True: called as a plain function, the unset default is the
    # Form() marker itself, which is truthy.
    as_evidence = as_evidence is True
    await check_upload_rate_limit(current_user["id"])
    session = await _owned_session(session_id, current_user)
    check_payment_access(current_user.get("payment_status", "ok"), "upload")
    await _refuse_while_generating(session)
    _refuse_while_filling(session)
    # After forms: the review page's open items BEFORE this add - by identity,
    # with the package score - so the answer (and the AI reading's status,
    # later) can say what is NEW on it.
    counts_before = None
    if session.get("generated_forms"):
        from services.session_documents import review_snapshot
        try:
            counts_before = review_snapshot(await _package_page(session_id, current_user),
                                            await _dismissed_issue_ids(session_id))
        except Exception as ex:                                # noqa: BLE001
            logger.warning(f"add documents: review counts before unavailable: {ex}")

    from services.extraction_service import ALLOWED_DOC_TYPES
    stated_type = (doc_type or "").strip()
    if stated_type in ("", "unknown", "auto"):
        stated_type = ""
    elif stated_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(400, "Unsupported document type.")

    from services.upload_intake import remove_files, store_uploads
    from utils.concurrency import release_heavy, try_acquire_heavy
    uploaded_paths: list = []
    all_paths: list = []
    sem_token = False
    new_docs: list = []
    duplicates: list = []
    reporter = None
    result: dict = {}
    try:
        uploaded_paths, all_paths = await store_uploads(files)

        sem_token = await try_acquire_heavy()
        if not sem_token:
            raise HTTPException(
                429,
                "Server busy - too many requests at once. Please retry in 30 seconds.",
                headers={"Retry-After": "30"},
            )
        from services.job_queue import get_job_queue
        if await get_job_queue().count_user_active_jobs(current_user["id"]) >= 5:
            raise HTTPException(429, "Too many jobs in progress. Please wait.")

        # Only the NEW files are read. The stored documents are re-merged from
        # their stored facts - no OCR and no extraction call for any of them.
        # A file that reads exactly like a document already in the package (or
        # an earlier file of this upload) is skipped before its extraction call.
        from services.extraction_pipeline import (
            _display_name_from_path, extract_document, stored_text_key,
        )
        from utils.progress_tracker import make_reporter
        known = {stored_text_key(d) for d in (session.get("docs") or [])
                 if isinstance(d, dict)} - {""}
        names = [_display_name_from_path(p) for p in all_paths]
        reporter = make_reporter(progress_token, current_user["id"], names)
        await reporter.begin()
        # No ASG pre-submit here (bug hunt, 29 Oct 2026): an added file is checked
        # against the package's documents only after OCR (`extract_document`'s
        # duplicate test), and a pre-submit would pay for a file already in it.
        # Added files are few; each reads its outside ACORD pages in its own turn,
        # on a page budget of their own (`open_package_budget` - before, an added
        # file read with no package cap at all).
        try:
            from services.acord_intake.transcriber_intake import open_package_budget
            open_package_budget()
        except Exception:                                      # noqa: BLE001
            pass
        for i, path in enumerate(all_paths):
            doc = await extract_document(path, names[i], current_user["id"],
                                         reporter=reporter, index=i,
                                         doc_type=stated_type or None, known_texts=known)
            if doc is None:
                continue
            if doc.get("duplicate"):
                duplicates.append(doc.get("filename") or names[i])
                continue
            known.add(stored_text_key(doc))
            if as_supporting:
                doc["supporting_only"] = True
            if as_evidence:
                _keep_as_evidence(doc)
            new_docs.append(doc)
        if not new_docs and duplicates:
            raise HTTPException(409, "These documents are already in this package.")
        if not new_docs:
            raise HTTPException(400, "No readable text found in uploaded files")

        # The package as it stands NOW - reading the files can take minutes.
        # (The door re-reads the row itself, once no other change is running.)
        session = await _owned_session(session_id, current_user)
        await _refuse_while_generating(session)
        _refuse_while_filling(session)
        from routes.form_routes import _PURGE_DEC_INDEX_AFTER_GENERATION
        result = await add_documents(
            session_id, new_docs, user_id=str(current_user["id"]),
            confirm_same_insured=bool(confirm_same_insured),
            purge_dec_index=_PURGE_DEC_INDEX_AFTER_GENERATION, reporter=reporter,
        )
    except IntegrityReviewRequired as ex:
        raise _integrity_refusal(ex)
    except AlreadyInPackage:
        raise HTTPException(409, "These documents are already in this package.")
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(400, "No readable text found in uploaded files")
    except ProcessingIntegrityError:
        raise HTTPException(422, "Document processing failed an integrity check. Please re-upload your files or contact support.")
    except Exception as ex:                                    # noqa: BLE001
        logger.error(f"add documents error [session={session_id} trace={get_trace_id()}]: {ex}",
                     exc_info=True)
        raise HTTPException(500, "Processing failed. Please try again.")
    finally:
        if sem_token:
            await release_heavy(sem_token)
        remove_files(uploaded_paths, all_paths)

    door = result.get("door") or {}
    added = list(result.get("documents_added") or new_docs)
    duplicates = duplicates + list(door.get("duplicates_skipped") or [])
    uid = str(current_user["id"])
    # E&O 5.11: more information entered the package. Same event as an upload.
    try:
        from services.audit_service import log_audit_event, log_integrity_assessed
        await log_audit_event(session_id, uid, "documents_uploaded", {
            "documents": [{"doc_id": d.get("doc_id"), "filename": d.get("filename"),
                           "doc_type": d.get("doc_type"),
                           "doc_type_confidence": d.get("doc_type_confidence")}
                          for d in added],
            "document_count": len(added),
            "facts_extracted": _facts_count(added),
            "duplicates_skipped": duplicates,
            "added_to_package": True,
            "after_forms": bool(door.get("forms_exist")),
            "as_supporting": bool(as_supporting),
            "as_evidence": bool(as_evidence),
            "stated_doc_type": stated_type or None,
        })
        await log_integrity_assessed(session_id, uid, door.get("integrity_verdict") or {})
        if door.get("integrity_override_recorded"):
            from services.audit_service import log_integrity_resolution
            await log_integrity_resolution(session_id, uid, "continue_anyway",
                                           integrity=door.get("integrity_verdict") or {})
    except Exception as _ev:                                   # noqa: BLE001
        logger.warning(f"add documents: audit events failed: {_ev}")
    if reporter is not None:
        try:
            await reporter.done(session_id)
        except Exception:                                      # noqa: BLE001
            pass

    from routes.form_routes import _doc_summary_entry
    page = await _package_page(session_id, current_user)
    # The dashboard keeps its own copy of the pre-form score: an add moves the
    # score, so it refreshes that copy like every other pre-form action (24 Oct
    # 2026: the page read 100 while the dashboard kept 92).
    if not door.get("forms_exist"):
        try:
            from repositories.session_repository import get_processing_session
            from routes.form_routes import _remember_pre_form_score
            await _remember_pre_form_score(session_id, await get_processing_session(session_id),
                                           page.get("package_sqs"))
        except Exception as _ps:                                # noqa: BLE001
            logger.warning(f"add documents: dashboard score not refreshed: {_ps}")
    page.update({"documents_added": [_doc_summary_entry(d) for d in added],
                 "duplicates_skipped": duplicates,
                 "evidence_only": [str(d.get("filename") or "") for d in added if d.get("evidence_only")],
                 **_door_fields(door)})
    # Evidence-only documents are not read into the forms (owner, 14 Oct 2026).
    fill_docs = [d for d in added if not d.get("excluded")]
    background = None
    if door.get("forms_exist") and fill_docs:
        # What is NEW on the review page after the documents door, and the AI
        # reading of the new documents (C103) - recorded RUNNING now (the lock
        # starts with the answer), started once the answer has gone out.
        from services.session_documents import (
            launch_new_document_fill, new_on_review, review_counts, review_snapshot,
            start_new_document_fill,
        )
        page["review_counts"] = review_counts(page)
        page["new_on_review"] = new_on_review(
            counts_before, review_snapshot(page, await _dismissed_issue_ids(session_id)))
        try:
            fill = await start_new_document_fill(session_id, fill_docs, uid,
                                                 review_counts_before=counts_before)
        except Exception as ex:                                # noqa: BLE001
            logger.error(f"add documents: AI fill not started [session={session_id}]: {ex}",
                         exc_info=True)
            fill = {"state": "failed", "message": "Reading the new document into your forms did not start."}
        page["ai_fill"] = _public_fill(fill)
        if fill.get("state") == "running":
            background = BackgroundTask(launch_new_document_fill, session_id, fill, uid)
    return JSONResponse(page, background=background)


def _keep_as_evidence(doc: dict) -> None:
    """"Add as evidence only" (owner, 14 Oct 2026 - the choice offered when a
    document names a different insured after forms): the file is kept with the
    package and listed, but EXCLUDED - the merge, the forms, the score and
    Submission Integrity all read only the active documents - and no AI fill
    reads it. `evidence_insured` keeps the insured it prints, for its tag.
    "Include" in the Documents list brings it in (and asks again)."""
    doc["excluded"] = True
    doc["evidence_only"] = True
    facts = doc.get("facts") if isinstance(doc.get("facts"), dict) else {}
    name = facts.get("applicant_name")
    name = name.get("value") if isinstance(name, dict) else name
    if isinstance(name, str) and name.strip():
        doc["evidence_insured"] = name.strip()


def _public_fill(status: Optional[dict]) -> Optional[dict]:
    """The fill status as the screen reads it (the run's ids and the review
    page snapshot it is compared with stay server-side)."""
    if not isinstance(status, dict):
        return None
    return {k: v for k, v in status.items()
            if k not in ("run_id", "doc_ids", "review_counts_before")}


async def _dismissed_issue_ids(session_id: str) -> set:
    """The issue ids the review page hides - the DISMISSED ones (a resolved
    item that still fires stays listed: `utils/resolvedIssues.splitClusters`).
    Empty when the statuses cannot be read."""
    try:
        from services.audit_service import get_issue_statuses
        rows = await get_issue_statuses(session_id) or []
    except Exception as ex:                                    # noqa: BLE001
        logger.warning(f"add documents: issue statuses unavailable: {ex}")
        return set()
    return {str(r.get("issue_id")) for r in rows
            if isinstance(r, dict) and r.get("issue_id") and r.get("status") == "dismissed"}


@router.get("/api/session/{session_id}/documents/ai-fill")
async def document_fill_status_route(
    session_id: str,
    form_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """The AI reading of documents added after forms (C103) - see the module
    note. `new_on_review` is computed only for the whole package once the run
    is no longer running (it reads the package page)."""
    session = await _owned_session(session_id, current_user)
    from services.generation_state import document_fill_status
    from services.needs_attention import document_suggestion_rows
    from services.session_documents import (
        SUGGESTIONS_KEY, new_on_review, review_counts, review_snapshot,
    )
    status = document_fill_status(session)
    rows = document_suggestion_rows(session.get("generated_forms") or {},
                                    session.get(SUGGESTIONS_KEY) or [], form_id=form_id,
                                    docs=session.get("docs") or [])
    out = {"success": True, "ai_fill": _public_fill(status), "suggestions": rows}
    if status and status.get("state") != "running" and not form_id:
        try:
            page = await _package_page(session_id, current_user)
            out["review_counts"] = review_counts(page)
            out["new_on_review"] = new_on_review(
                status.get("review_counts_before"),
                review_snapshot(page, await _dismissed_issue_ids(session_id)))
        except Exception as ex:                                # noqa: BLE001
            logger.warning(f"document fill status: review counts unavailable: {ex}")
    return JSONResponse(out)


@router.post("/api/session/{session_id}/documents/suggestions/keep")
async def keep_document_suggestion(
    session_id: str,
    req: KeepSuggestionRequest,
    current_user: dict = Depends(get_current_user),
):
    """"Keep current" - the form keeps its value; the suggestion is retired."""
    await _owned_session(session_id, current_user)
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    from services.session_documents import keep_current_value
    gone = await keep_current_value(session_id, (req.suggestion_id or "").strip())
    if gone is None:
        raise HTTPException(404, "That suggestion is no longer open.")
    try:
        from services.audit_service import log_audit_event
        await log_audit_event(session_id, str(current_user["id"]), "document_suggestion_kept", {
            "form_id": gone.get("form_id"), "field": gone.get("field"),
            "kept_value": gone.get("current"), "suggested_value": gone.get("suggested"),
            "documents": gone.get("documents") or [],
        })
    except Exception as ex:                                    # noqa: BLE001
        logger.warning(f"keep suggestion: audit failed: {ex}")
    return JSONResponse({"success": True, "suggestion_id": gone.get("id")})


@router.post("/api/session/{session_id}/documents/add-form")
async def add_offered_session_form(
    session_id: str,
    req: AddOfferedFormRequest,
    current_user: dict = Depends(get_current_user),
):
    """Add one form the documents door offered - see the module note."""
    session = await _owned_session(session_id, current_user)
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    await _refuse_while_generating(session)
    _refuse_while_filling(session)
    if not (session.get("generated_forms") or {}):
        raise HTTPException(409, "Forms have not been generated yet - tick the form on the "
                                 "Select Forms screen instead.")
    from services.form_addition import OK, message_for
    form_id = (req.form_id or "").strip()
    try:
        outcome, payload = await add_offered_form(session_id, form_id)
    except Exception as ex:                                    # noqa: BLE001
        logger.error(f"add offered form failed [session={session_id} form={form_id} "
                     f"trace={get_trace_id()}]: {ex}", exc_info=True)
        raise HTTPException(500, "The form could not be generated. Please try again.")
    if outcome == "not_offered":
        raise HTTPException(409, "That form is not offered for this package.")
    if outcome != OK:
        raise HTTPException(409 if outcome == "already_present" else 400, message_for(outcome))
    try:
        from services.audit_service import log_field_change
        from services.sqs_service import SQS_MODEL_VERSION
        await log_field_change(
            session_id=session_id, user_id=str(current_user["id"]),
            form_id=form_id, field_name=f"form::{form_id}", fact_key=None,
            source="producer", record_unchanged=True,
            previous_value="not in package", new_value="added",
            confidence="filled", model_version=SQS_MODEL_VERSION,
        )
    except Exception as _le:                                   # noqa: BLE001
        logger.warning(f"add offered form: audit log failed: {_le}")
    from services.arq_service import recalculate_session_scores
    await recalculate_session_scores(session_id)
    page = await _package_page(session_id, current_user)
    page.update({"added_form": payload.get("form"),
                 "form_ids": payload.get("selected_form_ids")})
    return JSONResponse(page)


@router.get("/api/session/{session_id}/documents/{doc_id}/form-values")
async def document_form_values(
    session_id: str,
    doc_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Every box ACORD Transcriber read off this document's ACORD pages (29 Oct
    2026, ASG_TRANSCRIBER.md "Keep everything"), grouped: `used` (a box the
    reverse map turns into a fact, with what it feeds) and `read` (read from the
    form - kept, shown, never a fact, never scored). The package's owner only;
    the values are decrypted for this response alone and never logged."""
    session = await _owned_session(session_id, current_user)
    doc = next((d for d in (session.get("docs") or [])
                if isinstance(d, dict) and str(d.get("doc_id")) == str(doc_id)), None)
    if doc is None:
        raise HTTPException(404, "Document not found")
    from services.acord_intake.transcriber_intake import form_values
    values = form_values(doc, session.get("facts") if isinstance(session.get("facts"), dict) else None)
    if values is None:
        raise HTTPException(404, "No values read from a form are kept for this document")
    return JSONResponse({"success": True, "doc_id": doc.get("doc_id"), "filename": doc.get("filename", ""),
                         **values})
