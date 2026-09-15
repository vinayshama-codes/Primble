# Chat 1 - Which value lands in which box (line binding)

Real package: session **e7084347** (Orbin, 271-page policy + COI + narrative). All evidence is offline replay of that session's plaintext per-document facts through `merge_facts` and the stampers (its merged facts are encrypted with the production key). **No paid LLM call. Nothing live-verified.** Line numbers are the files on disk at report time (14 Sep).

## 1. Problems I owned
1. Carrier, NAIC, policy number and dates do not stay with their own line of business
2. "IM 7100 06 04" (an Installation Floater form number) printed in ACORD 125's policy-number box
3. ACORD 126 pairs Employers Mutual Casualty with NAIC 25186
4. Territory 6679 (from the Auto Drive Other Car section) printed on ACORD 126
5. GL class 91580 printed on the ACORD 127 vehicle row instead of 7383

## 2. Per problem

### P1 - carrier / NAIC / policy / dates per line
- **Reproduced: Yes.** Deployed `field_state`: 126 carrier Employers Mutual Casualty + NAIC 25186; 127 and 131 NAIC 25186; 131 underlying Auto carrier + number blank, GL number blank; 125 term 07/15/2026 - 07/15/2027 and section forms eff 07/15/2026 (the policies print 07/15/2025 - 07/15/2026). Per-document `coverage_lines` (2 of 2 extraction runs): page-1 summary rows given 6C7 + Employers Mutual from page 3, ten "... Coverage Part" boilerplate rows, an "EMC Insurance" row, an AAIS / IM 7100 row.
- **Root cause (first wrong point):**
  - Extraction reply: rows carry a carrier / policy the row does not print. Prompt RULE 16 did not limit rows to declarations pages or forbid carry-over (`extraction_service.py` `_EXTRACT_PROMPT_PREFIX` RULE 16, :937). Class **b**.
  - Merge: `carrier_name` (policy) and `carrier_naic` (COI) merged as independent scalars - a pair no document prints (`merge_facts`, :10579, no pairing step existed). Class **d (merge)**.
  - Form filling: post-generation late-stamp `arq_service._backfill_and_resolve_present` (:1746, the `_deterministic_map` call now :1846) stamped section forms with no `_form_id` and no schema, so they took package scalars. Class **d (form filling)**.
  - 131 underlying: `pdf_service._resolve_underlying_policy_row` (:7964) compared `6E74002` vs `6E7-40-02---26` and "Co." vs "Company" as different -> false conflict -> blank. Class **e**.
  - Dates: `extraction_service._backfill_is_renewal` (:10014) matched ISO cancellation wording (OCR line 475 "or if it is a renewal of a policy issued by") -> `is_renewal` = yes -> `_route_renewal_dates` (:11421) derived 07/15/2026 - 07/15/2027. Class **e**.
- **Status: FIXED** (offline).
- **What changed:** RULE 16 tightened + deterministic partners: form-number / bureau cells scrubbed per document; each contract bound to the carrier printed in its own page headers; `carrier_naic` only as a printed pair; late-stamp doors given the form id + schema; 131 compare through the same-contract / same-entity doors; a conditional renewal phrase is not a renewal (owner ruling: printed term stays).

### P2 - IM 7100 06 04 on ACORD 125
- **Reproduced: Yes.** 125 `field_state` `Policy_PolicyNumberIdentifier_A` = "IM 7100 06 04" (the download renders `field_state`). OCR: 16 occurrences, the Installation Floater page footer. `underwriting_confirmation_audit`: the card offered only "IM 7100 06 04" vs "IM 7201 10 02"; producer confirmed at 00:33:39; forms generated 00:36:36 (`acord_audit_log`).
- **Root cause:** extraction wrote {Installation Floater, AAIS, IM 7100 06 04} into per-document `coverage_lines` (class **b**). The card read per-document rows (`underwriting_consistency.py` candidate collection, now :2573 / :2614) and offered it (class **e**). The confirmation became `facts.policy_number`; generation blanked the 125 box, then the late-stamp door wrote it (class **d, form filling**).
- **Status: FIXED** (offline).
- **What changed:** form numbers never reach a row, the card, a confirmation or an apply; the late-stamp door is form-scoped and never reopens a guard blank.

### P3 - 126 = Employers Mutual Casualty + 25186
- **Reproduced: Yes.** Deployed 126 header: Employers Mutual Casualty / 25186. On the working tree before my fix the stamper left 126 blank (four carrier printings on the GL record) and the late-stamp door wrote the same wrong pair.
- **Root cause:** same as P1 merge + late-stamp. Class **d (merge + form filling)**. `_carriers_by_line` also counts phone numbers as carriers - not changed, header binding replaces its job.
- **Status: FIXED** (offline): EMC Property & Casualty / 25186 / BBC7263 - 26.

### P4 - territory 6679 on ACORD 126
- **Reproduced: Yes.** 126 `GeneralLiability_Hazard_TerritoryCode_A/_B` = 104 / 6679 (gap fill). OCR line 6104 "DRIVE OTHER CAR - TERRITORY: 104 6679 $ 204.00" under "ENDORSEMENTS CLASS PREMIUM" - 6679 is the Drive Other Car CLASS, 104 its territory. The GL schedule prints no territory.
- **Root cause:** `pdf_service._resolve_gl_hazard_row` (:10654) returned "UNMATCHED" for a real row's empty territory -> gap fill (class **e**). Gap fill read the whole 711k-char package in 7 chunks and took the only "TERRITORY" in it (class **g** - no line scoping). The fence `_line_code_witnesses` (:19480) had no witness for 104 / 6679 (class **e**). Not class f: nothing told the model which line the box belongs to.
- **Status: FIXED** (offline): owned blank; the fence also reads code-labelled verified dec entries; gap fill scoped to the line's pages.

### P5 - 91580 on the ACORD 127 vehicle row
- **Reproduced: Yes.** Deployed 127 `Vehicle_RateClassCode_A` = 91580 (gap fill). OCR 6026 "VEH NO 1 TERR: 111", 6027 "... ID NO 4S4BRCGC9C3217772", 6031 "PRIV PASSENGER - COMM CLASS: 7383".
- **Root cause:** the session's vehicle rows carry no class (class **c** in that extraction), so the box went to gap fill, whose facts block showed every line's GL classes and whose auto page sat in 1 of 7 chunks (class **g**). On the working tree before my fix the box was already blank (fence), but 7383 never filled.
- **Status: FIXED** (offline): 7383 / 111 from the vehicle's own block.

GL limits on 126 (in scope to confirm): **unverified** in my final replay - not checked separately.

## 3. Every change I made

| file | function / constant | new / modified | what it does now | why |
|---|---|---|---|---|
| backend/services/extraction_service.py | RULE 16 in `_EXTRACT_PROMPT_PREFIX` (:941-943, :947-949, :950-952) | modified | dec / summary / schedule pages only; null when the row prints no carrier / NAIC / policy; a form number is never a policy number; ISO / AAIS never the carrier | P1, P2 |
| same | `PROMPT_VERSION`, `SCHEMA_VERSION` (:53-54) | modified | I set v19 -> v20. **Now v21 (round 6 chat)** | cache bust |
| same | `_ROW_POLICY_KEYS`, `_ROW_CARRIER_KEYS` (:9117, :9123), `_scrub_non_contract_identifiers` (:9130), called per document in `merge_facts` (:10614) | new | clears form-number policy cells and bureau carriers in coverage_lines / underlying_policies / prior_coverage_by_line / dec_page_entries | P2 |
| same | `_PAGE_MARKER_RE`, `_HEADER_LINE_COUNT`, `_HEADER_CARRIER_RE`, `_NOT_A_CARRIER_RE` (:9181-9186), `_page_blocks` (:9190), `_contract_printings` (:9196), `_contract_search_keys` (:9227), `_contract_carriers_from_page_headers` (:9241) | new | carrier printed in the first 6 lines of pages whose header names exactly one contract | P1, P3 |
| same | `_bind_carriers_to_contracts` (:9283), call :10927 | new | rewrites row carriers by contract (or by line with one current contract); drops a NAIC paired with a replaced carrier | P1, P3 |
| same | `_pair_carrier_naic_scalars` (:9328), call :10934 | new | `carrier_naic` = NAIC printed with `carrier_name`'s entity, else dropped | P1, P3 |
| same | `_VIN_RE`, `_VEHICLE_CODE_RES`, `_VEHICLE_BLOCK_BEFORE/_AFTER` (:9382-9387), `_backfill_vehicle_codes_from_text` (:9390), call :10941 | new | fills a missing vehicle class / territory from the nearest VIN's block on the same page | P5 |
| same | `_RENEWAL_CONDITION_RE`, `_RENEWAL_LOOSE_RE`, `_renewal_phrase_is_a_statement` (:9989-10011) | new | a renewal phrase in an if / unless / whether / when / provided / except clause is not a statement | P1 dates |
| same | `_backfill_is_renewal` (:10014) | modified | uses the first match that passes the statement test | P1 dates |
| same | `merge_facts` (:10579) | modified | four calls above | |
| backend/services/pdf_service.py | `import contextlib` (:6) | new | | |
| same | `_fold_contracts` (:2817) | new | folds printings of one contract | P1 (131) |
| same | `_naic_printed_with` (:6863); `_section_carrier_pair` return (:6933) | new / modified | NAIC printed with that entity when the row has none | P1 (IM 21415) |
| same | `_resolve_underlying_policy_row` (:7964, :8054-8135) | modified | carriers keyed by entity, numbers folded by contract, cross-check via `_same_policy_contract` | P1 (131) |
| same | `_schema_context` (:10524) | new | context manager, restores the previous schema | test pollution fix |
| same | `_OPTIONAL_COVERAGE_PART_BOXES` (:10626), `_resolve_uncarried_coverage_part` (:10631); in `_AUTHORITATIVE_BLANK_RESOLVERS` (:2624); called in `_deterministic_map_inner` (:11706) | new | EBL boxes owned blank unless coverage_lines or a dec entry names employee benefits; no coverage_lines -> old path | 126 EBL $1,000,000 / "0 - 25" (scope sweep) |
| same | `_resolve_gl_hazard_row` (:10691-10697) | modified | real row, empty territory -> owned blank (was "UNMATCHED") | P4 |
| same | `_resolve_phantom_gl_hazard_row` (:10764-10769) | modified | owns that same blank | P4 |
| same | `_line_code_witnesses` (:19511-19531) | modified | also reads verified dec entries whose label is a code label | P4, P5 |
| same | `_LINE_SCOPE_ENABLED`, `_SCOPE_EDGE_HEAD/_FOOT` (:16986-16988), `build_line_page_scopes` (:16991), `_field_scope_line` (:17046), `_facts_for_line` (:17063) | new | each line's policy section + unclaimed pages; other lines' facts removed | P4, P5, cost |
| same | `combined_gap_fill` (:17082) | modified | wrapper, new arg `line_scopes=None`; runs the old body per line group | same |
| same | `_combined_gap_fill_core` (:17130) | renamed | the old `combined_gap_fill` body, unchanged | |
| backend/services/arq_service.py | `_guard_blanked_fields` (:1737) | new | fields a post-fill guard emptied | P2 |
| same | `_backfill_and_resolve_present` (:1774-1785, :1841-1846) | modified | passes `_form_id` + form schema; skips guard blanks | P1, P2, P3 |
| same | `_restamp_canonical_into_forms` (:4346-4350) | modified | same form id + schema | P1, P2 |
| same | `_restamp_schedule_into_forms` (:4439) | modified | passes `_form_id` | P1 |
| backend/services/underwriting_consistency.py | `_is_form_number_policy_value` (:1520) | new | policy-number key + ISO / AAIS form shape | P2 |
| same | candidate collection (:2573-2574, :2614) | modified | form-number values never offered | P2 |
| same | `validate_confirmation` (:3386-3387) | modified | refuses a form number (`underwriting_invalid_value`) | P2 |
| same | `apply_confirmations` (:3277-3287) | modified by me; **refactored by round 6** into `usable_confirmations` (:1539), same behaviour | stored form-number confirmation not applied | P2 |
| backend/routes/form_routes.py | combined gap-fill block (:1309-1334) | modified | builds `line_scopes`, passes it; failure -> `{}` (old path) | P4, P5, cost |
| backend/tests/test_line_binding_14sep.py | 34 tests | new | literal Orbin shapes | |
| backend/tests/test_h3_wc_data_capture.py | `test_extraction_schema_carries_the_counts_and_moved_to_v17` (:392-403) | modified | version pin (see 4) | |
| backend/tests/test_form_findings_11sep_round3.py | `test_gap_fill_is_not_asked_about_the_blanked_hazard_grid` (:151-172) | modified | see 4 | |
| backend/tests/test_text_selection.py | `test_verification_still_reads_the_complete_document` (:268-293) | modified | see 4 | |
| improving-ll.md | C88 (:3883-3935) | new | prompt + gap-fill cost entry | |
| v1-20AUG.md | "ORBIN ROUND 3 - which value lands in which box" (:10466-10494) | new | | |
| 11sep-form-improvement.md | status rows 1, 3, 6 (:44, :46, :50); section "ORBIN ROUND 3 (14 Sep)" (:1803 to end of my section) | modified / new | | |

Not touched by me: CLAUDE.md, any frontend file, `ocr_service.py`, any schema. Scratch scripts are in my scratchpad only.

## 4. Tests I changed (not added)
- **`test_extraction_schema_carries_the_counts_and_moved_to_v17`** - before: `PROMPT_VERSION == SCHEMA_VERSION == "v19"`. I set `"v20"` + a docstring line. **Round 6 later set `"v21"`.** The test was not wrong: a version pin moves with a deliberate prompt change, which its own docstring says.
- **`test_gap_fill_is_not_asked_about_the_blanked_hazard_grid`** - before: with a real schedule (RUN_A), *some* `GeneralLiability_Hazard_*` field stays in gap fill (on that fixture: the empty territories). Now: an empty EXPOSURE (`_B`) stays asked; `TerritoryCode_A` is not asked. The old assertion pinned the exact path that produced 6679 on the real package; its intent ("a column the schedule can answer stays open") is kept with Exposure.
- **`test_verification_still_reads_the_complete_document`** - before: inspected `combined_gap_fill`'s source. Now: inspects `_combined_gap_fill_core` (the body moved there) and also asserts the new wrapper never rebinds `raw_text`. Followed a rename; the guard is kept and widened.

## 5. Prompt / LLM changes
- **Prompt text:** RULE 16, `extraction_service.py` :941-943, :947-949, :950-952. Schema text unchanged.
- **Batching / chunking:** gap fill now groups questions by coverage line and gives each group only its line's policy section plus unclaimed pages (`pdf_service.py` :16986-17127, wired at `form_routes.py` :1309-1334). Kill switch `GAP_FILL_LINE_SCOPE=0`. `form_addition.py:236` and the two scripts call without `line_scopes` -> old path.
- **Model setting:** unchanged.
- **Versions:** I moved both `PROMPT_VERSION` and `SCHEMA_VERSION` v19 -> v20 in one edit (SCHEMA text unchanged; `test_form_findings_11sep` requires the two to match). The round 6 chat then moved both to **v21**. On disk now: v21 / v21.
- **Cost per package:**
  - Extraction: about +110 tokens in the cached prefix, calls unchanged (14). Estimated, not billed.
  - Gap fill, measured offline on e7084347 (125 / 126 / 127 / 131) with a recorder in place of OpenAI that answers nothing (upper bound): **205 -> 114 calls; 27,403,562 -> 13,900,368 input chars (~6.85M -> ~3.48M tokens). DOWN about half.** `inspect_gap_fill_prompts.py` PASS ($0.0601, its fixture has no page markers so it is unchanged).
  - Unmeasured: cache hit rate per line group; wall-clock (each group warms its own prefix).
- **Model change recommended: No.** Every wrong value traced to extraction rows the code trusted, merge / stamping doors, or a gap-fill call that was never told the box's line. The three late-stamped values were never an LLM answer. None is class f.

## 6. Shared code I touched
| code | other callers | what I checked |
|---|---|---|
| `merge_facts` | `extraction_pipeline.py:470`, `scripts/restore_session_facts.py:60`; every consumer of merged facts | real-session replay; full suite at the time; each step acts only on positive evidence (one contract per header, a printed pair, a missing vehicle value, a form-number shape) |
| `is_renewal` (via `_backfill_is_renewal`) | `_route_renewal_dates` (:11421); `sqs_service._is_renewal_submission` (:933) -> `validate_policy_term_not_expired` (:975); `pdf_service._resolve_policy_status` (:3377-3391, 125 Renew box); `_resolve_renewal_proposed_period` (:8596-8610); 125 New / Renewal indicators (:9371-9372); `form_service.py:507, :1572` read `flags["is_renewal"]` (flag source **not traced**) | stated renewals still count (3 literal phrases tested); a model-stated `is_renewal` is never touched |
| `_deterministic_map_inner` (new resolver) | every stamper door: `map_facts_to_form`, `compute_form_gaps`, the arq doors, Field QA | the resolver matches only `GeneralLiability_EmployeeBenefits_*`: 5 boxes on ACORD 126 and **7 on ACORD 160** (schema grep). 160 **not tested** |
| `_resolve_gl_hazard_row` / `_resolve_phantom_gl_hazard_row` | `_GL_HAZARD_ROW_RE` (:10140) - ACORD 126 hazard grid only | TerritoryCode boxes exist only in the 126 schema |
| `_line_code_witnesses` | `_cross_line_code_borrows` (:19538, Guard 2d-ii) | on the four deployed Orbin forms it blanks 104 + 6679 (126) and 91580 (127), nothing else |
| `_section_carrier_pair` | `_resolve_section_policy_identity` (:6973, call :6998) | adds a NAIC only when the row has none and exactly one is printed with that entity; two NAICs -> none (test) |
| `_resolve_underlying_policy_row` | `_deterministic_map_inner` (:11726), ACORD 131 only | two different contracts still conflict (test) |
| `combined_gap_fill` | `form_routes.py:1331` (scoped), `form_addition.py:236`, `scripts/inspect_gap_fill_prompts.py:204`, `scripts/score_gap_fill.py:160` | no `line_scopes` -> the old body exactly (test) |
| `apply_confirmations` / `validate_confirmation` | `extraction_pipeline.py:830, :1714, :1752` | only policy-number keys with the ISO / AAIS form shape; round 6's `usable_confirmations` reuses my predicate |
| arq late-stamp doors | `arq_routes.py:165`; `arq_service.py:4673, :4830, :5088, :5232` | 8 order-dependent suite failures from a leaked schema context -> fixed with `_schema_context` |

Full suite when I finished: **7,874 passed / 1 failed (the known `httpx` ImportError) / 21 skipped** (baseline 7,840). That was before the round 6 and lines chats finished; not re-run, as instructed.

## 7. Scores that move
- **Orbin-shaped package** (ISO wording mentions "renewal" conditionally, no stated renewal, term already ended at upload, dates read from a document):
  - Before: `is_renewal` = yes -> dates re-derived to 07/15/2026 - 07/15/2027 -> no ended-term warning; 125 "Renew" ticked.
  - After: printed term 07/15/2025 - 07/15/2026 -> soft warning "Policy term already expired (07/15/2026) read from an uploaded policy document ..." (`sqs_service.py:1023-1030`) -> can bind the **85 cap**. Direction **DOWN or unchanged. Not measured.** 125 "Renew" blank.
- Packages that state a renewal: unchanged.
- Section forms fill carrier / NAIC / policy boxes that were blank (126) or wrong; EBL goes blank on packages without EBL; line-scoped gap fill can change which boxes the model fills on any multi-policy package. Fill-rate direction **unmeasured**.
- A stored form-number policy confirmation is no longer applied. On Orbin the policy-number card goes to "scoped" (no conflict, no withhold).
- No hard stop, cap rule or weight added or removed.

## 8. Live test checklist (fresh upload, so extraction runs at v21)
| # | where to look | expected when FIXED | still BROKEN looks like |
|---|---|---|---|
| 1, 3 | ACORD 126 header CARRIER / NAIC / POLICY NUMBER | EMC Property & Casualty / 25186 / BBC7263-26 (may print "BBC7263 - 26", the dec's own spacing) | Employers Mutual Casualty, or blank |
| 1 | ACORD 127 header | Employers Mutual Casualty / 21415 / 6E7-40-02---26 | NAIC 25186 |
| 1 | ACORD 131 header | Employers Mutual Casualty / 21415 / 6J7-40-02---26 | NAIC 25186, or the 6E7 number |
| 1 | ACORD 131 underlying schedule, Auto row | Employers Mutual Casualty / 6E7-40-02---26 | carrier or number blank |
| 1 | ACORD 131 underlying schedule, GL row | EMC Property & Casualty / BBC7263-26 | number blank |
| 1 | ACORD 125 PROPOSED EFF / EXP | 07/15/2025 / 07/15/2026 | 07/15/2026 / 07/15/2027 |
| 1 | 126 / 127 / 131 effective date | 07/15/2025 | 07/15/2026 |
| 1 | Pre-form Warnings | soft "Policy term already expired (07/15/2026) read from an uploaded policy document" | no warning, shifted dates |
| 1 | ACORD 125 STATUS OF TRANSACTION, Renew | blank (producer ticks) | ticked |
| 2 | ACORD 125 POLICY NUMBER (downloaded PDF) | blank - never IM 7100 06 04 | IM 7100 06 04 |
| 2 | Data Consistency, Policy Number | no card, or only 6C7 / 6E7 / 6J7 / BBC7263 printings; IM 7100 06 04 and IM 7201 10 02 never offered | card offers IM 7100 06 04 vs IM 7201 10 02 |
| 1-3 | Open the client questionnaire, then download again (the late-stamp door runs on questionnaire open) | every value above unchanged | 125 IM 7100 06 04, or 126 / 127 / 131 NAIC 25186 reappear |
| 4 | ACORD 126 hazard grid TERR, rows A and B | blank | 104 or 6679 |
| 5 | ACORD 127 vehicle 1 (2012 Subaru Outback, VIN 4S4BRCGC9C3217772) CLASS / TERR | 7383 / 111 | 91580, blank, or 6679 |
| scope | ACORD 126 Employee Benefits block | blank | $1,000,000 and "0 - 25" |
| cost | backend log `combined_gap_fill: line-scoped groups` and `line_scopes=` | four lines, each well under the 711k-char document | no such line, or every scope near full size |

## 9. Not done, not verified, risks
- **Nothing live-verified.** All results are offline on e7084347.
- **COI:** the real COI from the session was used. The COI's per-row INSURER letter is **not** joined to rows; the NAIC comes from the entity name the COI prints it with.
- **Not fixed (outside my five or not touched):** ACORD 125's "one line's carrier as THE package carrier" (it now prints a correct pair, EMC Mutual / 21415); 127 FARTHEST TERMINAL 6679; driver name split; the card still lists an unplaced "EMC Insurance" carrier candidate (scoped, no conflict - conflict-card chat).
- **ACORD 160:** its 7 EBL boxes share the prefix, so they go blank on a package with `coverage_lines` and no EBL evidence. Untested; fails toward blank. Owner said leave 160 alone - reviewer's call.
- **Renewal:** the owner ruled "printed term" without ruling on "is this a renewal". A real renewal whose only renewal wording is conditional loses the Renew tick.
- **Line scoping:** inside a scoped group, gap fill verifies quotes against the scoped text (stricter, not looser). Downstream verification is unchanged. A policy whose number never appears in a page header or footer gets no scope and reads the whole document. Latency and cache effect unmeasured.
- **Header binding** needs `[Document page N]` markers and the carrier in the first 6 lines. Without them it does nothing (old behaviour).
- **Vehicle codes** need the VIN within 3 lines before / 8 after the CLASS / TERR line on the same page.
- **Overlap with other chats:** round 6 refactored my `apply_confirmations` change into `usable_confirmations`, moved the prompt to v21, and moved the version pins in `test_line_binding_14sep.py` and `test_h3_wc_data_capture.py` to v21. Round 6's `_drop_unknown_form_references` also filters policy-number candidates - not tested together with my scrub beyond my files passing on today's tree. I did not review other chats' edits in the files I share.
- 126 GL limits staying correct: **unverified** in my final replay.

## 10. My test results
Run 14 Sep on the current tree, from `backend/`:
`py -m pytest -q -p no:randomly tests/test_line_binding_14sep.py tests/test_h3_wc_data_capture.py tests/test_form_findings_11sep_round3.py tests/test_text_selection.py`
-> **183 passed, 0 failed** (test_line_binding_14sep.py alone: 34 passed).
