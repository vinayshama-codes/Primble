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

    # ── WC Officers / Owners (ACORD 130, 138) ───────────────────────────────
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
    ("Producer_FaxNumber",                                 None),
    ("Producer_AuthorizedRepresentative",                  None),

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
    ("NamedInsured_WebsiteAddress",                        None),
    ("NamedInsured_BusinessStartDate",                     "years_in_business"),
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


def _fill_and_highlight(arr, data: dict, confidence: dict, counter: list):
    for item in arr:
        try:
            t    = item.get("/T", None)
            kids = item.get("/Kids", None)
            if t:
                name = str(t)
                val  = data.get(name)
                if val is not None and str(val).strip() not in ("", "null", "None"):
                    item["/V"] = pikepdf.String(str(val))
                    if "/AP" in item:
                        del item["/AP"]
                    counter[0] += 1
            if kids:
                _fill_and_highlight(kids, data, confidence, counter)
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
            _fill_and_highlight(acro.get("/Fields", []), data, confidence or {}, counter)
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
    # Lines of business — ACORD 125
    "Policy_LineOfBusiness_BusinessAutoIndicator": ("lines_of_business", "auto"),
    "Policy_LineOfBusiness_CommercialGeneralLiability": ("lines_of_business", "gl"),
    "Policy_LineOfBusiness_CommercialProperty": ("lines_of_business", "property"),
    "Policy_LineOfBusiness_UmbrellaIndicator": ("lines_of_business", "umbrella"),
    "Policy_LineOfBusiness_WorkersCompensation": ("lines_of_business", "workers comp"),
    "Policy_LineOfBusiness_BusinessOwnersIndicator": ("lines_of_business", "bop"),
    "Policy_LineOfBusiness_CrimeIndicator": ("lines_of_business", "crime"),
    "Policy_LineOfBusiness_GarageAndDealersIndicator": ("lines_of_business", "garage"),
    # Hired/non-owned auto
    "Vehicle_HiredIndicator":    ("hired_auto_indicator", "yes"),
    "Vehicle_HiredAutosIndicator": ("hired_auto_indicator", "yes"),
    "Vehicle_NonOwnedIndicator": ("non_owned_auto_indicator", "yes"),
    "Vehicle_NonOwnedAutosIndicator": ("non_owned_auto_indicator", "yes"),
    # Property valuation
    "ValuationCode_ReplacementCostIndicator": ("valuation_method", "rcv"),
    "ValuationCode_ActualCashValueIndicator": ("valuation_method", "acv"),
    # Loss history
    "LossHistory_NoPriorLossesIndicator": ("num_claims", "0"),
    # New / renewal
    "CommercialPolicy_NewBusinessIndicator": ("is_renewal", "no"),
    "CommercialPolicy_RenewalIndicator":     ("is_renewal", "yes"),
    # Umbrella form type
    "ExcessUmbrella_OccurrenceIndicator": ("gl_form_type", "occurrence"),
    "ExcessUmbrella_ClaimsMadeIndicator": ("gl_form_type", "claims"),
    # WC statutory limits indicator
    "WorkersCompensationEmployersLiability_WorkersCompensationStatutoryLimitIndicator": ("wc_el_each_accident", "statutory"),
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
            if raw is None:
                return None
            if isinstance(raw, bool):
                # Direct boolean fact: treat match_val=="yes"/"true" as "truthy expected"
                expected_true = match_val.lower() in {"yes", "true", "1"}
                return "Yes" if (raw == expected_true) else "No"
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


_RAW_TEXT_SKIP_PATTERNS = [
    "Indicator", "Signature", "InsurerLetterCode",
    "Attachment_", "Hazard_", "Premium", "Rate_", "Revision",
    "EditionIdentifier", "_Sig", "NeedAppearances",
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


# Chunk size for raw_text in form-fill pass. OpenAI gpt-4o-mini supports 128k
# tokens (~512k chars). We use 40k chars per chunk — leaves ample room for the
# fields block and structured facts in the same prompt.
_FORM_FILL_RAW_CHUNK_CHARS = int(os.getenv("FORM_FILL_RAW_CHUNK_CHARS", str(40_000)))
# Max retries per batch call
_FORM_FILL_BATCH_RETRIES = int(os.getenv("FORM_FILL_BATCH_RETRIES", "3"))


def _fill_unmatched_with_gpt(
    unmatched_fields: dict,
    facts: dict,
    form_id: str,
    model: str = None,
    raw_text: str = "",
) -> dict:
    """GPT form-fill: fills unmatched fields from structured facts + full raw document text.

    Uses a dedicated AsyncOpenAI client. Form-fill always uses OpenAI regardless
    of LLM_PROVIDER (extraction provider).

    Architecture — chunked full-coverage pass:
      STEP A: raw_text is split into semantic chunks of _FORM_FILL_RAW_CHUNK_CHARS.
              Every character is covered — no truncation.
      STEP B: Each chunk is sent independently to the LLM with the fields block
              and structured facts. Candidate values are collected per chunk.
      STEP C: Per-field conflict resolution: structured-facts values win; for
              raw-text-sourced values the most-frequent candidate across chunks wins.
      STEP D: Final merged field map returned.

    Source priority:
      SOURCE 1 — PII-filtered structured facts (stable, doc-independent mappings)
      SOURCE 2 — Raw OCR text chunks (full coverage, no truncation)

    Returns:
        {
            "filled_values":   {field_name: value_string, ...},
            "new_mappings":    {field_name: fact_key_or_null, ...},
            "raw_text_fields": {field_name},
            "model_used":      str,
        }
    """
    if not unmatched_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "model_used": model or GPT_MODEL}

    try:
        _client = _get_openai_form_fill_client()
    except RuntimeError as _e:
        logger.warning("gpt_fill: %s — skipping GPT form fill pass", _e)
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "model_used": model or GPT_MODEL}

    llm_model = model or GPT_MODEL

    # ── PII-filtered facts for LLM prompt ────────────────────────────────────
    facts_for_llm = {
        k: str(_fv(facts, k))[:120]
        for k in facts
        if k not in _PII_EXCLUDE_KEYS
        and _fv(facts, k) is not None
        and not isinstance(_fv(facts, k), (list, dict))
    }

    # ── Split raw_text into chunks — ZERO truncation ─────────────────────────
    # Every character of every uploaded document participates in form-fill.
    raw_text_used = bool(raw_text and raw_text.strip())
    if raw_text_used:
        # Split on paragraph/line boundaries to avoid mid-sentence cuts.
        raw_chunks: List[str] = []
        remaining = raw_text
        while remaining:
            if len(remaining) <= _FORM_FILL_RAW_CHUNK_CHARS:
                raw_chunks.append(remaining)
                break
            # Find last paragraph break before the limit so we don't split mid-sentence.
            split_at = remaining.rfind("\n\n", 0, _FORM_FILL_RAW_CHUNK_CHARS)
            if split_at == -1:
                split_at = remaining.rfind("\n", 0, _FORM_FILL_RAW_CHUNK_CHARS)
            if split_at == -1:
                split_at = _FORM_FILL_RAW_CHUNK_CHARS
            raw_chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")
        logger.info(
            "gpt_fill: form=%s raw_text_chars=%d raw_chunks=%d chunk_size=%d",
            form_id, len(raw_text), len(raw_chunks), _FORM_FILL_RAW_CHUNK_CHARS,
        )
    else:
        raw_chunks = [""]  # single empty chunk — facts-only pass

    # ── Filter out schedule fields and skip-pattern fields ───────────────────
    eligible_fields = {
        f: meta
        for f, meta in unmatched_fields.items()
        if not _is_schedule_field(f)
        and not any(p in f for p in _RAW_TEXT_SKIP_PATTERNS)
    }

    if not eligible_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "model_used": llm_model}

    field_list = list(eligible_fields.keys())

    # Accumulate per-field candidates: {field: {value_str: count}}
    candidate_counts: Dict[str, Dict[str, int]] = {f: {} for f in field_list}
    # Track whether a structured-facts mapping was found (persisted to fieldmap cache)
    all_mappings: Dict[str, Optional[str]] = {}
    # Track which fields were sourced from raw_text (not cached as structural mappings)
    all_raw_fields: set = set()

    fact_lines   = [f'  "{k}": "{v}"' for k, v in facts_for_llm.items()]
    fact_context = "{\n" + ",\n".join(fact_lines) + "\n}"

    # ── STEP B: send each (batch × chunk) combination to the LLM ─────────────
    for chunk_idx, raw_chunk in enumerate(raw_chunks):
        raw_text_section = (
            f"\n\n=== SOURCE 2: RAW DOCUMENT TEXT (chunk {chunk_idx + 1}/{len(raw_chunks)}) ===\n{raw_chunk}"
            if raw_text_used and raw_chunk.strip() else ""
        )

        for batch_start in range(0, len(field_list), GPT_BATCH_SIZE):
            batch_keys = field_list[batch_start : batch_start + GPT_BATCH_SIZE]
            batch_meta = {k: eligible_fields[k] for k in batch_keys}

            field_specs = []
            for f in batch_keys:
                info = batch_meta[f] if isinstance(batch_meta[f], dict) else {}
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
                field_specs.append(spec)

            fields_block = "\n".join(field_specs)

            prompt = (
                f"You are filling ACORD form {form_id} for an insurance submission.\n"
                "You have TWO data sources. Use SOURCE 1 (structured facts) first. "
                "Fall back to SOURCE 2 (raw document text) only when SOURCE 1 has no answer.\n\n"
                "Return two JSON objects:\n"
                '  "values":   {FieldName: "exact_value_or_null"}  — value to write into each field\n'
                '  "mappings": {FieldName: "fact_key_or_null"}     — fact key from SOURCE 1 only\n'
                '  "raw_text_sourced": [FieldName, ...]            — fields whose value came from SOURCE 2\n\n'
                "Rules for values:\n"
                "  1. Extract the EXACT value — do not paraphrase or invent.\n"
                "  2. Use null if no source has the answer. Prefer null over a wrong value.\n"
                "  3. For checkbox fields (Yes/No): return 'Yes' or 'No' only.\n"
                "  4. For dollar amounts: include $ and commas as found (e.g. $1,000,000).\n"
                "  5. Do NOT fill premium/rate/underwriter-computed fields — return null.\n\n"
                "Rules for mappings:\n"
                "  1. Use ONLY exact key names from SOURCE 1 extracted_facts.\n"
                "  2. A mapping is the structural field→fact relationship — not document-specific.\n"
                "  3. Use null if no single fact key cleanly maps to this field.\n"
                "  4. NEVER set a mapping for fields in raw_text_sourced — those are null.\n\n"
                f"=== SOURCE 1: EXTRACTED FACTS ===\n{fact_context}\n\n"
                f"Fields to fill ({form_id}):\n{fields_block}"
                f"{raw_text_section}\n\n"
                'Return ONLY valid JSON: {"values": {...}, "mappings": {...}, "raw_text_sourced": [...]}'
            )

            # Per-batch retry
            batch_success = False
            for attempt in range(_FORM_FILL_BATCH_RETRIES):
                try:
                    async def _call_openai(_prompt=prompt):
                        resp = await _client.chat.completions.create(
                            model=llm_model,
                            messages=[{"role": "user", "content": _prompt}],
                            temperature=GPT_TEMPERATURE,
                            response_format={"type": "json_object"},
                        )
                        return resp.choices[0].message.content or ""

                    raw_resp = _run_coro_sync(_call_openai())

                    result            = json.loads(raw_resp)
                    batch_values      = result.get("values",          {}) or {}
                    batch_mappings    = result.get("mappings",        {}) or {}
                    batch_raw_sourced = set(result.get("raw_text_sourced", []) or [])

                    # Validate mapping keys against full registry (reject hallucinations)
                    for field, fact_key in batch_mappings.items():
                        if field in batch_raw_sourced:
                            fact_key = None
                        elif fact_key is not None and fact_key not in _FULL_REGISTRY_KEYS:
                            logger.debug(
                                "gpt_fill: rejected hallucinated fact_key=%r field=%r form=%s",
                                fact_key, field, form_id,
                            )
                            fact_key = None
                        # Only set mapping on first (facts-pass) chunk — it's doc-independent
                        if chunk_idx == 0 and field not in all_mappings:
                            all_mappings[field] = fact_key

                    # Accumulate per-field candidate counts for conflict resolution
                    for field, value in batch_values.items():
                        if value and str(value).strip() not in ("", "null", "None"):
                            vstr = str(value).strip()
                            candidate_counts[field][vstr] = candidate_counts[field].get(vstr, 0) + 1
                            if field in batch_raw_sourced:
                                all_raw_fields.add(field)

                    logger.info(
                        "gpt_fill: form=%s chunk=%d/%d batch_start=%d sent=%d filled=%d raw_sourced=%d",
                        form_id, chunk_idx + 1, len(raw_chunks),
                        batch_start, len(batch_keys),
                        sum(1 for v in batch_values.values() if v and str(v).strip() not in ("", "null", "None")),
                        len(batch_raw_sourced),
                    )
                    batch_success = True
                    break  # success — no more retries needed

                except Exception as ex:
                    if attempt < _FORM_FILL_BATCH_RETRIES - 1:
                        import time as _time
                        wait = 2 ** attempt
                        logger.warning(
                            "gpt_fill: batch failed form=%s chunk=%d batch_start=%d attempt=%d/%d "
                            "retrying in %ds — %s",
                            form_id, chunk_idx + 1, batch_start,
                            attempt + 1, _FORM_FILL_BATCH_RETRIES, wait, ex,
                        )
                        _time.sleep(wait)
                    else:
                        logger.warning(
                            "gpt_fill: batch permanently failed form=%s chunk=%d batch_start=%d — %s",
                            form_id, chunk_idx + 1, batch_start, ex,
                        )

    # ── STEP C: conflict resolution — pick winner per field ──────────────────
    # Structured-facts values (SOURCE 1) always win over raw-text values.
    # Among raw-text values, the most-frequent candidate across chunks wins.
    all_filled: dict = {}
    for field, candidates in candidate_counts.items():
        if not candidates:
            continue
        # SOURCE 1 check: if there's a mapping AND facts have a non-empty value, prefer it.
        fact_key = all_mappings.get(field)
        if fact_key and _fv(facts, fact_key) is not None:
            src1_val = str(_fv(facts, fact_key)).strip()
            if src1_val and src1_val.lower() not in ("", "null", "none"):
                all_filled[field] = src1_val
                continue
        # SOURCE 2: pick the highest-frequency candidate (most chunks agreed)
        winner = max(candidates, key=lambda v: candidates[v])
        all_filled[field] = winner

    # ── STEP D: audit log ─────────────────────────────────────────────────────
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
        "gpt_fill DONE: form=%s fields_filled=%d/%d raw_chunks=%d model=%s",
        form_id, len(all_filled), len(eligible_fields), len(raw_chunks), llm_model,
    )

    return {
        "filled_values":   all_filled,
        "new_mappings":    all_mappings,
        "raw_text_fields": all_raw_fields,
        "model_used":      llm_model,
    }


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

    for field in schema.keys():
        if field in cached_fieldmap:
            # Schedule fields cached with a list-fact-key must re-resolve by row index
            # each call (different documents have different list lengths).
            sched = _resolve_schedule_row(field, facts)
            if sched is not _SCHED_SKIP:
                if sched is not None:
                    mapped[field] = sched
                # sched==None means row out-of-range → leave mapped[field] unset (blank)
            else:
                mapped[field] = _apply_fact_key(cached_fieldmap[field], facts)
        else:
            result = _deterministic_map(field, facts)
            if result == "UNMATCHED":
                unmatched[field] = schema[field]
            else:
                mapped[field] = result
                # Persist the matched fact_key so this field is free next run.
                for pattern, fact_key in _ACORD_FIELD_RULES:
                    if pattern in field:
                        new_fieldmap[field] = fact_key
                        break

    if unmatched:
        gpt_result       = _fill_unmatched_with_gpt(unmatched, facts, form_id, raw_text=raw_text)
        gpt_values       = gpt_result["filled_values"]
        gpt_mappings     = gpt_result["new_mappings"]
        gpt_raw_fields   = gpt_result.get("raw_text_fields", set())
        gpt_filled_set   = set(gpt_values.keys())

        # Apply GPT values and update fieldmap cache.
        # Raw-text-sourced fields get fact_key=None so they are never cached as
        # structural mappings (values are document-specific, not reusable).
        for field in unmatched:
            fact_key = None if field in gpt_raw_fields else gpt_mappings.get(field)
            new_fieldmap[field] = fact_key               # always cache, even None
            if field in gpt_values:
                mapped[field] = gpt_values[field]
            else:
                mapped.setdefault(field, None)
            if fact_key is not None:
                new_ai_set.add(field)

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
        elif is_req:
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


def inject_signature_into_pdf(
    template_path: str,
    field_data: dict,
    confidence: dict,
    signature_b64: str,
) -> bytes:
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
            annots_to_keep = []
            for annot_ref in annot_list:
                field_name = "?"
                try:
                    annot = annot_ref
                    if "/Widget" not in str(annot.get("/Subtype", "")):
                        annots_to_keep.append(annot_ref)
                        continue
                    ft_raw = annot.get("/FT")
                    if ft_raw is None:
                        try:
                            parent_obj = annot.get("/Parent")
                            if parent_obj is not None:
                                ft_raw = parent_obj.get("/FT")
                        except Exception:
                            pass
                    ft_str = str(ft_raw) if ft_raw is not None else ""
                    t = annot.get("/T")
                    if t is None:
                        try:
                            parent_obj = annot.get("/Parent")
                            if parent_obj is not None:
                                t = parent_obj.get("/T")
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
                    INSET   = 0.0
                    field_w = max(x2 - x1 - INSET * 2, 1.0)
                    field_h = max(y2 - y1 - INSET * 2, 1.0)
                    img_w, img_h = sig_img.size
                    img_ratio   = img_w / max(img_h, 1)
                    field_ratio = field_w / max(field_h, 1)
                    if img_ratio >= field_ratio:
                        draw_w = field_w
                        draw_h = field_w / img_ratio
                    else:
                        draw_h = field_h
                        draw_w = field_h * img_ratio
                    draw_w = min(draw_w, field_w)
                    draw_h = min(draw_h, field_h)
                    draw_x = x1 + INSET + (field_w - draw_w) / 2.0
                    draw_y = y1 + INSET + (field_h - draw_h) / 2.0
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
                    jpeg_bytes = jpeg_buf.getvalue()
                    img_xobj = pikepdf.Stream(pdf, jpeg_bytes)
                    img_xobj["/Type"]             = pikepdf.Name("/XObject")
                    img_xobj["/Subtype"]          = pikepdf.Name("/Image")
                    img_xobj["/Width"]            = px_w
                    img_xobj["/Height"]           = px_h
                    img_xobj["/ColorSpace"]       = pikepdf.Name("/DeviceRGB")
                    img_xobj["/BitsPerComponent"] = 8
                    img_xobj["/Filter"]           = pikepdf.Name("/DCTDecode")
                    indirect_img = pdf.make_indirect(img_xobj)
                    img_name = pikepdf.Name("/SigImg")
                    ap_ops = (
                        f"q {draw_w:.4f} 0 0 {draw_h:.4f} 0 0 cm /SigImg Do Q"
                    ).encode("latin-1")
                    ap_stream = pikepdf.Stream(pdf, ap_ops)
                    ap_stream["/Type"]    = pikepdf.Name("/XObject")
                    ap_stream["/Subtype"] = pikepdf.Name("/Form")
                    ap_stream["/BBox"]    = pikepdf.Array([pikepdf.Real(0), pikepdf.Real(0), pikepdf.Real(draw_w), pikepdf.Real(draw_h)])
                    ap_stream["/Resources"] = pikepdf.Dictionary(XObject=pikepdf.Dictionary())
                    ap_stream["/Resources"]["/XObject"][img_name] = indirect_img
                    indirect_ap  = pdf.make_indirect(ap_stream)
                    stamp_rect   = pikepdf.Array([pikepdf.Real(draw_x), pikepdf.Real(draw_y), pikepdf.Real(draw_x + draw_w), pikepdf.Real(draw_y + draw_h)])
                    stamp_annot  = pikepdf.Dictionary(Type=pikepdf.Name("/Annot"), Subtype=pikepdf.Name("/Stamp"), Rect=stamp_rect, F=pikepdf.Integer(4), AP=pikepdf.Dictionary(N=indirect_ap))
                    indirect_stamp = pdf.make_indirect(stamp_annot)
                    annots_to_keep.append(indirect_stamp)
                    injected += 1
                except Exception as field_ex:
                    logger.warning(f"Sig field error page={page_idx} field={field_name!r}: {field_ex}")
                    annots_to_keep.append(annot_ref)
            page["/Annots"] = pikepdf.Array(annots_to_keep)

        if injected > 0 and "/AcroForm" in pdf.Root:
            acro       = pdf.Root["/AcroForm"]
            acro["/NeedAppearances"] = pikepdf.Boolean(True)
            fields_arr = acro.get("/Fields")
            if fields_arr is not None:
                def _remove_sig_fields(arr):
                    result = []
                    for item in arr:
                        try:
                            t      = item.get("/T")
                            ft_raw = item.get("/FT")
                            ft_s   = str(ft_raw) if ft_raw is not None else ""
                            name   = str(t) if t is not None else ""
                            if _is_signature_field(name, ft_s):
                                continue
                            kids = item.get("/Kids")
                            if kids:
                                item["/Kids"] = pikepdf.Array(_remove_sig_fields(list(kids)))
                            result.append(item)
                        except Exception:
                            result.append(item)
                    return result
                acro["/Fields"] = pikepdf.Array(_remove_sig_fields(list(fields_arr)))

        out_buf = io.BytesIO()
        pdf.save(out_buf)
        pdf.close()
        out_buf.seek(0)
        result = out_buf.getvalue()
        logger.info(f"Signature injection: {injected} field(s) stamped")
        return result
    except Exception as ex:
        logger.error(f"Signature injection failed: {ex}", exc_info=True)
        try:
            pdf.close()
        except Exception:
            pass
        return filled_bytes
