import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional

from config.database import get_db
from config.settings import FRONTEND_URL, groq_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

_FIELD_QUESTION_MAP = {
    "applicant_name":           "What is the full legal name of your business?",
    "dba_name":                 "Does your business operate under a DBA (doing business as) name? If yes, what is it?",
    "mailing_address":          "What is your business mailing address? (Street, City, State, ZIP)",
    "physical_address":         "What is the physical location of your business? (if different from mailing address)",
    "contact_name":             "What is the name of the primary contact for this insurance application?",
    "contact_phone":            "What is the best phone number to reach you?",
    "contact_email":            "What is the best email address for insurance-related correspondence?",
    "fein":                     "What is your Federal Employer Identification Number (FEIN / Tax ID)?",
    "entity_type":              "What is your business entity type? (e.g., LLC, Corporation, Sole Proprietor, Partnership)",
    "effective_date":           "What is the desired effective date for this insurance policy? (MM/DD/YYYY)",
    "expiration_date":          "What is the desired expiration date for this insurance policy? (MM/DD/YYYY)",
    "policy_number":            "What is the current or prior policy number, if applicable?",
    "lines_of_business":        "What lines of business or types of coverage are you requesting?",
    "total_revenue":            "What is your business's total annual revenue?",
    "total_payroll":            "What is your total annual payroll?",
    "num_employees":            "How many employees does your business have?",
    "operations_description":   "Please describe your business operations in detail. What products or services do you provide?",
    "prior_carrier":            "Who was your previous insurance carrier, if applicable?",
    "naics_code":               "What is your NAICS code (industry classification code), if known?",
    "sic_code":                 "What is your SIC code, if known?",
    "years_in_business":        "How many years has your business been in operation?",
    "gl_limits":                "What General Liability coverage limits are you requesting?",
    "gl_each_occurrence":       "What per-occurrence limit are you requesting for General Liability?",
    "gl_aggregate":             "What aggregate limit are you requesting for General Liability?",
    "gl_deductible":            "What deductible amount are you requesting for General Liability?",
    "gl_class_codes":           "What are the General Liability class codes for your operations?",
    "retro_date":               "What is the retroactive date for your claims-made General Liability policy?",
    "additional_insured":       "Are there any additional insureds that need to be listed on the policy?",
    "property_building_value":  "What is the replacement value of the building(s) to be insured?",
    "property_bpp_value":       "What is the value of your business personal property (equipment, inventory, etc.)?",
    "construction_type":        "What is the construction type of your building? (Frame, Masonry, Fire-Resistive, etc.)",
    "occupancy_type":           "How is the building primarily occupied or used?",
    "year_built":               "What year was the building constructed?",
    "roof_year":                "What year was the roof last replaced or updated?",
    "sprinkler_system":         "Does the building have a fire sprinkler system? (Yes/No)",
    "fire_protection_class":    "What is the fire protection class for the property location?",
    "valuation_method":         "How would you like the property valued — Replacement Cost Value (RCV) or Actual Cash Value (ACV)?",
    "coinsurance_percentage":   "What coinsurance percentage applies to the property?",
    "business_income_limit":    "What Business Income/Business Interruption limit are you requesting?",
    "period_of_restoration":    "What is the desired period of restoration for Business Income coverage?",
    "property_deductible_aop":  "What is the All Other Perils (AOP) property deductible?",
    "property_deductible_wind": "What is the wind/hail deductible for your property?",
    "mortgagee_name":           "Is there a mortgagee or loss payee on the property? If so, what is their name and address?",
    "auto_liability_limit":     "What Commercial Auto liability limits are you requesting?",
    "auto_deductible_comp":     "What comprehensive deductible are you requesting for Commercial Auto?",
    "auto_deductible_collision":"What collision deductible are you requesting for Commercial Auto?",
    "wc_payroll":               "What is the total payroll subject to Workers Compensation coverage?",
    "wc_class_codes":           "What Workers Compensation class codes apply to your employees?",
    "wc_xmod":                  "What is your Experience Modification Factor (X-Mod) for Workers Compensation?",
    "wc_officer_exclusions":    "Are any officers or owners to be excluded from Workers Compensation coverage?",
    "umbrella_limit":           "What Umbrella / Excess Liability limit are you requesting?",
    "umbrella_sir":             "What is the self-insured retention (SIR) for the Umbrella policy?",
    "percent_subcontracted":    "What percentage of your work is subcontracted to others?",
    "num_claims":               "How many insurance claims have you had in the past 3–5 years?",
    "loss_history_years":       "How many years of loss history are you providing?",
    "certificate_holder":       "Who is the certificate holder that needs to be listed on the certificate of insurance?",
}


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
            elif conf_val == "filled":
                continue  # deterministic fill → skip
            else:
                continue

    # Also include hard-stop fields that map to known fact keys
    tier1_fact_keys = ["applicant_name", "producer_name", "mailing_address", "effective_date",
                       "contact_name", "contact_phone", "contact_email", "lines_of_business"]
    for fk in tier1_fact_keys:
        if not facts.get(fk):
            if fk not in missing_fields:
                missing_fields[fk] = set()
                field_current_values[fk] = ""

    questions = []
    seen_questions = set()

    for field_name, form_ids in missing_fields.items():
        # Get human-readable question
        question_text = _FIELD_QUESTION_MAP.get(field_name)
        if not question_text:
            # Generate from field name
            question_text = field_name.replace("_", " ").replace("-", " ").title() + "?"


        if field_name in seen_questions:
            continue
        seen_questions.add(field_name)
        

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
                # Invalidate pdf cache so it regenerates
                form_data.pop("_pdf_cache_hash", None)
                form_data.pop("pdf_bytes", None)
                form_data.pop("signature_applied", None)
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