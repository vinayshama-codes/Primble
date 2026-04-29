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
  Same as the API. In async mode AWS_S3_BUCKET must be set.

Environment tuning:
  WORKER_POLL_INTERVAL         — seconds between polls (default 5)
  WORKER_MAX_JOBS_PER_CYCLE    — max jobs per iteration (default 3)
"""
import asyncio
import logging
import os
import sys
import tempfile
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

_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "5"))
_MAX_PER_CYCLE = int(os.getenv("WORKER_MAX_JOBS_PER_CYCLE", "3"))
_BACKEND       = os.getenv("JOB_QUEUE_BACKEND", "local_file").lower()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_error(ex: Exception) -> str:
    """Return a safe, non-leaking error string for job records."""
    return f"{type(ex).__name__}: {str(ex)[:200]}"


def _resolve_source_files(payload: dict) -> list:
    """Return local file paths to process. Downloads from S3 if s3_keys present."""
    s3_keys    = payload.get("s3_keys", [])
    file_paths = payload.get("file_paths", [])

    if s3_keys:
        from services.s3_service import download_source_file, delete_source_file
        tmp_paths = []
        for key in s3_keys:
            data = download_source_file(key)
            if data is None:
                logger.warning("Worker: could not download S3 key %s — skipping", key)
                continue
            suffix = os.path.splitext(key)[-1] or ".tmp"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(data)
            tmp.close()
            tmp_paths.append((tmp.name, key))
        return tmp_paths  # list of (local_path, s3_key) tuples

    # file_paths: local disk files (sync mode / dev only)
    return [(p, None) for p in file_paths if os.path.exists(p)]


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
    s3_keys_to_delete = [k for _, k in source_pairs if k]

    try:
        from services.ocr_service import extract_text
        from services.extraction_service import (
            extract_facts_long, identify_doc_type, merge_facts, select_primary_truth,
        )
        from services.form_service import (
            filter_available_forms, load_all_forms, match_forms, score_extra_forms,
        )
        from services.sqs_service import (
            check_tier1, check_tier2, evaluate_stops, check_doc_consistency,
        )
        from repositories.session_repository import new_processing_session

        processed_docs = []
        all_low_conf: list = []
        for path in local_paths:
            try:
                text, low_conf = extract_text(path)
            except Exception as ex:
                logger.warning("Job %s: OCR failed for %s: %s", job_id, path, ex)
                continue
            if len(text) < 30:
                continue
            all_low_conf += low_conf
            doc_type  = identify_doc_type(text)
            extracted = extract_facts_long(text, doc_type, low_confidence_tokens=low_conf)
            processed_docs.append({
                "filename":              os.path.basename(path),
                "path":                  path,
                "doc_type":              doc_type,
                "text":                  text,
                "facts":                 extracted.get("facts", {}),
                "flags":                 extracted.get("flags", {}),
                "low_confidence_tokens": low_conf,
                "truncation_warning":    extracted.get("truncation_warning"),
            })

        if not processed_docs:
            await queue.update_status(job_id, "failed", error="no_readable_text")
            logger.error("Job %s: no readable text", job_id)
            return

        await queue.update_status(job_id, "processing", progress_message="Matching ACORD forms…")

        primary              = select_primary_truth(processed_docs)
        merged_facts, mflags = merge_facts(processed_docs, primary)
        mflags["_doc_type"]  = primary.get("doc_type", "unknown")
        tier1_ok, tier1_missing = check_tier1(merged_facts, mflags)

        if not tier1_ok:
            await queue.update_status(
                job_id, "failed",
                error="tier1_validation_failed",
                result={"missing_fields": tier1_missing, "gate": "tier1_fail"},
            )
            return

        tier2_score, tier2_missing = check_tier2(merged_facts)
        hard_stops, soft_stops     = evaluate_stops(merged_facts, mflags)
        for issue in check_doc_consistency(processed_docs):
            hard_stops = list(hard_stops) + [issue]

        all_forms       = load_all_forms()
        available_forms = filter_available_forms(all_forms)
        combined_text   = " ".join(d.get("text", "") for d in processed_docs)
        recommendations = match_forms(merged_facts, mflags, available_forms, text=combined_text)
        triggered_ids   = {r["form_id"] for r in recommendations}
        extra_scored    = score_extra_forms(merged_facts, triggered_ids, available_forms)
        unique_low_conf = list(dict.fromkeys(all_low_conf))

        sid = new_processing_session({
            "user_id": user_id, "docs": processed_docs,
            "primary_doc": primary["filename"], "facts": merged_facts, "flags": mflags,
            "tier2_score": tier2_score, "tier2_missing": tier2_missing,
            "hard_stops": hard_stops, "soft_stops": soft_stops,
            "all_forms": available_forms, "recommendations": recommendations,
            "selected_form_ids": [], "generated_forms": {},
            "low_confidence_tokens": unique_low_conf,
        })

        await queue.update_status(job_id, "completed", result={"session_id": sid})
        logger.info("Job %s (extraction) completed: session_id=%s", job_id, sid)

    except Exception as ex:
        err = _sanitize_error(ex)
        logger.error("Job %s extraction failed: %s\n%s", job_id, err, traceback.format_exc())
        try:
            await queue.update_status(job_id, "failed", error=err)
        except Exception:
            pass
    finally:
        # Delete temp files (S3 downloads)
        for path in local_paths:
            try:
                os.unlink(path)
            except OSError:
                pass
        # Clean up S3 source files after successful or failed processing
        if s3_keys_to_delete:
            try:
                from services.s3_service import delete_source_file
                for key in s3_keys_to_delete:
                    delete_source_file(key)
            except Exception as ex:
                logger.warning("Job %s: S3 cleanup failed: %s", job_id, ex)


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
        from services.audit_service import log_recommendations_presented
        import os as _os

        session = get_processing_session(session_id)
        if not session:
            await queue.update_status(job_id, "failed", error="session_not_found")
            return

        results = {}
        for form_id in form_ids:
            form_meta = next((f for f in session.get("all_forms", []) if f["form_id"] == form_id), None)
            if not form_meta:
                continue
            tpl = _os.path.join(TEMPLATE_DIR, form_meta.get("template_file", ""))
            if not _os.path.exists(tpl):
                logger.warning("Job %s: template missing for %s", job_id, form_id)
                continue
            try:
                result = process_single_form(form_meta, session)
                results[form_id] = result
            except Exception as ex:
                logger.error("Job %s: form %s failed: %s", job_id, form_id, ex)

        if not results:
            await queue.update_status(job_id, "failed", error="no_forms_generated")
            return

        cross_issues_raw     = cross_validate(session["facts"], session.get("flags", {}), form_ids)
        seen_msgs            = set()
        cross_issues_deduped = []
        for issue in cross_issues_raw:
            msg = issue.get("message", "")
            if msg not in seen_msgs:
                seen_msgs.add(msg)
                cross_issues_deduped.append(issue)

        upd_processing_session(session_id, {
            "selected_form_ids": form_ids,
            "generated_forms":   results,
            "active_form_id":    form_ids[0] if form_ids else None,
            "cross_issues_last": cross_issues_deduped,
        })

        # Log audit recommendations
        for fid, r in results.items():
            sqs_data = r.get("sqs")
            if sqs_data and sqs_data.get("recommendations"):
                try:
                    log_recommendations_presented(
                        session_id=session_id,
                        user_id=user_id,
                        sqs_result=sqs_data,
                        model_version=SQS_MODEL_VERSION,
                    )
                except Exception as ex:
                    logger.warning("Job %s: audit log failed for %s: %s", job_id, fid, ex)

        await queue.update_status(
            job_id, "completed",
            result={"session_id": session_id, "form_ids": form_ids},
        )
        logger.info("Job %s (form_generation) completed: session_id=%s forms=%s", job_id, session_id, form_ids)

    except Exception as ex:
        err = _sanitize_error(ex)
        logger.error("Job %s form_generation failed: %s\n%s", job_id, err, traceback.format_exc())
        try:
            await queue.update_status(job_id, "failed", error=err)
        except Exception:
            pass


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def _dispatch_job(job: dict, queue) -> None:
    job_type = job.get("job_type", "")
    job_id   = job["job_id"]

    if job_type == "extraction":
        await _process_extraction_job(job, queue)
    elif job_type == "form_generation":
        await _process_form_generation_job(job, queue)
    else:
        logger.warning("Job %s: unknown job_type=%r — marking failed", job_id, job_type)
        await queue.update_status(job_id, "failed", error=f"unknown_job_type:{job_type}")


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

                # Idempotency: check DB status before processing
                job = await queue.get_status(job_id)
                if not job:
                    logger.warning("Job %s not in DB — deleting SQS message", job_id)
                    queue.delete_message(msg["ReceiptHandle"])
                    continue
                if job["status"] != "pending":
                    # Already claimed or completed — ack and skip to avoid duplicate work.
                    # A 'processing' status means another worker is actively running it.
                    queue.delete_message(msg["ReceiptHandle"])
                    continue

                receipts[job_id] = msg["ReceiptHandle"]
                tasks.append(_dispatch_job(job, queue))
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


# ── DB / file polling mode ────────────────────────────────────────────────────

async def _run_poll_loop(queue, once: bool = False) -> None:
    logger.info("Worker poll mode (backend=%s, interval=%ds)", _BACKEND, _POLL_INTERVAL)
    while True:
        try:
            pending = await queue.list_pending(limit=_MAX_PER_CYCLE)
        except Exception as ex:
            logger.error("list_pending error: %s — retrying in %ds", ex, _POLL_INTERVAL)
            if once:
                return
            await asyncio.sleep(_POLL_INTERVAL)
            continue

        if pending:
            logger.info("Dispatching %d pending job(s)", len(pending))
            await asyncio.gather(*[_dispatch_job(j, queue) for j in pending], return_exceptions=True)
        else:
            logger.debug("No pending jobs")

        if once:
            return
        await asyncio.sleep(_POLL_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    once = "--once" in sys.argv

    from services.job_queue import get_job_queue
    queue = get_job_queue()

    if _BACKEND == "sqs" and not once:
        await _run_sqs_loop(queue)
    else:
        await _run_poll_loop(queue, once=once)


if __name__ == "__main__":
    asyncio.run(main())
