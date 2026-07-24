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
    from openai import AsyncOpenAI as _AsyncOpenAI, OpenAI as _SyncOpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    logger.warning("openai package not installed — GPT form fill pass disabled")

_openai_form_fill_client = None
_openai_form_fill_client_sync = None


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


def _get_openai_form_fill_client_sync():
    """SYNCHRONOUS form-fill client, for the ThreadPoolExecutor gap-fill path.

    Why a separate client (deadlock fix): an `httpx.AsyncClient` binds its
    connection pool AND its timeout timers to the event loop that created them.
    The gap-fill pass runs its calls on worker threads that each did
    `asyncio.run()` — a NEW event loop per call — while sharing the single
    module-level AsyncOpenAI client above. When a worker picked up a pooled
    connection created on another thread's now-closed loop, the await parked on
    a dead loop: it never completed, and the timeout never fired because that
    timer lived on the dead loop too. No exception, no log line — the thread
    simply blocked forever, and `concurrent.futures.as_completed()` waited on it
    forever, hanging the whole request. (Observed live: 4 compliance batches
    dispatched, 3 returned HTTP 200, the 4th vanished and all logging stopped.)

    `httpx.Client` is thread-safe and loop-free, so one shared sync client is
    both correct and connection-pool efficient across all worker threads.
    """
    global _openai_form_fill_client_sync
    if _openai_form_fill_client_sync is None:
        if not _HAS_OPENAI:
            raise RuntimeError("openai package not installed — install it with: pip install openai")
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — GPT form-fill pass unavailable. "
                "Set OPENAI_API_KEY in your .env file."
            )
        _openai_form_fill_client_sync = _SyncOpenAI(
            api_key=api_key,
            http_client=httpx.Client(
                timeout=float(os.getenv("LLM_REQUEST_TIMEOUT", "120")),
            ),
        )
    return _openai_form_fill_client_sync

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
    # NOTE (2026-07-21): the four `Vehicle_*Identifier`/`*Name`/`BodyCode` entries
    # below are the names ACORD 127 ACTUALLY uses. Audited against all 17 real
    # schemas: of the vehicle entries only `Vehicle_ModelYear` and
    # `Vehicle_GrossVehicleWeight` matched a real field, so VIN / make / model /
    # body type were extracted by `extraction_service` into `auto_vin_schedule`
    # and then had nowhere to land - the identity columns of the vehicle schedule
    # could never be stamped, and those boxes fell through to a gap-fill guess.
    # The generic aliases are retained (harmless, and other ACORD editions may
    # use them); these additions are what make the binding live.
    "Vehicle_ModelYear":             _ScheduleDef("auto_vin_schedule", "year"),
    "Vehicle_Year":                  _ScheduleDef("auto_vin_schedule", "year"),
    "Vehicle_ManufacturersName":     _ScheduleDef("auto_vin_schedule", "make"),
    "Vehicle_Make":                  _ScheduleDef("auto_vin_schedule", "make"),
    "Vehicle_ModelName":             _ScheduleDef("auto_vin_schedule", "model"),
    "Vehicle_Model":                 _ScheduleDef("auto_vin_schedule", "model"),
    "Vehicle_VINIdentifier":         _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_VINNumber":             _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_VIN":                   _ScheduleDef("auto_vin_schedule", "vin"),
    "Vehicle_BodyCode":              _ScheduleDef("auto_vin_schedule", "body_type"),
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


# `valuation_method` is normalized to "RCV"/"ACV" at extraction time (the
# common industry shorthand), but the real ACORD 140/141 ValuationCode
# field's own tooltip documents a single-letter code convention (A/R/V/M).
# See the call site (_deterministic_map) for the full story.
_VALUATION_METHOD_TO_ACORD_CODE = {"rcv": "R", "acv": "A"}

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
    # Most-specific FIRST: UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier
    # (ACORD 131's underlying-schedule GL row - tooltip: "The policy number of
    # the underlying general liability policy") is a substring match for the
    # generic Policy_GeneralLiability_PolicyNumberIdentifier rule right below,
    # which silently stamped the UMBRELLA'S OWN policy number into the
    # underlying GL row on a real ACORD 131 (confirmed live). No per-line
    # underlying-GL-policy-number fact exists in this codebase, so this maps
    # to None -> gap-fill, which already correctly reads the real underlying
    # GL policy number from raw text (same mechanism already proven for
    # UnderlyingPolicy_GeneralLiability_PolicyEffectiveDate_A).
    ("UnderlyingPolicy_GeneralLiability_PolicyNumberIdentifier", None),
    ("Policy_GeneralLiability_PolicyNumberIdentifier",     "policy_number"),
    ("Policy_GeneralLiability_EffectiveDate",              "effective_date"),
    ("Policy_GeneralLiability_ExpirationDate",             "expiration_date"),
    ("Policy_AutomobileLiability_PolicyNumberIdentifier",  "policy_number"),
    ("Policy_AutomobileLiability_EffectiveDate",           "effective_date"),
    ("Policy_AutomobileLiability_ExpirationDate",          "expiration_date"),
    # ACORD 25's certificate header has no per-line "excess policy number"
    # fact - only the generic policy_number (the GL/primary row's own
    # number, per every other rule in this block). Stamping that same number
    # onto the Excess row silently duplicated the GL policy number there on a
    # real certificate (confirmed live: same 'GL-4471029-25' on both rows).
    # Maps to None -> gap-fill, which already correctly distinguishes the
    # excess/umbrella coverage line's own values from the GL row's elsewhere
    # on this exact form (see Policy_ExcessLiability_EffectiveDate_A's
    # dedicated override above, and the underlying-schedule rows on 131).
    ("Policy_ExcessLiability_PolicyNumberIdentifier",      None),
    ("Policy_ExcessLiability_EffectiveDate",               "effective_date"),
    ("Policy_ExcessLiability_ExpirationDate",              "expiration_date"),
    # NOT a bare "Policy_WorkersCompensation" prefix: that substring also
    # matched Policy_WorkersCompensationAndEmployersLiability_EffectiveDate_A /
    # _ExpirationDate_A (ACORD 25), silently stamping the GL policy NUMBER
    # STRING into both WC DATE fields on the real certificate (confirmed live -
    # "GL-4471029-25" printed where a date belongs). The exact, fully-qualified
    # name below matches ONLY the real policy-number field; the WC date fields
    # now correctly fall through to UNMATCHED -> gap-fill, which already reads
    # them correctly from raw text (same mechanism proven for the underlying
    # GL/Auto/EL dates on ACORD 131 - see UnderlyingPolicy_*_PolicyEffectiveDate).
    ("Policy_WorkersCompensationAndEmployersLiability_PolicyNumberIdentifier", "policy_number"),
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
    # NOTE: the bare "EachOccurrence" catch-all (for ACORD 160's
    # GeneralLiability_BodilyInjury_EachOccurrenceLimitAmount_A, which has no
    # more-specific rule) is placed AFTER the umbrella section below, not
    # here. Listed here it silently beat the umbrella section's own more-
    # specific ExcessUmbrella_Umbrella_EachOccurrenceAmount rule (200 lines
    # down) for any field containing "EachOccurrence" ANYWHERE in its name -
    # including the umbrella's own each-occurrence limit field, which
    # confirmed-live stamped the GL each-occurrence limit onto ACORD 131's
    # umbrella limit field instead of the umbrella's real, distinct amount.
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
    # Bare "EachOccurrence" catch-all, relocated from the GL section above (see
    # the NOTE there): only needed for ACORD 160's GeneralLiability_
    # BodilyInjury_EachOccurrenceLimitAmount_A, which has no more-specific GL
    # rule. Placed AFTER every umbrella-specific rule so the umbrella's own
    # each-occurrence field (immediately above) is never shadowed by this
    # generic substring.
    ("EachOccurrence",                                     "gl_each_occurrence"),
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
            # Store the FULL tooltip (/TU). This was previously truncated to 80
            # chars, which — for Yes/No "Question" fields whose /TU is
            # "Enter Y for a Yes response. Input N for No response. The response
            # to the question, "<actual question>"?" — cut off BEFORE the actual
            # question text ever began (~85 chars of boilerplate precede it). The
            # gap-fill LLM was therefore answering compliance questions it could
            # not read (root cause of ACORD 126/140/25 coming back blank/wrong).
            # The /TU is the authoritative question text from the ACORD template
            # itself; capped only to guard against a pathological value.
            tu   = str(item.get("/TU", ""))[:_SCHEMA_TOOLTIP_MAX]
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
                elif conf == "missing_required_gate":
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


def apply_draft_watermark(pdf_bytes: bytes, label: str = "DRAFT - INCOMPLETE") -> bytes:
    """Stamp a diagonal, gray watermark across every page of a generated PDF.

    Used EXCLUSIVELY by the download-gate override path (routes/download_routes.py):
    when a producer explicitly chooses "Generate Draft Anyway" despite unresolved
    placeholder values or required COPE fields (services.field_qa.check_hard_block),
    the resulting PDF must never look identical to a clean, complete download - this
    is what makes that visually unmistakable. A clean download (the gate found
    nothing to block) never calls this function and is byte-for-byte unaffected.

    Uses the same raw pikepdf content-stream-injection technique as
    _draw_highlight_rects (this codebase's established pattern for PDF overlays)
    rather than introducing a new PDF-manipulation dependency (e.g. reportlab
    page-merging, not used anywhere else in this file). Standard Helvetica-Bold
    (one of the 14 base PDF fonts) needs no embedding, so this adds no new binary
    asset. The overlay is appended AFTER each page's existing content stream so it
    paints on top - visible over the stamped form content, not hidden behind it.
    """
    try:
        pdf = pikepdf.open(io.BytesIO(pdf_bytes))
        font_dict = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name("/Helvetica-Bold"),
            Encoding=pikepdf.Name.WinAnsiEncoding,
        ))
        safe_label = label.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        font_size = 46
        # Rough average glyph width for Helvetica-Bold uppercase text - used only to
        # approximately horizontally center the label, not a real font-metrics lookup.
        approx_half_width = len(label) * font_size * 0.31
        cos45 = sin45 = 0.70710678

        for page in pdf.pages:
            mb = page.mediabox
            width  = float(mb[2]) - float(mb[0])
            height = float(mb[3]) - float(mb[1])
            cx, cy = width / 2.0, height / 2.0

            resources = page.get("/Resources")
            if resources is None:
                resources = pikepdf.Dictionary()
                page["/Resources"] = resources
            fonts = resources.get("/Font")
            if fonts is None:
                fonts = pikepdf.Dictionary()
                resources["/Font"] = fonts
            fonts["/PrimbleDraftWM"] = font_dict

            lines = [
                "q",
                "0.55 0.55 0.55 rg",
                f"1 0 0 1 {cx:.2f} {cy:.2f} cm",
                f"{cos45:.6f} {sin45:.6f} {-sin45:.6f} {cos45:.6f} 0 0 cm",
                "BT",
                f"/PrimbleDraftWM {font_size} Tf",
                f"{-approx_half_width:.2f} 0 Td",
                f"({safe_label}) Tj",
                "ET",
                "Q",
            ]
            overlay_bytes = ("\n".join(lines) + "\n").encode("latin-1")
            overlay_stream = pikepdf.Stream(pdf, overlay_bytes)
            existing = page.get("/Contents")
            if existing is None:
                page["/Contents"] = overlay_stream
            elif isinstance(existing, pikepdf.Array):
                page["/Contents"] = pikepdf.Array(list(existing) + [overlay_stream])
            else:
                page["/Contents"] = pikepdf.Array([existing, overlay_stream])

        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        buf.seek(0)
        return buf.getvalue()
    except Exception as ex:
        logger.error(f"apply_draft_watermark error: {ex}")
        return pdf_bytes


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
# Guard 2 (repeating-row dedup) exemption - deliberately narrower than
# _SUBJECT_OF_INSURANCE_RE above: SubjectOfInsuranceCode legitimately repeats
# ("Building" is a perfectly normal subject at 2 different locations), but
# LimitAmount duplicating row A's EXACT dollar figure is a real bug, not a
# coincidence - a live test confirmed this exact failure: a 2nd location's
# row came back with row A's amount duplicated into it, and Guard 2 never
# caught it because LimitAmount was exempted here right alongside
# SubjectOfInsuranceCode. LimitAmount now goes through the same row-A
# comparison as any other free-text value field.
_SUBJECT_OF_INSURANCE_CODE_ONLY_RE = re.compile(
    r"^CommercialProperty_Premises_SubjectOfInsuranceCode_([A-Z])$"
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


def _resolve_via_field_rules(field_name: str, facts: dict):
    """The plain `_ACORD_FIELD_RULES` substring lookup, factored out so it can
    also serve as a fallback for row A of a schedule-shadowed field (see the
    call site in `_deterministic_map`) without duplicating this logic."""
    for pattern, fact_key in _ACORD_FIELD_RULES:
        if pattern in field_name:
            if fact_key is None:
                return None
            if fact_key.startswith("_"):
                if fact_key.startswith("_addr_") and not field_name.startswith("NamedInsured_"):
                    return "UNMATCHED"
                return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
            val = _fv(facts, fact_key)
            if fact_key == "valuation_method" and isinstance(val, str):
                val = _VALUATION_METHOD_TO_ACORD_CODE.get(val.strip().lower(), val)
            if isinstance(val, list):
                if "Indicator" in field_name and isinstance(val, list):
                    return _derive_indicator(field_name, facts)
                return str(val[0]) if val else None
            return str(val) if val is not None else None
    return None


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
        # A handful of `_ACORD_FIELD_RULES` entries share their EXACT base name
        # with a `_SCHEDULE_REGISTRY` entry (e.g. BusinessInformation_
        # FullTimeEmployeeCount is both "the num_employees rule" AND "column
        # full_time_employees of the property_locations schedule") - swept
        # across the full registry (2026-07): 4 such pairs exist. The schedule
        # check runs first and unconditionally wins, which is correct WHEN a
        # genuine structured breakdown exists (a real per-location employee
        # split, a real per-line prior-coverage schedule) - but when NO such
        # breakdown was ever captured (the common case: a document just states
        # one overall total), it silently shadows the simple scalar fact
        # forever, even after a client explicitly confirms it via ARQ.
        #
        # Live finding: a client answered "How many people does your business
        # employ?" - `facts['num_employees']` updated and SQS moved, but the
        # actual PDF box never changed, because this exact interception
        # returned None (property_locations has no entries) before the plain
        # num_employees rule was ever reached.
        #
        # Scoped narrowly to row A only: `_resolve_schedule_row` returns None
        # at row A (list index 0) if and only if the schedule's list is
        # COMPLETELY EMPTY - never as "too short for this particular row",
        # since index 0 always exists whenever the list has at least one real
        # entry. So this fallback can never override or hide genuine partial
        # schedule data, and rows B/C/D+ are untouched - a document with real
        # per-location or per-line data still uses it, exactly as before.
        if sched is None and field_name.endswith("_A"):
            fallback = _resolve_via_field_rules(field_name, facts)
            if fallback is not None and fallback != "UNMATCHED":
                return fallback
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
            if fact_key == "valuation_method" and isinstance(val, str):
                # `valuation_method` is normalized to the 3-letter industry term
                # ("RCV"/"ACV") at extraction time, but the real ACORD 140/141
                # ValuationCode field documents a SINGLE-LETTER code in its own
                # tooltip (A/R/V/M - Actual Cash Value/Replacement Cost/Agreed
                # Amount/Market Value). A live test surfaced the mismatch this
                # caused directly: the deterministically-filled row showed "RCV"
                # while a gap-filled row (which reads the tooltip itself) showed
                # "R" for the exact same concept - same field, two different
                # conventions. Translate to the schema's own convention here so
                # every row is consistent regardless of which pass filled it.
                val = _VALUATION_METHOD_TO_ACORD_CODE.get(val.strip().lower(), val)
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


# ACORD 140 Premises/Subject-of-Insurance schedule row letters. Note the raw
# schema skips "F" (verified against the real schema - not a bug here).
_ACORD140_PREMISES_ROWS = ("A", "B", "C", "D", "E", "G", "H", "I", "J", "K")

# Per-building COPE characteristics only exist for 2 building slots (A/B) in
# the raw schema, independent of the 10-row premises/value schedule above.
_ACORD140_BUILDING_ROWS = ("A", "B")

# Building-characteristic fields (Construction, Occupancy, Protection,
# Exposure) the client named explicitly (Figure 35): once a building slot has
# been started (see trigger below), these become required for THAT slot.
_ACORD140_BUILDING_CHAR_FIELDS = (
    "Construction_ConstructionCode",     # construction type
    "CommercialStructure_BuiltYear",     # year built
    "Construction_RoofMaterialCode",     # roof
    "BuildingFireProtection_ProtectionClassCode",  # protection class
)


def apply_acord140_missing_field_highlights(
    form_id: str,
    facts: dict,
    field_state: dict,
    confidence: dict,
) -> dict:
    """
    ACORD 140-only visual completeness layer for the COPE (Construction,
    Occupancy, Protection, Exposure) data the client flagged as silently
    incomplete (Figure 35): a premises row can show a placeholder-riddled or
    half-filled schedule - e.g. a Subject of Insurance row with an amount but
    no construction/year/roof/protection data for that building - and nothing
    previously marked the gap on the rendered PDF, because every ACORD 140
    field is "required": false in the raw schema (verified: 0 of 356 fields
    marked required there).

    Mirrors apply_acord125/126_missing_field_highlights' "started row" pattern
    exactly (a row/slot with ANY data in it makes its sibling fields required
    too), but writes a SEPARATE confidence label ("missing_required_gate"
    rather than "missing_required") so this is purely ADDITIVE: it cannot
    change behavior for any field that isn't part of the two groups below, and
    it never touches the pre-existing 125/126 highlight behavior.

    Two independent row groups, each gated on its own "started" signal:
      1. Premises/value schedule (10 slots): once a row has a Subject of
         Insurance code or a Limit Amount, that row's Limit Amount is
         required - this is the "building value / BPP value" the client
         named, keyed by whichever subject-of-insurance the row represents.
      2. Building characteristics (2 slots): once a building's premises row
         has started, its Construction Code, Built Year, Roof Material Code,
         and Protection Class Code become required.

    Deliberately NOT covered here (see CLAUDE.md audit notes): "occupancy"
    has no dedicated fillable field on the ACORD 140 schema itself (it lives
    on ACORD 125's operations description), and "business income" is only a
    Yes/No attachment indicator on this form - forcing a Yes/No box to a
    required value would fight the established evidence-gate "blank over
    wrong" rule for checkbox fields elsewhere in this codebase. Both remain
    real requirements, just satisfied by other existing mechanisms rather than
    fabricated here.
    """
    if form_id != "ACORD_140":
        return confidence

    def _mark_required(field: str) -> None:
        if field not in field_state and field not in confidence:
            return  # not part of this rendered schema instance
        if not _acord125_has_value(field_state, field):
            confidence[field] = "missing_required_gate"
        elif confidence.get(field) == "missing_required_gate":
            confidence[field] = "filled" if _acord125_has_value(field_state, field) else "low_confidence"

    for row in _ACORD140_PREMISES_ROWS:
        code_field   = f"CommercialProperty_Premises_SubjectOfInsuranceCode_{row}"
        amount_field = f"CommercialProperty_Premises_LimitAmount_{row}"
        if not (_acord125_has_value(field_state, code_field) or _acord125_has_value(field_state, amount_field)):
            continue  # row never started - an empty schedule row is not a gap
        _mark_required(amount_field)

    # Confirmed via a live multi-location test (2026-07-17): the Premises/value
    # schedule's row lettering and the building-characteristics fields' row
    # lettering are NOT the same axis. CommercialStructure_BuiltYear_A/B,
    # Construction_ConstructionCode_A/B etc. use SIMPLE addressing (_A =
    # building/premises 1, _B = building/premises 2 - confirmed against the
    # real schema's own CommercialStructure_PhysicalAddress_LineOne_A/B). But
    # the Premises schedule's SubjectOfInsuranceCode/LimitAmount fields use a
    # DIFFERENT 6-letter-block-per-premises scheme (see
    # _resolve_subject_of_insurance_row) - so a 2nd location's dollar amount
    # can legitimately land in row B, G, or anywhere else the gap-fill model
    # placed it, NOT necessarily row B. Gating building B's COPE requirement
    # on "did premises row B start" alone was confirmed WRONG: it only
    # happened to work when the 2nd location's data landed in row B by
    # chance, and silently missed the gap whenever it landed elsewhere.
    #
    # Fix: trigger primarily on the actual fact source - `property_locations`
    # genuinely having a 2nd (i.e. Nth) entry means building B/C/... COPE data
    # is required, independent of where the Premises schedule happened to put
    # the dollar amount. The premises-row check is kept as an OR fallback so a
    # session whose facts lack a clean property_locations list (but whose
    # schedule genuinely got real per-row data some other way) is still
    # covered - this only ever ADDS trigger coverage, never removes it.
    _locations = facts.get("property_locations") if isinstance(facts, dict) else None
    _location_count = len(_locations) if isinstance(_locations, list) else 0

    for _idx, row in enumerate(_ACORD140_BUILDING_ROWS):
        code_field   = f"CommercialProperty_Premises_SubjectOfInsuranceCode_{row}"
        amount_field = f"CommercialProperty_Premises_LimitAmount_{row}"
        premises_row_started = (
            _acord125_has_value(field_state, code_field) or _acord125_has_value(field_state, amount_field)
        )
        building_exists_in_facts = _idx < _location_count
        if not (premises_row_started or building_exists_in_facts):
            continue  # neither signal says this building/premises exists - not a gap
        for base in _ACORD140_BUILDING_CHAR_FIELDS:
            _mark_required(f"{base}_{row}")

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

# Tooltip (/TU) length caps. `_SCHEMA_TOOLTIP_MAX` bounds what schema extraction
# stores per field (the authoritative ACORD template question text — the real
# ACORD /TU values top out ~800 chars). `_PROMPT_TOOLTIP_MAX` bounds what the
# gap-fill prompt shows the model per field; it MUST be large enough to include
# the full compliance-question text that follows the ~85-char "Enter Y for a
# Yes response..." boilerplate, or the model answers questions it cannot read.
# Both replace a former hard 80-char cut that severed every question mid-preamble.
_SCHEMA_TOOLTIP_MAX = int(os.getenv("SCHEMA_TOOLTIP_MAX", "1000"))
_PROMPT_TOOLTIP_MAX = int(os.getenv("PROMPT_TOOLTIP_MAX", "500"))

# Fields per gap-fill LLM call. A single call carrying 200+ heterogeneous fields
# makes the model answer only a fraction of them (measured ~27% at 205 fields) —
# it silently drops questions it CAN answer from the document. Sub-batching the
# field list into focused groups of this size restores near-full completion so
# ALL data present in the dec pages actually lands on the form. `_FIELD_BATCH_POOL`
# bounds how many sub-batches run concurrently (the llm_limiter adaptive semaphore
# is the final TPM backstop).
_FIELD_FILL_BATCH = int(os.getenv("FIELD_FILL_BATCH", "40"))
_FIELD_BATCH_POOL = int(os.getenv("FIELD_BATCH_POOL", "4"))

# Yes/No compliance questions per focused LLM call (see the dedicated compliance
# pass). Small groups keep per-question diligence high — one call with all ~40
# questions makes the model rush and borrow a plausible sentence for questions it
# should omit; a handful per call it reads each carefully against the document.
_COMPLIANCE_BATCH = int(os.getenv("COMPLIANCE_BATCH", "10"))

# Retry backoff for a failed gap-fill call. The dominant failure is an OpenAI
# TPM (tokens-per-minute) 429 — the whole pipeline ships the document on every
# call, so a multi-form run can drain a 200k TPM budget. A TPM bucket refills
# over tens of seconds, so the old 1/2/4s backoff just re-hit the same 429 and
# burned all three attempts, after which the call returned {} and its fields
# went silently BLANK.
_LLM_RETRY_BACKOFF_BASE_S = float(os.getenv("LLM_RETRY_BACKOFF_BASE_S", "5"))
_LLM_RETRY_BACKOFF_MAX_S  = float(os.getenv("LLM_RETRY_BACKOFF_MAX_S", "45"))

# Evidence gate: max distinct Yes/No fields that may cite the same (near-duplicate)
# grounding quote before ALL of them are treated as boilerplate reuse and blanked.
# This existed to catch a false-"No" flood the model produced when it was BLIND to
# the question text (an 80-char tooltip truncation, fixed 2026-07-16, that severed
# every compliance question — see _SCHEMA_TOOLTIP_MAX). With the question text now
# actually reaching the model, moderate legitimate reuse is EXPECTED and correct:
# a single broad negation ("owns no boats, docks or floating structures; all
# operations are land-based") genuinely answers several distinct schedule/exposure
# questions "No", and for a narrow-operations applicant most facility/exposure
# questions truly ARE "No". A low cap here was blanking those correct answers
# (field-batching compounds it: related questions land in different sub-batches so
# the model cannot self-dedup its citations across them). Kept only as a
# defence-in-depth backstop against a pathological one-quote-for-everything
# regression, so the default is generous.
_EVIDENCE_QUOTE_REUSE_MAX = int(os.getenv("EVIDENCE_QUOTE_REUSE_MAX", "12"))

# Tighter reuse cap for AFFIRMATIVE ("Yes") answers. A genuine "Yes" exposure has
# its OWN specific description in the document (install work, a warranty clause, a
# hazmat-disposal sentence — each unique). A "Yes" whose grounding quote is SHARED
# with another question is almost always a borrow: the model reused a sentence
# meant for a different question (e.g. citing "manufactures to customer
# specifications" as proof of "foreign products used as components", or a
# subcontractor-COI sentence as proof of "vendors coverage required"). Those
# borrowed quotes are typically shared with a NEGATIVE answer, so a Yes-only cap
# blanks the false "Yes" without touching the legitimate "No" that shares the
# sentence. Default 1 = a "Yes" must cite evidence unique to it.
_EVIDENCE_YES_QUOTE_REUSE_MAX = int(os.getenv("EVIDENCE_YES_QUOTE_REUSE_MAX", "1"))

# ── Dedicated compliance Yes/No question pass ────────────────────────────────
# The general field-fill prompt buries ~40 Yes/No underwriting questions among
# 200 heterogeneous fields spread across separate sub-batches. In that setting
# the model reliably (a) defaults unanswered questions to "N" and (b) borrows a
# real negative sentence about one subject as fake "proof" for an unrelated
# question — the exact false-"N" flood seen on real ACORD 126 submissions. This
# pass instead sends ONLY the Yes/No questions, together, with their full text,
# under a prompt whose entire job is to answer them correctly OR leave them
# blank. Measured far fewer false "N"s and correct YES-by-meaning detection
# (e.g. hazardous-material disposal) than the general prompt produced.
_COMPLIANCE_SYSTEM_PROMPT = (
    "You are an expert commercial-insurance underwriter. You are given the full text of an "
    "insurance application / declarations document and a list of YES/NO underwriting questions "
    "from an ACORD form. Answer each question STRICTLY and ONLY from the document.\n\n"
    "For each question, choose exactly one:\n"
    "  \"Y\"  — the document contains SPECIFIC evidence the answer is YES (the applicant actually "
    "does the thing / has the exposure / the condition the question asks about).\n"
    "  \"N\"  — the document SPECIFICALLY discusses this question's subject and states it does NOT "
    "apply (no / none / not / never — about THAT subject).\n"
    "  omit — leave the field out entirely when the document does not specifically address this "
    "question's subject. On a typical submission this is the correct choice for MOST questions.\n\n"
    "HARD RULES — follow exactly:\n"
    "  1. SILENCE IS NOT \"N\". If the document does not specifically address a question's subject, "
    "OMIT that field. Never answer \"N\" merely because the subject is not mentioned. On a typical "
    "submission you will OMIT the majority of these questions — that is expected and correct.\n"
    "  2. NEVER BORROW EVIDENCE. A statement about subject A is not proof for a question about a "
    "different subject B, even if it is a negative statement. Before answering, check that the "
    "quote you would cite is SPECIFICALLY about the exact subject THIS question names; if it is "
    "about a different subject, you are borrowing — OMIT the question. Example: \"No blasting, "
    "demolition charges, or explosive materials\" answers ONLY a blasting/explosives question — it "
    "is NOT evidence about excavation, tunneling, planned demolition, joint ventures, or anything "
    "else; omit those unless separately stated.\n"
    "  3. EVERY \"Y\" or \"N\" REQUIRES a grounding quote: a verbatim span copied from the document "
    "that is SPECIFICALLY about THIS question's subject. If you cannot copy such a specific span, "
    "OMIT the field. A quote that merely happens to be negative is not enough — it must be about "
    "THIS question's subject.\n"
    "  4. NEVER reuse the same quote (or sentence) for two different questions. If you want to cite "
    "one sentence for a second question, that second question is almost certainly one to OMIT.\n"
    "  5. DETECT YES BY MEANING, not keywords. If the document describes the applicant actually "
    "doing or having what the question asks, answer \"Y\" even if the word \"yes\" never appears. "
    "Example: for 'do operations involve storing, disposing, or transporting hazardous material?', "
    "a document saying scrap and used cutting fluid are stored on site and removed by a licensed "
    "hazardous-waste hauler IS such an operation → \"Y\" (with that sentence as the quote).\n"
    "  6. Read the polarity of each question carefully. Some are phrased negatively (e.g. 'are "
    "subcontractors allowed to work WITHOUT providing a certificate of insurance?'). A document "
    "stating every subcontractor is REQUIRED to provide one means the answer is \"N\" — quote that "
    "requirement.\n"
    "  7. When genuinely unsure, OMIT. A blank the broker completes is always better than a guess.\n\n"
    "Return JSON with exactly two keys:\n"
    "  \"answers\": {\"<FieldName>\": \"Y\" or \"N\"}   — include ONLY questions you are answering.\n"
    "  \"quotes\":  {\"<FieldName>\": \"<verbatim quote from the document>\"}  — one for every answer.\n"
    "Every field in \"answers\" MUST have a matching entry in \"quotes\". Omit every other field."
)

_COMPLIANCE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "compliance_answers",
        "schema": {
            "type": "object",
            "properties": {
                "answers": {"type": "object", "additionalProperties": {"type": "string"}},
                "quotes":  {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["answers"],
            "additionalProperties": False,
        },
    },
}


def _compliance_question_text(tooltip: str) -> str:
    """Extract the human-readable question from an ACORD Yes/No field tooltip.

    Three real shapes (verified against the schemas):
      * '...The response to the question, "<Q>"?.'  (Question-code TEXT fields)
      * '...Indicates a "Yes"/"No" response to the question, "<Q>"?. As used
        here, ...'  (checkbox-PAIR form of the same convention — ACORD
        125/126/127/130/131/133/141/160/186 — often followed by trailing
        instructional text after the question mark that must NOT be included)
      * 'Enter Y ... Input N ... response. <description>.'  (…YesNoCode_ text
        fields on ACORD 140/25, which have no "the question," clause)
    Falls back to the whole tooltip if none is found."""
    tu = (tooltip or "").strip()
    if not tu:
        return ""
    low = tu.lower()
    marker = "the question,"
    idx = low.find(marker)
    if idx != -1:
        q = tu[idx + len(marker):].strip().strip('."“” ').strip()
        # Stop at the question's own "?" — anything after (e.g. "As used here,
        # if there was no prior coverage, indicate why...") is instructional
        # text about OTHER fields, not part of this question.
        qmark = q.find("?")
        if qmark != -1:
            q = q[: qmark + 1]
        return q or tu
    # No "the question," clause — drop the two "Enter Y…response." / "Input N…
    # response." preamble sentences and keep the trailing description.
    parts = tu.split("response.")
    if len(parts) >= 3:
        tail = "response.".join(parts[2:]).strip()
        return tail.strip('."“” ').strip() or tu
    return tu


# Tokens the LLM commonly returns to signal "not found" — all should be treated
# as empty/null regardless of casing. Kept here so the prompt and the post-filter
# stay in sync; update both sides together if you add new sentinels.
_LLM_EMPTY_SENTINELS = frozenset({
    "", "null", "none", "nil", "n/a", "na", "n.a.",
    "not provided", "not specified", "not available", "not applicable",
    "unknown", "tbd", "to be determined", "undefined", "blank",
})


def _is_empty_llm_value(value) -> bool:
    """Return True if `value` is a JSON null, any string the LLM uses to mean 'not
    found', or a leaked-instruction / template placeholder that must never be
    stamped onto a form.

    This catches true JSON nulls, the literal strings ("null", "None", "N/A",
    "Not Provided", etc.) that GPT-4o-mini frequently emits in JSON mode when the
    instruction is "use null when not found", AND placeholder text like "1st
    distinct value" that a confused model occasionally echoes back from the
    repeating-group prompt instructions instead of a real value (see
    services/placeholder_detector.py). Comparison is case-insensitive and trims
    surrounding whitespace.
    """
    if value is None:
        return True
    if isinstance(value, str):
        if value.strip().lower() in _LLM_EMPTY_SENTINELS:
            return True
        try:
            from services.placeholder_detector import is_placeholder_value
            is_ph, _reason = is_placeholder_value(value)
            if is_ph:
                return True
        except Exception:                                  # pragma: no cover
            pass
        return False
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _fill_unmatched_with_gpt(
    unmatched_fields: dict,
    facts: dict,
    form_id: str,
    model: str = None,
    raw_text: str = "",
    already_filled: Optional[dict] = None,
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

    ``already_filled`` (optional): {field_name: value} for SIBLING fields already
    resolved deterministically by Pass 1/1.5 (e.g. compute_form_gaps' ``mapped``
    return) - NOT sent to the model as fields to fill, but used to tell it which
    rows of a multi-column TABLE (see _table_group_block) are already spoken for,
    so it doesn't re-discover the same real-world entry and duplicate it into a
    different row. Without this, a table whose row A was already resolved by
    Pass 1 (so row A never reaches this function at all) has no way to know row
    A "used up" the first entry the raw text describes - live testing showed
    that produces exactly the failure you'd expect: the model treats whatever
    row IS in its field list as the first slot, re-finds the SAME entry Pass 1
    already captured, and duplicates it there instead of finding the next one.
    """
    already_filled = already_filled or {}
    if not unmatched_fields:
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": model or GPT_MODEL}

    try:
        # Gap fill dispatches its LLM calls onto worker threads, so it uses the
        # SYNC client — sharing the async one across per-call event loops is what
        # caused the generation-hang deadlock (see the factory's docstring).
        _sync_client = _get_openai_form_fill_client_sync()
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
    # Permanently-failed LLM calls in this pass. A failed call returns {}, which
    # downstream looks identical to "the model answered nothing" — so without
    # this the fields simply come back blank and nobody knows a call died.
    _llm_call_failures: List[str]               = []

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

    # ── Table-group detection ───────────────────────────────────────────────
    # Multiple DIFFERENT repeating-group columns that share the identical
    # row-letter set AND a common 2-token prefix are columns of ONE real
    # multi-column schedule (e.g. ACORD 140's Premises Information table:
    # SubjectOfInsuranceCode/LimitAmount/CoinsurancePercent/.../
    # FormsAndConditions all repeat over the SAME 10 rows). Filling each
    # column as an INDEPENDENT "find N distinct values" search (the prior
    # behavior) has no way to know that column X's 2nd distinct value and
    # column Y's 2nd distinct value must describe the SAME real-world row - a
    # live multi-location property test surfaced exactly this failure: a
    # genuine 2nd distinct LimitAmount bled into the unrelated
    # DeductibleAmount column instead of staying null, and an unrelated
    # document sentence landed in a free-text "FormsAndConditions" column,
    # because each column searched the WHOLE document blind to what its
    # sibling columns had already claimed for that row.
    #
    # Fix: bucket these columns' group_keys together so (a) the batcher below
    # never splits them across separate LLM calls (columns in different calls
    # can't possibly stay row-aligned), and (b) the prompt renders ONE
    # row-oriented TABLE block (_table_group_block) instead of N independent
    # column blocks - explicitly telling the model a ROW is one real entry
    # and its columns move together, including "leave this cell null" being
    # the normal, expected outcome for most columns of most rows.
    #
    # Only real multi-column tables (>=3 co-occurring columns) are treated as
    # atomic - a coincidental PAIR sharing a prefix is far more likely to be
    # two unrelated small groups (there are many on a typical ACORD schema)
    # than a genuine table, so pairs fall through to the existing
    # independent-column behavior, completely unchanged.
    #
    # Bucketed by PREFIX ONLY - NOT also by row-letter set. A live production
    # run surfaced why that matters: different columns of the SAME real table
    # very often have DIFFERENT row-letter sets active at gap-fill time,
    # because different Pass 1 mechanisms resolve different columns (e.g.
    # SubjectOfInsuranceCode/LimitAmount via the property_locations-aware
    # resolver, CoinsurancePercent/ValuationCode via a plain scalar-fact
    # rule that only ever fills row A). Requiring an EXACT row-letter match
    # to bucket columns together fragmented one real table into 3-4 separate
    # buckets too small to trigger table treatment at all - so the columns
    # that actually caused the duplication (SubjectOfInsuranceCode,
    # LimitAmount, ...) never got the row-oriented framing in the first
    # place. Each column's OWN active row-letter set is still tracked
    # separately (see active_col_fields in _build_user_prompt) - grouping by
    # prefix only widens WHICH columns are considered part of the same table,
    # it does not pretend every column shares identical rows.
    def _table_prefix(base: str) -> str:
        return "_".join(base.split("_")[:2])

    _table_buckets: Dict[str, List[tuple]] = {}
    for _gk, _slots in _base_to_slots.items():
        _row_letters = tuple(sorted(
            m.group(2) for m in (_ROW_SUFFIX_RE.match(s) for s in _slots) if m
        ))
        if len(_row_letters) < 2:
            continue
        _table_buckets.setdefault(_table_prefix(_gk[0]), []).append(_gk)

    _table_group_keys: set = set()                   # group_keys that are table columns
    _table_group_membership: Dict[tuple, str] = {}    # group_key -> table prefix
    for _prefix, _gks in _table_buckets.items():
        if len(_gks) >= 3:
            for _gk in _gks:
                _table_group_keys.add(_gk)
                _table_group_membership[_gk] = _prefix

    if _table_buckets:
        for _prefix, _gks in _table_buckets.items():
            _is_table = len(_gks) >= 3
            _cols = {g[0] for g in _gks}
            _already_hits = sum(
                1 for _k in already_filled
                if (_m := _ROW_SUFFIX_RE.match(_k)) and _m.group(1) in _cols
            )
            _row_union = sorted({
                _ROW_SUFFIX_RE.match(f).group(2)
                for g in _gks for f in _base_to_slots.get(g, [])
                if _ROW_SUFFIX_RE.match(f)
            })
            logger.info(
                "gpt_fill TABLE_DETECT: form=%s prefix=%s columns=%s row_union=%s treated_as_table=%s "
                "already_filled_hits=%d",
                form_id, _prefix, sorted(_cols), ",".join(_row_union), _is_table, _already_hits,
            )

    _ORDINALS = ["1st", "2nd", "3rd", "4th", "5th", "6th", "7th",
                 "8th", "9th", "10th", "11th", "12th", "13th", "14th"]

    def _field_spec(f: str) -> str:
        """Spec line for a single (non-grouped) field."""
        info = eligible_fields.get(f) or {}
        info = info if isinstance(info, dict) else {}
        full_tu = info.get("tu", "") or ""
        tu   = full_tu[:_PROMPT_TOOLTIP_MAX]   # was [:80] — cut off question text
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
        tu          = full_tu[:_PROMPT_TOOLTIP_MAX]   # was [:80] — cut off question text
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
            f"  RULE: Find up to {n_total} separate real values in the document, in the order\n"
            f"  they appear. Put the 1st one you find in slot _A, the 2nd in slot _B, and so on.\n"
            f"  NEVER copy the same value into more than one slot.\n"
            f"  If fewer than {n_total} values exist, set the remaining slots to JSON null.\n"
            f"  CRITICAL: a slot's value must be an ACTUAL value copied from the document\n"
            f"  (e.g. a name, an amount, a date) - NEVER the words describing which slot it is\n"
            f"  (never write things like 'first value', '2nd distinct value', or any text\n"
            f"  about counting/ordering - that is an instruction to you, not a value)."
        )
        for i, slot_field in enumerate(active_slots):
            ordinal = _ORDINALS[i] if i < len(_ORDINALS) else f"{i + 1}th"
            req     = " [REQUIRED]" if (eligible_fields.get(slot_field) or {}).get("required") else ""
            lines.append(f"  - {slot_field}{req} → slot {i + 1} of {n_total} (null if fewer values exist)")
        lines.append("  ──────────────────────────────────────────")
        return "\n".join(lines)

    def _table_group_block(table_prefix: str, active_col_fields: Dict[str, List[str]]) -> str:
        """Visual block for a genuine multi-column repeating TABLE - several
        DIFFERENT columns that share a common prefix (see the table-group
        detection above). Rendered as ONE combined row-oriented block instead
        of N independent per-column "find N distinct values" blocks, so the
        model reasons about a ROW as one real entry and keeps its columns
        aligned - each column's cell for that row is either grounded in data
        specific to that entry, or null.

        ``active_col_fields`` maps each column's base name to the list of its
        OWN field names actually being asked about in THIS call. Columns are
        deliberately NOT assumed to share an identical row-letter set - a live
        run showed they usually don't (different Pass 1 mechanisms resolve
        different columns for different rows), so each column's real,
        possibly-different row list is used as-is rather than forcing a single
        shared row range that would silently ask for cells that don't exist.
        """
        col_bases = sorted(active_col_fields.keys())
        row_union = sorted({
            _ROW_SUFFIX_RE.match(f).group(2)
            for _fields in active_col_fields.values() for f in _fields
            if _ROW_SUFFIX_RE.match(f)
        })
        n_total = len(row_union)
        slot_labels = "/".join(f"_{r}" for r in row_union)

        # Sibling rows of THIS table already resolved by Pass 1/1.5 (so they
        # never reached this function's field list at all) - without surfacing
        # them, the model has no way to know an earlier real-world entry was
        # already captured elsewhere, and re-discovers it as if it were the
        # first entry, duplicating it into whatever row IS in front of it.
        _col_base_set = set(col_bases)
        _already_rows: Dict[str, Dict[str, str]] = {}
        for _key, _val in already_filled.items():
            if _is_empty_llm_value(_val):
                continue
            _m = _ROW_SUFFIX_RE.match(_key)
            if not _m or _m.group(1) not in _col_base_set:
                continue
            _col_name = _m.group(1).rsplit("_", 1)[-1] if "_" in _m.group(1) else _m.group(1)
            _already_rows.setdefault(_m.group(2), {})[_col_name] = _val

        lines = [
            f"\n  ── TABLE '{table_prefix}' ({n_total} rows: {slot_labels}, "
            f"{len(col_bases)} columns) ──",
            "  Each row is ONE DISTINCT real-world entry (e.g. one coverage item for one\n"
            "  location). ALL columns in the SAME row must describe THAT SAME entry.",
        ]
        if _already_rows:
            lines.append(
                "  Some rows of this SAME table are ALREADY CAPTURED elsewhere and are NOT\n"
                "  part of this request (shown below ONLY so you recognize their entry and\n"
                "  skip past it - do NOT include these rows in your response, do NOT re-find\n"
                "  the same real-world entry, and do NOT restart counting from 1):"
            )
            for _row in sorted(_already_rows.keys()):
                _summary = ", ".join(f"{k}={v}" for k, v in _already_rows[_row].items())
                lines.append(f"    _{_row} (already filled): {_summary}")
        lines.append("  Columns:")
        for base in col_bases:
            sample_field = active_col_fields[base][0]
            info = eligible_fields.get(sample_field) or {}
            tooltip = info.get("tu", "") if isinstance(info, dict) else ""
            col_name = base.rsplit("_", 1)[-1] if "_" in base else base
            short_tu = (tooltip or "")[:_PROMPT_TOOLTIP_MAX]
            line = f"    - {col_name}"
            if short_tu:
                line += f": {short_tu}"
            lines.append(line)
        _first_row = row_union[0] if row_union else "?"
        _second_row = row_union[1] if n_total > 1 else _first_row
        lines.append(
            "  RULE: Find each distinct real entry in the document that is NOT already\n"
            "  captured above, in the order they appear. Fill ONE COMPLETE ROW per entry:\n"
            f"  the 1st such entry → row _{_first_row}, the 2nd → row _{_second_row}, and so on.\n"
            "    a) A cell must ONLY use information that specifically describes THAT\n"
            "       row's entry — never reuse or borrow a value that belongs to a\n"
            "       different entry, a different row, or an unrelated part of the document.\n"
            "    b) If a column's data is not stated for an entry you ARE filling (e.g. no\n"
            "       deductible was given for that item), leave THAT CELL null — do not\n"
            "       guess, and do not reuse a nearby number or sentence from elsewhere.\n"
            "    c) If there are fewer distinct entries than rows, leave the REMAINING\n"
            "       ROWS entirely null (every column null) — never invent an entry.\n"
            "    d) NEVER split one entry's data across two rows, and NEVER duplicate one\n"
            "       entry's data into two rows.\n"
            "    e) A column with no field name listed below for a given row is not part\n"
            "       of this request for that row (it was already resolved separately) -\n"
            "       fill ONLY the exact field names listed for each row, nothing else."
        )
        lines.append("  Exact field names per row:")
        for r in row_union:
            row_fields = [f"{base}_{r}" for base in col_bases if f"{base}_{r}" in active_col_fields[base]]
            if row_fields:
                lines.append(f"    _{r}: {', '.join(row_fields)}")
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
        "     They represent separate sequential entries — not repeated copies of one value.\n"
        "       a) Find each separate real value of that type in the document, in the order they appear.\n"
        "       b) Put the 1st one you find in slot _A, the 2nd in slot _B, the 3rd in slot _C, and so on.\n"
        "       c) NEVER copy the same value into multiple slots — that is always wrong.\n"
        "       d) If the document has fewer values than slots, set the extra slots to JSON null.\n"
        "       e) A slot's value must be copied verbatim from the document (a name, amount, date, …).\n"
        "          NEVER write text that describes the slot itself (e.g. never output the words\n"
        "          'first value', '2nd distinct value', or any ordinal/counting phrase as if it were\n"
        "          the answer — that describes what to do, it is not a value).\n"
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
        # bucket (table prefix) -> column base -> its own active field names.
        active_table_buckets: Dict[str, Dict[str, List[str]]] = {}
        for f in active_fields:
            _gk = _group_key(f)
            if _gk in _table_group_keys:
                _bucket = _table_group_membership[_gk]
                active_table_buckets.setdefault(_bucket, {}).setdefault(_gk[0], []).append(f)
            elif _gk and len(_base_to_slots.get(_gk, [])) > 1:
                active_groups.setdefault(_gk, []).append(f)
            else:
                active_singles.append(f)
        for _gk in active_groups:
            active_groups[_gk].sort()
        for _bucket in active_table_buckets:
            for _base in active_table_buckets[_bucket]:
                active_table_buckets[_bucket][_base].sort()

        parts: List[str] = [_field_spec(f) for f in active_singles]
        for _gk, _slots in sorted(active_groups.items()):
            parts.append(_slot_group_block(_gk, _slots))
        for _bucket, _col_fields in sorted(active_table_buckets.items()):
            parts.append(_table_group_block(_bucket, _col_fields))

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

    # ── LLM caller with retry (reusable for any system+user+schema) ───────────
    def _chat_json(system_msg: str, user_msg: str, response_format: dict) -> dict:
        # Runs on ThreadPoolExecutor worker threads. This is DELIBERATELY fully
        # synchronous: the previous implementation wrapped an async call in
        # asyncio.run(), creating a fresh event loop per call while sharing one
        # module-level AsyncOpenAI client. That let a worker await a pooled
        # connection owned by another thread's already-closed loop, which hung
        # forever with the timeout timer stranded on the dead loop — see
        # _get_openai_form_fill_client_sync() for the full analysis.
        from utils.llm_limiter import llm_slot_sync

        def _inner() -> str:
            with llm_slot_sync():
                try:
                    resp = _sync_client.chat.completions.create(
                        model=llm_model,
                        messages=[
                            {"role": "system", "content": system_msg},
                            {"role": "user",   "content": user_msg},
                        ],
                        temperature=GPT_TEMPERATURE,
                        response_format=response_format,
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
                    resp = _sync_client.chat.completions.create(
                        model=llm_model,
                        messages=[
                            {"role": "system", "content": system_msg},
                            {"role": "user",   "content": user_msg},
                        ],
                        temperature=GPT_TEMPERATURE,
                        response_format={"type": "json_object"},
                        max_completion_tokens=_FORM_FILL_MAX_TOKENS,
                    )
            return resp.choices[0].message.content or ""

        import time as _time
        for attempt in range(_FORM_FILL_BATCH_RETRIES):
            try:
                return json.loads(_inner())
            except Exception as ex:
                if attempt < _FORM_FILL_BATCH_RETRIES - 1:
                    # Backoff is deliberately longer than plain 1/2/4s: the common
                    # failure here is an OpenAI TPM (tokens-per-minute) 429, and a
                    # TPM bucket needs tens of seconds to refill — a 4s retry just
                    # burns an attempt and lands on the same 429. The SDK's own
                    # Retry-After handling covers the polite case; this covers the
                    # case where we exhausted the minute budget ourselves.
                    wait = min(_LLM_RETRY_BACKOFF_BASE_S * (2 ** attempt), _LLM_RETRY_BACKOFF_MAX_S)
                    logger.warning("gpt_fill: call failed attempt=%d/%d retrying in %ds — %s",
                                   attempt + 1, _FORM_FILL_BATCH_RETRIES, wait, ex)
                    _time.sleep(wait)
                else:
                    # A permanently-failed call returns {} — indistinguishable
                    # downstream from "the model legitimately answered nothing".
                    # That silence is how a rate-limited run turns into a form
                    # full of unexplained BLANK Yes/No answers. Count it and log
                    # at ERROR so the failure is visible instead of looking like
                    # a correct omission.
                    _llm_call_failures.append(str(ex)[:200])
                    logger.error(
                        "gpt_fill: call PERMANENTLY FAILED after %d attempts — the fields in "
                        "this batch will be BLANK and that is a FAILURE, not a model omission. "
                        "form=%s err=%s",
                        _FORM_FILL_BATCH_RETRIES, form_id, ex,
                    )
                    return {}

    # JSON-schema response format for the general field-fill call: typing `values`
    # as a map of string→string (no null permitted) forces the model to OMIT
    # absent fields rather than emit explicit nulls — cuts output tokens ~10× on
    # null-heavy batches. Falls back to json_object inside _chat_json if rejected.
    _FORM_FILL_RESPONSE_FORMAT = {
        "type": "json_schema",
        "json_schema": {
            "name": "form_fill_response",
            "schema": {
                "type": "object",
                "properties": {
                    "values":             {"type": "object", "additionalProperties": {"type": "string"}},
                    "raw_text_sourced":   {"type": "array",  "items": {"type": "string"}},
                    "question_grounding": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                "required": ["values"],
                "additionalProperties": False,
            },
        },
    }

    def _call_llm_sync(prompt: str) -> dict:
        # Split the historical single-prompt format back into (system, user) so
        # OpenAI's automatic prefix caching can reuse the skeleton.
        user_msg = prompt[_SKELETON_CHARS:] if prompt.startswith(_PROMPT_SKELETON) else prompt
        return _chat_json(_PROMPT_SKELETON, user_msg, _FORM_FILL_RESPONSE_FORMAT)

    # ── Result absorber ───────────────────────────────────────────────────────
    # Writes into caller-provided accumulators (counts/raw_fields/grounding_out)
    # rather than closure state, so each field sub-batch can absorb into its own
    # LOCAL dicts on a worker thread with zero shared mutation, and results merge
    # cleanly afterward (field sub-batches are disjoint by construction).
    def _absorb(result: dict, sent: List[str], counts: Dict[str, Dict[str, int]],
                raw_fields: set, grounding_out: Dict[str, str],
                chunk_label: str = "1/1") -> None:
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
            counts.setdefault(field, {})
            counts[field][vstr] = counts[field].get(vstr, 0) + 1
            if field in raw_sourced:
                raw_fields.add(field)
            _quote = grounding.get(field)
            if _quote and str(_quote).strip():
                grounding_out[field] = str(_quote).strip()
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

    if not raw_text_used:
        # No raw text available — skip GPT fill entirely
        logger.warning("gpt_fill: form=%s no raw_text provided — skipping GPT fill", form_id)
        return {"filled_values": {}, "new_mappings": {}, "raw_text_fields": set(), "question_grounding": {}, "model_used": llm_model}

    # ── Split raw text into chunks sized for a given field sub-batch ───────────
    def _split_raw_text(active_fields: List[str]) -> List[str]:
        budget = _raw_budget(active_fields)
        chunks: List[str] = []
        rest = raw_text
        while rest:
            if len(rest) <= budget:
                chunks.append(rest)
                break
            split_at = rest.rfind("\n\n", 0, budget)
            if split_at == -1:
                split_at = rest.rfind("\n", 0, budget)
            if split_at == -1:
                split_at = budget
            chunks.append(rest[:split_at])
            rest = rest[split_at:].lstrip("\n")
        return chunks or [raw_text]

    # ── Run ONE field sub-batch through the raw-text chunk loop ────────────────
    # The field list is split into focused sub-batches (see _FIELD_FILL_BATCH):
    # a single call carrying 200+ heterogeneous fields makes the model answer
    # only ~27% of them, silently dropping questions it CAN answer from the
    # document. Each sub-batch runs its raw-text chunks SEQUENTIALLY (so
    # progressive narrowing still trims later chunks) into its OWN local
    # accumulators, so sub-batches can run on parallel worker threads with zero
    # shared mutation and merge cleanly afterward (sub-batches are disjoint).
    def _run_field_batch(batch_fields: List[str], batch_label: str):
        local_counts: Dict[str, Dict[str, int]] = {}
        local_raw: set = set()
        local_grounding: Dict[str, str] = {}
        chunks = _split_raw_text(batch_fields)
        for chunk_idx, raw_chunk in enumerate(chunks):
            active_fields = [f for f in batch_fields if f not in local_counts]
            if not active_fields:
                break
            prompt = _build_prompt(active_fields, raw_chunk, chunk_idx, len(chunks))
            logger.info(
                "gpt_fill: batch=%s chunk %d/%d form=%s active_fields=%d prompt_chars=%d",
                batch_label, chunk_idx + 1, len(chunks), form_id, len(active_fields), len(prompt),
            )
            result = _call_llm_sync(prompt)
            _absorb(result, active_fields, local_counts, local_raw, local_grounding,
                    chunk_label=f"{batch_label}:{chunk_idx + 1}/{len(chunks)}")
        return local_counts, local_raw, local_grounding

    def _merge(local_counts, local_raw, local_grounding):
        # Runs on the main thread only (from the as_completed / direct path), so
        # no lock is needed. Sub-batches are disjoint, so this is effectively a
        # plain fill of pre-initialised candidate_counts buckets.
        for f, cmap in local_counts.items():
            candidate_counts.setdefault(f, {})
            for v, c in cmap.items():
                candidate_counts[f][v] = candidate_counts[f].get(v, 0) + c
        all_raw_fields.update(local_raw)
        all_question_grounding.update(local_grounding)

    # ── Dedicated compliance Yes/No question pass ─────────────────────────────
    # Yes/No underwriting questions are pulled OUT of the general field-fill and
    # answered together by a focused prompt (see _COMPLIANCE_SYSTEM_PROMPT). In
    # the general 200-field prompt the model defaulted these to "N" and borrowed
    # unrelated negative sentences as fake proof — the false-"N" flood reported
    # on real submissions.
    #
    # Three field shapes route here — deliberately NOT every /Btn checkbox:
    #   1. Tooltip begins with the ACORD "Enter Y for a Yes response…"
    #      convention (Question-code TEXT fields + …YesNoCode_ fields on 140/25).
    #   2. Tooltip contains "response to the question," — the CHECKBOX-PAIR
    #      form of the exact same convention ("Check the box (if applicable):
    #      Indicates a "Yes"/"No" response to the question, "<Q>""), used on
    #      ACORD 125/126/127/130/131/133/141/160/186. Found in audit: ACORD 133
    #      has ZERO shape-1 fields and 38 shape-2 fields (previous workers comp
    #      coverage, unpaid premium disputes, ...) that were reaching the
    #      general fill completely unprotected before this fix — same false-N
    #      risk as shape 1, just missed because it's a checkbox, not text.
    #   3. A genuine disclosure-style checkbox not caught by shape 2's tooltip
    #      wording (_is_high_impact_checkbox_field — hired/non-owned auto,
    #      leasing, hazardous materials, maintenance program on 137/138).
    # Generic /Btn coverage-SELECTION checkboxes ("which auto symbol applies",
    # per-row limit-type flags) are deliberately excluded: auditing a real
    # checkbox-heavy form (ACORD 137_CA) found 192 /Btn fields reach gap-fill,
    # of which only 46 are genuine disclosure questions — routing all 192 would
    # both waste ~14 extra LLM calls per form on fields with no false-N risk and
    # dilute this pass's focus away from what it exists to protect.
    _DISCLOSURE_QUESTION_MARKER = "response to the question,"

    def _is_compliance_question(f: str) -> bool:
        info = eligible_fields.get(f) or {}
        info = info if isinstance(info, dict) else {}
        tu = info.get("tu")
        tu_str = str(tu or "")
        if tu_str.startswith(_YES_NO_TOOLTIP_PREFIX):
            return True
        if _DISCLOSURE_QUESTION_MARKER in tu_str:
            return True
        return _is_high_impact_checkbox_field(f, tu, info.get("ft"))

    compliance_fields = [f for f in field_list if _is_compliance_question(f)]
    other_fields      = [f for f in field_list if not _is_compliance_question(f)]

    def _run_one_compliance_batch(q_fields: List[str]) -> Tuple[dict, dict]:
        """Answer one small, focused group of Yes/No questions. Returns
        (answers, quotes). Small groups keep the model's per-question diligence
        high — a single call with all ~40 questions makes it rush and borrow a
        plausible sentence for questions it should omit; ~10 per call it reads
        each carefully. Cross-group quote reuse is still caught downstream by
        the evidence gate's near-duplicate reuse cap.

        The DOCUMENT IS PLACED FIRST, before the question list. Two reasons:
        (1) it makes (system prompt + document) an identical PREFIX across every
        compliance batch for this submission, which OpenAI's automatic prefix
        caching can reuse — without it each call re-billed and re-processed the
        whole document from scratch (the dominant cost of this pipeline: a real
        8-form run issues ~70 calls, each previously shipping the full document);
        (2) "context first, task last" is the stronger ordering for grounded
        extraction.

        The document is also CHUNKED against the call budget. Previously the
        full raw_text was concatenated with no guard at all (unlike the general
        fill, which uses _split_raw_text): on a large multi-document submission
        that pushed the prompt past the budget, the call errored, the retry
        layer exhausted, _chat_json returned {} — and every Yes/No question in
        that batch came back BLANK with nothing surfaced to the user. Chunking
        keeps each call inside budget; a question is answered from whichever
        chunk actually contains its evidence, and "first non-empty answer wins"
        on merge (the model omits questions it cannot ground, so chunks that
        lack the evidence simply return nothing for them)."""
        lines = []
        for f in q_fields:
            info  = eligible_fields.get(f) or {}
            qtext = _compliance_question_text(info.get("tu") if isinstance(info, dict) else "")
            lines.append(f"- {f}: {qtext}")
        questions_block = (
            "\n\nQUESTIONS — answer using ONLY the document above. Follow every HARD RULE. "
            "Omit any question the document does not specifically address; most of the time "
            f"that is the correct choice. (ACORD form {form_id}.)\n" + "\n".join(lines)
        )
        # Budget the document so (system + document + questions + reply headroom)
        # stays inside one call.
        _overhead = len(_COMPLIANCE_SYSTEM_PROMPT) + len(questions_block) + 2_000
        _doc_budget = max(10_000, _GPT_CALL_BUDGET_CHARS - _GPT_REPLY_RESERVE_CHARS - _overhead)
        _doc_chunks: List[str] = []
        _rest = raw_text
        while _rest:
            if len(_rest) <= _doc_budget:
                _doc_chunks.append(_rest)
                break
            _cut = _rest.rfind("\n\n", 0, _doc_budget)
            if _cut == -1:
                _cut = _rest.rfind("\n", 0, _doc_budget)
            if _cut == -1:
                _cut = _doc_budget
            _doc_chunks.append(_rest[:_cut])
            _rest = _rest[_cut:].lstrip("\n")
        if not _doc_chunks:
            _doc_chunks = [raw_text]
        if len(_doc_chunks) > 1:
            logger.info("gpt_fill COMPLIANCE: form=%s document split into %d chunks (%d chars)",
                        form_id, len(_doc_chunks), len(raw_text))

        answers: dict = {}
        quotes:  dict = {}
        for _ci, _chunk in enumerate(_doc_chunks):
            user_msg = f"=== DOCUMENT TEXT ===\n{_chunk}" + questions_block
            result = _chat_json(_COMPLIANCE_SYSTEM_PROMPT, user_msg, _COMPLIANCE_RESPONSE_FORMAT)
            _a = (result.get("answers") or {}) if isinstance(result, dict) else {}
            _q = (result.get("quotes")  or {}) if isinstance(result, dict) else {}
            for _f, _v in _a.items():
                if _f not in answers:            # first chunk that grounds it wins
                    answers[_f] = _v
                    if _q.get(_f):
                        quotes[_f] = _q[_f]
            if len(answers) >= len(q_fields):
                break                            # every question answered already
        return answers, quotes

    def _run_compliance_pass(q_fields: List[str]) -> None:
        if not q_fields:
            return
        batches = [q_fields[i : i + _COMPLIANCE_BATCH]
                   for i in range(0, len(q_fields), _COMPLIANCE_BATCH)]
        logger.info("gpt_fill COMPLIANCE: form=%s questions=%d batches=%d",
                    form_id, len(q_fields), len(batches))
        qset, kept = set(q_fields), 0

        def _absorb_compliance(answers: dict, quotes: dict) -> None:
            nonlocal kept
            for fld, val in (answers or {}).items():
                if fld not in qset or _is_empty_llm_value(val):
                    continue
                vstr = str(val).strip()
                candidate_counts.setdefault(fld, {})
                candidate_counts[fld][vstr] = candidate_counts[fld].get(vstr, 0) + 1
                q = (quotes or {}).get(fld)
                if q and str(q).strip():
                    all_question_grounding[fld] = str(q).strip()
                kept += 1

        if len(batches) <= 1:
            _absorb_compliance(*_run_one_compliance_batch(q_fields))
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(_FIELD_BATCH_POOL, len(batches)),
                thread_name_prefix="gpt-fill-compliance",
            ) as _pool:
                _futs = [_pool.submit(_run_one_compliance_batch, b) for b in batches]
                for _fut in concurrent.futures.as_completed(_futs):
                    _absorb_compliance(*_fut.result())
        logger.info("gpt_fill COMPLIANCE_DONE: form=%s answered=%d/%d", form_id, kept, len(q_fields))

    _run_compliance_pass(compliance_fields)

    # ── Field sub-batch dispatch for everything else (bounded parallel) ───────
    # Flat 40-field slicing (unchanged for ordinary fields) would happily split
    # a table-group's columns across separate batches - i.e. separate LLM
    # calls that never see each other's data at all, making row-alignment
    # impossible no matter how the prompt is worded. Each table-group (see
    # detection above) is therefore packed as ONE atomic batch of its own;
    # everything else is bin-packed into ordinary _FIELD_FILL_BATCH-sized
    # batches exactly as before.
    def _pack_field_batches(fields: List[str], batch_size: int) -> List[List[str]]:
        placed_buckets: set = set()
        batches: List[List[str]] = []
        current: List[str] = []
        for f in fields:
            _gk = _group_key(f)
            _bucket = _table_group_membership.get(_gk) if _gk else None
            if _bucket is not None:
                if _bucket in placed_buckets:
                    continue  # this table's fields were already placed as a unit
                placed_buckets.add(_bucket)
                if current:
                    batches.append(current)
                    current = []
                batches.append([ff for ff in fields if _table_group_membership.get(_group_key(ff)) == _bucket])
                continue
            current.append(f)
            if len(current) >= batch_size:
                batches.append(current)
                current = []
        if current:
            batches.append(current)
        return batches

    field_batches = _pack_field_batches(other_fields, _FIELD_FILL_BATCH)
    logger.info(
        "gpt_fill: form=%s total_fields=%d compliance=%d other=%d field_batches=%d batch_size=%d "
        "table_groups=%d raw_text_chars=%d",
        form_id, len(field_list), len(compliance_fields), len(other_fields),
        len(field_batches), _FIELD_FILL_BATCH, len(_table_buckets), len(raw_text),
    )

    if len(field_batches) <= 1:
        if field_batches:
            _merge(*_run_field_batch(other_fields, "1/1"))
    else:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(_FIELD_BATCH_POOL, len(field_batches)),
            thread_name_prefix="gpt-fill-fbatch",
        ) as _pool:
            _futs = [
                _pool.submit(_run_field_batch, bf, f"{bi + 1}/{len(field_batches)}")
                for bi, bf in enumerate(field_batches)
            ]
            for _fut in concurrent.futures.as_completed(_futs):
                _merge(*_fut.result())

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
        "gpt_fill DONE: form=%s fields_filled=%d/%d field_batches=%d model=%s",
        form_id, len(all_filled), len(eligible_fields), len(field_batches), llm_model,
    )
    if _llm_call_failures:
        # Loud, explicit: some fields are blank because a call DIED, not because
        # the document lacked an answer. Without this the two are identical from
        # the outside and a rate-limited run looks like a correct sparse fill.
        logger.error(
            "gpt_fill INCOMPLETE: form=%s — %d LLM call(s) permanently failed; some fields are "
            "BLANK due to call failure, NOT because the document lacked an answer. Causes: %s",
            form_id, len(_llm_call_failures), "; ".join(_llm_call_failures[:3]),
        )
    return {
        "filled_values":       all_filled,
        "new_mappings":        {},
        "raw_text_fields":     all_raw_fields,
        "question_grounding":  {f: q for f, q in all_question_grounding.items() if f in all_filled},
        "model_used":          llm_model,
        "llm_call_failures":   len(_llm_call_failures),
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
    forms_to_mapped: Optional[Dict[str, dict]] = None,
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
    forms_to_mapped : Dict[form_id, Dict[field_name, value]], optional
        Each form's Pass 1/1.5 `mapped` dict (the OTHER return value of
        `compute_form_gaps`, alongside `unmatched`). Passed through to
        `_fill_unmatched_with_gpt` as `already_filled` so a multi-column TABLE
        (e.g. ACORD 140's Premises Information) whose row A was already
        resolved deterministically - and so never appears in `forms_to_
        unmatched` at all - doesn't get silently re-discovered and duplicated
        into row B by a gap-fill call with no visibility into what Pass 1
        already found. Field names are unique enough across forms in practice
        that a single merged dict is used for every batch; harmless even where
        it isn't, since it only ever SUPPRESSES an already-known row instead
        of asking for one.

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

    # Merge every form's Pass 1/1.5 results into one already_filled dict (see
    # docstring above) - passed through unchanged to every batch below.
    merged_already_filled: dict = {}
    for _fid_map in (forms_to_mapped or {}).values():
        if _fid_map:
            merged_already_filled.update(_fid_map)

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
                already_filled=merged_already_filled,
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


# A live test surfaced a real gap-fill hallucination `_is_numeric_or_date_field`
# above deliberately does NOT catch: `CommercialProperty_Summary_
# BlanketNumberIdentifier` (tooltip "Enter number: The identifying number for
# the blanket.") came back filled with "Location 1"/"Location 2" - a real
# value, just the wrong ENTITY's label, not the blanket grouping number
# nothing in the document actually states. `_NUMERIC_DATE_FIELD_HINTS`
# deliberately excludes "Number" (policy numbers are legitimately
# alphanumeric, e.g. "POL-2026-004471"), so that name-based guard correctly
# leaves it alone - the gap is field-name-blind, so it's covered here instead
# via the field's own SCHEMA TOOLTIP, which is authoritative regardless of
# what the field happens to be named.
_TOOLTIP_NUMBER_PREFIX = "enter number:"


def _tooltip_declares_number(meta: Any) -> bool:
    tu = (meta.get("tu") or "") if isinstance(meta, dict) else ""
    return tu.strip().lower().startswith(_TOOLTIP_NUMBER_PREFIX)


def _looks_like_declared_number_value(s: str) -> bool:
    """A value acceptable for a tooltip-declared 'Enter number:' field. A real
    blanket/identifier number is short and has no multi-letter prose word in
    it (e.g. "1", "2", "B-1", "#12") - a location name, address, or any other
    entity label always contains a run of 4+ letters and is rejected."""
    return not re.search(r"[A-Za-z]{4,}", s or "")


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

# Tokens recognized ONLY for PAIRING a Question-code field to its dependent
# detail field (_question_explanation_pairs below) - deliberately NOT added to
# _EVIDENCE_REQUIRED_TOKENS itself, which _is_evidence_required_field uses to
# decide Pass B eligibility for ANY field, paired or not (bare "Description"/
# "Cost" stays excluded there - most such fields, e.g. ItemDescription,
# AlarmDescription, OperationsDescription, are core content with no Yes/No
# tie at all, and evidence-gating those globally would wrongly blank
# legitimate data - see _EVIDENCE_REQUIRED_TOKENS's own note above). Scoped
# to PAIRING only, and only when the field genuinely sits immediately after
# an otherwise-unpaired Question-code (found in audit, live tests
# 2026-07-15/16: ACORD 186's hazardous-material-abatement question came back
# "Yes" with no gate at all on its dependent "...ExposureDescription" field,
# same bug class as ACORD 127's modified-equipment question).
_PAIRING_ONLY_TOKENS = ("Description", "CostAmount", "Cost")

# Confirmed-coincidental adjacencies to exclude, same rigor as the two
# Explanation-pairing exclusions documented in _question_explanation_pairs:
# audited by hand against the real question text, not assumed. ACORD 141's
# "is physical access to the computer room restricted?" has nothing to do
# with "the complete description of the property including merchandise and
# stock" - the two fields are simply adjacent in the schema by coincidence.
_PAIRING_EXCLUDED = frozenset({
    ("CrimeLineOfBusiness_Question_KBJCode_A", "CrimeInformation_PropertyDescription_A"),
})

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
    checkbox/text field's OWN answer regardless of whether it pairs.

    FALLBACK (found in audit, live tests 2026-07-15/16): when a Question-code
    field has NO adjacent Explanation-shaped field, it may still have a
    genuine dependent detail field immediately next, just named
    "...Description"/"...Cost"/"...CostAmount" instead (_PAIRING_ONLY_TOKENS -
    e.g. ACORD 186's hazardous-material-abatement question ->
    "...ExposureDescription"; ACORD 141's "is a physical inventory made?" ->
    "...FrequencyDescription"). Scoped to Question-code left fields only (not
    /Btn - no evidence yet that checkboxes need this fallback) and to STRICT
    immediate adjacency, same as the primary check - auditing every real
    occurrence across all 17 schemas at this fallback found 6 genuine matches
    and 1 confirmed coincidental adjacency (_PAIRING_EXCLUDED), same rigor as
    the two exclusions above."""
    keys = list(schema.keys())
    pairs: Dict[str, str] = {}
    for i, k in enumerate(keys):
        if i + 1 >= len(keys):
            continue
        nxt = keys[i + 1]
        meta = schema.get(k)
        is_pairable = _QUESTION_CODE_RE.search(k) or (isinstance(meta, dict) and meta.get("ft") == "/Btn")
        if not is_pairable:
            continue
        if any(t in nxt for t in _EVIDENCE_REQUIRED_TOKENS):
            pairs[k] = nxt
        elif (_QUESTION_CODE_RE.search(k)
              and any(re.search(rf"{t}(_[A-Z]{{1,2}})?$", nxt) for t in _PAIRING_ONLY_TOKENS)
              and (k, nxt) not in _PAIRING_EXCLUDED):
            pairs[k] = nxt
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
        if _is_schedule_field(field) or _GL_HAZARD_ROW_RE.match(field) or _SUBJECT_OF_INSURANCE_CODE_ONLY_RE.match(field):
            continue  # schedule / GL hazard / subject-of-insurance CODE rows may legitimately repeat values
            # (LimitAmount is deliberately NOT exempted here - see _SUBJECT_OF_INSURANCE_CODE_ONLY_RE above)
        # Checkbox/indicator rows legitimately share Yes/No across distinct entities
        # (two LLCs both have LLC=Yes; two locations can both be "inside city limits").
        # De-duplication must only collapse free-text VALUE rows (names, addresses).
        val = mapped.get(field)
        if val is None:
            continue
        if "Indicator" in field or str(val).strip().lower() in ("yes", "no", "true", "false"):
            continue
        # A LimitAmount genuinely GROUNDED in a real per-location fact
        # (_resolve_subject_of_insurance_row, backed by property_locations) is
        # trustworthy even if it coincidentally equals row A's amount - two
        # real, distinct locations CAN legitimately share the exact same
        # building value. Only an UNGROUNDED value (gap-filled guess, no
        # property_locations backing) gets the stricter duplicate check below;
        # this is what a live test's genuine 2nd-location duplication slipped
        # through as, and what a dedicated regression test (test_location_
        # consolidation.py) confirms must NOT be blanked for the grounded case.
        if _SUBJECT_OF_INSURANCE_RE.match(field):
            soi = _resolve_subject_of_insurance_row(field, facts)
            if isinstance(soi, str) and soi.strip() == str(val).strip():
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
        elif _tooltip_declares_number(meta) and not _looks_like_declared_number_value(s):
            # Field-name-based hints (_is_numeric_or_date_field) deliberately
            # exclude "Number" (policy numbers are legitimately alphanumeric) -
            # this catches the same class of error via the field's own SCHEMA
            # TOOLTIP instead, which is authoritative regardless of naming (a
            # live test found "Location 1"/"Location 2" stamped into a
            # BlanketNumberIdentifier field whose tooltip explicitly says
            # "Enter number:").
            mapped[field] = None
            logger.info("post_fill_guard type_reject blanked=%s (tooltip declares number, got %r)", field, s[:40])

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


# ── Guard: fabricated industry-classification codes ─────────────────────────
# Live finding (2026-07-20, two independent submissions, different industries):
# ACORD 125's GL CODE / SIC / NAICS boxes came back filled with REAL, correct
# codes for the applicant's industry that appear NOWHERE in the uploaded
# document - 236220 + 5403 for a commercial GC, then 561730 + 0782 for a
# landscaper. The gap-fill model recognised the industry from the operations
# narrative and supplied the code from its own world knowledge. A classification
# code is a regulated identifier that drives rating and eligibility: an
# authoritative-looking wrong code on a submitted ACORD is worse than a blank
# box, and a producer has no way to tell the invented ones apart.
#
# The check is deterministic and purely structural - no LLM, no topic matching
# (see evidence-gate-design memory). A code is kept ONLY when the document
# both (a) mentions that code SYSTEM by name and (b) contains the value itself.
# Requiring the system name is what catches cross-family bleed: the GC document
# did contain "5403", but only as a WORKERS COMP class code, and it never says
# "SIC" anywhere - so 5403 cannot be a grounded SIC code.
#
# Deterministic (Pass 1 / alias) and client-supplied values are never touched -
# only values this run's gap-fill LLM authored.
_CLASSIFICATION_CODE_LABELS: List[Tuple[str, Tuple[str, ...]]] = [
    ("SICCode",              ("sic",)),
    ("NAICSCode",            ("naics",)),
    ("GeneralLiabilityCode", ("gl code", "gl class", "general liability code",
                              "general liability class")),
]


def _drop_ungrounded_classification_codes(
    mapped: dict, raw_text: str, gpt_filled_set: set,
) -> List[str]:
    """Blank any AI-filled SIC / NAICS / GL classification code that the source
    document does not actually support. Returns the list of blanked fields."""
    if not raw_text or not gpt_filled_set:
        return []
    hay_norm = _normalize_for_search(raw_text)
    hay_low  = raw_text.lower()
    dropped: List[str] = []

    for field in list(mapped.keys()):
        if field not in gpt_filled_set:
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        for token, labels in _CLASSIFICATION_CODE_LABELS:
            if token not in field:
                continue
            label_present = any(lbl in hay_low for lbl in labels)
            value_present = _value_in_raw_text(str(val), hay_norm)
            if not (label_present and value_present):
                logger.info(
                    "gpt_fill DROP_UNGROUNDED_CODE: field=%s value=%r "
                    "label_in_doc=%s value_in_doc=%s",
                    field, val, label_present, value_present,
                )
                mapped[field] = None
                dropped.append(field)
            break
    return dropped


# ── Guard: the insured's own address bleeding into a THIRD PARTY's block ─────
# Live finding (2026-07-20): ACORD 125's PRODUCER block showed the applicant's
# street address. The deterministic rule for this was already fixed (see
# _deterministic_map: `_addr_*` resolves for NamedInsured_* only, everything
# else returns UNMATCHED) - so the field correctly fell through to gap-fill,
# and gap-fill then supplied the applicant's address because it was the only
# address in the document. Blanking the deterministic path alone was therefore
# not enough; the same wrong value simply arrived one pass later.
#
# A producer / certificate holder / mortgagee is by definition a DIFFERENT
# entity from the insured, so its street address matching the insured's own is
# a fill error, never a coincidence. Matching is done on the STREET line only -
# a third party genuinely can share the insured's city, state or ZIP - and when
# it matches, the whole address block for that entity is cleared so a stray
# city/ZIP is not left behind orphaned next to a blanked street.
#
# This is a value-IDENTITY check against one known fact with a different
# purpose (the same shape as _is_generic_boilerplate_reuse), not a keyword or
# topic heuristic.
# Swept across all 17 schemas for entity blocks that own an address: the ones
# below are the THIRD PARTIES (a different legal entity from the insured).
# Deliberately EXCLUDED, because the insured's own address is legitimate there:
#   NamedInsured / CommercialStructure / Location  - the insured's own premises
#   Vehicle                                        - garaging is often the yard
#   EmployeeBenefitPlan                            - a small employer really can
#                                                    administer its own plan
_THIRD_PARTY_ADDRESS_BLOCKS: Tuple[str, ...] = (
    "Producer_MailingAddress",
    "AdditionalInterest_MailingAddress",
    "CertificateHolder_MailingAddress",
    "Auditor_MailingAddress",
    "Auditor_Address",
)


def _drop_third_party_address_bleed(
    mapped: dict, facts: dict, gpt_filled_set: set,
) -> List[str]:
    """Clear a third party's address block when its street line is really the
    insured's own address. Returns the list of blanked fields."""
    if not gpt_filled_set:
        return []
    insured_addr = _fv(facts, "mailing_address")
    if not insured_addr or not str(insured_addr).strip():
        return []
    insured_norm = _normalize_for_search(str(insured_addr))
    if not insured_norm:
        return []

    dropped: List[str] = []
    for block in _THIRD_PARTY_ADDRESS_BLOCKS:
        # Find this block's street line(s) and test them against the insured's.
        bleed_rows: set = set()
        for field, val in mapped.items():
            if not field.startswith(block) or "LineOne" not in field:
                continue
            if field not in gpt_filled_set:
                continue
            if val is None or len(str(val).strip()) < 5:
                continue
            if _normalize_for_search(str(val)) in insured_norm:
                # Row suffix (_A/_B/…) so only the offending row is cleared.
                _m = re.search(r"_([A-N])$", field)
                bleed_rows.add(_m.group(1) if _m else "")

        if not bleed_rows:
            continue
        for field in list(mapped.keys()):
            if not field.startswith(block):
                continue
            _m = re.search(r"_([A-N])$", field)
            if (_m.group(1) if _m else "") not in bleed_rows:
                continue
            if mapped.get(field) is None or not str(mapped.get(field)).strip():
                continue
            if field not in gpt_filled_set:
                continue  # never touch a deterministic / client value
            logger.info(
                "gpt_fill DROP_ADDRESS_BLEED: field=%s value=%r "
                "(matches the insured's own mailing address)",
                field, mapped.get(field),
            )
            mapped[field] = None
            dropped.append(field)
    return dropped


# ── Guard: a NAIC number labelled for one entity, stamped for another ────────
# Live finding (2026-07-20): ACORD 125's CARRIER NAIC CODE box (Insurer_NAICCode
# - the CARRIER's own NAIC number) showed the PRODUCER's NAIC number instead.
# The document states "Producer NAIC Number: 41982" and never states a NAIC
# number for the carrier (Pinnacle Mutual Insurance) at all. There is no
# structured `producer_naic` fact anywhere in the extraction schema for this
# guard to compare against (unlike the address guard above, which has
# `facts['mailing_address']`) - "producer NAIC number" simply has no home, so
# gap-fill reached for the only NAIC-shaped number anywhere in the document.
#
# This is a DIFFERENT mechanism from both guards above: the value is not
# fabricated (5-digit codes like a WC class code, above) and it is not a known
# fact belonging to a different entity (the address guard, above) - it is a
# real number in the document whose OWN label names a different entity than
# the field being filled. So the check is text-proximity: does this number, at
# the point it actually appears in the document, sit next to language for the
# RIGHT entity (carrier/insurer) rather than a different one (producer/agency)?
#
# Every occurrence of the value is checked (a document can repeat a number);
# the value is kept if ANY occurrence is carrier/insurer-labelled. It is only
# dropped when EVERY occurrence is labelled for a different role - so a
# genuinely stated carrier NAIC number is never at risk even if the SAME
# digits happen to also appear elsewhere for an unrelated reason.
_NAIC_FIELD_TOKENS: Tuple[str, ...] = ("Insurer_NAICCode", "PriorCoverage_NAICCode")
_NAIC_OWN_ROLE_WORDS   = ("insurer", "carrier", "insurance company", "underwriter", "company")
_NAIC_OTHER_ROLE_WORDS = ("producer", "agency", "agent", "broker")
_NAIC_CONTEXT_WINDOW   = 45  # chars of context immediately before the number


def _drop_mislabeled_naic_codes(
    mapped: dict, raw_text: str, gpt_filled_set: set,
) -> List[str]:
    """Blank an AI-filled Insurer/PriorCoverage NAIC code whose only grounding
    in the document is labelled for a DIFFERENT entity (producer/agency, not
    carrier/insurer). Returns the list of blanked fields."""
    if not raw_text or not gpt_filled_set:
        return []
    hay_low = raw_text.lower()
    dropped: List[str] = []

    for field in list(mapped.keys()):
        if field not in gpt_filled_set:
            continue
        if not any(tok in field for tok in _NAIC_FIELD_TOKENS):
            continue
        val = mapped.get(field)
        if val is None or not str(val).strip():
            continue
        digits = re.sub(r"\D", "", str(val))
        if len(digits) < 4:
            continue  # too short to search for meaningfully

        any_own_role   = False
        any_other_only = False
        start = 0
        while True:
            idx = hay_low.find(digits, start)
            if idx == -1:
                break
            window = hay_low[max(0, idx - _NAIC_CONTEXT_WINDOW): idx]
            has_own   = any(w in window for w in _NAIC_OWN_ROLE_WORDS)
            has_other = any(w in window for w in _NAIC_OTHER_ROLE_WORDS)
            if has_own:
                any_own_role = True
            elif has_other:
                any_other_only = True
            start = idx + len(digits)

        if not any_own_role and any_other_only:
            logger.info(
                "gpt_fill DROP_MISLABELED_NAIC: field=%s value=%r "
                "(only labelled for a different entity in the document)",
                field, val,
            )
            mapped[field] = None
            dropped.append(field)
    return dropped


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
#
# "additional_remarks_text" (audit finding 2026-07-16) carries the identical
# risk profile: a broad, catch-all narrative fact ("any additional remarks,
# explanations, or narrative... e.g. claims context, operations detail,
# conflict resolution" - fact_registry.py) that could equally get recycled as
# an unrelated question's "explanation". Safe to add: its only legitimate
# destination (ACORD 101's AdditionalRemark_RemarkText_* rows, via
# _apply_acord101_overflow) runs strictly AFTER this evidence-gate block and
# unconditionally overwrites whatever it decided, so there is no collision
# with a genuine placement to guard against here.
_BOILERPLATE_FACT_KEYS = ("operations_description", "additional_remarks_text")


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


# ── Dedicated umbrella-period pass (ACORD 131 only) ───────────────────────────
# See the call site in map_facts_to_form for why this exists: the main
# extraction prompt asks for umbrella_effective_date/umbrella_expiration_date
# but has been observed to drop them under real-document load even with an
# explicit instruction, while correctly reading the same dates into a
# neighboring field. One small, standalone question — not a Yes/No, so it does
# not reuse the compliance pass's evidence-quote machinery — mirrors that
# pass's core idea instead: pull the one thing the crowded prompt keeps
# missing OUT of the crowd and ask it alone.
_UMBRELLA_PERIOD_MAX_CHARS = 60_000  # generous single-call budget; this is one small question, not the full doc pipeline

_UMBRELLA_PERIOD_SYSTEM_PROMPT = (
    "You are an expert commercial-insurance underwriter reading an insurance application or "
    "declarations document. The document may describe an UMBRELLA or EXCESS LIABILITY policy "
    "that sits above (attaches over) the applicant's other policies (General Liability, Auto, "
    "Workers Compensation). That umbrella/excess policy commonly has ITS OWN effective and "
    "expiration date, separate from the underlying GL/Auto/WC policy period — sometimes the same "
    "dates, often different.\n\n"
    "Find the umbrella/excess policy's OWN stated effective date and expiration date, if the "
    "document states them. Do NOT use the underlying GL/Auto/WC policy's dates unless the "
    "document explicitly says the umbrella shares that exact period. Do NOT use a retroactive "
    "date (a claims-made trigger date) as the effective date — those are a different concept. "
    "If the document does not clearly state the umbrella's own period, return null for that field "
    "rather than guessing.\n\n"
    "Return JSON with exactly two keys: \"umbrella_effective_date\" and "
    "\"umbrella_expiration_date\", each a date string (e.g. \"07/15/2025\") or null."
)

_UMBRELLA_PERIOD_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "umbrella_period",
        "schema": {
            "type": "object",
            "properties": {
                "umbrella_effective_date":  {"type": ["string", "null"]},
                "umbrella_expiration_date": {"type": ["string", "null"]},
            },
            "required": ["umbrella_effective_date", "umbrella_expiration_date"],
            "additionalProperties": False,
        },
    },
}


def _fetch_umbrella_period_sync(raw_text: str) -> Optional[dict]:
    """Synchronous implementation of the umbrella-period probe.

    This is the single source of truth for the call. It is fully synchronous and
    uses the SYNC OpenAI client so it is safe to invoke directly from a
    ThreadPoolExecutor worker — the previous code reached this logic via
    `_run_coro_sync(...)`, i.e. `asyncio.run()` on a worker thread sharing the
    module-level AsyncOpenAI client, which is the same cross-event-loop deadlock
    documented on `_get_openai_form_fill_client_sync()`.

    Returns {"umbrella_effective_date": ..., "umbrella_expiration_date": ...}
    (either value may be None) or None on any failure — advisory only, never
    raises past this function so a call-site failure can't block form generation.
    """
    try:
        _client = _get_openai_form_fill_client_sync()
    except RuntimeError as exc:
        logger.warning("gpt_fill UMBRELLA_PERIOD: %s — skipping", exc)
        return None

    text = raw_text[:_UMBRELLA_PERIOD_MAX_CHARS]
    user_msg = f"=== DOCUMENT TEXT ===\n{text}"

    try:
        from utils.llm_limiter import llm_slot_sync
        with llm_slot_sync():
            resp = _client.chat.completions.create(
                model=GPT_MODEL,
                messages=[
                    {"role": "system", "content": _UMBRELLA_PERIOD_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=GPT_TEMPERATURE,
                response_format=_UMBRELLA_PERIOD_RESPONSE_FORMAT,
                max_completion_tokens=500,
            )
        content = resp.choices[0].message.content or ""
        result = json.loads(content)
        if not isinstance(result, dict):
            return None
        return {
            "umbrella_effective_date":  result.get("umbrella_effective_date")  or None,
            "umbrella_expiration_date": result.get("umbrella_expiration_date") or None,
        }
    except Exception as exc:                              # noqa: BLE001 — advisory only
        logger.warning("gpt_fill UMBRELLA_PERIOD: call failed — %s", exc)
        return None


async def _fetch_umbrella_period(raw_text: str) -> Optional[dict]:
    """Async wrapper kept for the awaiting caller (extraction_pipeline).

    Delegates to the sync implementation on a worker thread, so there is exactly
    ONE request code path and no AsyncOpenAI client is ever shared across event
    loops. Offloading also keeps the blocking semaphore acquire off the loop.
    """
    import asyncio as _asyncio
    return await _asyncio.get_event_loop().run_in_executor(
        None, _fetch_umbrella_period_sync, raw_text,
    )


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
      - "missing_required_gate" → yellow (form-specific completeness gate, e.g. ACORD 140
        COPE fields via apply_acord140_missing_field_highlights — also feeds the download
        hard-block in field_qa.py, unlike plain "missing_required")
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

    # ── ACORD 131 / 25 dedicated umbrella-period pass ─────────────────────────
    # umbrella_effective_date / umbrella_expiration_date are asked for in the
    # main extraction prompt (extraction_service.py _EXTRACT_SCHEMA + RULE 1),
    # but that prompt carries ~150 other fields and has been observed TWICE on
    # real documents to correctly read the umbrella's stated period into an
    # adjacent field (ExcessUmbrella_*RetroactiveDate_A) while never populating
    # these two facts at all — a crowded-prompt miss, not a missing instruction.
    # The gap-fill stage's small, focused per-field batches DO reliably read
    # ACORD-131-shaped dates from the same document (same observed runs), so
    # this pass mirrors that success: one small, standalone question asked only
    # when facts are silent on the umbrella's own period — never overrides a
    # genuine extraction hit, never fires on any other form, never blocks
    # generation if it fails (falls through to the existing GL-date fallback
    # in the per-form overrides below).
    #
    # ACORD 25 (Certificate of Liability Insurance) ALSO has a genuinely
    # distinct Policy_ExcessLiability_EffectiveDate_A/ExpirationDate_A pair —
    # confirmed against its real schema tooltip ("the effective date of the
    # EXCESS LIABILITY policy"), same underlying concept as 131's umbrella
    # period, just a different form/field name for the same real-world date.
    # Reuses the SAME two facts (no new extraction work) and the same pass —
    # asking once here also means ACORD 131 and ACORD 25 never disagree with
    # each other on the umbrella's own period within a single generation run.
    if form_id in ("ACORD_131", "ACORD_25") and raw_text and raw_text.strip():
        _has_umb_eff = not _is_empty_llm_value(_fv(facts, "umbrella_effective_date"))
        _has_umb_exp = not _is_empty_llm_value(_fv(facts, "umbrella_expiration_date"))
        if not (_has_umb_eff and _has_umb_exp):
            try:
                # Direct sync call — map_facts_to_form runs on a worker thread,
                # so wrapping this in asyncio.run() risked the cross-loop hang.
                _umb_dates = _fetch_umbrella_period_sync(raw_text)
            except Exception as exc:                      # noqa: BLE001 — advisory only
                logger.warning("map_facts UMBRELLA_PERIOD form=%s | error: %s", form_id, exc)
                _umb_dates = None
            if _umb_dates:
                if not _has_umb_eff and _umb_dates.get("umbrella_effective_date"):
                    facts = {**facts, "umbrella_effective_date": _umb_dates["umbrella_effective_date"]}
                if not _has_umb_exp and _umb_dates.get("umbrella_expiration_date"):
                    facts = {**facts, "umbrella_expiration_date": _umb_dates["umbrella_expiration_date"]}
                logger.info(
                    "map_facts UMBRELLA_PERIOD form=%s | effective=%s expiration=%s",
                    form_id, _umb_dates.get("umbrella_effective_date"), _umb_dates.get("umbrella_expiration_date"),
                )

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

        # ACORD 131 override: the form-header Policy_EffectiveDate_A /
        # Policy_ExpirationDate_A fields are handled by the generic
        # _ACORD_FIELD_RULES substring rule shared by every form
        # ("Policy_EffectiveDate" -> effective_date), which is correct
        # everywhere else (that header IS the GL/primary policy's date on
        # every other form) but WRONG here: per the real ACORD 131 template
        # tooltip, this header is "the effective date of the policy [being
        # applied for]" - the UMBRELLA policy itself, which commonly runs its
        # own separate period from the underlying GL/Auto/WC policies it
        # attaches over (that's the whole point of the umbrella period-
        # alignment cross-form check - it needs the umbrella's OWN date here,
        # not a copy of the GL date, or every umbrella policy would trivially
        # "align" with itself). Prefer the umbrella-specific fact when present;
        # fall through to the generic effective_date/expiration_date result
        # _deterministic_map already computed when the document never states a
        # distinct umbrella date (the common case) - never regresses below
        # today's behavior, only improves on it.
        if form_id == "ACORD_131" and field in ("Policy_EffectiveDate_A", "Policy_ExpirationDate_A"):
            _umb_key = "umbrella_effective_date" if field == "Policy_EffectiveDate_A" else "umbrella_expiration_date"
            _umb_val = _fv(facts, _umb_key)
            if not _is_empty_llm_value(_umb_val):
                result = str(_umb_val)

        # ACORD 25 override: same bug, different field name. Policy_
        # ExcessLiability_EffectiveDate_A/ExpirationDate_A are matched by a
        # DEDICATED _ACORD_FIELD_RULES entry (not a generic fallback) that maps
        # them straight to effective_date/expiration_date. Per the real ACORD 25
        # template tooltip ("the effective date of the EXCESS LIABILITY
        # policy"), this is the certificate's excess/umbrella coverage-line row,
        # genuinely distinct from the GL row directly above it on the same
        # certificate (Policy_GeneralLiability_EffectiveDate_A, left untouched -
        # that row correctly IS the GL/primary policy's own date). Same fix,
        # same fact keys, same safety guarantee as the ACORD 131 override above:
        # prefer the umbrella-specific fact when present, fall through to the
        # generic result when the document states no distinct excess period.
        if form_id == "ACORD_25" and field in ("Policy_ExcessLiability_EffectiveDate_A", "Policy_ExcessLiability_ExpirationDate_A"):
            _umb_key = "umbrella_effective_date" if field == "Policy_ExcessLiability_EffectiveDate_A" else "umbrella_expiration_date"
            _umb_val = _fv(facts, _umb_key)
            if not _is_empty_llm_value(_umb_val):
                result = str(_umb_val)

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
        gpt_result     = _fill_unmatched_with_gpt(unmatched, facts, form_id, raw_text=raw_text, already_filled=mapped)
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

        # Count how many DISTINCT Yes/No fields cite each (near-duplicate)
        # grounding quote, so _evidence_supports can blank a quote reused beyond
        # _EVIDENCE_QUOTE_REUSE_MAX times (pathological one-quote-for-everything
        # boilerplate). Clustered by NEAR-DUPLICATE similarity, not exact string
        # match (same token-Jaccard technique Guard 4 uses for cross-field
        # boilerplate bleed on VALUES, here applied to grounding QUOTES): the
        # model can reword the same sentence slightly per field, which exact-
        # string counting would miss. Clustering compares quote-to-QUOTE, never
        # quote-to-QUESTION topic (that heuristic is the standing forbidden one).
        #
        # History: this cap was introduced when a broken 80-char tooltip
        # truncation left the model BLIND to question text, so it answered ~20
        # of 22 questions "No" citing one or two real sentences over and over.
        # With that truncation fixed (2026-07-16, see _SCHEMA_TOOLTIP_MAX) the
        # model reads each real question and moderate reuse is now LEGITIMATE
        # (a broad negation genuinely answers several exposure questions "No").
        # A tight cap therefore began blanking CORRECT answers, so the threshold
        # is now generous and env-tunable — see _EVIDENCE_QUOTE_REUSE_MAX.
        _quote_cluster_tokens: List[frozenset] = []
        _quote_cluster_texts: List[List[str]] = []
        for _f in gpt_filled_set:
            if not _is_gated_field(_f):
                continue
            _q = gpt_question_grounding.get(_f)
            if not _q or not str(_q).strip():
                continue
            _qn = _normalize_for_search(str(_q))
            if not _qn:
                continue
            _q_toks = _sim_tokens(str(_q))
            for _ci, _rep_toks in enumerate(_quote_cluster_tokens):
                if _qn in _quote_cluster_texts[_ci] or _is_near_duplicate_text(_q_toks, _rep_toks):
                    _quote_cluster_texts[_ci].append(_qn)
                    break
            else:
                _quote_cluster_tokens.append(_q_toks)
                _quote_cluster_texts.append([_qn])
        _quote_use_count: Dict[str, int] = {
            _qn: len(_texts) for _texts in _quote_cluster_texts for _qn in _texts
        }

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
            # A "Yes" must cite evidence unique to it (borrowed Yeses assert a
            # false exposure); a "No" may share a broad negation across several
            # exposure questions, so it uses the generous cap.
            _reuse_cap = _EVIDENCE_QUOTE_REUSE_MAX if negative else _EVIDENCE_YES_QUOTE_REUSE_MAX
            if _quote_use_count.get(_normalize_for_search(str(quote)), 0) > _reuse_cap:
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
            # In scope for Pass B when EITHER the field's own name is
            # Explanation-shaped, OR it was recognized as a dependent target
            # via the pairing fallback (_PAIRING_ONLY_TOKENS) - a "...
            # Description"/"...Cost" field with no name-shape signal of its
            # own still needs the same grounding/rescue treatment once
            # position has confirmed it's genuinely dependent on a question.
            if not (_is_evidence_required_field(exp_field) or exp_field in _exp_to_q):
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
            # The dedicated compliance pass is AUTHORITATIVE for a Yes/No question
            # whose tooltip is the ACORD "Enter Y…" convention: it saw the same
            # document and deliberately left this question blank (no Yes evidence).
            # Do NOT let a stray explanation the GENERAL field-fill happened to
            # write promote it to "Y" — that manufactured false "Yes" answers
            # (e.g. "products of others repackaged under applicant label = Y" with
            # a borrowed COI sentence). Blank the stray explanation instead. The
            # promotion path remains for non-compliance fields (the OtherIndicator
            # / companion patterns Pass B/C were originally built for).
            _q_tu = str((schema.get(q_field) or {}).get("tu", "") or "")
            _q_is_compliance = _q_tu.startswith(_YES_NO_TOOLTIP_PREFIX)
            if q_blank and not _q_is_compliance and _present(val, exp_field) \
                    and not _quote_expresses_negative(val) and not _is_nonfillable_field(q_field):
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

    # ── Guard: ungrounded industry-classification codes ───────────────────────
    # Runs BEFORE the trust-labelling pass below so a dropped value can never be
    # painted "ai_verified" on its way out.
    _dropped_codes = _drop_ungrounded_classification_codes(mapped, raw_text, gpt_filled_set)

    # ── Guard: insured's own address bleeding into a third party's block ──────
    _dropped_addr = _drop_third_party_address_bleed(mapped, facts, gpt_filled_set)

    # ── Guard: a NAIC number labelled for one entity, stamped for another ─────
    _dropped_naic = _drop_mislabeled_naic_codes(mapped, raw_text, gpt_filled_set)

    # Values that were just blanked are no longer AI-filled - drop them from the
    # fill set so downstream confidence/QA passes don't reason about a dead value.
    for _df in (_dropped_codes + _dropped_addr + _dropped_naic):
        gpt_filled_set.discard(_df)

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
    confidence = apply_acord140_missing_field_highlights(form_id, facts, mapped, confidence)

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
