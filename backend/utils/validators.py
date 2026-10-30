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

# Full US state names accepted by validate_address so addresses written with
# the full state name ("Denver, Colorado 80216") pass the same as those using
# the abbreviation ("Denver, CO 80216"). Multi-word states use a space so the
# substring check in validate_address catches them correctly.
_US_STATE_FULL_NAMES = frozenset({
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada",
    "new hampshire","new jersey","new mexico","new york","north carolina",
    "north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island",
    "south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming",
    "district of columbia",
})

MONOPOLISTIC_WC_STATES = {"ND", "OH", "WA", "WY"}

# Kept for _parse_date / validate_date_range which need datetime objects.
# validate_date_format now delegates to normalization.normalize_date so this
# list is only used internally by those two helpers.
_DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%d/%m/%Y",
                 "%Y/%m/%d", "%m-%d-%y", "%m.%d.%Y", "%m.%d.%y"]


# ---------------------------------------------------------------------------
# Individual validators — each returns (ok: bool, message: str)
# ---------------------------------------------------------------------------


def validate_password(password: str) -> Tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    return True, ""


def validate_address(addr: str) -> Tuple[bool, str]:
    """Soft-validate a US mailing address for state code and ZIP presence.

    Accepts both 2-letter abbreviations ("CO") and full state names
    ("Colorado", "West Virginia") so addresses OCR'd or typed with the full
    name do not produce a spurious soft-stop.
    """
    if not addr:
        return True, ""
    # Commas split too (owner, 14 Oct 2026): "Dnver,CO, 20132" was one token,
    # so a typed CO read as "missing valid US state".
    parts       = [p for p in re.split(r"[\s,]+", addr.upper()) if p]
    addr_lower  = addr.lower()
    state_found = (
        any(p.strip(",.") in US_STATES for p in parts)
        or any(name in addr_lower for name in _US_STATE_FULL_NAMES)
    )
    zip_found   = bool(re.search(r"\b\d{5}(-\d{4})?\b", addr))
    if not state_found:
        return False, f"Address missing valid US state: '{addr}'"
    if not zip_found:
        return False, f"Address missing ZIP code: '{addr}'"
    return True, ""


_PHONE_EXTENSION_RE = re.compile(r"(?i)\s*(?:x|ext\.?|extension)\s*\d{1,6}\s*$")


def phone_main_digits(phone: str) -> str:
    """The digits of the number itself - an extension ("x12", "ext. 12") is part
    of a correct answer and never counted against the 10 digits."""
    return re.sub(r"\D", "", _PHONE_EXTENSION_RE.sub("", str(phone or "")))


def validate_phone(phone: str) -> Tuple[bool, str]:
    if not phone:
        return True, ""
    if len(phone_main_digits(phone)) not in (10, 11):
        return False, f"Phone '{phone}' should be 10 digits (11 with country code)"
    return True, ""


def validate_email_format(email: str) -> Tuple[bool, str]:
    """The same rule the answer box applies (fact_registry._is_email, 15 Oct
    2026): a real address with an apostrophe (o'brien@...) is correct, and the
    stricter pattern this used flagged it after the box had accepted it."""
    if not email:
        return True, ""
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
        return False, f"Email '{email}' is not a valid email address"
    return True, ""


def validate_fein(fein: str) -> Tuple[bool, str]:
    """FEIN must be exactly 9 digits (hyphens stripped)."""
    if not fein:
        return True, ""
    digits = re.sub(r"[\-\s]", "", str(fein))
    if not digits.isdigit() or len(digits) != 9:
        return False, f"FEIN '{fein}' must be exactly 9 digits (XX-XXXXXXX format)"
    from services.normalization import is_placeholder_fein
    if is_placeholder_fein(digits):
        return False, f"FEIN '{fein}' is a placeholder, not a tax ID - enter the real EIN"
    return True, ""


def validate_date_format(date_str: str, label: str = "Date") -> Tuple[bool, str]:
    """Accept common US and ISO date formats. Reject unparseable strings.

    Delegates to normalization.normalize_date so the accepted format list stays
    in sync with the rest of the pipeline (no more divergence between validators).
    """
    if not date_str:
        return True, ""
    from services.normalization import normalize_date
    if normalize_date(date_str) is not None:
        return True, ""
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
        return False, "Effective date is on or after expiration date - policy period is invalid"
    return True, ""


# The same backwards term when no PERSON supplied either date (21 Oct 2026). It
# shares its opening words with the hard message above, so ONE rule row
# (`issue_registry`, "legacy_policy_term_backwards") codes both and opens the
# proposed-term window - the way "Policy term already expired" codes its hard
# and its read-from-a-document sentence. Static, so its issue id is stable.
#
# THE FIX LINE SAYS "CORRECT", NOT "CONFIRM" (21 Oct 2026 review, M2). A
# backwards pair cannot be confirmed - confirming it is what used to turn this
# warning into the hard stop. The save door refuses a backwards pair a person
# supplies (`term_save_refusal`), so the only way out is a correction.
BACKWARDS_TERM_TO_CONFIRM = (
    "Effective date is on or after expiration date in the dates read from your "
    "documents. Fix: Correct the proposed effective or expiration date."
)

# What the save door says when a person's save would leave the proposed term
# running backwards (21 Oct 2026 review, M2). Plain words, no em-dash.
TERM_BACKWARDS_REFUSAL = "The expiration date must be after the effective date."

# ...and when it would leave the proposed term already ENDED - its expiration
# before today (22 Oct 2026, Z31-N group C). Same door, same reason: a
# "Confirm these values" save of a document's expired term made that
# expiration a person's, and the expired-term warning a hard stop (Z30 open
# end). A term already under way (a past effective date, a future expiration)
# is in force and is not refused. Plain words, no em-dash.
TERM_ENDED_REFUSAL = "The proposed policy term has already ended. Enter the upcoming term's dates."

_TERM_DATE_KEYS = ("effective_date", "expiration_date")


def _iso_date(text: str):
    """The calendar date a date string reads as, or None (the one date reader,
    `normalization.normalize_date`)."""
    from services.normalization import normalize_date
    iso = normalize_date(str(text or "").strip()) if str(text or "").strip() else None
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return None


def term_save_refusal(stored_facts: dict, supplied: dict, today=None) -> str:
    """The refusal sentence when a person's save would leave the proposed term
    unusable: running backwards (`TERM_BACKWARDS_REFUSAL`), or already ended -
    its expiration before today (`TERM_ENDED_REFUSAL`); "" otherwise.

    `supplied` is every proposed-term date a PERSON gives in this save (the
    fix window sends its boxes one request at a time, so it names the whole
    save). The term judged is the one the save LEAVES: the supplied dates over
    the ones on file, then the save's own re-derivation (`extraction_service.
    follow_proposed_expiration` - a typed effective date takes a derived or
    blank expiration with it, exactly as `apply_producer_answer_to_session`
    does), so a save the follow corrects is never refused for the stale
    expiration it replaces. Empty when the save supplies neither date, when a
    supplied date is unreadable or the side to compare is missing (the format
    and missing-date rules' job), or when the term runs forwards and has not
    ended. An expiration of today has not ended. `today` is for tests.

    Why it exists: with the hard stops needing a PERSON's dates, a "Confirm
    these values" save of a backwards or an expired pair read off a document -
    the warning's own window - would otherwise make that pair a person's and
    the warning a hard stop."""
    given = {k: str(v).strip() for k, v in (supplied or {}).items()
             if k in _TERM_DATE_KEYS and v is not None and str(v).strip()}
    if not given or any(_iso_date(v) is None for v in given.values()):
        return ""
    left = dict(stored_facts or {})
    for key, text in given.items():
        left[key] = {"value": text, "source": "producer", "confidence": "filled"}
    try:
        from services.extraction_service import follow_proposed_expiration
        follow_proposed_expiration(left)
    except Exception:                                        # noqa: BLE001
        pass                     # judged on the dates as supplied over the stored ones
    eff = str(_fv(left, "effective_date") or "").strip()
    exp = str(_fv(left, "expiration_date") or "").strip()
    if eff and exp:
        ok, _msg = validate_date_range(eff, exp)
        if not ok:
            return TERM_BACKWARDS_REFUSAL
    end = _iso_date(exp) if exp else None
    if end is None:
        return ""
    if today is None:
        today = datetime.now().date()
    return TERM_ENDED_REFUSAL if end < today else ""


def _term_typed_by_a_person(facts: dict) -> bool:
    """Did a person supply BOTH proposed-term dates?

    BOTH, NOT ONE (21 Oct 2026 review, M2). "One typed date is enough" let the
    warning's own instruction make it hard: documents read 07/15/2026 ->
    07/15/2025 (an OCR slip), the producer retyped only the effective date, and
    the stop went hard on the document's unverified expiration. The condition
    is about the PAIR, so a person must have supplied both sides of it.

    The per-date door is `sqs_service._date_is_person_supplied`, which asks
    the one "typed by a person" door, `fact_state.typed_by_person` (21 Oct
    2026, review L1) - the expired-term rule asks it about the expiration date
    it judges, so both date rules read provenance the same way: a date typed
    by a producer or answered by the client is a person's; a date read off a
    document (whatever its confidence), picked between documents or typed into
    Data Consistency, confirmed by the client in confirm-or-correct, or
    calculated by Primble is not. Lazy import: sqs_service imports this
    module. If the door cannot be reached the stop keeps its old severity
    (hard)."""
    try:
        from services.sqs_service import _term_dates_both_person_supplied
    except Exception:                                        # noqa: BLE001
        return True
    return bool(_term_dates_both_person_supplied(facts))


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
        from services.display_canonicalizer import too_many_digits
        if too_many_digits(value):
            # Past 15 significant digits a float is noise (29 Oct 2026).
            return False, f"{label} has more than 15 digits - check the number"
    except ImportError:
        pass
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

def _scalar_text(facts: dict, key: str) -> str:
    """A fact's value as the text the format validators read (strict review, 29
    Oct 2026): a number read off a spreadsheet / an ACORD box / a model reply
    (an Excel serial date, a revenue 1500000) is its digits; a boolean, a list or
    a dict is no scalar answer to check - "". The validators call `.strip()`,
    and one non-string date (`effective_date = 46023`) raised inside the stops,
    so the package had NO score and no plan at all (the review page showed
    nothing to fix, R3)."""
    val = _fv(facts or {}, key)
    if isinstance(val, bool) or val is None:
        return ""
    if isinstance(val, (int, float)):
        return str(int(val)) if isinstance(val, float) and val.is_integer() else str(val)
    return val if isinstance(val, str) else ""


def run_field_validations(facts: dict) -> Tuple[List[str], List[str]]:
    """
    Run all deterministic field-level validations against extracted facts.

    Returns (hard_stops, soft_stops):
      hard_stops — conditions that cap SQS at 60 and block "Submission Ready"
                   (only the invalid policy period here - Brent's short
                   hard-stop list, 19 Oct 2026 - and since 21 Oct only when
                   a person supplied one of its dates)
      soft_stops — conditions that cap SQS at 85

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
        val = _scalar_text(facts, fn)
        ok, msg = validator(val)
        if not ok:
            soft.append(msg)

    # ── FEIN format (soft — advisory, hard stop handled in check_doc_consistency) ──
    # Through the one identifier door (30 Oct 2026): a statement with no digits
    # ("Applied for") is not a malformed FEIN, and a FEIN a person typed or
    # confirmed is theirs - never flagged.
    fein = _scalar_text(facts, "fein")
    if fein:
        from services.identifier_checks import _by_person, fein_is_impossible
        if fein_is_impossible(fein) and not _by_person(facts, "fein"):
            soft.append(validate_fein(fein)[1])

    # ── Date format validation ────────────────────────────────────────────────
    eff = _scalar_text(facts, "effective_date")
    exp = _scalar_text(facts, "expiration_date")

    if eff:
        ok, msg = validate_date_format(eff, "Effective date")
        if not ok:
            soft.append(msg)

    if exp:
        ok, msg = validate_date_format(exp, "Expiration date")
        if not ok:
            soft.append(msg)

    # ── Date range: effective must be before expiration ──────────────────────
    # HARD ONLY WHEN VERIFIED (21 Oct 2026, Brent's 20 Oct reply: "only trigger
    # a hard stop when Primble has enough VERIFIED information to know the
    # condition is true; otherwise flag it for confirmation"). A term a person
    # typed that runs backwards is a verified invalid period - hard, same
    # sentence and issue id as before. The same pair read off a document is an
    # OCR or reading slip until someone looks: a warning to correct the dates.
    # A person must have supplied BOTH dates (review, M2): one retyped date
    # beside a document's slip is still the document's slip.
    if eff and exp:
        ok, msg = validate_date_range(eff, exp)
        if not ok:
            if _term_typed_by_a_person(facts):
                hard.append(msg)
            else:
                soft.append(BACKWARDS_TERM_TO_CONFIRM)

    # ── Percentage validations ────────────────────────────────────────────────
    for field, label in [
        ("percent_subcontracted",  "Subcontracted work percentage"),
        ("coinsurance_percentage", "Coinsurance percentage"),
        ("building_ITV_percentage","Building ITV percentage"),
    ]:
        val = _scalar_text(facts, field)
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
        val = _scalar_text(facts, field)
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