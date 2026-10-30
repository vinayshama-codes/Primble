# Known Limitations

## Async Processing (ENABLE_ASYNC_PROCESSING)

`ENABLE_ASYNC_PROCESSING=true` is **NOT production-ready**.

A worker exists (`backend/worker.py`, DB-backed job queue), but production and localhost both run the SYNC route (the Render dashboard sets `ENABLE_ASYNC_PROCESSING=false`). Leave it `false`; the async path is a fallback, not the tested path. (Updated 26 Oct 2026.)

## OCR + LLM Latency

The synchronous processing path runs OCR → extraction → form matching in a single request. Expected latency by upload size:

| Files | Approximate Duration |
|-------|---------------------|
| 1–3   | 10–30 s (sweet spot) |
| 4–7   | 30–70 s             |
| 8–10  | 50–120 s            |

**Recommendation:** Set nginx `proxy_read_timeout ≥ 130s` when deploying. Uploading 1–3 files gives the best user experience.

## Multi-Worker: Rate Limiter and Semaphore Are In-Process Only

Both `utils/rate_limiter.py` and `utils/concurrency.py` use in-process state (dict + asyncio.Semaphore). This means:

- Per-user rate limits are enforced **per worker process**, not globally.
- The heavy-request semaphore only prevents overload **within one process**.

**For MVP:** `WEB_CONCURRENCY=1` (set in Dockerfile) is required. With a single worker these controls are fully effective.

**To scale past one worker:** Configure `REDIS_URL`. The rate limiter and the Redis distributed semaphore in `utils/concurrency.py` both use it automatically. (Updated 26 Oct 2026 - the semaphore exists now.)

## Cover Narrative Cache

The cover-page narrative is cached in-process in a `TTLCache(maxsize=256, ttl=3600)` (`routes/download_routes.py`). It resets on every server restart and is per worker process. (Updated 26 Oct 2026 - it was unbounded.)

## Template-Pending Forms - RESOLVED

All 17 supported forms have templates and generate PDFs, ACORD 127 / 130 / 131 / 141 included (`backend/templates/`). (Updated 26 Oct 2026.)
