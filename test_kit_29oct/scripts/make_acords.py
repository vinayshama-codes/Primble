import sys
sys.path.insert(0, sys.argv[1])
from data import *
import pikepdf

TPL = "/Users/vinaysharma/Downloads/Primble-16thsep/backend/templates/"
OUT = "/Users/vinaysharma/Downloads/Primble-16thsep/test_kit_29oct/"
OTHER = dict(name="Bluestem Risk Advisors LLC", l1="320 E Mountain Ave", l2="Suite 4", city="Fort Collins", st="CO", zip="80524",
             contact="Jordan Pike", phone="(970) 555-0133", fax="(970) 555-0134", email="jpike@bluestemrisk.com")
# ---- planted inconsistencies (ACORD value vs dec value) ----
ACORD_SUITE = "Suite 210"            # dec: Suite 200
ACORD_START = "06/01/2012"           # dec: 03/15/2011
ACORD_PHONE = "(303) 555-0184"       # dec: (303) 555-0148
ACORD_REV = "$9,200,000"             # dec: $8,450,000
ACORD_FT, ACORD_PT = "58", "4"       # dec: 62 / 6
ACORD_NAICS = "238210"               # dec: 238220
ACORD_EFF, ACORD_EXP = "01/01/2027", "01/01/2028"   # dec renewal: 12/01/2026 - 12/01/2027
ACORD_BLDG2_AREA = "25,000"          # dec: 22,000 (Loc 1 Bldg 2)
ACORD_AUTO_CLAIM_PAID = "$14,820"    # loss run 04: $18,420 (05/17/2022 auto claim)
ACORD_VIN2 = "3C6LRVDG4NE118367"     # dec: 3C6LRVDG4NE118362 (last character 2 -> 7)
ACORD_DOB3 = "12/08/1991"            # dec: 12/03/1991 (Derek A. Nguyen)


def fill(form, values, out, label):
    pdf = pikepdf.open(TPL + form + ".pdf")
    fields = {str(f.T): f for f in pdf.Root.AcroForm.Fields}
    missing = [k for k in values if k not in fields]
    if missing:
        print(label, "MISSING", missing)
    used_pages = set()
    page_of = {}
    for i, pg in enumerate(pdf.pages):
        for a in pg.obj.get("/Annots", []):
            t = a.get("/T") or (a.get("/Parent") or {}).get("/T")
            if t is not None:
                page_of[str(t)] = i
    for k, v in values.items():
        f = fields.get(k)
        if f is None or v in (None, ""):
            continue
        if f.get("/FT") == "/Btn":
            f.V = pikepdf.Name("/1"); f.AS = pikepdf.Name("/1")
        else:
            f.V = pikepdf.String(str(v))
        used_pages.add(page_of.get(k, 0))
    pdf.Root.AcroForm.NeedAppearances = True
    pdf.generate_appearance_streams()
    pdf.flatten_annotations("all")
    if "/AcroForm" in pdf.Root:
        del pdf.Root["/AcroForm"]
    for i in sorted(set(range(len(pdf.pages))) - used_pages, reverse=True):
        del pdf.pages[i]
    for k in list(pdf.docinfo.keys()):
        del pdf.docinfo[k]
    pdf.docinfo["/Producer"] = OTHER["name"] + " agency management system"
    pdf.save(out, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    print(label, "filled", len([k for k in values if k in fields and values[k]]), "pages kept", sorted(p + 1 for p in used_pages))


def producer_block(v):
    v.update({"Producer_FullName_A": OTHER["name"], "Producer_MailingAddress_LineOne_A": OTHER["l1"], "Producer_MailingAddress_LineTwo_A": OTHER["l2"],
              "Producer_MailingAddress_CityName_A": OTHER["city"], "Producer_MailingAddress_StateOrProvinceCode_A": OTHER["st"],
              "Producer_MailingAddress_PostalCode_A": OTHER["zip"], "Producer_ContactPerson_FullName_A": OTHER["contact"],
              "Producer_ContactPerson_PhoneNumber_A": OTHER["phone"], "Producer_FaxNumber_A": OTHER["fax"],
              "Producer_ContactPerson_EmailAddress_A": OTHER["email"], "Producer_CustomerIdentifier_A": "RIDGE-0042",
              "Form_CompletionDate_A": "10/22/2026"})


# ======================= ACORD 125 =======================
v = {}
producer_block(v)
v.update({
    "Insurer_ProducerIdentifier_A": "BRA-118", "Policy_Status_QuoteIndicator_A": True,
    "Policy_Status_EffectiveDate_A": ACORD_EFF,
    "Policy_LineOfBusiness_CommercialGeneralLiability_A": True, "Policy_LineOfBusiness_BusinessAutoIndicator_A": True,
    "Policy_LineOfBusiness_CommercialProperty_A": True, "Policy_LineOfBusiness_UmbrellaIndicator_A": True,
    "Policy_LineOfBusiness_OtherIndicator_A": True, "Policy_LineOfBusiness_OtherLineOfBusinessDescription_A": "Workers Compensation (CO)",
    "CommercialPolicy_Attachment_ContractorsSupplementIndicator_A": True, "CommercialPolicy_Attachment_LossSummaryIndicator_A": True,
    "Policy_EffectiveDate_A": ACORD_EFF, "Policy_ExpirationDate_A": ACORD_EXP,
    "Policy_Payment_PaymentScheduleCode_A": "Quarterly", "Policy_PaymentMethod_MethodDescription_A": "Agency bill", "Policy_Audit_FrequencyCode_A": "A",
    "NamedInsured_FullName_A": INSURED, "NamedInsured_MailingAddress_LineOne_A": MAIL1, "NamedInsured_MailingAddress_LineTwo_A": ACORD_SUITE,
    "NamedInsured_MailingAddress_CityName_A": CITY, "NamedInsured_MailingAddress_StateOrProvinceCode_A": ST, "NamedInsured_MailingAddress_PostalCode_A": ZIP,
    "NamedInsured_GeneralLiabilityCode_A": "98482", "NamedInsured_SICCode_A": SIC, "NamedInsured_NAICSCode_A": ACORD_NAICS,
    "NamedInsured_TaxIdentifier_A": FEIN, "NamedInsured_Primary_PhoneNumber_A": ACORD_PHONE, "NamedInsured_Primary_WebsiteAddress_A": WEB,
    "NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A": True, "NamedInsured_LegalEntity_MemberManagerCount_A": "2",
    "NamedInsured_Contact_ContactDescription_A": "Accounting", "NamedInsured_Contact_FullName_A": "Laura Kessler",
    "NamedInsured_Contact_PrimaryPhoneNumber_A": "(303) 555-0161", "NamedInsured_Contact_PrimaryEmailAddress_A": "lkessler@ridgelinemech.com",
    "NamedInsured_Contact_ContactDescription_B": "Inspection", "NamedInsured_Contact_FullName_B": "Marcus Delgado",
    "NamedInsured_Contact_PrimaryPhoneNumber_B": "(303) 555-0172",
    "BusinessInformation_BusinessType_ContractorIndicator_A": True, "NamedInsured_BusinessStartDate_A": ACORD_START,
    "CommercialPolicy_OperationsDescription_A": OPS,
    "CommercialStructure_InstallationRepairWorkPercent_A": "92", "CommercialStructure_InstallationRepairWorkOffPremisesPercent_A": "92",
    "LossHistory_InformationYearCount_A": "5",
    "CommercialPolicy_RemarkText_A": "Renewal marketing for 12/2026 programme. Insured requests quotes on GL, Auto, Umbrella and Property. "
                                     "Loss runs attached for 5 years. Warehouse (Loc 1 Bldg 2) was re-roofed 2016.",
    "Producer_AuthorizedRepresentative_FullName_A": OTHER["contact"], "NamedInsured_SignatureDate_A": "10/22/2026",
})
rows = [("A", "1", "1", "4150 S Kalamath St", "Denver", "Denver", "CO", "80223", "14,600", "Contractor office and fabrication shop", ACORD_REV, ACORD_FT, ACORD_PT),
        ("B", "1", "2", "4150 S Kalamath St", "Denver", "Denver", "CO", "80223", ACORD_BLDG2_AREA, "Warehouse - HVAC equipment and pipe storage", "", "", ""),
        ("C", "2", "1", "1720 Westland Rd", "Cheyenne", "Laramie", "WY", "82001", "8,400", "Branch shop and parts storage", "", "", "")]
for r, loc, b, a1, c, cty, st, z, area, occ, rev, ft, pt in rows:
    v.update({f"CommercialStructure_Location_ProducerIdentifier_{r}": loc, f"CommercialStructure_Building_ProducerIdentifier_{r}": b,
              f"CommercialStructure_PhysicalAddress_LineOne_{r}": a1, f"CommercialStructure_PhysicalAddress_CityName_{r}": c,
              f"CommercialStructure_PhysicalAddress_CountyName_{r}": cty, f"CommercialStructure_PhysicalAddress_StateOrProvinceCode_{r}": st,
              f"CommercialStructure_PhysicalAddress_PostalCode_{r}": z, f"CommercialStructure_RiskLocation_InsideCityLimitsIndicator_{r}": True,
              f"CommercialStructure_InsuredInterest_OwnerIndicator_{r}": True, f"Construction_BuildingArea_{r}": area,
              f"BuildingOccupancy_OccupiedArea_{r}": area, f"BuildingOccupancy_OperationsDescription_{r}": occ,
              f"CommercialStructure_AnnualRevenueAmount_{r}": rev, f"BusinessInformation_FullTimeEmployeeCount_{r}": ft,
              f"BusinessInformation_PartTimeEmployeeCount_{r}": pt})
prior = [("A", "2025", "-25", POL["GL"]["premium"], POL["AUTO"]["premium"], POL["PROP"]["premium"], POL["UMB"]["premium"], "12/01/2025", "12/01/2026"),
         ("B", "2024", "-24", "$27,105", "$39,870", "$17,215", "$13,600", "12/01/2024", "12/01/2025"),
         ("C", "2023", "-23", "$25,880", "$37,410", "$16,090", "$12,950", "12/01/2023", "12/01/2024")]
for r, yr, sfx, gp, ap, pp, up, e, x in prior:
    v.update({f"PriorCoverage_PolicyYear_{r}": yr,
              f"PriorCoverage_GeneralLiability_InsurerFullName_{r}": POL["GL"]["carrier"], f"PriorCoverage_GeneralLiability_PolicyNumberIdentifier_{r}": "CGL-4471209" + sfx,
              f"PriorCoverage_GeneralLiability_TotalPremiumAmount_{r}": gp, f"PriorCoverage_GeneralLiability_EffectiveDate_{r}": e, f"PriorCoverage_GeneralLiability_ExpirationDate_{r}": x,
              f"PriorCoverage_Automobile_InsurerFullName_{r}": POL["AUTO"]["carrier"], f"PriorCoverage_Automobile_PolicyNumberIdentifier_{r}": "BAP-7720158" + sfx,
              f"PriorCoverage_Automobile_TotalPremiumAmount_{r}": ap, f"PriorCoverage_Automobile_EffectiveDate_{r}": e, f"PriorCoverage_Automobile_ExpirationDate_{r}": x,
              f"PriorCoverage_Property_InsurerFullName_{r}": POL["PROP"]["carrier"], f"PriorCoverage_Property_PolicyNumberIdentifier_{r}": "CPP-6609312" + sfx,
              f"PriorCoverage_Property_TotalPremiumAmount_{r}": pp, f"PriorCoverage_Property_EffectiveDate_{r}": e, f"PriorCoverage_Property_ExpirationDate_{r}": x,
              f"PriorCoverage_OtherLine_LineOfBusinessCode_{r}": "UMBRC", f"PriorCoverage_OtherLine_InsurerFullName_{r}": POL["UMB"]["carrier"],
              f"PriorCoverage_OtherLine_PolicyNumberIdentifier_{r}": "CUP-5510873" + sfx, f"PriorCoverage_OtherLine_TotalPremiumAmount_{r}": up,
              f"PriorCoverage_OtherLine_EffectiveDate_{r}": e, f"PriorCoverage_OtherLine_ExpirationDate_{r}": x})
losses = [("A", "06/09/2022", "General Liability", "Water damage at customer site - failed PEX fitting after install", "06/10/2022", "$36,240", "$0", "N", "N"),
          ("B", "05/17/2022", "Commercial Auto", "Rear-end collision, Veh 2 (Ram ProMaster) struck third party", "05/18/2022", ACORD_AUTO_CLAIM_PAID, "$0", "N", "N"),
          ("C", "07/28/2024", "Property", "Hail damage to warehouse roof, Loc 1 Bldg 2", "07/30/2024", "$48,300", "$0", "N", "N")]
for r, od, lob, desc, cd, paid, res, sub, op in losses:
    v.update({f"LossHistory_OccurrenceDate_{r}": od, f"LossHistory_LineOfBusiness_{r}": lob, f"LossHistory_OccurrenceDescription_{r}": desc,
              f"LossHistory_ClaimDate_{r}": cd, f"LossHistory_PaidAmount_{r}": paid, f"LossHistory_ReservedAmount_{r}": res,
              f"LossHistory_ClaimStatus_SubrogationCode_{r}": sub, f"LossHistory_ClaimStatus_OpenCode_{r}": op})
v["LossHistory_TotalAmount_A"] = "$99,360"
for q in ['CommercialStructure_Question_ABBCode_A', 'CommercialPolicy_Question_AAICode_A', 'CommercialPolicy_Question_AAJCode_A', 'CommercialPolicy_Question_KAACode_A',
          'CommercialPolicy_Question_ABCCode_A', 'CommercialPolicy_Question_AAHCode_A', 'CommercialPolicy_Question_AACCode_A', 'CommercialPolicy_Question_AADCode_A',
          'CommercialPolicy_Question_KABCode_A', 'CommercialPolicy_Question_AAFCode_A', 'CommercialPolicy_Question_KAKCode_A', 'CommercialPolicy_Question_KALCode_A',
          'CommercialPolicy_Question_ABBCode_A', 'CommercialPolicy_Question_KACCode_A', 'CommercialPolicy_Question_KAMCode_A', 'CommercialPolicy_Question_KANCode_A',
          'CommercialPolicy_Question_KAOCode_A']:
    v[q] = "N"
fill("ACORD_125", v, OUT + "02_outside_acord_125_flattened.pdf", "125")

# ======================= ACORD 127 =======================
v = {}
producer_block(v)
v.update({"Policy_EffectiveDate_A": ACORD_EFF, "NamedInsured_FullName_A": INSURED,
          "CommercialVehicleLineOfBusiness_Attachment_CommercialAutoDriverInformationScheduleIndicator_A": True,
          "CommercialVehicleLineOfBusiness_Attachment_AdditionalInterestIndicator_A": True,
          "CommercialVehicleLineOfBusiness_Attachment_VehicleScheduleIndicator_A": True})
L = "ABCDEFGHIJKLM"
for i, d in enumerate(DRIVERS):
    r = L[i]
    dob = ACORD_DOB3 if d[0] == "3" else d[9]
    v.update({f"Driver_ProducerIdentifier_{r}": d[0], f"Driver_GivenName_{r}": d[1], f"Driver_OtherGivenNameInitial_{r}": d[2], f"Driver_Surname_{r}": d[3],
              f"Driver_MailingAddress_CityName_{r}": d[4], f"Driver_MailingAddress_StateOrProvinceCode_{r}": d[5], f"Driver_MailingAddress_PostalCode_{r}": d[6],
              f"Driver_GenderCode_{r}": d[7], f"Driver_MaritalStatusCode_{r}": d[8], f"Driver_BirthDate_{r}": dob, f"Driver_ExperienceYearCount_{r}": d[10],
              f"Driver_LicensedYear_{r}": d[11], f"Driver_LicenseNumberIdentifier_{r}": d[12], f"Driver_LicensedStateOrProvinceCode_{r}": d[13],
              f"Driver_HiredDate_{r}": d[14], f"Driver_Coverage_BroadenedNoFaultCode_{r}": "N", f"Driver_Coverage_DriverOtherCarCode_{r}": "N",
              f"Driver_Vehicle_ProducerIdentifier_{r}": d[15], f"Driver_Vehicle_UsePercent_{r}": d[16]})
QA = {
    "AAJ": ("N", None, None), "ABA": ("N", None, None),
    "KAD": ("Y", "CommercialVehicleLineOfBusiness_VehicleMaintenanceProgramInOperationExplanation_A", "Fleet serviced every 5,000 miles at Kalamath shop; written pre-trip inspection checklist"),
    "ABC": ("N", "CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A", "No vehicles are leased to others"),
    "AAG": ("Y", None, None),
    "AAE": ("N", None, None),
    "AAF": ("Y", "CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A", "Refrigerant cylinders (R-410A) and acetylene under DOT materials-of-trade exception, under 440 lbs"),
    "AAB": ("Y", "CommercialVehicleLineOfBusiness_HoldHarmlessAgreementsExplanation_A", "Standard GC subcontract agreements with mutual hold harmless; no auto-specific agreements"),
    "AAC": ("N", "CommercialVehicleLineOfBusiness_VehiclesUsedByFamilyMembersExplanation_A", "Company vehicles restricted to employees on company business"),
    "KAE": ("Y", "CommercialVehicleLineOfBusiness_ApplicantObtainMVRVerificationsExplanation_A", "MVRs pulled at hire and annually each December"),
    "KAF": ("Y", "CommercialVehicleLineOfBusiness_ApplicantSpecificDriverRecruitingMethodExplanation_K", "Minimum age 23, 3 years licensed, no major violations in 5 years"),
    "AAH": ("N", "CommercialVehicleLineOfBusiness_AnyDriversNotCoveredWorkersCompensationExplanation_A", "All drivers are W-2 employees covered by WC"),
    "AAD": ("N", "CommercialVehicleLineOfBusiness_AnyVehiclesOwnedNotScheduledExplanation_A", "All owned vehicles are scheduled"),
    "AAI": ("Y", None, None),
    "ABB": ("Y", "CommercialVehicleLineOfBusiness_AgentInspectedVehiclesExplanation_A", "Agent inspected the fleet at 4150 S Kalamath St on 10/15/2026"),
    "KAG": ("Y", None, None),
}
for code, (ans, exk, ex) in QA.items():
    v[f"CommercialVehicleLineOfBusiness_Question_{code}Code_A"] = ans
    if exk:
        v[exk] = ex
v["CommercialVehicleLineOfBusiness_KAHCode_A"] = "Y"
v.update({"Vehicle_ProducerIdentifier_AC": "3", "Vehicle_Question_ModifiedEquipmentDescription_A": "Knapheide service body with ladder rack and pipe vise",
          "Vehicle_Question_ModifiedEquipmentCostAmount_A": "$14,800",
          "AccidentConviction_DriverProducerIdentifier_A": "3", "AccidentConviction_TrafficViolationDate_A": "03/11/2024",
          "AccidentConviction_TrafficViolationDescription_A": "Speeding 11-15 mph over limit", "AccidentConviction_PlaceOfIncident_A": "Denver, CO",
          "AccidentConviction_ViolationYearCount_A": "3",
          "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A": "100",
          "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_MonitorDriverSafetyIndicator_A": True,
          "CommercialVehicleLineOfBusiness_LocationTrackingDeviceIndicator_A": True,
          "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_MileageTrackingDeviceIndicator_A": True,
          "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_AdditionalDescription_A": "Samsara telematics on all units",
          "CommercialVehicleLineOfBusiness_GarageStorageDescription_A": "Vehicles parked overnight inside fenced, gated, lit yard at 4150 S Kalamath St",
          "CommercialVehicleLineOfBusiness_MaximumExposureAllVehiclesAmount_A": "$218,850",
          "AdditionalInterest_Interest_LienholderIndicator_A": True, "AdditionalInterest_FullName_A": "Wells Fargo Equipment Finance",
          "AdditionalInterest_MailingAddress_LineOne_A": "800 Walnut St", "AdditionalInterest_MailingAddress_CityName_A": "Des Moines",
          "AdditionalInterest_MailingAddress_StateOrProvinceCode_A": "IA", "AdditionalInterest_MailingAddress_PostalCode_A": "50309",
          "AdditionalInterest_InterestRank_A": "1", "AdditionalInterest_AccountNumberIdentifier_A": "77-0042218", "AdditionalInterest_Item_VehicleProducerIdentifier_A": "1",
          "AdditionalInterest_Interest_LienholderIndicator_B": True, "AdditionalInterest_FullName_B": "Ally Bank",
          "AdditionalInterest_MailingAddress_LineOne_B": "PO Box 380902", "AdditionalInterest_MailingAddress_CityName_B": "Bloomington",
          "AdditionalInterest_MailingAddress_StateOrProvinceCode_B": "MN", "AdditionalInterest_MailingAddress_PostalCode_B": "55438",
          "AdditionalInterest_InterestRank_B": "1", "AdditionalInterest_AccountNumberIdentifier_B": "5521-098834", "AdditionalInterest_Item_VehicleProducerIdentifier_B": "3",
          "CommercialVehicleLineOfBusiness_RemarkText_A": "Renewal of fleet currently written with Front Range Mutual. Liability symbol 1, physical damage symbol 7, hired PD symbol 8.",
          "Producer_AuthorizedRepresentative_FullName_A": OTHER["contact"], "Producer_StateLicenseIdentifier_A": "CO-591204",
          "NamedInsured_SignatureDate_A": "10/22/2026"})
TERR = {"1": "112", "2": "112", "3": "112", "4": "205"}
GVW = {"1": "9070", "2": "9350", "3": "14000", "4": "9900"}
CLS = {"1": "21499", "2": "21499", "3": "31499", "4": "21499"}
for i, veh in enumerate(VEHICLES):
    r = L[i]
    no, yr, mk, md, body, vin, gar, cost, cded, coll, prem = veh
    if no == "2":
        vin = ACORD_VIN2
    street, city, rest = [x.strip() for x in gar.split(",")]
    st, z = rest.split()
    v.update({f"Vehicle_ProducerIdentifier_{r}": no, f"Vehicle_ModelYear_{r}": yr, f"Vehicle_ManufacturersName_{r}": mk, f"Vehicle_ModelName_{r}": md,
              f"Vehicle_BodyCode_{r}": body, f"Vehicle_VINIdentifier_{r}": vin, f"Vehicle_VehicleType_CommercialIndicator_{r}": True,
              f"Vehicle_ComprehensiveSymbolCode_{r}": "7", f"Vehicle_CollisionSymbolCode_{r}": "7",
              f"Vehicle_PhysicalAddress_LineOne_{r}": street, f"Vehicle_PhysicalAddress_CityName_{r}": city,
              f"Vehicle_PhysicalAddress_CountyName_{r}": VIN_COUNTY[city], f"Vehicle_PhysicalAddress_StateOrProvinceCode_{r}": st,
              f"Vehicle_PhysicalAddress_PostalCode_{r}": z, f"Vehicle_Registration_StateOrProvinceCode_{r}": st,
              f"Vehicle_RatingTerritoryCode_{r}": TERR[no], f"Vehicle_GrossVehicleWeight_{r}": GVW[no], f"Vehicle_RateClassCode_{r}": CLS[no],
              f"Vehicle_SpecialIndustryClassCode_{r}": "1711", f"Vehicle_RadiusOfUse_{r}": "50", f"Vehicle_CostNewAmount_{r}": cost,
              f"Vehicle_Use_ServiceIndicator_{r}": True, f"Vehicle_Coverage_LiabilityIndicator_{r}": True,
              f"Vehicle_Coverage_MedicalPaymentsIndicator_{r}": True, f"Vehicle_Coverage_UninsuredMotoristsIndicator_{r}": True,
              f"Vehicle_Coverage_UnderinsuredMotoristsIndicator_{r}": True, f"Vehicle_Coverage_TowingAndLabourIndicator_{r}": True,
              f"Vehicle_Coverage_ComprehensiveIndicator_{r}": True, f"Vehicle_Coverage_CollisionIndicator_{r}": True,
              f"Vehicle_Coverage_ValuationActualCashValueIndicator_{r}": True, f"Vehicle_Coverage_ComprehensiveDeductibleIndicator_{r}": True,
              f"Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_{r}": cded, f"Vehicle_Collision_DeductibleAmount_{r}": coll,
              f"Vehicle_Use_UnderFifteenMilesIndicator_{r}": True, f"Vehicle_TotalPremiumAmount_{r}": prem})
fill("ACORD_127", v, OUT + "03_outside_acord_127_flattened.pdf", "127")
