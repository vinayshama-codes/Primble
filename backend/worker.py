"""Acordly background worker.

Runs as a standalone process alongside the API server. Picks up pending
jobs from the configured queue and dispatches by job_type.

Supported job types:
  extraction       — OCR + LLM extraction + form matching (from /api/upload-declaration)
  form_generation  — ACORD form generation (from /api/select-forms-bulk)

Usage:
  python worker.py                    # continuous poll loop
  python worker.py --once             # process one batch then exit
  JOB_QUEUE_BACKEND=db python worker.py

Required env vars:
  Same as the API. In async mode STORAGE_BUCKET (+ STORAGE_ENDPOINT/ACCESS_KEY/SECRET_KEY) must be set.

Environment tuning:
  WORKER_POLL_INTERVAL         — seconds between polls (default 5)
  WORKER_MAX_JOBS_PER_CYCLE    — max jobs per iteration (default 3)
  WORKER_FORM_GEN_CONCURRENCY  — max parallel forms per job (default 4)
"""
import asyncio
import concurrent.futures
import logging
import os
import sys
import tempfile
import time
import traceback

from dotenv import load_dotenv

load_dotenv()

# Sentry — same DSN as the API process; worker errors appear in the same project.
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.getenv("ENVIRONMENT", "development"),
        release=os.getenv("APP_VERSION", "12.4.0"),
        traces_sample_rate=0.0,  # no performance tracing for workers
        integrations=[LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR)],
        send_default_pii=False,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("worker")

_POLL_INTERVAL        = int(os.getenv("WORKER_POLL_INTERVAL", "5"))
_MAX_PER_CYCLE        = int(os.getenv("WORKER_MAX_JOBS_PER_CYCLE", "3"))
_BACKEND              = os.getenv("JOB_QUEUE_BACKEND", "local_file").lower()
_FORM_GEN_CONCURRENCY = int(os.getenv("WORKER_FORM_GEN_CONCURRENCY", "4"))
_MAX_JOB_RETRIES      = int(os.getenv("WORKER_MAX_JOB_RETRIES", "5"))
# Watchdog: how often to re-scan for stuck 'processing' jobs after startup
# (also recovers jobs orphaned mid-shift by an OOM kill / deploy restart).
_WATCHDOG_INTERVAL_S  = int(os.getenv("WORKER_WATCHDOG_INTERVAL", "300"))  # 5 min

# Dedicated thread-pool for form generation (separate from OCR executor to avoid
# saturation when both extraction and form-gen jobs run concurrently).
_FORM_GEN_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_FORM_GEN_CONCURRENCY,
    thread_name_prefix="form-gen",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_error(ex: Exception) -> str:
    """Return a safe, non-leaking error string for job records."""
    return f"{type(ex).__name__}: {str(ex)[:200]}"


def _strip_uuid_prefixes(name: str) -> str:
    """Strip leading UUID hex prefixes (32 alnum chars + underscore) from a filename."""
    for _ in range(5):
        parts = name.split("_", 1)
        if len(parts) == 2 and len(parts[0]) == 32 and parts[0].isalnum():
            name = parts[1]
        else:
            break
    return name


async def _notify_user_job_done(user_id: str, session_id: str, kind: str) -> None:
    """Best-effort completion email. Never raises — failures are swallowed."""
    if not user_id:
        return
    try:
        from config.database import get_pool
        from services.email_service import send_processing_complete_email
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, full_name FROM users WHERE id=$1", user_id
            )
        if not row:
            return
        email = (dict(row).get("email") or "").strip()
        name  = (dict(row).get("full_name") or "").strip()
        if not email:
            return
        await asyncio.get_running_loop().run_in_executor(
            None, send_processing_complete_email, email, name, session_id or "", kind,
        )
    except Exception as ex:
        logger.warning("notify_user_job_done failed (user=%s, kind=%s): %s", user_id, kind, ex)


def _resolve_source_files(payload: dict) -> list:
    """Return [(local_path, s3_key_or_None), ...] ready for processing.

    Sync jobs supply file_paths (local tmp files already on disk).
    Async jobs supply s3_keys (uploaded to Supabase Storage by the web process);
    these are downloaded to temp files so the extraction pipeline can read them.
    """
    file_paths = payload.get("file_paths", [])
    if file_paths:
        return [(p, None) for p in file_paths if os.path.exists(p)]

    s3_keys = payload.get("s3_keys", [])
    if not s3_keys:
        return []

    from services.s3_service import download_pdf as _s3_get, is_configured as _s3_ok
    if not _s3_ok():
        logger.error("Worker: job has s3_keys but STORAGE_BUCKET is not configured")
        return []

    pairs = []
    for key in s3_keys:
        try:
            data = _s3_get(key)
            if data is None:
                logger.warning("Worker: failed to download s3_key=%s — skipping", key)
                continue
            suffix = os.path.splitext(key)[-1] or ".bin"
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            with open(tmp_path, "wb") as fh:
                fh.write(data)
            pairs.append((tmp_path, key))
        except Exception as ex:
            logger.error("Worker: error downloading s3_key=%s: %s", key, ex)
    return pairs


# ── Extraction job ─────────────────────────────────────────────────────────────

async def _process_extraction_job(job: dict, queue) -> None:
    job_id  = job["job_id"]
    payload = job.get("payload") or {}
    user_id = job.get("user_id", "")

    await queue.update_status(job_id, "processing", progress_message="Extracting text…")

    source_pairs = _resolve_source_files(payload)
    if not source_pairs:
        await queue.update_status(job_id, "failed", error="no_source_files_available")
        logger.error("Job %s: no readable source files", job_id)
        return

    local_paths = [p for p, _ in source_pairs]

    try:
        from services.extraction_pipeline import run_extraction_pipeline

        await queue.update_status(job_id, "processing", progress_message="Matching ACORD forms…")

        try:
            result = await run_extraction_pipeline(local_paths, user_id)
        except ValueError:
            await queue.update_status(job_id, "failed", error="no_readable_text")
            logger.error("Job %s: no readable text", job_id)
            return

        # Submission Integrity review (Beta Report §4.1) takes precedence over the
        # tier1 gate: a multi-insured package is paused for review BEFORE we treat
        # missing baseline fields as a failure, so the user reaches the review step.
        _integrity = result.get("integrity") or {}
        if not result["tier1_ok"] and not _integrity.get("review_required"):
            await queue.update_status(
                job_id, "failed",
                error="tier1_validation_failed",
                result={"missing_fields": result["tier1_missing"], "gate": "tier1_fail"},
            )
            return

        # Record the Submission Integrity verdict (Beta Report §4.1) — mirrors the
        # synchronous upload route so the async path leaves no audit gap.
        try:
            from services.audit_service import log_integrity_assessed
            await log_integrity_assessed(result["session_id"], user_id, _integrity)
        except Exception as _audit_ex:
            logger.warning("Job %s: integrity audit log failed (non-fatal): %s", job_id, _audit_ex)

        await queue.update_status(job_id, "completed", result={"session_id": result["session_id"]})
        logger.info("Job %s (extraction) completed: session_id=%s", job_id, result["session_id"])
        await _notify_user_job_done(user_id, result["session_id"], "upload")

    except Exception as ex:
        err = _sanitize_error(ex)
        logger.error("Job %s extraction failed: %s\n%s", job_id, err, traceback.format_exc())
        try:
            await queue.update_status(job_id, "failed", error=err)
        except Exception:
            pass
    finally:
        for path in local_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


# ── Form generation job ────────────────────────────────────────────────────────

async def _process_form_generation_job(job: dict, queue) -> None:
    job_id     = job["job_id"]
    payload    = job.get("payload") or {}
    session_id = payload.get("session_id") or job.get("session_id")
    form_ids   = payload.get("form_ids", [])
    user_id    = job.get("user_id", "")

    if not session_id:
        await queue.update_status(job_id, "failed", error="missing_session_id_in_payload")
        return

    if not form_ids:
        await queue.update_status(job_id, "failed", error="missing_form_ids_in_payload")
        return

    await queue.update_status(job_id, "processing", progress_message="Generating ACORD forms…")

    try:
        from config.settings import TEMPLATE_DIR
        from repositories.session_repository import get_processing_session, upd_processing_session
        from services.form_service import process_single_form
        from services.sqs_service import cross_validate, calculate_package_sqs, SQS_MODEL_VERSION
        from services.audit_service import log_recommendations_presented, run_and_log_field_qa
        import os as _os

        session = await get_processing_session(session_id)
        if not session:
            await queue.update_status(job_id, "failed", error="session_not_found")
            return

        # Submission Integrity gate (Beta Report §4.1): never generate forms on a
        # package still pending multi-insured review. Mirrors the synchronous
        # guard in form_routes.select_forms_bulk.
        _integrity = session.get("integrity") or {}
        if _integrity.get("review_required") and not _integrity.get("overridden"):
            await queue.update_status(
                job_id, "failed", error="submission_integrity_review_required"
            )
            logger.warning(
                "Job %s blocked: submission integrity review pending for session %s",
                job_id, session_id,
            )
            return

        # Building-value review gate (client Property Integrity): never generate
        # forms while building values conflict across documents and remain
        # unconfirmed. Mirrors form_routes.enforce_building_value_gate.
        from services.underwriting_consistency import GENERATION_BLOCKING_RECONCILABLE_KEYS
        _uw = session.get("underwriting_consistency") or {}
        if any(
            f.get("fact_key") in GENERATION_BLOCKING_RECONCILABLE_KEYS and f.get("review_required")
            for f in (_uw.get("fields") or [])
        ):
            await queue.update_status(
                job_id, "failed", error="building_value_review_required"
            )
            logger.warning(
                "Job %s blocked: building-value review pending for session %s",
                job_id, session_id,
            )
            return

        loop = asyncio.get_running_loop()

        async def _generate_one(fid: str):
            """Generate a single form; returns (fid, result) or (fid, None) on failure."""
            form_meta = next(
                (f for f in session.get("all_forms", []) if f["form_id"] == fid), None
            )
            if not form_meta:
                logger.warning("Job %s: form_meta missing for %s", job_id, fid)
                return fid, None
            tpl = _os.path.join(TEMPLATE_DIR, form_meta.get("template_file", ""))
            if not _os.path.exists(tpl):
                logger.warning("Job %s: template missing for %s", job_id, fid)
                return fid, None
            try:
                result = await loop.run_in_executor(
                    _FORM_GEN_EXECUTOR, process_single_form, form_meta, session
                )
                return fid, result
            except Exception as ex:
                logger.error("Job %s: form %s failed: %s", job_id, fid, ex)
                return fid, None

        # Run all form-generation coroutines in parallel; individual failures are
        # captured per-form (return_exceptions=True) so one failure doesn't cancel others.
        gen_results = await asyncio.gather(
            *[_generate_one(fid) for fid in form_ids],
            return_exceptions=True,
        )

        results = {}
        failed_form_ids = []
        for item in gen_results:
            if isinstance(item, Exception):
                logger.error("Job %s: unexpected gather exception: %s", job_id, item)
                continue
            fid, result = item
            if result is not None:
                results[fid] = result
            else:
                failed_form_ids.append(fid)

        if not results:
            await queue.update_status(job_id, "failed", error="no_forms_generated")
            return

        # §4.3 item 2: post-generation cross-form consistency assertion (mirrors
        # the sync select_forms_bulk path). Non-blocking: any drift is surfaced
        # via the cross-issues channel and persisted for audit; scoring untouched.
        _stamp_check  = {"ok": True, "checked": 0, "mismatches": []}
        _stamp_issues = []
        try:
            from services.underwriting_consistency import (
                verify_stamped_consistency, stamp_mismatch_issues,
            )
            _stamp_check = verify_stamped_consistency(
                results,
                merged_facts=session.get("facts") or {},
                confirmations=session.get("underwriting_confirmations") or {},
            )
            _stamp_issues = stamp_mismatch_issues(_stamp_check)
        except Exception as _vex:
            logger.warning("Job %s: stamped-consistency check skipped: %s", job_id, _vex)

        cross_issues_raw     = cross_validate(session["facts"], session.get("flags", {}), form_ids)
        seen_msgs            = set()
        cross_issues_deduped = []
        for issue in cross_issues_raw:
            msg = issue.get("message", "")
            if msg not in seen_msgs:
                seen_msgs.add(msg)
                cross_issues_deduped.append(issue)

        # Compute package SQS via the same scorer the sync + remediation paths use
        # so async (worker) sessions carry the full enriched package summary -
        # including loss_history_state, umbrella_state, evidence_labels, and the
        # 6-pillar breakdown - rather than a stripped-down per-form average.
        _sqs_list = [r["sqs"] for r in results.values() if r.get("sqs")]
        package_sqs = None
        if _sqs_list:
            try:
                package_sqs = calculate_package_sqs(
                    facts=session["facts"],
                    flags=session.get("flags", {}),
                    form_results=_sqs_list,
                    cross_issues=cross_issues_deduped,
                    hard_stops=session.get("hard_stops", []),
                    soft_stops=session.get("soft_stops", []),
                    session_data=session,
                    session_id=session_id,
                    user_id=user_id,
                    calculation_stage="form_generated",
                )
            except Exception as _pkg_ex:
                # Defensive fallback: a scoring failure must never block form
                # delivery. Mirror the previous simple per-form average shape.
                logger.error("Job %s: calculate_package_sqs failed, using per-form average: %s", job_id, _pkg_ex)
                _scores = [s.get("sqs_score") for s in _sqs_list if s.get("sqs_score") is not None]
                _first  = _sqs_list[0]
                package_sqs = {
                    "package_sqs_score": int(round(sum(_scores) / len(_scores))) if _scores else 0,
                    "tier":              _first.get("tier"),
                    "pillars":           _first.get("breakdown", {}),
                    "weights_used":      _first.get("breakdown", {}),
                    "weights_version":   "spec_compliant_v2.1.0",
                    "form_ids":          list(results.keys()),
                    "model_version":     SQS_MODEL_VERSION,
                }

        # Display copy = cross-form validation + any stamp-mismatch advisory.
        # SQS above used the pure cross_issues_deduped, so scoring is untouched.
        _update_payload = {
            "selected_form_ids": form_ids,
            "generated_forms":   results,
            "active_form_id":    form_ids[0] if form_ids else None,
            "cross_issues_last": cross_issues_deduped + _stamp_issues,
            "underwriting_stamp_consistency": _stamp_check,
        }
        if package_sqs is not None:
            _update_payload["package_sqs"] = package_sqs

        await upd_processing_session(session_id, _update_payload)

        # Log audit recommendations
        for fid, r in results.items():
            sqs_data = r.get("sqs")
            if sqs_data and sqs_data.get("recommendations"):
                try:
                    await log_recommendations_presented(
                        session_id=session_id,
                        user_id=user_id,
                        sqs_result=sqs_data,
                        model_version=SQS_MODEL_VERSION,
                    )
                except Exception as ex:
                    logger.warning("Job %s: audit log failed for %s: %s", job_id, fid, ex)

        # Form-level field QA (Figure 26): parity with the sync route. Advisory;
        # gated OFF by default.
        await run_and_log_field_qa(
            session_id, user_id, results,
            session.get("facts") or {}, session.get("underwriting_confirmations") or {},
            _os.getenv("ENABLE_FIELD_QA", "false").lower() == "true",
        )

        completion_result: dict = {"session_id": session_id, "form_ids": list(results.keys())}
        if failed_form_ids:
            completion_result["partial_failure"] = True
            completion_result["failed_form_ids"] = failed_form_ids
            logger.warning(
                "Job %s (form_generation) partial: %d/%d forms succeeded, failed=%s",
                job_id, len(results), len(form_ids), failed_form_ids,
            )

        await queue.update_status(job_id, "completed", result=completion_result)
        logger.info(
            "Job %s (form_generation) completed: session_id=%s forms=%s",
            job_id, session_id, list(results.keys()),
        )
        await _notify_user_job_done(user_id, session_id, "generate")

    except Exception as ex:
        err = _sanitize_error(ex)
        logger.error("Job %s form_generation failed: %s\n%s", job_id, err, traceback.format_exc())
        try:
            await queue.update_status(job_id, "failed", error=err)
        except Exception:
            pass


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def _dispatch_with_semaphore(job: dict, queue) -> None:
    from utils.concurrency import try_acquire_heavy, release_heavy
    acquired = await try_acquire_heavy()
    if not acquired:
        job_id = job["job_id"]
        # Increment retry counter before deciding whether to requeue or dead-letter.
        try:
            new_count = await queue.increment_retry_count(job_id)
        except (AttributeError, Exception) as inc_ex:
            # Fallback for backends that don't support increment_retry_count
            logger.debug("increment_retry_count unsupported: %s", inc_ex)
            new_count = job.get("retry_count", 0) + 1

        if new_count > _MAX_JOB_RETRIES:
            logger.error(
                "job_dead_lettered job_id=%s retry_count=%d max_retries=%d reason=semaphore_always_full",
                job_id, new_count, _MAX_JOB_RETRIES,
            )
            try:
                await queue.update_status(
                    job_id, "failed",
                    error=f"dead_lettered_after_{new_count}_retries:semaphore_always_full",
                )
            except Exception as dl_ex:
                logger.error("Failed to dead-letter job %s: %s", job_id, dl_ex)
        else:
            logger.warning(
                "Heavy semaphore full, requeueing job %s (retry %d/%d)",
                job_id, new_count, _MAX_JOB_RETRIES,
            )
            try:
                await queue.update_status(job_id, "pending")
            except Exception as requeue_ex:
                logger.error("Failed to requeue job %s: %s", job_id, requeue_ex)
        await asyncio.sleep(2)
        return
    try:
        await _dispatch_job(job, queue)
    finally:
        await release_heavy(acquired)


async def _dispatch_job(job: dict, queue) -> None:
    job_type = job.get("job_type", "")
    job_id   = job["job_id"]
    user_id  = job.get("user_id", "")
    # Mask user_id to last 6 chars for SOC2 log compliance
    user_id_masked = f"***{user_id[-6:]}" if len(user_id) > 6 else "***"

    t_start = time.monotonic()
    logger.info(
        "job_start job_id=%s job_type=%s user=%s",
        job_id, job_type, user_id_masked,
    )

    try:
        if job_type == "extraction":
            await _process_extraction_job(job, queue)
        elif job_type == "form_generation":
            await _process_form_generation_job(job, queue)
        else:
            logger.warning("Job %s: unknown job_type=%r — marking failed", job_id, job_type)
            await queue.update_status(job_id, "failed", error=f"unknown_job_type:{job_type}")
            return
    finally:
        duration = time.monotonic() - t_start
        logger.info(
            "job_end job_id=%s job_type=%s user=%s duration_s=%.1f",
            job_id, job_type, user_id_masked, duration,
        )


# ── SQS polling mode ──────────────────────────────────────────────────────────

async def _run_sqs_loop(queue) -> None:
    logger.info("Worker starting in SQS long-poll mode")
    while True:
        try:
            messages = queue.receive_messages(max_messages=_MAX_PER_CYCLE, wait_seconds=20)
        except Exception as ex:
            logger.error("SQS receive error: %s — retrying in 10s", ex)
            await asyncio.sleep(10)
            continue

        if not messages:
            continue

        import json as _json
        tasks, receipts = [], {}
        for msg in messages:
            try:
                body   = _json.loads(msg["Body"])
                job_id = body.get("job_id")
                if not job_id:
                    queue.delete_message(msg["ReceiptHandle"])
                    continue

                # Verify the job record exists before attempting to claim it.
                job = await queue.get_status(job_id)
                if not job:
                    logger.warning("Job %s not in DB — deleting SQS message", job_id)
                    queue.delete_message(msg["ReceiptHandle"])
                    continue

                # Atomic claim: UPDATE … WHERE status='pending'. Only one worker
                # wins the race; all others get False and skip without duplicate work.
                claimed = await queue.claim_job_if_pending(job_id)
                if not claimed:
                    queue.delete_message(msg["ReceiptHandle"])
                    continue

                receipts[job_id] = msg["ReceiptHandle"]
                tasks.append(_dispatch_with_semaphore(job, queue))
            except Exception as ex:
                logger.warning("Failed to parse SQS message: %s", ex)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            # Only delete after processing is persisted
            for jid, receipt in receipts.items():
                try:
                    queue.delete_message(receipt)
                except Exception as ex:
                    logger.warning("Failed to delete SQS msg job %s: %s", jid, ex)


# ── Watchdog ───────────────────────────────────────────────────────────────────

async def _run_watchdog(queue) -> None:
    """Periodically reset jobs orphaned in 'processing' by crashed workers.

    Runs as a background task alongside the main poll/listen loop. Each
    sweep finds jobs with status='processing' whose updated_at is older
    than STUCK_JOB_THRESHOLD_MINUTES and flips them back to 'pending' so
    the next dispatch picks them up.
    """
    reset_fn = getattr(queue, "reset_stuck_jobs", None)
    if reset_fn is None:
        logger.info("Watchdog: backend has no reset_stuck_jobs — disabled")
        return
    # First sweep runs immediately at startup; subsequent sweeps every
    # _WATCHDOG_INTERVAL_S. This catches orphans from the previous crash
    # before we begin claiming new work.
    while True:
        try:
            await reset_fn()
        except Exception as ex:
            logger.error("Watchdog sweep failed: %s", ex)
        await asyncio.sleep(_WATCHDOG_INTERVAL_S)


# ── DB / file polling mode ────────────────────────────────────────────────────

async def _drain_pending(queue) -> int:
    """Pull and dispatch one batch of pending jobs. Returns count dispatched."""
    try:
        pending = await queue.list_pending(limit=_MAX_PER_CYCLE)
    except Exception as ex:
        logger.error("list_pending error: %s", ex)
        return 0
    if not pending:
        return 0
    logger.info("Dispatching %d pending job(s)", len(pending))
    await asyncio.gather(
        *[_dispatch_with_semaphore(j, queue) for j in pending],
        return_exceptions=True,
    )
    return len(pending)


async def _listen_for_notify(wake_event: asyncio.Event) -> None:
    """Background task: LISTEN on PostgreSQL acordly_jobs channel.

    Sets wake_event each time a NOTIFY arrives so the main loop dispatches
    immediately instead of waiting for the next poll tick. Falls back to
    pure polling if LISTEN fails (older Postgres, PgBouncer in transaction
    mode without session-mode passthrough, etc.).

    Note on PgBouncer: LISTEN/NOTIFY require a dedicated session, so this
    function opens a direct connection (NOT through the asyncpg pool) on
    the same DATABASE_URL. If your DATABASE_URL points to PgBouncer
    transaction mode (port 6543) you should set DATABASE_URL_DIRECT to the
    session-mode URL (port 5432) for this listener only.
    """
    import asyncpg
    from config.settings import DATABASE_URL
    from repositories.job_repository import JOB_NOTIFY_CHANNEL

    listen_url = os.getenv("DATABASE_URL_DIRECT") or DATABASE_URL
    _env = os.getenv("ENVIRONMENT", "development").lower()
    _ssl = "require" if _env == "production" else None

    while True:
        conn = None
        try:
            conn = await asyncpg.connect(listen_url, ssl=_ssl, statement_cache_size=0)

            def _on_notify(_conn, _pid, _channel, payload):
                logger.debug("NOTIFY received: channel=%s payload=%s", _channel, payload)
                wake_event.set()

            await conn.add_listener(JOB_NOTIFY_CHANNEL, _on_notify)
            logger.info("Worker LISTEN active on channel '%s'", JOB_NOTIFY_CHANNEL)
            # Keep the connection alive forever — asyncpg dispatches NOTIFY
            # callbacks on its internal reader task while we just sleep.
            while True:
                await asyncio.sleep(60)
                # Cheap keep-alive that detects dead TCP sockets behind NAT
                try:
                    await conn.execute("SELECT 1")
                except Exception:
                    break
        except Exception as ex:
            logger.warning(
                "LISTEN connection error (%s) — retrying in 10s; poll loop continues",
                ex,
            )
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
        await asyncio.sleep(10)


async def _run_poll_loop(queue, once: bool = False) -> None:
    """Hybrid LISTEN + poll loop.

    The listener fires wake_event on NOTIFY, dropping dispatch latency from
    WORKER_POLL_INTERVAL seconds to ~milliseconds. The poll fallback covers:
      (a) backends without NOTIFY support (local_file, sqs handled elsewhere),
      (b) the brief window when the LISTEN connection is reconnecting,
      (c) stuck jobs reset by the watchdog (which does not NOTIFY).
    """
    logger.info(
        "Worker poll mode (backend=%s, interval=%ds, max_per_cycle=%d)",
        _BACKEND, _POLL_INTERVAL, _MAX_PER_CYCLE,
    )

    if once:
        await _drain_pending(queue)
        return

    wake_event: asyncio.Event = asyncio.Event()
    # Only the DB backend supports NOTIFY; for local_file we just poll.
    listener_task: asyncio.Task | None = None
    if _BACKEND == "db":
        listener_task = asyncio.create_task(_listen_for_notify(wake_event))

    try:
        while True:
            # Drain everything currently pending. Loop so a single NOTIFY can
            # pull more than one job if the queue accumulated during the
            # previous dispatch.
            while await _drain_pending(queue) > 0:
                pass

            # Wait for either: a NOTIFY (instant), or the poll interval (safety net).
            wake_event.clear()
            try:
                await asyncio.wait_for(wake_event.wait(), timeout=_POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass  # poll tick — fall through to drain
    finally:
        if listener_task is not None:
            listener_task.cancel()
            try:
                await listener_task
            except (asyncio.CancelledError, Exception):
                pass


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    once = "--once" in sys.argv

    from services.job_queue import get_job_queue
    queue = get_job_queue()

    # Initialise the asyncpg pool for backends that use it. The watchdog
    # and DB-backed queue both need it; for local_file we skip silently.
    if _BACKEND == "db":
        try:
            from config.database import create_pool
            await create_pool()
        except Exception as ex:
            logger.error("Worker: failed to initialise DB pool: %s", ex)
            raise

    # Startup watchdog sweep: recover any jobs orphaned in 'processing' by a
    # previous crash before we begin claiming new work. Run BEFORE entering
    # the main loop so the first dispatch cycle includes the recovered jobs.
    reset_fn = getattr(queue, "reset_stuck_jobs", None)
    if reset_fn is not None:
        try:
            recovered = await reset_fn()
            if recovered:
                logger.warning("Worker startup: recovered %d stuck job(s)", recovered)
        except Exception as ex:
            logger.error("Worker startup watchdog failed: %s", ex)

    # Periodic watchdog runs alongside the main loop in non-once mode.
    watchdog_task: asyncio.Task | None = None
    if not once and reset_fn is not None:
        watchdog_task = asyncio.create_task(_run_watchdog(queue))

    try:
        if _BACKEND == "sqs" and not once:
            await _run_sqs_loop(queue)
        else:
            await _run_poll_loop(queue, once=once)
    finally:
        if watchdog_task is not None:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except (asyncio.CancelledError, Exception):
                pass


if __name__ == "__main__":
    asyncio.run(main())
