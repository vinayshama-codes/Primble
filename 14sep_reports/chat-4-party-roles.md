# Chat 4 - Who is this party, and in what role

Verified on disk before writing (15 Sep): all 79 change markers present, 0 missing or altered
(script: every function / constant below checked by exact text). My test file: 132 passed.
Nothing committed. No prompt, schema or model change.

## 1. Problems I owned

11. The expiring producer (Commercial Risk Solutions / Terri Wroblewski) printed on the new application instead of the submitting producer (ThinkSmith Agency / Michelle Smith).
12. "For Informational Purposes Only" printed as an Additional Interest.

## 2. Per problem

### 11 - expiring producer on the new application
- **Reproduced:** Yes.
  - Session `e7084347-c34f-4dc0-ba08-25f8d151f75f` (10 Sep, the only real Orbin run with forms). Stored PDFs: ACORD 125/126/127/131 `Producer_FullName_A = "Commercial Risk Solutions, Inc."`, `Producer_AuthorizedRepresentative_FullName_A = "Terri Wroblewski"`; ACORD 125 `Producer_ContactPerson_FullName_A = "Terri Wroblewski"`, email `twroblewski@crsdenver.com`.
  - Replayed on the 14 Sep code (before my fix): same values on 125/126/127/131/25.
  - "ThinkSmith" and "Wroblewski" are absent from the 271-page policy text. "Terri Wroblewski" comes from the COI producer block (CONTACT NAME). **ThinkSmith appears in NO uploaded document**: the COI's producer is "CRS Insurance Brokerage", and the narrative names no producer. ThinkSmith Agency LLC / Michelle Smith are the uploader's account: `users.organization_name` / `users.full_name` for user `ed40f6a3-1d3e-4daf-a732-0b65f1f48d68`.
  - "Michelle Smith" appears in the COI only as embedded signature text beside AUTHORIZED REPRESENTATIVE. Extraction never captures it.
- **Root cause (first wrong point):** `backend/services/extraction_pipeline.py:_finalize_pipeline` called `merge_facts(active_docs, primary)` (old line 453) with the documents only. The account was never passed to the merge, so no input ever named the submitting agency. The 11 Sep routing `extraction_service.py:_route_producer_identity` could then only RECORD the old agency (branch "ONLY THE EXPIRING PROGRAMME NAMES ONE: RECORD, DO NOT CLEAR", now line 9034). It left `producer_*` = the old agency, and `pdf_service._resolve_submitting_producer` skipped.
  - Class: (g) missing input, plus (c) one producer role in the schema, plus (d) relationship lost in the merge. The producer block was routed key by key: fed the account, it printed ThinkSmith's name over the old agency's address, phone and email.
  - The 11 Sep "live-verified" run used the synthetic HALVORSEN kit, whose narrative names ThinkSmith. The real package does not.
- **Status:** FIXED (offline, on the real session's documents; not yet live).
- **What changed:**
  - The pipeline reads the logged-in account on every run and passes it to the merge.
  - The producer block now moves as ONE party. When the submitting agency (a submission document's single agency, else the account's) differs from the expiring documents' agency, every old value moves to `expiring_producer_*`. The form prints only the submitting side's values: ThinkSmith Agency LLC / Michelle Smith, with the address, phone, fax and email blank.
  - The Data Consistency producer card is not offered once the two agencies are separated.

### 12 - "For Informational Purposes Only" as an Additional Interest
- **Reproduced:** Yes.
  - Stored ACORD 127 PDF: `AdditionalInterest_FullName_A = "For Informational Purposes Only"`, with `AdditionalInterest_MailingAddress_CityName_A = "Denver"` and `AdditionalInterest_AccountNumberIdentifier_A = "0482854"` (the insured's own city and account number).
  - Source: the COI's CERTIFICATE HOLDER box, OCR text `ForInformationalPurposesOnly` (no spaces).
  - The phrase sat in 3 per-document facts: `certificate_holder`, `risk_transfer.certificate_holder_name`, `certificate_description_of_operations`.
- **Root cause (first wrong point):** extraction stored a placeholder as a party.
  - `extraction_service.py:329` offers only `"certificate_holder": string or null`, and `fact_registry.py:1144` has `validate: None` for `certificate_holder`.
  - The fact then went into every gap-fill prompt (`pdf_service.py:136` `_GAP_FILL_FACTS_EXCLUDE` excludes only `dec_page_entries`), and gap fill placed it in the Additional Interest row.
  - Class: (c) extraction schema, (e) no entity check, (d) role lost at gap fill.
- **Status:** FIXED, with residuals listed in section 9.
  - The 14 Sep code (another chat's box guard) already blanked this exact string. It did NOT catch the COI's own OCR spelling, the fact itself, or look-alikes.
- **What changed:**
  - Placeholder holder / payee / mortgagee facts are removed per document at the merge, together with a prose fact carrying the same text.
  - The party-name check re-spaces glued OCR text (camel-case and all-caps) and refuses third-party look-alikes made only of ACORD vocabulary.
  - The ACORD 25 holder box becomes an owned blank when the document's holder was a placeholder.

### Also closed in my area (owner asked "fix all")
- **The picker compared two spellings of one agency** ("COMMERCIAL RISK SOLUTIONS, INC." vs "CRS Insurance Brokerage") as "materially different entities". FIXED: they fold into one answer.
- **A stored producer confirmation of the old agency** (`e7084347`: `producer_name = COMMERCIAL RISK SOLUTIONS, INC.`) would re-apply it on every rebuild. FIXED: redirected to `expiring_producer_name`.
- **"Certificate requested - add ACORD 25" soft stop** fired on any uploaded COI. FIXED: an uploaded COI alone no longer counts; a named real holder still does.
- **`sqs_service.risk_transfer_check` read `has_certificate_holder_requirement`, which nothing writes.** FIXED: reads the real holder.

## 3. Every change I made

| file | function / constant | new / modified | what it does now | why |
|---|---|---|---|---|
| backend/services/extraction_pipeline.py | `_finalize_pipeline` | modified | reads `organization_name` / `full_name` via `repositories.user_repository.get_user_by_id(user_id)` on every run (fail-open: None -> old behaviour), passes `submitting_account=` to `merge_facts` | the submitting producer exists only in the account |
| backend/services/extraction_service.py | `_ACCOUNT_PRODUCER_SOURCE`, `_producer_text`, `_account_producer_envelope` | new | account values are labelled `source: "account"`, `evidence_state: "user_confirmed"`, `evidence_actor: "producer"` | provenance of an account-sourced fact |
| same | `_usable_account_agency` | new | refuses an account org that is a non-answer ("N/A", "TBD", "none") via `answer_semantics.interpret_answer` and `names_a_party` | junk org must not print as producer |
| same | `_route_producer_party` | new | moves the whole producer block when the submitting agency (one submission-doc agency, else the account) differs from an expiring doc's agency. Document agencies are clustered first. Unidentifiable names are ignored, and an unplaceable expiring agency stops the move. Only documents that NAME the submitting agency contribute. The account is ignored when it is the applicant. | client item 11; key-by-key produced a mixed identity |
| same | `_keep_one_agency_per_block` | new | after the per-key path, replaces or clears a producer value only when every document stating it names a provably different agency | no-login / declined cases mixed two agencies |
| same | `_submission_names_one_agency` | new | gate: the per-key "submission wins" swap runs only when all named agencies are the one the submission names | the per-key swap stitched agencies |
| same | `_route_producer_identity` | modified | new `account=None` param; calls `_route_producer_party` first; per-key swap gated by `one_agency`; unnamed submission docs no longer count; ends with `_keep_one_agency_per_block` | as above |
| same | `_THIRD_PARTY_NAME_KEYS`, `_THIRD_PARTY_NESTED_NAME_KEYS`, `drop_non_party_names` | new | clears `certificate_holder` / `loss_payee_name` / `mortgagee_name` (and the `risk_transfer.*` copies) when the text names no party; also clears a narrative/prose fact in the same doc holding that exact text | item 12, fixed where the fact is born |
| same | `merge_facts` | modified | new `submitting_account=None` param; runs `drop_non_party_names` per document; records rejected party keys in `_rejected_facts` (via existing `_record_fact_rejection`) after `_strip_non_value_facts`; passes the account to routing; log text changed | as above |
| backend/services/fact_comparison.py | `_AGENCY_LEGAL_WORDS`, `_AGENCY_SUFFIX_WORDS`, `_AGENCY_COMMON_WORDS`, `same_agency`, `__all__` | new / modified | True / False / None "same agency?"; initialism ("CRS" = Commercial Risk Solutions); partial overlap or no identity -> None; single letters ignored | one door for agency sameness |
| backend/services/field_mapping_integrity.py | `_PARTY_CLAUSE_TAILS` | modified | + "copy", "copies" | "Agency Copy", "File Copy" |
| same | `_DOCUMENT_STATUS_WORDS`, `_VOCAB_CONNECTORS`, `_ACORD_VOCAB_CACHE`, `_acord_vocabulary`, `_segment_glued_caps`, `_made_only_of_form_words` | new | reads ACORD field-name and tooltip vocabulary from `forms_schemas` once; splits all-caps glued text; detects "names" made only of form vocabulary | look-alikes / OCR glue |
| same | `_respace_run_together` | new | re-spaces a glued token (camel-case, or all-caps via vocabulary) into 3+ words; never re-spaces a glued legal name | `ForInformationalPurposesOnly` passed |
| same | `names_a_party` | modified | new params `third_party=False`, `respace=None`; third party: re-space, refuse role labels, refuse form-vocabulary-only names without a legal suffix. Defaults unchanged. | items above |
| backend/services/normalization.py | `_PARTY_ROLE_LABELS` | modified | + landlord, lessor, lessee, tenant, building owner, property owner | role, not a party |
| backend/services/pdf_service.py | `_SUBMITTING_PRODUCER_BOX_RE`, `_PRODUCER_ROW_SUFFIX_RE`, `_PRODUCER_BOX_TO_FACT`, `_resolve_submitting_producer` | modified | owns EVERY `Producer_*` box except the signature. Once a DIFFERENT expiring agency is recorded, it stamps only the submitting side's own fact, else an owned blank. Row letter stripped (the old `\w+` swallowed `_A`). Incumbent / cannot-tell -> unchanged. | old agency must not reach any producer box |
| same | `_REJECTED_PARTY_BOX_RE`, `_REJECTED_PARTY_BOX_FACT`, `_resolve_rejected_party_box`; call in `_deterministic_map`; entry in `_AUTHORITATIVE_BLANK_RESOLVERS` | new | CertificateHolder / Mortgagee / LossPayee boxes are owned blanks when the fact was rejected as a placeholder | gap fill re-read the placeholder |
| same | `_names_a_party` + its call in `_enforce_post_fill_guards` | modified | third-party boxes judged as third party; a GAP-FILLED insured box is re-spaced; a gap-filled insured CONTACT box gets the full third-party test; the applicant's own deterministic name is never re-spaced | glued / look-alike text in party boxes |
| same | `map_facts_to_form`, loop over `_drop_fabricated_interest_rows` | modified | row cells dropped with their row (not the name) are added to `_cascade_blanked` | the "131 fields" review-screen noise (`test_two_account_divergence` caught it) |
| backend/services/underwriting_consistency.py | `_fold_one_agency_printings` | new | folds `producer_name` value groups `same_agency` calls one agency | false "materially different entities" card |
| same | `_producer_block_separated` | new | True when `expiring_producer_name` is a different agency from `producer_name` | gate for the two changes below |
| same | `assess_underwriting_consistency` | modified | skips `producer_*` rows when separated (key stays in `assessed_keys`); folds `producer_name` printings | card must not offer the old agency |
| same | `apply_confirmations` | modified | when separated, a producer confirmation not naming the submitting agency is written to `expiring_producer_*` instead | `e7084347`'s stored CRS confirmation |
| backend/services/cross_form_validator.py | `_check_certificate_requested_but_missing` | modified | `has_certificate_request` counts only when `is_certificate_doc` is not set; a named holder / holder address still counts | an uploaded COI is not a request |
| backend/services/sqs_service.py | `risk_transfer_check` | modified | certificate item keyed on a real `certificate_holder` (was the never-written `has_certificate_holder_requirement`) | phantom flag |
| frontend/src/components/form/AcordModal.jsx | `_AUDIT_SOURCE_LABEL` | modified | + `account: "Producer's own agency, from their Primble account"` | new fact source label |
| backend/tests/test_party_role_14sep.py | whole file | new | 132 tests | coverage of all the above |
| v1-20AUG.md | section "ORBIN - who is this party, and in what role (2026-09-14)" | new | change log, D6, left items | repo rule |
| 11sep-form-improvement.md | section "14 SEP - items 4 and 8 on the REAL Orbin package (party chat)" | new | corrects the "live-verified" status; live-run-4 checklist changes | the 11 Sep claims were for a synthetic kit |

Not changed: CLAUDE.md, improving-ll.md, any prompt, `PROMPT_VERSION`, `SCHEMA_VERSION`, any `forms_schemas` file. I ran `npm run build` in `frontend/`; `frontend/dist` is gitignored. Scratch scripts are outside the repo.

## 4. Tests I changed or deleted (not added)

None. I did not edit any existing test file.

(Within my own new file, during development, I removed one test that asserted the incumbent's two-spellings card still appears. Removing that card is an intended change. I also moved `("A Agency", "B Agency")` from "different" to "cannot tell", because single letters are now noise.)

## 5. Prompt / LLM changes

- Prompt text, extraction schema, batching, chunking, model setting: **none**.
- `PROMPT_VERSION` / `SCHEMA_VERSION`: not touched. They read `"v21"` / `"v21"` on disk now (`extraction_service.py:53-54`), set by other chats. The value when I started is unverified.
- LLM cost: no new or removed calls, and not measured on a live run. Fewer fields reach gap fill:
  - producer boxes become owned blanks when the agencies are separated;
  - the ACORD 25 holder box becomes an owned blank when the holder was a placeholder;
  - the placeholder facts leave the gap-fill facts block.

  Expect a small decrease. One extra database read (users row) per pipeline run.
- Model change recommended: **No.** For #11 the right value is in no document. For #12 extraction read the box correctly; nothing checked whether it names a party. Both were fixed deterministically.

## 6. Shared code I touched

| shared code | other callers | how I checked |
|---|---|---|
| `merge_facts` | `_finalize_pipeline` (all 8 pipeline callers), `scripts/restore_session_facts.py`, ~20 test files | new kwarg defaults to None = old behaviour; source-inspection tests (`test_v1_c1_canonical_facts`, `test_review_screen_warnings_20260816`, `test_roster_party_and_lob_20260905`, `test_sys09_...`) pass; 100 real-session replays, 0 crashes |
| `names_a_party` | pdf post-fill guard, my merge door, `test_form_improvement_11sep` | default args unchanged; 11sep tests pass; 49 boxes x 15 real names: none blanked; 547 stored real names: none refused |
| `_PARTY_ROLE_LABELS` / `is_party_role_label` | `pdf_service._rejects_role_or_arrangement` (Guard 3c), `extraction_service` role-label filter (~11035) | only adds whole-value role words; related tests pass |
| `_resolve_submitting_producer`, `_AUTHORITATIVE_BLANK_RESOLVERS` | `_deterministic_map`, owned-blank check, the owner door used by Field QA | incumbent / no-expiring paths return `_SCHED_SKIP` exactly as before (tests); all 17 forms replayed |
| `assess_underwriting_consistency` | pipeline, picker routes, `dump_session_facts.py` | producer keys stay in `assessed_keys`, so `detect_source_conflicts` still skips them; tests pass |
| `apply_confirmations` | pipeline | only acts when separated; other keys untouched (tests) |
| `_check_certificate_requested_but_missing` | cross-form rule list | tests for both directions |
| `risk_transfer_check` | per-form SQS `compliance_checklist` | advisory list only |
| `_enforce_post_fill_guards` / `map_facts_to_form` cascade | every form fill | `test_two_account_divergence_20260813`, `test_line_binding_14sep`, `test_run_20260813g` pass |

Final full suite I ran (14 Sep, before handoff): 8367 passed / 1 failed. The failure is `test_arq_acord125_missing_only`, the known httpx ImportError. One earlier run showed 16 more failures while another chat edited arq / pdf / pipeline files mid-run; all 16 passed when re-run.

## 7. Scores that move

- **Producer address, phone, fax, email:** go BLANK on packages where the login's agency differs from the documents' agency (ACORD 125 / 25 producer block). Fill rate slightly DOWN. On those same packages the "Producer Name: documents disagree" conflict (a soft stop, 85 cap) is gone, so UP where it was the only soft stop.
- **Producer card with two spellings of one agency** (e.g. CRS vs Commercial Risk Solutions): no longer a conflict. UP where it was the only soft stop.
- **"A certificate of liability was requested ... Add ACORD 25"** soft stop: no longer fires when the only evidence is an uploaded COI with no named holder (Orbin had it). UP.
- **Look-alike third-party names** ("Proof of Insurance"...) now blank. Fill rate slightly DOWN.
- **Certificate checklist item:** now appears when a real holder is named. Advisory only, no score. Unverified whether any screen renders it.
- **Tier 1 `producer_name`:** unchanged. Present before (CRS) and after (ThinkSmith). Packages where no document names a producer do NOT get the account.

## 8. Live test checklist

**Precondition:** upload while logged in as the account whose profile reads organization **ThinkSmith Agency LLC**, name **Michelle Smith** (user `ed40f6a3-1d3e-4daf-a732-0b65f1f48d68`). Under any other account the producer block shows THAT account's organization. That is correct behaviour, not a bug.

| # | where to look | expected when FIXED | if still BROKEN |
|---|---|---|---|
| 11 | ACORD 125 `Producer_FullName_A` (AGENCY) | ThinkSmith Agency LLC | Commercial Risk Solutions, Inc. / COMMERCIAL RISK SOLUTIONS, INC. |
| 11 | ACORD 125 `Producer_ContactPerson_FullName_A` (CONTACT NAME) | Michelle Smith | Terri Wroblewski |
| 11 | ACORD 125 producer phone / fax / email / address boxes | blank | 303-996-7800 / 303-757-7719 / twroblewski@crsdenver.com / 9780 S Meridian Blvd, Englewood |
| 11 | ACORD 125, 126, 127, 131 `Producer_AuthorizedRepresentative_FullName_A` (PRODUCER'S NAME by the signature) | Michelle Smith | Terri Wroblewski |
| 11 | ACORD 126, 127, 131 `Producer_FullName_A` | ThinkSmith Agency LLC | Commercial Risk Solutions, Inc. |
| 11 | Data Consistency screen | no "Producer Name" card | card comparing COMMERCIAL RISK SOLUTIONS, INC. vs CRS Insurance Brokerage |
| 11 | Warnings list | no "Producer Name: documents disagree" | that warning |
| 12 | ACORD 127 Additional Interest row A (`AdditionalInterest_FullName_A`, city, account number, rank) | all blank | For Informational Purposes Only / Denver / 0482854 / 1 |
| 12 | ACORD 125 and 126 `AdditionalInterest_FullName_A` / `_B` | blank | For Informational Purposes Only |
| 12 | Any generated form, search the text "Informational" | not found | found in any box |
| 12 | ACORD 25 (only if selected) `CertificateHolder_FullName_A` + address | blank | For Informational Purposes Only, or the insured's address |
| 12 | Warnings list | no "A certificate of liability was requested (certificate holder detected) but ACORD 25 is not in the selected forms" | that warning |

## 9. Not done, not verified, risks

- **Not live-verified.** Gap fill (a paid LLM call) was not re-run. Replays used the session's own stored gap-fill answers plus the COI's OCR spelling. The account read was verified against the real database offline (`get_user_by_id` returned ThinkSmith Agency LLC / Michelle Smith), not through a real upload request.
- **Async worker path:** if a worker has no DB pool, the account read fails open (old behaviour: CRS prints). Unverified.
- **Residuals, deliberately not fixed:**
  - a 3-letter placeholder acronym ("FIO");
  - look-alikes that gap fill writes into an insured COMPANY-name box (the vocabulary rule is off there, because insured names are often ordinary words);
  - an account org typed as "Test" or a person's name is printed as the producer;
  - values from a document naming NO agency are kept;
  - a third party printed without a suffix as "Commercial Credit" / "National General" would be blanked.
- **Not mine:** the COI's real description ("Reduced Umbrella Limit from $3,000,000 to $1,000,000 Effective 7/25/25") was never extracted; it belongs to the umbrella chat. My merge door removes the placeholder from `certificate_description_of_operations`, and does not add the real text.
- **Behaviour changes others will see:**
  - The producer follows the login, so testers see their own agency.
  - The 11 Sep kit's Run B (MERIDIAN) now prints the tester's org, not Cascade.
  - HALVORSEN no longer shows the producer card.
- **Assumptions:** an uploaded COI's `is_certificate_doc` flag is reliable. A real certificate request that names no holder, in a package that also contains a COI, is no longer flagged.
- **Possible conflicts:** five chats edited the same files. My `_rejected_facts` record runs after `_strip_non_value_facts` in `merge_facts`. If another chat adds a later step that strips private keys, the ACORD 25 owned blank reverts to gap fill (the post-fill guard still refuses the phrase). Unverified against other chats' final code beyond my tests passing on the current tree.

## 10. My test results

`py -m pytest -q -p no:randomly tests/test_party_role_14sep.py` from backend/ (15 Sep): **132 passed, 0 failed.**
