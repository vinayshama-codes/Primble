# ROUND 2 - TEST 4 RESULTS - 28 Sep 2026

Kit: **FR125 v2 - the client's case at data-map density**. Session `a7ef6f98-ccc8-4e44-b00b-c1c8a1dec8c8`. ACORD 125 only, no human edits. Graded against the answer key by `score_form_fill.py` (meaning-aware since 28 Sep), and against the documents alone by `audit_125_rules.py`.

## The four numbers

| | boxes | |
|---|---|---|
| **Correct** | **281** of 312 (+61) | 280 exact, 0 code written as its word, 1 by meaning |
| **Wrong** | **2** (-46) | 1 of them partial - right but incomplete |
| **In the documents, missing from the form** | **29** (-15) | 0 printed only on a scanned page; by pass: 2 call2, 27 owned_blank |
| **Made-up values** - a value where the documents state nothing | **3** (-5) | |
| Wrong-role values - a trap value in its trap box | 0 (-3) | a real value, the wrong party or term |
| A rule says blank, and it was filled | 0 | |
| A row with no entity, and it was filled | 0 | |

**Accuracy of what it filled: 281 / 283 = 99.3%.**  
**Coverage of what it should fill: 281 / 312 = 90.1%.**

## Scorecard (round 1 format)

| | boxes |
|---|---|
| Must carry a value | 312 |
| &nbsp;&nbsp;correct | **281** |
| &nbsp;&nbsp;wrong value | **2** |
| &nbsp;&nbsp;missing (blank, should be filled) | **29** |
| Must stay empty | 220 |
| &nbsp;&nbsp;violated - a value appeared | **3** |
| **Fabricated** (scoped decoy landed) | **0** |
| Wrong shape (FEIN / ZIP / code format) | 0 |
| Overflow leak (a no-slot row displacing a real one) | 0 |
| Not scored | 16 |

## Row-cell

| group | cells due | correct | cross-row | orphan |
|---|---|---|---|---|
| named_insureds | 15 | 15 | 0 | 0 |
| premises | 32 | 32 | 0 | 0 |
| contacts | 8 | 8 | 0 | 0 |
| losses | 15 | 15 | 0 | 0 |
| prior_coverage | 24 | 24 | 0 | 0 |

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
  additional_interests           2/2             6      6      0      0  (+2 unexpected)

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
| C1 Status is QUOTE, and only QUOTE | PASS |  |
| C2 Page-one carrier is the carrier RECEIVING the submission | PASS |  |
| C3 NAIC only if verified for THAT carrier | PASS |  |
| C4 Policy number blank on a new-business quote | PASS |  |
| C5 Premium blank at submission stage unless known | PASS |  |
| C6 Proposed dates are the NEXT term, not the current one | PASS |  |
| C7 Prior carrier: only what the documents substantiate | PASS |  |
| C8 'No known losses' is never converted into loss history | PASS |  |
| C9 Loss total is the PAID amount of the losses (ACORD tooltip) | PASS |  |
| C10 Blank is not No - unanswered questions stay UNRESOLVED | REVIEW | 1 |
| C11 A Yes carries its explanation / detail | PASS |  |
| C12 A No (or blank) leaves its whole block empty | FAIL | 3 |
| C13 Other named insureds only if the documents support them | PASS |  |
| C14 Additional interest only if actually documented as one | PASS |  |
| C15 Form edition is the current one (2025/03) | PASS |  |
| C16 Every Yes / No answer has its own sentence in the documents | PASS |  |
| C17 An ATTACHMENTS tick names a form this package contains | PASS |  |
| S1 No placeholder ever reaches a box ('N/A', '--', 'none', 'TBD') | PASS |  |
| S2 Authorship: nothing signs or attests for a person | PASS |  |
| S3 Every code box holds the shape its ACORD tooltip declares | PASS |  |
| S4 Every printed value is found in the documents (made-up detector) | PASS |  |
| S5 No entity printed twice in one table | PASS |  |
| S6 Premises areas add up: public <= occupied <= building | PASS |  |
| S7 Dates are possible | PASS |  |

24 rules: 22 pass, 1 fail, 1 to review, **0 not exercised by this package** (a rule the package never triggers proves nothing either way).

## Every box that is not right

### Wrong (2)

| box | expected | on the form | |
|---|---|---|---|
| `Policy_PaymentMethod_MethodDescription_A` | EFT | Direct bill | recall 0.00 precision 0.00 |
| `CommercialPolicy_UncorrectedFireCodeViolationExplanation_A` | Colorado Springs Fire Department noted two extinguishers with expired inspection tags at L | Two fire extinguishers at Location 3 had expired inspection tags. | recall 0.67 - part of the meaning is missing |

### In the documents, missing from the form (29)

| box | expected | |
|---|---|---|
| `Insurer_ProductDescription_A` | Contractors Select Program |  |
| `Insurer_Underwriter_OfficeIdentifier_A` | Denver Branch |  |
| `CommercialPolicy_Question_AAICode_A` | Y |  |
| `CancelNonRenew_UnderwritingIndicator_A` | Y |  |
| `CommercialPolicy_RemarkText_A` | Please quote General Liability at $1,000,000 / $2,000,000 and the umbrella at $2,000,000.  |  |
| `NamedInsured_Contact_SecondaryBusinessPhoneIndicator_A` | Y |  |
| `NamedInsured_Contact_SecondaryCellPhoneIndicator_B` | Y |  |
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
| `AdditionalInterest_Item_BuildingProducerIdentifier_A` | 1 |  |

### Made up - the documents state nothing (3)

| box | expected | on the form | |
|---|---|---|---|
| `AdditionalInterest_Item_ScheduledItemClassCode_A` | (must be blank) | Contractors Equipment |  |
| `CancelNonRenew_OtherDescription_A` | (must be blank) | Agent no longer represents carrier |  |
| `CancelNonRenew_OtherIndicator_A` | (must be blank) | Y |  |

### Counted correct BY MEANING - check the wording (1)

| box | expected | on the form | |
|---|---|---|---|
| `AdditionalInterest_ItemDescription_A` | Fleet yard building, 5300 N Federal Blvd, Denver | Location 2, Building 1 - Fleet yard building, 5300 N Federal Blvd, Denver | recall 1.00 precision 0.70 |

### Rules audit failures (3)

| box | expected | on the form | |
|---|---|---|---|
| `C12: BusinessInformation_ParentOrganizationName_A` |  | Front Range Holdings Inc | filled while AAICode is blank |
| `C12: Subsidiary_ParentSubsidiaryRelationshipDescription_A` |  | Parent holding company | filled while AAICode is blank |
| `C12: Subsidiary_ParentOwnershipPercent_A` |  | 80% | filled while AAICode is blank |

