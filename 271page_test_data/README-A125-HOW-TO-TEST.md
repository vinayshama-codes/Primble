# A125 - the ACORD 125 full-form test kit

**Document:** `A125_meridian_package.pdf` - 100 pages, one upload.
**Key:** `A125_answer_key.json` - a verdict for **all 548** ACORD 125 boxes.
**Account:** Meridian Ironworks & Mechanical, LLC (synthetic).

## Why this kit exists

Every earlier kit scored a subset of ACORD 125 that whoever wrote the kit
chose. The T1 key has an opinion on 146 of the form's 548 boxes; the other
402 are unjudged, and the pipeline puts a value into 228 of them. This key
gives every box a verdict, so a percentage can never again be a percentage
of the boxes we decided to look at.

## The five verdicts

| verdict | meaning | count |
|---|---|---|
| `expect` | the document states it and this value belongs in THIS box | 243 |
| `blank_no_data` | the document says nothing - the box must ship EMPTY | 233 |
| `blank_by_rule` | the document DOES state something and one of our own rules owns the blank anyway (a signature, an agency-profile code, a premium on a quote) | 52 |
| `not_applicable` | a row the document has no entity for | 8 |
| `not_scored` | generation-time metadata nobody can pin | 12 |

`must_be_blank` in the scored key is the union of the middle three.

## How to run it

```bash
py backend/scripts/make_a125_test_pdf.py          # regenerate, self-verifying
#  upload 271page_test_data/A125_meridian_package.pdf, generate ACORD 125
py backend/scripts/score_form_fill.py \
    --key 271page_test_data/A125_answer_key.json \
    --pdf-dir <folder holding the generated PDF> [--facts facts.json]
```

Score in four buckets plus ROW-CELL, never in two. A run that fills every
cell of a four-row table with values from four different premises scores
100% on fields and near zero on ROW-CELL.

## 1. Is the data extracted, and does it keep its meaning?

The document is printed the way real carrier documents are, in the exact
shapes our own extraction layer was built to repair. The generator's
`verify()` re-reads the PDF **through `utils.page_layout`** and fails the
build if any of these stops being repaired:

| page | shape | what it proves |
|---|---|---|
| 11 | letter-spaced teletype - `P O L I C Y  N O` | `despaced_words` still rejoins it. This defect reached a client's ACORD 125 as `6 C 7 - 4 0 - 0 2`. |
| 19 | the description column physically overruns PAID, so pdfplumber returns `su$p7p,l3i2e0r` | `page_words` re-segments the line and `$7,320` comes back whole |
| 23 | the carrier name overruns the policy-number column | the same repair on the prior-carrier grid |
| 3, 13-17 | two independent columns with drifting baselines | the identity split, and prose read down each column instead of across |
| 2 | label on one line, value on the next | the bare-label fingerprint the column reflow keys on |
| 4 | the FEIN printed three ways (`93-2841760`, `93 2841760`, `932841760`) | one fact, three spellings, one value |
| every page | the CARRIER's own website and phone in the running header | the merge ranks by repetition - these out-repeat everything the applicant states |

## 2. Does each value land in the right box?

`expect` names the exact box. A value one box over is a WRONG, not a
CORRECT. The traps that separate boxes which look alike:

- **Proposed vs expiring term.** The submission is for 10/01/2026-10/01/2027;
  the expiring policy runs 10/01/2025-10/01/2026. Page one takes the proposed
  dates; the prior-carrier grid takes the expiring ones.
- **Receiving vs expiring carrier.** Page one is Northbridge Atlantic. The
  expiring carrier is Cascadia Harbor, the umbrella is on a third carrier,
  and two years ago it was a fourth.
- **Occupied area vs total building area.** Location 001 occupies 9,400 sq ft
  of a 26,000 sq ft building. Two numbers, two boxes.
- **Total paid vs total incurred.** `LossHistory_TotalAmount`'s own ACORD
  tooltip says *the amount that has been PAID*. The document prints
  `TOTAL PAID $77,810` and `TOTAL INCURRED $90,310`.
  Only one of them is right.
- **Parent's stake vs the applicant's stake.** Harbor Line owns 82% of the
  applicant; the applicant owns 100% of Cedar Bluff. The Subsidiary block
  wants the second.
- **Per-premises vs company-wide counts.** Employee counts and revenue on
  page 2 are per LOCATION; the company totals (50 / 11 /
  $21,480,000) are printed too and belong in neither.

## 3. Are the blanks correct?

Sixteen things are deliberately never stated. Their boxes must ship empty:

- applicant website for the FIRST named insured (row B has one, row A does not)
- producer fax number
- agency code / sub-code / customer identifier
- producer national identifier (NPN) and state licence number
- underwriter name and underwriter office
- billing plan, payment plan, deposit, minimum premium
- policy premium for the policy being applied for (it is a quote)
- a policy number for the policy being applied for
- county for Location 003 (Tigard)
- e-mail address for the ACCOUNTING contact
- question 9 - foreclosure / repossession / bankruptcy
- question 12 - foreign operations
- the OSHA element of the safety programme
- prior carrier year three (only two years are documented)
- an umbrella row in prior carrier year two
- a resolution date for the open fire-code violation

The sharpest of these is **question 9, 12**. The document
never puts them to the applicant, and says so in terms: *"Any question not
printed above was not put to the applicant and has no answer on file."*
Brent's own words: *Blank does not equal No.* A defaulted `N` in those boxes
is the defect this kit exists to catch.

The same rule at checkbox level: the safety programme states a manual, a
safety position and monthly meetings, and makes **no statement at all**
about OSHA. The OSHA box must be empty, not unticked-because-we-guessed.

## 4. Is the system inventing values?

Every decoy below is a real string in the document, scoped to the boxes it
must never reach. Scoping matters: a global "this must appear nowhere"
match fires on the box where the value legitimately belongs.

| value | must never reach | why it is tempting |
|---|---|---|
| `www.cascadiaharbor.com` | `NamedInsured_Primary_WebsiteAddress_*` | the carrier's own website, printed in 60 page headers - it out-repeats everything the applicant states |
| `(800) 555-0400` | `NamedInsured_Primary_PhoneNumber_*` | the carrier's service line, printed on every declarations page |
| `(503) 555-0118` | `NamedInsured_Primary_PhoneNumber_*` | the producer's phone sits beside the insured block in a two-column layout |
| `4471100` | `NamedInsured_TaxIdentifier_*` | a 7-digit account number in a 9-digit FEIN box - the SHAPE defect |
| `CG 21 47 12 07` | `Policy_PolicyNumberIdentifier_A` | an ISO endorsement form number reads like a policy number |
| `GL 4471102 25` | `Policy_PolicyNumberIdentifier_A` | the EXPIRING policy number in the box for the policy being applied for |
| `Cascadia Harbor Mutual Insurance Company` | `Insurer_FullName_A` | the expiring carrier where the receiving carrier belongs |
| `$73,410` | `GeneralLiabilityLineOfBusiness_TotalPremiumAmount_A` | the expiring GL premium in a page-one premium box on a quote |
| `$7,905,000` | `CommercialStructure_AnnualRevenueAmount_*` | payroll in a revenue box - the MEANING defect |
| `91746` | `NamedInsured_NAICSCode_*` | a GL class code in a NAICS box |
| `Pinnacle Grange Insurance Company` | `Insurer_FullName_A` | a carrier from two years ago as the submission carrier |

Three whole blocks are fabrication surfaces with nothing behind them:

- **`CancelNonRenew_*`** (8 boxes). Question 5 is `N`. Nothing goes here.
- **`OtherPolicy_*`** (8 boxes). Question 4 is `N`. The four expiring
  policies belong to a different carrier and must not be listed.
- **`PriorCoverage_*_C`** (21 boxes). Only two policy years are documented.
  The client's own instruction: *do not manufacture carrier history*.

## 5. Overflow - stated, with no slot

| stated | slots on the form | the overflow |
|---|---|---|
| 4 named insureds | 3 (rows A-C) | Meridian Ironworks Property Holdings, LLC |
| 5 premises | 4 (rows A-D) | 4110 Marine Dr, Astoria |
| 4 claims | 3 (rows A-C) | 06/08/2022 Commercial Inland Marine |

`expected_absent` fails the run if an overflow entity DISPLACES a real one.
Overflowing is capacity; displacing is a defect.

## What the kit does NOT decide

- `Form_CompletionDate_A` is the generation date - `not_scored`.
- `blank_by_rule` boxes are scored as must-be-blank. If a future ruling says
  one of them should fill (the agency-profile codes are the live example -
  they come from the broker's own profile, which the product does not yet
  collect), change the verdict here, not the scorer.

Generated by `backend/scripts/make_a125_test_pdf.py` from
`backend/scripts/_a125_data.py`. Edit the data module - the PDF and the key
are both built from it and cannot disagree.
