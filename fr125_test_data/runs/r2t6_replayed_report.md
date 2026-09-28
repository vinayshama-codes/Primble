# ROUND 2 - TEST 6 - replayed through the fixes RESULTS - 28 Sep 2026

Kit: **FR125 v2 - the client's case at data-map density**. Session `c3059a2d-3730-4752-9b8f-3ea8751a9360`. ACORD 125 only, no human edits. Graded against the answer key by `score_form_fill.py` (meaning-aware since 28 Sep), and against the documents alone by `audit_125_rules.py`.

## The four numbers

| | boxes | |
|---|---|---|
| **Correct** | **312** of 312 (+8) | 311 exact, 0 code written as its word, 1 by meaning |
| **Wrong** | **0** (-6) | 0 of them partial - right but incomplete |
| **In the documents, missing from the form** | **0** (-2) | 0 printed only on a scanned page; by pass: no dump - pass unknown |
| **Made-up values** - a value where the documents state nothing | **0** (-4) | |
| Wrong-role values - a trap value in its trap box | 0 (-1) | a real value, the wrong party or term |
| A rule says blank, and it was filled | 0 | |
| A row with no entity, and it was filled | 0 | |

**Accuracy of what it filled: 312 / 312 = 100.0%.**  
**Coverage of what it should fill: 312 / 312 = 100.0%.**

## Scorecard (round 1 format)

| | boxes |
|---|---|
| Must carry a value | 312 |
| &nbsp;&nbsp;correct | **312** |
| &nbsp;&nbsp;wrong value | **0** |
| &nbsp;&nbsp;missing (blank, should be filled) | **0** |
| Must stay empty | 220 |
| &nbsp;&nbsp;violated - a value appeared | **0** |
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
| prior_coverage | 36 | 36 | 0 | 0 |

## Extraction (LLM call 1) - read before the form

ENTITY-CELL **82/82 = 100.0%**; scalars 16 correct / 0 wrong / 0 missing; nothing invented.

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
  disclosure_answers             16/16           16     16      0      0  (+3 unexpected)
  safety_program_elements        4/4             0      0      0      0  (+4 unexpected)
  loss_history                   3/3            12     12      0      0
  additional_interests           2/2             6      6      0      0  (+2 unexpected)

  ENTITY-CELL  82/82 = 100.0%   cross-entity 0   blank 0

RELATIONSHIP CHECKS (no answer key - these run on any package)
  [warn ] UNKNOWN_SAFETY_ELEMENT                 safety_program_elements carries 'Other: Daily job hazard analysis before every shift', w
  [warn ] UNKNOWN_SAFETY_ELEMENT                 safety_program_elements carries 'Other: Lockout / tagout, arc-flash (NFPA 70E) and fall-
  [warn ] UNKNOWN_SAFETY_ELEMENT                 safety_program_elements carries 'Other: Incident reporting within 24 hours; root-cause r
  [warn ] UNKNOWN_SAFETY_ELEMENT                 safety_program_elements carries 'Other: Safety Training Log', which ticks no ACORD box

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
| C10 Blank is not No - unanswered questions stay UNRESOLVED | PASS |  |
| C11 A Yes carries its explanation / detail | PASS |  |
| C12 A No (or blank) leaves its whole block empty | PASS |  |
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

24 rules: 24 pass, 0 fail, 0 to review, **0 not exercised by this package** (a rule the package never triggers proves nothing either way).

## Every box that is not right

### Counted correct BY MEANING - check the wording (1)

| box | expected | on the form | |
|---|---|---|---|
| `AdditionalInterest_ItemDescription_A` | Fleet yard building, 5300 N Federal Blvd, Denver | Location 2, Building 1 - Fleet yard building, 5300 N Federal Blvd, Denver | recall 1.00 precision 0.70 |

