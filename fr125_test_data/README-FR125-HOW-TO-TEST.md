# FR125 v2 - the client's case at data-map density

**Upload:** `FR125_front_range_package.pdf` - 100 pages, 513,023 text-layer characters (every text page at least 3,116), 4 scanned pages with no text layer, 1 landscape page.  
**Answer key:** `FR125_answer_key.json` - all 548 ACORD 125 boxes.  
**Version 1** (the sparse client case graded in round 2 test 2) is kept in `v1_round2_test2/`.

## What the form should look like

Filled the way the client's Vertafore data map is filled: nearly every box a document can support carries a value. Every client rule still holds - receiving carrier, NAIC only if verified (it is, on the carrier's acknowledgement), no policy number or premium on a quote, no invented history, blank is not No.

| | boxes |
|---|---|
| expect a value | **312** |
| must be blank - nothing stated | 166 |
| must be blank - a rule owns it | 54 |
| not scored | 16 |

## Run it

```bash
# restart the backend first
python3 backend/scripts/make_fr125_test_pdf.py
# upload the PDF, generate ACORD 125 ONLY, change nothing
python3 backend/scripts/dump_a125_run.py --list
python3 backend/scripts/dump_a125_run.py <session_id> > fr125_run.json
python3 backend/scripts/report_125_run.py --key fr125_test_data/FR125_answer_key.json --dump fr125_run.json --label "ROUND 2 - TEST 9" --compare fr125_test_data/runs/r2t8_e3cebd88_numbers.json
```

**Results so far** (full detail in `improving125-21sep.md`, the runs in `runs/`):

| run | correct of 312 | wrong | missing | made up |
|---|---|---|---|---|
| Test 3, session `4c734a06`, as run (28 Sep) | 220 | 48 | 44 | 8 |
| Test 3 replayed through the 28 Sep fixes | 297 | 1 | 14 | 0 |
| Test 4, session `a7ef6f98`, live on the fixed code (28 Sep) | 281 | 2 | 29 | 3 |
| Test 4 replayed through the second fixes | 306 | 1 | 5 | 0 |
| Test 5, session `b63c3e25`, live on the second fixes (28 Sep) | 298 | 1 | 13 | 2 |
| Test 5 with extraction v23 facts (simulated) | 311 | 1 | 0 | 0 |
| Test 6, session `c3059a2d`, live on extraction v23 (28 Sep) | 304 | 6 | 2 | 4 |
| Test 6 replayed through the v24 fixes | 312 | 0 | 0 | 0 |
| Test 7, session `5af86855`, live on extraction v24 (28 Sep) | 310 | 0 | 2 | 1 |
| Test 7 replayed through the v25 fix | 312 | 0 | 0 | 0 |
| Test 8, session `e3cebd88`, live on extraction v25 (28 Sep) | 312 | 0 | 0 | 3 |
| Test 8 replayed through the fix | 312 | 0 | 0 | 0 |
| Test 9, same extraction (cached) | pending | | | |

## The traps

| value | forbidden in | why |
|---|---|---|
| `Timberline Mutual Insurance Company` | `Insurer_FullName_A` | the CURRENT carrier where the RECEIVING one belongs |
| `27413` | `Insurer_NAICCode_A` | the current carrier's NAIC |
| `GL-123456` | `Policy_PolicyNumberIdentifier_A` | an EXPIRING policy number on a quote |
| `CG 20 11 04 13` | `Policy_PolicyNumberIdentifier_A` | an ISO form number |
| `$18,450` | `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | the expiring GL premium on a quote |
| `$45,500` | `Policy_Payment_EstimatedTotalAmount_A` | the expiring package total |
| `10/01/2025` | `Policy_EffectiveDate_A` | the CURRENT term's start |
| `Agency bill - Quarterly installments` | `Policy_PaymentMethod_MethodDescription_A` | the CURRENT policy's billing, not the requested method |
| `www.timberlinemutual-ins.com` | `NamedInsured_Primary_WebsiteAddress_*` | the carrier's website |
| `(800) 555-0147` | `NamedInsured_Primary_PhoneNumber_*` | the carrier's service line |
| `303-555-0100` | `NamedInsured_Primary_PhoneNumber_*` | the producer's phone |
| `12345678` | `NamedInsured_TaxIdentifier_*` | an 8-digit state tax account |
| `3456789` | `NamedInsured_TaxIdentifier_*` | a 7-digit USDOT number |
| `92478` | `NamedInsured_NAICSCode_*` | a GL class code in the NAICS box |
| `$4,610,000` | `CommercialStructure_AnnualRevenueAmount_*` | the PROJECTED revenue |
| `$1,640,000` | `CommercialStructure_AnnualRevenueAmount_*` | payroll is not revenue |
| `$4,250,000` | `CommercialStructure_AnnualRevenueAmount_*` | the COMPANY total - each premises carries its own share |
| `6` | `BusinessInformation_PartTimeEmployeeCount_*` | agency temps |
| `$3,200` | `LossHistory_PaidAmount_*` | the OLD valuation's paid |
| `$1,650` | `LossHistory_ReservedAmount_*` | the OLD valuation's reserve |
| `$26,550` | `LossHistory_TotalAmount_A` | paid + reserved is INCURRED |
| `Commerce Way Partners LP` | `AdditionalInterest_FullName_*` | the landlord is no interest |
| `Commerce Way Partners LP` | `NamedInsured_FullName_*` | the landlord is not a named insured |
| `Front Range Holdings Inc` | `NamedInsured_FullName_*` | the PARENT is not a named insured |
| `FREC-001` | `Producer_CustomerIdentifier_A` | another agency's customer id |
| `$19,071,155` | `CommercialStructure_AnnualRevenueAmount_*` | the WIP backlog |
| `Mortenson Construction` | `AdditionalInterest_FullName_*` | a certificate HOLDER |
| `Mortenson Construction` | `NamedInsured_FullName_*` | a certificate holder |
| `Rocky Mountain Equipment Finance LLC` | `AdditionalInterest_FullName_B` | ACORD: 'as used here, this is the name of the TRUST' - not a second interest |

## Reachable ONLY by OCR

- `AdditionalInterest_FullName_B`
- `CommercialPolicy_Question_AAFCode_A`
- `CommercialPolicy_Question_ABBCode_A`
- `CommercialPolicy_Question_KACCode_A`
- `CommercialPolicy_Question_KAKCode_A`
- `CommercialPolicy_Question_KALCode_A`
- `CommercialPolicy_Question_KAMCode_A`
- `CommercialPolicy_Question_KANCode_A`
- `CommercialPolicy_Question_KAOCode_A`
- `NamedInsured_LegalEntity_MemberManagerCount_A`

## Deliberately never stated

- a policy number, premium, deposit or minimum premium for the policy being QUOTED
- any aircraft, airport, boat or scheduled item for the additional interest
- a resolution for the fire-code violation - service is only SCHEDULED
- a second occurrence under questions 8, 9 or 10
- any claim before 2023 in the five-year loss history

0 boxes defaulted to 'nothing stated' at build time.
