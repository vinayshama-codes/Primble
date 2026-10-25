"""The narrative questionnaire page (Brent's attachment A, 23 Oct 2026).

Brent, 23 Oct (25sepChanges.md Z34-2 Q6): "prefer its own page - completing most
automatically and only showing what's relevant", and "much of, if not all, of
the narrative information will be already available in the uploads. This is
just a good way for us to double-check key points." His questionnaire
(`Primble-Narrative-Questionnaire-10:17:26.docx.pdf`, Z29-3) is sections A-L;
this module holds every question as DATA and builds the page from the facts.

THE RULES IT KEEPS (his implementation rules, each mapped to a door we have):

  * Every question reads / writes ONE fact - an existing FACT_REGISTRY fact
    wherever one exists, else a registered `qn_` fact (`fact_registry`, "The
    narrative questionnaire"). A table question reads / writes its capture
    table (`schedule_capture`). Nothing here is a second store of an answer.
  * Prefill from documents, with a STATE per question: extracted /
    producer_confirmed / insured_confirmed / unverified / conflicting /
    not_applicable / missing / unknown / pending. Read off the fact envelope
    (`fact_state.derive_evidence_state` / `derive_value_state`), the Data
    Consistency picker (`underwriting_consistency` - both values shown, never
    overwritten) and the document + page each value prints on
    (`fact_lineage`). "A blank field is not equivalent to No": a two-way
    boolean's false is silence (`extraction_service.unevidenced_boolean_negative`).
  * Unknown / Pending / Not applicable are STATUSES, kept in ONE session key
    (`STATUS_KEY`), never a value and never scored. A status yields as soon as
    the fact it covers changes (each entry carries the value's signature).
  * Modules show only when their line is requested - the readers the scorer
    uses (`line_presence.line_in_submission`, `lob_canon.line_is_carried`,
    the selected forms through `fact_state.lines_applied_for`) plus the
    requested lines of business; "Allow manual additions" = `all_sections`.
  * G is per building: its building questions are VIEWS of the location table
    (one row per building, `premises_cope.is_building_row`), never one value
    for every building; an Extended Period of Indemnity is never a Period of
    Restoration.
  * Only CRITICAL items can block readiness - and they are exactly the facts
    behind the five hard-stop kinds (identity, proposed term, Minimum Viable
    COPE, umbrella underlying). The questionnaire adds no score and no stop:
    missing facts are already charged by Completeness, contradictions by
    Consistency (Brent: no double penalty).
  * A 1-2 page carrier-facing narrative is written from extracted / confirmed
    answers only (`narrative_evidence`, one evidence-gated model call,
    improving-ll.md C110) and printed on ACORD 101 once the producer approves
    it (`NARRATIVE_FACT`). The questionnaire itself stays internal.

Pure functions plus the narrative call - no route, no session write here
(`routes/questionnaire_routes.py` is the HTTP shell).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

STATUS_KEY = "questionnaire_status"      # session row: {question id: status entry}
NARRATIVE_KEY = "carrier_narrative"      # session row: the encrypted draft / approval
NARRATIVE_FACT = "qn_carrier_narrative"  # the APPROVED text - printed on ACORD 101
REMARKS_FACT = "additional_remarks_text"  # the ACORD 101 remarks every narrative card writes

# ── The states (Brent's implementation rules) ────────────────────────────────
EXTRACTED = "extracted"
PRODUCER_CONFIRMED = "producer_confirmed"
INSURED_CONFIRMED = "insured_confirmed"
UNVERIFIED = "unverified"
CONFLICTING = "conflicting"
NOT_APPLICABLE = "not_applicable"
MISSING = "missing"
UNKNOWN = "unknown"
PENDING = "pending"
STATES = (EXTRACTED, PRODUCER_CONFIRMED, INSURED_CONFIRMED, UNVERIFIED, CONFLICTING,
          NOT_APPLICABLE, MISSING, UNKNOWN, PENDING)
NEEDS_INPUT = frozenset({MISSING, UNVERIFIED, CONFLICTING, UNKNOWN, PENDING})
# The states a carrier narrative may be written from (never conflicting /
# unverified / unknown - the owner's rule for the writer).
NARRATIVE_STATES = frozenset({EXTRACTED, PRODUCER_CONFIRMED, INSURED_CONFIRMED})

STATUS_ACTIONS = (UNKNOWN, PENDING, NOT_APPLICABLE)
ACTIONS = ("answer", "confirm") + STATUS_ACTIONS
ANSWER_TYPES = ("text", "long_text", "choice", "yes_no", "number", "currency", "date", "table")

YES_NO_OPTIONS = ["Yes", "No"]
_MAX_DISPLAY = 2000


# ── The questions ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Question:
    id: str
    text: str                                   # Brent's words (the part asked)
    fact: Optional[str] = None                  # the fact it reads / writes
    answer_type: str = "text"
    group: str = ""                             # Brent's whole question, when split
    gate: Optional[str] = None                  # a module gate of its own (J, K, contractor)
    line: Optional[str] = None                  # the coverage family it belongs to
    critical: bool = False                      # behind a hard-stop kind
    insured: bool = False                       # the insured can confirm / answer it
    options: Optional[Tuple[str, ...]] = None   # when the fact has no catalogued list
    multi: bool = False
    table: Optional[str] = None                 # a capture table (schedule_capture)
    columns: Tuple[str, ...] = ()               # a table VIEW's own columns
    needs: Tuple[Tuple[str, ...], ...] = ()     # per row: each group needs one stated cell
    fallback: Tuple[str, ...] = ()              # facts that prefill an empty answer
    computed: Optional[str] = None              # read-only, built from the page
    secure: bool = False


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    intro: str
    gate: Optional[str]                         # None = always shown
    line: Optional[str]
    questions: Tuple[Question, ...]


def _q(qid, text, fact=None, answer_type="text", **kw) -> Question:
    return Question(id=qid, text=text, fact=fact, answer_type=answer_type, **kw)


_A1 = ("Named insured and all related entities / DBAs; mailing address and primary contact "
       "(name, role, email, phone).")
_A2 = ("Effective date, submission purpose (new business / renewal / remarketing), target carriers "
       "if known, requested coverage lines, and desired limits / deductibles.")
_A3 = "Producer, agency, and contact details; decision deadline, quote due date, and reason for marketing."
_B1 = ("Legal structure, FEIN (secure field), years in business, years of owner experience, ownership "
       "changes and acquisitions.")
_B2 = "Plain-language description of products/services and how work is performed; primary customer types."
_B3 = ("Operations by percentage of revenue (must total 100%); residential/commercial/industrial and new "
       "construction/service/repair breakdown where relevant.")
_B4 = "Annual gross revenue: prior year, current estimate and next-year projection; explain material changes."
_B5 = "Employee count (full/part time/seasonal), use of leased employees, temporary labor and subcontractors."
_B6 = ("States of operation, jobsite locations, international exposures, and any unusual or newly added "
       "operations.")
_B7 = "Licenses, certifications, contractual requirements and major changes anticipated next 12 months."
_C1 = ("Claims/loss history period available by line, including open claims and valuation dates; identify "
       "missing years.")
_C2 = ("Material losses: date, cause, amount paid/reserved, corrective actions, and whether conditions "
       "have changed.")
_D2 = "Annual sales or other rating bases by operation/class; confirm GL operations align with WC classifications."
_E1 = ("Payroll by state and WC class code, estimated versus actual, including owners/officers and "
       "inclusion/exclusion status.")
_E2 = "Experience modification factor, rating effective date, loss-control practices and safety responsibilities."
_E4 = "Requested Employers' Liability limits; any alternate employer or waiver of subrogation requirements."
_F1 = "Fleet counts by vehicle type and use; owned, hired, non-owned, leased and employee-owned vehicles."
_F2 = "Garaging locations, operating radius, states, commodities carried and special vehicle exposures."
_F3 = "Driver eligibility, MVR review, telematics, driver training, accident controls and vehicle maintenance."
_F4 = "Prior auto losses, changes to fleet, requested physical damage values/deductibles and applicable filings."
_G1 = "Location/building number, address, ownership/tenant status, occupancy and tenant operations."
_G2 = ("Year built, construction type, stories, square footage, roof type, roof age / last replacement, "
       "updates and protective safeguards.")
_G3 = ("Building, business personal property, stock and equipment values; valuation basis, coinsurance, "
       "deductibles and catastrophe exposures.")
_G4 = ("Sprinklers, alarms, fire protection, distance to hydrant/fire station and critical building "
       "systems, where known.")
_G5 = ("Business Income / Extra Expense requested values and basis; dependencies, maximum expected "
       "downtime and continuity plan.")
_H1 = "Requested limit, attachment points, underlying policy lines, carriers, policy dates and limits."
_H2 = ("Known exclusions, gaps, differing underlying terms, auto/WC/GL coordination and contractual "
       "limit requirements.")
_I1 = "Business use of technology, sensitive data types, approximate records and reliance on critical vendors."
_I2 = "MFA status and scope, backups and restoration testing, endpoint protection, patching and access controls."
_I3 = ("Incident response plan, employee security training, past incidents, ransomware/payment fraud "
       "exposure and outsourcing.")
_I4 = "Business interruption dependencies, revenue impact, requested limits, retentions and contractual requirements."
_K1 = "Specific insured property, activities, locations, values, custody/control, transit and catastrophe exposure."
_K2 = "Crime: funds-transfer approval, segregation of duties, employee dishonesty and social engineering controls."

# The location table's columns each building VIEW shows. The row's own
# identity (address, LOC #, BLDG #) rides with every view.
_LOC_IDENTITY = ("address_line1", "location_number", "building_number")
_LOC = "property_locations"

SECTIONS: Tuple[Section, ...] = (
    Section("A", "Submission overview", "Required for every account.", None, None, (
        _q("A.1a", "Named insured", "applicant_name", group=_A1, critical=True, insured=True),
        _q("A.1b", "Related entities / DBAs", "dba_name", group=_A1, insured=True),
        _q("A.1c", "Mailing address", "mailing_address", group=_A1, insured=True),
        _q("A.1d", "Primary contact - name", "contact_name", group=_A1, insured=True),
        _q("A.1e", "Primary contact - role", "contact_title", group=_A1, insured=True),
        _q("A.1f", "Primary contact - email", "contact_email", group=_A1, insured=True),
        _q("A.1g", "Primary contact - phone", "contact_phone", group=_A1, insured=True),
        _q("A.2a", "Effective date", "effective_date", "date", group=_A2, critical=True),
        _q("A.2b", "Submission purpose (new business / renewal / remarketing)", "qn_submission_purpose",
           "choice", group=_A2, options=("New business", "Renewal", "Remarketing"),
           fallback=("is_renewal", "submission_is_new_business")),
        _q("A.2c", "Target carriers, if known", "submission_carrier_name", group=_A2),
        _q("A.2d", "Requested coverage lines", "lines_of_business", "choice", group=_A2, multi=True),
        _q("A.2e", "Desired limits / deductibles", "qn_requested_terms", "long_text", group=_A2),
        _q("A.3a", "Producer / agency", "producer_name", group=_A3),
        _q("A.3b", "Producer contact - name", "producer_contact_name", group=_A3),
        _q("A.3c", "Producer contact - email", "producer_contact_email", group=_A3),
        _q("A.3d", "Producer contact - phone", "producer_contact_phone", group=_A3),
        _q("A.3e", "Decision deadline", "qn_decision_deadline", "date", group=_A3),
        _q("A.3f", "Quote due date", "qn_quote_due", "date", group=_A3),
        _q("A.3g", "Reason for marketing", "carrier_marketing_reason", "choice", group=_A3),
        _q("A.4", "What makes this account attractive to underwrite? Brief factual summary of "
                  "operations and controls.", "qn_attractive_summary", "long_text"),
        _q("A.5", "Which facts remain unknown or require insured confirmation?", None, "long_text",
           computed="open_items"),
    )),
    Section("B", "Business identity and operations",
            "Describe what the insured actually does, not only its NAICS or website description.",
            None, None, (
        _q("B.1a", "Legal structure", "entity_type", "choice", group=_B1, insured=True),
        _q("B.1b", "FEIN (secure field)", "fein", group=_B1, critical=True, secure=True),
        _q("B.1c", "Years in business", "years_in_business", "number", group=_B1, insured=True),
        _q("B.1d", "Years of owner experience", "qn_owner_experience", "number", group=_B1, insured=True),
        _q("B.1e", "Ownership changes and acquisitions", "qn_ownership_changes", "long_text",
           group=_B1, insured=True),
        _q("B.2a", "Plain-language description of products/services and how work is performed",
           "operations_description", "long_text", group=_B2, insured=True),
        _q("B.2b", "Primary customer types", "qn_customer_types", group=_B2, insured=True),
        _q("B.3a", "Operations by percentage of revenue (must total 100%)", "qn_operations_mix",
           "long_text", group=_B3, insured=True),
        _q("B.3b", "Residential share (%)", "contractor_residential_pct", "number", group=_B3,
           gate="contractor", insured=True),
        _q("B.3c", "Commercial share (%)", "contractor_commercial_pct", "number", group=_B3,
           gate="contractor", insured=True),
        _q("B.3d", "New construction / service / repair breakdown", "qn_work_type_mix", group=_B3,
           gate="contractor", insured=True),
        _q("B.4a", "Annual gross revenue - current estimate", "total_revenue", "currency", group=_B4,
           insured=True),
        _q("B.4b", "Annual gross revenue - prior year", "qn_prior_year_revenue", "currency", group=_B4,
           insured=True),
        _q("B.4c", "Annual gross revenue - next-year projection", "qn_projected_revenue", "currency",
           group=_B4, insured=True),
        _q("B.4d", "Explain material changes", "qn_growth_explanation", "long_text", group=_B4,
           insured=True),
        _q("B.5a", "Full-time employees", "num_employees_full_time", "number", group=_B5, insured=True),
        _q("B.5b", "Part-time employees", "num_employees_part_time", "number", group=_B5, insured=True),
        _q("B.5c", "Seasonal employees", "qn_seasonal_staff", "number", group=_B5, insured=True),
        _q("B.5d", "Leased employees and temporary labor", "qn_leased_temp_labor", group=_B5, insured=True),
        _q("B.5e", "Subcontractors - share of work subcontracted (%)", "percent_subcontracted", "number",
           group=_B5, insured=True),
        _q("B.6a", "States of operation", "state_of_operations", group=_B6, insured=True),
        _q("B.6b", "Jobsite locations", "qn_jobsite_locations", "long_text", group=_B6, insured=True),
        _q("B.6c", "International exposures", "qn_international_exposure", group=_B6, insured=True),
        _q("B.6d", "Unusual or newly added operations", "qn_new_operations", group=_B6, insured=True),
        _q("B.7a", "Licenses and certifications", "qn_credentials", group=_B7, insured=True,
           fallback=("contractor_license_number",)),
        _q("B.7b", "Contractual requirements", "qn_contract_requirements", group=_B7, insured=True),
        _q("B.7c", "Major changes anticipated next 12 months", "qn_planned_changes", group=_B7,
           insured=True),
    )),
    Section("C", "Loss history and risk management",
            "Use loss runs for verification; narrative explains context rather than replacing loss runs.",
            None, None, (
        _q("C.1a", "Claims / loss history period available (years)", "loss_history_years", "number",
           group=_C1, insured=True),
        _q("C.1b", "Open claims", "open_claims_count", "number", group=_C1, insured=True),
        _q("C.1c", "Valuation dates and missing years, by line", "qn_loss_run_gaps", "long_text",
           group=_C1),
        _q("C.2a", "Material losses: date, cause, amount paid/reserved", "loss_history", "table",
           group=_C2, table="loss_history", insured=True),
        _q("C.2b", "Corrective actions, and whether conditions have changed", "qn_corrective_actions",
           "long_text", group=_C2, insured=True),
        _q("C.3", "Safety program, employee training, inspections, incident reporting, contractual risk "
                  "transfer and management oversight.", "qn_safety_program", "long_text", insured=True),
        _q("C.4", "Prior nonrenewals, cancellations, declinations, significant underwriting restrictions "
                  "or coverage gaps, with explanation.", "qn_prior_nonrenewals", "long_text", insured=True,
           fallback=("nonrenewal_reasons",)),
    )),
    Section("D", "General Liability and contractors",
            "Show only for GL / contractors / completed operations.", "general_liab_or_contractor",
            "general_liab", (
        _q("D.1", "Work types, largest projects, project values, jobsite hazards, height/depth work, hot "
                  "work, excavation and other applicable exposures.", "qn_work_exposures", "long_text",
           insured=True, fallback=("contractor_high_hazard_ops",)),
        _q("D.2a", "Annual sales or other rating bases by operation/class", "gl_class_code_schedule",
           "table", group=_D2, table="gl_class_code_schedule"),
        _q("D.2b", "Confirm GL operations align with WC classifications", "qn_gl_wc_alignment",
           group=_D2),
        _q("D.3", "Subcontracted work percentage, subcontractor selection, certificates, additional "
                  "insured and waiver requirements.", "qn_subcontractor_controls", "long_text",
           insured=True),
        _q("D.4", "Contract terms, indemnity, hold harmless, additional insured requirements and any "
                  "wrap-up / OCIP / CCIP work.", "qn_contract_indemnity", "long_text", insured=True),
        _q("D.5", "Products/completed operations exposure, warranties, recalls, professional/design "
                  "responsibilities and prior completed-work losses.", "qn_completed_ops_exposure",
           "long_text", insured=True),
    )),
    Section("E", "Workers' Compensation and Employers' Liability",
            "Show only when WC / EL is requested. Employers' Liability is not Employee Benefits Liability.",
            "workers_comp", "workers_comp", (
        _q("E.1a", "Payroll by state and WC class code", "wc_class_codes", "table", group=_E1,
           table="wc_class_codes", insured=True),
        _q("E.1b", "Owners / officers and their inclusion / exclusion status", "wc_officers", "table",
           group=_E1, table="wc_officers"),
        _q("E.1c", "Estimated versus actual payroll", "qn_estimated_or_actual", "choice", group=_E1,
           options=("Estimated", "Actual", "Some of each")),
        _q("E.2a", "Experience modification factor", "wc_xmod", "choice", group=_E2),
        _q("E.2b", "Rating effective date", "wc_xmod_effective_date", "date", group=_E2),
        _q("E.2c", "Loss-control practices and safety responsibilities", "qn_loss_control", "long_text",
           group=_E2, insured=True),
        _q("E.3", "Subcontractor / independent-contractor labor, certificates, uninsured subcontractor "
                  "exposure and out-of-state work.", "qn_independent_contractors", "long_text",
           insured=True),
        _q("E.4a", "Employers' Liability limit requested - each accident", "wc_el_each_accident",
           "currency", group=_E4),
        _q("E.4b", "Employers' Liability limit requested - disease, each employee",
           "wc_el_disease_each_employee", "currency", group=_E4),
        _q("E.4c", "Employers' Liability limit requested - disease, policy limit",
           "wc_el_disease_policy_limit", "currency", group=_E4),
        _q("E.4d", "Alternate employer or waiver of subrogation requirements", "qn_alternate_employer",
           group=_E4, insured=True),
    )),
    Section("F", "Commercial Auto", "Show only when business auto coverage is requested.", "auto", "auto", (
        _q("F.1a", "Vehicles by type and use", "auto_vin_schedule", "table", group=_F1,
           table="auto_vin_schedule", insured=True),
        _q("F.1b", "Hired vehicles", "hired_auto_indicator", "yes_no", group=_F1, insured=True),
        _q("F.1c", "Non-owned vehicles", "non_owned_auto_indicator", "yes_no", group=_F1, insured=True),
        _q("F.1d", "Leased and employee-owned vehicles", "qn_fleet_mix", group=_F1, insured=True),
        _q("F.2a", "Garaging locations", "qn_garaging_locations", "long_text", group=_F2, insured=True,
           fallback=("auto_garaging_addresses",)),
        _q("F.2b", "Operating radius", "auto_radius_of_operation", "choice", group=_F2, insured=True),
        _q("F.2c", "Commodities carried", "qn_commodities_hauled", group=_F2, insured=True),
        _q("F.2d", "Special vehicle exposures", "qn_special_vehicle_exposures", group=_F2, insured=True),
        _q("F.3a", "Drivers", "auto_drivers", "table", group=_F3, table="auto_drivers", insured=True),
        _q("F.3b", "Driver eligibility, MVR review, telematics, driver training, accident controls and "
                   "vehicle maintenance", "qn_driver_program", "long_text", group=_F3, insured=True),
        _q("F.4a", "Physical damage deductible - comprehensive", "auto_deductible_comp", "currency",
           group=_F4),
        _q("F.4b", "Physical damage deductible - collision", "auto_deductible_collision", "currency",
           group=_F4),
        _q("F.4c", "Physical damage values (valuation)", "auto_physical_damage_valuation", "choice",
           group=_F4, options=("Actual Cash Value", "Agreed Value", "Stated Amount")),
        _q("F.4d", "Prior auto losses, changes to fleet and applicable filings", "qn_fleet_changes_filings",
           "long_text", group=_F4, insured=True),
    )),
    Section("G", "Property and Business Income",
            "Repeat building-level questions for every insured location/building; never apply one "
            "building's details to all.", "property", "property", (
        _q("G.1a", "Location / building number, address and tenant operations", _LOC, "table", group=_G1,
           table=_LOC, insured=True,
           columns=_LOC_IDENTITY + ("address_city", "address_state", "address_zip", "operations_description"),
           needs=(("address_line1",),)),
        _q("G.1b", "Ownership / tenant status", "premises_interest", "choice", group=_G1, insured=True),
        _q("G.1c", "Occupancy", "occupancy_type", "choice", group=_G1, insured=True),
        _q("G.2a", "Year built, construction type, square footage, roof type and roof age / last "
                   "replacement - per building", _LOC, "table", group=_G2, table=_LOC, critical=True,
           insured=True,
           columns=_LOC_IDENTITY + ("construction_type", "year_built", "total_building_area",
                                    "roof_material", "roof_year"),
           needs=(("construction_type",), ("year_built",))),
        _q("G.2b", "Stories, updates and protective safeguards", "qn_building_upgrades", "long_text",
           group=_G2, insured=True),
        _q("G.3a", "Building and business personal property values - per building", _LOC, "table",
           group=_G3, table=_LOC, critical=True, insured=True,
           columns=_LOC_IDENTITY + ("building_value", "bpp_value"),
           needs=(("building_value", "bpp_value"),)),
        _q("G.3b", "Valuation basis", "valuation_method", "choice", group=_G3),
        _q("G.3c", "Coinsurance (%)", "coinsurance_percentage", "number", group=_G3),
        _q("G.3d", "Deductible (all other perils)", "property_deductible_aop", "currency", group=_G3),
        _q("G.3e", "Stock and equipment values; catastrophe exposures", "qn_cat_exposure", "long_text",
           group=_G3, insured=True),
        _q("G.4a", "Sprinklers and fire protection class - per building", _LOC, "table", group=_G4,
           table=_LOC, columns=_LOC_IDENTITY + ("sprinkler", "protection_class"),
           needs=(("sprinkler",), ("protection_class",))),
        _q("G.4b", "Distance to hydrant (feet)", "distance_to_hydrant", "number", group=_G4, insured=True),
        _q("G.4c", "Fire department", "fire_department_type", "choice", group=_G4, insured=True),
        _q("G.4d", "Alarms and critical building systems", "qn_alarms_systems", group=_G4, insured=True),
        _q("G.5a", "Business Income requested value", "business_income_limit", "currency", group=_G5),
        _q("G.5b", "Extra Expense requested value", "extra_expense_limit", "currency", group=_G5),
        _q("G.5c", "Basis, dependencies, maximum expected downtime and continuity plan", "qn_bi_continuity",
           "long_text", group=_G5, insured=True),
        _q("G.6", "Any explicitly stated Business Income Period of Restoration terms or requested coverage "
                  "extensions; do not substitute Extended Period of Indemnity.", "period_of_restoration",
           "choice"),
        _q("G.7", "Vacancy, renovations, property in transit, offsite property and seasonal inventory "
                  "changes.", "qn_vacancy_renovation", "long_text", insured=True),
    )),
    Section("H", "Umbrella / Excess", "Show only when umbrella or excess coverage is requested.",
            "umbrella", "umbrella", (
        _q("H.1a", "Requested limit", "umbrella_limit", "currency", group=_H1),
        _q("H.1b", "Attachment point", "umbrella_attachment_point", "currency", group=_H1),
        _q("H.1c", "Underlying policy lines, carriers, policy dates and limits", None, "long_text",
           group=_H1, critical=True, computed="underlying"),
        _q("H.2a", "Follows the underlying terms (follow form)", "umbrella_follow_form", "choice", group=_H2),
        _q("H.2b", "Known exclusions, gaps, differing underlying terms, auto/WC/GL coordination and "
                   "contractual limit requirements", "qn_umbrella_gaps", "long_text", group=_H2),
        _q("H.3", "Large contracts, high-hazard operations and prior severe losses relevant to excess "
                  "underwriting.", "qn_excess_severity", "long_text", insured=True),
    )),
    Section("I", "Cyber and Technology",
            "Show only for cyber / technology-related coverages. Do not treat a blank control as \"False.\"",
            "cyber", "cyber", (
        _q("I.1a", "Business use of technology, sensitive data types and reliance on critical vendors",
           "qn_cyber_data_types", "long_text", group=_I1, insured=True),
        _q("I.1b", "Approximate records", "cyber_pii_records_count", "number", group=_I1, insured=True),
        _q("I.1c", "Critical vendors", "cyber_third_party_vendors", group=_I1, insured=True),
        _q("I.2a", "MFA status and scope", "cyber_controls_mfa", "yes_no", group=_I2, insured=True),
        _q("I.2b", "Backups and restoration testing", "cyber_controls_backups", "yes_no", group=_I2,
           insured=True),
        _q("I.2c", "Endpoint protection, patching and access controls", "qn_cyber_other_controls",
           "long_text", group=_I2, insured=True),
        _q("I.3a", "Past incidents", "cyber_prior_incidents", "yes_no", group=_I3, insured=True),
        _q("I.3b", "Incident response plan, employee security training, ransomware/payment fraud exposure "
                   "and outsourcing", "qn_cyber_incident_plan", "long_text", group=_I3, insured=True),
        _q("I.4a", "Requested limit", "cyber_limit", "currency", group=_I4),
        _q("I.4b", "Retention", "cyber_retention", "currency", group=_I4),
        _q("I.4c", "Business interruption dependencies, revenue impact and contractual requirements",
           "qn_cyber_dependencies", "long_text", group=_I4, insured=True),
    )),
    Section("J", "Management and Professional Liability",
            "Show EPLI, D&O, E&O or EBL questions only when those coverages are requested.", None, None, (
        _q("J.1", "EPLI: workforce geography, HR practices, employee handbook, complaint procedures, "
                  "turnover and employment claims.", "qn_epli_practices", "long_text", gate="epli",
           line="epli", insured=True),
        _q("J.2", "D&O: entity ownership, board/governance, funding, debt, financial changes and known "
                  "disputes.", "qn_do_governance", "long_text", gate="directors_officers",
           line="directors_officers", insured=True),
        _q("J.3", "Professional liability: professional services, contracts, project/client "
                  "concentration, quality controls and claims.", "qn_professional_controls", "long_text",
           gate="professional", line="professional", insured=True),
        _q("J.4", "Employee Benefits Liability: benefit plans administered, enrollment/eligibility "
                  "procedures, third-party administrators and known administrative errors.",
           "qn_ebl_administration", "long_text", gate="employee_benefits", line="employee_benefits",
           insured=True),
    )),
    Section("K", "Other specialty coverages",
            "Only show relevant specialty modules, e.g., inland marine, crime, pollution, builders risk, "
            "equipment breakdown.", None, None, (
        _q("K.1a", "Total insured value", "inland_marine_total_value", "currency", group=_K1,
           gate="specialty_property", line="inland_marine"),
        _q("K.1b", "Specific insured property, activities, locations, custody/control, transit and "
                   "catastrophe exposure", "qn_specialty_property", "long_text", group=_K1,
           gate="specialty_property", line="inland_marine", insured=True),
        _q("K.2a", "Funds-transfer approval, segregation of duties, employee dishonesty and social "
                   "engineering controls", "qn_crime_controls", "long_text", group=_K2, gate="crime",
           line="crime", insured=True),
        _q("K.2b", "Employees handling money or property", "crime_employee_count", "number", group=_K2,
           gate="crime", line="crime", insured=True),
        _q("K.3", "Pollution: materials handled, disposal practices, historical incidents and remediation "
                  "obligations.", "qn_pollution_exposure", "long_text", gate="pollution",
           line="pollution", insured=True),
        _q("K.4", "Any other unusual exposures or requested endorsements not captured above.",
           "qn_other_exposures", "long_text", insured=True),
    )),
    Section("L", "Producer narrative and underwriting presentation",
            "A concise human-readable summary should be generated from verified structured answers.",
            None, None, (
        _q("L.1", "Why is this account being submitted now, and what coverage outcome is requested?",
           "qn_submission_reason", "long_text"),
        _q("L.2", "What are the top three risk strengths and supporting evidence?", "qn_top_strengths",
           "long_text"),
        _q("L.3", "What are the top three material underwriting concerns and how are they mitigated?",
           "qn_top_concerns", "long_text"),
        _q("L.4", "What has changed since the prior policy period, and what must the underwriter know?",
           "qn_changes_since_prior", "long_text"),
        _q("L.5", "What information is still outstanding, who owns it and when will it be provided?",
           "qn_outstanding_plan", "long_text"),
        # The ACORD 101 remarks every "Explain via ACORD 101" window writes (Brent:
        # the questionnaire replaces that window - his 17 Oct item 7). A narrative
        # card deep-links here by this fact.
        _q("L.6", "Additional remarks and explanations for the underwriter (printed on ACORD 101)",
           "additional_remarks_text", "long_text"),
    )),
)

QUESTIONS: Dict[str, Question] = {q.id: q for s in SECTIONS for q in s.questions}
SECTION_OF: Dict[str, Section] = {q.id: s for s in SECTIONS for q in s.questions}


def question(qid: Any) -> Optional[Question]:
    return QUESTIONS.get(str(qid or "").strip())


def mapped_facts() -> Tuple[List[str], List[str]]:
    """(existing facts, questionnaire-only facts) the questions read / write -
    the second are the registry's `qn_` facts plus `contact_title`."""
    keys = list(dict.fromkeys(q.fact for q in QUESTIONS.values() if q.fact and not q.table))
    new = [k for k in keys if k.startswith("qn_") or k == "contact_title"]
    return [k for k in keys if k not in new], new


# ── Reading the session ──────────────────────────────────────────────────────

def _unwrap(raw: Any) -> Any:
    return raw.get("value") if isinstance(raw, dict) and "value" in raw else raw


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("", "null", "none", "nan", "unknown")
    if isinstance(value, (list, dict)):
        return not value
    return False


def _sig(raw: Any) -> str:
    try:
        blob = json.dumps(raw, sort_keys=True, default=str)
    except Exception:                                          # noqa: BLE001
        blob = repr(raw)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Page:
    """Everything one page build reads, read once."""

    def __init__(self, session: dict):
        session = session if isinstance(session, dict) else {}
        self.session = session
        self.facts = session.get("facts") if isinstance(session.get("facts"), dict) else {}
        self.flags = session.get("flags") if isinstance(session.get("flags"), dict) else {}
        self.docs = [d for d in (session.get("docs") or [])
                     if isinstance(d, dict) and not d.get("excluded")]
        gen = session.get("generated_forms") or {}
        self.form_ids = list(gen.keys()) if isinstance(gen, dict) and gen else \
            list(session.get("selected_form_ids") or [])
        st = session.get(STATUS_KEY)
        self.statuses = st if isinstance(st, dict) else {}
        self._doc_index = None
        self._requested: Optional[set] = None
        self._uw_fields = None

    # documents
    def doc_index(self) -> list:
        if self._doc_index is None:
            try:
                from services.fact_lineage import build_doc_index
                self._doc_index = build_doc_index(self.docs)
            except Exception as exc:                           # noqa: BLE001
                logger.warning("questionnaire: document index unavailable (%s)", exc)
                self._doc_index = []
        return self._doc_index

    def uw_field(self, fact: str) -> Optional[dict]:
        if self._uw_fields is None:
            uc = self.session.get("underwriting_consistency")
            fields = (uc or {}).get("fields") if isinstance(uc, dict) else None
            self._uw_fields = {}
            for f in fields or []:
                if isinstance(f, dict) and f.get("fact_key"):
                    self._uw_fields.setdefault(str(f["fact_key"]), f)
        return self._uw_fields.get(fact)

    # lines
    def requested(self) -> set:
        if self._requested is None:
            self._requested = _requested_families(self.facts, self.flags, self.form_ids)
        return self._requested

    def contractor(self) -> bool:
        from services.line_presence import _flag_true
        return bool(_flag_true(self.flags.get("is_contractor"))
                    or _flag_true(self.facts.get("is_contractor"))
                    or not _is_blank(_unwrap(self.facts.get("contractor_type"))))


def _requested_families(facts: dict, flags: dict, form_ids: list) -> set:
    """The coverage families this submission asks for - the readers the scorer
    uses, in their order of authority:

      1. a selected form applies for its line (`fact_state.lines_applied_for`);
      2. `line_presence.line_in_submission` where the line is described
         (WC, inland marine) - its ABSENT is the submission declining it;
      3. a line the submission declines (`_lines_not_requested`) or the
         documents deny (`fact_state.denied_lines`) is out;
      4. the requested lines of business (A.2d), then the package's own line
         evidence (`lob_canon.line_is_carried` - a granting row or a true
         `has_<line>` flag)."""
    from services import lob_canon
    from services.fact_state import denied_lines, lines_applied_for
    from services import line_presence as lp
    applied = set(lines_applied_for(form_ids))
    candidates: set = set(applied)
    lob = _unwrap(facts.get("lines_of_business"))
    for name in (lob if isinstance(lob, list) else ([lob] if isinstance(lob, str) else [])):
        for part in re.split(r"[,;/]| and ", str(name or "")):
            fam = lob_canon.canon_line(part.strip()) if part.strip() else None
            if fam:
                candidates.add(fam)
    try:
        evidenced, _rows = lob_canon.evidenced_line_families(facts, flags)
        candidates |= set(evidenced)
    except Exception:                                          # noqa: BLE001
        pass
    for prof_line in ("workers_comp", "inland_marine"):
        candidates.add(prof_line)          # judged below by their own door
    declined = {str(x) for x in (_unwrap(facts.get("_lines_not_requested")) or [])
                if isinstance(x, str)}
    denied = set(denied_lines(facts))
    out: set = set()
    for fam in candidates:
        if fam in applied:
            out.add(fam)
            continue
        if lp.line_profile(fam) is not None:
            verdict = lp.line_in_submission(fam, facts, flags, form_ids)
            if verdict == lp.PRESENT:
                out.add(fam)
            if verdict != lp.UNKNOWN:
                continue
        if fam in declined or fam in denied:
            continue
        if fam in _lob_families(facts) or lob_canon.line_is_carried(fam, facts, flags) is True:
            out.add(fam)
    return out


def _lob_families(facts: dict) -> set:
    from services.lob_canon import canon_line
    lob = _unwrap(facts.get("lines_of_business"))
    out: set = set()
    for name in (lob if isinstance(lob, list) else ([lob] if isinstance(lob, str) else [])):
        for part in re.split(r"[,;/]| and ", str(name or "")):
            fam = canon_line(part.strip()) if part.strip() else None
            if fam:
                out.add(fam)
    return out


def _names_a_line(facts: dict, phrases: Iterable[str]) -> bool:
    """A line with no canonical family (builders risk, equipment breakdown)
    named in the requested lines or the package's own line rows."""
    names: List[str] = []
    lob = _unwrap(facts.get("lines_of_business"))
    names += [str(x) for x in (lob if isinstance(lob, list) else [lob]) if x]
    rows = _unwrap(facts.get("coverage_lines"))
    if isinstance(rows, list):
        names += [str(r.get("line") or "") for r in rows if isinstance(r, dict)]
    text = " | ".join(names).lower()
    return any(p in text for p in phrases)


def _gate_open(gate: Optional[str], page: _Page) -> bool:
    if not gate:
        return True
    req = page.requested()
    if gate == "contractor":
        return page.contractor()
    if gate == "general_liab_or_contractor":
        return "general_liab" in req or page.contractor()
    if gate == "specialty_property":
        return ("inland_marine" in req
                or _names_a_line(page.facts, ("builders risk", "builder's risk", "equipment breakdown"))
                or any(not _is_blank(_unwrap(v)) for k, v in page.facts.items()
                       if str(k).startswith("builders_risk_")))
    return gate in req


def visible(q: Question, page: _Page, all_sections: bool = False) -> bool:
    if all_sections:
        return True
    sec = SECTION_OF[q.id]
    return _gate_open(sec.gate, page) and _gate_open(q.gate, page)


# ── One question's reading ───────────────────────────────────────────────────

_EPI_RE = re.compile(r"extended\s+period\s+of\s+indemnity|\bEPI\b", re.I)


def _epi_only(page: _Page) -> bool:
    """The documents print an Extended Period of Indemnity and never a Period
    of Restoration (the Choice Electric decs: "EXTENDED PERIOD OF INDEMNITY
    540 DAYS"). Brent: "do not substitute Extended Period of Indemnity"."""
    texts = " ".join(str(d.get("text") or "") for d in page.docs).lower()
    return bool(re.search(r"extended\s+period\s+of\s+indemnity", texts)) \
        and "period of restoration" not in texts


def mask_secure(value: Any) -> Optional[str]:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return None
    return "**-***" + digits[-4:] if len(digits) >= 4 else "****"


def display(value: Any) -> Optional[str]:
    """A value as the page prints it."""
    v = _unwrap(value)
    if v is None:
        return None
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, list):
        parts = [str(_unwrap(x)).strip() for x in v if not isinstance(_unwrap(x), (dict, list))
                 and str(_unwrap(x)).strip()]
        if parts:
            return ", ".join(parts)[:_MAX_DISPLAY]
        rows = [x for x in v if isinstance(x, dict)]
        return f"{len(rows)} row(s)" if rows else None
    if isinstance(v, dict):
        return None
    text = re.sub(r"[ \t]+", " ", str(v)).strip()
    return text[:_MAX_DISPLAY] or None


def _fallback_display(fact: str, raw: Any) -> Optional[str]:
    v = _unwrap(raw)
    if fact == "is_renewal":
        from services.normalization import yes_no_answer
        yn = yes_no_answer(v)
        return "Renewal" if yn == "Y" else ("New business" if yn == "N" and isinstance(raw, dict)
                                             and raw.get("source") in ("producer", "client_arq") else None)
    if fact == "submission_is_new_business":
        from services.normalization import yes_no_answer
        return "New business" if yes_no_answer(v) == "Y" else None
    return display(raw)


def _evidence_state(fact: str, raw: Any, sources: list) -> str:
    """extracted / producer_confirmed / insured_confirmed / unverified, for a
    value that is there (`fact_state.derive_evidence_state`): a person's value
    is confirmed by whoever it was; a value verified against the documents is
    extracted; a model's reading the documents never print, or a value we
    CALCULATED, is unverified (Brent: "If Primble cannot verify it, flag it
    for confirmation instead of assuming"). A bare value carries no provenance
    at all - extracted only when a document prints it."""
    from services.fact_state import (
        DERIVED, SOURCE_VERIFIED, USER_CONFIRMED, derive_evidence_state,
    )
    es, actor = derive_evidence_state(raw)
    if es == USER_CONFIRMED:
        return INSURED_CONFIRMED if actor == "client" else PRODUCER_CONFIRMED
    if es == SOURCE_VERIFIED:
        return EXTRACTED
    if es == DERIVED:
        return UNVERIFIED
    if not (isinstance(raw, dict) and "value" in raw):
        return EXTRACTED if sources else UNVERIFIED
    return UNVERIFIED


def _sources(fact: str, raw: Any, page: _Page) -> List[dict]:
    try:
        from services.fact_lineage import envelope_value, sources_for_fact
        found = sources_for_fact(fact, raw, page.doc_index())
    except Exception:                                          # noqa: BLE001
        return []
    out: List[dict] = []
    by_name = {str(d.get("filename") or ""): d for d in page.docs}
    for s in found[:3]:
        doc = by_name.get(str(s.get("filename") or "")) or {}
        own = envelope_value((doc.get("facts") or {}).get(fact)) if isinstance(doc, dict) else None
        value = display(own) if own is not None and not isinstance(own, (dict,)) else None
        if s.get("rows"):
            value = f"{s['rows']} row(s)"
        out.append({"document": s.get("filename"), "page": s.get("page"),
                    "value": value if value is not None else display(raw)})
    return out


def _conflict_values(fact: str, page: _Page) -> List[dict]:
    """Both (every) values the documents give - the Data Consistency picker's
    own groups, else each document's own reading. Never resolved here. Each
    carries its `choice` index: "Use this" posts the index, never the value,
    so a masked secure value never travels back (`choice_value`)."""
    return [dict(c, choice=i) for i, c in enumerate(_conflict_readings(fact, page))]


def choice_value(session: dict, q: Question, choice: Any) -> Optional[str]:
    """The REAL value behind a conflict row's `choice` index, or None."""
    try:
        i = int(choice)
    except (TypeError, ValueError):
        return None
    vals = _conflict_readings(q.fact, _Page(session)) if q.fact else []
    if 0 <= i < len(vals):
        v = vals[i].get("value")
        return str(v).strip() if v is not None and str(v).strip() else None
    return None


def _conflict_readings(fact: str, page: _Page) -> List[dict]:
    out: List[dict] = []
    field = page.uw_field(fact)
    if field:
        for grp in field.get("values") or []:
            if not isinstance(grp, dict):
                continue
            shown = grp.get("display") or grp.get("normalized")
            for src in grp.get("sources") or [{}]:
                out.append({"value": shown, "document": (src or {}).get("filename")})
    if out:
        return out
    for d in page.docs:
        v = display((d.get("facts") or {}).get(fact))
        if v is not None:
            out.append({"value": v, "document": d.get("filename")})
    return out


def _is_conflicting(fact: str, raw: Any, page: _Page) -> bool:
    from services.fact_state import CONFLICTING as _FS_CONFLICT, confirmed_by_person, derive_value_state
    if confirmed_by_person(raw):
        return False
    try:
        if derive_value_state(fact, raw, page.facts) == _FS_CONFLICT:
            return True
    except Exception:                                          # noqa: BLE001
        pass
    field = page.uw_field(fact)
    return bool(field and field.get("status") == "conflict" and field.get("review_required"))


def _status_entry(q: Question, sig: str, page: _Page) -> Optional[dict]:
    """The stored Unknown / Pending / Not applicable for this question, while
    the fact it covers is as it was when it was set."""
    entry = page.statuses.get(q.id)
    if not isinstance(entry, dict) or entry.get("status") not in STATUS_ACTIONS:
        return None
    if entry.get("sig") and entry.get("sig") != sig:
        return None                    # the answer moved since - the status yields
    return entry


def _blank_reading(fact: str, raw: Any, value: Any, page: _Page) -> Optional[str]:
    """None when the fact holds a value; else the state its emptiness reads as
    (`not_applicable` / a person's or document's explicit No / missing)."""
    from services.fact_state import EXPLICIT_NO, NOT_APPLICABLE as _FS_NA, NOT_STATED, \
        UNABLE_TO_DETERMINE, derive_value_state
    try:
        vs = derive_value_state(fact, raw, page.facts)
    except Exception:                                          # noqa: BLE001
        vs = None
    if vs == _FS_NA:
        return NOT_APPLICABLE
    if vs == EXPLICIT_NO:
        return "explicit_no"
    try:
        from services.extraction_service import unevidenced_boolean_negative
        if unevidenced_boolean_negative(fact, value):
            return MISSING             # a blank control is not "False" (Brent, section I)
    except Exception:                                          # noqa: BLE001
        pass
    if vs in (NOT_STATED, UNABLE_TO_DETERMINE) or _is_blank(value):
        return MISSING
    return None


def _read_scalar(q: Question, page: _Page) -> dict:
    fact = q.fact
    raw = page.facts.get(fact)
    value = _unwrap(raw)
    out: dict = {"value": None, "display_value": None, "state": MISSING, "sources": [],
                 "conflict_values": None, "prefilled_from": None, "note": None, "sig": _sig(raw)}
    status = _status_entry(q, out["sig"], page)

    if _is_conflicting(fact, raw, page):
        out.update(state=CONFLICTING, conflict_values=_conflict_values(fact, page),
                   value=display(value), display_value=display(value))
        if status is None:
            return _masked(q, out, value, True)

    blank = _blank_reading(fact, raw, value, page)
    if blank is None:
        sources = _sources(fact, raw, page)
        out.update(value=value if not isinstance(value, (dict, list)) else display(value),
                   display_value=display(value), sources=sources,
                   state=_evidence_state(fact, raw, sources))
    elif blank == "explicit_no":
        from services.fact_state import USER_CONFIRMED, derive_evidence_state
        es, actor = derive_evidence_state(raw)
        said = "No" if value is False else "None"
        out.update(value=said, display_value=said,
                   state=(INSURED_CONFIRMED if actor == "client" else PRODUCER_CONFIRMED)
                   if es == USER_CONFIRMED else EXTRACTED)
    elif blank == NOT_APPLICABLE:
        out.update(state=NOT_APPLICABLE)
    else:
        for fb in q.fallback:
            fb_raw = page.facts.get(fb)
            shown = _fallback_display(fb, fb_raw)
            if shown:
                sources = _sources(fb, fb_raw, page)
                out.update(value=shown, display_value=shown, prefilled_from=fb, sources=sources,
                           state=_evidence_state(fb, fb_raw, sources))
                break

    if fact == "period_of_restoration" and out["state"] in (EXTRACTED, UNVERIFIED) \
            and (_EPI_RE.search(str(out["display_value"] or "")) or _epi_only(page)):
        out.update(state=UNVERIFIED,
                   note="The documents print an Extended Period of Indemnity, not a Period of "
                        "Restoration - the two are never substituted for each other.")
    out = _masked(q, out, value, blank is None)
    if status is not None:
        out["state"] = status["status"]
    return out


def _masked(q: Question, out: dict, value: Any, present: bool) -> dict:
    """A secure field (FEIN) leaves the server masked - its value, its
    sources and every conflicting value; "Use this" posts the `choice` index
    (`choice_value`), never the number."""
    if not q.secure:
        return out
    shown = mask_secure(value) if present else None
    out.update(value=None, display_value=shown,
               sources=[dict(s, value=shown) for s in out["sources"]],
               conflict_values=[dict(c, value=mask_secure(c.get("value")))
                                for c in (out["conflict_values"] or [])] or out["conflict_values"])
    return out


def _table_rows(key: str, page: _Page) -> List[dict]:
    try:
        from services.schedule_capture import FOLLOW_UP_KEY, ROW_ID_KEY, rows_from_facts
        rows = rows_from_facts(key, page.facts)
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("questionnaire: %s rows unreadable (%s)", key, exc)
        return []
    keep = []
    for r in rows:
        if any(str(v or "").strip() for k, v in r.items() if k not in (ROW_ID_KEY, FOLLOW_UP_KEY)):
            keep.append(r)
    return keep


def _stated(v: Any) -> bool:
    return not _is_blank(v)


def _building_label(i: int, row: dict) -> str:
    loc = str(row.get("location_number") or "").strip()
    bldg = str(row.get("building_number") or "").strip()
    head = (f"Loc {loc}" if loc else f"Building {i + 1}") + (f" / Bldg {bldg}" if bldg else "")
    addr = str(row.get("address_line1") or "").strip()
    return f"{head} - {addr}" if addr else head


def _column_labels(key: str) -> Dict[str, dict]:
    from services.schedule_capture import get_def
    return {str(c.get("key")): c for c in ((get_def(key) or {}).get("columns") or [])
            if isinstance(c, dict)}


def _read_table(q: Question, page: _Page) -> dict:
    from services import confirm_known
    from services.schedule_capture import human_rows, rows_fingerprint
    key = q.table
    rows = _table_rows(key, page)
    out: dict = {"value": rows, "display_value": None, "state": MISSING, "sources": [],
                 "conflict_values": None, "prefilled_from": None, "note": None,
                 "sig": rows_fingerprint(rows), "per_building": None}
    labels = _column_labels(key)
    status = _status_entry(q, out["sig"], page)
    try:
        from services.fact_lineage import list_sources
        out["sources"] = [{"document": s.get("filename"), "page": None,
                           "value": f"{s.get('rows')} row(s)"}
                          for s in list_sources(key, page.facts.get(key), page.doc_index())[:3]]
    except Exception:                                          # noqa: BLE001
        pass

    missing_any = False
    if key == _LOC:
        from services.premises_cope import is_building_row
        buildings = [r for r in rows if is_building_row(r)]
        per: List[dict] = []
        lines: List[str] = []
        for i, row in enumerate(buildings):
            gaps = [" or ".join(labels.get(c, {}).get("label", c) for c in grp)
                    for grp in q.needs if not any(_stated(row.get(c)) for c in grp)]
            vals = {c: row.get(c) for c in q.columns if c in row}
            per.append({"building": _building_label(i, row), "row_id": row.get("_row_id"),
                        "values": vals, "missing": gaps})
            shown = ", ".join(f"{labels.get(c, {}).get('label', c)} {row.get(c)}"
                              for c in q.columns if c not in _LOC_IDENTITY and _stated(row.get(c)))
            lines.append(_building_label(i, row) + (f": {shown}" if shown else "")
                         + (f" (missing {', '.join(gaps)})" if gaps else ""))
            missing_any = missing_any or bool(gaps)
        out["per_building"] = per
        out["display_value"] = "\n".join(lines) or None
        has_rows = bool(buildings)
    else:
        has_rows = bool(rows)
        out["display_value"] = f"{len(rows)} row(s)" if rows else None

    if not has_rows:
        if key == "loss_history" and _no_losses_attested(page):
            out.update(state=EXTRACTED, display_value="No prior losses reported")
    elif missing_any:
        out["state"] = MISSING
    else:
        held, source = human_rows(page.facts, key)
        confs = page.facts.get(confirm_known.CONFIRMATIONS_KEY) or {}
        conf = confs.get(f"schedule::{key}")
        whole_by = None
        if held is not None:
            whole_by = source
        elif isinstance(conf, dict) and conf.get("signature") == confirm_known.rows_signature(rows):
            whole_by = conf.get("by")
        if q.columns:
            # A VIEW is confirmed by its own mark - a save or "Looks right" on
            # another view of the same table says nothing about these columns.
            # The insured's whole-table answer counts when they saw every column.
            mine = confs.get(view_confirmation_key(q))
            sees_all = not any((labels.get(c) or {}).get("producer_only") for c in q.columns)
            if isinstance(mine, dict) and mine.get("signature") == confirm_known.rows_signature(
                    view_rows(q, rows)):
                out["state"] = PRODUCER_CONFIRMED if mine.get("by") != "client_arq" else INSURED_CONFIRMED
            elif whole_by == "client_arq" and sees_all:
                out["state"] = INSURED_CONFIRMED
            else:
                out["state"] = EXTRACTED
        elif whole_by is not None:
            out["state"] = INSURED_CONFIRMED if whole_by == "client_arq" else PRODUCER_CONFIRMED
        else:
            out["state"] = EXTRACTED
    if status is not None:
        out["state"] = status["status"]
    return out


def _no_losses_attested(page: _Page) -> bool:
    try:
        from services.sqs_service import _attested_true
        return bool(page.flags.get("no_prior_losses")) or _attested_true(
            _unwrap(page.facts.get("loss_history_no_prior_losses_indicator")))
    except Exception:                                          # noqa: BLE001
        return bool(page.flags.get("no_prior_losses"))


def _read_underlying(q: Question, page: _Page) -> dict:
    """H.1c: the underlying policies the Policies table holds, and whether the
    umbrella's underlying limits are stated (`sqs_service.umbrella_underlying`
    - the hard-stop door). Read-only: the policies are edited in that table."""
    out: dict = {"value": None, "display_value": None, "state": MISSING, "sources": [],
                 "conflict_values": None, "prefilled_from": None, "sig": "",
                 "note": "Edit the underlying policies in the Policies table."}
    try:
        from services.policy_lines import table_rows
        rows = [r for r in table_rows(page.facts, page.docs) if r.get("line") != "umbrella"]
        # Only the lines an umbrella sits over (live e66d68d7, 25 Oct: H.1c
        # listed Property, Inland Marine, Crime, Cyber and D&O as "underlying
        # policies"). The one rule the excess 131 uses.
        from services.umbrella_layers import applicable_underlying_lines
        fams = set(applicable_underlying_lines({**(page.facts or {}), **(page.flags or {})}))
        if fams:
            rows = [r for r in rows if r.get("line") in fams]
    except Exception:                                          # noqa: BLE001
        rows = []
    lines = []
    for r in rows:
        limits = "; ".join(f"{p.get('amount')} {p.get('label') or ''}".strip()
                           for p in (r.get("limit_parts") or []) if isinstance(p, dict) and p.get("amount"))
        term = " to ".join(x for x in (r.get("effective_date"), r.get("expiration_date")) if x)
        lines.append(" | ".join(x for x in (r.get("line_label") or r.get("line"), r.get("carrier_name"),
                                            r.get("policy_number") and f"Policy no. {r['policy_number']}",
                                            term, limits and f"Limit {limits}") if x))
    out["display_value"] = "\n".join(lines) or None
    out["value"] = out["display_value"]
    out["sig"] = _sig(out["display_value"])
    try:
        from services.sqs_service import umbrella_underlying
        verdict = umbrella_underlying(page.facts, page.flags)
    except Exception:                                          # noqa: BLE001
        verdict = {}
    if not verdict.get("identified") or verdict.get("missing_scheduled"):
        out["state"] = MISSING
    elif verdict.get("missing_carried") or verdict.get("scheduled_to_confirm"):
        out["state"] = UNVERIFIED
    else:
        out["state"] = EXTRACTED
    status = _status_entry(q, out["sig"], page)
    if status is not None:
        out["state"] = status["status"]
    return out


def _options(q: Question) -> Optional[List[str]]:
    if q.answer_type == "yes_no":
        return list(YES_NO_OPTIONS)
    if q.answer_type != "choice":
        return None
    if q.options:
        return list(q.options)
    try:
        from services.answer_options import options_for
        return options_for(q.fact) if q.fact else None
    except Exception:                                          # noqa: BLE001
        return None


def _table_spec(q: Question, page: _Page, rows: List[dict]) -> Optional[dict]:
    """The table's spec in the shape the fix window's schedule editor already
    reads (`arq_service.get_session_schedules`: schedule_key / schedule_label /
    columns / rows / dedup_keys / ...), so the page draws the same
    `ScheduleTable`. A per-building VIEW (G) shows its own columns; the rows
    keep every cell, and a save lays the view's cells over each building's
    stored row (`merged_table_rows`)."""
    if not q.table:
        return None
    try:
        from services import schedule_capture as sc
        defn = sc.get_def(q.table)
        if defn is None:
            return None
        columns = sc.columns_for(q.table, page.facts)
        if q.columns:
            by_key = {str(c.get("key")): c for c in columns if isinstance(c, dict)}
            columns = [by_key[k] for k in q.columns if k in by_key]
        _rows, report = sc.validate_rows(q.table, rows, shown=rows)
        spec = {
            "schedule_key": q.table,
            "schedule_label": defn["label"],
            "schedule_singular": defn["singular"],
            "columns": columns,
            "dedup_keys": defn["dedup_keys"],
            "vin_decode": bool(defn["vin_decode"]),
            "row_capacity": sc.capacity_for(q.table),
            "rows": rows,
            "row_count": report.get("row_count", len(rows)),
            "overflow": report.get("overflow"),
            "duplicates": report.get("duplicates"),
            "producer_only": sc.is_producer_only(q.table),
        }
        for k in ("follow_up", "title", "intro"):
            if defn.get(k):
                spec[k] = defn[k]
        return spec
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("questionnaire: %s spec unavailable (%s)", q.table, exc)
        return None


def render(q: Question, page: _Page) -> dict:
    """One question in the API contract's shape (plus a few added fields)."""
    if q.computed == "underlying":
        reading = _read_underlying(q, page)
    elif q.computed:
        reading = {"value": None, "display_value": None, "state": EXTRACTED, "sources": [],
                   "conflict_values": None, "prefilled_from": None, "note": None, "sig": ""}
    elif q.table:
        reading = _read_table(q, page)
    else:
        reading = _read_scalar(q, page)
    sec = SECTION_OF[q.id]
    status = page.statuses.get(q.id) if isinstance(page.statuses.get(q.id), dict) else None
    help_text = q.group if q.group and q.group != q.text else ""
    if reading.get("note"):
        help_text = (help_text + " " + reading["note"]).strip()
    return {
        "id": q.id,
        "section": sec.id,
        "text": q.text,
        "help": help_text,
        "answer_type": q.answer_type,
        "options": _options(q),
        "multi": q.multi,
        "table": _table_spec(q, page, reading["value"]) if q.table else None,
        "table_key": q.table,
        "per_building": reading.get("per_building"),
        "value": reading["value"],
        "display_value": reading["display_value"],
        "state": reading["state"],
        "sources": reading["sources"] or [],
        "conflict_values": reading["conflict_values"] or None,
        "needs_input": reading["state"] in NEEDS_INPUT,
        "critical": q.critical,
        "insured_confirmable": q.insured and not q.secure and not q.computed,
        "fact": q.fact,
        "line": q.line or sec.line,
        "computed": bool(q.computed),
        "prefilled_from": reading.get("prefilled_from"),
        "status": ({k: status.get(k) for k in ("status", "as_of", "by", "owner", "note")}
                   if status and reading["state"] == status.get("status") else None),
    }


_TO_CONFIRM = frozenset({UNKNOWN, PENDING, UNVERIFIED, CONFLICTING})


def _open_items_reading(questions: List[dict]) -> Tuple[Optional[str], List[str]]:
    """A.5 "Which facts remain unknown or require insured confirmation?": the
    items marked Unknown / Pending, the values nobody has verified, the
    disagreements, and any critical item still missing - not every blank
    narrative question (the page's own count says how many of those there
    are)."""
    open_items = [f"{q['id']} {q['text']} ({q['state'].replace('_', ' ')})" for q in questions
                  if not q.get("computed")
                  and (q.get("state") in _TO_CONFIRM or (q.get("critical") and q.get("needs_input")))]
    return ("\n".join(open_items) if open_items else "Nothing outstanding."), open_items


def build_page(session: dict, all_sections: bool = False) -> dict:
    """GET /api/questionnaire/{session_id}."""
    page = _Page(session)
    sections: List[dict] = []
    rendered: List[dict] = []
    for sec in SECTIONS:
        if not all_sections and not _gate_open(sec.gate, page):
            continue
        qs = [render(q, page) for q in sec.questions if visible(q, page, all_sections)]
        if not qs:
            continue
        rendered.extend(qs)
        sections.append({"id": sec.id, "title": sec.title, "line": sec.line, "intro": sec.intro,
                         "questions": qs})
    text, items = _open_items_reading(rendered)
    for q in rendered:
        if q["id"] == "A.5":
            q.update(value=text, display_value=text, state=EXTRACTED, needs_input=False)
    counts = {"needs_input": sum(1 for q in rendered if q["needs_input"]),
              "total": len(rendered),
              "critical_open": sum(1 for q in rendered if q["needs_input"] and q["critical"])}
    return {"sections": sections, "counts": counts, "narrative": narrative_summary(session)}


def find_rendered(page_out: dict, qid: str) -> Optional[dict]:
    for sec in page_out.get("sections") or []:
        for q in sec.get("questions") or []:
            if q.get("id") == qid:
                return q
    return None


def reading_for(session: dict, qid: str) -> Optional[dict]:
    """One question rendered against `session` (visible or not)."""
    q = question(qid)
    if q is None:
        return None
    return render(q, _Page(session))


# ── Statuses ─────────────────────────────────────────────────────────────────

def status_entry(session: dict, qid: str, status: str, user_id: Optional[str] = None,
                 owner: Optional[str] = None, note: Optional[str] = None) -> dict:
    """The stored entry for an Unknown / Pending / Not applicable mark: the
    signature of the fact as it stands, so any later change supersedes it."""
    q = question(qid)
    page = _Page(session)
    if q.computed == "underlying":
        sig = _read_underlying(q, page)["sig"]
    elif q.table:
        sig = _read_table(q, page)["sig"]
    elif q.fact:
        sig = _sig(page.facts.get(q.fact))
    else:
        sig = ""
    entry = {"status": status, "as_of": now_iso(), "by": "producer", "sig": sig}
    if user_id:
        entry["by_user"] = str(user_id)
    if owner:
        entry["owner"] = re.sub(r"<[^>]*>", "", str(owner)).strip()[:80]
    if note:
        entry["note"] = re.sub(r"<[^>]*>", "", str(note)).strip()[:500]
    return entry


def with_status(session: dict, qid: str, entry: Optional[dict]) -> dict:
    statuses = dict(session.get(STATUS_KEY) or {}) if isinstance(session.get(STATUS_KEY), dict) else {}
    if entry is None:
        statuses.pop(qid, None)
    else:
        statuses[qid] = entry
    return statuses


# ── Answers ──────────────────────────────────────────────────────────────────

def answer_text(q: Question, value: Any) -> str:
    """The typed answer as the producer door takes it."""
    if isinstance(value, list):
        return ", ".join(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value if value is not None else "").strip()


def answer_refusal(q: Question, text: str) -> Optional[str]:
    """Refusals the producer door does not know about (Brent's own rules)."""
    if q.fact == "period_of_restoration" and _EPI_RE.search(text or ""):
        return ("An Extended Period of Indemnity is not a Period of Restoration - enter the Period of "
                "Restoration the policy states, or mark it Unknown.")
    if q.secure and "*" in (text or ""):
        return "Choose one of the values, or type the whole number."
    return None


def merged_table_rows(q: Question, session: dict, typed_rows: List[dict]) -> List[dict]:
    """The rows to save, each laid over its building's FULL stored row (by row
    id). A per-building VIEW (G.1a-G.4a) copies only its OWN columns: the page
    may hold another view's older copy of the same rows, and its stale cells
    must never overwrite what that other view saved (review of 23 Oct). A whole
    table copies every typed cell; a new row (no stored id) is kept whole."""
    from services.schedule_capture import ROW_ID_KEY, rows_from_facts
    facts = session.get("facts") if isinstance(session.get("facts"), dict) else {}
    stored_rows = rows_from_facts(q.table, facts)
    current = {str(r.get(ROW_ID_KEY)): r for r in stored_rows if r.get(ROW_ID_KEY)}
    # A row first served before the table was ever saved carries its POSITION
    # ("#1"); the save gives it its own id ("L2"). A view still holding the
    # older copy names the same row by that position.
    by_position = {f"#{i}": r for i, r in enumerate(stored_rows)}
    out: List[dict] = []
    for row in typed_rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get(ROW_ID_KEY) or "")
        stored = (current.get(rid) or by_position.get(rid)) if rid else None
        if stored is None:
            out.append(dict(row))
            continue
        base = dict(stored)
        for k in (q.columns or tuple(row)):
            if k in row and k != ROW_ID_KEY:
                base[k] = row[k]
        out.append(base)
    return out


def view_rows(q: Question, rows: List[dict]) -> List[dict]:
    """A view's rows as the view shows them (its own columns only)."""
    if not q.columns:
        return list(rows or [])
    return [{k: r.get(k) for k in q.columns} for r in rows or [] if isinstance(r, dict)]


def view_confirmation_key(q: Question) -> str:
    """Where one VIEW's confirmation is kept (`confirm_known.CONFIRMATIONS_KEY`):
    "Looks right" on the year-built view confirms that view's columns, never
    the whole location table."""
    return f"schedule::{q.table}@{q.id}"


def record_view_confirmation(facts: dict, q: Question, rows: List[dict], at_iso: str,
                             by: str = "producer") -> None:
    from services import confirm_known
    shown = view_rows(q, rows)
    conf = dict(facts.get(confirm_known.CONFIRMATIONS_KEY) or {})
    conf[view_confirmation_key(q)] = {"at": at_iso, "by": by, "rows": len(shown),
                                     "signature": confirm_known.rows_signature(shown)}
    facts[confirm_known.CONFIRMATIONS_KEY] = conf


# ── Send to client (the ARQ door) ────────────────────────────────────────────

_ARQ_FIELD_TYPE = {"text": "text", "long_text": "text", "choice": "select", "yes_no": "select",
                   "number": "number", "currency": "currency", "date": "date", "table": "schedule"}


def arq_questions(session: dict, question_ids: Iterable[str]) -> List[dict]:
    """The insured-confirmable questions as ARQ questions for
    `arq_routes.send_questions_to_client` - which rebuilds every confirm value
    and table spec from the session itself, never from this list."""
    from services.fact_registry import FACT_REGISTRY
    page = _Page(session)
    out: List[dict] = []
    seen: set = set()
    for qid in question_ids or []:
        q = question(qid)
        if q is None or not q.insured or q.secure or q.computed:
            continue
        rendered = render(q, page)
        if q.table:
            key = f"schedule::{q.table}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"field_name": key, "field_type": "schedule", "schedule_key": q.table,
                        "question": q.text, "current_rows": rendered["value"] or [],
                        "form_ids": [], "forms": "", "audience": "client", "bucket": "client",
                        "topic_group": "narrative", "topic_label": "Submission questionnaire"})
            continue
        if q.fact in seen:
            continue
        seen.add(q.fact)
        entry = {
            "field_name": q.fact,
            "question": (FACT_REGISTRY.get(q.fact) or {}).get("question") or q.text,
            "hint": q.group if q.group and q.group != q.text else "",
            "field_type": _ARQ_FIELD_TYPE.get(q.answer_type, "text"),
            "form_ids": [], "forms": "",
            "audience": "client", "bucket": "client", "priority": "optional",
            "topic_group": "narrative", "topic_label": "Submission questionnaire",
            # Confirm-or-correct for a value the documents verify; the send door
            # shows it only while `confirm_known` still finds it source verified.
            "confirm": rendered["state"] in (EXTRACTED, PRODUCER_CONFIRMED),
        }
        opts = _options(q)
        if opts:
            entry["options"] = opts
        out.append(entry)
    return out


# ── The carrier narrative (improving-ll.md C110) ─────────────────────────────

def narrative_enabled() -> bool:
    return os.getenv("CARRIER_NARRATIVE", "1").strip().lower() not in ("0", "false", "no", "off")


def narrative_evidence(page_out: dict) -> List[dict]:
    """The answers a carrier narrative may be written from: extracted or
    confirmed (by the producer or the insured), never conflicting / unverified /
    unknown / pending / missing; never the FEIN, never the questionnaire's own
    open-items list."""
    out: List[dict] = []
    for sec in page_out.get("sections") or []:
        for q in sec.get("questions") or []:
            if q.get("computed") and q.get("id") != "H.1c":
                continue
            if q.get("state") not in NARRATIVE_STATES or q.get("fact") == "fein":
                continue
            shown = str(q.get("display_value") or "").strip()
            if not shown:
                continue
            out.append({"id": q["id"], "section": sec.get("title"), "question": q["text"],
                        "answer": shown[:800], "state": q["state"]})
    return out


_NARRATIVE_SYSTEM = (
    "You write the carrier-facing narrative for a commercial insurance submission, for an underwriter. "
    "Write ONLY from the numbered answers given - every fact, name, number and date must come from them. "
    "Never add, infer, estimate or embellish anything they do not state, and never mention a topic they "
    "do not cover. Plain, factual, professional prose; no marketing language. Length: one to two pages "
    "(about 400 to 900 words). Organise it under short headings such as Account Overview, Operations, "
    "Exposures, Loss History and Risk Management, Coverage Requested - only the ones the answers support. "
    "After each section list the answer ids it uses. Reply with JSON only: "
    "{\"sections\": [{\"heading\": \"...\", \"text\": \"...\", \"cites\": [\"A.1a\", ...]}]}"
)

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")
_MAX_NARRATIVE_CHARS = 9000


def _numbers(text: str) -> set:
    out = set()
    for m in _NUMBER_RE.finditer(str(text or "")):
        digits = m.group(0).replace(",", "")
        digits = re.sub(r"\.0+$", "", digits)
        if digits:
            out.add(digits)
    return out


def gate_narrative(reply: Any, evidence: List[dict]) -> Tuple[Optional[str], dict]:
    """(the narrative text, a report) from the model's reply - EVIDENCE-GATED:
    a section with no valid citation is dropped, and so is any sentence holding
    a number no answer states (an invented amount, year or count can never
    reach the page). None when nothing survives."""
    ids = {e["id"] for e in evidence}
    allowed = set()
    for e in evidence:
        allowed |= _numbers(e["answer"])
    report = {"sections_in": 0, "sections_kept": 0, "sentences_dropped": 0}
    sections = reply.get("sections") if isinstance(reply, dict) else None
    if not isinstance(sections, list):
        return None, report
    parts: List[str] = []
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        report["sections_in"] += 1
        cites = [c for c in (sec.get("cites") or []) if isinstance(c, str) and c.strip() in ids]
        text = re.sub(r"\s+", " ", str(sec.get("text") or "")).strip()
        if not cites or not text:
            continue
        kept = []
        for sentence in _SENTENCE_RE.split(text):
            if _numbers(sentence) - allowed:
                report["sentences_dropped"] += 1
                continue
            kept.append(sentence.strip())
        body = " ".join(s for s in kept if s)
        if not body:
            continue
        heading = re.sub(r"\s+", " ", str(sec.get("heading") or "")).strip().upper()[:80]
        if _numbers(heading) - allowed:
            # A heading is printed too: an invented figure in it ("LOSS FREE
            # SINCE 2015 - 12 YEARS") drops its whole section.
            report["headings_dropped"] = report.get("headings_dropped", 0) + 1
            continue
        heading = heading.replace("—", "-")
        parts.append(f"{heading}\n{body}" if heading else body)
        report["sections_kept"] += 1
    if not parts:
        return None, report
    return "\n\n".join(parts)[:_MAX_NARRATIVE_CHARS].replace("—", "-"), report


async def write_narrative(evidence: List[dict]) -> Tuple[Optional[str], dict]:
    """ONE model call (C110): the evidence in, the gated narrative out.
    (None, report) when switched off, when there is nothing to write from, or
    when the call or its reply fails - never a partial guess."""
    if not narrative_enabled():
        return None, {"reason": "off"}
    if not evidence:
        return None, {"reason": "no_evidence"}
    listing = "\n".join(f"[{e['id']}] ({e['section']}) {e['question']}: {e['answer']}" for e in evidence)
    try:
        from config.settings import LLM_MODEL, groq_chat
        raw = await groq_chat(
            LLM_MODEL,
            [{"role": "system", "content": _NARRATIVE_SYSTEM},
             {"role": "user", "content": f"ANSWERS:\n{listing[:40000]}"}],
            temperature=0, max_tokens=3000, _retries=1,
        )
        m = re.search(r"\{.*\}", raw or "", re.S)
        reply = json.loads(m.group(0)) if m else None
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("carrier narrative: no draft (%s)", exc)
        return None, {"reason": "call_failed"}
    text, report = gate_narrative(reply, evidence)
    if text is None:
        report["reason"] = "nothing_survived"
    return text, report


def load_narrative(session: dict) -> dict:
    raw = (session or {}).get(NARRATIVE_KEY)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        from utils.crypto import decrypt_field
        data = json.loads(decrypt_field(raw))
        return data if isinstance(data, dict) else {}
    except Exception as exc:                                   # noqa: BLE001
        logger.warning("carrier narrative unreadable (%s) - treated as none", exc)
        return {}


def dump_narrative(blob: dict) -> str:
    from utils.crypto import encrypt_field
    return encrypt_field(json.dumps(blob or {}, default=str))


def narrative_summary(session: dict) -> dict:
    """The contract's `narrative`: none / draft / approved. A draft newer than
    the approval is shown as the draft; the approved text keeps printing."""
    blob = load_narrative(session)
    draft, approved = blob.get("draft"), blob.get("approved")
    if draft:
        state, text = "draft", draft
    elif approved:
        state, text = "approved", approved
    else:
        state, text = "none", None
    return {"state": state, "text": text, "approved_at": blob.get("approved_at") if approved else None,
            "drafted_at": blob.get("drafted_at") if draft else None,
            "approved_text": approved or None}
