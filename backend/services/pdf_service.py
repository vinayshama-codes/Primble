import io
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import pikepdf
from PIL import Image
from fastapi import HTTPException

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_SCHEMAS_DIR, groq_chat
from utils.helpers import _parse_address
from typing import NamedTuple
from services.extraction_service import _fv, ACTIVE_MODEL
from services.fact_registry import FACT_REGISTRY

logger = logging.getLogger(__name__)

# ── GPT model config — env-driven so any OpenAI model is selectable with zero code changes ──
GPT_MODEL       = os.getenv("GPT_MODEL",       "gpt-4o-mini")
GPT_BATCH_SIZE  = int(os.getenv("GPT_BATCH_SIZE",  "80"))
GPT_TEMPERATURE = float(os.getenv("GPT_TEMPERATURE", "0.0"))

# ── Dedicated OpenAI client for form-fill GPT pass (lazy-initialised) ────────
# Client is created on first use so Pass 1 deterministic fills work without
# OPENAI_API_KEY being present.
try:
    from openai import AsyncOpenAI as _AsyncOpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    logger.warning("openai package not installed — GPT form fill pass disabled")

_openai_form_fill_client = None


def _get_openai_form_fill_client():
    global _openai_form_fill_client
    if _openai_form_fill_client is None:
        if not _HAS_OPENAI:
            raise RuntimeError("openai package not installed — install it with: pip install openai")
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — GPT form-fill pass unavailable. "
                "Set OPENAI_API_KEY in your .env file."
            )
        _openai_form_fill_client = _AsyncOpenAI(api_key=api_key)
    return _openai_form_fill_client

# ── PII fields excluded from LLM prompts (SOC2 / data minimisation) ──────────
# These fields are handled deterministically by Pass 1 (_ACORD_FIELD_RULES +
# _resolve_special) and must never be forwarded to external LLM providers.
# mailing_address / physical_address are decomposed by _resolve_special() into
# line1/line2/city/state/zip — GPT has no need for the raw concatenated string.
_PII_EXCLUDE_KEYS: frozenset = frozenset({
    "fein",              # federal tax ID — highest-sensitivity financial identifier
    "contact_phone",     # personal phone number
    "contact_email",     # personal email address
    "mailing_address",   # full street address — decomposed by Pass 1
    "physical_address",  # full street address — decomposed by Pass 1
})

# ── Canonical valid fact-key set (full registry, not just current document) ───
# Used to validate GPT-returned new_mappings keys and reject hallucinations.
# A key absent from the CURRENT document's facts is still a valid structural
# mapping (e.g. wc_payroll is valid even in a GL-only submission).
_FULL_REGISTRY_KEYS: frozenset = frozenset(FACT_REGISTRY.keys()) | frozenset({
    "_addr_line1", "_addr_line2", "_addr_city", "_addr_state", "_addr_zip",
    "_loc_line1",  "_loc_line2",  "_loc_city",  "_loc_state",  "_loc_zip",
})

# ── Schedule row expansion ────────────────────────────────────────────────────
# Maps AcroForm field base-name prefixes to the list fact that backs them.
# Fields with row suffix _A/_B/..._N are resolved to list[idx] automatically.

_ROW_LETTER_TO_IDX: Dict[str, int] = {chr(ord("A") + i): i for i in range(14)}

_SCHED_SKIP = object()  # sentinel: not a schedule field → fall through to regular rules


class _ScheduleDef(NamedTuple):
    list_key: str            # fact dict key that holds the list
    sub_key: Optional[str]   # dict sub-key to extract; None = use item directly
    row_offset: int = 0      # subtract from letter-index before list lookup


_SCHEDULE_REGISTRY: Dict[str, "_ScheduleDef"] = {
    # ── Vehicles (ACORD 127) ────────────────────────────────────────────────
    "Vehicle_ModelYear":             _ScheduleDef("auto_vin_schedule", "year"),
    "Vehicle_Year":                  _ScheduleDef("auto_vin_schedule", "year"),
    "Vehicle_Make":                  _ScheduleDef("auto_vin_schedule", "make"),
    "Vehicle_Model":                 _ScheduleDef("auto_vin_schedule", "model"),
    "Vehicle_VINNumber":             _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_VIN":                   _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_BodyStyle":             _ScheduleDef("auto_vin_schedule", "body_type"),
    "Vehicle_BodyType":              _ScheduleDef("auto_vin_schedule", "body_type"),
    "Vehicle_GrossVehicleWeight":    _ScheduleDef("auto_vin_schedule", "gvw"),
    "Vehicle_GVW":                   _ScheduleDef("auto_vin_schedule", "gvw"),
    "Vehicle_GaragingAddress":       _ScheduleDef("auto_garaging_addresses", None),

    # ── Drivers (ACORD 127) ─────────────────────────────────────────────────
    "Driver_FullName":               _ScheduleDef("auto_drivers", "name"),
    "Driver_GivenName":              _ScheduleDef("auto_drivers", "name"),
    "Driver_BirthDate":              _ScheduleDef("auto_drivers", "dob"),
    "Driver_LicenseNumber":          _ScheduleDef("auto_drivers", "license_number"),
    "Driver_LicenseStateOrProvince": _ScheduleDef("auto_drivers", "license_state"),

    # ── WC Class Codes (ACORD 130) ──────────────────────────────────────────
    "WorkersCompensation_ClassCode":        _ScheduleDef("wc_class_codes", "code"),
    "WorkersCompensation_ClassDescription": _ScheduleDef("wc_class_codes", "description"),
    "WorkersCompensation_ClassPayroll":     _ScheduleDef("wc_class_codes", "payroll"),
    "WorkersCompensation_ClassState":       _ScheduleDef("wc_class_codes", "state"),
    "WorkersCompensation_ClassRate":        _ScheduleDef("wc_class_codes", "rate"),

    # ── WC Officers / Owners (ACORD 130) ───────────────────────────────────
    "Officer_FullName":              _ScheduleDef("wc_officers", "name"),
    "Officer_Title":                 _ScheduleDef("wc_officers", "title"),
    "Officer_OwnershipPercent":      _ScheduleDef("wc_officers", "ownership_pct"),
    "Officer_IncludeIndicator":      _ScheduleDef("wc_officers", "include"),
    "Officer_ExcludeIndicator":      _ScheduleDef("wc_officers", "exclude"),
    "Owner_FullName":                _ScheduleDef("wc_officers", "name"),
    "Owner_Title":                   _ScheduleDef("wc_officers", "title"),
    "Owner_OwnershipPercent":        _ScheduleDef("wc_officers", "ownership_pct"),

    # ── Additional Named Insureds (ACORD 125) ────────────────────────────────
    # row_offset=1: _A is the primary insured scalar, _B onward are additional
    "AdditionalInsured_FullName":    _ScheduleDef("additional_named_insureds", None),

    # ── Underlying Policies (ACORD 131) ─────────────────────────────────────
    "UnderlyingPolicy_TypeOfInsurance":  _ScheduleDef("underlying_policies", "line"),
    "UnderlyingPolicy_Line":             _ScheduleDef("underlying_policies", "line"),
    "UnderlyingPolicy_LimitAmount":      _ScheduleDef("underlying_policies", "limit"),
    "UnderlyingPolicy_Limit":            _ScheduleDef("underlying_policies", "limit"),
    "UnderlyingPolicy_InsuranceCarrier": _ScheduleDef("underlying_policies", "carrier"),
    "UnderlyingPolicy_Carrier":          _ScheduleDef("underlying_policies", "carrier"),
    "UnderlyingPolicy_PolicyNumber":     _ScheduleDef("underlying_policies", "policy_no"),

    # ── Loss History (ACORD 125) ─────────────────────────────────────────────
    "LossHistory_OccurrenceDate":    _ScheduleDef("loss_history", "date"),
    "LossHistory_LossDescription":   _ScheduleDef("loss_history", "description"),
    "LossHistory_Description":       _ScheduleDef("loss_history", "description"),
    "LossHistory_TotalIncurred":     _ScheduleDef("loss_history", "amount"),
    "LossHistory_AmountPaid":        _ScheduleDef("loss_history", "paid"),
    "LossHistory_ClaimNumber":       _ScheduleDef("loss_history", "claim_number"),
    "LossHistory_OpenIndicator":     _ScheduleDef("loss_history", "open"),

    # ── Prior Coverage by Line (ACORD 125/126/127/130) ───────────────────────
    "PriorCoverage_TypeOfInsurance": _ScheduleDef("prior_coverage_by_line", "line"),
    "PriorCoverage_InsuranceCarrier":_ScheduleDef("prior_coverage_by_line", "carrier"),
    "PriorCoverage_PolicyNumber":    _ScheduleDef("prior_coverage_by_line", "policy_no"),
    "PriorCoverage_EffectiveDate":   _ScheduleDef("prior_coverage_by_line", "effective"),
    "PriorCoverage_ExpirationDate":  _ScheduleDef("prior_coverage_by_line", "expiration"),
    "PriorCoverage_Premium":         _ScheduleDef("prior_coverage_by_line", "premium"),

    # ── Property Locations (ACORD 140) ──────────────────────────────────────
    "PropertyLocation_StreetAddress":    _ScheduleDef("property_locations", "address"),
    "PropertyLocation_BuildingValue":    _ScheduleDef("property_locations", "building_value"),
    "PropertyLocation_BPPValue":         _ScheduleDef("property_locations", "bpp_value"),
    "PropertyLocation_ConstructionType": _ScheduleDef("property_locations", "construction_type"),
    "PropertyLocation_YearBuilt":        _ScheduleDef("property_locations", "year_built"),

    # ── GL Class Codes by Location (ACORD 126) ───────────────────────────────
    "GL_LocationClassCode":          _ScheduleDef("gl_class_codes_by_location", "codes"),
    "GL_ClassCode":                  _ScheduleDef("gl_class_codes_by_location", "codes"),
    "GL_Location":                   _ScheduleDef("gl_class_codes_by_location", "location"),

    # ── Inland Marine Items (ACORD 160) ─────────────────────────────────────
    "InlandMarine_ItemDescription":  _ScheduleDef("inland_marine_items", "description"),
    "InlandMarine_ItemValue":        _ScheduleDef("inland_marine_items", "value"),
    "InlandMarine_SerialNumber":     _ScheduleDef("inland_marine_items", "serial_number"),
}

_SCHED_ROW_RE = re.compile(r"^(.+)_([A-N])$")


def _resolve_schedule_row(field_name: str, facts: dict):
    """Resolve a repeating-row field (e.g. Vehicle_Year_B) to its list-indexed value.

    Returns _SCHED_SKIP  — not a schedule field; caller falls through to regular rules.
    Returns None         — schedule field but list is shorter than row index (leave blank).
    Returns str          — resolved value for this row.
    """
    m = _SCHED_ROW_RE.match(field_name)
    if not m:
        return _SCHED_SKIP

    base   = m.group(1)
    letter = m.group(2)
    idx    = _ROW_LETTER_TO_IDX[letter]

    # Exact base match first, then longest-prefix match in registry
    defn = _SCHEDULE_REGISTRY.get(base)
    if defn is None:
        for prefix, d in _SCHEDULE_REGISTRY.items():
            if base == prefix or base.startswith(prefix + "_") or base.endswith("_" + prefix):
                defn = d
                break

    if defn is None:
        return _SCHED_SKIP

    list_idx = idx - defn.row_offset
    if list_idx < 0:
        return _SCHED_SKIP  # this letter belongs to scalar rules (row_offset guard)

    items = _fv(facts, defn.list_key)
    if not isinstance(items, list) or list_idx >= len(items):
        logger.debug(
            f"schedule_row: field={field_name!r} list={defn.list_key!r} "
            f"idx={list_idx} list_len={len(items) if isinstance(items, list) else 0} — blank"
        )
        return None  # list shorter than requested row → leave blank

    item = items[list_idx]
    if defn.sub_key is None:
        return str(item) if item is not None else None
    if isinstance(item, dict):
        val = item.get(defn.sub_key)
        if isinstance(val, bool):
            return "Yes" if val else "No"
        return str(val) if val is not None else None
    return str(item) if item is not None else None


def _is_schedule_field(field_name: str) -> bool:
    """Return True if this field belongs to _resolve_schedule_row() — not GPT.

    Reuses the exact same detection logic as Pass 1 so the two stays in sync.
    With empty facts the schedule resolver returns _SCHED_SKIP (not a schedule
    field) or None (out-of-range row) — either way, _SCHED_SKIP means GPT-eligible.
    """
    result = _resolve_schedule_row(field_name, {})
    return result is not _SCHED_SKIP


_ACORD_FIELD_RULES = [
    # ── Producer ────────────────────────────────────────────────────────────
    ("Producer_FullName",                                  "producer_name"),
    ("Producer_CustomerIdentifier",                        "producer_name"),
    ("Producer_ContactPerson_FullName",                    "contact_name"),
    ("Producer_ContactPerson_Phone",                       "contact_phone"),
    ("Producer_ContactPerson_Email",                       "contact_email"),
    ("Producer_MailingAddress_LineOne",                    "_addr_line1"),
    ("Producer_MailingAddress_LineTwo",                    "_addr_line2"),
    ("Producer_MailingAddress_CityName",                   "_addr_city"),
    ("Producer_MailingAddress_StateOrProv",                "_addr_state"),
    ("Producer_MailingAddress_PostalCode",                 "_addr_zip"),
    ("Producer_FaxNumber",                                 None),   # not in extraction schema
    ("Producer_AuthorizedRepresentative",                  "contact_name"),

    # ── Named insured ───────────────────────────────────────────────────────
    ("NamedInsured_FullName",                              "applicant_name"),
    ("NamedInsured_DBAName",                               "dba_name"),
    ("NamedInsured_TradeName",                             "dba_name"),
    ("NamedInsured_FEIN",                                  "fein"),
    ("NamedInsured_TaxIdentifier",                         "fein"),
    ("NamedInsured_EntityType",                            "entity_type"),
    ("NamedInsured_BusinessEntity",                        "entity_type"),
    ("NamedInsured_YearsInBusiness",                       "years_in_business"),
    ("NamedInsured_BusinessDescription",                   "operations_description"),
    ("NamedInsured_OperationsDescription",                 "operations_description"),
    ("NamedInsured_SICCode",                               "sic_code"),
    ("NamedInsured_NAICSCode",                             "naics_code"),
    ("NamedInsured_MailingAddress_LineOne",                "_addr_line1"),
    ("NamedInsured_MailingAddress_LineTwo",                "_addr_line2"),
    ("NamedInsured_MailingAddress_CityName",               "_addr_city"),
    ("NamedInsured_MailingAddress_StateOrProv",            "_addr_state"),
    ("NamedInsured_MailingAddress_PostalCode",             "_addr_zip"),
    ("NamedInsured_PhysicalAddress_LineOne",               "_loc_line1"),
    ("NamedInsured_PhysicalAddress_LineTwo",               "_loc_line2"),
    ("NamedInsured_PhysicalAddress_CityName",              "_loc_city"),
    ("NamedInsured_PhysicalAddress_StateOrProv",           "_loc_state"),
    ("NamedInsured_PhysicalAddress_PostalCode",            "_loc_zip"),
    ("NamedInsured_PhoneNumber",                           "contact_phone"),
    ("NamedInsured_Primary_PhoneNumber",                   "contact_phone"),
    ("NamedInsured_EmailAddress",                          "contact_email"),
    ("NamedInsured_WebsiteAddress",                        None),   # not in extraction schema
    ("NamedInsured_BusinessStartDate",                     "years_in_business"),
    # Named insured contact sub-fields (ACORD 125 contact section)
    ("NamedInsured_Contact_FullName",                      "contact_name"),
    ("NamedInsured_Contact_PrimaryPhoneNumber",            "contact_phone"),
    ("NamedInsured_Contact_PrimaryEmailAddress",           "contact_email"),
    ("NamedInsured_NumberOfEmployees",                     "num_employees"),
    ("NamedInsured_AnnualRevenue",                         "total_revenue"),
    ("NamedInsured_AnnualPayroll",                         "total_payroll"),

    # ── Prior / previous coverage — MUST map to prior_* keys, NOT current policy keys ──
    ("PriorCarrier_FullName",                              "prior_carrier"),
    ("PriorCoverage_InsuranceCarrierName",                 "prior_carrier"),
    ("PriorCoverage_PolicyNumberIdentifier",               "prior_policy_number"),
    ("PriorCoverage_EffectiveDate",                        "prior_effective_date"),
    ("PriorCoverage_ExpirationDate",                       "prior_expiration_date"),
    ("PriorCoverage_NAICCode",                             "prior_carrier_naic"),
    ("PreviousCarrier_FullName",                           "prior_carrier"),
    ("PreviousPolicy_PolicyNumber",                        "prior_policy_number"),
    ("PreviousPolicy_EffectiveDate",                       "prior_effective_date"),
    ("PreviousPolicy_ExpirationDate",                      "prior_expiration_date"),
    # Per-line prior coverage rows (ACORD 125 prior coverage section)
    ("PriorCoverage_GeneralLiability_InsurerFullName",     "prior_carrier"),
    ("PriorCoverage_GeneralLiability_PolicyNumberIdentifier", "prior_policy_number"),
    ("PriorCoverage_GeneralLiability_EffectiveDate",       "prior_effective_date"),
    ("PriorCoverage_GeneralLiability_ExpirationDate",      "prior_expiration_date"),
    ("PriorCoverage_Automobile_InsurerFullName",           "prior_carrier"),
    ("PriorCoverage_Automobile_PolicyNumberIdentifier",    "prior_policy_number"),
    ("PriorCoverage_Automobile_EffectiveDate",             "prior_effective_date"),
    ("PriorCoverage_Automobile_ExpirationDate",            "prior_expiration_date"),
    ("PriorCoverage_Property_InsurerFullName",             "prior_carrier"),
    ("PriorCoverage_Property_PolicyNumberIdentifier",      "prior_policy_number"),
    ("PriorCoverage_Property_EffectiveDate",               "prior_effective_date"),
    ("PriorCoverage_Property_ExpirationDate",              "prior_expiration_date"),
    ("PriorCoverage_OtherLine_InsurerFullName",            "prior_carrier"),
    ("PriorCoverage_OtherLine_PolicyNumberIdentifier",     "prior_policy_number"),
    ("PriorCoverage_OtherLine_EffectiveDate",              "prior_effective_date"),
    ("PriorCoverage_OtherLine_ExpirationDate",             "prior_expiration_date"),

    # ── Business information ─────────────────────────────────────────────────
    ("BusinessInformation_NAICSCode",                      "naics_code"),
    ("BusinessInformation_SICCode",                        "sic_code"),
    ("BusinessInformation_YearsInBusiness",                "years_in_business"),
    ("BusinessInformation_NumberOfEmployees",              "num_employees"),
    ("BusinessInformation_FullTimeEmployeeCount",          "num_employees"),
    ("BusinessInformation_PartTimeEmployeeCount",          "num_employees"),
    ("BusinessInformation_AnnualRevenue",                  "total_revenue"),
    ("CommercialPolicy_OperationsDescription",             "operations_description"),
    ("CommercialPolicy_AuditPeriod",                       "audit_period"),
    ("CommercialPolicy_BillingPlan",                       "billing_plan"),
    ("Policy_AuditPeriod",                                 "audit_period"),
    ("Policy_BillingPlan",                                 "billing_plan"),

    # ── Policy / form header ─────────────────────────────────────────────────
    ("Policy_PolicyNumberIdentifier",                      "policy_number"),
    ("Policy_EffectiveDate",                               "effective_date"),
    ("Policy_ExpirationDate",                              "expiration_date"),
    ("Policy_GeneralLiability_PolicyNumberIdentifier",     "policy_number"),
    ("Policy_GeneralLiability_EffectiveDate",              "effective_date"),
    ("Policy_GeneralLiability_ExpirationDate",             "expiration_date"),
    ("Policy_AutomobileLiability_PolicyNumberIdentifier",  "policy_number"),
    ("Policy_AutomobileLiability_EffectiveDate",           "effective_date"),
    ("Policy_AutomobileLiability_ExpirationDate",          "expiration_date"),
    ("Policy_ExcessLiability_PolicyNumberIdentifier",      "policy_number"),
    ("Policy_ExcessLiability_EffectiveDate",               "effective_date"),
    ("Policy_ExcessLiability_ExpirationDate",              "expiration_date"),
    ("Policy_WorkersCompensation",                         "policy_number"),
    ("OtherPolicy_PolicyNumberIdentifier",                 "policy_number"),
    ("OtherPolicy_PolicyEffectiveDate",                    "effective_date"),
    ("OtherPolicy_PolicyExpirationDate",                   "expiration_date"),
    ("Form_CompletionDate",                                "effective_date"),
    ("Form_EditionIdentifier",                             None),
    ("CertificateOfInsurance_CertificateNumberIdentifier", "policy_number"),
    ("CertificateOfInsurance_RevisionNumber",              None),

    # ── Insurer ──────────────────────────────────────────────────────────────
    ("Insurer_FullName",                                   "carrier_name"),
    ("Insurer_NAICCode",                                   "carrier_naic"),
    ("_InsurerLetterCode",                                 None),

    # ── General liability — most-specific rules FIRST to prevent prefix shadowing ──
    ("GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount", "gl_fire_damage_limit"),
    ("GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount", "gl_products_aggregate"),
    ("GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount", "gl_personal_advertising_injury"),
    ("GeneralLiability_MedicalExpense_EachPersonLimitAmount",     "gl_medical_expense"),
    ("GeneralLiability_EachOccurrence_LimitAmount",        "gl_each_occurrence"),
    ("GeneralLiability_EachOccurrence",                    "gl_each_occurrence"),
    ("EachOccurrence",                                     "gl_each_occurrence"),
    ("GeneralLiability_GeneralAggregate_LimitAmount",      "gl_aggregate"),
    ("GeneralLiability_GeneralAggregate",                  "gl_aggregate"),
    ("GeneralLiability_Aggregate",                         "gl_aggregate"),
    ("GeneralAggregate",                                   "gl_aggregate"),
    ("GeneralLiability_OtherCoverageLimitAmount",          "gl_deductible"),
    ("GeneralLiability_PropertyDamage_DeductibleAmount",   "gl_deductible"),
    ("GeneralLiability_BodilyInjury_DeductibleAmount",     "gl_deductible"),
    ("GeneralLiability_OtherDeductibleAmount",             "gl_deductible"),
    ("GeneralLiability_ClaimsMadeIndicator",               "gl_form_type"),
    ("GeneralLiability_OccurrenceIndicator",               "gl_form_type"),
    ("GeneralLiability_ClaimsMade_ProposedRetroactiveDate","retro_date"),
    ("GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate", "retro_date"),
    ("GeneralLiability_RetroactiveDate",                   "retro_date"),
    ("GeneralLiability_EmployeeBenefits_EmployeeCount",    "num_employees"),
    # GL indicators / admin checkboxes → null
    ("GeneralLiability_CoverageIndicator",                 None),
    ("GeneralLiability_OwnersAndContractors",              None),
    ("GeneralLiability_OtherCoverageIndicator",            None),
    ("GeneralLiability_OtherCoverageDescription",          None),
    ("GeneralLiability_DeductiblePerClaim",                None),
    ("GeneralLiability_DeductiblePerOccurrence",           None),
    ("GeneralLiability_UninsuredUnderinsured",             None),
    ("GeneralLiability_MedicalPayments_Coverage",          None),
    ("GeneralLiabilityLineOfBusiness_Question_",           None),
    ("GeneralLiabilityLineOfBusiness_Attachment_",         None),
    ("GeneralLiabilityLineOfBusiness_Total",               None),
    ("GeneralLiabilityLineOfBusiness_RemarkText",          None),
    ("GeneralLiabilityLineOfBusiness_TypeOfWork",          None),
    ("GeneralLiability_Hazard_Location",                   None),
    ("GeneralLiability_Hazard_Hazard",                     None),
    ("GeneralLiability_Hazard_PremiumBasis",               None),
    ("GeneralLiability_Hazard_Territory",                  None),
    ("GeneralLiability_Hazard_PremisesOperationsRate",     None),
    ("GeneralLiability_Hazard_ProductsRate",               None),
    ("GeneralLiability_Hazard_PremisesOperationsPremium",  None),
    ("GeneralLiability_Hazard_ProductsPremium",            None),
    ("GeneralLiability_Hazard_Exposure",                   None),
    ("GeneralLiability_Hazard_ClassCode",                  None),
    ("GeneralLiability_Hazard_Classification",             None),
    ("GeneralLiability_PremisesOperations_Premium",        None),
    ("GeneralLiability_Products_Premium",                  None),
    ("GeneralLiability_OtherCoveragePremium",              None),
    ("GeneralLiability_PropertyDamage_DeductibleIndicator",None),
    ("GeneralLiability_BodilyInjury_DeductibleIndicator",  None),
    ("GeneralLiability_OtherDeductibleIndicator",          None),
    ("GeneralLiability_GeneralAggregate_LimitApplies",     None),
    ("GeneralLiability_UninsuredUnderinsuredMotorists",    None),
    ("GeneralLiability_EmployeeBenefits_PerClaim",         None),
    ("GeneralLiability_EmployeeBenefits_EmployeeCovered",  None),
    ("GeneralLiability_EmployeeBenefits_Retroactive",      None),
    ("GeneralLiability_EmployeeBenefits_LimitAmount",      None),
    ("GeneralLiability_Otherlodging",                      None),

    # ── Commercial property / structure ─────────────────────────────────────
    ("CommercialProperty_Premises_LimitAmount",            "property_building_value"),
    ("CommercialProperty_Premises_CoinsurancePercent",     "coinsurance_percentage"),
    ("CommercialProperty_Premises_ValuationCode",          "valuation_method"),
    ("CommercialProperty_Premises_DeductibleAmount",       "property_deductible_aop"),
    ("CommercialProperty_Premises_DeductibleTypeCode",     None),
    ("CommercialProperty_Premises_SubjectOfInsuranceCode", None),
    ("CommercialProperty_Premises_CauseOfLossCode",        None),
    ("CommercialProperty_Premises_InflationGuardPercent",  None),
    ("CommercialProperty_Premises_BlanketNumber",          None),
    ("CommercialProperty_Premises_FormsAndConditions",     None),
    ("CommercialProperty_Premises_RemarkText",             None),
    ("CommercialProperty_Premises_Breakdown",              None),
    ("CommercialProperty_Premises_PowerOutage",            None),
    ("CommercialProperty_Premises_SellingPrice",           None),
    ("CommercialProperty_Premises_OtherIndicator",         None),
    ("CommercialProperty_Premises_OptionsDescription",     None),
    ("CommercialProperty_Summary_BlanketNumber",           None),
    ("CommercialProperty_Summary_BlanketLimit",            None),
    ("CommercialCoverage_Summary_BlanketType",             None),
    ("CommercialProperty_Spoilage_",                       None),
    ("CommercialProperty_Attachment_",                     None),
    ("CommercialPropertyCoverage_SinkHole",                None),
    ("CommercialPropertyCoverage_MineSubsidence",          None),
    ("CommercialStructure_BuiltYear",                      "year_built"),
    ("CommercialStructure_YearBuilt",                      "year_built"),
    ("CommercialStructure_Roof_Year",                      "roof_year"),
    ("CommercialStructure_Construction_TypeCode",          "construction_type"),
    ("CommercialStructure_Occupancy",                      "occupancy_type"),
    ("CommercialStructure_PhysicalAddress_LineOne",        "_loc_line1"),
    ("CommercialStructure_PhysicalAddress_LineTwo",        "_loc_line2"),
    ("CommercialStructure_PhysicalAddress_CityName",       "_loc_city"),
    ("CommercialStructure_PhysicalAddress_StateOrProv",    "_loc_state"),
    ("CommercialStructure_PhysicalAddress_PostalCode",     "_loc_zip"),
    ("CommercialStructure_Location_ProducerIdentifier",    None),
    ("CommercialStructure_Building_ProducerIdentifier",    None),
    ("CommercialStructure_Building_Sublocation",           None),
    ("CommercialStructure_TaxCode",                        None),
    ("CommercialStructure_WindClass_",                     None),
    ("CommercialStructure_PrimaryHeat_",                   None),
    ("CommercialStructure_SecondaryHeat_",                 None),
    ("CommercialStructure_HeatingBoiler",                  None),
    ("Construction_ConstructionCode",                      "construction_type"),
    ("Construction_OpenSidesCount",                        None),
    ("Construction_StoreyCount",                           None),
    ("Construction_BasementCount",                         None),
    ("Construction_BuildingArea",                          None),
    ("Construction_BuildingCodeEffectiveness",             None),
    ("Construction_RoofMaterialCode",                      None),

    # ── Building features / protection ──────────────────────────────────────
    ("BuildingFireProtection_HydrantDistanceFeetCount",    "distance_to_hydrant"),
    ("BuildingFireProtection_FireStationDistanceMile",     None),
    ("BuildingFireProtection_FireDistrictName",            None),
    ("BuildingFireProtection_FireDistrictCode",            None),
    ("BuildingFireProtection_ProtectionClassCode",         "fire_protection_class"),
    ("BuildingFireProtection_Alarm_SprinklerPercent",      "sprinkler_system"),
    ("BuildingFireProtection_Alarm_ManufacturerName",      None),
    ("BuildingFireProtection_Alarm_CentralStation",        None),
    ("BuildingFireProtection_Alarm_LocalGong",             None),
    ("BuildingFireProtection_Alarm_ProtectionDescription", None),
    ("BuildingImprovement_WiringYear",                     None),
    ("BuildingImprovement_WiringIndicator",                None),
    ("BuildingImprovement_RoofingYear",                    "roof_year"),
    ("BuildingImprovement_RoofingIndicator",               None),
    ("BuildingImprovement_PlumbingYear",                   None),
    ("BuildingImprovement_PlumbingIndicator",              None),
    ("BuildingImprovement_HeatingYear",                    None),
    ("BuildingImprovement_HeatingIndicator",               None),
    ("BuildingImprovement_OtherYear",                      None),
    ("BuildingImprovement_OtherIndicator",                 None),
    ("BuildingImprovement_OtherDescription",               None),
    ("BuildingFeatures_HistoricalProperty",                None),
    ("BuildingFeatures_SolidFuel",                         None),
    ("BuildingOccupancy_OtherOccupancies",                 None),
    ("BuildingOccupancy_Apartment",                        None),
    ("BuildingExposure_",                                  None),
    ("BuildingSecurity_",                                  None),

    # ── Additional interest / mortgagee ──────────────────────────────────────
    ("AdditionalInterest_FullName",                        "additional_named_insureds"),
    ("AdditionalInterest_MailingAddress_LineOne",          "_addr_line1"),
    ("AdditionalInterest_MailingAddress_LineTwo",          "_addr_line2"),
    ("AdditionalInterest_MailingAddress_CityName",         "_addr_city"),
    ("AdditionalInterest_MailingAddress_StateOrProv",      "_addr_state"),
    ("AdditionalInterest_MailingAddress_PostalCode",       "_addr_zip"),
    ("AdditionalInterest_MailingAddress_CountryCode",      None),
    ("AdditionalInterest_AccountNumber",                   None),
    ("AdditionalInterest_Interest_Mortgagee",              None),
    ("AdditionalInterest_Interest_LossPayee",              None),
    ("AdditionalInterest_Interest_LendersLoss",            None),
    ("AdditionalInterest_Interest_AdditionalInsured",      None),
    ("AdditionalInterest_Interest_Lienholder",             None),
    ("AdditionalInterest_Interest_Employee",               None),
    ("AdditionalInterest_Interest_Other",                  None),
    ("AdditionalInterest_InterestRank",                    None),
    ("AdditionalInterest_CertificateRequired",             None),
    ("AdditionalInterest_Item_",                           None),
    ("AdditionalInterest_ItemDescription",                 None),
    ("Mortgagee_FullName",                                 "mortgagee_name"),
    ("Mortgagee_Name",                                     "mortgagee_name"),

    # ── Certificate holder ──────────────────────────────────────────────────
    ("CertificateHolder_FullName",                         "certificate_holder"),
    ("CertificateHolder_MailingAddress_LineOne",           "_addr_line1"),
    ("CertificateHolder_MailingAddress_LineTwo",           "_addr_line2"),
    ("CertificateHolder_MailingAddress_CityName",          "_addr_city"),
    ("CertificateHolder_MailingAddress_StateOrProv",       "_addr_state"),
    ("CertificateHolder_MailingAddress_PostalCode",        "_addr_zip"),

    # ── Auto ─────────────────────────────────────────────────────────────────
    ("Vehicle_LiabilityAutoOnly_PerAccidentLimitAmount",          "garage_liability_limit"),
    ("Vehicle_LiabilityOtherThanAutoOnly_PerAccidentLimitAmount", "garage_liability_limit"),
    ("Vehicle_LiabilityOtherThanAutoOnly_AggregateLimitAmount",   "garage_liability_limit"),
    ("GarageAndDealers_GarageKeepersComprehensive_LimitAmount",   "garagekeeper_liability_limit"),
    ("GarageAndDealers_GarageKeepersCollision_LimitAmount",       "garagekeeper_liability_limit"),
    ("GarageAndDealers_GarageKeepersComprehensive_PerAutoDeductibleAmount", "garagekeeper_comp_deductible"),
    ("GarageAndDealers_GarageKeepersCollision_PerAutoDeductibleAmount", "garagekeeper_coll_deductible"),
    ("GarageAndDealers_PhysicalDamageComprehensive_LimitAmount",  "auto_dealers_inventory_value"),
    ("GarageAndDealers_PhysicalDamageCollision_LimitAmount",      "auto_dealers_inventory_value"),
    ("Vehicle_CombinedSingleLimit_LimitIndicator",         "auto_liability_structure"),
    ("AutoLiability_CombinedSingleLimit",                  "auto_liability_limit"),
    ("Vehicle_CombinedSingleLimit",                        "auto_liability_limit"),
    ("Vehicle_BodilyInjury_PerPerson",                     "auto_liability_limit"),
    ("Vehicle_BodilyInjury_PerAccident",                   "auto_liability_limit"),
    ("Vehicle_PropertyDamage_PerAccident",                 "auto_liability_limit"),
    ("Vehicle_OtherCoverage_CoverageDescription",          None),
    ("Vehicle_OtherCoverage_LimitAmount",                  None),
    ("Vehicle_OtherCoveredAutoDescription",                None),
    ("Vehicle_InsurerLetterCode",                          None),

    # ── Workers comp ─────────────────────────────────────────────────────────
    ("WorkersCompensation_Payroll",                        "wc_payroll"),
    ("WorkersCompensation_ExperienceModification",         "wc_xmod"),
    ("WorkersCompensation_ExperienceMod",                  "wc_xmod"),
    # Most-specific patterns first — DiseaseEachEmployee before Disease alone
    ("WorkersCompensationEmployersLiability_EmployersLiability_EachAccident",           "wc_el_each_accident"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_DiseaseEachEmployee",    "wc_el_disease_each_employee"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_Disease",                "wc_el_disease_policy_limit"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_EachEmployee",           "wc_el_disease_each_employee"),
    ("WorkersCompensation_EmployersLiability_EachAccident",                             "wc_el_each_accident"),
    ("WorkersCompensation_EmployersLiability_DiseaseEachEmployee",                      "wc_el_disease_each_employee"),
    ("WorkersCompensation_EmployersLiability_EachEmployee",                             "wc_el_disease_each_employee"),
    ("WorkersCompensation_EmployersLiability_PolicyLimit",                              "wc_el_disease_policy_limit"),
    ("EmployersLiability_EachAccident",                                                 "wc_el_each_accident"),
    ("EmployersLiability_Disease_EachEmployee",                                         "wc_el_disease_each_employee"),
    ("EmployersLiability_Disease_PolicyLimit",                                          "wc_el_disease_policy_limit"),
    ("WorkersCompensationEmployersLiability_OtherCoverage",                   None),
    ("WorkersCompensationEmployersLiability_InsurerLetterCode",               None),

    # ── Umbrella / excess ────────────────────────────────────────────────────
    ("Umbrella_EachOccurrence",                            "umbrella_limit"),
    ("Umbrella_Aggregate",                                 "umbrella_limit"),
    ("Umbrella_SelfInsuredRetention",                      "umbrella_sir"),
    ("ExcessUmbrella_Umbrella_EachOccurrenceAmount",       "umbrella_limit"),
    ("ExcessUmbrella_Umbrella_AggregateAmount",            "umbrella_limit"),
    ("ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount","umbrella_sir"),
    ("ExcessUmbrella_OtherCoverageDescription",            None),
    ("ExcessUmbrella_OtherCoverageLimitAmount",            None),
    ("ExcessUmbrella_InsurerLetterCode",                   None),

    # ── Contractors ──────────────────────────────────────────────────────────
    ("Contractors_WorkSubcontractedPercent",               "percent_subcontracted"),
    ("Contractors_SubcontractorsPaidAmount",               "total_revenue"),
    ("Contractors_FullTimeEmployeeCount",                  "num_employees"),
    ("Contractors_PartTimeEmployeeCount",                  "num_employees"),
    ("Contractors_Question_",                              None),
    ("ProductAndCompletedOperations_AnnualGrossSalesAmount","total_revenue"),
    ("ProductAndCompletedOperations_UnitCount",            None),
    ("ProductAndCompletedOperations_InMarketMonth",        None),
    ("ProductAndCompletedOperations_ExpectedLife",         None),
    ("ProductAndCompletedOperations_IntendedUse",          None),
    ("ProductAndCompletedOperations_PrincipalComponents",  None),
    ("ProductAndCompletedOperations_ProductName",          None),

    # ── Alarm, security, exposure, miscellaneous null fields ─────────────────
    ("Alarm_Burglar_",                                     None),
    ("Burglar_LocalGong",                                  None),
    ("SwimmingPool_",                                      None),
    ("AthleticTeam_",                                      None),
    ("GeneralLiabilityLineOfBusiness_",                    None),
    ("CommercialInlandMarineProperty_",                    None),
    ("PropertyItem_ItemDetail_",                           None),
    ("OtherPolicy_InsurerLetterCode",                      None),
    ("OtherPolicy_OtherPolicyDescription",                 None),
    ("OtherPolicy_SubrogationWaived",                      None),
    ("OtherPolicy_CoverageCode",                           None),
    ("OtherPolicy_CoverageLimitAmount",                    None),
    ("CertificateOfLiabilityInsurance_",                   None),
    ("_RemarkText",                                        None),
    ("_Explanation",                                       None),

    # ── ACORD 126 fields not covered above — eliminates all LLM fallback calls ─
    # Signature / admin fields
    ("NamedInsured_Signature",                             None),   # wet-ink signature widget
    ("NamedInsured_SignatureDate",                         None),   # date below signature
    ("Producer_NationalIdentifier",                        None),   # NPN — not in extraction schema
    ("Producer_StateLicenseIdentifier",                    None),   # state license # — not extracted
    # GL claims-made continuous coverage entry date (not same as retro_date)
    ("GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate", "retro_date"),
    # GL limit description and deductible description free-text boxes
    ("GeneralLiability_OtherCoverageLimitDescription",     None),
    ("GeneralLiability_OtherDeductibleDescription",        None),
    # Additional interest WC certificate checkbox codes
    ("AdditionalInterest_WorkersCompensationCarriedCode",  None),
]

_SIGNATURE_FIELD_PATTERNS = [
    "signature","producer_sig","insured_sig","authorized_sig","applicant_sig",
    "agent_sig","signedby","signed_by","sign_here","producersig","agentsig",
    "sig_producer","sig_insured","sig_agent",
]

_SIGNATURE_FIELD_EXCLUSIONS = [
    "signing_date","signdate","sign_date","datesigned","date_signed","date_of_sign",
    "signaturedate","signature_date","designation","title","printed","print_name",
    "name_of","countersign_date","countersignature_date",
]


def _is_signature_field(field_name: str, field_type: str = "") -> bool:
    if field_type and "/Sig" in str(field_type):
        return True
    fn = field_name.lower().replace(" ", "_").replace("-", "_").replace(".", "_")
    if "date" in fn:
        return False
    if any(excl in fn for excl in _SIGNATURE_FIELD_EXCLUSIONS):
        return False
    return any(pat in fn for pat in _SIGNATURE_FIELD_PATTERNS)


def _collect_fields_pikepdf(arr, results: dict):
    for item in arr:
        try:
            t    = item.get("/T", None)
            kids = item.get("/Kids", None)
            ft   = str(item.get("/FT", ""))
            tu   = str(item.get("/TU", ""))[:80]
            ff   = int(item.get("/Ff", 0) or 0)
            if t:
                results[str(t)] = {"ft": ft, "tu": tu, "required": bool(ff & 2)}
            if kids:
                _collect_fields_pikepdf(kids, results)
        except Exception:
            pass


def extract_form_schema(path: str, form_id: str = "") -> dict:
    """Extract AcroForm field schema from a PDF template.

    When *form_id* is supplied the function checks
    ``forms_schemas/{form_id}_schema.json`` first and returns immediately on a
    cache hit.  On a cache miss the PDF is parsed with pikepdf and the result
    is saved to disk so subsequent calls never touch pikepdf again.
    """
    if form_id:
        schema_path = os.path.join(FORMS_SCHEMAS_DIR, f"{form_id}_schema.json")
        if os.path.exists(schema_path):
            try:
                with open(schema_path) as f:
                    return json.load(f)
            except Exception as ex:
                logger.warning(f"extract_form_schema: failed to load cached schema for {form_id}: {ex}")

    if not os.path.exists(path):
        return {}
    try:
        pdf = pikepdf.open(path)
        if "/AcroForm" not in pdf.Root:
            pdf.close()
            if form_id:
                try:
                    with open(os.path.join(FORMS_SCHEMAS_DIR, f"{form_id}_schema.json"), "w") as f:
                        json.dump({}, f)
                except Exception:
                    pass
            return {}
        schema = {}
        _collect_fields_pikepdf(pdf.Root["/AcroForm"]["/Fields"], schema)
        pdf.close()
        if form_id:
            try:
                with open(os.path.join(FORMS_SCHEMAS_DIR, f"{form_id}_schema.json"), "w") as f:
                    json.dump(schema, f, indent=2)
                logger.info(f"extract_form_schema: saved schema for {form_id} ({len(schema)} fields)")
            except Exception as ex:
                logger.warning(f"extract_form_schema: could not save schema for {form_id}: {ex}")
        return schema
    except Exception as ex:
        logger.error(f"extract_form_schema error: {ex}")
        return {}



def _get_checkbox_on_state(item) -> str:
    """Return the non-Off appearance state name for a /Btn widget (usually '/Yes').

    Reads the widget's /AP /N dictionary and returns the first key that is not
    '/Off'.  Falls back to '/Yes' if the appearance dict is absent or has no
    non-Off entry.
    """
    try:
        ap = item.get("/AP")
        if ap is not None:
            n = ap.get("/N")
            if n is not None:
                for k in n.keys():
                    k_str = str(k)
                    if k_str.lstrip("/") not in ("Off", "off", "OFF"):
                        return k_str if k_str.startswith("/") else f"/{k_str}"
    except Exception:
        pass
    return "/Yes"


def _checkmark_stream_content(w: float, h: float) -> bytes:
    """Return PDF content-stream bytes that draw a bold ✔ scaled to w×h."""
    # Checkmark path: start at left ~20% across, mid height;
    # drop to bottom ~35% across; rise to top-right corner.
    # Coordinates are in the widget's local space (origin = bottom-left).
    margin_x = w * 0.10
    margin_y = h * 0.10
    # tip of the short left stroke (bottom-left of the tick)
    x0 = margin_x + w * 0.08
    y0 = h * 0.42
    # valley of the tick
    x1 = margin_x + w * 0.30
    y1 = margin_y
    # top-right end of the tick
    x2 = w - margin_x
    y2 = h - margin_y
    lw = max(0.9, min(w, h) * 0.11)   # line weight proportional to box size
    content = (
        f"q\n"
        f"{lw:.2f} w\n"          # line width
        f"1 J\n"                  # round line caps
        f"1 j\n"                  # round line joins
        f"{x0:.2f} {y0:.2f} m\n"
        f"{x1:.2f} {y1:.2f} l\n"
        f"{x2:.2f} {y2:.2f} l\n"
        f"S\n"
        f"Q\n"
    )
    return content.encode("latin-1")


def _set_checkbox_checkmark_ap(pdf: pikepdf.Pdf, item, on_state_key: str):
    """Overwrite the on-state appearance stream in-place with a ✔ path."""
    try:
        ap = item.get("/AP")
        if ap is None:
            return

        n = ap.get("/N")
        if n is None:
            return

        key = on_state_key.lstrip("/")
        stream_obj = None
        for k in n.keys():
            if str(k).lstrip("/") == key:
                stream_obj = n[k]
                break
        if stream_obj is None:
            for k in n.keys():
                if str(k).lstrip("/") not in ("Off", "off", "OFF"):
                    stream_obj = n[k]
                    break
        if stream_obj is None:
            return

        # Read BBox from existing stream
        bb = stream_obj.get("/BBox")
        if bb is not None:
            bx0, by0, bx1, by1 = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
        else:
            rect = item.get("/Rect")
            if rect:
                rx1, ry1, rx2, ry2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                bx0, by0, bx1, by1 = 0.0, 0.0, abs(rx2 - rx1), abs(ry2 - ry1)
            else:
                bx0, by0, bx1, by1 = 0.0, 0.0, 14.4, 12.0

        w = bx1 - bx0
        h = by1 - by0
        if w <= 0 or h <= 0:
            w, h = 14.4, 12.0

        stream_bytes = _checkmark_stream_content(w, h)

        # Write new content directly into the existing stream object in-place.
        # This works even when the stream is an indirect object, because we are
        # mutating the object that pikepdf already has a reference to.
        stream_obj.write(stream_bytes)

        # Remove /Filter so pikepdf doesn't try to decompress our raw bytes
        if "/Filter" in stream_obj:
            del stream_obj["/Filter"]
        if "/DecodeParms" in stream_obj:
            del stream_obj["/DecodeParms"]

    except Exception:
        pass


def _fill_and_highlight(arr, data: dict, confidence: dict, counter: list, pdf: pikepdf.Pdf = None):
    for item in arr:
        try:
            t    = item.get("/T", None)
            kids = item.get("/Kids", None)
            if t:
                name  = str(t)
                val   = data.get(name)
                if val is not None and str(val).strip() not in ("", "null", "None"):
                    ft = str(item.get("/FT", ""))
                    if "/Btn" in ft:
                        val_str    = str(val).strip()
                        is_checked = val_str.lower() in ("yes", "true", "1", "on", "x")
                        if is_checked:
                            on_state = _get_checkbox_on_state(item)
                            item["/V"]  = pikepdf.Name(on_state)
                            item["/AS"] = pikepdf.Name(on_state)
                            # Replace the on-state AP stream with a proper ✔ glyph
                            if pdf is not None:
                                _set_checkbox_checkmark_ap(pdf, item, on_state)
                        else:
                            item["/V"]  = pikepdf.Name("/Off")
                            item["/AS"] = pikepdf.Name("/Off")
                        counter[0] += 1
                    else:
                        item["/V"] = pikepdf.String(str(val))
                        if "/AP" in item:
                            del item["/AP"]
                        counter[0] += 1
            if kids:
                _fill_and_highlight(kids, data, confidence, counter, pdf)
        except Exception:
            pass


def _collect_field_rects_for_highlight(pdf: pikepdf.Pdf, confidence: dict, data: dict) -> dict:
    """Return {page_idx: [(x1,y1,x2,y2, color_rgb), ...]} for fields needing highlights."""
    # color tuples: pink=low_confidence+has_value, yellow=missing_required, green=client_arq_filled
    COLOR_PINK   = (1.00, 0.89, 0.89)   # rgba(254,226,226) — very light pink
    COLOR_YELLOW = (1.00, 0.95, 0.78)   # rgba(254,243,199) — very light yellow
    COLOR_GREEN  = (0.73, 0.97, 0.82)   # rgba(187,247,208) — very light green
    page_rects: dict = {}
    for page_idx, page in enumerate(pdf.pages):
        raw_annots = page.get("/Annots")
        if raw_annots is None:
            continue
        try:
            annot_list = list(raw_annots)
        except Exception:
            continue
        for annot_ref in annot_list:
            try:
                annot = annot_ref
                if "/Widget" not in str(annot.get("/Subtype", "")):
                    continue
                t = annot.get("/T")
                if t is None:
                    parent = annot.get("/Parent")
                    if parent:
                        t = parent.get("/T")
                if t is None:
                    continue
                name = str(t)
                rect = annot.get("/Rect")
                if rect is None:
                    continue
                x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                if x1 > x2: x1, x2 = x2, x1
                if y1 > y2: y1, y2 = y2, y1
                conf = confidence.get(name, "low_confidence")
                val  = data.get(name)
                has_val = val is not None and str(val).strip() not in ("", "null", "None")
                if conf == "filled":
                    color = None
                elif conf == "client_arq":
                    color = COLOR_GREEN
                elif conf == "missing_required":
                    color = COLOR_YELLOW
                elif conf == "low_confidence" and has_val:
                    color = COLOR_PINK
                else:
                    color = None
                if color:
                    page_rects.setdefault(page_idx, []).append((x1, y1, x2, y2, color))
            except Exception:
                pass
    return page_rects


def _draw_highlight_rects(pdf: pikepdf.Pdf, page_rects: dict) -> None:
    """Paint semi-transparent filled rectangles on each page's content stream."""
    for page_idx, rects in page_rects.items():
        if not rects:
            continue
        page = pdf.pages[page_idx]
        lines = ["q"]  # save graphics state
        for (x1, y1, x2, y2, rgb) in rects:
            r, g, b = rgb
            w = x2 - x1
            h = y2 - y1
            if w <= 0 or h <= 0:
                continue
            lines.append(f"{r:.3f} {g:.3f} {b:.3f} rg")   # fill color
            lines.append(f"{x1:.2f} {y1:.2f} {w:.2f} {h:.2f} re f")  # rect + fill
        lines.append("Q")  # restore graphics state
        overlay_bytes = ("\n".join(lines) + "\n").encode("latin-1")
        overlay_stream = pikepdf.Stream(pdf, overlay_bytes)
        existing = page.get("/Contents")
        if existing is None:
            page["/Contents"] = overlay_stream
        elif isinstance(existing, pikepdf.Array):
            # Already an array — prepend our overlay
            page["/Contents"] = pikepdf.Array([overlay_stream] + list(existing))
        else:
            # Single stream — wrap both in an array (overlay drawn first, page content on top)
            page["/Contents"] = pikepdf.Array([overlay_stream, existing])


def fill_pdf(template_path: str, data: dict, confidence: Optional[dict] = None) -> bytes:
    try:
        pdf = pikepdf.open(template_path)
        if "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            acro["/NeedAppearances"] = pikepdf.Boolean(True)
            counter = [0]
            _fill_and_highlight(acro.get("/Fields", []), data, confidence or {}, counter, pdf)
            logger.info(f"fill_pdf: wrote {counter[0]} field values")
        if confidence:
            page_rects = _collect_field_rects_for_highlight(pdf, confidence, data or {})
            if page_rects:
                _draw_highlight_rects(pdf, page_rects)
                total_hl = sum(len(v) for v in page_rects.values())
                logger.info(f"fill_pdf: drew {total_hl} highlight rects across {len(page_rects)} pages")
        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        buf.seek(0)
        return buf.getvalue()
    except Exception as ex:
        logger.error(f"fill_pdf error: {ex}")
        with open(template_path, "rb") as f:
            return f.read()


# Increment when new fact keys are added to extraction schema — forces fieldmap regen.
# Must match FIELDMAP_SCHEMA_VERSION in scripts/generate_fieldmaps.py.
_FIELDMAP_SCHEMA_VERSION = "v5"


def _load_fieldmap(form_id: str) -> tuple:
    """Load persisted {field_name: fact_key} map and AI-mapped field set.

    Returns (fieldmap, ai_mapped_set) where ai_mapped_set contains field names
    that were originally resolved by LLM (not deterministic rules). These retain
    "low_confidence" status across runs so the UI keeps showing pink highlights.
    """
    if not form_id:
        return {}, set()
    path = os.path.join(FORMS_DB_DIR, f"ACORD_{form_id}_fieldmap.json")
    if not os.path.exists(path):
        return {}, set()
    try:
        with open(path) as f:
            data = json.load(f)
        # Delete fieldmap if schema version changed or __ai_mapped__ is missing —
        # forces fresh LLM run with new fact keys.
        if data.get("__schema_version__") != _FIELDMAP_SCHEMA_VERSION or "__ai_mapped__" not in data:
            try:
                os.remove(path)
            except Exception:
                pass
            return {}, set()
        data.pop("__schema_version__", None)
        ai_set = set(data.pop("__ai_mapped__", []))
        return data, ai_set
    except Exception:
        return {}, set()


def _save_fieldmap(form_id: str, fieldmap: dict, ai_set: set = None):
    """Persist field→fact_key map and AI-mapped field names."""
    if not form_id or not fieldmap:
        return
    path = os.path.join(FORMS_DB_DIR, f"ACORD_{form_id}_fieldmap.json")
    try:
        data = dict(fieldmap)
        data["__schema_version__"] = _FIELDMAP_SCHEMA_VERSION
        if ai_set:
            data["__ai_mapped__"] = sorted(ai_set)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as ex:
        logger.warning(f"Could not save fieldmap for {form_id}: {ex}")


def migrate_fieldmaps_to_v5() -> None:
    """One-time startup migration: stamp all on-disk fieldmaps to schema version v5.

    All 15 fieldmaps shipped at v4. The runtime rejects v4 files (deletes them and
    rebuilds from zero), destroying the pre-generated non-null mappings. This function
    reads each file, sets __schema_version__ = "v5", adds __ai_mapped__ if missing,
    and writes it back — preserving every existing field→fact_key entry.

    Idempotent: safe to call on every boot (already-v5 files are untouched).
    """
    import glob as _glob
    pattern = os.path.join(FORMS_DB_DIR, "ACORD_ACORD_*_fieldmap.json")
    files   = _glob.glob(pattern)
    if not files:
        logger.warning("migrate_fieldmaps_to_v5: no fieldmap files found in %s", FORMS_DB_DIR)
        return

    migrated = 0
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
            current_ver = data.get("__schema_version__")
            if current_ver == _FIELDMAP_SCHEMA_VERSION:
                continue                                   # already correct — skip
            data["__schema_version__"] = _FIELDMAP_SCHEMA_VERSION
            if "__ai_mapped__" not in data:
                data["__ai_mapped__"] = []
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            migrated += 1
            logger.info(
                "migrate_fieldmaps_to_v5: %s %s → %s",
                os.path.basename(path), current_ver or "missing", _FIELDMAP_SCHEMA_VERSION,
            )
        except Exception as ex:
            logger.warning("migrate_fieldmaps_to_v5: skipped %s — %s", os.path.basename(path), ex)

    logger.info("migrate_fieldmaps_to_v5: done — %d/%d files updated", migrated, len(files))


def purge_stale_null_fieldmap_entries() -> None:
    """Remove null entries from all fieldmaps for fields that are actually fillable.

    Null entries for fillable fields (indicator checkboxes, contact fields, prior
    coverage rows, etc.) were written by older code that didn't have _INDICATOR_RULES
    or full _ACORD_FIELD_RULES coverage. Keeping them as null permanently blocks GPT
    from filling those fields. This function removes those nulls so the next form fill
    run sends them through GPT, which can now tick the right boxes from the document.

    Runs at startup; idempotent — only modifies files that have removable nulls.
    """
    import glob as _glob

    # Fields whose null entry is VALID and must NOT be removed (carrier-computed, admin-only).
    # Use precise substrings — avoid over-broad patterns that catch Indicator fields.
    _PERMANENT_NULL_SUBSTRINGS = (
        "Signature", "_Sig", "InsurerLetterCode",
        "Hazard_", "Premium", "Rate_", "Revision",
        "EditionIdentifier", "NeedAppearances",
        "Underwriter", "CarrierCode", "PolicyNumber_Carrier",
        # Truly un-extractable identifier fields
        "ProducerIdentifier", "SubProducerIdentifier",
        "ProductDescription", "ProductCode",
        "WebsiteAddress",       # not extracted
        "Initials_",            # handwritten initials widget
        "GeneralLiabilityCode", # carrier-assigned
        "OccupiedArea", "OpenToPublicArea",
        "Sublocation", "TaxCode",
    )

    # Additional whole-name patterns (exact contains check on stripped field name)
    _PERMANENT_NULL_EXACT = (
        "Policy_Status_EffectiveTime_A",
        "Policy_Status_EffectiveTimeAMIndicator_A",
        "Policy_Status_EffectiveTimePMIndicator_A",
        "LossHistory_TotalAmount_A",
    )

    def _is_permanent_null(field: str) -> bool:
        if field in _PERMANENT_NULL_EXACT:
            return True
        return any(s in field for s in _PERMANENT_NULL_SUBSTRINGS)

    pattern = os.path.join(FORMS_DB_DIR, "ACORD_ACORD_*_fieldmap.json")
    files   = _glob.glob(pattern)
    if not files:
        return

    total_purged = 0
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
            purged = []
            for field, value in list(data.items()):
                if field.startswith("__"):
                    continue
                if value is None and not _is_permanent_null(field):
                    del data[field]
                    purged.append(field)
            if purged:
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
                total_purged += len(purged)
                logger.info(
                    "purge_null_fieldmap: %s — removed %d stale nulls: %s",
                    os.path.basename(path), len(purged),
                    ", ".join(purged[:8]) + ("…" if len(purged) > 8 else ""),
                )
        except Exception as ex:
            logger.warning("purge_null_fieldmap: skipped %s — %s", os.path.basename(path), ex)

    if total_purged:
        logger.info("purge_null_fieldmap: done — %d null entries removed across %d files", total_purged, len(files))
    else:
        logger.debug("purge_null_fieldmap: no stale nulls found")


def _resolve_special(key: str, facts: dict, prefix: str) -> str:
    if prefix == "_addr":
        raw = _fv(facts, "mailing_address", "")
    elif prefix == "_loc":
        # Physical / premises address: prefer physical_address, fall back to
        # first entry in locations list, then mailing_address.
        raw = _fv(facts, "physical_address", "")
        if not raw:
            locs = facts.get("locations", [])
            raw  = locs[0] if isinstance(locs, list) and locs else ""
        if not raw:
            raw = _fv(facts, "mailing_address", "")
    else:
        raw = _fv(facts, "mailing_address", "")
    parsed = _parse_address(raw or "")
    suffix = key.split("_")[-1]
    return parsed.get(suffix, "") or ""


_SPECIAL_PREFIXES = {"_addr", "_loc"}


_INDICATOR_RULES: Dict[str, Tuple[str, str]] = {
    # field_substring: (fact_key, truthy_value_to_match)
    # GL form type
    "GeneralLiability_OccurrenceIndicator":    ("gl_form_type", "occurrence"),
    "GeneralLiability_ClaimsMadeIndicator":    ("gl_form_type", "claims"),
    # Named insured entity type — longer/more-specific substrings first
    "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator": ("entity_type", "llc"),
    "NamedInsured_LegalEntity_SubchapterSCorporationIndicator": ("entity_type", "s-corp"),
    "NamedInsured_LegalEntity_CorporationIndicator": ("entity_type", "corporation"),
    "NamedInsured_LegalEntity_PartnershipIndicator": ("entity_type", "partnership"),
    "NamedInsured_LegalEntity_IndividualIndicator":  ("entity_type", "individual"),
    "NamedInsured_LegalEntity_NotForProfitIndicator": ("entity_type", "non-profit"),
    "NamedInsured_LegalEntity_TrustIndicator": ("entity_type", "trust"),
    "NamedInsured_LegalEntity_JointVentureIndicator": ("entity_type", "joint venture"),
    "NamedInsured_LegalEntity_OtherIndicator": ("entity_type", "other"),
    # Lines of business — primary: flags booleans (has_*) from extraction; fallback: lines_of_business list
    "Policy_LineOfBusiness_BusinessAutoIndicator":          ("has_auto_coverage",      "yes"),
    "Policy_LineOfBusiness_CommercialGeneralLiability":     ("has_general_liability",  "yes"),
    "Policy_LineOfBusiness_CommercialProperty":             ("has_property_coverage",  "yes"),
    "Policy_LineOfBusiness_UmbrellaIndicator":              ("has_umbrella",           "yes"),
    "Policy_LineOfBusiness_WorkersCompensation":            ("has_workers_comp",       "yes"),
    "Policy_LineOfBusiness_BusinessOwnersIndicator":        ("lines_of_business",      "bop"),
    "Policy_LineOfBusiness_CrimeIndicator":                 ("has_crime",              "yes"),
    "Policy_LineOfBusiness_GarageAndDealersIndicator":      ("lines_of_business",      "garage"),
    "Policy_LineOfBusiness_CommercialInlandMarineIndicator":("has_inland_marine",      "yes"),
    "Policy_LineOfBusiness_MotorCarrierIndicator":          ("lines_of_business",      "motor carrier"),
    "Policy_LineOfBusiness_TruckersIndicator":              ("lines_of_business",      "truckers"),
    "Policy_LineOfBusiness_FiduciaryLiabilityIndicator":    ("lines_of_business",      "fiduciary"),
    "Policy_LineOfBusiness_LiquorLiabilityIndicator":       ("lines_of_business",      "liquor"),
    "Policy_LineOfBusiness_CyberAndPrivacy":                ("has_cyber",              "yes"),
    "Policy_LineOfBusiness_YachtIndicator":                 ("lines_of_business",      "yacht"),
    "Policy_LineOfBusiness_BoilerAndMachineryIndicator":    ("lines_of_business",      "boiler"),
    # Business type indicators — ACORD 125 BusinessInformation section
    "BusinessInformation_BusinessType_ContractorIndicator":    ("is_contractor",          "yes"),
    "BusinessInformation_BusinessType_ManufacturingIndicator": ("operations_description", "manufactur"),
    "BusinessInformation_BusinessType_RestaurantIndicator":    ("operations_description", "restaurant"),
    "BusinessInformation_BusinessType_RetailIndicator":        ("operations_description", "retail"),
    "BusinessInformation_BusinessType_ServiceIndicator":       ("operations_description", "service"),
    "BusinessInformation_BusinessType_WholesaleIndicator":     ("operations_description", "wholesale"),
    "BusinessInformation_BusinessType_OfficeIndicator":        ("operations_description", "office"),
    "BusinessInformation_BusinessType_ApartmentsIndicator":    ("operations_description", "apartment"),
    "BusinessInformation_BusinessType_CondominiumsIndicator":  ("operations_description", "condominium"),
    "BusinessInformation_BusinessType_InstitutionalIndicator": ("operations_description", "institutional"),
    # Policy status — new/renewal
    "CommercialPolicy_NewBusinessIndicator": ("is_renewal", "no"),
    "CommercialPolicy_RenewalIndicator":     ("is_renewal", "yes"),
    # Billing method
    "Policy_Payment_DirectBillIndicator":   ("billing_plan", "direct"),
    "Policy_Payment_ProducerBillIndicator": ("billing_plan", "agency"),
    # Hired/non-owned auto
    "Vehicle_HiredIndicator":         ("hired_auto_indicator", "yes"),
    "Vehicle_HiredAutosIndicator":    ("hired_auto_indicator", "yes"),
    "Vehicle_NonOwnedIndicator":      ("non_owned_auto_indicator", "yes"),
    "Vehicle_NonOwnedAutosIndicator": ("non_owned_auto_indicator", "yes"),
    # Property valuation
    "ValuationCode_ReplacementCostIndicator": ("valuation_method", "rcv"),
    "ValuationCode_ActualCashValueIndicator": ("valuation_method", "acv"),
    # Loss history
    "LossHistory_NoPriorLossesIndicator": ("num_claims", "0"),
    # Umbrella form type
    "ExcessUmbrella_OccurrenceIndicator": ("gl_form_type", "occurrence"),
    "ExcessUmbrella_ClaimsMadeIndicator": ("gl_form_type", "claims"),
    # WC statutory limits indicator
    "WorkersCompensationEmployersLiability_WorkersCompensationStatutoryLimitIndicator": ("wc_el_each_accident", "statutory"),
    # Builders risk
    "Policy_SectionAttached_InstallationBuildersRiskIndicator": ("has_builders_risk", "true"),
    # Inland marine
    "Policy_SectionAttached_OpenCargoIndicator": ("has_inland_marine", "true"),
    # Driver/vehicle schedule attachments
    "Policy_SectionAttached_DriverInformationScheduleIndicator": ("auto_drivers", "non-empty"),
    "Policy_SectionAttached_VehicleScheduleIndicator":           ("auto_vin_schedule", "non-empty"),
    # Contractors supplement
    "CommercialPolicy_Attachment_ContractorsSupplementIndicator": ("contractor_type", "contractor"),
}


def _resolve_bool_indicator(val) -> str:
    """Convert any fact value to 'Yes' or 'No' for /Btn checkbox fields."""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    s = str(val).strip().lower()
    return "Yes" if s in {"yes", "y", "true", "1", "on"} else "No"


def _derive_indicator(field_name: str, facts: dict) -> Optional[str]:
    """Return 'Yes'/'No' for indicator/checkbox fields based on extracted facts.

    Covers both fields with 'Indicator' in the name and LOB checkboxes like
    Policy_LineOfBusiness_CommercialGeneralLiability_A (no 'Indicator' suffix).
    """
    fn_lower = field_name.lower()
    for substr, (fact_key, match_val) in _INDICATOR_RULES.items():
        if substr.lower() in fn_lower:
            raw = _fv(facts, fact_key)
            # Special case: match_val=="non-empty" means check whether a list is populated
            if match_val == "non-empty":
                if raw is None:
                    return "No"
                if isinstance(raw, list):
                    return "Yes" if raw else "No"
                return "Yes" if str(raw).strip() else "No"
            if raw is None:
                return None
            if isinstance(raw, bool):
                # Direct boolean fact: treat match_val=="yes"/"true" as "truthy expected"
                expected_true = match_val.lower() in {"yes", "true", "1"}
                return "Yes" if (raw == expected_true) else "No"
            if isinstance(raw, list):
                # List fact (e.g. lines_of_business): check if match_val appears in any element
                return "Yes" if any(match_val.lower() in str(item).lower() for item in raw) else "No"
            val_str = str(raw).lower()
            if match_val.lower() in val_str:
                return "Yes"
            return "No"
    return None


def _deterministic_map(field_name: str, facts: dict):
    # ── Schedule row resolution (highest priority) ───────────────────────────
    sched = _resolve_schedule_row(field_name, facts)
    if sched is not _SCHED_SKIP:
        return sched  # None means blank; any string is the resolved value

    # Layer: Location\d+_SubField  →  facts["locations"][N-1] or sub-key lookup
    loc_m = re.match(r"Location(\d+)[_]?(.*)", field_name)
    if loc_m:
        idx      = int(loc_m.group(1)) - 1
        sub      = loc_m.group(2).lower()
        locs     = facts.get("locations", []) or []
        if idx < len(locs):
            entry = locs[idx]
            if isinstance(entry, dict):
                val = entry.get(sub) or entry.get("address") or str(entry)
            else:
                val = str(entry)
            return val if val else None
        return None

    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            if fact_key is None:
                return None
            if fact_key.startswith("_"):
                return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
            val = _fv(facts, fact_key)   # unwrap OCR-confidence envelope
            if isinstance(val, list):
                # For indicator fields, check if the relevant value exists in the list
                if "Indicator" in field_name and isinstance(val, list):
                    ind = _derive_indicator(field_name, facts)
                    return ind
                return str(val[0]) if val else None
            return str(val) if val is not None else None

    # Try indicator derivation — also handles LOB checkboxes without "Indicator"
    # in the field name (e.g. Policy_LineOfBusiness_CommercialGeneralLiability_A).
    ind = _derive_indicator(field_name, facts)
    if ind is not None:
        return ind

    return "UNMATCHED"


def _apply_fact_key(fact_key: str, facts: dict):
    """Resolve a cached/LLM-returned fact_key to a scalar string value."""
    if fact_key is None:
        return None
    if fact_key.startswith("_"):
        return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
    val = _fv(facts, fact_key)
    if isinstance(val, bool):
        return _resolve_bool_indicator(val)
    if isinstance(val, list):
        return str(val[0]) if val else None
    return str(val) if val is not None else None


_ACORD125_REQUIRED_ALWAYS = {
    "Producer_FullName_A",
    "NamedInsured_FullName_A",
    "NamedInsured_MailingAddress_LineOne_A",
    "NamedInsured_MailingAddress_CityName_A",
    "NamedInsured_MailingAddress_StateOrProvinceCode_A",
    "NamedInsured_MailingAddress_PostalCode_A",
    "Policy_EffectiveDate_A",
    "Policy_ExpirationDate_A",
    "CommercialPolicy_OperationsDescription_A",
    "NamedInsured_BusinessStartDate_A",
}

_ACORD125_CONTACT_FIELDS = {
    "Producer_ContactPerson_FullName_A",
    "Producer_ContactPerson_PhoneNumber_A",
    "Producer_ContactPerson_EmailAddress_A",
    "NamedInsured_Primary_PhoneNumber_A",
}

_ACORD125_LOB_FIELDS = {
    "Policy_LineOfBusiness_BoilerAndMachineryIndicator_A",
    "Policy_LineOfBusiness_BusinessAutoIndicator_A",
    "Policy_LineOfBusiness_BusinessOwnersIndicator_A",
    "Policy_LineOfBusiness_CommercialGeneralLiability_A",
    "Policy_LineOfBusiness_CommercialInlandMarineIndicator_A",
    "Policy_LineOfBusiness_CommercialProperty_A",
    "Policy_LineOfBusiness_CrimeIndicator_A",
    "Policy_LineOfBusiness_CyberAndPrivacy_A",
    "Policy_LineOfBusiness_FiduciaryLiabilityIndicator_A",
    "Policy_LineOfBusiness_GarageAndDealersIndicator_A",
    "Policy_LineOfBusiness_LiquorLiabilityIndicator_A",
    "Policy_LineOfBusiness_MotorCarrierIndicator_A",
    "Policy_LineOfBusiness_TruckersIndicator_A",
    "Policy_LineOfBusiness_UmbrellaIndicator_A",
    "Policy_LineOfBusiness_YachtIndicator_A",
    "Policy_LineOfBusiness_OtherIndicator_A",
    "Policy_LineOfBusiness_OtherIndicator_B",
    "Policy_LineOfBusiness_OtherIndicator_C",
    "Policy_LineOfBusiness_OtherIndicator_D",
    "Policy_LineOfBusiness_OtherIndicator_E",
    "Policy_LineOfBusiness_OtherIndicator_F",
}

_ACORD125_BUSINESS_TYPE_FIELDS = {
    "BusinessInformation_BusinessType_ApartmentsIndicator_A",
    "BusinessInformation_BusinessType_CondominiumsIndicator_A",
    "BusinessInformation_BusinessType_ContractorIndicator_A",
    "BusinessInformation_BusinessType_InstitutionalIndicator_A",
    "BusinessInformation_BusinessType_ManufacturingIndicator_A",
    "BusinessInformation_BusinessType_OfficeIndicator_A",
    "BusinessInformation_BusinessType_RestaurantIndicator_A",
    "BusinessInformation_BusinessType_RetailIndicator_A",
    "BusinessInformation_BusinessType_ServiceIndicator_A",
    "BusinessInformation_BusinessType_WholesaleIndicator_A",
    "BusinessInformation_BusinessType_OtherIndicator_A",
}

_ACORD125_ENTITY_FIELDS = {
    "NamedInsured_LegalEntity_CorporationIndicator_A",
    "NamedInsured_LegalEntity_IndividualIndicator_A",
    "NamedInsured_LegalEntity_JointVentureIndicator_A",
    "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A",
    "NamedInsured_LegalEntity_NotForProfitIndicator_A",
    "NamedInsured_LegalEntity_PartnershipIndicator_A",
    "NamedInsured_LegalEntity_SubchapterSCorporationIndicator_A",
    "NamedInsured_LegalEntity_TrustIndicator_A",
    "NamedInsured_LegalEntity_OtherIndicator_A",
}

_ACORD125_LOSS_ROW_FIELDS = (
    "LossHistory_OccurrenceDate_{row}",
    "LossHistory_LineOfBusiness_{row}",
    "LossHistory_OccurrenceDescription_{row}",
    "LossHistory_ClaimDate_{row}",
    "LossHistory_PaidAmount_{row}",
    "LossHistory_ReservedAmount_{row}",
    "LossHistory_ClaimStatus_OpenCode_{row}",
)


def _acord125_has_value(data: dict, field: str) -> bool:
    val = data.get(field)
    return val is not None and str(val).strip() not in ("", "null", "None", "Off", "No", "false", "0")


def _acord125_is_yes(data: dict, field: str) -> bool:
    return str(data.get(field) or "").strip().lower() in {"yes", "y", "true", "1", "on"}


def _acord125_any(data: dict, fields: set) -> bool:
    return any(_acord125_has_value(data, field) for field in fields)


def _acord125_row_started(data: dict, prefix: str, row: str) -> bool:
    needle = f"{prefix}_"
    suffix = f"_{row}"
    return any(k.startswith(needle) and k.endswith(suffix) and _acord125_has_value(data, k) for k in data)


def apply_acord125_missing_field_highlights(
    form_id: str,
    facts: dict,
    field_state: dict,
    confidence: dict,
) -> dict:
    """
    ACORD 125-only visual completeness layer.

    This does not change validation, scoring, mappings, or API shape. It only
    reuses the existing `missing_required` confidence label so the current PDF
    viewer/PDF renderer can paint empty required/triggered fields yellow.
    """
    if form_id != "ACORD_125":
        return confidence

    required_now = set(_ACORD125_REQUIRED_ALWAYS)
    managed = set(_ACORD125_REQUIRED_ALWAYS)

    managed.update(_ACORD125_CONTACT_FIELDS)
    if not _acord125_any(field_state, _ACORD125_CONTACT_FIELDS):
        required_now.update(_ACORD125_CONTACT_FIELDS)

    managed.update(_ACORD125_LOB_FIELDS)
    if not _acord125_any(field_state, _ACORD125_LOB_FIELDS):
        required_now.update(_ACORD125_LOB_FIELDS)

    managed.update(_ACORD125_BUSINESS_TYPE_FIELDS)
    if not _acord125_any(field_state, _ACORD125_BUSINESS_TYPE_FIELDS):
        required_now.update(_ACORD125_BUSINESS_TYPE_FIELDS)

    managed.update(_ACORD125_ENTITY_FIELDS)
    if not _acord125_any(field_state, _ACORD125_ENTITY_FIELDS):
        required_now.update(_ACORD125_ENTITY_FIELDS)

    for row in ("A", "B", "C", "D", "E", "F"):
        other = f"Policy_LineOfBusiness_OtherIndicator_{row}"
        desc = f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{row}"
        managed.add(desc)
        if _acord125_is_yes(field_state, other):
            required_now.add(desc)

        attachment_other = f"CommercialPolicy_Attachment_OtherIndicator_{row}"
        attachment_desc = f"CommercialPolicy_Attachment_OtherDescription_{row}"
        managed.add(attachment_desc)
        if _acord125_is_yes(field_state, attachment_other):
            required_now.add(attachment_desc)

    for row in ("B", "C"):
        row_fields = {
            f"NamedInsured_FullName_{row}",
            f"NamedInsured_MailingAddress_LineOne_{row}",
            f"NamedInsured_MailingAddress_CityName_{row}",
            f"NamedInsured_MailingAddress_StateOrProvinceCode_{row}",
            f"NamedInsured_MailingAddress_PostalCode_{row}",
        }
        managed.update(row_fields)
        if _acord125_row_started(field_state, "NamedInsured", row):
            required_now.update(row_fields)

    for row in ("A", "B", "C", "D"):
        location_fields = {
            f"CommercialStructure_Location_ProducerIdentifier_{row}",
            f"CommercialStructure_PhysicalAddress_LineOne_{row}",
            f"CommercialStructure_PhysicalAddress_CityName_{row}",
            f"CommercialStructure_PhysicalAddress_StateOrProvinceCode_{row}",
            f"CommercialStructure_PhysicalAddress_PostalCode_{row}",
            f"CommercialStructure_AnnualRevenueAmount_{row}",
            f"BusinessInformation_FullTimeEmployeeCount_{row}",
            f"BusinessInformation_PartTimeEmployeeCount_{row}",
            f"BuildingOccupancy_OperationsDescription_{row}",
        }
        managed.update(location_fields)
        if _acord125_row_started(field_state, "CommercialStructure", row) or _acord125_row_started(field_state, "BuildingOccupancy", row):
            required_now.update(location_fields)

        for trigger, dependent in (
            (f"CommercialStructure_RiskLocation_OtherIndicator_{row}", f"CommercialStructure_RiskLocation_OtherDescription_{row}"),
            (f"CommercialStructure_InsuredInterest_OtherIndicator_{row}", f"CommercialStructure_InsuredInterest_OtherDescription_{row}"),
        ):
            managed.add(dependent)
            if _acord125_is_yes(field_state, trigger):
                required_now.add(dependent)

    if _acord125_is_yes(field_state, "NamedInsured_LegalEntity_OtherIndicator_A"):
        required_now.add("NamedInsured_LegalEntity_OtherDescription_A")
    managed.add("NamedInsured_LegalEntity_OtherDescription_A")

    if _acord125_is_yes(field_state, "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A"):
        required_now.add("NamedInsured_LegalEntity_MemberManagerCount_A")
    managed.add("NamedInsured_LegalEntity_MemberManagerCount_A")

    conditional_pairs = {
        "BusinessInformation_BusinessType_OtherIndicator_A": ["BusinessInformation_BusinessType_OtherDescription_A"],
        "CommercialPolicy_Question_AAICode_A": ["BusinessInformation_ParentOrganizationName_A", "Subsidiary_ParentSubsidiaryRelationshipDescription_A", "Subsidiary_ParentOwnershipPercent_A"],
        "CommercialPolicy_Question_AAJCode_A": ["Subsidiary_OrganizationName_A", "Subsidiary_ParentSubsidiaryRelationshipDescription_B", "Subsidiary_ParentOwnershipPercent_B"],
        "CommercialPolicy_Question_ABCCode_A": ["CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A"],
        "CommercialPolicy_Question_AADCode_A": ["CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A"],
        "CommercialPolicy_Question_KABCode_A": ["CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A"],
        "CommercialPolicy_Question_KAMCode_A": ["CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A"],
        "CommercialPolicy_Question_KANCode_A": ["CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A"],
        "CommercialPolicy_Question_KAOCode_A": ["CommercialPolicy_ApplicantHireOthersOperateDronesExplanation_A"],
    }
    for trigger, dependents in conditional_pairs.items():
        managed.update(dependents)
        if _acord125_is_yes(field_state, trigger):
            required_now.update(dependents)

    managed.update({"LossHistory_NoPriorLossesIndicator_A", "LossHistory_InformationYearCount_A"})
    loss_rows_started = any(_acord125_row_started(field_state, "LossHistory", row) for row in ("A", "B", "C"))
    if not _acord125_is_yes(field_state, "LossHistory_NoPriorLossesIndicator_A") and not loss_rows_started:
        required_now.update({"LossHistory_NoPriorLossesIndicator_A", "LossHistory_InformationYearCount_A"})
    for row in ("A", "B", "C"):
        row_fields = {tmpl.format(row=row) for tmpl in _ACORD125_LOSS_ROW_FIELDS}
        managed.update(row_fields)
        if _acord125_row_started(field_state, "LossHistory", row):
            required_now.update(row_fields)

    for field in managed:
        if field not in field_state and field not in confidence:
            continue
        if field in required_now and not _acord125_has_value(field_state, field):
            confidence[field] = "missing_required"
        elif confidence.get(field) == "missing_required":
            confidence[field] = "filled" if _acord125_has_value(field_state, field) else "low_confidence"

    return confidence


# Fields that should NEVER be sent to GPT:
#  - Signature / approval fields (legal, must not be synthesised)
#  - Pure carrier-computed fields (Premium, Rate, Revision — underwriter fills these)
#  - Admin / form-metadata fields
# NOTE: "Indicator" is intentionally NOT here.  Business-logic checkbox/indicator
# fields (LOB, entity type, GL occurrence, WC statutory, etc.) ARE GPT-eligible so
# that Layer 2 can tick the right boxes from the raw document text.
_RAW_TEXT_SKIP_PATTERNS = [
    "Signature", "_Sig", "InsurerLetterCode",
    "Attachment_", "Hazard_", "Premium", "Rate_", "Revision",
    "EditionIdentifier", "NeedAppearances",
    "Underwriter", "CarrierCode", "PolicyNumber_Carrier",
]


def _run_coro_sync(coro):
    """Run an async coroutine from synchronous code.

    Uses the running loop if one exists (FastAPI request context), otherwise
    creates a new event loop. Never calls asyncio.run() which fails when called
    inside an already-running loop.
    """
    import asyncio as _asyncio
    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return _asyncio.run(coro)


def _fill_empty_from_raw_text(
    mapped: dict,
    schema: dict,
    raw_text: str,
    form_id: str,
    filled_set: set,
) -> None:
    """DEPRECATED: replaced by _fill_unmatched_with_gpt(). Kept for rollback only. Do NOT call this function.

    Full-document LLM fill for fields still empty after fact-key mapping.

    Sends the COMPLETE OCR text (every word from every uploaded document) plus
    detailed field metadata from the form schema to the LLM.  The LLM reads the
    entire document and extracts exact values for each empty field.

    Designed for GPT-4o / Claude (large context windows).  Results are never
    cached in the fieldmap — they are document-specific values, not structural
    mappings.  Fields filled here are added to *filled_set* so the UI shows
    pink highlights for broker review.
    """
    empty_fields = [
        f for f in schema
        if mapped.get(f) is None or str(mapped.get(f, "")).strip() in ("", "null", "None")
    ]
    if not empty_fields:
        return

    text_fields = [
        f for f in empty_fields
        if not any(p in f for p in _RAW_TEXT_SKIP_PATTERNS)
    ]
    if not text_fields:
        return

    # Always send the FULL extracted text — the system is designed for GPT/Claude.
    # On Groq the call may fail if context is too long; that's caught below and
    # logged — partial filling is acceptable until the provider is upgraded.
    doc_text = raw_text  # no truncation

    # Batch size: GPT-4o / Claude handle 40+ fields per call comfortably.
    # Groq will likely fail on large docs — but that's acceptable at this stage.
    BATCH = 40

    # Pick the model name based on provider
    if ACTIVE_MODEL == "claude":
        llm_model = "claude-haiku-4-5-20251001"   # fast + large context
    else:
        llm_model = "gpt-4o-mini"

    for start in range(0, len(text_fields), BATCH):
        batch = text_fields[start : start + BATCH]

        # Build rich field descriptions using form schema metadata
        field_specs = []
        for f in batch:
            info = schema.get(f, {})
            if isinstance(info, dict):
                tu   = info.get("tu", "")[:120]   # PDF tooltip / field label
                ft   = info.get("ft", "")          # field type (/Tx text, /Btn checkbox, /Ch dropdown)
                req  = " [REQUIRED]" if info.get("required") else ""
                desc = f"  - {f}{req}"
                if tu:
                    desc += f": {tu}"
                if "/Ch" in ft:
                    desc += " (dropdown)"
            else:
                desc = f"  - {f}"
            field_specs.append(desc)

        fields_block = "\n".join(field_specs)

        prompt = (
            f"You are an insurance form completion expert filling ACORD form {form_id}.\n"
            "Your task: read the COMPLETE insurance document text below and extract the exact "
            "value for each listed form field.\n\n"
            "Rules:\n"
            "  1. Read the ENTIRE document — values appear anywhere across all pages.\n"
            "  2. Extract the EXACT value as written in the document. Do not paraphrase.\n"
            "  3. Return null for any field whose value is genuinely absent from the document.\n"
            "  4. Return short scalar values only: names, dates, dollar amounts, addresses, codes.\n"
            "  5. Do NOT invent, estimate, or carry over values from other fields.\n"
            "  6. For date fields: use the format as found in the document (MM/DD/YYYY or similar).\n"
            "  7. For dollar amounts: include the $ sign and commas as found (e.g. $1,000,000).\n\n"
            "Return ONLY a single JSON object: {\"FieldName\": \"extracted_value_or_null\"}\n\n"
            f"=== FORM FIELDS TO FILL ({form_id}) ===\n{fields_block}\n\n"
            f"=== COMPLETE INSURANCE DOCUMENT TEXT ===\n{doc_text}\n\n"
            "JSON Output:"
        )
        try:
            _coro    = groq_chat(llm_model, [{"role": "user", "content": prompt}])
            raw_resp = _run_coro_sync(_coro)
            if raw_resp.startswith("```"):
                raw_resp = raw_resp.replace("```json", "").replace("```", "").strip()
            s, e = raw_resp.find("{"), raw_resp.rfind("}")
            if s != -1 and e != -1:
                result = json.loads(raw_resp[s : e + 1])
                for field, value in result.items():
                    if value and str(value).strip() not in ("", "null", "None"):
                        mapped[field] = str(value).strip()
                        filled_set.add(field)
                logger.info(
                    f"raw_text_fill form={form_id} batch_start={start} "
                    f"fields_sent={len(batch)} fields_filled={len(filled_set)}"
                )
        except Exception as ex:
            logger.warning(f"Raw-text fill batch failed (form={form_id}, start={start}): {ex}")


# ── Form-fill LLM budget constants ───────────────────────────────────────────
# gpt-4o-mini: 128k token context (~512k chars). We target 80k tokens per call
# so there is comfortable headroom for the system prompt, facts block, fields
# block, and the model's JSON reply.
#
# PROMPT BREAKDOWN (approximate):
#   fixed skeleton + rules  ~  1 500 chars
#   facts block             ~  5 000 chars  (varies by submission)
#   fields block            ~    100 chars per field
#   raw text section        = raw_chunk chars
#   reply headroom          ~ 30 000 chars  (JSON with ~350 fields)
#
# We budget: total_prompt_chars ≤ _GPT_CALL_BUDGET_CHARS per call.
# Raw-text chunks are sized so that (fixed_overhead + fields_block + chunk) ≤ budget.

_GPT_CALL_BUDGET_CHARS   = int(os.getenv("GPT_CALL_BUDGET_CHARS",  str(280_000)))  # ~70k tokens
_GPT_REPLY_RESERVE_CHARS = int(os.getenv("GPT_REPLY_RESERVE_CHARS", str(30_000)))   # output headroom
# Max retries per individual LLM call
_FORM_FILL_BATCH_RETRIES = int(os.getenv("FORM_FILL_BATCH_RETRIES", "3"))

# Legacy constant — kept so existing env-var overrides still work but no longer
# used as the primary chunk size (it's derived dynamically from the budget above).
_FORM_FILL_RAW_CHUNK_CHARS = int(os.getenv("FORM_FILL_RAW_CHUNK_CHARS", str(40_000)))


def _fill_unmatched_with_gpt(
    unmatched_fields: dict,
    facts: dict,
    form_id: str,
    model: str = None,
    raw_text: str = "",
) -> dict:
    """GPT form-fill: fills unmatched fields from structured facts + full raw document text.

    Strategy — single-pass chunking:
      Everything (facts + fields + raw text) goes into one prompt per chunk.
      The raw text is the only thing that needs chunking; facts and fields are
      small enough to repeat in every call.

      Chunk sizing is automatic:
        chunk_chars = _GPT_CALL_BUDGET_CHARS - reply_reserve - fixed_overhead - fields_block
      where fixed_overhead = prompt skeleton + facts block (measured, not guessed).

      For a short doc (< budget): exactly 1 LLM call.
      For a large doc (500k tokens): N calls, each carrying ALL still-empty fields
      + one slice of the raw text.  Fields resolved in earlier chunks are dropped
      from later chunks, shrinking the fields block and leaving more budget for text.

      Conflict resolution: if multiple chunks return different values for the same
      field, the most-frequent candidate wins (majority vote across chunks).
      Structured-facts values always beat raw-text values.
    """
    if not unmatched_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "model_used": model or GPT_MODEL}

    try:
        _client = _get_openai_form_fill_client()
    except RuntimeError as _e:
        logger.warning("gpt_fill: %s — skipping GPT form fill pass", _e)
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "model_used": model or GPT_MODEL}

    llm_model = model or GPT_MODEL

    # ── PII-filtered structured facts ────────────────────────────────────────
    facts_for_llm = {
        k: str(_fv(facts, k))[:120]
        for k in facts
        if k not in _PII_EXCLUDE_KEYS
        and _fv(facts, k) is not None
        and not isinstance(_fv(facts, k), (list, dict))
    }
    fact_lines   = [f'  "{k}": "{v}"' for k, v in facts_for_llm.items()]
    fact_context = "{\n" + ",\n".join(fact_lines) + "\n}"

    # ── Filter out schedule/admin fields ─────────────────────────────────────
    eligible_fields = {
        f: meta
        for f, meta in unmatched_fields.items()
        if not _is_schedule_field(f)
        and not any(p in f for p in _RAW_TEXT_SKIP_PATTERNS)
    }
    if not eligible_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "model_used": llm_model}

    field_list = list(eligible_fields.keys())
    raw_text_used = bool(raw_text and raw_text.strip())

    # ── Shared accumulators ───────────────────────────────────────────────────
    # candidate_counts[field][value] = number of chunks that returned that value.
    # Majority vote across chunks; structured-fact values always win at resolution.
    candidate_counts: Dict[str, Dict[str, int]] = {f: {} for f in field_list}
    all_mappings:     Dict[str, Optional[str]]  = {}   # field → fact_key (first chunk only)
    all_raw_fields:   set                       = set()

    # ── Build a field-spec line for the prompt ───────────────────────────────
    _ROW_SUFFIX_RE = re.compile(r"^(.+)_([A-N])$")

    # Pre-compute total slot count per base name across the eligible field list.
    # e.g. {"NamedInsured_MailingAddress_LineOne": 3} when _A/_B/_C all appear.
    _slot_counts: Dict[str, int] = {}
    for _f in eligible_fields:
        _m = _ROW_SUFFIX_RE.match(_f)
        if _m:
            _base = _m.group(1)
            _slot_counts[_base] = _slot_counts.get(_base, 0) + 1

    def _field_spec(f: str) -> str:
        info = eligible_fields.get(f) or {}
        info = info if isinstance(info, dict) else {}
        tu   = info.get("tu", "")[:80]
        ft   = info.get("ft", "")
        req  = " [REQUIRED]" if info.get("required") else ""
        spec = f"  - {f}{req}"
        if tu:
            spec += f": {tu}"
        if "/Ch" in ft:
            spec += " (dropdown)"
        elif "/Btn" in ft:
            spec += " (checkbox — Yes/No)"
        # Annotate row-suffixed fields with slot index and total so the LLM knows
        # exactly how many distinct values to search for.
        m = _ROW_SUFFIX_RE.match(f)
        if m:
            base    = m.group(1)
            row_idx = ord(m.group(2)) - ord("A") + 1
            total   = _slot_counts.get(base, 1)
            spec += f" [slot {row_idx} of {total} — find the {row_idx}{'st' if row_idx == 1 else 'nd' if row_idx == 2 else 'rd' if row_idx == 3 else 'th'} distinct value for '{base}'; leave null if fewer than {row_idx} distinct values exist]"
        return spec

    # ── Prompt builder ───────────────────────────────────────────────────────
    _PROMPT_SKELETON = (
        f"You are filling ACORD form {form_id} for an insurance submission.\n"
        "You have two data sources:\n"
        "  SOURCE 1 — context hints: facts previously extracted from the document (use ONLY for disambiguation or confirmation)\n"
        "  SOURCE 2 — raw OCR document text (PRIMARY source — find all values directly from here)\n\n"
        "PRIMARY RULE: Extract values directly from SOURCE 2 (raw document text). "
        "SOURCE 1 facts are hints only — do NOT copy from SOURCE 1 as the answer unless you can also confirm the value exists in SOURCE 2. "
        "Your goal is to find the actual values printed in the declaration pages.\n\n"
        "Return exactly three keys:\n"
        '  "values":          {FieldName: "exact_value_or_null"}\n'
        '  "mappings":        {FieldName: "fact_key_or_null"}\n'
        '  "raw_text_sourced":[FieldName, ...]\n\n'
        "Rules:\n"
        "  1. EXACT values only — copy verbatim from SOURCE 2. Do not paraphrase or invent.\n"
        "  2. Return null when the value is genuinely absent from the document text.\n"
        "  3. Checkbox/indicator fields (marked 'checkbox — Yes/No'): return 'Yes' or 'No' ONLY.\n"
        "     Examples of how to fill checkboxes:\n"
        "     - Policy_Status_BoundIndicator: 'Yes' if the document is a bound policy, else 'No'\n"
        "     - Policy_Status_QuoteIndicator: 'Yes' if document is a quote/application, else 'No'\n"
        "     - Policy_LineOfBusiness_CommercialGeneralLiability: 'Yes' if GL coverage is requested\n"
        "     - NamedInsured_LegalEntity_CorporationIndicator: 'Yes' if entity type is Corporation\n"
        "     - BusinessInformation_BusinessType_ContractorIndicator: 'Yes' if business is a contractor\n"
        "     - LossHistory_NoPriorLossesIndicator: 'Yes' only if document explicitly states no losses\n"
        "  4. Dollar amounts: include $ and commas as found (e.g. $1,000,000).\n"
        "  5. Do NOT fill premium/rate/underwriter-computed fields — return null.\n"
        "  6. mappings: use ONLY exact fact keys from SOURCE 1. null if no clean match.\n"
        "  7. List ALL fields you fill from SOURCE 2 in raw_text_sourced.\n"
        "  8. Fields ending in _A, _B, _C ... are SEPARATE row slots for DIFFERENT entries.\n"
        "     Each such field is annotated '[slot N of T]' telling you there are T slots for\n"
        "     that field type. Search SOURCE 2 carefully for EACH distinct value.\n"
        "       a) Count how many DISTINCT values of that type appear in the document.\n"
        "       b) Assign the 1st distinct value to _A, 2nd to _B, etc.\n"
        "       c) If the document has fewer distinct values than slots, leave the extra\n"
        "          slots null — do NOT duplicate a value to fill empty slots.\n"
        "     Example: 3 slots for NamedInsured_Phone but only 2 phone numbers found →\n"
        "       _A = first number, _B = second number, _C = null.\n\n"
    )
    _SKELETON_CHARS = len(_PROMPT_SKELETON)
    _FACTS_CHARS    = len(fact_context)
    # Fixed overhead per call: skeleton + facts header + facts block + fields header + footer
    _FIXED_OVERHEAD = _SKELETON_CHARS + _FACTS_CHARS + 200

    def _build_prompt(active_fields: List[str], raw_chunk: str, chunk_idx: int, total_chunks: int) -> str:
        fields_block = "\n".join(_field_spec(f) for f in active_fields)
        raw_section  = (
            f"\n\n=== SOURCE 2: RAW DOCUMENT TEXT (chunk {chunk_idx + 1}/{total_chunks}) ===\n{raw_chunk}"
            if raw_chunk else ""
        )
        return (
            _PROMPT_SKELETON
            + f"=== SOURCE 1: EXTRACTED FACTS ===\n{fact_context}\n\n"
            + f"Fields to fill ({form_id}):\n{fields_block}"
            + raw_section
            + '\n\nReturn ONLY valid JSON: {"values": {...}, "mappings": {...}, "raw_text_sourced": [...]}'
        )

    # ── LLM caller with retry ─────────────────────────────────────────────────
    def _call_llm_sync(prompt: str) -> dict:
        async def _inner(_p=prompt):
            resp = await _client.chat.completions.create(
                model=llm_model,
                messages=[{"role": "user", "content": _p}],
                temperature=GPT_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content or ""

        import time as _time
        for attempt in range(_FORM_FILL_BATCH_RETRIES):
            try:
                return json.loads(_run_coro_sync(_inner()))
            except Exception as ex:
                if attempt < _FORM_FILL_BATCH_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning("gpt_fill: call failed attempt=%d/%d retrying in %ds — %s",
                                   attempt + 1, _FORM_FILL_BATCH_RETRIES, wait, ex)
                    _time.sleep(wait)
                else:
                    logger.warning("gpt_fill: call permanently failed — %s", ex)
                    return {}

    # ── Result absorber ───────────────────────────────────────────────────────
    def _absorb(result: dict, sent: List[str], is_first_chunk: bool, chunk_label: str = "1/1") -> None:
        values      = result.get("values",          {}) or {}
        mappings    = result.get("mappings",        {}) or {}
        raw_sourced = set(result.get("raw_text_sourced", []) or [])
        _chunk_label = chunk_label

        for field, fk in mappings.items():
            if field not in sent:
                continue
            if field in raw_sourced:
                fk = None
            elif fk is not None and fk not in _FULL_REGISTRY_KEYS:
                logger.debug("gpt_fill: rejected hallucinated fact_key=%r field=%r", fk, field)
                fk = None
            # Structural mappings are doc-independent — record from first chunk only
            if is_first_chunk and field not in all_mappings:
                all_mappings[field] = fk

        filled_count = 0
        for field, value in values.items():
            if field not in sent:
                continue
            if value and str(value).strip() not in ("", "null", "None"):
                vstr = str(value).strip()
                candidate_counts[field][vstr] = candidate_counts[field].get(vstr, 0) + 1
                if field in raw_sourced:
                    all_raw_fields.add(field)
                filled_count += 1

        logger.info(
            "gpt_fill: chunk=%s form=%s sent=%d filled=%d raw_sourced=%d",
            _chunk_label,
            form_id, len(sent), filled_count, len(raw_sourced),
        )

    # ── Chunk sizing ──────────────────────────────────────────────────────────
    # Budget per call: model context minus reply headroom minus fixed overhead
    # minus fields block chars for the fields active in this call.
    def _raw_budget(active_fields: List[str]) -> int:
        fields_chars = sum(len(_field_spec(f)) + 1 for f in active_fields)
        return max(
            10_000,
            _GPT_CALL_BUDGET_CHARS - _GPT_REPLY_RESERVE_CHARS - _FIXED_OVERHEAD - fields_chars,
        )

    # ── Split raw text into chunks that fit the model context ─────────────────
    # Chunk size is computed from the INITIAL field list (conservative; shrinks
    # later chunks have more budget as fields get resolved, which is fine).
    if raw_text_used:
        initial_budget = _raw_budget(field_list)
        raw_chunks: List[str] = []
        rest = raw_text
        while rest:
            if len(rest) <= initial_budget:
                raw_chunks.append(rest)
                break
            split_at = rest.rfind("\n\n", 0, initial_budget)
            if split_at == -1:
                split_at = rest.rfind("\n", 0, initial_budget)
            if split_at == -1:
                split_at = initial_budget
            raw_chunks.append(rest[:split_at])
            rest = rest[split_at:].lstrip("\n")
        logger.info(
            "gpt_fill: form=%s fields=%d raw_text_chars=%d chunks=%d chunk_budget=%d",
            form_id, len(field_list), len(raw_text), len(raw_chunks), initial_budget,
        )
    else:
        # No raw text — single call with facts only
        raw_chunks = [""]

    # ── Main loop: one LLM call per chunk ─────────────────────────────────────
    for chunk_idx, raw_chunk in enumerate(raw_chunks):
        # Only send fields not yet resolved in a previous chunk
        active_fields = [f for f in field_list if not candidate_counts[f]]
        if not active_fields:
            logger.info("gpt_fill: all fields resolved — stopping at chunk %d/%d",
                        chunk_idx + 1, len(raw_chunks))
            break

        prompt = _build_prompt(active_fields, raw_chunk, chunk_idx, len(raw_chunks))
        logger.info(
            "gpt_fill: chunk %d/%d form=%s active_fields=%d prompt_chars=%d",
            chunk_idx + 1, len(raw_chunks), form_id, len(active_fields), len(prompt),
        )
        result = _call_llm_sync(prompt)
        _absorb(result, active_fields, is_first_chunk=(chunk_idx == 0),
                chunk_label=f"{chunk_idx + 1}/{len(raw_chunks)}")

    # ── Conflict resolution ───────────────────────────────────────────────────
    # Raw document text is the primary source. Among candidates from multiple
    # chunks, the most-frequent value wins (majority vote).
    # Facts (SOURCE 1) are used only as a fallback when no raw-text value was found.
    all_filled: dict = {}
    for field, candidates in candidate_counts.items():
        if not candidates:
            continue
        # Majority vote across chunks — raw text is the ground truth
        all_filled[field] = max(candidates, key=lambda v: candidates[v])

    # ── Audit log ─────────────────────────────────────────────────────────────
    for field, value in all_filled.items():
        logger.info(
            "FIELD_SOURCE_AUDIT field=%s source=ai model=%s form_id=%s "
            "fact_key=%s raw_text_used=%s chunks_agreed=%s",
            field, llm_model, form_id,
            all_mappings.get(field) or "none",
            str(field in all_raw_fields).lower(),
            candidate_counts.get(field, {}).get(value, 1),
        )

    logger.info(
        "gpt_fill DONE: form=%s fields_filled=%d/%d chunks=%d model=%s",
        form_id, len(all_filled), len(eligible_fields), len(raw_chunks), llm_model,
    )
    return {
        "filled_values":   all_filled,
        "new_mappings":    all_mappings,
        "raw_text_fields": all_raw_fields,
        "model_used":      llm_model,
    }


def _is_nonfillable_field(field: str) -> bool:
    """Return True when a field is carrier-computed or administrative and should
    never be retried via GPT even when its cached fact_key is None.

    These match _RAW_TEXT_SKIP_PATTERNS but are checked by name so we can keep
    Indicator fields OUT of this list (they ARE fillable business fields).
    """
    _NONFILLABLE_SUBSTRINGS = (
        "Signature", "_Sig", "InsurerLetterCode",
        "Attachment_", "Hazard_", "Premium", "Rate_", "Revision",
        "EditionIdentifier", "NeedAppearances",
        "Underwriter", "CarrierCode", "PolicyNumber_Carrier",
    )
    return any(s in field for s in _NONFILLABLE_SUBSTRINGS)


def map_facts_to_form(facts: dict, schema: dict, form_id: str = "", raw_text: str = "") -> Tuple[dict, dict]:
    if not schema:
        return {}, {}

    mapped     = {}
    unmatched  = {}
    confidence = {}

    # Load persisted field→fact_key map and the set of fields that were originally
    # AI-mapped. The ai_set persists across runs so those fields keep "low_confidence".
    cached_fieldmap, cached_ai_set = _load_fieldmap(form_id)
    new_fieldmap = dict(cached_fieldmap)
    new_ai_set   = set(cached_ai_set)

    # Fields whose Pass 1 values are authoritative and should NOT be overridden by
    # LLM Call 2: address decomposition (_addr_*/_loc_*), schedule rows, and
    # indicator/checkbox fields (derived from flags, not raw text values).
    _pass1_authoritative: set = set()

    # Counters for detailed pipeline logging
    cnt_schema          = len(schema)
    cnt_cached_hit      = 0   # fields resolved from cached fact_key (non-null)
    cnt_cached_null_skip = 0  # cached-null entries that are truly non-fillable → skipped
    cnt_cached_null_retry = 0 # cached-null entries for fillable fields → retried via GPT
    cnt_deterministic   = 0   # fields resolved by deterministic rules (not cached)

    for field in schema.keys():
        if field in cached_fieldmap:
            cached_key = cached_fieldmap[field]

            # Schedule fields cached with a list-fact-key must re-resolve by row index
            # each call (different documents have different list lengths).
            sched = _resolve_schedule_row(field, facts)
            if sched is not _SCHED_SKIP:
                if sched is not None:
                    mapped[field] = sched
                    cnt_cached_hit += 1
                    _pass1_authoritative.add(field)
                # sched==None means row out-of-range → leave mapped[field] unset (blank)
            elif cached_key is None:
                # Cached None means GPT previously found no mapping OR the field was
                # explicitly classified non-fillable. We only accept the cached null when
                # the field is truly non-fillable (carrier-computed / admin / signature).
                # For all other fields we retry via GPT so a fresh raw-text pass can fill them.
                if _is_nonfillable_field(field):
                    mapped[field] = None          # accepted: truly non-fillable
                    cnt_cached_null_skip += 1
                    _pass1_authoritative.add(field)
                else:
                    # Fillable field whose GPT pass previously returned null — retry.
                    # First try deterministic indicator derivation; if that returns a
                    # value we accept it and DON'T need GPT. Indicators are authoritative.
                    ind = _derive_indicator(field, facts)
                    if ind is not None:
                        mapped[field] = ind
                        cnt_cached_hit += 1
                        _pass1_authoritative.add(field)
                    else:
                        unmatched[field] = schema[field]
                        cnt_cached_null_retry += 1
            else:
                val = _apply_fact_key(cached_key, facts)
                mapped[field] = val
                cnt_cached_hit += 1
                # Authoritative if: address-decomposed key (_addr_*/_loc_*), indicator
                # field, or nonfillable (Signature, Premium, Rate, etc.).
                # All other cached fact-key fields go to LLM Call 2 for raw-text confirmation.
                if (
                    (isinstance(cached_key, str) and cached_key.startswith("_"))
                    or "Indicator" in field
                    or _is_nonfillable_field(field)
                ):
                    _pass1_authoritative.add(field)
                else:
                    unmatched[field] = schema[field]
        else:
            result = _deterministic_map(field, facts)
            if result == "UNMATCHED":
                unmatched[field] = schema[field]
            else:
                mapped[field] = result
                cnt_deterministic += 1
                # Persist the matched fact_key so this field is free next run.
                rule_fact_key = None   # fact_key from _ACORD_FIELD_RULES (None = no match or explicit null)
                for pattern, fact_key in _ACORD_FIELD_RULES:
                    if pattern in field:
                        new_fieldmap[field] = fact_key
                        rule_fact_key = fact_key     # may be None for explicit-null rules
                        break
                # Classify: authoritative (Pass 1 keeps) vs raw-text-eligible (LLM Call 2)
                #
                # Authoritative cases:
                #   1. Address decomposition: fact_key starts with "_" (_addr_*, _loc_*)
                #   2. Indicator/checkbox fields: value derived from flags, not raw text
                #   3. Nonfillable fields: Signature, Premium, Rate, etc. — no LLM needed
                #   4. rule_fact_key is None: either an explicit-null rule (field intentionally
                #      unmapped) or no _ACORD_FIELD_RULES match (resolved by _derive_indicator)
                is_addr_key    = isinstance(rule_fact_key, str) and rule_fact_key.startswith("_")
                is_indicator   = "Indicator" in field
                is_nonfillable = _is_nonfillable_field(field)

                if is_addr_key or is_indicator or is_nonfillable or rule_fact_key is None:
                    _pass1_authoritative.add(field)
                else:
                    # Non-address, non-indicator, fillable, non-null fact_key mapping:
                    # send to LLM Call 2 so raw document text can confirm/override.
                    unmatched[field] = schema[field]

    logger.info(
        "map_facts PIPELINE form=%s | schema=%d cached_hit=%d det=%d "
        "null_skip=%d null_retry=%d gpt_fields=%d pass1_auth=%d",
        form_id or "unknown",
        cnt_schema, cnt_cached_hit, cnt_deterministic,
        cnt_cached_null_skip, cnt_cached_null_retry, len(unmatched),
        len(_pass1_authoritative),
    )

    if unmatched:
        logger.info(
            "map_facts GPT_ELIGIBLE form=%s | fields=%d raw_text_chars=%d",
            form_id or "unknown", len(unmatched), len(raw_text),
        )
        gpt_result       = _fill_unmatched_with_gpt(unmatched, facts, form_id, raw_text=raw_text)
        gpt_values       = gpt_result["filled_values"]
        gpt_mappings     = gpt_result["new_mappings"]
        gpt_raw_fields   = gpt_result.get("raw_text_fields", set())
        gpt_filled_set   = set(gpt_values.keys())

        # Apply GPT values and update fieldmap cache.
        # Raw-text-sourced fields get fact_key=None — document-specific, not reusable.
        # For cached-null-retry fields: only persist a new None mapping if GPT
        # also returned null AND the field is non-fillable; otherwise leave the
        # existing cached None so we retry again on the next run.
        # Pass 1 authoritative fields (address decomposition, schedule rows, indicators)
        # keep their Pass 1 value — GPT raw-text fill does not override them.
        for field in unmatched:
            fact_key = None if field in gpt_raw_fields else gpt_mappings.get(field)
            gpt_returned_null = field not in gpt_values
            was_cached_null   = field in cached_fieldmap and cached_fieldmap[field] is None

            if was_cached_null and gpt_returned_null:
                # GPT still can't fill it — keep the cached null so it retries next
                # time (don't overwrite with another null that would look fresh).
                pass
            else:
                new_fieldmap[field] = fact_key   # cache non-null key or confirmed null

            if field in gpt_values and field not in _pass1_authoritative:
                # LLM Call 2 found a value in raw text — use it as the primary result.
                # If Pass 1 also had a value it is superseded (raw text is ground truth).
                mapped[field] = gpt_values[field]
            elif field in gpt_values and field in _pass1_authoritative:
                # Pass 1 is authoritative for this field; keep Pass 1 value.
                mapped.setdefault(field, gpt_values[field])
            else:
                mapped.setdefault(field, None)
            if fact_key is not None:
                new_ai_set.add(field)

        logger.info(
            "map_facts GPT_DONE form=%s | gpt_filled=%d/%d",
            form_id or "unknown", len(gpt_filled_set), len(unmatched),
        )
        _save_fieldmap(form_id, new_fieldmap, new_ai_set)

    else:
        gpt_filled_set = set()
        if new_fieldmap != cached_fieldmap:
            # Deterministic pass added new entries — persist even with no GPT batch.
            _save_fieldmap(form_id, new_fieldmap, new_ai_set)

    # On the very first run (no cached fieldmap) every filled field is unreviewed,
    # so mark them all low_confidence so pink highlights appear immediately.
    # On subsequent runs only truly AI-mapped fields stay pink; deterministic ones
    # transition to "filled" once the fieldmap is established.
    first_run = not cached_fieldmap

    for field, meta in schema.items():
        val       = mapped.get(field)
        has_value = val is not None and str(val).strip() not in ("", "null", "None")
        is_req    = meta.get("required", False) if isinstance(meta, dict) else False
        was_ai    = first_run or (field in unmatched) or (field in cached_ai_set) or (field in gpt_filled_set)
        if has_value:
            confidence[field] = "low_confidence" if was_ai else "filled"
        elif is_req and not _is_nonfillable_field(field):
            # Only paint yellow for genuinely fillable required fields.
            # Carrier-computed / admin / signature fields are never fillable so
            # marking them missing_required creates phantom yellow highlights.
            confidence[field] = "missing_required"
        else:
            confidence[field] = "low_confidence"

    confidence = apply_acord125_missing_field_highlights(form_id, facts, mapped, confidence)

    # Fill-rate: exclude fields whose fieldmap entry is explicitly null (carrier_computed /
    # not_fillable) — they are not theoretically fillable from a declaration page.
    fillable_fields = [f for f, v in new_fieldmap.items() if not f.startswith("__")]
    fillable_count  = len(fillable_fields) if fillable_fields else len(schema)
    total_filled    = sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("", "null", "None"))
    logger.info(f"Mapped {total_filled}/{fillable_count} fields (form_id={form_id or 'unknown'})")

    # Log every field that has a mapped fact_key but ended up empty — these are
    # extraction gaps that need investigation.
    for field, fact_key in new_fieldmap.items():
        if field.startswith("__") or fact_key is None:
            continue
        val = mapped.get(field)
        if val is None or str(val).strip() in ("", "null", "None"):
            logger.warning(
                f"FILL_MISS form={form_id or 'unknown'} field={field!r} "
                f"fact_key={fact_key!r} — fact value was empty/missing"
            )

    return mapped, confidence


def extract_form_fields_with_positions(path: str) -> List[dict]:
    fields: List[dict] = []
    if not os.path.exists(path):
        return fields
    try:
        pdf = pikepdf.open(path)
        for page_idx, page in enumerate(pdf.pages):
            raw_annots = page.get("/Annots", None)
            if raw_annots is None:
                continue
            try:
                annot_list = list(raw_annots)
            except Exception:
                continue
            for annot_ref in annot_list:
                try:
                    annot = annot_ref
                    if "/Widget" not in str(annot.get("/Subtype", "")):
                        continue
                    t = annot.get("/T")
                    if t is None:
                        parent = annot.get("/Parent")
                        if parent:
                            t = parent.get("/T")
                    if t is None:
                        continue
                    name = str(t)
                    rect = annot.get("/Rect")
                    if rect is None:
                        continue
                    x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                    if x1 > x2: x1, x2 = x2, x1
                    if y1 > y2: y1, y2 = y2, y1
                    ft_raw = annot.get("/FT")
                    if ft_raw is None:
                        parent = annot.get("/Parent")
                        if parent:
                            ft_raw = parent.get("/FT")
                    ft_str     = str(ft_raw) if ft_raw else "/Tx"
                    field_type = "checkbox" if "/Btn" in ft_str else "dropdown" if "/Ch" in ft_str else "text"
                    v = annot.get("/V")
                    if v is None:
                        parent = annot.get("/Parent")
                        if parent:
                            v = parent.get("/V")
                    val = ""
                    if v is not None:
                        sv = str(v)
                        if sv.startswith("/"):
                            sv = sv[1:]
                        val = sv if sv not in ("Off", "null", "None") else ""
                    fields.append({
                        "name": name, "page": page_idx,
                        "rect": {"x": round(x1, 2), "y": round(y1, 2),
                                 "width": round(x2 - x1, 2), "height": round(y2 - y1, 2)},
                        "type": field_type, "value": val,
                    })
                except Exception:
                    pass
        pdf.close()
    except Exception as ex:
        logger.error(f"extract_form_fields_with_positions error: {ex}")
    return fields


def get_page_dims_pikepdf(path: str) -> List[dict]:
    dims = []
    try:
        pdf = pikepdf.open(path)
        for page in pdf.pages:
            mb = page.get("/MediaBox", None)
            if mb:
                dims.append({"width": float(mb[2]) - float(mb[0]), "height": float(mb[3]) - float(mb[1])})
            else:
                dims.append({"width": 612.0, "height": 792.0})
        pdf.close()
    except Exception as ex:
        logger.error(f"get_page_dims_pikepdf error: {ex}")
    return dims


def regenerate_pdf_for_form(
    proc_session: dict,
    form_id: str,
    force: bool = False,
    user_signature: str = None,
) -> bytes:
    generated = proc_session.get("generated_forms", {})
    if form_id not in generated:
        raise HTTPException(404, f"Form {form_id} not generated")
    r          = generated[form_id]
    tpl        = os.path.join(TEMPLATE_DIR, r["form"]["template_file"])
    field_data = r.get("field_state") or r.get("mapped", {})
    confidence = r.get("confidence", {})

    if not force:
        # Only serve the cached signed PDF when the cache is still valid (non-empty hash).
        # An empty _pdf_cache_hash means client answers were applied after signing — must regen.
        if r.get("signature_applied") and r.get("pdf_bytes") and r.get("_pdf_cache_hash"):
            cached = r["pdf_bytes"]
            return cached if isinstance(cached, bytes) else bytes(cached)
        import hashlib
        state_hash  = hashlib.md5(json.dumps(field_data, sort_keys=True).encode()).hexdigest()
        cached_hash = r.get("_pdf_cache_hash")
        cached_bytes = r.get("pdf_bytes")
        if cached_bytes and cached_hash == state_hash:
            return cached_bytes if isinstance(cached_bytes, bytes) else bytes(cached_bytes)

    # Resolve which signature to use: prefer stored signature_b64, then fall back to
    # the caller-supplied user_signature (covers legacy sessions missing signature_b64).
    sig_b64 = None
    if r.get("signature_applied"):
        sig_b64 = r.get("signature_b64") or user_signature

    if sig_b64:
        # Regenerate with latest field values and re-stamp signature
        pdf_bytes = inject_signature_into_pdf(tpl, field_data, confidence, sig_b64)
    else:
        pdf_bytes = fill_pdf(tpl, field_data, confidence)

    import hashlib
    state_hash = hashlib.md5(json.dumps(field_data, sort_keys=True).encode()).hexdigest()
    generated[form_id]["pdf_bytes"]       = pdf_bytes
    generated[form_id]["_pdf_cache_hash"] = state_hash
    return pdf_bytes


def _get_page_content_scale(page) -> float:
    """Return the uniform scale factor applied by the first 'cm' operator in the
    page content stream, or 1.0 if none is found.

    Many ACORD templates open their content stream with a line like:
        0.12 0 0 0.12 0 0 cm
    which maps widget /Rect coordinates (in PDF user space) to a scaled internal
    coordinate system. When we append new content we must use the internal space,
    so all user-space coordinates need to be divided by this scale.

    Only handles the simple uniform-scale case (a == d, b == 0, c == 0, e == 0,
    f == 0). Returns 1.0 for any other transform so painting degrades gracefully.
    """
    import re as _re
    try:
        contents = page.get("/Contents")
        if contents is None:
            return 1.0
        if isinstance(contents, pikepdf.Array):
            raw = b"".join(bytes(s.read_bytes()) for s in contents)
        else:
            raw = bytes(contents.read_bytes())
        text = raw[:500].decode("latin-1", errors="replace")
        # Match "sx 0[.0] 0[.0] sy tx ty cm" — the zero components may be 0.00
        m = _re.search(
            r"([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s+cm",
            text,
        )
        if m:
            sx  = float(m.group(1))
            shx = float(m.group(2))
            shy = float(m.group(3))
            sy  = float(m.group(4))
            tx  = float(m.group(5))
            ty  = float(m.group(6))
            # Only trust as a pure uniform scale (no shear, no translation)
            if (abs(shx) < 0.001 and abs(shy) < 0.001
                    and abs(sx - sy) < 0.001
                    and abs(tx) < 0.001 and abs(ty) < 0.001
                    and sx > 0):
                return sx
    except Exception:
        pass
    return 1.0


def inject_signature_into_pdf(
    template_path: str,
    field_data: dict,
    confidence: dict,
    signature_b64: str,
) -> bytes:
    """Fill the PDF then paint the signature image directly into the page content
    stream at every signature-field rectangle.

    Painting into the content stream (not just adding an annotation) ensures the
    signature renders in every PDF viewer, including print dialogs and flattened
    exports that ignore annotations.
    """
    import base64
    filled_bytes = fill_pdf(template_path, field_data, confidence)
    try:
        b64_data = signature_b64
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        sig_raw = base64.b64decode(b64_data)
        sig_img = Image.open(io.BytesIO(sig_raw)).convert("RGBA")
    except Exception as ex:
        logger.error(f"Signature image decode failed: {ex}")
        return filled_bytes
    try:
        pdf = pikepdf.open(io.BytesIO(filled_bytes))
    except Exception as ex:
        logger.error(f"Cannot open filled PDF for signature injection: {ex}")
        return filled_bytes

    injected = 0
    try:
        for page_idx, page in enumerate(pdf.pages):
            raw_annots = page.get("/Annots")
            if raw_annots is None:
                continue
            try:
                annot_list = list(raw_annots)
            except Exception:
                continue

            # Collect signature field rects on this page, then remove the widget
            # annotations so the empty field boxes don't show through the image.
            sig_rects: List[tuple] = []   # (x1, y1, draw_w, draw_h, jpeg_bytes, px_w, px_h)
            annots_to_keep = []

            for annot_ref in annot_list:
                field_name = "?"
                try:
                    annot  = annot_ref
                    subtyp = str(annot.get("/Subtype", ""))
                    if "/Widget" not in subtyp:
                        annots_to_keep.append(annot_ref)
                        continue
                    ft_raw = annot.get("/FT")
                    if ft_raw is None:
                        try:
                            p = annot.get("/Parent")
                            if p is not None:
                                ft_raw = p.get("/FT")
                        except Exception:
                            pass
                    ft_str = str(ft_raw) if ft_raw is not None else ""
                    t = annot.get("/T")
                    if t is None:
                        try:
                            p = annot.get("/Parent")
                            if p is not None:
                                t = p.get("/T")
                        except Exception:
                            pass
                    field_name = str(t) if t is not None else ""
                    if not _is_signature_field(field_name, ft_str):
                        annots_to_keep.append(annot_ref)
                        continue
                    rect = annot.get("/Rect")
                    if rect is None:
                        annots_to_keep.append(annot_ref)
                        continue
                    x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
                    if x1 > x2: x1, x2 = x2, x1
                    if y1 > y2: y1, y2 = y2, y1
                    field_w = max(x2 - x1, 1.0)
                    field_h = max(y2 - y1, 1.0)

                    # Scale signature to fit inside the field, preserving aspect ratio
                    img_w, img_h = sig_img.size
                    img_ratio    = img_w / max(img_h, 1)
                    field_ratio  = field_w / max(field_h, 1)
                    if img_ratio >= field_ratio:
                        draw_w = field_w
                        draw_h = field_w / img_ratio
                    else:
                        draw_h = field_h
                        draw_w = field_h * img_ratio
                    draw_w = min(draw_w, field_w)
                    draw_h = min(draw_h, field_h)
                    # Centre inside the field
                    draw_x = x1 + (field_w - draw_w) / 2.0
                    draw_y = y1 + (field_h - draw_h) / 2.0

                    # Rasterise at 4× the point size for crisp output
                    px_w = max(int(draw_w * 4), 4)
                    px_h = max(int(draw_h * 4), 4)
                    sig_resized = sig_img.resize((px_w, px_h), Image.LANCZOS)
                    bg = Image.new("RGB", (px_w, px_h), (255, 255, 255))
                    if sig_resized.mode == "RGBA":
                        bg.paste(sig_resized, mask=sig_resized.split()[3])
                    else:
                        bg.paste(sig_resized.convert("RGB"))
                    jpeg_buf = io.BytesIO()
                    bg.save(jpeg_buf, format="JPEG", quality=92)
                    sig_rects.append((draw_x, draw_y, draw_w, draw_h,
                                      jpeg_buf.getvalue(), px_w, px_h))
                    # Drop the widget annotation — the image replaces it
                    injected += 1
                except Exception as field_ex:
                    logger.warning(f"Sig field error page={page_idx} field={field_name!r}: {field_ex}")
                    annots_to_keep.append(annot_ref)

            page["/Annots"] = pikepdf.Array(annots_to_keep)

            if not sig_rects:
                continue

            # Detect the page's global CTM scale so we can paint in the correct
            # coordinate space.  Many ACORD templates open their content stream
            # with "sx 0 0 sy 0 0 cm" which scales all internal coordinates.
            # Widget /Rect values are always in PDF user-space (post-transform),
            # but when we append new content the current graphics state already
            # has that scale applied — so we must invert it.
            page_scale = _get_page_content_scale(page)  # e.g. 0.12 for ACORD 125

            # Paint each signature image directly into the page content stream
            for draw_x, draw_y, draw_w, draw_h, jpeg_bytes, px_w, px_h in sig_rects:
                try:
                    # Register the image XObject on this page's /Resources
                    img_xobj = pikepdf.Stream(pdf, jpeg_bytes)
                    img_xobj["/Type"]             = pikepdf.Name("/XObject")
                    img_xobj["/Subtype"]          = pikepdf.Name("/Image")
                    img_xobj["/Width"]            = px_w
                    img_xobj["/Height"]           = px_h
                    img_xobj["/ColorSpace"]       = pikepdf.Name("/DeviceRGB")
                    img_xobj["/BitsPerComponent"] = 8
                    img_xobj["/Filter"]           = pikepdf.Name("/DCTDecode")
                    indirect_img = pdf.make_indirect(img_xobj)

                    # Find a unique XObject name for this page
                    if "/Resources" not in page:
                        page["/Resources"] = pikepdf.Dictionary()
                    res = page["/Resources"]
                    if "/XObject" not in res:
                        res["/XObject"] = pikepdf.Dictionary()
                    xobj_name = "/SigImg"
                    counter = 0
                    while pikepdf.Name(xobj_name) in res["/XObject"]:
                        counter += 1
                        xobj_name = f"/SigImg{counter}"
                    res["/XObject"][pikepdf.Name(xobj_name)] = indirect_img

                    # Convert user-space coordinates to the page's internal space.
                    # Widget rects are in user space; the content stream may have a
                    # global scale (e.g. 0.12) already applied, so we divide by it.
                    if page_scale and page_scale != 1.0:
                        ix = draw_x / page_scale
                        iy = draw_y / page_scale
                        iw = draw_w / page_scale
                        ih = draw_h / page_scale
                    else:
                        ix, iy, iw, ih = draw_x, draw_y, draw_w, draw_h

                    # q ... cm Image Do Q — save/restore graphics state so we
                    # don't disturb any transforms that follow in the stream.
                    paint_ops = (
                        f"q "
                        f"{iw:.4f} 0 0 {ih:.4f} {ix:.4f} {iy:.4f} cm "
                        f"{xobj_name} Do "
                        f"Q\n"
                    ).encode("latin-1")

                    # Append paint ops after the existing page content
                    existing = page.get("/Contents")
                    paint_stream = pikepdf.Stream(pdf, paint_ops)
                    if existing is None:
                        page["/Contents"] = pdf.make_indirect(paint_stream)
                    elif isinstance(existing, pikepdf.Array):
                        existing.append(pdf.make_indirect(paint_stream))
                        page["/Contents"] = existing
                    else:
                        page["/Contents"] = pikepdf.Array([
                            existing if existing.is_indirect else pdf.make_indirect(existing),
                            pdf.make_indirect(paint_stream),
                        ])
                except Exception as paint_ex:
                    logger.warning(f"Sig paint error page={page_idx}: {paint_ex}")

        # Clean up AcroForm: remove signature field entries so readers don't
        # show an empty signature widget on top of the painted image.
        if injected > 0 and "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            # NeedAppearances=false since we've painted directly
            acro["/NeedAppearances"] = pikepdf.Boolean(False)
            fields_arr = acro.get("/Fields")
            if fields_arr is not None:
                def _remove_sig_fields(arr):
                    kept = []
                    for item in arr:
                        try:
                            t     = item.get("/T")
                            ft_r  = item.get("/FT")
                            name  = str(t) if t is not None else ""
                            ft_s  = str(ft_r) if ft_r is not None else ""
                            if _is_signature_field(name, ft_s):
                                continue
                            kids = item.get("/Kids")
                            if kids:
                                item["/Kids"] = pikepdf.Array(_remove_sig_fields(list(kids)))
                            kept.append(item)
                        except Exception:
                            kept.append(item)
                    return kept
                acro["/Fields"] = pikepdf.Array(_remove_sig_fields(list(fields_arr)))

        out_buf = io.BytesIO()
        pdf.save(out_buf)
        pdf.close()
        out_buf.seek(0)
        logger.info(f"Signature injection: {injected} field(s) painted into content stream")
        return out_buf.getvalue()
    except Exception as ex:
        logger.error(f"Signature injection failed: {ex}", exc_info=True)
        try:
            pdf.close()
        except Exception:
            pass
        return filled_bytes
