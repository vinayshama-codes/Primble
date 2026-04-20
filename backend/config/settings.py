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


def groq_chat(model: str, messages: list, temperature: float = 0, max_tokens: int = 4096,
              _retries: int = 2) -> str:
    """
    Thin wrapper around groq_client.chat.completions.create with automatic
    retry on transient 5xx errors (Groq occasionally returns 500).
    Returns the raw content string; raises on permanent failure.
    """
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
                wait = 2 ** attempt  # 1s, 2s
                logger.warning(f"Groq {status} on attempt {attempt+1}, retrying in {wait}s: {ex}")
                time.sleep(wait)
            else:
                break
    raise last_ex