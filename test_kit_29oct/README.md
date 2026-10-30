# Live test kit, 29 Oct 2026: Ridgeline Mechanical Services LLC

Everything here is fictional. Insured: **Ridgeline Mechanical Services LLC**, FEIN **84-5512309**, 4150 S Kalamath St, Denver CO 80223, an HVAC and plumbing contractor. The current programme runs 12/01/2025 - 12/01/2026 (it ends in 33 days), so the next term to propose is **12/01/2026 - 12/01/2027**.

## Files

| File | Pages | What it is | Goes to ASG Transcriber? |
|---|---|---|---|
| `01_declarations_package.pdf` | 23 | A text PDF with 5 carriers and 5 policies: GL (class schedule), Business Auto (4 vehicles with VINs, 5 drivers), WC (CO classes, WY stop-gap, X-mod 0.92), Umbrella ($5M, $10k SIR, schedule of underlying), Property (2 premises, 3 buildings with COPE, 2% wind/hail). Also endorsement and forms pages. | No |
| `02_outside_acord_125_flattened.pdf` | 5 | Our ACORD 125 (2025/03) template, filled by an OUTSIDE agency (Bluestem Risk Advisors LLC, Fort Collins), then flattened: no form fields and no Primble record | **Yes, 5 pages** |
| `03_outside_acord_127_flattened.pdf` | 4 | ACORD 127 (2015/12), filled completely: 5 drivers, all 17 general-information Y/N questions with explanations, modified equipment, one conviction row, telematics, garage, 2 lienholders, remarks, 4-vehicle schedule. Flattened the same way. | **Yes, 4 pages** |
| `04_loss_runs_2021_2023.pdf` | 5 | Carrier loss runs for terms 12/2020 - 12/2023, valued 01/10/2024 (3 years only) | No |
| `later_05_loss_runs_2024_2026.pdf` | 5 | Loss runs for terms 12/2023 - 12/2026, valued 10/20/2026 | No |
| `later_06_primble_downloaded_form.pdf` | 5 | An ACORD 125 that Primble generated itself (carries `/PrimbleRecord`). It names **Orbin Contracting LLC** (FEIN 47-2918364, 4800 Dahlia St, producer "Astrea It services"). This is a different insured from Ridgeline. | No (our own record) |
| `scripts/` | - | The generators (run with `backend/.venv/bin/python`) | - |

**Expected Transcriber cost: 9 pages** (125: 5 + 127: 4), and only on the first upload of each file. The dec, the loss runs and Primble's own form never go to ASG. Note: page 1 of the 127 template does not print "Page 1 of 4". ACORD prints that only on pages 2-4, but the "ACORD 127 (2015/12)" footer and "ACORD CORPORATION" are on page 1. If routing needs "Page n of m" on every page, page 1 of the 127 is the edge case to watch.

## Upload order

1. **One upload together, as a new package:** 01, 02, 03, 04.
2. **When the pre-form screen asks for more loss runs** (Loss History): upload `later_05_loss_runs_2024_2026.pdf` with Add documents.
3. **06, separately.** The best test is a new package of its own: its answers should come back for Orbin, on the account that made it. A second test is to add it to the Ridgeline package to see the "Different insured" tag. It must not write anything into Ridgeline.

## Planted inconsistencies (FEIN and insured name are the same in every file)

| # | Fact | Declarations / loss run | Outside ACORD | Where |
|---|---|---|---|---|
| 1 | Mailing address line 2 | Suite 200 (dec) | **Suite 210** | 125 |
| 2 | Business start date | 03/15/2011 (dec Insured Information page) | **06/01/2012** | 125 |
| 3 | Business phone | (303) 555-0148 (dec) | **(303) 555-0184** | 125 |
| 4 | Annual revenue | $8,450,000 (dec) | **$9,200,000** (premises row A) | 125 |
| 5 | Employees FT / PT | 62 / 6 (dec) | **58 / 4** (premises row A) | 125 |
| 6 | NAICS | 238220 (dec) | **238210** | 125 |
| 7 | Proposed term | dec renewal 12/01/2026 - 12/01/2027 | **01/01/2027 - 01/01/2028**, status QUOTE | 125 |
| 8 | Loc 1 Bldg 2 area | 22,000 sq ft (dec COPE page) | **25,000** | 125 (the 125 has no year-built box, so the area is used instead) |
| 9 | Auto claim 05/17/2022 paid | **$18,420** (loss run 04, BA-22-118830) | **$14,820** | 125 loss history row B |
| 10 | Veh 2 VIN (2022 Ram ProMaster) | 3C6LRVDG4NE11836**2** | 3C6LRVDG4NE11836**7** | 127 |
| 11 | Driver 3 Derek A. Nguyen DOB | 12/0**3**/1991 | 12/0**8**/1991 | 127 |

These are differences, but not conflicts: producer (dec = Peak & Prairie Insurance Group, ACORD = Bluestem Risk Advisors LLC; the login should outrank both). The 125 loss history lists only 3 claims, while the runs show 9. The 125 prior-carrier grid repeats the dec carriers and premiums (2025 row = dec premiums), and its Other column = the umbrella (UMBRC).

## Edge-case checklist (expected results)

- [ ] **Document tags:** 02 and 03 show "Read by ACORD Transcriber" and are typed ACORD 125 / ACORD 127. 01 is Declarations, 04 / 05 are Loss Runs. 06 shows "Different insured" if it is added to Ridgeline.
- [ ] **Data Consistency:** every row 1-8, 10, 11 above raises a card with BOTH values, each naming its source (dec vs ACORD 125 / 127). Per the owner table, the ACORD owns applicant and submission facts, so it may be the suggested value. The dec value must still be offered. If a row produces no card and the forms print one value silently, that is a finding. Write down which value printed.
- [ ] **Claim amount conflict (row 9):** the 05/17/2022 auto claim is shown as one claim, with $18,420 vs $14,820 flagged. It must not appear as two claims.
- [ ] **Proposed term (row 7):** Primble never silently prints 12/01/2026 and ignores the ACORD's 01/01/2027, or the reverse. Expect a card or a question. After you confirm, the expiration follows (one year later).
- [ ] **Loss history years:** after the first upload, Loss History asks for more years. 04 covers only 12/2020 - 12/2023, valued 01/2024, and the business is 15 years old, so 5 years are needed. After 05 is added, that ask clears and the WC / auto / GL / property claims from both runs are listed (9 claims; 2 open WC claims).
- [ ] **Please verify:** values read by the Transcriber appear as "Please verify" rows. They must not be labelled as AI fills or as document-verified facts.
- [ ] **WY monopolistic:** the WC dec says Wyoming is insured through the Wyoming Workers' Compensation Division (state fund) and the private policy is stop-gap EL only. Any monopolistic question can be answered "state fund" and must clear. It must not be a stuck hard stop.
- [ ] **127 details reach the forms:** 5 drivers, 4 vehicles with garaging (Veh 4 in Cheyenne, Laramie County), symbol 7 comp/coll, $1,000 deductibles, lienholders Wells Fargo (Veh 1) / Ally (Veh 3), the conviction for driver 3.
- [ ] **Reach 100:** answer everything the pre-form screen asks (and pick a value on every Data Consistency card). The score reaches **exactly 100**, and the listed points add up to 100 minus the score at each step.
- [ ] **After forms:** the side-panel numbers add up to 100. The download screen lists the same open items and numbers as the side panel.
- [ ] **06 (Primble's own form):** in an Orbin package on the same account, its answers and tables are restored, and Transcriber is not called. In the Ridgeline package it is tagged as a different insured and restores nothing. On another account it restores nothing.
