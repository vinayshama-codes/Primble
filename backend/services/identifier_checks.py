"""ONE door for fixed-format identifiers read off the documents (30 Oct 2026).

A live dec printed VINs in a narrow table cell and the last character wrapped
onto the next line: three 16-character VINs were extracted and printed with no
warning. The same class hits every FIXED-FORMAT identifier a document states -
a NAIC code, a ZIP, a phone number, a term's two dates. This module lists, for
the package facts, the document- or AI-read identifiers whose format is
IMPOSSIBLE, and builds one warning per rule naming the items.

Rules of the door:
  * Scope: a value a person typed or confirmed is never flagged
    (`fact_state.confirmed_by_person` for a scalar; a table a person saved -
    `schedule_capture.human_rows` - is the person's as a whole).
  * Reuse: every check reads an existing format reader (`schedule_capture.
    is_valid_vin`, `validators.phone_main_digits` / `validate_fein` /
    `US_STATES`, `pdf_service._is_postal_code`, `normalization.normalize_date`).
  * When unsure, do not flag: a statement with no digits ("Applied for"), an
    international number / postcode, a pre-1981 VIN, a 4-digit NAIC (a dropped
    leading zero), an extension, a 6-month or 3-year term are all left alone.
  * Each rule has a `legacy_*` code; `issue_registry` builds its rows from
    `WARNING_RULES`, so the fix (the table, or the field) is declared once.

Already judged elsewhere, never warned twice: `fein` (FEIN message of
`validators.run_field_validations`, which asks `fein_is_impossible` here),
`contact_phone` length, `mailing_address` ZIP presence and the proposed term
(`effective_date` / `expiration_date`) stay with `run_field_validations`.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple


class Rule(NamedTuple):
    code: str
    phrase: str           # the message opening `issue_registry` matches on
    cluster: str
    home: Tuple[str, ...]  # ("schedule", key) or ("field", fact, ...)
    advice: str


VIN_RULE = Rule("legacy_auto_vin_incomplete", "Vehicle VIN incomplete", "Auto completeness",
                ("schedule", "auto_vin_schedule"), "")
NAIC_RULE = Rule("legacy_carrier_naic_format", "Carrier NAIC code is not 5 digits",
                 "Contact & identity field format",
                 ("field", "carrier_naic"),
                 "check it against the declarations page")
# One box per card (30 Oct 2026, live 50a7d9e6): a card offering the carrier AND
# the prior carrier box invited a value into the box that was not wrong.
PRIOR_NAIC_RULE = Rule("legacy_prior_carrier_naic_format", "Prior-carrier NAIC is not 5 digits",
                       "Contact & identity field format",
                       ("field", "prior_carrier_naic"),
                       "check it against the prior policy")
LOCATION_ZIP_RULE = Rule("legacy_location_zip_format", "Location ZIP code is not 5 or 9 digits",
                         "Contact & identity field format",
                         ("schedule", "property_locations"), "correct it in the location table")
PHYSICAL_ZIP_RULE = Rule("legacy_physical_zip_format", "Physical address ZIP code is not 5 or 9 digits",
                         "Contact & identity field format",
                         ("field", "physical_address"), "correct the address")
BUSINESS_PHONE_RULE = Rule("legacy_us_phone_format", "Business phone number is not a valid US number",
                           "Contact & identity field format",
                           ("field", "applicant_business_phone"),
                           "check the number against the documents")
CONTACT_PHONE_RULE = Rule("legacy_contact_phone_format", "Contact phone is not a valid US number",
                          "Contact & identity field format",
                          ("field", "contact_phone"),
                          "check the number against the documents")
UMBRELLA_TERM_RULE = Rule("legacy_umbrella_term_backwards", "Umbrella term ends on or before it starts",
                          "Date format & range",
                          ("field", "umbrella_effective_date", "umbrella_expiration_date"),
                          "correct the umbrella effective or expiration date")

WARNING_RULES: Tuple[Rule, ...] = (VIN_RULE, NAIC_RULE, PRIOR_NAIC_RULE, LOCATION_ZIP_RULE,
                                   PHYSICAL_ZIP_RULE, BUSINESS_PHONE_RULE, CONTACT_PHONE_RULE,
                                   UMBRELLA_TERM_RULE)


# ── helpers ──────────────────────────────────────────────────────────────────
def _value(facts: dict, key: str) -> Any:
    raw = (facts or {}).get(key)
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _by_person(facts: dict, key: str) -> bool:
    try:
        from services.fact_state import confirmed_by_person
        return confirmed_by_person((facts or {}).get(key))
    except Exception:                                          # noqa: BLE001
        return True                                  # unsure: never flag


def _document_scalar(facts: dict, key: str) -> str:
    """The scalar's text when a document / the AI put it there, else ""."""
    v = _value(facts, key)
    if not isinstance(v, (str, int)) or isinstance(v, bool) or _by_person(facts, key):
        return ""
    return str(v).strip()


def _document_rows(facts: dict, key: str) -> List[Any]:
    """The table's stored rows, or [] when a person saved the table."""
    try:
        from services.schedule_capture import human_rows
        if human_rows(facts, key)[0]:
            return []
    except Exception:                                          # noqa: BLE001
        return []
    rows = _value(facts, key)
    return rows if isinstance(rows, list) else []


def _row_number(row: dict, n: int) -> str:
    return str(row.get("vehicle_number") or row.get("location_number") or row.get("number") or n)


# ── the per-value readers (also used by the plan probe) ──────────────────────
def vin_is_impossible(vin: Any, year: Any = None) -> bool:
    """A VIN present but not 17 characters on a vehicle from model year 1981 on
    (or of unknown year). Earlier vehicles had no standard VIN."""
    from services.schedule_capture import is_valid_vin, normalize_vin
    v = normalize_vin(vin or "")
    if not v or is_valid_vin(v):
        return False
    m = re.search(r"(19|20)\d{2}", str(year or ""))
    return not (m and int(m.group(0)) < 1981)


def fein_is_impossible(value: Any) -> bool:
    """A FEIN that states digits but is not 9 of them (or a placeholder). A
    statement with no digits ("Applied for", "Pending") is not judged."""
    s = str(value or "").strip()
    if not re.search(r"\d", s):
        return False
    from utils.validators import validate_fein
    return not validate_fein(s)[0]


def naic_is_impossible(value: Any) -> bool:
    """A carrier NAIC code is 5 digits; 4 is a dropped leading zero (kept).
    A value with no digits ("Pending") is not judged."""
    digits = re.sub(r"\D", "", str(value or ""))
    return bool(digits) and len(digits) not in (4, 5)


def zip_is_impossible(zip_value: Any, state: Any) -> bool:
    """A US ZIP (the row's state is a US state) that is not 5 or 9 digits.
    No state, a foreign state, a Canadian postcode or no digits: not judged."""
    from utils.validators import US_STATES
    st = str(state or "").strip().upper().strip(".")
    z = str(zip_value or "").strip()
    if st not in US_STATES or not re.search(r"\d", z):
        return False
    from services.pdf_service import _is_postal_code
    return not _is_postal_code(z)


_ADDR_TAIL_RE = re.compile(r"\b([A-Za-z]{2})\.?,?\s+([0-9][0-9\- ]{1,12}[0-9]|[0-9])\s*$")


def address_zip_is_impossible(address: Any) -> bool:
    """A one-line address ending "<US state> <digits>" whose digits are not a ZIP."""
    m = _ADDR_TAIL_RE.search(str(address or "").strip())
    return bool(m) and zip_is_impossible(m.group(2).replace(" ", ""), m.group(1))


def phone_is_impossible(value: Any) -> bool:
    """Not a North American number: not 10 digits (11 with a leading 1), or an
    area / exchange code starting 0 or 1. An extension never counts; an
    international "+" number other than +1 and a value with no digits are not
    judged. 800 numbers are ordinary NANP numbers."""
    s = str(value or "").strip()
    if not re.search(r"\d", s) or (s.startswith("+") and not s.startswith("+1")):
        return False
    from utils.validators import phone_main_digits
    d = phone_main_digits(s)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    if len(d) != 10:
        return True
    return d[0] in "01" or d[3] in "01"


def term_is_backwards(effective: Any, expiration: Any) -> bool:
    """Both dates read and the expiration is on or before the effective date.
    Any length forward (6 months, 3 years) is fine; an unreadable date is not judged."""
    from services.normalization import normalize_date
    e, x = (normalize_date(str(v)) if v not in (None, "") else None for v in (effective, expiration))
    return bool(e and x and x <= e)


# Table cells the door judges, by schedule and column, with their reader - the
# review plan's probe corrects exactly these.
def cell_is_impossible(list_key: str, column: str, row: dict) -> bool:
    try:
        if list_key == "auto_vin_schedule" and column == "vin":
            return vin_is_impossible(row.get("vin") or row.get("VIN"),
                                     row.get("year") or row.get("model_year"))
        if list_key == "property_locations" and column == "address_zip":
            return zip_is_impossible(row.get("address_zip"), row.get("address_state"))
    except Exception:                                          # noqa: BLE001
        return False
    return False


# ── the door ─────────────────────────────────────────────────────────────────
def impossible_identifiers(facts: dict) -> Dict[str, List[str]]:
    """{rule code: [items]} for every rule with a document-read value whose
    format is impossible. Never raises."""
    facts = facts or {}
    out: Dict[str, List[str]] = {}

    def _add(rule: Rule, item: str) -> None:
        out.setdefault(rule.code, []).append(item)

    checks: List[Callable[[], None]] = []

    def vins():
        for n, r in enumerate(_document_rows(facts, "auto_vin_schedule"), start=1):
            if isinstance(r, dict) and cell_is_impossible("auto_vin_schedule", "vin", r):
                _add(VIN_RULE, _row_number(r, n))

    def naics():
        for key, label, rule in (("carrier_naic", "carrier", NAIC_RULE),
                                 ("prior_carrier_naic", "prior carrier", PRIOR_NAIC_RULE)):
            v = _document_scalar(facts, key)
            if v and naic_is_impossible(v):
                _add(rule, f"{label} {v}")

    def zips():
        for n, r in enumerate(_document_rows(facts, "property_locations"), start=1):
            if isinstance(r, dict) and cell_is_impossible("property_locations", "address_zip", r):
                _add(LOCATION_ZIP_RULE, f"location {_row_number(r, n)} ({r.get('address_zip')})")
        v = _document_scalar(facts, "physical_address")
        if v and address_zip_is_impossible(v):
            _add(PHYSICAL_ZIP_RULE, v)

    def phones():
        from utils.validators import validate_phone
        for key, label, rule in (("applicant_business_phone", "business phone", BUSINESS_PHONE_RULE),
                                 ("contact_phone", "contact phone", CONTACT_PHONE_RULE)):
            v = _document_scalar(facts, key)
            # contact_phone's LENGTH is run_field_validations' own warning.
            if not v or (key == "contact_phone" and not validate_phone(v)[0]):
                continue
            if phone_is_impossible(v):
                _add(rule, f"{label} {v}")

    def terms():
        e = _value(facts, "umbrella_effective_date")
        x = _value(facts, "umbrella_expiration_date")
        if (_by_person(facts, "umbrella_effective_date") and _by_person(facts, "umbrella_expiration_date")):
            return
        if term_is_backwards(e, x):
            _add(UMBRELLA_TERM_RULE, f"{e} to {x}")

    for fn in (vins, naics, zips, phones, terms):
        try:
            fn()
        except Exception:                                      # noqa: BLE001
            continue
    return out


def warning_message(rule: Rule, items: List[str]) -> str:
    if rule is VIN_RULE:          # the 30 Oct sentence, kept word for word
        return (f"{rule.phrase} - the VIN of vehicle {', '.join(items)} is not 17 "
                "characters; check it against the registration")
    return f"{rule.phrase} - {'; '.join(items)}; {rule.advice}"


def warning_messages(facts: dict) -> List[str]:
    """One warning per rule that holds an impossible value, in rule order."""
    found = impossible_identifiers(facts)
    return [warning_message(r, found[r.code]) for r in WARNING_RULES if found.get(r.code)]


def resolution_for_rule(rule: Rule) -> dict:
    if rule.home[0] == "schedule":
        return {"mode": "schedule", "schedule_key": rule.home[1]}
    return {"mode": "field", "facts": list(rule.home[1:])}


_SCALAR_CHECKS = {
    "carrier_naic": naic_is_impossible, "prior_carrier_naic": naic_is_impossible,
    "applicant_business_phone": phone_is_impossible, "contact_phone": phone_is_impossible,
    "physical_address": address_zip_is_impossible,
}


def impossible_scalar(key: str, value: Any) -> bool:
    """Does this one fact's value have an impossible format? (Rule 1's door for
    the fix windows: a box holding such a value is one that needs fixing.)"""
    fn = _SCALAR_CHECKS.get(str(key))
    try:
        return bool(fn and value not in (None, "") and fn(value))
    except Exception:                                          # noqa: BLE001
        return False
