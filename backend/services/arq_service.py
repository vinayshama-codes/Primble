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
from config.settings import FRONTEND_URL, LLM_MODEL
from services.question_classifier import (
    AUDIENCE_CLIENT,
    apply_default_selection,
    classify_question,
    decorate_questions,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Answer format validators
# ---------------------------------------------------------------------------

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
    "num_claims":               "How many insurance claims has your business filed in the last 3 to 5 years?",
    "loss_history_years":       "How many years of past insurance claims history are you able to provide?",
    # §6.4: lets the client attest "no prior losses" so the loss-history score can move.
    "loss_history_no_prior_losses_indicator": "To the best of your knowledge, has your business had NO insurance claims or losses in the past 5 years? (Answer 'Yes' to confirm no prior losses.)",
    "certificate_holder":       "Is there a company, landlord, or individual who needs written proof of your insurance? If yes, what is their name and address?",
    # Prior carrier / marketing context (Brent feedback: questionnaire more reliable than document extraction)
    "carrier_marketing_reason": "Why are you marketing this account at this time?",
    # Upcoming deadlines / urgency (Brent feedback: gives the underwriter context and supports readiness)
    "submission_urgency":       "Are there any upcoming deadlines or urgency we should know about?",
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
    "naics_code":               "This is a 6-digit industry code — leave blank if unsure, your agent can look it up, e.g. '238160' for roofing contractors.",
    "sic_code":                 "This is a 4-digit older industry code — leave blank if unsure, e.g. '1761' for roofing.",
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
    "num_claims":               "Enter the total number of insurance claims your business has filed in the past 3–5 years, e.g. '2'. Enter '0' if none.",
    "loss_history_years":       "Enter how many years of claims history you can provide documentation for, e.g. '5'.",
    "loss_history_no_prior_losses_indicator": "Answer 'Yes' only if there have been no insurance claims or losses. If you have had any claims, answer 'No' and provide your loss runs or claim count instead.",
    "certificate_holder":       "Enter the name and address of anyone who needs a certificate of insurance, e.g. 'ABC Property Management, 456 Oak Ave, Dallas TX 75201'.",
    "carrier_marketing_reason": "Select the primary reason for seeking coverage. This helps the underwriter understand the account background and is much more reliable than trying to extract this from documents.",
    "submission_urgency":       "Optional. Note any binding deadline, renewal date, or time-sensitivity, e.g. 'Need to bind by 07/01 for a new job'. Leave blank if none.",
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

_ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th", "8th", "9th", "10th"]

def _ordinal(n: int) -> str:
    return _ORDINALS[n - 1] if 1 <= n <= len(_ORDINALS) else f"{n}th"

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

    words = text.split()
    cleaned = []
    prev_word = None

    for word in words:
        if prev_word and word.lower() == prev_word.lower():
            continue
        cleaned.append(word)
        prev_word = word

    text = ' '.join(cleaned)
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


def _clean_answer(raw: str, field_name: str) -> Optional[str]:
    """Sanitize, validate format by field name, and return cleaned answer."""
    if raw is None:
        return None
    val = str(raw).strip()

    if not val or val.lower() in ("n/a", "na", "?", "unknown", "none", "null", "-", "--", "tbd", "unsure"):
        return None

    val = re.sub(r"<[^>]*>", "", val).strip()

    if "policy_number" in field_name.lower():
        val = re.sub(r"(?i)^policy\s*(number|#|no\.?|num\.?)[\s:]*", "", val).strip()
        val = re.sub(r'\b(policy)\s+\1\b', r'\1', val, flags=re.IGNORECASE)

    if len(val) > 500:
        val = val[:500].strip()

    if not val:
        return None

    fmt = _field_format_type(field_name)

    if fmt == "checkbox" or field_name.lower().find("indicator") >= 0:
        yes_values = ("yes", "true", "1", "y", "on", "checked")
        no_values  = ("no", "false", "0", "n", "off", "unchecked")

        if val.lower() in yes_values:
            return "Yes"
        elif val.lower() in no_values:
            return "No"
        else:
            logger.warning(f"ARQ answer rejected: field={field_name} expected=checkbox val={val!r}")
            return None

    if fmt == "email":
        if not _VAL_EMAIL_RE.match(val):
            logger.warning(f"ARQ answer rejected: field={field_name} expected=email val={val!r}")
            return None

    elif fmt == "phone":
        normalized = val.replace(" ", "").replace("-", "").replace(".", "").replace("(", "").replace(")", "")
        if not normalized.lstrip("+").isdigit() or len(normalized.lstrip("+")) < 7:
            logger.warning(f"ARQ answer rejected: field={field_name} expected=phone/fax val={val!r}")
            return None

    elif fmt == "date":
        if not _VAL_DATE_RE.match(val):
            logger.warning(f"ARQ answer rejected: field={field_name} expected=date val={val!r}")
            return None

    elif fmt == "number":
        clean_num = val.replace(" ", "").replace(",", "").replace("$", "")
        if not re.match(r"^\d+(\.\d+)?$", clean_num):
            logger.info(f"ARQ answer number format unusual: field={field_name} val={val!r}")

    return val


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
        allowed_125 = is_acord125_yellow_missing_field(acord125, field_name)
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
    """Canonical fact keys already filled in the package (for §8.2.4 suppression)."""
    from services.sqs_service import _fact_is_filled
    present = set()
    for k, v in (facts or {}).items():
        if _fact_is_filled(v):
            present.add(k)
    return present


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
) -> List[dict]:
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
        # Only spend an LLM humanization call on fields that will actually reach
        # the client. Raw/internal form fields get the no-LLM readable fallback
        # and live in the collapsed "Internal / Producer Review" panel — so the
        # ~1,700 obscure PDF fields no longer trigger a humanization pass.
        pre = classify_question(
            field_name, list(missing_fields[field_name]),
            is_curated_client=_is_curated_client_field(field_name),
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
            continue
        if canon and not canon.startswith("_"):
            seen_canon_keys.add(canon)

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
            "field_type":    field_type,
            "current_value": field_current_values.get(field_name, ""),
            "_group_label":  group_label,
            "_is_curated_client": _is_curated_client_field(field_name),
            "_canonical_key":     _canonical_key(field_name),
        })

    # §6.4: offer a "no prior losses" attestation when loss history is unestablished.
    _maybe_inject_no_loss_question(questions, facts, flags)
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

    # Curation layer (Beta Report §8): tag audience/priority/topic/score-impact,
    # then apply the curated default-selection policy.
    hard_stop_text = " ".join(str(s) for s in (hard_stops or []))
    decorate_questions(
        questions,
        present_fact_keys=_present_fact_keys(facts),
        hard_stop_text=hard_stop_text,
    )
    apply_default_selection(questions)

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
    # Umbrella underlying-schedule + follow-form evidence fallback (umbrella present
    # but evidence missing) - keeps the Clarity path in step with the form-aware ARQ.
    _maybe_inject_umbrella_evidence_questions(questions, facts, flags)

    hard_stop_text = " ".join(str(s) for s in (hard_stops or []))
    decorate_questions(
        questions,
        present_fact_keys=_present_fact_keys(facts),
        hard_stop_text=hard_stop_text,
    )
    apply_default_selection(questions)

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
    # the producer UI groups them and flags their hard-stop / SQS impact.
    decorate_questions(questions)
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
    for col in ("questions", "answers"):
        val = row.get(col)
        if isinstance(val, str):
            try:
                row[col] = json.loads(val)
            except Exception:
                pass
        elif val is None:
            row[col] = {} if col == "answers" else []
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
) -> Tuple[bool, str, List[str]]:
    arq = await get_arq_by_token(token)
    if not arq:
        return False, "ARQ session not found.", []

    now     = datetime.now(timezone.utc)
    expires = datetime.fromisoformat(arq["expires_at"].replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        return False, "This questionnaire link has expired.", []

    if arq["status"] == "submitted":
        return False, "This questionnaire has already been submitted.", []

    questions      = arq["questions"]
    cleaned        = {}
    updated_fields = []

    for q in questions:
        field_name = q["field_name"]
        raw_val    = raw_answers.get(field_name, "")
        if q.get("field_type") == "checkbox":
            cleaned_val = raw_val if raw_val in ("Yes", "No", "true", "false") else None
        else:
            cleaned_val = _clean_answer(raw_val, field_name)

        if cleaned_val is not None:
            cleaned[field_name] = cleaned_val
            updated_fields.append(field_name)

    now_iso = now.isoformat()
    async with get_pool().acquire() as conn:
        await conn.execute(
            "UPDATE arq_sessions SET answers=$1, status='submitted', submitted_at=$2 WHERE token=$3",
            json.dumps(cleaned), now_iso, token,
        )

    return True, "Answers submitted successfully.", updated_fields


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
        calculate_package_sqs, _check_loss_run_insured_match,
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
    tier2_score  = proc.get("tier2_score", 50)
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

    if generated:
        for fid, fdata in generated.items():
            field_state = fdata.get("field_state") or fdata.get("mapped", {})
            confidence  = fdata.get("confidence", {})
            schema      = fdata.get("schema", {})
            try:
                fdata["sqs"] = calculate_sqs(
                    facts=facts, flags=flags, mapped_data=field_state,
                    form_schema=schema, selected_form_ids=selected_ids,
                    hard_stops=hard_stops, soft_stops=soft_stops,
                    tier2_score=tier2_score, form_id=fid,
                    confidence_dict=confidence, session_id=processing_session_id,
                    user_id=user_id, calculation_stage="arq_remediated",
                    has_narrative_doc=_has_narr, has_loss_run_doc=_has_loss,
                    loss_run_match=_loss_match, cross_issues_full=cf_deduped,
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

    await upd_processing_session(processing_session_id, {
        "generated_forms":   generated,
        "hard_stops":        hard_stops,
        "soft_stops":        soft_stops,
        "package_sqs":       package_sqs,
        "cross_issues_last": cf_deduped,
    })

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
            and (v.get("source") == "client_arq" or v.get("confidence") == "client_arq")
        ]

    _has_conflicts = any(
        isinstance(i, dict) and i.get("type") == "hard_stop"
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
        for r in (fdata.get("recommendations") or [])
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
    else:
        status = "still_missing"  # user provided answers but score didn't move and no conflict

    logger.info(
        f"ARQ recalc {processing_session_id}: {score_before}->{score_after} "
        f"({status}); hard_stops {hard_before}->{len(hard_stops)}"
    )
    return {
        "ok":                   True,
        "score_before":         score_before,
        "score_after":          score_after,
        "delta":                delta,
        "status":               status,
        "hard_stops_remaining": len(hard_stops),
        "soft_stops_remaining": len(soft_stops),
        "tier":                 (package_sqs or {}).get("tier"),
        "fill_rate_before":     fill_rate_before,
        "fill_rate_after":      fill_rate_after,
        "fill_rate_delta":      fill_rate_delta,
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
