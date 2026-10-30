# ---------------------------------------------------------------------------
# Unified fact registry — single source of truth for all fact metadata.
#
# Each entry shape:
#   {
#     "forms":      set of ACORD form IDs that consume this fact,
#     "question":   plain-English ARQ question for the client,
#     "tier":       1 = hard gate (blocks submission if missing),
#                   2 = quality score (SQS narrative component),
#                   None = optional / enrichment only,
#     "required":   True = hard block if missing (Tier 1 only),
#     "validate":   optional callable(value: str) → bool — returns True if valid,
#     "format_hint": human-readable format description for error messages,
#   }
#
# WHY validate lives here:
#   Centralized validation avoids separate validator modules drifting out of
#   sync with the registry. Callers use validate_fact() from this module.
#
# WHY tier + required live here:
#   sqs_service.py derives TIER1_REQUIRED_FIELDS and TIER2_SCORED_FIELDS
#   from this registry instead of maintaining parallel hardcoded lists.
# ---------------------------------------------------------------------------

import re
from typing import Any, Optional, Callable

# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

def _is_date(v: str) -> bool:
    """MM/DD/YYYY or YYYY-MM-DD or M/D/YYYY."""
    return bool(re.match(
        r'^(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})$', v.strip()
    ))


def _beyond_float_digits(v: str) -> bool:
    """More than 15 significant digits in one number - past what a float
    holds exactly, so a 30-digit typing would be stored as noise (strict
    review, 29 Oct 2026). The display rule's own reader, shared."""
    try:
        from services.display_canonicalizer import too_many_digits
        return too_many_digits(v)
    except Exception:                                         # noqa: BLE001
        return False


def _is_currency(v: str) -> bool:
    """$1,000,000 or 1000000 or 1,000,000.00 etc. - at most 15 significant
    digits."""
    return bool(re.match(
        r'^\$?[\d,]+(?:\.\d{1,2})?$', v.strip().replace(" ", "")
    )) and not _beyond_float_digits(v)


def _is_fein(v: str) -> bool:
    """XX-XXXXXXX (9 digits, with or without hyphen)."""
    clean = v.strip().replace("-", "")
    if not (clean.isdigit() and len(clean) == 9):
        return False
    # One digit nine times ("00-0000000") holds a FEIN's place, never is one.
    # The function's IDENTITY is unchanged (the merge, the type sweep and the
    # stamper key on it), only what it accepts.
    from services.normalization import is_placeholder_fein
    return not is_placeholder_fein(clean)


def _is_email(v: str) -> bool:
    """something@something.tld. Named (not an inline lambda) because the
    stamp-time shape check reuses these validators - a lambda cannot be looked
    up by name from pdf_service, and duplicating the pattern there is how two
    copies of one rule drift apart."""
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v.strip()))


def _is_phone(v: str) -> bool:
    """7-20 chars of digits and the usual separators, and at least 7 DIGITS.
    The digit floor is what the old inline pattern lacked: '(   )   -    ' and
    '----------' both satisfied the character-class form."""
    s = v.strip()
    return bool(re.match(r'^[\d\s\-\(\)\+\.xX]{7,20}$', s)) and len(re.sub(r'\D', '', s)) >= 7


# THE BOX REFUSES WHAT A LATER CHECK FLAGS (15 Oct 2026). An answer box applies
# the same rule as the check that would raise a warning on the stored value
# (`utils.validators.run_field_validations`, `sqs_service.validate_naics_code`),
# so a value the box takes can never come back as a warning no correct answer
# clears. BOX-ONLY, as `answer_validate` (read through `answer_check`): the
# fact's own `validate` stays the shared SHAPE that the extraction merge, the
# dec-entry backfill, the stamper's shape guard and the comparison door key on
# by identity - swapping it there moved extraction (contact_phone left the
# merge's phone partition).
VALID_NAICS_SECTORS = frozenset({
    "11", "21", "22", "23", "31", "32", "33", "42", "44", "45",
    "48", "49", "51", "52", "53", "54", "55", "56", "61", "62",
    "71", "72", "81", "92",
})


def _is_naics(v: str) -> bool:
    s = str(v or "").strip()
    return bool(re.match(r'^\d{2,6}$', s)) and s[:2] in VALID_NAICS_SECTORS


def _is_full_phone(v: str) -> bool:
    try:
        from utils.validators import validate_phone
        return _is_phone(v) and validate_phone(v)[0]
    except Exception:                                          # noqa: BLE001
        return _is_phone(v)


def _is_us_mailing_address(v: str) -> bool:
    if len(str(v or "").strip()) < 10:
        return False
    try:
        from utils.validators import validate_address
        return validate_address(v)[0]
    except Exception:                                          # noqa: BLE001
        return True


def _us_states_answer(v: str) -> bool:
    """The state question's box (23 Oct 2026): one US state or a list of them
    ("CO", "Colorado", "CO, CA") - read by the same door the state readers use
    (`form_service.state_codes_of`), so a value the box takes is a state every
    reader sees."""
    s = str(v or "").strip()
    if not s or len(s) > 120:
        return False
    try:
        from services.form_service import state_codes_of, _STATE_LIST_SPLIT_RE, _state_token
    except Exception:                                          # noqa: BLE001
        return True        # a broken reader never refuses a real answer
    parts = [p for p in _STATE_LIST_SPLIT_RE.split(s) if p.strip()]
    return bool(parts) and all(_state_token(p) for p in parts) and bool(state_codes_of(s))


def takes_amount_or_percent(entry_or_key: Any) -> bool:
    """A fact whose own declaration takes a dollar amount OR a percentage: a
    money shape (`validate` is `_is_currency`) whose format hint or question
    also names a percentage - "Dollar amount or percentage", the wind / hail
    and earthquake deductibles (22 Oct 2026, Z33-PERCENT). Derived from the
    declaration, never listed: a fact declared that way later is in the class
    the day it is added. Takes a registry entry or a fact key."""
    e = FACT_REGISTRY.get(entry_or_key) if isinstance(entry_or_key, str) else entry_or_key
    if not isinstance(e, dict) or e.get("validate") is not _is_currency:
        return False
    return "percent" in f"{e.get('format_hint') or ''} {e.get('question') or ''}".lower()


def _amount_or_percent_answer(v: str) -> bool:
    """The person check of an amount-or-percent fact: its own dollar shape, or
    a statement whose first figure is a percentage from 0 to 100 ("2%",
    "1.5 percent", "2% of TIV", "2% / $25,000 minimum" - the reader is
    `normalization.stated_percentage`). "-2%" and "200%" stay refused. Not
    `_is_*` (the dec-entry backfill reason below)."""
    if _is_currency(v):
        return True
    from services.normalization import stated_percentage
    got = stated_percentage(v)
    return got is not None and 0 <= got["number"] <= 100


def answer_check(entry: Optional[dict]):
    """The check a PERSON's typed answer must pass: the box rule
    (`answer_validate`) where it is stricter than the fact's shape, else the
    shape (`validate`). Every door that judges a typed answer reads this. An
    amount-or-percent fact (`takes_amount_or_percent`) takes a percentage too:
    its `validate` stays the dollar shape the merge, the type sweep and the
    stamper key on by identity."""
    e = entry if isinstance(entry, dict) else {}
    if not e.get("answer_validate") and takes_amount_or_percent(e):
        return _amount_or_percent_answer
    return e.get("answer_validate") or e.get("validate")


# ── Facts every operating business HAS (strict review, 29 Oct 2026) ──────────
# "N/A" / "None" typed for one of these is never an answer: every business has
# a tax ID, an annual revenue, an industry classification and a start date. C3
# 3.6 (Not Applicable leaves the Tier 2 denominator) is for facts that can
# genuinely not apply; on these it let one word score HIGHER than the real
# value (a smaller denominator, and an "N/A" NAICS escaped the class-code
# mismatch check). The answer door refuses the absence (`answer_semantics.
# interpret_answer`) and the scorer never credits a stored one
# (`answer_semantics.answered_for`). The value is the label the refusal names.
# Employee counts are NOT here: a business can have no employees ("0" / "None").
ALWAYS_EXISTS: dict[str, str] = {
    "fein": "a federal tax ID (FEIN)",
    "total_revenue": "an annual revenue",
    "naics_code": "a NAICS industry code",
    "sic_code": "a SIC industry code",
    "years_in_business": "a number of years in business",
    "business_start_date": "a business start date",
}


def fein_may_be_absent(facts: Any) -> bool:
    """True when the applicant is an individual / sole proprietorship
    (`normalization.entity_family` of `entity_type`): such an applicant may
    file under the owner's SSN and have no EIN at all - an SSN is never stored
    here - so "None" / "N/A" is its honest FEIN answer, scored Not Applicable
    (29 Oct 2026). Any other entity, or no entity type on file: False."""
    if not isinstance(facts, dict):
        return False
    try:
        from services.normalization import ENTITY_FAMILY_INDIVIDUAL, entity_family
        raw = facts.get("entity_type")
        val = raw.get("value") if isinstance(raw, dict) else raw
        return entity_family(val) == ENTITY_FAMILY_INDIVIDUAL
    except Exception:                                         # noqa: BLE001
        return False


def always_exists(fact_key: Any, facts: Any = None) -> str:
    """The label of a fact every operating business has (`ALWAYS_EXISTS`),
    else "". With ``facts``: an individual / sole proprietor's FEIN is not one
    (`fein_may_be_absent`)."""
    key = str(fact_key or "").strip()
    if key == "fein" and fein_may_be_absent(facts):
        return ""
    return ALWAYS_EXISTS.get(key, "")


def _descriptive_amount(text: str, format_hint: str) -> bool:
    """True when a non-numeric answer is a legitimate convention, not garbage.

    Real ACORD money boxes print words: "Statutory" on an Employers Liability
    limit, "Waived" on a deductible, "Not covered" on an excluded peril. The
    fact's own `format_hint` says which boxes those are - "Dollar amount (e.g.
    $1,000,000)" is a money box, "Whole number of years (e.g. 5)" is not, and a
    count box has no descriptive convention (so "no losses" is never accepted
    into `loss_history_years`). Only an answer with NO digits at all: one that
    has digits and still fails is a botched number, not a convention."""
    if any(ch.isdigit() for ch in text):
        return False
    h = (format_hint or "").lower()
    return "dollar" in h or "amount" in h or "percent" in h


def answer_refusal(entry: Optional[dict], text) -> str:
    """The words a person's typed answer is refused with when it fails its
    fact's own check (`answer_check`), else "". ONE rule for the producer's
    card (`audit_routes._validate_producer_answer`) and the client's
    questionnaire (`arq_service`, where such an answer is HELD for the
    producer, never written - 22 Oct 2026). A broken validator never refuses a
    real answer; an amount box's descriptive convention is kept."""
    checker = answer_check(entry)
    if not callable(checker):
        return ""
    s = str(text if text is not None else "")
    try:
        ok = bool(checker(s))
    except Exception:                                          # noqa: BLE001
        ok = True          # a broken validator must never block a real answer
    hint = str((entry or {}).get("format_hint") or "").strip()
    if ok or _descriptive_amount(s, hint):
        return ""          # "Statutory" / "Waived" / "Not covered"
    return (f"That does not look right for this field. Expected: {hint}"
            if hint else "That value is not valid for this field.")


def _is_url(v: str) -> bool:
    """A web address. Accepts bare domains ('acme.com', 'www.acme.com') as well
    as full URLs, because that is how they are printed on ACORD forms."""
    s = v.strip().lower()
    if " " in s or "@" in s:
        return False
    s = re.sub(r'^https?://', '', s)
    return bool(re.match(r'^[a-z0-9][a-z0-9\-\.]*\.[a-z]{2,}(/.*)?$', s))


def _is_percent(v: str) -> bool:
    """0–100 with optional % sign."""
    clean = v.strip().rstrip("%").strip()
    try:
        f = float(clean)
        return 0.0 <= f <= 100.0
    except ValueError:
        return False


def _is_positive_int(v: str) -> bool:
    clean = v.strip().replace(",", "")
    return clean.isdigit() and int(clean) >= 0 and not _beyond_float_digits(clean)


def _is_valuation(v: str) -> bool:
    return v.strip().upper() in {"RCV", "ACV"}


def _is_covered_auto_symbols(v: str) -> bool:
    """At least one parseable covered-auto symbol number.

    Deliberately permissive about SHAPE (a producer may type "Liability 1,
    Comp 7", "1/7/7", or just "1") and strict about SUBSTANCE - the answer must
    contain a symbol number that ACORD actually defines, so a free-text
    non-answer like "see policy" is rejected rather than stored as a coverage
    designation. Parsing is owned by services.auto_symbols, which is also what
    every reader of this fact uses.
    """
    from services.auto_symbols import ALL_NUMBERS, parse_symbols
    nums = {n for group in parse_symbols(v).values() for n in group}
    return bool(nums) and bool(nums & ALL_NUMBERS)


def _premises_interest_answer(v: str) -> bool:
    """An answer naming ONE interest in the premises - Tenant, Owner, or an
    Other description - read by `premises_interest.kind_of_answer`, the same
    rule the location consolidation reads a document's wording with.

    Deliberately NOT named `_is_*`: the dec-entry backfill fills only `_is_*`
    typed facts from printed labels, and an interest is never read off a label
    (owner, 29 Sep 2026: tenant is never silently inferred)."""
    from services.premises_interest import kind_of_answer
    return kind_of_answer(v) is not None


def _is_payroll_period(v: str) -> bool:
    """A payroll period stated by MEANING - annual in any spelling, or another
    recognised period. Owned by `coverage_evidence.payroll_period_meaning`, the
    same reader the H1 6.4 scorer uses, so a value this accepts is one the
    scorer can interpret."""
    from services.coverage_evidence import payroll_period_meaning
    return payroll_period_meaning(v) is not None


def _entity_type_is_recognized(v: str) -> bool:
    """A legal entity type we can place on ACORD's own nine-box list.

    Owned by `normalization.entity_family`, the SAME reader the ACORD 125
    stamper uses, so a value this accepts is one the form can actually express -
    which the literal 16-item uppercase set it replaces could not promise.

    Measured 2026-08-27, V1 H4: that set REFUSED 8 of the 13 options
    `answer_options.ENTITY_TYPE_OPTIONS` offers, so a producer picking
    "Limited Liability Company", "S Corporation", "Joint Venture", "Association"
    or "Municipality or Government Entity" from OUR OWN dropdown was told
    *"That does not look right for this field"* by `_validate_producer_answer`.
    The replacement is a strict SUPERSET: every value the old set accepted still
    maps to a family, and all 13 options now validate.

    DO NOT RENAME THIS TO `_is_entity_type`. `extraction_service`'s dec-page
    backfill selects its candidate validators with
    `v_name.startswith("_is_")` (see `_backfill_empty_facts_from_entries`), so
    an `_is_` prefix would silently enrol `entity_type` in a backfill it has
    never taken part in - a behaviour change nobody asked for, arriving through
    a rename. The name is load-bearing.
    """
    from services.normalization import entity_family
    return entity_family(v) is not None


def _coverage_part_lines_answer(v: str) -> bool:
    """The coverage-part card's answer: every "<part key>=<line>" pair names a
    line the canon knows (`lob_canon.is_valid_part_lines`, the reader of the
    same text). Not `_is_*`, for the dec-entry backfill reason above: this is
    a person's choice, never read off a printed label."""
    from services.lob_canon import is_valid_part_lines
    return is_valid_part_lines(v)


# ── A PERSON's real answers the facts' shapes refused (22 Oct 2026) ─────────
# Box rules (`answer_validate`, read through `answer_check`): each fact's
# `validate` stays the shape extraction keys on - `fire_protection_class`'s is
# what reduces an extracted "8B" to a whole number. Not `_is_*` (the dec-entry
# backfill reason above). Only these real printings are added.
_XMOD_ANSWER_RE = re.compile(r'^(?:\d+(?:\.\d{1,3})?|\.\d{1,3})$')     # also ".87"
# Four decimals ("1.0800", ".8765" on an NCCI worksheet) only as the number the
# scorer's own reader reads (`coverage_evidence.parse_xmod`, same shape).
_XMOD_FOUR_DP_RE = re.compile(r'^(?:\d{1,3}\.\d{4}|\.\d{4})$')
_VALUATION_ANSWERS = frozenset({
    "RCV", "ACV", "REPLACEMENT COST", "REPLACEMENT COST VALUE", "ACTUAL CASH VALUE",
    "AGREED VALUE", "FUNCTIONAL REPLACEMENT COST",
    "AGREED AMOUNT", "MARKET VALUE",          # ACORD's own words (the 140's ValuationCode)
})
# ISO public protection classes 1-10 plus 8B and 10W, alone or split ("4/9"),
# each with the leading zeros a dec page prints ("03", "010") - the shape's own
# check took those, and the person check must not refuse what it took.
_PPC_CLASS = r"(?:10W|10|8B|[1-9])"
_PPC_ANSWER_RE = re.compile(rf"^0*({_PPC_CLASS})(?:\s*/\s*0*({_PPC_CLASS}))?$", re.I)


def _xmod_answer(v: str) -> bool:
    s = str(v or "").strip()
    if _XMOD_ANSWER_RE.match(s):
        return True
    if not _XMOD_FOUR_DP_RE.match(s):
        return False
    try:
        from services.coverage_evidence import parse_xmod
        return parse_xmod(s) is not None
    except Exception:                                          # noqa: BLE001
        return False


def _valuation_answer(v: str) -> bool:
    return str(v or "").strip().upper() in _VALUATION_ANSWERS


def _protection_class_answer(v: str) -> bool:
    """1-10, 8B, 10W, or a split class whose second class is the higher ("4/9")."""
    m = _PPC_ANSWER_RE.match(str(v or "").strip())
    if not m:
        return False
    if not m.group(2):
        return True
    first, second = (int(re.match(r"\d+", g).group(0)) for g in (m.group(1), m.group(2)))
    return first < second


_PERCENT_SHARE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.I)


def _revenue_shares_answer(v: str) -> bool:
    """Brent's B.3 (23 Oct 2026): operations by percentage of revenue "must
    total 100%". Two or more stated shares must add up to 100 (half a point of
    rounding either way); a description with fewer than two shares is free text
    and passes."""
    shares = [float(m.group(1)) for m in _PERCENT_SHARE_RE.finditer(str(v or ""))]
    if len(shares) < 2:
        return True
    return abs(sum(shares) - 100.0) <= 0.5


def _questionnaire_fact(question: str, hint: Optional[str] = None,
                        answer_validate: Optional[Callable[[str], bool]] = None) -> dict:
    """A fact only the narrative questionnaire asks (Brent's attachment A,
    `services/questionnaire.py`, 23 Oct 2026): printed on no form (`forms` is
    empty, so no ARQ form scan asks it), unscored (no tier), and with NO
    `validate` - the extraction merge, the dec-entry backfill and the type sweep
    key on that callable, and nothing extracts these. A person's typed answer
    is judged by `answer_validate` (`answer_check`) alone."""
    entry = {"forms": set(), "question": question, "tier": None, "required": False,
             "validate": None, "format_hint": hint}
    if answer_validate is not None:
        entry["answer_validate"] = answer_validate
    return entry


_QN_DATE_HINT = "Date (MM/DD/YYYY)"
_QN_COUNT_HINT = "Whole number (e.g. 4)"
_QN_MONEY_HINT = "Dollar amount (e.g. $1,500,000)"


# ---------------------------------------------------------------------------
# FACT_REGISTRY
# ---------------------------------------------------------------------------

FACT_REGISTRY: dict[str, dict] = {

    # ── Business basics — ACORD 125 ─────────────────────────────────────────
    "applicant_name": {
        "forms":       {"ACORD_125"},
        "question":    "What is the full legal name of your business?",
        "tier": 1, "required": True,
        "validate":    lambda v: len(v.strip()) >= 2,
        "format_hint": "Business legal name (at least 2 characters)",
    },
    "dba_name": {
        "forms":       {"ACORD_125", "ACORD_186"},
        "question":    "Does your business go by a different name than its legal name? If yes, what is it?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "mailing_address": {
        "forms":       {"ACORD_125"},
        "question":    "What is your business mailing address? (Street, City, State, ZIP)",
        "tier": 1, "required": True,
        "validate":    lambda v: len(v.strip()) >= 10,
        "answer_validate": _is_us_mailing_address,
        "format_hint": "Full address including street, city, state, ZIP",
    },
    "physical_address": {
        "forms":       {"ACORD_125"},
        "question":    "Where is your business physically located? (Leave blank if same as mailing address)",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    # THE STATE QUESTION (Brent, 23 Oct 2026 - Z34-1 #6). Asked only when no
    # insured document places the risk (`cross_form_validator`'s
    # `auto_state_unverified` card); a person's answer is the one value of this
    # fact any state reader counts (`form_service.coverage_states`) - the
    # model's own reading of it never is. Unscored (no tier). `validate` stays
    # None so the extraction merge, the type sweep and the dec-entry backfill
    # never key on it; the box rule is `answer_validate`.
    "state_of_operations": {
        "forms":       {"ACORD_125"},
        "question":    "Which state does your business operate in? If your vehicles are "
                       "kept in another state, list that state too.",
        "tier": None, "required": False,
        "validate":    None,
        "answer_validate": _us_states_answer,
        "format_hint": "US state code (e.g. CO or CO, CA)",
    },
    "contact_name": {
        "forms":       {"ACORD_125"},
        "question":    "Who is the main person we should contact about this insurance application?",
        "tier": 1, "required": False,
        "validate":    lambda v: len(v.strip()) >= 2,
        "format_hint": "Full name",
    },
    "contact_phone": {
        "forms":       {"ACORD_125"},
        "question":    "What is the best phone number to reach you?",
        "tier": 1, "required": False,
        "validate":    _is_phone,
        "answer_validate": _is_full_phone,
        "format_hint": "Phone number with area code (10 digits); an extension is fine",
    },
    "contact_email": {
        "forms":       {"ACORD_125"},
        "question":    "What email address should we use to contact you?",
        "tier": 1, "required": False,
        "validate":    _is_email,
        "format_hint": "Valid email address (name@domain.com)",
    },
    # The applicant ORGANISATION's main phone - ACORD 125 "BUSINESS PHONE #"
    # (`pdf_service._APPLICANT_ROW_A_FACTS`), never a contact person's line
    # (`contact_phone`). Extracted since the H-series; registered 29 Oct 2026
    # (item 8) so an outside ACORD's reading is judged as a phone and compared
    # with the declarations'. Not asked (tier None): the documents state it.
    "applicant_business_phone": {
        "forms":       {"ACORD_125"},
        "question":    "What is the business's main phone number?",
        "tier": None, "required": False,
        "validate":    _is_phone,
        "answer_validate": _is_full_phone,
        "format_hint": "Phone number with area code (10 digits); an extension is fine",
    },
    "applicant_website": {
        "forms":       {"ACORD_125"},
        "question":    "What is your business's website address?",
        "tier": 2, "required": False,
        "validate":    _is_url,
        "format_hint": "Website (e.g. www.yourcompany.com)",
    },

    # ── Producer-scoped identity ────────────────────────────────────────────
    # These are the AGENCY's own details. `tier: None` deliberately: they must
    # never be asked of the insured in the client questionnaire - the agency
    # already knows its own fax number. They exist so producer form fields stop
    # being filled from the applicant's `contact_*` facts and vice versa.
    "producer_contact_name": {
        "forms":       {"ACORD_125"},
        "question":    "Which person at the agency is handling this submission?",
        "tier": None, "required": False,
        "validate":    lambda v: len(v.strip()) >= 2,
        "format_hint": "Full name",
    },
    "producer_contact_phone": {
        "forms":       {"ACORD_125"},
        "question":    "What is the agency contact's phone number?",
        "tier": None, "required": False,
        "validate":    _is_phone,
        "format_hint": "Phone number",
    },
    "producer_contact_email": {
        "forms":       {"ACORD_125"},
        "question":    "What is the agency contact's email address?",
        "tier": None, "required": False,
        "validate":    _is_email,
        "format_hint": "Valid email address (name@domain.com)",
    },
    "producer_fax": {
        "forms":       {"ACORD_125"},
        "question":    "What is the agency's fax number?",
        "tier": None, "required": False,
        "validate":    _is_phone,
        "format_hint": "Fax number",
    },
    "producer_address": {
        "forms":       {"ACORD_125"},
        "question":    "What is the agency's street address?",
        "tier": None, "required": False,
        "validate":    lambda v: len(v.strip()) >= 5,
        "format_hint": "Street, city, state, ZIP",
    },
    "carrier_website": {
        "forms":       {"ACORD_125"},
        "question":    "What is the carrier's website address?",
        "tier": None, "required": False,
        "validate":    _is_url,
        "format_hint": "Website (e.g. www.carrier.com)",
    },
    "fein": {
        "forms":       {"ACORD_125"},
        "question":    "What is your business's federal tax ID number? (9-digit EIN assigned by the IRS)",
        "tier": 2, "required": False,
        "validate":    _is_fein,
        "format_hint": "9-digit EIN (XX-XXXXXXX)",
    },
    "entity_type": {
        "forms":       {"ACORD_125"},
        "question":    "How is your business legally set up? (LLC, Corporation, Sole Proprietor, Partnership, etc.)",
        "tier": 2, "required": False,
        "validate":    _entity_type_is_recognized,
        "format_hint": "LLC, Corporation, Sole Proprietor, Partnership, LLP, etc.",
    },
    "effective_date": {
        "forms":       {"ACORD_125"},
        "question":    "What date would you like your insurance coverage to start? (MM/DD/YYYY)",
        "tier": 1, "required": True,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },
    "expiration_date": {
        "forms":       {"ACORD_125"},
        "question":    "What date would you like your insurance coverage to end? (MM/DD/YYYY)",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },
    "policy_number": {
        "forms":       {"ACORD_125"},
        "question":    "Do you have a current or previous insurance policy number? If yes, please share it.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "lines_of_business": {
        "forms":       {"ACORD_125"},
        "question":    "What types of insurance coverage are you looking for? (GL, Property, Auto, WC, etc.)",
        "tier": 1, "required": True,
        "validate":    None,   # list field — validated structurally elsewhere
        "format_hint": "List of coverage types",
    },
    "total_revenue": {
        "forms":       {"ACORD_125"},
        "question":    "What is your business's total annual income or sales?",
        "tier": 2, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "total_payroll": {
        "forms":       {"ACORD_125"},
        "question":    "What is the total amount you pay your employees each year (gross payroll)?",
        "tier": 2, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $500,000)",
    },
    "num_employees": {
        "forms":       {"ACORD_125"},
        "question":    "How many people does your business employ?",
        "tier": 2, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number (e.g. 25)",
    },
    # tier 2 = asked in the client questionnaire. Deliberate: these boxes used
    # to be filled (wrongly) from the overall headcount, so blanking them without
    # asking would be a pure fill loss. The client asked for exactly this -
    # "Send these questions to the client" (report #14).
    "num_employees_full_time": {
        "forms":       {"ACORD_125"},
        "question":    "How many of your employees are full time?",
        "tier": 2, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number (e.g. 18)",
    },
    "num_employees_part_time": {
        "forms":       {"ACORD_125"},
        "question":    "How many of your employees are part time?",
        "tier": 2, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number (e.g. 7)",
    },
    # ACORD 125's NO. OF MEMBERS AND MANAGERS (row A, the applicant). No
    # document states it, so before 13 Oct 2026 the box could only be typed on
    # the generated form - listed as Missing after generation and nowhere
    # before. Registered so it is answerable before forms (the dry run's fix
    # window, the questionnaire's box -> fact door); the stamper already prints
    # it from this fact (`pdf_service._APPLICANT_ROW_A_FACTS`).
    "applicant_member_manager_count": {
        "forms":       {"ACORD_125"},
        "question":    "How many members and managers does the LLC have?",
        "tier": None, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number (e.g. 2)",
    },
    # Client report #15: "Obtain the actual business inception date. Do not
    # treat the policy inception date as the business inception date." The box no
    # longer takes `years_in_business`, so the questionnaire is how it gets filled.
    "business_start_date": {
        "forms":       {"ACORD_125"},
        "question":    "On what date did your business start operating?",
        "tier": 2, "required": False,
        "validate":    _is_date,
        "format_hint": "Date (MM/DD/YYYY)",
    },
    "operations_description": {
        "forms":       {"ACORD_125"},
        "question":    "In a few sentences, what does your business do?",
        "tier": 2, "required": False,
        "validate":    lambda v: len(v.strip()) >= 10,
        "format_hint": "Text description (at least 10 characters)",
    },
    "account_description": {
        "forms":       set(),   # narrative-only; not stamped onto any ACORD form field
        "question":    None,    # not surfaced as a client question
        "tier": None, "required": False,
        "validate":    lambda v: len(v.strip()) >= 10,
        "format_hint": "High-level account/executive summary text (at least 10 characters)",
    },
    "prior_carrier": {
        "forms":       {"ACORD_125"},
        "question":    "Who provided your business insurance most recently? (If none, write 'None')",
        "tier": 2, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "carrier_name": {
        "forms":       {"ACORD_125", "ACORD_126"},
        "question":    "What is the name of the insurance carrier?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    # The carrier RECEIVING this submission (v23 addressee fact). Written by a
    # document's "TO:" line or, since 29 Sep 2026, by the producer's page-one
    # card. Kept apart from `carrier_name` (the CURRENT policies' carrier the
    # documents print) so a typed market is never overwritten or held as a
    # conflict by the next re-merge (Orbin item 8).
    "submission_carrier_name": {
        "forms":       {"ACORD_125"},
        "question":    "Which insurance company is this submission going to?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "carrier_naic": {
        "forms":       {"ACORD_125", "ACORD_126"},
        "question":    "What is the carrier's NAIC code?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^\d{4,6}$', v.strip())),
        "format_hint": "4-6 digit NAIC code",
    },
    "prior_carrier_naic": {
        "forms":       {"ACORD_125"},
        "question":    "What is the prior carrier's NAIC code?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^\d{4,6}$', v.strip())),
        "format_hint": "4-6 digit NAIC code",
    },
    "audit_period": {
        "forms":       {"ACORD_125"},
        "question":    "What is the audit period for this policy?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "billing_plan": {
        "forms":       {"ACORD_125"},
        "question":    "What is the billing plan for this policy?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    # Prior/previous policy — distinct namespace from current policy keys
    # (policy_number / effective_date / expiration_date are for the CURRENT policy)
    "prior_policy_number": {
        "forms":       {"ACORD_125"},
        "question":    "What was the policy number on your most recent prior policy?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "prior_effective_date": {
        "forms":       {"ACORD_125"},
        "question":    "When did your prior policy become effective? (MM/DD/YYYY)",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },
    "prior_expiration_date": {
        "forms":       {"ACORD_125"},
        "question":    "When did your prior policy expire? (MM/DD/YYYY)",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },
    "naics_code": {
        "forms":       {"ACORD_125"},
        "question":    "Do you know your business's NAICS code?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^\d{2,6}$', v.strip())),
        "answer_validate": _is_naics,
        "format_hint": "2–6 digit NAICS code",
    },
    "sic_code": {
        "forms":       {"ACORD_125"},
        "question":    "Do you know your business's SIC code?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^\d{4}$', v.strip())),
        "format_hint": "4-digit SIC code",
    },
    "years_in_business": {
        "forms":       {"ACORD_125"},
        "question":    "How many years has your business been open?",
        "tier": 2, "required": False,
        "validate":    lambda v: _is_positive_int(v) and int(v.strip().replace(",", "")) <= 500,
        "format_hint": "Whole number of years (e.g. 12)",
    },
    "is_renewal": {
        "forms":       {"ACORD_125"},
        "question":    "Is this a renewal of an existing policy or a new submission?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"yes", "no", "true", "false", "renewal", "new"},
        "format_hint": "Yes or No",
    },
    "percent_subcontracted": {
        "forms":       {"ACORD_125", "ACORD_186"},
        "question":    "What percentage of your total work is done by outside contractors?",
        "tier": None, "required": False,
        "validate":    _is_percent,
        "format_hint": "Percentage 0–100 (e.g. 25 or 25%)",
    },
    "num_claims": {
        "forms":       {"ACORD_125"},
        "question":    "How many insurance claims has your business filed in the last 3 to 5 years?",
        "tier": 2, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number (e.g. 3)",
    },
    "loss_history_years": {
        "forms":       {"ACORD_125"},
        "question":    "How many years of past insurance claims history are you able to provide?",
        "tier": None, "required": False,
        "validate":    lambda v: _is_positive_int(v) and int(v.strip()) <= 20,
        "format_hint": "Whole number of years (e.g. 5)",
    },
    "total_incurred": {
        "forms":       {"ACORD_125"},
        "question":    "What is the total incurred amount (paid + reserves) across all claims in your loss history?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $50,000)",
    },
    "total_paid": {
        "forms":       {"ACORD_125"},
        "question":    "What is the total amount already paid out across all claims in your loss history?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $30,000)",
    },
    "open_claims_count": {
        "forms":       {"ACORD_125"},
        "question":    "How many insurance claims are currently open or still pending resolution?",
        "tier": None, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number (e.g. 1)",
    },
    # ── Loss-history workflow states (client C2 2.9/2.10, 2026-08-24) ───────
    "new_venture_indicator": {
        # Producer confirmation (client 2.2: "if the producer confirms") - it
        # is answered from the Loss History card, never asked to the client,
        # and is not stamped onto any ACORD box. Parsed by
        # services.loss_history_state.new_venture_answer.
        "forms":       set(),
        "question":    None,
        "tier": None, "required": False,
        "validate":    lambda v: (v.strip().lower().startswith(("yes", "no"))
                                  or "new venture" in v.lower()
                                  or "prior operations" in v.lower()),
        "format_hint": "Yes or No (is this a new venture with no prior operations?)",
    },
    "loss_run_ownership_confirmed": {
        # 23 Oct 2026 (package fc04c74f): the producer's "these loss runs belong
        # to this insured". Read by the one match door
        # (`loss_run_identity.match_loss_run_identity`): Yes lifts a name-matched
        # run to a person-confirmed strong match. Answered from the Loss History
        # row, never asked to the client, never stamped on a form.
        "forms":       set(),
        "question":    None,
        "tier": None, "required": False,
        "validate":    lambda v: str(v or "").strip().lower().startswith(("yes", "no")),
        "format_hint": "Yes or No (do these loss runs belong to this insured?)",
    },
    "loss_run_status": {
        # Client 2.10 (Prior Claims Exist): whether loss runs have been
        # requested / are available. Extraction also writes "pending" /
        # "requested" here (RULE 12); the questionnaire select stores its
        # option text and services.loss_history_state.parse_loss_run_status
        # reads both shapes with one rule.
        "forms":       set(),
        "question":    "Have loss runs been requested, or are any available to upload?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(v.strip()),
        "format_hint": "e.g. 'Requested - pending' or 'No loss runs are available'",
    },
    "producer_name": {
        "forms":       {"ACORD_125"},
        "question":    "What is the name of your insurance producer or agency?",
        "tier": 1, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "additional_named_insureds": {
        "forms":       {"ACORD_125", "ACORD_126"},
        "question":    "Are there any additional named insureds who need to be listed on the policy?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── General Liability — ACORD 126 ───────────────────────────────────────
    "gl_limits": {
        "forms":       {"ACORD_126"},
        "question":    "How much liability coverage are you looking for? (e.g. $1,000,000 per incident / $2,000,000 total)",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "gl_products_aggregate": {
        "forms":       {"ACORD_126"},
        "question":    "What is the Products & Completed Operations aggregate limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $2,000,000)",
    },
    "gl_personal_advertising_injury": {
        "forms":       {"ACORD_126"},
        "question":    "What is the Personal & Advertising Injury limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "gl_fire_damage_limit": {
        "forms":       {"ACORD_126"},
        "question":    "What is the Damage to Rented Premises (Fire Damage) limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $100,000)",
        # The key is ISO's pre-2001 name ("fire damage legal liability"); every
        # current CGL declarations page prints the coverage under this one.
        # Read by extraction_service._backfill_empty_facts_from_entries.
        "dec_labels":  ("Damage to Premises Rented to You",),
    },
    "gl_medical_expense": {
        "forms":       {"ACORD_126"},
        "question":    "What is the Medical Expense limit (per person)?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $5,000)",
    },
    "hired_auto_indicator": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "Do employees drive hired or rented vehicles for business purposes?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"yes", "no", "true", "false"},
        "format_hint": "Yes or No",
    },
    "non_owned_auto_indicator": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "Do employees drive their own personal vehicles for business purposes?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"yes", "no", "true", "false"},
        "format_hint": "Yes or No",
    },
    "gl_each_occurrence": {
        "forms":       {"ACORD_126"},
        "question":    "What is the maximum amount covered for a single incident?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "gl_aggregate": {
        "forms":       {"ACORD_126"},
        "question":    "What is the total maximum covered across all claims in a year?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $2,000,000)",
    },
    "gl_deductible": {
        "forms":       {"ACORD_126"},
        "question":    "How much would you pay out of pocket before GL insurance kicks in?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $500)",
    },
    "gl_form_type": {
        "forms":       {"ACORD_126"},
        "question":    "Is your GL policy written on an 'occurrence' or 'claims-made' basis?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"occurrence", "claims-made", "claims made"},
        "format_hint": "Occurrence or Claims-Made",
    },
    "gl_class_codes_by_location": {
        "forms":       {"ACORD_126"},
        "question":    "What type of work does your business perform at each location?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "gl_class_code_schedule": {
        "forms":       {"ACORD_126"},
        "question":    "Provide the GL rating schedule per class code (class code, "
                       "premium/exposure basis, exposure amount i.e. payroll or gross "
                       "sales, territory, and subcontracted %).",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": "List of class-code rows with rating basis and exposure",
    },
    # 15 Oct 2026: the facts two warnings wait for - neither could be typed, so
    # the warning held the score at 85 whatever the producer answered.
    "prior_acts_confirmation": {
        "forms":       {"ACORD_126", "ACORD_131"},
        "question":    "Does the claims-made general liability policy cover prior acts back to the retroactive date?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(str(v or "").strip()),
        "format_hint": "Yes / No (first claims-made policy) / nose or tail coverage",
    },
    "crime_coverage_decision": {
        "forms":       set(),
        "question":    "The business description suggests cash handling. Is Crime coverage requested, declined, already carried or not applicable?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(str(v or "").strip()),
        "format_hint": "Requested / Declined / Already carried / Not applicable",
    },
    "cyber_coverage_decision": {
        "forms":       set(),
        "question":    "The business description suggests customer data or digital exposure. Is Cyber coverage requested, declined, already carried or not applicable?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(str(v or "").strip()),
        "format_hint": "Requested / Declined / Already carried / Not applicable",
    },
    "workers_comp_arrangement": {
        "forms":       set(),
        "question":    "The documents list employees but no workers compensation policy. How are the employees covered?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(str(v or "").strip()),
        "format_hint": "Carried (policy not uploaded) / PEO or leasing company / Not required / Not carried",
    },
    "auto_coverage_arrangement": {
        "forms":       set(),
        "question":    "The documents list vehicles but no auto policy. How are the vehicles covered?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(str(v or "").strip()),
        "format_hint": "Carried (policy not uploaded) / Personal vehicles / Hired and non-owned only / Not carried",
    },
    "wc_state_fund_acknowledged": {
        "forms":       {"ACORD_130"},
        "question":    "Is the workers compensation payroll in ND, OH, WA or WY placed with the state fund?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(str(v or "").strip()),
        "format_hint": "Yes (state fund) or No (private carrier requested)",
    },
    "retro_date": {
        "forms":       {"ACORD_126"},
        "question":    "What was the original continuous coverage start date? (Required for claims-made policies)",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },

    # ── Commercial Auto — ACORD 127 ─────────────────────────────────────────
    "auto_liability_limit": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "How much liability coverage are you looking for on your business vehicles?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    # A split-limit auto policy states three separate figures (100/300/50).
    # Without these there was nothing to fill the split boxes with, so the
    # combined single limit was stamped into all of them.
    "auto_bi_per_person": {
        "forms":       {"ACORD_127"},
        "question":    "What is the auto bodily injury limit per person?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $100,000)",
    },
    "auto_bi_per_accident": {
        "forms":       {"ACORD_127"},
        "question":    "What is the auto bodily injury limit per accident?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $300,000)",
    },
    "auto_pd_per_accident": {
        "forms":       {"ACORD_127"},
        "question":    "What is the auto property damage limit per accident?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $50,000)",
    },
    "auto_liability_structure": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "Is your auto liability CSL or split limits?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().upper() in {"CSL", "SPLIT", "SPLIT LIMITS", "COMBINED SINGLE LIMIT"},
        "format_hint": "CSL or Split Limits",
    },
    "auto_deductible_comp": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "How much would you pay out of pocket for non-collision vehicle damage?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "auto_deductible_collision": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "How much would you pay out of pocket if a business vehicle is in a collision?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "auto_vin_schedule": {
        "forms":       {"ACORD_127"},
        "question":    "Please list your business vehicles: year, make, model, and VIN for each.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "auto_drivers": {
        "forms":       {"ACORD_127"},
        "question":    "Who are the primary drivers of your business vehicles?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "auto_garaging_addresses": {
        "forms":       {"ACORD_127"},
        "question":    "Where are your business vehicles primarily kept overnight?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "auto_radius_of_operation": {
        "forms":       {"ACORD_127"},
        "question":    "What is the typical radius of operation for your business vehicles?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    # ADDED 2026-08-26 (V1 H1, client 6.3 "No vehicle-use information = -5").
    # There was no fact for how the vehicles are used - the ACORD 127 USE
    # boxes (Vehicle_Use_Service/Retail/Commercial/ForHire/...Indicator) were
    # ticked only by gap fill guessing from the raw text, so the client's
    # deduction had nothing to read. Policy-level on purpose: a declarations
    # page states one use class for the fleet, and pdf_service inherits it
    # into every REAL vehicle row (never a phantom one). Factual, not
    # classification - the insured knows what their trucks do - so it stays
    # client-eligible (master plan 4.3).
    "auto_vehicle_use": {
        "forms":       {"ACORD_127"},
        "question":    "How are your business vehicles mainly used - service calls, "
                       "retail delivery, general commercial use, for hire, farm, or "
                       "personal use?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": "Service, Retail, Commercial, For hire, Farm, Pleasure or Other",
    },
    "auto_physical_damage_valuation": {
        "forms":       {"ACORD_127"},
        "question":    "For physical damage coverage, how should vehicle value be determined?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().upper() in {
            "ACV", "ACTUAL CASH VALUE", "AGREED VALUE", "STATED AMOUNT"
        },
        "format_hint": "Actual Cash Value, Agreed Value, or Stated Amount",
    },
    "auto_covered_symbols": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        # Asked as a transfer, not a decision: the carrier already designated
        # the covered autos on the declarations. See services/auto_symbols.py.
        "question":    "Which covered-auto symbols does the policy show for each "
                       "coverage? (e.g. Liability 1, Comprehensive 7, Collision 7)",
        "tier": None, "required": False,
        "validate":    _is_covered_auto_symbols,
        "format_hint": "Coverage and symbol number, e.g. 'Liability 1, "
                       "Comprehensive 7, Collision 7'",
    },
    "auto_um_uim_limit": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "Do you want UM/UIM coverage? If yes, what limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "auto_med_pay_limit": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "Do you want Medical Payments or PIP coverage? If yes, what limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "auto_hired_nonowned": {
        "forms":       {"ACORD_127", "ACORD_137_CA", "ACORD_137_CO"},
        "question":    "Do employees drive rented or personally-owned vehicles for business?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"yes", "no"},
        "format_hint": "Yes or No",
    },

    # ── Workers Comp — ACORD 130 ────────────────────────────────────────────
    "wc_payroll": {
        "forms":       {"ACORD_130"},
        "question":    "What is the total annual payroll for employees covered under Workers Compensation?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $500,000)",
    },
    "wc_class_codes": {
        "forms":       {"ACORD_130"},
        "question":    "What types of work do your employees perform?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "wc_xmod": {
        "forms":       {"ACORD_130"},
        "question":    "Has your business received a workers comp experience modification factor (X-Mod)?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^\d+(\.\d{1,3})?$', v.strip())),
        "answer_validate": _xmod_answer,
        "format_hint": "Decimal number (e.g. 0.95 or 1.10)",
    },
    "wc_xmod_effective_date": {
        "forms":       {"ACORD_130"},
        "question":    "What is the effective date of your WC X-Mod?",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },
    "wc_officer_exclusions": {
        "forms":       {"ACORD_130"},
        "question":    "Are there owners or officers who should NOT be covered under Workers Compensation?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "wc_monopolistic_payroll": {
        "forms":       {"ACORD_130"},
        "question":    "Do you have employees in ND, OH, WA, or WY? If yes, provide payroll by state.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "wc_payroll_by_state": {
        "forms":       {"ACORD_130"},
        "question":    "Please provide your payroll broken out by state and job classification.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "wc_el_each_accident": {
        "forms":       {"ACORD_130"},
        "question":    "What is the Employer's Liability limit per accident?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "wc_el_disease_each_employee": {
        "forms":       {"ACORD_130"},
        "question":    "What is the Employer's Liability disease limit per employee?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "wc_el_disease_policy_limit": {
        "forms":       {"ACORD_130"},
        "question":    "What is the Employer's Liability disease policy limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "wc_prior_carrier": {
        "forms":       {"ACORD_130"},
        "question":    "Who was your previous Workers Compensation insurance carrier?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "wc_payroll_period": {
        "forms":       {"ACORD_130"},
        "question":    "What period does your WC payroll figure cover?",
        "tier": None, "required": False,
        # By MEANING, not one spelling (owner 2026-08-26, V1 H1 6.4): "per
        # year", "12 months", "annualized", "yearly" all mean annual, and the
        # five-word allow-list this used to be rejected every one of them.
        # `coverage_evidence.payroll_period_meaning` is the ONE reader of the
        # vocabulary - the scorer, the validator and the stamper all ask it.
        "validate":    _is_payroll_period,
        "format_hint": "Annual, Quarterly, Monthly, etc.",
    },

    # ── Umbrella — ACORD 131 ────────────────────────────────────────────────
    "umbrella_limit": {
        "forms":       {"ACORD_131"},
        "question":    "How much additional liability coverage on top of your other policies?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $5,000,000)",
    },
    "umbrella_sir": {
        "forms":       {"ACORD_131"},
        "question":    "How much would you cover yourself before the umbrella kicks in (self-insured retention)?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "umbrella_attachment_point": {
        "forms":       {"ACORD_131"},
        "question":    "At what underlying coverage limit does your umbrella policy attach?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "underlying_policies": {
        "forms":       {"ACORD_131"},
        "question":    "Please list your underlying liability policies with limits, carriers, and policy numbers.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "schedule_of_underlying_insurance": {
        "forms":       {"ACORD_131"},
        "question":    "Is a Schedule of Underlying Insurance included with this submission (the list of underlying GL/Auto/EL policies the umbrella sits over)?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "umbrella_follow_form": {
        "forms":       {"ACORD_131"},
        "question":    "Do the submitted documents explicitly state the umbrella follows form over the underlying coverages? Leave blank if it is not explicitly stated - coverage is never assumed.",
        "tier": None, "required": False,
        "validate":    None,
        # Declared 24 Sep 2026: the question IS a Yes/No, and without the hint
        # the comparison door read this fact as free text - so a certificate's
        # form reference was offered as a rival to a declarations page's "Yes"
        # (client item 10, "boolean vs ...").
        "format_hint": "Yes or No",
    },
    "employers_liability_limits": {
        "forms":       {"ACORD_131"},
        "question":    "What are your Employers Liability limits on your WC policy?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "umbrella_effective_date": {
        "forms":       {"ACORD_131"},
        "question":    "What date does your umbrella/excess liability policy start? (MM/DD/YYYY)",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },
    "umbrella_expiration_date": {
        "forms":       {"ACORD_131"},
        "question":    "What date does your umbrella/excess liability policy end? (MM/DD/YYYY)",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },

    # ── Property — ACORD 140 ────────────────────────────────────────────────
    "property_building_value": {
        "forms":       {"ACORD_140"},
        "question":    "If your building had to be completely rebuilt today, what would it cost?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $2,000,000)",
    },
    "property_bpp_value": {
        "forms":       {"ACORD_140"},
        "question":    "What is the total value of your business equipment, furniture, inventory, and contents?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $500,000)",
    },
    "construction_type": {
        "forms":       {"ACORD_140"},
        "question":    "What is your building mainly made of?",
        "tier": None, "required": False,
        # "MASONRY" (22 Oct 2026): the hint below names it, and the check
        # refused it - a client typing it was held, a producer refused.
        "validate":    lambda v: v.strip().upper() in {
            "FRAME", "WOOD FRAME", "JOISTED MASONRY", "MASONRY NON-COMBUSTIBLE",
            "NON-COMBUSTIBLE", "MODIFIED FIRE RESISTIVE", "FIRE RESISTIVE",
            "MASONRY", "BRICK", "CONCRETE", "STEEL", "MIXED",
        },
        "format_hint": "Frame, Masonry, Concrete, Steel, etc.",
    },
    "occupancy_type": {
        "forms":       {"ACORD_140"},
        "question":    "What is your building used for on a day-to-day basis?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "year_built": {
        "forms":       {"ACORD_140"},
        "question":    "What year was your building originally built?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^(1[6-9]\d{2}|20[012]\d)$', v.strip())),
        "format_hint": "4-digit year (e.g. 1995)",
    },
    "roof_year": {
        "forms":       {"ACORD_140"},
        "question":    "What year was the roof last replaced or repaired?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^(1[6-9]\d{2}|20[012]\d)$', v.strip())),
        "format_hint": "4-digit year (e.g. 2015)",
    },
    "sprinkler_system": {
        "forms":       {"ACORD_140"},
        "question":    "Does your building have a fire sprinkler system installed?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {
            "yes", "no", "partial", "full", "wet", "dry", "none"
        },
        "format_hint": "Yes, No, Partial, Full, Wet, or Dry",
    },
    "fire_protection_class": {
        "forms":       {"ACORD_140"},
        "question":    "What is your building's fire protection class? (1–10 scale)",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().isdigit() and 1 <= int(v.strip()) <= 10,
        "answer_validate": _protection_class_answer,
        "format_hint": "Number from 1 to 10",
    },
    "distance_to_hydrant": {
        "forms":       {"ACORD_140"},
        "question":    "How far is the nearest fire hydrant from your building (in feet)?",
        "tier": None, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Distance in feet (whole number)",
    },
    "fire_department_type": {
        "forms":       {"ACORD_140"},
        "question":    "Is the nearest fire department volunteer or professional (paid)?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"volunteer", "professional", "paid", "career", "combination"},
        "format_hint": "Volunteer or Professional",
    },
    "valuation_method": {
        "forms":       {"ACORD_140"},
        "question":    "If there is a loss, how would you like your property valued? (RCV or ACV)",
        "tier": None, "required": False,
        "validate":    _is_valuation,
        "answer_validate": _valuation_answer,
        "format_hint": "RCV (Replacement Cost Value) or ACV (Actual Cash Value)",
    },
    "coinsurance_percentage": {
        "forms":       {"ACORD_140"},
        "question":    "Does your insurance require you to insure your property for a minimum percentage?",
        "tier": None, "required": False,
        "validate":    _is_percent,
        "format_hint": "Percentage (e.g. 80 or 90)",
    },
    "business_income_limit": {
        "forms":       {"ACORD_140"},
        "question":    "If your business had to close temporarily, how much income would you need covered per month?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount per month (e.g. $50,000)",
    },
    "period_of_restoration": {
        "forms":       {"ACORD_140"},
        "question":    "If damaged, how many months to reopen?",
        "tier": None, "required": False,
        "validate":    lambda v: _is_positive_int(v) and int(v.strip()) <= 60,
        "format_hint": "Whole number of months (e.g. 6)",
    },
    "extra_expense_limit": {
        "forms":       {"ACORD_140"},
        "question":    "Do you want Extra Expense coverage? If yes, what limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "property_deductible_aop": {
        "forms":       {"ACORD_140"},
        "question":    "How much would you pay out of pocket for most property claims? (All Other Perils deductible)",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $5,000)",
    },
    # Amount OR percentage (`takes_amount_or_percent`): `validate` stays the
    # dollar shape; a person's "2%" passes `answer_check`.
    "property_deductible_wind": {
        "forms":       {"ACORD_140"},
        "question":    "How much would you pay out of pocket for wind or hail damage?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount or percentage (e.g. $5,000 or 2%)",
    },
    "property_deductible_earthquake": {
        "forms":       {"ACORD_140"},
        "question":    "How much would you pay out of pocket for earthquake damage?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount or percentage (e.g. $25,000 or 5%)",
    },
    "property_deductible_flood": {
        "forms":       {"ACORD_140"},
        "question":    "How much would you pay out of pocket for flood damage?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "deductible_basis": {
        "forms":       {"ACORD_140"},
        "question":    "How is your property deductible applied — per occurrence or per cause of loss?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {
            "per occurrence", "per cause of loss", "per location", "occurrence", "cause of loss"
        },
        "format_hint": "Per Occurrence or Per Cause of Loss",
    },
    "deductible_application": {
        "forms":       {"ACORD_140"},
        "question":    "Does your deductible apply per building, per location, or per occurrence?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "agreed_value_endorsement": {
        "forms":       {"ACORD_140"},
        "question":    "Does your property policy include an agreed value endorsement? (Yes or No)",
        "tier": None, "required": False,
        "validate":    lambda v: str(v).strip().lower() in {"yes", "no", "true", "false"},
        "format_hint": "Yes or No",
    },
    "building_ITV_percentage": {
        "forms":       {"ACORD_140"},
        "question":    "What percentage of your building's full replacement cost is it currently insured for?",
        "tier": None, "required": False,
        "validate":    _is_percent,
        "format_hint": "Percentage (e.g. 100)",
    },
    "mortgagee_name": {
        "forms":       {"ACORD_140"},
        "question":    "Does a bank or lender have a financial interest in your building? If yes, their name and address?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "locations": {
        "forms":       {"ACORD_125", "ACORD_140"},
        "question":    "Please list all business locations to be covered.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "property_locations": {
        "forms":       {"ACORD_140"},
        "question":    "Please confirm the physical addresses of all insured property locations.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Contractors Supplement — ACORD 186 ──────────────────────────────────
    "contractor_type": {
        "forms":       {"ACORD_186"},
        "question":    "What type of contracting work does your business perform?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Certificate — ACORD 25 ──────────────────────────────────────────────
    "certificate_holder": {
        "forms":       {"ACORD_25"},
        "question":    "Is there a company, landlord, or individual who needs written proof of your insurance?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Risk transfer (all forms) ────────────────────────────────────────────
    "risk_transfer": {
        "forms":       {"ACORD_125", "ACORD_126"},
        "question":    "Do any contracts require Additional Insured, Waiver of Subrogation, or Primary & Non-Contributory wording?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Auto — additional fields ─────────────────────────────────────────────
    "auto_garaging_addresses": {
        "forms":       {"ACORD_127"},
        "question":    "Where are your business vehicles primarily kept overnight?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "auto_covered_symbols": {
        "forms":       {"ACORD_127"},
        "question":    "Which covered-auto symbols does the policy show for each "
                       "coverage? (e.g. Liability 1, Comprehensive 7, Collision 7)",
        "tier": None, "required": False,
        "validate":    _is_covered_auto_symbols,
        "format_hint": "Coverage and symbol number, e.g. 'Liability 1, "
                       "Comprehensive 7, Collision 7'",
    },
    "auto_um_uim_limit": {
        "forms":       {"ACORD_127"},
        "question":    "Do you want UM/UIM coverage? If yes, what limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "auto_med_pay_limit": {
        "forms":       {"ACORD_127"},
        "question":    "Do you want Medical Payments or PIP coverage? If yes, what limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    # ── Loss history / claims ────────────────────────────────────────────────
    "loss_run_age_days": {
        "forms":       {"ACORD_125"},
        "question":    "How old are your most recent loss runs (in days)?",
        "tier": None, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number of days",
    },

    # ── BOP — ACORD 160 ──────────────────────────────────────────────────────
    "bop_liability_limit": {
        "forms":       {"ACORD_160"},
        "question":    "What is your BOP liability limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "bop_property_limit": {
        "forms":       {"ACORD_160"},
        "question":    "What is your BOP property limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "bop_deductible": {
        "forms":       {"ACORD_160"},
        "question":    "What is your BOP deductible?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },

    # ── Builders Risk — NO SECTION FORM (2026-09-05) ─────────────────────────
    # These seven declared `forms={"ACORD_133"}`, which was wrong twice over:
    # ACORD 133 is the Workers Compensation Assigned Risk section (its own
    # template says so; 67 of its 136 fields are WorkersCompensation*, none is
    # a builders-risk field), so they never had a box to stamp AND the claim
    # made `fact_equivalence.fact_line` answer "workers_comp" for every one of
    # them - which in turn made `coverage_evidence.coverage_flag_supported`
    # return True for has_workers_comp on a builders-risk-only package.
    # `forms=set()` is the honest statement: builders risk has no section form
    # in this product. It keeps its ACORD 125 sections-attached indicator and
    # its own project-value cross-form check. OPEN PRODUCT QUESTION for Brent.
    "builders_risk_project_address": {
        "forms":       set(),          # no section form - see the note above
        "question":    "What is the full address of the construction or renovation project?",
        "tier": 1, "required": True,
        "validate":    lambda v: len(v.strip()) >= 10,
        "format_hint": "Full project address including street, city, state, ZIP",
    },
    "builders_risk_project_cost": {
        "forms":       set(),          # no section form - see the note above
        "question":    "What is the total project cost or contract value?",
        "tier": 1, "required": True,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $2,500,000)",
    },
    "builders_risk_completion_date": {
        "forms":       set(),          # no section form - see the note above
        "question":    "What is the anticipated project completion date?",
        "tier": 1, "required": True,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },
    "builders_risk_construction_type": {
        "forms":       set(),          # no section form - see the note above
        "question":    "What is the construction type for this project (Frame, Masonry, Steel, etc.)?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "builders_risk_owner_name": {
        "forms":       set(),          # no section form - see the note above
        "question":    "Who is the project owner?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "builders_risk_contractor_name": {
        "forms":       set(),          # no section form - see the note above
        "question":    "Who is the general contractor on this project?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "builders_risk_insured_interest": {
        "forms":       set(),          # no section form - see the note above
        "question":    "What is the insured's interest in this project (Owner, Contractor, or Lender)?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"owner", "contractor", "lender", "other"},
        "format_hint": "Owner, Contractor, or Lender",
    },

    # ── Crime coverage facts (no ACORD 137/138 mapping) ─────────────────────
    "crime_limit": {
        "forms":       set(),
        "question":    "What is the crime coverage limit per insuring agreement?",
        "tier": 1, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $250,000)",
    },
    "crime_deductible": {
        "forms":       set(),
        "question":    "What is the crime policy deductible?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "crime_employee_count": {
        "forms":       set(),
        "question":    "How many employees are covered under the crime policy?",
        "tier": None, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number",
    },
    "crime_locations_count": {
        "forms":       set(),
        "question":    "How many locations does the crime policy cover?",
        "tier": None, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Whole number",
    },

    # ── Cyber / Network Security facts (no ACORD 137/138 mapping) ───────────
    "cyber_limit": {
        "forms":       set(),
        "question":    "What is the cyber liability coverage limit?",
        "tier": 1, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "cyber_retention": {
        "forms":       set(),
        "question":    "What is the cyber policy retention or deductible?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "cyber_prior_incidents": {
        "forms":       set(),
        "question":    "Has the business experienced any prior cyber incidents or data breaches? (Yes or No)",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().lower() in {"yes", "no", "true", "false"},
        "format_hint": "Yes or No",
    },
    "cyber_controls_mfa": {
        "forms":       set(),
        "question":    "Does the business use multi-factor authentication (MFA) across all critical systems?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "cyber_controls_backups": {
        "forms":       set(),
        "question":    "Does the business maintain regular offline or offsite data backups?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "cyber_pii_records_count": {
        "forms":       set(),
        "question":    "Approximately how many PII records does the business store or process?",
        "tier": None, "required": False,
        "validate":    _is_positive_int,
        "format_hint": "Number of records",
    },
    "cyber_third_party_vendors": {
        "forms":       set(),
        "question":    "Does the business use third-party vendors with access to its systems or customer data?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Inland Marine — ACORD 160 ────────────────────────────────────────────
    "inland_marine_total_value": {
        "forms":       {"ACORD_160"},
        "question":    "What is the total insured value of all scheduled inland marine items?",
        "tier": 1, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $500,000)",
    },
    "inland_marine_transit_limit": {
        "forms":       {"ACORD_160"},
        "question":    "What is the in-transit or motor truck cargo coverage limit?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "inland_marine_items": {
        "forms":       {"ACORD_160"},
        "question":    "Please list each scheduled inland marine item: description, value, and serial number if available.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Contractors Supplemental additions — ACORD 186 ───────────────────────
    "contractor_residential_pct": {
        "forms":       {"ACORD_186"},
        "question":    "What percentage of your contracting work is residential?",
        "tier": None, "required": False,
        "validate":    _is_percent,
        "format_hint": "Percentage 0–100 (e.g. 30)",
    },
    "contractor_commercial_pct": {
        "forms":       {"ACORD_186"},
        "question":    "What percentage of your contracting work is commercial?",
        "tier": None, "required": False,
        "validate":    _is_percent,
        "format_hint": "Percentage 0–100 (e.g. 70)",
    },
    "contractor_high_hazard_ops": {
        "forms":       {"ACORD_186"},
        "question":    "Does your business perform any high-hazard operations such as blasting, demolition, roofing, scaffolding, or underwater work? List all that apply.",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "contractor_license_number": {
        "forms":       {"ACORD_186"},
        "question":    "What is the contractor's license number and the state that issued it?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Certificate of Liability additions — ACORD 25 ────────────────────────
    "certificate_holder_address": {
        "forms":       {"ACORD_25"},
        "question":    "What is the certificate holder's full mailing address?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "certificate_description_of_operations": {
        "forms":       {"ACORD_25"},
        "question":    "What description of operations, locations, or vehicles should appear on the certificate?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Evidence of Property Insurance — ACORD 28 ────────────────────────────
    "loss_payee_name": {
        "forms":       {"ACORD_28"},
        "question":    "Does a lender, leasing company or other party have a financial interest in anything you are insuring - a vehicle, equipment or a building? If so, what is their name? (If none, write 'None')",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },

    # ── Additional Remarks — ACORD 101 ───────────────────────────────────────
    "additional_remarks_text": {
        "forms":       {"ACORD_101"},
        "question":    "Please provide any additional remarks, explanations, or narrative to attach to the submission (e.g. claims context, operations detail, conflict resolution).",
        "tier": None, "required": False,
        "validate":    lambda v: len(v.strip()) >= 10,
        "format_hint": "Free-text explanation (at least 10 characters)",
    },

    # ── Loss History Schedule ─────────────────────────────────────────────────
    "loss_history": {
        "forms":       {"ACORD_125", "ACORD_186"},
        "question":    "Provide the loss history schedule (date, description, amount, paid, claim number, open/closed for each claim).",
        "tier": 2, "required": False,
        "validate":    None,
        "format_hint": "List of loss run records",
    },

    # ── Prior Coverage by Line ────────────────────────────────────────────────
    "prior_coverage_by_line": {
        "forms":       {"ACORD_125", "ACORD_126", "ACORD_127", "ACORD_130", "ACORD_131"},
        "question":    "List prior coverage by line of business (carrier, policy number, effective and expiration dates, premium).",
        "tier": 2, "required": False,
        "validate":    None,
        "format_hint": "List of prior policy records per line",
    },

    # ── WC Officers / Owners ──────────────────────────────────────────────────
    "wc_officers": {
        "forms":       {"ACORD_130"},
        "question":    "List all officers and owners subject to workers compensation (name, title, ownership %, include/exclude).",
        "tier": 2, "required": False,
        "validate":    None,
        "format_hint": "List of officer/owner records",
    },

    # ── Garage / Dealers (ACORD 138) ─────────────────────────────────────────
    "garage_operations_type": {
        "forms":       {"ACORD_138_CA", "ACORD_138_CO"},
        "question":    "What type of garage operations does the insured conduct (Dealers, Service, Parking, etc.)?",
        "tier": 2, "required": False,
        "validate":    None,
        "format_hint": "e.g. Dealers, Service, Parking",
    },
    "garage_liability_limit": {
        "forms":       {"ACORD_138_CA", "ACORD_138_CO"},
        "question":    "What is the garage liability coverage limit?",
        "tier": 2, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "garage_deductible": {
        "forms":       {"ACORD_138_CA", "ACORD_138_CO"},
        "question":    "What is the garage liability deductible?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "garagekeeper_liability_limit": {
        "forms":       {"ACORD_138_CA", "ACORD_138_CO"},
        "question":    "What is the garagekeepers liability coverage limit?",
        "tier": 2, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "garagekeeper_comp_deductible": {
        "forms":       {"ACORD_138_CA", "ACORD_138_CO"},
        "question":    "What is the garagekeepers comprehensive deductible?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "garagekeeper_coll_deductible": {
        "forms":       {"ACORD_138_CA", "ACORD_138_CO"},
        "question":    "What is the garagekeepers collision deductible?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "auto_dealers_inventory_value": {
        "forms":       {"ACORD_138_CA", "ACORD_138_CO"},
        "question":    "What is the total inventory value for the auto dealers operation?",
        "tier": 2, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },

    # ── WC Description of Operations (ACORD 130) ──────────────────────────────
    "wc_description_of_operations": {
        "forms":       {"ACORD_130"},
        "question":    "Provide a description of operations for the workers compensation application.",
        "tier": 2, "required": False,
        "validate":    None,
        "format_hint": "Free-text operations description",
    },

    # ── The ONE premises' interest, and a tenant's landlord (29 Sep 2026) ─────
    # Orbin 22 Sep item 12 and G2 - see services/premises_interest.py. Asked
    # only on a ONE-location package (a producer card and an optional client
    # question), never inferred, never scored (tier None), and deliberately NOT
    # in `sqs_service.FORM_FIELD_INVENTORY`, so no generator asks them on its
    # own. NAMING: none may start with `property_` - `lob_canon.
    # fact_line_family` would file it under the property line.
    "premises_interest": {
        "forms":       {"ACORD_125"},
        "question":    "Does your business own the building at its location, or rent the space it uses?",
        "tier": None, "required": False,
        "validate":    _premises_interest_answer,
        "format_hint": "Tenant, Owner, or Other",
    },
    # Recorded for certificates; printed on no form yet (the ACORD 125
    # additional-interest row and the ACORD 25 holder are Brent's call).
    "landlord_name": {
        "forms":       {"ACORD_125"},
        "question":    "What is the full name of your landlord (the owner of the building you rent)?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "landlord_address": {
        "forms":       {"ACORD_125"},
        "question":    "What is your landlord's full mailing address? (Street, City, State, ZIP)",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    # The producer's answer to "which line is this coverage part?" (14 Oct
    # 2026, owner - the coverage-part card on the Review screen). One stored
    # text, "<part key>=<line>; ...", composed by that card's choice list
    # (`lob_canon.part_line_choices`) and read by `lob_canon.parse_part_lines`
    # for the review alone: it prints on no form, no scorer reads it and no
    # questionnaire asks it (no form binds it). `lob_canon.PART_LINES_FACT`.
    "coverage_part_lines": {
        "forms":       set(),
        "question":    "Which line does each listed coverage part belong to?",
        "tier": None, "required": False,
        "validate":    _coverage_part_lines_answer,
        "format_hint": "A line chosen for each coverage part",
    },

    # ── The narrative questionnaire (Brent's attachment A, 23 Oct 2026) ─────
    # Facts no other fact already holds - `services/questionnaire.py` maps
    # every other question onto an existing fact. Keyed `qn_` (never a line
    # prefix, so `lob_canon.fact_line_family` and `line_presence` read none of
    # them as evidence of a coverage line) and named so the answer readers'
    # name heuristics (`answer_semantics._declared_kind`,
    # `audit_routes._validate_producer_answer`) give each its intended type -
    # pinned by tests/test_build26_questionnaire.py. Kept out of the gap-fill
    # facts block (`pdf_service._build_facts_block`); only the approved carrier
    # narrative prints, on ACORD 101 (`pdf_service._acord101_blocks`).
    "contact_title":               _questionnaire_fact("What is the primary contact's role or title?"),
    "qn_submission_purpose":       _questionnaire_fact("Is this submission new business, a renewal or a remarketing?"),
    "qn_requested_terms":          _questionnaire_fact("What limits and deductibles are wanted?"),
    "qn_decision_deadline":        _questionnaire_fact("What is the decision deadline?", _QN_DATE_HINT, _is_date),
    "qn_quote_due":                _questionnaire_fact("When is the quote due?", _QN_DATE_HINT, _is_date),
    "qn_attractive_summary":       _questionnaire_fact("What makes this account attractive to underwrite? Brief factual summary of operations and controls."),
    "qn_owner_experience":         _questionnaire_fact("How many years of experience do the owners have?", _QN_COUNT_HINT, _is_positive_int),
    "qn_ownership_changes":        _questionnaire_fact("Any ownership changes or acquisitions?"),
    "qn_customer_types":           _questionnaire_fact("Who are the primary customers?"),
    "qn_operations_mix":           _questionnaire_fact("What share of revenue comes from each operation? The shares must total 100%.",
                                                       "Each operation with its share of revenue - the shares must add up to the whole (100)",
                                                       _revenue_shares_answer),
    "qn_work_type_mix":            _questionnaire_fact("How does the work split between new construction, service and repair?"),
    "qn_prior_year_revenue":       _questionnaire_fact("What was the prior year's annual gross revenue?", _QN_MONEY_HINT, _is_currency),
    "qn_projected_revenue":        _questionnaire_fact("What annual gross revenue is projected for next year?", _QN_MONEY_HINT, _is_currency),
    "qn_growth_explanation":       _questionnaire_fact("What explains any material change in revenue?"),
    "qn_seasonal_staff":           _questionnaire_fact("How many seasonal employees are there?", _QN_COUNT_HINT, _is_positive_int),
    "qn_leased_temp_labor":        _questionnaire_fact("Are leased employees or temporary labor used?"),
    "qn_jobsite_locations":        _questionnaire_fact("Where are the jobsites?"),
    "qn_international_exposure":   _questionnaire_fact("Any international exposures?"),
    "qn_new_operations":           _questionnaire_fact("Any unusual or newly added operations?"),
    "qn_credentials":              _questionnaire_fact("Which licenses and certifications are held?"),
    "qn_contract_requirements":    _questionnaire_fact("Any contractual insurance requirements?"),
    "qn_planned_changes":          _questionnaire_fact("Any major changes anticipated in the next 12 months?"),
    "qn_loss_run_gaps":            _questionnaire_fact("Loss runs by line: valuation dates and any missing years."),
    "qn_corrective_actions":       _questionnaire_fact("What corrective actions followed material losses, and have conditions changed?"),
    "qn_safety_program":           _questionnaire_fact("Describe the safety program, employee training, inspections, incident reporting, contractual risk transfer and management oversight."),
    "qn_prior_nonrenewals":        _questionnaire_fact("Any prior nonrenewals, cancellations, declinations, significant underwriting restrictions or coverage gaps? Please explain."),
    "qn_work_exposures":           _questionnaire_fact("Work types, largest projects, project values, jobsite hazards, height/depth work, hot work, excavation and other exposures."),
    "qn_gl_wc_alignment":          _questionnaire_fact("Do the GL operations align with the WC classifications?"),
    "qn_subcontractor_controls":   _questionnaire_fact("Subcontracted work percentage, subcontractor selection, certificates, additional insured and waiver requirements."),
    "qn_contract_indemnity":       _questionnaire_fact("Contract terms, indemnity, hold harmless, additional insured requirements and any wrap-up / OCIP / CCIP work."),
    "qn_completed_ops_exposure":   _questionnaire_fact("Products / completed operations exposure, warranties, recalls, professional / design responsibilities and prior completed-work losses."),
    "qn_estimated_or_actual":      _questionnaire_fact("Is the payroll estimated or actual?"),
    "qn_loss_control":             _questionnaire_fact("Loss-control practices and safety responsibilities."),
    "qn_independent_contractors":  _questionnaire_fact("Subcontractor / independent-contractor labor, certificates, uninsured subcontractor exposure and out-of-state work."),
    "qn_alternate_employer":       _questionnaire_fact("Any alternate employer or waiver of subrogation requirements?"),
    "qn_fleet_mix":                _questionnaire_fact("Any leased or employee-owned vehicles?"),
    "qn_garaging_locations":       _questionnaire_fact("Where are the vehicles garaged?"),
    "qn_commodities_hauled":       _questionnaire_fact("What commodities are carried?"),
    "qn_special_vehicle_exposures": _questionnaire_fact("Any special vehicle exposures?"),
    "qn_driver_program":           _questionnaire_fact("Driver eligibility, MVR review, telematics, driver training, accident controls and vehicle maintenance."),
    "qn_fleet_changes_filings":    _questionnaire_fact("Prior auto losses, changes to the fleet and applicable filings."),
    "qn_building_upgrades":        _questionnaire_fact("Stories, updates and protective safeguards, per building."),
    "qn_cat_exposure":             _questionnaire_fact("Stock and equipment values, and catastrophe exposures."),
    "qn_alarms_systems":           _questionnaire_fact("Alarms and critical building systems, where known."),
    "qn_bi_continuity":            _questionnaire_fact("Business Income basis, dependencies, maximum expected downtime and continuity plan."),
    "qn_vacancy_renovation":       _questionnaire_fact("Vacancy, renovations, property in transit, offsite property and seasonal inventory changes."),
    "qn_umbrella_gaps":            _questionnaire_fact("Known exclusions, gaps, differing underlying terms, auto / WC / GL coordination and contractual limit requirements."),
    "qn_excess_severity":          _questionnaire_fact("Large contracts, high-hazard operations and prior severe losses relevant to excess underwriting."),
    "qn_cyber_data_types":         _questionnaire_fact("Business use of technology, sensitive data types and reliance on critical vendors."),
    "qn_cyber_other_controls":     _questionnaire_fact("Endpoint protection, patching and access controls."),
    "qn_cyber_incident_plan":      _questionnaire_fact("Incident response plan, employee security training, ransomware / payment fraud exposure and outsourcing."),
    "qn_cyber_dependencies":       _questionnaire_fact("Business interruption dependencies, revenue impact and contractual requirements."),
    "qn_epli_practices":           _questionnaire_fact("EPLI: workforce geography, HR practices, employee handbook, complaint procedures, turnover and employment claims."),
    "qn_do_governance":            _questionnaire_fact("D&O: entity ownership, board / governance, funding, debt, financial changes and known disputes."),
    "qn_professional_controls":    _questionnaire_fact("Professional liability: professional services, contracts, project / client concentration, quality controls and claims."),
    "qn_ebl_administration":       _questionnaire_fact("Employee Benefits Liability: benefit plans administered, enrollment / eligibility procedures, third-party administrators and known administrative errors."),
    "qn_specialty_property":       _questionnaire_fact("Specific insured property, activities, locations, values, custody / control, transit and catastrophe exposure."),
    "qn_crime_controls":           _questionnaire_fact("Crime: funds-transfer approval, segregation of duties, employee dishonesty and social engineering controls."),
    "qn_pollution_exposure":       _questionnaire_fact("Pollution: materials handled, disposal practices, historical incidents and remediation obligations."),
    "qn_other_exposures":          _questionnaire_fact("Any other unusual exposures or requested endorsements not captured above?"),
    "qn_submission_reason":        _questionnaire_fact("Why is this account being submitted now, and what coverage outcome is requested?"),
    "qn_top_strengths":            _questionnaire_fact("What are the top three risk strengths and supporting evidence?"),
    "qn_top_concerns":             _questionnaire_fact("What are the top three material underwriting concerns and how are they mitigated?"),
    "qn_changes_since_prior":      _questionnaire_fact("What has changed since the prior policy period, and what must the underwriter know?"),
    "qn_outstanding_plan":         _questionnaire_fact("What information is still outstanding, who owns it and when will it be provided?"),
    # The carrier-facing narrative the producer APPROVED (C110): written by
    # `questionnaire.approve_narrative`, printed first on ACORD 101's remarks.
    "qn_carrier_narrative":        _questionnaire_fact("The approved carrier-facing submission narrative."),

}

# ---------------------------------------------------------------------------
# Validation API
# ---------------------------------------------------------------------------

def validate_fact(field: str, value: str) -> bool:
    """
    Validate a single extracted fact value against the registry's validate rule.
    Returns True if valid or if no validator is defined for the field.
    Returns False if validator is defined and value fails.

    value should be the raw string (not the {value: ..., ocr_confident: ...} dict).
    """
    entry = FACT_REGISTRY.get(field)
    if entry is None:
        return True   # unknown field — no opinion
    validator: Optional[Callable[[str], bool]] = entry.get("validate")
    if validator is None:
        return True   # no rule defined — passes
    try:
        return bool(validator(str(value).strip()))
    except Exception:
        return False


def validation_error(field: str) -> Optional[str]:
    """
    Returns the format_hint string for a field if it has a validator,
    or None if no validator is defined.
    Used to construct user-facing error messages.
    """
    entry = FACT_REGISTRY.get(field)
    if entry is None:
        return None
    return entry.get("format_hint")


# ---------------------------------------------------------------------------
# Derived views — backwards-compatible aliases consumed by arq_service.py
# ---------------------------------------------------------------------------
_FIELD_QUESTION_MAP: dict[str, str] = {k: v["question"] for k, v in FACT_REGISTRY.items()}
_FIELD_TO_FORMS: dict[str, set]     = {k: v["forms"]    for k, v in FACT_REGISTRY.items()}

# ---------------------------------------------------------------------------
# Tier-derived sets — consumed by sqs_service.py
# ---------------------------------------------------------------------------

TIER1_REQUIRED_FIELDS: dict[str, str] = {
    k: v["question"]
    for k, v in FACT_REGISTRY.items()
    if v.get("tier") == 1 and v.get("required") is True
}

TIER1_CONTACT_FIELDS: tuple = ("contact_name", "contact_phone", "contact_email")

TIER2_SCORED_FIELDS: dict[str, str] = {
    k: v["question"]
    for k, v in FACT_REGISTRY.items()
    if v.get("tier") == 2
}

# ---------------------------------------------------------------------------
# Schedule row validation — validates the ROWS inside a list fact (e.g. one
# driver inside auto_drivers). Separate from FACT_REGISTRY's scalar
# ``validate`` above, which only ever sees one string value, never a list of
# dicts.
#
# Each rule: {"required": bool, "validate": callable(value) -> bool or None}.
# A sub-key with no rule entry is never checked. "required" only flags a
# missing value; it does not block anything downstream (field_qa, the sole
# consumer, is advisory-only — see services/field_qa.py).
# ---------------------------------------------------------------------------

def _is_experience_years(v) -> bool:
    try:
        n = float(str(v).strip())
        return 0 <= n <= 75
    except (ValueError, TypeError):
        return False


SCHEDULE_ROW_RULES: dict[str, dict[str, dict]] = {
    # ACORD 127 driver schedule (Figure 32 client feedback).
    "auto_drivers": {
        "name":                {"required": True,  "validate": lambda v: len(str(v).strip()) >= 2},
        "dob":                 {"required": False, "validate": _is_date},
        "license_number":      {"required": True,  "validate": lambda v: len(str(v).strip()) >= 3},
        "license_state":       {"required": False, "validate": None},
        "hire_date":           {"required": False, "validate": _is_date},
        "experience_years":    {"required": False, "validate": _is_experience_years},
        "vehicle_use_percent": {"required": False, "validate": _is_percent},
    },
}


def validate_schedule_rows(list_key: str, rows) -> list[dict]:
    """Validate every row of a schedule list fact against SCHEDULE_ROW_RULES.

    Returns a list of {"row_index", "sub_key", "issue" ("missing"|"invalid"),
    "value"} dicts — empty if ``list_key`` has no registered rules, ``rows``
    isn't a list, or every row passes. Never raises: a validator exception is
    treated as "invalid", not propagated.
    """
    rules = SCHEDULE_ROW_RULES.get(list_key)
    if not rules or not isinstance(rows, list):
        return []
    issues: list[dict] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for sub_key, rule in rules.items():
            val = row.get(sub_key)
            has_val = val is not None and str(val).strip().lower() not in ("", "null", "none")
            if not has_val:
                if rule.get("required"):
                    issues.append({"row_index": idx, "sub_key": sub_key, "issue": "missing", "value": None})
                continue
            validator = rule.get("validate")
            if validator is None:
                continue
            try:
                ok = bool(validator(val))
            except Exception:
                ok = False
            if not ok:
                issues.append({"row_index": idx, "sub_key": sub_key, "issue": "invalid", "value": str(val)})
    return issues


# ── The answer a producer would type (27 Oct 2026) ───────────────────────────
# For each fact whose format hint names no example ("e.g. ..."). The review
# page's plan stands a person's answer in with it (`review_plan.probe_value`)
# to say what each item adds, and the reach-100 test answers random packages
# with it. A generic stand-in ("Yes", "50") typed a contact named "Yes", a $50
# umbrella limit and a 50% coinsurance - raising the very warnings the page
# could then not clear, and promising points the real answer would not give.
# Every fact a person can answer has one: `example_answer` reads this, then
# the hint's own example; `test_reach_100_every_package` fails on a fact with
# neither that is not a choice list, a date or a yes / no question.
EXAMPLE_ANSWERS: dict[str, str] = {
    # names and identifiers
    "applicant_name": "Probe Contracting",
    "dba_name": "Probe Services",
    "contact_name": "Pat Probe",
    "contact_title": "Owner",
    "producer_name": "Probe Insurance Agency",
    "producer_contact_name": "Sam Agent",
    "carrier_name": "Probe Mutual Insurance Company",
    "submission_carrier_name": "Probe Mutual Insurance Company",
    "prior_carrier": "Probe Mutual Insurance Company",
    "wc_prior_carrier": "Probe Mutual Insurance Company",
    "carrier_naic": "12345",
    "prior_carrier_naic": "12345",
    "policy_number": "PRB-100001",
    "prior_policy_number": "PRB-100000",
    "contractor_license_number": "LIC-12345",
    "certificate_holder": "Probe Property Owner",
    "landlord_name": "Probe Property Owner",
    "loss_payee_name": "Probe Bank",
    "mortgagee_name": "Probe Bank",
    "builders_risk_owner_name": "Probe Property Owner",
    "builders_risk_contractor_name": "Probe Builders",
    # descriptions (neutral: names no industry, so no class-code check reads
    # a verdict into it that the person's real words would not)
    "account_description": "Answered by the producer.",
    "certificate_description_of_operations": "Answered by the producer.",
    "wc_description_of_operations": "Answered by the producer.",
    "contractor_type": "General contractor",
    "contractor_high_hazard_ops": "No",
    "builders_risk_construction_type": "Frame",
    "builders_risk_insured_interest": "Owner",
    "auto_liability_structure": "CSL",
    "auto_physical_damage_valuation": "Actual Cash Value",
    "deductible_basis": "Per Occurrence",
    # amounts
    "auto_dealers_inventory_value": "$500,000",
    "auto_deductible_collision": "$1,000",
    "auto_deductible_comp": "$1,000",
    "auto_med_pay_limit": "$5,000",
    "bop_deductible": "$1,000",
    "bop_liability_limit": "$1,000,000",
    "bop_property_limit": "$500,000",
    "crime_deductible": "$5,000",
    "cyber_retention": "$10,000",
    "extra_expense_limit": "$25,000",
    "garage_deductible": "$1,000",
    "garage_liability_limit": "$1,000,000",
    "garagekeeper_coll_deductible": "$1,000",
    "garagekeeper_comp_deductible": "$1,000",
    "garagekeeper_liability_limit": "$100,000",
    "inland_marine_transit_limit": "$100,000",
    "property_deductible_flood": "$25,000",
    "umbrella_attachment_point": "$1,000,000",
    "umbrella_sir": "$10,000",
    "employers_liability_limits": "$1,000,000",
    # counts and measures
    "crime_employee_count": "10",
    "crime_locations_count": "1",
    "cyber_pii_records_count": "1000",
    "loss_run_age_days": "30",
    "distance_to_hydrant": "500",
    "fire_protection_class": "3",
}
for _key, _example in EXAMPLE_ANSWERS.items():
    if _key in FACT_REGISTRY:
        FACT_REGISTRY[_key].setdefault("example", _example)

_HINT_EXAMPLE_RE = re.compile(r"e\.g\.\s*([^)]*)", re.IGNORECASE)


def example_answer(key: str) -> Optional[str]:
    """The answer a producer would type for `key` - its declared example, else
    the first example its format hint names ("Percentage (e.g. 80 or 90)" ->
    "80") - when the fact's own person-answer check accepts it; else None."""
    entry = FACT_REGISTRY.get(key)
    if not isinstance(entry, dict):
        return None
    candidates = [entry.get("example")]
    match = _HINT_EXAMPLE_RE.search(str(entry.get("format_hint") or ""))
    if match:
        first = re.split(r"\s+or\s+|,\s+(?=[A-Za-z'\"$])", match.group(1).strip())[0]
        candidates.append(first.strip().strip("'\"").strip())
    check = answer_check(entry)
    for value in candidates:
        if not value:
            continue
        try:
            if not callable(check) or check(value):
                return str(value)
        except Exception:                                      # noqa: BLE001
            continue
    return None
