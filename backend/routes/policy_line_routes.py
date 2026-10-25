"""policy_line_routes.py - "Policies in this submission": correct a policy,
add one the documents do not show, remove one you added (7 Oct 2026, Choice
Electric #9). The rules live in `services/policy_lines.py`; this module is the
HTTP shell: owner check, the generation lock, the re-run before forms or the
in-place re-stamp after them, the audit rows, and the response shapes the
Review screen already reads (confirm-value before forms, confirm-value-in-
editor after them).
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from repositories.session_repository import get_processing_session, upd_processing_session
from services.auth_service import get_current_user
from services import policy_lines as pl
from utils.json_logging import get_trace_id

router = APIRouter(tags=["policy-lines"])
logger = logging.getLogger(__name__)


class PolicyLineEditRequest(BaseModel):
    edit_key: str
    fields: Dict[str, Optional[str]] = {}


class PolicyLineAddRequest(BaseModel):
    line: str
    fields: Dict[str, Optional[str]] = {}


class PolicyLineAddFormRequest(BaseModel):
    form_id: str


class PolicyLinePriorOtherRequest(BaseModel):
    edit_key: str = ""


# One change at a time per package in this process: two quick saves would
# otherwise each read the store before the other wrote it. The lock lives with
# the store (`policy_lines.session_lock`) because the questionnaire's answers
# about a policy write the same store (22 Oct 2026).
def _lock_for(session_id: str) -> asyncio.Lock:
    return pl.session_lock(session_id)


def _owner(session: dict, current_user: dict) -> None:
    if session.get("user_id") != str(current_user["id"]):
        raise HTTPException(403, "Access denied")


async def _refuse_while_running(session: dict) -> None:
    """409 while a generation run is live - its forms are stamped from the
    facts it read (the existing lock text, `generation_state`)."""
    from routes.form_routes import _generation_state_for
    from services.generation_state import STATE_RUNNING
    state, _job = await _generation_state_for(session)
    if state == STATE_RUNNING:
        raise HTTPException(409, "Forms are being generated - wait for them to finish.")
    # The AI reading of a document added after forms writes onto the same
    # forms (C103) - wait for it, as the documents door does.
    from services.generation_state import DOCUMENT_FILL_LOCKED, document_fill_running
    if document_fill_running(session):
        raise HTTPException(409, DOCUMENT_FILL_LOCKED)


async def _audit(session_id: str, user_id: str, rows: list) -> None:
    if not rows:
        return
    try:
        from services.audit_service import log_field_change
        from services.sqs_service import SQS_MODEL_VERSION
    except Exception as ex:                                   # noqa: BLE001
        logger.warning(f"policy lines: audit unavailable: {ex}")
        return
    for row in rows:
        try:
            await log_field_change(
                session_id=session_id, user_id=user_id, form_id=None,
                field_name=str(row.get("field"))[:200], fact_key=None, source="producer",
                previous_value=(str(row.get("previous") or "").strip()[:2000] or None),
                new_value=(str(row.get("new") or "").strip()[:2000] or "(cleared)"),
                confidence="producer", model_version=SQS_MODEL_VERSION,
            )
        except Exception as ex:                               # noqa: BLE001
            logger.warning(f"policy lines: audit row failed: {ex}")


async def _pre_form_response(session_id: str, result: dict, current_user: dict) -> dict:
    """The confirm-value response shape (the Review screen's own refresh)."""
    from routes.form_routes import _grouped_with_package_caps, _pre_form_status
    from services.sqs_service import classify_stops
    integrity = result.get("integrity") or {}
    _can_warn, _remaining_hard, _downgraded = classify_stops(
        result.get("hard_stops") or [], result.get("mflags") or {})
    _soft = result.get("soft_stops") or []
    # The status object, as the confirm-value route reads it: the score so far,
    # the key details and the "Before you generate" dry run (DRYRUN, 7 Oct).
    _status = await _pre_form_status(
        result["session_id"], result.get("merged_facts") or {},
        result.get("mflags") or {}, integrity, current_user, remember_score=True)
    _pkg, _key = _status
    _grouped = _grouped_with_package_caps(
        result.get("structured_issues") or [], result.get("hard_stops") or [], _soft, _pkg,
        facts=result.get("merged_facts") or {})
    uw = result.get("underwriting_consistency") or {}
    return {
        "success": True,
        "session_id": result["session_id"],
        "after_forms": False,
        "underwriting_consistency": uw,
        "policy_lines": uw.get("policy_lines") or [],
        "unmatched_policy_edits": uw.get("unmatched_policy_edits") or [],
        "recommendations": result.get("recommendations") or [],
        "account_profile": result.get("account_profile") or {},
        "all_available_forms": result.get("extra_forms_scored") or [],
        "flags": result.get("mflags") or {},
        "hard_stops": _remaining_hard,
        "soft_stops": _soft,
        "can_proceed_with_warning": _can_warn,
        "warning_stops": _downgraded,
        "grouped_issues": _grouped,
        "tier2_score": result.get("tier2_score"),
        "tier2_missing": result.get("tier2_missing") or [],
        "package_sqs": _pkg,
        "key_details": _key,
        "dry_run": getattr(_status, "dry_run", None),
        "normalized_differences": result.get("normalized_differences") or [],
        "doc_conflicts": result.get("doc_conflicts") or [],
        "integrity": integrity,
        "integrity_review_required": bool(integrity.get("review_required")),
    }


async def _post_form_response(session_id: str, forms_updated: list) -> dict:
    """The confirm-value-in-editor response shape (resolve-issue's), plus the
    add-form offers for a line the producer added."""
    from routes.audit_routes import (
        _editor_score_refresh, _form_selection_view, _grade_from_score,
        _grouped_cross_issues_for_panel, _package_page_key_details,
    )
    sess = await get_processing_session(session_id)
    updated_forms: dict = {}
    for fid, fdata in (sess.get("generated_forms") or {}).items():
        score = (fdata.get("sqs") or {}).get("sqs_score") if isinstance(fdata, dict) else None
        if score is None:
            continue
        g, t, c = _grade_from_score(int(score), (fdata.get("sqs") or {}).get("open_hard_stops"))
        updated_forms[fid] = {"new_sqs_score": int(score), "new_grade": g, "new_tier": t,
                              "new_tier_color": c, "new_sqs": fdata.get("sqs")}
    cross_issues = sess.get("cross_issues_last") or []
    package_sqs = sess.get("package_sqs") or {}
    view = _form_selection_view(sess, cross_issues, package_sqs=package_sqs)
    uw = sess.get("underwriting_consistency") or {}
    return {
        "success": True,
        "session_id": session_id,
        "after_forms": True,
        "forms_updated": forms_updated or [],
        "underwriting_consistency": uw,
        "policy_lines": uw.get("policy_lines") or [],
        "unmatched_policy_edits": uw.get("unmatched_policy_edits") or [],
        "add_form_offers": pl.form_offers(sess),
        "updated_forms": updated_forms,
        "new_package_sqs_score": package_sqs.get("package_sqs_score"),
        "new_package_tier": package_sqs.get("tier"),
        "cross_issues": cross_issues,
        # The session facts: a COPE card's fix follows the package (2+ buildings:
        # per building, only what is missing - premises_cope, 21 Oct 2026).
        "grouped_cross_issues": _grouped_cross_issues_for_panel(
            cross_issues, facts=sess.get("facts") or {}),
        "hard_stops": view["hard_stops"],
        "soft_stops": view["soft_stops"],
        "grouped_issues": view["grouped_issues"],
        "can_proceed_with_warning": view["can_proceed_with_warning"],
        "warning_stops": view["warning_stops"],
        **_editor_score_refresh(sess),
        **_package_page_key_details(sess),
    }


async def _change(session_id: str, current_user: dict, action: str, **kw) -> JSONResponse:
    session = await get_processing_session(session_id)
    _owner(session, current_user)
    await _refuse_while_running(session)
    user_id = str(current_user["id"])
    async with _lock_for(session_id):
        session = await get_processing_session(session_id)
        try:
            new_store, audit_rows = pl.plan_change(session, action, user=user_id, **kw)
        except pl.PolicyLineError as e:
            return JSONResponse({"success": False, "errors": e.errors, "message": e.message},
                                status_code=400)
        except KeyError:
            raise HTTPException(404, "That policy is no longer in this submission - reload the page.")
        after_forms = bool(session.get("generated_forms"))
        if not audit_rows:
            # Nothing changed: answer with the screen as it stands.
            uw = session.get("underwriting_consistency") or {}
            return JSONResponse({"success": True, "changed": False, "after_forms": after_forms,
                                 "policy_lines": pl.table_rows(session.get("facts") or {}, pl._active_docs(session)),
                                 "unmatched_policy_edits": uw.get("unmatched_policy_edits") or [],
                                 "add_form_offers": pl.form_offers(session) if after_forms else []})
        try:
            if after_forms:
                out = await pl.apply_post_generation(session, session_id, new_store)
                from services.arq_service import recalculate_session_scores
                await recalculate_session_scores(session_id)
                await _audit(session_id, user_id, audit_rows)
                body = await _post_form_response(session_id, out.get("forms_updated") or [])
            else:
                docs = list(session.get("docs") or [])
                if not docs:
                    raise HTTPException(409, "This submission has no stored documents.")
                from services.extraction_pipeline import _finalize_pipeline
                facts = copy.deepcopy(session.get("facts") or {})
                facts[pl.STORE_KEY] = new_store
                prior_integrity = session.get("integrity") or {}
                override = prior_integrity.get("override") if prior_integrity.get("overridden") else None
                result = await _finalize_pipeline(
                    docs, user_id, session_id=session_id, integrity_override=override,
                    confirmations=session.get("underwriting_confirmations") or {},
                    probe_umbrella=False,
                    client_answer_conflicts=session.get("client_answer_conflicts") or {},
                    prior_facts=facts, prior_flags=session.get("flags") or {},
                )
                # The facts write is additive: a derived key this run left empty
                # (the last added line removed from a package with no rows of
                # its own) is retracted explicitly.
                stale = pl.stale_keys(session.get("facts") or {}, result.get("merged_facts") or {})
                if stale:
                    await upd_processing_session(session_id, {}, delete_facts=stale)
                await _audit(session_id, user_id, audit_rows)
                body = await _pre_form_response(session_id, result, current_user)
        except HTTPException:
            raise
        except Exception as ex:                               # noqa: BLE001
            logger.error(f"policy lines {action} failed [session={session_id} "
                         f"trace={get_trace_id()}]: {ex}", exc_info=True)
            raise HTTPException(500, "The change could not be saved. Please try again.")
    body["changed"] = True
    return JSONResponse(body)


@router.get("/api/policy-lines/options")
async def policy_line_options(current_user: dict = Depends(get_current_user)):
    """The lines a producer may add."""
    return JSONResponse({"lines": pl.line_options(), "fields": pl.FIELD_LABELS})


@router.get("/api/policy-lines/{session_id}")
async def policy_lines_for(session_id: str, current_user: dict = Depends(get_current_user)):
    """The table as it stands (the Review screen normally reads it from
    `underwriting_consistency.policy_lines`)."""
    session = await get_processing_session(session_id)
    _owner(session, current_user)
    after_forms = bool(session.get("generated_forms"))
    uw = session.get("underwriting_consistency") or {}
    return JSONResponse({
        "policy_lines": pl.table_rows(session.get("facts") or {}, pl._active_docs(session)),
        "unmatched_policy_edits": uw.get("unmatched_policy_edits") or [],
        "add_form_offers": pl.form_offers(session) if after_forms else [],
        "after_forms": after_forms,
    })


@router.post("/api/policy-lines/{session_id}/edit")
async def policy_line_edit(session_id: str, req: PolicyLineEditRequest,
                           current_user: dict = Depends(get_current_user)):
    """Correct one policy's carrier / NAIC / number / term / premium. An empty
    value clears that box (never the carrier)."""
    return await _change(session_id, current_user, "edit",
                         edit_key=req.edit_key, fields=dict(req.fields or {}))


@router.post("/api/policy-lines/{session_id}/add")
async def policy_line_add(session_id: str, req: PolicyLineAddRequest,
                          current_user: dict = Depends(get_current_user)):
    """Add a policy the documents do not show."""
    return await _change(session_id, current_user, "add",
                         line_key=req.line, fields=dict(req.fields or {}))


@router.delete("/api/policy-lines/{session_id}/added/{line_id}")
async def policy_line_remove(session_id: str, line_id: str,
                             current_user: dict = Depends(get_current_user)):
    """Remove a policy the producer added. A document's policy cannot be
    removed here (correct it instead)."""
    return await _change(session_id, current_user, "remove", line_id=line_id)


@router.post("/api/policy-lines/{session_id}/prior-other")
async def policy_line_prior_other(session_id: str, req: PolicyLinePriorOtherRequest,
                                  current_user: dict = Depends(get_current_user)):
    """Choose the policy ACORD 125's prior-carrier OTHER column holds (Brent,
    19 Oct 2026: the primary umbrella / excess "unless the agent specifies
    otherwise"); an empty key goes back to that rule. The rest are listed on
    ACORD 101."""
    return await _change(session_id, current_user, "prior_other", edit_key=req.edit_key)


@router.post("/api/policy-lines/{session_id}/add-form")
async def policy_line_add_form(session_id: str, req: PolicyLineAddFormRequest,
                               current_user: dict = Depends(get_current_user)):
    """Generate the form an ADDED policy line needs, after forms exist - only
    a form the server itself offers (`policy_lines.form_offers`), never one
    named by the wire. Never automatic: this runs on the producer's click."""
    from utils.helpers import check_payment_access
    from services.form_addition import OK, add_form_to_session, message_for
    session = await get_processing_session(session_id)
    _owner(session, current_user)
    await _refuse_while_running(session)
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    if not session.get("generated_forms"):
        raise HTTPException(409, "Forms are not generated yet - tick the form on the form list.")
    form_id = str(req.form_id or "").strip()
    offered = {o.get("form_id") for o in pl.form_offers(session)}
    if not form_id or form_id not in offered:
        return JSONResponse({"success": False, "outcome": "not_requested",
                             "message": "That form is not needed by a policy you added."})
    async with _lock_for(session_id):
        try:
            outcome, payload = await add_form_to_session(session_id, form_id,
                                                         enforce_requested=False)
        except Exception as ex:                               # noqa: BLE001
            logger.error(f"policy lines add-form failed [session={session_id} form={form_id} "
                         f"trace={get_trace_id()}]: {ex}", exc_info=True)
            return JSONResponse({"success": False,
                                 "message": "The form could not be generated. Please try again."})
        if outcome != OK:
            return JSONResponse({"success": False, "outcome": outcome,
                                 "message": message_for(outcome)})
        try:
            from services.audit_service import log_field_change
            from services.sqs_service import SQS_MODEL_VERSION
            await log_field_change(
                session_id=session_id, user_id=str(current_user["id"]), form_id=form_id,
                field_name=f"form::{form_id}", fact_key=None, source="producer",
                record_unchanged=True, previous_value="not in package", new_value="added",
                confidence="filled", model_version=SQS_MODEL_VERSION,
            )
        except Exception as ex:                               # noqa: BLE001
            logger.warning(f"policy lines add-form: audit failed: {ex}")
        from services.arq_service import recalculate_session_scores
        await recalculate_session_scores(session_id)
        body = await _post_form_response(session_id, [form_id])
    body["added_form"] = (payload or {}).get("form")
    body["form_ids"] = (payload or {}).get("selected_form_ids")
    body["changed"] = True
    return JSONResponse(body)
