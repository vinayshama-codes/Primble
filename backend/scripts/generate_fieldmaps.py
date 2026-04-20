"""
generate_fieldmaps.py
---------------------
Pre-seed field→fact_key maps for ALL supported ACORD form schemas.

Run once (or after adding new PDF templates or new deterministic rules):
    py -3 backend/scripts/generate_fieldmaps.py

After this, map_facts_to_form() in pdf_service.py makes 0 LLM calls for
these forms on all subsequent runs — every field either hits the disk cache
or is resolved by _deterministic_map() without touching Groq.

Design rules:
  - RULES is the canonical superset of _ACORD_FIELD_RULES in pdf_service.py.
    They must be kept in sync. If you add a rule in pdf_service, add it here too.
  - Unmatched fields are saved as null so the runtime skips them (no LLM call).
  - Existing manual review edits in a fieldmap are never overwritten.
  - Run idempotently — safe to re-run at any time.
"""

import json
import os
import sys

# ---------------------------------------------------------------------------
# Canonical field→fact_key rules
# Must be an exact superset of _ACORD_FIELD_RULES in pdf_service.py.
# ---------------------------------------------------------------------------
RULES = [
    # ── Producer ─────────────────────────────────────────────────────────────
    ("Producer_FullName",                                   "producer_name"),
    ("Producer_CustomerIdentifier",                         "producer_name"),
    ("Producer_ContactPerson_FullName",                     "contact_name"),
    ("Producer_ContactPerson_Phone",                        "contact_phone"),
    ("Producer_ContactPerson_Email",                        "contact_email"),
    ("Producer_MailingAddress_LineOne",                     "_addr_line1"),
    ("Producer_MailingAddress_LineTwo",                     "_addr_line2"),
    ("Producer_MailingAddress_CityName",                    "_addr_city"),
    ("Producer_MailingAddress_StateOrProv",                 "_addr_state"),
    ("Producer_MailingAddress_PostalCode",                  "_addr_zip"),
    ("Producer_FaxNumber",                                  None),
    ("Producer_AuthorizedRepresentative",                   None),

    # ── Named insured ────────────────────────────────────────────────────────
    ("NamedInsured_FullName",                               "applicant_name"),
    ("NamedInsured_DBAName",                                "dba_name"),
    ("NamedInsured_TradeName",                              "dba_name"),
    ("NamedInsured_FEIN",                                   "fein"),
    ("NamedInsured_TaxIdentifier",                          "fein"),
    ("NamedInsured_EntityType",                             "entity_type"),
    ("NamedInsured_BusinessEntity",                         "entity_type"),
    ("NamedInsured_YearsInBusiness",                        "years_in_business"),
    ("NamedInsured_BusinessDescription",                    "operations_description"),
    ("NamedInsured_OperationsDescription",                  "operations_description"),
    ("NamedInsured_SICCode",                                "sic_code"),
    ("NamedInsured_NAICSCode",                              "naics_code"),
    ("NamedInsured_MailingAddress_LineOne",                 "_addr_line1"),
    ("NamedInsured_MailingAddress_LineTwo",                 "_addr_line2"),
    ("NamedInsured_MailingAddress_CityName",                "_addr_city"),
    ("NamedInsured_MailingAddress_StateOrProv",             "_addr_state"),
    ("NamedInsured_MailingAddress_PostalCode",              "_addr_zip"),
    ("NamedInsured_PhysicalAddress_LineOne",                "_loc_line1"),
    ("NamedInsured_PhysicalAddress_LineTwo",                "_loc_line2"),
    ("NamedInsured_PhysicalAddress_CityName",               "_loc_city"),
    ("NamedInsured_PhysicalAddress_StateOrProv",            "_loc_state"),
    ("NamedInsured_PhysicalAddress_PostalCode",             "_loc_zip"),

    # ── Policy / form header ─────────────────────────────────────────────────
    ("Policy_PolicyNumberIdentifier",                       "policy_number"),
    ("Policy_EffectiveDate",                                "effective_date"),
    ("Policy_ExpirationDate",                               "expiration_date"),
    ("Policy_GeneralLiability_PolicyNumberIdentifier",      "policy_number"),
    ("Policy_GeneralLiability_EffectiveDate",               "effective_date"),
    ("Policy_GeneralLiability_ExpirationDate",              "expiration_date"),
    ("Policy_AutomobileLiability_PolicyNumberIdentifier",   "policy_number"),
    ("Policy_AutomobileLiability_EffectiveDate",            "effective_date"),
    ("Policy_AutomobileLiability_ExpirationDate",           "expiration_date"),
    ("Policy_ExcessLiability_PolicyNumberIdentifier",       "policy_number"),
    ("Policy_ExcessLiability_EffectiveDate",                "effective_date"),
    ("Policy_ExcessLiability_ExpirationDate",               "expiration_date"),
    ("Policy_WorkersCompensation",                          "policy_number"),
    ("OtherPolicy_PolicyNumberIdentifier",                  "policy_number"),
    ("OtherPolicy_PolicyEffectiveDate",                     "effective_date"),
    ("OtherPolicy_PolicyExpirationDate",                    "expiration_date"),
    ("Form_CompletionDate",                                 "effective_date"),
    ("Form_EditionIdentifier",                              None),
    ("CertificateOfInsurance_CertificateNumberIdentifier",  "policy_number"),
    ("CertificateOfInsurance_RevisionNumber",               None),

    # ── Insurer ──────────────────────────────────────────────────────────────
    ("Insurer_FullName",                                    "prior_carrier"),
    ("Insurer_NAICCode",                                    "naics_code"),
    ("_InsurerLetterCode",                                  None),

    # ── General Liability ─────────────────────────────────────────────────────
    ("GeneralLiability_EachOccurrence_LimitAmount",         "gl_each_occurrence"),
    ("GeneralLiability_EachOccurrence",                     "gl_each_occurrence"),
    ("EachOccurrence",                                      "gl_each_occurrence"),
    ("GeneralLiability_GeneralAggregate_LimitAmount",       "gl_aggregate"),
    ("GeneralLiability_GeneralAggregate",                   "gl_aggregate"),
    ("GeneralLiability_Aggregate",                          "gl_aggregate"),
    ("GeneralAggregate",                                    "gl_aggregate"),
    ("GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount", "gl_aggregate"),
    ("GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount", "gl_limits"),
    ("GeneralLiability_MedicalExpense_EachPersonLimitAmount",     "gl_limits"),
    ("GeneralLiability_OtherCoverageLimitAmount",           "gl_deductible"),
    ("GeneralLiability_PropertyDamage_DeductibleAmount",    "gl_deductible"),
    ("GeneralLiability_BodilyInjury_DeductibleAmount",      "gl_deductible"),
    ("GeneralLiability_OtherDeductibleAmount",              "gl_deductible"),
    ("GeneralLiability_ClaimsMadeIndicator",                "gl_form_type"),
    ("GeneralLiability_OccurrenceIndicator",                "gl_form_type"),
    ("GeneralLiability_ClaimsMade_ProposedRetroactiveDate", "retro_date"),
    ("GeneralLiability_RetroactiveDate",                    "retro_date"),
    ("GeneralLiability_EmployeeBenefits_EmployeeCount",     "num_employees"),
    ("GeneralLiability_CoverageIndicator",                  None),
    ("GeneralLiability_OwnersAndContractors",               None),
    ("GeneralLiability_OtherCoverageIndicator",             None),
    ("GeneralLiability_OtherCoverageDescription",           None),
    ("GeneralLiability_DeductiblePerClaim",                 None),
    ("GeneralLiability_DeductiblePerOccurrence",            None),
    ("GeneralLiability_UninsuredUnderinsured",              None),
    ("GeneralLiability_MedicalPayments_Coverage",           None),
    ("GeneralLiabilityLineOfBusiness_Question_",            None),
    ("GeneralLiabilityLineOfBusiness_Attachment_",          None),
    ("GeneralLiabilityLineOfBusiness_Total",                None),
    ("GeneralLiabilityLineOfBusiness_RemarkText",           None),
    ("GeneralLiabilityLineOfBusiness_TypeOfWork",           None),
    ("GeneralLiability_Hazard_Location",                    None),
    ("GeneralLiability_Hazard_Hazard",                      None),
    ("GeneralLiability_Hazard_PremiumBasis",                None),
    ("GeneralLiability_Hazard_Territory",                   None),
    ("GeneralLiability_Hazard_PremisesOperationsRate",      None),
    ("GeneralLiability_Hazard_ProductsRate",                None),
    ("GeneralLiability_Hazard_PremisesOperationsPremium",   None),
    ("GeneralLiability_Hazard_ProductsPremium",             None),
    ("GeneralLiability_Hazard_Exposure",                    None),
    ("GeneralLiability_Hazard_ClassCode",                   None),
    ("GeneralLiability_Hazard_Classification",              None),
    ("GeneralLiability_PremisesOperations_Premium",         None),
    ("GeneralLiability_Products_Premium",                   None),
    ("GeneralLiability_OtherCoveragePremium",               None),
    ("GeneralLiability_PropertyDamage_DeductibleIndicator", None),
    ("GeneralLiability_BodilyInjury_DeductibleIndicator",   None),
    ("GeneralLiability_OtherDeductibleIndicator",           None),
    ("GeneralLiability_GeneralAggregate_LimitApplies",      None),
    ("GeneralLiability_UninsuredUnderinsuredMotorists",     None),
    ("GeneralLiability_EmployeeBenefits_PerClaim",          None),
    ("GeneralLiability_EmployeeBenefits_EmployeeCovered",   None),
    ("GeneralLiability_EmployeeBenefits_Retroactive",       None),
    ("GeneralLiability_EmployeeBenefits_LimitAmount",       None),
    ("GeneralLiability_Otherlodging",                       None),

    # ── Commercial Property ───────────────────────────────────────────────────
    ("CommercialProperty_Premises_LimitAmount",             "property_building_value"),
    ("CommercialProperty_Premises_CoinsurancePercent",      "coinsurance_percentage"),
    ("CommercialProperty_Premises_ValuationCode",           "valuation_method"),
    ("CommercialProperty_Premises_DeductibleAmount",        "property_deductible_aop"),
    ("CommercialProperty_Premises_DeductibleTypeCode",      None),
    ("CommercialProperty_Premises_SubjectOfInsuranceCode",  None),
    ("CommercialProperty_Premises_CauseOfLossCode",         None),
    ("CommercialProperty_Premises_InflationGuardPercent",   None),
    ("CommercialProperty_Premises_BlanketNumber",           None),
    ("CommercialProperty_Premises_FormsAndConditions",      None),
    ("CommercialProperty_Premises_RemarkText",              None),
    ("CommercialProperty_Premises_Breakdown",               None),
    ("CommercialProperty_Premises_PowerOutage",             None),
    ("CommercialProperty_Premises_SellingPrice",            None),
    ("CommercialProperty_Premises_OtherIndicator",          None),
    ("CommercialProperty_Premises_OptionsDescription",      None),
    ("CommercialProperty_Summary_BlanketNumber",            None),
    ("CommercialProperty_Summary_BlanketLimit",             None),
    ("CommercialCoverage_Summary_BlanketType",              None),
    ("CommercialProperty_Spoilage_",                        None),
    ("CommercialProperty_Attachment_",                      None),
    ("CommercialPropertyCoverage_SinkHole",                 None),
    ("CommercialPropertyCoverage_MineSubsidence",           None),

    # ── BPP ──────────────────────────────────────────────────────────────────
    ("CommercialProperty_BPP_LimitAmount",                  "property_bpp_value"),
    ("BusinessPersonalProperty_LimitAmount",                "property_bpp_value"),
    ("BPP_LimitAmount",                                     "property_bpp_value"),

    # ── Business Income ───────────────────────────────────────────────────────
    ("BusinessIncome_LimitAmount",                          "business_income_limit"),
    ("BusinessIncome_Limit",                                "business_income_limit"),
    ("BusinessIncome_PeriodOfRestoration",                  "period_of_restoration"),
    ("BusinessIncome_Period",                               "period_of_restoration"),
    ("ExtraExpense_LimitAmount",                            "extra_expense_limit"),
    ("ExtraExpense_Limit",                                  "extra_expense_limit"),

    # ── Peril deductibles ────────────────────────────────────────────────────
    ("Deductible_WindHail",                                 "property_deductible_wind"),
    ("Deductible_Wind",                                     "property_deductible_wind"),
    ("Deductible_Hail",                                     "property_deductible_wind"),
    ("Deductible_Earthquake",                               "property_deductible_earthquake"),
    ("Deductible_Flood",                                    "property_deductible_flood"),
    ("Deductible_AOP",                                      "property_deductible_aop"),
    ("Deductible_AllOtherPerils",                           "property_deductible_aop"),
    ("Deductible_Basis",                                    "deductible_basis"),
    ("Deductible_Application",                              "deductible_application"),
    ("AgreedValue_Endorsement",                             "agreed_value_endorsement"),
    ("AgreedValue_Indicator",                               "agreed_value_endorsement"),

    # ── Commercial Structure ──────────────────────────────────────────────────
    ("CommercialStructure_BuiltYear",                       "year_built"),
    ("CommercialStructure_YearBuilt",                       "year_built"),
    ("CommercialStructure_Roof_Year",                       "roof_year"),
    ("CommercialStructure_Construction_TypeCode",           "construction_type"),
    ("CommercialStructure_Occupancy",                       "occupancy_type"),
    ("CommercialStructure_PhysicalAddress_LineOne",         "_loc_line1"),
    ("CommercialStructure_PhysicalAddress_LineTwo",         "_loc_line2"),
    ("CommercialStructure_PhysicalAddress_CityName",        "_loc_city"),
    ("CommercialStructure_PhysicalAddress_StateOrProv",     "_loc_state"),
    ("CommercialStructure_PhysicalAddress_PostalCode",      "_loc_zip"),
    ("CommercialStructure_Location_ProducerIdentifier",     None),
    ("CommercialStructure_Building_ProducerIdentifier",     None),
    ("CommercialStructure_Building_Sublocation",            None),
    ("CommercialStructure_TaxCode",                         None),
    ("CommercialStructure_WindClass_",                      None),
    ("CommercialStructure_PrimaryHeat_",                    None),
    ("CommercialStructure_SecondaryHeat_",                  None),
    ("CommercialStructure_HeatingBoiler",                   None),
    ("Construction_ConstructionCode",                       "construction_type"),
    ("Construction_OpenSidesCount",                         None),
    ("Construction_StoreyCount",                            None),
    ("Construction_BasementCount",                          None),
    ("Construction_BuildingArea",                           None),
    ("Construction_BuildingCodeEffectiveness",              None),
    ("Construction_RoofMaterialCode",                       None),

    # ── Building fire protection ──────────────────────────────────────────────
    ("BuildingFireProtection_HydrantDistanceFeetCount",     "distance_to_hydrant"),
    ("BuildingFireProtection_FireStationDistanceMile",      None),
    ("BuildingFireProtection_FireDistrictName",             "fire_department_type"),
    ("BuildingFireProtection_FireDistrictCode",             None),
    ("BuildingFireProtection_ProtectionClassCode",          "fire_protection_class"),
    ("BuildingFireProtection_Alarm_SprinklerPercent",       "sprinkler_system"),
    ("BuildingFireProtection_Alarm_ManufacturerName",       None),
    ("BuildingFireProtection_Alarm_CentralStation",         None),
    ("BuildingFireProtection_Alarm_LocalGong",              None),
    ("BuildingFireProtection_Alarm_ProtectionDescription",  None),
    ("BuildingImprovement_WiringYear",                      None),
    ("BuildingImprovement_WiringIndicator",                 None),
    ("BuildingImprovement_RoofingYear",                     "roof_year"),
    ("BuildingImprovement_RoofingIndicator",                None),
    ("BuildingImprovement_PlumbingYear",                    None),
    ("BuildingImprovement_PlumbingIndicator",               None),
    ("BuildingImprovement_HeatingYear",                     None),
    ("BuildingImprovement_HeatingIndicator",                None),
    ("BuildingImprovement_OtherYear",                       None),
    ("BuildingImprovement_OtherIndicator",                  None),
    ("BuildingImprovement_OtherDescription",                None),
    ("BuildingFeatures_HistoricalProperty",                 None),
    ("BuildingFeatures_SolidFuel",                          None),
    ("BuildingOccupancy_OtherOccupancies",                  None),
    ("BuildingOccupancy_Apartment",                         None),
    ("BuildingExposure_",                                   None),
    ("BuildingSecurity_",                                   None),

    # ── ITV / Coinsurance ─────────────────────────────────────────────────────
    ("Building_ITV_Percentage",                             "building_ITV_percentage"),
    ("ITV_Percentage",                                      "building_ITV_percentage"),
    ("Coinsurance_Percentage",                              "coinsurance_percentage"),
    ("Valuation_Method",                                    "valuation_method"),
    ("Valuation_Code",                                      "valuation_method"),

    # ── Additional interest / mortgagee ──────────────────────────────────────
    ("AdditionalInterest_FullName",                         "additional_named_insureds"),
    ("AdditionalInterest_MailingAddress_LineOne",           "_addr_line1"),
    ("AdditionalInterest_MailingAddress_LineTwo",           "_addr_line2"),
    ("AdditionalInterest_MailingAddress_CityName",          "_addr_city"),
    ("AdditionalInterest_MailingAddress_StateOrProv",       "_addr_state"),
    ("AdditionalInterest_MailingAddress_PostalCode",        "_addr_zip"),
    ("AdditionalInterest_MailingAddress_CountryCode",       None),
    ("AdditionalInterest_AccountNumber",                    None),
    ("AdditionalInterest_Interest_Mortgagee",               None),
    ("AdditionalInterest_Interest_LossPayee",               None),
    ("AdditionalInterest_Interest_LendersLoss",             None),
    ("AdditionalInterest_Interest_AdditionalInsured",       None),
    ("AdditionalInterest_Interest_Lienholder",              None),
    ("AdditionalInterest_Interest_Employee",                None),
    ("AdditionalInterest_Interest_Other",                   None),
    ("AdditionalInterest_InterestRank",                     None),
    ("AdditionalInterest_CertificateRequired",              None),
    ("AdditionalInterest_Item_",                            None),
    ("AdditionalInterest_ItemDescription",                  None),
    ("Mortgagee_FullName",                                  "mortgagee_name"),
    ("Mortgagee_Name",                                      "mortgagee_name"),

    # ── Certificate holder ───────────────────────────────────────────────────
    ("CertificateHolder_FullName",                          "certificate_holder"),
    ("CertificateHolder_MailingAddress_LineOne",            "_addr_line1"),
    ("CertificateHolder_MailingAddress_LineTwo",            "_addr_line2"),
    ("CertificateHolder_MailingAddress_CityName",           "_addr_city"),
    ("CertificateHolder_MailingAddress_StateOrProv",        "_addr_state"),
    ("CertificateHolder_MailingAddress_PostalCode",         "_addr_zip"),

    # ── Auto ─────────────────────────────────────────────────────────────────
    ("AutoLiability_CombinedSingleLimit",                   "auto_liability_limit"),
    ("Vehicle_CombinedSingleLimit",                         "auto_liability_limit"),
    ("Vehicle_BodilyInjury_PerPerson",                      "auto_liability_limit"),
    ("Vehicle_BodilyInjury_PerAccident",                    "auto_liability_limit"),
    ("Vehicle_PropertyDamage_PerAccident",                  "auto_liability_limit"),
    ("Vehicle_Deductible_Comprehensive",                    "auto_deductible_comp"),
    ("Vehicle_Deductible_Collision",                        "auto_deductible_collision"),
    ("Auto_LiabilityStructure",                             "auto_liability_structure"),
    ("Auto_CoveredSymbols",                                 "auto_covered_symbols"),
    ("Auto_RadiusOfOperation",                              "auto_radius_of_operation"),
    ("Auto_HiredNonOwned",                                  "auto_hired_nonowned"),
    ("Auto_UMUIM_Limit",                                    "auto_um_uim_limit"),
    ("Auto_MedPay_Limit",                                   "auto_med_pay_limit"),
    ("Vehicle_OtherCoverage_CoverageDescription",           None),
    ("Vehicle_OtherCoverage_LimitAmount",                   None),
    ("Vehicle_OtherCoveredAutoDescription",                 None),
    ("Vehicle_InsurerLetterCode",                           None),

    # ── Workers Comp ─────────────────────────────────────────────────────────
    ("WorkersCompensation_Payroll",                         "wc_payroll"),
    ("WorkersCompensation_ExperienceModification",          "wc_xmod"),
    ("WorkersCompensation_ExperienceMod",                   "wc_xmod"),
    ("WorkersCompensation_ClassCodes",                      "wc_class_codes"),
    ("WorkersCompensation_PayrollByState",                  "wc_payroll_by_state"),
    ("WorkersCompensation_PriorCarrier",                    "wc_prior_carrier"),
    ("WorkersCompensation_PayrollPeriod",                   "wc_payroll_period"),
    ("WorkersCompensation_OfficerExclusions",               "wc_officer_exclusions"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_EachAccident", "employers_liability_limits"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_Disease",      "employers_liability_limits"),
    ("WorkersCompensationEmployersLiability_OtherCoverage",                   None),
    ("WorkersCompensationEmployersLiability_InsurerLetterCode",               None),

    # ── Umbrella / Excess ────────────────────────────────────────────────────
    ("Umbrella_EachOccurrence",                             "umbrella_limit"),
    ("Umbrella_Aggregate",                                  "umbrella_limit"),
    ("Umbrella_SelfInsuredRetention",                       "umbrella_sir"),
    ("Umbrella_AttachmentPoint",                            "umbrella_attachment_point"),
    ("ExcessUmbrella_Umbrella_EachOccurrenceAmount",        "umbrella_limit"),
    ("ExcessUmbrella_Umbrella_AggregateAmount",             "umbrella_limit"),
    ("ExcessUmbrella_Umbrella_DeductibleOrRetentionAmount", "umbrella_sir"),
    ("ExcessUmbrella_OtherCoverageDescription",             None),
    ("ExcessUmbrella_OtherCoverageLimitAmount",             None),
    ("ExcessUmbrella_InsurerLetterCode",                    None),
    ("UnderlyingPolicies_",                                 "underlying_policies"),
    ("EmployersLiability_EachAccident",                     "employers_liability_limits"),
    ("EmployersLiability_Disease",                          "employers_liability_limits"),

    # ── Contractors ──────────────────────────────────────────────────────────
    ("Contractors_WorkSubcontractedPercent",                "percent_subcontracted"),
    ("Contractors_SubcontractorsPaidAmount",                "total_revenue"),
    ("Contractors_FullTimeEmployeeCount",                   "num_employees"),
    ("Contractors_PartTimeEmployeeCount",                   "num_employees"),
    ("Contractors_ContractorType",                          "contractor_type"),
    ("Contractors_Question_",                               None),
    ("ProductAndCompletedOperations_AnnualGrossSalesAmount","total_revenue"),
    ("ProductAndCompletedOperations_UnitCount",             None),
    ("ProductAndCompletedOperations_InMarketMonth",         None),
    ("ProductAndCompletedOperations_ExpectedLife",          None),
    ("ProductAndCompletedOperations_IntendedUse",           None),
    ("ProductAndCompletedOperations_PrincipalComponents",   None),
    ("ProductAndCompletedOperations_ProductName",           None),

    # ── Loss history ─────────────────────────────────────────────────────────
    ("LossHistory_NumClaims",                               "num_claims"),
    ("LossHistory_TotalIncurred",                           "total_incurred"),
    ("LossHistory_TotalPaid",                               "total_paid"),
    ("LossHistory_OpenClaims",                              "open_claims_count"),
    ("LossHistory_Years",                                   "loss_history_years"),
    ("PriorCarrier_FullName",                               "prior_carrier"),

    # ── Miscellaneous null fields ─────────────────────────────────────────────
    ("Alarm_Burglar_",                                      None),
    ("Burglar_LocalGong",                                   None),
    ("SwimmingPool_",                                       None),
    ("AthleticTeam_",                                       None),
    ("GeneralLiabilityLineOfBusiness_",                     None),
    ("CommercialInlandMarineProperty_",                     None),
    ("PropertyItem_ItemDetail_",                            None),
    ("OtherPolicy_InsurerLetterCode",                       None),
    ("OtherPolicy_OtherPolicyDescription",                  None),
    ("OtherPolicy_SubrogationWaived",                       None),
    ("OtherPolicy_CoverageCode",                            None),
    ("OtherPolicy_CoverageLimitAmount",                     None),
    ("CertificateOfLiabilityInsurance_",                    None),
    ("_RemarkText",                                         None),
    ("_Explanation",                                        None),
]


def apply_rules(field_name: str):
    """Return the fact_key for a PDF field name, or 'UNMATCHED' if no rule covers it."""
    for pattern, fact_key in RULES:
        if pattern in field_name:
            return fact_key
    return "UNMATCHED"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS_DB  = os.path.join(BASE, "forms_database")
FORMS_SCH = os.path.join(BASE, "forms_schemas")

# All ACORD forms with known templates — extend this list as new PDFs are added.
TARGET_FORMS = [
    "ACORD_125",
    "ACORD_126",
    "ACORD_127",
    "ACORD_130",
    "ACORD_131",
    "ACORD_140",
    "ACORD_141",
    "ACORD_25",
    "ACORD_28",
    "ACORD_101",
    "ACORD_133",
    "ACORD_137",
    "ACORD_138",
    "ACORD_160",
    "ACORD_186",
]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print(f"Base: {BASE}")
print(f"Schemas: {FORMS_SCH}")
print(f"Fieldmaps: {FORMS_DB}\n")

total_matched   = 0
total_unmatched = 0
total_skipped   = 0

for form_id in TARGET_FORMS:
    schema_path   = os.path.join(FORMS_SCH, f"{form_id}_schema.json")
    fieldmap_path = os.path.join(FORMS_DB,  f"ACORD_{form_id}_fieldmap.json")

    if not os.path.exists(schema_path):
        print(f"  {form_id}: schema not found at {schema_path} — skipping (add PDF template first)")
        total_skipped += 1
        continue

    with open(schema_path) as f:
        schema = json.load(f)

    if not schema:
        print(f"  {form_id}: empty schema — skipping")
        total_skipped += 1
        continue

    # Load existing fieldmap — never overwrite manual review edits.
    existing: dict = {}
    if os.path.exists(fieldmap_path):
        try:
            with open(fieldmap_path) as f:
                existing = json.load(f)
        except Exception as ex:
            print(f"  {form_id}: WARNING — could not read existing fieldmap: {ex}")

    fieldmap      = dict(existing)
    newly_matched = 0
    newly_null    = 0

    for field in schema:
        if field in fieldmap:
            continue   # already mapped — preserve existing value
        result = apply_rules(field)
        if result == "UNMATCHED":
            fieldmap[field] = None   # explicit null → runtime skips LLM
            newly_null     += 1
        else:
            fieldmap[field] = result
            newly_matched  += 1

    with open(fieldmap_path, "w") as f:
        json.dump(fieldmap, f, indent=2)

    total_fields  = len(schema)
    mapped_count  = sum(1 for v in fieldmap.values() if v is not None)
    null_count    = total_fields - mapped_count
    coverage_pct  = int(mapped_count / total_fields * 100) if total_fields else 0

    print(
        f"  {form_id}: {total_fields} fields | "
        f"{mapped_count} mapped ({coverage_pct}%) | "
        f"{null_count} explicit nulls | "
        f"+{newly_matched} new matches | "
        f"+{newly_null} new nulls | "
        f"→ {fieldmap_path}"
    )
    total_matched   += newly_matched
    total_unmatched += null_count

print(f"\nDone.  Newly matched: {total_matched}  |  Total explicit nulls: {total_unmatched}  |  Skipped: {total_skipped}")
print("Re-run after adding new PDF templates or new deterministic rules to update fieldmaps.")