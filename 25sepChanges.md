# 25sepChanges - Orbin client feedback and our re-run

---

## CHOICE ELECTRIC - Brent + Michelle's test of 5 Oct 2026 (`Choice-Electric-Testing-10_5.pdf`, 27 items) - ANALYSIS 6 Oct, NO CODE CHANGED

**Sources.** The client doc (27 items + screenshots), the 7 uploaded decs (`Choice-Electric/`), and the client's stored
production session **`ca93ed8f`** (read-only, owner-approved 6 Oct: 177 audit events, 7 generated forms, stored PDFs,
guard logs). Five read-only code investigations, each claim re-checked in code. Evidence dumps:
`<scratchpad>/ce/` (session dump, `timeline.txt`, `final_<FORM>.txt`, `guard_<FORM>.json`, offline replays).

### LIVE VERIFICATION BOARD - the owner's runs of 8 Oct 2026 (`b4d18e8e`, `805049a7`, `b38a4367`, `505bf394`; localhost)

**"Live verified" means: seen working in one of THOSE runs, from the stored session data or on the owner's screen.**
Everything else is fixed offline and still owed a live look. Updated after `505bf394` (part R) - the first run with
every 8 Oct fix loaded (backend started 16:26, newest source 16:16).

**STATUS 12 Oct (the owner's fresh run `18ecbfa8`, part Y): 21 done (live verified), 6 waiting on Brent, 0 UI left.**
Every built item passed live on a new package (6 decs, Cyber added after forms). Our parts of 18 / 26 / 27 were seen
live too; 27's count is still 8 too high (part Y, problem 2). Earlier: 10 Oct 14 / 7 built / 6; 9 Oct 14 / 6 / 6 / 1 UI.

| State | Count | Items |
|---|---|---|
| **Done (live verified)** | **21** | 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 20, 21, 23, 24, 25 (12 Oct on `18ecbfa8`: 2, 12, 13, 16, 17, 19, 24 for the first time; 7 / 20 / 21 under Brent's 8 Oct page-one rules - carrier and page-1 premiums blank, Prior Carrier Information on page 4) |
| **Waiting on Brent** | **6** | 7 (where expiring premiums that do not fit the prior-carrier grid go; an EPLI line - forms 152 / 834 / 827 left out for now, owner), 15 (EBL with GL or WC - also decides whether EBL keeps its own policy row), 22 (built; only the "hard stops before forms" rule is left), 18 / 26 / 27 (his two rules: show future hard stops before forms? required values a dec does not print - hard stop or warning, and do they cost Exposure points?) |
| **Ours of 18 / 26 / 27** | **-** | seen live 12 Oct: 26's rows in points; 27's "N items to fix" + "Also listed", hard stops first, the 6 ACORD 140 download blockers listed before forms. 18's "Confirm this value" did not come up (Choice Electric's building card opens the table). Open: part Y problems 1-5 |
| **UI changes, not started** | **0** | - |

How each unverified item is checked is in part R ("How to verify the rest") and part N; the UI round's items (2, 12,
13, 16, 17, 19 and "Open again" taking a fix back) in part W's "How to check it live" table; 18 / 24 / 26 / 27 in
part X's.

### OPEN ISSUES FOUND IN OUR RUNS - NOT IN BRENT'S 27 (kept here so none is lost; detail in parts S, T, T2)
| # | Issue | Where | Next step |
|---|---|---|---|
| X1 | 137 "hired physical damage: primary" ticked with no document stating the basis | 137_CO | rule: a basis tick needs "primary" beside the coverage |
| X2 | 130 OTHER rating row B holds "CO 9812: Employers Liab Incr Limits" - the form has its own INCREASED LIMITS row | 130 | widen the OTHER-row rule to `..._Other_CoverageDescription` + abbreviations |
| X3 | 131 ANY AUTO tick is paired with an unrelated description box; the naked-Yes guard blanks it when that box is empty | 131 | exempt a deterministic tick from the pairing |
| X4 | `umbrella_follow_form` is set from the EXCESS policy's "FOLLOWING FORM" heading and credited to the umbrella | scoring | needs a D6 table (score-moving) |
| X5 | 127 USE "Service" on vehicle 4 - its own schedule line prints no use | 127 | owner's call: USE is policy-level by the 15 Sep ruling |
| X6 | 125 / 127 mailing city + ZIP taken from the vehicles' garaging line (the decs redact the mailing address) | 125 / 127 | decide: blank (never guess) or garaging as a stated address |
| X7 | 140 sublocation description = "Prem. #: 001 Bldg #: 001" (a reference, not a description) | 140 | low |
| X8 | Exposure rows "Operations" / "Cross-Document Consistency" carry deductions that are not about them (= item 26) | SQS panel | **built 10 Oct (part X)**: "Class Codes & Operations" / "Cross-Form Checks", rows as "-N pts" |

### Status board - the 27 items (7 Oct; "done" = fixed offline, live only after commit + deploy + reloaded tabs)
| # | Point | Status | Left / who |
|---|---|---|---|
| 1 | Blank band where the header was | Probably the old tab; not reproducible | A screen recording if it recurs (UI) |
| 2 | "Next" button per section | **Built 9 Oct (part W)**: "Continue to <next page>" + "Skip to form selection" (212px, same as "Back to review"); last page one button | Live look |
| 3 | Document types right | Nothing to do | - |
| 4 | Umbrella $5M vs Excess $4M | **Done**: two policies, no conflict; **7 Oct: a second ACORD 131 for the Excess** (`ACORD_131__excess`: Travelers, $4M, no SIR, Excess ticked, underlying = the Amerisure Mutual $5M umbrella); the plain 131 prints only the umbrella | Brent: should the excess 131 also list GL / Auto / EL under it? Should a follow-form excess count as having an attachment in its score? |
| 5 | Audit "Annual" vs "A" | **LIVE PASS 8 Oct (my earlier FAIL was wrong).** ACORD's OWN tooltip for `Policy_Audit_FrequencyCode_A` reads "enter the code; **A - annual**, S - semi-annual, Q - Quarterly, M - Monthly, O - Other", so "A" is that box's correct code for an annual audit, and no indicator box is ticked. Brent was reading the CHECKBOX row (at expiration / semi-annual / quarterly / monthly / other), which indeed has no Annual. Reading a bare "A" OUT of a document is still refused (`_audit_period_of`). **13 Oct (Z11, owner's decision): the 130 now ticks AT EXPIRATION for an annual audit and leaves its code box empty; the 125 keeps "A".** | Live look on a fresh run (Z11) |
| 6 | Address as a website | **Done**: refused, no card | Brent: which box? (no form of ours prints a carrier website) |
| 7 | Premiums | **Done**: no card, money format, every premium on the 125 incl. Excess $10,692 / EBL $425, total = printed rows; **7 Oct: the 130 prints the WC premium $29,278, minimum $465, class premiums $37,600 / $597 / $180** | Brent: WC in the 125 total, an EPLI row, forms 152 / 834 / 827 |
| 8 | "COMMERCIAL AUTO" as a policy number | **Done** | - |
| 9 | 10 policies; inline edit; wrap | **LIVE PASS in part 8 Oct.** The TABLE renders **10 rows** and the Excess has its own row - `policy_line_records` correctly filters the nine auto coverage parts out of the 20 raw `coverage_lines` entries. (My first grading said 20 rows; I had measured the raw fact, not `policy_lines.table_rows`.) **STILL WRONG: there is no Commercial Auto row.** `canon_line` reads "Auto Medical Payments" as the auto LINE rather than a coverage part, and that record carries no premium (redacted on the dec) and no number, so the de-dup drops it - leaving the auto policy with no row at all. Was: the Excess is its own row; **7 Oct: edit a policy's carrier / NAIC / number / term / premium, add a missing policy, remove one you added - before and after forms**; long text wraps in the new table | - |
| 10 | Remove the "not a conflict" blocks; group by carrier | **Done 7 Oct (round 4)**: both blocks removed (both layouts), a Limit column (each policy's own), sort + "Group by carrier" with premium subtotals | - |
| 11 | Remove "Important" | **Done 1 Oct** (old tab) | - |
| 12 | Keep fixed items listed as "Resolved" | **Built 8-9 Oct (parts V, W)**: a "RESOLVED" heading (tier style) with "Resolved" / "Dismissed" labels and an "Open again" chip | Live look |
| 13 | Remove "Resolve" | **Built 8 Oct (part V)**: no Resolve on the review screen; the editor keeps its own | Live look |
| 14 | 2 buildings, not 3; value columns; template | **Done** | - |
| 15 | EBL "tucks under WC" | **Done**: recognised, warning gone | Brent: WC (his words) or GL (where ACORD prints it: 126 / 131)? |
| 16 | Positive SQS wording | **Built 9 Oct (part W)**: "- fulfill to increase your Submission Quality Score (SQS)™" on every capped message and heading, screen only | Live look |
| 17 | ACORD 125 first and ticked | **Built 9 Oct (part W)**: ticked on arrival; the order stays by match % (owner) | Live look |
| 18 | Hard stop after forms; "Enter at least one value"; two values | **Done**: no stale stops, answers kept; **7 Oct: with 2+ buildings EVERY COPE card (also occupancy-only, also the editor's package HARD STOPS block) opens the location table, package-level asks typed above it**; **10 Oct (part X): the window confirms the values it shows ("Confirm this value")**; **13 Oct (Z11): answers reach the forms - the saved GL class code prints on the 126, building 2 prints the location's hydrant, the fire department type no longer fills the district** | Live look (Z11); Brent: pre-form stop severity, per-building COPE block or warn |
| 19 | Edit button; double-click; Cancel | Edit / double-click **done 1 Oct**; **Cancel built 9 Oct (part W)** - "Done editing - save" waits for a change | Live look |
| 20 | Carrier information on the 125 | **Done**: Federal listed, prior grid GL / Auto / Property | - |
| 21 | Excess as a 125 line | **Done** | - |
| 22 | Best Solutions before forms | **Done 7 Oct (round 4)**: a "Recommendations" section on the review page - "Raise your score" (the scorer's own rows with the same fix window) + "Your forms will need" (Before you generate; after forms the editor's Needs-attention Missing rows), one to-do in one place; **13 Oct (Z11): each form's own checklist cards (125 carrier receiving the submission, 126 GL form type, 130 officer exclusions) are listed before forms** | Live look (Z11); Brent: pre-form stop severity |
| 23 | Location edits not saved | **Done** | - |
| 24 | Pills on form names | **Built 10 Oct (part X)**: plain pink text in the editor's Cross-Form rows and the fix window | Live look |
| 25 | Upload after forms; submission profile | **LIVE PARTIAL 8 Oct**: panel, upload, different-insured guard and the deterministic re-stamp all work; the **AI fill crashed** (sync BackgroundTask, no event loop) - fixed 8 Oct, needs a re-run. Profile **done 1 Oct** (old tab); **7 Oct: "Add documents" before and after forms; reclassify / exclude / supporting-only after forms; the forms update in place** | Owner: exclude BEFORE forms still keeps a document's unique values (today's behaviour) |
| 26 | Exposure score looks wrong | **LIVE FAIL 8 Oct** - Exposure 33: a false "WC payroll is missing" while the ACORD 130 printed all three class payrolls. Fixed 8 Oct (the scalar is derived), 53 -> 65 on that session; needs a re-run. Earlier: false deductions gone (65 -> 75), "LOCAL" radius. **10 Oct (part X): rows print "-N pts" and add up to the pillar; "Class Codes & Operations", "Cross-Form Checks"** | Live look; Brent: do unsatisfiable hard stops cost Exposure points? |
| 27 | 176 items, hard stops at the end | **Done**: 6 fake hard stops + 7 date rows gone, no DRAFT; **7 Oct: "Before you generate" lists the form checks before generation** (on Brent's package: building 2's year / roof / protection class and building 1's roof - the boxes behind his DRAFT); **10 Oct (part X): "47 items to fix" + "Also listed: ...", hard stops first after the download**; **13 Oct (Z11): one premises with two buildings is ONE location - revenue / staff asked once, interest / city limits repeat; five producer-only location-table columns; LLC member count answerable; on `ba7c709d` all 19 after-forms boxes but the fact-less Y/N questions are listed before forms** | Live look (Z11); held: fact-less Y/N questions; Brent: pre-form stop severity |

Not in his doc but his to decide: the proposed date on an expired dec (01/01/2026 printed in Oct 2026 - he retyped
01/01/2027): roll forward or ask? Payment plans with no ACORD code ("semi-annual", "10 pay") print as written - OK?

### A. Why Brent "saw old things" (his afterthought mail) - SOLVED
- primble.ai has served the 1 Oct build (7b681f4) since **1 Oct 17:20 UTC** (Vercel `last-modified`, edge age 4.6 days,
  bundle `index-DLD3siP6.js` contains "Done editing - save", "Continue where you left off", "Score so far").
- Most of Brent's screenshots are the **pre-1-Oct bundle** ("Refresh | Edit Fields | Sign", Best Solutions with %, "SQS is
  calculated after forms are generated", the Important tab) - strings removed in 4f7e7db. His download window is the NEW
  bundle. So at least one browser tab was opened before 1 Oct and never reloaded: a single-page app keeps running the
  code it loaded. The backend he talked to was 7b681f4 (the session carries `active_form_id`, a 1 Oct route).
- **No version check exists** (no build stamp, no "new version - reload" prompt). Old screens + new server can also
  produce bugs that exist in neither build.
- **Fix:** build stamp + `/version.json` poll on focus / every few minutes -> "A new version is available - Reload"
  banner; backend `X-App-Version` header (Render's `RENDER_GIT_COMMIT`) logged against the client's. For this round:
  ask Brent and Michelle to close every Primble tab and reload before retesting.
- Stale-bundle items (already done at HEAD): **11** (Important block), **19** (Edit button + double-click), **22**'s
  percentages, **25**'s "submission profile" (the package page, item 1). Item 1 (blank band where the header was) - not
  reproducible in code; likely the Header's scroll-hide state; get a recording.

### B. The five classes behind almost everything (fix the class, not the item)
1. **Per-policy facts treated as one package fact.** Data Consistency auto-discovers every scalar
   (`ENABLE_FULL_FIELD_RECONCILIATION`, `underwriting_consistency._auto_scalar_keys`) and compares it ACROSS different
   policies - premium, audit term, carrier website, "schedule of underlying". Package scalars come from the
   **first-uploaded dec** (`select_primary_truth` = first dec_page; here the Excess), so the package "carrier" was
   Travelers, the umbrella limit $4M, the total premium $10,692. Excess is folded into the umbrella family
   (`lob_canon` -> `umbrella`), and unnumbered policies on one family collapse into ONE line record
   (`_build_line_records`), so the Excess policy and its carrier vanish. Items 4, 5, 6, 7, 9, 10, 20, 21 + extras.
2. **Checks that only exist after generation, or use stale stored results.** Generation scores with the STORED
   `hard_stops`; a legacy hard stop hides behind its demoted coded twin pre-form (`_LEGACY_SUPERSEDED_BY_CODE`); per-form
   gates and field QA run only on stamped forms. Items 18, 22, 27.
3. **Edits that do not propagate / get undone.** A Data Consistency confirm re-reads all documents and (HEAD `_fv`
   NameError, fixed only in the working tree) drops human answers and re-adds deleted rows; the location table saves
   only its 6 columns and wipes LOC #, construction, values; a 125 box edit updates the fact but re-stamps no other
   form; the loose `locations` list is never re-synced after a table edit. Items 14, 18, 23, 26, 27.
4. **"AI-verified" means "the string is somewhere in the documents", not "it belongs in this box".** Gap fill put
   other sections' values into boxes and our guards then removed GOOD values (building 2 on the 140). Items 26, 27 +
   most extras.
5. **Extraction reads labels and menus as values.** Unticked option lists became audit periods, a redaction label
   became a policy number, a form number became a policy number, a logo address became a website, carrier office states
   became the insured's state, the EPLI "pending/prior" date became a retro date, EPI 540 days became period of
   restoration, NCCI carrier code became NAIC, the WC dividend plan became the payment plan.

### C. Item by item (verdict - root cause - fix - why we left it)
| # | Brent's point | Verdict | Root cause (verified) | Fix | Why we left it |
|---|---|---|---|---|---|
| 1 | Blank band instead of header | Not reproducible | Header scroll-hide state not reset on mount (likely) | Reset header on the review mount; get a recording | Never reported before |
| 2 | Section-aware "Next" button | UI ask, not done | Footer is `continueLabel(genState)` only | "Next: Documents" ... form selection last | New ask |
| 3 | Doc types right | Positive | - | - | - |
| 4 | Umbrella $5M vs Excess $4M "conflict"; each layer its own 131 | **Real** | Excess = umbrella family; one line record; `umbrella_limit` pinned to one line; suggestion = first-uploaded doc. The 131 PRINTED $4M (the excess) as the umbrella limit | Layer axis on line records (excess identified by its controlling-underlying schedule / title); scope `umbrella_*` per record; one 131 per layer = form instances (architecture) | No kit ever had a tower; the pin was built for Orbin's single umbrella ($3M vs $1M) |
| 5 | Audit "Annual" vs "A"; 130 choices | **Real** | Unticked menus read as answers (`_audit_period_of` returns the first word -> "Semi-annual", a value NO document states; stored as the merged fact); 130 code box sits beside OTHER, nothing ticked | A line naming 2+ periods names none; never decode a bare "A"; per-policy fact; 130 resolver ticks the checkbox (annual -> At Expiration, confirm) | We decided "A = ACORD's code" ourselves on 29 Sep and never asked; true for the 125, wrong for the 130 |
| 6 | Address offered as website | **Real** | `carrier_website` undefined in the prompt; Travelers' logo-image address; no URL check; compared across carriers; no form prints a carrier website | URL shape check at merge; no card for a fact no form prints | New shape |
| 7 | Premium formatting; every premium belongs to its own line/form | **Real** | `total_policy_premium` auto-discovered as "identity" (raw strings); five policies' own totals treated as rivals | Premium per line record; format via `canonicalize_currency`; no card | 23 Aug removed premium from line scoping; never re-admitted |
| 8 | "COMMERCIAL AUTO" as policy number | **Real** | `is_not_a_policy_number` has no digit rule (verified: returns False) | Brent's rule: no digit = not a policy number; one check everywhere | Every kit had real numbers |
| 9 | 9 policies not 10; inline edit; wrap | **Real + asks** | Excess merged into the umbrella record (carrier Travelers - Amerisure Mutual lost); table read-only; CSS `nowrap` | Record per policy; wrap Line/Carrier/Source; inline edit + add line = product feature | Line identity is per FAMILY by design |
| 10 | Remove "NOT A CONFLICT" blocks; group by carrier | UI ask | Blocks restored by the owner 27 Sep | Move their 2 unique facts into the table, then remove; sort/group | Owner's 27 Sep restoration - needs owner OK |
| 11 | Remove Important block | **Done at HEAD** (stale tab) | Removed in 4f7e7db | - | - |
| 12 | Fixed items vanish from Required / Binder | **Real** | Legacy rows are rebuilt each recalc (fixed = gone); cross-form rows are a stale mirror that never refreshes (shows "Resolved" by accident) | Pre-form "Resolved (n)" per group from status + not live; refresh mirrored rows | Item 16 shipped editor-only; conflicts with Brent's #18 "hide under Reviewed" - pick one |
| 13 | Drop "Resolve" | UI ask | One `IssueStatusControl` everywhere | Keep Open to fix + Dismiss; auto "Resolved" tag after a fix | Client review #8 asked for Resolve earlier |
| 14 | 2 buildings not 3; no COPE columns; template | **Real** | Auto garaging "DENVER, CO 80221" (prompt key `locations` undefined) became a premises (working tree drops it, fragile); building labels used as street addresses; LOC # = row position; table has 6 columns, saving deletes construction/values | Building label -> LOC/BLDG #; garaging never a premises; add LOC #, BLDG #, construction, year, building $, BPP $ columns (template follows); merge-on-save | Redacted decs never tested; table data loss logged 1 Oct as "next fix" and not done |
| 15 | EBL "tucks under WC" | **Real (canon) + decision** | `canon_line("Employee Benefit Liability ...")` = None (only plural known) | Recognise singular; ACORD puts EBL on 126/131/160, never the 130 - **confirm with Brent** | Singular never seen |
| 16 | Positive wording, not "capped at 85" | UI ask | Text in sqs_service messages; issue ids hash the MESSAGE | Display-layer rewrite only (never change `message`) | New ask |
| 17 | 125 selected + first | UI ask | Sort by confidence (125 at 80% sank); selection starts empty | 125 first and pre-ticked | New ask |
| 18 | Hard stop only after generation; "Enter at least one value"; two building values | **Real** | 18:21 audit confirm re-ran the pipeline; HEAD `_fv` NameError dropped human answers; stops computed without occupancy were STORED; generation scored with the stored stops and the hidden legacy stop surfaced (cap 60). Modal submits only TOUCHED fields | One `stops_now()` door for every scorer; never hide a hard legacy stop behind a demoted twin; modal "Confirm these values"; per-building COPE | `_fv` silent since 24 Aug (inside a try); supersession table predates C75 |
| 19 | Edit button / double-click; Cancel | Stale tab + **new ask** | HEAD has both; no discard path | Add "Cancel" (discard, confirm if edits) | Item 10 rule "every exit saves" |
| 20 | Carrier info missing on 125 | **Real** | Federal (EPLI) dropped: a writer needs a number or premium; prior-carrier grid drops every row without a policy number (all redacted) | Writer = carrier + term on its own dec; grid rows on carrier + term + premium | Kits always had numbers |
| 21 | Excess as an LOB line | **Real** | One box per family; OTHER premium boxes never filled (ACORD tooltip typo "the for" breaks `_LOB_PHRASE_RE`) - EBL $425 blank; EPLI no row; total 58,385 includes rows not shown | Second policy of a family -> next OTHER row with premium; OTHER premium owner; total = printed rows | Never two policies in one family |
| 22 | Best Solutions before forms | **Real gap** | The pre-form package result already holds them; nothing renders them; Exposure/Property rows have no field | Pillar ledger rendered on the Review rail with the fix window | Pre-form card kept "tier only" (H2) |
| 23 | Location edits did not save | **Real** | The 17:53 delete WAS saved; the 18:21 confirm re-merge re-added the row (working tree marks human tables - new saves only; `write_location_answer` hole) | Commit the 5 Oct fix + re-mark after every schedule writer | Same `_fv` class |
| 24 | Pill on form tags | UI ask | Editor Cross-Form `row()` | Plain pink text | New ask |
| 25 | Upload docs after generation | **Not built** | Upload always starts a new package; re-reading actions 409 after forms | Append-to-session upload + re-stamp changed boxes (L, owner decision) | Locked on purpose 1 Oct |
| 26 | Exposure 65 looks wrong | **Formula right, display wrong, 10-15 pts ours** | Pillar = 100 - deductions (spec) but rows show 100 - own deduction. -10 = two FALSE location warnings (stale `locations` copy after Brent's delete - his fix LOWERED the score); -5 "no radius" ("LOCAL" not read); -20 "no GL class codes" mislabelled "Operations" (126 meanwhile prints WC codes as GL) | Show "-N pts"; derive `locations` from the table; read radius classes; one GL-code door | Per-row tip removed 27 Aug; arithmetic shown nowhere |
| 27 | 176 items; hard stops at the end | **Real** | 176 = 6 + 18 + 152. All 6 hard stops are OUR guards emptying building 2 on the 140 (construction "NON-COMBUSTIBLE - LIGHT STEEL" is printed in the dec; Brent's year/PC answers). **They blocked the download: Brent's package went out as a DRAFT** (`download_zip_draft`, 23:01). Of 176, ~28 accurate asks + ~36 genuine verify rows; ~112 inaccurate, self-inflicted, duplicate or informational | Fix the guards + per-building COPE; propagate edits; count only actions; dry-run deterministic stamp before forms | Field QA was built post-generation only |

### D. Wrong values on the forms Brent did NOT report (fix before his next look)
- **126:** GL hazards = the WC class codes 5190/8742/8810 with WC payroll (extraction put the WC schedule in
  `gl_class_code_schedule`; `_drop_codes_another_line_owns` reads the cell name, not the list key, and the wrong
  schedule witnesses itself); GL aggregate 1,000,000 (dec 2,000,000 - the umbrella's underlying schedule is extracted
  with ONE limit per line); the property wind/hail "2" as a GL deductible.
- **131:** umbrella limit $4M (the excess); Employee Benefits section filled with the EPLI policy (EBL is EXCLUDED);
  GL aggregate 1,000,000; "COMMERCIAL AUTO" as the auto policy number; no umbrella carrier or premium.
- **130:** claim count "1" (no loss data; the guard accepted "(1) Each Employment Claim" as evidence); prior mod "100%"
  (dec 1.08); NCCI carrier code 11525 in the NCCI RISK ID box; small-deductible RATE as "$6.50" deductible; prior WC
  carriers = Travelers / ACE with form numbers; building numbers as floor counts; "4" years in business; audit "A"
  beside OTHER; dividend plan as the payment plan.
- **125:** "IL DS 71 05 02 08" (a form number - the ISO regex has no second letter group) and "COMMERCIAL AUTO" in
  question 4; payment plan "Blue I (B1) Dividend Plan"; proposed term 01/01/2026 on 10/05/2026 (9 months past - the
  stale test checks the END of the next term, not its start; Brent retyped 01/01/2027-01/01/2028); EBL premium blank;
  no Excess / EPLI rows; total 58,385 not the sum of rows; Federal missing from CARRIER; prior grid Auto only.
- **127:** garaging street "111 Denver" (territory code glued on); raw OCR page text in the "vehicles owned but not
  scheduled" explanation.
- **137 CO:** property rate lines ("GRP I 0.053 $533.00", "Prem. #: 001 Bldg #: 001") as symbol descriptions; Med Pay
  $1,000,000 (schedule: $5,000).
- **140:** building 2 construction, limits $421,714 / $75,000 stock, deductibles removed by guards (Guard 2 row dedup;
  the unanchored-row net; the numeric meaning gate classing every "Prem #" schedule value as a PREMIUM).
- **Labels:** the producer's own location-table rows are labelled `client_arq` (green "Client") on 130/131/140.
- **Security:** `session.docs[*].facts` (every per-document fact) is stored as PLAIN TEXT while `session.facts` is
  encrypted. Needs the same field encryption + a migration (`scripts/encrypt_facts_data.py` pattern).

### E. Not defects / already right
3 (doc types), 11 / 19 / 25-profile (stale tab), the 125 "A" code itself (ACORD's code for annual on the 125), CARRIER
joined list (owner's 1 Oct rule - only Federal missing), Brent's 94 form edits are all intact in `field_state`
(only the two LOC # boxes were wiped by table saves).

### V. Items 12 / 13 BUILT (owner's spec, 8 Oct night - question 5 settled by the owner, not sent to Brent)
The review screen (rail layout, the default) now works like the editor's SQS panel "Reviewed":
- A hard stop or warning that is DISMISSED, or fixed through "Open to fix", leaves its list and goes into a collapsed
  **"Resolved (n)"** dropdown at the bottom of its own page (Hard Stops / Warnings), with a small **"Resolved"**
  (value entered through Open to fix) or **"Dismissed"** label and an **"Open again"** button. Open again: a
  dismissed item goes back to its list; a fixed one is reopened by the editor's own reopen (`handleReopenIssue` ->
  `/api/audit/reopen-issue`: the typed value is taken back and the item returns to its list).
- An answer that did NOT clear the check leaves the item in its list (it still needs attention).
- **No "Resolve" button** on any review-screen hard stop or warning (both layouts); "Open to fix" + "Dismiss" stay.
  The editor keeps its own controls.
- Each stored status records its page (`submission_issue_status.severity`, "hard" / "warning", added by an
  idempotent ALTER on startup), so a fixed item that stops firing is filed under the right page after a reload;
  an older status with no page files under Warnings.
- Empty pages say the truth: "No open hard stops. A dismissed hard stop still holds the score at 60 until its value
  is fixed."
Code: `frontend/src/utils/resolvedIssues.js` (pure rules), `ReviewRailLayout.jsx`, `AcordModal.jsx`
(`IssueStatusControl showResolve`, `reviewSeverity`, `reopenFromResolved`), `models/schemas.py`,
`services/audit_service.set_issue_status`, `routes/audit_routes.py`. Tests: `tests/test_review_resolved_section_8oct.py`
(11, the rules run under node); `test_round5_stops_7oct.py` updated (it pinned the old function text). Full suite **13,659 passed, 1 failed (the known one), 19 skipped**. The classic
layout (`VITE_REVIEW_LAYOUT=classic`) only loses Resolve - it has no Resolved section.

### W. The UI round - items 2, 16, 17, 19 and the Resolved follow-ups BUILT (owner, 9 Oct 2026; frontend only)
Every decision below is the owner's (9 Oct); nothing here moves a score or touches stored data.
- **Item 2 - the review footer walks the pages.** Before forms, every review page but the last shows two solid-pink
  buttons: **"Skip to form selection"** (left) and **"Continue to <next page>" ->** (the rest of the row), in rail order
  Overview > Documents > Submission Integrity > Data Consistency > Hard Stops > Warnings > Recommendations. The last page
  has the one button "Continue to form selection". Once forms exist or are generating: one button "Continue where you
  left off" on every page, unchanged. Nothing is ever blocked by open items. The skip button is the form-selection
  screen's "Back to review" button (same classes, `step-footer-*`); both are **exactly 212px** (owner) and grow only when
  their words need it (text-only zoom, a minimum font size, a translation - measured 262 / 284px, no spill). Narrow, the
  row stacks (main on top, both full width): the review footer under 600px, form selection under 520px (with Back at
  212px, "Generate 12 Forms Now" wrapped just above 480). A second click of a double-click is ignored on the main button
  (it would land on the next page's button and, from Warnings, leave the review). The interrupted-run note now says
  "Go to form selection to generate the forms again." Code: `utils/packageGeneration.js` (`nextReviewStep`,
  `SKIP_TO_SELECTION`), `ReviewRailLayout.jsx/.css`, `App.css`.
- **Item 16 - positive SQS wording, on screen only.** Every message that said the score is "capped / held / pinned"
  now reads Brent's words - e.g. "Carrier-Grade COPE incomplete **- fulfill to increase your Submission Quality Score
  (SQS)™**. Missing: ..." - in the fix window, the review cards (both layouts), the editor's lists and HARD STOPS blocks,
  the download review, the essentials screen and Recommendations. The six backend shapes (COPE x2, FEIN, the two date
  mismatches, the loss-history attestation, the pinned loss-run year) are rewritten by `utils/positiveWording.js`
  at render; the STORED message is untouched (issue ids, statuses, the legacy rule table key on it). The headings and
  notes said the same thing and were rewritten too (owner: "this should not appear on any other messages"): "Caps your
  SQS at 60 / 85" -> "fulfill to increase your Submission Quality Score (SQS)™"; the Reviewed notes now say what raises
  the score ("Fix the value of the hard stop you marked to increase your SQS™ - marking it records your review only");
  empty states "Your SQS™ is clear of hard stops / warnings". **Kept on purpose:** the SQS panel's arithmetic line
  ("raw 88, held at 60 = 60", the client's C3 traceability) and the downloadable audit report. **Not changed:** the
  cover PDF (not the screen). A backend test harvests every backend string with cap wording and fails on a new one.
- **Item 17 - ACORD 125 ticked.** Ticked the moment the producer reaches form selection, unless they unticked it; the
  list keeps the recommender's match-percentage order (owner). Ticking it at upload would have narrowed the review
  page's "Your forms will need" checks to ACORD 125 alone, so those checks follow the ticks only once the producer
  changes one. Code: `utils/formSelection.js`, `AcordModal.jsx` (`resetFormTicks`, `declined125`, `formTicksTouched`).
- **Item 19 - "Cancel" in the form editor.** Beside "Done editing - save": every box goes back to its last saved value,
  a signature removed in this edit comes back, nothing is sent or redrawn; asks first when something would be lost.
  "Done editing - save" waits for a change (Brent: "reserved for actual updates"). The one exception to "every exit
  saves". Over 1366px the edit-mode toolbar keeps its buttons on one row and the form name truncates (it had 1px to spare
  at 1440 before Cancel). **Known:** a 1024px window with the editor sidebar open hides the form name in edit mode and
  the counts touch the buttons by ~3px - close the sidebar. Code: `PDFJsViewer.jsx/.css`.
- **Resolved follow-ups (owner's screenshots, 9 Oct):** the Resolved section takes the look of the headings around it -
  on Warnings a heading like "REQUIRED BEFORE SUBMISSION" (rows in one card under it), on Hard Stops (no tiers there) a
  card like the hard-stop cards - and "Open again" is a real chip, the Dismiss chip's size and colours with a turn-back
  arrow (it rendered as a bare browser button). A row stays in place showing "Opening..." until the server answers; a
  dismissed item that has since stopped firing shows "No longer applies" instead of "Open again" (there is nothing to
  reopen, and reopening it only made it vanish).
- **"Open again" takes the fix - and its points - back (owner, 9 Oct evening).** Before, reopen undid only a TYPED
  value, by deleting it; a fix made through a table (the location table behind the COPE checks, loss history, WC
  classes) or an ACORD 101 note stayed in place, so the score stayed up. Now every "Open to fix" records exactly what it
  changed - facts, flags and form boxes, before and after (`services/issue_fix_undo.py`, encrypted at rest like facts)
  - and "Open again" puts all of it back and re-scores: the score returns to the exact pre-fix number (tested on the
  real routes and scorer, before and after forms). If something changed those values after the fix, nothing is undone
  and the producer is told to use "Open to fix" - an undo never erases later work. Dismiss never moved a score, so
  reopening a dismissal changes none. **An adversarial review (26 findings, 20 confirmed) hardened it the same night:**
  only the fix's OWN writes are recorded (a client answer or an AI fill landing in the same moment is left out, and the
  snapshot is taken right at the write); the shared table bookkeeping is recorded per table (a later WC table save no
  longer blocks undoing a location-table fix); a second fix of the same issue is folded in only when nothing else changed
  those values in between, otherwise the undo is refused; a document added / excluded / reclassified retires every undo
  (the merge ran on other evidence); a form generated after the fix is re-stamped from the restored facts; the review
  list's own Reopen button goes through the undo too; a reopen that undid nothing no longer stores "open" (the row
  vanished on reload); the old "clear the typed value" fallback for fixes made before this change runs only from the
  editor's Cross-Form panel, never the review screen (it could delete a value typed elsewhere); and for a moment after a
  screen change the second click of a double-click is dropped wherever it lands (it could tick a form row).
- **Responsive (owner):** the review footer stays one line down to 320px; the editor toolbar keeps one row on wide
  screens and puts its buttons on a second row when the viewer is under 900px (a laptop with the sidebar open, a
  tablet) instead of overlapping; the Resolved sections and chips were checked at 390 / 768 / 1280.
- **From the review of this round:** a double-click's second click is ignored on every button that changes screen (it
  could land on "Generate", live now that ACORD 125 starts ticked); ACORD 125 is not ticked when the producer uploaded
  their own filled ACORD 125; older stored wordings ("Score is capped at 60 ...") are rewritten too; the editor's Best
  Solutions rows use the positive wording; Cancel after a failed save reads the form back; ticking and unticking a blank
  checkbox is not an edit.

**How to check it live (restart the backend first - the reopen change is server code - then reload the browser; a fix
made before the restart reopens the old way):**
| # | Where | Do | Expect |
|---|---|---|---|
| 2 | Review, before forms | Click the pink "Continue to ..." on each page; then try "Skip to form selection" | Overview > Documents > ... > Recommendations, each page opens at its top; Recommendations has one button "Continue to form selection"; Skip goes straight there; a double-click moves one page |
| 2 | Same, after generating | Open the package page | One button "Continue where you left off" on every page |
| 16 | Hard Stops / Warnings / a COPE warning's "Open to fix" | Read the subtitles and the message | "fulfill to increase your Submission Quality Score (SQS)™" - "capped at" appears nowhere |
| 17 | Form selection | Arrive from the review | ACORD 125 ticked ("1 selected"), list still in match-% order; untick it, go back and return - it stays unticked |
| 19 | Editor | Edit form; then type in a box; then Cancel | "Done editing - save" greyed until a change; Cancel asks, puts the saved value back, leaves edit mode, score unchanged |
| 12 / 13 | Review | Dismiss a hard stop and a warning | Hard Stops: a "Resolved" card with a yellow "Dismissed" label and "Open again"; Warnings: a "RESOLVED" heading like the tiers; no "Resolve" button anywhere on the review |
| reopen | Review | Note the score; "Open to fix" an item and enter its value; then "Open again" | Score goes up and the item moves to Resolved; "Opening...", then it is back in its list and the score is the noted number again |
| mobile | Phone, or the browser's device mode at 390px; a narrow laptop window | Repeat the footer, Resolved and editor checks | Buttons stack cleanly, nothing runs off the screen, the editor toolbar uses two rows |
Tick each item off on the LIVE VERIFICATION BOARD above (move it from "Built, needs a live look" to "Done").
Tests: `tests/test_review_next_button_9oct.py`, `tests/test_ui_items_16_17_19_9oct.py`; updated where they pinned the
old wording or behaviour (the tests were wrong, the code intended): `test_review_resolved_section_8oct.py`,
`test_item16_reviewed_30sep.py`, `test_viewer_items_10_18_30sep.py`, `test_package_page_1oct.py`. Measured in headless
Chrome with the built CSS (footer at 23 widths, the editor toolbar at 7 widths with long names, the Resolved section).

### X. Our parts of 18, 26, 27 and item 24 BUILT (owner, 10 Oct 2026: "fix what is our part")
Brent's halves of 18 / 26 / 27 (show future hard stops before forms? a required value no dec prints - hard stop or
warning, and does it cost Exposure points?) are untouched and still wait on him. Measured on the owner's run `2076fe35`.
- **Item 26 - the Exposure rows add up and name their cause.** Each row printed 100 minus its OWN deduction ("80%")
  while the pillar is 100 minus ALL of them, so 85 / 80 / 80 and four 100s sat beside an Exposure of 45. Rows now print
  the points they took: **Auto Completeness -15 pts, Class Codes & Operations -20 pts, Cross-Form Checks -20 pts**, the
  rest "0 pts" -> 100 - 55 = 45. Two rows were renamed by what they charge: "Operations" carried "no GL class codes"
  (also WC codes, a code that does not match the operations, a contractor's subcontracting %) -> **"Class Codes &
  Operations"**; "Cross-Document Consistency" carried the two cross-form hard stops (Minimum Viable COPE, Period of
  Restoration) on documents that agreed -> **"Cross-Form Checks"** (every check the cross-form validator raises: -15 a
  hard stop, -5 a warning, cap 20). One label table (`sqs_service.EXPOSURE_BUCKET_LABELS`) - the scorer's rows, the
  unscored fallback and Best Solutions ("Incomplete: Class Codes & Operations, Cross-Form Checks, Auto Completeness")
  read it; a stored run gets today's names when it is opened (`with_current_bucket_labels`, at `GET /api/session` and
  `current_package_sqs`) without a recalculation. Keys unchanged. **No score moves.** Whether those two hard stops
  should cost Exposure points at all is Brent's question (F00), not changed here.
- **Item 18 - "Enter at least one value" in the fix window.** The window shows the values on file but sent only boxes
  the producer TYPED in, so Apply on a window showing the right values said "Enter at least one value." Now, with
  nothing typed and values showing, the button reads **"Confirm this value" / "Confirm these values"** and sends them as
  the producer's answer; typing switches it back to "Apply" and only the typed boxes go (an untouched box is never
  re-sent beside a typed one - unchanged). An empty window still asks for a value; a box emptied by hand says "Type
  the correct value, or close this window to keep what is on file."; after a save that asks for one more value nothing
  is re-sent. Code: `utils/fixWindow.js`, `ResolutionModal.jsx`. A confirmation is a producer answer, so the box's
  label and fill weight become the producer's (the same as typing it).
- **Item 27 - the download review counts what there is to fix.** "176 items flagged" (190 on `2076fe35`) added every
  open card and every needs-attention row of every kind. The headline is now **"47 items to fix - review before
  downloading"** (8 hard stops incl. the 6 required boxes that block the download + 39 Missing boxes the producer
  fills), with **"Also listed: 26 to verify, 93 held back by the AI, 16 for the applicant to sign, 8 recommendations"**
  under it; nothing is hidden. The checklist after the download says "To fix before sending (47)" and lists its hard
  stops FIRST (they were after every form's rows - Brent's "hard stops at the end"); a required box that blocks the
  download counts as a hard stop there too. The forms list says "Missing 39, To be signed by the applicant 16, AI
  held back 93, Please verify 26" instead of one "(174)". Code: `utils/needsAttention.js` (`downloadReviewCounts`,
  `alsoListedText`, `downloadReviewHeadline`), `AcordModal.jsx`, `NeedsAttentionPanel.jsx`.
- **Item 24 - form names are plain pink text.** The editor's Cross-Form rows and the fix window's header printed
  "ACORD 140" as a pink pill; both now print "ACORD 140, ACORD 125" as plain pink text.
- **"Open again" on a form generated AFTER the fix (left open from the 9 Oct review, S2).** Generation labels a box
  that prints a producer's answer "producer" - and the fix IS a producer's answer - so the undo's re-stamp kept the
  fix on that form as "a person's value". It now moves the fixed facts' own boxes while they still print the fix,
  keeps any box a person changed after generation, and labels each restored box by who supplied the restored value
  (`issue_fix_undo._restamp_late_forms`, `arq_service._restamp_changed_boxes(keep_edited_own=True)`). Proven: the old
  code reproduces the defect, the new test fails on it.

**How to check it live (restart the backend, reload the browser):**
| # | Where | Do | Expect |
|---|---|---|---|
| 26 | Editor, Total Package Score, expand Exposure Consistency | Read the rows | "-N pts" per row, the names "Class Codes & Operations" and "Cross-Form Checks"; 100 minus the rows = the pillar |
| 18 | Any "Open to fix" whose window opens with a value already in the box | Click the pink button without typing | It says "Confirm this value" and saves; type in a box and it says "Apply" |
| 27 | Download (any package with open items) | Read the review's top lines; download; read the checklist | "N items to fix" + "Also listed: ..."; after the download "To fix before sending (N)" with the hard stops first |
| 24 | Editor side panel, Cross-Form Validation; any "Open to fix" window | Look at the form names | Plain pink "ACORD 140", no pill |
| reopen | Fix an item BEFORE forms, generate, then "Open again" | Look at the form box | It prints the value from before the fix again |
Tests: `tests/test_our_parts_18_24_26_27_10oct.py` (18), +2 in `tests/test_reopen_takes_the_fix_back_9oct.py`.

### Y. The owner's fresh run `18ecbfa8` (12 Oct 2026) - every built item passed; 5 problems found (ours)
6 decs uploaded, `25-26 Cyber Policy.pdf` added after forms (item 25: done in ~3 min, 125 ticks Cyber, 11 policy rows,
no Data Consistency card). Owner passed 1, 2, 3, 4, 6, 8, 9, 10, 12, 13, 16, 17, 18 (part 1), 19, 22, 23, 24 on screen
(12 / 13 with "Open again": 41 -> 46 -> 41 on the GL class code 92478). Checked on the stored row: 125 page 1 carrier,
policy number and every premium blank; Other lines EBL + Excess; Prior Carrier Information (page 4) GL $16,818,
Property $6,275, Auto; 130 audit "A", no tick, WC $29,278 on pages 1 and 2; umbrella 131 Amerisure Mutual $5M over GL /
Auto / EL; Excess 131 Travelers $4M over the Amerisure umbrella, no claims-made tick; 127 policy number blank; building
values right (BPP $73,008 is printed for BOTH buildings; building 2's $75,000 is stock).
**Changed:** the editor's Cross-Form Validation "RESOLVED (n)" list is a closed dropdown (owner) - `AcordModal`,
`tests/test_live_run_12oct.py`.
**All five FIXED offline 12 Oct (owner: "fix these 5 problems and do not touch any other fixed things") - each
measured so nothing else moves; backend restart needed.**
- 1: `scoped_evidence.retention_values` (rule e): an AI umbrella / excess retention (`ExcessUmbrella_Umbrella_
  DeductibleOrRetentionAmount_*` on 131, its copies, 25) must sit beside a retention / SIR / self-insured / retained /
  deductible label in that layer's own documents. Corpus: 172 packages hold the box - 84 rule values never judged; 5 AI
  values: 3 ACORD 25 "1,000" kept, 2 refused (this run's 5,000 and `b248c194`'s 10,000 - both Choice Electric excess
  layers that print no retention). 0 correct values lost.
- 2: `needs_attention._page_one_premiums_withheld` - the stamper's own test; on `18ecbfa8` the 125's Missing list
  38 -> 30 (the 7 page-1 premiums + the estimated total), so "49 items to fix" -> 41. A quote / a person's premium
  keeps the 30 Sep to-do.
- 3: the table's examples read "e.g. 789 Commerce Dr" (italic, lighter - `scheduleImport.exampleHint`,
  `.schedule-cell::placeholder`); the Template is the column names only (`templateCsv`); an untouched example row
  from an older template is skipped on upload (`isTemplateExampleRow` - the WHOLE example only); a table save that
  still misses required cells keeps the window open with "Still missing: Street address on rows 1 and 2"
  (`missingRequiredSummary`; a typed value alone closes as before). Apply is NOT blocked (owner's suggestion
  weighed: partial saves stay - Brent's #18 "had to retype").
- 4: `session_documents.plan_form_fill(new_text=)`: a "New document" choice must be printed in the NEW document's own
  text and differ by more than punctuation (`_words_only`, `_says_it`); fills of blank boxes unchanged.
- 5: "March 1, 2022" is a date (`needs_attention._DATE_SHAPE` reads written dates - the sentence becomes "...could not
  be confirmed for this box"); a blocking 140 box names its row ("(row 2)", field QA's gate message only); the
  building card names only the missing parts ("Required: street address and occupancy" - `sqs_service._words_list`;
  all four missing reads word for word as before) and open cards take the live words on every sync
  (`audit_service.plan_card_sync` "reword", open + unanswered only, like "repoint"); the Cyber policy row reads
  "Cyber" (`policy_lines._names_a_section` - over the 65 names in 1,137 stored packages it changes only that one).
Tests: `tests/test_live_run_12oct.py` (21). Updated (the TEST was wrong): three in
`tests/test_needs_attention_30sep.py` pinned the 30 Sep premium to-dos on two stored dec renewals (29 -> 24 rows;
no "_missing_producer" row) - Brent's 8 Oct answer keeps those page-1 premiums blank. Full suite: 13,747 passed,
1 failed (the known `test_arq_acord125_missing_only`), 19 skipped. Frontend builds.
**How to see each fix (restart the backend, Cmd+Shift+R):** on the CURRENT package `18ecbfa8` - the download count
(41), the "March 1, 2022" sentence, the Cyber row name, the table hints / Template / "Still missing" note, and the
building card's words after any save or answer. Only a NEW generation shows the Excess 131 retention (blank) and the
140 hard stops' "(row 2)"; only a document added after forms shows the "New document" rule (the two stored choices
stay until "Keep current").

**Problems found (as reported to the owner):**
1. Excess 131 retention = 5,000 (`ai_verified`) - the Excess dec's "POLICY LIMITS (000 OMITTED) ... 5,000 EACH
   OCCURRENCE" is the UMBRELLA's $5,000,000 in thousands; the Excess prints no retention. Rule: an AI retention / SIR
   needs a retention / SIR / deductible label beside it in that layer's own documents.
2. Download "49 items to fix" counts 8 ACORD 125 page-1 premium boxes (7 lines + the estimated total) as Missing - Brent's
   8 Oct rule leaves them blank on a renewal. Should be 41. `needs_attention`'s 1 Oct premium rule
   (`lob_premium_box_pairs`) never learned that rule.
3. The location table's placeholders look like data ("789 Commerce Dr", "Houston", "TX", "77001", "Warehouse and
   dispatch", "1998", "Metal", "2015", "3", "100") - the owner read the empty street address as filled. The Template CSV's
   second line is that example row and `rowsFromMatrix` imports it: an uploaded template adds a fake building (vehicles /
   drivers the same). Owner proposed blocking Apply until every required cell is filled; recommended instead: empty boxes
   look empty, the example row is never imported, and Apply says what is still missing.
4. Adding Cyber raised two "New document" choices on ACORD 140 (sublocation "Prem #: 001 Bldg #: 001" vs "Prem. #: ...")
   - text the Cyber dec does not contain (the AI read it from the package's facts) and differing only by a dot.
5. Text: "Your documents print 'March 1, 2022', which is not a date" (`needs_attention._DATE_SHAPE` reads numeric dates
   only; the real reason - the EBL retro date, not the umbrella's); the six ACORD 140 download hard stops name no building
   (read as duplicates); the min-COPE rec says "Required: street address, occupancy, construction type, and building or
   BPP value" when only occupancy + address are missing; the Cyber policy row is labelled "Cyber Incident Response Team".

### Z. Save progress - an unfinished fix is not Resolved (owner, 13 Oct 2026, run `18f6914f`; frontend only)
**What the owner saw.** Pre-form, Hard Stops page: the COPE hard stop's window (location table + occupancy type above
it) was saved with the table filled and occupancy type left blank. The item came back with a green "Resolved" tag and
"Reopen", the page said "All 1 handled" - while the stop still fired ("Property Minimum Viable COPE incomplete -
missing: occupancy type") and still held the score. Stored row: `submission_issue_status` iss_57ef2c1bec59 =
"resolved" (hard) at 19:04:32; `occupancy_type` empty.
**Cause.** `AcordModal.handleIssueResolved` set "resolved" after EVERY successful save, whatever the save did (only the
add-form branch checked). The 12 Oct part Y note then offered "Apply the fix" over an unfinished table.
**Owner's rule.** Unless an item is completely fixed: no Resolved section, no Resolved tag; it stays in its list with
"Open to fix", and the window offers "Save progress" instead of "Apply the fix". Every hard stop / warning whose window
holds more than one value (boxes, rows).
**Built.**
- `utils/fixProgress.js`: `listedIssues` (every item a response or the screen lists - grouped hard stops, warning
  tiers, cross-form issues, bare sentences) and `fixLeftOpen` - after a save the item is still open when the same item
  is still listed (by id or by its words - the editor's raw cross issues carry no server id), or its rule now fires
  under NEW words (a partly fixed card renames what is missing: new id, same unfinished item); another listing of the
  same rule that was there before is a different item (location 2). Errs toward "still open".
- `handleIssueResolved`: "resolved" only when `fixLeftOpen` is false; a "resolved" an earlier partial save left on the
  item is set back to "open".
- `ResolutionModal`: a table window that still lacks a value it shows (a box above the table, or a required cell)
  names it ("Still missing: Occupancy Type. Save your progress now and finish it later - it stays open until
  everything is in.") and its button reads "Save progress"; the save closes the window, "Open to fix" shows what was
  saved. Field windows with several boxes are "whichever applies" (their own hint says so) - the label cannot know, so
  the server's answer after the save decides. The part Y "Still missing ... Apply the fix" note is removed (its test
  was updated - the owner's new rule outdated it, the code was not wrong).
**Not changed:** the trade-off note ("Saved - one thing to check" + "Apply the fix" when the RAISED item's box is on
the screen) - a different case; none-mode "Mark resolved" (a deliberate mark).
**On `18f6914f` now:** the stale "resolved" stays until that item is saved once more - Open to fix, then Save progress
(or fill occupancy and Apply). Do NOT press its "Reopen": that takes the saved table back.
Tests: `backend/tests/test_save_progress_13oct.py` (6, rules run under node). Related screen tests 1,664 passed;
frontend build clean.

### Z2. `18f6914f` pre-form answer sheet (13 Oct) - replayed read-only through the real fix routes
All 9 remaining items (6 warnings, 2 score rows, ACORD 125 start date) cleared in memory: 60 -> 90 "Submission Ready", no
cap, dry run "ready". Only ONE answer is in the documents: **UM/UIM $1,000,000** (Business Auto Policy vehicle schedule,
UNINSURED/UNDERINSURED MOTORISTS column, every vehicle - the app's reader missed the column and raised a false "not
specified"). Everything else is a labelled test value (the decs redact the insured block; no drivers, GL class schedule,
period of restoration, loss runs or start date are printed). Files: `<scratchpad>/plan18f6/` (`sim_steps.json`,
`sim_out.json`). **Open defects confirmed on the current code, NOT fixed:**
- F1 `answer_semantics`: a narrative containing "no losses" / "no claims" / "never" / "none" / "without" is stored as an
  ABSENCE - `additional_remarks_text` = "" and any remarks on file emptied, while the route says success.
- F2 `pdf_service` guard `driver_personal_unattributable` blanks the PRODUCER's own driver table (DOB, licence #,
  licence state, hire date, years) on ACORD 127: 8 typed drivers = 40 boxes "held back" (dry run 4 -> 44). Names only
  avoids it.
- `operations_description` = "LOCAL SERVICE" (AI) is the auto schedule's vehicle-use column, not the business; it prints
  as the 125 description of operations and the pre-form screen has no link to change it (F4).
- UM/UIM column not read by the vehicle-schedule reader (above).

### Z3. Fixed the same night (owner: "fix the remaining issues ... then I generate") - each proven on `18f6914f`'s own boxes
Replayed read-only (the Z2 answers + the operations description), then stamped ACORD 125 / 127 from the result:
- **Driver table (F2):** `pdf_service` driver guard keeps a box that prints exactly what a PERSON-saved, unchanged
  `auto_drivers` row states (`schedule_capture.human_rows` + `_is_person_driver_cell`). All 8 drivers print DOB,
  licence, state, hire date, years; dry-run "held back" 44 -> 4. An unmarked or later-changed record is still cleared.
- **Narrative (F1):** `answer_semantics.interpret_answer` step 0c - a NARRATIVE_FACT_KEYS answer longer than five words
  is the text to print; short answers ("None", "N/A", "TBD") read as before; scalar facts unchanged.
- **"LOCAL SERVICE":** `normalization.is_vehicle_use_label`; the merge drops it per document
  (`extraction_service.drop_vehicle_use_descriptions`); Tier 2 lists it as missing unless a person typed it
  (`sqs_service._describes_a_vehicle_not_the_business`); the key detail now has a link (`_key_detail_actions` types a
  prose fact of its own - never the ACORD 101 remarks). On `18f6914f`: "Operations description" shows under Key details
  missing; typed there it prints on the 125 and the score returns to 90.
- **Rows a record states are not repeats:** `_GROUNDED_ROW_DETAIL_RESOLVERS` + `_resolve_schedule_row` and
  `_resolve_vehicle_deductible_cell` (17 vehicles kept their $1,000 deductibles on rows B-D); `_dedupe_stamped_
  premises_rows` never folds two rows with different BLDG # (building 2's whole 125 premises row was folded into
  building 1's - same street, no unit). The one-premises-printed-twice case still folds.
- **"Save progress" on box windows:** `issue_registry._r_field(needs=)` declares the box groups a rule requires (Minimum
  Viable COPE: occupancy, construction, building or BPP value; legacy Carrier-Grade COPE: all six); `fixProgress.
  unmetNeeds` + `ResolutionModal` show "Save progress" and the missing groups; a "Save progress" never confirms on-file
  values. Undeclared windows stay "whichever applies".
Not run: the stored-corpus replay (the grounding change can un-blank a repeated schedule value on other sessions -
by design, each kept value is its row's own record). Tests: `backend/tests/test_fixes_before_generation_13oct.py` (32).

### Z4. Adversarial review of Z3 (3 reviewers, read-only) - 11 real findings, fixed the same night
- **Narrative fix was too broad (2 HIGH):** a >5-word non-answer ("I'm not sure, will ask my accountant") became an
  operations description, and a client's denial ("We do not have any operations at all") no longer held (F7). Now only
  the ACORD 101 remarks (`answer_semantics._REMARKS_FACT_KEYS`) are protected - uncertainty only on a short answer,
  N/A and absence only as the whole answer - and `append_producer_narrative` judges the person's NEW words alone
  ("None" / "TBD" add nothing; the composed remarks are never re-read as "none"). Every other fact reads as before.
- **"LOCAL SERVICE" rule was vocabulary-only (2 medium, 1 low):** it dropped "LONG DISTANCE HAULING", "Local retail
  business". Now `normalization.vehicle_use_as_operations` - the description must restate the evidence's own
  `auto_vehicle_use` ("service"), a person's or confirmed (`user_confirmed`) value stands - and ONE ruling feeds the
  merge drop, Tier 2, the stamper (the box prints blank), the fix-window pre-fill (never offered to "Confirm") and the
  questionnaire (`_present_fact_keys` - the client is asked).
- **Rows (3 medium / low):** a client-typed table (no BLDG #) lost building 2 on the 140 with a download hard stop ->
  `_dedupe_stamped_premises_rows(facts=)` never folds two rows their own records state, and compares only LOC / BLDG #s
  a person or document gave ("001" == "1"; gap fill's own numbers are no evidence); the per-vehicle deductible no longer
  reaches ACORD 137 sections; ACORD 130 / 133 print each location once (`_dedupe_repeated_location_rows`: same LOC #
  and street).
- **Save progress (2 HIGH, 1 low):** a COPE card whose legacy TWIN took over was marked Resolved while the 85 cap held
  -> `fixLeftOpen` treats a new item in the card's own cluster as the same unfinished item; the location-table window now
  checks each building row's COPE columns (`premises_cope` `row_needs`, `fixProgress.rowNeedsSummary` - "Construction
  on row 2"); a card stored before `needs` existed takes the code's current declaration (`_with_current_needs`).
- **Navbar (owner, same night):** the header never came back after a refresh - the first scroll was measured from 0
  (a restored position read as a huge downward scroll) and only ONE 40px upward step brought it back (a trackpad's
  small steps never do). `utils/headerAutoHide.js`: first event = starting point, upward runs add up, the top always
  shows it. Tests: `tests/test_header_comes_back_13oct.py`.
- **Narrative card (owner, same night):** with every topic covered the card said only "Improve narrative quality" (the depth check missed "specific operations detail"). The card now names it (`sqs_service.narrative_substance_gaps`), and the narrative window lists everything still missing as tickable options - each adds a sentence starter carrying the phrase its check reads (`narrative_gap_options` -> row `narrative_gaps` -> `resolution.gaps`). On 18f6914f the scope-of-work sentence takes Narrative to 100. Box counts under "Why other boxes are not listed" read "14 boxes:".
- **Narrative, owner-approved three layers (same night):** (1) the window's options ARE the classification - a starter or topic label with no real words after it (or "TBD") is no content: `narrative_reader.strip_unfinished_starters` removes such lines before storing (the narrative door) and scoring (`extraction_service._narrative_remarks_text`), and the window refuses them (`fixProgress.unfinishedStarters`); (2) ONE meaning-based model call per narrative SAVE (`narrative_reader.read_narrative`, improving-ll.md C106) credits a topic or depth item only with a word-for-word quote, stored with the text's hash (`facts["_narrative_reading"]`) and ignored for any other text - live probe on a paraphrased narrative: 17 items credited, each quoted; the model sometimes drops the id prefix, so bare ids are accepted; (3) the keyword pass stays first, the reading only adds; `NARRATIVE_READER=0` (the suite sets it) or a failed call = keywords alone. The fix window holds the page still while it scrolls (body scroll lock + `overscrollBehavior: contain`). Tests: `tests/test_narrative_options_and_reader_13oct.py` (14).
- **Owner, same night, two more:** (a) the page behind the fix window still scrolled - the body lock alone let a wheel over the faded area or past the window's end reach the page; now html + body are held and a native wheel listener (`passive: false`) keeps every wheel in the window - whatever inside can still scroll that way (sideways for the tables) takes it, nothing passes on. (b) "2 to consider" with one card in view: the forms group's count sat beside "Check again" and read as that button's. Each group now shows its count beside its title and the page badge names its parts (`recommendations.considerText`: "1 to raise your score · 1 your forms need").
- **Owner, same night: the "Why other boxes are not listed" breakdown is gone from the pre-form screen** (`BeforeYouGenerate`) - nothing in it can be acted on before generation, it counted boxes nobody can see in system terms, and each line has a home after generation (AI held back / Please verify panels, the Missing list). The counts stay in the dry run's payload (`dropped`); the red "Also needed for a clean download" note stays (actionable).
- **Owner, same night: a white band under the review footer.** Scrolling inside the fix window (its own scroll box) hid AND collapsed the navbar; the window closed and nothing released it - Brent's item 1 class. `Header.jsx` now ignores any scroll inside a window or dialog (`role=dialog`, `aria-modal`, `.modal-overlay`, or any element under a `position: fixed` layer, cached per element); the editor's PDF scroll still hides it. Replay of 18f6914f with the last three key details (41 employees, NAICS 238210, SIC 1731): 94, "Submission Ready" - not 100: Structural 92 (the forms' fill rate, measured at generation), Exposure 95 (auto radius / use - no pre-form box), Property 90 (distance to hydrant / fire department type - asked on the 140 after generation).
**Named, NOT fixed (pre-existing, not on 18f6914f's path):** `premises_cope.derive_package_cope` needs every row to
state the SAME value column (building on one row + BPP on the other clears nothing); the one-building COPE field window
cannot offer the street address its rule also needs; `unmetNeeds` counts an explicit "none" as a value; the re-merge's
legacy branch marks restored driver rows as the producer's (unproven); gap fill could still write a vehicle use into an
operations description box on a package where nobody typed one.
On `18f6914f` after all of it: every form stamps with no wrong blank (125 both buildings + the typed description, 127
drivers and deductibles, 130 one location, 140 both buildings). Tests: `test_fixes_before_generation_13oct.py` (61).

### Z5. SQS without forms - DECIDED (owner + Brent, 13 Oct 2026): the SQS must exist without forms
**Decision:** the SQS is separated from the forms (it exists, and can reach 100, before any form is selected or
generated); after generation the score recalculates. Supersedes the 5 Oct "needs Brent" status of the form-independence
research (memory `sqs-form-independence-research`).
**Where the last points are on `18f6914f`** (replay with every pre-form item answered: 94, "Submission Ready"):
- Structural 92 = Tier 1 100 x 40% + Tier 2 100 x 35% + **Form Fill Rate 71** x 25%. The client's own no-forms
  formula (C3 3.7: Tier 1 53.3 / Tier 2 46.7, `_W_NOFORM_TIER1/2`) is already in `sqs_service` but applies only when no
  forms exist; with it this pillar is 100.
- Exposure 95 = Auto Completeness -5 "No radius of operation" (`coverage_evidence.auto_completeness_gaps`). The auto
  policy's vehicle schedule prints "LOCAL" in the radius / use column ("LOCAL SERVICE") - not read today.
- Property 90 = Location Info 60: `distance_to_hydrant` and `fire_department_type` missing (of locations, value,
  hydrant, fire department, BI limit).
- All three facts are already answerable (`answer_routing` field mode) - the score rows just never name them
  ("Improve property integrity", "Incomplete: Auto Completeness" have no fix route).
**Plan proposed (owner to approve the order):** (1) Structural always on the no-forms formula; the fill rate becomes
the forms' own "Form completeness" number shown beside the SQS after generation; (2) every remaining deduction names
its fact and is asked before forms (radius, hydrant distance, fire department - with option lists), and the radius is
READ where the vehicle schedule prints it; (3) "form X is missing" checks and the C75 generation re-promotion leave the
number, line rules keyed on submission scope (lines requested) instead of selected forms; (4) a build test - every
deduction the scorer can make has a pre-form fix route. With (1) + (2) `18f6914f` reaches 100 before forms. D6 table
before shipping (5 Oct measurement: pre-form fill slice averaged 62, post-generation 95).

### Z6. BUILT (13 Oct 2026, offline, uncommitted): the SQS without forms - and with them - reaches 100 when everything is answered
Owner: "build all the discussed things ... score should reach 100 before and after forms as well if user solves
everything". **Restart the backend before testing** (it runs without `--reload`).
**Proven on the owner's own package `18f6914f`** (read-only replay through the real fix routes, DB blocked, no LLM):
every pre-form item answered = **100** "Submission Ready" (was 94); the last three answers are rows that did not
exist before - Radius of operation +2, Distance to the nearest fire hydrant +1, Fire department type +1. Then the
same answered package with the generated forms of the same documents (stored run `18ecbfa8`, real AI labels):
**with forms 99** (Form Fill Rate 96 - 24 values to verify), **"Confirm all" on the 24 Please verify rows -> 100**
(every form's fill 100). The 50 Missing / 121 AI held back rows are empty boxes and do not move the score.
**Before forms (the pre-form door, `sqs_service.score_package_pre_generation`):**
- Structural is the no-forms formula (Tier 1 53.3 / Tier 2 46.7) - `calculate_package_sqs(form_fill=False)`; the
  per-form results still carry the cards. Lite / Clarity (selected, not generated) keep their own recipe.
- **A form choice is not a gap in the submission.** A check whose only fix is choosing a form (mode `none` + a
  remaining `add_forms` - today only `certificate_requested_but_acord25_missing` fires pre-form: 22 of 94 stored
  packages, each capped at 85 by it with no way to answer it on the review) is deferred before forms
  (`cross_form_validator.is_form_choice` / `defer_form_choices`, applied in `stops_now`, the upload pipeline and the
  pre-form recalc): an advisory marked `form_choice`, out of both stop lists and the Exposure cross penalty. The
  package payload lists them (`form_choices`); the grouped view moves their cards out of Warnings into
  `grouped_issues.form_choices`; Recommendations shows them under "Your forms will need" with "Add ACORD 25" (ticks it
  in Select forms). After generation the rule runs on the generated forms at full force, as before.
- **One row per deduction.** `exposure_deduction_items` / `property_gap_items` list every Exposure / Property
  deduction as {points, fact, label}; the pillar scores ARE their sums (one list, no drift) and the Best Solutions rows
  are built from them (`_gap_rows`: a row per box, one review row for coverage decisions and the cross-form cards).
  "Incomplete: Auto Completeness" / "Improve property integrity" are gone.
- **The radius a rating table prints is read** (`extraction_service.read_vehicle_radius_class`, merge tail): the
  header must name the radius of operation ("Radius of" over "Operation", or "Radius of Operation"), every row printing a
  class must print the same one; stored in the scoring-only `_auto_radius_dec_reading` (the 127 RADIUS box prints miles).
  Measured on 39 distinct stored documents: only the Choice Electric Business Auto Policy prints one (11 sessions, all
  LOCAL); "12:01 AM local time" never matches. A stored session gets it on its next merge - until then the radius row asks.
- Choice lists: radius (Local / Intermediate / Long distance, each reads as a stated radius) and fire department type
  (the words its validator accepts). A probe answers a choice-list question with a choice (`_package_probe_answer`).
**After forms:**
- **Confidence weights stay Brent's 1.00 / 0.85 / 0.50** (he confirmed them 24 Aug). A same-day change of
  `ai_verified` to 1.00 was REVERTED on the owner's instruction after the spec audit (part Z7): "we need to go with
  Brent's one". 100 stays reachable because a found value is now a Please verify row too (reason "Filled by the AI
  from your documents. Confirm it belongs in this box.").
- **Confirm / "Confirm all N"** on the editor's Please verify rows (`NeedsAttentionPanel`, `utils/confirmValues.js`):
  sends each box's own value through the producer-edit door (`/api/update-pdf`), which labels it `producer` and
  re-scores. Every filled box below full weight is confirmable (`needs_attention.CONFIRMABLE_LABELS`: low_confidence,
  ai_verified, and a value under a stale missing_required label); `conflicted` stays Data Consistency's. An unticked
  checkbox ("Off") is no longer a filled box in the fill rate. Those rows' score line reads "Counts in full once you
  confirm it" (it said "No score effect"). The verify tag's hint no longer says "not confirmed in your documents".
- **Proven on the owner's generated `18f6914f`** (read-only snapshot, current code): package 99 (Form Fill Rate 93),
  54 Please verify rows (13 of them found in the documents); all 54 confirmed -> **100**. Missing (36) and AI held
  back (93) are empty boxes and never move the score.
- Every post-generation package score carries `without_forms` {score, tier} (the pre-form recipe, light, never in a
  probe); the editor's Total Package Score and the review page print "Without forms X · With forms Y" and why
  (`utils/scoreWithForms.formsEffect`). A post-form Structural gap that is only the fill reads "Confirm the Please verify
  values on each form (Form Fill Rate N%)".
**D6 (Brent sees these first) - 94 stored packages, recomputed before / after on the same code paths:**
- Before forms: 76 moved, 48 up / 28 down, -2 to +4 (mean +0.7), 9 tier changes (8 up from "Not Ready" 57 to "Major
  Gaps" 60-61 - the ACORD 25 form choice no longer charged; 1 down 60 -> 59). Every DOWN is Structural on a package
  missing Tier 1 / Tier 2 details: the old pre-form fill slice (a recommended form's inventory) was propping it up;
  answering the key details now lifts it. Caps unchanged on all 94 (57 at 85, 34 at 60, 3 none).
- After forms: 0 of 61 moved (re-measured after the `ai_verified` weight went back to Brent's 0.85; at 1.00 it was 7 up by 1).
- With forms vs without forms (after): -4 to +4 - a package can score higher WITH forms (the fill exceeds its weak
  Tier 2) or lower (cross-form checks at full force, unconfirmed AI values).
- D6 panel (`score_delta_probe.py`): 0 of 12 moved.
Tests: `tests/test_sqs_without_forms_13oct.py` (107). Updated as outdated by the owner's decisions:
`test_c3_sqs_integrity` / `test_confidence_score_covers_every_label` (pinned ai_verified < filled) and the
`test_step2_orbin_29sep` recipe guard (its fixture differed only through the fill slice; now claims-made GL) and
`test_narrative_options_and_reader_13oct`'s pin on the forms badge (it now counts open form choices). Suite
13,956 passed / 1 failed (`test_arq_acord125_missing_only`, pre-existing) / 19 skipped; frontend build clean.
**How to verify live:** restart the backend; on `18f6914f` the Recommendations "Raise your score" group lists Radius of
operation, Distance to the nearest fire hydrant and Fire department type; answering them (with the key details) shows
100 before forms. Generate; the editor's Total Package Score says "Without forms 100 · With forms N"; each form's Needs
attention panel has Confirm / "Confirm all" on Please verify rows; confirming them all brings the package to 100.
**Not done / open:** a package whose only remaining Exposure item is a coverage decision ("employees but no workers comp
coverage", "vehicles but no auto coverage") or a payroll / revenue ratio outlier cannot reach 100 by typing - those
rows say so (review); Lite / Clarity keep their old recipe; the 127 RADIUS box still prints only a mileage.

### Z7. Audit against `SQS_Scoring_Specification.docx.pdf` (13 Oct 2026, read-only) - owner's ruling
The spec the client holds (repo root; `v1-20AUG.md` D0: the V1 master plan overrides it where they conflict) was
checked rule by rule against the code. **Matches exactly:** §1-2 weights / N/A rescale / round down / ceiling then
credits / raw kept; Tier 1 list and formula, producer and certificate exemptions; Tier 2 formula; per-form checklists
125 / 126 / 127 / 131 / 28 / 101 / 140-141 and the OCR penalty (-6, cap -30); §3.3 Property in full; §3.5 Umbrella
point for point; §3.6 Narrative formula, x0.75, floor 40, +8, two-signal rule; §4 field-level 6 of 7, identity 4 of 4,
cross-form hard 10 of 11, the 5 "unexplained" rules; §5 cross-form warnings 36 of 37 and all 8 advisories; §6-9
ceiling behaviour, Resolve / Dismiss never scores, a reasonless dismissal earns 0, credits re-capped and retired;
§10 per-form vs package split and the tier ladder. Today's no-fill-before-forms BRINGS the code in line with §3.1
("if no forms have been generated yet, the fill-rate component is dropped") - the recommended forms' fill broke it.
**Divergences, all deliberate:** client V1 (C3 40/35/25, 53.3/46.7, Tier 2 six fields, prior carrier to Loss History,
three Exposure deductions removed and two buckets added, C2 Loss History numbers, SYS-04 narrative gating) and later
owner / Michelle / Brent calls (attested no-loss and new venture = Not Applicable, peril deductibles a warning,
building value hard only with property, no pre-form credits, the narrative reader, expired term hard, the generation /
clean-download blocks, pre-form cross-form rules on the recommended forms, the fill rate over FILLED boxes only, ACORD
25 on the fill rate). **Owner's ruling (13 Oct): "else I think me / Michelle / Brent have discussed and we implemented
as per their requirements" - these stand; do not re-raise them. One change: the `ai_verified` weight goes back to
Brent's 0.85** (part Z6). Correction recorded: 126 / 130 / Excess 131 sit below 100 for their OWN checklist items (GL
form type; owner / officer inclusion; the excess layer's SIR or attachment point), not a missing policy number.
Open: the client's copy of the spec is out of date - a v2 was offered, not written.

### Z8. Review page "x of y handled" (owner, 13 Oct 2026, run `841bb967`; frontend only, no score effect)
Owner: every blocker fixed and the page read "0 of 0 items handled"; with one hard stop left, "0 of 1". The count
read only what was still LISTED, and a fixed item stops firing and leaves its list. Owner: "x of y handled - y were
all the blockers initially and x is how many are handled - and if 0 remaining then remove this."
- y = the items still listed + the page's Resolved rows (dismissed, and fixed items that stopped firing, rebuilt
  from their stored status); x = the Resolved rows (`utils/resolvedIssues.pageProgress`). The Hard Stops /
  Warnings badges and rail lines read the same numbers ("All handled" once a page's blockers are all handled).
- A save that clears OTHER listed blockers - a key-detail link, a "Raise your score" row, another card's fix -
  records them "resolved" (`resolvedIssues.clearedBlockers` with the Save progress rule `fixLeftOpen`, called first
  in `AcordModal.handleIssueResolved`), so they count and move to the Resolved section. A part-fixed item is never
  marked. Items cleared that way BEFORE this change have no record and do not count retroactively.
- Nothing left: the Overview panel shows no "x of y" and no bar; the rail's Overview line reads "All handled".
Tests: `tests/test_review_progress_13oct.py` (4).

### Z9. Recommendations get a Resolved list; the narrative window reads meaning (owner, 13 Oct 2026, run `841bb967`)
**1. Owner: "on the preform screen i need a resolved section similar to hard stops and warnings and also they can be
reopened and score goes back, basically same thing" (the Recommendations page).** Cause: a "Raise your score" /
"Your forms will need" fix went to `resolve-issue` with `issue_id: null`, and the route records what a fix changed
(`issue_fix_undo`) only under an id - so nothing could ever be taken back, and the row simply vanished.
- The fix now carries the row's own id: `rec:score:<pillar>:<asks>` (`recommendations.scoreFixIssue`) or
  `rec:dry:<item id>` (`dryRun.dryRunFixIssue`). Ids and the page live in `utils/resolvedIssues.js`
  (`REC_PAGE = "recommendation"`, `recScoreIssueId` / `recDryIssueId` / `recChoiceIssueId`); they never collide
  with an issue's `iss_...`.
- A save that FIXED its row marks it "resolved" under that page (`AcordModal.markRecommendationFix`): a score row
  is fixed when the package scorer no longer asks for it, read with NOTHING covered (a row now hidden behind a
  warning card asking the same value is still open); a form-check row when a finished check of its form no longer
  lists it - a check still running is judged when it finishes (`pendingRecFixes`). A part-fixed row is never marked,
  and a stale "resolved" on a row still listed is taken off (the Save progress rule). Rules:
  `recommendations.recommendationFixState` / `liveRecommendationIds` / `recommendationResolvedRows`.
- The page shows a collapsed "Resolved (n)" at the bottom (`Recommendations.ResolvedGroup`, both layouts): label
  "Resolved", "Open again" -> the one reopen door (`handleReopenIssue`): the server takes back what the fix
  changed, re-scores, and the row returns to its list with its points. A ticked form choice moves there as "Added";
  "Open again" unticks it. A row that vanished because ANOTHER fix answered it is not listed - it has nothing of its
  own to take back. Pre-existing rows fixed before this change have no record and are not listed.
- Backend: `audit_service.set_issue_status` files `severity: "recommendation"` (`ISSUE_STATUS_PAGES`); a status
  with that page (or a `rec:` id) never shows under Warnings' Resolved list or the editor's Cross-Form Resolved
  list (`resolvedIssues.pageOfStatus(st, iid)`).
- **Replay on `841bb967`'s stored row (read-only, real routes):** narrative row 41 -> 46, Open again -> 41 and the row
  is back; loss-history row 41 -> 44, Open again -> 41 and back. A value changed after the fix refuses the undo
  ("changed since"), as on Hard Stops / Warnings.

**2. Owner: "i pasted the paragraph and only the safety or loss control program is ticked".** A chip ticked only
when its sentence STARTER appeared word for word; the paragraph covered all 20 options by the scorer's own phrases
(and the save takes Narrative to 100). Each option now carries `phrases` (`sqs_service.narrative_gap_options`) -
the exact strings its check reads - and the window ticks an option the typed text covers
(`fixProgress.textForCoverage` / `gapCovered`; unfinished starter lines are ignored, as the server strips them).
A covered option cannot be unticked (unticking only removes a starter line); "Your text covers N of M" / "all of
these" under the chips. The paragraph: 1 of 20 ticked before, 20 of 20 now. Display only - no score moves.
Tests: `tests/test_recommendations_resolved_13oct.py` (11); `test_save_progress_13oct` import pin updated (the TEST
pinned the old import line). Suite 13,971 / 1 / 19 (the known `test_arq_acord125_missing_only`); frontend build clean.
**3. Owner, same day: "add a little drop down icon like warnings and hard stops on recommendations as well".** Every
Recommendations group heading ("Raise your score", "Your forms will need" before and after forms, "Resolved") is now
a fold with the Hard Stops / Warnings triangle (`Recommendations.FoldHead`, `.rec-tri` turned 90 degrees when open).
The working groups start open, Resolved starts closed; a folded "Your forms will need" is hidden, not unmounted, so
the form check keeps polling and re-checking on the ticks. Display only. Test: +1 in
`tests/test_recommendations_resolved_13oct.py` (12).

### Z10. The owner's run `ba7c709d` (13 Oct 2026, fresh upload, 100 before forms, 8 forms generated 13:34 UTC)
Pre-form: 42 (cap 60) -> **100** with the answer sheet (replayed read-only first; the owner's edit log matches it except
contact phone / e-mail and the business start date, which were not typed). After generation: **99** ("Without forms 100
· With forms 99" - the Form Fill Rate slice; Please verify values count 0.85 until confirmed). No hard stops, no
warnings. Generated: 125, 126, 127, 130, 131, 131 (Excess), 137_CO, 140.

**Brent's items graded on the stored forms (read-only):** 4 PASS (two 131s: Amerisure Mutual umbrella $5M over GL /
Auto / EL; Travelers excess $4M over the umbrella), 5 PASS by ACORD's tooltip ("A - annual", no tick; Brent's tick
question open), 6 PASS (only `carrier_website` = Chubb's cyber site; no address as a website; no form prints it), 7 OUR
PART PASS (policies table in "$ X"; 126 GL $16,818; 130 WC $29,278, minimum $465, class premiums; 125 Prior Carrier
GL / Auto / Property 2025; page-1 premiums blank by Brent's renewal rule; 131 and 140 have no own-premium box; 152 / 834
/ 827 not built; the "Other" column waits on Brent), 15 OUR PART PASS (no EBL warning; EBL its own line), 18 PASS (0
hard stops after forms; the COPE card opened the two-building table), 20 PASS (Brent's rule: page-1 carrier blank +
the "carrier receiving this submission" card; Prior Carrier filled), 21 PASS (125 "Other: Excess (Following Form)
Liability"), 22 PASS (owner reached 100 through it), 23 PASS (the table kept the owner's values; 125 / 140 print them),
26 PASS (Exposure 100, no false deductions), 27 BETTER, NOT DONE (download review: 0 hard stops, 19 producer boxes to
fill - was 175 then 47 - but those 19 were never listed before forms: 10 were "left to the documents" and 8 had no fix
route in the dry run; examples: LLC members / managers, revenue per location, inside city limits, own or rent, FT / PT
employees, square feet, area leased, four Yes / No questions), 25 not re-tested on this run. The policies table shows
**11** rows, not Brent's 10: "Crime and Fidelity $500" - the Package Policy prints "CRIME AND FIDELITY COVERAGE PART
$ 500.00", so the row is real (tell Brent; do not remove it).

**UI fixes the same evening (owner, frontend only):** (1) one "Confirm" on a Please verify row put "Confirming..." on
EVERY row and on "Confirm all" - `NeedsAttentionPanel` kept one busy flag; it now tracks the rows being saved by key
(`confirmingKeys`): only they say "Confirming...", the others wait (one save of a form at a time) with their own
label, "Confirm all" says so only when it is the save in flight. (2) The row footer's "Page N" / "Show on form" wrapped
to "Page / 1" and "Show on / form"; they are now two small square-cornered labels (`rowChip`, radius 4, nowrap),
one line each, stacked at the row's right. Tests: `tests/test_verify_rows_13oct.py` (2). Full suite after these: 13,998 / 1 / 19 (the known `test_arq_acord125_missing_only`; the count includes another session's `tests/test_policy_contract_count_13oct.py` and its `pdf_service._policy_contracts` change, made at 18:41 local - after the owner's backend started at 18:16, so `ba7c709d`'s forms predate it).

**WRONG VALUES ON `ba7c709d`'s FORMS - OPEN, NOT FIXED (owner, 13 Oct: "do not fix these but note for future").** Each
was read off the stored forms and checked against the documents. Most carry a Please verify label (low confidence or
"AI verified"), so "Confirm all" would bless them - fix or clear them first.
| # | Form / box | Printed | Why it is wrong | Class |
|---|---|---|---|---|
| W1 | 125 / 130 producer mailing address | 26777 Halsted Rd, Farmington Hills MI 48331-3586 | Amerisure's own head office, read off the dec header as the agency's (the account has no Agency Address) | a carrier's details read as someone else's (5th sighting) |
| W2 | 125 / 130 / both 131s operations description | "Business auto coverage for a fleet of vehicles garaged in Denver, Colorado." | Written by the AI from the auto policy (only "BUSINESS AUTO COVERAGE FORM" is printed); describes a policy, not the business | an insurance description as the business description |
| W3 | 125 contact type | "Accounting" | No document says so - the box's own tooltip example ("e.g. accounting, claims") | tooltip example as an answer |
| W4 | 126 "paid to subcontractors" | $2,626,500 | The WC total payroll | wrong-category amount (meaning gate missed it) |
| W5 | 126 tail coverage Y + explanation | "Item 3. Extended Reporting Period: (A) Additional Period: 1 Year(s)" | The EMPLOYMENT PRACTICES policy's extended reporting period answering a GL question | another policy's text (EPL not seen as foreign to GL) |
| W6 | 126 type of work subcontracted | "about 70% new construction and tenant finish ..." | The narrative's scope-of-work sentence | borrowed sentence |
| W7 | 126 hazard class code | (blank) | **FIXED 13 Oct (Z11). Our bug:** the warning's fix window writes `gl_class_codes_by_location` ("92478"); `pdf_service._gl_hazard_rows` reads only `gl_class_code_schedule` / `gl_class_codes`. The score counts the code, the form never prints it | one truth, two declarations |
| W8 | 127 driver middle initial (all 8 rows) | M, T, L, K, B, A, C, R | Each driver's FIRST initial | invented from the given name |
| W9 | 127 driver 1 mailing city / ZIP | Denver 80221 | The vehicles' garaging ZIP | borrowed address |
| W10 | 131 (umbrella) "anything excluded?" Y + explanation | "EXCLUDED Employee Benefits Liability Each Employee Annual Aggregate" | The umbrella's coverage schedule; the question is about products / work / locations | borrowed sentence |
| W11 | 140 fire district name | "Professional" | The fire department TYPE in the district-name box. **FIXED 13 Oct (Z11)** | wrong-role value |
| W12 | 140 heating / wiring / other improvement years (bldg 1) | 2015 | Copied from the roof year | borrowed value |
| W13 | 125 business start date | "April 2008" (Please verify) | From the producer's own narrative; not wrong, but not a date (the owner skipped the start-date item) | - |
| W14 | 125 / 140 bldg 2 description | "Material and equipment storag" | A letter missing in what was typed in the table | owner's typing |
| W15 | 130 normal anniversary / rating effective date | 01/01/2025 | The EXPIRING term's date on a renewal application for 01/01/2026 | worth a look |
| W16 | 127 additional interest D ("other owner") + Y to "any vehicles not solely owned by the applicant?" | Dana Whitfield | The producer-typed CONTACT name used as a vehicle's other owner; no document prints it | a person's answer borrowed into another role |

**RE-VERIFIED ON CURRENT CODE the same evening (3 read-only checks: the 8 forms re-stamped through the current code -
0 deterministic differences, 23 replay-only differences (stored rows keep no grounding quotes), the other chat's
`_policy_contracts` change a no-op here (policy numbers redacted); the pre-form answer sheet replayed 42 -> 100, dry run
0; and an adversarial pass that tried to refute each verdict). The adversarial pass CORRECTED four of my verdicts:**
| # | Corrected status | Why |
|---|---|---|
| 5 | **OPEN - the owner's decision (F00), not fixed in Brent's terms** | Brent: "neither option would be correct ... careful with A". The 130 prints "A" as a write-in beside the unlabelled Other box; the gate removed the AI's "At Expiration" tick. Decide: tick At Expiration for an annual audit, or keep the code **-> FIXED 13 Oct, part Z11** |
| 18 | **PARTIAL (ours)** | No hard stops after forms - holds. But "answers already given must not be lost" fails: the GL class code (W7) prints nowhere; the hydrant answer prints on building A only (guard REPEATS_ROW_A blanked building B though both are LOC 1 at one address); "Annual revenue for this location" is asked after forms for both rows though total revenue was answered (the one-premises rule counts ROWS, not locations); the fire department type landed in the district-name box (W11) **-> FIXED 13 Oct, part Z11** |
| 20 | **PARTIAL - waits on Brent (F00 Q1)** | Page one follows his 8 Oct rule, but 4 of the 5 carriers (Amerisure Mutual umbrella, Travelers excess, ACE cyber, Federal EPL) appear nowhere on the 125 - all 16 Prior Carrier "Other line" boxes are blank |
| 22 | **PARTIAL (ours)** | Every pre-form recommendation was answerable (42 -> 100), but after forms the editor shows three per-form cards never offered before forms: 125 "carrier receiving this submission", 126 "Specify GL form type: occurrence or claims-made", 130 "owner / officer inclusion / exclusion" **-> FIXED 13 Oct, part Z11** |
Also: 7 holds for our part, plus one box of ours - the excess 131's underlying (umbrella) premium box is blank though the
umbrella dec prints $17,082. 27 "better, not done" holds, and 12 of its 19 boxes are six questions asked twice for two
buildings at one location; the review lists 252 rows in all (19 to fix, 83 to verify, 134 held back, 16 applicant
steps). 15: EBL today sits on the GL side (126 EBL employee count) - Brent wrote WC. Held: 4, 6, 15 (ours), 21, 23, 26.
25 not exercised on this run. Evidence: `<scratchpad>/verify13/`.

### Z11. Items 5 / 18 / 22 / 27 fixed (13 Oct 2026 night, offline, uncommitted) - owner: "fix them all ... for 5 go with your recommendation"

**Proven on the stored run `ba7c709d` (read-only replay, stored AI answers fed back): 6 boxes change, all intended:**
125 `CommercialStructure_AnnualRevenueAmount_A` blank -> 4,500,000; 126 `GeneralLiability_Hazard_ClassCode_A` blank -> 92478 (W7);
130 `Policy_Audit_AtExpirationIndicator_A` blank -> Yes and `Policy_Audit_FrequencyCode_A` "A" -> blank (item 5); 140
`BuildingFireProtection_FireDistrictName_A` "Professional" -> blank (W11); 140 `HydrantDistanceFeetCount_B` blank -> 500 (filled,
the producer's answer). ACORD 125 yellow boxes 13 -> 7 (building 2's revenue / staff / interest / city limits no longer asked
twice). **Pre-form dry run on the same package now lists 8 items** (location 1 staff + sq ft + city limits; location 2 sq ft;
business start date; owner or tenant; LLC member count; and the three form cards - carrier receiving the submission, GL
occurrence / claims-made, WC officer exclusions). **With every one answered before forms: 0 items left, 0 yellow boxes on the 125.**

- **Item 5 (owner: go with the recommendation).** A form that PRINTS the audit tick boxes (130: At expiration / Semi-annual /
  Quarterly / Monthly / Other) ticks the stated term's box and leaves the code box empty; an annual audit = At expiration. A
  form with only the code box (125) keeps "A". Decided by the form's own schema (`pdf_service._form_prints_audit_ticks`,
  `_resolve_audit_tick`, `_AUTHORITATIVE_BLANK_RESOLVERS`). No stated term = every box blank, as before.
- **Item 18 - answers carried to the forms.** (a) W7: a GL class code a person saves (`gl_class_codes_by_location`) prints on
  the 126 hazard grid when no schedule exists (`_gl_code_only_rows`; its other cells stay owned blanks, never "UNMATCHED").
  (b) Hydrant / fire station / fire district are LOCATION-wide (`_LOCATION_WIDE_FIRE_FIELDS`): a later building at the same
  premises prints row A's deterministic value (`_resolve_location_wide_fire_box`) and Guard 2 no longer blanks its copy.
  (c) W11: "fire" is a generic word in `ai_role_guards._KEY_GENERIC_WORDS` - the department's TYPE never fills the district.
- **Item 27 - one premises, several buildings = ONE location** (LOC # is the premises, BLDG # the building).
  `premises_interest.same_premises` / `first_row_of_premises`; `one_premises_row` returns the first row when every row is at
  one premises (was: exactly one row). Then: the business's revenue, full-time and part-time staff twin onto row A
  (`_ONE_PREMISES_TWINS` + FT/PT); a LATER building prints no revenue / staff (counted once - `_LOCATION_ONCE_SUBKEYS`) and
  repeats row A's interest and city limits (`_LOCATION_SHARED_GROUPS`) unless it states its own; the 125 yellow boxes skip
  those on a later building (square feet stays per building); the interest boxes of a later building are twins of
  `premises_interest`, so a post-form answer re-stamps them; the questionnaire asks own-or-rent ONCE for one premises and
  never for a later building of a multi-location package.
  **Five producer-only location-table columns** (`schedule_capture`): Location revenue, Full-time staff, Part-time staff,
  Building sq ft, Inside city limits (Yes / No). The client's copy of the table is unchanged. City limits: "No" = OUTSIDE,
  the reading extraction already gives `inside_city_limits` (owner's call: go with the recommendation) - ACORD's third option
  "Other (unincorporated)" is not offered by the column; a stated Inside answer decides Outside over a stale stored value
  (`pdf_service.city_limits_inside` / `_city_limits_cell`). A True / False cell shows as Yes / No in the table.
  LLC NO. OF MEMBERS AND MANAGERS: `applicant_member_manager_count` registered (`fact_registry`), and
  `arq_service._canonical_key` maps the row-A applicant boxes by name (`_APPLICANT_ROW_A_FACTS`) after the rules loop.
- **Item 22 - a form's own checklist cards before forms** (`form_dry_run.form_card_items`): the per-form scorer runs on the
  dry run's stamped forms; a `missing_field` card is listed only when it is a typed fact the answer door accepts, still
  unanswered, not named by a verified dec entry, not already an item, not a Key detail. The dry run also offers the
  business's own answer for a twinned premises box (`_field_routes` -> `premises_twin_key`), labelled by the fact
  ("Owner or tenant of the premises"). `DRY_RUN_MODEL_VERSION` 1.1.0.
- **Held, not built:** unanswered Y/N questions with no fact behind them (126 ACJ, 127 ABC / AAF, 130 ACD, 125 ABB x2) stay
  "after forms" - answering them before forms needs an answer store for raw boxes (owner's call).
- **D6:** no pre-form score moves (pre-form Structural reads facts only). Post-form fill rate rises slightly on packages
  with one premises / several buildings (newly filled boxes at 1.00) - tell Brent with the rest.
- Tests: `tests/test_items_5_18_22_27_13oct.py` (15); `test_choice_electric_dryrun_7oct` updated (the TEST pinned "only 125 /
  140 items" - cards on other forms are item 22 itself). Full suite 14,013 passed / 1 failed (the known `test_arq_acord125_missing_only`) / 19 skipped.

### Z12. Orbin 22 Sep document re-checked on today's code + items 2 and 4 / 11 changed (14 Oct 2026)

**Re-check (owner: "be honest and check deeply").** Stored Orbin run `bfa8711d` (1 Oct) re-stamped read-only through
current code, plus the 8 Oct page-one rule re-run on its facts (what a fresh upload does today). Results: page-one
CARRIER blank (Brent 8 Oct: two EMC companies) + the "carrier receiving this submission" card (now listed before
forms, Z11); page-one premiums blank (Brent 8 Oct); Prior Carrier prints GL EMC P&C BBC7263-26 $3,954 and Auto EMCC
6E7-40-02---26 $2,991, 07/15/2025-07/15/2026; **the Umbrella $3,418 and Inland Marine $300 expiring premiums print
nowhere on the 125** (the grid has one "Other" column per year - Brent asked); producer phone / e-mail from the
logged-in account (never the dec's agency phone; the dec prints no e-mail at all); GL CODE 91580, 91585; FEIN = the
client's answer. Item 1 confirmed by the owner (a dashboard click opens the package page).

**Item 2 - the score must not read as forms-dependent (owner: "fix point 2").**
- Wording: "Submission Quality Score so far. It can change when forms are generated." -> "Submission Quality Score.
  Scored from your documents and answers - no forms needed." (rail and classic layouts); the classic heading drops
  "so far"; the rail footer reads "Submission Score" before forms (`packageGeneration.scoreHeading`, "Total Package
  Score" after). Marketing page (`PlatformPage.jsx`): "Submission quality, scored without forms", "SQS scores the
  submission itself - from its documents and answers, with or without ACORD forms - and still gates every download",
  "Submission scoring" card; the step tags lose "SQS per-form".
- **Dashboard showed "SQS -" before forms** - it reads a SAVED score and nothing was saved until the first answer.
  `form_routes._remember_pre_form_score` copies the pre-form screen's score into `pre_form_score` (display only:
  `package_sqs`, its history and the delta baseline untouched) on the four pre-form actions that change the package
  (upload, integrity resolve, reclassify, confirm value - never a page view); `session_repository.
  list_sessions_for_user` reads `COALESCE(package_sqs, pre_form_score)`. No score moves.
- Kept on purpose (owner, part O): the per-row "becomes a hard stop" tag beside a warning's own "Open to fix".

**Items 4 / 11 - the proposed term is the next anniversary on or after today (owner: "yes").** Brent retyped Choice
Electric's 01/01/2026 (nine months past) as 01/01/2027-01/01/2028. `extraction_service._route_renewal_dates`: when the
derived next term is more than `_ROLL_FORWARD_AFTER_DAYS` (30) days under way it rolls on to the term after it
(derivation flag `rolled_to_next_anniversary`; still "Please verify - calculated"); a next term that began within 30
days is kept (a renewal a few days late); a next term that has ENDED is still asked (documents two terms old). The
old "next term ends within 30 days -> ask" rule is gone (that case now proposes the upcoming term). Orbin today:
07/15/2027-07/15/2028 (was 07/15/2026-07/15/2027); Choice Electric 01/01/2027-01/01/2028. **Acts at the merge: a
stored package keeps its dates until re-uploaded.**

Tests: `tests/test_orbin_items_2_4_14oct.py` (new); TESTS updated, not code, where they pinned the old wording or the
29 Sep date rule: `test_step2_orbin_29sep`, `test_package_page_1oct`, `test_remaining_items_15sep`,
`test_relationship_preservation_20260815`, `test_line_binding_14sep`. Frontend build clean. Full suite 14,022 passed / 1 failed (the known `test_arq_acord125_missing_only`) / 19 skipped.

**Still open on the Orbin document (for Brent / Michelle):** item 8's Umbrella / Inland Marine premiums (ask Brent -
the Other column); items 5 and 12 declined, Michelle never told; item 14 - do carriers accept the built-in signature;
item 15 lowers some weak packages; item 17's retype check never run; nothing verified on the deployed site with
Michelle's account (set her Contact Phone / Agency Address first).

### Z13. A person's pre-form answers reach their own boxes - and only those (14 Oct 2026, live Render run `b117f010`)

**The live run** (Choice Electric, 6 decs, the Business Auto Policy held back for the item 25 test; 41 -> 100 before forms;
generated 125 / 126 / 127 / 130 / 131 / 131 Excess / 137_CO / 140; 99 with forms, 100 without). Render's merged facts
are under Render's key, so the check was: the session's 19 logged answers (`field_source_audit`) replayed read-only
through the real fix routes on facts rebuilt from the documents' own readings (40 vs the screen's 41 - the account's
agency details), then each answer removed in turn and all 8 forms re-stamped (`<scratchpad>/live14/reach.py`): the
boxes that move are the boxes that answer fills, compared with what Render printed. **Every answer that has a box
reached it** (location table 53 boxes, contact, mailing, revenue, payroll, "Check if none", remarks, hydrant, FEIN,
NAICS, SIC, employees, years, operations). Score-only (no box on these forms): occupancy, period of restoration, fire
department type. The owner confirmed typing FT 90 / PT 100 / 8500 sq ft on both rows (own values print).

**Fixed (each measured):**
1. **ACORD 125 GL CODE ignored the person's code** - `_applicant_gl_codes_from_schedule` read only the rating
   schedule; the "no class codes" card's answer (`gl_class_codes_by_location`) printed on the 126 (W7, Z11) and not
   here. Falls back to `_gl_code_only_rows` (5-digit ISO codes only; a schedule still wins).
2. **A typed auto limit could never print** - stored as bare digits ("$1,000,000" -> "1000000"), which
   `coverage_evidence._labelled_amounts` refuses (to keep policy numbers inside a printing out). A printing that is
   WHOLLY one bare number of 5+ digits is now that amount: the 131's underlying auto CSL prints 1,000,000.
3. **A person's value was evidence for EVERY AI box holding the same text** (`ai_answer_guards._judge`) - the
   hydrant "500" stood as miles to the fire station, the auto limit as the 137's UM limits, the roof year as heating /
   wiring / other years, a contact's name as the contact TYPE. Now only for the question they answered
   (`person_value_facts`, `box_question_facts` = `pdf_service.source_fact_for_field` + the schedule column + the
   one-premises twin + `_FACT_FALLBACKS`). Round 9's own case holds (a person's year built / protection class on
   building 2).
4. **`_COPE_ATTRIBUTE_BOXES` had no exposure DISTANCE and no TOWING** - the 140's four exposure distances "500" and
   the 137's towing "1,000,000" were checked by nothing. Added (exposure wording only; towing wording).

**Measured.** `b117f010`: only the intended boxes move (125 GL CODE 92478, 131 auto CSL 1,000,000; refused: 140 fire
station x2, exposure distances x4, 137 UM x3, towing). `ba7c709d`: + 125 GL CODE, - three improvement years 2015
(W12). **611 stored packages** (99 Render-keyed skipped): 19 stored AI values now refused, **all junk** (towing
1,000,000 x4 / $0, exposure "0" x6, improvement years from the roof year / year built, fire station 500, fire
department type as the district, a contact's name as the contact type x2); **0 correct values lost**. **94 stored
packages: 0 score changes** before or after forms. Tests: `tests/test_answers_reach_forms_14oct.py`.

**"Your forms will need" (owner asked whether we had decided to remove it): no.** A 4-agent check of every chat and
doc: the owner approved the group on 7 Oct ("okay built it like this the way you suggested"), asked on 8 Oct for MORE
before forms (cross-form issues), and on 13 Oct removed only its "Why other boxes are not listed" breakdown. The six
items are Brent #22 ("addressable prior to (and independently of) the forms") and the owner's Z11 "fix them all".

**Still open on `b117f010` (AI values, noted, not fixed):** 137 "Other symbol" codes 1-7; 126 other deductible $5,000
(property), "type of work subcontracted" from the narrative, products row = the business description; 130 rating /
anniversary dates 01/01/2025 (W15), "Item 3A State: CO", the contact as accounting / claims / inspection contact; 131
underlying description "The Schedule of Underlying Insurance is part of Policy No."; 125 contact type "Accounting"
(W3); 127 garaging with no vehicles (auto policy not yet uploaded). ~~Next live step: add the Business Auto Policy
(item 25) - it re-stamps the forms in place, so the fixes show on this package without regenerating.~~ **WRONG
(corrected in Z14):** a document added after forms re-stamps only boxes whose FACTS change
(`session_documents.restamp_forms` -> `_restamp_changed_boxes`); these were CODE changes, so the forms generated before
the deploy keep their old boxes. Adding the auto policy still tests item 25 / 8; the Z13 fixes show on forms generated
on the new build.

### Z14. The Z13 deploy checked + an adversarial review of Z13 (14 Oct 2026, offline after the deploy of `2e4dd44`)

**Deploy:** `2e4dd44` ("fixed bugs") carries Z13 AND the four same-night corrections the first review found:
`state_auto_grid.box_facts` (a person's UM / med pay answer stays on the 138 / 137), `_human_liability_reading` reads the
envelope's `answer_text` first (split limits typed in words stay split), `UnderlyingPolicy_` boxes are never the auto
limit cell (the 131 OTHER row), a bare amount with cents is a premium, not a limit. Full suite on it: 14,037 / 1 / 19.
**`b117f010` was not touched after the deploy** - and Z13's "add the auto policy and the fixes show" was WRONG (see the
Z13 correction): forms generated before a deploy keep their boxes until they are generated again.

**The second reviewer (FIX 1, the GL code) - four real defects, all fixed (each reproduced first):**
1. **An answer given AFTER generation reached neither the 125 GL CODE nor the 126 grid** - the card closed, the score
   counted the code, both forms stayed blank. Every answer door re-stamps through `_restamp_canonical_into_forms`,
   which reaches only boxes whose canonical key IS the fact; these two are derived by resolvers. New
   `arq_service._restamp_boxes_the_answer_decides` runs `_restamp_changed_boxes` (the confirm path's door since 5 Oct)
   after the canonical re-stamp in `apply_producer_answer_to_session` (cards, resolve-issue, a held client answer) and
   `apply_arq_answers_to_session`: generation's engine, box by box, before and after; a person's box never moves.
   `_restamp_changed_boxes` now builds one facts view per form and runs under the stamp's grid memo
   (`_engine_memo`): the 125's prior-carrier grid was rebuilt for every box - 4.1 s -> 1.8 s warm on `b117f010`'s 8
   forms; on 8 stored packages x 2 answer changes the new door moved exactly the same boxes to the same values as
   the deployed one (16 of 16, 209 boxes on the wider 25-package run, 44 of 44), mean 6.4 s -> 3.9 s. **And a re-stamp
   now prints only what GENERATION's post-fill guards allow** - the engine answers
   box by box, generation then runs `_enforce_post_fill_guards` over the form; replaying ten common answers on
   `b117f010`'s stored forms showed an employee count landing on the 131's named-insured rows B-F, which the row
   de-dup guard blanks. The moves now pass the same guards (a refused one prints blank). Same replay, what the new
   pass moves beyond the canonical one, every box correct: mailing address line + ZIP on 125 / 130 (they kept the old
   address), gross receipts on 131 / 131 Excess, years in business on 130, the Excess 131's effective date, the 125
   GL CODE; contact, FEIN, auto limit, operations: nothing extra.
2. **A ZIP / payroll / year / SIC / NAICS in the card's free text printed as the GL code** ("Electrical contracting at
   4800 Pecos St, Denver CO 80221" -> 125 GL CODE 80221; the producer questionnaire asks this fact as "what type of work
   at each location?"). `sqs_service.gl_code_tokens_in_text`: an ISO code (five digits) that STANDS as a code - leading
   an item after a location / code label, or the one number of a short item - never after a state, a money word or "$",
   never a street number. `_gl_code_only_rows` (125 and 126 alike) reads it. **Presence is unchanged on purpose**
   (`_gl_code_tokens`: any number, a description answers the question) - no score moves by this.
3. **An AI-read `applicant_gl_class_code` beat the person's answer on the 125** while the 126 printed the answer
   (two GL codes for one applicant): `_person_gl_codes` - a person's code wins unless the stated code is a person's too.
4. **WC classes a combined package files under GL printed as 126 hazards** and the 125 stopped at the first non-ISO
   code before reaching the person's answer. `_gl_row_is_another_lines`: a schedule row is another line's when its code
   is witnessed only by another line (the score's own rule, `_gl_codes_owned_elsewhere`) AND is not five digits;
   applied in `_gl_hazard_rows`, the 125 box and `_gl_schedule_evidence` (a grid left with no GL row is an owned blank,
   the 11 Sep rule, never gap fill reaching for the WC table). The by-location home counts as GL evidence only
   through an ISO code it gives AS a code (`_gl_code_only_rows(keep_elsewhere=True)`): a row holding a NAICS code
   ("531120"), a location or the word "GL" no longer leaves the grid open to gap fill; a real GL code another line's
   table repeats still does (first cut blanked six May / June kits whose GL code extraction copied into
   `wc_class_codes` - their stored grids printed nothing either way, narrowed anyway so nothing else moves). **The shape half came from the measurement:** the first
   cut (shape-blind) blanked real GL codes on three stored kits (`1dcc1a9d`, `cda0d536`, `26412d4b`) whose extraction
   had copied the GL hazard row INTO `wc_class_codes`; a five-digit code another line's table repeats is that misfile.
Also: Guard 2e (127 rating-box borrows) now knows a person's GL code (`_gl_code_only_rows`), not only the schedule's.

**Measured (read-only, deployed tree vs this one):** 560 stored packages with forms (99 Render-keyed skipped), the
125 GL CODE and every 126 hazard box through the engine: **24 boxes in 2 packages move, both intended** - `5a0c962f`'s
126 no longer prints a NAICS code (531120) as the GL class code, `65dfbf52`'s grid (by-location code "GL") is an
owned blank instead of open to gap fill (its stored grid printed nothing). The 125 GL CODE moves on none.
**Score corpus:** 94 stored packages, 0 changes (before forms, after forms, without forms).

**Found, NOT changed (D6 / owner calls):**
- ACORD 126 per-form Exposure reads only `gl_class_codes_by_location` and gives +10 only to a LIST: a full rating
  schedule scores 60, a typed answer 85, a list 100 (per-form panel and covers; the package is unaffected, D29). Two
  lines through `gl_class_codes_present` - moves 126 per-form scores UP.
- The score's "no class codes" warning (85 cap) fires on packages whose documents state the applicant's GL code
  (`applicant_gl_class_code`) and on the three kits above (the score's other-line rule is shape-blind). Counted on 926
  stored packages: a stated applicant code - 18 state one, the warning fires on **0**; the misfiled GL row - **3** (the kits
  `26412d4b`, `1dcc1a9d`, `cda0d536`). Low priority.
- A document added after a person's one-amount auto answer prints split limits: the person's CSL stands (the one-door
  order, 5 Oct). Brent: should it raise a "New document says" conflict instead?
- On a two-family auto package (symbols 1 + 41) a person's UM answer now prints on the Business Auto page while the
  grid leaves that section to the document - owner's call if it should stay document-only.
- Pre-existing, low: a compound split answer stores only its first number (`words_to_number`), which the umbrella
  checks read; a box EDIT of the 125 GL CODE does not carry to the 126 (`propagate_fact_edits` reaches canonical boxes
  only); the legacy (receipt-less) clear does not clear derived boxes.

**The owner's local backend runs the production crons against the SHARED database.** `main.py`: `SCHEDULER_ENABLED`
defaults to TRUE off production, and the Mac's uvicorn (no --reload, up since 00:00) holds the advisory lock. At 03:00
IST `run_retention_cleanup` deleted every session untouched for 180+ days (policy `SESSION_RETENTION_DAYS`; 51 with
forms tonight, all April / Render-keyed; every recent test session intact). 03:30 audit retention (365 d) and 04:00
facts retention (180 d, same cutoff) do nothing tonight; **09:00 payment lifecycle and 10:00 questionnaire reminder
e-mails would also run from the Mac.** The CLAUDE.md line "retention ... run NOWHERE" was wrong. Owner's call:
`SCHEDULER_ENABLED=false` in the local `.env`.

**Live check (after this round is deployed):** on `b117f010`, BEFORE adding a document (a fix's undo receipt refuses
once the document set changes) - package page -> the "GL coverage detected but no class codes" row under Resolved ->
Open again (the 126 row clears, the warning returns) -> Open to fix -> 92478 -> Save: ACORD 125 GL CODE and 126 hazard
row A both print 92478 labelled producer (fix 1, on the existing forms). Then add the Business Auto Policy (item 25 / 8).
Z13 / Z14's other fixes show on a NEW package (same 6 PDFs): 125 GL CODE 92478, 131 auto CSL 1,000,000, 140 fire
station / exposure distances blank, 137 UM / towing blank. Tests: `tests/test_gl_code_answers_14oct.py` (65); `test_form_findings_11sep_round3` updated (its by-location fixture
held a dummy code "1" - the TEST was outdated: the home now needs a GL code). Suite 14,102 / 1 / 19.

### Z15. Live run `f83757cf` (14 Oct 2026, Z14 deployed; 6 decs, auto held back; 41 -> 100 before forms, 99 / 100 after)

Graded box by box from the stored row. Verified on the forms: 125 GL CODE and 126 row A 92478; 131 auto CSL
1,000,000; Excess 131 Travelers $4M / umbrella 131 Amerisure $5M; 140 fire station, exposure distances and improvement
years blank (hydrant 500 on both buildings); 137 UM / towing blank; proposed term 01/01/2027-01/01/2028 (Please
verify); page-one premiums and carrier blank + the receiving-carrier card (Brent 8 Oct); 125 lines incl. Other: EBL and
Excess; one location, two buildings; no "COMMERCIAL AUTO"; Exposure 100. Three changes (uncommitted until deployed):
1. **"Your forms will need" is gone before forms (owner: "this section does not increase score so why show it before
   even generating the forms").** `utils/recommendations.buildRecommendations` lists and counts nothing about forms
   before generation (dry run, per-form cards, form choices); `Recommendations.jsx` renders the group only once forms
   exist. Reverses the 7 Oct pre-form group: Brent #22's per-form cards (125 receiving carrier, 126 GL form type, 130
   officers) now appear after forms. A deferred form choice ("Add ACORD 25") surfaces after generation. TESTS updated
   (not code): `test_recommendations_section_7oct`, `test_recommendations_resolved_13oct`,
   `test_sqs_without_forms_13oct`, `test_narrative_options_and_reader_13oct`. `BeforeYouGenerate.jsx` is now unused.
2. **Field QA compared a location row's own cells with package facts** ("Number of full time employees shows 90 but
   the source value is 100. Re-confirm"; the premises' "Office and electrical shop" vs the business description).
   `pdf_service.authoritative_expected_value` (the one door) now asks the schedule resolver: a table cell's owner is
   its row. Proven on the live forms (2 false rows gone, nothing else); the page-one carrier / question 4 callers are
   untouched (no table cell). Tests: `tests/test_field_qa_table_rows_14oct.py`.
3. **The 125 prior-carrier grid lost GL and Property** - this run's Package Policy rows came back with no carrier (the
   last run's had "AMERISURE INSURANCE COMPANY"); the header carrier only bound through policy numbers and these decs
   are redacted. `extraction_service.assign_document_carrier_to_rows` (per-document pre-pass in `merge_facts`): a document that is one
   carrier's own paperwork, whose `carrier_name` a carrier-labelled index entry corroborates and which names no other
   carrier, gives it to its own rows that print none (never over a carrier, a NAIC or a person's value). Measured on
   all 1,704 stored documents: 4 touched (12 rows), all that document's only carrier. `f83757cf` now prints GL /
   Property prior rows (Amerisure, 01/01/2025); `b117f010` unchanged. Acts at the merge: adding the 7th PDF re-merges
   the package. Tests: `tests/test_document_carrier_rows_14oct.py`.
Suite 14,150 / 1 / 19. **Download review, read with the owner:** after these deploy, 12 "to fix" are real (LLC
members, own / rent, leased area x2, 126 code-only row's 6 cells, 131 hazardous materials x2); signatures (12) and
"AI held back" (58, refusals working) stay by design. **Open, ours:** CE 25 (add the auto policy after this deploy),
Orbin 17 (retype check), G2 client path live; tell Michelle 5 / 12.

### F00. FINAL - only the questions that BLOCK the remaining test items (owner, 8 Oct night)
Owner's answers: forms 152 / 834 / 827 - **leave for now, correct the 17 forms we have**; questions 9-17 below
(excess 131 underlying, 130 audit tick, website, risk state, expired-dec dates, vehicle use, follow-form credit,
"AI verified", location hints) are **the owner's to answer, not Brent's**. **Owner: every question and every fix is
a RULE FOR ANY DEC PAGE / PACKAGE - Choice Electric is only the example** (each fix is measured over every stored
document, as rounds 8-10 were). Sent to Brent as general rules (five questions; the generic wording is in the chat of
8 Oct night):
1. #7 - where the expiring premiums of lines with no prior-grid column go (one "Other" per year; ACORD 101 for the
   rest?) and whether EPLI (no premium) gets a page-one OTHER row.
2. #15 - EBL with GL (126 / 131 / 160) rather than WC?
3. #18 / #22 / #27 - show the checks that become hard stops at generation as hard stops BEFORE forms?
4. #18 / #26 / #27 - occupancy type and Period of Restoration (no document states them): hard stop + 60 cap until
   typed, or a warning that asks? Can "Extended Period of Indemnity 540 days" stand in for Period of Restoration?
   Should they also cost Exposure points?
5. ~~#12 / #13 / #18 fixed items~~ - SETTLED BY THE OWNER and built (part V); not sent to Brent.

**The message as finalised with the owner (9 Oct) - four questions, plain words, rules for every package:**
1. *Expiring premiums that don't fit.* Prior Carrier Information has GL, Auto, Property and one "Other" column per
   year; page 1 has two "Other" line rows. With more lines than that: how do we choose which line takes "Other",
   where do the rest go, and do we still list a policy whose premium is redacted or blank (carrier and dates)?
2. *Employee Benefits Liability.* ACORD prints it on the liability forms (126, 131, 160), never the 130 - for every
   client, where should EBL go?
3. *Hard stops that appear only after forms.* Some checks run only once a form exists and show before that as
   warnings marked "becomes a hard stop" (his earlier rule). When we already know the forms, how should these show
   before generation?
4. *Required values a dec usually doesn't print* (occupancy, Period of Restoration, roof / year built per building).
   How strict should a missing one be (hard stop at 60 until entered, or a warning that asks)? Can a related printed
   value stand in (e.g. Extended Period of Indemnity for Period of Restoration)? Should it also cost Exposure points?

### F0. BATCH TO SEND BRENT - 8 Oct night (superseded by F00; part U closed the two-carrier,
### page-one premium, landlord and SIC / NAICS questions)
Needed to finish his test items: (1) #7 which line takes the prior-carrier grid's one "Other" column per year, the
rest to ACORD 101? EPLI row on page one? (2) #7 forms 152 / 834 / 827 - add or out of V1? (3) #15 EBL with GL
(126 / 131 / 160), not the 130? (4) #18 / #22 / #27 show future hard stops as hard before forms (reverses C75)?
(5) #18 / #26 / #27 occupancy, Minimum Viable COPE, Period of Restoration - cap / block, or request for information?
(6) #18 per-building year / roof / protection class - per building or per location; block or warn? (7) #12 / #13 /
#18 fixed items: "Resolved" tag in place or a "Reviewed" group; remove Resolve? (8) #26 should property gaps also
deduct in Exposure? Confirmations: (9) #4 excess 131 also lists GL / Auto / EL? (10) #5 annual audit = "At
Expiration" tick? (11) #6 www.chubb.com/cyber is Chubb's site - did he mean the insured's? Also affecting his
package: (12) risk state from carrier letterheads - blank and ask? (13) an ended dec's proposed term - roll to the
next anniversary or ask? (14) per-vehicle USE when a vehicle's own line prints none? (15) follow-form credit from the
Excess heading? (16) "AI verified" label? (17) location-table sample hints? Heads-up: extraction varies run to run.
No Brent input needed (ours): #2, #16, #17, #19 Cancel, #24, #18's modal bug, #26's labels, #27's to-do count -
all built 9-10 Oct (parts W and X), each waiting for a live look.

### F. Decisions needed (Brent / owner) before building
1. Two ACORD 131s (one per layer) - forms keyed by form_id today; an architecture change.
2. 130 audit: annual = "At Expiration" tick? Which policy's audit goes on 125 page one?
3. EBL: ACORD prints it on 126 / 131 / 160, never the 130 - does "tucks under WC" stand?
4. WC premium in the 125 POLICY PREMIUM? EPLI row with a blank premium? Excess as its own OTHER row (Brent: yes).
5. Proposed term on an expired dec: roll forward to the first anniversary after today, or ask?
6. Pre-form: show stops at the severity generation will give them (reverses part of C75)?
7. Resolved items: keep listed as "Resolved" (#12) or tuck under "Reviewed" (#18)? Remove "Resolve" (#13)?
8. Per-building year / roof / protection class: one answer for all buildings or ask per building; hard block or warning?
9. Forms 152 / 834 / 827 are outside our 17.
10. #10 reverses the owner's 27 Sep restoration of the blocks; #19 Cancel is an exception to "every exit saves";
    #25 reverses the 1 Oct lock.

**ADDED 8 Oct 2026 - ASK THESE WITH THE TEN ABOVE, IN ONE GO (owner's instruction). Nothing below is built.**

11. **A carrier's address is being read as the insured's state of operations** (part P - the one with a drafted
    message to Brent already written). On a Colorado contractor we recorded MI, PA, AZ and IN - Amerisure's head
    office, Chubb's Scranton claims office, a Phoenix office, Federal Insurance. **The question for Brent:** when
    nothing in the documents states the risk state except carrier letterheads, do we leave it BLANK and ask, or
    keep asserting a guess? We lean blank (a wrong state builds the wrong state's rules into the submission), but
    it turns a populated field into a new "missing" item on some accounts - a D6 number.
12. **Three gates no document can satisfy** - occupancy type, Minimum Viable COPE, and Business Income's Period of
    Restoration (these decs print "EXTENDED PERIOD OF INDEMNITY 540 DAYS" and a 72-hour BI deductible instead).
    Each caps the score and no uploaded document can clear it. **Ask as ONE question:** should a gate a producer
    cannot satisfy from the documents cap the score at all, or become a request for information?
13. **Where cross-form issues belong before forms exist** (part O). Three options, (a) recommended: add them to
    "Your forms will need" only; (b) move them out of Warnings entirely - they leave the warning count and the 85
    ceiling display; (c) stop demoting for forms already RECOMMENDED - closest to "fixable before must not block
    after", but it REVERSES C75, which was Brent's own call, and moves scores.
14. **The location table's placeholders.** Five plausible values sit in empty COPE cells - year built 1998, roof
    Metal, roof year 2015, protection class 3, sprinkler 100, plus a Houston TX address on a Colorado risk. They
    are grey ghost text, but they invite a copied wrong value. Neutral hints instead?
15. **"AI verified" means only "this string appears somewhere in the documents"** - which is how an ISO copyright
    line ("Copyright, Insurance Services Office, Inc., 1999") printed as a building's year built on ACORD 140,
    with eight such boxes labelled `ai_verified`. **Ask:** should that label be renamed, or the bar raised so a
    value must be found in a context that MEANS the field?
16. **Extraction is not repeatable, and Brent should know.** The same Package Policy PDF gave CO on one run and MI
    on the next; `wc_payroll` was extracted one run and not the next; the WC class table was present one run and
    null the next. Facts the score depends on are now DERIVED where we can (round 6), but this is a standing
    property of the pipeline he should hear from us rather than discover.

### G. Proposed order (nothing started - owner's go)
- **P0 (wrong values / data loss / trust):** commit the 5 Oct `_fv` + human-table fixes; version check; location table
  (columns, merge-on-save, LOC/BLDG, garaging never a premises, `locations` derived); 140 guards; edit propagation;
  `stops_now()` door; digit rule + ISO form regex; WC-codes-as-GL; per-policy facts out of the picker (premium, audit,
  website, schedule sentence) + Excess as its own record; audit menus; the D-list wrong values; docs facts encryption.
- **P1 (pre-form parity):** Best Solutions + dry-run stamp before forms; "-N pts" Exposure; download count = actions only.
- **P2 (UI asks):** 2, 9c, 10, 12, 13, 16, 17, 19 Cancel, 24, 7a.
- **Bigger, after decisions:** 131 per layer, inline policy edit / add line, upload after generation.
- Every fix: replay `ca93ed8f` offline (per-document facts are readable) + FR125 312/312 + Orbin stored sessions + the
  D6 panel; tell Brent where scores move (most go UP: false cards and false location warnings disappear).

### I. FIX ROUND DONE 6 Oct evening (offline, NOT committed, NOT deployed) - the "no Brent approval" list + the 127-only cap bug
Four parallel workstreams, each replayed on the client's own session `ca93ed8f`, then integrated and gated together.

**Gates (final combined code):** full suite **12,543 passed / 1 failed / 19 skipped** (the 1 = known
`test_arq_acord125_missing_only`); FR125 r2t6 / r2t7 / r2t8 **312 of 312, 0 wrong, 0 made up** (test 8's 3 made-up
question-4 numbers are now blank); D6 panel **2 of 12 moved, both +1** (property deductible basis), live Orbin 71 -> 71;
frontend builds, lint clean.

**What changed - by area (notes per change: `<scratchpad>/ce/agents/{prop,pol,c125,scoring}/CHANGES.md`):**
- **Locations (14, 23, 26, 27):** building labels fill LOC # / BLDG # (street blank; buildings at one premises share its
  LOC #); a vehicle garaging address is never a premises; location table gets LOC #, BLDG #, Construction, Year built,
  Building value, BPP value (CSV template follows; header synonyms); every save MERGES by a hidden row id and never drops
  a field the table has no column for (`schedule_capture.merge_saved_rows`, `arq_service._write_schedule_rows`); the loose
  `locations` list is derived from the table (`extraction_service.sync_location_list`, also after a re-run restores the
  table); re-stamp only changed columns, never over a producer box; ACORD 140 guards keep a row's own stated values,
  anchor rows on LOC/BLDG/street, read "LIMIT"/"DEDUCTIBLE" before "Prem #", clear a subject with its refused amount;
  every guard removal records a reason. Session: 1 premises / 2 buildings, building 2 NON-COMBUSTIBLE / $421,714 /
  $75,000 stock printed, 140 hard blocks 6 -> 0 (no DRAFT), no false location warnings.
- **Stops / propagation / scoring (18, 26, 27, owner's 127-only bug):** new `services/stops_now.py` = the ONE stops door
  for generation, per-form scoring, worker and pre-form (stored stop lists are display copies only - an AST test pins
  it); the pipeline evaluates stops on the facts it will STORE; a hard legacy stop is never hidden behind a demoted twin;
  a form edit propagates its fact to every other form (`arq_service.propagate_fact_edits`, person-typed boxes kept);
  stated radius classes ("LOCAL") count; one GL class-code reader (`sqs_service.gl_class_codes_present`, both homes,
  minus codes another line owns). Session: no stale occupancy stop, generation not capped at 60, Exposure 65 -> 75,
  date mismatches 7 -> 0. The BI / Period of Restoration rule no longer caps a 127-only package (5 Oct scope + new test).
- **Policies / Data Consistency / extraction (4, 5, 6, 7, 8, 9, 15):** no digit = not a policy number; form numbers with
  a second letter group rejected; the Excess is its own line record (`lob_canon.umbrella_layer`, record id
  `umbrella~excess`), confirmations are layer-scoped; per-policy facts compared only inside one policy; package scalars
  no longer from the first-uploaded dec (`_settle_policy_level_scalars`); audit menus are not answers, a bare "A" is never
  decoded; merge-time corrections (website shape, dividend plan, NCCI-as-NAIC, pending/prior date, EPI, insured's state);
  WC codes leave the GL schedule; GL limits read from the umbrella's underlying schedule; singular EBL recognised.
  Session: 11 records (Excess / Travelers and Umbrella / Amerisure Mutual apart; EBL its own), Data Consistency
  conflicts 5 -> 0, umbrella_limit $5M, identical results with the upload order reversed.
- **Stamped values (20, 21 + section D):** Federal in the 125 carrier list; prior-carrier rows without numbers (GL
  $16,818, Auto, Property $6,275); one 125 row per policy - OTHER A = EBL $425, OTHER B = Excess $10,692; POLICY PREMIUM
  = the printed rows; payment plan code-or-blank (dividend plan only in the 130's dividend box); 131 Employee Benefits
  takes only EBL evidence; 130 claim count / prior mod / NCCI risk id / $6.50 / floor counts / years refused; 127
  "111 Denver"; 137 symbol junk and Med Pay $1M (now blank - no med-pay fact exists); 126 wind/hail deductible.

**Tests changed, and why (the TEST was out of date, not the code):** `test_stop_visibility_c75` (3 source pins moved
with the rule into `stops_now.py`), `test_remaining_items_15sep::test_a_form_number_is_never_a_policy` and
`test_estimated_total_sanity::test_one_implementation_of_the_line_sum` (rules this round reverses on purpose). Integrator
fix: the new GL reader had counted a classification-only schedule row as a code - restored HEAD's rule.
New tests: `test_choice_electric_{loc,pol,forms,flow}_6oct.py` (49 + 110 + 65 + ~30) with fixtures from `ca93ed8f`.

**Still open (named, not hidden):**
1. Building 2's year / roof / protection class are the producer's one answer copied by gap fill; roof "Composition" is
   an AI guess (owner call: ask per building?).
2. Vehicle and driver tables still rebuild from their columns on save (same data-loss class as the location table).
3. ACORD 137 Med Pay prints blank (no extracted med-pay limit); $75,000 stock prints without its subject name.
4. Other GL class-code readers (3 cross-form rules, per-form checklist, industry match) not yet on the one reader.
5. Client questionnaire still built from the stored stop list; the score trace does not yet name each Exposure cause.
6. LOC # / BLDG # values still travel to the client page (producer-only columns hidden, values not stripped).
7. Prompt recommendations only (no prompt changed): define `locations`, `carrier_website`, `payment_plan`,
   `state_of_operations`; unticked audit menus; per-vehicle radius; `limit` on `coverage_lines`; med-pay limit.
8. Brent decisions in section F are untouched (two 131s, 130 audit tick, EBL placement, WC in the total, EPLI row,
   past proposed date, pre-form stop severity, per-building COPE).

**D6 for Brent:** scores go UP on multi-policy packages (false conflict cards and false location warnings gone),
property packages +1; DOWN where a GL package has no GL class schedule (warning now true) and where boxes that printed
wrong values now ship blank (fill rate). **To see any of this live: commit, push and deploy, then reload every tab.**

### J. ROUND 3 - the six bigger builds (7 Oct; offline, NOT committed, NOT deployed; final full gate pending)
Owner: "build these with full accuracy and do not leave anything behind". Four parallel builds (LAYERS, UPLOAD,
POLICIES, DRYRUN), each designed in writing first, tested on Brent's own package, then integrated by the main session.
Notes per build: `<scratchpad>/ce/r3/<BUILD>/CHANGES.md`; requests: `.../REQUESTS.md`.

**Shared rule first - form instances (`services/form_instances.py`, JS twin `utils/formInstances.js`).** A second
copy of an ACORD form is "<base>__<key>" ("ACORD_131__excess"). Anything that loads a file or keys a rule uses
`base_form_id()`; anything that stores or shows uses the instance id (`instance_label()` / `formLabel()`,
`file_stem()` / `fileStem()`); stamping, scoring and QA use `facts_for_form()`. Every single-copy package is
byte-identical.

| # | Built | How (doors to know) | Evidence on Brent's package |
|---|---|---|---|
| 4 | One ACORD 131 per umbrella-family LAYER | `services/umbrella_layers.py` (what a tower is, layer order, each layer's own document values in `_umbrella_layer_docs`), the ACORD_131 overlay, `pdf_service._resolve_upper_layer_box`; gap fill split: insured boxes shared, each copy's own-policy boxes in its own group over its own documents (improving-ll.md **C102**, +~4 calls per tower) | Plain 131: Amerisure Mutual / $5M / SIR 0 / Umbrella; `ACORD_131__excess`: Travelers / $4M / no SIR / Excess, underlying = the Amerisure Mutual $5M umbrella. Upload order irrelevant. 10,042 regression tests passed (2 failures, neither from LAYERS) |
| 25 | Add documents to a package, before or after forms; reclassify / exclude / supporting-only after forms | `routes/session_documents_routes.py` (`POST /api/session/{id}/documents`, `/documents/add-form`), ONE door `services/session_documents.remerge_package` (only new files are OCR'd / extracted; stored per-document facts re-merged; human answers, tables and policy lines carried; integrity checked; one write), `services/upload_intake.py` (the upload checks, shared), `_finalize_pipeline(keep_forms, retract_document_keys, persist)`; frontend `AddDocumentsPanel.jsx`, `DocumentChangeConfirm.jsx` | Door vs REAL generation (every box, premiums included): package added last 62 moved / 0 missed / 0 wrong; WC added last 34 / 0 / 0; Excess excluded 6 / 0 / 0. Exclude after forms now really removes that document's values |
| 9 | Edit / add / remove policy lines in "Policies in this submission" | `services/policy_lines.py` (`_producer_policy_lines` store, edits keyed by record with anchors, added lines as their own records, applied inside `_finalize_pipeline` and the editor confirm), `routes/policy_line_routes.py`, frontend `review/PoliciesTable.jsx` (both layouts); added umbrella / excess lines take `limit_each_occurrence`, `limit_aggregate`, `sir` | Correcting the auto policy after forms moved exactly the 127 header, 125 question 4 / Business Auto premium / POLICY PREMIUM (58,385 -> 61,485) / prior-grid auto row, the 131 underlying auto row; a person-typed box kept |
| 7 | The 130's WC premiums | `services/wc_premiums.py` (read at merge into `_wc_premiums`, never computed), `pdf_service.nonfillable_box_value` (THE premium-box door generation and every re-stamp use) | 130 prints total $29,278, minimum $465, class premiums $37,600 / $597 / $180; over 1,359 boxes on 3 packages the only output change is those 130 boxes |
| 27 | "Before you generate" | `services/form_dry_run.py` (the real stamper with `allow_llm=False`, then the download review's own `run_field_qa` / `needs_attention`; keeps only what a person must supply with a proven fix route; cached, off the event loop, 3 s wait then "pending"), `routes/dry_run_routes.py`, frontend `BeforeYouGenerate.jsx` | 8 items, 2 blocking: building 2 year / roof / protection class and building 1 roof - the boxes behind Brent's DRAFT, BEFORE generation; the download gate flags exactly the same blocking boxes; filling the table empties the list |
| 18 | COPE card opens the location table with 2+ buildings | `services/premises_cope.py`, `issue_registry` card routing (`facts=`), four producer-only columns (roof material, roof year, protection class, sprinkler %) bound to live 140 / 160 boxes | One-building packages: byte-identical cards |

**Integration (main session) - each found by checking the builds against each other:**
- Premium boxes after a document change or an editor confirmation: `_restamp_changed_boxes` skips non-fillable boxes,
  so the upload door and `confirm_underwriting_value_in_editor` now also run `policy_lines.restamp_nonfillable_boxes`,
  each side judged against its OWN documents' text (`raw_text_before`). The earlier "0 missed" comparison skipped
  every non-fillable box; against real generation the door is now exact (above).
- The editor confirmation asks the engine with generation's own input (facts + flags + the package's forms) - a
  flag-driven box was mistaken for an edited one.
- `pdf_service._value_in_raw_text`: a NUMBER is "in the documents" only as the same number (token-aligned, no
  thousands continuation, cents and trailing decimal zeros allowed, no word-subset fallback). It accepted "$3,100"
  inside "23,100.00", and "100" anywhere vouched for "$3,100". 692 verification tests pass.
- The client's copy of a table carries no producer-only VALUES (`schedule_capture.client_rows`).
- ACORD 125 prior-carrier grid built once per stamp (`_with_grid_memo`): 10-11 s -> 1.0 s per 125 stamp on Choice
  Electric (109 grid builds -> 1), FR125 4-6 s -> 0.8 s; 0 differences over 17 forms x 3 real packages.
- `test_dec_index_purge` records the dry run (pre-generation only); CSV header synonyms for the new columns.
- Tests: `test_form_instances_7oct.py`, `test_choice_electric_{layers,upload,policies,dryrun,integration}_7oct.py`.

**LAYERS follow-ups - done:** a copy stays bound to ITS layer (`facts["_umbrella_layer_bindings"]`, written with
`generated_forms` through `form_instances.binding_update`, carried through every re-merge by `carry_bindings`): on
the real package, uploading a lower $2M excess after generation leaves `ACORD_131__excess` on Travelers $4M and
offers the new layer as `ACORD_131__excess-2`; a producer-added layer prints its own limit / aggregate / SIR; EPIC
and Vertafore payloads carry `base_form_id` beside `form_id`.

**FINAL GATE (7 Oct, nothing else editing):**
- Full suite (`-p no:randomly`, from `backend/`): **12,821 passed / 1 failed / 19 skipped** - the 1 is the known
  `test_arq_acord125_missing_only`.
- FR125 r2t6 / r2t7 / r2t8: **312 of 312 each, 0 wrong, 0 made up**.
- D6 panel vs production (HEAD 7b681f4): 2 of 12 moved, both +1 (the 6 Oct property deductible-basis fix); live
  Orbin 71 -> 71. Round 3 moved no panel score (no panel package is a tower or uses the new features).
- Documents door vs REAL generation on Brent's package, every box incl. premiums: 62 / 34 / 6 moved, 0 missed,
  0 wrong; the door now runs in ~8 s (was ~43 s before the grid memo).
- Grid memo: 0 differences over 17 forms x 3 real packages.
- Frontend: builds clean; eslint 0 errors, 74 warnings (unchanged).

**Residual, named (not fixed):** the layer bindings are one fact written whole, so two add-forms of two different
131 copies clicked at the same moment in one session could keep only one binding (that copy then falls back to
position - today's behaviour).

**Owner / Brent decisions this round adds:** excess 131 underlying (umbrella only, or GL / Auto / EL too); excess
131 score (SIR / attachment rule costs it 20 + 25 points); exclude BEFORE forms keeps unique values; no new AI fill
after an upload (deterministic only, by design); dry-run default form set (Required tier) and the operations
description box (no pre-form route); `_build_line_records` lets one numbered contract absorb another carrier's
unnumbered rows (pre-existing, moves Data Consistency results if changed).

### K. ROUND 4 - the owner's localhost run of 7 Oct (session `9acec031`) and what it found (offline, NOT committed)
The owner re-ran Brent's 7 decs on localhost (round 3 code). The pre-form screen found four wrong things a FRESH extraction
produced that Brent's stored run did not, plus the owner's design asks. Five parallel builds (DATA, CARDS, POLICIES, RECS,
NEWDOC; notes `<scratchpad>/ce/r4/<BUILD>/CHANGES.md`), integrated by the main session.

| Found / asked | Root cause | Fix (door) |
|---|---|---|
| GL limits $5,000,000 (the umbrella's own) | The umbrella dec's model reading put its own "Each Occurrence $5,000,000" in all five GL facts; nothing competed; the underlying-schedule reader only fills blanks | `extraction_service._drop_another_lines_limits_on_one_line_document`: a one-line-family document never witnesses another line's limit equal to its own. Live: GL $1M / $2M / $2M / $1M from the umbrella's schedule of underlying |
| Entity type "Corporation" for an LLC (Brent's stored 125 ticked it too - unreported) | Menu read as a value ("Corporation X Limited Liability Company"); Travelers' menu has no LLC | `normalization.settle_document_entity_type`: a menu counts only as the ticked option; a legal-form designator in the insured's own name (LLC, Inc, Corp, LP, LLP, PLLC) overrides an incompatible reading |
| "Entity type differs ... confirm in Data Consistency" with Data Consistency saying "nothing to confirm" | The picker dropped "LLC" as not a legal option; the integrity check counted it | `underwriting_consistency._declared_domain_check` accepts what the fact's own comparison equates; guard test: a warning pointing at Data Consistency always has a card there |
| "Multiple carriers referenced" on every multi-carrier package | Counted distinct carriers | `submission_integrity._carrier_line_claims`: only two carriers on the SAME line / layer |
| COPE pop-up on 2 buildings showed building 1's values as package boxes | Round 3 kept "occupancy-only" cards in field mode | `premises_cope.route_cope_resolution`: 2+ rows -> always the table; also `sqs_service._cap_stop_items` (editor) |
| Card reasons: 160 cited the Cyber limit, 127 "1,000,000", 140 building 1 only | Reason facts not line-checked; raw money; one scalar | `form_service._FORM_EVIDENCE_LINES` + `fact_line_family`; currency canonicaliser; "Building values: $1,220,270 (2 buildings)" |
| Vehicle / driver tables wiped non-column fields on save (class code, territory on 17 vehicles) | Only `property_locations` merged on save | `schedule_capture.MERGE_ON_SAVE` + VIN / licence / name+DOB identities (unique on both sides) |
| Brent #10 | - | Blocks removed; `policy_lines.record_limits` -> Limit column; sort + Group by carrier |
| Brent #22 / #27, owner's design | - | Recommendations section (`review_recommendations.with_fix_routes`, `utils/recommendations.js`, `Recommendations.jsx`) |
| Owner: a document added after forms must be read like the others | Only rule boxes re-stamped | `session_documents.run_new_document_fill` (improving-ll.md **C103**): the shared gap fill on the NEW document(s) only, every generation guard; blank -> filled; a differing AI box -> a "New document says X" choice (side panel + download review), never an overwrite; person / rule boxes never; background, locks document changes, policy edits and editor confirms while it runs; `NEW_DOCUMENT_AI_FILL=0` kill switch |
| Owner: tell the producer what an added document changed; a way back | - | Pre-upload note; result box (boxes moved per form, AI fill outcome, "New on the review page: N hard stops, N warnings, N Data Consistency items" + Review them); editor sidebar "Back to review" with an open-items count |

Integrator fixes: a client's untouched table holding producer-only values read as "changed" (`client_supplied_schedule`,
the row-change review - compared as the client saw them); a building row with no address added no `locations` entry
(`location_list_from_rows` fallback); the pre-form fast path after a resolve now carries the fix windows. Tests changed
because the owner reversed what they pinned: `test_v1_c1d` (scoped rows), `test_choice_electric_dryrun_7oct` (occupancy-only
field card), `test_coverage_presence_14sep` (money spelling), `test_v1_c1_canonical_facts` (an "LLC" name is not a real
entity divergence). New tests: `test_choice_electric_{data,cards,policies_table}_7oct.py`, `test_recommendations_section_7oct.py`,
`test_new_document_fill_7oct.py`, +6 in `test_choice_electric_integration_7oct.py`.

**FINAL GATE (round 4):** full suite **13,001 passed / 1 failed / 19 skipped** (the 1 = known `test_arq_acord125_missing_only`;
`test_retest_fixes_1oct` counted 2 side-panel sections and now 3 - the TEST was out of date); FR125 r2t6 / r2t7 / r2t8
**312 of 312, 0 wrong, 0 made up**; D6 panel 2 of 12 moved, both +1 (unchanged from round 2), live Orbin 71 -> 71; frontend
builds; eslint 0 errors / 74 warnings (unchanged). Live docs of `9acec031` re-merged: GL $1,000,000 / $2,000,000, entity
Limited Liability Company, umbrella $5,000,000, integrity high with no reasons.

**Residual, named:** a "Raise your score" row opened right after an EDITOR response shows a typed box without its choice
list until the next package-page load; vehicle / driver rows with no VIN / licence and a stale tab opened before a
reorder can still match by position; `shared_gap_fill` failing internally reports "done, 0 boxes" not "failed";
the one-line-limit rule stands down if extraction lists an umbrella's underlying rows as its own coverage rows.

### L. ROUND 5 - the owner's live run with the REAL AI fill (session `b248c194`, 7-8 Oct; offline, NOT committed)
Every earlier gate replayed with `allow_llm=False`, so the AI gap fill's answers were never in a test. The live run put 15
classes of wrong values on the forms (`<scratchpad>/ce/r5/PROBLEMS.md`). Owner: "fix them for all the random data, not
this one submission". Built and measured on a replay corpus: 691 stored sessions dumped read-only; a harness
(`<scratchpad>/ce/r5/harness/`) re-stamps 225 of them (393 forms) with their STORED AI answers fed back through the
guards, old tree (frozen copy) vs new, every changed box with a reason code.

| Class | Door (new / changed) |
|---|---|
| Policy number = label + the dec's own form number ("COMMERCIAL AUTO CA DS 70 01 09 06"), dates, amounts, "ACCOUNT ...", truncated "CGL-2024-" | `normalization.policy_number_refusal` (one door, reason codes); `pdf_service._not_a_contract_number` at 17 resolvers; a policy with its own declarations stays a policy without a number (`_policy_has_own_declarations`) |
| AI non-answers: "SEE SCHEDULE", the insured's name as operations, "service" / question echoes, form titles, option-list dumps, rating-class wording as operations | `services/ai_answer_guards.py` (`AI_*` codes) |
| Wrong-role AI values: another fact's value ("FRAME" as alarm), unverifiable small counts (floor "1"), premium-line amounts as deductibles / limits, binder dates without a binder | `services/ai_role_guards.py` (stands down when the dec index is purged) |
| A value only another policy's document prints (excess retention $10,000 from Cyber / EPLI); coverage sections the documents do not carry (140 Spoilage / Blanket, 131 Employee Benefits) - now never asked (C104); 131 underlying OTHER rows from the umbrella's own schedule | `services/scoped_evidence.py` |
| 140 premises grid: each schedule row its own subject / limit / coinsurance / deductible ($5,000, not the $500 default "Exceptions: SEE SCHEDULE"); Stock and BI rows; AI copies of other buildings refused | `services/property_coverages.py` + 140 resolvers |
| City boxes with the state / ZIP glued on ("Denver, Co", "Tx 75201"); a state code as a tax code | display / address split |
| The same hard stop listed twice after generation; pre-form warnings that generation promotes are tagged "Becomes a hard stop when ACORD 140 is generated" (display only, C75 unchanged) | `stops_now` / `issue_registry` / both review layouts |

**FINAL GATE (8 Oct):** suite **13,497 passed / 1 failed / 19 skipped** (the known `test_arq_acord125_missing_only`);
FR125 r2t6 / r2t7 / r2t8 **312 of 312, 0 wrong, 0 made up**; D6 panel unchanged (2 of 12 +1, Orbin 71); frontend builds,
eslint 0 errors / 74 warnings; corpus replay **302 boxes changed over 50 sessions, every one reviewed: junk removed or a
wrong value corrected, 0 correct values lost** (170 AI removals, 60 deterministic removals, 36 additions - split addresses,
the 140 Stock / BI rows, the auto term on ca93ed8f's 131 - 35 deterministic corrections, 1 AI correction). Tests changed
because they pinned a reversed rule: the 131 "every carried line is underlying" pins (2), the seating-capacity fixture
(the index is always present at generation), the Yes/No vocabulary pin (a non-category list). New tests:
`test_round5_{identifiers,ai_answer_guards,ai_role_guards,scoped_evidence,property_grid,stops}_7oct.py`.
**Open / owner:** ACORD 125 Q4 lists only numbered policies (a redacted auto policy is not listed - same as ca93ed8f today);
with no umbrella schedule a liquor policy may still take a 131 OTHER row; one-word "Roofing"-style descriptions; AI "See
schedule" refused in amount boxes; the insured's contact copied into the 130's other contact boxes (74 sessions); the
"State Act - " prefix on the deterministic 130 class description; stored sessions get the full 140 grid / clean line
records only after a re-merge. Notes per fix: `<scratchpad>/ce/r5/FX-*/CHANGES.md`.

### M. ROUND 6 - the owner's live run of 8 Oct (session `b4d18e8e`) - 3 defects found and FIXED, 8 points live-verified

**The run.** The same seven Choice Electric decs, re-uploaded on current code (every round-5 module in place -
backend started 7 Oct 23:48, newest source 7 Oct 23:48, nothing changed mid-run), 8 forms generated, **score 38,
capped at 60, "Not Ready"**. Brent's own `ca93ed8f` scored 80. Most of that gap is round 5 correctly removing junk;
three of the points were defects, all now fixed.

**What the decs actually are, and why some "missing" values are right.** The seven PDFs are REDACTED:
`NAMEDINSURED:` and `MAILINGADDRESS:` print as bare labels with no value, and the property dec says
"Location, Construction And Occupancy: **SEE SCHEDULE**" while the schedule prints construction but never
occupancy. So `mailing_address`, `fein`, `operations_description` and `occupancy_type` being empty is HONEST.
**But the 60 cap is held by "Minimum Viable COPE incomplete - missing: occupancy type", which no document in
this package can satisfy** - the unsatisfiable-gate class, open for the owner.

| # | Defect | Door (new / changed) |
|---|---|---|
| 1 | **Adding a document crashed its AI fill.** `launch_new_document_fill` was a SYNC `def` handed to a Starlette `BackgroundTask`, so it ran in an AnyIO worker thread with no event loop; `asyncio.ensure_future` raised `RuntimeError: There is no current event loop` and the coroutine was dropped (`coroutine 'run_new_document_fill' was never awaited`). `document_ai_fill` then sat on `{"state":"running"}` for ever and the screen kept saying "Reading <file> into your forms...". C103's logic was fine; the seam was not | `session_documents.launch_new_document_fill` is now `async def`. AST sweep of `services/` + `routes/`: it was the ONLY instance, and `test_no_sync_function_schedules_an_asyncio_task` fails the build on the shape |
| 2 | **A document naming a DIFFERENT insured handed the applicant its identity.** A Harborline Plumbing & Mechanical dec added to Choice Electric: the upload WARNED ("These documents name a different insured"), the producer answered "they belong to this insured", and the merge took **18 applicant facts** wholesale - DBA, mailing and physical address, FEIN, all three contacts, revenue, NAICS, SIC, employee counts, operations, occupancy, year built, years in business, business start date. Package SQS **38 -> 60 (raw 38 -> 80)** on another company's data; ACORD 186 printed a **Washington** contractor licence and Harborline's own policy number under "Choice Electric LLC". A cap is not a scope | **`services/insured_scope.py`** - an applicant-scoped fact is dropped only when EVERY document stating it names a different company. One applicant document stating it keeps it; a person's answer is never touched; `applicant_name` itself is left to the picker; a document naming no insured is never judged. Called from the merge tail, BEFORE the WC derivations and the flag re-derivation |
| 3 | **`wc_payroll` was left to the model while `wc_payroll_by_state` was derived.** The scorer reads the SCALAR (`wc_payroll` / `total_payroll`), so a complete class table produced a false "Workers Comp detected but payroll is missing" and a 12-point Exposure deduction. Measured on two runs of the IDENTICAL documents: 7 Oct the model emitted it (Exposure 45), 8 Oct it did not (Exposure 33) - with `wc_payroll_by_state` holding `{'CO': '$2,626,500'}` and the ACORD 130 printing all three class payrolls | `derive_wc_facts_from_class_rows` now derives the scalar from the SAME complete-table evidence, one rule one moment. Same three guards: a stated or human value stands, our own value is recomputed, rows that stop supporting it retire it |

**Also fixed (owner, same run):** "Back to review" ran a save plus a session re-read with no busy state - it looked
dead and people clicked twice; it now disables, spins and says "Opening review...". It also clears the editor's
body scroll lock explicitly instead of waiting for the `step` effect - that lock surviving into the review render is
what leaves the page unscrollable with the footer stranded over empty space.

**MEASURED (D6).** 104 stored sessions replayed read-only:

| | Sessions |
|---|---|
| Identity scoped away | **2** - `b4d18e8e` (18 facts, Harborline) and `59cacc39` (3 facts: Orbin Contracting's FEIN / year built / construction type were **Meridian Fabrication Inc**'s, from a control dec) |
| `wc_payroll` newly derived | **1** - `b4d18e8e`, Exposure 53 -> 65 |

**Zero false positives.** Both identity hits are genuine two-insured packages; every other package is untouched,
because the module cannot act unless a document actually names a different company.
On `b4d18e8e`: `wc_payroll` None -> **$2,626,500**, Exposure **53 -> 65**, the payroll warning gone.

Tests: `tests/test_choice_electric_fixes_8oct.py` (22). Targeted suites 351 passed. Frontend eslint 0 errors
(26 pre-existing warnings), production build clean.

**Open from this run, NOT fixed (ranked):**
- **Ten invented values on the ACORD 140**, eight of them labelled `ai_verified`: `BuiltYear_A` = 2001 and
  `BuiltYear_B` = **1999** - and 1999 appears in the documents ONLY as "Copyright, Insurance Services Office,
  Inc., 1999", so an ISO copyright year is printing as the year a building was built; `ProtectionClassCode_A/B` = 4;
  `Alarm_ProtectionDescription_A` = "sprinklers"; five `BuildingImprovement_*Year_A` = 2025. The words "protection
  class", "year built", "sprinkler", "alarm", "heating", "plumbing", "fire protection" appear in NO document.
  `ai_verified` means only "this string occurs somewhere", which is how a copyright year passed.
- **No Commercial Auto row in the policy table** (item 9's remaining half). The table itself is RIGHT - 10 rows,
  the nine auto coverage parts filtered out of 20 raw `coverage_lines` entries, the Excess its own row. But
  `lob_canon.canon_line` reads **"Auto Medical Payments" as the auto LINE** instead of a coverage part, and that
  record has no premium (redacted) and no policy number, so `policy_line_records`' de-dup drops it - and no other
  row names the auto line. **Not fixed at speed on purpose:** `_row_evidence` (behind `evidenced_line_families` /
  `carried_lines_of_business`) reads `canon_line` ONLY, so reclassifying that phrase as a part could drop the auto
  family on a package where it is the only auto row and un-recommend the ACORD 127. The right fix is "a document
  evidencing coverage PARTS of a family contributes a LINE record for it", measured across the corpus first.
  Two of those part strings also leak onto ACORD 137_CO as `Vehicle_OtherCoverageDescription_C/D`.
- **ACORD 126 is 12 boxes of 255** - no GL premium (Brent's item 7 wanted $16,818 on the 126), no class codes.
- **126 says GL is claims-made; 131 says it is not** - two forms in one package contradicting each other.
- **131 asserts follow-form** ("Umbrella follows form over the underlying coverages") - a guessed value, against
  the standing never-guess rule (client Q3).
- **131 (Excess) ticks BOTH `ClaimsMadeIndicator` and `OccurrenceIndicator`** - mutually exclusive.
- **125 premium total 41,567** is the exact sum of the seven rows it prints but excludes GL $16,818 and WC $29,278
  (real package ~$87,500); currency format is inconsistent ($37,600 on the 130, 2,431 on the 125 - Brent asked for "$ X").
- **125 applicant address prints a ZIP and a state with no street or city**; producer address = "Office: Phoenix AZ"
  (a carrier office line as the agency's address).
- **`percent_subcontracted` = "estimated annual cost $310,000 of subcontracted work"** reads as a percentage out
  of range - a cost in a percent fact.
- **Three different hard-stop counts on one screen**: 1 in the stored `hard_stops`, "4 need attention" in the
  sidebar, "3 hard stops remaining" in the block - and that block is headed "Since client answers" when the change
  came from adding a document.
- **Extraction is not repeatable**: 8 facts differ between the 7 Oct and 8 Oct runs of identical files.

**Standing lesson.** Two guards fired on the cross-insured document (the upload warning and the integrity hard
stop) and the data was still merged. **A warning is not a scope and a cap is not a block** - if a value must not be
used, something has to refuse it, not price it.

### O. ROUND 7 - the owner's second run of 8 Oct (`805049a7`, 6 documents) and the "becomes a hard stop" reversal

**The run.** The same Choice Electric decs **minus the Business Auto Policy** (deliberate: one document held back so
adding it after generation is a clean before/after). 6 docs, score 29, 1 hard stop, 11 warnings, 7 recommendations.

**Three things confirmed, each from the code and not the screen:**

1. **The location table is HONEST and the ACORD 140 is not - on the same package.** Every empty cell in the COPE
   table is a value no document states: street / city / state / ZIP (the decs are redacted), what happens here
   ("Location, Construction And Occupancy: SEE SCHEDULE", and the schedule never says), year built, roof material,
   roof year, protection class, sprinkler %. What the rows DO carry is real: BLDG 001 / 002, FRAME and
   NON-COMBUSTIBLE - LIGHT STEEL, $798,556 / $421,714, BPP $73,008 both. Everything else the owner saw is the
   column PLACEHOLDER (`schedule_capture.py`: "789 Commerce Dr", "Houston", "TX", "77001", "1998", "Metal",
   "2015", "3", "100"). **So on identical data the table shows blanks while round 6's ACORD 140 printed invented
   values** (built year 2001 / 1999, protection class 4, "sprinklers", five 2025 improvement years). The defect is
   the gap fill on the form, not the table. Two searches of mine returned FALSE POSITIVES worth recording: a street
   address matched **Amerisure's own** "26777 HALSTED ROAD, FARMINGTON HILLS, MI" in the dec header, and a roof
   material matched the form title "LIMITATIONS ON COVERAGE FOR ROOF SURFACING".
   **Owner's call, open:** five plausible placeholders sitting in empty COPE cells invite a copied wrong value.
2. **"Two hard stops earlier, one now" is correct.** Pre-form, C75 demotes BOTH cross-form hard stops (Minimum
   Viable COPE and Business Income / Period of Restoration) to warnings, leaving only the field-level COPE stop.
   Generation puts them back. The duplicate COPE wording is one problem said twice and the grouped view folds it.
3. **Period of Restoration will be a hard stop nobody can clear.** These decs print "EXTENDED PERIOD OF INDEMNITY
   540 DAYS" and a 72-hour BI deductible, never a period of restoration - a THIRD unsatisfiable gate beside
   occupancy type and the COPE one. All three wait on the owner / Brent.

**CHANGED (owner, 8 Oct): the "becomes a hard stop" sentences are gone from both layouts.**
Brent's item 18 ASKED why hard stops appeared after generation; he did not ask for the answer to be printed on
screen. Removed: "N hard stops now, M more when forms are generated" (the Overview tile) and "1 warning becomes a
hard stop when forms are generated." (the Hard Stops section). **Kept: the per-row `becomes_hard_tag`**, which sits
beside that row's own "Open to fix" - the one place a person can act on it. `generationStops.js` keeps its helpers
and their unit tests; `test_no_layout_announces_a_future_hard_stop` now pins that no layout renders the sentences
(the old pin asserted the opposite and was updated - the TEST was wrong, not the code).

**STILL OPEN - the owner's point 3, NOT built, and why.** *"Cross form issues should be in the recommendation
section before forms are generated, and once forms are generated in the left SQS panel under sections like cross
form validation or hard stops."* The placement is right and the principle behind it is right - **an item you could
have fixed before generating must not first become blocking after**. It is not built because it collides with a
rule `utils/recommendations.js` states in its own header: *"ONE TO-DO, ONE PLACE. An item whose whole fix is
already offered by a Hard Stop or Warning card on this screen is not repeated here."* A demoted cross-form issue
IS such a card today (in Warnings, with its fix). Three ways out, owner to choose:
  * **(a)** add the promoting rows to the **"Your forms will need"** group only - semantically exact ("what your
    forms will need"), a different question from "what is wrong now", so the dedupe rule survives. Smallest change,
    no score movement. **Recommended.**
  * **(b)** move them out of Warnings into Recommendations entirely - one place, but they leave the warning count
    and the 85 ceiling display, which is a score-surface change.
  * **(c)** stop demoting for forms that are already RECOMMENDED (ACORD 140 is in this package's list), so the stop
    is hard now and fixable now. Closest to the principle, but it REVERSES C75 (Brent's own ruling) and moves
    scores - a D6 decision with a before/after table, his to make.
After generation they already appear in the review page's Hard Stops section AND the editor's red HARD STOPS block,
so the post-form half of the ask is satisfied today.

### P. A CARRIER'S ADDRESS IS BEING READ AS THE INSURED'S STATE - found 8 Oct, HELD for Brent (nothing built)

**Found by the owner's own test**, not by us: he re-ran Choice Electric with the Business Auto Policy held back and
noticed **ACORD 137_CO was no longer recommended**. It was not the missing document, and it was not a recommender
change - the recommender was fed a wrong state.

**`state_of_operations` is being taken off carrier letterheads.** Per-document facts, written by extraction:

| Document | 7-doc run (`b4d18e8e`) | 6-doc run (`805049a7`) | Whose address that is |
|---|---|---|---|
| Package Policy | **CO** | **MI** | Amerisure, 26777 Halsted Road, Farmington Hills MI |
| Workers Compensation | CO | *(table not extracted)* | - |
| Business Auto | CO | *(held back)* | - |
| Cyber | - | **PA** | Chubb claims, P.O. Box 5105 Scranton PA |
| Excess Umbrella | - | **AZ** | the "OFFICE: PHOENIX AZ" line (also seen as `producer_address`, round 6) |
| EPLI | - | **IN** | Federal Insurance |

Choice Electric is a **Colorado** contractor. In the 7-doc run three documents said CO (garaging DENVER CO 80221,
the WC class rows CO/CO/CO, the package dec) and outvoted the noise. Remove the auto policy and lose the WC table
to extraction variance, and the merge settles on **PA** -> `_supported_state_forms` returns `[]` -> no 137_CO, and
ACORD 28 is lost too.

**Two defects, not one:**
1. **A carrier's / claims administrator's address is read as the insured's state.** Fourth sighting of one class
   on 8 Oct, after Harborline's identity becoming the applicant's (round 6), `producer_address` = "Office: Phoenix
   AZ", and a premises-address search matching Amerisure's own head office.
2. **It is not repeatable.** The SAME Package Policy PDF gave **CO** on one run and **MI** on the next. Same code,
   same file. (Third nondeterminism sighting: `wc_payroll` 7 vs 8 Oct, `wc_class_codes` present then null, now this.)

**Blast radius beyond the form list:** `state_of_operations` feeds `_infer_primary_state` /
`_supported_state_forms` AND the state-specific surfaces (`state_restricted_boxes`, `state_auto_grid`). A wrong
state does not only drop a form - it builds state-specific content on the wrong basis. And it fails ASSERTIVELY:
it printed "PA" rather than leaving the field open.

**NOT BUILT - owner's decision 8 Oct: hold it and put it to Brent.** The proposed rule, for when it is approved:
take the state only from evidence that belongs to the INSURED - garaging addresses, WC class-row states,
`wc_payroll_by_state` keys, the premises schedule, the applicant's own mailing / physical address - and when none
of those corroborate the extracted value, **drop it and ask** rather than assert it. Same shape as
`_gate_inferred_payroll_period` (H1-K), and the same shape as `insured_scope` landed the same day.
**Why it needs Brent:** on a package whose only state signal is noise the field goes BLANK, so a currently
populated value becomes a new "missing" item. That is the blank-over-wrong rule, which is the owner's standing
preference, but it is a D6 number Brent should see before it ships.

**The owner's standing instruction recorded with it:** *form recommendations are working - do not change them
unless explicitly asked.* Verified: neither 8 Oct change touched the recommender. `insured_scope` was a NO-OP on
`805049a7` (no document names a different insured - five decs are redacted and state no insured at all, the sixth
says CHOICE ELECTRIC LLC), and `derive_wc_facts_from_class_rows` had no table to read. The per-document `state_of_
operations` values are written by extraction, which was not touched.

### Q. ROUND 8 - the generation of `805049a7` (8 Oct evening): five defects fixed, the forms graded box by box

**The run.** The six-document package (Business Auto Policy held back), the occupancy answer applied pre-form,
7 forms generated: 131, 131 (Excess), 125, 126, 130, 140, 127. **Package 41, "Not Ready", one hard stop - Period of
Restoration, exactly as predicted in part O** (the decs print "EXTENDED PERIOD OF INDEMNITY 540 DAYS" and a 72-hour
BI deductible). Backend started 12:50 with every round-6 fix loaded (sources 12:17), so nothing here is a stale
server. Box-by-box report: `<scratchpad>/ce12/forms_report.txt`.

| # | Defect (found on this run) | Root cause | Fix |
|---|---|---|---|
| 1 | **"Back to review" still left no navbar and a blank band at the bottom** (item 1, the owner's second report) | The app header's auto-hide is driven by WHICHEVER element scrolls. Scrolling the PDF inside the editor hid it AND collapsed its space (`body.app-header-collapsed`, negative margin). Leaving the editor removed that element, so nothing could release the state: the review page opens at the top, where no upward scroll can bring the header back, and the review layout's heights still subtracted the header's 83 px - the blank band. A refresh reset the component. Round 6's fix (body scroll lock, scroll to top) was real but not this | `Header.jsx` listens for `app-header:reset` and shows itself; `AcordModal`'s step effect (every step change) and `goBackToReview` dispatch it |
| 2 | **The Workers Comp dec was read in part** - 75 of 201 schema keys, no flags: no class table, no state, no X-mod, no dec index. **Same 10,829-char text that extracted all three class rows on three earlier runs** | **CORRECTED the same night by a probe (one real call): the reply was NOT cut off.** The model finished (`finish_reason=stop`, 3,768 tokens, 0 reasoning) with ONE stray `{` four closers from the end. The salvage, built for truncation, could not parse it and returned nothing; `_safe_json_parse` fell through to an LLM repair fed only the first 3,000 characters - whose valid answer was the 75-key fragment, cached as the whole document. The model repeats the slip on this document, so it failed the same way on every run since | `utils.json_salvage` rewinds past a slip until the text parses (live reply: **203 facts, 42 flags, all three class rows, state CO**); `extract_facts` retries a partial result once and never caches one (improving-ll.md **C105**). This one defect explains the 130's empty rating rows, "WC payroll is missing" (-12 Exposure), and the state settling on carrier letterheads so **137_CO and ACORD 28 dropped off** - part P's finding has a second cause |
| 3 | **ACORD 125 POLICY PREMIUM $66,709 while its printed rows add to $62,547; two cyber coverage parts printed as lines of business** ("Cyber Incident Response Team", "Electronic, Social And Printed Media Liability") | Extraction pinned the cyber policy's ONE premium ($4,162, ACE American) on eight coverage parts. The policies table folds them into one Cyber row (`_line_records`, correct); the 125's OTHER rows used a second reader (`_nonstandard_lob_rows`) whose token match missed that the canon already calls "Cyber Incident Response Team" the cyber line, and which had no rule for a nameless part repeating a line's carrier and premium. The total counted $4,162 three times (one copy later removed by a guard, after the sum) | `_nonstandard_lob_rows`: a name the ONE line canon places in a family with its own 125 box is that box's line; a name with no family that prints a standard line's carrier AND premium is a coverage part of that policy (unnumbered decs - the number rule could not see it); a named line whose figure is another line's premium keeps its row, not the premium. **Now: OTHER rows = EBL $425, Excess $10,692; total $58,385 = the printed rows** |
| 4 | **"Since client answers: 1 updated, 1 new"** on a package no client has seen (owner's question) | Figure 24's band is computed by `recalculate_session_scores`, which EVERY human action calls - producer card answers, table saves, policy-line edits, documents added. The owner's own pre-form occupancy answer (09:06, stage "arq_remediated") wrote it | `recalculate_session_scores(..., trigger=)`: only `CLIENT_ANSWERS_TRIGGER` (the questionnaire submit, and a held client answer the producer accepts) writes `issue_diff_last`, stamped with `trigger`; the band renders only a stamped diff, so the stored one on this session is hidden too. Placement unchanged |
| 5 | **The answered occupancy kept "Minimum Viable COPE: occupancy type" in Warnings** after generation and every reload (part O's prediction - confirmed) | The upload copies each cross-form issue into `structured_issues` under its rule code. `replace_recomputed_issues` rebuilds only `legacy_` / `tier1_missing_` codes, so cross-form copies outlived every recalculation - though the recalculation re-runs the cross-form rules | `issue_registry.retire_stopped_cross_form_issues`: a copy whose code `cross_form_validator` emits (`rule_codes()`, read off its own `_issue` literals) and whose code-and-message the fresh run no longer raises is dropped. Replayed read-only on `805049a7`: Warnings 12 -> 11 (only that row), score 41 -> 41. **The stored row clears on the session's next recalculation** (any card answer or save) |
| 6 | **The rail said "9 policies" beside a 10-row table** (Brent #9's literal complaint) | The rail counted `line_records`, which carry no id and no layer - the umbrella and the Excess, both line "umbrella", both unnumbered, keyed as one | The rail counts the rows the policies table renders (`underwriting.policy_lines`) |

**Checked and RIGHT on this run:** both 131s (Amerisure Mutual $5M umbrella, SIR 0, Umbrella ticked; Travelers $4M
Excess ticked, its underlying the $5M umbrella; neither claims-made box ticked - round 6's double tick is gone); the
125's carrier list (all five companies), prior-carrier grid (GL / Auto / Property), Excess as an OTHER row, LLC ticked,
2 buildings; the 130's premium $29,278 / minimum $465 and "A"; the 140's limits, subjects, coinsurance, deductibles,
the $75,000 Stock, BI $1,000,000 and $25,000 at 72 hours, construction FRAME / NON-COMBUSTIBLE; the policies table's
10 rows; no address offered as a website anywhere (item 6); the occupancy answer survived reload and generation
(item 23). The 127 is a header only - correct, its policy is held back.

**Wrong AI values on the forms, NOT fixed (not in Brent's 27; one class - an AI value whose only evidence is another
policy's or another section's text):**
- **ACORD 140:** `BuiltYear_A/B` = 2025, `WiringYear_A` = 2025 (2025 is only a policy date); burglar alarm
  descriptions "Cyber Incident Response Team" / "Non-Panel Response Provider" (cyber dec text); fire protection
  "REPLACEMENT COST" (a valuation). All labelled `ai_verified`. Round 6 printed 2001 / 1999 / class 4 on the same boxes
  - the 140 gap fill invents COPE values on every run.
- **ACORD 126:** claims-made TICKED (no claims-made or occurrence wording in the package or umbrella decs - the
  sentence is Chubb's EPL / cyber); "other deductible" $5,000 (the PROPERTY deductible); per-project aggregate Yes (the
  UMBRELLA's endorsement list); work subcontracted 100% (no document mentions subcontracting).
- **ACORD 130:** NCCI risk ID 11525 = the CARRIER's "NCCI Code No.11525"; retrospective rating plan "Annual" (no retro
  plan in any document); state "other coverage" = a Colorado PROPERTY endorsement; "additional company information" CO.
- **ACORD 125 / 130:** applicant mailing state AZ and producer address "Phoenix AZ" - Travelers' "OFFICE: PHOENIX AZ"
  (the carrier-address-as-insured family of part P, fifth sighting).
- **ACORD 131:** underlying-coverage description = endorsement "CU 24 03 12 20 WAIVER OF TRANSFER OF RIGHTS...".

**Q2. The re-upload `b38a4367` (after the backend restart, one document held back) - two more defects, fixed:**

| # | Defect | Root cause | Fix |
|---|---|---|---|
| 7 | **"Submission Integrity Review Needed - Possible multiple submissions: S.B. MO. / CHOICE ELECTRIC LLC"** over six documents of ONE insured - and **"S.B. MO." won the merge as the package's applicant name** | The Travelers Excess dec prints "INSURED'S NAME:" (redacted) above its billing table's column headings "ACCT. EFF. PREMIUM" / "S.B. MO. DATE"; the model returned the heading as the insured. Integrity compared it as a second insured; it also blocked the insured's "LLC" from settling the same dec's "X CORPORATION" tick, adding "Entity type differs". `insured_scope` would have judged the Umbrella dec (the one document that DOES name Choice Electric) as another company's. Extraction variance - the previous run read nothing there | `normalization.is_not_a_party_name` / `is_abbreviation_heading`: a name made ENTIRELY of dotted abbreviations, with no legal-form designator, is a heading. Applied in the ONE per-document door `drop_non_party_names` (run at extraction and by `merge_facts` before it chooses), the merge's chunk vote, `_strip_non_value_facts`, the integrity check's own and package name lists, and `insured_scope`. **Measured: 1,594 per-document insured names in 1,105 stored sessions - exactly one dropped ("S.B. MO.", b38a4367).** Replayed on `b38a4367`: integrity "high", no reasons; merged applicant CHOICE ELECTRIC LLC |
| 8 | The WC dec failed AGAIN on the re-upload, with the retry live | Row 2's real cause - a malformed, complete reply - which a retry at temperature 0 reproduces | Row 2's salvage fix |

**`b38a4367` cannot be repaired in place** - its stored applicant name is "S.B. MO." and its WC read is the fragment.
Restart the backend and upload again.

**Re-checks for these fixes (frontend is live on Vite; the BACKEND needs a restart - it runs without --reload):**
1. Open any form, scroll the PDF until the header hides, click **Back to review** -> navbar visible, no blank band.
2. Restart the backend, then on `805049a7` answer or dismiss any card -> the "Minimum Viable COPE: occupancy type"
   warning is gone; the "Since client answers" box is gone (no client answered).
3. The rail reads **10 policies**.
4. A FRESH upload of the same six decs -> the ACORD 130 shows the three class rows and their payrolls, no "WC payroll is
   missing", and the 125 total equals its printed rows ($58,385 without WC).

Tests: `tests/test_choice_electric_run7_8oct.py` (39 after Q2). Full suite after Q2: **13,559 passed, 1 failed (the known `test_arq_acord125_missing_only`), 19 skipped**. **Measured (D6):** the 125 OTHER-row change replayed over
every stored session whose facts decrypt locally and carry coverage lines - **317 sessions, 1 changed** (`805049a7`:
OTHER rows 4 -> 2, total $66,709 -> $58,385); 155 sessions are Render-key and cannot be read here. The stale-copy
retirement replayed on `805049a7` alone: Warnings 12 -> 11, score unchanged. No score rule changed in this round.

### R. `505bf394` - the first run with every 8 Oct fix (6 documents, Business Auto Policy held back, 8 forms)

**Confirmed live:** no integrity screen and the applicant is CHOICE ELECTRIC LLC ("S.B. MO." fix); the WC dec read in
full - 202 keys, 3 class rows, CO, payroll $2,626,500, X-mod 1.08 (salvage fix) - so the ACORD 130 prints every class
row, rate, payroll and premium ($37,600 / $597 / $180), $29,278, minimum $465; **item 26 PASS** - Payroll/Employee 100,
WC Supplemental 100, no "WC payroll is missing" (Exposure 20 = auto held back -40, no operations / GL class codes -20,
the two cross-form gates -20); state CO, so **137_CO is back**; the 125 OTHER rows are EBL $425 and Excess $10,692 and
its total ($54,223) equals the printed rows; the policies table 10 rows; Data Consistency nothing to confirm. ACORD 28
is NOT a regression: in clean 7-document runs it was triggered by lender / loss-payee wording, and none of these six
documents has any - it belongs to the held-back auto policy. Pre-form (reconstructed): 29, 1 hard stop (occupancy),
12 warnings; after generation 32, 2 hard stops (occupancy, Period of Restoration - promoted at generation, C75),
11 warnings.

**Found on this run, NOT fixed (owner's next call):**
- **A. "GL is claims-made" from the EPL dec.** Chubb's "NOTICE: THE LIABILITY COVERAGE PARTS PROVIDE CLAIMS-MADE
  COVERAGE" (its own EPL parts) set `gl_is_claims_made` on the EPL document this run (False on every earlier run); the
  package OR-merges flags, so three false "Claims-made continuity" warnings, and the ACORD 126 printed "claims-made
  coverage" and a retro date 01/01/2025. Fix: a line's flag only from a document carrying that line.
- **B. Cyber premium missing.** The model attached no premium to any cyber part this run; the cyber dec's own index
  holds "Item 8. Policy Premium $4,162.00". The 125 ticks Cyber with no premium and its total is $4,162 short; the
  table's Cyber row is blank. Fix: a policy record with no premium takes its document's single "Policy Premium" entry.
- **C. AI values borrowed from another policy or section (one class):** ACORD 127 vehicle COST NEW $798,556 (building
  1's limit); ACORD 140 building improvement "Other: Certified Risk Management Program" (a WC premium credit); ACORD 130
  "employees travel out of state" Y with a class row as the explanation, NCCI risk ID 11525 (the carrier's NCCI code);
  ACORD 131 underlying-coverage description = a carrier name plus a WC policy title; ACORD 131 (Excess) Occurrence
  ticked with nothing stating it; ACORD 125 business type "Other: Electrical Wiring..." (a contractor).
- **D.** Producer address "Office: Phoenix AZ" (Travelers' office line) on the 125 / 130 - the carrier-address family.
- **E.** No audit period extracted this run ("ADJUSTMENTS OF PREMIUM SHALL BE MADE ANNUALLY" not read) - item 5's code
  could not print; the rule itself passed on two earlier runs. Another non-repeatable read (Brent question 16).

**How to verify the rest:**
1. **Item 1** - open any form, scroll the PDF until the navbar hides, click Back to review: navbar visible, no blank
   band. **Item 9 (rail)** - the rail reads "10 policies".
2. **Item 25 (+ 9's auto row, ACORD 28)** - Documents -> Add documents -> the Business Auto Policy. "Reading ... into
   your forms" must finish. Then the session row shows `document_ai_fill` done, a Commercial Auto row, 137_CO filled,
   ACORD 28 offered, Auto Completeness recovered.
3. **Item 10** - the policies table: click a column header (sorts); tick "Group by carrier" (groups, premium
   subtotals); a Limit column.
4. **Items 22 and 27** - on the NEXT fresh upload, before generating: Recommendations -> "Raise your score" -> open a
   row (its fix window opens) -> answer -> the score moves; "Before you generate" lists the form checks.

### R2. The Business Auto Policy added to `505bf394` AFTER generation (item 25) - what really changed

**Item 25 PASS.** `document_ai_fill` reached `done` (11:17:17 -> 11:20:06), 46 boxes over 6 forms, 3 "new document
says" choices; the deterministic re-stamp changed the rest - **164 boxes on 7 forms** (130 untouched, correctly).
**Item 1 PASS** (owner, Back to review). **Item 10 PASS** (owner: Group by carrier with premium subtotals, Limit column).

| | Before | After |
|---|---|---|
| Package | 32 | **40** (Exposure 20 -> 45, Umbrella 80 -> 100, Structural 46 -> 47) |
| Per form | 125 40, 126 28, 127 24, 130 45, 131 54, 131x 42, 137_CO 28, 140 34 | 42, 30, **54**, 47, 60, **55**, **55**, 36 |
| Warnings | 11 | **7** - gone: vehicle schedule, covered-auto symbols, umbrella / auto CSL unknown, UM/UIM advisory |
| Hard stops | 2 (occupancy, Period of Restoration) | 2 (unchanged - neither is an auto question) |
| Offers | - | **ACORD 28** ("lender / mortgagee evidence") |

**Right:** the 127's four vehicles (2001 Chevrolet Express G2500, 1999 GMC Safari XT, 2012 Haulmark trailer, 2022
Chevrolet Equinox LT), rate classes, territory 111, use Service, $1,000 comp / collision, liability / med pay / UM
ticks, Denver 80221 garaging; the 137_CO insurer, symbols (1 liability, 2, 7 physical damage), hired and non-owned
Yes; the 131's any-auto tick and $1,000,000 auto CSL; the 125's Business Auto tick and vehicle-schedule section.

**Wrong, written by the addition (NOT fixed):**
- ACORD 125 business START date 01/16/2025 - the common declarations' ISSUE date (reads as a 2025 new venture).
- ACORD 127 COST NEW: A $798,556 (building 1's limit), B-D $1,000 (the deductible); the real cost-new figures
  ($21,210 / $23,316 / $7,500 / $28,750, the dec's "Cost New" column) sit in the STATED AMOUNT boxes; garaging street
  line "CO".
- ACORD 137_CO: four OTHER-coverage rows "Medical Payments $1,000,000" (the dec prints Med Pay "SEE SCHEDULE");
  BI per person $1,000,000 on a CSL policy. Facts `auto_med_pay_limit` / `auto_um_uim_limit` = "$SEE SCHEDULE".
- ACORD 140: all 17 new boxes - improvement years 2025 x5, roof "Composition" x2, SPOILAGE limits = the building /
  BPP limits, BLANKET summary = the buildings' limits, front exposure = the VEHICLE garaging address, guard / watchmen
  = the WC "Certified Risk Management Program" credit. The auto dec never says spoilage or blanket.
- Data Consistency: "Auto Liability Structure - Each Accident (umbrella) vs combined single limit (auto)" - one thing
  in two wordings; a false card that also labels the 137's CSL tick "conflicted".
- Policies table: still NO Commercial Auto row; the auto PDF (which carries the package's common declarations page)
  appears as a second source on the GL and Property rows instead.

**Period of Restoration after generation is correct under today's rules** (C75 demotes it before forms, generation
promotes it once ACORD 140 is chosen; nothing in these decs states a period of restoration - "EXTENDED PERIOD OF
INDEMNITY 540 DAYS" is a different coverage). On the editor's left panel it is listed under **Cross-Form Validation**;
the red package HARD STOPS block names only the ONE reason that set the cap (occupancy) - with two capping stops, the
second is not named there.

### S. ROUND 9 - everything left that is neither UI nor Brent's (8 Oct night, offline; owner: "fix the remaining things")

Every fix below was replayed on the stored sessions (`505bf394` before / after the auto policy was added) and each new
per-document rule was measured over **all 1,688 stored documents in 1,132 sessions**. Two first cuts over-reached on
that measurement and were narrowed BEFORE anything shipped (noted per row). No prompt or LLM call changed.

| # | Problem (where seen) | Root cause | Fix (door) | Measured |
|---|---|---|---|---|
| 1 | Adding a document wrote 17 wrong ACORD 140 boxes, 12 on the 127 / 137 (R2) | The add-document stamp (`session_documents._stamp_with_answers`) never attached the package's documents, so every scoped guard stood down - sections no document carries (spoilage, blanket), values from another policy | Attach them exactly as generation does (`scoped_evidence.attach_documents`) | The addition's 46 AI boxes: **41 refused, 5 kept - all 5 correct** (garaging city / ZIP / state, garage description, hired PD state) |
| 2 | "GL is claims-made": 3 false warnings + a GL retro date and "claims-made coverage" on ACORD 126 (R, item A) | The EPL dec's own notice set `gl_is_claims_made`; package flags are OR-merged | `extraction_service.drop_flags_of_lines_not_carried` (`_LINE_ATTRIBUTE_FLAGS`): a line's attribute only from a document carrying that line; run per document before the merge | 14 documents in 11 sessions - every one a Chubb EPL / cyber / ForeFront dec; no GL document touched |
| 3 | Cyber premium $4,162 missing; 125 total short (R, item B) | The model attached the premium to no row this run | `assign_declared_policy_premium`: a single-policy document with every row unpriced takes the ONE "policy premium" its own verified declarations state | 1 document (the cyber dec). Multi-line, two amounts, minimum / additional premiums never assigned |
| 4 | "Auto Liability Structure - Each Accident vs combined single limit" Data Consistency card (R2) | One structure, two wordings | `fact_equivalence.auto_structure_reading` (csl / split) inside `same_fact` | split vs CSL is still a conflict |
| 5 | Med Pay / UM limits stored as "$SEE SCHEDULE" (R2) | A pointer kept as an amount | `drop_reference_amounts` - LIMIT facts only. **First cut also took deductible-basis sentences (64 documents); narrowed** | 1 document |
| 6 | ACORD 140 invented improvement years 2025 (every run), round 6's ISO-copyright 1999; the 125's business start date = the issue date 01/16/2025 | A year / date "printed somewhere" passed every presence test | `ai_answer_guards`: a building year printed only inside dates / copyright lines / glued to a vehicle description is refused; a start date printed beside a policy-administration label is refused. **First cut counted "electric" as a building word (the insured's name); narrowed** | - |
| 7 | Roof "Composition", protection class, sprinklers, cyber text as burglar alarm, "REPLACEMENT COST" as fire protection, garaging address as front exposure; 137 UM limits $1,000,000 copied from liability | ACORD options and amounts with no evidence for THAT attribute | `cope_answer_without_evidence`: the documents must state the attribute with the answer near it (coverage amounts read forward from their own heading) | - |
| 8 | 137 "Medical Payments $1,000,000" x4 OTHER rows | Med Pay has its own boxes on the 137 | `other_row_names_a_coverage_with_its_own_boxes` (row + its limit / symbol) | - |
| 9 | 130 NCCI risk ID 11525 = the carrier's "NCCI Code No.11525" | A carrier code in an insured identifier box | `carrier_code_as_insured_id` | - |
| 10 | 130 "employees travel out of state" Yes, explained by a rating row; 125 business type "Other: Electrical Wiring..." | A rating classification is not an explanation / business type | The classification rule extended to explanation and business-type boxes | - |
| 11 | 127 garaging street line "CO" | A state code in a street box | `not_a_street_line` | - |
| 12 | 126 "claims-made coverage", 140 "Certified Risk Management Program" (WC credit) | Rule (a) never judged TEXT | `scoped_evidence.foreign_policy_text`: a description printed ONLY by documents of another line (not 125 / 101 / 25 / 131 / 186, never a description of the insured's business) | Both refused on `505bf394`; correct descriptions kept |
| 13 | 127 COST NEW = $1,000 deductible / $798,556 building limit; the real cost new in STATED AMOUNT | The dec's vehicle schedule is a TABLE with VINs redacted - the VIN-keyed reader found nothing | `_read_vehicle_schedule_tables` (columns by position, matched by year + make + model, never guessed between two rows) + `pdf_service._resolve_vehicle_stated_amount` (the table's empty Stated Amount = owned blank) + the meaning gate's vehicle-value category | All 15 vehicles: cost new 21,210 / 23,316 / ... printed by rule |
| 14 | **Item 9: no Commercial Auto row** (open since round 6) | The auto dec's bare "Liability" row read as GENERAL LIABILITY and "Property Protection Insurance (Michigan Only)" as PROPERTY, so the auto policy joined the GL / Property rows and had none of its own | `attach_generic_rows_to_document_line` (a bare liability row belongs to the one line its document's named rows establish) + `lob_canon` "property protection" is not Property. **First cut counted "general" / "commercial" as generic - renamed real GL rows on 99 documents; narrowed** | 2 documents (both Choice Electric auto decs). Table: 11 rows incl. "Auto Liability" (Business Auto Policy); GL / Property sourced from the Package only |
| 15 | Producer address "Office: Phoenix AZ" (Travelers' office line) under the login's agency | No document names an agency, so the login is the producer - but only EMPTY producer facts took its values | `_route_producer_party`: in that case a document address with no street is dropped; the account's Agency Address (or a blank) takes its place | - |
| 16 | No audit period on one run (the model skipped it) | The deterministic reader scanned only lines containing "audit"; the NCCI page says "ADJUSTMENTS OF PREMIUM SHALL BE MADE ANNUALLY" | The scan also reads "adjustment(s) of premium" lines (an unticked options list still reads as nothing) | Annual on `505bf394` |

**Not done, and why:** the red HARD STOPS block naming only one capping stop (UI); carrier letterhead states (held
for Brent, part P); the 131's underlying-coverage description wording and the Excess Occurrence tick (borderline -
plausible from the documents, not wrong enough to refuse without a rule I can state).

**Live check (one fresh upload of all 7 decs after a backend restart, then add the auto policy again):** no
"claims-made" warnings; Cyber $4,162 in the table and on the 125; ACORD 127 COST NEW 21,210 / 23,316 / 7,500 /
28,750 and STATED AMOUNT blank; the policies table shows a Business Auto row; ACORD 140 has no 2025 years, no roof
material, no spoilage / blanket limits; ACORD 137 no "Medical Payments" OTHER rows; ACORD 130 NCCI risk ID blank,
audit "A"; the 125 producer address blank (or your Account Settings address).

**Two corrections from the full suite (first run: 13,601 passed, 3 failed - the known one plus two of mine):**
- `test_cost_new_still_stamps_with_its_own_witness` - **the CODE was wrong.** The meaning gate's vehicle category was
  "value", but a dec entry labelled COST NEW witnesses its figure as "cost", so a real COST NEW 26680 was refused.
  COST NEW boxes now take "cost", STATED / AGREED AMOUNT "value". (Making the two interchangeable was rejected: it
  would let a GL subcontract cost back into a property VALUE box.)
- `test_replay_acord140_raises_no_completeness_hard_block` (Brent's own `ca93ed8f`) - **the code was wrong in part,
  the test in part.** The producer had answered year built 2001 and protection class 3; gap fill carried them to
  building 2 and the new rules refused them because no DOCUMENT prints them. A value equal to one a person supplied
  is now grounded by that person (`ai_answer_guards.person_values`) - both values stand again. Roof material
  "Composition" was answered by nobody (only roof YEAR 2011) - refusing it is right, and the test's "no gap at all"
  held only because that invented value hid the gap. The test now pins the one honest gap (roof material, both
  buildings) and both producer values. **Visible change for Brent: his 140 now asks for roof material instead of
  printing an invented "Composition".**

Tests: `tests/test_choice_electric_run8_8oct.py` (46). Full suite after the corrections: **13,605 passed, 1 failed (the
known `test_arq_acord125_missing_only`), 19 skipped**.

### T. ROUND 10 - the owner's run `15f43bba` (all 7 documents, 8 forms), graded box by box; 9 defects fixed offline

**Read first: that run's backend started 18:15, before the last round-9 edits (18:22-18:23).** Two of its wrong values
(the 127 hold-harmless explanation from the WC policy; the 140 roof answers) are already refused by the current tree
on the run's own stored values. Restart the backend before the next run.

**Held up live in this run:** no claims-made warnings (round 9); the 127's four vehicles with Cost New from the
schedule table (21,210 / 23,316 / 7,500 / 28,750) and Stated Amount blank (its column is empty); class codes,
territory 111, comp / collision $1,000; the 130's three class rows, payrolls, rates, minimum premium 465, total 29,278,
EL 1M/1M/1M, and the AI's five prior-year "mods" (really this term's rating factors) refused; both 131s (umbrella 5M,
excess 4M over the Amerisure Mutual umbrella); 137_CO symbols 1 / 2 / 2 / 7 / 7 and the Med Pay $1,000,000 refused;
the 140's two buildings, every limit / deductible / coinsurance, and the invented years (2025 x7), roof materials,
"80%" sprinkler and zero counts all refused; 125 cyber $4,162 and total $58,385.

**Defects found, all fixed offline (each measured; none moves a score on the measured sessions - fix 1 removes the
misalignment warnings here, umbrella pillar 90 -> 90, and the package stays capped by its hard stops):**
1. **An issue date read as four policies' start.** The Business Auto Policy's common declarations prints
   "01/16/2025 / Issue Date: ___" beside its coverage-part menu; the reading dated 11 menu rows 01/16/2025, so GL /
   Property / Inland Marine / Crime opened 01/16/2025 (125 prior grid, 131 GL underlying, policies table) and two false
   "Umbrella and GL policy periods misaligned" warnings fired. `extraction_service.issue_only_dates` /
   `clear_issue_dates` (per-document pre-pass): a date printed ONLY beside an issue / countersign / transaction /
   printed / processed label - never after a period label, never in a range; a label belongs to its nearest date -
   leaves that document's rows and date facts. **1,695 stored documents: 3 change, all issue dates** (this auto dec, a
   test certificate whose only date is "Date Issued"). Re-merged: all four lines 01/01/2025, both warnings gone.
2. **No Commercial Auto row (item 9).** `_sources_are_own_declarations` counted the menu rows as other lines on the
   auto dec. Now only rows stating something (premium, number or date) speak; a document of only bare rows is judged on
   all of them, as before. Re-merged: the auto record (01/01/2025-01/01/2026, own declarations) is back. 8 stored
   documents change eligibility; the 3 sessions re-built show no other record change.
3. **140 protection class "GRP I"** (the property schedule's Group I RATE line), labelled AI verified, and **BCEG
   "0"** (no document says BCEG). `cope_answer_without_evidence` abstained on any answer with no 4-letter word; a short
   code is now read as itself (a Y/N tick still abstains), and BCEG joined the table. Corpus: 24 stored AI answers
   newly refused, all junk (GL class codes and "SEE SCHEDULE" as BCEG, ZIPs as fire district, edition dates as Med Pay).
4. **127 "other owner" = "Chevrolet" / "Gmc"** (the schedule's MAKE column), and the gate then ticked "any vehicles not
   solely owned? Y" from them. `pdf_service._vehicle_make_in_a_party_box`, before the gate (`VEHICLE_MAKE_AS_PARTY`);
   lenders' own names never judged. Corpus: 0 of 293 AI party boxes change.
5. **127 "Any hold harmless agreements? Y"** explained by the WC policy's waiver-of-subrogation endorsement. The
   explanation is refused as another policy's text (current tree); now an AI Yes whose OWN explanation is refused that
   way goes with it (scoped evidence runs after the gate). Corpus: 0 other forms.
6. **130 WC deductible "$1,000"** - the WC policy states no amount; "$1,000.00" is the umbrella's Minimum Policy
   Charge, and the umbrella counted as a WC witness through its schedule of underlying insurance.
   `scoped_evidence._drop_reference_only`: a document that only references a line (flags, not its own rows) speaks for
   that line's limits, dates and identifiers - never deductibles, premiums or text - when the line's own policy is
   present. Corpus: 0 of 1,210 forms change.
7. **130 "CO: CO"** and the **131 "Umbrella follows form over the underlying coverages (per submitted documents)"** -
   the second is OUR derived `umbrella_follow_form` sentence (`extraction_pipeline`, set from the Excess policy's
   "FOLLOWING FORM" heading), copied by gap fill into 131 boxes in 7 stored sessions (one a tail-coverage box). Two
   non-answer rules: `AI_LABEL_REPEATS_ITSELF`, `AI_SUMMARY_NOT_DOCUMENT_TEXT`. Corpus: the 7, nothing else.
8. **The printed X-Mod 1.0800 never reached the 130.** `parse_xmod` read at most 3 decimals, so "1.0800" was "no mod"
   (the fact registry's validator allows 4) - on every Choice Electric session (b248c194, ca93ed8f hold it). Fixed, and
   `derive_xmod_from_rating_lines` reads "Experience Mod 1.0800" off a rating line when the fact is empty (one factor
   only). Corpus: 16 agree with the stored mod, 4 sessions gain one (Meridian 0.96, Orbin 1.00). **D6: no score moved**
   - measured on b248c194 (X-Mod status unknown -> satisfied, deduction 0 -> 0) and ca93ed8f (unchanged); unknown
   never deducts. The 130's EXPERIENCE OR MERIT box now prints the mod.

**Found, NOT fixed (owner's call or next round):**
- **127 USE "Service" on vehicle 4** (2022 Equinox, class 7398) - its own schedule line prints no use; the other
  vehicles print LOCAL SERVICE. USE is policy-level by the 15 Sep ruling; per-vehicle use needs the owner's yes.
- **137 hired physical damage "primary" ticked** - no document states the basis (an AI tick with a borrowed quote).
- **`umbrella_follow_form` is set from the EXCESS policy's heading** and the umbrella scorer credits it to the
  umbrella - score-moving, needs a D6 table.
- **125 / 127 mailing city and ZIP "Denver 80221"** come from the vehicles' garaging line (the decs redact the mailing
  address) - plausible, not stated as the mailing address.
- **The 131's deterministic ANY AUTO tick is paired with "UnderlyingCoverage_Coverage_OtherDescription_A"**
  (`_question_explanation_pairs`) and the naked-Yes guard blanks it whenever that unrelated box is empty. It printed in
  this run only because the AI had written that box (later removed). Seen on the replay; pre-existing.

**Replay of this run through the current tree (stored facts, stored AI answers, judge off): 16 boxes change.** 12 are
this round's refusals (127: both makes, "vehicles not solely owned? Y", the hold-harmless pair; 130: "CO: CO", "$1,000";
131: the follow-form sentence; 140: "GRP I" x2, BCEG "0" x2). The other 4 change with every round-10 rule switched
off, so they are replay effects, not fixes: the any-auto tick and the 130 deductible type (Other -> Medical) - the
pairing above - and the 137 hired physical damage "primary" tick, which drops only because a stored run keeps no
evidence quote (live it would print again - still open).

Tests: `tests/test_choice_electric_run10_8oct.py` (28). Full suite: **13,633 passed, 1 failed (the known `test_arq_acord125_missing_only`), 19 skipped** - 13,605 + the 28 new, no regressions.

### U. BRENT'S ANSWERS OF 8 OCT 2026 (ACORD 125 page one, SIC / NAICS, landlords) - applied

| Brent's answer | Before | Now |
|---|---|---|
| **Two insurance companies:** "Don't list both EMC companies in the top Carrier box. That field is for the carrier tied to the application. Existing carriers are listed by coverage under Prior Carrier Information." | Several writing companies printed "; "-joined (30 Sep join) | **Blank**, and the unscored "carrier receiving this submission" card asks (`pdf_service._resolve_page_one_receiving_carrier`). One writing company still prints (the 15 / 29 Sep renewal rule - not part of his question) |
| **Renewal premiums:** "Don't automatically put the expiring premium from the dec in the page 1 premium field. Expiring premiums belong under Prior Carrier Information. Leave the page 1 premium blank unless the appropriate premium is provided." | A dec-only renewal printed every line premium, the OTHER rows' premiums and the total on page one (29 Sep) | **Page one blank** (`_mark_page_one_current_policy` marks the premium on every dec renewal); a quote / application premium, a typed total, or a line premium a person typed in the policies table still prints; the prior-carrier grid still prints the expiring premiums; **the 130 still prints the WC premium** (his item 7 - `wc_premiums.premiums_withheld` ignores the page-one flag on a renewal) |
| **SIC / NAICS:** "leave them blank and flag them for the agent/client to confirm" | Already so: no document code -> blank (the identifier / classification guards), and "NAICS or SIC industry code" is a key-details item for the agent | **No change needed** (checked on `2076fe35`) |
| **Several landlords:** "The first can go under Additional Interest on the 125. Additional landlords go on ACORD 45." | With 2+ rented locations, NO landlord printed | **The first location's landlord prints** on 125 Additional Interest row A; the rest are a producer to-do in Needs attention: "Additional landlords (ACORD 45)" naming each (Primble does not produce ACORD 45) |
| **ACORD 25:** "Don't automatically carry a landlord over as an Additional Insured." | Nothing ever carried a landlord to the 25 | **No change needed** |

Measured on `2076fe35`: the 125 loses the five joined carrier names, the eight page-one premiums and the $58,385
total; the ACORD 125 per-form score stays 42 and the package score does not read those boxes. **Follow-up for Brent:
the Prior Carrier Information grid has ONE "Other" column per year, so Umbrella, Excess, Cyber, Crime, Inland Marine,
EBL and WC's expiring premiums cannot all print there** - which one goes in "Other", and do the rest go to ACORD 101
remarks? (His item 7 asked for every premium "with carrier information" on the 125.)
Tests: 12 rewritten to his answers (they pinned the 29 / 30 Sep rules he reversed - the TESTS were wrong, not the
code), +5 new in `tests/test_choice_electric_run10_8oct.py`. Full suite: **13,648 passed, 1 failed (the known `test_arq_acord125_missing_only`), 19 skipped** - no regressions.

### T2. The re-run `2076fe35` (backend restarted 20:56, after every round-10 edit) - round 10 verified live; 3 more fixed

**Verified live in this run:** every policy now starts 01/01/2025 (125 prior grid GL / Property, 131 GL underlying);
**item 9 PASS - the policies table renders 11 rows including Commercial Auto** (01/01/2025-01/01/2026, $1,000,000
CSL; no premium because the auto dec prints "$" / "SEE SCHEDULE" - correct); the 131 prints the auto underlying's
own dates; no umbrella-misalignment warnings; the 127 makes / hold-harmless pair / "vehicles not solely owned" gone;
the 130 prints the X-Mod 1.0800 and lost "CO: CO" and the $1,000 deductible; the 131 follow-form sentence gone; the
140 lost "GRP I" and BCEG "0". (This run's auto extraction carried no menu rows, so the issue-date rule had nothing to
do here - it is proven on 15f43bba's stored documents.)

**Found in this run, fixed offline (backend restart needed):**
1. **Hard stop said "building or BPP value" missing** although the 140 printed every building's limits - this run's
   extraction returned no `property_building_value` / `property_bpp_value` (the previous run did: $798,556 /
   $73,008). `extraction_service.derive_property_values_from_premises`: an empty fact takes the first scheduled
   building's value, ONLY from a document whose role may state it (`fact_comparison.document_witnesses` - the
   SYS-05 certificate's $4,200,000 is still never a building value; the first cut took it and was narrowed). Corpus:
   7 sessions gain a value, 4 lose the false item; every COPE hard stop stays (occupancy / construction still
   missing), so no cap moves.
2. **Excess 131: claims-made "Yes" with retro dates 01/01/2025** - the only claims-made wording is the EPL policy's
   notice; the excess prints "any one occurrence". `scoped_evidence.trigger_values` (rule d): an AI claims-made tick
   needs claims-made wording in that policy's own documents; an AI retro date must be printed beside a "retro"
   label there (an Employee Benefits retro date on a GL dec stands; a "No" is never judged). Corpus: 31 stored retro
   dates refused - none printed within 600 characters of any "retro" label (most are the policy's own effective date;
   Choice Electric's EBL "03/01/2022" appears in no document).
3. **130 credit / rating bureau = "3", bureau name "Dun And Bradstreet Number"** - the Package Policy's "ACCOUNT
   NUMBER: 3". `ai_answer_guards.bureau_value_without_its_label` (`AI_BUREAU_ID_NOT_STATED`). Every value ever stored
   in those boxes was junk (3 in the corpus).

**What the producer must still do on this package (not defects - the documents do not state these):**
- Occupancy type (and, for Brent, the Period of Restoration) - the three hard stops capping the score at 60.
- Applicant mailing address and contact information - the decs redact them.
- GL class codes - no GL class code is printed anywhere in the package.
- Drivers - the auto policy schedules vehicles, not drivers.

**Still open (code):** 130 OTHER rating row B holds "CO 9812: Employers Liab Incr Limits" (the form has its own
INCREASED LIMITS row); the 137 hired physical damage "primary" tick; per-vehicle USE (owner's call); follow-form
credited from the excess (score-moving); the 131 any-auto / description pairing.

Tests: +10 in `tests/test_choice_electric_run10_8oct.py` (38).

### N. HOW TO VERIFY THE REST LIVE (written 8 Oct, after round 6)

**Before anything: hard-refresh the tab (Cmd+Shift+R) and be on `localhost:5173`.** The `dist/` build is from
23 Sep and primble.ai is a different deploy. A stale bundle is what made Brent's 5 Oct screenshots misleading
(section A), and the app still has no version check.

**Start a FRESH package of the seven `Choice-Electric/` decs.** `b4d18e8e` has Harborline's facts merged into it
and can no longer answer a question about values. The round-6 fixes act at the MERGE, so only a fresh upload
exercises them.

#### Re-run the two that were live-verified broken and are now fixed

| # | Where | PASS looks like | FAIL looks like |
|---|---|---|---|
| 26 | Review page, Warnings | **No** "Workers Comp detected but payroll is missing". Exposure above 60 | the warning is back, Exposure in the 30s |
| 25 | Package page -> Documents -> "Add documents". Add any extra PDF **of this same insured** | the panel reports the boxes updated AND the "Reading ... into your forms" line finishes; `document_ai_fill` reaches `done`, not `running` | the message sticks on "Reading ..." for ever (the old crash) |

For 25, also confirm the cross-insured guard still bites: add `harborline_dec_package_10p.pdf`, answer **"they
belong to this insured"**, then check the ACORD 125 - the applicant's DBA, FEIN, address, contacts, revenue and
NAICS must still be Choice Electric's (or blank), never Harborline's. That is round 6's defect 2.

#### The four built-but-never-seen

| # | Where | PASS looks like |
|---|---|---|
| 6 | Review page -> Data Consistency, on the fresh package | no row offers a **street address** as a website. The Cyber policy's real website, if captured, is available to the 126 and never the 125 |
| 10 | Review page -> the policies table | the two "not a conflict" blocks are gone; there is a **Limit** column; a column header sorts; a **"Group by carrier"** checkbox groups with premium subtotals |
| 22 | Review page, **before selecting or generating any form** | a **Recommendations** section with "Raise your score" and "Your forms will need"; every row opens a fix window; applying one moves the score with no form generated |
| 23 | Hard stop "Minimum Viable COPE ... occupancy type" -> **Open to fix** | the modal shows **2 buildings** with per-building columns and ONE package-level Occupancy Type above the table. Answer it, **Apply**, then RELOAD: the value is still there and the hard stop is gone |

**Item 23 note (8 Oct).** The red "Street address is required" on the pre-filled rows is **advisory** - the Apply
button is gated on `busy` and the schedule loading, never on row errors, so Apply works. The placeholder
("789 Commerce Dr / Ste 400 / Houston / TX / 77001", `schedule_capture.py`) is a Texas address on a Colorado risk
and invites a copied wrong value - owner's call whether to make the placeholders neutral.

#### What CANNOT be judged from a screen, and must be read from the session

These were all verified on 8 Oct by dumping the stored session, not by looking:

* which facts came from which document (round 6 defect 2) - compare `docs[*].facts` against the merged `facts`;
* whether a form box is grounded - normalise the value and search the document text (that is how the ACORD 140's
  "1999" was caught as an ISO copyright year);
* whether the pre-form and post-form score agree (item 18) - recompute `score_package_pre_generation` on the row
  with the forms removed and compare with the stored `package_sqs`;
* the real policy count (item 9) - `facts["coverage_lines"]`, not the rendered table.

**A screenshot proves a screen. Only the session row proves a value.**

### H. Sorted by "needs Brent or not" - owner's ask 6 Oct (UI last)
**Owner's run 6 Oct (session `ac300073`, CH125 kit, on primble.ai - facts do not decrypt locally, so Render / 7b681f4):**
pre-form about 80, then 60 after generating ACORD 127 alone. Cause: the cross-form rule "Business Income limit but no
Period of Restoration" is DEMOTED to a warning before forms (C75) and RE-PROMOTED to a hard stop at generation; at
7b681f4 it is not scoped to the property forms, so it capped a 127-only package (raw 78 -> 60). After generation the
package page shows the stored Total Package Score (item 1), hence 60 on reopening. The 5 Oct work scopes the rule to
ACORD 140 / 160 - not deployed. The same run still shows the other false warnings fixed on 5 Oct ("26442473% of
revenue ($19)", umbrella dates, multi-state WC): primble.ai cannot verify the 5 Oct work until it is deployed.

**Step 0 - before anything:** commit the uncommitted 5 Oct work (the `_fv` re-run fix and the saved-table markers are
in it). Exception to "UI last": the "new version - reload" banner - without it Brent can test old code again.

**Can fix now, no Brent approval (bugs, or things he already asked for):**
1. Location table: keep every field on save (LOC #, construction, values), building labels -> LOC/BLDG #, a vehicle
   garaging address never becomes a premises, the loose `locations` list follows the table, the COPE columns he asked
   for (+ CSV template). Fixes 14, 23 and the false location warnings in 26.
2. ACORD 140 guards: never delete a value the documents print; clear a subject code with its amount; a reason on
   every removal. Removes the 6 false hard stops and the DRAFT download (27).
3. One door for stops: generation and every scorer recompute stops from the facts they score; a hard legacy stop is
   never hidden behind a demoted warning (18).
4. A box edit on one form updates the same fact on every form (the 7 date mismatch rows in 27).
5. Policy identity: no digit = not a policy number (Brent's rule); ISO form numbers with a second letter group; Excess
   its own policy record with its own carrier (10 policies, Amerisure Mutual back); per-policy facts (premium, website,
   "schedule of underlying") out of the conflict picker; package values no longer taken from the first-uploaded dec
   (4, 6, 7, 8, 9).
6. Audit: an unticked options list is not an answer; never decode a bare "A" (5, reading half).
7. Extraction misreads: dividend plan is not a payment plan (code-or-blank); NCCI code is not NAIC; a website must look
   like one; pending/prior date is not a retro date; EPI is not period of restoration; carrier office states are not
   the insured's state. Any prompt change = an `improving-ll.md` entry.
8. Wrong values on the forms (section D): WC codes as GL on 126; GL aggregate (richer underlying schedule); 131 limit
   from the right layer and no EPLI in Employee Benefits; 130 claim count / mod / NCCI risk id / $6.50 / floor count /
   years; 127 "111 Denver" and the OCR dump; 137 symbol junk and Med Pay.
9. ACORD 125: Federal in the carrier list; prior-carrier rows without policy numbers; the OTHER premium boxes (EBL $425);
   Excess as its own line row (Brent: "should have been a line item"); total = the printed rows.
10. Recognise "Employee Benefit Liability" (singular) - the warning goes; WHERE it prints waits for Brent.
11. Exposure: read "LOCAL" as a radius; one GL-class-code reader.

**Needs Brent first:** two 131s (one per layer); 130 audit tick (annual = At Expiration?); EBL under WC or GL; WC in the
125 total / EPLI row with no premium; past proposed date (roll forward or ask); pre-form severity of stops (C75);
per-building year / roof / PC (one answer or per building, block or warn); forms 152 / 834 / 827.

**Owner's call (not Brent):** encrypting `docs[*].facts` (CLAUDE.md: ask Brent about compliance before data-handling
changes - this one only tightens it); #10 reverses the 27 Sep restoration; #19 Cancel; #25 upload after forms.

**UI - last:** "Enter at least one value" modal (a bug), 2, 9 wrap, 12, 13, 16, 17, 19 Cancel, 24, 7a money format,
26 "-N pts" display, 22 Best Solutions before forms, 27 count only real actions, 10 and 9 inline edit, 25 upload.

---

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
- **Committed and pushed as `4f7e7db` (1 Oct) on `ready-for-deployment-V1`.** Not yet committed: the owner's build of
  1 Oct night - 24 paths, including 3 NEW files the running code imports (`backend/services/follow_ups.py`,
  `frontend/src/utils/followUps.js`, plus `backend/tests/test_owner_asks_1oct.py`); add them explicitly. Whether Render
  has deployed `4f7e7db` is not verified here - check the Render dashboard before telling Michelle anything is live.
- Full backend suite: **11,612 passed / 1 failed / 19 skipped** (1 Oct night, after the owner's build; the one failure is the
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
| 1 | Opening a package should land on the package profile ("Continue where you left off") | **Done, seen working on localhost** (owner's retest, 1 Oct night - R8) | A package click always opens the package page; "Continue where you left off" (editor on the LAST form open, or the progress screen) once forms exist or are generating; "Generation didn't finish" for a dead run; "Total Package Score" after generation; the forms listed under Key Details with Open; the re-reading actions locked (screen + server 409) | - |
| 2 | A score before forms are generated | **Done** (owner, 1 Oct night: the forms-first wording is left as is) | The pre-form screen shows "NN / 100" and the tier "so far" (seen live) | The wording is still forms-first ("It can change when forms are generated", "continue to form selection", dashboard "SQS -"); the score moves at generation (64 -> 66) with no input. Not in this round |
| 3 | Remove the "Important" block | **Done, seen working** | A missing key detail that has its own card is said ONCE, on the card; the key-details line counts it ("1 more under Warnings") - seen live on `bfa8711d` (U2) | - |
| 4 | Proposed dates from the dec | **Done, seen working** | A calculated box (the proposed term) is "Please verify": "Calculated, not read from your documents" - seen live on `bfa8711d` (P3) | The effective date is already past on a QUOTE (an older dec; the owner's 29 Sep rule) |
| 5 | "Contacts are in the dec" | **Declined - explain** | The dec prints no insured contact (all 271 pages) | Ask Michelle whose contact she means (Erin Royal? the producer?) |
| 6 | "Open to fix" on the driver warning | **Done, seen working** | Fix round: an offline end-to-end proof (125 alone: the card's table is served, one saved driver is stored, the warning clears) | - |
| 7 | Page-one carrier; the dec agency's phone | **Partly done** (1 Oct build: phone formatted, Agency Address in Account Settings - R7a) | Both EMC companies print on CARRIER; fix round: always in the same order (alphabetical) | Brent has not approved two carriers. Michelle's account has NO Contact Phone (set it before her run). Producer mailing address blank |
| 8 | Premiums did not attach, no prompt | **Done, seen working** | Line premiums and POLICY PREMIUM print; a blank one is a Missing row. Fix round: the list opens by default; a typed premium prints "3,418" (with cents too) | They are the EXPIRING premiums (Brent not asked) |
| 9 | Missing / required / verify in the side panel, earlier | **Done, seen working** (moved up 1 Oct) | Side panel per form; pre-form key details clickable. "AI held back" never repeats a refused answer - seen live on `bfa8711d` (P2). After the retest (owner): both lists start CLOSED like every other section; the applicant's steps are their own group | R2: the owner's layout change, not yet seen |
| 10 | Make Edit obvious; double-click to edit | **Done, seen working** | Typed edits are saved before a form switch, a fix window, a download or a new package; closing the tab asks first and still sends them - seen live on `bfa8711d` (E1-E4). The pending-edits note now reads "... from the last save. Save to update." (owner) | R3: the note's new words |
| 11 | Policy period and premium | **Done, seen working** | As 4 and 8 | As 4 and 8 |
| 12 | Tenant, not owner; revenue "$0" | **Declined - explain** | Tenant is a producer card; "$0" not built (ACORD asks for the location's revenue) | Tell Michelle why; INSIDE city limits is never filled |
| 13 | GL code, SIC, NAICS; FEIN | **Partly done** | GL CODE 91580, 91585; the auto class 7383 appears nowhere on the 125 and in no "AI held back" row - seen live on `bfa8711d` (W7) | SIC / NAICS are not in the dec (ask Michelle which page); LLC members blank |
| 14 | Send the 125 to the client; applicant signature | **Done, seen working on localhost** (signature prints after the client submits; download and edit-after-signing tried; the producer cannot edit the client's signature) (owner: built in, same draw / upload pad, as a PRE-TICKED questionnaire question asking ONLY for the signature - R9) | A question in Send to Client; the client draws or uploads their signature; recorded after their answers apply; the signature prints on the application's signature lines only (read off the printed forms - never initials, never 130's Minnesota attestation), dated; locked to what was signed; stored encrypted | Live retest R9; Brent never asked whether carriers accept a built-in signature; the cover prints no "signed" line |
| 15 | "No known losses" still counts | **Done, seen working** | Loss History becomes Not Applicable and reads "Attested - no known losses"; unticked it reads "Unknown", never "Prior claims known" - seen live on `bfa8711d` (C1, C2) | Lowers weak and some 1-5 year packages: tell Brent |
| 16 | A resolved hard stop moves to Reviewed | **Done, seen working** | Fix round: a handled stop's sentence prints once, on its Reviewed row | Live retest |
| 17 | Green "Client" boxes filled by the producer | **Partly done** | A box is green only while the client's value is in it - the client's FEIN printed green on `bfa8711d` (Q5) | The retype half (green goes away) not yet reported |
| 18 | Yes / No not editable on 126 / 127 | **Done, seen working on localhost** (owner, 1 Oct night: a Y/N box is highlighted ONLY when it holds an answer, in that answer's own colour - R10b passed) | Every Y/N question is editable (owner checked); an answered one wears its answer's colour (client green, AI-OK pink, verify orange); a blank one is plain and not counted; no Y/N colour of its own | The client half was declined (owner); about 181 of 190 Y/N answers open blank |
| 19 | Each item: what, how, score effect | **Done, seen working** (moved up 1 Oct) | Every box in the form's words with what to do and its score effect; ONE number per card - the loss card +7 on all five forms and "Answering this adds +7 pts" in Best Solutions, seen live on `bfa8711d` (P5, P6); the wrong Emcasco row is gone (W3). After the retest: the cover prints each card with the panel's own number and hedge | D1 (the download review window) not yet reported; R4 |
| G1 | E-mail tagline | **Done, seen working** | Also in the plain-text part of both client e-mails; the heading seen again on `bfa8711d` (Q2) | Deploy |
| G2 | Landlord name and address | **Done, seen working on localhost** (1 Oct night: client picks Tenant -> landlord asked -> prints on 125 page 3) | Prints on 125 ADDITIONAL INTEREST row A; fix round: as typed ("CBRE Group Inc", not "Cbre") | The client path never ran live; not on the ACORD 25 holder; nothing with 2+ locations |
| Q | Questions vs check items | **Done, seen working on localhost** (owner, 1 Oct night: header, check items, Tenant follow-ups and the end summary all counted apart) | Counted apart everywhere - the client's end summary read "1 of 7 questions answered - 3 of 4 details checked" on `bfa8711d` (Q3) | The client's header / ring / chips and the producer's receipt not yet reported |

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
  "two EMC companies" question - ANSWERED by Brent 8 Oct: neither prints in the top box (part U).

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

#### The owner's build of 1 Oct (after grading the 22 points) - DONE OFFLINE, retest R7 next

The owner picked three of the five "fix cleanly without their input" items (16 and 2's wording / dashboard: leave as
they are):

1. **Item 7 - the producer block.** The account's Contact Phone printed as typed ("7983789751"). The display formatter
   had no phone rule at all: now a BARE run of 10 digits (or 1 + 10) prints `798-378-9751` in every phone / fax box on
   every form (17 box families); anything written with separators, "+", or an extension prints exactly as written.
   **Account Settings gains "Agency Address"** (Street, City, State ZIP): stored on the account (`users.agency_address`,
   created and migrated by `init_db`), read with the account at extraction, and printed through the existing producer
   mailing block (line one / two, city, state, ZIP). A document's own producer address for the login's agency still
   wins; another agency's is recorded as the expiring one. Found on the way: an Indian PIN in an address ("UP 201301")
   printed state **DC** - the address parser let a ZIP "correct" the state; it now does so only for a US ZIP against a
   US state (the MO -> CO correction still works).
2. **Item 18 - Yes / No questions highlighted while viewing.** An unanswered question is tinted and outlined in view
   mode too (it was edit mode only), with a legend chip "Yes / No question not answered yet" beside "Double-click any
   box to edit it". Edit mode is unchanged.
3. **G2 - the landlord, as a follow-up, for each location.** Before: asked only when Tenant had been confirmed before
   sending, and only on a one-location 125. Now:
   - the landlord's name and address go out as FOLLOW-UPS of the "own or rent?" question: hidden until the client
     picks Tenant, gone again if they pick Owner (`services/follow_ups.py`, its JS twin `utils/followUps.js`);
   - with two or more locations, each location whose interest is unknown is asked by its own address, with its own
     landlord follow-ups; a location already known to be rented is asked its landlord directly;
   - the producer's Send to Client list shows the follow-ups under their parent ("If the answer is Tenant, also asks:
     ..."), never as separate ticks; they go with a ticked parent, straight after it;
   - one rule decides what the client saw, for the page, the receipt and its counts, the send and the apply step: a
     hidden follow-up is not validated, not counted, not on the receipt and never applied, whatever a payload says;
   - per-location answers are written onto that location's row; only that row's interest boxes re-stamp (labelled the
     client's), never the documents' addresses; ACORD 125's one ADDITIONAL INTEREST row prints the landlord when exactly
     one location has one (with its LOC #) - several are kept for certificates, not squeezed into one row.

**Evidence (offline):** `tests/test_owner_asks_1oct.py` (78: phones on all 17 box families, the profile route with a
stubbed database, the account load, the producer routing, the address in its boxes, the ZIP rule, follow-up rule /
bounds / 30 seeded orderings, one location and four-location question sets, the receipt, the real apply step end to end
for two locations and for one, the node twin); switching the follow-up gate off fails 3 of them. Two old pins updated
with the owner's reversal (`test_viewer_items_10_18_30sep.py`: Y/N tint "only in edit mode"; `test_step2_orbin_29sep.py`:
"only the interest question"). Replay of 34 stored sessions plus today's two: **3 boxes change, all bare-digit phones
now formatted (798-378-9751, 112-233-4455); 0 scores, 0 side-panel counts.** FR125: its two rented locations (rows 1, 3)
now get optional landlord questions; its forms are untouched. Lint 74 = baseline, 0 errors; build clean. Full suite:
**11,612 passed / 1 failed / 19 skipped** (the known `test_arq_acord125_missing_only`). The run first showed
11,611 / 2: the second was `test_brent_prep_fixes_15sep` pinning the account profile's exact keys - the new `address`
key is intended, so the pin was updated (and now also checks a stored address); re-run, it passes.

**Retest R7 (restart the backend; hard-refresh):**

| ID | Do | Pass when |
|---|---|---|
| R7a | Account Settings: Agency Address `1450 Larimer St, Suite 210, Denver, CO 80202` (any real address), Contact Phone as digits only; Save. Then a NEW package from the dec, generate the 125 | Page 1 AGENCY block: the address in its boxes (line, suite, city, state, ZIP) and the phone as `798-378-9751` |
| R7b | (superseded 1 Oct night - the owner removed the Y/N highlight; see R10a) | - |
| R7c | Same package: Send to Client. Find "Premises interest - owner or tenant" | The card says "If the answer is Tenant, also asks: ..." and the landlord is NOT a separate tick |
| R7d | Tick it, send to yourself, open the link | Choose **Owner**: no landlord questions. Choose **Tenant**: two landlord questions appear just below, indented. The header count moves with them |
| R7e | Answer Tenant, a landlord name and `100 Main St, Austin, TX 78701`, submit; back in the editor, Refresh | The client's summary lists exactly what was shown. 125 page 2: the premises TENANT box ticked (green). 125 page 3 ADDITIONAL INTEREST row A: the landlord, OTHER "Landlord", CERTIFICATE ticked, LOC # 1 |
| R7f (optional) | A package with two or more locations | Each location with no stated interest is asked by its address, each with its own landlord follow-ups |

### Items 1 and 14 - built 1 Oct 2026 night (owner's approvals of 1 Oct), offline; retest R8 / R9 below

**Item 1 - a package click lands on the package page.** Owner's decisions: the page always opens first; its button is
"Continue where you left off" once forms exist or are being generated, else "Continue to form selection"; after
generation the score reads "Total Package Score" (no "It can change when forms are generated"); before, "so far"; the
re-reading actions are off once forms exist, with "Forms are generated - make changes in the form editor."; a run that
did not finish says "Generation didn't finish"; the generated forms are listed under Key Details with an Open link.
- **One door for "is this package's generation running?":** `services/generation_state.py`. A live run proves it is
  alive with a heartbeat (the sync route and the worker re-stamp the job every 30 s through `JobQueue.touch`, which never
  touches a finished job); a processing job silent for 5 minutes died with its process. Until now a dead sync run left
  its job "processing" forever: every reopen spun for 5 minutes, then dropped the producer on the upload screen (the
  restore was handed a signal the 20 s timer had already aborted - fixed too). A crashed run now marks its job FAILED.
- GET /api/session returns `generation_state`, `form_order` (the producer's order; the row's JSONB sorts ACORD_25
  before ACORD_125) and `active_form_id` - the form LAST OPEN, recorded on every form switch
  (POST /api/session/{id}/active-form, one owner-scoped JSONB key, `updated_at` untouched). The earlier claim "the
  session already stores it" was wrong: it held the first form only, written once at generation.
- **Server locks (409), mirroring marketing-reason:** reclassify / exclude / supporting-only, confirm-value, integrity
  resolve and select-forms-bulk refuse once forms exist or while a run is live (`_refuse_once_forms_exist`). They re-read
  the documents and never touch existing forms; on a generated package they also emptied `selected_form_ids`. An
  interrupted run is not live, so "Continue to form selection" can generate again. The editor's add-form path
  (resolve-issue `add_form`) is untouched; the package page's "Add form" row button now opens it after generation
  (it used to jump to form selection - also from the editor).
- A fix made on the package page after generation refreshes its Key Details list (`_package_page_key_details`).
- Frontend: `utils/packageGeneration.js` holds the states and the wording for both layouts (rail and classic).
  The URL path into a package (the "client answered" e-mail, sign-in return) still opens the forms - on the last form.
  Essentials / lite untouched.

**Item 14 - the applicant signs through a link.** Owner: built in, the same draw-or-upload pad the producer uses.
- The producer: "Send for Signature" under "Send to Client" in the editor (shown when a generated form has an applicant
  line). Pick the forms, the client's e-mail; the client gets "Review and Sign". One live link per package (a new one
  replaces any pending). The side panel's "Applicant Signature" section shows each form: "Signed on 10/01/2026 by
  ...", "Not signed yet", or "Signature no longer matches - send for signature again."
- The client (/sign/<token>, no sign-in): opens each form (read-only PDF), ticks "I have reviewed these forms ... true,
  correct and complete ...", types their full name, draws or uploads (PNG/JPG, 2 MB). Sign is enabled only after every
  form is opened. Signs once; expired / replaced / already signed say so.
- **Which lines get the signature, read off the printed forms (no list):** an applicant signature box whose own cell
  label says SIGNATURE, dated in the applicant date box on the same row. All 13 applicant forms; never initials (each
  is a legal choice - UM rejection, credit notice); never ACORD 130's Signature_A, which is the Minnesota "I have no
  employees and an estimated exposure of zero" attestation under the same tooltip as the real line (Signature_B).
  The date is the signer's local date (browser offset, bounded).
- **Locked to what was signed:** each form records the fingerprint of its values (signature boxes excluded) as the
  client reviewed it. A save with no change keeps the signature; any changed value (an edit, a questionnaire answer, a
  fix) stops painting it and the producer is told to send again. The client page refuses to sign forms changed after
  it was opened ("Please review them again").
- **Stored encrypted** (signature_requests row and the session row), checked (real PNG / JPEG by magic bytes, size,
  pixel cap, not blank), re-encoded as PNG and trimmed to its ink (a 440 x 140 pad signature fills the 12 pt line).
  Never in plaintext, never in an answer, never counted as a question. Account deletion deletes the requests.
- Painted by the one render door every view and download already uses, plus the save and the producer's Sign button,
  so neither drops it. The viewer draws nothing over a painted box; the side panel's "To be signed by the applicant"
  rows go once signed.
- Activity Log: "Sent for signature", "Client signed" (added to the producer's feed on purpose). E-mails: the client's
  request and the producer's "signed" notice (names escaped).
- The shared pad also fixes strokes landing off the finger on a phone (the producer's pad had the same bug).

**Not done / decisions left:** Brent has not been asked whether carriers accept a built-in signature (the owner chose
built-in). Initials and the 130 Minnesota line stay for the applicant to complete by hand. The cover page does not
print a "signed" line.

**Evidence (offline):**
- New tests: `tests/test_package_page_1oct.py` (64: the state door on every job state and timestamp shape, the heartbeat
  on the real queue backends - never overwriting a finished job, the 409 locks on all five writers and their order,
  GET /api/session order / last form / the raced completed job, the active-form endpoint and its SQL, the frontend
  helper run in node, both layouts) and `tests/test_applicant_signature_1oct.py` (70: the lines on all 17 REAL
  templates, 130's Minnesota line, row pairing, the fingerprint, picture checks, the signing date, one-time signing
  with every refusal writing nothing, painting on the real 125 / 130 / 131 / 137_CO with and without the producer,
  stale forms, the side panel, the HTTP edge, the screens).
- The new SQL ran on the real Postgres inside a rolled-back transaction (temp table): the claim is atomic - a second
  sign on the same link returns nothing; the active-form UPDATE and the heartbeat UPDATE plan cleanly (EXPLAIN).
- Tests changed on purpose (each says so in place): `test_step2_orbin_29sep.py` (the rail footer label is now
  `scoreHeading(...)`; an editor reply now carries Key Details), `test_item16_reviewed_30sep.py` (same),
  `test_h7_audit_history.py` (the Activity Log shows 11 event types - the two signature events added on purpose),
  `test_final_run_fixes_30sep.py` / `test_viewer_items_10_18_30sep.py` (the overlay and double-click skip a painted box).
- Full suite after the question rework and the review fixes: **11,762 passed / 1 failed / 19 skipped** (after the owner's 1 Oct night round, incl. the G2 and Y/N fixes; the known
  `test_arq_acord125_missing_only`; `test_owner_asks_1oct.py` pinned the old submit line - the marker is added on
  purpose, the TEST changed). Lint 74 = baseline, 0 errors; build clean.

**Retest R8 - item 1 (restart the backend; hard-refresh):**

| ID | Do | Pass when |
|---|---|---|
| R8a | Dashboard: click a package that HAS generated forms | The package page opens (not the editor). Button: "Continue where you left off". The score card reads "Total Package Score" with no "It can change when forms are generated". Under Key details: "Your forms", each with its score and an Open link |
| R8b | Click Open on the 3rd form. In the editor switch to another form, go back to the dashboard, click the package, then "Continue where you left off" | The editor opens on the form you were last on (not the first form) |
| R8c | On that package page: Documents, then Data Consistency (if it has conflicts) | The type picker, Exclude / Include and Supporting only are greyed with "Forms are generated - make changes in the form editor."; Confirm is off. Review data still works. A hard stop's "Open to fix" still works |
| R8d | Click a package with NO forms yet | Exactly as before: "Continue to form selection", the score "so far" with its note |
| R8e | Start generating a package, open the dashboard in a second tab and click that package while it runs | The page says "Your forms are being generated."; "Continue where you left off" shows the progress screen and then the editor |
| R8f | Start generating, stop the backend (Ctrl+C) mid-run, start it again with `GENERATION_STALE_AFTER_SECONDS=60`, wait a minute, click the package | "Generation didn't finish. Continue to form selection to generate the forms again." - never a spinner; generating again works |

**Retest R9 - item 14, as a questionnaire question (RESTART the backend - it creates `signature_requests`; hard-refresh):**

| ID | Do | Pass when |
|---|---|---|
| R9a | Editor: Send to Client | Applicant Information lists "Please sign your insurance application." - **ticked by default**. No "Send for Signature" button anywhere |
| R9b | Send it to your own e-mail, open the link (also once on a phone) | The question shows ONLY the signature pad (Draw / Upload Image) - no forms list, no consent box, no name. Drawing follows the finger; a phone photo uploads |
| R9c | Draw a signature, answer one other question, Submit | "Thank You!"; the summary lists the signature question as "Signed" and counts it as a question |
| R9d | Editor: refresh; open the 125's last page | Side panel "Applicant Signature": "Signed on <date> by <the name you sent the questionnaire to>". APPLICANT'S SIGNATURE shows the signature, DATE the date - even though your other answer changed the form; the producer's line is untouched; no "To be signed by the applicant" rows |
| R9e | Download the 125 | The signature and the date are in the PDF |
| R9f | Change any value on the 125 and save | The signature disappears; the panel says "Signature no longer matches - send for signature again." |
| R9g | Send another questionnaire, leave the signature BLANK, submit | Nothing is signed; the earlier signature (if still valid) stays |

**Owner, 1 Oct night: "i dont need a new send for signature button, we need to send it as a question along with
other questions" - DONE.** The signature is now ONE question in Send to Client ("Please review your completed
application forms and sign them."), offered (not pre-ticked) whenever a generated form has an applicant line. The
"Send for Signature" button, its window, the standalone /sign page and the request e-mail are gone; the side panel's
"Applicant Signature" status stays.
- Send: the question is rebuilt from the session (never trusted from the request) and gets its own signing request;
  its token rides the stored question (`arq_routes.send_arq`, `client_view`).
- The client: the question shows the forms (View form), the consent box, their name and the pad (draw / upload).
  Submit sends the signature FIRST (its own endpoint - an image cannot ride a 500-character answer), then the
  answers with the "signed" marker. The marker is kept only when the signature is really stored; it is never
  stamped on a form box; the receipt shows "Signed" and it counts as a question.
- **The signature is recorded on the forms AFTER the client's answers are applied** (`applicant_signing.finalize`
  in the submit route), so it covers the forms as they print with the client's own answers in - signing before the
  answers would have made every signature stale at once. Recorded once: a later call never re-validates.

**Owner's live check, 1 Oct night (session `55325284`) - three changes and one bug:**
- **The bug: the drawn signature never reached the form.** The stored data showed why: the signing request was still
  `pending` and the questionnaire answers carried no signature - the client page counted the signature as ready only
  once every form was opened, the consent box ticked, a name typed AND a signature drawn, and with any one missing
  Submit went ahead WITHOUT it, silently. The question is now just the pad (below), so a drawn signature is always
  sent. Replayed offline on that session's real 125: signed, painted on APPLICANT'S SIGNATURE, dated 10/01/2026.
- **Pre-ticked** like the critical questions (`force_preselect`, the owner-decision flag the selector already reads).
- **Only the signature** (owner: "remove this section, just ask for signature, either to draw or to upload pic"): no
  forms list, no consent box, no name. The signer is recorded as the person the questionnaire was sent to; a consent
  is recorded only if a page sends one. The two public "view" endpoints (forms list, form PDF) went with it - only
  `POST /api/applicant-sign/sign/{token}` stays public.
- **Yes / No boxes are no longer highlighted** (owner: "why are all these y/n fields highlighted, remove it") - no
  tint, no outline, no legend, in either mode. They stay editable. Reverses the item 18 view-mode highlight (R7b).

**Adversarial review (5 reviewers + 5 skeptics): 38 findings, 29 confirmed, all fixed or logged.**
Fixed:
- A failed / refused Generate re-reads the package (a run still going opens the progress screen, a finished one the
  editor) instead of inviting a retry the server refuses; the e-mail / URL resume does the same.
- While a run is live, resolve-issue / reopen-issue refuse with 409 (the run stamps from older facts; a fix would
  sit in the facts with no box showing it).
- A run that made no forms keeps its marker ("Generation didn't finish"); the heartbeat beats on the wall clock (a
  sleeping Mac no longer reads a live run as dead).
- No dead "Fix in Data Consistency" / "Add form" once forms exist or are generating; locked items are not counted as
  "needs your input"; the running copy; no "Review Before Generating" banner after generation; a missing package
  score no longer leaves the pre-generation "so far" number on screen.
- Initials (UM rejection, credit notice) now count in the signed-form fingerprint - initialled after signing, the
  signature no longer matches. "Signed" is reported only when the image can be painted (another key / a rotation
  reads "send again").
- The client's review copy never shows an earlier signer's signature; it renders off the event loop; a deleted
  package reads "not found". Signature images are never retired from the session.
- Deleting a package deletes its signing requests and its PDFs - and only the OWNER's: the PDF delete used to run
  for any session id (pre-existing). Account deletion also deletes the rendered PDFs (they can carry signatures).
- The pad keeps its shape (a stretched canvas distorted the stored signature); a phone photo is scaled down to
  1600 px in the browser (the server's 4000 px cap was hit only at Sign).
- After a save, the viewer re-reads its boxes and the panel its signature status.
Logged, not fixed: `scripts/rekey_encryption.py` does not re-key the two new signature stores (after a key rotation
they read "send again"); ACORD 130's always-required applicant box is still the Minnesota line in the side panel and
the viewer's yellow (pre-existing - the PAINTING is right).

**Owner's retest, 1 Oct night (localhost): PASSED** - the client's drawn signature prints on the 125's applicant
line after a refresh (R9c-d), and no Yes / No box is highlighted (R10a). Item 1 (the package page, R8) also verified
working by the owner. Not yet reported: R9e-g (download, the stale message after an edit, a blank signature).

**Retest R10 (same restart):**

| ID | Do | Pass when |
|---|---|---|
| R10a | (superseded by R10b - the owner wants answered ones highlighted) | - |
| R10b | Open the 126 (or any form with Yes / No questions); then Edit form, type Y in a blank one, then clear it | A blank Y/N box is plain (no yellow, no amber), an answered one wears its answer's colour (green / pink / orange), no blue anywhere; the toolbar's Required count does not include blank Y/N boxes; Y/N boxes stay editable |

### Grade of Michelle's 22 points - 1 Oct 2026, late night (after items 1 and 14 verified on localhost)

- **Done (8):** 1, 2, 3, 6, 9, 10, 16, G1. (18 seen working too - listed with its catch below.)
- **Done, with a catch (7):** 4 (the proposed effective date is already past on an older dec); 8 and 11 (the premiums
  are the EXPIRING ones - Brent not asked); 14 (tried live incl. download and edit-after-signing; the producer cannot
  edit the client's signature. Catch: Brent not asked whether carriers accept a built-in signature; initials and 130's
  Minnesota line stay manual); 15 (lowers weak and some 1-5 year packages - Brent not told); 18 (a Y/N box is highlighted
  only when answered, in its answer's colour, all editable - seen working; catch: the client never answers Y/N in the
  questionnaire, owner's call); 19 (the
  download review seen live; catch: the premises "own or rent?" is asked twice there).
- **G2 is done too** (seen working 1 Oct night; catch: several landlords on one 125 and the ACORD 25 holder are not
  built). **Q is done** (client side seen working 1 Oct night; the producer's receipt should read the same numbers).
  **Left (5):** 7 (tell Brent); 13 (confirm with Brent); 17 (retype half - check: on session `55325284` retype the
  landlord ZIP 7870 -> 78701 on 125 page 3; the box loses its green, "12 Client" -> "11 Client"); was: Q (the client's header / ring and the producer's receipt not yet reported); 5 and 12 declined (tell
  Michelle - above).
- **Fixed from the download window (1 Oct night):** a FALSE "shows 798-378-9751 but the source value is 7983789751" -
  `field_qa._value_matches` compares a phone / fax by its digits now. Checked, NOT a defect: "Prior claims are known"
  - the client answered "Yes - we have had claims or losses".
- Everything is localhost only: nothing since `4f7e7db` is committed or deployed, so Michelle sees none of it.

### Owner's decisions on the open points - 1 Oct 2026, late night

- **2:** done - the forms-first wording stays for now.
- **7:** tell Brent (two writing companies printed on page-one CARRIER, "; "-joined; Michelle's ThinkSmith account has
  no Contact Phone - set it before her run).
- **13:** SIC / NAICS are entered by the producer and are not on dec pages - confirm once more with Brent.
- **18:** built - a Y/N box is highlighted only when answered, in its answer's own colour (no blue), blank ones plain,
  all editable (R10b). Tell Michelle the colours.
- **5, 12:** declined - tell Michelle why (below).

**How to check 17 (green "Client" boxes - the producer-retype half):**
1. Open a package whose client answered the questionnaire (session `bfa8711d` - its FEIN `42-3456790` prints green on
   the 125, page 1).
2. Note the toolbar's "N Client" count. Press Edit form, type a different FEIN (e.g. `42-1111111`) over the green box,
   Done editing - save.
3. Pass: the box is no longer green (a plain producer value), the "Client" count drops by one, and after Refresh it
   stays that way; the side panel does not call it the client's. (Typing back the client's exact value is not an edit:
   it stays green.)

**G2 live check, 1 Oct night (session `55325284`) - FAILED, fixed offline:** the client picked Tenant and nothing
appeared, and the producer's card had no "If the answer is Tenant, also asks" line. Cause: the list already held "own
or rent?" from another question generator, and `_maybe_inject_premises_questions` added the landlord follow-ups ONLY
when it created that question itself - so on this package they were never generated. They now attach to the interest
question whoever added it (one-location and per-location alike); replayed on `55325284`: `landlord_name` /
`landlord_address` now go out as follow-ups of `premises_interest`. Test:
`test_the_landlord_follows_an_interest_question_another_generator_already_added`. **A questionnaire sent BEFORE the
fix keeps its old questions - send a new one to re-check.** **Re-checked live the same night: PASSED** - Tenant showed
the two landlord questions; after submit the 125 printed TENANT (green) on page 2 and, on page 3 row A, CBRE Group Inc /
100 Main St / Austin TX, OTHER "Landlord", CERTIFICATE, LOCATION 1. Notes: the ZIP printed "7870" because the client
typed four digits (a landlord ZIP is not length-checked); the client's "You may also need to provide supporting
documents" is correct here - the client had answered "Yes - we have had claims or losses", so loss runs are owed.

**How to check G2 (the landlord, from the client):**
1. Send to Client with "Premises interest - owner or tenant" ticked (Locations group). Its card says "If the answer is
   Tenant, also asks: ...", and the landlord is NOT a separate tick.
2. Open the link: pick **Owner** - no landlord questions; pick **Tenant** - "landlord's name" and "landlord's address"
   appear just below, indented.
3. Answer Tenant, `CBRE Group Inc`, `100 Main St, Austin, TX 78701`; submit; in the editor press Refresh on the 125.
4. Pass: page 2 premises TENANT ticked (green); page 3 ADDITIONAL INTEREST row A prints the landlord, OTHER "Landlord",
   CERTIFICATE ticked, LOC # 1.
5. Two or more locations (needs a package with 2+ premises): each location is asked by its address with its own
   landlord follow-ups (R7f). Correction to the earlier grade: per-location asking IS built; what is not built is
   printing several landlords on the 125 (one row prints only when exactly one location has a landlord) and the
   ACORD 25 certificate holder.

**For Brent:** (1) two writing companies on 125 page-one CARRIER, NAIC / POLICY NUMBER blank; (2) the page-one premiums
are the EXPIRING ones on a dec renewal; (3) SIC / NAICS are producer-entered (confirm); (4) "No known losses" lowers
weak and some 1-5 year packages; (5) carriers accepting the built-in applicant signature; (6) the D6 note on card
numbers and dismissal credits.

**For Michelle:**
- **Item 5 ("contacts are in the dec"):** all 271 pages were read: the dec prints no insured contact person, phone or
  e-mail. The only person named is ERIN ROYAL under the auto "NAMES OF INDIVIDUALS" (a drive-other-car listing, not a
  contact), and the only phone numbers are your agency's (303-996-7800) and EMC's claim lines. Erin's 303-521-0561 and
  erin@orbin.com came from the questionnaire. Ask which page she means.
- **Item 12 ("tenant; revenue $0"):** the dec never calls Orbin a tenant (the word appears only in policy wording), so
  Primble asks the client "own or rent?" (and the landlord when they rent). The 125's ANNUAL REVENUES box asks for
  "the annual revenue amount for this location" - the business's revenue at that premises, not the building's - so a
  one-location business prints its total revenue there, never $0.
- **Item 18 (Y/N colours):** a Yes / No question is highlighted only once it has an answer, in the colour of who
  answered it - green the client, pink AI-filled and found in your documents, orange AI-filled to verify; an
  unanswered one is plain; double-click any box to change it.

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
- **Items 1 and 14 built (1 Oct night, owner's approvals)** - see "Items 1 and 14" above; retest R8 / R9 / R10. Item 14
  is a pre-ticked questionnaire question asking only for the signature; the Y/N highlight is removed (owner).
- **Not touched (on purpose):** 5 and 12 (need Michelle), item 2's forms-first wording, item 18's client half (owner
  declined), the location-table edit that wipes LOC # / county / revenue (logged), and the question 4 policy order.
