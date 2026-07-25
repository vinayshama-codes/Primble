import asyncio
import collections
import concurrent.futures
import hashlib
import json
import logging
import math
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple, Dict, Any

from config.settings import groq_chat, LLM_MODEL, LLM_PROVIDER
from services.normalization import normalize_date

# ASYNC-SAFE: shared executor for CPU-bound blocking work (tiktoken, sync helpers)
_EXECUTOR = ThreadPoolExecutor(max_workers=(os.cpu_count() or 2) * 2)

logger = logging.getLogger(__name__)

# ── Cache versioning (Fix 3) ──────────────────────────────────────────────────
# Bump BOTH whenever _EXTRACT_PROMPT_PREFIX or _EXTRACT_SCHEMA changes - this is
# what forces a stale cached extraction to be discarded instead of silently
# served forever. v10: added umbrella_effective_date/umbrella_expiration_date
# to the schema and a RULE 1 umbrella-policy-namespace instruction to the prompt.
PROMPT_VERSION = "v11"
SCHEMA_VERSION = "v11"

# ── Model context config ──────────────────────────────────────────────────────
_MODEL_CHUNK_CHARS: Dict[str, int] = {
    "claude": 28_000,
    "openai": 100_000,
}
ACTIVE_MODEL = LLM_PROVIDER  # driven by LLM_PROVIDER env var ("openai" or "claude")

_MAX_TOKENS_PER_DOC = int(os.getenv("ACORDLY_MAX_DOC_TOKENS", "500000"))
_CHARS_PER_TOKEN    = 4


def get_chunk_size(model: str = ACTIVE_MODEL) -> int:
    return _MODEL_CHUNK_CHARS.get(model, _MODEL_CHUNK_CHARS["openai"])


# ── Token estimation (tiktoken with char/4 fallback) ─────────────────────────
try:
    import tiktoken as _tiktoken
    _TK_ENC = _tiktoken.get_encoding("cl100k_base")
    logger.info("extraction_service: tiktoken loaded (cl100k_base)")
except Exception as _tk_err:
    _TK_ENC = None
    logger.warning(
        f"extraction_service: tiktoken unavailable ({_tk_err}) — using char/4 fallback"
    )


def estimate_tokens(text: str) -> int:
    if _TK_ENC is not None:
        try:
            return len(_TK_ENC.encode(text))
        except Exception:
            pass
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


# ── Extraction schema ─────────────────────────────────────────────────────────
_EXTRACT_SCHEMA = (
    '"facts": {\n'
    '  "producer_name": string or null, "applicant_name": string or null,\n'
    '  "dba_name": string or null, "mailing_address": string or null,\n'
    '  "physical_address": string or null, "contact_name": string or null,\n'
    '  "contact_phone": string or null, "contact_email": string or null,\n'
    '  "fein": string or null, "entity_type": string or null,\n'
    # CURRENT policy dates/number — NEVER mix with prior policy fields below
    '  "effective_date": string or null, "expiration_date": string or null,\n'
    '  "policy_number": string or null, "lines_of_business": [string],\n'
    '  "total_revenue": string or null, "total_payroll": string or null,\n'
    '  "num_employees": string or null, "locations": [string],\n'
    '  "operations_description": string or null,\n'
    # Narrative-only: high-level account/executive summary distinct from operations.
    # Populated ONLY for underwriting narrative / submission narrative docs; null elsewhere.
    '  "account_description": string or null,\n'
    # PRIOR/PREVIOUS policy — separate namespace, never overwrite current policy keys
    '  "prior_carrier": string or null,\n'
    '  "prior_policy_number": string or null,\n'
    '  "prior_effective_date": string or null,\n'
    '  "prior_expiration_date": string or null,\n'
    '  "naics_code": string or null, "sic_code": string or null,\n'
    '  "years_in_business": string or null,\n'
    '  "gl_limits": string or null, "gl_aggregate": string or null,\n'
    '  "gl_each_occurrence": string or null,\n'
    '  "gl_products_aggregate": string or null,\n'
    '  "gl_personal_advertising_injury": string or null,\n'
    '  "gl_fire_damage_limit": string or null,\n'
    '  "gl_medical_expense": string or null,\n'
    '  "gl_class_codes_by_location": [{"location": string, "codes": [string]}],\n'
    # GL schedule of hazards (ACORD 126): one object per class-code row. Capture
    # the RATING data SEPARATELY from the operations_description narrative.
    #   premium_basis    = exposure/premium basis: the code or word shown on the
    #                      form (P=Payroll, S=Gross Sales, A=Area, U=Unit,
    #                      C=Total Cost, M=Admissions, T=Per $1,000/other).
    #   exposure_amount  = the basis figure itself (payroll $ or gross sales $).
    #   subcontractor_pct= % of this class code's work that is subcontracted.
    # Emit [] when no class-code / payroll / gross-sales schedule is present; do
    # NOT synthesize rows from the prose operations description.
    '  "gl_class_code_schedule": [{"location": string or null, "class_code": string or null, "classification": string or null, "premium_basis": string or null, "exposure_amount": string or null, "territory": string or null, "subcontractor_pct": string or null}],\n'
    '  "gl_deductible": string or null, "gl_form_type": string or null,\n'
    '  "retro_date": string or null,\n'
    '  "carrier_name": string or null,\n'
    '  "carrier_naic": string or null,\n'
    '  "prior_carrier_naic": string or null,\n'
    '  "audit_period": string or null,\n'
    '  "billing_plan": string or null,\n'
    '  "wc_el_each_accident": string or null,\n'
    '  "wc_el_disease_each_employee": string or null,\n'
    '  "wc_el_disease_policy_limit": string or null,\n'
    '  "hired_auto_indicator": string or null,\n'
    '  "non_owned_auto_indicator": string or null,\n'
    '  "additional_named_insureds": [string],\n'
    '  "property_building_value": string or null, "property_bpp_value": string or null,\n'
    '  "construction_type": string or null, "occupancy_type": string or null,\n'
    '  "year_built": string or null, "roof_year": string or null,\n'
    '  "sprinkler_system": string or null, "fire_protection_class": string or null,\n'
    '  "valuation_method": "RCV"|"ACV"|null, "coinsurance_percentage": string or null,\n'
    '  "business_income_limit": string or null, "period_of_restoration": string or null,\n'
    '  "property_deductible_aop": string or null, "property_deductible_wind": string or null,\n'
    '  "property_deductible_earthquake": string or null, "property_deductible_flood": string or null,\n'
    '  "mortgagee_name": string or null, "auto_liability_limit": string or null,\n'
    '  "auto_liability_structure": string or null, "auto_deductible_comp": string or null,\n'
    '  "auto_deductible_collision": string or null,\n'
    # Vehicle schedule: one object per vehicle row
    '  "auto_vin_schedule": [{"year": string, "make": string, "model": string, "vin": string, "body_type": string or null, "gvw": string or null}],\n'
    '  "auto_garaging_addresses": [string],\n'
    # WC class codes: one object per class code row
    '  "wc_payroll": string or null, "wc_payroll_by_state": {}, "wc_class_codes": [{"code": string, "description": string, "state": string or null, "payroll": string or null, "rate": string or null}],\n'
    '  "wc_xmod": string or null, "wc_xmod_effective_date": string or null,\n'
    '  "wc_officer_exclusions": string or null,\n'
    '  "wc_monopolistic_payroll": {"state": "amount"},\n'
    '  "umbrella_limit": string or null, "umbrella_sir": string or null,\n'
    '  "umbrella_attachment_point": string or null,\n'
    '  "umbrella_effective_date": string or null, "umbrella_expiration_date": string or null,\n'
    '  "underlying_policies": [{"line": string, "limit": string, "carrier": string, "policy_no": string}],\n'
    '  "schedule_of_underlying_insurance": string or null,\n'
    '  "umbrella_follow_form": string or null,\n'
    '  "employers_liability_limits": string or null,\n'
    '  "percent_subcontracted": string or null,\n'
    '  "contractor_type": string or null, "num_claims": string or null,\n'
    '  "loss_history_years": string or null, "certificate_holder": string or null,\n'
    '  "is_renewal": string or null,\n'
    '  "wc_prior_carrier": string or null,\n'
    '  "wc_payroll_period": string or null,\n'
    # Driver schedule: one object per driver row
    '  "auto_drivers": [{"name": string, "dob": string or null, "license_number": string or null, "license_state": string or null, "hire_date": string or null, "experience_years": string or null, "vehicle_use_percent": string or null}],\n'
    '  "auto_radius_of_operation": string or null,\n'
    '  "auto_physical_damage_valuation": string or null,\n'
    '  "auto_covered_symbols": [int],\n'
    '  "auto_um_uim_limit": string or null,\n'
    '  "auto_med_pay_limit": string or null,\n'
    '  "auto_hired_nonowned": string or null,\n'
    '  "distance_to_hydrant": string or null,\n'
    '  "fire_department_type": string or null,\n'
    '  "extra_expense_limit": string or null,\n'
    '  "deductible_basis": string or null,\n'
    '  "agreed_value_endorsement": boolean,\n'
    '  "deductible_application": string or null,\n'
    '  "building_ITV_percentage": string or null,\n'
    '  "total_incurred": string or null,\n'
    '  "total_paid": string or null,\n'
    '  "open_claims_count": string or null,\n'
    # Property location schedule: one object per DISTINCT physical location.
    # Sub-fields mirror ACORD's own per-location premises data (occupancy,
    # ownership, employee counts, revenue) so multi-location submissions are
    # captured with real per-location facts instead of one company-wide total.
    '  "property_locations": [{"address": string, "ownership": string or null (owner, tenant, or a short description '
    'of the actual interest if neither, e.g. "licensee"), '
    '"inside_city_limits": boolean or null, "full_time_employees": string or null, "part_time_employees": string or null, '
    '"annual_revenue": string or null, "occupied_area": string or null, "open_to_public_area": string or null, '
    '"total_building_area": string or null (the TOTAL square footage of the building, NOT the same as occupied_area - '
    'leave null if the document does not state the whole building\'s size), '
    '"operations_description": string or null, "building_value": string or null, "bpp_value": string or null, '
    '"construction_type": string or null, "year_built": string or null}],\n'
    '  "loss_run_age_days": string or null,\n'
    # Loss-run dating: the "valued as of" / valuation / evaluation date printed on
    # the loss run, and the earliest experience-period (policy-period) start date
    # the loss runs cover. Used to compute recency and years deterministically.
    '  "loss_run_valuation_date": string or null, "loss_run_period_start": string or null,\n'
    '  "loss_run_period_end": string or null,\n'
    # Loss-run availability status: set to "pending" or "requested" when the submission
    # explicitly mentions loss runs have been requested but not yet received.
    # Null when loss run data is actually present or when no loss runs are mentioned.
    '  "loss_run_status": "pending"|"requested"|null,\n'
    # risk_transfer sub-fields are independent facts - do not let one leak into
    # another. specific_wording_requirements is ONLY for an actual CONTRACTUAL/
    # ENDORSEMENT WORDING clause quoted or closely paraphrased from the document
    # (e.g. "certificate holder must be endorsed as additional insured", "waiver
    # applies only where required by written contract") - never a restatement or
    # summary of the OTHER risk_transfer booleans/names above (do not write
    # something like "waiver required: yes; AI required: no" into this field -
    # those facts already have their own keys). Leave null when the document
    # contains no such wording clause, even if other risk_transfer sub-fields
    # are populated.
    '  "risk_transfer": {\n'
    '    "additional_insured_required": boolean,\n'
    '    "additional_insured_names": [string],\n'
    '    "primary_noncontributory_required": boolean,\n'
    '    "waiver_of_subrogation_required": boolean,\n'
    '    "certificate_holder_name": string or null,\n'
    '    "loss_payee_name": string or null,\n'
    '    "mortgagee_name": string or null,\n'
    '    "specific_wording_requirements": string or null (an actual quoted/paraphrased '
    'contractual wording or endorsement REQUIREMENT clause only - never a summary of the '
    'other risk_transfer fields; null if no such clause is stated)\n'
    '  },\n'
    '  "builders_risk_project_address": string or null,\n'
    '  "builders_risk_project_cost": string or null,\n'
    '  "builders_risk_completion_date": string or null,\n'
    '  "builders_risk_construction_type": string or null,\n'
    '  "builders_risk_owner_name": string or null,\n'
    '  "builders_risk_contractor_name": string or null,\n'
    '  "builders_risk_insured_interest": string or null,\n'
    '  "crime_limit": string or null,\n'
    '  "crime_deductible": string or null,\n'
    '  "crime_employee_count": string or null,\n'
    '  "crime_locations_count": string or null,\n'
    '  "cyber_limit": string or null,\n'
    '  "cyber_retention": string or null,\n'
    '  "cyber_prior_incidents": string or null,\n'
    '  "cyber_controls_mfa": boolean,\n'
    '  "cyber_controls_backups": boolean,\n'
    '  "cyber_pii_records_count": string or null,\n'
    '  "cyber_third_party_vendors": string or null,\n'
    '  "inland_marine_total_value": string or null,\n'
    '  "inland_marine_transit_limit": string or null,\n'
    '  "inland_marine_items": [{"description": string, "value": string or null, "serial_number": string or null}],\n'
    '  "contractor_residential_pct": string or null,\n'
    '  "contractor_commercial_pct": string or null,\n'
    '  "contractor_high_hazard_ops": [string],\n'
    '  "contractor_license_number": string or null,\n'
    '  "certificate_holder_address": string or null,\n'
    '  "certificate_description_of_operations": string or null,\n'
    '  "loss_payee_name": string or null,\n'
    '  "additional_remarks_text": string or null,\n'
    # ── Loss history schedule (ACORD 125, 186) ────────────────────────────
    '  "loss_history": [{"date": string or null, "claim_date": string or null, '
    '"description": string or null, "amount": string or null, "paid": string or null, '
    '"reserved_amount": string or null, "claim_number": string or null, '
    '"line_of_business": string or null, "open": boolean, '
    '"open_code": "O" or "C" or null, "subrogation_code": "Y" or "N" or null}],\n'
    # ── Prior coverage by line (ACORD 125/126/127/130) ───────────────────
    '  "prior_coverage_by_line": [{"line": string, "carrier": string or null, '
    '"policy_no": string or null, "effective": string or null, '
    '"expiration": string or null, "premium": string or null}],\n'
    # ── WC officers / owners (ACORD 130) ────────────────────────────────
    '  "wc_officers": [{"name": string, "title": string or null, '
    '"ownership_pct": string or null, "include": boolean, "exclude": boolean, '
    '"state": string or null}],\n'
    # ── Garage / Dealers (ACORD 138 CA/CO) ──────────────────────────────
    '  "garage_operations_type": string or null,\n'
    '  "garage_liability_limit": string or null,\n'
    '  "garage_deductible": string or null,\n'
    '  "garagekeeper_liability_limit": string or null,\n'
    '  "garagekeeper_comp_deductible": string or null,\n'
    '  "garagekeeper_coll_deductible": string or null,\n'
    '  "auto_dealers_inventory_value": string or null,\n'
    # ── WC Application (ACORD 130) ────────────────────────────────────────
    '  "wc_description_of_operations": string or null,\n'
    '  "state_of_operations": string or null\n'
    '},\n\n'
    '"flags": {\n'
    '  "is_commercial_policy": boolean, "has_general_liability": boolean,\n'
    '  "has_property_coverage": boolean, "has_auto_coverage": boolean,\n'
    '  "has_workers_comp": boolean, "has_umbrella": boolean,\n'
    '  "has_multiple_locations": boolean, "has_loss_history": boolean,\n'
    '  "asserts_no_known_losses": boolean,\n'
    '  "is_contractor": boolean, "has_certificate_request": boolean,\n'
    '  "is_certificate_doc": boolean, "gl_is_claims_made": boolean,\n'
    '  "auto_has_physical_damage": boolean, "auto_split_limits": boolean,\n'
    '  "auto_has_hired_nonowned": boolean, "auto_has_um_uim": boolean,\n'
    '  "wc_multi_state": boolean, "wc_has_monopolistic_state": boolean,\n'
    '  "property_has_bi_coverage": boolean, "property_has_peril_deductibles": boolean,\n'
    '  "has_additional_insured_requirement": boolean,\n'
    '  "has_waiver_of_subrogation": boolean,\n'
    '  "has_primary_noncontributory": boolean,\n'
    '  "has_builders_risk": boolean,\n'
    '  "has_inland_marine": boolean,\n'
    '  "has_crime": boolean,\n'
    '  "has_cyber": boolean,\n'
    '  "has_commercial_auto": boolean,\n'
    '  "has_auto_liability": boolean,\n'
    '  "has_truckers_coverage": boolean,\n'
    '  "has_motor_carrier_coverage": boolean,\n'
    '  "has_garage_operations": boolean,\n'
    '  "has_auto_dealer_exposure": boolean,\n'
    '  "has_garagekeepers_coverage": boolean,\n'
    '  "has_garage_coverage": boolean,\n'
    '  "has_dealers_coverage": boolean,\n'
    '  "has_garage_liability": boolean,\n'
    '  "has_garage_keepers": boolean,\n'
    '  "narrative_components": {\n'
    '    "account_overview":    {"present": boolean, "evidence": string or null},\n'
    '    "operations":          {"present": boolean, "evidence": string or null},\n'
    '    "years_in_business":   {"present": boolean, "evidence": string or null},\n'
    '    "management":          {"present": boolean, "evidence": string or null},\n'
    '    "risk_controls":       {"present": boolean, "evidence": string or null},\n'
    '    "loss_history":        {"present": boolean, "evidence": string or null},\n'
    '    "coverage_discussion": {"present": boolean, "evidence": string or null},\n'
    '    "carrier_market":      {"present": boolean, "evidence": string or null},\n'
    '    "location_exposure":   {"present": boolean, "evidence": string or null},\n'
    '    "employee_practices":  {"present": boolean, "evidence": string or null},\n'
    '    "growth_trends":       {"present": boolean, "evidence": string or null},\n'
    '    "target_markets":      {"present": boolean, "evidence": string or null}\n'
    '  }\n'
    '}'
)

# Full verbose prompt — used for Claude / OpenAI paths where token budget is ample.
_EXTRACT_PROMPT_PREFIX = (
    'You are a carrier-grade insurance document analyzer with deep expertise in commercial '
    'insurance policies, declarations pages, ACORD forms, certificates, loss runs, and '
    'endorsements. Your job is to read every word of the document and extract EVERY visible '
    'data point — leave nothing behind.\n\n'
    'RULE 1 — Policy namespace separation:\n'
    '  • Current/active policy  → policy_number, effective_date, expiration_date\n'
    '  • Prior/previous policy  → prior_policy_number, prior_effective_date, prior_expiration_date, prior_carrier\n'
    '  • Umbrella/excess policy → umbrella_effective_date, umbrella_expiration_date\n'
    '  NEVER mix these groups. If a document shows "Prior Policy: XYZ / 01/01/2023–01/01/2024" '
    'and "Current Policy: ABC / 01/01/2024–01/01/2025", both sets must appear in their correct keys. '
    'An umbrella/excess policy commonly runs its OWN separate effective/expiration period, distinct '
    'from the underlying GL/Auto/WC policy period — if the document states an umbrella-specific '
    'policy period (e.g. "Umbrella Policy Effective Date: 07/15/2025"), it belongs in '
    'umbrella_effective_date/umbrella_expiration_date even when it differs from effective_date/'
    'expiration_date. Do not collapse it into the current-policy dates just because both are present '
    'in the same document — a differing umbrella period is a real, common attachment scenario, not '
    'an error to normalize away.\n\n'
    'RULE 2 — Schedule tables: output ONE JSON object per row.\n'
    '  • Vehicle schedule      → one entry per vehicle in auto_vin_schedule\n'
    '  • WC class code table   → one entry per class code row in wc_class_codes\n'
    '  • Driver schedule       → one entry per driver in auto_drivers\n'
    '  • Property locations    → one entry per DISTINCT physical location in property_locations. '
    'The SAME address printed on multiple pages (dec page, attached schedule, certificate) is still '
    'ONE location — do not emit a duplicate entry for a repeated mention of the same address.\n\n'
    'RULE 3 — Never hallucinate. If a value is not visible in the document, set the field to null '
    '(or [] for list fields). Do not invent or infer values that are not explicitly stated.\n\n'
    'RULE 4 — Extract ALL financial figures exactly as printed: limits, premiums, payrolls, '
    'deductibles, values. Include currency symbols and formatting as-is.\n\n'
    'RULE 5 — For addresses: extract the full address string including city, state, ZIP.\n\n'
    'RULE 6 — Flag definitions. Judge each boolean flag by the MEANING of the document, not the mere presence of exact keywords - the example terms listed are illustrative, not an exhaustive checklist, so set a flag true for clear equivalents and paraphrases too (e.g. "ransomware incident response" or "we hold customer health and card data" implies cyber even without the word "cyber"). This does NOT relax any "Do NOT set true" restriction below - those guards still apply in full. Criteria:\n'
    '  is_commercial_policy: true if document is a commercial insurance policy, application, dec page, certificate, or quote (not personal lines).\n'
    '  has_general_liability: true if document mentions "General Liability", "GL", "premises/operations", "products/completed operations", "personal and advertising injury", GL limits, or GL premiums.\n'
    '  has_property_coverage: true if document explicitly lists a building limit or BPP (business personal property) value, commercial property premium, or COPE data (construction type, year built, occupancy, protection class) for a covered location. Do NOT set true based on mailing addresses alone, certificate holder addresses, or GL-only premises descriptions.\n'
    '  has_auto_coverage: true if document mentions business auto, commercial auto, vehicle schedules, VINs, auto liability limits, or fleet coverage as a distinct coverage line or policy section. Do NOT set true based solely on "hired/non-owned auto" appearing as a GL endorsement line — that alone is not a separate commercial auto policy.\n'
    '  has_workers_comp: true if document mentions workers compensation, WC, payroll by class code, experience modification factor, employers liability, or WC class codes.\n'
    '  has_umbrella: true if the document explicitly shows an umbrella or excess liability LIMIT or PREMIUM (e.g. "$2M Umbrella", "Excess Liability – $5,000,000") for coverage above a primary GL or auto policy. Do NOT set true merely because the words "excess", "limits", "attachment point", or "SIR" appear without a distinct umbrella/excess policy section or stated dollar amount.\n'
    '  has_multiple_locations: true if document lists 2 or more distinct insured property addresses or locations.\n'
    '  has_loss_history: true if document contains a loss run, claims history table, prior claims, loss amounts, or any mention of paid/incurred/open claims.\n'
    '  asserts_no_known_losses: true ONLY if the document affirmatively states the insured has had NO prior or known losses/claims — judge this by MEANING, not exact wording. Set true for any clear paraphrase, e.g. "no known losses", "no prior losses", "loss-free", "claims-free", "clean loss history", "favorable loss experience with no claims", "no reported claims in the past N years", "the insured reports no losses". Set FALSE when the document merely discusses, lists, or summarizes losses/claims, when any actual claim (paid, incurred, reserved, or open) appears, or when loss history is simply absent/not mentioned. This is a no-loss ASSERTION, not the presence of loss data.\n'
    '  is_contractor: true only if the named INSURED\'s PRIMARY BUSINESS is a construction or installation contracting trade (general contractor, roofing contractor, electrical, plumbing, excavation, demolition contractor, etc.). Do NOT set true if construction trades are only mentioned in loss history, claims descriptions, operations of a third party, or as endorsement requirements listed for certificate holders.\n'
    '  has_certificate_request: true if document contains language requesting issuance of a certificate of insurance, lists a certificate holder, or shows "certificate required".\n'
    '  is_certificate_doc: true if the document IS itself an ACORD 25 Certificate of Liability Insurance or ACORD 28 Evidence of Property — identifiable by "Certificate of Liability Insurance" or "Evidence of Commercial Property Insurance" as the document title.\n'
    '  gl_is_claims_made: true if GL coverage is written on a claims-made basis (document shows "Claims Made" selected or "Retro Date" present for GL).\n'
    '  auto_has_physical_damage: true if document shows comprehensive and/or collision coverage for autos.\n'
    '  auto_split_limits: true if auto liability is expressed as split limits (BI per person / BI per accident / PD per accident) rather than a combined single limit (CSL).\n'
    '  auto_has_hired_nonowned: true if document mentions "hired auto", "non-owned auto", "HNOA", or hired and non-owned coverage.\n'
    '  auto_has_um_uim: true if document mentions uninsured motorist (UM) or underinsured motorist (UIM) coverage.\n'
    '  wc_multi_state: true if the insured has payroll or employees in more than one U.S. state.\n'
    '  wc_has_monopolistic_state: true if any WC payroll or employee location is in North Dakota (ND), Ohio (OH), Washington (WA), or Wyoming (WY).\n'
    '  property_has_bi_coverage: true if document mentions business income, business interruption, BI limit, extra expense, or period of restoration.\n'
    '  property_has_peril_deductibles: true if document shows cause-specific deductibles such as wind/hail deductible, earthquake deductible, or flood deductible.\n'
    '  has_additional_insured_requirement: true if document shows "Additional Insured" endorsement, AI requirement, or any party listed as an additional insured.\n'
    '  has_waiver_of_subrogation: true if document mentions "Waiver of Subrogation" or "WOS".\n'
    '  has_primary_noncontributory: true if document mentions "Primary and Non-Contributory" or "PNC" coverage requirement.\n'
    '  has_builders_risk: true if the document explicitly covers property that is CURRENTLY UNDER CONSTRUCTION — identified by a Builders Risk or Course of Construction section listing a project address, construction value, or completion date for a specific active project. Do NOT set true for a general contractor\'s GL/WC submission, for completed property coverage, or when "construction" appears only in the insured\'s trade description.\n'
    '  has_inland_marine: true if the document explicitly includes a distinct inland marine coverage line, floater policy, or scheduled equipment endorsement WITH stated limits or values (e.g. contractor\'s equipment schedule with item values, motor truck cargo with a per-load limit, installation floater). Do NOT set true if equipment or cargo is mentioned incidentally in operations descriptions or loss history without stated inland marine limits.\n'
    '  has_crime: true if document mentions crime coverage, employee dishonesty, money and securities, forgery, fidelity bond, ERISA bond, or commercial crime policy.\n'
    '  has_cyber: true if document mentions cyber liability, data breach, network security, ransomware, cyber insurance, PCI, PHI, or cyber/privacy coverage.\n'
    '  has_commercial_auto: true if document shows a commercial auto policy, business auto coverage symbol, or fleet policy.\n'
    '  has_auto_liability: true if document shows auto liability limits (CSL or split limits) on a commercial auto policy.\n'
    '  has_truckers_coverage: true if document mentions truckers coverage, motor truckers, long-haul trucking, or ICC/MC authority numbers.\n'
    '  has_motor_carrier_coverage: true if document mentions motor carrier, MCS-90 endorsement, or interstate transport coverage.\n'
    '  has_garage_operations: true if document mentions garage operations, service garage, repair shop, or autos left for service or safekeeping.\n'
    '  has_auto_dealer_exposure: true if document mentions auto dealership, dealer operations, dealer plates, or new/used vehicle inventory.\n'
    '  has_garagekeepers_coverage: true if document mentions garagekeepers coverage, garagekeepers legal liability, or coverage for customer vehicles.\n'
    '  has_garage_coverage: true if document shows garage liability coverage covering auto dealer and service operations.\n'
    '  has_dealers_coverage: true if document mentions dealers physical damage, dealer inventory, or floorplan coverage.\n'
    '  has_garage_liability: true if document shows a garage liability limit (applies to auto dealers and service shops).\n'
    '  has_garage_keepers: true if document mentions garagekeepers or coverage for vehicles in the insured\'s custody.\n\n'
    'RULE 7 — loss_history fields: For each loss history entry, populate all available sub-fields:\n'
    '  date: occurrence/loss date. claim_date: date claim was filed or reported (may differ from occurrence date).\n'
    '  description: brief description of the loss. amount: total incurred (paid + reserved).\n'
    '  paid: amount already paid to date. reserved_amount: reserves held but not yet paid.\n'
    '  claim_number: insurer claim reference number. line_of_business: line of insurance the claim falls under (e.g. "GL", "Auto", "Property").\n'
    '  open: true if the claim is still open/pending, false if closed. open_code: "O" for open, "C" for closed.\n'
    '  subrogation_code: "Y" if subrogation is being pursued, "N" if not applicable or waived.\n\n'
    'RULE 8 — state_of_operations: Set this to the two-letter US state code (e.g. "CA", "CO", "TX") where the insured\'s '
    'primary operations are located. Determine this from the mailing address, physical address, garaging address, '
    'or any explicit state reference in the document. If multiple states appear, use the state in the mailing or '
    'physical address of the named insured. Return null only if no state can be determined.\n\n'
    'RULE 9 — Revenue / payroll temporal precision:\n'
    '  • total_revenue: extract the CURRENT or MOST RECENT COMPLETED YEAR figure only.\n'
    '    If the document contains both a prior year figure and a current year figure, extract ONLY the current year.\n'
    '    If only one figure is present, extract that figure regardless of label.\n'
    '    NEVER blend, average, or choose a projected/future figure over a stated current figure.\n'
    '    Example: "Prior year revenue was $1,200,000. Current year gross sales are $2,500,000." → extract $2,500,000.\n'
    '    Example: "Annual Revenue: $1,500,000" (no year context) → extract $1,500,000.\n'
    '  • total_payroll: same rule — extract the current/most recent year figure only.\n\n'
    'RULE 10 — account_description (narrative documents only):\n'
    '  Populate `account_description` ONLY when the document is an underwriting narrative, '
    'submission narrative, account summary, executive summary, or account overview document. '
    'Extract the opening paragraph(s) that read as a high-level account summary, whether or '
    'not they carry an explicit heading - commonly (but not always) labeled "Account Overview", '
    '"Account Summary", "Company Overview", "Background", or "Executive Summary", though an '
    'unlabeled opening pitch paragraph qualifies just as well. This field captures the broker\'s high-level account pitch — '
    'distinct from the factual `operations_description` (what the business does). '
    'Set `account_description` to null for dec pages, applications, loss runs, certificates, '
    'and all other structured documents that are not narrative account summaries.\n\n'
    'RULE 11 — narrative_components: For each of the 12 components, set present=true only if '
    'THIS CHUNK OF TEXT contains meaningful prose discussing that topic (not just a heading or '
    'label). Include a short verbatim quote (30 words max) as evidence. Set present=false and '
    'evidence=null when the topic is absent from this chunk.\n'
    '  account_overview: high-level account summary, executive summary, broker account pitch.\n'
    '  operations: what the business does day-to-day, scope of work, services provided.\n'
    '  years_in_business: how long the company has operated, founding year, tenure in business.\n'
    '  management: leadership team, principals, owner experience, org structure, key personnel.\n'
    '  risk_controls: safety programs, loss prevention, certifications, written procedures.\n'
    '  loss_history: prior claims, loss history, claims summary, loss experience discussion.\n'
    '  coverage_discussion: coverage needs, existing lines, limits discussion, gaps analysis.\n'
    '  carrier_market: prior or current carriers, market context, market appetite.\n'
    '  location_exposure: premises, locations, geographic footprint, facilities.\n'
    '  employee_practices: HR policies, workforce description, hiring practices, turnover.\n'
    '  growth_trends: workers comp payroll by class code, WC class codes, payroll breakdown by classification, NCCI class, labor classification, payroll schedule.\n'
    '  target_markets: experience modifier, EMOD, XMOD, experience modification rate, mod factor, merit rating, debit mod, credit mod, rating bureau, workers comp mod.\n\n'
    'RULE 12 — loss_run_status: Set to "pending" or "requested" when the document indicates, '
    'by MEANING, that loss runs have been requested or ordered but not yet received - whether '
    'stated plainly ("loss runs requested", "loss runs pending", "awaiting loss runs", "loss '
    'runs on order", "loss runs to follow") or paraphrased ("loss history is being compiled", '
    '"we will forward the loss runs once the prior carrier provides them", "claims experience '
    'to be supplied under separate cover"). Two strict guards still apply: set to null when '
    'actual loss run data IS present in this document (use loss_history, loss_run_valuation_date, '
    'and related fields for that), and do NOT infer pending status from the absence of loss '
    'runs alone - there must be an affirmative statement that they are outstanding.\n\n'
    'RULE 13 — Loss-run period dating (loss_run_period_start / loss_run_period_end / '
    'loss_history_years): these are deterministic scoring inputs, not the per-claim list from '
    'RULE 7 - extract them whenever a loss run states its OWN coverage/experience period, even '
    'if that period contains zero claims.\n'
    '  loss_run_period_start: the EARLIEST date of the stated experience period.\n'
    '  loss_run_period_end: the LATEST date of that period (often the same as, or close to, '
    'the valuation date). If the document gives a range "X to Y" or "X through Y", '
    'loss_run_period_start = X and loss_run_period_end = Y.\n'
    '  loss_history_years: an EXPLICIT year count the document itself states for this period '
    '(e.g., "(5 years)", "5-year loss run", "for the last 5 years") - a direct cross-check, not '
    'a value you calculate yourself from the dates.\n'
    '  Example: "Loss Run Period: 09/01/2021 to 09/01/2026 (5 years)" → '
    'loss_run_period_start="09/01/2021", loss_run_period_end="09/01/2026", loss_history_years="5".\n'
    '  Example: "5-year loss history requested, currently valued 07/01/2026" with no explicit '
    'start date → loss_run_valuation_date="07/01/2026", loss_history_years="5", '
    'loss_run_period_start/end may be null since no explicit range was given.\n'
    '  Do NOT confuse this with a lookback WINDOW inside a Yes/No question ("...in the past 5 '
    'years?") or the blank ACORD Loss History section header asks the filer to fill in ("FOR THE '
    'LAST ___ YEARS") - those describe how far back the FORM asks, not how much loss-run '
    'DOCUMENTATION was actually supplied. Only extract loss_history_years from a phrase that '
    'describes an actual loss run/claims history document, not from the disclosure window in an '
    'unanswered or narrative-only question.\n\n'
    'Return ONLY a valid JSON object with exactly these two top-level keys:\n\n'
    + _EXTRACT_SCHEMA
    + '\n\nReturn ONLY the JSON object. No markdown fences, no explanation, no extra text. '
    'Start your response with { and end with }.\n\n'
)

# ── Prompt overhead constants ─────────────────────────────────────────────────
# Max realistic context_section length (label + context_prefix up to max_chars//7 tail).
# Max realistic low_conf_note length (label + 40 tokens * ~10 chars).
# These are upper bounds used for prompt overhead calculation — no magic constants.
_CONTEXT_SECTION_HEADER = (
    "\n\nPREVIOUS CONTEXT (reference only — do NOT re-extract from this; "
    "extract ONLY from PRIMARY TEXT below):\n---\n\n---\n"
)
_LOW_CONF_NOTE_HEADER = (
    "\n\nOCR CONFIDENCE WARNING: The following tokens had low OCR confidence. "
    "Apply corrections where context makes the correct value clear:\n"
)
_LOW_CONF_NOTE_MAX_TOKENS = 40 * 12  # 40 tokens * ~12 chars each (conservative)

# Fix 7: dynamic prompt overhead computed from actual component lengths
def _compute_prompt_overhead(model: str = ACTIVE_MODEL) -> int:
    raw = get_chunk_size(model)
    context_max = raw // 7   # max context_prefix tail length
    return (
        len(_EXTRACT_PROMPT_PREFIX)
        + len(_CONTEXT_SECTION_HEADER)
        + context_max
        + len(_LOW_CONF_NOTE_HEADER)
        + _LOW_CONF_NOTE_MAX_TOKENS
    )


# ── OCR confidence ────────────────────────────────────────────────────────────
_OCR_CRITICAL_FIELDS = frozenset({
    "applicant_name", "mailing_address", "fein", "effective_date",
    "expiration_date", "property_building_value", "property_bpp_value",
})
_OCR_STANDARD_FIELDS = frozenset({
    "construction_type", "occupancy_type", "fire_protection_class",
    "year_built", "roof_year",
})
_OCR_THRESHOLD_CRITICAL = 0.90
_OCR_THRESHOLD_STANDARD = 0.80
_OCR_THRESHOLD_DEFAULT  = 0.70

# Fix 11: confusion-map applied ONLY to code/numeric-type fields.
# Free-text fields (names, addresses, descriptions) use plain .lower() to prevent
# false low-confidence flags (e.g. "policy" → "p01icy").
_OCR_CONFUSION_SAFE_FIELDS = frozenset({
    "fein", "policy_number", "naics_code", "sic_code",
    "effective_date", "expiration_date", "retro_date",
    "wc_xmod", "wc_xmod_effective_date",
    "year_built", "roof_year", "fire_protection_class",
    "property_building_value", "property_bpp_value",
    "total_revenue", "total_payroll", "wc_payroll",
    "auto_liability_limit", "umbrella_limit",
})

_OCR_CONFUSION_MAP = str.maketrans({
    "O": "0", "o": "0", "l": "1", "I": "1",
    "S": "5", "Z": "2", "B": "8", "G": "6",
})


def _normalize_for_ocr_check(s: str, field: str = "") -> str:
    """Apply confusion-map normalization ONLY for code/numeric fields. Skip free-text."""
    if field and field not in _OCR_CONFUSION_SAFE_FIELDS:
        return s.lower()
    return s.translate(_OCR_CONFUSION_MAP)


def _ocr_threshold(field_name: str) -> float:
    if field_name in _OCR_CRITICAL_FIELDS:
        return _OCR_THRESHOLD_CRITICAL
    if field_name in _OCR_STANDARD_FIELDS:
        return _OCR_THRESHOLD_STANDARD
    return _OCR_THRESHOLD_DEFAULT


# ── Null normalisation ────────────────────────────────────────────────────────
_NULL_STRINGS = {"null", "none", "n/a", "na", "unknown", ""}


def _fv(facts: dict, key: str, default=None):
    raw = facts.get(key, default)
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"]
    return raw


def _narrative_remarks_text(facts: dict) -> str:
    """Resolve the free-text ACORD-101 / submission narrative from a facts dict.

    Three possible homes for narrative prose:
    - acord101_remarks         -- legacy key some scorers historically read
    - additional_remarks_text  -- canonical ACORD-101 schema key written by the chunked
                                  extractor for ACORD-101 remarks text
    - account_description      -- RULE 10: populated ONLY for standalone underwriting /
                                  submission narratives (account overview, executive summary).
                                  This is where broker account narratives land; mapped to no
                                  form field. Resolving it here is what makes standalone
                                  narratives score correctly.

    Priority: explicit legacy key > canonical remarks key > standalone narrative home.
    Returns "" when none present.
    """
    return str(
        _fv(facts, "acord101_remarks")
        or _fv(facts, "additional_remarks_text")
        or _fv(facts, "account_description")
        or ""
    )


def _focr(facts: dict, key: str) -> bool:
    """Returns True if field has high OCR confidence."""
    raw = facts.get(key)
    if isinstance(raw, dict):
        conf = raw.get("confidence")
        # New 4-tier confidence system
        if conf in ("deterministic", "filled"):
            return True
        if conf == "ai_high":
            return True
        if conf == "ai_low":
            return False
        # Legacy boolean fallback
        if "ocr_confident" in raw:
            return bool(raw["ocr_confident"])
    return True


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, list):
        return len(v) == 0
    if isinstance(v, dict):
        if "value" in v:
            inner = str(v["value"]).strip().lower()
            return not inner or inner in _NULL_STRINGS
        return len(v) == 0
    return str(v).strip().lower() in _NULL_STRINGS


# ── Thread-safe in-process LRU cache with TTL (Fix 8) ────────────────────────
_CACHE_TTL      = 86_400   # seconds
_CACHE_MAX_SIZE = 500
_EXTRACT_CACHE: "collections.OrderedDict[str, Tuple[dict, float]]" = collections.OrderedDict()
_CACHE_LOCK     = threading.Lock()   # guards ALL access to _EXTRACT_CACHE


def _lru_get(key: str) -> Optional[dict]:
    with _CACHE_LOCK:
        if key not in _EXTRACT_CACHE:
            return None
        value, ts = _EXTRACT_CACHE[key]
        if time.monotonic() - ts > _CACHE_TTL:
            _EXTRACT_CACHE.pop(key, None)
            return None
        _EXTRACT_CACHE.move_to_end(key)
        return value


def _lru_set(key: str, value: dict) -> None:
    with _CACHE_LOCK:
        if key in _EXTRACT_CACHE:
            _EXTRACT_CACHE.move_to_end(key)
        _EXTRACT_CACHE[key] = (value, time.monotonic())
        while len(_EXTRACT_CACHE) > _CACHE_MAX_SIZE:
            _EXTRACT_CACHE.popitem(last=False)


# ── Redis cache (optional) ────────────────────────────────────────────────────
try:
    import redis.asyncio as _aioredis
    from redis.asyncio.connection import ConnectionPool
    from config.settings import REDIS_URL as _REDIS_URL
    _redis = _aioredis.Redis(connection_pool=ConnectionPool.from_url(
        _REDIS_URL,
        max_connections=20,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        decode_responses=True,
    ))
    logger.info(f"extract_facts: Redis cache connected ({_REDIS_URL})")
except Exception as _redis_init_err:
    logger.warning(
        f"extract_facts: Redis unavailable ({_redis_init_err}) — "
        "in-process LRU cache active (degraded caching mode)"
    )
    _redis = None


def _cache_key(text: str, model: str, ctx_hash: str, lct_hash: str) -> str:
    """
    Fix 3: includes PROMPT_VERSION + SCHEMA_VERSION so any schema/prompt change
    automatically invalidates all existing cache entries.
    Fix (prev): includes ctx_hash + lct_hash to prevent stale hits on same text
    at different positions or with different OCR quality.
    """
    payload = f"pv={PROMPT_VERSION}|sv={SCHEMA_VERSION}|m={model}|ctx={ctx_hash}|lct={lct_hash}|{text}"
    return hashlib.md5(payload.encode(), usedforsecurity=False).hexdigest()


_REDIS_CACHE_TTL = 3600  # Redis L2 TTL — shorter than LRU to bound cross-worker staleness


async def _cache_get(key: str) -> Optional[dict]:
    # L1: check in-process LRU first (fastest, no network)
    hit = _lru_get(key)
    if hit is not None:
        return hit
    # L2: check Redis (shared across workers)
    if _redis is not None:
        try:
            raw = await _redis.get(f"extract:{key}")
            if raw:
                value = json.loads(raw)
                _lru_set(key, value)  # promote into L1
                return value
        except Exception as ex:
            logger.warning(f"Redis get failed: {ex}")
    return None


async def _cache_set(key: str, value: dict) -> None:
    # Write to both L1 and L2 so all workers share the result immediately
    _lru_set(key, value)
    if _redis is not None:
        try:
            await _redis.setex(f"extract:{key}", _REDIS_CACHE_TTL, json.dumps(value))
        except Exception as ex:
            logger.warning(f"Redis set failed, in-process only: {ex}")


# ── Document-type identification (Beta Report §4.2) ───────────────────────────
# Classification fuses three signals, in priority order:
#   1. CONTENT keywords  (primary)  — DOC_TYPE_KEYWORDS below.
#   2. NARRATIVE rules   (content)  — _NARRATIVE_SIGNALS: a doc with several
#      underwriting-narrative signals is classified `narrative` even though it
#      has no single strong keyword (the Beta Test 1/2 "Unknown narrative" bug).
#   3. FILENAME signals  (supporting, NOT overriding) — _FILENAME_SIGNALS adds a
#      bounded bonus to a type that already has some content support, and can
#      only classify on its own at LOW confidence.
#
# Each keyword tuple is (keyword, weight). High-weight keywords are strong type
# signals (appear almost exclusively in that doc type); low-weight keywords are
# supporting signals that can appear across types. The taxonomy mirrors the
# Beta Report §4.2 action item #1 list, collapsed to canonical snake_case keys.
DOC_TYPE_KEYWORDS: Dict[str, List[Tuple[str, float]]] = {
    "dec_page": [
        ("declarations page", 3.0), ("dec page", 3.0), ("policy declarations", 3.0),
        ("declaration", 3.0),
        ("declarations", 2.0), ("coverage summary", 2.0), ("insuring agreement", 2.0),
        ("policy period", 1.5), ("named insured", 1.0), ("policy number", 0.5),
    ],
    "certificate": [
        ("certificate of liability insurance", 3.0), ("certificate of insurance", 3.0),
        ("acord 25", 3.0), ("this is to certify", 3.0),
        ("certificate holder", 2.0), ("evidence of insurance", 2.0),
    ],
    "loss_run": [
        # Specific / tabular signals — strong. A real loss run carries several.
        ("loss run", 3.0), ("loss runs", 3.0), ("date of loss", 2.0), ("loss date", 2.0),
        ("paid losses", 2.0), ("claim number", 2.0), ("claimant", 1.5),
        ("incurred", 1.0), ("reserve", 1.0), ("paid", 0.5), ("open", 0.3),
        # Prose-y phrases — intentionally MODERATE so a single narrative mention of
        # "loss history" does not, on its own, override narrative classification.
        ("loss history", 2.0), ("claims history", 2.0), ("claim history", 2.0),
        ("loss experience", 2.0),
    ],
    "narrative": [
        ("underwriting narrative", 3.0), ("submission narrative", 3.0),
        ("carrier narrative", 3.0), ("account narrative", 3.0),
        ("executive summary", 2.5), ("account overview", 2.5), ("account summary", 2.5),
        ("submission summary", 2.5), ("company overview", 2.0), ("business narrative", 2.0),
        ("narrative", 1.5), ("overview", 0.5),
    ],
    "supplemental_application": [
        ("supplemental application", 3.0), ("contractors supplemental", 3.0),
        ("acord 186", 3.0), ("supplemental questionnaire", 2.5),
        ("supplement", 1.0),
    ],
    "sov": [
        ("statement of values", 3.0), ("schedule of values", 3.0),
        ("total insured value", 2.5), ("total insurable value", 2.5),
        ("building value", 1.0), ("replacement cost", 1.0),
    ],
    "cope_report": [
        ("cope report", 3.0), ("construction occupancy protection exposure", 3.0),
        ("construction, occupancy, protection", 3.0),
        ("protection class", 1.5), ("year built", 1.0), ("roof type", 1.0),
    ],
    "payroll_report": [
        ("payroll report", 3.0), ("payroll by class code", 3.0),
        ("payroll breakdown", 2.5), ("class code", 1.5), ("payroll", 1.0),
        ("remuneration", 1.5),
    ],
    "gross_sales_report": [
        ("gross sales report", 3.0), ("gross sales", 2.5), ("gross receipts", 2.5),
        ("annual sales", 1.5), ("sales report", 1.5),
    ],
    "emod_worksheet": [
        ("experience modification worksheet", 3.0), ("experience rating worksheet", 3.0),
        ("experience modification factor", 2.5), ("mod worksheet", 2.5),
        ("experience modification", 2.0), ("emod", 2.0), ("xmod", 2.0),
        ("ncci", 1.5), ("expected losses", 1.0),
    ],
    "financial_statement": [
        ("balance sheet", 3.0), ("income statement", 3.0), ("profit and loss", 3.0),
        ("financial statement", 3.0), ("statement of cash flows", 3.0),
        ("net income", 1.0), ("total assets", 1.0), ("total liabilities", 1.0),
    ],
    "handbook": [
        ("employee handbook", 3.0), ("employer handbook", 3.0),
        ("employee manual", 2.5), ("personnel policy", 2.0), ("code of conduct", 1.5),
    ],
    "safety_manual": [
        ("safety manual", 3.0), ("risk control program", 3.0),
        ("safety program", 2.5), ("written safety", 2.5), ("safety procedures", 2.0),
        ("injury and illness prevention", 2.5), ("loss control", 1.5),
    ],
    "vehicle_schedule": [
        ("vehicle schedule", 3.0), ("schedule of vehicles", 3.0),
        ("vin", 1.0), ("year make model", 1.5), ("gvw", 1.0),
    ],
    "driver_schedule": [
        ("driver schedule", 3.0), ("schedule of drivers", 3.0),
        ("driver list", 2.5), ("license number", 1.0), ("date of hire", 1.0),
    ],
    "equipment_schedule": [
        ("equipment schedule", 3.0), ("schedule of equipment", 3.0),
        ("contractors equipment", 2.5), ("acord 138", 2.5), ("serial number", 1.0),
    ],
    "location_schedule": [
        ("location schedule", 3.0), ("schedule of locations", 3.0),
        ("premises schedule", 2.5), ("location number", 1.0),
    ],
    "schedule": [
        ("schedule of", 2.0),
    ],
    "quote": [
        ("quoted premium", 3.0), ("estimated premium", 3.0),
        ("quote proposal", 3.0), ("insurance proposal", 2.5),
        ("quote", 2.0), ("proposal", 2.0), ("indication", 1.5),
    ],
    "binder": [
        ("insurance binder", 3.0), ("binder number", 3.0), ("this binder", 2.5),
        ("acord 75", 3.0), ("binder", 1.5),
    ],
    "policy": [
        ("policy jacket", 3.0), ("common policy conditions", 3.0),
        ("policy form", 2.0), ("policy contract", 2.0),
    ],
    "application": [
        ("acord 125", 3.0), ("acord 126", 3.0), ("acord 130", 3.0), ("acord 127", 3.0),
        ("acord 131", 3.0), ("acord 140", 3.0),
        ("application for insurance", 3.0), ("commercial insurance application", 3.0),
        ("application", 1.5), ("prior application", 1.5),
    ],
    "endorsement": [
        # Strong signals — these words appear almost exclusively on endorsement forms
        ("endorsement number", 3.0), ("policy endorsement", 3.0),
        ("this endorsement changes the policy", 3.0), ("endorsement effective", 2.5),
        ("form number", 2.0), ("endorsement", 1.5),
        # Weak signals — these appear on many doc types; alone they cannot classify as endorsement
        ("additional insured", 0.3), ("waiver of subrogation", 0.3), ("mortgagee", 0.3),
    ],
}

# Human-readable labels for every canonical doc type (used by the UI + the
# manual-reclassification dropdown). "unknown" is always last.
DOC_TYPE_LABELS: Dict[str, str] = {
    "dec_page":                 "Dec Page",
    "policy":                   "Policy",
    "application":              "Commercial Insurance Application",
    "supplemental_application": "Supplemental Application",
    "certificate":              "Certificate of Insurance",
    "loss_run":                 "Loss Runs",
    "narrative":                "Underwriting Narrative",
    "quote":                    "Quote Proposal",
    "binder":                   "Binder",
    "endorsement":              "Endorsement",
    "acord_form":               "ACORD Form",
    "sov":                      "Statement / Schedule of Values",
    "cope_report":              "COPE Report",
    "financial_statement":      "Financial Statements",
    "payroll_report":           "Payroll Report",
    "gross_sales_report":       "Gross Sales Report",
    "emod_worksheet":           "Experience Modification Worksheet",
    "vehicle_schedule":         "Vehicle Schedule",
    "driver_schedule":          "Driver Schedule",
    "equipment_schedule":       "Equipment Schedule",
    "location_schedule":        "Location Schedule",
    "schedule":                 "Schedule",
    "handbook":                 "Employer Handbook",
    "safety_manual":            "Safety Manual / Risk Control Program",
    "unknown":                  "Unknown",
}

# Canonical list of every type a user may assign (manual reclassification) and
# that the classifier may emit. Order is the resolution priority for ties and
# for select_primary_truth: richer "primary" documents (dec page, application)
# win over supporting documents (narrative, loss run, schedules).
ALLOWED_DOC_TYPES: List[str] = list(DOC_TYPE_LABELS.keys())

# Narrative-detection rules (Beta Report §4.2 action item #2). Each entry is a
# signal CATEGORY -> the phrases that satisfy it. A document that satisfies
# several distinct categories is a likely underwriting narrative even when it
# carries no single strong keyword. We count DISTINCT categories so a long
# prose document that repeats one theme isn't over-credited.
#
# One theme PER Beta Report §4.2 signal (18 total) so each listed signal is
# counted independently — e.g. "renewal context" and "prior carrier context"
# are no longer folded into one carrier theme. Phrases are scoped to avoid
# substring overlap between sibling themes (e.g. "risk controls" vs "risk
# control program") so a single mention can't credit two themes at once.
_NARRATIVE_SIGNALS: Dict[str, Tuple[str, ...]] = {
    # 1. Account overview
    "account_overview":     ("account overview", "company overview", "about the",
                             "background", "company profile", "overview of operations"),
    # 2. Named insured / applicant context
    "named_insured":        ("named insured", "applicant", "the insured", "dba", "d/b/a"),
    # 3. Operations description
    "operations":           ("operations", "scope of work", "nature of business",
                             "services provided", "business operations", "describe operations"),
    # 4. Years in business
    "years_in_business":    ("years in business", "established in", "in business since",
                             "founded in", "incorporated in", "years of experience"),
    # 5. Management experience
    "management":           ("management experience", "ownership", "principals",
                             "key personnel", "owner has", "management team", "leadership"),
    # 6. Risk controls or safety practices
    "risk_controls":        ("risk controls", "safety practices", "loss control",
                             "risk management", "quality control", "loss prevention"),
    # 7. Loss history statement
    "loss_history":         ("no prior losses", "no losses", "loss history",
                             "claims history", "prior claims", "loss experience",
                             "no claims", "favorable loss"),
    # 8. Coverage discussion
    "coverage_discussion":  ("coverage", "limits of liability", "general liability",
                             "umbrella", "workers compensation", "deductible",
                             "coverage requested", "coverage needed"),
    # 9. Carrier or market considerations
    "carrier_market":       ("market considerations", "market appetite", "insurance market",
                             "marketing this account", "remarketing", "coverage placement"),
    # 10. Location or exposure summary
    "location_exposure":    ("location", "premises", "exposure", "square footage",
                             "address", "operations are performed"),
    # 11. Renewal context
    "renewal_context":      ("renewal", "up for renewal", "renewal date", "renewing",
                             "expiring policy", "policy expires", "renewal term"),
    # 12. Prior carrier context
    "prior_carrier":        ("prior carrier", "previous carrier", "current carrier",
                             "expiring carrier", "incumbent carrier", "incumbent"),
    # 13. Employer / employee handbook
    "handbook":             ("employee handbook", "employer handbook", "employee manual",
                             "personnel policy", "personnel manual", "code of conduct"),
    # 14. Safety manual, risk control program, or written safety procedures
    "safety_program":       ("safety manual", "risk control program", "safety program",
                             "written safety", "safety procedures", "safety policy",
                             "injury and illness prevention", "iipp"),
    # 15. Hiring, training, onboarding, or employee management practices
    "employee_practices":   ("hiring", "training", "onboarding", "employee management",
                             "staff management", "personnel management", "workforce"),
    # 16. Workers Compensation payroll breakdown by class code
    "wc_payroll":           ("payroll by class", "class code", "payroll breakdown",
                             "remuneration"),
    # 17. Current Experience Modification Factor, EMOD, or XMOD
    "experience_mod":       ("experience modification", "emod", "xmod",
                             "experience mod", "mod factor", "experience rating"),
    # 18. Workers Compensation exposure summaries or classification details
    "wc_exposure":          ("workers compensation exposure", "wc exposure",
                             "workers comp classification", "wc classification",
                             "governing classification", "classification code",
                             "exposure summary", "classification details"),
}

# When this many DISTINCT narrative categories appear, the document is treated
# as a likely underwriting narrative. Tuned so a short cover letter (1-2 themes)
# does not trip it, but a real account narrative (operations + management + loss
# + coverage + carrier ...) does.
_NARRATIVE_MIN_CATEGORIES = 4

# Stage-1 prose-confusable flip guard (below): a structured doc whose top keyword
# is a prose-confusable supporting type is re-labelled `narrative` ONLY when it
# shows this many distinct narrative themes. Set higher than _NARRATIVE_MIN_CATEGORIES
# because the §4.2 themes above are fine-grained — a genuine account narrative spans
# many themes (account + operations + management + loss + carrier + renewal + ...),
# while a focused safety manual / handbook stays within its own cluster and must NOT
# be flipped. Preserves the pre-split behaviour (real safety manuals stay safety
# manuals) under the finer theme set.
_PROSE_CONFUSABLE_NARRATIVE_MIN = 8

# Filename signals (Beta Report §4.2 action item #3) — SUPPORTING evidence only.
# A filename match adds a bounded bonus to the matching content type; it never
# overrides a confident content classification. Substrings are matched against
# the lowercased filename with separators normalised to spaces.
_FILENAME_SIGNALS: Dict[str, Tuple[str, ...]] = {
    "narrative":                ("submission narrative", "underwriting narrative",
                                 "carrier narrative", "executive summary",
                                 "account summary", "account overview", "narrative",
                                 "submission summary", "overview"),
    "loss_run":                 ("loss run", "lossrun", "loss runs", "claims history",
                                 "claim history", "loss history"),
    "certificate":              ("certificate", "acord 25", "acord25", "coi"),
    "dec_page":                 ("dec page", "decpage", "declarations", "dec-page", "declaration"),
    "handbook":                 ("handbook", "employee manual"),
    "safety_manual":            ("safety manual", "safety program", "risk control"),
    "payroll_report":           ("payroll",),
    "emod_worksheet":           ("emod", "xmod", "experience mod", "mod worksheet"),
    "sov":                      ("sov", "statement of values", "schedule of values"),
    "gross_sales_report":       ("gross sales", "sales report"),
    "supplemental_application": ("supplemental", "supp app", "acord 186"),
    "application":              ("acord 125", "acord 126", "acord 127", "acord 130",
                                 "application", "app "),
    "quote":                    ("quote", "proposal", "indication"),
    "binder":                   ("binder",),
    "financial_statement":      ("financials", "balance sheet", "income statement",
                                 "profit and loss", "p&l", "p and l"),
}

# Resolution priority for ties + select_primary_truth. Primary "truth" documents
# (rich, structured) outrank supporting documents.
_DOC_TYPE_PRIORITY = [
    "dec_page", "application", "supplemental_application", "policy", "quote",
    "binder", "certificate", "endorsement", "acord_form",
    "sov", "cope_report", "vehicle_schedule", "driver_schedule",
    "equipment_schedule", "location_schedule", "schedule",
    "loss_run", "emod_worksheet", "payroll_report", "gross_sales_report",
    "financial_statement", "narrative", "handbook", "safety_manual",
    "unknown",
]

_DOC_TYPE_MIN_SCORE = 3.0   # content score required for a confident (non-filename) classification
_FILENAME_BONUS     = 2.0   # bounded bonus a filename match adds to its type

# A generic ACORD-form reference, e.g. "ACORD 28", "ACORD-101", "ACORD form".
# Used ONLY as a fallback after the specific-type stages, so a recognised
# application / certificate / endorsement is never demoted to the generic bucket.
_ACORD_FORM_RE = re.compile(r"acord\s*[-#]?\s*\d{2,4}", re.IGNORECASE)

# Supporting/prose document types whose keywords are easily tripped by an
# account narrative that merely *discusses* the topic (e.g. a narrative that
# describes the insured's safety program is not a Safety Manual). When the
# structured winner is one of these AND the document shows a high density of
# distinct narrative categories AND the filename does not corroborate the
# supporting type, we prefer `narrative`.
_PROSE_CONFUSABLE_TYPES = frozenset({
    "safety_manual", "handbook", "loss_run", "payroll_report",
    "gross_sales_report", "cope_report", "financial_statement", "schedule",
})


def _content_scores(tl: str) -> Dict[str, float]:
    """Pure keyword-weighted content score per doc type (no narrative-rule or
    filename influence — those are layered on separately so broad narrative
    signals can never out-vote a strong structured keyword)."""
    return {
        dt: sum(w for kw, w in kws if kw in tl)
        for dt, kws in DOC_TYPE_KEYWORDS.items()
    }


def narrative_signal_categories(text: str) -> List[str]:
    """Return the distinct narrative-signal categories present in *text*."""
    tl = text.lower()
    return [cat for cat, phrases in _NARRATIVE_SIGNALS.items()
            if any(p in tl for p in phrases)]


def _filename_bonus(filename: Optional[str]) -> Dict[str, float]:
    """Bounded per-type bonus derived from the filename (supporting evidence)."""
    if not filename:
        return {}
    fl = re.sub(r"[._\-]+", " ", str(filename).lower())
    fl = re.sub(r"\s+", " ", fl).strip()
    bonus: Dict[str, float] = {}
    for dt, sigs in _FILENAME_SIGNALS.items():
        if any(s in fl for s in sigs):
            bonus[dt] = _FILENAME_BONUS
    return bonus


def _references_acord_form(text_lower: str, filename: Optional[str]) -> bool:
    """True when a document clearly references an ACORD form by number or name.

    Pure FALLBACK signal: callers must consult it only after the specific-type
    stages, so it never overrides a recognised application/certificate/etc. It
    catches the ACORD forms the keyword taxonomy doesn't name individually (e.g.
    ACORD 28/101/133/141/160) so they land in a generic ACORD bucket, not Unknown."""
    if "acord form" in text_lower or _ACORD_FORM_RE.search(text_lower):
        return True
    if filename:
        fl = re.sub(r"[._\-]+", " ", str(filename).lower())
        if "acord form" in fl or _ACORD_FORM_RE.search(fl):
            return True
    return False


def _argmax_by_priority(scores: Dict[str, float]) -> Tuple[str, float]:
    """Highest-scoring type; ties broken by _DOC_TYPE_PRIORITY."""
    if not scores:
        return "unknown", 0.0
    top = max(scores.values())
    tied = [dt for dt, s in scores.items() if abs(s - top) < 1e-9]
    if len(tied) == 1:
        return tied[0], top
    for dt in _DOC_TYPE_PRIORITY:
        if dt in tied:
            return dt, top
    return tied[0], top


def classify_document(text: str, filename: Optional[str] = None) -> dict:
    """Classify a document from content + narrative rules + filename signals.

    Returns a dict:
        {
          "doc_type":   canonical key (or "unknown"),
          "confidence": "high" | "medium" | "low",
          "source":     "content" | "content+filename" | "narrative_rules"
                        | "acord_form" | "filename" | "none",
          "scores":     {doc_type: float, ...},   # fused scores (debug/UI)
          "narrative_categories": [str, ...],      # distinct narrative signals hit
        }

    Resolution order (Beta Report §4.2). The key design property: narrative
    rules and filename signals are LAYERED FALLBACKS, never peers of the
    structured-keyword vote — so a dec page or application is never demoted to
    `narrative` just because it happens to mention coverage/operations/locations.

      1. Strong structured CONTENT keyword wins (best content score ≥ min).
      2. Else, enough DISTINCT narrative categories ⇒ `narrative`
         (the Beta Test 1/2 "Unknown narrative" fix).
      3. Else, content + FILENAME bonus clears the bar (filename as supporting
         evidence for a type that already had some content support).
      3.5 Else, a clear ACORD-form reference ⇒ generic `acord_form` (catches the
         ACORD forms the taxonomy doesn't name individually; runs only here, so
         it never demotes a recognised specific type).
      4. Else, a filename-only match classifies at LOW confidence (never
         overrides 1–3); otherwise `unknown`.
    """
    tl = text.lower()
    content = _content_scores(tl)
    narr_cats = narrative_signal_categories(text)
    fbonus = _filename_bonus(filename)

    # Fused scores are for display/debug only — decisions below are staged.
    fused = dict(content)
    for dt, b in fbonus.items():
        fused[dt] = fused.get(dt, 0.0) + b

    best_type, best_content = _argmax_by_priority(content)

    # ── (1) Confident structured-content classification ─────────────────────
    if best_content >= _DOC_TYPE_MIN_SCORE:
        # A rich account narrative can trip a prose-confusable supporting type
        # (safety program, handbook, loss history, payroll mentions). When the
        # narrative-category density is high and the filename does NOT corroborate
        # the supporting type, prefer `narrative` over the weak supporting match.
        if (best_type in _PROSE_CONFUSABLE_TYPES
                and best_type not in fbonus
                and len(narr_cats) >= _PROSE_CONFUSABLE_NARRATIVE_MIN):
            return _classification(
                "narrative", confidence="medium", source="narrative_rules",
                scores=fused, narr_cats=narr_cats,
            )
        had_filename = best_type in fbonus
        return _classification(
            best_type,
            confidence="high" if best_content >= 2 * _DOC_TYPE_MIN_SCORE else "medium",
            source="content+filename" if had_filename else "content",
            scores=fused, narr_cats=narr_cats,
        )

    # ── (2) Narrative detection rules (fallback gate) ───────────────────────
    if len(narr_cats) >= _NARRATIVE_MIN_CATEGORIES:
        return _classification(
            "narrative",
            confidence="high" if len(narr_cats) >= _NARRATIVE_MIN_CATEGORIES + 2 else "medium",
            source="narrative_rules",
            scores=fused, narr_cats=narr_cats,
        )

    # ── (3) Content + filename bonus clears the bar ─────────────────────────
    best_fused_type, best_fused_score = _argmax_by_priority(fused)
    if best_fused_score >= _DOC_TYPE_MIN_SCORE and content.get(best_fused_type, 0.0) > 0:
        return _classification(
            best_fused_type, confidence="medium",
            source="content+filename" if best_fused_type in fbonus else "content",
            scores=fused, narr_cats=narr_cats,
        )

    # ── (3.5) Generic ACORD-form fallback ───────────────────────────────────
    # A document that references an ACORD form by number/name but matched no
    # SPECIFIC ACORD type above (e.g. ACORD 28 / 101 / 133 / 141 / 160) is a
    # generic ACORD form - not Unknown. Reached only after the specific-type
    # stages, so it can never demote a recognised application/certificate/etc.
    if _references_acord_form(tl, filename):
        return _classification(
            "acord_form", confidence="medium", source="acord_form",
            scores=fused, narr_cats=narr_cats,
        )

    # ── (4) Filename-only (weak) — LOW confidence, never overrides 1–3 ───────
    if fbonus:
        fn_type, _ = _argmax_by_priority(fbonus)
        return _classification(
            fn_type, confidence="low", source="filename",
            scores=fused, narr_cats=narr_cats,
        )

    return _classification("unknown", confidence="low", source="none",
                           scores=fused, narr_cats=narr_cats)


def _classification(doc_type: str, *, confidence: str, source: str,
                    scores: Dict[str, float], narr_cats: List[str]) -> dict:
    return {
        "doc_type":   doc_type,
        "confidence": confidence,
        "source":     source,
        "scores":     {k: round(v, 2) for k, v in scores.items() if v},
        "narrative_categories": narr_cats,
    }


def identify_doc_type(text: str, filename: Optional[str] = None) -> str:
    """Backwards-compatible thin wrapper — returns just the canonical type string."""
    return classify_document(text, filename)["doc_type"]


def select_primary_truth(docs: List[dict]) -> dict:
    by_type: Dict[str, dict] = {}
    for d in docs:
        by_type.setdefault(d["doc_type"], d)
    for p in _DOC_TYPE_PRIORITY:
        if p in by_type:
            return by_type[p]
    return docs[0]


# ── Cost guardrail ────────────────────────────────────────────────────────────

def _check_cost_guardrail(text: str, doc_type: str) -> None:
    est = estimate_tokens(text)
    if est > _MAX_TOKENS_PER_DOC:
        raise ValueError(
            f"extract_facts_long: doc_type='{doc_type}' estimated {est:,} tokens "
            f"exceeds ACORDLY_MAX_DOC_TOKENS={_MAX_TOKENS_PER_DOC:,}. "
            "Split the document or raise the env var limit."
        )


# ── Fix 7: Dynamic effective chunk size ───────────────────────────────────────

def _effective_chunk_size(model: str = ACTIVE_MODEL) -> int:
    """
    Raw chunk_size minus dynamically computed prompt overhead.
    Overhead = len(prompt prefix) + len(context section header) + max context tail
               + len(OCR warning header) + max OCR token chars.
    No magic constants — all components measured from actual strings.
    """
    raw      = get_chunk_size(model)
    overhead = _compute_prompt_overhead(model)
    return max(1000, raw - overhead)


# ── Structured fields whitelist (Fix 4) ──────────────────────────────────────
# Only these fact fields may be dicts in the LLM output.
# All others must be string, null, or list. Any other dict → REJECT.
_STRUCTURED_DICT_FIELDS = frozenset({
    "risk_transfer",
    "wc_payroll_by_state",
    "wc_monopolistic_payroll",
})

# List fields in the schema — LLM must return [] not null for these.
_LIST_FIELDS = frozenset({
    "lines_of_business", "locations", "property_locations",
    "auto_vin_schedule", "auto_garaging_addresses", "auto_drivers",
    "gl_class_codes_by_location", "gl_class_code_schedule",
    "wc_class_codes", "underlying_policies",
    "additional_named_insureds", "auto_covered_symbols",
    "loss_history", "prior_coverage_by_line", "wc_officers",
    "inland_marine_items", "contractor_high_hazard_ops",
})


# ── Fix 2: Strict JSON validation ─────────────────────────────────────────────

def _validate_parsed(result: dict, context: str) -> dict:
    """
    Fix 2: require facts AND flags to exist and be dicts. Raise RuntimeError if not.
    Fix 4: enforce structured dict whitelist. Non-whitelisted dict fields → REJECT.

    Pipeline contract: this function sees RAW LLM output scalars only.
    Annotated dicts (containing "value"/"ocr_confident") must NEVER enter here.
    If a field value is a dict with "value" key → it's annotated, which means
    _annotate_facts ran before _validate_parsed — that is a pipeline ordering bug.
    Raise RuntimeError immediately to surface it.
    """
    # Require "facts" as a dict. "flags" is optional — insert empty dict if absent.
    if "facts" not in result:
        raise RuntimeError(
            f"_validate_parsed [{context}]: required top-level key 'facts' missing. "
            "LLM output did not include required schema keys."
        )
    if not isinstance(result["facts"], dict):
        raise RuntimeError(
            f"_validate_parsed [{context}]: 'facts' is {type(result['facts']).__name__}, expected dict."
        )
    if "flags" not in result:
        logger.warning(f"_validate_parsed [{context}]: 'flags' missing — inserting empty dict")
        result["flags"] = {}
    elif not isinstance(result["flags"], dict):
        logger.warning(
            f"_validate_parsed [{context}]: 'flags' is {type(result['flags']).__name__} — resetting to {{}}"
        )
        result["flags"] = {}

    normalized: dict = {}
    for field, v in result["facts"].items():

        # Detect pipeline ordering violation: annotated dict entered validation
        if isinstance(v, dict) and "confidence" in v:
            raise RuntimeError(
                f"_validate_parsed [{context}]: field={field!r} contains annotated dict "
                "(has 'confidence' key). _annotate_facts must NOT run before _validate_parsed."
            )

        # None → pass through
        if v is None:
            normalized[field] = None
            continue

       
        # List → validate + normalize for known fields
        if isinstance(v, list):

            # normalize locations (list of dict → list of string, then dedup)
            if field == "locations":
                if all(isinstance(x, dict) for x in v):
                    try:
                        v = [str(list(x.values())[0]).strip() for x in v if x]
                        logger.warning(
                            f"_validate_parsed [{context}]: normalized locations from dict → string list"
                        )
                    except Exception:
                        raise RuntimeError(
                            f"_validate_parsed [{context}]: invalid locations structure"
                        )

                elif all(isinstance(x, str) for x in v):
                    pass  # valid

                else:
                    raise RuntimeError(
                        f"_validate_parsed [{context}]: locations must be list of strings"
                    )

                # Deduplicate while preserving first-occurrence order.
                # The LLM occasionally emits the same address multiple times
                # across chunks - not always as the identical string. A bare
                # street line ("4800 DAHLIA ST # D13") and a fuller line for
                # the exact same location ("4800 Dahlia St # D13, Denver, CO
                # 80216-3121") both normalize street-first (number, street,
                # unit, then city/state/zip - addresses are always written in
                # that order), so the short form's normalized tokens are
                # always a PREFIX of the long form's, never a same-length
                # variant. An exact-string dedup alone misses this and lets
                # both survive as separate Location rows.
                #
                # Prefix-aware grouping catches it: two addresses are the same
                # location if one's normalized token sequence is a prefix of
                # the other's (or they're identical). The surviving display
                # value per group is picked by the SAME structural-completeness
                # scoring the cross-document identity-field picker already uses
                # (ZIP+4 outranks a bare ZIP5, a present state outranks none,
                # a leading street number outranks none) rather than a naive
                # token-count or raw-length proxy, which a malformed/truncated
                # ZIP ("80216-3", missing 3 digits) can fool into looking
                # falsely "more complete" than a clean one.
                from services.normalization import normalize_address
                from services.underwriting_consistency import _value_completeness
                _seen: List[tuple] = []   # [(norm_tokens, best_raw), ...] first-occurrence order
                for _raw in v:
                    _raw = _raw.strip()
                    if not _raw:
                        continue
                    _norm = normalize_address(_raw)
                    _tokens = tuple(_norm.split()) if _norm else (_raw.lower(),)
                    _match_idx = None
                    for _i, (_etoks, _) in enumerate(_seen):
                        _shorter, _longer = (_tokens, _etoks) if len(_tokens) <= len(_etoks) else (_etoks, _tokens)
                        if _longer[: len(_shorter)] == _shorter:
                            _match_idx = _i
                            break
                    if _match_idx is None:
                        _seen.append((_tokens, _raw))
                    else:
                        _etoks, _ebest = _seen[_match_idx]
                        # An exact completeness tie keeps the first raw string seen,
                        # so behavior for identical duplicates is unchanged.
                        if _value_completeness("physical_address", "identity", _raw) > \
                           _value_completeness("physical_address", "identity", _ebest):
                            _seen[_match_idx] = (_tokens, _raw)
                        else:
                            _seen[_match_idx] = (_etoks, _ebest)
                v = [_raw for _, _raw in _seen]

            # you can extend similar normalization for other weak fields later
        
            normalized[field] = v
            continue

        # Dict → only allowed for whitelisted structured fields
        if isinstance(v, dict):
            if field not in _STRUCTURED_DICT_FIELDS:
                raise RuntimeError(
                    f"_validate_parsed [{context}]: field={field!r} returned dict "
                    f"but is not in _STRUCTURED_DICT_FIELDS whitelist. "
                    f"Keys returned: {list(v.keys())}. Rejecting entire result."
                )
            normalized[field] = v
            continue

        # Scalar → coerce to str, normalize nulls
        str_val = str(v).strip()
        if str_val.lower() in _NULL_STRINGS:
            normalized[field] = None
        elif field in _LIST_FIELDS:
            # LLM returned a scalar for a known list field — try to recover.
            # Attempt JSON parse (LLM sometimes returns a JSON array as a string).
            try:
                parsed = json.loads(str_val)
                if isinstance(parsed, list):
                    normalized[field] = parsed
                    logger.warning(
                        f"_validate_parsed [{context}]: list field {field!r} "
                        "returned as JSON string — parsed successfully"
                    )
                else:
                    logger.warning(
                        f"_validate_parsed [{context}]: list field {field!r} "
                        f"returned scalar {str_val!r} — defaulting to []"
                    )
                    normalized[field] = []
            except (json.JSONDecodeError, ValueError):
                logger.warning(
                    f"_validate_parsed [{context}]: list field {field!r} "
                    f"returned scalar {str_val!r} — defaulting to []"
                )
                normalized[field] = []
        else:
            normalized[field] = str_val

    result["facts"] = normalized
    return result


# ── Fix 2: Strict JSON parse for extraction output ────────────────────────────

# ASYNC-SAFE
async def _safe_json_parse(raw: str, context: str = "") -> dict:
    """
    Parse LLM extraction output. Expects: {"facts": {...}, "flags": {...}}.
    On parse failure: LLM repair (max 2 repair attempts), full raw passed each time.
    After parse: _validate_parsed() enforces strict schema.
    Raises RuntimeError on any failure — never returns empty silently.
    """
    for attempt in range(3):
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.I)
            raw = raw.rstrip("`").strip()
        s = raw.find("{")
        e = raw.rfind("}")
        if s != -1 and e != -1:
            candidate = raw[s : e + 1]
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                parsed = None

            if isinstance(parsed, dict):
                # If the model returned a bare field-dict without the facts/flags wrapper,
                # wrap it automatically. This happens when the model echoes the schema
                # structure rather than wrapping it in {"facts": {...}, "flags": {...}}.
                if "facts" not in parsed and "flags" not in parsed:
                    logger.warning(
                        f"_safe_json_parse [{context}]: bare dict (no facts/flags keys) "
                        "— wrapping into {{facts: ..., flags: {{}}}}"
                    )
                    parsed = {"facts": parsed, "flags": {}}

                try:
                    result = _validate_parsed(parsed, context)
                    if attempt > 0:
                        fact_count = sum(1 for v in result["facts"].values() if v is not None)
                        if fact_count == 0:
                            logger.warning(
                                f"_safe_json_parse [{context}]: repair attempt {attempt} "
                                "produced 0 non-null facts — continuing"
                            )
                            if attempt >= 2:
                                raise RuntimeError(
                                    f"_safe_json_parse [{context}]: repair produced 0 non-null "
                                    "facts after all attempts."
                                )
                        else:
                            return result
                    else:
                        return result
                except RuntimeError:
                    raise

        if attempt < 2:
            logger.warning(
                f"_safe_json_parse: attempt {attempt + 1} failed"
                + (f" [{context}]" if context else "") + ", requesting LLM repair"
            )
            try:
                raw = await groq_chat(
                    LLM_MODEL,
                    [{
                        "role": "user",
                        "content": (
                            "Fix the malformed JSON. Return ONLY a valid JSON object. "
                            "Do not add any explanation or markdown.\n\n"
                            + raw[:3000]
                        ),
                    }],
                    max_tokens=16000,
                )
            except Exception as repair_ex:
                logger.error(f"_safe_json_parse: LLM repair call failed — {repair_ex}")
                break

    raise RuntimeError(
        "_safe_json_parse: could not parse valid JSON after 3 attempts"
        + (f" [{context}]" if context else "")
    )


# ── Fix 5: Separate flat JSON parser for reconciliation ───────────────────────

def _parse_flat_json(raw: str, context: str = "") -> dict:
    """
    Parse reconciliation output: {"field_name": "chosen_value", ...}
    This is a flat dict — NOT {"facts": ..., "flags": ...}.
    Uses a separate parser so _safe_json_parse (which enforces extraction schema)
    is never reused for a structurally different output format.
    Raises RuntimeError on failure.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.I)
        raw = raw.rstrip("`").strip()
    s = raw.find("{")
    e = raw.rfind("}")
    if s == -1 or e == -1:
        raise RuntimeError(
            f"_parse_flat_json [{context}]: no JSON object found in LLM output"
        )
    candidate = raw[s : e + 1]
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError as je:
        raise RuntimeError(
            f"_parse_flat_json [{context}]: JSON decode failed — {je}"
        ) from je
    if not isinstance(result, dict):
        raise RuntimeError(
            f"_parse_flat_json [{context}]: expected dict, got {type(result).__name__}"
        )
    return result


# ── Chunking ──────────────────────────────────────────────────────────────────
_LONG_DOC_LIST_KEYS = [
    "locations", "property_locations", "auto_vin_schedule", "auto_garaging_addresses",
    "auto_drivers", "gl_class_codes_by_location", "gl_class_code_schedule",
    "wc_class_codes", "underlying_policies",
    "additional_named_insureds", "auto_covered_symbols",
    "loss_history", "prior_coverage_by_line", "wc_officers",
    "inland_marine_items", "contractor_high_hazard_ops",
]

DOC_TYPE_CHUNK_LIMITS: Dict[str, int] = {
    "dec_page": 100, "loss_run": 200, "schedule": 200,
    "certificate": 50, "endorsement": 100, "quote": 100,
    "application": 100, "default": 100,
}

_SECTION_BOUNDARY_RE = re.compile(
    r'(?m)^(?:'
    r'[A-Z][A-Z\s\-/]{4,}:|'
    r'[A-Z][A-Z\s\-/]{4,}$|'
    r'ACORD\s+\d+|'
    r'SECTION\s+[A-Z0-9]+|'
    r'SCHEDULE\s+[A-Z0-9]+|'
    r'ITEM\s+\d+\.|'
    r'(?:\d+\.\s+[A-Z][A-Za-z\s]{3,})'
    r')'
)

_KV_LABEL_RE = re.compile(r'^\s*[A-Za-z][A-Za-z\s/\-]{2,40}:\s*$')

ChunkTuple = Tuple[str, int, int, str]


def _find_section_boundaries(lines: List[str]) -> List[int]:
    boundaries = [0]
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped and _SECTION_BOUNDARY_RE.match(stripped):
            if i > 0 and i not in boundaries:
                boundaries.append(i)
    return sorted(set(boundaries))


def _tail_chars(s: str, n: int) -> str:
    if n <= 0 or not s:
        return ""
    tail = s[-n:]
    nl = tail.find("\n")
    if nl > 0:
        tail = tail[nl + 1:]
    return tail


def _split_lines_into_chunks(
    lines: List[str],
    line_start_idx: int,
    line_starts: List[int],
    max_chars: int,
    init_context: str,
) -> List[ChunkTuple]:
    """
    Line-level fallback for oversized sections.
    KV guard: chains consecutive label-only lines to avoid splitting KV pairs.
    Never drops content — all sections emitted regardless of length.
    """
    results: List[ChunkTuple] = []
    buf: List[str] = []
    buf_chars      = 0
    buf_char_start = line_starts[line_start_idx] if line_start_idx < len(line_starts) else 0
    context_prefix = init_context
    total_lines    = len(lines)
    i              = 0

    def _flush(upto_abs_line: int) -> None:
        nonlocal buf, buf_chars, buf_char_start, context_prefix
        if not buf:
            return
        body     = "".join(buf)
        safe_idx = min(upto_abs_line, len(line_starts) - 1)
        c_end    = line_starts[safe_idx]
        results.append((body, buf_char_start, c_end, context_prefix))
        context_prefix = _tail_chars(body, max_chars // 7)
        buf            = []
        buf_chars      = 0
        buf_char_start = c_end

    while i < total_lines:
        # max_chunks is advisory — never break early and drop content.
        # All lines are always processed to guarantee zero truncation.
        abs_line = line_start_idx + i

        # KV guard with chaining
        consumed = [lines[i]]
        j        = i + 1
        while j < total_lines and _KV_LABEL_RE.match(consumed[-1].rstrip()):
            consumed.append(lines[j])
            j += 1
            if j < total_lines and _KV_LABEL_RE.match(consumed[-1].rstrip()):
                continue
            break

        block      = "".join(consumed)
        block_len  = len(block)
        lines_used = j - i

        if buf_chars + block_len > max_chars and buf:
            _flush(abs_line)

        buf.extend(consumed)
        buf_chars += block_len
        i         += lines_used

    if buf:
        end_abs = line_start_idx + total_lines
        safe    = min(end_abs, len(line_starts) - 1)
        _flush(safe)

    return results


def _chunk_by_sections(
    text: str,
    max_chars: int,
    overlap_pct: float,
) -> List[ChunkTuple]:
    """
    Hybrid semantic + line chunking.
    char_start/char_end: unique content offsets into original text.
    context_prefix: boundary context for LLM — not counted in char ranges.
    Short sections never dropped.
    """
    lines = text.splitlines(keepends=True)

    line_starts: List[int] = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line)
    line_starts.append(pos)

    boundaries = _find_section_boundaries(lines)
    if len(lines) not in boundaries:
        boundaries.append(len(lines))

    sections: List[Tuple[int, int]] = [
        (boundaries[i], boundaries[i + 1])
        for i in range(len(boundaries) - 1)
    ]

    results: List[ChunkTuple] = []
    context_prefix   = ""
    cur_lines: List[str] = []
    cur_chars        = 0
    cur_char_start   = 0

    def _flush_cur(upto_char: int) -> None:
        nonlocal cur_lines, cur_chars, cur_char_start, context_prefix
        if not cur_lines:
            return
        body = "".join(cur_lines)
        results.append((body, cur_char_start, upto_char, context_prefix))
        context_prefix = _tail_chars(body, max_chars // 7)
        cur_lines      = []
        cur_chars      = 0

    for sec_start_li, sec_end_li in sections:
        # max_chunks is advisory — never drop sections. Full coverage is required.
        sec_lines      = lines[sec_start_li:sec_end_li]
        sec_chars      = sum(len(l) for l in sec_lines)
        sec_char_start = line_starts[sec_start_li]

        if sec_chars > max_chars:
            if cur_lines:
                _flush_cur(sec_char_start)
                cur_char_start = sec_char_start

            sub_chunks = _split_lines_into_chunks(
                sec_lines, sec_start_li, line_starts,
                max_chars, context_prefix,
            )
            results.extend(sub_chunks)
            if sub_chunks:
                context_prefix = sub_chunks[-1][3]
                cur_char_start = sub_chunks[-1][2]
            cur_lines = []
            cur_chars = 0
            continue

        if cur_chars + sec_chars > max_chars and cur_lines:
            _flush_cur(sec_char_start)
            cur_char_start = sec_char_start
            cur_lines      = list(sec_lines)
            cur_chars      = sec_chars
        else:
            if not cur_lines:
                cur_char_start = sec_char_start
            cur_lines.extend(sec_lines)
            cur_chars += sec_chars

    # Always flush the final buffer — no cap guard here either.
    if cur_lines:
        _flush_cur(line_starts[len(lines)])

    if not results:
        results = [(text[:max_chars], 0, min(max_chars, len(text)), "")]

    return results


# ── Coverage verification ─────────────────────────────────────────────────────

def _verify_coverage(
    chunks: List[ChunkTuple],
    text_len: int,
    doc_type: str,
) -> None:
    if not chunks:
        raise RuntimeError(
            f"_verify_coverage: doc_type='{doc_type}' — no chunks produced"
        )

    intervals = sorted((cs, ce) for (_, cs, ce, _) in chunks)

    merged: List[Tuple[int, int]] = []
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))

    gaps: List[Tuple[int, int]] = []
    if merged[0][0] > 0:
        gaps.append((0, merged[0][0]))
    for i in range(len(merged) - 1):
        if merged[i][1] < merged[i + 1][0]:
            gaps.append((merged[i][1], merged[i + 1][0]))
    if merged[-1][1] < text_len:
        gaps.append((merged[-1][1], text_len))

    covered = sum(e - s for s, e in merged)
    pct     = covered / text_len if text_len > 0 else 1.0

    if gaps:
        gap_desc = ", ".join(f"{s}–{e} ({e - s} chars)" for s, e in gaps[:5])
        raise RuntimeError(
            f"_verify_coverage: doc_type='{doc_type}' coverage={pct:.1%} "
            f"({covered}/{text_len} chars). Gaps: [{gap_desc}]."
        )

    logger.info(
        f"_verify_coverage: doc_type='{doc_type}' OK "
        f"({covered}/{text_len} chars, {len(chunks)} chunks)"
    )


# ── Fix 11: Annotation pipeline (4-tier confidence) ───────────────────────────

def _annotate_facts(
    raw_facts: dict,
    low_confidence_tokens: Optional[List[str]],
    source: str = "ai",
) -> Tuple[dict, List[str]]:
    """
    Called AFTER _validate_parsed on RAW LLM output.
    Receives clean str/None/list/structured-dict values — never annotated dicts.
    OCR confusion-map applied field-by-field: only safe fields get normalized.
    Free-text fields (names, addresses) use plain .lower() — no false flags.
    
    NEW: 4-tier confidence labels:
    - deterministic: schema-validated rule match (not implemented in extraction, reserved for mapping)
    - filled: producer-confirmed (source="producer")
    - ai_high: AI-extracted, high OCR confidence
    - ai_low: AI-extracted, low OCR confidence
    """
    low_conf_set: set = set()
    if low_confidence_tokens:
        for t in low_confidence_tokens:
            tl = t.lower()
            low_conf_set.add(tl)
            # Add confusion-normalized form for numeric/code token matching
            low_conf_set.add(_normalize_for_ocr_check(tl))

    manual_confirmation_required: List[str] = []
    annotated: dict = {}

    for k, v in raw_facts.items():
        # Pass-through: None, list, structured dict — not annotated
        if v is None or isinstance(v, list) or isinstance(v, dict):
            annotated[k] = v
            continue

        # v is a clean str at this point (guaranteed by _validate_parsed)
        str_val = str(v).strip()
        if not str_val or str_val.lower() in _NULL_STRINGS:
            annotated[k] = None
            continue

        # Determine confidence based on source and OCR quality
        if source == "producer":
            confidence = "filled"
        else:
            norm_val  = _normalize_for_ocr_check(str_val.lower(), field=k)
            ocr_confident = not any(
                token and len(token) >= 3
                and re.search(rf"\b{re.escape(token)}\b", norm_val)
                for token in low_conf_set
            )
            confidence = "ai_high" if ocr_confident else "ai_low"
        
        annotated[k] = {
            "value": str_val,
            "confidence": confidence,
            "source": source
        }
        
        if confidence == "ai_low" and k in _OCR_CRITICAL_FIELDS:
            manual_confirmation_required.append(k)

    return annotated, manual_confirmation_required


# ── Core extraction ───────────────────────────────────────────────────────────

# ASYNC-SAFE
async def extract_facts(
    text: str,
    low_confidence_tokens: Optional[List[str]] = None,
    context_prefix: str = "",
    source: str = "ai",
) -> dict:
    """
    Single-chunk extraction.
    Pipeline: LLM → _safe_json_parse → _validate_parsed → _annotate_facts (strict order).
    Cache key: model + PROMPT_VERSION + SCHEMA_VERSION + ctx_hash + lct_hash + text.
    Raises RuntimeError on any failure — never swallowed.
    """
    if len(text) < 30:
        return {"facts": {}, "flags": {}}

    ctx_hash = hashlib.md5(context_prefix.encode(), usedforsecurity=False).hexdigest()[:8]
    lct_hash = hashlib.md5(
        json.dumps(sorted(low_confidence_tokens or [])).encode(),
        usedforsecurity=False,
    ).hexdigest()[:8]
    ck = _cache_key(text, ACTIVE_MODEL, ctx_hash, lct_hash)

    cached = await _cache_get(ck)
    if cached is not None:
        logger.info(f"extract_facts: cache HIT key={ck[:8]} — returning cached result, no LLM call")
        return cached

    low_conf_note = ""
    if low_confidence_tokens:
        unique_tokens = list(dict.fromkeys(low_confidence_tokens))[:40]
        low_conf_note = (
            _LOW_CONF_NOTE_HEADER
            + f"{', '.join(unique_tokens)}\n"
        )

    context_section = ""
    if context_prefix and context_prefix.strip():
        context_section = (
            "\n\nPREVIOUS CONTEXT (reference only — do NOT re-extract from this; "
            "extract ONLY from PRIMARY TEXT below):\n"
            f"---\n{context_prefix.strip()}\n---\n"
        )
    _EXTRACT_PROMPT_SUFFIX = (
        '\n\nCRITICAL REMINDER: Your response MUST be a single JSON object with EXACTLY '
        'these two top-level keys: "facts" and "flags". No other keys. No markdown. '
        'Start your response with { and end with }.'
    )

    prompt = (
        _EXTRACT_PROMPT_PREFIX
        + context_section
        + f'PRIMARY TEXT:\n"""\n{text}\n"""{low_conf_note}'
        + _EXTRACT_PROMPT_SUFFIX
    )

    raw = await groq_chat(LLM_MODEL, [{"role": "user", "content": prompt}], max_tokens=16000)

    result   = await _safe_json_parse(raw, context=f"key={ck[:8]}")
    annotated, manual_conf = _annotate_facts(result["facts"], low_confidence_tokens, source=source)
    result["facts"] = annotated
    if manual_conf:
        result["manual_confirmation_required"] = manual_conf

    await _cache_set(ck, result)
    return result


# ── Scored merge ──────────────────────────────────────────────────────────────

_TIER_WEIGHTS: Dict[str, float] = {"tier1": 1.5, "tier2": 1.2, "default": 1.0}


def _get_field_tier(field: str) -> str:
    try:
        from services.fact_registry import FACT_REGISTRY
        t = FACT_REGISTRY.get(field, {}).get("tier")
        if t == 1:
            return "tier1"
        if t == 2:
            return "tier2"
    except Exception:
        pass
    return "default"


# Structured dict fields: frequency is meaningless as a quality signal because
# the LLM produces a full object each time — identical keys with different boolean
# values count as distinct candidates.  Score by confidence only.
_STRUCTURED_SCORE_FIELDS = frozenset({
    "risk_transfer", "wc_payroll_by_state", "wc_monopolistic_payroll",
})

# Currency fields where a larger non-zero magnitude is a stronger signal.
_CURRENCY_FIELDS = frozenset({
    "total_revenue", "total_payroll", "wc_payroll", "property_building_value",
    "property_bpp_value", "gl_limits", "gl_aggregate", "gl_each_occurrence",
    "auto_liability_limit", "umbrella_limit", "business_income_limit",
    "extra_expense_limit", "umbrella_sir", "umbrella_attachment_point",
})


def _currency_magnitude(sval: str) -> float:
    """Extract numeric magnitude from a currency string for tiebreaking."""
    try:
        return float(re.sub(r"[^\d.]", "", sval))
    except Exception:
        return 0.0


def _score_value(field: str, record: Any, freq: int) -> float:
    tier_weight = _TIER_WEIGHTS[_get_field_tier(field)]

    # Extract confidence from annotated dict
    conf = "ai_low"  # default
    if isinstance(record, dict) and "confidence" in record:
        conf = record["confidence"]

    CONF_WEIGHTS = {
        "deterministic": 1.0,
        "filled":        1.0,
        "ai_high":       0.85,
        "ai_low":        0.50,
    }
    conf_score = CONF_WEIGHTS.get(conf, 0.5)

    # Structured dicts: frequency is not a meaningful quality signal — skip it.
    if field in _STRUCTURED_SCORE_FIELDS:
        return tier_weight * conf_score

    freq_score = math.log1p(freq)
    return tier_weight * (freq_score + conf_score)


# ── Schedule row dedup ────────────────────────────────────────────────────────
# _merge_list_fields' cross-chunk merge below only dedupes byte-identical rows
# (exact JSON match). That misses the common real case: the SAME driver/entity
# appearing on two document pages/chunks with a formatting difference (a DL#
# filled in on one page and blank on another, different name capitalization).
# For list keys registered here, rows are merged by a natural key instead -
# duplicates are combined (first non-empty value per sub-key wins) rather than
# kept as separate rows. List keys with no entry here are completely unaffected
# (identity passthrough), so this only changes behavior for auto_drivers today.

def _driver_dedup_keys(item: dict) -> List[str]:
    """Candidate natural keys for one auto_drivers row: license number (a
    real-world driver has exactly one) AND normalized name+dob, when present.
    Returning BOTH (not just whichever is available) lets a row missing its
    license number still match an earlier row that has one, as long as the
    name+dob agree - the common case where one page/chunk lists a driver
    without their DL# and another page lists the same driver with it.

    DOB is normalized to ISO form via normalize_date() rather than compared as
    a raw string. Found via live test 2026-07-13: the same real duplicate
    driver (identical DOB) intermittently failed to merge because the model
    extracted the date in two different valid formats ("07/22/1979" vs
    "7/22/1979") across the two mentions - an exact-string comparison treated
    those as different people. Falls back to the raw stripped string if the
    value isn't a parseable date, so behavior is unchanged for anything
    normalize_date() can't handle."""
    keys: List[str] = []
    lic = re.sub(r"[\s-]", "", str(item.get("license_number") or "")).strip().upper()
    if lic:
        keys.append(f"lic:{lic}")
    name = str(item.get("name") or "").strip().lower()
    if name:
        dob_raw = str(item.get("dob") or "").strip()
        dob_key = normalize_date(dob_raw) or dob_raw
        keys.append(f"name:{name}|dob:{dob_key}")
    return keys


_SCHEDULE_DEDUP_KEYS: Dict[str, Any] = {
    "auto_drivers": _driver_dedup_keys,
}


def _dedupe_schedule_rows(list_key: str, items: List[dict]) -> List[dict]:
    """Merge rows describing the same entity (per _SCHEDULE_DEDUP_KEYS),
    filling gaps from later duplicates rather than dropping their data. Two
    rows merge if ANY of their candidate keys match (see _driver_dedup_keys).
    Returns ``items`` unchanged for any list_key with no registered key fn."""
    key_fn = _SCHEDULE_DEDUP_KEYS.get(list_key)
    if key_fn is None:
        return items
    groups: List[dict] = []
    key_to_group: Dict[str, int] = {}
    unkeyed: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            unkeyed.append(item)
            continue
        keys = key_fn(item)
        if not keys:
            unkeyed.append(item)
            continue
        group_idx = next((key_to_group[k] for k in keys if k in key_to_group), None)
        if group_idx is None:
            group_idx = len(groups)
            groups.append(dict(item))
        else:
            existing = groups[group_idx]
            for sub_key, val in item.items():
                if _is_empty(existing.get(sub_key)) and not _is_empty(val):
                    existing[sub_key] = val
        for k in keys:
            key_to_group[k] = group_idx
    return groups + unkeyed


def _merge_list_fields(partials: List[dict], list_keys: List[str]) -> dict:
    if not partials:
        return {"facts": {}, "flags": {}}
    if len(partials) == 1:
        p = dict(partials[0])
        for k in ("_chunk_idx", "_char_start", "_char_end"):
            p.pop(k, None)
        raw_facts = p.get("facts")
        if isinstance(raw_facts, dict) and any(k in _SCHEDULE_DEDUP_KEYS for k in list_keys):
            facts = dict(raw_facts)
            for lk in list_keys:
                items = facts.get(lk)
                if isinstance(items, list) and items:
                    deduped = _dedupe_schedule_rows(lk, items)
                    if lk in _SCHEDULE_DEDUP_KEYS and len(deduped) != len(items):
                        logger.info(
                            "merge schedule_dedup field=%r partials=1 (single-chunk doc) "
                            "rows_before=%d rows_after=%d",
                            lk, len(items), len(deduped),
                        )
                    facts[lk] = deduped
            p["facts"] = facts
        return p

    val_candidates: Dict[str, Dict[str, dict]] = {}
    for partial in sorted(partials, key=lambda p: p.get("_chunk_idx", 0)):
        for k, v in partial.get("facts", {}).items():
            if k in list_keys or k == "wc_payroll_by_state" or _is_empty(v):
                continue
            # Extract canonical string value from annotated or raw form
            raw_val = v.get("value", v) if isinstance(v, dict) and "value" in v else v
            if _is_empty(raw_val):
                continue
            sval     = str(raw_val).strip()
            norm_key = sval.lower()
            val_candidates.setdefault(k, {})
            if norm_key not in val_candidates[k]:
                val_candidates[k][norm_key] = {"record": v, "freq": 0}
            val_candidates[k][norm_key]["freq"] += 1

    merged_facts: dict = {}

    for field, candidates in val_candidates.items():
        scored = sorted(
            [(nk, _score_value(field, c["record"], c["freq"]), c) for nk, c in candidates.items()],
            key=lambda x: x[1], reverse=True,
        )

        # Tiebreaker for currency fields: equal score → prefer larger non-zero magnitude.
        # This prevents "$0" from beating "$8,750,000" when both appear once.
        if (
            field in _CURRENCY_FIELDS
            and len(scored) >= 2
            and abs(scored[0][1] - scored[1][1]) < 0.01   # effectively tied
        ):
            scored = sorted(
                scored,
                key=lambda x: _currency_magnitude(x[0]),
                reverse=True,
            )
            if _currency_magnitude(scored[0][0]) > 0:
                logger.info(
                    f"merge field={field!r} currency tiebreak: "
                    f"chose {scored[0][0]!r} over {scored[1][0]!r} by magnitude"
                )

        winner_nk, winner_score, winner_c = scored[0]
        merged_facts[field] = winner_c["record"]
        if len(scored) > 1:
            rejected = [
                f"{nk!r}(score={sc:.2f},freq={c['freq']})"
                for nk, sc, c in scored[1:]
            ]
            logger.info(
                f"merge field={field!r} chosen={winner_nk!r} "
                f"score={winner_score:.2f} freq={winner_c['freq']} "
                f"rejected=[{', '.join(rejected)}]"
            )

    for lk in list_keys:
        seen: dict = {}
        for partial in partials:
            for item in (partial.get("facts", {}).get(lk) or []):
                seen.setdefault(json.dumps(item, sort_keys=True), item)
        if seen:
            before = list(seen.values())
            after = _dedupe_schedule_rows(lk, before)
            if lk in _SCHEDULE_DEDUP_KEYS and len(after) != len(before):
                logger.info(
                    "merge schedule_dedup field=%r partials=%d rows_before=%d rows_after=%d",
                    lk, len(partials), len(before), len(after),
                )
            merged_facts[lk] = after

    # wc_payroll_by_state: scored per state
    wc_candidates: Dict[str, Dict[str, dict]] = {}
    for partial in partials:
        for state, amount in (partial.get("facts", {}).get("wc_payroll_by_state") or {}).items():
            if _is_empty(amount):
                continue
            amt_str  = str(amount).strip()
            norm_key = amt_str.lower()
            wc_candidates.setdefault(state, {})
            if norm_key not in wc_candidates[state]:
                wc_candidates[state][norm_key] = {"record": amt_str, "freq": 0}
            wc_candidates[state][norm_key]["freq"] += 1

    if wc_candidates:
        merged_wc: dict = {}
        for state, candidates in wc_candidates.items():
            scored_wc = sorted(
                [(nk, _score_value("wc_payroll_by_state", {"value": c["record"]}, c["freq"]), c)
                 for nk, c in candidates.items()],
                key=lambda x: x[1], reverse=True,
            )
            merged_wc[state] = scored_wc[0][2]["record"]
        merged_facts["wc_payroll_by_state"] = merged_wc

    claim_vals = []
    for partial in partials:
        raw = partial.get("facts", {}).get("num_claims")
        val = raw.get("value", raw) if isinstance(raw, dict) and "value" in raw else raw
        if val:
            try:
                claim_vals.append(int(str(val).replace(",", "")))
            except ValueError:
                pass
    if claim_vals:
        merged_facts["num_claims"] = {"value": str(max(claim_vals)), "confidence": "ai_high", "source": "ai"}

    merged_flags: dict = {}
    for partial in partials:
        for k, v in partial.get("flags", {}).items():
            if k == "narrative_components":
                continue  # OR-merged below
            if isinstance(v, bool):
                merged_flags[k] = merged_flags.get(k, False) or v
            elif k not in merged_flags or merged_flags[k] is None:
                merged_flags[k] = v

    # OR-merge narrative_components: a component is present if any chunk/doc detected it
    # with a non-empty evidence quote (evidence-gate prevents false positives).
    _nc_merged: dict = {}
    for partial in partials:
        for comp, data in ((partial.get("flags") or {}).get("narrative_components") or {}).items():
            if isinstance(data, dict) and data.get("present") and data.get("evidence"):
                if not _nc_merged.get(comp, {}).get("present"):
                    _nc_merged[comp] = data
    if _nc_merged:
        merged_flags["narrative_components"] = _nc_merged

    return {"facts": merged_facts, "flags": merged_flags}


# ── Reconciliation ────────────────────────────────────────────────────────────

def _build_reconciliation_payload(
    partials: List[dict],
    raw_text: str,
) -> Optional[Dict[str, dict]]:
    conflicts: Dict[str, dict] = {}

    for k in _OCR_CRITICAL_FIELDS:
        val_data: Dict[str, dict] = {}

        for p in partials:
            v = p.get("facts", {}).get(k)
            if _is_empty(v):
                continue
            raw_val = v.get("value", v) if isinstance(v, dict) and "value" in v else v
            if _is_empty(raw_val):
                continue
            sval     = str(raw_val).strip()
            norm_key = sval.lower()

            val_data.setdefault(norm_key, {"original": sval, "freq": 0, "snippets": []})
            val_data[norm_key]["freq"] += 1

            if len(val_data[norm_key]["snippets"]) < 3:
                c_start = p.get("_char_start", 0)
                c_end   = p.get("_char_end", len(raw_text))
                region  = raw_text[c_start:c_end]
                idx     = region.lower().find(sval.lower())
                if idx >= 0:
                    snip = region[max(0, idx - 100) : idx + len(sval) + 100].strip()
                else:
                    snip = region[:200].strip()
                if snip and snip not in val_data[norm_key]["snippets"]:
                    val_data[norm_key]["snippets"].append(snip)

        if len(val_data) > 1:
            conflicts[k] = {
                entry["original"]: {
                    "frequency": entry["freq"],
                    "contexts":  entry["snippets"],
                }
                for entry in val_data.values()
            }

    return conflicts if conflicts else None


def _name_quality_score(s: str) -> float:
    """
    Heuristic score for applicant_name candidates.
    Longer, title-cased, multi-word strings score higher than short partial names.
    Used as a deterministic tiebreaker before calling the LLM.
    """
    s = s.strip()
    score = 0.0
    score += min(len(s) / 40.0, 1.0) * 0.5          # length up to 40 chars: 0–0.5
    words = s.split()
    if len(words) >= 2:
        score += 0.3                                   # multi-word bonus
    if s == s.title() or s.isupper():
        score += 0.2                                   # proper casing bonus
    # Business entity suffix bonus (LLC, Inc, Corp, etc.)
    _BIZ_SUFFIXES = {"llc", "inc", "corp", "co", "ltd", "lp", "llp", "pllc",
                     "incorporated", "corporation", "company", "limited"}
    if any(w.rstrip(".,").lower() in _BIZ_SUFFIXES for w in words):
        score += 0.3
    return score


def _deterministic_reconcile(field: str, candidates: Dict[str, dict]) -> Optional[str]:
    """
    Resolve a conflict deterministically without an LLM call.
    Returns the winning original value string, or None if no clear winner.

    Rules (in priority order):
      1. applicant_name / mailing_address: pick candidate with highest _name_quality_score.
         If the top score is ≥0.3 more than second place, it wins outright.
      2. effective_date / expiration_date: pick the value with the highest frequency.
         On a tie, keep the current merged value (caller should not overwrite).
      3. All other fields: return None → fall through to LLM.
    """
    if not candidates:
        return None

    # Sort by frequency descending as a baseline
    by_freq = sorted(candidates.items(), key=lambda x: x[1]["frequency"], reverse=True)
    top_val, top_data = by_freq[0]

    if field == "applicant_name":
        scored = sorted(
            candidates.items(),
            key=lambda x: _name_quality_score(x[0]),
            reverse=True,
        )
        best_val, _ = scored[0]
        if len(scored) > 1:
            second_val, _ = scored[1]
            gap = _name_quality_score(best_val) - _name_quality_score(second_val)
            if gap >= 0.3:
                logger.info(
                    f"reconciliation deterministic: applicant_name → {best_val!r} "
                    f"(quality gap={gap:.2f})"
                )
                return best_val
        # No clear quality winner — fall through to LLM
        return None

    if field in ("effective_date", "expiration_date", "fein", "policy_number"):
        if len(by_freq) >= 2 and by_freq[0][1]["frequency"] > by_freq[1][1]["frequency"]:
            logger.info(
                f"reconciliation deterministic: {field} → {top_val!r} "
                f"(freq={top_data['frequency']})"
            )
            return top_val
        return None  # tie → LLM

    return None  # unknown field → LLM


# ASYNC-SAFE
async def _run_reconciliation(conflicts: Dict[str, dict], result: dict) -> None:
    """
    Resolve per-field conflicts between chunk extractions.

    Two-stage approach:
      1. Deterministic tiebreakers (_deterministic_reconcile) — no LLM, no latency.
         Handles applicant_name quality scoring and date/FEIN frequency wins.
      2. LLM fallback — only called for fields that deterministic couldn't resolve,
         with an enriched prompt that warns against short/partial names.

    Hallucinated values (not in allowed candidate set) are always rejected.
    Non-fatal — keeps merged result on any exception.
    """
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())

    allowed: Dict[str, set] = {}
    for field, values_dict in conflicts.items():
        allowed[field] = {_norm(v) for v in values_dict.keys()}

    # Stage 1: deterministic resolution
    llm_conflicts: Dict[str, dict] = {}
    for field, values_dict in conflicts.items():
        winner = _deterministic_reconcile(field, values_dict)
        if winner is not None:
            old = result.get("facts", {}).get(field)
            result["facts"][field] = {
                "value": winner,
                "confidence": "ai_high",
                "source": "ai",
                "reconciled": True,
                "reconcile_method": "deterministic",
            }
            logger.info(f"reconciliation field={field!r} resolved={winner!r} was={old!r} (deterministic)")
        else:
            llm_conflicts[field] = values_dict

    if not llm_conflicts:
        return

    # Stage 2: LLM for remaining unresolved fields
    try:
        prompt = (
            "You are resolving conflicts in extracted insurance document facts.\n"
            "For each field, pick the most accurate value from the candidates.\n\n"
            "IMPORTANT RULES:\n"
            "  - applicant_name: prefer the FULL legal business name (e.g. 'TechVision Solutions Inc.')\n"
            "    over short partial names or first-name-only values (e.g. 'raj k').\n"
            "    A longer, properly formatted business name is almost always more accurate.\n"
            "  - effective_date: prefer the date with higher frequency; if equal, prefer\n"
            "    the more recent date.\n"
            "  - For all fields: higher frequency + more specific context = stronger signal.\n"
            "  - The chosen value MUST be one of the provided candidates exactly as shown.\n"
            "Return ONLY a JSON object: {\"field_name\": \"chosen_value\"}.\n\n"
            "Conflicts:\n" + json.dumps(llm_conflicts, indent=2)
        )
        raw      = await groq_chat(LLM_MODEL, [{"role": "user", "content": prompt}], max_tokens=4096)
        resolved = _parse_flat_json(raw, context="reconciliation")
        for k, v in resolved.items():
            if k not in _OCR_CRITICAL_FIELDS or _is_empty(v):
                continue
            chosen_str  = str(v).strip()
            chosen_norm = _norm(chosen_str)
            if chosen_norm not in allowed.get(k, set()):
                logger.warning(
                    f"reconciliation: field={k!r} LLM chose {chosen_str!r} "
                    f"(norm={chosen_norm!r}) NOT in candidates "
                    f"{list(allowed.get(k, set()))} — rejecting"
                )
                continue
            old = result.get("facts", {}).get(k)
            result["facts"][k] = {
                "value": chosen_str,
                "confidence": "ai_high",
                "source": "ai",
                "reconciled": True,
                "reconcile_method": "llm",
            }
            logger.info(f"reconciliation field={k!r} resolved={chosen_str!r} was={old!r} (llm)")
    except Exception as ex:
        logger.warning(f"_run_reconciliation: non-fatal failure — {ex}")


# ── Fix 1: Adaptive semaphore — no blocking in record(), no semaphore swap ────

class _AdaptiveSemaphore:
    """
    Fix 1: concurrency enforced ONLY in __aenter__ via _target_level check.
    record() NEVER blocks — it only updates _target_level.
    Scale-down: __aenter__ waits when active >= _target_level (condition-based).
    Scale-up: condition notified so waiters can proceed.
    No semaphore object is ever replaced mid-flight.
    No draining in record(). No busy loops.
    """
    _INIT            = 1
    _MIN             = 1
    _MAX             = 3
    _RETRY_THRESHOLD = 0.30
    _STABLE_WINDOW   = 10

    def __init__(self) -> None:
        self._target_level = self._INIT
        self._active       = 0          # count of coroutines currently inside context
        self._lock         = asyncio.Lock()
        self._condition    = asyncio.Condition(self._lock)
        self._retries      = 0
        self._calls        = 0
        self._stable       = 0

    async def __aenter__(self):
        async with self._condition:
            # Wait until active count is below target level
            while self._active >= self._target_level:
                await self._condition.wait()
            self._active += 1
        return self

    async def __aexit__(self, *_):
        async with self._condition:
            self._active -= 1
            self._condition.notify_all()

    async def record(self, retried: bool) -> None:
        """
        Non-blocking stats update. Updates _target_level only.
        notify_all() wakes any waiters in __aenter__ when level increases.
        """
        async with self._condition:
            self._calls += 1
            if retried:
                self._retries += 1
                self._stable   = 0
            else:
                self._stable  += 1

            if self._calls % 10 == 0:
                rate = self._retries / self._calls
                if rate > self._RETRY_THRESHOLD and self._target_level > self._MIN:
                    new = max(self._MIN, self._target_level - 1)
                    self._target_level = new
                    # No notify needed on reduction — __aenter__ naturally
                    # blocks new entrants; existing holders finish unaffected.
                    logger.warning(f"AdaptiveSem: retry_rate={rate:.0%} concurrency →{new}")
                elif rate <= self._RETRY_THRESHOLD and self._stable >= self._STABLE_WINDOW:
                    if self._target_level < self._MAX:
                        new = min(self._MAX, self._target_level + 1)
                        self._target_level = new
                        self._stable       = 0
                        self._condition.notify_all()   # wake waiters — more slots available
                        logger.info(f"AdaptiveSem: stable concurrency →{new}")


# ── Async extraction ──────────────────────────────────────────────────────────

# ASYNC-SAFE
async def extract_facts_async(
    text: str,
    low_confidence_tokens: Optional[List[str]] = None,
    context_prefix: str = "",
    source: str = "ai",
) -> dict:
    """
    Async wrapper with jittered exponential backoff for transient errors.
    RuntimeError (JSON/schema failure) propagates immediately — not transient.
    All retries live here. Per-chunk retries in _gather_chunks_async are additional.
    """
    _TRANSIENT      = ("rate", "timeout", "connection", "503", "502", "500", "429",
                       "413", "service unavailable", "temporarily")
    # Rate-limit signals — applies to all providers (OpenAI 429, Groq 413/TPM, etc.)
    _RATE_LIM_MARKS = ("rate_limit", "413", "tokens per minute", "tpm", "rate limit exceeded",
                       "requests per minute", "rpm")
    last_ex: Optional[Exception] = None
    for attempt in range(3):
        try:
            return await extract_facts(text, low_confidence_tokens, context_prefix, source)
        except RuntimeError:
            raise
        except Exception as ex:
            last_ex = ex
            msg = str(ex).lower()
            if attempt < 2 and any(t in msg for t in _TRANSIENT):
                if any(m in msg for m in _RATE_LIM_MARKS):
                    # Rate-limited — wait for provider bucket to refill before retrying.
                    wait = 62.0 + random.uniform(0, 5)
                    logger.warning(
                        f"extract_facts_async: rate-limited attempt={attempt + 1}/3 "
                        f"waiting {wait:.0f}s — {ex}"
                    )
                else:
                    base   = 2 ** attempt
                    jitter = random.uniform(-0.25 * base, 0.25 * base)
                    wait   = max(0.5, base + jitter)
                    logger.warning(
                        f"extract_facts_async: transient attempt={attempt + 1}/3 wait={wait:.2f}s — {ex}"
                    )
                await asyncio.sleep(wait)
                continue
            raise
    raise last_ex


async def _gather_chunks_async(
    chunks: List[ChunkTuple],
    low_confidence_tokens: Optional[List[str]],
    doc_type: str,
) -> List[dict]:
    sem             = _AdaptiveSemaphore()
    total_llm_calls = 0

    # Inter-chunk pacing — tunable via env vars (defaults suit OpenAI rate limits).
    _PRE_CALL_DELAY  = float(os.getenv("CHUNK_PRE_CALL_DELAY",  "0.1"))
    _POST_CALL_DELAY = float(os.getenv("CHUNK_POST_CALL_DELAY", "0.1"))
    # Per-chunk retry budget — retried inside _one before marking chunk_failed.
    _CHUNK_MAX_RETRIES = int(os.getenv("CHUNK_MAX_RETRIES", "3"))

    async def _one(idx: int, chunk_text: str, c_start: int, c_end: int, ctx: str) -> dict:
        nonlocal total_llm_calls
        last_ex: Optional[Exception] = None
        async with sem:
            for attempt in range(_CHUNK_MAX_RETRIES):
                try:
                    await asyncio.sleep(_PRE_CALL_DELAY)
                    total_llm_calls += 1
                    result = await extract_facts_async(chunk_text, low_confidence_tokens, ctx, source="ai")
                    await asyncio.sleep(_POST_CALL_DELAY)
                    result.update({"_chunk_idx": idx, "_char_start": c_start, "_char_end": c_end})
                    await sem.record(retried=(attempt > 0))
                    if attempt > 0:
                        logger.info(f"chunk {idx}: recovered on attempt {attempt + 1} chars={c_start}–{c_end}")
                    else:
                        logger.debug(f"chunk {idx}: ok chars={c_start}–{c_end}")
                    return result
                except RuntimeError:
                    # Schema/JSON failure — not transient, do not retry.
                    raise
                except Exception as ex:
                    # Permanent errors — retrying will never succeed, fail fast to avoid
                    # burning API quota and spamming the upstream provider:
                    #   • HTTP 400  → bad parameter / unsupported model flag (API rejection)
                    #   • TypeError → SDK signature mismatch (e.g. unknown kwarg in installed
                    #                  openai version) — raised by the Python client, not the API
                    #   • AttributeError → SDK shape mismatch (missing attr on response object)
                    if (
                        getattr(ex, "status_code", None) == 400
                        or isinstance(ex, (TypeError, AttributeError))
                    ):
                        logger.error(
                            f"chunk {idx} (chars {c_start}–{c_end}): permanent error — not retrying: "
                            f"{type(ex).__name__}: {ex}"
                        )
                        raise
                    last_ex = ex
                    wait = 2 ** attempt + random.uniform(0, 0.5)
                    logger.warning(
                        f"chunk {idx} attempt {attempt + 1}/{_CHUNK_MAX_RETRIES} "
                        f"(chars {c_start}–{c_end}) failed — retrying in {wait:.1f}s: {ex}"
                    )
                    if attempt < _CHUNK_MAX_RETRIES - 1:
                        await asyncio.sleep(wait)
            # All retries exhausted — mark as failed but preserve metadata for audit.
            logger.error(
                f"chunk {idx} (chars {c_start}–{c_end}): all {_CHUNK_MAX_RETRIES} attempts failed — {last_ex}"
            )
            await sem.record(retried=True)
            return {
                "facts": {}, "flags": {},
                "_chunk_idx": idx, "_char_start": c_start, "_char_end": c_end,
                "chunk_failed": True, "chunk_error": str(last_ex),
            }

    results = list(await asyncio.gather(*[
        _one(i, ct, cs, ce, cx) for i, (ct, cs, ce, cx) in enumerate(chunks)
    ]))
    failed        = sum(1 for r in results if r.get("chunk_failed"))
    total_chars   = sum(r.get("_char_end", 0) - r.get("_char_start", 0) for r in results)
    failed_ranges = [
        f"{r['_char_start']}–{r['_char_end']}"
        for r in results if r.get("chunk_failed")
    ]
    logger.info(
        f"gather_chunks doc_type='{doc_type}' chunks={len(chunks)} failed={failed} "
        f"llm_calls={total_llm_calls} total_chars_processed={total_chars}"
        + (f" failed_ranges={failed_ranges}" if failed_ranges else "")
    )
    return results


# ── Transient runtime error classification ────────────────────────────────────

_TRANSIENT_RUNTIME_MARKERS = (
    "permanently failed",
    "rate", "timeout", "connection", "503", "502", "500", "429",
)


def _is_transient_runtime_error(err: RuntimeError) -> bool:
    msg = str(err).lower()
    return any(m in msg for m in _TRANSIENT_RUNTIME_MARKERS)


# ── Fix 6: num_claims row-level deduplication ─────────────────────────────────

# Anchors that appear once per claim row in well-structured loss runs.
# "date of loss" is used rather than "claimant" because it appears exactly
# once per row and is less likely to appear in headers or footers.
# Fallback to "claimant" if date-of-loss count is zero.
_CLAIM_ROW_ANCHOR_PRIMARY   = re.compile(r"date\s+of\s+loss", re.I)
_CLAIM_ROW_ANCHOR_SECONDARY = re.compile(r"\bclaimant\b", re.I)
# Lines that are clearly headers — excluded from row count
_CLAIM_HEADER_RE = re.compile(
    r"(?:date\s+of\s+loss|claim\s*(?:no|number|#)|claimant|description|status|reserve|paid|incurred)",
    re.I,
)


def _count_claims_from_text(text: str) -> int:
    """
    Fix 6: Line-based deduplication. Count unique lines matching a claim-row anchor.
    Header detection: lines where ALL common claim column labels appear together
    on a single line → excluded (those are table headers, not claim rows).
    Returns 0 if no anchors found.
    """
    lines = text.splitlines()
    claim_lines: set = set()

    for line_no, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Header heuristic: line contains 3+ column label keywords → skip
        header_hits = len(_CLAIM_HEADER_RE.findall(stripped))
        if header_hits >= 3:
            continue

        # Primary anchor: "date of loss" appears on this line → it's a claim row
        if _CLAIM_ROW_ANCHOR_PRIMARY.search(stripped):
            claim_lines.add(line_no)

    if not claim_lines:
        # Fallback: count unique lines with "claimant" not in a header
        for line_no, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            header_hits = len(_CLAIM_HEADER_RE.findall(stripped))
            if header_hits >= 3:
                continue
            if _CLAIM_ROW_ANCHOR_SECONDARY.search(stripped):
                claim_lines.add(line_no)

    return len(claim_lines)


# ── Core pipeline ─────────────────────────────────────────────────────────────

# ASYNC-SAFE
async def _run_extraction(
    text: str,
    doc_type: str,
    low_confidence_tokens: Optional[List[str]],
    chunk_size: int,
    cap: int,
) -> dict:
    overlap_pct = 0.15

    chunks = _chunk_by_sections(
        text,
        max_chars=chunk_size,
        overlap_pct=overlap_pct,
    )

    _verify_coverage(chunks, len(text), doc_type)

    logger.info(
        f"extraction START doc_type='{doc_type}' model='{ACTIVE_MODEL}' "
        f"chunks={len(chunks)} total_chars={len(text)} est_tokens={estimate_tokens(text):,} "
        f"chunk_size={chunk_size}"
    )

    partials = await _gather_chunks_async(chunks, low_confidence_tokens, doc_type)

    failed_partials  = [p for p in partials if p.get("chunk_failed")]
    success_partials = [p for p in partials if not p.get("chunk_failed")]
    failed_indices   = [p["_chunk_idx"] for p in failed_partials]
    failed_ranges    = [f"{p['_char_start']}–{p['_char_end']}" for p in failed_partials]
    fail_ratio       = len(failed_partials) / len(chunks) if chunks else 0.0

    # ── Document-level retry: if majority failed, halve chunk size and retry ──
    if fail_ratio > 0.5 and chunk_size > 1500:
        new_chunk_size = int(chunk_size * 0.6)
        logger.warning(
            f"_run_extraction: majority failed ({len(failed_partials)}/{len(chunks)}), "
            f"retrying with smaller chunks {chunk_size} → {new_chunk_size}"
        )
        return await _run_extraction(text, doc_type, low_confidence_tokens, new_chunk_size, cap)

    # ── Surface failed chunks — NEVER silently discard ────────────────────────
    if failed_partials:
        errors = [p.get("chunk_error", "?") for p in failed_partials]
        covered_chars = sum(
            p.get("_char_end", 0) - p.get("_char_start", 0) for p in success_partials
        )
        failed_chars = sum(
            p.get("_char_end", 0) - p.get("_char_start", 0) for p in failed_partials
        )
        coverage_pct = covered_chars / len(text) if len(text) > 0 else 0.0
        logger.warning(
            f"_run_extraction PARTIAL doc_type='{doc_type}' "
            f"failed={len(failed_partials)}/{len(chunks)} chunks "
            f"failed_indices={failed_indices} failed_ranges={failed_ranges} "
            f"failed_chars={failed_chars} covered_chars={covered_chars} "
            f"coverage={coverage_pct:.1%} errors={errors}"
        )
        # Use only successful partials for merging, but warn downstream.
        merge_partials = success_partials
        extraction_complete = False
    else:
        merge_partials      = partials
        extraction_complete = True

    if not merge_partials:
        raise RuntimeError(
            f"extraction: all {len(chunks)} chunks failed for doc_type='{doc_type}' "
            f"indices={failed_indices} errors={[p.get('chunk_error') for p in failed_partials]}"
        )

    result = _merge_list_fields(merge_partials, list_keys=_LONG_DOC_LIST_KEYS)

    # Full-text coverage verification — log so operators can confirm no silent truncation.
    if extraction_complete:
        total_chunk_chars = sum(
            p.get("_char_end", 0) - p.get("_char_start", 0) for p in merge_partials
        )
        coverage_pct = total_chunk_chars / len(text) if len(text) > 0 else 1.0
        logger.info(
            "_run_extraction FULL_COVERAGE doc_type='%s' chunks=%d "
            "total_chars=%d chunk_chars=%d coverage=%.1f%%",
            doc_type, len(chunks), len(text), total_chunk_chars, coverage_pct * 100,
        )

    # Attach audit metadata so callers can surface warnings to the user.
    if not extraction_complete:
        result["extraction_incomplete"] = True
        result["failed_chunk_count"]    = len(failed_partials)
        result["failed_chunk_ranges"]   = failed_ranges
        result["coverage_pct"]          = round(
            sum(p.get("_char_end", 0) - p.get("_char_start", 0) for p in success_partials) / len(text),
            4,
        ) if len(text) > 0 else 0.0

    if doc_type == "loss_run":
        regex_count = _count_claims_from_text(text)
        if regex_count > 0:
            existing     = result.get("facts", {}).get("num_claims")
            existing_val = 0
            if existing:
                try:
                    existing_val = int(str(
                        existing.get("value", existing)
                        if isinstance(existing, dict) and "value" in existing
                        else existing
                    ).replace(",", ""))
                except (ValueError, TypeError):
                    pass
            if regex_count > existing_val:
                result.setdefault("facts", {})
                result["facts"]["num_claims"] = {
                    "value": str(regex_count),
                    "confidence": "ai_high",
                    "source": "ai",
                }

    conflicts = _build_reconciliation_payload(merge_partials, text)

    if conflicts:
        logger.info(f"reconciliation triggered fields={list(conflicts.keys())}")
        await _run_reconciliation(conflicts, result)
    else:
        logger.info("reconciliation: no conflicts — skipped")

    # Final extraction audit log
    fact_count  = sum(1 for v in result.get("facts", {}).values() if not _is_empty(v))
    status_str  = "FULL" if extraction_complete else f"PARTIAL({len(failed_partials)}/{len(chunks)} chunks failed)"
    logger.info(
        f"extraction DONE doc_type='{doc_type}' status={status_str} "
        f"chunks_ok={len(success_partials)}/{len(chunks)} "
        f"facts_extracted={fact_count} model='{ACTIVE_MODEL}'"
    )

    return result

# ── Unified single+long extraction path ──────────────────────────────────────

# ASYNC-SAFE
async def _extract_any(
    text: str,
    doc_type: str,
    low_confidence_tokens: Optional[List[str]],
) -> dict:
    """
    All documents go through extract_facts() which enforces the full pipeline:
    LLM → _safe_json_parse → _validate_parsed → _annotate_facts.
    chunk_size is computed from the active provider's context budget via
    _effective_chunk_size() — OpenAI gets 100k chars, Claude 28k.
    """
    chunk_size = _effective_chunk_size(ACTIVE_MODEL)
    cap = DOC_TYPE_CHUNK_LIMITS.get(doc_type, DOC_TYPE_CHUNK_LIMITS["default"])

    if len(text) <= chunk_size:
        return await extract_facts(text, low_confidence_tokens, context_prefix="", source="ai")

    return await _run_extraction(text, doc_type, low_confidence_tokens, chunk_size, cap)


# ── Public entry point ────────────────────────────────────────────────────────

# ASYNC-SAFE
async def extract_facts_long(
    text: str,
    doc_type: str,
    low_confidence_tokens: Optional[List[str]] = None,
) -> dict:
    """
    Public extraction entry for all doc types and sizes.
    Raises ValueError on budget/cap violations (not retried — config issues).
    Raises RuntimeError on persistent chunk failures after document-level retry.
    Coverage gaps and deterministic errors are NOT retried.
    """
    t_start = time.monotonic()
    _check_cost_guardrail(text, doc_type)

    try:
        result = await _extract_any(text, doc_type, low_confidence_tokens)
    except ValueError:
        raise
    except RuntimeError as first_err:
        if not _is_transient_runtime_error(first_err):
            raise
        logger.warning(f"extract_facts_long: attempt 1 failed ({first_err}) — doc-level retry")
        wait = 3 + random.uniform(0, 2)
        await asyncio.sleep(wait)
        try:
            result = await _extract_any(text, doc_type, low_confidence_tokens)
        except RuntimeError as second_err:
            raise RuntimeError(
                f"extract_facts_long: doc_type='{doc_type}' failed after 2 attempts. "
                f"Attempt1={first_err} Attempt2={second_err}"
            ) from second_err

    logger.info(
        f"extract_facts_long: done doc_type='{doc_type}' elapsed={time.monotonic() - t_start:.2f}s"
    )
    return result


# ── Source confidence by data type ────────────────────────────────────────────
# Maps each fact field to the ordered list of doc types that are authoritative
# for that field. The first matching doc type in a multi-doc upload wins.
# Fields not listed fall back to the primary doc (legacy behaviour).
_FIELD_CONFIDENCE_SOURCES: Dict[str, Tuple[str, ...]] = {
    # Dec page: authoritative for existing policy data, carrier, limits, named insured
    "named_insured":          ("dec_page", "application"),
    "carrier":                ("dec_page", "quote"),
    "policy_number":          ("dec_page",),
    "policy_effective_date":  ("dec_page", "application"),
    "policy_expiration_date": ("dec_page", "application"),
    "coverage_limits":        ("dec_page", "quote"),
    "premium":                ("dec_page", "quote"),
    "lines_of_business":      ("dec_page", "application"),

    # Application/supplement: authoritative for current operations, exposures, underwriting
    "business_description":          ("application", "dec_page"),
    "annual_revenue":                ("application",),
    "annual_payroll":                ("application",),
    "wc_payroll_by_state":           ("application",),
    "num_employees":                 ("application",),
    "gl_class_codes_by_location":    ("application",),
    "gl_class_code_schedule":        ("application", "payroll_report", "gross_sales_report"),
    "wc_class_codes":                ("application",),
    "fein":                          ("application", "dec_page"),
    "years_in_business":             ("application", "dec_page"),
    "entity_type":                   ("application", "dec_page"),

    # Loss run: authoritative for claims history
    "loss_history":         ("loss_run", "dec_page"),
    "has_losses":           ("loss_run", "dec_page"),
    "prior_coverage_by_line": ("loss_run", "dec_page"),

    # SOV/schedule: authoritative for locations, property values, assets
    "property_locations":   ("schedule", "application"),
    "locations":            ("schedule", "application"),
    "inland_marine_items":  ("schedule",),
}


def _get_authoritative_doc(docs: List[dict], field: str) -> Optional[dict]:
    """Return the doc most authoritative for *field*, or None if no doc has the field."""
    preference = _FIELD_CONFIDENCE_SOURCES.get(field)
    if not preference:
        return None
    # Index docs by doc_type (first doc of each type wins if duplicates)
    by_type: Dict[str, dict] = {}
    for d in docs:
        by_type.setdefault(d.get("doc_type", "unknown"), d)
    for dt in preference:
        if dt in by_type and not _is_empty(by_type[dt].get("facts", {}).get(field)):
            return by_type[dt]
    return None


def _display_scalar(v: Any) -> Any:
    """Coerce a structured-dict sub-value to something readable in a message.

    bool -> Yes/No (raw True/False reads as a coding artifact to a broker);
    list -> sorted comma-joined text (so ['A','B'] vs ['B','A'] never manufacture
    a false conflict purely from extraction order); everything else unchanged.
    """
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, list):
        return ", ".join(sorted(str(x) for x in v if x not in (None, "")))
    return v


# Insurance acronyms that must stay upper-cased when a raw fact key is turned
# into a human label (so "gl_deductible" reads "GL Deductible", not "Gl
# Deductible"). Mirrors the frontend humanizeFact() acronym set.
_LABEL_ACRONYMS = {
    "gl", "wc", "bi", "pd", "el", "um", "uim", "sir", "aop", "acv", "rcv",
    "bpp", "dba", "fein", "vin", "naics", "sic", "coi", "itv", "hnoa", "por",
}

# Friendly prefixes for the structured-dict CONTAINERS. risk_transfer's sub-keys
# ("additional_insured_names", "certificate_holder_name") are self-descriptive,
# so they read best with no container prefix; the WC payroll containers key their
# sub-values by state code ("CA", "NY"), which is meaningless alone, so those DO
# get a prefix. Anything not listed falls back to humanizing the container too.
_CONFLICT_CONTAINER_LABEL = {
    "risk_transfer": "",
    "wc_payroll_by_state": "WC payroll",
    "wc_monopolistic_payroll": "Monopolistic WC payroll",
}


def _humanize_label(token: str) -> str:
    """Turn a snake_case fact token into a readable label, upper-casing known
    insurance acronyms. 'additional_insured_names' -> 'Additional Insured Names';
    'gl_deductible' -> 'GL Deductible'."""
    parts = [p for p in str(token or "").replace(".", " ").split("_") if p]
    if not parts:
        return str(token or "")
    return " ".join(
        p.upper() if p.lower() in _LABEL_ACRONYMS else p[:1].upper() + p[1:]
        for p in parts
    )


def _conflict_field_label(field: str) -> str:
    """Human label for a cross-document conflict's field key, so the producer
    never sees a raw variable like 'risk_transfer.additional_insured_names'.
    Handles the 'container.subkey' shape used by structured-dict facts."""
    if "." in field:
        container, subkey = field.split(".", 1)
        sub_label = _humanize_label(subkey)
        prefix = _CONFLICT_CONTAINER_LABEL.get(container)
        if prefix is None:                       # unknown container: humanize it
            prefix = _humanize_label(container)
        return f"{prefix} - {sub_label}" if prefix else sub_label
    return _humanize_label(field)


def _humanize_conflict_sources(sources: str) -> str:
    """Rewrite the 'doc_type=value, doc_type=value' source string so each source
    shows the DOCUMENT'S readable name, not its internal doc_type token
    ('emod_worksheet=X' -> 'Experience Modification Worksheet: X')."""
    out = []
    for part in sources.split(", "):
        dt, sep, val = part.partition("=")
        if not sep:
            out.append(part)
            continue
        label = DOC_TYPE_LABELS.get(dt.strip(), dt.strip().replace("_", " ").title())
        out.append(f"{label}: {val}")
    return ", ".join(out)


def _structured_dict_field_conflicts(
    field: str, values_by_doc: List[Tuple[str, dict]],
    normalize_value, is_carrier_field,
) -> List[Tuple[str, str, bool]]:
    """Per-sub-key conflict tuples ``(field_key, message, is_carrier)`` for a
    structured dict fact (Fix 4's
    ``_STRUCTURED_DICT_FIELDS`` — e.g. ``risk_transfer``'s mortgagee/loss-payee/
    additional-insured/waiver-of-subrogation/... sub-questions, or
    ``wc_payroll_by_state``'s per-state amounts).

    Comparing the dict as one opaque scalar (``str(dict)``) was the actual bug:
    it bundled every unrelated sub-question into a single unreadable Python-repr
    dump behind one generic "Fix", AND manufactured a conflict any time a SINGLE
    sub-key was populated on only one document — a dict with 8 keys is never
    "empty" even when every value inside it is None/False/[], so the whole-dict
    comparison fired constantly on cases with zero real disagreement. Each
    sub-key is its own underwriting question; it is compared and reported
    independently, exactly like every other scalar field, and only when at
    least two documents actually disagree about THAT sub-key.
    """
    conflicts: List[Tuple[str, str, bool]] = []
    all_subkeys: set = set()
    for _, v in values_by_doc:
        if isinstance(v, dict):
            all_subkeys.update(v.keys())

    for subkey in sorted(all_subkeys):
        sub_values: List[Tuple[str, Any]] = []
        for dt, v in values_by_doc:
            if not isinstance(v, dict):
                continue
            sv = v.get(subkey)
            if _is_empty(sv):
                continue
            sub_values.append((dt, sv))
        if len(sub_values) < 2:
            continue

        # "_name"/"_date"/"_address"/carrier shape inference (normalization.py
        # _infer_field_category) keys off the field NAME's suffix, so composing
        # "risk_transfer_mortgagee_name" reuses the same name-aware normalizer a
        # top-level "mortgagee_name" field would get, with no extra mapping.
        sub_field = f"{field}_{subkey}"
        normalized = {
            n for _, sv in sub_values
            if (n := normalize_value(sub_field, _display_scalar(sv)))
        }
        if len(normalized) <= 1:
            continue

        raw_sources = ", ".join(f"{dt}={_display_scalar(sv)}" for dt, sv in sub_values[:3])
        sources = _humanize_conflict_sources(raw_sources)
        field_key = f"{field}.{subkey}"
        label = _conflict_field_label(field_key)
        is_carrier = is_carrier_field(sub_field)
        if is_carrier:
            msg = (
                f"Carrier names differ across documents for {label} - {sources}. "
                "Flagged for review (possible carrier alias). "
                "Fix: Confirm whether these refer to the same carrier."
            )
        else:
            msg = (
                f"Conflicting values for {label} across documents - {sources}. "
                "Fix: Review and confirm the correct value."
            )
        conflicts.append((field_key, msg, is_carrier))
    return conflicts


def detect_source_conflicts(
    docs: List[dict], skip_fields: Optional[set] = None, return_fields: bool = False,
):
    """
    Compare field values across documents. Return human-readable conflict messages
    for fields that have materially different non-empty values from two or more docs.
    Only checks scalar fields (not lists) to keep noise low. Structured dict fields
    (``_STRUCTURED_DICT_FIELDS``) are compared per sub-key instead — see
    ``_structured_dict_field_conflicts`` — so one field's sub-questions never
    bundle into a single unreadable message.

    ``skip_fields`` lets a more specialised, normalization-aware reconciler own a
    set of fields (e.g. the Core Underwriting Data reconciler owns total_revenue,
    Beta Report §4.3). Those keys are excluded here so a formatting-only
    difference ($1,000,000 vs 1000000) is not double-reported as a raw-string
    conflict.

    ``return_fields`` (default False keeps the historical ``List[str]`` contract
    every existing caller/test relies on). When True, returns
    ``List[(field_key, message, is_carrier)]`` so the pipeline can derive a stable
    ``source_conflict_<field_key>`` code DIRECTLY from the real fact key instead of
    regex-scraping it back out of the (now humanised, label-only) display message —
    the message no longer contains the raw key at all, by design (client #1).
    """
    if len(docs) < 2:
        return []

    # Imported lazily to keep this module import-light and avoid any cycle.
    from services.normalization import (
        normalize_value, is_carrier_field,
    )

    skip_fields = skip_fields or set()
    conflicts: List[Tuple[str, str, bool]] = []
    all_keys: set = set()
    for d in docs:
        all_keys.update(d.get("facts", {}).keys())

    for field in sorted(all_keys):
        if field in _LIST_FIELDS or field in skip_fields:
            continue

        if field in _STRUCTURED_DICT_FIELDS:
            dict_values_by_doc: List[Tuple[str, dict]] = []
            for d in docs:
                v = _fv(d.get("facts", {}), field)
                if isinstance(v, dict):
                    dict_values_by_doc.append((d.get("doc_type", "unknown"), v))
            if len(dict_values_by_doc) < 2:
                continue
            conflicts.extend(_structured_dict_field_conflicts(
                field, dict_values_by_doc, normalize_value, is_carrier_field,
            ))
            continue

        values_by_doc: List[Tuple[str, object]] = []
        for d in docs:
            # Unwrap the {value, confidence, source} envelope before comparison so
            # normalization runs on the actual value, not the dict repr. Without
            # this the confidence/source labels leak into the normalized string and
            # (a) defeat carrier-alias / formatting suppression and (b) flag a
            # false conflict when two docs carry the same value at different
            # confidence (Beta Report §5).
            v = _fv(d.get("facts", {}), field)
            if _is_empty(v):
                continue
            values_by_doc.append((d.get("doc_type", "unknown"), v))
        if len(values_by_doc) < 2:
            continue

        # Beta Report §5: compare NORMALIZED values so formatting/terminology
        # differences (case, punctuation, date format, $1,000,000 vs 1000000,
        # CSL vs Combined Single Limit, LLC vs Limited Liability Company, address
        # abbreviations) do not manufacture a conflict. Values that normalize to
        # '' carry no usable signal and are ignored. Raw values are kept in the
        # message so they remain visible to the user (§5.1).
        normalized = {n for _, v in values_by_doc if (n := normalize_value(field, v))}
        if len(normalized) <= 1:
            continue

        raw_sources = ", ".join(f"{dt}={val}" for dt, val in values_by_doc[:3])
        sources = _humanize_conflict_sources(raw_sources)
        label = _conflict_field_label(field)
        is_carrier = is_carrier_field(field)
        if is_carrier:
            # §5.2 carrier handling: surface as a REVIEW item when the seed alias
            # map cannot collapse the names, never as a definitive hard conflict.
            msg = (
                f"Carrier names differ across documents for {label} - {sources}. "
                "Flagged for review (possible carrier alias). "
                "Fix: Confirm whether these refer to the same carrier."
            )
        else:
            msg = (
                f"Conflicting values for {label} across documents - {sources}. "
                "Fix: Review and confirm the correct value."
            )
        conflicts.append((field, msg, is_carrier))

    if return_fields:
        return conflicts
    return [m for _, m, _ in conflicts]


# ── Multi-doc merge ───────────────────────────────────────────────────────────

def _consolidate_property_locations(facts: dict) -> None:
    """Consolidate `locations` / `property_locations` into ONE canonical,
    deduplicated multi-location list (Beta Report Figure 27 fix).

    Chunk-level and cross-document merge (`_merge_list_fields`) only dedupe
    list items by EXACT string/JSON equality. The same physical location
    mentioned with slightly different formatting at multiple points in the
    source document(s) - dec page, an attached ACORD 823, a certificate -
    therefore survives as several near-duplicate entries. This pass re-groups
    every entry by NORMALIZED address (services.normalization.normalize_address,
    the same function already used to compare addresses elsewhere), merges
    whatever sub-fields each near-duplicate mention contributed (nothing is
    discarded), decomposes the address into line1/city/state/zip for per-slot
    ACORD stamping, and derives the boolean indicators the PDF checkboxes need.

    Mutates `facts` in place. Runs once, after chunk + cross-document merge
    are both complete, so it is the single source of truth every multi-row
    ACORD schedule (125/131/140/160/186 all reuse these same ACORD field
    concepts - see pdf_service._SCHEDULE_REGISTRY) stamps from.
    """
    from services.normalization import normalize_address
    from utils.helpers import _parse_address

    raw_objs  = facts.get("property_locations") or []
    raw_addrs = facts.get("locations") or []

    entries: List[dict] = []
    for item in raw_objs:
        entries.append(dict(item) if isinstance(item, dict) else {"address": str(item)})
    for addr in raw_addrs:
        if addr:
            entries.append({"address": str(addr)})

    if not entries:
        # No dedicated location list at all - fall back to the submission-level
        # address scalars so slot A of a multi-row schedule (e.g. ACORD 125
        # premises) is never blank just because no location list was extracted.
        fallback = _fv(facts, "physical_address") or _fv(facts, "mailing_address")
        if fallback:
            entries.append({"address": str(fallback)})

    if not entries:
        return

    # Decompose each entry's address UP FRONT so grouping and merging both key
    # off the STABLE street-line identity rather than the full address string.
    # A bare street mention ("4800 Dahlia St #D13") and a fully-qualified
    # mention of the SAME street ("4800 Dahlia St #D13, Denver, CO 80216-3121")
    # must dedupe together - city/state/zip are frequently present on one
    # mention and dropped on another (chunk truncation, a summary line vs. a
    # detail line), while the street line itself is the stable identifier for
    # "this building." This mirrors the client's own §5.2 normalization
    # examples, which compare on the street line, not the full address.
    for entry in entries:
        addr = str(entry.get("address") or "").strip()
        if not addr:
            continue
        parsed = _parse_address(addr)
        entry.setdefault("address_line1", parsed.get("line1"))
        entry.setdefault("address_city",  parsed.get("city"))
        entry.setdefault("address_state", parsed.get("state"))
        entry.setdefault("address_zip",   parsed.get("zip"))

    groups: Dict[str, dict] = {}
    order: List[str] = []
    for entry in entries:
        addr  = str(entry.get("address") or "").strip()
        line1 = str(entry.get("address_line1") or "").strip()
        key = normalize_address(line1) if line1 else (normalize_address(addr) if addr else "")
        if not key:
            # No usable address signal - keep as its own singleton so whatever
            # sub-field data it carries is never silently dropped.
            key = f"__no_address_{len(groups)}__"
        if key not in groups:
            groups[key] = {}
            order.append(key)
        target = groups[key]
        for k, v in entry.items():
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            # First non-empty value wins per sub-field - a later near-duplicate
            # mention only fills gaps, it never overwrites an earlier value.
            target.setdefault(k, v)
        # Prefer the LONGEST raw address string as the display value - it is
        # usually the more complete mention (with city/state/zip) rather than
        # a truncated repeat.
        if len(addr) > len(str(target.get("address") or "")):
            target["address"] = addr

    consolidated: List[dict] = []
    for i, key in enumerate(order):
        obj = groups[key]
        obj["location_id"] = f"L{i + 1}"
        # Plain numeric companion to location_id - ACORD's own "LOC #" box
        # (CommercialStructure_Location_ProducerIdentifier_{row}) expects a
        # bare number ("1", "2", ...), not the "L1" internal id format.
        obj["location_number"] = str(i + 1)
        obj.setdefault("address_line1", obj.get("address"))
        obj.setdefault("address_city", None)
        obj.setdefault("address_state", None)
        obj.setdefault("address_zip", None)

        # Owner / Tenant / Other are mutually exclusive on the real ACORD
        # form. Deriving ALL THREE deterministically (not just owner/tenant)
        # matters: an ungated "Other" checkbox left open for GPT gap-fill
        # will independently re-guess an interest for a row already resolved
        # here, producing a contradictory PDF (e.g. Tenant=Yes AND Other=Yes
        # with a redundant description on the same row).
        ownership = str(obj.get("ownership") or "").strip()
        ownership_l = ownership.lower()
        if ownership_l.startswith("owner"):
            obj["is_owner"], obj["is_tenant"], obj["is_other_interest"] = True, False, False
            obj["other_interest_description"] = None
        elif ownership_l.startswith("tenant"):
            obj["is_owner"], obj["is_tenant"], obj["is_other_interest"] = False, True, False
            obj["other_interest_description"] = None
        elif ownership_l:
            # A real signal that is neither "owner" nor "tenant" - a genuine
            # "Other" interest (e.g. licensee, easement holder).
            obj["is_owner"], obj["is_tenant"], obj["is_other_interest"] = False, False, True
            obj["other_interest_description"] = ownership
        else:
            obj["is_owner"] = obj["is_tenant"] = obj["is_other_interest"] = None
            obj["other_interest_description"] = None

        city_limits = obj.get("inside_city_limits")
        if isinstance(city_limits, bool):
            obj["is_inside_city_limits"], obj["is_outside_city_limits"] = city_limits, not city_limits
        elif isinstance(city_limits, str) and city_limits.strip():
            cl = city_limits.strip().lower()
            if cl in ("yes", "true", "inside"):
                obj["is_inside_city_limits"], obj["is_outside_city_limits"] = True, False
            elif cl in ("no", "false", "outside"):
                obj["is_inside_city_limits"], obj["is_outside_city_limits"] = False, True
            else:
                obj["is_inside_city_limits"] = obj["is_outside_city_limits"] = None
        else:
            obj["is_inside_city_limits"] = obj["is_outside_city_limits"] = None

        consolidated.append(obj)

    facts["property_locations"] = consolidated
    facts["locations"] = [str(o["address"]) for o in consolidated if o.get("address")]


def merge_facts(docs: List[dict], primary: dict) -> Tuple[dict, dict]:
    """
    Multi-document merge with field-level source confidence.

    For each field, the value is taken from the most authoritative doc type
    (per _FIELD_CONFIDENCE_SOURCES) rather than blindly applying the primary doc.
    Fields without a confidence mapping fall back to the legacy primary-wins
    behaviour. List fields are always merged across all docs.
    """
    if not docs:
        return {}, {}

    non_primary = [d for d in docs if d["filename"] != primary["filename"]]

    if non_primary:
        pseudo_partials = [
            {"facts": d.get("facts", {}), "flags": d.get("flags", {}), "_chunk_idx": i}
            for i, d in enumerate(non_primary)
        ]
        np_merged = _merge_list_fields(pseudo_partials, list_keys=_LONG_DOC_LIST_KEYS)
        mf: dict = np_merged.get("facts", {})
        mg: dict = np_merged.get("flags", {})
    else:
        mf = {}
        mg = {}

    # Apply primary doc as legacy fallback for unmapped fields
    for k, v in primary.get("facts", {}).items():
        if not _is_empty(v):
            mf[k] = v

    # Override with field-level authoritative sources when a better doc exists
    if len(docs) > 1:
        for field in list(mf.keys()):
            if field in _LIST_FIELDS:
                continue
            auth_doc = _get_authoritative_doc(docs, field)
            if auth_doc and auth_doc["filename"] != primary["filename"]:
                auth_val = auth_doc.get("facts", {}).get(field)
                if not _is_empty(auth_val):
                    mf[field] = auth_val

    for k, v in primary.get("flags", {}).items():
        if k == "narrative_components":
            _existing = mg.get("narrative_components") or {}
            for comp, data in (v or {}).items():
                if isinstance(data, dict) and data.get("present") and data.get("evidence"):
                    if not _existing.get(comp, {}).get("present"):
                        _existing[comp] = data
            if _existing:
                mg["narrative_components"] = _existing
        elif isinstance(v, bool):
            mg[k] = mg.get(k, False) or v
        elif not _is_empty(v):
            mg[k] = v

    # Deterministic re-derivation of WC monopolistic / multi-state flags
    # (Decision_Tree.txt §137-150). The LLM may omit these, so we always
    # cross-check from wc_payroll_by_state keys to avoid silent fail-open.
    _MONOPOLISTIC_STATES = {"ND", "OH", "WA", "WY"}
    wc_by_state = mf.get("wc_payroll_by_state")
    if isinstance(wc_by_state, dict) and wc_by_state:
        state_codes = set()
        for raw_state in wc_by_state.keys():
            code = str(raw_state or "").strip().upper()[:2]
            if code:
                state_codes.add(code)
        if len(state_codes) > 1:
            mg["wc_multi_state"] = True
        if state_codes & _MONOPOLISTIC_STATES:
            mg["wc_has_monopolistic_state"] = True

    # Canonical, deduplicated multi-location list (Beta Report Figure 27).
    # Must run LAST, after every chunk/doc-level merge above, so it is the
    # single final consolidation pass rather than one of several partial ones.
    try:
        _consolidate_property_locations(mf)
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: location consolidation failed: %s", exc)

    return mf, mg
