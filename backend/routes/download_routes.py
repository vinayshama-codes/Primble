import io
import logging
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from config.database import get_db
from repositories.session_repository import get_processing_session
from repositories.audit_repository import write_audit_log
from services.auth_service import get_current_user
from services.cover_service import generate_ai_cover_narrative, build_cover_page_pdf
from services.pdf_service import regenerate_pdf_for_form
from services.stripe_service import evaluate_package_limit, create_overage_invoice_item
from services.sqs_service import calculate_sqs

router = APIRouter(tags=["downloads"])
logger = logging.getLogger(__name__)


def _refresh_user(user_id: str) -> dict:
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


@router.get("/api/download-pdf/{session_id}/{form_id}")
async def download_pdf(
    session_id: str,
    form_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    fresh = _refresh_user(current_user["id"])
    if not fresh:
        from fastapi import HTTPException
        raise HTTPException(401, "User not found")
    sub  = fresh.get("subscription_tier", "free") or "free"
    used = int(fresh.get("downloads_used", 0) or 0)

    if fresh.get("payment_status") == "suspended":
        return JSONResponse({"success": False, "payment_locked": True, "message": "Account suspended."}, status_code=403)
    if sub == "lite":
        return JSONResponse({"success": False, "message": "ACORD form downloads are not included in the Lite plan."}, status_code=403)
    if sub == "free" and used >= 3:
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Free limit reached."}, status_code=403)

    pkg_eval = None
    if sub in ("essentials", "professional"):
        pkg_eval = evaluate_package_limit(fresh)

    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    form_name    = generated.get(form_id, {}).get("form_name", form_id)
    pdf_bytes    = regenerate_pdf_for_form(proc_session, form_id, force=True)
    facts        = proc_session.get("facts", {})
    flags        = proc_session.get("flags", {})
    org_name     = fresh.get("organization_name") or fresh.get("full_name") or "Acordly User"
    sqs_results  = {form_id: generated[form_id].get("sqs", {})} if form_id in generated else {}

    ai_content = generate_ai_cover_narrative(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=[form_id], org_name=org_name, user=fresh)
    cover_pdf  = build_cover_page_pdf(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=[form_id], org_name=org_name, narrative=ai_content["narrative"], ai_block=ai_content["ai_block"], sqs_reasoning=ai_content.get("sqs_reasoning",""), user=fresh)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Acordly_Cover_Page.pdf", cover_pdf)
        zf.writestr(f"{form_id}_FILLED.pdf", pdf_bytes)
    zip_buf.seek(0)

    conn = get_db(); cur = conn.cursor()
    if sub == "free":
        cur.execute("UPDATE users SET downloads_used = downloads_used + 1 WHERE id = %s", (fresh["id"],))
    elif sub in ("essentials", "professional") and pkg_eval:
        cur.execute("UPDATE users SET packages_used = packages_used + 1 WHERE id = %s", (fresh["id"],))
        if pkg_eval["status"] == "overage":
            stripe_queued = create_overage_invoice_item(fresh, pkg_eval["overage_rate_cents"])
            if stripe_queued:
                cur.execute("UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced,0) + 1 WHERE id = %s", (fresh["id"],))
            else:
                cur.execute("UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + 1 WHERE id = %s", (fresh["id"],))
    conn.commit(); cur.close(); conn.close()

    write_audit_log(user=fresh, action="download", form_id=form_id, form_name=form_name,
                    session_id=session_id, ip_address=request.client.host if request.client else None)

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"]  = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")

    return Response(content=zip_buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={form_id}_Package.zip", **extra_headers})


@router.get("/api/download-all/{session_id}")
async def download_all(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    fresh = _refresh_user(current_user["id"])
    if not fresh:
        from fastapi import HTTPException
        raise HTTPException(401, "User not found")
    sub  = fresh.get("subscription_tier", "free") or "free"
    used = int(fresh.get("downloads_used", 0) or 0)

    if fresh.get("payment_status") == "suspended":
        return JSONResponse({"success": False, "payment_locked": True, "message": "Account suspended."}, status_code=403)
    if sub == "lite":
        return JSONResponse({"success": False, "message": "ACORD form downloads are not included in the Lite plan."}, status_code=403)
    if sub == "free" and used >= 3:
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Free limit reached."}, status_code=403)

    pkg_eval = None
    if sub in ("essentials", "professional"):
        pkg_eval = evaluate_package_limit(fresh)

    proc_session = get_processing_session(session_id)
    generated    = proc_session.get("generated_forms", {})
    if not generated:
        from fastapi import HTTPException
        raise HTTPException(400, "No forms generated yet")

    acord_pdfs = {}
    for fid in generated.keys():
        try:
            acord_pdfs[fid] = regenerate_pdf_for_form(proc_session, fid, force=True)
        except Exception as ex:
            logger.error(f"Skipping {fid}: {ex}")

    sqs_results = {fid: generated[fid].get("sqs", {}) for fid in generated}
    facts       = proc_session.get("facts", {})
    flags       = proc_session.get("flags", {})
    org_name    = fresh.get("organization_name") or fresh.get("full_name") or "Acordly User"

    ai_content = generate_ai_cover_narrative(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=list(generated.keys()), org_name=org_name, user=fresh)
    cover_pdf  = build_cover_page_pdf(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=list(generated.keys()), org_name=org_name, narrative=ai_content["narrative"], ai_block=ai_content["ai_block"], sqs_reasoning=ai_content.get("sqs_reasoning",""), user=fresh)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Acordly_Cover_Page.pdf", cover_pdf)
        for fid, pb in acord_pdfs.items():
            zf.writestr(f"{fid}_FILLED.pdf", pb)
    zip_buf.seek(0)

    conn = get_db(); cur = conn.cursor()
    if sub == "free":
        cur.execute("UPDATE users SET downloads_used = downloads_used + 1 WHERE id = %s", (fresh["id"],))
    elif sub in ("essentials", "professional") and pkg_eval:
        cur.execute("UPDATE users SET packages_used = packages_used + 1 WHERE id = %s", (fresh["id"],))
        if pkg_eval["status"] == "overage":
            stripe_queued = create_overage_invoice_item(fresh, pkg_eval["overage_rate_cents"])
            if stripe_queued:
                cur.execute("UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced,0) + 1 WHERE id = %s", (fresh["id"],))
            else:
                cur.execute("UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + 1 WHERE id = %s", (fresh["id"],))
    conn.commit(); cur.close(); conn.close()

    write_audit_log(user=fresh, action="download_zip", form_id=", ".join(generated.keys()),
                    form_name=f"ZIP Bundle ({len(generated)} forms + cover page)",
                    session_id=session_id, ip_address=request.client.host if request.client else None)

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"]  = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")

    return Response(content=zip_buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=ACORD_Package_Acordly.zip", **extra_headers})


@router.get("/api/lite/analyze/{session_id}")
async def lite_analyze(session_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("subscription_tier") != "lite":
        raise HTTPException(403, "This endpoint is for Lite plan users only.")
    proc_session = get_processing_session(session_id)
    facts      = proc_session.get("facts", {})
    flags      = proc_session.get("flags", {})
    hard_stops = proc_session.get("hard_stops", [])
    soft_stops = proc_session.get("soft_stops", [])
    tier2_score = proc_session.get("tier2_score", 50)
    sqs = calculate_sqs(
        facts=facts, flags=flags,
        mapped_data={}, form_schema={},
        selected_form_ids=[],
        hard_stops=hard_stops, soft_stops=soft_stops,
        tier2_score=tier2_score,
    )
    return JSONResponse({"success": True, "sqs": sqs, "hard_stops": hard_stops, "soft_stops": soft_stops, "flags": flags})


@router.get("/api/lite/cover-sheet/{session_id}")
async def lite_cover_sheet(session_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("subscription_tier") != "lite":
        raise HTTPException(403, "This endpoint is for Lite plan users only.")
    proc_session = get_processing_session(session_id)
    facts       = proc_session.get("facts", {})
    flags       = proc_session.get("flags", {})
    hard_stops  = proc_session.get("hard_stops", [])
    soft_stops  = proc_session.get("soft_stops", [])
    tier2_score = proc_session.get("tier2_score", 50)
    org_name    = current_user.get("organization_name") or current_user.get("full_name") or "Acordly User"

    # Use real post-generation SQS if forms were internally generated, else fall back to pre-gen
    generated_forms = proc_session.get("generated_forms", {})
    if generated_forms:
        sqs_list = [r["sqs"] for r in generated_forms.values() if r.get("sqs")]
        avg_score = int(sum(s.get("sqs_score", 0) for s in sqs_list) / max(len(sqs_list), 1)) if sqs_list else 0
        sqs = {**(sqs_list[0] if sqs_list else {}), "sqs_score": avg_score}
    else:
        sqs = calculate_sqs(
            facts=facts, flags=flags,
            mapped_data={}, form_schema={},
            selected_form_ids=[],
            hard_stops=hard_stops, soft_stops=soft_stops,
            tier2_score=tier2_score,
        )
    sqs_results = {"Pre-Submission Analysis": sqs}

    from services.cover_service import generate_lite_cover_narrative
    ai_content = generate_lite_cover_narrative(
        facts=facts, flags=flags, sqs=sqs,
        hard_stops=hard_stops, soft_stops=soft_stops,
        org_name=org_name, user=current_user,
    )
    cover_pdf = build_cover_page_pdf(
        facts=facts, flags=flags, sqs_results=sqs_results, form_ids=[],
        org_name=org_name, narrative=ai_content["narrative"],
        ai_block=ai_content["ai_block"],
        sqs_reasoning=ai_content.get("sqs_reasoning", ""),
        user=current_user,
        hard_stops=hard_stops, soft_stops=soft_stops,
    )
    return Response(content=cover_pdf, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=Acordly_SQS_Cover_Sheet.pdf"})