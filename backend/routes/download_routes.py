import hashlib
import io
import logging
import time
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from datetime import datetime, timezone

from config.database import get_pool
from repositories.session_repository import get_processing_session, upd_processing_session
from repositories.audit_repository import write_audit_log
from services.auth_service import get_current_user
from services.cover_service import generate_ai_cover_narrative, build_cover_page_pdf
from services.pdf_service import regenerate_pdf_for_form
from services.stripe_service import evaluate_package_limit, create_overage_invoice_item
from services.sqs_service import calculate_sqs
from services import s3_service

router = APIRouter(tags=["downloads"])
logger = logging.getLogger(__name__)

_COVER_CACHE: dict = {}

_DEDUP_WINDOW_SECONDS = 300

try:
    from utils.rate_limiter import _redis as _dl_redis
except Exception:
    _dl_redis = None

_dedup_seen: dict = {}


def _acquire_download_lock(user_id: str, session_id: str, form_ids_hash: str) -> bool:
    """Return True (and acquire lock) if this is a fresh download; False if duplicate."""
    key = f"dl_counted:{user_id}:{session_id}:{form_ids_hash}"
    now = time.time()

    if _dl_redis is not None:
        try:
            acquired = _dl_redis.set(key, "1", nx=True, ex=_DEDUP_WINDOW_SECONDS)
            return bool(acquired)
        except Exception as ex:
            logger.warning("download dedup Redis error, using in-process fallback: %s", ex)

    stale = [k for k, exp in list(_dedup_seen.items()) if exp <= now]
    for k in stale:
        del _dedup_seen[k]
    if key in _dedup_seen:
        return False
    _dedup_seen[key] = now + _DEDUP_WINDOW_SECONDS
    return True


def _cover_cache_key(facts: dict, form_ids: list, sqs_results: dict, flags: dict) -> str:
    applicant = facts.get("applicant_name")
    if isinstance(applicant, dict):
        applicant = applicant.get("value", "")
    scores    = [v.get("sqs_score", 0) for v in sqs_results.values() if isinstance(v, dict)]
    avg_score = round(sum(scores) / len(scores)) if scores else 0
    raw = (
        str(applicant or "")
        + str(sorted(form_ids))
        + str(avg_score)
        + str(sorted((k, str(v)) for k, v in flags.items()))
    )
    return hashlib.md5(raw.encode()).hexdigest()


# ASYNC-SAFE
async def _refresh_user(user_id: str) -> dict:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return dict(row) if row else None


# ASYNC-SAFE
@router.get("/api/download-pdf/{session_id}/{form_id}")
async def download_pdf(
    session_id: str,
    form_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    fresh = await _refresh_user(current_user["id"])
    if not fresh:
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
        pkg_eval = await evaluate_package_limit(fresh)

    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    generated      = proc_session.get("generated_forms", {})
    form_name      = generated.get(form_id, {}).get("form_name", form_id)
    user_signature = fresh.get("signature_data") or None
    pdf_bytes      = regenerate_pdf_for_form(proc_session, form_id, force=True, user_signature=user_signature)
    s3_service.upload_pdf(session_id, form_id, pdf_bytes)
    facts       = proc_session.get("facts", {})
    flags       = proc_session.get("flags", {})
    org_name    = fresh.get("organization_name") or fresh.get("full_name") or "Acordly User"
    sqs_results = {form_id: generated[form_id].get("sqs", {})} if form_id in generated else {}

    _ck = _cover_cache_key(facts, [form_id], sqs_results, flags)
    ai_content = _COVER_CACHE.get(_ck)
    if ai_content is None:
        ai_content = generate_ai_cover_narrative(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=[form_id], org_name=org_name, user=fresh)
        _COVER_CACHE[_ck] = ai_content
        logger.debug(f"cover narrative cached for key {_ck[:8]}")
    else:
        logger.debug(f"cover narrative cache hit {_ck[:8]}")
    cover_pdf = build_cover_page_pdf(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=[form_id], org_name=org_name, narrative=ai_content["narrative"], ai_block=ai_content["ai_block"], sqs_reasoning=ai_content.get("sqs_reasoning", ""), user=fresh)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Acordly_Cover_Page.pdf", cover_pdf)
        zf.writestr(f"{form_id}_FILLED.pdf", pdf_bytes)
    zip_buf.seek(0)

    _ids_hash = hashlib.md5(form_id.encode()).hexdigest()[:8]
    if _acquire_download_lock(fresh["id"], session_id, _ids_hash):
        async with get_pool().acquire() as conn:
            if sub == "free":
                await conn.execute(
                    "UPDATE users SET downloads_used = downloads_used + 1 WHERE id = $1", fresh["id"]
                )
            elif sub in ("essentials", "professional") and pkg_eval:
                await conn.execute(
                    "UPDATE users SET packages_used = packages_used + 1 WHERE id = $1", fresh["id"]
                )
                if pkg_eval["status"] == "overage":
                    stripe_queued = create_overage_invoice_item(fresh, pkg_eval["overage_rate_cents"])
                    if stripe_queued:
                        await conn.execute(
                            "UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced,0) + 1 WHERE id = $1",
                            fresh["id"],
                        )
                    else:
                        await conn.execute(
                            "UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + 1 WHERE id = $1",
                            fresh["id"],
                        )
    else:
        logger.info("download_pdf: duplicate download skipped for user=%s session=%s form=%s", fresh["id"], session_id, form_id)

    await write_audit_log(
        user=fresh, action="download", form_id=form_id, form_name=form_name,
        session_id=session_id, ip_address=request.client.host if request.client else None,
    )

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"]  = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")

    return Response(
        content=zip_buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={form_id}_Package.zip", **extra_headers},
    )


# ASYNC-SAFE
@router.get("/api/download-all/{session_id}")
async def download_all(
    session_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    fresh = await _refresh_user(current_user["id"])
    if not fresh:
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
        pkg_eval = await evaluate_package_limit(fresh)

    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    generated = proc_session.get("generated_forms", {})
    if not generated:
        raise HTTPException(400, "No forms generated yet")

    user_signature = fresh.get("signature_data") or None
    acord_pdfs = {}
    for fid in generated.keys():
        try:
            acord_pdfs[fid] = regenerate_pdf_for_form(proc_session, fid, force=True, user_signature=user_signature)
            s3_service.upload_pdf(session_id, fid, acord_pdfs[fid])
        except Exception as ex:
            logger.error(f"Skipping {fid}: {ex}")

    sqs_results = {fid: generated[fid].get("sqs", {}) for fid in generated}
    facts    = proc_session.get("facts", {})
    flags    = proc_session.get("flags", {})
    org_name = fresh.get("organization_name") or fresh.get("full_name") or "Acordly User"

    _ck = _cover_cache_key(facts, list(generated.keys()), sqs_results, flags)
    ai_content = _COVER_CACHE.get(_ck)
    if ai_content is None:
        ai_content = generate_ai_cover_narrative(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=list(generated.keys()), org_name=org_name, user=fresh)
        _COVER_CACHE[_ck] = ai_content
        logger.debug(f"cover narrative cached for key {_ck[:8]}")
    else:
        logger.debug(f"cover narrative cache hit {_ck[:8]}")
    cover_pdf = build_cover_page_pdf(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=list(generated.keys()), org_name=org_name, narrative=ai_content["narrative"], ai_block=ai_content["ai_block"], sqs_reasoning=ai_content.get("sqs_reasoning", ""), user=fresh)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Acordly_Cover_Page.pdf", cover_pdf)
        for fid, pb in acord_pdfs.items():
            zf.writestr(f"{fid}_FILLED.pdf", pb)
    zip_buf.seek(0)

    _ids_hash = hashlib.md5((",".join(sorted(generated.keys()))).encode()).hexdigest()[:8]
    if _acquire_download_lock(fresh["id"], session_id, _ids_hash):
        async with get_pool().acquire() as conn:
            if sub == "free":
                await conn.execute(
                    "UPDATE users SET downloads_used = downloads_used + 1 WHERE id = $1", fresh["id"]
                )
            elif sub in ("essentials", "professional") and pkg_eval:
                await conn.execute(
                    "UPDATE users SET packages_used = packages_used + 1 WHERE id = $1", fresh["id"]
                )
                if pkg_eval["status"] == "overage":
                    stripe_queued = create_overage_invoice_item(fresh, pkg_eval["overage_rate_cents"])
                    if stripe_queued:
                        await conn.execute(
                            "UPDATE users SET overage_packages_invoiced = COALESCE(overage_packages_invoiced,0) + 1 WHERE id = $1",
                            fresh["id"],
                        )
                    else:
                        await conn.execute(
                            "UPDATE users SET overage_packages_pending = COALESCE(overage_packages_pending,0) + 1 WHERE id = $1",
                            fresh["id"],
                        )
    else:
        logger.info("download_all: duplicate download skipped for user=%s session=%s", fresh["id"], session_id)

    await write_audit_log(
        user=fresh, action="download_zip",
        form_id=", ".join(generated.keys()),
        form_name=f"ZIP Bundle ({len(generated)} forms + cover page)",
        session_id=session_id, ip_address=request.client.host if request.client else None,
    )

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"]  = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")

    return Response(
        content=zip_buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ACORD_Package_Acordly.zip", **extra_headers},
    )


@router.get("/api/lite/analyze/{session_id}")
async def lite_analyze(session_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("subscription_tier") != "lite":
        raise HTTPException(403, "This endpoint is for Lite plan users only.")
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    facts       = proc_session.get("facts", {})
    flags       = proc_session.get("flags", {})
    hard_stops  = proc_session.get("hard_stops", [])
    soft_stops  = proc_session.get("soft_stops", [])
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
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    facts       = proc_session.get("facts", {})
    flags       = proc_session.get("flags", {})
    hard_stops  = proc_session.get("hard_stops", [])
    soft_stops  = proc_session.get("soft_stops", [])
    tier2_score = proc_session.get("tier2_score", 50)
    org_name    = current_user.get("organization_name") or current_user.get("full_name") or "Acordly User"

    clarity_result  = proc_session.get("clarity_result", {})
    generated_forms = proc_session.get("generated_forms", {})

    if clarity_result.get("sqs_combined"):
        sqs = clarity_result["sqs_combined"]
    elif generated_forms:
        sqs_list  = [r["sqs"] for r in generated_forms.values() if r.get("sqs")]
        avg_score = int(sum(s.get("sqs_score", 0) for s in sqs_list) / max(len(sqs_list), 1)) if sqs_list else 0
        sqs = {**(sqs_list[0] if sqs_list else {}), "sqs_score": avg_score}
    else:
        from services.sqs_service import calculate_sqs_from_facts
        selected_ids = proc_session.get("selected_form_ids") or ["ACORD_125"]
        sqs = calculate_sqs_from_facts(
            facts=facts, flags=flags,
            selected_form_ids=selected_ids,
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

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    return Response(
        content=cover_pdf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Acordly_SQS_Cover_Sheet.pdf"},
    )
