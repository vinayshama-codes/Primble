import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional

from config.database import get_db
from config.settings import FRONTEND_URL, groq_chat
from services.extraction_service import _fv, _focr
from services.fact_registry import _FIELD_QUESTION_MAP, _FIELD_TO_FORMS  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prefix-pattern map for suffixed/indexed field families.
# Each entry: (prefix, base_question, group_label)
# group_label is used to number repeated instances: "1st insurer", "2nd location" etc.
# ---------------------------------------------------------------------------
_ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th"]

def _ordinal(n: int) -> str:
    return _ORDINALS[n - 1] if 1 <= n <= len(_ORDINALS) else f"{n}th"

_FIELD_PREFIX_MAP: list[tuple[str, str, str]] = [
    # Insurer / carrier info (ACORD 25, 28 style)
    ("insurer_fullname",         "What is the full name of your insurance company?",                        "insurer"),
    ("insurer_name",             "What is the name of your insurance company?",                             "insurer"),
    ("insurer_naic",             "What is your insurance company's NAIC number? (Your agent can look this up if needed)", "insurer"),
    ("insurer_policy",           "What is the policy number for this insurance?",                           "insurer"),
    ("insurer_phone",            "What is the phone number for your insurance company?",                    "insurer"),
    ("insurer_address",          "What is the address of your insurance company?",                          "insurer"),
    ("insurer_",                 "Please provide the details for your insurance company.",                  "insurer"),
    # Additional insured / interest
    ("additional_insured_name",  "What is the name of the additional person or company to be listed on the policy?", "additional party"),
    ("additional_insured_addr",  "What is the address of the additional person or company to be listed on the policy?", "additional party"),
    ("additional_insured_",      "Please provide the details for the additional party to be listed on your policy.", "additional party"),
    ("additional_interest_name", "What is the name of the additional interested party?",                    "additional party"),
    ("additional_interest_",     "Please provide details for the additional interested party.",              "additional party"),
    # Location fields
    ("location_address",         "What is the address of this business location?",                         "location"),
    ("location_city",            "What city is this business location in?",                                 "location"),
    ("location_state",           "What state is this business location in?",                                "location"),
    ("location_zip",             "What is the ZIP code for this business location?",                        "location"),
    ("location_",                "Please provide the details for this business location.",                  "location"),
    # Vehicle fields
    ("vehicle_vin",              "What is the VIN (Vehicle Identification Number) for this vehicle?",       "vehicle"),
    ("vehicle_year",             "What year is this vehicle?",                                              "vehicle"),
    ("vehicle_make",             "What is the make (brand) of this vehicle?",                               "vehicle"),
    ("vehicle_model",            "What is the model of this vehicle?",                                      "vehicle"),
    ("vehicle_",                 "Please provide the details for this vehicle.",                            "vehicle"),
    # Driver fields
    ("driver_name",              "What is the full name of this driver?",                                   "driver"),
    ("driver_license",           "What is the driver's license number for this driver?",                    "driver"),
    ("driver_dob",               "What is the date of birth for this driver? (MM/DD/YYYY)",                 "driver"),
    ("driver_",                  "Please provide the details for this driver.",                             "driver"),
    # Owner / officer fields
    ("owner_name",               "What is the full name of this owner or officer?",                        "owner"),
    ("owner_title",              "What is the title or role of this owner or officer?",                     "owner"),
    ("owner_ownership",          "What percentage of the business does this person own?",                   "owner"),
    ("owner_",                   "Please provide the details for this owner or officer.",                   "owner"),
    # Claim / loss fields
    ("claim_date",               "What was the date of this claim or loss? (MM/DD/YYYY)",                  "claim"),
    ("claim_amount",             "What was the total amount paid or reserved for this claim?",              "claim"),
    ("claim_description",        "Briefly describe what happened for this claim.",                          "claim"),
    ("claim_",                   "Please provide the details for this claim.",                              "claim"),
    # Schedule / item fields
    ("schedule_item",            "Please describe this scheduled item (make, model, value, or serial number).", "item"),
    ("schedule_value",           "What is the value of this scheduled item?",                              "item"),
    ("schedule_",                "Please provide details for this scheduled item.",                        "item"),
]


# ---------------------------------------------------------------------------
# Word splitter — converts concatenated PDF field tokens into readable words
# e.g. "generalliability" → "general liability"
#      "limitappliesperpolicyindicator" → "limit applies per policy indicator"
# ---------------------------------------------------------------------------

# Ordered longest-first so greedy matching works correctly
_INSURANCE_WORDS = sorted([
    "certificateofinsurance", "certificate", "workerscompensation", "workers", "compensation",
    "generalliability", "general", "liability", "automobile", "commercial",
    "umbrella", "excess", "property", "inland", "marine",
    "additional", "insured", "holder", "indicator", "description",
    "aggregate", "occurrence", "limit", "limits", "applies", "applied",
    "per", "policy", "project", "location", "other",
    "employers", "employer", "employee", "person", "persons",
    "excluded", "exclusion", "waiver", "subrogation",
    "each", "any", "all", "code", "codes", "type", "types",
    "name", "fullname", "full", "address", "phone", "email",
    "number", "amount", "date", "year", "state", "city", "zip",
    "effective", "expiration", "retroactive", "inception",
    "deductible", "retention", "self", "insured",
    "bodily", "injury", "property", "damage", "personal", "advertising",
    "products", "completed", "operations", "fire", "legal",
    "medical", "payments", "combined", "single",
    "owned", "hired", "non", "scheduled", "uninsured", "motorist",
    "statutory", "disease", "accident", "benefit",
    "builder", "risk", "installation", "equipment",
    "auto", "auto", "vehicle", "driver", "owner", "officer",
    "location", "schedule", "item", "value",
    "named", "insurer", "carrier", "company",
    "revision", "agency", "agent", "broker", "producer",
    "contact", "fax", "naic", "id",
], key=len, reverse=True)

_SPLIT_CACHE: dict[str, str] = {}

def _split_concatenated(token: str) -> str:
    """Split a run-together word into spaced words using greedy longest-match."""
    token = token.strip().lower()
    if not token:
        return token
    if token in _SPLIT_CACHE:
        return _SPLIT_CACHE[token]

    original = token
    result_parts = []
    while token:
        matched = False
        for word in _INSURANCE_WORDS:
            if token.startswith(word):
                result_parts.append(word)
                token = token[len(word):]
                matched = True
                break
        if not matched:
            # consume one char as-is
            result_parts.append(token[0])
            token = token[1:]

    result = " ".join(result_parts)
    _SPLIT_CACHE[original] = result
    return result


def _field_name_to_readable(field_name: str) -> str:
    """
    Convert a raw PDF field name to a readable phrase.
    Handles:
      - snake_case separators
      - camelCase
      - concatenated insurance terms
      - trailing _a/_b/_1/_2 suffixes (stripped)
    """
    # Strip trailing index suffix
    name = re.sub(r'[_\s]+[a-z]$', '', field_name)
    name = re.sub(r'[_\s]+\d+$', '', name)

    # Split on underscores/hyphens → tokens
    tokens = re.split(r'[_\-\s]+', name)

    # camelCase split within each token
    expanded = []
    for tok in tokens:
        # insert space before uppercase runs: "myField" → "my Field"
        tok = re.sub(r'([a-z])([A-Z])', r'\1 \2', tok)
        tok = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', tok)
        # now split concatenated lowercase
        for sub in tok.split():
            expanded.append(_split_concatenated(sub))

    readable = " ".join(expanded).strip()
    # Collapse multiple spaces
    readable = re.sub(r'\s+', ' ', readable)
    return readable.lower()


# ---------------------------------------------------------------------------
# Groq batch humanizer — single LLM call for all fallback fields
# ---------------------------------------------------------------------------

_HUMANIZED_CACHE: dict[str, str] = {}  # field_name → humanized question


def _humanize_fields_with_groq(field_names: list[str]) -> dict[str, str]:
    """
    Send a batch of readable field phrases to Groq and get back plain-language
    client-facing questions. Returns {field_name: question_text}.
    Uncached fields only; results merged into _HUMANIZED_CACHE.
    """
    uncached = [f for f in field_names if f not in _HUMANIZED_CACHE]
    if not uncached:
        return {f: _HUMANIZED_CACHE[f] for f in field_names}

    # Build numbered list of readable phrases for the prompt
    readable_map = {f: _field_name_to_readable(f) for f in uncached}
    numbered_lines = "\n".join(
        f"{i+1}. {readable_map[f]}" for i, f in enumerate(uncached)
    )

    prompt = f"""You are helping convert insurance form field names into clear, plain-language questions for business owners filling out an insurance application. They are not insurance professionals.

Below is a numbered list of field descriptions (derived from internal form field names). For each one, write a single plain-language question a non-expert would understand. Follow these rules:
- Write in second person ("What is your...", "Does your business...", "Please provide...")
- No jargon, abbreviations, or technical terms
- Keep it concise — one sentence per question
- For yes/no fields containing words like "indicator", "included", "excluded", "applies", write a yes/no question
- For name/address/code fields, ask for the value directly
- Preserve the meaning exactly

Return ONLY a JSON object mapping each number (as a string key) to the question. No explanation, no markdown, no extra text. Example format:
{{"1": "Does the general aggregate limit apply per policy?", "2": "What is the full name of the certificate holder?"}}

Fields:
{numbered_lines}"""

    try:
        raw    = groq_chat("llama-3.3-70b-versatile", [{"role": "user", "content": prompt}],
                           temperature=0.2, max_tokens=1500)
        raw    = re.sub(r'^```[a-z]*\n?', '', raw)
        raw    = re.sub(r'\n?```$', '', raw)
        parsed: dict = json.loads(raw)

        for i, field_name in enumerate(uncached):
            q = parsed.get(str(i + 1), "").strip()
            if q:
                _HUMANIZED_CACHE[field_name] = q
            else:
                # Groq skipped this one — use readable fallback
                _HUMANIZED_CACHE[field_name] = f"Please provide your {readable_map[field_name]}."

    except Exception as ex:
        logger.warning(f"ARQ: Groq humanization failed ({ex}), using readable fallback for {len(uncached)} fields")
        for field_name in uncached:
            _HUMANIZED_CACHE[field_name] = f"Please provide your {readable_map[field_name]}."

    return {f: _HUMANIZED_CACHE[f] for f in field_names}


def _resolve_question(field_name: str) -> tuple[str, str | None]:
    """
    Return (base_question_text, group_label_or_None).
    group_label is non-None when this field belongs to a numbered family
    (e.g. insurers, locations) so the caller can append "1st insurer" etc.
    Falls back to Groq humanization (called in batch from generate_arq_questions).
    """
    # 1. Exact match — no grouping needed
    q = _FIELD_QUESTION_MAP.get(field_name)
    if q:
        return q, None

    # 2. Strip trailing index suffix (_a … _z, _1 … _99) and try exact map again
    base_name = re.sub(r'[_\s]+[a-z]$', '', field_name)
    base_name = re.sub(r'[_\s]+\d+$',   '', base_name)
    q = _FIELD_QUESTION_MAP.get(base_name)
    if q:
        return q, None  # known field, suffix was noise — no numbering needed

    # 3. Prefix pattern match
    for candidate in (field_name, base_name):
        lower = candidate.lower()
        for prefix, question, group_label in _FIELD_PREFIX_MAP:
            if lower.startswith(prefix):
                return question, group_label

    # 4. Groq-humanized (pre-populated by caller before _resolve_question is called)
    if field_name in _HUMANIZED_CACHE:
        return _HUMANIZED_CACHE[field_name], None

    # 5. Readable fallback (should rarely hit — only if Groq batch was skipped)
    readable = _field_name_to_readable(field_name)
    return f"Please provide your {readable}.", None


def _clean_answer(raw: str, field_name: str) -> Optional[str]:
    """
    Sanitize and validate a client-provided answer.
    Returns cleaned string or None if the answer is invalid/empty.
    """
    if raw is None:
        return None
    val = str(raw).strip()
    # Empty / placeholder values
    if not val or val.lower() in ("n/a", "na", "?", "unknown", "none", "null", "-", "--", "tbd", "unsure"):
        return None
    # For policy number fields, extract digits/alphanumeric from noisy answers
    if "policy_number" in field_name.lower():
        # Strip common prefixes like "Policy Number 123" → "123"
        val = re.sub(r"(?i)^policy\s*(number|#|no\.?|num\.?)[\s:]*", "", val).strip()
    # Truncate excessively long answers (max 500 chars)
    if len(val) > 500:
        val = val[:500].strip()
    return val if val else None


def generate_arq_questions(
    facts: dict,
    flags: dict,
    generated_forms: dict,
    hard_stops: list,
    soft_stops: list,
) -> List[dict]:
    """
    Generate deduplicated plain-language questions for missing/questionable fields
    across all generated forms, grouped by field (one question per unique field).
    """
    # Collect missing fields across all forms
    missing_fields: dict = {}  # field_name -> set of form_ids
    field_current_values: dict = {}

    for form_id, form_data in generated_forms.items():
        confidence    = form_data.get("confidence", {})
        mapped        = form_data.get("field_state") or form_data.get("mapped", {})
        client_filled = set(form_data.get("client_filled_fields", []))

        for field_name, conf_val in confidence.items():
            if field_name in client_filled:
                continue
            if any(p in field_name.lower() for p in ["signature", "sig_", "_sig"]):
                continue
            raw_val     = mapped.get(field_name)
            current_val = str(raw_val).strip() if raw_val is not None else ""
            is_empty    = current_val == "" or current_val in ("null", "None")

            if conf_val == "missing_required":
                pass  # always include
            elif conf_val == "low_confidence" and is_empty:
                pass  # empty low_confidence → include
            elif conf_val == "low_confidence" and not is_empty:
                continue  # AI filled with value → skip
            elif conf_val == "filled" and is_empty:
                pass  # marked filled but actually empty → include
            elif conf_val == "filled" and not is_empty:
                continue  # genuinely filled → skip
            else:
                continue

            if field_name not in missing_fields:
                missing_fields[field_name] = set()
                field_current_values[field_name] = current_val
            missing_fields[field_name].add(form_id)
        
    # Also include hard-stop fields that map to known fact keys
    tier1_fact_keys = ["applicant_name", "producer_name", "mailing_address", "effective_date",
                       "contact_name", "contact_phone", "contact_email", "lines_of_business"]
    for fk in tier1_fact_keys:
        if not facts.get(fk):
            if fk not in missing_fields:
                missing_fields[fk] = set()
                field_current_values[fk] = ""

    # Sweep _FIELD_QUESTION_MAP: any fact that is null AND relevant to at least one
    # generated form gets a question even if the PDF confidence loop missed it.
    active_form_ids = set(generated_forms.keys())
    for fact_key in _FIELD_QUESTION_MAP:
        if fact_key in missing_fields:
            continue  # already captured above
        relevant_forms = _FIELD_TO_FORMS.get(fact_key, set())
        if relevant_forms and not (relevant_forms & active_form_ids):
            continue  # not relevant to any form in this submission
        val = facts.get(fact_key)
        is_null = (
            val is None
            or (isinstance(val, str) and not val.strip())
            or (isinstance(val, list) and not val)
            or (isinstance(val, dict) and not val)
        )
        if not is_null:
            continue
        affected = (relevant_forms & active_form_ids) if relevant_forms else active_form_ids
        missing_fields[fact_key] = affected
        field_current_values[fact_key] = ""

    # Low-confidence sweep: surface facts that are non-null but OCR-uncertain.
    # These go into missing_fields so the question builder picks them up, and
    # into _ocr_low_conf_fields so the builder can prefix "Please confirm: ".
    _ocr_low_conf_fields: set = set()
    for fact_key in _FIELD_QUESTION_MAP:
        if fact_key in missing_fields:
            continue  # already in queue (null case)
        if _focr(facts, fact_key):
            continue  # confident or not annotated → skip
        relevant_forms = _FIELD_TO_FORMS.get(fact_key, set())
        if relevant_forms and not (relevant_forms & active_form_ids):
            continue  # not relevant to any generated form
        affected = (relevant_forms & active_form_ids) if relevant_forms else active_form_ids
        missing_fields[fact_key] = affected
        field_current_values[fact_key] = str(_fv(facts, fact_key) or "")
        _ocr_low_conf_fields.add(fact_key)

    questions = []
    seen_field_names = set()
    group_counts: dict[str, int] = {}

    # Pre-identify fields that will need Groq humanization (miss both maps)
    # and batch them in a single LLM call before the loop runs.
    groq_needed = []
    for field_name in missing_fields:
        if field_name in _FIELD_QUESTION_MAP:
            continue
        base = re.sub(r'[_\s]+[a-z]$', '', field_name)
        base = re.sub(r'[_\s]+\d+$', '', base)
        if base in _FIELD_QUESTION_MAP:
            continue
        lower = field_name.lower()
        base_lower = base.lower()
        if any(lower.startswith(p) or base_lower.startswith(p) for p, _, __ in _FIELD_PREFIX_MAP):
            continue
        if field_name not in _HUMANIZED_CACHE:
            groq_needed.append(field_name)

    if groq_needed:
        _humanize_fields_with_groq(groq_needed)

    for field_name, form_ids in missing_fields.items():
        if field_name in seen_field_names:
            continue
        seen_field_names.add(field_name)

        base_question, group_label = _resolve_question(field_name)

        # If this field belongs to a numbered group (insurer, location, driver, etc.)
        # append an ordinal so "1st insurer", "2nd insurer" etc. are distinct.
        if group_label is not None:
            group_counts[group_label] = group_counts.get(group_label, 0) + 1
            count = group_counts[group_label]
            if count == 1:
                # First occurrence — no number yet; will be retroactively numbered
                # when/if a second appears (via _group_label scan below).
                question_text = base_question
            else:
                # Second+ occurrence: number this one
                question_text = f"{base_question} ({_ordinal(count)} {group_label})"
                # Retroactively number the first entry if this is the 2nd
                if count == 2:
                    for prev_q in questions:
                        if prev_q.get("_group_label") == group_label:
                            prev_q["question"] = f"{base_question} (1st {group_label})"
                            break
        else:
            question_text = base_question

        if field_name in _ocr_low_conf_fields:
            question_text = "Please confirm: " + question_text

        # Build list of form names
        form_names_list = []
        for fid in sorted(form_ids):
            fd = generated_forms.get(fid, {})
            fn = fd.get("form_name", fid)
            # Extract just the ACORD number e.g. "ACORD_125" -> "125"
            num = fid.replace("ACORD_", "").replace("ACORD ", "")
            form_names_list.append(num)

        # Determine field type from schema
        field_type = "text"
        for fid in form_ids:
            schema = generated_forms.get(fid, {}).get("schema", {})
            field_meta = schema.get(field_name, {})
            if isinstance(field_meta, dict):
                ft = field_meta.get("ft", "")
                if "/Btn" in ft:
                    field_type = "checkbox"
                    break

        questions.append({
            "field_name":    field_name,
            "question":      question_text,
            "forms":         ", ".join(sorted(set(form_names_list))),
            "form_ids":      list(form_ids),
            "field_type":    field_type,
            "current_value": field_current_values.get(field_name, ""),
            "_group_label":  group_label,  # internal — stripped before return
        })

    # Strip internal key before returning
    for q in questions:
        q.pop("_group_label", None)

    return questions


def generate_arq_questions_from_facts(
    facts: dict,
    flags: dict,
    selected_form_ids: List[str],
    hard_stops: list,
    soft_stops: list,
) -> List[dict]:
    """
    Generate plain-language ARQ questions for the Clarity pipeline (no generated PDFs).
    Iterates _FIELD_QUESTION_MAP and emits a question for each fact key that is
    null/empty AND whose _FIELD_TO_FORMS entry intersects selected_form_ids.
    Return shape matches generate_arq_questions() so callers are interchangeable.
    """
    selected = set(selected_form_ids)
    questions: List[dict] = []
    seen: set = set()

    for fact_key, base_question in _FIELD_QUESTION_MAP.items():
        if fact_key in seen:
            continue
        relevant_forms = _FIELD_TO_FORMS.get(fact_key, set())
        # If the field has a known form mapping, require at least one to be selected.
        # If there's no entry in _FIELD_TO_FORMS, include it unconditionally.
        if relevant_forms and not (relevant_forms & selected):
            continue

        val = facts.get(fact_key)
        is_null = (
            val is None
            or (isinstance(val, str) and not val.strip())
            or (isinstance(val, list) and not val)
            or (isinstance(val, dict) and not val)
        )
        is_low_conf = not _focr(facts, fact_key)

        if is_null:
            question_out  = base_question
            current_val   = ""
        elif is_low_conf:
            question_out  = "Please confirm: " + base_question
            current_val   = str(_fv(facts, fact_key) or "")
        else:
            continue  # filled and confident → skip

        seen.add(fact_key)
        affected_ids = sorted(relevant_forms & selected) if relevant_forms else sorted(selected)
        form_nums    = [fid.replace("ACORD_", "") for fid in affected_ids]
        questions.append({
            "field_name":    fact_key,
            "question":      question_out,
            "forms":         ", ".join(form_nums),
            "form_ids":      affected_ids,
            "field_type":    "text",
            "current_value": current_val,
        })

    return questions


# ---------------------------------------------------------------------------
# ARQ session CRUD
# ---------------------------------------------------------------------------

def create_arq_session(
    processing_session_id: str,
    user_id: str,
    client_email: str,
    client_name: str,
    questions: List[dict],
    expires_days: int = 7,
) -> dict:
    arq_id  = str(uuid.uuid4())
    token   = str(uuid.uuid4()).replace("-", "") + str(uuid.uuid4()).replace("-", "")
    now     = datetime.now(timezone.utc).isoformat()
    expires = (datetime.now(timezone.utc) + timedelta(days=expires_days)).isoformat()

    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        """INSERT INTO arq_sessions
           (id, session_id, user_id, token, email, client_name, status, questions, answers,
            expires_at, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,'pending',%s,'{}', %s,%s)""",
        (arq_id, processing_session_id, user_id, token,
         client_email, client_name or "",
         json.dumps(questions), expires, now),
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"ARQ session created: {arq_id} for session={processing_session_id}")
    return {"arq_id": arq_id, "token": token, "expires_at": expires}


def get_arq_by_token(token: str) -> Optional[dict]:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM arq_sessions WHERE token = %s", (token,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    result = dict(row)
    if isinstance(result.get("questions"), str):
        result["questions"] = json.loads(result["questions"])
    if isinstance(result.get("answers"), str):
        result["answers"] = json.loads(result["answers"])
    return result


def get_arq_by_id(arq_id: str) -> Optional[dict]:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM arq_sessions WHERE id = %s", (arq_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    result = dict(row)
    if isinstance(result.get("questions"), str):
        result["questions"] = json.loads(result["questions"])
    if isinstance(result.get("answers"), str):
        result["answers"] = json.loads(result["answers"])
    return result


def get_arq_sessions_for_user(user_id: str) -> List[dict]:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM arq_sessions WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if isinstance(r.get("questions"), str):
            r["questions"] = json.loads(r["questions"])
        if isinstance(r.get("answers"), str):
            r["answers"] = json.loads(r["answers"])
    return rows


def mark_arq_viewed(token: str):
    now  = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE arq_sessions SET viewed_at=%s WHERE token=%s AND viewed_at IS NULL",
        (now, token),
    )
    conn.commit()
    cur.close()
    conn.close()


def submit_arq_answers(
    token: str,
    raw_answers: dict,
    processing_session_id: str,
    generated_forms: dict,
) -> Tuple[bool, str, List[str]]:
    """
    Validate answers, map them back to form fields, update processing session.
    Returns (success, message, list_of_updated_field_names).
    """
    arq = get_arq_by_token(token)
    if not arq:
        return False, "ARQ session not found.", []

    now = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return False, "This questionnaire link has expired.", []

    if arq["status"] == "submitted":
        return False, "This questionnaire has already been submitted.", []

    questions    = arq["questions"]
    cleaned      = {}
    updated_fields = []

    for q in questions:
        field_name = q["field_name"]
        raw_val    = raw_answers.get(field_name, "")
        # For checkboxes, allow "Yes"/"No"
        if q.get("field_type") == "checkbox":
            cleaned_val = raw_val if raw_val in ("Yes", "No", "true", "false") else None
        else:
            cleaned_val = _clean_answer(raw_val, field_name)

        if cleaned_val is not None:
            cleaned[field_name] = cleaned_val
            updated_fields.append(field_name)

    # Persist cleaned answers to arq_sessions
    now_iso = now.isoformat()
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE arq_sessions SET answers=%s, status='submitted', submitted_at=%s WHERE token=%s",
        (json.dumps(cleaned), now_iso, token),
    )
    conn.commit()
    cur.close()
    conn.close()

    return True, "Answers submitted successfully.", updated_fields


def apply_arq_answers_to_session(
    arq_id: str,
    processing_session_id: str,
) -> Tuple[bool, List[str]]:
    """
    Apply submitted ARQ answers to the processing session's generated forms.
    Called after client submits — updates field_state across all affected forms.
    Returns (success, updated_field_names).
    """
    from repositories.session_repository import get_processing_session, upd_processing_session

    arq = get_arq_by_id(arq_id)
    if not arq or arq["status"] != "submitted":
        return False, []

    answers   = arq.get("answers", {})
    questions = arq.get("questions", [])
    if not answers:
        return True, []

    # Build a map: field_name -> list of form_ids
    field_to_forms: dict = {}
    for q in questions:
        fn = q["field_name"]
        if fn in answers:
            field_to_forms[fn] = q.get("form_ids", [])

    try:
        proc_session = get_processing_session(processing_session_id)
    except Exception as ex:
        logger.error(f"apply_arq_answers: cannot load session {processing_session_id}: {ex}")
        return False, []

    generated = proc_session.get("generated_forms", {})
    updated   = []

    for field_name, form_ids in field_to_forms.items():
        new_val = answers[field_name]
        # Apply to all affected forms (and also propagate to all forms sharing the field)
        for fid, form_data in generated.items():
            field_state = form_data.get("field_state") or form_data.get("mapped", {})
            schema      = form_data.get("schema", {})
            if field_name in schema or field_name in field_state or fid in form_ids:
                field_state[field_name] = new_val
                form_data["field_state"] = field_state
                if "confidence" in form_data:
                    form_data["confidence"][field_name] = "filled"
                # Invalidate pdf cache so it regenerates.
                # Use assignment (not pop) so dict.update() in upd_processing_session
                # actually overwrites these keys in the stored session.
                # signature_applied is intentionally left unchanged — if the form was
                # signed, regeneration will re-apply the signature via signature_b64.
                form_data["_pdf_cache_hash"] = ""
                form_data["pdf_bytes"] = None
        if field_name not in updated:
            updated.append(field_name)

    upd_processing_session(processing_session_id, {"generated_forms": generated})
    logger.info(f"ARQ {arq_id}: applied {len(updated)} fields to session {processing_session_id}")
    return True, updated


def get_client_filled_fields(processing_session_id: str) -> List[str]:
    """Return list of field names that were filled via ARQ for highlighting in editor."""
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT answers FROM arq_sessions WHERE session_id=%s AND status='submitted'",
        (processing_session_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    fields = []
    for row in rows:
        answers = row["answers"]
        if isinstance(answers, str):
            answers = json.loads(answers)
        if isinstance(answers, dict):
            fields.extend(answers.keys())
    return list(set(fields))


def send_arq_reminder(arq_id: str, user: dict) -> bool:
    """Send a manual or automatic reminder for an ARQ session."""
    from services.email_service import send_arq_reminder_email

    arq = get_arq_by_id(arq_id)
    if not arq or arq["status"] == "submitted":
        return False

    now       = datetime.now(timezone.utc)
    expires   = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return False

    arq_link     = f"{FRONTEND_URL}/questionnaire/{arq['token']}"
    producer_name = user.get("full_name", "") or user.get("email", "")
    first_name    = producer_name.split()[0] if producer_name else "Your Agent"

    ok = send_arq_reminder_email(
        to_email=arq["email"],
        client_name=arq.get("client_name", ""),
        producer_full_name=producer_name,
        producer_first_name=first_name,
        arq_link=arq_link,
    )

    if ok:
        now_iso = now.isoformat()
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """UPDATE arq_sessions
               SET reminder_sent=1,
                   reminder_count=COALESCE(reminder_count,0)+1,
                   last_reminder_at=%s
               WHERE id=%s""",
            (now_iso, arq_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    return ok


def create_arq_notification(arq_id: str, user_id: str, notif_type: str):
    notif_id = str(uuid.uuid4())
    now      = datetime.now(timezone.utc).isoformat()
    conn     = get_db()
    cur      = conn.cursor()
    cur.execute(
        "INSERT INTO arq_notifications (id, arq_id, user_id, type, read_status, created_at) VALUES (%s,%s,%s,%s,0,%s)",
        (notif_id, arq_id, user_id, notif_type, now),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_arq_notifications(user_id: str) -> List[dict]:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM arq_notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT 50",
        (user_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def mark_notifications_read(user_id: str):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(
        "UPDATE arq_notifications SET read_status=1 WHERE user_id=%s",
        (user_id,),
    )
    conn.commit()
    cur.close()
    conn.close()