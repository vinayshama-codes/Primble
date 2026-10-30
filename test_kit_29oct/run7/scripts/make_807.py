"""Fill ASG's sample ACORD 807 (2016/03) for Ridgeline as an OUTSIDE agency would, then flatten.
Run: backend/.venv/bin/python -I test_kit_29oct/run3/scripts/make_807.py <sample 807 pdf> <out pdf>"""
import sys
import pikepdf

SRC, OUT = sys.argv[1], sys.argv[2]
INSURED = "Ridgeline Mechanical Services LLC"          # same as the dec (one insured)

# ---- planted inconsistencies (807 value vs dec value) ----
DO_EFF, DO_EXP = "02/01/2027", "02/01/2028"            # dec renewal term: 12/01/2026 - 12/01/2027
CUR_YEAR_REVENUE = "9,040,000"                         # dec Annual Gross Revenue: $8,450,000
MISSPELT_OFFICER = "Laura Kesler"                       # dec: Laura Kessler (Member, CFO)

X = "X"  # any non-empty value = tick the box
v = {
    # header
    "Producer_CustomerIdentifier_A": "RIDG-0731",
    "Form_CompletionDate_A": "10/31/2026",
    "Producer_FullName_A": "Bluestem Risk Advisors LLC",
    "Policy_PolicyNumberIdentifier_A": "DOL-2290417-26",
    "Policy_EffectiveDate_A": DO_EFF,
    "Insurer_FullName_A": "Larkspur Specialty Insurance Company",
    "Insurer_NAICCode_A": "38150",
    "NamedInsured_FullName_A": INSURED,
    "Policy_ExpirationDate_A": DO_EXP,
    # coverages / limits (requested vs current)
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_PrimaryIndicator_A": X,
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_RequestedPerClaimLimitAmount_A": "3,000,000",
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_RequestedAggregateLimitAmount_A": "3,000,000",
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_CurrentPerClaimLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_CurrentAggregateLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_RequestedRetentionAmount_A": "0",
    "DirectorsAndOfficersCoverage_DirectorsAndOfficers_CurrentRetentionAmount_A": "0",
    "DirectorsAndOfficersCoverage_CompanyReimbursement_PrimaryIndicator_A": X,
    "DirectorsAndOfficersCoverage_CompanyReimbursement_RequestedPerClaimLimitAmount_A": "2,000,000",
    "DirectorsAndOfficersCoverage_CompanyReimbursement_RequestedAggregateLimitAmount_A": "2,000,000",
    "DirectorsAndOfficersCoverage_CompanyReimbursement_CurrentPerClaimLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_CompanyReimbursement_CurrentAggregateLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_CompanyReimbursement_RequestedRetentionAmount_A": "25,000",
    "DirectorsAndOfficersCoverage_CompanyReimbursement_CurrentRetentionAmount_A": "25,000",
    "DirectorsAndOfficersCoverage_CompanyEntityLiability_PrimaryIndicator_A": X,
    "DirectorsAndOfficersCoverage_CompanyEntityLiability_RequestedPerClaimLimitAmount_A": "2,000,000",
    "DirectorsAndOfficersCoverage_CompanyEntityLiability_RequestedAggregateLimitAmount_A": "2,000,000",
    "DirectorsAndOfficersCoverage_CompanyEntityLiability_CurrentPerClaimLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_CompanyEntityLiability_CurrentAggregateLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_CompanyEntityLiability_RequestedRetentionAmount_A": "35,000",
    "DirectorsAndOfficersCoverage_CompanyEntityLiability_CurrentRetentionAmount_A": "25,000",
    "DirectorsAndOfficersCoverage_Other_CoverageDescription_A": "Employment Practices",
    "DirectorsAndOfficersCoverage_Other_PrimaryIndicator_A": X,
    "DirectorsAndOfficersCoverage_Other_RequestedPerClaimLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_Other_RequestedAggregateLimitAmount_A": "1,000,000",
    "DirectorsAndOfficersCoverage_Other_CurrentPerClaimLimitAmount_A": "500,000",
    "DirectorsAndOfficersCoverage_Other_CurrentAggregateLimitAmount_A": "500,000",
    "DirectorsAndOfficersCoverage_Other_RequestedRetentionAmount_A": "15,000",
    "DirectorsAndOfficersCoverage_Other_CurrentRetentionAmount_A": "15,000",
    "DirectorsAndOfficersCoverage_Other_CoverageDescription_B": "Fiduciary Liability",
    "DirectorsAndOfficersCoverage_Other_PrimaryIndicator_B": X,
    "DirectorsAndOfficersCoverage_Other_RequestedPerClaimLimitAmount_B": "500,000",
    "DirectorsAndOfficersCoverage_Other_RequestedAggregateLimitAmount_B": "500,000",
    "DirectorsAndOfficersCoverage_Other_CurrentPerClaimLimitAmount_B": "500,000",
    "DirectorsAndOfficersCoverage_Other_CurrentAggregateLimitAmount_B": "500,000",
    "DirectorsAndOfficersCoverage_Other_RequestedRetentionAmount_B": "0",
    "DirectorsAndOfficersCoverage_Other_CurrentRetentionAmount_B": "0",
    "DirectorsAndOfficersCoverage_DefenceCosts_SeparateLimitCode_A": "Y",
    "DirectorsAndOfficersCoverage_DefenceCosts_LimitAmount_A": "250,000",
    "DirectorsAndOfficersCoverage_DefenceCosts_OutsideIndicator_A": X,
    "DirectorsAndOfficersCoverage_DefenceCosts_PendingAndPriorLitigationDate_A": "12/01/2019",
    "DirectorsAndOfficersLineOfBusiness_Question_ACICode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_Question_ACJCode_A": "Y",
    # sections attached
    "Policy_SectionAttached_EPLIIndicator_A": X,
    "Policy_SectionAttached_FiduciaryIndicator_A": X,
    "Policy_SectionAttached_OtherIndicator_A": X,
    "Policy_SectionAttached_OtherSectionDescription_A": "Cyber Liability Supplement",
    # endorsements
    "FormEndorsement_WorldWideCoverage_AppliesIndicator_A": X,
    "FormEndorsement_FormIdentifier_A": "LSI-DO 104",
    "FormEndorsement_FormName_A": "Worldwide Coverage Extension",
    "FormEndorsement_FormDate_A": "06/2021",
    "FormEndorsement_OutsideDirectorshipLiabilityForProfit_AppliesIndicator_A": X,
    "FormEndorsement_FormIdentifier_D": "LSI-DO 118",
    "FormEndorsement_FormName_D": "Outside Directorship Liability - For Profit",
    "FormEndorsement_FormDate_D": "06/2021",
    "FormEndorsement_AppliesIndicator_A": X,
    "FormEndorsement_FormDescription_A": "BI/PD exclusion amendatory",
    "FormEndorsement_FormIdentifier_F": "LSI-DO 212",
    "FormEndorsement_FormName_F": "BI/PD Exclusion Amendatory",
    "FormEndorsement_FormDate_F": "01/2023",
    "FormEndorsement_AppliesIndicator_B": X,
    "FormEndorsement_FormDescription_B": "Colorado amendatory endorsement",
    "FormEndorsement_FormIdentifier_G": "LSI-DO 900 CO",
    "FormEndorsement_FormName_G": "Colorado Changes",
    "FormEndorsement_FormDate_G": "09/2022",
    # financial statement
    "FinancialStatement_FinancialInformationDate_A": "03/31/2026",
    "DirectorsAndOfficersLineOfBusiness_Question_ADACode_A": "Y",
    "DirectorsAndOfficersLineOfBusiness_Question_AAFCode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_Question_ABICode_A": "N",
    "FinancialStatement_CurrentYear_A": "2025",
    "FinancialStatement_StartDate_A": "01/01/2025",
    "FinancialStatement_EndDate_A": "12/31/2025",
    "FinancialStatement_CurrentYear_TotalAssetsAmount_A": "6,420,000",
    "FinancialStatement_CurrentYear_CurrentAssetsAmount_A": "3,180,000",
    "FinancialStatement_CurrentYear_InventoryAmount_A": "640,000",
    "FinancialStatement_CurrentYear_CashAmount_A": "1,210,000",
    "FinancialStatement_CurrentYear_CurrentLiabilitiesAmount_A": "1,740,000",
    "FinancialStatement_CurrentYear_TotalLiabilitiesAmount_A": "2,960,000",
    "FinancialStatement_CurrentYear_TotalRevenueAmount_A": CUR_YEAR_REVENUE,
    "FinancialStatement_CurrentYear_NetIncomeAmount_A": "612,000",
    "FinancialStatement_PriorYear_A": "2024",
    "FinancialStatement_StartDate_B": "01/01/2024",
    "FinancialStatement_EndDate_B": "12/31/2024",
    "FinancialStatement_PriorYear_TotalAssetsAmount_A": "5,880,000",
    "FinancialStatement_PriorYear_CurrentAssetsAmount_A": "2,910,000",
    "FinancialStatement_PriorYear_InventoryAmount_A": "585,000",
    "FinancialStatement_PriorYear_CashAmount_A": "1,040,000",
    "FinancialStatement_PriorYear_CurrentLiabilitiesAmount_A": "1,620,000",
    "FinancialStatement_PriorYear_TotalLiabilitiesAmount_A": "2,875,000",
    "FinancialStatement_PriorYear_TotalRevenueAmount_A": "7,910,000",
    "FinancialStatement_PriorYear_NetIncomeAmount_A": "498,000",
    # not for profit: fund balances blank, tax exempt N
    "BusinessInformation_TaxExemptOrganizationCode_A": "N",
    # ownership
    "BusinessInformation_OwnerCount_A": "2",
    "BusinessInformation_StockInformation_OutstandingVotingSharesCount_A": "1,000",
    "BusinessInformation_StockInformation_TotalVotingSharesCount_A": "1,000",
    "BusinessInformation_StockInformation_VotingSharesOwnedByDirectorsCount_A": "1,000",
    "BusinessInformation_StockInformation_VotingSharesOwnedByOfficersCount_A": "0",
    "BusinessInformation_DirectorOrOfficer_FullName_A": MISSPELT_OFFICER + " - Member / Chief Financial Officer",
    "AffiliationInformation_OrganizationName_A": "Colorado Mechanical Contractors Association (board member)",
    "BusinessInformation_DirectorOrOfficer_FullName_B": "Gregory Hale - Managing Member",
    "AffiliationInformation_OrganizationName_B": "None",
    "AdditionalInterest_FullName_A": "Marcus J. Delgado",
    "EmploymentInformation_EmploymentTitle_A": "Field Operations Manager",
    "EmploymentInformation_DutiesDescription_A": "Field crews and job-site safety",
    "AffiliationInformation_OrganizationName_K": "None",
    "AdditionalInterest_FullName_B": "Dana L. Ruiz",
    "EmploymentInformation_EmploymentTitle_B": "Controller",
    "EmploymentInformation_DutiesDescription_B": "Accounting and payroll",
    "AffiliationInformation_OrganizationName_L": "None",
    "Subsidiary_OrganizationName_A": "Ridgeline Mechanical Wyoming LLC",
    "Subsidiary_BusinessTypeDescription_A": "HVAC service - Cheyenne branch operations",
    "Subsidiary_StartDate_A": "04/01/2023",
    "Subsidiary_ParentOwnershipPercent_A": "100",
    "Shareholder_FullName_A": MISSPELT_OFFICER,
    "Shareholder_BoardOfDirectorsRepresentedCode_A": "Y",
    "Shareholder_SharesHeldPercent_A": "50",
    "Shareholder_FullName_B": "Gregory Hale",
    "Shareholder_BoardOfDirectorsRepresentedCode_B": "Y",
    "Shareholder_SharesHeldPercent_B": "50",
    "DirectorsAndOfficersLineOfBusiness_Question_ACACode_A": "Y",
    # general information (12 Y/N codes, 11 explanation boxes - ABB and ABE share one)
    "DirectorsAndOfficersLineOfBusiness_Question_KAACode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_ApplicantOrDirectorOfficersInvolvedAnyClaimsLawsuitsLastMandatedNumberYearsExplanation_A":
        "No D&O claims, suits or administrative proceedings in the last 5 years.",
    "DirectorsAndOfficersLineOfBusiness_Question_AAECode_A": "Y",
    "DirectorsAndOfficersLineOfBusiness_AnyChangesBoardOfDirectorsOrSeniorManagementLastMandatedNumberYearsExplanation_A":
        "Controller Dana L. Ruiz hired 02/2024; no other management changes.",
    "DirectorsAndOfficersLineOfBusiness_Question_KABCode_A": "Y",
    "DirectorsAndOfficersLineOfBusiness_AppllicantCompletedMergerAcquisitionWithAnotherEntityLastMandatedNumberOfYearsExplanation_A":
        "Formed Ridgeline Mechanical Wyoming LLC 04/01/2023 to hold the Cheyenne branch; no merger planned.",
    "DirectorsAndOfficersLineOfBusiness_Question_AAICode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_ApplicantCompletedRegistrationPublicOfferingLastMandatedNumberOfYearsExplanaton_A":
        "No public offering or private placement; privately held LLC.",
    "DirectorsAndOfficersLineOfBusiness_Question_AAJCode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_ApplicantCompletedReorganizationWithCreditorsWithinLastMandatedNumberOfYearsExplanation_A":
        "No reorganization or arrangement with creditors.",
    "DirectorsAndOfficersLineOfBusiness_Question_ACCCode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_ApplicantOrSubsidiariesActAsGeneralPartnerOrInvolvedJointVentureExplanation_A":
        "Not a general partner; no joint ventures.",
    "DirectorsAndOfficersLineOfBusiness_Question_ABBCode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_Question_ABECode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_PersonsOrEntitiesAwareAnyCircumstanceGiveRiseToClaimExplanation_A":
        "No known circumstances; no notice given under any prior policy.",
    "DirectorsAndOfficersLineOfBusiness_Question_ABHCode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_AnyInsurerRefusedCancelledNonrenewedInsuranceExplanation_A":
        "Larkspur has written the D&O since 2022; never refused or non-renewed.",
    "DirectorsAndOfficersLineOfBusiness_Question_ABJCode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_ApplicantSecuritiesPubliclyTradedExplanation_A":
        "Membership interests are not publicly traded.",
    "DirectorsAndOfficersLineOfBusiness_Question_ACECode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_ApplicantBreachOfDebtOrLoanAgreementExplanation_A":
        "In compliance with all covenants on the FirstBank equipment line.",
    "DirectorsAndOfficersLineOfBusiness_Question_ACFCode_A": "N",
    "DirectorsAndOfficersLineOfBusiness_ApplicantProvideAnyConsultingProfessionalServicesExplanation_A":
        "Installation and service contractor only; no design or consulting.",
    # attachments, remarks
    "DirectorsAndOfficersLineOfBusiness_Attachment_ScheduleOfShareholdersIndicator_A": X,
    "DirectorsAndOfficersLineOfBusiness_Attachment_OtherIndicator_A": X,
    "DirectorsAndOfficersLineOfBusiness_Attachment_OtherDescription_A": "FY2025 CPA financials",
    "DirectorsAndOfficersLineOfBusiness_RemarkText_A":
        "D&O / EPL / Fiduciary marketed with the 12/2026 package renewal. Financials reviewed by Hollis & Varga CPAs. Increase to $2M requested by the members.",
    # signature block
    "NamedInsured_FullName_B": "Gregory Hale",
    "NamedInsured_Title_A": "Managing Member",
    "Producer_StateLicenseIdentifier_A": "0461275",
    "NamedInsured_Signature_A": "Gregory Hale",
    "NamedInsured_SignatureDate_A": "10/31/2026",
    "Producer_AuthorizedRepresentative_Signature_A": "Jordan Pike",
    "Producer_NationalIdentifier_A": "18834502",
}
KEEP = {"Form_EditionIdentifier_A"}

pdf = pikepdf.open(SRC)
fields = {str(f.T): f for f in pdf.Root.AcroForm.Fields}
missing = [k for k in v if k not in fields]
assert not missing, missing

def widgets(f):
    return list(f.Kids) if "/Kids" in f else [f]

# 1. clear every field (value AND old appearance, else the sample text still prints)
for name, f in fields.items():
    if name in KEEP:
        continue
    if "/V" in f:
        del f["/V"]
    for w in widgets(f):
        if f.get("/FT") == "/Btn":
            w.AS = pikepdf.Name("/Off")
        elif "/AP" in w:
            del w["/AP"]
# 2. refill
for k, val in v.items():
    f = fields[k]
    if f.get("/FT") == "/Btn":
        on = [n for n in widgets(f)[0].AP.N.keys() if n != "/Off"][0]
        f.V = pikepdf.Name(on)
        for w in widgets(f):
            w.AS = pikepdf.Name(on)
    else:
        f.V = pikepdf.String(val)
# 3. drop ASG's "Sample" watermark: a full-page image painted by its own tiny content stream
import re
for pg in pdf.pages:
    c = pg.obj.Contents
    if not isinstance(c, pikepdf.Array):
        continue
    keep = pikepdf.Array()
    for st in c:
        b = st.read_bytes()
        m = re.fullmatch(rb"q\s+[-\d. ]+cm\s+/(\w+) Do\s+Q\s*", b)
        img = pg.obj.Resources.XObject.get("/" + m.group(1).decode()) if m else None
        if img is not None and img.get("/Subtype") == "/Image" and int(img.get("/Width", 0)) * int(img.get("/Height", 0)) > 500000:
            print("removed watermark", m.group(1).decode(), "page", pdf.pages.index(pg) + 1)
            continue
        keep.append(st)
    pg.obj.Contents = keep
# 4. flatten
pdf.Root.AcroForm.NeedAppearances = True
pdf.generate_appearance_streams()
pdf.flatten_annotations("all")
for key in ("/AcroForm", "/OpenAction", "/PrimbleRecord"):
    if key in pdf.Root:
        del pdf.Root[key]
for k in list(pdf.docinfo.keys()):
    del pdf.docinfo[k]
pdf.docinfo["/Producer"] = "Bluestem Risk Advisors LLC agency management system"
pdf.save(OUT, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
print("filled", len(v), "of", len(fields), "fields ->", OUT)
