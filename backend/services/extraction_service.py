#extraction_service.py

import hashlib
import json
import logging
import re
from typing import List, Optional, Tuple, Dict

from config.settings import groq_chat

logger = logging.getLogger(__name__)

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
    '  "num_employees": string or null, "locations": [],\n'
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
    + _EXTRACT_SCHEMA +
    '\n\nReturn ONLY the JSON object, no markdown, no extra text.\n\n'
)

# ── OCR confidence thresholds by field tier ───────────────────────────────────
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


def _ocr_threshold(field_name: str) -> float:
    if field_name in _OCR_CRITICAL_FIELDS:
        return _OCR_THRESHOLD_CRITICAL
    if field_name in _OCR_STANDARD_FIELDS:
        return _OCR_THRESHOLD_STANDARD
    return _OCR_THRESHOLD_DEFAULT


# ── Extraction cache ──────────────────────────────────────────────────────────
_CACHE_TTL      = 86_400
_CACHE_MAX_SIZE = 500
_EXTRACT_CACHE: dict = {}

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
        "falling back to in-process dict cache"
    )
    _redis = None


def _evict_in_process_cache() -> None:
    if len(_EXTRACT_CACHE) >= _CACHE_MAX_SIZE:
        evict_keys = list(_EXTRACT_CACHE.keys())[: _CACHE_MAX_SIZE // 10]
        for k in evict_keys:
            _EXTRACT_CACHE.pop(k, None)


def _cache_get(md5: str) -> Optional[dict]:
    if _redis is not None:
        try:
            raw = _redis.get(f"extract:{md5}")
            if raw:
                return json.loads(raw)
        except Exception as ex:
            logger.warning(f"Redis get failed, using in-process fallback: {ex}")
    return _EXTRACT_CACHE.get(md5)


def _cache_set(md5: str, value: dict) -> None:
    if _redis is not None:
        try:
            _redis.setex(f"extract:{md5}", _CACHE_TTL, json.dumps(value))
            return
        except Exception as ex:
            logger.warning(f"Redis set failed, storing in-process only: {ex}")
    _evict_in_process_cache()
    _EXTRACT_CACHE[md5] = value


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


# ── Document-type identification ──────────────────────────────────────────────
DOC_TYPE_KEYWORDS = {
    "dec_page":    ["declarations", "dec page", "policy declarations", "named insured",
                    "policy period", "coverage summary", "insuring agreement", "policy number"],
    "certificate": ["certificate of liability", "certificate of insurance", "acord 25",
                    "certificate holder", "evidence of insurance", "this is to certify"],
    "loss_run":    ["loss run", "loss history", "incurred", "reserve", "paid losses", "claimant", "date of loss"],
    "schedule":    ["schedule of", "vehicle schedule", "equipment schedule", "location schedule", "driver schedule"],
    "quote":       ["quote", "proposal", "indication", "estimated premium", "quoted premium"],
    "application": ["application", "acord 125", "acord 126", "acord 130", "prior application"],
    "endorsement": ["endorsement", "additional insured", "waiver of subrogation", "mortgagee"],
}


def identify_doc_type(text: str) -> str:
    tl     = text.lower()
    scores = {dt: sum(1 for kw in kws if kw in tl) for dt, kws in DOC_TYPE_KEYWORDS.items()}
    best   = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def select_primary_truth(docs: List[dict]) -> dict:
    priority = ["dec_page", "application", "quote", "schedule", "endorsement", "certificate", "loss_run", "unknown"]
    by_type  = {}
    for d in docs:
        by_type.setdefault(d["doc_type"], d)
    for p in priority:
        if p in by_type:
            return by_type[p]
    return docs[0]


# ── Core extraction ───────────────────────────────────────────────────────────

def extract_facts(text: str, low_confidence_tokens: Optional[List[str]] = None) -> dict:
    if len(text) < 30:
        return {"facts": {}, "flags": {}}

    cache_key = hashlib.md5((text[:7000] + f"|len={len(text)}").encode()).hexdigest()
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug(f"extract_facts cache hit {cache_key[:8]}")
        return cached

    low_conf_note = ""
    if low_confidence_tokens:
        unique_tokens = list(dict.fromkeys(low_confidence_tokens))[:40]
        low_conf_note = (
            "\n\nOCR CONFIDENCE WARNING: The following words/tokens were read with low OCR confidence "
            "and may be misread. Treat them cautiously — do not blindly copy them into extracted fields. "
            "If context suggests a correction (e.g. '0' vs 'O', '1' vs 'l'), apply it:\n"
            f"{', '.join(unique_tokens)}\n"
        )

    prompt = _EXTRACT_PROMPT_PREFIX + f'Text:\n"""\n{text[:7000]}\n"""{low_conf_note}'
    try:
        raw = groq_chat("llama-3.1-8b-instant", [{"role": "user", "content": prompt}])
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            raw = raw[s : e + 1]
        result = json.loads(raw)

        low_conf_set = {t.lower() for t in (low_confidence_tokens or [])}
        manual_confirmation_required: List[str] = []
        annotated: dict = {}

        for k, v in result.get("facts", {}).items():
            if v is None or isinstance(v, (list, dict)):
                annotated[k] = v
                continue
            str_val = str(v).strip()
            if not str_val or str_val.lower() in _NULL_STRINGS:
                annotated[k] = None
                continue
            confident = not any(token and token in str_val.lower() for token in low_conf_set)
            annotated[k] = {"value": str_val, "ocr_confident": confident}
            if not confident and k in _OCR_CRITICAL_FIELDS:
                manual_confirmation_required.append(k)

        result["facts"] = annotated
        if manual_confirmation_required:
            result["manual_confirmation_required"] = manual_confirmation_required

        _cache_set(cache_key, result)
        return result

    except Exception as ex:
        logger.error(f"Facts extraction error: {ex}")
        return {"facts": {}, "flags": {}}


# ── Chunking ──────────────────────────────────────────────────────────────────
_LONG_DOC_LIST_KEYS = [
    "locations", "property_locations", "auto_vin_schedule", "auto_garaging_addresses",
    "auto_drivers", "gl_class_codes_by_location", "wc_class_codes", "underlying_policies",
    "additional_named_insureds", "auto_covered_symbols",
]

# Max chunks per doc type — all types go through full chunked extraction.
# No doc type is truncated or given a special fast path.
# Adjust these numbers only if Groq cost becomes a real constraint,
# and only after measuring actual doc sizes in production.
DOC_TYPE_CHUNK_LIMITS: Dict[str, int] = {
    "dec_page":    10,
    "loss_run":    15,
    "schedule":    15,
    "certificate":  3,
    "endorsement":  8,
    "quote":        8,
    "application": 10,
    "default":     10,
}


def _chunk_by_lines(
    text: str,
    max_chars: int = 6500,
    overlap_lines: int = 10,
    max_chunks: int = 10,
) -> List[str]:
    lines  = text.splitlines(keepends=True)
    chunks: List[str] = []
    start  = 0

    while start < len(lines) and len(chunks) < max_chunks:
        buf:  List[str] = []
        size: int       = 0
        i = start

        while i < len(lines):
            line_len = len(lines[i])
            if size + line_len > max_chars and buf:
                break
            buf.append(lines[i])
            size += line_len
            i    += 1

        if not buf:
            buf = [lines[start]]
            i   = start + 1

        chunks.append("".join(buf))

        next_start = i - overlap_lines if i - overlap_lines > start else i
        if next_start <= start:
            next_start = i
        start = next_start

        if start >= len(lines):
            break

    return chunks or [text[:max_chars]]


# ── Merge helpers ─────────────────────────────────────────────────────────────

def _merge_list_fields(partials: List[dict], list_keys: List[str]) -> dict:
    if not partials:
        return {"facts": {}, "flags": {}}
    if len(partials) == 1:
        return partials[0]

    merged_facts: dict = {}
    merged_flags: dict = {}

    def _is_empty(v) -> bool:
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

    for partial in partials:
        for k, v in partial.get("facts", {}).items():
            if k in list_keys:
                continue
            if k not in merged_facts or _is_empty(merged_facts[k]):
                merged_facts[k] = v

    for lk in list_keys:
        seen: dict = {}
        for partial in partials:
            for item in (partial.get("facts", {}).get(lk) or []):
                key = json.dumps(item, sort_keys=True)
                seen.setdefault(key, item)
        if seen:
            merged_facts[lk] = list(seen.values())

    merged_wc: dict = {}
    for partial in partials:
        for state, amount in (partial.get("facts", {}).get("wc_payroll_by_state") or {}).items():
            merged_wc.setdefault(state, amount)
    if merged_wc:
        merged_facts["wc_payroll_by_state"] = merged_wc

    claim_vals = []
    for partial in partials:
        raw = partial.get("facts", {}).get("num_claims")
        val = raw.get("value", raw) if isinstance(raw, dict) else raw
        if val:
            try:
                claim_vals.append(int(str(val).replace(",", "")))
            except ValueError:
                pass
    if claim_vals:
        merged_facts["num_claims"] = {"value": str(max(claim_vals)), "ocr_confident": True}

    for partial in partials:
        for k, v in partial.get("flags", {}).items():
            if isinstance(v, bool):
                merged_flags[k] = merged_flags.get(k, False) or v
            elif k not in merged_flags or merged_flags[k] is None:
                merged_flags[k] = v

    return {"facts": merged_facts, "flags": merged_flags}


# ── Long-document extraction ──────────────────────────────────────────────────

def extract_facts_long(
    text: str,
    doc_type: str,
    low_confidence_tokens: Optional[List[str]] = None,
) -> dict:
    """
    Uniform chunked extraction for all doc types. No truncation, no special paths.
    All docs → _chunk_by_lines → per-chunk LLM call → merge.

    loss_run additionally runs a regex claim count over the FULL text and
    uses it if it exceeds the LLM-extracted value (LLM only sees chunks;
    regex sees everything).
    """
    if len(text) <= 7000:
        return extract_facts(text, low_confidence_tokens)

    max_chunks = DOC_TYPE_CHUNK_LIMITS.get(doc_type, DOC_TYPE_CHUNK_LIMITS["default"])
    overlap    = 5 if doc_type == "schedule" else 10
    chunks     = _chunk_by_lines(text, max_chars=6500, overlap_lines=overlap, max_chunks=max_chunks)
    partials   = [extract_facts(c, low_confidence_tokens) for c in chunks]
    result     = _merge_list_fields(partials, list_keys=_LONG_DOC_LIST_KEYS)

    # loss_run: regex over full text is more accurate than chunked LLM count
    if doc_type == "loss_run":
        regex_count = len(re.findall(
            r"(?:date\s+of\s+loss|claim\s*#|claim\s+number|claimant)", text, re.I
        ))
        if regex_count > 0:
            existing = result.get("facts", {}).get("num_claims")
            existing_val = 0
            if existing:
                try:
                    existing_val = int(str(
                        existing.get("value", existing) if isinstance(existing, dict) else existing
                    ).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            if regex_count > existing_val:
                result.setdefault("facts", {})
                result["facts"]["num_claims"] = {"value": str(regex_count), "ocr_confident": True}

    chars_processed = sum(len(c) for c in chunks)
    coverage        = chars_processed / len(text)
    if coverage < 0.80:
        pct = int(coverage * 100)
        result["truncation_warning"] = (
            f"Only {pct}% of this document ({chars_processed:,} of {len(text):,} chars) was processed "
            f"due to the {max_chunks}-chunk limit for doc_type '{doc_type}'. "
            "Some fields from later pages may be missing."
        )
        logger.warning(
            f"extract_facts_long: truncation on doc_type='{doc_type}' — "
            f"{pct}% coverage ({chars_processed}/{len(text)} chars, {len(chunks)} chunks)"
        )

    return result


# ── Multi-doc merge ───────────────────────────────────────────────────────────

def merge_facts(docs: List[dict], primary: dict) -> Tuple[dict, dict]:
    def _is_empty(v) -> bool:
        if v is None:
            return True
        if isinstance(v, list):
            return len(v) == 0
        if isinstance(v, dict) and "value" in v:
            inner = str(v["value"]).strip().lower()
            return not inner or inner in _NULL_STRINGS
        if isinstance(v, dict):
            return len(v) == 0
        return str(v).strip().lower() in _NULL_STRINGS

    mf: dict = {}
    mg: dict = {}

    for d in docs:
        if d["filename"] == primary["filename"]:
            continue
        for k, v in d["facts"].items():
            if not _is_empty(v):
                mf.setdefault(k, v)
        for k, v in d["flags"].items():
            if isinstance(v, bool):
                mg[k] = mg.get(k, False) or v
            elif not _is_empty(v):
                mg.setdefault(k, v)

    for k, v in primary["facts"].items():
        if not _is_empty(v):
            mf[k] = v
    for k, v in primary["flags"].items():
        if isinstance(v, bool):
            mg[k] = mg.get(k, False) or v
        elif not _is_empty(v):
            mg[k] = v

    return mf, mg