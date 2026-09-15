# Handoff - problems 6-8: comparisons that should never happen, and the umbrella as a dated change

- **Chat number:** my prompt gave none. I owned problems **6, 7 and 8**, so the file is named after them.
- **Not committed.** Every result below is offline: no paid calls were made.
- **Where the evidence comes from:**
  - Session `e7084347` - the client's 10 Sep run with forms. Its stored confirmations are `{"policy_number": "IM 7100 06 04", "producer_name": "COMMERCIAL RISK SOLUTIONS, INC.", "umbrella_limit": "$1,000,000"}`.
  - Session `5037f1a6` - the latest extraction.
  - The merged facts will not decrypt locally, so I replayed the merge on the current code from the stored per-document facts.
  - What the producer actually saw comes word for word from the `sqs_recommendation_audit` and `underwriting_confirmation_audit` tables.
- **Line numbers:** "now" means on disk today. "then" means before my edits, as quoted in my diagnosis.

## 1. Problems I owned

6. Separate policies flagged as conflicts because their numbers or NAICs differ - including the four correct numbers in ACORD 125's Other Policy section
7. Comparisons between values that are not the same thing: a $2M limit vs a Per Location / Per Project Yes/No box; a Claims Made indicator vs the words "Commercial Liability Umbrella Coverage Form"; a policy number vs a form number
8. The umbrella $3M -> $1M change treated as a conflict instead of a change over time

Scope, also mine: list every comparison site, and own the umbrella limit end to end, including what ACORD 131 prints.

## 2. Per problem

### Problem 6 - separate policies / NAICs / ACORD 125 Other Policy

**Reproduced: Yes.** The 10 Sep audit rows (`e7084347`) show:
- The Data Consistency picker offered only `IM 7100 06 04` / `IM 7201 10 02` as policy numbers, and the producer confirmed `IM 7100 06 04`.
- Field QA then flagged:
  - the policy boxes on 126, 127 and 131 ("source value is IM 7100 06 04");
  - ACORD 125 Other Policy row A ("shows BBC7263 - 26 but source value is IM 7100 06 04");
  - the 125 NAIC ("shows 21415, source 25186").

**Already fixed before I started (not by me):** on the code I found on 14 Sep, policy number and NAIC already came out "scoped" (4 policies on 4 lines). That was earlier 11 Sep work.

**Still broken when I started:**
- The stored `IM 7100 06 04` confirmation was still read as the answer by the card, by both conflict-key lists and by Field QA.
- The carrier's own form references (`CU7001A 11-15`, `IL 71 31A 04 01`, `CG 70 01A 10 12`) passed as policy numbers.

**Root cause:**
- `field_qa.run_field_qa` compared each form's own box with one package value, or with the confirmed value (field_qa.py:173-190 then). Class (e), plus (d): the relationship was lost at comparison.
- The form-number test only knew the ISO/AAIS shape (`extraction_service._looks_like_a_form_number`, :8226 then). Class (e).
- `apply_confirmations` was the only reader that ignored a form-number confirmation - one rule, several readers. Class (e).

**Status: FIXED (offline).**

**What changed:**
- `underwriting_consistency.usable_confirmations` (:1539) is now the one door every confirmation reader uses.
- `pdf_service.box_expectation` (:16523) asks the box's owner first.
- `_drop_unknown_form_references` (:1601) sets a form-shaped candidate aside only when all three hold:
  - a verified declarations index exists;
  - no known contract matches the candidate;
  - at least one kept candidate is a known contract.

### Problem 7a - $2M vs the Per Location / Per Project Yes/No box

**Reproduced: Yes.** Two audit rows (`e7084347`): "...LimitAppliesPerLocationIndicator shows No but the source value is $2,000,000", and the same for Per Project.

**Root cause:** `pdf_service._ACORD_FIELD_RULES` is first-match-wins. `("GeneralLiability_GeneralAggregate", "gl_aggregate")` (:1364 then) sat above the `..._LimitApplies -> None` rule (:1408 then), so the None rule never fired. Class (e).

**Status: FIXED for the client's example** (the 4 aggregate-basis tick boxes). **NOT FIXED** for two related bindings:
- The 126/25 "other basis" text box `GeneralLiability_GeneralAggregate_LimitAppliesToCode_A` still maps to `gl_aggregate`. This is deliberate; the comment is at pdf_service.py:1372-1374.
- ACORD 160's liquor aggregate still maps to `gl_aggregate`.

**What changed:** four specific None rules at pdf_service.py:1375-1378, placed above the `gl_aggregate` rules (:1379-1382). Stamping is unchanged, because the Yes/No gate already sent these ticks to gap fill.

### Problem 7b - Claims Made tick vs "Commercial Liability Umbrella Coverage Form"

**Reproduced: Yes.**
- Two audit rows, on 126 and 131.
- It still happened on the code I found: all 12 tick/value pairs I tried came out as a mismatch, including the correct "Occurrence".
- What each document's facts held for `gl_form_type`:
  - `e7084347` dec page: "COMMERCIAL LIABILITY UMBRELLA COVERAGE FORM";
  - `5037f1a6` dec page: "CG 00 01 04 13";
  - the COI: "OCCUR".

**Root cause - three stacked causes:**
- **(e)** Field QA compared a tick with the fact's wording. `pdf_service.expected_value_for_field` had no checkbox case.
- **(b)/(c)** `gl_form_type` had no definition and no tie to the GL line: it was `"gl_form_type": string or null` (extraction_service.py:233 then).
- **(e)** The card's allowed-values check was an exact match (`underwriting_consistency._declared_domain_check`, :1311-1320 then). So the COI's correct "OCCUR" counted as illegal, and "CG 00 01 04 13 vs OCCUR" stayed a conflict.
- Also, ACORD 131/25's **umbrella** Occurrence / Claims-Made ticks read the GL fact (`_INDICATOR_RULES`).

**Status: FIXED (offline).** The 131 umbrella ticks need a fresh v21 extraction to fill.

**What changed:**
- `expected_tick_for_box` and `box_expectation`: a checkbox is compared by the tick its fact implies, never by the fact's wording.
- `option_named_by`: "OCCUR" names Occurrence, and the card folds two printings of one option into one.
- Prompt v21 defines `gl_form_type` and adds `umbrella_form_type`.
- `coverage_basis` canonicalises each document's value at merge.
- The 131 umbrella ticks now read `umbrella_form_type`.

### Problem 7c - policy number vs form number

**Reproduced: Yes** - the `IM 7100 06 04` rows under problem 6.

**Root cause:** same as problem 6 (class e).

**Status: FIXED (offline),** by the same changes as problem 6.

### Problem 8 - umbrella $3M -> $1M

**Reproduced: Yes.** What the documents say:
- **Policy, page 143** (umbrella declarations, 6J7-40-02---26) prints `Each Occurrence Limit (Liability Coverage) $ 3,000,000` and `Aggregate Limit (Liability Coverage) $ 3,000,000` (271page-testdec.txt:9275-9278). No page of the policy mentions a reduction.
- **COI (dated 8/14/2025)** - the umbrella row reads `UMBRELLA LIAB X OCCUR 6J74002 ... EACH OCCURRENCE $1,000,000 / AGGREGATE $1,000,000`.
- **The COI remark in OCR:** `Note:ReducedUmbrellaLimitfrom$3,000,000to$1,000,000LimitEffective7/25/25.` (e7084347 COI text, line 52).
- **The extracted COI fact** `additional_remarks_text`: "Note: Reduced Umbrella Limit from $3,000,000 to $1,000,000 Limit Effective 7/25/25."

What the product did on the code I found:
- The card showed a conflict with no explanation.
- ACORD 131 Each Occurrence and Aggregate were withheld (blank) until someone confirmed.
- A warning capped the score at 85.
- On 10 Sep the producer had to confirm $1,000,000.

**Root cause:**
- **(c)/(d)** `umbrella_limit` is one undated value. The dated change lived only in the remark text.
- **(e)** Three readers then treated it as two undated rivals:
  - `extraction_service._flag_intra_document_limit_conflicts` read both amounts in the sentence as a conflict and withheld the box (:9486-9489 then; :9741 now);
  - the card had no time axis;
  - `narrative_facts._subject_for` looked only BEFORE the verb (:189-212 then; :217 now). So "Reduced Umbrella Limit from..." produced no statement and no explanation.

**Decision:** a change the documents state as done, for that same fact, dated inside the policy term, is not a conflict. Anything less stays a conflict. This respects the client's rule that an unresolved conflict stays unresolved.

**Status: FIXED (offline).**

**What changed:**
- `fact_comparison.dated_change` (with `fact_term` and `document_as_of`) is the rule.
- The merge writes the current value (`_apply_dated_changes`), and the withhold skips it.
- The card shows the row as `changed`, and the UI shows a read-only row for it.
- The sentence reader finds a subject after the verb. It marks negated, requested, conditional and question sentences as not asserted, and the change rule ignores them.

### Scope item - one door for every comparison site

**Status: PARTLY FIXED.**
- Field QA and the post-generation stamp check now share `box_expectation`.
- The merge and the card share `dated_change`.
- **NOT moved:** the other comparison sites from my diagnosis (the cross-form date rules; the SQS row that string-searches messages, sqs_service.py:4563 then; the rest of the 18 I listed). `test_comparison_has_one_owner` was not extended to cover them. This needs a follow-up.

## 3. Every change I made

| file | function / constant | new / mod / del | what it does now | why |
|---|---|---|---|---|
| backend/services/fact_comparison.py | `_INCEPTION_DATED_DOC_TYPES` (:637) | new | doc types dated by policy inception: dec_page, policy, binder | only these can be the proven-older side of a change |
| " | `fact_term` (:640) | new | ISO (start, end) of the fact's own line term, else the package term | a change must fall inside the term |
| " | `document_as_of` (:669) | new | inception date for dec_page / policy / binder, else None | an undated printing never proves it came first |
| " | `dated_change` (:685) | new | returns current / prior / as_of / quote / doc indexes when every gate holds, else None. Skips unasserted statements. Two different amount pairs (dated in term, or undated) -> None | the time axis the one door lacked (problem 8) |
| backend/services/narrative_facts.py | `_AMOUNT_RE` (:79) | mod | keeps a K / M / MM / B multiplier | "$3M" was read as $3 |
| " | `_NEGATION_RE`, `_UNREALISED_RE`, `_CONDITION_RE`, `_ASSERTION_WINDOW_WORDS` (:121-125) | new | cue words for the guard below | - |
| " | `_asserts_the_change` (:128) | new | False when the verb is negated, modal or "be" + participle, conditional, or a question | "was not reduced" / "requests it be reduced" read as a done change and stamped $1M |
| " | `_subject_inside` (:243) | new | finds the label between the change verb and "from" | the client's literal sentence puts the subject after the verb |
| " | `mine_statements` (:299; :319, :330) | mod | reads the subject after the verb first; every amendment carries `asserted` | as above |
| " | `statements_for_facts` (:354; :391) | mod | reads each document first and tags `source_doc_index`, then the merged facts | the rule must know which document states the change |
| " | `explain_conflict` (:398; :420) | mod | skips unasserted statements | a negated sentence must never read back as "the remarks state this was reduced" |
| backend/services/extraction_service.py | `PROMPT_VERSION`, `SCHEMA_VERSION` (:53-54) | mod | v20 -> v21 | schema edit (see section 5) |
| " | `_EXTRACT_SCHEMA` (:233, :240) | mod | the old line `"gl_deductible": string or null, "gl_form_type": string or null,` was split. `gl_deductible` is unchanged (:233); `gl_form_type` is now `"Occurrence"\|"Claims-Made"\|null`, the GL part only (:240). The comment at :234-239 is Python, not prompt text | problem 7b |
| " | `_EXTRACT_SCHEMA` (:320) | new | `umbrella_form_type` - the umbrella's own trigger | the 131 umbrella ticks were reading the GL fact |
| " | `_flag_intra_document_limit_conflicts` (:9741; :9769-9774) | mod | treats a `document_amendment` value's current + prior amounts as one value, not two; any third amount still withholds | problem 8 |
| " | `_COVERAGE_BASIS_FACTS`, `_ISO_GL_FORM_BASIS`, `_BASIS_LIMIT_LABEL_RE`, `_OCCURRENCE_WORD_RE`, `_CLAIMS_MADE_WORD_RE` (:9859-9868) | new | vocabulary for `coverage_basis` | - |
| " | `coverage_basis` (:9871) | new | printing -> "Occurrence" / "Claims-made" / None. Order: the option or its caption; then the words, unless both appear or it is a limit label; then ISO CG 00 01 / 00 02 (GL only). Words that disagree with the ISO number -> None | problem 7b |
| " | `_canonicalise_coverage_basis` (:9907) | new | per fact dict: rewrites to the basis, or drops the value (the raw text is kept as `raw_value`) | - |
| " | `_apply_dated_changes` (:9938) | new | writes `{"value": current, "source": "document_amendment", "confidence": "ai_high", "as_of", "prior_value", "evidence", "evidence_document"}` | problem 8 |
| " | `merge_facts` (:10641, :10984) | mod | canonicalises each document's basis facts in the per-document loop; applies dated changes just before the withhold | - |
| backend/services/underwriting_consistency.py | `unresolved_withheld_keys` (:654 / :664), `unresolved_conflict_keys` (:676 / :695) | mod | count only usable confirmations | problems 6 / 7c |
| " | `_declared_domain_check` (:1289; :1320) | mod | closed-list check is now `option_named_by(...) is not None` | "OCCUR" was illegal |
| " | `_drop_values_outside_declared_domain` (:1340; :1430-1464) | mod | folds value groups that name the same option (the keeper keeps the fuller display and every source); logs drops and folds | "CG 00 01 04 13 vs OCCUR" |
| " | `usable_confirmations` (:1539) | new | drops a confirmation of a policy-number key whose value is form-number-shaped; the stored record is kept | problems 6 / 7c |
| " | `_FORM_REFERENCE_RE` (:1575) | new | 2-3 letters + series + MM YY tail, with no run of 5+ digits | carrier form references |
| " | `_verified_contracts` (:1579) | new | policy numbers from `dec_page_entries`, merged and per document | - |
| " | `_drop_unknown_form_references` (:1601) | new | see problem 6 | - |
| " | `_dated_change_for_field` (:1641) | new | turns the card's value groups into `dated_change` input; skips text-scan sources; adds document filenames | problem 8 |
| " | `assess_underwriting_consistency` (:2413; :2454, :2787, :2877-2884, :2971-2976, :2999) | mod | uses usable confirmations; applies the form-reference filter; adds the `changed` status (no review); writes the changed-row note; puts a `change` dict on the row | - |
| " | `apply_confirmations` (:3261; :3281) | mod | reads usable confirmations only | - |
| " | `verify_stamped_consistency` (:3417; :3504) | mod | asks `box_expectation`; compares only value expectations | one box door |
| backend/services/pdf_service.py | `_ACORD_FIELD_RULES` (:1375-1378, comment :1364-1374) | mod | 4 None rules placed above `gl_aggregate` | problem 7a |
| " | `_INDICATOR_RULES` ExcessUmbrella Occurrence / ClaimsMade (:9391-9392) | mod | now read `umbrella_form_type` (was `gl_form_type`) | problem 7b |
| " | `_resolve_via_field_rules` (:10944), `_deterministic_map_inner` (:12107) | mod | a declared choice box stamps the tick from `expected_tick_for_box` | stamper and checker read one rule |
| " | `expected_tick_for_box` (:16465), `_is_declared_choice_box` (:16514), `box_expectation` (:16523) | new | the box door | problems 6, 7 |
| backend/services/field_qa.py | imports (:39 `canonical_yes_no`; :150-151 `usable_confirmations`; :161 `box_expectation`) | mod | - | - |
| " | `run_field_qa` value check (:254-277) | mod | asks `box_expectation`; a tick counts as a mismatch only when the stamped value reads as yes/no and differs | problems 6, 7 |
| backend/services/answer_options.py | `_OPTION_CAPTION_MIN` (:350), `option_named_by` (:353) | new | an option, or an unambiguous 4+ character truncation of one | "OCCUR" |
| " | `_CATALOGUE["umbrella_form_type"]` (:298) | new | same options as `gl_form_type` | the tick door can read the 131 umbrella ticks |
| frontend/src/components/form/AcordModal.jsx | Data Consistency visibility (:7055) | mod | the section also shows when a row is `changed` | - |
| " | changed rows (:7160-7195) | new | read-only badge "Changed during the policy term - not a conflict", Now / Before lines, and the note | problem 8 |
| backend/tests/test_comparison_guards_14sep.py | whole file | new | 40 tests | - |
| backend/tests/test_remaining_fixes_14sep.py | whole file | new | 109 tests (65 + 44 `TestBreakValues`) | - |
| backend/tests/test_h3_wc_data_capture.py | `test_extraction_schema_carries_the_counts_and_moved_to_v17` | mod | version pin v20 -> v21 | see section 4 |
| backend/tests/test_line_binding_14sep.py (file created by another chat) | `test_rule_16_defines_the_form_number_and_moved_to_v20` | mod | version pin v20 -> v21 | see section 4 |
| backend/tests/test_dec_index_purge.py | `test_every_consumer_of_the_index_runs_at_or_before_generation` | mod | `known_files` gained `underwriting_consistency.py`, with its reason | see section 4 |
| improving-ll.md | "C89" (:3937) | new | the v21 prompt change | the prompt-change rule |
| v1-20AUG.md | three entries (:10496 safe half, :10553 remaining half, :10588 break-it pass) | new | change log | - |
| 11sep-form-improvement.md | status block (:18 onward) + section "# ROUND 6" (:1644) | mod + new | heading "AFTER ROUND 6"; "10 of 11 fixed"; run-table row 6; round-6 suite line; "Open, in order"; item 9 row; pointer paragraph; full round-6 log | owner asked |
| CLAUDE.md | - | **not touched by me** | - | git shows it modified: that is another chat |
| outside the repo | memory `client-session-offline-replay.md` + its MEMORY.md line; scratch scripts in my scratchpad | new | - | - |

## 4. Tests I changed (not added)

| test | before | now | was the TEST wrong? |
|---|---|---|---|
| `test_h3_wc_data_capture.py::test_extraction_schema_carries_the_counts_and_moved_to_v17` | `PROMPT_VERSION == SCHEMA_VERSION == "v20"` | `== "v21"`, and the docstring names C89 | No. It pins the version so a schema edit must bump it; my schema edit bumped it |
| `test_line_binding_14sep.py::test_rule_16_defines_the_form_number_and_moved_to_v20` | `PROMPT_VERSION == "v20"` | `== "v21"`, docstring notes RULE 16 is unchanged | No. Same tripwire |
| `test_dec_index_purge.py::test_every_consumer_of_the_index_runs_at_or_before_generation` | no `underwriting_consistency.py` in `known_files`, so it failed when `_verified_contracts` started reading `dec_page_entries` | lists the file, with the purge-safety reason: it reads the per-document copies the purge never deletes, and with no index it has no opinion | No. The test is designed to force exactly this decision; I made it and recorded it |

No test was deleted.

## 5. Prompt / LLM changes

- **Prompt text:** yes. `_EXTRACT_SCHEMA` in backend/services/extraction_service.py (the extraction call, LLM call 1): lines :233 / :240 (`gl_form_type` defined) and :320 (`umbrella_form_type`, new).
  - No batching, chunking or model setting changed.
  - No gap-fill prompt changed.
- **Versions:**
  - `PROMPT_VERSION` / `SCHEMA_VERSION` were **v20** when I started (bumped earlier on 14 Sep by another chat, improving-ll.md C88).
  - I set **v21** (:53-54).
  - For reference, the HEAD commit has v18. On disk now: v21.
- **Cost per package:**
  - The number of calls is unchanged.
  - Each extraction call grows by about +570 characters, roughly 140 tokens at 4 characters per token. This is **estimated, not tokenized**, and it sits inside the cached prefix. improving-ll.md C89 says "~+90 tokens", which is low; use this figure.
  - One-time cost: v21 invalidates the extraction cache, so every package re-extracts once.
  - Output: one extra short field per reply (unmeasured).
- **Model change recommended: No.** The model returned the right values every time: $3,000,000 from the umbrella dec, $1,000,000 and the remark from the COI, and "OCCUR". Every failure happened in code after the model, so this is not a class (f) failure.

## 6. Shared code I touched

| shared thing | other callers (grep, on disk now) | what I checked |
|---|---|---|
| `merge_facts` | the whole pipeline and every re-run | Full suite on 14 Sep: 8,301 passed, 6 failed. 5 were in `test_screen_level_coverage_14sep.py`, which another chat rewrote mid-run; they pass on re-run (14 passed, 2 xfailed). 1 is the known `httpx` failure. Both real sessions replayed |
| `_flag_intra_document_limit_conflicts` | `merge_facts` only | the exemption applies only to `source == "document_amendment"`; a third amount is still withheld (test) |
| `statements_for_facts` | extraction_service.py:9628 (drops an endorsement date from the policy dates), :9947 (`_apply_dated_changes`), underwriting_consistency.py:2491 (the card) | The :9628 reader uses only `kind` and `as_of`, so unasserted statements still reach it, by design. `test_narrative_facts_20260817.py` passes |
| `mine_statements`, `_AMOUNT_RE` | narrative_facts only | same |
| `explain_conflict` | underwriting_consistency.py:2964 | tests |
| `option_named_by` | underwriting_consistency.py:1320, :1433; pdf_service.py:16502; extraction_service.py:9883 | `test_underwriting_consistency.py` and `test_answer_options.py` pass |
| answer-option catalogue (+ `umbrella_form_type`) | `options_for` / `control_for` readers: arq_service.py:692, issue_registry.py:291, answer_semantics.py:488, underwriting_consistency.py:1318, `expected_tick_for_box` | `umbrella_form_type` has no FACT_REGISTRY entry, question or card, so only the card's allowed-values check and the tick door read it. The catalogue round-trip test covers it |
| `_drop_values_outside_declared_domain` | every closed-list fact on the Data Consistency card | it can only keep more values, or fold printings of one option; `test_underwriting_consistency.py` |
| `usable_confirmations` | `apply_confirmations`, both `unresolved_*` lists, `assess_underwriting_consistency`, `field_qa` | it ignores only policy-number keys whose value is form-number-shaped |
| `_ACORD_FIELD_RULES` order | Pass 1 stamper; `fact_to_form_fields` (the Field QA map and the confirmation "applied to" list) | `test_stamping_is_unchanged` |
| `_INDICATOR_RULES` (ExcessUmbrella) | `_derive_indicator` (stamper) | tests; replay shows UNMATCHED until a v21 extraction supplies the fact |
| stamper choice-box path | `_resolve_via_field_rules`, `_deterministic_map_inner` | only fields `_is_declared_choice_box` claims. Measured: the 6 GL basis boxes on 126/131/25. Replay ticks Occurrence Yes / Claims-Made No |
| `gl_form_type` **values** (now canonical, or dropped when no basis is stated) | coverage_evidence.py:417 `gl_form_basis` (another chat's claims-made door); sqs_service.py:6821 and :6835 (ACORD 126 structure + recommendation); question_eligibility.py:127 (producer question); pdf_service `_LABELLED_ECHO_FACT_KEYS` (evidence gate) | **Read, not separately tested.** `gl_form_basis`'s regex matches "Occurrence" / "Claims-made". The score effects are in section 7 |
| `fact_comparison` (the one door) | many | `test_comparison_has_one_owner` passes |
| AcordModal Data Consistency panel | - | frontend build clean (14 Sep); **not viewed in a browser** |

## 7. Scores that move

**UP:**
- **Packages where a document states a dated limit change (Orbin):**
  - the umbrella is no longer a Data Consistency conflict, so its 85 cap lifts where it was the only soft stop;
  - `umbrella_limit` leaves `_uw_conflict_keys`, so its fill-rate credit is restored;
  - the 131 / 25 umbrella amount boxes fill.
- **Packages whose `gl_form_type` came out as a form number or caption** ("CG 00 01 04 13", "OCCUR"): no `gl_form_type` conflict card, so that soft stop is gone.
- **ACORD 126 / 131 / 25:** the GL basis ticks are now stamped by rule (Pass 1) instead of by gap fill, so their fill-rate confidence goes up.
- **Fewer policy-number conflicts** where the carrier's form references had been candidates.

**DOWN:**
- **Packages where every printing of `gl_form_type` is a form title with no basis** ("Commercial General Liability", "Business Auto Coverage Form", an umbrella form title): `gl_form_type` is now blank. As a result:
  - ACORD 126's structural score loses 1 of its 5 checks (sqs_service.py:6821);
  - the "Specify GL form type" recommendation appears (score_impact 5, sqs_service.py:6835-6844);
  - the producer is asked for it.

  **Not Orbin** - its COI states OCCUR.
- **Sessions extracted before v21:** the 131 / 25 umbrella Occurrence / Claims-Made ticks move from rule-stamped (from the GL fact) to gap fill until the package is re-extracted. Small.
- **A session where a producer confirmed a form number as the policy number, and the field is not scoped:** the confirmation no longer counts, so the policy-number conflict (85 cap) comes back. Not Orbin - its policy number is scoped.

**EITHER DIRECTION:** another chat's claims-made door (`coverage_evidence.gl_is_claims_made`) now reads the canonical basis.
- A dec page printing only "CG 00 02 ..." now states claims-made (before, the detector flag decided).
- "OCCUR" now states occurrence.
- This switches the claims-made checks (such as retro date) on or off. Magnitude: unverified.

**Unchanged:**
- No hard stop was added or removed.
- Field QA is advisory.
- Negated or requested change sentences stay conflicts, exactly as before my work.

## 8. Live test checklist

| problem # | where to look | expected when FIXED | if still BROKEN |
|---|---|---|---|
| 6 | Data Consistency - Policy Number | scoped (one value per policy), not a card to confirm: BBC7263 - 26 (GL), 6E7-40-02---26 (Auto), 6C7-40-02---26 (Inland Marine), 6J7-40-02---26 (Umbrella) | a conflict card between these, or `IM 7100 06 04` / `CU7001A 11-15` / `IL 71 31A 04 01` offered as a choice |
| 6 | Data Consistency - Carrier NAIC | scoped: 25186 (GL), 21415 (Auto, Umbrella) | a "25186 vs 21415" conflict |
| 6 | Pre-download review (Field QA) + ACORD 125 `OtherPolicy_PolicyNumberIdentifier_A..D` | the 4 numbers print (order unverified, except row D = Umbrella per `OtherPolicy_LineOfBusinessCode_D`); no Field QA row on them | "shows BBC7263 - 26 but the source value is ..." |
| 6 | ACORD 126 / 127 / 131 `Insurer_NAICCode_A` | 126 = 25186; 127 and 131 = 21415; no Field QA NAIC row | If 131 prints 25186, a Field QA row is CORRECT - that is a stamping defect (line identity), not a comparison defect. The stored 10 Sep 131 form carried 25186 |
| 7a | Pre-download review - ACORD 126 / 25 `GeneralLiability_GeneralAggregate_LimitAppliesPerPolicyIndicator_A` / `...PerProjectIndicator_A` / `...PerLocationIndicator_A` | no row | "shows No but the source value is $2,000,000" |
| 7b | ACORD 126 / 131 / 25 `GeneralLiability_OccurrenceIndicator_A` / `GeneralLiability_ClaimsMadeIndicator_A` | Occurrence ticked, Claims-Made not ticked; no Field QA row; no `gl_form_type` card in Data Consistency | a row comparing the Claims-Made box with "Commercial Liability Umbrella Coverage Form" (or any form title), Claims-Made ticked, or a "CG 00 01 04 13 vs OCCUR" card |
| 7b | ACORD 131 `ExcessUmbrella_OccurrenceIndicator_A` / `ExcessUmbrella_ClaimsMadeIndicator_A` (**fresh upload only**) | Occurrence ticked, Claims-Made not. The COI's umbrella row prints "UMBRELLA LIAB X OCCUR" | both blank (the v21 fact was not extracted), or copied from the GL basis |
| 7c | Data Consistency - Policy Number, on a **re-run of `e7084347`** (it holds the stored `IM 7100 06 04` confirmation) | not shown as "Confirmed: IM 7100 06 04"; Field QA has no "source value is IM 7100 06 04" rows on 126 / 127 / 131 | either of those |
| 8 | Data Consistency - Umbrella Limit (**fresh upload** - on a re-run of `e7084347` the stored $1,000,000 confirmation wins and the row shows Confirmed) | badge "Changed during the policy term - not a conflict". "Now: $1,000,000 - effective 7/25/25 (<COI filename>)". "Before: $ 3,000,000 (<policy filename>)" - the spacing follows the document. Note "<COI filename> states this changed from $ 3,000,000 to $1,000,000 effective 7/25/25: "Note: Reduced Umbrella Limit from $3,000,000 to $1,000,000 Limit Effective 7/25/25."" | a conflict card "$3,000,000 vs $1,000,000" asking to confirm |
| 8 | ACORD 131 `ExcessUmbrella_Umbrella_EachOccurrenceAmount_A`, `ExcessUmbrella_Umbrella_AggregateAmount_A`; ACORD 25 `ExcessUmbrella_Umbrella_EachOccurrenceAmount_A` (its Aggregate box is mapped but was not printed in my replay) | $1,000,000 | blank (withheld) or $3,000,000 |
| 8 | Score panel / Warnings | no umbrella-limit data-consistency warning, and no 85 cap caused by it | the "documents state different amounts" warning for the umbrella limit |

## 9. Not done, not verified, risks

**Not done:**
- **One door for all comparison sites.** Only Field QA + the stamp check, and the merge + the card, share a door. The other sites and the `test_comparison_has_one_owner` extension are open (section 2).
- **ACORD 160 liquor aggregate** is still bound to `gl_aggregate`. The owner's standing note says to leave 141/160 alone, so I didn't touch it.
- **The 126 / 25 `LimitAppliesToCode` text box** is still routed to `gl_aggregate`. What it prints on the live run: **unverified**.
- **Invalid stored confirmations** are ignored and kept on record, not visibly voided with an audit note as my diagnosis proposed.
- **Document issue dates** are not captured. A declarations page re-issued after the change cannot be ordered against it, so it stays a conflict.
- **`dated_change` does not check the policy number the sentence names.** It relies on `umbrella_limit` belonging to one line.

**Live-run risks:**
- **The COI's raw OCR prints the remark with NO spaces** (`Note:ReducedUmbrellaLimitfrom$3,000,000to$1,000,000LimitEffective7/25/25.`).
  - The rule reads the EXTRACTED remark, and both stored extractions returned it with spaces.
  - If the live v21 extraction copies it unspaced, no statement is found. The umbrella then stays a conflict, and without its explanation.
  - That is the safe direction, but the fix would not show. **Unverified.**
- **Document types:** the rule needs the policy PDF typed `dec_page` / `policy` / `binder`. Stored runs typed it `dec_page`, the COI `certificate` and the narrative `narrative`. If the live run types it differently, the umbrella stays a conflict.
- **A short real policy number can still be hidden:** one with a 4-digit-or-shorter series and an MM YY tail can still be kept out of the card's choices. It never changes a stamped value.
- **A real change phrased with "if" or a modal verb** in the same sentence stays a conflict. Safe direction.

**Not verified:**
- a live v21 extraction;
- the changed row in a browser;
- the live value of the 131 umbrella ticks;
- whether ACORD 25 carries the `ExcessUmbrella_*Indicator` boxes;
- the token estimate in section 5.

**Possible conflicts with other chats:**
- `merge_facts` and `pdf_service.py` were edited by several chats at once. My `_canonicalise_coverage_basis` call sits in the per-document loop after another chat's scrub (:10641).
- The prompt version: other chats set v19 and v20 earlier the same day. If anyone sets it back below v21 after me, cached v20 replies will be served again.
- `coverage_evidence.gl_form_basis` (another chat's F4 door) now receives canonical values. I checked this by reading only.

## 10. My test results

`py -m pytest -q -p no:randomly tests/test_comparison_guards_14sep.py tests/test_remaining_fixes_14sep.py tests/test_h3_wc_data_capture.py tests/test_line_binding_14sep.py tests/test_dec_index_purge.py` (from backend/, run after the handoff request, on the tree as it is now):

**257 passed, 0 failed.**
