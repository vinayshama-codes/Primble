import concurrent.futures
import io
import json
import logging
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pikepdf
from PIL import Image
from fastapi import HTTPException

from config.settings import TEMPLATE_DIR, FORMS_DB_DIR, FORMS_SCHEMAS_DIR, groq_chat
from utils.helpers import _parse_address
from typing import NamedTuple
from services.extraction_service import _fv, ACTIVE_MODEL
from services.fact_registry import FACT_REGISTRY
from services.normalization import detect_no_loss_assertion

logger = logging.getLogger(__name__)

# ── GPT model config — env-driven so any OpenAI model is selectable with zero code changes ──
GPT_MODEL       = os.getenv("GPT_MODEL",       "gpt-4.1-nano")
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
        _openai_form_fill_client = _AsyncOpenAI(
            api_key=api_key,
            http_client=httpx.AsyncClient(
                timeout=float(os.getenv("LLM_REQUEST_TIMEOUT", "120")),
            ),
        )
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

# Per-row PII sub-keys stripped from schedule list facts (e.g. auto_drivers)
# before they reach an LLM prompt, rather than excluding the whole list. DOB
# and license number are the sensitive identifiers; they are already
# deterministically stamped onto the form by _resolve_schedule_row (Pass 1),
# so gap-fill never needs to see them. Other row fields (name, hire_date,
# experience_years, vehicle_use_percent) are left in case a legitimate
# narrative gap-fill question needs them (e.g. "describe the driver
# experience program").
_SCHEDULE_ROW_PII_SUBKEYS: Dict[str, frozenset] = {
    "auto_drivers": frozenset({"dob", "license_number"}),
}


def _redact_schedule_rows(list_key: str, rows: Any) -> Any:
    """Strip _SCHEDULE_ROW_PII_SUBKEYS[list_key] from every row dict. Returns
    ``rows`` unchanged if list_key has no registered PII sub-keys or rows
    isn't a list."""
    subkeys = _SCHEDULE_ROW_PII_SUBKEYS.get(list_key)
    if not subkeys or not isinstance(rows, list):
        return rows
    return [
        {k: v for k, v in row.items() if k not in subkeys} if isinstance(row, dict) else row
        for row in rows
    ]

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
    # NOTE: "Driver_FullName" is a DIFFERENT real schema field used by ACORD 133
    # (Driver_FullName_A/B/C) — kept as-is, do not repoint it. ACORD 127 itself
    # has no "Driver_FullName" field; it splits the name into GivenName/Surname,
    # so those two resolve via the "_name_given"/"_name_surname" sentinel
    # sub-keys (see _resolve_schedule_row) instead of both taking the raw
    # "name" string. LicenseNumber/LicenseStateOrProvince below were pointed at
    # base names that don't exist in ACORD_127_schema.json (the real fields are
    # *Identifier/*Code) and so silently never stamped; fixed to the real names.
    "Driver_FullName":                    _ScheduleDef("auto_drivers", "name"),
    "Driver_GivenName":                   _ScheduleDef("auto_drivers", "_name_given"),
    "Driver_Surname":                     _ScheduleDef("auto_drivers", "_name_surname"),
    "Driver_BirthDate":                   _ScheduleDef("auto_drivers", "dob"),
    "Driver_LicenseNumberIdentifier":     _ScheduleDef("auto_drivers", "license_number"),
    "Driver_LicensedStateOrProvinceCode": _ScheduleDef("auto_drivers", "license_state"),
    "Driver_HiredDate":                   _ScheduleDef("auto_drivers", "hire_date"),
    "Driver_ExperienceYearCount":         _ScheduleDef("auto_drivers", "experience_years"),
    "Driver_Vehicle_UsePercent":          _ScheduleDef("auto_drivers", "vehicle_use_percent"),

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
    "LossHistory_OccurrenceDate":             _ScheduleDef("loss_history", "date"),
    "LossHistory_ClaimDate":                  _ScheduleDef("loss_history", "claim_date"),
    "LossHistory_LossDescription":            _ScheduleDef("loss_history", "description"),
    "LossHistory_Description":                _ScheduleDef("loss_history", "description"),
    "LossHistory_OccurrenceDescription":      _ScheduleDef("loss_history", "description"),
    "LossHistory_TotalIncurred":              _ScheduleDef("loss_history", "amount"),
    "LossHistory_AmountPaid":                 _ScheduleDef("loss_history", "paid"),
    "LossHistory_PaidAmount":                 _ScheduleDef("loss_history", "paid"),
    "LossHistory_ReservedAmount":             _ScheduleDef("loss_history", "reserved_amount"),
    "LossHistory_ClaimNumber":                _ScheduleDef("loss_history", "claim_number"),
    "LossHistory_LineOfBusiness":             _ScheduleDef("loss_history", "line_of_business"),
    "LossHistory_OpenIndicator":              _ScheduleDef("loss_history", "open"),
    "LossHistory_ClaimStatus_OpenCode":       _ScheduleDef("loss_history", "open_code"),
    "LossHistory_ClaimStatus_SubrogationCode":_ScheduleDef("loss_history", "subrogation_code"),

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

    # ── Premises / Location Schedule (Beta Report Figure 27) ─────────────────
    # These are ACORD's own shared field concepts — the SAME base field names
    # (CommercialStructure_*/BusinessInformation_*/BuildingOccupancy_*) appear
    # on ACORD 125, 131, 140, 160 and 186 to mean the same thing: "location A's
    # / B's / ... address, ownership, and occupancy detail." Registering them
    # once here (mirroring the LossHistory_*/PriorCoverage_* pattern above)
    # binds every one of those forms' A/B/C/D premises rows to the SAME
    # canonical, deduplicated `property_locations` list instead of each row
    # falling through to an ungrounded per-field GPT guess.
    # "LOC #" - tooltip: "The location number for the premises." Was already
    # in the required-field set (pre-existing) but never had a data source,
    # so it stayed blank/yellow on every row. Sourced from the consolidated
    # list's own position, matching the row it's actually stamped into.
    "CommercialStructure_Location_ProducerIdentifier":        _ScheduleDef("property_locations", "location_number"),
    "CommercialStructure_PhysicalAddress_LineOne":            _ScheduleDef("property_locations", "address_line1"),
    "CommercialStructure_PhysicalAddress_CityName":           _ScheduleDef("property_locations", "address_city"),
    "CommercialStructure_PhysicalAddress_StateOrProvinceCode":_ScheduleDef("property_locations", "address_state"),
    "CommercialStructure_PhysicalAddress_PostalCode":         _ScheduleDef("property_locations", "address_zip"),
    "CommercialStructure_RiskLocation_InsideCityLimitsIndicator":  _ScheduleDef("property_locations", "is_inside_city_limits"),
    "CommercialStructure_RiskLocation_OutsideCityLimitsIndicator": _ScheduleDef("property_locations", "is_outside_city_limits"),
    "CommercialStructure_InsuredInterest_OwnerIndicator":     _ScheduleDef("property_locations", "is_owner"),
    "CommercialStructure_InsuredInterest_TenantIndicator":    _ScheduleDef("property_locations", "is_tenant"),
    "CommercialStructure_AnnualRevenueAmount":                _ScheduleDef("property_locations", "annual_revenue"),
    "BusinessInformation_FullTimeEmployeeCount":              _ScheduleDef("property_locations", "full_time_employees"),
    "BusinessInformation_PartTimeEmployeeCount":              _ScheduleDef("property_locations", "part_time_employees"),
    "BuildingOccupancy_OccupiedArea":                         _ScheduleDef("property_locations", "occupied_area"),
    "BuildingOccupancy_OpenToPublicArea":                     _ScheduleDef("property_locations", "open_to_public_area"),
    "BuildingOccupancy_OperationsDescription":                _ScheduleDef("property_locations", "operations_description"),
    # "Total Building Area" (whole building's sq ft) - a DISTINCT field from
    # occupied_area (the space the insured occupies). Missed on the first
    # pass; caught during manual re-verification because it was left
    # unregistered, fell to ungated GPT gap-fill, and got silently filled
    # with a copy of occupied_area instead of staying blank.
    "Construction_BuildingArea":                              _ScheduleDef("property_locations", "total_building_area"),
    # Owner/Tenant/Other are mutually exclusive. Registering "Other" too
    # (sourced from the SAME deterministic ownership derivation as Owner/
    # Tenant) stops it from being independently, ungated-ly re-guessed by
    # GPT and contradicting an already-resolved Owner/Tenant answer.
    "CommercialStructure_InsuredInterest_OtherIndicator":     _ScheduleDef("property_locations", "is_other_interest"),
    "CommercialStructure_InsuredInterest_OtherDescription":   _ScheduleDef("property_locations", "other_interest_description"),

    # ── GL Class Codes (ACORD 126 schedule of hazards) ───────────────────────
    # NOTE: the real ACORD 126 field names are `GeneralLiability_Hazard_*_A/_B/_C`
    # (see ACORD_126_schema.json). The former "GL_ClassCode" / "GL_Location" keys
    # matched no real field and were dead. Structured filling now lives in
    # `_resolve_gl_hazard_row`, which is checked at the top of `_deterministic_map`
    # so an absent schedule falls through to gap-fill instead of being blanked.

    # ── Inland Marine Items (ACORD 160) ─────────────────────────────────────
    "InlandMarine_ItemDescription":  _ScheduleDef("inland_marine_items", "description"),
    "InlandMarine_ItemValue":        _ScheduleDef("inland_marine_items", "value"),
    "InlandMarine_SerialNumber":     _ScheduleDef("inland_marine_items", "serial_number"),
}

_SCHED_ROW_RE = re.compile(r"^(.+)_([A-N])$")


def repeating_group_key(field_name: str, tooltip: Optional[str]):
    """Repeating-group identity for a gap-fill slot field: ``(base, tooltip)``.

    Two ``_A/_B/...`` siblings belong to the SAME repeating group only when they
    share BOTH the base name AND the tooltip. ACORD reuses one base for genuinely
    DIFFERENT roles distinguished only by the "As used here..." tooltip note - on
    ACORD 127, ``AdditionalInterest_FullName_A/B`` are the additional-interest
    (lienholder) schedule while ``_C/_D`` are "the name of the other owner of the
    vehicle". Keying on the base alone merged all four into one ordinal
    "find N distinct values" block, so the gap-fill LLM filled the first role and
    left the owner boxes (_C/_D) empty. Splitting by tooltip gives each role its
    own block. Returns ``None`` when the field has no row suffix (not a slot).
    Module-level + pure so the grouping is unit-testable against the real schemas.
    """
    m = _SCHED_ROW_RE.match(field_name or "")
    if not m:
        return None
    return (m.group(1), (tooltip or "").strip())


# Sentinel sub_keys handled specially by _resolve_schedule_row: the "name"
# sub-key holds one full-name string per driver, but ACORD 127 splits that
# into separate GivenName/Surname boxes. Last whitespace token = surname;
# everything before it = given name. A single-token name has no surname.
_NAME_GIVEN_KEY = "_name_given"
_NAME_SURNAME_KEY = "_name_surname"


def _split_driver_name(full: Optional[str]):
    if not full or not str(full).strip():
        return None, None
    parts = str(full).strip().split()
    if len(parts) == 1:
        return parts[0], None
    return " ".join(parts[:-1]), parts[-1]


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
        if defn.sub_key in (_NAME_GIVEN_KEY, _NAME_SURNAME_KEY):
            given, surname = _split_driver_name(item.get("name"))
            val = given if defn.sub_key == _NAME_GIVEN_KEY else surname
        else:
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
    ("Producer_CustomerIdentifier",                        None),            # agency-assigned account ID — not in extraction schema; must not receive producer_name
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
    # NOT total_revenue - this field is "dollar amount paid TO subcontractors",
    # a distinct (usually much smaller) figure than annual gross revenue.
    # No dedicated extraction fact exists for it, so leave unmatched -> gap-fill
    # LLM reads the real number from raw text if the document states it;
    # otherwise it stays blank instead of silently showing total revenue.
    ("Contractors_SubcontractorsPaidAmount",               None),
    ("Contractors_FullTimeEmployeeCount",                  "num_employees"),
    # NOT num_employees - that would duplicate the full-time count into this
    # field verbatim (no dedicated part-time extraction fact exists). Leave
    # unmatched -> gap-fill LLM reads the real part-time figure from raw text
    # when the document states one distinctly; otherwise stays blank instead
    # of silently repeating the full-time number.
    ("Contractors_PartTimeEmployeeCount",                  None),
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
    # Two AI tiers, deliberately distinct colors:
    #   PINK   = AI-filled AND confirmed present in the uploaded documents (AI-OK)
    #   ORANGE = AI-filled but NOT confirmed (verify) — never reads as the yellow
    #            "Required" highlight.
    COLOR_PINK   = (1.00, 0.89, 0.89)   # rgba(254,226,226) — light pink (AI-OK, verified)
    COLOR_ORANGE = (1.00, 0.84, 0.67)   # rgba(254,215,170) — light orange (Verify)
    COLOR_YELLOW = (1.00, 0.95, 0.78)   # rgba(254,243,199) — very light yellow (Required)
    COLOR_GREEN  = (0.73, 0.97, 0.82)   # rgba(187,247,208) — very light green (Client)
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
                elif conf == "ai_verified" and has_val:
                    color = COLOR_PINK
                elif conf == "low_confidence" and has_val:
                    color = COLOR_ORANGE
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


# ── Fieldmap cache layer REMOVED ─────────────────────────────────────────────
# The persisted {field → fact_key} JSON cache was removed because >92% of its
# entries were null and the ambiguous null semantics caused dozens of fillable
# fields to be re-queried against GPT on every run. All form filling now flows
# through: (1) deterministic Pass 1 rules in this module and (2) the GPT call
# with the form schema + complete extracted raw text. Archived fieldmap JSONs
# live in backend/forms_database/deprecated/ for reference.
#
# The stubs below preserve the external API surface so callers in main.py and
# routes/form_routes.py keep working without modification.

def _load_fieldmap(form_id: str) -> tuple:
    """No-op stub. Cache layer removed — always returns empty fieldmap + ai set."""
    return {}, set()


def _save_fieldmap(form_id: str, fieldmap: dict, ai_set: set = None):
    """No-op stub. Cache layer removed — fills are recomputed from schema + raw text."""
    return


def migrate_fieldmaps_to_v5() -> None:
    """No-op stub. Cache layer removed — nothing to migrate."""
    return


def purge_stale_null_fieldmap_entries() -> None:
    """No-op stub. Cache layer removed — nothing to purge."""
    return


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
    # Loss history — handled by _derive_no_prior_losses_indicator (evidence-driven,
    # multi-input); intentionally NOT a generic single-key substring rule.
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


def _int_or_none(val) -> Optional[int]:
    """First signed integer in `val`, else None. Booleans and bare text → None."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    m = re.search(r"-?\d+", str(val).replace(",", ""))
    return int(m.group()) if m else None


def _money_positive(val) -> bool:
    """True if `val` parses to a number greater than zero (e.g. '$12,500')."""
    if val is None or isinstance(val, bool):
        return False
    m = re.search(r"-?\d+(?:\.\d+)?", str(val).replace(",", ""))
    try:
        return bool(m) and float(m.group()) > 0
    except (TypeError, ValueError):
        return False


def _attests_no_loss(val) -> bool:
    """True when `val` affirmatively states 'no prior/known losses'.

    Accepts booleans, truthy tokens, and free-text no-loss phrasing. A stored
    "No"/"false"/"0" is NOT an attestation (mirrors sqs_service._attested_true so
    the form indicator and the P4 loss score can never disagree on the evidence).
    """
    if val is None or val is False:
        return False
    if val is True:
        return True
    s = str(val).strip().lower()
    if s in {"yes", "y", "true", "1", "on"}:
        return True
    return ("no " in s or s.startswith("no")) and ("loss" in s or "claim" in s)


def _derive_no_prior_losses_indicator(facts: dict) -> Optional[str]:
    """Resolve the ACORD 125 'No Prior Losses' checkbox from the SAME evidence the
    SQS loss-history state rests on, so the printed form and the score agree.

      • Actual claims / incurred present            → "No"  (losses DO exist)
      • Attested no-loss (user, narrative, or a real 0 claim count) → "Yes"
      • Nothing extracted either way                → None  (leave BLANK so the
        questionnaire asks for loss runs / a no-known-loss confirmation instead
        of a blank box silently reading as "no losses").

    Replaces the previous num_claims=="0" SUBSTRING rule, which mis-fired for any
    claim count containing the digit 0 (e.g. 10 → "0" in "10" → wrongly "Yes").
    """
    claims = _int_or_none(_fv(facts, "num_claims"))
    if (claims is not None and claims > 0) or _money_positive(_fv(facts, "total_incurred")):
        return "No"
    attested = (
        _attests_no_loss(_fv(facts, "no_prior_losses"))
        or _attests_no_loss(_fv(facts, "narrative_states_no_losses"))
        or _attests_no_loss(_fv(facts, "loss_history_no_prior_losses_indicator"))
        or claims == 0
    )
    return "Yes" if attested else None


def _derive_indicator(field_name: str, facts: dict) -> Optional[str]:
    """Return 'Yes'/'No' for indicator/checkbox fields based on extracted facts.

    Covers both fields with 'Indicator' in the name and LOB checkboxes like
    Policy_LineOfBusiness_CommercialGeneralLiability_A (no 'Indicator' suffix).
    """
    fn_lower = field_name.lower()
    # Loss-history "No Prior Losses" is evidence-driven and multi-input — resolve
    # it deterministically before the generic single-key substring rules below.
    if "nopriorlosses" in fn_lower.replace("_", ""):
        return _derive_no_prior_losses_indicator(facts)
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
            # For entity_type, normalize common phrase variants before substring
            # matching so "Limited Liability Company" and "Limited Liability
            # Corporation" both resolve to "llc" rather than falling through to
            # gap fill and letting the LLM mark multiple checkboxes.
            if fact_key == "entity_type":
                val_lower = str(raw).lower()
                for _llc_phrase in (
                    "limited liability corporation",
                    "limited liability company",
                    "limited liability corp",
                    # Abbreviated forms: "LLC Corp", "LLC Corporation"
                    # (full-phrase variants above don't match these)
                    "llc corp",
                    "llc corporation",
                ):
                    if _llc_phrase in val_lower:
                        val_lower = "llc"
                        break
                val_str = val_lower
            else:
                val_str = str(raw).lower()
            if match_val.lower() in val_str:
                return "Yes"
            return "No"
    return None


# ── Gap-fill field-spec clarifications ────────────────────────────────────────
# Bug fix (found via GL test suite): the gap-fill LLM answered
# Contractors_SubcontractorsPaidAmount_A ($15) from a document that only ever
# stated "15% of work is subcontracted" - it reused the percentage's digits as
# a dollar figure for an adjacent, easily-confused field instead of returning
# null. Rule 4 in the prompt ("Dollar amounts: include $ and commas as found")
# combined with this field's own tooltip ("total dollar amount... paid to
# subcontractors") pushed it to force an answer rather than admit absence.
# Keyed by field name so this only adds prompt text when the field is actually
# being asked about, and is a plain dict so more confusable-field pairs can be
# added later without growing the global prompt skeleton.
_FIELD_SPEC_CLARIFICATIONS = {
    "Contractors_SubcontractorsPaidAmount_A": (
        " CAUTION: this is a DOLLAR AMOUNT paid to subcontractors, NOT the "
        "subcontracted-work PERCENTAGE (that is the separate field "
        "Contractors_WorkSubcontractedPercent_A). Only fill this if the "
        "document states an explicit dollar figure for this. Never derive a "
        "dollar amount from a percentage - if only a percentage is stated, "
        "return null for this field."
    ),
}


# ── GL schedule-of-hazards structured fill (ACORD 126) ───────────────────────
# Maps each broker-fillable hazard column to its key inside a row of the
# `gl_class_code_schedule` fact (list of dicts). Kept separate from the generic
# _SCHEDULE_REGISTRY so an ABSENT schedule falls through to gap-fill (returns
# "UNMATCHED") instead of being marked an authoritative blank — the client
# requires missing class/hazard data to remain a visible high-priority gap.
_GL_HAZARD_COL_TO_KEY = {
    "ClassCode":        "class_code",
    "Classification":   "classification",
    "PremiumBasisCode": "premium_basis",
    "Exposure":         "exposure_amount",
    "TerritoryCode":    "territory",
}
_GL_HAZARD_ROW_RE = re.compile(
    r"^GeneralLiability_Hazard_"
    r"(ClassCode|Classification|PremiumBasisCode|Exposure|TerritoryCode)_([A-N])$"
)


def _resolve_gl_hazard_row(field_name: str, facts: dict):
    """Resolve an ACORD 126 schedule-of-hazards data cell from the structured
    `gl_class_code_schedule` fact.

    Returns
    -------
    _SCHED_SKIP  — not a GL hazard data field; caller continues normally.
    str          — the structured value for this row/column.
    "UNMATCHED"  — GL hazard field with no structured value → send to gap-fill
                   so the LLM can still read it from raw text (never a silent blank).
    """
    m = _GL_HAZARD_ROW_RE.match(field_name)
    if not m:
        return _SCHED_SKIP
    col, letter = m.group(1), m.group(2)
    idx = _ROW_LETTER_TO_IDX[letter]
    rows = _fv(facts, "gl_class_code_schedule")
    if isinstance(rows, list) and idx < len(rows):
        row = rows[idx]
        if isinstance(row, dict):
            val = row.get(_GL_HAZARD_COL_TO_KEY[col])
            if val is not None and str(val).strip():
                return str(val).strip()
    return "UNMATCHED"


_SUBJECT_OF_INSURANCE_RE = re.compile(
    r"^CommercialProperty_Premises_(SubjectOfInsuranceCode|LimitAmount)_([A-Z])$"
)
# Building = subject slot 0, BPP = subject slot 1, within each premises's own
# 6-letter block (see _resolve_subject_of_insurance_row). Slots 2-4 (e.g.
# Business Income) have no structured source in the current fact model.
_SUBJECT_OF_INSURANCE_SLOTS = (
    ("Building", "building_value"),
    ("Business Personal Property", "bpp_value"),
)


def _resolve_subject_of_insurance_row(field_name: str, facts: dict):
    """Resolve a per-premises Subject-of-Insurance data cell (the Building /
    BPP amount grid on ACORD 140/141) from the canonical `property_locations`
    list.

    This grid's row-lettering is NOT the simple "letter = premises index"
    scheme used elsewhere on the same form (address, revenue, employee
    count, ...). Confirmed directly against ACORD_140_schema.json:
    CommercialStructure_PhysicalAddress_LineOne_A is premises 1's address and
    _B is premises 2's - but CommercialProperty_Premises_LimitAmount jumps
    from _E straight to _G for premises 2's first subject row, skipping _F.
    Each premises gets its OWN 6-letter block (5 real subject rows + 1 unused
    spacer): premises 1 = A-F, premises 2 = G-L, premises 3 = M-R, etc.

    Without this, these fields were entirely unregistered and fell to
    ungated GPT gap-fill with no per-premises grounding, which mixed dollar
    figures from DIFFERENT locations into a single premises block's grid.

    Returns
    -------
    _SCHED_SKIP  — not a subject-of-insurance field; caller continues normally.
    None         — this premises doesn't exist (fewer real locations than
                   letter-blocks) - an authoritative blank, not sent to GPT.
    "UNMATCHED"  — a real premises, but no structured value for this subject
                   slot yet → gap-fill may still try from raw text.
    str          — the resolved value.
    """
    m = _SUBJECT_OF_INSURANCE_RE.match(field_name)
    if m is None:
        return _SCHED_SKIP
    col, letter = m.group(1), m.group(2)
    letter_idx = _ROW_LETTER_TO_IDX.get(letter)
    if letter_idx is None:
        return _SCHED_SKIP
    loc_idx, slot_idx = divmod(letter_idx, 6)
    if slot_idx == 5:
        return _SCHED_SKIP  # the unused spacer letter (F, L, R, ...) - not a real row

    locations = _fv(facts, "property_locations")
    if not isinstance(locations, list) or loc_idx >= len(locations):
        return None
    loc = locations[loc_idx]
    if not isinstance(loc, dict) or slot_idx >= len(_SUBJECT_OF_INSURANCE_SLOTS):
        return "UNMATCHED"

    label, value_key = _SUBJECT_OF_INSURANCE_SLOTS[slot_idx]
    value = loc.get(value_key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return "UNMATCHED"
    return label if col == "SubjectOfInsuranceCode" else str(value)


_NO_LOSS_INDICATOR_FIELDS = {"LossHistory_NoPriorLossesIndicator_A"}


def _resolve_no_loss_indicator(field_name: str, facts: dict, raw_text: str = ""):
    """Deterministically resolve the ACORD 'Check if none' loss-history
    checkbox from the SAME signal the SQS scorer uses, instead of an
    independent per-field GPT judgment call.

    Previously the checkbox was decided purely by a Pass-2 GPT per-field
    guess, disconnected from the facts/flags the SQS panel scores against. A
    submission could come back with the checkbox CHECKED ("Yes" - reads to a
    broker as confirmed/done) while the SQS panel simultaneously scored the
    identical submission as only a narrative assertion, "weaker than an
    attestation, please confirm" - the PDF and the report contradicting each
    other about the same finding.

    Every real caller (process_single_form, compute_form_gaps) already merges
    session flags into the facts dict it passes in (`facts_with_flags = {
    **session["facts"], **session["flags"]}` - see form_service.py), the same
    pattern already relied on for other checkboxes like has_general_liability.
    So `narrative_states_no_losses` / `no_prior_losses` here are the EXACT
    flag values calculate_p4_loss_history() and _get_loss_history_state() in
    sqs_service.py read - not a re-derived approximation, the same booleans.
    That makes the checkbox and the SQS state impossible to disagree by
    construction. A raw-text scan (detect_no_loss_assertion) is kept only as
    a defensive fallback for a caller that didn't merge flags in.

    Returns
    -------
    _SCHED_SKIP  — not this field; caller continues normally.
    "No"         — real claim data is present. Never attest "none" above a
                   populated claims table on the same form - that would be
                   its own internal contradiction.
    "Yes"        — a no-loss assertion was found with no contradicting claims.
    "UNMATCHED"  — neither signal fired → gap-fill may still try from raw text.
    """
    if field_name not in _NO_LOSS_INDICATOR_FIELDS:
        return _SCHED_SKIP

    def _has_positive_amount(key: str) -> bool:
        v = _fv(facts, key)
        if v is None:
            return False
        try:
            return float(re.sub(r"[^\d.]", "", str(v)) or 0) > 0
        except Exception:
            return False

    if _has_positive_amount("num_claims") or _has_positive_amount("total_incurred"):
        return "No"
    if bool(_fv(facts, "narrative_states_no_losses")) or bool(_fv(facts, "no_prior_losses")):
        return "Yes"
    npl = _fv(facts, "loss_history_no_prior_losses_indicator")
    if str(npl or "").strip().lower() in ("yes", "y", "true", "1"):
        return "Yes"
    if detect_no_loss_assertion(raw_text or ""):
        return "Yes"
    return "UNMATCHED"


def _deterministic_map(field_name: str, facts: dict):
    # ── Loss-history no-loss checkbox (single source of truth with SQS) ─────
    no_loss = _resolve_no_loss_indicator(field_name, facts)
    if no_loss is not _SCHED_SKIP:
        return no_loss  # "Yes"/"No", or "UNMATCHED" → gap-fill from raw text

    # ── GL schedule-of-hazards structured cells (highest priority) ───────────
    gl_haz = _resolve_gl_hazard_row(field_name, facts)
    if gl_haz is not _SCHED_SKIP:
        return gl_haz  # value string, or "UNMATCHED" → gap-fill from raw text

    # ── Subject-of-Insurance per-premises structured cells ───────────────────
    soi = _resolve_subject_of_insurance_row(field_name, facts)
    if soi is not _SCHED_SKIP:
        return soi  # value string, None (no such premises), or "UNMATCHED"

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

    # ── Row-variant guard ────────────────────────────────────────────────────
    # Fields whose names end with a row suffix (_B, _C … _N) but were NOT
    # resolved by _resolve_schedule_row above represent additional-entity
    # slots (2nd named insured, 2nd building location, …).
    # _ACORD_FIELD_RULES uses substring matching and would blindly stamp the
    # PRIMARY scalar fact into every _B/_C/_D variant, causing duplicated
    # values (e.g. Named Insured × 4 on ACORD 101, same premises address in
    # every CommercialStructure row on ACORD 125).
    #
    # By routing these non-primary rows directly through _derive_indicator:
    #   • Checkbox/indicator fields get correct "Yes"/"No" from facts.
    #   • All other fields return None → treated as UNMATCHED by the caller
    #     → gap-fill LLM fills them only if a second entity exists in the doc.
    # The _A slot (idx=0) is the primary slot and always passes through below.
    _row_guard = _SCHED_ROW_RE.match(field_name)
    if _row_guard and _ROW_LETTER_TO_IDX[_row_guard.group(2)] >= 1:
        return _derive_indicator(field_name, facts)  # None for non-indicator fields

    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            if fact_key is None:
                return None
            if fact_key.startswith("_"):
                # "_addr_*" (mailing_address) is only a real fact for the NAMED
                # INSURED - extraction never captures a separate Producer /
                # AdditionalInterest / CertificateHolder address. Reusing the
                # insured's mailing_address for those (previous behavior)
                # silently stamped the WRONG entity's address onto the form -
                # a direct "producer details must be exact" violation. Only
                # resolve _addr_* for NamedInsured_* fields; everything else
                # falls through to gap-fill, which reads the correctly-labelled
                # address for that entity directly from the raw document text.
                # "_loc_*" (physical_address) is unaffected - both its users
                # (NamedInsured_PhysicalAddress_* and CommercialStructure_
                # PhysicalAddress_*) legitimately mean the insured's own premises.
                if fact_key.startswith("_addr_") and not field_name.startswith("NamedInsured_"):
                    return "UNMATCHED"
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
            f"Construction_BuildingArea_{row}",
        }
        managed.update(location_fields)
        row_started = (
            _acord125_row_started(field_state, "CommercialStructure", row)
            or _acord125_row_started(field_state, "BuildingOccupancy", row)
        )
        if row_started:
            required_now.update(location_fields)

        # Beta Report Figure 27: "clarify owned vs tenant" + "require
        # occupancy/COPE details before property forms are considered
        # complete." Owner/Tenant and Inside/Outside-City-Limits are
        # COMPLEMENTARY checkbox pairs — exactly one is "Yes", the other is a
        # deliberate, correct "No" (not a gap). _acord125_has_value() treats
        # "No" as "no value" (the right behavior for the single yes/no
        # QUESTIONS checked elsewhere in this function), which would wrongly
        # flag the correctly-"No" half of a resolved pair as missing. So
        # these two pairs are checked separately: require only that AT LEAST
        # ONE half of each pair has an actual "Yes" answer, and flag only
        # ONE field per pair — never both halves of an already-resolved
        # answer.
        owner_field  = f"CommercialStructure_InsuredInterest_OwnerIndicator_{row}"
        tenant_field = f"CommercialStructure_InsuredInterest_TenantIndicator_{row}"
        other_interest_field = f"CommercialStructure_InsuredInterest_OtherIndicator_{row}"
        inside_field  = f"CommercialStructure_RiskLocation_InsideCityLimitsIndicator_{row}"
        outside_field = f"CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_{row}"
        other_city_field = f"CommercialStructure_RiskLocation_OtherIndicator_{row}"
        managed.update({owner_field, tenant_field, other_interest_field, inside_field, outside_field})
        if row_started:
            # "Other" is now ALSO a deterministic resolution (see the
            # InsuredInterest_OtherIndicator registration above), so it must
            # count as "resolved" here too - otherwise a genuine Other answer
            # would leave Owner sitting at missing_required forever.
            if not (
                _acord125_is_yes(field_state, owner_field)
                or _acord125_is_yes(field_state, tenant_field)
                or _acord125_is_yes(field_state, other_interest_field)
            ):
                required_now.add(owner_field)
            # City-limits "Other" (unincorporated) stays GPT-eligible - there is
            # no deterministic "unincorporated" signal in the extracted facts -
            # but it must still count as a resolution so a GPT-filled "Other"
            # doesn't leave Inside/Outside falsely flagged missing.
            if not (
                _acord125_is_yes(field_state, inside_field)
                or _acord125_is_yes(field_state, outside_field)
                or _acord125_is_yes(field_state, other_city_field)
            ):
                required_now.add(inside_field)

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

    # NOTE (deliberate, per product decision): the page-3 General Information
    # Yes/No questions (CommercialPolicy_Question_*Code_*) are intentionally NOT
    # forced to missing_required / yellow. They are not treated as required
    # fields on the form. When the AI leaves one blank it is still surfaced for
    # the broker via field_qa's "not_answered" review item (the pre-download
    # modal) — just without a yellow highlight on the PDF itself. Do not
    # re-add a loop that marks these codes required; that was tried and
    # reverted because 16 yellow compliance boxes made a form read as alarmingly
    # incomplete when most are edge-case questions.

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


# GL schedule-of-hazards columns (ACORD 126), mirrored from _GL_HAZARD_COL_TO_KEY
# above so this stays in lockstep with the extraction-side mapping by
# construction rather than duplicating the row-letter regex.
_ACORD126_HAZARD_COLS = ("ClassCode", "Classification", "PremiumBasisCode", "Exposure", "TerritoryCode")
_ACORD126_HAZARD_ROWS = tuple("ABCDEFGHIJKLMN")


def apply_acord126_missing_field_highlights(
    form_id: str,
    facts: dict,
    field_state: dict,
    confidence: dict,
) -> dict:
    """
    ACORD 126-only visual completeness layer for the GL schedule of hazards.

    Every hazard column (`GeneralLiability_Hazard_*_A..N`) is marked
    "required": false in the raw schema, so the generic confidence pass at the
    bottom of map_facts_to_form never paints a blank cell yellow - a row with
    ClassCode and Exposure filled but TerritoryCode left blank looks IDENTICAL
    to an untouched row. That silently defeats the client's own requirement
    that missing hazard/class data stay a visible high-priority gap: the data
    pipeline (_resolve_gl_hazard_row) is careful never to fabricate a cell, but
    nothing then flags the resulting gap on the rendered PDF. Mirrors
    apply_acord125_missing_field_highlights: once a row has ANY hazard data
    (i.e. the broker/extraction started that class-code row), every other
    hazard column in that same row is forced missing_required (yellow) until
    it has a value too.
    """
    if form_id != "ACORD_126":
        return confidence

    for row in _ACORD126_HAZARD_ROWS:
        row_fields = [f"GeneralLiability_Hazard_{col}_{row}" for col in _ACORD126_HAZARD_COLS]
        if not any(f in field_state or f in confidence for f in row_fields):
            continue
        if not any(_acord125_has_value(field_state, f) for f in row_fields):
            continue  # row never started - an empty row is not a gap, just unused
        for f in row_fields:
            if not _acord125_has_value(field_state, f):
                confidence[f] = "missing_required"
            elif confidence.get(f) == "missing_required":
                confidence[f] = "filled" if _acord125_has_value(field_state, f) else "low_confidence"

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
    """Run an async coroutine from a synchronous executor thread.

    This is always called from run_in_executor() worker threads, which have no
    running event loop of their own. asyncio.run() is safe here — it creates a
    fresh loop for the thread and cleans it up on exit.
    """
    import asyncio as _asyncio
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
        if _is_empty_llm_value(mapped.get(f))
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
        llm_model = GPT_MODEL

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
            "  3. Use JSON null (the unquoted literal null) for any field whose value is genuinely "
            "absent. You MUST NOT return the strings \"null\", \"None\", \"N/A\", \"NA\", "
            "\"Not Provided\", \"Not Specified\", \"Not Available\", \"Not Applicable\", \"Unknown\", "
            "\"TBD\", \"Undefined\", or \"\" — these will be discarded. Omitting the field from the "
            "JSON object is also acceptable and equivalent to null.\n"
            "  4. Return short scalar values only: names, dates, dollar amounts, addresses, codes.\n"
            "  5. Do NOT invent, estimate, or carry over values from other fields.\n"
            "  6. For date fields: use the format as found in the document (MM/DD/YYYY or similar).\n"
            "  7. For dollar amounts: include the $ sign and commas as found (e.g. $1,000,000).\n\n"
            "Return ONLY a single JSON object: {\"FieldName\": <string value> OR JSON null}\n\n"
            f"=== FORM FIELDS TO FILL ({form_id}) ===\n{fields_block}\n\n"
            f"=== COMPLETE INSURANCE DOCUMENT TEXT ===\n{doc_text}\n\n"
            "JSON Output:"
        )
        try:
            _coro    = groq_chat(llm_model, [{"role": "user", "content": prompt}], max_tokens=16000)
            raw_resp = _run_coro_sync(_coro)
            if raw_resp.startswith("```"):
                raw_resp = raw_resp.replace("```json", "").replace("```", "").strip()
            s, e = raw_resp.find("{"), raw_resp.rfind("}")
            if s != -1 and e != -1:
                result = json.loads(raw_resp[s : e + 1])
                batch_filled    = 0
                batch_rejected  = 0
                batch_rej_sample: List[str] = []
                for field, value in result.items():
                    if _is_empty_llm_value(value):
                        batch_rejected += 1
                        if len(batch_rej_sample) < 6:
                            batch_rej_sample.append(f"{field}={value!r}")
                        continue
                    mapped[field] = str(value).strip()
                    filled_set.add(field)
                    batch_filled += 1
                logger.info(
                    f"raw_text_fill form={form_id} batch_start={start} "
                    f"fields_sent={len(batch)} batch_filled={batch_filled} "
                    f"batch_rejected={batch_rejected} total_filled={len(filled_set)}"
                )
                if batch_rej_sample:
                    logger.info(
                        f"raw_text_fill REJECT_SAMPLE form={form_id} batch_start={start}: "
                        + "; ".join(batch_rej_sample)
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

_GPT_CALL_BUDGET_CHARS   = int(os.getenv("GPT_CALL_BUDGET_CHARS",  str(380_000)))  # ~95k tokens; bumped from 360k so combined batches keep doc coverage in fewer chunks
_GPT_REPLY_RESERVE_CHARS = int(os.getenv("GPT_REPLY_RESERVE_CHARS", str(30_000)))   # output headroom
# Max retries per individual LLM call
_FORM_FILL_BATCH_RETRIES = int(os.getenv("FORM_FILL_BATCH_RETRIES", "3"))
# Cap output tokens so one call can't burn the full 200k TPM budget
_FORM_FILL_MAX_TOKENS    = int(os.getenv("FORM_FILL_MAX_TOKENS",    "16000"))
# combined_gap_fill: max fields per LLM batch — 200 cuts batch count ~50% vs 100,
# halving how many times the raw document is re-shipped to OpenAI per session.
_COMBINED_FIELD_BATCH    = int(os.getenv("COMBINED_FIELD_BATCH",    "200"))
# combined_gap_fill: seconds to sleep between batches so the OpenAI TPM bucket
# refills — eliminates the 429-storm we observed in production logs.
_COMBINED_BATCH_PAUSE_S  = float(os.getenv("COMBINED_BATCH_PAUSE_S", "2.0"))

# Legacy constant — kept so existing env-var overrides still work but no longer
# used as the primary chunk size (it's derived dynamically from the budget above).
_FORM_FILL_RAW_CHUNK_CHARS = int(os.getenv("FORM_FILL_RAW_CHUNK_CHARS", str(40_000)))

# Tokens the LLM commonly returns to signal "not found" — all should be treated
# as empty/null regardless of casing. Kept here so the prompt and the post-filter
# stay in sync; update both sides together if you add new sentinels.
_LLM_EMPTY_SENTINELS = frozenset({
    "", "null", "none", "nil", "n/a", "na", "n.a.",
    "not provided", "not specified", "not available", "not applicable",
    "unknown", "tbd", "to be determined", "undefined", "blank",
})


def _is_empty_llm_value(value) -> bool:
    """Return True if `value` is a JSON null or any string the LLM uses to mean 'not found'.

    This catches both true JSON nulls AND the literal strings ("null", "None", "N/A",
    "Not Provided", etc.) that GPT-4o-mini frequently emits in JSON mode when the
    instruction is "use null when not found". Comparison is case-insensitive and
    trims surrounding whitespace.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _LLM_EMPTY_SENTINELS
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


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
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": model or GPT_MODEL}

    try:
        _client = _get_openai_form_fill_client()
    except RuntimeError as _e:
        logger.warning("gpt_fill: %s — skipping GPT form fill pass", _e)
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": model or GPT_MODEL}

    llm_model = model or GPT_MODEL

    # ── Filter out schedule/admin fields ─────────────────────────────────────
    # GL schedule-of-hazards DATA columns are exempted from the skip patterns:
    # they contain "Hazard_" (and PremiumBasisCode contains "Premium") but ARE
    # broker-fillable, so when structured extraction missed them the gap-fill LLM
    # must still get a chance to read them from raw text (client Figure 29).
    eligible_fields = {
        f: meta
        for f, meta in unmatched_fields.items()
        if not _is_schedule_field(f)
        and (
            _GL_HAZARD_FILLABLE_RE.match(f)
            or not any(p in f for p in _RAW_TEXT_SKIP_PATTERNS)
        )
    }
    if not eligible_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": llm_model}

    field_list = list(eligible_fields.keys())
    raw_text_used = bool(raw_text and raw_text.strip())

    # ── Shared accumulators ───────────────────────────────────────────────────
    # candidate_counts[field][value] = number of chunks that returned that value.
    # Majority vote across chunks resolves conflicts between chunks.
    candidate_counts: Dict[str, Dict[str, int]] = {f: {} for f in field_list}
    all_raw_fields:   set                       = set()
    all_question_grounding: Dict[str, str]      = {}

    # ── Partition eligible fields into singles and slot-groups ────────────────
    # Slot-groups: fields sharing the same base name with _A/_B/…/_N suffixes.
    # Singles:     everything else (no repeating siblings).
    _ROW_SUFFIX_RE = re.compile(r"^(.+)_([A-N])$")

    def _group_key(field: str):
        """Repeating-group identity for ``field`` - delegates to the module-level
        :func:`repeating_group_key` (pure + unit-tested) using this field's
        schema tooltip. See that function for why grouping is (base, tooltip)."""
        info = eligible_fields.get(field) or {}
        tu = info.get("tu") if isinstance(info, dict) else None
        return repeating_group_key(field, tu)

    _base_to_slots: Dict[tuple, List[str]] = {}
    for _f in field_list:
        _gk = _group_key(_f)
        if _gk:
            _base_to_slots.setdefault(_gk, []).append(_f)
    for _gk in _base_to_slots:
        _base_to_slots[_gk].sort()            # _A, _B, _C, … always in order
    _grouped_fields_set = {f for slots in _base_to_slots.values() for f in slots}

    _ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th",
                 "8th", "9th", "10th", "11th", "12th", "13th", "14th"]

    def _field_spec(f: str) -> str:
        """Spec line for a single (non-grouped) field."""
        info = eligible_fields.get(f) or {}
        info = info if isinstance(info, dict) else {}
        full_tu = info.get("tu", "") or ""
        tu   = full_tu[:80]
        ft   = info.get("ft", "")
        req  = " [REQUIRED]" if info.get("required") else ""
        spec = f"  - {f}{req}"
        if tu:
            spec += f": {tu}"
        if "/Ch" in ft:
            spec += " (dropdown)"
        elif "/Btn" in ft:
            spec += " (checkbox — Yes/No)"
            if _is_high_impact_checkbox_field(f, full_tu, ft):
                spec += " [HIGH-IMPACT — see rule 8]"
        clarification = _FIELD_SPEC_CLARIFICATIONS.get(f)
        if clarification:
            spec += clarification
        return spec

    def _slot_group_block(group_key, active_slots: List[str]) -> str:
        """Visual block for repeating-row siblings (_A/_B/_C …).

        Rendering all siblings in one block forces the LLM to reason about
        the full slot set before assigning values, preventing duplication
        caused by identical per-field descriptions.

        ``group_key`` is (base, tooltip) - all slots in it share the same
        meaning by construction (see _group_key), so a single shared
        description is accurate.
        """
        base        = group_key[0] if isinstance(group_key, tuple) else group_key
        all_slots   = _base_to_slots.get(group_key, active_slots)
        n_total     = len(all_slots)
        info_a      = eligible_fields.get(active_slots[0]) or {}
        info_a      = info_a if isinstance(info_a, dict) else {}
        full_tu     = info_a.get("tu", "") or ""
        tu          = full_tu[:80]
        ft          = info_a.get("ft", "")
        # Real row letters of THIS group (e.g. "_C/_D" for the split owner group),
        # not a positional _A/_B/... which would mislabel a split-off group.
        slot_labels = "/".join(
            "_" + (_ROW_SUFFIX_RE.match(s).group(2) if _ROW_SUFFIX_RE.match(s) else "?")
            for s in all_slots
        )

        lines = [f"\n  ── REPEATING GROUP '{base}' ({n_total} slots: {slot_labels}) ──"]
        if tu:
            lines.append(f"  Description (same for all slots): {tu}")
        if "/Ch" in ft:
            lines.append("  Type: dropdown")
        elif "/Btn" in ft:
            lines.append(
                "  Type: checkbox — return Yes/No for each slot; see rule 8: cite a "
                "grounding quote in \"question_grounding\" keyed by that slot's exact "
                "field name for each slot you answer Yes/No"
            )
            if _is_high_impact_checkbox_field(active_slots[0], full_tu, ft):
                lines.append("  [HIGH-IMPACT — see rule 8]")
        lines.append(
            f"  RULE: Find up to {n_total} DISTINCT values in the document.\n"
            f"  Assign 1st distinct value → _A, 2nd → _B, and so on.\n"
            f"  NEVER copy the same value into more than one slot.\n"
            f"  Leave a slot null if fewer distinct values exist than its position."
        )
        for i, slot_field in enumerate(active_slots):
            ordinal = _ORDINALS[i] if i < len(_ORDINALS) else f"{i + 1}th"
            req     = " [REQUIRED]" if (eligible_fields.get(slot_field) or {}).get("required") else ""
            lines.append(f"  - {slot_field}{req} → {ordinal} distinct value (null if < {i + 1} exist)")
        lines.append("  ──────────────────────────────────────────")
        return "\n".join(lines)

    # ── Prompt builder ───────────────────────────────────────────────────────
    _PROMPT_SKELETON = (
        f"You are filling ACORD form {form_id} for an insurance submission.\n"
        "You have two sources to fill fields from:\n"
        "  1. EXTRACTED FACTS — structured JSON of key/value pairs already extracted from the\n"
        "     document. Use a fact value when the field meaning matches the fact key.\n"
        "     Boolean facts (has_general_liability, is_contractor, has_auto_coverage, etc.)\n"
        "     directly answer Yes/No checkbox fields.\n"
        "  2. RAW DOCUMENT TEXT — the full document text. Use this for any field not already\n"
        "     answered by EXTRACTED FACTS.\n\n"
        "PRIMARY RULE: Fill EVERY field you can from either source. "
        "Copy values verbatim. Do not invent or paraphrase — if a value is not present in\n"
        "either source, return JSON null for that field.\n\n"
        "Return exactly three keys:\n"
        '  "values":            {FieldName: <string value> OR JSON null}\n'
        '  "raw_text_sourced":  [FieldName, ...]  (list only fields whose value came from raw text)\n'
        '  "question_grounding":{FieldName: <short verbatim quote>}  (every Question-code field\n'
        '                        and every checkbox — Yes/No field — see rule 8)\n\n'
        "ABSENCE PROTOCOL — read carefully:\n"
        "  When a field's value is not present in the document text, you MUST use JSON null "
        "(the unquoted literal null). You MUST NOT return any of the following strings as a "
        "stand-in for null: \"null\", \"None\", \"N/A\", \"NA\", \"Not Provided\", \"Not Specified\", "
        "\"Not Available\", \"Not Applicable\", \"Unknown\", \"TBD\", \"Undefined\", \"\". "
        "These strings will be discarded as if you had returned no value at all — which makes "
        "the response useless. If the value is missing, write null with no quotes. If the value "
        "is present but extremely short (e.g., a single digit, a single letter, a single word), "
        "return that exact string — short is fine, sentinel strings are not.\n\n"
        "OMIT-WHEN-UNKNOWN PROTOCOL (REQUIRED — affects response size):\n"
        "  When you have no value for a field you MUST omit it from the \"values\" object. "
        "Do NOT emit explicit JSON nulls for absent fields — omission is the required form. "
        "An omitted field is treated identically to null by the caller. "
        "This rule is mandatory: a response that lists every field with null will exceed the "
        "output-token cap and lose answers at the end. Only include fields you actually filled. "
        "Do NOT include a field in \"raw_text_sourced\" unless you actually copied its value "
        "from the document text.\n\n"
        "Rules:\n"
        "  1. EXACT values only — copy verbatim from the document text. Do not paraphrase or invent.\n"
        "  2. Use JSON null (unquoted) when the value is genuinely absent. Never the string \"null\".\n"
        "  3. Checkbox/indicator fields (marked 'checkbox — Yes/No'): return \"Yes\" or \"No\" ONLY.\n"
        "     If the document does not say one way or the other, return null — do NOT default to \"No\".\n"
        "     Every Yes/No you give here also needs a grounding quote in \"question_grounding\" — see rule 8.\n"
        "     Examples of how to fill checkboxes:\n"
        "     - Policy_Status_BoundIndicator: \"Yes\" if the document is a bound policy, else \"No\"\n"
        "     - Policy_Status_QuoteIndicator: \"Yes\" if document is a quote/application, else \"No\"\n"
        "     - Policy_LineOfBusiness_CommercialGeneralLiability: \"Yes\" if GL coverage is requested\n"
        "     - NamedInsured_LegalEntity_CorporationIndicator: \"Yes\" if entity type is Corporation\n"
        "     - BusinessInformation_BusinessType_ContractorIndicator: \"Yes\" if business is a contractor\n"
        "     - LossHistory_NoPriorLossesIndicator: \"Yes\" only if the document clearly indicates the insured has no prior/known losses (by meaning - e.g. \"no known losses\", \"loss-free\", \"clean loss history\"); NEVER infer \"Yes\" from losses simply being unmentioned. If it does not clearly say so, return null.\n"
        "  4. Dollar amounts: include $ and commas as found (e.g. $1,000,000).\n"
        "  5. Do NOT fill premium/rate/underwriter-computed fields — return null.\n"
        "  6. List ALL fields you fill in raw_text_sourced. Do NOT list fields you returned null for.\n"
        "  7. REPEATING GROUP fields (shown as '── REPEATING GROUP … ──' blocks below):\n"
        "     These are sibling fields sharing the same base name but different _A/_B/_C suffixes.\n"
        "     They represent DISTINCT sequential entries — not repeated copies of one value.\n"
        "       a) Count how many DISTINCT values of that type appear in the document.\n"
        "       b) Assign them in order: 1st distinct value → _A, 2nd → _B, 3rd → _C, …\n"
        "       c) NEVER copy the same value into multiple slots — that is always wrong.\n"
        "       d) If the document has fewer distinct values than slots, set the extras to JSON null.\n"
        "     Example: 3 slots for Insurer_FullName but only 2 insurer names found →\n"
        "       _A = \"Acme Insurance\", _B = \"Beta Insurance\", _C = null (unquoted).\n\n"
        "  8. EVERY Yes/No answer needs a grounding quote. This covers THREE field shapes:\n"
        "     - Question-code fields (name contains \"_Question_<code>Code_\"; the form's\n"
        "       compliance Yes/No questions, e.g. \"...any exposure to radioactive materials\").\n"
        "     - EVERY checkbox field marked 'checkbox — Yes/No' above, whatever it is named -\n"
        "       auto ownership, building features, coverage accept/reject, entity type, line of\n"
        "       business, anything else. One additionally marked [HIGH-IMPACT] is a field the\n"
        "       client specifically flagged (auto ownership / hired-non-owned / leasing /\n"
        "       hazardous-materials / maintenance) and deserves particular care, but the rule\n"
        "       below applies equally to every checkbox, labeled or not.\n"
        "     - Any other field whose own description says \"Enter Y for a Yes response... Input\n"
        "       N for a No response\" (a plain text Yes/No field that is neither a checkbox nor a\n"
        "       Question-code field, e.g. a spoilage or refrigeration-maintenance Y/N field).\n"
        "       a) Answer \"Y\"/\"Yes\" or \"N\"/\"No\" ONLY when the document explicitly addresses\n"
        "          that exact question. If the document never mentions the topic, return null for\n"
        "          the field - do NOT answer from silence and do NOT default to \"N\"/\"No\".\n"
        "       b) For EVERY such answer you give, add an entry to \"question_grounding\":\n"
        "          {FieldName: quote}, where quote is a short VERBATIM excerpt copied from the\n"
        "          document that is your specific basis for THAT answer.\n"
        "          - When the document poses the question and states the answer beside it\n"
        "            (e.g. \"Are any vehicles leased to others? No\" or \"Is there a vehicle\n"
        "            maintenance program in operation? Yes\"), cite the WHOLE question-and-answer\n"
        "            together, and you MUST INCLUDE the \"Yes\"/\"No\"/\"Y\"/\"N\" answer word itself\n"
        "            inside the quote - the quote is not valid proof without it.\n"
        "          - Otherwise, for a \"N\", the quote MUST be the sentence where the document\n"
        "            denies the topic (e.g. \"has no prior cancellations\"); never cite an\n"
        "            unrelated sentence just to have a quote.\n"
        "          Do not reuse the same quote for more than one question.\n"
        "       c) Whenever you answer \"Y\" and the form has a matching \"...Explanation\" or\n"
        "          \"...OtherDescription\" field for that question, ALSO fill that field with the\n"
        "          specific detail from the document (the same content as your grounding quote\n"
        "          is fine).\n\n"
    )
    _SKELETON_CHARS = len(_PROMPT_SKELETON)

    # ── Build a clean, PII-stripped JSON facts block once per call ───────────
    # Strips PII keys, unwraps {value, confidence} envelopes, drops null/empty
    # values. Booleans (flags merged via process_single_form) are preserved so
    # GPT can correctly answer Yes/No checkbox fields that fell through Pass 1.
    def _build_facts_block(_facts: dict) -> str:
        clean: dict = {}
        for _k, _v in (_facts or {}).items():
            if _k in _PII_EXCLUDE_KEYS:
                continue
            # Unwrap annotated envelope from extraction_service._annotate_facts
            if isinstance(_v, dict) and "value" in _v:
                _v = _v.get("value")
            if _v is None:
                continue
            if _k in _SCHEDULE_ROW_PII_SUBKEYS:
                _v = _redact_schedule_rows(_k, _v)
            if isinstance(_v, str):
                if not _v.strip():
                    continue
                _v = _v.strip()
            elif isinstance(_v, list) and len(_v) == 0:
                continue
            elif isinstance(_v, dict) and len(_v) == 0:
                continue
            clean[_k] = _v
        try:
            return json.dumps(clean, indent=2, ensure_ascii=False, default=str)
        except Exception:
            return "{}"

    _facts_block_text = _build_facts_block(facts)
    _facts_block_present = bool(_facts_block_text) and _facts_block_text != "{}"
    _FACTS_SECTION_WRAPPER = (
        "\n\n=== EXTRACTED FACTS (PRIMARY SOURCE — already verified by document analyzer) ===\n"
        "\n=== END EXTRACTED FACTS ===\n"
    )
    _FACTS_BLOCK_CHARS = (
        len(_facts_block_text) + len(_FACTS_SECTION_WRAPPER) if _facts_block_present else 0
    )

    # Fixed overhead per call: skeleton + fields header + footer + facts block
    _FIXED_OVERHEAD = _SKELETON_CHARS + 200 + _FACTS_BLOCK_CHARS

    def _build_user_prompt(active_fields: List[str], raw_chunk: str, chunk_idx: int, total_chunks: int) -> str:
        """Build the variable portion of the prompt (fields + document text).

        The stable instructions live in _PROMPT_SKELETON and are passed as a
        separate system message so OpenAI's automatic prompt caching can
        reuse them across calls for the same form_id. On gpt-4o / gpt-4o-mini
        any prefix ≥1024 tokens is cached automatically — combined with the
        per-form skeleton + form-id this can cut input token cost ~50% and
        TTFT noticeably on hot forms (ACORD 125 etc.).

        Grouped repeating-slot fields are rendered as visual GROUP blocks so
        the LLM can reason about all siblings at once before assigning values.
        """
        # Separate active_fields into singles and per-base slot groups.
        # Bug fix: ACORD's row-letter suffix convention means nearly every field
        # ends in _A..._N even when it has no siblings (e.g. Contractors_
        # SubcontractorsPaidAmount_A has no _B). Routing a true 1-slot field
        # through _slot_group_block() renders it as a fake "REPEATING GROUP"
        # ("find up to 1 distinct value...") instead of the plain field-spec
        # line, which both bloats the prompt for no reason and skips any
        # per-field clarification hook _field_spec() carries. Only real
        # multi-row groups (>1 slot) need group-block treatment.
        active_groups: Dict[tuple, List[str]] = {}
        active_singles: List[str] = []
        for f in active_fields:
            _gk = _group_key(f)
            if _gk and len(_base_to_slots.get(_gk, [])) > 1:
                active_groups.setdefault(_gk, []).append(f)
            else:
                active_singles.append(f)
        for _gk in active_groups:
            active_groups[_gk].sort()

        parts: List[str] = [_field_spec(f) for f in active_singles]
        for _gk, _slots in sorted(active_groups.items()):
            parts.append(_slot_group_block(_gk, _slots))

        fields_block = "\n".join(parts)
        facts_section = (
            "\n\n=== EXTRACTED FACTS (PRIMARY SOURCE — already verified by document analyzer) ===\n"
            f"{_facts_block_text}\n"
            "=== END EXTRACTED FACTS ===\n"
        ) if _facts_block_present else ""
        raw_section  = (
            f"\n\n=== RAW DOCUMENT TEXT (SECONDARY SOURCE — chunk {chunk_idx + 1}/{total_chunks}) ===\n{raw_chunk}"
            if raw_chunk else ""
        )
        return (
            f"Fields to fill ({form_id}):\n{fields_block}"
            + facts_section
            + raw_section
            + '\n\nReturn ONLY valid JSON: {"values": {...}, "raw_text_sourced": [...], "question_grounding": {...}}'
        )

    # Kept under the old name for any external callers; new code should use
    # _build_user_prompt + _PROMPT_SKELETON as a system message.
    def _build_prompt(active_fields: List[str], raw_chunk: str, chunk_idx: int, total_chunks: int) -> str:
        return _PROMPT_SKELETON + _build_user_prompt(active_fields, raw_chunk, chunk_idx, total_chunks)

    # ── LLM caller with retry ─────────────────────────────────────────────────
    def _call_llm_sync(prompt: str) -> dict:
        # Split the historical single-prompt format back into (system, user)
        # so OpenAI's automatic prefix caching can reuse the skeleton.
        if prompt.startswith(_PROMPT_SKELETON):
            system_msg = _PROMPT_SKELETON
            user_msg   = prompt[_SKELETON_CHARS:]
        else:
            # Defensive fallback: caller built a prompt without the skeleton
            # prefix (shouldn't happen, but don't break the call).
            system_msg = _PROMPT_SKELETON
            user_msg   = prompt

        async def _inner(_s=system_msg, _u=user_msg):
            from utils.llm_limiter import get_llm_semaphore
            # JSON-schema response format: typing `values` as a map of string→string
            # (no null permitted) forces the model to OMIT absent fields rather
            # than emit explicit nulls. This cuts output tokens ~10× on null-heavy
            # batches and eliminates the truncation we saw under the 16k cap.
            # Falls back to plain json_object if the model rejects the schema —
            # the response shape is identical either way ({"values": {…}, …}).
            _schema_response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "form_fill_response",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "values": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                            "raw_text_sourced": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "question_grounding": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                        },
                        "required": ["values"],
                        "additionalProperties": False,
                    },
                },
            }
            async with get_llm_semaphore():
                try:
                    resp = await _client.chat.completions.create(
                        model=llm_model,
                        messages=[
                            {"role": "system", "content": _s},
                            {"role": "user",   "content": _u},
                        ],
                        temperature=GPT_TEMPERATURE,
                        response_format=_schema_response_format,
                        max_completion_tokens=_FORM_FILL_MAX_TOKENS,
                    )
                except Exception as _schema_err:
                    # Some models/SDKs don't accept the json_schema response_format —
                    # transparently fall back to json_object so the pipeline never
                    # breaks. We accept the larger response in that case.
                    logger.warning(
                        "gpt_fill: json_schema response_format rejected (%s) — "
                        "falling back to json_object for this call", _schema_err,
                    )
                    resp = await _client.chat.completions.create(
                        model=llm_model,
                        messages=[
                            {"role": "system", "content": _s},
                            {"role": "user",   "content": _u},
                        ],
                        temperature=GPT_TEMPERATURE,
                        response_format={"type": "json_object"},
                        max_completion_tokens=_FORM_FILL_MAX_TOKENS,
                    )
            return resp.choices[0].message.content or ""

        import time as _time
        for attempt in range(_FORM_FILL_BATCH_RETRIES):
            try:
                return json.loads(_run_coro_sync(_inner()))
            except Exception as ex:
                if attempt < _FORM_FILL_BATCH_RETRIES - 1:
                    wait = min(2 ** attempt, 8)
                    logger.warning("gpt_fill: call failed attempt=%d/%d retrying in %ds — %s",
                                   attempt + 1, _FORM_FILL_BATCH_RETRIES, wait, ex)
                    _time.sleep(wait)
                else:
                    logger.warning("gpt_fill: call permanently failed — %s", ex)
                    return {}

    # ── Result absorber ───────────────────────────────────────────────────────
    def _absorb(result: dict, sent: List[str], chunk_label: str = "1/1") -> None:
        values      = result.get("values",          {}) or {}
        raw_sourced = set(result.get("raw_text_sourced", []) or [])
        grounding   = result.get("question_grounding", {}) or {}

        # DIAGNOSTIC: log first 30 entries of GPT response to understand what is returned
        _diag_sample = {k: v for i, (k, v) in enumerate(values.items()) if i < 30}
        logger.info("gpt_fill DIAG_RESPONSE: form=%s chunk=%s total_returned=%d sample=%s",
                    form_id, chunk_label, len(values), json.dumps(_diag_sample, default=str)[:2000])

        filled_count    = 0
        rejected_count  = 0
        rejected_sample: List[str] = []
        non_null_rejected: List[str] = []
        for field, value in values.items():
            if field not in sent:
                continue
            if _is_empty_llm_value(value):
                rejected_count += 1
                if len(rejected_sample) < 8:
                    rejected_sample.append(f"{field}={value!r}")
                # Log non-null rejections separately — these are actual values being filtered
                if value is not None and len(non_null_rejected) < 20:
                    non_null_rejected.append(f"{field}={value!r}")
                logger.debug(
                    "gpt_fill REJECT: form=%s chunk=%s field=%s value=%r",
                    form_id, chunk_label, field, value,
                )
                continue
            vstr = str(value).strip()
            candidate_counts[field][vstr] = candidate_counts[field].get(vstr, 0) + 1
            if field in raw_sourced:
                all_raw_fields.add(field)
            _quote = grounding.get(field)
            if _quote and str(_quote).strip():
                all_question_grounding[field] = str(_quote).strip()
            filled_count += 1

        logger.info(
            "gpt_fill: chunk=%s form=%s sent=%d filled=%d raw_sourced=%d rejected=%d",
            chunk_label,
            form_id, len(sent), filled_count, len(raw_sourced), rejected_count,
        )
        if rejected_sample:
            logger.info(
                "gpt_fill REJECT_SAMPLE: form=%s chunk=%s (%d shown of %d) %s",
                form_id, chunk_label, len(rejected_sample), rejected_count,
                "; ".join(rejected_sample),
            )
        if non_null_rejected:
            logger.info(
                "gpt_fill NON_NULL_REJECTED: form=%s chunk=%s (non-null values being filtered) %s",
                form_id, chunk_label, "; ".join(non_null_rejected),
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
        # No raw text available — skip GPT fill entirely
        logger.warning("gpt_fill: form=%s no raw_text provided — skipping GPT fill", form_id)
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": llm_model}

    # ── Parallel chunk dispatch ────────────────────────────────────────────────
    # When there are multiple chunks, dispatch all LLM calls in parallel using a
    # small thread pool (one thread per chunk, capped at 4).  Each call carries
    # ALL still-unresolved fields; conflicts are resolved by majority vote in
    # _absorb (already handles multi-chunk results correctly).
    #
    # For a single chunk this degenerates to a plain sequential call — no overhead.
    #
    # Sequential override applies in two cases:
    #   (a) field_list > 200 — the prompt is too large to fire 4× in parallel
    #       without saturating the TPM bucket and breaking progressive narrowing.
    #   (b) combined_gap_fill batches (form_id "COMBINED_B<n>of<N>") — these
    #       already arrive as sequential batches of ≤100 fields. Firing the
    #       4 chunks of each batch in parallel lands ~240k tokens on the
    #       OpenAI TPM limit (200k/min) in milliseconds, draining the budget
    #       for the NEXT batch and triggering a 429 storm. Sequential dispatch
    #       lets progressive narrowing trim later chunks and lets the adaptive
    #       semaphore in llm_limiter pace the calls. Full document coverage
    #       is preserved — every chunk is still processed, just one at a time.
    _is_combined_batch = isinstance(form_id, str) and form_id.startswith("COMBINED_B")
    _chunk_pool_size   = (
        1 if (len(field_list) > 200 or _is_combined_batch)
        else min(len(raw_chunks), 4)
    )

    if _chunk_pool_size == 1:
        # Sequential path with REAL progressive narrowing: absorb each chunk's
        # result before dispatching the next, so chunk N+1's active_fields drops
        # everything chunk N already filled. Cuts chunk-2 prompt size 30-50% on
        # combined batches without changing what gets returned. The full
        # document is still scanned — each chunk holds a different slice of raw
        # text and every chunk runs unless every field is already filled.
        for chunk_idx, raw_chunk in enumerate(raw_chunks):
            active_fields = [f for f in field_list if not candidate_counts[f]]
            if not active_fields:
                break
            prompt = _build_prompt(active_fields, raw_chunk, chunk_idx, len(raw_chunks))
            logger.info(
                "gpt_fill: chunk %d/%d form=%s active_fields=%d prompt_chars=%d",
                chunk_idx + 1, len(raw_chunks), form_id, len(active_fields), len(prompt),
            )
            result = _call_llm_sync(prompt)
            _absorb(result, active_fields, chunk_label=f"{chunk_idx + 1}/{len(raw_chunks)}")
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=_chunk_pool_size, thread_name_prefix="gpt-fill-chunk"
        ) as _chunk_pool:
            def _dispatch_chunk(args):
                chunk_idx, raw_chunk = args
                active_fields = [f for f in field_list if not candidate_counts[f]]
                if not active_fields:
                    return chunk_idx, {}, active_fields
                prompt = _build_prompt(active_fields, raw_chunk, chunk_idx, len(raw_chunks))
                logger.info(
                    "gpt_fill: chunk %d/%d form=%s active_fields=%d prompt_chars=%d",
                    chunk_idx + 1, len(raw_chunks), form_id, len(active_fields), len(prompt),
                )
                result = _call_llm_sync(prompt)
                return chunk_idx, result, active_fields

            futures = {
                _chunk_pool.submit(_dispatch_chunk, (i, chunk)): i
                for i, chunk in enumerate(raw_chunks)
            }
            # Collect in submission order so _absorb sees results deterministically
            ordered = sorted(
                (f.result() for f in concurrent.futures.as_completed(futures)),
                key=lambda x: x[0],
            )

        for chunk_idx, result, active_fields in ordered:
            if active_fields:
                _absorb(result, active_fields, chunk_label=f"{chunk_idx + 1}/{len(raw_chunks)}")

    # ── Conflict resolution ───────────────────────────────────────────────────
    # Among candidates from multiple chunks, the most-frequent value wins (majority vote).
    all_filled: dict = {}
    for field, candidates in candidate_counts.items():
        if not candidates:
            continue
        # Majority vote across chunks — raw text is the ground truth
        all_filled[field] = max(candidates, key=lambda v: candidates[v])

    # ── Deduplication: remove values duplicated across repeating-slot siblings ─
    # Safety net for when the LLM assigns the same value to multiple _A/_B/_C
    # slots despite the GROUP block instructions. Walk each group in slot order
    # (_A first) and clear any slot whose value has already appeared in an
    # earlier sibling.  Comparison is case-insensitive and whitespace-normalised.
    # Groups are keyed by (base, tooltip), so different roles that share a base
    # (e.g. lienholder rows vs vehicle-owner rows) are NOT cross-deduped.
    for _gk, _slots in _base_to_slots.items():
        _seen: Dict[str, str] = {}  # normalised_value -> first slot that claimed it
        for _slot_field in _slots:  # already sorted _A, _B, _C, …
            _val = all_filled.get(_slot_field)
            if _val is None:
                continue
            _key = str(_val).strip().lower()
            if _key in _seen:
                logger.info(
                    "gpt_fill: dedup cleared duplicate '%s' from %s (same as %s)",
                    _val, _slot_field, _seen[_key],
                )
                del all_filled[_slot_field]
            else:
                _seen[_key] = _slot_field

    # ── Audit log ─────────────────────────────────────────────────────────────
    for field, value in all_filled.items():
        logger.info(
            "FIELD_SOURCE_AUDIT field=%s source=ai model=%s form_id=%s "
            "raw_text_sourced=%s chunks_agreed=%s",
            field, llm_model, form_id,
            str(field in all_raw_fields).lower(),
            candidate_counts.get(field, {}).get(value, 1),
        )

    logger.info(
        "gpt_fill DONE: form=%s fields_filled=%d/%d chunks=%d model=%s",
        form_id, len(all_filled), len(eligible_fields), len(raw_chunks), llm_model,
    )
    return {
        "filled_values":       all_filled,
        "new_mappings":        {},
        "raw_text_fields":     all_raw_fields,
        "question_grounding":  {f: q for f, q in all_question_grounding.items() if f in all_filled},
        "model_used":          llm_model,
    }


# GL schedule-of-hazards DATA columns (ACORD 126) that the broker fills from a
# class-code / payroll / gross-sales schedule. They must be treated as fillable
# even though the broad "Hazard_" and "Premium" substrings below would otherwise
# blanket-block the entire hazard block — which force-blanked class codes,
# exposure basis, exposure amount, territory and classification and hid the
# high-priority gap the client flagged (Figure 29). The Rate / PremiumAmount
# columns are deliberately NOT here: those are underwriter-computed and stay
# blocked by the "Rate_" / "Premium" substrings.
_GL_HAZARD_FILLABLE_RE = re.compile(
    r"^GeneralLiability_Hazard_"
    r"(ClassCode|PremiumBasisCode|Exposure|TerritoryCode|Classification)_[A-N]$"
)


def _is_nonfillable_field(field: str) -> bool:
    """Return True when a field is carrier-computed or administrative and should
    never be retried via GPT even when its cached fact_key is None.

    These match _RAW_TEXT_SKIP_PATTERNS but are checked by name so we can keep
    Indicator fields OUT of this list (they ARE fillable business fields).
    """
    # Explicit allow (wins over the broad substrings): GL hazard data columns.
    # PremiumBasisCode in particular contains the substring "Premium", so this
    # override is required, not just a matter of dropping "Hazard_".
    if _GL_HAZARD_FILLABLE_RE.match(field):
        return False
    # Explicit allow: CommercialStructure_Location_ProducerIdentifier_{row} is
    # a naming false-positive caught by the "ProducerIdentifier" substring
    # below. Despite the name, its own schema tooltip is "the location number
    # for the premises" (the visible "LOC #" box) - a plain sequential number
    # derived from the canonical location list, not an agency-assigned code.
    # The broad "ProducerIdentifier" block below stays as-is for the fields it
    # was actually added for (Producer_CustomerIdentifier and similar).
    if field.startswith("CommercialStructure_Location_ProducerIdentifier_"):
        return False
    _NONFILLABLE_SUBSTRINGS = (
        "Signature", "_Sig", "InsurerLetterCode",
        "Attachment_", "Hazard_", "Premium", "Rate_", "Revision",
        "EditionIdentifier", "NeedAppearances",
        "Underwriter", "CarrierCode", "PolicyNumber_Carrier",
        # CustomerIdentifier / ProducerIdentifier are carrier- or agency-assigned
        # internal codes not present in policy document text. The gap-fill LLM
        # cannot infer them and hallucinated the producer name instead
        # (e.g. "RSG Specialty Atlanta Binding"). Blocking the entire
        # *Identifier suffix family closes all 116 exposed fields in one shot.
        "CustomerIdentifier",
        "ProducerIdentifier",
    )
    return any(s in field for s in _NONFILLABLE_SUBSTRINGS)


# ── Fact → form-field derivation (Beta Report §4.3) ───────────────────────────
# Used by the Core Underwriting Data reconciler to (a) name the true, complete
# set of forms a confirmed value flows into ("applied to N forms" badge) and
# (b) drive the post-generation cross-form consistency assertion. Pure derivation
# from static config + form schemas; cached.

@lru_cache(maxsize=1)
def _all_form_schemas() -> Dict[str, dict]:
    """Load every ``forms_schemas/ACORD_*_schema.json`` once (the field-name
    source of truth for fact→form derivation). Cached; pure disk read."""
    out: Dict[str, dict] = {}
    try:
        for name in sorted(os.listdir(FORMS_SCHEMAS_DIR)):
            if name.startswith("ACORD_") and name.endswith("_schema.json"):
                form_id = name[: -len("_schema.json")]
                try:
                    with open(os.path.join(FORMS_SCHEMAS_DIR, name), encoding="utf-8") as fh:
                        out[form_id] = json.load(fh)
                except Exception as exc:                  # noqa: BLE001 — skip & continue
                    logger.warning("fact-map: failed to load schema %s — %s", name, exc)
    except Exception as exc:                              # noqa: BLE001
        logger.warning("fact-map: cannot list schemas dir %s — %s", FORMS_SCHEMAS_DIR, exc)
    return out


def _first_rule_fact(field_name: str) -> Optional[str]:
    """The fact key the FIRST matching ``_ACORD_FIELD_RULES`` pattern assigns to
    ``field_name`` — mirrors the substring loop in ``_deterministic_map`` so rule
    shadowing is respected. None when no rule matches."""
    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            return fact_key
    return None


def _is_secondary_row(field_name: str) -> bool:
    """True when ``field_name`` is a non-primary repeating row (_B, _C, ... - a
    SECOND/additional named insured, premises, interest, etc.), False for a
    primary (_A) or non-row field.

    A secondary row is architecturally a DIFFERENT entity, not a repeat of the
    primary row's value - this is the same principle _enforce_post_fill_guards'
    row-dedup guard already relies on ("NamedInsured_FullName_B ... must not
    echo the row-A value"). A scalar fact (e.g. mailing_address) has exactly one
    value, so it can only ever be the SOURCE for the primary row; matching it to
    a secondary row too - as a plain substring match does - manufactures a false
    "value disagrees with source" report whenever that secondary row legitimately
    holds a different (or independently gap-filled) value.
    """
    m = _SCHED_ROW_RE.match(field_name)
    return bool(m and _ROW_LETTER_TO_IDX[m.group(2)] >= 1)


@lru_cache(maxsize=64)
def fact_to_form_fields(fact_key: str) -> Dict[str, Tuple[str, ...]]:
    """Map an extraction fact key to the ACORD form fields that DETERMINISTICALLY
    receive its value, grouped by form id.

    Mirrors the two deterministic stamping paths used by ``map_facts_to_form``:
      * Pass 1   — ``_ACORD_FIELD_RULES`` substring rules (first matching rule wins).
      * Pass 1.5 — per-form alias maps + the ``CANONICAL_TO_EXTRACTION`` bridge.

    Pass 2 (GPT gap fill) is intentionally excluded: it sources from raw document
    text rather than from the merged/confirmed fact, so it does not propagate a
    confirmed value. The result therefore reflects exactly the forms/fields a
    confirmed underwriting value flows into.

    Returns ``{form_id: (field_name, ...)}`` (field names sorted for stability).
    Pure derivation from static config + form schemas; cached.
    """
    result: Dict[str, set] = {}

    # ── Pass 1.5 alias path ──────────────────────────────────────────────────
    try:
        from services.alias_stamper import (
            _ALIAS_MAPS, CANONICAL_TO_EXTRACTION, _load_all_alias_maps,
        )
        _load_all_alias_maps()
        canon_keys = {c for c, k in CANONICAL_TO_EXTRACTION.items() if k == fact_key}
        if canon_keys:
            for form_id, alias_map in _ALIAS_MAPS.items():
                for field, canonical in alias_map.items():
                    if canonical not in canon_keys or _is_nonfillable_field(field):
                        continue
                    if _is_secondary_row(field):
                        continue
                    # Skip fields a Pass-1 rule deterministically claims for a
                    # DIFFERENT fact (alias only runs on Pass-1 leftovers).
                    rf = _first_rule_fact(field)
                    if rf not in (None, fact_key):
                        continue
                    result.setdefault(form_id, set()).add(field)
    except Exception as exc:                              # noqa: BLE001 — never block
        logger.warning("fact-map: alias path failed for %s — %s", fact_key, exc)

    # ── Pass 1 deterministic-rule path ───────────────────────────────────────
    if any(fk == fact_key for _, fk in _ACORD_FIELD_RULES):
        for form_id, schema in _all_form_schemas().items():
            for field in schema:
                if _is_nonfillable_field(field) or _is_secondary_row(field):
                    continue
                if _first_rule_fact(field) == fact_key:
                    result.setdefault(form_id, set()).add(field)

    # ── Pass 1 special-prefix address path ───────────────────────────────────
    # NamedInsured mailing-address sub-fields (LineOne/City/State/Zip) don't map
    # to "mailing_address" directly - _resolve_special() derives them from it at
    # fill-time via the "_addr_*" pseudo-key (see _resolve_special above), and
    # "_loc_*" derives from "physical_address" the same way. Without this, a
    # caller asking fact_to_form_fields("mailing_address") - e.g. field_qa's
    # value-vs-source check - would see NO address fields at all, leaving the
    # single most safety-critical field family (client feedback: "address...
    # must be exact") unchecked. Map the pseudo-key family back to its real
    # source fact so those fields are included like any other.
    #
    # "_addr_*" is scoped to NamedInsured_* fields only, mirroring the same
    # restriction in _deterministic_map: Producer / AdditionalInterest /
    # CertificateHolder addresses are NOT captured as a "mailing_address" fact
    # (they're a different entity's address) and are gap-filled from raw text
    # instead - including them here would compare their correct, independently-
    # sourced value against the NAMED INSURED's address and manufacture a false
    # mismatch. "_loc_*" has no such restriction: both its users
    # (NamedInsured_PhysicalAddress_* and CommercialStructure_PhysicalAddress_*)
    # legitimately mean the insured's own premises.
    for _prefix, _source_fact in (("_addr", "mailing_address"), ("_loc", "physical_address")):
        if fact_key != _source_fact:
            continue
        for form_id, schema in _all_form_schemas().items():
            for field in schema:
                if _is_nonfillable_field(field) or _is_secondary_row(field):
                    continue
                if _prefix == "_addr" and not field.startswith("NamedInsured_"):
                    continue
                rf = _first_rule_fact(field)
                if rf and rf.startswith(_prefix + "_"):
                    result.setdefault(form_id, set()).add(field)

    return {fid: tuple(sorted(fields)) for fid, fields in result.items()}


def expected_value_for_field(field_name: str, fact_key: str, source_value: Any) -> Any:
    """The piece of ``source_value`` a QA/consistency check should compare
    ``field_name`` against, given the source fact it was included in
    ``fact_to_form_fields(fact_key)`` for.

    For an ordinary (non-address) field this is ``source_value`` unchanged. For
    an address sub-field (LineOne/City/State/Zip, routed through the "_addr_*"
    / "_loc_*" special-prefix mechanism - see ``_resolve_special``) the field
    only ever receives ONE piece of the full address, so comparing it against
    the WHOLE address string would manufacture a false mismatch on every
    address field (e.g. stamped "Aurora" vs full "7740 Foundry Ln, Aurora, CO
    80011" would never match as address text). Parses ``source_value`` the same
    way ``_resolve_special`` does and returns the matching piece so a value
    check compares like-for-like.
    """
    rf = _first_rule_fact(field_name)
    if not rf or not any(rf.startswith(p + "_") for p in _SPECIAL_PREFIXES):
        return source_value
    suffix = rf.split("_")[-1]
    return _parse_address(str(source_value or "")).get(suffix, "")


def forms_consuming_fact(fact_key: str) -> List[str]:
    """Sorted list of ACORD form ids a confirmed value for ``fact_key`` flows
    into deterministically. Thin wrapper over :func:`fact_to_form_fields`."""
    return sorted(fact_to_form_fields(fact_key).keys())


def compute_form_gaps(form_id: str, schema: dict, facts: dict) -> Tuple[dict, dict, set]:
    """
    Run Pass 1 (deterministic rules) and Pass 1.5 (alias stamping) ONLY.
    NO LLM call. Pure dictionary lookup.

    Used by the combined cross-form gap-fill orchestrator (Stage 4) to determine
    each form's gap list before running a single shared Pass 2 across all forms.

    Returns
    -------
    mapped : dict
        {field_name: value} for fields filled by Pass 1 + Pass 1.5
        (plus authoritative blanks for non-fillable and out-of-range schedule rows).
    unmatched : dict
        {field_name: schema_meta} for fields that need GPT in Pass 2.
    deterministic_filled : set
        Field names treated as authoritative (no highlight) — superset of `mapped`
        keys that includes deterministic blanks.

    Mirrors the Pass 1 + Pass 1.5 logic at the top of `map_facts_to_form`
    exactly. Kept as a standalone function so the orchestrator can preview gaps
    cheaply without paying for Pass 2.
    """
    if not schema:
        return {}, {}, set()

    mapped: dict = {}
    unmatched: dict = {}
    deterministic_filled: set = set()

    for field in schema.keys():
        # Non-fillable fields (signatures, premiums, rates, underwriter codes)
        # are never sent to GPT.
        if _is_nonfillable_field(field):
            mapped[field] = None
            deterministic_filled.add(field)
            continue

        # Schedule rows resolved against facts["..."] lists.
        sched = _resolve_schedule_row(field, facts)
        if sched is not _SCHED_SKIP:
            if sched is not None and not _is_empty_llm_value(sched):
                mapped[field] = sched
                deterministic_filled.add(field)
            else:
                deterministic_filled.add(field)
            continue

        # Pass 1: _ACORD_FIELD_RULES + address decomposition + indicator derivation.
        result = _deterministic_map(field, facts)
        if result == "UNMATCHED" or _is_empty_llm_value(result):
            unmatched[field] = schema[field]
        else:
            mapped[field] = result
            deterministic_filled.add(field)

    # Pass 1.5: alias-based deterministic stamping (opt-in via flag).
    if unmatched and form_id:
        try:
            from config.settings import ENABLE_ALIAS_STAMPING
            if ENABLE_ALIAS_STAMPING:
                from services.alias_stamper import stamp_form_fields
                alias_filled = stamp_form_fields(form_id, facts, list(unmatched.keys()))
                for field, value in alias_filled.items():
                    if value is not None and not _is_empty_llm_value(value):
                        mapped[field] = value
                        deterministic_filled.add(field)
                        unmatched.pop(field, None)
        except Exception as exc:                # noqa: BLE001 — never block the pipeline
            logger.warning("compute_form_gaps ALIAS form=%s | error: %s", form_id, exc)

    return mapped, unmatched, deterministic_filled


def combined_gap_fill(
    forms_to_unmatched: Dict[str, dict],
    facts: dict,
    raw_text: str,
    model: str = None,
) -> Dict[str, dict]:
    """
    Run ONE shared GPT pass to fill the deduplicated union of gap fields across
    all selected forms (Stage 5 of the extraction architecture).

    Parameters
    ----------
    forms_to_unmatched : Dict[form_id, Dict[field_name, schema_meta]]
        Per-form gap lists (typically produced by `compute_form_gaps`).
    facts : dict
        The shared extraction facts (same dict passed to per-form maps).
    raw_text : str
        Full extracted document text. Chunked internally by `_fill_unmatched_with_gpt`.
    model : str, optional
        Override model id. Default: GPT_MODEL.

    Returns
    -------
    Dict[form_id, {"filled_values": dict, "raw_text_fields": set, "question_grounding": dict, "model_used": str}]
        Per-form fill results, distributed from the shared LLM output. Each form
        only receives values for fields *it* asked for.

    Design notes
    ------------
    Fields are deduplicated by exact ACORD name (e.g. `Producer_FullName_A`).
    Across our 17 schemas, ~858 of 4571 unique field names appear in 2+ forms;
    those de-dupe automatically. Form-unique fields are passed through unchanged.

    Same chunking, retries, prompt skeleton, and majority-vote conflict
    resolution as the existing per-form Pass 2 — implemented by delegating to
    `_fill_unmatched_with_gpt` with the unioned input.
    """
    # Default empty results per form so callers can iterate safely.
    empty_result_for = lambda: {                      # noqa: E731
        "filled_values": {},
        "raw_text_fields": set(),
        "question_grounding": {},
        "model_used": model or GPT_MODEL,
    }
    per_form: Dict[str, dict] = {fid: empty_result_for() for fid in forms_to_unmatched}

    if not forms_to_unmatched:
        return per_form

    # Build union (dedup by ACORD field name) + form-ownership index.
    union_unmatched: dict = {}
    field_to_forms: Dict[str, list] = {}
    for form_id, fields_meta in forms_to_unmatched.items():
        if not fields_meta:
            continue
        for field_name, meta in fields_meta.items():
            if field_name not in union_unmatched:
                union_unmatched[field_name] = meta
            field_to_forms.setdefault(field_name, []).append(form_id)

    if not union_unmatched:
        return per_form

    total_asks   = sum(len(v or {}) for v in forms_to_unmatched.values())
    dedup_count  = len(union_unmatched)
    saved_pct    = 0 if total_asks == 0 else round(100 * (1 - dedup_count / total_asks))
    logger.info(
        "combined_gap_fill: forms=%d union_fields=%d total_asks=%d savings=%d%%",
        len(forms_to_unmatched), dedup_count, total_asks, saved_pct,
    )

    # GPT pass: batch fields into groups of _COMBINED_FIELD_BATCH (default 100).
    # With 1531 fields the fields block alone is ~612k chars, leaving almost no
    # budget for raw text inside _fill_unmatched_with_gpt. Batching keeps each
    # fields block ~40k chars so _fill_unmatched_with_gpt gets ~309k chars of
    # raw text budget per chunk (3 chunks for a 671k doc) — the full document
    # is still scanned; we do NOT truncate the document here.
    field_items = list(union_unmatched.items())
    batches = [
        dict(field_items[i : i + _COMBINED_FIELD_BATCH])
        for i in range(0, len(field_items), _COMBINED_FIELD_BATCH)
    ]
    logger.info(
        "combined_gap_fill: field_batches=%d batch_size=%d total_fields=%d",
        len(batches), _COMBINED_FIELD_BATCH, len(field_items),
    )

    all_filled_values: dict = {}
    all_raw_text_fields: set = set()
    all_question_grounding: dict = {}
    used_model = model or GPT_MODEL

    import time as _time
    for batch_idx, batch_fields in enumerate(batches):
        batch_id = f"COMBINED_B{batch_idx + 1}of{len(batches)}"
        # Pause between batches so the OpenAI TPM bucket refills. Without this
        # back-to-back batches each consumed ~60k input tokens and the first
        # chunk of every batch hit 429 → ~10s automatic backoff (see prod logs).
        # The 2s pause costs ~12s total but saves ~120s of cumulative 429 waits.
        if batch_idx > 0 and _COMBINED_BATCH_PAUSE_S > 0:
            _time.sleep(_COMBINED_BATCH_PAUSE_S)
        try:
            gpt_result = _fill_unmatched_with_gpt(
                batch_fields, facts, batch_id, model=model, raw_text=raw_text,
            )
        except Exception as exc:                      # noqa: BLE001
            logger.warning("combined_gap_fill: batch %s failed — %s", batch_id, exc)
            continue
        all_filled_values.update(gpt_result.get("filled_values", {}) or {})
        all_raw_text_fields.update(gpt_result.get("raw_text_fields", set()) or set())
        all_question_grounding.update(gpt_result.get("question_grounding", {}) or {})
        used_model = gpt_result.get("model_used", used_model)

    filled_values   = all_filled_values
    raw_text_fields = all_raw_text_fields

    # Distribute results back to each requesting form. A value flows to every
    # form that asked for that field name; it does NOT bleed into forms that
    # did not request it.
    for field_name, value in filled_values.items():
        for form_id in field_to_forms.get(field_name, []):
            per_form[form_id]["filled_values"][field_name] = value

    for field_name in raw_text_fields:
        for form_id in field_to_forms.get(field_name, []):
            per_form[form_id]["raw_text_fields"].add(field_name)

    for field_name, quote in all_question_grounding.items():
        for form_id in field_to_forms.get(field_name, []):
            per_form[form_id]["question_grounding"][field_name] = quote

    for form_id in per_form:
        per_form[form_id]["model_used"] = used_model

    return per_form


# Legal-entity indicator types in mutual-exclusion priority order. When a row
# has more than one entity-type box marked "Yes" (e.g. the LLM checked both
# Corporation and LLC), only the highest-priority surviving box is kept. LLC is
# first because the reported failure was exactly "Corporation AND LLC both
# checked" for a Limited Liability Company.
_LEGAL_ENTITY_INDICATOR_PRIORITY = (
    "LimitedLiabilityCorporationIndicator",
    "CorporationIndicator",
    "SubchapterSCorporationIndicator",
    "PartnershipIndicator",
    "JointVentureIndicator",
    "TrustIndicator",
    "NotForProfitIndicator",
    "IndividualIndicator",
    "OtherIndicator",
)

_ENTITY_BASE_RE = re.compile(r"^(.*LegalEntity_)(\w+Indicator)_([A-N])$")

# ── Post-fill guard helpers (Guards 3 & 4) ───────────────────────────────────
_CHECKBOX_VALID_VALUES = frozenset({
    "yes", "no", "y", "n", "true", "false", "1", "0", "on", "off", "x", "checked",
})

# Tokens that mark a field as PROSE-expecting — such fields are never treated as
# numeric/date even if a numeric hint also appears in the name (e.g.
# "AnyExposure...Explanation", "Hazard_Classification").
_PROSE_FIELD_TOKENS = (
    "Explanation", "Description", "Remark", "Comment", "Operations",
    "Classification", "Narrative", "FullName", "Address", "Name",
)
# Field-name hints that a value must be numeric / a code / a date — never prose.
# Deliberately tight: "Number" is excluded (policy numbers are alphanumeric).
_NUMERIC_DATE_FIELD_HINTS = (
    "_Amount", "Deductible", "Count", "Percent", "PostalCode", "ZipCode",
    "Hazard_Exposure", "YearBuilt", "ModelYear", "OwnershipPercent", "Date",
)


def _is_numeric_or_date_field(field: str) -> bool:
    if any(t in field for t in _PROSE_FIELD_TOKENS):
        return False
    return any(h in field for h in _NUMERIC_DATE_FIELD_HINTS)


def _looks_like_number_or_date(s: str) -> bool:
    """True when the string is only digits/punctuation/currency/space — a number,
    code, money or date carrying no prose words."""
    return bool(re.fullmatch(r"[\s\d.,/$%()\-:+#]+", s or ""))


# ── Guard 4 similarity helpers (paraphrased-boilerplate detection) ──────────
_BOILERPLATE_SIMILARITY_THRESHOLD = 0.75
_BOILERPLATE_MIN_SHARED_TOKENS = 4


def _sim_tokens(s: str) -> frozenset:
    """Lowercased word-tokens (len >= 3) used for near-duplicate comparison —
    order-insensitive, so a reworded/reordered sentence still matches."""
    return frozenset(t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) >= 3)


def _is_near_duplicate_text(a: frozenset, b: frozenset) -> bool:
    """True when two token sets are similar enough to be the same boilerplate
    idea paraphrased, not merely two answers that happen to share a few common
    words. Requires both a minimum absolute token overlap and a high Jaccard
    ratio, so two short, topically-adjacent-but-distinct answers don't collide."""
    if len(a) < _BOILERPLATE_MIN_SHARED_TOKENS or len(b) < _BOILERPLATE_MIN_SHARED_TOKENS:
        return False
    inter = a & b
    if len(inter) < _BOILERPLATE_MIN_SHARED_TOKENS:
        return False
    union = a | b
    return (len(inter) / len(union)) >= _BOILERPLATE_SIMILARITY_THRESHOLD


_AFFIRMATIVE_VALUES = frozenset({"yes", "y", "true", "1", "on"})
_NEGATIVE_VALUES    = frozenset({"no", "n", "false", "0", "off"})

# Narrative answers that justify/explain a prior Yes/No or "Other" selection.
# "…Explanation" is the dominant ACORD naming convention (117 fields across the
# 17 schemas), but "…OtherDescription" ("Other" box checked -> please specify,
# 62 fields) and "…ResolutionDescription" (a compliance follow-up: foreclosure /
# lien / fire-code violation -> how was it resolved) are the same shape of
# field under a different suffix. Deliberately NOT "Description" alone - most
# Description fields (OperationsDescription, ItemDescription, AlarmDescription,
# ...) are core required content, not a Yes/No justification, and evidence-
# gating those would wrongly blank legitimate broker-needed data.
_EVIDENCE_REQUIRED_TOKENS = ("Explanation", "OtherDescription", "ResolutionDescription")

# Matches the Yes/No "…Question_<code>Code_<row>" convention used for compliance
# questions across ACORD 125/126/127/130/131/141/160/186 (e.g.
# "WorkersCompensationLineOfBusiness_Question_ABFCode_A").
_QUESTION_CODE_RE = re.compile(r"_Question_[A-Za-z0-9]+Code_[A-N]$")

# The ACORD schema's own boilerplate for a Yes/No TEXT field that does NOT use
# the "_Question_<code>Code_" name convention at all - verified byte-identical
# on every "_Question_<code>Code_" field AND on plain Y/N fields that don't
# follow that naming (e.g. ACORD 140's CommercialProperty_Spoilage_YesNoCode_A /
# …RefrigeratorMaintenanceCode_A, ACORD 25's equivalents). This is the schema
# itself TELLING us the field is Yes/No, independent of what it's named.
_YES_NO_TOOLTIP_PREFIX = "Enter Y for a “Yes” response."


def _is_yes_no_field(field: str, schema: dict) -> bool:
    """True when `field` is structurally a Yes/No answer - covering every ACORD
    naming convention for one across all 17 forms, not just the compliance
    "_Question_<code>Code_" family (client requirement: "in all the forms...
    certain fields where Y/N/Yes/No to be filled"). Three independent,
    schema-driven signals - any one is sufficient:
      1. The "_Question_<code>Code_<row>" name pattern (compliance questions).
      2. ft == "/Btn" - a checkbox is structurally boolean by PDF form design,
         whatever it's named: coverage accept/reject (sink hole, mine
         subsidence), building features, LOB selection, entity type, auto
         ownership/HNOA, ...
      3. The field's own tooltip carries the ACORD "Enter Y for a Yes
         response..." boilerplate - the same Yes/No convention on a plain
         /Tx field that uses neither of the above.
    Deliberately structural (field type / tooltip metadata already in the
    schema), never a guess from the field's semantic name - matching the
    project's standing rule against topic/keyword-overlap heuristics (see
    _question_explanation_pairs and the evidence-gate design notes).
    """
    if _QUESTION_CODE_RE.search(field):
        return True
    meta = schema.get(field)
    if not isinstance(meta, dict):
        return False
    if meta.get("ft") == "/Btn":
        return True
    tu = meta.get("tu")
    return bool(tu) and str(tu).startswith(_YES_NO_TOOLTIP_PREFIX)


def _is_high_impact_checkbox_field(field: str, tooltip: Optional[str], ft: Optional[str]) -> bool:
    """True for a checkbox (``/Btn``) field that is high-impact (Figure 33: auto
    ownership / HNOA / leasing / hazardous-materials / maintenance) but does NOT
    already follow the ``_Question_<code>Code_`` naming convention the evidence
    gate recognizes by field name alone.

    Found in audit: ACORD 137_CA/137_CO/138_CA/138_CO express their HNOA-
    equivalent question as a checkbox pair (``Vehicle_HiredBorrowed_YesIndicator_A``
    / ``_NoIndicator_A``, ``Vehicle_TruckersHiredBorrowed_*``) or an opaque numeric
    symbol box (``Vehicle_GarageAndDealersSymbol_TwentyEightIndicator_A`` = hired
    auto). None of these match ``_QUESTION_CODE_RE``, so — before this — a
    hallucinated "Yes" on one of them was never blanked by the evidence gate,
    only soft-flagged for review via ``is_high_impact_field`` + low_confidence.
    That is weaker than the "never inferred loosely" the client asked for.

    SHARED by the gap-fill prompt builder (``_fill_unmatched_with_gpt``, which
    marks the field so the model must cite a grounding quote) and
    ``map_facts_to_form``'s evidence gate (which enforces it) so the two can
    never silently drift apart — same pattern as ``is_value_contaminated`` /
    ``detect_field_mapping_contamination`` sharing ``_classify_value``.
    """
    if "/Btn" not in (ft or ""):
        return False
    if _QUESTION_CODE_RE.search(field or ""):
        return False  # already covered by the name-shape rule
    try:
        from services.field_mapping_integrity import is_high_impact_field
    except Exception:                              # noqa: BLE001
        return False
    return is_high_impact_field(field, tooltip)


def _is_evidence_required_field(field: str) -> bool:
    """Narrative answers to Yes/No application questions (the "…Explanation" /
    "…OtherDescription" / "…ResolutionDescription" fields — e.g. ACORD 126
    claims-made / employee-benefits sections). Under ENABLE_EVIDENCE_GATED_FILL
    these are stamped only when the gap-fill LLM copied them from the document,
    never when inferred (client Figure 30)."""
    return any(token in field for token in _EVIDENCE_REQUIRED_TOKENS)


def _question_explanation_pairs(schema: dict) -> Dict[str, str]:
    """Map each Yes/No field to its own paired "…Explanation"/"…OtherDescription"/
    "…ResolutionDescription" field, using the ACORD layout convention that the
    question immediately precedes its own explanation in the form (and
    therefore in the schema, whose key order mirrors the source PDF). A pair
    is accepted ONLY when the very next schema field actually contains one of
    those tokens - never inferred from position alone - so an unrelated
    neighboring field (another question, a table header, a producer-
    identifier column) is never mistaken for this answer's justification.
    Confirmed against ACORD_130/127/160: most Question codes pair this way;
    the ones that don't (no adjacent Explanation) are simply excluded, which
    is the safe default.

    Eligible LEFT-side fields are "_Question_<code>Code_" text fields OR any
    /Btn checkbox (audited across all 17 schemas: this is exactly the shape of
    the extremely common "…OtherIndicator_<row>" checkbox -> "…OtherDescription
    _<row>" text pair - "Other" is checked, please specify - present on 10+
    forms and previously invisible to this function entirely). Deliberately
    NOT the broader _is_yes_no_field tooltip-convention signal here: auditing
    all 17 schemas found two cases where a plain Y/N /Tx field happens to sit
    directly before an unrelated Explanation field from a different section
    (ACORD 126 PropertyItem_ItemDetail_InstructionGivenCode_A ->
    ...MachineryOrEquipmentLoanedRentedOthersExplanation_B; ACORD 141
    BuildingProtection_DoubleCylinderDoorLockCode_A -> CrimeInformation_
    OtherDescription_A) - real coincidental adjacency, not a real pair. A
    checkbox's own PDF layout position is a stronger structural signal than an
    arbitrarily-ordered Y/N text field, so pairing trusts /Btn but not the
    tooltip-only signal; _is_yes_no_field is still used for gating the
    checkbox/text field's OWN answer regardless of whether it pairs."""
    keys = list(schema.keys())
    pairs: Dict[str, str] = {}
    for i, k in enumerate(keys):
        if i + 1 >= len(keys) or not any(t in keys[i + 1] for t in _EVIDENCE_REQUIRED_TOKENS):
            continue
        meta = schema.get(k)
        is_pairable = _QUESTION_CODE_RE.search(k) or (isinstance(meta, dict) and meta.get("ft") == "/Btn")
        if is_pairable:
            pairs[k] = keys[i + 1]
    return pairs


# ── Non-adjacent companion fields (Figure 33 audit finding, live test 2026-07-15) ─
# ACORD 127's vehicle-ownership question is "explained" not by a single adjacent
# free-text field (the _question_explanation_pairs convention above) but by the
# "Name of Other Owner" schedule (AdditionalInterest_FullName_C/_D - see
# repeating_group_key's own note on why these are a SEPARATE role from _A/_B's
# lienholder schedule). A Vehicle_ProducerIdentifier_AA field sits between the
# question and the first owner-name slot in the real schema, so the adjacency
# check above never finds it - the question was permanently treated as
# "unpaired" (no Explanation field at all), relying solely on its own
# grounding quote even when the owner-name box was independently, correctly
# filled with a real name. Explicit and narrow by design (same pattern as
# _INDICATOR_RULES / _FIELD_SPEC_CLARIFICATIONS elsewhere in this file) rather
# than a generalized non-adjacent-pairing mechanism, since this specific
# mismatch was checked by hand against the real schema, not inferred.
_NONADJACENT_QUESTION_COMPANIONS: Dict[str, tuple] = {
    "CommercialVehicleLineOfBusiness_Question_AAJCode_A": (
        "AdditionalInterest_FullName_C", "AdditionalInterest_FullName_D",
    ),
}


# ── Non-adjacent DEPENDENT fields (Figure 33 audit finding, live test 2026-07-15) ─
# The inverse relationship from _NONADJACENT_QUESTION_COMPANIONS above: ACORD
# 127's "any car modified / special equipment?" question (AAGCode) has its own
# per-vehicle DESCRIPTION/COST sub-fields (Vehicle_Question_
# ModifiedEquipmentDescription_A/_B, ...CostAmount_A/_B) - plain free-text
# fields with no "Explanation"/"OtherDescription" suffix, so they are neither
# gated by the evidence gate nor covered by Guard 5's adjacent-Explanation
# check (_enforce_post_fill_guards). Found in audit: the gap-fill LLM filled
# DESCRIPTION with a sentence lifted from a DIFFERENT vehicle's ownership note
# even though the question itself correctly stayed blank/ungrounded - these
# dependent fields must never carry a value when their own parent question
# isn't a genuine "Yes" (enforced by Guard 6).
_NONADJACENT_DEPENDENT_FIELDS: Dict[str, tuple] = {
    "CommercialVehicleLineOfBusiness_Question_AAGCode_A": (
        "Vehicle_Question_ModifiedEquipmentDescription_A", "Vehicle_Question_ModifiedEquipmentCostAmount_A",
        "Vehicle_Question_ModifiedEquipmentDescription_B", "Vehicle_Question_ModifiedEquipmentCostAmount_B",
    ),
}


# ── ACORD 101 overflow routing (Figure 29) ───────────────────────────────────
# A single ACORD /Tx field holds far less than a full operations/classification
# narrative. When such text exceeds this budget it is routed IN FULL to the
# ACORD 101 "Additional Remarks" section — losslessly (the originating form's
# field is never truncated). Gated by ENABLE_ACORD101_OVERFLOW.
_OVERFLOW_CHAR_THRESHOLD = 300
_ACORD101_REMARK_ROWS = ("A", "B", "C", "D", "E", "F")


def _compose_acord101_remarks(facts: dict) -> List[str]:
    """Ordered, de-duplicated remark blocks destined for ACORD 101."""
    blocks: List[str] = []
    # 1. Explicit remarks fact (conflict explanations, client answers via ARQ).
    for key in ("acord101_remarks", "additional_remarks_text"):
        v = _fv(facts, key)
        if not v:
            continue
        if isinstance(v, list):
            blocks.extend(str(x).strip() for x in v if str(x).strip())
        elif str(v).strip():
            blocks.append(str(v).strip())
    # 2. Oversized operations narrative that will not fit its form field.
    ops = _fv(facts, "operations_description")
    if ops and len(str(ops).strip()) > _OVERFLOW_CHAR_THRESHOLD:
        blocks.append("Operations (continued): " + str(ops).strip())
    seen: set = set()
    out: List[str] = []
    for b in blocks:
        k = b.lower()
        if k and k not in seen:
            seen.add(k)
            out.append(b)
    return out


def _apply_acord101_overflow(mapped: dict, schema: dict, facts: dict,
                             deterministic_filled: set) -> None:
    """Stamp ACORD 101 RemarkText rows from the composed remark blocks. Remarks
    are authoritative for ACORD 101, so this overrides any gap-fill guess. Any
    surplus beyond the last available row is concatenated into it (never dropped)."""
    blocks = _compose_acord101_remarks(facts)
    if not blocks:
        return
    rows = [
        f"AdditionalRemark_RemarkText_{r}"
        for r in _ACORD101_REMARK_ROWS
        if f"AdditionalRemark_RemarkText_{r}" in schema
    ]
    if not rows:
        return
    if len(blocks) > len(rows):
        values = blocks[: len(rows) - 1] + ["\n\n".join(blocks[len(rows) - 1:])]
    else:
        values = blocks
    for field, text in zip(rows, values):
        mapped[field] = text
        deterministic_filled.add(field)
    logger.info("acord101_overflow: filled %d remark row(s) from %d block(s)",
                len(values), len(blocks))


def _enforce_post_fill_guards(mapped: dict, schema: dict, facts: dict) -> None:
    """Deterministic safety nets applied to `mapped` in place AFTER all fill
    passes (Pass 1, alias, GPT). These do NOT depend on how a value was filled,
    so they catch LLM mistakes the prompt could not guarantee against.

    Guard 1 - Legal-entity mutual exclusion: an entity is exactly one legal
              type. If multiple LegalEntity_*Indicator boxes in the same row
              are "Yes", keep only the highest-priority one and blank the rest.

    Guard 2 - Repeating-row de-duplication: non-schedule repeating rows
              (NamedInsured_FullName_B, premises rows, etc.) must not echo the
              row-A value. Schedule / GL-hazard / subject-of-insurance fields
              are exempt - two vehicles can share a model year, and two
              different locations can both have a "Building" subject at
              genuinely different dollar amounts. Only collapses an exact
              duplicate of row A.

    Guard 3 - Wrong-type value rejection: prose dropped into a checkbox or a
              numeric/date cell (e.g. a contractor description in a per-claim
              deductible box) is always wrong — blank it (Figure 30).

    Guard 4 - Cross-field boilerplate bleed: the same generic sentence pasted
              into 3+ unrelated field families is boilerplate, not data. Keep
              only the field(s) whose own deterministic rule produces that value
              and blank the rest (Figure 30).

    Guard 5 - Explanation without a "Yes": every ACORD Question/Explanation
              pair's own field text reads "an explanation IF [X]" - the
              explanation only applies when the paired question is Yes. A
              filled Explanation whose paired Question is anything else (No,
              or any other non-affirmative answer) is answering a question
              that was never asked - blank it. This is a structural check,
              independent of ENABLE_EVIDENCE_GATED_FILL: even a verbatim,
              document-grounded sentence is wrong here if it's attached to a
              "No".

    Guard 6 - Non-adjacent dependent field without a "Yes": the same
              invariant as Guard 5, for a dependent field the adjacency-based
              pairing can't find (see _NONADJACENT_DEPENDENT_FIELDS - e.g. a
              plain "...Description"/"...CostAmount" sub-field, not
              "...Explanation"-suffixed). Also fires on a BLANK question, not
              just an explicit "No".
    """
    # ── Guard 1: legal-entity mutual exclusion ───────────────────────────────
    # Group entity indicator fields present in this schema by their row letter.
    rows: Dict[str, Dict[str, str]] = {}
    for field in schema:
        m = _ENTITY_BASE_RE.match(field)
        if not m:
            continue
        _prefix, indicator_type, row = m.group(1), m.group(2), m.group(3)
        if indicator_type in _LEGAL_ENTITY_INDICATOR_PRIORITY:
            rows.setdefault(row, {})[indicator_type] = field

    # Derive the ground-truth entity type from extracted facts once so each row
    # can prefer the box that matches the fact over the hardcoded priority order.
    _raw_entity = str(_fv(facts, "entity_type") or "").lower()
    _fact_entity_indicator: Optional[str] = None
    if _raw_entity:
        for _llc_phrase in ("limited liability corporation", "limited liability company",
                            "limited liability corp", "llc corp", "llc corporation", "llc"):
            if _llc_phrase in _raw_entity:
                _fact_entity_indicator = "LimitedLiabilityCorporationIndicator"
                break
        if _fact_entity_indicator is None:
            for _ind, _phrases in (
                ("SubchapterSCorporationIndicator", ("s-corp", "s corp", "subchapter s")),
                ("CorporationIndicator",            ("corporation", "corp", "inc", "incorporated")),
                ("PartnershipIndicator",            ("partnership", "llp", "lp")),
                ("JointVentureIndicator",           ("joint venture",)),
                ("TrustIndicator",                  ("trust",)),
                ("NotForProfitIndicator",           ("non-profit", "nonprofit", "not for profit", "not-for-profit")),
                ("IndividualIndicator",             ("individual", "sole prop")),
            ):
                if any(p in _raw_entity for p in _phrases):
                    _fact_entity_indicator = _ind
                    break

    for row, type_to_field in rows.items():
        marked = [
            t for t, f in type_to_field.items()
            if str(mapped.get(f) or "").strip().lower() in ("yes", "true", "1")
        ]
        if len(marked) <= 1:
            continue
        # Multiple boxes checked → prefer the one matching the extracted entity_type
        # fact (ground truth); fall back to hardcoded priority order when no fact.
        if _fact_entity_indicator and _fact_entity_indicator in marked:
            keep = _fact_entity_indicator
        else:
            keep = next(
                (t for t in _LEGAL_ENTITY_INDICATOR_PRIORITY if t in marked),
                marked[0],
            )
        for t in marked:
            if t != keep:
                mapped[type_to_field[t]] = "No"
        logger.info(
            "post_fill_guard entity_exclusion row=%s kept=%s blanked=%s",
            row, keep, [t for t in marked if t != keep],
        )

    # ── Guard 2: repeating-row de-duplication ────────────────────────────────
    for field in schema:
        m = _SCHED_ROW_RE.match(field)
        if not m:
            continue
        base, letter = m.group(1), m.group(2)
        if _ROW_LETTER_TO_IDX[letter] < 1:
            continue  # row A is the canonical row — never blanked
        if _is_schedule_field(field) or _GL_HAZARD_ROW_RE.match(field) or _SUBJECT_OF_INSURANCE_RE.match(field):
            continue  # schedule / GL hazard / subject-of-insurance rows may legitimately repeat values
        # Checkbox/indicator rows legitimately share Yes/No across distinct entities
        # (two LLCs both have LLC=Yes; two locations can both be "inside city limits").
        # De-duplication must only collapse free-text VALUE rows (names, addresses).
        val = mapped.get(field)
        if val is None:
            continue
        if "Indicator" in field or str(val).strip().lower() in ("yes", "no", "true", "false"):
            continue
        row_a = f"{base}_A"
        a_val = mapped.get(row_a)
        if a_val is not None and str(val).strip() and str(val).strip() == str(a_val).strip():
            mapped[field] = None
            logger.info("post_fill_guard row_dedup blanked=%s (== %s)", field, row_a)

    # ── Guard 3: wrong-type value rejection ──────────────────────────────────
    # An LLM sometimes drops a prose description into a field that structurally
    # cannot hold prose (a checkbox, or a numeric/date cell) — e.g. the reported
    # "COMMERCIAL GENERAL CONTRACTOR" landing in a per-claim DEDUCTIBLE box
    # (Figure 30). These are always wrong, so blank them deterministically.
    for field, val in list(mapped.items()):
        if val is None or not isinstance(val, str):
            continue
        s = val.strip()
        if not s:
            continue
        meta = schema.get(field) or {}
        is_checkbox = isinstance(meta, dict) and meta.get("ft") == "/Btn"
        prose_like = bool(re.search(r"[A-Za-z]{3,}\s+[A-Za-z]{3,}", s))
        if is_checkbox and s.lower() not in _CHECKBOX_VALID_VALUES:
            mapped[field] = None
            logger.info("post_fill_guard type_reject blanked=%s (checkbox got %r)", field, s[:40])
        elif prose_like and _is_numeric_or_date_field(field):
            mapped[field] = None
            logger.info("post_fill_guard type_reject blanked=%s (numeric/date got prose %r)", field, s[:40])

    # ── Guard 4: cross-field boilerplate bleed ───────────────────────────────
    # The same generic sentence pasted into several UNRELATED fields is boilerplate
    # bleed, not real data (Figure 30). Group non-trivial free-text values; when one
    # value spans 2+ distinct field families ("multiple unrelated fields" per the
    # requirement), keep only the field(s) whose own deterministic rule legitimately
    # produces that value (e.g. the real operations description field) and blank
    # the rest.
    #
    # Grouping is exact-match FIRST (identical strings always cluster, regardless
    # of length) and near-duplicate SECOND: the more common LLM failure mode is
    # not verbatim copy-paste but the same idea paraphrased into several fields, so
    # values are also clustered by token-Jaccard similarity against the first
    # member of each cluster. A cluster's representative tokens are fixed at its
    # first member deliberately — cheap, and sufficient to catch the paraphrase-
    # bleed pattern without O(n^2) pairwise recomputation.
    candidates: List[Tuple[str, str]] = []
    for field, val in mapped.items():
        if not isinstance(val, str):
            continue
        s = val.strip()
        if len(s) < 20 or " " not in s or _looks_like_number_or_date(s):
            continue
        candidates.append((field, s))

    clusters: List[List[Tuple[str, str]]] = []
    cluster_tokens: List[frozenset] = []
    for field, s in candidates:
        s_l = s.lower()
        toks = _sim_tokens(s)
        for ci, rep_tokens in enumerate(cluster_tokens):
            if s_l == clusters[ci][0][1].lower() or _is_near_duplicate_text(toks, rep_tokens):
                clusters[ci].append((field, s))
                break
        else:
            clusters.append([(field, s)])
            cluster_tokens.append(toks)

    # An explanation currently paired to a kept (affirmative) Question-code
    # answer already went through the evidence gate's own grounding check
    # (Figure 30 Pass A - see map_facts_to_form) — it is a CONFIRMED answer,
    # not a guess. Without this exemption, Guard 4 silently undoes that
    # verification whenever the model reused the same real citation as its
    # (wrong) grounding for OTHER unrelated Yes/No questions in the same
    # batch: every field sharing that text gets blanked here, INCLUDING the
    # one it was actually true for, which reintroduces a bare "Yes" with no
    # explanation - exactly the failure Pass A exists to prevent. Found via
    # live test 2026-07-13 (MVR question kept "Y", explanation wiped).
    _exp_to_kept_q = {exp: q for q, exp in _question_explanation_pairs(schema).items()}

    for cluster in clusters:
        fields = [f for f, _ in cluster]
        families = {
            (_SCHED_ROW_RE.match(f).group(1) if _SCHED_ROW_RE.match(f) else f)
            for f in fields
        }
        if len(families) < 2:
            continue  # not a broad enough spread to be confident it's bleed
        for f, s in cluster:
            det = _deterministic_map(f, facts)
            legit_owner = isinstance(det, str) and det.strip().lower() == s.lower()
            paired_q = _exp_to_kept_q.get(f)
            is_confirmed_yes_explanation = (
                paired_q is not None
                and str(mapped.get(paired_q) or "").strip().lower() in _AFFIRMATIVE_VALUES
            )
            if not legit_owner and not is_confirmed_yes_explanation:
                mapped[f] = None
                logger.info("post_fill_guard boilerplate_bleed blanked=%s", f)

    # ── Guard 5: explanation without a "Yes" ──────────────────────────────────
    for q_field, exp_field in _question_explanation_pairs(schema).items():
        exp_val = mapped.get(exp_field)
        if not (isinstance(exp_val, str) and exp_val.strip()):
            continue
        q_val = str(mapped.get(q_field) or "").strip().lower()
        if q_val and q_val not in _AFFIRMATIVE_VALUES:
            mapped[exp_field] = None
            logger.info(
                "post_fill_guard explanation_without_yes blanked=%s (question=%s answer=%r)",
                exp_field, q_field, q_val,
            )

    # ── Guard 6: non-adjacent dependent field without a "Yes" ─────────────────
    # See _NONADJACENT_DEPENDENT_FIELDS - the same "no Yes, no supporting
    # content" invariant as Guard 5, for dependent fields the adjacency-based
    # _question_explanation_pairs can't find (a plain "...Description"/
    # "...CostAmount" field, not "...Explanation"-suffixed). Unlike Guard 5,
    # this also fires when the question is BLANK (not just an explicit "No") -
    # a dependent description/cost has no legitimate standalone meaning
    # without its own parent question being a genuine "Yes".
    for q_field, dep_fields in _NONADJACENT_DEPENDENT_FIELDS.items():
        if q_field not in schema:
            continue
        q_val = str(mapped.get(q_field) or "").strip().lower()
        if q_val in _AFFIRMATIVE_VALUES:
            continue
        for dep_field in dep_fields:
            if mapped.get(dep_field) is not None:
                mapped[dep_field] = None
                logger.info(
                    "post_fill_guard dependent_without_yes blanked=%s (question=%s answer=%r)",
                    dep_field, q_field, q_val,
                )


# Values the AI can produce that are never literally present in the document
# text (they are reasoned out, not copied) — a presence check is meaningless for
# them, so they are treated as "not verifiable" rather than falsely flagged.
_VERIFY_SKIP_TOKENS = {
    "yes", "no", "y", "n", "true", "false", "on", "off", "x",
    "null", "none", "n/a", "na",
}


def _normalize_for_search(text: str) -> str:
    """Fold text to a punctuation/case/whitespace-insensitive form for literal
    presence checks. Any run of non-alphanumerics becomes a single space, so
    "$6,150,000" → "6 150 000", "4/1/2026" → "4 1 2026", and OCR line breaks
    collapse. Both the document text and the value are folded the SAME way, so
    formatting differences never break a match."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _value_in_raw_text(value: str, haystack_norm: str) -> bool:
    """True when `value` (as the AI produced it) actually appears in the uploaded
    document text (already normalized via `_normalize_for_search`).

    Deliberately conservative — biased AWAY from false "not found" flags: a
    word-subset fallback treats a lightly reworded value (dropped suffix,
    reordered tokens) as present. Yes/No answers and very short values are not
    meaningfully verifiable by presence and return False (they are handled by the
    existing confidence logic, not painted "verified")."""
    raw = (value or "").strip()
    if not raw or raw.lower() in _VERIFY_SKIP_TOKENS:
        return False
    needle = _normalize_for_search(raw)
    if len(needle.replace(" ", "")) < 4:
        return False
    if needle and needle in haystack_norm:
        return True
    # Word-subset fallback: every significant token (len >= 3) present.
    tokens = [t for t in needle.split(" ") if len(t) >= 3]
    return bool(tokens) and all(t in haystack_norm for t in tokens)


# ── Stricter verification for LLM-authored "grounding quotes" ───────────────
# _value_in_raw_text's word-subset fallback exists to forgive a lightly
# REWORDED real value (dropped suffix, reordered tokens on an address/name).
# It is too permissive for a "grounding quote" the LLM writes freely (Figure
# 30 Question-code proof, see question_grounding): with only common short
# words required to each appear SOMEWHERE in the document independently, a
# model can pass a sentence it invented outright, so long as its individual
# words happen to be scattered across an unrelated business document (bug
# found 2026-07-12, live ACORD 126 test: fabricated "products under label of
# others: N" and "products of others sold: N" both survived on quotes whose
# words matched this way despite the document never mentioning either topic).
# A quote is proof only when the model's claimed excerpt actually occurs as
# a contiguous phrase, OR (found in live audit testing 2026-07-15: a genuine,
# clearly-documented "Yes" on ACORD 127's vehicle-maintenance question was
# wiped, along with its explanation, because the model's own paraphrase of the
# real sentence wasn't a byte-for-byte match) most of the quote's own words are
# covered by ONE specific real sentence in the document. The fallback is
# scoped per-SENTENCE and measured as COVERAGE OF THE QUOTE (not a symmetric
# Jaccard ratio against the whole sentence) - Guard 4's symmetric ratio under-
# counts here because a real sentence is often a long run-on containing lots
# of unrelated content around the part actually being quoted (e.g. a company-
# description clause bundled into the same sentence as the maintenance detail),
# which dilutes a symmetric ratio even for a faithful paraphrase.
#
# This does NOT reopen the 2026-07-12 bug this strictness was built to close:
# that bug worked by scattering common words ACROSS THE WHOLE DOCUMENT, in
# unrelated sentences, with no requirement that they co-occur anywhere. Here,
# the matching words must cluster inside ONE bounded, real sentence - a
# fabricated quote about an undiscussed topic would need to coincidentally
# share most of its words with some single real sentence to pass, which is a
# materially higher bar.
_QUOTE_COVERAGE_THRESHOLD = 0.75
_QUOTE_MIN_SHARED_TOKENS = 3


def _quote_covered_by_sentence(quote_tokens: frozenset, sentence_tokens: frozenset) -> bool:
    """True when `sentence_tokens` covers most of `quote_tokens` - directional
    (relative to the QUOTE only), unlike _is_near_duplicate_text's symmetric
    Jaccard ratio. See _quote_grounds_claim for why direction matters here."""
    if len(quote_tokens) < _QUOTE_MIN_SHARED_TOKENS:
        return False
    shared = quote_tokens & sentence_tokens
    if len(shared) < _QUOTE_MIN_SHARED_TOKENS:
        return False
    return (len(shared) / len(quote_tokens)) >= _QUOTE_COVERAGE_THRESHOLD


def _quote_grounds_claim(quote: str, haystack_norm: str, sentences: Optional[List[str]] = None) -> bool:
    raw = (quote or "").strip()
    if not raw:
        return False
    needle = _normalize_for_search(raw)
    if len(needle.replace(" ", "")) < 12:   # too short to be a real excerpt, not a value
        return False
    if needle in haystack_norm:
        return True
    if not sentences:
        return False
    q_tokens = _sim_tokens(raw)
    return any(_quote_covered_by_sentence(q_tokens, _sim_tokens(s)) for s in sentences)


# ── Explanation must be genuine per-question content, not reused boilerplate ─
# (found in audit, live test 2026-07-15): "operations_description" answers a
# BROAD question - "what does the business do" - and is core content meant for
# its own dedicated field(s) (see _EVIDENCE_REQUIRED_TOKENS's design note:
# "OperationsDescription... core required content, not a Yes/No
# justification"). The gap-fill LLM, unable to find real content for a
# specific compliance question (e.g. "do operations involve transporting
# hazardous material?"), grabbed this same generic sentence and reused it
# verbatim as the "explanation" - _present() saw it was genuinely IN the
# document and accepted it, with no check that it actually ANSWERS this
# question rather than a different one entirely.
#
# This is the single-occurrence counterpart to Guard 4's cross-field
# boilerplate-bleed detection (_enforce_post_fill_guards), which only fires
# when the SAME text repeats across 2+ MAPPED fields - it never saw this
# case because the sentence appeared in exactly one field on this form. This
# check compares against the FACT itself (a known, single, well-defined value
# with an established DIFFERENT purpose), so it is a value-IDENTITY check,
# not a keyword or topic-overlap heuristic - it does not revisit the standing
# rule against those (see _is_yes_no_field's design note; also
# evidence-gate-design memory: "do NOT reintroduce topic-keyword matching").
_BOILERPLATE_FACT_KEYS = ("operations_description",)


def _is_generic_boilerplate_reuse(
    field: Optional[str], text: str, facts: dict,
    reserved_values: Optional[Dict[str, str]] = None,
) -> bool:
    """True when `text` is the applicant's generic operations_description fact
    (verbatim or a near-duplicate paraphrase of it), UNLESS `field` is itself
    the field that legitimately holds that fact deterministically (mirrors
    Guard 4's own "legit_owner" exemption - the same fact is always allowed to
    sit in the ONE field it actually belongs to).

    `reserved_values` (optional): {other_field: its_value} for values ALREADY
    assigned as the specific, correct companion answer to a DIFFERENT question
    on this same form (see _NONADJACENT_QUESTION_COMPANIONS). A candidate
    explanation that CONTAINS one of these reserved values verbatim is the
    same document fact being double-counted for two different, unrelated
    questions - found in audit (live test 2026-07-15): ACORD 127's "leased to
    others" question came back "Yes", explained by the same vehicle-lease
    paragraph that correctly names the OTHER owner for the SEPARATE ownership
    question. A value-CONTAINMENT check against a KNOWN reserved value, not a
    keyword/topic heuristic."""
    if not field or not text or not str(text).strip():
        return False
    s = str(text).strip()
    s_lower = s.lower()
    s_tokens = _sim_tokens(s)
    for fact_key in _BOILERPLATE_FACT_KEYS:
        fact_val = _fv(facts, fact_key)
        if not fact_val or not str(fact_val).strip():
            continue
        f_tokens = _sim_tokens(str(fact_val))
        if s_lower != str(fact_val).strip().lower() and not _is_near_duplicate_text(s_tokens, f_tokens):
            continue
        det = _deterministic_map(field, facts)
        if isinstance(det, str) and det.strip().lower() == s_lower:
            return False   # this field IS the legitimate home for the fact
        return True
    for other_field, other_val in (reserved_values or {}).items():
        if other_field == field or not other_val:
            continue
        ov = str(other_val).strip()
        if len(ov) >= 8 and ov.lower() in s_lower:
            return True
    return False


# ── "Proof of No" verification (bug found 2026-07-12, live ACORD 125 test) ───
# _quote_grounds_claim confirms a grounding quote is genuinely PRESENT in the
# document, but not that it actually PROVES a NEGATIVE answer. The model,
# required to cite a quote for every Question-code answer, would grab any real
# sentence from the document (e.g. "Ironclad Fabrication & Welding LLC is a
# metal fabrication and welding contractor") as "proof" that the applicant is
# NOT a subsidiary / has NO fire-code violations / etc. A presence-only check
# kept the bogus "No" - the exact symptom the client reported (every General
# Information Y/N stamped "No" from a document that never addresses any of
# those questions). The distinguishing property of a genuine proof-of-No is
# simple and reliable: it EXPRESSES a negative (contains a negation cue). A
# positive descriptive sentence does not, so requiring one on the negative
# branch drops the bogus "No" while keeping a documented explicit "No" (e.g.
# "no prior cancellations"). Its failure mode is safe - a real "No" phrased
# without any negation word is rare and merely left blank for ARQ.
_NEGATION_CUE_RE = re.compile(
    r"\b(no|not|none|never|without|nor|neither|nil|cannot|lack|absence|"
    r"free|clear|clean)\b|n't\b|-free\b"
)


def _quote_expresses_negative(quote: str) -> bool:
    """True when the quote contains an explicit negation cue - the hallmark of
    a real 'the document says NO' statement, as opposed to a positive
    descriptive sentence the model grabbed at random."""
    return bool(_NEGATION_CUE_RE.search((quote or "").lower()))


def map_facts_to_form(
    facts: dict,
    schema: dict,
    form_id: str = "",
    raw_text: str = "",
    pre_filled_gpt: Optional[Dict[str, Any]] = None,
) -> Tuple[dict, dict]:
    """Two-stage form fill — cache-free.

    Pass 1 (deterministic, no LLM): schedule row routing, address decomposition,
    indicator derivation from flags, and direct fact-key mappings via
    `_ACORD_FIELD_RULES`. Non-fillable fields (signatures, premiums, carrier-
    computed codes) are skipped entirely.

    Pass 2 (LLM Call 2): every remaining field is sent to GPT together with the
    complete extracted raw document text and the form schema (field name +
    tooltip + type + required flag). Chunked automatically when the prompt
    exceeds the per-call character budget.

    Confidence labels feed the highlight layer:
      - "filled"           → no highlight (deterministic OR GPT verbatim from raw text)
      - "low_confidence"   → pink (GPT inferred — not copied verbatim from doc)
      - "missing_required" → yellow (required + empty + fillable)
    """
    if not schema:
        return {}, {}

    mapped     = {}
    unmatched  = {}
    confidence = {}

    # Fields filled by Pass 1 (deterministic rules) — always treated as "filled"
    # in the highlight pass. Schedule rows that resolved to N/A are also marked
    # here as authoritative blanks so they don't waste GPT prompt budget.
    _deterministic_filled: set = set()

    cnt_deterministic = 0
    cnt_nonfillable   = 0
    cnt_blank_sched   = 0

    for field in schema.keys():
        # Non-fillable fields (signatures, premiums, rates, underwriter codes)
        # are never sent to GPT. Leave them blank.
        if _is_nonfillable_field(field):
            mapped[field] = None
            _deterministic_filled.add(field)
            cnt_nonfillable += 1
            continue

        # Schedule fields: row index → list[idx] lookup against facts.
        # If the row is out of range, mark as authoritative blank (do NOT send
        # to GPT — we know the row doesn't exist).
        sched = _resolve_schedule_row(field, facts)
        if sched is not _SCHED_SKIP:
            if sched is not None and not _is_empty_llm_value(sched):
                mapped[field] = sched
                _deterministic_filled.add(field)
                cnt_deterministic += 1
            else:
                _deterministic_filled.add(field)
                cnt_blank_sched += 1
            continue

        # General deterministic path: _ACORD_FIELD_RULES, address decomposition,
        # indicator derivation.
        result = _deterministic_map(field, facts)
        if result == "UNMATCHED" or _is_empty_llm_value(result):
            # No rule matched, or rule produced empty value — let GPT try the
            # raw text. This keeps coverage on fields like _addr_line2 that
            # decompose to empty when the source address is a single line.
            unmatched[field] = schema[field]
        else:
            mapped[field] = result
            _deterministic_filled.add(field)
            cnt_deterministic += 1

    logger.info(
        "map_facts PIPELINE form=%s | schema=%d det=%d nonfill=%d blank_sched=%d gpt_fields=%d",
        form_id or "unknown",
        len(schema), cnt_deterministic, cnt_nonfillable, cnt_blank_sched, len(unmatched),
    )

    # ── Pass 1.5: alias-based deterministic stamping (opt-in) ───────────────
    # Fills fields Pass 1 missed by looking up each field's canonical name in
    # forms_aliases/<form_id>_alias.json and resolving it via the extraction-
    # key bridge in alias_stamper. Pure dictionary lookup — no LLM. When the
    # ENABLE_ALIAS_STAMPING flag is off, this block is a no-op and behavior
    # is identical to the prior pipeline.
    cnt_alias_filled = 0
    if unmatched and form_id:
        try:
            from config.settings import ENABLE_ALIAS_STAMPING
            if ENABLE_ALIAS_STAMPING:
                from services.alias_stamper import stamp_form_fields
                alias_filled = stamp_form_fields(form_id, facts, list(unmatched.keys()))
                for field, value in alias_filled.items():
                    if value is not None and not _is_empty_llm_value(value):
                        mapped[field] = value
                        _deterministic_filled.add(field)
                        unmatched.pop(field, None)
                        cnt_alias_filled += 1
                if cnt_alias_filled:
                    logger.info(
                        "map_facts ALIAS form=%s | alias_filled=%d remaining_gpt=%d",
                        form_id, cnt_alias_filled, len(unmatched),
                    )
        except Exception as exc:                # noqa: BLE001 — never block the pipeline
            logger.warning("map_facts ALIAS form=%s | error: %s", form_id, exc)

    gpt_raw_fields: set = set()
    gpt_filled_set: set = set()
    gpt_question_grounding: Dict[str, str] = {}

    if unmatched and pre_filled_gpt is not None:
        # Combined gap-fill path: consume pre-computed values from the cross-form
        # GPT pass instead of issuing a per-form call. The shared pass already
        # ran over the union of unmatched fields across all selected forms.
        gpt_values     = pre_filled_gpt.get("filled_values", {}) or {}
        gpt_raw_fields = pre_filled_gpt.get("raw_text_fields", set()) or set()
        gpt_question_grounding = pre_filled_gpt.get("question_grounding", {}) or {}
        gpt_filled_set = {f for f in unmatched if f in gpt_values}

        for field in unmatched:
            if field in gpt_values:
                mapped[field] = gpt_values[field]
            else:
                mapped.setdefault(field, None)

        logger.info(
            "map_facts COMBINED form=%s | pre_filled=%d/%d raw_text_sourced=%d",
            form_id or "unknown", len(gpt_filled_set), len(unmatched), len(gpt_raw_fields),
        )
    elif unmatched:
        logger.info(
            "map_facts GPT_ELIGIBLE form=%s | fields=%d raw_text_chars=%d",
            form_id or "unknown", len(unmatched), len(raw_text),
        )
        gpt_result     = _fill_unmatched_with_gpt(unmatched, facts, form_id, raw_text=raw_text)
        gpt_values     = gpt_result["filled_values"]
        gpt_raw_fields = gpt_result.get("raw_text_fields", set())
        gpt_question_grounding = gpt_result.get("question_grounding", {}) or {}
        gpt_filled_set = set(gpt_values.keys())

        for field in unmatched:
            if field in gpt_values:
                mapped[field] = gpt_values[field]
            else:
                mapped.setdefault(field, None)

        logger.info(
            "map_facts GPT_DONE form=%s | gpt_filled=%d/%d raw_text_sourced=%d",
            form_id or "unknown", len(gpt_filled_set), len(unmatched), len(gpt_raw_fields),
        )

    # ── Evidence-gated fill (opt-in, Figure 30 + Figure 33, generalized) ─────
    # A single, uniform rule for EVERY Yes/No field on EVERY ACORD form (client
    # requirement: "in all the forms... certain fields where Y/N/Yes/No to be
    # filled... only fill if we found concrete evidence") - not just the
    # compliance "_Question_<code>Code_" text-field family this gate started
    # with, and not just the high-impact auto/ownership checkbox subset added
    # afterward. See _is_yes_no_field for the full field-shape coverage: name
    # pattern, /Btn checkbox type, or tooltip Y/N convention. The gap-fill
    # model answers the field and cites its evidence (question_grounding); we
    # KEEP the answer only when that evidence is genuinely present in the
    # uploaded document. We do NOT second-guess the model's polarity or
    # re-derive the topic with keyword matching — earlier attempts at that
    # blanked legitimate documented answers ("not a subsidiary" -> wrongly
    # dropped) and manufactured false ones (a "no claims" explanation ->
    # wrongly flipped to "Yes"). The model reads the document and decides; our
    # only job is to catch a hallucination, i.e. an answer whose cited evidence
    # is not actually in the document.
    #
    #   * YES  - kept when its paired explanation OR its evidence quote is
    #            present in the document. A kept "Yes" is always given an
    #            explanation (backfilled from the evidence quote if the model
    #            left the box empty), so a broker never sees a bare "Yes".
    #   * NO   - kept when its evidence quote is present AND actually expresses a
    #            negative (so a random positive sentence grabbed from the
    #            document cannot masquerade as proof of a "No"). A "No" carries
    #            no explanation.
    #   * else - ungrounded answer -> blanked -> left for ARQ / manual entry.
    #
    # The gap-fill LLM's own "raw_text_sourced" self-report is NOT trusted (bug
    # 2026-07-11: a model that fabricates content can falsely flag it verbatim).
    # Deterministic (Pass 1 / alias) values never enter gpt_filled_set, so they
    # are untouched here - a checkbox Pass 1 (or alias stamping) already filled
    # from a real extracted fact is never re-litigated by this gate.
    _evidence_hay = _normalize_for_search(raw_text) if raw_text else ""
    # Per-sentence split for _quote_grounds_claim's paraphrase fallback - kept
    # as ORIGINAL (unnormalized) text so _sim_tokens can tokenize each sentence
    # independently. Split is intentionally simple (sentence-ending punctuation
    # or a newline); a slightly-too-long or too-short "sentence" only affects
    # the fallback's precision, never the exact-match path above it.
    _evidence_sentences = (
        [s for s in re.split(r"[.!?\n]+", raw_text) if s and s.strip()] if raw_text else []
    )
    try:
        from config.settings import ENABLE_EVIDENCE_GATED_FILL
    except Exception:                              # noqa: BLE001
        ENABLE_EVIDENCE_GATED_FILL = False
    if ENABLE_EVIDENCE_GATED_FILL:
        _gated = 0
        _q_to_exp = _question_explanation_pairs(schema)
        _exp_to_q = {exp: q for q, exp in _q_to_exp.items()}

        # Values already assigned as the specific companion answer for a
        # DIFFERENT question (see _NONADJACENT_QUESTION_COMPANIONS) - reserved
        # so they can't ALSO be accepted as generic "explanation" content for
        # an unrelated question (see _is_generic_boilerplate_reuse). Computed
        # once here since companion fields are plain gap-fill text, already
        # settled in `mapped` before this evidence-gate block runs.
        _reserved_companion_values: Dict[str, str] = {
            _c: mapped.get(_c)
            for _companions in _NONADJACENT_QUESTION_COMPANIONS.values()
            for _c in _companions
            if isinstance(mapped.get(_c), str) and mapped.get(_c).strip()
        }

        def _is_gated_field(f: str) -> bool:
            """Every ACORD Yes/No convention across all 17 forms - not just the
            compliance-question naming pattern (Figure 30) or the high-impact
            auto/ownership checkbox subset (Figure 33 audit finding: ACORD
            137/138's HNOA-equivalent checkboxes have no "_Question_Code_"
            name, so they were never reaching this gate). Delegates to
            _is_yes_no_field, which is a strict superset: every high-impact
            checkbox is a /Btn field, so nothing here regresses - it just also
            now covers every OTHER checkbox (sink hole, mine subsidence,
            building features, entity type, LOB selection, ...) and the plain
            Y/N text-field convention (e.g. ACORD 140/25's "…YesNoCode_")."""
            return _is_yes_no_field(f, schema)

        # A quote cited as "proof" for 3+ different questions is boilerplate
        # asserted as universal justification, not evidence of any one of them.
        _quote_use_count: Dict[str, int] = {}
        for _f in gpt_filled_set:
            if not _is_gated_field(_f):
                continue
            _q = gpt_question_grounding.get(_f)
            if _q and str(_q).strip():
                _qn = _normalize_for_search(str(_q))
                if _qn:
                    _quote_use_count[_qn] = _quote_use_count.get(_qn, 0) + 1

        def _present(text, field: Optional[str] = None) -> bool:
            """True when `text` is grounded in the uploaded document (independent
            search; punctuation/case/whitespace-insensitive with a word-subset
            fallback). With no document text to check against, nothing is
            grounded - self-report is deliberately not trusted.

            `field`: when given, also rejects `text` that is really the
            generic operations_description fact, or another question's own
            reserved companion value, reused as this field's explanation (see
            _is_generic_boilerplate_reuse) - presence alone proves the text is
            real, not that it answers THIS question."""
            if text is None or not str(text).strip():
                return False
            if not (bool(_evidence_hay) and _value_in_raw_text(str(text), _evidence_hay)):
                return False
            return not _is_generic_boilerplate_reuse(field, text, facts, _reserved_companion_values)

        def _evidence_supports(quote, *, negative: bool, allow_paraphrase: bool) -> bool:
            """The model's cited evidence really backs its answer: a contiguous
            phrase actually in the document, not reused as boilerplate, and -
            for a NEGATIVE answer - one that actually states a denial rather
            than an unrelated positive sentence.

            `allow_paraphrase`: the per-sentence paraphrase fallback (see
            _quote_grounds_claim) is enabled ONLY when this question has a real
            paired Explanation field in the schema - i.e. the model had a
            SECOND, independent place to demonstrate its answer and simply
            didn't use it, which is a materially lower-risk gap to forgive than
            a question with NO Explanation slot at all, where the quote is the
            ONLY signal that exists. Found in audit (live test 2026-07-15):
            without this restriction, a fabricated quote for an unpaired
            question (ACORD 127's ICC/PUC filings question, "no explanation
            needed" per the form itself) passed by reusing real words from an
            UNRELATED sentence elsewhere in the document - exactly the
            2026-07-12 bug class this file's strictness exists to prevent.
            Unpaired questions keep the original exact-match-only bar."""
            if not quote or not _evidence_hay or not _quote_grounds_claim(
                quote, _evidence_hay, _evidence_sentences if allow_paraphrase else None
            ):
                return False
            if _quote_use_count.get(_normalize_for_search(str(quote)), 0) > 2:
                return False
            if negative and not _quote_expresses_negative(quote):
                return False
            return True

        # ── Pass A: validate each answered Yes/No field (see _is_gated_field) ──
        for q_field in list(gpt_filled_set):
            if not _is_gated_field(q_field):
                continue
            v = str(mapped.get(q_field) or "").strip().lower()
            if not v:
                continue
            exp_field = _q_to_exp.get(q_field)
            exp_val   = mapped.get(exp_field) if exp_field else None
            quote     = gpt_question_grounding.get(q_field)

            if v in _AFFIRMATIVE_VALUES:
                exp_present   = _present(exp_val, exp_field)
                quote_present = _evidence_supports(quote, negative=False, allow_paraphrase=exp_field is not None)
                if not (exp_present or quote_present):
                    mapped[q_field] = None            # ungrounded "Yes" -> blank
                    if exp_field:
                        mapped[exp_field] = None
                    _gated += 1
                    continue
                # Keep the "Yes"; guarantee it carries a grounded explanation.
                if exp_field and not exp_present:
                    mapped[exp_field] = str(quote).strip() if quote_present else None
            elif v in _NEGATIVE_VALUES:
                if _evidence_supports(quote, negative=True, allow_paraphrase=exp_field is not None):
                    if exp_field:
                        mapped[exp_field] = None       # a "No" needs no explanation
                else:
                    mapped[q_field] = None             # ungrounded "No" -> blank
                    if exp_field:
                        mapped[exp_field] = None
                    _gated += 1
            else:
                mapped[q_field] = None                 # not a valid Y/N token
                if exp_field:
                    mapped[exp_field] = None
                _gated += 1

        # ── Pass C: promote via non-adjacent companion fields ─────────────────
        # Mirrors Pass B's "rescue a stranded grounded Yes" but for the
        # _NONADJACENT_QUESTION_COMPANIONS pattern instead of the adjacent-
        # Explanation pattern - covers BOTH (a) the model never attempted the
        # question's own Y/N at all, and (b) it did, but Pass A above gated it
        # to blank for lack of its own quote. Either way, a companion field
        # (e.g. the "Name of Other Owner" box) that is independently, genuinely
        # present in the document is real, on-topic proof the answer is "Y" -
        # never overrides an explicit, already-kept "Yes" or gate-approved "No".
        for _q_field, _companions in _NONADJACENT_QUESTION_COMPANIONS.items():
            if _q_field not in schema:
                continue
            current = str(mapped.get(_q_field) or "").strip().lower()
            if current in _AFFIRMATIVE_VALUES or current in _NEGATIVE_VALUES:
                continue
            for _companion in _companions:
                if _present(mapped.get(_companion), _companion):
                    mapped[_q_field] = "Y"
                    break

        # ── Pass B: narrative fields not owned by a kept "Yes" above ──────────
        # An "…Explanation"/"…OtherDescription"/"…ResolutionDescription" value
        # must be grounded in the document or it is AI-invented prose.
        #   * Unpaired (standalone "Other, please specify") -> keep iff present.
        #   * Paired to a Question code that is a kept "Yes" -> already handled.
        #   * Paired but the question is blank -> if the explanation is a real,
        #     document-present, AFFIRMATIVE statement, promote the question to
        #     "Y" so genuine grounded info is not stranded; if it expresses a
        #     negative (evidence for "No", not "Yes") or is ungrounded, blank it
        #     - never manufacture a "Yes" from a negative (the live ACORD 125
        #     "sexual-abuse claims = Y" bug).
        for exp_field in list(gpt_filled_set):
            if not _is_evidence_required_field(exp_field):
                continue
            val = mapped.get(exp_field)
            if val is None or not str(val).strip():
                continue
            q_field = _exp_to_q.get(exp_field)
            if q_field is None:
                if not _present(val, exp_field):
                    mapped[exp_field] = None
                    _gated += 1
                continue
            if str(mapped.get(q_field) or "").strip().lower() in _AFFIRMATIVE_VALUES:
                continue                               # owned by a kept "Yes"
            q_blank = not str(mapped.get(q_field) or "").strip()
            if q_blank and _present(val, exp_field) and not _quote_expresses_negative(val) \
                    and not _is_nonfillable_field(q_field):
                mapped[q_field] = "Y"                  # rescue a stranded grounded Yes
            else:
                mapped[exp_field] = None
                _gated += 1

        if _gated:
            logger.info("map_facts EVIDENCE_GATE form=%s | dropped_ungrounded=%d",
                        form_id or "unknown", _gated)

    # ── ACORD 101 overflow routing (opt-in, Figure 29) ───────────────────────
    # Oversized operations/classification narrative and accumulated remarks are
    # routed IN FULL to this form's Additional Remarks rows. Only ACORD 101 owns
    # these fields, so this is self-contained and lossless for every other form.
    if form_id == "ACORD_101":
        try:
            from config.settings import ENABLE_ACORD101_OVERFLOW
        except Exception:                          # noqa: BLE001
            ENABLE_ACORD101_OVERFLOW = False
        if ENABLE_ACORD101_OVERFLOW:
            _apply_acord101_overflow(mapped, schema, facts, _deterministic_filled)

    # ── Post-fill deterministic guards ───────────────────────────────────────
    # Enforce invariants the gap-fill prompt can only request, not guarantee:
    # legal-entity mutual exclusion and repeating-row de-duplication. Runs on the
    # merged result so it corrects values from any source (Pass 1, alias, GPT).
    _enforce_post_fill_guards(mapped, schema, facts)

    # ── Raw-text verification (Figure 26 trust check — no LLM) ────────────────
    # Confirm every value the AI filled actually appears in the uploaded document
    # text. Runs on the PRE-canonicalization value so our own display formatting
    # can never break the match. A value found in the documents is trusted (→
    # "ai_verified", painted pink); a value the AI produced that is NOT present —
    # a guess, or a "copied" claim we cannot locate — stays "low_confidence"
    # (painted orange) for review. Deterministic (fact) and client values are
    # never checked. Yes/No answers are skipped inside _value_in_raw_text.
    _ai_verified_fields: set = set()
    if raw_text and gpt_filled_set:
        _hay = _normalize_for_search(raw_text)
        for _f in gpt_filled_set:
            _v = mapped.get(_f)
            if _v is not None and _value_in_raw_text(str(_v), _hay):
                _ai_verified_fields.add(_f)

    # ── Owner/insured field contamination override (Figure 33 client feedback)
    # An owner/insured NAME field must never be silently trusted just because
    # it was filled by a deterministic rule, or because its value passed the
    # generic raw-text check above - neither proves the value belongs in THIS
    # field's ROLE. Values that look like carrier/policy data in an owner/
    # insured slot are forced to low_confidence (reviewable, never blanked -
    # values are never deleted here, only their trust label changes).
    #
    # Checks EVERY owner/insured field with a value, regardless of fill source
    # (deterministic rule, alias stamp, or GPT). Originally scoped to GPT-
    # filled fields only, on the theory that a deterministic rule is "trusted
    # by construction" - reconsidered after a live test showed the gap
    # concretely: CertificateHolder_FullName has its OWN deterministic rule
    # (-> the "certificate_holder" fact, a different key from "carrier_name"),
    # so when a document's extracted certificate_holder happens to equal its
    # carrier, the field was filled deterministically and stayed fully
    # trusted (no highlight) - correctly caught by the separate post-
    # generation warning either way, but confusingly inconsistent with the
    # orange highlight a GPT-filled equivalent would have gotten. Checking
    # every source uniformly removes that inconsistency; the check itself
    # (is_value_contaminated) is unchanged.
    #
    # No underwriting_confirmations here (not available at this call depth) -
    # uses whichever carrier/applicant facts are already in `facts`. Never
    # raises: a detector fault must never break generation.
    _owner_field_contamination: set = set()
    try:
        from services.field_mapping_integrity import is_insured_owner_field, is_value_contaminated
        for _f, _v in mapped.items():
            if _v is None or not is_insured_owner_field(_f):
                continue
            if is_value_contaminated(_f, _v, facts):
                _owner_field_contamination.add(_f)
    except Exception as _cont_ex:
        logger.warning("owner-field contamination check skipped (form=%s): %s", form_id, _cont_ex)

    # ── Display canonicalization (Beta feedback: stamp clean, standardized
    # values, not raw OCR strings) ───────────────────────────────────────────
    # NON-destructive: standardizes date / currency / address / name / state
    # formatting while PRESERVING all content (entity suffix, unit number,
    # ZIP+4). The raw value stays in the fact envelope for verification. This is
    # distinct from services/normalization.py, whose stripped comparison key must
    # never be stamped. Gated OFF by default so behavior is identical to the
    # prior pipeline unless ENABLE_DISPLAY_CANONICALIZATION is set.
    try:
        from config.settings import ENABLE_DISPLAY_CANONICALIZATION
    except Exception:
        ENABLE_DISPLAY_CANONICALIZATION = False
    if ENABLE_DISPLAY_CANONICALIZATION:
        try:
            from services.display_canonicalizer import canonicalize_for_field
            for _field in list(mapped.keys()):
                _val = mapped.get(_field)
                if _val is None:
                    continue
                _clean = canonicalize_for_field(_field, _val)
                if _clean is not None and _clean != _val:
                    mapped[_field] = _clean
        except Exception as _cex:
            logger.warning("display canonicalization skipped (form=%s): %s", form_id, _cex)

    # ── Confidence / highlight assignment ────────────────────────────────────
    # Deterministic (Pass 1 / alias, from facts) values are trusted with no
    # highlight. AI-filled values are split by the raw-text verification above:
    #   found in the documents   → "ai_verified"  → pink  (AI-OK)
    #   NOT found (guess, or a
    #   "copied" claim we can't
    #   locate)                  → "low_confidence" → orange (verify)
    # An owner/insured field flagged as contamination-shaped (checked just
    # above) always forces low_confidence, even if it passed the generic
    # raw-text check - a carrier name really is present in the document, just
    # never in this field's role (Figure 33).
    for field, meta in schema.items():
        val       = mapped.get(field)
        has_value = val is not None and str(val).strip() not in ("", "null", "None")
        is_req    = meta.get("required", False) if isinstance(meta, dict) else False

        if has_value:
            if field in _owner_field_contamination:
                confidence[field] = "low_confidence"
            elif field in _deterministic_filled:
                confidence[field] = "filled"
            elif field in _ai_verified_fields:
                confidence[field] = "ai_verified"
            else:
                confidence[field] = "low_confidence"
        elif is_req and not _is_nonfillable_field(field):
            # Paint yellow only for genuinely fillable required fields.
            confidence[field] = "missing_required"
        else:
            confidence[field] = "low_confidence"

    confidence = apply_acord125_missing_field_highlights(form_id, facts, mapped, confidence)
    confidence = apply_acord126_missing_field_highlights(form_id, facts, mapped, confidence)

    # Fill-rate denominator excludes non-fillable fields (signatures, premiums,
    # rate codes) so the reported coverage is meaningful.
    fillable_count = sum(1 for f in schema if not _is_nonfillable_field(f))
    total_filled   = sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("", "null", "None"))
    logger.info(f"Mapped {total_filled}/{fillable_count} fields (form_id={form_id or 'unknown'})")

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
    existing_pdf_bytes: bytes = None,
) -> bytes:
    """Fill the PDF then paint the signature image directly into the page content
    stream at every signature-field rectangle.

    Painting into the content stream (not just adding an annotation) ensures the
    signature renders in every PDF viewer, including print dialogs and flattened
    exports that ignore annotations.
    """
    import base64
    # Use pre-filled bytes when available so no field values are lost on re-generation
    filled_bytes = existing_pdf_bytes if existing_pdf_bytes is not None else fill_pdf(template_path, field_data, confidence)
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
