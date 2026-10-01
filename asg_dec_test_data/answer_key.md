# Answer key - Harborline 10-page dec package (fictional test data)

| Page | Fact | Expected value | ACORD 125 field | Note |
|---|---|---|---|---|
| 1 | Carrier | Granite Peak Casualty Company | Insurer_FullName_A |  |
| 1 | Carrier NAIC | 99887 | Insurer_NAICCode_A |  |
| 1 | Program name | Contractors Advantage Program | Insurer_ProductDescription_A |  |
| 1 | Program code | CAP-27 | Insurer_ProductCode_A |  |
| 1 | Underwriter | Marisol Vance | Insurer_Underwriter_FullName_A |  |
| 1 | Underwriter office | SEA-02 (Seattle Regional) | Insurer_Underwriter_OfficeIdentifier_A |  |
| 1 | Producer | Northsound Insurance Brokers LLC | Producer_FullName_A |  |
| 1 | Producer contact | Renee Castillo | Producer_ContactPerson_FullName_A |  |
| 1 | Producer phone | (253) 555-0100 | Producer_ContactPerson_PhoneNumber_A |  |
| 1 | Producer fax | (253) 555-0101 | Producer_FaxNumber_A |  |
| 1 | Producer email | rcastillo@northsound-ins.example.com | Producer_ContactPerson_EmailAddress_A |  |
| 1 | Agency code | 44-1187 | Insurer_ProducerIdentifier_A |  |
| 1 | Sub code | 07 | Insurer_SubProducerIdentifier_A |  |
| 1 | Named insured | Harborline Plumbing & Mechanical, LLC | NamedInsured_FullName_A | DBA Harborline Mechanical also printed |
| 1 | FEIN | 91-4478123 | NamedInsured_TaxIdentifier_A |  |
| 1 | SIC | 1711 | NamedInsured_SICCode_A |  |
| 1 | NAICS | 238220 | NamedInsured_NAICSCode_A |  |
| 1 | Business phone | (253) 555-0142 | NamedInsured_Primary_PhoneNumber_A |  |
| 1 | Website | www.harborline-mech.example.com | NamedInsured_Primary_WebsiteAddress_A |  |
| 1 | Entity type | LLC | NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A |  |
| 1 | Members/managers | 2 | NamedInsured_LegalEntity_MemberManagerCount_A |  |
| 1 | Current term effective | 10/15/2025 |  | printed in 3 formats |
| 1 | Current term expiration | 10/15/2026 |  |  |
| 1 | Proposed effective (next term) | 10/15/2026 | Policy_EffectiveDate_A | renewal: next term |
| 1 | Proposed expiration | 10/15/2027 | Policy_ExpirationDate_A |  |
| 1 | Transaction | Renewal | Policy_Status_RenewIndicator_A |  |
| 1 | LOB: GL / Auto / Property / Umbrella | ticked | Policy_LineOfBusiness_* indicators |  |
| 1 | GL premium | 38,640 | GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A |  |
| 1 | Property premium | 14,980 | CommercialPropertyLineOfBusiness_PremiumAmount_A |  |
| 1 | Auto premium | 26,310 | CommercialVehicleLineOfBusiness_PremiumAmount_A |  |
| 1 | Umbrella premium | 9,450 | CommercialUmbrellaLineOfBusiness_PremiumAmount_A |  |
| 1 | Policy premium total | 89,380 | Policy_Payment_EstimatedTotalAmount_A | IM $3,275 excluded - separate policy, not in submission |
| 1 | Billing plan | Direct | Policy_Payment_DirectBillIndicator_A |  |
| 1 | Payment plan | Quarterly | Policy_Payment_PaymentScheduleCode_A |  |
| 1 | Method of payment | ACH / EFT | Policy_PaymentMethod_MethodDescription_A |  |
| 1 | Deposit | 22,345 | Policy_Payment_DepositAmount_A |  |
| 1 | Minimum premium | 1,000 | Policy_Payment_MinimumPremiumAmount_A |  |
| 1 | Audit | Annual | Policy_Audit_FrequencyCode_A |  |
| 2 | Subcontracted cost | 310,000 |  | for ACORD 126 |
| 2 | GL each occurrence | 1,000,000 |  |  |
| 2 | GL general aggregate | 2,000,000 |  |  |
| 2 | GL products/completed ops aggregate | 2,000,000 |  |  |
| 2 | Personal & advertising injury | 1,000,000 |  | printed as $1M |
| 2 | Damage to rented premises | 300,000 |  |  |
| 2 | Medical expense | 10,000 |  |  |
| 2 | GL deductible | 2,500 per claim BI/PD |  |  |
| 2 | GL code (primary) | 98483 | NamedInsured_GeneralLiabilityCode_A |  |
| 2 | GL class 98483 payroll | 1,860,000 |  |  |
| 2 | GL class 98482 payroll | 420,000 |  |  |
| 2 | GL class 68707 area | 4,000 sq ft |  |  |
| 2 | GL class 61217 area | 2,400 sq ft |  |  |
| 2 | Stop Gap EL limits | 1,000,000 / 1,000,000 / 1,000,000 |  |  |
| 3 | Hired auto cost of hire | 12,000 |  | for ACORD 127/137 |
| 3 | Vehicle schedule attached | Yes (6 owned vehicles) | Policy_SectionAttached_VehicleScheduleIndicator_A |  |
| 3 | Driver schedule attached | Yes (6 drivers) | Policy_SectionAttached_DriverInformationScheduleIndicator_A |  |
| 3 | Auto CSL | 1,000,000 |  |  |
| 3 | Auto symbols | Liab 1; UM 2; Med 2; Comp/Coll 7; Hired 8; Non-owned 9 |  |  |
| 3 | Vehicle 1 VIN / cost new | 1FTBR2C85PKA10427 / 52,400 |  | for ACORD 127 |
| 3 | Vehicle 2 VIN / cost new | 1FTBR2C84NKA38815 / $49,900 |  | for ACORD 127 |
| 3 | Vehicle 3 VIN / cost new | 1GC4YLE71MF211903 / 57,300.00 |  | for ACORD 127 |
| 3 | Vehicle 4 VIN / cost new | 3C6LRVDG5RE104462 / 54,150 |  | for ACORD 127 |
| 3 | Vehicle 5 VIN / cost new | 54DC4W1B8KS801244 / 71,800 |  | for ACORD 127 |
| 3 | Vehicle 6 VIN / cost new | 1FDUF5HT3LDA22917 / 96,500 |  | for ACORD 127 |
| 4 | Loc 1 / 2 / 3 roof year | 2016 / 2012 / 2019 |  | for ACORD 140 |
| 4 | Loc 1 construction / year / sq ft | Joisted masonry / 1978 / 18,000 (bldg) | Construction_BuildingArea_A | total building area 18,000 |
| 4 | Loc 2 construction / year / sq ft | Non-combustible / 1996 / 4,000 | Construction_BuildingArea_B |  |
| 4 | Loc 3 construction / year / sq ft | Frame / 1954 / 2,400 | Construction_BuildingArea_C |  |
| 4 | Loc 2 building limit | 1,150,000 |  |  |
| 4 | Loc 3 building limit | 620,000 |  |  |
| 4 | Loc 1 BPP | 380,000 |  |  |
| 4 | Mortgagee name | Cascadia Community Bank | AdditionalInterest_FullName_A |  |
| 4 | Mortgagee address | 950 Pacific Ave, Tacoma WA 98402 | AdditionalInterest_MailingAddress_*_A |  |
| 4 | Mortgagee loan # | CCB-77-40981 | AdditionalInterest_AccountNumberIdentifier_A |  |
| 4 | Mortgagee loan amount | 780,000 | AdditionalInterest_LoanAmount_A |  |
| 4 | Mortgagee interest end | 11/30/2033 | AdditionalInterest_InterestEndDate_A |  |
| 4 | Mortgagee phone | (253) 555-0300 | AdditionalInterest_Primary_PhoneNumber_A |  |
| 4 | Mortgagee email | loans@cascadiacb.example.com | AdditionalInterest_Primary_EmailAddress_A |  |
| 4 | Mortgagee applies to | Location 2, Building 1 | AdditionalInterest_Item_LocationProducerIdentifier_A |  |
| 4 | Loc 3 area leased to others | Y | CommercialStructure_Question_ABBCode_C |  |
| 5 | Umbrella limit | 5,000,000 each occurrence / aggregate |  |  |
| 5 | Umbrella SIR | 10,000 |  |  |
| 5 | Workers comp | WA state fund (L&I) - no private WC policy |  |  |
| 5 | Drones | N / N | CommercialPolicy_Question_KANCode_A / KAOCode_A |  |
| 6 | Other named insured | Harborline Equipment Holdings LLC | NamedInsured_FullName_B |  |
| 6 | ONI FEIN | 91-4478124 | NamedInsured_TaxIdentifier_B |  |
| 6 | ONI SIC / NAICS / GL | 7359 / 532412 / 97111 | NamedInsured_SICCode_B / NAICSCode_B / GeneralLiabilityCode_B |  |
| 6 | ONI address | 2210 Port of Tacoma Rd Ste 4C, Tacoma WA 98421 | NamedInsured_MailingAddress_*_B |  |
| 6 | ONI phone | (253) 555-0143 | NamedInsured_Primary_PhoneNumber_B |  |
| 6 | ONI entity / members | LLC / 1 | NamedInsured_LegalEntity_*_B |  |
| 6 | Contact A type / name | Inspection / Dale Okafor | NamedInsured_Contact_ContactDescription_A / FullName_A |  |
| 6 | Contact A primary phone | (253) 555-0187 cell | NamedInsured_Contact_PrimaryPhoneNumber_A + PrimaryCellPhoneIndicator_A |  |
| 6 | Contact A secondary phone | (253) 555-0142 business | NamedInsured_Contact_SecondaryPhoneNumber_A |  |
| 6 | Contact A emails | dokafor@... / field@... | NamedInsured_Contact_PrimaryEmailAddress_A / SecondaryEmailAddress_A |  |
| 6 | Contact B type / name | Accounting / Priya Raman | NamedInsured_Contact_ContactDescription_B / FullName_B |  |
| 6 | Contact B primary phone | (253) 555-0150 business | NamedInsured_Contact_PrimaryPhoneNumber_B |  |
| 6 | Contact B secondary phone | (253) 555-0151 cell | NamedInsured_Contact_SecondaryPhoneNumber_B |  |
| 6 | Contact B emails | ap@... / praman@... | NamedInsured_Contact_PrimaryEmailAddress_B / SecondaryEmailAddress_B |  |
| 6 | Parent company | Harborline Group, Inc. - 75% | BusinessInformation_ParentOrganizationName_A / Subsidiary_ParentOwnershipPercent_A |  |
| 6 | Subsidiary | Harborline Equipment Holdings LLC - 100% | Subsidiary_OrganizationName_A / Subsidiary_ParentOwnershipPercent_B |  |
| 6 | Q4 other insurance with this company | Y - Inland Marine IM-3301877-02 | CommercialPolicy_Question_AAHCode_A / OtherPolicy_*_A |  |
| 6 | Q13 other business ventures | Y - Sound Backflow Testing LLC | CommercialPolicy_Question_KAMCode_A |  |
| 7 | Loss history years | 5 | LossHistory_InformationYearCount_A |  |
| 7 | Total losses | 32,030 paid (38,030 incurred) | LossHistory_TotalAmount_A | ambiguous by design |
| 7 | Loss A | 02/11/2026 GL, claim 02/13/2026, paid 18,750, reserve 6,000, subro Y, open Y | LossHistory_*_A |  |
| 7 | Loss B | 07/22/2025 Auto, claim 07/23/2025, paid 3,420, reserve 0, subro N, open N | LossHistory_*_B |  |
| 7 | Loss C | 12/03/2024 Property, claim 12/04/2024, paid 9,860, reserve 0, subro N, open N | LossHistory_*_C |  |
| 7 | Loss D (4th claim - beyond 3 rows) | 05/16/2022 GL Olympic Mutual, denied, 0 |  | belongs on loss summary / ACORD 101 |
| 7 | Q6 abuse / discrimination / negligent hiring | N | CommercialPolicy_Question_AADCode_A |  |
| 8 | Replaced vehicle (sold) | 2016 Ford Transit VIN 1FTYR2CM6GKA90312 - must NOT appear in schedule |  | TRAP |
| 8 | Mailing address (current, after endorsement) | PO Box 11820, Tacoma, WA 98411-0820 | NamedInsured_MailingAddress_*_A | TRAP: page 1 shows the old street address |
| 8 | Prior carrier year 1 (2025) | Granite Peak: GL CPP-4418820-03 38,640 / Auto BA-4418821-03 26,310 / Prop CPP-4418820-03 14,980 / Umb UMB-7720145-03 9,450; 10/15/2025-10/15/2026 | PriorCoverage_*_A |  |
| 8 | Prior carrier year 2 (2024) | Granite Peak -02 numbers: 36,120 / 24,880 / 14,210 / 8,900; 10/15/2024-10/15/2025 | PriorCoverage_*_B |  |
| 8 | Prior carrier year 3 (2023) | Granite Peak -01 numbers: 33,870 / 23,400 / 13,560 / 8,300; 10/15/2023-10/15/2024 | PriorCoverage_*_C | 2022-23 Olympic Mutual is a 4th year - no room on 125 |
| 8 | Q5 declined/cancelled/non-renewed | Y - Non-renewal (Olympic Mutual, 10/15/2023, carrier exited class) | CommercialPolicy_Question_AACCode_A + CancelNonRenew_NonRenewalIndicator_A |  |
| 8 | Q7 fraud/arson | N | CommercialPolicy_Question_KABCode_A |  |
| 8 | Q8 fire/safety violations | N | CommercialPolicy_Question_AAFCode_A |  |
| 8 | Q9 foreclosure/bankruptcy | N | CommercialPolicy_Question_KAKCode_A |  |
| 8 | Q10 judgement/lien | Y - 06/12/2024 Rainier Pipe Supply lien, resolved 09/30/2024 (paid, released) | CommercialPolicy_Question_KALCode_A + JudgementOrLien_*_A |  |
| 9 | Q1a subsidiary of another entity | Y - Harborline Group, Inc., 75% | CommercialPolicy_Question_AAICode_A | scanned + handwritten |
| 9 | Q1b has subsidiaries | Y - Harborline Equipment Holdings LLC, 100% | CommercialPolicy_Question_AAJCode_A | scanned + handwritten |
| 9 | Q2 safety program | Y - manual, safety position, monthly meetings, OSHA | CommercialPolicy_Question_KAACode_A + FormalSafetyProgram_* | scanned + handwritten |
| 9 | Q3 flammables | Y - propane cylinders + pipe cement/primer in flammables cabinet | CommercialPolicy_Question_ABCCode_A | scanned + handwritten |
| 9 | Q11 trust | N | CommercialPolicy_Question_ABBCode_A | scanned + handwritten |
| 9 | Q12 foreign operations | N | CommercialPolicy_Question_KACCode_A | scanned + handwritten |
| 9 | Q14/Q15 drones | N / N | CommercialPolicy_Question_KANCode_A / KAOCode_A | scanned + handwritten |
| 9 | Business start date | 03/01/2011 | NamedInsured_BusinessStartDate_A | scanned + handwritten |
| 9 | Installation/service/repair % | 100% | CommercialStructure_InstallationRepairWorkPercent_A | scanned + handwritten |
| 9 | Off-premises % | 95% | CommercialStructure_InstallationRepairWorkOffPremisesPercent_A | scanned + handwritten |
| 10 | Premises A | 2210 Port of Tacoma Rd Ste 4B, Tacoma, Pierce, WA 98421; Inside; Tenant; 22; 2; 5,400,000; 6,500; 400; 18,000; N | CommercialStructure_PhysicalAddress_*_A, city limits, interest, BusinessInformation_Full/PartTimeEmployeeCount_A, CommercialStructure_AnnualRevenueAmount_A, BuildingOccupancy_OccupiedArea_A, OpenToPublicArea_A, Construction_BuildingArea_A, Question_ABBCode_A |  |
| 10 | Premises B | 8801 Canyon Rd E, Puyallup, Pierce, WA 98371; Outside; Owner; 6; 1; 1,250,000; 4,000; 0; 4,000; N | CommercialStructure_PhysicalAddress_*_B, city limits, interest, BusinessInformation_Full/PartTimeEmployeeCount_B, CommercialStructure_AnnualRevenueAmount_B, BuildingOccupancy_OccupiedArea_B, OpenToPublicArea_B, Construction_BuildingArea_B, Question_ABBCode_B |  |
| 10 | Premises C | 305 W Main St, Auburn, King, WA 98001; Inside; Owner; 0; 0; 0; 1,200; 0; 2,400; Y | CommercialStructure_PhysicalAddress_*_C, city limits, interest, BusinessInformation_Full/PartTimeEmployeeCount_C, CommercialStructure_AnnualRevenueAmount_C, BuildingOccupancy_OccupiedArea_C, OpenToPublicArea_C, Construction_BuildingArea_C, Question_ABBCode_C |  |
| 10 | Nature of business | Contractor | BusinessInformation_BusinessType_ContractorIndicator_A |  |
| 10 | Description of primary operations | Plumbing, hydronic heating & HVAC install/service/repair, commercial & residential | CommercialPolicy_OperationsDescription_A |  |
| 10 | Description of other named insured ops | Equipment Holdings owns vehicles/equipment, leases only to applicant | CommercialPolicy_OperationsDescription_B |  |
| 10 | Status of transaction | Quote (renewal) | Policy_Status_QuoteIndicator_A / RenewIndicator_A | document says renewal AND requests a quote |
| 10 | Umbrella requested limit | 5,000,000 |  |  |
