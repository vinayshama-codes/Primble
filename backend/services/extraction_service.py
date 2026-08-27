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
from services.lob_canon import canon_line as _lob_canon_line
from services.normalization import normalize_date

# ASYNC-SAFE: shared executor for CPU-bound blocking work (tiktoken, sync helpers)
_EXECUTOR = ThreadPoolExecutor(max_workers=(os.cpu_count() or 2) * 2)

logger = logging.getLogger(__name__)

# ── Cache versioning (Fix 3) ──────────────────────────────────────────────────
# Bump BOTH whenever _EXTRACT_PROMPT_PREFIX or _EXTRACT_SCHEMA changes - this is
# what forces a stale cached extraction to be discarded instead of silently
# served forever. v10: added umbrella_effective_date/umbrella_expiration_date
# to the schema and a RULE 1 umbrella-policy-namespace instruction to the prompt.
# v12: added RULE 14 disambiguating naics_code (business industry classification)
# from carrier_naic/prior_carrier_naic (insurer's NAIC company number) - both are
# called "NAIC" in real documents and the prompt previously gave the model no
# description at all for naics_code to tell them apart.
# v14 (2026-08-23): `dec_page_entries` was removed from _EXTRACT_SCHEMA earlier
# the same day (v13) and is now RESTORED, after the dedicated index pass lost its
# A/B - see the note above `_DEC_INDEX_DEDICATED_PASS`. The schema is byte-
# identical to v12 again, but the version must still move FORWARD rather than
# back: v13 replies (facts and flags with no dec entries) are sitting in the
# cache, and reusing "v12" would serve them as if they were current.
# v15 (2026-08-26, V1 H1 client section 6): ONE new schema key,
# `auto_vehicle_use` (the client's "No vehicle-use information = -5" had no
# fact to read), plus RULE 2c defining it and giving `wc_payroll_period` - a
# key that had been in the schema with no definition at all - the "read the
# period off the figure's own label, never assume annual" instruction the 6.4
# payroll-period rule depends on. Same 14 calls, zero extra tokens beyond the
# rule text; v14 replies stay in the cache under their own version.
# improving-ll.md C80 is the registry entry.
# v16 (2026-08-26, same day, after the c6 live run): RULE 2c gained the three
# "never infer" sentences - P5 printed no radius, use or garaging and the
# model still filled one of them from the operations text, which turned a
# -15 into a -10. No schema change; the version moves so the five live
# packages re-extract under the stricter rule instead of serving v15 replies.
PROMPT_VERSION = "v17"
SCHEMA_VERSION = "v17"

# ── Extraction chunk sizing ───────────────────────────────────────────────────
# This used to be one hand-typed literal:
#
#     _MODEL_CHUNK_CHARS = {"claude": 28_000, "openai": 100_000}
#
# with no comment, no calculation and no provenance. It predated the current
# model. THREE things were wrong with it, and only one was the number:
#
#  1. **No provenance.** Nothing said where 100,000 came from or what would make
#     it wrong. Meanwhile gap fill derives its budget from the model spec
#     (`MODEL_CONTEXT_TOKENS`), so the two halves of the pipeline disagreed about
#     the same model: 56,357 chars/call for extraction, 899,393 for gap fill.
#  2. **No capacity guard.** Nothing checked the value against the model's real
#     window. Typing 2_000_000 there would have made every extraction call fail
#     on context length, with no warning at import.
#  3. **The overlap was coupled to it.** `_compute_prompt_overhead` computed the
#     carry-over tail as `raw // 7`, so changing the chunk size silently changed
#     how much context each chunk inherited from the previous one. Those are two
#     unrelated concerns: the tail exists so a fact split across a boundary is
#     still readable, which is a fixed-size need, not a fraction of anything.
#
# It is now derived from TWO explicit ceilings, and the smaller one wins:
#
#     capacity  = what the model's window can physically hold
#     quality   = how much document the model still reads CAREFULLY per call
#
# **The quality ceiling is the binding one, by a wide margin**, and that is the
# whole point. Capacity says ~1.3M chars would fit. Measured behaviour says
# otherwise:
#
#     ~14,000 tok/call  (extraction today)   fine - 61 facts, 100% coverage
#    ~170,000 tok/call  (gap fill, 684k doc) DEGRADED - the model stops copying
#                                            ACORD field names and invents its
#                                            own (improving-ll.md C21/C22)
#
# So extraction's small chunks were accidentally the SAFE setting. Deriving the
# value must not be an excuse to raise it toward capacity - that would trade a
# known-good stage for ~$0.11 a run. `EXTRACTION_DOC_TOKENS_PER_CALL` defaults to
# 14,000 to reproduce today's behaviour almost exactly (56,000 vs 56,357 chars,
# same chunk count on a real 683,601-char package - asserted in
# tests/test_extraction_chunk_sizing.py). Raise it only with an accuracy baseline
# in hand.
_MODEL_CONTEXT_TOKENS: Dict[str, int] = {
    # Shared with pdf_service via the same env var, so one edit moves both halves
    # of the pipeline when the model changes.
    "openai": int(os.getenv("MODEL_CONTEXT_TOKENS", "400000")),
    "claude": int(os.getenv("CLAUDE_CONTEXT_TOKENS", "200000")),
}
# Fraction of the window one extraction call may occupy. Only ever a backstop
# here, because the quality ceiling below binds first.
_EXTRACTION_CONTEXT_UTILISATION = float(os.getenv("EXTRACTION_CONTEXT_UTILISATION", "0.75"))
# Our own reply cap for an extraction call (facts JSON). Input + output share the
# window, so this must be reserved.
_EXTRACTION_REPLY_TOKENS = int(os.getenv("EXTRACTION_REPLY_TOKENS", "16000"))
# THE quality dial. Document text per extraction call, in tokens. See above.
_EXTRACTION_DOC_TOKENS_PER_CALL = int(os.getenv("EXTRACTION_DOC_TOKENS_PER_CALL", "14000"))
# Carry-over tail from the previous chunk, so a fact spanning a chunk boundary is
# still readable. Its own constant now, NOT a fraction of the chunk size (see 3
# above). Default reproduces the historical `100_000 // 7`.
_EXTRACTION_OVERLAP_CHARS = int(os.getenv("EXTRACTION_OVERLAP_CHARS", "14285"))

ACTIVE_MODEL = LLM_PROVIDER  # driven by LLM_PROVIDER env var ("openai" or "claude")

_MAX_TOKENS_PER_DOC = int(os.getenv("ACORDLY_MAX_DOC_TOKENS", "500000"))
_CHARS_PER_TOKEN    = 4


def _context_capacity_chars(model: str = ACTIVE_MODEL) -> int:
    """Chars one extraction call may carry in total, from the model's window."""
    window = _MODEL_CONTEXT_TOKENS.get(model, _MODEL_CONTEXT_TOKENS["openai"])
    usable = window * _EXTRACTION_CONTEXT_UTILISATION - _EXTRACTION_REPLY_TOKENS
    return max(1000, int(usable * _CHARS_PER_TOKEN))


def get_chunk_size(model: str = ACTIVE_MODEL) -> int:
    """Total prompt budget per extraction call (document text + fixed overhead).

    Kept under its original name and signature for existing callers. It is now
    derived rather than looked up in a table of literals.
    """
    return _effective_chunk_size(model) + _compute_prompt_overhead(model)


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
    '  "applicant_website": string or null,\n'
    # Producer-scoped identity. These exist because `contact_*` above means the
    # APPLICANT (see RULE 11 and arq_service's own client-facing wording, "the
    # best phone number to reach YOU"). Before these existed, the producer's
    # contact details were written into `contact_*` and then stamped onto BOTH
    # the Producer and the Named Insured blocks of every form - the client-
    # reported "mixture of client and carrier information".
    '  "producer_contact_name": string or null, "producer_contact_phone": string or null,\n'
    '  "producer_contact_email": string or null, "producer_fax": string or null,\n'
    '  "producer_address": string or null,\n'
    '  "carrier_website": string or null,\n'
    '  "fein": string or null, "entity_type": string or null,\n'
    # CURRENT policy dates/number — NEVER mix with prior policy fields below
    '  "effective_date": string or null, "expiration_date": string or null,\n'
    '  "policy_number": string or null, "lines_of_business": [string],\n'
    # A package is written PER COVERAGE LINE, and a dec page prints it that way:
    # each line has its own premium, and often its own carrier and policy number
    # (a "single" package can be issued by two affiliated carriers). The scalar
    # carrier_name / policy_number above hold the package-level values and stay
    # exactly as they were; this list carries the per-line breakdown that a
    # single scalar structurally cannot represent.
    '  "coverage_lines": [{"line": string, "carrier": string or null, '
    '"naic": string or null, "policy_number": string or null, '
    '"premium": string or null, "effective_date": string or null, '
    '"expiration_date": string or null}],\n'
    '  "total_revenue": string or null, "total_payroll": string or null,\n'
    '  "num_employees": string or null,\n'
    # num_employees is the TOTAL. The full/part-time SPLIT is a different number
    # and needs its own facts: mapping the total into both the "full time" and
    # "part time" boxes stamped the same figure twice, which is wrong unless one
    # of them is zero.
    '  "num_employees_full_time": string or null, "num_employees_part_time": string or null,\n'
    # years_in_business is a COUNT OF YEARS; business_start_date is a DATE. The
    # ACORD box "NamedInsured_BusinessStartDate" declares itself "Enter date: The
    # date the applicant began in business", so the duration fact never belonged
    # in it.
    '  "business_start_date": string or null,\n'
    '  "locations": [string],\n'
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
    # An INSTALLMENT plan ("Payment Plan: Monthly"), not the billing method and
    # not the audit term. Most dec pages print none - null is the normal answer.
    # Consumed only by _resolve_payment_schedule (fact-or-blank): every run
    # without this key stamped "AN", a code invented from "Audit Period: Annual".
    '  "payment_plan": string or null,\n'
    # The package total the DOCUMENT states. Without it the form's POLICY
    # PREMIUM box had to be computed by summing per-line premiums, which is
    # only as good as every line's extraction - a real 271-page run summed to
    # $9,438 against a stated total of $10,663 because one line's premium was
    # missed. A stated total is a copy; a sum is an inference.
    '  "total_policy_premium": string or null (the TOTAL package/policy premium the '
    'document itself states - e.g. "TOTAL ANNUAL PACKAGE PREMIUM: $10,500". Never a '
    'single coverage part\'s premium, never a figure you add up yourself, and never a '
    'deposit or instalment. Null if the document states no overall total),\n'
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
    # A split-limit auto policy (100/300/50) has THREE different figures. Without
    # these, one `auto_liability_limit` was stamped into the combined-single-limit
    # box AND all three split boxes at once, which reads as $1M for every part.
    '  "auto_bi_per_person": string or null, "auto_bi_per_accident": string or null,\n'
    '  "auto_pd_per_accident": string or null,\n'
    '  "auto_deductible_collision": string or null,\n'
    # Vehicle schedule: one object per vehicle row
    '  "auto_vin_schedule": [{"year": string, "make": string, "model": string, "vin": string, "body_type": string or null, "gvw": string or null, "comp_symbol": string or null, "coll_symbol": string or null}],\n'
    '  "auto_garaging_addresses": [string],\n'
    # WC class codes: one object per class code row
    # v17 (V1 H3, client 8.1): the per-class employee counts ACORD 130 prints
    # beside every rating row. Read only when the table prints them (RULE 3).
    '  "wc_payroll": string or null, "wc_payroll_by_state": {}, "wc_class_codes": [{"code": string, "description": string, "state": string or null, "payroll": string or null, "rate": string or null, "full_time_employees": string or null, "part_time_employees": string or null}],\n'
    '  "wc_xmod": string or null, "wc_xmod_effective_date": string or null,\n'
    '  "wc_officer_exclusions": string or null,\n'
    '  "wc_monopolistic_payroll": {"state": "amount"},\n'
    '  "umbrella_limit": string or null, "umbrella_sir": string or null,\n'
    '  "umbrella_attachment_point": string or null,\n'
    '  "umbrella_effective_date": string or null, "umbrella_expiration_date": string or null,\n'
    '  "umbrella_um_limit": string or null, "umbrella_uim_limit": string or null,\n'
    '  "umbrella_medical_payments_limit": string or null,\n'
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
    # V1 H1 6.3 (2026-08-26, v15): how the fleet is used - the ACORD 127 USE
    # column. One value for the policy; see RULE 15.
    '  "auto_vehicle_use": string or null,\n'
    '  "auto_physical_damage_valuation": string or null,\n'
    # Covered-auto symbols, attributed to the coverage line they sit against on
    # the declarations. A bare [1, 7] cannot tell a validator or a form field
    # WHICH coverage each number designates, which is the whole point of a
    # symbol - see services/auto_symbols.py.
    '  "auto_covered_symbols": [{"coverage": string, "symbols": [int]}],\n'
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
    '  "property_locations": [{"address": string, "county": string or null (the COUNTY the '
    'premises sits in, only when the document states it - e.g. "Arapahoe"; never guessed from the city), '
    '"ownership": string or null (owner, tenant, or a short description '
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
    # ABSENCE IS NOT "NO" (client 2026-08-17 item 3). These three assert
    # something about a CONTRACT REQUIREMENT, and every one of them was declared
    # a bare `boolean` - so the model had no way to say "the document does not
    # mention this" and answered false. A dec page that is simply silent about
    # additional-insured status then fought a certificate that said Yes, and the
    # producer got a conflict card about a requirement nobody had asserted
    # either way (probe runs B and D, 2026-08-17).
    #
    # `null` is the third state. Nothing downstream has to change to accept it:
    # the three readers in sqs_service all test `is True`, the chunk merge skips
    # a null instead of OR-ing it, and an absent sub-key is skipped by the
    # conflict detector - so "not stated" simply stops manufacturing an answer.
    #
    # The `has_*` coverage flags are deliberately NOT changed. There, false
    # genuinely means "no such coverage was detected in this document", which is
    # a finding rather than a claim about a contract.
    '  "risk_transfer": {\n'
    '    "additional_insured_required": boolean or null (true when the document '
    'REQUIRES additional-insured status, false ONLY when it affirmatively says '
    'it is not required; null when the document does not address it at all - '
    'silence is not a "no"),\n'
    '    "additional_insured_names": [string],\n'
    '    "primary_noncontributory_required": boolean or null (same rule: null '
    'when the document does not address it),\n'
    '    "waiver_of_subrogation_required": boolean or null (same rule: null '
    'when the document does not address it),\n'
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
    # RESTORED 2026-08-23 after a live A/B. The dedicated index pass was
    # measured against this key and did not earn its cost: ~593,000 output
    # tokens and 18-20 minutes per run against ~30,000 for the whole of
    # facts+flags, and the owner's regenerated forms came back 'almost the
    # same'. This key produces ~250 entries as a passenger on a call that is
    # already happening, which is what every deterministic consumer has run
    # on for months. See LLMcall1-promptChange.md Round 8.
    # ── Declarations-page recording (source-driven, form-agnostic) ────────
    # WHY THIS EXISTS (2026-08-12): the ~170 keys above are DESTINATION-driven -
    # they capture what the forms are known to ask for, and anything else a dec
    # page prints (audit basis, deposit, program code, servicing contacts, ...)
    # evaporates and can only be re-found by the gap-fill model inside a 683k-
    # char haystack, which measurably answers ~26% of what it is asked. This key
    # is SOURCE-driven: record what the document STATES, decide who consumes it
    # later. Every entry is mechanically verified verbatim against the document
    # in merge_facts (_verify_dec_entries) - a fabricated entry cannot survive -
    # and consumed ONLY by deterministic code (fact backfill, rescue anchors).
    # SINCE 2026-08-13 it is ALSO the index LLM call 2 reads first (Stage A -
    # see pdf_service._render_dec_index and CALL2_RETRIEVAL_REDESIGN D11). That
    # is why `section` exists: two coverage parts print the identical label
    # ("Each Occurrence Limit") with different amounts, and without the section
    # title the two are indistinguishable once the page break is gone.
    '  "dec_page_entries": [{"label": string, "value": string, '
    '"section": string or null, '
    '"owner": "applicant"|"producer"|"carrier"|"policy"|"other", '
    '"policy_number": string or null, "line_of_business": string or null}] '
    '(EVERY label:value pair printed on a DECLARATIONS, coverage-summary or '
    'SCHEDULE page in this text - premiums, limits, deductibles, dates, '
    'identifiers, phone/email/web contacts, codes. Copy label and value '
    'VERBATIM as printed. In a TABLE, one entry per CELL - label = the column '
    'heading plus the row identifier if printed, value = that one cell; never '
    'join two cells into one value. section = the heading printed at the top of the page '
    'the entry appears on, copied VERBATIM (e.g. "COMMERCIAL UMBRELLA '
    'DECLARATIONS", "GENERAL LIABILITY DECLARATIONS", "BUSINESS AUTO '
    'DECLARATIONS"); null only if the page prints no heading. This matters: '
    'the same label carries different amounts under different headings, and '
    'the heading is the only thing that says which coverage part a figure '
    'belongs to. owner = whose value it is: the applicant/insured, '
    'the producer/agency, the carrier/insurer, or "policy" for policy-level '
    'figures like premiums and limits. NEVER record anything from policy '
    'wording, endorsement legal text, or hypothetical/illustrative amounts - '
    'only values this policy actually states on its declarations/schedule '
    'pages. At most 150 entries; [] when this text contains no declarations '
    'content.),\n'
    '  "state_of_operations": string or null\n'
    '},\n\n'
    '"flags": {\n'
    '  "is_commercial_policy": boolean, "has_general_liability": boolean,\n'
    '  "has_property_coverage": boolean, "has_auto_coverage": boolean,\n'
    '  "has_workers_comp": boolean, "has_umbrella": boolean,\n'
    '  "has_multiple_locations": boolean, "has_loss_history": boolean,\n'
    '  "asserts_no_known_losses": boolean (true ONLY when the document '
    'EXPLICITLY states there are no losses/claims - e.g. "no known losses", '
    '"loss free", "claim free". "NOT ON FILE", "NOT REPORTED" or loss data '
    'simply being absent means UNKNOWN - leave false),\n'
    '  "asserts_no_subcontractors": boolean (true ONLY when the document '
    'EXPLICITLY states the insured does not use subcontractors - e.g. '
    '"no subcontractors", "all work performed by insured\'s own employees". '
    'Subcontracting simply not being mentioned means UNKNOWN - leave false),\n'
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
    '  "has_open_cargo": boolean,\n'
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

# ── Facts whose extraction contract is TRI-STATE (client 1.3) ───────────────
# `boolean or null` in the schema above means the model is told to answer null
# when the document does not address the subject, so a `false` from a document
# is the document SAYING NO - the client's "Explicit No / Absent".
#
# Every OTHER boolean in the schema is a bare `boolean`, where `false` is
# indistinguishable from "never mentioned". That is defect B8 - a COI that
# simply never discussed subcontractors produced `false`, which manufactured a
# cross-document conflict and an 85 cap - and `fact_state` correctly reads those
# as `not_stated`.
#
# DERIVED FROM THE SCHEMA STRING, never hand-listed: a new `boolean or null`
# field becomes an Explicit No automatically, and a field demoted to a bare
# boolean stops being one, with no second list to remember.
TRISTATE_BOOLEAN_FACTS: frozenset = frozenset(
    re.findall(r'"([a-z_][a-z0-9_]*)":\s*boolean or null', _EXTRACT_SCHEMA)
)

# The set of flags the schema ASKS the model to answer as an affirmative
# absence assertion. Auto-discovered by NAMING CONVENTION - `asserts_no_*` -
# from the schema string itself, the same way `TRISTATE_BOOLEAN_FACTS` is
# discovered from the `boolean or null` shape. A new flag added to the schema
# under this convention is found automatically; `test_every_assertion_flag_is_
# registered` fails the build until someone decides what it is an Explicit No
# ABOUT, which is the one piece of domain knowledge no regex can supply.
ASSERTION_FLAG_NAMES: frozenset = frozenset(
    re.findall(r'"(asserts_no_[a-z0-9_]*)":\s*boolean', _EXTRACT_SCHEMA)
)

# Which fact(s) each assertion flag is an Explicit No ABOUT. This one mapping
# cannot be derived - "no known losses" is about `loss_history` and its
# siblings by domain knowledge, not by string shape - so it stays a table, but
# ONE centralised, self-verifying table rather than a special case built fresh
# per fact. `asserts_no_known_losses` is the client's own first example ("No
# prior losses"); `asserts_no_subcontractors` is the second ("No subcontracting")
# - both positive evidence of absence, which is exactly what `explicit_no`
# means. `test_every_assertion_flag_is_registered` / `test_every_registered_
# flag_still_exists_in_the_schema` keep this table and the schema from drifting
# in either direction; adding the THIRD example ("No Property coverage") is
# deliberately not done here - it already resolves to `not_applicable` via a
# declared-absent coverage line, and the client's own vocabulary places it
# under Explicit No, so which box is correct is a product decision, not an
# engineering one (see v1-20AUG.md).
ABSENCE_ASSERTION_FLAGS: Dict[str, Tuple[str, ...]] = {
    "asserts_no_known_losses":   ("loss_history", "num_claims", "total_incurred",
                                  "loss_history_years"),
    "asserts_no_subcontractors": ("percent_subcontracted",),
}

# ── Class/rating SCHEDULES whose per-row amount is not a package total ──────
# A class-code schedule row states the RATING BASIS for one classification -
# `$285,000` payroll for GL class 91580 - never the account's total payroll.
# `underwriting_consistency._drop_class_exposure_candidates` reads this to keep
# those rows out of a package TOTAL's candidate list.
#
# DERIVED FROM THE SCHEMA, but not blindly: a naive "any list field with a
# money-shaped column" scan also matched `dec_page_entries.value` (the
# PRIMARY EVIDENCE source other facts are backfilled FROM - excluding it would
# have been actively destructive), `coverage_lines.premium` (owned by its own
# dedicated line-premium-vs-package-total logic, `is_component_of`),
# `property_locations.building_value` and `inland_marine_items.value`
# (per-ITEM values, which belong to C1b's item-scope axis, not this filter) -
# each a real false positive, found by running the scan and inspecting it
# before trusting it. The selector that survives is FIELD NAME contains
# "class" (both today's class-code schedules are named for exactly that) plus
# whichever of ITS OWN columns are money-shaped
# (`services.fact_equivalence._MONEY_TOKENS`, reused rather than re-invented).
# A future `auto_class_schedule` or `cyber_class_codes` with a money column is
# picked up automatically; nothing outside a class schedule ever is.
def _discover_class_schedule_money_columns() -> Dict[str, Tuple[str, ...]]:
    try:
        from services.fact_equivalence import _MONEY_TOKENS
        out: Dict[str, Tuple[str, ...]] = {}
        for m in re.finditer(r'"(\w+)":\s*\[\{([^}]*)\}\]', _EXTRACT_SCHEMA):
            field, body = m.group(1), m.group(2)
            if "class" not in field.lower():
                continue
            cols = re.findall(r'"(\w+)":', body)
            money_cols = tuple(
                c for c in cols if set(c.lower().split("_")) & _MONEY_TOKENS)
            if money_cols:
                out[field] = money_cols
        return out
    except Exception:                                         # noqa: BLE001
        return {}


_CLASS_EXPOSURE_COLUMNS: Dict[str, Tuple[str, ...]] = (
    _discover_class_schedule_money_columns())

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
    'an error to normalize away. umbrella_um_limit / umbrella_uim_limit / '
    'umbrella_medical_payments_limit are the UM/UIM/medical-payments coverages of the UMBRELLA '
    'POLICY ITSELF, only when the umbrella declarations state them for the umbrella — the '
    'underlying AUTO policy\'s UM/UIM/med-pay limits belong to auto_um_uim_limit and must NEVER '
    'be copied into the umbrella keys; when the umbrella states none, all three stay null.\n\n'
    'RULE 2 — Schedule tables: output ONE JSON object per row.\n'
    '  • Vehicle schedule      → one entry per vehicle in auto_vin_schedule\n'
    '  • WC class code table   → one entry per class code row in wc_class_codes\n'
    '  • Driver schedule       → one entry per driver in auto_drivers\n'
    '  • Property locations    → one entry per DISTINCT physical location in property_locations. '
    'The SAME address printed on multiple pages (dec page, attached schedule, certificate) is still '
    'ONE location — do not emit a duplicate entry for a repeated mention of the same address.\n\n'
    'RULE 2b — Covered-auto symbols. A commercial auto declarations page designates which autos each '
    'coverage applies to using a symbol NUMBER printed against that coverage line (e.g. "Liability 01", '
    '"Comprehensive 07", "Collision 07"). For auto_covered_symbols, emit one object per coverage line, '
    'copying the number EXACTLY as designated: '
    '[{"coverage": "liability", "symbols": [1]}, {"coverage": "comprehensive", "symbols": [7]}]. '
    'Use the coverage wording the document itself uses. If a covered-autos grid lists symbols without '
    'making the coverage line clear, use "coverage": "unspecified" rather than guessing. NEVER infer a '
    'symbol that is not printed — a covered-auto symbol is a coverage designation with legal effect, so '
    'an absent symbol must stay absent.\n\n'
    'RULE 2c — Vehicle use and payroll period (v15). auto_vehicle_use is the USE CLASS the '
    'document states for the vehicles, as ACORD 127 prints it: "service", "retail", "commercial", '
    '"for hire", "farm" or "pleasure" - copy the document\'s own word ("Service Use", '
    '"Commercial - Retail Delivery", "Contractor service vehicles" -> "service"). One value for the '
    'policy; if vehicles genuinely differ, give the use that applies to most of them. NEVER infer '
    'auto_vehicle_use from the description of operations, auto_radius_of_operation from anything but '
    'a printed radius, or auto_garaging_addresses from the mailing address - each stays null unless '
    'the document states it for the vehicles. '
    'wc_payroll_period is the PERIOD the stated payroll figure covers, read from its own label: '
    '"Estimated Annual Payroll", "Annual Remuneration", "per year" -> "annual"; a quarterly '
    'report or a monthly figure -> "quarterly" / "monthly". Set null when the payroll figure carries '
    'no period wording at all - never assume annual.\n\n'
    'RULE 3 — Never hallucinate. If a value is not visible in the document, set the field to null '
    '(or [] for list fields). Do not invent or infer values that are not explicitly stated.\n\n'
    'RULE 4 — Extract ALL financial figures exactly as printed: limits, premiums, payrolls, '
    'deductibles, values. Include currency symbols and formatting as-is.\n\n'
    'RULE 5 — For addresses: extract the full address string including city, state, ZIP.\n\n'
    'RULE 6 — Flag definitions. Judge each boolean flag by the MEANING of the document, not the mere presence of exact keywords - the example terms listed are illustrative, not an exhaustive checklist, so set a flag true for clear equivalents and paraphrases too (e.g. a coverage part named "Network Security and Privacy Liability" or "ransomware incident response coverage" is cyber coverage even without the word "cyber"). Judge by meaning, but the meaning that matters is WHAT THE POLICY COVERS. A coverage flag describes coverage the document GRANTS - never an exposure the applicant merely has, and never a coverage the document names in order to EXCLUDE or decline it. "We hold customer health and card data" is a cyber EXPOSURE and does not by itself make has_cyber true; a "Cyber Incident and Data Privacy Exclusion" attached to a liability form makes it explicitly FALSE. This does NOT relax any "Do NOT set true" restriction below - those guards still apply in full. Criteria:\n'
    '  is_commercial_policy: true if document is a commercial insurance policy, application, dec page, certificate, or quote (not personal lines).\n'
    '  has_general_liability: true if document mentions "General Liability", "GL", "premises/operations", "products/completed operations", "personal and advertising injury", GL limits, or GL premiums.\n'
    '  has_property_coverage: true if document explicitly lists a building limit or BPP (business personal property) value, commercial property premium, or COPE data (construction type, year built, occupancy, protection class) for a covered location. Do NOT set true based on mailing addresses alone, certificate holder addresses, or GL-only premises descriptions.\n'
    '  has_auto_coverage: true if document mentions business auto, commercial auto, vehicle schedules, VINs, auto liability limits, or fleet coverage as a distinct coverage line or policy section. Do NOT set true based solely on "hired/non-owned auto" appearing as a GL endorsement line — that alone is not a separate commercial auto policy.\n'
    '  has_workers_comp: true if document mentions workers compensation, WC, payroll by class code, experience modification factor, employers liability, or WC class codes.\n'
    '  has_umbrella: true if the document explicitly shows an umbrella or excess liability LIMIT or PREMIUM (e.g. "$2M Umbrella", "Excess Liability – $5,000,000") for coverage above a primary GL or auto policy. Do NOT set true merely because the words "excess", "limits", "attachment point", or "SIR" appear without a distinct umbrella/excess policy section or stated dollar amount.\n'
    '  has_multiple_locations: true if document lists 2 or more distinct insured property addresses or locations.\n'
    '  has_loss_history: true if document contains a loss run, claims history table, prior claims, loss amounts, or any mention of paid/incurred/open claims.\n'
    '  asserts_no_known_losses: true ONLY if the document affirmatively states the insured has had NO prior or known losses/claims — judge this by MEANING, not exact wording. Set true for any clear paraphrase, e.g. "no known losses", "no prior losses", "loss-free", "claims-free", "clean loss history", "favorable loss experience with no claims", "no reported claims in the past N years", "the insured reports no losses". Set FALSE when the document merely discusses, lists, or summarizes losses/claims, when any actual claim (paid, incurred, reserved, or open) appears, or when loss history is simply absent/not mentioned. This is a no-loss ASSERTION, not the presence of loss data.\n'
    '  asserts_no_subcontractors: true ONLY if the document affirmatively states the insured does NOT use subcontractors — judge this by MEANING, not exact wording. Set true for any clear paraphrase, e.g. "no subcontractors are used", "all work is performed by the insured\'s own employees", "the applicant does not subcontract any portion of its operations", "0% subcontracted". Set FALSE when the document merely discusses subcontractor insurance requirements (e.g. "subcontractors are required to carry their own coverage"), when a nonzero subcontracted percentage or cost appears, or when subcontracting is simply not mentioned. This is a no-subcontracting ASSERTION, not the absence of subcontractor cost data.\n'
    '  is_contractor: true only if the named INSURED\'s PRIMARY BUSINESS is a construction or installation contracting trade (general contractor, roofing contractor, electrical, plumbing, excavation, demolition contractor, etc.). Do NOT set true if construction trades are only mentioned in loss history, claims descriptions, operations of a third party, or as endorsement requirements listed for certificate holders.\n'
    '  has_certificate_request: true if document contains language requesting issuance of a certificate of insurance, lists a certificate holder, or shows "certificate required".\n'
    '  is_certificate_doc: true if the document IS itself an ACORD 25 Certificate of Liability Insurance or ACORD 28 Evidence of Property — identifiable by "Certificate of Liability Insurance" or "Evidence of Commercial Property Insurance" as the document title.\n'
    '  gl_is_claims_made: true ONLY if the GENERAL LIABILITY COVERAGE FORM ITSELF (Coverage A bodily injury / property damage) is written on a claims-made basis. A retroactive date alone is NOT enough - it must belong to the GL coverage form. Do NOT set true when the retroactive date belongs to a SUB-COVERAGE endorsement such as Employee Benefits Liability, Professional/E&O, or Pollution, which are routinely claims-made INSIDE an otherwise occurrence-based GL policy; and do NOT set true when the document states the GL form is written on an OCCURRENCE basis. When a declarations page says both (e.g. "CG 00 01 is written on an OCCURRENCE basis" and "Employee Benefits Liability CG 04 35 is the only coverage written on a CLAIMS-MADE basis"), the answer is FALSE.\n'
    '  auto_has_physical_damage: true if document shows comprehensive and/or collision coverage for autos.\n'
    '  auto_split_limits: true if auto liability is expressed as split limits (BI per person / BI per accident / PD per accident) rather than a combined single limit (CSL). When true, ALSO fill auto_bi_per_person, auto_bi_per_accident and auto_pd_per_accident with the three separate figures (e.g. "100/300/50" means $100,000 / $300,000 / $50,000). When the policy carries a single combined limit, leave those three null and put the figure in auto_liability_limit only - a CSL is NOT the same amount as each split part.\n'
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
    '  has_open_cargo: true ONLY if the document shows an OPEN CARGO or OCEAN CARGO policy or section - the ocean-marine coverage for goods shipped by sea, typically labeled "Open Cargo Policy", "Ocean Cargo", or "Marine Cargo Certificate" - with a stated limit or premium. Do NOT set true for inland transit coverage of any kind: a motor truck cargo limit, a transit or property-in-transit extension inside an installation floater or an inland marine schedule, or a contractors-equipment floater are all INLAND marine, not open cargo. If in doubt, false.\n'
    '  has_crime: true if the document shows a DISTINCT crime or fidelity coverage part, policy or endorsement WITH a stated limit or premium (e.g. "Employee Dishonesty $50,000", a Commercial Crime coverage part, a money-and-securities limit). Do NOT set true when crime terms appear only as an EXCLUSION, as a fidelity or ERISA bond a contract REQUIRES the applicant to carry elsewhere, or on a line the document lists as not covered ("Crime and Fidelity - No Coverage").\n'
    '  has_cyber: true if the document shows a DISTINCT cyber or privacy coverage part, policy or endorsement WITH a stated limit or premium (e.g. "Cyber Liability $1,000,000", a Cyber and Privacy section carrying its own premium). Do NOT set true when cyber terms appear only as: an EXCLUSION or disclaimer (a "Cyber Incident and Data Privacy Exclusion" notice attached to a general liability form), a limited virus, hacking or data-restoration extension inside ANOTHER line such as Electronic Data Processing or inland marine, or a description of the applicant\'s operations and data holdings (that is an exposure, not coverage).\n'
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
    'RULE 14 — naics_code vs. carrier_naic/prior_carrier_naic: these are UNRELATED numbers '
    'that both get called "NAIC" in real documents - do not confuse them.\n'
    '  naics_code is the INSURED BUSINESS\'s own industry classification code (NAICS - North '
    'American Industry Classification System, e.g. "238160" for roofing contractors), typically '
    'labeled "NAICS Code" or "SIC Code" near the applicant/business information.\n'
    '  carrier_naic and prior_carrier_naic are the INSURANCE COMPANY\'s identifier (NAIC - '
    'National Association of Insurance Commissioners company code, e.g. "41982"), typically '
    'labeled "NAIC #" or "NAIC Number" next to the carrier/insurer name (or the prior carrier\'s '
    'name for prior_carrier_naic).\n'
    '  If a document shows a number labeled just "NAIC #" or "NAIC Number" next to a carrier, '
    'insurer, or insurance company name, it belongs in carrier_naic (or prior_carrier_naic) - '
    'NEVER in naics_code, even though the label looks similar.\n\n'
    # RULE 15 generalises RULE 14 from one confusable pair to every identity field.
    # A dec page prints the agency's phone in the largest block on page 1 and the
    # insured's phone often not at all, so an undefined "contact_phone" reliably
    # captured the AGENCY's number and every downstream stamper then wrote it into
    # the applicant's box too. Naming the owning party for each field is what makes
    # a null possible; without it the model has no way to know a value is not its.
    'RULE 16 — coverage_lines (the per-line breakdown of THIS policy):\n'
    '  Output one entry per coverage line the document actually shows as covered - General '
    'Liability, Business Auto, Inland Marine, Umbrella, Property, Crime, Cyber, and so on. '
    'Use the line name as the document prints it.\n'
    '  Put that line\'s OWN premium, carrier, NAIC and policy number in its entry. In a '
    'package issued by affiliated companies these genuinely differ per line - copy what is '
    'printed against each line, never the package total or the first carrier you saw.\n'
    '  A line the document lists as NOT covered ("Property - No Coverage", "Crime and '
    'Fidelity - No Coverage") is NOT a coverage line. Leave it out.\n'
    '  Set premium to null when only a package total is shown; never divide or estimate one. '
    'These are amounts that appear on a signed application.\n'
    '  A line premium is the ANNUAL PREMIUM CHARGED FOR THAT COVERAGE PART. It is not a '
    'terrorism (TRIA/TRIPRA) charge, a policy or service fee, a state surcharge or tax, a '
    'minimum premium, an endorsement or audit adjustment, or one vehicle\'s or one '
    'location\'s share. Those figures print in the same column and are far smaller; if the '
    'only amount you can find against a line is one of them, set premium to null.\n\n'
    'RULE 15 — ENTITY DISCIPLINE. A submission names several DIFFERENT parties. Never copy '
    'one party\'s detail into another party\'s field.\n'
    '  PRODUCER (the agency/brokerage submitting the business - the "Producer", "Agency" or '
    '"Agent" block): producer_name, producer_address, producer_contact_name, '
    'producer_contact_phone, producer_contact_email, producer_fax.\n'
    '  CARRIER (the insurance company issuing the policy - the "Insurer", "Carrier" or '
    '"Company" block): carrier_name, carrier_naic, carrier_website.\n'
    '  APPLICANT (the insured named on the policy): applicant_name, dba_name, fein, '
    'mailing_address, physical_address, applicant_website, contact_name, contact_phone, '
    'contact_email. The contact_* fields are the APPLICANT\'s own contact person - never the '
    'agency\'s and never the carrier\'s.\n'
    '  Fill each of these ONLY from a value the document labels as belonging to THAT party. '
    'A phone, email, address or website printed inside the producer\'s or carrier\'s block '
    'belongs to that party alone: put it in that party\'s field and leave the other parties\' '
    'fields null. Do NOT reuse one party\'s value to fill another party\'s empty field. '
    'null is the CORRECT answer when a party\'s own value is not stated - a borrowed value is '
    'a defect, a null is not.\n'
    '  Never derive one field from another: a fax number counts only if the document labels it '
    'as a fax (never copy the phone number into it), and an email address must contain "@" '
    '(a person\'s name is not an email address).\n\n'
    'Return ONLY a valid JSON object with exactly these two top-level keys:\n\n'
    + _EXTRACT_SCHEMA
    + '\n\nReturn ONLY the JSON object. No markdown fences, no explanation, no extra text. '
    'Start your response with { and end with }.\n\n'
)

# ── Prompt overhead constants ─────────────────────────────────────────────────
# Max realistic context_section length (label + a context_prefix tail of at most
# _EXTRACTION_OVERLAP_CHARS — the SAME constant the chunkers cut the tail with,
# so this reservation is exact rather than a guess at a different number).
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
    """Fixed chars every extraction call spends before any document text.

    NO LONGER CALLS `get_chunk_size`. It used to derive the carry-over tail as
    `raw // 7`, which (a) coupled two unrelated concerns — see the block comment
    at `_MODEL_CONTEXT_TOKENS` — and (b) would now be circular, since
    `get_chunk_size` is derived from this function. The tail is its own constant.
    """
    return (
        len(_EXTRACT_PROMPT_PREFIX)
        + len(_CONTEXT_SECTION_HEADER)
        + _EXTRACTION_OVERLAP_CHARS
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
    """Document-text chars per extraction call — the number that decides chunking.

    The smaller of two ceilings, and which one binds is the whole story:

      quality  — how much document the model still reads carefully per call.
                 `EXTRACTION_DOC_TOKENS_PER_CALL` (14,000 tok = 56,000 chars).
                 **This is the one that binds.**
      capacity — what the model's window can physically hold after the prompt
                 overhead and our reply reserve. ~1.29M chars on a 400k window.

    Capacity is ~23x larger than quality here. That gap is not waste to be
    reclaimed — it is the measured difference between a stage that works and one
    that invents field names (improving-ll.md C21). Read the block comment at
    `_MODEL_CONTEXT_TOKENS` before touching either number.
    """
    overhead = _compute_prompt_overhead(model)
    quality  = _EXTRACTION_DOC_TOKENS_PER_CALL * _CHARS_PER_TOKEN
    capacity = _context_capacity_chars(model) - overhead
    if quality > capacity:
        # An explicit override that cannot physically fit. Clamping beats letting
        # every call fail on context length with no explanation.
        logger.warning(
            "extraction: EXTRACTION_DOC_TOKENS_PER_CALL=%d (%d chars) exceeds what a "
            "%d-token window holds after %d chars of prompt overhead and a %d-token "
            "reply reserve — clamping to %d chars.",
            _EXTRACTION_DOC_TOKENS_PER_CALL, quality,
            _MODEL_CONTEXT_TOKENS.get(model, _MODEL_CONTEXT_TOKENS["openai"]),
            overhead, _EXTRACTION_REPLY_TOKENS, capacity,
        )
    return max(1000, min(quality, capacity))


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
    "dec_page_entries",
    "lines_of_business", "locations", "property_locations",
    "auto_vin_schedule", "auto_garaging_addresses", "auto_drivers",
    "gl_class_codes_by_location", "gl_class_code_schedule",
    "wc_class_codes", "underlying_policies",
    "additional_named_insureds", "auto_covered_symbols",
    "loss_history", "prior_coverage_by_line", "wc_officers",
    "inland_marine_items", "contractor_high_hazard_ops",
    "coverage_lines",
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


# ── Extraction output-token cap (improving-ll.md C51) ────────────────────────
# The reply this cap bounds is one chunk's WHOLE fact set: ~150 scalar facts,
# every schedule (vehicles, drivers, locations, class codes, loss rows) and up
# to 150 `dec_page_entries`, each with label/value/section/owner/policy_number/
# line_of_business. On a dense declarations chunk that reply is large, and at
# 16,000 tokens it was being CUT OFF mid-object - which is what made a chunk
# unparseable and (before the salvage + retry fix below) 500'd the client's
# 271-page upload on 2026-08-15.
#
# Raising the cap does not raise the bill: output tokens are billed on what the
# model actually writes, and the cap only decides where the text is severed.
# `gpt-5.4-mini` allows 128,000 output tokens, so 32,000 is 4x headroom and
# still a quarter of what the model would permit. Lower it with
# EXTRACT_MAX_OUTPUT_TOKENS if a future model needs it; the salvage path below
# stays as the safety net either way, because a cap can always be reached.
_EXTRACT_MAX_OUTPUT_TOKENS = int(os.getenv("EXTRACT_MAX_OUTPUT_TOKENS", "32000"))


# ── Fix 2: Strict JSON parse for extraction output ────────────────────────────

# ASYNC-SAFE
async def _safe_json_parse(raw: str, context: str = "") -> dict:
    """
    Parse LLM extraction output. Expects: {"facts": {...}, "flags": {...}}.
    On parse failure: DETERMINISTIC salvage of the completed portion first
    (utils.json_salvage — free, and truncation at the output cap is the usual
    cause), then LLM repair (max 2 attempts, fed the first 3,000 chars).
    After parse: _validate_parsed() enforces strict schema.
    Raises RuntimeError on any failure — never returns empty silently. The
    CALLER (_gather_chunks_async._one) degrades that to a failed chunk rather
    than aborting the upload; see the note there.
    """
    for attempt in range(3):
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.I)
            raw = raw.rstrip("`").strip()
        s = raw.find("{")
        e = raw.rfind("}")
        parsed = None
        if s != -1 and e != -1:
            candidate = raw[s : e + 1]
            try:
                parsed = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                parsed = None

        # ── Deterministic salvage BEFORE spending an LLM repair call ─────────
        # The dominant real-world cause of an unparseable extraction reply is
        # TRUNCATION at the output-token cap: the schema is large (up to 150
        # dec_page_entries, plus every schedule), and a reply cut mid-object
        # leaves `rfind("}")` pointing at a nested close, so the candidate is
        # unbalanced and json.loads fails.
        #
        # The old path went straight to an LLM repair fed `raw[:3000]` - the
        # first 3,000 CHARACTERS of a reply that may be 60,000 - so the repair
        # saw a fragment of a fragment, and each subsequent attempt re-truncated
        # the previous repair's output. Three attempts later the chunk was
        # declared unparseable and the whole upload 500'd (live 2026-08-15, the
        # client's 271-page package).
        #
        # Rewinding to the last completed element recovers everything the model
        # DID write, costs nothing, and cannot invent a value. Same parser the
        # gap-fill stage has used since the C-series work (utils.json_salvage).
        if parsed is None and s != -1:
            from utils.json_salvage import salvage_truncated_json
            _sal = salvage_truncated_json(raw[s:])
            if isinstance(_sal, dict) and _sal:
                logger.warning(
                    "_safe_json_parse [%s]: reply was not valid JSON (almost always "
                    "truncation at the output cap) - SALVAGED %d top-level key(s) "
                    "from the completed portion instead of discarding the chunk",
                    context, len(_sal),
                )
                parsed = _sal

        if parsed is not None:
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
    # `lines_of_business` was in _LIST_FIELDS but NOT here, so the cross-chunk
    # merge scored it as a scalar and kept ONE chunk's list. A line named only in
    # a later chunk was discarded, taking its ACORD 125 line-of-business checkbox
    # with it (_INDICATOR_RULES reads this fact for BOP / garage / truckers /
    # liquor / fiduciary / yacht / motor carrier). Found 2026-08-09 by
    # test_every_list_shaped_extraction_fact_is_registered. Merging is a union
    # with dedup, so this can only preserve lines, never invent one.
    "lines_of_business",
    "locations", "property_locations", "auto_vin_schedule", "auto_garaging_addresses",
    "auto_drivers", "gl_class_codes_by_location", "gl_class_code_schedule",
    "wc_class_codes", "underlying_policies",
    "additional_named_insureds", "auto_covered_symbols",
    "loss_history", "prior_coverage_by_line", "wc_officers",
    "inland_marine_items", "contractor_high_hazard_ops",
    # Without this the cross-chunk merge treats coverage_lines as a scalar and
    # keeps ONE chunk's list, so a dec page split across chunks silently loses
    # every line mentioned in the other chunks.
    "coverage_lines",
    # Source-driven dec-page recording - union across chunks for the same
    # reason as coverage_lines: a dec section split across two chunks must
    # contribute entries from both halves.
    "dec_page_entries",
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
        context_prefix = _tail_chars(body, _EXTRACTION_OVERLAP_CHARS)
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
    overlap_pct: float = 0.0,
) -> List[ChunkTuple]:
    """
    Hybrid semantic + line chunking.
    char_start/char_end: unique content offsets into original text.
    context_prefix: boundary context for LLM — not counted in char ranges.
    Short sections never dropped.

    `overlap_pct` is **accepted and ignored**, and has been for as long as this
    function has existed. Kept only so existing positional callers/tests keep
    working. The real carry-over is `_EXTRACTION_OVERLAP_CHARS` — a fixed char
    count, not a fraction of anything. Do not add a third meaning of "overlap"
    here; there were already three (this dead fraction, the constant, and a
    `max_chars // 7` expression) and only the undocumented one was live.
    """
    del overlap_pct                       # documented no-op, see docstring
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
        context_prefix = _tail_chars(body, _EXTRACTION_OVERLAP_CHARS)
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

    raw = await groq_chat(
        LLM_MODEL, [{"role": "user", "content": prompt}],
        max_tokens=_EXTRACT_MAX_OUTPUT_TOKENS,
    )

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
# `gl_products_aggregate` and `gl_personal_advertising_injury` were added
# 2026-07-30: a live run stamped BOTH from the umbrella ($3,000,000) alongside
# gl_each_occurrence and gl_aggregate. They are children of the `gl_limits`
# composite and must go through the same reconciliation.
_CURRENCY_FIELDS = frozenset({
    "total_revenue", "total_payroll", "wc_payroll", "property_building_value",
    "property_bpp_value", "gl_limits", "gl_aggregate", "gl_each_occurrence",
    "gl_products_aggregate", "gl_personal_advertising_injury",
    "auto_liability_limit", "umbrella_limit", "business_income_limit",
    "extra_expense_limit", "umbrella_sir", "umbrella_attachment_point",
})


def _currency_magnitude(sval: str) -> float:
    """Extract numeric magnitude from a currency string for tiebreaking.

    NOTE: only meaningful for a string holding ONE amount. On a composite
    ("each occurrence $1,000,000; general aggregate $2,000,000") it concatenates
    every digit and returns 1.0e+20 — which is why the magnitude tiebreak is now
    restricted to the single zero-versus-real case. Do not widen it. See the
    tiebreak comment in `_merge_list_fields`.
    """
    try:
        return float(re.sub(r"[^\d.]", "", sval))
    except Exception:
        return 0.0


# ── Composite-consistency tiebreak ───────────────────────────────────────────
# A scalar limit fact and the composite fact it belongs to are extracted
# separately, from the same document, and can disagree. On the real package that
# produced C23 they did: `gl_limits` said "each occurrence $1,000,000 … general
# aggregate $2,000,000" while `gl_each_occurrence` was filled from the Commercial
# Liability Umbrella's $3,000,000.
#
# Killing the magnitude tiebreak stopped umbrella figures winning *systematically*
# but left the outcome decided by which chunk happened to mention the amount
# first — a coin flip on a field that prints on a certificate of liability. The
# composite is the better witness for its own children: it was extracted as ONE
# coherent block, so its parts are mutually consistent by construction.
#
# This does not parse, reformat or invent anything. It asks one question: does
# this candidate's amount actually appear in the composite? It only acts when
# EXACTLY ONE candidate does — if both appear, or neither does, the composite has
# nothing useful to say and the ordinary scoring stands.
_CURRENCY_COMPOSITE_PARENT = {
    "gl_each_occurrence":             "gl_limits",
    "gl_aggregate":                   "gl_limits",
    "gl_products_aggregate":          "gl_limits",
    "gl_personal_advertising_injury": "gl_limits",
}
_CURRENCY_COMPOSITES = frozenset(_CURRENCY_COMPOSITE_PARENT.values())
_CURRENCY_COMPOSITE_CHILDREN: Dict[str, List[str]] = {}
for _c, _p in _CURRENCY_COMPOSITE_PARENT.items():
    _CURRENCY_COMPOSITE_CHILDREN.setdefault(_p, []).append(_c)

_MONEY_TOKEN_RE = re.compile(r"\$\s*([\d][\d,]*(?:\.\d{1,2})?)")


def _money_amounts(sval: str) -> set:
    """Every $-prefixed amount in `sval`, as floats.

    Requires the `$` so plain years, class codes and policy numbers are not
    mistaken for money — this is used as a positive containment test, and a false
    member would let a wrong candidate look 'consistent'.
    """
    out = set()
    for m in _MONEY_TOKEN_RE.findall(sval or ""):
        try:
            out.add(float(m.replace(",", "")))
        except Exception:
            continue
    return out


# ── Arithmetic reconciliation: the package total vs its own coverage lines ───
# THE case source authority (C45) cannot decide, named there as the known limit:
# a LINE premium and the PACKAGE total both sit on the declarations page, so they
# land in the same authority tier and frequency decides - and a line premium
# printed twice beats the true total printed once. Live 2026-08-12: $2,991 (the
# Commercial Auto line) won `total_policy_premium` over the real $10,663.
#
# `pdf_service._resolve_estimated_total` already REFUSES the impossible figure
# (a total cannot be smaller than one of its own lines), but a resolver can only
# blank - the candidate list is gone by then, so the client's PDF shipped with an
# EMPTY policy-premium box while the correct figure sat in the rejected pile.
# This runs where the candidates still exist and swaps in the best VALID one.
#
# VALIDITY, not preference (the C23 lesson): nothing here prefers a bigger
# number. It removes candidates that are arithmetically impossible as a total -
# smaller than the largest single granted coverage-line premium - and only when
# the document provides that evidence. No coverage lines, or no candidate that
# passes, and the merge result stands untouched (the resolver still blanks it
# downstream, which is the correct last resort: blank beats wrong).
def _premium_dollars(text: Any) -> int:
    """Whole dollars from a currency string; 0 when there is no figure."""
    digits = re.sub(r"[^\d]", "", str(text or "").split(".")[0])
    return int(digits) if digits else 0


def _reconcile_total_premium(merged_facts: dict, candidates: Dict[str, dict]) -> None:
    """Replace an arithmetically-impossible `total_policy_premium` winner with
    the best-scored candidate that IS possible. Mutates `merged_facts`."""
    lines = merged_facts.get("coverage_lines")
    if not isinstance(lines, list) or not lines or not candidates:
        return
    granted = [
        _premium_dollars(e.get("premium"))
        for e in lines
        if isinstance(e, dict) and _line_entry_grants_coverage(e)
    ]
    largest = max(granted, default=0)
    if largest <= 0:
        return
    # With two or more PRICED lines the true total strictly exceeds any single
    # line, so equality with the largest line is impossible too. Live run fr1
    # (2026-08-12): the merge picked $3,954 - the GL line premium exactly - and
    # the >=-only floor waved it through. A one-line package keeps equality.
    positive = sum(1 for p in granted if p > 0)
    def _possible(amount: int) -> bool:
        if amount <= 0:
            return False
        return amount > largest or (amount == largest and positive < 2)
    chosen = merged_facts.get("total_policy_premium")
    chosen_val = chosen.get("value", chosen) if isinstance(chosen, dict) else chosen
    chosen_amt = _premium_dollars(chosen_val)
    if chosen_amt == 0 or _possible(chosen_amt):
        return                            # valid as a total, or nothing parseable
    valid = [
        c for c in candidates.values()
        if _possible(_premium_dollars(c["display"]))
    ]
    if not valid:
        return                            # no possible total among the candidates
    # Among the valid: an exact match with the sum of the granted lines is the
    # total by definition; otherwise the ordinary score decides. Both only ever
    # pick from values the document actually stated.
    line_sum = sum(granted)
    exact = [c for c in valid if line_sum and _premium_dollars(c["display"]) == line_sum]
    pool = exact or valid
    best = max(
        pool,
        key=lambda c: _score_value(
            "total_policy_premium", c["record"], c["freq"], c.get("authority")),
    )
    logger.warning(
        "merge total_policy_premium ARITHMETIC reconciliation: %r is smaller "
        "than a single granted coverage line ($%s) and cannot be the package "
        "total - replaced with %r (%s). The rejected figure is a line premium "
        "that out-voted the real total on repetition (C45's known limit).",
        str(chosen_val)[:40], f"{largest:,}", best["display"][:40],
        "matches the sum of the lines" if exact else "best-scored valid candidate",
    )
    _rec = best["record"]
    if isinstance(_rec, dict) and "value" in _rec:
        # V1 plan C1 F11 (client 1.4 "Derived"): chosen by arithmetic over
        # the granted lines, not read off one label - say so on the envelope.
        _rec = dict(_rec, evidence_state="derived")
    merged_facts["total_policy_premium"] = _rec


def _score_composite_candidate(cand_text: str, child_candidates: Dict[str, dict]) -> tuple:
    """Rank a candidate COMPOSITE limits string. Higher is better.

    WHY THIS EXISTS — the fix above it was not enough, proven by a live run.
    Reconciling each scalar against the composite only works if the COMPOSITE is
    right. On a real package (ORBIN CONTRACTING, 2026-07-30) it was not: three
    composites tied on score and the winner was the UMBRELLA one —

        'each occurrence limit (liability coverage) $ 3,000,000; personal &
         advertising injury limit $ 3,000,000; aggregate limit (liability
         coverage) $ 3,000,000'

    — so gl_each_occurrence, gl_aggregate and gl_personal_advertising_injury all
    "agreed" with it and all came out $3,000,000 when the real GL part is
    $1M/$2M. The scalar check made no change and logged nothing, because the top
    scalar candidate already matched the wrong parent. It was not misfiring; it
    was blind to a wrong witness.

    Two structural signals, deliberately NOT keyword matching on coverage-part
    names (that heuristic has failed here three times — see the evidence-gate
    note in CLAUDE.md):

      1. `explained` — how many CHILD FIELDS this composite can account for, i.e.
         for how many of gl_each_occurrence / gl_aggregate /
         gl_products_aggregate / gl_personal_advertising_injury does the composite
         contain one of that child's own candidate amounts. A composite that
         explains the whole family is describing the same coverage part the
         scalars came from.
      2. `distinct` — how many DIFFERENT dollar amounts it lists. A real GL
         limits block enumerates several ($1M occurrence, $2M aggregate, $500k
         damage-to-premises, $10k medical); an umbrella block repeats one number.
         This is what separates the two GL candidates from the umbrella on the
         package above, and it needs no domain vocabulary at all.

    Measured on that package's exact strings:
        umbrella  {3M}                  explained=3  distinct=1
        GL short  {1M, 2M}              explained=4  distinct=2
        GL full   {1M, 500k, 10k, 2M}   explained=4  distinct=4   <- wins
    and the full GL breakdown is the correct answer.

    `explained` is ordered FIRST so a long endorsement paragraph that happens to
    contain many dollar figures cannot outrank a composite that actually accounts
    for the scalars.
    """
    amts = _money_amounts(cand_text)
    if not amts:
        return (0, 0)
    explained = 0
    for _child, _cands in child_candidates.items():
        child_amts = set()
        for _nk in _cands:
            child_amts |= _money_amounts(_nk)
        if child_amts & amts:
            explained += 1
    return (explained, len(amts))


# ── Shape-qualified candidate partition ──────────────────────────────────────
# `_score_value` below ranks competing values for a fact by
# `log1p(repetitions) + confidence`. `tier_weight` multiplies every candidate of
# the same field equally, so it cancels out of the ordering entirely - which
# means the ranking contains NOTHING ABOUT THE VALUE ITSELF. The most-repeated
# candidate wins. On a declarations page the thing that repeats on every page is
# the carrier's letterhead.
#
# Two measurements that make the point:
#   * one extra repetition is worth log1p(2)-log1p(1) = 0.405, while the whole
#     gap between `ai_high` (0.85) and `ai_low` (0.50) is 0.35 - so a
#     low-confidence value seen twice beats a high-confidence value seen once;
#   * nothing checks whether the value can even BE the thing (a 7-digit string
#     competing for a 9-digit FEIN wins if it appears more often).
#
# This is a PARTITION, not another weight. Candidates that pass their fact's own
# registry validator are ranked ahead of ones that cannot possibly be valid; if
# NONE qualify the whole list is returned untouched, so it can only ever reorder
# and never drops the last value. No magic number to calibrate.
#
# Only the four HARD shapes are enforced - FEIN, email, phone, URL - the same set
# `pdf_service._shape_violation` uses, for the same reason: C22's ~49,000-pair
# sweep showed an amount box legitimately holds "Statutory" or "Included", so a
# currency validator must never disqualify a candidate. Currency ordering stays
# entirely with the C23 composite-consistency logic below.
_HARD_SHAPE_FACTS: Optional[Dict[str, Any]] = None


def _hard_shape_facts() -> Dict[str, Any]:
    """{fact_key: validator} for facts whose shape is legally defined."""
    global _HARD_SHAPE_FACTS
    if _HARD_SHAPE_FACTS is None:
        out: Dict[str, Any] = {}
        try:
            from services.fact_registry import (
                FACT_REGISTRY, _is_email, _is_fein, _is_phone, _is_url,
            )
            hard = {_is_email, _is_fein, _is_phone, _is_url}
            for key, meta in FACT_REGISTRY.items():
                fn = (meta or {}).get("validate")
                if fn in hard:
                    out[key] = fn
        except Exception as exc:                          # noqa: BLE001
            logger.warning("shape-partition: validators unavailable — %s", exc)
        _HARD_SHAPE_FACTS = out
    return _HARD_SHAPE_FACTS


def _partition_by_shape(field: str, scored: list) -> list:
    """Stable-reorder `scored` so shape-valid candidates come first.

    Returns the input unchanged when the fact has no hard shape, when every
    candidate passes, or when every candidate fails - the last case being the
    one that guarantees a value is never lost to this.
    """
    validator = _hard_shape_facts().get(field)
    if validator is None or len(scored) < 2:
        return scored
    good, bad = [], []
    for entry in scored:
        try:
            (good if validator(str(entry[0])) else bad).append(entry)
        except Exception:                                 # noqa: BLE001
            good.append(entry)
    if not good or not bad:
        return scored
    return good + bad


# ── Source authority ─────────────────────────────────────────────────────────
# THE large-document root cause. `_score_value` ranks by repetition, and a
# declarations page states each figure exactly ONCE while the policy forms
# behind it mention rival figures on page after page. Measured against the real
# scorer: a wrong value needs only TWO mentions to beat the right one stated
# once at high confidence (1.599 vs 1.543). Across 17 chunks the authoritative
# statement is structurally the minority vote, so the more document we read, the
# worse the answer gets. On a ONE-chunk document every candidate has freq==1,
# the frequency term is constant and confidence decides correctly - which is
# exactly why small documents come out right and large packages do not.
#
# The signal is STRUCTURAL, deliberately carrying no insurance vocabulary: a
# declarations page is TABULAR (short lines, dense money and dates), a policy
# form is PROSE (long wrapped lines, almost no figures). A keyword list would be
# a per-carrier lookup in disguise and would not hold across the 17 forms or a
# carrier whose wording we have never seen. `test_authority_needs_no_insurance_
# vocabulary` fails the build if that ever stops being true.
# Deliberately NOT named _MONEY_TOKEN_RE: that name is already taken above by a
# CAPTURING pattern `_money_amounts` parses with float(). Redefining it here
# shadowed it, findall() started returning whole matches, and every C23 currency
# tiebreak test went red. Counting patterns and parsing patterns are different
# things and must not share a name.
_AUTHORITY_FIGURE_RE = re.compile(r"[$€£]\s?\d[\d,]*(?:\.\d{1,2})?")
_AUTHORITY_DATE_RE   = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
# Mean line length of wrapped policy prose vs a printed schedule row. Only the
# GAP between them matters - the score is a position between the two.
_PROSE_LINE_CHARS   = 75.0
_TABULAR_LINE_CHARS = 40.0
# Roughly one printed page. The unit the signal is about: "is there a
# declarations page in here", not "is this whole 56,000-char chunk one".
_AUTHORITY_WINDOW_CHARS = 3_000


def _window_authority(text: str) -> float:
    """Declarations-likeness of one window, 0.0 (prose) .. 1.0 (dense tabular)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return 0.0
    figures = (len(_AUTHORITY_FIGURE_RE.findall(text))
               + len(_AUTHORITY_DATE_RE.findall(text)))
    # One figure per line saturates: a schedule row carries an amount, prose does
    # not. Beyond that, more figures say nothing extra.
    figure_density = min(1.0, figures / len(lines))
    mean_len = sum(len(ln) for ln in lines) / len(lines)
    brevity = (_PROSE_LINE_CHARS - mean_len) / (_PROSE_LINE_CHARS - _TABULAR_LINE_CHARS)
    brevity = min(1.0, max(0.0, brevity))
    return 0.5 * figure_density + 0.5 * brevity


def declarations_authority(text: str) -> float:
    """Whether this span CONTAINS a declarations/schedule region - the MAXIMUM
    over page-sized windows, never the average across the span.

    Averaging was measured and rejected: an extraction chunk is 56,000 chars and
    a real dec page is a few thousand, so a genuine declarations page occupying
    14% of its chunk scored 0.174 - indistinguishable from pure policy prose at
    0.061. Chunk-mean would have shipped a fix that quietly does nothing on the
    documents it was built for.

    Max is deliberately the SENSITIVE choice. A limits table inside an
    endorsement can raise a boilerplate chunk too, but the cost of that is every
    chunk landing in one tier, which is a flat signal, which is exactly today's
    ranking (see _AUTHORITY_TIER_CUTS). A false positive costs nothing; a false
    negative costs the whole fix.

    Public: `_gather_chunks_async` stamps it onto every partial.
    """
    text = text or ""
    if len(text) <= _AUTHORITY_WINDOW_CHARS:
        return round(_window_authority(text), 4)
    step = max(1, _AUTHORITY_WINDOW_CHARS // 2)          # 50% overlap, so a
    best = 0.0                                           # region cannot be split
    for start in range(0, len(text), step):              # across two windows and
        window = text[start : start + _AUTHORITY_WINDOW_CHARS]   # diluted in both
        if not window:
            break
        best = max(best, _window_authority(window))
        if best >= 1.0:
            break
    return round(best, 4)


# Authority enters the score as a QUANTIZED TIER, never as a continuous weight.
# That is the whole safety argument: within one tier the expression below is
# byte-for-byte today's formula, so when a document cannot be discriminated
# (every chunk prose, or every chunk tabular) the ranking is not merely similar
# to the old one, it IS the old one. A continuous weight would silently reorder
# every fact in the system on every document - which is why the sibling
# `_partition_by_shape` above ships in shadow mode.
_AUTHORITY_TIER_CUTS = (0.25, 0.55)
# Must exceed the widest possible spread of (log1p(freq) + confidence). At 40
# chunks that is log1p(40) + 1.0 = 4.71, so 10.0 dominates with room to spare.
_AUTHORITY_GAIN = 10.0


def _authority_tier(authority: Optional[float]) -> int:
    """0 = prose, 1 = mixed, 2 = declarations. None/absent behaves as 0 for
    every candidate alike, which is a flat signal, not a demotion."""
    if authority is None:
        return 0
    return sum(1 for cut in _AUTHORITY_TIER_CUTS if authority >= cut)


# Authority is a claim about WHERE a value came from, and it is only meaningful
# for values a declarations page actually prints: amounts, dates, numbers, names,
# codes. A narrative does not live on a dec page - the fuller operations
# description is out in the prose, and ranking a tabular fragment above it would
# ENTRENCH the truncated-shorthand defect rather than fix it. So when any
# candidate for a fact is prose, authority sits out and the old ranking stands.
#
# Derived from the VALUE, not from a list of fact keys: `FACT_REGISTRY` has no
# `kind` column, and a name pattern would silently miss the next narrative fact
# somebody adds. Thresholds are set well clear of the longest atomic value a
# dec page prints - a full mailing address is ~45 chars / 8 tokens.
_PROSE_VALUE_CHARS = 100
_PROSE_VALUE_WORDS = 12

# A narrative candidate whose grammatical subject is the COVERAGE/POLICY
# itself ("... coverage ... is/are described/provided/afforded ...", "this
# policy/endorsement ..."). Such a sentence describes what the policy GRANTS,
# never what the business DOES, so it may not win a narrative fact while a
# genuine candidate exists. Used only to DEMOTE, never to blank.
_COVERAGE_META_RE = re.compile(
    r"\bcoverages?\b[^.]{0,120}?\b(?:is|are)\s+"
    r"(?:described|provided|afforded|included|excluded|extended)\b"
    r"|\b(?:this|the)\s+(?:policy|endorsement|coverage\s+(?:form|part))\b",
    re.I,
)


def _is_prose_value(s: str) -> bool:
    return len(s) > _PROSE_VALUE_CHARS and len(s.split()) > _PROSE_VALUE_WORDS


def _best_authority(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """A candidate is credited with the MOST authoritative place it was seen.

    Max, not mean: a figure printed on the declarations page does not become
    less trustworthy because the policy forms repeat it. The corollary is the
    known limit of this signal - when two RIVAL values both appear on the
    declarations page (a line premium against the package total, say) they land
    in the same tier and frequency decides between them exactly as before.
    Separating those needs the arithmetic reconciliation, not this.
    """
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _score_value(field: str, record: Any, freq: int,
                 authority: Optional[float] = None) -> float:
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

    # `base` is today's expression, unchanged. Authority is added on top as a
    # dominant quantized tier, so candidates from the SAME tier are ordered by
    # exactly the arithmetic that shipped before this change (see the block
    # comment at _AUTHORITY_TIER_CUTS).
    freq_score = math.log1p(freq)
    base = freq_score + conf_score
    return tier_weight * (_AUTHORITY_GAIN * _authority_tier(authority) + base)


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


# ── Natural keys: identifiers that pick out ONE real-world entity ───────────
# GENERIC by design. Rather than a bespoke dedup function per schedule - which
# is how the vehicle schedule went unprotected while drivers were covered - any
# schedule row carrying one of these identifiers de-duplicates on it, and a
# schedule added later is covered with no code change at all.
#
# Every entry here is unique BY CONSTRUCTION for the entity it names: one VIN is
# one vehicle, one driver's licence is one person, one serial number is one
# machine. Two rows sharing one describe the same thing and must merge.
#
# Measured on the client's real session 2026-08-12 (session 7d95a6e6):
#
#     2012 SUBARU OUTBACK                 vin=4S4BRCGC9C3217772
#     2012 SUBARU OUTBACK 2.5i SEDAN 4D   vin=4S4BRCGC9C3217772
#
# One vehicle described two ways on two pages, extracted as two rows. That is
# the "vehicle duplicated" defect reported on ACORD 127, and it also inflated
# every downstream row count - the phantom-row suppression, the fleet warnings
# and the ACORD 125 attachment box were all working from a fleet one vehicle
# too large.
#
# `policy_number` is DELIBERATELY ABSENT and must never be added: a policy
# carries many coverage parts, so merging on it would DELETE real lines.
# Measured on the same session - BBC7263-26 legitimately carries both
# Commercial General Liability and Employee Benefits Liability. Same trap that
# broke `_line_list_is_trustworthy` on its first run.
#
# Nothing here falls back to descriptive fields (year+make+model, name alone):
# a contractor can own two identical trucks bought together, and merging those
# would delete a real vehicle. No identifier, no merge - the same "positive
# evidence only" rule the rest of this module follows.
_NATURAL_ID_SUBKEYS: Tuple[str, ...] = (
    "vin", "license_number", "serial_number", "equipment_serial_number",
    "identification_number", "item_serial_number",
)
# Short strings collide; a real identifier of any of these kinds is longer.
_NATURAL_ID_MIN_CHARS = 6


def _natural_id_keys(item: dict) -> List[str]:
    """Candidate natural keys for ANY schedule row, from _NATURAL_ID_SUBKEYS."""
    keys: List[str] = []
    for sub in _NATURAL_ID_SUBKEYS:
        raw = re.sub(r"[\s\-.]", "", str(item.get(sub) or "")).strip().upper()
        if len(raw) >= _NATURAL_ID_MIN_CHARS:
            keys.append(f"{sub}:{raw}")
    return keys


def _coverage_line_dedup_keys(item: dict) -> List[str]:
    """Identity of ONE coverage-line row: the LINE plus the CONTRACT covering it.

    Needed because `_natural_id_keys` finds nothing on these rows (no VIN, no
    licence number), so every printing of the same coverage part would survive
    the union as its own row - the GL part alone is printed on the dec page, the
    certificate, the second dec page and the loss run.

    NEITHER HALF WORKS ALONE, and both failures are recorded above:
      * policy number alone - the comment on `_NATURAL_ID_SUBKEYS` measured
        `BBC7263-26` legitimately carrying both Commercial General Liability AND
        Employee Benefits Liability. Keying on the number would fold two real
        coverage parts into one.
      * line alone - that is the D-1 defect (2026-08-23). EMC's GL
        `BBC7263-26` and Travelers' GL `GL-4471102-26` are two different
        policies on the same line, and collapsing them is precisely what hid a
        real conflict from the producer.

    So identity is the PAIR. Same line + same contract = one row printed twice.
    Same line + different contract = two policies, both kept, which is what
    lets the scope logic say "two policies on the same coverage line".

    No policy number falls back to the line + the carrier's strict key: a
    certificate row often omits the number, and (GL, EMC) is still enough to
    recognise it as the dec page's GL row rather than a second policy. A row
    with no canonical line at all gets NO key and is never merged - the same
    positive-evidence rule the rest of this module follows.
    """
    line = _canon_line(item.get("line") or item.get("line_of_business"))
    if not line:
        return []
    pol = re.sub(r"[^0-9A-Za-z]", "", str(item.get("policy_number") or "")).upper()
    if len(pol) >= _NATURAL_ID_MIN_CHARS:
        return [f"coverage_line:{line}:{pol}"]
    try:
        from services.normalization import strict_entity_key
        car = strict_entity_key(item.get("carrier") or item.get("carrier_name") or "")
    except Exception:                                     # noqa: BLE001
        car = ""
    if car:
        return [f"coverage_line:{line}:carrier:{car}"]
    return []


# Bespoke key functions, for schedules needing MORE than the generic identifier
# scan (auto_drivers also matches on name+dob so a row missing its licence
# number still merges). Every other schedule uses _natural_id_keys.
def _wc_class_dedup_keys(item: dict) -> List[str]:
    """Identity of ONE employee-group / rating row: class code + state +
    payroll (V1 H3, 2026-08-27).

    `_natural_id_keys` finds nothing on these rows (no VIN, no licence), so a
    class table printed on the dec page AND the rating sheet survived the chunk
    union twice. Code + state alone would be WRONG: ACORD 130 prints one row
    per class per LOCATION, so two 5551 rows in CO with different payrolls are
    two real rows, and folding them keeps only the first payroll. The payroll
    figure is the third key, so only an exact reprint of the same row folds.
    A row missing any of the three gets NO key and is never merged.

    THE CODE IS READ THROUGH `coverage_evidence.wc_class_code_token`, the same
    door the normaliser uses. A raw strip was tried first and was WRONG: the
    identity runs BEFORE normalisation, so a premium summary printing
    "8810 Clerical" and a rating sheet printing "8810" produced two different
    keys, both rows survived, and the payroll-by-state derived from them
    doubled. Caught on the H3 live dry run, not by a unit test - the unit test
    fed both printings in the same shape.
    """
    try:
        from services.coverage_evidence import wc_class_code_token
        code = wc_class_code_token(item).upper()
    except Exception:                                     # noqa: BLE001
        code = re.sub(r"[^0-9A-Za-z]", "", str(item.get("code") or "")).upper()
    state = str(item.get("state") or "").strip().upper()
    pay = re.sub(r"[^\d]", "", str(item.get("payroll") or ""))
    if not (code and state and pay):
        return []
    return [f"wc_class:{code}:{state}:{pay}"]


_SCHEDULE_DEDUP_KEYS: Dict[str, Any] = {
    "auto_drivers": _driver_dedup_keys,
    "coverage_lines": _coverage_line_dedup_keys,
    "wc_class_codes": _wc_class_dedup_keys,
}


# ── A schedule row that is really the PRODUCER or the CARRIER ────────────────
# Live run 2026-08-12, two wrong boxes on two forms from ONE bad row: ACORD 127
# listed "ERIN ROYAL" - the producer contact at Commercial Risk Solutions - as a
# DRIVER, and ACORD 125 then ticked the DRIVER INFORMATION SCHEDULE attachment
# because `auto_drivers` was non-empty. The client had flagged both separately.
#
# The producer and the carrier are named all over a policy - the dec page
# header, the cancellation notice, the servicing-contact block, the signature
# line - so any person-schedule extracted from that text will eventually pick
# one of them up. They are parties TO the transaction; they are never members of
# the APPLICANT's own driver or officer schedule.
#
# Derived from the identity facts this same extraction already produced, so
# there is no name list, nothing carrier-specific, and it works for an agency we
# have never seen. Applied to person-schedules only - a company name legitimately
# repeats across property or vehicle rows.
_PERSON_SCHEDULE_KEYS: Tuple[str, ...] = ("auto_drivers", "wc_officers")

# Below this a "name" is too short to match safely ("Lee" would collide).
_PARTY_NAME_MIN_CHARS = 5

# Schedules keyed by ADDRESS rather than by name. Same principle, same defect:
# session 7d95a6e6 (2026-08-12) captured "9780 S Meridian Blvd STE 400,
# Englewood, CO 80112-6072" as the applicant's fourth PREMISES - it is the
# producer's own office, byte-identical to `producer_address`, and it printed on
# ACORD 125 as a location with no operations description.
_ADDRESS_SCHEDULE_KEYS: Tuple[str, ...] = ("property_locations",)


def _address_identity_key(value: Any) -> Optional[Tuple[str, str]]:
    """(street number, 5-digit ZIP) - enough to identify a building, and immune
    to the spelling differences that defeat whole-string comparison ("Suite 400"
    vs "STE 400", "S." vs "S"). Both parts are required; either alone would
    collide across a city."""
    if isinstance(value, dict):
        value = " ".join(
            str(value.get(k) or "")
            for k in ("address_line1", "address", "address_city", "address_zip")
        )
    text = str(value or "")
    number = re.match(r"\s*(\d{1,8})\b", text)
    zip5 = re.search(r"\b(\d{5})(?:-\d{4})?\b", text)
    if not number or not zip5:
        return None
    return (number.group(1), zip5.group(1))


def _identity_name_key(value: Any) -> str:
    """Letters-only, lowercased comparison key. Unwraps the annotated
    ``{"value": ..., "confidence": ...}`` envelope a merged fact may carry."""
    if isinstance(value, dict):
        value = value.get("value")
    return re.sub(r"[^a-z]+", " ", str(value or "").lower()).strip()


def _drop_transaction_party_rows(
    list_key: str, items: List[dict], facts: dict,
) -> List[dict]:
    """Remove person-schedule rows naming the producer or the carrier.

    Returns an EMPTY list when every row was such a party - that is the correct
    answer (there is no driver schedule), and it is what makes the ACORD 125
    attachment box resolve to an explicit "No" instead of ticking.
    """
    if not items:
        return items

    if list_key in _ADDRESS_SCHEDULE_KEYS:
        blocked_addr = {
            _address_identity_key(facts.get(key))
            for key in ("producer_address", "carrier_address")
        }
        blocked_addr.discard(None)
        if not blocked_addr:
            return items
        kept = []
        for item in items:
            if isinstance(item, dict) and _address_identity_key(item) in blocked_addr:
                logger.info(
                    "merge schedule_party_drop field=%r dropped=%r - that is the "
                    "producer's/carrier's own office, not a premises of the "
                    "applicant", list_key, str(item.get("address_line1") or item)[:70],
                )
                continue
            kept.append(item)
        return kept

    if list_key not in _PERSON_SCHEDULE_KEYS:
        return items
    blocked = {
        _identity_name_key(facts.get(key))
        for key in ("producer_contact_name", "producer_name", "carrier_name")
    }
    blocked = {b for b in blocked if len(b) >= _PARTY_NAME_MIN_CHARS}
    if not blocked:
        return items
    kept: List[dict] = []
    for item in items:
        name_key = _identity_name_key(item.get("name") if isinstance(item, dict) else None)
        if name_key and name_key in blocked:
            logger.info(
                "merge schedule_party_drop field=%r dropped=%r - that is the "
                "producer/carrier on this policy, not a member of the "
                "applicant's schedule",
                list_key, (item.get("name") if isinstance(item, dict) else item),
            )
            continue
        kept.append(item)
    return kept


def _dedupe_schedule_rows(list_key: str, items: List[dict]) -> List[dict]:
    """Merge rows describing the same entity, filling gaps from later duplicates
    rather than dropping their data. Two rows merge if ANY of their candidate
    keys match (see _driver_dedup_keys / _natural_id_keys).

    Schedules with special needs register a bespoke key function in
    `_SCHEDULE_DEDUP_KEYS`; EVERY other schedule falls back to the generic
    natural-identifier scan, so a row carrying a VIN, a licence number or a
    serial number de-duplicates without anyone registering it first. A row with
    no identifier at all is never merged."""
    key_fn = _SCHEDULE_DEDUP_KEYS.get(list_key) or _natural_id_keys
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


_DATE_ISH_RE = re.compile(r"^[\d/\-.\s]{6,12}$")
_FOUR_DIGIT_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _iso_date_or_none(sval: str) -> Optional[str]:
    """ISO form of a bare date string, else None. Never raises."""
    if not _DATE_ISH_RE.match(sval.strip()):
        return None
    try:
        from services.normalization import normalize_date
        return normalize_date(sval) or None
    except Exception:                                     # noqa: BLE001
        return None


def _variant_group_key(sval: str) -> str:
    """Group key that ignores FORMATTING but not CONTENT.

    THE VOTE-SPLITTING FIX. Cross-chunk merging used `sval.lower()` as the
    key, so two spellings of ONE value became two rivals and split their own
    frequency. Measured on a real 271-page package, every one of these was a
    self-inflicted contest between identical values:

        effective_date          '07/15/25'(4)      vs '07/15/2025'(3)
        producer_contact_phone  '303-996-7800'(3)  vs '(303)996-7800'(3)
        mailing_address         '... denver, co'(3) vs '... denver co'(3)
        auto_deductible_comp    '$1000 ded'        vs '1000 ded'
        gl_each_occurrence      '$1,000,000'       vs '$ 1,000,000'

    The mailing-address split is also what surfaced a phantom "documents
    disagree" conflict to the user on a SINGLE-document submission.

    Dates canonicalise through the shared `normalize_date` (so a two-digit
    year merges with its four-digit twin); everything else folds to
    alphanumerics. Genuinely different values - four different policy numbers,
    two different NAIC codes - still land in different groups and still
    compete, because they really are different.
    """
    s = sval.strip()
    iso = _iso_date_or_none(s)
    if iso:
        return "d:" + iso
    folded = re.sub(r"[^a-z0-9]+", "", s.lower())
    return folded or s.lower()


def _is_midword_truncation(short: str, long: str) -> bool:
    """True when `short` is `long` cut off MID-WORD - the carrier-shorthand
    shape ("commercial general contra" / "commercial general contractor").

    The mid-word test is the whole safety argument. "$1,000,000" is also a
    prefix of "$1,000,000 each accident", but the continuation begins at a
    word boundary: that is a QUALIFIED value, not a truncated one, and merging
    the two would put "each accident" into a limit box.
    """
    a, b = short.strip().lower(), long.strip().lower()
    if len(a) < 4 or len(a) >= len(b) or not b.startswith(a):
        return False
    return b[len(a)].isalnum() and a[-1].isalnum()


def _prefer_variant(new: str, current: str) -> bool:
    """Should `new` replace `current` as its group's representative?"""
    if _is_midword_truncation(current, new):
        return True                       # new restores truncated characters
    if _is_midword_truncation(new, current):
        return False
    # A four-digit year is the complete rendering of the same date.
    new_full = bool(_FOUR_DIGIT_YEAR_RE.search(new))
    cur_full = bool(_FOUR_DIGIT_YEAR_RE.search(current))
    if new_full != cur_full:
        return new_full
    return False                          # otherwise first-seen spelling holds


def _fold_truncated_groups(bucket: Dict[str, dict]) -> None:
    """Merge groups whose representative is a mid-word truncation of another's
    into that longer group, summing their frequencies. Mutates `bucket`."""
    keys = list(bucket)
    for short_key in keys:
        entry = bucket.get(short_key)
        if entry is None:
            continue
        for long_key in keys:
            if long_key == short_key or long_key not in bucket:
                continue
            target = bucket[long_key]
            if _is_midword_truncation(entry["display"], target["display"]):
                target["freq"] += entry["freq"]
                # The truncation's sighting counts for the group it folds into,
                # so its source authority has to travel with its frequency -
                # otherwise a dec-page value cut off mid-word would donate its
                # vote and lose its standing.
                target["authority"] = _best_authority(
                    target.get("authority"), entry.get("authority"))
                bucket.pop(short_key, None)
                break


def _merge_risk_transfer(partials: List[dict]) -> Optional[dict]:
    """Union of every chunk's `risk_transfer`: booleans OR, lists union
    (order-preserving), scalars first non-empty in chunk order. None when no
    partial carried the fact at all.

    WHY UNION AND NOT THE VOTE: the sub-facts live on single pages (an AI
    schedule, a waiver endorsement), so the chunks that saw them are always a
    small minority against chunks correctly reporting "nothing here". A vote
    is the wrong question - see the call-site comment in _merge_list_fields.
    Only ever ADDS information relative to any single chunk; a document with
    no risk-transfer content still merges to all-False/empty exactly as
    before.
    """
    merged: Optional[dict] = None
    for partial in sorted(partials, key=lambda p: p.get("_chunk_idx", 0)):
        rt = (partial.get("facts") or {}).get("risk_transfer")
        if not isinstance(rt, dict):
            continue
        if merged is None:
            merged = {}
        for k, v in rt.items():
            if isinstance(v, bool):
                merged[k] = bool(merged.get(k)) or v
            elif isinstance(v, list):
                bucket = merged.setdefault(k, [])
                if isinstance(bucket, list):
                    for item in v:
                        if item and item not in bucket:
                            bucket.append(item)
            elif v is not None and str(v).strip():
                if not str(merged.get(k) or "").strip():
                    merged[k] = v
            else:
                merged.setdefault(k, v)
    return merged


def _merge_list_fields(partials: List[dict], list_keys: List[str]) -> dict:
    if not partials:
        return {"facts": {}, "flags": {}}
    if len(partials) == 1:
        p = dict(partials[0])
        for k in ("_chunk_idx", "_char_start", "_char_end", "_authority"):
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
        # How declarations-like the chunk this fact came from was. Absent on
        # hand-built partials (replayed fixtures, the reconciliation path, any
        # pre-2026-08-12 session), and absent uniformly means a flat signal.
        p_auth = partial.get("_authority")
        for k, v in partial.get("facts", {}).items():
            if k in list_keys or k in ("wc_payroll_by_state", "risk_transfer") or _is_empty(v):
                continue
            # Extract canonical string value from annotated or raw form
            raw_val = v.get("value", v) if isinstance(v, dict) and "value" in v else v
            if _is_empty(raw_val):
                continue
            sval     = str(raw_val).strip()
            norm_key = _variant_group_key(sval)
            bucket   = val_candidates.setdefault(k, {})
            entry    = bucket.get(norm_key)
            if entry is None:
                entry = {"record": v, "freq": 0, "display": sval, "authority": p_auth}
                bucket[norm_key] = entry
            elif _prefer_variant(sval, entry["display"]):
                entry["record"], entry["display"] = v, sval
            entry["authority"] = _best_authority(entry.get("authority"), p_auth)
            entry["freq"] += 1

    # Fold carrier-shorthand truncations into their complete twin before any
    # scoring runs, so a value cut off mid-word cannot out-vote itself.
    for _bucket in val_candidates.values():
        _fold_truncated_groups(_bucket)

    merged_facts: dict = {}

    # Resolve COMPOSITE currency facts first so their scalar children can be
    # checked against them in the same pass (see _CURRENCY_COMPOSITE_PARENT).
    # Iteration order is otherwise irrelevant here — each field writes its own
    # independent key — so reordering is safe.
    _ordered_fields = sorted(
        val_candidates, key=lambda f: (f not in _CURRENCY_COMPOSITES, f)
    )

    # Read once per merge, not once per field.
    _partition_mode = os.getenv("SCORE_SHAPE_PARTITION", "shadow").strip().lower()

    for field in _ordered_fields:
        candidates = val_candidates[field]
        # Element 0 is the group's REPRESENTATIVE spelling, not the folded key:
        # every downstream consumer (shape partition, money-amount comparison,
        # the composite tiebreak, the logs) reads the real value that way.
        # A narrative fact opts out of source authority entirely (see
        # _is_prose_value): the fuller answer lives in the prose, so a tabular
        # fragment must not be promoted over it.
        _narrative = any(_is_prose_value(c["display"]) for c in candidates.values())
        scored = sorted(
            [(c["display"],
              _score_value(field, c["record"], c["freq"],
                           None if _narrative else c.get("authority")), c)
             for c in candidates.values()],
            key=lambda x: x[1], reverse=True,
        )

        # ── A FRAGMENT MUST NEVER OUT-VOTE A SENTENCE ────────────────────────
        # Measured on the client's real 271-page package (2026-08-12):
        #
        #   merge field='operations_description'
        #     chosen='COMMERCIAL GENERAL CONTRA'          score=2.95 freq=4
        #     rejected=["Contractors' equipment coverage and installation
        #                floater coverage for property used in contracting,
        #                installation, erection, repair, moving, ..."  freq=1,
        #               'Contractors - Executive Supervisors or Executive
        #                Superintendents; subcontractors in connection with
        #                construction, reconstruction, repair, ...'    freq=1]
        #
        # `COMMERCIAL GENERAL CONTRA` is a column header cut off mid-word,
        # repeated on four pages. `_score_value` is `log1p(freq) + confidence`,
        # so four repetitions of a fragment beat one statement of the real
        # thing. The client's verdict on the stamped result: "truncated carrier
        # shorthand, not a usable underwriting description".
        #
        # `_narrative` is ALREADY computed directly above - the code recognises
        # that this fact has a prose candidate and switches authority off for
        # it, then ranks the fragment first anyway. This makes it act on what it
        # already knows.
        #
        # Scope is deliberately tiny. It fires ONLY when a fact has BOTH a prose
        # candidate and a non-prose one, and `_is_prose_value` demands >100
        # chars AND >12 words - comfortably past the longest atomic value a
        # declarations page prints (a full mailing address is ~45 chars / 8
        # tokens), so no scalar fact can reach this branch. It REORDERS and
        # never discards: the fragment stays in the list, one place lower.
        #
        # Repetition is evidence of a repeated HEADER, not of a better answer.
        if _narrative and len(scored) > 1:
            _prose_c = [e for e in scored if _is_prose_value(e[0])]
            _frag_c  = [e for e in scored if not _is_prose_value(e[0])]
            if _prose_c and _frag_c and not _is_prose_value(scored[0][0]):
                logger.info(
                    "merge field=%r narrative partition: chose %r (a complete "
                    "statement) over %r (a %d-char fragment seen %d time(s)) - "
                    "repetition of a truncated header is not quality",
                    field, _prose_c[0][0][:90], scored[0][0][:60],
                    len(scored[0][0]), scored[0][2]["freq"],
                )
                scored = _prose_c + _frag_c

        # ── THE POLICY DESCRIBING ITSELF IS NOT AN ANSWER ────────────────────
        # Live 2026-08-14 run 3: operations_description shipped "Contractors'
        # equipment coverage and installation floater coverage are described,
        # including coverage for ..." - a sentence about the POLICY's grants,
        # stamped as what the BUSINESS does, because run-to-run jitter let it
        # out-score the genuine classification text. Same demote-never-discard
        # shape as the fragment rule above: when a narrative fact has a
        # candidate whose grammatical subject is the coverage/policy itself
        # AND at least one candidate that is not, every self-referential
        # candidate drops below every genuine one. It can only ever pick a
        # DIFFERENT real candidate, never blank the fact.
        if _narrative and len(scored) > 1:
            _meta_c = [e for e in scored if _COVERAGE_META_RE.search(e[0])]
            _gen_c  = [e for e in scored if not _COVERAGE_META_RE.search(e[0])]
            if _meta_c and _gen_c and _COVERAGE_META_RE.search(scored[0][0]):
                logger.info(
                    "merge field=%r coverage-meta demotion: %r describes the "
                    "POLICY, not the business - choosing %r instead",
                    field, _meta_c[0][0][:80], _gen_c[0][0][:80],
                )
                scored = _gen_c + _meta_c

        # Shape partition (see _partition_by_shape). SHADOW BY DEFAULT: the old
        # winner still ships and the disagreement is logged, because this reorders
        # candidates for every scalar fact in the system and that blast radius
        # deserves evidence from real documents before it changes output.
        # Set SCORE_SHAPE_PARTITION=on to enforce, off to silence.
        if _partition_mode != "off":
            _repartitioned = _partition_by_shape(field, scored)
            if _repartitioned and _repartitioned[0][0] != scored[0][0]:
                logger.warning(
                    "SHAPE_PARTITION field=%r would_choose=%r instead_of=%r "
                    "(mode=%s) — the rejected value is not a valid %s",
                    field, _repartitioned[0][0][:80], scored[0][0][:80],
                    _partition_mode, field,
                )
            if _partition_mode == "on":
                scored = _repartitioned

        # Tiebreaker for currency fields — NARROW ON PURPOSE. Read before widening.
        #
        # This used to re-sort the WHOLE candidate list by dollar magnitude
        # whenever the top two scores were within 0.01, i.e. "biggest number
        # wins". Three defects, all measured on a real package:
        #
        #  1. Across coverage parts it is inverted. A submission with a General
        #     Liability part ($1M each occurrence / $2M aggregate) AND a
        #     Commercial Liability Umbrella ($3M) had its GL facts filled from
        #     the UMBRELLA: `gl_each_occurrence` came out "$ 3,000,000" over
        #     "$1,000,000". Umbrella/excess limits are BY DEFINITION the larger
        #     ones, so this rule is wrong precisely where two parts coexist —
        #     which is most real packages. Wrong limits on a certificate of
        #     liability is the failure mode with legal exposure.
        #  2. The re-sort was global, not a top-two swap, so a candidate ranked
        #     5th on score could win on magnitude alone. That discards the
        #     scoring entirely on the strength of two entries being close.
        #  3. `_currency_magnitude` strips non-digits and parses the remainder,
        #     so on a COMPOSITE string ("each occurrence $1,000,000; general
        #     aggregate $2,000,000; products $2,000,000" — and `gl_limits` IS in
        #     `_CURRENCY_FIELDS`) it yields 1.0e+20. The tiebreak became
        #     "whichever string contains the most digits".
        #
        # All that survives is the single case the original comment actually
        # cites: a real limit beating a literal zero. Anything beyond that was
        # coincidence, not correctness. On a genuine tie between two non-zero
        # amounts, the COMPOSITE-CONSISTENCY check below decides it where it can,
        # and otherwise the ordinary scoring stands.
        # ── Composite SELECTION (must run before the scalar checks below) ────
        # A wrong composite makes every scalar that agrees with it wrong too, so
        # this is the load-bearing half of the C23 fix. See
        # `_score_composite_candidate` for the two structural signals and the
        # live measurement that forced it.
        if (
            field in _CURRENCY_COMPOSITES
            and len(scored) >= 2
            and abs(scored[0][1] - scored[1][1]) < 0.01   # effectively tied
        ):
            _kids = {
                _ch: val_candidates.get(_ch, {})
                for _ch in _CURRENCY_COMPOSITE_CHILDREN.get(field, [])
                if val_candidates.get(_ch)
            }
            if _kids:
                _tied_idx = [
                    i for i, (_nk, _s, _c) in enumerate(scored)
                    if abs(_s - scored[0][1]) < 0.01
                ]
                _best = max(
                    _tied_idx,
                    key=lambda i: _score_composite_candidate(scored[i][0], _kids),
                )
                if _best != 0:
                    logger.warning(
                        "merge field=%r composite SELECTION: chose %r over %r — it "
                        "explains %s of the scalar limit fields and lists more "
                        "distinct amounts. The rejected candidate is almost always "
                        "an umbrella/excess block, whose limits are by definition "
                        "larger and must NOT fill General Liability fields (C23).",
                        field,
                        scored[_best][0][:160], scored[0][0][:160],
                        _score_composite_candidate(scored[_best][0], _kids)[0],
                    )
                    scored = [scored[_best]] + [
                        s for i, s in enumerate(scored) if i != _best
                    ]

        if (
            field in _CURRENCY_FIELDS
            and len(scored) >= 2
            and abs(scored[0][1] - scored[1][1]) < 0.01   # effectively tied
        ):
            top_mag = _currency_magnitude(scored[0][0])
            if top_mag == 0:
                nonzero = next(
                    (i for i, (nk, _s, _c) in enumerate(scored)
                     if _currency_magnitude(nk) > 0),
                    None,
                )
                if nonzero is not None:
                    logger.info(
                        "merge field=%r currency tiebreak: chose %r over a zero-valued "
                        "candidate (the ONLY case the magnitude tiebreak still handles)",
                        field, scored[nonzero][0],
                    )
                    scored = [scored[nonzero]] + [
                        s for i, s in enumerate(scored) if i != nonzero
                    ]
            else:
                # Composite consistency (see _CURRENCY_COMPOSITE_PARENT). Without
                # this, a tie between the GL part's $1,000,000 and the umbrella's
                # $3,000,000 is settled by whichever chunk mentioned it first —
                # arbitrary, on a figure that prints on a certificate. Acts ONLY
                # when exactly one tied candidate's amount is actually present in
                # the already-resolved composite; otherwise the composite has
                # nothing to say and nothing changes.
                _parent = _CURRENCY_COMPOSITE_PARENT.get(field)
                _prec = merged_facts.get(_parent) if _parent else None
                if _prec is not None:
                    _pval = _prec.get("value", _prec) if isinstance(_prec, dict) else _prec
                    _pamts = _money_amounts(str(_pval))
                    if _pamts:
                        _tied = [
                            i for i, (_nk, _s, _c) in enumerate(scored)
                            if abs(_s - scored[0][1]) < 0.01
                        ]
                        _consistent = [
                            i for i in _tied
                            if _money_amounts(scored[i][0]) & _pamts
                        ]
                        # Group the consistent candidates by the AMOUNT they carry,
                        # not by their string. An earlier version required EXACTLY
                        # ONE consistent candidate and therefore did nothing on the
                        # real ORBIN package: '$ 1,000,000' and '$1,000,000' are two
                        # candidates for the SAME amount, both agreed with the
                        # composite, the count was 2, and the wrong $3,000,000 stayed
                        # in first place. Ambiguity means two DIFFERENT amounts, not
                        # two spellings of one.
                        _amt_sets = {
                            frozenset(_money_amounts(scored[i][0])) for i in _consistent
                        }
                        if _consistent and len(_amt_sets) == 1 and _consistent[0] != 0:
                            _pick = _consistent[0]
                            logger.warning(
                                "merge field=%r composite tiebreak: chose %r over %r — "
                                "its amount appears in %s and the rejected one's does "
                                "not. This is what stops an umbrella/excess limit "
                                "filling a General Liability field (C23). parent=%r",
                                field, scored[_pick][0], scored[0][0], _parent,
                                str(_pval)[:120],
                            )
                            scored = [scored[_pick]] + [
                                s for i, s in enumerate(scored) if i != _pick
                            ]
                        elif len(_amt_sets) > 1:
                            logger.info(
                                "merge field=%r composite tiebreak: no action — %d tied "
                                "candidates carry %d DIFFERENT amounts that all appear "
                                "in %s, so it cannot separate them",
                                field, len(_consistent), len(_amt_sets), _parent,
                            )
                        elif not _consistent:
                            logger.warning(
                                "merge field=%r composite MISMATCH: none of the %d tied "
                                "candidates %s appears in %s=%r. The scalar and the "
                                "composite disagree about this limit — the value stamped "
                                "on the form may be from a different coverage part.",
                                field, len(_tied), [scored[i][0] for i in _tied],
                                _parent, str(_pval)[:120],
                            )

        winner_nk, winner_score, winner_c = scored[0]
        merged_facts[field] = winner_c["record"]
        if len(scored) > 1:
            # Kept for the intra-document conflict check: a limit whose merge had
            # to CHOOSE between two materially different amounts is unresolved,
            # not decided (client 2026-08-15, the $3M/$1M umbrella limit inside
            # one package). Private key, stripped before the facts are stored.
            merged_facts.setdefault("_merge_rejected", {})[field] = [
                nk for nk, _sc, _c in scored[1:]
            ]
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
            # Runs AFTER dedup so a party appearing on several pages is one row
            # by the time it is dropped, and after the scalar loop above so the
            # producer/carrier identity facts it compares against are resolved.
            after = _drop_transaction_party_rows(lk, after, merged_facts)
            merged_facts[lk] = after

    # Runs AFTER the list merge above so `coverage_lines` is final, and while
    # the scalar candidate buckets still exist - the whole point is choosing a
    # DIFFERENT stated value, which no downstream resolver can do.
    _reconcile_total_premium(
        merged_facts, val_candidates.get("total_policy_premium") or {})

    # risk_transfer: UNION across chunks, never a vote. 52-page trap run
    # (2026-08-12): the Additional Insured schedule lives on ONE page, so one
    # chunk returned the three scheduled AI names and TEN chunks - which never
    # saw that page - returned an all-empty dict. The vote chose empty
    # (freq=11 beat freq=1) and three real additional insureds vanished from
    # the form. For a structured fact, ABSENCE of data is not an answer that
    # can outvote PRESENCE: booleans OR, name lists union, scalars first
    # non-empty in chunk order.
    _rt_union = _merge_risk_transfer(partials)
    if _rt_union is not None:
        merged_facts["risk_transfer"] = _rt_union

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
                    # Source authority for every fact this chunk produced. Scored
                    # here because `chunk_text` is in hand - no raw_text change,
                    # no OCR change, no new parameter on any signature, so the
                    # cached prompt prefix and the sentinel coverage test are
                    # untouched. See declarations_authority().
                    result.update({
                        "_chunk_idx": idx, "_char_start": c_start, "_char_end": c_end,
                        "_authority": declarations_authority(chunk_text),
                    })
                    await sem.record(retried=(attempt > 0))
                    if attempt > 0:
                        logger.info(f"chunk {idx}: recovered on attempt {attempt + 1} chars={c_start}–{c_end}")
                    else:
                        logger.debug(f"chunk {idx}: ok chars={c_start}–{c_end}")
                    return result
                except RuntimeError as ex:
                    # Schema / JSON-parse failure. This used to `raise`, on the
                    # theory that it is "not transient". That theory cost the
                    # client a whole upload on 2026-08-15: ONE chunk of a
                    # 271-page package came back unparseable and the raise blew
                    # straight through `asyncio.gather`, past the per-chunk
                    # retry budget, past the smaller-chunk document retry, past
                    # the PARTIAL-coverage reporting - every degradation path
                    # this function has - and returned a 500 to the browser.
                    #
                    # It is also not true. The usual cause is TRUNCATION at the
                    # output cap (now salvaged deterministically in
                    # `_safe_json_parse`), and what survives that is a
                    # non-deterministic model reply that a retry genuinely
                    # re-rolls. So it takes the ordinary retry path, and if the
                    # budget runs out the chunk is marked `chunk_failed` like
                    # any other failure - which `_run_extraction` already
                    # handles LOUDLY: failed indices, char ranges and coverage
                    # percentage are logged, `extraction_complete` goes False,
                    # and an all-chunks-failed document still raises.
                    #
                    # Losing one chunk of a document is a bad day. Losing the
                    # document is a worse one.
                    last_ex = ex
                    wait = 2 ** attempt + random.uniform(0, 0.5)
                    logger.warning(
                        f"chunk {idx} attempt {attempt + 1}/{_CHUNK_MAX_RETRIES} "
                        f"(chars {c_start}–{c_end}) JSON/schema failure — "
                        f"retrying in {wait:.1f}s: {ex}"
                    )
                    if attempt < _CHUNK_MAX_RETRIES - 1:
                        await asyncio.sleep(wait)
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
# ── THE DEDICATED DECLARATIONS-INDEX PASS ────────────────────────────────────
# WHY THIS EXISTS, measured rather than assumed. `dec_page_entries` is one key
# among ~170 in the main extraction schema, and the model budgets its answer
# across all of them: on the client's 271-page package it returned ~19 entries
# per chunk against a 150 allowance and a 16,000-token output cap, neither of
# which was binding. 250 entries recorded from ~30 declarations pages that
# carry an estimated ~750. The index is what Stage A of LLM call 2 reads first,
# so a thin index is a direct loss of fill quality - and it is why the same
# defect ("Limited Pollution Coverage - Work Sites $150") kept coming back:
# guards that key off the index are blind to whatever it failed to record.
#
# Attention is the constraint, so the fix is SEPARATION, not a bigger cap or a
# louder instruction. One prompt, one job: enumerate every label:value printed
# here. No facts, no flags, no coverage judgments.
#
# COST IS BOUNDED BY ROUTING, not by trimming the ask. Only chunks whose
# `declarations_authority` clears `_DEC_INDEX_MIN_AUTHORITY` are sent - the
# same scorer the retrieval filter already trusts, measured at 0.75 on a real
# dec page against 0.00 on policy wording. On the client's package that is a
# handful of chunks, not fourteen. Everything else about the pipeline is
# untouched: the main extraction prompt is byte-identical, so its cached prefix
# survives, and LLM call 2 never sees this pass at all.
#
# Set DEC_INDEX_DEDICATED_PASS=0 to disable and fall back to whatever the main
# extraction happened to record.
#
# ── OFF BY DEFAULT SINCE 2026-08-23, ON MEASUREMENT NOT OPINION ──────────────
# The pass ran end to end for the first time that day (a key-path bug had been
# discarding its output since the day it shipped - see LLMcall1-promptChange.md
# §31). With it finally working, the A/B was decisive and it lost:
#
#   cost   ~593,000 output tokens across 39 calls, against ~30,000 for the
#          WHOLE of facts+flags. Roughly 20x the rest of extraction combined.
#   time   18-20 minutes added to every cold upload.
#   gain   the owner regenerated the ACORD forms and reported them "almost the
#          same" as the ones the ~250-entry main-pass index had produced.
#
# The main extraction's own `dec_page_entries` key is restored and does the job
# as a passenger on a call that is already happening, at no extra cost - which
# is what every deterministic consumer (`_backfill_empty_facts_from_entries`,
# `_carriers_by_line`, `_resolve_section_policy_identity`, the payroll flag, the
# text-selection rescue) has actually run on for months.
#
# DISABLED RATHER THAN DELETED, deliberately. The machinery is measured and
# correct - bounded concurrency, split-on-truncation, label-aware Stage A
# packing - and the one configuration never tried on a form is the FILTERED
# index (1,341 entries, 17% of the document, one Stage A call). Deleting it
# would throw that away along with its tests. `DEC_INDEX_DEDICATED_PASS=1`
# turns it back on for an experiment; nothing calls it otherwise.
_DEC_INDEX_DEDICATED_PASS = os.getenv(
    "DEC_INDEX_DEDICATED_PASS", "0").strip().lower() not in ("0", "false", "no")
_DEC_INDEX_MIN_AUTHORITY = float(os.getenv("DEC_INDEX_MIN_AUTHORITY", "0.25"))
# EVERY chunk that clears the authority bar is indexed - the owner's stated
# requirement (2026-08-14) is FULL declarations coverage, the authority gate is
# the cost boundary, and an upload is already bounded by MAX_UPLOAD_SIZE_MB.
# The old default of 8 silently skipped dec pages on any package whose dec
# content spread across more chunks than that - a recall loss with no log line.
# >0 restores a hard cap as an emergency valve; when it trims, it WARNS with
# what it cost, so it can never be silent again.
_DEC_INDEX_MAX_CHUNKS = int(os.getenv("DEC_INDEX_MAX_CHUNKS", "0"))
# ── Output cap: a RUNAWAY GUARD, never the mechanism (2026-08-23) ────────────
# RAISED 16,000 -> 50,000 on measurement. The 13-key atomic schema costs ~86
# output tokens per entry against ~51 for the old 6-key one, and a 7,835-char
# fixture hit the 16,000 cap EXACTLY and was still cut off mid-object
# (`out=16000` in LLM_SPEND, 187 entries salvaged from a reply that wanted
# more). Every real chunk was therefore being truncated on every call.
#
# RAISING THIS DOES NOT RAISE THE BILL: output is billed on what the model
# actually writes, so the cap only decides where the text is severed. The model
# allows 128,000, so 50,000 keeps 2.5x headroom and still stops a looping model
# from writing forever and hanging the request. Do not remove it.
#
# It is NOT what guarantees a complete reply - `_DEC_INDEX_CHUNK_CHARS` is.
_DEC_INDEX_MAX_TOKENS = int(os.getenv("DEC_INDEX_MAX_TOKENS", "50000"))

# ── THE MECHANISM: bound the INPUT so the output is predictable ──────────────
# Measured on the 5_complex_tables fixture: 7,835 chars of declarations text
# produced >16,000 output tokens - over 2 output tokens per input character.
# The extraction chunk the router hands us is ~56,000 chars, which projects to
# ~114,000 output tokens: 89% of the model's ABSOLUTE 128,000 output ceiling,
# with no margin. That is unshippable, and no cap value fixes it - the reply
# simply cannot fit.
#
# The context WINDOW (400,000 tokens) is not the constraint here; the OUTPUT
# ceiling is, and it is a different and much smaller number. Input size is the
# only lever that moves output size, so the index pass re-splits its chunks:
# 15,000 chars projects to ~31,000 output tokens, comfortably inside the cap.
#
# Cost of splitting is small and worth naming: the total OUTPUT is unchanged
# (same document, same entries, just divided differently) and output is the
# expensive half. The extra cost is re-sending the instruction prefix, which
# runs at a measured 94% cache hit. More calls, same answer, no truncation.
#
# SIZED FROM A TIMED CALL, not from the cap alone (2026-08-23). One measured
# call: 7,907 chars in -> 21,672 output tokens in 89.2s = 243 tokens/sec. So a
# piece projects to ~2.05 output tokens per input char, and the two ceilings a
# piece must clear are the 50,000-token cap AND the 300s request timeout:
#     22,000 chars -> ~45,000 tokens -> ~185s   both cleared, with margin
#     15,000 chars -> ~31,000 tokens -> ~128s   safe but needlessly small
# 15,000 was the first cut and it was over-cautious: it turned a 13-chunk
# package into 47 calls and, at the pool size then in force, roughly half an
# hour of wall clock. 22,000 is the largest piece that still clears both
# ceilings, and it cuts the call count by a third.
_DEC_INDEX_CHUNK_CHARS = int(os.getenv("DEC_INDEX_CHUNK_CHARS", "22000"))

# ── Concurrency: THE bug that made this pass look broken ─────────────────────
# The pass used to fire every eligible chunk at once through a bare
# `asyncio.gather`, with no pacing of its own - unlike the main extraction,
# which has always used an adaptive semaphore. With the v3 prompt every call
# runs to the output cap, so 14 maximal calls launched together put roughly
# half a million tokens into one burst against a 200k TPM ceiling. The 429s
# exhausted all five retry attempts (~15s of backoff), every call raised, every
# error was swallowed into [], and the index came back built entirely by the
# main pass. That is the "my prompt did nothing" report.
#
# 3, AND MEASURED THIS TIME. It was briefly raised to 6 to claw back the wave
# count, which was a second blind tune - the TPM arithmetic says 6 does not fit:
#   one real call, measured: in=13,798  out=9,820  in 41s
#   = 23,618 tokens / 41s = ~35,000 tokens per minute PER CALL
#   pool 6 -> ~210,000 TPM, over the 200,000 ceiling before anything else runs
#   pool 3 -> ~105,000 TPM, with room for the main extraction beside it
# Wave count is the wrong thing to optimise while the pass is still indexing the
# WHOLE document; the fix for that is the authority gate, not more parallelism
# (see LLMcall1-promptChange.md §22).
_DEC_INDEX_POOL = max(1, int(os.getenv("DEC_INDEX_POOL", "3")))

# How many times a truncated reply may be split in half and retried before the
# salvage fallback takes over. 3 turns one 15,000-char piece into eight ~1,900-
# char pieces, which no realistic declarations page can overflow.
_DEC_INDEX_SPLIT_RETRIES = int(os.getenv("DEC_INDEX_SPLIT_RETRIES", "3"))

# PURPOSE FIRST, RULES SECOND (2026-08-16). The previous version opened with
# "you have exactly one job: list every label:value pair" and then governed
# `label`, `value` and `section` with seven rules - leaving `owner`,
# `policy_number` and `line_of_business` with NO rule at all. Those three ARE
# the relationship the client asked us to preserve, and the live index showed
# exactly what an ungoverned key produces: FOUR keys for TWO policies
# ('6E7-40-02---26' 77 entries / '6E74002' 4, 'BBC7263 - 26' 51 / 'BBC7263' 8),
# the Inland Marine number keyed WITH its OCR spacing ('6 C 7 - 4 0 - 0 2---26',
# which then printed that way on the client's ACORD 125), two names for one line
# ('General Liability' 37 / 'Commercial General Liability' 40), and one phone
# number owned by 'carrier' on one page and 'producer' on the next.
#
# The fix is the EVIDENCE-versus-KEY distinction, which the old prompt did not
# make: label/value/section are quotations and stay verbatim; owner/
# policy_number/line_of_business are join keys. Rule 1's verbatim instruction
# was being applied to fields it was never meant to govern.
#
# EXHAUSTIVENESS IS NOT A JUDGMENT CALL and must never read as one. Stating the
# downstream purpose creates pull toward "only record what fills a box", which
# would reverse the reason this pass exists (under-reporting). Rule 1 carries
# the counterweight explicitly - keep the two together if this is ever edited.
#
# WHAT THE PROMPT CAN AND CANNOT DO, measured on a re-run of the same package:
#   WORKS - owner definitions (one value owned two ways: 2 -> 0) and the
#           label-repeats-value rule (19 -> 1). Recall also rose 212 -> 261
#           entries, recovering the whole Inland Marine sub-limit schedule.
#   FAILS - asking for a canonical policy number or a fixed line vocabulary.
#           Both were tried as rules 8 and 9 and both made their metric WORSE
#           (a third umbrella spelling appeared; off-vocabulary line values went
#           2 -> 7). Deleted. That work is deterministic and now lives in
#           `_canonicalise_dec_entry_keys`, which runs after verification.
# The lesson generalises: ask the model for judgment it can exercise from the
# page in front of it, and do identity arithmetic in code.
#
# SIX PHRASES IN HERE ARE PINNED BY ANTI-ROT TESTS and are kept verbatim: the
# behaviours they guard all survive this rewrite, only the surrounding prose
# changed. tests/test_dec_index_dedicated_pass.py pins "VERBATIM",
# "BE EXHAUSTIVE", "one entry PER printed cell" and "NEVER concatenate";
# tests/test_run_20260814b_form_fixes.py pins "labels must differ exactly as the
# printed captions differ", "the amount's LABEL, not a separate entry" and
# "never shorten, reorder or reword". Each records a real production incident -
# a dozen inland-marine sub-limits labelled with the same row id collapsed 80
# entries into 26, and a paraphrased heading cost 17 entries their section. If
# you reword this prompt, run those two files before anything else.
# EXPERIMENT 2026-08-22 (owner): the prompt below replaces the 12-rule version
# wholesale to measure a structured-entry schema (kind / row / page, worked
# examples, block-by-block procedure). NOTHING ELSE CHANGED in this commit -
# `_verify_dec_entries` still whitelists the original six keys and still drops
# any entry whose label is empty, so `kind`/`row`/`page` and every
# label-null entry are visible ONLY in the per-document raw copies
# (documents[].facts.dec_page_entries), not in the merged index. Read the
# per-doc copies to judge the experiment; read the merged index to judge what
# call 2 saw. The history notes that used to sit inline in the old constant
# are preserved verbatim below; every measurement they record still stands.
#
# ---- history notes relocated from the previous constant ----
    # REVERTED to the pre-2026-08-16 wording, measured. The rewrite added
    # "never split one printed fact into two entries" immediately before the
    # 'Payroll $39,300' example, and the model read "do not split" as "collapse
    # the row": the GL class table went from SIX entries to ONE
    # ("Location 001 91580 Prem Basis" = "Payroll"), losing $39,300, $350,000,
    # class 91585 and the Total Cost basis - the client's own headline number
    # gone from the index. The original text below is imperfect (the model still
    # emits basis and amount as two entries) but it PRESERVES BOTH VALUES, and a
    # recorded pair beats a tidy single entry with the number missing.
    # REVERTED 2026-08-16 (C60). An example was appended here asking the model
    # to split a captionless run of figures - `COVERED AUTOS LIABILITY:
    # '01 $ 1,000,000 .$ 1,496.00'` - into symbol / limit / premium. Run
    # c655a44b returned those rows BYTE-IDENTICAL: measured zero effect. It was
    # removed rather than kept as harmless, because a measured-useless
    # instruction is not neutral in THIS prompt - rule 7 looked harmless too and
    # cost the GL class table for three runs. Nothing downstream needs the split
    # either: covered-auto symbols have `auto_covered_symbols` (per-coverage
    # attribution, 2026-08-07), line premiums have `_resolve_lob_premium`, the
    # limits have their own facts. Cost is a little Stage A retrieval quality on
    # those boxes; no value and no relationship is lost. Do not retry this in the
    # prompt - splitting a rating row positionally is C46's phantom-row pattern.
    # 6b ADDED 2026-08-22, and it is the one new rule the VERIFIER CANNOT
    # ENFORCE. In "SECTION III - LIMITS OF INSURANCE = 10" both halves are
    # literally printed, so `_verify_dec_entries` passes the entry, and the
    # index then offers a bare 10 to anything looking for a limit. A table of
    # contents is the one page shape whose label:value pairs are structurally
    # real and semantically empty, so the prompt is the only layer that can
    # refuse it. 6a is the pre-existing rule, unchanged in meaning, with the
    # endorsement case stated: a schedule block filled in with this insured's
    # own values is declarations content wherever it is printed.
    # SCOPED 2026-08-16 after a measured regression. The first wording was the
    # general instruction "Give the value the caption printed above or beside
    # it", which is a second, competing theory of what a label IS - and on a
    # rating table it beat rule 5's. Rule 5 says the basis word beside an amount
    # labels that amount ('Payroll' labels '$39,300'). Rule 7 pointed at the
    # column header ABOVE the basis word ('Prem Basis') and made 'Payroll' the
    # VALUE - at which point the amount had no entry left to live in. The GL
    # class table went 6 entries -> 1 and $39,300, $350,000, class 91585 and the
    # 'Total Cost' basis vanished from two consecutive runs after being present
    # in all seven before. Rule 5 was byte-identical across that change and was
    # wrongly blamed first. Now rule 7 states its one case and yields explicitly,
    # so the two can no longer disagree about the same cell.
    # RULES 8 AND 9 WERE HERE AND ARE DELETED, on measurement, not opinion.
    # They asked the model to emit ONE canonical policy number per contract and
    # to map line names onto a fixed vocabulary. Re-running the same package:
    # policies carrying more than one key went 2 -> 3 (the model invented a
    # THIRD umbrella spelling, '6J74002---26', beside '6J7-40-02---26'), and
    # off-vocabulary line values went 2 -> 7 (the Common Declarations rows came
    # back as 'Liability', 'Automobile', 'Umbrella', 'Crime and Fidelity' -
    # exactly what rule 9 forbade). They cost ~250 tokens per indexed chunk and
    # made both metrics WORSE. Canonicalising a join key is deterministic work
    # and now happens in `_canonicalise_dec_entry_keys` after verification,
    # where it can be proven. Do not reinstate them here.
    # RULES 9-11 ADDED 2026-08-22, NUMBERED AFTER 8 SO NOTHING ABOVE MOVES.
    # Rule 7 cites "rule 5 wins" by number and
    # tests/test_dec_entry_key_canonicalisation.py pins that phrase - renumber
    # the rules above and the citation points at the wrong rule.
    #
    # 9 IS THE ONE WITH MEASURED UPSIDE. `_carriers_by_line` pairs a carrier
    # with its NAIC out of ONE entry (FIX_TRACKING_2026-08-15, RC1) and starves
    # when the carrier name was never recorded at all - the normal case, because
    # a dec page prints the company name as a captionless header above the
    # section heading. The LABEL FALLBACK CHAIN is written this way on purpose:
    # `_verify_dec_entries` requires the LABEL to be literally present in the
    # document, so a made-up 'Carrier' caption would be dropped and would take
    # the carrier name down with it. Every step of the chain is text the page
    # actually prints.
    #
    # 10 and 11 close two label/value inversions seen on real packages: an
    # address line arriving as the caption of the next address line, and a
    # forms-and-endorsements list where each form number labelled itself
    # (rule 14's identical-text case, one level up - those entries record
    # nothing and crowd out the DEC_ENTRY_MAX budget).
    #
    # DELIBERATELY NOT ADDED, all three measured or verified first:
    #   - a `page` key: `_verify_dec_entries` rebuilds every kept entry from a
    #     fixed six-key whitelist, so it would never reach a consumer.
    #   - page-scoped policy_number ("only from the same page"): the
    #     [Document page N] markers exist only when the document has >1 page and
    #     the page has content (ocr_service `_PAGE_MARKERS_ON`), and chunking
    #     cuts mid-page, so the entries at the top of every chunk would be
    #     forced to null - starving `_policy_numbers_by_line`, which is what the
    #     2026-08-15 section-identity fix runs on. The borrowed-number defect it
    #     targets is already handled after verification by
    #     `_entry_self_attributes_its_own_identifier`, the ISO form-number clear
    #     and the printed-as-a-policy-number invariant.
    #   - a fixed line_of_business vocabulary: that is deleted rule 9. See the
    #     comment above rule 8 - it was measured making both metrics worse.
_DEC_INDEX_SYSTEM_PROMPT = """WHAT YOU ARE BUILDING AND WHY
You are building a structured index of every printed datum in an insurance document. It is the evidence base for automatically filling insurance forms. Downstream code never re-reads the document: it reads your entries, joins them on their keys, and stamps the values into named boxes.

You do NOT know which form will be selected. Different forms ask for different things under different names, at different depths. A form field name is a PATH - 'PriorCoverage / GeneralLiability / TotalPremiumAmount / instance A' - not a flat name. So you never decide what matters and you never guess a form's vocabulary. You record every printed datum as its own ATOMIC entry, wrapped in the printed hierarchy it sits inside, so that any form's path can find it later.

Two failures end this pass:
  * A printed value you did not record. Nothing downstream can tell it is missing.
  * A value welded to its neighbour, or filed under a heading instead of its own caption. It is present but unfindable.
Both are worse than a null key. A null key is repairable.

YOUR INPUT
A page-ordered text extract. Two markers structure it:
  [Document page N]                      every line after this is printed on page N
  [Table - page N ...] ... [End table]   a reconstructed table; cells separated by |

================================================================================
OUTPUT SCHEMA
================================================================================
Return exactly:

{"dec_page_entries": [{
  "id":               integer,
  "page":             integer,
  "kind":             "kv" | "standalone" | "heading" | "statement" | "footer" | "index",
  "path":             [string],
  "row":              string | null,
  "col":              string | null,
  "label":            string | null,
  "value":            string,
  "value_type":       "money" | "date" | "percent" | "number" | "code" | "phone" | "address" | "name" | "status" | "text",
  "qualifiers":       [string],
  "owner":            "applicant" | "producer" | "carrier" | "policy" | "other",
  "policy_number":    string | null,
  "line_of_business": string | null
}]}

EVERY field appears on EVERY entry. Use null or [] - never omit a key.
id is sequential from 1, in printed order.

THE FIELDS DO FOUR DIFFERENT JOBS.

  EVIDENCE - label, value. Copied verbatim, and ATOMIC. A later step discards any entry
  whose text is not literally in the document, so tidying a value destroys it.

  LOCATION - path, row, col. The printed hierarchy this value sits inside. Together with
  label they form the address a form field is matched against. This is what lets a form
  you have never seen find its answer.

  STRUCTURE - id, page, kind, value_type, qualifiers. What shape the printed thing is,
  where it sits, what type of datum it is, and what narrows it.

  KEYS - owner, policy_number, line_of_business. Which party, which contract, which
  coverage part. The joins run on these. Keep them identical across entries that share
  them; one spelling variant means the two never join.

SOME FIELDS ARE OPEN, SOME ARE CLOSED. This matters.
  OPEN   - path, label, row, col, qualifiers. No fixed vocabulary. YOU decide the words,
           taken from what the page actually prints. Depth is yours to choose. Use them.
  CLOSED - kind, value_type, owner, line_of_business. Fixed lists below. Never invent a
           new member, never abbreviate one.

================================================================================
RULES
================================================================================

1. RECORD EVERYTHING. BE EXHAUSTIVE.
   This is not a judgment call and never becomes one. Every premium, limit, deductible,
   date, code, identifier, address, phone, name, percentage, valuation, coverage line,
   status word - including EVERY numeric column of EVERY row in a rating or class table
   (rate, factor, exposure, cost new, per-row premium), not just the identity columns.
   A page printing forty values returns forty entries.
   Never skip a value because you cannot see a box for it. You do not know the form.
   Your judgment applies to how an entry is DECOMPOSED and ATTRIBUTED - never to whether
   it is worth recording.

2. ONE ENTRY = ONE ATOMIC DATUM. THE SPLIT TEST.
   A value is ONE thing: one amount, one date, one code, one name, one phrase, one status.
   Before writing a value, ask: can I draw a line inside this text where one side NAMES
   and the other side MEASURES? If yes, the naming side is the label, the measuring side
   is the value.
       WRONG   label:"SUPPLEMENTAL COVERAGES"  value:"POLLUTANT CLEANUP AND REMOVAL $ 25,000"
       RIGHT   path:["SUPPLEMENTAL COVERAGES"] label:"POLLUTANT CLEANUP AND REMOVAL" value:"$ 25,000"
   If the text holds TWO measured amounts, it is TWO entries:
       WRONG   value:"Virus and Hacking Limit any one occurrence $ 5,000 Limit each separate 12 month period $ 10,000"
       RIGHT   label:"Virus and Hacking Limit any one occurrence"  value:"$ 5,000"
               label:"Virus and Hacking Limit each separate 12 month period" value:"$ 10,000"
   A code and its wording are two entries: "91585 Contrctrs-sub work..." is a Code No.
   entry AND a Classification entry, never one.
   The ONLY value permitted to span multiple printed lines is a postal address (rule 15).
   A welded value is not literally printed as a unit, so it is discarded downstream.
   Splitting is not optional.

3. A HEADING IS NEVER A LABEL. IT IS A PATH SEGMENT.
   This is the most common and most damaging failure.
   When a heading stands above a list, block or column of items - 'LIMITS',
   'SUPPLEMENTAL COVERAGES', 'COVERAGE EXTENSIONS', 'DEDUCTIBLES', 'COVERAGES PROVIDED',
   'SCHEDULE OF UNDERLYING INSURANCE' - that heading goes in `path`. It NEVER goes in
   `label`. Each item printed under it carries its own caption. THAT is the label.

   path = the chain of headings enclosing this entry, OUTERMOST first, each verbatim.
       ["COMMERCIAL INLAND MARINE SCHEDULE", "SUPPLEMENTAL COVERAGES"]
       ["ITEM TWO: SCHEDULE OF COVERAGES AND COVERED AUTOS"]
       ["General Liability Declarations", "Limits of Insurance"]
   Depth is whatever the page prints - one level, three levels, or none ([] on a page
   with no heading at all). Do not pad it and do not flatten it.
   Copy each segment EXACTLY as printed. Never shorten, reorder or reword. A reworded
   heading joins to nothing.
   Record every heading ONCE as its own entry with kind "heading", then keep recording
   the block beneath it with that heading appended to path.

   DETECTION: if more than three entries on one page share a label, you have used a
   heading as a label. Go back and read each item's own caption.

4. COPY label AND value VERBATIM.
   Do not normalise, expand an abbreviation, reformat a number, strip a currency symbol,
   pad a date or fix a typo. Downstream code normalises; you do not.
   The label NAMES the value and is never part of it.

5. TABLES: ONE ENTRY PER PRINTED CELL, CARRYING row AND col.
   row = the printed identifier of the row, verbatim - class code, vehicle number, driver
   number, location number, item number, claim date, coverage name, whichever the table
   prints as that row's own name. If a row prints no identifier of its own, use the text
   of its first printed cell. Every cell of one row carries the SAME row string, spelled
   identically.
   col = the column header printed above that cell, verbatim. Every cell down one column
   carries the same col.
   label = the caption for THAT cell. Normally identical to col; where a row-level caption
   is what names it, use that instead.
   NEVER label several different cells with only the shared row identifier.
   NEVER weld two cells into one value.
   A basis word printed beside an amount ('Payroll $39,300') is that amount's LABEL, not
   a separate entry - and the amount must still be recorded.
   row + col is what lets a RATE be joined back to its class code when four rows each
   print a RATE. Without both, four entries labelled 'Rate' are indistinguishable, and two
   rows printing the same rate collapse into one.
   An entry not inside a table carries row null and col null.

6. qualifiers - WHAT NARROWS THIS VALUE. OPEN VOCABULARY. THINK HERE.
   Insurance values are almost never bare: the same caption carries different amounts
   depending on a peril, a basis, a location, a period, a trigger, a sub-limit tier. Those
   narrowing words are printed on the page, and if you leave them inside `value` the value
   is unusable, but if you drop them the entries become indistinguishable.
   Put each narrowing term in `qualifiers`, verbatim, one per element.
       'EARTHQUAKE "AGGREGATE" LIMIT $15,000'
           label:"LIMIT" value:"$ 15,000" qualifiers:["EARTHQUAKE","AGGREGATE"]
       'DEDUCTIBLE - "FLOOD"  NOT COVERED'
           label:"DEDUCTIBLE" value:"NOT COVERED" qualifiers:["FLOOD"]
       'Each Occurrence Limit $1,000,000'
           label:"Each Occurrence Limit" value:"$1,000,000" qualifiers:["Each Occurrence"]
   Typical qualifiers: a peril (EARTHQUAKE, FLOOD, SEWER BACKUP, WIND), a trigger
   (per occurrence, aggregate, catastrophe, jobsite, any one item), a basis (Payroll,
   Total Cost, Gross Sales), a period (12 month period, annual), a scope (per location,
   per vehicle, scheduled, unscheduled, blanket), a condition (ACV, Replacement Cost,
   80% coinsurance, waiting period).
   You are not choosing from a list. Take the words the page prints. Empty list is fine
   when nothing narrows the value.
   qualifiers NEVER replace the label and never replace path. The label still names the
   thing; qualifiers say which flavour of it this is.

7. kind - EVERY PRINTED LINE ENDS UP IN EXACTLY ONE.
   "kv"          a caption and its atomic value.  'Each Occurrence Limit' / '$1,000,000'
   "standalone"  a printed value with NO caption anywhere near it. label null.
                 'DIRECT BILL' printed alone in a declarations block. A carrier name
                 printed above the masthead with no caption.
   "heading"     a heading or sub-heading naming the block beneath it. label null,
                 value = the heading text. A column header row inside a table is also
                 "heading". Record it AND keep recording the block under it.
   "statement"   a sentence stating something about THIS policy. label null.
                 'See attached schedule for location of all premises owned, rented or
                 occupied.' It is not policy wording - it states a fact about this
                 contract and tells a later step that a premises schedule exists.
   "footer"      the form line at the foot of a page, carrying form number, edition date,
                 effective date and policy number on one line. label null, value = whole
                 line as printed.
   "index"       a line from a table of contents, quick reference or form index (rule 9b).
                 label null.
   NEVER drop a printed line because it does not look like a caption and a value.

8. value_type - CLOSED LIST. Pick the shape of the value as printed.
   money    an amount of currency, however printed: '$ 25,000', '1,496.00', '$0'
   date     a date or a date range: '07/15/2025', '07/15/26-07/15/27', '08-99'
   percent  '80%', '30%'
   number   a bare number that is not currency: a rate '3.4240', a count, a factor, hours
   code     an identifier: class code '91585', form number 'CG 00 01 04 13', policy number,
            VIN, NAIC, SIC, account number, location number
   phone    a telephone or fax number
   address  a postal address (rule 15)
   name     a person's or company's name
   status   a coverage disposition: 'No Coverage', 'NOT COVERED', 'COVERED', 'Included',
            'Excluded', 'Waived', 'Not Applicable', 'None', 'Closed', 'Open', 'DIRECT BILL'
   text     anything else - a classification wording, a description, a sentence, a heading

9. SCOPE.
   a. OUT OF SCOPE - record nothing. Policy wording, coverage forms, endorsement legal
      text, exclusions, definitions, conditions and hypothetical examples. That text
      describes what coverage WOULD mean, not what this policy grants.
      An endorsement page is in scope ONLY where it prints a schedule block filled in with
      this insured's own values: record that block and nothing else on the page.
      This is the ONLY thing you drop. A certificate's coverages table, an application's
      answers, a quote's or binder's terms, and a loss run's claim rows are all this
      insured's own values and are all IN SCOPE.
   b. TAGGED, NOT DROPPED. Tables of contents, quick-reference pages and form indexes.
      A page listing section or coverage names against small integers is an index, and
      those integers are page numbers, not values - stamping '10' into a limits box is a
      real danger. Record its lines with kind "index", label null, value = the line as
      printed, so downstream can filter them. NEVER turn an index line into a kv pair.

10. NEVER EMIT label == value.
    If the only text you have is the value itself, it is not a kv. Give it kind
    "standalone" (or "index" per rule 9b) with label null.
    An entry reading 'CG 00 01 04 13' = 'CG 00 01 04 13' records nothing and is discarded.
    This rule covers the identical-text case only. Where rule 5 has already decided which
    cell is the label, rule 5 wins.

11. page = the number from the [Document page N] marker the entry appears under.
    Never guess it, never carry it forward. Every entry has one.

12. owner - WHO THE VALUE IS ABOUT, not who printed it. Same for every page it appears on.
    applicant  the insured
    producer   the agency or broker
    carrier    the insurance company, including its claim-reporting and servicing numbers
    policy     the contract itself - numbers, terms, limits, deductibles, premiums,
               coverages, schedules
    other      any third party
    WHEN owner IS "other", THE LABEL MUST NAME WHICH KIND, copied from the page:
    Mortgagee, Loss Payee, Lienholder, Trustee, Co-Owner, Registrant, Additional Insured,
    Certificate Holder, Leaseback Owner, Employee As Lessor, Lender's Loss Payable,
    Breach Of Warranty, Owner.
    'other' with no kind named cannot be joined to any form box and is a wasted entry. If
    the page prints the party but names no interest type, use kind "standalone" and let
    path carry the printed heading - do not guess the type.

13. line_of_business - CLOSED LIST, spelled exactly:
       General Liability | Commercial Auto | Commercial Umbrella | Inland Marine
       Property | Crime | Workers Compensation | Professional Liability
       Cyber | Employment Practices Liability | Commercial Package
    If the document names a coverage part not on this list, use the full name exactly as
    the page prints it - never an abbreviation, never your own shortening. 'GL' one time
    and 'General Liability' the next means the two never join.
    Use null when the entry is not specific to one coverage part: an account number, the
    insured's name, the producer's phone, a package-wide total.
    This is the key the forms are filled from. It matters more than any other.

14. A ROW'S OWN KEYS BEAT THE PAGE HEADER.
    A page header's policy number belongs only to entries of that policy's own line.
    When a table row names its own coverage line - a loss run's LINE column, an
    underlying-insurance schedule's TYPE OF POLICY column, a premium summary's COVERAGE
    PART column - that row's line_of_business is the ROW'S, and its policy_number is the
    number printed FOR that line: on the row itself, or in a carrier-by-coverage-part
    block. If the only number in sight is the header's and the header's line differs from
    the row's, policy_number is null.
    A common or package declarations page printing an account number and no policy number
    describes the whole package: its entries carry policy_number null.

15. A RESOLUTION BLOCK IS THE ANSWER KEY - NEVER SKIP IT.
    Some pages print a block stating which carrier and which policy number belong to which
    coverage part, headed 'CARRIER BY COVERAGE PART', 'SCHEDULE OF COVERAGE PARTS',
    'SCHEDULE OF UNDERLYING INSURANCE' or similar. That block is the most valuable thing
    on the page: it is what lets every other entry be keyed correctly. Record every line
    of it as its own entry, and use it to fill policy_number and line_of_business on
    entries elsewhere that would otherwise be null.

16. THE CARRIER IS OFTEN PRINTED WITHOUT A LABEL, AND IS THE MOST-MISSED REQUIRED VALUE.
    On most declarations pages the insurance company name is the first line on the page,
    printed above the section heading, or set inside the box holding the policy number. It
    carries no caption, so it is easily missed - and a coverage part whose carrier was
    never recorded cannot be filled onto any form.
    EVERY coverage part in this document must end with at least one entry whose owner is
    "carrier" and whose value is a COMPANY NAME, value_type "name". A claim-reporting or
    servicing PHONE NUMBER is not a carrier name and does not satisfy this.
    Record it: value = the company name as printed, owner "carrier", line_of_business =
    the coverage part of the page it appears on, policy_number = the number printed on
    that same page. Caption printed beside it -> kind "kv" with that label. No caption
    anywhere near it -> kind "standalone", label null.
    A package may be written by several member companies of the same group. Two coverage
    parts naming two different companies is normal and both must be recorded against their
    own coverage part. Never assume one carrier writes the whole package.

17. AN ADDRESS IS ONE VALUE, AND A NAME IS NOT PART OF IT.
    A postal address printed across several lines is a single value: join the lines with a
    single space, in printed order, value_type "address". Downstream code splits it into
    street, city, state and postal code - you do not.
    A party's NAME and their ADDRESS are two entries: the name takes the printed caption
    ('Named Insured', 'PRODUCER'), the address takes that caption plus 'Address'.
    NEVER make one line of an address the label of another line - a street line is not the
    caption of a city line. Never fold a name into an address block.

18. A LIST OF FORM NUMBERS IS NOT A LIST OF label:value PAIRS.
    Applicable-forms lists are worth recording, and are often printed as comma-separated
    runs across several lines rather than as a table - record those too.
    label = the caption printed above the list ('Forms Applicable', 'FORMS AND
    ENDORSEMENTS', 'EDITION'), value = ONE form number per entry, with its edition date if
    printed alongside.
    Where a forms schedule prints a form number, a form date and a description across one
    row, those are three entries sharing one row (rule 5) - never a FORM DATE entry
    orphaned from the form number it belongs to.

19. STATUS WORDS ARE VALUES.
    'No Coverage', 'NOT COVERED', 'COVERED', 'Included', 'Waived', 'Not Applicable',
    'None', 'Excluded' - record them, value_type "status". A line the policy declines to
    cover is data, and it is often the finding a reviewer most needs.

20. NEVER OMIT THESE, EVER.
    A page's own premium, limit, deductible, policy number, carrier name, effective and
    expiration date, class code, exposure, rate, claim amount, and every line marked
    'No Coverage' must always produce an entry. If a keying rule makes one ambiguous,
    record the entry and set the ambiguous KEY to null. Never resolve ambiguity by staying
    silent.

21. If this text contains nothing that states this insured's own values - no declarations,
    schedule, certificate, application, quote, binder or loss-run content - return an
    empty list.

================================================================================
WORKED EXAMPLES
================================================================================

A. A BLOCK UNDER A HEADING. The heading is PATH, never label. Printed on page 14, under
   the page heading 'COMMERCIAL INLAND MARINE SCHEDULE':

      SUPPLEMENTAL COVERAGES
      POLLUTANT CLEANUP AND REMOVAL                     $ 25,000
      RENTAL REIMBURSEMENT LIMIT                        $ 7,500
      WAITING PERIOD                                    72 HRS
      Virus and Hacking  Limit any one occurrence $ 5,000  Limit each separate 12 month period $ 10,000

   SIX entries:
   {id:41, page:14, kind:"heading", path:["COMMERCIAL INLAND MARINE SCHEDULE"],
    label:null, value:"SUPPLEMENTAL COVERAGES", value_type:"text", qualifiers:[]}
   {id:42, page:14, kind:"kv", path:["COMMERCIAL INLAND MARINE SCHEDULE","SUPPLEMENTAL COVERAGES"],
    label:"POLLUTANT CLEANUP AND REMOVAL", value:"$ 25,000", value_type:"money", qualifiers:[]}
   {id:43, ... label:"RENTAL REIMBURSEMENT LIMIT", value:"$ 7,500", value_type:"money", qualifiers:[]}
   {id:44, ... label:"WAITING PERIOD", value:"72 HRS", value_type:"number", qualifiers:[]}
   {id:45, ... label:"Virus and Hacking Limit", value:"$ 5,000",  value_type:"money", qualifiers:["any one occurrence"]}
   {id:46, ... label:"Virus and Hacking Limit", value:"$ 10,000", value_type:"money", qualifiers:["each separate 12 month period"]}

   NOT four entries all labelled "SUPPLEMENTAL COVERAGES" with the real caption buried
   inside the value. That is the failure this rule exists to stop.

B. A DEDUCTIBLE AND LIMIT BLOCK. Amount printed FIRST; the caption still names it, and the
   peril is a qualifier. Printed under heading 'LIMITS':

      $ 500        DEDUCTIBLE - EARTHQUAKE AND VOLCANIC ERUPTION
      NOT COVERED  DEDUCTIBLE - "FLOOD"
      $ 15,000     EARTHQUAKE "AGGREGATE" LIMIT
      $ 15,000     EARTHQUAKE "OCCURRENCE" LIMIT
      $ 15,000     EARTHQUAKE "CATASTROPHE" LIMIT

   FIVE entries, all path [...,"LIMITS"], all label "DEDUCTIBLE" or "LIMIT", separated by
   qualifiers - NOT five entries labelled "LIMITS":
   {label:"DEDUCTIBLE", value:"$ 500",       value_type:"money",  qualifiers:["EARTHQUAKE AND VOLCANIC ERUPTION"]}
   {label:"DEDUCTIBLE", value:"NOT COVERED", value_type:"status", qualifiers:["FLOOD"]}
   {label:"LIMIT",      value:"$ 15,000",    value_type:"money",  qualifiers:["EARTHQUAKE","AGGREGATE"]}
   {label:"LIMIT",      value:"$ 15,000",    value_type:"money",  qualifiers:["EARTHQUAKE","OCCURRENCE"]}
   {label:"LIMIT",      value:"$ 15,000",    value_type:"money",  qualifiers:["EARTHQUAKE","CATASTROPHE"]}
   Three identical amounts stay three distinguishable entries. Without qualifiers they
   collapse into one.

C. A CLASS-CODE RATING ROW. row = the class code, NOT the location. Printed:

      Location 001 | 91585 | Contrctrs-sub work in connection w/construction | Payroll | $350,000 | 3.4240 | $1,198

   SEVEN entries, every one carrying row "91585":
   {row:"91585", col:"Location",       label:"Location",       value:"Location 001", value_type:"code"}
   {row:"91585", col:"Code No.",       label:"Code No.",       value:"91585",        value_type:"code"}
   {row:"91585", col:"Classification", label:"Classification", value:"Contrctrs-sub work in connection w/construction", value_type:"text"}
   {row:"91585", col:"Prem Basis",     label:"Prem Basis",     value:"Payroll",      value_type:"text"}
   {row:"91585", col:"Exposure",       label:"Exposure",       value:"$350,000",     value_type:"money", qualifiers:["Payroll"]}
   {row:"91585", col:"Rate",           label:"Rate",           value:"3.4240",       value_type:"number"}
   {row:"91585", col:"Advance Prem",   label:"Advance Prem",   value:"$1,198",       value_type:"money"}
   The next row's Rate carries row "91580". Without row + col the two rates are
   indistinguishable and the joins are guesswork.

D. A CERTIFICATE COVERAGES ROW. Printed:

      General Liability | BBC7263-26 | 07/15/26-07/15/27 | Each Occurrence $1,000,000
                                                           General Aggregate $2,000,000

   FOUR entries, every one row "General Liability", line_of_business "General Liability":
   {row:"General Liability", col:"POLICY NUMBER", label:"POLICY NUMBER", value:"BBC7263-26",        value_type:"code"}
   {row:"General Liability", col:"POLICY PERIOD", label:"POLICY PERIOD", value:"07/15/26-07/15/27", value_type:"date"}
   {row:"General Liability", col:"LIMITS", label:"Each Occurrence",   value:"$1,000,000", value_type:"money", qualifiers:["Each Occurrence"]}
   {row:"General Liability", col:"LIMITS", label:"General Aggregate", value:"$2,000,000", value_type:"money", qualifiers:["General Aggregate"]}

E. A LOSS RUN CLAIM ROW, on a loss run headed 'Policy Number: 6E7 40 02 26'. Printed:

      11/02/2022 | General Liability | Water damage to customer premises | $12,300 | $0 | Closed

   FIVE entries, row "11/02/2022", line_of_business "General Liability" from the row's own
   LINE column - and policy_number NULL, because 6E7 40 02 26 is the automobile policy and
   this row names a different line (rule 14):
   {row:"11/02/2022", col:"LINE",        label:"LINE",        value:"General Liability",  value_type:"text",   policy_number:null}
   {row:"11/02/2022", col:"DESCRIPTION", label:"DESCRIPTION", value:"Water damage to customer premises", value_type:"text", policy_number:null}
   {row:"11/02/2022", col:"PAID",        label:"PAID",        value:"$12,300",            value_type:"money",  policy_number:null}
   {row:"11/02/2022", col:"RESERVED",    label:"RESERVED",    value:"$0",                 value_type:"money",  policy_number:null}
   {row:"11/02/2022", col:"STATUS",      label:"STATUS",      value:"Closed",             value_type:"status", policy_number:null}

F. A DECLARATIONS MASTHEAD. Not everything is a caption and a value. Printed:

      EMC Property & Casualty Company
      General Liability Declarations
      DIRECT BILL
      See attached schedule for location of all premises owned, rented or occupied.
      Form CG7000A Ed. 08-99 07/15/2025 BBC7263 2601

   The heading line becomes the first path segment for the page. Nothing is dropped:
   {kind:"standalone", path:[], label:null, value:"EMC Property & Casualty Company",
    value_type:"name", owner:"carrier", line_of_business:"General Liability"}
   {kind:"heading",    path:[], label:null, value:"General Liability Declarations", value_type:"text"}
   {kind:"standalone", path:["General Liability Declarations"], label:null,
    value:"DIRECT BILL", value_type:"status", owner:"policy"}
   {kind:"statement",  path:["General Liability Declarations"], label:null,
    value:"See attached schedule for location of all premises owned, rented or occupied.", value_type:"text"}
   {kind:"footer",     path:["General Liability Declarations"], label:null,
    value:"Form CG7000A Ed. 08-99 07/15/2025 BBC7263 2601", value_type:"text"}

G. A QUICK-REFERENCE / INDEX PAGE. Tagged, never turned into fake kv pairs. Printed:

      COMMERCIAL GENERAL LIABILITY QUICK REFERENCE
      CG 00 01 04 13
      CG 21 06 12 23

   {kind:"heading", label:null, value:"COMMERCIAL GENERAL LIABILITY QUICK REFERENCE", value_type:"text"}
   {kind:"index",   path:["COMMERCIAL GENERAL LIABILITY QUICK REFERENCE"], label:null, value:"CG 00 01 04 13", value_type:"code"}
   {kind:"index",   path:["COMMERCIAL GENERAL LIABILITY QUICK REFERENCE"], label:null, value:"CG 21 06 12 23", value_type:"code"}
   NEVER {label:"CG 00 01 04 13", value:"CG 00 01 04 13"}.

================================================================================
HOW TO WORK
================================================================================
Go BLOCK BY BLOCK down each page, in printed order. A declarations page is a stack of
blocks - a masthead, a party block, a limits block, a premium block, a forms block, a
footer.

For each block:
  1. Read its heading. Push it onto `path`. Record it once as kind "heading".
  2. Walk the items beneath it ONE AT A TIME.
  3. For each item: find its OWN caption (label), split off the narrowing words
     (qualifiers), take the bare datum (value), assign its type.
  4. Finish the block completely before starting the next. Pop the heading off `path`.

Do not scan a page for things that look important. A block you skim is a block you lose.

================================================================================
BEFORE YOU RETURN - RUN THESE CHECKS
================================================================================
1. COLLAPSE CHECK. Group your entries by label, per page. Does any label appear more than
   three times? If yes you used a heading as a label (rule 3). Move it into `path` and
   re-read each item's own caption.

2. SPLIT CHECK. Does any value contain BOTH a word of four or more letters AND an amount,
   date or percentage? If yes it is two entries (rule 2). Split it. Addresses and full
   sentences recorded as kind "statement" or "footer" are the only exceptions.

3. QUALIFIER CHECK. Do two entries share a label AND a value AND a row? If yes, either
   they are one entry duplicated, or you dropped the qualifier that distinguishes them.

4. IDENTITY CHECK. Does any entry have label == value? Fix it to "standalone" or "index"
   (rule 10).

5. CARRIER CHECK. List every line_of_business you emitted. Does each have at least one
   owner "carrier" entry whose value is a COMPANY NAME? A phone number does not count
   (rule 16).

6. ROW CHECK. Does every table cell carry both row and col, spelled identically across the
   row and down the column? Does any label repeat within a single row?

7. COVERAGE CHECK. Read each page again, line by line. Does EVERY printed line appear in
   at least one entry - as a value, a label, a qualifier or a path segment? Name the ones
   that do not. If rule 9a does not exclude it, it needs an entry.

8. KEY CHECK. Is a page header's policy number sitting on a row that names a different
   line? Is every line_of_business one of the listed spellings or a full printed name? Is
   every kind, value_type and owner a member of its closed list? Does every entry carry
   its page and a sequential id?

9. SOURCE CHECK. Is this an application, certificate, quote, binder or loss run you
   returned nothing for? It states the insured's own values and is in scope."""


async def _harvest_dec_index(chunks: List[ChunkTuple]) -> List[dict]:
    """Index-only LLM pass over the declarations-dense chunks. Never raises."""
    if not _DEC_INDEX_DEDICATED_PASS or not chunks:
        return []
    try:
        ranked = sorted(
            ((declarations_authority(c[0]), i, c[0]) for i, c in enumerate(chunks)),
            key=lambda t: -t[0],
        )
        eligible = [(i, txt) for score, i, txt in ranked
                    if score >= _DEC_INDEX_MIN_AUTHORITY]
        picked = (eligible if _DEC_INDEX_MAX_CHUNKS <= 0
                  else eligible[:_DEC_INDEX_MAX_CHUNKS])
        if len(picked) < len(eligible):
            logger.warning(
                "dec_index_pass: DEC_INDEX_MAX_CHUNKS=%d trimmed %d of %d "
                "declarations-dense chunk(s) - their pages fall back to the "
                "thin main-pass index",
                _DEC_INDEX_MAX_CHUNKS, len(eligible) - len(picked), len(eligible),
            )
        if not picked:
            logger.info("dec_index_pass: no chunk cleared authority %.2f - skipped",
                        _DEC_INDEX_MIN_AUTHORITY)
            return []
        logger.info(
            "dec_index_pass: %d of %d chunk(s) are declarations-dense (authority "
            ">= %.2f) - running the dedicated index call on those",
            len(picked), len(chunks), _DEC_INDEX_MIN_AUTHORITY,
        )

        # ── Sub-split: the index pass reads SMALLER pieces than extraction ───
        # See `_DEC_INDEX_CHUNK_CHARS`. Splitting on line boundaries keeps a
        # printed row whole; a single line longer than the budget is passed
        # through rather than cut mid-value, because a severed line is exactly
        # the welded/half value the verbatim gate would discard anyway.
        def _sub_split(text: str, budget: int) -> List[str]:
            if len(text) <= budget:
                return [text]
            out, cur = [], ""
            for line in text.splitlines(keepends=True):
                if cur and len(cur) + len(line) > budget:
                    out.append(cur)
                    cur = line
                else:
                    cur += line
            if cur:
                out.append(cur)
            return out or [text]

        # ── THE GATE RUNS AGAIN, ON EACH PIECE (2026-08-23) ─────────────────
        # `declarations_authority` is the MAXIMUM over page-sized windows, which
        # is right for ROUTING a chunk (a real dec page occupying 14% of a
        # 56,000-char chunk must not be averaged away) but wrong for BILLING
        # one: a chunk containing a single dec page among fifty pages of policy
        # wording clears the gate, and the whole 56,000 chars were then indexed.
        # On the client's 271-page package - ~30 declarations pages out of 271 -
        # that sent roughly 240 pages of wording to the model for nothing, and
        # cost a measured 3x on the time to recommend forms.
        #
        # Splitting first and re-scoring each piece keeps the sensitive routing
        # (nothing declarations-dense is skipped, because a piece is close to
        # page-sized and the max is taken over it) while dropping the wording
        # that merely travelled with it. Strictly more accurate AND cheaper.
        # A chunk whose pieces ALL fall below the bar keeps its single best
        # piece rather than contributing nothing - the chunk did clear the bar,
        # so something in it is declarations content.
        pieces: List[Tuple[int, str]] = []
        _dropped_pieces = 0
        for _i, _txt in picked:
            _subs = [p for p in _sub_split(_txt, _DEC_INDEX_CHUNK_CHARS) if p.strip()]
            if len(_subs) <= 1:
                pieces.extend((_i, p) for p in _subs)
                continue
            _scored = [(declarations_authority(p), p) for p in _subs]
            _keep = [(s, p) for s, p in _scored if s >= _DEC_INDEX_MIN_AUTHORITY]
            if not _keep:
                _keep = [max(_scored, key=lambda t: t[0])]
            _dropped_pieces += len(_subs) - len(_keep)
            pieces.extend((_i, p) for _, p in _keep)
        if len(pieces) != len(picked) or _dropped_pieces:
            logger.info(
                "dec_index_pass: %d declarations chunk(s) -> %d piece(s) of <=%d "
                "chars (%d piece(s) dropped as not declarations-dense). Smaller "
                "pieces keep every reply inside the output cap; re-scoring keeps "
                "policy wording that merely shared a chunk out of the bill.",
                len(picked), len(pieces), _DEC_INDEX_CHUNK_CHARS, _dropped_pieces,
            )

        # Bounded concurrency. The unbounded gather that used to live here is
        # what killed this pass under load - see `_DEC_INDEX_POOL`.
        _gate = asyncio.Semaphore(_DEC_INDEX_POOL)
        _truncated = 0

        async def _ask(idx: int, text: str, depth: int) -> List[dict]:
            """One call. On a truncated reply, split in half and retry both
            halves rather than accepting the salvaged remainder."""
            nonlocal _truncated
            async with _gate:
                raw = await groq_chat(
                    LLM_MODEL,
                    [{"role": "system", "content": _DEC_INDEX_SYSTEM_PROMPT},
                     {"role": "user", "content": text}],
                    max_tokens=_DEC_INDEX_MAX_TOKENS,
                )
            # A complete JSON reply parses on its own. One that does not is
            # almost always severed at the output cap - and `_safe_json_parse`
            # would silently hand back only the completed portion, which is the
            # invisible data loss this retry exists to stop.
            _body = (raw or "").strip()
            if _body.startswith("```"):
                _body = re.sub(r"^```[a-z]*\n?", "", _body, flags=re.I).rstrip("`").strip()
            _s, _e = _body.find("{"), _body.rfind("}")
            _whole = None
            if _s != -1 and _e != -1:
                try:
                    _whole = json.loads(_body[_s:_e + 1])
                except (json.JSONDecodeError, ValueError):
                    _whole = None
            if _whole is None and depth < _DEC_INDEX_SPLIT_RETRIES and len(text) > 400:
                _truncated += 1
                _mid = text.rfind("\n", 0, len(text) // 2 + 1) + 1 or len(text) // 2
                logger.warning(
                    "dec_index_pass: chunk %d reply did not parse (truncated at the "
                    "%d-token cap) - splitting %d chars in two and retrying "
                    "(depth %d) instead of keeping a partial index",
                    idx, _DEC_INDEX_MAX_TOKENS, len(text), depth + 1,
                )
                _halves = await asyncio.gather(
                    _ask(idx, text[:_mid], depth + 1),
                    _ask(idx, text[_mid:], depth + 1),
                )
                return [e for h in _halves for e in h]
            if _whole is not None:
                parsed = _whole if ("facts" in _whole or "flags" in _whole) \
                    else {"facts": _whole, "flags": {}}
            else:
                # Out of retries: fall back to the deterministic salvage so a
                # stubborn piece still contributes what the model did write.
                parsed = await _safe_json_parse(raw, context=f"dec_index[{idx}]")
                # `_safe_json_parse` normalises a bare reply into
                # {"facts": {...}, "flags": {}} - which is exactly what this
                # prompt returns, since it deliberately does NOT ask for the
                # facts/flags wrapper. The first cut read the top level only
                # and discarded EIGHT successful calls on the first live run:
                # every one logged "bare dict ... wrapping into {facts: ...}"
                # and then "harvested 0 raw entries from 8 chunk(s)". The
                # output was there - up to 6,788 tokens of it - and this
                # function could not see it.
            out = None
            for level in (parsed, (parsed or {}).get("facts")):
                if isinstance(level, dict) and isinstance(
                        level.get("dec_page_entries"), list):
                    out = level["dec_page_entries"]
                    break
            if out is None:
                logger.warning(
                    "dec_index_pass: chunk %d returned no usable "
                    "dec_page_entries (top-level keys: %s)", idx,
                    sorted(parsed)[:6] if isinstance(parsed, dict) else type(parsed),
                )
            return out or []

        async def _one(idx: int, text: str) -> List[dict]:
            try:
                return await _ask(idx, text, 0)
            except Exception as ex:                        # noqa: BLE001
                logger.warning("dec_index_pass: chunk %d failed - %s", idx, ex)
                return []

        results = await asyncio.gather(*[_one(i, t) for i, t in pieces])
        entries = [e for r in results for e in r if isinstance(e, dict)]
        # LOUD ON ZERO. This pass is now the ONLY producer of the index (the
        # main extraction schema no longer asks for it), so "nothing harvested
        # from chunks that ARE declarations" is a broken run, not a quiet
        # nothing. It stayed silent for two full runs and cost days.
        if not entries:
            logger.error(
                "dec_index_pass: harvested ZERO entries from %d declarations-dense "
                "piece(s) - the declarations index will be EMPTY for this document. "
                "Check the per-chunk warnings above (429/timeout/parse).",
                len(pieces),
            )
        else:
            logger.info(
                "dec_index_pass: harvested %d raw entries from %d piece(s) across "
                "%d chunk(s)%s",
                len(entries), len(pieces), len(picked),
                f" ({_truncated} truncated reply/replies split and retried)"
                if _truncated else "",
            )
        return entries
    except Exception as ex:                                # noqa: BLE001
        logger.warning("dec_index_pass skipped: %s", ex)
        return []


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

    # ── The dedicated index pass, merged in ADDITIVELY ───────────────────────
    # Appended to whatever the main extraction recorded rather than replacing
    # it: `_verify_dec_entries` de-duplicates on (label, value, section) at
    # merge time, so an entry both passes found costs nothing, and one only the
    # main pass saw is never lost. Everything here still faces the verbatim
    # gate - this pass buys RECALL, not trust.
    try:
        _extra = await _harvest_dec_index(chunks)
        if _extra:
            # ── THE KEY PATH, and it was wrong from the day this pass shipped ──
            # `_merge_list_fields` returns {"facts": {...}, "flags": {...}} - the
            # entries live at result["facts"]["dec_page_entries"], NOT at the top
            # level. This block used to read and write `result["dec_page_entries"]`,
            # so `_base` was always None and every entry the dedicated pass
            # produced was filed one level too high, where nothing reads it:
            # `_validate_extraction_output` forwards it as an unrecognised extra
            # and `extraction_pipeline` stores only `extracted["facts"]`.
            #
            # It was invisible for as long as the MAIN extraction also recorded
            # dec entries - those went into facts correctly, the index looked
            # populated, and the dedicated pass's contribution silently
            # evaporated. Removing that key from the main schema (2026-08-23,
            # §3.1) took the last producer away and exposed it: three live runs
            # in a row logged successful index calls - `out=7921`, `out=14110`,
            # HTTP 200, no 429 - and still stored ZERO entries.
            #
            # Diagnosed the long way round: rate limiting was the leading theory
            # for two rounds and was wrong. The calls were never failing.
            _facts = result.get("facts")
            if not isinstance(_facts, dict):
                _facts = {}
                result["facts"] = _facts
            _base = _facts.get("dec_page_entries")
            _base = _base if isinstance(_base, list) else []
            _facts["dec_page_entries"] = _base + _extra
            logger.info(
                "dec_index_pass: %d entries from the main extraction + %d from "
                "the dedicated pass -> %d before verification",
                len(_base), len(_extra), len(_facts["dec_page_entries"]),
            )
    except Exception as _dx:                               # noqa: BLE001
        logger.warning("dec_index_pass merge skipped: %s", _dx)

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


# ── Declared-absent coverage lines ───────────────────────────────────────────
# A declarations page states what it does NOT cover as plainly as what it does:
# "PROPERTY - NO COVERAGE", "CRIME AND FIDELITY - NO COVERAGE". The coverage
# flags are keyword-presence booleans (has_crime is documented as "true if
# document mentions crime coverage ... fidelity bond"), and they OR across every
# chunk and document - so one such line sets the flag TRUE forever and the
# client gets Commercial Property, Crime and Cyber ticked on a policy that
# explicitly excludes all three.
#
# This is the only mechanism allowed to turn a coverage flag OFF, and it is
# deliberately hard to trigger:
#   * the line name and the denial must sit within _ABSENT_PROXIMITY characters
#     of each other with no sentence break, i.e. one row of a dec-page grid;
#   * the phrase must be an unambiguous denial. "excluded" and "none" are NOT in
#     the list: a Cyber Incident EXCLUSION inside a General Liability form does
#     not mean the GL line is absent, and "none" appears all over a dec page;
#   * a line named in `coverage_lines` is NEVER downgraded, whatever the prose
#     says - positive structured evidence always beats a text scan.
# SILENCE NEVER DOWNGRADES ANYTHING. Absence of a mention leaves the flag alone.
_ABSENT_PROXIMITY = 40

# ONE definition, owned by the line-of-business leaf. Re-bound here because
# `pdf_service` imports the name from this module and the Y-gate reasoning in
# that file refers to it by this name.
from services.lob_canon import COVERAGE_DENIAL_RE as _COVERAGE_DENIAL_RE

# flag -> the words a document uses to name that line. Kept to unambiguous line
# names; a word that also appears in unrelated prose is not eligible.
_FLAG_LINE_WORDS: Dict[str, Tuple[str, ...]] = {
    "has_property_coverage": ("commercial property", "property"),
    "has_crime":             ("crime and fidelity", "crime", "fidelity"),
    "has_cyber":             ("cyber and privacy", "cyber liability", "cyber"),
    "has_inland_marine":     ("inland marine",),
    "has_workers_comp":      ("workers compensation", "workers' compensation"),
    "has_umbrella":          ("umbrella",),
}


def _lines_declared_absent(text: str) -> set:
    """Flags whose coverage line the document explicitly declares NOT covered."""
    if not text:
        return set()
    lowered = text.lower()
    found: set = set()
    for match in _COVERAGE_DENIAL_RE.finditer(lowered):
        start = max(0, match.start() - _ABSENT_PROXIMITY)
        window = lowered[start:match.end()]
        # Cut the window back to its own row/sentence. A NEWLINE counts: a
        # declarations page is a grid and each denial belongs to exactly one
        # row. Without this the window reaches into the PREVIOUS row - measured
        # on the client's own dec page, "Umbrella $3,418" one line above
        # "Property - No Coverage" was enough to downgrade has_umbrella, the
        # precise opposite of what that page says.
        window = re.split(r"[.;\n\r]+", window)[-1]
        # Within one row, the NEAREST line name owns the denial. Splitting on
        # column whitespace instead was tried and is wrong in the other
        # direction: it discards the name in the very common two-column layout
        # "PROPERTY      NO COVERAGE". Nearest-wins handles both, and picking
        # exactly one flag per denial means a row can never silence two lines.
        nearest_flag, nearest_pos = None, -1
        for flag, words in _FLAG_LINE_WORDS.items():
            for w in words:
                pos = window.rfind(w)
                if pos > nearest_pos:
                    nearest_flag, nearest_pos = flag, pos
        if nearest_flag:
            found.add(nearest_flag)
    return found


# Keys on a `coverage_lines` entry that CORROBORATE the line beyond its own
# name. A declarations page that actually grants a line prints at least one of
# them next to it; a line the page DENIES has nothing but the name.
# Only a PREMIUM or a LIMIT is strong enough to override an explicit written
# denial. Measured on a real run (2026-08-09): the dec page says
# "PROPERTY - NO COVERAGE", and extraction still produced a `coverage_lines`
# entry named "Property" carrying the INLAND MARINE policy number - so a policy
# number alone vetoed the denial and Commercial Property stayed ticked, appeared
# in an "Other line of business" row, AND filled a Q4 row. One weak signal, three
# visible defects.
#
# A carrier, a NAIC code, a policy number or a date can all appear against a line
# a schedule merely REFERENCES. Money changing hands is what distinguishes a
# granted coverage from a mentioned one - and an explicit "NO COVERAGE" printed
# on the declarations page outranks every inference.
_LINE_EVIDENCE_KEYS: Tuple[str, ...] = ("premium", "limit")


def _line_entry_grants_coverage(entry: dict) -> bool:
    """True when a `coverage_lines` entry is positive evidence of a GRANT, not
    merely a mention of the line's name.

    Why this exists, measured on a real run (2026-08-09): the declared-absent
    downgrade was vetoed for `has_property_coverage` and the Commercial Property
    box stayed ticked on a package whose dec page reads "PROPERTY - NO
    COVERAGE". RULE 16 tells the model to leave a denied line OUT of
    `coverage_lines`; it does not always obey, and the veto trusted the bare
    name. So the arrival of `coverage_lines` DISABLED the fix for exactly the
    line the client reported - a mention was being read as a grant, which is the
    project's oldest root cause (see fix-form-stamping.md, GRANT qualifier)
    reappearing one layer up.

    Two ways an entry fails to be evidence:
      * it carries no corroborating detail at all - just a line name;
      * a corroborating value is ITSELF a coverage denial. The client's own run
        stamped the literal string "No Coverage" into the Property and Crime
        premium boxes, so this is observed behaviour, not a hypothetical.
    """
    if not isinstance(entry, dict):
        return False
    for key in _LINE_EVIDENCE_KEYS:
        val = entry.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if not text or text.lower() in _NULL_STRINGS:
            continue
        if _COVERAGE_DENIAL_RE.search(text):
            return False                    # the detail denies the line outright
        return True
    return False


def _line_entry_denies_coverage(entry: dict) -> bool:
    """True when a `coverage_lines` entry EXPLICITLY says the line is not covered.

    THE TWIN OF `_line_entry_grants_coverage`, AND NOT ITS NEGATION. That
    distinction is the whole reason this function exists (V1 plan C1-K):

        grants  -> "premium or limit present"      = positive proof of coverage
        denies  -> "a detail literally says NO"    = positive proof of absence
        neither -> the document is SILENT

    A certificate of insurance never prints premiums, so most COI rows are
    `grants=False`. Reading that as a DENIAL is Principle 3's forbidden move -
    absence of evidence turned into evidence - and it manufactured a false
    "lines of business differ" warning on the 2026-08-21 live package, inside
    the very fix meant to enforce Principle 3.

    Only ever returns True on an explicit denial phrase, so silence can never
    become a denial.
    """
    from services.lob_canon import denies_coverage
    return denies_coverage(entry)


def _line_name_is_a_carrier(name: str) -> bool:
    """True when a `coverage_lines` name is really a CARRIER name.

    "EMC Property & Casualty Company" contains the token "property" and would
    otherwise veto `has_property_coverage` forever. Uses the shared carrier
    shape heuristic rather than a second local copy; never raises, because a
    detector fault must not change extraction behaviour.
    """
    try:
        from services.field_mapping_integrity import looks_like_carrier
        return bool(looks_like_carrier(name))
    except Exception:                       # noqa: BLE001 - advisory only
        return False


def apply_declared_absent_downgrades(
    flags: dict, facts: dict, text: str,
) -> List[str]:
    """Turn OFF coverage flags the document explicitly denies. Returns the flags
    changed, for logging. Never turns a flag ON.

    A flag is vetoed only by a `coverage_lines` entry that actually GRANTS the
    line (see `_line_entry_grants_coverage`) - a bare name is a mention, and a
    mention has never been proof of coverage anywhere else in this pipeline.
    """
    covered_words: set = set()
    lines = facts.get("coverage_lines")
    if isinstance(lines, list):
        for entry in lines:
            if not isinstance(entry, dict) or not entry.get("line"):
                continue
            name = str(entry["line"]).strip()
            if not _line_entry_grants_coverage(entry):
                continue
            if _line_name_is_a_carrier(name):
                continue
            covered_words.add(name.lower())

    changed: List[str] = []
    for flag in _lines_declared_absent(text):
        if not flags.get(flag):
            continue                        # already false - nothing to do
        words = _FLAG_LINE_WORDS[flag]
        if any(w in cl for cl in covered_words for w in words):
            continue                        # positive evidence vetoes the scan
        flags[flag] = False
        changed.append(flag)
    return changed


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
        # V1 plan C1 F5 / defect B8 (Principle 3): a boolean False from
        # extraction cannot be told apart from "this document never mentioned
        # it" - nothing in the prompt distinguishes the two. Comparing
        # True-vs-False across documents therefore manufactured a conflict
        # (and an 85 cap) from SILENCE. Booleans are value-state NOT_STATED
        # unless a human supplied them, and NOT_STATED never enters a
        # comparison, so they are excluded here outright.
        if any(isinstance(_fv(d.get("facts", {}), field), bool) for d in docs):
            continue
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
    # A state is a real 2-letter postal code and a ZIP is 5 digits - anything
    # else in those boxes is a mis-parse, not data. Derived from the SAME
    # name->abbreviation table normalize_address already uses, so "Colorado"
    # in a state box converts to "CO" instead of being wiped.
    from services.normalization import _US_STATE_NAME_PHRASES
    _state_codes = {ab.upper() for _p, ab in _US_STATE_NAME_PHRASES}
    _name_to_code = {p.lower(): ab.upper() for p, ab in _US_STATE_NAME_PHRASES}

    def _coerce_state(value: Any) -> Optional[str]:
        s = str(value or "").strip().rstrip(".")
        if not s:
            return None
        if s.upper() in _state_codes:
            return s.upper()
        return _name_to_code.get(s.lower())

    for entry in entries:
        addr = str(entry.get("address") or "").strip()
        if not addr:
            continue
        parsed = _parse_address(addr)
        entry.setdefault("address_line1", parsed.get("line1"))
        entry.setdefault("address_line2", parsed.get("line2"))
        entry.setdefault("address_city",  parsed.get("city"))
        entry.setdefault("address_state", parsed.get("state"))
        entry.setdefault("address_zip",   parsed.get("zip"))
        # County comes only from the document (extraction's per-location
        # "county" key) - _parse_address cannot derive one.
        entry.setdefault("address_county", entry.get("county"))

        # ── Shape validation (52-page trap run, 2026-08-12) ──────────────────
        # "VARIOUS JOB SITES, STATE OF COLORADO" decomposed to city="State",
        # state="of", zip="Colorado" and PRINTED that way on the form. Rules:
        # a state either is/converts to a postal code or it is None; a ZIP
        # either matches \d{5}(-\d{4})? or it is None; and when the "ZIP" was
        # actually a STATE NAME the whole city/state/zip split is one shifted
        # mis-parse, so all three are cleared and the full text stays in the
        # street line - a street-only row beats three boxes of garbage.
        _st_raw, _zp_raw = entry.get("address_state"), entry.get("address_zip")
        if _st_raw:
            entry["address_state"] = _coerce_state(_st_raw)
        if _zp_raw and not re.match(r"^\d{5}(-\d{4})?$", str(_zp_raw).strip()):
            if _coerce_state(_zp_raw):
                entry["address_city"] = None
                entry["address_state"] = None
            entry["address_zip"] = None

    # ── Entries that are not locations at all ────────────────────────────────
    # Two shapes observed on a live run (client form, premises section):
    #
    #   1. A bare UNIT fragment ("# D13", "Ste 400") captured as its own
    #      "location". Its line1 is only a unit designator and it carries no
    #      city/state/zip of its own, so it can never be a distinct premises -
    #      it is a piece of some full address mentioned elsewhere. Stamping it
    #      produced a phantom "LOC # 2" row whose street was the producer's
    #      suite number.
    #   2. The PRODUCER'S OWN ADDRESS swept into the insured's location list.
    #      The premises schedule describes the INSURED's premises; the agency's
    #      street belongs to the Producer block and nowhere else (same entity
    #      discipline as extraction RULE 15).
    #
    # Both filters only ever REMOVE a non-location; a genuine location always
    # has a real street line or its own city/state/zip and never equals the
    # producer's address line.
    _unit_only_re = re.compile(
        r"^\s*(?:#|apt\.?|suite|ste\.?|unit|bldg\.?|building|fl\.?|floor|rm\.?|room)"
        r"\s*[\w-]*\s*$",
        re.I,
    )
    _producer_line1_key = ""
    _producer_addr = _fv(facts, "producer_address")
    if _producer_addr:
        _p_line1 = _parse_address(str(_producer_addr)).get("line1") or ""
        _producer_line1_key = normalize_address(_p_line1) if _p_line1 else ""

    # STREET-NUMBER + ZIP identity for the producer/carrier, alongside the
    # line1-equality check above. 52-page trap run (2026-08-12): the packet's
    # own location schedule lists the producer's office as "Loc 004" with the
    # explicit note "this is not a location of the named insured" - and it
    # stamped as premises #4 anyway, because the entry's line1 carried the
    # suite INSIDE it ("9780 S Meridian Blvd Ste 400") while the producer fact
    # parsed the suite onto line2, so normalized-line1 equality never matched.
    # (street number, ZIP5) is immune to where the suite lands - the same
    # comparator _drop_transaction_party_rows already trusts.
    _blocked_party_ids = set()
    for _party_key in ("producer_address", "carrier_address"):
        _pv = _fv(facts, _party_key)
        _pid = _address_identity_key(str(_pv)) if _pv else None
        if _pid:
            _blocked_party_ids.add(_pid)

    # Sub-fields that make an address-less entry worth keeping as its own row —
    # real per-location data a document can state without repeating the street.
    _substantive_keys = (
        "ownership", "building_value", "bpp_value", "annual_revenue",
        "full_time_employees", "part_time_employees", "occupied_area",
        "open_to_public_area", "total_building_area", "operations_description",
        "construction_type", "year_built", "inside_city_limits",
    )

    def _is_location_entry(entry: dict) -> bool:
        line1 = str(entry.get("address_line1") or "").strip()
        has_own_geo = any(
            str(entry.get(k) or "").strip()
            for k in ("address_city", "address_state", "address_zip")
        )
        if line1 and _unit_only_re.match(line1) and not has_own_geo:
            return False                    # bare unit fragment, not a premises
        if _producer_line1_key and line1 and normalize_address(line1) == _producer_line1_key:
            return False                    # the agency's address, not the insured's
        if _blocked_party_ids and _address_identity_key(entry) in _blocked_party_ids:
            return False                    # producer/carrier office by street#+ZIP
        if not line1 and not has_own_geo:
            # No address signal at all. Keep it only when it carries real
            # per-location data; otherwise it becomes a phantom row whose only
            # stamped cell is its own LOC # (observed live: an empty "LOC # 2"
            # premises row on the client's form).
            has_data = any(
                entry.get(k) not in (None, "", [])
                for k in _substantive_keys
            )
            if not has_data:
                return False
        return True

    _dropped = [e for e in entries if not _is_location_entry(e)]
    if _dropped:
        logger.info(
            "consolidate_locations: dropped %d non-location entr%s: %s",
            len(_dropped), "y" if len(_dropped) == 1 else "ies",
            [str(e.get("address") or "")[:40] for e in _dropped[:4]],
        )
        entries = [e for e in entries if _is_location_entry(e)]
        if not entries:
            return

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

    # ── Fold parse-variant groups describing ONE premises ────────────────────
    # Live run 2026-08-12: the client's single location printed as THREE
    # premises rows on ACORD 125. `_parse_address` splits on commas, and the
    # document mentions the address comma-free in three shapes, so each kept
    # its whole string as line1 and produced a DIFFERENT group key:
    #
    #     "4800 dahlia st d13 denver"                    <- street + city leaked
    #     "4800 dahlia st d13 denver co 80216"           <- everything in line1
    #     "denver co 80216"                              <- geo fragment, no street
    #
    # Two structural rules fold them, both requiring positive evidence:
    #   1. PREFIX: one key extends the other and both start with the SAME street
    #      number - the longer is the same premises with its city/state/zip tail
    #      leaked into line1. Two different suites diverge before the tail
    #      ("...st d13 denver" vs "...st b5 denver") so they never fold.
    #   2. FRAGMENT: a key with NO street number whose every token appears in
    #      exactly ONE street-numbered group is a geo fragment of that group. It
    #      carries zero distinguishing information by construction; if TWO
    #      groups could contain it, it stays its own row (no guessing).
    # Sub-fields merge with the same setdefault semantics as above, so a fold
    # only ever FILLS gaps (the fragment's zip completes the street group).
    def _street_num(k: str) -> str:
        m = re.match(r"(\d{1,8})\b", k)
        return m.group(1) if m else ""

    # "City ST 80216-3121" and nothing else - the exact shape of a geo fragment.
    _geo_only_re = re.compile(
        r"^\s*([A-Za-z][A-Za-z .'-]*?)[\s,]+([A-Za-z]{2})\.?[\s,]+(\d{5}(?:-\d{4})?)\s*$"
    )
    # "City, State" with NO zip - a 2-letter code or a full state name.
    _geo_city_state_re = re.compile(
        r"^\s*([A-Za-z][A-Za-z .'-]*?)[\s,]+([A-Za-z]{2}|[A-Za-z]+(?: [A-Za-z]+)?)\.?\s*$"
    )
    # A comma-free mention's city/state/zip tail, leaked into line1 by
    # _parse_address (which only splits on commas).
    _state_zip_tail_re = re.compile(r"[\s,]+([A-Za-z]{2})\.?[\s,]+(\d{5}(?:-\d{4})?)\s*$")

    # Can group key `a` host (absorb) key `b`? Two shapes, mirroring C48:
    # a street-numbered b folds by same-number prefix/compact identity; a
    # numberless b is a geo fragment folding by token subset. COMPACT
    # comparison rides alongside the token one: OCR splits unit designators
    # unpredictably ("D13" on one page, "D 13" on the next), which breaks
    # token-level prefixing while the two keys are byte-identical once spaces
    # are removed. Two real suites ("d13" vs "b5") still differ compacted.
    def _street_claims(a_key: str, b_key: str) -> bool:
        a_num, b_num = _street_num(a_key), _street_num(b_key)
        if b_num:
            if not a_num or a_num != b_num:
                return False
            a_c, b_c = a_key.replace(" ", ""), b_key.replace(" ", "")
            return (b_key.startswith(a_key + " ") or a_key.startswith(b_key + " ")
                    or a_c == b_c or b_c.startswith(a_c) or a_c.startswith(b_c))
        # A geo fragment ("Denver, Colorado") folds into the ONE street group
        # whose FULL address contains it. V1 plan C1 F9 (defect B7): the old
        # rule compared the fragment's line1-only key ("denver") against the
        # host's line1-only key ("4800 dahlia st d13") - neither side carried
        # the city - so the client's literal third string became a second
        # premises row on ACORD 125. Both sides now use the same normaliser
        # the picker uses, over the whole address string.
        b_full = normalize_address(str(groups.get(b_key, {}).get("address") or b_key))
        a_full = normalize_address(str(groups.get(a_key, {}).get("address") or a_key))
        b_toks = set(b_full.split()) or set(b_key.split())
        a_toks = set(a_full.split()) | set(a_key.split())
        return bool(a_num and b_toks and b_toks <= a_toks)

    def _same_premises(x: str, y: str) -> bool:
        return _street_claims(x, y) or _street_claims(y, x)

    folded = True
    while folded and len(order) > 1:
        folded = False
        for b_key in list(order):
            hosts = [a for a in order if a != b_key and _street_claims(a, b_key)]
            if not hosts:
                continue
            if len(hosts) > 1:
                # THE THREE-VARIANT DEADLOCK (live 2026-08-14): one premises
                # printed in 3+ shapes ('...st d13' / '...st d13 denver' /
                # '...st d13 denver co 80216') makes EVERY key see the other
                # two as hosts, the old exactly-one rule skipped all of them,
                # zero folds happened, and three rows stamped. Multiple hosts
                # fold only when they are all the SAME premises as each other
                # (pairwise related); 'd13 denver' vs 'd13 boulder' fails and
                # b stays put.
                if not all(_same_premises(h1, h2)
                           for _i, h1 in enumerate(hosts) for h2 in hosts[_i + 1:]):
                    continue
                hosts = [max(hosts, key=len)]
            a_key = hosts[0]
            # REVERSE ambiguity, the hole the deadlock fix exposed: when the
            # HOST is the more-specific shape ('...d13 denver' finding bare
            # '...d13'), a third group ('...d13 boulder') may claim the bare
            # shape just as well - folding would guess which premises owns the
            # fragment. A third claimant only excuses itself by being the same
            # premises as the LONGER member of the pair (a chain, which folds
            # on its own turn anyway).
            shorter, longer = sorted((a_key, b_key), key=len)
            if any(k not in (a_key, b_key) and _street_claims(k, shorter)
                   and not _same_premises(k, longer) for k in order):
                continue
            first = a_key if order.index(a_key) < order.index(b_key) else b_key
            second = b_key if first == a_key else a_key
            # The TOKEN-SUPERSET key becomes the group's key (at the earlier
            # position) so a later fragment can still find its tokens in it -
            # keeping the short key here left "denver co 80216" unable to fold.
            canonical = a_key if len(a_key) >= len(b_key) else b_key
            merged: dict = {}
            for src in (groups[first], groups[second]):
                for k, v in src.items():
                    if v is None or (isinstance(v, str) and not v.strip()):
                        continue
                    merged.setdefault(k, v)
            merged["address"] = max(
                (str(groups[first].get("address") or ""),
                 str(groups[second].get("address") or "")), key=len)
            # A geo-only member IS the city/state/zip, stated plainly - capture
            # it now, before its short string is buried under the longer display.
            for src in (groups[first], groups[second]):
                gm = _geo_only_re.match(str(src.get("address") or ""))
                if gm:
                    merged.setdefault("address_city", gm.group(1).strip())
                    merged.setdefault("address_state", gm.group(2).upper())
                    merged.setdefault("address_zip", gm.group(3))
                    continue
                # "Denver, Colorado" / "Denver, CO" - city + state, no ZIP (F9).
                gm2 = _geo_city_state_re.match(str(src.get("address") or ""))
                if gm2 and _street_num(normalize_address(str(src.get("address") or ""))) == "":
                    st = _coerce_state(gm2.group(2))
                    if st:
                        merged.setdefault("address_city", gm2.group(1).strip())
                        merged.setdefault("address_state", st)
            logger.info(
                "consolidate_locations: folded parse-variant group %r into %r "
                "- one premises mentioned in different shapes, not two premises",
                second[:50], first[:50],
            )
            order = [canonical if k == first else k for k in order if k != second]
            del groups[first], groups[second]
            groups[canonical] = merged
            folded = True
            break

    # ── Recover city/state/zip a comma-free mention left inside line1 ────────
    # Runs for every group (folded or not). Only ever fills EMPTY sub-fields
    # from unambiguous shapes, then strips those now-known values off the tail
    # of the street line so "4800 Dahlia St # D13 Denver" prints as a street
    # and "Denver" prints in the CITY box - not both in one.
    for key in order:
        obj = groups[key]
        if not str(obj.get("address_zip") or "").strip():
            tm = (_state_zip_tail_re.search(str(obj.get("address") or ""))
                  or _state_zip_tail_re.search(str(obj.get("address_line1") or "")))
            if tm:
                obj.setdefault("address_state", None)
                if not str(obj.get("address_state") or "").strip():
                    obj["address_state"] = tm.group(1).upper()
                obj["address_zip"] = tm.group(2)
        line1 = str(obj.get("address_line1") or "")
        if line1:
            city  = str(obj.get("address_city") or "").strip()
            state = str(obj.get("address_state") or "").strip()
            zip_v = str(obj.get("address_zip") or "").strip()
            tails = []
            if zip_v:
                tails.append(re.compile(
                    r"[\s,]+" + re.escape(zip_v.split("-")[0]) + r"(?:-\d{4})?\s*$"))
            if state:
                tails.append(re.compile(
                    r"[\s,]+" + re.escape(state) + r"\.?\s*$", re.I))
            if city:
                tails.append(re.compile(
                    r"[\s,]+" + re.escape(city) + r"\s*$", re.I))
            for _ in range(4):                     # zip, state, city - at most
                stripped = line1                   # one pass each, repeated in
                for t in tails:                    # case of "city state zip"
                    stripped = t.sub("", stripped)
                if stripped == line1:
                    break
                line1 = stripped
            if line1.strip():
                obj["address_line1"] = line1.strip()

    consolidated: List[dict] = []
    for i, key in enumerate(order):
        obj = groups[key]
        obj["location_id"] = f"L{i + 1}"
        # Plain numeric companion to location_id - ACORD's own "LOC #" box
        # (CommercialStructure_Location_ProducerIdentifier_{row}) expects a
        # bare number ("1", "2", ...), not the "L1" internal id format.
        obj["location_number"] = str(i + 1)
        obj.setdefault("address_line1", obj.get("address"))
        obj.setdefault("address_line2", None)
        obj.setdefault("address_city", None)
        obj.setdefault("address_state", None)
        obj.setdefault("address_zip", None)
        obj.setdefault("address_county", None)

        # Owner / Tenant / Other are mutually exclusive on the real ACORD
        # form. Deriving ALL THREE deterministically (not just owner/tenant)
        # matters: an ungated "Other" checkbox left open for GPT gap-fill
        # will independently re-guess an interest for a row already resolved
        # here, producing a contradictory PDF (e.g. Tenant=Yes AND Other=Yes
        # with a redundant description on the same row).
        ownership = str(obj.get("ownership") or "").strip()
        ownership_l = ownership.lower()
        # A sentence naming SEVERAL interests is not a determination of one.
        # Live 25-page run: the dec says "This location is owned, rented or
        # occupied by the named insured" - deliberately non-committal - and
        # that whole phrase was written into the ACORD "Other" interest box
        # with the sentence as its description. Owner, tenant and other are
        # mutually exclusive; a phrase that lists two of them tells us the
        # document did not say which, so all three stay unknown and the
        # question goes to the client.
        # The tell is the document offering ALTERNATIVES ("owned, rented OR
        # occupied"), not the length of the phrase: "Tenant (leased office
        # space)" and "Licensee under a shared-use agreement" are single,
        # determinate answers and must still resolve.
        _interest_words = len({
            w for w in ("own", "rent", "occup", "tenant", "lease", "licens")
            if w in ownership_l
        })
        if _interest_words > 1 and re.search(r"\bor\b", ownership_l):
            logger.info(
                "consolidate_locations: ambiguous ownership %r - left unknown",
                ownership[:60],
            )
            ownership_l = ""
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


# ── Dec-page entries: verify mechanically, consume deterministically ─────────
# The recording half lives in the extraction schema ("dec_page_entries"). These
# two functions are the ONLY consumers, and neither involves an LLM:
#
#   _verify_dec_entries       - literal-presence check against the uploaded
#                               text. An entry the document does not actually
#                               print is DISCARDED before anything can read it.
#   _backfill_empty_facts_... - fills a registry fact that merged EMPTY from a
#                               verified entry, under five stacked conditions
#                               (typed validator, all-token label match, owner
#                               compatibility, single distinct value, fact
#                               genuinely empty). Misses are fine; a wrong box
#                               is not - every condition fails toward blank.
#
# SINCE 2026-08-13 there is a THIRD consumer, and it is an LLM one: the entries
# are rendered as the dec-page INDEX that gap fill reads before the raw document
# (pdf_service._render_dec_index, CALL2_RETRIEVAL_REDESIGN D11). The old comment
# here said call 2 stays byte-identical; that constraint was lifted deliberately
# by the owner. What has NOT changed is the verification contract below - an
# entry that is not literally printed in the document never reaches any consumer,
# LLM or otherwise, so the index cannot introduce a value the document lacks.
#
# STILL DELIBERATELY NOT DONE: open-vocabulary matching of entry labels onto the
# 5,852 ACORD field names (a hand-rolled NLU layer - the exact heuristic class
# this codebase has repeatedly burned on). The model does that matching, from an
# index that is small enough for it to read carefully.
#
# CAP SIZING (raised 2026-08-13, and these are the numbers, not a guess). The
# real ORBIN package prints 30 declarations/schedule pages inside 271. At the
# ~25 label:value pairs a dec page carries that is ~750 entries, so the old
# global 500 was throwing away a third of the index it now feeds, and the old
# per-chunk 80 x 13 chunks capped the candidates before dedup. 1200 holds that
# package with headroom and renders to ~2 index chunks, against 13 raw ones.
# ── A RUNAWAY GUARD, NOT A DATA CEILING (raised 1,200 -> 50,000, 2026-08-23) ─
# 1,200 was sized for the old 6-key shape where one printed row became one
# entry. The atomic schema splits that same row into one entry PER CELL - a
# seven-column rating row is seven entries - so the old ceiling truncated a
# large package's declarations data long before any token cap fired, and the
# drop was a log line nobody reads. Declarations data is exactly what must not
# be dropped: we cannot know which value a form will ask for.
#
# WHY IT COULD BE RAISED. It could not, until `_dec_index_chunks` was taught to
# split BY LABEL. Before that a big index was cut blindly through the rendered
# text, which separated the umbrella's $3,000,000 from the GL's $1,000,000 and
# re-created C23 - so a low ceiling was the lesser evil. Now a label can never
# straddle two Stage A calls however large the index grows, so the ceiling is
# free to stop being a ceiling. 3,000 was an intermediate step for exactly one
# commit and is recorded here so nobody reinstates it as a considered value.
#
# WHY IT IS NOT REMOVED. Entries land in the session row in Postgres. An
# unbounded list lets a looping or adversarial reply write unbounded data. At
# 50,000 it cannot fire on any real document - roughly forty times the largest
# package measured - so if it EVER fires that is a signal to chase, and the
# warning it logs says so.
_DEC_ENTRY_MAX = int(os.getenv("DEC_ENTRY_MAX", "50000"))
_DEC_ENTRY_VALUE_MAX_CHARS = 300
_DEC_ENTRY_LABEL_MAX_CHARS = 120
_DEC_ENTRY_SECTION_MAX_CHARS = 80
_DEC_ENTRY_OWNERS = frozenset({"applicant", "producer", "carrier", "policy", "other"})
# The index prompt's two other CLOSED vocabularies. Anything outside them is
# dropped rather than stored, so a model inventing a member cannot put an
# unknown token into the session row - the same discipline `owner` has always
# had. Both keys are additive and nothing reads them yet.
_DEC_ENTRY_KINDS = frozenset({"kv", "standalone", "heading", "statement",
                              "footer", "index"})
def _dec_norm(text: Any) -> str:
    """Case/punctuation-insensitive form - mirrors text_selection._norm and
    pdf_service._normalize_for_search so 'verbatim' means the same thing in
    every layer that checks it."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


_SECTION_TOKEN_GAP = 80


def _tokens_printed_in_order(tokens: List[str], hay: str) -> bool:
    """Every token, in printed order, each within `_SECTION_TOKEN_GAP` chars of
    its predecessor. The one shared engine behind `_section_is_printed` and
    `_entry_is_printed` - a single definition of "printed, allowing for how
    print survives OCR", not two that drift. Fewer than two tokens is no
    evidence of anything and always fails; callers fall back to strict."""
    if len(tokens) < 2:
        return False
    pattern = (r"\b" + rf"\b.{{0,{_SECTION_TOKEN_GAP}}}?\b".join(
        re.escape(t) for t in tokens) + r"\b")
    try:
        return re.search(pattern, hay, re.S) is not None
    except re.error:                                       # pragma: no cover
        return False


def _section_is_printed(n_section: str, hay: str) -> bool:
    """Is this page heading actually printed, allowing for how headings print?

    RELAXED 2026-08-13, from a plain substring test, on measured evidence. The
    first live run with `section` logged **45 SECTION_DROPPED lines** and every
    one of them was a coverage part this package demonstrably contains:
    `COMMERCIAL UMBRELLA DECLARATIONS`, `COMMERCIAL UMBRELLA SCHEDULE`,
    `COMMERCIAL INLAND MARINE DECLARATIONS`. Both the plain and the `POLICY`
    variant of the umbrella heading failed, so this is not the model guessing a
    name - the heading does not survive OCR as one contiguous run. A dec page
    heading is large centred type, routinely broken by a logo, a page number or a
    column boundary landing between its words.

    The cost of that was precise: `section` is the C23 discriminator - the only
    thing that tells the umbrella's $3,000,000 from the GL's $1,000,000 under the
    identical label "Each Occurrence Limit" - and it was being discarded for
    exactly the pages that need it.

    So the test is now ORDERED CONTAINMENT: every significant word of the heading
    must appear, in the printed order, within `_SECTION_TOKEN_GAP` characters of
    its predecessor. That accepts a heading split by page furniture and still
    rejects an invented one, because a heading the document never printed will
    not have its words sitting in sequence anywhere.

    It IS a relaxation and the risk is named rather than dressed up: a heading
    could now be accepted from words that coincidentally line up in body text.
    The consequence is bounded - a mis-grouped line in the index, never a stamped
    value, since `label` and `value` face their own gate (`_entry_is_printed`,
    which is stricter about numbers than this is about words). Single-word
    headings keep the strict test: one word in sequence is no evidence of
    anything.
    """
    if n_section in hay:
        return True
    return _tokens_printed_in_order(
        [t for t in n_section.split() if len(t) > 2], hay)


def _entry_is_printed(n_text: str, hay: str) -> bool:
    """Is this label/value printed - verbatim, or the way OCR prints a TABLE?

    EXTENDED 2026-08-14 from a plain substring test, on the same class of
    measured evidence that relaxed `_section_is_printed` the day before. The
    live ORBIN runs logged DROPPED_UNVERIFIED for the entire GL class table
    (label 'Location 001', value '91580 Contractors - Executive Supervisors or
    Executive Superintendents') and for every 'Section N <part>' = 'No
    Coverage' summary line. None of those are fabrications: the model joined
    two printed CELLS of one row, and OCR interleaves the neighbouring columns
    (premium basis, exposure, a second section's column) between them, so the
    joined string is not contiguous anywhere in the text. Dropping them cost
    the index exactly the table content Stage A exists to serve - generically,
    on any package with a rating schedule, not just this one.

    The relaxation is the SAME ordered containment the section check uses,
    with two extra rules it does not need, both protecting the one class of
    value where a false accept is cheapest to manufacture - numbers:

      - digit tokens are always significant, whatever their length: the class
        code / location number is the anchor of its row and must be present.
      - a text whose significant tokens are ALL digits never takes the relaxed
        path. '1,000,000' rewritten as '1000000', a date rewritten from
        07/16/25 to 07/16/2025, a re-grouped phone number: scattered digit
        groups sitting in order prove nothing, and a NUMBER that fails the
        verbatim test is precisely the fabrication this gate exists to stop.
        Reformatting is the model disobeying rule 1; the entry stays dropped.

    Single-significant-token texts stay strict for the same reason single-word
    sections do. The named risk: a multi-word text assembled from real words
    that coincidentally sit in reading order within one row's width. The
    consequence is an odd line in the index - every downstream consumer still
    guards itself (backfill's five stacked conditions, the post-fill guards on
    anything the Stage A model stamps).
    """
    if n_text in hay:
        return True
    significant = [t for t in n_text.split() if len(t) > 2 or t.isdigit()]
    if not significant or all(t.isdigit() for t in significant):
        return False
    return _tokens_printed_in_order(significant, hay)


def _verify_dec_entries(entries: Any, full_text: str) -> List[dict]:
    """The verified subset of `entries`: label AND value literally present.

    No text to check against means nothing can be verified, and unverifiable
    entries are dropped - blank over wrong, same as everywhere else.
    """
    if not isinstance(entries, list) or not entries or not (full_text or "").strip():
        return []
    hay = _dec_norm(full_text)
    kept: List[dict] = []
    seen: set = set()
    dropped_unverified = dropped_malformed = 0
    for pos, item in enumerate(entries):
        if len(kept) >= _DEC_ENTRY_MAX:
            # Truncation must never be silent: everything past this point is
            # dec-page data the index will simply not have, and "the index is
            # thin" has already cost days of tracing once. Raise DEC_ENTRY_MAX
            # (and GAP_FILL_DEC_INDEX_BUDGET_MULT with it - see
            # pdf_service._dec_index_chunks) if this fires on a real package.
            logger.warning(
                "dec_entries CAP: reached DEC_ENTRY_MAX=%d with %d candidate "
                "entr(ies) still unprocessed - the index is TRUNCATED",
                _DEC_ENTRY_MAX, len(entries) - pos,
            )
            break
        if not isinstance(item, dict):
            dropped_malformed += 1
            continue
        label = str(item.get("label") or "").strip()[:_DEC_ENTRY_LABEL_MAX_CHARS]
        value = str(item.get("value") or "").strip()
        if not label or not value or len(value) > _DEC_ENTRY_VALUE_MAX_CHARS:
            dropped_malformed += 1
            continue
        n_label, n_value = _dec_norm(label), _dec_norm(value)
        if not n_label or not n_value:
            dropped_malformed += 1
            continue
        # PRINTED or gone. The model was instructed to copy both halves as
        # printed; an entry the document does not print is exactly the
        # fabrication this gate exists to stop. "Printed" means verbatim, OR
        # in printed order across one table row's width (`_entry_is_printed`) -
        # numbers get no such latitude, see that function for why.
        if not _entry_is_printed(n_value, hay) or not _entry_is_printed(n_label, hay):
            dropped_unverified += 1
            logger.info(
                "dec_entries DROPPED_UNVERIFIED label=%r value=%r - not "
                "printed in the uploaded text", label[:60], value[:60],
            )
            continue
        owner = str(item.get("owner") or "").strip().lower()
        # `section` is the coverage-part heading, and it gets the SAME verbatim
        # treatment as label and value - it is the discriminator that tells the
        # umbrella's $3,000,000 from the GL's $1,000,000 (improving-ll.md C23),
        # so a fabricated one would be worse than none at all. Unverifiable
        # section, no section: the entry survives, it just loses its attribution.
        section = str(item.get("section") or "").strip()[:_DEC_ENTRY_SECTION_MAX_CHARS]
        n_section = _dec_norm(section)
        if not n_section or not _section_is_printed(n_section, hay):
            if section:
                logger.info("dec_entries SECTION_DROPPED %r - not printed in the "
                            "uploaded text", section[:60])
            section, n_section = "", ""
        kept_item = {
            "label": label,
            "value": value,
            "section": section or None,
            "owner": owner if owner in _DEC_ENTRY_OWNERS else "other",
            "policy_number": (str(item.get("policy_number")).strip()
                              if item.get("policy_number") else None),
            "line_of_business": (str(item.get("line_of_business")).strip()
                                 if item.get("line_of_business") else None),
        }
        # Section is part of the identity. Dropping it from the key would collapse
        # the SAME label:value printed under two headings into one entry and keep
        # whichever heading happened to arrive first - inventing an attribution.
        dedup_key = (n_label, n_value, n_section)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        kept.append(kept_item)
    if kept or dropped_unverified or dropped_malformed:
        logger.info(
            "dec_entries VERIFIED kept=%d dropped_unverified=%d dropped_malformed=%d",
            len(kept), dropped_unverified, dropped_malformed,
        )
    return kept


# ── The join keys are canonicalised in CODE, not by the prompt (2026-08-16) ───
# `policy_number` and `line_of_business` are what every downstream consumer
# JOINS on - the ACORD 131 underlying grid, the 125 prior-carrier grid, the Q4
# grid, the section-form header identity. When one contract carries two keys,
# each of those sees half its evidence, and the surfaces starve one fact at a
# time (which is the shape of every "why is this box blank" report in
# FIX_TRACKING_2026-08-15.md).
#
# ASKING THE MODEL FOR THIS WAS TRIED AND MEASURED AND FAILED. Prompt rules 8
# and 9 instructed exactly this; on a re-run of the same package the model
# invented a THIRD umbrella spelling ('6J74002---26') and produced MORE
# off-vocabulary line names, not fewer. Identity arithmetic is deterministic
# work; it belongs here, where it can be proven and tested.
#
# THE FUNCTION NEVER INVENTS. It only elects one printing from the printings the
# verified entries already carry, and it only rewrites the KEY - `value` stays
# verbatim, so the evidence and the `_verify_dec_entries` literal-presence
# guarantee are both untouched. Two numbers merge only when one is a prefix of
# the other after stripping punctuation and OCR spacing, which is how a single
# contract is printed several ways ('6E7-40-02---26' / '6E74002',
# 'BBC7263 - 26' / 'BBC7263', '6 C 7 - 4 0 - 0 2---26'). Two genuinely different
# numbers share no such prefix and are left alone.
_DEC_LINE_DISPLAY: Dict[str, str] = {
    "general_liab":   "General Liability",
    "auto":           "Commercial Auto",
    "umbrella":       "Commercial Umbrella",
    "inland_marine":  "Inland Marine",
    "workers_comp":   "Workers Compensation",
    "property":       "Property",
    "crime":          "Crime",
    "cyber":          "Cyber",
}


# Two letters + exactly four 2-digit groups (spaced or contiguous): the ISO
# form-number-with-edition shape ("CG 99 09 12 19", "CG00011213"). See the
# clearing loop in _canonicalise_dec_entry_keys for why this can never be a
# contract key and why real policy numbers cannot match it.
_ISO_FORM_NUMBER_KEY_RE = re.compile(r"^[A-Za-z]{2}(\s?\d{2}){4}$")


def _entry_self_attributes_its_own_identifier(entry: Any) -> bool:
    """The entry's `policy_number` IS its own `value`, and its own label does
    not claim that value is a policy number.

    THE SHAPE THIS CATCHES, from run 47556cd2: the common declarations page
    prints `Account Number: 0482854`, and the model - asked which contract the
    entry belongs to, on the one page that belongs to ALL of them - reached for
    the only identifier in front of it and keyed the entry to itself. That
    invented a fifth policy on a four-policy package.

    Deliberately NOT a denylist of label words ("account", "agent no", "claim
    number", "form number" ...). The tell is structural and needs no vocabulary:
    a contract key is something OTHER entries are filed under. An identifier
    whose only support is the entry that prints it has attributed nothing.
    `POLICY NUMBER: 6C7-40-02---26` is the same self-reference and is KEPT,
    because its own label says the value is a policy number.
    """
    if not isinstance(entry, dict):
        return False
    pn = re.sub(r"[^A-Za-z0-9]", "", str(entry.get("policy_number") or "")).upper()
    if not pn:
        return False
    val = re.sub(r"[^A-Za-z0-9]", "", str(entry.get("value") or "")).upper()
    if pn != val:
        return False
    return "policy" not in str(entry.get("label") or "").lower()


def _canonicalise_dec_entry_keys(entries: Any) -> None:
    """Collapse each contract's several printings to ONE `policy_number`, and
    each line's several wordings to ONE `line_of_business`. Mutates in place;
    never raises; never invents a value that is not already present."""
    if not isinstance(entries, list) or not entries:
        return
    try:
        # ── Drop identifiers that key nothing but their own entry ────────────
        # Runs BEFORE the election so a phantom key can never become a head and
        # pull real printings into its group. Both conditions are required: the
        # entry must self-attribute AND no other entry may be filed under that
        # key - a thin document where a real policy genuinely has one entry is
        # left alone, because there the key is doing its job.
        _uses: Dict[str, int] = {}
        for e in entries:
            if isinstance(e, dict) and e.get("policy_number"):
                k = str(e["policy_number"]).strip()
                _uses[k] = _uses.get(k, 0) + 1
        for e in entries:
            if not _entry_self_attributes_its_own_identifier(e):
                continue
            if _uses.get(str(e["policy_number"]).strip(), 0) > 1:
                continue
            logger.info(
                "dec_entries: %r keyed only its own entry (label=%r) - not a "
                "contract key, cleared", str(e.get("policy_number")),
                str(e.get("label"))[:40],
            )
            e["policy_number"] = None
        # An ISO FORM NUMBER is not a contract. Run 34efbef4 keyed the PREMIUM
        # AUDIT NONCOMPLIANCE endorsement's entries to "CG 99 09 12 19" - a
        # fifth policy on a four-policy package. The shape is unmistakable and
        # exact: two letters then FOUR two-digit groups (line prefix, form
        # number pair, edition MM YY). Real policy numbers never fit it -
        # "WC-99-123" fails on its three-digit group, "BBC7263 - 26" on its
        # three letters. The key is cleared; the entry and its value survive.
        for e in entries:
            if not isinstance(e, dict) or not e.get("policy_number"):
                continue
            if _ISO_FORM_NUMBER_KEY_RE.match(str(e["policy_number"]).strip()):
                logger.info(
                    "dec_entries: %r is an ISO form number, not a contract "
                    "key - cleared", str(e.get("policy_number")))
                e["policy_number"] = None
        # ── THE INVARIANT: a contract key is PRINTED as a policy number ──────
        # Run 7e95e3ae: the account number returned as a key in a STRONGER
        # shape - the model filed FOUR Common-Declarations entries under
        # "0482854", so the single-entry guard above correctly stood aside and
        # the phantom policy came back with four coverage lines. The first fix
        # pinned the measured case; this is the class: every real contract in
        # every observed package prints its number under a policy-labelled
        # entry ("POLICY NUMBER", "Policy", "POLICY NO", ...), and a key with
        # no such witness anywhere in the document is an identifier the model
        # promoted, never a contract. CONDITIONAL on the document proving it
        # labels policy numbers at all (at least one key has a witness) - a
        # recording with no policy labels anywhere gives the invariant no
        # basis to judge, and it stands aside rather than clearing every key.
        def _is_policy_label(lab: str) -> bool:
            low = str(lab or "").lower()
            return "policy" in low or bool(re.search(r"\bpol\b", low))
        _keys_in_use = {
            str(e.get("policy_number")).strip()
            for e in entries
            if isinstance(e, dict) and e.get("policy_number")
        }
        _key_norm = {k: re.sub(r"[^A-Za-z0-9]", "", k).upper()
                     for k in _keys_in_use}
        _witnessed: set = set()
        for e in entries:
            if not isinstance(e, dict) or not _is_policy_label(e.get("label")):
                continue
            vn = re.sub(r"[^A-Za-z0-9]", "", str(e.get("value") or "")).upper()
            if len(vn) < 4:
                continue
            for k, kn in _key_norm.items():
                if len(kn) >= 4 and (kn.startswith(vn) or vn.startswith(kn)):
                    _witnessed.add(k)
        if _witnessed:
            for e in entries:
                if not isinstance(e, dict) or not e.get("policy_number"):
                    continue
                k = str(e["policy_number"]).strip()
                if k and k not in _witnessed:
                    logger.info(
                        "dec_entries: %r is never printed as a policy number "
                        "anywhere in the document - not a contract key, "
                        "cleared (label=%r)", k, str(e.get("label"))[:40])
                    e["policy_number"] = None
        # ── policy_number ────────────────────────────────────────────────────
        printings = {
            str(e.get("policy_number")).strip()
            for e in entries
            if isinstance(e, dict) and e.get("policy_number")
            and str(e.get("policy_number")).strip()
        }
        norm = {p: re.sub(r"[^A-Za-z0-9]", "", p).upper() for p in printings}
        # ELECTION ORDER, and every clause is load-bearing:
        #   1. longest normalised form  - a short printing joins the fuller one
        #      instead of starting its own group ('BBC7263' -> 'BBC7263 - 26').
        #   2. fewest spaces            - between two printings of the SAME
        #      characters, the OCR-spaced one is the corrupt one. Without this
        #      the alphabetical tie-break elected '6 C 7 - 4 0 - 0 2---26',
        #      which is the exact string that printed on the client's ACORD 125.
        #   3. longest raw              - '6J7-40-02---26' over '6J74002---26':
        #      same characters, but the printing that kept its punctuation kept
        #      more of the document's own structure. Ground truth confirms the
        #      dashed form is what page 143 prints.
        #   4. alphabetical             - only so the result is deterministic.
        # OCR LETTER-SPACING REPAIR, display only. Run 7e95e3ae: the Inland
        # Marine contract's ONLY surviving printing was "6 C 7 - 4 0 - 0 2---26"
        # (the page prints its header letter-spaced), so the election - which
        # never invents a printing - correctly shipped the spaced form as the
        # join key and it landed on the client's ACORD 125 Q4. Collapsing the
        # spacing is FORMATTING repair of an OCR artifact, not invention: it
        # fires only on the unmistakable fingerprint (three or more single
        # alphanumeric characters separated by spaces), so an ordinarily
        # spaced printing like "BBC7263 - 26" ('-' is not alphanumeric) can
        # never match, and entry VALUES keep the verbatim spaced printing.
        def _despace(p: str) -> str:
            toks = p.split(" ")
            if sum(1 for t in toks if len(t) == 1 and t.isalnum()) >= 3:
                return "".join(toks)
            return p
        canonical: Dict[str, str] = {}          # printing -> elected printing
        heads: List[str] = []                   # elected printings, by norm
        for p in sorted(printings,
                        key=lambda x: (-len(norm[x]), x.count(" "), -len(x), x)):
            n = norm[p]
            if not n:
                continue
            for h in heads:
                hn = norm[h]
                if hn.startswith(n) or n.startswith(hn):
                    canonical[p] = _despace(h)
                    break
            else:
                heads.append(p)
                canonical[p] = _despace(p)
        merged = {p: h for p, h in canonical.items() if p != h}
        # ── line_of_business ─────────────────────────────────────────────────
        remapped: Dict[str, str] = {}
        for e in entries:
            if not isinstance(e, dict):
                continue
            raw_pn = str(e.get("policy_number") or "").strip()
            if raw_pn and raw_pn in canonical:
                e["policy_number"] = canonical[raw_pn]
            raw_lob = str(e.get("line_of_business") or "").strip()
            if raw_lob:
                display = _DEC_LINE_DISPLAY.get(_canon_line(raw_lob) or "")
                # No display name means the canonicaliser cannot place this
                # wording. Leave it exactly as printed - dropping it would
                # destroy an attribution the model did establish.
                if display and display != raw_lob:
                    e["line_of_business"] = display
                    remapped[raw_lob] = display
        if merged or remapped:
            logger.info(
                "dec_entries KEYS canonicalised: %d policy printing(s) merged "
                "(%s), %d line wording(s) mapped (%s)",
                len(merged), "; ".join(f"{k!r}->{v!r}" for k, v in list(merged.items())[:4]),
                len(remapped), "; ".join(f"{k!r}->{v!r}" for k, v in list(remapped.items())[:4]),
            )
    except Exception as exc:                              # noqa: BLE001
        logger.warning("dec_entries key canonicalisation skipped: %s", exc)


def _dec_entry_token_match(a: str, b: str) -> bool:
    """Two tokens name the same thing: identical, or prefix-stems (>=4 chars,
    the same rule pdf_service._stem_match uses, so 'comprehensive'~'comp')."""
    if a == b:
        return True
    return len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a))


# Key/label tokens that QUALIFY a fact without changing WHAT it is. Dropping
# "total" from total_payroll still names payroll; dropping "gl" from
# gl_deductible names a DIFFERENT thing (any line's deductible). That asymmetry
# is the whole safety argument of the reverse label match below.
_GENERIC_QUALIFIER_TOKENS = frozenset({
    "total", "annual", "num", "number", "count", "overall", "estimated",
})


def _dec_entry_label_matches_key(label: str, key_tokens: List[str]) -> bool:
    """Does this dec-page label name this fact key?

    FORWARD (the original rule): every key token appears in the label -
    "FEIN OR SOC SEC #" names `fein`, extra label words are fine.

    STRICT REVERSE (added after the first live run backfilled NOTHING): the
    dec page prints "PAYROLL", the key is `total_payroll`, and the unmatched
    "total" blocked the forward rule - so the one warning on that run ("no
    revenue or payroll found") stood while the dec printed both. Reverse
    matching is allowed ONLY when (a) every significant label token matches a
    key token AND (b) every UNMATCHED key token is a generic qualifier.
    "Deductible" -> gl_deductible leaves "gl" unmatched: refused, because a
    bare deductible could belong to any coverage line. "Premium" ->
    total_policy_premium leaves "policy": refused for the same reason.
    """
    label_tokens = [t for t in _dec_norm(label).split() if len(t) >= 3]
    if not label_tokens:
        return False
    if all(any(_dec_entry_token_match(kt, lt) for lt in label_tokens)
           for kt in key_tokens):
        return True                        # forward
    sig_label = [t for t in label_tokens if t not in _GENERIC_QUALIFIER_TOKENS]
    if not sig_label:
        return False
    return (
        all(any(_dec_entry_token_match(lt, kt) for kt in key_tokens)
            for lt in sig_label)
        and all(kt in _GENERIC_QUALIFIER_TOKENS
                or any(_dec_entry_token_match(kt, lt) for lt in sig_label)
                for kt in key_tokens)
    )


def _dec_entry_owner_ok(fact_key: str, owner: str) -> bool:
    """A producer's value only ever fills producer_* facts; a carrier's only
    carrier_*; everything else takes applicant- or policy-owned values ONLY.
    This is the deterministic form of the client's Part 19 rule: 'never place
    producer or carrier contact information into applicant fields'."""
    if fact_key.startswith("producer"):
        return owner == "producer"
    if fact_key.startswith("carrier"):
        return owner == "carrier"
    return owner in ("applicant", "policy")


def _backfill_empty_facts_from_entries(facts: dict, entries: List[dict]) -> None:
    """Fill registry facts that merged EMPTY from verified dec-page entries.

    Five stacked conditions, each of which alone would block the client's
    literal reported defect (the carrier's account number stamped as the FEIN):
      1. the fact is genuinely empty - a backfill never overwrites;
      2. the fact has a NAMED shape validator in FACT_REGISTRY and the entry
         value passes it (a fact with no validator is not typed enough to
         backfill safely);
      3. every token of the fact KEY appears in the entry LABEL (stem match) -
         'fein' is not in 'Account Number', so that value cannot route there;
      4. the entry's owner is compatible (_dec_entry_owner_ok);
      5. all matching entries agree on ONE value - two distinct candidates is
         ambiguity, and ambiguity stays blank for the ARQ to ask.
    Mutates `facts`; every fill is logged with its provenance.
    """
    if not entries or not isinstance(facts, dict):
        return
    try:
        from services.fact_registry import FACT_REGISTRY, _is_currency
    except Exception:                                     # noqa: BLE001
        return
    # Extraction facts that are NOT in FACT_REGISTRY but are typed and worth
    # backfilling. total_policy_premium is the flagship dec value and its only
    # downstream consumer (_resolve_estimated_total) carries its own arithmetic
    # guards. Deliberately NOT added to FACT_REGISTRY instead: registry
    # membership would generate a new ARQ client question for it, a behaviour
    # change far beyond this feature's scope.
    _extra_typed = {"total_policy_premium": _is_currency}
    _candidates = {**{k: (s or {}).get("validate") for k, s in FACT_REGISTRY.items()},
                   **_extra_typed}
    filled = 0
    for key, validator in _candidates.items():
        if key in _LIST_FIELDS or key in _STRUCTURED_DICT_FIELDS:
            continue
        v_name = getattr(validator, "__name__", "")
        if not callable(validator) or not v_name.startswith("_is_"):
            continue                       # condition 2: typed facts only
        current = facts.get(key)
        current_val = current.get("value") if isinstance(current, dict) else current
        if not _is_empty(current_val):
            continue                       # condition 1: never overwrite
        key_tokens = re.findall(r"[a-z0-9]+", key)
        by_value: Dict[str, dict] = {}
        for entry in entries:
            if not _dec_entry_label_matches_key(entry["label"], key_tokens):
                continue                   # condition 3: label names this key
            if not _dec_entry_owner_ok(key, entry["owner"]):
                continue                   # condition 4: right party
            try:
                if not validator(entry["value"]):
                    continue               # condition 2: value has the right shape
            except Exception:              # noqa: BLE001
                continue
            by_value.setdefault(_dec_norm(entry["value"]), entry)
        if len(by_value) != 1:
            if len(by_value) > 1:
                logger.info(
                    "dec_entries BACKFILL_AMBIGUOUS fact=%s candidates=%s - "
                    "two distinct stated values, leaving blank for the ARQ",
                    key, [e["value"][:40] for e in list(by_value.values())[:3]],
                )
            continue                       # condition 5: exactly one value
        entry = next(iter(by_value.values()))
        facts[key] = {"value": entry["value"], "confidence": "ai_low",
                      "source": "dec_entry", "evidence_state": "source_verified",
                      "verified_in_text": True,
                      # E&O 5.7: what produced this - the printed entry itself.
                      "derivation": {"rule": "dec_entry_backfill",
                                     "inputs": ["dec_page_entries"],
                                     "entry_label": str(entry.get("label") or "")[:80],
                                     "entry_owner": entry.get("owner")}}
        filled += 1
        logger.info(
            "dec_entries BACKFILL fact=%s value=%r from label=%r owner=%s - "
            "extraction merged this fact empty; the dec page states it verbatim",
            key, entry["value"][:60], entry["label"][:60], entry["owner"],
        )
    if filled:
        logger.info("dec_entries BACKFILL filled %d empty fact(s)", filled)


# ACORD's billing method is a TWO-VALUE vocabulary: a policy is direct bill or
# agency bill. Closed vocabulary is the one shape of raw-text scan this
# codebase allows itself (same argument as _LOB_NAMES) - it maps a printed
# literal onto an enum and can never capture free text, which is what makes it
# different from the label-scan class that caused the 2026-08-08 boilerplate
# defects. Word-bounded so "direct billing disputes" prose cannot match.
_BILLING_VOCAB = (
    ("DIRECT BILL", re.compile(r"\bdirect bill\b")),
    ("AGENCY BILL", re.compile(r"\bagency bill\b")),
)


# ── THE ROOT FIX: repair the line -> policy relationship (client 2026-08-15) ──
# Live run, `merge coverage_lines FINAL`:
#     ('Property','None','6C7-40-02---26')  ('Liability','$3,954','6C7-40-02---26')
#     ('Automobile','$2,991','6C7-40-02---26') ('Umbrella','$3,418','6C7-40-02---26') ...
# ONE policy number - the Inland Marine one, the last the model happened to read -
# attached to all EIGHT lines. Every downstream consumer was then working from a
# fact in which "which policy covers which line" had already been destroyed, which
# is the client's report #1 ("policy numbers are crossing lines of business") at
# its actual source. Stamping guards can only refuse to print a corrupt pairing;
# they cannot recover the real one.
#
# `dec_page_entries` CAN. Each entry is verified verbatim against the uploaded
# text (_verify_dec_entries) and carries its own `line_of_business` and
# `policy_number` as printed together on the page. On this package the correct
# pairs are all there - 6E7 with Covered Autos, 6J7 with the Umbrella, BBC7263
# with the CGL - which is exactly why ACORD 125's Q4 grid printed them correctly
# while the section forms did not.
#
# So: when the line list is self-contradictory, rebuild its policy numbers from
# the verified entries. A line the entries cannot settle gets None - blank, never
# another line's number.
# SPECIFIC coverage names, tried FIRST. "Liability" is deliberately absent:
# it is the weakest word on a declarations page - "Commercial Auto Liability",
# "Commercial Liability Umbrella" and "Employers Liability" are all liability,
# and none of them is the General Liability part. A first version of this ranked
# by phrase LENGTH and therefore read "Commercial Liability Umbrella" as General
# Liability, which is the very defect this function exists to repair (caught by
# test_auto_beats_bare_liability_in_line_canonicalisation, not in production).
def _canon_line(text: Any) -> Optional[str]:
    """Which standard line of business a free-text line name denotes.

    Delegates to the leaf module ``services.lob_canon`` (V1 plan C1, F8): the
    tables used to live here, inside a 7,000-line module that three other
    modules imported lazily behind ``except: lambda _s: None`` fallbacks - a
    circular-import blip silently disabled canonicalisation. The name is kept
    so every internal caller and test reads unchanged; the rules live in one
    importable place. Returns None when the text names no line we recognise,
    so callers can tell "not this line" from "cannot tell" and blank rather
    than guess.
    """
    return _lob_canon_line(text)


def _looks_like_a_policy_number(value: Any) -> bool:
    """Reject ISO/AAIS FORM numbers ('CG 00 01 04 13', 'IM 7100 06 04') and
    obvious non-identifiers. A form number names the coverage WORDING; a policy
    number names THIS contract. Mirrors pdf_service._looks_like_a_form_number,
    kept local to avoid importing the stamping layer into extraction."""
    s = str(value or "").strip()
    if len(s) < 4 or not re.search(r"\d", s):
        return False
    return not re.match(r"^[A-Z]{2}[ -]?\d{2,4}(?:[ -]\d{2}){2,3}$", s, re.I)


def _policy_numbers_by_line(entries: Any) -> Dict[str, set]:
    """{canonical_line: {policy numbers the document printed for it}} from the
    VERIFIED dec entries - the only place the pairing survives intact."""
    out: Dict[str, set] = {}
    if not isinstance(entries, list):
        return out
    for e in entries:
        if not isinstance(e, dict):
            continue
        pn = str(e.get("policy_number") or "").strip()
        if not pn or not _looks_like_a_policy_number(pn):
            continue
        # The entry's own line, else the declarations SECTION heading it was
        # printed under ("COMMERCIAL UMBRELLA DECLARATIONS") - that heading is
        # precisely what says which coverage part a figure belongs to.
        line = _canon_line(e.get("line_of_business")) or _canon_line(e.get("section"))
        if line:
            out.setdefault(line, set()).add(pn)
    return out


def _coverage_lines_are_self_contradictory(lines: Any) -> bool:
    """True when one policy number is attached to two or more DIFFERENT lines of
    business - it cannot be identifying a policy, so the pairing is corrupt."""
    if not isinstance(lines, list):
        return False
    by_number: Dict[str, set] = {}
    for e in lines:
        if not isinstance(e, dict):
            continue
        pn = re.sub(r"[^a-z0-9]", "", str(e.get("policy_number") or "").lower())
        line = _canon_line(e.get("line"))
        if pn and line:
            by_number.setdefault(pn, set()).add(line)
    return any(len(v) > 1 for v in by_number.values())


def _carriers_by_line(entries: Any) -> Dict[str, set]:
    """{canonical_line: {carrier names printed under that line}}.

    The Orbin ground truth is why this is per-line and not a scalar: EMC
    Property & Casualty Company issues the GENERAL LIABILITY part while
    Employers Mutual Casualty Company issues Inland Marine, Auto and Umbrella.
    Two legal entities from one group on one package - so "the carrier" cannot
    be one value without being wrong on some form.
    """
    out: Dict[str, set] = {}
    if not isinstance(entries, list):
        return out
    for e in entries:
        if not isinstance(e, dict):
            continue
        if str(e.get("owner") or "").strip().lower() != "carrier":
            continue
        name = str(e.get("value") or "").strip()
        if len(name) < 4:
            continue
        line = _canon_line(e.get("line_of_business")) or _canon_line(e.get("section"))
        if line:
            out.setdefault(line, set()).add(name)
    return out


def _repair_coverage_lines_from_entries(mf: dict) -> None:
    """Re-attach each coverage line to ITS OWN policy number, or to none.

    Acts only when the list is self-contradictory - a healthy list is never
    touched, so a package whose extraction was clean behaves exactly as before.
    Carrier is repaired on the same pass from the same evidence, and only when
    the document names exactly ONE carrier for that line; anything ambiguous is
    left for `_section_carrier_pair`, which refuses to pair on ambiguity.
    """
    lines = mf.get("coverage_lines")
    if not isinstance(lines, list) or not lines:
        return
    if not _coverage_lines_are_self_contradictory(lines):
        return
    by_line = _policy_numbers_by_line(mf.get("dec_page_entries"))
    by_carrier = _carriers_by_line(mf.get("dec_page_entries"))
    for e in lines:
        if not isinstance(e, dict):
            continue
        canon = _canon_line(e.get("line"))
        names = by_carrier.get(canon) if canon else None
        if names and len(names) == 1:
            e["carrier"] = next(iter(names))
    repaired = cleared = 0
    for e in lines:
        if not isinstance(e, dict):
            continue
        canon = _canon_line(e.get("line"))
        candidates = by_line.get(canon) if canon else None
        if candidates and len(candidates) == 1:
            new_pn = next(iter(candidates))
            if str(e.get("policy_number") or "").strip() != new_pn:
                e["policy_number"] = new_pn
                repaired += 1
        else:
            # The document cannot settle this line's policy number. Blank beats
            # a number belonging to a different coverage part.
            if e.get("policy_number") is not None:
                e["policy_number"] = None
                cleared += 1
    logger.warning(
        "coverage_lines REPAIRED from verified dec entries: one policy number "
        "was attached to several different lines of business - %d line(s) "
        "re-paired to their own policy number, %d cleared as unresolvable",
        repaired, cleared,
    )


# ── A conflict INSIDE one document is still a conflict (client 2026-08-15) ───
# "The original Umbrella declarations show a $3,000,000 limit. A later COI
# states that the limit was reduced from $3,000,000 to $1,000,000... Primble
# showed $1M in one part of the workflow and $3M in another, and ultimately
# populated $3M on the form."
#
# The cross-DOCUMENT reconciler already holds a conflicted value back until the
# producer confirms it - but it compares documents, and this client uploads ONE
# 271-page package containing the dec page AND the later COI. One document in,
# no disagreement seen, and the merge quietly stamped the figure that appeared
# most often. Repetition is not authority: a superseded limit printed on every
# dec page beats a corrected one printed once, every time.
#
# The merge already knows: `_merge_list_fields` records the candidates it
# REJECTED. When a limit-class fact was chosen over a materially different
# rival, that IS the unresolved conflict, and the withhold list is exactly the
# right place to say so.
_CONFLICT_SENSITIVE_LIMITS: Tuple[str, ...] = ("umbrella_limit",)


# The legally-standard printings of the three risk-transfer requirements. A
# document that requires one of these says so in one of these ways - the wording
# is contractual boilerplate, not free description, which is what makes a
# presence test safe here.
_RISK_TRANSFER_TOPIC_PHRASES: Dict[str, Tuple[str, ...]] = {
    "additional_insured_required": (
        "additional insured", "additional insureds", "add'l insured",
        "addl insured", "as additional insured",
    ),
    "waiver_of_subrogation_required": (
        "waiver of subrogation", "waive subrogation", "waiver of rights of "
        "recovery", "transfer of rights of recovery", "subrogation waived",
    ),
    "primary_noncontributory_required": (
        "primary and non-contributory", "primary and noncontributory",
        "primary & non-contributory", "primary/noncontributory",
        "non-contributory", "noncontributory",
    ),
}


def _drop_unstated_risk_transfer(mf: dict, text: str) -> None:
    """A `false` the document never actually says is NOT an answer.

    BELT AND BRACES for the schema change above. The prompt now offers `null`
    for "the document does not address this", but a prompt is a request; this is
    the check. If the merged facts claim `false` and the uploaded text contains
    no mention of the topic AT ALL, the claim has no basis and the sub-key is
    removed - which the conflict detector reads as "not stated" and skips.

    Only ever removes an UNSUPPORTED `false`. A `true` is untouched (something
    asserted it), and a `false` printed against real wording ("waiver of
    subrogation is not required") is untouched too, because the phrase is there.
    Presence is safe to test here precisely because these three requirements are
    contractual boilerplate with standard printings, not free description.
    """
    rt = mf.get("risk_transfer")
    if not isinstance(rt, dict):
        return
    low = str(text or "").lower()
    dropped = []
    for key, phrases in _RISK_TRANSFER_TOPIC_PHRASES.items():
        if rt.get(key) is not False:
            continue                      # true, or already "not stated"
        if not any(p in low for p in phrases):
            rt.pop(key, None)
            dropped.append(key)
    if dropped:
        logger.info(
            "risk_transfer: dropped an unsupported 'No' on %s - the uploaded "
            "text never mentions the requirement, so absence was being "
            "reported as a refusal", ", ".join(dropped))


# Policy-date facts. An AMENDMENT date ("...effective 07/25/2025") is not one
# of these - it is the day a change took effect, while the policy still incepted
# on its own date.
_POLICY_DATE_KEYS: Tuple[str, ...] = (
    "effective_date", "expiration_date",
    "umbrella_effective_date", "umbrella_expiration_date",
    "prior_effective_date", "prior_expiration_date",
)


def _dec_index_witnesses_date(mf: dict, value: str) -> bool:
    """True when the verified dec index printed this date against a DATE label.

    A date on a declarations page sits next to "Policy Effective Date"; a date
    inside a sentence sits next to "effective". Only the first is a policy date.
    """
    from services.normalization import normalize_date
    want = normalize_date(value)
    if not want:
        return False
    for e in (mf.get("dec_page_entries") or []):
        if not isinstance(e, dict):
            continue
        label = str(e.get("label") or "").lower()
        if "date" not in label and "eff" not in label and "exp" not in label:
            continue
        if normalize_date(e.get("value")) == want:
            return True
    return False


def _drop_endorsement_dates_from_policy_facts(mf: dict, docs: List[dict]) -> None:
    """An endorsement date must not be stamped as the policy's own date.

    PROBE RUN B, 2026-08-17. The certificate's remarks read "...the Commercial
    Umbrella limit was reduced from $3,000,000 to $1,000,000 effective
    07/25/2025", and `umbrella_effective_date` came back as 07/25/2025 - which
    then fought the dec page's real inception date of 07/15/2025 and produced a
    conflict card about two dates that were never describing the same thing.
    The client's words: "The individual facts within it need to be interpreted
    in their appropriate context."

    POSITIVE EVIDENCE ON BOTH SIDES before anything is removed:
      * the date must be the `as_of` of an AMENDMENT the narrative states, and
      * the dec index must NOT independently witness it against a date label.
    A policy whose term genuinely begins the day an endorsement takes effect
    therefore keeps its date, because the dec page prints it.
    """
    # NO INDEX, NO OPINION. Without dec entries there is no way to ask whether a
    # date is printed as a policy date, so every amendment date would look
    # unwitnessed and be removed. That is not a theoretical worry: if an
    # amendment happens to take effect on the policy's own inception date, this
    # would delete `effective_date` - and `_route_renewal_dates` (Fix 2) then
    # has nothing to route, so ACORD 125's PROPOSED EFF/EXP goes blank and
    # Tier-1 demands a date the document already answers. That is Round 3's
    # Fix 13 regression, reintroduced from a different direction.
    if not (mf.get("dec_page_entries") or []):
        return
    try:
        from services.narrative_facts import statements_for_facts
    except Exception:                                        # pragma: no cover
        return
    amendment_dates = {
        str(s.get("as_of")) for s in statements_for_facts(mf, None, docs)
        if s.get("kind") == "amendment" and s.get("as_of")
    }
    if not amendment_dates:
        return
    from services.normalization import normalize_date
    normed = {normalize_date(d) for d in amendment_dates}
    normed.discard(None)
    for key in _POLICY_DATE_KEYS:
        val = _fv(mf, key)
        if not val or normalize_date(val) not in normed:
            continue
        if _dec_index_witnesses_date(mf, str(val)):
            continue                      # the dec page prints it - it is real
        mf.pop(key, None)
        _record_fact_rejection(
            mf, key, "the only date found is an endorsement's effective date, "
                     "not a policy inception date")
        logger.info(
            "%s dropped: %r is the effective date of an amendment stated in the "
            "remarks, and no declarations page prints it as a policy date. An "
            "endorsement date is not an inception date.", key, str(val))


# How far into a document "the top of the page" reaches, and how long a value
# can be and still be a heading rather than a remark.
_PAGE_FURNITURE_HEAD_CHARS = 200
# A heading is a line, not a paragraph. 250 was tried and dropped a real
# 142-character remark that happened to open its document; a form title runs to
# roughly a hundred characters, so anything longer is content.
_PAGE_FURNITURE_MAX_LEN = 120


def _drop_page_furniture_remarks(mf: dict, docs: List[dict]) -> None:
    """A document's own TITLE is not a remark about the risk.

    PROBE RUN B, 2026-08-17: `additional_remarks_text` came back as
    "PROBE 2 - COMMERCIAL PACKAGE DECLARATIONS Upload together with PROBE 3..."
    - the PDF's title block. On a real submission the equivalent is the form
    heading ("COMMERCIAL PACKAGE DECLARATIONS"), and it would be stamped into
    ACORD 101's Additional Remarks rows as though the broker had written it.

    THE DOCUMENT MUST BEGIN WITH IT. A first cut asked only whether the value
    appeared within the first %d characters, and that dropped a REAL remark: an
    ACORD 101 is mostly remarks, and they start right after a one-line form
    header. "Near the top" is not the signal - "IS the top" is. A heading is
    literally the first thing printed; a remark always has something above it.

    Also requires the value to be short enough to be a heading (under %d
    chars), so a long narrative that genuinely opens a document survives.

    Fails toward keeping the remark: anything not clearly furniture stays,
    because losing a real remark is worse than printing a heading once.
    """ % (_PAGE_FURNITURE_HEAD_CHARS, _PAGE_FURNITURE_MAX_LEN)
    from services.narrative_facts import NARRATIVE_FACT_KEYS
    heads = [re.sub(r"\s+", " ", str(d.get("text") or "").strip().lower())
             [:_PAGE_FURNITURE_HEAD_CHARS] for d in (docs or [])]
    if not any(heads):
        return
    for key in NARRATIVE_FACT_KEYS:
        val = _fv(mf, key)
        if not isinstance(val, str) or len(val) > _PAGE_FURNITURE_MAX_LEN:
            continue
        probe = re.sub(r"\s+", " ", val.strip().lower())[:40]
        if len(probe) < 12:
            continue
        if any(h.startswith(probe) for h in heads):
            mf.pop(key, None)
            _record_fact_rejection(
                mf, key, "the only text found is the document's page heading, "
                         "not a remark about the risk")
            logger.info(
                "%s dropped: %r is what the document OPENS with, so it is the "
                "page heading rather than a remark about the risk",
                key, val[:60])


# ── THE REJECTION LEDGER (client 1.3 "Unable to Determine") ─────────────────
# *"Primble has relevant source material but cannot reliably determine the
# answer. This is different from simply not finding the information."*
#
# Several components already find a value, judge it unusable and DISCARD it -
# an endorsement date that is not an inception date, a page heading mistaken
# for a remark. Each logged its reasoning and then dropped the fact, which made
# the result indistinguishable from a document that never mentioned the subject
# at all. That is the exact distinction the client asked us to keep.
#
# The ledger only RECORDS a judgement already made. It never makes one, never
# resurrects a value, and never changes what any existing consumer reads: the
# fact is still absent, `_fv` still returns None, scoring is untouched. The
# only new thing is that `fact_state` can now say WHY it is absent.
REJECTED_FACTS_KEY = "_rejected_facts"


def _record_fact_rejection(mf: dict, key: str, reason: str) -> None:
    """Note that a value for ``key`` was found and deliberately discarded.

    Idempotent, never raises, and a no-op once the fact carries a real value
    again - a later document supplying a good value must not leave the fact
    reading "unable to determine".
    """
    try:
        if not isinstance(mf, dict) or not key:
            return
        ledger = mf.get(REJECTED_FACTS_KEY)
        if not isinstance(ledger, dict):
            ledger = {}
            mf[REJECTED_FACTS_KEY] = ledger
        ledger[key] = str(reason or "")[:200]
    except Exception:                                         # noqa: BLE001
        pass                                                  # bookkeeping only


def _flag_intra_document_limit_conflicts(mf: dict, rejected_by_field: Dict[str, List[str]]) -> None:
    """Add a limit fact to the stamped-value withhold list when the merge had to
    choose between two materially different amounts for it.

    Only ever ADDS to `_uw_conflicted_keys`, which the stamping layer reads to
    leave a box blank pending confirmation. The fact itself is untouched, so
    scoring, warnings and the picker all still see it.
    """
    for key in _CONFLICT_SENSITIVE_LIMITS:
        chosen = _fv(mf, key)
        if not chosen:
            continue
        amounts = {_amount_key(chosen)}
        for cand in rejected_by_field.get(key) or []:
            amounts.add(_amount_key(cand))
        # EVERY STATED WITNESS COUNTS, not only the merge's rejects. Client
        # run 2026-08-16: the 131 still shipped $3,000,000 while the package's
        # own narrative carries the COI's reduction to $1,000,000 effective
        # 7/25/25. The merge only records a REJECT when both amounts arrive as
        # candidates for this same fact - a limit stated in a certificate or a
        # narrative sentence never does, so the conflict was invisible to the
        # withhold and the most-repeated figure stamped unchallenged.
        # `_stated_umbrella_limits` reads the sources that DO carry it.
        if key == "umbrella_limit":
            amounts |= {_amount_key(v) for v in _stated_umbrella_limits(mf)}
        amounts.discard(None)
        if len(amounts) > 1:
            existing = list(mf.get("_uw_conflicted_keys") or [])
            if key not in existing:
                existing.append(key)
                mf["_uw_conflicted_keys"] = sorted(existing)
            logger.warning(
                "intra-document conflict on %r: the document states %d different "
                "amounts (%s) and no endorsement settles which is authoritative - "
                "the stamped value is WITHHELD pending producer confirmation",
                key, len(amounts), sorted(a for a in amounts if a),
            )


# An umbrella/excess limit stated in prose, e.g. the COI's "the Umbrella limit
# was reduced from $3,000,000 to $1,000,000 effective 7/25/25". BOTH figures in
# that sentence are stated umbrella limits, which is precisely the
# disagreement - so the clause is matched WHOLE (to the sentence end) and every
# amount inside it is harvested. A first-amount-only capture was tried and
# found half the evidence: it returned the $3,000,000 the form already had and
# missed the $1,000,000 that makes it a conflict.
_UMBRELLA_PROSE_CLAUSE_RE = re.compile(r"(?:umbrella|excess)[^.]{0,160}", re.I)
# $1,000,000 and up: seven characters of digits-and-commas. A four-figure
# deductible, premium or fee cannot reach it.
_ANY_AMOUNT_RE = re.compile(r"\$\s?[\d,]{7,}")


def _stated_umbrella_limits(mf: dict) -> List[str]:
    """Umbrella/excess limit amounts the package states OUTSIDE the merged
    fact - narrative remarks and the coverage-line summary.

    Deliberately narrow. Only sentences that NAME the umbrella or excess line
    are read, and only amounts of $1,000,000 or more (the regex's 7-digit
    floor), so a deductible, a premium or an unrelated GL figure cannot
    manufacture a conflict. Returning extra amounts can only ever WITHHOLD a
    stamped value pending confirmation - it never changes a fact and never
    fills a box - so the failure direction is the client's own: unresolved
    rather than silently resolved.
    """
    out: List[str] = []
    for key in ("acord101_remarks", "additional_remarks_text",
                "account_description", "umbrella_notes"):
        text = str(_fv(mf, key) or "")
        if not text:
            continue
        for m in _UMBRELLA_PROSE_CLAUSE_RE.finditer(text):
            # the whole clause, so "reduced from $3,000,000 to $1,000,000"
            # contributes BOTH figures, not just the first
            out.extend(_ANY_AMOUNT_RE.findall(m.group(0)))
    lines = _fv(mf, "coverage_lines")
    if isinstance(lines, list):
        for e in lines:
            if not isinstance(e, dict):
                continue
            if _canon_line(str(e.get("line") or "")) != "umbrella":
                continue
            for k in ("limit", "each_occurrence", "aggregate"):
                v = str(e.get(k) or "")
                if re.search(r"\d", v):
                    out.append(v)
    return out


def _amount_key(v: Any) -> Optional[int]:
    """Whole dollars, or None when there is no figure to compare."""
    digits = re.sub(r"[^\d]", "", str(v or "").split(".")[0])
    return int(digits) if digits else None


# ── is_renewal, deterministically (client: "Primble correctly identifies this ──
# submission as a Renewal"). On the live run it did NOT: the STATUS OF
# TRANSACTION boxes came out blank and the expired-term HARD stop fired, because
# the renewal fixes are gated on this fact and the model had left it null. The
# document states it in print - "RENEWAL OF: 6E7-40-02---25" - so this is a
# copy, not an inference.
_RENEWAL_TEXT_RE = re.compile(
    r"\b(?:renewal\s+of|renewal\s+policy|renewal\s+declarations?|"
    r"this\s+is\s+a\s+renewal|renewal\s+certificate)\b", re.I)


def _backfill_is_renewal(mf: dict, full_text: str) -> None:
    """Set is_renewal from the document's own printed wording when extraction
    left it empty. Never overrides a value the model DID state."""
    if _fv(mf, "is_renewal"):
        return
    m = _RENEWAL_TEXT_RE.search(full_text or "")
    if not m:
        return
    mf["is_renewal"] = {"value": "yes", "confidence": "filled", "source": "dec_entry",
                        # E&O 5.7: derived from the document's own printed phrase.
                        "derivation": {"rule": "renewal_phrase_in_document_text",
                                       "inputs": [],
                                       "matched_text": m.group(0)[:80]}}
    logger.info(
        "is_renewal BACKFILL value='yes' - the document prints %r; extraction "
        "merged the fact empty, which left the renewal date routing and the "
        "renewal hard-stop exception disengaged", m.group(0)[:40],
    )


def _entries_state_payroll(entries: Any) -> bool:
    """The verified dec entries state a payroll exposure, whatever the shape:
    a payroll-labelled entry carrying a figure ('PAYROLL' = '$39,300'), or a
    basis entry whose value IS the word ('Prem Basis' = 'Payroll' - the
    split-cell shape; its amount is the sibling entry). Consumed by
    sqs_service's GL exposure warning, both live (via the entries) and after
    the C57 purge (via the `dec_states_payroll_basis` fact merge_facts derives
    from this while the entries still exist)."""
    if not isinstance(entries, list):
        return False
    for e in entries:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label") or "").lower()
        value = str(e.get("value") or "").strip().lower()
        if "payroll" in label and re.search(r"\d", value):
            return True
        if value == "payroll":
            return True
    return False


def _backfill_billing_plan(facts: dict, full_text: str) -> None:
    """Fill an EMPTY billing_plan from the document's own printed billing word.

    WHY (live 2026-08-14, ORBIN): the package prints DIRECT BILL on all four
    section dec pages, but always FUSED into a label run ("DIRECT BILL AGENT
    PHONE: ..."), so the extraction model never returned the fact and the
    entry-backfill's label-match condition (correctly) refused the fused
    entries. The empty fact then fell to gap fill, which answered the Direct
    Bill checkbox "No" - a stamped contradiction of four printed statements.

    Fires ONLY when the fact merged empty, and ONLY when exactly one of the
    two vocabulary values is printed - both printed is a real ambiguity and
    stays blank for reconciliation, same rule as the entry backfill's
    condition 5. Never overwrites; the value written is ACORD's own canonical
    printing of the method.
    """
    if not isinstance(facts, dict) or not (full_text or "").strip():
        return
    current = facts.get("billing_plan")
    current_val = current.get("value") if isinstance(current, dict) else current
    if not _is_empty(current_val):
        return
    hay = _dec_norm(full_text)
    stated = [printed for printed, rx in _BILLING_VOCAB if rx.search(hay)]
    if len(stated) != 1:
        if len(stated) > 1:
            logger.info(
                "billing_plan backfill: document prints BOTH billing methods - "
                "ambiguous, leaving blank")
        return
    facts["billing_plan"] = {"value": stated[0], "confidence": "ai_low",
                             "source": "dec_entry",
                             # E&O 5.7: closed-vocabulary scan of the document.
                             "derivation": {"rule": "billing_vocabulary_in_document_text",
                                            "inputs": []}}
    logger.info(
        "billing_plan BACKFILL value=%r - extraction merged this fact empty; "
        "the document prints the method verbatim (closed two-value vocabulary)",
        stated[0],
    )


SCOPED_FACTS_KEY = "_scoped"

# Which `coverage_lines` column states each line-scoped fact. Mirrors
# `underwriting_consistency._LINE_SCOPED_FACT_COLUMN`; kept here because the
# store is BUILT here and read there, and a cross-check test pins the two.
_SCOPED_FACT_COLUMNS: Dict[str, str] = {
    "policy_number":   "policy_number",
    "carrier_name":    "carrier",
    "carrier_naic":    "naic",
    "effective_date":  "effective_date",
    "expiration_date": "expiration_date",
}


def _build_scoped_fact_store(mf: dict) -> None:
    """Write ``facts["_scoped"]`` - each line-scoped fact WITH its scope.

    C1b / D19, owner-directed 2026-08-21: *"we should carry relationship, we
    should store it somehow, not just this but for every other important
    fact"*. Client 1.1 puts Scope/Association BEFORE Reconciliation; until now
    scope was re-derived inside the comparator from the value's own characters,
    which is how a spelling variant lost its scope and produced a false
    conflict (the reverted "Pass 1b" attempt, C1-Q).

    SHAPE - additive, and `mf[key]` is untouched, so all existing fact reads
    stay valid::

        facts["_scoped"]["carrier_name"] = [
            {"value": "EMC Prop & Cas Co",
             "scope": {"line": "general_liab", "line_printed": "Commercial
                       General Liability", "policy_number": "BBC7263-26"}},
            ...
        ]

    ONE ENTRY PER (fact, coverage line). A line with no canonical family is
    skipped - unmapped terminology gets no opinion (client 1.7 / D9) - and a
    fact with no value on that line contributes nothing. Never raises: the
    store is an enrichment, and its absence returns every consumer to the
    behaviour it had before C1b.
    """
    try:
        lines = mf.get("coverage_lines")
        if not isinstance(lines, list) or not lines:
            mf.pop(SCOPED_FACTS_KEY, None)
            return
        store: Dict[str, List[dict]] = {}
        for entry in lines:
            if not isinstance(entry, dict):
                continue
            printed = str(entry.get("line") or "").strip()
            canon = _canon_line(printed)
            if not canon:
                continue
            pol = str(entry.get("policy_number") or "").strip() or None
            scope = {"line": canon, "line_printed": printed, "policy_number": pol}
            for fact_key, column in _SCOPED_FACT_COLUMNS.items():
                raw = entry.get(column)
                val = str(raw).strip() if raw is not None else ""
                if not val:
                    continue
                store.setdefault(fact_key, []).append(
                    {"value": val, "scope": dict(scope)})
        if store:
            mf[SCOPED_FACTS_KEY] = store
            logger.info(
                "scoped fact store: %s",
                {k: len(v) for k, v in sorted(store.items())})
        else:
            mf.pop(SCOPED_FACTS_KEY, None)
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("merge_facts: scoped fact store failed: %s", exc)
        mf.pop(SCOPED_FACTS_KEY, None)


def _union_list_fact(list_key: str, primary_rows: list, merged_rows: list) -> list:
    """The primary document's rows PLUS everything the companions add.

    Order is primary-first on purpose: every consumer that takes "the first
    matching row" keeps the answer it gives today, and a companion document can
    only ever ADD a row. De-duplication is the schedule de-duplicator the
    chunk-level merge already uses, so "is this the same vehicle / driver /
    coverage part?" has ONE definition rather than a second one here.

    A list of plain strings (`lines_of_business`) has no schedule identity, so
    it de-duplicates on its own normalised text. Never raises: any failure
    returns the primary's rows, which is exactly today's behaviour.
    """
    try:
        combined = list(primary_rows) + list(merged_rows)
        if not any(isinstance(r, dict) for r in combined):
            # `lines_of_business` de-duplicates by COVERAGE FAMILY, not by text.
            # Five documents name one GL part five ways ("Commercial General
            # Liability", "General Liability", ...) and a text-only union kept
            # all five, which is the very "different terminology read as
            # different things" the client's 1.7 is about. The first printing
            # wins, so the primary document's wording is what shows.
            # Unmappable terminology has no family and falls back to its own
            # text - it is never folded into anything (1.7, D9).
            _by_family = (list_key == "lines_of_business")
            seen: set = set()
            out: list = []
            for r in combined:
                text = re.sub(r"\s+", " ", str(r if r is not None else "")).strip()
                if not text:
                    continue
                key = (_canon_line(text) if _by_family else None) or text.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(r)
            return out
        deduped = _dedupe_schedule_rows(list_key, combined)
        if len(deduped) != len(primary_rows):
            logger.info(
                "merge list_union field=%r primary=%d companions=%d -> %d rows",
                list_key, len(primary_rows), len(merged_rows), len(deduped),
            )
        return deduped
    except Exception as exc:                              # noqa: BLE001
        logger.warning("merge_facts: list union failed for %s - %s", list_key, exc)
        return list(primary_rows)


_WC_BY_STATE_RULE = "wc_payroll_by_state_from_class_rows"


def derive_wc_facts_from_class_rows(facts: dict) -> bool:
    """V1 H3 (client 8.1 / 8.2 / 8.3): what the employee-group rows already say.

    Two things, both deterministic, both from POSITIVE evidence only:
      1. every `wc_class_codes` row is tidied (`coverage_evidence.
         normalize_wc_class_row` - "8810 Clerical" becomes code 8810 + wording;
         client 8.3 "normalize known formatting");
      2. `wc_payroll_by_state` is DERIVED as {state: summed payroll} when EVERY
         row carries both a state and a payroll - a complete table is a
         statement of payroll by state, a partial one is not (H1-F class).
         Labelled `evidence_state: derived` with its rule (E&O 5.7). Never
         overwrites a STATED value; a value this rule wrote earlier is
         re-computed, so an edited table never leaves a stale derivation.

    Called from the merge tail (documents) and from both schedule-save paths
    (a producer pre-load, a client answer), so the fact is the same whoever
    supplied the rows. Returns True when anything changed.
    """
    try:
        from services.coverage_evidence import (
            normalize_wc_class_row, wc_payroll_by_state_from_rows,
        )
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("wc row derivations unavailable: %s", exc)
        return False
    if not isinstance(facts, dict):
        return False
    raw = facts.get("wc_class_codes")
    rows = raw.get("value") if isinstance(raw, dict) and "value" in raw else raw
    if not isinstance(rows, list):
        return False
    changed = False
    for row in rows:
        if isinstance(row, dict):
            before = (row.get("code"), row.get("description"))
            normalize_wc_class_row(row)
            changed = changed or before != (row.get("code"), row.get("description"))

    existing = facts.get("wc_payroll_by_state")
    env = existing if isinstance(existing, dict) and "value" in existing else None
    stated = (existing if env is None else env.get("value"))
    ours = bool(env) and (env.get("derivation") or {}).get("rule") == _WC_BY_STATE_RULE
    if not _is_empty(stated) and not ours:
        return changed                      # a stated / human value stands
    derived = wc_payroll_by_state_from_rows(rows)
    if derived:
        if not (ours and env.get("value") == derived):
            facts["wc_payroll_by_state"] = {
                "value": derived,
                "confidence": "deterministic",
                "source": "derived",
                "evidence_state": "derived",
                "derivation": {"rule": _WC_BY_STATE_RULE, "inputs": ["wc_class_codes"]},
            }
            logger.info("derived wc_payroll_by_state=%r from the employee-group rows", derived)
            changed = True
    elif ours:
        facts["wc_payroll_by_state"] = None   # the rows no longer support it
        changed = True
    return changed


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
        # ROLE SCOPE ON THE LIST UNION (D23, client 1.2). A document only
        # contributes list facts its ROLE covers. One definition, shared with
        # every cross-document comparison - see fact_comparison._ROLE_BLIND_FACTS
        # for the measured reason `coverage_lines` is on it for a loss run.
        # Fail-open: an unknown doc_type contributes everything, so this can
        # only ever REMOVE a row, never invent one.
        try:
            from services.fact_comparison import document_witnesses as _witnesses
        except Exception:                                 # noqa: BLE001
            _witnesses = lambda _t, _k: True              # noqa: E731
        pseudo_partials = []
        for i, d in enumerate(non_primary):
            _f = d.get("facts", {}) or {}
            _dt = d.get("doc_type")
            _kept = {k: v for k, v in _f.items()
                     if k not in _LIST_FIELDS or _witnesses(_dt, k)}
            if len(_kept) != len(_f):
                logger.info("merge: %s contributes no %s (document role)",
                            d.get("filename"),
                            sorted(set(_f) - set(_kept)))
            pseudo_partials.append(
                {"facts": _kept, "flags": d.get("flags", {}), "_chunk_idx": i})
        np_merged = _merge_list_fields(pseudo_partials, list_keys=_LONG_DOC_LIST_KEYS)
        mf: dict = np_merged.get("facts", {})
        mg: dict = np_merged.get("flags", {})
    else:
        mf = {}
        mg = {}

    # Apply primary doc as legacy fallback for unmapped fields.
    #
    # A LIST FIELD IS UNIONED, NEVER REPLACED (D-1, 2026-08-23). This loop used
    # to write `mf[k] = v` for every key, so the primary document's list wiped
    # the companions' - measured on the live Run B session: `coverage_lines`
    # came out as `1_dec_page.pdf`'s four rows byte-for-byte, and Travelers'
    # General Liability, Travelers' Commercial Property and Hartford's
    # Professional Liability were simply gone. The Data Consistency picker was
    # then blamed for missing a carrier conflict it was never shown.
    #
    # The defect was already KNOWN and fixed twice, one key at a time: the
    # `dec_page_entries` block below says it in as many words - "deliberately
    # NOT routed through the primary-wins loop above: that loop would let the
    # primary doc's list REPLACE the others'" - and `risk_transfer` has its own
    # copy of the same workaround. Three list fields never got one
    # (`coverage_lines`, `lines_of_business`, `auto_covered_symbols`). Fixing
    # the loop instead of adding a fourth bespoke block is gate 1 of the change
    # quality bar: the class, not the reported case.
    #
    # The primary's rows go FIRST so anything reading "the first matching row"
    # keeps today's answer; the companions can only ADD.
    for k, v in primary.get("facts", {}).items():
        if _is_empty(v):
            continue
        _pv = v.get("value") if isinstance(v, dict) and "value" in v else v
        _mv = mf.get(k)
        if k in _LIST_FIELDS and isinstance(_pv, list) and isinstance(_mv, list) and _mv:
            mf[k] = _union_list_fact(k, _pv, _mv)
        else:
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

    # V1 H3: tidy the employee-group rows and derive payroll-by-state from
    # them - BEFORE the flag re-derivation below, which reads that fact.
    try:
        derive_wc_facts_from_class_rows(mf)
    except Exception as exc:  # noqa: BLE001 - never block the pipeline
        logger.warning("merge_facts: wc row derivations skipped: %s", exc)

    # Deterministic re-derivation of WC monopolistic / multi-state flags
    # (Decision_Tree.txt §137-150). The LLM may omit these, so we always
    # cross-check from wc_payroll_by_state keys to avoid silent fail-open.
    _MONOPOLISTIC_STATES = {"ND", "OH", "WA", "WY"}
    wc_by_state = mf.get("wc_payroll_by_state")
    if isinstance(wc_by_state, dict) and "value" in wc_by_state:
        wc_by_state = wc_by_state.get("value")           # the derived envelope
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

    # DIAGNOSTIC: the final line list every LOB premium box resolves from.
    # Live 2026-08-12: GL and Umbrella premium boxes came back blank on a run
    # where the previous run filled them, and nothing logged WHICH line names
    # the merge had kept - so the difference was invisible. One line fixes that.
    _cl = mf.get("coverage_lines")
    if isinstance(_cl, list) and _cl:
        logger.info(
            "merge coverage_lines FINAL: %s",
            [(str(e.get("line"))[:32], str(e.get("premium"))[:12],
              str(e.get("policy_number"))[:18])
             for e in _cl if isinstance(e, dict)][:14],
        )

    # risk_transfer: union across ALL docs for the same reason as the chunk-
    # level union in _merge_list_fields - the primary-wins loop above would let
    # the primary doc's (possibly empty) dict replace a companion document's
    # real AI/waiver data.
    try:
        _rt_docs = _merge_risk_transfer(
            [{"facts": d.get("facts") or {}, "_chunk_idx": i}
             for i, d in enumerate(docs)])
        if _rt_docs is not None:
            mf["risk_transfer"] = _rt_docs
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: risk_transfer union failed: %s", exc)

    # ── Dec-page entries: union across ALL docs, verify, then consume ────────
    # Deliberately NOT routed through the primary-wins loop above: that loop
    # would let the primary doc's list REPLACE the others', and a value stated
    # only on a companion policy's dec page would vanish. Union preserves
    # everything; verification then throws out anything not literally printed.
    # Failure here must never block the pipeline - entries are an enrichment.
    try:
        _all_entries: List[dict] = []
        for _d in docs:
            _lst = (_d.get("facts") or {}).get("dec_page_entries")
            if isinstance(_lst, list):
                _all_entries.extend(_lst)
        _full_text = " ".join(str(_d.get("text") or "") for _d in docs)
        _verified = _verify_dec_entries(_all_entries, _full_text)
        _canonicalise_dec_entry_keys(_verified)
        mf["dec_page_entries"] = _verified
        # Durable one-bit derivation, computed while the entries still exist:
        # the purge (C57) deletes the entries after generation, and the GL
        # exposure warning re-evaluates on every recalc - without this fact the
        # warning would stand down before generation and refire after it.
        #
        # BEFORE the backfill, deliberately: both used to sit after it inside
        # this one try block, so a single exception anywhere in the backfill
        # took the payroll flag down WITH the entries (the except clause pops
        # `dec_page_entries`) and the GL-exposure warning fired on a package
        # that plainly states its payroll. Deriving first makes the flag
        # independent of every later step.
        if _entries_state_payroll(_verified):
            mf["dec_states_payroll_basis"] = True
        _backfill_empty_facts_from_entries(mf, _verified)
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: dec-entry verification/backfill failed: %s", exc)
        mf.pop("dec_page_entries", None)
    try:
        _backfill_billing_plan(
            mf, " ".join(str(_d.get("text") or "") for _d in docs))
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: billing_plan backfill failed: %s", exc)

    # Canonical, deduplicated multi-location list (Beta Report Figure 27).
    # Must run LAST, after every chunk/doc-level merge above, so it is the
    # single final consolidation pass rather than one of several partial ones.
    try:
        _consolidate_property_locations(mf)
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: location consolidation failed: %s", exc)

    # ── Relationship repair, then renewal handling (client 2026-08-15) ───────
    # ORDER IS LOAD-BEARING:
    #   1. repair coverage_lines from the verified entries - every line-scoped
    #      stamping resolver reads that fact, so it must be correct first;
    #   2. backfill is_renewal from the document's printed wording - the two
    #      renewal behaviours below are gated on it and silently no-op without it;
    #   3. route the dates, which needs (2) to have run.
    try:
        _repair_coverage_lines_from_entries(mf)
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: coverage_lines repair failed: %s", exc)
    # A limit the merge had to CHOOSE between two different amounts for is
    # unresolved - withhold the stamped value until a human settles it. Runs
    # before the private merge bookkeeping is stripped below.
    try:
        _flag_intra_document_limit_conflicts(mf, mf.get("_merge_rejected") or {})
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: intra-document conflict check failed: %s", exc)
    mf.pop("_merge_rejected", None)
    # Absence must not read as a refusal (client 2026-08-17 item 3). Runs on the
    # merged result with the full uploaded text, so a requirement stated in ANY
    # document counts as stated for the package.
    try:
        _drop_unstated_risk_transfer(
            mf, " ".join(str(_d.get("text") or "") for _d in docs))
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: risk-transfer absence check failed: %s", exc)
    # A document's heading is not a remark. Runs BEFORE the endorsement-date
    # check, which mines the remarks - there is no point mining a page title.
    try:
        _drop_page_furniture_remarks(mf, docs)
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: page-furniture check failed: %s", exc)
    # An endorsement date is not an inception date. Runs AFTER the dec-entry
    # work above, because it asks the verified index whether the date is really
    # printed as a policy date.
    try:
        _drop_endorsement_dates_from_policy_facts(mf, docs)
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: endorsement-date check failed: %s", exc)
    try:
        _backfill_is_renewal(mf, " ".join(str(_d.get("text") or "") for _d in docs))
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: is_renewal backfill failed: %s", exc)
    try:
        _route_renewal_dates(mf)
    except Exception as exc:  # noqa: BLE001 — never block the pipeline
        logger.warning("merge_facts: renewal date routing failed: %s", exc)
    # Client 1.4 "Derived": compute what the documents already answer, so the
    # questionnaire never asks for it. Runs AFTER renewal routing so it reads
    # the settled dates.
    _derive_years_in_business(mf)
    # V1 H1 (2026-08-26): three more derivations from the verified dec index,
    # computed HERE - while the entries still exist - so they survive the C57
    # purge exactly like `dec_states_payroll_basis` does. Each is positive
    # evidence only and never overwrites a stated value.
    # BEFORE the derivations below, deliberately: they never overwrite a stated
    # value, so an INVENTED period would keep the real one from ever being
    # derived from its own label.
    try:
        _gate_inferred_payroll_period(mf, docs)
    except Exception as exc:  # noqa: BLE001 - never block the pipeline
        logger.warning("merge_facts: payroll-period gate skipped: %s", exc)
    _derive_from_dec_entries_h1(mf)

    # C1b / D19 (owner-directed): scope is STORED on the fact, not re-derived
    # at each point of use. Runs LAST, so it reads the settled `coverage_lines`
    # - after the union, after the entry repair, after renewal routing.
    _build_scoped_fact_store(mf)

    return mf, mg


def _derive_years_in_business(mf: dict) -> None:
    """Compute `years_in_business` from `business_start_date` when it is absent.

    CLIENT 1.4 "Derived": *"the value was deterministically calculated from
    supported facts using a known rule."* Live run 2026-08-21: the dec page
    printed "Date Business Started: 06/15/2014" and the questionnaire still
    asked the insured "How many years has your business been open?" - a
    question the documents already answer. Brent's own point: if the paperwork
    says it, do not ask.

    POSITIVE EVIDENCE ONLY, and never overwrites:
      * skipped entirely when years_in_business already has a value;
      * the start date must parse AND be in the past (a future date is a
        mis-extraction - the policy inception date landing in this box is a
        known defect, see the business_start_date registry note);
      * the result is floored whole years and must be sane (<= 500), the same
        bound the registry validator applies.

    Labelled `evidence_state: derived` so the E&O record shows it was computed,
    not read - a derived value must never read as source-verified.
    """
    try:
        if _fv(mf, "years_in_business"):
            return
        raw = _fv(mf, "business_start_date")
        if not raw:
            return
        iso = normalize_date(raw)
        if not iso:
            return
        from datetime import datetime as _dt
        start = _dt.strptime(iso, "%Y-%m-%d")
        now = _dt.now()
        if start > now:
            return                      # future date - a mis-extraction
        years = int((now - start).days // 365.25)
        if years < 0 or years > 500:
            return
        mf["years_in_business"] = {
            "value": str(years),
            "confidence": "deterministic",
            "source": "derived",
            "evidence_state": "derived",
            # E&O 5.7: the rule and its input facts, on the envelope itself -
            # "Source: derived does not explain how the value was produced."
            "derivation": {"rule": "years_since_business_start_date",
                           "inputs": ["business_start_date"]},
        }
        logger.info(
            "derived years_in_business=%s from business_start_date=%r - the "
            "documents answer this, so the questionnaire will not ask it",
            years, str(raw)[:40])
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("years_in_business derivation skipped: %s", exc)


_PERIOD_NAMED_SOURCES = ("producer", "client_arq", "client", "derived", "human")


def _gate_inferred_payroll_period(mf: dict, docs) -> None:
    """Drop a `wc_payroll_period` the model INFERRED rather than read.

    D43 (owner ruling 2026-08-26, answering Q21): *"'clearly annual' ... read
    from NAMED evidence, never inferred from a category ... a payroll figure is
    annual when its OWN label / source MEANS annual"*, and the -3 "fires only
    for a bare figure with no period anywhere".

    LIVE RUN 2026-08-27 (session 6a60e036): the dec index printed
    `Payroll = $210,000` - no period word anywhere in 1,877 characters - and the
    merged fact came back `wc_payroll_period = "annual"`. The extraction prompt
    already forbids exactly this in terms ("Set null when the payroll figure
    carries no period wording at all - never assume annual"); it assumed anyway.
    A prompt is not a guarantee, so the guarantee is deterministic and lives
    here. This is CLAUDE.md's documented GAP 1 - `answer_semantics` guards what
    a HUMAN types, and nothing guarded what the model extracts.

    PROVENANCE DECIDES (Principle 6). A producer or client answer IS the named
    evidence and is never gated; neither is a derived value, which was computed
    from a corroborating label to begin with. Only the model's own inference is
    stripped, and only when the document names the period nowhere.

    Dropping it invents no penalty - it hands the question back to
    `wc_payroll_period_status`, which still satisfies the check from a
    class-code schedule (D43's other half) before charging anything.
    """
    try:
        from services.coverage_evidence import payroll_period_corroborated
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("payroll-period gate unavailable: %s", exc)
        return
    env = (mf or {}).get("wc_payroll_period")
    value = env.get("value") if isinstance(env, dict) else env
    if not value:
        return
    source = str((env.get("source") if isinstance(env, dict) else "") or "").lower()
    if source in _PERIOD_NAMED_SOURCES:
        return
    entries = (mf or {}).get("dec_page_entries")
    text = " ".join(str(_d.get("text") or "") for _d in (docs or []))
    if payroll_period_corroborated(value, entries, text):
        return
    mf["wc_payroll_period"] = None
    logger.info(
        "payroll-period gate: dropped wc_payroll_period=%r - no wording in the "
        "document names that period for the payroll figure (D43). The 6.4 check "
        "now decides from the payroll's own label / class schedule.", value)


def _derive_from_dec_entries_h1(mf: dict) -> None:
    """V1 H1 (client section 6): three purge-safe derivations off the verified
    declarations index. Read by `services.coverage_evidence`, the one door the
    6.3 / 6.4 scoring, the ACORD 127 checklist and the questionnaire consult.

      * `auto_radius_of_operation` - the ONE numeric radius the auto dec
        prints (the same entry `pdf_service._resolve_vehicle_rating_cell`
        stamps onto Vehicle_RadiusOfUse), so the package can never deduct for
        a radius that is on the generated form. "RADIUS: NA" derives nothing.
      * `wc_payroll_period` = "annual" when the payroll figure's own printed
        label means annual ("Estimated Annual Payroll", "per year", "12
        months" ...) - the owner's "clearly annual by MEANING" ruling.
      * `wc_xmod` - the factor a mod-labelled entry PRINTS ("Experience
        Modification: 0.95"). The generic entry backfill cannot reach it: its
        label rule wants the key's own tokens ("wc", "xmod") in the label.
      * `wc_xmod_applicability` - "applicable" when a mod entry says pending /
        see worksheet, "not_applicable" when it says not rated / none / N/A;
        only when no factor is stated.

    Every write is labelled `evidence_state: derived` with its rule and
    inputs (E&O 5.7), and is skipped when the fact already has a value.
    """
    try:
        from services.coverage_evidence import (
            payroll_label_states_annual, radius_from_dec_entries,
            xmod_applicability_from_entries, xmod_from_entries,
        )
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("H1 dec-entry derivations unavailable: %s", exc)
        return
    entries = (mf or {}).get("dec_page_entries")
    if not isinstance(entries, list) or not entries:
        return

    def _derive(key: str, value: str, rule: str) -> None:
        if _fv(mf, key):
            return                              # never overwrite a stated value
        mf[key] = {
            "value": value,
            "confidence": "deterministic",
            "source": "derived",
            "evidence_state": "derived",
            "derivation": {"rule": rule, "inputs": ["dec_page_entries"]},
        }
        logger.info("derived %s=%r from the declarations index (%s)", key, value, rule)

    try:
        radius = radius_from_dec_entries(entries)
        if radius:
            _derive("auto_radius_of_operation", radius, "auto_dec_radius_entry")
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("radius derivation skipped: %s", exc)
    try:
        if payroll_label_states_annual(entries) and \
                (_fv(mf, "wc_payroll") or _fv(mf, "total_payroll")):
            _derive("wc_payroll_period", "annual", "payroll_label_means_annual")
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("payroll period derivation skipped: %s", exc)
    try:
        # The FACTOR first: the generic backfill cannot route "Experience
        # Modification: 0.95" to `wc_xmod` (its label rule wants the key's own
        # tokens), so the printed factor is read by the label's meaning here.
        factor = xmod_from_entries(entries)
        if factor:
            _derive("wc_xmod", factor, "experience_mod_entry_factor")
        applicability = xmod_applicability_from_entries(entries)
        if applicability and not _fv(mf, "wc_xmod"):
            _derive("wc_xmod_applicability", applicability, "experience_mod_entry_meaning")
    except Exception as exc:                                  # noqa: BLE001
        logger.warning("x-mod derivation skipped: %s", exc)


def _route_renewal_dates(mf: dict) -> None:
    """On a Renewal, an already-ENDED extracted term is the EXPIRING policy's
    term, not the term being applied for - route it to the prior_* namespace.

    Client (2026-08-15, Orbin package): ACORD 131 stamped 07/15/2025 as the
    proposed effective date because RULE 1's "current policy" IS the expiring
    dec page on a renewal, and the fact schema had no concept of "the term
    being applied for". "For a renewal, Primble needs to distinguish the
    expiring policy period from the proposed renewal period."

    Acts only on POSITIVE evidence, both conditions required:
      * the is_renewal fact is affirmative, AND
      * the extracted expiration date is in the past - a term that ended
        cannot be the term being proposed, so the assignment is provably wrong.
    A FUTURE-dated term on a renewal is left alone: it is plausibly the real
    renewal term (a renewal quote's dates). Non-renewals are never touched.

    After routing, effective_date/expiration_date are EMPTY: Tier-1 lists the
    proposed effective date as missing, the questionnaire asks for it, and
    `pdf_service._resolve_renewal_proposed_period` keeps the application
    forms' proposed-date boxes as owned blanks (gap fill excluded) until a
    human supplies the real term. Unknown stays unknown - never assumed.
    """
    if str(_fv(mf, "is_renewal") or "").strip().lower() not in (
            "yes", "y", "true", "1", "renewal", "renew"):
        return
    exp_raw = _fv(mf, "expiration_date")
    if not exp_raw:
        return
    iso = normalize_date(exp_raw)
    if not iso:
        return
    from datetime import datetime
    try:
        exp_d = datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return
    if exp_d >= datetime.now():
        return                       # future term - plausibly the renewal term
    # Move the whole stored entries (value+confidence envelope intact) into the
    # prior namespace - as a PAIR, and only when BOTH prior slots are empty.
    # Audit 2026-08-15 #7: with a genuinely-extracted prior_effective_date of
    # 07/15/2024 and no prior_expiration_date, the old per-slot guards wrote
    # the EXPIRING term's end date next to it, fabricating a 2024-2026 prior
    # term no document states. Half of one term never joins half of another;
    # a partially-known prior term stays partially known.
    if not _fv(mf, "prior_effective_date") and not _fv(mf, "prior_expiration_date"):
        if _fv(mf, "effective_date"):
            mf["prior_effective_date"] = mf.get("effective_date")
        mf["prior_expiration_date"] = mf.get("expiration_date")
    # ── DERIVE the proposed term; do NOT leave the application empty ─────────
    # First cut of this blanked both boxes and made the producer type them.
    # That was wrong in both directions: it stripped ACORD 125's PROPOSED EFF
    # DATE (a field Tier 1 requires, so it immediately re-appeared as a
    # "minimum field missing" task), and it treated a KNOWN quantity as
    # unknown. A renewal takes effect when the expiring policy ends - that is
    # what renewing means - so the proposed term is DERIVED from the document's
    # own expiring term, not invented and not guessed at.
    #
    # It carries `source="derived"` / `confidence="low_confidence"` so the E&O
    # layer highlights it for review and the producer can correct it in one
    # click, which is the client's "confirmed rather than guessed" - confirmed
    # meaning a human signs off on a stated value, not a human doing data entry
    # the document already answers.
    from datetime import timedelta
    prop_eff = exp_d
    prop_exp = None
    eff_prev = normalize_date(_fv(mf, "effective_date") or "")
    if eff_prev:
        try:
            _term_days = (exp_d - datetime.strptime(eff_prev, "%Y-%m-%d")).days
            if 300 <= _term_days <= 400:          # an ordinary annual term
                prop_exp = exp_d + timedelta(days=_term_days)
        except ValueError:
            pass
    # E&O 5.7's own worked example is exactly this value: "Proposed Effective
    # Date ... Derivation: Prior expiration date + renewal routing rule".
    mf["effective_date"] = {"value": prop_eff.strftime("%m/%d/%Y"),
                            "confidence": "low_confidence", "source": "derived",
                            "derivation": {
                                "rule": "renewal_routing_prior_expiration",
                                "inputs": ["prior_expiration_date", "is_renewal"]}}
    if prop_exp is not None:
        mf["expiration_date"] = {"value": prop_exp.strftime("%m/%d/%Y"),
                                 "confidence": "low_confidence", "source": "derived",
                                 "derivation": {
                                     "rule": "renewal_routing_prior_term_length",
                                     "inputs": ["prior_effective_date",
                                                "prior_expiration_date"]}}
    else:
        mf.pop("expiration_date", None)
        _record_fact_rejection(
            mf, "expiration_date",
            "this is a renewal and the expiring term was found, but the "
            "proposed term length is not stated anywhere")
    # ── THE PER-LINE TERMS ARE EXPIRING TOO, AND NOTHING SAID SO ─────────────
    # Client session 2026-08-16: after the false "Umbrella and GL policy
    # periods misaligned" hard stop was removed, the review screen went SILENT
    # on the umbrella term - and silence is not the right answer either. Every
    # per-line date (`umbrella_*`, `auto_*`, `wc_*`) is read off that line's
    # own DEC PAGE, so on a renewal every one of them is an EXPIRING date; the
    # routing above only ever handled the package pair, so the proposed term
    # for each underlying line stayed genuinely unknown and unannounced.
    #
    # Recorded as a fact, not a message: `renewal_lines_expiring` lists the
    # lines whose stated term has ended, and the SQS layer turns it into ONE
    # recommended, resolvable item ("confirm the proposed term"). Nothing is
    # derived here - deriving a per-line renewal term is exactly the guess the
    # client's "unknown must remain unknown" rule forbids, and the underlying
    # policies may genuinely renew on their own dates.
    _expiring_lines: List[str] = []
    for _line, _pfx in (("Umbrella", "umbrella"), ("Auto", "auto"),
                        ("Workers Compensation", "wc"), ("Property", "property")):
        _line_exp = normalize_date(_fv(mf, f"{_pfx}_expiration_date") or "")
        if not _line_exp:
            continue
        try:
            if datetime.strptime(_line_exp, "%Y-%m-%d") < datetime.now():
                _expiring_lines.append(_line)
        except ValueError:
            continue
    if _expiring_lines:
        mf["renewal_lines_expiring"] = _expiring_lines
        logger.info(
            "merge_facts: RENEWAL - %d underlying line(s) carry an EXPIRED "
            "stated term (%s); their proposed terms are unknown and will be "
            "asked for, never derived", len(_expiring_lines),
            ", ".join(_expiring_lines),
        )
    # Plain bool, not an envelope: consumed by the stamping-layer resolver and
    # excluded from the auto-scalar reconciliation sweep (bools are skipped).
    mf["renewal_dates_routed"] = True
    logger.info(
        "merge_facts: RENEWAL date routing - expiring term (%s) moved to "
        "prior_effective/expiration_date; proposed term DERIVED as %s to %s "
        "(flagged for producer confirmation)", iso,
        mf["effective_date"]["value"],
        (mf.get("expiration_date") or {}).get("value", "(unset)"),
    )
