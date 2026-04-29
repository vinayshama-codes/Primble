import logging
import os
import uuid as _uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Sentry must be initialised before any application code runs.
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
        # Never send PII (form data, emails, user content)
        send_default_pii=False,
    )

from config.database import get_db
from config.settings import ALLOWED_ORIGINS, MAX_UPLOAD_SIZE_BYTES  # noqa: F401
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

_DEV_ROUTES_ENABLED   = os.getenv("DEV_ROUTES_ENABLED", "false").lower() == "true"
_ENVIRONMENT          = os.getenv("ENVIRONMENT", "development").lower()
_IS_PROD              = _ENVIRONMENT == "production"
_JOB_QUEUE_BACKEND    = os.getenv("JOB_QUEUE_BACKEND", "local_file").lower()
_SCHEDULER_ENABLED    = os.getenv("SCHEDULER_ENABLED", "false" if _IS_PROD else "true").lower() == "true"

_json_handler = logging.StreamHandler()
_json_handler.setFormatter(JsonFormatter())
logging.root.setLevel(logging.INFO)
logging.root.handlers = [_json_handler]
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

app = FastAPI(title="API", version="12.4.0")


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


@app.on_event("startup")
async def startup():
    # Production guards — refuse to start with unsafe configuration.
    if _IS_PROD and _JOB_QUEUE_BACKEND in ("local_file", "memory"):
        raise RuntimeError(
            f"JOB_QUEUE_BACKEND='{_JOB_QUEUE_BACKEND}' is not allowed in production. "
            "Use JOB_QUEUE_BACKEND=db or JOB_QUEUE_BACKEND=sqs."
        )
    if _IS_PROD and _DEV_ROUTES_ENABLED:
        raise RuntimeError("DEV_ROUTES_ENABLED=true is not allowed in production.")

    if _SCHEDULER_ENABLED:
        start_scheduler()
    else:
        logger.info(
            "Scheduler disabled (SCHEDULER_ENABLED=false). "
            "Run a dedicated scheduler process with SCHEDULER_ENABLED=true."
        )

    try:
        from services.audit_service import init_audit_tables
        init_audit_tables()
    except Exception as _e:
        logger.warning(f"Audit table init failed (non-fatal): {_e}")


@app.on_event("shutdown")
async def shutdown():
    if _SCHEDULER_ENABLED:
        stop_scheduler()


@app.get("/")
def home():
    return {"message": "API v12.4.0", "status": "operational"}


@app.get("/api/health")
def health():
    try:
        conn     = get_db()
        cur      = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return {"status": "healthy"}
    except Exception:
        logger.exception("Health check failed")
        return {"status": "error"}