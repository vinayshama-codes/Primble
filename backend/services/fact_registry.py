# ---------------------------------------------------------------------------
# Unified fact registry — single source of truth for all fact metadata.
#
# Each entry shape:
#   {
#     "forms":    set of ACORD form IDs that consume this fact,
#     "question": plain-English ARQ question for the client,
#     "tier":     1 = hard gate (blocks submission if missing),
#                 2 = quality score (SQS narrative component),
#                 None = optional / enrichment only,
#     "required": True = hard block if missing (Tier 1 only),
#   }
#
# WHY tier + required live here:
#   check_tier1() and check_tier2() in sqs_service.py previously maintained
#   their own parallel hardcoded lists — a second source of truth that could
#   drift from this file. With these fields here, both functions can derive
#   their field sets from FACT_REGISTRY instead of duplicating definitions.
# ---------------------------------------------------------------------------

FACT_REGISTRY: dict[str, dict] = {

    # ── Business basics — ACORD 125 ─────────────────────────────────────────
    "applicant_name": {
        "forms":    {"ACORD_125"},
        "question": "What is the full legal name of your business?",
        "tier": 1, "required": True,
    },
    "dba_name": {
        "forms":    {"ACORD_125", "ACORD_186"},
        "question": "Does your business go by a different name than its legal name? If yes, what is it?",
        "tier": None, "required": False,
    },
    "mailing_address": {
        "forms":    {"ACORD_125"},
        "question": "What is your business mailing address? (Street, City, State, ZIP)",
        "tier": 1, "required": True,
    },
    "physical_address": {
        "forms":    {"ACORD_125"},
        "question": "Where is your business physically located? (Leave blank if same as mailing address)",
        "tier": None, "required": False,
    },
    "contact_name": {
        "forms":    {"ACORD_125"},
        "question": "Who is the main person we should contact about this insurance application?",
        "tier": 1, "required": False,   # contact is required as a group; any one of name/phone/email suffices
    },
    "contact_phone": {
        "forms":    {"ACORD_125"},
        "question": "What is the best phone number to reach you?",
        "tier": 1, "required": False,
    },
    "contact_email": {
        "forms":    {"ACORD_125"},
        "question": "What email address should we use to contact you?",
        "tier": 1, "required": False,
    },
    "fein": {
        "forms":    {"ACORD_125"},
        "question": "What is your business's federal tax ID number? (9-digit EIN assigned by the IRS)",
        "tier": 2, "required": False,
    },
    "entity_type": {
        "forms":    {"ACORD_125"},
        "question": "How is your business legally set up? (LLC, Corporation, Sole Proprietor, Partnership, etc.)",
        "tier": 2, "required": False,
    },
    "effective_date": {
        "forms":    {"ACORD_125"},
        "question": "What date would you like your insurance coverage to start? (MM/DD/YYYY)",
        "tier": 1, "required": True,
    },
    "expiration_date": {
        "forms":    {"ACORD_125"},
        "question": "What date would you like your insurance coverage to end? (MM/DD/YYYY)",
        "tier": None, "required": False,
    },
    "policy_number": {
        "forms":    {"ACORD_125"},
        "question": "Do you have a current or previous insurance policy number? If yes, please share it.",
        "tier": None, "required": False,
    },
    "lines_of_business": {
        "forms":    {"ACORD_125"},
        "question": "What types of insurance coverage are you looking for? (General Liability, Property, Auto, Workers Comp, etc.)",
        "tier": 1, "required": True,
    },
    "total_revenue": {
        "forms":    {"ACORD_125"},
        "question": "What is your business's total annual income or sales?",
        "tier": 2, "required": False,
    },
    "total_payroll": {
        "forms":    {"ACORD_125"},
        "question": "What is the total amount you pay your employees each year (gross payroll)?",
        "tier": 2, "required": False,
    },
    "num_employees": {
        "forms":    {"ACORD_125"},
        "question": "How many people does your business employ?",
        "tier": 2, "required": False,
    },
    "operations_description": {
        "forms":    {"ACORD_125"},
        "question": "In a few sentences, what does your business do? What products or services do you offer?",
        "tier": 2, "required": False,
    },
    "prior_carrier": {
        "forms":    {"ACORD_125"},
        "question": "Who provided your business insurance most recently? (If none, write 'None')",
        "tier": 2, "required": False,
    },
    "naics_code": {
        "forms":    {"ACORD_125"},
        "question": "Do you know your business's industry classification code (NAICS code)? If yes, please share it.",
        "tier": None, "required": False,
    },
    "sic_code": {
        "forms":    {"ACORD_125"},
        "question": "Do you know your business's SIC code (an older industry classification number)? If yes, please share it.",
        "tier": None, "required": False,
    },
    "years_in_business": {
        "forms":    {"ACORD_125"},
        "question": "How many years has your business been open?",
        "tier": 2, "required": False,
    },
    "is_renewal": {
        "forms":    {"ACORD_125"},
        "question": "Is this a renewal of an existing policy or a new submission?",
        "tier": None, "required": False,
    },
    "percent_subcontracted": {
        "forms":    {"ACORD_125", "ACORD_186"},
        "question": "What percentage of your total work is done by outside contractors rather than your own employees?",
        "tier": None, "required": False,
    },
    "num_claims": {
        "forms":    {"ACORD_125"},
        "question": "How many insurance claims has your business filed in the last 3 to 5 years?",
        "tier": 2, "required": False,
    },
    "loss_history_years": {
        "forms":    {"ACORD_125"},
        "question": "How many years of past insurance claims history are you able to provide?",
        "tier": None, "required": False,
    },
    "total_incurred": {
        "forms":    {"ACORD_125"},
        "question": "What is the total incurred amount (paid + reserves) across all claims in your loss history?",
        "tier": None, "required": False,
    },
    "total_paid": {
        "forms":    {"ACORD_125"},
        "question": "What is the total amount already paid out across all claims in your loss history?",
        "tier": None, "required": False,
    },
    "open_claims_count": {
        "forms":    {"ACORD_125"},
        "question": "How many insurance claims are currently open or still pending resolution?",
        "tier": None, "required": False,
    },
    "producer_name": {
        "forms":    {"ACORD_125"},
        "question": "What is the name of your insurance producer or agency?",
        "tier": 1, "required": False,   # skipped for dec_page uploads
    },
    "additional_named_insureds": {
        "forms":    {"ACORD_125", "ACORD_126"},
        "question": "Are there any additional named insureds (parent company, subsidiary, co-owner) who need to be listed on the policy? If yes, provide their names.",
        "tier": None, "required": False,
    },

    # ── General Liability — ACORD 126 ───────────────────────────────────────
    "gl_limits": {
        "forms":    {"ACORD_126"},
        "question": "How much liability coverage are you looking for? (e.g. $1,000,000 per incident / $2,000,000 total)",
        "tier": None, "required": False,
    },
    "gl_each_occurrence": {
        "forms":    {"ACORD_126"},
        "question": "What is the maximum amount you want covered for a single incident or accident?",
        "tier": None, "required": False,
    },
    "gl_aggregate": {
        "forms":    {"ACORD_126"},
        "question": "What is the total maximum amount you want covered across all claims in a year?",
        "tier": None, "required": False,
    },
    "gl_deductible": {
        "forms":    {"ACORD_126"},
        "question": "How much would you be willing to pay out of pocket before insurance kicks in (your GL deductible)?",
        "tier": None, "required": False,
    },
    "gl_form_type": {
        "forms":    {"ACORD_126"},
        "question": "Is your General Liability policy written on an 'occurrence' or 'claims-made' basis?",
        "tier": None, "required": False,
    },
    "gl_class_codes_by_location": {
        "forms":    {"ACORD_126"},
        "question": "What type of work does your business perform at each location? (Your agent uses this to classify your operations — describe your work and locations if unsure)",
        "tier": None, "required": False,
    },
    "retro_date": {
        "forms":    {"ACORD_126"},
        "question": "Has your current insurance policy been continuously active since a specific start date? If yes, what was that original start date? (Required for claims-made policies)",
        "tier": None, "required": False,
    },

    # ── Commercial Auto — ACORD 127 ─────────────────────────────────────────
    "auto_liability_limit": {
        "forms":    {"ACORD_127"},
        "question": "How much liability coverage are you looking for on your business vehicles?",
        "tier": None, "required": False,
    },
    "auto_liability_structure": {
        "forms":    {"ACORD_127"},
        "question": "Is your auto liability structured as a combined single limit (CSL) or split limits (BI per person / BI per accident / PD per accident)?",
        "tier": None, "required": False,
    },
    "auto_deductible_comp": {
        "forms":    {"ACORD_127"},
        "question": "How much would you pay out of pocket for non-collision vehicle damage (theft, weather, vandalism)?",
        "tier": None, "required": False,
    },
    "auto_deductible_collision": {
        "forms":    {"ACORD_127"},
        "question": "How much would you pay out of pocket if one of your business vehicles is in a collision?",
        "tier": None, "required": False,
    },
    "auto_vin_schedule": {
        "forms":    {"ACORD_127"},
        "question": "Please list your business vehicles: year, make, model, and VIN for each vehicle.",
        "tier": None, "required": False,
    },
    "auto_drivers": {
        "forms":    {"ACORD_127"},
        "question": "Who are the primary drivers of your business vehicles? (Names and approximate ages)",
        "tier": None, "required": False,
    },
    "auto_garaging_addresses": {
        "forms":    {"ACORD_127"},
        "question": "Where are your business vehicles primarily kept overnight? (Garaging address for each vehicle)",
        "tier": None, "required": False,
    },
    "auto_radius_of_operation": {
        "forms":    {"ACORD_127"},
        "question": "What is the typical radius of operation for your business vehicles? (Local, intermediate, or long-haul)",
        "tier": None, "required": False,
    },
    "auto_physical_damage_valuation": {
        "forms":    {"ACORD_127"},
        "question": "For physical damage coverage, how should vehicle value be determined? (Actual Cash Value, Agreed Value, or Stated Amount)",
        "tier": None, "required": False,
    },
    "auto_covered_symbols": {
        "forms":    {"ACORD_127"},
        "question": "Which vehicle coverage symbols apply? (e.g. Symbol 1 = any auto, Symbol 7 = scheduled autos — your agent can assist)",
        "tier": None, "required": False,
    },
    "auto_um_uim_limit": {
        "forms":    {"ACORD_127"},
        "question": "Do you want Uninsured/Underinsured Motorist (UM/UIM) coverage? If yes, what limit?",
        "tier": None, "required": False,
    },
    "auto_med_pay_limit": {
        "forms":    {"ACORD_127"},
        "question": "Do you want Medical Payments or PIP coverage on your auto policy? If yes, what limit?",
        "tier": None, "required": False,
    },
    "auto_hired_nonowned": {
        "forms":    {"ACORD_127"},
        "question": "Do your employees drive rented or personally-owned vehicles for business purposes? (Hired & Non-Owned Auto exposure)",
        "tier": None, "required": False,
    },

    # ── Workers Comp — ACORD 130 ────────────────────────────────────────────
    "wc_payroll": {
        "forms":    {"ACORD_130"},
        "question": "What is the total annual payroll for employees covered under Workers Compensation?",
        "tier": None, "required": False,
    },
    "wc_class_codes": {
        "forms":    {"ACORD_130"},
        "question": "What types of work do your employees perform? (Describe their job duties — your agent will assign the appropriate WC codes)",
        "tier": None, "required": False,
    },
    "wc_xmod": {
        "forms":    {"ACORD_130"},
        "question": "Has your business received a workers compensation experience modification factor (X-Mod) from your previous insurer? If yes, what is the number?",
        "tier": None, "required": False,
    },
    "wc_xmod_effective_date": {
        "forms":    {"ACORD_130"},
        "question": "What is the effective date of your workers compensation experience modification (X-Mod)?",
        "tier": None, "required": False,
    },
    "wc_officer_exclusions": {
        "forms":    {"ACORD_130"},
        "question": "Are there any business owners or officers who should NOT be covered under Workers Compensation? If yes, list their names.",
        "tier": None, "required": False,
    },
    "wc_monopolistic_payroll": {
        "forms":    {"ACORD_130"},
        "question": "Do you have employees in ND, OH, WA, or WY (monopolistic WC states)? If yes, provide the payroll amount for each state.",
        "tier": None, "required": False,
    },
    "wc_payroll_by_state": {
        "forms":    {"ACORD_130"},
        "question": "Please provide your payroll broken out by state and job classification (required for multi-state WC submissions).",
        "tier": None, "required": False,
    },
    "wc_prior_carrier": {
        "forms":    {"ACORD_130"},
        "question": "Who was your previous Workers Compensation insurance carrier?",
        "tier": None, "required": False,
    },
    "wc_payroll_period": {
        "forms":    {"ACORD_130"},
        "question": "What period does your Workers Compensation payroll figure cover? (e.g. annual, quarterly)",
        "tier": None, "required": False,
    },

    # ── Umbrella — ACORD 131 ────────────────────────────────────────────────
    "umbrella_limit": {
        "forms":    {"ACORD_131"},
        "question": "How much additional liability coverage would you like on top of your other policies? (e.g. $1,000,000 or $5,000,000)",
        "tier": None, "required": False,
    },
    "umbrella_sir": {
        "forms":    {"ACORD_131"},
        "question": "For this extra liability coverage, how much would you be willing to cover yourself before it kicks in (self-insured retention)?",
        "tier": None, "required": False,
    },
    "umbrella_attachment_point": {
        "forms":    {"ACORD_131"},
        "question": "At what underlying coverage limit does your umbrella policy attach? (Your agent can assist)",
        "tier": None, "required": False,
    },
    "underlying_policies": {
        "forms":    {"ACORD_131"},
        "question": "Please list your underlying liability policies (GL, Auto, WC) with their limits, carriers, and policy numbers.",
        "tier": None, "required": False,
    },
    "employers_liability_limits": {
        "forms":    {"ACORD_131"},
        "question": "What are your Employers Liability limits on your Workers Compensation policy? (Required when umbrella attaches over WC)",
        "tier": None, "required": False,
    },

    # ── Property — ACORD 140 ────────────────────────────────────────────────
    "property_building_value": {
        "forms":    {"ACORD_140"},
        "question": "If your building had to be completely rebuilt from scratch today, what would it cost? (Estimated rebuild value)",
        "tier": None, "required": False,
    },
    "property_bpp_value": {
        "forms":    {"ACORD_140"},
        "question": "What is the total value of your business equipment, furniture, inventory, and other contents inside the building?",
        "tier": None, "required": False,
    },
    "construction_type": {
        "forms":    {"ACORD_140"},
        "question": "What is your building mainly made of? (Wood frame, brick, concrete, steel, etc.)",
        "tier": None, "required": False,
    },
    "occupancy_type": {
        "forms":    {"ACORD_140"},
        "question": "What is your building used for on a day-to-day basis?",
        "tier": None, "required": False,
    },
    "year_built": {
        "forms":    {"ACORD_140"},
        "question": "What year was your building originally built?",
        "tier": None, "required": False,
    },
    "roof_year": {
        "forms":    {"ACORD_140"},
        "question": "What year was the roof last replaced or repaired?",
        "tier": None, "required": False,
    },
    "sprinkler_system": {
        "forms":    {"ACORD_140"},
        "question": "Does your building have a fire sprinkler system installed?",
        "tier": None, "required": False,
    },
    "fire_protection_class": {
        "forms":    {"ACORD_140"},
        "question": "What is your building's fire protection class? (1–10 scale, or ask your agent — based on distance to fire station/hydrant)",
        "tier": None, "required": False,
    },
    "distance_to_hydrant": {
        "forms":    {"ACORD_140"},
        "question": "How far is the nearest fire hydrant from your building (in feet)?",
        "tier": None, "required": False,
    },
    "fire_department_type": {
        "forms":    {"ACORD_140"},
        "question": "Is the nearest fire department volunteer or professional (paid)?",
        "tier": None, "required": False,
    },
    "valuation_method": {
        "forms":    {"ACORD_140"},
        "question": "If there is a loss, how would you like your property valued? Choose: Replacement Cost Value (RCV) or Actual Cash Value (ACV)",
        "tier": None, "required": False,
    },
    "coinsurance_percentage": {
        "forms":    {"ACORD_140"},
        "question": "Does your insurance require you to insure your property for a minimum percentage of its value? If yes, what percentage? (Your agent can clarify — typically 80% or 90%)",
        "tier": None, "required": False,
    },
    "business_income_limit": {
        "forms":    {"ACORD_140"},
        "question": "If your business had to close temporarily due to a covered loss, how much income would you need covered per month?",
        "tier": None, "required": False,
    },
    "period_of_restoration": {
        "forms":    {"ACORD_140"},
        "question": "If your business had to shut down due to damage, how many months do you estimate it would take to reopen?",
        "tier": None, "required": False,
    },
    "extra_expense_limit": {
        "forms":    {"ACORD_140"},
        "question": "Do you want Extra Expense coverage to help pay costs above normal operating expenses during a shutdown? If yes, what limit?",
        "tier": None, "required": False,
    },
    "property_deductible_aop": {
        "forms":    {"ACORD_140"},
        "question": "How much would you pay out of pocket for most property claims before insurance covers the rest? (All Other Perils deductible)",
        "tier": None, "required": False,
    },
    "property_deductible_wind": {
        "forms":    {"ACORD_140"},
        "question": "How much would you pay out of pocket for wind or hail damage claims?",
        "tier": None, "required": False,
    },
    "property_deductible_earthquake": {
        "forms":    {"ACORD_140"},
        "question": "How much would you pay out of pocket for earthquake damage claims?",
        "tier": None, "required": False,
    },
    "property_deductible_flood": {
        "forms":    {"ACORD_140"},
        "question": "How much would you pay out of pocket for flood damage claims?",
        "tier": None, "required": False,
    },
    "deductible_basis": {
        "forms":    {"ACORD_140"},
        "question": "How is your property deductible applied — per occurrence or per cause of loss?",
        "tier": None, "required": False,
    },
    "deductible_application": {
        "forms":    {"ACORD_140"},
        "question": "Does your deductible apply per building, per location, or per occurrence?",
        "tier": None, "required": False,
    },
    "agreed_value_endorsement": {
        "forms":    {"ACORD_140"},
        "question": "Does your property policy include an agreed value endorsement that suspends the coinsurance clause? (Yes or No)",
        "tier": None, "required": False,
    },
    "building_ITV_percentage": {
        "forms":    {"ACORD_140"},
        "question": "What percentage of your building's full replacement cost is it currently insured for? (e.g. 80%, 100%)",
        "tier": None, "required": False,
    },
    "mortgagee_name": {
        "forms":    {"ACORD_140"},
        "question": "Does a bank or lender have a financial interest in your building (a mortgage)? If yes, what is their name and address?",
        "tier": None, "required": False,
    },
    "locations": {
        "forms":    {"ACORD_125", "ACORD_140"},
        "question": "Please list all business locations to be covered. (Street address, City, State, ZIP for each)",
        "tier": None, "required": False,
    },
    "property_locations": {
        "forms":    {"ACORD_140"},
        "question": "Please confirm the physical addresses of all insured property locations.",
        "tier": None, "required": False,
    },

    # ── Contractors Supplement — ACORD 186 ──────────────────────────────────
    "contractor_type": {
        "forms":    {"ACORD_186"},
        "question": "What type of contracting work does your business perform? (General Contractor, Electrical, Plumbing, Roofing, etc.)",
        "tier": None, "required": False,
    },

    # ── Certificate — ACORD 25 ──────────────────────────────────────────────
    "certificate_holder": {
        "forms":    {"ACORD_25"},
        "question": "Is there a company, landlord, or individual who needs written proof of your insurance? If yes, what is their name and address?",
        "tier": None, "required": False,
    },

    # ── Risk transfer (all forms) ────────────────────────────────────────────
    # risk_transfer is stored as a nested dict in extraction — individual sub-fields
    # are surfaced here for ARQ question routing.
    "risk_transfer": {
        "forms":    {"ACORD_125", "ACORD_126"},
        "question": "Do any contracts or leases require you to name another party as an Additional Insured, add a Waiver of Subrogation, or use Primary & Non-Contributory wording?",
        "tier": None, "required": False,
    },
}

# ---------------------------------------------------------------------------
# Derived views — backwards-compatible aliases consumed by arq_service.py
# ---------------------------------------------------------------------------
_FIELD_QUESTION_MAP: dict[str, str] = {k: v["question"] for k, v in FACT_REGISTRY.items()}
_FIELD_TO_FORMS: dict[str, set]     = {k: v["forms"]    for k, v in FACT_REGISTRY.items()}

# ---------------------------------------------------------------------------
# Tier-derived sets — consumed by sqs_service.py to replace hardcoded lists
# ---------------------------------------------------------------------------

# All Tier 1 fields (hard gate — block submission if missing)
TIER1_REQUIRED_FIELDS: dict[str, str] = {
    k: v["question"]
    for k, v in FACT_REGISTRY.items()
    if v.get("tier") == 1 and v.get("required") is True
}

# Contact fields are Tier 1 but only one of the three needs to be present
TIER1_CONTACT_FIELDS: tuple = ("contact_name", "contact_phone", "contact_email")

# All Tier 2 fields (quality score — penalise SQS if missing, never block)
TIER2_SCORED_FIELDS: dict[str, str] = {
    k: v["question"]
    for k, v in FACT_REGISTRY.items()
    if v.get("tier") == 2
}