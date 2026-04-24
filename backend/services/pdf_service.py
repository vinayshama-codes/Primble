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
from services.extraction_service import _fv

logger = logging.getLogger(__name__)

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
    ("Insurer_FullName",                                   "prior_carrier"),
    ("Insurer_NAICCode",                                   "naics_code"),
    ("_InsurerLetterCode",                                 None),

    # ── General liability ─────────────────────────────────────────────────────
    ("GeneralLiability_EachOccurrence_LimitAmount",        "gl_each_occurrence"),
    ("GeneralLiability_EachOccurrence",                    "gl_each_occurrence"),
    ("EachOccurrence",                                     "gl_each_occurrence"),
    ("GeneralLiability_GeneralAggregate_LimitAmount",      "gl_aggregate"),
    ("GeneralLiability_GeneralAggregate",                  "gl_aggregate"),
    ("GeneralLiability_Aggregate",                         "gl_aggregate"),
    ("GeneralAggregate",                                   "gl_aggregate"),
    ("GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount", "gl_aggregate"),
    ("GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount", "gl_limits"),
    ("GeneralLiability_MedicalExpense_EachPersonLimitAmount",     "gl_limits"),
    ("GeneralLiability_OtherCoverageLimitAmount",          "gl_deductible"),
    ("GeneralLiability_PropertyDamage_DeductibleAmount",   "gl_deductible"),
    ("GeneralLiability_BodilyInjury_DeductibleAmount",     "gl_deductible"),
    ("GeneralLiability_OtherDeductibleAmount",             "gl_deductible"),
    ("GeneralLiability_ClaimsMadeIndicator",               "gl_form_type"),
    ("GeneralLiability_OccurrenceIndicator",               "gl_form_type"),
    ("GeneralLiability_ClaimsMade_ProposedRetroactiveDate","retro_date"),
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
    ("WorkersCompensationEmployersLiability_EmployersLiability_EachAccident", "employers_liability_limits"),
    ("WorkersCompensationEmployersLiability_EmployersLiability_Disease",      "employers_liability_limits"),
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
    YELLOW = pikepdf.Array([pikepdf.Real(1.0), pikepdf.Real(1.0), pikepdf.Real(0.0)])
    PINK   = pikepdf.Array([pikepdf.Real(1.0), pikepdf.Real(0.71), pikepdf.Real(0.76)])
    WHITE  = pikepdf.Array([pikepdf.Real(1.0), pikepdf.Real(1.0), pikepdf.Real(1.0)])
    for item in arr:
        try:
            t    = item.get("/T", None)
            kids = item.get("/Kids", None)
            if t:
                name = str(t)
                val  = data.get(name)
                conf = confidence.get(name, "low_confidence")
                if val is not None and str(val).strip() not in ("", "null", "None"):
                    item["/V"] = pikepdf.String(str(val))
                    if "/AP" in item:
                        del item["/AP"]
                    counter[0] += 1
                if conf == "filled":
                    item["/MK"] = pikepdf.Dictionary(**{"/BG": WHITE})
                elif conf == "missing_required":
                    item["/MK"] = pikepdf.Dictionary(**{"/BG": YELLOW})
                else:
                    item["/MK"] = pikepdf.Dictionary(**{"/BG": PINK})
            if kids:
                _fill_and_highlight(kids, data, confidence, counter)
        except Exception:
            pass


def fill_pdf(template_path: str, data: dict, confidence: Optional[dict] = None) -> bytes:
    try:
        pdf = pikepdf.open(template_path)
        if "/AcroForm" in pdf.Root:
            acro = pdf.Root["/AcroForm"]
            acro["/NeedAppearances"] = pikepdf.Boolean(True)
            counter = [0]
            _fill_and_highlight(acro.get("/Fields", []), data, confidence or {}, counter)
            logger.info(f"fill_pdf: wrote {counter[0]} field values")
        buf = io.BytesIO()
        pdf.save(buf)
        pdf.close()
        buf.seek(0)
        return buf.getvalue()
    except Exception as ex:
        logger.error(f"fill_pdf error: {ex}")
        with open(template_path, "rb") as f:
            return f.read()


def _load_fieldmap(form_id: str) -> dict:
    """Load persisted {field_name: fact_key} map for this form template, if it exists."""
    if not form_id:
        return {}
    path = os.path.join(FORMS_DB_DIR, f"ACORD_{form_id}_fieldmap.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_fieldmap(form_id: str, fieldmap: dict):
    """Persist {field_name: fact_key} map so future runs skip the LLM for known fields."""
    if not form_id or not fieldmap:
        return
    path = os.path.join(FORMS_DB_DIR, f"ACORD_{form_id}_fieldmap.json")
    try:
        with open(path, "w") as f:
            json.dump(fieldmap, f, indent=2)
    except Exception as ex:
        logger.warning(f"Could not save fieldmap for {form_id}: {ex}")


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


# Valid fact key set — used to validate LLM-returned keys.
_VALID_FACT_KEYS: set = set()  # populated lazily on first map_facts_to_form call
_SPECIAL_PREFIXES = {"_addr", "_loc"}


def _deterministic_map(field_name: str, facts: dict):
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
                return str(val[0]) if val else None
            return str(val) if val is not None else None
    return "UNMATCHED"


def _apply_fact_key(fact_key: str, facts: dict):
    """Resolve a cached/LLM-returned fact_key to a scalar string value."""
    if fact_key is None:
        return None
    if fact_key.startswith("_"):
        return _resolve_special(fact_key, facts, "_" + fact_key.split("_")[1]) or None
    val = _fv(facts, fact_key)
    if isinstance(val, list):
        return str(val[0]) if val else None
    return str(val) if val is not None else None


def map_facts_to_form(facts: dict, schema: dict, form_id: str = "") -> Tuple[dict, dict]:
    if not schema:
        return {}, {}

    BATCH      = 80
    mapped     = {}
    unmatched  = {}
    confidence = {}

    # Build valid fact-key set for LLM response validation (lazy, one-time).
    global _VALID_FACT_KEYS
    if not _VALID_FACT_KEYS:
        _VALID_FACT_KEYS = set(facts.keys()) | {
            "_addr_line1", "_addr_line2", "_addr_city", "_addr_state", "_addr_zip",
            "_loc_line1",  "_loc_line2",  "_loc_city",  "_loc_state",  "_loc_zip",
        }
    else:
        _VALID_FACT_KEYS.update(facts.keys())

    # Load persisted field→fact_key map built on previous runs for this form template.
    cached_fieldmap = _load_fieldmap(form_id)
    new_fieldmap    = dict(cached_fieldmap)

    for field in schema.keys():
        if field in cached_fieldmap:
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
        unmatched_keys = list(unmatched.keys())
        ai_mapped: dict = {}  # {field: fact_key_or_null}
        facts_plain = {k: _fv(facts, k) for k in facts}  # strip envelopes for LLM

        for batch_start in range(0, len(unmatched_keys), BATCH):
            batch_keys  = unmatched_keys[batch_start : batch_start + BATCH]
            batch_hints = []
            for k in batch_keys:
                info = unmatched[k] if isinstance(unmatched[k], dict) else {}
                tu   = info.get("tu", "")[:60] if info else ""
                batch_hints.append(k + (f"  # {tu}" if tu else ""))
            prompt = (
                "Map these PDF AcroForm field names to insurance fact keys.\n"
                "Return ONLY a JSON object: {\"FieldName\": \"fact_key_or_null\"}.\n"
                "Rules:\n"
                "  - Use null if no fact key applies.\n"
                "  - Use ONLY exact fact key names from the list below — do NOT invent keys.\n"
                "  - Prefer null over a wrong key.\n\n"
                f"Available fact keys:\n{json.dumps(list(facts_plain.keys()))}\n\n"
                f"Fields to map:\n{json.dumps(batch_hints)}\n\nOutput:"
            )
            try:
                raw = groq_chat("llama-3.1-8b-instant", [{"role": "user", "content": prompt}])
                if raw.startswith("```"):
                    raw = raw.replace("```json", "").replace("```", "").strip()
                s, e = raw.find("{"), raw.rfind("}")
                if s != -1 and e != -1:
                    ai_mapped.update(json.loads(raw[s : e + 1]))
            except Exception as ex:
                logger.warning(f"AI batch failed: {ex}")

        # Apply LLM results and always persist (even null) → 0 LLM calls on repeat runs.
        for field, fact_key in ai_mapped.items():
            # Validate key: reject hallucinated keys not in our known fact set.
            if fact_key is not None and fact_key not in _VALID_FACT_KEYS:
                logger.debug(f"LLM returned unknown fact key '{fact_key}' for {field} — treating as null")
                fact_key = None
            new_fieldmap[field] = fact_key   # always cache, even None
            mapped[field]       = _apply_fact_key(fact_key, facts)

        # Fields in unmatched that the LLM didn't return → save as null so we skip next run.
        for field in unmatched_keys:
            if field not in ai_mapped:
                new_fieldmap[field] = None
                mapped.setdefault(field, None)

        _save_fieldmap(form_id, new_fieldmap)

    elif new_fieldmap != cached_fieldmap:
        # Deterministic pass added new entries — persist them even with no LLM batch.
        _save_fieldmap(form_id, new_fieldmap)

    for field, meta in schema.items():
        val       = mapped.get(field)
        has_value = val is not None and str(val).strip() not in ("", "null", "None")
        is_req    = meta.get("required", False) if isinstance(meta, dict) else False
        was_ai    = field in unmatched and field in mapped and mapped[field] is not None
        if has_value:
            confidence[field] = "low_confidence" if was_ai else "filled"
        elif is_req:
            confidence[field] = "missing_required"
        else:
            confidence[field] = "low_confidence"

    total_filled = sum(1 for v in mapped.values() if v is not None and str(v).strip() not in ("", "null", "None"))
    logger.info(f"Mapped {total_filled}/{len(schema)} fields (form_id={form_id or 'unknown'})")
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