"""questionnaire_routes.py - the narrative questionnaire page (Brent's attachment
A, 23 Oct 2026; 25sepChanges.md Z36). The rules live in
`services/questionnaire.py`; this module is the HTTP shell, and every write goes
through a door that already exists:

  * an answer -> `audit_routes.resolve_issue` (field / schedule mode: the
    producer answer door, its validation, audit row, form re-stamp and the full
    re-score), or - for a value the documents disagree about - the Data
    Consistency door (`form_routes.underwriting_confirm_value` before forms,
    `..._in_editor` after them), which shows both values and never overwrites;
  * "confirm" -> `confirm_known.record_fact_confirmation` /
    `record_schedule_confirmation` (`user_confirmed` evidence, value untouched);
  * Unknown / Pending / Not applicable -> one session key, never a value;
  * "Send to client" -> `arq_routes.send_questions_to_client` (the one mailer);
  * the approved carrier narrative -> `arq_service.apply_producer_answer_to_session`
    on `qn_carrier_narrative`, which ACORD 101's remarks print.
Owner-scoped like every session route; works before and after forms.
"""
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services import questionnaire as qn
from services.auth_service import get_current_user

router = APIRouter(tags=["questionnaire"])
logger = logging.getLogger(__name__)

_MAX_NARRATIVE_CHARS = 12000


class QuestionnaireAnswerRequest(BaseModel):
    question_id: str
    action: str
    value: Optional[Any] = None
    # A Pending / Unknown mark's remediation owner and note (Brent: "Record
    # remediation owner and status").
    owner: Optional[str] = None
    note: Optional[str] = None
    # A line-scoped Data Consistency disagreement: the coverage family it is about.
    scope: Optional[str] = None
    # A disagreement's "Use this": the index of the conflict value (its
    # `choice`) - the server reads the real value, so a masked FEIN never
    # travels back.
    choice: Optional[int] = None
    # The card this answer was opened from (an "Explain via ACORD 101" card's
    # deep link): its rule code - an explanation then answers it
    # (`_explained_issue_codes`) - and its issue id, so "Open again" takes the
    # fix back (the undo receipt), exactly as the card's own window does.
    code: Optional[str] = None
    issue_id: Optional[str] = None


class QuestionnaireSendRequest(BaseModel):
    question_ids: List[str] = []
    # Default: the insured's contact e-mail and name on file.
    client_email: Optional[str] = None
    client_name: Optional[str] = None


class NarrativeApproveRequest(BaseModel):
    text: str = ""


# ── plumbing ─────────────────────────────────────────────────────────────────

async def _get(session_id: str) -> dict:
    from repositories.session_repository import get_processing_session
    return await get_processing_session(session_id)


async def _put(session_id: str, updates: dict) -> None:
    from repositories.session_repository import upd_processing_session
    await upd_processing_session(session_id, updates)


async def _owned(session_id: str, current_user: dict) -> dict:
    from routes.audit_routes import _verify_session_owner
    return await _verify_session_owner(session_id, current_user)


async def _not_while_generating(session: dict) -> None:
    from routes.audit_routes import _refuse_while_generating
    await _refuse_while_generating(session)


async def _audit(session_id: str, current_user: dict, field_name: str, fact_key: Optional[str],
                 previous: Optional[str], new: str) -> None:
    """One E&O row for a write that does not pass through resolve-issue."""
    try:
        from routes import audit_routes as _ar
        await _ar.log_field_change(
            session_id=session_id, user_id=str(current_user["id"]), form_id=None,
            field_name=field_name, fact_key=fact_key, source="producer",
            previous_value=previous, new_value=new, confidence="filled",
            model_version=_ar.SQS_MODEL_VERSION, record_unchanged=True)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("questionnaire: audit row not written (%s)", exc)


async def _refresh(session_id: str, current_user: dict, *, rescore: bool,
                   before: Optional[dict] = None) -> dict:
    """resolve-issue's refresh shape for a write that did not go through it
    (a confirmation, a status, a Data Consistency settle) - built from the same
    helpers (`audit_routes`), so the Review screen and the editor read one
    shape. A re-score is handed the row as it was BEFORE the write (`before`),
    so before forms the recommender re-runs when the write moved which forms
    apply, and the new list rides along (`arq_service.refreshed_form_list` -
    the only `recommendations` this response ever carries)."""
    from routes.audit_routes import (
        _editor_score_refresh, _form_selection_view, _grade_from_score,
        _grouped_cross_issues_for_panel, _package_page_key_details, _pre_form_readiness,
    )
    from services.arq_service import refreshed_form_list
    impact: dict = {}
    if rescore:
        from services.arq_service import recalculate_session_scores
        impact = await recalculate_session_scores(session_id, before=before)
        impact = impact if isinstance(impact, dict) else {}
    sess = await _get(session_id)
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
    card = await _pre_form_readiness(sess, session_id, current_user,
                                     scored=package_sqs if impact.get("package_rescored") else None)
    if card is not None:
        package_sqs = card["package_sqs"] or {}
    view = _form_selection_view(sess, cross_issues, package_sqs=package_sqs)
    return {
        "success": True,
        "updated_forms": updated_forms,
        "new_package_sqs_score": package_sqs.get("package_sqs_score"),
        "new_package_tier": package_sqs.get("tier"),
        "cross_issues": cross_issues,
        "grouped_cross_issues": _grouped_cross_issues_for_panel(cross_issues, facts=sess.get("facts") or {}),
        **view,
        **(card or {}),
        **_editor_score_refresh(sess),
        **_package_page_key_details(sess),
        **refreshed_form_list(impact, sess),
    }


async def _resolve(session_id: str, current_user: dict, **req) -> dict:
    """The producer answer door, as the inline fix window calls it."""
    from models.schemas import ResolveIssueRequest
    from routes.audit_routes import resolve_issue
    resp = await resolve_issue(ResolveIssueRequest(session_id=session_id, **req),
                               current_user=current_user)
    return json.loads(resp.body)


def _door_error(body: dict) -> str:
    return (body.get("validation_error") or body.get("message")
            or ("Inline answers are switched off." if body.get("disabled") else None)
            or "This answer could not be applied.")


async def _clear_status(session_id: str, qid: str) -> None:
    sess = await _get(session_id)
    if qid in (sess.get(qn.STATUS_KEY) or {}):
        await _put(session_id, {qn.STATUS_KEY: qn.with_status(sess, qid, None)})


async def _settle_conflict(session_id: str, session: dict, q: qn.Question, text: str,
                           scope: Optional[str], current_user: dict):
    """The documents disagree: the producer's pick goes through the Data
    Consistency door - the picker's own record of both values stays."""
    from models.schemas import UnderwritingConfirmRequest
    from routes import form_routes as fr
    field = qn._Page(session).uw_field(q.fact) or {}
    lines = [s for s in (field.get("conflict_scope") or []) if s]
    if not scope and len(lines) > 1:
        return False, ("The documents disagree about this on more than one coverage line - settle each "
                       "line in Data Consistency."), None
    scope = scope or (lines[0] if lines else None)
    creq = UnderwritingConfirmRequest(session_id=session_id, fact_key=q.fact, value=text, scope=scope)
    try:
        if session.get("generated_forms"):
            resp = await fr.underwriting_confirm_value_in_editor(creq, current_user=current_user)
        else:
            resp = await fr.underwriting_confirm_value(creq, current_user=current_user)
    except HTTPException as he:
        return False, str(he.detail), None
    refresh = await _refresh(session_id, current_user, rescore=False)
    # Before forms the door re-ran the pipeline, recommender included: its form
    # list is the refreshed one (the confirm-value response's own keys).
    try:
        done = json.loads(resp.body) if resp is not None and hasattr(resp, "body") else {}
    except Exception:                                          # noqa: BLE001
        done = {}
    if not session.get("generated_forms"):
        for key in ("recommendations", "account_profile", "all_available_forms"):
            if key in done:
                refresh[key] = done[key]
    return True, None, refresh


# ── the page ─────────────────────────────────────────────────────────────────

@router.get("/api/questionnaire/{session_id}")
async def get_questionnaire(session_id: str, all: bool = False,
                            current_user: dict = Depends(get_current_user)):
    """The page: sections (only the modules this submission asks for, unless
    `all` - Brent's "allow manual additions"), each question prefilled with its
    state and sources, the open count and the carrier narrative."""
    session = await _owned(session_id, current_user)
    return JSONResponse(qn.build_page(session, all_sections=bool(all)))


@router.post("/api/questionnaire/{session_id}/answer")
async def answer_question(session_id: str, req: QuestionnaireAnswerRequest,
                          current_user: dict = Depends(get_current_user)):
    session = await _owned(session_id, current_user)
    q = qn.question(req.question_id)
    action = (req.action or "").strip().lower()
    ok, err, refresh = False, None, None
    if q is None:
        err = "Unknown question."
    elif action not in qn.ACTIONS:
        err = "Unknown action."
    elif q.computed and action in ("answer", "confirm"):
        err = ("Primble fills this in from the rest of the page."
               if q.computed == "open_items" else
               "Edit the underlying policies in the Policies table.")
    else:
        try:
            if action == "answer":
                ok, err, refresh = await _answer(session_id, session, q, req, current_user)
            elif action == "confirm":
                ok, err, refresh = await _confirm(session_id, session, q, current_user)
            else:
                await _not_while_generating(session)
                entry = qn.status_entry(session, q.id, action, user_id=current_user.get("id"),
                                        owner=req.owner, note=req.note)
                await _put(session_id, {qn.STATUS_KEY: qn.with_status(session, q.id, entry)})
                await _audit(session_id, current_user, f"questionnaire::{q.id}", q.fact, None,
                             f"marked {action.replace('_', ' ')}")
                ok, refresh = True, await _refresh(session_id, current_user, rescore=False)
        except HTTPException as he:
            ok, err = False, str(he.detail)
    sess = await _get(session_id)
    page = qn.build_page(sess)
    rendered = qn.find_rendered(page, q.id) if q else None
    if rendered is None and q is not None:
        rendered = qn.reading_for(sess, q.id)
    refresh = refresh or {}
    package_sqs = (refresh.get("package_sqs") or refresh.get("editor_package_sqs")
                   or sess.get("package_sqs") or {})
    return JSONResponse({
        **refresh,
        "ok": bool(ok),
        "error": None if ok else (err or "This answer could not be applied."),
        "question": rendered,
        "counts": page["counts"],
        "package_sqs": package_sqs,
        "grouped_issues": refresh.get("grouped_issues"),
    })


async def _answer(session_id: str, session: dict, q: qn.Question, req: QuestionnaireAnswerRequest,
                  current_user: dict):
    card = {k: v for k, v in (("code", req.code), ("issue_id", req.issue_id)) if v}
    if q.table:
        if not isinstance(req.value, list):
            return False, "Send the table's rows.", None
        rows = qn.merged_table_rows(q, session, req.value)
        body = await _resolve(session_id, current_user, mode="schedule", schedule_key=q.table,
                              rows=rows, **card)
        if body.get("success") and q.columns:
            # The producer saved THIS view: its own columns are theirs now.
            fresh = await _get(session_id)
            facts = dict(fresh.get("facts") or {})
            qn.record_view_confirmation(facts, q, qn.reading_for(fresh, q.id)["value"] or [],
                                        qn.now_iso())
            from services import confirm_known
            await _put(session_id, {"facts": {confirm_known.CONFIRMATIONS_KEY:
                                              facts[confirm_known.CONFIRMATIONS_KEY]}})
    else:
        if req.choice is not None:
            text = qn.choice_value(session, q, req.choice)
            if not text:
                return False, "That value is no longer one of the choices - reload the page.", None
        else:
            text = qn.answer_text(q, req.value)
        if not text:
            return False, "Enter an answer - or mark it Unknown, Pending or Not applicable.", None
        refusal = qn.answer_refusal(q, text)
        if refusal:
            return False, refusal, None
        reading = qn.reading_for(session, q.id) or {}
        if reading.get("state") == qn.CONFLICTING and qn._Page(session).uw_field(q.fact):
            ok, err, refresh = await _settle_conflict(session_id, session, q, text, req.scope, current_user)
            if ok:
                await _clear_status(session_id, q.id)
            return ok, err, refresh
        if q.fact == qn.REMARKS_FACT:
            body = await _answer_remarks(session_id, session, text, current_user, card)
        else:
            body = await _resolve(session_id, current_user, mode="field", field=q.fact, value=text,
                                  **card)
    if not body.get("success"):
        return False, _door_error(body), body
    await _clear_status(session_id, q.id)
    return True, None, body


async def _answer_remarks(session_id: str, session: dict, text: str, current_user: dict,
                          card: dict) -> dict:
    """The ACORD 101 remarks (L.6): the box shows the whole remarks, so text
    that only ADDS to them (or the first remarks) goes through the append door
    every "Explain via ACORD 101" window uses - resolve-issue narrative mode,
    with the card's code and issue id, so the explanation answers its card and
    "Open again" takes it back; an edit of what is there replaces it through the
    producer answer door, and the card's code is then recorded the same way
    (folded into that fix's undo receipt)."""
    existing = str(qn._unwrap((session.get("facts") or {}).get(qn.REMARKS_FACT)) or "").strip()
    if not existing or (text.startswith(existing) and text.strip() != existing):
        return await _resolve(session_id, current_user, mode="narrative",
                              text=text[len(existing):].strip(), **card)
    body = await _resolve(session_id, current_user, mode="field", field=qn.REMARKS_FACT, value=text,
                          **card)
    if not body.get("success"):
        return body
    from services.arq_service import store_narrative_reading
    await store_narrative_reading(session_id)
    if card.get("code"):
        before = await _get(session_id)
        from services.issue_registry import explained_issue_codes
        codes = sorted(explained_issue_codes(before.get("facts") or {}) | {str(card["code"])})
        await _put(session_id, {"facts": {"_explained_issue_codes": {
            "value": codes, "source": "producer", "confidence": "producer"}}})
        if card.get("issue_id"):
            try:
                from services.issue_fix_undo import capture, record_fix
                receipt = capture(before, await _get(session_id))
                if receipt:
                    await record_fix(session_id, card["issue_id"], receipt)
            except Exception as exc:                           # noqa: BLE001
                logger.warning("questionnaire: explained-code receipt not recorded (%s)", exc)
        body = {**body, **await _refresh(session_id, current_user, rescore=True, before=before)}
    return body


async def _confirm(session_id: str, session: dict, q: qn.Question, current_user: dict):
    from services import confirm_known
    reading = qn.reading_for(session, q.id) or {}
    state = reading.get("state")
    if state == qn.CONFLICTING:
        return False, "The documents disagree - choose the right value instead.", None
    if reading.get("value") in (None, "", []) and not reading.get("display_value"):
        return False, "There is nothing to confirm yet - enter the answer.", None
    if state == qn.NOT_APPLICABLE:
        return False, "There is nothing to confirm yet - enter the answer.", None
    if reading.get("prefilled_from"):
        # The value came from another fact: confirming it makes it this
        # question's answer, through the producer door like any answer.
        body = await _resolve(session_id, current_user, mode="field", field=q.fact,
                              value=str(reading.get("display_value") or ""))
        if not body.get("success"):
            return False, _door_error(body), body
        await _clear_status(session_id, q.id)
        return True, None, body
    await _not_while_generating(session)
    facts = dict(session.get("facts") or {})
    at = qn.now_iso()
    if q.table:
        if q.columns:
            # One view of the table: only its own columns are confirmed.
            qn.record_view_confirmation(facts, q, reading.get("value") or [], at)
        else:
            confirm_known.record_schedule_confirmation(facts, q.table, reading.get("value") or [], None,
                                                       at, by="producer")
        await _put(session_id, {"facts": {confirm_known.CONFIRMATIONS_KEY:
                                          facts[confirm_known.CONFIRMATIONS_KEY]}})
        await _audit(session_id, current_user, f"questionnaire::{q.id}", q.table, None, "table confirmed")
        await _clear_status(session_id, q.id)
        return True, None, await _refresh(session_id, current_user, rescore=False)
    raw = facts.get(q.fact)
    if not confirm_known.record_fact_confirmation(facts, q.fact, raw, None, at, by="producer"):
        # A list / yes-no / bare value `record_fact_confirmation` does not show:
        # the same mark on the envelope, value untouched.
        from services.fact_state import USER_CONFIRMED
        env = dict(raw) if isinstance(raw, dict) and "value" in raw else {"value": raw}
        env.update(evidence_state=USER_CONFIRMED, evidence_actor="producer",
                   confirmed_by="producer", confirmed_at=at)
        facts[q.fact] = env
        conf = dict(facts.get(confirm_known.CONFIRMATIONS_KEY) or {})
        conf[f"fact:{q.fact}"] = {"at": at, "arq_id": None, "by": "producer",
                                  "value": reading.get("display_value")}
        facts[confirm_known.CONFIRMATIONS_KEY] = conf
    await _put(session_id, {"facts": {q.fact: facts[q.fact],
                                      confirm_known.CONFIRMATIONS_KEY: facts[confirm_known.CONFIRMATIONS_KEY]}})
    shown = None if q.secure else str(reading.get("display_value") or "")[:2000]
    await _audit(session_id, current_user, f"questionnaire::{q.id}", q.fact, shown, "confirmed")
    await _clear_status(session_id, q.id)
    return True, None, await _refresh(session_id, current_user, rescore=True, before=session)


# ── Send to client (the existing ARQ door) ───────────────────────────────────

@router.post("/api/questionnaire/{session_id}/send-to-client")
async def send_to_client(session_id: str, req: QuestionnaireSendRequest,
                         current_user: dict = Depends(get_current_user)):
    session = await _owned(session_id, current_user)
    page = qn.build_page(session, all_sections=True)
    chosen = []
    for qid in req.question_ids or []:
        r = qn.find_rendered(page, str(qid))
        if r and r.get("insured_confirmable") and qid not in chosen:
            chosen.append(str(qid))
    if not chosen:
        return JSONResponse({"ok": False, "link": None,
                             "error": "Choose at least one question the insured can answer."})
    facts = session.get("facts") or {}
    email = (req.client_email or qn.display(facts.get("contact_email")) or "").strip()
    name = (req.client_name or qn.display(facts.get("contact_name")) or "").strip()
    if not email:
        return JSONResponse({"ok": False, "link": None, "error": "Enter the client's e-mail address."})
    from routes import arq_routes
    try:
        sent = await arq_routes.send_questions_to_client(
            session_id=session_id, client_email=email, client_name=name,
            questions=qn.arq_questions(session, chosen), current_user=current_user)
    except HTTPException as he:
        return JSONResponse({"ok": False, "link": None, "error": str(he.detail)})
    # Each item is now pending with the insured until their answer lands (a
    # status yields the moment the fact changes).
    fresh = await _get(session_id)
    statuses = dict(fresh.get(qn.STATUS_KEY) or {})
    for qid in chosen:
        statuses[qid] = qn.status_entry(fresh, qid, qn.PENDING, user_id=current_user.get("id"),
                                        owner="insured", note=f"Sent to {name or email}")
    await _put(session_id, {qn.STATUS_KEY: statuses})
    return JSONResponse({"ok": True, "link": sent.get("link"), "error": None,
                         "arq_id": sent.get("arq_id"), "email_sent": sent.get("email_sent"),
                         "sent": len(chosen)})


# ── The carrier narrative (improving-ll.md C110) ─────────────────────────────

@router.post("/api/questionnaire/{session_id}/narrative/draft")
async def draft_narrative(session_id: str, current_user: dict = Depends(get_current_user)):
    session = await _owned(session_id, current_user)
    if not qn.narrative_enabled():
        return JSONResponse({"ok": False, "text": None, "error": "The narrative writer is switched off."})
    evidence = qn.narrative_evidence(qn.build_page(session))
    if not evidence:
        return JSONResponse({"ok": False, "text": None,
                             "error": "Nothing is confirmed or read from the documents yet."})
    text, report = await qn.write_narrative(evidence)
    if not text:
        return JSONResponse({"ok": False, "text": None,
                             "error": "The narrative could not be written. Please try again."})
    blob = qn.load_narrative(await _get(session_id))
    blob.update(draft=text, drafted_at=qn.now_iso(), evidence_ids=[e["id"] for e in evidence],
                gate=report)
    await _put(session_id, {qn.NARRATIVE_KEY: qn.dump_narrative(blob)})
    return JSONResponse({"ok": True, "text": text, "error": None,
                         "narrative": qn.narrative_summary({qn.NARRATIVE_KEY: blob})})


@router.post("/api/questionnaire/{session_id}/narrative/approve")
async def approve_narrative(session_id: str, req: NarrativeApproveRequest,
                            current_user: dict = Depends(get_current_user)):
    session = await _owned(session_id, current_user)
    await _not_while_generating(session)
    text = str(req.text or "").strip()
    if not text or len(text) > _MAX_NARRATIVE_CHARS:
        return JSONResponse({"ok": False, "narrative": qn.narrative_summary(session),
                             "error": ("Enter the narrative to approve." if not text
                                       else "The narrative is too long for ACORD 101.")})
    from services.arq_service import apply_producer_answer_to_session
    applied, _ = await apply_producer_answer_to_session(session_id, qn.NARRATIVE_FACT, text)
    if not applied:
        return JSONResponse({"ok": False, "narrative": qn.narrative_summary(session),
                             "error": "The narrative could not be saved."})
    fresh = await _get(session_id)
    blob = qn.load_narrative(fresh)
    previous = blob.get("approved")
    blob.update(approved=text, approved_at=qn.now_iso(), approved_by=str(current_user.get("id")))
    blob.pop("draft", None)
    blob.pop("drafted_at", None)
    await _put(session_id, {qn.NARRATIVE_KEY: qn.dump_narrative(blob)})
    await _audit(session_id, current_user, "questionnaire::narrative", qn.NARRATIVE_FACT,
                 f"{len(previous)} characters" if previous else None, f"approved ({len(text)} characters)")
    if fresh.get("generated_forms"):
        from services.arq_service import recalculate_session_scores
        await recalculate_session_scores(session_id)
    forms = set((fresh.get("generated_forms") or {}).keys()) | set(fresh.get("selected_form_ids") or [])
    return JSONResponse({"ok": True, "error": None,
                         "narrative": qn.narrative_summary({qn.NARRATIVE_KEY: blob}),
                         "on_acord_101": "ACORD_101" in forms})
