"""
kit_key.py - the answer key for the CH125 kit: a verdict for EVERY box on
ACORD 125 (548), ACORD 126 (255) and ACORD 127 (634).

Verdicts (the same contract as fr125_test_data/FR125_answer_key.json, so
backend/scripts/score_form_fill.py and report_125_run.py read it unchanged):
  expect          the box must carry this value
  blank_no_data   the documents state nothing for this box - it must stay blank
  blank_by_rule   a client rule owns the box as a blank (quote not priced, a No
                  question's detail block, authorship, ...)
  not_scored      the right answer depends on the logged-in account or on an
                  open owner decision - read the note, grade by hand

Every box is decided EXPLICITLY. The builder fails if a box is assigned twice,
names a field not on the form, or is left undecided.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

import kit_data as D

BACKEND = Path(__file__).resolve().parents[2] / "backend"
EXPECT, NO_DATA, BY_RULE, NOT_SCORED = "expect", "blank_no_data", "blank_by_rule", "not_scored"
FORMS = ("ACORD_125", "ACORD_126", "ACORD_127")
FIELDS: Dict[str, Dict[str, dict]] = {f: {} for f in FORMS}
SEMANTIC_EXTRA: Dict[str, set] = {f: set() for f in FORMS}

ACCOUNT_WHY = ("resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded "
               "documents - grade by hand against the account")
UNRESOLVED = "UNRESOLVED - the insured never answered it; must stay BLANK (blank is not No)"
QUOTE_RULE = "a new-business quote is not priced - client rule: blank unless known"
SECTION_HEADER = ("DECISION POINT: the client's rule (8-19-26) is that the application describes "
                  "the policy BEING APPLIED FOR. The 15 Sep 'section forms keep the current "
                  "policy's identity' rule (Brent point 1, made on a dec-only renewal) may print "
                  "the incumbent here instead - that is an owner decision, not a fill defect")


def put(form, field, verdict, value="", why="", trap="", source="text"):
    if field in FIELDS[form]:
        raise SystemExit(f"answer key: {form}.{field} assigned twice")
    FIELDS[form][field] = {"verdict": verdict, "value": value, "why": why, "trap": trap,
                           "source": source}


def tick(form, field, on, why="", trap=""):
    if on:
        put(form, field, EXPECT, "Y", why, trap)
    else:
        put(form, field, NO_DATA, "", why or "the documents do not assert this", trap)


def yn(form, field, answer, why="", trap=""):
    if answer in ("Y", "N"):
        put(form, field, EXPECT, answer, why, trap)
    else:
        put(form, field, NO_DATA, "", UNRESOLVED, trap)


def schema(form: str) -> dict:
    return json.loads((BACKEND / "forms_schemas" / f"{form}_schema.json").read_text(encoding="utf-8"))


def _common_tail(form: str, sig_suffix: str = "_A"):
    """Signature block - authorship and the account."""
    put(form, f"Producer_AuthorizedRepresentative_Signature{sig_suffix}", BY_RULE, "",
        "AUTHORSHIP - only the producer signs (the Sign button), never the fill")
    put(form, f"Producer_AuthorizedRepresentative_FullName{sig_suffix}", NOT_SCORED,
        D.AGENCY_PRODUCER, ACCOUNT_WHY)
    put(form, f"Producer_StateLicenseIdentifier{sig_suffix}", NOT_SCORED, D.AGENCY_TN_LICENSE,
        "client: 'state producer license: completed where applicable' - Primble's account "
        "profile has NO licence field (audit gap); the cover e-mail prints Riverbend's licence")
    put(form, f"Producer_NationalIdentifier{sig_suffix}", NOT_SCORED, D.AGENCY_NPN,
        "client: 'NPN: completed' - Primble's account profile has NO NPN field (audit gap); "
        "the cover e-mail prints Riverbend's NPN")
    put(form, f"NamedInsured_Signature{sig_suffix}", BY_RULE, "", "AUTHORSHIP - the applicant signs")
    put(form, f"NamedInsured_SignatureDate{sig_suffix}", BY_RULE, "", "AUTHORSHIP - set when signed")


def _section_header(form: str, line_policy: str):
    put(form, "Form_CompletionDate_A", NOT_SCORED, "", "the generation date")
    put(form, "Producer_FullName_A", NOT_SCORED, D.AGENCY, ACCOUNT_WHY)
    put(form, "Producer_CustomerIdentifier_A", NOT_SCORED, D.AGENCY_AMS_CUSTOMER_ID,
        "client: 'only if verified from agency/AMS' - Riverbend's AMS export prints it; Primble "
        "never fills this box today (audit). Must NEVER be the prior agency's CUMB-0044",
        trap=D.PRIOR_AGENCY_CUSTOMER_ID)
    put(form, "Policy_PolicyNumberIdentifier_A", BY_RULE, "",
        "new business: no policy number exists yet. " + SECTION_HEADER, trap=line_policy)
    put(form, "Policy_EffectiveDate_A", EXPECT, D.PROPOSED_EFF, SECTION_HEADER, trap=D.CUR_EFF)
    put(form, "Insurer_FullName_A", EXPECT, D.CARRIER, SECTION_HEADER, trap=D.OHM)
    put(form, "Insurer_NAICCode_A", EXPECT, D.CARRIER_NAIC, "verified on the MGA acknowledgement",
        trap=D.OHM_NAIC)
    put(form, "NamedInsured_FullName_A", EXPECT, D.NAME, "the first named insured (a box listing "
        "both named insureds also scores correct)")


# ════════════════════════════════════════════════════════════════════════════
# ACORD 125
# ════════════════════════════════════════════════════════════════════════════
def build_125():
    F = "ACORD_125"
    Q = D.Q125
    put(F, "Form_EditionIdentifier_A", EXPECT, "ACORD 125 (2025/03)", "the template's footer",
        source="template")
    put(F, "Form_CompletionDate_A", NOT_SCORED, "", "the generation date")
    for fld, v in (("Producer_FullName_A", D.AGENCY),
                   ("Producer_MailingAddress_LineOne_A", D.AGENCY_L1),
                   ("Producer_MailingAddress_LineTwo_A", D.AGENCY_L2),
                   ("Producer_MailingAddress_CityName_A", D.AGENCY_CITY),
                   ("Producer_MailingAddress_StateOrProvinceCode_A", D.AGENCY_STATE),
                   ("Producer_MailingAddress_PostalCode_A", D.AGENCY_ZIP),
                   ("Producer_ContactPerson_FullName_A", D.AGENCY_PRODUCER),
                   ("Producer_ContactPerson_PhoneNumber_A", D.AGENCY_PHONE),
                   ("Producer_ContactPerson_EmailAddress_A", D.AGENCY_EMAIL)):
        put(F, fld, NOT_SCORED, v, ACCOUNT_WHY)
    put(F, "Producer_FaxNumber_A", NO_DATA, "", "no agency fax is printed anywhere",
        trap=f"{D.FAX} is the APPLICANT's fax")
    put(F, "Insurer_ProducerIdentifier_A", NOT_SCORED, D.AGENCY_CARRIER_CODE,
        "client: 'only if verified from agency/AMS' - Ridgeline's code for Riverbend is printed "
        "on the MGA acknowledgement and the AMS export; Primble never fills it today (audit). "
        f"Must NEVER be the prior agency's {D.PRIOR_AGENCY_CODE}", trap=D.PRIOR_AGENCY_CODE)
    put(F, "Insurer_SubProducerIdentifier_A", NOT_SCORED, D.AGENCY_CARRIER_SUBCODE,
        "as the agency code")
    put(F, "Producer_CustomerIdentifier_A", NOT_SCORED, D.AGENCY_AMS_CUSTOMER_ID,
        "client: the agency's customer id, verified from its AMS - the AMS export prints "
        f"CUMBHEA-01; Primble never fills it today (audit). Must NEVER be {D.PRIOR_AGENCY_CUSTOMER_ID}",
        trap=D.PRIOR_AGENCY_CUSTOMER_ID)

    # INSURER - the carrier RECEIVING the submission, through an MGA
    put(F, "Insurer_FullName_A", EXPECT, D.CARRIER, "the writing company named on the MGA's "
        "acknowledgement", trap=f"not the MGA ({D.MGA}) and not the incumbent ({D.OHM})")
    put(F, "Insurer_NAICCode_A", EXPECT, D.CARRIER_NAIC, "client: 'only if verified' - printed "
        "beside the carrier's name in the acknowledgement's fine print", trap=D.OHM_NAIC)
    put(F, "Insurer_ProductDescription_A", EXPECT, D.PROGRAM_NAME, "the program")
    put(F, "Insurer_ProductCode_A", EXPECT, D.PROGRAM_CODE, "the program code")
    put(F, "Insurer_Underwriter_FullName_A", EXPECT, D.UNDERWRITER, "the submission is directed to her")
    put(F, "Insurer_Underwriter_OfficeIdentifier_A", EXPECT, D.UNDERWRITER_OFFICE)

    # POLICY / STATUS
    put(F, "Policy_PolicyNumberIdentifier_A", BY_RULE, "", "client: blank for a new-business "
        "quote", trap="OHM-GL-4471902-25 (expiring), IMF-3318207 (question 4), CG 25 04 05 09 (a form)")
    tick(F, "Policy_Status_QuoteIndicator_A", True, "client: QUOTE - 'request for quotation - new "
         "business to Ridgeline'", trap="the incumbent dec prints 'RENEWAL OF OHM-GL-4471902-24'")
    for st in ("Issue", "Bound", "Change", "Cancel", "Renew"):
        put(F, f"Policy_Status_{st}Indicator_A", BY_RULE, "", "the transaction is a quote",
            trap="RENEW: the incumbent's renewal offer and the SUPERSEDED 2024 application")
    for fld in ("Policy_Status_EffectiveDate_A", "Policy_Status_EffectiveTime_A",
                "Policy_Status_EffectiveTimeAMIndicator_A", "Policy_Status_EffectiveTimePMIndicator_A"):
        put(F, fld, BY_RULE, "", "nothing is bound - the acknowledgement says it is not a binder")

    for k in ("CommercialGeneralLiability", "CommercialProperty", "BusinessAutoIndicator",
              "UmbrellaIndicator"):
        tick(F, f"Policy_LineOfBusiness_{k}_A", True, "requested in the submission e-mail")
    traps = {"BoilerAndMachineryIndicator": "equipment breakdown is an ENDORSEMENT to property",
             "CommercialInlandMarineIndicator": "inland marine is already with Ridgeline - not requested",
             "CrimeIndicator": "crime declined by the insured",
             "CyberAndPrivacy": "cyber discussed, not requested",
             "LiquorLiabilityIndicator": "the caterer holds the liquor licence"}
    for k in ("BoilerAndMachineryIndicator", "BusinessOwnersIndicator", "CrimeIndicator",
              "CyberAndPrivacy", "FiduciaryLiabilityIndicator", "GarageAndDealersIndicator",
              "LiquorLiabilityIndicator", "MotorCarrierIndicator", "TruckersIndicator",
              "YachtIndicator", "CommercialInlandMarineIndicator"):
        tick(F, f"Policy_LineOfBusiness_{k}_A", False, "not requested", trap=traps.get(k, ""))
    for ch in "ABCDEF":
        put(F, f"Policy_LineOfBusiness_OtherIndicator_{ch}", NO_DATA, "", "no other line requested",
            trap="workers compensation stays with Tennessee Employers Mutual")
        put(F, f"Policy_LineOfBusiness_OtherLineOfBusinessDescription_{ch}", NO_DATA)
        put(F, f"Policy_SectionAttached_OtherPremiumAmount_{ch}", BY_RULE, "", QUOTE_RULE)
    for b in ("BoilerAndMachinery", "BusinessOwners", "CommercialInlandMarine", "CommercialProperty",
              "CommercialVehicle", "CommercialUmbrella", "Crime", "CyberAndPrivacy", "Fiduciary",
              "GarageAndDealers", "LiquorLiability", "MotorCarrier", "Truckers", "Yacht"):
        put(F, f"{b}LineOfBusiness_PremiumAmount_A", BY_RULE, "", QUOTE_RULE,
            trap="$61,775 / $27,940 / $9,880 are EXPIRING premiums" if b in
            ("CommercialVehicle", "CommercialProperty", "CommercialUmbrella") else "")
    put(F, "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A", BY_RULE, "", QUOTE_RULE,
        trap="$38,420 is the expiring GL premium")

    # ATTACHMENTS
    for k in ("VehicleScheduleIndicator", "DriverInformationScheduleIndicator"):
        put(F, f"Policy_SectionAttached_{k}_A", NOT_SCORED, "",
            "disputed: ACORD 127 (generated with this 125) carries the vehicles and drivers; "
            "whether that ticks these boxes is an owner decision")
    for k in ("AccountsReceivableValuablePapersIndicator", "DealerIndicator",
              "ElectronicDataProcessingIndicator", "GlassAndSignIndicator",
              "InstallationBuildersRiskIndicator", "OpenCargoIndicator"):
        put(F, f"Policy_SectionAttached_{k}_A", BY_RULE, "", "not attached - only 125/126/127 "
            "are generated (client: tick 'only when Primble actually creates and attaches' it)")
    for k in ("ContractorsSupplementIndicator", "StatementOfValuesIndicator", "LossSummaryIndicator",
              "AdditionalInterestScheduleIndicator", "AdditionalPremisesScheduleIndicator",
              "ApartmentBuildingSupplementIndicator", "CondominiumAssociationByLawsIndicator",
              "CoveragesScheduleIndicator", "HotelMotelSupplementIndicator",
              "InternationalLiabilityExposureSupplementIndicator",
              "InternationalPropertyExposureSupplementIndicator",
              "PremiumPaymentSupplementIndicator", "ProfessionalLiabilitySupplementIndicator",
              "RestaurantTavernSupplementIndicator", "StateSupplementIndicator",
              "VacantBuildingSupplementIndicator"):
        put(F, f"CommercialPolicy_Attachment_{k}_A", BY_RULE, "", "not attached",
            trap="the package CONTAINS a statement of values and loss runs - they are not ACORD "
                 "attachments Primble generates" if k in ("StatementOfValuesIndicator",
                                                          "LossSummaryIndicator") else "")
    for ch in "ABCDEF":
        put(F, f"CommercialPolicy_Attachment_OtherIndicator_{ch}", NOT_SCORED, "",
            "listing ACORD 126 / 127 as 'other' attachments is acceptable either way")
        put(F, f"CommercialPolicy_Attachment_OtherDescription_{ch}", NOT_SCORED, "",
            "as the indicator")

    # POLICY INFORMATION
    put(F, "Policy_EffectiveDate_A", EXPECT, D.PROPOSED_EFF, "confirmed in the CFO's 09/30 e-mail "
        "and the acknowledgement", trap=f"{D.STALE_PROPOSED_EFF} (August worksheet) and {D.CUR_EFF} (current)")
    put(F, "Policy_ExpirationDate_A", EXPECT, D.PROPOSED_EXP, trap=D.CUR_EXP)
    tick(F, "Policy_Payment_DirectBillIndicator_A", True, "direct bill requested and acknowledged",
         trap="the incumbent is agency billed")
    put(F, "Policy_Payment_ProducerBillIndicator_A", BY_RULE, "", "billing is DIRECT",
        trap="the incumbent dec: 'Agency bill - 10 installments'")
    put(F, "Policy_Payment_PaymentScheduleCode_A", EXPECT, D.PAYMENT_PLAN_CODE,
        "ACORD tooltip: 'QT - Quarterly'", trap="10 installments is the incumbent's")
    put(F, "Policy_PaymentMethod_MethodDescription_A", EXPECT, D.PAYMENT_METHOD,
        trap="Agency bill - 10 installments")
    put(F, "Policy_Audit_FrequencyCode_A", EXPECT, D.AUDIT_CODE, "acknowledgement: premium audit "
        "annual", trap="the incumbent GL dec says semi-annual (S)")
    for fld in ("Policy_Payment_DepositAmount_A", "Policy_Payment_MinimumPremiumAmount_A"):
        put(F, fld, BY_RULE, "", QUOTE_RULE, trap="$9,605 is the incumbent's minimum premium")
    put(F, "Policy_Payment_EstimatedTotalAmount_A", BY_RULE, "", QUOTE_RULE,
        trap=f"{D.CUR_TOTAL_PREMIUM} is the expiring programme")
    put(F, "Policy_InformationPracticesNoticeIndicator_A", BY_RULE, "", "AUTHORSHIP")

    # NAMED INSUREDS A (applicant), B (subsidiary), C (none)
    a = {"name": D.NAME, "l1": D.MAIL_L1, "city": D.MAIL_CITY, "state": D.MAIL_STATE,
         "zip": D.MAIL_ZIP, "gl": D.GL_CODE, "sic": D.SIC, "naics": D.NAICS, "fein": D.FEIN,
         "phone": D.BUS_PHONE, "web": D.WEBSITE}
    b = {"name": D.SUB["name"], "l1": D.SUB["l1"], "l2": D.SUB["l2"], "city": D.SUB["city"],
         "state": D.SUB["state"], "zip": D.SUB["zip"], "gl": D.SUB["gl"], "sic": D.SUB["sic"],
         "naics": D.SUB["naics"], "fein": D.SUB["fein"], "phone": D.SUB["phone"], "web": D.SUB["web"]}
    cols = (("FullName", "name"), ("MailingAddress_LineOne", "l1"), ("MailingAddress_LineTwo", "l2"),
            ("MailingAddress_CityName", "city"), ("MailingAddress_StateOrProvinceCode", "state"),
            ("MailingAddress_PostalCode", "zip"), ("GeneralLiabilityCode", "gl"), ("SICCode", "sic"),
            ("NAICSCode", "naics"), ("TaxIdentifier", "fein"), ("Primary_PhoneNumber", "phone"),
            ("Primary_WebsiteAddress", "web"))
    trapmap = {"name": f"{D.FORMER_NAME} / {D.JV['name']} / the trust",
               "fein": f"{D.SOS_CONTROL} (SOS), {D.DUNS} (D-U-N-S), {D.USDOT} (USDOT)",
               "phone": f"{D.FAX} is the fax; {D.OHM_PHONE} the incumbent",
               "web": D.OHM_WEB, "gl": "68706 / 91127 are not the governing class",
               "l1": f"{L1['l1']} is a PREMISES, not the mailing address"}
    for row, o in (("A", a), ("B", b)):
        for col, k in cols:
            v = o.get(k, "")
            if v:
                put(F, f"NamedInsured_{col}_{row}", EXPECT, v, trap=trapmap.get(k, "") if row == "A" else "")
            else:
                put(F, f"NamedInsured_{col}_{row}", NO_DATA, "", "no second address line")
    for col, _k in cols:
        put(F, f"NamedInsured_{col}_C", NO_DATA, "", "only two named insureds",
            trap=f"never {D.JV['name']}, {D.FORMER_NAME}, the trust or the landlord")
    ents = ["CorporationIndicator", "IndividualIndicator", "JointVentureIndicator",
            "LimitedLiabilityCorporationIndicator", "NotForProfitIndicator", "OtherIndicator",
            "PartnershipIndicator", "SubchapterSCorporationIndicator", "TrustIndicator"]
    for row, ent in (("A", "CorporationIndicator"), ("B", "LimitedLiabilityCorporationIndicator")):
        for e in ents:
            tick(F, f"NamedInsured_LegalEntity_{e}_{row}", e == ent,
                 "a C corporation (W-9, Form 1120)" if row == "A" else "a member-managed LLC",
                 trap="the FORMER LLC" if (row == "A" and e == "LimitedLiabilityCorporationIndicator")
                 else ("no S election" if e == "SubchapterSCorporationIndicator" else ""))
        put(F, f"NamedInsured_LegalEntity_OtherDescription_{row}", NO_DATA)
    for e in ents:
        put(F, f"NamedInsured_LegalEntity_{e}_C", NO_DATA, "", "no third named insured")
    put(F, "NamedInsured_LegalEntity_OtherDescription_C", NO_DATA)
    put(F, "NamedInsured_LegalEntity_MemberManagerCount_A", BY_RULE, "", "a corporation has no "
        "members or managers", trap="the old LLC")
    put(F, "NamedInsured_LegalEntity_MemberManagerCount_B", EXPECT, D.SUB["members"],
        "the 2026 SOS annual report")
    put(F, "NamedInsured_LegalEntity_MemberManagerCount_C", NO_DATA)
    put(F, "NamedInsured_BusinessStartDate_A", EXPECT, D.START_DATE, "in continuous operation since "
        "March 1, 2009", trap="01/01/2022 is the conversion; 03/15/2018 is the subsidiary's formation")

    # CONTACTS
    for row, c in zip("AB", D.CONTACTS):
        put(F, f"NamedInsured_Contact_ContactDescription_{row}", EXPECT, c["type"])
        put(F, f"NamedInsured_Contact_FullName_{row}", EXPECT, c["name"], trap="never the CFO")
        put(F, f"NamedInsured_Contact_PrimaryPhoneNumber_{row}", EXPECT, c["phone"])
        put(F, f"NamedInsured_Contact_SecondaryPhoneNumber_{row}", EXPECT, c["phone2"],
            trap=D.DENISE_CELL_TYPO + " is a corrected typo" if row == "B" else "")
        put(F, f"NamedInsured_Contact_PrimaryEmailAddress_{row}", EXPECT, c["email"])
        put(F, f"NamedInsured_Contact_SecondaryEmailAddress_{row}", EXPECT, c["email2"])
        for slot, typ in (("Primary", c["phone_type"]), ("Secondary", c["phone2_type"])):
            for kind in ("Business", "Cell", "Home"):
                tick(F, f"NamedInsured_Contact_{slot}{kind}PhoneIndicator_{row}", kind == typ,
                     "the phone's type is stated")

    # BUSINESS INFORMATION
    tick(F, "BusinessInformation_BusinessType_WholesaleIndicator_A", True, "worksheet + operations",
         trap="the SUPERSEDED 2024 application said Retail")
    for k in ("ApartmentsIndicator", "CondominiumsIndicator", "ContractorIndicator",
              "InstitutionalIndicator", "ManufacturingIndicator", "OfficeIndicator", "OtherIndicator",
              "RestaurantIndicator", "RetailIndicator", "ServiceIndicator"):
        tick(F, f"BusinessInformation_BusinessType_{k}_A", False, "one nature of business",
             trap="customers are restaurants; the subsidiary is service" if k in
             ("RestaurantIndicator", "ServiceIndicator", "RetailIndicator") else "")
    put(F, "BusinessInformation_BusinessType_OtherDescription_A", NO_DATA)
    put(F, "CommercialPolicy_OperationsDescription_A", EXPECT, D.PRIMARY_OPERATIONS)
    put(F, "CommercialPolicy_OperationsDescription_B", EXPECT, D.OTHER_INSURED_OPERATIONS)
    put(F, "CommercialStructure_InstallationRepairWorkPercent_A", EXPECT, D.INSTALL_PCT,
        "ACORD tooltip: % of TOTAL SALES - the CFO's e-mail")
    put(F, "CommercialStructure_InstallationRepairWorkOffPremisesPercent_A", EXPECT, D.INSTALL_OFF_PCT,
        "% of TOTAL SALES done off premises", trap="95% is a share of service CALLS")
    put(F, "CommercialPolicy_RemarkText_A", EXPECT, D.REMARKS, "the worksheet's remark for the application")

    # PREMISES A-C, D empty
    for row, l in zip("ABC", D.LOCATIONS):
        put(F, f"CommercialStructure_Location_ProducerIdentifier_{row}", EXPECT, l["num"],
            "the premises schedule (LOC #)",
            trap="the property carrier numbers its premises 001-004 differently")
        put(F, f"CommercialStructure_Building_ProducerIdentifier_{row}", EXPECT, l["bldg"],
            "the premises schedule (BLD #)")
        put(F, f"CommercialStructure_PhysicalAddress_LineOne_{row}", EXPECT, l["l1"])
        if l["l2"]:
            put(F, f"CommercialStructure_PhysicalAddress_LineTwo_{row}", EXPECT, l["l2"])
        else:
            put(F, f"CommercialStructure_PhysicalAddress_LineTwo_{row}", NO_DATA)
        for col, k in (("CityName", "city"), ("CountyName", "county"),
                       ("StateOrProvinceCode", "state"), ("PostalCode", "zip")):
            put(F, f"CommercialStructure_PhysicalAddress_{col}_{row}", EXPECT, l[k])
        tick(F, f"CommercialStructure_RiskLocation_InsideCityLimitsIndicator_{row}", l["inside"],
             trap="La Vergne mailing address, unincorporated county" if row == "B" else "")
        tick(F, f"CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_{row}", not l["inside"])
        tick(F, f"CommercialStructure_RiskLocation_OtherIndicator_{row}", False)
        put(F, f"CommercialStructure_RiskLocation_OtherDescription_{row}", NO_DATA)
        tick(F, f"CommercialStructure_InsuredInterest_OwnerIndicator_{row}", l["interest"] == "Owner")
        tick(F, f"CommercialStructure_InsuredInterest_TenantIndicator_{row}", l["interest"] == "Tenant",
             trap="location 1 subleases space TO others - the insured still owns it" if row == "A" else "")
        tick(F, f"CommercialStructure_InsuredInterest_OtherIndicator_{row}", False)
        put(F, f"CommercialStructure_InsuredInterest_OtherDescription_{row}", NO_DATA)
        put(F, f"BusinessInformation_FullTimeEmployeeCount_{row}", EXPECT, l["ft"],
            "the HR census, F/T column", trap="HC (head count) is full + part time")
        put(F, f"BusinessInformation_PartTimeEmployeeCount_{row}", EXPECT, l["pt"],
            "the HR census, P/T column", trap="TMP agency temps are not employees")
        put(F, f"CommercialStructure_AnnualRevenueAmount_{row}", EXPECT, l["revenue"],
            trap="the company total, the 2027 plan, the backlog and payroll")
        put(F, f"BuildingOccupancy_OccupiedArea_{row}", EXPECT, l["occupied"],
            trap=f"{D.LOC3_STALE_OCCUPIED} is pre-amendment" if row == "C" else "")
        put(F, f"BuildingOccupancy_OpenToPublicArea_{row}", EXPECT, l["public"],
            "premises schedule PUB SF + footnotes")
        put(F, f"Construction_BuildingArea_{row}", EXPECT, l["total_area"], "premises schedule TOT SF")
        put(F, f"BuildingOccupancy_OperationsDescription_{row}", EXPECT, l["ops"])
        put(F, f"CommercialStructure_Question_ABBCode_{row}", EXPECT, l["leased"],
            "premises schedule LSD TO OTH + footnote 1")
    for base in ("CommercialStructure_Location_ProducerIdentifier", "CommercialStructure_Building_ProducerIdentifier",
                 "CommercialStructure_PhysicalAddress_LineOne", "CommercialStructure_PhysicalAddress_LineTwo",
                 "CommercialStructure_PhysicalAddress_CityName", "CommercialStructure_PhysicalAddress_CountyName",
                 "CommercialStructure_PhysicalAddress_StateOrProvinceCode", "CommercialStructure_PhysicalAddress_PostalCode",
                 "CommercialStructure_RiskLocation_InsideCityLimitsIndicator",
                 "CommercialStructure_RiskLocation_OutsideCityLimitsIndicator",
                 "CommercialStructure_RiskLocation_OtherIndicator", "CommercialStructure_RiskLocation_OtherDescription",
                 "CommercialStructure_InsuredInterest_OwnerIndicator", "CommercialStructure_InsuredInterest_TenantIndicator",
                 "CommercialStructure_InsuredInterest_OtherIndicator", "CommercialStructure_InsuredInterest_OtherDescription",
                 "BusinessInformation_FullTimeEmployeeCount", "BusinessInformation_PartTimeEmployeeCount",
                 "CommercialStructure_AnnualRevenueAmount", "BuildingOccupancy_OccupiedArea",
                 "BuildingOccupancy_OpenToPublicArea", "Construction_BuildingArea",
                 "BuildingOccupancy_OperationsDescription", "CommercialStructure_Question_ABBCode"):
        put(F, f"{base}_D", NO_DATA, "", "three premises only",
            trap=f"{D.CLOSED_LOCATION['l1']} CLOSED 06/30/2026; the JV kitchen; customer job sites")

    # ADDITIONAL INTEREST - the mortgagee
    M = D.MORTGAGEE
    for col, v in (("FullName_A", M["name"]), ("MailingAddress_LineOne_A", M["l1"]),
                   ("MailingAddress_LineTwo_A", M["l2"]), ("MailingAddress_CityName_A", M["city"]),
                   ("MailingAddress_StateOrProvinceCode_A", M["state"]),
                   ("MailingAddress_PostalCode_A", M["zip"]), ("InterestRank_A", M["rank"]),
                   ("AccountNumberIdentifier_A", M["loan_no"]), ("InterestEndDate_A", M["end"]),
                   ("LoanAmount_A", M["amount"]), ("Primary_PhoneNumber_A", M["phone"]),
                   ("Primary_FaxNumber_A", M["fax"]), ("Primary_EmailAddress_A", M["email"]),
                   ("InterestReasonDescription_A", M["reason"]),
                   ("Item_LocationProducerIdentifier_A", M["loc"]),
                   ("Item_BuildingProducerIdentifier_A", M["bldg"]), ("ItemDescription_A", M["item"])):
        put(F, f"AdditionalInterest_{col}", EXPECT, v, "the loan summary",
            trap=f"{D.LOAN_BALANCE_DECOY} is the balance" if col == "LoanAmount_A" else "")
    put(F, "AdditionalInterest_MailingAddress_CountryCode_A", NOT_SCORED, "",
        "no country is printed; 'US' is harmless either way")
    tick(F, "AdditionalInterest_Interest_MortgageeIndicator_A", True, "first mortgage")
    for k in ("AdditionalInsuredIndicator", "BreachOfWarrantyIndicator", "CoOwnerIndicator",
              "EmployeeAsLessorIndicator", "LeasebackOwnerIndicator", "LendersLossPayableIndicator",
              "LienholderIndicator", "LossPayeeIndicator", "OtherIndicator", "OwnerIndicator",
              "RegistrantIndicator", "TrusteeIndicator"):
        tick(F, f"AdditionalInterest_Interest_{k}_A", False, "the interest is a mortgagee")
    put(F, "AdditionalInterest_Interest_OtherDescription_A", NO_DATA)
    tick(F, "AdditionalInterest_PolicyRequiredIndicator_A", True, "evidence: a copy of the policy")
    put(F, "AdditionalInterest_CertificateRequiredIndicator_A", BY_RULE, "",
        "the bank: 'a certificate of insurance alone is NOT acceptable' - evidence is the policy")
    put(F, "AdditionalInterest_SendBillIndicator_A", BY_RULE, "", "'Do not send premium bills to the bank'")
    for col in ("Item_VehicleProducerIdentifier_A", "Item_BoatProducerIdentifier_A",
                "Item_AirportIdentifier_A", "Item_AircraftProducerIdentifier_A",
                "Item_ScheduledItemClassCode_A", "Item_ScheduledItemProducerIdentifier_A"):
        put(F, f"AdditionalInterest_{col}", NO_DATA, "", "the interest is in a building")
    put(F, "AdditionalInterest_FullName_B", BY_RULE, "", "ACORD: 'as used here, this is the name of "
        "the TRUST' - question 11 is NO", trap=D.TRUST_NAME)

    # GENERAL INFORMATION 1-15
    for code, q in Q.items():
        yn(F, f"CommercialPolicy_Question_{code}Code_A", q["answer"],
           f"question {q['n']}: the signed supplement" + (" + the CFO's e-mail" if q["answer"] else ""),
           trap={"AAI": "the 2024 application's dissolved parent; a shareholder's trust",
                 "AAF": "a citation that WAS corrected is not uncorrected",
                 "KAK": "a CUSTOMER's Chapter 11; a repossession BY the applicant; policy wording",
                 "KAB": "policy wording about fraud; the word 'arson' in a clause",
                 "KAL": "a judgment WON by the applicant; the bank's UCC filings",
                 "ABB": "a shareholder's revocable trust",
                 "KAN": "the SUPERSEDED 2024 application said Y (drone sold June 2025)"}.get(code, ""))
    put(F, "BusinessInformation_ParentOrganizationName_A", BY_RULE, "", "1a is NO", trap=D.TRUST_NAME)
    put(F, "Subsidiary_ParentSubsidiaryRelationshipDescription_A", BY_RULE, "", "1a is NO")
    put(F, "Subsidiary_ParentOwnershipPercent_A", BY_RULE, "", "1a is NO", trap="60%")
    put(F, "Subsidiary_OrganizationName_A", EXPECT, D.SUB["name"], "1b", trap=D.JV["name"] + " (40%)")
    put(F, "Subsidiary_ParentSubsidiaryRelationshipDescription_B", EXPECT, D.SUB["relationship"], "1b")
    put(F, "Subsidiary_ParentOwnershipPercent_B", EXPECT, D.SUB["pct"], "1b")
    S = D.SAFETY
    tick(F, "CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A", S["manual"])
    tick(F, "CommercialPolicy_FormalSafetyProgram_SafetyPositionIndicator_B", S["position"])
    tick(F, "CommercialPolicy_FormalSafetyProgram_MonthlyMeetingsIndicator_B", S["monthly"],
         "meetings are QUARTERLY", trap="monthly meetings stopped in 2023")
    tick(F, "CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B", S["osha"], "follows OSHA 29 CFR 1910")
    tick(F, "CommercialPolicy_FormalSafetyProgram_OtherIndicator_B", S["other"])
    put(F, "CommercialPolicy_FormalSafetyProgram_OtherDescription_B", EXPECT, S["other_text"])
    put(F, "CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A", EXPECT,
        Q["ABC"]["explain"])
    put(F, "OtherPolicy_PolicyNumberIdentifier_A", EXPECT, D.OTHER_POLICIES[0][1], "question 4",
        trap="the INCUMBENT's policies are not with this company")
    put(F, "OtherPolicy_LineOfBusinessCode_A", NOT_SCORED, "", "ACORD wants a line CODE; the repo "
        "has no ACORD line-of-business code table")
    for r in "BCD":
        put(F, f"OtherPolicy_PolicyNumberIdentifier_{r}", NO_DATA, "", "one policy only",
            trap=f"{D.TEM_POLICY} (WC) is with Tennessee Employers Mutual, not Ridgeline")
        put(F, f"OtherPolicy_LineOfBusinessCode_{r}", NO_DATA)
    Cn = D.CANCEL
    tick(F, "CancelNonRenew_NonRenewalIndicator_A", Cn["nonrenewal"], "the VF&M notice of nonrenewal")
    tick(F, "CancelNonRenew_UnderwritingIndicator_A", Cn["underwriting"], "the notice's reason")
    tick(F, "CancelNonRenew_UnderwritingConditionCorrectedIndicator_A", Cn["corrected"], "roof replaced")
    put(F, "CancelNonRenew_UnderwritingConditionCorrectedDescription_A", EXPECT, Cn["corrected_text"])
    put(F, "CancelNonRenew_NonPaymentIndicator_A", BY_RULE, "", "the 2023 notice of cancellation for "
        "non-payment was RESCINDED - no cancellation took effect", trap="the rescinded notice")
    tick(F, "CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A", False)
    tick(F, "CancelNonRenew_OtherIndicator_A", False)
    put(F, "CancelNonRenew_OtherDescription_A", NO_DATA)
    put(F, "CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A",
        BY_RULE, "", "question 6 is NO")
    put(F, "CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A",
        NO_DATA, "", "question 7 is UNRESOLVED")
    for blk, why in (("UncorrectedFireCodeViolation", "question 8 is NO - the citation was corrected"),
                     ("ForeclosureRepossessionBankruptcy", "question 9 is UNRESOLVED - and the "
                      "bankruptcy / repossession in the package are a CUSTOMER's"),
                     ("JudgementOrLien", "question 10 is NO - the judgment was won BY the applicant")):
        verdict = NO_DATA if blk == "ForeclosureRepossessionBankruptcy" else BY_RULE
        for row in "AB":
            for suf in ("Explanation", "_OccurrenceDate", "_ResolutionDate", "_ResolutionDescription"):
                put(F, f"CommercialPolicy_{blk}{suf}_{row}", verdict, "", why,
                    trap={"UncorrectedFireCodeViolation": "02/11/2026 / 03/02/2026",
                          "ForeclosureRepossessionBankruptcy": "Riverside Bistro Group; Gallatin Pike Diner",
                          "JudgementOrLien": "$22,480 v. Two Rivers Catering"}[blk] if row == "A" else "")
    put(F, "CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A", EXPECT,
        Q["KAM"]["explain"])
    put(F, "CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A", BY_RULE, "",
        "question 14 is NO", trap="the 2024 application's DJI Mavic")
    put(F, "CommercialPolicy_ApplicantHireOthersOperateDronesExplanation_A", EXPECT, Q["KAO"]["explain"])

    # PRIOR CARRIER - three substantiated years
    for row, term in zip("ABC", D.PRIOR_TERMS):
        put(F, f"PriorCoverage_PolicyYear_{row}", EXPECT, term["year"])
        for g in D.GRID_LINE_NAMES:
            cell = term["lines"].get(g)
            for fld in ("InsurerFullName", "PolicyNumberIdentifier", "TotalPremiumAmount",
                        "EffectiveDate", "ExpirationDate"):
                name = f"PriorCoverage_{g}_{fld}_{row}"
                if cell is None:
                    put(F, name, NO_DATA, "", "no umbrella before 12/01/2024")
                    continue
                carrier, pol, prem = cell
                v = {"InsurerFullName": carrier, "PolicyNumberIdentifier": pol,
                     "TotalPremiumAmount": prem, "EffectiveDate": term["eff"],
                     "ExpirationDate": term["exp"]}[fld]
                if v is None:
                    put(F, name, NO_DATA, "", "the VF&M loss run prints no premium - populate only "
                        "what is substantiated and REQUEST it")
                else:
                    put(F, name, EXPECT, v, "loss runs / declarations")
    put(F, "PriorCoverage_OtherLine_LineOfBusinessCode_A", NOT_SCORED, "",
        "ACORD wants a CODE (umbrella); the repo has no code table")

    # LOSS HISTORY - three claims in five years, latest valuation
    for row, x in zip("ABC", D.LOSSES):
        for col, k in (("OccurrenceDate", "occurrence"), ("ClaimDate", "claim"),
                       ("LineOfBusiness", "line"), ("OccurrenceDescription", "desc"),
                       ("PaidAmount", "paid"), ("ReservedAmount", "reserved"),
                       ("ClaimStatus_SubrogationCode", "subro"), ("ClaimStatus_OpenCode", "open")):
            trap = ""
            if row == "A" and k in ("paid", "reserved"):
                trap = "the 12/31/2025 valuation and the stale August summary"
            if row == "C" and k == "occurrence":
                trap = "reported under the FORMER name - same insured"
            put(F, f"LossHistory_{col}_{row}", EXPECT, x[k], f"loss run, claim {x['claim_no']}", trap=trap)
    put(F, "LossHistory_InformationYearCount_A", EXPECT, D.LOSS_YEARS, "the market requires 5 years")
    put(F, "LossHistory_TotalAmount_A", EXPECT, D.TOTAL_PAID, "ACORD tooltip: PAID - the sum of the "
        "three rows' paid amounts", trap=f"{D.TOTAL_INCURRED} is incurred", source="derived")
    put(F, "LossHistory_NoPriorLossesIndicator_A", BY_RULE, "", "three claims exist",
        trap="'Umbrella - no known losses' and 'no losses in the past 3 years' are narrative")

    # SIGNATURES
    put(F, "NamedInsured_Initials_A", BY_RULE, "", "AUTHORSHIP")
    _common_tail(F)


L1, L2, L3 = D.LOCATIONS


# ════════════════════════════════════════════════════════════════════════════
# ACORD 126
# ════════════════════════════════════════════════════════════════════════════
def build_126():
    F = "ACORD_126"
    G = D.GL_LIMITS
    put(F, "Form_EditionIdentifier_A", EXPECT, "ACORD 126 (2025/03)", "the template's footer",
        source="template")
    _section_header(F, "OHM-GL-4471902-25")
    tick(F, "GeneralLiability_CoverageIndicator_A", True, "commercial general liability is requested")
    tick(F, "GeneralLiability_OccurrenceIndicator_A", True, "occurrence form, as expiring")
    put(F, "GeneralLiability_ClaimsMadeIndicator_A", BY_RULE, "", "occurrence form",
        trap="the separate E&O policy is claims-made")
    tick(F, "GeneralLiability_OwnersAndContractorsProtectiveIndicator_A", False)
    tick(F, "GeneralLiability_OtherCoverageIndicator_A", False)
    put(F, "GeneralLiability_OtherCoverageDescription_A", NO_DATA)
    tick(F, "GeneralLiability_PropertyDamage_DeductibleIndicator_A", True, "requested")
    put(F, "GeneralLiability_PropertyDamage_DeductibleAmount_A", EXPECT, D.GL_PD_DEDUCTIBLE,
        trap="the expiring policy has none")
    tick(F, "GeneralLiability_DeductiblePerOccurrenceIndicator_A", True, "per occurrence")
    tick(F, "GeneralLiability_DeductiblePerClaimIndicator_A", False)
    tick(F, "GeneralLiability_BodilyInjury_DeductibleIndicator_A", False, "'Bodily injury deductible: none'")
    put(F, "GeneralLiability_BodilyInjury_DeductibleAmount_A", NO_DATA)
    tick(F, "GeneralLiability_OtherDeductibleIndicator_A", False)
    put(F, "GeneralLiability_OtherDeductibleDescription_A", NO_DATA)
    put(F, "GeneralLiability_OtherDeductibleAmount_A", NO_DATA,
        trap="the $1,000 EBL deductible has its own box")
    put(F, "GeneralLiability_GeneralAggregate_LimitAmount_A", EXPECT, G["general_aggregate"][0])
    tick(F, "GeneralLiability_GeneralAggregate_LimitAppliesPerLocationIndicator_A", True,
         "CG 25 04 requested", trap="the expiring aggregate is per policy")
    put(F, "GeneralLiability_GeneralAggregate_LimitAppliesPerPolicyIndicator_A", BY_RULE, "",
        "the requested aggregate is per LOCATION", trap="expiring: per policy")
    tick(F, "GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A", False)
    tick(F, "GeneralLiability_GeneralAggregate_LimitAppliesToOtherIndicator_A", False)
    put(F, "GeneralLiability_GeneralAggregate_LimitAppliesToCode_A", NO_DATA)
    for fld, k in (("GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount_A", "products"),
                   ("GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount_A", "personal_adv"),
                   ("GeneralLiability_EachOccurrence_LimitAmount_A", "each_occurrence"),
                   ("GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A", "rented_premises"),
                   ("GeneralLiability_MedicalExpense_EachPersonLimitAmount_A", "medical"),
                   ("GeneralLiability_EmployeeBenefits_LimitAmount_A", "ebl")):
        req, exp = G[k]
        put(F, fld, EXPECT, req, "REQUESTED limit", trap=f"{exp} is the EXPIRING limit" if exp else
            "the umbrella's $5,000,000")
    put(F, "GeneralLiability_OtherCoverageLimitDescription_A", NO_DATA)
    put(F, "GeneralLiability_OtherCoverageLimitAmount_A", NO_DATA)
    for fld in ("GeneralLiability_PremisesOperations_PremiumAmount_A", "GeneralLiability_Products_PremiumAmount_A",
                "GeneralLiability_OtherCoveragePremiumAmount_A", "GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A"):
        put(F, fld, BY_RULE, "", QUOTE_RULE, trap="$38,420 expiring")
    put(F, "GeneralLiabilityLineOfBusiness_RemarkText_A", EXPECT, D.GL_REMARKS)
    put(F, "GeneralLiabilityLineOfBusiness_RemarkText_B", NO_DATA)
    for fld in ("GeneralLiability_UninsuredUnderinsuredMotorists_CoverageAvailableIndicator_A",
                "GeneralLiability_UninsuredUnderinsuredMotorists_CoverageAvailableNoIndicator_A",
                "GeneralLiability_MedicalPayments_CoverageAvailableIndicator_A",
                "GeneralLiability_MedicalPayments_CoverageAvailableNoIndicator_A"):
        put(F, fld, NOT_SCORED, "", "state-specific options; medical EXPENSE is requested but this box "
            "is ambiguous for Tennessee")
    for row, h in zip("ABC", D.GL_HAZARDS):
        put(F, f"GeneralLiability_Hazard_LocationProducerIdentifier_{row}", EXPECT, h["loc"])
        put(F, f"GeneralLiability_Hazard_HazardProducerIdentifier_{row}", EXPECT, h["haz"])
        put(F, f"GeneralLiability_Hazard_ClassCode_{row}", EXPECT, h["code"])
        put(F, f"GeneralLiability_Hazard_PremiumBasisCode_{row}", EXPECT, h["basis"])
        put(F, f"GeneralLiability_Hazard_Exposure_{row}", EXPECT, h["exposure"],
            "the PROPOSED-term estimate", trap=f"{h['exp_exposure']} expiring" if h["exp_exposure"] != h["exposure"] else "")
        put(F, f"GeneralLiability_Hazard_TerritoryCode_{row}", EXPECT, h["terr"])
        put(F, f"GeneralLiability_Hazard_Classification_{row}", EXPECT, h["desc"])
        SEMANTIC_EXTRA[F].add(f"GeneralLiability_Hazard_Classification_{row}")
        for fld in ("PremisesOperationsRate", "ProductsRate", "PremisesOperationsPremiumAmount",
                    "ProductsPremiumAmount"):
            put(F, f"GeneralLiability_Hazard_{fld}_{row}", BY_RULE, "", "rates and premiums are "
                "quoted by the company", trap=f"expiring rate {h['rate']} / premium {h['premium']}")
    for fld in ("GeneralLiability_ClaimsMade_ProposedRetroactiveDate_A",
                "GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate_A"):
        put(F, fld, BY_RULE, "", "occurrence form", trap="03/01/2015 is the E&O policy's retro date")
    put(F, "GeneralLiability_EmployeeBenefits_PerClaimDeductibleAmount_A", EXPECT, D.EBL["deductible"])
    put(F, "GeneralLiability_EmployeeBenefits_EmployeeCount_A", EXPECT, D.EBL["employees"])
    put(F, "GeneralLiability_EmployeeBenefits_EmployeeCoveredCount_A", EXPECT, D.EBL["covered"])
    put(F, "GeneralLiability_EmployeeBenefits_RetroactiveDate_A", EXPECT, D.EBL["retro"],
        trap="03/01/2015 is the E&O retro")
    # questions
    for code, (ans, expl_field, expl) in D.Q126.items():
        yn(F, code, ans, "the GL supplemental" if ans else "")
        if expl_field:
            if ans == "Y":
                put(F, expl_field, EXPECT, expl)
    expl_fields = {
        "GeneralLiabilityLineOfBusiness_AnyProductWorkAccidentLocationExcludedUninsuredPreviousCoverageExplanation_A",
        "GeneralLiabilityLineOfBusiness_TailCoveragePurchasedPreviousPolicyExplanation_A",
        "GeneralLiabilityLineOfBusiness_OperationsIncludeBlastingExplanation_A",
        "GeneralLiabilityLineOfBusiness_OperationsIncludeEvacuationExplanation_A",
        "GeneralLiabilityLineOfBusiness_SubcontractorsWorksWithoutCertificatesOfInsuranceExplanation_A",
        "GeneralLiabilityLineOfBusiness_ProductsRelatedToAircraftIndustryExplanation_A",
        "GeneralLiabilityLineOfBusiness_ProductsUnderLabelOfOthersExplanation_A",
        "GeneralLiabilityLineOfBusiness_VendorCoverageRequiredExplanation_A",
        "GeneralLiabilityLineOfBusiness_AnyMedicalFacilitiesProvidedMedicalProfessionalsEmployedExplanation_A",
        "GeneralLiabilityLineOfBusiness_AnyExposureRadioactiveMaterialsExplanation_A",
        "GeneralLiabilityLineOfBusiness_WatercraftDocksFloatsOwnedHiredLeasedExplanation_A",
        "GeneralLiabilityLineOfBusiness_FeeChargedForParkingExplanation_A",
        "GeneralLiabilityLineOfBusiness_RecreationalFacilitiesProvidedExplanation_A",
        "GeneralLiabilityLineOfBusiness_DemolitionExposureContemplatedExplanation_A",
        "GeneralLiabilityLineOfBusiness_DayCareFacilitiesOperatedExplanation_A",
        "GeneralLiabilityLineOfBusiness_BusinessPromotionalLiteratureSafetyRepresentationsExplanation_A",
    }
    for fld in sorted(expl_fields):
        put(F, fld, BY_RULE, "", "its question is NO or UNRESOLVED - no explanation")
    put(F, "GeneralLiability_Otherlodgingoperationsdescription_A", NO_DATA, "", "lodging UNRESOLVED")
    put(F, "BuildingOccupancy_ApartmentCount_A", NO_DATA)
    put(F, "BuildingOccupancy_ApartmentArea_A", NO_DATA)
    for k in ("ApprovedFenceIndicator", "LimitedAccessIndicator", "DivingBoardIndicator", "SlideIndicator",
              "AboveGroundIndicator", "InGroundIndicator", "LifeGuardIndicator"):
        put(F, f"SwimmingPool_{k}_A", NO_DATA, "", "swimming pool UNRESOLVED")
    T = D.ATHLETIC_TEAM
    put(F, "AthleticTeam_SportDescription_A", EXPECT, T["sport"])
    put(F, "AthleticTeam_ContactSportCode_A", EXPECT, T["contact"])
    tick(F, "AthleticTeam_AgeGroup_OverEighteenIndicator_A", True, "an adult league")
    tick(F, "AthleticTeam_AgeGroup_TwelveAndUnderIndicator_A", False, trap="'no youth teams'")
    tick(F, "AthleticTeam_AgeGroup_ThirteenThroughEighteenIndicator_A", False)
    put(F, "AthleticTeam_SponsorshipExtentDescription_A", EXPECT, T["extent"])
    for k in ("SportDescription", "ContactSportCode", "SponsorshipExtentDescription"):
        put(F, f"AthleticTeam_{k}_B", NO_DATA, "", "one team")
    for k in ("TwelveAndUnderIndicator", "ThirteenThroughEighteenIndicator", "OverEighteenIndicator"):
        put(F, f"AthleticTeam_AgeGroup_{k}_B", NO_DATA)
    # loaned equipment
    put(F, "GeneralLiabilityLineOfBusiness_MachineryOrEquipmentLoanedRentedOthersExplanation_B", NO_DATA)
    tick(F, "CommercialInlandMarineProperty_PropertySubClass_LargeEquipmentIndicator_A", True,
         "combi ovens and refrigerators")
    tick(F, "CommercialInlandMarineProperty_PropertySubClass_SmallToolsIndicator_A", False)
    put(F, "PropertyItem_ItemDetail_InstructionGivenCode_A", EXPECT, D.LOANER["instruction"])
    for k in ("CommercialInlandMarineProperty_PropertySubClass_SmallToolsIndicator_B",
              "CommercialInlandMarineProperty_PropertySubClass_LargeEquipmentIndicator_B",
              "PropertyItem_ItemDetail_InstructionGivenCode_B"):
        put(F, k, NO_DATA)
    # contractors
    put(F, "Contractors_SubcontractorsPaidAmount_A", EXPECT, D.SUBS_PAID)
    put(F, "Contractors_WorkSubcontractedPercent_A", EXPECT, D.SUBS_PCT)
    put(F, "Contractors_FullTimeEmployeeCount_A", EXPECT, "66", trap="73 is the head count")
    put(F, "Contractors_PartTimeEmployeeCount_A", EXPECT, "7", trap="9 agency temps")
    put(F, "GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A", EXPECT, D.SUBS_WORK)
    # products
    for row, p in zip("ABC", D.PRODUCTS):
        for col, k in (("ProductName", "name"), ("AnnualGrossSalesAmount", "sales"),
                       ("UnitCount", "units"), ("InMarketMonthCount", "months"),
                       ("ExpectedLifeMonthCount", "life"), ("IntendedUse", "use"),
                       ("PrincipalComponents", "components")):
            put(F, f"ProductAndCompletedOperations_{col}_{row}", EXPECT, p[k],
                trap="a GL rating class is not a product" if col == "ProductName" else "")
            if col in ("ProductName", "IntendedUse", "PrincipalComponents"):
                SEMANTIC_EXTRA[F].add(f"ProductAndCompletedOperations_{col}_{row}")
    # additional interest - the landlord, additional insured
    A = D.LANDLORD_AI
    tick(F, "AdditionalInterest_Interest_AdditionalInsuredIndicator_A", True, "the lease requires it")
    for k in ("EmployeeAsLessorIndicator", "LienholderIndicator", "LendersLossPayableIndicator",
              "LossPayeeIndicator", "MortgageeIndicator", "OtherIndicator"):
        tick(F, f"AdditionalInterest_Interest_{k}_A", False, "an additional insured",
             trap="the bank is a PROPERTY mortgagee" if k == "MortgageeIndicator" else "")
    put(F, "AdditionalInterest_Interest_OtherDescription_A", NO_DATA)
    put(F, "AdditionalInterest_InterestRank_A", NO_DATA)
    tick(F, "AdditionalInterest_CertificateRequiredIndicator_A", True, "the lease requires a certificate")
    for col, v in (("FullName_A", A["name"]), ("MailingAddress_LineOne_A", A["l1"]),
                   ("MailingAddress_LineTwo_A", A["l2"]), ("MailingAddress_CityName_A", A["city"]),
                   ("MailingAddress_StateOrProvinceCode_A", A["state"]),
                   ("MailingAddress_PostalCode_A", A["zip"]),
                   ("Item_LocationProducerIdentifier_A", A["loc"]),
                   ("Item_BuildingProducerIdentifier_A", A["bldg"]), ("ItemDescription_A", A["item"])):
        put(F, f"AdditionalInterest_{col}", EXPECT, v, "lease abstract + GL supplemental")
    put(F, "AdditionalInterest_MailingAddress_CountryCode_A", NOT_SCORED, "", "no country printed")
    put(F, "AdditionalInterest_AccountNumberIdentifier_A", NO_DATA)
    put(F, "AdditionalInterest_Item_ScheduledItemProducerIdentifier_A", NO_DATA)
    put(F, "AdditionalInterest_Item_ScheduledItemClassCode_A", NO_DATA)
    put(F, "GeneralLiabilityLineOfBusiness_Attachment_AdditionalInterestIndicator_A", BY_RULE, "",
        "one interest - no ACORD 45")
    for row in "BCDE":
        put(F, f"AdditionalInterest_FullName_{row}", BY_RULE, "", "no leased employees (question NO)",
            trap=f"{D.STAFFING} supplies TEMPORARY workers")
    for row in "ABCD":
        put(F, f"AdditionalInterest_WorkersCompensationCarriedCode_{row}", BY_RULE, "",
            "no leased employees")
    _common_tail(F)


# ════════════════════════════════════════════════════════════════════════════
# ACORD 127
# ════════════════════════════════════════════════════════════════════════════
def build_127():
    F = "ACORD_127"
    put(F, "Form_EditionIdentifier_A", EXPECT, "ACORD 127 (2015/12)", "the template's footer",
        source="template")
    _section_header(F, "OHM-CA-4471903-25")
    put(F, "CommercialVehicleLineOfBusiness_Attachment_CommercialAutoDriverInformationScheduleIndicator_A",
        BY_RULE, "", "six drivers fit on the form")
    put(F, "CommercialVehicleLineOfBusiness_Attachment_VehicleScheduleIndicator_A", BY_RULE, "",
        "four vehicles fit on the form", trap="the SOLD E-350 would make five")
    put(F, "CommercialVehicleLineOfBusiness_Attachment_AdditionalInterestIndicator_A", BY_RULE, "",
        "two interests fit on the form")
    # drivers A-F, G-M empty
    cols = (("ProducerIdentifier", "num"), ("GivenName", "first"), ("OtherGivenNameInitial", "mi"),
            ("Surname", "last"), ("MailingAddress_CityName", "city"),
            ("MailingAddress_StateOrProvinceCode", "state"), ("MailingAddress_PostalCode", "zip"),
            ("GenderCode", "sex"), ("MaritalStatusCode", "marital"), ("BirthDate", "dob"),
            ("ExperienceYearCount", "exp"), ("LicensedYear", "lic_year"),
            ("LicenseNumberIdentifier", "lic"), ("LicensedStateOrProvinceCode", "lic_state"),
            ("HiredDate", "hired"), ("Vehicle_ProducerIdentifier", "veh"), ("Vehicle_UsePercent", "pct"))
    rows = "ABCDEFGHIJKLM"
    for i, row in enumerate(rows):
        d = D.DRIVERS[i] if i < len(D.DRIVERS) else None
        for col, k in cols:
            fld = f"Driver_{col}_{row}"
            if d is None:
                put(F, fld, NO_DATA, "", "six drivers only",
                    trap="Ambrose (terminated), Lindqvist (own car), Ellison (DOC only)")
            elif d[k]:
                put(F, fld, EXPECT, d[k], f"driver {d['num']} ({d['first']} {d['last']}): the HR driver "
                    "roster / MVR",
                    trap="Franklin, KY - not Franklin, TN" if (d["num"] == "3" and k in ("state", "city")) else "")
            else:
                put(F, fld, NO_DATA, "", "driver 5 is a relief driver with no assigned vehicle")
        put(F, f"Driver_TaxIdentifier_{row}", BY_RULE, "", "never print an SSN - the MVRs show "
            "masked fragments only", trap="XXX-XX-4471")
        put(F, f"Driver_Coverage_BroadenedNoFaultCode_{row}", NO_DATA, "", "Tennessee is not no-fault")
        put(F, f"Driver_Coverage_DriverOtherCarCode_{row}", NO_DATA, "", "no listed driver has Drive "
            "Other Car - the named individual is not a driver", trap="Margaret A. Ellison")
    # questions
    for code, (ans, expl_field, expl) in D.Q127.items():
        yn(F, code, ans, "the auto supplemental" if ans else "")
        if expl_field and ans == "Y":
            put(F, expl_field, EXPECT, expl)
    for fld in ("CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A",
                "CommercialVehicleLineOfBusiness_HoldHarmlessAgreementsExplanation_A",
                "CommercialVehicleLineOfBusiness_VehiclesUsedByFamilyMembersExplanation_A",
                "CommercialVehicleLineOfBusiness_AnyDriversNotCoveredWorkersCompensationExplanation_A",
                "CommercialVehicleLineOfBusiness_AnyVehiclesOwnedNotScheduledExplanation_A",
                "CommercialVehicleLineOfBusiness_AgentInspectedVehiclesExplanation_A"):
        put(F, fld, BY_RULE, "", "its question is NO")
    for row in "AB":
        put(F, f"Vehicle_ProducerIdentifier_A{row}", BY_RULE, "", "'not solely owned' is NO")
    for row in "CD":
        put(F, f"AdditionalInterest_FullName_{row}", BY_RULE, "", "ACORD: 'the other owner of the "
            "vehicle' - every vehicle is solely owned (encumbrances only)",
            trap="the lienholder / loss payee are interests, not owners")
    for row, e in zip("CD", D.SPECIAL_EQUIPMENT):
        put(F, f"Vehicle_ProducerIdentifier_A{row}", EXPECT, e["veh"], "special equipment row "
            f"{'A' if row == 'C' else 'B'} (template position)")
    for row, e in zip("AB", D.SPECIAL_EQUIPMENT):
        put(F, f"Vehicle_Question_ModifiedEquipmentDescription_{row}", EXPECT, e["desc"])
        put(F, f"Vehicle_Question_ModifiedEquipmentCostAmount_{row}", EXPECT, e["cost"])
    C = D.CONVICTION
    put(F, "AccidentConviction_DriverProducerIdentifier_A", EXPECT, C["driver"])
    put(F, "AccidentConviction_TrafficViolationDate_A", EXPECT, C["date"], trap="09/02/2019 is outside 3 years")
    put(F, "AccidentConviction_TrafficViolationDescription_A", EXPECT, C["desc"])
    put(F, "AccidentConviction_PlaceOfIncident_A", EXPECT, C["place"])
    put(F, "AccidentConviction_ViolationYearCount_A", EXPECT, C["years"])
    T = D.TELEMATICS
    put(F, "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A",
        EXPECT, T["pct"])
    for fld, k in (("ElectronicDataMonitoringDevice_MonitorDriverSafetyIndicator_A", "driver_safety"),
                   ("ElectronicDataMonitoringDevice_TrackFuelConsumptionIndicator_A", "fuel"),
                   ("ElectronicDataMonitoringDevice_MonitorVehicleMaintenanceIndicator_A", "maintenance"),
                   ("ElectronicDataMonitoringDevice_MileageTrackingDeviceIndicator_A", "mileage"),
                   ("LocationTrackingDeviceIndicator_A", "location"),
                   ("ElectronicDataMonitoringDevice_NavigationIndicator_A", "navigation"),
                   ("ElectronicDataMonitoringDevice_OtherIndicator_A", "other")):
        tick(F, f"CommercialVehicleLineOfBusiness_{fld}", T[k], "the FleetPulse report",
             trap="fuel tracking is NOT subscribed" if k == "fuel" else "")
    put(F, "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_OtherDesciption_A", EXPECT,
        T["other_text"])
    put(F, "CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_AdditionalDescription_A",
        EXPECT, T["additional"])
    put(F, "CommercialVehicleLineOfBusiness_GarageStorageDescription_A", EXPECT, D.GARAGE_STORAGE)
    put(F, "CommercialVehicleLineOfBusiness_MaximumExposureAllVehiclesAmount_A", EXPECT, D.MAX_EXPOSURE)
    SEMANTIC_EXTRA[F].update({"CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_AdditionalDescription_A",
                              "CommercialVehicleLineOfBusiness_GarageStorageDescription_A",
                              "Vehicle_Question_ModifiedEquipmentDescription_A",
                              "Vehicle_Question_ModifiedEquipmentDescription_B",
                              "AccidentConviction_TrafficViolationDescription_A"})
    # additional interests (vehicles)
    kinds = ("AdditionalInsuredIndicator", "EmployeeAsLessorIndicator", "LendersLossPayableIndicator",
             "LienholderIndicator", "LossPayeeIndicator", "OwnerIndicator", "RegistrantIndicator",
             "OtherIndicator")
    want = {"Lienholder": "LienholderIndicator", "Loss Payee": "LossPayeeIndicator"}
    for row, a in zip("AB", D.AUTO_AI):
        put(F, f"AdditionalInterest_FullName_{row}", EXPECT, a["name"], "the auto declarations")
        for k in kinds:
            tick(F, f"AdditionalInterest_Interest_{k}_{row}", k == want[a["type"]])
        put(F, f"AdditionalInterest_Interest_OtherDescription_{row}", NO_DATA)
        for col, k in (("MailingAddress_LineOne", "l1"), ("MailingAddress_CityName", "city"),
                       ("MailingAddress_StateOrProvinceCode", "state"), ("MailingAddress_PostalCode", "zip"),
                       ("InterestRank", "rank"), ("AccountNumberIdentifier", "acct"),
                       ("Item_VehicleProducerIdentifier", "veh")):
            put(F, f"AdditionalInterest_{col}_{row}", EXPECT, a[k])
        if a["l2"]:
            put(F, f"AdditionalInterest_MailingAddress_LineTwo_{row}", EXPECT, a["l2"])
        else:
            put(F, f"AdditionalInterest_MailingAddress_LineTwo_{row}", NO_DATA)
        tick(F, f"AdditionalInterest_CertificateRequiredIndicator_{row}", True, "'certificate required'")
        put(F, f"AdditionalInterest_Item_LocationProducerIdentifier_{row}", NO_DATA, "", "a vehicle interest")
    put(F, "CommercialVehicleLineOfBusiness_RemarkText_A", EXPECT, D.AUTO_REMARKS)
    put(F, "CommercialVehicleLineOfBusiness_RemarkText_B", NO_DATA)
    # vehicles A-D
    use_kinds = ("PleasureIndicator", "FarmIndicator", "CommercialIndicator", "RetailIndicator",
                 "ServiceIndicator", "ForHireIndicator", "OtherIndicator")
    for row, v in zip("ABCD", D.VEHICLES):
        loc = D.LOCATIONS[int(v["loc"]) - 1]
        for col, val in (("ProducerIdentifier", v["num"]), ("ModelYear", v["year"]),
                         ("ManufacturersName", v["make"]), ("ModelName", v["model"]),
                         ("BodyCode", v["body"]), ("VINIdentifier", v["vin"]),
                         ("PhysicalAddress_LineOne", loc["l1"]), ("PhysicalAddress_CityName", loc["city"]),
                         ("PhysicalAddress_CountyName", loc["county"]),
                         ("PhysicalAddress_StateOrProvinceCode", loc["state"]),
                         ("PhysicalAddress_PostalCode", loc["zip"]),
                         ("Registration_StateOrProvinceCode", "TN"), ("RatingTerritoryCode", v["terr"]),
                         ("GrossVehicleWeight", v["gvw"]), ("RateClassCode", v["cls"]),
                         ("RadiusOfUse", v["radius"]), ("CostNewAmount", v["cost"]),
                         ("Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount", v["comp_ded"]),
                         ("Collision_DeductibleAmount", v["coll_ded"])):
            trap = ""
            if col == "CostNewAmount":
                trap = f"{v['acv_decoy']} is the current ACV"
            if col == "Collision_DeductibleAmount" and v["num"] == "4":
                trap = "$1,000 is the EXPIRING deductible"
            put(F, f"Vehicle_{col}_{row}", EXPECT, val, f"vehicle {v['num']} ({v['year']} {v['make']}): "
                "auto declarations / endorsement 1 / auto supplemental",
                trap=trap)
        SEMANTIC_EXTRA[F].add(f"Vehicle_BodyCode_{row}")
        for sym in ("SymbolCode", "ComprehensiveSymbolCode", "CollisionSymbolCode"):
            put(F, f"Vehicle_{sym}_{row}", NOT_SCORED, "", "physical-damage RATING symbols vs covered-auto "
                "symbol 7 - owner decision (127 SYM columns are owned blanks since 24 Sep)")
        put(F, f"Vehicle_SpecialIndustryClassCode_{row}", NO_DATA)
        for fld in ("PrimaryLiabilityRatingFactor", "NetRatingFactor", "TotalPremiumAmount"):
            put(F, f"Vehicle_{fld}_{row}", BY_RULE, "", QUOTE_RULE, trap=f"{v['premium']} expiring")
        put(F, f"Vehicle_SeatingCapacityCount_{row}", NO_DATA, "", "not a public passenger vehicle")
        put(F, f"Vehicle_FarthestZoneCode_{row}", NO_DATA)
        tick(F, f"Vehicle_VehicleType_CommercialIndicator_{row}", True, "trucks and vans - stated")
        tick(F, f"Vehicle_VehicleType_PrivatePassengerIndicator_{row}", False)
        tick(F, f"Vehicle_VehicleType_SpecialIndicator_{row}", False)
        for k in use_kinds:
            tick(F, f"Vehicle_Use_{k}_{row}", k == f"{v['use']}Indicator", f"USE: {v['use']}")
        put(F, f"Vehicle_Use_OtherDescription_{row}", NO_DATA)
        cov = {"LiabilityIndicator": True, "NoFaultIndicator": False, "AdditionalNoFaultIndicator": False,
               "MedicalPaymentsIndicator": True, "UninsuredMotoristsIndicator": True,
               "UnderinsuredMotoristsIndicator": True, "TowingAndLabourIndicator": v["towing"],
               "SpecifiedCauseOfLossIndicator": False, "FireIndicator": False, "FireTheftIndicator": False,
               "FireTheftWindstormIndicator": False, "LimitedSpecifiedPerilsIndicator": False,
               "ComprehensiveIndicator": True, "CollisionIndicator": True,
               "RentalReimbursementIndicator": v["rental"], "FullGlassIndicator": False,
               "OtherIndicator": False, "ValuationActualCashValueIndicator": True,
               "ValuationAgreedAmountIndicator": False, "ValuationStatedAmountIndicator": False,
               "ComprehensiveDeductibleIndicator": True, "SpecifiedCauseOfLossDeductibleIndicator": False}
        for k, on in cov.items():
            tick(F, f"Vehicle_Coverage_{k}_{row}", on, "requested coverages",
                 trap="towing is ADDED at this submission" if k == "TowingAndLabourIndicator" and on else "")
        put(F, f"Vehicle_Coverage_OtherDescription_{row}", NO_DATA)
        put(F, f"Vehicle_Coverage_AgreedOrStatedAmount_{row}", NO_DATA, "", "actual cash value")
        tick(F, f"Vehicle_Use_UnderFifteenMilesIndicator_{row}", False, "commuting applies to private passenger")
        tick(F, f"Vehicle_Use_FifteenMilesOrOverIndicator_{row}", False)
    _common_tail(F)


# ════════════════════════════════════════════════════════════════════════════
_NARRATIVE_NAME = re.compile(r"(Description|Explanation|RemarkText|Operations|Relationship)", re.I)


def _match_mode(form: str, field: str, meta: dict) -> str:
    if field in SEMANTIC_EXTRA[form]:
        return "semantic"
    tu = (meta.get("tu") or "").strip().lower()
    if meta.get("ft") == "/Tx" and tu.startswith("enter text") and _NARRATIVE_NAME.search(field):
        return "semantic"
    return "exact"


def build_all() -> dict:
    for f in FORMS:
        FIELDS[f].clear()
        SEMANTIC_EXTRA[f].clear()
    build_125()
    build_126()
    build_127()
    out = {}
    for f in FORMS:
        sch = schema(f)
        unknown = [x for x in FIELDS[f] if x not in sch]
        if unknown:
            raise SystemExit(f"{f}: key names fields NOT on the schema: {unknown[:8]}")
        missing = [x for x in sch if x not in FIELDS[f]]
        if missing:
            raise SystemExit(f"{f}: {len(missing)} boxes left undecided: {missing[:12]}")
        for x, v in FIELDS[f].items():
            v["match"] = _match_mode(f, x, sch.get(x) or {})
        out[f] = sch
    return out


def decoys_for(form: str):
    return {"ACORD_125": D.DECOYS_125, "ACORD_126": D.DECOYS_126, "ACORD_127": D.DECOYS_127}[form]


def assemble(meta: dict) -> dict:
    expect, blanks, forbidden, semantic, counts = {}, {}, {}, {}, {}
    for f in FORMS:
        expect[f] = {x: v["value"] for x, v in FIELDS[f].items() if v["verdict"] == EXPECT}
        blanks[f] = sorted(x for x, v in FIELDS[f].items() if v["verdict"] in (NO_DATA, BY_RULE))
        fb: Dict[str, List[str]] = {}
        for value, scope, _why in decoys_for(f):
            fb.setdefault(scope, []).append(value)
        forbidden[f] = fb
        semantic[f] = {"semantic": sorted(x for x, v in FIELDS[f].items()
                                          if v["verdict"] == EXPECT and v["match"] == "semantic"),
                       "rule": "semantic = ACORD 'Enter text:' AND a narrative field name, plus "
                               "product names / uses / components, classifications, body types"}
        counts[f] = {k: sum(1 for v in FIELDS[f].values() if v["verdict"] == k)
                     for k in (EXPECT, NO_DATA, BY_RULE, NOT_SCORED)}
    shapes = {
        "ACORD_125": {
            "NamedInsured_TaxIdentifier_*": {"regex": r"^\d{2}-?\d{7}$", "why": "a FEIN is nine digits"},
            "NamedInsured_NAICSCode_*": {"regex": r"^\d{6}$", "why": "NAICS is six digits"},
            "NamedInsured_SICCode_*": {"regex": r"^\d{4}$", "why": "SIC is four digits"},
            "*_PostalCode_*": {"regex": r"^\d{5}(-\d{4})?$", "why": "a US ZIP"},
            "*StateOrProvinceCode*": {"regex": r"^[A-Za-z]{2}$", "why": "two letters"},
            "Policy_Payment_PaymentScheduleCode_A": {"regex": r"^[A-Z]{2}$", "why": "AN / MO / QT"},
            "Policy_Audit_FrequencyCode_A": {"regex": r"^[ASQMO]$", "why": "A / S / Q / M / O"},
        },
        "ACORD_126": {
            "GeneralLiability_Hazard_ClassCode_*": {"regex": r"^\d{5}$", "why": "a 5-digit class code"},
            "*_PostalCode_*": {"regex": r"^\d{5}(-\d{4})?$", "why": "a US ZIP"},
        },
        "ACORD_127": {
            "Vehicle_VINIdentifier_*": {"regex": r"^[A-HJ-NPR-Z0-9]{17}$", "why": "a VIN is 17 characters"},
            "Vehicle_ModelYear_*": {"regex": r"^(19|20)\d{2}$", "why": "a model year"},
            "Driver_LicensedYear_*": {"regex": r"^(19|20)\d{2}$", "why": "a year"},
            "Driver_GenderCode_*": {"regex": r"^[MFX]$", "why": "a gender code"},
            "Driver_MaritalStatusCode_*": {"regex": r"^[SMDPWCVFUO]$", "why": "a marital code"},
            "*_PostalCode_*": {"regex": r"^\d{5}(-\d{4})?$", "why": "a US ZIP"},
            "*StateOrProvinceCode*": {"regex": r"^[A-Za-z]{2}$", "why": "two letters"},
        },
    }
    ea125 = D.expected_absent_125()
    row_sets = {
        "ACORD_125": {
            "named_insureds": {"slots": list("ABC"), "columns": {
                "name": "NamedInsured_FullName_{row}", "fein": "NamedInsured_TaxIdentifier_{row}",
                "naics": "NamedInsured_NAICSCode_{row}", "phone": "NamedInsured_Primary_PhoneNumber_{row}",
                "web": "NamedInsured_Primary_WebsiteAddress_{row}"},
                "rows": [{"name": D.NAME, "fein": D.FEIN, "naics": D.NAICS, "phone": D.BUS_PHONE,
                          "web": D.WEBSITE},
                         {"name": D.SUB["name"], "fein": D.SUB["fein"], "naics": D.SUB["naics"],
                          "phone": D.SUB["phone"], "web": D.SUB["web"]}]},
            "premises": {"slots": list("ABCD"), "columns": {
                "loc": "CommercialStructure_Location_ProducerIdentifier_{row}",
                "line1": "CommercialStructure_PhysicalAddress_LineOne_{row}",
                "city": "CommercialStructure_PhysicalAddress_CityName_{row}",
                "zip": "CommercialStructure_PhysicalAddress_PostalCode_{row}",
                "revenue": "CommercialStructure_AnnualRevenueAmount_{row}",
                "ft": "BusinessInformation_FullTimeEmployeeCount_{row}",
                "pt": "BusinessInformation_PartTimeEmployeeCount_{row}",
                "occupied": "BuildingOccupancy_OccupiedArea_{row}",
                "area": "Construction_BuildingArea_{row}"},
                "rows": [{"loc": l["num"], "line1": l["l1"], "city": l["city"], "zip": l["zip"],
                          "revenue": l["revenue"], "ft": l["ft"], "pt": l["pt"],
                          "occupied": l["occupied"], "area": l["total_area"]} for l in D.LOCATIONS]},
            "contacts": {"slots": list("AB"), "columns": {
                "type": "NamedInsured_Contact_ContactDescription_{row}",
                "name": "NamedInsured_Contact_FullName_{row}",
                "phone": "NamedInsured_Contact_PrimaryPhoneNumber_{row}",
                "phone2": "NamedInsured_Contact_SecondaryPhoneNumber_{row}",
                "email": "NamedInsured_Contact_PrimaryEmailAddress_{row}"},
                "rows": [{"type": c["type"], "name": c["name"], "phone": c["phone"], "phone2": c["phone2"],
                          "email": c["email"]} for c in D.CONTACTS]},
            "losses": {"slots": list("ABC"), "columns": {
                "occurrence": "LossHistory_OccurrenceDate_{row}", "line": "LossHistory_LineOfBusiness_{row}",
                "paid": "LossHistory_PaidAmount_{row}", "reserved": "LossHistory_ReservedAmount_{row}",
                "subro": "LossHistory_ClaimStatus_SubrogationCode_{row}",
                "open": "LossHistory_ClaimStatus_OpenCode_{row}"},
                "rows": [{"occurrence": x["occurrence"], "line": x["line"], "paid": x["paid"],
                          "reserved": x["reserved"], "subro": x["subro"], "open": x["open"]}
                         for x in D.LOSSES]},
            "prior_coverage": {"slots": list("ABC"), "columns": {
                f"{g}_{k}": f"PriorCoverage_{g}_{fld}_{{row}}" for g in D.GRID_LINE_NAMES
                for k, fld in (("carrier", "InsurerFullName"), ("policy", "PolicyNumberIdentifier"),
                               ("premium", "TotalPremiumAmount"))},
                "rows": [{f"{g}_{k}": (v or "") for g, cell in t["lines"].items() if cell
                          for k, v in (("carrier", cell[0]), ("policy", cell[1]), ("premium", cell[2]))}
                         for t in D.PRIOR_TERMS]},
        },
        "ACORD_126": {
            "hazards": {"slots": list("ABC"), "columns": {
                "loc": "GeneralLiability_Hazard_LocationProducerIdentifier_{row}",
                "code": "GeneralLiability_Hazard_ClassCode_{row}",
                "basis": "GeneralLiability_Hazard_PremiumBasisCode_{row}",
                "exposure": "GeneralLiability_Hazard_Exposure_{row}",
                "terr": "GeneralLiability_Hazard_TerritoryCode_{row}"},
                "rows": [{"loc": h["loc"], "code": h["code"], "basis": h["basis"],
                          "exposure": h["exposure"], "terr": h["terr"]} for h in D.GL_HAZARDS]},
            "products": {"slots": list("ABC"), "columns": {
                "sales": "ProductAndCompletedOperations_AnnualGrossSalesAmount_{row}",
                "units": "ProductAndCompletedOperations_UnitCount_{row}",
                "months": "ProductAndCompletedOperations_InMarketMonthCount_{row}",
                "life": "ProductAndCompletedOperations_ExpectedLifeMonthCount_{row}"},
                "rows": [{"sales": p["sales"], "units": p["units"], "months": p["months"],
                          "life": p["life"]} for p in D.PRODUCTS]},
        },
        "ACORD_127": {
            "drivers": {"slots": list("ABCDEFGHIJKLM"), "columns": {
                "first": "Driver_GivenName_{row}", "last": "Driver_Surname_{row}",
                "dob": "Driver_BirthDate_{row}", "lic": "Driver_LicenseNumberIdentifier_{row}",
                "hired": "Driver_HiredDate_{row}", "veh": "Driver_Vehicle_ProducerIdentifier_{row}"},
                "rows": [{"first": d["first"], "last": d["last"], "dob": d["dob"], "lic": d["lic"],
                          "hired": d["hired"], "veh": d["veh"]} for d in D.DRIVERS]},
            "vehicles": {"slots": list("ABCD"), "columns": {
                "year": "Vehicle_ModelYear_{row}", "vin": "Vehicle_VINIdentifier_{row}",
                "gvw": "Vehicle_GrossVehicleWeight_{row}", "cost": "Vehicle_CostNewAmount_{row}",
                "radius": "Vehicle_RadiusOfUse_{row}", "coll": "Vehicle_Collision_DeductibleAmount_{row}",
                "zip": "Vehicle_PhysicalAddress_PostalCode_{row}"},
                "rows": [{"year": v["year"], "vin": v["vin"], "gvw": v["gvw"], "cost": v["cost"],
                          "radius": v["radius"], "coll": v["coll_ded"],
                          "zip": D.LOCATIONS[int(v["loc"]) - 1]["zip"]} for v in D.VEHICLES]},
            "interests": {"slots": list("AB"), "columns": {
                "name": "AdditionalInterest_FullName_{row}", "acct": "AdditionalInterest_AccountNumberIdentifier_{row}",
                "veh": "AdditionalInterest_Item_VehicleProducerIdentifier_{row}"},
                "rows": [{"name": a["name"], "acct": a["acct"], "veh": a["veh"]} for a in D.AUTO_AI]},
        },
    }
    expected_absent = {
        "ACORD_125": ea125,
        "ACORD_126": {"scope": ["AdditionalInterest_FullName_*", "ProductAndCompletedOperations_ProductName_*"],
                      "values": [n for n, _a in D.CERT_HOLDERS] + [D.STAFFING, D.MORTGAGEE["name"]]},
        "ACORD_127": {"scope": ["Vehicle_VINIdentifier_*", "Driver_Surname_*", "Driver_LicenseNumberIdentifier_*",
                                "AdditionalInterest_FullName_*", "AccidentConviction_*"],
                      "values": [D.SOLD_VEHICLE["vin"], "Ambrose", D.TERMINATED_DRIVER["lic"],
                                 D.OLD_CONVICTION["date"], D.MORTGAGEE["name"], "Lindqvist", "Ellison"]},
    }
    return {
        "_meta": {**meta, "verdict_counts": counts,
                  "absent_by_design": D.ABSENT_BY_DESIGN,
                  "unresolved_expected": [{"form": f, "field": x, "what": w}
                                          for f, x, w in D.UNRESOLVED_EXPECTED]},
        "_doc": meta["document"],
        "_forms": list(FORMS),
        "expect": expect,
        "must_be_blank": blanks,
        "forbidden": forbidden,
        "shapes": shapes,
        "expected_absent": expected_absent,
        "row_sets": row_sets,
        "fields": FIELDS["ACORD_125"],
        "fields_by_form": FIELDS,
        "match_modes": semantic,
    }
