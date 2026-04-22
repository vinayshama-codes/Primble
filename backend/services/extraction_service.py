import asyncio
import collections
import concurrent.futures as _cf
import hashlib
import json
import logging
import math
import os
import random
import re
import threading
import time
from typing import List, Optional, Tuple, Dict, Any

from config.settings import groq_chat

logger = logging.getLogger(__name__)

# ── Cache versioning (Fix 3) ──────────────────────────────────────────────────
PROMPT_VERSION = "v2"
SCHEMA_VERSION = "v2"

# ── Model context config ──────────────────────────────────────────────────────
_MODEL_CHUNK_CHARS: Dict[str, int] = {
    "groq":    2_000,
    "claude": 28_000,
    "openai": 40_000,
}
ACTIVE_MODEL = os.getenv("LLM_PROVIDER", "groq").lower()

_MAX_TOKENS_PER_DOC = int(os.getenv("ACORDLY_MAX_DOC_TOKENS", "500000"))
_CHARS_PER_TOKEN    = 4


def get_chunk_size(model: str = ACTIVE_MODEL) -> int:
    return _MODEL_CHUNK_CHARS.get(model, _MODEL_CHUNK_CHARS["groq"])


# ── Token estimation (tiktoken with char/4 fallback) ─────────────────────────
try:
    import tiktoken as _tiktoken
    _TK_ENC = _tiktoken.get_encoding("cl100k_base")
    logger.info("extraction_service: tiktoken loaded (cl100k_base)")
except Exception as _tk_err:
    _TK_ENC = None
    logger.warning(
        f"extraction_service: tiktoken unavailable ({_tk_err}) — using char/4 fallback"
    )


def estimate_tokens(text: str) -> int:
    if _TK_ENC is not None:
        try:
            return len(_TK_ENC.encode(text))
        except Exception:
            pass
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


# ── Extraction schema ─────────────────────────────────────────────────────────
_EXTRACT_SCHEMA = (
    '"facts": {\n'
    '  "producer_name": string or null, "applicant_name": string or null,\n'
    '  "dba_name": string or null, "mailing_address": string or null,\n'
    '  "physical_address": string or null, "contact_name": string or null,\n'
    '  "contact_phone": string or null, "contact_email": string or null,\n'
    '  "fein": string or null, "entity_type": string or null,\n'
    '  "effective_date": string or null, "expiration_date": string or null,\n'
    '  "policy_number": string or null, "lines_of_business": [],\n'
    '  "total_revenue": string or null, "total_payroll": string or null,\n'
    '  "num_employees": string or null, "locations": [string],\n'
    '  "operations_description": string or null, "prior_carrier": string or null,\n'
    '  "naics_code": string or null, "sic_code": string or null,\n'
    '  "years_in_business": string or null,\n'
    '  "gl_limits": string or null, "gl_aggregate": string or null,\n'
    '  "gl_each_occurrence": string or null,\n'
    '  "gl_class_codes_by_location": [{"location": string, "codes": [string]}],\n'
    '  "gl_deductible": string or null, "gl_form_type": string or null,\n'
    '  "retro_date": string or null,\n'
    '  "additional_named_insureds": [],\n'
    '  "property_building_value": string or null, "property_bpp_value": string or null,\n'
    '  "construction_type": string or null, "occupancy_type": string or null,\n'
    '  "year_built": string or null, "roof_year": string or null,\n'
    '  "sprinkler_system": string or null, "fire_protection_class": string or null,\n'
    '  "valuation_method": "RCV"|"ACV"|null, "coinsurance_percentage": string or null,\n'
    '  "business_income_limit": string or null, "period_of_restoration": string or null,\n'
    '  "property_deductible_aop": string or null, "property_deductible_wind": string or null,\n'
    '  "property_deductible_earthquake": string or null, "property_deductible_flood": string or null,\n'
    '  "mortgagee_name": string or null, "auto_liability_limit": string or null,\n'
    '  "auto_liability_structure": string or null, "auto_deductible_comp": string or null,\n'
    '  "auto_deductible_collision": string or null, "auto_vin_schedule": [], "auto_garaging_addresses": [],\n'
    '  "wc_payroll": string or null, "wc_payroll_by_state": {}, "wc_class_codes": [],\n'
    '  "wc_xmod": string or null, "wc_xmod_effective_date": string or null,\n'
    '  "wc_officer_exclusions": string or null,\n'
    '  "wc_monopolistic_payroll": {"state": "amount"},\n'
    '  "umbrella_limit": string or null, "umbrella_sir": string or null,\n'
    '  "umbrella_attachment_point": string or null,\n'
    '  "underlying_policies": [{"line": string, "limit": string, "carrier": string, "policy_no": string}],\n'
    '  "employers_liability_limits": string or null,\n'
    '  "percent_subcontracted": string or null,\n'
    '  "contractor_type": string or null, "num_claims": string or null,\n'
    '  "loss_history_years": string or null, "certificate_holder": string or null,\n'
    '  "is_renewal": string or null,\n'
    '  "wc_prior_carrier": string or null,\n'
    '  "wc_payroll_period": string or null,\n'
    '  "auto_drivers": [],\n'
    '  "auto_radius_of_operation": string or null,\n'
    '  "auto_physical_damage_valuation": string or null,\n'
    '  "auto_covered_symbols": [int],\n'
    '  "auto_um_uim_limit": string or null,\n'
    '  "auto_med_pay_limit": string or null,\n'
    '  "auto_hired_nonowned": string or null,\n'
    '  "distance_to_hydrant": string or null,\n'
    '  "fire_department_type": string or null,\n'
    '  "extra_expense_limit": string or null,\n'
    '  "deductible_basis": string or null,\n'
    '  "agreed_value_endorsement": boolean,\n'
    '  "deductible_application": string or null,\n'
    '  "building_ITV_percentage": string or null,\n'
    '  "total_incurred": string or null,\n'
    '  "total_paid": string or null,\n'
    '  "open_claims_count": string or null,\n'
    '  "property_locations": [],\n'
    '  "risk_transfer": {\n'
    '    "additional_insured_required": boolean,\n'
    '    "additional_insured_names": [string],\n'
    '    "primary_noncontributory_required": boolean,\n'
    '    "waiver_of_subrogation_required": boolean,\n'
    '    "certificate_holder_name": string or null,\n'
    '    "loss_payee_name": string or null,\n'
    '    "mortgagee_name": string or null,\n'
    '    "specific_wording_requirements": string or null\n'
    '  }\n'
    '},\n\n'
    '"flags": {\n'
    '  "is_commercial_policy": boolean, "has_general_liability": boolean,\n'
    '  "has_property_coverage": boolean, "has_auto_coverage": boolean,\n'
    '  "has_workers_comp": boolean, "has_umbrella": boolean,\n'
    '  "has_multiple_locations": boolean, "has_loss_history": boolean,\n'
    '  "is_contractor": boolean, "has_certificate_request": boolean,\n'
    '  "is_certificate_doc": boolean, "gl_is_claims_made": boolean,\n'
    '  "auto_has_physical_damage": boolean, "auto_split_limits": boolean,\n'
    '  "auto_has_hired_nonowned": boolean, "auto_has_um_uim": boolean,\n'
    '  "wc_multi_state": boolean, "wc_has_monopolistic_state": boolean,\n'
    '  "property_has_bi_coverage": boolean, "property_has_peril_deductibles": boolean,\n'
    '  "has_additional_insured_requirement": boolean,\n'
    '  "has_waiver_of_subrogation": boolean,\n'
    '  "has_primary_noncontributory": boolean\n'
    '}'
)

_EXTRACT_PROMPT_PREFIX = (
    'You are a carrier-grade insurance document analyzer. Extract every available data point.\n\n'
    'Return ONLY a valid JSON object with exactly these two top-level keys:\n\n'
    + _EXTRACT_SCHEMA
    + '\n\nReturn ONLY the JSON object, no markdown, no extra text.\n\n'
)

# Max realistic context_section length (label + context_prefix up to max_chars//7 tail).
# Max realistic low_conf_note length (label + 40 tokens * ~10 chars).
# These are upper bounds used for prompt overhead calculation — no magic constants.
_CONTEXT_SECTION_HEADER = (
    "\n\nPREVIOUS CONTEXT (reference only — do NOT re-extract from this; "
    "extract ONLY from PRIMARY TEXT below):\n---\n\n---\n"
)
_LOW_CONF_NOTE_HEADER = (
    "\n\nOCR CONFIDENCE WARNING: The following tokens had low OCR confidence. "
    "Apply corrections where context makes the correct value clear:\n"
)
_LOW_CONF_NOTE_MAX_TOKENS = 40 * 12  # 40 tokens * ~12 chars each (conservative)

# Fix 7: dynamic prompt overhead computed from actual component lengths
def _compute_prompt_overhead(model: str = ACTIVE_MODEL) -> int:
    raw = get_chunk_size(model)
    context_max = raw // 7   # max context_prefix tail length
    return (
        len(_EXTRACT_PROMPT_PREFIX)
        + len(_CONTEXT_SECTION_HEADER)
        + context_max
        + len(_LOW_CONF_NOTE_HEADER)
        + _LOW_CONF_NOTE_MAX_TOKENS
    )


# ── OCR confidence ────────────────────────────────────────────────────────────
_OCR_CRITICAL_FIELDS = frozenset({
    "applicant_name", "mailing_address", "fein", "effective_date",
    "expiration_date", "property_building_value", "property_bpp_value",
})
_OCR_STANDARD_FIELDS = frozenset({
    "construction_type", "occupancy_type", "fire_protection_class",
    "year_built", "roof_year",
})
_OCR_THRESHOLD_CRITICAL = 0.90
_OCR_THRESHOLD_STANDARD = 0.80
_OCR_THRESHOLD_DEFAULT  = 0.70

# Fix 11: confusion-map applied ONLY to code/numeric-type fields.
# Free-text fields (names, addresses, descriptions) use plain .lower() to prevent
# false low-confidence flags (e.g. "policy" → "p01icy").
_OCR_CONFUSION_SAFE_FIELDS = frozenset({
    "fein", "policy_number", "naics_code", "sic_code",
    "effective_date", "expiration_date", "retro_date",
    "wc_xmod", "wc_xmod_effective_date",
    "year_built", "roof_year", "fire_protection_class",
    "property_building_value", "property_bpp_value",
    "total_revenue", "total_payroll", "wc_payroll",
    "auto_liability_limit", "umbrella_limit",
})

_OCR_CONFUSION_MAP = str.maketrans({
    "O": "0", "o": "0", "l": "1", "I": "1",
    "S": "5", "Z": "2", "B": "8", "G": "6",
})


def _normalize_for_ocr_check(s: str, field: str = "") -> str:
    """Apply confusion-map normalization ONLY for code/numeric fields. Skip free-text."""
    if field and field not in _OCR_CONFUSION_SAFE_FIELDS:
        return s.lower()
    return s.translate(_OCR_CONFUSION_MAP)


def _ocr_threshold(field_name: str) -> float:
    if field_name in _OCR_CRITICAL_FIELDS:
        return _OCR_THRESHOLD_CRITICAL
    if field_name in _OCR_STANDARD_FIELDS:
        return _OCR_THRESHOLD_STANDARD
    return _OCR_THRESHOLD_DEFAULT


# ── Null normalisation ────────────────────────────────────────────────────────
_NULL_STRINGS = {"null", "none", "n/a", "na", "unknown", ""}


def _fv(facts: dict, key: str, default=None):
    raw = facts.get(key, default)
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    return raw


def _focr(facts: dict, key: str) -> bool:
    raw = facts.get(key)
    if isinstance(raw, dict) and "ocr_confident" in raw:
        return bool(raw["ocr_confident"])
    return True


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, dict):
        if "value" in v:
            inner = str(v["value"]).strip().lower()
            return not inner or inner in _NULL_STRINGS
        return len(v) == 0
    return str(v).strip().lower() in _NULL_STRINGS


# ── Thread-safe in-process LRU cache with TTL (Fix 8) ────────────────────────
_CACHE_TTL      = 86_400   # seconds
_CACHE_MAX_SIZE = 500
_EXTRACT_CACHE: "collections.OrderedDict[str, Tuple[dict, float]]" = collections.OrderedDict()
_CACHE_LOCK     = threading.Lock()   # guards ALL access to _EXTRACT_CACHE


def _lru_get(key: str) -> Optional[dict]:
    with _CACHE_LOCK:
        if key not in _EXTRACT_CACHE:
            return None
        value, ts = _EXTRACT_CACHE[key]
        if time.monotonic() - ts > _CACHE_TTL:
            _EXTRACT_CACHE.pop(key, None)
            return None
        _EXTRACT_CACHE.move_to_end(key)
        return value


def _lru_set(key: str, value: dict) -> None:
    with _CACHE_LOCK:
        if key in _EXTRACT_CACHE:
            _EXTRACT_CACHE.move_to_end(key)
        _EXTRACT_CACHE[key] = (value, time.monotonic())
        while len(_EXTRACT_CACHE) > _CACHE_MAX_SIZE:
            _EXTRACT_CACHE.popitem(last=False)


# ── Redis cache (optional) ────────────────────────────────────────────────────
try:
    import redis as _redis_lib
    from config.settings import REDIS_URL as _REDIS_URL
    _redis = _redis_lib.from_url(
        _REDIS_URL,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )
    _redis.ping()
    logger.info(f"extract_facts: Redis cache connected ({_REDIS_URL})")
except Exception as _redis_init_err:
    logger.warning(
        f"extract_facts: Redis unavailable ({_redis_init_err}) — "
        "in-process LRU cache active (degraded caching mode)"
    )
    _redis = None


def _cache_key(text: str, model: str, ctx_hash: str, lct_hash: str) -> str:
    """
    Fix 3: includes PROMPT_VERSION + SCHEMA_VERSION so any schema/prompt change
    automatically invalidates all existing cache entries.
    Fix (prev): includes ctx_hash + lct_hash to prevent stale hits on same text
    at different positions or with different OCR quality.
    """
    payload = f"pv={PROMPT_VERSION}|sv={SCHEMA_VERSION}|m={model}|ctx={ctx_hash}|lct={lct_hash}|{text}"
    return hashlib.md5(payload.encode(), usedforsecurity=False).hexdigest()


def _cache_get(key: str) -> Optional[dict]:
    if _redis is not None:
        try:
            raw = _redis.get(f"extract:{key}")
            if raw:
                return json.loads(raw)
        except Exception as ex:
            logger.warning(f"Redis get failed, in-process fallback: {ex}")
    return _lru_get(key)


def _cache_set(key: str, value: dict) -> None:
    if _redis is not None:
        try:
            _redis.setex(f"extract:{key}", _CACHE_TTL, json.dumps(value))
            return
        except Exception as ex:
            logger.warning(f"Redis set failed, in-process only: {ex}")
    _lru_set(key, value)


# ── Document-type identification ──────────────────────────────────────────────
DOC_TYPE_KEYWORDS = {
    "dec_page":    ["declarations", "dec page", "policy declarations", "named insured",
                    "policy period", "coverage summary", "insuring agreement", "policy number"],
    "certificate": ["certificate of liability", "certificate of insurance", "acord 25",
                    "certificate holder", "evidence of insurance", "this is to certify"],
    "loss_run":    ["loss run", "loss history", "incurred", "reserve", "paid losses",
                    "claimant", "date of loss"],
    "schedule":    ["schedule of", "vehicle schedule", "equipment schedule",
                    "location schedule", "driver schedule"],
    "quote":       ["quote", "proposal", "indication", "estimated premium", "quoted premium"],
    "application": ["application", "acord 125", "acord 126", "acord 130", "prior application"],
    "endorsement": ["endorsement", "additional insured", "waiver of subrogation", "mortgagee"],
}

_DOC_TYPE_PRIORITY = ["dec_page", "application", "quote", "schedule",
                      "endorsement", "certificate", "loss_run", "unknown"]
_DOC_TYPE_MIN_SCORE = 2


def identify_doc_type(text: str) -> str:
    tl         = text.lower()
    scores     = {dt: sum(1 for kw in kws if kw in tl) for dt, kws in DOC_TYPE_KEYWORDS.items()}
    best_score = max(scores.values())
    if best_score < _DOC_TYPE_MIN_SCORE:
        return "unknown"
    for dt in _DOC_TYPE_PRIORITY:
        if scores.get(dt, 0) == best_score:
            return dt
    return "unknown"


def select_primary_truth(docs: List[dict]) -> dict:
    by_type: Dict[str, dict] = {}
    for d in docs:
        by_type.setdefault(d["doc_type"], d)
    for p in _DOC_TYPE_PRIORITY:
        if p in by_type:
            return by_type[p]
    return docs[0]


# ── Cost guardrail ────────────────────────────────────────────────────────────

def _check_cost_guardrail(text: str, doc_type: str) -> None:
    est = estimate_tokens(text)
    if est > _MAX_TOKENS_PER_DOC:
        raise ValueError(
            f"extract_facts_long: doc_type='{doc_type}' estimated {est:,} tokens "
            f"exceeds ACORDLY_MAX_DOC_TOKENS={_MAX_TOKENS_PER_DOC:,}. "
            "Split the document or raise the env var limit."
        )


# ── Fix 7: Dynamic effective chunk size ───────────────────────────────────────

def _effective_chunk_size(model: str = ACTIVE_MODEL) -> int:
    """
    Raw chunk_size minus dynamically computed prompt overhead.
    Overhead = len(prompt prefix) + len(context section header) + max context tail
               + len(OCR warning header) + max OCR token chars.
    No magic constants — all components measured from actual strings.
    """
    raw      = get_chunk_size(model)
    overhead = _compute_prompt_overhead(model)
    return max(1000, raw - overhead)


# ── Structured fields whitelist (Fix 4) ──────────────────────────────────────
# Only these fact fields may be dicts in the LLM output.
# All others must be string, null, or list. Any other dict → REJECT.
_STRUCTURED_DICT_FIELDS = frozenset({
    "risk_transfer",
    "wc_payroll_by_state",
    "wc_monopolistic_payroll",
})

# List fields in the schema — LLM must return [] not null for these.
_LIST_FIELDS = frozenset({
    "lines_of_business", "locations", "property_locations",
    "auto_vin_schedule", "auto_garaging_addresses", "auto_drivers",
    "gl_class_codes_by_location", "wc_class_codes", "underlying_policies",
    "additional_named_insureds", "auto_covered_symbols",
})


# ── Fix 2: Strict JSON validation ─────────────────────────────────────────────

def _validate_parsed(result: dict, context: str) -> dict:
    """
    Fix 2: require facts AND flags to exist and be dicts. Raise RuntimeError if not.
    Fix 4: enforce structured dict whitelist. Non-whitelisted dict fields → REJECT.

    Pipeline contract: this function sees RAW LLM output scalars only.
    Annotated dicts (containing "value"/"ocr_confident") must NEVER enter here.
    If a field value is a dict with "value" key → it's annotated, which means
    _annotate_facts ran before _validate_parsed — that is a pipeline ordering bug.
    Raise RuntimeError immediately to surface it.
    """
    # Require both top-level keys as dicts — no silent insertion
    for k in ("facts", "flags"):
        if k not in result:
            raise RuntimeError(
                f"_validate_parsed [{context}]: required top-level key '{k}' missing. "
                "LLM output did not include required schema keys."
            )
        if not isinstance(result[k], dict):
            raise RuntimeError(
                f"_validate_parsed [{context}]: '{k}' is {type(result[k]).__name__}, expected dict."
            )

    normalized: dict = {}
    for field, v in result["facts"].items():

        # Detect pipeline ordering violation: annotated dict entered validation
        if isinstance(v, dict) and "ocr_confident" in v:
            raise RuntimeError(
                f"_validate_parsed [{context}]: field={field!r} contains annotated dict "
                "(has 'ocr_confident' key). _annotate_facts must NOT run before _validate_parsed."
            )

        # None → pass through
        if v is None:
            normalized[field] = None
            continue

       
        # List → validate + normalize for known fields
        if isinstance(v, list):

    # 🔥 FIX: normalize locations (list of dict → list of string)
            if field == "locations":
                if all(isinstance(x, dict) for x in v):
                    try:
                        v = [str(list(x.values())[0]).strip() for x in v if x]
                        logger.warning(
                            f"_validate_parsed [{context}]: normalized locations from dict → string list"
                        )
                    except Exception:
                        raise RuntimeError(
                            f"_validate_parsed [{context}]: invalid locations structure"
                        )
        
                elif all(isinstance(x, str) for x in v):
                    pass  # valid
        
                else:
                    raise RuntimeError(
                        f"_validate_parsed [{context}]: locations must be list of strings"
                    )
        
            # you can extend similar normalization for other weak fields later
        
            normalized[field] = v
            continue

        # Dict → only allowed for whitelisted structured fields
        if isinstance(v, dict):
            if field not in _STRUCTURED_DICT_FIELDS:
                raise RuntimeError(
                    f"_validate_parsed [{context}]: field={field!r} returned dict "
                    f"but is not in _STRUCTURED_DICT_FIELDS whitelist. "
                    f"Keys returned: {list(v.keys())}. Rejecting entire result."
                )
            normalized[field] = v
            continue

        # Scalar → coerce to str, normalize nulls
        str_val = str(v).strip()
        if str_val.lower() in _NULL_STRINGS:
            normalized[field] = None
        else:
            normalized[field] = str_val

    result["facts"] = normalized
    return result


# ── Fix 2: Strict JSON parse for extraction output ────────────────────────────

def _safe_json_parse(raw: str, context: str = "") -> dict:
    """
    Parse LLM extraction output. Expects: {"facts": {...}, "flags": {...}}.
    On parse failure: LLM repair (max 2 repair attempts), full raw passed each time.
    After parse: _validate_parsed() enforces strict schema.
    Raises RuntimeError on any failure — never returns empty silently.
    """
    for attempt in range(3):
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.I)
            raw = raw.rstrip("`").strip()
        s = raw.find("{")
        e = raw.rfind("}")
        if s != -1 and e != -1:
            candidate = raw[s : e + 1]
            try:
                result = json.loads(candidate)
                if not isinstance(result, dict):
                    raise RuntimeError(
                        f"_safe_json_parse [{context}]: top-level value is "
                        f"{type(result).__name__}, expected dict."
                    )
                # Strict schema enforcement — raises RuntimeError on violation
                result = _validate_parsed(result, context)
                # Sanity check on repair attempts: 0 facts after repair = truncation
                if attempt > 0:
                    fact_count = sum(1 for v in result["facts"].values() if v is not None)
                    if fact_count == 0:
                        logger.warning(
                            f"_safe_json_parse [{context}]: repair attempt {attempt} "
                            "produced 0 non-null facts — continuing"
                        )
                        # Do not raise here — try next repair
                        if attempt < 2:
                            pass
                        else:
                            raise RuntimeError(
                                f"_safe_json_parse [{context}]: repair produced 0 non-null facts "
                                "after all attempts."
                            )
                    else:
                        return result
                else:
                    return result
            except RuntimeError:
                raise   # schema violations propagate immediately
            except (json.JSONDecodeError, ValueError):
                # Heuristic: LLM returned a bare dict (facts only) → wrap
                try:
                    bare = json.loads(candidate)
                    if isinstance(bare, dict) and "facts" not in bare and "flags" not in bare:
                        wrapped = {"facts": bare, "flags": {}}
                        result = _validate_parsed(wrapped, context)
                        logger.warning(
                            f"_safe_json_parse [{context}]: wrapped bare dict into facts/flags"
                        )
                        return result
                except Exception:
                    pass

        if attempt < 2:
            logger.warning(
                f"_safe_json_parse: attempt {attempt + 1} failed"
                + (f" [{context}]" if context else "") + ", requesting LLM repair"
            )
            try:
                raw = groq_chat(
                    "llama-3.1-8b-instant",
                    [{
                        "role": "user",
                        "content": (
                            "Fix the malformed JSON. Return ONLY a valid JSON object. "
                            "Do not add any explanation or markdown.\n\n"
                            + raw[:3000]   # 🔥 IMPORTANT: truncate
                        ),
                    }],
                )
            except Exception as repair_ex:
                logger.error(f"_safe_json_parse: LLM repair call failed — {repair_ex}")
                break

    raise RuntimeError(
        "_safe_json_parse: could not parse valid JSON after 3 attempts"
        + (f" [{context}]" if context else "")
    )


# ── Fix 5: Separate flat JSON parser for reconciliation ───────────────────────

def _parse_flat_json(raw: str, context: str = "") -> dict:
    """
    Parse reconciliation output: {"field_name": "chosen_value", ...}
    This is a flat dict — NOT {"facts": ..., "flags": ...}.
    Uses a separate parser so _safe_json_parse (which enforces extraction schema)
    is never reused for a structurally different output format.
    Raises RuntimeError on failure.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.I)
        raw = raw.rstrip("`").strip()
    s = raw.find("{")
    e = raw.rfind("}")
    if s == -1 or e == -1:
        raise RuntimeError(
            f"_parse_flat_json [{context}]: no JSON object found in LLM output"
        )
    candidate = raw[s : e + 1]
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError as je:
        raise RuntimeError(
            f"_parse_flat_json [{context}]: JSON decode failed — {je}"
        ) from je
    if not isinstance(result, dict):
        raise RuntimeError(
            f"_parse_flat_json [{context}]: expected dict, got {type(result).__name__}"
        )
    return result


# ── Chunking ──────────────────────────────────────────────────────────────────
_LONG_DOC_LIST_KEYS = [
    "locations", "property_locations", "auto_vin_schedule", "auto_garaging_addresses",
    "auto_drivers", "gl_class_codes_by_location", "wc_class_codes", "underlying_policies",
    "additional_named_insureds", "auto_covered_symbols",
]

DOC_TYPE_CHUNK_LIMITS: Dict[str, int] = {
    "dec_page": 100, "loss_run": 200, "schedule": 200,
    "certificate": 50, "endorsement": 100, "quote": 100,
    "application": 100, "default": 100,
}

_SECTION_BOUNDARY_RE = re.compile(
    r'(?m)^(?:'
    r'[A-Z][A-Z\s\-/]{4,}:|'
    r'[A-Z][A-Z\s\-/]{4,}$|'
    r'ACORD\s+\d+|'
    r'SECTION\s+[A-Z0-9]+|'
    r'SCHEDULE\s+[A-Z0-9]+|'
    r'ITEM\s+\d+\.|'
    r'(?:\d+\.\s+[A-Z][A-Za-z\s]{3,})'
    r')'
)

_KV_LABEL_RE = re.compile(r'^\s*[A-Za-z][A-Za-z\s/\-]{2,40}:\s*$')

ChunkTuple = Tuple[str, int, int, str]


def _find_section_boundaries(lines: List[str]) -> List[int]:
    boundaries = [0]
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped and _SECTION_BOUNDARY_RE.match(stripped):
            if i > 0 and i not in boundaries:
                boundaries.append(i)
    return sorted(set(boundaries))


def _tail_chars(s: str, n: int) -> str:
    if n <= 0 or not s:
        return ""
    tail = s[-n:]
    nl = tail.find("\n")
    if nl > 0:
        tail = tail[nl + 1:]
    return tail


def _split_lines_into_chunks(
    lines: List[str],
    line_start_idx: int,
    line_starts: List[int],
    max_chars: int,
    max_chunks: int,
    init_context: str,
    existing_count: int,
) -> List[ChunkTuple]:
    """
    Line-level fallback for oversized sections.
    KV guard: chains consecutive label-only lines to avoid splitting KV pairs.
    Never drops content — all sections emitted regardless of length.
    """
    results: List[ChunkTuple] = []
    buf: List[str] = []
    buf_chars      = 0
    buf_char_start = line_starts[line_start_idx] if line_start_idx < len(line_starts) else 0
    context_prefix = init_context
    total_lines    = len(lines)
    i              = 0

    def _flush(upto_abs_line: int) -> None:
        nonlocal buf, buf_chars, buf_char_start, context_prefix
        if not buf:
            return
        body     = "".join(buf)
        safe_idx = min(upto_abs_line, len(line_starts) - 1)
        c_end    = line_starts[safe_idx]
        results.append((body, buf_char_start, c_end, context_prefix))
        context_prefix = _tail_chars(body, max_chars // 7)
        buf            = []
        buf_chars      = 0
        buf_char_start = c_end

    while i < total_lines:
        if existing_count + len(results) >= max_chunks:
            break

        abs_line = line_start_idx + i

        # KV guard with chaining
        consumed = [lines[i]]
        j        = i + 1
        while j < total_lines and _KV_LABEL_RE.match(consumed[-1].rstrip()):
            consumed.append(lines[j])
            j += 1
            if j < total_lines and _KV_LABEL_RE.match(consumed[-1].rstrip()):
                continue
            break

        block      = "".join(consumed)
        block_len  = len(block)
        lines_used = j - i

        if buf_chars + block_len > max_chars and buf:
            _flush(abs_line)

        buf.extend(consumed)
        buf_chars += block_len
        i         += lines_used

    if buf:
        end_abs = line_start_idx + total_lines
        safe    = min(end_abs, len(line_starts) - 1)
        _flush(safe)

    return results


def _chunk_by_sections(
    text: str,
    max_chars: int,
    overlap_pct: float,
    max_chunks: int,
) -> List[ChunkTuple]:
    """
    Hybrid semantic + line chunking.
    char_start/char_end: unique content offsets into original text.
    context_prefix: boundary context for LLM — not counted in char ranges.
    Short sections never dropped.
    """
    lines = text.splitlines(keepends=True)

    line_starts: List[int] = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line)
    line_starts.append(pos)

    boundaries = _find_section_boundaries(lines)
    if len(lines) not in boundaries:
        boundaries.append(len(lines))

    sections: List[Tuple[int, int]] = [
        (boundaries[i], boundaries[i + 1])
        for i in range(len(boundaries) - 1)
    ]

    results: List[ChunkTuple] = []
    context_prefix   = ""
    cur_lines: List[str] = []
    cur_chars        = 0
    cur_char_start   = 0

    def _flush_cur(upto_char: int) -> None:
        nonlocal cur_lines, cur_chars, cur_char_start, context_prefix
        if not cur_lines:
            return
        body = "".join(cur_lines)
        results.append((body, cur_char_start, upto_char, context_prefix))
        context_prefix = _tail_chars(body, max_chars // 7)
        cur_lines      = []
        cur_chars      = 0

    for sec_start_li, sec_end_li in sections:
        if len(results) >= max_chunks:
            break

        sec_lines      = lines[sec_start_li:sec_end_li]
        sec_chars      = sum(len(l) for l in sec_lines)
        sec_char_start = line_starts[sec_start_li]
        sec_char_end   = line_starts[sec_end_li]

        if sec_chars > max_chars:
            if cur_lines:
                _flush_cur(sec_char_start)
                cur_char_start = sec_char_start

            sub_chunks = _split_lines_into_chunks(
                sec_lines, sec_start_li, line_starts,
                max_chars, max_chunks, context_prefix,
                existing_count=len(results),
            )
            results.extend(sub_chunks)
            if sub_chunks:
                context_prefix = sub_chunks[-1][3]
                cur_char_start = sub_chunks[-1][2]
            cur_lines = []
            cur_chars = 0
            continue

        if cur_chars + sec_chars > max_chars and cur_lines:
            if len(results) >= max_chunks:
                break
            _flush_cur(sec_char_start)
            cur_char_start = sec_char_start
            cur_lines      = list(sec_lines)
            cur_chars      = sec_chars
        else:
            if not cur_lines:
                cur_char_start = sec_char_start
            cur_lines.extend(sec_lines)
            cur_chars += sec_chars

    if cur_lines and len(results) < max_chunks:
        _flush_cur(line_starts[len(lines)])

    if not results:
        results = [(text[:max_chars], 0, min(max_chars, len(text)), "")]

    return results


# ── Coverage verification ─────────────────────────────────────────────────────

def _verify_coverage(
    chunks: List[ChunkTuple],
    text_len: int,
    doc_type: str,
) -> None:
    if not chunks:
        raise RuntimeError(
            f"_verify_coverage: doc_type='{doc_type}' — no chunks produced"
        )

    intervals = sorted((cs, ce) for (_, cs, ce, _) in chunks)

    merged: List[Tuple[int, int]] = []
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))

    gaps: List[Tuple[int, int]] = []
    if merged[0][0] > 0:
        gaps.append((0, merged[0][0]))
    for i in range(len(merged) - 1):
        if merged[i][1] < merged[i + 1][0]:
            gaps.append((merged[i][1], merged[i + 1][0]))
    if merged[-1][1] < text_len:
        gaps.append((merged[-1][1], text_len))

    covered = sum(e - s for s, e in merged)
    pct     = covered / text_len if text_len > 0 else 1.0

    if gaps:
        gap_desc = ", ".join(f"{s}–{e} ({e - s} chars)" for s, e in gaps[:5])
        raise RuntimeError(
            f"_verify_coverage: doc_type='{doc_type}' coverage={pct:.1%} "
            f"({covered}/{text_len} chars). Gaps: [{gap_desc}]."
        )

    logger.info(
        f"_verify_coverage: doc_type='{doc_type}' OK "
        f"({covered}/{text_len} chars, {len(chunks)} chunks)"
    )


# ── Fix 11: Annotation pipeline ───────────────────────────────────────────────

def _annotate_facts(
    raw_facts: dict,
    low_confidence_tokens: Optional[List[str]],
) -> Tuple[dict, List[str]]:
    """
    Fix 11: Called AFTER _validate_parsed on RAW LLM output.
    Receives clean str/None/list/structured-dict values — never annotated dicts.
    OCR confusion-map applied field-by-field: only safe fields get normalized.
    Free-text fields (names, addresses) use plain .lower() — no false flags.
    """
    low_conf_set: set = set()
    if low_confidence_tokens:
        for t in low_confidence_tokens:
            tl = t.lower()
            low_conf_set.add(tl)
            # Add confusion-normalized form for numeric/code token matching
            low_conf_set.add(_normalize_for_ocr_check(tl))

    manual_confirmation_required: List[str] = []
    annotated: dict = {}

    for k, v in raw_facts.items():
        # Pass-through: None, list, structured dict — not annotated
        if v is None or isinstance(v, list) or isinstance(v, dict):
            annotated[k] = v
            continue

        # v is a clean str at this point (guaranteed by _validate_parsed)
        str_val = str(v).strip()
        if not str_val or str_val.lower() in _NULL_STRINGS:
            annotated[k] = None
            continue

        norm_val  = _normalize_for_ocr_check(str_val.lower(), field=k)
        confident = not any(
            token and len(token) >= 3
            and re.search(rf"\b{re.escape(token)}\b", norm_val)
            for token in low_conf_set
        )
        annotated[k] = {"value": str_val, "ocr_confident": confident}
        if not confident and k in _OCR_CRITICAL_FIELDS:
            manual_confirmation_required.append(k)

    return annotated, manual_confirmation_required


# ── Core extraction ───────────────────────────────────────────────────────────

def extract_facts(
    text: str,
    low_confidence_tokens: Optional[List[str]] = None,
    context_prefix: str = "",
) -> dict:
    """
    Single-chunk extraction.
    Pipeline: LLM → _safe_json_parse → _validate_parsed → _annotate_facts (strict order).
    Cache key: model + PROMPT_VERSION + SCHEMA_VERSION + ctx_hash + lct_hash + text.
    Raises RuntimeError on any failure — never swallowed.
    """
    if len(text) < 30:
        return {"facts": {}, "flags": {}}

    ctx_hash = hashlib.md5(context_prefix.encode(), usedforsecurity=False).hexdigest()[:8]
    lct_hash = hashlib.md5(
        json.dumps(sorted(low_confidence_tokens or [])).encode(),
        usedforsecurity=False,
    ).hexdigest()[:8]
    ck = _cache_key(text, ACTIVE_MODEL, ctx_hash, lct_hash)

    cached = _cache_get(ck)
    if cached is not None:
        logger.debug(f"extract_facts cache hit {ck[:8]}")
        return cached

    low_conf_note = ""
    if low_confidence_tokens:
        unique_tokens = list(dict.fromkeys(low_confidence_tokens))[:40]
        low_conf_note = (
            _LOW_CONF_NOTE_HEADER
            + f"{', '.join(unique_tokens)}\n"
        )

    context_section = ""
    if context_prefix and context_prefix.strip():
        context_section = (
            "\n\nPREVIOUS CONTEXT (reference only — do NOT re-extract from this; "
            "extract ONLY from PRIMARY TEXT below):\n"
            f"---\n{context_prefix.strip()}\n---\n"
        )
    _EXTRACT_PROMPT_SUFFIX = (
        '\n\nCRITICAL REMINDER: Your response MUST be a single JSON object with EXACTLY '
        'these two top-level keys: "facts" and "flags". No other keys. No markdown. '
        'Start your response with { and end with }.'
    )

    prompt = (
        _EXTRACT_PROMPT_PREFIX
        + context_section
        + f'PRIMARY TEXT:\n"""\n{text}\n"""{low_conf_note}'
        + _EXTRACT_PROMPT_SUFFIX
    )

    raw = groq_chat("llama-3.1-8b-instant", [{"role": "user", "content": prompt}])

    # Pipeline order: parse → validate → annotate (never reversed)
    result   = _safe_json_parse(raw, context=f"key={ck[:8]}")
    # _validate_parsed already called inside _safe_json_parse on the raw LLM dict.
    # result["facts"] now contains clean str/None/list/structured-dict values.
    annotated, manual_conf = _annotate_facts(result["facts"], low_confidence_tokens)
    result["facts"] = annotated
    if manual_conf:
        result["manual_confirmation_required"] = manual_conf

    _cache_set(ck, result)
    return result


# ── Scored merge ──────────────────────────────────────────────────────────────

_TIER_WEIGHTS: Dict[str, float] = {"tier1": 1.5, "tier2": 1.2, "default": 1.0}


def _get_field_tier(field: str) -> str:
    try:
        from services.fact_registry import FACT_REGISTRY
        t = FACT_REGISTRY.get(field, {}).get("tier")
        if t == 1:
            return "tier1"
        if t == 2:
            return "tier2"
    except Exception:
        pass
    return "default"


def _score_value(field: str, record: Any, freq: int) -> float:
    tier_weight = _TIER_WEIGHTS[_get_field_tier(field)]
    freq_score  = math.log1p(freq)
    ocr_score   = 1.0 if (record.get("ocr_confident", True) if isinstance(record, dict) else True) else 0.5
    return tier_weight * (freq_score + ocr_score)


def _merge_list_fields(partials: List[dict], list_keys: List[str]) -> dict:
    if not partials:
        return {"facts": {}, "flags": {}}
    if len(partials) == 1:
        p = dict(partials[0])
        for k in ("_chunk_idx", "_char_start", "_char_end"):
            p.pop(k, None)
        return p

    val_candidates: Dict[str, Dict[str, dict]] = {}
    for partial in sorted(partials, key=lambda p: p.get("_chunk_idx", 0)):
        for k, v in partial.get("facts", {}).items():
            if k in list_keys or k == "wc_payroll_by_state" or _is_empty(v):
                continue
            # Extract canonical string value from annotated or raw form
            raw_val = v.get("value", v) if isinstance(v, dict) and "value" in v else v
            if _is_empty(raw_val):
                continue
            sval     = str(raw_val).strip()
            norm_key = sval.lower()
            val_candidates.setdefault(k, {})
            if norm_key not in val_candidates[k]:
                val_candidates[k][norm_key] = {"record": v, "freq": 0}
            val_candidates[k][norm_key]["freq"] += 1

    merged_facts: dict = {}

    for field, candidates in val_candidates.items():
        scored = sorted(
            [(nk, _score_value(field, c["record"], c["freq"]), c) for nk, c in candidates.items()],
            key=lambda x: x[1], reverse=True,
        )
        winner_nk, winner_score, winner_c = scored[0]
        merged_facts[field] = winner_c["record"]
        if len(scored) > 1:
            rejected = [
                f"{nk!r}(score={sc:.2f},freq={c['freq']})"
                for nk, sc, c in scored[1:]
            ]
            logger.info(
                f"merge field={field!r} chosen={winner_nk!r} "
                f"score={winner_score:.2f} freq={winner_c['freq']} "
                f"rejected=[{', '.join(rejected)}]"
            )

    for lk in list_keys:
        seen: dict = {}
        for partial in partials:
            for item in (partial.get("facts", {}).get(lk) or []):
                seen.setdefault(json.dumps(item, sort_keys=True), item)
        if seen:
            merged_facts[lk] = list(seen.values())

    # wc_payroll_by_state: scored per state
    wc_candidates: Dict[str, Dict[str, dict]] = {}
    for partial in partials:
        for state, amount in (partial.get("facts", {}).get("wc_payroll_by_state") or {}).items():
            if _is_empty(amount):
                continue
            amt_str  = str(amount).strip()
            norm_key = amt_str.lower()
            wc_candidates.setdefault(state, {})
            if norm_key not in wc_candidates[state]:
                wc_candidates[state][norm_key] = {"record": amt_str, "freq": 0}
            wc_candidates[state][norm_key]["freq"] += 1

    if wc_candidates:
        merged_wc: dict = {}
        for state, candidates in wc_candidates.items():
            scored_wc = sorted(
                [(nk, _score_value("wc_payroll_by_state", {"value": c["record"]}, c["freq"]), c)
                 for nk, c in candidates.items()],
                key=lambda x: x[1], reverse=True,
            )
            merged_wc[state] = scored_wc[0][2]["record"]
        merged_facts["wc_payroll_by_state"] = merged_wc

    claim_vals = []
    for partial in partials:
        raw = partial.get("facts", {}).get("num_claims")
        val = raw.get("value", raw) if isinstance(raw, dict) and "value" in raw else raw
        if val:
            try:
                claim_vals.append(int(str(val).replace(",", "")))
            except ValueError:
                pass
    if claim_vals:
        merged_facts["num_claims"] = {"value": str(max(claim_vals)), "ocr_confident": True}

    merged_flags: dict = {}
    for partial in partials:
        for k, v in partial.get("flags", {}).items():
            if isinstance(v, bool):
                merged_flags[k] = merged_flags.get(k, False) or v
            elif k not in merged_flags or merged_flags[k] is None:
                merged_flags[k] = v

    return {"facts": merged_facts, "flags": merged_flags}


# ── Reconciliation ────────────────────────────────────────────────────────────

def _build_reconciliation_payload(
    partials: List[dict],
    raw_text: str,
) -> Optional[Dict[str, dict]]:
    conflicts: Dict[str, dict] = {}

    for k in _OCR_CRITICAL_FIELDS:
        val_data: Dict[str, dict] = {}

        for p in partials:
            v = p.get("facts", {}).get(k)
            if _is_empty(v):
                continue
            raw_val = v.get("value", v) if isinstance(v, dict) and "value" in v else v
            if _is_empty(raw_val):
                continue
            sval     = str(raw_val).strip()
            norm_key = sval.lower()

            val_data.setdefault(norm_key, {"original": sval, "freq": 0, "snippets": []})
            val_data[norm_key]["freq"] += 1

            if len(val_data[norm_key]["snippets"]) < 3:
                c_start = p.get("_char_start", 0)
                c_end   = p.get("_char_end", len(raw_text))
                region  = raw_text[c_start:c_end]
                idx     = region.lower().find(sval.lower())
                if idx >= 0:
                    snip = region[max(0, idx - 100) : idx + len(sval) + 100].strip()
                else:
                    snip = region[:200].strip()
                if snip and snip not in val_data[norm_key]["snippets"]:
                    val_data[norm_key]["snippets"].append(snip)

        if len(val_data) > 1:
            conflicts[k] = {
                entry["original"]: {
                    "frequency": entry["freq"],
                    "contexts":  entry["snippets"],
                }
                for entry in val_data.values()
            }

    return conflicts if conflicts else None


def _run_reconciliation(conflicts: Dict[str, dict], result: dict) -> None:
    """
    Fix 5: separate flat JSON parser (_parse_flat_json) used — not _safe_json_parse.
    Fix 5: value normalization (lowercase + strip + collapse whitespace) before
           candidate set membership check.
    Hallucinated values (not in candidates after normalization) are rejected.
    Non-fatal — keeps merged result on any exception.
    """
    # Build allowed candidate set with normalization
    # normalize: lowercase, strip, collapse internal whitespace
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())

    allowed: Dict[str, set] = {}
    for field, values_dict in conflicts.items():
        allowed[field] = {_norm(v) for v in values_dict.keys()}

    prompt = (
        "You are resolving conflicts in extracted insurance document facts. "
        "For each field, use the frequency (how many document sections contained each value) "
        "and context snippets to pick the most accurate value. "
        "Higher frequency and more specific context are stronger signals. "
        "Return ONLY a JSON object mapping field_name → chosen_value_string. "
        "The chosen value MUST be one of the provided candidate values exactly as shown.\n\n"
        "Conflicts:\n" + json.dumps(conflicts, indent=2)
    )
    try:
        raw      = groq_chat("llama-3.1-8b-instant", [{"role": "user", "content": prompt}])
        resolved = _parse_flat_json(raw, context="reconciliation")
        for k, v in resolved.items():
            if k not in _OCR_CRITICAL_FIELDS or _is_empty(v):
                continue
            chosen_str  = str(v).strip()
            chosen_norm = _norm(chosen_str)
            if chosen_norm not in allowed.get(k, set()):
                logger.warning(
                    f"reconciliation: field={k!r} LLM chose {chosen_str!r} "
                    f"(norm={chosen_norm!r}) NOT in candidates "
                    f"{list(allowed.get(k, set()))} — rejecting"
                )
                continue
            old = result.get("facts", {}).get(k)
            result["facts"][k] = {"value": chosen_str, "ocr_confident": True, "reconciled": True}
            logger.info(f"reconciliation field={k!r} resolved={chosen_str!r} was={old!r}")
    except Exception as ex:
        logger.warning(f"_run_reconciliation: non-fatal failure — {ex}")


# ── Fix 1: Adaptive semaphore — no blocking in record(), no semaphore swap ────

class _AdaptiveSemaphore:
    """
    Fix 1: concurrency enforced ONLY in __aenter__ via _target_level check.
    record() NEVER blocks — it only updates _target_level.
    Scale-down: __aenter__ waits when active >= _target_level (condition-based).
    Scale-up: condition notified so waiters can proceed.
    No semaphore object is ever replaced mid-flight.
    No draining in record(). No busy loops.
    """
    _INIT            = 1
    _MIN             = 1
    _MAX             = 3
    _RETRY_THRESHOLD = 0.30
    _STABLE_WINDOW   = 10

    def __init__(self) -> None:
        self._target_level = self._INIT
        self._active       = 0          # count of coroutines currently inside context
        self._lock         = asyncio.Lock()
        self._condition    = asyncio.Condition(self._lock)
        self._retries      = 0
        self._calls        = 0
        self._stable       = 0

    async def __aenter__(self):
        async with self._condition:
            # Wait until active count is below target level
            while self._active >= self._target_level:
                await self._condition.wait()
            self._active += 1
        return self

    async def __aexit__(self, *_):
        async with self._condition:
            self._active -= 1
            self._condition.notify_all()

    async def record(self, retried: bool) -> None:
        """
        Non-blocking stats update. Updates _target_level only.
        notify_all() wakes any waiters in __aenter__ when level increases.
        """
        async with self._condition:
            self._calls += 1
            if retried:
                self._retries += 1
                self._stable   = 0
            else:
                self._stable  += 1

            if self._calls % 10 == 0:
                rate = self._retries / self._calls
                if rate > self._RETRY_THRESHOLD and self._target_level > self._MIN:
                    new = max(self._MIN, self._target_level - 1)
                    self._target_level = new
                    # No notify needed on reduction — __aenter__ naturally
                    # blocks new entrants; existing holders finish unaffected.
                    logger.warning(f"AdaptiveSem: retry_rate={rate:.0%} concurrency →{new}")
                elif rate <= self._RETRY_THRESHOLD and self._stable >= self._STABLE_WINDOW:
                    if self._target_level < self._MAX:
                        new = min(self._MAX, self._target_level + 1)
                        self._target_level = new
                        self._stable       = 0
                        self._condition.notify_all()   # wake waiters — more slots available
                        logger.info(f"AdaptiveSem: stable concurrency →{new}")


# ── Async extraction ──────────────────────────────────────────────────────────

async def extract_facts_async(
    text: str,
    low_confidence_tokens: Optional[List[str]] = None,
    context_prefix: str = "",
) -> dict:
    """
    Async wrapper with jittered exponential backoff for transient errors.
    RuntimeError (JSON/schema failure) propagates immediately — not transient.
    All retries live here. _gather_chunks_async adds no extra retry layer.
    """
    _TRANSIENT = ("rate", "timeout", "connection", "503", "502", "500", "429",
                  "service unavailable", "temporarily")
    last_ex: Optional[Exception] = None
    for attempt in range(3):
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, extract_facts, text, low_confidence_tokens, context_prefix
            )
        except RuntimeError:
            raise
        except Exception as ex:
            last_ex = ex
            if attempt < 2 and any(t in str(ex).lower() for t in _TRANSIENT):
                base   = 2 ** attempt
                jitter = random.uniform(-0.25 * base, 0.25 * base)
                wait   = max(0.5, base + jitter)
                logger.warning(
                    f"extract_facts_async: transient attempt={attempt + 1}/3 wait={wait:.2f}s — {ex}"
                )
                await asyncio.sleep(wait)
                continue
            raise
    raise last_ex


async def _gather_chunks_async(
    chunks: List[ChunkTuple],
    low_confidence_tokens: Optional[List[str]],
    doc_type: str,
) -> List[dict]:
    sem             = _AdaptiveSemaphore()
    total_llm_calls = 0

    async def _one(idx: int, chunk_text: str, c_start: int, c_end: int, ctx: str) -> dict:
        nonlocal total_llm_calls
        async with sem:
            try:
                await asyncio.sleep(1.0)
                total_llm_calls += 1
                await asyncio.sleep(0.7)
                result = await extract_facts_async(chunk_text, low_confidence_tokens, ctx)
                result.update({"_chunk_idx": idx, "_char_start": c_start, "_char_end": c_end})
                await sem.record(retried=False)
                logger.debug(f"chunk {idx}: ok chars={c_start}–{c_end}")
                return result
            except Exception as ex:
                logger.error(f"chunk {idx} (chars {c_start}–{c_end}): permanent fail — {ex}")
                await sem.record(retried=True)
                return {
                    "facts": {}, "flags": {},
                    "_chunk_idx": idx, "_char_start": c_start, "_char_end": c_end,
                    "chunk_failed": True, "chunk_error": str(ex),
                }

    results = list(await asyncio.gather(*[
        _one(i, ct, cs, ce, cx) for i, (ct, cs, ce, cx) in enumerate(chunks)
    ]))
    failed = sum(1 for r in results if r.get("chunk_failed"))
    logger.info(
        f"gather_chunks doc_type='{doc_type}' chunks={len(chunks)} "
        f"failed={failed} llm_calls={total_llm_calls}"
    )
    return results


# ── Fix 9: Thread-based async runner ─────────────────────────────────────────

def _run_async(coro) -> Any:
    """
    Always spawns a new thread with its own event loop.
    Deterministic under any framework (FastAPI/uvloop/sync).
    No get_running_loop() branching — no deadlock paths.
    """
    with _cf.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# ── Transient runtime error classification ────────────────────────────────────

_TRANSIENT_RUNTIME_MARKERS = (
    "permanently failed",
    "rate", "timeout", "connection", "503", "502", "500", "429",
)


def _is_transient_runtime_error(err: RuntimeError) -> bool:
    msg = str(err).lower()
    return any(m in msg for m in _TRANSIENT_RUNTIME_MARKERS)


# ── Fix 6: num_claims row-level deduplication ─────────────────────────────────

# Anchors that appear once per claim row in well-structured loss runs.
# "date of loss" is used rather than "claimant" because it appears exactly
# once per row and is less likely to appear in headers or footers.
# Fallback to "claimant" if date-of-loss count is zero.
_CLAIM_ROW_ANCHOR_PRIMARY   = re.compile(r"date\s+of\s+loss", re.I)
_CLAIM_ROW_ANCHOR_SECONDARY = re.compile(r"\bclaimant\b", re.I)
# Lines that are clearly headers — excluded from row count
_CLAIM_HEADER_RE = re.compile(
    r"(?:date\s+of\s+loss|claim\s*(?:no|number|#)|claimant|description|status|reserve|paid|incurred)",
    re.I,
)


def _count_claims_from_text(text: str) -> int:
    """
    Fix 6: Line-based deduplication. Count unique lines matching a claim-row anchor.
    Header detection: lines where ALL common claim column labels appear together
    on a single line → excluded (those are table headers, not claim rows).
    Returns 0 if no anchors found.
    """
    lines = text.splitlines()
    claim_lines: set = set()

    for line_no, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Header heuristic: line contains 3+ column label keywords → skip
        header_hits = len(_CLAIM_HEADER_RE.findall(stripped))
        if header_hits >= 3:
            continue

        # Primary anchor: "date of loss" appears on this line → it's a claim row
        if _CLAIM_ROW_ANCHOR_PRIMARY.search(stripped):
            claim_lines.add(line_no)

    if not claim_lines:
        # Fallback: count unique lines with "claimant" not in a header
        for line_no, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            header_hits = len(_CLAIM_HEADER_RE.findall(stripped))
            if header_hits >= 3:
                continue
            if _CLAIM_ROW_ANCHOR_SECONDARY.search(stripped):
                claim_lines.add(line_no)

    return len(claim_lines)


# ── Core pipeline ─────────────────────────────────────────────────────────────

def _run_extraction(
    text: str,
    doc_type: str,
    low_confidence_tokens: Optional[List[str]],
    chunk_size: int,
    cap: int,
) -> dict:
    overlap_pct = 0.15

    chunks = _chunk_by_sections(
        text,
        max_chars=chunk_size,
        overlap_pct=overlap_pct,
        max_chunks=cap
    )

    if len(chunks) > cap:
        raise ValueError(
            f"_run_extraction: doc_type='{doc_type}' actual chunk count={len(chunks)} "
            f"exceeds cap={cap}. Raise DOC_TYPE_CHUNK_LIMITS['{doc_type}'] or split the document."
        )

    _verify_coverage(chunks, len(text), doc_type)

    logger.info(
        f"extraction doc_type='{doc_type}' model='{ACTIVE_MODEL}' "
        f"chunks={len(chunks)} total_chars={len(text)} est_tokens={estimate_tokens(text):,}"
    )

    partials = _run_async(
        _gather_chunks_async(chunks, low_confidence_tokens, doc_type)
    )

    # ─────────────────────────────────────────────
    # PATCH 3: Partial failure handling + retry
    # ─────────────────────────────────────────────
    failed = [p["_chunk_idx"] for p in partials if p.get("chunk_failed")]

    if failed:
        errors = [p.get("chunk_error", "?") for p in partials if p.get("chunk_failed")]
        fail_ratio = len(failed) / len(chunks)

        # CASE 1: Majority failed → retry smaller chunks
        if fail_ratio > 0.5 and chunk_size > 1500:
            new_chunk_size = int(chunk_size * 0.6)
            logger.warning(
                f"_run_extraction: majority failed ({len(failed)}/{len(chunks)}), "
                f"retrying {chunk_size} → {new_chunk_size}"
            )
            return _run_extraction(
                text,
                doc_type,
                low_confidence_tokens,
                new_chunk_size,
                cap
            )

        # CASE 2: Minority failed → continue with partial results
        if fail_ratio <= 0.5:
            logger.warning(
                f"_run_extraction: {len(failed)}/{len(chunks)} chunks failed "
                f"(below threshold) — continuing with partial results. "
                f"indices={failed}"
            )
            partials = [p for p in partials if not p.get("chunk_failed")]

        else:
            # CASE 3: Still failing after retry → hard fail
            raise RuntimeError(
                f"extraction: {len(failed)}/{len(chunks)} chunks permanently failed "
                f"doc_type='{doc_type}' indices={failed} errors={errors}"
            )

    # ─────────────────────────────────────────────

    result = _merge_list_fields(partials, list_keys=_LONG_DOC_LIST_KEYS)

    # Fix 6: row-level claim count with header exclusion
    if doc_type == "loss_run":
        regex_count = _count_claims_from_text(text)
        if regex_count > 0:
            existing     = result.get("facts", {}).get("num_claims")
            existing_val = 0

            if existing:
                try:
                    existing_val = int(str(
                        existing.get("value", existing)
                        if isinstance(existing, dict) and "value" in existing
                        else existing
                    ).replace(",", ""))
                except (ValueError, TypeError):
                    pass

            if regex_count > existing_val:
                result.setdefault("facts", {})
                result["facts"]["num_claims"] = {
                    "value": str(regex_count),
                    "ocr_confident": True
                }

    conflicts = _build_reconciliation_payload(partials, text)

    if conflicts:
        logger.info(f"reconciliation triggered fields={list(conflicts.keys())}")
        _run_reconciliation(conflicts, result)
    else:
        logger.info("reconciliation: no conflicts — skipped")

    return result

# ── Fix 10: Unified single+long extraction path ───────────────────────────────

def _extract_any(
    text: str,
    doc_type: str,
    low_confidence_tokens: Optional[List[str]],
) -> dict:
    """
    Fix 10: NO bypass path for single-chunk documents.
    All documents go through extract_facts() which enforces the full pipeline:
    LLM → _safe_json_parse → _validate_parsed → _annotate_facts.
    The only difference for single-chunk docs is no chunking loop and no reconciliation
    (legitimately unnecessary when there is only one chunk and no conflicts to resolve).
    """
    chunk_size = _effective_chunk_size(ACTIVE_MODEL)
    cap        = DOC_TYPE_CHUNK_LIMITS.get(doc_type, DOC_TYPE_CHUNK_LIMITS["default"])

    if len(text) <= chunk_size:
        return extract_facts(text, low_confidence_tokens, context_prefix="")

    return _run_extraction(text, doc_type, low_confidence_tokens, chunk_size, cap)


# ── Public entry point ────────────────────────────────────────────────────────

def extract_facts_long(
    text: str,
    doc_type: str,
    low_confidence_tokens: Optional[List[str]] = None,
) -> dict:
    """
    Public extraction entry for all doc types and sizes.
    Raises ValueError on budget/cap violations (not retried — config issues).
    Raises RuntimeError on persistent chunk failures after document-level retry.
    Coverage gaps and deterministic errors are NOT retried.
    """
    t_start = time.monotonic()
    _check_cost_guardrail(text, doc_type)

    try:
        result = _extract_any(text, doc_type, low_confidence_tokens)
    except ValueError:
        raise
    except RuntimeError as first_err:
        if not _is_transient_runtime_error(first_err):
            raise
        logger.warning(f"extract_facts_long: attempt 1 failed ({first_err}) — doc-level retry")
        wait = 3 + random.uniform(0, 2)
        time.sleep(wait)
        try:
            result = _extract_any(text, doc_type, low_confidence_tokens)
        except RuntimeError as second_err:
            raise RuntimeError(
                f"extract_facts_long: doc_type='{doc_type}' failed after 2 attempts. "
                f"Attempt1={first_err} Attempt2={second_err}"
            ) from second_err

    logger.info(
        f"extract_facts_long: done doc_type='{doc_type}' elapsed={time.monotonic() - t_start:.2f}s"
    )
    return result


# ── Multi-doc merge ───────────────────────────────────────────────────────────

def merge_facts(docs: List[dict], primary: dict) -> Tuple[dict, dict]:
    """
    Multi-document merge. Non-primary docs scored via _merge_list_fields.
    Primary applied last and always wins on conflict.
    """
    if not docs:
        return {}, {}

    non_primary = [d for d in docs if d["filename"] != primary["filename"]]

    if non_primary:
        pseudo_partials = [
            {"facts": d.get("facts", {}), "flags": d.get("flags", {}), "_chunk_idx": i}
            for i, d in enumerate(non_primary)
        ]
        np_merged = _merge_list_fields(pseudo_partials, list_keys=_LONG_DOC_LIST_KEYS)
        mf: dict = np_merged.get("facts", {})
        mg: dict = np_merged.get("flags", {})
    else:
        mf = {}
        mg = {}

    for k, v in primary.get("facts", {}).items():
        if not _is_empty(v):
            mf[k] = v

    for k, v in primary.get("flags", {}).items():
        if isinstance(v, bool):
            mg[k] = mg.get(k, False) or v
        elif not _is_empty(v):
            mg[k] = v

    return mf, mg