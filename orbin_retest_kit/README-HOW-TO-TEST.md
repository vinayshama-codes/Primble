# Orbin retest kit - the client's real submission, rebuilt

Built 24 Sep 2026 so the owner can check Michelle's 11 items on the SHAPE of
the client's own Orbin Contracting LLC submission. Every earlier kit used an
invented insured; this one reprints the client's EMC package (271 pages
condensed to 49), a certificate whose text comes back run-together exactly like
the client's certificate OCR, and a narrative that mentions the old broker and
names no new one.

| File | What it is | Pages | The pipeline must type it as |
|---|---|---|---|
| `1_policy_package.pdf` | EMC "Package Policy": common declarations, Inland Marine, Business Auto, Umbrella, General Liability, plus the endorsement pages that set the traps | 49 | Dec Page |
| `2_certificate.pdf` | ACORD 25 look-alike dated 07/28/2025 | 1 | Certificate of Insurance |
| `3_narrative.pdf` | Underwriting submission narrative | 1 | Underwriting Narrative |

**Upload all three TOGETHER, as ONE package, in a NEW session.** Several rules
key on each document's type (a certificate documents the existing policy, a
narrative is a submission document), so they must stay three files. A re-used
session carries old confirmations (`IM 7100 06 04`, `$1,000,000`, the old
agency) that hide exactly the fixes this kit checks.

## Item numbers (the "Item" column)

Michelle's 11 items, numbered as in the client's 11 Sep audit
(`11sep-form-improvement.md`):

| Item | What the client reported |
|---|---|
| 1 | Carrier, NAIC, policy number and dates not staying with their own line of business |
| 2 | Phantom coverages - Property, Crime, Workers Comp, Farm, Liquor, EPLI, OCP, Pollution shown as lines |
| 3 | A form number (`IM 7100 06 04`) printed as a policy number; false conflicts |
| 4 | The expiring producer (Commercial Risk Solutions / Terri Wroblewski) on the new application |
| 5 | Carrier / NAIC pairs no document prints; comparisons that should never happen ($2M vs a Yes/No box, Claims-Made vs a form title) |
| 6 | Codes on the wrong line (GL class 91580 on the vehicle row, Drive Other Car 104 / 6679 on the GL form) |
| 7 | ACORD 137 for Colorado auto - offered, and filled correctly |
| 8 | "For Informational Purposes Only" printed as a named party |
| 9 | Umbrella $3,000,000 -> $1,000,000 treated as a conflict instead of a dated change |
| 10 | Comparison guardrails - conflict cards and warnings that should not exist |
| 11 | Asked again for what the policy already states (the Subaru, "Driver 25") |

## Before you start

1. **Restart the backend, then prove the running process is the current code.**
   `uvicorn --reload` has served stale code on this machine before (the A125
   run 4 served 16:01 code all evening). Stop it - if `--reload` left a parent
   AND a child, stop both (`kill -9` if they ignore TERM) - and start it
   without reload, keeping the log:

   ```
   cd backend
   PURGE_DEC_INDEX_AFTER_GENERATION=0 .venv/bin/uvicorn main:app --port 8000 2>&1 | tee ../orbin_retest_kit/backend-run.log
   ```

   Then check that the worker started AFTER the last code change:

   ```
   ps -eo pid,lstart,command | grep main:app
   ```

   Hard-refresh the browser too (rebuild if you serve a built frontend): the
   "ticking 127 ticks 137 CO" behaviour (A3 / A5) is frontend code.
2. **`PURGE_DEC_INDEX_AFTER_GENERATION=0`** - on the command line above, or in
   `backend/.env` - so `dec_page_entries` survives generation for inspection.
3. **Set your test user's profile: organization `ThinkSmith Agency LLC`, full
   name `Michelle Smith`** (and a phone number, if the profile has one). No
   uploaded document names the new agency - the producer block follows the
   LOGIN: agency, name, and since 24 Sep the login's e-mail and phone. If you
   keep your own account, read every "ThinkSmith Agency LLC / Michelle Smith"
   below as your own account's agency and name; the rule being checked is the
   same. **A profile with NO agency is not a pass or a fail - it voids every
   producer row:** the block then prints blank (never Commercial Risk
   Solutions) and the log says `submitting account unavailable` (section N).
4. **FRESH upload of all three files together as ONE package.** Record sections
   A-C before answering anything on the pre-form screen.
5. **Select ACORD 125, 126, 127, 131 and 186**, and check that ticking 127 ticks
   **ACORD 137 CO** by itself (row A3). Generate. (186 because the client
   generates it; without it the contractor rule caps the package at 85.)
6. **Download one generated form first.** If it is the blank template, stop:
   this environment cannot fill PDFs (the pikepdf issue) and nothing below means
   anything - grade from the stored session instead.

## What the documents say (the truth)

| Line | Carrier (legal entity) | NAIC | Policy number - every printing is ONE contract | Premium |
|---|---|---|---|---|
| General Liability | EMC Property & Casualty Company | 25186 | `BBC7263-26` = `BBC7263 - 26` = `BBC7263` | $3,954.00 |
| Business Auto | Employers Mutual Casualty Company | 21415 | `6E7-40-02---26` = `6E7-40-02` = `6E74002` | $2,991.00 |
| Inland Marine | Employers Mutual Casualty Company | 21415 | `6C7-40-02---26` = `6C74002` | $300.00 |
| Umbrella | Employers Mutual Casualty Company | 21415 | `6J7-40-02---26` = `6J74002---26` = `6J74002` | $3,418.00 |
| Property / Crime and Fidelity / Workers' Compensation | - | - | **No Coverage** on page 1 | - |

- Term 07/15/2025 - 07/15/2026 on every line; declarations issued 07/16/25;
  estimated total $10,663.00. Account number `0482854` is NOT a policy number.
- **The policy prints no NAIC anywhere** - exactly like the real package. Each
  carrier's NAIC exists only on the certificate (INSURER A / B).
- **GL:** OCCURRENCE (CG 00 01 04 13). Each Occurrence 1,000,000; General
  Aggregate 2,000,000; Products-Completed Ops 2,000,000; Personal & Adv Injury
  1,000,000; Damage to Premises Rented 500,000; Medical Expense 10,000. Classes
  91580 (payroll $39,300) and 91585 (total cost $350,000), no territory printed.
  The GL extension (CG 77 59) applies the aggregate per project and per location.
- **Auto:** CSL $1,000,000 symbol 1; Med Pay $5,000 symbol 2; UM / UIM
  $1,000,000 CSL symbol 2; comprehensive and collision $1,000 deductible symbol 7;
  hired auto physical damage deductibles $1,000 (CA7450 M). ONE vehicle - 2012
  SUBARU OUTBACK SEDAN, VIN `4S4BRCGC9C3217772`, CLASS 7383, TERR 111, USE: NA, garaged at
  4800 Dahlia St D13, Denver CO. Drive Other Car: TERRITORY 104, class 6679,
  $204.00, named individual ROYAL, ERIN (also printed "ERIN ROYAL", as on the real
  package) - she is NOT a driver. Auto Elite Extension class 8556.
- **Umbrella:** $3,000,000 each occurrence / aggregate on the 07/16/25
  declarations. The certificate (07/28/2025) prints $1,000,000 and the remark
  "Reduced Umbrella Limit from $3,000,000 to $1,000,000 Limit Effective 7/25/25";
  the narrative says $1,000,000. Underlying: GL EMC Property & Casualty Company `BBC7263-26`, Auto
  Employers Mutual Casualty Company `6E7-40-02---26`.
- **Producer on every document:** Commercial Risk Solutions, Inc. - the EXPIRING broker. The
  narrative's only agency sentence is "The account has been placed through
  Commercial Risk Solutions."

### Page map of `1_policy_package.pdf`

| Pages | Section |
|---|---|
| 1-2 | Common Declarations (IL 7000A) - Coverages and Premium, servicing company |
| 3-14 | Inland Marine `6C7-40-02---26` - dec, endorsement schedule, schedule of coverages, AAIS IM 7100 / IM 7201 / CL 0182, IL 73 06 |
| 15-28 | Business Auto `6E7-40-02---26` - dec, UM schedule, vehicle, hired / non-owned, endorsement premium detail, Drive Other Car, CA 00 01, CA7450 M, IL 00 21, IL 02 28 |
| 29-38 | Umbrella `6J7-40-02---26` - dec, endorsement schedule, schedule of underlying insurance, CU 00 01, CU7269 / CU7270, IL 01 25, Colorado Company Elimination |
| 39-49 | General Liability `BBC7263-26` - dec, forms, endorsement schedule, GL schedule, locations, CG 00 01, CG 77 59, IL 00 03 |

## The traps

| Trap | Where | Item |
|---|---|---|
| Page 1 lists lines and premiums only; "6 Workers' Compensation No Coverage" sits directly above "7 Umbrella $3,418.00" | policy p1 | 1, 2 |
| Two legal entities of one group; "EMC Property and Casualty Company", "EMCASCO", "EMC Insurance Companies" printed elsewhere | policy p2, p38, GL section | 1, 5, 10 |
| Every page header names the producer and that section's policy number; footers print form numbers, the compact number and a "2601" print code (`6C74002 2601`) | every policy page | 1, 3, 4 |
| Form numbers beside policy numbers: IM 7100 06 04, IM 7201 10 02, CU7001A 11-15, CA7450 M, CA7000A 02-22, CG 70 01A 10 12, IL 71 31A 04 01, CG 00 01 04 13 | forms schedules, footers, umbrella dec | 3 |
| Endorsement MENUS naming Commercial Property, Commercial Crime, Crime and Fidelity, Farm, Liquor, EPLI, OCP, Pollution, Medical Professional | policy p14, 27, 28, 37, 49 | 2 |
| "DRIVE OTHER CAR - TERRITORY: 104 6679 $ 204.00" and "Auto Elite Extension 8556 $ 250.00" | policy p21 | 6 |
| VIN, CLASS 7383, TERR 111 in one vehicle block; the narrative repeats the car without a VIN | policy p19; narrative | 6, 11 |
| "Coverage Form: CU7001A 11-15 Commercial Liability Umbrella Coverage Form" beside the umbrella limits | policy p29 | 3, 5 |
| GL aggregate "applies separately to each of your construction projects" / "to each of your locations" | policy p48 | 5, 10 |
| Run-together certificate strings: `INSURER A :EMCProperty&CasualtyCompany 25186`, `INSURER B :EmployersMutualCasualtyCo. 21415`, `ForInformationalPurposesOnly`, `Note:ReducedUmbrellaLimitfrom$3,000,000to$1,000,000LimitEffective7/25/25.` | certificate | 1, 8, 9 |
| Unticked HIRED AUTOS ONLY / NON-OWNED AUTOS ONLY; an empty preprinted Workers Comp / Employers Liability row | certificate | 2, 10 |
| Conditional renewal wording ("if it is a renewal of a policy issued by us") | policy p13, 28, 49 | 10 |
| The old broker named in a SUBMISSION document | narrative | 4 |

## Checklist

Fill **Result**: PASS / FAIL + the literal value you saw. Row IDs are stable, so
"E4 FAIL, TERR shows 104" is enough. **Send = yes** means screenshot it.

### A. Form selection (pre-form)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| A1 | 2 | Recommended forms | ACORD 125, 126, 127, 131 marked Required | any of the four missing or not Required | yes | |
| A2 | 2 | Recommended forms | ACORD 130, 140 and 141 NOT offered at all | any of them offered (page 1 says Workers' Comp, Property, Crime: No Coverage) | yes | |
| A3 | 7 | Tick ACORD 127 | ACORD 137 CO becomes ticked automatically, and its card still reads **Needs Confirmation** | 137 CO stays unticked, disappears, or is relabelled Required | yes | |
| A4 | 7 | ACORD 137 CO card evidence | auto facts: liability limit $1,000,000, UM / UIM $1,000,000 | contractor facts ("Contractor type: ...") | | |
| A5 | 7 | Untick 137 CO by hand (re-tick it before generating) | a banner "ACORD 127 is selected without ACORD 137 CO ..." with a one-click **Add ACORD 137 CO** | 137 CO silently dropped, no banner | | |
| A6 | new | "Tailored for:" chips above the list | no "Renewal" chip (no document says this is a renewal) | "Renewal" | | |

Not graded: ACORD 25, 186 and 160 may also be offered (160 is the known
mislabelled Business Owners form).

### B. Data Consistency (pre-form)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| B1 | 1, 3, 10 | Policy Number | no conflict card - scoped per line: GL `BBC7263-26`, Auto `6E7-40-02---26`, Inland Marine `6C7-40-02---26`, Umbrella `6J7-40-02---26` | a card; `IM 7100 06 04` / `IM 7201 10 02` / `CU7001A 11-15` / `IL 71 31A 04 01` / `CG 70 01A 10 12` / `0482854` offered as a choice | yes | |
| B2 | 1, 10 | Carrier | no conflict card - GL EMC Property & Casualty Company; Auto, Inland Marine, Umbrella Employers Mutual Casualty Company | an "EMC Property & Casualty vs Employers Mutual" card; "EMC Insurance" or "EMCASCO" offered | yes | |
| B3 | 1, 5, 10 | Carrier NAIC | no conflict card - 25186 on GL only, 21415 on Auto / Umbrella; Inland Marine shows "-" (only the certificate prints NAICs, and it does not list the Inland Marine policy) | a "25186 vs 21415" card; 25186 beside Employers Mutual | yes | |
| B4 | 9 | Umbrella Limit | read-only row **"Changed during the policy term - not a conflict"**: Now $1,000,000, effective 7/25/25 (certificate); Before $3,000,000 (policy) | a "$3,000,000 vs $1,000,000" card asking you to confirm | yes | |
| B5 | 4 | Producer Name | no card | COMMERCIAL RISK SOLUTIONS, INC. vs Commercial Risk Solutions, Inc. (or vs your agency) | | |
| B6 | 10 | Building value | no card | any building-value card - the package has no property coverage | | |
| B7 | 10 | Renewal | no is_renewal card | a renewal yes / no card - the only "renewal" words are cancellation-clause boilerplate | | |
| B8 | 10 | Hired auto | no card | a hired-auto yes / no card (the certificate's UNTICKED "HIRED AUTOS ONLY" label vs the policy's Item Four) | | |
| B9 | 1, 2 | Policies in this submission (if shown) | 4 policies, each with its own carrier and number; no Workers Comp, Property or Crime row | 5+ rows; a No Coverage line listed; a dash for a number | yes | |

### C. Warnings / hard stops (pre-form)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| C1 | 1, 10 | Warnings / submission integrity | NO "Multiple carriers referenced across documents" | present | yes | |
| C2 | 2 | Cover page, dashboard card, submission integrity, questionnaire | no coverage list naming Property, Crime, Workers Compensation, Farm, Liquor, Employment-Related Practices (EPLI), Owners and Contractors Protective (OCP) or Pollution - anywhere | any of them listed as a line the insured has | yes | |
| C3 | 9 | Warnings | no umbrella "documents state different amounts" warning | present | | |
| C4 | 4 | Warnings | no "Producer Name: documents disagree" warning | present | | |

Expected, NOT a failure: "Driver schedule not provided" (the policy schedules no
drivers - the only person is the Drive Other Car individual); a note that the
printed term already ended (07/15/2026) or that the new term must be confirmed.

### D. ACORD 125

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| D1 | 1, 3 | Page 1 CARRIER / NAIC / POLICY NUMBER | all three **blank** - no document names the carrier receiving this submission | Employers Mutual or EMC P&C; 21415 / 25186; any number (`IM 7100 06 04`, `0482854`, a 6E7 / BBC number) | yes | |
| D2 | 1 | STATUS OF TRANSACTION | **QUOTE** ticked | RENEW ticked, or nothing | | |
| D3 | 2 | LINES OF BUSINESS ticks | only Commercial General Liability, Business Auto, Inland Marine, Umbrella | Property, Crime, Workers Comp, Cyber, Liquor or anything else ticked | yes | |
| D4 | 1, 3, 10 | OTHER INSURANCE WITH THIS COMPANY (rows A-D) | the 4 policies, each with its own number: General Liability `BBC7263-26`, Commercial Auto `6E7-40-02---26`, Inland Marine `6C7-40-02---26`, Umbrella `6J7-40-02---26` (row order may differ; `BBC7263 - 26` is the same GL policy) | one number on every row; a form number; `0482854`; a line with no number; a No Coverage line | yes | |
| D5 | 4 | Producer block - agency, contact, authorised representative | the logged-in agency and name (ThinkSmith Agency LLC / Michelle Smith); e-mail and phone are your login's (blank only if the profile has none); address blank | Commercial Risk Solutions / Terri Wroblewski; 303-996-7800 or twroblewski@crsdenver.com as the producer's contact | yes | |
| D6 | 4 | Anywhere on the form | none of: Commercial Risk Solutions, Terri Wroblewski, W6258-0001 (or AW 6258, W6258), 303-996-7800, twroblewski@crsdenver.com, Meridian | any of them | | |
| D7 | 8 | Any box | no "For Informational Purposes Only" in any spelling the kit prints (`ForInformationalPurposesOnly`, `FOR INFORMATIONAL PURPOSES ONLY`) | in Additional Interest, certificate holder or remarks | | |
| D8 | 3 | Every policy-number box (page 1, other insurance, prior carrier grid) | never `IM 7100 06 04`, `IM 7201 10 02`, `CU7001A 11-15`, `CA7450 M`, `CA7000A 02-22`, `CG 70 01A 10 12`, `IL 71 31A 04 01`, `CG 00 01 04 13`; never `0482854` | any of them | | |
| D9 | new | DESCRIPTION OF PRIMARY OPERATIONS (page 2, the big box) | the narrative's own paragraph: "Commercial general contractor. The company manages tenant-finish, remodeling ..." | "INSURED IS: LLC BUSINESS DESC: COMMERCIAL GENERAL CONTRA" | yes | |
| D10 | new | Premises row DESCRIPTION OF OPERATIONS (one-line box) | "Commercial general contractor." at a readable size | the whole paragraph in tiny type, cut off mid-word; "INSURED IS: LLC ..." | | |
| D11 | new | General information Q "Any exposure to flammables, explosives, chemicals?" | blank (no document says) | Y - the live run printed Y "explained" by the business description | yes | |

**D4 - if the whole list is blank:** it was blanked on 16 Sep (run 10 read "this
company" as the carrier receiving the submission) and RESTORED on 24 Sep by owner
decision (`pdf_service._other_policy_rows`). A blank list most likely means the
backend is still running pre-24-Sep code - redo the restart check in "Before you
start", step 1, before recording a FAIL.

### E. ACORD 126

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| E1 | 1, 5 | Header CARRIER / NAIC / POLICY NUMBER | EMC Property & Casualty Company / 25186 / `BBC7263-26` (`BBC7263 - 26` is the same policy) | Employers Mutual Casualty; 21415; an auto / umbrella / inland marine number; blank | yes | |
| E2 | 5 | Occurrence / Claims-Made; retro date | OCCURRENCE ticked, CLAIMS-MADE not; PROPOSED RETROACTIVE DATE blank | Claims-Made ticked; both blank; any retro date | | |
| E3 | 1 | GL limits | Each Occurrence 1,000,000; General Aggregate 2,000,000; Products-Completed Ops 2,000,000; Personal & Adv Injury 1,000,000; Damage to Premises Rented 500,000; Medical Expense 10,000 | any 3,000,000 (the umbrella's); 1,000,000 as the aggregate | | |
| E4 | 6 | Hazard grid | row A 91580 (payroll $39,300), row B 91585 (total cost $350,000); **TERR blank** on both | 7383 / 6679 / 104 / 8556 in any cell; TERR filled; a third row copying row A or reading "Fungi Or Bacteria Exclusion" | yes | |
| E5 | 6 | Anywhere on 126 | no 7383, 6679, 104 or 8556 | any of them | | |
| E6 | 2, 6 | UM / UIM and Employee Benefits | no UM / UIM amount; no Employee Benefits limit | $1,000,000 in a UM / UIM box; EBL $1,000,000 or "0 - 25" | | |
| E7 | 2, 5 | OTHER coverage description | does not name an auto, inland marine or umbrella line (a GL coverage such as "Limited Pollution Coverage - Work Sites" may appear) | "Commercial Auto Liability", "Installation Floater", "Commercial Umbrella", "Commercial General Liability / Commercial Auto Liability" | | |
| E8 | new | DEDUCTIBLES | PROPERTY DAMAGE and BODILY INJURY blank; the third (OTHER) row reads "Property Damage Deductible Each Pollution Incidents" with 1,000 | 1,000 in the PROPERTY DAMAGE or BODILY INJURY box | yes | |
| E9 | new | Contractors Q4 "Do your subcontractors carry coverages or limits less than yours?" | blank (no document says) - and never the opposite of 131 Q14 (row G7) | N here with Y on 131, or any answer | | |
| E10 | new | Q "Vendors coverage required?" | blank (no document says) | Y - the live run printed Y "explained" by the subcontractor sentence | yes | |
| E11 | new | Contractors Q5 "Are subcontractors allowed to work without providing you with a certificate of insurance?" | N (the narrative: they must provide certificates before they start) or blank | Y | | |

### F. ACORD 127

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| F1 | 1 | Header | Employers Mutual Casualty Company / 21415 / `6E7-40-02---26` | 25186; EMC P&C; another line's number | yes | |
| F2 | 6, 11 | Vehicle row 1 | 2012 / SUBARU / OUTBACK / VIN `4S4BRCGC9C3217772` / CLASS 7383 / TERR 111 | class 91580 / 91585 / 6679; TERR 104; VIN missing | yes | |
| F3 | 11 | Vehicle row 2 (and 3, 4) | **blank** - the narrative's "2012 Subaru Outback" is the SAME car and must merge into the declarations row | a second Subaru row; $39,300 / $350,000 / 26680 on another row | yes | |
| F4 | 11 | Driver rows | ERIN ROYAL not printed as a driver | ERIN / ROYAL in any Driver box; the name in a gender or tax-ID box | | |
| F5 | 6 | FARTHEST TERMINAL | blank | 6679 or 104 | | |
| F6 | 6 | Anywhere on 127 | no 91580, 91585, 6679 | any of them | | |
| F7 | 11 | Vehicle row 1 garaging address | 4800 DAHLIA STREET D13 / DENVER / CO / 80216-3121 (read off the vehicle block's LOC line) | blank; another address; the producer's Meridian address | | |
| F8 | new | Vehicle row 1 COST NEW and the "$ AA ST AMT" box | COST NEW 26,680; ACV ticked; the AA / ST AMT amount blank | 100,000 (the hired-auto limit) or any amount beside ACV; COST NEW blank | yes | |
| F9 | new | SYM / AGE, COMP/OTC SYM, COLL SYM | all blank (owner decision 24 Sep: covered-auto symbols print on the 137) | 7 / 07 / 07 | | |
| F10 | new | USE (commercial, service, retail, pleasure, farm, for hire, OTHER) | nothing ticked and the OTHER description blank - the vehicle's own block prints "USE: NA" | any use ticked; OTHER ticked with "PRIVATE PASSENGER" (the live run 2 value - that is the vehicle's TYPE) | yes | |
| F11 | new | "ACORD 129 attached for additional vehicles" | unticked - one vehicle fits the 127 | ticked | | |
| F12 | new | Page 2 MAXIMUM DOLLAR VALUE SUBJECT TO LOSS | 26,680 (the one vehicle's cost new) | 1,000,000 or any other amount | | |

### G. ACORD 131

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| G1 | 1 | Header | Employers Mutual Casualty Company / 21415 / `6J7-40-02---26` | 25186; the 6E7 number | | |
| G2 | 9 | Umbrella EACH OCCURRENCE / AGGREGATE | 1,000,000 / 1,000,000 | blank, or 3,000,000 | yes | |
| G3 | 9 | Anywhere on 131 | no 3,000,000 - including the personal & advertising injury / OTHER limit | any 3,000,000 | | |
| G4 | 1 | Underlying GL row | EMC Property & Casualty Company / `BBC7263-26` (or `BBC7263`) | carrier or number blank; Employers Mutual on the GL row | yes | |
| G5 | 1 | Underlying Auto row | Employers Mutual Casualty Company / `6E7-40-02---26` (or `6E74002`) | carrier or number blank | | |
| G6 | 2 | Underlying schedule | no Liquor, Pollution, OCP or Employers Liability entries | an Employers Liability row or E.L. limits; any of the others | | |
| G7 | new | Q14 "Do subcontractors carry coverages or limits less than applicant?" | blank, like 126 (row E9) | Y (the live run printed Y while 126 printed N) | yes | |
| G8 | new | PRIMARY LOCATION description (one-line box) | "Commercial general contractor." at a readable size | the whole paragraph in tiny type, cut off; "INSURED IS: LLC BUSINESS DESC: ..." | | |

### H. ACORD 137 CO

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| H1 | 1, 7 | Header | Employers Mutual Casualty Company / 21415 / `6E7-40-02---26` | anything else | | |
| H2 | 7 | Business Auto liability | CSL ticked + 1,000,000 | blank; EACH PERSON ticked | yes | |
| H3 | 7 | Med Pay | 5,000 | blank | | |
| H4 | 7 | Uninsured Motorists | CSL + 1,000,000 | blank | | |
| H5 | 7 | Symbol grid | 1 (liability) / 2 (med pay) / 2 (UM) / 7 (comprehensive) / 7 (collision), and no "other symbol" ticked on any row | rows blank; 1 on every row; UM row "other: 1" | yes | |
| H6 | 7 | Truckers and Motor Carrier pages | completely blank | any value or tick | | |
| H7 | 7 | Hired physical damage comprehensive / collision deductible | 1,000 or blank | any other amount | | |

### P. ACORD 186

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| P1 | 1 | Header | EMC Property & Casualty Company / 25186 / `BBC7263-26` | another line's carrier or number | | |
| P2 | 4 | CONTRACTORS LICENSE NUMBER | blank - no document prints a contractor licence | W6258-0001 (the old broker's AGENT NO.) or AW 6258 | yes | |
| P3 | new | MINIMUM GL LIMITS REQUIRED OF SUBCONTRACTORS | both blank - no document states a required minimum | 1,000,000 / 2,000,000 (Orbin's own limits) | yes | |
| P4 | new | TOTAL COST OF SUBCONTRACTED WORK PAST YEAR | 350,000 (GL class 91585's exposure) | blank or another amount | | |
| P5 | new | Questions marked * (1 plans, 2 blasting, 3 excavation, 4 safety policy, 7 subcontractor limits, 8 certificates, 9 lease equipment, 10 boats, 13 lease employees) | all blank - the form says "* DO NOT ANSWER IF THIS FORM IS ATTACHED TO ACORD 126", and 126 is in this package | any answer (the live run printed 8 = N) | yes | |

### I. Every generated form (125, 126, 127, 131, 137 CO, 186)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| I1 | 4 | Producer block | the logged-in agency / name on all six | Commercial Risk Solutions / Terri Wroblewski on any; W6258 / AW 6258 / 303-996-7800 anywhere | | |
| I2 | 8 | Any party box | never "For Informational Purposes Only" (any spelling) | present | | |
| I3 | 3 | Every policy-number box | never a form number (list in D8), never `0482854` | present | | |
| I4 | new | Every Y on an underwriting question (125, 126, 127, 131, 186) | its explanation actually states the thing asked; otherwise the question is blank | a Y "explained" by the business description ("Commercial general contractor ...") or by the subcontractor sentence ("Subcontractors are required to carry their own ...") | yes | |

### J. Pre-download review (Field QA)

| # | Item | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|
| J1 | 5, 10 | no row comparing a dollar amount with a Per Project / Per Location box | "PerLocation / PerProject shows No but source is $2,000,000" | yes | |
| J2 | 5 | no row comparing a Claims-Made tick with a form title | "... source is Commercial Liability Umbrella Coverage Form" / "CG 00 01 04 13" | | |
| J3 | 3 | no row comparing a policy number with a form number | "source value is IM 7100 06 04" (or any form number in the D8 list) | | |
| J4 | 1, 10 | no row comparing one line's number or NAIC with another line's | "shows 6J7-40-02---26 but the source value is 6E7-40-02---26"; "21415 vs 25186" | | |

### K. Send to Client - preview only (do not send)

| # | Item | Where | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| K1 | 11 | Vehicle table | **CONFIRM mode**: "We found 1 vehicle in your policy declarations..." with the Subaru row shown and pre-ticked | "Please list the vehicles to be insured"; an empty table | yes | |
| K2 | 11 | Location table | confirm mode with 4800 DAHLIA ST # D13 / DENVER / CO / 80216-3121 | "Please list every business location" | yes | |
| K3 | 11 | Drivers | no numbered "(Nth driver)" questions | "(1st driver)" ... "(25th driver)"; ERIN ROYAL pre-filled as a driver | yes | |
| K4 | 11 | Confirm items | legal name (ORBIN CONTRACTING LLC) and mailing address shown as confirm items, pre-ticked | missing; empty text boxes asking for them | | |
| K5 | 1, 3 | Carrier / NAIC / policy-number questions | none | any | | |
| K6 | 2 | Coverage questions | no Workers Comp, Employers Liability or Property questions | any | | |
| K7 | 1, 3, 4 | After opening the preview, download 125 / 126 / 127 / 131 again | every value in D-H unchanged | `IM 7100 06 04`, 25186 beside Employers Mutual, or Commercial Risk Solutions comes back | | |

### L. Cover page

| # | Item | Box | Expected when fixed | Broken looks like | Send | Result |
|---|---|---|---|---|---|---|
| L1 | 2 | LINES OF BUSINESS | Liability, Inland Marine, Automobile, Umbrella - nothing else | Property, Crime, Workers Comp, Farm, Liquor, EPLI, OCP, Pollution | yes | |
| L2 | 4 | PRIOR CARRIER | never "Commercial Risk Solutions" (a broker, not a carrier); the current policies' own carriers may appear | "PRIOR CARRIER: Commercial Risk Solutions" | | |
| L3 | 8 | Anywhere | no "For Informational Purposes Only" | present | | |
| L4 | new | POLICY PERIOD | "To be confirmed (expired term 07/15/25 - 07/15/26)" | "current term" | | |
| L5 | new | Package summary paragraph | never says the account is currently in force | "currently in force" | | |

### M. Scores - record only, nothing is graded

Package ___ | 125 ___ | 126 ___ | 127 ___ | 131 ___ | 137 CO ___

### N. Backend log - grep after the run

| grep (in `orbin_retest_kit/backend-run.log`) | Expected | Result |
|---|---|---|
| `grep "combined_gap_fill: line-scoped groups"` | present, with groups `None` (package-level questions), `general_liab` (126), `auto` (127 / 137 CO) and `umbrella` (131). Offline, each line's scope is the common pages plus its own section only - 12 to 16 of the 49 pages | |
| `grep -c "UNKNOWN_KEYS"` | few or none | |
| `grep "calculate_package_sqs failed"` | absent | |
| `grep "submitting account unavailable"` | absent - present means the login's agency could not be read, and every producer row (B5, C4, D5, D6, I1, L2) is void | |
| `grep "vehicle block cells applied"` | present: cost_new ...=26680 and auto_vehicle_use cleared | |
| `grep "GL deductible applies to"` | present, `'other'` | |
| `grep "operations description from the applicant's own words"` | present | |
| `grep "answered both ways"` / `grep "PRODUCER_IDENTIFIER"` | either may appear - each line is a wrong answer the fill produced and the guard removed | |

## What to send back

1. This README with the **Result** column filled (row ID + PASS / FAIL + the
   literal value for every FAIL).
2. The generated PDFs: ACORD 125, 126, 127, 131, 137 CO and the cover page.
3. Screenshots of every **Send = yes** row - at minimum: the recommended-forms list
   after ticking 127; the whole Data Consistency panel (cards, the umbrella row,
   the policies table); the warnings / hard stops; the pre-download review list;
   the Send to Client preview (vehicle table, location table, drivers, confirm
   items).
4. The whole matching lines from the four greps in section N (or "none").
5. The scores from section M.

## Known, not graded here

- **Dates.** The printed term (07/15/2025 - 07/15/2026) ended on 07/15/2026.
  ACORD 125's proposed dates are asked of the producer (15 Sep ruling); the
  section forms keep the current policy's identity with the ended date blank.
- **The umbrella remark is run-together on purpose**, like the client's
  certificate. Since 24 Sep the change reader re-spaces it itself
  (`narrative_facts.respace_glued_prose`), so **a B4 conflict card is a FAIL** -
  with one exception worth a screenshot: open the certificate's extracted
  `additional_remarks_text` / `certificate_description_of_operations`. If the
  note is not there at all, extraction never captured it (send that); if it is
  there, in any spacing, the reader missed it (send that too). With no dated
  sentence anywhere the row stays a conflict by owner decision, and its
  suggested value is the amount the forms print (D16).
- **Drive Other Car name order.** The schedule prints "ROYAL, ERIN" (as the retest
  spec asked); the continuation page also prints "ERIN ROYAL" (as the real package
  does), so F4 / K3 test the 14 Sep named-individual rule whichever order
  extraction copies.
- The producer ADDRESS prints blank when the login's agency differs from the
  documents' (by design since 14 Sep); e-mail and phone come from the login
  since 24 Sep.
- **An abbreviated placeholder ("FIO", "FIPO") is NOT refused.** The party test
  is structural, and an initialism reads exactly like a real company ("3M",
  "EMC", "CRS"). The kit prints the client's full run-together phrase, which is
  refused; an abbreviation in a live document would print.
- ACORD 137 CO's hired physical damage deductible (H7) still comes from gap
  fill, not a deterministic reader - 1,000 or blank are both acceptable.
- ACORD 160 is the known mislabelled form; leave it.

## How this kit was built and self-checked

`backend/.venv/bin/python backend/scripts/make_orbin_retest_pdfs.py` rebuilds the
three PDFs and this README, offline (no database, network or LLM call), and fails
unless:

- the certificate's four run-together strings come back verbatim from plain
  pdfplumber `page.extract_text()` AND from the pipeline's own text layer;
- the policy contains every form number above, the account number, the three
  "No Coverage" rows as lines of their own, the 7-line endorsement menu, the Drive
  Other Car line and the VIN;
- 17/17 passages copied verbatim from the client's own OCR
  (`271page_test_data/271page-testdec.txt`) come back as consecutive lines through
  the pipeline's text layer - character similarity to the real pages: mean
  96% over 20 declarations / schedule pages;
- the pipeline's own classifier types the files dec page / certificate / narrative;
- the page-header carrier binder (`_header_carrier_name`) reads each section's own
  carrier off 47/47 section pages;
- both printings of the Drive Other Car name sit under a named-individual heading
  (`named_individuals.printing_roles`);
- every page carries at least 100 native characters and no image, so the live
  pipeline reads this text instead of sending the page to Google Vision.

**Different from the real package, on purpose:** 49 pages instead of 271; every
page (ISO pages included) carries a carrier + policy number + producer header
stamp; per the retest spec, the umbrella's underlying schedule prints `BBC7263-26` /
`6E7-40-02---26` (the real one printed `BBC7263` / `6E74002`), the GL dec
prints "Coverage Form: CG 00 01 04 13 ... Occurrence", the umbrella dec prints the
`CU7001A 11-15` coverage-form line, the Auto Elite Extension carries a hired-auto
physical damage deductible schedule, and the certificate's producer is
Commercial Risk Solutions, Inc. (the real one printed "CRS Insurance Brokerage").
