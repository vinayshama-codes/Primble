import asyncio
import logging
import os

import httpx
import stripe
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL          = os.getenv("DATABASE_URL", "")
GOOGLE_CLIENT_ID      = os.getenv("GOOGLE_CLIENT_ID", "")
FRONTEND_URL          = os.getenv("FRONTEND_URL", "http://localhost:5173")
REDIS_URL             = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_BILLING_PORTAL_URL = os.getenv("STRIPE_BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/")
OCR_PROVIDER              = os.getenv("OCR_PROVIDER", "easyocr").lower()
ENABLE_ASYNC_PROCESSING   = os.getenv("ENABLE_ASYNC_PROCESSING", "false").lower() == "true"

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

# Sync Groq client — kept for use inside executor threads (ocr_service, legacy paths)
from groq import Groq, AsyncGroq
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Async Groq client with 30-second HTTP timeout — used from async code
_groq_async = AsyncGroq(
    api_key=os.getenv("GROQ_API_KEY"),
    http_client=httpx.AsyncClient(timeout=30.0),
)

SOFT_BUFFER_PCT    = 0.05
STRIPE_CURRENCY    = "usd"
STRIPE_YEARLY_AMOUNT = 30000

PLANS = {
    "lite": {
        "monthly": {"amount": 4900,  "interval": "month", "packages": 0, "overage_rate": 0},
        "annual":  {"amount": 39900, "interval": "year",  "packages": 0, "overage_rate": 0},
    },
    "essentials": {
        "monthly": {"amount": 12900,  "interval": "month", "packages": 100,  "overage_rate": 150},
        "annual":  {"amount": 118800, "interval": "year",  "packages": 1200, "overage_rate": 150},
    },
    "professional": {
        "monthly": {"amount": 44900,  "interval": "month", "packages": 400,  "overage_rate": 125},
        "annual":  {"amount": 478800, "interval": "year",  "packages": 4800, "overage_rate": 125},
    },
    "enterprise": {
        "monthly": {"amount": 119900, "interval": "month", "packages": 0, "overage_rate": 0},
        "annual":  {"amount": 119900, "interval": "month", "packages": 0, "overage_rate": 0},
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

_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()


# ASYNC-SAFE
async def groq_chat(
    model: str,
    messages: list,
    temperature: float = 0,
    max_tokens: int = 4096,
    _retries: int = 2,
) -> str:
    """
    Async provider-dispatching LLM wrapper. Controlled by LLM_PROVIDER env var.
    All retry waits use asyncio.sleep — never blocks the event loop.
    """
    if _LLM_PROVIDER == "claude":
        return await _claude_chat(model, messages, temperature, max_tokens, _retries)
    if _LLM_PROVIDER == "openai":
        return await _openai_chat(model, messages, temperature, max_tokens, _retries)
    return await _groq_chat(model, messages, temperature, max_tokens, _retries)


# ASYNC-SAFE
async def _groq_chat(
    model: str,
    messages: list,
    temperature: float,
    max_tokens: int,
    _retries: int,
) -> str:
    last_ex = None
    for attempt in range(_retries + 1):
        try:
            r = await _groq_async.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (r.choices[0].message.content or "").strip()
        except Exception as ex:
            last_ex = ex
            status = getattr(ex, "status_code", None)
            if attempt < _retries and status in (429, 500, 502, 503, 504):
                wait = 2 ** attempt
                logger.warning(
                    f"Groq {status} on attempt {attempt+1}, retrying in {wait}s: {ex}"
                )
                await asyncio.sleep(wait)  # non-blocking
            else:
                break
    raise last_ex


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
