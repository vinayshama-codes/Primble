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
from typing import Optional, Callable

# ---------------------------------------------------------------------------
# Shared validators
# ---------------------------------------------------------------------------

def _is_date(v: str) -> bool:
    """MM/DD/YYYY or YYYY-MM-DD or M/D/YYYY."""
    return bool(re.match(
        r'^(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})$', v.strip()
    ))


def _is_currency(v: str) -> bool:
    """$1,000,000 or 1000000 or 1,000,000.00 etc."""
    return bool(re.match(
        r'^\$?[\d,]+(?:\.\d{1,2})?$', v.strip().replace(" ", "")
    ))


def _is_fein(v: str) -> bool:
    """XX-XXXXXXX (9 digits, with or without hyphen)."""
    clean = v.strip().replace("-", "")
    return clean.isdigit() and len(clean) == 9


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
    return clean.isdigit() and int(clean) >= 0


def _is_valuation(v: str) -> bool:
    return v.strip().upper() in {"RCV", "ACV"}


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
        "format_hint": "Full address including street, city, state, ZIP",
    },
    "physical_address": {
        "forms":       {"ACORD_125"},
        "question":    "Where is your business physically located? (Leave blank if same as mailing address)",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
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
        "validate":    lambda v: bool(re.match(r'^[\d\s\-\(\)\+\.]{7,20}$', v.strip())),
        "format_hint": "Phone number (7–20 digits, dashes, parentheses allowed)",
    },
    "contact_email": {
        "forms":       {"ACORD_125"},
        "question":    "What email address should we use to contact you?",
        "tier": 1, "required": False,
        "validate":    lambda v: bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v.strip())),
        "format_hint": "Valid email address (name@domain.com)",
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
        "validate":    lambda v: v.strip().upper() in {
            "LLC", "CORPORATION", "CORP", "SOLE PROPRIETOR", "SOLE PROPRIETORSHIP",
            "PARTNERSHIP", "LLP", "LP", "S-CORP", "S CORP", "C-CORP", "C CORP",
            "NON-PROFIT", "NONPROFIT", "TRUST", "OTHER",
        },
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
    "operations_description": {
        "forms":       {"ACORD_125"},
        "question":    "In a few sentences, what does your business do?",
        "tier": 2, "required": False,
        "validate":    lambda v: len(v.strip()) >= 10,
        "format_hint": "Text description (at least 10 characters)",
    },
    "prior_carrier": {
        "forms":       {"ACORD_125"},
        "question":    "Who provided your business insurance most recently? (If none, write 'None')",
        "tier": 2, "required": False,
        "validate":    None,
        "format_hint": None,
    },
    "naics_code": {
        "forms":       {"ACORD_125"},
        "question":    "Do you know your business's NAICS code?",
        "tier": None, "required": False,
        "validate":    lambda v: bool(re.match(r'^\d{2,6}$', v.strip())),
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
    "retro_date": {
        "forms":       {"ACORD_126"},
        "question":    "What was the original continuous coverage start date? (Required for claims-made policies)",
        "tier": None, "required": False,
        "validate":    _is_date,
        "format_hint": "Date in MM/DD/YYYY format",
    },

    # ── Commercial Auto — ACORD 127 ─────────────────────────────────────────
    "auto_liability_limit": {
        "forms":       {"ACORD_127"},
        "question":    "How much liability coverage are you looking for on your business vehicles?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount (e.g. $1,000,000)",
    },
    "auto_liability_structure": {
        "forms":       {"ACORD_127"},
        "question":    "Is your auto liability CSL or split limits?",
        "tier": None, "required": False,
        "validate":    lambda v: v.strip().upper() in {"CSL", "SPLIT", "SPLIT LIMITS", "COMBINED SINGLE LIMIT"},
        "format_hint": "CSL or Split Limits",
    },
    "auto_deductible_comp": {
        "forms":       {"ACORD_127"},
        "question":    "How much would you pay out of pocket for non-collision vehicle damage?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount",
    },
    "auto_deductible_collision": {
        "forms":       {"ACORD_127"},
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
        "forms":       {"ACORD_127"},
        "question":    "Which vehicle coverage symbols apply?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
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
    "auto_hired_nonowned": {
        "forms":       {"ACORD_127"},
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
        "validate":    lambda v: v.strip().lower() in {
            "annual", "quarterly", "monthly", "semi-annual", "biannual"
        },
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
    "employers_liability_limits": {
        "forms":       {"ACORD_131"},
        "question":    "What are your Employers Liability limits on your WC policy?",
        "tier": None, "required": False,
        "validate":    None,
        "format_hint": None,
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
        "validate":    lambda v: v.strip().upper() in {
            "FRAME", "WOOD FRAME", "JOISTED MASONRY", "MASONRY NON-COMBUSTIBLE",
            "NON-COMBUSTIBLE", "MODIFIED FIRE RESISTIVE", "FIRE RESISTIVE",
            "BRICK", "CONCRETE", "STEEL", "MIXED",
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
    "property_deductible_wind": {
        "forms":       {"ACORD_140"},
        "question":    "How much would you pay out of pocket for wind or hail damage?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount or percentage",
    },
    "property_deductible_earthquake": {
        "forms":       {"ACORD_140"},
        "question":    "How much would you pay out of pocket for earthquake damage?",
        "tier": None, "required": False,
        "validate":    _is_currency,
        "format_hint": "Dollar amount or percentage",
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