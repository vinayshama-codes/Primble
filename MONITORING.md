# Acordly Production Monitoring Checklist

## Render Dashboard — Check Weekly

| Metric | Location | Alert Threshold |
|--------|----------|----------------|
| Web service memory | Render → acordly-api → Metrics | >1.5 GB sustained |
| Worker memory | Render → acordly-worker → Metrics | >1.2 GB sustained |
| PostgreSQL connections | Render → acordly-db → Metrics | >80 active connections |
| Redis memory | Render → acordly-redis → Metrics | >20 MB |

## Render Log Stream — Watch For

Search these strings in Render's live log stream:

| Log string | What it means | Action |
|------------|--------------|--------|
| `Heavy semaphore full` | `MAX_CONCURRENT_HEAVY_OPS` is too low | Increase `MAX_CONCURRENT_HEAVY_OPS` on the worker |
| `job_dead_lettered` | Job failed permanently after max retries | Investigate the job in DB; check `jobs` table for `retry_count >= 5` |
| `easyocr` (in OCR logs) | EasyOCR fallback active — high memory use | Set `OCR_PROVIDER=textract` or `google_vision` on both services |
| `rate_limiter: Redis error` | Redis connectivity issue during request | Check Redis service health on Render dashboard |
| `Redis unavailable` (at startup) | Redis URL not configured or unreachable | Verify `REDIS_URL` env var on both web and worker services |
| `decrypt_facts: FIELD_ENCRYPTION_KEY mismatch` | Encryption key rotated without migrating data | Do NOT change `FIELD_ENCRYPTION_KEY` after initial deploy |

## Worker Health Check

- Worker service should show **Running** on the Render dashboard (acordly-worker).
- If the worker stops, jobs accumulate in the `jobs` table with `status = 'pending'`.
- Recovery: restart the worker via **Render dashboard → acordly-worker → Manual Deploy** or restart button.
- To verify queue depth: `SELECT count(*), status FROM jobs GROUP BY status;` on the Render Postgres shell.

## Uptime Monitoring (External)

Set up [UptimeRobot](https://uptimerobot.com) (free tier) to ping `GET /api/health` every 5 minutes.
Alert on non-200 response. This is the only external alerting available without paid Render plans.

## Sentry Error Tracking

Set `SENTRY_DSN` on both the web service and worker to enable error tracking.
Create a free Sentry project at sentry.io and copy the DSN from Project Settings → Client Keys.

## Scaling Triggers

Scale when any of these conditions are consistently true for >10 minutes:

| Condition | Action |
|-----------|--------|
| p95 latency on `GET /api/auth/me` > 500 ms | Add a 2nd API instance on Render |
| Pending job count in DB > 5 for >10 min | Add a 2nd worker instance on Render |
| Redis memory > 20 MB | Upgrade Redis to Render Standard plan |
| Postgres connections consistently > 60 | Upgrade Postgres or reduce `DB_POOL_MAX` |
| Worker memory > 1.2 GB | Switch `OCR_PROVIDER` from `easyocr` to `textract` |

## Architecture Path to 1000+ Users (No Code Changes)

All application state is external (Redis + PostgreSQL). Instances are stateless.

1. Add worker instances: Render → acordly-worker → increase instance count
2. Switch job queue to SQS: set `JOB_QUEUE_BACKEND=sqs` (already coded)
3. Add API instances: Render → acordly-api → increase instance count
4. Upgrade Redis to Render Standard
5. Upgrade Postgres to a plan with more connections (Standard supports 120+)

## Critical Database Warning

**The free Render Postgres plan expires after 90 days and causes DATA LOSS.**
Ensure `DATABASE_URL` points to a **Starter plan ($7/mo) or higher** before going live.
Check the plan under Render → acordly-db → Info.

## Performance Baselines (Post-Deploy Targets)

| Endpoint | Target | Notes |
|----------|--------|-------|
| `GET /api/auth/me` | < 50 ms | 30s Redis cache active |
| `POST /api/upload-declaration` | < 10 s | Async mode; just enqueues |
| `GET /api/jobs/{id}/status` | < 20 ms | Simple DB read |
| 10-form parallel generation | < 60 s | Worker with 4-thread executor |
| Single form generation | < 15 s | Includes GPT batch fill |
