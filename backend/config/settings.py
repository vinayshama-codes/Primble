import asyncio
import logging
import os

import httpx
import stripe
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL          = os.getenv("DATABASE_URL", "")
SECRET_KEY            = os.getenv("SECRET_KEY", "")
GOOGLE_CLIENT_ID      = os.getenv("GOOGLE_CLIENT_ID", "")
FRONTEND_URL          = os.getenv("FRONTEND_URL", "http://localhost:5173")
REDIS_URL             = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_BILLING_PORTAL_URL = os.getenv("STRIPE_BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/")
OCR_PROVIDER              = os.getenv("OCR_PROVIDER", "easyocr").lower()
ENABLE_ASYNC_PROCESSING   = os.getenv("ENABLE_ASYNC_PROCESSING", "false").lower() == "true"
SESSION_TTL_H             = int(os.getenv("SESSION_TTL_H", "8"))  # session lifetime in hours

_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
_env         = os.getenv("ENVIRONMENT", "development").lower()

if _raw_origins.strip():
    ALLOWED_ORIGINS: list = [o.strip() for o in _raw_origins.split(",") if o.strip()]
elif _env == "production":
    raise RuntimeError(
        "ALLOWED_ORIGINS env var must be set in production. "
        "Example: ALLOWED_ORIGINS=https://app.acordly.ai"
    )
else:
    ALLOWED_ORIGINS = list({FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"})

MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
MAX_FILES_PER_UPLOAD  = int(os.getenv("MAX_FILES_PER_UPLOAD", "10"))

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

SOFT_BUFFER_PCT    = 0.05
STRIPE_CURRENCY    = "usd"
STRIPE_YEARLY_AMOUNT = 30000

PLANS = {
    "essentials": {
        "monthly": {"amount": 5900,   "interval": "month", "packages": 50,   "overage_rate": 175},
        "annual":  {"amount": 47400,  "interval": "year",  "packages": 600,  "overage_rate": 175},
    },
    "professional": {
        "monthly": {"amount": 12900,  "interval": "month", "packages": 100,  "overage_rate": 150},
        "annual":  {"amount": 95400,  "interval": "year",  "packages": 1200, "overage_rate": 150},
    },
    "business": {
        "monthly": {"amount": 44900,  "interval": "month", "packages": 400,  "overage_rate": 125},
        "annual":  {"amount": 399000, "interval": "year",  "packages": 4800, "overage_rate": 125},
    },
    "enterprise": {
        "monthly": {"amount": 0, "interval": "month", "packages": 0, "overage_rate": 0},
        "annual":  {"amount": 0, "interval": "year",  "packages": 0, "overage_rate": 0},
    },
}

BASE_DIR          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR        = os.path.join(BASE_DIR, "tmp")
TEMPLATE_DIR      = os.path.join(BASE_DIR, "templates")
FORMS_DB_DIR      = os.path.join(BASE_DIR, "forms_database")
FORMS_INDEX       = os.path.join(FORMS_DB_DIR, "forms_index.json")
FORMS_SCHEMAS_DIR = os.path.join(BASE_DIR, "forms_schemas")

SUPPORTED_IMG = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FORMS_SCHEMAS_DIR, exist_ok=True)

ADMIN_EMAILS: set = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

DEV_ROUTES_ENABLED: bool = os.getenv("DEV_ROUTES_ENABLED", "false").lower() == "true"

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

_llm_secret_key = "OPENAI_API_KEY"
_llm_secret_val = os.getenv(_llm_secret_key, "")

_REQUIRED_PRODUCTION_SECRETS = {
    "DATABASE_URL":           DATABASE_URL,
    # SECRET_KEY removed: it is read from env but never consumed by any application
    # code (no JWT signing, no HMAC, no session middleware uses it).  Validating an
    # unused secret creates false security assurance.  If a signing key is needed in
    # future, wire it explicitly at that point and re-add here.
    "STRIPE_SECRET_KEY":      os.getenv("STRIPE_SECRET_KEY", ""),
    "STRIPE_WEBHOOK_SECRET":  STRIPE_WEBHOOK_SECRET,
    "GOOGLE_CLIENT_ID":       GOOGLE_CLIENT_ID,
    _llm_secret_key:          _llm_secret_val,
    "FIELD_ENCRYPTION_KEY":   os.getenv("FIELD_ENCRYPTION_KEY", ""),
}


def validate_production_config() -> None:
    """Raise RuntimeError listing every missing required secret. Call at app startup."""
    if _env != "production":
        return
    missing = [k for k, v in _REQUIRED_PRODUCTION_SECRETS.items() if not v]
    if missing:
        raise RuntimeError(
            "Missing required environment variables for production: "
            + ", ".join(missing)
        )
    if DEV_ROUTES_ENABLED and not ADMIN_EMAILS:
        raise RuntimeError(
            "Production misconfiguration: DEV_ROUTES_ENABLED requires ADMIN_EMAILS to be set."
        )
    if not ADMIN_EMAILS:
        raise RuntimeError(
            "ADMIN_EMAILS must be set in production. "
            "Admin-gated endpoints will reject all requests without this. "
            "Set ADMIN_EMAILS=email1@example.com,email2@example.com in your .env"
        )
    from urllib.parse import urlparse as _urlparse
    _parsed = _urlparse(FRONTEND_URL)
    if _parsed.scheme != "https":
        raise RuntimeError(
            f"FRONTEND_URL must use https:// in production. Got: {FRONTEND_URL!r}"
        )


if not os.getenv("OPENAI_API_KEY"):
    logger.warning("OPENAI_API_KEY not set — all LLM calls will fail.")


# ASYNC-SAFE
async def groq_chat(
    model: str,
    messages: list,
    temperature: float = 0,
    max_tokens: int = 4096,
    _retries: int = 4,
) -> str:
    """OpenAI LLM wrapper. Name kept for backwards compatibility with callers."""
    return await _openai_chat(model, messages, temperature, max_tokens, _retries)


# ASYNC-SAFE
async def _claude_chat(
    model: str,
    messages: list,
    temperature: float,
    max_tokens: int,
    _retries: int,
) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        http_client=httpx.AsyncClient(timeout=30.0),
    )
    last_ex = None
    for attempt in range(_retries + 1):
        try:
            r = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            return (r.content[0].text or "").strip()
        except Exception as ex:
            last_ex = ex
            status = getattr(ex, "status_code", None)
            if attempt < _retries and status in (429, 500, 502, 503, 529):
                wait = 2 ** attempt
                logger.warning(
                    f"Claude {status} on attempt {attempt+1}, retrying in {wait}s: {ex}"
                )
                await asyncio.sleep(wait)  # non-blocking
            else:
                break
    raise last_ex


# ASYNC-SAFE
async def _openai_chat(
    model: str,
    messages: list,
    temperature: float,
    max_tokens: int,
    _retries: int,
) -> str:
    import openai as _openai
    client = _openai.AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        http_client=httpx.AsyncClient(timeout=30.0),
    )
    last_ex = None
    for attempt in range(_retries + 1):
        try:
            r = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as ex:
            last_ex = ex
            status = getattr(ex, "status_code", None)
            if attempt < _retries and status in (429, 500, 502, 503):
                wait = 2 ** attempt
                logger.warning(
                    f"OpenAI {status} on attempt {attempt+1}, retrying in {wait}s: {ex}"
                )
                await asyncio.sleep(wait)  # non-blocking
            else:
                break
    raise last_ex
