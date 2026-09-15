# Chat 5 - Don't ask for what we already have

Session used for all evidence: `e7084347-c34f-4dc0-ba08-25f8d151f75f` (client user ed40f6a3, 10 Sep 2026, 2526 Package Policy + CRS COI + narrative, forms 125/126/127/131). Its merged `facts` do NOT decrypt with the local key, so every replay rebuilt merged facts from the plaintext per-document facts with current `select_primary_truth` + `merge_facts`. No paid LLM calls, no emails, nothing sent.

State at handoff: every change listed below is on disk and unaltered (checked marker by marker, 14 Sep). My test file passes (36/36). Nothing is committed.

## 1. Problems I owned

- 13. The client was asked again for the Subaru's year / make / model / VIN, which the policy already states.
- 14. Driver questions ran through "Driver 25".
- 15. There is no step that shows source-verified data to the client to confirm or correct.

## 2. Per problem

### 13 - Subaru asked again
- **Reproduced:** yes.
  - What the client actually received is stored in `arq_sessions` 424ef2ef (29 Aug; its session 4cea505b has since been deleted). It contains:
    - `Vehicle_BodilyInjury_PerPersonLimitAmount_A` worded "Please provide ... Year, Make, Model, VIN ... (1st vehicle)". The client answered "$2,012 Subaru 4S4BRCGC9C3217772" into an auto liability LIMIT box.
    - `schedule::auto_vin_schedule` worded "Please list the vehicles to be insured", pre-filled with the Subaru.
  - On code before my change, replaying e7084347 still produced the "Please list" table.
  - The source document states the vehicle: `271page-testdec.txt:6027` "2012 SUBARU OUTBACK SEDAN ID NO 4S4BRCGC9C3217772". The dec-page per-document facts hold the full row. ACORD 127 row A has year/make/model/VIN stamped (confidence `filled`).
- **Root cause:** a rule (class e).
  - `arq_service.py:_partition_schedule_fields`, PASS 1 (HEAD line 2629, now 2704) raised the table whenever any capturable box was blank.
  - Orbin had 35 such blanks: `Vehicle_BodyCode_A` (removed by a post-fill guard), `Vehicle_GrossVehicleWeight_A`, and 11 each on rows B-D. The form leaves rows B-D blank on purpose (`pdf_service.py:_resolve_phantom_schedule_row`, line 2331).
  - `_finalize_schedule_taxonomy` (now line 2918) then forced `suppressed=False`.
  - The wording was fixed at "Please list" (`schedule_capture.py` HEAD line 799, `question_text` HEAD line 853).
- **Status:** FIXED.
- **Change:**
  - Held rows now decide the question, not blank boxes: rows held gives confirm mode ("We found 1 vehicle in your policy declarations. Please check it, correct anything that is wrong, and add any we missed."); no rows gives list mode.
  - A complete fleet also gets its confirm table.
  - A confirmed, unchanged table is not asked again.
  - Same class, also fixed: the garaging question is suppressed when the form's `Vehicle_PhysicalAddress_*` street, city or ZIP box is filled. The empty claims table is dropped when the loss state is "no known losses attested".

### 14 - "Driver 25"
- **Reproduced on current code:** no.
  - Replay of e7084347 gives 0 questions matching `\(\d+(st|nd|rd|th) `. All 156 raw `Driver_*` boxes land in the hidden internal bucket, and there is one driver table.
  - The mechanism is visible in history:
    - Commit d6d09c7 `arq_service.py` lines ~2905-2910 used `group_counts[label] += 1` to label "(Nth driver)", counting questions, not drivers.
    - The client's stored 26 Jun questionnaire (arq 0226bb4f) shows "(1st driver)" / "(2nd driver)" on raw `Driver_Surname_A/B`.
  - The literal text "Driver 25" is **unverified**: the Send-to-Client preview list is never stored.
- **Root cause:** class e, fixed earlier by BUG-07 in commit 11e1969 (8 Sep), before the client's 10 Sep run.
- **Status:** NOT A DEFECT on current code (already fixed).
- **Related defect I did fix:** the one driver table was pre-filled with ERIN ROYAL, the Drive Other Car named individual (`271page-testdec.txt:6124-6125`). Extraction put her in `auto_drivers`.
  - First wrong point: the extraction prompt/schema (class b/c/d). `extraction_service.py:354` says a driver's territory is printed "e.g. in a Drive Other Car schedule", and there is no key for a named individual.
  - Three consumers disagreed on her:
    - The stamper refuses name-only rows (`pdf_service.py:9474 _NAME_ONLY_INVALID_SCHEDULES`).
    - The scorer counted her as a driver schedule (`coverage_evidence.py:795 _drivers_known`).
    - The questionnaire seeded her as a driver.
  - Fixed by `services/named_individuals.py`, which runs once in `_finalize_pipeline` right after `merge_facts`.

### 15 - No confirm-or-correct step
- **Reproduced:** yes.
  - Known facts are suppressed as `already_provided` (`question_classifier.py:decorate_questions`).
  - `current_value` was hard-blanked in `arq_routes.py` send_arq (line 299) and client_view (line 490).
  - Tables arrived pre-filled under "Please list" wording.
  - An untouched table is discarded as "no answer" (`arq_service.py:client_supplied_schedule`), so the 29 Aug unchanged resubmission recorded no confirmation.
- **Root cause:** missing feature (class g).
- **Status:** FIXED, with one limitation (section 9).
- **Change:** new `services/confirm_known.py` plus `_build_confirm_questions`.
  - Core facts (Tier 1 / contact / Tier 2) that are source verified, uncontested, client-audience, not insurance judgment and not FEIN/DOB/licence become optional `confirm` items. Each shows the value and the document TYPE it came from.
  - The `__CONFIRMED__` answer sets `evidence_state: user_confirmed` with no value change and no box change.
  - A correction goes through the existing F7 hold.
  - Table rows from the documents that the client removed or changed are flagged on `review_fields`.

## 3. Every change I made

| file | function / constant | new/mod/del | what it does now | why |
|---|---|---|---|---|
| backend/services/named_individuals.py | whole module (`separate_named_individuals`, `drivers_without_named_individuals`, `is_named_individual_row`, `printing_roles`, `_NAMED_HEADING_RE`, `_DRIVER_HEADING_RE`) | new | Moves a row out of `auto_drivers` into `auto_named_individuals` when it has no driver details AND its name is printed under a named-individual heading and never under a driver heading (nearest heading within 800 chars). Keeps `territory`. | Problem 14 related (ERIN ROYAL). One role decision for every consumer. |
| backend/services/confirm_known.py | whole module (`CONFIRMED_SENTINEL`, `CONFIRMATIONS_KEY`, `is_confirmed_value`, `core_confirm_candidates`, `confirmable_display_value`, `source_labels_for_list/_for_fact`, `sanitize_source_labels`, `sources_phrase`, `rows_signature`, `schedule_is_confirmed`, `record_schedule_confirmation`, `schedule_row_changes`, `record_fact_confirmation`, `is_sensitive`, `doc_label`) | new | Pure helpers for confirm-or-correct. | Problem 15. |
| backend/services/schedule_capture.py | `_CONFIRM_NOUNS`, `_CONFIRM_HINT`, `confirm_question_text` | new | Confirm-mode wording per table. | Problem 13. |
| backend/services/schedule_capture.py | `question_text(list_key, rows=None, source_labels=None)` | modified | With rows, returns confirm wording. Without rows, unchanged. | Problem 13. |
| backend/services/schedule_capture.py | `hint_text(list_key, confirm=False)` | modified | `confirm=True` returns the confirm hint. Otherwise unchanged. | Problem 13. |
| backend/services/arq_service.py | imports (lines 18-31) | modified | Imports `confirm_known`, `CONFIRMED_SENTINEL`, `is_confirmed_value`, `PRIORITY_OPTIONAL`. | wiring |
| backend/services/arq_service.py | `_backfill_and_resolve_present`, new third pass (~line 1894) | modified | Adds `auto_garaging_addresses` to the present set when any `Vehicle_PhysicalAddress_LineOne_/CityName_/PostalCode_` or `Vehicle_GaragingAddress_` box has a value. | Garaging re-asked (same class as 13). |
| backend/services/arq_service.py | `_partition_schedule_fields`, PASS 1c (~2732) and PASS 3 (~2782) | modified | A form carrying a schedule with rows held now justifies the table (`carried_held`), not only a blank box. | Problem 13. |
| backend/services/arq_service.py | `_build_schedule_questions(..., session_docs=None)` (~2814) | modified | Adds `schedule_mode`, `confirm`, `source_labels`; confirm wording and hint when rows are held; skips a confirmed, unchanged table with no required blanks. | Problems 13/15. |
| backend/services/arq_service.py | `_build_confirm_questions` (~2922) | new | Builds scalar confirm items (rules in section 2). | Problem 15. |
| backend/services/arq_service.py | `_apply_loss_state_question_gate` (~2321) | modified | In `STATE_NO_KNOWN_LOSSES_ATTESTED`, drops `schedule::loss_history` when it has no `current_rows`. Early return now also requires the state not to be attested. | Claims table re-asked after the producer answered "no losses". |
| backend/services/arq_service.py | `generate_arq_questions` (~3630, ~3657) | modified | Passes `session_docs` to `_build_schedule_questions`; appends `_build_confirm_questions` after `_finalize_schedule_taxonomy`. | Problems 13/15. |
| backend/services/arq_service.py | `generate_arq_questions_from_facts` (~3831) | modified | Appends `_build_confirm_questions` (no docs, so "on file" wording). | Parity between the two generators. |
| backend/services/arq_service.py | `submit_arq_answers` (~4348, ~4381) | modified | Sentinel stored only on a question sent with `confirm`. A confirm table with document rows changed or removed adds a `review` entry. | Problem 15. |
| backend/services/arq_service.py | `apply_arq_answers_to_session` (~4841, ~4854, ~5173) | modified | Sentinel records the confirmation (`record_fact_confirmation` / `record_schedule_confirmation`) and `continue`s, so no stamp, no hold, no `updated` entry. Adds `confirmed_by_client` to the audit detail. | Problem 15. |
| backend/services/arq_receipt_service.py | `KIND_CONFIRMED`, `build_receipt_payload`, `confirmed_count` | new / modified | A confirmation is its own receipt kind and counts as answered. | Problem 15. |
| backend/services/extraction_pipeline.py | `_finalize_pipeline` (~480, ~1403) | modified | Calls `separate_named_individuals` right after `merge_facts`. On a re-run (session_id set) that moved rows and left `auto_drivers` empty, passes `delete_facts=["auto_drivers"]`. | Problem 14 related; the additive facts merge skips empty lists. |
| backend/services/pdf_service.py | `_is_name_only_record_echo` (line 22719) | modified | Reads `auto_named_individuals` as well as `auto_drivers`. A named individual's name always counts as a name-only echo. | Keep an existing guard working after the move (ERIN ROYAL used as Yes-evidence). |
| backend/routes/arq_routes.py | import (35), `_sanitize_answers` (136) | modified | Keeps the sentinel on a schedule key instead of decoding it to an empty table (drafts and submit). | Problem 15. |
| backend/routes/arq_routes.py | `send_arq` (~340, ~363) | modified | For confirm scalars, rebuilds `current_value` from the session's facts (only if still source verified) plus `source_labels`. For schedules, recomputes question, hint, `confirm`, `schedule_mode` and `source_labels` from the rows actually sent. | Problems 13/15. |
| backend/routes/arq_routes.py | `client_view` (~497, ~531) | modified | Passes `confirm`, `source_labels` and `current_value` (confirm scalars only), plus `schedule_mode` for tables. All other questions still get `current_value: ""`. | Problem 15. |
| backend/tests/test_known_data_not_reasked_14sep.py | 36 tests | new | Fixtures use the literal Orbin OCR text, the stored Orbin rows and the real ACORD 127 schema. | Proof. |
| frontend/src/components/arq/ClientQuestionnaire.jsx | `CONFIRMED` const; load seed; `validateAnswers`; `buildReceipt`; `changingConfirm` state; per-question variables; input-area JSX; "Keep what we have"; "I'm not sure" hidden on confirm items; source-label line | modified | Confirm scalar: read-only value with "This is correct" / "Change it". Confirm table: "Everything here is correct" while it is untouched, a confirmed summary with Undo, otherwise the normal table. | Problem 15. |
| frontend/src/components/arq/ARQReceiptModal.jsx | `KIND_STYLE.confirmed`, render branch, confirmed count | modified | Shows confirmations on the receipt. | Problem 15. |
| frontend/src/components/form/AcordModal.jsx | `ARQModal`: "Confirm with client" line in `renderRow`; `confirmQuestions` / `addConfirmations`; "Add confirmations (N)" button | modified | Producer sees and can add confirm items. | Problem 15. |
| CLAUDE.md | new section "Don't Ask The Client For What We Already Have (Orbin Chat 5)" under Critical Issues | modified | Short summary. | Docs rule. |
| v1-20AUG.md | new entry "## ORBIN Chat 5 - do not ask the client for what we already have (2026-09-14)" at the end | modified | Change log. | Docs rule. |
| (outside repo) memory `client-session-offline-replay.md` | one sentence added | modified | Notes that `arq_sessions.questions/answers` survive session deletion. | Session memory, not repo. |

Not touched: improving-ll.md, 11sep-form-improvement.md (read only), any prompt, extraction_service.py, sqs_service.py, coverage_evidence.py, question_classifier.py, underwriting_consistency.py. Scratch scripts live in the session scratchpad, outside the repo.

## 4. Tests I changed or deleted (not added)
None. No existing test was edited or deleted. (Inside my new file I fixed my own fixture once: `values_agree` treats "ORBIN CONTRACTING, LLC (NEW NAME)" as the same name as "ORBIN CONTRACTING LLC". The code is right to trust the comparison door, so the fixture now uses a genuinely different name.)

## 5. Prompt / LLM changes
- **Prompt, schema, batching, chunking, model:** none changed.
- **PROMPT_VERSION / SCHEMA_VERSION:** I did not touch them. On disk they read `v21` / `v21` (`extraction_service.py:53-54`).
- **LLM cost change:** zero. All changes are deterministic. `_humanize_fields_with_openai` was not called for any new question in the offline replays: confirm items use curated wording, schedules use their own text.
- **Model change recommended:** no. The model extracted the Subaru correctly (every field, text-verified). The re-ask was created afterwards by rules. On ERIN ROYAL, the model followed the prompt as written.

## 6. Shared code I touched
- **`_finalize_pipeline`** (all 8 callers: upload, resolve, reclassify, confirm value, marketing reason, split).
  - The new step only moves rows that meet both conditions.
  - It is fail-open (any exception leaves facts unchanged).
  - `delete_facts` is passed only when rows were moved AND the merged `auto_drivers` is empty.
- **`_is_name_only_record_echo`** (pdf_service explanation guard). Only adds a second key; behavior for `auto_drivers` is unchanged. Test `test_the_echo_guard_still_knows_her_after_the_move`.
- **`_line_code_witnesses`** (cross-line fence): not edited. `_canon_from_name("auto_named_individuals")` returns `auto` (checked), so the moved territory still witnesses Auto. Test `test_the_territory_moves_with_her_and_still_fences_the_gl_grid`.
- **`_partition_schedule_fields`, `_build_schedule_questions`, `_apply_loss_state_question_gate`:** used by both generators. Existing suites pass: test_schedule_capture, test_bug07_ghost_vehicle_questions, test_question_eligibility, test_loss_history_c2, test_questionnaire_progress_20260908, test_naics_suggester, test_h3_wc_data_capture, test_h1_coverage_gap_closure, test_answer_routing, test_sys01_critical_tagging, test_v1_regpack_loss_history, test_fill_integrity_guards. Result: 781 passed.
- **`schedule_capture.question_text` / `hint_text`:** new arguments are optional, so old callers (h3 tests, `send_arq`) get byte-identical text when no rows are passed.
- **`_backfill_and_resolve_present`:** called by `GET /api/arq/generate`. The new pass only ADDS to the present set and never stamps.
- **`submit_arq_answers`, `apply_arq_answers_to_session`, `build_receipt_payload`, `_sanitize_answers`, `send_arq`, `client_view`:** new behavior triggers only on the sentinel or on `confirm`, which no existing question carries.
- **Full suite, run once before the handoff:** 8403 passed / 1 failed (`test_arq_acord125_missing_only`, the documented httpx ImportError) / 21 skipped / 2 xfailed. Other chats were editing at the time.
- **Concurrent edits by other chats:** `arq_service.py` (`_asks_about_an_absent_line`, `_drop_not_applicable_questions`, backfill `_form_id`), `extraction_pipeline.py` (`_submitting_account`), `pdf_service.py`, `extraction_service.py`. None of them overlap my lines; checked by marker grep.

## 7. Scores that move
Measured offline on e7084347 (rebuilt facts, plus the two producer answers from `sqs_recommendation_audit`: the no-loss attestation and contact name "Erin Royal").

| What | Before | After |
|---|---|---|
| Package SQS | 78 | 75 |
| ACORD 127 | 82 | 77 |
| ACORD 125, 126, 131 | unchanged | unchanged |

- New `auto_completeness` gap: `auto_drivers` -10 "No driver schedule".
- New legacy soft stop: "Driver schedule not provided - list the drivers of the scheduled vehicles (name, licence, date of birth)". Legacy warnings cap at 85.
- **Who moves:** any auto package whose only "driver" is a name printed under a Drive Other Car / named-individual heading. Direction: DOWN. It matches the client's 6.3 rule (the policy schedules no drivers). **Brent first.**
- **No score change** from confirmations, the garaging change or the loss-table change (questionnaire only). "Confirmations don't move the score" is by code reading: the envelope keeps `source`/`confidence`, which drive the SQS evidence labels. Unverified by a live run.

## 8. Live test checklist
Run on the NEW code, with a fresh upload of the Orbin package. Then Forms, Send to Client (preview only). The client view needs a sent ARQ to a test inbox.

| # | Where to look | Expected when FIXED | If still BROKEN |
|---|---|---|---|
| 13 | Send to Client modal, Client list, Auto topic: vehicle table | "We found 1 vehicle in your policy declarations. Please check it, correct anything that is wrong, and add any we missed." with "Confirm with client - 1 vehicle on file (from the policy declarations)". Row: 2012 / SUBARU / OUTBACK SEDAN / 4S4BRCGC9C3217772 | "Please list the vehicles to be insured..." |
| 13 | Same modal, Client list | No "Where are your business vehicles primarily kept overnight?" (ACORD 127 row A shows Denver / 80216-3121) | That question present |
| 13 | Same modal, Loss History topic | No "Please list any insurance claims or losses..." table (after the producer answers "No - no claims or losses in the past 5 years" on the loss card) | Claims table present |
| 13 | Same modal, location table | "We found 1 business location in your policy declarations and your certificate of insurance..." with 4800 DAHLIA ST / # D13 / DENVER / CO / 80216-3121 | "Please list every business location..." |
| 14 | Same modal (all buckets) | No question text containing "(2nd driver)", "(25th driver)" or any "(Nth driver)" / "(Nth vehicle)". Exactly one driver item: "Please list everyone who drives a business vehicle...", EMPTY table | Numbered driver cards, or ERIN ROYAL pre-filled in the driver table |
| 14 | ACORD 127 PDF, `Driver_GivenName_A` / `Driver_Surname_A` | Blank (no scheduled driver) | ERIN / ROYAL printed |
| 14 | Pre-form / SQS warnings | "Driver schedule not provided - list the drivers of the scheduled vehicles (name, licence, date of birth)" appears (expected, D6) | Absent |
| 15 | Send to Client modal | "Add confirmations (N)" button. Items "What is the full legal name of your business?" Current: ORBIN CONTRACTING LLC and "What is your business mailing address?" Current: 4800 DAHLIA ST # D13, DENVER CO 80216-3121, both "Confirm with client", not pre-ticked | No such items / button |
| 15 | Client questionnaire | Name card shows "ORBIN CONTRACTING LLC", "We found this in your policy declarations...", buttons "This is correct" and "Change it". Vehicle table shows "Everything here is correct" | Empty text box for a known value |
| 15 | After submit: producer ARQ panel, "View response receipt" | Name: "ORBIN CONTRACTING LLC - Confirmed as correct"; vehicle table: "1 row - Confirmed as correct"; header "2 confirmed as correct" | Items shown as "Not answered" / blank |

## 9. Not done, not verified, risks
- **Not done: extraction prompt.** It still points Drive Other Car at `auto_drivers` (`extraction_service.py:354`). The merge-time rule covers it. A prompt edit needs a PROMPT_VERSION bump (paid re-extraction of every cached package). Owner's call.
- **Not done: held table corrections.** A client edit to a pre-filled table still applies straight away and is only flagged on `review_fields`. Holding it needs a producer surface for held tables, which doesn't exist.
- **Not verified:**
  - The frontend was only built (vite build clean), never clicked through in a browser.
  - `send_arq` / `client_view` are covered by a source-level test only; there is no end-to-end HTTP test.
  - The literal "Driver 25" text was never seen stored.
  - Score deltas come from a rebuilt-facts replay, not the deployed session (which is encrypted).
- **Heuristic limits (named individuals):**
  - English headings only.
  - An 800-character lookback.
  - A name-only row printed under both headings, or with no heading at all, stays a driver (by design).
  - A name formatted differently in the text ("ROYAL, ERIN") is not matched, so no move.
- **Re-run behavior:** human-typed driver rows are lost on a pipeline re-run. This is pre-existing (lists carry no provenance) and neither better nor worse after my change.
- **Confirm scalar sameness** uses `fact_comparison.values_agree`, so a containment variant ("ORBIN CONTRACTING, LLC") keeps a confirmation.
- **Disagreement with `11sep-form-improvement.md` item 11** ("with rows present we ask nothing"). That was measured on an empty synthetic ACORD 127; on the real session the table was still raised.
- **Out of my scope, still visible in the Agency bucket on Orbin:** split-limit BI/PD questions on a CSL policy, and `UnderlyingPolicy_OtherPolicy_*` dates/number. Those belong to other chats.
- **Deployment note:** the client's stored 10 Sep session ran the deployed code (commit 162bfbd). The live test needs this working tree deployed plus a fresh upload.

## 10. My test results
`py -m pytest -q -p no:randomly tests/test_known_data_not_reasked_14sep.py` from backend/: **36 passed, 0 failed** (run 14 Sep, at handoff).
