# FR125 - the client's ACORD 125 test case

**Upload:** `FR125_front_range_package.pdf` (100 pages, one file).  
**Answer key:** `FR125_answer_key.json` - a verdict for all 548 ACORD 125 boxes.  
**Answers come from:** the CLIENT's own answer key (`125_reference/ACORD 125 - field completition 8-19-26.docx`).

## Verdicts

| | |
|---|---|
| expect a value | 106 (6 graded on MEANING) |
| must be blank - nothing stated | 242 |
| must be blank - a rule owns it | 53 |
| no entity for the row | 134 |
| not scored | 13 |

## Run it

```bash
# 1. RESTART THE BACKEND (a stale process ran old code on test 2)
python3 backend/scripts/make_fr125_test_pdf.py
# 2. upload fr125_test_data/FR125_front_range_package.pdf,
#    generate ACORD 125 ONLY, change nothing
python3 backend/scripts/dump_a125_run.py --list
python3 backend/scripts/dump_a125_run.py <session_id> > fr125_run.json
python3 backend/scripts/report_125_run.py --key fr125_test_data/FR125_answer_key.json --dump fr125_run.json
python3 backend/scripts/audit_125_rules.py fr125_run.json
```

## What is hard, and where

| technique | where | what it tests |
|---|---|---|
| scanned page, no text layer | questionnaire p.2, W-9, articles, old loss run | OCR; questions 8-15 are ONLY here |
| X in a column | questionnaire p.1 | reading an answer from its position |
| abbreviated headers | premises table (FT, PT, OCC SF, TOT SF, LSD) | RC-G beyond the two columns fixed on 21 Sep |
| landscape page | statement of values | wide-table reading order |
| teletype | GL declarations | `page_layout.despaced_words` |
| riffled table | premises, profile, job sites, auto loss run | `page_layout.page_words` |
| two-column drift | contacts, operations | column reflow |
| dot leaders | profile | label and value 70 characters apart |
| spelled three ways | revenue, employees, area, start date | normalisation |
| placeholders in source | '--', 'N/A', '(none)' | Guard 13 at the source |
| two valuations of one claim | auto loss run + old fax | latest wins, never two rows |

## Decoys (each scoped to the boxes it is forbidden in)

| value | forbidden in | why |
|---|---|---|
| `Timberline Mutual Insurance Company` | `Insurer_FullName_A` | the CURRENT carrier, on every dec header, where the RECEIVING carrier belongs |
| `27413` | `Insurer_NAICCode_A` | the current carrier's NAIC - the receiving carrier's NAIC is never stated |
| `GL-123456` | `Policy_PolicyNumberIdentifier_A` | an EXPIRING policy number in the box for the policy being applied for |
| `CG 20 11 04 13` | `Policy_PolicyNumberIdentifier_A` | an ISO form number reads like a policy number |
| `$18,450` | `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | the expiring GL premium on a quote |
| `$45,500` | `Policy_Payment_EstimatedTotalAmount_A` | the expiring package total on a quote |
| `10/01/2025` | `Policy_EffectiveDate_A` | the CURRENT term's start |
| `www.timberlinemutual-ins.com` | `NamedInsured_Primary_WebsiteAddress_*` | the carrier's website, printed in every running header |
| `(800) 555-0147` | `NamedInsured_Primary_PhoneNumber_*` | the carrier's service line, printed in every running header |
| `303-555-0100` | `NamedInsured_Primary_PhoneNumber_*` | the producer's phone sits beside the applicant block |
| `12345678` | `NamedInsured_TaxIdentifier_*` | an 8-digit state tax account is not a FEIN |
| `3456789` | `NamedInsured_TaxIdentifier_*` | a 7-digit USDOT number is not a FEIN |
| `92478` | `NamedInsured_NAICSCode_*` | a GL class code in the NAICS box |
| `$4,610,000` | `CommercialStructure_AnnualRevenueAmount_*` | the PROJECTED 2026 revenue, not the stated annual figure |
| `$1,640,000` | `CommercialStructure_AnnualRevenueAmount_*` | payroll is not revenue |
| `20` | `BusinessInformation_FullTimeEmployeeCount_*` | total headcount is 18 full-time + 2 part-time, not 20 full-time |
| `6` | `BusinessInformation_PartTimeEmployeeCount_*` | agency temps are not part-time employees |
| `$3,200` | `LossHistory_PaidAmount_*` | the OLD valuation's paid figure |
| `$1,650` | `LossHistory_ReservedAmount_*` | the OLD valuation's reserve - the claim is closed |
| `Pinecrest Employers Assurance Company` | `PriorCoverage_OtherLine_InsurerFullName_*` | workers comp is not being applied for; the umbrella owns OTHER |
| `Commerce Way Partners LP` | `AdditionalInterest_FullName_*` | the landlord is named in a lease summary, not as an interest on any policy |
| `Commerce Way Partners LP` | `NamedInsured_FullName_*` | the landlord is not a named insured |
| `FREC-001` | `Producer_CustomerIdentifier_A` | another agency's customer id - the logged-in agency is not Summit |
| `$6,451,100` | `CommercialStructure_AnnualRevenueAmount_*` | the work-in-progress BACKLOG is contract value, not annual revenue |
| `Mortenson Construction` | `AdditionalInterest_FullName_*` | a certificate HOLDER is not an additional interest |
| `Mortenson Construction` | `NamedInsured_FullName_*` | a certificate holder is not a named insured |

## Facts reachable ONLY by OCR

- `CommercialPolicy_Question_AAFCode_A`
- `CommercialPolicy_Question_ABBCode_A`
- `CommercialPolicy_Question_KACCode_A`
- `CommercialPolicy_Question_KAKCode_A`
- `CommercialPolicy_Question_KALCode_A`
- `CommercialPolicy_Question_KAMCode_A`
- `CommercialPolicy_Question_KANCode_A`
- `CommercialPolicy_Question_KAOCode_A`

If these miss and everything else lands, OCR is the suspect - check the backend log for `ocr_service` before touching extraction.

## Deliberately never stated

- the receiving carrier's NAIC code
- any audit period (for either the current or the proposed policy)
- any policy premium, deposit or minimum premium for the proposed policy
- an OSHA statement for the safety programme
- a phone type (home / business / cell) for either contact
- a secondary phone or e-mail for either contact
- a member / manager count for the LLC
- any other named insured
- any additional interest - every vehicle is owned outright
- any prior-carrier policy number or premium before the 2025-26 term
- a remark for the REMARKS box
- a second address line for the applicant or the premises

## Defaulted to blank at build time

40 fields were not decided explicitly and default to `blank_no_data`. They are listed in the build output; review them when the kit changes.
