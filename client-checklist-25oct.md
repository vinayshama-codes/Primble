# Client items checklist (25 Oct 2026)

Compiled read-only from 25sepChanges.md, v1-20AUG.md and CLAUDE.md. "Live verified" = seen on localhost unless Render is named; everything from Z28 on is uncommitted.


**Read this first:** the last deploy is `6bff54a` (15 Oct). Everything from Z28 onward (19-25 Oct) is uncommitted and runs only on localhost. Unless a line says Render, "LIVE VERIFIED" means it was seen on localhost. Where the notes disagree, I took the latest dated note and say so on that line.

### Choice Electric test, 5 Oct (27 items + 1 extra)
- CE 5 Oct #1 | Blank band where the header was | BUILT, NOT LIVE-VERIFIED | re-fixed 13 Oct, after the last live check (AUDIT 15 Oct)
- CE #2 | "Next" button per section | LIVE VERIFIED | localhost `18ecbfa8` (part Y, 12 Oct)
- CE #3 | Document types right (praise) | LIVE VERIFIED | `0353c36b` (Z21)
- CE #4 | Umbrella $5M vs Excess $4M: one 131 per layer | BUILT, NOT LIVE-VERIFIED | two 131s seen live on `0353c36b`. Brent's 23 Oct follow-up (excess lists GL/Auto/EL, SIR or attachment) built in Z35, not live
- CE #5 | Audit "Annual" vs "A" | LIVE VERIFIED | `0353c36b` (125 "A", 130 At expiration; Z11/Z21)
- CE #6 | Address offered as a website | LIVE VERIFIED | `0353c36b`, no website row. Leftover question "which box takes a carrier website" was never answered (F00 made it the owner's to answer, the 15 Oct audit lists it as waiting)
- CE #7 | Every premium on its own line/form | BUILT, NOT LIVE-VERIFIED | Z28 (Brent 19 Oct rules) + Z35 partial total. Forms 152/834/827 left out by the owner (F00)
- CE #8 | "COMMERCIAL AUTO" read as a policy number | LIVE VERIFIED | `f83757cf` (Z16)
- CE #9 | 10 policies; inline edit; wrap | BUILT, NOT LIVE-VERIFIED | row count live on `f83757cf`. Edit/add/remove never used live (AUDIT 15 Oct)
- CE #10 | Remove "not a conflict" blocks; group by carrier | LIVE VERIFIED | localhost 8-12 Oct (AUDIT 15 Oct)
- CE #11 | Remove "Important" | LIVE VERIFIED | localhost (AUDIT 15 Oct)
- CE #12 | Keep fixed items listed as "Resolved" | LIVE VERIFIED | Render, fix path only; Dismiss never ran on Render (AUDIT 15 Oct)
- CE #13 | Remove "Resolve" | LIVE VERIFIED | localhost
- CE #14 | 2 buildings, not 3; value columns; template | LIVE VERIFIED | Render (AUDIT 15 Oct)
- CE #15 | EBL "tucks under WC" | BUILT, NOT LIVE-VERIFIED | Brent answered 19 Oct; built Z28 B
- CE #16 | Positive SQS wording | LIVE VERIFIED | localhost
- CE #17 | ACORD 125 ticked and first | LIVE VERIFIED | localhost. The "first in the list" half was declined by the owner (order stays by match %)
- CE #18 | Hard stop only after forms; modal; two building values | LIVE VERIFIED | `0353c36b` closed (Z21). "Confirm this value" never seen live
- CE #19 | Edit / double-click / Cancel | LIVE VERIFIED | localhost
- CE #20 | Carrier information on the 125 | BUILT, NOT LIVE-VERIFIED | page-one rule live on `0353c36b`. Other column per Brent 19 Oct built in Z28, not live
- CE #21 | Excess as a 125 line | LIVE VERIFIED | `0353c36b`. Z28 row re-order not live
- CE #22 | Best Solutions before forms | WAITING ON BRENT | 23 Oct Q1: keep or hide each after-forms item (re-ask item by item). Pre-form part live on `0353c36b`
- CE #23 | Location edits not saved | LIVE VERIFIED | Render (AUDIT 15 Oct)
- CE #24 | Pills on form names | LIVE VERIFIED | localhost
- CE #25 | Upload after forms; exclude | BUILT, NOT LIVE-VERIFIED | Notes conflict: the 15 Oct audit found the exclude defect; Z37-A (24 Oct) found it already fixed at HEAD (`df3e981`). Live recheck owed
- CE #27 | 176 items, hard stops at the end | PARTLY BUILT | download screen right (Z20/Z22). Raising these items at the start is unmet; waits on Q1/Q4
- CE #26 | Exposure score looks wrong | BUILT, NOT LIVE-VERIFIED | "-N pts" rows were seen live. Brent's 19 Oct "Exposure = conflicts only" built in Z28 C
- CE afterthought | Stale tab showed old screens; version/reload banner | NOT BUILT - OURS | part A. Fix proposed; no version.json found in the frontend

### Orbin, 22 Sep (Michelle's 22 points)
- Orbin 22 Sep #1 | Package page / "Continue where you left off" | LIVE VERIFIED | localhost R8 (1 Oct); owner confirmed again 14 Oct (Z12)
- Orbin #2 | Score before forms | LIVE VERIFIED | Render `5eb5b23c` pre-form (Z24). Z35's one-number-after-forms not live
- Orbin #3 | Remove "Important" | LIVE VERIFIED | `bfa8711d`
- Orbin #4 | Proposed dates from the dec | LIVE VERIFIED | Render `5eb5b23c`: rolled to 07/15/2027, "Please verify" (Z12/Z24)
- Orbin #5 | "Contacts are in the dec" | DECLINED / BY DESIGN | owner, 1 Oct: the dec prints no contact. Michelle still not told (Z31-N)
- Orbin #6 | "Open to fix" on the driver warning | LIVE VERIFIED | Render `5eb5b23c` (driver CSV cleared it)
- Orbin #7 | Page-one carrier; agency phone | BUILT, NOT LIVE-VERIFIED on Orbin | Brent's 8 Oct rule is live on CE `0353c36b`. Michelle's account still has no Contact Phone / Agency Address
- Orbin #8 | Premiums did not attach | BUILT, NOT LIVE-VERIFIED | Umbrella/IM expiring premiums now go to the Other column + ACORD 101 (Z28)
- Orbin #9 | Missing / verify list in the side panel, earlier | LIVE VERIFIED | `bfa8711d`. Z35 removed "AI held back", not live
- Orbin #10 | Obvious Edit; double-click | LIVE VERIFIED | `bfa8711d`
- Orbin #11 | Policy period and premium | BUILT, NOT LIVE-VERIFIED | dates live (as #4); premium half as #8
- Orbin #12 | Tenant, not owner; revenue "$0" | DECLINED / BY DESIGN | owner, 1 Oct. Michelle not told
- Orbin #13 | GL code, SIC, NAICS; FEIN | LIVE VERIFIED | GL codes on Render `5eb5b23c`. SIC/NAICS blank and flagged per Brent 8 Oct
- Orbin #14 | Send 125 to client; applicant signature | LIVE VERIFIED | localhost R9 (1 Oct). Question to Brent "do carriers accept the built-in signature?" never answered
- Orbin #15 | "No known losses" still counts | BUILT, NOT LIVE-VERIFIED | original fix live (`bfa8711d`); Brent's 23 Oct wording + business-age rule built Z35
- Orbin #16 | Resolved hard stop moves to Reviewed | LIVE VERIFIED | localhost (1 Oct board, Z16)
- Orbin #17 | Green "Client" boxes the producer filled | BUILT, NOT LIVE-VERIFIED | Notes conflict: Z18 (14 Oct) says verified live; the 15 Oct audit says "no trace". Took the audit
- Orbin #18 | Y/N not editable on 126/127 | LIVE VERIFIED | R10b, localhost. Client half declined by the owner
- Orbin #19 | Each item: what, how, score effect | LIVE VERIFIED | `bfa8711d`
- Orbin G1 | E-mail tagline | LIVE VERIFIED | `bfa8711d`
- Orbin G2 | Landlord name and address | LIVE VERIFIED | localhost `55325284` re-check passed (1 Oct night)
- Orbin Q | Questions counted apart from check items | LIVE VERIFIED | `bfa8711d`

Caveat from the 15 Oct audit: 0 of the 22 were seen on the Orbin package on Render with then-current code. Z24 then covered only the pre-form screen (2, 4, 6, 13, 15). Generation on that run was never reported.

### Brent, 8 Oct (part U)
- Brent 8 Oct U1 | Don't join two carriers in the top Carrier box | LIVE VERIFIED | `0353c36b` (blank + card)
- U2 | No expiring premiums on page 1 | LIVE VERIFIED | `0353c36b`
- U3 | SIC/NAICS blank and flagged | LIVE VERIFIED | `2076fe35`; `5eb5b23c`
- U4 | First landlord on 125, the rest as an ACORD 45 to-do | BUILT, NOT LIVE-VERIFIED | no 2+ landlord run recorded
- U5 | Don't carry a landlord to ACORD 25 | DECLINED / BY DESIGN | already the behaviour, no change

### Brent, 14 Oct (Z20)
- Brent 14 Oct #3a | Warning pre-form re-flagged as a hard stop after forms | LIVE VERIFIED | `0353c36b` (Z21)
- #3b | Download modal flooded with new flags | LIVE VERIFIED | `0353c36b` (Z22, rule held; 3 later fixes not live)
- #3c | "Hard stop" implies cannot move forward | BUILT, NOT LIVE-VERIFIED | readiness flag built Z28; caps kept (D72)
- #1C | List a policy whose premium is redacted | LIVE VERIFIED | `0353c36b` (EPL as OTHER row C)
- V2a | SQS independent of forms | BUILT, NOT LIVE-VERIFIED | Z35
- V2b | E&O fact lineage | PARTLY BUILT | source + page built Z28 B; nothing more found in the notes
- V2c | SMS sharing, captcha, Apple Pay, e-mail extraction via Transcriber | NOT BUILT - OURS | V2 roadmap

### Brent, 19 Oct (Z27; built in Z28)
- Brent 19 Oct R1a | Prior grid Other column = primary umbrella unless the agent picks | BUILT, NOT LIVE-VERIFIED | Z28 A
- R1b | Every other expiring policy on ACORD 101 | BUILT, NOT LIVE-VERIFIED | Z28 A
- R1c | Missing premium = blank + "Missing / Requires Confirmation" | BUILT, NOT LIVE-VERIFIED | Z28 A
- R1d | Page-1 Other rows = lines applied for | PARTLY BUILT | rule built; setting "lines applied for" in the review is still open (Z34-4)
- R2a | WC/EL on the 130; EBL with GL, never the 130 | BUILT, NOT LIVE-VERIFIED | Z28 B. The EBL premium goes on the 101, not the 126 (our decision)
- R2b | Extract WC classes, payroll, rates, mod, endorsements | PARTLY BUILT | endorsements built; rating-worksheet rows decided against (Z28 B)
- R2c | Source + page for every coverage and limit | BUILT, NOT LIVE-VERIFIED | Z28 B
- R3a | Search every document; no substitutes; blank + flag | LIVE VERIFIED | Period of Restoration warning, no EPI substitute, on `0353c36b`
- R3b | Few hard stops, only where essential | BUILT, NOT LIVE-VERIFIED | Z28 C (5 kinds)
- R3c | No automatic 60 cap; a hard stop blocks "Ready" | DECLINED / BY DESIGN | owner restored the 60/85 caps on 20 Oct (D72) and told Brent; the readiness flag is built
- R3d | Never penalise missing info twice; Exposure = conflicts only | BUILT, NOT LIVE-VERIFIED | Z28 C

### Choice Electric test, 17 Oct + attachments (Z29; built Z30-Z37)
- Brent 17 Oct item 1 | Excel won't upload | BUILT, NOT LIVE-VERIFIED | Z30; spreadsheet loss-run typing in Z37-C
- item 2 | Document review wording + type labels | BUILT, NOT LIVE-VERIFIED | Z30; Confirm-type button Z32
- item 3 | Review data shows unstated "False" | BUILT, NOT LIVE-VERIFIED | Z30
- item 4 | "Berger Owner of Choice Electric" as the company | BUILT, NOT LIVE-VERIFIED | Z30
- item 5 | Driver Excel mis-mapped | BUILT, NOT LIVE-VERIFIED | Z30 + Z31 Excel formats
- item 6 | One GL classification window | BUILT, NOT LIVE-VERIFIED | Z31-GL
- item 7 | "Explain via ACORD 101" confusing | BUILT, NOT LIVE-VERIFIED | Z36 questionnaire page
- item 8 | COPE hard stop asks twice | BUILT, NOT LIVE-VERIFIED | Z30
- item 9 | Empty officer rows repeated | BUILT, NOT LIVE-VERIFIED | Z30
- item 10 | Too much at the end | PARTLY BUILT | built: 131 warnings fix, "AI held back" removed, score independent of forms, GL window. Missing: shorter Please-verify list, moving form items earlier (Q1/Q4)
- Attachment A | Narrative questionnaire | BUILT, NOT LIVE-VERIFIED | Z36 phases 1+2
- Attachment B | Driver schedule file | BUILT, NOT LIVE-VERIFIED | = item 5
- Attachment C | Synthetic claims checks | PARTLY BUILT | Z31-C. Expense / date first made not read from loss runs (owner's call)
- B2 question | Upload the claims file's two copies separately, or read it whole? | WAITING ON BRENT | never actually sent (Z34-4)
- Request | His 16 simulated loss-run PDFs | UNCLEAR | no record that they were requested or received

### Brent, 20 Oct (Z29-1)
- Brent 20 Oct #1 | Effective-date hard stop only when none found/confirmed (backwards dates judged by source) | BUILT, NOT LIVE-VERIFIED | Z30
- #2 | Umbrella: the applicable underlying limits (EL and its own schedule count) | BUILT, NOT LIVE-VERIFIED | Z30
- #3 | Monopolistic WC: hard stop only with no acknowledgment | BUILT, NOT LIVE-VERIFIED | already matched; dead inputs cleaned Z30
- #4 | Hard stop only on verified information (identity stop) | BUILT, NOT LIVE-VERIFIED | Z30
- #5 | Forms Ready stays separate from SQS | PARTLY BUILT | package side Z35; per-form side waits on Q4

### Brent, 23 Oct (Z34; built Z35/Z36)
- Brent 23 Oct #1 | Score independent of forms; "Forms ready" meter | BUILT, NOT LIVE-VERIFIED | Z35-A
- #2a | "Unable to Verify / Confirmation Required" wording | BUILT, NOT LIVE-VERIFIED | Z35-A
- #2b | Loss runs measured against business age | BUILT, NOT LIVE-VERIFIED | Z35-A
- #3a | Excess 131 lists applicable GL / Auto / EL | BUILT, NOT LIVE-VERIFIED | Z35-B
- #3b | SIR or attachment point; review flag if neither | BUILT, NOT LIVE-VERIFIED | Z35-B
- #4 | More than six Other lines | BUILT, NOT LIVE-VERIFIED | Z28
- #5 | Partial 125 total when a premium is redacted | BUILT, NOT LIVE-VERIFIED | Z35-B
- #6 | State from insured evidence, per coverage | BUILT, NOT LIVE-VERIFIED | Z35-C
- Q1 | Keep or hide each after-forms item | WAITING ON BRENT | he asked us to clarify; re-ask item by item
- Q2 | Forms stop nudging the score | BUILT, NOT LIVE-VERIFIED | Z35-A
- Q3 | Refused AI values to the audit record only | BUILT, NOT LIVE-VERIFIED | Z35-C
- Q4 | Each form keeps its own score? | WAITING ON BRENT | his "TBD"
- Q5 | Simulated SQS from e-labels | NOT BUILT - OURS | reply owed; `form_dry_run` exists
- Q6 | Narrative questionnaire as its own page | BUILT, NOT LIVE-VERIFIED | Z36
- Q7 | Umbrella carried-but-unlisted line = warning | BUILT, NOT LIVE-VERIFIED | Z30
- Round-trip test (24 Oct) | Re-upload downloaded forms, expect 97 again | UNCLEAR | runs on the 15 Oct deploy; no result recorded; reply owed
- Form base expansion (800+) | Scale to the core forms via e-labels | WAITING ON BRENT | his core form list; timeline reply owed
- Vendor API keys | Address validation, narrative enrichment | NOT BUILT - OURS | security review first

### Michelle (Orbin re-test of 22 Sep, 11 items; v1-20AUG "ORBIN client re-test")
All 10 lines below were verified on Render run `1597ac25` (27 Sep) using our kit built from her OCR, not her own package. None has been re-run on Render since.
- Michelle 22 Sep re-test #1 | Glued company name read as two companies | LIVE VERIFIED | Render `1597ac25`
- #2 | Which lines are carried (one door) | LIVE VERIFIED | `1597ac25`
- #3 | Form numbers taken as policy numbers | LIVE VERIFIED | `1597ac25` (prefix-less number fixed later in Z32)
- #4 | Login agency is the producer | LIVE VERIFIED | `1597ac25`
- #5 / #10 | Comparisons only within one kind, line and term | LIVE VERIFIED | `1597ac25`
- #6 | Line-scoped generation on every path | LIVE VERIFIED | `1597ac25`
- #7 | ACORD 137 ticked with 127 | LIVE VERIFIED | `1597ac25` (Z35 state rule later changed the offer)
- #8 | Placeholder text fills no party box | LIVE VERIFIED | `1597ac25` ("FIO" fixed later in Z32)
- #9 | Umbrella reduction read from the run-together remark | LIVE VERIFIED | `1597ac25`; stays a conflict (owner)
- #11 | Policy-printed vehicle confirmed, not asked | LIVE VERIFIED | `1597ac25`
- M1 | Tell Michelle why Orbin 5 and 12 were declined | NOT BUILT - OURS | still on the Z31-N list

Michelle's five 15 Oct questions (F01 #7: Other column, six page-1 rows, page-1 total, EBL, values a dec never prints) are not separate lines: Brent answered all of them on 19 and 23 Oct.

### Totals
| Source | Live | Built, not live | Partly | Waiting | Not built (ours) | Declined / by design | Unclear | Total |
|---|---|---|---|---|---|---|---|---|
| Choice Electric 5 Oct | 17 | 8 | 1 | 1 | 1 | 0 | 0 | 28 |
| Orbin 22 Sep | 15 | 5 | 0 | 0 | 0 | 2 | 0 | 22 |
| Brent 8 Oct | 3 | 1 | 0 | 0 | 0 | 1 | 0 | 5 |
| Brent 14 Oct | 3 | 2 | 1 | 0 | 1 | 0 | 0 | 7 |
| Brent 19 Oct | 1 | 7 | 2 | 0 | 0 | 1 | 0 | 11 |
| Choice Electric 17 Oct + attachments | 0 | 11 | 2 | 1 | 0 | 0 | 1 | 15 |
| Brent 20 Oct | 0 | 4 | 1 | 0 | 0 | 0 | 0 | 5 |
| Brent 23 Oct | 0 | 12 | 0 | 3 | 2 | 0 | 1 | 18 |
| Michelle (re-test + M1) | 10 | 0 | 0 | 0 | 1 | 0 | 0 | 11 |
| **Overall** | **49** | **50** | **7** | **5** | **5** | **4** | **2** | **122** |

### What matters
- **Half the list is unproven live.** All 50 "built, not live" items sit on uncommitted code. None of Brent's 17, 19, 20 or 23 Oct asks has been seen working live. His 24 Oct round-trip test is measuring the 15 Oct build.
- **Real blockers on Brent:** Q1 (keep or hide each after-forms item, which also decides CE 22, CE 27 and part of 17 Oct item 10) and Q4 (per-form scores).
- **Owed by us, never sent:** the B2 claims-file question, the Q5 / form-base / API-key replies, and Michelle's explanation for Orbin 5 and 12.
- **One reversal Brent should see clearly:** the owner restored the 60/85 caps against his 19 Oct "no automatic 60 cap" (D72). He was told on 20 Oct and his reply did not object.
---

## Live test plan: Brent's 17-23 Oct items (to run on localhost, 25 Oct onward)

Package to use: a fresh Choice Electric upload (7 decs), or `c5dc03ec` (filled to 88, Loss History left). Restart the
backend and refresh the browser first. Tick each line as it passes; note the package id beside it.

### Before forms (review pages)
- [ ] 17 Oct #1 - Upload an Excel / CSV as a document: accepted (old .xls / macro files refused with a "save as .xlsx" message). A loss-run spreadsheet is typed "Loss Runs" on its own (Z37).
- [ ] 17 Oct #2 - A "Needs Verification" document shows "Some documents require review" and a Confirm type button; confirming does not re-read it.
- [ ] 17 Oct #3 - Review data popup shows no unstated "False" values.
- [ ] 17 Oct #4 - The applicant is "Choice Electric LLC", never "Berger Owner of Choice Electric".
- [ ] 17 Oct #5 / Attachment B - Import Brent's driver Excel into the driver table: every column lands in its own column.
- [ ] 17 Oct #6 - GL class codes open ONE classification window (no second GL card).
- [ ] 17 Oct #7 / Attachment A / 23 Oct Q6 - The Narrative questionnaire is its own page (last review page before form selection), pre-filled from the documents.
- [ ] 17 Oct #8 - The COPE hard stop asks each item once (2 buildings: table + Occupancy box above it).
- [ ] Attachment C - Upload the claims file: claims checks show as Loss History deductions / cards, never hard stops.
- [ ] 20 Oct #1 - No effective-date hard stop when a date was found or confirmed; backwards dates are a hard stop only when a person typed both.
- [ ] 20 Oct #2 / 23 Oct Q7 - Umbrella: underlying limits read per line (GL, Auto, EL); a carried line the umbrella schedule does not list is a WARNING.
- [ ] 20 Oct #3 - Monopolistic WC is a hard stop only with no acknowledgment.
- [ ] 20 Oct #4 - Name / FEIN hard stops only from verified sources.
- [ ] 19 Oct R3b - Only the five hard-stop kinds appear (different companies, no proposed term, property without COPE, monopolistic + private carrier, umbrella with no underlying).
- [ ] 19 Oct R3d - Exposure lists only real conflicts; missing details sit under Structural "Coverage Details".
- [ ] 23 Oct #6 - Recommended forms include 137_CO with the auto policy (garaging CO); hold the auto policy back and the state is ASKED, not guessed.
- [ ] 23 Oct #2a - Answer "No claims" with no loss runs: Loss History reads "Unable to Verify / Confirmation Required".
- [ ] 23 Oct #2b - A business younger than 5 years needs only its own years of loss runs for full credit.
- [ ] 19 Oct R2c - Policies table shows each policy's source document and page.

### Generate forms, then check
- [ ] 23 Oct #1 / Q2 - The package score is the same number before and after forms; a "Forms ready: N values to confirm, M boxes to fill" line replaces "With forms / Without forms".
- [ ] 23 Oct Q3 / 17 Oct #10 - No "AI held back" section anywhere; real gaps are Missing rows.
- [ ] 19 Oct R1a - ACORD 125 Prior Carrier "Other" column = the primary umbrella (an agent pick on the policies table changes it).
- [ ] 19 Oct R1b - Every other expiring policy (carrier, number, dates, limits, premium) prints on ACORD 101.
- [ ] 19 Oct R1c - A missing premium is blank + "Missing / Requires Confirmation", never $0.
- [ ] 19 Oct R1d / 23 Oct #4 - ACORD 125 page-1 Other rows are lines applied for; more than six go to ACORD 101.
- [ ] 23 Oct #5 - A redacted premium gives a partial 125 total plus a "total is partial" to-do.
- [ ] 19 Oct R2a - WC + Employers Liability on ACORD 130; Employee Benefits with GL, never on the 130.
- [ ] 23 Oct #3a - The excess ACORD 131 lists the applicable GL / Auto / EL underlying lines.
- [ ] 23 Oct #3b - Umbrella SIR OR attachment point; a review card only when neither is known.
- [ ] 17 Oct #9 - ACORD 130 officer rows: no empty rows repeated.
- [ ] 20 Oct #5 - Forms ready shown apart from the score.

### Still waiting (cannot be tested yet)
- Brent Q1 (keep or hide each after-forms item, also CE 22 / CE 27 / 17 Oct #10 rest), Q4 (per-form scores), the 800+ form list.
- The claims-file question (B2) was never sent to Brent.

---

## Next upload: the owner's full test script (written 25 Oct 2026)

Restart the backend, refresh the browser, upload the 7 Choice Electric decs as a NEW package. Note its id here: ______

### 1. Starting screen (check before answering anything)
- [ ] Score starts around 42 (43 minus the umbrella follow-form question). If very different, tell Claude the number before going on.
- [ ] Producer address = your Agency Address (Noida), not Amerisure's head office.
- [ ] Recommended forms: ACORD 141 shows as "Crime Section"; 160 is not offered; a second ACORD 131 (Excess) is offered.
- [ ] Data Consistency has no "two carriers on the umbrella" item.
- [ ] Recommendations list hydrant / fire department from the start.

### 2. Fill the pre-form pages (Overview, Hard Stops, Warnings, Recommendations except Loss History)
- [ ] Every item moves the score by the number it shows (the COPE hard stop shows +10, Carrier-Grade COPE +3).
- [ ] Each fixed item appears under "Resolved"; "Open again" brings it back with its value editable.
- [ ] Narrative: fill it in the narrative window. Use claims wording ("12 claims in the past five years, 4 open") so the mismatch test below works.

### 3. Loss History and the narrative mismatch
- [ ] Recommendations show 3 Loss History rows: "Any claims in the last 5 years?" (no number), "Record loss runs requested" (+4), "Upload loss runs" (+8).
- [ ] Open the claims question, pick "No claims": BEFORE saving, a warning shows under "Then:" ("your narrative says there were claims ...").
- [ ] Save "No claims": score held at 85 and the warning appears under Warnings.
- [ ] Change the answer to "Yes - we have had claims": warning clears, score back.
- [ ] Reverse test: replace the narrative's loss sentence (Narrative questionnaire page, remarks box L.6) with "no claims or losses in the past five years" while the answer is "Yes": the warning returns, worded the other way. Put the claims sentence back: it clears.
- [ ] "Record loss runs requested": +4.
- [ ] Upload Choice_Electric_Loss_Runs_2021-2024_TEST.csv, then Choice_Electric_Loss_Runs_Current_TEST.csv: each is typed "Loss Runs" on its own (no manual type change), a change message shows the years and score, the coverage strip reaches 5 of 5, score reaches 100.
- [ ] Exclude one CSV, then include it again: score and years go down and back up consistently.

### 4. Handwritten document
File: `Handwritten-note-mitchell.png` (repo root, Michelle's note dated 6/15/25). It says: met Eric Berger, owner of
Choice Electric; purchased the company Jan 2024 with an SBA loan; 23 employees; anticipated 25-26 gross sales $3.2M;
payroll $1.4M; all commercial electrical work, no residential; small sponsorship with the Denver Broncos.
Expect: applicant name STAYS "Choice Electric LLC" (Brent 17 Oct #4); ownership change read, not a new venture;
a value a PERSON typed (employees 28, the operations text) is not overwritten - so possibly no conflict shown for
those; $3.2M agrees; payroll $1.4M vs the WC class payroll $2,626,500 may be a Data Consistency item, never a silent
overwrite. Before testing, correct the operations description to commercial-only (the fill typed "commercial and
residential"). Record what it read right and what it missed.
- [ ] Upload the client's handwritten document (scan / photo, PDF or image). Check: it is read (not "Unable to Classify" with no text), its values appear where they belong (Overview / Data Consistency), a value that disagrees with the decs becomes a Data Consistency item rather than silently replacing it, and nothing on the page breaks. Note which values it read correctly and which it missed.

### 5. At 100, add Brent's Excel claims file (17 Oct Attachment C)
NOTE (25 Oct, measured in memory): Brent's xlsx holds 12 CONTROL claims + 12 CHALLENGE copies with the SAME claim
numbers; the reading keeps one copy per claim (the clean one), so no claims check fires - whether the two copies
should be compared is Brent's unsent question B2. To see the claims checks, ALSO upload
~/Downloads/Choice_Electric_Claims_CHALLENGE_only_TEST.csv (the 12 challenge rows only): expect Loss History cards /
deductions naming each planted mistake (report date before loss date, "NOT PROVIDED" dates, missing reserve,
incurred not adding up, Bldg 003, WC class 5403) - never a hard stop.
- [ ] Upload it: it should be typed "Loss Runs" automatically (spreadsheet claims listing).
- [ ] Expected: its claim rows are read; the claims checks (Attachment C) may add Loss History deductions or cards - so the score MAY drop below 100. Every new item must name what to do and its points; nothing should become a hard stop.
- [ ] Note the score before and after, and every new row it adds.

### 6. Then generate forms and run the "Generate forms, then check" list above.

---

## Live status - package f575160b (uploaded 25 Oct 03:24 IST), starting screen checked against the stored data

PASS = verified live on localhost on f575160b. LEFT = still to verify, with how.

### Choice Electric 5 Oct
- PASS #4 one ACORD 131 per umbrella layer (131 + 131 Excess offered)
- PASS #9 policies table: 10 policies (edit / add / remove: LEFT - use them on the table)
- PASS #26 Exposure charges only conflicts (Exposure 100, no missing-item deductions)
- PASS #21 excess its own layer, umbrella limit $5,000,000, no false carrier conflict
- LEFT #1 blank band under the header - scroll the PDF in the editor, then "Back to review"
- LEFT #7, #15, #20, #25 - after forms (premiums per line, EBL placement, 125 carrier box, exclude after forms)
- LEFT #27 - waits on Brent Q1

### Orbin 22 Sep - all 5 unproven items (#7, #8, #11, #15, #17) need an Orbin package run. LEFT.

### Brent 8 Oct - LEFT U4 (first landlord on 125, rest as ACORD 45 to-do) - needs a package with 2+ landlords.

### Brent 14 Oct
- PASS #3c readiness rides beside the score (submission_ready false, 1 open hard stop)
- LEFT V2a score independent of forms - after forms; V2b partly built

### Brent 19 Oct
- PASS R2c each policy's source file + page (Cyber: no page printed, none guessed)
- PASS R3b only the five hard-stop kinds (one: Minimum Viable COPE)
- PASS R3d Exposure = conflicts only
- LEFT R1a-R1d, R2a - after forms (125 prior grid Other column, ACORD 101 other policies, Missing / Requires
  Confirmation, page-1 Other rows, WC/EL on 130, EBL with GL)

### Choice Electric 17 Oct + attachments
- PASS #2 a not-high document type is flagged (the WC dec is "medium" - on screen: "Some documents require review" + Confirm type)
- PASS #4 applicant "CHOICE ELECTRIC LLC" (the handwritten note's "Berger owner of Choice Electric" must not change it - recheck after step 4)
- PASS #6 one GL classification fix
- PASS #7 / Attachment A narrative questionnaire page built
- PASS #8 COPE asked once (hard stop + Carrier-Grade, no duplicate)
- LEFT #1 Excel / CSV upload - the loss-run CSVs in the test script
- LEFT #3 Review data popup shows no unstated "False" - open it and look
- LEFT #5 / Attachment B - import Primble_Sample_Driver_Schedule_12-10:17:26.xlsx into the driver table
- LEFT #9 officer rows - after forms (ACORD 130)
- LEFT Attachment C - claims checks: upload Choice_Electric_Claims_CHALLENGE_only_TEST.csv (test script step 5)

### Brent 20 Oct
- PASS #1 no effective-date hard stop (date found: 01/01/2027)
- PASS #2 umbrella underlying read, no "no underlying" hard stop
- PASS #3 no monopolistic hard stop (Colorado)
- PASS #4 no identity hard stop from unverified sources
- LEFT #5 Forms ready apart from the score - after forms

### Brent 23 Oct
- PASS #2b loss runs required = min(5, business age)
- PASS #6 ACORD 137_CO offered from the insured's CO garaging
- PASS Q3 no "AI held back" on the review page
- PASS Q6 narrative questionnaire is its own page
- LEFT #1 / Q2 same score before and after forms + "Forms ready" line - after forms
- LEFT #2a "Unable to Verify / Confirmation Required" - answer "No claims" on a narrative that does NOT state claims
- LEFT #3a / #3b excess 131 lists GL / Auto / EL; SIR or attachment - after forms
- LEFT #4 >6 Other lines to ACORD 101; #5 partial 125 total (EPL premium is redacted here) - after forms
- LEFT Q7 umbrella carried-but-unlisted warning - not raised on this package (check whether it should be)

### Our own fixes checked the same run
- PASS 141 = Crime Section, 160 not offered; hydrant / fire listed from the start; Loss History rows claims-first
- FAIL -> FIXED (needs restart + a re-merge): producer address was Amerisure's head office again - it is printed
  on two lines ("26777 HALSTED ROAD" / "FARMINGTON HILLS, MI") and the check read one line; and Travelers' HQ sits
  under its logo "TRAVELERSJ". Both now recognised (`insured_scope.address_is_a_party_office`: an address across
  2-3 lines; the package's own carrier names; a short logo line above). Adding the loss-run CSVs re-merges the
  package, so the address should turn to your Agency Address then (after a backend restart).

Totals on this run: 21 client items PASS today; LEFT = after forms (16), screen / action checks (7), other packages (7), Brent (2).

### Added after the fill of f575160b (25 Oct, 42 -> 88, Loss History left)
- PASS 17 Oct #5 / Attachment B - Brent's driver Excel through the page's own import: 12 drivers, every column right, title lines skipped
- PASS 23 Oct #2a - "No claims" on a narrative without claims -> "Unable to Verify / Confirmation Required"
- PASS 23 Oct Q7 - umbrella carried-line warning correctly NOT raised (every scheduled line has its limit)
- Fill: every step moved what it showed (COPE hard stop shown +10 moved +13 only because the fill script also typed
  the year-built / roof columns that belong to the Carrier-Grade card; narrative shown 7 moved 6 = rounding)

### Pre-form, completed 25 Oct night (f575160b at 100)
- PASS CE 5 Oct #9 policies table edit / add / remove (real routes; auto row restored after a loss-run bug fix)
- PASS 17 Oct #1 Excel / CSV uploads (CSVs, Brent's xlsx, CHALLENGE CSV all typed Loss Runs)
- PASS 17 Oct #3 Review data shows no "False" / invented fields
- PASS Attachment C claims checks 9 of 9, then corrected in the loss table (new columns) -> 100
- PASS Resolved + "Open again" (percent subcontracted: 100 -> 98 -> 100)
- PASS questionnaire pre-fill from the handwritten note (B.1e ownership change)
- PASS 17 Oct #5 driver Excel import - live by the owner: 12 drivers, every column right, no duplicates, score stays 100
- ON A COPY ONLY: 23 Oct #2a "Unable to Verify" (needs a package whose narrative does not state claims)

---

## After forms - package f575160b, first generation (25 Oct night, before the Z41/Z42 fixes)

Verified LIVE on the generated forms:
- PASS 23 Oct #3a excess 131 lists GL / Auto / EL underlying (+ the umbrella row as attachment)
- PASS 23 Oct #3b SIR or attachment (retention blank; the umbrella row stands as the attachment)
- PASS 19 Oct R2a WC + EL on ACORD 130; no Employee Benefits on the 130
- PASS CE 5 Oct #15 Employee Benefits with GL on ACORD 126
- PASS CE 5 Oct #20 125 CARRIER box blank + "carrier receiving this submission" card
- PASS CE 5 Oct #5 130 audit "At expiration"
- PASS 17 Oct #9 no repeated officer rows on the 130 (no officer rows on this package - weak)
- PASS 20 Oct #5 Forms ready data present (screen not looked at)

FAILED, then FIXED offline (Z41 / Z42) - verify on the REGENERATED forms:
- 23 Oct #1 / Q2 same score before and after forms (100 -> 85 from the ACORD 186 form-choice check; now package-only deferral)
- 19 Oct R1a 125 prior grid Other = umbrella (garbled carrier, 2021 dates)
- 19 Oct R1b ACORD 101 other expiring policies (fake limit-label rows, policies missing, EBL listed)
- 19 Oct R1c "Missing / Requires Confirmation" on premiums the documents state
- 19 Oct R1d page-1 Other rows (Employee Benefits row)
- CE 5 Oct #7 prior grid premiums

Not exercised by this package: 23 Oct #4 (>6 Other lines), 23 Oct #5 (partial total - renewal withholds page-1 premiums).
Not tested yet (owner): CE #25 exclude a document after forms; CE #1 blank band after the editor.

Totals: 41 verified live (33 pre-form + 8 after forms); 6 fixed awaiting regeneration; 2 not exercised; 2 owner
actions; 1 on a copy only (23 Oct #2a).

Owner decisions 25 Oct night: ACORD 28 keeps the expired 2025-26 term; ACORD 141 gross receipts prints the revenue.
Known gaps (not fixed): 127 physical-damage deductibles on vehicles without that cover (needs per-vehicle charges
from extraction); 130 per-period loss totals blank; "Add ACORD 186" after forms only in the editor (not the review
page); a stated $0 premium reads "Missing / Requires Confirmation".

---

## Live status - package ff2ba3e5 (re-upload 25 Oct 13:08 IST), pre-form, filled through the real routes

Start 42 (same as f575160b); every pre-form item re-checked on the stored data: 22 PASS today (CE 5 Oct #4 #9 #21 #26;
14 Oct #3c; 19 Oct R2c R3b R3d; 17 Oct #2 #3 #4 #6 #7 #8; 20 Oct #1-#4; 23 Oct #2b #6 Q3 Q6). Producer address = Agency
Address (failed at the start of the last run).

Fill: 42 -> 83 (all pages but Loss History / narrative) -> "No claims" 93 -> narrative stating 12 claims 85 (mismatch
warning) -> "Yes, claims" 88 -> loss runs requested 92 -> 2021-2024 CSV 97 (4 of 5 years) -> current CSV 100 (5 of 5) ->
note 85 (payroll $1.4M vs $2,626,500 Data Consistency pick) -> confirm 100 -> Brent's xlsx 95 -> CHALLENGE CSV 95 (folds
into CONTROL, B2) -> xlsx excluded 94 (9 of 9 planted mistakes) -> corrected in the loss table 100. Every step moved what
it showed.
- PASS LIVE 23 Oct #2a "Unable to Verify / Confirmation Required" (was copy-only)
- PASS narrative / claims mismatch warning (85, released by the truthful answer)
- PASS edge: another company's loss run (Harborline) -> name + FEIN hard stops, score held; excluded -> back to 100
- PASS edge: re-including Brent's xlsx keeps the corrected claims (100, 14 rows)
- PASS edge: driver Excel uploaded as a document beside the typed 12 drivers - no duplicates
- PASS edge: "Open again" after the document set changed is refused (changed_since), nothing undone
- PASS note: applicant unchanged, ownership change read, no invented Yes / No, typed "unknown / low" (was loss_run)

Bugs found and fixed (offline, tests in tests/test_z43_live_ff2.py):
1. agreed_value_endorsement = False although the Package dec lists "Coverage Option(s): AGREED VALUE" (ACORD 28 ticked
   Agreed Value No last run); also "agreed" matched "agreement" in the auto dec. Fixed in drop_unmentioned_ai_yes_no.
   Reaches NEW uploads only - this package keeps the stored False (a re-merge never rewrites it): untick on the 28.
2. Loss History label "No Known Losses attested - left out of the score" beside a SCORED 25 when the narrative says
   claims - the label now follows the scorer (sqs_service._get_loss_history_state).
3. Loss-run ownership check stopped at the first matching run - a later run of another company went unchecked
   (loss_run_identity, no early stop).
Noted, not fixed: the note's own reading says "Residential and commercial" (handwriting OCR "NO" -> "MO"; package keeps
the typed value); per-period summary rows show as rows in the review loss table (kept out of counts and forms);
loss_history_years fact reads 4 while coverage reads 5 of 5 (coverage is what the screen uses).

### Updated totals after f575160b + ff2ba3e5 (25 Oct, afternoon)
122 items: 84 done live, 5 declined / by design, 33 left. Left = 8 after-forms (regenerate ff2ba3e5), 2 owner actions
(CE #1, CE #25), 7 need another package (Orbin #7 #8 #11 #17, U4, 23 Oct #4 #5), 8 waiting on Brent (CE #22 #27,
17 Oct #10, B2, 20 Oct #5, Q1, Q4, form base), 8 ours (V2b, V2c, R2b, 16 PDFs request, Q5, round-trip reply, API keys, M1).
Changed to done since the table above: CE #4 #9 #15 #20 #26, Orbin #15, 14 Oct #3c, 19 Oct R2a R2c R3b R3d, all of
17 Oct except #10 / B2 / the PDF request, 20 Oct #1-#4, 23 Oct #2a #2b #3a #3b #6 Q3 Q6 Q7. CE afterthought (version
banner) dropped by the owner -> declined.

---

## Live run 85e51d02 (fresh upload 25 Oct ~14:25 IST, backend restarted) - pre-form, every step through the real routes

Start 42, 23 of 23 start checks PASS, Agreed Value now correct (True - the Package dec lists it). Path: fill 42 -> 83 ->
No claims 85 (Unable to Verify) -> narrative with claims (mismatch warning, label "Claims known") -> Yes -> requested ->
2021-2024 run 97 -> current run -> other company's run (name + FEIN hard stops) -> excluded -> note (payroll warning) ->
confirm -> Brent xlsx -> CHALLENGE -> xlsx excluded (9 of 9) -> corrected -> xlsx included 100 (5 of 5, 2021-2025) ->
driver xlsx -> driver xlsx out / in -> Cyber dec out / in: 100 throughout. "No claims" against the loss runs: with a
narrative the mismatch warning (85); without one 45 "Conflicting" (checked on a copy). Both correct.

Bugs found on this run, all fixed (tests/test_z43_live_ff2.py, related files green):
1. "Submission Program Name: documents disagree" - the Cyber and EPL decs' product names read as the submission's
   program; capped 85, 15 points unplaced. A dec page no longer supplies submission program / underwriter. LIVE: cleared.
2. Review data printed "True" / "true" - now Yes / No. LIVE.
3. Coinsurance missing on this run although every coverage prints 80% - derived from the property schedule when the
   model leaves it (and valuation). Reaches new uploads.
4. The coinsurance box refused "80%" (every percent box refused the % sign). LIVE: saved.
5. A loss run whose period was read as bare years ("2021" - "2025") counted 0 years (stuck at 97). LIVE: 5 of 5.
6. Coverage label read "(2020-2024)" for a period ending 31 Dec 2025. LIVE: "(2021-2025)".
7. Brent's driver Excel (title "COMMERCIAL AUTO") gave vehicle use = commercial -> a Data Consistency pick, 85. A vehicle
   use counts only beside a "Use" label. LIVE: driver file out / in, no conflict, 100.
Known, not fixed: the handwritten note's own reading says "Residential and commercial" (handwriting OCR "NO" -> "MO";
the package keeps the typed value); per-period summary rows show in the review loss table (not counted, not printed);
the auto policy row is named "Auto Liability" this run ("Commercial Auto" before); the EPL dec's "Coverage(s)
Applicable" menu puts D&O / Fiduciary / K&R in the questionnaire's lines-of-business answer.

### 85e51d02 after forms (first generation, 25 Oct afternoon)
Package 100 -> 100 after forms (23 Oct #1 / Q2 PASS). PASS: R1a, R1b, R1c, R1d, CE #7, CE #20, 23 Oct #3a / #3b,
R2a, CE #5, 17 Oct #9 (weak), 17 Oct #5 (12 drivers), 141 / 28 owner decisions, Forms ready data (75 / 100).
Wrong values found and fixed (show on the NEXT generation): 125 years of loss history 4 (page says 5); 125 contact
type "Inspection"; 130 "employees under 16 / over 60" Yes with a driver row; 130 other-insurance explanation = the
dec's coverage menu (now follows the 125's rule); 126 GL PD deductible $5,000 (property's) + tick; 126 type of work
subcontracted = insurance sentence; 28 wind / hail and named windstorm LIMITS "2%"; 140 inflation guard 80%; 140
other improvement year = roof year; excess 131 retention listed Missing although its attachment is known; Add
documents panel had no Cancel. Kept (checked): named windstorm deductible 2% (Z42 B). Suite 20,403 / 1 / 19.
- Add documents Cancel button: VERIFIED LIVE by the owner (25 Oct afternoon).

---

## Live run bcfd175b (fresh upload 25 Oct ~16:26 IST, backend restarted) - full pre-form script + Michelle checks

Everything from the 85e51d02 run repeated, all PASS: start 42 (23 / 23, Agreed Value right, no program conflict, plan
adds up, coinsurance read), fill 42 -> 83 (every step moved what it showed), No claims 93 (Unable to Verify), narrative
mismatch 85 + "Claims known" label, Yes 88, requested 92, older run 97 (4 of 5), current run 100 (5 of 5, 2021-2025 -
bare-year fix live), Harborline hard stops -> excluded 100, note -> payroll warning -> confirmed 100, Brent xlsx 95,
CHALLENGE folds (B2), xlsx out 94 with 9 of 9, corrected 100 (+6), xlsx back 100, driver xlsx 100 (no vehicle-use
conflict - fix live), driver / Cyber out-in 100, No claims vs runs 85 then 100. Review data clean on 14 documents.
Michelle checks: FEIN "abc", phone "12345", date "13/45/2026", revenue "TBD", employees "lots", coinsurance 150% all
refused with clear messages; Cyber premium edit / restore; add + remove a policy line (the page's id); Open again right
after a fix restores the old value; the same CSV twice -> 409 "already in this package"; an unrelated spreadsheet ->
unknown / low, nothing read; Package dec out -> 60 (property still typed, values gone) -> back in 100.
Bugs found, fixed: "-3" years in business saved as 3 (a negative number is now refused, "This can't be a negative
number"); a "TBD" narrative said only "Could not save the explanation" (now says why). By design: "N/A" as revenue
is an answer ("there is none") and clears the value.
Noted: with the Package dec excluded, 15 points were not placed on any row (a transient state; back to 100 on include).

### bcfd175b after forms (25 Oct evening)
Package 100 after forms. The 11 form fixes from 85e51d02 all hold on the new forms (125 years 5; 130 age question /
other-insurance blank; 126 PD deductible + tick, type of work blank; 28 2% limits blank; 140 inflation guard / other
year blank). Found and fixed: 125 contact type "Full Name" (a column heading; field labels refused); 28 equipment
breakdown deductible $500 (the policy-wide deductible; the schedule prints $5,000 - section amounts now judged when the
documents name the coverage); a premium typed back to the documents' own value stayed a person edit and printed on
ACORD 125 page one (now clears the edit - verified live: Cyber $4,162 left page one, package 100). Michelle checks:
"-3" refused ("can't be negative"), a "TBD" narrative now says why. Known, left: 127 garaging state blank on this run
(the AI put "CO" in the street line; fleet garaging is the document's by an earlier review decision); 137 hired PD
"primary" tick (P15 X1); 137 specified-causes deductible 1,000 (per-vehicle detail, needs Brent / a closer read).
- Suite after the bcfd175b fixes: 20,407 passed, 1 failed (the known test_arq_acord125_missing_only), 19 skipped. CE #25 exclude after forms: PASS (2021-2024 loss run excluded, score 100, totals and years correct, no form box moved). Re-including Harborline correctly asks 'names a different insured'.
- bcfd175b: owner confirmed Harborline as 'same insured' -> name + FEIN Data Consistency hard stops, 60, nothing overwritten (correct). Bug found + fixed: the FEIN conflict was drawn TWICE as hard stops (picker card + legacy 'FEIN differs across uploaded documents'); issue_registry._LEGACY_SUPERSEDED_BY_CODE now folds it (test_stop_visibility_c75 harvests the Data Consistency codes too). Verified on the package: 2 hard stops.
- bcfd175b after forms, Data Consistency confirm (applicant CHOICE ELECTRIC LLC, FEIN 84-1234567) via confirm-value-in-editor: hard stops cleared, 0 form boxes moved. Bug found + fixed: the confirmed FEIN (source user_confirmed) was not a FEIN witness for the loss-run match (only TYPED values were), so both Choice Electric loss runs fell strong -> possible and Loss History 100 -> 85 (score 97). loss_run_identity now uses fact_state.confirmed_by_person. Re-scored live: 100, both runs strong, Harborline no_match. Server restarted on the fix.

## Live run e66d68d7 (fresh upload 25 Oct ~18:40 IST) - full pre-form script + Harborline confirm path + Michelle checks
ALL PASS: start 23 / 23 (Agreed Value, no program conflict, Review data); fill 42 -> 83; No claims 93 (Unable to Verify);
narrative mismatch 85 + "Claims known"; Yes 88; requested 92; runs 97 -> 100 (5 of 5, 2021-2025); Harborline -> name +
FEIN stops (FEIN once) -> confirm CHOICE ELECTRIC LLC / 84-1234567 -> loss runs stay STRONG -> excluded 100; note ->
payroll warning -> 100; Brent xlsx + CHALLENGE 9 of 9 -> corrected 100; driver xlsx (no vehicle-use conflict); driver /
Cyber out-in 100; No claims vs runs 85 -> 100. Michelle: bad inputs refused (incl. "-3" negative, "TBD" narrative
message), Open again, duplicate 409, junk file unknown / nothing read, Package dec out 60 / in 100.
Bugs found + fixed this run: questionnaire H.1c listed every policy as umbrella underlying (now GL / Auto / EL via
umbrella_layers.applicable_underlying_lines); a premium typed back to the documents' value after an edit stayed an edit
BEFORE forms (the re-merge writes the edit into the facts) - the documents' value is now recorded with the first edit
(`originals`) and compared against; verified live in every order. Package left at 100 (test line removed, revenue
restored, movie file excluded). Server restarted on all fixes.

### e66d68d7 after forms (25 Oct night)
Brent's after-forms items all PASS (score 100 -> 100; prior grid GL $16,818 / Property $6,275 / Other = Umbrella
$17,082; ACORD 101 Excess, WC, Cyber, IM, Crime, EPL "Missing / Requires Confirmation"; page-1 Other rows Excess + EPL;
carrier box blank; excess 131 GL / Auto / EL + umbrella attachment; 130 WC + EL, At expiration; 126 EBL; 12 drivers).
The 14 earlier form fixes: 14 / 14 PASS. New bugs found + fixed (each tested):
1. Package Policy rows lost their carrier (the model wrote the carrier entry as a heading) -> GL / Property out of the
   125 grid. A heading-shaped carrier entry counts, still confirmed by the page header (assign_document_carrier_to_rows).
2. Chubb EPL dec read as a 7-part menu -> EPL off the 101 / page one, a D&O "policy". The part with its own section
   (limit) is the document's line (_sources_are_own_declarations + _part_has_own_section); menu-only parts dropped
   per document (drop_menu_only_parts).
3. ACORD 141 insurer blank (the menu's Crime vs Amerisure's) - cleared by #2.
4. "Eric Berger" (the owner the note names) as additional interest #2 on the 28 / 126 / 127 / 140 - refused unless a
   document names him in an interest role (REASON_OWN_PARTY_AS_INTEREST); the row's other AI boxes go with it.
5. ACORD 130 Non-participating ticked beside "Blue I (B1) Dividend Plan" - a stated dividend plan ticks Participating.
1-3 verified on the package after a re-merge (141 Amerisure, grid / 101 / page one right, 100). 4-5 show on the next
generation. Server restarted on all fixes.
- FINAL suite 25 Oct night (after all e66d68d7 fixes): 20,415 passed, 1 failed (the known test_arq_acord125_missing_only), 19 skipped. Ready to report to Brent as tested on localhost (not deployed).

### Brent items from 17 Oct onwards - status on the last run e66d68d7 (49 items)
30 passed with no bug on the last run (5 of them fixed earlier the same day: 17 Oct #3, #5; 23 Oct #2a, #2b, #3b);
5 failed on the last run and were fixed + re-verified (17 Oct #7 / Att. A questionnaire H.1c; 19 Oct R1b, R1c, R1d);
2 built but not exercised by this package (23 Oct #4, #5); 12 not done / partial: 17 Oct #10 (Brent Q1 / Q4), B2 and the
16-PDF request (ours to send), 19 Oct R2b (rating rows decided against), R3c (declined - caps kept), 20 Oct #5 (per-form
waits Q4), 23 Oct Q1, Q4 (Brent), Q5 (reply owed), round-trip (reply owed), form base (Brent), API keys (security review).
Nothing deployed at the time; owner pushed commit 845e250 on 25 Oct night (GitHub secret alert - see 25sepChanges Z43).
- LIVE 654f34c4 (primble.ai, 25 Oct night, owner-driven): pre-form flow A/B passed (42 -> 100, mismatch both ways, loss runs 4 -> 5 of 5, Harborline). Bug found: the handwritten note's Review data showed Business Start Date 2024 = the PURCHASE year ('purchased the company in January of 2024'); the start feeds business age -> loss years required. Fixed locally (extraction_service.drop_purchase_year_as_start, test in test_z43_live_ff2.py, 3,402 related tests green) - NOT deployed. Note: local scripts cannot read/write live packages (Render's FIELD_ENCRYPTION_KEY differs) - live checks are owner-driven + read-only per-document data. Edge files EDGE1-5 created in ~/Downloads for C1-C6.

## FINAL - live package 654f34c4 on primble.ai (deployed 25 Oct night), forms generated
26 / 26 form checks PASS on the live forms (all earlier fixes incl. owner-not-additional-interest, 130 participating,
141 insurer, 125 grid / page one, 101 list with EPL Missing / Requires Confirmation). Package 100 before and after forms.
Brent's 49 items from 17 Oct onwards: 27 verified LIVE on primble.ai; 8 verified on localhost only (17 Oct #7, Att. A,
Att. C; 19 Oct R2c, R3d; 20 Oct #4; 23 Oct Q3, Q6 - not exercised on the live package); 2 built but not exercisable with
this package (23 Oct #4, #5); 12 not done / partial (17 Oct #10, B2, 16-PDF request; 19 Oct R2b, R3c declined; 20 Oct #5;
23 Oct Q1, Q4, Q5, round-trip, form base, API keys). Several passed only after fixes made during 25 Oct testing (see Z43).
- Download screen (live 654f34c4): summary said 'no material risk drivers' beside the high-loss-frequency advisory -> FIXED locally (C111: advisories passed to the summary prompt). 'Specify GL form type' card is CORRECT (no document states occurrence / claims-made) - no change. Suggested Brent proposal for the download screen (17 Oct #10 / Q1): show quote-blocking items first, fold optional Y/N questions per form, hide additional-interest blanks without an interest, count values-to-confirm and signatures. Both fixes need a push + deploy.
- Download screen after deploy (live 654f34c4, 25 Oct night): two ACORD 140 "roof material" HARD STOPS on a package at 100 with no hard stop.
  Cause: the old Figure 35 ACORD 140 gate blocked on year built / roof material / protection class; Minimum Viable COPE
  needs only construction type (+ building/BPP value), and Brent 19 Oct says roof info missing = blank + flag. FIXED locally:
  `pdf_service._ACORD140_GATE_HARD_FIELDS` = construction type only; the rest are Missing rows (`missing_required`).
  Then (owner: "do it"): the premises value rows too - a download now blocks ONLY on a placeholder value or ACORD 140
  construction type (Minimum Viable COPE, already a review-page hard stop). `field_qa._gate_still_blocks` reads today's rule,
  so forms generated before the fix stop blocking without a re-stamp. 17 tests that pinned the old rule updated (test was wrong). Needs push + deploy; old forms keep their labels until regenerated
  or re-stamped. Rest of that screen checked: correct per the documents (no premises address / roof material in any dec,
  EPL + auto premiums redacted); the 84-row list is the 17 Oct #10 / Q1 proposal waiting on Brent.
