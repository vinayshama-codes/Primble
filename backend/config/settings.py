import os
import time
import logging
import stripe
from groq import Groq
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL          = os.getenv("DATABASE_URL", "")
GOOGLE_CLIENT_ID      = os.getenv("GOOGLE_CLIENT_ID", "")
FRONTEND_URL          = os.getenv("FRONTEND_URL", "http://localhost:5173")
REDIS_URL             = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_BILLING_PORTAL_URL = os.getenv("STRIPE_BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/")
OCR_PROVIDER          = os.getenv("OCR_PROVIDER", "easyocr").lower()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
groq_client    = Groq(api_key=os.getenv("GROQ_API_KEY"))

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


def groq_chat(model: str, messages: list, temperature: float = 0, max_tokens: int = 4096,
              _retries: int = 2) -> str:
    """
    Provider-dispatching LLM wrapper. Controlled by LLM_PROVIDER env var.

    groq  (default) — uses GROQ_API_KEY
    claude          — uses ANTHROPIC_API_KEY; pass a claude-* model name
    openai          — uses OPENAI_API_KEY; pass a gpt-* model name

    The function is named groq_chat for backwards compatibility — all callers
    use this name. Switching providers requires only changing LLM_PROVIDER.
    """
    if _LLM_PROVIDER == "claude":
        return _claude_chat(model, messages, temperature, max_tokens, _retries)
    if _LLM_PROVIDER == "openai":
        return _openai_chat(model, messages, temperature, max_tokens, _retries)
    return _groq_chat(model, messages, temperature, max_tokens, _retries)


def _groq_chat(model: str, messages: list, temperature: float, max_tokens: int,
               _retries: int) -> str:
    last_ex = None
    for attempt in range(_retries + 1):
        try:
            r = groq_client.chat.completions.create(
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
                logger.warning(f"Groq {status} on attempt {attempt+1}, retrying in {wait}s: {ex}")
                time.sleep(wait)
            else:
                break
    raise last_ex


def _claude_chat(model: str, messages: list, temperature: float, max_tokens: int,
                 _retries: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    last_ex = None
    for attempt in range(_retries + 1):
        try:
            r = client.messages.create(
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
                logger.warning(f"Claude {status} on attempt {attempt+1}, retrying in {wait}s: {ex}")
                time.sleep(wait)
            else:
                break
    raise last_ex


def _openai_chat(model: str, messages: list, temperature: float, max_tokens: int,
                 _retries: int) -> str:
    import openai as _openai
    client = _openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    last_ex = None
    for attempt in range(_retries + 1):
        try:
            r = client.chat.completions.create(
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
                logger.warning(f"OpenAI {status} on attempt {attempt+1}, retrying in {wait}s: {ex}")
                time.sleep(wait)
            else:
                break
    raise last_ex