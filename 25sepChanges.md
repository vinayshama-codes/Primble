# 25sepChanges - Orbin client feedback and our re-run

**Status (1 Oct 2026) - read this first, it is the honest picture:**
- The client's test document has **22 points**: 19 numbered items plus G1, G2 and Q. Where they stand after the
  owner's fresh runs of 1 Oct (sessions `359b36b0` and `69687a55`, section 6, "Third results" / "Fourth results"):

  **CORRECTED 1 Oct night by an independent audit** (8 reviewers + a critic, graded on the live sessions and the client's own
  screenshots - section 6, "Independent audit"). The earlier "17 of 22 verified live" OVERCLAIMED: several points meet only
  part of what Michelle wrote.

  | Verdict | Count | Items |
  |---|---|---|
  | Done and seen working on localhost | **11** | 3, 4, 6, 8, 9, 10, 11, 15, 16, 19, G1 |
  | Partly done | **7** | 2, 7, 13, 17, 18, G2, Q |
  | Declined - must be explained to Michelle | **2** | 5, 12 |
  | Not started (owner: not yet) | **2** | 1, 14 |

  (9 and 19 moved up on the owner's retest of 1 Oct, session `bfa8711d` - see below.)

  **Fix round after the audit (1 Oct night) - DONE OFFLINE:** every wrong value on the audit's list is fixed (GL limits
  = umbrella, Emcasco as co-owner, CBD, "20" years, unsupported Yes / No answers, the Sign button on the applicant's line)
  and the point fixes for 3, 4, 9, 10, 16, 17, 19, Q and G1 are in - proven on tests, 34 stored sessions (no score moved,
  no correct value lost) and the FR125 kit (312 of 312 held). **Not yet seen live**: the verdicts above change only after
  the owner's retest (section 6, "Retest after the fix round"). The GL-limit and 7383 fixes need a FRESH upload.

  **The owner's retest, 1 Oct (session `bfa8711d`, a fresh upload): PASSED** on every audit wrong value (W1-W9), typed
  edits, the Sign button, the side panel's reasons and points, the cover's rows and score, the questionnaire's split
  summary and "Check if none". It found four more defects (ACORD 126 LOC # printed the street number "4800"; the cover's
  lower-case agent name, raw form ids and an "up to +7 pts" beside the panel's "+7 pts") and one script miss (the side
  panel listed the applicant's signature under Missing) - all fixed offline, plus the owner's three changes. Short
  retest R1-R5: section 6, "Retest results - 1 Oct".

  **None of it is on the client's server** (see below). Do not show the client "fixed" until the retest passes,
  everything is committed and deployed, and a run on Render passes.

- **"Verified live" means:** on the owner's localhost, with the client's own 271-page dec. Part 2 generated ACORD 125,
  126, 127, 131 and 186. Michelle has not re-tested anything.
- **Nothing is committed and nothing is deployed.** 91 paths carry local changes (63 edited, 28 new) on top of `c69b4cc`,
  and `c69b4cc` itself (28 Sep) is not pushed: the remote branch is at `8b005ad` (27 Sep). **The client's server shows
  none of this work** until it is committed, pushed and deployed. **Add every new file explicitly** - three are imported
  by running code and a commit without them breaks the backend at start: `backend/services/signature_boxes.py`,
  `backend/services/needs_attention.py`, `backend/services/premises_interest.py` (and the frontend's new
  `utils/keyDetailCards.js`, `utils/viewerBoxes.js`, `utils/reviewedStops.js`, `utils/needsAttention.js`,
  `review/KeyDetailsMissing.jsx`, `NeedsAttentionPanel.jsx`, `usePdfFieldFocus.js`, `PDFJsViewer.css`).
- Full backend suite: **11,534 passed / 1 failed / 19 skipped** (1 Oct, after the R1-R5 fixes; the one failure is the
  known, pre-existing `test_arq_acord125_missing_only`). The frontend builds clean, with no new lint warning.
- The board below gives each point's verdict, what is true today and what is still open.

How this file works:
1. **Status board** (just below) - where every point stands today.
2. **Section 1** - the baseline: our fresh run of the client's own declarations, before any change.
3. **Section 2** - the client's test document (`Orbin_Testing_09_22_2026.pdf`), item by item, with
   what the baseline run showed for each one.
4. **Section 3** - other problems the baseline run shows that the client did not list.
5. **Section 4** - what the client wants (to be added when the owner sends it).
6. **Section 5** - the fix plan and the decisions.
7. **Section 6** - the fix log, the reviews and the live checks, in order (Step 1, Step 2, items 9 / 10 / 16 / 18 / 19).

---

## Status board (1 Oct 2026 - the audit's verdicts, moved only by the owner's retest of `bfa8711d`)

Verdicts are the independent audit's (section 6, "Independent audit"), moved only where the owner's retest of 1 Oct
(session `bfa8711d`, section 6, "Retest results - 1 Oct") showed the point working: 9 and 19 moved up. "Seen live"
below names the retest ID; anything else is proven offline only (tests, replays of 34 stored sessions, the FR125 kit).

| # | Client's point (short) | Verdict (audit) | What is true today | Still open |
|---|---|---|---|---|
| 1 | Opening a package should land on the package profile ("Continue where you left off") | **Not started** (owner: not yet) | Before forms the dashboard opens the review page; once a form exists it opens the editor and the review page cannot be reached again | Plan (Michelle Q1): profile, "Continue where you left off", started forms under Key Details |
| 2 | A score before forms are generated | **Partly done** | The pre-form screen shows "NN / 100" and the tier "so far" (seen live) | The wording is still forms-first ("It can change when forms are generated", "continue to form selection", dashboard "SQS -"); the score moves at generation (64 -> 66) with no input. Not in this round |
| 3 | Remove the "Important" block | **Done, seen working** | A missing key detail that has its own card is said ONCE, on the card; the key-details line counts it ("1 more under Warnings") - seen live on `bfa8711d` (U2) | - |
| 4 | Proposed dates from the dec | **Done, seen working** | A calculated box (the proposed term) is "Please verify": "Calculated, not read from your documents" - seen live on `bfa8711d` (P3) | The effective date is already past on a QUOTE (an older dec; the owner's 29 Sep rule) |
| 5 | "Contacts are in the dec" | **Declined - explain** | The dec prints no insured contact (all 271 pages) | Ask Michelle whose contact she means (Erin Royal? the producer?) |
| 6 | "Open to fix" on the driver warning | **Done, seen working** | Fix round: an offline end-to-end proof (125 alone: the card's table is served, one saved driver is stored, the warning clears) | - |
| 7 | Page-one carrier; the dec agency's phone | **Partly done** | Both EMC companies print on CARRIER; fix round: always in the same order (alphabetical) | Brent has not approved two carriers. Michelle's account has NO Contact Phone (set it before her run). Producer mailing address blank |
| 8 | Premiums did not attach, no prompt | **Done, seen working** | Line premiums and POLICY PREMIUM print; a blank one is a Missing row. Fix round: the list opens by default; a typed premium prints "3,418" (with cents too) | They are the EXPIRING premiums (Brent not asked) |
| 9 | Missing / required / verify in the side panel, earlier | **Done, seen working** (moved up 1 Oct) | Side panel per form; pre-form key details clickable. "AI held back" never repeats a refused answer - seen live on `bfa8711d` (P2). After the retest (owner): both lists start CLOSED like every other section; the applicant's steps are their own group | R2: the owner's layout change, not yet seen |
| 10 | Make Edit obvious; double-click to edit | **Done, seen working** | Typed edits are saved before a form switch, a fix window, a download or a new package; closing the tab asks first and still sends them - seen live on `bfa8711d` (E1-E4). The pending-edits note now reads "... from the last save. Save to update." (owner) | R3: the note's new words |
| 11 | Policy period and premium | **Done, seen working** | As 4 and 8 | As 4 and 8 |
| 12 | Tenant, not owner; revenue "$0" | **Declined - explain** | Tenant is a producer card; "$0" not built (ACORD asks for the location's revenue) | Tell Michelle why; INSIDE city limits is never filled |
| 13 | GL code, SIC, NAICS; FEIN | **Partly done** | GL CODE 91580, 91585; the auto class 7383 appears nowhere on the 125 and in no "AI held back" row - seen live on `bfa8711d` (W7) | SIC / NAICS are not in the dec (ask Michelle which page); LLC members blank |
| 14 | Send the 125 to the client; applicant signature | **Not started** | The Sign button signs the PRODUCER's box only, on all 17 forms - seen live on `bfa8711d` (G1-G3); the applicant's lines stay blank, are listed as "To be signed by the applicant" (now in the side panel too) and never reach the cover | E-signature: Brent |
| 15 | "No known losses" still counts | **Done, seen working** | Loss History becomes Not Applicable and reads "Attested - no known losses"; unticked it reads "Unknown", never "Prior claims known" - seen live on `bfa8711d` (C1, C2) | Lowers weak and some 1-5 year packages: tell Brent |
| 16 | A resolved hard stop moves to Reviewed | **Done, seen working** | Fix round: a handled stop's sentence prints once, on its Reviewed row | Live retest |
| 17 | Green "Client" boxes filled by the producer | **Partly done** | A box is green only while the client's value is in it - the client's FEIN printed green on `bfa8711d` (Q5) | The retype half (green goes away) not yet reported |
| 18 | Yes / No not editable on 126 / 127 | **Partly done** | Every Y/N question is outlined and clickable in edit mode | The client half was declined (owner); about 181 of 190 Y/N answers open blank |
| 19 | Each item: what, how, score effect | **Done, seen working** (moved up 1 Oct) | Every box in the form's words with what to do and its score effect; ONE number per card - the loss card +7 on all five forms and "Answering this adds +7 pts" in Best Solutions, seen live on `bfa8711d` (P5, P6); the wrong Emcasco row is gone (W3). After the retest: the cover prints each card with the panel's own number and hedge | D1 (the download review window) not yet reported; R4 |
| G1 | E-mail tagline | **Done, seen working** | Also in the plain-text part of both client e-mails; the heading seen again on `bfa8711d` (Q2) | Deploy |
| G2 | Landlord name and address | **Partly done** | Prints on 125 ADDITIONAL INTEREST row A; fix round: as typed ("CBRE Group Inc", not "Cbre") | The client path never ran live; not on the ACORD 25 holder; nothing with 2+ locations |
| Q | Questions vs check items | **Partly done** | Counted apart everywhere - the client's end summary read "1 of 7 questions answered - 3 of 4 details checked" on `bfa8711d` (Q3) | The client's header / ring / chips and the producer's receipt not yet reported |

**Fixes and decisions outside the client's list:**

| Item | Status |
|---|---|
| Question 4 line names mixed | **Fixed, verified live** |
| Premises description printed tiny | **Fixed, verified live** |
| "New venture" card on a renewal | **Fixed, verified live** |
| FEIN invented by gap fill ("27-0272601") | **Fixed**, proven by replay; no live run since has invented one |
| "producer" label scored 0 in the fill rate | **Fixed** (offline); fill rates go up - tell Brent |
| An answered box printed unformatted ("300000") | **Fixed** (offline), not re-checked live |
| A status notice asked for "a supporting document" | **Fixed** (offline), not re-checked live |
| Carrier-name casing | Dropped on purpose (V1 H5: print it as the policy does) |
| Exposure rows show "100%" when nothing is supplied | Dropped on purpose (C3 traceability); the owner may choose a wording |
| AUDIT prints "A", not "Annual" | No change: ACORD's box asks for the code; tell the client |
| BLD # "1" / "001" | No change: a gap-fill reading; the dec numbers the location |

**Found in the final run and FIXED offline (30 Sep evening, retest pending):** the viewer drawing one page under
another page's boxes; CONTACT TYPE / BLD # copied from the box beside them; "Found" for invented values; internal
names in the review and cover page; the GL policy misread as 6C7 (question 4 and page 4). See section 6 "Fixes from
part 1".

**Found and NOT fixed (known, logged):**
1. **Editing the location table loses data** (pre-existing): LOC #, BLD #, county, interest, revenue, employee counts and
   areas are wiped by any table edit. Recommended next fix.
2. **Before forms, a pre-form fix re-checks the cross-form rules against no forms**, which can lift an 85 cap while its
   card stays on screen (2 of 12 panel packages; pre-existing). Owner's call.
3. **Question 4 lists the four policies in a different order on each run** (cosmetic).
4. **Landlord answers are logged in plain text** in the audit tables, like every producer answer (existing class).
5. The known pre-existing failing test `test_arq_acord125_missing_only`.

**Checked in the dec (all 271 pages, 30 Sep):** no e-mail address anywhere; "tenant" only in policy wording (never about
Orbin); no SIC code; "NAICS" once, in an auto rating notice, with no code; the only person named is "NAMES OF
INDIVIDUALS: ERIN ROYAL" on the auto page; the only phone numbers are the agency's (303-996-7800) and EMC's claim /
servicing lines. The contact Michelle typed in the questionnaire (303-521-0561, erin@orbin.com) is not in the dec.

**Questions for Brent and Michelle - prepared 30 Sep, NOT sent (owner: test first, ask later):**
- Michelle: (1) item 5 - which page shows the insured's contact; (2) item 7 - is Commercial Risk Solutions the
  submitting agency; (3) item 12 - $0 or the business's revenue in the premises ANNUAL REVENUES box; (4) item 13 - which
  page shows SIC / NAICS; (5) item 18 - should the client also answer unanswered Yes/No questions in the questionnaire.
- Brent: (1) page 1 on a dec renewal shows the dec's premiums and carrier, reversing his answer key - accept, and the
  rule for two writing companies; (2) item 14 - how the applicant signs; (3) G2 - where the landlord prints; (4) item
  15 - "No known losses" lowers weak and some 1-5 year packages - accept.

**Decided by us, not asked:** item 1 (Michelle wrote "your call": the dashboard opens the profile, a "Continue where you
left off" button, started forms under Key Details); G2 who supplies the landlord (Michelle wrote the client: add it to
the questionnaire); item 8 blank-premium prompt (she asked for one: build it); the producer's receipt counts like the
client's summary; item 15 "Max 85%" (gone after the fix); the stale-dec rule; item 19 "a." (a formatting gap); AUDIT "A"
(ACORD's code - explain if she asks). Her 22 Sep TENANT / CITY LIMITS ticks no longer matter (Tenant is confirmed
by a card).

---

## 1. The baseline run (before any change)

| | |
|---|---|
| Session | `8992d874-2a2d-4144-89dc-a663fc62b1d7` (28 Sep 2026, 18:23 UTC / 23:53 IST) |
| Build | local, uncommitted work on top of `8b005ad` (FR125 round 2 fixes, extraction **v25**) |
| Document | `2526 Package Policy (Complete Copy) (4).pdf` - 271 pages, 699,844 characters of text. Classified **Dec Page, strong match** |
| Forms generated | ACORD 125 only |
| Login | Astrea IT Services / Vinay Sharma. The client's run used ThinkSmith Agency LLC / Michelle Smith |
| Re-grade it | `py backend/scripts/dump_a125_run.py 8992d874-2a2d-4144-89dc-a663fc62b1d7 > <scratch>.json` (real client data - keep the dump out of the repo) |

### 1.1 What the declarations actually print (checked in the text of all 271 pages)

This is the evidence every fix below has to be measured against.

| Topic | What the dec prints | Where |
|---|---|---|
| Named insured | ORBIN CONTRACTING LLC, 4800 DAHLIA ST # D13, DENVER CO 80216-3121 | page 1 |
| Producer (agency) | **COMMERCIAL RISK SOLUTIONS, INC.**, 9780 S MERIDIAN BLVD STE 400, ENGLEWOOD CO 80112-6072. AGENT NO. W6258-0001, **AGENT PHONE 303-996-7800** | page 1; again on page 3 ("AGENT: AW 6258", "DIRECT BILL AGENT PHONE") |
| Producer e-mail | **Not printed anywhere** (every "e-mail" in the text is policy wording) | - |
| Carriers | EMPLOYERS MUTUAL CASUALTY COMPANY (auto, inland marine, umbrella); EMC Property & Casualty Company (GL). **No NAIC printed** | section decs |
| Policies | Auto 6E7-40-02---26; GL BBC7263 - 26; Inland Marine 6C7-40-02---26; Umbrella 6J7-40-02---26 | section decs |
| Policy period | 07/15/2025 to 07/15/2026 on every policy | all section decs |
| Premiums | Property No Coverage; **Liability $3,954; Inland Marine $300; Automobile $2,991; Umbrella $3,418**; Crime and WC No Coverage; **Estimated Total $10,663** | page 1 "Coverages and Premium" |
| Billing | "DIRECT BILL" | page 3 |
| Audit | "Audit Period: Annual" (GL) | GL dec |
| GL class codes | **91580** Contractors - Executive Supervisors (payroll $39,300, premium $1,305); **91585** subcontracted work (total cost $350,000, premium $1,198 + $803) | page 211 |
| SIC / NAICS | **Not printed anywhere** (the only "NAICS" is a rating notice) | - |
| Business description | "INSURED IS: LLC BUSINESS DESC: COMMERCIAL GENERAL CONTRA" (cut off by the carrier's system) | page 3 |
| Premises | "Location of All Premises Owned, Rented or Occupied - Rated Locations: 4800 Dahlia St # D13, Location 1". **The words tenant / owner / city limits are never printed for this location** | page 212 |
| Property coverage | No Coverage (so no building is insured) | page 1 |
| Insured contact person, phone, e-mail | **None printed.** The only phone numbers are the agent's, EMC claims (888-362-2255) and EMC's servicing office (720-200-3700). ERIN ROYAL appears once, as the auto policy's Drive Other Car named individual | - |
| Loss history | None | - |

### 1.2 Pre-form review screen

- **Overview:** "Major Gaps", 5 of 12 key details in place.
  - In place: legal name, mailing address, lines of business, entity type, operations description.
  - Missing: proposed effective date, contact information, FEIN, annual revenue, number of employees,
    years in business, NAICS or SIC.
  - The card still says "Your Submission Quality Score is calculated after forms are generated."
- **Documents:** 1 document, Dec Page, strong match, all clear.
- **Submission Integrity:** verified.
- **Data Consistency:** nothing to confirm.
  - Policies table: 4 rows, NAIC "-" on each.
  - "Carrier: 4 policies, 2 values - not a conflict".
  - "Policy Number: 4 policies, 4 values - not a conflict".
- **Hard stops:** none.
- **Warnings (3):**
  1. ACORD 125 minimum field missing: Proposed effective date.
  2. ACORD 125 minimum field missing: Contact information.
  3. Driver schedule not provided.
- **"Important" block:** repeats two of those warnings. Its text is broken: "Fix: Provide this value manually, or upload a
  document that states it.) (+1 related" (the same broken text is in the client's screenshot, item 3).

### 1.3 SQS after generating ACORD 125

- **ACORD 125 form score: 57 (F, Not Ready).**

  | Pillar | Score |
  |---|---|
  | Structural | 60% |
  | Exposure | 40% |
  | Property | 100% |
  | Loss History | 25% |
  | Umbrella | 100% |
  | Narrative | 40% |

- **Package score: 64 / 100, "Major Gaps" (contractor).**

  | Pillar | Score | Categories |
  |---|---|---|
  | Structural | 54% | Form Fill Rate 100% |
  | Exposure | 72% | Operations 92%, Coverage 100%, Payroll/Employee 100%, Revenue/Sales 100%, Cross-Document 100%, Auto Completeness 80%, WC 100% |
  | Property | 100% | COPE and Location not applicable |
  | Loss History | 25% | Limited |
  | Umbrella | 100% | Complete, follow form confirmed |
  | Narrative | 40% | Limited |

- The stored cap reason is the missing proposed effective date.
- **Best solutions add up to 35.7 points:**
  - Structural +11.5 (proposed effective date).
  - Loss history +11.2.
  - Exposure +7 (auto completeness, operations description).
  - Narrative +6.

### 1.4 Pre-download "SQS Review" (8 items, verbatim in short)

1. Narrative is missing account overview, years in business, management experience, risk controls (+3 more). Up to +6.
2. No loss history provided. Up to +6.
3. "If this business is a new venture..., confirm New Venture status". Up to +6.
4. ACORD 125 missing: effective date. Up to +5.
5. ACORD 125 missing: contact info. Up to +5.
6. "ACORD 125: 19 fields left blank on purpose - a value was found for each but could not be true for that box ...
   (AdditionalInterest FullName, CancelNonRenew UnderwritingConditionCorrectedDescription, CommercialStructure
   InstallationRepairWorkOffPremisesPercent, +7 more)".
7. "ACORD 125: 4 high-impact questions were left blank by the AI (no value found in the documents):
   CommercialPolicy ApplicantOwnLeaseOperateDronesExplanation, AdditionalInterest Interest LeasebackOwnerIndicator,
   AdditionalInterest FullName, +1 more".
8. "Field QA: 12 required fields still empty and 152 optional fields not covered by the documents".

### 1.5 Client questionnaire as offered

- **Counts:** 21 client, 5 agency, 9 critical (3 agency), 10 optional, 2 duplicates merged, 11 selected.
- **Applicant (12):**
  - Critical: contact name, FEIN, contact phone, contact e-mail, annual revenue, employee count.
  - Suggested: annual gross payroll.
  - Optional: date business started, additional remarks, DBA, and two confirm items (legal name, mailing address).
- **Operations:** subcontracted % by type of work.
- **Property:** confirm the 1 location.
- **Auto:** garaging / return to yard.
- **Loss history:** no-known-losses attestation and the claims table.
- **Other:** urgency, plus three narrative questions (account overview, management, risk controls).
- **Schedules:** 1 vehicle, 1 location, 0 claims.

### 1.6 ACORD 125 output, box by box

- The stored form has 441 boxes, and **73 carry a value**. All 73 came from the deterministic passes.
- **321 are owned blanks** (a rule decided they stay empty).
- **154 were sent to the AI gap fill, and every one of the 154 came back empty.**

**Page 1**

| Box | Printed | Why |
|---|---|---|
| Date | 09/28/2026 | run date |
| Producer / contact / e-mail | Astrea It Services / Vinay Sharma / vinaysharma@astreait.com | the login (the dec's agency is Commercial Risk Solutions, Inc.) |
| Producer phone, fax, address, code, subcode, customer ID | blank | owned blank - the dec's agency is not the login's agency, so its phone and code are withheld |
| Carrier, NAIC, program, policy number, underwriter | blank | owned blank - page one is the policy being applied for, and the dec is the CURRENT policy (`carrier_is_current_policy: true`, rule of 15 Sep) |
| Status | QUOTE | |
| Lines of business | Business Auto, CGL, Commercial Inland Marine, Umbrella | correct |
| Line premiums | all blank | owned blank (`premium_is_current_policy: true`) |
| Attachments | Vehicle Schedule | kept on purpose (client's "do not regress") |
| Proposed eff / exp date | **blank, flagged required** | rejected: "the current policy's term ended on 2026-07-15; ... no document states when the new policy starts" |
| Billing plan | Direct | dec "DIRECT BILL" |
| Payment plan | blank | |
| Method of payment | "Direct bill" | a copy of the billing plan |
| Audit | "A" | dec "Audit Period: Annual", printed as the ACORD code (the client's 22 Sep run printed "Annual") |
| Deposit / minimum / policy premium | blank | owned blank |
| First named insured | Orbin Contracting LLC, 4800 Dahlia St, # D13, Denver CO 80216-3121 | correct |
| Legal entity | LLC | correct |
| No. of members and managers | blank, flagged required | not on the dec |
| GL code / SIC / NAICS / FEIN | blank | GL code went to the AI and came back empty, although the dec prints 91580 and 91585; SIC, NAICS and FEIN are not on the dec |
| Business phone, website | blank | not on the dec (EMC's own www.emcins.com was extracted and correctly not used) |

**Page 2**

| Box | Printed | Why |
|---|---|---|
| Contact information (both blocks) | blank | owned blank; the dec names no insured contact |
| Premises LOC 1 / BLD 001 | 4800 Dahlia St, # D13, Denver CO 80216-3121 | correct |
| City limits, interest (owner / tenant) | **blank, flagged required** | owned by the location schedule; today's extraction left `is_tenant` and the city-limits flags empty |
| Employees, annual revenues, building area | blank, flagged required | not on the dec |
| Premises description of operations | the two GL class descriptions joined by ";", at a tiny font | |
| Nature of business | Contractor | |
| Date business started | blank, flagged required | not on the dec |
| Description of primary operations | same two GL class descriptions | |

**Page 3**

| Box | Printed | Why |
|---|---|---|
| Additional interest | blank | |
| Questions 1-3 and 5-15 | blank | the dec does not answer them |
| Question 4 (other insurance with this company) | Y. Rows: Commercial General Liability BBC7263 - 26; Inland Marine 6C7-40-02---26; Commercial Auto 6E7-40-02---26; Umbrella 6J7-40-02---26 | owner decision of 24 Sep (Q4 restored) |

**Page 4**

| Box | Printed | Why |
|---|---|---|
| Remarks | blank | |
| Prior carrier, year 2025 | GL: EMC Property & Casualty Company, BBC7263 - 26, $3,954, 07/15/2025 to 07/15/2026. Auto: EMPLOYERS MUTUAL CASUALTY COMPANY (all caps, tiny font), 6E7-40-02---26, $2,991, same dates | Inland Marine and Umbrella have no column; OTHER is empty |
| Loss history, "Check if none" | blank, flagged required | nothing on the dec |

**Page 5:** producer's name Vinay Sharma. The applicant signature, date, licence number and NPN are blank.

---

## 2. The client's test document - `Orbin_Testing_09_22_2026.pdf`

- **Who, when, what:** Michelle, 22 Sep, on build `42a092a`. She tested 125, 126, 127, 131 and 186 on this same dec.
- **Contents:** 19 numbered items, 2 general comments and a questionnaire note.
- **Today column:** what our 28 Sep run (section 1) shows for the same thing.

**Type key:**
- **BUG** - we confirmed it is wrong today.
- **BUG?** - not re-checked today.
- **DECISION** - the client's ask conflicts with a rule we built on purpose, so the owner must choose.
- **UX** - screen or workflow change.

| # | Client says | Today (28 Sep run) | What we found | Type |
|---|---|---|---|---|
| 1 | Opening a package from the dashboard should land on the package profile, even after forms were started ("View Package Profile" / "Continue where you left off"); started forms in their own tab or under Key Details | not tested in this run | - | UX |
| 2 | Do not require forms to get the score; move towards "formless" (SQS on top of any system). Pre-score? Hide or change the "calculated after forms are generated" line? | Overview card still says the score is calculated after forms are generated | A stateless pre-form package score already exists (`sqs_service.current_package_sqs`, 27 Aug). The card shows only the tier by the owner's H2 call | DECISION + UX |
| 3 | Remove the "Important" section; the repeated items confuse | still there, same broken text | **Root cause of the broken text:** "(+N related)" is added AFTER the Fix text (`ReviewRailLayout.jsx:837`, `AcordModal.jsx:7570`). `IssueLine` (`AcordModal.jsx:845-857`) then strips the last ")" as if it closed "(Fix:", so it strips the one from "(+1 related)" | BUG + UX |
| 4 | Proposed effective date = the last date of the current term (the renewal date on the dec) | **blank + warning** | Our 15 Sep rule `_route_renewal_dates`: an ENDED term (07/15/2026 is past) is not the term being applied for, so the dates are asked. The client says: take the dec's expiration as the proposed effective date. In her own run she typed 07/15/2026 to 07/15/2027 | DECISION (client instruction) |
| 5 | "Contacts are in the dec" | warning "Contact information" still fires | **The dec prints no insured contact** (see 1.1). What it has is the AGENT's phone. 125's CONTACT INFORMATION is the applicant's inspection / accounting contact, and the client's own spec (3.3) says contact information is not waived on a dec-only package. We need to ask which contact she means | DECISION / clarify |
| 6 | Error when clicking "Open to fix" on "Driver schedule not provided" | **still reproduces** once forms are chosen without ACORD 127 | Fixed 24 Sep for the pre-form screen (nothing chosen yet). But `get_session_schedules(8992d874, only_key="auto_drivers")` returns `[]` on this run: the only chosen form is 125, and the endpoint serves only schedules of chosen forms, while the warning (gated on the auto LINE) still offers the table. Same BUG-05 class: a control the server will not serve | BUG |
| 7 | 125 carrier information not auto-filled ("it was at one point"); producer phone and e-mail are in the dec | carrier / NAIC / policy number / program / underwriter blank; producer phone blank | **Carrier:** blank by our 15 Sep page-one rule from Brent's key (page one = the policy being applied for). The package has 2 carriers and 4 policy numbers, and page one has one box each. **Producer:** the dec's agency is Commercial Risk Solutions, Inc. (phone 303-996-7800, no e-mail printed). The login's agency (ThinkSmith / Astrea) has a different name, and our 24 Sep rule withholds another agency's identifiers. When the dec's agency IS the login's agency (the normal real case), the merge records no expiring producer and the dec's phone counts as the submitter's own (`_producer_identifiers`) | DECISION |
| 8 | Lines identified but premiums did not attach, and no prompt to supply them | line premiums blank; no card or question asks for them | Blank by our page-one rule (`premium_is_current_policy`). The dec prints GL $3,954, IM $300, Auto $2,991, Umbrella $3,418, total $10,663. Nothing prompts for the blank premiums | DECISION + BUG (no prompt) |
| 9 | We know what is missing / required / to verify: show it in the side panel, or earlier, before form selection | the "14 Required / 1 Verify" list exists only inside the form viewer | - | UX |
| 10 | Make the Edit button far more obvious; allow double-click editing on the form | not tested | - | UX |
| 11 | Policy period is on the dec; premium missing with no prompt | same as 4 and 8 | - | see 4, 8 |
| 12 | The dec notes a tenant policy, not owner; as tenant, revenue should be "$0" by default | **TENANT and INSIDE CITY LIMITS both blank today** (her 22 Sep screenshot had both ticked; we cannot tell whether the AI or she ticked them). Annual revenues blank, flagged required | The dec never prints tenant / owner / city limits for the location. The only evidence is indirect: no property coverage, a suite number "# D13", and "Premises Owned, Rented or Occupied". Today's v25 extraction left them empty, so the schedule-owned boxes print blank. "$0 revenue for a tenant" is a client rule we have not built, and it conflicts with ACORD's own instruction for that box: "The annual revenue amount for this location" (the business's revenue there, not rent) | DECISION + regression vs 22 Sep |
| 13 | GL code, SIC and NAICS are all on the dec; FEIN may be client / producer filled | all blank | **GL code: BUG** - the dec's GL schedule prints 91580 and 91585, but the box went to the AI and came back empty (no deterministic binding from `gl_class_code_schedule`). ACORD's instruction asks for an ISO CLM code. The extracted schedule carries no per-class premium, so "the governing class" cannot be picked from facts. **SIC / NAICS: not printed anywhere in the dec** - they need a source (the Figure 20 suggester can offer candidates for confirmation, never fill them). FEIN is asked in the questionnaire | BUG (GL code) + clarify (SIC / NAICS) |
| 14 | Can the 125 go to the client through the questionnaire? How does the applicant (not the producer) sign? | applicant signature and date blank | No applicant-signature path exists | Feature |
| 15 | Loss runs still show 60% (max 85%) after "No Known Losses" was confirmed; it should not count against the score | not attested in this run (Loss History 25%) | This is by design today: an attested "no known losses" scores the pillar at 60 (`sqs_service` loss path C: attested 60, requested 50), and only loss runs raise it. The client wants it not to count. That is a scoring rule change, and scores go up (D6) | DECISION (score rule) |
| 16 | A resolved hard stop should tuck under "Reviewed" / "Recommendations", not stay in the red panel | no hard stops this run | - | UX |
| 17 | Green "Client" fields were filled by the PRODUCER, not the client - change the wording or verify | not tested | The viewer paints any field in `client_filled_fields` green as "Client" (`PDFJsViewer.jsx:277`, list served by `form_routes.py:1747-1781`). Next: find which producer path writes into that list | BUG |
| 18 | Yes / No questions on 126 and 127 cannot be edited (they can on 186) | 125 only this run | - | BUG? |
| 19 | The download "SQS Review" comes too late. Each item should say what needs attention, what to do, and the score effect, and whether the value is missing, withheld by the AI, or inferred and needing verification. The score should update as items are resolved. The Field QA summary does not say which form or question | same pattern today (section 1.4) | Today's review shows internal field names ("AdditionalInterest FullName"). "19 fields" counts boxes while the list counts 10 distinct names ("3 + 7 more"), from `field_qa.py:758-783`. **The same box, "AdditionalInterest FullName", appears both as "a value was found but removed" and "no value found".** "High-impact questions" includes explanation boxes and an Additional Interest checkbox, which are not questions | UX + BUG (messaging) |
| G1 | Client e-mail should say "Commercial Insurance **Submission** Platform" | - | - | copy |
| G2 | If there is a landlord, the client must give the landlord's full name and address for certificates | - | - | Feature |
| Q | The questionnaire summary said "21 of 25 answered", but 3 of the 25 were verification (confirm) questions | - | Confirm items are counted as questions | BUG (count) |

What she typed in the questionnaire (useful for re-testing):
- Answers:
  - lender / additional interest: none
  - outside contractors: 80%
  - contact: Erin Royal
  - DBA: no
  - revenue: $300,000
  - payroll: $0
  - additional named insureds: none
  - radius: 50 miles
  - vehicle use: "Other: used for both personal and to go to job sites"
  - hired or rented vehicles: no
  - employees' own vehicles: no
  - residential work: 0%
  - high-hazard operations: none
  - licence: a Colorado licence number
  - urgency: none
  - subcontracted work by type: 60% tenant improvement, 20% painting, 20% HVAC
  - garaging: "No - vehicles are garaged at drivers' homes or elsewhere"
  - drivers: 1 driver
- She also gave a phone, an e-mail and an FEIN. They are left out of this file on purpose.

---

## 3. Other problems this run shows (not in the client's list)

1. **AUDIT prints "A"; on 22 Sep it printed "Annual".** This changed with the FR125 round 2 tooltip-code work, and the
   client may read it as a regression. **But "A" is what ACORD asks for.** The box's own instruction reads "Enter code:
   ... A - annual, S - semi-annual, Q - Quarterly, M - Monthly, O - Other". Keep "A" and tell the client why.
2. **METHOD OF PAYMENT prints "Direct bill"**, the same words as the billing plan. The box's instruction is only "The method
   the policy will be paid", so this is defensible. It was the same on 22 Sep and the client did not flag it. Leave it.
3. **The premises operations description prints at a tiny font.** It is two GL class descriptions joined by ";". The 25 Sep
   one-line shortening works only on whole sentences. The dec also has its own "BUSINESS DESC: COMMERCIAL GENERAL
   CONTRA" (cut off).
4. **Prior carrier grid:**
   - Only GL and Auto appear.
   - Inland Marine and Umbrella have no column, and OTHER is empty.
   - The two carrier names print in different casing: EMPLOYERS MUTUAL CASUALTY COMPANY in capitals at a tiny font,
     against EMC Property & Casualty Company.
5. **Question 4 lists all four current policies** as "other insurance with this company" (owner decision, 24 Sep).
   - Page one's carrier box is blank, so "this company" is undefined on the form itself.
   - The line names are mixed: "Commercial General Liability" and "Commercial Auto" against "Inland Marine" and "Umbrella".
6. **The "New venture" recommendation is offered** on a package whose own documents show policies in force since 07/2025.
7. **The Exposure pillar shows "Revenue/Sales 100%" and "Payroll/Employee 100%"** while annual revenue and number of
   employees are listed as missing key details. The pillar measures agreement, not presence, but it reads as a
   contradiction.
8. **None of the 154 boxes sent to the AI came back with a value.** That is fine where the dec is silent. It is wrong for GL
   CODE (item 13).
9. The "Driver schedule not provided" warning is raised by the auto LINE, whatever forms are chosen (it drives item 6).

---

## 4. What the client wants

_To be added when the owner sends it._

---

## 5. Fix plan (proposed 29 Sep - the decisions wait for the owner's yes)

**Step 1 - clear bugs, no decision needed.** **DONE 29 Sep, see section 6.** Two extras were dropped
(carrier casing, Exposure wording) because each would reverse a deliberate earlier decision. The NAICS suggester
stays off (client spec 3.13).

| # | Fix |
|---|---|
| 3 | Remove the "Important" block and its filter chip. Also make sure "(+N related)" can never again land after a Fix line (`ReviewRailLayout.jsx:837`, `AcordModal.jsx:7570`) |
| 6 | Serve a schedule when a chosen form uses it OR its line is carried - the same evidence the warning uses - so the warning and the table can never disagree |
| 13 | GL CODE stamped from the dec's GL class schedule, with no AI. Two classes print both ("91580, 91585"). SIC and NAICS stay blank; the suggester offers candidates to the producer |
| 17 | A value the producer typed is labelled as the producer's, never "Client" |
| Q | The questionnaire summary counts confirmations separately from questions |
| G1 | E-mail subtitle: "Commercial Insurance Submission Platform" |
| extras | One casing for carrier names; one naming style for Q4 lines; the one-line premises description breaks at ";"; no "new venture" card when the documents show an existing policy; Exposure categories say "Not provided" instead of 100% when there is nothing to compare |

**Step 2 - decisions (recommendation in bold)**

| # | Question | Recommendation |
|---|---|---|
| 4, 11 | Proposed dates from the dec? | **Yes.** Effective = the dec's expiration date; expiration = one term later. Ask only when that next term is itself already over (a stale dec). Reverses the 15 Sep "ended term - ask" rule |
| 7, 8 | Page-one carrier and premiums from the dec? | **Yes, as one rule.** If the documents name the carrier the submission goes to, use it (the FR125 case, which must stay 312 of 312). If they do not, a dec upload is a renewal with the same carrier: carrier and line premiums from the dec. NAIC stays blank (not printed). Policy number stays blank (four different numbers, all already in Q4 and the prior-carrier grid). Anything left blank gets a card that asks for it. Reverses the 15 Sep page-one rule - confirm once with Brent, because his key and Michelle's test disagree |
| 7 | Print the dec agency's phone? | **No change.** It is another agency's phone (Commercial Risk Solutions, not ThinkSmith). On a producer's own client's dec it already prints. The producer phone should come from the agency profile |
| 12 | Tick tenant, and put $0 revenue? | **Tenant: a one-click confirm showing the evidence (suite # D13, no building insured) - not a silent guess. Revenue: not $0.** ACORD's instruction is the location's revenue, so with one location copy the business's annual revenue into it. Ask for the landlord's name and address when the interest is tenant (G2) |
| 5 | Which contact does the dec have? | **Ask Michelle.** Meanwhile offer Erin Royal as a one-click suggestion for the contact name (the dec names her only as the Drive Other Car person). Phone and e-mail stay asked |
| 15 | Should an attested "no known losses" count in the score? | **Do what the client asks:** treat it as Not Applicable, like a confirmed new venture. Scores go up - tell Brent (D6) |
| 2 | Show a score number before forms? | **Yes.** It is already calculated (`current_package_sqs`); drop "calculated after forms are generated" and label the number as "so far", because it can still move at generation. Reverses the 27 Aug tier-only card |

**Step 3 - check, then fix:** 18 (Yes/No boxes not editable on 126 and 127).

**Step 4 - screens and workflow** (after the client's list arrives, because it may reshape these):
- **19 with 9:** one "needs attention" list.
  - Where it shows: pre-form for package items, and in the form viewer's side panel for form items, with click-to-jump.
  - Each row in plain words: the question as the form prints it, what to do, and the points.
  - Each row gets one tag: Missing / AI held back / Please verify.
  - The counts must be right. No contradictions: today the same box shows as both "value found" and "no value found".
  - The score updates as items are fixed.
- **1:** opening a package from the dashboard lands on the package profile, with "Continue where you left off".
- **10:** a bigger Edit button, and double-click to edit a box.
- **16:** a resolved hard stop moves to "Reviewed".
- **14:** applicant signature through the questionnaire. This needs Brent's call on e-signature.

## 6. Fix log

### Step 1 - done 29 Sep 2026 (owner: "fix things of step 1 ... do not break things that are not related")

**Replay of session `8992d874` through the new code:**
- Exactly 3 boxes change:
  - GL CODE: blank -> "91580, 91585";
  - question 4 row B: "Inland Marine" -> "Commercial Inland Marine";
  - question 4 row D: "Umbrella" -> "Commercial Umbrella".
- Nothing else moves. The form date is a replay artefact.
- The premises description change is print-only, so the stored value is the same.

**FR125 v2 test 8 replay:** still **312 of 312, 0 made up**, and 0 boxes moved against the previous replay.

| # | What was wrong (root cause) | The fix | Blast radius checked |
|---|---|---|---|
| 3 | The "Important" block repeated the top clusters of the tiers below it. Its "(+N related)" suffix was appended AFTER a message ending "(Fix: ...)", and `IssueLine` then stripped the last ")" - the one from "(+1 related)" - printing "states it.) (+1 related" | The "Important" tab and block are removed from both review screens (`ReviewRailLayout.jsx`, legacy `AcordModal.jsx`). `IssueLine` now removes the bracket that actually CLOSES "(Fix:", and moves any trailing text to the headline | Only these two screens read `grouped_issues.important`. The backend still sends it: tests pin it, and nothing renders it. Counts never included it |
| 6 | The driver warning is raised from the auto LINE (`has_auto_coverage`) whatever forms are chosen. The table endpoint served a table only when a CHOSEN form used it. With ACORD 125 alone, the card was on screen and the endpoint returned nothing, so the modal said "This schedule is not available for the current forms." (BUG-05 class) | `get_session_schedules` also serves any table a stored issue's resolution opens (`_schedules_offered_by_issues`, which falls back to the rule code for older sessions). It can only ADD a table a card already names | The 23 Sep narrowing still holds: no WC table appears on a package without a WC card or form. Saving the table writes `auto_drivers`, and the warning clears on the recompute. The pre-load panel handles an empty form list ("Forms:" is hidden) |
| 13 | GL CODE's only deterministic source was a STATED applicant code. The dec's GL class schedule (91580, 91585) never reached the box; it went to gap fill and came back empty | `_applicant_gl_codes_from_schedule`: when no applicant code is stated, print the schedule's rated ISO classes (1-3 distinct codes; the box fits two at full size, three slightly smaller) | A stated code still wins (FR125's 92478 and the Meridian kit's 91746 are unchanged). Today's behaviour is kept when: another named insured is listed; there are more than 3 classes; or a code is not 5 digits |
| 13 | SIC / NAICS | **Not changed.** They are not printed anywhere in the dec. The NAICS suggester is OFF by the client's own spec 3.13 (`ENABLE_CLASSIFICATION_SUGGESTIONS`), so offering candidates is the owner's call | - |
| 17 | `_restamp_canonical_into_forms` labelled EVERY box it stamped `client_arq` and put it on `client_filled_fields`. That includes the producer's own card answers and "Open to fix" answers, so the viewer painted them green "Client" | The function takes `provenance`. The producer path (`apply_producer_answer_to_session`) stamps "producer" and takes the box OFF the client list. Questionnaire answers keep "client_arq" | **Latent bug found and fixed with it:** "producer" had NO fill-rate weight, so every producer-saved SCHEDULE cell (labelled "producer" since BUG-05) scored 0.00. Now 1.00 in `CONFIDENCE_SCORE`, and "pass" in Field QA. The anti-rot test missed it because it read only two files; it now also reads `arq_service.py` and the `conf[...]` form. Producer boxes are still never re-asked in the questionnaire. **D6: forms with producer-saved schedule cells score HIGHER in fill rate - tell Brent** |
| Q | The questionnaire summary counted the 3 "confirm" items as questions ("21 of 25 answered") | The summary now reads "21 of 22 questions answered - N of 3 details checked". A confirm item counts as checked whether it was confirmed or corrected | Receipt only (`ClientQuestionnaire.jsx`). The progress ring still counts confirms as items to go through (not raised) |
| G1 | The e-mail tagline was "Commercial Insurance Platform" | Both client e-mails (invitation and reminder) now say "Commercial Insurance Submission Platform", from one constant | - |
| extra | Question 4 rows took their names from whichever summary row survived the dedupe, mixing the common dec's short labels with the section decs' titles | Each row takes its own policy's declarations title (`_line_records.line_printed`), matched by contract | Only the inferred list changes. A list the documents STATE prints as stated |
| extra | The one-line premises box keeps only whole sentences that fit. A dec's class descriptions are joined by "; " with no full stop, so nothing fitted and the box printed at the 3.5pt floor | "; " before a capital is also a break, and the kept text never ends on ";" | Print-only; the stored value is unchanged. Paragraphs and short values print as before |
| extra | The New Venture card was offered on a package whose only policy term had already ended | `completed_policy_term`: a printed expiration date on or before today means the business had prior operations, so the card is not offered | A first policy still in force keeps the card. A producer's own confirmation is judged exactly as before, because `prior_operations_evidence` is unchanged |
| extra | "One casing for carrier names" | **Dropped - it would reverse a deliberate decision.** V1 H5: a carrier's name prints exactly as the policy prints it, because ACORD's instruction asks for the name "as found in the file copy of the policy". Title-casing once printed "Emc Property & Casualty" | - |
| extra | "Exposure rows say Not provided instead of 100%" | **Dropped - it would break the client's C3 traceability rule.** Each row is "100 minus what this bucket deducted", and the rows add up to the pillar. Missing revenue is charged under Structural, so "Revenue/Sales 100%" means "nothing deducted here". The owner can decide on a wording change | - |

**Tests:**
- New: `backend/tests/test_orbin_feedback_29sep.py` (36).
- Widened: `test_confidence_score_covers_every_label.py` (now also reads `arq_service`, +2).
- Frontend: builds clean, with no ESLint errors in the changed files.
- **One existing test was out of date and was corrected**, not the code:
  - The test was `test_live_run6_fixes_15sep::test_the_five_live_clipped_values_now_fit`.
  - It proves that long values no longer clip. It used "shrunk below 8pt" as a stand-in, with Orbin's ";"-joined value as the sample.
  - The two one-line operations boxes now print the first whole item at a readable size.
  - The test now asserts exactly that. The four other boxes still shrink and fit.
- **Suite `-p no:randomly`:** 10,326 passed / 2 failed / 19 skipped before the test correction. The two failures were
  that test and the pre-existing `test_arq_acord125_missing_only`.
- **After the correction, a full re-run: 10,327 passed / 1 failed / 19 skipped.** The one failure is the pre-existing
  `test_arq_acord125_missing_only`.

### Step 1 - live check (the owner's run, to be recorded here)

**Setup:**
- Restart the backend and hard-refresh the browser.
- Upload the same `2526 Package Policy (Complete Copy) (4).pdf` and choose ACORD 125 only.
- ~~No prompt changed, so extraction comes from the cache and should match `8992d874`.~~ **Wrong:** both live runs
  (`67e5ccf1`, `15f42b1d`) read the document afresh, so their facts differ from `8992d874` and from each other.

**Expect these changes:**

| # | Where | Expect |
|---|---|---|
| 1 | Review > Warnings | No "Important" block, no "Important" tab, no "(+1 related" text. Tabs: All / Required before submission / Recommended before quoting |
| 2 | Warning "Driver schedule not provided" > Open to fix | A driver table opens (0 rows), before AND after forms are chosen. Never "This schedule is not available for the current forms." |
| 3 | ACORD 125 page 1 | GL CODE "91580, 91585". SIC / NAICS / FEIN still blank |
| 4 | ACORD 125 page 2, LOC 1 "DESCRIPTION OF OPERATIONS" (one line) | "Contractors - Executive Supervisors or Executive Superintendents" at a readable size. The big PRIMARY OPERATIONS box still shows both descriptions |
| 5 | ACORD 125 page 3, question 4 | Y; Commercial General Liability BBC7263 - 26 / Commercial Inland Marine 6C7-40-02---26 / Commercial Auto 6E7-40-02---26 / Commercial Umbrella 6J7-40-02---26 |
| 6 | Pre-download "SQS Review" | The "new venture" item is gone (7 items instead of 8) |
| 7 | Enter the proposed effective date on its card ("Open to fix" or "Type your answer"), then open the form | The box is filled but NOT green, and the "Client" badge does not count it |
| 8 | Questionnaire (optional): send it to your own address | The e-mail says "Commercial Insurance Submission Platform". After submitting, the summary reads "N of M questions answered - X of 3 details checked" |

**Expect NO change anywhere else.** Every other box should match FILLED 14. The scores should be about the same (64 package, 57 on the
125).

**Still open on purpose (Step 2 / Step 4):**
- Proposed dates, carrier and premiums on page one: blank.
- Tenant, city limits, revenue: blank.
- The contact and effective-date warnings.
- Loss history at 25%.
- AUDIT "A".
- The SQS Review only at download.

### Step 1 - live check RESULT (session `67e5ccf1`, 29 Sep, ACORD_125_FILLED 15)

**Verified live:**
- question 4 names (item 5 of the check);
- the premises line prints readable (item 4);
- the "new venture" item is gone - 7 items instead of 8 (item 6);
- the drivers table is now offered: "1 vehicle · 0 drivers · 1 location" in the questionnaire's schedule panel (item 2, backend side).

**Not seen live:**
- The browser still ran the OLD screen code: "Important" and "(+1 related" were still there. The dev server had not been
  restarted and the page not hard-refreshed. The new code is on disk and builds clean.
- Not tried: the driver "Open to fix" click, the green-label test (item 7), the questionnaire e-mail and summary (item 8).

**This upload read the document afresh** (not from the cache), so the facts differ from `8992d874`. Two new WRONG values
came from that fresh reading, NOT from Step 1:

| Box | Printed | Root cause | Fix (29 Sep) |
|---|---|---|---|
| GL CODE | "7383" | The fresh extraction stated `applicant_gl_class_code = "7383"`. That code is the Subaru's rating class: the auto dec prints "PRIV PASSENGER - COMM CLASS: 7383", and it is also in `auto_vin_schedule`. A stated applicant code outranked the schedule fallback | `_code_is_another_lines`: when the documents give a stated code ONLY to another line's rating (read through the existing cross-line witnesses, `_line_code_witnesses`) and the GL schedule does not rate it, it is not this box's value. The policy's GL classes print ("91580, 91585"); without a GL schedule the box is an owned blank, NOT sent to gap fill, which would read the same auto line again. The existing cross-line fence could not catch it: it places a box by its FIRST name segment, and "NamedInsured" names no line |
| FEIN | "27-0272601" | Gap fill invented it: the number appears nowhere in the 271 pages. The raw-text check labelled it orange and it printed anyway. **Knock-on:** a FEIN "on file" retired the questionnaire's FEIN question, so the real one would never have been asked | `_drop_ungrounded_identifiers`: an AI value in an "Enter identifier:" box must appear in the documents (letters and digits in order; spacing and punctuation ignored), else it is blanked. That covers 223 boxes on 101 bases across the 17 forms (FEIN/SSN, licence, policy, VIN, NPN, form, loan numbers). Not judged: numbers the producer assigns, values under 4 characters, and anything a fact or a person supplied |
| BLD # | "1" (was "001") | Gap-fill guess; the dec numbers the location, not a building. Either value is a convention, not a document fact | Not changed |

**Replay tool fixed too:** `scripts/replay_125_run.py` restored every blanked call-2 answer that was not logged as
"blanked=". So it put back values the ungrounded-code and ungrounded-identifier guards had deliberately dropped: those
log as "DROP_...: field=". The replay of `67e5ccf1` showed the invented FEIN "restored" until this was fixed.

**Replays after the two fixes:**
- `67e5ccf1`: exactly 2 boxes change - GL CODE "7383" -> "91580, 91585", and the FEIN is blanked.
- `8992d874`: the same 3 Step 1 changes as before, nothing new.
- FR125 v2 test 8: **312 / 312, 0 made up**, 0 moved.
- FR125 tests 3-7: the new rules never fire (0 identifier drops, 0 GL rejections).

**Tests:** 15 added to `tests/test_orbin_feedback_29sep.py` (now 51).
**Suite `-p no:randomly`: 10,342 passed / 1 failed / 19 skipped.** The one failure is the pre-existing
`test_arq_acord125_missing_only`.

### Step 1 - second live check (session `15f42b1d`, 29 Sep, ACORD_125_FILLED) - PASSED

| Check | Result |
|---|---|
| No "Important" block or tab, no "(+1 related" | **Pass** (the frontend was restarted) |
| GL CODE | **"91580, 91585". The fix fired LIVE:** the fresh reading again stated `applicant_gl_class_code = 7383` |
| FEIN | **Blank.** This time gap fill tried the EMC ACCOUNT number "0482854" and an existing guard removed it (`guard_blanks`). The invented-number guard was not needed on this run; the replay of `67e5ccf1` proves it |
| Premises one-line description | **Pass** - readable |
| Question 4 names | **Pass** |
| SQS Review | **Pass** - 7 items, no New Venture |
| Everything else | Same as FILLED 15, except BLD # "1" (a gap-fill guess, unchanged) |

**Not tried yet:**
- the driver "Open to fix" click;
- the green-label test (type a date on a card);
- the questionnaire e-mail and summary, and whether the FEIN question is back as Critical.

**Worth knowing:**
- The safety net is doing heavy lifting on this dec-only package. The run's `guard_blanks` hold 98 entries, including:
  - policy wording in the Additional Interest name;
  - the agency as the applicant's website;
  - the carrier as the parent company;
  - the agent's phone as the applicant's phone;
  - invented NAICS 238990 and SIC 1799.
- Every one was caught, but it shows how noisy gap fill is when the documents cannot answer. That's for Step 4 / a later
  prompt review, not a Step 1 defect.

### Step 1 - third live run: the exact script (for the three checks not yet tried)

**Why the order matters:**
- The pre-form review screen cannot be reopened once forms are generated. So everything on it is checked FIRST.
- The green-label test must happen AFTER generation. A date typed before generation is stamped from the facts as an
  ordinary value ("filled"), so it never reaches the path that was painting producer answers green.

**Before you start:**
- Restart the backend and the frontend (`npm run dev`), then hard-refresh the browser (Cmd+Shift+R).
- Upload `2526 Package Policy (Complete Copy) (4).pdf` as a new package.

**A. On the pre-form review screen (before "Continue to form selection")**

| Step | Do | Expect | Record |
|---|---|---|---|
| A1 | Open Warnings | 3 items; tabs All / Required before submission / Recommended before quoting; no "Important" | a copy of the page |
| A2 | On "Driver schedule not provided", click **Open to fix** | An "Update the schedule" window with an empty driver table, NOT "This schedule is not available for the current forms." | a screenshot |
| A3 | Click **Cancel** (do not save drivers) | The window closes; the warning is still listed | - |

Do NOT fix the effective date or any other warning here; A2 is enough.

**B. Generate:** Continue to form selection, choose **ACORD 125 only**, generate.

| Step | Do | Expect | Record |
|---|---|---|---|
| B1 | Open the SQS & Actions panel | Package score and the ACORD 125 score (write both down); no "new venture" card | the two numbers |
| B2 | Open ACORD 125 in the viewer | GL CODE "91580, 91585"; FEIN blank; the premises line readable; question 4 names consistent | the header badges (e.g. "12 Required / 1 Verify / N Client") |
| B3 | If the driver warning is shown anywhere in the side panel, click its **Open to fix** | The same driver table opens (this is the exact case that failed before: forms chosen without ACORD 127). Cancel | a screenshot, or "not shown" |

**C. The green-label test (item 17)**

| Step | Do | Expect | Record |
|---|---|---|---|
| C1 | In the SQS & Actions panel, on the card **"ACORD 125 missing: effective date"**, type `07/15/2026` and submit | The card resolves; the score may move up | the new scores |
| C2 | Open ACORD 125 in the viewer again | PROPOSED EFF DATE shows 07/15/2026 and is **NOT green**; the "Client" badge does not count it | a screenshot of the box and the badges |

**D. The questionnaire (items G1 and Q)**

| Step | Do | Expect | Record |
|---|---|---|---|
| D1 | Open **Send to Client** | The list has **FEIN / Tax ID as Critical** (it disappeared when the invented FEIN filled the box) | a copy of the list |
| D2 | Send it to an e-mail address you can read | The e-mail's header line reads "Commercial Insurance **Submission** Platform" (localhost may not send - if nothing arrives, open the link from the app) | a screenshot |
| D3 | Open the link, answer 2-3 questions, click "This is correct" on ONE of the 3 check items, submit | The summary reads "N of M questions answered - 1 of 3 details checked" (M excludes the 3 check items) | a copy of the summary |

**E. Download:** send the filled ACORD 125 PDF and the pre-download SQS Review list, as before.

### Step 1 - third live run (session `f67bf8ab`, 29 Sep, ACORD_125_FILLED 2)

The owner entered PROPOSED EFF DATE 07/15/2026 on the pre-form screen, then generated ACORD 125 alone.

| Check | Result |
|---|---|
| GL CODE | **"91580, 91585".** This reading stated no applicant GL code, so the Step 1 schedule fallback filled it |
| FEIN | **Blank.** Gap fill wrote the company NAME "ORBIN CONTRACTING LLC" into it this time; an existing guard removed it |
| Driver table after generation (ACORD 125 only) | **Served** by the server (`get_session_schedules` -> `auto_drivers`, 0 rows). The owner's screenshot of the click did not arrive |
| PROPOSED EFF DATE | "07/15/2026", label "filled" (entered pre-form, so stamped from the facts - not the path item 17 fixed) |
| Scores | ACORD 125: 57 -> **62** (Structural 60 -> 80%). Package: 64 -> **66** |
| SQS Review | 6 items (no effective date, no New Venture) |
| Resolved warning | Listed under "Cross-Form Validation - Resolved (1)" with Reopen in the side panel |

**Found on this run:**
1. **Entering the proposed effective date leaves PROPOSED EXP DATE blank, and no card asks for it.** The terms are
   12 months, so it should follow (07/15/2027). This belongs to the Step 2 decision on items 4/11 ("expiration = one
   term later").
2. **Question 4 prints the same four policies in a different ORDER on each run** (this run: Inland Marine, Auto,
   Umbrella, GL). The order follows the fresh reading's summary. Cosmetic, but a client comparing two runs will see
   it. The fix is a stable order, e.g. the order of the dec's own "Coverages and Premium" table.
3. **Workflow:** once forms are generated, the pre-form review screen (warnings, Data Consistency) cannot be reopened.
   Only the side panel remains. This is the client's item 1; it also blocks testing. **Recommended: move it up.**

**Still not tried live:**
- item 17, the green label. Test it now: type a contact name on the side panel's "ACORD 125 missing: contact info"
  card, then open the form. Page 2 CONTACT NAME should be filled and NOT green (verified offline: that card stamps
  `NamedInsured_Contact_FullName_A`, labelled "producer");
- G1 and Q (the questionnaire e-mail and its summary).

### Item 13 - "GL Code, SIC and NAICS are all present in the dec": what the dec actually has (29 Sep)

- **GL CODE: yes.** The GL schedule (page 207) prints 91580 and 91585. They are filled now.
- **SIC and NAICS: no.** They appear nowhere in the 271 pages. Checked two ways:
  - the text of every page, allowing for spellings "S.I.C." and "N.A.I.C.S.", "Standard Industrial", "industry code",
    and 4- and 6-digit industry-code shapes;
  - a visual look at the Common Declarations (page 1) and the Inland Marine declarations (page 3).
- The only "NAICS" in the package is page 127, a generic ISO auto-rating notice with no code for this business.
- What the dec does have is a business description, "BUSINESS DESC: COMMERCIAL GENERAL CONTRA" (pages 3, 85, 143).
  It is cut off on the page itself.
- **Most likely meaning:** Michelle reads "commercial general contractor" plus the GL classes as the SIC / NAICS
  (NAICS 236220 / SIC 1542 for commercial building construction). That is a LOOKUP, not something printed.
- **Why we do not auto-fill it:**
  - A classification code drives rating, and a wrong one is worse than a blank.
  - Run `15f42b1d` proves the risk: gap fill guessed NAICS 238990 and SIC 1799 (specialty trade contractors - wrong for
    a general contractor), and the existing guard removed them.
- **Options for the owner:**
  1. Ask Michelle which page she means.
  2. If she wants help, turn on the producer-side SUGGESTION (her own Figure 20 feature: candidates shown, the producer
     confirms with one click). It is off because her spec 3.13 deferred classification help to Section 19.
- **FEIN:** she is right that it is client / producer-filled. The questionnaire asks for it, and the AI can no longer
  invent one.

### Fourth check - on the same generated session `f67bf8ab` (no new upload needed)

| Step | Where | Do | Expect |
|---|---|---|---|
| T1 (item 17) | Side SQS panel | On "ACORD 125 missing: contact info", type `Erin Royal`, submit | Page 2 CONTACT NAME = Erin Royal, **not green**; the "Client" badge does not count it; the score goes up |
| T2 | Form viewer, Edit Fields | Page 1 PROPOSED EXP DATE: type `07/15/2027`, save | Saved, not green, the yellow gone |
| T3 (G1, Q) | Send to Client | Check the list (FEIN / Tax ID should be Critical). Send it to your own e-mail. Answer FEIN `12-3456789` (dummy), click "This is correct" on ONE of the 3 check items, submit | The e-mail reads "Commercial Insurance Submission Platform". The summary reads "N of M questions answered - 1 of 3 details checked". Back in the app, the FEIN box shows 12-3456789 in **green** (a client answer), and Erin Royal is still not green |
| T4 (item 6, optional) | Send to Client > Fill schedules yourself | Open it | A Drivers table (0 drivers) is offered |

### Fourth check - RESULT (29 Sep, session `f67bf8ab`) - PASSED

Checked on the screen AND in the stored session:

| Step | What the owner saw | What the stored session holds | Verdict |
|---|---|---|---|
| T1 (item 17) | CONTACT NAME = Erin Royal. ACORD 125 score 62 -> 67. "The package score stayed the same" | Box labelled `producer`, NOT in `client_filled_fields`. Fact `contact_name` has source `producer`. The package score moved 66 -> 68 (history stage `arq_remediated`, 05:41) | **Pass** |
| T2 | 07/15/2027 saved, not green | Box `07/15/2027`, label `filled`. Fact `expiration_date` has source `producer`. Package score unchanged at 68 (stage `form_edited`) | **Pass** |
| T3 (G1, Q) | FEIN listed as Critical. E-mail header "Commercial Insurance Submission Platform". Summary "1 of 5 questions answered - 2 of 3 details checked". FEIN green, badge "1 Client" | FEIN `12-3456789`, label `client_arq`, in `client_filled_fields` (the only box there). The questionnaire held 8 items: 5 questions and 3 check items (the location table in confirm mode, the legal name and the mailing address). Two confirmations were stored as `__CONFIRMED__`; they changed no box. Package score 68 -> 69 | **Pass** |
| T4 (item 6) | not done | - | Still open: the server serves the table, but no screenshot of the click yet |

Score history of this session: 63 (pre-form, the effective date) -> 66 (generated) -> 68 (T1) -> 68 (T2) -> 69
(questionnaire). 69 sits in the 60-69 "Major Gaps" band; the form's 72 is "Needs Work". Both are capped at 85 by
"Driver schedule not provided".

**Open points from this check:**
1. **The package score on screen after T1.** The panel replaces the package score from the answer's reply, and the
   reply carried 68. So the "same" reading is not explained by the code. Ask the owner to open "Total Package Score"
   in the side panel: it should read 69. If it does not, the panel is stale and that is a bug.
2. **The producer's receipt counts differently from the client's summary.** "View response receipt" reads
   "3 answered, 8 asked, 2 confirmed as correct". The client's page reads "1 of 5 questions answered - 2 of 3 details
   checked". Both describe the same submission. The receipt counts a confirmation as a response, by the 14 Sep design,
   and a test pins it (`test_the_receipt_files_a_confirmation_as_its_own_kind`). Recommendation: show the client's
   split on the producer's receipt too, and keep the stored counts. That needs the owner's yes, because it reverses
   the 14 Sep choice.

Standing rules for every fix here:
- Replay the stored session (`8992d874`) before and after, and list every box that changed.
- Run the full suite with `py -m pytest -q -p no:randomly`. The only allowed failure is `test_arq_acord125_missing_only`.
- Any prompt change bumps PROMPT_VERSION and gets an `improving-ll.md` entry.
- Never edit `forms_schemas/`.
- Nothing is committed until the owner says so.

---

### Step 2 - started 29 Sep 2026 (owner: "start with step 2 and do it cleanly ... do not break anything that is correctly working")

The owner approved the section 5 recommendations. This log records each change as it lands.

**Scope (client items):**

| # | Decision being built |
|---|---|
| 4, 11 | Proposed dates from the dec: effective = the dec's expiration date, expiration = one term later. Ask only when that next term is already over. Also: when only the effective date is typed, the expiration follows |
| 7, 8 | Page-one carrier and line premiums from the dec when the documents name no submission carrier. NAIC and policy number stay blank. A card asks for anything left blank. The dec agency's phone stays withheld (no change) |
| 12, G2 | Tenant: a one-click confirm showing the evidence, never a silent guess. Location revenue: the business's revenue when there is one location, never "$0". Ask for the landlord when the interest is tenant |
| 5 | Ask Michelle which contact she means. A suggestion for the contact name is being evaluated |
| 15 | An attested "no known losses" makes the loss-history pillar Not Applicable, like a confirmed new venture |
| 2 | The pre-form screen shows the score number, labelled "so far" |

**Baselines recorded before any Step 2 change** (current code, in the scratchpad `pre2/`):
- FR125 test 8 replay: **312 of 312, 0 wrong, 0 missing, nothing made up** (24 of 24 rules pass).
- Orbin `8992d874` replay: only the three Step 1 boxes differ from the stored run.
- A dump of the latest Orbin session `f67bf8ab` (76 of 441 boxes filled).
- The D6 score panel (11 packages, `score_delta_probe.py --save`).

**Method:** first a read-only map of each decision (current code, the tests that pin it, the Orbin data, the
smallest design), then the changes one at a time, then an adversarial review, then the full suite and both replays.

#### Step 2 - items 4 and 11: the proposed term from the dec - DONE (29 Sep)

| | |
|---|---|
| **Root cause** | The 15 Sep rule (`extraction_service._route_renewal_dates`) parked an ENDED current-policy term in `prior_*` and asked for both proposed dates. Separately, nothing derived the expiration when a person supplied only the effective date, and the Tier 1 card offered only an effective-date box |
| **The fix** | 1. An ended current-policy term (or an ended renewal term) now proposes the next term: effective = the dec's expiration, expiration = one repeat of the dec's own term (whole calendar months repeat by months, 29 Feb safe). <br>2. **Stale dec:** when that next term has ended too, or ends within 30 days (`_STALE_PROPOSAL_GRACE_DAYS`), both dates are asked (`_park_stale_term`). This now applies to renewals as well, which used to derive a term that was already over. <br>3. A term outside 300-400 days (for example 6 months) is still asked, as before. <br>4. `follow_proposed_expiration`: when a PERSON supplies or confirms the effective date (producer card, questionnaire, Data Consistency), the expiration follows by the policy's own term. It writes only over a blank or over a date WE derived, and never follows a document's own effective date. It runs on both answer doors (`arq_service._rederive_answer_dependent_facts`, restamped labelled "filled") and after every pipeline re-run. <br>5. On a pipeline re-run, a date we derived never outvotes a person's typed date (`extraction_pipeline._finalize_pipeline`). <br>6. The Tier 1 "Proposed effective date" card now offers an expiration box too; a typed expiration wins |
| **Decisions made on the way** | The 30-day stale window (a proposal about to expire is not a proposal). 6-month and 2-year terms keep today's "ask". The follow rule acts only on a person's (or our derived) effective date |
| **Replays** | Orbin `8992d874` and `15f42b1d`: exactly two boxes change, PROPOSED EFF DATE 07/15/2026 and PROPOSED EXP DATE 07/15/2027. The prior-carrier grid is unchanged. FR125 test 8: **312 of 312, nothing made up, stamps byte-identical** to before Step 2 |
| **Tests** | New `tests/test_step2_orbin_29sep.py` (25). Six existing tests pinned the reversed rule and were updated (the TEST was wrong under the new decision): 3 in `test_remaining_items_15sep.py`, and one each in `test_audit_lineage_20260826.py`, `test_line_binding_14sep.py` and `test_tier1_warnings_persist_23sep.py`. They now use relative dates, so they never age into the stale window. 618 related tests pass |
| **Tool** | `scripts/replay_125_run.py` now re-runs the date routing on the stored facts, so a date change can be measured on a stored session |
| **Score effect (D6)** | UP on packages whose only term is an ended dec. Orbin: the "Proposed effective date" Tier 1 gap closes (measured offline: package +3, ACORD 125 +5); the 85 cap stays because of the contact and driver warnings. DOWN on a stale RENEWAL dec, which used to derive an already-ended term and now asks. Tell Brent |
| **Not changed** | Quotes', applications' and ACORD forms' own terms never move. Certificates (ACORD 25 / 28) print the existing term. Editing PROPOSED EFF DATE directly on the form does not move the expiration (both boxes are in front of the producer) |

#### Step 2 - items 7, 8 and 11: page-one carrier and premiums on a dec upload - DONE (29 Sep)

| | |
|---|---|
| **Root cause** | The 15 Sep page-one rule (`extraction_service._mark_page_one_current_policy`) blanked the carrier and every premium unless a quote or application named them, a person entered them, or the package was a STATED renewal written by one company. A dec almost never says "renewal" (Orbin's 271 pages never do), so a dec-only package always printed a blank page one. Nothing asked for the blank carrier (item 8's "no prompt") |
| **The fix** | 1. `_renews_current_programme`: the upload is the programme's own paperwork (a dec, policy, binder or endorsement; no quote or application), nothing says it is new business, no addressee names another company, the carrier writes a current policy, and the proposed effective date is known. Then the producer is renewing it. <br>2. With that verdict the dec's line premiums and POLICY PREMIUM print on page one. The carrier prints too when ONE company writes every policy. <br>3. **Several writing companies (Orbin: EMCC writes Auto, Inland Marine and Umbrella; EMC Property & Casualty writes GL):** CARRIER stays blank, because naming one would misattribute the other's policy (ACORD's box asks for "the actual name of the company within the group to which the policy has been issued"). A new unscored card, "ACORD 125 missing: carrier receiving this submission", asks for it, worth 0 points. Answering it prints the typed name on page one. <br>4. NAIC stays blank unless printed beside that carrier. POLICY NUMBER stays blank (four different numbers; they are already in question 4 and the prior-carrier grid). The dec agency's phone stays withheld (no change). <br>5. The page-one flags are now recomputed on every run (idempotent), so a replay or re-merge reflects the current rule. <br>6. The 125 grading script (`scripts/audit_125_rules.py`, rules C2 and C5) accepts this approved output when the merge recorded `renews_current_programme` |
| **Decisions made on the way** | A certificate, a loss run or a narrative does not count as the programme's own paperwork. A stale or odd-length dec (whose dates are asked) is not presumed to renew at its old premiums. For two writing companies, "blank plus a card" was chosen over the carrier writing the most lines or the GL carrier (each misattributes a policy). The other defensible option, both names joined ("name(s)" in ACORD's instruction), is the owner's call: it needs the one-carrier guard loosened and prints at about 6pt |
| **Replays** | Orbin `8992d874` and `15f42b1d`: exactly five boxes change beyond the dates, GL 3,954, Auto 2,991 (never the $1,496 Covered Autos part), Inland Marine 300, Umbrella 3,418 and POLICY PREMIUM 10,663. CARRIER, NAIC and POLICY NUMBER stay blank, and no producer box moves. FR125 test 8: **312 of 312, nothing made up, stamps byte-identical**, and C2 / C5 pass |
| **Tests** | `tests/test_step2_orbin_29sep.py` +38 (the presumption and every negative control, idempotency, the stamper, the card, the grader). One existing test updated (the merge test now expects the premiums to print). `test_a_policy_only_package_marks_all_three` still passes as written: with no proposed date known, the dec is not presumed to renew. 866 page-one related tests pass |
| **Score effect (D6)** | None. Carrier and premiums are not Tier 1 or Tier 2 facts and the card is unscored. The ACORD 125 fill rate stays the same (measured 100 -> 100 and 99 -> 99 on the Orbin sessions). Output changes on every dec-only package with no addressee: it now prints the dec's premiums (and a single carrier). **This reverses Brent's answer key "POLICY PREMIUM blank unless known" for dec-only renewals - tell him** |
| **Worth knowing** | The page-one premiums are the ended term's figures standing in as the renewal's, so GL 3,954 and Auto 2,991 also appear in the 2025 prior-carrier row. That is by construction, not a double print |

#### Step 2 - item 5: "Contacts are in the dec" - DONE, one question for Michelle (29 Sep)

| | |
|---|---|
| **What the dec has** | No insured contact anywhere in the 271 pages. The only phone numbers are the agent's (Commercial Risk Solutions, 303-996-7800), claims reporting and the servicing carrier. The only person named is ERIN ROYAL, on the Drive Other Car endorsement (page 92) |
| **Bug found while mapping it** | Entering any contact NAME (as the owner did in the fourth live check) un-ticked the phone and e-mail questions in the questionnaire, because "any one contact method satisfies Tier 1". That broke the approved "phone and e-mail stay asked" |
| **The fix** | A name is not a way to reach anyone. When the contact name is the only contact item known, the phone and e-mail questions stay demoted to Important (Tier 1 is met, so they carry no readiness points) but stay PRE-TICKED (`question_eligibility._only_contact_name_known`, a `force_preselect` overlay honoured by `question_classifier.apply_default_selection`). A known phone or e-mail keeps the 27 Aug (H4) behaviour exactly |
| **Measured on Orbin `8992d874`** | Before: after a name, 7 questions pre-ticked and phone / e-mail NOT among them. After: 9 pre-ticked, phone and e-mail among them. The control (a phone known) is unchanged |
| **Not built, on purpose** | The one-click "Erin Royal" suggestion. Her name is right on this package (Michelle typed it herself on 22 Sep), but the policy never names her as a contact, it gives score credit for a guess, and it rests on one package. It waits for Michelle's answer below |
| **Tests** | `tests/test_step2_orbin_29sep.py` +8. 325 questionnaire tests pass |
| **Score effect** | None (the questionnaire's pre-ticks only) |

**Question for Michelle (item 5):** "The declarations print no phone or e-mail for Orbin. The only person they name is Erin
Royal, on the Drive Other Car endorsement. Is Erin the person the carrier should call about inspections, accounting and
claims? If so, please give her phone and e-mail. Or did you mean the agent's contact, Commercial Risk Solutions,
303-996-7800?"

#### Found during Step 2 (not in the client's list) - logged, not fixed yet

1. **Editing the location table loses data (pre-existing).** Any edit of the "business locations" table (the
   questionnaire's confirm table or the producer's "Fill schedules yourself"), not a plain confirm, rebuilds each row
   from the table's 6 columns. That wipes LOC #, BLD #, county, and the document's interest, city limits, revenue,
   employee counts and areas, and the restamp then blanks those boxes on the forms. It also blanks full-time and
   part-time counts that generation had filled. Found by the item 12 map. Recommended as its own fix after Step 2.
2. **Two pre-form score recipes.** Before forms exist, a fix on the pre-form screen recalculates the package score one
   way, and a page reload another way (Orbin: 60 against 61). Being fixed with item 2, so the number shown never jumps.

#### Step 2 - item 15: an attested "No Known Losses" no longer counts against the score - DONE (29 Sep)

| | |
|---|---|
| **Root cause** | By design (client spec 2.5, Brent's 24 Aug years ladder) an attested "no known losses" scored the Loss History pillar at 60 (85 for a business of 1-5 years), so it still pulled the score down. Michelle: "It should not calculate against the score." ("Max 85%" is not a string in the product; it is her reading of the 85 warning cap or the 1-5 year score) |
| **The fix** | One door, `loss_history_state.attested_no_losses_not_applicable`: an attestation nothing contradicts makes the pillar **Not Applicable** on the package and on every form, the same mechanism a confirmed New Venture uses; the other pillars rescale. It still scores when a loss run is on file (documents win), when the insured also answered "we have had claims", or when a corroborated claim contradicts it (the 45 ceiling stays). The questionnaire state is unchanged, so prior-carrier questions are still asked. The panel says "Not applicable - No Known Losses attested"; the notice is worth 0 points; the "No loss history provided" card shows 0 when attesting cannot raise the score (`_measure_recommendation_impacts`); an old dismissal credit for the attested card now retires instead of stacking (`audit_service`). Frontend: the package N/A chip is no longer hard-coded "No umbrella", and the lite panel shows N/A instead of "null%" |
| **Correction to the plan** | Section 5 said "scores go up". Measured: a Not Applicable pillar raises the score only when the other pillars average above the attested score. Healthy packages go UP; weak packages and some 1-5 year businesses go DOWN |
| **Score effect (D6, measured)** | Orbin 8992 attested: package 65 -> 66 (ACORD 125 63 -> 63). With 12 years in business: 67 -> 69. With 3 years: **71 -> 69 (down)**, ACORD 125 **66 -> 63 (down)**. Orbin f67b attested: 73 -> 75, ACORD 125 78 -> 81. Healthy panel packages reshaped to "no runs, attested": +4 to +6 raw (Workers Comp 87 -> 93). An identity-only package: 52 -> 51. Nothing moves until someone attests. **Tell Brent: his 85 for 1-5 years is no longer reachable for an attestation** |
| **Tests** | 20 existing tests pinned "attested = 60" and were updated (the TEST pinned the reversed rule in every case; no code bug found). 44 new tests. 2,689 loss-related tests pass (the one failure is the known pre-existing `test_arq_acord125_missing_only`) |

#### Step 2 - item 2: the score number before forms - DONE (29 Sep)

| | |
|---|---|
| **The change** | The pre-form Review screen (new layout and legacy) shows the package Submission Quality Score as a number "so far", for example "61 / 100 - Major Gaps", with "It can change when forms are generated." The old "calculated after forms are generated" line is gone. The number comes from the one door (`sqs_service.current_package_sqs`), never the Tier 2 ratio. Reverses the 27 Aug tier-only card (V1 H2) |
| **Root cause found on the way** | Two pre-form recipes. A pre-form fix (Resolve, Reopen or an answer) saved the "no forms" score, while every reload recomputed the door's score, so the number would have jumped after an unrelated fix and back on reload (Orbin: 60 against 61). The pre-form recalculation now saves the door's own recipe and applies no credit before forms exist (no screen can earn one then). Resolve and Reopen now return the door's number and fresh key details, so the "Key details missing" list no longer goes stale after a fix |
| **Score effect (D6)** | Nothing after generation moved (panel 0 of 11). The SAVED pre-form score moves once per session: Orbin up 1 (60 -> 61); complete panel packages down 1-5 |
| **Open (owner's call)** | Before forms, a pre-form fix re-checks the cross-form rules against an EMPTY form set, while the upload checked the recommended forms. So after a pre-form fix, recommended-form warnings can stop capping the score while their card stays on screen (2 of 11 panel packages: 85 -> 87 and 85 -> 86). Pre-existing (the old code did the same, and worse: 85 -> 89); the number is simply visible now. Proposed fix: re-check against the recommended forms with the existing "suggested form = warning" demotion |
| **Tests** | 29 new. `test_h2_readiness_presentation.py` docstring only (all assertions unchanged and passing) |

#### Step 2 - items 12 and G2: tenant, location revenue, landlord - DONE (29 Sep)

| | |
|---|---|
| **Root cause** | Nothing ever asked who owns the premises, the location's revenue, or the landlord. The location boxes were bound only to the document's location schedule, and the location table has no such columns. **Michelle's $300,000 revenue answer never printed anywhere**: no ACORD 125 box reads the business's total revenue |
| **The fix** | 1. Tenant is never inferred. With one location and no stated interest, the ACORD 125 gets a 0-point card "does the insured own or rent <address>?" with the reasons shown. Tenant is pre-selected only when both signals agree (a unit number on the address, and no building insured) and nothing points to an owner (a building value or a mortgagee). Orbin: pre-selected, "unit number on the address (# D13); no building insured (no property coverage)". <br>2. The confirmed answer ticks exactly one of Owner, Tenant or Other. The insured gets the same question as an optional item (not pre-ticked, no evidence text). <br>3. Location revenue is never "$0" by default: with one location and no revenue of its own, ANNUAL REVENUES prints the business's total revenue. Never a model's $0, a range, "Included" or one class's rating exposure; a $0 a person typed does print. <br>4. G2: once the interest is Tenant, the producer and the insured are asked for the landlord's full name and address. Recorded for certificates, **not printed yet** (the 125 additional-interest row and the ACORD 25 holder are Brent's call). <br>5. Two or more locations: unchanged. New module `services/premises_interest.py` |
| **Replays / D6** | FR125: 312 of 312, stamps identical. Orbin: 0 boxes change until someone answers (the session has no revenue and no answered interest). Panel: 0 of 11 moved. The cards are worth 0 points |
| **Tests** | 43 new; no existing test changed. 6,578 related tests pass (the one failure is the known pre-existing one) |
| **Known limits** | The location-table data-loss bug (logged above) can still wipe a DOCUMENT-stated interest and per-row revenue on any table edit; the one-location copies are immune. A producer's manual edit of the one-location revenue box is overwritten if the business revenue is answered later. City limits are out of scope |

### Step 2 - verification (29 Sep) and the live check to run

**Offline, all green:** full suite **10,529 passed / 1 failed / 19 skipped** (the one failure is the known pre-existing
`test_arq_acord125_missing_only`; +187 new tests since 10,342). FR125 test 8: **312 of 312, 24 of 24 rules, stamps
byte-identical to before Step 2**. Orbin `8992d874` replay: exactly 7 boxes change (the two proposed dates and five
premiums). D6 panel: **0 of 12 moved** (one new row for "no loss runs, No Known Losses attested"). Frontend builds clean.

**Live check - needs a FRESH upload.** The stored sessions keep their old merged facts, so the date and page-one
changes show only on a new upload. Restart the backend and `npm run dev`, then hard-refresh the browser.

| # | Where | Do | Expect |
|---|---|---|---|
| L1 (item 2) | Pre-form Review screen | Upload the Orbin dec | "Submission Readiness" shows a NUMBER "NN / 100" with its tier, and "Submission Quality Score so far. It can change when forms are generated." The old "calculated after forms are generated" line is gone. Write the number down |
| L2 (items 4/11) | Pre-form warnings | Look for "Proposed effective date" | **Gone** (the dates come from the dec). "Key details in place" includes the proposed effective date |
| L3 (item 2) | Pre-form | Fix one warning (e.g. contact info: type a name), then press F5 | The number updates after the fix and is the SAME after the reload |
| L4 (items 4, 7, 8) | Generate ACORD 125, page 1 | Read the header | PROPOSED EFF 07/15/2026, PROPOSED EXP 07/15/2027 (marked to verify). Premiums: GL 3,954, Auto 2,991, Inland Marine 300, Umbrella 3,418, POLICY PREMIUM 10,663. CARRIER, NAIC and POLICY NUMBER blank |
| L5 (item 8) | Side panel | Card "ACORD 125 missing: carrier receiving this submission" (0 pts). Try both: (a) type "EMC Property & Casualty Company"; then Reopen and (b) type "Travelers Casualty Company" | (a) Page 1 CARRIER shows it and the premiums stay. (b) CARRIER shows Travelers and the five premiums go blank (EMC's figures are not Travelers' premiums). Neither is green |
| L6 (item 12, G2) | Side panel | Card "ACORD 125 premises: does the insured own or rent ...": Tenant is pre-selected with the reasons shown; click Confirm | Page 2 premises: TENANT ticked, OWNER not. Then two landlord cards (name, address) appear |
| L7 (item 15) | Side panel | On "No loss history provided", choose "No known losses" and submit | Loss History reads "Not applicable - No Known Losses attested"; note the package and form scores before and after |
| L8 (items 5, 12) | Send to Client | Open the list (after L3's contact name) | Phone and e-mail questions still ticked. An optional "own or rent" question may appear (not ticked). Answer revenue $300,000 in the questionnaire: page 2 ANNUAL REVENUES shows 300,000 |
| L9 (item 6, still open) | Send to Client > Fill schedules yourself | Open the Drivers table | Offered with 0 drivers (screenshot please) |

**Report back:** the L1 number, the L3 numbers (after fix / after reload), a screenshot of page 1 (L4), the page 2
premises and revenue boxes (L6, L8), the Loss History row and scores (L7), the Send to Client list (L8), and L9.


### Step 2 - adversarial review (29 Sep) and what it changed

Two independent reviewers read the merged Step 2 code (one on the backend rules, one on the screens and cross-cutting
concerns). Every finding was reproduced before it was acted on.

| # | Finding | Verdict | What changed |
|---|---|---|---|
| R1 (medium, found by both) | The carrier card wrote its answer into `carrier_name`, the documents' CURRENT carrier. A typed new market printed beside EMC's premiums, and the next re-run held the answer as a conflict with the documents | **Fixed** | The card now asks for, and writes, `submission_carrier_name` (the carrier RECEIVING the submission, producer-only). The renewal presumption holds only when that carrier writes a current policy. Page one is re-judged the moment the card is answered or reopened (`arq_service._refresh_acord125_page_one`): CARRIER prints the answer; if the named market writes none of the current policies, the five premiums are blanked. A re-run judges page one again after restoring the answer. Dropped flags are deleted from storage (the facts merge is additive) |
| R2 (medium/low) | The carrier card fired on every ACORD 125 scored before forms existed (the facts-only scorer's mapping is keyed by fact names, so the box always read "blank") | **Fixed** | Only a stamped form's box counts; otherwise the stamper's own resolver decides |
| R3 (low) | Reopening a typed effective date left the expiration it pulled along | **Fixed** | Reopen also removes an expiration that followed the answer; the dec's own dates are untouched |
| R4 (low) | A one-company, one-policy dec now prints its policy number and NAIC on page one | **Kept, on purpose** | It is exactly what a STATED one-carrier renewal already printed before Step 2, and the dec's number and NAIC are the ones being renewed. Orbin (four policies, no NAIC printed) keeps both blank. The owner can ask for them blank |
| R5 (low) | A street name read as a unit ("500 Ste Genevieve Ave", "8 Apt Ln", "55 Unit Dr") and could pre-select Tenant | **Fixed** | The premises rule needs a designator followed by a short identifier ("# D13", "Suite 210", "Unit B"). The shared address-repair rule is unchanged |
| R6 (low, older gap) | A renewal whose term we cannot repeat (6 months, 2 years) still derived an effective date years in the past | **Fixed** | Asked when that term ended more than a year and a month ago |
| R7 (low) | A questionnaire of "please check" items only printed "0 of 0 questions answered" | **Fixed** | That part is left out when there are no questions |
| R8 (low, existing class) | A producer's landlord answer is written in plain text to the recommendation audit and field-change log, like every producer answer | **Logged** | Encrypting or redacting those audit rows is a separate decision (it changes the E&O record for every answer) |

Checked and found sound by the reviewers: no page shows "null%", NaN or "0 / 100" for a missing score; the editor panel is
not touched by the pre-form changes; no new em-dash in any user-facing string; the loss-history Not Applicable pillar is
handled by every consumer; the tenant, other and owner answers restamp and clear correctly.

After the fixes: Orbin replay still changes exactly the 2 dates and 5 premiums; FR125 still 312 of 312 and
byte-identical; D6 panel 0 of 12 moved; frontend builds clean.

**Final full suite after the review fixes: 10,544 passed / 1 failed / 19 skipped** (the one failure is the known
pre-existing `test_arq_acord125_missing_only`). `tests/test_step2_orbin_29sep.py` holds 190 tests. Nothing is committed.

### Step 2 - first live run (session `b8d6cb2d`, 29 Sep, fresh upload, downloaded as ACORD_125_FILLED 3.pdf)

**Note:** the PDF first attached was `ACORD_125_FILLED 2.pdf` (10:54), which is the OLD run `f67bf8ab` - same question 4
order, no expiration. The new run's download is `ACORD_125_FILLED 3.pdf` (16:30), checked field by field below.

| Check | Result |
|---|---|
| L1 pre-form number | **"64 / 100 - Major Gaps"** with "Submission Quality Score so far. It can change when forms are generated." The old line is gone. After generation the package is 66: the "so far" label is doing its job |
| L2 dates | The "Proposed effective date" warning is **gone** (3 warnings -> 2: contact information, driver schedule). Key details 5 -> **6 of 12** in place |
| L4 page 1 | PROPOSED EFF **07/15/2026**, EXP **07/15/2027**. Premiums **GL 3,954, Auto 2,991, Inland Marine 300, Umbrella 3,418, POLICY PREMIUM 10,663**. CARRIER, NAIC, POLICY NUMBER blank. GL CODE 91580, 91585 |
| Cards | "ACORD 125 missing: carrier receiving this submission" (0 pts) and "ACORD 125 premises: does the insured own or rent 4800 DAHLIA ST # D13 ...?" with Tenant pre-selected and both reasons shown. Both as designed |
| Questionnaire | Contact name, phone, e-mail Critical (no contact yet); "Premises interest - owner or tenant" optional and not ticked. As designed |
| Scores | ACORD 125 form 62, package 66 |

**Why ACORD 125 is now first in the form list (owner's question):** nothing in the ranking changed. A form's match score
is 60% "how many of its key facts are known" plus 40% the trigger. Every form counts the effective and expiration dates,
which are now known from the dec (items 4/11). So every score rose: 125 0.80 -> 0.90 (one fact), 127 0.82 -> 0.90, 126
0.77 -> 0.85, 131 0.68 -> 0.83 (two facts each), 137 0.83 -> 0.88. 125 and 127 now tie at 0.90 and 125 lists first.

**Fixed from this run:** the package "Best Solutions" list said "Needs a supporting document - typing cannot close this
one" on the loss gap, while the card under it offers "No known losses". Since item 15 that selection DOES close the gap,
so the row now says "You can answer this directly". A loss gap whose own answer is not the attestation still says it needs
a document. One 23 Sep test pinned the old wording and was updated (the premise changed). 498 related tests pass.

#### Live tests on session `b8d6cb2d` (29 Sep, the owner) - results

| Test | Result |
|---|---|
| 1A carrier card, "EMC Property & Casualty Company" | **Pass.** CARRIER filled, not highlighted, premiums kept |
| 1B carrier card, "Travelers Casualty Company" | **Pass.** CARRIER = Travelers, the five premiums blanked. Rule: page one prints the dec's premiums only on a renewal with a company that already writes the policies (Michelle item 8 + Brent's key "POLICY PREMIUM blank unless known"). The owner may choose to keep them for a new market instead |
| 2 premises card | **Pass** (after Confirm). Database: TENANT "Yes", OWNER "No", labelled the producer's. Two landlord cards appeared |
| 3 no known losses | **Pass.** ACORD 125 62 -> 69, package 66 -> 73. Loss History (25%, weight 15%) leaves the score; the other pillars average about 73: (66 - 25 x 0.15) / 0.85 = 73 |
| 4 questionnaire revenue | First try: the revenue was typed into the FEIN question (FEIN became "30-0000000"; the revenue question was left empty). Second try: **Pass** - `total_revenue` 300000 from the client, ANNUAL REVENUES filled and on the client list. Summary line "1 of 6 questions answered - 0 of 3 details checked" |

**Fixed from these tests:**
1. **An answered box printed unformatted** ("300000", where generation prints "10,663"). The answer paths (producer cards, questionnaire answers) wrote the raw value; generation applies display formatting. Now one helper, `pdf_service.display_value_for_box`, gives both the same printing. Two tests expected the raw value (a name in capitals, "$300,000" in a box whose "$" the form prints) and were updated to the printed form.
2. **A status notice asked for a document.** "No Known Losses attested - Loss History is Not Applicable ..." (and the older underwriting-advisory and New Venture notices) rendered with "attach a supporting document or dismiss it with a note". Such notices are now marked informational and say "For your information - nothing to fill here. Dismiss it once read."
3. (Earlier on this run) the package list's "typing cannot close this one" line on the loss gap.

**Full suite after the live-test fixes: 10,546 passed / 1 failed / 19 skipped** (the one failure is the known pre-existing `test_arq_acord125_missing_only`).

---

### Step 3 / Step 4 - started 30 Sep 2026 (owner: "start with these and fix these properly and do not break anything that is working correctly")

Scope, in the client's own words (`Orbin_Testing_09_22_2026.pdf`):

| # | Client says | What we build |
|---|---|---|
| 9 | "We know what's missing/required/verify. Why can't we put them in the side panel, or better yet, earlier in the workflow pre-form selection." | With item 19: one "Needs attention" list per form in the side panel |
| 19 | "The SQS recommendations are very useful, but they appear way too late in the workflow ... each item to tell me what needs attention, what to do next, and how it could affect the score ... whether information is missing, the AI withheld a value, or an inferred value needs verification. Can the score update as I resolve items? ... the Field QA summary says 4 required fields are empty and 7 AI-inferred fields need verification, but I can't tell which forms or questions it's referring to." | Each row: the question as the form prints it, one tag (Missing / AI held back / Please verify), what to do, the score effect, click to jump to the box. The download review uses the same list and names the form and question |
| 10 | "Make Edit button WAY more obvious ... producers will want to click directly on the form to fix fields, so maybe allow double-click edit." | A prominent Edit button, and double-click on a box to edit it |
| 16 | "Stylistically, this should tuck under 'reviewed' or 'recommendations' after it's been addressed." (screenshot: a resolved hard stop still in the red HARD STOPS block of the side panel) | A resolved hard stop moves to Reviewed, keeping Reopen |
| 18 | "All 'yes' and 'no' questions need to be highlighted and editable for the client or producer to edit. I could not edit them on 126 or 127, but I can on 186." | Find why, fix it for every form |

Method: three builders in isolated copies of the code (A: items 10 + 18, the form viewer; B: item 16; C: items 9 + 19), then a
merge, an adversarial review, the full suite and the replays.

#### Items 10 and 18 - the form viewer - DONE (30 Sep), merged, not yet tried live

| | |
|---|---|
| **Item 18 root cause** | Nothing refused the edit. Every Yes/No box on all 17 forms was already in the viewer's field list, got an input in edit mode, and saved what was typed. The difference is the box SHAPE (measured on the real templates): ACORD 126 and 127 (also 125, 130, 131, 141, 160) print each Yes/No box as a thin strip at the top of a tall answer cell that also holds the explanation row (126: 41 of 48 boxes; 127: 43 of 43). On 186 the box fills its cell (73 of 88), which is why the client could edit 186. The viewer only listened for clicks on the strip, and in edit mode an empty box was white on the white page with no border - so a click in the cell hit nothing and the strip could not be seen |
| **Item 18 fix** | The server now tells the viewer which boxes take a single Y or N, which answer a printed question, and each box's printed answer cell (read from the form's own lines; 235 boxes). In edit mode every Yes/No question box (318 across the forms) has an amber outline and is tinted until answered; a click anywhere in its cell puts the cursor in the box. A Yes/No box accepts only Y or N ("yes" becomes Y) and the save stores Y or N; unreadable input is kept as typed, never blanked. On a Yes/No checkbox pair (ACORD 133) ticking one clears the other. Schedule-row letters (driver rows, certificate columns) are not marked, so empty rows are never flagged. All 358 Yes/No boxes round-trip: typed, saved, printed and read back |
| **Item 10 fix** | The grey "Edit Fields" toggle is now a filled pink "Edit form" button with a pencil, the largest in the toolbar at every screen width; "Done editing - save" while editing. Same save, score refresh and signed-form rules. In view mode a hint reads "Double-click any box to edit it"; double-clicking a box turns editing on with the cursor in it and never changes a value (a checkbox is only focused) |
| **Tests** | New `tests/test_viewer_items_10_18_30sep.py` (91). No existing test changed |
| **Score effect** | None |

#### Item 16 - a resolved hard stop moves to Reviewed - DONE (30 Sep), merged, not yet tried live

| | |
|---|---|
| **Root cause** | Two things. (1) Stale data, which is what the client's screenshot shows: after "Open to fix" the editor merged only the new headline score into the side panel, so the old "caps at 60" data stayed and the fixed stop kept printing in the red block beside a score of 84. (2) Both red blocks (package and per form) printed every cap sentence whatever its status |
| **The fix** | Resolve and Reopen now send the editor the whole recomputed package and form scores (the same numbers a reload shows). The red HARD STOPS blocks list only OPEN stops and disappear when none are open. A stop marked Resolved or Dismissed moves to Reviewed with its Open to fix, its chip and its Reopen; a fixed stop is listed there once (not also in the Cross-Form Validation panel's Resolved list) and survives a reload |
| **Measured on the way** | Marking an item Resolved is only a to-do tick: it never changes the score. So when every stop still holding the score has only been marked, the red block is replaced by a short amber note naming it: "The package is still capped at 60 by an item you marked resolved - reopen it under Reviewed, or fix the value." A 60 is never left unexplained |
| **Not changed, on purpose** | The pre-form screens: they are a checklist that counts handled items in place ("N of M handled"), and every stop stays visible there |
| **Tests** | New `tests/test_item16_reviewed_30sep.py` (37). No existing test changed |
| **Score effect** | None |

Merged together: 909 related tests pass; the frontend builds clean. Items 9 + 19 are still being built.

#### Items 9 and 19 - one "Needs attention" list - DONE (30 Sep), merged, not yet tried live

| | |
|---|---|
| **Root cause** | The three states the client asked about had three owners and no shared door: Missing = the viewer's yellow Required boxes (re-derived on read), AI held back = `guard_blanks`, Please verify = orange low-confidence boxes. The pre-download review re-derived them by its own rules from stored labels only, so it printed internal field names, counted boxes while listing names ("19 fields" beside 10 names), listed the same box ("AdditionalInterest FullName") both as "a value was found but removed" AND "no value found" (two branches of `field_qa.run_field_qa` never looked at each other), called explanation boxes and a checkbox "questions", said "12 required" while the viewer said 14, and named no form (item 19d). Nothing outside the viewer showed any of it before download (item 9) |
| **The fix** | New door `services/needs_attention.py` (GET `/api/needs-attention/{session_id}`, owner-checked). Every box gets exactly ONE tag - Missing, AI held back or Please verify - with the page, the label as the form prints it (from ACORD's tooltip, never an internal name), a plain reason (for held-back values, what was found and what it really was, e.g. 'Found "303-996-7800". Your documents print it as "AGENT PHONE"'), what to do, and the score effect (the scorer's own measured points for that box's fact, else "No score effect"). Precedence: a box with a value is only ever Please verify (and only when the AI inferred it); a box a guard emptied is AI held back and outranks Missing; otherwise an empty required box is Missing. Copies the form already prints elsewhere, unused spare rows, and the explanation boxes behind an unanswered question are not findings; a Yes/No checkbox pair is one question |
| **Where it shows** | (1) The form's side panel: a "NEEDS ATTENTION (N)" section grouped by tag; clicking a row turns the viewer to the box's page and flashes it; the list refreshes whenever the score does (Done editing, card answers, questionnaire). (2) The pre-download SQS Review and the post-download checklist show the SAME live list by form and tag; the stored review rows now name each form and box. (3) Pre-form (item 9's "earlier"): forms do not exist yet, so there are no boxes; one line under "Key details missing" says where the list appears after generation |
| **Measured** | Latest Orbin run `b8d6cb2d`: 10 Missing, 13 AI held back, 0 to verify. Baseline `8992d874`: 13 Missing + 1 required held-back box = the viewer's 14 Required exactly (the old review said 12). The double-listed box now appears once |
| **Tests** | New `tests/test_needs_attention_30sep.py` (34) with a fixture from the two stored runs. One tripwire test updated by design (`test_dec_index_purge`: a new reader of the declarations index must be recorded; this one reads it only for the WORDING of a held-back reason, pinned) |
| **Score effect** | None (display only) |
| **Known limits** | Held-back reasons are derived (guards do not record which rule fired), so a reason can occasionally name a coincidental match; it never changes a status. Optional questions the documents never address, and the "N optional fields left blank by design" count, are no longer listed in the review (not Missing, held back or verify). An unsigned ACORD 125 always opens the review (the signature boxes are Required, as in the viewer); Download Anyway still works |

**All three merged together** (one hand merge in `PDFJsViewer.jsx`, where two builders added lines next to each other): 585 tests across the three items and their neighbours pass; the frontend builds clean; no new lint warnings. Full suite and an adversarial review are running.

#### Items 9, 10, 16, 18, 19 - adversarial review (30 Sep) and what it changed

Two independent reviewers read the merged code (one backend, one the screens and how the three builders' work fits
together). Every finding was reproduced first.

| # | Finding | What changed |
|---|---|---|
| R1 (medium) | A box the producer typed into after generation stayed on the list as "Please verify" or "AI held back" (an edit keeps the old label so its highlight persists), so the list never shrank as items were fixed | A box whose value now differs from what generation stamped was typed by a person and leaves the list |
| R2 (medium) | Unanswered HIGH-IMPACT questions the list does not name vanished from the download review and its record (breaking the Figure 33 rule "a high-impact gap is never buried") | They stay in the review; a box the list already names is never reported twice. One existing test pinned the old hiding and was updated |
| R3 (medium) | On ACORD 125 a "tick one of these" group became one Missing row per checkbox (a nearly empty 125 listed 58 rows, 41 of them line-of-business, entity and nature-of-business boxes) | One row per group ("Lines of business applied for", "Business entity type", "Nature of business") that jumps to the group's first box |
| R4 (low) | A signed form still listed "The applicant signs here" | Skipped once the form is signed |
| R5 (low) | 21 labels were cut mid-sentence at ACORD's double spaces ("The", "That", "An explanation of") | Split only at a sentence end; a test checks every box on all 17 forms |
| R6 (low) | An ACORD 140 COPE gate box appeared twice in the download review (its hard-block row + Missing) | Left to its hard-block row |
| R7 (low-medium) | A jump requested while the viewer was still drawing was lost, then pulled the reader back on the next page turn | The jump watches for the box to be drawn (up to 12 s) and is dropped for good if it never appears |
| R8 (low) | The jump's flash erased item 18's amber Yes/No outline on the box it landed on | The flash uses the outline only and restores what it changed |
| R9 (low) | A jump to another page in edit mode lost the cursor (the viewer rebuilds its boxes after the page draws) | The viewer keeps the cursor on the same box across its own rebuilds |
| R10 (low) | If one form's list failed to build, the review counted the other forms' boxes twice | Stored rows are hidden per form, only where the live list loaded |

Checked and found sound: the new endpoint checks the owner and fails safe on every broken session shape tried; counts
are summed from the rows; page numbers are right; score effects come from the scorer; the Yes/No save only touches
Yes/No boxes (358) and never a box that writes back a fact; nothing writes into `forms_schemas`; the Edit button,
double-click and the Yes/No click area do not interfere; the resolve / reopen replies only gained keys.

Tests: new `tests/test_needs_attention_review_30sep.py` (10). 245 tests across the items pass; the frontend builds clean.

### Items 9, 10, 16, 18, 19 - the live check to run

Restart the backend and `npm run dev`, then hard-refresh the browser. Use the Orbin session already generated
(`b8d6cb2d`) - no new upload needed. For item 18 also generate ACORD 126 and 127 on it (Add forms).

| # | Where | Do | Expect |
|---|---|---|---|
| V1 (item 10) | Form viewer toolbar | Look at the toolbar | A pink "Edit form" button with a pencil, bigger than Refresh and Sign; a slim bar "Double-click any box to edit it" |
| V2 (item 10) | ACORD 125, view mode | Double-click an empty box (e.g. BUSINESS PHONE) | Edit mode turns on, the button reads "Done editing - save", the cursor is in that box, nothing typed |
| V3 (item 18) | ACORD 126 page 2 (and 127 GENERAL INFORMATION), edit mode | Look at the Y/N column; click LOW in a question's Y/N cell (level with its explanation line) | Every Y/N question box has an amber outline (tinted while unanswered); the click puts the cursor in that question's box. Type "yes": shows Y. Type "a": stays. Save: the PDF prints Y |
| V4 (item 9/19) | Side panel | Find "NEEDS ATTENTION (N)" | Groups Missing / AI held back (no internal names like "AdditionalInterest FullName"). Each row: the question, a tag, what to do, "No score effect" or points, a page |
| V5 (item 9/19) | Side panel | Click a Missing row (e.g. "Building is within the city limits") | The viewer turns to its page and the box flashes pink for about 2 seconds; page away - it does not snap back |
| V6 (item 9/19) | Edit mode | Fill that box, then "Done editing - save" | The row disappears and the count drops by one |
| V7 (item 19) | Download | Click Download | The SQS Review shows "Needs attention on the forms" with the SAME rows and tags, by form. No "Field QA: N required fields still empty" line naming nothing. Download Anyway still works |
| V8 (item 16) | A form with a red HARD STOPS block (make one: set PROPOSED EXP DATE on the 125 to a date long past, save) | Click Resolve on the stop | The red block goes; a small amber note says the package is still capped at 60 by an item you marked resolved; the stop is listed under Reviewed with Reopen |
| V9 (item 16) | Same | Reopen it, then fix it with Open to fix (a future expiration) | It returns to the red block; after the fix the score rises, the red block and note are gone, and it shows once under Reviewed |

**Send back:** a screenshot for V1, V3, V4 and V7, and one line each for V2, V5, V6, V8 and V9 (what happened).
Then set the 125's expiration back to 07/15/2027.

**Full suite after items 9, 10, 16, 18, 19 and the review fixes: 10,717 passed / 1 failed / 19 skipped** (the one failure is the known pre-existing `test_arq_acord125_missing_only`). Nothing is committed.

**Superseded by the final run below.** V8's "a date long past" makes TWO stops (expiry before the effective date is
its own hard stop), so the final script uses 08/01/2026: after the 07/15/2026 effective date, over 30 days past, and a
producer-typed date, so exactly one hard stop ("Policy term already expired").

### Final localhost run - 30 Sep 2026 (the script)

One fresh upload of the Orbin dec, with the five forms Michelle tested (125, 126, 127, 131, 186), plus a 2-minute check
on the old 125-only session `b8d6cb2d` for item 6 (its bug shows only when ACORD 127 is NOT chosen). Covers 20 of the
22 points; 1 and 14 are not built.

| Test | Covers | Do | Expect |
|---|---|---|---|
| A1 | 6 | Old session `b8d6cb2d`: side panel, "Driver schedule not provided", Open to fix | An empty Drivers table opens, no error. Close without saving |
| B1 | 2 | Fresh upload, pre-form Review | "NN / 100 - tier" and "Submission Quality Score so far" (last time 64) |
| B2 | 3, 4, 11 | Pre-form warnings | No "Proposed effective date" warning; no "Important" block; "Key details in place" lists the proposed effective date |
| B3 | 9 | Under "Key details missing" | "After you generate forms, each form's side panel lists the boxes to fill or check ..." |
| B4 | 2, 5 | Contact information warning: type only the name "Erin Royal", save; note the score; F5 | Same number after the reload |
| C0 | - | Choose 125, 126, 127, 131, 186; generate | Note the package and form scores (they differ from 125-only runs) |
| D1 | 4, 7, 8, 11, 13 | 125 page 1 | 07/15/2026 - 07/15/2027; GL 3,954, Auto 2,991, IM 300, Umbrella 3,418, total 10,663; GL CODE 91580, 91585; CARRIER, NAIC, POLICY NUMBER blank |
| D2 | 10 | Toolbar | Pink "Edit form" button with a pencil, the biggest; bar "Double-click any box to edit it" |
| D3 | 9, 19 | Side panel "NEEDS ATTENTION (N)" | Missing / AI held back groups, form wording, a tag, What to do, a score line, a page (last time 10 + 13). Rows say "No score effect": true, those boxes do not feed the score |
| D4 | 9 | Click Missing "Number of square feet of the building ..." | Viewer turns to page 2, the box flashes pink about 2 s; scrolling away does not snap back |
| D5 | 10 | Double-click that box in view mode | Edit mode on, "Done editing - save", cursor in the box, nothing typed |
| D6 | 9, 19 | Type 1200, Done editing - save | The row leaves the list, count down by 1 (the box writes no fact: no score change) |
| E1 | 7, 8, 17 | Carrier card: "EMC Property & Casualty Company" | CARRIER prints exactly that; premiums stay; not green |
| E2 | 12 | Premises card, Tenant pre-selected: Confirm | TENANT ticked, OWNER not; two landlord cards appear |
| E3 | G2 | Fill both landlord cards (test values) | Cards close, no error; nothing prints (Brent's call) |
| E4 | 15 | Note scores; "No known losses" on the loss card | Loss History Not applicable; scores up (last 62 -> 69, 66 -> 73); notice reads "For your information - nothing to fill here. Dismiss it once read." |
| F1 | 16 | 125 page 1 PROPOSED EXP DATE = 08/01/2026, save | Red HARD STOPS "Policy term already expired (08/01/2026) ..."; score 60 |
| F2 | 16 | Resolve | Red block gone; amber "... still capped at 60 by an item you marked resolved - reopen it under Reviewed, or fix the value."; stop under Reviewed with Reopen |
| F3 | 16 | Reopen; then Open to fix, expiration 07/15/2027 | Back in red after Reopen; after the fix score back up, no red block, no note, listed once under Reviewed, page 1 07/15/2027 |
| G1 | 4 | Header EFFECTIVE DATE on 126, 127, 131, 186 | 07/15/2026 on each |
| G2 | 18 | 126 page 2, Edit form; click low in an EMPTY Y/N cell; type "yes", then "x"; save; then clear and save | Amber outlines, empty ones tinted; cursor lands in the Y/N box; "yes" -> Y, "x" keeps Y; the form shows Y |
| G3 | 18 | Same on 127 GENERAL INFORMATION | Same |
| G4 | 18 | Same on 186 (control) | Still works |
| G5 | 9 | NEEDS ATTENTION on 126, 127, 131, 186 | A list on each (counts) |
| H1 | 5 | Send to Client list | Phone and e-mail still ticked though a contact name is known |
| H2 | G1 | Send to own e-mail | "Commercial Insurance Submission Platform" |
| H3 | Q | As the client, answer ONLY annual revenue 300000 (not the FEIN question); submit | Summary counts questions and "details checked" separately |
| H4 | 12, 17 | 125 page 2 ANNUAL REVENUES after a reload | "300,000", GREEN (pink = the label "AI, found in documents": screenshot and hover if so) |
| I1 | 19 | Download | "Needs attention on the forms (N)" by form, same rows and tags; no "Field QA: N required fields" line naming nothing; Download Anyway works |

#### Results, part 1 (30 Sep; A1 on `b8d6cb2d`, the rest on the fresh session `17351800`)

The owner generated 125, 127, 131 and **137 CO** (not 126 and 186), so G2 (126) and G4 (186) cannot run on this session.

| Test | Result |
|---|---|
| A1 (6) | **Pass.** "Update the schedule ... 0 drivers ... + Add driver", no error. Item 6 verified live |
| B1 (2) | **Pass.** 64 / 100 |
| B2 (3, 4, 11) | **Pass.** Two warnings only (contact information, driver schedule); no proposed-date warning; no Important block |
| B3 (9) | Shown. **Owner: remove the line and do the action instead** |
| B4 (2, 5) | **Pass.** 66 after the fix, 66 after F5. (F5 drops back to the dashboard and the package must be reopened: that is item 1) |
| C1 | Package 68; 125 67, 127 69, 131 82, 137 CO 70 |
| D1 (4, 7, 8, 11, 13) | **Pass** (downloaded 125): 07/15/2026 - 07/15/2027, the five premiums, GL CODE 91580, 91585, CARRIER blank |
| G1, part (4) | **Pass** on 127, 131, 137 CO: EFFECTIVE DATE 07/15/2026 |
| D3 (9, 19) | The list shows: 26 = Missing 12, AI held back 13, Please verify 1. Every row "No score effect" (true: none of those boxes feeds the score) |
| I1 (19) | "Needs attention on the forms (69)" by form, and Download Anyway works; **but** 4 rows still print internal field names (found 3 below) |

"13 held back in the side panel, 15 in the review" is **not** a bug: at 10:12 UTC an edit changed page 1's producer
e-mail from `.com` to `.co` (edit log); the two contact e-mail boxes the guard blanked held the `.com` e-mail, which page 1
no longer printed, so they became findings. The viewer has no length limit: the `.co` is a keystroke.

**Found in this run, NOT fixed yet** (no code touched while the owner tests):
1. **Wrong value: 125 page 2 CONTACT TYPE prints "Erin Royal".** The AI copied the contact's name into "the type of
   contact (e.g. accounting, claims)" (label `ai_verified`). A type box must never repeat its entity's name.
2. **Misleading held-back reason for invented values.** "Found "84-1234567"" (FEIN) and "Found "1521"" (SIC): the AI made
   them up and the guards blanked them because they are NOT in the documents, but "Found" reads as if the dec prints them.
   It backs Michelle's wrong SIC claim (item 13) and invites typing a fake FEIN. Guards do not record which rule fired,
   so the door cannot tell; fix at the source (the guard records why) and never show an invented identifier.
3. **Internal field names are back** in the review's "N high-impact questions were left blank by the AI" rows and on
   the cover page ("AdditionalInterest FullName", "CommercialPolicy ApplicantOwnLeaseOperateDronesExplanation"): exactly
   Michelle's item 19 complaint, and they list explanation boxes that are not questions. The 30 Sep review (R2) kept
   those rows but not their wording. Item 19 is not clean until they use the form's wording (or join the list).
4. **This run's extraction paired the GL premium with the Inland Marine policy.** `coverage_lines` "Liability" =
   Employers Mutual / 6C7-40-02---26 / $3,954 (b8d6 and f67b read it right: EMC P&C / BBC7263 - 26). So question 4
   prints "Liability 6C7-40-02---26" (Inland Marine missing) and page 4's GL prior-carrier column is blank (two policies
   on one line). Our code should have caught it: 6C7's own declarations say Inland Marine and the GL's say BBC7263 - 26.
5. **Double-click selects the box's whole text**, so one stray key wipes a filled value before "Done editing - save".
   Put the cursor at the end instead (Y/N boxes keep select, one letter).
6. Minor: a 127 reason says "the auto vin schedule" (internal name); BLD # prints "# D13" (the suite, flagged Please
   verify); OWNER / TENANT and INSIDE / OUTSIDE are listed as single boxes, not pairs.

**Owner's UI asks:** a smaller "Done editing - save" button; remove "Unsaved - score updates when you save" (it wraps the
toolbar to two lines); remove the pre-form pointer line (B3) and give the pre-form step a real action.

**Owner (after two more screenshots: toolbar "2/5", page 1 drawn, page 2's yellow boxes and "# D13" on it, worse after
Edit form): "First fix all the pointed out issues ... fix and i will retest again."**

#### Fixes from part 1 (30 Sep, evening) - offline-verified, NOT yet tried live

| # | What was wrong | Root cause | Fix |
|---|---|---|---|
| 1 | The viewer drew page 1 with page 2's boxes on it (random yellow boxes, "# D13" on page 1); Edit form "broke it again" | Two races. (a) A page render cancelled the previous one BEFORE loading its page, so a render still loading was never cancelled and the slower one painted last. (b) The redraw after "Done editing - save" and after signing painted the page the reader was on when they CLICKED. And the overlay was always built for the toolbar's page number, so every later rebuild (Edit form) drew page 2's boxes over the stale page 1 | Each render takes a ticket and paints off screen; only the newest ticket swaps its page in, in one step. The viewer records the page the canvas really shows and builds the boxes (and the double-click hit test) for THAT page. The save and sign redraws use the page the reader is on when they finish |
| 2 | Double-click selected the box's whole text | Select-all on focus | The cursor goes to the end, nothing selected; Y/N boxes keep select (typing replaces Y/N). A rebuild while typing keeps the cursor where it was |
| 3 | 125 CONTACT TYPE printed "Erin Royal"; BLD # printed "# D13" | Gap fill copied the box beside it (the contact name; the suite on the street line) | New post-fill check: an AI value in a box that asks for a TYPE or a NUMBER is blanked when it repeats a name or address box of the same entity and row (`pdf_service._blank_neighbour_copies`). AI values only |
| 4 | 'Found "84-1234567"' (FEIN) and 'Found "1521"' (SIC): both invented by the AI | Guards do not record why they blanked, so the reason could not tell an invented value from a real one | The guard report records `in_documents` (same text test as the ungrounded-identifier guard). "Found" only for a value the documents or our own records hold; a value the documents never print says so and is never quoted; an identifier or code of unknown origin is never quoted. Our agency's own e-mail / phone are named as such |
| 5 | Internal field names back in the review and on the cover page ("AdditionalInterest FullName", "...DronesExplanation") | The 30 Sep review kept the unanswered high-impact rows but not their wording; explanation boxes, checkbox options and refused boxes counted as "questions left blank" | Real Y/N questions the documents do not answer are now in the NEEDS ATTENTION list as Missing ("An underwriting question your documents do not answer"), in the form's words. An explanation box follows its question; an unticked checkbox option is not a gap; a box a guard emptied was ANSWERED and is never also "left blank". Remaining rows use the form's words ("boxes", not "questions") |
| 6 | Cover page (goes to the underwriter) listed "AI held back" / "Please verify" rows | Every open review row was copied onto it | Those two are the producer's to-dos and stay off the cover page; "Missing" rows stay |
| 7 | Question 4 "Liability 6C7-40-02---26" (Inland Marine missing); page 4 GL column blank | The AI tagged every Common Declarations entry with the NEXT page's inland marine number (page 1 prints no policy number), so "Section 2 Liability $3,954" became evidence that GL was policy 6C7 and the repair saw no contradiction. The 28 and 29 Sep runs read it right | An entry keeps its policy-number tag only if a page printing that number also prints the entry's value (`_verify_dec_entries`). Then the repair fires; two printings of one contract ("BBC7263" / "BBC7263 - 26") are one candidate, not a choice; a re-paired row takes its contract's carrier from the untouched row that prints it |
| 8 | Smaller things | - | OWNER/TENANT and INSIDE/OUTSIDE listed as the choice ("interest ... (owner, tenant or other)"); schedules named in the producer's words ("vehicle schedule", not "auto vin schedule"); a label no longer cut inside ACORD's own quotation; a count "1" is not a Yes/No answer |
| 9 | Owner's asks | - | "Done editing - save" smaller (the "Edit form" button unchanged); the "Unsaved" toolbar line removed (the side panel still says the score is from the last save); the pre-form pointer line removed and each "Key details missing" item is now a link that opens the same fix window the warnings use (score and list refresh from the reply) |

**Proof (offline):**
- FR125 test 8 replay: **312 of 312**, 24 of 24 rules, stamps byte-identical to the 29 Sep base (only today's date).
- Orbin 8992 replay: stamps identical to the 29 Sep replay apart from the known Step 2 boxes; the new entry check drops 4
  number tags there and changes no coverage row.
- The owner's run `17351800` replayed: exactly 15 boxes change, all intended - CONTACT TYPE and BLD # blank, question 4
  = CGL BBC7263 - 26 / Commercial Inland Marine 6C7 / Commercial Auto 6E7 / Commercial Umbrella 6J7, and the GL
  prior-carrier column restored (EMC P&C, BBC7263 - 26, 3,954, 07/15/2025 - 07/15/2026).
- `scripts/replay_125_run.py` now re-runs the entry check, the coverage repair and the per-policy records, as a fresh
  upload does, and honours the new check's `DROP_NEIGHBOUR_COPY` log line.
- Tests: new `tests/test_final_run_fixes_30sep.py` (29). Updated by design, reason written in each: the pointer-line test
  (now "key details are actions"), the "Unsaved" and hit-test pins, the edit-button CSS pin, four list-count pins (+1
  unanswered question), the viewer-badge test (counts REQUIRED rows only), the double-listing test (now fixed at the
  source), the key-details shape test (additive key), two card tests (the line moved into its component), one wording
  pin ("The AI suggested"). 1,072 related tests pass; frontend builds clean, 0 lint errors.
- **Full suite: 10,746 passed / 1 failed / 19 skipped** (the one failure is the known pre-existing
  `test_arq_acord125_missing_only`). After it: a failed redraw after a signature is applied now reloads the form (the
  current page is drawn, the busy state clears, the form stays signed); 346 viewer and list tests re-run green.
- Nothing is committed or deployed.

**Not changed, on purpose:** the extraction prompt (no PROMPT_VERSION bump); the per-line carrier index (it lists phone
numbers as carriers - noisy, but a separate change).

#### Retest after these fixes - the script (fresh upload needed: fixes 3, 4, 5, 7 act when the dec is read)

Restart the backend and `npm run dev`, hard-refresh. Upload the Orbin dec fresh. Choose **125, 126, 127, 131 and 186**.

| Test | Covers | Do | Expect |
|---|---|---|---|
| R1 | 2, 5, 9 | Pre-form: click "Number of employees" in "Key details missing"; type 5; apply. On the Contact information warning type only the name "Erin Royal". Then F5 | The fix window opens; after apply the item moves to "in place" and the score updates at once; same number after F5. No pointer line |
| R2 | 1 (viewer) | On the 125: click "Show on form" rows on pages 1, 2, 3 quickly; turn pages; toggle Edit form on and off; save an edit and turn a page while it saves | The boxes always sit on the page shown. No yellow boxes in page 1's text, no "# D13" on page 1 |
| R3 | 10 | Edit form | One toolbar line; "Done editing - save" smaller than "Edit form" was; no "Unsaved" text. Double-click a FILLED box: cursor at the end, nothing selected |
| R4 | new | 125 page 2 and 3, page 4 | CONTACT TYPE not a person's name; BLD # not "# D13". Q4: CGL BBC7263 - 26, Commercial Inland Marine 6C7, Commercial Auto 6E7, Commercial Umbrella 6J7. Prior carrier: GL and Auto columns filled |
| R5 | 9, 19 | NEEDS ATTENTION on 125 and 127 | No "Found" for FEIN / SIC; premises rows read "(owner, tenant or other)" and "inside or outside the city limits"; "Any area leased to others?" and the 127's unanswered vehicle questions listed as Missing |
| R6 | 9, 10 | Click a Missing row; double-click its box; type; Done editing - save | Jump + flash; cursor in the box; the row leaves and the count drops by 1 |
| R7 | 7, 8, 17 | Carrier card: "EMC Property & Casualty Company" | CARRIER prints it; premiums stay; not green |
| R8 | 12, G2 | Premises card: Confirm Tenant; fill both landlord cards | TENANT ticked; the owner/tenant row leaves the list; landlord cards close |
| R9 | 15 | "No known losses" | Scores up; notice "For your information - nothing to fill here. Dismiss it once read."; page 4 "Check if none" |
| R10 | 16 | PROPOSED EXP DATE 08/01/2026, save; Resolve; Reopen; Open to fix 07/15/2027 | Red stop -> Reviewed + amber note -> back to red -> cleared, score back up |
| R11 | 18 | 126 page 2, 127 GENERAL INFORMATION, 186: Edit form, click low in an empty Y/N cell, type "yes" then "x", save, then clear | Amber outlines; cursor lands in the box; "yes" -> Y, "x" keeps Y; saved |
| R12 | 5, G1, Q, 12, 17 | Send to Client; send to your e-mail; as the client answer only revenue 300000 | Phone / e-mail still ticked; tagline; summary counts separate; ANNUAL REVENUES "300,000" in green |
| R13 | 19 | Download | Review: no internal names anywhere; cover page "Red Flags" has Missing rows but no "AI held back" / "Please verify" |

#### Retest, part 2 - results (30 Sep, fresh session `8739a72a`, forms 125 / 126 / 127 / 131 / 186, ACORD_125_FILLED 3)

Checked by the owner on localhost, then box by box by us from the stored session and the downloaded 125.

| Test | Result | What we saw |
|---|---|---|
| R1 | **Pass** | Each "Key details missing" item opens its fix window; the contact name moved to "Key details in place". One warning left: "Driver schedule not provided" (the policy schedules no drivers - Chat 5, accepted) |
| R2 | Not run | Owner asked for clearer steps - rewritten as numbered steps below |
| R3 | **Pass** | One toolbar line, smaller save button, no "Unsaved" line |
| R4 | **Pass, one fix** | CONTACT TYPE and BLD # blank; question 4 lists all four policies with their numbers; prior-carrier GL and Auto columns filled (EMC P&C BBC7263 - 26 3,954; Employers Mutual 6E7 2,991). The auto row was named "COVERED AUTOS LIABILITY" (a coverage part) - fixed below |
| R5 | **Pass** | Premises rows in the form's words; 127's unanswered vehicle questions listed as Missing; "Any area leased to others?" listed (as AI held back: the AI said Yes with nothing in the documents). The FEIN and SIC rows quote a REAL document value and say what it really is ("Account Number", the auto class code); the invented NAICS says "not in your documents" |
| R6 | **Pass** | Jump to the box and double-click edit work |
| R7 | **Pass** | CARRIER (page 1, top right) prints "EMC Property & Casualty Company" |
| R8 | **Pass** | Landlord "vinay p" / "noida 22" stored (printed nowhere - Brent's call) |
| R9 | **Pass, one fix** | Package 68 -> 75 (125 67 -> 75, 126 74 -> 82, 127 69 -> 77, 131 82 -> 85, 186 57 -> 63); Loss History became Not Applicable. Page 4 "Check if none" stayed unticked and stayed in the list - fixed below |
| R10 | **Pass** | 60 -> Resolve -> "still capped at 60 by an item you marked resolved" -> date fixed -> score back up |
| R11 | **Pass (126)** | Only Y or N can be typed. Two answers WERE saved at 16:19 (126 "Does applicant install, service or demonstrate products?" = Y, "Foreign products, sold, distributed, used as components?" = N); the later removal was not saved. 127 / 186 not tried |
| R12 | **Pass, one open** | Phone / e-mail still ticked, tagline, separate counts ("1 of 6 questions answered - 0 of 4 details checked"), ANNUAL REVENUES "300,000". "Pink" NOT reproduced: the box is stored as the client's, and the downloaded 125 paints it green (measured pixel 186,247,209). The viewer's only pink fill means "AI-OK"; the jump flash is a pink OUTLINE. Owner to press Refresh and send a screenshot if it is still pink |
| R13 | **Pass, one fix** | No internal names except four rows "Producer AuthorizedRepresentative FullName on ACORD 125 shows "Vinay Sharma" but the source value is "Vinay Sharmaa"" - wording fixed below. The rows themselves are right: the producer contact was edited to "Vinay Sharmaa" (typo) at 15:38. Cover page not checked |

Item 4 also closes: the stored run prints EFFECTIVE DATE 07/15/2026 on 126 and 186 as well.

**Where each 125 value came from (owner asked "did you hardcode anything?") - checked box by box, nothing is keyed to
Orbin:**
- From the dec: line premiums and 10,663, lines of business, names, addresses, GL codes 91580 / 91585, LLC, the question
  4 policies, the prior-carrier rows, audit "A" (the dec prints "Audit Period: Annual"), the operations description.
- Read from a dec LABEL (an inference): billing "Direct bill" from "DIRECT BILL AGENT PHONE".
- By rule, not typed: today's date, the form's edition, STATUS = QUOTE, the attachment ticks (the forms chosen),
  question 4 = Y (the policy list), PROPOSED EFF 07/15/2026 (= the dec's expiration), prior year 2025, LOC # 1.
- Typed by the owner: contact "Eirn Royal" (typo), producer contact "Vinay Sharmaa" (typo), CARRIER, TENANT, PROPOSED EXP
  07/15/2027 (typed in R10; a fresh run computes the same date as the dec's expiration + one term), landlord.
- From the client: revenue 300,000. From the login: producer name and e-mail.

#### Fixes from part 2 (30 Sep, night) - offline-verified, NOT yet tried live

| # | What was wrong | Root cause | Fix |
|---|---|---|---|
| 1 | "Check if none" (125 page 4) stayed unticked after "No known losses", and stayed in the list | The box-to-fact link ran one way: ticking the box wrote the fact (`pdf_service._FORM_FIELD_WRITEBACK`), but answering the fact never found the box (`arq_service._canonical_keys_for` did not read that table) | The lookup includes the write-back links: the answer ticks the box (125 and 131, which ask the same thing) and reopening the answer clears it |
| 2 | Question 4 named the auto policy "COVERED AUTOS LIABILITY" | With no ACORD line name printed, the per-policy record took the LONGEST printing, and the coverage part is longer than "Automobile" | Then the policy is named by the row carrying its full premium ($2,991 "Automobile" over $1,496 "COVERED AUTOS LIABILITY"); no premiums: longest, as before. An ACORD line name still wins |
| 3 | Review rows "Producer AuthorizedRepresentative FullName on ACORD 125 shows ..." | The four value-check row types still used the internal-name wording | Every review row speaks the form's words: `ACORD 125: "<the form's label>" shows ...` |
| 4 | Owner: the side-panel list as two dropdown sections with (i) tips, styled like Recommendations | - | "Needs attention (N)" and "AI held back (N)" are two collapsible sections drawn with the side panel's own section component, closed by default, each with an (i) tip; expanding shows every item |
| 5 | Owner (R1): which key details the client usually answers | - | Each fix window says who answers: FEIN, revenue, employees "If you don't know it, leave it - Send to Client asks the client"; NAICS / SIC "comes from you or the underwriter - the client is not asked for it" (client PART 13, 12 Aug) |

**Proof:** FR125 test 8 replay 312 of 312, stamps byte-identical to the 29 Sep base (only today's date). Session
`8739a72a` replayed: the policy records read Automobile / Commercial General Liability / Commercial Inland Marine /
Commercial Umbrella; answering "No known losses" ticks 125 and 131 and both loss rows leave the list. Tests: +4 in
`tests/test_final_run_fixes_30sep.py`, the side-panel pin updated in `tests/test_needs_attention_30sep.py`, the grouped-
row wording pin in `tests/test_live_run6_fixes_15sep.py` (it pinned the internal name the owner asked us to remove).
Frontend builds; 0 lint errors. **Full suite: 10,750 passed / 1 failed / 19 skipped** (the one failure is the known
`test_arq_acord125_missing_only`).

**Found, not fixed (next round):**
- **A box the producer types over keeps the AI's label.** `form_routes.update_pdf` promotes only `missing_required` to
  `filled`, so a producer's answer in a box the AI had touched stays `low_confidence`: the viewer paints it orange ("AI,
  verify") and the fill rate counts it at 0.50 instead of 1.00. Seen on the two 126 answers above. The fix is one rule,
  but it moves scores UP a little, so Brent hears first (D6).
- **Question 4 depends on WHEN the carrier is answered.** The receiving-carrier filter keeps only that carrier's
  policies. Answered after generation (this run), question 4 kept all four; regenerated with EMC P&C named, it lists
  only BBC7263 (the other three are written by Employers Mutual Casualty Company). Which is right is the parked
  "two EMC companies" question.

**Owner's questions, answered:**
- *Did the client ask for the pre-form key-detail links?* No - the owner asked (30 Sep evening: give the pre-form step a
  real action). Michelle's item 9 asked for the list "earlier in the workflow pre-form selection".
- *NAICS / SIC answered by the client?* The client said the opposite, PART 13 (12 Aug): "We should not be asking the
  client for the NAICS or SIC class codes; those come from the producer or underwriter." Owner ruling D-FS: "no keep them
  in agency and put a critical tag on naic and sic as well." Unchanged.
- *Where did "Needs attention" / "AI held back" come from?* Michelle, item 9: "We know what's missing/required/verify.
  Why can't we put them in the side panel, or better yet, earlier in the workflow pre-form selection." Item 19b: "I'd
  like each item to tell me what needs attention, what to do next, and how it could affect the score. It should also be
  clear whether information is missing, the AI withheld a value, or an inferred value needs verification."
- *"Loss History +11.2 pts 25%"?* 25% is the Loss History score for the whole package; +11.2 is what the package would
  gain if it reached 100%: Loss History weighs 15%, so 75 x 15% = 11.25. After "No known losses" it is Not Applicable,
  leaves the list, and its weight is shared by the other pillars.

#### R2, rewritten as steps (the viewer fix: page 2's boxes drawn on page 1)

1. Open ACORD 125 in the editor, on page 1. In the side panel open "Needs attention".
2. Click "Show on form" on a page 2 row, then at once a page 1 row, then a page 3 row. Do not wait between clicks.
3. After each click: the pink flashing outline sits on a box of the page you see; no yellow boxes over printed text;
   "# D13" never on page 1.
4. Page arrows: 1 -> 2 -> 3 -> 2 -> 1, fast. Same check.
5. "Edit form", then "Done editing - save" with no change. Twice. Same check.
6. Open ACORD 126, page 2. "Edit form", clear the two answers saved in R11 ("Does applicant install, service or
   demonstrate products?" = Y, "Foreign products, sold, distributed, used as components?" = N), click "Done editing -
   save" and, while it saves, click to page 3. When it finishes, page 3 shows page 3's boxes, and the two boxes on
   page 2 are empty.
Pass = the boxes always belong to the page shown. If not: a screenshot and the step number.

#### The "done in part" items, finished (30 Sep night - 1 Oct) - offline-verified, NOT yet tried live

Owner's decisions (30 Sep): CARRIER prints both companies; the landlord prints on the 125's Additional Interest
row; the Yes/No questions stay the producer's (not offered in Send to Client); items 1 and 14 not started yet.

| Item | What changed | Why this way |
|---|---|---|
| 7 | A renewal of a programme several companies write prints them all on page 1's CARRIER: "EMC Property & Casualty Company; Employers Mutual Casualty Company". NAIC and POLICY NUMBER stay blank (one box, two companies / four policies). The "carrier receiving this submission" card no longer fires for it. A company a person or a document names still prints alone, and question 4 now moves with a carrier named after generation | ACORD's own tooltip for CARRIER: "full legal company name(s) ... the actual name of the company within the group ... not the insurer's group name". The insurer guard now checks EACH listed company - one invented name still blanks the box |
| 7 (phone) | No code. Account Settings has "Contact Phone"; set it and page 1's producer PHONE prints it on the next upload. The dec's phone belongs to Commercial Risk Solutions, another agency, and prints only when that agency is the one logged in (the rule already) | - |
| G2 | A tenant's landlord prints on 125 page 3, ADDITIONAL INTEREST row A: name, address, OTHER ticked with "Landlord", CERTIFICATE REQUIRED ticked, LOCATION 1. It prints the moment it is answered (producer card or client questionnaire) and reopening the answer clears it. Only with one premises, Tenant, a name given, and no loss payee / mortgagee / document interest already on row A | Never ADDITIONAL INSURED - that requests coverage the lease may not require. Two guards were deleting it: "Landlord" read as a role in a NAME box (now allowed in the 7 "type of additional interest" boxes only), and the name test deleted a person's own typed name ("vinay p") - a guard now never second-guesses a value a person gave |
| 8 / 11 | A ticked line of business whose premium box is blank, and a blank POLICY PREMIUM beside ticked lines, are listed in "Needs attention" as Missing - "Enter it on the form if you know it." A producer to-do, kept off the underwriter's cover page (a quote's premium is blank until quoted) | Each line's tick is paired with its own premium box by ACORD's wording (all 15 lines on the 125). Nothing is filled or guessed |
| 18 (client) | No change - owner's decision: the unanswered Yes/No questions stay the producer's | - |
| Found | A box the producer types over is the producer's: label "producer" (not the AI's orange "verify"), weight 1.00; a client box the producer retypes leaves the client's green | Reverses the old "so pink highlights persist" rule. D6: ACORD 126 fill rate 93 -> 95 on the owner's session (the two typed Y/N); nothing else moves |

Not code, explained: 5 (the dec prints no insured contact), 12 ("$0" would be a wrong value - ACORD's box is "the
annual revenue amount for this location"; the pink needs a screenshot), 13 (SIC and NAICS are not in the dec).

**Proof (offline):** FR125 test 8 replay **312 of 312**, stamps identical to the 30 Sep replay apart from today's
date. Session 8992 replay: only CARRIER changes (both names). Session 8739 replay: only the landlord row prints ("Vinay
P", "Noida 22", Other: Landlord, certificate, LOC 1). Tests: new `tests/test_partial_items_30sep.py` (20). Updated by
design, reason in each: two Step 2 carrier pins (the 29 Sep blank + card the owner reversed) and three needs-attention
count pins (+5 blank premiums on the b8d6 / 8992 fixtures). **Full suite: 10,770 passed / 1 failed / 19 skipped** (the
one failure is the known `test_arq_acord125_missing_only`). No frontend change this round.

#### Verify all together - the script (1 Oct)

Restart the backend and frontend, hard-refresh. **Before uploading, add your phone in Account Settings (Contact
Phone).**

**A. Your current session (8739a72a) - no upload**

| # | Covers | Do | Expect |
|---|---|---|---|
| A1 | 18 + typed label | ACORD 127 page 1, Edit form. Click low in the empty cell of "Is there a vehicle maintenance program in operation?", type "yes", then "x". Done editing - save, then Refresh. Then clear it and save | Amber outlines; Y shown; "x" keeps Y; after Refresh the Y is still there and is NOT orange |
| A2 | viewer (R2) + cleanup | 125: click "Show on form" on a page 2, then a page 1, then a page 3 row fast; page arrows 1-2-3-2-1 fast; Edit form + Done twice. Then 126 page 2: clear your two saved answers, save, and click to page 3 while it saves | The boxes always belong to the page shown; the two 126 boxes end empty |
| A3 | 19 | Download - This Form: read the review | The four rows read `ACORD 125: "Name of the authorized representative of the producer, agency and/or broker that signed the form" shows ...`; no internal names |
| A4 | 19 | Download - Entire Package, unzip, open `00_Primble_Cover_Page.pdf` | Red Flags lists real gaps only - no "AI held back", no "Please verify", no premium to-dos |

**B. A fresh upload of the Orbin dec - choose 125, 126, 127, 131, 186. Do not answer any carrier card.**

| # | Covers | Do | Expect |
|---|---|---|---|
| B1 | 9 | Pre-form, "Key details missing": open "NAICS or SIC industry code", then "FEIN / Tax ID" | NAICS: "comes from you or the underwriter"; FEIN: "Send to Client asks the client" |
| B2 | 7 | 125 page 1 | CARRIER: "EMC Property & Casualty Company; Employers Mutual Casualty Company"; NAIC and POLICY NUMBER blank; producer PHONE = your Account Settings phone; no "carrier receiving this submission" card |
| B3 | 9 | 125 side panel | Two closed dropdowns, "Needs attention (N)" and "AI held back (N)", each with (i) |
| B4 | new | 125 page 3, question 4 | Four rows, both companies' policies: Commercial General Liability BBC7263 - 26, Commercial Inland Marine 6C7-40-02---26, Automobile 6E7-40-02---26, Commercial Umbrella 6J7-40-02---26 |
| B5 | 15 | Answer "No known losses" | "Check if none" ticked on 125 page 4 and 131 page 2; both loss rows leave "Needs attention" |
| B6 | 8 / 11 | Edit form, clear page 1's Umbrella premium, save. Then type 3,418 back and save | "Premium amount for the Commercial Umbrella line of business" appears under Needs attention as Missing; leaves when retyped |
| B7 | G2 | Premises card: Tenant; landlord cards: a real-looking name and address, e.g. "Dahlia Street Properties LLC", "1200 Blake St, Suite 4, Denver, CO 80202" | 125 page 3 ADDITIONAL INTEREST row A at once: name + address, OTHER ticked "Landlord", CERTIFICATE REQUIRED ticked, LOCATION 1 |
| B8 | 7, 19 | Download - Entire Package | Page 1 CARRIER as B2; cover page as A4 |

If anything fails: a screenshot and the test number.

**First results (1 Oct, the owner, session 8739a72a):**
- **The backend never loaded this round's code.** `uvicorn main:app --reload` last restarted its worker at 30 Sep
  23:37:30; every file changed after that (form_routes 23:56, extraction_service 23:38, pdf_service 00:19) was not
  running. So A1's orange "Y" is the OLD rule: the database holds the saved Y as `low_confidence`. Restart the backend
  fully before testing again (the auto-reload has stopped following edits - cause not yet proven; `main.py` installs
  its own SIGTERM handler, which is the first suspect).
- A1: Y / N typing works - a one-letter box takes Y or N (typing "yes" stops at "Y"; pasting "yes" gives Y); saved and
  still there after Refresh. The "not orange" half waits for the restart.
- A2: **new bug, fixed 1 Oct** - after Backspace on a Y / N box in edit mode the old "Y" still showed until saving.
  The box WAS empty (the save cleared it): its unanswered tint was 15% see-through, so the answer printed on the page
  image showed through. The tint is now the same amber, solid (`PDFJsViewer.YN_BLANK_BG`).
- A3: **pass** - the four value-check rows read `ACORD 125: "Name of the authorized representative of the producer,
  agency and/or broker that signed the form" shows ...`; no internal names.
- A4: not checked - neither download reached ~/Downloads (the newest zip is from 30 Sep 21:52).
- B: not run yet.

**Second results (1 Oct, after a full backend restart):**
- A2: **pass** - Backspace now empties a Y / N box on screen at once (the solid tint).
- The owner sent the **Submission Brief** (the Lite cover sheet), not the Entire Package's cover page. It showed five
  defects, all fixed 1 Oct (improving-ll.md C101, `tests/test_cover_sheet_1oct.py`):
  1. "77/100 **B** Needs Work" - the brief laid the package score over the FIRST FORM's result and kept its grade
     (81 -> B); the app shows 77 as **C**. Every cover now reads grade and tier off the score with the app's one
     ladder (`sqs_service.tier_for_score`), and the brief's route sets the package grade.
  2. The routing CODE "priority_review" in the table and the summary - the cover's label table knew only older codes.
     Routing now always prints in words ("Priority review"); an unknown code becomes words, never raw.
  3. "ANNUAL REVENUE 300000" -> "$300,000"; PRIOR CARRIER spells each company as the forms do.
  4. The summary said "the current flags suggest" no subcontractors while the GL rates subcontracted work (class
     91585). The model was given all 49 raw flags and read `asserts_no_subcontractors: False` ("the documents do not
     say none") as "none". It now gets only the TRUE flags plus the GL classifications the dec prints.
  5. The hidden carrier-AI (A2A) block was WRITTEN BY THE MODEL - it repeated the wrong grade and was asked for a
     FEIN and a NAICS code it was never given. It is now built from the package's own records (no FEIN).
- Not changed, on purpose: AGENT / AGENCY print as the account spells them ("vinay sharma", "Astrea It services");
  LINES OF BUSINESS keep the declarations' own words ("Liability").
- Still to check: the Entire Package's `00_Primble_Cover_Page.pdf` (A4), then B.
- Named, not fixed: the scorer holds its routing rule three times and they disagree at 85 (`> 85` vs `>= 85`).

**Owner, 1 Oct: "score during download should be exactly same on the cover page of individual form or whole package
as of the sqs section."** Done offline:
- Every cover's scores table now ends with a **Total Package Score** row - the same stored number the SQS panel
  headlines (`sqs_service.current_package_sqs`, the one door), with the ladder grade and routing in words. It used to
  appear only inside the model's paragraph. The per-form rows were already each form's stored score.
- The Submission Brief, once forms exist, prints that same package score labelled "Total Package Score" - it used to
  prefer a Clarity snapshot from the first analysis, which goes stale as forms are edited. Before forms, a Lite
  brief keeps the Lite screen's own number.
- The E&O download record ("Score at download") now stores the score the producer saw - the package score, as the
  post-download panel prints it - not an average of the form scores (Orbin: ~80 vs 77).
- The cover paragraph's cache key includes the package score, so a cached paragraph never quotes an older one.
- Note: the UI's "This Form" download has NO cover by design ("no summary"); covers come with "Entire Package" and
  "Submission Brief". The single-form cover path (API) prints the same scores too.
- Tests: `tests/test_cover_sheet_1oct.py` (19 in all). Full suite 10,789 passed / 1 failed (the known one) / 19 skipped.
- Suite note: one full run started from the repo root (pytest wrote `.pytest_cache` there) and three tests that open
  schemas by a relative path failed; from `backend/` they pass (255 of 255). Always run from `backend/`.

**Third results (1 Oct, a fresh upload: session `359b36b0`, forms 125 / 126 / 127 / 131 / 186; the owner sent
`ACORD_125_FILLED 4.pdf` and the Entire Package's `00_Primble_Cover_Page.pdf`):**

| # | Result | Checked in the stored session |
|---|---|---|
| B1 | **Pass** - the key-detail hints read as expected | - |
| B2 | **Pass** - CARRIER "EMC Property & Casualty Company; Employers Mutual Casualty Company"; NAIC and POLICY NUMBER blank; no "carrier receiving this submission" card. Producer PHONE **not tried**: no Contact Phone was set in Account Settings (it is set there, not on the pre-form screen), so the box is blank - the dec's agency phone stayed withheld, as it should | The three boxes as stated; the phone box is empty; none of the 125's cards is a carrier card |
| B3 | Not reported | - |
| B4 | **Pass** - question 4 lists all four policies, the auto one as "Automobile 6E7-40-02---26" | - |
| B5 | **Pass** - "No known losses" ticked "Check if none" on 125 page 4 | 131's "Check if none" is ticked too |
| B6 | **Pass** - the cleared Umbrella premium was listed as Missing and left when retyped. It prints "3418": a producer's own entry prints as typed | Cleared 21:05:53, retyped 21:09:21 |
| A1 (127) | **Pass** - a typed Y / N is no longer orange | 127 "KAD" box = N, label `producer` |
| Viewer | **Pass** | - |
| B7 | **Fail as seen** - after "Tenant", no landlord card appeared. Root cause: defects 1 and 2 below | TENANT ticked (producer); the 125's score holds both landlord cards |
| B8 / A4 | **Pass, one defect** - the cover's scores equal the side panel exactly (125 69 D, 126 82 B, 127 77 C, 131 85 B, 186 63 D, Total Package Score 73 C Needs Work, Priority review); Red Flags hold Missing rows only (no "AI held back", no "Please verify", no premium to-dos); PRIOR CARRIER spelled as the forms print it; revenue "Not provided". The defect (3 below): "ACORD 125 - Missing (10)" still listed the building-interest question answered minutes before; the download review showed 9 | The E&O record stored **73** at both downloads (21:10 the 125, 21:20 the package) - the score on screen |

**Three defects found, each proven on the stored session:**
1. **Saving an edit on any form but the first re-scored it as the FIRST form - since May 2026.** `form_routes.
   update_pdf` called `calculate_sqs` without `form_id`, and the scorer falls back to `selected_form_ids[0]` (here
   ACORD 125). After the 127 edit at 21:14:58 the 127's panel showed a score built by the 125's rules, with the 125's
   cards - that is how the 125's premises card sat on the 127 panel. It was answered there at 21:16:39 (recorded as
   form ACORD_127), and the landlord cards it raised went to the 125's panel, which was not open. The answer's full
   re-score (which does pass each form's id) put every form right again - which is why the cover's numbers were right.
   The other four scorer calls pass the form id; this was the only one.
2. **A card that first appears after generation never reaches the download review or the cover.** Cards are recorded
   as "shown" (`sqs_recommendation_audit`) only when forms are generated. The landlord cards were raised by an answer,
   so the review's "Open Recommendations (6)" and the cover's Red Flags could not list them.
3. **The cover's Needs-attention rows are a snapshot.** They are rebuilt when forms are generated or a form is saved,
   not when a card is answered. The download review computes its list live, so the two disagreed by the answered
   question.

**Owner's question - what the Best Solutions percentages show.** The % is that pillar's score for the whole package;
"+N pts" is what the package gains if the pillar reaches 100%: (100 - %) x the pillar's weight. Weights: Structural 25%,
Exposure 25%, Property 15%, Loss History 15%, Umbrella 10%, Narrative 10%. Before "No known losses" (score 66): Loss
History 25% -> 75 x 15% = 11.2; Structural 62% -> 38 x 25% = 9.5; Exposure 72% -> 28 x 25% = 7.0; Narrative 40% ->
60 x 10% = 6.0. After it, Loss History is Not Applicable and leaves the list; its 15% is shared out, so every other
weight is divided by 0.85 (Structural becomes 29.4%): 11.2, 8.2 and 7.1 - "26.5 points remaining", score 73.

#### Fixes from the third results (1 Oct, night) - offline-verified, NOT yet tried live

| # | What was wrong | Root cause | Fix |
|---|---|---|---|
| 1 | A save on the 127 showed the 125's score and cards on the 127 panel | `update_pdf` called the scorer without the form's id; the scorer takes the first selected form. Since May 2026, every save on any form but the first scored it by the first form's rules until the next answer re-scored it | The save passes its form's id. A test fails the build on any scorer call that does not name its form (the Submission Brief's pre-form call now names its first form - same number as before) |
| 2 | The landlord cards never reached the download review or the cover | Cards were recorded as "shown" only at generation. Also found: a save resolved a card the moment it left the saved form, though another form still showed it; and nothing reopened a card the system had closed when its gap came back | One door, `audit_service.sync_recommendation_cards`, used by generation, the worker, a save and every answer: it records every card the forms show that is not stored yet (one insert per new card), reopens a card the system closed that is live again, and resolves an open card no form shows. A card the producer dismissed or answered is never touched; field-QA rows keep their own refresh; nothing scored means nothing changes |
| 3 | The cover's "ACORD 125 - Missing (10)" kept an item answered minutes before | Those rows are a snapshot rebuilt only on generation and saves. Rebuilding them after every answer costs 5-10 s per answer (field QA measured 4.8 s warm, 10.6 s cold on this package) | The cover and the download's E&O record take the needs-attention rows from the live list - the same door, at the same moment, as the review (`audit_service.current_unresolved_recommendations`). An item acknowledged with "Download Anyway" keeps that mark |
| 3b | Side effect of fix 2, handled | Once recorded, the landlord cards would print under the underwriter's Red Flags, and the cover's paragraph already called the landlord "a major gap" | A card that declares itself worth zero points (`unscored`: the premises and landlord asks) stays off the cover and out of the cover paragraph's input. It stays in the review and the E&O record. The premises box itself, when blank, is still on the cover as a Missing row |

**Proof (offline, session 359b36b0 replayed read-only):** the 127 scored as itself is 77 with its own two cards; as the
route scored it, 69 with the 125's five (premises + landlord). The sync would record three cards the panel shows and
the table never held: both landlord cards and the "No Known Losses attested" note; nothing to reopen or resolve. The
live 125 Missing row reads 9. Tests: new `tests/test_card_sync_1oct.py` (24; two of the fixes reverted on purpose and
the tests failed); updated by design: `test_v1_regpack_audit_score` (it pinned the old function's name as proof the
download reads fresh rows - the new door is fresher) and two recalc tests that stub the database (a stub for the new
door). improving-ll.md C101 notes the cover paragraph's smaller input. **Full suite: 10,813 passed / 1 failed / 19 skipped** (the one failure is the known
`test_arq_acord125_missing_only`).

**Named, not fixed:**
- The "No Known Losses attested" note now also shows in the review and on the cover when the attestation comes after
  generation - it already did when it came before. It is a status notice, not a gap: a one-line call if the owner wants
  status notices off the cover.
- The other stored field-QA findings (value mismatches, guard rows) are still rebuilt only on generation and saves;
  the review reads the same snapshot, so the review and the cover still agree.
- The E&O "N open item(s) at download" count still counts stored rows.
- Session 359b36b0 records the premises answer against ACORD_127 (the panel it was answered on). Cosmetic; left.
- On an existing session the landlord cards reach the review after its next answer, save or regeneration.

#### Retest after these fixes - the script (restart the backend fully first)

Before uploading: Account Settings -> Contact Phone. Fresh upload of the Orbin dec; choose 125, 126, 127, 131, 186.

| # | Covers | Do | Expect |
|---|---|---|---|
| C1 | fix 1 | ACORD 127: Edit form, type N in any Yes / No box, Done editing - save | The 127 panel keeps the 127's own score and cards - no "ACORD 125 premises" card |
| C2 | G2 | ACORD 125 panel: the premises card - answer Tenant | Two landlord cards appear at once on the 125 panel |
| C3 | fixes 2, 3, 3b | Download - Entire Package | The review's Open Recommendations lists both landlord cards. The cover: no landlord card under Red Flags; "ACORD 125 - Missing (N)" has the review's 125 Missing count and does not list the building-interest question |
| C4 | G2 | Answer both landlord cards ("Dahlia Street Properties LLC"; "1200 Blake St, Suite 4, Denver, CO 80202") | 125 page 3 ADDITIONAL INTEREST row A: name + address, OTHER ticked "Landlord", CERTIFICATE REQUIRED ticked, LOCATION 1; both cards move to Reviewed |
| C5 | 7 (phone) | 125 page 1 | Producer PHONE = the Account Settings phone |

If anything fails: a screenshot and the test number.

**Fourth results (1 Oct night, fresh upload: session `69687a55`, forms 125 / 126 / 127 / 137 CO / 131 / 186) - all
five pass, graded on the stored session.** The two PDFs the owner attached were from the previous run (`359b36b0`: the
cover is dated 30 Sep 21:20 UTC and the 125's umbrella premium reads "3418", the value retyped there), so C3-C5 were
checked in the database instead.

| # | Result | Evidence |
|---|---|---|
| C1 | **Pass** - after a Y / N save on the 127, its panel kept its own two cards (no premises card) | Owner's paste of the 127 panel |
| C2 | **Pass** - "Tenant" on the 125 raised both landlord cards on the 125 panel at once | Owner's paste; answer 22:26:00 |
| C3 | **Pass** - the landlord cards were RECORDED when raised (22:26:12, twelve seconds after Tenant), then resolved by their answers; the package download stored exactly the review's Missing counts (125: 11, 126: 4, 127: 3, 131: 2, 186: 1, 137 CO: 2) and score 66 | `sqs_recommendation_audit`, `acord_audit_log` |
| C4 | **Pass** - 125 ADDITIONAL INTEREST row A: "Claude Sharma", "Chaude House" (as typed), OTHER "Landlord", CERTIFICATE REQUIRED, LOCATION 1, all labelled `producer` | Stored 125 |
| C5 | **Pass** - 125 producer PHONE "7983789751" from Account Settings (printed as typed) | Stored 125 |

Not exercised live: the zero-point-card-off-the-cover rule (both landlord cards were answered before the download);
it is covered by `tests/test_card_sync_1oct.py`.

**Found in this run, NOT fixed (next round):**
- **A wrong value on the 127:** `AdditionalInterest_FullName_C` = "Emcasco Insurance Company" (the vehicle's "other
  owner"), filled by the AI from the dec's corporate signature block ("IN WITNESS WHEREOF ... EMCASCO Insurance
  Company, Corporate Office, Des Moines"). The field-mapping check flagged it only as a warning; the paired "vehicles
  not solely owned" question is also AI-filled ("Please verify"). An insurer is never a vehicle's co-owner.
- **That warning still speaks the internal name** ("AdditionalInterest FullName on ACORD 127 shows ...") - the
  field-mapping rows were missed when item 19 moved every review row to the form's words.

**Owner, 1 Oct night: "remove the percentage from these parts as it is confusing users"** (the Best Solutions rows).
Done: no % on any Best Solutions row (package rows and the per-form fallback), and the "Percentages below are for the
whole package, not this form" note is gone with them. The "+N pts" and the pillar rows above stay. Frontend builds;
0 lint errors. Not yet seen live.

#### Independent audit - 1 Oct night (owner: "how many are addressed and verified ... brutally honest")

Seven reviewers (3-4 points each) read Michelle's words and screenshots, the code, and the stored live sessions
(read-only), each told to prove the claim false; a critic then challenged every "done" and re-checked the riskiest
claims itself. The main thread re-verified the four heaviest findings in the database (GL limits, Michelle's account,
the signature field, the untracked files). This table replaces the status board's verdicts.

| # | Verdict | What is true today | The catch |
|---|---|---|---|
| 1 | **Not started** | Not built. Opening a package that has forms goes straight into the form editor. There is no package profile, no 'Continue where you left off' and no list of started forms under Key Details. Once forms exist, the pre-form review screen cannot be reached again, and F5 on it drops you to the dashboard. | The dashboard is the first thing she clicks. It still behaves exactly as she reported, and it labels every package 'Not Quote Ready' because the label needs 90+ and nothing in practice scores above 89. |
| 2 | **Partly done** | We chose to pre-score: the review screen shows 'NN / 100' and the tier before any form exists (seen live on b8d6cb2d, 17351800 and 8739a72a). Some forms messaging remains: the new line still reads 'It can change when forms are generated', the header and main button still say 'continue to form selection', and the dashboard shows 'SQS -' until forms exist. The 'formless / on top of any 3rd-party system' direction has no work behind it. | The score jumps when forms are generated with no input from anyone (64->66, 66->68), which shows it is still partly forms-driven. No pre-form score was recorded on the newest run (69687a55). |
| 3 | **Done, seen working on localhost** | The 'Important' tab and preview block are gone from both pre-form layouts (confirmed in code), and so is the broken '(+1 related' text. Seen live on 15f42b1d and 17351800. | One repeat remains on the same screen: 'Contact information' appears under Key details missing AND as a warning. If she is hunting for repeats, she will find it. |
| 4 | **Done, seen working on localhost** | Proposed dates are derived as the next term (07/15/2026 - 07/15/2027) with no warning. Seen on 69687a55, current code, with no owner input. These are the dates she typed herself on 22 Sep. | The dates are our calculation (fact source 'derived'), but the boxes are labelled 'filled', so nothing asks the producer to verify them. The effective date is already about 2.5 months in the past on a QUOTE. The section forms pair it with the expiring '-26' policy numbers. With an older dec the warning comes back. |
| 5 | **Declined - must be explained** | Nothing she would see has changed: the same 'ACORD 125 minimum field missing: Contact information' card is in 69687a55 and caps the package at 85. The dec prints no insured contact. Its only phone is the other agency's (303-996-7800), it has no e-mail, and the only person named is Erin Royal on Drive Other Car. | The question to Michelle ('which page? is Erin the contact?') was never sent. The card still does not say WHOSE contact it wants, and she may mean the producer contact (see item 7). |
| 6 | **Done, seen working on localhost** | 'Open to fix' now opens an empty driver table ('0 drivers, + Add driver') with no error. It was seen live on a 125-only session (b8d6cb2d, A1), and a read-only call shows the server now serves the table on 125-only sessions that returned nothing before. | Her exact screen, the pre-form review, was not clicked live on today's code, and nobody has saved a driver through the window. The warning itself returns on every Orbin run and caps at 85, because the policy lists no drivers. |
| 7 | **Partly done** | CARRIER now prints both EMC companies joined by '; '. NAIC, POLICY NUMBER, program and underwriter stay blank on purpose. The producer phone and e-mail come from the login account, not the dec. The dec's only agency phone belongs to Commercial Risk Solutions and is deliberately withheld, and the dec has no e-mail at all. | Michelle's ThinkSmith account has NO phone saved (users.phone is NULL, verified), so on her login PHONE prints blank, exactly as in her screenshot. The producer mailing address is blank too. Printing two carriers reverses Brent's answer key, and he has not been asked. The tracker's 'Done, verified live' overclaims. |
| 8 | **Done, seen working on localhost** | Line premiums (3,954 / 2,991 / 300 / 3,418) and POLICY PREMIUM 10,663 print on 125 page 1 in 69687a55 and match the dec. A blank premium shows as a Missing row under 'Needs attention'; seen live on 359b36b0 (cleared and retyped). | These are the EXPIRING term's premiums printed as the renewal basis, which reverses Brent's answer key ('blank unless known'); Brent has not approved it. The prompt is a 0-point row inside a side-panel section that is closed by default, and on Orbin it never appears unless you clear a box. A retyped premium prints '3418' next to '3,954'. |
| 9 | **Partly done** | Each form's side panel now has 'Needs attention' and 'AI held back' lists, with the form's own words and a jump to the box. The 69687a55 download record matches the recount of 123 rows. Before form selection she only gets the six score key details, now clickable. That line already existed on her 22 Sep build. | Both side-panel sections start COLLAPSED (confirmed in code: defaultOpen=false), and the current layout was never reported seen live. 122 of 123 rows say 'No score effect'. The held-back list prints the AI's rejected 'Yes' answers verbatim (sexual abuse claims, radioactive materials, flammables). |
| 10 | **Done, seen working on localhost** | A large pink 'Edit form' button, and double-clicking a box starts editing it. Seen live on 8739a72a (R3, R6). | Unsaved typed edits are silently lost if you switch forms, apply an 'Open to fix', or download before pressing 'Done editing - save'. The 'Unsaved' marker was removed. Very easy to hit in a live demo. |
| 11 | **Done, seen working on localhost** | Proposed dates and premiums fill from the dec (69687a55), and a blank premium or total shows under Needs attention as Missing (seen on 359b36b0). | The same caveats as 4 and 8 apply: derived dates are not flagged for verification, the premiums are last term's (Brent not asked), and the prompt is hidden in a collapsed section. DEPOSIT and MINIMUM PREMIUM stay blank with no prompt. The total's row is worded 'Estimated total cost amount of the policy', not 'POLICY PREMIUM'. |
| 12 | **Declined - must be explained** | '$0 revenue by default' was deliberately NOT built. Tenant is now a producer card, pre-selected on this shape, instead of being auto-ticked. ANNUAL REVENUES fills only from a supplied business revenue; in 69687a55 it is empty. The dec never says 'tenant' (checked). | On a fresh upload this looks WORSE than her 22 Sep screenshot. There, TENANT and INSIDE city limits were already ticked; today both are empty until someone acts, and INSIDE is never filled (verified missing_required in 69687a55). The question to Michelle about $0 was never sent. |
| 13 | **Partly done** | GL CODE prints '91580, 91585' from the dec's class schedule (verified). SIC and NAICS are not printed anywhere in the dec, so they stay blank. FEIN is asked in the questionnaire, and the client-FEIN print path was last seen on 29 Sep code. | The 'AI held back' rows for SIC and NAICS say 'Found "7383"...', which reads as if the system found her code and hid it. The stored fact applicant_gl_class_code is 7383, the auto class, which is wrong. LLC 'NO. OF MEMBERS AND MANAGERS: 1', filled in her own item-13 screenshot, is now blank. The question to Michelle ('which page shows SIC/NAICS?') was never sent. |
| 14 | **Not started** | Not built. The questionnaire sends questions only; the client never sees or signs an ACORD form, and there is no attestation step. | SERIOUS and live on Render today: the producer's 'Sign' button paints the producer's saved signature on the APPLICANT's signature line too (_is_signature_field('NamedInsured_Signature_A') = True; the code is unchanged since May). Michelle's account has a saved signature. The review also tells the producer to 'fill in' the applicant's signature. Fix this before answering her. |
| 15 | **Done, seen working on localhost** | Once No Known Losses is confirmed, the Loss History pillar becomes N/A on the package and every form (359b36b0: state no_known_losses_not_applicable, package 66 -> 73, verified in the DB). | The package is STILL capped at 85, by the item-5 contact card, so if '(Max 85%)' meant the cap, nothing she sees lifts it. The change lowers weak packages and 1-5 year businesses, reversing Brent's 85 rule, and Brent has not been told. The same loss card shows +6/+7/+8/+10/+11.2 in different places, but answering it really gives +7. The newest run (69687a55) did not re-test this. |
| 16 | **Done, seen working on localhost** | A resolved or dismissed hard stop leaves the red box for a collapsed 'Reviewed' section with Reopen; a stop only marked resolved gets an amber 'still capped at 60' note. Seen live on 8739a72a (R10). | Her exact case (the expired term) no longer happens on the Orbin dec, so the demo needs a prepared hard stop. The pre-form review screen does NOT tuck handled stops away. AcordModal.jsx was edited after the last live run. |
| 17 | **Partly done** | Her reported case is fixed and was seen live (f67bf8ab): answers the producer gives on a card, through 'Open to fix' or by typing are labelled 'producer', not green. Her exact boxes, the proposed dates, now come from the dec and are not green. | The viewer still paints a box green whenever its name is a key in ANY submitted questionnaire (get_client_filled_fields is never pruned). A producer who retypes a raw-keyed box the client answered (e.g. subcontracted %) still sees green 'Client'. The tracker's 'Done, verified live' overclaims. |
| 18 | **Partly done** | In edit mode every Y/N question on 125/126/127/131 is outlined, clickable across its whole cell, and takes Y or N only. The producer half was seen live on the 126 and 127. | The CLIENT half she asked for was declined (owner decision) and the question was never sent. The highlight appears only in edit mode. About 181 of 190 Y/N answers on the Orbin forms open blank, so the producer types them by hand. |
| 19 | **Partly done** | The guidance is now in each form's side panel and in the download review: each box in the form's words, tagged Missing / AI held back / Please verify, with what to do and a jump to the box. The vague 'Field QA: 4 required / 7 to verify' line is gone. Before forms, it is only clickable key details. | The internal name she complained about is still there and carries a WRONG value: 'AdditionalInterest FullName on ACORD 127 shows "Emcasco Insurance Company"' is stored in the review and the E&O download record (verified) and reaches the underwriter cover. The review count went from her 11 to 131. 122 of 123 rows say 'No score effect'. The review pop-up cannot resolve anything. |
| G1 | **Done, seen working on localhost** | The questionnaire invitation and reminder say 'Commercial Insurance Submission Platform'. The owner saw it in his inbox on 29 and 30 Sep. | It is not deployed: e-mails sent from her Render server still say 'Commercial Insurance Platform'. |
| G2 | **Partly done** | With one location, after Tenant is confirmed, producer cards ask for the landlord's name and address, and the answer prints on 125 page 3, ADDITIONAL INTEREST row A (Other 'Landlord', Certificate Required). This was seen once, on 69687a55, with junk test values. | She asked for the CLIENT to supply it 'for certificates'. The client path has never run live and only works if Tenant was confirmed before sending. The landlord never reaches the ACORD 25 certificate holder and is not Additional Insured. Printing re-cases names ('CBRE' -> 'Cbre'). With 2+ locations, or if any other interest exists, there is nothing. premises_interest.py is an untracked file imported unguarded, so a careless commit breaks every upload. |
| Q | **Partly done** | The client's end summary now reads 'N of M questions answered - X of Y details checked' (seen live on 8739a72a and f67bf8ab); her submission would read '21 of 21 - 0 of 4 details checked'. | The same screen's header still says 'Questions (25)', and the ring and 'N to go' still count check items (confirmed in code). The producer's receipt still reads '21 answered / 25 asked'. There were 4 check items, not the 3 she counted. |

**Demo-day risks, most serious first:**
1. NOTHING is deployed. The client's Render server runs 8b005ad (27 Sep); c69b4cc is unpushed and 74 files are local only. If Michelle opens her server she sees every 22 Sep defect unchanged. Do not say 'fixed' to her until commit + push + deploy, then re-run on Render.
2. Broken-deploy risk: premises_interest.py, needs_attention.py and several frontend files are UNTRACKED, and extraction_service imports premises_interest without a guard. A commit that misses them breaks location handling on every upload. Add every new file explicitly and smoke-test on Render.
3. WRONG GL LIMITS can appear on a fresh upload. The newest run (69687a55) printed the umbrella's $3,000,000 as the GL Each Occurrence / Aggregate / Personal & Advertising on the ACORD 126 and in the 131's underlying schedule, labelled as document values with no warning. Earlier runs were right. It is non-deterministic, so check the demo session's 126 and 131 before showing them.
4. The 'Sign' button stamps the producer's signature on the APPLICANT's signature line (125/126/127/131/137). It is live on Render today and Michelle has a saved signature. Item 14 is exactly this question, so fix it or do not click Sign in front of her.
5. Account settings: Michelle's ThinkSmith account has no Contact Phone. On her login the 125 producer PHONE prints blank, exactly her item-7 complaint. She must set Account Settings > Contact Phone BEFORE uploading. The producer mailing address is blank for everyone.
6. Wrong values visible on the forms: 127 'other owner' = 'Emcasco Insurance Company' (the insurer as co-owner of the Subaru); 126 'products of others under your label' explained with 'Repackages or relabels CBD products' (from the cannabis exclusion); 186 'years of experience' = 20 (in no document). The Emcasco row also shows the internal name 'AdditionalInterest FullName' in the review, the E&O record and the underwriter cover.
7. Things she saw filled on 22 Sep are now blank on a fresh upload: TENANT (now needs a card click), INSIDE city limits, and LLC members '1'. The package scores 66 'Major Gaps', and every screen shows the same 85 cap from the contact card she said should not exist (item 5).
8. The side panel's 'AI held back' list prints the AI's rejected answers verbatim, e.g. 'The AI answered "Yes"' to sexual-abuse claims, radioactive materials and flammables for her insured. The guard worked, but read aloud it sounds like an AI that invents damaging answers.
9. Unsaved edits vanish silently when you switch forms, apply an 'Open to fix' or download without pressing 'Done editing - save'. Double-click editing makes this easy to trigger live.
10. Owner/Brent decisions presented as done: CARRIER prints both companies, and page 1 prints the expiring premiums (both reverse Brent's answer key); No Known Losses lowers weak and young packages (reverses Brent's 85 rule). Brent has not been told, and the questions to Michelle (items 5, 12, 13) and Brent (14, G2) were never sent. If Brent objects in the room, the fixes look unsettled.
11. Do not demo sessions 69687a55 or 8739a72a: they hold test junk ('Claude Sharma' / 'Chaude House', 'Eirn Royal', 'Vinay Sharmaa', 'vinay p' / 'noida 22') and an owner-typed Y on the 127 maintenance question. Use a clean upload and review it first.
12. Numbers that disagree on screen: the loss card is worth +6/+7/+8/+10/+11.2 depending on where you look (it really gives +7). The review went from her '11 items flagged' to 131. 122 of 123 Needs-attention rows say 'No score effect'. The dashboard shows 'SQS -' before forms and 'Not Quote Ready' on everything.
13. The environment differs from production: the owner's Mac runs pikepdf 9.3.0 (it has produced blank downloads before), while Render runs 10.5.1. Local and Render do not share the encryption key, so sessions do not cross over. F5 on the pre-form screen drops to the dashboard. AcordModal.jsx changed after the last live run (Best Solutions % removal, not yet seen live). The uvicorn --reload stall has already once made a 'live' result run old code.
14. The tracker's status board ('17 of 22 done and verified live') overclaims. By her own words, 2, 7, 9, 13, 17, 18, 19, G2 and Q are partial. Do not quote 17/22 to the client.

**Wrong or embarrassing values on the forms (newest run 69687a55 unless stated):**
- ACORD 126 (69687a55): GL Each Occurrence 3,000,000, General Aggregate 3,000,000, Personal & Advertising Injury 3,000,000. These are the UMBRELLA's limits; the GL policy prints 1,000,000 / 2,000,000 / 1,000,000. Labelled as document values, and Products-Completed Ops 2,000,000 on the same form contradicts them.
- ACORD 131 (69687a55): the underlying GL schedule repeats 3,000,000 / 3,000,000 / 3,000,000, so the umbrella appears to sit on a $3M GL.
- ACORD 127: AdditionalInterest_FullName_C (the vehicle's 'other owner') = 'Emcasco Insurance Company', taken from the dec's 'IN WITNESS WHEREOF' signature block. The paired question 'any vehicles not solely owned?' is AI-filled. Its 'Please verify' reason ('not found word for word') is false: EMCASCO appears 21 times.
- Review / E&O record / cover: 'AdditionalInterest FullName on ACORD 127 shows "Emcasco Insurance Company"...' uses an internal field name and advertises the wrong value.
- ACORD 126: 'Products of others sold or repackaged under applicant label' explanation = 'Repackages or relabels "CBD products"', from the umbrella's cannabis exclusion, on a building contractor.
- ACORD 186: Contractor's years of experience = 20. Stated nowhere in 271 pages.
- ACORD 127: 'Any drivers not covered by workers compensation?' = N (AI). There is no WC policy in the package to support it.
- ACORD 126: swimming pool / lodging / recreation facilities = N (AI, low confidence), not addressed by the dec.
- ACORD 127 (69687a55): 'vehicle maintenance program' = Y is the owner's test edit, not a document fact.
- ACORD 125 page 3 (69687a55): Additional Interest row A 'Claude Sharma' / 'Chaude House' is owner test data. 8739a72a holds 'Eirn Royal', 'Vinay Sharmaa' and landlord 'vinay p' / 'noida 22'.
- ACORD 125 page 1: the premiums shown are the expiring 2025-26 figures, repeated in the prior-carrier 2025 row. The proposed effective date 07/15/2026 is already past on a QUOTE-status application.
- Section forms 126/127/131/186/137 CO: the expiring policy numbers (BBC7263 - 26, 6E7-40-02---26, 6J7-40-02---26) are paired with the new EFFECTIVE DATE 07/15/2026. The 131's underlying terms 07/15/2025 - 07/15/2026 expire the day the umbrella's proposed term starts.
- ACORD 125 CARRIER: two names, 66 characters, shrunk to about 6.8pt. Name order flips between runs, and the casing differs from the section forms' 'EMPLOYERS MUTUAL CASUALTY COMPANY'.
- ACORD 125 producer block: phone '7983789751' printed unformatted, agency re-cased as 'Astrea It Services', mailing address blank. On Michelle's account the phone would be blank.
- A retyped premium prints '3418' next to formatted '3,954'.
- The landlord name is re-cased on print ('CBRE Group Inc' -> 'Cbre Group Inc', 'JLL' -> 'Jll', 'II' -> 'Ii').
- Stored fact applicant_gl_class_code = 7383 (the auto class). The guard keeps it off the form, but the 125 'AI held back' SIC/NAICS rows show 'Found "7383"'.
- ACORD 125: INSIDE city limits, LLC members / managers, FT/PT employees, business start date and annual revenue are all blank on a fresh upload. INSIDE and members '1' were filled in her 22 Sep screenshots.
- ACORD 125/126/131 operations boxes print the ISO abbreviation 'Contrctrs-sub work-in connection w/constrctn,recon,repr,erctn of buildings - NOC' (the dec's own text, but it reads as garbled).
- Question 4 line names and order change run to run on the same dec ('Umbrella' vs 'Commercial Umbrella').
- Every form lists 'Signature of the applicant' and its date as Missing, with 'Fix: Fill these in on the form'. That tells the producer to sign for the applicant.

---

#### Fix round after the audit (1 Oct night) - DONE OFFLINE, the owner's retest is next

Owner: "Fix them and do not break anything that is working ... do not leave any caveat and cover all the edge cases,
do not hard code anything." Owner commits himself - nothing is committed by us. Everything below is proven OFFLINE
(tests, replays, the real templates); none of it has been seen on a live run yet.

**Wrong values (the audit's list) - all fixed:**

| Wrong value | Root cause | Fix |
|---|---|---|
| GL limits = the umbrella's $3,000,000 (126, 131) | The merge chose between candidate amounts by vote and order; nothing asked which LINE printed the amount | The merge settles each line's limits by that line's own verified declarations (`extraction_service._settle_line_limits`). Any row order, any spelling (fuzzed 40 ways). **Needs a FRESH upload** - a stored session keeps its old facts |
| "Emcasco Insurance Company" as the 127 vehicle's other owner | Gap fill read the dec's corporate signature block; the insurer is never a party to its own policy's interests | An insurer in an owner / additional-interest / lienholder box is refused (`pdf_service._insurer_in_a_party_box`). Banks, finance and leasing companies, agencies, the package's own interest parties and a person's answer never are. The "vehicles not solely owned?" Yes that stood only on it goes with it |
| "Repackages or relabels CBD products" (126) | The quote was a line of the cannabis EXCLUSION; the model's JSON escaping also hid its quoted defined terms | Evidence the document prints only inside its own policy wording cannot answer a question about the applicant (`_evidence_sits_in_policy_wording`). Measured on 85 stored sessions: of 42 AI "Yes" explanations it flags only the two CBD lines; 0 of 36 application, 0 of 69 certificate, 0 of 10 loss-run sentences |
| 186 years of experience "20" | A count no document prints | An AI count the documents do not print is dropped (`_drop_unstated_counts`) |
| Unsupported AI Yes / No | A "No Coverage" line answered "no swimming pool"; an exclusion's title "proved" a Yes | A coverage denial cannot answer a question about the applicant (`_coverage_denial_cannot_answer_no`); policy wording as above. On Orbin: the "Yes" to sexual-abuse claims and flammables (both "proved" by "Fungi Or Bacteria Exclusion ($33)") and to radioactive materials ("Nuclear Energy Liability Exclusion") are refused |
| The Sign button signed the APPLICANT's line | The painter asked only "is this a signature box?" | `services/signature_boxes.py`: whose box it is comes from ACORD's own tooltip and the field name (they must agree); the Sign button paints the PRODUCER's boxes only. Checked on all 17 real templates; a signed PDF cached before the fix is re-painted, never served |
| Every form told the producer to "fill in" the applicant's signature, and the row reached the cover | The applicant's steps were ordinary "Missing" rows | They are a row of their own, "To be signed by the applicant", and never reach the cover |

**Point fixes:** 3 (a key detail said once), 4 (calculated dates "Please verify"), 9 (lists open by default - reversed by the owner after the 1 Oct retest, they start closed; a refused
answer is never repeated), 10 (typed edits are never lost), 16 (no sentence twice), 17 (green only while the client's value
is in the box), 19 (field-mapping rows in the form's words and off the cover; one number per card; plain words in Best
Solutions), Q (counted apart everywhere), G1 (plain-text tagline). Plus: typed premiums formatted, the carrier line in a
fixed order, names as typed, the auto class 7383 never kept as the GL code (fresh upload), unticking "Check if none"
means "no information", the "No Known Losses attested" notes kept off the cover.

**Item 19, "one number per card" - how it works.** The loss card showed +6 / +7 / +8 / +10 depending on the form and the
Best Solutions row +11.2, while answering it moved the package +7. Now every copy of a card shows what answering it does
to the PACKAGE score (the number the covers and the headline print), measured by the scorer itself with an answer the
field accepts. A table or a narrative cannot be probed, so it keeps "up to N". Best Solutions keeps the pillar's gap
("+11.2 pts") and adds "Answering this adds +7 pts" when the two differ.

**Found while verifying, and fixed:**
- The new policy-wording check was silently using ANOTHER check's pattern (two module variables with one name).
- A re-stamp after an answer kept a DOCUMENT value's capitals as if a person had typed them.
- Lower-case typing printed in lower case ("vinay sharma") - text typed with no capital is formatted as before; one
  capital keeps the person's own spelling ("CBRE Group Inc", "JLL").
- An amount with cents ("3418.50") was taken for a web address and printed unformatted; "3.14.15" would have printed
  "$3.14". Both fixed in the display formatter.
- A typed edit made while a save was still running could miss the save before a form switch.
- (Found while writing the retest script.) The calculated proposed dates were flagged "Please verify" with the reason
  "Filled by the AI, but not found word for word in your documents" - untrue: we calculate them. They now read
  "Calculated, not read from your documents. Confirm it before sending." (one shared test,
  `pdf_service.prints_a_calculated_value`, decides both the label and the reason), and the orange chip's hover says
  "Filled by the AI or calculated by us".

**Evidence (offline):**

| Check | Result |
|---|---|
| Full backend suite | **11,373 passed / 1 failed / 19 skipped** - the one failure is the known `test_arq_acord125_missing_only`. 13 older test pins encoded the behaviour this round fixes (a quoted "Yes", "None corroborated", the applicant's signature as Missing, the duplicate handled-stop line, ...) and were updated, each with its reason |
| New tests | `test_fix_round_1oct_night.py` (124), `test_fuzz_fix_round_1oct.py` (340, seeded fuzz: shuffled rows, spellings, OCR glue), `test_fix_g1a_1oct.py` (41), `test_fix_g1b_1oct.py` (55) |
| 34 stored sessions (one per distinct package, plus 359b36b0 and 8992d874), old code vs new | **No score moved** on any package or form. 64 boxes changed: 46 the agency name as typed, 2 the carrier order, 16 refused values - every one wrong (Emcasco, CBD, 20 years, the fungi / nuclear exclusions as proof, a policy definition as hazmat proof, the employee count "24" as a guard count). No correct value lost. Invariant checks: 546 violations -> 0 (486 quoted refusals, 45 "fill in the applicant's signature" rows, 14 cards with different numbers per form, 1 insurer as a party) |
| FR125 kit, tests 3-8 replayed | 299 / 307 / 306 / 312 / 312 / 312 of 312 (previous replays 297 / 306 / 306 / 312 / 312 / 312); 0 made up on all six |
| Score panel (D6) | 0 of 12 packages moved |
| Sign button | All 17 real templates: producer box painted, every applicant box still a live field |
| Frontend | No new lint warning against the pre-fix code; build clean; the three helpers run under node (9 checks) |

**D6 - tell Brent (no score moved):** a card's number is now its package effect, so some numbers fall - % subcontracted
+12 -> +2, contact +5 -> +2, the three contractor suggestions +6 -> 0 (no score reads them), GL class codes +13 -> 0 (they
move only the 126's own score). A dismissal credits the card's number, so those credits fall the same way, and the
questionnaire pre-selects questions by these numbers. The loss label reads "Attested - no known losses".

#### Retest after the fix round (for the owner) - the full script

**Time:** about 60-90 minutes, most of it waiting for the upload to be read. **Account:** vinaysharma@astreait.com
(professional tier, signature saved, Contact Phone 7983789751 - all checked in the database, 1 Oct).

**0. Start everything fresh (5 minutes)**

| Step | Do | Expected |
|---|---|---|
| S1 | Stop the old backend if one runs: in its terminal press Ctrl+C. If port 8000 is still taken: `lsof -nP -iTCP:8000 -sTCP:LISTEN`, then `kill <PID>` for each PID listed | `lsof` prints nothing |
| S2 | Redis: `~/redis/bin/redis-cli ping` | `PONG` (if not: `launchctl load -w ~/Library/LaunchAgents/io.redis.local.plist`) |
| S3 | Backend, **without `--reload`** (so it runs exactly what is on disk - the reloader has stalled before): `cd ~/Downloads/Primble-16thsep/backend`, `source .venv/bin/activate`, `uvicorn main:app --host 127.0.0.1 --port 8000` | `Application startup complete.` and no Traceback |
| S4 | Second terminal: `curl -s http://localhost:8000/api/health` | `{"status":"healthy"}` |
| S5 | Frontend (Vite has been running since 28 Sep; restart it to be safe): Ctrl+C in its terminal (or `lsof -nP -iTCP:5173 -sTCP:LISTEN` and `kill <PID>`), then `cd ~/Downloads/Primble-16thsep/frontend`, `npm run dev` | `Local: http://localhost:5173/` |
| S6 | Open http://localhost:5173, hard-refresh (Cmd+Shift+R), log in | Dashboard loads |

**1. Fresh upload (the GL-limit and 7383 fixes run only when a document is READ)**

| Step | Do | Expected / record |
|---|---|---|
| U1 | New package: upload the Orbin dec, `2526 Package Policy (Complete Copy) (4).pdf`. **Write down the time.** | Reading takes several minutes (271 pages) |
| U2 | Pre-form Review screen: read the "Key details missing" line (item 3) | "Contact information" is NOT named there while the warning card "ACORD 125 minimum field missing: Contact information" is on screen; the line instead ends "N more under Warnings" (or reads "Key details missing: 1 under Warnings.") |
| U3 | Note the score shown "so far" | Record the number |
| U4 | Continue to form selection, pick 125, 126, 127, 131, 186 (and 137 CO if offered), Generate forms | Editor opens; record the package score |

**2. The wrong values (open each form in the editor; page numbers are the form's own)**

| ID | Where | Pass when | Fail looks like |
|---|---|---|---|
| W1 | ACORD 126 page 1, LIMITS | EACH OCCURRENCE 1,000,000 · GENERAL AGGREGATE 2,000,000 · PRODUCTS & COMPLETED OPERATIONS AGGREGATE 2,000,000 · PERSONAL & ADVERTISING INJURY 1,000,000 · DAMAGE TO RENTED PREMISES 500,000 · MEDICAL EXPENSE 10,000 | any 3,000,000 |
| W2 | ACORD 131 page 1, the underlying General Liability row | 1,000,000 / 2,000,000 / 2,000,000 / 1,000,000 as W1 | 3,000,000 |
| W3 | ACORD 127 page 1 | The vehicle's "other owner" name box is blank (no "Emcasco"); "With the exception of encumbrances, are any vehicles not solely owned by and registered to the applicant?" is not Y | Emcasco Insurance Company |
| W4 | ACORD 126 pages 2-3 | "Products of others sold or repackaged under applicant label?" not Y, its explanation not "CBD products"; "Any exposure to radioactive/nuclear materials?" not Y, no "Nuclear Energy Liability Exclusion" text | Y with exclusion wording as the explanation |
| W5 | ACORD 125 page 3 | "Any exposure to flammables, explosives, chemicals?" and "Any past losses or claims relating to sexual abuse or molestation allegations, discrimination or negligent hiring?" not Y; no "Fungi Or Bacteria Exclusion" text anywhere | Y, or an exclusion name as the explanation |
| W6 | ACORD 186 page 1 | Contractor's years of experience blank | 20 |
| W7 | ACORD 125 page 1 | SIC and NAICS blank; GL CODE 91580, 91585; no "7383" anywhere on the 125 | 7383 |
| W8 | ACORD 125 page 1, CARRIER | "EMC Property & Casualty Company; Employers Mutual Casualty Company" - in this order (it is now alphabetical, every run) | the other order |
| W9 | ACORD 125 page 1, producer block | Agency name exactly as saved in Account Settings ("Astrea It services"); contact "Vinay Sharma" (your saved name is all lower case, so it is formatted) | "Astrea It Services" (re-cased) |

**3. The side panel (items 3, 4, 9, 19)**

| ID | Do | Pass when |
|---|---|---|
| P1 | Open the 125, then the 126 | "Needs attention" and "AI held back" are OPEN as each form opens |
| P2 | Read every "AI held back" row on the 125 and 126 | No row says 'The AI answered "Yes"' or '"No"'; a Yes/No row reads "Your documents do not answer this question, so it was left for you to answer."; no row says 'Found "7383"' |
| P3 | 125 page 1, PROPOSED EFF / EXP DATE | Both are orange (verify) on the form and listed under "Needs attention" as Please verify with the reason "Calculated, not read from your documents. Confirm it before sending." |
| P4 | 125 side panel | The applicant's signature and date are listed under "To be signed by the applicant", NOT under Missing with "Fill these in" |
| P5 | The loss card (it starts "No loss history provided") on the 125, 126, 127, 131 and 186 | The SAME "+N pts" on every form; hovering the points says "What answering this adds to the Total Package Score - the same on every form". Record N |
| P6 | Total Package Score, Best Solutions | The Loss History row keeps its own "+x pts" and adds "Answering this adds +N pts" with the N of P5; no percentages; bucket names in words (never "snake_case") |

**4. Typed edits are never lost (item 10, typed amounts)**

| ID | Do | Pass when |
|---|---|---|
| E1 | 125 page 1: Edit form, type `3418.50` in DEPOSIT, do NOT press "Done editing - save"; click the 126 tab | "Saving…" shows, then the 126 opens; back on the 125 DEPOSIT reads 3,418.50 |
| E2 | Edit form, type in any empty box, then click "Open to fix" on a card | The edit is saved before the fix window opens |
| E3 | Edit form, type in a box, then Download > This Form | The downloaded PDF has the edit |
| E4 | Edit form, type in a box, close the browser tab | The browser asks before leaving; leave anyway; reopen the package - the edit is there |

**5. The Sign button (the applicant's line)**

| ID | Do | Pass when |
|---|---|---|
| G1 | On the 125 click "Sign" | It turns "Signed"; page 5: your signature on the PRODUCER's line only, the APPLICANT's signature line blank |
| G2 | Download > This Form, open the PDF, page 5 | Same as G1 |
| G3 | Side panel after signing | The applicant's signature and date still under "To be signed by the applicant" |

**6. Download review and cover page (items 19, 14's cover half)**

| ID | Do | Pass when |
|---|---|---|
| D1 | Download > Entire Package: the "SQS Review" window | No row quotes a refused Yes/No; no internal field name (e.g. "AdditionalInterest FullName"); the loss card shows the P5 number |
| D2 | Download, open the cover page (`00_Primble_Cover_Page.pdf`) | No "To be signed by the applicant", "AI held back" or "Please verify" rows; no "No Known Losses attested" notes; its "Total Package Score" equals the panel |

**7. The questionnaire (items Q, 17, G1)**

| ID | Do | Pass when |
|---|---|---|
| Q1 | Send to Client: make sure the FEIN question is ticked, click "Add confirmations (N)" so the check items go too, enter your own e-mail, send | Sent |
| Q2 | The e-mail | Ends "Commercial Insurance Submission Platform" (optional: Gmail > Show original - the plain-text part ends the same) |
| Q3 | Open the link | Header "Questions (N) · Details to check (M)"; chips and ring count the two apart; answer the FEIN with a valid one, check one detail, submit; the summary reads "X of N questions answered - Y of M details checked" |
| Q4 | Back in the editor, Refresh | The sent-questionnaire line reads the same split; "View response receipt" shows "X of N questions answered" and "Y of M details checked" |
| Q5 | 125 FEIN box (item 17) | Green ("Client"); then Edit form, retype it, Done editing - save: no longer green |

**8. "Check if none" (loss history)**

| ID | Do | Pass when |
|---|---|---|
| C1 | 125 page 4: Edit form, tick CHECK IF NONE, save | Package panel > Loss History: "Not applicable - No Known Losses attested", label ATTESTED - NO KNOWN LOSSES |
| C2 | Untick it, save | "No loss information provided", label UNKNOWN - never "Prior claims known" |

**Report back** (paste this table, one line per ID; a screenshot for every FAIL):

```
Upload time: ____   Score so far (U3): ____   Package score (U4): ____   Loss card N (P5): ____
ID  | PASS/FAIL | What you saw (the value or the text)
S1-S6, U2, W1-W9, P1-P6, E1-E4, G1-G3, D1-D2, Q1-Q5, C1-C2
Anything else odd (an error toast, a spinner that never ends, a slow step):
```

From the upload time I find the session in the database and check every box behind your answers.

#### Retest results - 1 Oct 2026 (session `bfa8711d`: a fresh upload, forms 125 / 126 / 127 / 131 / 186, downloaded 1:04 PM)

Graded from the owner's report, the stored session (read-only) and the downloaded PDFs (cover + five forms).

| ID | Result | What was seen |
|---|---|---|
| U2 | **Pass** | "Key details missing: FEIN / Tax ID · Annual revenue · Number of employees · Years in business · NAICS or SIC industry code - click one to enter it now. 1 more under Warnings." Contact information is said once |
| U3 | Recorded | 63 / 100 "so far" (Major Gaps); 65 after typing $200,000 annual revenue from the key-details link |
| U4 | Recorded | 66 after generation; 68 before download (125 71, 126 81, 127 68, 131 81, 186 69) |
| W1 | **Pass** | 126 LIMITS 1,000,000 / 2,000,000 / 2,000,000 / 1,000,000 / 500,000 / 10,000 |
| W2 | **Pass** | 131 underlying GL = the GL's own limits; 3,000,000 prints only as the umbrella's own limit (the dec's umbrella) |
| W3 | **Pass** | 127 "other owner" boxes A-D blank |
| W4 | **Pass** | No CBD / nuclear Yes or exclusion text on the 126 |
| W5 | **Pass** | 125 flammables and abuse questions blank; listed under AI held back as "Your documents do not answer this question, so it was left for you to answer." |
| W6 | **Pass** | 186 years of experience blank |
| W7 | **Pass** | 125 SIC / NAICS blank; GL CODE "91580, 91585"; no 7383 anywhere on the 125 |
| W8 | **Pass** | CARRIER "EMC Property & Casualty Company; Employers Mutual Casualty Company" |
| W9 | **Pass** | Producer "Astrea It services", contact "Vinay Sharma" |
| P1 | **Changed by the owner** | Both lists opened as built; the owner wants them CLOSED like every other section - done (below) |
| P2 | **Pass** | No "The AI answered"; SIC reads 'The AI tried a value your documents print as "PRIV PASSENGER - COMM CLASS" ... a different item'; no "Found 7383" |
| P3 | **Pass** | Both proposed dates under Please verify: "Calculated, not read from your documents. Confirm it before sending." |
| P4 | **FAIL - fixed offline** | The applicant's signature and date sat under "Missing (11)". The download review already grouped them apart; the side panel did not. Now their own group, "To be signed by the applicant", tagged "Applicant signs" |
| P5 | **Pass** | +7 on every form (owner: "this is correct and no percentages") |
| P6 | **Pass** | Best Solutions: Loss History "+11.2 pts" and "Answering this adds +7 pts" |
| E1-E4 | **Pass** | Owner: "these are all correct"; switching forms without saving kept the edit |
| G1-G3 | **Pass** | The signature is on the producer's line only |
| D1 | Not reported | The review window was not pasted |
| D2 | **Pass - three cover defects found and fixed** | No applicant / held-back / verify rows; Total Package Score 68 = the panel. Fixed: AGENT / USER printed the account's lower-case "vinay sharma" (every form prints "Vinay Sharma"); FORMS INCLUDED printed raw ids ("ACORD_125, ..."); the loss card printed "up to +7 pts" beside the panel's "+7 pts" |
| Q1 | **Pass** | Sent with "Add confirmations (4)" |
| Q2 | **Pass** | The e-mail reads "Commercial Insurance Submission Platform" |
| Q3 | **Pass (the summary)** | The client's end summary: "1 of 7 questions answered - 3 of 4 details checked". The header, chips and ring were not reported |
| Q4 | Not reported | |
| Q5 | **Pass (the green half)** | FEIN 11-2233445 prints green "Client"; the retype half was not reported |
| C1 | **Pass** | "Not applicable - No Known Losses attested" / "Attested - no known losses" |
| C2 | **Pass** | "No loss information provided" / "Unknown"; the card is back at "+7 pts" |

**Found in the PDFs (not in the script) - fixed offline: ACORD 126 LOC # printed "4800"**, the street number. The dec
printed the hazard rows' location as the premises' ADDRESS (a street, a suite, a ZIP+4), and the LOC # reader took the
first number in it. Now an address is matched to ONE premises (street number, street words and ZIP -
`_address_names_location`, the matcher the 127 garaging boxes already use) and prints that premises' ACORD 125 LOC #
("1"), as the box's own tooltip asks; an address no premises matches is an owned blank, never gap-filled, and never
its street number. Labels ("Location 001", "Loc #2", "001", "2 Warehouse") read as before. HAZ # 1 / 2 was already
right. Acts at stamping: generate the 126 again to see it.

**Checked, not defects:** the 126's aggregate "per project" AND "per location" are both ticked (AI, Please verify) -
the GL's own contractors endorsement prints "X. AGGREGATE LIMITS PER PROJECT" and "Y. AGGREGATE LIMITS PER LOCATION";
the 131's 3,000,000 is the umbrella's own limit.

**The owner's changes, made:**
1. The pending-edits note on the SQS panel: "You have unsaved field edits. These scores are from the last save. Save
   to update."
2. "Needs attention" and "AI held back" start CLOSED, like every other section (and close again on a form switch).
3. The applicant's steps are their own group wherever the list is drawn (side panel, download review and its counts),
   named as the review and the E&O record name them (`needsAttention.attentionGroups`, one split).
4. The Please verify hover reads "Filled by the AI or calculated by us, and not confirmed in your documents." (the
   proposed dates are calculated, not AI).
5. **Google's account chooser says "Acordly": not in our code.** The chooser shows the App name of the OAuth consent
   screen in Google Cloud Console (the project that owns `VITE_GOOGLE_CLIENT_ID`). Change it there: Google Cloud
   Console > Google Auth Platform > Branding (older console: APIs & Services > OAuth consent screen > Edit app) >
   App name "Primble" > Save. One project covers localhost and Render; no code or env change. The "acordly" strings
   in the repo are internal names nobody sees (browser storage keys such as the login token `acordly_tk`, the Render
   service names, Terraform); renaming the token key would sign every user out, so they stay.

**The owner's two questions, answered:**
- **The 125 proposed dates (07/15/2026 - 07/15/2027): where from?** Calculated from the dec. The dec prints the
  CURRENT term, 07/15/25 - 07/15/26 (stored as the prior term, verified in the text). The proposed effective date is
  that term's expiration; the proposed expiration is one term later (same 12 months). Facts: `effective_date` source
  "derived", rule `next_term_after_current_policy`; `expiration_date` rule `renewal_routing_prior_term_length`. **The
  client asked for it** - 22 Sep item 4: "Proposed effective date = the last date of the current term (the renewal date
  on the dec)", item 11 "Policy period is on the dec"; she typed 07/15/2026 - 07/15/2027 herself on 22 Sep; owner
  approved 29 Sep (Step 2). **It is not in the document** because a dec prints only its own term - the next term does
  not exist on paper yet. That is why both boxes are orange "Please verify" with "Calculated, not read from your
  documents".
- **"Add confirmations": did the client ask?** Yes - the client's 11 Sep Orbin audit, item 11: the Subaru the policy
  already printed was asked again, and the client wanted what we found shown for confirmation instead of re-asked
  (built 14 Sep, "Chat 5" in `v1-20AUG.md`). Each check item shows the value and the document TYPE it came from; the
  insured answers "This is correct" or "Change it". Nothing is sent unless the producer clicks "Add confirmations (N)";
  a confirmation changes no value and no score, a correction is an ordinary answer.

**Evidence (offline):** `tests/test_retest_fixes_1oct.py` (83: the address shapes, 40 seeded random premises lists,
the hazard grid and its owned blank, the cover agent / form labels / printed PDF, the cover points, the panel source
and the groups run in node). Switching the address branch off makes it fail with the live value ('4800' == '1').
Two pins in `test_viewer_items_10_18_30sep.py` held the old note text and now hold the owner's. Lint: 74 warnings
before and after, 0 errors. Build clean. Full suite: **11,456 passed / 1 failed / 19 skipped** (the known
`test_arq_acord125_missing_only`; +83 = the new file). Replay of 34 stored sessions through the fix-round code and
through this code: **0 boxes changed, 0 scores changed**, identical needs-attention counts - the LOC # change acts
only on a hazard location printed as an address, which no earlier session had.

**Retest these (10 minutes, no new upload needed except R1):**

| ID | Do | Pass when |
|---|---|---|
| R1 | A new package from the same dec (or regenerate the 126), open the 126 page 1 hazard grid | LOC # "1" on rows A and B (not "4800"); HAZ # 1, 2 |
| R2 | Open the 125 | "Needs attention" and "AI held back" are CLOSED; open "Needs attention": groups Missing, To be signed by the applicant (2), Please verify; the two applicant rows tagged "Applicant signs". Switch to the 126 and back: closed again |
| R3 | Edit form, type in a box, do not save | The SQS panel note reads "You have unsaved field edits. These scores are from the last save. Save to update." |
| R4 | Download > Entire Package, open the cover | AGENT / USER "Vinay Sharma"; FORMS INCLUDED "ACORD 125, ACORD 126, ACORD 127, ACORD 131, ACORD 186"; the loss card "(+7 pts)" (no "up to"); the narrative card "(up to +6 pts)" as on the panel |
| R5 | After the Google Console change: log out, Continue with Google | The account chooser says "Primble" (Google can take a few minutes to show it) |
| R6 | Not reported last time (2 minutes): Download > Entire Package, read the "SQS Review" window (D1); open the client link's header (Q3); "View response receipt" (Q4); retype the client's FEIN and save (Q5) | D1: no refused Yes / No quoted, no internal field name, the loss card +7. Q3: "Questions (N) · Details to check (M)". Q4: "X of N questions answered" and "Y of M details checked". Q5: the FEIN box is no longer green |

For long runs keep the Mac awake (`caffeinate -i` before the command): it idle-slept 30 minutes in the middle of this
round's replay, which made one step look 450 times slower than it is (the power log, `pmset -g log`, shows it).

#### R1-R5 results - 1 Oct 2026 (session `82a8b15d`: a new package, ACORD 126 only, downloaded 10:26 UTC)

| ID | Result | What was seen |
|---|---|---|
| R1 | **Pass** | 126 hazard grid LOC # "1" on rows A and B (was "4800"); HAZ # 1, 2 |
| R2 | **Pass (closed)** | Both lists start closed; "Needs attention (10)", "AI held back (24)". The groups inside were not opened (R6 below) |
| R3 | **Pass, restyled** | Owner: the words are right; remove the box border and the dot, and make the text pink like the rest. Done: plain pink text (`#E61B84`), no box, no dot, and the score card no longer turns amber while edits are pending |
| R4 | **Pass, one more defect found and fixed** | AGENT / USER "Vinay Sharma"; FORMS INCLUDED "ACORD 126"; "(+7 pts)" and "(up to +6 pts)" as on the panel. **Found:** the SQS Score Explanation said the package was in "a Needs Work tier with priority review routing" under the table's own row "Total Package Score 63 D Major Gaps Standard review" - the ACORD 126's tier and routing, pinned on the package |
| R5 | **Pass** | The Google account chooser reads "Primble" (owner changed the consent screen's App name) |

"rw" in the 126's ADDITIONAL INTEREST address box is the owner's own typed test edit (labelled `producer`).

**Found in the downloaded 126 (not in the script) - fixed offline: the PRODUCTS / COMPLETED OPERATIONS table held the
insurer's RATING schedule.** PRODUCTS "91580" and "91585" (the GL class codes), ANNUAL GROSS SALES "$1,198" and "$803"
(each class's premium - the dec prints "91585 ... 3.4240 $1,198 2.293 $803"), and a row C of "12" / "12" months and
"COMMERCIAL GENERAL LIABILITY COVERAGE FORM" (the policy's own form). Not a one-off: 4 of 17 stored ACORD 126s carried junk
there (classification wording split across two boxes, the coverage form as a product, component lists with no product).
ACORD's tooltips allow a product OR a service of the applicant, so "contractors leave it blank" is not the rule. The rule
(`pdf_service._product_rows_to_refuse`, run after every guard that can empty a product name):
- a product name that is one of the package's rating classes - a class code, or the classification's own wording, whole
  or its first / last three or more words - is refused; so is a name with no words (a bare number);
- a row with no product name left keeps none of its other AI cells, and reports only its name (the Additional Interest
  rule) - so the side panel does not list each cell of a junk row;
- the line-of-business guard now also knows a line's own document title ("... Coverage Form", "... Endorsement"):
  across every value of 34 stored sessions that changes exactly one, the "Coverage Form" product.
A real product row ("Steel mounting brackets", its sales, use and components) stands whole, and two words of a
classification ("Metal goods") are not enough to call a name the class.

**Fixed offline - the cover's score paragraph.** The model was handed each FORM's grade, tier and routing but only the
package's number, so it gave the package the ACORD 126's. It now gets the package's own grade, tier and routing (the
table's values), and `cover_service._checked_sqs_reasoning` replaces the paragraph with the plain, true one when a
sentence about the submission states any other tier or routing (tiers read off the score ladder, routings off the
app's routing words; "needs work" or "hold back" in prose is not a claim). Prompt change logged in `improving-ll.md`
(C101 addendum).

**Evidence (offline):** `tests/test_retest_fixes_1oct.py` now 161 (+78: the live products rows, the split
classification, a real product kept, 40 seeded spellings, malformed schedules, the LOB title, the live paragraph and six
claim shapes, the prompt, both cover routes, the note's style). Replay of 34 stored sessions plus today's through this
code: **9 boxes change, all junk in the 126 products table; 0 scores and 0 side-panel counts change**; today's session
replays with an empty products table, 126 still 74, package still 63. Lint 74 = baseline, 0 errors; build clean. Full
suite: **11,534 passed / 1 failed / 19 skipped** (the known `test_arq_acord125_missing_only`; +78 = the new tests).

#### R6 on the open session (`82a8b15d`, ACORD 126 only) and the re-checks for these fixes

**Restart the backend first** (Ctrl+C, then `uvicorn main:app --host 127.0.0.1 --port 8000` without `--reload`) and
hard-refresh the browser (Cmd+Shift+R).

| ID | Do | Pass when |
|---|---|---|
| R6a (D1) | Download > Entire Package. Read the "SQS Review" window before it downloads | No row quotes a refused Yes / No answer; no internal field name (like "AdditionalInterest FullName"); the loss card reads "+7 pts" |
| R6b (R2) | Open "Needs attention" on the 126 | Group headings: MISSING, TO BE SIGNED BY THE APPLICANT (the signature and date, tagged "Applicant signs"), PLEASE VERIFY |
| R6c (Q3) | Send to Client: tick "Subcontracted work %", click "Add confirmations (N)", send to your own e-mail, open the link | The header reads "Questions (N) · Details to check (M)" (the second half shows only when confirmations were added); answer Subcontracted work % with `40`, confirm one detail, submit |
| R6d (Q4) | Back in the editor: Refresh, then "View response receipt" | "X of N questions answered" and "Y of M details checked" - counted apart, the same numbers as the client's summary |
| R6e (Q5) | 126 page 2, "% OF WORK SUBCONTRACTED" | Shows 40 in green ("Client"). Then Edit form, retype `35`, "Done editing - save": no longer green |
| R6f (R3) | Edit form, type in any box, do not save | The SQS panel note is plain pink text: no box, no dot, and the score card's border stays grey |
| R6g (cover) | After R6a, open `00_Primble_Cover_Page.pdf` | The SQS Score Explanation never gives the package a tier or routing other than its table row (Major Gaps / Standard review) |
| R6h (products) | New package from the same dec, generate the 126 (the fix acts when a form is stamped) | Page 2 PRODUCTS / COMPLETED OPERATIONS table is empty: no 91580 / 91585, no $1,198 / $803, no 12 / 12 or "COVERAGE FORM" |

### Where it all stands - 1 Oct 2026, after the owner's retest (`bfa8711d`)

- **The retest passed** on every audit wrong value (W1-W9), typed edits (E1-E4), the Sign button (G1-G3), the side
  panel's reasons and points (P2, P3, P5, P6), the cover's rows and score (D2), the questionnaire (Q1, Q2, Q3's
  summary, Q5's green) and "Check if none" (C1, C2). Not reported: D1, Q4, the questionnaire header / ring, Q5's
  retype half.
- **Fixed after it, offline:** the 126 LOC # street number; the cover's agent casing, form names and points hedge; the
  side panel's applicant group (P4); the owner's changes (both lists closed by default, the pending-edits note, the
  verify hover). Google's "Acordly" is the consent screen's App name in Google Cloud Console - the owner changes it
  there. Short retest: R1-R5 in "Retest results - 1 Oct".
- **Next, in order:** (1) R6a-h ("R6 on the open session" above; R1-R5 and the Google change passed); (2) commit EVERY file, including the 28 new ones (three
  are imported by running code - see the top of this file), push, deploy; (3) set Michelle's Contact Phone, then a run
  on Render with her account; (4) send the pending questions (Michelle: 5, 12, 13; Brent: two carriers, expiring
  premiums, No Known Losses, 14, and the D6 note on card numbers and dismissal credits); (5) items 1 and 14 and the
  remaining halves (2's wording, 18's client half, G2's client path and the ACORD 25 holder).
- **Not touched (on purpose):** items 1 and 14 (owner: not yet), 5 and 12 (need Michelle), item 2's forms-first
  wording, item 18's client half (owner declined), the location-table edit that wipes LOC # / county / revenue
  (logged), and the question 4 policy order.
