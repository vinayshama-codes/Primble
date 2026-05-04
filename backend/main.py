import asyncio
import logging
import os
import signal
import uuid as _uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.getenv("ENVIRONMENT", "development"),
        release=os.getenv("APP_VERSION", "12.4.0"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        integrations=[
            StarletteIntegration(transaction_style="url"),
            FastApiIntegration(transaction_style="url"),
            LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
        ],
        send_default_pii=False,
    )

from config.database import create_pool, close_pool, get_pool, init_db
from config.settings import ALLOWED_ORIGINS, MAX_UPLOAD_SIZE_BYTES, validate_production_config  # noqa: F401
from services.scheduler_service import start_scheduler, stop_scheduler
from utils.json_logging import JsonFormatter, set_trace_id
from routes.auth_routes import router as auth_router
from routes.form_routes import router as form_router
from routes.download_routes import router as download_router
from routes.stripe_routes import router as stripe_router
from routes.signature_routes import router as signature_router
from routes.arq_routes import router as arq_router
from routes.audit_routes import router as audit_router
from routes.job_routes import router as job_router
from routes.admin_routes import router as admin_router

_DEV_ROUTES_ENABLED = os.getenv("DEV_ROUTES_ENABLED", "false").lower() == "true"
_ENVIRONMENT        = os.getenv("ENVIRONMENT", "development").lower()
_IS_PROD            = _ENVIRONMENT == "production"
_JOB_QUEUE_BACKEND  = os.getenv("JOB_QUEUE_BACKEND", "local_file").lower()
_SCHEDULER_ENABLED  = os.getenv("SCHEDULER_ENABLED", "false" if _IS_PROD else "true").lower() == "true"

_json_handler = logging.StreamHandler()
_json_handler.setFormatter(JsonFormatter())
logging.root.setLevel(logging.INFO)
logging.root.handlers = [_json_handler]
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-flight request tracking for graceful shutdown
# ---------------------------------------------------------------------------
_in_flight: int = 0
_in_flight_lock = asyncio.Lock()
_in_flight_zero = asyncio.Event()
_in_flight_zero.set()  # starts at zero — event is set
_shutting_down: bool = False


async def _increment_in_flight() -> None:
    global _in_flight
    async with _in_flight_lock:
        _in_flight += 1
        _in_flight_zero.clear()


async def _decrement_in_flight() -> None:
    global _in_flight
    async with _in_flight_lock:
        _in_flight = max(0, _in_flight - 1)
        if _in_flight == 0:
            _in_flight_zero.set()


async def drain_in_flight_requests() -> None:
    """Wait until all in-flight requests finish (or until the caller times out)."""
    if _in_flight == 0:
        return
    logger.info("Graceful shutdown: waiting for %d in-flight request(s)…", _in_flight)
    await _in_flight_zero.wait()
    logger.info("Graceful shutdown: all in-flight requests completed")


app = FastAPI(
    title="API",
    version="12.4.0",
    docs_url=None if _IS_PROD else "/docs",
    redoc_url=None if _IS_PROD else "/redoc",
    openapi_url=None if _IS_PROD else "/openapi.json",
)


class InFlightMiddleware(BaseHTTPMiddleware):
    """Track in-flight requests and reject new ones once shutdown is signalled."""

    async def dispatch(self, request: Request, call_next):
        if _shutting_down:
            return JSONResponse(
                status_code=503,
                content={"detail": "Server is shutting down"},
                headers={"Retry-After": "10"},
            )
        await _increment_in_flight()
        try:
            return await call_next(request)
        finally:
            await _decrement_in_flight()


class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or _uuid.uuid4().hex
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://accounts.google.com https://apis.google.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "frame-src https://accounts.google.com; "
            "connect-src 'self' https://accounts.google.com https://api.stripe.com; "
            "object-src 'none'; base-uri 'self'"
        )
        if (request.url.scheme == "https"
                or request.headers.get("x-forwarded-proto") == "https"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TraceIDMiddleware)
app.add_middleware(InFlightMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

app.include_router(auth_router)
app.include_router(form_router)
app.include_router(download_router)
app.include_router(stripe_router)
app.include_router(signature_router)
app.include_router(arq_router)
app.include_router(audit_router)
app.include_router(job_router)
app.include_router(admin_router)

if _DEV_ROUTES_ENABLED:
    from routes.dev_routes import router as dev_router
    app.include_router(dev_router)
    logger.warning("DEV_ROUTES_ENABLED=true — dev/test routes are mounted. Never enable in production.")


_WEB_CONCURRENCY = int(os.getenv("WEB_CONCURRENCY", "1"))


def _check_redis_reachable() -> bool:
    """Return True if REDIS_URL is set and Redis responds to PING."""
    from config.settings import REDIS_URL as _REDIS_URL
    if not _REDIS_URL:
        return False
    try:
        import redis as _redis_lib
        r = _redis_lib.from_url(_REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        r.ping()
        return True
    except Exception as _e:
        logger.warning(f"startup: Redis ping failed: {_e}")
        return False


@app.on_event("startup")
async def startup():
    validate_production_config()

    from services.job_queue import validate_queue_backend_for_environment
    validate_queue_backend_for_environment()
    if _IS_PROD and _DEV_ROUTES_ENABLED:
        raise RuntimeError("DEV_ROUTES_ENABLED=true is not allowed in production.")

    # Multi-worker Redis check — rate limiter already raises at import time,
    # but we also verify here to catch any edge cases and log clearly.
    if _WEB_CONCURRENCY > 1:
        if not _check_redis_reachable():
            raise RuntimeError(
                f"WEB_CONCURRENCY={_WEB_CONCURRENCY} requires Redis. "
                "Set REDIS_URL to a reachable Redis instance before starting multiple workers."
            )
        logger.info(f"startup: Redis reachable — distributed state active (WEB_CONCURRENCY={_WEB_CONCURRENCY})")
    else:
        logger.info("startup: WEB_CONCURRENCY=1 — in-process fallbacks are safe")

    # Initialize asyncpg connection pool
    await create_pool()
    logger.info("Database pool created (asyncpg)")

    # Run DDL migrations
    try:
        await init_db()
    except Exception as _e:
        logger.warning(f"DB init failed (non-fatal): {_e}")

    # Create audit tables
    try:
        from services.audit_service import init_audit_tables
        await init_audit_tables()
    except Exception as _e:
        logger.warning(f"Audit table init failed (non-fatal): {_e}")

    # Encrypt any plaintext signature_data rows (idempotent — safe to run every boot)
    try:
        from scripts.encrypt_signature_data import run_migration
        await run_migration()
    except Exception as _e:
        logger.warning(f"signature_data migration failed (non-fatal): {_e}")

    if _SCHEDULER_ENABLED:
        start_scheduler()
    else:
        logger.info(
            "Scheduler disabled (SCHEDULER_ENABLED=false). "
            "Run a dedicated scheduler process with SCHEDULER_ENABLED=true."
        )


@app.on_event("shutdown")
async def shutdown():
    global _shutting_down
    _shutting_down = True
    logger.info("Shutdown signal received — stopping new request acceptance")

    try:
        await asyncio.wait_for(drain_in_flight_requests(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning(
            "Graceful shutdown timed out after 30s with %d request(s) still in-flight",
            _in_flight,
        )

    if _SCHEDULER_ENABLED:
        stop_scheduler()
    await close_pool()
    logger.info("Database pool closed")


def _handle_sigterm(signum, frame) -> None:
    """SIGTERM handler: signal the app to begin graceful shutdown."""
    logger.info("SIGTERM received — initiating graceful shutdown")
    # Raise SystemExit so uvicorn's lifespan triggers the shutdown event
    raise SystemExit(0)


# Register SIGTERM handler so cloud/container orchestrators trigger graceful drain
signal.signal(signal.SIGTERM, _handle_sigterm)


@app.get("/")
def home():
    return {"message": "API v12.4.0", "status": "operational"}


@app.get("/api/health")
async def health():
    try:
        async with get_pool().acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "healthy"}
    except Exception as e:
        logger.exception("Health check failed")
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(e)})
