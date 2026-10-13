# CH125 ANSWER KEY - Cumberland Hearth & Hospitality Supply, Inc.

Document: `CH125_cumberland_hearth_package.pdf` - **300,000 characters** (sum(len(page.extract_text()) for page in pdfplumber pages)), 59 pages, text layer only (no scanned images).  
Machine key: `CH125_answer_key.json` (every box on all three forms). Grade a run with `ch125_test_data/grade_kit.py`.

## The account in one paragraph

Cumberland Hearth & Hospitality Supply, Inc. (formerly Cumberland Restaurant Supply, LLC, converted to a C corporation 01/01/2022; in business since 03/01/2009) is a Nashville wholesale distributor of commercial kitchen equipment with a service subsidiary, Cumberland Hearth Service Co., LLC. It owns 40% of Music Row Kitchen Rentals, LLC (not a subsidiary, not insured here). Its new agent, Riverbend Insurance Partners, LLC, is submitting NEW BUSINESS for a QUOTE to Ridgeline Specialty Insurance Company (NAIC 41297) through the MGA Appalachian Risk Underwriters, LLC, for 12/01/2026 - 12/01/2027: GL, property, business auto and umbrella. The incumbents are Old Hickory Mutual Insurance Company (GL, auto), Magnolia Underwriters Insurance Company (property) and Cardinal Excess Insurance Company (umbrella).

## Totals

| form | expect a value | blank - nothing stated | blank - a rule owns it | not scored |
|---|---|---|---|---|
| ACORD_125 | 252 | 174 | 89 | 33 |
| ACORD_126 | 141 | 54 | 49 | 11 |
| ACORD_127 | 288 | 286 | 42 | 18 |

## 1. UNRESOLVED - must stay BLANK and be asked (blank is not No)

| form | box | question |
|---|---|---|
| ACORD_125 | `CommercialPolicy_Question_KABCode_A` | Q7 fraud / bribery / arson conviction |
| ACORD_125 | `CommercialPolicy_Question_KAKCode_A` | Q9 foreclosure / repossession / bankruptcy |
| ACORD_126 | `GeneralLiabilityLineOfBusiness_Question_ACECode_A` | recreation facilities |
| ACORD_126 | `GeneralLiabilityLineOfBusiness_Question_KAACode_A` | lodging operations |
| ACORD_126 | `GeneralLiabilityLineOfBusiness_Question_KAHCode_A` | swimming pool |
| ACORD_126 | `GeneralLiabilityLineOfBusiness_Question_AAECode_A` | day care facilities |
| ACORD_126 | `GeneralLiabilityLineOfBusiness_Question_AAGCode_A` | promotional literature safety representations |
| ACORD_127 | `CommercialVehicleLineOfBusiness_Question_KAGCode_A` | all vehicles part of a fleet |
| ACORD_125 | `PriorCoverage_Property_TotalPremiumAmount_C` | 2023-24 property premium - request it |

## 2. Expected recommendations (what Primble should ask, and of whom)

| who | ask | why |
|---|---|---|
| Insured | Answer 125 question 7 (fraud / bribery / arson conviction). | UNRESOLVED - never answered |
| Insured | Answer 125 question 9 (foreclosure / repossession / bankruptcy). | UNRESOLVED - the client's own example |
| Insured | Answer the 126 recreation facilities, lodging, swimming pool, day care and promotional-literature questions. | UNRESOLVED |
| Insured / producer | Answer the 127 question 'are all vehicles part of a fleet?'. | UNRESOLVED - the agent said it is open |
| Producer | Request the 2023-24 property premium from Volunteer Fire & Marine (prior carrier year 3). | client: populate only what is substantiated and REQUEST the rest |
| Producer | Enter the NPN and the state producer licence. | client: 'NPN: completed' - Primble's account profile has no field for either (audit gap) |
| Producer | Agency code / sub-code / customer id - only from the agency's own records. | Riverbend's AMS prints them; Primble never fills these boxes today |
| Applicant / producer | Sign and date the applications. | authorship - never filled by the AI |

Primble should **not** ask for: drones (answered: no own, hires a Part 107 vendor); loss history (loss runs supplied); employee counts (HR census); revenue by location (CFO e-mail); safety program (manual, coordinator, OSHA, quarterly meetings); the proposed term (confirmed 12/01/2026 - 12/01/2027); parent company (no); trust (no); vehicles, drivers, garaging, use, radius (schedules supplied).

## ACORD_125 - every box that must carry a value

| box | expected | match | page(s) | trap / note |
|---|---|---|---|---|
| `Form_EditionIdentifier_A` | ACORD 125 (2025/03) | exact | template | the template's footer |
| `Insurer_FullName_A` | Ridgeline Specialty Insurance Company | exact | 1,2,3,6,15 | the writing company named on the MGA's acknowledgement; TRAP: not the MGA (Appalachian Risk Underwriters, LLC) and not the incumbent (Old Hickory Mutual Insurance Comp... |
| `Insurer_NAICCode_A` | 41297 | exact | 2 | client: 'only if verified' - printed beside the carrier's name in the acknowledgement's fine print; TRAP: 27718 |
| `Insurer_ProductDescription_A` | Hospitality Trades Package Program | semantic | 1,2,3 | the program |
| `Insurer_ProductCode_A` | HTP-TN | exact | 1 | the program code |
| `Insurer_Underwriter_FullName_A` | Priya Raman | exact | 1,3 | the submission is directed to her |
| `Insurer_Underwriter_OfficeIdentifier_A` | Knoxville | exact | 1,2 |  |
| `Policy_Status_QuoteIndicator_A` | Y | exact | see note | client: QUOTE - 'request for quotation - new business to Ridgeline'; TRAP: the incumbent dec prints 'RENEWAL OF OHM-GL-4471902-24' |
| `Policy_LineOfBusiness_CommercialGeneralLiability_A` | Y | exact | see note | requested in the submission e-mail |
| `Policy_LineOfBusiness_CommercialProperty_A` | Y | exact | see note | requested in the submission e-mail |
| `Policy_LineOfBusiness_BusinessAutoIndicator_A` | Y | exact | see note | requested in the submission e-mail |
| `Policy_LineOfBusiness_UmbrellaIndicator_A` | Y | exact | see note | requested in the submission e-mail |
| `Policy_EffectiveDate_A` | 12/01/2026 | exact | 1,2,3,4,5,15 | confirmed in the CFO's 09/30 e-mail and the acknowledgement; TRAP: 11/15/2026 (August worksheet) and 12/01/2025 (current) |
| `Policy_ExpirationDate_A` | 12/01/2027 | exact | 1,2,30 | TRAP: 12/01/2026 |
| `Policy_Payment_DirectBillIndicator_A` | Y | exact | see note | direct bill requested and acknowledged; TRAP: the incumbent is agency billed |
| `Policy_Payment_PaymentScheduleCode_A` | QT | exact | see note | ACORD tooltip: 'QT - Quarterly'; TRAP: 10 installments is the incumbent's |
| `Policy_PaymentMethod_MethodDescription_A` | ACH auto-debit | semantic | 1,2 | TRAP: Agency bill - 10 installments |
| `Policy_Audit_FrequencyCode_A` | A | exact | see note | acknowledgement: premium audit annual; TRAP: the incumbent GL dec says semi-annual (S) |
| `NamedInsured_FullName_A` | Cumberland Hearth & Hospitality Supply, Inc. | exact | 1,2,3,5,9,10 | TRAP: Cumberland Restaurant Supply, LLC / Music Row Kitchen Rentals, LLC / the trust |
| `NamedInsured_MailingAddress_LineOne_A` | P.O. Box 41120 | exact | 2,3,14,15,29,31 | TRAP: 2850 Kellerman Industrial Pkwy is a PREMISES, not the mailing address |
| `NamedInsured_MailingAddress_CityName_A` | Nashville | exact | 1,2,3,6,10,11 |  |
| `NamedInsured_MailingAddress_StateOrProvinceCode_A` | TN | exact | see note |  |
| `NamedInsured_MailingAddress_PostalCode_A` | 37204-1120 | exact | 2,3,14,15,29,31 |  |
| `NamedInsured_GeneralLiabilityCode_A` | 12683 | exact | 3,15,29,30 | TRAP: 68706 / 91127 are not the governing class |
| `NamedInsured_SICCode_A` | 5046 | exact | 3 |  |
| `NamedInsured_NAICSCode_A` | 423440 | exact | 3 |  |
| `NamedInsured_TaxIdentifier_A` | 62-3418806 | exact | 2,3,7,8,14,15 | TRAP: 000817423 (SOS), 07-881-4420 (D-U-N-S), 3217744 (USDOT) |
| `NamedInsured_Primary_PhoneNumber_A` | 615-555-0142 | exact | 3,5,15 | TRAP: 615-555-0149 is the fax; 1-800-555-0198 the incumbent |
| `NamedInsured_Primary_WebsiteAddress_A` | www.cumberlandhearth-example.com | exact | 3,15 | TRAP: www.oldhickorymutual-example.com |
| `NamedInsured_FullName_B` | Cumberland Hearth Service Co., LLC | exact | 1,2,3,4,6,7 |  |
| `NamedInsured_MailingAddress_LineOne_B` | 1199 Hillsboro Commons Dr | exact | 3,6,7,14,28,30 |  |
| `NamedInsured_MailingAddress_LineTwo_B` | Suite 220 | exact | 3,5,14,28,30,33 |  |
| `NamedInsured_MailingAddress_CityName_B` | Franklin | exact | 3,4,5,7,9,10 |  |
| `NamedInsured_MailingAddress_StateOrProvinceCode_B` | TN | exact | see note |  |
| `NamedInsured_MailingAddress_PostalCode_B` | 37067 | exact | 3,6,14,28,30,31 |  |
| `NamedInsured_GeneralLiabilityCode_B` | 91127 | exact | 4,15,29,30 |  |
| `NamedInsured_SICCode_B` | 7699 | exact | 3 |  |
| `NamedInsured_NAICSCode_B` | 811310 | exact | 3 |  |
| `NamedInsured_TaxIdentifier_B` | 47-2290113 | exact | 3,14 |  |
| `NamedInsured_Primary_PhoneNumber_B` | 615-555-0143 | exact | 3 |  |
| `NamedInsured_Primary_WebsiteAddress_B` | www.chhservice-example.com | exact | 3 |  |
| `NamedInsured_LegalEntity_CorporationIndicator_A` | Y | exact | see note | a C corporation (W-9, Form 1120) |
| `NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_B` | Y | exact | see note | a member-managed LLC |
| `NamedInsured_LegalEntity_MemberManagerCount_B` | 1 | exact | see note | the 2026 SOS annual report |
| `NamedInsured_BusinessStartDate_A` | 03/01/2009 | exact | 2,3,10,14 | in continuous operation since March 1, 2009; TRAP: 01/01/2022 is the conversion; 03/15/2018 is the subsidiary's formation |
| `NamedInsured_Contact_ContactDescription_A` | Inspection | semantic | 4,6,23,24,25,26 |  |
| `NamedInsured_Contact_FullName_A` | Rafael Quintero | exact | 4,5,15,27 | TRAP: never the CFO |
| `NamedInsured_Contact_PrimaryPhoneNumber_A` | 615-555-0177 | exact | 4,5,15 |  |
| `NamedInsured_Contact_SecondaryPhoneNumber_A` | 615-555-0168 | exact | 4,5,15 |  |
| `NamedInsured_Contact_PrimaryEmailAddress_A` | rquintero@cumberlandhearth-example.com | exact | 4,15 |  |
| `NamedInsured_Contact_SecondaryEmailAddress_A` | facilities@cumberlandhearth-example.com | exact | 4 |  |
| `NamedInsured_Contact_PrimaryCellPhoneIndicator_A` | Y | exact | see note | the phone's type is stated |
| `NamedInsured_Contact_SecondaryBusinessPhoneIndicator_A` | Y | exact | see note | the phone's type is stated |
| `NamedInsured_Contact_ContactDescription_B` | Accounting | semantic | 4,5,8,49 |  |
| `NamedInsured_Contact_FullName_B` | Denise Okafor | exact | 4,5,14,15 | TRAP: never the CFO |
| `NamedInsured_Contact_PrimaryPhoneNumber_B` | 615-555-0165 | exact | 4,5,15 |  |
| `NamedInsured_Contact_SecondaryPhoneNumber_B` | 615-555-0190 | exact | 4 | TRAP: 615-555-0109 is a corrected typo |
| `NamedInsured_Contact_PrimaryEmailAddress_B` | dokafor@cumberlandhearth-example.com | exact | 4,15 |  |
| `NamedInsured_Contact_SecondaryEmailAddress_B` | ap@cumberlandhearth-example.com | exact | 4,5 |  |
| `NamedInsured_Contact_PrimaryBusinessPhoneIndicator_B` | Y | exact | see note | the phone's type is stated |
| `NamedInsured_Contact_SecondaryCellPhoneIndicator_B` | Y | exact | see note | the phone's type is stated |
| `BusinessInformation_BusinessType_WholesaleIndicator_A` | Y | exact | see note | worksheet + operations; TRAP: the SUPERSEDED 2024 application said Retail |
| `CommercialPolicy_OperationsDescription_A` | Wholesale distributor of commercial kitchen and foodservice equipment, parts and suppli... | semantic | 4 |  |
| `CommercialPolicy_OperationsDescription_B` | Cumberland Hearth Service Co., LLC installs, services and repairs commercial kitchen eq... | semantic | 4 |  |
| `CommercialStructure_InstallationRepairWorkPercent_A` | 18% | exact | see note | ACORD tooltip: % of TOTAL SALES - the CFO's e-mail |
| `CommercialStructure_InstallationRepairWorkOffPremisesPercent_A` | 17% | exact | see note | % of TOTAL SALES done off premises; TRAP: 95% is a share of service CALLS |
| `CommercialPolicy_RemarkText_A` | Seasonal warehouse labor (up to 9 workers, October through December) is supplied by Har... | semantic | 4 | the worksheet's remark for the application |
| `CommercialStructure_Location_ProducerIdentifier_A` | 1 | exact | see note | the premises schedule (LOC #); TRAP: the property carrier numbers its premises 001-004 differently |
| `CommercialStructure_Building_ProducerIdentifier_A` | 1 | exact | see note | the premises schedule (BLD #) |
| `CommercialStructure_PhysicalAddress_LineOne_A` | 2850 Kellerman Industrial Pkwy | exact | 6,7,10,14,16,17 |  |
| `CommercialStructure_PhysicalAddress_CityName_A` | Nashville | exact | 1,2,3,6,10,11 |  |
| `CommercialStructure_PhysicalAddress_CountyName_A` | Davidson | exact | 4,6,14,29,33,34 |  |
| `CommercialStructure_PhysicalAddress_StateOrProvinceCode_A` | TN | exact | see note |  |
| `CommercialStructure_PhysicalAddress_PostalCode_A` | 37211 | exact | 6,14,17,23,24,26 |  |
| `CommercialStructure_RiskLocation_InsideCityLimitsIndicator_A` | Y | exact | see note |  |
| `CommercialStructure_InsuredInterest_OwnerIndicator_A` | Y | exact | see note |  |
| `BusinessInformation_FullTimeEmployeeCount_A` | 41 | exact | see note | the HR census, F/T column; TRAP: HC (head count) is full + part time |
| `BusinessInformation_PartTimeEmployeeCount_A` | 6 | exact | see note | the HR census, P/T column; TRAP: TMP agency temps are not employees |
| `CommercialStructure_AnnualRevenueAmount_A` | $15,200,000 | exact | 4,9,17 | TRAP: the company total, the 2027 plan, the backlog and payroll |
| `BuildingOccupancy_OccupiedArea_A` | 52,000 | exact | 5,6 |  |
| `BuildingOccupancy_OpenToPublicArea_A` | 2,400 | exact | 5,6,27 | premises schedule PUB SF + footnotes |
| `Construction_BuildingArea_A` | 58,000 | exact | 5,6,17,27,29,45 | premises schedule TOT SF |
| `BuildingOccupancy_OperationsDescription_A` | Headquarters: offices, showroom with test kitchen, and the main distribution warehouse ... | semantic | 6 |  |
| `CommercialStructure_Question_ABBCode_A` | Y | exact | see note | premises schedule LSD TO OTH + footnote 1 |
| `CommercialStructure_Location_ProducerIdentifier_B` | 2 | exact | see note | the premises schedule (LOC #); TRAP: the property carrier numbers its premises 001-004 differently |
| `CommercialStructure_Building_ProducerIdentifier_B` | 1 | exact | see note | the premises schedule (BLD #) |
| `CommercialStructure_PhysicalAddress_LineOne_B` | 410 Industrial Blvd | exact | 6,7,16,28,29,30 |  |
| `CommercialStructure_PhysicalAddress_LineTwo_B` | Suite C | exact | 5,6,16,28,29,30 |  |
| `CommercialStructure_PhysicalAddress_CityName_B` | La Vergne | exact | 4,5,6,7,9,10 |  |
| `CommercialStructure_PhysicalAddress_CountyName_B` | Rutherford | exact | 6,10,11,12,13,24 |  |
| `CommercialStructure_PhysicalAddress_StateOrProvinceCode_B` | TN | exact | see note |  |
| `CommercialStructure_PhysicalAddress_PostalCode_B` | 37086 | exact | 6,28,30,33,45 |  |
| `CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_B` | Y | exact | see note |  |
| `CommercialStructure_InsuredInterest_TenantIndicator_B` | Y | exact | see note |  |
| `BusinessInformation_FullTimeEmployeeCount_B` | 3 | exact | see note | the HR census, F/T column; TRAP: HC (head count) is full + part time |
| `BusinessInformation_PartTimeEmployeeCount_B` | 0 | exact | see note | the HR census, P/T column; TRAP: TMP agency temps are not employees |
| `CommercialStructure_AnnualRevenueAmount_B` | $0 | exact | see note | TRAP: the company total, the 2027 plan, the backlog and payroll |
| `BuildingOccupancy_OccupiedArea_B` | 12,500 | exact | 5,6,15,28,29,30 |  |
| `BuildingOccupancy_OpenToPublicArea_B` | 0 | exact | see note | premises schedule PUB SF + footnotes |
| `Construction_BuildingArea_B` | 50,000 | exact | 5,6,28,45 | premises schedule TOT SF |
| `BuildingOccupancy_OperationsDescription_B` | Parts depot and overflow storage; no sales and no customer access | semantic | 6 |  |
| `CommercialStructure_Question_ABBCode_B` | N | exact | see note | premises schedule LSD TO OTH + footnote 1 |
| `CommercialStructure_Location_ProducerIdentifier_C` | 3 | exact | see note | the premises schedule (LOC #); TRAP: the property carrier numbers its premises 001-004 differently |
| `CommercialStructure_Building_ProducerIdentifier_C` | 1 | exact | see note | the premises schedule (BLD #) |
| `CommercialStructure_PhysicalAddress_LineOne_C` | 1199 Hillsboro Commons Dr | exact | 3,6,7,14,28,30 |  |
| `CommercialStructure_PhysicalAddress_LineTwo_C` | Suite 220 | exact | 3,5,14,28,30,33 |  |
| `CommercialStructure_PhysicalAddress_CityName_C` | Franklin | exact | 3,4,5,7,9,10 |  |
| `CommercialStructure_PhysicalAddress_CountyName_C` | Williamson | exact | 6,10,11,12,13,18 |  |
| `CommercialStructure_PhysicalAddress_StateOrProvinceCode_C` | TN | exact | see note |  |
| `CommercialStructure_PhysicalAddress_PostalCode_C` | 37067 | exact | 3,6,14,28,30,31 |  |
| `CommercialStructure_RiskLocation_InsideCityLimitsIndicator_C` | Y | exact | see note |  |
| `CommercialStructure_InsuredInterest_TenantIndicator_C` | Y | exact | see note |  |
| `BusinessInformation_FullTimeEmployeeCount_C` | 22 | exact | see note | the HR census, F/T column; TRAP: HC (head count) is full + part time |
| `BusinessInformation_PartTimeEmployeeCount_C` | 1 | exact | see note | the HR census, P/T column; TRAP: TMP agency temps are not employees |
| `CommercialStructure_AnnualRevenueAmount_C` | $3,400,000 | exact | 4,5,6,9,12,13 | TRAP: the company total, the 2027 plan, the backlog and payroll |
| `BuildingOccupancy_OccupiedArea_C` | 3,100 | exact | 5,6,28 | TRAP: 3,400 is pre-amendment |
| `BuildingOccupancy_OpenToPublicArea_C` | 300 | exact | see note | premises schedule PUB SF + footnotes |
| `Construction_BuildingArea_C` | 24,000 | exact | 5,6,28,45 | premises schedule TOT SF |
| `BuildingOccupancy_OperationsDescription_C` | Service dispatch office of Cumberland Hearth Service Co., LLC; technicians report here;... | semantic | 6 |  |
| `CommercialStructure_Question_ABBCode_C` | N | exact | see note | premises schedule LSD TO OTH + footnote 1 |
| `AdditionalInterest_FullName_A` | Pinnacle Commerce Bank, N.A. | exact | 10,14,28,44 | the loan summary |
| `AdditionalInterest_MailingAddress_LineOne_A` | 150 Third Ave S | exact | 14,28 | the loan summary |
| `AdditionalInterest_MailingAddress_LineTwo_A` | Suite 900 | exact | 14,28 | the loan summary |
| `AdditionalInterest_MailingAddress_CityName_A` | Nashville | exact | 1,2,3,6,10,11 | the loan summary |
| `AdditionalInterest_MailingAddress_StateOrProvinceCode_A` | TN | exact | see note | the loan summary |
| `AdditionalInterest_MailingAddress_PostalCode_A` | 37201 | exact | 14,28 | the loan summary |
| `AdditionalInterest_InterestRank_A` | 1 | exact | see note | the loan summary |
| `AdditionalInterest_AccountNumberIdentifier_A` | 7004418829 | exact | 28 | the loan summary |
| `AdditionalInterest_InterestEndDate_A` | 05/01/2034 | exact | 10,28 | the loan summary |
| `AdditionalInterest_LoanAmount_A` | $3,150,000 | exact | 10,11,21,28,40 | the loan summary; TRAP: $2,684,512 is the balance |
| `AdditionalInterest_Primary_PhoneNumber_A` | 615-555-0300 | exact | 28 | the loan summary |
| `AdditionalInterest_Primary_FaxNumber_A` | 615-555-0301 | exact | 28 | the loan summary |
| `AdditionalInterest_Primary_EmailAddress_A` | insurance.tracking@pinnaclecb-example.com | exact | 28 | the loan summary |
| `AdditionalInterest_InterestReasonDescription_A` | First mortgage on the building at location 1 | semantic | see note | the loan summary |
| `AdditionalInterest_Item_LocationProducerIdentifier_A` | 1 | exact | see note | the loan summary |
| `AdditionalInterest_Item_BuildingProducerIdentifier_A` | 1 | exact | see note | the loan summary |
| `AdditionalInterest_ItemDescription_A` | Building at 2850 Kellerman Industrial Pkwy, Nashville | semantic | 28 | the loan summary |
| `AdditionalInterest_Interest_MortgageeIndicator_A` | Y | exact | see note | first mortgage |
| `AdditionalInterest_PolicyRequiredIndicator_A` | Y | exact | see note | evidence: a copy of the policy |
| `CommercialPolicy_Question_AAICode_A` | N | exact | see note | question 1a: the signed supplement + the CFO's e-mail; TRAP: the 2024 application's dissolved parent; a shareholder's trust |
| `CommercialPolicy_Question_AAJCode_A` | Y | exact | see note | question 1b: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_KAACode_A` | Y | exact | see note | question 2: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_ABCCode_A` | Y | exact | see note | question 3: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_AAHCode_A` | Y | exact | see note | question 4: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_AACCode_A` | Y | exact | see note | question 5: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_AADCode_A` | N | exact | see note | question 6: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_AAFCode_A` | N | exact | see note | question 8: the signed supplement + the CFO's e-mail; TRAP: a citation that WAS corrected is not uncorrected |
| `CommercialPolicy_Question_KALCode_A` | N | exact | see note | question 10: the signed supplement + the CFO's e-mail; TRAP: a judgment WON by the applicant; the bank's UCC filings |
| `CommercialPolicy_Question_ABBCode_A` | N | exact | see note | question 11: the signed supplement + the CFO's e-mail; TRAP: a shareholder's revocable trust |
| `CommercialPolicy_Question_KACCode_A` | Y | exact | see note | question 12: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_KAMCode_A` | Y | exact | see note | question 13: the signed supplement + the CFO's e-mail |
| `CommercialPolicy_Question_KANCode_A` | N | exact | see note | question 14: the signed supplement + the CFO's e-mail; TRAP: the SUPERSEDED 2024 application said Y (drone sold June 2025) |
| `CommercialPolicy_Question_KAOCode_A` | Y | exact | see note | question 15: the signed supplement + the CFO's e-mail |
| `Subsidiary_OrganizationName_A` | Cumberland Hearth Service Co., LLC | exact | 1,2,3,4,6,7 | 1b; TRAP: Music Row Kitchen Rentals, LLC (40%) |
| `Subsidiary_ParentSubsidiaryRelationshipDescription_B` | Wholly owned subsidiary - installation and service | semantic | 4,6 | 1b |
| `Subsidiary_ParentOwnershipPercent_B` | 100% | exact | see note | 1b |
| `CommercialPolicy_FormalSafetyProgram_SafetyManualIndicator_A` | Y | exact | see note |  |
| `CommercialPolicy_FormalSafetyProgram_SafetyPositionIndicator_B` | Y | exact | see note |  |
| `CommercialPolicy_FormalSafetyProgram_OSHAIndicator_B` | Y | exact | see note | follows OSHA 29 CFR 1910 |
| `CommercialPolicy_FormalSafetyProgram_OtherIndicator_B` | Y | exact | see note |  |
| `CommercialPolicy_FormalSafetyProgram_OtherDescription_B` | Quarterly safety committee meetings and annual forklift operator certification | semantic | 6 |  |
| `CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A` | Propane: up to twelve 33-lb forklift cylinders stored in a locked exterior cage at the ... | semantic | 4,6 |  |
| `OtherPolicy_PolicyNumberIdentifier_A` | IMF-3318207 | exact | 1,3,6,15 | question 4; TRAP: the INCUMBENT's policies are not with this company |
| `CancelNonRenew_NonRenewalIndicator_A` | Y | exact | see note | the VF&M notice of nonrenewal |
| `CancelNonRenew_UnderwritingIndicator_A` | Y | exact | see note | the notice's reason |
| `CancelNonRenew_UnderwritingConditionCorrectedIndicator_A` | Y | exact | see note | roof replaced |
| `CancelNonRenew_UnderwritingConditionCorrectedDescription_A` | Roof replaced with a new TPO membrane at 2850 Kellerman Industrial Pkwy; work completed... | semantic | 6 |  |
| `CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A` | Owns a 40% minority interest in Music Row Kitchen Rentals, LLC, a shared commercial kit... | semantic | 6 |  |
| `CommercialPolicy_ApplicantHireOthersOperateDronesExplanation_A` | Hires SkyFrame Imaging, LLC (FAA Part 107 certified) about twice a year to photograph c... | semantic | 6 |  |
| `PriorCoverage_PolicyYear_A` | 2025 | exact | 3,4,6,10,14,26 |  |
| `PriorCoverage_GeneralLiability_InsurerFullName_A` | Old Hickory Mutual Insurance Company | exact | 1,3,15,28,29,30 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A` | OHM-GL-4471902-25 | exact | 15,29,30,31,32,46 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_TotalPremiumAmount_A` | $38,420 | exact | 29,30,47 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_EffectiveDate_A` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_ExpirationDate_A` | 12/01/2026 | exact | 1,2,3,4,5,15 | loss runs / declarations |
| `PriorCoverage_Automobile_InsurerFullName_A` | Old Hickory Mutual Insurance Company | exact | 1,3,15,28,29,30 | loss runs / declarations |
| `PriorCoverage_Automobile_PolicyNumberIdentifier_A` | OHM-CA-4471903-25 | exact | 15,30,31,32,46,47 | loss runs / declarations |
| `PriorCoverage_Automobile_TotalPremiumAmount_A` | $61,775 | exact | 30,33,47 | loss runs / declarations |
| `PriorCoverage_Automobile_EffectiveDate_A` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_Automobile_ExpirationDate_A` | 12/01/2026 | exact | 1,2,3,4,5,15 | loss runs / declarations |
| `PriorCoverage_Property_InsurerFullName_A` | Magnolia Underwriters Insurance Company | exact | 1,3,15,31,32,44 | loss runs / declarations |
| `PriorCoverage_Property_PolicyNumberIdentifier_A` | MUI-CP-0098817-25 | exact | 15,31,32,44,47 | loss runs / declarations |
| `PriorCoverage_Property_TotalPremiumAmount_A` | $27,940 | exact | 44,47 | loss runs / declarations |
| `PriorCoverage_Property_EffectiveDate_A` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_Property_ExpirationDate_A` | 12/01/2026 | exact | 1,2,3,4,5,15 | loss runs / declarations |
| `PriorCoverage_OtherLine_InsurerFullName_A` | Cardinal Excess Insurance Company | exact | 1,3,15,31,32,46 | loss runs / declarations |
| `PriorCoverage_OtherLine_PolicyNumberIdentifier_A` | CXS-UMB-220871-25 | exact | 15,31,32,46,48 | loss runs / declarations |
| `PriorCoverage_OtherLine_TotalPremiumAmount_A` | $9,880 | exact | 46,48 | loss runs / declarations |
| `PriorCoverage_OtherLine_EffectiveDate_A` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_OtherLine_ExpirationDate_A` | 12/01/2026 | exact | 1,2,3,4,5,15 | loss runs / declarations |
| `PriorCoverage_PolicyYear_B` | 2024 | exact | 4,10,14,16,22,29 |  |
| `PriorCoverage_GeneralLiability_InsurerFullName_B` | Old Hickory Mutual Insurance Company | exact | 1,3,15,28,29,30 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_PolicyNumberIdentifier_B` | OHM-GL-4471902-24 | exact | 27,29,47 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_TotalPremiumAmount_B` | $35,910 | exact | 47 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_EffectiveDate_B` | 12/01/2024 | exact | 3,6,28,30,46,47 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_ExpirationDate_B` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_Automobile_InsurerFullName_B` | Old Hickory Mutual Insurance Company | exact | 1,3,15,28,29,30 | loss runs / declarations |
| `PriorCoverage_Automobile_PolicyNumberIdentifier_B` | OHM-CA-4471903-24 | exact | 27,47 | loss runs / declarations |
| `PriorCoverage_Automobile_TotalPremiumAmount_B` | $57,240 | exact | 47 | loss runs / declarations |
| `PriorCoverage_Automobile_EffectiveDate_B` | 12/01/2024 | exact | 3,6,28,30,46,47 | loss runs / declarations |
| `PriorCoverage_Automobile_ExpirationDate_B` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_Property_InsurerFullName_B` | Magnolia Underwriters Insurance Company | exact | 1,3,15,31,32,44 | loss runs / declarations |
| `PriorCoverage_Property_PolicyNumberIdentifier_B` | MUI-CP-0098817-24 | exact | 47 | loss runs / declarations |
| `PriorCoverage_Property_TotalPremiumAmount_B` | $25,115 | exact | 47 | loss runs / declarations |
| `PriorCoverage_Property_EffectiveDate_B` | 12/01/2024 | exact | 3,6,28,30,46,47 | loss runs / declarations |
| `PriorCoverage_Property_ExpirationDate_B` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_OtherLine_InsurerFullName_B` | Cardinal Excess Insurance Company | exact | 1,3,15,31,32,46 | loss runs / declarations |
| `PriorCoverage_OtherLine_PolicyNumberIdentifier_B` | CXS-UMB-220871-24 | exact | 48 | loss runs / declarations |
| `PriorCoverage_OtherLine_TotalPremiumAmount_B` | $9,240 | exact | 48 | loss runs / declarations |
| `PriorCoverage_OtherLine_EffectiveDate_B` | 12/01/2024 | exact | 3,6,28,30,46,47 | loss runs / declarations |
| `PriorCoverage_OtherLine_ExpirationDate_B` | 12/01/2025 | exact | 3,15,29,30,31,32 | loss runs / declarations |
| `PriorCoverage_PolicyYear_C` | 2023 | exact | 4,16,24,27,33,50 |  |
| `PriorCoverage_GeneralLiability_InsurerFullName_C` | Old Hickory Mutual Insurance Company | exact | 1,3,15,28,29,30 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_PolicyNumberIdentifier_C` | OHM-GL-4471902-23 | exact | 47,50 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_TotalPremiumAmount_C` | $33,005 | exact | 47 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_EffectiveDate_C` | 12/01/2023 | exact | 47 | loss runs / declarations |
| `PriorCoverage_GeneralLiability_ExpirationDate_C` | 12/01/2024 | exact | 3,6,28,30,46,47 | loss runs / declarations |
| `PriorCoverage_Automobile_InsurerFullName_C` | Old Hickory Mutual Insurance Company | exact | 1,3,15,28,29,30 | loss runs / declarations |
| `PriorCoverage_Automobile_PolicyNumberIdentifier_C` | OHM-CA-4471903-23 | exact | 47,50 | loss runs / declarations |
| `PriorCoverage_Automobile_TotalPremiumAmount_C` | $52,880 | exact | 47 | loss runs / declarations |
| `PriorCoverage_Automobile_EffectiveDate_C` | 12/01/2023 | exact | 47 | loss runs / declarations |
| `PriorCoverage_Automobile_ExpirationDate_C` | 12/01/2024 | exact | 3,6,28,30,46,47 | loss runs / declarations |
| `PriorCoverage_Property_InsurerFullName_C` | Volunteer Fire & Marine Insurance Company | exact | 6,28,47,48 | loss runs / declarations |
| `PriorCoverage_Property_PolicyNumberIdentifier_C` | VFM-CPP-7781203 | exact | 6,28,47,50 | loss runs / declarations |
| `PriorCoverage_Property_EffectiveDate_C` | 12/01/2023 | exact | 47 | loss runs / declarations |
| `PriorCoverage_Property_ExpirationDate_C` | 12/01/2024 | exact | 3,6,28,30,46,47 | loss runs / declarations |
| `LossHistory_OccurrenceDate_A` | 08/09/2025 | exact | 4,47 | loss run, claim OHM-25-CA-018822 |
| `LossHistory_ClaimDate_A` | 08/11/2025 | exact | 47 | loss run, claim OHM-25-CA-018822 |
| `LossHistory_LineOfBusiness_A` | Commercial Auto | exact | 4,47 | loss run, claim OHM-25-CA-018822 |
| `LossHistory_OccurrenceDescription_A` | Box truck backing at a customer's loading dock struck and damaged the customer's awning... | semantic | 47 | loss run, claim OHM-25-CA-018822 |
| `LossHistory_PaidAmount_A` | $6,412 | exact | 47,48 | loss run, claim OHM-25-CA-018822; TRAP: the 12/31/2025 valuation and the stale August summary |
| `LossHistory_ReservedAmount_A` | $1,500 | exact | 47,48 | loss run, claim OHM-25-CA-018822; TRAP: the 12/31/2025 valuation and the stale August summary |
| `LossHistory_ClaimStatus_SubrogationCode_A` | N | exact | see note | loss run, claim OHM-25-CA-018822 |
| `LossHistory_ClaimStatus_OpenCode_A` | Y | exact | see note | loss run, claim OHM-25-CA-018822 |
| `LossHistory_OccurrenceDate_B` | 07/22/2023 | exact | 4,28,47,50 | loss run, claim VFM-23-P-30418 |
| `LossHistory_ClaimDate_B` | 07/24/2023 | exact | 47,48 | loss run, claim VFM-23-P-30418 |
| `LossHistory_LineOfBusiness_B` | Commercial Property | exact | 1,4,44,47 | loss run, claim VFM-23-P-30418 |
| `LossHistory_OccurrenceDescription_B` | Hail damage to the roof and rooftop HVAC units at 2850 Kellerman Industrial Pkwy | semantic | 47 | loss run, claim VFM-23-P-30418 |
| `LossHistory_PaidAmount_B` | $41,980 | exact | 4,47,48,50 | loss run, claim VFM-23-P-30418 |
| `LossHistory_ReservedAmount_B` | $0 | exact | see note | loss run, claim VFM-23-P-30418 |
| `LossHistory_ClaimStatus_SubrogationCode_B` | N | exact | see note | loss run, claim VFM-23-P-30418 |
| `LossHistory_ClaimStatus_OpenCode_B` | N | exact | see note | loss run, claim VFM-23-P-30418 |
| `LossHistory_OccurrenceDate_C` | 03/03/2022 | exact | 4,47,50 | loss run, claim OHM-22-CA-004471; TRAP: reported under the FORMER name - same insured |
| `LossHistory_ClaimDate_C` | 03/04/2022 | exact | 47,48 | loss run, claim OHM-22-CA-004471 |
| `LossHistory_LineOfBusiness_C` | Commercial Auto | exact | 4,47 | loss run, claim OHM-22-CA-004471 |
| `LossHistory_OccurrenceDescription_C` | Insured service van rear-ended by a third party while stopped at a traffic light; vehic... | semantic | 47 | loss run, claim OHM-22-CA-004471 |
| `LossHistory_PaidAmount_C` | $3,775 | exact | 4,47,48,50 | loss run, claim OHM-22-CA-004471 |
| `LossHistory_ReservedAmount_C` | $0 | exact | see note | loss run, claim OHM-22-CA-004471 |
| `LossHistory_ClaimStatus_SubrogationCode_C` | Y | exact | see note | loss run, claim OHM-22-CA-004471 |
| `LossHistory_ClaimStatus_OpenCode_C` | N | exact | see note | loss run, claim OHM-22-CA-004471 |
| `LossHistory_InformationYearCount_A` | 5 | exact | see note | the market requires 5 years |
| `LossHistory_TotalAmount_A` | $52,167 | exact | derived | ACORD tooltip: PAID - the sum of the three rows' paid amounts; TRAP: $53,667 is incurred |

### ACORD_125 - boxes a RULE owns as blank

| box | rule | trap |
|---|---|---|
| `Policy_PolicyNumberIdentifier_A` | client: blank for a new-business quote | OHM-GL-4471902-25 (expiring), IMF-3318207 (question 4), CG 25 04 05 09 (a form) |
| `Policy_Status_IssueIndicator_A` | the transaction is a quote | RENEW: the incumbent's renewal offer and the SUPERSEDED 2024 application |
| `Policy_Status_BoundIndicator_A` | the transaction is a quote | RENEW: the incumbent's renewal offer and the SUPERSEDED 2024 application |
| `Policy_Status_ChangeIndicator_A` | the transaction is a quote | RENEW: the incumbent's renewal offer and the SUPERSEDED 2024 application |
| `Policy_Status_CancelIndicator_A` | the transaction is a quote | RENEW: the incumbent's renewal offer and the SUPERSEDED 2024 application |
| `Policy_Status_RenewIndicator_A` | the transaction is a quote | RENEW: the incumbent's renewal offer and the SUPERSEDED 2024 application |
| `Policy_Status_EffectiveDate_A` | nothing is bound - the acknowledgement says it is not a binder |  |
| `Policy_Status_EffectiveTime_A` | nothing is bound - the acknowledgement says it is not a binder |  |
| `Policy_Status_EffectiveTimeAMIndicator_A` | nothing is bound - the acknowledgement says it is not a binder |  |
| `Policy_Status_EffectiveTimePMIndicator_A` | nothing is bound - the acknowledgement says it is not a binder |  |
| `Policy_SectionAttached_OtherPremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `Policy_SectionAttached_OtherPremiumAmount_B` | a new-business quote is not priced - client rule: blank unless known |  |
| `Policy_SectionAttached_OtherPremiumAmount_C` | a new-business quote is not priced - client rule: blank unless known |  |
| `Policy_SectionAttached_OtherPremiumAmount_D` | a new-business quote is not priced - client rule: blank unless known |  |
| `Policy_SectionAttached_OtherPremiumAmount_E` | a new-business quote is not priced - client rule: blank unless known |  |
| `Policy_SectionAttached_OtherPremiumAmount_F` | a new-business quote is not priced - client rule: blank unless known |  |
| `BoilerAndMachineryLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `BusinessOwnersLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `CommercialInlandMarineLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `CommercialPropertyLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $61,775 / $27,940 / $9,880 are EXPIRING premiums |
| `CommercialVehicleLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $61,775 / $27,940 / $9,880 are EXPIRING premiums |
| `CommercialUmbrellaLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $61,775 / $27,940 / $9,880 are EXPIRING premiums |
| `CrimeLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `CyberAndPrivacyLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `FiduciaryLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `GarageAndDealersLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `LiquorLiabilityLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `MotorCarrierLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `TruckersLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `YachtLineOfBusiness_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known |  |
| `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $38,420 is the expiring GL premium |
| `Policy_SectionAttached_AccountsReceivableValuablePapersIndicator_A` | not attached - only 125/126/127 are generated (client: tick 'only when Primble actually... |  |
| `Policy_SectionAttached_DealerIndicator_A` | not attached - only 125/126/127 are generated (client: tick 'only when Primble actually... |  |
| `Policy_SectionAttached_ElectronicDataProcessingIndicator_A` | not attached - only 125/126/127 are generated (client: tick 'only when Primble actually... |  |
| `Policy_SectionAttached_GlassAndSignIndicator_A` | not attached - only 125/126/127 are generated (client: tick 'only when Primble actually... |  |
| `Policy_SectionAttached_InstallationBuildersRiskIndicator_A` | not attached - only 125/126/127 are generated (client: tick 'only when Primble actually... |  |
| `Policy_SectionAttached_OpenCargoIndicator_A` | not attached - only 125/126/127 are generated (client: tick 'only when Primble actually... |  |
| `CommercialPolicy_Attachment_ContractorsSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_StatementOfValuesIndicator_A` | not attached | the package CONTAINS a statement of values and loss runs - they are not ACORD attachmen... |
| `CommercialPolicy_Attachment_LossSummaryIndicator_A` | not attached | the package CONTAINS a statement of values and loss runs - they are not ACORD attachmen... |
| `CommercialPolicy_Attachment_AdditionalInterestScheduleIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_AdditionalPremisesScheduleIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_ApartmentBuildingSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_CondominiumAssociationByLawsIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_CoveragesScheduleIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_HotelMotelSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_InternationalLiabilityExposureSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_InternationalPropertyExposureSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_PremiumPaymentSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_ProfessionalLiabilitySupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_RestaurantTavernSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_StateSupplementIndicator_A` | not attached |  |
| `CommercialPolicy_Attachment_VacantBuildingSupplementIndicator_A` | not attached |  |
| `Policy_Payment_ProducerBillIndicator_A` | billing is DIRECT | the incumbent dec: 'Agency bill - 10 installments' |
| `Policy_Payment_DepositAmount_A` | a new-business quote is not priced - client rule: blank unless known | $9,605 is the incumbent's minimum premium |
| `Policy_Payment_MinimumPremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $9,605 is the incumbent's minimum premium |
| `Policy_Payment_EstimatedTotalAmount_A` | a new-business quote is not priced - client rule: blank unless known | $138,015 is the expiring programme |
| `Policy_InformationPracticesNoticeIndicator_A` | AUTHORSHIP |  |
| `NamedInsured_LegalEntity_MemberManagerCount_A` | a corporation has no members or managers | the old LLC |
| `AdditionalInterest_CertificateRequiredIndicator_A` | the bank: 'a certificate of insurance alone is NOT acceptable' - evidence is the policy |  |
| `AdditionalInterest_SendBillIndicator_A` | 'Do not send premium bills to the bank' |  |
| `AdditionalInterest_FullName_B` | ACORD: 'as used here, this is the name of the TRUST' - question 11 is NO | Margaret A. Ellison Revocable Trust |
| `BusinessInformation_ParentOrganizationName_A` | 1a is NO | Margaret A. Ellison Revocable Trust |
| `Subsidiary_ParentSubsidiaryRelationshipDescription_A` | 1a is NO |  |
| `Subsidiary_ParentOwnershipPercent_A` | 1a is NO | 60% |
| `CancelNonRenew_NonPaymentIndicator_A` | the 2023 notice of cancellation for non-payment was RESCINDED - no cancellation took ef... | the rescinded notice |
| `CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A` | question 6 is NO |  |
| `CommercialPolicy_UncorrectedFireCodeViolationExplanation_A` | question 8 is NO - the citation was corrected | 02/11/2026 / 03/02/2026 |
| `CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_A` | question 8 is NO - the citation was corrected | 02/11/2026 / 03/02/2026 |
| `CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A` | question 8 is NO - the citation was corrected | 02/11/2026 / 03/02/2026 |
| `CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_A` | question 8 is NO - the citation was corrected | 02/11/2026 / 03/02/2026 |
| `CommercialPolicy_UncorrectedFireCodeViolationExplanation_B` | question 8 is NO - the citation was corrected |  |
| `CommercialPolicy_UncorrectedFireCodeViolation_OccurrenceDate_B` | question 8 is NO - the citation was corrected |  |
| `CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_B` | question 8 is NO - the citation was corrected |  |
| `CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDescription_B` | question 8 is NO - the citation was corrected |  |
| `CommercialPolicy_JudgementOrLienExplanation_A` | question 10 is NO - the judgment was won BY the applicant | $22,480 v. Two Rivers Catering |
| `CommercialPolicy_JudgementOrLien_OccurrenceDate_A` | question 10 is NO - the judgment was won BY the applicant | $22,480 v. Two Rivers Catering |
| `CommercialPolicy_JudgementOrLien_ResolutionDate_A` | question 10 is NO - the judgment was won BY the applicant | $22,480 v. Two Rivers Catering |
| `CommercialPolicy_JudgementOrLien_ResolutionDescription_A` | question 10 is NO - the judgment was won BY the applicant | $22,480 v. Two Rivers Catering |
| `CommercialPolicy_JudgementOrLienExplanation_B` | question 10 is NO - the judgment was won BY the applicant |  |
| `CommercialPolicy_JudgementOrLien_OccurrenceDate_B` | question 10 is NO - the judgment was won BY the applicant |  |
| `CommercialPolicy_JudgementOrLien_ResolutionDate_B` | question 10 is NO - the judgment was won BY the applicant |  |
| `CommercialPolicy_JudgementOrLien_ResolutionDescription_B` | question 10 is NO - the judgment was won BY the applicant |  |
| `CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A` | question 14 is NO | the 2024 application's DJI Mavic |
| `LossHistory_NoPriorLossesIndicator_A` | three claims exist | 'Umbrella - no known losses' and 'no losses in the past 3 years' are narrative |
| `NamedInsured_Initials_A` | AUTHORSHIP |  |
| `Producer_AuthorizedRepresentative_Signature_A` | AUTHORSHIP - only the producer signs (the Sign button), never the fill |  |
| `NamedInsured_Signature_A` | AUTHORSHIP - the applicant signs |  |
| `NamedInsured_SignatureDate_A` | AUTHORSHIP - set when signed |  |

### ACORD_125 - not scored (grade by hand)

| box | value to look for | why |
|---|---|---|
| `Form_CompletionDate_A` |  | the generation date |
| `Producer_FullName_A` | Riverbend Insurance Partners, LLC | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_MailingAddress_LineOne_A` | 401 Church St | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_MailingAddress_LineTwo_A` | Suite 1700 | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_MailingAddress_CityName_A` | Nashville | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_MailingAddress_StateOrProvinceCode_A` | TN | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_MailingAddress_PostalCode_A` | 37219 | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_ContactPerson_FullName_A` | Caroline Whitlock | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_ContactPerson_PhoneNumber_A` | 615-555-0410 | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_ContactPerson_EmailAddress_A` | cwhitlock@riverbend-example.com | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Insurer_ProducerIdentifier_A` | RIV-0417 | client: 'only if verified from agency/AMS' - Ridgeline's code for Riverbend is printed ... |
| `Insurer_SubProducerIdentifier_A` | 22 | as the agency code |
| `Producer_CustomerIdentifier_A` | CUMBHEA-01 | client: the agency's customer id, verified from its AMS - the AMS export prints CUMBHEA... |
| `Policy_SectionAttached_VehicleScheduleIndicator_A` |  | disputed: ACORD 127 (generated with this 125) carries the vehicles and drivers; whether... |
| `Policy_SectionAttached_DriverInformationScheduleIndicator_A` |  | disputed: ACORD 127 (generated with this 125) carries the vehicles and drivers; whether... |
| `CommercialPolicy_Attachment_OtherIndicator_A` |  | listing ACORD 126 / 127 as 'other' attachments is acceptable either way |
| `CommercialPolicy_Attachment_OtherDescription_A` |  | as the indicator |
| `CommercialPolicy_Attachment_OtherIndicator_B` |  | listing ACORD 126 / 127 as 'other' attachments is acceptable either way |
| `CommercialPolicy_Attachment_OtherDescription_B` |  | as the indicator |
| `CommercialPolicy_Attachment_OtherIndicator_C` |  | listing ACORD 126 / 127 as 'other' attachments is acceptable either way |
| `CommercialPolicy_Attachment_OtherDescription_C` |  | as the indicator |
| `CommercialPolicy_Attachment_OtherIndicator_D` |  | listing ACORD 126 / 127 as 'other' attachments is acceptable either way |
| `CommercialPolicy_Attachment_OtherDescription_D` |  | as the indicator |
| `CommercialPolicy_Attachment_OtherIndicator_E` |  | listing ACORD 126 / 127 as 'other' attachments is acceptable either way |
| `CommercialPolicy_Attachment_OtherDescription_E` |  | as the indicator |
| `CommercialPolicy_Attachment_OtherIndicator_F` |  | listing ACORD 126 / 127 as 'other' attachments is acceptable either way |
| `CommercialPolicy_Attachment_OtherDescription_F` |  | as the indicator |
| `AdditionalInterest_MailingAddress_CountryCode_A` |  | no country is printed; 'US' is harmless either way |
| `OtherPolicy_LineOfBusinessCode_A` |  | ACORD wants a line CODE; the repo has no ACORD line-of-business code table |
| `PriorCoverage_OtherLine_LineOfBusinessCode_A` |  | ACORD wants a CODE (umbrella); the repo has no code table |
| `Producer_AuthorizedRepresentative_FullName_A` | Caroline Whitlock | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_StateLicenseIdentifier_A` | 2204418 | client: 'state producer license: completed where applicable' - Primble's account profil... |
| `Producer_NationalIdentifier_A` | 19448210 | client: 'NPN: completed' - Primble's account profile has NO NPN field (audit gap); the ... |

### ACORD_125 - 174 boxes the documents never support (must stay blank)

`Producer_FaxNumber_A`, `Policy_LineOfBusiness_BoilerAndMachineryIndicator_A`, `Policy_LineOfBusiness_BusinessOwnersIndicator_A`, `Policy_LineOfBusiness_CrimeIndicator_A`, `Policy_LineOfBusiness_CyberAndPrivacy_A`, `Policy_LineOfBusiness_FiduciaryLiabilityIndicator_A`, `Policy_LineOfBusiness_GarageAndDealersIndicator_A`, `Policy_LineOfBusiness_LiquorLiabilityIndicator_A`, `Policy_LineOfBusiness_MotorCarrierIndicator_A`, `Policy_LineOfBusiness_TruckersIndicator_A`, `Policy_LineOfBusiness_YachtIndicator_A`, `Policy_LineOfBusiness_CommercialInlandMarineIndicator_A`, `Policy_LineOfBusiness_OtherIndicator_A`, `Policy_LineOfBusiness_OtherLineOfBusinessDescription_A`, `Policy_LineOfBusiness_OtherIndicator_B`, `Policy_LineOfBusiness_OtherLineOfBusinessDescription_B`, `Policy_LineOfBusiness_OtherIndicator_C`, `Policy_LineOfBusiness_OtherLineOfBusinessDescription_C`, `Policy_LineOfBusiness_OtherIndicator_D`, `Policy_LineOfBusiness_OtherLineOfBusinessDescription_D`, `Policy_LineOfBusiness_OtherIndicator_E`, `Policy_LineOfBusiness_OtherLineOfBusinessDescription_E`, `Policy_LineOfBusiness_OtherIndicator_F`, `Policy_LineOfBusiness_OtherLineOfBusinessDescription_F`, `NamedInsured_MailingAddress_LineTwo_A`, `NamedInsured_FullName_C`, `NamedInsured_MailingAddress_LineOne_C`, `NamedInsured_MailingAddress_LineTwo_C`, `NamedInsured_MailingAddress_CityName_C`, `NamedInsured_MailingAddress_StateOrProvinceCode_C`, `NamedInsured_MailingAddress_PostalCode_C`, `NamedInsured_GeneralLiabilityCode_C`, `NamedInsured_SICCode_C`, `NamedInsured_NAICSCode_C`, `NamedInsured_TaxIdentifier_C`, `NamedInsured_Primary_PhoneNumber_C`, `NamedInsured_Primary_WebsiteAddress_C`, `NamedInsured_LegalEntity_IndividualIndicator_A`, `NamedInsured_LegalEntity_JointVentureIndicator_A`, `NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A`, `NamedInsured_LegalEntity_NotForProfitIndicator_A`, `NamedInsured_LegalEntity_OtherIndicator_A`, `NamedInsured_LegalEntity_PartnershipIndicator_A`, `NamedInsured_LegalEntity_SubchapterSCorporationIndicator_A`, `NamedInsured_LegalEntity_TrustIndicator_A`, `NamedInsured_LegalEntity_OtherDescription_A`, `NamedInsured_LegalEntity_CorporationIndicator_B`, `NamedInsured_LegalEntity_IndividualIndicator_B`, `NamedInsured_LegalEntity_JointVentureIndicator_B`, `NamedInsured_LegalEntity_NotForProfitIndicator_B`, `NamedInsured_LegalEntity_OtherIndicator_B`, `NamedInsured_LegalEntity_PartnershipIndicator_B`, `NamedInsured_LegalEntity_SubchapterSCorporationIndicator_B`, `NamedInsured_LegalEntity_TrustIndicator_B`, `NamedInsured_LegalEntity_OtherDescription_B`, `NamedInsured_LegalEntity_CorporationIndicator_C`, `NamedInsured_LegalEntity_IndividualIndicator_C`, `NamedInsured_LegalEntity_JointVentureIndicator_C`, `NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_C`, `NamedInsured_LegalEntity_NotForProfitIndicator_C`, `NamedInsured_LegalEntity_OtherIndicator_C`, `NamedInsured_LegalEntity_PartnershipIndicator_C`, `NamedInsured_LegalEntity_SubchapterSCorporationIndicator_C`, `NamedInsured_LegalEntity_TrustIndicator_C`, `NamedInsured_LegalEntity_OtherDescription_C`, `NamedInsured_LegalEntity_MemberManagerCount_C`, `NamedInsured_Contact_PrimaryBusinessPhoneIndicator_A`, `NamedInsured_Contact_PrimaryHomePhoneIndicator_A`, `NamedInsured_Contact_SecondaryCellPhoneIndicator_A`, `NamedInsured_Contact_SecondaryHomePhoneIndicator_A`, `NamedInsured_Contact_PrimaryCellPhoneIndicator_B`, `NamedInsured_Contact_PrimaryHomePhoneIndicator_B`, `NamedInsured_Contact_SecondaryBusinessPhoneIndicator_B`, `NamedInsured_Contact_SecondaryHomePhoneIndicator_B`, `BusinessInformation_BusinessType_ApartmentsIndicator_A`, `BusinessInformation_BusinessType_CondominiumsIndicator_A`, `BusinessInformation_BusinessType_ContractorIndicator_A`, `BusinessInformation_BusinessType_InstitutionalIndicator_A`, `BusinessInformation_BusinessType_ManufacturingIndicator_A`, `BusinessInformation_BusinessType_OfficeIndicator_A`, `BusinessInformation_BusinessType_OtherIndicator_A`, `BusinessInformation_BusinessType_RestaurantIndicator_A`, `BusinessInformation_BusinessType_RetailIndicator_A`, `BusinessInformation_BusinessType_ServiceIndicator_A`, `BusinessInformation_BusinessType_OtherDescription_A`, `CommercialStructure_PhysicalAddress_LineTwo_A`, `CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_A`, `CommercialStructure_RiskLocation_OtherIndicator_A`, `CommercialStructure_RiskLocation_OtherDescription_A`, `CommercialStructure_InsuredInterest_TenantIndicator_A`, `CommercialStructure_InsuredInterest_OtherIndicator_A`, `CommercialStructure_InsuredInterest_OtherDescription_A`, `CommercialStructure_RiskLocation_InsideCityLimitsIndicator_B`, `CommercialStructure_RiskLocation_OtherIndicator_B`, `CommercialStructure_RiskLocation_OtherDescription_B`, `CommercialStructure_InsuredInterest_OwnerIndicator_B`, `CommercialStructure_InsuredInterest_OtherIndicator_B`, `CommercialStructure_InsuredInterest_OtherDescription_B`, `CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_C`, `CommercialStructure_RiskLocation_OtherIndicator_C`, `CommercialStructure_RiskLocation_OtherDescription_C`, `CommercialStructure_InsuredInterest_OwnerIndicator_C`, `CommercialStructure_InsuredInterest_OtherIndicator_C`, `CommercialStructure_InsuredInterest_OtherDescription_C`, `CommercialStructure_Location_ProducerIdentifier_D`, `CommercialStructure_Building_ProducerIdentifier_D`, `CommercialStructure_PhysicalAddress_LineOne_D`, `CommercialStructure_PhysicalAddress_LineTwo_D`, `CommercialStructure_PhysicalAddress_CityName_D`, `CommercialStructure_PhysicalAddress_CountyName_D`, `CommercialStructure_PhysicalAddress_StateOrProvinceCode_D`, `CommercialStructure_PhysicalAddress_PostalCode_D`, `CommercialStructure_RiskLocation_InsideCityLimitsIndicator_D`, `CommercialStructure_RiskLocation_OutsideCityLimitsIndicator_D`, `CommercialStructure_RiskLocation_OtherIndicator_D`, `CommercialStructure_RiskLocation_OtherDescription_D`, `CommercialStructure_InsuredInterest_OwnerIndicator_D`, `CommercialStructure_InsuredInterest_TenantIndicator_D`, `CommercialStructure_InsuredInterest_OtherIndicator_D`, `CommercialStructure_InsuredInterest_OtherDescription_D`, `BusinessInformation_FullTimeEmployeeCount_D`, `BusinessInformation_PartTimeEmployeeCount_D`, `CommercialStructure_AnnualRevenueAmount_D`, `BuildingOccupancy_OccupiedArea_D`, `BuildingOccupancy_OpenToPublicArea_D`, `Construction_BuildingArea_D`, `BuildingOccupancy_OperationsDescription_D`, `CommercialStructure_Question_ABBCode_D`, `AdditionalInterest_Interest_AdditionalInsuredIndicator_A`, `AdditionalInterest_Interest_BreachOfWarrantyIndicator_A`, `AdditionalInterest_Interest_CoOwnerIndicator_A`, `AdditionalInterest_Interest_EmployeeAsLessorIndicator_A`, `AdditionalInterest_Interest_LeasebackOwnerIndicator_A`, `AdditionalInterest_Interest_LendersLossPayableIndicator_A`, `AdditionalInterest_Interest_LienholderIndicator_A`, `AdditionalInterest_Interest_LossPayeeIndicator_A`, `AdditionalInterest_Interest_OtherIndicator_A`, `AdditionalInterest_Interest_OwnerIndicator_A`, `AdditionalInterest_Interest_RegistrantIndicator_A`, `AdditionalInterest_Interest_TrusteeIndicator_A`, `AdditionalInterest_Interest_OtherDescription_A`, `AdditionalInterest_Item_VehicleProducerIdentifier_A`, `AdditionalInterest_Item_BoatProducerIdentifier_A`, `AdditionalInterest_Item_AirportIdentifier_A`, `AdditionalInterest_Item_AircraftProducerIdentifier_A`, `AdditionalInterest_Item_ScheduledItemClassCode_A`, `AdditionalInterest_Item_ScheduledItemProducerIdentifier_A`, `CommercialPolicy_Question_KABCode_A`, `CommercialPolicy_Question_KAKCode_A`, `CommercialPolicy_FormalSafetyProgram_MonthlyMeetingsIndicator_B`, `OtherPolicy_PolicyNumberIdentifier_B`, `OtherPolicy_LineOfBusinessCode_B`, `OtherPolicy_PolicyNumberIdentifier_C`, `OtherPolicy_LineOfBusinessCode_C`, `OtherPolicy_PolicyNumberIdentifier_D`, `OtherPolicy_LineOfBusinessCode_D`, `CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A`, `CancelNonRenew_OtherIndicator_A`, `CancelNonRenew_OtherDescription_A`, `CommercialPolicy_PastFiveYearsAnyApplicantIndictedOrConvictedFraudBriberyArsonExplanation_A`, `CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_A`, `CommercialPolicy_ForeclosureRepossessionBankruptcy_OccurrenceDate_A`, `CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDate_A`, `CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDescription_A`, `CommercialPolicy_ForeclosureRepossessionBankruptcyExplanation_B`, `CommercialPolicy_ForeclosureRepossessionBankruptcy_OccurrenceDate_B`, `CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDate_B`, `CommercialPolicy_ForeclosureRepossessionBankruptcy_ResolutionDescription_B`, `PriorCoverage_Property_TotalPremiumAmount_C`, `PriorCoverage_OtherLine_InsurerFullName_C`, `PriorCoverage_OtherLine_PolicyNumberIdentifier_C`, `PriorCoverage_OtherLine_TotalPremiumAmount_C`, `PriorCoverage_OtherLine_EffectiveDate_C`, `PriorCoverage_OtherLine_ExpirationDate_C`

## ACORD_126 - every box that must carry a value

| box | expected | match | page(s) | trap / note |
|---|---|---|---|---|
| `Form_EditionIdentifier_A` | ACORD 126 (2025/03) | exact | template | the template's footer |
| `Policy_EffectiveDate_A` | 12/01/2026 | exact | 1,2,3,4,5,15 | DECISION POINT: the client's rule (8-19-26) is that the application describes the policy BEING APPLIED FOR. The 15 Sep 'section forms keep the current policy's identit... |
| `Insurer_FullName_A` | Ridgeline Specialty Insurance Company | exact | 1,2,3,6,15 | DECISION POINT: the client's rule (8-19-26) is that the application describes the policy BEING APPLIED FOR. The 15 Sep 'section forms keep the current policy's identit... |
| `Insurer_NAICCode_A` | 41297 | exact | 2 | verified on the MGA acknowledgement; TRAP: 27718 |
| `NamedInsured_FullName_A` | Cumberland Hearth & Hospitality Supply, Inc. | exact | 1,2,3,5,9,10 | the first named insured (a box listing both named insureds also scores correct) |
| `GeneralLiability_CoverageIndicator_A` | Y | exact | see note | commercial general liability is requested |
| `GeneralLiability_OccurrenceIndicator_A` | Y | exact | see note | occurrence form, as expiring |
| `GeneralLiability_PropertyDamage_DeductibleIndicator_A` | Y | exact | see note | requested |
| `GeneralLiability_PropertyDamage_DeductibleAmount_A` | $1,000 | exact | 1,15,29,30,33 | TRAP: the expiring policy has none |
| `GeneralLiability_DeductiblePerOccurrenceIndicator_A` | Y | exact | see note | per occurrence |
| `GeneralLiability_GeneralAggregate_LimitAmount_A` | $2,000,000 | exact | 3,4,5,6,13,15 |  |
| `GeneralLiability_GeneralAggregate_LimitAppliesPerLocationIndicator_A` | Y | exact | see note | CG 25 04 requested; TRAP: the expiring aggregate is per policy |
| `GeneralLiability_ProductsAndCompletedOperations_AggregateLimitAmount_A` | $2,000,000 | exact | 3,4,5,6,13,15 | REQUESTED limit; TRAP: the umbrella's $5,000,000 |
| `GeneralLiability_PersonalAndAdvertisingInjury_LimitAmount_A` | $1,000,000 | exact | 1,9,12,13,15,17 | REQUESTED limit; TRAP: the umbrella's $5,000,000 |
| `GeneralLiability_EachOccurrence_LimitAmount_A` | $1,000,000 | exact | 1,9,12,13,15,17 | REQUESTED limit; TRAP: the umbrella's $5,000,000 |
| `GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A` | $300,000 | exact | 1,2,5,6,7,9 | REQUESTED limit; TRAP: $100,000 is the EXPIRING limit |
| `GeneralLiability_MedicalExpense_EachPersonLimitAmount_A` | $10,000 | exact | 1,15,46 | REQUESTED limit; TRAP: $5,000 is the EXPIRING limit |
| `GeneralLiability_EmployeeBenefits_LimitAmount_A` | $1,000,000 | exact | 1,9,12,13,15,17 | REQUESTED limit; TRAP: the umbrella's $5,000,000 |
| `GeneralLiabilityLineOfBusiness_RemarkText_A` | Per-location general aggregate (CG 25 04) requested for all three locations; the landlo... | semantic | 16 |  |
| `GeneralLiability_Hazard_LocationProducerIdentifier_A` | 1 | exact | see note |  |
| `GeneralLiability_Hazard_HazardProducerIdentifier_A` | 1 | exact | see note |  |
| `GeneralLiability_Hazard_ClassCode_A` | 12683 | exact | 3,15,29,30 |  |
| `GeneralLiability_Hazard_PremiumBasisCode_A` | S | exact | see note |  |
| `GeneralLiability_Hazard_Exposure_A` | $14,950,000 | exact | 15 | the PROPOSED-term estimate; TRAP: $13,700,000 expiring |
| `GeneralLiability_Hazard_TerritoryCode_A` | 004 | exact | see note |  |
| `GeneralLiability_Hazard_Classification_A` | Kitchen and Restaurant Equipment Distributors - commercial | semantic | 15,29 |  |
| `GeneralLiability_Hazard_LocationProducerIdentifier_B` | 2 | exact | see note |  |
| `GeneralLiability_Hazard_HazardProducerIdentifier_B` | 1 | exact | see note |  |
| `GeneralLiability_Hazard_ClassCode_B` | 68706 | exact | 15,29,30 |  |
| `GeneralLiability_Hazard_PremiumBasisCode_B` | A | exact | see note |  |
| `GeneralLiability_Hazard_Exposure_B` | 12,500 | exact | 5,6,15,28,29,30 | the PROPOSED-term estimate |
| `GeneralLiability_Hazard_TerritoryCode_B` | 005 | exact | see note |  |
| `GeneralLiability_Hazard_Classification_B` | Warehouses - private - occupied by the named insured | semantic | 15,29 |  |
| `GeneralLiability_Hazard_LocationProducerIdentifier_C` | 3 | exact | see note |  |
| `GeneralLiability_Hazard_HazardProducerIdentifier_C` | 1 | exact | see note |  |
| `GeneralLiability_Hazard_ClassCode_C` | 91127 | exact | 4,15,29,30 |  |
| `GeneralLiability_Hazard_PremiumBasisCode_C` | P | exact | see note |  |
| `GeneralLiability_Hazard_Exposure_C` | $1,284,600 | exact | 5,15,47 | the PROPOSED-term estimate; TRAP: $1,190,000 expiring |
| `GeneralLiability_Hazard_TerritoryCode_C` | 006 | exact | see note |  |
| `GeneralLiability_Hazard_Classification_C` | Appliances and Accessories - installation, servicing or repair - commercial | semantic | 15 |  |
| `GeneralLiability_EmployeeBenefits_PerClaimDeductibleAmount_A` | $1,000 | exact | 1,15,29,30,33 |  |
| `GeneralLiability_EmployeeBenefits_EmployeeCount_A` | 73 | exact | see note |  |
| `GeneralLiability_EmployeeBenefits_EmployeeCoveredCount_A` | 66 | exact | see note |  |
| `GeneralLiability_EmployeeBenefits_RetroactiveDate_A` | 12/01/2019 | exact | 15,29,30,47 | TRAP: 03/01/2015 is the E&O retro |
| `GeneralLiabilityLineOfBusiness_Question_AAHCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_AAICode_A` | N | exact | see note | the GL supplemental |
| `Contractors_Question_AABCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_ApplicantDrawPlansForOthersExplanation_A` | Prepares CAD kitchen layout drawings showing equipment placement for customers' kitchen... | semantic | 15 |  |
| `Contractors_Question_AAICode_A` | N | exact | see note | the GL supplemental |
| `Contractors_Question_AACCode_A` | N | exact | see note | the GL supplemental |
| `Contractors_Question_ABBCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_SubcontractorsCarryLowerLimitsExplanation_A` | Subcontractors carry $1,000,000 / $2,000,000 general liability but are not required to ... | semantic | 15 |  |
| `Contractors_Question_AADCode_A` | N | exact | see note | the GL supplemental |
| `Contractors_Question_AAECode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_ApplicantLeaseEquipmentToOthersExplanation_A` | Loaner combi ovens and reach-in refrigerators are provided to customers, without operat... | semantic | 15 |  |
| `GeneralLiabilityLineOfBusiness_Question_AAJCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_ApplicantInstallServiceProductsExplanation_A` | Installs and services the commercial kitchen equipment it sells, through its subsidiary... | semantic | see note |  |
| `GeneralLiabilityLineOfBusiness_Question_ABACode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ABBCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_ResearchDevelopmentConductedNewProductsPlannedExplanation_A` | A private-label descaler is planned for 2027, to be blended by the same contract blende... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ABCCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_GuaranteesWarrantiesHoldHarmlessExplanation_A` | One-year labor warranty on installations; installation contracts include hold harmless ... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ABDCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ABECode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_ProductsRecalledDiscontinuedExplanation_A` | Discontinued the Volunteer Grill gas griddle line in 2024 after the manufacturer's reca... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ABFCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_ProductsOfOthersSoldUnderApplicantLabelExplanation_A` | The CHHS ProClean degreaser is manufactured by Delta Chem Blending, Inc. and sold under... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ABGCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ABHCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ABICode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_NamedInsuredSellToOtherNamedInsuredExplanation_R` | The applicant sells replacement parts at cost to its subsidiary, Cumberland Hearth Serv... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ABJCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ACACode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ACJCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_OperationsInvolveStoringDisposingTransportingHazardousMaterialExplanation_A` | Stores corrosive degreaser concentrate in sealed drums, and technicians recover used re... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ACBCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_AnyListedOperationsSoldAcquiredLastFiveYearsExplanation_A` | Acquired the assets of Bluegrass Bakery Equipment Service (Bowling Green, KY) in 2023; ... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ACCCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_MachineryOrEquipmentLoanedRentedOthersExplanation_A` | Loaner combi ovens and reach-in refrigerators lent to service customers during repairs | semantic | 16 |  |
| `Contractors_Question_AAHCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ACDCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_AnyParkingFacilitiesOwnedRentedExplanation_A` | Owned surface parking lot at 2850 Kellerman Industrial Pkwy, 60 spaces for customers an... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_KAGCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ACFCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_SportingOrSocialEventsSponsoredExplanation_A` | Annual customer appreciation barbecue at the Kellerman showroom (about 250 guests); alc... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_KABCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_ACGCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_StructuralAlterationsContemplatedExplanation_A` | A mezzanine addition in the Kellerman warehouse is planned for 2027; permits are pending | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_ACHCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_AABCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_ApplicantActiveJointVenturesExplanation_A` | 40% member of Music Row Kitchen Rentals, LLC, a shared commercial kitchen rental; insur... | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_AACCode_A` | N | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_Question_AADCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_LabourInterchangeOtherBusinessSubsidiariesExplanation_A` | Technicians of the applicant and of its subsidiary are interchanged as workload requires | semantic | 16 |  |
| `GeneralLiabilityLineOfBusiness_Question_AAFCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_CrimesOccurredOrAttemptedLastThreeYearsExplanation_A` | Attempted break-in at the La Vergne parts depot on 01/09/2025; the alarm sounded, the i... | semantic | 16 |  |
| `Contractors_Question_AAGCode_A` | Y | exact | see note | the GL supplemental |
| `GeneralLiabilityLineOfBusiness_FormalSafetySecurityPolicyInEffectExplanation_A` | Written safety program and a written security policy (alarm, cameras, gated yard, key-c... | semantic | 16 |  |
| `AthleticTeam_SportDescription_A` | Bowling (adult league) | semantic | 16 |  |
| `AthleticTeam_ContactSportCode_A` | N | exact | see note |  |
| `AthleticTeam_AgeGroup_OverEighteenIndicator_A` | Y | exact | see note | an adult league |
| `AthleticTeam_SponsorshipExtentDescription_A` | Team shirts and league fees only | semantic | 16,51 |  |
| `CommercialInlandMarineProperty_PropertySubClass_LargeEquipmentIndicator_A` | Y | exact | see note | combi ovens and refrigerators |
| `PropertyItem_ItemDetail_InstructionGivenCode_A` | Y | exact | see note |  |
| `Contractors_SubcontractorsPaidAmount_A` | $412,000 | exact | 1,2,3,9,10,11 |  |
| `Contractors_WorkSubcontractedPercent_A` | 22% | exact | see note |  |
| `Contractors_FullTimeEmployeeCount_A` | 66 | exact | see note | TRAP: 73 is the head count |
| `Contractors_PartTimeEmployeeCount_A` | 7 | exact | see note | TRAP: 9 agency temps |
| `GeneralLiabilityLineOfBusiness_TypeOfWorkSubcontractedDescription_A` | Final electrical connections by licensed electricians and gas and plumbing hookups by l... | semantic | 15,22 |  |
| `ProductAndCompletedOperations_ProductName_A` | CHHS ProClean private-label degreaser and oven cleaner | semantic | 15 | TRAP: a GL rating class is not a product |
| `ProductAndCompletedOperations_AnnualGrossSalesAmount_A` | $186,000 | exact | 1,2,3,4,5,8 |  |
| `ProductAndCompletedOperations_UnitCount_A` | 24,800 | exact | 15,16 |  |
| `ProductAndCompletedOperations_InMarketMonthCount_A` | 54 | exact | see note |  |
| `ProductAndCompletedOperations_ExpectedLifeMonthCount_A` | 24 | exact | see note |  |
| `ProductAndCompletedOperations_IntendedUse_A` | Degreasing and cleaning commercial kitchen equipment | semantic | 15 |  |
| `ProductAndCompletedOperations_PrincipalComponents_A` | Sodium hydroxide, surfactants and water | semantic | 15 |  |
| `ProductAndCompletedOperations_ProductName_B` | Forni Lombardi imported gas deck pizza ovens | semantic | 15 | TRAP: a GL rating class is not a product |
| `ProductAndCompletedOperations_AnnualGrossSalesAmount_B` | $2,340,000 | exact | 12,15,20 |  |
| `ProductAndCompletedOperations_UnitCount_B` | 156 | exact | see note |  |
| `ProductAndCompletedOperations_InMarketMonthCount_B` | 96 | exact | see note |  |
| `ProductAndCompletedOperations_ExpectedLifeMonthCount_B` | 180 | exact | see note |  |
| `ProductAndCompletedOperations_IntendedUse_B` | Commercial baking in restaurant kitchens | semantic | 15 |  |
| `ProductAndCompletedOperations_PrincipalComponents_B` | Steel shell, refractory stone deck and gas burners | semantic | 15 |  |
| `ProductAndCompletedOperations_ProductName_C` | Vettore imported commercial espresso machines | semantic | 15 | TRAP: a GL rating class is not a product |
| `ProductAndCompletedOperations_AnnualGrossSalesAmount_C` | $1,120,000 | exact | 2,3,5,6,7,8 |  |
| `ProductAndCompletedOperations_UnitCount_C` | 410 | exact | see note |  |
| `ProductAndCompletedOperations_InMarketMonthCount_C` | 72 | exact | see note |  |
| `ProductAndCompletedOperations_ExpectedLifeMonthCount_C` | 120 | exact | see note |  |
| `ProductAndCompletedOperations_IntendedUse_C` | Commercial espresso preparation | semantic | 15 |  |
| `ProductAndCompletedOperations_PrincipalComponents_C` | Stainless steel boiler, pumps and electronic controls | semantic | 15 |  |
| `AdditionalInterest_Interest_AdditionalInsuredIndicator_A` | Y | exact | see note | the lease requires it |
| `AdditionalInterest_CertificateRequiredIndicator_A` | Y | exact | see note | the lease requires a certificate |
| `AdditionalInterest_FullName_A` | Brightline Flex Properties, LP | exact | 16,28,29,30 | lease abstract + GL supplemental |
| `AdditionalInterest_MailingAddress_LineOne_A` | 3300 West End Ave | exact | 16,28 | lease abstract + GL supplemental |
| `AdditionalInterest_MailingAddress_LineTwo_A` | Suite 400 | exact | 16,28 | lease abstract + GL supplemental |
| `AdditionalInterest_MailingAddress_CityName_A` | Nashville | exact | 1,2,3,6,10,11 | lease abstract + GL supplemental |
| `AdditionalInterest_MailingAddress_StateOrProvinceCode_A` | TN | exact | see note | lease abstract + GL supplemental |
| `AdditionalInterest_MailingAddress_PostalCode_A` | 37203 | exact | 16,23,28,30,31,32 | lease abstract + GL supplemental |
| `AdditionalInterest_Item_LocationProducerIdentifier_A` | 2 | exact | see note | lease abstract + GL supplemental |
| `AdditionalInterest_Item_BuildingProducerIdentifier_A` | 1 | exact | see note | lease abstract + GL supplemental |
| `AdditionalInterest_ItemDescription_A` | Leased premises at 410 Industrial Blvd, Suite C, La Vergne | semantic | 16 | lease abstract + GL supplemental |

### ACORD_126 - boxes a RULE owns as blank

| box | rule | trap |
|---|---|---|
| `Policy_PolicyNumberIdentifier_A` | new business: no policy number exists yet. DECISION POINT: the client's rule (8-19-26) ... | OHM-GL-4471902-25 |
| `GeneralLiability_ClaimsMadeIndicator_A` | occurrence form | the separate E&O policy is claims-made |
| `GeneralLiability_GeneralAggregate_LimitAppliesPerPolicyIndicator_A` | the requested aggregate is per LOCATION | expiring: per policy |
| `GeneralLiability_PremisesOperations_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $38,420 expiring |
| `GeneralLiability_Products_PremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $38,420 expiring |
| `GeneralLiability_OtherCoveragePremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $38,420 expiring |
| `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $38,420 expiring |
| `GeneralLiability_Hazard_PremisesOperationsRate_A` | rates and premiums are quoted by the company | expiring rate 1.842 / premium $25,235 |
| `GeneralLiability_Hazard_ProductsRate_A` | rates and premiums are quoted by the company | expiring rate 1.842 / premium $25,235 |
| `GeneralLiability_Hazard_PremisesOperationsPremiumAmount_A` | rates and premiums are quoted by the company | expiring rate 1.842 / premium $25,235 |
| `GeneralLiability_Hazard_ProductsPremiumAmount_A` | rates and premiums are quoted by the company | expiring rate 1.842 / premium $25,235 |
| `GeneralLiability_Hazard_PremisesOperationsRate_B` | rates and premiums are quoted by the company | expiring rate 96.210 / premium $1,203 |
| `GeneralLiability_Hazard_ProductsRate_B` | rates and premiums are quoted by the company | expiring rate 96.210 / premium $1,203 |
| `GeneralLiability_Hazard_PremisesOperationsPremiumAmount_B` | rates and premiums are quoted by the company | expiring rate 96.210 / premium $1,203 |
| `GeneralLiability_Hazard_ProductsPremiumAmount_B` | rates and premiums are quoted by the company | expiring rate 96.210 / premium $1,203 |
| `GeneralLiability_Hazard_PremisesOperationsRate_C` | rates and premiums are quoted by the company | expiring rate 9.886 / premium $11,764 |
| `GeneralLiability_Hazard_ProductsRate_C` | rates and premiums are quoted by the company | expiring rate 9.886 / premium $11,764 |
| `GeneralLiability_Hazard_PremisesOperationsPremiumAmount_C` | rates and premiums are quoted by the company | expiring rate 9.886 / premium $11,764 |
| `GeneralLiability_Hazard_ProductsPremiumAmount_C` | rates and premiums are quoted by the company | expiring rate 9.886 / premium $11,764 |
| `GeneralLiability_ClaimsMade_ProposedRetroactiveDate_A` | occurrence form | 03/01/2015 is the E&O policy's retro date |
| `GeneralLiability_ClaimsMade_UninterruptedCoverageEntryDate_A` | occurrence form | 03/01/2015 is the E&O policy's retro date |
| `GeneralLiabilityLineOfBusiness_AnyExposureRadioactiveMaterialsExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_AnyMedicalFacilitiesProvidedMedicalProfessionalsEmployedExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_AnyProductWorkAccidentLocationExcludedUninsuredPreviousCoverageExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_BusinessPromotionalLiteratureSafetyRepresentationsExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_DayCareFacilitiesOperatedExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_DemolitionExposureContemplatedExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_FeeChargedForParkingExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_OperationsIncludeBlastingExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_OperationsIncludeEvacuationExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_ProductsRelatedToAircraftIndustryExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_ProductsUnderLabelOfOthersExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_RecreationalFacilitiesProvidedExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_SubcontractorsWorksWithoutCertificatesOfInsuranceExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_TailCoveragePurchasedPreviousPolicyExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_VendorCoverageRequiredExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_WatercraftDocksFloatsOwnedHiredLeasedExplanation_A` | its question is NO or UNRESOLVED - no explanation |  |
| `GeneralLiabilityLineOfBusiness_Attachment_AdditionalInterestIndicator_A` | one interest - no ACORD 45 |  |
| `AdditionalInterest_FullName_B` | no leased employees (question NO) | Harpeth Staffing Solutions, Inc. supplies TEMPORARY workers |
| `AdditionalInterest_FullName_C` | no leased employees (question NO) | Harpeth Staffing Solutions, Inc. supplies TEMPORARY workers |
| `AdditionalInterest_FullName_D` | no leased employees (question NO) | Harpeth Staffing Solutions, Inc. supplies TEMPORARY workers |
| `AdditionalInterest_FullName_E` | no leased employees (question NO) | Harpeth Staffing Solutions, Inc. supplies TEMPORARY workers |
| `AdditionalInterest_WorkersCompensationCarriedCode_A` | no leased employees |  |
| `AdditionalInterest_WorkersCompensationCarriedCode_B` | no leased employees |  |
| `AdditionalInterest_WorkersCompensationCarriedCode_C` | no leased employees |  |
| `AdditionalInterest_WorkersCompensationCarriedCode_D` | no leased employees |  |
| `Producer_AuthorizedRepresentative_Signature_A` | AUTHORSHIP - only the producer signs (the Sign button), never the fill |  |
| `NamedInsured_Signature_A` | AUTHORSHIP - the applicant signs |  |
| `NamedInsured_SignatureDate_A` | AUTHORSHIP - set when signed |  |

### ACORD_126 - not scored (grade by hand)

| box | value to look for | why |
|---|---|---|
| `Form_CompletionDate_A` |  | the generation date |
| `Producer_FullName_A` | Riverbend Insurance Partners, LLC | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_CustomerIdentifier_A` | CUMBHEA-01 | client: 'only if verified from agency/AMS' - Riverbend's AMS export prints it; Primble ... |
| `GeneralLiability_UninsuredUnderinsuredMotorists_CoverageAvailableIndicator_A` |  | state-specific options; medical EXPENSE is requested but this box is ambiguous for Tenn... |
| `GeneralLiability_UninsuredUnderinsuredMotorists_CoverageAvailableNoIndicator_A` |  | state-specific options; medical EXPENSE is requested but this box is ambiguous for Tenn... |
| `GeneralLiability_MedicalPayments_CoverageAvailableIndicator_A` |  | state-specific options; medical EXPENSE is requested but this box is ambiguous for Tenn... |
| `GeneralLiability_MedicalPayments_CoverageAvailableNoIndicator_A` |  | state-specific options; medical EXPENSE is requested but this box is ambiguous for Tenn... |
| `AdditionalInterest_MailingAddress_CountryCode_A` |  | no country printed |
| `Producer_AuthorizedRepresentative_FullName_A` | Caroline Whitlock | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_StateLicenseIdentifier_A` | 2204418 | client: 'state producer license: completed where applicable' - Primble's account profil... |
| `Producer_NationalIdentifier_A` | 19448210 | client: 'NPN: completed' - Primble's account profile has NO NPN field (audit gap); the ... |

### ACORD_126 - 54 boxes the documents never support (must stay blank)

`GeneralLiability_OwnersAndContractorsProtectiveIndicator_A`, `GeneralLiability_OtherCoverageIndicator_A`, `GeneralLiability_OtherCoverageDescription_A`, `GeneralLiability_DeductiblePerClaimIndicator_A`, `GeneralLiability_BodilyInjury_DeductibleIndicator_A`, `GeneralLiability_BodilyInjury_DeductibleAmount_A`, `GeneralLiability_OtherDeductibleIndicator_A`, `GeneralLiability_OtherDeductibleDescription_A`, `GeneralLiability_OtherDeductibleAmount_A`, `GeneralLiability_GeneralAggregate_LimitAppliesPerProjectIndicator_A`, `GeneralLiability_GeneralAggregate_LimitAppliesToOtherIndicator_A`, `GeneralLiability_GeneralAggregate_LimitAppliesToCode_A`, `GeneralLiability_OtherCoverageLimitDescription_A`, `GeneralLiability_OtherCoverageLimitAmount_A`, `GeneralLiabilityLineOfBusiness_RemarkText_B`, `GeneralLiabilityLineOfBusiness_Question_ACECode_A`, `GeneralLiabilityLineOfBusiness_Question_KAACode_A`, `GeneralLiabilityLineOfBusiness_Question_KAHCode_A`, `GeneralLiabilityLineOfBusiness_Question_AAECode_A`, `GeneralLiabilityLineOfBusiness_Question_AAGCode_A`, `GeneralLiability_Otherlodgingoperationsdescription_A`, `BuildingOccupancy_ApartmentCount_A`, `BuildingOccupancy_ApartmentArea_A`, `SwimmingPool_ApprovedFenceIndicator_A`, `SwimmingPool_LimitedAccessIndicator_A`, `SwimmingPool_DivingBoardIndicator_A`, `SwimmingPool_SlideIndicator_A`, `SwimmingPool_AboveGroundIndicator_A`, `SwimmingPool_InGroundIndicator_A`, `SwimmingPool_LifeGuardIndicator_A`, `AthleticTeam_AgeGroup_TwelveAndUnderIndicator_A`, `AthleticTeam_AgeGroup_ThirteenThroughEighteenIndicator_A`, `AthleticTeam_SportDescription_B`, `AthleticTeam_ContactSportCode_B`, `AthleticTeam_SponsorshipExtentDescription_B`, `AthleticTeam_AgeGroup_TwelveAndUnderIndicator_B`, `AthleticTeam_AgeGroup_ThirteenThroughEighteenIndicator_B`, `AthleticTeam_AgeGroup_OverEighteenIndicator_B`, `GeneralLiabilityLineOfBusiness_MachineryOrEquipmentLoanedRentedOthersExplanation_B`, `CommercialInlandMarineProperty_PropertySubClass_SmallToolsIndicator_A`, `CommercialInlandMarineProperty_PropertySubClass_SmallToolsIndicator_B`, `CommercialInlandMarineProperty_PropertySubClass_LargeEquipmentIndicator_B`, `PropertyItem_ItemDetail_InstructionGivenCode_B`, `AdditionalInterest_Interest_EmployeeAsLessorIndicator_A`, `AdditionalInterest_Interest_LienholderIndicator_A`, `AdditionalInterest_Interest_LendersLossPayableIndicator_A`, `AdditionalInterest_Interest_LossPayeeIndicator_A`, `AdditionalInterest_Interest_MortgageeIndicator_A`, `AdditionalInterest_Interest_OtherIndicator_A`, `AdditionalInterest_Interest_OtherDescription_A`, `AdditionalInterest_InterestRank_A`, `AdditionalInterest_AccountNumberIdentifier_A`, `AdditionalInterest_Item_ScheduledItemProducerIdentifier_A`, `AdditionalInterest_Item_ScheduledItemClassCode_A`

## ACORD_127 - every box that must carry a value

| box | expected | match | page(s) | trap / note |
|---|---|---|---|---|
| `Form_EditionIdentifier_A` | ACORD 127 (2015/12) | exact | template | the template's footer |
| `Policy_EffectiveDate_A` | 12/01/2026 | exact | 1,2,3,4,5,15 | DECISION POINT: the client's rule (8-19-26) is that the application describes the policy BEING APPLIED FOR. The 15 Sep 'section forms keep the current policy's identit... |
| `Insurer_FullName_A` | Ridgeline Specialty Insurance Company | exact | 1,2,3,6,15 | DECISION POINT: the client's rule (8-19-26) is that the application describes the policy BEING APPLIED FOR. The 15 Sep 'section forms keep the current policy's identit... |
| `Insurer_NAICCode_A` | 41297 | exact | 2 | verified on the MGA acknowledgement; TRAP: 27718 |
| `NamedInsured_FullName_A` | Cumberland Hearth & Hospitality Supply, Inc. | exact | 1,2,3,5,9,10 | the first named insured (a box listing both named insureds also scores correct) |
| `Driver_ProducerIdentifier_A` | 1 | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_GivenName_A` | Marcus | exact | 8,9,26,34,35,50 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_OtherGivenNameInitial_A` | T | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_Surname_A` | Bellweather | exact | 8,9,26,34,35,41 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_MailingAddress_CityName_A` | Nashville | exact | 1,2,3,6,10,11 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_MailingAddress_StateOrProvinceCode_A` | TN | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_MailingAddress_PostalCode_A` | 37211 | exact | 6,14,17,23,24,26 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_GenderCode_A` | M | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_MaritalStatusCode_A` | M | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_BirthDate_A` | 06/11/1984 | exact | 34,35 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_ExperienceYearCount_A` | 25 | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_LicensedYear_A` | 2001 | exact | 34 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_LicenseNumberIdentifier_A` | 104883127 | exact | 34,35 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_LicensedStateOrProvinceCode_A` | TN | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_HiredDate_A` | 04/06/2015 | exact | 34 | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_Vehicle_ProducerIdentifier_A` | 1 | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_Vehicle_UsePercent_A` | 100 | exact | see note | driver 1 (Marcus Bellweather): the HR driver roster / MVR |
| `Driver_ProducerIdentifier_B` | 2 | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_GivenName_B` | Alicia | exact | 7,9,26,34,35,50 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_OtherGivenNameInitial_B` | R | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_Surname_B` | Fontenot | exact | 7,9,26,34,35,41 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_MailingAddress_CityName_B` | Antioch | exact | 10,11,12,13,17,18 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_MailingAddress_StateOrProvinceCode_B` | TN | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_MailingAddress_PostalCode_B` | 37013 | exact | 34 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_GenderCode_B` | F | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_MaritalStatusCode_B` | S | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_BirthDate_B` | 11/02/1991 | exact | 34,35 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_ExperienceYearCount_B` | 18 | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_LicensedYear_B` | 2008 | exact | 34 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_LicenseNumberIdentifier_B` | 117260554 | exact | 34,35 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_LicensedStateOrProvinceCode_B` | TN | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_HiredDate_B` | 03/15/2019 | exact | 34 | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_Vehicle_ProducerIdentifier_B` | 2 | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_Vehicle_UsePercent_B` | 70 | exact | see note | driver 2 (Alicia Fontenot): the HR driver roster / MVR |
| `Driver_ProducerIdentifier_C` | 3 | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_GivenName_C` | Dwayne | exact | 7,8,25,34,35 | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_OtherGivenNameInitial_C` | K | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_Surname_C` | Hollis | exact | 7,8,23,24,25,34 | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_MailingAddress_CityName_C` | Franklin | exact | 3,4,5,7,9,10 | driver 3 (Dwayne Hollis): the HR driver roster / MVR; TRAP: Franklin, KY - not Franklin, TN |
| `Driver_MailingAddress_StateOrProvinceCode_C` | KY | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR; TRAP: Franklin, KY - not Franklin, TN |
| `Driver_MailingAddress_PostalCode_C` | 42134 | exact | 34 | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_GenderCode_C` | M | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_MaritalStatusCode_C` | D | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_BirthDate_C` | 01/23/1978 | exact | 34,35 | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_ExperienceYearCount_C` | 31 | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_LicensedYear_C` | 1995 | exact | 34 | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_LicenseNumberIdentifier_C` | H22118430 | exact | 34,35 | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_LicensedStateOrProvinceCode_C` | KY | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_HiredDate_C` | 07/01/2023 | exact | 34 | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_Vehicle_ProducerIdentifier_C` | 3 | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_Vehicle_UsePercent_C` | 100 | exact | see note | driver 3 (Dwayne Hollis): the HR driver roster / MVR |
| `Driver_ProducerIdentifier_D` | 4 | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_GivenName_D` | Priyanka | exact | 7,9,26,34,35,50 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_OtherGivenNameInitial_D` | S | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_Surname_D` | Dandekar | exact | 7,9,26,34,35,41 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_MailingAddress_CityName_D` | Brentwood | exact | 10,11,12,13,23,24 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_MailingAddress_StateOrProvinceCode_D` | TN | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_MailingAddress_PostalCode_D` | 37027 | exact | 23,24,34,51 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_GenderCode_D` | F | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_MaritalStatusCode_D` | M | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_BirthDate_D` | 08/30/1996 | exact | 34,35 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_ExperienceYearCount_D` | 14 | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_LicensedYear_D` | 2012 | exact | 34 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_LicenseNumberIdentifier_D` | 121904773 | exact | 34,35 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_LicensedStateOrProvinceCode_D` | TN | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_HiredDate_D` | 09/20/2021 | exact | 34 | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_Vehicle_ProducerIdentifier_D` | 4 | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_Vehicle_UsePercent_D` | 100 | exact | see note | driver 4 (Priyanka Dandekar): the HR driver roster / MVR |
| `Driver_ProducerIdentifier_E` | 5 | exact | see note | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_GivenName_E` | Gregory | exact | 7,8,25,34,35,50 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_OtherGivenNameInitial_E` | L | exact | see note | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_Surname_E` | Szymanski | exact | 7,8,25,34,35,50 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_MailingAddress_CityName_E` | Mount Juliet | exact | 34 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_MailingAddress_StateOrProvinceCode_E` | TN | exact | see note | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_MailingAddress_PostalCode_E` | 37122 | exact | 34 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_GenderCode_E` | M | exact | see note | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_MaritalStatusCode_E` | M | exact | see note | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_BirthDate_E` | 02/14/1969 | exact | 34,35 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_ExperienceYearCount_E` | 41 | exact | see note | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_LicensedYear_E` | 1985 | exact | 34 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_LicenseNumberIdentifier_E` | 098317562 | exact | 34,35 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_LicensedStateOrProvinceCode_E` | TN | exact | see note | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_HiredDate_E` | 01/11/2010 | exact | 34 | driver 5 (Gregory Szymanski): the HR driver roster / MVR |
| `Driver_ProducerIdentifier_F` | 6 | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_GivenName_F` | Tamsin | exact | 7,9,26,34,35,36 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_OtherGivenNameInitial_F` | E | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_Surname_F` | O'Rourke | exact | 7,9,26,34,35,36 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_MailingAddress_CityName_F` | Smyrna | exact | 10,11,12,13,18,23 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_MailingAddress_StateOrProvinceCode_F` | TN | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_MailingAddress_PostalCode_F` | 37167 | exact | 34 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_GenderCode_F` | F | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_MaritalStatusCode_F` | S | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_BirthDate_F` | 12/05/2001 | exact | 34,36 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_ExperienceYearCount_F` | 9 | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_LicensedYear_F` | 2017 | exact | 1,14,27,33,34,50 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_LicenseNumberIdentifier_F` | 130555287 | exact | 34,36 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_LicensedStateOrProvinceCode_F` | TN | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_HiredDate_F` | 02/26/2024 | exact | 34 | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_Vehicle_ProducerIdentifier_F` | 2 | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `Driver_Vehicle_UsePercent_F` | 30 | exact | see note | driver 6 (Tamsin O'Rourke): the HR driver roster / MVR |
| `CommercialVehicleLineOfBusiness_Question_AAJCode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_ABACode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_KADCode_A` | Y | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_VehicleMaintenanceProgramInOperationExplanation_A` | Written preventive maintenance schedule: oil and inspection every 5,000 miles, annual D... | semantic | 33,37 |  |
| `CommercialVehicleLineOfBusiness_Question_ABCCode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_AAGCode_A` | Y | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_AAECode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_AAFCode_A` | Y | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_OperationInvolveTransportingHazardousMaterialsExplanation_A` | Vehicle 3 carries recovered refrigerant cylinders (non-flammable compressed gas) to a l... | semantic | 33 |  |
| `CommercialVehicleLineOfBusiness_Question_AABCode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_AACCode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_KAECode_A` | Y | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_ApplicantObtainMVRVerificationsExplanation_A` | MVRs are obtained at hire and every March through Clearpath MVR Services | semantic | 34 |  |
| `CommercialVehicleLineOfBusiness_Question_KAFCode_A` | Y | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_ApplicantSpecificDriverRecruitingMethodExplanation_K` | Drivers are recruited from internal technician and warehouse staff; three years of driv... | semantic | 34 |  |
| `CommercialVehicleLineOfBusiness_Question_AAHCode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_AADCode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_AAICode_A` | Y | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_Question_ABBCode_A` | N | exact | see note | the auto supplemental |
| `CommercialVehicleLineOfBusiness_KAHCode_A` | Y | exact | see note | the auto supplemental |
| `Vehicle_ProducerIdentifier_AC` | 3 | exact | see note | special equipment row A (template position) |
| `Vehicle_ProducerIdentifier_AD` | 4 | exact | see note | special equipment row B (template position) |
| `Vehicle_Question_ModifiedEquipmentDescription_A` | Refrigerant recovery unit and steel shelving | semantic | 33 |  |
| `Vehicle_Question_ModifiedEquipmentCostAmount_A` | $7,400 | exact | 33 |  |
| `Vehicle_Question_ModifiedEquipmentDescription_B` | Hydraulic liftgate (3,000 lb) | semantic | 33 |  |
| `Vehicle_Question_ModifiedEquipmentCostAmount_B` | $6,850 | exact | 33 |  |
| `AccidentConviction_DriverProducerIdentifier_A` | 3 | exact | see note |  |
| `AccidentConviction_TrafficViolationDate_A` | 05/17/2025 | exact | 34,35 | TRAP: 09/02/2019 is outside 3 years |
| `AccidentConviction_TrafficViolationDescription_A` | Speeding - 14 mph over the posted limit | semantic | 34 |  |
| `AccidentConviction_PlaceOfIncident_A` | Simpson County, KY | exact | 34 |  |
| `AccidentConviction_ViolationYearCount_A` | 3 | exact | see note |  |
| `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_FleetMonitoredPercent_A` | 100% | exact | see note |  |
| `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_MonitorDriverSafetyIndicator_A` | Y | exact | see note | the FleetPulse report |
| `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_MonitorVehicleMaintenanceIndicator_A` | Y | exact | see note | the FleetPulse report |
| `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_MileageTrackingDeviceIndicator_A` | Y | exact | see note | the FleetPulse report |
| `CommercialVehicleLineOfBusiness_LocationTrackingDeviceIndicator_A` | Y | exact | see note | the FleetPulse report |
| `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_OtherIndicator_A` | Y | exact | see note | the FleetPulse report |
| `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_OtherDesciption_A` | Forward-facing dash cameras | exact | 34,36 |  |
| `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_AdditionalDescription_A` | FleetPulse telematics units in all four vehicles report harsh braking, speeding, idle t... | semantic | 34 |  |
| `CommercialVehicleLineOfBusiness_GarageStorageDescription_A` | Vehicles are parked overnight inside the fenced, gated and camera-monitored yard at eac... | semantic | 34 |  |
| `CommercialVehicleLineOfBusiness_MaximumExposureAllVehiclesAmount_A` | $221,050 | exact | 34,46 |  |
| `AdditionalInterest_FullName_A` | Volunteer Truck Finance, LLC | exact | 33 | the auto declarations |
| `AdditionalInterest_Interest_LienholderIndicator_A` | Y | exact | see note |  |
| `AdditionalInterest_MailingAddress_LineOne_A` | 2210 Murfreesboro Pike | exact | 33 |  |
| `AdditionalInterest_MailingAddress_CityName_A` | Nashville | exact | 1,2,3,6,10,11 |  |
| `AdditionalInterest_MailingAddress_StateOrProvinceCode_A` | TN | exact | see note |  |
| `AdditionalInterest_MailingAddress_PostalCode_A` | 37217 | exact | 33 |  |
| `AdditionalInterest_InterestRank_A` | 1 | exact | see note |  |
| `AdditionalInterest_AccountNumberIdentifier_A` | 55-2190-388 | exact | 33 |  |
| `AdditionalInterest_Item_VehicleProducerIdentifier_A` | 4 | exact | see note |  |
| `AdditionalInterest_CertificateRequiredIndicator_A` | Y | exact | see note | 'certificate required' |
| `AdditionalInterest_FullName_B` | Highline Commercial Truck Credit, LLC | exact | 33 | the auto declarations |
| `AdditionalInterest_Interest_LossPayeeIndicator_B` | Y | exact | see note |  |
| `AdditionalInterest_MailingAddress_LineOne_B` | 9001 Corporate Center Dr | exact | 33 |  |
| `AdditionalInterest_MailingAddress_CityName_B` | Charlotte | exact | 23,24,33,51 |  |
| `AdditionalInterest_MailingAddress_StateOrProvinceCode_B` | NC | exact | see note |  |
| `AdditionalInterest_MailingAddress_PostalCode_B` | 28226 | exact | 33 |  |
| `AdditionalInterest_InterestRank_B` | 1 | exact | see note |  |
| `AdditionalInterest_AccountNumberIdentifier_B` | HC-778104 | exact | 33 |  |
| `AdditionalInterest_Item_VehicleProducerIdentifier_B` | 1 | exact | see note |  |
| `AdditionalInterest_MailingAddress_LineTwo_B` | Suite 300 | exact | 33 |  |
| `AdditionalInterest_CertificateRequiredIndicator_B` | Y | exact | see note | 'certificate required' |
| `CommercialVehicleLineOfBusiness_RemarkText_A` | Towing and labor added on vehicles 2 and 3; the collision deductible on vehicle 4 incre... | semantic | 34 |  |
| `Vehicle_ProducerIdentifier_A` | 1 | exact | see note | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelYear_A` | 2023 | exact | 4,16,24,27,33,50 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ManufacturersName_A` | Isuzu | exact | 27,33,50 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelName_A` | NPR-HD | exact | 27,33,50 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_BodyCode_A` | Box Truck | semantic | 33,47 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_VINIdentifier_A` | JALC4W162P7004417 | exact | 33,43,50 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_LineOne_A` | 2850 Kellerman Industrial Pkwy | exact | 6,7,10,14,16,17 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CityName_A` | Nashville | exact | 1,2,3,6,10,11 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CountyName_A` | Davidson | exact | 4,6,14,29,33,34 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_StateOrProvinceCode_A` | TN | exact | see note | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_PostalCode_A` | 37211 | exact | 6,14,17,23,24,26 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Registration_StateOrProvinceCode_A` | TN | exact | see note | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RatingTerritoryCode_A` | 104 | exact | see note | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_GrossVehicleWeight_A` | 14,500 | exact | 33 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RateClassCode_A` | 21499 | exact | 33 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RadiusOfUse_A` | 150 | exact | see note | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_CostNewAmount_A` | $78,450 | exact | 33 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental; TRAP: $61,300 is the current ACV |
| `Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_A` | $1,000 | exact | 1,15,29,30,33 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Collision_DeductibleAmount_A` | $1,000 | exact | 1,15,29,30,33 | vehicle 1 (2023 Isuzu): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_VehicleType_CommercialIndicator_A` | Y | exact | see note | trucks and vans - stated |
| `Vehicle_Use_CommercialIndicator_A` | Y | exact | see note | USE: Commercial |
| `Vehicle_Coverage_LiabilityIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_MedicalPaymentsIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UninsuredMotoristsIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UnderinsuredMotoristsIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ComprehensiveIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_CollisionIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_RentalReimbursementIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ValuationActualCashValueIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ComprehensiveDeductibleIndicator_A` | Y | exact | see note | requested coverages |
| `Vehicle_ProducerIdentifier_B` | 2 | exact | see note | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelYear_B` | 2022 | exact | 5,10,16,27,33,50 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ManufacturersName_B` | Ford | exact | 1,14,27,33,50 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelName_B` | Transit 250 | exact | 27,33,50 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_BodyCode_B` | Cargo Van | semantic | 33 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_VINIdentifier_B` | 1FTBR1C82NKA31907 | exact | 33,43,50 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_LineOne_B` | 410 Industrial Blvd | exact | 6,7,16,28,29,30 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CityName_B` | La Vergne | exact | 4,5,6,7,9,10 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CountyName_B` | Rutherford | exact | 6,10,11,12,13,24 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_StateOrProvinceCode_B` | TN | exact | see note | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_PostalCode_B` | 37086 | exact | 6,28,30,33,45 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Registration_StateOrProvinceCode_B` | TN | exact | see note | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RatingTerritoryCode_B` | 112 | exact | see note | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_GrossVehicleWeight_B` | 9,070 | exact | 33 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RateClassCode_B` | 01499 | exact | 33 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RadiusOfUse_B` | 50 | exact | see note | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_CostNewAmount_B` | $52,310 | exact | 33 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental; TRAP: $38,900 is the current ACV |
| `Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_B` | $500 | exact | see note | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Collision_DeductibleAmount_B` | $1,000 | exact | 1,15,29,30,33 | vehicle 2 (2022 Ford): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_VehicleType_CommercialIndicator_B` | Y | exact | see note | trucks and vans - stated |
| `Vehicle_Use_ServiceIndicator_B` | Y | exact | see note | USE: Service |
| `Vehicle_Coverage_LiabilityIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_MedicalPaymentsIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UninsuredMotoristsIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UnderinsuredMotoristsIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_TowingAndLabourIndicator_B` | Y | exact | see note | requested coverages; TRAP: towing is ADDED at this submission |
| `Vehicle_Coverage_ComprehensiveIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_CollisionIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ValuationActualCashValueIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ComprehensiveDeductibleIndicator_B` | Y | exact | see note | requested coverages |
| `Vehicle_ProducerIdentifier_C` | 3 | exact | see note | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelYear_C` | 2024 | exact | 4,10,14,16,22,29 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ManufacturersName_C` | Ram | exact | see note | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelName_C` | ProMaster 2500 | exact | 14,33 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_BodyCode_C` | Cargo Van | semantic | 33 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_VINIdentifier_C` | 3C6LRVDG4RE118802 | exact | 33,43 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_LineOne_C` | 1199 Hillsboro Commons Dr | exact | 3,6,7,14,28,30 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CityName_C` | Franklin | exact | 3,4,5,7,9,10 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CountyName_C` | Williamson | exact | 6,10,11,12,13,18 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_StateOrProvinceCode_C` | TN | exact | see note | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_PostalCode_C` | 37067 | exact | 3,6,14,28,30,31 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Registration_StateOrProvinceCode_C` | TN | exact | see note | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RatingTerritoryCode_C` | 118 | exact | see note | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_GrossVehicleWeight_C` | 9,350 | exact | 33 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RateClassCode_C` | 01499 | exact | 33 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RadiusOfUse_C` | 50 | exact | see note | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_CostNewAmount_C` | $56,980 | exact | 33 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental; TRAP: $51,200 is the current ACV |
| `Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_C` | $500 | exact | see note | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Collision_DeductibleAmount_C` | $1,000 | exact | 1,15,29,30,33 | vehicle 3 (2024 Ram): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_VehicleType_CommercialIndicator_C` | Y | exact | see note | trucks and vans - stated |
| `Vehicle_Use_ServiceIndicator_C` | Y | exact | see note | USE: Service |
| `Vehicle_Coverage_LiabilityIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_MedicalPaymentsIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UninsuredMotoristsIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UnderinsuredMotoristsIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_TowingAndLabourIndicator_C` | Y | exact | see note | requested coverages; TRAP: towing is ADDED at this submission |
| `Vehicle_Coverage_ComprehensiveIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_CollisionIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ValuationActualCashValueIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ComprehensiveDeductibleIndicator_C` | Y | exact | see note | requested coverages |
| `Vehicle_ProducerIdentifier_D` | 4 | exact | see note | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelYear_D` | 2021 | exact | 27,33,50 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ManufacturersName_D` | Freightliner | exact | 1,27,33,50 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_ModelName_D` | M2 106 | exact | 27,33,50 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_BodyCode_D` | Straight Truck | semantic | 33 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_VINIdentifier_D` | 1FVACWDT7MHMN4471 | exact | 33,43,50 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_LineOne_D` | 2850 Kellerman Industrial Pkwy | exact | 6,7,10,14,16,17 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CityName_D` | Nashville | exact | 1,2,3,6,10,11 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_CountyName_D` | Davidson | exact | 4,6,14,29,33,34 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_StateOrProvinceCode_D` | TN | exact | see note | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_PhysicalAddress_PostalCode_D` | 37211 | exact | 6,14,17,23,24,26 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Registration_StateOrProvinceCode_D` | TN | exact | see note | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RatingTerritoryCode_D` | 104 | exact | see note | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_GrossVehicleWeight_D` | 33,000 | exact | 17,33 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RateClassCode_D` | 31499 | exact | 33 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_RadiusOfUse_D` | 200 | exact | see note | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_CostNewAmount_D` | $142,600 | exact | 33 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental; TRAP: $103,750 is the current ACV |
| `Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_D` | $1,000 | exact | 1,15,29,30,33 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental |
| `Vehicle_Collision_DeductibleAmount_D` | $2,500 | exact | 1,2,10,20,33,34 | vehicle 4 (2021 Freightliner): auto declarations / endorsement 1 / auto supplemental; TRAP: $1,000 is the EXPIRING deductible |
| `Vehicle_VehicleType_CommercialIndicator_D` | Y | exact | see note | trucks and vans - stated |
| `Vehicle_Use_CommercialIndicator_D` | Y | exact | see note | USE: Commercial |
| `Vehicle_Coverage_LiabilityIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_MedicalPaymentsIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UninsuredMotoristsIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_UnderinsuredMotoristsIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ComprehensiveIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_CollisionIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_RentalReimbursementIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ValuationActualCashValueIndicator_D` | Y | exact | see note | requested coverages |
| `Vehicle_Coverage_ComprehensiveDeductibleIndicator_D` | Y | exact | see note | requested coverages |

### ACORD_127 - boxes a RULE owns as blank

| box | rule | trap |
|---|---|---|
| `Policy_PolicyNumberIdentifier_A` | new business: no policy number exists yet. DECISION POINT: the client's rule (8-19-26) ... | OHM-CA-4471903-25 |
| `CommercialVehicleLineOfBusiness_Attachment_CommercialAutoDriverInformationScheduleIndicator_A` | six drivers fit on the form |  |
| `CommercialVehicleLineOfBusiness_Attachment_VehicleScheduleIndicator_A` | four vehicles fit on the form | the SOLD E-350 would make five |
| `CommercialVehicleLineOfBusiness_Attachment_AdditionalInterestIndicator_A` | two interests fit on the form |  |
| `Driver_TaxIdentifier_A` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_B` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_C` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_D` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_E` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_F` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_G` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_H` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_I` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_J` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_K` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_L` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `Driver_TaxIdentifier_M` | never print an SSN - the MVRs show masked fragments only | XXX-XX-4471 |
| `CommercialVehicleLineOfBusiness_VehiclesLeasedToOthersExplanation_A` | its question is NO |  |
| `CommercialVehicleLineOfBusiness_HoldHarmlessAgreementsExplanation_A` | its question is NO |  |
| `CommercialVehicleLineOfBusiness_VehiclesUsedByFamilyMembersExplanation_A` | its question is NO |  |
| `CommercialVehicleLineOfBusiness_AnyDriversNotCoveredWorkersCompensationExplanation_A` | its question is NO |  |
| `CommercialVehicleLineOfBusiness_AnyVehiclesOwnedNotScheduledExplanation_A` | its question is NO |  |
| `CommercialVehicleLineOfBusiness_AgentInspectedVehiclesExplanation_A` | its question is NO |  |
| `Vehicle_ProducerIdentifier_AA` | 'not solely owned' is NO |  |
| `Vehicle_ProducerIdentifier_AB` | 'not solely owned' is NO |  |
| `AdditionalInterest_FullName_C` | ACORD: 'the other owner of the vehicle' - every vehicle is solely owned (encumbrances o... | the lienholder / loss payee are interests, not owners |
| `AdditionalInterest_FullName_D` | ACORD: 'the other owner of the vehicle' - every vehicle is solely owned (encumbrances o... | the lienholder / loss payee are interests, not owners |
| `Vehicle_PrimaryLiabilityRatingFactor_A` | a new-business quote is not priced - client rule: blank unless known | $14,982 expiring |
| `Vehicle_NetRatingFactor_A` | a new-business quote is not priced - client rule: blank unless known | $14,982 expiring |
| `Vehicle_TotalPremiumAmount_A` | a new-business quote is not priced - client rule: blank unless known | $14,982 expiring |
| `Vehicle_PrimaryLiabilityRatingFactor_B` | a new-business quote is not priced - client rule: blank unless known | $11,407 expiring |
| `Vehicle_NetRatingFactor_B` | a new-business quote is not priced - client rule: blank unless known | $11,407 expiring |
| `Vehicle_TotalPremiumAmount_B` | a new-business quote is not priced - client rule: blank unless known | $11,407 expiring |
| `Vehicle_PrimaryLiabilityRatingFactor_C` | a new-business quote is not priced - client rule: blank unless known | $11,866 expiring |
| `Vehicle_NetRatingFactor_C` | a new-business quote is not priced - client rule: blank unless known | $11,866 expiring |
| `Vehicle_TotalPremiumAmount_C` | a new-business quote is not priced - client rule: blank unless known | $11,866 expiring |
| `Vehicle_PrimaryLiabilityRatingFactor_D` | a new-business quote is not priced - client rule: blank unless known | $23,520 expiring |
| `Vehicle_NetRatingFactor_D` | a new-business quote is not priced - client rule: blank unless known | $23,520 expiring |
| `Vehicle_TotalPremiumAmount_D` | a new-business quote is not priced - client rule: blank unless known | $23,520 expiring |
| `Producer_AuthorizedRepresentative_Signature_A` | AUTHORSHIP - only the producer signs (the Sign button), never the fill |  |
| `NamedInsured_Signature_A` | AUTHORSHIP - the applicant signs |  |
| `NamedInsured_SignatureDate_A` | AUTHORSHIP - set when signed |  |

### ACORD_127 - not scored (grade by hand)

| box | value to look for | why |
|---|---|---|
| `Form_CompletionDate_A` |  | the generation date |
| `Producer_FullName_A` | Riverbend Insurance Partners, LLC | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_CustomerIdentifier_A` | CUMBHEA-01 | client: 'only if verified from agency/AMS' - Riverbend's AMS export prints it; Primble ... |
| `Vehicle_SymbolCode_A` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_ComprehensiveSymbolCode_A` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_CollisionSymbolCode_A` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_SymbolCode_B` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_ComprehensiveSymbolCode_B` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_CollisionSymbolCode_B` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_SymbolCode_C` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_ComprehensiveSymbolCode_C` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_CollisionSymbolCode_C` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_SymbolCode_D` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_ComprehensiveSymbolCode_D` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Vehicle_CollisionSymbolCode_D` |  | physical-damage RATING symbols vs covered-auto symbol 7 - owner decision (127 SYM colum... |
| `Producer_AuthorizedRepresentative_FullName_A` | Caroline Whitlock | resolved from the LOGGED-IN ACCOUNT by design, not from the uploaded documents - grade ... |
| `Producer_StateLicenseIdentifier_A` | 2204418 | client: 'state producer license: completed where applicable' - Primble's account profil... |
| `Producer_NationalIdentifier_A` | 19448210 | client: 'NPN: completed' - Primble's account profile has NO NPN field (audit gap); the ... |

### ACORD_127 - 286 boxes the documents never support (must stay blank)

`Driver_Coverage_BroadenedNoFaultCode_A`, `Driver_Coverage_DriverOtherCarCode_A`, `Driver_Coverage_BroadenedNoFaultCode_B`, `Driver_Coverage_DriverOtherCarCode_B`, `Driver_Coverage_BroadenedNoFaultCode_C`, `Driver_Coverage_DriverOtherCarCode_C`, `Driver_Coverage_BroadenedNoFaultCode_D`, `Driver_Coverage_DriverOtherCarCode_D`, `Driver_Vehicle_ProducerIdentifier_E`, `Driver_Vehicle_UsePercent_E`, `Driver_Coverage_BroadenedNoFaultCode_E`, `Driver_Coverage_DriverOtherCarCode_E`, `Driver_Coverage_BroadenedNoFaultCode_F`, `Driver_Coverage_DriverOtherCarCode_F`, `Driver_ProducerIdentifier_G`, `Driver_GivenName_G`, `Driver_OtherGivenNameInitial_G`, `Driver_Surname_G`, `Driver_MailingAddress_CityName_G`, `Driver_MailingAddress_StateOrProvinceCode_G`, `Driver_MailingAddress_PostalCode_G`, `Driver_GenderCode_G`, `Driver_MaritalStatusCode_G`, `Driver_BirthDate_G`, `Driver_ExperienceYearCount_G`, `Driver_LicensedYear_G`, `Driver_LicenseNumberIdentifier_G`, `Driver_LicensedStateOrProvinceCode_G`, `Driver_HiredDate_G`, `Driver_Vehicle_ProducerIdentifier_G`, `Driver_Vehicle_UsePercent_G`, `Driver_Coverage_BroadenedNoFaultCode_G`, `Driver_Coverage_DriverOtherCarCode_G`, `Driver_ProducerIdentifier_H`, `Driver_GivenName_H`, `Driver_OtherGivenNameInitial_H`, `Driver_Surname_H`, `Driver_MailingAddress_CityName_H`, `Driver_MailingAddress_StateOrProvinceCode_H`, `Driver_MailingAddress_PostalCode_H`, `Driver_GenderCode_H`, `Driver_MaritalStatusCode_H`, `Driver_BirthDate_H`, `Driver_ExperienceYearCount_H`, `Driver_LicensedYear_H`, `Driver_LicenseNumberIdentifier_H`, `Driver_LicensedStateOrProvinceCode_H`, `Driver_HiredDate_H`, `Driver_Vehicle_ProducerIdentifier_H`, `Driver_Vehicle_UsePercent_H`, `Driver_Coverage_BroadenedNoFaultCode_H`, `Driver_Coverage_DriverOtherCarCode_H`, `Driver_ProducerIdentifier_I`, `Driver_GivenName_I`, `Driver_OtherGivenNameInitial_I`, `Driver_Surname_I`, `Driver_MailingAddress_CityName_I`, `Driver_MailingAddress_StateOrProvinceCode_I`, `Driver_MailingAddress_PostalCode_I`, `Driver_GenderCode_I`, `Driver_MaritalStatusCode_I`, `Driver_BirthDate_I`, `Driver_ExperienceYearCount_I`, `Driver_LicensedYear_I`, `Driver_LicenseNumberIdentifier_I`, `Driver_LicensedStateOrProvinceCode_I`, `Driver_HiredDate_I`, `Driver_Vehicle_ProducerIdentifier_I`, `Driver_Vehicle_UsePercent_I`, `Driver_Coverage_BroadenedNoFaultCode_I`, `Driver_Coverage_DriverOtherCarCode_I`, `Driver_ProducerIdentifier_J`, `Driver_GivenName_J`, `Driver_OtherGivenNameInitial_J`, `Driver_Surname_J`, `Driver_MailingAddress_CityName_J`, `Driver_MailingAddress_StateOrProvinceCode_J`, `Driver_MailingAddress_PostalCode_J`, `Driver_GenderCode_J`, `Driver_MaritalStatusCode_J`, `Driver_BirthDate_J`, `Driver_ExperienceYearCount_J`, `Driver_LicensedYear_J`, `Driver_LicenseNumberIdentifier_J`, `Driver_LicensedStateOrProvinceCode_J`, `Driver_HiredDate_J`, `Driver_Vehicle_ProducerIdentifier_J`, `Driver_Vehicle_UsePercent_J`, `Driver_Coverage_BroadenedNoFaultCode_J`, `Driver_Coverage_DriverOtherCarCode_J`, `Driver_ProducerIdentifier_K`, `Driver_GivenName_K`, `Driver_OtherGivenNameInitial_K`, `Driver_Surname_K`, `Driver_MailingAddress_CityName_K`, `Driver_MailingAddress_StateOrProvinceCode_K`, `Driver_MailingAddress_PostalCode_K`, `Driver_GenderCode_K`, `Driver_MaritalStatusCode_K`, `Driver_BirthDate_K`, `Driver_ExperienceYearCount_K`, `Driver_LicensedYear_K`, `Driver_LicenseNumberIdentifier_K`, `Driver_LicensedStateOrProvinceCode_K`, `Driver_HiredDate_K`, `Driver_Vehicle_ProducerIdentifier_K`, `Driver_Vehicle_UsePercent_K`, `Driver_Coverage_BroadenedNoFaultCode_K`, `Driver_Coverage_DriverOtherCarCode_K`, `Driver_ProducerIdentifier_L`, `Driver_GivenName_L`, `Driver_OtherGivenNameInitial_L`, `Driver_Surname_L`, `Driver_MailingAddress_CityName_L`, `Driver_MailingAddress_StateOrProvinceCode_L`, `Driver_MailingAddress_PostalCode_L`, `Driver_GenderCode_L`, `Driver_MaritalStatusCode_L`, `Driver_BirthDate_L`, `Driver_ExperienceYearCount_L`, `Driver_LicensedYear_L`, `Driver_LicenseNumberIdentifier_L`, `Driver_LicensedStateOrProvinceCode_L`, `Driver_HiredDate_L`, `Driver_Vehicle_ProducerIdentifier_L`, `Driver_Vehicle_UsePercent_L`, `Driver_Coverage_BroadenedNoFaultCode_L`, `Driver_Coverage_DriverOtherCarCode_L`, `Driver_ProducerIdentifier_M`, `Driver_GivenName_M`, `Driver_OtherGivenNameInitial_M`, `Driver_Surname_M`, `Driver_MailingAddress_CityName_M`, `Driver_MailingAddress_StateOrProvinceCode_M`, `Driver_MailingAddress_PostalCode_M`, `Driver_GenderCode_M`, `Driver_MaritalStatusCode_M`, `Driver_BirthDate_M`, `Driver_ExperienceYearCount_M`, `Driver_LicensedYear_M`, `Driver_LicenseNumberIdentifier_M`, `Driver_LicensedStateOrProvinceCode_M`, `Driver_HiredDate_M`, `Driver_Vehicle_ProducerIdentifier_M`, `Driver_Vehicle_UsePercent_M`, `Driver_Coverage_BroadenedNoFaultCode_M`, `Driver_Coverage_DriverOtherCarCode_M`, `CommercialVehicleLineOfBusiness_Question_KAGCode_A`, `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_TrackFuelConsumptionIndicator_A`, `CommercialVehicleLineOfBusiness_ElectronicDataMonitoringDevice_NavigationIndicator_A`, `AdditionalInterest_Interest_AdditionalInsuredIndicator_A`, `AdditionalInterest_Interest_EmployeeAsLessorIndicator_A`, `AdditionalInterest_Interest_LendersLossPayableIndicator_A`, `AdditionalInterest_Interest_LossPayeeIndicator_A`, `AdditionalInterest_Interest_OwnerIndicator_A`, `AdditionalInterest_Interest_RegistrantIndicator_A`, `AdditionalInterest_Interest_OtherIndicator_A`, `AdditionalInterest_Interest_OtherDescription_A`, `AdditionalInterest_MailingAddress_LineTwo_A`, `AdditionalInterest_Item_LocationProducerIdentifier_A`, `AdditionalInterest_Interest_AdditionalInsuredIndicator_B`, `AdditionalInterest_Interest_EmployeeAsLessorIndicator_B`, `AdditionalInterest_Interest_LendersLossPayableIndicator_B`, `AdditionalInterest_Interest_LienholderIndicator_B`, `AdditionalInterest_Interest_OwnerIndicator_B`, `AdditionalInterest_Interest_RegistrantIndicator_B`, `AdditionalInterest_Interest_OtherIndicator_B`, `AdditionalInterest_Interest_OtherDescription_B`, `AdditionalInterest_Item_LocationProducerIdentifier_B`, `CommercialVehicleLineOfBusiness_RemarkText_B`, `Vehicle_SpecialIndustryClassCode_A`, `Vehicle_SeatingCapacityCount_A`, `Vehicle_FarthestZoneCode_A`, `Vehicle_VehicleType_PrivatePassengerIndicator_A`, `Vehicle_VehicleType_SpecialIndicator_A`, `Vehicle_Use_PleasureIndicator_A`, `Vehicle_Use_FarmIndicator_A`, `Vehicle_Use_RetailIndicator_A`, `Vehicle_Use_ServiceIndicator_A`, `Vehicle_Use_ForHireIndicator_A`, `Vehicle_Use_OtherIndicator_A`, `Vehicle_Use_OtherDescription_A`, `Vehicle_Coverage_NoFaultIndicator_A`, `Vehicle_Coverage_AdditionalNoFaultIndicator_A`, `Vehicle_Coverage_TowingAndLabourIndicator_A`, `Vehicle_Coverage_SpecifiedCauseOfLossIndicator_A`, `Vehicle_Coverage_FireIndicator_A`, `Vehicle_Coverage_FireTheftIndicator_A`, `Vehicle_Coverage_FireTheftWindstormIndicator_A`, `Vehicle_Coverage_LimitedSpecifiedPerilsIndicator_A`, `Vehicle_Coverage_FullGlassIndicator_A`, `Vehicle_Coverage_OtherIndicator_A`, `Vehicle_Coverage_ValuationAgreedAmountIndicator_A`, `Vehicle_Coverage_ValuationStatedAmountIndicator_A`, `Vehicle_Coverage_SpecifiedCauseOfLossDeductibleIndicator_A`, `Vehicle_Coverage_OtherDescription_A`, `Vehicle_Coverage_AgreedOrStatedAmount_A`, `Vehicle_Use_UnderFifteenMilesIndicator_A`, `Vehicle_Use_FifteenMilesOrOverIndicator_A`, `Vehicle_SpecialIndustryClassCode_B`, `Vehicle_SeatingCapacityCount_B`, `Vehicle_FarthestZoneCode_B`, `Vehicle_VehicleType_PrivatePassengerIndicator_B`, `Vehicle_VehicleType_SpecialIndicator_B`, `Vehicle_Use_PleasureIndicator_B`, `Vehicle_Use_FarmIndicator_B`, `Vehicle_Use_CommercialIndicator_B`, `Vehicle_Use_RetailIndicator_B`, `Vehicle_Use_ForHireIndicator_B`, `Vehicle_Use_OtherIndicator_B`, `Vehicle_Use_OtherDescription_B`, `Vehicle_Coverage_NoFaultIndicator_B`, `Vehicle_Coverage_AdditionalNoFaultIndicator_B`, `Vehicle_Coverage_SpecifiedCauseOfLossIndicator_B`, `Vehicle_Coverage_FireIndicator_B`, `Vehicle_Coverage_FireTheftIndicator_B`, `Vehicle_Coverage_FireTheftWindstormIndicator_B`, `Vehicle_Coverage_LimitedSpecifiedPerilsIndicator_B`, `Vehicle_Coverage_RentalReimbursementIndicator_B`, `Vehicle_Coverage_FullGlassIndicator_B`, `Vehicle_Coverage_OtherIndicator_B`, `Vehicle_Coverage_ValuationAgreedAmountIndicator_B`, `Vehicle_Coverage_ValuationStatedAmountIndicator_B`, `Vehicle_Coverage_SpecifiedCauseOfLossDeductibleIndicator_B`, `Vehicle_Coverage_OtherDescription_B`, `Vehicle_Coverage_AgreedOrStatedAmount_B`, `Vehicle_Use_UnderFifteenMilesIndicator_B`, `Vehicle_Use_FifteenMilesOrOverIndicator_B`, `Vehicle_SpecialIndustryClassCode_C`, `Vehicle_SeatingCapacityCount_C`, `Vehicle_FarthestZoneCode_C`, `Vehicle_VehicleType_PrivatePassengerIndicator_C`, `Vehicle_VehicleType_SpecialIndicator_C`, `Vehicle_Use_PleasureIndicator_C`, `Vehicle_Use_FarmIndicator_C`, `Vehicle_Use_CommercialIndicator_C`, `Vehicle_Use_RetailIndicator_C`, `Vehicle_Use_ForHireIndicator_C`, `Vehicle_Use_OtherIndicator_C`, `Vehicle_Use_OtherDescription_C`, `Vehicle_Coverage_NoFaultIndicator_C`, `Vehicle_Coverage_AdditionalNoFaultIndicator_C`, `Vehicle_Coverage_SpecifiedCauseOfLossIndicator_C`, `Vehicle_Coverage_FireIndicator_C`, `Vehicle_Coverage_FireTheftIndicator_C`, `Vehicle_Coverage_FireTheftWindstormIndicator_C`, `Vehicle_Coverage_LimitedSpecifiedPerilsIndicator_C`, `Vehicle_Coverage_RentalReimbursementIndicator_C`, `Vehicle_Coverage_FullGlassIndicator_C`, `Vehicle_Coverage_OtherIndicator_C`, `Vehicle_Coverage_ValuationAgreedAmountIndicator_C`, `Vehicle_Coverage_ValuationStatedAmountIndicator_C`, `Vehicle_Coverage_SpecifiedCauseOfLossDeductibleIndicator_C`, `Vehicle_Coverage_OtherDescription_C`, `Vehicle_Coverage_AgreedOrStatedAmount_C`, `Vehicle_Use_UnderFifteenMilesIndicator_C`, `Vehicle_Use_FifteenMilesOrOverIndicator_C`, `Vehicle_SpecialIndustryClassCode_D`, `Vehicle_SeatingCapacityCount_D`, `Vehicle_FarthestZoneCode_D`, `Vehicle_VehicleType_PrivatePassengerIndicator_D`, `Vehicle_VehicleType_SpecialIndicator_D`, `Vehicle_Use_PleasureIndicator_D`, `Vehicle_Use_FarmIndicator_D`, `Vehicle_Use_RetailIndicator_D`, `Vehicle_Use_ServiceIndicator_D`, `Vehicle_Use_ForHireIndicator_D`, `Vehicle_Use_OtherIndicator_D`, `Vehicle_Use_OtherDescription_D`, `Vehicle_Coverage_NoFaultIndicator_D`, `Vehicle_Coverage_AdditionalNoFaultIndicator_D`, `Vehicle_Coverage_TowingAndLabourIndicator_D`, `Vehicle_Coverage_SpecifiedCauseOfLossIndicator_D`, `Vehicle_Coverage_FireIndicator_D`, `Vehicle_Coverage_FireTheftIndicator_D`, `Vehicle_Coverage_FireTheftWindstormIndicator_D`, `Vehicle_Coverage_LimitedSpecifiedPerilsIndicator_D`, `Vehicle_Coverage_FullGlassIndicator_D`, `Vehicle_Coverage_OtherIndicator_D`, `Vehicle_Coverage_ValuationAgreedAmountIndicator_D`, `Vehicle_Coverage_ValuationStatedAmountIndicator_D`, `Vehicle_Coverage_SpecifiedCauseOfLossDeductibleIndicator_D`, `Vehicle_Coverage_OtherDescription_D`, `Vehicle_Coverage_AgreedOrStatedAmount_D`, `Vehicle_Use_UnderFifteenMilesIndicator_D`, `Vehicle_Use_FifteenMilesOrOverIndicator_D`

## Decoys - printed in the package, wrong only in the boxes named

| form | value | must not appear in | why |
|---|---|---|---|
| 125 | `Appalachian Risk Underwriters, LLC` | `Insurer_FullName_A` | the MGA administers - Ridgeline is the insurer |
| 125 | `Old Hickory Mutual Insurance Company` | `Insurer_FullName_A` | the CURRENT carrier, not the one receiving the submission |
| 125 | `27718` | `Insurer_NAICCode_A` | the current carrier's NAIC |
| 125 | `OHM-GL-4471902-25` | `Policy_PolicyNumberIdentifier_A` | an EXPIRING policy number on a new-business quote |
| 125 | `IMF-3318207` | `Policy_PolicyNumberIdentifier_A` | the existing inland marine policy (question 4), not this one |
| 125 | `CG 25 04 05 09` | `Policy_PolicyNumberIdentifier_A` | an ISO form number |
| 125 | `$38,420` | `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | the expiring GL premium |
| 125 | `$61,775` | `CommercialVehicleLineOfBusiness_PremiumAmount_A` | the expiring auto premium |
| 125 | `$138,015` | `Policy_Payment_EstimatedTotalAmount_A` | the expiring programme total |
| 125 | `$107,090` | `Policy_Payment_EstimatedTotalAmount_A` | the INCUMBENT's renewal quotation (not accepted) |
| 125 | `$40,880` | `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | the incumbent's renewal GL premium |
| 125 | `$66,210` | `CommercialVehicleLineOfBusiness_PremiumAmount_A` | the incumbent's renewal auto premium |
| 125 | `$2,500` | `Policy_Payment_MinimumPremiumAmount_A` | the PROGRAM's minimum - not this policy's |
| 125 | `$9,605` | `Policy_Payment_MinimumPremiumAmount_A` | the incumbent GL policy's minimum premium |
| 125 | `12/01/2025` | `Policy_EffectiveDate_A` | the CURRENT term's start |
| 125 | `11/15/2026` | `Policy_EffectiveDate_A` | the August worksheet's date - superseded on 09/24 |
| 125 | `Agency bill - 10 installments` | `Policy_PaymentMethod_MethodDescription_A` | the expiring billing |
| 125 | `CUMB-0044` | `Producer_CustomerIdentifier_A` | the PRIOR agency's customer id |
| 125 | `VSA-2291` | `Insurer_ProducerIdentifier_A` | the PRIOR agency's code with the incumbent |
| 125 | `www.oldhickorymutual-example.com` | `NamedInsured_Primary_WebsiteAddress_*` | the incumbent carrier's website |
| 125 | `1-800-555-0198` | `NamedInsured_Primary_PhoneNumber_*` | the incumbent carrier's service line |
| 125 | `615-555-0149` | `NamedInsured_Primary_PhoneNumber_A` | the applicant's FAX line |
| 125 | `615-555-0410` | `NamedInsured_Primary_PhoneNumber_*` | the agency's phone |
| 125 | `000817423` | `NamedInsured_TaxIdentifier_*` | a 9-digit Secretary of State control number |
| 125 | `07-881-4420` | `NamedInsured_TaxIdentifier_*` | a 9-digit D-U-N-S number |
| 125 | `3217744` | `NamedInsured_TaxIdentifier_*` | a USDOT number |
| 125 | `85-1047712` | `NamedInsured_TaxIdentifier_*` | the joint venture's FEIN |
| 125 | `68706` | `NamedInsured_GeneralLiabilityCode_A` | a non-governing GL class |
| 125 | `12683` | `NamedInsured_NAICSCode_*` | a GL class code in the NAICS box |
| 125 | `Cumberland Restaurant Supply, LLC` | `NamedInsured_FullName_*` | the FORMER name - the LLC converted in 2022 |
| 125 | `Music Row Kitchen Rentals, LLC` | `NamedInsured_FullName_*` | the joint venture - coverage not requested |
| 125 | `Margaret A. Ellison Revocable Trust` | `NamedInsured_FullName_*` | a shareholder, not an insured |
| 125 | `Margaret A. Ellison Revocable Trust` | `BusinessInformation_ParentOrganizationName_A` | a 60% shareholder's trust is not a parent company |
| 125 | `Margaret A. Ellison Revocable Trust` | `AdditionalInterest_FullName_B` | question 11 is NO - the shareholder's trust is not the business placed in trust |
| 125 | `Brightline Flex Properties, LP` | `NamedInsured_FullName_*` | the location 2 landlord |
| 125 | `Music Row Kitchen Rentals, LLC` | `Subsidiary_OrganizationName_A` | a 40% minority interest is not a subsidiary |
| 125 | `$18,600,000` | `CommercialStructure_AnnualRevenueAmount_*` | the COMPANY total - each premises carries its own |
| 125 | `$21,100,000` | `CommercialStructure_AnnualRevenueAmount_*` | the PROJECTED 2027 revenue |
| 125 | `$4,312,600` | `CommercialStructure_AnnualRevenueAmount_*` | the order backlog |
| 125 | `$4,918,300` | `CommercialStructure_AnnualRevenueAmount_*` | payroll is not revenue |
| 125 | `73` | `BusinessInformation_FullTimeEmployeeCount_*` | total headcount, full and part time |
| 125 | `9` | `BusinessInformation_PartTimeEmployeeCount_*` | agency temps are not employees |
| 125 | `3,400` | `BuildingOccupancy_OccupiedArea_C` | corrected by the lease amendment |
| 125 | `95%` | `CommercialStructure_InstallationRepairWorkOffPremisesPercent_A` | share of SERVICE CALLS at customer sites - not of total sales |
| 125 | `615-555-0109` | `NamedInsured_Contact_*PhoneNumber_*` | a typo corrected in the CFO's e-mail |
| 125 | `615-555-0161` | `NamedInsured_Contact_*PhoneNumber_*` | the CFO is not a listed contact |
| 125 | `$2,100` | `LossHistory_PaidAmount_*` | the 12/31/2025 valuation |
| 125 | `$5,800` | `LossHistory_ReservedAmount_*` | the 12/31/2025 valuation |
| 125 | `$5,950` | `LossHistory_PaidAmount_*` | the agency summary of 08/04/2026 - stale |
| 125 | `$2,000` | `LossHistory_ReservedAmount_*` | the agency summary of 08/04/2026 - stale |
| 125 | `$53,667` | `LossHistory_TotalAmount_A` | paid + reserved is INCURRED |
| 125 | `$38,400` | `LossHistory_PaidAmount_*` | the hail claim as of 10/2024 - it closed at $41,980 |
| 125 | `$12,900,000` | `CommercialStructure_AnnualRevenueAmount_*` | the SUPERSEDED 2024 application's figure |
| 125 | `$2,684,512` | `AdditionalInterest_LoanAmount_A` | the current balance - the loan amount is $3,150,000 |
| 125 | `$6,900,000` | `AdditionalInterest_LoanAmount_A` | the building value |
| 125 | `Brightline Flex Properties, LP` | `AdditionalInterest_FullName_A` | the GL additional insured belongs on the 126 |
| 125 | `Volunteer Truck Finance, LLC` | `AdditionalInterest_FullName_A` | a vehicle lienholder belongs on the 127 |
| 125 | `OHM-GL-4471902-22` | `PriorCoverage_*` | a FOURTH year - the grid holds three |
| 125 | `OHM-CA-4471903-22` | `PriorCoverage_*` | a FOURTH year - the grid holds three |
| 125 | `Tennessee Employers Mutual` | `PriorCoverage_OtherLine_InsurerFullName_*` | workers compensation is not part of this programme's grid |
| 126 | `Old Hickory Mutual Insurance Company` | `Insurer_FullName_A` | the current carrier |
| 126 | `27718` | `Insurer_NAICCode_A` | the current carrier's NAIC |
| 126 | `OHM-GL-4471902-25` | `Policy_PolicyNumberIdentifier_A` | the EXPIRING GL policy number |
| 126 | `12/01/2025` | `Policy_EffectiveDate_A` | the current term's start |
| 126 | `$100,000` | `GeneralLiability_FireDamageRentedPremises_EachOccurrenceLimitAmount_A` | the EXPIRING limit - $300,000 is requested |
| 126 | `$5,000` | `GeneralLiability_MedicalExpense_EachPersonLimitAmount_A` | the EXPIRING limit - $10,000 is requested |
| 126 | `$5,000,000` | `GeneralLiability_*LimitAmount_A` | the umbrella limit |
| 126 | `$13,700,000` | `GeneralLiability_Hazard_Exposure_*` | the EXPIRING exposure - the proposed estimate is $14,950,000 |
| 126 | `$1,190,000` | `GeneralLiability_Hazard_Exposure_*` | the EXPIRING payroll - the proposed estimate is $1,284,600 |
| 126 | `$13,210,500` | `GeneralLiability_Hazard_Exposure_*` | the AUDITED 2024-25 sales |
| 126 | `$1,122,400` | `GeneralLiability_Hazard_Exposure_*` | the AUDITED 2024-25 payroll |
| 126 | `10150` | `GeneralLiability_Hazard_ClassCode_*` | the DELETED Visco Drive retail class |
| 126 | `$25,235` | `GeneralLiability_Hazard_*PremiumAmount_*` | an expiring class premium |
| 126 | `1.842` | `GeneralLiability_Hazard_*Rate_*` | an expiring rate |
| 126 | `$38,420` | `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | the expiring GL premium |
| 126 | `12683` | `ProductAndCompletedOperations_ProductName_*` | a GL rating class is not a product |
| 126 | `Kitchen and Restaurant Equipment Distributors - commercial` | `ProductAndCompletedOperations_ProductName_*` | a rating classification is not a product |
| 126 | `Volunteer Grill` | `ProductAndCompletedOperations_ProductName_*` | a DISCONTINUED line |
| 126 | `Harpeth Staffing Solutions, Inc.` | `AdditionalInterest_FullName_*` | temporary workers from a staffing firm are not leased employees |
| 126 | `73` | `Contractors_FullTimeEmployeeCount_A` | total headcount, full and part time |
| 126 | `9` | `Contractors_PartTimeEmployeeCount_A` | agency temps are not employees |
| 126 | `03/01/2015` | `GeneralLiability_ClaimsMade_*` | the E&O policy's retro date - GL is occurrence |
| 126 | `03/01/2015` | `GeneralLiability_EmployeeBenefits_RetroactiveDate_A` | the E&O retro date - EBL retro is 12/01/2019 |
| 126 | `Pinnacle Commerce Bank, N.A.` | `AdditionalInterest_FullName_A` | the property mortgagee is not a GL additional insured |
| 127 | `Old Hickory Mutual Insurance Company` | `Insurer_FullName_A` | the current carrier |
| 127 | `OHM-CA-4471903-25` | `Policy_PolicyNumberIdentifier_A` | the EXPIRING auto policy number |
| 127 | `12/01/2025` | `Policy_EffectiveDate_A` | the current term's start |
| 127 | `$1,000` | `Vehicle_Collision_DeductibleAmount_D` | the EXPIRING deductible - $2,500 is requested |
| 127 | `$14,982` | `Vehicle_TotalPremiumAmount_*` | an expiring vehicle premium |
| 127 | `$23,520` | `Vehicle_TotalPremiumAmount_*` | an expiring vehicle premium |
| 127 | `$61,300` | `Vehicle_CostNewAmount_*` | the current ACV, not cost new |
| 127 | `$103,750` | `Vehicle_CostNewAmount_*` | the current ACV, not cost new |
| 127 | `1FDWE3FL4HDC22016` | `Vehicle_VINIdentifier_*` | SOLD 05/22/2026 by endorsement 2 |
| 127 | `1GCWGFCF5F1144028` | `Vehicle_VINIdentifier_*` | the 2015 Chevrolet Express - SOLD 08/2025 |
| 127 | `126633019` | `Driver_LicenseNumberIdentifier_*` | a driver TERMINATED 08/29/2026 |
| 127 | `Ambrose` | `Driver_Surname_*` | a driver TERMINATED 08/29/2026 |
| 127 | `Ellison` | `Driver_Surname_*` | the owner is a Drive Other Car named individual, not a driver |
| 127 | `Lindqvist` | `Driver_Surname_*` | the CFO drives his own car - not a listed driver |
| 127 | `4471` | `Driver_TaxIdentifier_*` | masked SSN fragments never print |
| 127 | `09/02/2019` | `AccidentConviction_TrafficViolationDate_A` | outside the three-year look-back |
| 127 | `3217744` | `*` | a USDOT number is not on the 127 |
| 127 | `Pinnacle Commerce Bank, N.A.` | `AdditionalInterest_FullName_*` | the building mortgagee is not a vehicle interest |

## Deliberately never stated

- a policy number, premium, deposit or minimum premium for the policy being QUOTED
- an answer to 125 question 7 (fraud / bribery / arson) or question 9 (foreclosure, repossession, bankruptcy) - the insured never answered them; the package mentions a CUSTOMER's bankruptcy and a repossession BY the applicant, which answer nothing
- an answer to 126 recreation facilities, lodging, swimming pool, day care and promotional-literature questions, and 127 'all vehicles part of a fleet'
- a premium for the 2023-24 property term (the Volunteer Fire & Marine loss run prints none)
- an umbrella before 12/01/2024 (the first umbrella incepted then)
- a resolution block for question 8 - the 02/11/2026 citation was CORRECTED, so 8 is No
- any claim older than five years in the loss history
- a producer NPN / state licence from the account (the account profile has no such field)
