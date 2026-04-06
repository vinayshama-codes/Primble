import json
import logging
from typing import List, Tuple, Dict

from config.settings import groq_client

logger = logging.getLogger(__name__)

DOC_TYPE_KEYWORDS = {
    "dec_page":    ["declarations", "dec page", "policy declarations", "named insured",
                    "policy period", "coverage summary", "insuring agreement", "policy number"],
    "certificate": ["certificate of liability", "certificate of insurance", "acord 25",
                    "certificate holder", "evidence of insurance", "this is to certify"],
    "loss_run":    ["loss run", "loss history", "incurred", "reserve", "paid losses", "claimant", "date of loss"],
    "schedule":    ["schedule of", "vehicle schedule", "equipment schedule", "location schedule", "driver schedule"],
    "quote":       ["quote", "proposal", "indication", "estimated premium", "quoted premium"],
    "application": ["application", "acord 125", "acord 126", "acord 130", "prior application"],
    "endorsement": ["endorsement", "additional insured", "waiver of subrogation", "mortgagee"],
}


def identify_doc_type(text: str) -> str:
    tl     = text.lower()
    scores = {dt: sum(1 for kw in kws if kw in tl) for dt, kws in DOC_TYPE_KEYWORDS.items()}
    best   = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def select_primary_truth(docs: List[dict]) -> dict:
    priority = ["dec_page", "application", "quote", "schedule", "endorsement", "certificate", "loss_run", "unknown"]
    by_type  = {}
    for d in docs:
        by_type.setdefault(d["doc_type"], d)
    for p in priority:
        if p in by_type:
            return by_type[p]
    return docs[0]


def extract_facts(text: str) -> dict:
    if len(text) < 30:
        return {"facts": {}, "flags": {}}
    prompt = (
        'You are a carrier-grade insurance document analyzer. Extract every available data point.\n\n'
        'Return ONLY a valid JSON object with exactly these two top-level keys:\n\n'
        '"facts": {\n'
        '  "producer_name": string or null, "applicant_name": string or null,\n'
        '  "dba_name": string or null, "mailing_address": string or null,\n'
        '  "physical_address": string or null, "contact_name": string or null,\n'
        '  "contact_phone": string or null, "contact_email": string or null,\n'
        '  "fein": string or null, "entity_type": string or null,\n'
        '  "effective_date": string or null, "expiration_date": string or null,\n'
        '  "policy_number": string or null, "lines_of_business": [],\n'
        '  "total_revenue": string or null, "total_payroll": string or null,\n'
        '  "num_employees": string or null, "locations": [],\n'
        '  "operations_description": string or null, "prior_carrier": string or null,\n'
        '  "naics_code": string or null, "sic_code": string or null,\n'
        '  "years_in_business": string or null,\n'
        '  "gl_limits": string or null, "gl_aggregate": string or null,\n'
        '  "gl_each_occurrence": string or null, "gl_class_codes": [],\n'
        '  "gl_deductible": string or null, "gl_form_type": string or null,\n'
        '  "retro_date": string or null, "additional_insured": string or null,\n'
        '  "property_building_value": string or null, "property_bpp_value": string or null,\n'
        '  "construction_type": string or null, "occupancy_type": string or null,\n'
        '  "year_built": string or null, "roof_year": string or null,\n'
        '  "sprinkler_system": string or null, "fire_protection_class": string or null,\n'
        '  "valuation_method": string or null, "coinsurance_percentage": string or null,\n'
        '  "business_income_limit": string or null, "period_of_restoration": string or null,\n'
        '  "property_deductible_aop": string or null, "property_deductible_wind": string or null,\n'
        '  "property_deductible_earthquake": string or null, "property_deductible_flood": string or null,\n'
        '  "mortgagee_name": string or null, "auto_liability_limit": string or null,\n'
        '  "auto_liability_structure": string or null, "auto_deductible_comp": string or null,\n'
        '  "auto_deductible_collision": string or null, "auto_vin_schedule": [], "auto_garaging_addresses": [],\n'
        '  "wc_payroll": string or null, "wc_payroll_by_state": {}, "wc_class_codes": [],\n'
        '  "wc_xmod": string or null, "wc_officer_exclusions": string or null,\n'
        '  "umbrella_limit": string or null, "umbrella_sir": string or null,\n'
        '  "umbrella_attachment_point": string or null, "percent_subcontracted": string or null,\n'
        '  "contractor_type": string or null, "num_claims": string or null,\n'
        '  "loss_history_years": string or null, "certificate_holder": string or null\n'
        '},\n\n'
        '"flags": {\n'
        '  "is_commercial_policy": boolean, "has_general_liability": boolean,\n'
        '  "has_property_coverage": boolean, "has_auto_coverage": boolean,\n'
        '  "has_workers_comp": boolean, "has_umbrella": boolean,\n'
        '  "has_multiple_locations": boolean, "has_loss_history": boolean,\n'
        '  "is_contractor": boolean, "has_certificate_request": boolean,\n'
        '  "is_certificate_doc": boolean, "gl_is_claims_made": boolean,\n'
        '  "auto_has_physical_damage": boolean, "auto_split_limits": boolean,\n'
        '  "wc_multi_state": boolean, "wc_has_monopolistic_state": boolean,\n'
        '  "property_has_bi_coverage": boolean, "property_has_peril_deductibles": boolean\n'
        '}\n\n'
        'Return ONLY the JSON object, no markdown, no extra text.\n\n'
        f'Text:\n"""\n{text[:7000]}\n"""'
    )
    try:
        r   = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = (r.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e != -1:
            raw = raw[s : e + 1]
        return json.loads(raw)
    except Exception as ex:
        logger.error(f"Facts extraction error: {ex}")
        return {"facts": {}, "flags": {}}


def merge_facts(docs: List[dict], primary: dict) -> Tuple[dict, dict]:
    mf, mg = {}, {}
    for d in docs:
        if d["filename"] != primary["filename"]:
            mf.update({k: v for k, v in d["facts"].items() if v})
            mg.update({k: v for k, v in d["flags"].items() if v})
    mf.update({k: v for k, v in primary["facts"].items() if v})
    mg.update({k: v for k, v in primary["flags"].items() if v})
    return mf, mg