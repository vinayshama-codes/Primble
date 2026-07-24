import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional

import httpx
import openai

from config.database import get_pool
from config.settings import ENABLE_SCHEDULE_CAPTURE, FRONTEND_URL, LLM_MODEL
from services import schedule_capture
from services.question_classifier import (
    AUDIENCE_CLIENT,
    BUCKET_CLIENT,
    PRIORITY_IMPORTANT,
    apply_default_selection,
    classify_question,
    decorate_questions,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Answer format validators
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# "I'm not sure" (client-facing don't-know) support
# ---------------------------------------------------------------------------
# Client requirement (Figure 14): a client who cannot answer a question — SIC /
# NAICS being the canonical example — must be able to say so explicitly and move
# on, instead of abandoning the questionnaire.
#
# The sentinel is deliberately NOT a normal answer:
#   * it is split out of `answers` at submit time and stored in the separate
#     `not_sure_fields` column, so it can never be stamped into an ACORD field,
#     never counts toward the answered/score totals, and never reaches the PDF;
#   * it is distinguishable from "client never reached this question", which is
#     the whole point — the producer gets an explicit follow-up list.
#
# It round-trips through `draft_answers` as a plain string, so a client can close
# the tab and come back and their "not sure" selections are still shown.
NOT_SURE_SENTINEL = "__NOT_SURE__"


def is_not_sure_value(raw) -> bool:
    """True when a submitted value is the explicit client 'I'm not sure' marker."""
    return isinstance(raw, str) and raw.strip() == NOT_SURE_SENTINEL


_VAL_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_VAL_PHONE_RE = re.compile(r"^[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}$")
_VAL_DATE_RE  = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$|^\d{4}-\d{2}-\d{2}$")
_VAL_NUM_RE   = re.compile(r"^\$?[\d,]+(\.\d+)?$")


def _field_format_type(field_name: str) -> str:
    """Infer expected format from field name."""
    fn = field_name.lower()
    if re.search(r"email", fn):
        return "email"
    if re.search(r"phone|fax|tel", fn):
        return "phone"
    if re.search(r"_date|date_|effective|expiration|retro|inception|dob", fn):
        return "date"
    if re.search(r"amount|limit|value|payroll|revenue|premium|deductible|aggregate|occurrence", fn):
        return "number"
    return "text"


# ---------------------------------------------------------------------------
# Structured input types + normalizers (Figure 18)
# ---------------------------------------------------------------------------
# Client requirement: "structured data types for currency, codes, dates,
# yes/no, and schedules". yes/no (`checkbox`) and schedules already shipped;
# currency / codes / dates are added here.
#
# `_FIELD_INPUT_TYPE` is a deliberately CURATED allowlist, NOT a name-regex
# sweep. `_field_format_type` above matches substrings such as "limit" and
# "value", which is fine for advisory validation but far too coarse to choose
# an INPUT WIDGET: `gl_limits` legitimately holds "$1,000,000 per occurrence /
# $2,000,000 aggregate" and `auto_liability_limit` holds "$1,000,000 combined
# single limit". Forcing either into a single-amount box would make a CORRECT
# answer untypeable. Only fields that genuinely hold one scalar are listed;
# every other field keeps its existing free-text behaviour.
_FIELD_INPUT_TYPE = {
    # currency - exactly one dollar amount
    "total_revenue":             "currency",
    "total_payroll":             "currency",
    "wc_payroll":                "currency",
    "property_building_value":   "currency",
    "property_bpp_value":        "currency",
    "gl_each_occurrence":        "currency",
    "gl_aggregate":              "currency",
    "gl_deductible":             "currency",
    "umbrella_limit":            "currency",
    "umbrella_sir":              "currency",
    "business_income_limit":     "currency",
    "property_deductible_aop":   "currency",
    "property_deductible_wind":  "currency",
    "auto_deductible_comp":      "currency",
    "auto_deductible_collision": "currency",
    # date - exactly one calendar date
    "effective_date":            "date",
    "expiration_date":           "date",
    "retro_date":                "date",
    # code - fixed-width identifier
    "naics_code":                "code",
    "sic_code":                  "code",
    "fein":                      "code",
    # number - a plain count or year, never money
    "num_employees":             "number",
    "years_in_business":         "number",
    "num_claims":                "number",
    "loss_history_years":        "number",
    "year_built":                "number",
    "roof_year":                 "number",
}

# Expected digit width per code field. Drives the client-side input cap, the
# submit-time normalizer, and nothing else - a wrong width is never rejected,
# only flagged for producer review (see `_clean_answer`).
_CODE_DIGITS = {"naics_code": 6, "sic_code": 4, "fein": 9}

# Curated questions whose WORDING asks for more than one value, so they must
# stay free text even though their underlying ACORD field is a single amount.
# `gl_limits` is phrased "$1,000,000 per incident / $2,000,000 total" and
# `auto_liability_limit` as "$1,000,000 combined single limit".
_NEVER_STRUCTURED = frozenset({"gl_limits", "auto_liability_limit"})

# Raw ACORD field names ending in `...Amount` are monetary by ACORD's own
# convention - their tooltips literally begin "Enter amount:". Verified against
# all 17 real schemas: 897 fields match, and every distinct trailing token is a
# money term (LimitAmount, PremiumAmount, DeductibleAmount, RemunerationAmount,
# CostNewAmount, AgreedOrStatedAmount, ...). The `$` anchor is what makes this
# safe: it excludes the checkbox family `...StatedAmountIndicator`, which ends
# in "Indicator" and is a /Btn, not a value.
_ACORD_AMOUNT_RE = re.compile(r"Amount$", re.IGNORECASE)


def _resolve_input_type(field_name: str, canonical_key: Optional[str] = None) -> str:
    """Structured input type for a question, or "text".

    Resolution mirrors `_resolve_producer_label`: canonical fact key first (so
    a raw ACORD field name resolves through it), then the raw name, then the
    instance-stripped base. The only inference fallback is DATE - a field named
    `..._EffectiveDate` really is a date, whereas "limit"/"value" are not
    reliably single amounts (see `_FIELD_INPUT_TYPE` above).
    """
    if canonical_key in _NEVER_STRUCTURED or field_name in _NEVER_STRUCTURED:
        return "text"
    for key in (canonical_key, field_name):
        if key and key in _FIELD_INPUT_TYPE:
            return _FIELD_INPUT_TYPE[key]
    base = re.sub(r"[_\s]+[a-zA-Z]$", "", field_name or "")
    base = re.sub(r"[_\s]+\d+$", "", base)
    if base in _FIELD_INPUT_TYPE:
        return _FIELD_INPUT_TYPE[base]
    if field_name and _field_format_type(field_name) == "date":
        return "date"
    # Raw ACORD monetary fields (`..._EachAccidentLimitAmount_A`). Deliberately
    # LAST, so a curated question always wins over the schema naming convention.
    if base and _ACORD_AMOUNT_RE.search(base):
        return "currency"
    return "text"


_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _normalize_date(val: str) -> Optional[str]:
    """Coerce a human-typed date to MM/DD/YYYY, or None if unparseable.

    The prior behaviour accepted ONLY MM/DD/YYYY and YYYY-MM-DD and silently
    DISCARDED anything else (see `_clean_answer`), so a client typing
    "June 1, 2025" lost the answer and was shown a success screen. Nothing is
    discarded now: an unparseable value is kept verbatim and flagged.
    """
    s = (val or "").strip()
    if not s:
        return None

    # 2025-06-01
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _fmt_date(y, mo, d)

    # 6/1/2025, 06-01-25, 6.1.2025
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})$", s)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:                      # 2-digit year: 70-99 -> 19xx, else 20xx
            y += 1900 if y >= 70 else 2000
        return _fmt_date(y, mo, d)

    # June 1, 2025  /  Jun 1 2025
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$", s)
    if m:
        mo = _MONTHS.get(m.group(1)[:3].lower())
        if mo:
            return _fmt_date(int(m.group(3)), mo, int(m.group(2)))

    # 1 June 2025
    m = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$", s)
    if m:
        mo = _MONTHS.get(m.group(2)[:3].lower())
        if mo:
            return _fmt_date(int(m.group(3)), mo, int(m.group(1)))

    return None


def _fmt_date(y: int, mo: int, d: int) -> Optional[str]:
    """MM/DD/YYYY for a real calendar date, else None (rejects 02/31 etc.)."""
    try:
        return datetime(y, mo, d).strftime("%m/%d/%Y")
    except ValueError:
        return None


def _normalize_currency(val: str) -> Optional[str]:
    """Coerce a typed amount to "$1,234,567", preserving any trailing
    qualifier, or None if no amount can be read.

    Trailing text is deliberately KEPT: `business_income_limit` is documented
    to the client as "$20,000 per month", so dropping "per month" would lose
    real meaning. Only the numeric part is reformatted.

    Per the agreed decision the STORED value stays formatted display text -
    exactly what lands on the ACORD PDF today - so PDF output is unchanged.
    """
    s = (val or "").strip()
    if not s:
        return None

    m = re.match(r"^\$?\s*([\d,]*\.?\d+)\s*([kKmM])?\b(.*)$", s)
    if not m:
        return None

    try:
        amount = float(m.group(1).replace(",", ""))
    except ValueError:
        return None

    suffix = (m.group(2) or "").lower()
    if suffix == "k":
        amount *= 1_000
    elif suffix == "m":
        amount *= 1_000_000

    rest = (m.group(3) or "").strip(" ,;")
    # A trailing token that is itself a number ("1,000,000 / 2,000,000") means
    # this is a compound answer, not one amount - leave it completely alone.
    if rest and re.match(r"^[/\-]?\s*\$?[\d,]", rest):
        return None

    body = f"${amount:,.2f}".replace(".00", "") if amount % 1 else f"${int(amount):,}"
    return f"{body} {rest}".strip() if rest else body


def _normalize_code(val: str, field_name: str) -> Tuple[Optional[str], bool]:
    """Coerce an industry / tax code to digits.

    Returns `(normalized_or_original, ok)`. `ok` is False when the digit count
    does not match the expected width - the value is still KEPT (never
    discarded), just flagged so the producer can confirm it.
    """
    s = (val or "").strip()
    if not s:
        return None, True

    digits = re.sub(r"\D", "", s)
    if not digits:
        return s, False

    expected = _CODE_DIGITS.get(field_name)
    for key, width in _CODE_DIGITS.items():
        if expected is None and key in field_name.lower():
            expected = width
            break

    if expected is not None and len(digits) != expected:
        return s, False

    # FEIN is conventionally written XX-XXXXXXX on ACORD forms.
    if expected == 9:
        return f"{digits[:2]}-{digits[2:]}", True
    return digits, True


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

_FIELD_QUESTION_MAP = {
    # Business basics
    "applicant_name":           "What is the full legal name of your business?",
    "dba_name":                 "Does your business go by a different name than its legal name? If yes, what is it?",
    "mailing_address":          "What is your business mailing address? (Street, City, State, ZIP)",
    "physical_address":         "Where is your business physically located? (Leave blank if same as mailing address)",
    "contact_name":             "Who is the main person we should contact about this insurance application?",
    "contact_phone":            "What is the best phone number to reach you?",
    "contact_email":            "What email address should we use to contact you?",
    "fein":                     "What is your business's federal tax ID number? (This is the 9-digit number the IRS assigned to your business, also called an EIN)",
    "entity_type":              "How is your business legally set up? (For example: LLC, Corporation, Sole Proprietor, Partnership)",
    "effective_date":           "What date would you like your insurance coverage to start? (MM/DD/YYYY)",
    "expiration_date":          "What date would you like your insurance coverage to end? (MM/DD/YYYY)",
    "policy_number":            "Do you have a current or previous insurance policy number? If yes, please share it.",
    "lines_of_business":        "What types of insurance coverage are you looking for? (For example: General Liability, Property, Auto, Workers Comp)",
    "total_revenue":            "What is your business's total annual income or sales?",
    "total_payroll":            "What is the total amount you pay your employees each year (gross payroll)?",
    "num_employees":            "How many people does your business employ?",
    "operations_description":   "In a few sentences, what does your business do? What products or services do you offer?",
    "prior_carrier":            "Who provided your business insurance most recently? (If none, write 'None')",
    "naics_code":               "Do you know your business's industry classification code (NAICS code)? If yes, please share it. (If unsure, leave blank)",
    "sic_code":                 "Do you know your business's SIC code (an older industry classification number)? If yes, please share it. (If unsure, leave blank)",
    "years_in_business":        "How many years has your business been open?",
    # General Liability
    "gl_limits":                "How much liability coverage are you looking for? (For example: $1,000,000 per incident / $2,000,000 total)",
    "gl_each_occurrence":       "What is the maximum amount you want covered for a single incident or accident?",
    "gl_aggregate":             "What is the total maximum amount you want covered across all claims in a year?",
    "gl_deductible":            "How much would you be willing to pay out of pocket before insurance kicks in (your deductible)?",
    "gl_class_codes":           "Please describe your business operations in detail. What specific services or products do you provide? What percentage of your work is residential vs commercial?",
    "retro_date":               "Has your current insurance policy been continuously active since a specific start date? If yes, what was that original start date?",
    "additional_insured":       "Is there anyone else — such as a landlord, client, or partner — who needs to be listed on your policy? If yes, please provide their name(s).",
    # Property
    "property_building_value":  "If your building had to be completely rebuilt from scratch today, what would it cost? (Estimated rebuild value)",
    "property_bpp_value":       "What is the total value of your business equipment, furniture, inventory, and other contents inside the building?",
    "construction_type":        "What is your building mainly made of? (For example: wood frame, brick, concrete, steel)",
    "occupancy_type":           "What is your building used for on a day-to-day basis?",
    "year_built":               "What year was your building originally built?",
    "roof_year":                "What year was the roof last replaced or repaired?",
    "sprinkler_system":         "Does your building have a fire sprinkler system installed?",
    "fire_protection_class":    "How close is your building to a fire station or fire hydrant? (Your agent may help determine this — share what you know)",
    "valuation_method":         "If there is a loss, how would you like your property valued? Choose one: Full rebuild cost (Replacement Cost) or Current depreciated value (Actual Cash Value)",
    "coinsurance_percentage":   "Does your insurance require you to insure your property for a minimum percentage of its value? If yes, what percentage? (Your agent can clarify if needed)",
    "business_income_limit":    "If your business had to close temporarily due to a covered loss, how much income would you need covered per month?",
    "period_of_restoration":    "If your business had to shut down due to damage, how many months do you estimate it would take to reopen?",
    "property_deductible_aop":  "How much would you pay out of pocket for most property claims before insurance covers the rest?",
    "property_deductible_wind": "How much would you pay out of pocket for wind or hail damage claims?",
    "mortgagee_name":           "Does a bank or lender have a financial interest in your building (for example, a mortgage)? If yes, what is their name and address?",
    # Commercial Auto
    "auto_liability_limit":     "How much liability coverage are you looking for on your business vehicles?",
    "auto_deductible_comp":     "How much would you pay out of pocket for non-collision vehicle damage (such as theft, weather, or vandalism)?",
    "auto_deductible_collision": "How much would you pay out of pocket if one of your business vehicles is in a collision?",
    # Workers Compensation
    "wc_payroll":               "What is the total annual payroll for employees covered under Workers Compensation?",
    "wc_class_codes":           "What types of work do your employees perform? (Describe their job duties — your agent will assign the appropriate codes)",
    "wc_xmod":                  "Has your business received a workers compensation safety rating or modifier from your previous insurer? If yes, what is the number?",
    "wc_officer_exclusions":    "Are there any business owners or officers who should NOT be covered under Workers Compensation? If yes, list their names.",
    # Umbrella / Excess
    "umbrella_limit":           "How much additional liability coverage would you like on top of your other policies? (For example: $1,000,000 or $5,000,000 extra)",
    "umbrella_sir":             "For this extra liability coverage, how much would you be willing to cover yourself before it kicks in?",
    "schedule_of_underlying_insurance": "Is a Schedule of Underlying Insurance included with this submission (the list of the underlying GL / Auto / Employers Liability policies your umbrella sits over)?",
    "umbrella_follow_form":     "Do the submitted documents explicitly state the umbrella follows form over the underlying coverages? Leave blank if it is not explicitly stated.",
    # Miscellaneous
    "percent_subcontracted":    "What percentage of your total work is done by outside contractors rather than your own employees?",
    # Subcontractor usage broken out by class code (client example) - captured as a
    # free-text remark alongside the single overall percentage above.
    "subcontractor_pct_by_class_code": "If you use subcontractors, what percentage of work is subcontracted for each type of work (class code)? For example: 'Roofing - 40%; Framing - 20%'.",
    # Vehicle garaging / return-to-yard (client example) - context for the auto rater.
    "vehicles_return_to_premises": "At the end of the workday, do your vehicles return to your place of business or yard, or are they kept somewhere else? Please describe.",
    "num_claims":               "How many insurance claims has your business filed in the last 3 to 5 years?",
    "loss_history_years":       "How many years of past insurance claims history are you able to provide?",
    # §6.4: lets the client attest "no prior losses" so the loss-history score can move.
    "loss_history_no_prior_losses_indicator": "To the best of your knowledge, has your business had NO insurance claims or losses in the past 5 years? (Answer 'Yes' to confirm No Known Losses - the industry term for an account with no reported claims.)",
    "certificate_holder":       "Is there a company, landlord, or individual who needs written proof of your insurance? If yes, what is their name and address?",
    # Prior carrier / marketing context (Brent feedback: questionnaire more reliable than document extraction)
    "carrier_marketing_reason": "Why are you marketing this account at this time?",
    # Upcoming deadlines / urgency (Brent feedback: gives the underwriter context and supports readiness)
    "submission_urgency":       "Are there any upcoming deadlines or urgency we should know about?",
    # §6.3 item 2/4: narrative-quality topics with no structured ACORD field.
    # Asked ONLY when the narrative does not already cover the topic.
    "narrative_account_overview": "In a few sentences, give a brief overview of your business - how long you've operated, what you do, and anything that helps an underwriter understand your account.",
    "narrative_management":       "Tell us about the owners and management team - their experience, years in the trade, and relevant background.",
    "narrative_risk_controls":    "What safety or risk-control measures does your business have in place? (For example: written safety program, employee training, inspections, drug testing, maintenance program)",
    "narrative_growth_trends":    "Provide your WC payroll breakdown by class code - list each class code, its description, and the associated payroll amount. (For example: 5183 Plumbing - $320,000; 5190 Electrical - $180,000)",
    "narrative_target_markets":   "What is your workers comp experience modifier (EMOD / XMOD)? Provide the current mod value, the rating bureau, and any relevant context about losses or safety programs that affect it.",
}


_FIELD_HINT_MAP = {
    "applicant_name":           "Enter your company's full registered legal name, e.g. 'Acme Construction LLC'.",
    "dba_name":                 "If your business operates under a trade name different from its legal name, enter it here, e.g. 'Acme Builders'.",
    "mailing_address":          "Enter the address where your business receives mail, e.g. '123 Main St, Austin, TX 78701'.",
    "physical_address":         "Enter the street address where your business actually operates. Leave blank if it's the same as your mailing address.",
    "contact_name":             "Enter the full name of the person handling this insurance application, e.g. 'Jane Smith'.",
    "contact_phone":            "Enter a direct phone number including area code, e.g. '(512) 555-1234'.",
    "contact_email":            "Enter the email address your agent should use to reach you, e.g. 'jane@acmecorp.com'.",
    "fein":                     "This is your 9-digit IRS Employer Identification Number — find it on any IRS letter or your prior tax return, e.g. '12-3456789'.",
    "entity_type":              "Choose how your business is legally structured, e.g. 'LLC', 'Corporation', 'Sole Proprietor', or 'Partnership'.",
    "effective_date":           "Enter the date you want coverage to begin in MM/DD/YYYY format, e.g. '06/01/2025'.",
    "expiration_date":          "Enter the date you want coverage to end in MM/DD/YYYY format, e.g. '06/01/2026'.",
    "policy_number":            "Enter just the policy number from your insurance documents, e.g. 'GL-123456'. Write 'None' if you don't have one.",
    "lines_of_business":        "List the types of coverage you need, e.g. 'General Liability, Commercial Property'.",
    "total_revenue":            "Enter your business's total annual sales or income, e.g. '$500,000'. Use your most recent full year.",
    "total_payroll":            "Enter the total gross wages paid to all employees in a year, e.g. '$200,000'. Found on your W-3 or payroll summary.",
    "num_employees":            "Enter the total number of people currently employed, including part-time workers, e.g. '12'.",
    "operations_description":   "Describe what your business does in 2–3 sentences, e.g. 'We install residential roofing and gutters in the Austin metro area'.",
    "prior_carrier":            "Enter the name of your current or most recent insurance company, e.g. 'Hartford' or 'Travelers'. Write 'None' if you've never had coverage.",
    # Fallback wording only. When the uploaded documents describe the business
    # well enough to match a trade, `_attach_classification_suggestions`
    # (Figure 20) replaces this with a hint naming THAT business's likely code.
    # The example below is deliberately labelled as an illustration of the
    # shape, so a bakery is never shown a roofing code as if it were theirs.
    "naics_code":               "This is a 6-digit industry code - leave blank if unsure, your agent can look it up. As an example of the format, a roofing contractor would use something like '238160'.",
    "sic_code":                 "This is a 4-digit older industry code - leave blank if unsure. As an example of the format, a roofing contractor would use something like '1761'.",
    "years_in_business":        "Enter the number of years your business has been operating, e.g. '7'.",
    "gl_limits":                "Enter your desired coverage limits, e.g. '$1,000,000 per occurrence / $2,000,000 aggregate'. Your agent can advise if unsure.",
    "gl_each_occurrence":       "Enter the max payout for a single incident, e.g. '$1,000,000'.",
    "gl_aggregate":             "Enter the total max payout across all claims in a policy year, e.g. '$2,000,000'.",
    "gl_deductible":            "Enter how much you'd pay out of pocket before insurance covers the rest, e.g. '$500' or '$0' for no deductible.",
    "gl_class_codes":           "Describe the type of work your business performs — your agent will assign the classification code, e.g. 'residential painting contractor'.",
    "retro_date":               "If your policy has been active without gaps since a certain date, enter that original start date, e.g. '01/01/2018'. Leave blank if unsure.",
    "additional_insured":       "List any landlords, clients, or partners who need to be named on your policy, e.g. 'City of Austin, 123 City Hall Ave'.",
    "property_building_value":  "Estimate the cost to completely rebuild the building from scratch today (not market value), e.g. '$800,000'.",
    "property_bpp_value":       "Estimate the total value of all equipment, furniture, and inventory inside the building, e.g. '$150,000'.",
    "construction_type":        "Describe the main material your building is made of, e.g. 'Wood Frame', 'Brick', 'Concrete Block', or 'Steel'.",
    "occupancy_type":           "Describe how the building is used day-to-day, e.g. 'Office', 'Retail Store', 'Warehouse', or 'Restaurant'.",
    "year_built":               "Enter the 4-digit year the building was originally constructed, e.g. '1998'.",
    "roof_year":                "Enter the 4-digit year the roof was last replaced or significantly repaired, e.g. '2019'.",
    "sprinkler_system":         "Answer Yes if the building has an active fire sprinkler system installed throughout, No if it does not.",
    "fire_protection_class":    "Enter your building's fire protection class (1–10) if you know it — your agent can help determine this. Lower numbers mean better protection.",
    "valuation_method":         "Choose 'Replacement Cost' to be paid the full rebuild cost, or 'Actual Cash Value' to be paid the depreciated value after a loss.",
    "coinsurance_percentage":   "Enter the minimum insured percentage required by your policy, e.g. '80%'. Your agent can clarify — leave blank if unsure.",
    "business_income_limit":    "Enter how much monthly income you'd need covered if your business had to temporarily close, e.g. '$20,000 per month'.",
    "period_of_restoration":    "Estimate how many months it would take to reopen your business after a major loss, e.g. '6 months'.",
    "property_deductible_aop":  "Enter your deductible for most property claims (All Other Perils), e.g. '$2,500'.",
    "property_deductible_wind": "Enter your deductible specifically for wind or hail damage claims, e.g. '$5,000'.",
    "mortgagee_name":           "If a bank holds a mortgage on the building, enter their full name and address, e.g. 'Wells Fargo Bank NA, PO Box 10335, Des Moines IA 50306'.",
    "auto_liability_limit":     "Enter your desired liability coverage for business vehicles, e.g. '$1,000,000 combined single limit'.",
    "auto_deductible_comp":     "Enter what you'd pay out of pocket for non-collision damage like theft or weather, e.g. '$500'.",
    "auto_deductible_collision": "Enter what you'd pay out of pocket if a business vehicle is in a collision, e.g. '$1,000'.",
    "wc_payroll":               "Enter the total annual wages paid to employees covered under Workers Comp, e.g. '$350,000'. Found on your payroll records.",
    "wc_class_codes":           "Describe your employees' job duties — your agent assigns the codes, e.g. 'office staff, field installers, drivers'.",
    "wc_xmod":                  "Enter your experience modification factor if you have one, e.g. '0.95'. Found on your current WC policy. Leave blank if unknown.",
    "wc_officer_exclusions":    "List any owners or officers who should be excluded from WC coverage by name, e.g. 'John Smith, Jane Doe'. Leave blank if none.",
    "umbrella_limit":           "Enter the additional liability limit you want above your other policies, e.g. '$2,000,000'.",
    "umbrella_sir":             "Enter your self-insured retention (similar to a deductible) for this umbrella policy, e.g. '$10,000'.",
    "schedule_of_underlying_insurance": "Answer 'Yes' if the submission includes a Schedule of Underlying Insurance, or briefly list the underlying policies, e.g. 'GL $1M/$2M, Auto $1M CSL, EL $1M'. Leave blank if not provided.",
    "umbrella_follow_form":     "Enter 'Follows form' only if a document explicitly says so. Coverage is never assumed - leave blank if it is not stated and an underwriter will review.",
    "percent_subcontracted":    "Enter what percentage of your work is performed by subcontractors rather than your own employees, e.g. '30%'.",
    "subcontractor_pct_by_class_code": "For each trade or class code, give the share of that work done by subcontractors, e.g. 'Roofing 5551 - 40%; Framing 5645 - 20%'. Leave blank if you use no subcontractors.",
    "vehicles_return_to_premises": "Tell us where your vehicles are parked overnight, e.g. 'All vehicles return to our main yard at 123 Industrial Rd' or 'Drivers take vehicles home'.",
    "num_claims":               "Enter the total number of insurance claims your business has filed in the past 3–5 years, e.g. '2'. Enter '0' if none.",
    "loss_history_years":       "Enter how many years of claims history you can provide documentation for, e.g. '5'.",
    "loss_history_no_prior_losses_indicator": "Answer 'Yes' only if there have been no insurance claims or losses. If you have had any claims, answer 'No' and provide your loss runs or claim count instead.",
    "certificate_holder":       "Enter the name and address of anyone who needs a certificate of insurance, e.g. 'ABC Property Management, 456 Oak Ave, Dallas TX 75201'.",
    "carrier_marketing_reason": "Select the primary reason for seeking coverage. This helps the underwriter understand the account background and is much more reliable than trying to extract this from documents.",
    "submission_urgency":       "Optional. Note any binding deadline, renewal date, or time-sensitivity, e.g. 'Need to bind by 07/01 for a new job'. Leave blank if none.",
    "narrative_account_overview": "A short summary of your company and its background. Helps the underwriter understand your account at a glance, e.g. 'Family-owned commercial GC operating in Denver since 2009'.",
    "narrative_management":       "Describe who runs the business and their experience, e.g. 'Owner has 20 years in commercial roofing; PM has 12 years on the team'.",
    "narrative_risk_controls":    "List the steps you take to prevent accidents and losses, e.g. 'Written safety program, quarterly training, drug testing, annual equipment inspections'.",
    "narrative_growth_trends":    "List payroll by class code, e.g. '5183 Plumbing $320,000 | 5190 Electrical $180,000 | 8810 Clerical $95,000'.",
    "narrative_target_markets":   "State the mod value and bureau, e.g. 'EMOD 0.88 (NCCI) - credit mod reflecting 3 years clean; no lost-time claims'.",
}

_PREFIX_HINT_MAP = {
    "insurer":          "Enter the full legal name of the insurance company, e.g. 'State Farm Fire and Casualty Company'.",
    "additional party": "Enter the full name and address of the person or company to be listed, e.g. 'City of Austin, 301 W 2nd St, Austin TX 78701'.",
    "location":         "Enter the complete address for this business location, e.g. '789 Commerce Dr, Houston TX 77001'.",
    "vehicle":          "Enter ALL of the following: Year (e.g., 2021), Make (e.g., Ford), Model (e.g., F-150), VIN (17 characters), and primary use (e.g., local deliveries, long-haul, service vehicle).",
    "driver":           "Enter driver's: Full legal name, Driver's license number and state, Date of birth (MM/DD/YYYY), and years of commercial driving experience.",
    "owner":            "Enter this owner's full name, title, and ownership percentage, e.g. 'Jane Doe, President, 60%'.",
    "claim":            "Enter the date, amount, and a brief description of this claim, e.g. '03/15/2022, $8,500, slip and fall at job site'.",
    "item":             "Describe the item including make, model, serial number, and value, e.g. 'DeWalt Table Saw, Model DWE7491RS, Serial 123456, Value $600'.",
}

# ---------------------------------------------------------------------------
# Producer-facing labels (engineering note, Figure 14)
# ---------------------------------------------------------------------------
# "Separate producer-facing rule labels from client-facing wording. The same
# missing field may require different wording depending on who is answering."
#
# `_FIELD_QUESTION_MAP` above is deliberately written FOR THE CLIENT - plain
# language, no jargon. That reads poorly in the producer's send modal, where an
# insurance professional wants the underwriting term and why the field matters.
# This map supplies that short, rule-oriented label; the client wording is never
# changed and never replaced.
#
# Resolution is best-effort: any field with no entry here falls back to the
# client question text, so coverage gaps degrade gracefully instead of blanking
# a row. The label is attached as `producer_label` and is stripped from the
# client payload by the /client-view whitelist, so it can never leak.
_FIELD_PRODUCER_LABEL_MAP = {
    "applicant_name":           "Named Insured - full legal name",
    "dba_name":                 "DBA / trade name",
    "mailing_address":          "Mailing address",
    "physical_address":         "Physical / premises address",
    "contact_name":             "Primary contact - name",
    "contact_phone":            "Primary contact - phone",
    "contact_email":            "Primary contact - email",
    "fein":                     "FEIN / Tax ID",
    "entity_type":              "Legal entity type",
    "effective_date":           "Policy effective date",
    "expiration_date":          "Policy expiration date",
    "policy_number":            "Policy number",
    "lines_of_business":        "Lines of business requested",
    "total_revenue":            "Annual revenue - rating basis",
    "total_payroll":            "Annual gross payroll - rating basis",
    "num_employees":            "Employee count",
    "operations_description":   "Operations description - drives class assignment",
    "prior_carrier":            "Prior / incumbent carrier",
    "naics_code":               "NAICS classification code",
    "sic_code":                 "SIC classification code",
    "years_in_business":        "Years in business",
    "gl_limits":                "GL limits - occurrence / aggregate",
    "gl_each_occurrence":       "GL each-occurrence limit",
    "gl_aggregate":             "GL general aggregate limit",
    "gl_deductible":            "GL deductible",
    "gl_class_codes":           "GL class code basis - operations detail",
    "retro_date":               "Retroactive date - claims-made",
    "additional_insured":       "Additional insured(s)",
    "property_building_value":  "Building limit - replacement cost",
    "property_bpp_value":       "Business personal property limit",
    "construction_type":        "Construction type - COPE",
    "occupancy_type":           "Occupancy - COPE",
    "year_built":               "Year built - COPE",
    "roof_year":                "Roof update year - COPE",
    "sprinkler_system":         "Sprinklered - protection / COPE",
    "fire_protection_class":    "Protection class - COPE",
    "valuation_method":         "Valuation - RC vs ACV",
    "coinsurance_percentage":   "Coinsurance %",
    "business_income_limit":    "Business income limit",
    "period_of_restoration":    "Period of restoration",
    "property_deductible_aop":  "Property deductible - AOP",
    "property_deductible_wind": "Property deductible - wind / hail",
    "mortgagee_name":           "Mortgagee / loss payee",
    "auto_liability_limit":     "Auto liability limit - CSL",
    "auto_deductible_comp":     "Auto comprehensive deductible",
    "auto_deductible_collision": "Auto collision deductible",
    "wc_payroll":               "WC payroll - rating basis",
    "wc_class_codes":           "WC class codes",
    "wc_xmod":                  "Experience mod - EMOD / XMOD",
    "wc_officer_exclusions":    "Officer inclusions / exclusions",
    "umbrella_limit":           "Umbrella limit",
    "umbrella_sir":             "Umbrella SIR",
    "schedule_of_underlying_insurance": "Schedule of underlying insurance",
    "umbrella_follow_form":     "Follow-form confirmation",
    "percent_subcontracted":    "Subcontracted work %",
    "subcontractor_pct_by_class_code": "Subcontracted % by class code",
    "vehicles_return_to_premises": "Vehicle garaging / return-to-yard",
    "num_claims":               "Claim count - last 3-5 years",
    "loss_history_years":       "Loss history years available",
    "loss_history_no_prior_losses_indicator": "No known losses attestation",
    "certificate_holder":       "Certificate holder",
    "carrier_marketing_reason": "Marketing reason - submission context",
    "submission_urgency":       "Submission urgency / deadline",
    "narrative_account_overview": "Narrative - account overview",
    "narrative_management":       "Narrative - management experience",
    "narrative_risk_controls":    "Narrative - risk controls",
    "narrative_growth_trends":    "WC payroll breakdown by class code",
    "narrative_target_markets":   "Experience mod detail - EMOD",
}


def _resolve_producer_label(field_name: str, canonical_key: Optional[str] = None) -> str:
    """Short rule-oriented label for the PRODUCER, or "" to fall back to the
    client wording. Tries the canonical fact key first (raw ACORD field names
    resolve through it), then the raw name, then the instance-stripped base."""
    for key in (canonical_key, field_name):
        if key and key in _FIELD_PRODUCER_LABEL_MAP:
            return _FIELD_PRODUCER_LABEL_MAP[key]
    base = re.sub(r"[_\s]+[a-zA-Z]$", "", field_name or "")
    base = re.sub(r"[_\s]+\d+$", "", base)
    return _FIELD_PRODUCER_LABEL_MAP.get(base, "")


def _attach_producer_labels(questions: List[dict]) -> None:
    """Attach `producer_label` to every question, in place.

    Runs BEFORE the `_canonical_key` cleanup pass so the canonical key is still
    available for resolution. Purely additive - no existing key is modified.
    """
    for q in questions:
        try:
            q["producer_label"] = _resolve_producer_label(
                q.get("field_name", ""), q.get("_canonical_key"),
            )
        except Exception:  # never let labelling break question generation
            q["producer_label"] = ""


def _attach_input_types(questions: List[dict]) -> None:
    """Upgrade `field_type` from plain "text" to a structured type, in place.

    Figure 18 ("structured data types for currency, codes, dates, yes/no, and
    schedules"). Every question-building path used to hard-code
    `"field_type": "text"`, so the renderer never learned that gross payroll is
    money or that an effective date is a date - and the client-side validation
    for those types, which already existed, could never fire.

    ONLY questions still typed "text" are touched, so `checkbox`, `select` and
    `schedule` questions are structurally incapable of being reclassified here.
    Runs alongside `_attach_producer_labels`, i.e. before the `_canonical_key`
    cleanup this resolves against.
    """
    for q in questions:
        try:
            if (q.get("field_type") or "text") != "text":
                continue
            resolved = _resolve_input_type(
                q.get("field_name", ""), q.get("_canonical_key"),
            )
            if resolved != "text":
                q["field_type"] = resolved
                if resolved == "code":
                    _digits = _CODE_DIGITS.get(q.get("_canonical_key") or "") \
                        or _CODE_DIGITS.get(q.get("field_name", ""))
                    if _digits:
                        q["code_digits"] = _digits
        except Exception:  # never let typing break question generation
            continue


def _attach_classification_suggestions(questions: List[dict], facts: dict) -> None:
    """Attach NAICS / SIC candidates and a business-specific hint, in place.

    Figure 20. Two defects this closes:
      1. `_FIELD_HINT_MAP` carried ONE hard-coded roofing example, shown to every
         applicant regardless of trade. The client asked for examples based on
         the detected business.
      2. There was no candidate mechanism at all, so the assistant could only
         ever answer "a NAICS code is..." generically.

    Purely additive and fail-open: a question with no confident match keeps its
    existing hint and gains no `suggestions` key, so the renderer shows exactly
    what it shows today. Nothing here fills an answer - `suggestions` is a list
    the client must tap, and the hint says to confirm with their agent.
    """
    if not questions:
        return
    try:
        from services import naics_suggester
        from services.extraction_service import _fv
    except Exception as ex:  # pragma: no cover - import guard only
        logger.debug(f"classification suggestions unavailable: {ex}")
        return

    targets = [
        q for q in questions
        if (q.get("_canonical_key") or q.get("field_name", "")) in
        (naics_suggester.NAICS_KEYS | naics_suggester.SIC_KEYS)
    ]
    if not targets:
        return

    try:
        business_text = naics_suggester.business_text_from_facts(facts or {}, _fv)
    except Exception as ex:
        logger.debug(f"classification business text unavailable: {ex}")
        return
    if not business_text.strip():
        return

    for q in targets:
        try:
            key = q.get("_canonical_key") or q.get("field_name", "")
            kind = "naics" if key in naics_suggester.NAICS_KEYS else "sic"
            picks = naics_suggester.suggestions_for(kind, business_text)
            if not picks:
                continue
            q["suggestions"] = picks
            new_hint = naics_suggester.hint_for(kind, naics_suggester.suggest(business_text))
            if new_hint:
                q["hint"] = new_hint
        except Exception:  # never let suggestion enrichment break generation
            continue


def _ordinal(n: int) -> str:
    """English ordinal for any n ("1st", "2nd", "11th", "21st", "141st").

    The previous implementation held a literal list for 1-10 and fell back to
    f"{n}th" above that, which produced the "141th vehicle" seen in the client's
    Figure 15 screenshot. Ordinals above 10 are now correct; the 11/12/13
    exception is handled explicitly (11th, not 11st).
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if 11 <= (abs(n) % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(abs(n) % 10, "th")
    return f"{n}{suffix}"

_FIELD_PREFIX_MAP: list[tuple[str, str, str]] = [
    ("insurer_fullname",         "What is the full name of your insurance company?",                        "insurer"),
    ("insurer_name",             "What is the name of your insurance company?",                             "insurer"),
    ("insurer_naic",             "What is your insurance company's NAIC number? (Your agent can look this up if needed)", "insurer"),
    ("insurer_policy",           "What is the policy number for this insurance?",                           "insurer"),
    ("insurer_phone",            "What is the phone number for your insurance company?",                    "insurer"),
    ("insurer_address",          "What is the address of your insurance company?",                          "insurer"),
    ("insurer_",                 "Please provide the details for your insurance company.",                  "insurer"),
    ("additional_insured_name",  "What is the name of the additional person or company to be listed on the policy?", "additional party"),
    ("additional_insured_addr",  "What is the address of the additional person or company to be listed on the policy?", "additional party"),
    ("additional_insured_",      "Please provide the details for the additional party to be listed on your policy.", "additional party"),
    ("additional_interest_name", "What is the name of the additional interested party?",                    "additional party"),
    ("additional_interest_",     "Please provide details for the additional interested party.",              "additional party"),
    ("location_address",         "What is the address of this business location?",                         "location"),
    ("location_city",            "What city is this business location in?",                                 "location"),
    ("location_state",           "What state is this business location in?",                                "location"),
    ("location_zip",             "What is the ZIP code for this business location?",                        "location"),
    ("location_",                "Please provide the complete address for this business location including street address, city, state, and ZIP code. Also specify if this location has any unique risks or operations.", "location"),
    ("vehicle_vin",              "What is the VIN (Vehicle Identification Number) for this vehicle?",       "vehicle"),
    ("vehicle_year",             "What year is this vehicle?",                                              "vehicle"),
    ("vehicle_make",             "What is the make (brand) of this vehicle?",                               "vehicle"),
    ("vehicle_model",            "What is the model of this vehicle?",                                      "vehicle"),
    ("vehicle_",                 "Please provide the following details for this vehicle: Year, Make, Model, VIN (Vehicle Identification Number), and primary use (e.g., delivery, transportation, service).", "vehicle"),
    ("driver_name",              "What is the full name of this driver?",                                   "driver"),
    ("driver_license",           "What is the driver's license number for this driver?",                    "driver"),
    ("driver_dob",               "What is the date of birth for this driver? (MM/DD/YYYY)",                 "driver"),
    ("driver_",                  "Please provide the following details for this driver: Full name, Driver's license number, Date of birth (MM/DD/YYYY), and years of driving experience.", "driver"),
    ("owner_name",               "What is the full name of this owner or officer?",                        "owner"),
    ("owner_title",              "What is the title or role of this owner or officer?",                     "owner"),
    ("owner_ownership",          "What percentage of the business does this person own?",                   "owner"),
    ("owner_",                   "Please provide the details for this owner or officer.",                   "owner"),
    ("claim_date",               "What was the date of this claim or loss? (MM/DD/YYYY)",                  "claim"),
    ("claim_amount",             "What was the total amount paid or reserved for this claim?",              "claim"),
    ("claim_description",        "Briefly describe what happened for this claim.",                          "claim"),
    ("claim_",                   "Please provide the details for this claim.",                              "claim"),
    ("schedule_item",            "Please describe this scheduled item (make, model, value, or serial number).", "item"),
    ("schedule_value",           "What is the value of this scheduled item?",                              "item"),
    ("schedule_",                "Please provide details for this scheduled item.",                        "item"),
]

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
    """Split concatenated insurance terms without adding artificial spaces between letters."""
    token = token.strip().lower()
    if not token:
        return token

    if len(token) < 20 and ' ' not in token and token.isalpha():
        return token

    if token in _SPLIT_CACHE:
        return _SPLIT_CACHE[token]

    original = token
    result_parts = []
    i = 0
    token_len = len(token)

    while i < token_len:
        matched = False
        for word in _INSURANCE_WORDS:
            word_len = len(word)
            if i + word_len <= token_len and token[i:i+word_len] == word:
                result_parts.append(word)
                i += word_len
                matched = True
                break

        if not matched:
            result_parts.append(token[i])
            i += 1

    result = " ".join(result_parts)

    if re.search(r'\b[a-z]\s+[a-z]\s+[a-z]', result):
        result = re.sub(r'([a-z])\s+(?=[a-z])', r'\1', result)

    _SPLIT_CACHE[original] = result
    return result


def _field_name_to_readable(field_name: str) -> str:
    """Convert field name to readable text without trailing characters."""
    name = re.sub(r'[_\s]+[a-zA-Z]$', '', field_name)
    name = re.sub(r'[_\s]+\d+$', '', name)

    tokens = re.split(r'[_\-\s]+', name)

    expanded = []
    for tok in tokens:
        if not tok:
            continue
        tok = re.sub(r'([a-z])([A-Z])', r'\1 \2', tok)
        tok = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', tok)

        for sub in tok.split():
            if len(sub) == 1 and sub.lower() == 'a':
                continue
            result = _split_concatenated(sub)
            if result and result != 'a':
                expanded.append(result)

    readable = " ".join(expanded).strip()
    readable = re.sub(r'\s+', ' ', readable)
    readable = re.sub(r'\s+a$', '', readable)
    readable = re.sub(r'^a\s+', '', readable)

    return readable.lower()


_HUMANIZED_CACHE: dict[str, str] = {}


def _clean_duplicate_words(text: str) -> str:
    """Remove duplicate consecutive words and stray characters."""
    if not text:
        return text

    # Collapse an adjacent repeated PHRASE, longest first, then repeated single
    # words. ACORD field names routinely repeat a section name inside the field
    # name itself - `WorkersCompensationEmployersLiability_EmployersLiability_
    # EachAccidentLimitAmount` humanized to "...employers liability employers
    # liability each accident..." and shipped to the CLIENT that way, because
    # the old loop only compared each word with the one before it and no two
    # ADJACENT words were equal. n=1 reproduces that original behaviour exactly.
    words = text.split()
    for n in (4, 3, 2, 1):
        i = 0
        while i + 2 * n <= len(words):
            first  = [w.lower() for w in words[i:i + n]]
            second = [w.lower() for w in words[i + n:i + 2 * n]]
            if first == second:
                del words[i + n:i + 2 * n]
            else:
                i += 1

    text = ' '.join(words)
    text = re.sub(r'\s+a([\.\?\!]|$)', r'\1', text)
    text = re.sub(r'\b(policy)\s+\1\b', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+([\.\?\!,])', r'\1', text)

    return text


# ASYNC-SAFE
async def _humanize_fields_with_openai(field_names: list[str]) -> dict[str, str]:
    uncached = [f for f in field_names if f not in _HUMANIZED_CACHE]
    if not uncached:
        return {f: _HUMANIZED_CACHE[f] for f in field_names}

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
        _timeout = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
        client = openai.AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            http_client=httpx.AsyncClient(timeout=_timeout),
        )
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1500,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r'^```[a-z]*\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
        parsed: dict = json.loads(raw)

        for i, field_name in enumerate(uncached):
            q = parsed.get(str(i + 1), "").strip()
            if q:
                q = _clean_duplicate_words(q)
                _HUMANIZED_CACHE[field_name] = q
            else:
                _HUMANIZED_CACHE[field_name] = f"Please provide your {readable_map[field_name]}."

    except Exception as ex:
        logger.warning(f"ARQ: OpenAI humanization failed ({ex}), using readable fallback for {len(uncached)} fields")
        for field_name in uncached:
            _HUMANIZED_CACHE[field_name] = f"Please provide your {readable_map[field_name]}."

    return {f: _HUMANIZED_CACHE[f] for f in field_names}


async def _classify_other_reason_adverse(explanation: str) -> bool:
    """LLM yes/no: does this 'Other' free-text explanation indicate an adverse
    carrier action (nonrenewal, cancellation, declination, market exit, or
    carrier-imposed coverage restrictions)?  Falls back to False on any error."""
    if not explanation or len(explanation.strip()) < 3:
        return False
    try:
        _timeout = float(os.getenv("LLM_REQUEST_TIMEOUT", "120"))
        client = openai.AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            http_client=httpx.AsyncClient(timeout=_timeout),
        )
        prompt = (
            "You are an insurance underwriting assistant.\n"
            "A producer selected 'Other' when asked why they are marketing an account "
            "and provided this explanation:\n\n"
            f'"{explanation}"\n\n'
            "Does this explanation indicate an adverse carrier action - such as nonrenewal, "
            "cancellation, declination, market exit, or carrier-imposed coverage restrictions?\n"
            "Reply with exactly one word: YES or NO."
        )
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=5,
        )
        answer = response.choices[0].message.content.strip().upper()
        return answer.startswith("Y")
    except Exception as ex:
        logger.warning(f"ARQ: adverse-reason LLM classification failed ({ex}), defaulting to non-adverse")
        return False


def _resolve_question(field_name: str) -> tuple[str, str | None]:
    q = _FIELD_QUESTION_MAP.get(field_name)
    if q:
        q = _clean_duplicate_words(q)
        return q, None

    base_name = re.sub(r'[_\s]+[a-z]$', '', field_name)
    base_name = re.sub(r'[_\s]+\d+$',   '', base_name)
    q = _FIELD_QUESTION_MAP.get(base_name)
    if q:
        q = _clean_duplicate_words(q)
        return q, None

    for candidate in (field_name, base_name):
        lower = candidate.lower()
        for prefix, question, group_label in _FIELD_PREFIX_MAP:
            if lower.startswith(prefix):
                question = _clean_duplicate_words(question)
                return question, group_label

    if field_name in _HUMANIZED_CACHE:
        question = _HUMANIZED_CACHE[field_name]
        question = _clean_duplicate_words(question)
        return question, None

    readable = _field_name_to_readable(field_name)
    question = f"Please provide your {readable}."
    question = _clean_duplicate_words(question)
    return question, None


def _blocks_submit(field_type: str, field_name: str) -> bool:
    """True when a format error on this field must STOP the submission.

    The client asked that a badly formatted answer never reach an ACORD box -
    "sometime in December" was landing in PROPOSED EXP DATE and rendering
    green, i.e. indistinguishable from a verified answer.

    The hard rule here: only block on a check the CLIENT'S BROWSER also runs.
    Blocking on anything else traps the client in a 422 they cannot see or
    fix, which is far worse than the problem being solved. Two real traps this
    guards against:

      * `_field_format_type` matches "limit"/"value"/"amount" ANYWHERE in a
        name, so a narrative field like `..._LimitDescription` resolves to
        "number" server-side while rendering as a free-text box. Prose in it
        would be rejected forever.
      * The `"indicator" in name` checkbox branch expects Yes/No, but a raw
        ACORD `..._SprinkleredIndicator_A` reaches the client as a TEXT box.

    Both stay advisory - kept, flagged, surfaced to the producer, never
    blocking. `field_type` is taken from the stored question, so this asks
    exactly what the client was shown.
    """
    if (field_type or "") in ("date", "currency", "code", "number"):
        return True
    # Email / phone are validated in the browser by field NAME, using the same
    # regexes as `_field_format_type` (see isEmailField / isPhoneField).
    return _field_format_type(field_name) in ("email", "phone")


def _clean_answer(raw: str, field_name: str) -> Optional[str]:
    """Backwards-compatible wrapper: cleaned value only, review flag dropped."""
    val, _ = _clean_answer_ex(raw, field_name)
    return val


def _clean_answer_ex(raw: str, field_name: str) -> Tuple[Optional[str], str]:
    """Sanitize + NORMALIZE an answer. Returns `(value, review_reason)`.

    `review_reason` is "" when the value is clean or was normalized
    successfully, otherwise a short client-safe explanation.

    Behaviour change (Figure 18): this function previously returned None for
    any value failing a format check, and `submit_arq_answers` then DROPPED
    the field - so a client typing "June 1 2025" into a date question lost the
    answer permanently and was still shown a success screen. Nothing typed by
    a client is discarded any more. We normalize what we can recognise, keep
    the raw text when we cannot, and flag the latter for producer review.
    """
    if raw is None:
        return None, ""
    val = str(raw).strip()

    # Defense in depth: the "I'm not sure" sentinel is split out before this
    # function is reached (see submit_arq_answers). If it ever arrives here it
    # must NEVER be treated as a real answer — returning None keeps it out of
    # `answers`, out of the ACORD stamping path, and out of the score.
    if is_not_sure_value(val):
        return None, ""

    if not val or val.lower() in ("n/a", "na", "?", "unknown", "none", "null", "-", "--", "tbd", "unsure"):
        return None, ""

    val = re.sub(r"<[^>]*>", "", val).strip()

    if "policy_number" in field_name.lower():
        val = re.sub(r"(?i)^policy\s*(number|#|no\.?|num\.?)[\s:]*", "", val).strip()
        val = re.sub(r'\b(policy)\s+\1\b', r'\1', val, flags=re.IGNORECASE)

    if len(val) > 500:
        val = val[:500].strip()

    if not val:
        return None, ""

    fmt        = _field_format_type(field_name)
    input_type = _resolve_input_type(field_name)

    if fmt == "checkbox" or field_name.lower().find("indicator") >= 0:
        yes_values = ("yes", "true", "1", "y", "on", "checked")
        no_values  = ("no", "false", "0", "n", "off", "unchecked")

        if val.lower() in yes_values:
            return "Yes", ""
        elif val.lower() in no_values:
            return "No", ""
        else:
            # Kept, not discarded - a free-text reply to a Yes/No question is
            # still information the producer can act on.
            return val, "Expected Yes or No"

    # Structured types first: these normalize, and only flag when they cannot.
    if input_type == "code":
        normalized, ok = _normalize_code(val, field_name)
        if normalized is None:
            return None, ""
        if ok:
            return normalized, ""
        width = _CODE_DIGITS.get(field_name)
        return normalized, (
            f"Expected a {width}-digit code" if width else "Unrecognized code format"
        )

    if input_type == "currency":
        normalized = _normalize_currency(val)
        if normalized:
            return normalized, ""
        return val, "Could not read this as a dollar amount"

    if fmt == "email":
        if not _VAL_EMAIL_RE.match(val):
            return val, "Does not look like a valid email address"

    elif fmt == "phone":
        normalized = val.replace(" ", "").replace("-", "").replace(".", "").replace("(", "").replace(")", "")
        if not normalized.lstrip("+").isdigit() or len(normalized.lstrip("+")) < 7:
            return val, "Does not look like a valid phone or fax number"

    elif fmt == "date" or input_type == "date":
        if _VAL_DATE_RE.match(val):
            # Already an accepted shape - still canonicalize 2025-06-01 to
            # MM/DD/YYYY so every date reaching an ACORD field looks the same.
            return _normalize_date(val) or val, ""
        normalized = _normalize_date(val)
        if normalized:
            logger.info(f"ARQ answer date normalized: field={field_name} {val!r} -> {normalized!r}")
            return normalized, ""
        return val, "Could not read this as a date"

    elif fmt == "number" or input_type == "number":
        clean_num = val.replace(" ", "").replace(",", "").replace("$", "")
        if not re.match(r"^\d+(\.\d+)?$", clean_num):
            return val, "Expected a number"

    return val, ""


# ---------------------------------------------------------------------------
# ACORD 125 yellow-field guard helpers
# ---------------------------------------------------------------------------

def _is_empty_arq_value(val) -> bool:
    current_val = str(val).strip() if val is not None else ""
    return current_val == "" or current_val in ("null", "None")


def is_acord125_yellow_missing_field(form_data: dict, field_name: str) -> bool:
    """True when an ACORD 125 field is the yellow missing-required state."""
    confidence = form_data.get("confidence", {})
    mapped = form_data.get("field_state") or form_data.get("mapped", {})
    return confidence.get(field_name) == "missing_required" and _is_empty_arq_value(mapped.get(field_name))


def filter_arq_questions_for_session(generated_forms: dict, questions: List[dict]) -> List[dict]:
    """
    Server-side guard for producer-selected ARQ questions.

    ACORD 125 questions may only target yellow missing-required fields. Other
    forms keep their existing behavior unchanged.
    """
    cleaned_questions = []

    for q in questions:
        field_name = q.get("field_name", "")
        form_ids = q.get("form_ids") or []
        if not isinstance(form_ids, list):
            form_ids = []

        if not form_ids:
            forms_text = str(q.get("forms", ""))
            form_ids = [f"ACORD_{m}" for m in re.findall(r"\b(\d{2,3})\b", forms_text)]

        if "ACORD_125" not in form_ids:
            cleaned_questions.append(q)
            continue

        acord125 = generated_forms.get("ACORD_125", {})
        _125_schema = acord125.get("schema", {}) or {}
        _125_conf   = acord125.get("confidence", {}) or {}
        # A coverage-guarantee / canonical client question (e.g. keyed on
        # `applicant_name`) is NOT a raw ACORD-125 schema field, so the yellow
        # missing-required restriction does not apply to it - it is a curated
        # client question that also happens to feed ACORD 125. Only RAW 125 schema
        # fields are held to the yellow-field rule.
        is_raw_125_field = field_name in _125_schema or field_name in _125_conf
        if is_raw_125_field:
            allowed_125 = is_acord125_yellow_missing_field(acord125, field_name)
        else:
            allowed_125 = True
        remaining_form_ids = [
            fid for fid in form_ids
            if fid != "ACORD_125" or allowed_125
        ]

        if not remaining_form_ids:
            continue

        guarded_q = dict(q)
        guarded_q["form_ids"] = remaining_form_ids
        if remaining_form_ids != form_ids:
            form_nums = []
            for fid in remaining_form_ids:
                form_nums.append(str(fid).replace("ACORD_", "").replace("ACORD ", ""))
            guarded_q["forms"] = ", ".join(sorted(set(form_nums)))
        cleaned_questions.append(guarded_q)

    return cleaned_questions


# ---------------------------------------------------------------------------
# Canonical-fact resolution + curation helpers (Beta Report §8 controls)
# ---------------------------------------------------------------------------

_CANON_CACHE: dict = {}
_FIELD_RULES_CACHE: dict = {}


def _canonical_fact_keys() -> set:
    """Union of every canonical fact key the system understands.

    Used to decide whether an ARQ field maps to a real underwriting fact (so it
    can flow into facts + SQS) vs. a raw PDF field with no fact behind it.
    """
    if "keys" not in _CANON_CACHE:
        keys: set = set(_FIELD_QUESTION_MAP.keys())
        try:
            from services.fact_registry import FACT_REGISTRY
            keys |= set(FACT_REGISTRY.keys())
        except Exception:
            pass
        try:
            from services.sqs_service import FORM_FIELD_INVENTORY
            for lst in FORM_FIELD_INVENTORY.values():
                keys |= set(lst)
        except Exception:
            pass
        _CANON_CACHE["keys"] = keys
    return _CANON_CACHE["keys"]


def _acord_field_rules() -> list:
    if "rules" not in _FIELD_RULES_CACHE:
        try:
            from services.pdf_service import _ACORD_FIELD_RULES
            _FIELD_RULES_CACHE["rules"] = _ACORD_FIELD_RULES
        except Exception:
            _FIELD_RULES_CACHE["rules"] = []
    return _FIELD_RULES_CACHE["rules"]


def _canonical_key(field_name: str) -> Optional[str]:
    """Resolve a question's field name to a canonical fact key, or None.

    Handles three cases: (1) the field IS a canonical key, (2) its
    instance-suffix-stripped base is, (3) it is a raw ACORD schema field that
    substring-matches an `_ACORD_FIELD_RULES` mapping. Internal address
    sub-parts (keys starting with "_") are intentionally not resolved.
    """
    if not field_name:
        return None
    canon = _canonical_fact_keys()
    if field_name in canon:
        return field_name
    base = re.sub(r'[_\s]+[a-zA-Z]$', '', field_name)
    base = re.sub(r'[_\s]+\d+$', '', base)
    if base in canon:
        return base
    for pattern, fact_key in _acord_field_rules():
        if fact_key and not str(fact_key).startswith("_") and pattern in field_name:
            return fact_key
    return None


def _is_curated_client_field(field_name: str) -> bool:
    """True when the field resolves to a known plain-language client question."""
    if not field_name:
        return False
    if field_name in _FIELD_QUESTION_MAP:
        return True
    base = re.sub(r'[_\s]+[a-z]$', '', field_name)
    base = re.sub(r'[_\s]+\d+$', '', base)
    if base in _FIELD_QUESTION_MAP:
        return True
    lower, base_lower = field_name.lower(), base.lower()
    if any(lower.startswith(p) or base_lower.startswith(p) for p, _, __ in _FIELD_PREFIX_MAP):
        return True
    return _canonical_key(field_name) is not None


def _present_fact_keys(facts: dict) -> set:
    """Canonical fact keys already filled in the package (for already-provided suppression)."""
    from services.sqs_service import _fact_is_filled
    present = set()
    for k, v in (facts or {}).items():
        if _fact_is_filled(v):
            present.add(k)
    return present


def _merge_form_ids_into_question(questions: List[dict], canon: str, new_form_ids) -> None:
    """Fold additional forms into the existing question for `canon`.

    Each ACORD form names the same underlying fact with a different raw field, so
    the same canonical fact can surface several times. Instead of dropping the
    duplicates, we merge their forms into the first question so its label lists
    every form the single answer satisfies. The answer still reaches all of them
    because apply resolves the canonical fact and restamps it into each form
    (see _restamp_canonical_into_forms).
    """
    for q in questions:
        if q.get("_canonical_key") != canon:
            continue
        merged = set(q.get("form_ids") or []) | set(new_form_ids or [])
        q["form_ids"] = sorted(merged)
        nums = sorted({str(f).replace("ACORD_", "").replace("ACORD ", "") for f in merged})
        q["forms"] = ", ".join(nums)
        return


def _backfill_and_resolve_present(generated: dict, facts: dict) -> Tuple[set, bool]:
    """Close the "known fact, blank box" mapping gap before ARQ generation.

    For every canonical fact already known (filled in `facts`), find the schema
    fields across all generated forms that resolve to it:

      * if at least one such box already carries a value, the fact is genuinely
        present on the form -> add it to the present set (its question is
        suppressed as already-provided);
      * if every such box is blank, attempt a deterministic late-stamp
        (`_deterministic_map` - the same engine Pass 1 used, no LLM) into each
        blank box. If the value lands on at least one box, the fact is now present
        (suppress). If nothing could be stamped, the fact is left OUT of the
        present set so the client is still asked for it;
      * if no schema field on any selected form resolves to the fact, keep prior
        behaviour and treat it as present (there is no box to fill or ask about).

    Late-stamped values are labelled `filled` (document-sourced) - they came from
    the uploaded documents, not the client, so they are NOT labelled `client_arq`
    and are NOT added to client_filled_fields. Only blank boxes are ever written;
    an existing value is never overwritten.

    Returns (present_on_form, changed). `changed` is True when any box was stamped,
    so the caller can persist the updated forms.
    """
    from services.sqs_service import _fact_is_filled
    try:
        from services.pdf_service import _deterministic_map
    except Exception as ex:  # pragma: no cover - defensive
        logger.warning(f"_backfill_and_resolve_present: pdf_service import failed: {ex}")
        _deterministic_map = None

    generated = generated or {}
    facts = facts or {}

    # One pass over every form's schema: canonical fact key -> [(form_id, field)].
    canon_fields: dict = {}
    for fid, form_data in generated.items():
        schema = (form_data or {}).get("schema", {}) or {}
        for sf in schema.keys():
            c = _canonical_key(sf)
            if not c or c.startswith("_"):
                continue
            canon_fields.setdefault(c, []).append((fid, sf))

    present: set = set()
    changed = False

    for canon, value in facts.items():
        if not _fact_is_filled(value):
            continue
        fields = canon_fields.get(canon)
        if not fields:
            present.add(canon)          # no box anywhere - unchanged behaviour
            continue

        has_value = False
        blanks: List[tuple] = []
        for fid, sf in fields:
            fs = generated[fid].get("field_state") or generated[fid].get("mapped", {})
            if str(fs.get(sf) or "").strip() != "":
                has_value = True
            else:
                blanks.append((fid, sf))

        # Best-effort deterministic late-stamp into every blank box for this fact.
        if _deterministic_map is not None:
            for fid, sf in blanks:
                form_data = generated[fid]
                fs = form_data.get("field_state") or form_data.get("mapped", {})
                try:
                    mapped_val = _deterministic_map(sf, facts)
                except Exception:
                    mapped_val = None
                if mapped_val is None or str(mapped_val).strip() == "":
                    continue
                fs[sf] = mapped_val
                form_data["field_state"] = fs
                conf = form_data.get("confidence") or {}
                conf[sf] = "filled"
                form_data["confidence"] = conf
                form_data["_pdf_cache_hash"] = ""
                form_data["pdf_bytes"] = None
                has_value = True
                changed = True

        if has_value:
            present.add(canon)
        # else: no box carries it and none could be stamped -> ask the client.

    # ── Second pass: facts the FORM already answers but `facts` never captured ─
    # The loop above can only ever consider a fact that is present in the
    # extracted `facts` dict. That misses everything the gap-fill (Pass 2) LLM
    # read straight from the document and wrote into the form: gap-fill writes
    # into the form's `field_state`, and never back into `facts`.
    #
    # Live finding (2026-07-20): the document plainly stated "Number of
    # Employees: 41" and the ACORD 125 box showed 41, yet the client was still
    # asked "How many people does your business employ?" - because structured
    # extraction had missed `num_employees`, so the fact was never in `facts`
    # and this function never looked at it. Same cause for SIC / NAICS.
    #
    # So: treat a fact as present whenever a form box that resolves to it
    # actually carries a value, regardless of how it got there. This only ever
    # ADDS to `present` (never un-suppresses), so no question that is currently
    # suppressed can start being asked because of this.
    for canon, fields in canon_fields.items():
        if canon in present:
            continue
        for fid, sf in fields:
            form_data = generated.get(fid) or {}
            fs = form_data.get("field_state") or form_data.get("mapped", {})
            if str(fs.get(sf) or "").strip() != "":
                present.add(canon)
                break

    return present, changed


def _narrative_components_from_facts(
    facts: dict, session_docs: list = None, flags: dict = None
) -> dict:
    """Which §6.3 narrative-quality components the uploaded narrative covers.

    Used so a question the narrative already answers is not re-asked (§6.3 item
    2). Prefers the authoritative LLM component profile detected once during
    extraction and stored on the session flags - it recognises paraphrased
    components the keyword scan misses and is consistent with the narrative score
    and the evidence labels. The keyword scan (full narrative doc body in strict
    mode, unioned with structured remarks/operations) is unioned in / used as the
    fallback when no profile is present. Returns {} when no narrative signal of
    any kind exists.
    """
    try:
        from services.sqs_service import _score_narrative_components, _extract_narrative_doc_text
        from services.sqs_service import narrative_profile_present_map
        from services.extraction_service import _fv, _narrative_remarks_text
    except Exception:
        return {}
    facts = facts or {}
    doc_text  = _extract_narrative_doc_text(session_docs or []).strip()
    remarks   = _narrative_remarks_text(facts).strip()
    ops       = str(_fv(facts, "operations_description") or "").strip()
    _profile  = (flags or {}).get("narrative_profile")
    _prof_present = narrative_profile_present_map(_profile) if _profile else {}
    if not (doc_text or remarks or ops or any(_prof_present.values())):
        return {}
    # Compact curated fields (account_description / acord101_remarks / operations)
    # credit a component on a single clear mention. The noisier full doc body is
    # scanned in strict mode so a stray boilerplate word ("carrier", "operations")
    # cannot wrongly suppress a legitimate client question.
    components = _score_narrative_components(remarks or ops)
    if doc_text:
        _body = _score_narrative_components(doc_text, strict=True)
        components = {k: bool(components.get(k) or _body.get(k)) for k in components}
    # §6.3 robustness: union the meaning-based LLM profile so a paraphrased
    # component the keywords missed still drives suppression / labelling,
    # consistent with sqs_service._calculate_narrative_quality.
    if any(_prof_present.values()):
        components = {k: bool(components.get(k) or _prof_present.get(k)) for k in components}
    # §6.3 item 2: a client narrative-enrichment answer covers its component, so
    # the corresponding question is not re-asked on a later ARQ pass.
    try:
        from services.sqs_service import _narrative_enrichment_present
        _enrich = _narrative_enrichment_present(facts)
        if any(_enrich.values()):
            components = {k: bool(components.get(k) or _enrich.get(k)) for k in components}
    except Exception:
        pass
    return components


# §6.3 item 2/4: ordered Bucket-C narrative topics asked of the client when the
# narrative does not cover them (account overview first, the broker-style pitch).
_NARRATIVE_ENRICHMENT_ORDER = (
    "account_overview", "management", "risk_controls", "growth_trends", "target_markets",
)


def _maybe_inject_narrative_enrichment_questions(
    questions: List[dict], facts: dict, flags: dict, session_docs: list = None
) -> None:
    """Ask the client for each narrative-quality topic the narrative is MISSING
    (§6.3 item 2: "if the narrative answers it, don't send it; if not, ask").

    A topic the narrative already covers is simply not injected. A topic the
    client already answered on a prior pass (its enrichment fact key is filled)
    is also skipped. In-place and additive - never removes existing questions.
    """
    from services.sqs_service import NARRATIVE_ENRICHMENT_FIELDS
    facts = facts or {}
    flags = flags or {}
    components = _narrative_components_from_facts(facts, session_docs=session_docs, flags=flags)
    existing  = {q.get("field_name") for q in questions}
    # WC Payroll/Class Code and EMOD/XMOD questions are only relevant when the
    # submission includes workers compensation coverage.
    _WC_ONLY_COMPS = frozenset({"growth_trends", "target_markets"})
    has_wc = bool(flags.get("has_workers_comp"))
    for comp in _NARRATIVE_ENRICHMENT_ORDER:
        if comp in _WC_ONLY_COMPS and not has_wc:
            continue
        field_key = NARRATIVE_ENRICHMENT_FIELDS.get(comp)
        if not field_key or field_key in existing:
            continue
        # Narrative already covers this topic → do not ask (client requirement #2).
        if components.get(comp):
            continue
        # Already answered/present in facts → do not re-ask.
        _v = facts.get(field_key)
        if isinstance(_v, dict):
            _v = _v.get("value")
        if _v not in (None, "", "null", "none"):
            continue
        questions.append({
            "field_name":         field_key,
            "question":           _FIELD_QUESTION_MAP[field_key],
            "hint":               _FIELD_HINT_MAP.get(field_key, ""),
            "forms":              "",
            "form_ids":           [],
            "field_type":         "text",
            "current_value":      "",
            "_group_label":       None,
            "_is_curated_client": True,
            "_canonical_key":     field_key,
        })


# §6.4: the curated "no prior losses" attestation field.
NO_LOSS_INDICATOR_FIELD = "loss_history_no_prior_losses_indicator"


def _maybe_inject_no_loss_question(questions: List[dict], facts: dict, flags: dict) -> None:
    """Append a curated 'no prior losses' confirmation when loss history is
    otherwise unestablished, so the client can attest and lift the P4 score
    (Beta Report §6.4 — the reported "score didn't move" bug). In-place, additive.
    """
    from services.sqs_service import _attested_true
    facts = facts or {}
    flags = flags or {}

    def _val(key):
        v = facts.get(key)
        if isinstance(v, dict):
            v = v.get("value")
        return v

    # Already attested, quantified, or evidenced → nothing to ask.
    if _attested_true(_val("no_prior_losses")) or _attested_true(_val(NO_LOSS_INDICATOR_FIELD)):
        return
    if flags.get("no_prior_losses") or flags.get("narrative_states_no_losses"):
        return
    _yrs = _val("loss_history_years")
    _clm = _val("num_claims")
    if _yrs not in (None, "", "0", 0) or _clm not in (None, "", "0", 0):
        return
    if any(q.get("field_name") == NO_LOSS_INDICATOR_FIELD for q in questions):
        return

    questions.append({
        "field_name":         NO_LOSS_INDICATOR_FIELD,
        "question":           _FIELD_QUESTION_MAP[NO_LOSS_INDICATOR_FIELD],
        "hint":               _FIELD_HINT_MAP.get(NO_LOSS_INDICATOR_FIELD, ""),
        "forms":              "",
        "form_ids":           [],
        "field_type":         "checkbox",
        "current_value":      "",
        "_group_label":       None,
        "_is_curated_client": True,
        "_canonical_key":     NO_LOSS_INDICATOR_FIELD,
    })


# §6.4 item 1: the conflict-resolution prompt reuses the existing ACORD-101
# "additional remarks" free-text field (its registry question already names
# "conflict resolution"), so no new question type or answer plumbing is added -
# the client's explanation flows through the same apply path, is labelled
# client-provided, and lands on ACORD 101.
LOSS_CONFLICT_FIELD = "additional_remarks_text"

_LOSS_CONFLICT_QUESTION = (
    "Your submission indicates No Known Losses, but the uploaded loss runs show "
    "one or more claims. Please explain the discrepancy - for example, the loss "
    "runs may belong to a related entity, cover a different period, or those "
    "claims may now be closed."
)


def _maybe_inject_loss_conflict_question(questions: List[dict], facts: dict, flags: dict) -> None:
    """Append a conflict-resolution prompt when a no-loss attestation is
    contradicted by actual loss-run claims (§6.4 item 1). In-place and additive.

    Lets the client explain the discrepancy for the underwriter; it does NOT
    auto-clear the data conflict (the score stays capped until the underlying
    loss data is reconciled). Tagged as a conflict so it surfaces like other
    cross-form conflicts rather than as an optional remark.
    """
    from services.sqs_service import _loss_history_conflict
    facts = facts or {}
    flags = flags or {}

    if not _loss_history_conflict(facts, flags):
        return
    # Don't re-ask if the remarks field is already queued or already answered.
    if any(q.get("field_name") == LOSS_CONFLICT_FIELD for q in questions):
        return
    _existing = facts.get(LOSS_CONFLICT_FIELD)
    if isinstance(_existing, dict):
        _existing = _existing.get("value")
    if _existing not in (None, "", []):
        return

    questions.append({
        "field_name":         LOSS_CONFLICT_FIELD,
        "question":           _LOSS_CONFLICT_QUESTION,
        "hint":               _FIELD_HINT_MAP.get(LOSS_CONFLICT_FIELD)
                              or "Briefly explain the loss-history discrepancy for the underwriter.",
        "forms":              "",
        "form_ids":           [],
        "field_type":         "text",
        "current_value":      "",
        # Route through the cross-form-conflict classification so it is surfaced
        # to the client (AUDIENCE_CLIENT / important) instead of an optional remark.
        "source":             "cross_form_conflict",
        "conflict_code":      "loss_history_conflict",
        "severity":           "soft_warning",
        "_group_label":       None,
        "_is_curated_client": True,
        "_canonical_key":     LOSS_CONFLICT_FIELD,
    })


# Prior carrier marketing reason (Brent feedback: ask via questionnaire, not document extraction)
CARRIER_MARKETING_FIELD = "carrier_marketing_reason"

_CARRIER_MARKETING_OPTIONS = [
    "Shopping for better pricing",
    "Seeking broader coverage",
    "Voluntary carrier change",
    "Broker change",
    "Carrier nonrenewal",
    "Carrier cancellation",
    "Carrier declined renewal",
    "Carrier exited market",
    "Coverage restrictions imposed by carrier",
    "Coverage concerns",
    "New venture",
    "Other",
]

# Options that indicate a meaningful underwriting concern and should escalate ACORD 101
# (client DOUBTS-Workstream4 "Trigger ACORD 101" list - includes carrier-imposed
# coverage restrictions alongside nonrenewal / cancellation / declination / exit).
_ADVERSE_CARRIER_REASONS = frozenset({
    "carrier nonrenewal",
    "carrier cancellation",
    "carrier declined renewal",
    "carrier exited market",
    "coverage restrictions imposed by carrier",
    "coverage concerns",
})


def _maybe_inject_carrier_marketing_question(questions: List[dict], facts: dict, flags: dict) -> None:
    """Inject the 'Why are you marketing this account?' question when not already answered.

    Per Brent's feedback: the reason for leaving a carrier rarely appears in uploaded
    documents. A targeted questionnaire question is more reliable than document extraction
    and takes the client 15 seconds to answer. Inject whenever prior_carrier is known
    OR the submission has any active coverage line (nearly all commercial submissions).
    """
    facts = facts or {}
    flags = flags or {}

    def _val(key):
        v = facts.get(key)
        if isinstance(v, dict):
            v = v.get("value")
        return v

    # Already answered — nothing to ask
    if _val(CARRIER_MARKETING_FIELD):
        return
    # Already queued
    if any(q.get("field_name") == CARRIER_MARKETING_FIELD for q in questions):
        return
    # Only relevant when there is an active submission (prior carrier OR any coverage line)
    _has_coverage = any(flags.get(k) for k in (
        "has_general_liability", "has_auto_coverage", "has_property_coverage",
        "has_workers_comp", "has_umbrella",
    ))
    if not _val("prior_carrier") and not _has_coverage:
        return

    questions.append({
        "field_name":         CARRIER_MARKETING_FIELD,
        "question":           _FIELD_QUESTION_MAP[CARRIER_MARKETING_FIELD],
        "hint":               _FIELD_HINT_MAP.get(CARRIER_MARKETING_FIELD, ""),
        "forms":              "",
        "form_ids":           [],
        "field_type":         "select",
        "options":            list(_CARRIER_MARKETING_OPTIONS),
        "current_value":      "",
        "_group_label":       None,
        "_is_curated_client": True,
        "_canonical_key":     CARRIER_MARKETING_FIELD,
    })


# Upcoming deadlines / urgency (Brent feedback: a targeted questionnaire question
# gives the underwriter context and supports Submission Readiness). Free-text,
# optional - captured as context and credited as a small narrative-quality nudge.
SUBMISSION_URGENCY_FIELD = "submission_urgency"


def _maybe_inject_urgency_question(questions: List[dict], facts: dict, flags: dict) -> None:
    """Inject the 'Any upcoming deadlines or urgency?' question when not already
    answered. Same gate as the marketing question (active submission), in-place,
    additive. Optional context - never a hard stop.
    """
    facts = facts or {}
    flags = flags or {}

    def _val(key):
        v = facts.get(key)
        if isinstance(v, dict):
            v = v.get("value")
        return v

    if _val(SUBMISSION_URGENCY_FIELD):
        return
    if any(q.get("field_name") == SUBMISSION_URGENCY_FIELD for q in questions):
        return
    _has_coverage = any(flags.get(k) for k in (
        "has_general_liability", "has_auto_coverage", "has_property_coverage",
        "has_workers_comp", "has_umbrella",
    ))
    if not _val("prior_carrier") and not _has_coverage:
        return

    questions.append({
        "field_name":         SUBMISSION_URGENCY_FIELD,
        "question":           _FIELD_QUESTION_MAP[SUBMISSION_URGENCY_FIELD],
        "hint":               _FIELD_HINT_MAP.get(SUBMISSION_URGENCY_FIELD, ""),
        "forms":              "",
        "form_ids":           [],
        "field_type":         "text",
        "current_value":      "",
        "_group_label":       None,
        "_is_curated_client": True,
        "_canonical_key":     SUBMISSION_URGENCY_FIELD,
    })


# Umbrella underlying-schedule + follow-form evidence (Brent / DOUBTS-Workstream3
# Q4 + "No Schedule of Underlying Insurance -15"). These rarely extract cleanly
# from documents, so when an umbrella IS present and the evidence is still absent
# we ask the producer directly - the same fallback pattern as the marketing /
# urgency questions. Follow-form is Option B: only confirmed when explicitly
# stated, never inferred. Asked ONLY when has_umbrella is true and the field is
# unanswered, so non-umbrella submissions and already-evidenced umbrellas are
# untouched.
_UMBRELLA_EVIDENCE_FIELDS = (
    "schedule_of_underlying_insurance",
    "umbrella_follow_form",
)

# Follow-form is Option B (explicit-only). The affirmative option text deliberately
# contains "follows form" so the Umbrella Adequacy scorer's phrase detection credits
# it; the negative option carries no follow-form phrase, so the -10 stands and an
# underwriter review is recommended. Coverage is never inferred from a blank.
_FOLLOW_FORM_OPTIONS = [
    "Follows form - explicitly stated in the submitted documents",
    "Not stated - underwriter review recommended",
]


def _maybe_inject_umbrella_evidence_questions(questions: List[dict], facts: dict, flags: dict) -> None:
    facts = facts or {}
    flags = flags or {}
    if not flags.get("has_umbrella"):
        return

    def _val(key):
        v = facts.get(key)
        if isinstance(v, dict):
            v = v.get("value")
        return v

    for field_name in _UMBRELLA_EVIDENCE_FIELDS:
        if _val(field_name):
            continue
        if any(q.get("field_name") == field_name for q in questions):
            continue
        _q = {
            "field_name":         field_name,
            "question":           _FIELD_QUESTION_MAP[field_name],
            "hint":               _FIELD_HINT_MAP.get(field_name, ""),
            "forms":              "ACORD 131",
            "form_ids":           ["ACORD_131"],
            "field_type":         "text",
            "current_value":      "",
            "_group_label":       "Umbrella",
            "_is_curated_client": True,
            "_canonical_key":     field_name,
        }
        if field_name == "umbrella_follow_form":
            _q["field_type"] = "select"
            _q["options"]    = list(_FOLLOW_FORM_OPTIONS)
        questions.append(_q)


# Client examples (2026-07): two curated client questions that previously had no
# field. Both are OPTIONAL client questions (shown in the Client panel, not
# pre-selected) and both become canonical facts via _canonical_fact_keys(), so an
# answer flows into `facts` and is captured for the underwriter even when no ACORD
# box maps to it (the "single % + remarks" / "context" capture the client chose).
SUBCONTRACTOR_BY_CLASS_FIELD = "subcontractor_pct_by_class_code"
VEHICLES_RETURN_FIELD        = "vehicles_return_to_premises"


def _maybe_inject_generic_client_questions(questions: List[dict], facts: dict, flags: dict) -> None:
    """Add the client-example questions that lacked a curated field (subcontractor
    % per class code; vehicles return to yard). Additive, in-place, and gated on
    the relevant coverage so non-contractor / non-auto submissions are untouched.
    """
    facts = facts or {}
    flags = flags or {}

    def _val(key):
        v = facts.get(key)
        if isinstance(v, dict):
            v = v.get("value")
        return v

    existing = {q.get("field_name") for q in questions}

    def _append(field_name):
        questions.append({
            "field_name":         field_name,
            "question":           _FIELD_QUESTION_MAP[field_name],
            "hint":               _FIELD_HINT_MAP.get(field_name, ""),
            "forms":              "",
            "form_ids":           [],
            "field_type":         "text",
            "current_value":      "",
            "_group_label":       None,
            "_is_curated_client": True,
            "_canonical_key":     field_name,
        })

    # Subcontractor % per class code — relevant where there is GL exposure (the
    # line where subcontractor use matters). Optional; producer can add it.
    if (flags.get("has_general_liability")
            and SUBCONTRACTOR_BY_CLASS_FIELD not in existing
            and not _val(SUBCONTRACTOR_BY_CLASS_FIELD)):
        _append(SUBCONTRACTOR_BY_CLASS_FIELD)

    # Vehicles return to premises / yard — relevant when auto coverage is present.
    if (flags.get("has_auto_coverage")
            and VEHICLES_RETURN_FIELD not in existing
            and not _val(VEHICLES_RETURN_FIELD)):
        _append(VEHICLES_RETURN_FIELD)


# ---------------------------------------------------------------------------
# Bulk schedule capture (Beta Report Figure 15)
# ---------------------------------------------------------------------------

def _schedule_key_for_question_field(field_name: str) -> Optional[str]:
    """Which bulk schedule (if any) a missing field belongs to.

    Two detection paths, because questions arrive from two generators:
      1. a raw repeating ACORD schema field (`Vehicle_Year_B`), resolved through
         `pdf_service._SCHEDULE_REGISTRY` so detection can never drift from the
         stamping logic;
      2. a curated `_FIELD_PREFIX_MAP` group (`vehicle_*`, `driver_*`, ...),
         which is what produced the ordinal-labelled cards in the report.

    Returns None for anything not schedule-backed, so non-schedule questions are
    completely unaffected.
    """
    if not ENABLE_SCHEDULE_CAPTURE or not field_name:
        return None
    list_key = schedule_capture.schedule_list_key_for_field(field_name)
    if list_key:
        return list_key
    _, group_label = _resolve_question(field_name)
    if group_label:
        candidate = schedule_capture.GROUP_LABEL_TO_LIST_KEY.get(group_label)
        # Only claim the field when a capture table actually exists for it.
        # Without this guard a group mapped to a schedule with no definition
        # would be removed from `missing_fields` and then skipped by
        # `_build_schedule_questions`, silently losing the question entirely.
        if candidate and schedule_capture.get_def(candidate) is not None:
            return candidate
    return None


def _partition_schedule_fields(missing_fields: dict, field_current_values: dict) -> dict:
    """Remove schedule-backed fields from `missing_fields`, in place.

    Returns {list_key: set(form_ids)} for the schedules that had at least one
    missing field, so the caller can emit exactly ONE question per schedule.
    """
    schedule_forms: dict = {}
    if not ENABLE_SCHEDULE_CAPTURE:
        return schedule_forms
    for field_name in list(missing_fields.keys()):
        list_key = _schedule_key_for_question_field(field_name)
        if not list_key:
            continue
        schedule_forms.setdefault(list_key, set()).update(missing_fields[field_name])
        del missing_fields[field_name]
        field_current_values.pop(field_name, None)
    return schedule_forms


def _build_schedule_questions(schedule_forms: dict, facts: dict) -> List[dict]:
    """One table-style question per schedule, pre-loaded with known rows.

    `current_rows` carries whatever extraction (or a producer pre-load) already
    established, so the client edits/completes a partially-known fleet instead of
    re-typing it. The column spec travels with the question so the questionnaire
    renderer stays generic across all schedule types.
    """
    out: List[dict] = []
    for list_key, form_ids in sorted(schedule_forms.items()):
        defn = schedule_capture.get_def(list_key)
        if defn is None:
            continue
        rows, _report = schedule_capture.validate_rows(
            list_key, schedule_capture.rows_from_facts(list_key, facts),
        )
        nums = sorted({
            str(f).replace("ACORD_", "").replace("ACORD ", "") for f in form_ids
        })
        out.append({
            "field_name":        schedule_capture.answer_key(list_key),
            "question":          schedule_capture.question_text(list_key),
            "hint":              schedule_capture.hint_text(list_key),
            "forms":             ", ".join(nums),
            "form_ids":          sorted(form_ids),
            "field_type":        "schedule",
            "current_value":     "",
            # Schedule-specific payload consumed by the ScheduleTable renderer.
            "schedule_key":      list_key,
            "schedule_label":    defn["label"],
            "schedule_singular": defn["singular"],
            "columns":           defn["columns"],
            "dedup_keys":        defn["dedup_keys"],
            "vin_decode":        bool(defn["vin_decode"]),
            "row_capacity":      schedule_capture.ROW_CAPACITY,
            "current_rows":      rows,
            "_group_label":       None,
            "_is_curated_client": True,
            "_canonical_key":     list_key,
        })
    return out


def _finalize_schedule_taxonomy(questions: List[dict]) -> None:
    """Give schedule questions their taxonomy explicitly, after decoration.

    `decorate_questions` judges a question by its field name / canonical key,
    which for a synthetic `schedule::<key>` question would be guesswork. Two
    behaviours specifically must not apply to a schedule:

      * "already provided" suppression - a fleet where extraction found 5 of 143
        vehicles is exactly when the client most needs the table, so a
        partially-populated schedule must stay askable;
      * accidental routing to the internal/producer panel via a substring match
        on the synthetic key.

    Schedules are Client + important, so they are surfaced and suggested but not
    force-selected into the default send set.
    """
    for q in questions:
        if q.get("field_type") != "schedule":
            continue
        q["audience"]          = AUDIENCE_CLIENT
        q["bucket"]            = BUCKET_CLIENT
        q["bucket_label"]      = "Client"
        q["priority"]          = PRIORITY_IMPORTANT
        q["suppressed"]        = False
        q["suppressed_reason"] = ""


# ---------------------------------------------------------------------------
# Question generation
# ---------------------------------------------------------------------------

# ASYNC-SAFE
async def generate_arq_questions(
    facts: dict,
    flags: dict,
    generated_forms: dict,
    hard_stops: list,
    soft_stops: list,
    session_docs: list = None,
    present_fact_keys: Optional[set] = None,
    stats: Optional[dict] = None,
) -> List[dict]:
    # `present_fact_keys`, when supplied by the caller, is the form-aware set of
    # facts to treat as already-provided (a fact counts as present only when it
    # actually landed on a form box - see _backfill_and_resolve_present). When not
    # supplied we fall back to the facts-only view for backward compatibility.
    # `stats`, when supplied, is an out-param the caller reads for the ARQ metric
    # "Duplicate / Merged Questions Removed" (stats["merged_removed"]).
    facts = facts or {}
    missing_fields: dict = {}
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
            is_empty    = _is_empty_arq_value(raw_val)

            if form_id == "ACORD_125":
                if conf_val != "missing_required" or not is_empty:
                    continue
            else:
                if conf_val == "missing_required":
                    pass
                elif conf_val == "low_confidence" and is_empty:
                    pass
                elif conf_val == "low_confidence" and not is_empty:
                    continue
                elif conf_val == "filled" and is_empty:
                    pass
                elif conf_val == "filled" and not is_empty:
                    continue
                else:
                    continue

            if field_name not in missing_fields:
                missing_fields[field_name] = set()
                field_current_values[field_name] = current_val
            missing_fields[field_name].add(form_id)

    has_non_acord125_forms = any(fid != "ACORD_125" for fid in generated_forms)
    if has_non_acord125_forms:
        tier1_fact_keys = ["applicant_name", "producer_name", "mailing_address", "effective_date",
                           "contact_name", "contact_phone", "contact_email", "lines_of_business"]
        for fk in tier1_fact_keys:
            if not facts.get(fk):
                if fk not in missing_fields:
                    missing_fields[fk] = set()
                    field_current_values[fk] = ""

    # Figure 15: pull repeating-row fields OUT of the per-field flow so they are
    # answered as ONE table per schedule. Done before the humanization pass below
    # so we never spend an LLM call rewriting a field that is about to collapse.
    schedule_forms = _partition_schedule_fields(missing_fields, field_current_values)

    questions = []
    seen_field_names = set()
    seen_canon_keys = set()   # deduplicate row-indexed variants by canonical fact
    group_counts: dict[str, int] = {}

    llm_needed = []
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
        # A raw field that resolves to a curated canonical fact reuses that fact's
        # plain-language question text, so it needs no humanization call.
        _canon = _canonical_key(field_name)
        if _canon and _canon in _FIELD_QUESTION_MAP:
            continue
        # Only spend an LLM humanization call on fields that will actually reach
        # the client. Raw/internal form fields get the no-LLM readable fallback
        # and live in the collapsed "Internal / Producer Review" panel — so the
        # ~1,700 obscure PDF fields no longer trigger a humanization pass.
        pre = classify_question(
            field_name, list(missing_fields[field_name]),
            is_curated_client=_is_curated_client_field(field_name),
            canonical_key=_canon,
        )
        if pre["audience"] != AUDIENCE_CLIENT:
            continue
        if field_name not in _HUMANIZED_CACHE:
            llm_needed.append(field_name)

    if llm_needed:
        await _humanize_fields_with_openai(llm_needed)

    for field_name, form_ids in missing_fields.items():
        if field_name in seen_field_names:
            continue
        seen_field_names.add(field_name)

        # Deduplicate row-indexed schema variants (e.g. BusinessInformation_FullTimeEmployeeCount_1,
        # _2, _3 all resolve to the same canonical fact `num_employees`). Without this guard
        # the same plain-English question would appear multiple times in the list.
        canon = _canonical_key(field_name)
        if canon and not canon.startswith("_") and canon in seen_canon_keys:
            # Same underlying fact already produced a question under a different
            # raw ACORD field name (each form names it differently). Merge this
            # form into that question so its label lists every form the single
            # answer fills; the answer reaches all of them on apply via the
            # canonical restamp.
            _merge_form_ids_into_question(questions, canon, form_ids)
            if stats is not None:
                stats["merged_removed"] = stats.get("merged_removed", 0) + 1
            continue
        if canon and not canon.startswith("_"):
            seen_canon_keys.add(canon)

        # Prefer the curated, plain-language question/hint when the raw ACORD
        # field resolves to a known canonical fact, so a client-facing question
        # reads cleanly instead of as a mangled raw field name.
        text_key = canon if (canon and canon in _FIELD_QUESTION_MAP) else field_name
        base_question, group_label = _resolve_question(text_key)

        if group_label is not None:
            group_counts[group_label] = group_counts.get(group_label, 0) + 1
            count = group_counts[group_label]
            if count == 1:
                question_text = base_question
            else:
                question_text = f"{base_question} ({_ordinal(count)} {group_label})"
                if count == 2:
                    for prev_q in questions:
                        if prev_q.get("_group_label") == group_label:
                            prev_q["question"] = f"{base_question} (1st {group_label})"
                            break
        else:
            question_text = base_question

        form_names_list = []
        for fid in sorted(form_ids):
            num = fid.replace("ACORD_", "").replace("ACORD ", "")
            form_names_list.append(num)

        field_type = "text"
        for fid in form_ids:
            schema = generated_forms.get(fid, {}).get("schema", {})
            field_meta = schema.get(field_name, {})
            if isinstance(field_meta, dict):
                ft = field_meta.get("ft", "")
                if "/Btn" in ft:
                    field_type = "checkbox"
                    break

        hint = _FIELD_HINT_MAP.get(text_key, "") or _FIELD_HINT_MAP.get(field_name, "")
        if not hint:
            base_fn = re.sub(r'[_\s]+[a-z]$', '', field_name)
            base_fn = re.sub(r'[_\s]+\d+$', '', base_fn)
            hint = _FIELD_HINT_MAP.get(base_fn, "")
        if not hint and group_label:
            hint = _PREFIX_HINT_MAP.get(group_label, "")

        questions.append({
            "field_name":    field_name,
            "question":      question_text,
            "hint":          hint,
            "forms":         ", ".join(sorted(set(form_names_list))),
            "form_ids":      list(form_ids),
            "field_type":    field_type,
            "current_value": field_current_values.get(field_name, ""),
            "_group_label":  group_label,
            "_is_curated_client": _is_curated_client_field(field_name),
            "_canonical_key":     _canonical_key(field_name),
        })

    # Coverage guarantee: ensure every curated, client-answerable fact each
    # selected form actually needs is present as a clean canonical question - even
    # when no raw ACORD field for it surfaced in the confidence scan, or its only
    # raw field was un-curated and routed to the internal panel. Bounded to curated
    # facts (plain-language) that are still missing and not already represented by
    # canonical key. Each injected question is labelled with EVERY form whose
    # inventory needs it (so the producer sees which forms the answer fills); the
    # ACORD-125 yellow-field send guard exempts these canonical questions because
    # they are curated client facts, not raw 125 schema fields.
    from services.sqs_service import FORM_FIELD_INVENTORY, _fact_is_filled
    _inv_fact_forms: dict = {}
    for _fid in generated_forms:
        for _fact_key in FORM_FIELD_INVENTORY.get(_fid, []):
            _bucket = _inv_fact_forms.setdefault(_fact_key, [])
            if _fid not in _bucket:
                _bucket.append(_fid)
    for _fact_key, _fact_forms in _inv_fact_forms.items():
        if _fact_key not in _FIELD_QUESTION_MAP:
            continue
        if _fact_key in seen_field_names or _fact_key in seen_canon_keys:
            continue
        if _fact_is_filled(facts.get(_fact_key)):
            continue
        seen_field_names.add(_fact_key)
        seen_canon_keys.add(_fact_key)
        _ids  = sorted(set(_fact_forms))
        _nums = sorted({fid.replace("ACORD_", "").replace("ACORD ", "") for fid in _ids})
        questions.append({
            "field_name":         _fact_key,
            "question":           _resolve_question(_fact_key)[0],
            "hint":               _FIELD_HINT_MAP.get(_fact_key, ""),
            "forms":              ", ".join(_nums),
            "form_ids":           _ids,
            "field_type":         "text",
            "current_value":      "",
            "_group_label":       None,
            "_is_curated_client": True,
            "_canonical_key":     _fact_key,
        })

    # §6.4: offer a "no prior losses" attestation when loss history is unestablished.
    _maybe_inject_no_loss_question(questions, facts, flags)
    # §6.4 item 1: ask the client to explain a no-loss / loss-run-claims conflict.
    _maybe_inject_loss_conflict_question(questions, facts, flags)
    # NOTE: "Why are you marketing this account?" is intentionally NOT injected
    # here - it is asked upfront on the recommendation screen (producer-facing,
    # drives ACORD 101 live). Re-asking the client would be redundant, so it is
    # only collected upfront now.
    # Upcoming deadlines / urgency: optional underwriter-context question (Brent).
    _maybe_inject_urgency_question(questions, facts, flags)
    # Umbrella underlying-schedule + follow-form evidence (only when an umbrella is
    # present and the evidence is still missing) - the questionnaire fallback that
    # lets the Umbrella Adequacy -15 / -10 deductions be earned back.
    _maybe_inject_umbrella_evidence_questions(questions, facts, flags)
    # §6.3 item 2: ask the client for each narrative-quality topic the narrative
    # lacks (and stay silent on the ones it already covers).
    _maybe_inject_narrative_enrichment_questions(questions, facts, flags, session_docs)
    # Client examples (2026-07): subcontractor % per class code + vehicles-return-
    # to-yard, gated on GL / auto coverage. Optional client questions (opt-in).
    _maybe_inject_generic_client_questions(questions, facts, flags)

    # Figure 15: ONE table question per repeating schedule, replacing the
    # per-field cards removed by _partition_schedule_fields above.
    questions.extend(_build_schedule_questions(schedule_forms, facts))

    # Curation layer (Beta Report §8): tag audience/priority/topic/score-impact,
    # then apply the curated default-selection policy.
    hard_stop_text = " ".join(str(s) for s in (hard_stops or []))
    decorate_questions(
        questions,
        present_fact_keys=(present_fact_keys if present_fact_keys is not None
                           else _present_fact_keys(facts)),
        narrative_components=_narrative_components_from_facts(facts, session_docs=session_docs, flags=flags),
        hard_stop_text=hard_stop_text,
    )
    # Schedules own their taxonomy explicitly (see docstring): must run after
    # decoration and before the default-selection pass reads priority/suppressed.
    _finalize_schedule_taxonomy(questions)
    apply_default_selection(questions)

    # Engineering note (Figure 14): give the producer a rule-oriented label while
    # the client keeps the plain-language wording. Must run before the cleanup
    # below, which drops the canonical key this resolves against.
    _attach_producer_labels(questions)
    # Figure 18: structured currency / date / code types. Same placement
    # constraint as the labels above - needs `_canonical_key`.
    _attach_input_types(questions)
    # Figure 20: business-specific NAICS / SIC candidates. Same placement
    # constraint again - resolves against `_canonical_key`.
    _attach_classification_suggestions(questions, facts)

    for q in questions:
        q.pop("_group_label", None)
        q.pop("_is_curated_client", None)
        q.pop("_canonical_key", None)

    return questions


# ---------------------------------------------------------------------------
# Clarity pipeline: facts-only ARQ generation (no generated_forms needed)
# ---------------------------------------------------------------------------

def generate_arq_questions_from_facts(
    facts: dict,
    flags: dict,
    selected_form_ids: List[str],
    hard_stops: List[str],
    soft_stops: List[str],
) -> List[dict]:
    """
    Synchronous ARQ question generator for the Clarity pipeline.

    Instead of reading confidence/mapped data from generated PDF forms, it
    consults FORM_FIELD_INVENTORY to know which fields each form requires and
    then checks whether those fields are present in the extracted facts.
    Fields that are missing or empty become ARQ questions for the client.
    """
    from services.sqs_service import FORM_FIELD_INVENTORY, _fact_is_filled

    # Collect missing fields per form.  We deduplicate by field_name across
    # forms so the client is never asked the same question twice.
    missing_fields: dict[str, set] = {}

    for fid in selected_form_ids:
        inventory = FORM_FIELD_INVENTORY.get(fid, [])
        for field_name in inventory:
            if any(p in field_name.lower() for p in ["signature", "sig_", "_sig"]):
                continue
            val = facts.get(field_name)
            if not _fact_is_filled(val):
                if field_name not in missing_fields:
                    missing_fields[field_name] = set()
                missing_fields[field_name].add(fid)

    # Figure 15: collapse repeating-row fields into one table question each,
    # matching the form-aware generator above (no-op when none are present).
    schedule_forms = _partition_schedule_fields(missing_fields, {})

    questions: List[dict] = []
    seen_field_names: set = set()
    group_counts: dict[str, int] = {}

    for field_name, form_ids in missing_fields.items():
        if field_name in seen_field_names:
            continue
        seen_field_names.add(field_name)

        base_question, group_label = _resolve_question(field_name)

        if group_label is not None:
            group_counts[group_label] = group_counts.get(group_label, 0) + 1
            count = group_counts[group_label]
            if count == 1:
                question_text = base_question
            else:
                question_text = f"{base_question} ({_ordinal(count)} {group_label})"
                if count == 2:
                    for prev_q in questions:
                        if prev_q.get("_group_label") == group_label:
                            prev_q["question"] = f"{base_question} (1st {group_label})"
                            break
        else:
            question_text = base_question

        form_names_list = [fid.replace("ACORD_", "").replace("ACORD ", "") for fid in sorted(form_ids)]

        hint = _FIELD_HINT_MAP.get(field_name, "")
        if not hint:
            base_fn = re.sub(r'[_\s]+[a-z]$', '', field_name)
            base_fn = re.sub(r'[_\s]+\d+$', '', base_fn)
            hint = _FIELD_HINT_MAP.get(base_fn, "")
        if not hint and group_label:
            hint = _PREFIX_HINT_MAP.get(group_label, "")

        questions.append({
            "field_name":    field_name,
            "question":      question_text,
            "hint":          hint,
            "forms":         ", ".join(sorted(set(form_names_list))),
            "form_ids":      list(form_ids),
            "field_type":    "text",
            "current_value": "",
            "_group_label":  group_label,
            "_is_curated_client": _is_curated_client_field(field_name),
            "_canonical_key":     _canonical_key(field_name),
        })

    # §6.4: offer a "no prior losses" attestation when loss history is unestablished.
    _maybe_inject_no_loss_question(questions, facts, flags)
    # §6.4 item 1: ask the client to explain a no-loss / loss-run-claims conflict.
    _maybe_inject_loss_conflict_question(questions, facts, flags)
    # Umbrella underlying-schedule + follow-form evidence fallback (umbrella present
    # but evidence missing) - keeps the Clarity path in step with the form-aware ARQ.
    _maybe_inject_umbrella_evidence_questions(questions, facts, flags)
    # §6.3 item 2: ask the client for each narrative-quality topic the narrative lacks.
    _maybe_inject_narrative_enrichment_questions(questions, facts, flags)
    # Client examples (2026-07): subcontractor % per class code + vehicles-return-
    # to-yard, gated on GL / auto coverage. Optional client questions (opt-in).
    _maybe_inject_generic_client_questions(questions, facts, flags)

    # Figure 15: ONE table question per repeating schedule.
    questions.extend(_build_schedule_questions(schedule_forms, facts))

    hard_stop_text = " ".join(str(s) for s in (hard_stops or []))
    decorate_questions(
        questions,
        present_fact_keys=_present_fact_keys(facts),
        narrative_components=_narrative_components_from_facts(facts, flags=flags),
        hard_stop_text=hard_stop_text,
    )  # session_docs not available on this path; uses the stored profile + facts
    _finalize_schedule_taxonomy(questions)
    apply_default_selection(questions)

    # Engineering note (Figure 14): give the producer a rule-oriented label while
    # the client keeps the plain-language wording. Must run before the cleanup
    # below, which drops the canonical key this resolves against.
    _attach_producer_labels(questions)
    # Figure 18: structured currency / date / code types. Same placement
    # constraint as the labels above - needs `_canonical_key`.
    _attach_input_types(questions)
    # Figure 20: business-specific NAICS / SIC candidates. Same placement
    # constraint again - resolves against `_canonical_key`.
    _attach_classification_suggestions(questions, facts)

    for q in questions:
        q.pop("_group_label", None)
        q.pop("_is_curated_client", None)
        q.pop("_canonical_key", None)

    return questions


# ---------------------------------------------------------------------------
# Cross-form conflict ARQ questions
# ---------------------------------------------------------------------------

# Maps cross-form issue codes to human-readable resolution questions.
# Each entry: (question_text, hint_text, field_name_for_answer, field_type)
_CROSS_FORM_QUESTION_MAP: dict[str, tuple[str, str, str, str]] = {
    "wc_payroll_mismatch": (
        "Your Workers Compensation payroll and total payroll don't match. "
        "What is the correct total annual payroll for all employees?",
        "Enter the gross annual wages paid to all employees, e.g. '$350,000'. "
        "This should match both your payroll records and workers comp figures.",
        "total_payroll",
        "text",
    ),
    "wc_state_payroll_total_mismatch": (
        "The state-level WC payroll breakdown does not add up to your total payroll. "
        "Please confirm your total annual payroll across all states.",
        "Enter the total gross payroll across all states, e.g. '$500,000'.",
        "total_payroll",
        "text",
    ),
    "wc_multi_state_no_breakdown": (
        "Your business has employees in more than one state. "
        "Please provide your annual payroll broken out by state "
        "(e.g. 'Texas: $200,000 / California: $150,000').",
        "List each state and the payroll amount for employees in that state.",
        "wc_payroll_by_state",
        "text",
    ),
    "high_subcontracting_no_wc_payroll": (
        "Your application shows a high percentage of subcontracted work "
        "but no Workers Compensation payroll was found. "
        "What is the total annual payroll for your own (non-subcontracted) employees?",
        "Enter the gross annual wages paid to your own employees, e.g. '$120,000'. "
        "Enter '$0' if you have no direct employees.",
        "wc_payroll",
        "text",
    ),
    "location_count_mismatch": (
        "The number of business locations on your application doesn't match "
        "your property schedule. How many physical locations does your business have?",
        "Enter the total number of locations — each location will need its own "
        "address and property details.",
        "locations",
        "text",
    ),
    "umbrella_sir_below_gl_deductible": (
        "Your umbrella self-insured retention (SIR) appears to be lower than "
        "your GL deductible, which can leave a coverage gap. "
        "Please confirm your umbrella SIR amount.",
        "Enter your umbrella self-insured retention, e.g. '$10,000'. "
        "This should be equal to or greater than your GL deductible.",
        "umbrella_sir",
        "text",
    ),
    "umbrella_missing_employers_liability": (
        "Your umbrella policy attaches over Workers Compensation, but we couldn't "
        "find your Employers Liability limits. What are your Employers Liability limits?",
        "Enter your Employers Liability limits, e.g. '$100,000 / $500,000 / $100,000' "
        "(per accident / disease policy / disease each employee).",
        "employers_liability_limits",
        "text",
    ),
    "umbrella_gl_period_misaligned": (
        "Your umbrella policy effective date doesn't match your GL/underlying policy "
        "dates. What is the correct policy effective date?",
        "Enter the date all your policies begin in MM/DD/YYYY format.",
        "effective_date",
        "date",
    ),
    "bi_missing_period_of_restoration": (
        "You have Business Income coverage but no Period of Restoration was provided. "
        "How many months would it take to reopen your business after a major covered loss?",
        "Estimate the number of months needed to repair damage and reopen, e.g. '6 months' or '12 months'.",
        "period_of_restoration",
        "text",
    ),
    "acord125_missing": (
        "We weren't able to identify a commercial insurance application in your "
        "uploaded documents. Can you confirm what type of submission this is?",
        "Describe the type of coverage you need, e.g. 'new business GL and Property'.",
        "lines_of_business",
        "text",
    ),
    "gl_codes_no_operations": (
        "GL class codes were found but your application doesn't have a description "
        "of business operations. In a few sentences, what does your business do?",
        "Describe your main products or services, e.g. "
        "'We install commercial HVAC systems in office buildings across Texas.'",
        "operations_description",
        "text",
    ),
    "contractor_missing_acord186": (
        "Your business appears to be a contractor but the Contractors Supplement "
        "is missing. What percentage of your total work is done by subcontractors?",
        "Enter a percentage, e.g. '40%'. If you use no subcontractors, enter '0%'.",
        "percent_subcontracted",
        "text",
    ),
    "wc_gl_class_code_mismatch": (
        "Your Workers Compensation class codes indicate heavy manual labor but your "
        "GL class codes suggest office or clerical operations. "
        "Please describe your business operations so we can verify the correct "
        "class code assignment.",
        "Describe what your employees actually do day-to-day, e.g. "
        "'50% office staff handling admin, 50% field technicians installing equipment.'",
        "operations_description",
        "text",
    ),
    "claims_made_missing_retro_date": (
        "Your General Liability policy is written on a claims-made basis but no "
        "retroactive date was found. What is the retroactive date for your GL policy?",
        "Enter the original start date of continuous GL coverage in MM/DD/YYYY format, "
        "e.g. '01/01/2018'. This is the earliest date from which claims can arise.",
        "retro_date",
        "date",
    ),
    "claims_made_missing_prior_acts": (
        "Your GL policy is claims-made. Does your coverage include prior acts "
        "(also called 'nose coverage' or 'prior acts endorsement')?",
        "Answer Yes or No. If yes, enter the date prior acts coverage begins.",
        "prior_acts_confirmation",
        "text",
    ),
    "umbrella_gl_attachment_failure": (
        "Your GL per-occurrence limit appears to be below the minimum required for "
        "umbrella attachment. What is your GL each-occurrence limit?",
        "Enter the maximum payout per single incident under your GL policy, "
        "e.g. '$1,000,000'. Umbrella coverage typically requires at least $1M GL underlying.",
        "gl_each_occurrence",
        "text",
    ),
    "umbrella_auto_attachment_failure": (
        "Your Auto combined single limit appears to be below the minimum typically "
        "required for umbrella attachment. What is your Auto liability limit?",
        "Enter the Auto combined single limit (CSL), e.g. '$1,000,000'. Umbrella "
        "coverage typically requires at least $1M Auto CSL underlying.",
        "auto_liability_limit",
        "text",
    ),
    "umbrella_auto_period_misaligned": (
        "Your umbrella and Auto policy effective dates don't match. "
        "What is the correct effective date for your Auto policy?",
        "Enter the date your Auto policy begins in MM/DD/YYYY format.",
        "auto_effective_date",
        "date",
    ),
    "umbrella_wc_period_misaligned": (
        "Your umbrella and Workers Compensation policy effective dates don't match. "
        "What is the correct effective date for your WC policy?",
        "Enter the date your Workers Compensation policy begins in MM/DD/YYYY format.",
        "wc_effective_date",
        "date",
    ),
}


def generate_cross_form_arq_questions(
    cross_form_issues: List[dict],
    generated_forms: dict,
    facts: dict = None,
    flags: dict = None,
) -> List[dict]:
    """
    Convert cross-form validation issues into ARQ questions for the client.

    Only hard_stop and soft_warning issues generate questions.
    Advisory issues are informational and do not require client input.

    Parameters
    ----------
    cross_form_issues : list of issue dicts from run_cross_form_validation()
    generated_forms   : current generated_forms dict (used to avoid asking
                        questions about fields already filled by the client)

    Returns
    -------
    List of question dicts in the same format as generate_arq_questions().
    """
    questions: List[dict] = []
    seen_field_names: set = set()

    # Build a flat map of already-filled fields across all forms
    filled_fields: set = set()
    for form_data in generated_forms.values():
        mapped = form_data.get("field_state") or form_data.get("mapped", {})
        for field, val in mapped.items():
            if val is not None and str(val).strip() not in ("", "null", "None"):
                filled_fields.add(field)

    for issue in cross_form_issues:
        itype = issue.get("type", "advisory")
        if itype == "advisory":
            continue

        code = issue.get("code", "")
        if code not in _CROSS_FORM_QUESTION_MAP:
            continue

        q_text, hint, field_name, field_type = _CROSS_FORM_QUESTION_MAP[code]

        # Skip if we've already queued a question for this field
        if field_name in seen_field_names:
            continue

        # Skip if the field is already filled
        if field_name in filled_fields:
            continue

        seen_field_names.add(field_name)
        forms_involved = issue.get("forms", [])
        form_nums = sorted(
            {str(f).replace("ACORD_", "").replace("ACORD ", "") for f in forms_involved}
        )

        questions.append({
            "field_name":    field_name,
            "question":      q_text,
            "hint":          hint,
            "forms":         ", ".join(form_nums),
            "form_ids":      forms_involved,
            "field_type":    field_type,
            "current_value": "",
            "source":        "cross_form_conflict",
            "conflict_code": code,
            "severity":      itype,
            "_is_cross_form": True,
            "_is_curated_client": True,
            "_canonical_key":  _canonical_key(field_name),
        })

    # Cross-form conflicts are client-relevant structural issues; tag them so
    # the producer UI groups them and flags their hard-stop / SQS impact. Apply
    # the same narrative suppression/labelling as the other paths so a question
    # the narrative already covers is not re-asked here either (§6.3 item 2 -
    # closes the cross-form path inconsistency).
    decorate_questions(
        questions,
        present_fact_keys=_present_fact_keys(facts or {}),
        narrative_components=_narrative_components_from_facts(facts or {}, flags=flags),
    )
    _attach_producer_labels(questions)
    _attach_input_types(questions)
    _attach_classification_suggestions(questions, facts or {})

    for q in questions:
        q.pop("_is_cross_form", None)
        q.pop("_is_curated_client", None)
        q.pop("_canonical_key", None)

    return questions


# ---------------------------------------------------------------------------
# ARQ session CRUD
# ---------------------------------------------------------------------------

def _decode_arq_row(row: dict) -> dict:
    """Decode JSON string columns if not already parsed by asyncpg codec."""
    # `not_sure_fields` is a LIST of field names; the other two are dict/list as
    # before. Rows created before the column existed come back NULL, so each is
    # coerced to its correct empty shape.
    _empty = {"questions": [], "answers": {}, "not_sure_fields": [], "review_fields": []}
    for col in ("questions", "answers", "not_sure_fields", "review_fields"):
        val = row.get(col)
        if isinstance(val, str):
            try:
                row[col] = json.loads(val)
            except Exception:
                row[col] = _empty[col]
        elif val is None:
            row[col] = _empty[col]
    return row


# ASYNC-SAFE
async def create_arq_session(
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

    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO arq_sessions
               (id, session_id, user_id, token, email, client_name, status, questions, answers,
                expires_at, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,'pending',$7,'{}',$8,$9)""",
            arq_id, processing_session_id, user_id, token,
            client_email, client_name or "",
            json.dumps(questions), expires, now,
        )
    logger.info(f"ARQ session created: {arq_id} for session={processing_session_id}")
    return {"arq_id": arq_id, "token": token, "expires_at": expires}


# ASYNC-SAFE
async def get_arq_by_token(token: str) -> Optional[dict]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM arq_sessions WHERE token = $1", token
        )
    if not row:
        return None
    return _decode_arq_row(dict(row))


# ASYNC-SAFE
async def get_arq_by_id(arq_id: str) -> Optional[dict]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM arq_sessions WHERE id = $1", arq_id
        )
    if not row:
        return None
    return _decode_arq_row(dict(row))


# ASYNC-SAFE
async def get_arq_sessions_for_user(user_id: str) -> List[dict]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM arq_sessions WHERE user_id = $1 ORDER BY created_at DESC",
            user_id,
        )
    return [_decode_arq_row(dict(r)) for r in rows]


# ASYNC-SAFE
async def save_arq_draft(token: str, draft_answers: dict) -> bool:
    """Persist partial answers server-side without marking the session submitted."""
    try:
        async with get_pool().acquire() as conn:
            result = await conn.execute(
                """UPDATE arq_sessions
                   SET draft_answers=$1
                   WHERE token=$2 AND status != 'submitted'""",
                json.dumps(draft_answers), token,
            )
        return result != "UPDATE 0"
    except Exception as ex:
        logger.warning(f"save_arq_draft failed: {ex}")
        return False


# ASYNC-SAFE
async def mark_arq_viewed(token: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE arq_sessions SET viewed_at=$1 WHERE token=$2 AND viewed_at IS NULL",
            now, token,
        )


# ASYNC-SAFE
async def submit_arq_answers(
    token: str,
    raw_answers: dict,
    processing_session_id: str,
    generated_forms: dict,
) -> Tuple[bool, str, List[str], dict]:
    """Returns `(ok, message, updated_fields, field_errors)`.

    `field_errors` is a {field_name: message} map. When it is non-empty the
    submission is REJECTED and nothing is written - the client fixes the
    format and resubmits (or marks the question "I'm not sure").
    """
    arq = await get_arq_by_token(token)
    if not arq:
        return False, "ARQ session not found.", [], {}

    now     = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return False, "This questionnaire link has expired.", [], {}

    if arq["status"] == "submitted":
        return False, "This questionnaire has already been submitted.", [], {}

    questions      = arq["questions"]
    cleaned        = {}
    updated_fields = []
    not_sure       = []
    # A format error the CLIENT can see and fix - blocks the submission.
    field_errors   = {}
    # A format oddity the client's browser does NOT validate (see
    # `_blocks_submit`). Kept, stored, and surfaced to the producer rather than
    # blocking, because the client has no way to act on it.
    review         = []

    for q in questions:
        field_name = q["field_name"]
        raw_val    = raw_answers.get(field_name, "")

        # Explicit client "I'm not sure" — recorded as a follow-up item, never as
        # an answer. Iterating over `questions` (not over client-supplied keys)
        # also bounds this list to fields that were actually sent, so a crafted
        # payload cannot inject arbitrary field names here.
        if is_not_sure_value(raw_val):
            # Store the question text alongside the field name so the producer's
            # follow-up panel can render it directly, with no extra lookup.
            not_sure.append({
                "field_name": field_name,
                "question":   str(q.get("question", ""))[:300],
            })
            continue

        if schedule_capture.is_schedule_answer_key(field_name):
            # A schedule answer is a JSON list of rows, not a scalar string, so
            # it must bypass `_clean_answer` (which would reject/truncate it).
            # Validation is advisory here for the same reason it is in the UI: a
            # partially-complete fleet is worth more than a refused submission,
            # and the producer sees the flagged rows on their side.
            _list_key = schedule_capture.list_key_from_answer_key(field_name)
            _rows, _report = schedule_capture.validate_rows(
                _list_key, schedule_capture.decode_answer(raw_val),
            )
            cleaned_val = schedule_capture.encode_answer(_rows) if _rows else None
            if cleaned_val is not None and (_report["errors"] or _report["duplicates"]):
                logger.info(
                    "ARQ submit: schedule %s accepted with %d row error(s), %d duplicate(s)",
                    _list_key, len(_report["errors"]), len(_report["duplicates"]),
                )
            review_reason = ""
        elif q.get("field_type") == "checkbox":
            cleaned_val = raw_val if raw_val in ("Yes", "No", "true", "false") else None
            review_reason = ""
        else:
            cleaned_val, review_reason = _clean_answer_ex(raw_val, field_name)

        if cleaned_val is not None:
            if review_reason and _blocks_submit(q.get("field_type"), field_name):
                # Client-visible format error: refuse the submission so the
                # value never reaches an ACORD box. They can correct it or tap
                # "I'm not sure" - which is why this can never dead-end them.
                field_errors[field_name] = review_reason
                continue
            cleaned[field_name] = cleaned_val
            updated_fields.append(field_name)
            if review_reason:
                review.append({
                    "field_name": field_name,
                    "question":   str(q.get("question", ""))[:300],
                    "value":      str(cleaned_val)[:200],
                    "reason":     review_reason,
                })

    if field_errors:
        # Nothing is written - not the answers, not the status. The client's
        # draft is already saved server-side, so their work is safe while they
        # fix the highlighted fields.
        logger.info(
            "ARQ submit rejected: %d field(s) failed format validation for token=%s…",
            len(field_errors), token[:8],
        )
        return (
            False,
            "Some answers need a small correction before we can submit.",
            [],
            field_errors,
        )

    now_iso = now.isoformat()
    async with get_pool().acquire() as conn:
        try:
            await conn.execute(
                "UPDATE arq_sessions SET answers=$1, not_sure_fields=$2, review_fields=$3, "
                "status='submitted', submitted_at=$4 WHERE token=$5",
                json.dumps(cleaned), json.dumps(not_sure), json.dumps(review), now_iso, token,
            )
        except Exception as _review_ex:
            # `review_fields` is the newest column; an instance that has not yet
            # restarted through init_db() must still record the answers and the
            # follow-up list exactly as before.
            logger.warning(
                "ARQ submit: review_fields update failed (%s); "
                "falling back to the pre-Figure-18 write.", _review_ex,
            )
            await _submit_without_review(conn, cleaned, not_sure, now_iso, token)

    if review:
        logger.info(
            "ARQ submit: %d answer(s) kept but flagged for producer review for token=%s…",
            len(review), token[:8],
        )

    if not_sure:
        logger.info(
            "ARQ submit: client marked %d field(s) as 'not sure' for token=%s…",
            len(not_sure), token[:8],
        )

    return True, "Answers submitted successfully.", updated_fields, {}


async def _submit_without_review(conn, cleaned, not_sure, now_iso, token) -> None:
    """Pre-Figure-18 submit write, used when `review_fields` is unavailable.

    Preserves the original two-tier resilience exactly: try the answers plus
    the follow-up list, and if even that column is missing, commit the answers
    alone. A client's submission is terminal - it must never fail over a
    reporting column.
    """
    try:
        await conn.execute(
            "UPDATE arq_sessions SET answers=$1, not_sure_fields=$2, status='submitted', "
            "submitted_at=$3 WHERE token=$4",
            json.dumps(cleaned), json.dumps(not_sure), now_iso, token,
        )
    except Exception as ex:
        logger.error(
            "ARQ submit: not_sure_fields update failed (%s); "
            "committing answers without the follow-up list.", ex,
        )
        await conn.execute(
            "UPDATE arq_sessions SET answers=$1, status='submitted', submitted_at=$2 "
            "WHERE token=$3",
            json.dumps(cleaned), now_iso, token,
        )


def _restamp_canonical_into_forms(
    generated: dict,
    canon: str,
    facts: dict,
) -> List[str]:
    """Stamp a client-confirmed canonical fact into every generated form that
    carries it under an ACORD schema field name.

    `canon` is a canonical fact key (e.g. `applicant_name`) already written into
    `facts`. For each generated form we run the SAME deterministic rule engine
    used by the initial fill (`_deterministic_map`) over the form's schema. Only
    fields that resolve specifically to `canon` are touched, and only when the
    deterministic map yields a non-empty value — so this never overwrites an
    unrelated field or blanks one out. Each stamped field is labelled
    `client_arq` and its PDF cache is busted so the next render shows the value.

    Returns the list of form ids that received at least one stamped field.
    """
    try:
        from services.pdf_service import _deterministic_map
    except Exception as ex:
        logger.warning(f"_restamp_canonical: pdf_service import failed: {ex}")
        return []

    touched_forms: List[str] = []
    for fid, form_data in generated.items():
        schema = form_data.get("schema", {}) or {}
        if not schema:
            continue
        field_state = form_data.get("field_state") or form_data.get("mapped", {})
        conf = form_data.get("confidence") or {}
        cff = set(form_data.get("client_filled_fields", []))
        form_touched = False

        for schema_field in schema.keys():
            # Only consider schema fields that map to THIS canonical fact. This
            # keeps the re-stamp surgical: a question about `applicant_name`
            # touches only the named-insured fields, nothing else.
            if _canonical_key(schema_field) != canon:
                continue
            mapped_val = _deterministic_map(schema_field, facts)
            if mapped_val is None or str(mapped_val).strip() == "":
                continue
            if str(field_state.get(schema_field) or "").strip() == str(mapped_val).strip():
                # Already shows the confirmed value — still label as client-supplied
                # but don't force a needless re-render.
                if conf.get(schema_field) != "client_arq":
                    conf[schema_field] = "client_arq"
                cff.add(schema_field)
                continue
            field_state[schema_field] = mapped_val
            conf[schema_field] = "client_arq"
            cff.add(schema_field)
            form_touched = True

        if form_touched or cff != set(form_data.get("client_filled_fields", [])):
            form_data["field_state"] = field_state
            form_data["confidence"] = conf
            form_data["client_filled_fields"] = list(cff)
        if form_touched:
            form_data["_pdf_cache_hash"] = ""
            form_data["pdf_bytes"] = None
            touched_forms.append(fid)

    return touched_forms


def _restamp_schedule_into_forms(
    generated: dict,
    list_key: str,
    facts: dict,
) -> List[str]:
    """Stamp a client-provided schedule into every form's repeating rows.

    The schedule list has already been written to `facts[list_key]`, so this
    replays the SAME resolver Pass 1 uses (`_resolve_schedule_row`) over each
    form's schema and writes whatever it yields. Only fields bound to THIS
    schedule are touched, so an unrelated form or column is never affected.

    Rows beyond the form's physical capacity (A..N) resolve to None and are
    simply not stamped - the full list still lives in facts, which is what
    downstream scoring and any overflow attachment read.

    A schedule-bound field is exclusively owned by its schedule - nothing else
    ever writes to `Vehicle_VINIdentifier_F`, for example - so this function
    must be authoritative, not just additive. If a row is deleted (the client
    removed a duplicate, or the schedule simply got shorter), the field must be
    CLEARED back to blank, not left holding the previous vehicle's stale value.
    A prior version only wrote when a row produced a value and silently skipped
    otherwise, so a deleted vehicle's old VIN/make/model kept printing on the
    PDF forever - fixed by always resolving to either the row's value or "".
    """
    try:
        from services.pdf_service import _SCHED_SKIP, _resolve_schedule_row
    except Exception as ex:  # pragma: no cover - defensive
        logger.warning(f"_restamp_schedule: pdf_service import failed: {ex}")
        return []

    touched_forms: List[str] = []
    for fid, form_data in generated.items():
        schema = form_data.get("schema", {}) or {}
        if not schema:
            continue
        field_state = form_data.get("field_state") or form_data.get("mapped", {})
        conf = form_data.get("confidence") or {}
        cff = set(form_data.get("client_filled_fields", []))
        form_touched = False

        for schema_field in schema.keys():
            if schedule_capture.schedule_list_key_for_field(schema_field) != list_key:
                continue
            val = _resolve_schedule_row(schema_field, facts)
            if val is _SCHED_SKIP:
                continue
            val = "" if (val is None or str(val).strip() == "") else val

            if str(field_state.get(schema_field) or "").strip() != str(val).strip():
                field_state[schema_field] = val
                form_touched = True

            if val:
                conf[schema_field] = "client_arq"
                cff.add(schema_field)
            else:
                # Row removed: this box is no longer schedule-provided - drop
                # its provenance too, so a cleared field doesn't keep reading
                # as "client answered" once it's genuinely blank again.
                conf.pop(schema_field, None)
                cff.discard(schema_field)

        if form_touched or cff != set(form_data.get("client_filled_fields", [])):
            form_data["field_state"] = field_state
            form_data["confidence"] = conf
            form_data["client_filled_fields"] = list(cff)
        if form_touched:
            form_data["_pdf_cache_hash"] = ""
            form_data["pdf_bytes"] = None
            touched_forms.append(fid)

    return touched_forms


# ASYNC-SAFE
async def apply_arq_answers_to_session(
    arq_id: str,
    processing_session_id: str,
) -> Tuple[bool, List[str]]:
    from repositories.session_repository import get_processing_session, upd_processing_session

    arq = await get_arq_by_id(arq_id)
    if not arq or arq["status"] != "submitted":
        return False, []

    answers   = arq.get("answers", {})
    questions = arq.get("questions", [])
    if not answers:
        return True, []

    field_to_forms: dict = {}
    for q in questions:
        fn = q["field_name"]
        if fn in answers:
            field_to_forms[fn] = q.get("form_ids", [])

    try:
        proc_session = await get_processing_session(processing_session_id)
    except Exception as ex:
        logger.error(f"apply_arq_answers: cannot load session {processing_session_id}: {ex}")
        return False, []

    from services.sqs_service import _attested_true

    generated = proc_session.get("generated_forms", {})
    facts     = dict(proc_session.get("facts", {}) or {})
    flags     = dict(proc_session.get("flags", {}) or {})
    flags_changed = False
    updated   = []

    for field_name, form_ids in field_to_forms.items():
        new_val = answers[field_name]

        # Schedule answers carry a list of rows, not a scalar. They are written
        # to `facts[list_key]` (the shape `_resolve_schedule_row` reads) and
        # stamped into each form's repeating rows. This MUST short-circuit the
        # scalar path below: that path writes `field_state[field_name] = value`
        # for every form in `form_ids`, which would otherwise plant a raw JSON
        # blob under the synthetic `schedule::<key>` name in the form state.
        if schedule_capture.is_schedule_answer_key(field_name):
            list_key = schedule_capture.list_key_from_answer_key(field_name)
            rows, _report = schedule_capture.validate_rows(
                list_key, schedule_capture.decode_answer(new_val),
            )
            facts[list_key] = schedule_capture.rows_for_facts(list_key, rows)
            for _fid in _restamp_schedule_into_forms(generated, list_key, facts):
                if _fid not in updated:
                    updated.append(_fid)
            if _report["overflow"]:
                logger.info(
                    "ARQ apply: schedule %s has %d row(s) beyond the form's "
                    "%d-row capacity; full list retained in facts.",
                    list_key, _report["overflow"], schedule_capture.ROW_CAPACITY,
                )
            if field_name not in updated:
                updated.append(field_name)
            continue

        for fid, form_data in generated.items():
            field_state = form_data.get("field_state") or form_data.get("mapped", {})
            schema      = form_data.get("schema", {})
            if field_name in schema or field_name in field_state or fid in form_ids:
                field_state[field_name] = new_val
                form_data["field_state"] = field_state
                # Label as client-supplied (scores 1.00 in SQS, distinct from
                # source-document evidence — Beta Report §6 evidence labelling).
                conf = form_data.get("confidence") or {}
                conf[field_name] = "client_arq"
                form_data["confidence"] = conf
                cff = set(form_data.get("client_filled_fields", []))
                cff.add(field_name)
                form_data["client_filled_fields"] = list(cff)
                # Bust the PDF cache so the next get-pdf regenerates the form
                # with the client's answer baked in (populated after refresh).
                form_data["_pdf_cache_hash"] = ""
                form_data["pdf_bytes"] = None
        # Mirror the answer into canonical facts so SQS, stops, and readiness can
        # actually move — the per-form field_state alone never reached the
        # facts-driven scorers (root cause of "score didn't change", §6.2).
        canon = _canonical_key(field_name)
        if canon and not canon.startswith("_"):
            facts[canon] = {
                "value":      str(new_val),
                "confidence": "client_arq",
                "source":     "client_arq",
            }
            # Stamp this canonical answer into EVERY generated form whose schema
            # carries it under an ACORD field name. Curated client questions and
            # every `_maybe_inject_*` / coverage-guarantee question key on a
            # canonical fact directly (e.g. `field_name == "num_employees"`) -
            # no raw ACORD schema field is ever literally named that, so the PDF
            # has nowhere for the direct field_state write below to land. We
            # reuse the same deterministic rule engine that the initial fill
            # used (_deterministic_map, no LLM), so the value lands in exactly
            # the fields Pass 1 would have filled, across all forms.
            #
            # FIX (2026-07, live finding): this used to run only `if canon !=
            # field_name`, on the assumption that `canon == field_name` meant
            # field_name was already a real schema field. That assumption is
            # false for every canonical-only injected question - confirmed live:
            # a client answered "How many people does your business employ?"
            # (field_name="num_employees", which IS its own canonical key), the
            # answer updated `facts` and moved SQS, but the real ACORD 125 boxes
            # (BusinessInformation_FullTimeEmployeeCount_A /
            # PartTimeEmployeeCount_A) were never touched - the PDF stayed
            # exactly as it was before the client answered anything.
            #
            # Always calling this is safe: `_restamp_canonical_into_forms` only
            # writes when `_deterministic_map` produces a non-empty value and
            # the box doesn't already show it, so a field_name that IS already a
            # real schema field (the common case) is a harmless no-op re-stamp,
            # not a double-write of different data.
            _stamped_forms = _restamp_canonical_into_forms(
                generated, canon, facts,
            )
            for _fid in _stamped_forms:
                if _fid not in updated:
                    updated.append(_fid)
            # §6.4: an affirmative "no prior losses" attestation must also set the
            # flag (not just a facts string) so the loss-history pillar moves. A
            # "No" answer means the client HAS losses — do not set the flag.
            if canon == NO_LOSS_INDICATOR_FIELD:
                if _attested_true(new_val):
                    flags["no_prior_losses"] = True
                    flags_changed = True
                else:
                    # L9 fix: a "No" answer (client has losses) must reset the flag
                    # so a subsequent recompute doesn't keep awarding the no-loss credit.
                    if flags.get("no_prior_losses"):
                        flags["no_prior_losses"] = False
                        flags_changed = True
            elif canon == CARRIER_MARKETING_FIELD:
                # Derive prior_carrier_adverse_action from the selected reason.
                # Adverse options escalate ACORD 101 and impact Narrative Quality.
                _val_lower = str(new_val).strip().lower()
                if _val_lower.startswith("other:"):
                    _free_text = str(new_val).strip()[6:].strip()
                    _is_adverse = await _classify_other_reason_adverse(_free_text)
                else:
                    _is_adverse = _val_lower in _ADVERSE_CARRIER_REASONS
                flags["prior_carrier_adverse_action"] = _is_adverse
                flags_changed = True
        if field_name not in updated:
            updated.append(field_name)

    _update_payload = {"generated_forms": generated, "facts": facts}
    if flags_changed:
        _update_payload["flags"] = flags
    await upd_processing_session(processing_session_id, _update_payload)
    logger.info(f"ARQ {arq_id}: applied {len(updated)} fields to session {processing_session_id}")
    return True, updated


# ASYNC-SAFE
async def get_session_schedules(processing_session_id: str) -> List[dict]:
    """Every capturable schedule for a session, with its current rows.

    Powers the producer-side pre-load table: the agent can paste or upload the
    fleet/driver/location list BEFORE sending the questionnaire, and the client
    then edits an already-populated table instead of starting from nothing.

    A schedule is included when the session's selected forms actually have
    repeating rows bound to it, OR when rows already exist for it - so the agent
    is never shown a Workers Comp class-code table on a property-only package.
    """
    from repositories.session_repository import get_processing_session

    try:
        proc = await get_processing_session(processing_session_id)
    except Exception as ex:
        logger.error(f"get_session_schedules: cannot load {processing_session_id}: {ex}")
        return []

    facts     = proc.get("facts", {}) or {}
    generated = proc.get("generated_forms", {}) or {}

    relevant: dict = {}
    for fid, form_data in generated.items():
        for schema_field in (form_data.get("schema", {}) or {}).keys():
            lk = schedule_capture.schedule_list_key_for_field(schema_field)
            if lk:
                relevant.setdefault(lk, set()).add(fid)

    out: List[dict] = []
    for list_key, defn in schedule_capture.SCHEDULE_DEFS.items():
        rows, report = schedule_capture.validate_rows(
            list_key, schedule_capture.rows_from_facts(list_key, facts),
        )
        form_ids = sorted(relevant.get(list_key, set()))
        if not form_ids and not rows:
            continue
        out.append({
            "schedule_key":      list_key,
            "schedule_label":    defn["label"],
            "schedule_singular": defn["singular"],
            "columns":           defn["columns"],
            "dedup_keys":        defn["dedup_keys"],
            "vin_decode":        bool(defn["vin_decode"]),
            "row_capacity":      schedule_capture.ROW_CAPACITY,
            "rows":              rows,
            "row_count":         report["row_count"],
            "overflow":          report["overflow"],
            "duplicates":        report["duplicates"],
            "form_ids":          form_ids,
            "forms": ", ".join(sorted({
                f.replace("ACORD_", "").replace("ACORD ", "") for f in form_ids
            })),
        })
    return out


# ASYNC-SAFE
async def save_session_schedule(
    processing_session_id: str,
    list_key: str,
    rows: list,
) -> Tuple[bool, dict]:
    """Write a producer-supplied schedule into the session and stamp the forms.

    Mirrors the client-submit path exactly (validate -> facts -> re-stamp), so a
    schedule pre-loaded by the agent and one submitted by the client land in the
    same place with the same shape. Provenance differs: these rows come from the
    agency, so stamped cells are labelled `producer` rather than `client_arq`.
    """
    from repositories.session_repository import get_processing_session, upd_processing_session

    if schedule_capture.get_def(list_key) is None:
        return False, {"message": "Unknown schedule."}

    try:
        proc = await get_processing_session(processing_session_id)
    except Exception as ex:
        logger.error(f"save_session_schedule: cannot load {processing_session_id}: {ex}")
        return False, {"message": "Session not found."}

    clean_rows, report = schedule_capture.validate_rows(list_key, rows)
    facts     = dict(proc.get("facts", {}) or {})
    generated = proc.get("generated_forms", {}) or {}

    facts[list_key] = schedule_capture.rows_for_facts(list_key, clean_rows)
    touched = _restamp_schedule_into_forms(generated, list_key, facts)

    # Producer-sourced, not client-sourced: relabel what the shared re-stamp
    # marked so evidence provenance stays accurate for SQS and the audit trail.
    for fid in touched:
        form_data = generated.get(fid, {})
        conf = form_data.get("confidence") or {}
        cff = set(form_data.get("client_filled_fields", []))
        for schema_field in list(conf.keys()):
            if (conf.get(schema_field) == "client_arq"
                    and schedule_capture.schedule_list_key_for_field(schema_field) == list_key):
                conf[schema_field] = "producer"
                cff.discard(schema_field)
        form_data["confidence"] = conf
        form_data["client_filled_fields"] = list(cff)

    await upd_processing_session(
        processing_session_id, {"generated_forms": generated, "facts": facts},
    )
    logger.info(
        "save_session_schedule: %s rows=%d forms_touched=%d session=%s",
        list_key, len(clean_rows), len(touched), processing_session_id,
    )
    return True, {
        "rows":       clean_rows,
        "row_count":  report["row_count"],
        "errors":     report["errors"],
        "duplicates": report["duplicates"],
        "overflow":   report["overflow"],
        "forms_updated": touched,
    }


# ASYNC-SAFE
async def apply_producer_answer_to_session(
    processing_session_id: str,
    field_name: str,
    value: str,
) -> Tuple[bool, List[str]]:
    """Apply a single producer-entered recommendation answer to the session.

    Fig 13 producer-answer flow. Writes the typed value into the session facts as
    a producer-provenance fact (source="producer", confidence="filled" - scores
    1.00 in SQS, exactly like a producer field edit, and distinct in the audit
    trail from a client_arq answer), stamps it into every generated form that
    carries the canonical fact, and mirrors the same loss-history / carrier flag
    derivation apply_arq_answers_to_session uses so the facts-driven scorers move.
    The caller re-runs recalculate_session_scores afterwards to recompute stops
    and SQS and to auto-resolve any recommendation the answer cleared.

    Returns (ok, updated_ids). ok=False (with empty list) means the recommendation
    does not resolve to a fillable canonical fact - the caller should route the
    producer to attach a supporting document or dismiss with a note instead.
    """
    from repositories.session_repository import (
        get_processing_session, upd_processing_session,
    )

    canon = _canonical_key(field_name)
    if not canon or canon.startswith("_"):
        return False, []

    new_val = str(value).strip()
    if not new_val:
        return False, []

    try:
        proc_session = await get_processing_session(processing_session_id)
    except Exception as ex:
        logger.error(f"apply_producer_answer: cannot load session {processing_session_id}: {ex}")
        return False, []

    from services.sqs_service import _attested_true

    generated = proc_session.get("generated_forms", {}) or {}
    facts     = dict(proc_session.get("facts", {}) or {})
    flags     = dict(proc_session.get("flags", {}) or {})
    flags_changed = False
    updated: List[str] = []

    # Producer-provenance fact. Distinct source from client_arq; same 1.00 weight.
    facts[canon] = {
        "value":      new_val,
        "confidence": "filled",
        "source":     "producer",
    }

    # Stamp the confirmed value into every generated form whose schema carries it
    # (same deterministic engine used by the initial fill and the ARQ apply path).
    _stamped = _restamp_canonical_into_forms(generated, canon, facts)
    for _fid in _stamped:
        if _fid not in updated:
            updated.append(_fid)

    # Mirror apply_arq_answers_to_session's flag derivation so loss-history /
    # carrier-marketing answers actually move their pillars (not just a facts str).
    if canon == NO_LOSS_INDICATOR_FIELD:
        if _attested_true(new_val):
            flags["no_prior_losses"] = True
            flags_changed = True
        elif flags.get("no_prior_losses"):
            flags["no_prior_losses"] = False
            flags_changed = True
    elif canon == CARRIER_MARKETING_FIELD:
        _val_lower = new_val.lower()
        if _val_lower.startswith("other:"):
            _is_adverse = await _classify_other_reason_adverse(new_val[6:].strip())
        else:
            _is_adverse = _val_lower in _ADVERSE_CARRIER_REASONS
        flags["prior_carrier_adverse_action"] = _is_adverse
        flags_changed = True

    if field_name not in updated:
        updated.append(field_name)

    _update_payload = {"generated_forms": generated, "facts": facts}
    if flags_changed:
        _update_payload["flags"] = flags
    await upd_processing_session(processing_session_id, _update_payload)
    logger.info(
        f"Producer answer applied: session={processing_session_id} "
        f"field={field_name} canon={canon} forms={_stamped}"
    )
    return True, updated


def _clear_canonical_from_forms(generated: dict, canon: str) -> List[str]:
    """Blank every generated-form field that a producer's answer for `canon`
    previously stamped - the reverse of _restamp_canonical_into_forms's write.

    Reopening a resolved cross-form issue (SQS panel "Reopen") must clear the
    value everywhere it was applied, not just flip the status label - a field
    still showing the old answer while the panel claims the issue is open
    again is worse than useless, since it looks fixed when it isn't.

    Deliberately narrow: a field is blanked ONLY when it currently carries
    confidence "producer" or "client_arq" - i.e. only when THIS mechanism (or
    the equivalent client-answer path sharing the same restamp engine) is the
    one that wrote it. A value that came from document extraction or the LLM
    gap-fill is never touched, so reopening an inline fix can never erase real
    data the client's documents actually provided - it can only undo what a
    producer typed through this exact flow.
    """
    touched_forms: List[str] = []
    for fid, form_data in generated.items():
        schema = form_data.get("schema", {}) or {}
        if not schema:
            continue
        field_state = form_data.get("field_state") or form_data.get("mapped", {})
        conf = form_data.get("confidence") or {}
        cff = set(form_data.get("client_filled_fields", []))
        form_touched = False

        for schema_field in schema.keys():
            if _canonical_key(schema_field) != canon:
                continue
            if conf.get(schema_field) not in ("producer", "client_arq"):
                continue
            if str(field_state.get(schema_field) or "").strip() == "":
                continue
            field_state[schema_field] = ""
            conf.pop(schema_field, None)
            cff.discard(schema_field)
            form_touched = True

        if form_touched:
            form_data["field_state"] = field_state
            form_data["confidence"] = conf
            form_data["client_filled_fields"] = list(cff)
            form_data["_pdf_cache_hash"] = ""
            form_data["pdf_bytes"] = None
            touched_forms.append(fid)

    return touched_forms


async def clear_producer_answer_from_session(
    processing_session_id: str,
    field_name: str,
) -> Tuple[bool, List[str]]:
    """Undo a producer's inline answer for one canonical fact (SQS panel
    "Reopen" on a field-mode Cross-Form Validation issue).

    Reverse of apply_producer_answer_to_session: deletes the producer-
    provenance fact and blanks it on every form it was stamped into. Only acts
    when the CURRENT fact value's source is literally "producer" - if the fact
    is already blank, or its value came from extraction/gap-fill (the producer
    never actually answered this one), this is a no-op and returns (False, []),
    so a caller can safely call it speculatively for every fact a resolution
    covers without risking a value it doesn't own.

    Returns (ok, updated_form_ids).
    """
    from repositories.session_repository import (
        get_processing_session, upd_processing_session,
    )

    canon = _canonical_key(field_name)
    if not canon or canon.startswith("_"):
        return False, []

    try:
        proc_session = await get_processing_session(processing_session_id)
    except Exception as ex:
        logger.error(f"clear_producer_answer: cannot load session {processing_session_id}: {ex}")
        return False, []

    facts = dict(proc_session.get("facts", {}) or {})
    existing = facts.get(canon)
    existing_source = existing.get("source") if isinstance(existing, dict) else None
    if existing_source != "producer":
        return False, []

    generated = proc_session.get("generated_forms", {}) or {}
    del facts[canon]
    cleared = _clear_canonical_from_forms(generated, canon)

    await upd_processing_session(
        processing_session_id, {"generated_forms": generated, "facts": facts},
    )
    logger.info(
        f"Producer answer cleared: session={processing_session_id} "
        f"field={field_name} canon={canon} forms={cleared}"
    )
    return True, cleared


# ASYNC-SAFE
async def recalculate_session_scores(processing_session_id: str) -> dict:
    """Re-run scoring after ARQ answers are applied (Beta Report §6.2 / §8.2.7).

    Mirrors the producer field-edit recompute path (form_routes.update_pdf):
    re-evaluate field + cross-form stops, recompute per-form and package SQS,
    and persist — so missing-field status, related warnings, SQS, form
    readiness, and submission readiness all reflect the client's answers on the
    producer's next view. Pure-Python (no LLM, no PDF), safe to run inline.
    """
    from repositories.session_repository import (
        get_processing_session, upd_processing_session,
    )
    from services.sqs_service import (
        evaluate_stops, calculate_sqs, calculate_sqs_from_facts,
        calculate_package_sqs, _check_loss_run_insured_match, check_tier2,
        _extract_narrative_doc_text,
    )
    from services.extraction_service import _fv as _sqs_fv
    from services.cross_form_validator import (
        run_cross_form_validation, split_cross_form_issues,
    )

    try:
        proc = await get_processing_session(processing_session_id)
    except Exception as ex:
        logger.error(f"recalculate_session_scores: cannot load {processing_session_id}: {ex}")
        return {"ok": False}

    facts        = proc.get("facts", {}) or {}
    flags        = proc.get("flags", {}) or {}
    generated    = proc.get("generated_forms", {}) or {}
    selected_ids = proc.get("selected_form_ids") or list(generated.keys())
    # Recompute Tier-2 data completeness from the post-remediation facts rather than
    # reusing the extraction-time value stored on the session, so the per-form
    # scorers receive the current value (mirrors how package SQS recomputes it).
    # Remediation only adds facts, so this never lowers the score; falls back to the
    # stored value if recomputation fails for any reason.
    try:
        tier2_score, _ = check_tier2(facts, flags)
    except Exception:
        tier2_score = proc.get("tier2_score", 50)
    user_id      = proc.get("user_id")

    score_before = (proc.get("package_sqs") or {}).get("package_sqs_score")
    hard_before  = len(proc.get("hard_stops", []) or [])

    # §6.2: capture fill rate before recalculation so we can show before/after delta.
    _fill_before_rates = [
        fdata.get("sqs", {}).get("confidence_fill_rate")
        for fdata in generated.values()
        if isinstance(fdata, dict) and fdata.get("sqs", {}).get("confidence_fill_rate") is not None
    ]
    fill_rate_before = int(sum(_fill_before_rates) / len(_fill_before_rates)) if _fill_before_rates else None

    # Re-evaluate field-level + cross-form stops from the latest facts.
    re_hard, re_soft = evaluate_stops(facts, flags)
    triggered        = set(selected_ids) | set(generated.keys())
    cf_issues        = run_cross_form_validation(facts, flags, triggered)
    cf_hard, cf_soft, _cf_adv = split_cross_form_issues(cf_issues)
    hard_stops = list(re_hard) + list(cf_hard)
    soft_stops = list(re_soft) + list(cf_soft)

    seen, cf_deduped = set(), []
    for i in cf_issues:
        m = i.get("message", "") if isinstance(i, dict) else ""
        if m and m not in seen:
            seen.add(m)
            cf_deduped.append(i)

    # §6.3/§6.4: classified-doc presence + loss-run insured match so the
    # narrative/loss-history floors apply on the post-remediation recompute too.
    _docs        = proc.get("docs", []) or []
    _present     = {str(d.get("doc_type") or "").strip() for d in _docs if isinstance(d, dict) and not d.get("excluded")}
    _has_narr    = "narrative" in _present
    _has_loss    = "loss_run" in _present
    _loss_match  = _check_loss_run_insured_match(_docs, _sqs_fv(facts, "applicant_name"))
    _narr_text   = _extract_narrative_doc_text(_docs)

    if generated:
        for fid, fdata in generated.items():
            field_state = fdata.get("field_state") or fdata.get("mapped", {})
            confidence  = fdata.get("confidence", {})
            schema      = fdata.get("schema", {})
            try:
                fdata["sqs"] = calculate_sqs(
                    facts=facts, flags=flags, mapped_data=field_state,
                    form_schema=schema, selected_form_ids=selected_ids,
                    # SQS design: cross-form stops cap the PACKAGE only, never
                    # individual forms - per-form SQS uses field-level (global)
                    # stops only; cf_* still cap the package score below.
                    hard_stops=re_hard, soft_stops=re_soft,
                    tier2_score=tier2_score, form_id=fid,
                    confidence_dict=confidence, session_id=processing_session_id,
                    user_id=user_id, calculation_stage="arq_remediated",
                    has_narrative_doc=_has_narr, has_loss_run_doc=_has_loss,
                    loss_run_match=_loss_match, cross_issues_full=cf_deduped,
                    narrative_doc_text=_narr_text,
                )
            except Exception as ex:
                logger.error(f"recalc per-form SQS failed for {fid}: {ex}")
        sqs_list = [f.get("sqs") for f in generated.values() if f.get("sqs")]
    else:
        # Clarity/Lite path — no generated forms; score directly from facts.
        sqs_list = []
        for fid in selected_ids:
            try:
                sqs_list.append(calculate_sqs_from_facts(
                    facts=facts, flags=flags, selected_form_ids=selected_ids,
                    hard_stops=hard_stops, soft_stops=soft_stops,
                    tier2_score=tier2_score, form_id=fid,
                    session_id=processing_session_id, user_id=user_id,
                    calculation_stage="arq_remediated",
                    session_data=proc, cross_issues_full=cf_deduped,
                ))
            except Exception as ex:
                logger.error(f"recalc facts SQS failed for {fid}: {ex}")

    try:
        package_sqs = calculate_package_sqs(
            facts=facts, flags=flags, form_results=sqs_list,
            cross_issues=cf_deduped, hard_stops=hard_stops, soft_stops=soft_stops,
            session_data=proc, session_id=processing_session_id, user_id=user_id,
            calculation_stage="arq_remediated",
        )
    except Exception as ex:
        logger.error(f"recalc package SQS failed: {ex}", exc_info=True)
        package_sqs = proc.get("package_sqs")

    # ── Post-remediation issue diff (Figure 24) ──────────────────────────────
    # Compare the issue set BEFORE this recalculation against the one after, so
    # the producer sees what the client's answers actually fixed, worsened, or
    # left open - not just a score delta. Both sides are assembled identically
    # (persisted structured issues + injected cross-form issues, then
    # classify_stops applied) so the comparison is like-for-like and the
    # severities agree with the cards the producer sees on screen.
    #
    # structured_issues is REFRESHED here too. It was written once at extraction
    # time and never updated, so a hard stop the client had actually resolved
    # stayed in the list and kept rendering as a blocker - build_grouped_view
    # holds an issue at its original severity when its message appears in
    # neither final list. Only the entries this function recomputes are
    # replaced; doc-conflict / source-conflict / OCR / Tier-1 entries are left
    # untouched, because nothing here re-runs those detectors and so this
    # function cannot know whether they cleared.
    issue_diff = None
    fresh_structured = proc.get("structured_issues") or []
    try:
        from services.issue_registry import (
            build_grouped_view, build_structured_from_sources,
            diff_grouped_views, drop_confirmed_ocr_issues, replace_recomputed_issues,
        )
        from services.sqs_service import classify_stops

        _, _prior_hard, _prior_down = classify_stops(proc.get("hard_stops", []) or [], flags)
        prior_view = build_grouped_view(
            proc.get("structured_issues") or [],
            _prior_hard,
            (proc.get("soft_stops", []) or []) + _prior_down,
            cross_issues=proc.get("cross_issues_last") or [],
        )

        # Format the rebuilt field-level messages EXACTLY as extraction_pipeline
        # stored them. It appends a "Fix: ..." remediation hint to every
        # evaluate_stops message (plus a source annotation on address-format
        # ones) BEFORE writing structured_issues. Rebuilding them raw gives the
        # same underlying stop different text, hence a different issue_id, so
        # every cluster holding a field-level stop reported as "updated" on the
        # first recalculation even when nothing about it had changed - and the
        # producer silently lost the Fix hints from their issue list.
        from services.extraction_pipeline import _ensure_fix_hint, _enrich_stops_with_source
        _legacy_hard = _ensure_fix_hint(list(re_hard))
        _legacy_soft = _ensure_fix_hint(_enrich_stops_with_source(list(re_soft), _docs))

        fresh_structured = replace_recomputed_issues(
            proc.get("structured_issues") or [],
            build_structured_from_sources(legacy_hard=_legacy_hard, legacy_soft=_legacy_soft),
        )
        # An OCR "confirm this field" warning is satisfied the moment a human
        # supplies the value, and the questionnaire asks the client for exactly
        # those fields. Every other preserved source (doc / source conflicts)
        # describes two DOCUMENTS disagreeing, which an answer cannot settle, so
        # those stay untouched.
        fresh_structured = drop_confirmed_ocr_issues(
            fresh_structured,
            facts=facts,
            confirmed_keys=(proc.get("underwriting_confirmations") or {}).keys(),
        )
        # The view's stop lists must carry that same formatting or
        # build_grouped_view cannot match a structured issue to its final list,
        # which is what lets it honour classify_stops' hard->soft downgrades.
        # Display only - the persisted hard_stops/soft_stops that feed scoring
        # are left exactly as they were.
        _, _now_hard, _now_down = classify_stops(_legacy_hard + list(cf_hard), flags)
        current_view = build_grouped_view(
            fresh_structured, _now_hard, _legacy_soft + list(cf_soft) + _now_down,
            cross_issues=cf_deduped,
        )
        issue_diff = diff_grouped_views(prior_view, current_view)
    except Exception as _diff_ex:
        # Non-fatal: remediation must still complete. Falling back leaves
        # structured_issues exactly as it was, i.e. the prior behaviour.
        logger.error(f"ARQ recalc: issue diff failed (non-fatal): {_diff_ex}", exc_info=True)
        issue_diff = None
        fresh_structured = proc.get("structured_issues") or []

    _session_updates = {
        "generated_forms":   generated,
        "hard_stops":        hard_stops,
        "soft_stops":        soft_stops,
        "package_sqs":       package_sqs,
        "cross_issues_last": cf_deduped,
        "structured_issues": fresh_structured,
    }
    if issue_diff is not None:
        _session_updates["issue_diff_last"] = issue_diff
    await upd_processing_session(processing_session_id, _session_updates)

    # §6.2 / AC2: auto-resolve open recommendation audit records whose underlying
    # issue was cleared during this recalculation. After the SQS recompute, each
    # form's recommendations list contains only still-active issues with stable
    # rec_ids (e.g. "rec_applicant_name"). Any open audit record not in that set
    # means the client's answers resolved the gap — mark it resolved automatically
    # so the producer's recommendation panel stays in sync with the score.
    try:
        from services.audit_service import get_open_recommendations, mark_recommendation_resolved
        from services.sqs_service import SQS_MODEL_VERSION
        active_rec_ids: set = set()
        for _fdata in generated.values():
            for _rec in ((_fdata.get("sqs") or {}).get("recommendations") or []):
                if isinstance(_rec, dict) and _rec.get("rec_id"):
                    active_rec_ids.add(_rec["rec_id"])
        for _sqs_item in sqs_list:
            for _rec in (_sqs_item.get("recommendations") or []):
                if isinstance(_rec, dict) and _rec.get("rec_id"):
                    active_rec_ids.add(_rec["rec_id"])
        _open_recs = await get_open_recommendations(processing_session_id)
        _score_at_resolve = (package_sqs or {}).get("package_sqs_score") or 0
        _auto_resolved = 0
        for _orec in _open_recs:
            _rid = _orec.get("rec_id")
            # Only SQS-engine recommendations are auto-resolved here. Field-QA
            # ('fieldqa_') and field-mapping-integrity ('fieldmap_') advisory
            # rows are NOT SQS recs - they never appear in active_rec_ids, and
            # are managed by their own DELETE+rebuild refresh on generation/edit.
            # Auto-resolving them here would silently clear a live contamination
            # warning the moment a client answers any questionnaire item.
            if _rid and (_rid.startswith("fieldmap_") or _rid.startswith("fieldqa_")):
                continue
            if _rid and _rid not in active_rec_ids:
                await mark_recommendation_resolved(
                    session_id=processing_session_id,
                    rec_id=_rid,
                    sqs_score_at_action=_score_at_resolve,
                    model_version=SQS_MODEL_VERSION,
                )
                _auto_resolved += 1
        if _auto_resolved:
            logger.info(
                f"ARQ recalc {processing_session_id}: auto-resolved "
                f"{_auto_resolved} cleared recommendation(s)"
            )
    except Exception as _auto_resolve_ex:
        logger.error(f"ARQ recalc: auto-resolve step failed (non-fatal): {_auto_resolve_ex}")

    score_after = (package_sqs or {}).get("package_sqs_score")
    delta = (score_after - score_before) if (score_before is not None and score_after is not None) else 0

    # §6.2: capture fill rate after so we can compute delta for producer display.
    _fill_after_rates = [
        fdata.get("sqs", {}).get("confidence_fill_rate")
        for fdata in generated.values()
        if isinstance(fdata, dict) and fdata.get("sqs", {}).get("confidence_fill_rate") is not None
    ]
    fill_rate_after = int(sum(_fill_after_rates) / len(_fill_after_rates)) if _fill_after_rates else None
    fill_rate_delta = (fill_rate_after - fill_rate_before) if (fill_rate_before is not None and fill_rate_after is not None) else None

    # §6.2 — 7-state post-remediation status vocabulary
    _user_provided_fields = [
        f for fdata in generated.values()
        for f in (fdata.get("client_filled_fields") or [])
    ] if generated else []
    # Clarity/Lite path has no generated_forms, so client_filled_fields is never
    # populated. Derive user-provided fields from client_arq-sourced facts instead
    # so the user_provided_only / pending_validation statuses can still fire (§6.2).
    if not _user_provided_fields:
        _user_provided_fields = [
            k for k, v in facts.items()
            if isinstance(v, dict)
            and (v.get("source") in ("client_arq", "producer")
                 or v.get("confidence") == "client_arq")
        ]

    _has_conflicts = any(
        isinstance(i, dict) and i.get("type") in ("hard_stop", "soft_warning")
        for i in cf_deduped
    )
    # Structured detection: check recommendations for an explicit requires_doc flag first.
    # Keyword fallback retained for soft_stops that predate the structured approach.
    _DOC_REQUIRED_SOFT_PATTERNS: tuple = (
        "no loss history provided",
        "loss runs requested",
        "loss runs are",
        "provide loss",
        "narrative explanation recommended",
        "requires supporting",
        "supporting document",
        "attach loss",
        "attach narrative",
    )
    _needs_docs_from_recs = any(
        r.get("requires_doc")
        for fdata in (generated or {}).values()
        for r in ((fdata.get("sqs") or {}).get("recommendations") or [])
    )
    _needs_docs_from_stops = any(
        any(pat in str(s).lower() for pat in _DOC_REQUIRED_SOFT_PATTERNS)
        for s in soft_stops
    )
    _needs_docs = _needs_docs_from_recs or _needs_docs_from_stops

    if hard_before > 0 and len(hard_stops) == 0:
        status = "resolved"
    elif delta > 0:
        status = "improved"
    elif delta < 0:
        # Score decreased (e.g. client reveals prior losses). Map to pending_validation
        # which is the correct §6.2 spec vocab for "submitted, producer must review."
        status = "pending_validation"
    elif _user_provided_fields and delta == 0 and len(hard_stops) > 0:
        status = "pending_validation"
    elif _user_provided_fields and delta == 0 and not _has_conflicts and not _needs_docs:
        status = "user_provided_only"
    elif _has_conflicts:
        status = "conflicting_evidence_remains"
    elif _needs_docs:
        status = "requires_supporting_document"
    elif _user_provided_fields:
        status = "still_missing"
    else:
        status = "pending_validation"

    # Report DISTINCT remaining problems, not raw message strings. The
    # field-level engine (evaluate_stops) and cross_form_validator word the same
    # deficiency differently - incomplete property COPE is reported by both - so
    # len() counts one problem twice and disagrees with the clustered view the
    # producer actually sees. Fail-open to the raw counts: a reporting number
    # must never break the remediation path. `status` above deliberately keeps
    # using len(hard_stops) - "zero raw stops" and "zero distinct stops" are the
    # same condition, so its behaviour is unchanged.
    try:
        from services.issue_registry import count_distinct_issues
        _counts = count_distinct_issues(
            hard_stops=hard_stops, soft_stops=soft_stops,
            legacy_hard=re_hard, legacy_soft=re_soft, cross_issues=cf_deduped,
        )
        _hard_remaining, _soft_remaining = _counts["hard"], _counts["soft"]
    except Exception as _count_ex:
        logger.error(f"ARQ recalc: distinct issue count failed (non-fatal): {_count_ex}")
        _hard_remaining, _soft_remaining = len(hard_stops), len(soft_stops)

    logger.info(
        f"ARQ recalc {processing_session_id}: {score_before}->{score_after} "
        f"({status}); hard_stops {hard_before}->{len(hard_stops)} "
        f"(distinct {_hard_remaining})"
    )
    return {
        "ok":                   True,
        "score_before":         score_before,
        "score_after":          score_after,
        "delta":                delta,
        "status":               status,
        "hard_stops_remaining": _hard_remaining,
        "soft_stops_remaining": _soft_remaining,
        # Raw string counts preserved under explicit names so nothing that needs
        # the pre-dedup figure has to recompute it.
        "hard_stops_raw_count": len(hard_stops),
        "soft_stops_raw_count": len(soft_stops),
        "tier":                 (package_sqs or {}).get("tier"),
        "fill_rate_before":     fill_rate_before,
        "fill_rate_after":      fill_rate_after,
        "fill_rate_delta":      fill_rate_delta,
        # Which issues the answers resolved / worsened / left open. None when the
        # diff could not be computed, so the UI can tell "nothing changed" apart
        # from "we don't know".
        "issue_diff":           issue_diff,
    }


# ASYNC-SAFE
async def get_client_filled_fields(processing_session_id: str) -> List[str]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT answers FROM arq_sessions WHERE session_id=$1 AND status='submitted'",
            processing_session_id,
        )
    fields = []
    for row in rows:
        answers = row["answers"]
        if isinstance(answers, str):
            answers = json.loads(answers)
        if isinstance(answers, dict):
            fields.extend(answers.keys())
    return list(set(fields))


# ASYNC-SAFE
async def send_arq_reminder(arq_id: str, user: dict) -> bool:
    from services.email_service import send_arq_reminder_email

    arq = await get_arq_by_id(arq_id)
    if not arq or arq["status"] == "submitted":
        return False

    now     = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return False

    arq_link      = f"{FRONTEND_URL}/questionnaire/{arq['token']}"
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
        async with get_pool().acquire() as conn:
            await conn.execute(
                """UPDATE arq_sessions
                   SET reminder_sent=1,
                       reminder_count=COALESCE(reminder_count,0)+1,
                       last_reminder_at=$1
                   WHERE id=$2""",
                now_iso, arq_id,
            )

    return ok


# ASYNC-SAFE
async def create_arq_notification(arq_id: str, user_id: str, notif_type: str) -> None:
    notif_id = str(uuid.uuid4())
    now      = datetime.now(timezone.utc).isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO arq_notifications (id, arq_id, user_id, type, read_status, created_at) VALUES ($1,$2,$3,$4,0,$5)",
            notif_id, arq_id, user_id, notif_type, now,
        )


# ASYNC-SAFE
async def get_arq_notifications(user_id: str) -> List[dict]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM arq_notifications WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50",
            user_id,
        )
    return [dict(r) for r in rows]


# ASYNC-SAFE
async def mark_notifications_read(user_id: str) -> None:
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE arq_notifications SET read_status=1 WHERE user_id=$1",
            user_id,
        )
