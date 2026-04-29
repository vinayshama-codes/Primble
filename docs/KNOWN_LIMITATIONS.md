# Known Limitations

## Async Processing (ENABLE_ASYNC_PROCESSING)

`ENABLE_ASYNC_PROCESSING=true` is **NOT production-ready**.

No background worker process exists yet. Setting this flag causes upload endpoints to return HTTP 202 immediately, but the actual OCR/LLM work is never performed. Leave this env var unset (defaults to `false`) until a real worker (Celery, ARQ, or similar) is wired up.

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

**To scale past one worker:** Configure `REDIS_URL`. The rate limiter will automatically use Redis for cross-process coordination. A Redis-based semaphore must also be added to `utils/concurrency.py` before raising concurrency.

## Cover Narrative Cache

The cover-page narrative is cached in-process with no TTL and no maximum size. The cache resets on every server restart.

**Implication:** Cache grows unboundedly in long-running single-worker deployments. Add `functools.lru_cache(maxsize=512)` or a TTL-aware cache before scaling past ~50 active users.

## Template-Pending Forms

The following ACORD forms are matched and shown in recommendations but **cannot generate PDFs yet** because their template files are not available:

- ACORD 127 — Business Auto Section
- ACORD 130 — Workers Compensation Application  
- ACORD 131 — Umbrella / Excess Liability
- ACORD 141 — Property Schedule

These appear in the UI with a "Template coming soon" label and are excluded from the PDF generation pipeline. Supported PDF-generating forms: **ACORD 25, 125, 126, 140**.
