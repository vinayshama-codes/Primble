# 5 Oct 2026 - Form improvement: ACORD 125 / 126 / 127 (CH125 kit)

**Living file. Update it after every test run, fix, or decision.** Newest entries go at the top of each log.

## Why this exists
The client sent two docs (`125_reference/`, 8-19-26): the Vertafore data map and the "field completion"
rules. Question: have we reached that level? Answer on 5 Oct was **no**:
- **Values: close.** FR125 v2 reached 312/312, but only after 8 rounds of fixes on that same kit, so it proves the fixture, not generalisation.
- **Process: not met.** The client's blank-is-not-No flow, the four field states and NPN are not implemented.

## Client rules (the contract)
- Page 1 is the policy BEING APPLIED FOR:
  - carrier = the one receiving the submission
  - NAIC only if verified
  - status QUOTE
  - no policy number or premium on a new-business quote
- **Blank is not No.** An unanswered question means "UNRESOLVED - insured confirmation required", resolved through the client questionnaire *before* the submission-ready 125.
- Four states per field: VERIFIED / CONFIRMED / NOT APPLICABLE / UNRESOLVED. **Never ASSUMED.**
- Prior carrier: only the years the documents substantiate; REQUEST the missing ones.
- Loss history comes from verified loss runs:
  - "Check if none" only when the loss runs show none
  - a "no known losses" narrative never counts as a verified history
  - total = PAID
- Producer signature, printed name, state licence and NPN completed.

## Audit 5 Oct (code-verified, no changes made)
| Rule | Status | Where |
|---|---|---|
| Edition 2025/03 | MEETS | `pdf_service._form_edition_identifier` |
| Carrier / NAIC / QUOTE / no number or premium | MEETS, with edge gaps | Edge gaps: MGA "on behalf of" not handled; a "market this account" package is presumed a renewal and prints the incumbent; billing can leak from the incumbent dec (`_backfill_billing_plan`) |
| Blank is not No | HALF | Silence stays blank. But an unanswered Q shows nowhere: <ul><li>no tint</li><li>not in needs-attention (none of the 125's 16 question tooltips is "high-impact")</li><li>the field_qa row is dropped (`field_qa.py:787`)</li><li>never in the client ARQ (`arq_service.py:3452`, owner 25 Sep)</li><li>nothing blocks download</li><li>the score doesn't charge for it</li></ul> |
| No ASSUMED | GAP | <ul><li>Q4 ticked "Y" by inference (`pdf_service.py:3784-3792`)</li><li>AI text values "found in the docs" labelled `ai_verified` and scored 0.85</li><li>four states exist only in the audit export (`fact_state.display_state`)</li></ul> |
| Loss history | PARTIAL | <ul><li>zero-claim loss runs can't tick "none"; only a person can (`pdf_service.py:13531`)</li><li>a person's "no known losses" outranks listed claims</li><li>total falls back to INCURRED (`amount`) when paid is missing (`pdf_service.py:16083`)</li><li>no deterministic latest-valuation / period / entity filter</li></ul> |
| Prior carrier | PARTIAL | Substantiate-only holds; nothing requests the missing years |
| NPN / state licence | GAP | No field anywhere (`users` table, Account Settings), so always blank |
| Agency code / sub-code / customer ID | PARTIAL | Never filled (blocked at `pdf_service.py:21128`), never wrong |

## The CH125 kit - `ch125_test_data/`
**Account:** Cumberland Hearth & Hospitality Supply, Inc. (Nashville; wholesale kitchen equipment).
- Service subsidiary: Cumberland Hearth Service Co., LLC.
- Transaction: new business, QUOTE, to Ridgeline Specialty (NAIC 41297) through the MGA Appalachian Risk Underwriters.
- Proposed term: 12/01/2026 - 12/01/2027.
- Incumbents: Old Hickory (GL / auto), Magnolia (property), Cardinal (umbrella).

**PDF:** `CH125_cumberland_hearth_package.pdf`
- **Exactly 300,000 characters**, measured as `sum(len(page.extract_text()))` with pdfplumber.
- 59 pages, text only (no scans).
- Primble's own reader feeds the model about 439k characters, because it re-emits detected tables.

**Key:** `CH125_answer_key.json` decides every box; `CH125_ANSWER_KEY.md` is the human version.

| Form | Expect | Blank: no data | Blank: by rule | Not scored |
|---|---|---|---|---|
| 125 | 252 | 174 | 89 | 33 |
| 126 | 141 | 54 | 49 | 11 |
| 127 | 288 | 286 | 42 | 18 |

**Planted UNRESOLVED** (must stay blank and be asked):
- 125: Q7 (fraud / arson) and Q9 (foreclosure / bankruptcy)
- 126: recreation, lodging, pool, day care, promotional literature
- 127: "all vehicles part of a fleet"
- Also: the 2023-24 property premium (request it)

**Main traps:**
- MGA vs carrier
- incumbent renewal offer
- stale August worksheet vs CFO e-mail 09/30
- requested vs expiring (126 limits / deductible; 127 vehicle 4 collision deductible, towing)
- rescinded cancellation; corrected fire citation (Q8 = N)
- judgment WON by the applicant (Q10 = N); shareholder's trust (Q11 = N); drone sold (Q14 = N)
- 40% joint venture is not a subsidiary
- former name on the 2022 claim (include); 2020 claim and the JV's claim (exclude); three valuations of one claim
- head count / FT / PT / agency temps
- 18% / 17% of total sales vs "95% of calls"
- two premises numberings
- sold vehicles, terminated driver, closed location

**Hard formats:** X-in-column answers, drifting two-column layout, riffled tables, teletype, form boxes, OCR-garbled fax, rotated SUPERSEDED watermark, 5 date formats, $000s.

**Proved before use:**
- every expected value is printed and visible through Primble's reader
- every decoy is printed
- a perfect form scores 100%; an empty form has 0 violations

**Run / grade** (grade the stored session, not the PDF):
```bash
backend/.venv/bin/python ch125_test_data/grade_kit.py --list
backend/.venv/bin/python ch125_test_data/grade_kit.py --session <id> --label "CH125 - TEST N" --out ch125_test_data/runs/tN.md
# 125 in the FR125 format: dump_a125_run.py <id> > dump.json ; report_125_run.py --key ch125_test_data/CH125_answer_key.json --dump dump.json
```

**Rebuild:**
```bash
backend/.venv/bin/python ch125_test_data/generator/make_kit.py
backend/.venv/bin/python ch125_test_data/generator/write_docs.py
```
Use `make_kit.py --key-only` when only the key changed.

## Decision points (owner / Brent)
- **126/127 headers.** The key follows the client rule (Ridgeline, 12/01/2026, no policy number). The 15 Sep "section forms keep the current policy" rule may print the incumbent.
- **Unanswered Y/N questions.** Should they go to the client questionnaire (client rule) or stay producer-only (25 Sep decision)?
- **NPN / licence.** Add account-profile fields?
- **Q4 inference.** It is an ASSUMED value. Keep it or blank it?

## Test results log
| Date | Run / session | 125 correct / wrong / missing / made up | 126 | 127 | Unresolved kept blank | Notes |
|---|---|---|---|---|---|---|
| 5 Oct | Test 1 - in progress (pre-form screen) | - | - | - | - | Data Consistency findings below. Generate WITHOUT confirming anything (no human edits); Test 1b = the same session after confirming the four typed values |

**b601fad1 after the producer's actions (5 Oct 11:47-11:53 UTC).**
- 4 confirms SAVED - the `_fv` fix is LIVE-VERIFIED.
- But effective was typed **12/02/2026** (a typo; re-confirm 12/01/2026).
- 15 issues dismissed, 1 resolved (loss conflict).
- **Score still 60** (raw 78):
  - **Dismiss does not remove a stop or lift a cap** - by design: the credit goes to RAW and is clamped under the cap.
  - The cap is now the FALSE split-limit stop.
  - **"Business Income ... Period of Restoration" became a HARD stop after the confirm re-run.** The first upload demoted it to a warning pre-selection; the confirm path does not. Inconsistent re-run paths.
- Root-cause investigation of every false warning launched 5 Oct (rules + extraction + score refresh + post-generation fixing).

**Test 1 third upload - session b601fad1 (5 Oct 11:39 UTC, after the backend restart).** Pre-form score **60** = raw **78** capped by 2 hard stops; both stops come from wrong facts.
- **Invalid period.** expiration = 12/01/2026 = effective. Confirming 12/01/2027 clears it (offline replay: clears).
- **"Split liability limits incomplete" is FALSE.**
  - Auto liability is a $1,000,000 CSL.
  - `auto_bi_per_person` $1M / `auto_bi_per_accident` $2M were taken from GL / lease / subcontract "$1,000,000 / $2,000,000" text.
  - Dismiss it; never type split values.
- **SAME PDF, DIFFERENT FACTS run to run** (extraction is not deterministic across uploads):
  - claims 16 -> 3
  - property locations 5 -> **20**
  - dates 12/01/2025-12/01/2026 -> 12/01/2026-12/01/2026
- **New defects:**
  - **20 "insured locations":** the 40-row customer JOB SITE list became premises (the planted trap), plus "La Vergne depot" / "Franklin office" duplicates, so COPE "16 of 20 missing".
  - **`total_revenue` stored as "$18.6MM",** which the WC check parsed as **$19** ("payroll is 26442473% of revenue"). The currency parser has no "MM" suffix.
  - **WC flagged** (`has_workers_comp`) plus "multi-state WC payroll by state" (x2). WC is NOT part of this submission and is TN only.
  - **"Umbrella effective 12/01/2025 vs GL 12/01/2026"** - the expiring umbrella term compared with the proposed term.
  - **"ACV on a building valued $6,900,000"** - ACV is the VEHICLES' valuation report; property valuation is never stated.
  - **"Coverage part not recognised: Commercial Package"** - from the AMS export code `LOB=CPKGE` (the property policy).
  - **The whole PDF is classified `narrative`.**
  - **Still wrong:** `is_renewal` Y, `carrier_name` Old Hickory, `submission_carrier_name` Riverbend (the AGENCY).
- **Locked after generation (409):** reclassify and integrity resolve. (Data Consistency confirm is available after generation since 5 Oct - editor side panel.)
  - Also available after generation: the hard-stop / warning cards (Open to fix / Resolve / Dismiss), typing into a form box, recommendation cards, Send to Client.

**Test 1 rerun - session 41dab31c (fresh upload, 5 Oct 11:02 UTC), stored facts read from the DB.** The pre-form score was **80 "Almost There"** (fa2f62da had been capped at 60). **NOT an improvement:**
- fa2f62da had eff 12/01/2026 = exp 12/01/2026, an invalid period, so a HARD stop capped it at 60.
- 41dab31c has eff **12/01/2025** / exp 12/01/2026 - the EXPIRING term. Wrong dates, but a valid period, so the cap is gone.
- The score rewards consistency, not correctness; "13 of 13 key details" counts presence only.

Defects found in the stored facts (both sessions unless noted):
- **Receiving carrier = the agency.** `submission_carrier_name` = **"Riverbend Insurance Partners"**, because the MGA acknowledgement is addressed "To: Riverbend...". Ridgeline / 41297 missed. The `_addressee_from_text` reading of "To:" is wrong when the MGA writes TO the agency.
- **Treated as a renewal of the incumbent.**
  - `is_renewal` = Y
  - `submission_is_new_business` = None, though the e-mail subject says "NEW BUSINESS SUBMISSION" and the ack says "Transaction: New business - quotation requested"
  - `carrier_name` / `carrier_naic` / `policy_number` = Old Hickory / 27718 / OHM-GL-4471902-25
- **Loss figures wrong.**
  - `num_claims` = **16** (truth: 3)
  - `total_incurred` $52,167 (= the key's PAID total); `total_paid` $51,705
- **5 property locations.** Two are not locations: the CLOSED 1040 Visco Dr and the **P.O. Box** mailing address.
- **Loc 1 building value $4,880,000** = the balance-sheet cost (the SOV says $6,900,000).
- **A narrative became a package-wide no-loss attestation.** `narrative_states_no_losses` = True raised "a No Known Losses attestation conflicts with claims" and holds Loss History at 45. The source is "the umbrella has never had a claim" plus the SUPERSEDED 2024 app. This is the client's 8-19-26 rule broken in scoring form.
- **False warnings:**
  - "property deductible basis missing" - the Magnolia dec prints $5,000 AOP / 1% wind-hail
  - "ACORD 160 + 140 duplication" - inland marine is not requested; 160 is BOP (the known label bug)

**Producer actions:** confirm 12/01/2026, 12/01/2027, Ridgeline Specialty Insurance Company, 41297; leave Policy Number; Loss-history card -> "loss runs are correct"; dismiss the rest. Generate 125 + 126 + 127 only.

**Test 1 - Data Consistency screen (pre-form), 5 Oct.** 5 conflict cards; none of the offered values is right.
- Dates offered: 06/15/2026, 01/01/2026, 06/15/2027, 01/01/2027, 11/15/2026. These are the inland-marine and WC terms, plus the stale target date / renewal-quote expiry. The submission's 12/01/2026-12/01/2027 is not offered.
- Carrier: suggested Magnolia; also offered Cardinal and Tennessee Employers Mutual. NAIC offered: 15542, 39087, 11236. Ridgeline / 41297 (stated on the MGA acknowledgement) are not offered.
- Policy number: 5 offered, all other policies' (incumbents, IM, WC). New business has no number, the picker refuses an empty value, and `CONFLICT_WITHHOLD_KEYS` is empty, so an unconfirmed card stamps the SUGGESTED value.
- **Defects:**
  1. Out-of-scope lines (WC "not part of this submission", IM "not requested") are treated as rivals.
  2. "Policies in this submission" pairs Ridgeline with the INCUMBENT's numbers, two of them from the 2024 term (MUI-CP-0098817-24, CXS-UMB-220871-24). That is the C1 recombination class.
  3. Business Auto is missing from that table.
- **Producer answers for Test 1b:**
  - type 12/01/2026, 12/01/2027, Ridgeline Specialty Insurance Company, 41297
  - leave Policy Number unconfirmed

**Test 1 - issues found in the logs (session fa2f62da, 5 Oct).** The first two (the `_fv` crash and the dropped human answers) are **FIXED 5 Oct** - see the Improvements log. The rest are open.
- **BLOCKER - confirm returns 500 "Failed to confirm the underwriting value".**
  - `extraction_pipeline.py:1520` calls `_fv`, which is never imported in that file.
  - It runs only on a re-run (`session_id` set) when a Drive Other Car named individual was moved out of `auto_drivers`.
  - The kit's Margaret Ellison triggers it. Since 16 Sep (5a263e1).
  - Breaks every confirm / reclassify / integrity-resolve on such a package.
- **SILENT, worse - human answers dropped on every re-run since 24 Aug (4d80b9a1).**
  - `extraction_pipeline.py:580`: the same missing `_fv` inside a try.
  - The log says "human-fact preservation skipped"; V1 C1-D has never worked on a re-run.
  - Fix for both: `from services.extraction_service import _fv`, plus a test re-running a session that has a named individual AND a human fact.
- **The tester typed `01/12/2026`, which is 12 Jan 2026 (DD/MM habit).** Retry with 12/01/2026.
  - The confirm box gives no date-format hint and no sanity check.
- **HARD stop "Effective date is on or after expiration date" (caps the score at 60).**
  - Scalar dates come from different contracts.
  - 11/15/2026 (stale target date / renewal-quote expiry) is an expiration candidate.
- **SOFT "Umbrella and GL policy periods misaligned"** - 2024 and 2025 terms mixed.
- **`coverage_lines` FINAL:**
  - the requested lines carry no number
  - the prior-term numbers (-24) are attached to them
  - WC and IM are included

  This is the root of "Ridgeline + old numbers".
- **Dec index dropped 50 entries, including printed ones:**
  - wrapped footnotes (loc 3 = 3,100 sq ft, loc 2 outside city limits, the sublease)
  - AMS pipe rows (the label is not literal)
  - X-column answers

  Check whether the facts kept them.
- **Teletype policy numbers** stripped the policy tag from the vehicle entries (the test working as designed).
- **`OHM-GL-4471902-23` cleared** as "never printed as a policy number" although the loss run prints it in the POLICY column. Risk to prior-grid year 3, GL.
- **To verify after generation:**
  - the "loss-history attestation conflict" card must not come from the umbrella "no known losses" narrative
  - "15 contracts evidenced" counts historic terms as contracts

## Round 2 - fresh upload 6eda3069 (5 Oct, 19:44 IST, after the first batch)
**What the owner saw:**
- score 83, no hard stops
- 5 Data Consistency cards
- warnings:
  - BI period of restoration
  - "2 of 6 locations" missing COPE
  - loss-history conflict
  - 2 binder follow-ups

**Root causes (all from the stored session):**

| Item | Verdict | Root cause | Fix (generic) |
|---|---|---|---|
| 5 Data Consistency cards ("could not be matched to a coverage line") | FALSE | (1) The picker read every `coverage_lines` row while the line records it scopes against EXCLUDE expiring-programme numbers (`prior_term_policy_numbers`), so the incumbents' -25 auto / property / umbrella numbers were unplaceable rivals. (2) Rows of the DECLINED lines (WC, inland marine) were candidates, including AMS code rows ("WORK", "INMRC") that share their policy numbers. (3) The text "safety net" read "This renewal quotation expires 11/15/2026" and a vehicle registration's "EXPIRES 11/30/2027" as the policy expiration | `underwriting_consistency._out_of_scope_contract_rows` (same exclusion as the store, plus declined lines by family OR shared number); expiration scan reads a LABEL (noun / "policy expires" / "Expires:"), never a bare verb; other-subject words added (quotation, proposal, offer, registration, licence, lease, endorsement, cancellation ...). Result: **0 conflicts**; the proposed term and each incumbent carrier show as SCOPED, not rivals |
| "2 of 6 insured locations" | FALSE | Two nickname rows WITH data ("La Vergne depot", "Franklin - Service Co.") duplicated premises 2 and 3; the closed 1040 Visco Dr (SOV "(DELETED)", "closed 06/30/2026") stayed | `extraction_service.premises_is_retired` (own-field evidence; dated closure on or before the proposed effective; kept aside in `_retired_premises`) and `fold_nickname_premises` (no street number, one street premises in the city, every nickname word in the host's own address / description, no contradicting value). Result: **3 premises** = the key |
| Loss-history conflict (held at 45) | FALSE | Every no-loss phrase was SCOPED (umbrella, property for 3 years, loss-run rows for a policy year); the claims are auto / property | `normalization.no_loss_statements` (account / line / term scope) + `loss_history_state.no_loss_statements_contradict` (line statements only against claims on that line in their window; term rows never). No claims = unchanged. The AI flag stands down only when every literal statement is scoped and none contradicts |
| Loss History 25 "insufficient" (exposed once the false conflict went) | FALSE | One uploaded PDF = one document type; the 59-page package is typed "narrative", so 8 sites read "no loss runs on file" | ONE door `loss_history_state.package_has_loss_runs` (type OR facts: valuation date + run period or carrier-numbered claim rows) at all 8 sites. Result: Loss History **100** (5 years, valued 09/15/2026) |
| BI period of restoration | **REAL** | The SOV prints BI $1,800,000; no period of restoration anywhere | none - correct ask (and only when ACORD 140 is in play) |
| COPE: fire protection class, coinsurance | **REAL** | Never stated in the kit (only policy wording) | none - correct ask |
| ACORD LOB codes (CPKGE, UMBRC, INMRC, WORK, PROPC, BOP, EXLIA, GARAG) unrecognised | GAP, **owner decision (D9 / D57)** | AMS exports print ACORD's standard codes; `lob_canon` knows CGL / AUTOB / CRIME / CYBER / EPLI only | NOT done: D57 makes a fourth abbreviation a fresh D9 decision. Recommended: whole-label exact matches only |

**Replayed 6eda3069 through the round-2 code:** raw **94**, capped **85** by the two REAL warnings; 0 hard stops; 0 Data Consistency conflicts; 3 premises; Loss History 100.

## Improvements log (what changed, why, result)
| Date | Change | Root cause | Before -> after |
|---|---|---|---|
| 5 Oct | **False pre-form warnings - 14 generic fixes** (offline; live retest pending) | Rules read facts no document supports, or ignore what the submission states. Details below | b601fad1 replayed: score **60 -> 83**, hard stops -> 0, soft 12 -> 5 (the 5 left are real asks: COPE, property valuation) |
| 5 Oct | **Data Consistency confirmable after generation** (editor side panel + package page) | The pre-form confirm re-reads the documents and resets the forms, so it was locked once forms existed | Confirm now re-stamps the generated forms in place and re-scores, no reload |

**The 14 false-warning fixes (5 Oct), each generic:**

| # | Warning that was wrong | Root cause | Fix |
|---|---|---|---|
| 1 | HARD "Split liability limits incomplete" on a $1M CSL | The split flag OR-merged from GL / lease "$1M / $2M" text | One door, `coverage_evidence.auto_limits_are_split`: a CSL in words wins over the flag. Used by the legacy and cross-form rules, the 127 stamper, the 101 reason and the state auto grid |
| 2 | "Umbrella effective / expiration date does not match" (x4) | The umbrella's IN-FORCE term was compared with the PROPOSED term | Umbrella term that ends by the proposal -> compared with the expiring term only when that term meets the proposal; otherwise stand down. FR125 checked: its `prior_*` is the year before, now no false row |
| 3 | HARD "BI limit but no Period of Restoration" after a confirm | Recalc validated pre-form against an empty form set and never demoted (C75) | Recalc uses the recommended forms + demotes like the upload; rule also scoped to ACORD 140 |
| 4 | "ACORD 160 + 140 inland marine duplication" | Pair of forms alone treated as an overlap; and the in-force floater kept `has_inland_marine` on | Needs `has_inland_marine`, and (via #12) a declined inland marine turns that flag off. `line_presence` now describes inland marine with census inference OFF (statement / explicit denial / false flag only) - the census alone would have flipped the Meridian kit, which has no key to check |
| 5 | "WC payroll is 26442473% of revenue ($19)" | `cross_form_validator._to_float` digit-stripped "$18.6MM" | One money parser (sqs `_to_float`, MM / M / K) |
| 6 | "Coverage part not recognised: Commercial Package" | A package/CPP heading is a container, not a line | `lob_canon.is_container_label`: skipped when a placed line carries its policy number |
| 7 | "Property deductible basis (flat dollar or %) missing" | "$5,000" / "1%" already answer it | Fires only when a stated deductible shows neither $ nor %. `test_h1...basis` updated (it pinned "$2,500" as open) |
| 8 | "ACV selected on a building valued $6,900,000" | Every "ACV" in the package was the VEHICLES' valuation | Valuation corroboration ignores a vehicle-only context (text window, or a dec entry in an auto section). Now honestly "valuation method missing" |
| 9 | "16 of 20 insured locations missing COPE" | Customer job sites, nicknames and the P.O. Box became premises | Beside a premises schedule with data, an address-only row from the loose `locations` list (or the mailing / certificate-holder address) is not a premises; a P.O. Box never is. Census: 6 of 93 sessions had such rows, all non-premises |
| 10 | Page-one carrier = "Riverbend Insurance Partners" (the AGENCY) | The MGA's ack is addressed TO the agency | `_validate_submission_carrier`: never an agency the docs / account name as producer |
| 11 | `is_renewal` vetoed "Transaction: New business" | The incumbent's "RENEWAL QUOTATION (NOT ACCEPTED)" counted as describing this submission | A renewal QUOTE vetoes only when it is being requested |
| 12 | WC multi-state + WC payroll warnings; ACORD 130 recommended | The SYS-04 door never read "NOT REQUESTED: workers compensation" | `extraction_service.lines_not_requested` (label lists + "<line> is not being marketed / not part of this submission", each line start a candidate subject); `line_presence` treats it as ABSENT, below "ACORD 130 selected" and a person's answer. The flag is demoted once and every WC / IM reader follows. Census over 120 stored sessions: 6 hits, all TRUE - the 3 CH125 runs, harborline ("quote the Inland Marine policy separately - it is not part of this submission") and 2 FR125 runs ("WORKERS COMPENSATION - SUMMARY (NOT PART OF THIS SUBMISSION)"). ACORD 125 has no WC line-of-business box at all, so the WC demotion cannot move a 125 box; the 125 INLAND MARINE box (CH125 key: blank, not requested) now stays blank on CH125 and harborline |
| 12b | (found by the replay) FR125 70 -> 69 after #12 | `has_workers_comp` has TWO meanings: "part of this submission" (the WC rules) and "the insured carries WC" (employees-without-WC -8, the umbrella's Employers Liability checks). Demoting the declined line manufactured an exposure gap | `reconcile_line_flags` records `<line>_in_force` when a declined line still has a policy or stated facts (EL, payroll, class codes); `line_presence.line_carried` / `sqs_service._wc_carried` serve the coverage readers. FR125 now 70 -> 71 / 72. The recommender also drops ACORD 130 / 160 for a declined line (`form_service._DECLINED_LINE_FORMS`; an uploaded copy stays) - #12 alone had NOT stopped the 130 recommendation |
| 13 | A line-scoped confirmation stopped counting on the first rescore | `doc_consistency_stops` read raw keys ("effective_date@auto") | Reads the base key, like the extraction path |
| 14 | Unused `auto_limit_structure` left by fix 1 | - | Removed (ruff) |

**Dismiss is work-tracking only (answer to the owner, 5 Oct).** Dismiss / Resolve mark an item reviewed. They never change a value, never remove a stop and never lift a cap (a dismiss credit goes to RAW and is clamped under the cap). The score moves only when the value changes (confirm, "Open to fix", form edit). The Review card now says so when every stop still holding the cap is marked (`reviewedStops.railCapNote`).

**Data Consistency after generation (5 Oct, owner reversal of the 1 Oct lock).**
- New route `POST /api/underwriting/confirm-value-in-editor` -> `extraction_pipeline.confirm_underwriting_value_in_editor`:
  - same validation, linked fields and scoped key as the pre-form route
  - `apply_confirmations` on the STORED facts (no document re-read), re-assess, recompute `_uw_conflict(ed)_keys`
  - re-stamps every affected fact into every generated form (producer label); drops that key's picker / doc-conflict issues
  - audit row, `recalculate_session_scores`, answers in the resolve-issue shape
- `GET /api/session` returns `underwriting_consistency`.
- Frontend: one handler, two routes (`confirmLockedReason` locks only while a run is live). Editor side panel: a DATA CONSISTENCY block under HARD STOPS. Package page: the picker stays live.
- Offline replays (writes captured): FR125 e3cebd88 effective date -> conflict closed, 73 -> 75, form kept. Orbin 17351800 carrier@GL -> carrier AND policy-number conflicts closed, 4 forms kept.
- Still pre-form only: reclassify, integrity resolve, exclude a document (they re-read documents).

**Measured, final clean run (5 Oct evening):**
- Suite (`-p no:randomly`, from `backend/`): **11,832 passed / 1 failed / 19 skipped** - the 1 is the known `test_arq_acord125_missing_only`.
- D6 score panel: **0 of 12** packages moved.
- Replay of 30 stored sessions (stored confirmations included - the same re-run a confirm triggers): **11 changed, none went down**.
  - CH125: b601fad1 **60 -> 83**; 41dab31c 80 -> 83; fa2f62da stays 60 - its hard stop is REAL (that upload read effective = expiration 12/01/2026; confirming 12/01/2027 clears it).
  - FR125: every run +1 to +3 (false umbrella rows and deductible-basis row gone).

Tests: `tests/test_false_warnings_5oct.py` (63). Updated: `test_h1_coverage_gap_closure` (basis), `test_package_page_1oct` (lock contract).
**Verification lesson (5 Oct):** two suite runs showed 9 and 4 extra failures that pass in isolation - I had edited source files WHILE the suite ran, and tests that `inspect.getsource` read the shifted file against already-loaded code. Never edit while the suite runs. A replay under memory pressure also SKIPPED a session silently (a7ef6f98) - compare the session sets, not just the diff.
| 5 Oct | Data Consistency confirm 500 + human answers lost on re-run - **FIXED** (offline; live retest pending) | `_fv` used in `extraction_pipeline.py` (lines 580, 1520) and never imported. Line 1520 runs only on a re-run of a package with a Drive Other Car named individual (crash, since 16 Sep). Line 580 sits inside a try (C1-D human-answer carry-over silently skipped since 24 Aug). No test ever EXECUTED `_finalize_pipeline` with a session | <ul><li>Confirm / reclassify / integrity-resolve on a named-individual package: 500 -> works</li><li>Human answers on re-run: dropped -> kept</li></ul> |

**The 5 Oct fix in detail:**
- **Import.** `_fv` is now imported from `extraction_service`.
- **Rule for a human answer on a re-run** (a re-run re-reads the same documents, so it never brings new evidence):
  - documents silent or agreeing -> restored, with provenance kept
  - documents disagree with a PRODUCER answer (card, form edit, picker confirmation, accepted client answer) -> **the producer's decision stands**
  - documents disagree with a CLIENT questionnaire answer -> held for the producer (F7 / rule 1.5)
  - The C1-D code as written would have HELD producer answers too, re-asking decided questions. That code had never run.
- **Tests:** `tests/test_rerun_human_facts_5oct.py` (6).
  - They execute `_finalize_pipeline` with a session (DB and account stubbed).
  - A static guard fails the build on ANY undefined name in the product code (ruff F821 / F822 / F823). The whole backend was swept and these 2 lines were the only hits.
  - Proved they bite: 5 of 6 fail on the old code with the live NameError.
- **Census (read-only, 80 newest sessions, 66 decryptable here):**
  - 30 carry a named individual, so every confirm on them crashed
  - 53 hold 176 human answers (164 producer, 12 client), which now survive re-runs
- **Suite** (`-p no:randomly`, run from `backend/`):
  - baseline: **11,762 passed / 1 failed / 19 skipped**
  - after the fix: **11,768 / 1 / 19**
  - +6 = the new tests; the 1 failure is the known `test_arq_acord125_missing_only`; zero regressions
- **D6 (tell Brent):** after a confirm or reclassify, scores can move UP, because human answers now count in the re-run. A client answer that contradicts a document after a reclassify now raises a held-answer card.
- **First live retry (11:27 UTC) still failed, because the backend was never restarted.**
  - The uvicorn PID started 12:32 IST with no `--reload`; the fix was written at 13:08 IST, so the old code ran.
  - The session was unchanged and had 0 confirmations.
  - **Offline replay of all 4 confirms on the real session 41dab31c with the fixed code (DB write stubbed):**
    - all OK; each fact is `user_confirmed`
    - earlier confirmations are kept
    - no NameError, no "preservation skipped"
    - hard stops: none
    - Policy number stays the incumbent's (unconfirmed, as instructed)
- **Live retest:**
  1. Restart the backend.
  2. On session fa2f62da, confirm Effective Date = `12/01/2026` (MM/DD) - it must save, not 500.
  3. Answer one card, then confirm another value - the first answer must still be on the form.

## Generality audit - "is it CH125-only?" (5-6 Oct night)
The owner asked whether the fixes were specific to this PDF. Eight auditors (G1-G8) probed each change with
non-kit data and stored sessions, then five skeptics tried to break the result. Verdicts and what was rebuilt:

| Group | Change | Audit verdict | What was rebuilt | Measured after |
|---|---|---|---|---|
| G1 | Auto split / CSL door | partially generic | Each amount read with its nearest label; signals ranked person > strong printing > structure > stored dec reading > weak printing > flag | Seeded fuzz: CSL read as split 46.7% -> 5.0%, split read as CSL 11.2% -> 8.1% (a printed split: 0) |
| G2 | Money parser, umbrella periods | partially generic | `_to_float` reads ranges, M / MM, "(000s)", counts, labels; umbrella alignment by policy ANNIVERSARY in all three copies | Money 28/28; umbrella 0 false of 13, 5 of 5 real |
| G3 | Container labels | partially generic | Not rebuilt further - advisory only, no score | Known gaps below |
| G3 | Deductible basis | partially generic | Every deductible that APPLIES must show $ / %; "See Schedule" / "TBD" beside a 2% wind no longer silences it; a bare small number on a peril is its % | Skeptic 14/14 |
| G3 | ACV / RCV corroboration | partially generic, fixture-shaped part | Row's specific words first, then its table nearest-first, then generic words; policy-wording prose ("covered property", quoted "you") never counts; coinsurance / perils moved to weak (IM forms use them) | Skeptic 23/23, 9/9, sweeps 0/64 and 0/14; auditor fuzz 4.1% / 2.1% / 0.2%; client's real Orbin package: 38 IM / form mentions counting -> 0 |
| G4 | Premises (P.O. Box, context, retirement, nickname, holder) | partially generic / fixture-shaped | A box is a mailbox only when no street sits beside it; "location" counts only as a SCHEDULE noun ("Service Location:" is third party); a closure must be THIS premises closing ("beer and wine sold on premises since 2018" no longer retires a restaurant); nickname values compared by meaning ($3.4M = $3,400,000, Leased = Tenant); a holder rules out a row only when it is a lender / insurer / lessor | P.O. Box 22/23, rural 11/11, retirement 19/23 (0 live premises retired), nickname 8/10, CH125 relabelled tickets 4 rows |
| G5 | New business vs renewal | fixture-shaped | Symmetric rule: a renewal phrase vetoes only when its line is a statement about the SUBMISSION; options lists / "not new business" mark nothing; a bullet is not a ticked box | CH125 kit itself: NOT marked -> marked (4/4 stored runs); skeptic grid 120 cases: 0 regressions vs HEAD (was ~80) |
| G5 | Receiving carrier is never the agency | partially generic | One door `fact_comparison.names_the_agency` (legal suffix, "- producer code" tail, OCR glue, initials; an insurer-shaped name is never an agency); also applied to the index addressee in `pdf_service` | Pinned |
| G6 | Lines not requested | partially generic | Reader moved to `services/declined_lines.py`, vocabulary from `lob_canon` | 155/162 probes, 0 false declines |
| G7 | Confirm after generation | partially generic | Before/after re-stamp of every box the change moves; documents' rows snapshotted; validation refuses non-answers and bad dates | 0 stale boxes over 11 confirmations, 0 label-only rewrites |
| G8 | Human facts on re-run | generic | - | - |

**Clean verification (6 Oct, no edits during the runs):**
- Suite (`-p no:randomly`, from `backend/`): 12,273 passed / 3 failed / 19 skipped. Two of the three were guard tests that needed the new shapes recorded (the add-form harvester now reads a message helper's literal arguments; the purge guard records `extraction_pipeline`'s stored dec reading); both pass now. The third is the known `test_arq_acord125_missing_only`. Net **12,275 / 1 / 19**.
- Replay, 29 of the 30 newest stored sessions (b891d0e1 left the window when 6eda3069 arrived): **none went down**. CH125 b601fad1 60 -> 84, 41dab31c 80 -> 85; FR125 runs 70-72 -> 72-84; Orbin cc3ecfcc 72 -> 75 (the producer's own driver row now survives the re-run, so "Driver schedule not provided" is gone).
- D6 panel: **2 of 12 moved, both +1** (the two property packages: the deductible-basis warning no longer fires when every applicable deductible shows $ or %).
- Frontend build clean.

**Found by the slowness diagnosis (6 Oct, after the verification):** `extraction_service._prefer_submission_terms` read audit lines with `[^\n]*\baudit\b[^\n]*`, which is quadratic on a long line (57 s on one 80,000-char line; an OCR'd document with no line breaks would stall `merge_facts` for over an hour). It now finds the word and widens to its line: the same 46 lines on the Orbin text, 0.03 s on a 200,000-char single-line document. Pinned by `test_the_audit_reader_is_linear_on_text_with_no_line_breaks`.

**Known gaps (not fixed, honest list):**
- Container labels: "Commercial Package - Kidnap & Ransom" / "(Data Compromise)" / "... Package" add-ons are hidden; "Master Pac", "C.P.P.", "-YYYY" term suffixes, BOP rows, raw AMS codes (UMBRC / INMRC / WORK - owner decision D9/D57). Advisory only, no score.
- Valuation: mixed property + auto fuzz still 4.1% false strip (asks the producer, never prints a wrong value).
- Premises: a closure only on a second mention of the address; "Location 3 relocated to 55 Elm St on <date>"; lender holder with only an ATTN line; customer-sentence context in a broker e-mail; nickname revenue printed in $000s.
- New business: an incumbent's own "RENEWAL APPLICATION" / "TRANSACTION TYPE: RENEWAL" beside a new-business statement marks nothing (contested -> no opinion, the pre-fix behaviour).

## What went wrong building the kit (5 Oct) - lessons
- **Content was only 91k characters** at first; bulked it with real operating records rather than boilerplate. Policy wording is about 19%.
- **Calibration oscillated.** One added character can add two (char + newline). Fixed by tuning a separate, non-wrapping closing line.
- **Two decoys were not printed:** $138,015 and $53,667. A trap that is not in the document tests nothing; the verifier caught both.
- **Rendering defects found only by LOOKING at pages:**
  - a clipped long line (now every line wraps)
  - footer colliding with the page number
  - teletype double-spaced off the page
  - riffled loss-run cells overlapping money values
- **An uninsured $180 incident was removed.** ACORD's "whether or not insured" made the key ambiguous.

## Open items
- [ ] **Live retest of the 5 Oct fixes:** restart the backend, upload the CH125 PDF fresh, expect no split-limit / umbrella / BI / IM / deductible / ACV / Commercial Package / WC warnings, 3-4 premises, carrier not Riverbend, new business. Then generate 125 + 126 + 127 and confirm a Data Consistency value from the editor side panel.
- [ ] Not fixed (decisions / larger): the loss-history "attestation conflicts with claims" card (the narrative is "the umbrella has never had a claim" - SYS-04 pins this as a conflict); Data Consistency still offers out-of-scope lines' dates as rivals (the picker does not read `_lines_not_requested` yet); extraction mixes date terms run to run; `deductible_basis` the FACT asks per-occurrence vs per-cause, while the RULE asks flat vs % (two meanings, one key).
- [x] **BLOCKER fixed 5 Oct:** the missing `_fv` import, plus the producer-vs-client re-run rule, plus 6 tests. Next: the live retest (steps in the Improvements log).
- [ ] Finish Test 1: generate WITHOUT confirming, grade with `grade_kit.py`, log the numbers.
- [ ] Decide the 4 decision points.
- [ ] Fix the audit gaps (Blank-is-not-No surfacing, Q4 inference, loss-total incurred fallback, zero-claim "Check if none", NPN), then log the before/after here.
