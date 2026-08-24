import asyncio
import logging
import os

import httpx
import stripe
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load backend/.env by its OWN path, never by working directory. A bare
# load_dotenv() resolves from the CWD, so a server started from the repo root
# silently loaded NOTHING - measured 2026-08-14: every .env setting fell back
# to its default (the dec-index purge ran with PURGE_DEC_INDEX_AFTER_GENERATION
# printed as =0 in the file, and the OpenAI key was coming from the Windows
# user environment, which is what hid the failure). The plain call stays as a
# second pass so a genuinely CWD-local .env (e.g. a deploy override) still
# wins nothing away: override=False everywhere, real environment always wins.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
load_dotenv()

DATABASE_URL          = os.getenv("DATABASE_URL", "")
SECRET_KEY            = os.getenv("SECRET_KEY", "")
GOOGLE_CLIENT_ID      = os.getenv("GOOGLE_CLIENT_ID", "")
FRONTEND_URL          = os.getenv("FRONTEND_URL", "http://localhost:5173")
REDIS_URL             = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_BILLING_PORTAL_URL = os.getenv("STRIPE_BILLING_PORTAL_URL", "https://billing.stripe.com/p/login/")
OCR_PROVIDER              = os.getenv("OCR_PROVIDER", "google").lower()
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

_dev_origin_regex = (
    r"^https?://("
    r"localhost|127\.0\.0\.1|0\.0\.0\.0|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
    r")(?::\d+)?$"
)
CORS_ALLOW_ORIGIN_REGEX = (
    os.getenv("CORS_ALLOW_ORIGIN_REGEX", "").strip()
    or (None if _env == "production" else _dev_origin_regex)
)

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
FORMS_ALIASES_DIR = os.path.join(BASE_DIR, "forms_aliases")

SUPPORTED_IMG = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FORMS_SCHEMAS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Permanently-enabled pipeline features.
#
# The seven flags below are part of the shipped pipeline and are enabled in
# code, NOT via the environment - so no deployment has to set them and no
# environment can accidentally turn them off. The legacy "off" paths they used
# to guard are retained in the call sites only as import-failure fallbacks.
# ---------------------------------------------------------------------------

# Alias-based deterministic stamping (Pass 1.5 in map_facts_to_form).
# Fields left empty by _ACORD_FIELD_RULES are looked up via the per-form alias
# maps in forms_aliases/ before being sent to GPT, reducing LLM calls.
ENABLE_ALIAS_STAMPING: bool = True

# Combined cross-form gap fill (Stages 4-6 of the extraction architecture).
# /api/select-forms-bulk runs ONE shared LLM gap-fill across the union of
# unmatched fields from ALL selected forms, instead of one GPT call per form.
ENABLE_COMBINED_GAP_FILL: bool = True

# Display canonicalization (Beta Report Sec 5 follow-up / Figure 26 trust
# feedback). When true, values are cleaned to a consistent DISPLAY format before
# being stamped onto the generated PDF (dates -> MM/DD/YYYY, street suffixes
# abbreviated, currency grouped, state -> 2-letter, casing standardized) while
# PRESERVING all content (entity suffix, unit number, ZIP+4). The raw value
# stays in the fact envelope. This is NON-destructive and distinct from the
# comparison normalizer in services/normalization.py.
ENABLE_DISPLAY_CANONICALIZATION: bool = True

# Form-level field QA (Figure 26 client feedback). Every mapped ACORD field is
# checked against its source fact + confidence threshold after generation;
# fields that fail (empty-required, or stamped value disagrees with the source
# fact) or need review (AI-inferred) are surfaced in the existing pre-download
# review so the producer sees them before a clean download. Advisory only - it
# never blocks the download or alters a value.
ENABLE_FIELD_QA: bool = True

# Note: field-mapping integrity (Figure 33 client feedback - carrier/policy data
# mapped into an insured/owner field) has no feature flag. It always runs after
# form generation (services/field_mapping_integrity.py, invoked via
# audit_service.run_and_log_field_mapping_check) and surfaces findings as an
# advisory warning on the pre-download and post-download screens. It never
# blocks the download.

# Full-field cross-document reconciliation (Beta Report Sec 4.3 "and similar
# fields" -> generalized to every field, per client). The underwriting
# consistency picker covers EVERY scalar fact that disagrees across documents,
# not just the curated set - so no field is silently merged. Auto-discovered
# fields are non-blocking (never a hard stop or a generation block) and use the
# shared normalizer, so formatting-only differences never surface.
ENABLE_FULL_FIELD_RECONCILIATION: bool = True

# Evidence-gated fill for narrative answer fields (Figure 30 client feedback).
# Free-text "…Explanation" answers produced by the gap-fill LLM are stamped ONLY
# if the model marked them as copied from the document text (raw_text_sourced).
# Inferred/boilerplate answers are dropped and left blank so the field becomes a
# client/producer question instead of being over-filled.
ENABLE_EVIDENCE_GATED_FILL: bool = True

# ACORD 101 overflow routing (Figure 29 client feedback). Oversized
# operations/classification narrative that exceeds a form field's practical
# capacity is ALSO routed in full to the ACORD 101 "Additional Remarks" section
# (lossless — the originating form field is never truncated), and the ACORD 101
# RemarkText fields are stamped deterministically from the remarks fact instead
# of relying on the gap-fill LLM.
ENABLE_ACORD101_OVERFLOW: bool = True

# Producer-entered answers on the recommendation cards (Fig 13). When true, the
# "Submit" action on a recommendation writes the typed value into the session as
# a producer-provenance fact and re-runs the SQS / cross-form rules, instead of
# only dismissing the card. Server-side kill switch; the "Dismiss" waiver path is
# unaffected either way. Default on (requested behaviour, no client-side flag
# plumbing); set ENABLE_PRODUCER_ANSWERS=false to fall back to dismiss-only.
ENABLE_PRODUCER_ANSWERS: bool = os.getenv("ENABLE_PRODUCER_ANSWERS", "true").lower() == "true"

# Bulk schedule capture (Figure 15 client feedback: "many vehicle detail
# questions"). When true, repeating-row ACORD fields (vehicles, drivers,
# locations, class codes, loss runs, ...) collapse into ONE questionnaire item
# per schedule, rendered as an editable table with CSV/XLSX import, row-level
# validation and duplicate detection — instead of one ordinal-labelled card per
# field ("141th vehicle"). Default ON because the prior behaviour is the
# reported defect, not a working fallback; set ENABLE_SCHEDULE_CAPTURE=false to
# restore the legacy per-field questions.
ENABLE_SCHEDULE_CAPTURE: bool = os.getenv("ENABLE_SCHEDULE_CAPTURE", "true").lower() == "true"

# Client questionnaire answer vs source document (V1 plan C1 F7, client rule
# 1.5 "Client Answer Conflicts With Source: do not automatically overwrite the
# source value. Create a conflict and route it to the producer."). When true, an
# ARQ answer that materially DISAGREES with a value the documents state is held
# as a candidate and surfaced in the Data Consistency picker with source
# "Client questionnaire" instead of overwriting the fact and re-stamping every
# form; the producer picks. An answer that AGREES with the source, or fills a
# blank, applies immediately exactly as before. Server-side kill switch; set
# ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING=false to restore overwrite-on-answer.
ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING: bool = (
    os.getenv("ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING", "true").lower() == "true")


ADMIN_EMAILS: set = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# ACORD license confirmation wording version (Figure 25 requirement).
# Bump this whenever the legal text in the AcordModal license-confirmation
# copy changes. Users who confirmed under an older version are treated as
# unconfirmed (see is_acord_license_current below) and are re-prompted on
# their next download. The value is never shown to users or typed by them -
# it is a developer-set label for the exact wording, like a document
# revision number.
ACORD_LICENSE_VERSION = os.getenv("ACORD_LICENSE_VERSION", "2026-07-v1")

DEV_ROUTES_ENABLED: bool = os.getenv("DEV_ROUTES_ENABLED", "false").lower() == "true"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()  # "openai" or "claude"
LLM_MODEL    = os.getenv("LLM_MODEL",    "gpt-4.1-nano")

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
    supported_ocr = {"google", "google_vision", "vision"}
    if OCR_PROVIDER not in supported_ocr:
        raise RuntimeError(
            "Unsupported OCR_PROVIDER for this deployment: "
            f"{OCR_PROVIDER!r}. Supported values: google, google_vision, vision."
        )
    if not (
        os.getenv("GOOGLE_VISION_API_KEY")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    ):
        raise RuntimeError(
            "Google Vision OCR requires GOOGLE_VISION_API_KEY, "
            "GOOGLE_APPLICATION_CREDENTIALS, or GOOGLE_APPLICATION_CREDENTIALS_JSON "
            "in production."
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
def _uses_max_completion_tokens(model: str) -> bool:
    """Return True for models that require max_completion_tokens instead of max_tokens.

    OpenAI o-series and gpt-5.x models reject max_tokens with HTTP 400.
    All other models (gpt-4*, gpt-3.5*) accept max_tokens.
    """
    m = model.lower()
    return m.startswith("o1") or m.startswith("o3") or m.startswith("o4") or "gpt-5" in m


async def _openai_chat(
    model: str,
    messages: list,
    temperature: float,
    max_tokens: int,
    _retries: int,
) -> str:
    import openai as _openai
    from utils.llm_limiter import get_llm_semaphore
    _timeout = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
    client = _openai.AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        http_client=httpx.AsyncClient(timeout=_timeout),
    )
    # Global concurrency cap smooths bursts under OpenAI Tier 1 RPM limits.
    # Slot is acquired per-attempt so it is released BEFORE the retry sleep,
    # letting other callers proceed instead of freezing all slots during backoff.
    #
    # Parameter name differs by model family:
    #   gpt-4*, gpt-3.5* → max_tokens
    #   o1/o3/o4, gpt-5* → max_completion_tokens  (max_tokens returns HTTP 400)
    token_param = "max_completion_tokens" if _uses_max_completion_tokens(model) else "max_tokens"
    last_ex = None
    for attempt in range(_retries + 1):
        try:
            async with get_llm_semaphore():
                r = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    **{token_param: max_tokens},
                )
            # Token accounting — see improving-ll.md. `cache_pct` is the share of
            # input tokens served from OpenAI's automatic prefix cache (billed at
            # ~10%). Extraction prompts are already prefix-first
            # (_EXTRACT_PROMPT_PREFIX leads every call), so this should read high
            # across a multi-chunk document. Never allowed to break a call.
            try:
                _u = getattr(r, "usage", None)
                if _u is not None:
                    _pt = int(getattr(_u, "prompt_tokens", 0) or 0)
                    _cached = int(getattr(
                        getattr(_u, "prompt_tokens_details", None), "cached_tokens", 0) or 0)
                    logger.info(
                        "LLM_SPEND stage=extraction form=- in=%d cached=%d out=%d cache_pct=%d",
                        _pt, _cached, int(getattr(_u, "completion_tokens", 0) or 0),
                        (100 * _cached // _pt) if _pt else 0,
                    )
            except Exception:                                  # pragma: no cover
                pass
            return (r.choices[0].message.content or "").strip()
        except Exception as ex:
            last_ex = ex
            status = getattr(ex, "status_code", None)
            is_timeout = isinstance(ex, (_openai.APITimeoutError, httpx.TimeoutException))
            if attempt < _retries and (status in (429, 500, 502, 503) or is_timeout):
                wait = _retry_wait_seconds(ex, status, attempt)
                logger.warning(
                    "OpenAI %s on attempt %d, retrying in %ss: %s",
                    "timeout" if is_timeout else status, attempt + 1, wait, ex,
                )
                await asyncio.sleep(wait)  # non-blocking; slot NOT held during sleep
            else:
                break
    raise last_ex


# ── 429 IS NOT A TRANSIENT ERROR - IT IS A CLOCK (2026-08-23) ────────────────
# The backoff used to be `2 ** attempt` for every retryable status: 1s, 2s, 4s,
# 8s, then give up. That is right for a 500 or a timeout, which clear in
# milliseconds. It is WRONG for a 429, because a tokens-per-minute limit clears
# on a SIXTY-SECOND window - so the whole retry budget expired in 15 seconds and
# the call raised while the limit still had 45 seconds to run.
#
# WHAT THAT COST, measured. The declarations-index pass makes ~39 calls right
# behind the main extraction's 14. On a cold cache those two bursts together
# exceed the TPM ceiling, every index call took a 429, every one exhausted its
# 15 seconds and raised, and `_harvest_dec_index` caught them all and returned
# an empty list. Three consecutive live runs produced ZERO declarations entries
# and nothing looked wrong. The same code with a warm cache - no first burst,
# no 429 - returns 2,215 entries from four chunks.
#
# Two changes, both narrow:
#   1. OpenAI states the wait in a `Retry-After` header. We ignored it. Now it
#      wins outright when present - the server knows better than any formula.
#   2. Absent that header, a 429 gets a schedule that actually crosses a minute
#      (5s, 15s, 30s, 60s) instead of one that expires inside it. Everything
#      else keeps the original 1/2/4/8 exactly.
#
# Worst case a rate-limited call now waits ~110s across its retries instead of
# 15s. That is the correct trade: extraction is a background job, and a slow
# answer beats a silent empty one. Cap kept so nothing can hang indefinitely.
_LLM_RATE_LIMIT_BACKOFF = (5, 15, 30, 60)
_LLM_RETRY_AFTER_MAX = float(os.getenv("LLM_RETRY_AFTER_MAX", "90"))


def _retry_wait_seconds(ex: Exception, status: object, attempt: int) -> float:
    """Seconds to wait before the next attempt.

    `Retry-After` first (the server's own instruction, capped so a hostile or
    mistaken header cannot stall the pipeline), then a rate-limit-aware schedule
    for 429, then the original exponential backoff for everything else.
    """
    try:
        resp = getattr(ex, "response", None)
        hdr = getattr(resp, "headers", None)
        raw = hdr.get("retry-after") if hdr is not None else None
        if raw:
            return max(1.0, min(_LLM_RETRY_AFTER_MAX, float(str(raw).strip())))
    except Exception:                                      # noqa: BLE001
        pass                                               # header absent or unparseable
    if status == 429:
        idx = min(attempt, len(_LLM_RATE_LIMIT_BACKOFF) - 1)
        return float(_LLM_RATE_LIMIT_BACKOFF[idx])
    return float(2 ** attempt)
