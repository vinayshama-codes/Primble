# Live run 4 - real Orbin package (merged from the five 14 Sep chats)

Fill in the Result column (PASS / FAIL + what you saw) and send it back. Row IDs are
stable so "E3 FAIL, shows 104" is enough. "Prob" = the problem number from the chat prompts.

## Before you start
1. Commit the tree first.
2. Backend `.env`: `PURGE_DEC_INDEX_AFTER_GENERATION=0`. Leave `GAP_FILL_LINE_SCOPE` unset (default on).
3. **The producer now follows the login.** The producer block prints the logged-in account's
   `organization_name` / `full_name`. To match the client's view, set your test user's row to
   `ThinkSmith Agency LLC` / `Michelle Smith`. Otherwise read "ThinkSmith / Michelle Smith" below
   as "my own account's org / name".
4. **FRESH upload** of all three documents as ONE package: the 271-page policy, the COI, the
   narrative. Do not re-run an old session - extraction must run at v21, and old sessions carry
   stored confirmations ($1,000,000, IM 7100 06 04, CRS) that hide the fixes.
5. Keep the backend log for the whole run.
6. Select 125, 126, 127, 131 and 137 CO.

## A. Form selection
| # | Prob | Where | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| A1 | 9 | Recommended forms | 125, 126, 127, 131 Required; 137 CO + 25 Needs Confirmation; 186; 160 (known wrong form - leave) | ACORD 130, 140 or 141 offered | |
| A2 | 10 | 137 CO card evidence | auto liability limit $ 1,000,000; UM/UIM $ 1,000,000 | "Contractor type: commercial general contractor" | |

## B. Data Consistency
| # | Prob | Where | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| B1 | 6 | Policy Number | scoped, no card: BBC7263-26 (GL), 6E7-40-02---26 (Auto), 6C7-40-02---26 (IM), 6J7-40-02---26 (Umbrella) | a card; IM 7100 06 04 / IM 7201 10 02 / CU7001A 11-15 / IL 71 31A 04 01 offered | |
| B2 | 6 | Carrier NAIC | scoped: 25186 GL; 21415 Auto / IM / Umbrella | "25186 vs 21415" card | |
| B3 | 8 | Umbrella Limit | read-only "Changed during the policy term - not a conflict"; Now $1,000,000 effective 7/25/25 (COI); Before $ 3,000,000 (policy) | "$3,000,000 vs $1,000,000" card asking to confirm | |
| B4 | 7 | GL form type | no card | "CG 00 01 04 13 vs OCCUR" | |
| B5 | 11 | Producer Name | no card | COMMERCIAL RISK SOLUTIONS, INC. vs CRS Insurance Brokerage | |

## C. Warnings / hard stops (pre-form)
| # | Prob | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|
| C1 | 1 | PRESENT: soft "Policy term already expired (07/15/2026) read from an uploaded policy document" (owner ruling: printed term stays) | missing, or dates shifted to 2026-2027 | |
| C2 | 14 | PRESENT: "Driver schedule not provided - list the drivers of the scheduled vehicles..." (the policy schedules no drivers) | missing | |
| C3 | 8 | ABSENT: umbrella limit "documents state different amounts" | present | |
| C4 | 11 | ABSENT: "Producer Name: documents disagree" | present | |
| C5 | 12 | ABSENT: "A certificate of liability was requested ... ACORD 25 is not in the selected forms" | present | |
| C6 | 7 | ABSENT: any claims-made / retro-date warning | present | |

## D. ACORD 125
| # | Prob | Box | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| D1 | 1, 2 | POLICY NUMBER | blank | IM 7100 06 04 | |
| D2 | 1 | PROPOSED EFF / EXP | 07/15/2025 / 07/15/2026 | 07/15/2026 / 07/15/2027 | |
| D3 | 1 | STATUS OF TRANSACTION - Renew | blank (producer ticks it) | ticked | |
| D4 | 9 | LINES OF BUSINESS | Business Auto 2,991; CGL 3,954; Inland Marine 300; Umbrella 3,418 - nothing else | Property, Crime or WC ticked | |
| D5 | 6 | Other Policy rows A-D | the four own numbers; row D = 6J7-40-02---26 | IM 7100 06 04, or blanks | |
| D6 | 11 | Producer AGENCY / CONTACT NAME | ThinkSmith Agency LLC / Michelle Smith | Commercial Risk Solutions / Terri Wroblewski | |
| D7 | 11 | Producer address / phone / fax / email | blank (expected - the account holds no address) | 9780 S Meridian Blvd / 303-996-7800 / twroblewski@crsdenver.com | |
| D8 | 12 | Additional Interest A / B | blank | For Informational Purposes Only | |
| D9 | known | package CARRIER / NAIC | Employers Mutual Casualty / 21415 - KNOWN OPEN, not a regression | - | |

## E. ACORD 126
| # | Prob | Box | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| E1 | 1, 3 | header CARRIER / NAIC / POLICY # / EFF | EMC Property & Casualty / 25186 / BBC7263-26 (or "BBC7263 - 26") / 07/15/2025 | Employers Mutual Casualty; blank; 07/15/2026 | |
| E2 | reg | GL limits | occ $1,000,000; agg $2,000,000; products $2,000,000; P&AI $1,000,000; premises $500,000; med $10,000 | any $3,000,000 | |
| E3 | 4 | hazard grid TERR, rows A and B | blank | 104 or 6679 | |
| E4 | 5 | hazard grid classes | 91580 (payroll $39,300) / 91585 (total cost $350,000) | an auto code (7383) | |
| E5 | 7 | Occurrence / Claims-Made | Occurrence ticked, Claims-Made not | Claims-Made ticked, or both blank | |
| E6 | 7 | PROPOSED RETROACTIVE DATE | blank | any date | |
| E7 | scope | Employee Benefits block | blank | $1,000,000 / "0 - 25" | |
| E8 | 11 | Producer | ThinkSmith Agency LLC / Michelle Smith | CRS / Terri Wroblewski | |
| E9 | 12 | Additional Interest | blank | For Informational Purposes Only | |

## F. ACORD 127
| # | Prob | Box | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| F1 | 1 | header | Employers Mutual Casualty / 21415 / 6E7-40-02---26 / 07/15/2025 | NAIC 25186 | |
| F2 | 5 | vehicle 1 | 2012 / SUBARU / OUTBACK SEDAN / 4S4BRCGC9C3217772 / CLASS 7383 / TERR 111 | class 91580, blank or 6679 | |
| F3 | 13 | vehicle rows 2+ | blank | a second Subaru, or $39,300 / $350,000 anywhere | |
| F4 | 14 | Driver_GivenName_A / Surname_A | blank | ERIN / ROYAL | |
| F5 | 12 | Additional Interest row A (name, city, acct no., rank) | blank | For Informational Purposes Only / Denver / 0482854 / 1 | |
| F6 | known | FARTHEST TERMINAL | may show 6679 - KNOWN OPEN | - | |

## G. ACORD 131
| # | Prob | Box | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| G1 | 1 | header | Employers Mutual Casualty / 21415 / 6J7-40-02---26 | 25186, or 6E7 number | |
| G2 | 8 | Umbrella each occurrence / aggregate | $1,000,000 / $1,000,000 | blank or $3,000,000 | |
| G3 | 1 | underlying Auto row | Employers Mutual Casualty / 6E7-40-02---26 | carrier or number blank | |
| G4 | 1 | underlying GL row | EMC Property & Casualty / BBC7263-26 | number blank | |
| G5 | 7 | Umbrella Occurrence / Claims-Made | Occurrence ticked, Claims-Made not | blank, or copied from the GL basis | |
| G6 | 11 | Producer | ThinkSmith Agency LLC / Michelle Smith | CRS | |

## H. ACORD 137 CO
| # | Prob | Box | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| H1 | 1 | header | Employers Mutual Casualty / 21415 / 6E7-40-02---26 | anything else | |
| H2 | 10 | Business Auto liability | CSL ticked + 1,000,000; BI each accident and PD blank | blank, or EACH PERSON ticked | |
| H3 | 10 | Med Pay | 5,000 | blank | |
| H4 | 10 | UM | CSL ticked + 1,000,000 (no UIM box on the CO form - correct) | blank | |
| H5 | 10 | symbol grid | 1 liability (A); 2 med pay (B); 2 UM (C); 7 comp (F); 7 collision (H); towing (E) blank | rows blank, or 1 on every row | |
| H6 | 10 | Truckers + Motor Carrier pages | completely blank | any value or tick | |
| H7 | 10 | hired PD comp / collision deductible | 1,000 or blank | any other amount | |

## I. Pre-download review (Field QA) and cover page
| # | Prob | Where | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| I1 | 6 | Field QA | no rows on Other Policy numbers, NAIC, or "source value is IM 7100 06 04" | those rows | |
| I2 | 7 | Field QA | no "PerLocation / PerProject shows No but source is $2,000,000"; no Claims-Made vs a form title | those rows | |
| I3 | 9 | Cover page LINES OF BUSINESS | Liability, Inland Marine, Automobile, Umbrella | Property, Crime, WC, Farm, Liquor, EPLI, OCP, Pollution | |
| I4 | fmt | every money box, every form | full amounts ("1,000,000") | "$1", "$5", or a glued "10,000,002,000,000" - KNOWN formatter defect, not fixed | |

## J. Send to Client - preview only
| # | Prob | Where | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| J1 | 13 | vehicle table | "We found 1 vehicle in your policy declarations. Please check it, correct anything that is wrong, and add any we missed." + the Subaru row | "Please list the vehicles to be insured" | |
| J2 | 13 | garaging | no "Where are your business vehicles primarily kept overnight?" | present | |
| J3 | 13 | loss table | after answering "No - no claims or losses in the past 5 years" on the loss card: no claims table | present | |
| J4 | 13 | location table | "We found 1 business location..." with 4800 DAHLIA ST # D13 / DENVER / CO / 80216-3121 | "Please list every business location" | |
| J5 | 14 | drivers | no "(Nth driver)"; one EMPTY driver table | numbered cards, or ERIN ROYAL pre-filled | |
| J6 | 9 | producer questions | no Employers Liability / WC questions | EL limit questions | |
| J7 | 15 | confirmations | "Add confirmations (N)" with ORBIN CONTRACTING LLC and 4800 DAHLIA ST # D13, DENVER CO 80216-3121 | missing | |
| J8 | 1-3 | after opening the questionnaire, download 125/126/127/131 AGAIN | every value in D-G unchanged | IM 7100 06 04 or 25186 comes back | |

## K. Client questionnaire (send to a test inbox)
| # | Prob | Where | Expected when fixed | Broken looks like | Result |
|---|---|---|---|---|---|
| K1 | 15 | name card | ORBIN CONTRACTING LLC with "This is correct" / "Change it" | empty text box | |
| K2 | 15 | vehicle table | "Everything here is correct" | empty table | |
| K3 | 15 | producer receipt after submit | "2 confirmed as correct"; name + vehicle table "Confirmed as correct" | "Not answered" | |

## L. Scores - write them down
Package ___  | 125 ___ | 126 ___ | 127 ___ | 131 ___ | 137 CO ___

Only one chat measured a score move (Chat 5: package 78 -> 75, ACORD 127 82 -> 77, from the driver
warning alone). The combined effect of all five is unmeasured - this run is the first measurement.
Brent sees these before anything ships.

## M. Backend log - grep after the run
| grep | Expected | Result |
|---|---|---|
| `combined_gap_fill: line-scoped groups` | present; four line groups, each far under the 711k-char document | |
| `LLM_SPEND stage=` | count the calls and note `cache_pct` (Chat 1 measured 205 -> 114 gap-fill calls offline) | |
| `line scoping unavailable` | absent | |
| `submitting account unavailable` | absent | |
| `named-individual separation skipped` | absent | |
| `calculate_package_sqs failed` | absent | |
| `UNKNOWN_KEYS` | few or none | |
| `TWO_COLUMN_REFLOW_ACCEPT` with `DIFFER` | just note the count (new logging) | |

## Known open - do not score as regressions
- 125 package carrier box shows one line's carrier (D9)
- 127 FARTHEST TERMINAL 6679 (F6)
- money formatter (I4)
- producer address / phone / email blank when the agencies differ (D7)
- 160 liquor aggregate; 126/25 aggregate "other basis" text box
- hired PD deductible still from gap fill (H7)
- 127 "PD per accident" asked on a CSL policy; loss-payee question says "property policy"
- a client edit to a pre-filled table applies immediately (flagged for the producer, not held)
