# ROUND 2 - TEST 3 (as run) RESULTS - 28 Sep 2026

Kit: **FR125 v2 - the client's case at data-map density**. Session `4c734a06-601d-43c7-b97e-a0d1b0cf5753`. ACORD 125 only, no human edits. Graded against the answer key by `score_form_fill.py` (meaning-aware since 28 Sep), and against the documents alone by `audit_125_rules.py`.

## The four numbers

| | boxes | |
|---|---|---|
| **Correct** | **220** of 312 | 216 exact, 0 code written as its word, 4 by meaning |
| **Wrong** | **48** | 2 of them partial - right but incomplete |
| **In the documents, missing from the form** | **44** | 0 printed only on a scanned page; by pass: 3 call2, 34 owned_blank, 7 pass1 |
| **Made-up values** - a value where the documents state nothing | **8** | |
| Wrong-role values - a trap value in its trap box | 3 | a real value, the wrong party or term |
| A rule says blank, and it was filled | 1 | |
| A row with no entity, and it was filled | 0 | |

**Accuracy of what it filled: 220 / 268 = 82.1%.**  
**Coverage of what it should fill: 220 / 312 = 70.5%.**

## Scorecard (round 1 format)

| | boxes |
|---|---|
| Must carry a value | 312 |
| &nbsp;&nbsp;correct | **220** |
| &nbsp;&nbsp;wrong value | **48** |
| &nbsp;&nbsp;missing (blank, should be filled) | **44** |
| Must stay empty | 220 |
| &nbsp;&nbsp;violated - a value appeared | **9** |
| **Fabricated** (scoped decoy landed) | **3** |
| Wrong shape (FEIN / ZIP / code format) | 0 |
| Overflow leak (a no-slot row displacing a real one) | 0 |
| Not scored | 16 |

## Row-cell

| group | cells due | correct | cross-row | orphan |
|---|---|---|---|---|
| named_insureds | 15 | 14 | 0 | 0 |
| premises | 32 | 32 | 0 | 0 |
| contacts | 8 | 8 | 0 | 0 |
| losses | 15 | 14 | 0 | 1 |
| prior_coverage | 24 | 21 | 0 | 0 |

## Extraction (LLM call 1) - read before the form

ENTITY-CELL **81/82 = 98.8%**; scalars 16 correct / 0 wrong / 0 missing; nothing invented.

<details><summary>extraction detail</summary>

```
==========================================================================
LLM CALL 1 vs the supplied key
==========================================================================

SCALARS
  -> 16 correct / 0 wrong / 0 missing

LISTS
  fact                                rows   cells  right  cross  blank
  applicant_contacts             2/2             6      6      0      0
  property_locations             4/4            28     28      0      0  (+4 unexpected)
  named_insured_details          2/2            10     10      0      0
  organization_relationships     2/2             4      4      0      0
  disclosure_answers             15/16           16     15      0      1
  safety_program_elements        4/4             0      0      0      0
  loss_history                   3/3            12     12      0      0
  additional_interests           2/2             6      6      0      0

  ENTITY-CELL  81/82 = 98.8%   cross-entity 0   blank 1

RELATIONSHIP CHECKS (no answer key - these run on any package)
  clean

HOW TO READ THIS
  ENTITY-CELL is the number to steer by. A high scalar score with a low
  entity-cell score means extraction is FINDING the values and attaching
  them to the wrong parties - which no form-level metric can see.
```
</details>

## Rules audit - no answer key, the form against the documents

| rule | status | |
|---|---|---|
| C1 Status is QUOTE, and only QUOTE | FAIL | 2 |
| C2 Page-one carrier is the carrier RECEIVING the submission | NOT EXERCISED |  |
| C3 NAIC only if verified for THAT carrier | PASS |  |
| C4 Policy number blank on a new-business quote | NOT EXERCISED |  |
| C5 Premium blank at submission stage unless known | NOT EXERCISED |  |
| C6 Proposed dates are the NEXT term, not the current one | PASS |  |
| C7 Prior carrier: only what the documents substantiate | PASS |  |
| C8 'No known losses' is never converted into loss history | PASS |  |
| C9 Loss total is the PAID amount of the losses (ACORD tooltip) | PASS |  |
| C10 Blank is not No - unanswered questions stay UNRESOLVED | PASS |  |
| C11 A Yes carries its explanation / detail | PASS |  |
| C12 A No (or blank) leaves its whole block empty | PASS |  |
| C13 Other named insureds only if the documents support them | PASS |  |
| C14 Additional interest only if actually documented as one | PASS |  |
| C15 Form edition is the current one (2025/03) | PASS |  |
| C16 Every Yes / No answer has its own sentence in the documents | REVIEW | 1 |
| C17 An ATTACHMENTS tick names a form this package contains | PASS |  |
| S1 No placeholder ever reaches a box ('N/A', '--', 'none', 'TBD') | PASS |  |
| S2 Authorship: nothing signs or attests for a person | PASS |  |
| S3 Every code box holds the shape its ACORD tooltip declares | PASS |  |
| S4 Every printed value is found in the documents (made-up detector) | PASS |  |
| S5 No entity printed twice in one table | PASS |  |
| S6 Premises areas add up: public <= occupied <= building | PASS |  |
| S7 Dates are possible | PASS |  |

24 rules: 19 pass, 1 fail, 1 to review, **3 not exercised by this package** (a rule the package never triggers proves nothing either way).

## Every box that is not right

### Wrong (48)

| box | expected | on the form | |
|---|---|---|---|
| `Insurer_FullName_A` | Granite Arch Casualty Company | Timberline Mutual Insurance Company | no |
| `Insurer_NAICCode_A` | 21334 | 27413 | no |
| `Policy_PaymentMethod_MethodDescription_A` | EFT | Direct bill | recall 0.00 precision 0.00 |
| `CommercialPolicy_FormalSafetyProgram_OtherDescription_B` | Daily job hazard analysis before every shift | Safety Manual, Safety Position, Monthly Meetings, OSHA | recall 0.00 precision 0.00 |
| `OtherPolicy_PolicyNumberIdentifier_A` | WC-GA-448120 | GL-123456 | no |
| `OtherPolicy_PolicyNumberIdentifier_B` | IM-GA-220915 | BA-456789 | no |
| `CommercialPolicy_UncorrectedFireCodeViolationExplanation_A` | Colorado Springs Fire Department noted two extinguishers with expired inspection tags at L | Two portable extinguishers at Location 3 had expired inspection tags and were open pending | recall 0.58 - part of the meaning is missing |
| `CommercialPolicy_ApplicantOwnLeaseOperateDronesExplanation_A` | The applicant owns one DJI Mavic 3 Enterprise drone flown by a Part 107 certified employee | The applicant owns one DJI Mavic 3 Enterprise drone for roof and site inspections. | recall 0.69 - part of the meaning is missing |
| `NamedInsured_Contact_SecondaryEmailAddress_A` | jsmith.site@example-electrical.com | jsmith.site@example.com | no |
| `NamedInsured_Contact_SecondaryEmailAddress_B` | sjones@example-electrical.com | sjones@example.com | no |
| `LossHistory_LineOfBusiness_A` | General Liability | GL | no |
| `PriorCoverage_PolicyYear_A` | 2025 | 2024 | no |
| `PriorCoverage_GeneralLiability_PolicyNumberIdentifier_A` | GL-123456 | GL-104471 | no |
| `PriorCoverage_GeneralLiability_TotalPremiumAmount_A` | $18,450 | 17,600 | no |
| `PriorCoverage_GeneralLiability_EffectiveDate_A` | 10/01/2025 | 10/01/2024 | no |
| `PriorCoverage_GeneralLiability_ExpirationDate_A` | 10/01/2026 | 10/01/2025 | no |
| `PriorCoverage_Automobile_PolicyNumberIdentifier_A` | BA-456789 | BA-431120 | no |
| `PriorCoverage_Automobile_TotalPremiumAmount_A` | $14,200 | 13,450 | no |
| `PriorCoverage_Automobile_EffectiveDate_A` | 10/01/2025 | 10/01/2024 | no |
| `PriorCoverage_Automobile_ExpirationDate_A` | 10/01/2026 | 10/01/2025 | no |
| `PriorCoverage_Property_PolicyNumberIdentifier_A` | CP-567890 | CP-540018 | no |
| `PriorCoverage_Property_TotalPremiumAmount_A` | $8,750 | 8,200 | no |
| `PriorCoverage_Property_EffectiveDate_A` | 10/01/2025 | 10/01/2024 | no |
| `PriorCoverage_Property_ExpirationDate_A` | 10/01/2026 | 10/01/2025 | no |
| `PriorCoverage_OtherLine_PolicyNumberIdentifier_A` | CU-678901 | CU-652207 | no |
| `PriorCoverage_OtherLine_TotalPremiumAmount_A` | $4,100 | 3,900 | no |
| `PriorCoverage_OtherLine_EffectiveDate_A` | 10/01/2025 | 10/01/2024 | no |
| `PriorCoverage_OtherLine_ExpirationDate_A` | 10/01/2026 | 10/01/2025 | no |
| `PriorCoverage_PolicyYear_B` | 2024 | 2023 | no |
| `PriorCoverage_GeneralLiability_PolicyNumberIdentifier_B` | GL-104471 | GL-091233 | no |
| `PriorCoverage_GeneralLiability_TotalPremiumAmount_B` | $17,600 | 16,900 | no |
| `PriorCoverage_GeneralLiability_EffectiveDate_B` | 10/01/2024 | 10/01/2023 | no |
| `PriorCoverage_GeneralLiability_ExpirationDate_B` | 10/01/2025 | 10/01/2024 | no |
| `PriorCoverage_Automobile_PolicyNumberIdentifier_B` | BA-431120 | BA-402266 | no |
| `PriorCoverage_Automobile_TotalPremiumAmount_B` | $13,450 | 12,980 | no |
| `PriorCoverage_Automobile_EffectiveDate_B` | 10/01/2024 | 10/01/2023 | no |
| `PriorCoverage_Automobile_ExpirationDate_B` | 10/01/2025 | 10/01/2024 | no |
| `PriorCoverage_Property_PolicyNumberIdentifier_B` | CP-540018 | CP-511907 | no |
| `PriorCoverage_Property_TotalPremiumAmount_B` | $8,200 | 7,850 | no |
| `PriorCoverage_Property_EffectiveDate_B` | 10/01/2024 | 10/01/2023 | no |
| `PriorCoverage_Property_ExpirationDate_B` | 10/01/2025 | 10/01/2024 | no |
| `PriorCoverage_OtherLine_InsurerFullName_B` | Timberline Mutual Insurance Company | Harbor Excess Insurance Company | no |
| `PriorCoverage_OtherLine_PolicyNumberIdentifier_B` | CU-652207 | XS-3310472 | no |
| `PriorCoverage_OtherLine_TotalPremiumAmount_B` | $3,900 | 3,650 | no |
| `PriorCoverage_OtherLine_EffectiveDate_B` | 10/01/2024 | 10/01/2023 | no |
| `PriorCoverage_OtherLine_ExpirationDate_B` | 10/01/2025 | 10/01/2024 | no |
| `AdditionalInterest_MailingAddress_LineOne_A` | 1600 Broadway | 1600 Broadway, Ste 900 | no |
| `AdditionalInterest_FullName_B` | Ortega Family Trust | Rocky Mountain Equipment Finance LLC | no (scanned page only) |

### In the documents, missing from the form (44)

| box | expected | |
|---|---|---|
| `Insurer_ProductDescription_A` | Contractors Select Program |  |
| `Insurer_ProductCode_A` | CSP-EL |  |
| `Insurer_Underwriter_FullName_A` | Dana Whitfield |  |
| `Insurer_Underwriter_OfficeIdentifier_A` | Denver Branch |  |
| `Policy_Status_QuoteIndicator_A` | Y |  |
| `Policy_Payment_PaymentScheduleCode_A` | MO |  |
| `CancelNonRenew_AgentNoLongerWritesForInsurerIndicator_A` | Y |  |
| `CancelNonRenew_UnderwritingIndicator_A` | Y |  |
| `CancelNonRenew_UnderwritingConditionCorrectedIndicator_A` | Y |  |
| `CommercialPolicy_RemarkText_A` | Please quote General Liability at $1,000,000 / $2,000,000 and the umbrella at $2,000,000.  |  |
| `NamedInsured_Primary_PhoneNumber_A` | 303-555-0175 |  |
| `NamedInsured_MailingAddress_LineOne_B` | 8000 Commerce Way |  |
| `NamedInsured_MailingAddress_LineTwo_B` | Suite 130 |  |
| `NamedInsured_MailingAddress_LineOne_C` | 8000 Commerce Way |  |
| `NamedInsured_MailingAddress_LineTwo_C` | Suite 140 |  |
| `NamedInsured_Contact_SecondaryBusinessPhoneIndicator_A` | Y |  |
| `NamedInsured_Contact_SecondaryCellPhoneIndicator_B` | Y |  |
| `CommercialStructure_PhysicalAddress_LineTwo_C` | Suite 210 |  |
| `PriorCoverage_GeneralLiability_InsurerFullName_B` | Timberline Mutual Insurance Company |  |
| `PriorCoverage_Automobile_InsurerFullName_B` | Timberline Mutual Insurance Company |  |
| `PriorCoverage_Property_InsurerFullName_B` | Timberline Mutual Insurance Company |  |
| `PriorCoverage_PolicyYear_C` | 2023 |  |
| `PriorCoverage_GeneralLiability_InsurerFullName_C` | Timberline Mutual Insurance Company |  |
| `PriorCoverage_GeneralLiability_PolicyNumberIdentifier_C` | GL-091233 |  |
| `PriorCoverage_GeneralLiability_TotalPremiumAmount_C` | $16,900 |  |
| `PriorCoverage_GeneralLiability_EffectiveDate_C` | 10/01/2023 |  |
| `PriorCoverage_GeneralLiability_ExpirationDate_C` | 10/01/2024 |  |
| `PriorCoverage_Automobile_InsurerFullName_C` | Timberline Mutual Insurance Company |  |
| `PriorCoverage_Automobile_PolicyNumberIdentifier_C` | BA-402266 |  |
| `PriorCoverage_Automobile_TotalPremiumAmount_C` | $12,980 |  |
| `PriorCoverage_Automobile_EffectiveDate_C` | 10/01/2023 |  |
| `PriorCoverage_Automobile_ExpirationDate_C` | 10/01/2024 |  |
| `PriorCoverage_Property_InsurerFullName_C` | Timberline Mutual Insurance Company |  |
| `PriorCoverage_Property_PolicyNumberIdentifier_C` | CP-511907 |  |
| `PriorCoverage_Property_TotalPremiumAmount_C` | $7,850 |  |
| `PriorCoverage_Property_EffectiveDate_C` | 10/01/2023 |  |
| `PriorCoverage_Property_ExpirationDate_C` | 10/01/2024 |  |
| `PriorCoverage_OtherLine_InsurerFullName_C` | Harbor Excess Insurance Company |  |
| `PriorCoverage_OtherLine_PolicyNumberIdentifier_C` | XS-3310472 |  |
| `PriorCoverage_OtherLine_TotalPremiumAmount_C` | $3,650 |  |
| `PriorCoverage_OtherLine_EffectiveDate_C` | 10/01/2023 |  |
| `PriorCoverage_OtherLine_ExpirationDate_C` | 10/01/2024 |  |
| `AdditionalInterest_MailingAddress_LineTwo_A` | Suite 900 |  |
| `AdditionalInterest_Item_BuildingProducerIdentifier_A` | 1 |  |

### Made up - the documents state nothing (8)

| box | expected | on the form | |
|---|---|---|---|
| `AdditionalInterest_PolicyRequiredIndicator_A` | (must be blank) | Y |  |
| `AdditionalInterest_SendBillIndicator_A` | (must be blank) | Y |  |
| `CommercialPolicy_UncorrectedFireCodeViolation_ResolutionDate_A` | (must be blank) | 10/05/2026 |  |
| `OtherPolicy_LineOfBusinessCode_C` | (must be blank) | Commercial Property |  |
| `OtherPolicy_LineOfBusinessCode_D` | (must be blank) | Commercial Umbrella |  |
| `OtherPolicy_PolicyNumberIdentifier_C` | (must be blank) | CP-567890 |  |
| `OtherPolicy_PolicyNumberIdentifier_D` | (must be blank) | CU-678901 |  |
| `Policy_Status_RenewIndicator_A` | (must be blank) | Y |  |

### Wrong role - a trap value in its trap box (3)

| box | expected | on the form | |
|---|---|---|---|
| `Insurer_FullName_A` | must not be 'Timberline Mutual Insurance Company' | Timberline Mutual Insurance Company |  |
| `Insurer_NAICCode_A` | must not be '27413' | 27413 |  |
| `AdditionalInterest_FullName_B` | must not be 'Rocky Mountain Equipment Finance LLC' | Rocky Mountain Equipment Finance LLC | (scanned page only) |

### A rule says blank (1)

| box | expected | on the form | |
|---|---|---|---|
| `Policy_SectionAttached_DriverInformationScheduleIndicator_A` | (must be blank) | Y |  |

### Counted correct BY MEANING - check the wording (4)

| box | expected | on the form | |
|---|---|---|---|
| `CommercialPolicy_AnyExposureToFlammableExplosivesChemicalsExplanation_A` | Limited quantities of common jobsite adhesives and solvents stored in approved containers. | Limited quantities of common jobsite adhesives and solvents are stored in approved contain | recall 1.00 precision 1.00 |
| `CommercialPolicy_PastLossesClaimsRelatingSexualAbuseDiscriminationNegligentHiringExplanation_A` | A former apprentice filed an EEOC discrimination charge in 2023; it was dismissed with no  | A former apprentice filed an EEOC discrimination charge in 2023; it was dismissed with no  | recall 0.90 precision 1.00 |
| `CommercialPolicy_ApplicantOtherBusinessVenturesCoverageNotRequestedExplanation_A` | The managing member owns Summit Solar Services LLC, a residential solar installer that is  | Luis Ortega owns Summit Solar Services LLC, a residential solar installer not part of this | recall 0.82 precision 0.82 |
| `AdditionalInterest_ItemDescription_A` | Fleet yard building, 5300 N Federal Blvd, Denver | Location 2, Building 1 - Fleet yard building, 5300 N Federal Blvd, Denver | recall 1.00 precision 0.70 |

### Rules audit failures (2)

| box | expected | on the form | |
|---|---|---|---|
| `C1: Policy_Status_RenewIndicator_A` |  | Yes | a status other than QUOTE is ticked |
| `C1: Policy_Status_QuoteIndicator_A` |  |  | QUOTE is not ticked |

