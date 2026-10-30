import asyncio
import hashlib
import io
import logging
import time
import zipfile
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from datetime import datetime, timezone
from typing import Optional

from config.database import get_pool
from config.settings import ACORD_LICENSE_VERSION, FREE_PACKAGE_LIMIT
from repositories.session_repository import get_processing_session, upd_processing_session
from repositories.audit_repository import write_audit_log
from services.auth_service import get_current_user, is_acord_license_current
from services.cover_service import generate_ai_cover_narrative, build_cover_page_pdf
from services.pdf_service import apply_draft_watermark
# A signed form downloads with the producer's signature on the producer's boxes
# only, never the applicant's line (1 Oct 2026).
from services.signature_boxes import regenerate_pdf_for_form as _regenerate_for_form


def regenerate_pdf_for_form(proc_session, form_id, force=False, user_signature=None):
    """A downloaded form: the rendered PDF plus the encrypted Primble record
    (`acord_intake.primble_record`, 27 Oct 2026) - attached HERE, where a PDF
    leaves the system, never in the render / cache door (its bytes stay stable
    for the cache, the editor and signing)."""
    pdf_bytes = _regenerate_for_form(proc_session, form_id, force, user_signature)
    try:
        from services.acord_intake.primble_record import attach
        return attach(pdf_bytes, proc_session, form_id)
    except Exception:                                          # noqa: BLE001
        return pdf_bytes


def _cover_with_record(cover_pdf, proc_session):
    """The SQS summary (cover page) with the package's encrypted Primble record
    (27 Oct 2026, owner): the same answers, tables and Policies-table edits the
    forms carry, so the cover re-uploaded beside the declarations alone
    restores them. Hidden in the PDF's document information; nothing is printed.
    Unchanged on any failure."""
    try:
        from services.acord_intake.primble_record import SUMMARY_FORM, attach
        return attach(cover_pdf, proc_session, SUMMARY_FORM)
    except Exception:                                          # noqa: BLE001
        return cover_pdf
from services.field_qa import check_hard_block
# Download file names: a form's second copy is "ACORD_131_Excess" (7 Oct 2026).
from services.form_instances import file_stem
from services.stripe_service import evaluate_package_limit, create_overage_invoice_item
from services.sqs_service import calculate_sqs, current_package_sqs, tier_for_score
from services.audit_service import current_unresolved_recommendations
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


def _cover_cache_key(facts: dict, form_ids: list, sqs_results: dict, flags: dict,
                     package_score=None, open_hard_stops=None) -> str:
    applicant = facts.get("applicant_name")
    if isinstance(applicant, dict):
        applicant = applicant.get("value", "")
    scores    = [v.get("sqs_score", 0) for v in sqs_results.values() if isinstance(v, dict)]
    avg_score = round(sum(scores) / len(scores)) if scores else 0
    raw = (
        str(applicant or "")
        + str(sorted(form_ids))
        + str(avg_score)
        # The package score is part of what the paragraph says (1 Oct 2026): a
        # cached paragraph must never quote an older package score.
        + f"|pkg={package_score}"
        # ...nor an older readiness (19 Oct 2026): the tier the paragraph states
        # reads the open hard stops too (`cover_service.grade_and_tier`).
        + (f"|open={open_hard_stops}" if open_hard_stops is not None else "")
        + str(sorted((k, str(v)) for k, v in flags.items()))
    )
    return hashlib.md5(raw.encode()).hexdigest()


def _package_score_now(proc_session: dict, session_id: str, user_id) -> dict:
    """The package SQS exactly as the SQS panel shows it (1 Oct 2026, owner: the
    cover's score must be exactly the SQS section's). The one door
    (`sqs_service.current_package_sqs`); {} when there is none."""
    try:
        return current_package_sqs(proc_session, session_id, str(user_id)) or {}
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("cover: package score unavailable for %s: %s", session_id, exc)
        return {}


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


def _unscored_card_ids(generated_forms: dict) -> set:
    """The cards the forms show that are worth zero points by their own
    declaration (`unscored`) - asks such as the landlord "kept for certificates"
    (Orbin G2). Read off the live form scores: a stored row does not carry the
    flag, and a stored 0 is no proof (a scored card whose pillar is full stores 0
    too)."""
    out = set()
    for fr in (generated_forms or {}).values():
        for rec in (((fr or {}).get("sqs") or {}).get("recommendations") or []):
            if isinstance(rec, dict) and rec.get("unscored") and rec.get("rec_id"):
                out.add(rec["rec_id"])
    return out


def _live_card_points(generated_forms: dict) -> dict:
    """{rec_id: (points, is_exact)} - the number and hedge each card shows on
    the panel NOW (one number per card since 1 Oct 2026, item 19). The stored
    row keeps the number but not whether it is exact, so the cover printed
    "up to +7 pts" beside the panel's "+7 pts" (owner's retest, 1 Oct)."""
    out: dict = {}
    for fr in (generated_forms or {}).values():
        for rec in (((fr or {}).get("sqs") or {}).get("recommendations") or []):
            if not isinstance(rec, dict) or not rec.get("rec_id") or rec["rec_id"] in out:
                continue
            pts = rec.get("score_impact")
            if isinstance(pts, (int, float)) and not isinstance(pts, bool):
                out[rec["rec_id"]] = (int(round(pts)), rec.get("impact_is_exact") is True)
    return out


def _split_open_recs(open_recs: list, unscored_ids=frozenset(), live_points=None,
                     package_sqs: Optional[dict] = None) -> tuple:
    """Split open (unresolved) recommendations into hard-stop and soft-warning strings
    for the cover page's Red Flags & Warnings section.

    The cover is the underwriter's page: real gaps only (owner, 30 Sep 2026). A
    producer to-do row and a zero-point card (`unscored_ids`) stay in the
    producer's review and the E&O record, never here. `live_points`
    (`_live_card_points`) gives each card the number and hedge the panel shows;
    a card no form shows any more keeps its stored number, hedged.

    `package_sqs`: the score the cover prints. Its open hard stops are the
    CRITICAL list (`_critical_lines`), so the list names every hard stop the
    score holds - not only the cards typed hard stop (22 Oct 2026)."""
    hard_rows, soft = [], []
    try:
        from services.needs_attention import is_producer_todo_row
    except Exception:                                      # noqa: BLE001
        is_producer_todo_row = lambda _rid: False          # noqa: E731
    for r in open_recs or []:
        msg = (r.get("message") or "").strip()
        if not msg:
            continue
        # The cover page is the underwriter's: real gaps only. "AI held back"
        # and "Please verify" are the producer's to-dos (owner, 30 Sep 2026).
        if is_producer_todo_row(r.get("rec_id")):
            continue
        if r.get("rec_id") in unscored_ids and r.get("recommendation_type") != "hard_stop":
            continue
        imp = r.get("score_impact")
        exact = False
        if live_points and r.get("rec_id") in live_points:
            imp, exact = live_points[r["rec_id"]]
        if r.get("recommendation_type") == "hard_stop":
            hard_rows.append((r, msg, imp))
        else:
            soft.append((f"{msg} (+{imp} pts)" if exact else f"{msg} (up to +{imp} pts)")
                        if imp else msg)
    # The safety net's items (27 Oct 2026, `sqs_service.charge_only_answerable`):
    # not charged because the page could not ask them - the underwriter still
    # sees each one.
    for item in (package_sqs or {}).get("not_scored") or []:
        label = str((item or {}).get("label") or "").strip() if isinstance(item, dict) else ""
        line = f"Not scored - could not be asked on screen: {label}"
        if label and line not in soft:
            soft.append(line)
    return _critical_lines(hard_rows, package_sqs), soft


def _hard_line(msg: str, imp) -> str:
    return f"{msg} (-{imp} pts)" if imp else msg


def _critical_lines(hard_rows: list, package_sqs: Optional[dict]) -> list:
    """The cover's "CRITICAL - Hard Stops" (22 Oct 2026): every open hard stop
    the package score holds, read off the score's own door - its readiness
    fields (`sqs_service.readiness_fields`: `ready_blocker_items`, one per
    conflict, each with its fix) - then each card typed hard stop whose fix no
    listed stop's fix covers. The cards alone missed every hard stop that is
    not a card: documents naming different companies (name / FEIN) and the
    monopolistic state with a private carrier.

    One problem, one line (`needs_attention.download_review_rows`' rule): a
    card whose fix a stop's fix covers is that stop's line, and the line keeps
    the card's points. A score stored before 19 Oct carries no readiness
    fields: the cards, exactly as before."""
    pkg = package_sqs if isinstance(package_sqs, dict) else {}
    items = pkg.get("ready_blocker_items")
    if not isinstance(items, list):
        blockers = pkg.get("ready_blockers")
        items = ([{"message": m} for m in blockers if m]
                 if isinstance(blockers, list) else None)
    if items is None:
        return [_hard_line(msg, imp) for _r, msg, imp in hard_rows]
    try:
        from services.needs_attention import card_fix_keys, issue_fix_keys
    except Exception:                                      # noqa: BLE001
        card_fix_keys = issue_fix_keys = lambda _x: set()  # noqa: E731
    lines: list = []
    for it in items:
        msg = str((it or {}).get("message") or "").strip() if isinstance(it, dict) else ""
        if msg and msg not in [ln["message"] for ln in lines]:
            lines.append({"message": msg, "points": None, "keys": issue_fix_keys(it)})
    cards: list = []
    for r, msg, imp in hard_rows:
        keys = card_fix_keys(r)
        owner = next((ln for ln in lines if (keys & ln["keys"]) or ln["message"] == msg), None)
        if owner is None:
            cards.append(_hard_line(msg, imp))
            continue
        if isinstance(imp, (int, float)) and not isinstance(imp, bool) \
                and imp > (owner["points"] or 0):
            owner["points"] = imp
    return [_hard_line(ln["message"], ln["points"]) for ln in lines] + cards


# ASYNC-SAFE
async def _refresh_user(user_id: str) -> dict:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return dict(row) if row else None


# ASYNC-SAFE
def _free_limit_blocks(sub: str, used: int, proc_session: dict) -> bool:
    """True when a free account has spent its allowance on OTHER packages.

    A free package is counted when its forms are GENERATED (usage_service), so by
    the time the user downloads it `downloads_used` already includes it. Gating on
    the counter alone refused the very package the credit paid for - at a limit of
    1, the only one. A session stamped `package_counted_at` is already paid for and
    always downloads; an uncounted session would spend a new credit, so it is
    refused once the allowance is gone.
    """
    if sub != "free" or used < FREE_PACKAGE_LIMIT:
        return False
    return not proc_session.get("package_counted_at")


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
    if sub == "essentials":
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Form downloads are not included in the Essentials tier."}, status_code=403)

    pkg_eval = None
    if sub in ("professional", "business"):
        pkg_eval = await evaluate_package_limit(fresh)

    proc_session = await get_processing_session(session_id, include_pdf=True)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    if _free_limit_blocks(sub, used, proc_session):
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Free limit reached."}, status_code=403)
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
    _pkg_now = _package_score_now(proc_session, session_id, fresh["id"])
    _pkg_score = _pkg_now.get("package_sqs_score")

    # Substantively unresolved recommendations: never reviewed OR acknowledged via
    # "Download Anyway" but not actually fixed. Deliberately broader than the
    # pre-download gate's own query (which stops re-prompting once overridden) -
    # here we want the override to still show up in the audit trail.
    unresolved_recs = await current_unresolved_recommendations(session_id, proc_session)

    _ck = _cover_cache_key(facts, [form_id], sqs_results, flags, _pkg_score,
                           open_hard_stops=_pkg_now.get("open_hard_stops"))
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
                generate_ai_cover_narrative(facts, flags, sqs_results, [form_id], org_name, fresh,
                                            package_score=_pkg_score,
                                            package_routing=_pkg_now.get("routing_decision"),
                                            package_open_hard_stops=_pkg_now.get("open_hard_stops") or 0),
            )
            _COVER_CACHE[_ck] = ai_content
            logger.debug(f"cover narrative cached for key {_ck[:8]}")

        if is_draft:
            pdf_bytes = await _loop.run_in_executor(None, apply_draft_watermark, pdf_bytes)
        file_manifest, package_checksum = _compute_manifest({f"{file_stem(form_id)}_{_file_suffix}.pdf": pdf_bytes})
        hard_stops, soft_stops = _split_open_recs(
            unresolved_recs, _unscored_card_ids(proc_session.get("generated_forms")),
            _live_card_points(proc_session.get("generated_forms")), package_sqs=_pkg_now)
        cover_pdf = await _loop.run_in_executor(
            None, lambda: build_cover_page_pdf(
                facts, flags, sqs_results, [form_id], org_name,
                ai_content["narrative"], ai_content["ai_block"], ai_content.get("sqs_reasoning", ""), fresh,
                hard_stops, soft_stops, file_manifest, package_checksum,
                package_sqs=_pkg_now),
        )
        cover_pdf = _cover_with_record(cover_pdf, proc_session)

        def _build_zip():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("00_Primble_Cover_Page.pdf", cover_pdf)
                zf.writestr(f"{file_stem(form_id)}_{_file_suffix}.pdf", pdf_bytes)
            buf.seek(0)
            return buf
    else:
        # No cover — just the filled form PDF
        pdf_bytes = await _loop.run_in_executor(None, regenerate_pdf_for_form, proc_session, form_id, True, user_signature)
        if is_draft:
            pdf_bytes = await _loop.run_in_executor(None, apply_draft_watermark, pdf_bytes)
        file_manifest, package_checksum = _compute_manifest({f"{file_stem(form_id)}_{_file_suffix}.pdf": pdf_bytes})

        def _build_zip():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{file_stem(form_id)}_{_file_suffix}.pdf", pdf_bytes)
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

    # The score the producer saw (the post-download panel prints the PACKAGE
    # score), so the E&O record states the same number; the form's own score
    # only for a session with no package score.
    _score_at_dl = (_pkg_score if _pkg_score is not None
                    else (sqs_results.get(form_id) or {}).get("sqs_score"))
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

    _zip_name = (f"{file_stem(form_id)}_Package_DRAFT.zip" if is_draft
                 else f"{file_stem(form_id)}_Package.zip")
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
    if sub == "essentials":
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Form downloads are not included in the Essentials tier."}, status_code=403)

    pkg_eval = None
    if sub in ("professional", "business"):
        pkg_eval = await evaluate_package_limit(fresh)

    proc_session = await get_processing_session(session_id, include_pdf=True)
    if proc_session.get("user_id") != current_user["id"]:
        raise HTTPException(403, "Access denied")
    if _free_limit_blocks(sub, used, proc_session):
        return JSONResponse({"success": False, "upgrade_required": True, "message": "Free limit reached."}, status_code=403)
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
    unresolved_recs = await current_unresolved_recommendations(session_id, proc_session)
    # The package score exactly as the SQS panel shows it (1 Oct 2026) - read
    # first: its open hard stops are the cover's CRITICAL list (22 Oct 2026).
    _pkg_now = _package_score_now(proc_session, session_id, fresh["id"])
    _pkg_score = _pkg_now.get("package_sqs_score")
    hard_stops, soft_stops = _split_open_recs(
        unresolved_recs, _unscored_card_ids(proc_session.get("generated_forms")),
        _live_card_points(proc_session.get("generated_forms")), package_sqs=_pkg_now)
    file_manifest, package_checksum = _compute_manifest(
        {f"{file_stem(fid)}_{_file_suffix}.pdf": pb for fid, pb in acord_pdfs.items()}
    )
    _ck = _cover_cache_key(facts, list(generated.keys()), sqs_results, flags, _pkg_score,
                           open_hard_stops=_pkg_now.get("open_hard_stops"))
    ai_content = _COVER_CACHE.get(_ck)
    if ai_content is None:
        # Pass the submission's OWN score so the cover page states the same
        # number the app shows. Without it this narrative averaged the per-form
        # scores, which disagreed with the package score everywhere else.
        ai_content = await generate_ai_cover_narrative(
            facts=facts, flags=flags, sqs_results=sqs_results,
            form_ids=list(generated.keys()), org_name=org_name, user=fresh,
            package_score=_pkg_score, package_routing=_pkg_now.get("routing_decision"),
            package_open_hard_stops=_pkg_now.get("open_hard_stops") or 0,
        )
        _COVER_CACHE[_ck] = ai_content
        logger.debug(f"cover narrative cached for key {_ck[:8]}")
    else:
        logger.debug(f"cover narrative cache hit {_ck[:8]}")
    cover_pdf = build_cover_page_pdf(facts=facts, flags=flags, sqs_results=sqs_results, form_ids=list(generated.keys()), org_name=org_name, narrative=ai_content["narrative"], ai_block=ai_content["ai_block"], sqs_reasoning=ai_content.get("sqs_reasoning", ""), user=fresh, hard_stops=hard_stops, soft_stops=soft_stops, file_manifest=file_manifest, package_checksum=package_checksum, package_sqs=_pkg_now)
    cover_pdf = _cover_with_record(cover_pdf, proc_session)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_Primble_Cover_Page.pdf", cover_pdf)
        for fid, pb in acord_pdfs.items():
            zf.writestr(f"{file_stem(fid)}_{_file_suffix}.pdf", pb)
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

    # The score the producer saw - the package score the SQS panel and the cover
    # print (1 Oct 2026); the old average of the form scores only for a session
    # that has no package score.
    _scores = [(v or {}).get("sqs_score") for v in sqs_results.values()]
    _scores = [s for s in _scores if s is not None]
    _avg_score = (_pkg_score if _pkg_score is not None
                  else (round(sum(_scores) / len(_scores), 1) if _scores else None))
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
    # The stops as they stand (6 Oct 2026): the one door, never the stored
    # display cache (see services/stops_now.py).
    from services.stops_now import stops_now as _stops_now
    _lite_stops = _stops_now(proc_session, None, pre_form=not proc_session.get("generated_forms"))
    hard_stops  = _lite_stops["hard"]
    soft_stops  = _lite_stops["soft"]
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
    # The lists as a screen PRINTS them - each problem once (round 5 #15); the
    # scorer above read the door's own.
    from services.issue_registry import stops_for_display
    _shown_hard, _shown_soft = stops_for_display(hard_stops, soft_stops, _lite_stops["cross_issues"])
    return JSONResponse({"success": True, "sqs": sqs, "hard_stops": _shown_hard, "soft_stops": _shown_soft, "flags": flags})


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
    # The stops as they stand (6 Oct 2026): the one door, never the stored
    # display cache (see services/stops_now.py).
    from services.stops_now import stops_now as _stops_now
    _brief_stops = _stops_now(proc_session, None, pre_form=not proc_session.get("generated_forms"))
    hard_stops  = _brief_stops["hard"]
    soft_stops  = _brief_stops["soft"]
    # The brief PRINTS each problem once (round 5 #15): a legacy stop and its
    # coded twin collapse by the cards' own rule. Display copies only - the
    # scorer below still reads the door's lists.
    from services.issue_registry import stops_for_display
    _shown_hard, _shown_soft = stops_for_display(hard_stops, soft_stops,
                                                 _brief_stops["cross_issues"])
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
    # Once forms exist, the brief prints the TOTAL PACKAGE SCORE exactly as the SQS
    # panel does (1 Oct 2026) - the one door, never the Clarity snapshot taken at
    # the first analysis, which goes stale as soon as the forms are edited. Before
    # forms, the Lite screen's own source stands (Clarity, then the facts scorer).
    _pkg = (_package_score_now(proc_session, session_id, current_user["id"])
            if generated_forms else {}) or {}
    _row_label = "Pre-Submission Analysis"
    if _pkg.get("package_sqs_score") is not None:
        _row_label = "Total Package Score"
    if clarity_result.get("sqs_combined") and _pkg.get("package_sqs_score") is None:
        sqs = clarity_result["sqs_combined"]
    elif _pkg.get("package_sqs_score") is not None:
        _first = next((r["sqs"] for r in generated_forms.values() if r.get("sqs")), {})
        sqs = {
            **_first,
            "sqs_score":     _pkg["package_sqs_score"],
            "raw_sqs_score": _pkg.get("raw_sqs_score"),
            "cap_applied":   _pkg.get("cap_applied"),
            "cap_reason":    _pkg.get("cap_reason"),
            # The package's open hard stops (19 Oct 2026): they hold its tier
            # below Submission Ready - never the first form's count.
            "open_hard_stops": _pkg.get("open_hard_stops") or 0,
            "ready_blockers":  _pkg.get("ready_blockers") or [],
            "breakdown":     _pkg.get("pillars", _first.get("breakdown", {})),
            "tier":          _pkg.get("tier", _first.get("tier")),
            "routing_decision": _pkg.get("routing_decision", _first.get("routing_decision")),
            # The PACKAGE score's own grade (1 Oct 2026): the first form's grade
            # rode along above and printed "77/100 B" where the app shows C.
            "grade":         tier_for_score(_pkg["package_sqs_score"])[0],
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
            # The brief's one row is the first selected form - named, as every
            # scorer call must name the form it scores (1 Oct 2026).
            form_id=selected_ids[0],
            session_data=proc_session,
        )
    sqs_results = {_row_label: sqs}

    # Same "still unresolved" definition used on the real ACORD-package cover, so an
    # Essentials-tier producer sees the same open items whether they get a Lite
    # cover sheet or a full package.
    unresolved_recs = await current_unresolved_recommendations(session_id, proc_session)

    from services.cover_service import generate_lite_cover_narrative
    ai_content = await generate_lite_cover_narrative(
        facts=facts, flags=flags, sqs=sqs,
        hard_stops=_shown_hard, soft_stops=_shown_soft,
        org_name=org_name, user=fresh,
    )
    cover_pdf = build_cover_page_pdf(
        facts=facts, flags=flags, sqs_results=sqs_results, form_ids=[],
        org_name=org_name, narrative=ai_content["narrative"],
        ai_block=ai_content["ai_block"],
        sqs_reasoning=ai_content.get("sqs_reasoning", ""),
        user=fresh,
        hard_stops=_shown_hard, soft_stops=_shown_soft,
    )
    # The record goes on BEFORE the checksum below: the checksum proves the
    # bytes delivered, and these are them.
    cover_pdf = _cover_with_record(cover_pdf, proc_session)

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
