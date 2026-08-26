import asyncio
import hashlib
import io
import logging
import time
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from datetime import datetime, timezone

from config.database import get_pool
from config.settings import ACORD_LICENSE_VERSION
from repositories.session_repository import get_processing_session, upd_processing_session
from repositories.audit_repository import write_audit_log
from services.auth_service import get_current_user, is_acord_license_current
from services.cover_service import generate_ai_cover_narrative, build_cover_page_pdf
from services.pdf_service import regenerate_pdf_for_form, apply_draft_watermark
from services.field_qa import check_hard_block
from services.stripe_service import evaluate_package_limit, create_overage_invoice_item
from services.sqs_service import calculate_sqs
from services.audit_service import get_unresolved_recommendations
from utils.crypto import decrypt_field, decrypt_field_soft
from utils.rate_limiter import check_download_rate_limit
from utils.helpers import check_payment_access

router = APIRouter(tags=["downloads"])
logger = logging.getLogger(__name__)


# ASYNC-SAFE
def _enforce_integrity_gate(proc_session: dict) -> None:
    """Block scoring / Submission Brief generation while a Submission Integrity
    review is pending (Beta Report §4.1).

    Mirrors form_routes.enforce_integrity_gate and the worker.py guard. The lower
    tiers' facts-based scoring (/api/lite/analyze) and downloadable Submission
    Brief (/api/lite/cover-sheet) can both score straight from the extracted facts
    without any generated forms, so without this guard a package flagged as likely
    multi-insured could still produce a score or a brief - bypassing the review.
    Applies to EVERY paid tier (essentials / professional / business).
    """
    integrity = proc_session.get("integrity") or {}
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
def _enforce_completeness_gate(
    proc_session: dict,
    form_ids: list,
    draft: bool,
    override_reason: str,
) -> list:
    """Block a clean download when a stamped value is a leaked placeholder
    (e.g. "1st distinct value") or a form-specific completeness gate is unmet
    (currently ACORD 140 COPE fields) - Figure 35 client feedback: "This should
    be a hard stop... If a draft is allowed, watermark or label it clearly as
    incomplete."

    Recomputes fresh from the live generated-forms state on every call
    (services.field_qa.check_hard_block) rather than trusting any cached/DB
    snapshot - this is the one place that actually enforces the gate; the
    advisory "fieldqa_hardblock_..." rows written elsewhere only feed the
    frontend's preflight display. Deliberately narrow in scope (see
    field_qa._HARD_BLOCK_REASON_CODES): every OTHER existing advisory/soft
    finding (SQS hard stops, ordinary missing_required, low_confidence, field-
    mapping-integrity warnings, submission-integrity soft path) is completely
    unaffected and stays exactly as click-through-able as it always was.

    Returns the blocking items (possibly empty). Raises HTTP 409 unless the
    caller explicitly opted into a watermarked draft with a non-blank reason -
    the caller is then responsible for calling apply_draft_watermark() on the
    resulting PDF bytes and logging the override distinctly.
    """
    generated = proc_session.get("generated_forms") or {}
    facts = proc_session.get("facts") or {}
    blocking = check_hard_block(generated, form_ids=form_ids, merged_facts=facts)
    if not blocking:
        return []
    if draft and override_reason.strip():
        return blocking
    raise HTTPException(
        status_code=409,
        detail={
            "error": "download_incomplete",
            "message": (
                f"{len(blocking)} field(s) contain placeholder values or are missing "
                "data required for this section. Fix them, or add a note and use "
                "'Download Anyway' to get a clearly-watermarked incomplete copy."
            ),
            "blocking_items": [
                {
                    "form_id":     b.get("form_id"),
                    "field":       b.get("field"),
                    "field_label": b.get("field_label"),
                    "reason_code": b.get("reason_code"),
                    "message":     b.get("message"),
                }
                for b in blocking
            ],
        },
    )


# ASYNC-SAFE
@router.post("/api/acord/confirm-license")
async def confirm_acord_license(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    # Idempotent: if already confirmed under the CURRENT wording, skip the write
    # and return success. This prevents spurious 500s when the client retries
    # after a dropped connection. A confirmation recorded under an older
    # ACORD_LICENSE_VERSION does NOT short-circuit here — it falls through and
    # re-confirms under the current wording (forces re-acceptance after a
    # legal-text change).
    if is_acord_license_current(current_user):
        return {"success": True, "acord_license_confirmed": True, "acord_license_version": ACORD_LICENSE_VERSION}

    now = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE users SET acord_license_confirmed=1, acord_license_confirmed_at=$1, "
            "acord_license_version=$2 WHERE id=$3",
            now, ACORD_LICENSE_VERSION, current_user["id"],
        )
    await write_audit_log(
        user={**current_user, "acord_license_confirmed": 1},
        action="license_confirmed",
        ip_address=request.client.host if request.client else None,
        license_version=ACORD_LICENSE_VERSION,
    )
    return {"success": True, "acord_license_confirmed": True, "acord_license_version": ACORD_LICENSE_VERSION}

from cachetools import TTLCache
_COVER_CACHE = TTLCache(maxsize=256, ttl=3600)

_DEDUP_WINDOW_SECONDS = 300

try:
    from utils.rate_limiter import _redis as _dl_redis
except Exception:
    _dl_redis = None

_dedup_seen: dict = {}


async def _acquire_download_lock(user_id: str, session_id: str, form_ids_hash: str) -> bool:
    """Return True (and acquire lock) if this is a fresh download; False if duplicate."""
    key = f"dl_counted:{user_id}:{session_id}:{form_ids_hash}"
    now = time.time()

    if _dl_redis is not None:
        try:
            acquired = await _dl_redis.set(key, "1", nx=True, ex=_DEDUP_WINDOW_SECONDS)
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


def _compute_manifest(pdf_map: dict) -> tuple:
    """Return (manifest, package_checksum) for a {filename: bytes} map.

    manifest is a list of {filename, sha256} sorted by filename; package_checksum is
    a SHA-256 roll-up over the per-file digests (stable, reproducible, and independent
    of the surrounding zip, which cannot be hashed from inside the cover it contains).
    """
    manifest = [
        {"filename": fname, "sha256": hashlib.sha256(pdf_map[fname]).hexdigest()}
        for fname in sorted(pdf_map)
    ]
    rollup = hashlib.sha256("".join(m["sha256"] for m in manifest).encode()).hexdigest()
    return manifest, rollup


def _split_open_recs(open_recs: list) -> tuple:
    """Split open (unresolved) recommendations into hard-stop and soft-warning strings
    for the cover page's Red Flags & Warnings section."""
    hard, soft = [], []
    for r in open_recs or []:
        msg = (r.get("message") or "").strip()
        if not msg:
            continue
        imp = r.get("score_impact")
        if r.get("recommendation_type") == "hard_stop":
            hard.append(f"{msg} (-{imp} pts)" if imp else msg)
        else:
            soft.append(f"{msg} (up to +{imp} pts)" if imp else msg)
    return hard, soft


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
    include_cover: bool = Query(True),
    draft: bool = Query(False),
    override_reason: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    await check_download_rate_limit(current_user["id"])
    fresh = await _refresh_user(current_user["id"])
    if not fresh:
        raise HTTPException(401, "User not found")
    sub  = fresh.get("subscription_tier", "free") or "free"
    used = int(fresh.get("downloads_used", 0) or 0)

    check_payment_access(fresh.get("payment_status", "ok"), "form")
    if sub == "free" and used >= 3:
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Free limit reached."}, status_code=403)
    if sub == "essentials":
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Form downloads are not included in the Essentials tier."}, status_code=403)

    pkg_eval = None
    if sub in ("professional", "business"):
        pkg_eval = await evaluate_package_limit(fresh)

    proc_session = await get_processing_session(session_id, include_pdf=True)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    # Submission Integrity gate (Beta Report §4.1): never serve a generated form for
    # a package still pending multi-insured review. Explicit server-side enforcement,
    # not just reliance on "forms can't have been generated while paused".
    _enforce_integrity_gate(proc_session)
    # Completeness gate (Figure 35 client feedback): blocks a clean download when a
    # placeholder value or a required COPE-style field remains, unless the caller
    # explicitly asked for a watermarked draft with a typed reason.
    blocking_items = _enforce_completeness_gate(proc_session, [form_id], draft, override_reason)
    is_draft       = bool(blocking_items)
    _file_suffix   = "DRAFT" if is_draft else "FILLED"
    generated      = proc_session.get("generated_forms", {})
    form_name      = generated.get(form_id, {}).get("form_name", form_id)
    user_signature = decrypt_field_soft(fresh.get("signature_data")) or None
    facts       = proc_session.get("facts") or {}
    flags       = proc_session.get("flags", {})
    org_name    = fresh.get("organization_name") or fresh.get("full_name") or "Primble User"
    sqs_results = {form_id: generated[form_id].get("sqs", {})} if form_id in generated else {}

    # Substantively unresolved recommendations: never reviewed OR acknowledged via
    # "Download Anyway" but not actually fixed. Deliberately broader than the
    # pre-download gate's own query (which stops re-prompting once overridden) -
    # here we want the override to still show up in the audit trail.
    unresolved_recs = await get_unresolved_recommendations(session_id)

    _ck = _cover_cache_key(facts, [form_id], sqs_results, flags)
    _loop = asyncio.get_event_loop()

    if include_cover:
        # Parallelize PDF regeneration and AI narrative (independent of each other)
        _cached_ai = _COVER_CACHE.get(_ck)
        if _cached_ai is not None:
            logger.debug(f"cover narrative cache hit {_ck[:8]}")
            pdf_bytes, ai_content = await asyncio.gather(
                _loop.run_in_executor(None, regenerate_pdf_for_form, proc_session, form_id, True, user_signature),
                asyncio.sleep(0, result=_cached_ai),
            )
        else:
            pdf_bytes, ai_content = await asyncio.gather(
                _loop.run_in_executor(None, regenerate_pdf_for_form, proc_session, form_id, True, user_signature),
                generate_ai_cover_narrative(facts, flags, sqs_results, [form_id], org_name, fresh),
            )
            _COVER_CACHE[_ck] = ai_content
            logger.debug(f"cover narrative cached for key {_ck[:8]}")

        if is_draft:
            pdf_bytes = await _loop.run_in_executor(None, apply_draft_watermark, pdf_bytes)
        file_manifest, package_checksum = _compute_manifest({f"{form_id}_{_file_suffix}.pdf": pdf_bytes})
        hard_stops, soft_stops = _split_open_recs(unresolved_recs)
        cover_pdf = await _loop.run_in_executor(
            None, build_cover_page_pdf,
            facts, flags, sqs_results, [form_id], org_name,
            ai_content["narrative"], ai_content["ai_block"], ai_content.get("sqs_reasoning", ""), fresh,
            hard_stops, soft_stops, file_manifest, package_checksum,
        )

        def _build_zip():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("00_Primble_Cover_Page.pdf", cover_pdf)
                zf.writestr(f"{form_id}_{_file_suffix}.pdf", pdf_bytes)
            buf.seek(0)
            return buf
    else:
        # No cover — just the filled form PDF
        pdf_bytes = await _loop.run_in_executor(None, regenerate_pdf_for_form, proc_session, form_id, True, user_signature)
        if is_draft:
            pdf_bytes = await _loop.run_in_executor(None, apply_draft_watermark, pdf_bytes)
        file_manifest, package_checksum = _compute_manifest({f"{form_id}_{_file_suffix}.pdf": pdf_bytes})

        def _build_zip():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{form_id}_{_file_suffix}.pdf", pdf_bytes)
            buf.seek(0)
            return buf

    zip_buf = await _loop.run_in_executor(None, _build_zip)

    _ids_hash        = hashlib.md5(form_id.encode()).hexdigest()[:8]
    _already_counted = bool(proc_session.get("package_counted_at"))
    if not _already_counted and await _acquire_download_lock(fresh["id"], session_id, _ids_hash):
        _now_iso = datetime.now(timezone.utc).isoformat()
        await upd_processing_session(session_id, {"package_counted_at": _now_iso})
        async with get_pool().acquire() as conn:
            if sub == "free":
                await conn.execute(
                    "UPDATE users SET downloads_used = COALESCE(downloads_used, 0) + 1 WHERE id = $1", fresh["id"]
                )
            elif sub in ("professional", "business") and pkg_eval:
                await conn.execute(
                    "UPDATE users SET packages_used = COALESCE(packages_used, 0) + 1 WHERE id = $1",
                    fresh["id"],
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
        logger.info("download_pdf: already counted — skipping for user=%s session=%s form=%s", fresh["id"], session_id, form_id)

    _score_at_dl = (sqs_results.get(form_id) or {}).get("sqs_score")
    if is_draft:
        # Distinct action + payload from a normal "download": logs exactly what
        # was overridden and the producer's typed reason, never conflated with
        # the ordinary soft-warning "Download Anyway" audit trail above.
        await write_audit_log(
            user=fresh, action="download_draft", form_id=form_id, form_name=form_name,
            session_id=session_id, ip_address=request.client.host if request.client else None,
            sqs_score=_score_at_dl,
            # E&O 5.13: the draft payload used to REPLACE the open-items list
            # with the override alone - the one download where preserving what
            # was outstanding matters most recorded the least (2026-08-26).
            unresolved_issues={"override_reason": override_reason.strip(),
                               "blocking_items": blocking_items,
                               "open_recommendations": unresolved_recs},
            file_checksum=package_checksum,
        )
    else:
        await write_audit_log(
            user=fresh, action="download", form_id=form_id, form_name=form_name,
            session_id=session_id, ip_address=request.client.host if request.client else None,
            sqs_score=_score_at_dl, unresolved_issues=unresolved_recs, file_checksum=package_checksum,
        )

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    # E&O 5.12: "package is downloaded" is its own snapshot trigger - always
    # store the score the package shipped with.
    try:
        from services.audit_service import log_sqs_snapshot_if_changed
        await log_sqs_snapshot_if_changed(
            session_id, str(fresh.get("id") or "") or None,
            proc_session.get("package_sqs"), "package_downloaded")
    except Exception as _snap_ex:
        logger.warning(f"download_pdf: sqs snapshot skipped: {_snap_ex}")

    # Package activity log (best-effort).
    try:
        from services.activity_service import record_event, derive_package_label, EVENT_DOWNLOAD
        await record_event(
            fresh["id"], session_id, EVENT_DOWNLOAD,
            {"kind": "single", "form_id": form_id, "form_name": form_name},
            derive_package_label(proc_session.get("facts")),
        )
    except Exception as _act_ex:
        logger.warning(f"activity log (download) failed: {_act_ex}")

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"]  = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")
    if is_draft:
        extra_headers["X-Download-Draft"] = "true"

    _zip_name = f"{form_id}_Package_DRAFT.zip" if is_draft else f"{form_id}_Package.zip"
    return Response(
        content=zip_buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={_zip_name}", **extra_headers},
    )


# ASYNC-SAFE
@router.get("/api/download-all/{session_id}")
async def download_all(
    session_id: str,
    request: Request,
    draft: bool = Query(False),
    override_reason: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    await check_download_rate_limit(current_user["id"])
    fresh = await _refresh_user(current_user["id"])
    if not fresh:
        raise HTTPException(401, "User not found")
    sub  = fresh.get("subscription_tier", "free") or "free"
    used = int(fresh.get("downloads_used", 0) or 0)

    check_payment_access(fresh.get("payment_status", "ok"), "form")
    if sub == "free" and used >= 3:
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Free limit reached."}, status_code=403)
    if sub == "essentials":
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Form downloads are not included in the Essentials tier."}, status_code=403)

    pkg_eval = None
    if sub in ("professional", "business"):
        pkg_eval = await evaluate_package_limit(fresh)

    proc_session = await get_processing_session(session_id, include_pdf=True)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    # Submission Integrity gate (Beta Report §4.1): never serve the package bundle
    # for a flagged, unresolved multi-insured submission.
    _enforce_integrity_gate(proc_session)
    generated = proc_session.get("generated_forms", {})
    if not generated:
        raise HTTPException(400, "No forms generated yet")
    # Completeness gate (Figure 35 client feedback): blocks a clean package download
    # when any form has a placeholder value or an unmet required COPE-style field,
    # unless the caller explicitly asked for a watermarked draft with a typed reason.
    blocking_items = _enforce_completeness_gate(proc_session, list(generated.keys()), draft, override_reason)
    is_draft       = bool(blocking_items)
    _file_suffix   = "DRAFT" if is_draft else "FILLED"

    user_signature = decrypt_field_soft(fresh.get("signature_data")) or None
    acord_pdfs = {}
    for fid in generated.keys():
        try:
            pb = regenerate_pdf_for_form(proc_session, fid, force=True, user_signature=user_signature)
            acord_pdfs[fid] = apply_draft_watermark(pb) if is_draft else pb
        except Exception as ex:
            logger.error(f"Skipping {fid}: {ex}")

    sqs_results = {fid: generated[fid].get("sqs", {}) for fid in generated}
    facts    = proc_session.get("facts") or {}
    flags    = proc_session.get("flags", {})
    org_name = fresh.get("organization_name") or fresh.get("full_name") or "Primble User"

    # Substantively unresolved recommendations (never reviewed OR overridden via
    # "Download Anyway" without a fix) + per-file integrity manifest, for the cover
    # and the download audit record.
    unresolved_recs = await get_unresolved_recommendations(session_id)
    hard_stops, soft_stops = _split_open_recs(unresolved_recs)
    file_manifest, package_checksum = _compute_manifest(
        {f"{fid}_{_file_suffix}.pdf": pb for fid, pb in acord_pdfs.items()}
    )

    _ck = _cover_cache_key(facts, list(generated.keys()), sqs_results, flags)
    ai_content = _COVER_CACHE.get(_ck)
    if ai_content is None:
        # Pass the submission's OWN score so the cover page states the same
        # number the app shows. Without it this narrative averaged the per-form
        # scores, which disagreed with the package score everywhere else.
        ai_content = await generate_ai_cover_narrative(
            facts=facts, flags=flags, sqs_results=sqs_results,
            form_ids=list(generated.keys()), org_name=org_name, user=fresh,
            package_score=(proc_session.get("package_sqs") or {}).get("package_sqs_score"),
        )
        _COVER_CACHE[_ck] = ai_content
        logger.debug(f"cover narrative cached for key {_ck[:8]}")
    else:
        logger.debug(f"cover narrative cache hit {_ck[:8]}")
    cover_pdf = build_cover_page_pdf(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=list(generated.keys()), org_name=org_name, narrative=ai_content["narrative"], ai_block=ai_content["ai_block"], sqs_reasoning=ai_content.get("sqs_reasoning", ""), user=fresh, hard_stops=hard_stops, soft_stops=soft_stops, file_manifest=file_manifest, package_checksum=package_checksum)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Primble_Cover_Page.pdf", cover_pdf)
        for fid, pb in acord_pdfs.items():
            zf.writestr(f"{fid}_{_file_suffix}.pdf", pb)
    zip_buf.seek(0)

    _ids_hash        = hashlib.md5((",".join(sorted(generated.keys()))).encode()).hexdigest()[:8]
    _already_counted = bool(proc_session.get("package_counted_at"))
    if not _already_counted and await _acquire_download_lock(fresh["id"], session_id, _ids_hash):
        _now_iso = datetime.now(timezone.utc).isoformat()
        await upd_processing_session(session_id, {"package_counted_at": _now_iso})
        async with get_pool().acquire() as conn:
            if sub == "free":
                await conn.execute(
                    "UPDATE users SET downloads_used = COALESCE(downloads_used, 0) + 1 WHERE id = $1", fresh["id"]
                )
            elif sub in ("professional", "business") and pkg_eval:
                await conn.execute(
                    "UPDATE users SET packages_used = COALESCE(packages_used, 0) + 1 WHERE id = $1",
                    fresh["id"],
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
        logger.info("download_all: already counted — skipping for user=%s session=%s", fresh["id"], session_id)

    _scores = [(v or {}).get("sqs_score") for v in sqs_results.values()]
    _scores = [s for s in _scores if s is not None]
    _avg_score = round(sum(_scores) / len(_scores), 1) if _scores else None
    if is_draft:
        # Distinct action + payload from a normal "download_zip": logs exactly what
        # was overridden and the producer's typed reason, never conflated with the
        # ordinary soft-warning "Download Anyway" audit trail below.
        await write_audit_log(
            user=fresh, action="download_zip_draft",
            form_id=", ".join(generated.keys()),
            form_name=f"ZIP Bundle DRAFT ({len(generated)} forms + cover page)",
            session_id=session_id, ip_address=request.client.host if request.client else None,
            sqs_score=_avg_score,
            # E&O 5.13: keep the open-items list on the draft record too - the
            # override payload used to replace it (2026-08-26).
            unresolved_issues={"override_reason": override_reason.strip(),
                               "blocking_items": blocking_items,
                               "open_recommendations": unresolved_recs},
            file_checksum=package_checksum,
        )
    else:
        await write_audit_log(
            user=fresh, action="download_zip",
            form_id=", ".join(generated.keys()),
            form_name=f"ZIP Bundle ({len(generated)} forms + cover page)",
            session_id=session_id, ip_address=request.client.host if request.client else None,
            sqs_score=_avg_score, unresolved_issues=unresolved_recs, file_checksum=package_checksum,
        )

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    # E&O 5.12: "package is downloaded" is its own snapshot trigger.
    try:
        from services.audit_service import log_sqs_snapshot_if_changed
        await log_sqs_snapshot_if_changed(
            session_id, str(fresh.get("id") or "") or None,
            proc_session.get("package_sqs"), "package_downloaded")
    except Exception as _snap_ex:
        logger.warning(f"download_all: sqs snapshot skipped: {_snap_ex}")

    # Package activity log (best-effort).
    try:
        from services.activity_service import record_event, derive_package_label, EVENT_DOWNLOAD
        await record_event(
            fresh["id"], session_id, EVENT_DOWNLOAD,
            {"kind": "all", "form_count": len(generated)},
            derive_package_label(proc_session.get("facts")),
        )
    except Exception as _act_ex:
        logger.warning(f"activity log (download_all) failed: {_act_ex}")

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"]  = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")
    if is_draft:
        extra_headers["X-Download-Draft"] = "true"

    _zip_name = "ACORD_Package_Primble_DRAFT.zip" if is_draft else "ACORD_Package_Primble.zip"
    return Response(
        content=zip_buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={_zip_name}", **extra_headers},
    )


@router.get("/api/lite/analyze/{session_id}")
async def lite_analyze(session_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("subscription_tier") == "free":
        raise HTTPException(403, "Upgrade required to access submission scoring.")
    check_payment_access(current_user.get("payment_status", "ok"), "form")
    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    # Submission Integrity gate (Beta Report §4.1): do not score a package still
    # pending multi-insured review (this path computes SQS straight from facts).
    _enforce_integrity_gate(proc_session)
    facts       = proc_session.get("facts") or {}
    flags       = proc_session.get("flags", {})
    hard_stops  = proc_session.get("hard_stops", [])
    soft_stops  = proc_session.get("soft_stops", [])
    tier2_score = proc_session.get("tier2_score", 50)

    # Use session recommendations for form-aware scoring.
    # calculate_sqs_from_facts uses FORM_FIELD_INVENTORY (no LLM, no PDF generation)
    # so this returns in milliseconds.  Falls back to ACORD_125 if no recs exist.
    from services.sqs_service import calculate_sqs_from_facts
    recs             = proc_session.get("recommendations", [])
    selected_ids     = [r["form_id"] for r in recs] if recs else ["ACORD_125"]
    primary_form_id  = selected_ids[0]

    sqs = calculate_sqs_from_facts(
        facts=facts, flags=flags,
        selected_form_ids=selected_ids,
        hard_stops=hard_stops, soft_stops=soft_stops,
        tier2_score=tier2_score,
        form_id=primary_form_id,
        session_data=proc_session,
    )
    return JSONResponse({"success": True, "sqs": sqs, "hard_stops": hard_stops, "soft_stops": soft_stops, "flags": flags})


@router.get("/api/lite/cover-sheet/{session_id}")
async def lite_cover_sheet(session_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("subscription_tier") == "free":
        raise HTTPException(403, "Upgrade required to access cover sheet generation.")
    check_payment_access(current_user.get("payment_status", "ok"), "form")

    fresh = await _refresh_user(current_user["id"])
    if not fresh:
        raise HTTPException(401, "User not found")
    sub = fresh.get("subscription_tier", "free") or "free"

    proc_session = await get_processing_session(session_id)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    # Submission Integrity gate (Beta Report §4.1): do not score or brief a package
    # still pending multi-insured review (the cover sheet is the lower tiers'
    # downloadable Submission Brief and can score straight from facts below).
    _enforce_integrity_gate(proc_session)
    facts       = proc_session.get("facts") or {}
    flags       = proc_session.get("flags", {})
    hard_stops  = proc_session.get("hard_stops", [])
    soft_stops  = proc_session.get("soft_stops", [])
    tier2_score = proc_session.get("tier2_score", 50)
    org_name    = fresh.get("organization_name") or fresh.get("full_name") or "Primble User"

    clarity_result  = proc_session.get("clarity_result", {})
    generated_forms = proc_session.get("generated_forms", {})

    # The submission's OWN score comes first. This branch used to average the
    # per-form scores and paste that average over the FIRST form's tier, grade
    # and breakdown - so the number and the explanation beside it described
    # different things, and neither matched the score shown in the app
    # (2026-08-16 audit). The average survives only for a legacy session that
    # has generated forms but no stored package score.
    _pkg = proc_session.get("package_sqs") or {}
    if clarity_result.get("sqs_combined"):
        sqs = clarity_result["sqs_combined"]
    elif _pkg.get("package_sqs_score") is not None:
        _first = next((r["sqs"] for r in generated_forms.values() if r.get("sqs")), {})
        sqs = {
            **_first,
            "sqs_score":     _pkg["package_sqs_score"],
            "raw_sqs_score": _pkg.get("raw_sqs_score"),
            "cap_applied":   _pkg.get("cap_applied"),
            "cap_reason":    _pkg.get("cap_reason"),
            "breakdown":     _pkg.get("pillars", _first.get("breakdown", {})),
            "tier":          _pkg.get("tier", _first.get("tier")),
            "routing_decision": _pkg.get("routing_decision", _first.get("routing_decision")),
        }
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
            session_data=proc_session,
        )
    sqs_results = {"Pre-Submission Analysis": sqs}

    # Same "still unresolved" definition used on the real ACORD-package cover, so an
    # Essentials-tier producer sees the same open items whether they get a Lite
    # cover sheet or a full package.
    unresolved_recs = await get_unresolved_recommendations(session_id)

    from services.cover_service import generate_lite_cover_narrative
    ai_content = await generate_lite_cover_narrative(
        facts=facts, flags=flags, sqs=sqs,
        hard_stops=hard_stops, soft_stops=soft_stops,
        org_name=org_name, user=fresh,
    )
    cover_pdf = build_cover_page_pdf(
        facts=facts, flags=flags, sqs_results=sqs_results, form_ids=[],
        org_name=org_name, narrative=ai_content["narrative"],
        ai_block=ai_content["ai_block"],
        sqs_reasoning=ai_content.get("sqs_reasoning", ""),
        user=fresh,
        hard_stops=hard_stops, soft_stops=soft_stops,
    )

    # The cover sheet IS the delivered file for this tier - there is no separate
    # filled-form PDF to hash, and it cannot contain a hash of its own final bytes
    # (embedding the digest would change the digest). So this checksum is computed
    # over the finished PDF and recorded only in the audit DB row below, not printed
    # on the page itself - it still lets us prove exactly which bytes were delivered.
    cover_checksum = hashlib.sha256(cover_pdf).hexdigest()

    # Essentials billing: cover sheet is the downloadable artifact for this tier.
    # Count once per session (permanent flag), with rapid-double-click guard on top.
    pkg_eval = None
    if sub == "essentials":
        _already_counted = bool(proc_session.get("package_counted_at"))
        if not _already_counted:
            pkg_eval = await evaluate_package_limit(fresh)
            _ids_hash = hashlib.md5(b"cover").hexdigest()[:8]
            if await _acquire_download_lock(fresh["id"], session_id, _ids_hash):
                _now_iso = datetime.now(timezone.utc).isoformat()
                await upd_processing_session(session_id, {"package_counted_at": _now_iso})
                async with get_pool().acquire() as conn:
                    await conn.execute(
                        "UPDATE users SET packages_used = COALESCE(packages_used, 0) + 1 WHERE id = $1",
                        fresh["id"],
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
            logger.info("lite_cover_sheet: already counted — skipping for user=%s session=%s", fresh["id"], session_id)

    await write_audit_log(
        user=fresh, action="download_lite_cover", form_id=None,
        form_name="Pre-Submission SQS Analysis (Lite)",
        session_id=session_id, ip_address=request.client.host if request.client else None,
        sqs_score=sqs.get("sqs_score"), unresolved_issues=unresolved_recs,
        file_checksum=cover_checksum,
    )

    await upd_processing_session(session_id, {
        "last_downloaded_at": datetime.now(timezone.utc).isoformat()
    })

    extra_headers = {"Cache-Control": "no-cache"}
    if pkg_eval:
        extra_headers["X-Package-Status"]  = pkg_eval["status"]
        extra_headers["X-Package-Message"] = pkg_eval.get("message", "")

    return Response(
        content=cover_pdf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Primble_SQS_Cover_Sheet.pdf", **extra_headers},
    )
