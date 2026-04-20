import re
from datetime import datetime
from typing import Tuple, List

from services.extraction_service import _fv

# ---------------------------------------------------------------------------
# Static data
# ---------------------------------------------------------------------------

US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR","VI","GU","MP","AS",
}

MONOPOLISTIC_WC_STATES = {"ND", "OH", "WA", "WY"}

PERSONAL_EMAIL_DOMAINS = {
    "gmail.com","yahoo.com","hotmail.com","outlook.com","icloud.com",
    "live.com","aol.com","msn.com","ymail.com","mail.com",
    "protonmail.com","proton.me","tutanota.com","zoho.com",
}

_DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%d/%m/%Y"]


# ---------------------------------------------------------------------------
# Individual validators — each returns (ok: bool, message: str)
# ---------------------------------------------------------------------------

def validate_work_email(email: str) -> Tuple[bool, str]:
    """Reject obviously personal email domains for producer/contact fields."""
    domain = email.lower().split("@")[-1] if "@" in email else ""
    if domain in PERSONAL_EMAIL_DOMAINS:
        return False, f"Please use a work email. Personal domains ({domain}) are not accepted."
    return True, ""


def validate_password(password: str) -> Tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    return True, ""


def validate_address(addr: str) -> Tuple[bool, str]:
    """Soft-validate a US mailing address for state code and ZIP presence."""
    if not addr:
        return True, ""
    parts       = addr.upper().split()
    state_found = any(p.strip(",.") in US_STATES for p in parts)
    zip_found   = bool(re.search(r"\b\d{5}(-\d{4})?\b", addr))
    if not state_found:
        return False, f"Address missing valid US state: '{addr}'"
    if not zip_found:
        return False, f"Address missing ZIP code: '{addr}'"
    return True, ""


def validate_phone(phone: str) -> Tuple[bool, str]:
    if not phone:
        return True, ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) not in (10, 11):
        return False, f"Phone '{phone}' should be 10 digits (11 with country code)"
    return True, ""


def validate_email_format(email: str) -> Tuple[bool, str]:
    if not email:
        return True, ""
    if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email.strip()):
        return False, f"Email '{email}' is not a valid email address"
    return True, ""


def validate_fein(fein: str) -> Tuple[bool, str]:
    """FEIN must be exactly 9 digits (hyphens stripped)."""
    if not fein:
        return True, ""
    digits = re.sub(r"[\-\s]", "", str(fein))
    if not digits.isdigit() or len(digits) != 9:
        return False, f"FEIN '{fein}' must be exactly 9 digits (XX-XXXXXXX format)"
    return True, ""


def validate_date_format(date_str: str, label: str = "Date") -> Tuple[bool, str]:
    """Accept common US and ISO date formats. Reject unparseable strings."""
    if not date_str:
        return True, ""
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(date_str.strip(), fmt)
            return True, ""
        except ValueError:
            continue
    return False, f"{label} '{date_str}' could not be parsed — use MM/DD/YYYY format"


def _parse_date(date_str: str):
    """Parse date string into datetime, returning None on failure."""
    if not date_str:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def validate_date_range(eff: str, exp: str) -> Tuple[bool, str]:
    """Effective date must be strictly before expiration date."""
    d_e = _parse_date(eff)
    d_x = _parse_date(exp)
    if d_e and d_x and d_e >= d_x:
        return False, "Effective date is on or after expiration date — policy period is invalid"
    return True, ""


def validate_percent(value: str, label: str = "Percentage") -> Tuple[bool, str]:
    """Percentage must be 0–100."""
    if not value:
        return True, ""
    try:
        pct = float(re.sub(r"[^\d.]", "", str(value)))
        if not 0 <= pct <= 100:
            return False, f"{label} '{value}' is outside the valid range (0–100)"
    except (ValueError, TypeError):
        return False, f"{label} '{value}' is not a valid number"
    return True, ""


def validate_monetary(value: str, label: str = "Amount") -> Tuple[bool, str]:
    """Monetary value must be a non-negative number."""
    if not value:
        return True, ""
    try:
        amt = float(re.sub(r"[^\d.]", "", str(value)))
        if amt < 0:
            return False, f"{label} '{value}' cannot be negative"
    except (ValueError, TypeError):
        return False, f"{label} '{value}' is not a valid monetary amount"
    return True, ""


# ---------------------------------------------------------------------------
# Aggregate validator — called by sqs_service.evaluate_stops()
# ---------------------------------------------------------------------------

def run_field_validations(facts: dict) -> Tuple[List[str], List[str]]:
    """
    Run all deterministic field-level validations against extracted facts.

    Returns (hard_stops, soft_stops):
      hard_stops — conditions that cap SQS at 60 and block submission
      soft_stops — conditions that cap SQS at 85 but allow submission

    This function is the ONLY place format/range validations run.
    sqs_service.evaluate_stops() calls this and extends the results with
    domain-level logic (COPE, WC, umbrella attachment, etc.).
    """
    hard: List[str] = []
    soft: List[str] = []

    # ── Contact / identity field validations (soft — user can correct) ──────
    for fn, validator in [
        ("mailing_address", validate_address),
        ("contact_phone",   validate_phone),
        ("contact_email",   validate_email_format),
    ]:
        val = _fv(facts, fn) or ""
        ok, msg = validator(val)
        if not ok:
            soft.append(msg)

    # ── FEIN format (soft — advisory, hard stop handled in check_doc_consistency) ──
    fein = _fv(facts, "fein") or ""
    if fein:
        ok, msg = validate_fein(fein)
        if not ok:
            soft.append(msg)

    # ── Date format validation ────────────────────────────────────────────────
    eff = _fv(facts, "effective_date") or ""
    exp = _fv(facts, "expiration_date") or ""

    if eff:
        ok, msg = validate_date_format(eff, "Effective date")
        if not ok:
            soft.append(msg)

    if exp:
        ok, msg = validate_date_format(exp, "Expiration date")
        if not ok:
            soft.append(msg)

    # ── Date range: effective must be before expiration (hard — invalid period) ─
    if eff and exp:
        ok, msg = validate_date_range(eff, exp)
        if not ok:
            hard.append(msg)

    # ── Percentage validations ────────────────────────────────────────────────
    for field, label in [
        ("percent_subcontracted",  "Subcontracted work percentage"),
        ("coinsurance_percentage", "Coinsurance percentage"),
        ("building_ITV_percentage","Building ITV percentage"),
    ]:
        val = _fv(facts, field) or ""
        if val:
            ok, msg = validate_percent(val, label)
            if not ok:
                soft.append(msg)

    # ── Monetary field validations ────────────────────────────────────────────
    for field, label in [
        ("total_revenue",           "Total revenue"),
        ("total_payroll",           "Total payroll"),
        ("wc_payroll",              "WC payroll"),
        ("property_building_value", "Building value"),
        ("property_bpp_value",      "BPP value"),
        ("umbrella_limit",          "Umbrella limit"),
        ("gl_each_occurrence",      "GL each occurrence limit"),
        ("gl_aggregate",            "GL aggregate limit"),
        ("auto_liability_limit",    "Auto liability limit"),
        ("business_income_limit",   "Business income limit"),
    ]:
        val = _fv(facts, field) or ""
        if val:
            ok, msg = validate_monetary(val, label)
            if not ok:
                soft.append(msg)

    # ── WC monopolistic state: if payroll in monopolistic states, hard stop ──
    wc_mono = _fv(facts, "wc_monopolistic_payroll")
    if isinstance(wc_mono, dict) and wc_mono:
        states_listed = {s.upper() for s in wc_mono.keys()}
        found_mono    = states_listed & MONOPOLISTIC_WC_STATES
        if found_mono:
            # This is informational here; sqs_service raises the actual stop
            # when wc_has_monopolistic_state flag is set. Don't double-add.
            pass

    return hard, soft