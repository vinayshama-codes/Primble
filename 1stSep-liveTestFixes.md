# 1 Sep Live Test - Fixes, Decisions and Reasoning

> **Keep updating this file with relevant data and decisions for future chats and for
> future references.** For every item add: what the issue was, how we solved it, why we
> took those decisions, and any other relevant data.

**Source of truth for the test itself:** `Primble-Live-Test-basics.pdf` (30 consolidated
handoff items, 40 source screenshots, grouped by engineering type and priority).
**Related running memory:** `v1-20AUG.md` (V1 master log), `v1-core-principles.md`
(the 7 binding principles), `CLAUDE.md` (architecture + known issues).

**Ground rules the client set for this round:**
- Work top to bottom: systemic corrections, then bugs, then workflow/UX, then UI/copy.
- Results come from the client's REAL documents. Do not fix for the specific values.
  Find the root cause and fix the class, generically.

---

## Status board

| ID | Priority | Area | Status |
|---|---|---|---|
| SYS-01 | P0 systemic | Client questionnaire / Critical tagging | **SHIPPED + LIVE-VERIFIED 2026-09-07** (3 runs, all predicted counts hit exactly: A `5 Critical (2 agency)`, B `0 Critical`, C `11 Critical (3 agency)`). `priority` was a STATIC tier label - Critical meant "is in SQS Tier 1", so it never read the submission. Tier 1 complete on the reported run -> modal said **0 Critical** and *"All critical fields were already answered"* while the pre-form card on the SAME session printed *"Key details missing: FEIN / Tax ID, Annual revenue, Number of employees, NAICS or SIC industry code"*. The four the client named are **exactly** the four Tier 2 entries missing on that run - he read his own line back to us, so the rule is "required AND missing", not four names. **ONE SOURCE, TWO VIEWS:** `_tier1_entries` / `_tier2_entries` now carry `(fact_keys, label)`; `_tier1_items` / `_tier2_items` are the LABEL projection (score + `key_details`, byte-identical) and new `sqs_service.core_missing_fact_keys` is the KEY projection the questionnaire promotes from. A projection cannot disagree with what it projects. **ADDITIVE** (owner: *"keep list 1 as it is and add more to it"*) - only ever raises a priority, never touches audience/bucket. **NAICS / SIC stay AGENCY** (owner ruling; client PART 13 2026-08-12 *"those come from the producer or underwriter"*) and gain the Critical flag there - never auto-sent to the insured. Fixed on the way: the NAICS-or-SIC pair is now ONE requirement in the questionnaire too (a stated SIC no longer raises a false NAICS Critical); `_finalize_schedule_taxonomy`'s unconditional IMPORTANT became a FLOOR; the Agency panel now renders the Critical chip and sorts by priority (it was hidden by `!showAudienceBadge`); the chip counts both buckets. Tests `tests/test_sys01_critical_tagging.py` (26). Suite **6802 / 1 / 14** (the one failure is the documented `httpx` ImportError); frontend build clean. **D6: no SQS score moves; more questions pre-tick, and NAICS is missing on nearly every dec-page package so the Critical count will rarely be 0 - tell Brent.** |
| SYS-05 | P0 systemic | Coverage normalization | **SHIPPED 2026-09-03** |
| - | owner ask | Unresolvable warning had a dead Resolve button | **SHIPPED 2026-09-03** |
| - | owner ask | "Advisory" rendered as a scoring warning | **SHIPPED 2026-09-03** |
| SYS-06 | P0 systemic | Carrier / policy mapping | **SHIPPED + LIVE-VERIFIED 2026-09-04** |
| SYS-07 | P0 systemic | Normalization / boolean fields | **MET - see FINAL VERDICT at the end of this file.** **SHIPPED + LIVE-VERIFIED 2026-09-04**; **broadened 2026-09-05** after an adversarial real-shape sweep found 11 false conflicts (dec-page vocabulary, two-line cells, OCR damage) - all closed |
| SYS-07b | P0, same clause | **Policy-number formatting** | **SHIPPED 2026-09-05.** `BBC7263` vs `BBC7263 - 26` - the client's own package - drew a false card. Same root cause as SYS-07: `same_policy_contract` was correct since SYS-06 and nothing routed to it. Rule moved into `fact_equivalence`, `fact_comparison` delegates. |
| SYS-07c | P0, same clause | **Open Yes/No vocabulary** | **SHIPPED + LIVE-VERIFIED 2026-09-05** (run E clean, 4 unlisted words, 0 cards). `services/yes_no_lexicon.py` - the extraction model classifies the words the deterministic table cannot read, cached by the WORD. Comparison only, never form stamping. AAIS guard and crime advisory ALSO confirmed live in the same run. |
| SYS-04 | P0 systemic | Coverage detection / recommendations | **SHIPPED + LIVE-VERIFIED 2026-09-05.** W1/W2 render **10** narrative components, W3/W4 render **12** - and the sentences' own counts prove the denominators (`+5 more` = 10, `+7 more` = 12). W2's blank certificate WC row produced no WC row in the policy table at all and its narrative card **disappeared** (84%, above the emit gate). `WC Supplemental 100%` on every session. New door `services/line_presence.py`. Suite **6293 / 1 / 14**. |
| SYS-02 | P0 systemic | SQS scoring / Loss History | **SHIPPED + LIVE-VERIFIED 2026-09-05.** TWO causes: the producer's tick never reached a fact (`update_pdf` walked only `_ACORD_FIELD_RULES`, which has no `LossHistory_*` entry), AND the box was pre-ticked by us from a NARRATIVE MENTION so it could not be used as an input at all. One door `pdf_service.no_loss_attestation_verdict`; a human's answer now outranks the derivation. Owner-verified live: **40 -> 60** on re-tick. The client had ruled on the prose-vs-attestation split three times - his spec's two-tier table, his Core regression gate ("a **confirmed** no-loss state"), and his ACORD 125 point 5. **No score moves; the box prints blank until confirmed** - D6. |
| - | wrong form shipped | ACORD 133 identity | **FIXED 2026-09-05.** Its template is the **Workers Compensation Assigned Risk** section (67 of 136 fields are `WorkersCompensation*`); the product labelled it Builders Risk and, because `template_pending` gates nothing, **stamped the WC PDF for construction projects**. Metadata, recommender, 2 cross-form rules and 7 fact registry entries corrected; 3 tests were wrong and were rewritten. See "ACORD 133 - WRONG FORM" at the end. |
| - | **defect, found by the SYS-04 live run** | Loss-run conflict false positive | **FIXED 2026-09-05, root cause in the session data.** The extraction model wrote the NO-LOSS SENTENCE into the `loss_history` claims TABLE as a row, and `asserted_claims` counted any non-blank description - so the sentence saying there are no claims became a claim contradicting the attestation it restates. Two gates: `_row_states_a_claim` (the row) and `claims_are_corroborated` (the scalar). **Replayed against the owner's own six live sessions: all now False.** New tool `scripts/why_is_loss_conflicting.py`. Scores go UP - D6. |
| - | defect, same run | WC language on non-WC packages | **FIXED 2026-09-05.** A GL-only finding rendered under the cluster heading *"WC / GL class code alignment"*, and ACORD 186's reason hard-coded *"supplements GL & WC"* at two sites. A cluster TITLE is language (D-BH). |
| BUG-04 | bug, SYS-02's other half | ACORD 125 loss-row "required" highlight | **CLOSED, live-verified 2026-09-08.** A name-shaped test could not tell a table CELL from a section SUMMARY box, so ticking "Check if none" marked the whole claim row required (2 -> 7). The same confusion reappeared twice inside its own fix. Closed on the way: the no-loss SENTENCE printing as a claim, two divergent attestation parsers, a document denying it has loss runs classifying as one, and a stale SQS panel during edits. Full entry at the end of this file. |
| BUG-01 | bug | Client questionnaire / progress counter | **CLOSED, live-verified 2026-09-08.** Opened at *"1/11 - 9%"* with the auto-save bar already on, before the client answered anything. Progress measured whether a field HELD content, not whether the CLIENT put it there - and a schedule question ships PRE-FILLED with the rows extraction found, so our own pre-fill counted itself. Scalars could never do this (both serializers force `current_value: ""`); tables were the one path nobody applied that rule to. Same confusion three layers deeper, none of it reported: an untouched table was written back as a `client_arq` fact + audit row, the receipt claimed *"2 vehicles provided"*, and `fields_answered_count` was `len(posted_answers)` i.e. the question count. One rule now, browser and server: **counts when the client TOUCHED it and there is content on one side or the other** (theirs now, or ours that they cleared) - sticky, so delete-then-retype-identical never walks the bar backwards. Two ship blockers found by adversarial audit AFTER the first live run and both reproduced: the orphan-row sweep erased **applicant-level fields wearing ACORD's `_A` suffix** (nature-of-business boxes, the No Prior Losses attestation) - a row letter is not a row index, a field repeats only if its base appears at more than one letter; and a **pre-fix draft** restored the whole answer map as "touched", reintroducing the bug and defeating the server guard. Full entry at the end of this file. |
| BUG-02 | bug / UI state | Client questionnaire / unexplained green badge | **CLOSED, live-verified 2026-09-08.** The green "1" on the help/contact control was BUG-01's counter: absolutely positioned but a SIBLING of the Submit button inside a `position:fixed` stack, so it anchored to the stack's corner - the "Contact Your Agent" card. Wrapped with the button in a `position:relative` parent, given a tooltip and an aria-label. Not an unread indicator; it never was. |
| BUG-03 | bug | Producer workspace / "Sent to Client (2)" | **CLOSED, live-verified 2026-09-08.** Showed 2 on a session that had sent nothing. The badge read `/api/arq/notifications` - rows written when a client SUBMITS, i.e. inbound, on an outbound button - and that query is `WHERE user_id=$1` with **no session filter**, so a workspace inherited submissions from every other package. `POST /api/arq/notifications/read` had **no caller anywhere in the frontend**, so it could only ever count up. Now `openArqCount(arqSessions)` off the per-session list the panel below already renders: status `pending`, not expired. One definition of "open" shared with the status panel. Proof of the root cause is a brand-new session showing no badge on an account with several submissions - verified. |
| BUG-07 | bug | Client questionnaire / ghost vehicle questions | **FIXED + LIVE-VERIFIED 2026-09-08.** *"Hundreds of indexed vehicle questions, reaching the 308th, 309th, 310th vehicle even though those vehicle records do not exist."* Nothing invented rows: `_FIELD_PREFIX_MAP` is a curated **snake_case** vocabulary for OUR fact keys and was matched against raw ACORD names with a bare case-insensitive `startswith`. ACORD names its whole auto section `Vehicle_*`, so `Vehicle_BusinessAutoSymbol_TwoIndicator_G` (a covered-auto symbol checkbox) took the one-vehicle question text, the "vehicle" group label and a CLIENT audience; the ordinal came from a per-QUESTION counter shared across forms. Cards 308/309/310 are literally `_OtherSymbolCode_F`, `_TwoIndicator_G`, `_ThreeIndicator_G`. **1,035 distinct ACORD names collide with that vocabulary (vehicle 691 / driver 266 / location 36 / insurer 11) and ZERO bind a schedule column.** Worse, the polished English **laundered them past `_hide_machine_worded_questions`**, the one filter built to catch raw schema prompts. Fixed by `_is_raw_acord_field` (schema-union membership OR any uppercase - two conditions, H1-F) gating the prefix branch in BOTH `_resolve_question` and `_is_curated_client_field`; `_record_ordinal` reads the index off the NAME (`_C` -> 3rd), one shared labeller for both generators. **Live: RUN 2 (18 vehicles) 302 client questions -> 28, ghosts 287 -> 0; RUN 1 (0 vehicles) 19 -> 29.** Before/after diff of all 4,571 ACORD names: 1,004 ghosts removed, 67 rescued, 30 reworded, **0 genuine questions lost**. Tests `tests/test_bug07_ghost_vehicle_questions.py` (34). Suite **6938 / 1 / 14**. |
| - | **defect, found by the BUG-07 fixture** | Empty schedule offered no capture table | **FIXED 2026-09-08.** RUN 1 (0 vehicles) got NO vehicle or driver grid, only a free-text "Please list your business vehicles". Cause was an uncommitted experiment in the tree, `_suppress_ghost_schedule_rows` (*"PRE-PARTITION GHOST-ROW GATE (experimental; proves a fix can live here)"*), which deleted every schedule-row field whose row letter was `>= len(facts[list_key])`. On an EMPTY schedule that is `idx >= 0` - it deleted all 635 and the grid was never built; with 18 vehicles it deleted none. **That, not gap-fill coverage, is why RUN 1 read 19 and RUN 2 read 302.** Removed. Replaced by `schedule_capture.schedules_on_form()` (reads the FORM'S SCHEMA, so gap fill cannot defeat it) + `_partition_schedule_fields` PASS 1b/3: a form that carries a schedule raises it whenever we hold no rows. The table's canonical key is reserved before the injectors, so a schedule is asked once as its grid and never also as a scalar (H1-E). **C4 now closed structurally** - ACORD 25/131/137 carry no capturable column, so they cannot raise a fleet table. |
| - | **defect, found auditing the BUG-07 fix** | Coverage limits asked of the insured | **FIXED 2026-09-08.** `auto_liability_limit` / `gl_limits` / `employers_liability_limits` are producer-only, but their COMPONENT limits were not listed and reached the client - one coverage, two audiences, decided by whether the policy happened to be written CSL or split. Invisible before BUG-07 because they surfaced as the mislabelled "(Nth vehicle)" cards. 9 keys added to `INSURANCE_JUDGMENT_FACTS`. **The line is the WORDING:** *"What IS the limit?"* is read off a policy -> producer; *"Do you WANT this coverage?"* is the insured's preference -> client (`auto_um_uim_limit`, `auto_med_pay_limit`, `extra_expense_limit` deliberately left). **3 of my first 10 keys were guessed, not looked up, and matched nothing** - the phantom-key class that shipped the auto-symbol defect; new build-breaking guard `test_every_judgment_fact_is_a_real_registry_key`. Also fixed: the humanization skip read one of the two question tables, sending **39 fields/run to the LLM whose wording already existed in FACT_REGISTRY** and was then discarded. |
| SYS-09 | P0 systemic | ACORD contact mapping | **SHIPPED 2026-09-05, NOT YET LIVE-VERIFIED.** Both directions: the picker offering the BROKERAGE's contact as the applicant's `contact_name`, and the ACORD 125 producer block printing the APPLICANT's contact and address. Three causes - the certificate role-blind set never listed the contact fields, `merge_facts` enforced document ROLE on the non-primary half only, and `_resolve_applicant_contact` had no producer-side mirror. **The obvious one-line fix is a REGRESSION alone** (certificate outranks narrative, so the COI is PRIMARY: blinding it silences the picker while the wrong value still stamps) - read the trap before touching it. Suite **6376 / 1 / 14**. **D6: scores can move - Brent first.** |
| - | **defect, found by the SYS-09 live run** | Certificate holder printed as an Other Named Insured | **FIXED 2026-09-05.** `Kestrel Terminal Authority`, the CERT HOLDER, stamped on ACORD 125 as `NAME (Other Named Insured)` - a party the policy does not name, asserted as sharing it. An additional insured is NOT an additional named insured. **Root cause was the SEAM, the same one SYS-09 had:** `_drop_transaction_party_rows` was correct but reachable from the NON-PRIMARY branch of `merge_facts` only, so a single-document session never filtered at all. Now runs on the FINAL list for every key it knows - drivers, officers, premises, roster. Scores can move - D6. |
| - | **the above MISSED live, re-fixed 2026-09-06** | Certificate holder still printed on run 2 | **FIXED 2026-09-06.** The guard read `certificate_holder_name` at the TOP level - a key that does not exist. Extraction writes `certificate_holder` (top-level) and `risk_transfer.certificate_holder_name` (nested). Dead for exactly the reported party, working for the other four; and 24 tests passed because the FIXTURE invented the missing key (D22, the fixture easier than reality). Replaced the hand-list with ONE DERIVED DOOR (`third_party_identity_names`) that walks containers and classifies keys by meaning, plus a build-breaking test that scrapes the real extraction schema. Address half: the post-fill net was skipping row B (`<=` conflated two exemptions; `<` alone would have judged row A on all 17 roots). **Fixture rewritten to the real shape FIRST and watched to fail - 13 did.** Suite **6467 / 1 / 14**. |
| - | defect, same run | A refrigerated warehouse scored as a RESTAURANT | **FIXED 2026-09-05.** `infer_lob` matched bare substrings, so "cold storage of packaged **food** products" became a restaurant and `LOB_RULES["restaurant"]` charged it for `occupancy_type`. Same defect in every list ("app"/apparel, "tech"/geotechnical, "platform"/trailer). Now word boundaries + single-bucket evidence + the shared customer-phrase door, all failures resolving to `generic`. NAICS 311/312 (food MANUFACTURING) removed. Also fixed a crash: `.lower()` on a non-string fact raised inside both scorers - the H1-G shape. Scores go UP - D6. |
| - | **class fix, found by SYS-09 run 3** | Bare-substring keyword matching over document text | **ONE DOOR SHIPPED 2026-09-06** - `services/term_match.py`. Swept the whole backend: **38 candidates, 33 CONFIRMED** by running the real code with control inputs, 5 refuted. `"bank"` inside **SHOREBANK Avenue** sold Crime cover; `"California"` inside **CALIFORNIA STREET, Denver CO** shipped the **wrong state's form**; `"building"` inside **OUTBUILDING Value** **REFUSED TO GENERATE FORMS**; `"tech"` inside **TECHNICIANS** sold Cyber; `"siding"` inside **RESIDING** cost **-15**. Root cause is the COPIES, not the boundaries - proof: `_lob_from_operations` was fixed 2026-09-05 while its twin **78 lines below in the same file** was not. Door is stdlib-only so it sits below every consumer; `stem`/`plural` default OFF; every function total (30,000 fuzzed pairs, zero raises). **22 of 33 fixed, 11 recorded as NOT boundary problems.** Suite **6551 / 1 / 14**. Scores move BOTH ways - D6. |
| B8 | defect | Two-way boolean false read as No | **SHIPPED + LIVE-VERIFIED 2026-09-04** (found by the SYS-07 kit, not SYS-07) |
| - | root cause | Wrong VALUES on generated forms (6 defects, one class) | **SHIPPED 2026-09-05** - see `fix-form-stamping.md`, section "THE QUALIFIERS ENFORCED AS A CLASS" |
| PROD-02 | P2 - product decision | Warnings / underwriting language | **SHIPPED + LIVE-VERIFIED 2026-09-09** (session `299cd414`). *"Reassess whether the Specific Wording Requirements warning belongs in Important."* **Not a product decision - the last unmigrated comparator.** `detect_source_conflicts` compared normalised STRINGS, and two paragraphs are never identical, so a prose fact conflicted every time. Both sides were boilerplate: a dec-page service-of-process CONDITION and the **ACORD 25's own preprinted footer**. `fact_comparison.py`'s header has listed this site as having **"none"** since C1 (2026-08-21) - the only one of five never migrated; the build guard watches three function names and this one imports a fourth. The rule it was missing is the client's OWN 2026-08-17 ruling, already shipped as `_PROSE_WORD_FLOOR` (*"nobody picks between two true paragraphs"*). Fixed as a **SECOND gate, not a replacement** - the first attempt replaced gate 1 and re-opened the carrier-alias suppression (`Employers Mutual` vs `EMC P&C`), caught by the suite and now pinned as a property. One change closes all four complaints: card gone, #1 IMPORTANT slot freed, dead "Fix:" gone, 85 cap gone. Blast radius **6 of 176** facts (narrative-kind); every enumerated type still competes. Tests `tests/test_prod02_prose_conflicts.py` (28). Suite **7460 / 1 / 21**. **D6: scores go UP - Brent first.** |
| UX-04 | P2 - UX / safeguard & guidance | Document processing | **SHIPPED 2026-09-09.** *"Explain Exclude, Supporting only, and Review data actions before use."* The three controls on each Documents Processed row carried a bare native `title` (~1s delay, one terse clause) and two of them re-run the whole pipeline, so the producer was committing a write with no idea what it did. Copy now states the EFFECT and the UNDO: **Exclude** *"Ignores this document everywhere - forms, score, recommendations. Use it if the file doesn't belong here. Click \"Include\" to undo."*; **Supporting only** *"Still uses this document's values, but never as the main source. If documents disagree, this one gives way. Click again to undo."*; **Review data** *"See exactly what Primble read from this document. Read-only, changes nothing."* Verified against the code, not the labels: `exclude` drops the doc from `active_docs` so its text and facts leave the merge, scoring, form fill and recommendations (`extraction_pipeline.py:439`); `supporting_only` keeps the facts in the merge but removes the doc from `_primary_candidates`, so it can never be primary truth (`:451`); `review data` is a read-only GET. Delivered through the EXISTING `HoverTip` (hover + keyboard focus, and the native `title` is REMOVED on those three - two tooltips on one control is worse than none), plus one `InfoTip` on the Documents Processed header carrying all three in a sentence, because `HoverTip` shows nothing on touch by design (a tap must reach the button). One `DOC_ACTION_TIPS` map is the single source for both, so the header summary cannot drift from the buttons. The toggled states get their own line (`Include`, `Supporting only ✓`). Copy only - no behaviour, no scores, no backend. The type dropdown keeps its own title (not in the client's ask). Frontend build clean; eslint 0 errors. |

Suite after the full 5 Sep form-value arc: **6077 passed / 1 failed / 14 skipped.** The one failure is the
long-documented `httpx`/`openai` ImportError. Frontend production build clean.

**Baseline correction (2026-09-04):** this file previously recorded TWO pre-existing
failures. `test_confidence_score_covers_every_label` is now GREEN at HEAD and was not
touched by any work here - `sqs_service.py` is unchanged by SYS-06 and
`confidence_fill_rate` still ends `return int(...)`, so the truncation defect itself
remains open. **The baseline is ONE pre-existing failure.**

---

## SYS-06 QUICK REFERENCE - read this before touching carrier / policy identity

*The SYS-06 sections further down are CHRONOLOGICAL - fifteen of them, written as
the work happened, including the wrong turns. This is the FINAL STATE. Read this
first; go to the narrative only when you need the reasoning behind a decision.*

### What it does, in one paragraph

A package carries one carrier, NAIC, policy number and term **per coverage
line**. Those are folded into one record per **(line, policy contract)** at merge
time, stored on the facts, and everything downstream - the Data Consistency
picker, the E&O record, the per-line form stampers - reads that instead of a
single submission-wide scalar. Two printings of ONE policy (`BBC7263` /
`BBC7263 - 26`) are one record; two genuinely different policies on one line stay
two and are still a question.

### The doors - ask these, never re-implement them

| Question | Function | File |
|---|---|---|
| are these the same policy contract? | `same_policy_contract(a, b)` | `services/fact_comparison.py` |
| ...group N printings by contract | `policy_contract_groups(values)` | `services/fact_comparison.py` |
| what policies does this package carry? | `_build_line_records(mf, docs)` | `services/extraction_service.py` |
| which line does this value belong to? | `_scope_from_store` / `_scope_of_group` | `services/underwriting_consistency.py` |
| is this string a form number, not a policy? | `_looks_like_a_form_number` | `services/extraction_service.py` |
| which coverage line does this FORM apply to? | `_SECTION_FORM_LINE_PHRASES` | `services/pdf_service.py` |

`pdf_service._same_policy_contract` is a DELEGATION to the door, with the
original body kept only as an import-failure fallback. A fourth copy fails
`test_the_stamping_layer_delegates_to_the_door`.

### The data

```python
facts["_line_records"] = [                     # the client's chain
  {"id": "general_liab#BBC726326", "line": "general_liab",
   "line_printed": "General Liability",
   "carrier_name": "...", "carrier_naic": "25186",
   "policy_number": "BBC7263 - 26",
   "effective_date": ..., "expiration_date": ...,
   "granted": True,                            # premium or limit present
   "printings": {"policy_number": ["BBC7263 - 26", "BBC7263"], ...},
   "sources": ["dec.pdf", "coi.pdf"]},         # WHICH DOCUMENTS said so
  ...
]
facts["_scoped"]["policy_number"] = [          # DERIVED from the records
  {"value": "BBC7263 - 26",
   "scope": {"line": "general_liab", "line_printed": ...,
             "policy_number": ..., "record": "general_liab#BBC726326"}},
]
confirmations["policy_number@general_liab"] = "BBC7263 - 26"   # line-scoped
confirmations["policy_number"]              = "..."            # package-wide (legacy)
```

`_scoped` keeps its pre-SYS-06 shape apart from the additive `record` id, so
every D19 reader is untouched.

### INVARIANTS - break one and a wrong value reaches a signed form

1. **Two different policies on one line stay a conflict.** D-1, and the client's
   own review rule. `test_two_real_policies_on_one_line_still_raise_a_conflict`.
2. **No record id means no proof of a shared contract.** A pre-SYS-06 store has
   `scope.line` but no `scope.record`; treating the line as the contract folds
   two real carriers into one.
   `test_a_legacy_store_with_no_record_ids_never_folds`.
3. **A line-scoped question offers only that line's values.** Otherwise a
   "Confirm for general liab" button can write the Auto policy number onto GL.
   `test_a_one_line_question_never_offers_another_lines_value`.
4. **Carrier and NAIC move as a matched pair.** The confirmed CARRIER decides; a
   contradicting NAIC answer is overridden, never stamped.
   `test_a_confirmed_carrier_brings_its_own_naic`.
5. **A scoped confirmation never writes the package scalar.**
   `test_a_scoped_confirmation_never_becomes_the_package_scalar`.
6. **A form's identity line comes from the form's own printed title.**
   `test_every_section_form_maps_to_the_line_its_template_names`.
7. **The separated 2-digit tail is what makes a term marker.** `POL123` and
   `POL12345` are two policies. Without that condition the prefix rule eats real
   contracts.

### Behaviour table - what the picker does with what

| Situation | Result |
|---|---|
| N lines, N different numbers | **scoped** - "N policies, N values - not a conflict" |
| one policy printed two ways | folded into one record, one value |
| a value the records cannot place | shown "not matched to a coverage line", **not** a conflict |
| TWO unplaceable values | conflict, restricted to those two |
| two policies on ONE line | conflict, reason names the line, only that line's values offered |
| a renewal's expiring number | excluded via `prior_term_policy_numbers` (needs a prior grid) |
| an ISO/AAIS form number | never a policy |
| no `coverage_lines` at all | legacy pre-SYS-06 behaviour |

### Test kit

```
py backend/scripts/make_sys06_test_pdfs.py      ->  sys06_test_data/
```

Three PDFs, **two sessions, cannot be merged**: A1+A2 together (the client's
case, must be silent), B alone (the control, must complain).
`backend/tests/test_sys06_line_specific_identity_20260904.py` - **80 tests**,
adversarial cases first in the file.

### Still open after SYS-06

| Item | Why not done |
|---|---|
| `gl_class_codes_by_location` false warning - the screen says "GL coverage detected but no class codes found" while our own ACORD 126 prints two (the stamper reads `gl_class_code_schedule`) | score-bearing; the correction moves scores UP, so D6 |
| ACORD 160 is a **Business Owners** template used as the Cyber form | which PDF to ship is a product decision (D-AG) |
| `forms_database/ACORD_141.json` still calls it a "Property Schedule" and recommends it on property flags | changing the flags changes which forms every package is offered |
| gap fill writes LABELS into value boxes (`Any Auto`, `Erisa`, `Damage To Rented Premis...`) | Guard 8 class, pre-existing |
| ACORD 126 invents an EMPLOYEE BENEFITS limit on a package that never mentions it | Principle 3, pre-existing |
| `Source` is on screen but not in the E&O export (`audit_service` reads `_scoped`, not `_line_records`) | ~5 lines, not asked for |
| the Line column shows the LONGEST printing, mixing dec and certificate wording | cosmetic |
| "Suggested" on a two-policy tie is decided by string LENGTH | MEDIUM confidence, never pre-selected |

### THE DEPENDENCY TO STATE OUT LOUD

All of it rests on `coverage_lines` carrying one row per line with its own
carrier / NAIC / policy number. **No per-line rows, nothing fires** - the picker
falls back to pre-SYS-06 behaviour. That is a property of extraction, not of this
change.

### Standing lessons this item earned

* **Nine defects; four were introduced by the fix.** Every one of the four was
  caught by a positive control, a full-suite run, or a live screenshot - **none
  by reading the diff.**
* **The control package earns its keep.** 61 unit tests and a clean suite were
  green while the screen was offering the Auto policy number as an answer to a
  General Liability question, because every test asserted the VERDICT and none
  asserted what the producer is allowed to CHOOSE.
* **Test on messy data before claiming it holds.** Six noise shapes from the
  client's real package were replayed after the clean kit passed; two failed.
* **When a fix is impossible without guessing, change the QUESTION.** `gl_limits`
  could not be compared safely, so it stopped being asked - its four child
  scalars already are.

---

## SYS-05 - Normalize Auto coverage terminology back to the Automobile line

### What the client saw

> *"Terms such as UNINSURED AND UNDERINSURED MOTORISTS, COMPREHENSIVE, COLLISION, and
> Uninsured Motorists are being treated as unrecognized coverage parts. They are
> components of Automobile coverage and should not become standalone unknown lines.
> Map these terms into the Commercial Auto/Automobile coverage family BEFORE
> cross-document comparison. Once normalized, the warning should disappear unless the
> source documents genuinely conflict on the Auto coverage itself."*

On screen, under WARNINGS > IMPORTANT:

> *"Coverage part not recognised: UNINSURED AND UNDERINSURED MOTORISTS, COMPREHENSIVE,
> COLLISION, Uninsured Motorists. The documents show it is carried, but Primble has no
> normalization rule for this terminology, so it is not matched to a standard line of
> business. Confirm which line it belongs to."*

### The root cause - it was never an Auto vocabulary gap

A declarations page prints a SCHEDULE OF COVERAGES whose rows are the coverage **parts**
of one line, each with its own limit and premium. `extraction_service` RULE 16 asks the
model for *"one entry per coverage line ... use the line name as the document prints
it"*, so extraction is doing exactly what we told it. The defect is that
**`coverage_lines` has one bucket for two different concepts**:

```
Business Auto   $2,991   <- a LINE of business
Comprehensive   $412     <- a PART of that line
Collision       $688     <- a PART of that line
Uninsured Motorists      <- a PART of that line
```

`lob_canon.canon_line()` only answers *"does this phrase NAME a line?"*, so every part
came back `None`, and `unmapped_material_lines()` reported each as terminology with no
normalization rule.

Reproduced against the client's literal rows before changing anything.

### The class was wider than the report

Measured with the real function. The same hole existed on every line, not just Auto:

| Phrase | Before | Correct |
|---|---|---|
| `Personal and Advertising Injury` | None | GL part |
| `Damage to Premises Rented to You` | None | GL part |
| `Medical Expense` | None | GL part |
| `Business Income` | None | Property part |
| `Ordinance or Law` | None | Property part |
| `Equipment Breakdown` / `Boiler and Machinery` | None | Property part |

**Fixing only the four reported words would have been the pinpoint patch the client's
own instructions forbid.** The whole class is mapped.

### A pre-existing WRONG mapping the same sweep uncovered

`canon_line("Property Damage Liability")` returned **PROPERTY**.

"Property damage" is a category of LOSS that a LIABILITY policy pays for - the standard
second half of every GL and Auto liability limit ("Bodily Injury and Property Damage
Liability"). It is not the Commercial Property line. So a COI's GL limit row could be
read as a Property line, and `denied_families` / the cross-document LOB compare would
then reason about a Property line the package does not carry.

Cause: `_SPECIFIC` matches by naive substring, and PROPERTY's phrase list contains
`"property"`. Fixed with `_FAMILY_BLIND_PHRASES`, which masks a phrase out of ONE
family's haystack only. `Business Personal Property` and `Commercial Property` are
untouched; the masked phrase falls through to the bare-"liability" branch and lands on
`GENERAL_LIAB`.

### What shipped - `services/lob_canon.py`

**Decision: `canon_part()` is a SEPARATE door from `canon_line()`. This is the
load-bearing decision of the whole fix.**

`canon_line` is what decides whether a row GRANTS or DENIES coverage - it is read by
`denied_families`, `coverage_evidence`, `_coverage_lines_are_self_contradictory`. A part
must never reach it, or:

- a lone `COLLISION - NO COVERAGE` row would deny the whole Auto line, and
- a `COLLISION` row would on its own flip an HNOA-only account into an owned fleet,
  which moves SQS scores (D6).

**Parts are for PLACEMENT and COMPARISON only. No score moves.**

Resolution order, each step narrowing the last:

1. **`canon_line` first.** So `Comprehensive General Liability` (the pre-1986 name for
   CGL) and `Comprehensive Crime` resolve as LINES and the bare word never gets a vote.
2. **`_PART_UNAMBIGUOUS`** - one possible line whatever else is in the package.
   `"motorist"` covers UM/UIM in every printing it takes; also `collision`, `towing`,
   `business income`, `personal and advertising injury`.
3. **`_PART_NEEDS_PARENT`** - shared phrases resolve ONLY when the package already shows
   the parent line. This is H1-F's "structural second condition" rule: a test that is
   necessary but not sufficient needs a structural second condition.
   `coverage_families_present()` runs two passes, so a package that names Auto ONLY
   through `COLLISION` can still place the `COMPREHENSIVE` beside it.
4. **Two candidates and no separator -> REFUSE.** `BODILY INJURY`, `PROPERTY DAMAGE` and
   `MEDICAL PAYMENTS` are standard rows on BOTH a GL and an Auto dec page. Guessing is
   Principle 4's forbidden move, so they route to the producer.
5. **`policy_number_families()` settles case 4 when the document states the contract.**
   A `MEDICAL PAYMENTS` row carrying the auto policy's number is the auto policy's
   medical payments. Built from rows that NAME a line only, so a part can never
   bootstrap the contract it is then placed by; a number attached to two families is
   dropped as corrupt (`_coverage_lines_are_self_contradictory` already treats that
   pairing as corrupt, and a corrupt witness must not settle an ambiguity).

**Cross-document comparison** (`sqs_service.check_doc_consistency`, the client's
"BEFORE cross-document comparison"): parts fold into their parent before the LOB compare.
A dec listing the whole schedule and a COI listing `Automobile Liability` now both
resolve to `{auto}`. This can only ever REMOVE a false difference - a name nothing can
place still keeps its own text as its key, so a genuinely extra policy still differs.

**Client 1.7's other half survives, pinned by test:** `Kidnap and Ransom` and
`Widget Protection` still route to the producer, even when sharing a placed policy
number. A fix that force-maps everything would delete the feature this warning exists
to provide.

### A bug the new tests found in the new fix

`Comprehensive Dishonesty, Disappearance and Destruction` (the ISO 3-D crime policy)
matched nothing in `_SPECIFIC`, because CRIME held only `employee dishonesty`. Harmless
until `canon_part` could read a bare "Comprehensive" as Auto - then it became a real
false mapping on any package carrying an auto line. CRIME widened to `dishonesty`
(no other line of business uses the word).

**Lesson: write the adversarial case first. The test caught this, not review.**

### One door - `pdf_service` no longer holds a second part vocabulary

Found while tracing: `pdf_service._coverage_part_vocab()` **already** existed, built
2026-08-12 after the same defect ("four coverage PARTS printed into ACORD 125's Other
line of business rows"). It answers *"is this a part?"* from ACORD's own schema field
names (349 words, auto-growing). Mine answers *"a part of which line?"*.

Two mechanisms, one overlapping question, no shared door - the exact duplication class
that let the Umbrella SIR and auto-symbol bugs survive their first fixes. That file's own
comment reads *"Third incident, third set of tokens, one defect."*

`_name_is_a_line_not_a_part` now asks `lob_canon.canon_part` FIRST and falls back to the
ACORD vocabulary. **No package context is passed, deliberately** - that restricts it to
the unambiguous table, because letting a shared row like "Bodily Injury" resolve here
would drop a real LINE from the premium sum and understate the policy total. Same money
field, opposite error.

### Verification

- Client's literal rows -> `unmapped_material_lines` returns `[]`.
- 32 standard line names re-checked, all unchanged. (`Plate Glass` / `Burglary and Theft`
  return `None` at HEAD too - they are lob_canon's own examples of strings that must NOT
  match the `gl` abbreviation. My expectation was wrong, not the code.)
- Tests: `backend/tests/test_sys05_coverage_parts.py` (59).

### Explicitly NOT done

- **RULE 16 was not changed to nest parts under their parent line.** See the decision
  register below.
- `fact_equivalence.PackageContext._build` still attributes `coverage_lines` by
  `canon_line` alone. Folding parts there would attribute a component row's carrier and
  policy number to its parent line - an improvement, but it changes conflict detection,
  so it is out of this change's scope.

---

## Owner ask - a warning that cannot be cleared must say so

### The issue

`unmapped_coverage_line` had **no entry in `RESOLUTION_MAP` at all**. The message told
the producer *"Confirm which line it belongs to"* over a control that opened nothing. The
only way it ever cleared was if the underlying document data changed and the pipeline
re-ran.

### Owner ruling

> *"if by clicking a resolve button and adding something, a producer can clear it then
> it's well and good, and if it can't be cleared by a value then don't show a resolve
> button and just show a disclaimer like: it can't be cleared by a value and it needs
> this (add actual reason), and keep it short."*

### What we did, and why

**Can a typed value clear it? No.** There is no canonical fact for "this coverage part
belongs to line X". Creating one means a new fact, a writer for it, and a
re-canonicalisation path. Not worth it for a message that is now rare.

So it gets `_r_review(note)` - mode `none` plus a short context-specific note. **The
machinery already existed**: `_r_review` at `issue_registry.py:436` and `ResolutionHint`
in `AcordModal.jsx`, which prints a small grey italic line and suppresses the button. The
frontend needed no change for this half.

`_r_review` had to be MOVED above `RESOLUTION_MAP` in the file - it was defined after it,
so referencing it inside the map was a `NameError`.

Note text: *"Primble can't tell which line this belongs to. Check the source document,
then mark it resolved."*

---

## Owner ask - "Advisory" was rendering as a scoring warning

### The issue

Three mechanical facts, all verified in code:

1. **Clusters carried no severity at all.** `_make_clusters` built
   `{cluster, issue_id, primary_message, count, forms, items, resolution}`. The frontend
   literally could not tell an advisory cluster from a warning cluster.
2. **`build_grouped_view` sorts into two piles only** - hard stops, and everything else.
   "Everything else" is the WARNINGS section, so an advisory renders as a warning and
   counts toward "N items still need attention".
3. **The IMPORTANT promotion overwrites severity** with `{**c, "severity":
   "soft_warning"}`, which is exactly the band in the client's screenshot.

### Owner ruling

> *"show it under a specific warning which can't move the score, and treat the loss
> history one as a proper warning as it is capping the score."*

Checked first: **the client said nothing about this.** Their nearest items are UI-06
(noise reduction), PROD-02 (whether a specific warning belongs in Important), UX-03
(Resolved vs Dismissed), UI-03 (spell out SQS). None of them is this. So this is an
owner decision, recorded here rather than attributed to the client.

### THE TRAP - and why the obvious implementation is wrong

Deriving the note from `severity == "advisory"` looks equivalent and is **not**. Measured
across all ten advisory emitters:

| Advisory code | What its condition actually costs |
|---|---|
| `loss_history_attestation_conflict` | caps the Loss History pillar at 45 (`_LOSS_CONFLICT_CAP`) |
| `auto_um_uim_not_specified` | `auto_um_uim_limit` drives ACORD 137's structural score AND an 8-point recommendation |
| `auto_pip_medpay_not_specified` | same, via `auto_med_pay_limit` |
| `acv_high_value_building` / `rcv_old_building` | `valuation_method` appears 18 times in the scorer |
| `acord101_required` | `additional_remarks_text` downgrades hard stops |

**"Advisory" in this codebase is a DISPLAY ROUTING choice, not a promise about the
score.** A blanket severity rule would have printed "does not affect your score" on rows
that demonstrably do - a false statement about a number, which is the one failure this
codebase treats as unrecoverable.

### What we did

- **`SCORE_NEUTRAL_CODES` is an explicit per-code claim**, currently **one entry**:
  `unmapped_coverage_line`. Verified end to end - emitted to `structured_issues` only,
  never to `hard_stops`/`soft_stops`, and there is no FACT behind it to deduct against
  (it is raw terminology we could not place). Principle 7 states the rule outright:
  *"give it no new scoring effect until a rule is explicitly defined."*
- **Silence means scoring.** An unknown code is never assumed neutral. A new advisory
  earns the note only after somebody traces what its condition costs.
- **`score_neutral` is re-derived from the CODE in `build_grouped_view`**, never trusted
  from the incoming dict. Issues reach that view from persisted sessions, legacy string
  arrays and the cross-form mirror, and only some went through `make_issue`.
- **A cluster is neutral only when EVERY member is.** One scoring member makes the
  sentence false for the whole cluster.
- Frontend: `ScoreNeutralNote` renders *"Advice only - this does not affect your score."*
  It stays in the warnings list, as ruled. Missing flag renders nothing, so older
  payloads and the lite path are unchanged.

### The loss-history row is now a proper warning

Retyped from `advisory` to `soft_warning` in `extraction_pipeline`.

**Verified display-only before changing it:** `structured_issues` is read by
`build_grouped_view` and the audit export and by **nothing** in any scoring path, and
both severities land in the same warning bucket there. So no cap fires that did not fire
before, and no count moves. What changes is that it is no longer eligible for the
score-neutral note. The stale comment above it, which claimed advisory severity was "on
purpose", was corrected in the same edit.

### Two knock-on fixes the work forced

1. **Both codes were falling into `DEFAULT_CLUSTER`**, which put an advice-only
   terminology note and a pillar-capping loss conflict under one "Other validations"
   heading - and made the cluster mixed, so neither could carry an honest note. Each now
   has its own cluster. `unmapped_coverage_line` is tiered `binder_followup`, which the
   IMPORTANT promotion skips by design, so **advice stops displacing real work from the
   band the client screenshotted**.
2. **Giving `loss_history_attestation_conflict` a cluster made it a "cross-form cluster
   code", which the guard test `test_every_cross_form_cluster_code_has_a_resolution`
   requires to have a resolution.** The guard caught it, doing exactly its job. Unlike
   the terminology row, this one IS typeable: the conflict is between an attestation and
   a claim count, and the message already asks the producer to confirm which is correct.
   It gets `_r_field("loss_history_no_prior_losses_indicator", "num_claims",
   "total_incurred")` - all writable through the producer-answer path, so stating the
   truth retires the conflict on the next pipeline run and the 45 cap lifts with it.
   `no_prior_losses` is deliberately absent: it is a FLAG, not a writable canonical fact.

### One test was WRONG and was rewritten, not deleted

`test_loss_history_c2.py::test_conflict_routes_to_data_consistency_as_advisory` asserted
the literal string `"advisory"` appeared near the emission, as a PROXY for "does not cap
the package".

The proxy broke when the severity legitimately changed - and it was always the weaker
test: a future edit could have kept the word `advisory` while appending to `soft_stops`
on the next line, and it would have passed.

Rewritten as `test_conflict_routes_to_data_consistency_without_capping_the_package`,
which pins the actual PROPERTY: the emit block writes to `structured_issues` only.
Severity is free to change; the routing is not. **Proved it bites** by injecting a
`soft_stops` write and watching it fail, then reverting.

Tests: `backend/tests/test_advisory_presentation_20260903.py` (21).

---

## Decision register

| # | Decision | Reasoning |
|---|---|---|
| D-A | **Do NOT change RULE 16 to nest coverage parts under their parent line.** | 39 read sites expect a flat list of flat dicts (24 in `pdf_service` alone). It would bump `PROMPT_VERSION`/`SCHEMA_VERSION` off v17 and invalidate every cached extraction. Old sessions keep the flat shape forever, so all 39 readers become permanent dual-path. `_coverage_line_dedup_keys` identifies a row as `(line, contract)` and has two recorded defects behind that pairing. And the LLM is not reliable at nesting - a half-nested reply is a shape that is neither, with no cheap way to detect it. Owner: *"don't change the prompt yet."* |
| D-B | **`canon_part` is a separate door from `canon_line`.** | `canon_line` decides GRANT and DENIAL. Letting a part answer it would let `COLLISION - NO COVERAGE` deny the whole Auto line and let a Collision row flip an HNOA-only account to owned-fleet. Both move SQS scores. Placement and comparison are safe; grant/deny is not. |
| D-C | **An ambiguous part with two candidate parents is REFUSED, not guessed.** | Principle 4: a genuine conflict routes to the producer rather than being silently resolved. `BODILY INJURY` on a GL+Auto package really is ambiguous. Structural evidence (shared policy number) is allowed to settle it; a coin flip is not. |
| D-D | **D9 shipped on the owner's ruling, not escalated to Brent.** | Owner: *"ship it if this doesn't break any working thing and completes the expected result."* Condition met: full suite clean, 32 standard line names unchanged, no score path touched. |
| D-E | **Score-neutrality is DECLARED per code, never derived from severity.** | Measured: nearly every advisory-typed issue has a traced score effect elsewhere. Deriving it would print a false claim about a number. |
| D-F | **`SCORE_NEUTRAL_CODES` starts at one entry and grows only after tracing.** | Silence is not a promise, and the promise is what has to be earned. |
| D-G | **`unmapped_coverage_line` tiered `binder_followup`.** | Advice only, nothing typeable clears it. The IMPORTANT promotion skips that tier by design, so it stops outranking real work - which is the client's screenshot complaint. |
| D-H | **Rewrote a failing test instead of the code.** | The test pinned an implementation detail (`"advisory"` in a source window) as a proxy for a property. The property version is strictly stronger and was proved to bite. |

---

## Still open, deliberately

- **ACORD 133 has two contradictory identities in this repo, and it is LIVE.** The
  section-form identity table calls it Workers Compensation (its template's own printed
  title, pinned by a passing anti-rot test); `forms_database` / `form_service` call it
  Builders Risk. Consequence, verified by execution: all 7 `builders_risk_*` facts answer
  `fact_line == "workers_comp"`, and `coverage_flag_supported("has_workers_comp",
  {"builders_risk_project_cost": "500000"}, [])` returns **True**. Found 2026-09-05 while
  verifying SYS-04. **Owner decision - which one is the form?** See D-AP.
- **`extraction_service.py:753` sets `has_workers_comp` on a MENTION**, and two of its six
  triggers are preprinted on every ACORD 25. No path demotes it on a blank row. Not fixed;
  D-AN routes around it rather than depending on it. Same class as the
  `form-stamping-mention-vs-grant` memory.
- **`fact_equivalence.PackageContext._build`** attributes `coverage_lines` by
  `canon_line` alone. Folding parts there is an improvement but changes conflict
  detection. Out of scope of SYS-05.
- **Coverage parts are still their own `coverage_lines` rows.** Nesting is the cleaner
  model; see D-A for why it is not V1.
- **UI-06** ("Remove duplicate/noisy coverage-term equivalence output") is related. The
  `[info] code=lob_normalized Coverage terms: ...` branch in
  `sqs_service.check_doc_consistency` is the other half of that noise, and SYS-05's fold
  already shrinks it. Not separately addressed yet.
- ~~**PROD-02** (whether the Specific Wording Requirements warning belongs in Important) is
  the same family of question as the advisory-bucket work, and is a product decision.~~
  **CLOSED 2026-09-09 - it was not a product decision, it was the last unmigrated
  comparator.** Full entry at the end of this file.
- **The IMPORTANT band ranks by TIER, and the tiers are wrong.** Fixing PROD-02 removed
  the card, not the ordering. Measured by driving the real `build_grouped_view`: the
  `required` tier is document-conflict prefixes plus 10 coded rules, while **43 rules -
  umbrella attachment, property COPE, auto symbols, WC payroll, claims-made retro date,
  business income, coinsurance - are `recommended`**. IMPORTANT fills from `required`
  first, so a real coverage gap can never outrank a cross-document text conflict, however
  many forms it affects (`_cluster_rank_key`'s form count only sorts WITHIN a tier). The
  next genuine carrier disagreement will sit above "the owned fleet has no liability
  symbol" for the same structural reason. **Owner's call, not a defect fix** - re-tiering
  changes what every producer sees first on every submission.

---

## Suite baseline notes

**CURRENT (end of 2026-09-04, after SYS-06): 5584 passed, 1 failed, 14 skipped.**
The ONE failure is `test_arq_acord125_missing_only` - the long-documented
`httpx`/`openai` `ImportError: cannot import name URL from httpx`.

The historical note below is kept for the reasoning, but its COUNT is stale and
its second failure is GONE (see the correction under the status board):

> `py -m pytest -q -p no:randomly` from `backend/` -> **5358 passed, 2 failed, 14 skipped.**
>
> Both failures are pre-existing at HEAD and unrelated to this work:
>
> 1. `test_arq_acord125_missing_only` - the long-documented `httpx`/`openai`
>    `ImportError: cannot import name URL from httpx`.
> 2. `test_confidence_score_covers_every_label::test_verified_ai_values_never_read_as_an_empty_form`
>    - the **already-open** `confidence_fill_rate` truncation defect (CLAUDE.md, "Three
>    Score-Moving Defects Held For Brent", item 2). `return int((weighted/filled)*100)`;
>    10 x `ai_verified` = `84.99999999999999` -> `84`, and the test wants `>= 85`.

**That second failure is GREEN at HEAD now and was not fixed by any work here** -
`sqs_service.py` was never touched by SYS-06 and `confidence_fill_rate` still ends
`return int(...)`, so the truncation defect itself remains OPEN. Do not use the
old "2 pre-existing failures" line as cover for a red test.

**Always baseline with `-p no:randomly`.** The default run reports more failures because
the suite uses `pytest-randomly` and carries pre-existing cross-test pollution.

Frontend: `VITE_API_BASE=https://api.primble.io npx vite build` - clean.

---

## Files touched

| File | Change |
|---|---|
| `backend/services/lob_canon.py` | `_FAMILY_BLIND_PHRASES`, `_PART_UNAMBIGUOUS`, `_PART_NEEDS_PARENT`, `canon_part`, `canon_line_or_part`, `coverage_families_present`, `policy_number_families`; CRIME widened to `dishonesty`; `unmapped_material_lines` skips placeable parts |
| `backend/services/sqs_service.py` | LOB compare folds parts into their parent before comparing |
| `backend/services/pdf_service.py` | `_name_is_a_line_not_a_part` asks `lob_canon` first (one door) |
| `backend/services/issue_registry.py` | `SCORE_NEUTRAL_CODES` + `is_score_neutral`; `score_neutral` on `make_issue`, the enrich step and clusters; `_r_review` moved above `RESOLUTION_MAP`; resolutions + clusters + tier for the two codes |
| `backend/services/extraction_pipeline.py` | loss-history conflict retyped to `soft_warning`; stale comment corrected |
| `frontend/src/components/form/AcordModal.jsx` | `ScoreNeutralNote`; rendered in both item-action branches and the IMPORTANT band; cluster carries the flag |
| `backend/tests/test_sys05_coverage_parts.py` | new, 59 tests |
| `backend/tests/test_advisory_presentation_20260903.py` | new, 21 tests |
| `backend/tests/test_loss_history_c2.py` | one test rewritten to pin the property, not the proxy |

---

## Two invented values, found by the SYS-05 test kit - SHIPPED 2026-09-03

Not client-reported. Both were exposed by run 2 of the SYS-05 live kit, which is
the whole reason the kit used values unlike the client's.

**Run 1** (declarations page alone) correctly reported the building value as
MISSING and raised no valuation advisory. **Run 2** added a certificate whose
property row reads `Property - Special Form  $4,200,000`, and the package came
back with:

```
property_building_value = 4,200,000   <- a LIMIT read as a VALUE
valuation_method        = ACV         <- named in NEITHER document
```

which produced *"Actual Cash Value (ACV) selected on a building valued at
$4,200,000. ACV applies depreciation..."* - a confident, wrong, score-bearing
statement about a risk nobody described.

"Special Form" is a CAUSE OF LOSS form (Basic / Broad / Special). It says nothing
about valuation. `valuation_method` is read by the scorer in ~18 places.

Both are Principle 3's forbidden move and CLAUDE.md's documented **GAP 1**:
`answer_semantics` guards what a HUMAN types; nothing guarded what the model
extracts.

### Fix 1 - `_gate_inferred_valuation_method` (no prompt change)

The twin of `_gate_inferred_payroll_period`, one coverage line over, built for
the same reason H1-K gives outright: *"v16's prompt already forbids it in terms;
a prompt is not a guarantee."* A prompt is a request; on a signed application the
guarantee has to be deterministic.

`coverage_evidence.valuation_method_corroborated` asks whether any uploaded
document (raw text OR a verified dec entry) literally names the method claimed.
If not, the AI-sourced value is dropped and the producer is asked instead.

* **Provenance decides** (Principle 6) - producer / client / derived values are
  never gated, through the SAME `_PERIOD_NAMED_SOURCES` set the payroll gate uses.
* **Whole tokens for abbreviations.** `acv` / `rcv` are three letters; a substring
  test matches inside `vacvuum`, `MACVILLE`, `preplacement`. The D9 lesson in
  miniature - the danger was never the equivalence, it was the matching mechanism.
* **No opinion on what it cannot read.** An unrecognised method is left alone; the
  gate strips an invented value, it does not police free text.
* **Drops no score by itself** - the valuation advisories simply stop firing on a
  method nobody stated, and the existing "valuation missing" question asks instead.

### Fix 2 - a certificate states LIMITS, never VALUES

`fact_comparison._ROLE_BLIND_FACTS` gained a `certificate` entry: property and
BPP values, valuation/coinsurance/deductible basis, all COPE fields, and the
exposure basis (revenue, payroll, employee counts, years in business).

**Deliberately NOT blind** to identity, policy numbers, carriers, NAICs, dates or
`coverage_lines` - those are exactly what a certificate is FOR, and blinding them
would break the multi-carrier ACORD 25 roster (H5).

### The half-applied rule underneath both - the real root cause

The merge's role gate read:

```python
_kept = {k: v for k, v in _f.items() if k not in _LIST_FIELDS or _witnesses(_dt, k)}
```

so a role-blind **SCALAR sailed straight through** and the table only half meant
what it said. Adding `certificate` to the table alone would NOT have fixed
anything. Now:

```python
_kept = {k: v for k, v in _f.items() if _witnesses(_dt, k)}
```

**This is the defect class this codebase keeps paying for** - a rule enforced in
one place and not another. The Umbrella SIR and auto-symbol bugs each survived
their first fix for exactly this reason.

Widening it also brings `loss_run`'s eight scalar blind facts into force for the
first time (its policy numbers and dates had always reached the merge despite the
table saying they must not). **Full suite green**, so nothing depended on the old
half-behaviour.

### An edge case the new tests found in the new code

Both gates read `" ".join(str(d.get("text") or "") for d in (docs or []))`.
A `str` survives `or []`, is iterable, and yields characters - so a malformed
`docs` raised `AttributeError`. The callers wrap each gate in try/except, so this
was **not a crash; it was worse** - the gate was SKIPPED and the invented value
survived silently, which is the one outcome these functions exist to prevent.
Shared `_all_document_text()` now fails closed for both.

### Verification

* The live shape reproduced and fixed: ACV dropped, building value not taken.
* **The seam is tested, not just the function.** `test_the_merge_ACTUALLY_drops_a_
  role_blind_SCALAR` drives the real `merge_facts`. Standing lesson from the
  declarations-index arc: *"an offline probe proves the FUNCTION, never the SEAM
  around it."* **Proved it bites** by reverting the one-line gate - it failed, and
  nothing else did.
* Tests: `tests/test_inferred_value_gates_20260903.py` (71).
* Suite **5455 passed / 2 failed / 14 skipped** - the same two documented
  pre-existing failures. Zero regressions.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-I | **No LLM prompt change for either fix.** | H1-K measured that a prompt rule forbidding exactly this was ignored anyway. A prompt is also a `PROMPT_VERSION` bump, which invalidates every cached extraction and re-extracts every package at full cost. Deterministic gates are cache-safe and enforceable. |
| D-J | **The role table applies to every fact, not just lists.** | Half-applying it is why adding `certificate` alone would have fixed nothing. One table, one meaning, matching its own documented contract. |
| D-K | **Certificate keeps identity, policy, carrier, date and coverage-line facts.** | Blinding those would break the ACORD 25 multi-carrier roster. A certificate is a bad witness to the RISK, an excellent one to the CONTRACT. |

### LIVE VERIFICATION - run 3, both files, 2026-09-04

Re-uploaded the same two PDFs after the gates shipped. Diffed against run 2.

| | Run 2 (before) | Run 3 (after) |
|---|---|---|
| Warnings | 9 | **8** |
| ACV valuation advisory | *"Actual Cash Value (ACV) selected on a building valued at $4,200,000"* | **gone** |
| Property COPE missing | occupancy type, construction type | occupancy type, construction type, **building or BPP value** |
| Binder / placement follow-up | 2 items | **1 item** |

**Both predictions held exactly.** The building value going back to MISSING is the
POINT, not a regression - it is what run 1 (the declarations page alone) always
said correctly, and the certificate may no longer manufacture it.

**Nothing else moved.** SYS-05 still passes on the same run: the "treated as
equivalent" notice, `Kidnap and Ransom` reported once, no Resolve button, the
"Advice only" line, and the binder tier. ACORD 125 still shows $18,605 total,
CRIME $1,225, four lines ticked with premiums and no coverage part among them.
Data Consistency still reads "not a conflict" with both documents cited.

**The role-blind widening cost nothing that mattered.** `total_revenue`,
`num_employees` and `years_in_business` are on the certificate's blind list and
are still in "Key details in place" - the declarations page supplies them, which
is the fail-safe working as designed. Carrier, policy numbers, dates and
`coverage_lines` all still come through from both documents.

### Still open after run 3 - neither caused by these fixes

Both were already present in run 2 before the gates, and both are two-document
only (run 1, the dec page alone, was correct):

1. **Operations description is blank on the ACORD 125.** Page 2's "Description of
   Operations" and "Description of Primary Operations" are both empty, while the
   readiness card still lists "Operations description" as in place, and the
   Additional Interest block DOES print "Refrigerated trucking and cold storage".
   So the fact exists and reaches at least one stamper. A `pdf_service` issue,
   not extraction.
2. **"Key details in place" goes 12 -> 8** when the second document is added -
   mailing address, lines of business, entity type and contact information leave
   the list. All four are correctly filled ON THE FORM, so this is the readiness
   card's own list (`sqs_service._tier1_items`), not the data. Display only.

---

## The two remaining two-document defects - SHIPPED 2026-09-04

Both invisible on a single-document submission, and both the SAME shape as a
defect this codebase already fixed once: **a PER-DOCUMENT signal answering a
PACKAGE-LEVEL question.** `producer_fields_exempt` records that shape in its own
correction #1 (it keyed on `_doc_type`, the PRIMARY document's type, so a dec
page + application package was exempted from producer name even though the
application prints it). Its remedy was `_only_dec_page`, computed over EVERY
active document. Both fixes below take the same remedy.

### 1. A supporting certificate collapsed the whole submission's checklist

**Measured:** "Key details in place" went **12 -> 8** the moment a certificate was
uploaded beside the declarations page. Mailing address, lines of business, entity
type and contact information all left the list - while the generated ACORD 125
printed every one of them correctly. The data was right; only the checklist was
wrong.

`_tier1_items` collapses Tier 1 to two items on `is_certificate_doc`. That flag
is per-document ("this document IS an ACORD 25/28") and flags merge across the
package, so one supporting COI spoke for the whole submission.

The collapse is **right** for a submission that is only a certificate - a COI
cannot carry an application's checklist, and demanding one marks a submission
down for what its document type can never state. It is wrong the moment the
package also carries a dec page or an application.

New `_only_certificate` (pipeline, over every active document) + new
`sqs_service.certificate_only_package()`. `has_certificate_request` is untouched:
that one IS package-level and means the producer asked for a COI.

**Legacy sessions have no such key**, so a genuine certificate-only package stops
being exempt on its next recalculation and is asked for the full checklist. That
direction can only ADD checklist items, never hide one - the same migration
`_only_dec_page` took.

**Two existing tests failed, and the TEST was wrong, not the code.**
`test_certificate_package_lists_only_its_two_tier1_items` expressed "a
certificate package" with `{"is_certificate_doc": True}` - a package-level
intent carried by a document-level signal, which is the defect itself. Its
fixture now sets `_only_certificate` too; the assertion is unchanged.

### 2. "Description of Primary Operations" shipped blank on ACORD 125

**Measured by driving the real stamper**, not reasoned about: with the scalar
`operations_description` present, both the premises row AND the primary-operations
box fill. With the value only on `property_locations[0]`, the premises row fills
and **the primary-operations box ships BLANK** - the binding is one-directional
(`BuildingOccupancy_OperationsDescription` is schedule-backed and falls back to
the scalar; nothing goes the other way).

New `_derive_operations_description_from_locations`, in the merge tail beside the
other derivations. Derived at the FACT rather than at the field on purpose: the
same absence otherwise costs a Tier 2 checklist item, an ACORD 126 narrative and
the NAICS suggester's only input. One derivation, every consumer.

**It refuses to guess.** Only when the premises that state a description all state
the SAME one - two premises describing different operations is a real distinction
that the ACORD's per-location boxes already carry, and collapsing them into one
applicant-level sentence would invent a fact (Principle 4). Never overwrites a
stated value; labels itself `derived` (Principle 6).

### HONEST LIMIT ON #2 - read this before assuming the live blank is fixed

The live 2-document run had BOTH operations boxes blank, and the derivation above
only helps when the premises schedule carries the text. **Four hypotheses for the
live case were tested and FALSIFIED:**

| Hypothesis | Result |
|---|---|
| Withheld as an unresolved cross-document conflict | **No** - `CONFLICT_WITHHOLD_KEYS` is EMPTY (owner ruling D16) |
| The longer certificate wording tripped a length/guard limit | **No** - drove the stamper with both the 67-char and 189-char values; both stamp |
| Guard 4 blanked it as cross-field boilerplate bleed | **No** - reproduced the 3-family cluster including the gap-filled Additional Interest text; all three survive |
| An envelope / not-applicable fact shape | **No** - every shape tested is consistent: the readiness card says "in place" **if and only if** the field stamps |

That last row is the useful one: **there is no fact shape where the card reports
"in place" and the box ships blank.** So in the live run
`operations_description` was genuinely EMPTY at generation time while the
pre-form card (an earlier point in the pipeline, on a different facts dict) still
reported it present. Closing that needs the session's own facts -
`py backend/scripts/dump_session_facts.py <session_id>` - not the PDFs.

### Verification

* Tests: `tests/test_two_document_regressions_20260904.py` (24), including a seam
  test that reads `extraction_pipeline` and fails if `_only_certificate` is ever
  computed from anything but the full active-document list.
* Suite **5479 passed / 2 failed / 14 skipped** - the same two documented
  pre-existing failures. Zero regressions.

| # | Decision | Reasoning |
|---|---|---|
| D-L | **`_only_certificate` mirrors `_only_dec_page` rather than inventing a new mechanism.** | Same question, same shape, same file. A second mechanism for "what is this package made of" is the duplication class that has already cost this codebase three incidents. |
| D-M | **Derive the operations fact, not the field.** | A field-level fallback would fix one box on one form and leave the Tier 2 checklist, ACORD 126 and the NAICS suggester still blind. |
| D-N | **Premises that disagree derive nothing.** | The per-location boxes already carry the distinction; one applicant-level sentence would invent a fact (Principle 4). |

### CORRECTION - the first checklist fix was INCOMPLETE (2026-09-04)

The live re-run still read **8 items**. The fix had gated `is_certificate_doc`
and left `has_certificate_request` alone, on the reasoning that it was "already
package-level".

**It is package-level, and it answers a different question.** The extraction
prompt sets it when a document *"lists a certificate holder"* - and the SYS-05
certificate names Cascade Terminal Authority. A full commercial package
routinely needs a COI for a landlord or a terminal. **Needing one is not being
one.**

Fixing one signal and assuming the other was safe is the same mistake as the bug
itself: a flag that answers question A deciding question B. Both signals are now
gated on `certificate_only_package`.

**And grepping for the flag afterwards found a THIRD site.** `calculate_sqs`:

```python
is_cert_only = fid == "ACORD_25" or flags.get("is_certificate_doc", False)
```

Any uploaded COI graded the **ACORD 125** against the CERTIFICATE checklist
(applicant / effective date / policy number) instead of its own application
checklist. That does not mis-score a form slightly - it grades the wrong form.
`fid == "ACORD_25"` is correct and stays; the package half now goes through the
same door. **SCORES MOVE (D6)** on any package carrying a COI beside other
documents: those forms are now graded against their own checklist.

Three copies of one question is the duplication class that cost this codebase the
Umbrella SIR and auto-symbol bugs - each survived its FIRST fix because a second
copy went unchanged. `test_all_three_sites_read_the_same_door` now fails the
build if a site reads `is_certificate_doc` without the package door.

Verified across every flag combination:

| Package | in place |
|---|---|
| dec + COI naming a holder (**the live case**) | **12** |
| dec page that names a certificate holder | 12 |
| legacy session, no `_only_certificate` key | 12 |
| certificate ONLY, holder named | 8 |
| certificate ONLY, no request flag | 8 |
| plain dec page | 12 |

Tests: `tests/test_two_document_regressions_20260904.py` (28).
Suite **5483 passed / 2 failed / 14 skipped** - the same two documented
pre-existing failures.

### The blank operations boxes - ROOT CAUSE FOUND AND FIXED (2026-09-04)

**Guard 4 was deleting a field's own value.** Found by driving
`_enforce_post_fill_guards` directly rather than by another live round trip.

Guard 4 CLUSTERS free-text values by near-duplicate similarity, then decided
whether to EXEMPT a field by **exact string equality** against its own
deterministic value:

```python
det = _deterministic_map(f, facts)
legit_owner = isinstance(det, str) and det.strip().lower() == s.lower()
```

**Fuzzy to accuse, exact to acquit.** So a stamped value differing from its fact
by a single character - a trailing period, a normalisation, display
canonicalisation, one document's wording against another's - was blanked AS
BOILERPLATE BLEED while being the field's own data.

Reproduced character for character: adding ONE trailing period blanked BOTH
`BuildingOccupancy_OperationsDescription_A` and
`CommercialPolicy_OperationsDescription_A` while the Additional Interest item
description survived. That is the live symptom exactly.

**It fires hardest on MULTI-DOCUMENT packages**, because that is when two
sources supply near-identical wording and the merged fact can differ from the
stamped text by punctuation. Single-document run 1 was byte-identical, so it
never fired - which is why this looked like a two-document bug.

**Fix: one comparison for both halves.** Ownership now accepts exact equality,
near-duplicate similarity (the SAME predicate the clustering uses), or
directional token containment (the field's own value plus the second document's
extra sentence - the value is demonstrably in there, so blanking deletes real
data to remove an addition). Containment is token-exact and directional, so it
can never accept text that merely resembles the field's value.

**The guard is not weakened.** A field with no deterministic value of its own
still returns None and is still blanked - the actual bleed case. Verified: the
same boilerplate in three unrelated fields is still removed from all three.

| Stamped value | Before | After |
|---|---|---|
| byte-identical | KEPT | KEPT |
| **trailing period (the live case)** | **BLANKED** | **KEPT** |
| display-canonicalised casing | KEPT | KEPT |
| whitespace normalised | BLANKED | KEPT |
| + the certificate's extra sentence | BLANKED | KEPT |
| genuine boilerplate in 3 unrelated fields | BLANKED | **BLANKED** |

### Four wrong hypotheses before this one, all falsified by measurement

Withhold list (empty), value length (both stamp), a 3-field Guard 4 repro (all
survived - the cluster was too small to expose the exact-match trap), and fact
envelope shape. **The fifth attempt found it by varying the STAMPED value
instead of the FACT** - the guard compares the two, and every earlier probe had
held them identical.

Standing lesson: when a guard takes two inputs, vary BOTH. Holding one fixed
tests half the predicate.

### Checklist fix CONFIRMED LIVE

"Key details in place" now reads **13 items** - Producer / Agency name, Applicant
legal name, mailing address, effective date, lines of business, entity type,
contact information, FEIN, operations description, annual revenue, employees,
years in business, NAICS. Thirteen rather than run 1's twelve because producer
name is correctly APPLICABLE once the package is not dec-page-only, and it is
satisfied (both documents print the agency).

Tests: `tests/test_two_document_regressions_20260904.py` (35).
Suite **5490 passed / 2 failed / 14 skipped** - the same two documented
pre-existing failures.

| # | Decision | Reasoning |
|---|---|---|
| D-O | **Guard 4 uses ONE comparison for clustering and for ownership.** | Clustering fuzzily and acquitting exactly is internally inconsistent, and the inconsistency is what deleted real data. A field whose own rule produces a near-duplicate IS the owner - that is what the exact test was reaching for, expressed too literally. |
| D-P | **Containment counts as ownership.** | On a multi-document package the stamped text is often the fact plus one more sentence. The value is in there; blanking deletes real data to remove an addition. Directional and token-exact so it cannot accept a lookalike. |

### THE BLANK OPERATIONS BOXES - ACTUAL CAUSE, FOUND IN THE SESSION DATA (2026-09-04)

**Six predictions were made from the CODE. All six were wrong.** The withhold
list (empty), the value's length (both stamp), a three-field Guard 4 repro
(cluster too small), the fact envelope shape, Guard 4's exact-match ownership
(a REAL defect, fixed, but not this one), and the declared-type guard.

The answer took four minutes once the real session's facts were loaded and INFO
logging was on. The guard named itself:

```
truncated_copy blanked=CommercialPolicy_OperationsDescription_A
  value='Refrigerated trucking and cold storage w...'
  - it is the cut-off head of '...warehousing of food p...', which we hold in full
```

**`_is_truncated_copy_of_a_held_value` blanks any narrative that is a PREFIX of
another held value.** On the two-document package the facts were:

```
operations_description                = "...warehousing of food products"
certificate_description_of_operations = "...warehousing of food products.
                                         Certificate holder is an additional
                                         insured with respect to operations at
                                         the terminal, as required by written
                                         contract."
```

The second is the first **plus a new sentence** - a certificate appends its own
additional-insured wording to the same opening description. Two different facts
sharing an opening sentence, not one value cut in half. `_normalize_for_search`
strips punctuation, so the sentence boundary that tells them apart was invisible
and the complete value was deleted as a stump.

**Fix - the structural second condition** (H1-F's standing rule again: a test
that is necessary but not sufficient needs one). A real truncation stops
mid-word or mid-clause; a complete statement stops at a sentence boundary:

* the shorter already ends in `.` `!` `?`               -> COMPLETE, keep it
* the longer continues with a new sentence (`. Foo`)    -> COMPLETE, keep it
* the longer continues the same word or clause          -> TRUNCATED, blank it

The prefix test is still required, so this only ever REFUSES to blank: it can
cost a genuine truncation catch and can never delete a value the old code kept.

**Verified on the real session, end to end** (`/tmp/repro.py` against the stored
facts, not a fixture): both `BuildingOccupancy_OperationsDescription_A` and
`CommercialPolicy_OperationsDescription_A` now survive Pass 1 AND the post-fill
guards. Before: both `None`.

### New tool: `backend/scripts/why_is_ops_blank.py`

No arguments. Loads the newest session through the decrypting repository and
prints the merged facts, each document's contribution, the premises schedule,
the package flags, the withhold list, and what the stamper produces - then tells
you how to read it:

```
section 1 empty            -> extraction/merge never produced the fact
section 1 filled, 6 None   -> the stamping rule is the problem
sections 1 and 6 filled    -> a POST-FILL GUARD is blanking it
```

It said "a post-fill guard" on the first run. Six code-based guesses; one data
read.

**STANDING LESSON, and this is the second time it has been earned in this
repo.** `dump_session_facts.py` exists because on 2026-08-17 *"three of four
predictions about conflict behaviour were wrong, and every one of them was wrong
because the reasoning was done against the CODE instead of against a real
session's facts."* The same mistake, the same cost. **When a live symptom does
not match the code's apparent behaviour, load the session before forming a
sixth hypothesis - and turn on INFO logging, because these guards already
announce themselves by name.**

Tests: `tests/test_two_document_regressions_20260904.py` (48).
Suite **5503 passed / 2 failed / 14 skipped** - the same two documented
pre-existing failures.

| # | Decision | Reasoning |
|---|---|---|
| D-Q | **Prefix alone never means truncation.** | Two facts can legitimately share an opening sentence - a certificate's narrative is the operations description plus its own additional-insured wording. The boundary decides: mid-word is a stump, a sentence end is a statement. |
| D-R | **Guard 4's ownership fix stays even though it was not this bug.** | It was independently reproduced deleting a field's own value whenever the stamped text differed from the fact by punctuation. A real defect found on the way is still a real defect. |

### LIVE CONFIRMED - run 6, 2026-09-04

ACORD 125 page 2 now prints, on the two-document package:

```
DESCRIPTION OF OPERATIONS:        Refrigerated trucking and cold storage warehousing of food products.
DESCRIPTION OF PRIMARY OPERATIONS: Refrigerated trucking and cold storage warehousing of food products
```

**Proved strictly additive before believing the form.** Ran the real session's
facts through `map_facts_to_form` twice - once with the shipped code, once with
`_is_cut_off_mid_sentence` forced to `True` (the exact old behaviour) - and
diffed every populated field:

```
fields filled  OLD=62  NEW=64
GAINED (2)  BuildingOccupancy_OperationsDescription_A
            CommercialPolicy_OperationsDescription_A
LOST (0)
CHANGED (0)
```

Zero lost, zero changed. Both of this session's guard fixes (the truncated-copy
boundary and Guard 4's ownership) can only ever REFUSE to blank, and the diff
proves it on real data rather than asserting it.

The Additional Interest block renders differently between runs (item description
/ reason for interest move around, and the additional-insured box is now
ticked). That is gap-fill variance - the LLM fills different optional fields each
run - and cannot be either fix: both are strictly keep-more, as the diff shows.

**ALL SIX ITEMS FROM THIS ARC ARE NOW CLOSED AND LIVE-VERIFIED.**

---

## SYS-06 - Keep carrier and policy number line-specific - THE DIAGNOSIS

**Kept as the record of what was found and measured. The fix that shipped is the next section.**

### What the client asked for

> *"Maintain the relationship Line of Business -> Carrier -> NAIC -> Policy Number ->
> Effective Date -> Expiration Date -> Source. Compare values only within the same
> line/policy context. When the producer confirms a mapping, apply it only to the
> applicable line or lines and populate the corresponding forms from that line-specific
> record. Different policy numbers across different lines are valid and must not create a
> conflict by themselves."*

Their regression table (Orbin): GL = EMC Property & Casualty / 25186 / `BBC7263-26`;
Auto = Employers Mutual Casualty / 21415 / `6E7-40-02---26`; Umbrella = same carrier /
`6J7-40-02---26`; Inland Marine = same carrier / `6C7-40-02---26`.

On screen: a **Carrier** picker reading *"two policies on the same coverage line in one
submission - confirm which applies"*, and a **Policy Number** picker offering NINE values
(`6E7-40-02---26`, `6C7-40-02---26`, `IM 7100 06 04`, `IM 7201 10 02`, `6J7-40-02---26`,
`BBC7263 - 26`, `BBC7263`, `6E74002`, `6J74002`) under one "Confirm & apply to forms".

### The headline: line scoping ALREADY EXISTS. It fails shut.

Verified by driving the real code, not by reading it:

| Machinery | State |
|---|---|
| `coverage_lines` (line, carrier, naic, policy_number, eff, exp) | **is** the client's chain, already extracted (RULE 16). Only `Source` is missing. |
| `facts["_scoped"]` (`extraction_service._build_scoped_fact_store`) | already stores each line-scoped fact WITH its line + policy number |
| Data Consistency `status="scoped"` + per-line chips in `AcordModal.jsx` | already built, already renders *"N policies, N values - not a conflict"* |
| Section forms 126/127/131/141/130/140 + ACORD 25 per-line rows | already resolve identity per line and are **immune to a package-wide confirm** (measured: confirming the Auto number left ACORD 126 on `BBC7263 - 26`) |

So SYS-06 is not a missing feature. It is six ways the existing scope logic collapses back
to one submission-wide question.

### Reproduced with the client's OWN table and perfectly clean data

`assess_underwriting_consistency` on a dec page + a COI, both stating the four policies
correctly, no OCR noise:

```
carrier_name  => scoped   (auto/inland_marine/umbrella  vs  general_liab)   <- correct
policy_number => conflict "two policies on the same coverage line in one
                           submission - confirm which applies"
                 BBC7263 - 26 / 6E7-40-02---26 / 6J7-40-02---26 /
                 6C7-40-02---26 / BBC7263 / 6E74002 / 6J74002
```

The client's literal message, from clean input. Nothing about their documents is required
to produce it.

### Defect 1 (root cause) - ONE policy printed two ways becomes TWO policies on one line

`extraction_service._coverage_line_dedup_keys` identifies a `coverage_lines` row as
**(canonical line, policy number with punctuation stripped)**:

```
'BBC7263 - 26'    -> coverage_line:general_liab:BBC726326
'BBC7263'         -> coverage_line:general_liab:BBC7263      <- different key
'6E7-40-02---26'  -> coverage_line:auto:6E7400226
'6E74002'         -> coverage_line:auto:6E74002              <- different key
```

Measured: `_union_list_fact` keeps **4 rows where 2 exist**. Then
`_build_scoped_fact_store` writes one record per row, so `general_liab` carries two policy
numbers, and `_scope_from_store` - whose rule is *"no two groups share a line"* - correctly
concludes two policies sit on one line and refuses to scope the WHOLE field.

**The codebase already knows those are one contract, in two places:**
`pdf_service._same_policy_contract` (*"the `---26` tail is the policy TERM marker"*) and
`fact_equivalence.PackageContext.same_contract_printing`. Both return **True** for
`BBC7263` / `BBC7263 - 26` and for `6E74002` / `6E7-40-02---26`. **Neither is consulted by
the dedup key or by the scoped store.** Third copy of "is this the same policy?", and the
weakest copy decides - the duplication class that already cost this repo the Umbrella SIR
and auto-symbol bugs.

### Defect 2 - a certificate row is treated as a RIVAL policy

The form side filters `coverage_lines` through `_line_entry_grants_coverage`, which
requires a **premium or a limit**. Its own docstring says *"a certificate of insurance
never prints premiums, so most COI rows are `grants=False`"*.

`_build_scoped_fact_store` applies **no such filter**. So one COI row is
*not a grant* to the stamper and *a second policy on this line* to the picker. Same data,
two verdicts, one of them user-visible.

### Defect 3 - scoping is ALL-OR-NOTHING

`_scope_from_store` returns `False` for the entire field if **any single** value group is
unplaceable (`if not all(lines_for): return False, None`) or if **any two** share a line.

Measured: adding ONE stray value - a bureau name (`AAIS`, which prints in ISO/AAIS form
footers) or a form number (`IM 7100 06 04`) - flips four perfectly-scoped policies into one
flat package-wide "pick one" list. Both stray shapes appear in the client's screenshots.

### Defect 4 - the fallback merge can NEVER fire on 3+ policies

In `fact_equivalence.equivalent_index`, the proof "these belong to different contracts"
(`different_owners`) is expressed as a **merge partnership**. With four policies every
dec-page number partners with every other one, so each has 3 mates and the ambiguity guard
(`len(set(mates)) != 1`) cancels every merge - including the genuine
`BBC7263` / `BBC7263 - 26` pair. Measured: `equivalent_index` returns **None** on the
client's four numbers. Two policies work; three or more never do.

### Defect 5 - the ANSWER has no scope either

`UnderwritingConfirmRequest` is `{session_id, fact_key, value}`. `apply_confirmations`
writes `facts[fact_key] = one envelope`. There is no way to say *"this is the Auto
policy's number"*.

And Pass 1's field rules read the package scalar AS the GL number -
`("Policy_GeneralLiability_PolicyNumberIdentifier", "policy_number")`, whose own comment
says *"the GL/primary row's own number, per every other rule in this block"*. That is the
client's sentence **"default a confirmed value to the GL package policy"**, verbatim, in
the code.

*(Mitigation already in place: the section forms and ACORD 25 rows override the scalar, so
the blast radius today is ACORD 125's package header. The carrier/NAIC pair is also still
protected - confirming a mismatched pair was tested and the resolver refused it.)*

### Defect 6 - presentation drops the very thing the client wants to see

* `policy_number` and `carrier_naic` are **not curated** Data Consistency fields. They
  arrive through `ENABLE_FULL_FIELD_RECONCILIATION` auto-discovery, and auto fields are
  **dropped from the payload when `status == "scoped"`**. So on a HEALTHY four-policy
  package the producer is shown nothing at all about policy numbers, and on an unhealthy
  one they get a nine-way package-wide pick. Neither is the line table the client asked
  for.
* Pass 1b already records `"line"` on every `coverage_line`-sourced value. `AcordModal`
  renders `sources.map(s => s.filename)` and throws the line away.

### Proposed approach (5 layers) - ALL FIVE SHIPPED, see the next section

| # | Layer | Fixes |
|---|---|---|
| L1 | **One door for "same policy contract?"** - promote `_same_policy_contract` into the shared comparison door and have the dedup key, the scoped store and `_scope_from_store` all ask it. Guard test against a fourth copy. | 1, 2, 4 |
| L2 | **Store the LINE RECORD, not per-fact lists** - one record per (line, contract) carrying carrier + NAIC + number + term + **source documents**, de-duplicated through L1, with evidence strength so a COI row corroborates instead of competing. This is literally the client's chain. | 1, 2, 6 |
| L3 | **Scope per VALUE, not per field** - placed groups keep their line; only the unplaceable or line-colliding remainder becomes the question. | 3 |
| L4 | **A confirmation carries its scope** - optional `scope` on the confirm request; `apply_confirmations` writes the line record. No scope = today's package-wide behaviour, so legacy sessions are untouched. | 5 |
| L5 | **Show the line record** - curate `policy_number` / `carrier_naic`, render the line chip already present in `sources[].line`. | 6 |

### What must NOT be lost

A genuine **two different policies on the same line** (EMC GL `BBC7263-26` vs Travelers GL
`GL-4471102-26`) must still surface - that is defect D-1 from 2026-08-23 and the client's
own regression rule: *"a mismatch within the same line/policy context is what should
trigger review."*

### Score risk: NONE (verified, not assumed)

`policy_number` / `carrier_name` / `carrier_naic` are absent from
`HARD_STOP_RECONCILABLE_KEYS`, `GENERATION_BLOCKING_RECONCILABLE_KEYS` and
`CONFLICT_WITHHOLD_KEYS` (empty), and `sqs_service.check_doc_consistency` compares names /
FEIN / entity / addresses / dates only - never carrier or policy number. L1-L3 can only
REMOVE questions, so no cap moves. L4 changes an API contract and an audit row.

### Repro scripts (scratchpad, not committed)

`sys06_repro.py` (client table -> conflict), `sys06_repro2.py` (stray-value and
form-number variants), `sys06_repro3.py` (union -> the client's literal message),
`sys06_forms.py` / `sys06_forms2.py` (proof the section forms are already line-specific
and immune to a package-wide confirm).

---

## SYS-06 - SHIPPED 2026-09-04

**Everything in the diagnosis above was built. Five layers, one new test file (59),
full suite 5563 passed / 1 failed (the documented `httpx` ImportError), frontend build
clean.**

### The acceptance criteria, and where each one is now satisfied

| Client's criterion | Where it lives now |
|---|---|
| Maintain LoB -> Carrier -> NAIC -> Policy Number -> Effective -> Expiration -> **Source** | `facts["_line_records"]`, one record per (line, contract), built at merge |
| Compare values only within the same **line/policy context** | `_scope_from_store` compares by RECORD id, not by line |
| A confirmation applies **only to the applicable line(s)** | `policy_number@general_liab` confirmation keys + `_apply_scoped_confirmations` |
| ...and **populates the corresponding forms from that line-specific record** | the answer is written onto that line's `coverage_lines` row, which every per-line stamper already reads |
| Different policy numbers across different lines are **not a conflict by themselves** | `fact_comparison.same_policy_contract` + the record fold |

### End-to-end proof, through the real `merge_facts` and the real stamper

Client's regression table + a certificate printing the same four policies without their
term markers + two ISO/AAIS form numbers. **Nine `coverage_lines` rows in, four policies
out, zero conflicts:**

```
DATA CONSISTENCY        conflict_count = 0   review_required = False
  Carrier               SCOPED
  Policy Number         SCOPED
  Carrier NAIC          SCOPED

POLICIES IN THIS SUBMISSION
  Line                          Carrier                            NAIC   Policy number    Term                    Source
  Commercial General Liability  EMC Property & Casualty Company    25186  BBC7263 - 26     07/15/25-07/15/26       dec, COI
  Automobile Liability          Employers Mutual Casualty Company  21415  6E7-40-02---26   07/15/25-07/15/26       dec, COI
  Commercial Umbrella           Employers Mutual Casualty Company  21415  6J7-40-02---26   07/15/25-07/15/26       dec, COI
  Commercial Inland Marine      Employers Mutual Casualty Company  21415  6C7-40-02---26   07/15/25-07/15/26       dec

FORMS
  ACORD_126 (GL)             'BBC7263 - 26'      'EMC Property & Casualty Company'    naic='25186'
  ACORD_127 (Auto)           '6E7-40-02---26'    'Employers Mutual Casualty Company'  naic='21415'
  ACORD_131 (Umbrella)       '6J7-40-02---26'    'Employers Mutual Casualty Company'  naic='21415'
  ACORD_141 (Inland Marine)  '6C7-40-02---26'    'Employers Mutual Casualty Company'  naic='21415'
```

### L1 - ONE door for "are these the same policy?"

`fact_comparison.same_policy_contract(a, b)` + `policy_contract_groups(values)`.

The RULE is not new - it has lived in `pdf_service._same_policy_contract` since the
2026-08-17 ACORD 125 Q4 audit. What is new is that it is behind the door. Before SYS-06
there were **three** answers:

```
pdf_service._same_policy_contract       term-marker rule, context-free
PackageContext.same_contract_printing   prefix election, needs the dec index
_coverage_line_dedup_keys               raw alnum equality      <- the WEAKEST
```

and the weakest one decided whether the picker saw one policy or two.
`pdf_service._same_policy_contract` is now a delegation with the original body kept as an
import-failure fallback (byte-identical - swept over 144 pairs). `test_the_stamping_layer_
delegates_to_the_door` fails the build if a fourth copy appears.

**The separated tail is the whole safety story.** `POL123` / `POL12345` are two policies
whose digits run together; the term marker only counts when the document PRINTED it
separated (`---26`, ` - 26`). That single condition is why `BBC7263-26` vs
`GL-4471102-26` still separates - defect D-1, and the client's own review trigger.

### L2 - the line record, and why NOT the dedup key

`extraction_service._build_line_records` folds `coverage_lines` into one record per
(canonical line, policy contract), carrying carrier + NAIC + number + term + **sources**
(which uploaded documents printed it) + `granted` + every `printings` variant.
`_scoped` is now DERIVED from those records - one structure, one truth - and its documented
shape is unchanged apart from an additive `scope.record` id.

**`_coverage_line_dedup_keys` was deliberately NOT changed.** 39 read sites, two recorded
defects behind that (line, contract) pairing, and D-A already says so. The fold happens at
the READER, where the only consumers are the picker and the E&O record. The union still
keeps both printings; the record layer decides they are one policy.

### L3 - compare within the line/POLICY context

`_scope_from_store` now maps each value group to the RECORD ids it is stated on, not just
the lines. Two groups sharing a record are two printings of one contract's one fact and can
never be rivals; two groups on the same line with **different** records is the genuine
"two policies on one coverage line" question - and the reason string now names the line.

`_merge_by_line_record` runs before the scope decision and folds groups the records prove
are one contract. It is merge-only, so it can never manufacture a conflict.

`_store_entries` fills the gap when a session's stored scope predates a fact (see the
regression below).

### L4 - the answer carries its scope

* `UnderwritingConfirmRequest.scope` - optional, omitted = today's submission-wide meaning.
* Stored as `policy_number@general_liab`. Every existing reader resolves an unknown key to
  no reconcilable field and skips it, so the namespaced entry is **inert to code that has
  not been taught about it** - that is why the scope is encoded in the KEY rather than by
  changing the map's value shape, which five call sites would have had to understand.
* `_apply_scoped_confirmations` writes the value onto that line's own `coverage_lines`
  row(s), rebuilds the derived store, and **never touches the package scalar**.
* The forms then need NO change: `_resolve_section_policy_identity`,
  `_resolve_current_policy_line_cell` and `_section_carrier_pair` already read this line's
  own row. Proved by driving the real stamper - confirming Travelers for the GL line put it
  on ACORD 126 and left ACORD 127 on Employers Mutual.
* "Apply to all" (linked fields) is **disabled for a scoped answer**: it is a
  submission-wide convenience, and spraying a one-line claim across another field
  package-wide is the opposite of what was asked.
* Rows are copied before mutation - `apply_confirmations` shallow-copies, so an in-place
  edit would reach back into the session's stored facts and rewrite history.

### L5 - the mapping is shown

`policy_number` and `carrier_naic` are now curated Data Consistency fields. They previously
arrived only through auto-discovery, and **an auto-discovered field is dropped from the
payload the moment its status is "scoped"** - so on a healthy four-policy package the
producer saw nothing at all about policy numbers, and on an unhealthy one a nine-way
package-wide pick. Curating them costs no new noise: the panel renders conflict / confirmed
/ scoped only, never "consistent".

Frontend: a **Policies in this submission** table (line / carrier / NAIC / policy number /
term / source) above the Data Consistency rows on a multi-policy package; a per-line
`Confirm for <line>` button when the dispute is about exactly one line; and confirmed
line answers shown on the scoped row.

### THE BUG MY OWN FIX SHIPPED FIRST, caught by an existing test

`test_two_carriers_on_the_SAME_line_is_still_a_conflict` (H5) builds the pre-SYS-06 store
by hand - `scope.line` but no `scope.record`. My first cut read the record id as
`scope.get("record") or line`, so on a legacy store **every value on a line looked like one
contract**, Alpha and Beta Insurance folded into a single candidate, and the conflict
vanished. Exactly the over-fold I had written down as the one thing that must not happen.

**Rule now: no record id = no proof of a shared contract** (Principle 3 - absence is not a
value). A legacy store therefore behaves exactly as it did before. Pinned by
`test_a_legacy_store_with_no_record_ids_never_folds`.

**Lesson, again: the positive control is the test that earns its keep.** Every one of the
57 new tests passed on the first run; the failure came from a control written a week
earlier for a different fix.

### A REAL REGRESSION THE FULL SUITE FOUND, and the fix

`test_r03_multi_insurer_documents_raise_no_consistency_conflict` went red: a legitimately
three-carrier, three-NAIC package started reporting a **NAIC conflict**.

Cause: nothing writes `carrier_naic` as a scalar, so auto-discovery had never seen it and
the picker had never assessed it. Curating it (L5) made it visible - and that session's
stored scope, written before the field was curated, had no entries for it, so it could not
be placed and fell through to the character-keyed path, which cannot place a 5-digit code.

**A store that covers only part of the chain is a half-scoped package.** `_store_entries`
now rebuilds the records from `coverage_lines` when the store cannot speak for a fact.
Pure gap-filling - a stored entry always wins, so nothing that scopes today scopes
differently. Pinned by `test_a_store_that_predates_a_fact_does_not_half_scope_the_package`
and `test_a_stored_entry_always_wins_over_a_derived_one`.

### Proved every fix bites

Each was reverted in turn and the suite re-run:

| Reverted | Result |
|---|---|
| record id falls back to the line | 2 failed |
| no contract folding (one record per row) | 5 failed |
| form numbers count as policy numbers | 1 failed |
| the derived-store fallback | 2 failed |
| all restored | 87 passed |

### Score risk: NONE, verified not assumed

`policy_number` / `carrier_name` / `carrier_naic` appear in no
`HARD_STOP_RECONCILABLE_KEYS`, no `GENERATION_BLOCKING_RECONCILABLE_KEYS`, and
`CONFLICT_WITHHOLD_KEYS` is empty. `sqs_service.check_doc_consistency` compares names /
FEIN / entity / addresses / dates - never carrier or policy number. L1-L3 and L5 can only
REMOVE questions. **What the client WILL see change: rows that read "VALUES DIFFER -
CONFIRM" now read "N policies, N values - not a conflict", and the "to fix" badge drops.
That is the deliverable, not a regression - tell Brent before he notices the count fall.**

### Verification

* Client's regression table, end to end through `merge_facts` + `map_facts_to_form`.
* Tests: `backend/tests/test_sys06_line_specific_identity_20260904.py` (59), adversarial
  cases FIRST in the file, plus a seam test that drives the real `merge_facts` (standing
  lesson: an offline probe proves the FUNCTION, never the SEAM).
* Suite **5563 passed / 1 failed / 14 skipped**. The one failure is the long-documented
  `test_arq_acord125_missing_only` `httpx`/`openai` ImportError.
* Frontend `VITE_API_BASE=https://api.primble.io npx vite build` - clean.

**Correction to this file's own baseline note:** the SECOND documented pre-existing failure
(`test_confidence_score_covers_every_label`) is now GREEN at HEAD. Not caused by this work -
`sqs_service.py` was not touched here and `confidence_fill_rate` still ends
`return int(...)`, so the truncation defect itself is still open. **The baseline is now 1
pre-existing failure, not 2.**

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-S | **`same_policy_contract` goes in `fact_comparison`, and `pdf_service` delegates.** | Three answers to one question, and the weakest one was deciding user-visible behaviour. Same duplication class as the Umbrella SIR and auto-symbol bugs. Not folded into `identifiers_match`: that is the loss-run matcher's contract and widening it would loosen an unrelated comparison. |
| D-T | **Fold at the READER, never in `_coverage_line_dedup_keys`.** | 39 read sites and two recorded defects sit behind that key (D-A). The picker and the E&O record are the only consumers that need the fold, so it happens where they read. |
| D-U | **`_scoped` is DERIVED from the line records, not written beside them.** | Two structures answering "which line does this belong to" is the duplication class this whole item exists to close. Shape preserved so every D19 reader is untouched. |
| D-V | **No record id means no proof of a shared contract.** | A pre-SYS-06 store has `line` but no `record`. Treating the line as the contract folded two real carriers into one candidate and deleted a genuine conflict. Absence is not a value (Principle 3). |
| D-W | **A line-scoped confirmation drops the candidates it rules out for THAT line.** | The picker's candidates also come from each document's own facts, so rewriting the merged row alone left the rejected value coming straight back - the producer would be asked forever. Narrow: a value also stated on an unanswered line is never removed on another line's behalf. |
| D-X | **The scope rides in the confirmation KEY, not in a new value shape.** | Every existing reader skips a key it cannot resolve to a reconcilable field, so the namespaced entry is inert to code that has not been taught about it. Changing the value shape would have needed the audit writer, the pipeline and five call sites to agree at once. |
| D-Y | **A scoped confirmation is refused for a fact that is not line-scoped.** | One insured however many policies. Scoping `applicant_name` to a line would invent a relationship the package does not have. |
| D-Z | **"Apply to all" is disabled for a scoped answer.** | Linked fields are a submission-wide convenience for two fields showing the identical disagreement. A one-line claim sprayed package-wide onto another field is the exact defect being fixed. |
| D-AA | **A form number is stripped to no-number, not left as a policy.** | `IM 7100 06 04` names the coverage WORDING. As a policy number it manufactures a phantom second policy on the line - two of the nine candidates in the client's screenshot. Uses a NARROW form-number test, deliberately not `_looks_like_a_policy_number`, which also rejects anything under four characters and would have cost a short-but-real number its scope. |

### Files touched

| File | Change |
|---|---|
| `backend/services/fact_comparison.py` | `same_policy_contract`, `policy_contract_groups` (+ `re` import, `__all__`) |
| `backend/services/pdf_service.py` | `_same_policy_contract` delegates to the door; original body kept as an import-failure fallback |
| `backend/services/extraction_service.py` | `LINE_RECORDS_KEY`, `_contract_key`, `_line_record_rows`, `_record_sources`, `_build_line_records`, `_merge_line_record`; `_build_scoped_fact_store` derives from them and takes `docs`; `_FORM_NUMBER_RE` / `_looks_like_a_form_number` split out of `_looks_like_a_policy_number` |
| `backend/services/underwriting_consistency.py` | curated `policy_number` + `carrier_naic`; `_scope_of_group`, `_merge_by_line_record`, `_store_entries`, `_line_records`, `_line_records_for`, `_printings_by_line`, `_drop_answered_line_candidates`; `_scope_from_store` is record-aware and returns collided lines; `scoped_confirmation_key` / `parse_confirmation_key` / `_apply_scoped_confirmations`; payload gains `conflict_scope`, `confirmed_scopes`, `line_records` |
| `backend/services/extraction_pipeline.py` | `confirm_underwriting_value(scope=...)`; linked-field spray gated on scope; `_confirmed_keys` uses bare fact keys |
| `backend/models/schemas.py` | `UnderwritingConfirmRequest.scope` |
| `backend/routes/form_routes.py` | passes `scope` through |
| `frontend/src/components/form/AcordModal.jsx` | "Policies in this submission" table; per-line `Confirm for <line>`; `confirmed_scopes` chip; `scope` sent on confirm |
| `backend/tests/test_sys06_line_specific_identity_20260904.py` | new, 59 tests |
| `backend/tests/test_underwriting_consistency.py` | exempt-set fixture extended for the two newly curated fields (property unchanged) |

### Still open, deliberately

* **Partial scoping was NOT built.** `_scope_from_store` is still all-or-nothing: one value
  group the records cannot place still sends the whole field to a package-wide question.
  The client's two stray shapes are gone at source (form numbers filtered, spelling
  variants folded), so the remaining case is a genuine mis-extraction such as the bureau
  name `AAIS` in a carrier column - which, sitting on a line beside the real carrier, is a
  "two carriers on one line" review the client's own rule says SHOULD be raised. Revisit
  with live data rather than by widening the fold speculatively.
* **A line with two rival rows keeps both rows after a scoped confirm** (identity columns
  rewritten, only exact duplicates dropped). Premium double-counting on such a package is
  **pre-existing** - two GL rows already summed twice before this change - and deciding
  which premium to discard is not what the producer was asked.
* **`_held_client` and the human-provenance restore still key on the bare confirmation
  map**, so a line-scoped answer does not suppress a package-level human value. Correct as
  it stands (different axis), noted so it is a decision rather than an oversight.
* **`fact_equivalence.same_fact` was not loosened.** Its identifier branch deliberately
  refuses to merge a prefix without the canonical joiner, and that decision has tests
  behind it. The package-level proof lives in `_merge_by_line_record` instead.

### SYS-06 LIVE TEST KIT - `sys06_test_data/` (2026-09-04)

`py backend/scripts/make_sys06_test_pdfs.py` -> three PDFs + `README-HOW-TO-TEST.md`.

**THREE files, TWO sessions, and they cannot be merged.** Package A asserts
*"nothing is wrong here"*; Package B asserts *"this IS wrong"*. Putting B's rival
GL policy into A destroys A's entire claim, so they are separate uploads with
different insureds (no cache or identity bleed).

| File | Upload | What it proves |
|---|---|---|
| `A1_package_dec_five_lines.pdf` + `A2_certificate_same_policies.pdf` | **together** | 5 lines / 2 carriers / 2 NAICs / 5 numbers -> ZERO conflicts; the certificate's tail-less printings FOLD; form numbers never become policies; the Source column cites both files |
| `B_two_GL_policies_CONTROL.pdf` | **alone** | two real GL policies still CONFLICT, the reason names the line, the Auto line stays clean, and a per-line confirm applies to GL only |

Ten edge cases are enumerated in the script's docstring. The ones worth naming:
`CR-4471` (short but REAL - the form-number filter must be narrow enough not to
eat it), the three ISO/AAIS form numbers printed in a real FORMS AND ENDORSEMENTS
schedule, and the certificate printing NO premiums (so every COI row is
`grants=False` and must corroborate rather than rival).

**The generator self-verifies, and the self-check earned its keep on its first
run.** It flagged `A1: must NOT contain 'BBC7263 '` - and the CHECK was wrong,
not the PDF: the short printing is a PREFIX of the long one by construction, so a
substring test cannot express "does not appear as a value of its own". It is now
a COUNT comparison (every occurrence of the short form must be accounted for by a
long one). The check also drives the real `same_policy_contract` to prove the
four fold pairs fold AND that B's two GL policies do NOT - a kit whose premises
are untested proves nothing.

### RUN B FOUND A DEFECT ON SCREEN - FIXED 2026-09-04

The kit's own control caught something no test had: a question scoped to ONE
coverage line was still offering candidates from ANOTHER line.

Run B (two GL policies, one clean Auto line) rendered:

```
Policy Number   Values differ - confirm
                two policies on the same coverage line (general liab) ...
                  ( ) RB-GL-880194-26
                  ( ) TR-4471102-26
                  ( ) RB-CA-880771-26      <- the AUTO policy
                  [ Confirm for general liab ]
```

**One click would have written the Auto policy number onto the General Liability
line** - the exact mis-assignment SYS-06 exists to prevent, offered as an option,
under a button that promises to apply it to GL.

The candidate list had always been the whole field; L4 made that actively
dangerous by giving the button a line to apply to. `_restrict_to_conflicted_lines`
now drops candidates not stated on the disputed line. Nothing is hidden - every
value still appears in "Policies in this submission" against its own line - and
the function refuses to act unless at least two candidates survive, so it can
never turn a real conflict into a silent single value.

Tests: `test_a_one_line_question_never_offers_another_lines_value` (the literal
run-B shape) and `test_the_restriction_never_collapses_a_real_conflict`.
**Proved it bites** - disabled, 1 failed; restored, 61 passed.
Suite **5565 passed / 1 failed / 14 skipped**.

| # | Decision | Reasoning |
|---|---|---|
| D-AB | **A line-scoped question offers only that line's values.** | "Compare values only within the same line/policy context" applies to the CANDIDATE LIST too, not just the verdict. An out-of-line candidate under a per-line confirm button is a one-click way to produce the defect. |

**Standing lesson: the control package earned its keep before the fix was even
retested.** 61 unit tests and a full suite were green while the screen was
offering a wrong answer, because every test asserted the VERDICT and none
asserted what the producer is allowed to CHOOSE.

### RUN 2's CONFIRM FLOW COULD PRINT A PAIR NO DOCUMENT EVER PRINTED - FIXED 2026-09-04

Found while reviewing the owner's second run, BEFORE any form was generated.

The producer answers three separate cards. On the control package that means
Carrier, Policy Number and Carrier NAIC, each scoped to General Liability. So:

```
confirm carrier_name@general_liab = "Redwood Basin Insurance Company"
confirm carrier_naic@general_liab = "36161"          <- Trinity Ridge's NAIC
   -> ACORD 126 printed:  Redwood Basin Insurance Company   /   36161
```

**A company beside an identifier belonging to a different company, on a signed
application.** This is RC1 verbatim (2026-08-15: *"Employers Mutual recombined
with EMC P&C's NAIC 25186 - a pair no document prints"*), reopened by the path I
added: the per-line confirm WRITES the row, so the two independent answers both
landed.

`_pair_naic_with_its_carrier` now runs before any scoped edit is applied. **The
confirmed CARRIER decides**; its NAIC is read from the rows that actually state
that carrier on that line, and a contradicting NAIC answer is overridden with a
warning rather than stamped.

Positive evidence only: the pair is set only when the documents state exactly
ONE NAIC for the confirmed carrier on that line. A typed-in carrier the
documents do not name leaves the NAIC untouched - blank or stale is recoverable,
a wrong pair is not.

**A side benefit worth having:** the NAIC now follows the carrier without being
asked, so the producer answers one card instead of two.

Verified in all four directions:

| Producer's answer | ACORD 126 prints |
|---|---|
| carrier=Redwood, NAIC=36161 (mismatched on purpose) | Redwood / **14312** + warning logged |
| carrier=Redwood, NAIC card untouched | Redwood / **14312** |
| carrier=Redwood, policy=RB-GL-880194-26, NAIC=14312 | Redwood / 14312 / RB-GL-880194-26 |
| carrier=Trinity Ridge, policy=TR-4471102-26 | Trinity Ridge / **36161** / TR-4471102-26 |

Auto stayed `Redwood Basin / 14312 / RB-CA-880771-26` in every one.

Tests: `test_a_confirmed_carrier_brings_its_own_naic`,
`test_the_naic_follows_the_carrier_without_being_asked`,
`test_an_unpairable_naic_is_refused_not_guessed`. **Proved they bite** -
pairing removed, 2 failed; restored, 64 passed.
Suite **5568 passed / 1 failed / 14 skipped**. Frontend build clean.

| # | Decision | Reasoning |
|---|---|---|
| D-AC | **The confirmed CARRIER decides its NAIC; a contradicting NAIC answer is overridden, not stamped.** | Carrier and NAIC are a matched pair (client, RC1). Two independent cards make an unpaired answer one click away, and the output is a legal document naming a company beside another company's identifier. |
| D-AD | **An unpairable NAIC is left alone, never guessed.** | A carrier the documents do not name has no NAIC to pair with. Blank or stale is recoverable; a wrong pair is not. |

### Two COSMETIC observations from run 1 - NOT fixed, recorded

1. **The Line column mixes dec-page and certificate wording** ("Automobile
   Liability" beside "Commercial Umbrella"). `_merge_line_record` keeps the
   LONGEST printing, which is arbitrary - the DEC PAGE's wording is the better
   answer on a package that has one. Display only: `line_printed` is never read
   by a stamper, and the canonical `line` is correct.
2. **The "Suggested" badge on run 2's carrier conflict is decided by string
   LENGTH.** Both values come from one document, so the doc-agreement tiebreak
   `_NAME_LIKE_FIELDS` exists for has nothing to work with and it falls through
   to `_value_completeness` (0.38 vs 0.31). On a genuine two-policies-on-one-line
   tie there is no evidence for either, and badging one edges toward Principle
   4's forbidden move. Mitigated already: confidence is MEDIUM and `preselect`
   is False, so no radio is pre-checked. Worth removing the badge when the
   conflict is line-scoped and every candidate has equal support.

## SYS-06 FORM RUN - TWO REAL DEFECTS FOUND ON THE GENERATED PDFs (2026-09-04)

Six forms on package A, two on package B. **Everything the acceptance criteria ask
for passed**, and two defects surfaced that no screen could show.

### PASSED, on the forms themselves

| Form | Printed |
|---|---|
| ACORD 126 (GL) | `EMC Property & Casualty Company` / **25186** / `BBC7263 - 26` - the headline, and the only line with the other carrier |
| ACORD 127 (Auto) | `Employers Mutual Casualty Company` / 21415 / `6E7-40-02---26` |
| ACORD 131 (Umbrella) | Employers Mutual / 21415 / `6J7-40-02---26` |
| ACORD 25 | INSURER A = EMC P&C / 25186, INSURER B = Employers Mutual / 21415, **C-F blank** |
| ACORD 125 Q4 | four distinct policy numbers, **no duplicate from the fold** |
| RUN B - 126 | `Redwood Basin` / **14312** - the producer confirmed the CARRIER only, and the NAIC followed. The pairing fix, live. |
| RUN B - 127 | **still** `Redwood Basin` / 14312 / `RB-CA-880771-26` - the answer did not leak onto another line |
| RUN B - 126 policy number | **blank** - correct: two GL policies remain and the producer did not confirm one |

### DEFECT 1 - the ACORD 25's ENTIRE policy-number column shipped blank

The certificate form could not state the certificate's own policy numbers. The
log named it:

```
current-policy: Policy_GeneralLiability_PolicyNumberIdentifier_A matched 2
  different values ['BBC7263', 'BBC7263 - 26'] - left blank
```

`_resolve_current_policy_line_cell` was doing the right thing for the wrong
reason: refusing to choose between two policy numbers. They are ONE contract -
the dec page's printing and the certificate's. **This was the last identity site
still comparing raw strings instead of asking the door.** Pre-existing (nothing
in SYS-06 caused it) and invisible on a single-document package, which is why it
had never been seen.

`_fold_policy_printings` now collapses printings of one contract before the
refusal, and keeps the FULLEST one - a certificate holder should see
`BBC7263 - 26`, not the stub. **Two genuinely different policies on one line are
still refused**, pinned by test.

### DEFECT 2 - ACORD 141 is a CRIME form and we stamped the Inland Marine policy on it

The generated 141 printed policy `6C7-40-02---26` (Inland Marine) and a header
carrier, while its body carried employee-theft limits. **One form, two policies.**

`_SECTION_FORM_LINE_PHRASES` had been written from the repo's idea of what each
form is, not from the form. Checked every entry against its template's OWN
printed title:

| Form | ACORD's printed title | Was mapped to | Now |
|---|---|---|---|
| ACORD 141 | **CRIME SECTION** | inland marine | **crime** |
| ACORD 133 | **WORKERS COMPENSATION INSURANCE PLAN / ASSIGNED RISK SECTION** | builders risk | **workers compensation** |
| ACORD 160 | **BUSINESS OWNERS SECTION** | cyber | unchanged - see below |

`builders risk` was not merely the wrong line: `canon_line` cannot place it at
all, so **ACORD 133's header has been unconditionally blank since the map was
written**. This is the first value it can carry.

`test_every_section_form_maps_to_the_line_its_template_names` reads the template
titles and fails the build if an entry drifts from its form again. Forms whose
ACORD title names no line at all (137, 138, 28, 186) are a DECLARED exception
list, each with its reason - never inferred.

### OPEN FOR THE OWNER / BRENT - ACORD 160 is the wrong FORM, not the wrong mapping

The template shipped as ACORD 160 is the **BUSINESS OWNERS SECTION**, while
`CLAUDE.md` and `form_service` treat 160 as the Cyber Liability form. So today a
BOP application takes the CYBER policy's number, carrier and NAIC.

**Deliberately not "fixed" here.** Repointing the identity at a family
`lob_canon` has no entry for (`business owners`) would only blank the header and
would not answer the real question: which PDF this product intends to ship for
cyber. A product decision, recorded rather than improvised (Principle 7).

**Same family, also open:** `forms_database/ACORD_141.json` calls 141 a
"Property Schedule" and recommends it on `has_property_coverage` /
`has_multiple_locations`. A property package with no crime coverage therefore
gets a Crime application. That is the RECOMMENDER, not the identity map, and
changing it changes which forms are suggested for every package - out of scope
of this change, flagged.

### Two existing tests failed, and the TESTS were wrong

`test_no_section_form_ever_gets_another_lines_number` and
`test_repaired_lines_flow_through_to_the_forms` both asserted ACORD 141 receives
the INLAND MARINE number. That expectation encoded the mapping error: on a Crime
form the Inland Marine number IS "another line's number", which is the exact
thing the first test exists to forbid. 141 now falls into that test's own
"blank, never borrowed" branch (Orbin carries no Crime line), and its positive
case lives in the new kit.

### Verification

* Tests: `tests/test_sys06_line_specific_identity_20260904.py` now **70**.
  **Proved both bite** - fold removed, 1 failed; 141 mapped back, 2 failed.
* Suite **5574 passed / 1 failed / 14 skipped** (the documented `httpx` one).
  Frontend build clean.

| # | Decision | Reasoning |
|---|---|---|
| D-AE | **The certificate cell folds printings of one contract before refusing.** | Refusing to choose between two policy numbers is right; treating two printings of ONE number as two policies is not. It was the last identity site not asking the shared door, and the cost was a certificate that could not state its own policy numbers. |
| D-AF | **A form's identity line comes from the form's OWN printed title.** | Every entry in the map had been written from the repo's belief about a form. Two contradicted the form; one shipped live. The template is the authority, and a test now enforces it. |
| D-AG | **ACORD 160's mismatch is recorded, not patched.** | The template is a Business Owners section while the repo uses 160 as Cyber. That is a question about which FORM to ship, not about which line's identity to stamp. Improvising an answer would hide it (Principle 7). |

### RE-RUN CONFIRMS BOTH FORM FIXES LIVE (package A, 2026-09-04)

| Box | Before | After |
|---|---|---|
| ACORD 25 GL policy number | **blank** | `BBC7263 - 26` |
| ACORD 25 Auto policy number | **blank** | `6E7-40-02---26` |
| ACORD 25 Excess policy number | **blank** | `6J7-40-02---26` |
| ACORD 141 policy number | `6C7-40-02---26` (Inland Marine) | **`CR-4471`** (Crime) |

ACORD 25's insurer roster unchanged - A = EMC P&C / 25186, B = Employers Mutual /
21415, C-F blank. ACORD 141's title reads CRIME SECTION and its body carries the
employee-theft limits, so header and body finally describe the SAME contract.
**SYS-06 is closed on the forms as well as the screen.**

### THREE OBSERVATIONS FROM THE SAME RUN - none of them SYS-06

**1. `gl_limits` raised a false conflict, and it is Principle 2.** The dec page
states `$1,000,000 / $2,000,000`; the certificate states `$1,000,000 Each
Occurrence`. The picker says *"the documents state different amounts"*. They do
not - they agree on every amount BOTH state; one simply also states the
aggregate. Principle 2 names this exactly: *"differing levels of specificity
should be normalized before deciding that two values conflict."*

Pre-existing and DELIBERATE: `fact_equivalence.same_fact`'s money branch merges
two composites by subset but requires BOTH sides to be composites, and its own
comment explains why - an UNLABELLED `$1,000,000` against `$1,000,000 /
$2,000,000` really is ambiguous (is it the occurrence or the aggregate?), and
`test_a_composite_amount_is_never_flattened` guards that.

The distinction that makes a safe fix is the LABEL: the certificate's value
names which limit it is. A labelled single limit whose amount matches the
composite's same-labelled component is not a disagreement; an unlabelled one
still is. That is H1-F's structural-second-condition pattern again. **Not built -
it needs its own adversarial cases, and it is not SYS-06.**

Note it is INTERMITTENT - the first two runs of the same package did not raise
it, because extraction phrased `gl_limits` differently. That is worth knowing
before anyone tries to reproduce it.

**2. Gap fill is writing LABELS into value boxes.** On ACORD 25: `Any Auto`,
`Commercial Auto`, `Self-Insured Retention`. On ACORD 141: `Commercial Crime
Coverage Part`, `Employee Theft`, `Erisa` in NAME OF PLAN. These are the field's
own caption echoed back as its value - the class Guard 8 (`_is_tooltip_echo`)
exists for, evidently not catching this shape. Cosmetic on a draft, wrong on a
signed form.

**3. The UI still labels ACORD 141 "Property Schedule"** - now visibly over a
page titled CRIME SECTION. `forms_database/ACORD_141.json` carries
`form_name: "ACORD 141 - Property Schedule"`, a property description, and
`matching_flags: [has_property_coverage, has_multiple_locations]`. The NAME is
display-only and safe to correct; the FLAGS decide which packages are offered
the form, so a property package with no crime coverage is currently offered a
Crime application. Same open item as D-AG - owner call.

## SYS-06 ADVERSARIAL STRESS TEST - TWO REAL DEFECTS THE CLEAN KIT HID (2026-09-04)

Asked before presenting to the client: does this hold on MESSY data, not just on
my own tidy PDFs? Six noise shapes were replayed against the real pipeline - the
ones the client's actual package carried. **Two failed.**

| Noise | Before | After |
|---|---|---|
| ISO form number as a `coverage_lines` row | "scoped", but **every chip printed a POLICY-NUMBER TOKEN** (`bbc7263 / bbc726326`) instead of a coverage line, and the form number was listed as a fifth policy | scoped, chips are lines, form number shown "not matched to a coverage line" |
| a package-level `policy_number` scalar no line states | **four real policies folded into ONE candidate**, producer asked to choose between it and the scalar | five values, each on its own line, scalar shown unplaced, no question |
| AAIS (a bureau) as a carrier on a line | conflict | conflict (unchanged - two carriers on one line IS the client's own review trigger) |
| unmappable coverage line | scoped | scoped |
| OCR-garbled carrier printing | scoped | scoped |
| all at once | conflict | conflict, restricted to the values actually in dispute |

### The root cause was MY all-or-nothing gate

`_scope_from_store` returned "no opinion" the moment ONE value could not be
placed, handing the whole field to `_scope_values` - the LEGACY path that
attributes a value by its own CHARACTERS and labels each group with a CONTRACT
TOKEN. That is why the chips printed `bbc7263`.

Worse was the second row. With the field unscoped, the equivalence pass ran with
package context, `different_owners` partnered the four line numbers as "not a
disagreement", and they merged into ONE candidate. The producer was then offered
`PKG-99999` against `6C7-40-02---26` - and confirming either writes the PACKAGE
SCALAR, which `Policy_GeneralLiability_PolicyNumberIdentifier` maps to. **The
client's original complaint, reproduced by the fix meant to end it.**

### Partial scoping now ships

A value the store cannot place is not evidence against the values it can:

* no group placed -> legacy path, exactly as before (pre-SYS-06 sessions);
* some placed -> each keeps its LINE scope, and the unplaceable ones render
  "not matched to a coverage line";
* **two or more** unplaceable values -> still a question, but about THEM - the
  correctly placed lines are never offered as answers to it;
* two policies on one line -> unchanged, still a conflict naming the line.

Tests: `test_one_unplaceable_value_does_not_unscope_the_whole_field`,
`test_a_package_scalar_no_line_states_never_forces_a_choice`,
`test_two_unplaceable_values_are_still_a_question`. **Proved they bite** -
all-or-nothing restored, 3 failed. Kit now **73**. Suite **5577 passed / 1
failed / 14 skipped**. Frontend build clean.

| # | Decision | Reasoning |
|---|---|---|
| D-AH | **A value the store cannot place never unscopes the values it can.** | The all-or-nothing gate was a bigger risk than the case it was protecting: it handed the field to a character-keyed path that printed contract tokens as coverage lines and let the equivalence pass fold four real policies into one. Partial knowledge is still knowledge. |
| D-AI | **One unplaceable value is not a question; two are.** | Nothing competes with a single unattributable value, so asking "which applies" is the forced choice the client objected to. Two competing for the same unidentifiable slot is a real question - about them, not about the lines already placed. |

### HONEST RESIDUAL GAPS - state these before anyone asks

1. **Source is on screen, not in the E&O export.** `audit_service` reads
   `_scoped` (line + policy number per fact) but not `_line_records`, so the
   audit record traces the relationship without naming WHICH DOCUMENT stated
   each row. ~5 lines to close; not done.
2. **`gl_limits` can still raise a false conflict on the same panel** (see the
   observations above). It is a Principle 2 defect, not SYS-06 - but it renders
   two rows below the SYS-06 result and a client will read it as the same
   family. **Highest presentation risk of anything open.**
3. **A bureau name in a carrier column still raises a carrier conflict.**
   Defensible - two carriers on one line is the client's own review trigger -
   but it is what their screenshot complained about, and we have not made it go
   away, only made the message name the line and restrict the choices.
4. **Package B's POLICY NUMBER confirm is verified offline and by test, not
   live.** The carrier half is live-verified.

## THE `gl_limits` FALSE CONFLICT - FIXED 2026-09-04

Live run A put this two rows below the SYS-06 result:

```
Gl Limits   Values differ - confirm   "the documents state different amounts"
              ( ) $1,000,000 / $2,000,000        from A1 (dec page)
              ( ) $1,000,000 Each Occurrence     from A2 (certificate)
```

**They do not state different amounts.** They agree on every amount BOTH state;
one simply also states the aggregate. That is Principle 2 verbatim - *"differing
levels of specificity should be normalized before deciding that two values
conflict."*

### The comparator was NOT the thing to change

`fact_equivalence.same_fact`'s money branch merges two composites by subset but
requires BOTH sides to be composites, and its reason is sound: an UNLABELLED
`$1,000,000` against `$1,000,000 / $2,000,000` really is ambiguous - is it the
occurrence or the aggregate? - and `test_a_composite_amount_is_never_flattened`
guards it.

Loosening it was considered and REJECTED. Every variant either kept the live
case broken (match by label - the dec side came back unlabelled) or introduced a
false merge that could hide a real limit disagreement (`$1,000,000 General
Aggregate` against `$1,000,000 / $2,000,000` where the aggregate is really $2M).
**Guessing which amount is which is the forbidden move.**

### The QUESTION was the thing to change

`gl_limits` is a RENDERING of four scalars - `gl_each_occurrence`,
`gl_aggregate`, `gl_products_aggregate`, `gl_personal_advertising_injury`
(`_CURRENCY_COMPOSITE_PARENT`) - and this picker reconciles every one of them on
its own. So the composite is a WITNESS, not a rival answer, and asking a
producer to choose between two printings of it is not a fact question. Worse,
confirming one REPLACES the other: a certificate's single row would have
overwritten the dec page's six limits.

A composite is no longer asked **when the package actually carries a child this
picker can assess**. Positive evidence only - nothing is ever silenced unless a
better question is already on screen in its place.

| Case | Before | After |
|---|---|---|
| composite differs, children AGREE (**the live case**) | 1 conflict on `gl_limits` | **0 conflicts** |
| children genuinely disagree ($1M vs $500k occurrence) | conflict on the block | conflict on **`gl_each_occurrence`** - the field that actually stamps |
| the block is the ONLY evidence, no child facts | conflict | **conflict** - unchanged |

The relationship is read from `extraction_service._CURRENCY_COMPOSITE_CHILDREN`,
the table the merge already uses, so "which facts is this a rendering of?" keeps
ONE owner - pinned by `test_the_composite_relationship_has_one_owner`.

Tests: `test_a_limits_block_rendered_two_ways_is_not_a_conflict`,
`test_the_children_are_still_asked_when_they_really_disagree`,
`test_a_composite_with_no_children_is_still_asked`. **Proved it bites** -
suppression disabled, 1 failed. Kit now **77**.
Suite **5581 passed / 1 failed / 14 skipped**. Frontend build clean.

| # | Decision | Reasoning |
|---|---|---|
| D-AJ | **The comparator was left alone; the QUESTION was removed.** | Every loosening of the money rule either failed to fix the live case or could hide a real limit disagreement by guessing which amount is which. The composite is not an independent fact - its parts are, and they are already asked. |
| D-AK | **A composite is suppressed only when a child is actually present.** | On a package that states the block and none of its parts, the block is the only evidence there is. Suppressing it there would hide a disagreement behind a better question that does not exist. |

**Note the improvement is not only cosmetic:** in the genuine-disagreement case
the producer is now asked about `gl_each_occurrence` - a stampable canonical
fact - instead of a display string. Confirming it fixes the forms; confirming
the block never could.

## FINAL PRE-CLIENT HARDENING (2026-09-04)

The `gl_limits` fix was confirmed live: **Data Consistency reads "All confirmed",
warnings 5 -> 4, the "Financial figure conflicts" cluster is gone, and ACORD 126
still prints all six GL limits** ($2,000,000 general aggregate, $2,000,000
products, $1,000,000 P&AI, $1,000,000 each occurrence, $100,000 rented premises,
$5,000 medical, total $6,720). Nothing was lost by removing the question.

Two further checks were then run specifically against "will this hold on the
client's REAL data".

### RENEWAL RISK - FOUND AND FIXED

A renewal declarations page prints the EXPIRING number beside the in-force one.
`BBC7263 - 25` and `BBC7263 - 26` are genuinely different contracts, so nothing
folds them - and the line records landed them as TWO records on the General
Liability line, so **an ordinary renewal was reported as "two policies on the
same coverage line"**.

This repo already carries that lesson: `prior_term_policy_numbers` exists
because the same leak was measured on `dec_page_entries` (run 3, 1 Sep - *"the
extra entries were the EXPIRING programme's policy numbers, and nothing
downstream could tell them from the in-force ones"*). **The line records were
the one identity structure not asking it.**

`_line_record_rows` now takes the prior-term set. Positive evidence only - no
prior grid, no filtering, behaviour unchanged - and if EVERY row is prior-term
it falls back to the unfiltered rows rather than emptying the store.

| Shape | Before | After |
|---|---|---|
| renewal with a prior grid | conflict on GL | **scoped**, GL = `BBC7263 - 26` |
| no prior grid (no proof) | conflict | **conflict** - unchanged |
| only prior rows | records | records kept |

Tests: `test_last_years_number_is_not_a_second_policy_on_the_line`,
`test_without_a_prior_grid_the_question_is_still_asked`,
`test_a_package_of_only_prior_rows_keeps_them`. Kit now **80**.
Suite **5584 passed / 1 failed / 14 skipped**.

| # | Decision | Reasoning |
|---|---|---|
| D-AL | **Prior-term numbers are excluded from the line records.** | Last year's contract is not a second policy on the line. The door already existed for the dec index; this was the structure that had not been wired to it. Fails open with no prior grid, so it can only ever remove a false conflict. |

### A FALSE WARNING THE FORM ITSELF CONTRADICTS - NOT FIXED, owner call

The screen says *"GL coverage detected but no class codes found"* while the
ACORD 126 it generates prints **two** class codes (99471 Refrigerated
warehousing, 91580 Contractors - subcontracted work).

Cause: two different facts. The warning reads `gl_class_codes_by_location`
(`sqs_service.py:972`); the ACORD 126 hazard rows are stamped from
`gl_class_code_schedule`. Extraction populated the second and not the first, so
the warning is a false negative **contradicted by our own output**, and it is
score-bearing (it sits in the 85-cap warnings block).

Same defect class as the auto-symbol phantom keys (2026-08-07): a check reading
a fact the package does not write. **Not fixed here** - the correction makes
scores go UP on every GL package that has a schedule, which is a D6 conversation,
not a drive-by before a client demo.

### OTHER THINGS A CLIENT WILL SEE ON THESE SCREENS - all pre-existing, none SYS-06

* **Gap fill writes LABELS into value boxes.** ACORD 126 prints
  `Damage To Rented Premis...` inside the DEDUCTIBLES block; ACORD 25 prints
  `Any Auto`, `Commercial Auto`, `Self-Insured Retention`; ACORD 141 prints
  `Employee Theft`, `Commercial Crime Coverage Part`, `Erisa`.
* **ACORD 126 invents an EMPLOYEE BENEFITS limit of $1,000,000** on a package
  whose documents never mention Employee Benefits Liability - Principle 3.
* **The ACORD 126 Schedule of Hazards repeats row 1** as a third, gap-filled row
  with no LOC #/HAZ # - the C46 phantom-row class, one form over.
* **ACORD 160 is a Business Owners template used as the Cyber form** (D-AG), and
  **`forms_database` still calls ACORD 141 a "Property Schedule"**.

### WHAT THE RESULT DEPENDS ON, stated plainly

Every guarantee above is built on `coverage_lines` carrying one row per line
with its own carrier / NAIC / policy number. **If extraction returns no per-line
rows, none of this fires** and the picker falls back to pre-SYS-06 behaviour.
Measured: no `coverage_lines` -> no line records -> legacy path. That is the
single largest real-data dependency, and it is a property of extraction, not of
this change.

### PACKAGE A - FINAL REGRESSION RUN CLEAN (2026-09-04)

Re-run after the renewal fix. Predicted a no-op on this package (no
`prior_coverage_by_line`, so `prior_term_policy_numbers` returns empty) and it
was: **identical to the previous run in every respect.**

* Data Consistency: **All confirmed**, 0 to fix
* Warnings: **4** - auto symbols, driver schedule, GL class codes, UM/UIM
  (all pre-existing, none SYS-06)
* Policies table: **5 rows**, both filenames in Source on every row
* Carrier **2/2**, Policy Number **5/5**, Carrier NAIC **2/2** - all read-only
* General Liability on `EMC Property & Casualty Company` / **25186** /
  `BBC7263 - 26`; every other line on `Employers Mutual Casualty Company` /
  **21415**

**SYS-06 IS CLOSED.** All four acceptance criteria verified live, on the screen
and on the forms, across three packages (the client's shape, the two-policy
control, and a renewal), plus six adversarial noise shapes.

### Status board entry

| ID | Priority | Area | Status |
|---|---|---|---|
| SYS-06 | P0 systemic | Carrier / policy mapping | **SHIPPED + LIVE-VERIFIED 2026-09-04** |

### What SYS-06 cost, in defects found

Nine, of which **four were introduced by the fix itself** and caught before the
client saw them:

| # | Defect | Found by |
|---|---|---|
| 1 | one policy printed two ways became "two policies on one line" | the client's own table, replayed |
| 2 | a certificate row treated as a rival policy | reproduction |
| 3 | `policy_number` / `carrier_naic` invisible when scoped | code read |
| 4 | *(mine)* legacy store folded two real carriers into one | an existing positive control |
| 5 | *(mine)* a store predating a fact half-scoped the package | the full suite |
| 6 | *(mine)* a one-line question offered another line's value | live run B |
| 7 | *(mine)* a scoped confirm could print an unpaired carrier/NAIC | review of run B before it shipped |
| 8 | ACORD 25's whole policy-number column blank | live run A forms |
| 9 | ACORD 141 stamped the Inland Marine policy on a CRIME form | live run A forms |

Plus two found by stress test (chips printing contract tokens; four policies
folded into one candidate), one by principle (`gl_limits`), and one by asking
"what does a renewal look like".

**The lesson worth keeping: every one of the four self-inflicted defects was
caught by a positive control, a full-suite run, or a live screenshot - none by
reading the diff.**

---

## SYS-06 - CONSOLIDATED FILES TOUCHED (all sessions, final)

| File | Change |
|---|---|
| `backend/services/fact_comparison.py` | `same_policy_contract`, `policy_contract_groups` (+ `re` import, `__all__`) |
| `backend/services/extraction_service.py` | `LINE_RECORDS_KEY`, `_contract_key`, `_line_record_rows` (form-number + prior-term filters), `_record_sources`, `_build_line_records`, `_merge_line_record`; `_build_scoped_fact_store` derives from them and takes `docs`; `_FORM_NUMBER_RE` / `_looks_like_a_form_number` split out of `_looks_like_a_policy_number` |
| `backend/services/underwriting_consistency.py` | curated `policy_number` + `carrier_naic`; `_scope_of_group`, `_merge_by_line_record`, `_store_entries`, `_line_records`, `_line_records_for`, `_printings_by_line`, `_drop_answered_line_candidates`, `_restrict_to_conflicted_lines`, `_composite_children`, `_composite_is_reconciled_by_its_children`; `_scope_from_store` is record-aware, returns collided lines and scopes PARTIALLY; `scoped_confirmation_key` / `parse_confirmation_key` / `_apply_scoped_confirmations` / `_pair_naic_with_its_carrier`; payload gains `conflict_scope`, `confirmed_scopes`, `line_records` |
| `backend/services/pdf_service.py` | `_same_policy_contract` delegates to the door; `_fold_policy_printings` + the fold in `_resolve_current_policy_line_cell`; `_SECTION_FORM_LINE_PHRASES` corrected for ACORD 141 (crime) and 133 (workers comp), 160 documented as a known FORM mismatch |
| `backend/services/extraction_pipeline.py` | `confirm_underwriting_value(scope=...)`; linked-field spray gated on scope; `_confirmed_keys` uses bare fact keys |
| `backend/models/schemas.py` | `UnderwritingConfirmRequest.scope` |
| `backend/routes/form_routes.py` | passes `scope` through |
| `frontend/src/components/form/AcordModal.jsx` | "Policies in this submission" table; per-line `Confirm for <line>`; `confirmed_scopes` chip; "not matched to a coverage line" chip; `scope` sent on confirm |
| `backend/scripts/make_sys06_test_pdfs.py` | new - the 3-PDF live kit + README, self-verifying |
| `backend/tests/test_sys06_line_specific_identity_20260904.py` | new, 80 tests |
| `backend/tests/test_underwriting_consistency.py` | exempt-set fixture extended for the two newly curated fields |
| `backend/tests/test_relationship_preservation_20260815.py` | ACORD 141 expectation corrected (it encoded the mapping error) |
| `backend/tests/test_relationship_root_fixes_20260815.py` | same |

**Next client item: SYS-07** - *"Normalize Yes, True, and X/checkmark as the same
affirmative value"* (P0 systemic). Nothing in SYS-06 touches it.

---

## SYS-07 - Normalize Yes / True / X / checkmark as one affirmative - THE DIAGNOSIS

*Diagnosis only, 2026-09-04. No code written yet. Owner approval pending on the
approach below.*

### What the client asked for

> "The same affirmative answer can arrive as 'Yes,' boolean true, X, or a checked box
> depending on the source document and extraction path. These representation
> differences should not create false conflicts."
>
> **Expected:** "Normalize common affirmative representations to one canonical true
> value and common negative representations to one canonical false value **before
> comparison**. Route this through the **same pre-comparison canonicalization layer**
> used for other equivalent values so warnings are created only after normalization
> and formatting or representation differences alone cannot produce a conflict."

Screenshot: the Data Consistency panel prints **Auto Hired Nonowned - VALUES DIFFER -
CONFIRM**, `Yes` from *2526 Package Policy (Complete Copy).pdf* against `X` from
*CRS COI FiO - Orbin CERT ONLY.pdf*, CONFIDENCE: MEDIUM, under the standing subtitle
*"materially different values remain after normalization and scope matching"*.
They are the same answer.

### The headline: the Yes/No comparator ALREADY EXISTS and works. It is never reached.

`fact_equivalence` has had a Yes/No branch since C1 (`same_fact`, `kind == KIND_YESNO`)
and its `_YES` set already knows `y / yes / true / t / 1 / checked / x`. Proved by
running the real door:

```
hired_auto_indicator     ['Yes','X']    kind=yesno   -> equivalent   (correct)
new_venture_indicator    ['Y','true']   kind=yesno   -> equivalent   (correct)
auto_hired_nonowned      ['Yes','X']    kind=text    -> CONFLICT     (the screenshot)
auto_hired_nonowned      ['Yes','Y']    kind=text    -> CONFLICT
auto_hired_nonowned      ['Yes',True]   kind=text    -> CONFLICT
cyber_prior_incidents    ['No','N']     kind=text    -> CONFLICT
agreed_value_endorsement ['Yes','X']    kind=MONEY   -> CONFLICT
inside_city_limits       [True,'Yes']   kind=MONEY   -> CONFLICT
```

### Root cause - the TYPE is guessed from the key's NAME, not read from its declaration

`fact_equivalence.value_kind(fact_key)` decides which comparator runs. Its only route to
`KIND_YESNO` is step 3, key-shape tokens:

```python
if "indicator" in tk or "required" in tk:
    return KIND_YESNO
```

So a Yes/No fact is compared as Yes/No only if somebody happened to put the word
"indicator" in its key. `auto_hired_nonowned` did not, so it falls to `KIND_TEXT` and
`"Yes" != "X"`. Two facts fall further: `agreed_value_endorsement` and
`inside_city_limits` hit the MONEY tokens (`value`, `limits`) first and are compared as
dollar amounts.

**The declaration was there the whole time and nothing reads it.** `FACT_REGISTRY`
already carries `"format_hint": "Yes or No"` and validators whose vocabulary is
literally `{"yes","no","true","false"}`; the extraction schema already declares
`agreed_value_endorsement`, `inside_city_limits`, `cyber_controls_mfa` and
`additional_insured_required` as `boolean`. Measured: of the **8** facts the registry
itself declares Yes/No, only **3** are classified `yesno` - 3 are `text` and 2 are
`money`. Same shape as H1-C's phantom keys and C1's five comparison sites: one rule, and
the copy that runs is not the copy that knows.

### Blast radius - it is not just the picker card

1. **The card is also a SOFT STOP.** An auto-discovered reconcilable field with
   `review_required` becomes a warning in `extraction_pipeline` (~line 1075), which caps
   the package SQS at **85**. A spelling difference is currently costing score.
2. **The merge splits its own vote.** `extraction_service._variant_group_key` folds to
   alphanumerics, so `yes` / `x` / `true` / `y` are FOUR rival candidates for one fact.
   Whichever spelling appears most often wins and becomes the stored canonical fact - so
   `X` can be the value that reaches the forms. That breaks core principle 1 (one
   canonical fact) independently of the picker.
3. **Real checkbox printings are not in the vocabulary at all.** `_yesno` returns None
   for the checkmark, the ballot-box-with-check, `[X]` and `(X)`. Worse,
   `normalize_general(checkmark)` returns `''`, so a checkmark is treated as ABSENT and
   silently dropped rather than counted as a Yes.
4. **`_prefer` would put the WRONG printing on screen.** For `KIND_YESNO` it keeps the
   SHORTEST string, so simply retyping these facts as `yesno` makes `X` beat `Yes` as the
   displayed / suggested / stamped value. The fix must also elect the canonical printing,
   or it trades a false conflict for a worse display.
5. **THE ONE THAT PUTS A WRONG VALUE ON A SIGNED FORM.**
   `pdf_service._resolve_bool_indicator` - the function that decides whether a `/Btn`
   checkbox is ticked - reads `{"yes","y","true","1","on"}` and returns `"No"` for
   everything else. **`_resolve_bool_indicator("X")` returns `"No"`.** An affirmative X
   from a certificate ticks the NEGATIVE box. Verified live. It also turns blank into
   "No", which is core principle 3 (missing does not mean no) inverted.

### The real class - EIGHT copies of "what counts as affirmative", all different

| Where | Vocabulary | Knows "X"? |
|---|---|---|
| `fact_equivalence._YES` | y yes true t 1 checked x | yes |
| `pdf_service._YN_ACCEPTED_TOKENS` | y n yes no true false on off x 1 0 | accepts, never converts |
| `pdf_service._resolve_bool_indicator` | yes y true 1 on | **NO - returns "No"** |
| `pdf_service._AFFIRMATIVE_VALUES` | yes y true 1 on | no |
| `pdf_service` checkbox writer (~7323) | yes true 1 on x | yes |
| `answer_semantics._AFFIRM_TOKENS` | yes y yeah yep true correct confirmed ... | no |
| `coverage_evidence._TRUE_WORDS` | y yes true 1 on included include ... | no |
| `cross_form_validator` (~1045) | y yes true 1 | no |

None of them knows the checkmark glyphs. This is why one submission can read one X as a
Yes, another X as a No, and a third X as a conflict.

### Proposed approach - one door, in the layer the client named

1. **Read the declared type before guessing the name.** `value_kind` gains a step that
   consults `FACT_REGISTRY` (`format_hint` "Yes or No" / the validator's own vocabulary)
   and the extraction schema's `boolean` declarations, ahead of the money / count token
   guess. Derived from declarations that already exist - no hand-list, and a future
   Yes/No fact is classified correctly the day it is added.
2. **Widen the ONE vocabulary** (`fact_equivalence._YES` / `_NO`) to the printings real
   documents use - the checkmark and ballot-box glyphs, `[X]`, `(X)`, `checked` /
   `unchecked`, `on` / `off`, `included` / `excluded` - and expose a single
   `canonical_yes_no(value) -> "Yes" | "No" | None` helper as the module's public door.
3. **A value-shaped safety net with a STRUCTURAL second condition** (the H1-F lesson).
   For a fact with no declared type, fold only when every value parses as a Yes/No token
   AND at least one of them is an unambiguous WORD (`yes/no/true/false/checked`). That
   catches "Yes vs X" on an undeclared key and refuses to read a bare `1` against `0` on
   a numeric text field as Y vs N.
4. **Elect the canonical printing.** `_prefer` for `KIND_YESNO` must return `Yes` / `No`,
   not the shortest string, so the picker, the E&O record and the stamped value all show
   one canonical true value - exactly what the acceptance criteria asks for.
5. **Route the merge through the same helper.** `_variant_group_key` folds the whole
   affirmative family to one group key so the vote is not split and the stored fact is
   canonical (principle 1).
6. **Collapse the scattered copies onto the helper, starting with
   `_resolve_bool_indicator`** - it is the one that puts a wrong tick on a form. Keep
   "unreadable" meaning BLANK, never "No" (principle 3). A grep test should fail the
   build if a new private yes/no token set appears.

### Risks to state before writing code

- **Scores move UP** - a false warning disappearing releases an 85 cap. D6 applies:
  Brent sees the numbers before this ships.
- `agreed_value_endorsement` and `inside_city_limits` change comparator from money to
  yesno. Needs an explicit regression pin.
- Step 4 changes what the picker DISPLAYS for every existing `KIND_YESNO` field
  (`hired_auto_indicator`, `non_owned_auto_indicator`, `new_venture_indicator`) - today
  it shows the shortest printing.
- A checkmark currently normalizes to empty and is dropped; after the fix it becomes a
  real affirmative VALUE, so a fact that was blank can start carrying Yes. That is the
  correct behaviour and it can move a fill rate.

---

## SYS-07 - SHIPPED 2026-09-04

Diagnosis is the section above. This is what was built, what it deliberately does
NOT do, and the proof.

### The acceptance criteria, and where each one is satisfied

| Client asked for | Where it lives now |
|---|---|
| "normalize common affirmative representations to one canonical true value" | `normalization.canonical_yes_no` -> "Yes" / "No" / None |
| "...and common negative representations to one canonical false value" | same function; `yes_no_token` returns "Y"/"N" for callers that need ACORD's letter |
| "before comparison" | `normalization.normalize_value` (step 1b) - the dispatcher every comparison already went through |
| "route this through the SAME pre-comparison canonicalization layer used for other equivalent values" | `normalization.py`, beside the date / address / carrier / entity normalizers |
| "warnings are created only after normalization" | `fact_equivalence.value_kind` now reaches `KIND_YESNO`, so the picker and `check_doc_consistency` (one door, C1/D3) both stop asking |
| "representation differences alone cannot produce a conflict" | `tests/test_sys07_boolean_normalization_20260904.py` (202) |

### Root cause, restated as the thing that was fixed

**The type was guessed from the key's NAME. The declaration was never read.**
`value_kind`'s only route to `KIND_YESNO` was `if "indicator" in tokens or
"required" in tokens`, and it sat BELOW the money and count tokens. Now a Yes/No
fact is identified from declarations that already existed:

1. `FACT_REGISTRY`'s own `format_hint` ("Yes or No") and, failing that, its
   `validate` lambda probed BEHAVIOURALLY - accepts "Yes" and "No", rejects an
   amount, a company name, a date, a FEIN, an address and a NAICS code. No
   source parsing, so it cannot drift from what the validator does.
2. `extraction_service.BOOLEAN_FACT_KEYS` - every `"...": boolean` in LLM call
   1's schema, harvested by regex the same way `TRISTATE_BOOLEAN_FACTS` and
   `ASSERTION_FLAG_NAMES` already are (52 keys).
3. Key shape (`*_indicator`, `*_required`, `*_confirmed`, `is_*`, `has_*`) -
   the weakest source, and the only one that is a guess.

**`YES_NO_FIELDS` is deliberately EMPTY.** It is the override hatch. Everything
real is derived, so a Yes/No fact added tomorrow is classified the day it is
added and there is no list to remember. `test_the_declaration_sources_are_
derived_not_hand_listed` fails the build if someone starts filling it in.

### Measured blast radius - 53 fact keys changed comparator, every one a boolean

The sweep ran the OLD resolution and the NEW one over all 318 fact keys
(registry + extraction schema + `RECONCILABLE_FIELDS`). 53 moved, and **not one
of them holds a name, date, address, amount or code**. The worst of what the
name-guess had been doing:

| Fact | Was compared as | Because |
|---|---|---|
| `agreed_value_endorsement` | **money** | the token "value" |
| `inside_city_limits` | **money** | the token "limits" |
| `auto_split_limits`, `property_has_peril_deductibles` | **money** | same |
| `gl_is_claims_made` | **count** | the token "claims" |
| `wc_multi_state`, `wc_has_monopolistic_state` | **state** | the token "state" |
| `has_motor_carrier_coverage` | **name** | "carrier" - compared with `strict_entity_key` |
| `has_garage_operations` | **narrative** | "operations" - so ALWAYS `INCOMPARABLE` |
| `auto_hired_nonowned`, `is_renewal`, `sprinkler_system`, `cyber_prior_incidents` | text | the reported class |

`test_no_other_fact_changed_its_comparator` and `test_no_identity_field_was_
captured_by_the_yes_no_rule` pin the other direction.

### The shape guess is blocked by a key that names another type

`has_` / `is_` is a guess, and a guess must not beat a key that says outright it
holds an amount. `_YES_NO_SHAPE_BLOCKERS` (amount, limit, value, premium,
payroll, deductible, count, date, code, rate, name, address, ...) gates
`yes_no_field_shape` ONLY - a DECLARED Yes/No is unaffected. So `has_umbrella`
is a boolean and `has_umbrella_limit` stays money; `is_renewal` is a boolean and
`is_effective_date` stays a date. Pinned by test.

### What the reader refuses to decide - core principles 3 and 7

`yes_no_token` returns None ("cannot say"), never "No", for:

* **"N/A" / "not applicable" / "none" / "null" / "unknown" / "TBD"** - a
  non-answer is not a negative. `answer_semantics` (C2-G) and `_fv` already own
  those and reading one as a No would turn an absence into an assertion.
* **a bare ballot-X glyph with no box** (U+2717 / U+2718) - it means "checked"
  in a column and "wrong" standing alone. The ballot BOX glyphs are read
  (U+2611 / U+2612 checked, U+2610 empty) because the box disambiguates.
* **an empty bracket pair** "[ ]" - more often OCR noise than an asserted No.
* **anything that is not the WHOLE value** - "Yes - see the attached schedule"
  keeps its words and falls through to ordinary text comparison.

### The value-shaped fallback, and its structural second condition

The declaration route covers every key we can name. For a key nothing declares,
`same_fact` folds Yes/No only when **both sides read as Yes/No AND at least one
is an unambiguous English word** (yes/no/true/false/checked/unchecked). That is
H1-F's standing lesson applied: a test that is necessary but not sufficient
needs a structural second condition. Without it a bare "1" against a bare "0" on
an untyped numeric field would become Yes vs No. Pinned five ways.

### One canonical value, not just one comparison

Fixing only the comparison would have made the display WORSE. `_prefer` keeps
the shortest printing for a Yes/No - right for an amount - so the moment these
facts started comparing as Yes/No the picker would have put the certificate's
bare **"X"** in front of the producer with a "Suggested" badge on it, and
stamped that X. So:

* `_prefer` for `KIND_YESNO` now ranks the printing: `Yes`/`No` > `Y`/`N` >
  `true`/`false` > a mark. `equivalent_index` uses `_prefer` to pick the keeper,
  so the picker shows "Yes" and keeps BOTH documents' attribution.
* `_variant_group_key(sval, fact_key)` folds the whole affirmative family to one
  merge group. It used to leave `yes`/`x`/`true`/`y` as FOUR rivals splitting
  one answer's own vote, so the stored fact - and the value stamped on every
  form - was whichever spelling the document printed most often.
  `_prefer_variant` then elects the canonical printing. `fact_key` is OPTIONAL
  on both, so every existing caller and its pinned behaviour is untouched.
* `validate_confirmation` returns the canonical printing: a producer confirming
  the certificate's X is confirming the ANSWER.

### The defect nobody reported, which was the worst one

`pdf_service._resolve_bool_indicator` - the function that decides whether a
`/Btn` checkbox is ticked - read `{"yes","y","true","1","on"}` and returned
`"No"` for everything else. **`_resolve_bool_indicator("X")` returned "No".** An
affirmative X from a certificate would have ticked the NEGATIVE box on a signed
ACORD form. Not reachable today (its only caller passes a real `bool`), which is
exactly why it went unnoticed - a latent wrong-value defect is still a defect.

And the actual PDF checkbox writer accepted `("yes","true","1","on","x")` -
**no "y"** - so a resolver answering ACORD's own single letter left the box
UNCHECKED. Both now go through `yes_no_token`. Every value that ticked before
still ticks; this only ever added printings.

### One gate for the three deterministic writers

Pass 1 (`_deterministic_map`), Pass 1.5 (`alias_stamper`) and the schedule-row
producer each carried their own copy of the Y/N gate sequence. SYS-07 needed to
add a step to all three - which is precisely when three copies become a bug - so
they now share **`pdf_service._yn_gate(field, value, schema)`**. Its order is
deliberate and conservative:

1. A value ACORD itself prints (`Y` / `N` / `Yes` / `No`) is written UNTOUCHED.
   Nothing that works today moves.
2. A MARK is an answer in the wrong alphabet, not a non-answer: `X`, a
   checkmark, `[X]`, `true`, `1`, `Included` become the canonical `Yes`/`No`
   instead of being printed verbatim into a box ACORD heads "Y / N", or (for the
   glyphs) dropped outright.
3. Everything else keeps the 2 Sep 2026 behaviour exactly - name-licensed
   concept rescue, otherwise dropped so call 2 is ASKED rather than guessed.

`field_qa` compares through `normalize_value`, which now canonicalizes Y/N, so a
stamped "Yes" agrees with a source fact of "X" instead of raising a false
mismatch.

### Eight vocabularies down to one, with the exceptions named

| Was | Now |
|---|---|
| `fact_equivalence._YES` / `_NO` | delegates to `normalization.yes_no_token`; local sets kept only as an import-failure fallback |
| `pdf_service._resolve_bool_indicator` | shared reader |
| `pdf_service` `/Btn` writer | shared reader |
| `pdf_service._AFFIRMATIVE_VALUES` / `_NEGATIVE_VALUES` | derived from the shared tables |
| `pdf_service._CHECKBOX_VALID_VALUES` | derived (so Guard 3 stops BLANKING a gap-filled checkmark) |
| `pdf_service` dedup exemption | shared reader |
| `pdf_service._YN_ACCEPTED_TOKENS` | shared reader first, local list as fallback |
| `arq_service` checkbox answer | shared reader, and it now STORES the canonical printing - the literal `("Yes","No","true","false")` tuple was dropping a client who ticked with "X", "Y", "1" or a pasted checkmark |
| `answer_semantics` | keeps its own richer human vocabulary; a new step 4b asks the shared reader ONLY when the field is a Yes/No |

**`answer_semantics` is deliberately NOT collapsed into the shared table.** It
distinguishes VALUE / ABSENCE / NOT_APPLICABLE / UNKNOWN, and "1" means one
employee on a count box and Yes only on a Yes/No box. So the new step is GATED
ON THE FIELD, not on the value, and is placed AFTER the absence step - a bare
"No" keeps meaning ABSENCE exactly as it does today, which `_attested_true` and
`new_venture_answer` depend on.

**`coverage_evidence._TRUE_WORDS` is deliberately left alone.** It looks wrong
("excluded" is a TRUE word) and it is not: `_truthy` is only ever asked about
the WC officer table's own `include` / `exclude` cells, where a cell reading
"Excluded" is an affirmative answer to "is exclude set?". Folding it into the
shared vocabulary would INVERT it. Pinned in the anti-rot allow-list with that
reason.

### The anti-rot guard

`test_no_module_declares_its_own_yes_no_vocabulary` AST-walks `services/`,
`utils/` and `routes/` for any container literal holding two or more affirmative
AND two or more negative tokens. Seven are pinned by (file, exact tokens) WITH
the reason each cannot use the shared one; a ninth has to be a decision.
`fact_registry.py` is exempt as a file - its Yes/No literals are inside
`validate` lambdas, which DECLARE a fact's domain, and that declaration is the
source of truth this fix reads rather than a rival copy of it.
`test_the_guard_actually_harvests_something` is C25's lesson: a coverage test
that harvests nothing passes vacuously.

### Deliberately NOT done

* **`_usable` still filters a bare boolean `False` out of the picker.** That is
  defect B8 and it is load-bearing: every non-tri-state boolean in the
  extraction schema is `false` when the document simply never mentioned the
  subject, so making False a candidate would resurrect the exact false conflict
  and 85 cap B8 records. `same_fact` reads a bool correctly for its direct
  callers; `compare` still ignores it. Pinned by test.
* **ACORD text boxes are not rewritten from "Yes" to "Y".** The tooltip asks for
  Y, but changing every already-correct stamped value across 17 forms is a
  display change nobody asked for and a real regression surface. The gate leaves
  ACORD's own printings alone.
* **`display_canonicalizer` gained no Yes/No category.** The three deterministic
  writers are canonicalized at the gate and gap-fill Y/N answers are already
  governed by the evidence gate. Nothing to add.

### Verification

* **Full suite: 5786 passed / 1 failed / 14 skipped.** The one failure is the
  long-documented `httpx`/`openai` ImportError. Baseline before this work was
  5584 / 1; +202 new tests, **zero regressions**, run twice.
* **The reported case, end to end through the real `assess_underwriting_
  consistency`** with the client's two literal filenames: `review_required`
  False on "Yes" vs "X", True on "Yes" vs "No".
* **Proved the fix bites**: stubbing `declares_yes_no` to return False fails
  **38 of 202**. The tests are testing the fix, not themselves.
* **Blast-radius sweep** over 318 fact keys, old resolution vs new, printed and
  read one by one.
* No frontend change - the picker renders what the backend sends.

### Score movement - D6 applies

**Scores go UP.** A false picker conflict on an auto-discovered field becomes a
soft stop in `extraction_pipeline` (~line 1075), which caps the package at 85.
Every submission whose documents spelled one Yes two ways was paying that.
Brent sees the numbers before this ships.

Two smaller movements in the same direction: a gap-filled checkmark is no longer
blanked by Guard 3, and a client who ticked a checkbox question with "X" is now
recorded as having answered it (both raise fill rate).

### Files touched

| File | Change |
|---|---|
| `backend/services/normalization.py` | `_YES_TOKENS` / `_NO_TOKENS` / `_YES_NO_STRONG_WORDS`, `yes_no_token`, `canonical_yes_no`, `is_strong_yes_no_word`, `YES_NO_FIELDS`, `_boolean_schema_keys`, `_registry_declares_yes_no`, `declares_yes_no`, `yes_no_field_shape` + `_YES_NO_SHAPE_BLOCKERS`, `is_yes_no_field`; `normalize_value` step 1b |
| `backend/services/fact_equivalence.py` | `value_kind` step 1 reads the declaration (old step-3 shape check removed); `_yesno` / `_is_strong_yesno` delegate; bool coercion at the top of `same_fact`; the value-shaped Yes/No fallback; `_yn_printing_rank` + `_prefer` |
| `backend/services/extraction_service.py` | `BOOLEAN_FACT_KEYS`; `_variant_group_key(sval, fact_key=None)`; `_prefer_variant(new, current, fact_key=None)`; both call sites pass the key |
| `backend/services/pdf_service.py` | shared-vocabulary imports; `_yn_gate` (new, one door for three writers); `_yn_value_is_possible`, `_resolve_bool_indicator`, the `/Btn` writer, `_AFFIRMATIVE_VALUES` / `_NEGATIVE_VALUES`, `_CHECKBOX_VALID_VALUES`, the dedup exemption |
| `backend/services/alias_stamper.py` | Pass 1.5 asks `_yn_gate` instead of re-implementing it |
| `backend/services/answer_semantics.py` | step 4b - a mark typed into a Yes/No box, gated on the FIELD |
| `backend/services/arq_service.py` | checkbox answers read and stored through the shared door |
| `backend/services/underwriting_consistency.py` | `validate_confirmation` returns the canonical printing |
| `backend/tests/test_sys07_boolean_normalization_20260904.py` | new, 202 tests |

### Standing lesson this item earned

**A working rule that is never reached is indistinguishable from a missing one.**
The Yes/No comparator had been correct since C1 and already knew "X"; nothing
routed to it, because the router guessed a fact's type from the spelling of its
KEY while the registry and the extraction schema had both been declaring that
type all along. Before writing a rule, check whether the one that exists is
being asked - and route from a declaration, never from a name.

### SYS-07 LIVE TEST KIT - `sys07_test_data/` (2026-09-04)

`py backend/scripts/make_sys07_test_pdfs.py` -> four PDFs + `README-HOW-TO-TEST.md`,
self-verifying. **TWO uploads, two sessions, different insureds so extraction
caches and identity matching cannot bleed.**

| Package | Files | Claim |
|---|---|---|
| **A** | `A1_package_policy_words.pdf` + `A2_certificate_marks.pdf` | the SAME four answers, one file in words and one in marks -> **ZERO** Data Consistency conflicts |
| **B** | `B1_application_mark_yes.pdf` + `B2_questionnaire_mark_no.pdf` | the two documents genuinely DISAGREE, two of them in marks -> **STILL ASKED** |

Package A's pairs, with byte-identical labels in both files so the only variable
is the spelling:

| Question | A1 | A2 | Tests |
|---|---|---|---|
| Hired and Non-Owned Auto Coverage | `Yes` | `X` | THE CLIENT'S LITERAL CASE |
| Hired Auto Liability | `Yes` | `Y` | REGRESSION CONTROL - already Yes/No-typed before the fix |
| Non-Owned Auto Liability | `Yes` | `[X]` | a bracketed checkbox, never readable before |
| Prior Cyber Incidents or Data Breaches | `No` | `N` | the NEGATIVE half of the criteria |

**Package B is also the instrument, not just a control.** The extraction model
is free to tidy a mark into "Yes" on its own; if it does, A passes for the wrong
reason and nothing about marks was tested. B's conflict card PRINTS THE TWO RAW
VALUES - `X`/`N` means the model echoed the marks and A's pass is real,
`Yes`/`No` means it normalised upstream and a different probe is needed for the
mark path. Either answer is information.

**PROVED THE KIT DISCRIMINATES**, replayed through the real
`assess_underwriting_consistency` with the shipped code disabled and the exact
values the PDFs print:

    OLD code, package A:  auto_hired_nonowned      ['Yes', 'X']    FALSE CONFLICT
                          cyber_prior_incidents    ['No',  'N']    FALSE CONFLICT
                          non_owned_auto_indicator ['Yes', '[X]']  FALSE CONFLICT
                          hired_auto_indicator     silent          (control, correct)
    NEW code, package A:  zero conflicts
    NEW code, package B:  three conflicts, printing X and N

The first cut of that proof was WRONG and worth recording: stubbing only
`declares_yes_no` still returned "no conflict", because the **value-shaped
fallback** in `same_fact` fires independently of the type declaration. A
faithful pre-fix simulation has to disable BOTH routes plus `normalize_value`'s
Y/N branch and restore the old `_yesno` vocabulary. A partial revert can make a
real test look vacuous.

**Deliberate omissions, so the kit tests one thing honestly:**
* **No "N/A", "None" or "null" anywhere.** Those are NON-answers, and the
  extraction side of that is a separate still-open gap (CLAUDE.md "GAP 1" -
  `answer_semantics` covers the human path only). Including one would
  manufacture a failure that is not SYS-07's.
* **No renewal language.** A routed renewal moves dates to `prior_*` and changes
  what is asked - pure noise.
* **`sprinkler_system` is tested in package B, not A.** `fact_comparison.
  _ROLE_BLIND_FACTS` blinds a CERTIFICATE to COPE values, so a sprinkler answer
  on A2 would never become a candidate and the pair would prove nothing. Both
  package B files are applications.

**Forms: one generation, package A only** (ACORD 125 + 127), and the check is a
negative one that needs no knowledge of a specific box - *no Y/N box may print a
raw mark*. The client's requirement itself is entirely visible on the Review
screen; package B needs no forms at all.

### SYS-07 LIVE RUN 1 (2026-09-04) - B PASSED, A FOUND ONE MISS AND ONE OLDER BUG

**PACKAGE B - PASS, and it did its second job.** All four genuine disagreements
were asked, and the cards printed the marks **verbatim**:

    Hired Auto Indicator       X  vs  N
    Auto Hired Nonowned        X  vs  N
    Non Owned Auto Indicator   X  vs  N
    Sprinkler System           Yes vs No

So the extraction model DOES echo a bare mark into a fact. Package A was
therefore a real test of the mark path, not a vacuous pass, and normalising has
not become an amnesty - every real disagreement still reaches the producer.

**PACKAGE A - the reported class is fixed for a bare mark, and MISSED for a
mark that arrives carrying its own label.**

    Auto Hired Nonowned:  "Yes"                                   from A1
                          "Hired and Non-Owned Auto Coverage: X"  from A2   <- MISS

Extraction returned the WHOLE printed line for A2, label included, where the
same helper produced a bare "X" in package B. `yes_no_token` reads a whole bare
token only - by design, so "Yes - see the attached schedule" is not flattened
into a bald Yes - so the labelled value fell through to text comparison and
conflicted. Reproduced:

    yes_no_token("Hired and Non-Owned Auto Coverage: X")  -> None
    normalize_value(...)                                  -> "hnoa coverage x"
    compare("auto_hired_nonowned", ["Yes", <that>])       -> conflict

**This is SYS-07's own class** - "the same affirmative answer can arrive as ...
depending on the source document and **extraction path**" - so it is in scope.
The rule is not wrong, it is incomplete: a value of the shape
`<the question restated>: <bare mark>` is a labelled answer, not a qualified
one. The label is the question, not a condition on the answer.

**PACKAGE A's other two cards are NOT SYS-07 and were NOT caused by it.**

    Cyber Controls Mfa       "True" (A1)  vs  "False" (A2)
    Cyber Controls Backups   "True" (A1)  vs  "False" (A2)

A2 is a CERTIFICATE. It never mentions multi-factor authentication or backups
at all. Extraction manufactured a negative out of silence - core principle 3
("Missing does not mean No") and defect **B8** by name.

Verified not a regression: pre-SYS-07 `cyber_controls_mfa` resolved to
`KIND_TEXT` and `compare("True","False")` returned **conflict** there too.
Identical outcome before and after.

**The part worth keeping: B8's guard exists and did not fire.**
`_auto_scalar_keys` skips a value that `isinstance(v, bool)`, precisely so a
bare-`boolean` fact (where `false` is indistinguishable from "never mentioned")
cannot become a rival candidate. **The model returned the STRINGS "True" /
"False", not JSON booleans**, so the type test missed them. Measured:

    facts as real bools     -> auto_scalar_keys excludes it -> no card
    facts as "True"/"False" -> included                     -> CARD

`cyber_controls_mfa` is NOT in `TRISTATE_BOOLEAN_FACTS`, so its `false` carries
no meaning by the schema's own declaration - and the guard built on that
declaration is defeated by the model ignoring the declared type. This is the
standing lesson again in a new place: **a guard keyed on a TYPE is only as good
as the producer's willingness to honour it.** The durable form is to key on the
DECLARATION (`TRISTATE_BOOLEAN_FACTS`) and the VALUE, not on the Python type.

Also confirmed working live in the same run: SYS-05's coverage-term
normalisation ("General Liability, Commercial Auto, Cyber Liability" vs
"General Liability, Automobile Liability, Cyber Liability - treated as
equivalent") and SYS-06's per-line policy table (three lines, three numbers,
both files cited as Source, "not a conflict").

### RUN 1's TWO FINDINGS - BOTH SHIPPED 2026-09-04

#### FIX 1 (SYS-07) - an answer that arrives carrying its own question

`yes_no_token` reads a WHOLE bare token, by design, so "Yes - see the attached
schedule" is never flattened into a bald Yes. The certificate's value was
`"Hired and Non-Owned Auto Coverage: X"` - the whole printed line - so it fell
through to text comparison and conflicted with the dec page's "Yes".

**A LABEL IS NOT A QUALIFIER**, and that is the entire safety argument:

    "Hired and Non-Owned Auto Coverage: X"   the label RESTATES THE QUESTION
                                             -> the answer is X
    "Yes - see the attached schedule"        the tail QUALIFIES THE ANSWER
                                             -> never flattened

The tail must therefore be a WHOLE bare token, which the second shape fails.

**TWO READERS, ONE VOCABULARY.** `normalization.yes_no_answer` is the wider
reader and `yes_no_token` stays strict:

| Reader | Reads | Used by |
|---|---|---|
| `yes_no_token` | a bare token only | the value-shaped fallback in `same_fact`, which runs on facts NOTHING declares - a labelled value there would be an opinion on no evidence |
| `yes_no_answer` | bare, OR `<label><sep><bare token>` | every FIELD-GATED caller: `normalize_value`, `same_fact`'s KIND_YESNO branch, `_variant_group_key`, `canonical_yes_no` and through it the stamping gate, `answer_semantics`, `arq_service`, the confirm endpoint |

Guards, each one written before the code: separator is `:` or `=` only (never
`-`, which is the qualifier separator); split on the LAST separator; the tail
must be a bare token; the label is capped at 12 words / 140 chars and rejected
if it contains a sentence break; a label that is itself a NON-ANSWER ("N/A: X",
"unknown: X") reads nothing; and a label that is itself a CONTRADICTING Yes/No
token reads nothing, which is what keeps a ratio ("1:0") and a time ("10:30")
out.

**Two of those guards were written by the TESTS, not by me.** The first cut
accepted `"N/A: X"` and disagreed with itself about `": X"`. The non-answer set
and the pinned `": X"` behaviour both exist because the adversarial cases were
written first.

#### FIX 2 (defect B8, NOT SYS-07) - a two-way boolean's false is silence

Owner's ruling, verbatim: *"if any document indicates yes or no and there is
nothing related mentioned in another doc then take yes/no from that doc, but if
there is a conflict then show"*.

`extraction_service.unevidenced_boolean_negative(fact_key, value)` is the one
door. It answers True only when the fact is declared a BARE `boolean` (so the
model had no way to say "not addressed") AND the value reads as No. A
`boolean or null` fact - `TRISTATE_BOOLEAN_FACTS` - is never touched, because
there a `false` is the document saying No and principle 4 keeps it visible.

Applied in **both** places, and one without the other is a worse bug than
either:
* `underwriting_consistency` - `_auto_scalar_keys` and the candidate loop, so
  the card is not drawn;
* `extraction_service._merge_list_fields` - so the merge does not then ELECT the
  silent document's false and stamp "No" on the form. Retiring the question and
  keeping the wrong answer is the worst of both.

**The merge rule is CONDITIONAL, and that is the whole blast-radius argument:**
negatives are dropped only when some document actually answered. If every
document is silent the bucket is untouched, so a fact that merges to `false`
today still merges to `false` - no stamped box, no flag and no score moves.
Pinned by `test_when_every_document_is_silent_nothing_changes_at_all`.

**Why the old guard failed, and the lesson.** B8's protection was
`isinstance(v, bool)` - a TYPE test - and the model returned the STRINGS
"True" / "False". Measured: as real bools the key is excluded and no card
appears; as strings it is included and a card does. **A guard keyed on a TYPE is
only as good as the model's willingness to honour that type.** The rule is now
keyed on the DECLARATION plus the VALUE, which the model cannot defeat.

**Honest cost, told to the owner before it shipped:** a document that genuinely
says "No MFA in use" on a two-way boolean is now ignored, because we cannot tell
it from silence. We end with no answer instead of a wrong one - the safe
direction, and already what the schema's own tri-state split assumes. The cheap
way to shrink it later is to promote the facts that matter to `boolean or null`;
that is a prompt change (an `improving-ll.md` event, it invalidates the
extraction cache) and was NOT done here.

#### Verification

* Full suite **5839 passed / 1 failed / 14 skipped** - the documented `httpx`
  ImportError. Was 5584/1 before SYS-07 and 5786/1 before these two fixes;
  **+255 tests across the three, zero regressions.**
* Run A replayed with its literal on-screen values: **all three cards gone.**
* Run B replayed unchanged: **all four real disagreements still asked**, still
  printing `X` and `N`.
* Tests: `tests/test_sys07_boolean_normalization_20260904.py` (+16, now 218) and
  `tests/test_b8_unevidenced_boolean_negative_20260904.py` (37, new).

#### Score movement - D6

Both fixes move scores **UP** and in the same way: a false "documents disagree"
card is a soft stop, which caps the package at 85. Run A alone was carrying
three of them.

### SYS-07 LIVE RUN 2 (2026-09-04) - BOTH PACKAGES PASS

**PACKAGE A - Data Consistency reads "All confirmed". Zero cards.** All three
of run 1's cards are gone and nothing replaced them:

| Run 1 card | Run 2 | Fixed by |
|---|---|---|
| `Auto Hired Nonowned` - "Yes" vs "Hired and Non-Owned Auto Coverage: X" | GONE | Fix 1 (labelled answer) |
| `Cyber Controls Mfa` - "True" vs "False" | GONE | Fix 2 (two-way boolean's false is silence) |
| `Cyber Controls Backups` - "True" vs "False" | GONE | Fix 2 |

The whole **"Required before submission"** section disappeared with them (it
held exactly those three cross-document conflicts), and the warning count went
**7 -> 4**. Every one of the four survivors is a real property of the fixture,
not a defect: no driver schedule was printed, the ops text really does contain
the word "restaurant", and no UM/UIM or GL class code reached the facts.

**PACKAGE B - identical to run 1. Four cards, all still asked:**

    Non Owned Auto Indicator   X   vs  N
    Auto Hired Nonowned        X   vs  N
    Hired Auto Indicator       X   vs  N
    Sprinkler System           Yes vs  No

That is the whole point of the control. Neither fix is an amnesty: a genuine
disagreement still reaches the producer, and the marks are still printed
verbatim so the values remain auditable.

**Read together, the two packages prove the fix is exact rather than blunt.**
The same `X` that no longer conflicts with "Yes" in A still conflicts with `N`
in B - the difference is the MEANING, which is the only thing that was ever
supposed to matter.

#### Observed in both runs, NOT this item, not fixed

* **"GL coverage detected but no class codes found"** fires on package A even
  though A1 prints a GL hazard schedule with class code `11288`
  (Food products distributors / Sales / $9,300,000 / 0.874). Either extraction
  is not lifting a single-row hazard table or the check reads a fact nothing
  writes - the H1-C "phantom key" shape. Present in run 1 and run 2 identically,
  so it is stable and unrelated to SYS-07. **Worth a look after the P0 queue.**
* Package B's two files classify as **Dec Page** though both are applications.
  Cosmetic; it changes nothing here because an application and a dec page are
  role-blind to the same (empty) set.
* Package A's readiness tier stayed **Major Gaps**. Expected: three fewer
  conflicts raise the raw score, but four warnings still cap it at 85 and the
  tier threshold was not crossed.

### SYS-07 FORM RUN - ACORD 125 / 126 / 127 on package A (2026-09-05)

#### THE SWEEP PASSES

**No Y/N box on any of the three forms prints a raw mark**, and the string
`Hired and Non-Owned Auto Coverage: X` appears nowhere. Every Yes/No column
(125 page 3, 126 pages 2-4, 127 pages 1-2) is BLANK, which is correct: neither
document addresses those questions and blank-over-wrong is the standing rule.

**The checkbox writer still ticks.** Widening it to the shared vocabulary did
not break anything that worked: LLC, BUSINESS AUTO, COMMERCIAL GENERAL
LIABILITY, CYBER AND PRIVACY, VEHICLE SCHEDULE, and per-vehicle USE `COMM'L` /
CHECK COVERAGES `LIAB` are all ticked correctly.

**Honest limit on the sweep.** The hired/non-owned Y/N box itself lives on
ACORD **137** (the state variants), and Washington has no 137 in our set - so
that particular value had nowhere to land on these three forms. The sweep
proves the gate and the writer; it does not prove that one field's landing.
Testing it needs a CA or CO risk.

#### CONFIRMED GOOD (things earlier items fixed, still holding)

* **SYS-06**: every header carries its OWN line's contract - ACORD 126 shows
  `CSG-GL-770412-26`, ACORD 127 shows `CSG-CA-770418-26`, both with the right
  carrier and NAIC 26841.
* Evidence gate: no guessed "N" anywhere.
* Driver grid BLANK rather than invented (the review screen warned about it).
* Vehicle rows: VINs, GVW, deductibles, garaging state/ZIP and `auto_vehicle_use`
  -> `COMM'L` all correct (H1).

#### NEW FINDINGS - none of them SYS-07

**1. WRONG TICK: NATURE OF BUSINESS = RESTAURANT (ACORD 125 page 2).**
The applicant is a food WHOLESALER whose operations text reads *"Wholesale
distribution of packaged food products to grocery and restaurant accounts"*.
`_DERIVED_INDICATORS` maps
`BusinessInformation_BusinessType_RestaurantIndicator` to a bare SUBSTRING test
- `("operations_description", "restaurant")` - so the word being MENTIONED ticks
the box. The same table ticks SERVICE on any description containing "service",
RETAIL on "retail accounts", MANUFACTURING on "manufactur". This is the
`form-stamping-mention-vs-grant` class exactly, and it is a wrong answer on a
signed application. **Highest-severity thing on these three forms.** The same
word also drove the review screen's "consider crime coverage" advisory.

**2. ONE CLASS CODE PRINTED THREE TIMES (ACORD 126 schedule of hazards).**
Row A is complete and correct: LOC 1, HAZ 1, class `11288`, basis `Sales`,
exposure `$9,300,000`, description "Food products distributors". Rows B and C
repeat the class code, basis and exposure with NO location, NO hazard number and
NO classification description. The document states ONE classification. Same
shape as C46's phantom vehicle rows, one form over - the identity columns are
bound to the schedule and the rest fall through to gap fill, which then answers
about rows that do not exist.

**3. THE PRODUCER BLOCK CARRIES THE APPLICANT'S CONTACT AND ADDRESS (ACORD 125
page 1).** Producer name is right (Meridian Coast Insurance Brokers LLC) but the
address underneath is the APPLICANT's (`Ste 300, Tacoma WA 98402`) and the
contact is `Dana Whitcomb / (253) 555-0172 / dwhitcomb@northgateprovisions.com`
- the applicant's own person. **This is SYS-09**, already on the client's P0
list ("Separate client contact and brokerage contact when populating ACORD
forms"). Not a regression; the kit reproduces it cleanly, so SYS-09 has a live
repro ready.

**4. CYBER TICKED TWICE (ACORD 125 lines of business).** Both the standard
`CYBER AND PRIVACY` box (with the $1,860 premium) and a free-text
`Cyber Liability` written into an OTHER row with its own tick. One coverage
line, two boxes.

**5. DOUBLE DOLLAR SIGNS.** `$ $4,275`, `$ $8,140`, `$ $14,275` - the form
pre-prints `$` and the stamped value carries its own. Cosmetic, but on every
premium box on ACORD 125.

**6. `% OF WORK SUBCONTRACTED: 0%` (ACORD 126 page 2).** Neither document
mentions subcontracting at all. A fabricated zero - core principle 3 on the
EXTRACTION side, which is the documented GAP 1 (`answer_semantics` covers the
human path only). Note the percentage GUARD in `pdf_service` blocks gap-filled
percentages but not the fact route, so this came through as a "fact".

**7. ADDITIONAL INTEREST NAMED "Certificate Holder".** A2's remarks say
*"Certificate holder is an additional insured with respect to general liability
where required by written contract"* and we created an additional interest whose
NAME is the literal phrase, on all three forms. A label echo, not an entity.

**8. Smaller ones, recorded not chased.** ACORD 126's OCCURRENCE box is blank
though A1 prints "Coverage Form: Occurrence"; ACORD 125's premises ANNUAL
REVENUES is blank though the package states $9,300,000; ACORD 127's vehicle
`CLASS` column holds "Commercial" (a USE, not a rating class) and `VEH #` is
blank on both rows; vehicle 2 has no garaging city/state while vehicle 1 does.

#### THE REVIEW-SCREEN GL CLASS CODE WARNING IS NOW A CONFIRMED DEFECT

Run 2 recorded *"GL coverage detected but no class codes found"* as an
observation. The forms settle it: class code **11288** reached ACORD 125's
`GL CODE` box AND ACORD 126's hazard row A. The fact exists and stamps; the
check reads something the pipeline does not write. Upgraded from "worth a look"
to a confirmed phantom-key defect of the H1-C family.

### SYS-07 HOLE 1 CLOSED + THE BROADER CLAUSE MEASURED (2026-09-05)

The owner's challenge after the form run: *"check it on fuzzy values so real
client values also work not just example"*, and address the three caveats I had
raised. Both fixes below came out of a FUZZ SWEEP, not out of reasoning.

#### HOLE 1 - the label rule took two separators because that is what the run printed

`yes_no_answer` accepted `:` and `=` only. That is fitting the fixture, the exact
thing the change quality bar forbids. Measured before the fix - every one of
these was a false conflict against a plain "Yes":

    Hired and Non-Owned Auto Coverage - X          hyphen / en dash / em dash
    Hired and Non-Owned Auto Coverage    X         a COLUMN GAP, which is what a
                                                   two-column layout becomes once
                                                   it is flattened to text
    Hired and Non-Owned Auto Coverage ....... X    dot leader
    Hired and Non-Owned Auto Coverage | X          a table cell boundary
    Hired and Non-Owned Auto Coverage\tX           tab

`_YN_LABEL_SPLIT_RE` now takes `: = | tab em-dash en-dash hyphen`, a dot leader
(`\.{2,}`) and a run of two or more spaces, matching GREEDILY so it splits on the
LAST separator.

**WIDENING THE SEPARATORS IS SAFE BECAUSE THE TAIL TEST DOES THE WORK.** A
qualifier is never a bare Yes/No token, so it fails however it is divided:

    "Yes - see the attached schedule"       tail = "see the attached schedule"
    "Yes — subject to underwriting approval" tail = "subject to ..."
    "Yes - only scheduled autos"            tail = "only scheduled autos"
    "No - refer to endorsement CA 99 03"    tail = "refer to endorsement ..."

The hyphen was originally excluded for fear of the first of those. **That fear
was unfounded** - it fails on the tail, not on the separator - and the exclusion
cost real coverage.

#### TWO NEW STRUCTURAL GUARDS, BOTH WRITTEN BY THE SWEEP

1. **A label is made of WORDS** (`_YN_LABEL_WORD_RE`, one alphabetic run of 3+).
   Without it "3 - 0" reads as a No. A ratio, score, time or measurement has no
   label; every real question label does.
2. **A bare digit BEHIND A LABEL is a number, not an answer.** `"Total Losses -
   0"` came back **N** on the first run of the sweep. A bare `0`/`1` ALONE on a
   Yes/No field can only be the answer - there is nothing else the box holds -
   but behind a label it is exactly the shape of a labelled count. Also kills
   "Number of Claims: 0", "Years in Business - 1".

The mark-first parenthetical (`X (Hired and Non-Owned Auto)`) is deliberately
NOT read: `Yes (subject to underwriting)` has the identical shape and flattening
it would lose a material restriction. Recorded, not guessed at.

#### THE BROADER CLAUSE - MEASURED INSTEAD OF ASSERTED

The client's own text: *"part of the broader normalization requirement that also
applies to DATES, ADDRESSES, POLICY-NUMBER FORMATTING and other equivalent
values"*. I had been ASSERTING that earlier work covered it. Swept 33 real-world
pairs through the real door in both directions. **31 correct, 2 flagged:**

**1. `15-Jul-2025` vs `07/15/2025` -> CONFLICT. A REAL DEFECT, now fixed.**
DD-Mon-YYYY is what carrier and agency-management systems export.
`_DATE_FORMATS` gained the `%d-%b-%Y` family (and `%d/%b/%Y`, `%b-%d-%Y`, plus
2-digit-year variants).

*Two formats stay deliberately unparsed, and the reasons are asymmetric:*
* **`15/07/2025` day-first numeric** - `05/09/2026` is the 5th of September or
  the 9th of May and nothing in the string decides. Parsing it would INVENT a
  date rather than normalise one, which is worse than a false conflict.
* **`20250715` compact** - `same_fact`'s value-shape fallback tries
  `normalize_date` on NON-date fields too, so an 8-digit account or policy
  number would start reading as a date.
Both pinned by test.

**2. `BBC7263 - 26` vs `BBC7263` -> conflict through `compare()`. NOT a defect -
MY TEST used the wrong door.** The term-marker fold is SYS-06's
`same_policy_contract` / `policy_contract_groups`, which is what the picker
actually calls, and it returns True. The test was wrong, not the code. Both
doors are now pinned so the distinction cannot rot.

Everything else passed on messy input first time: ZIP+4 vs ZIP5, `Pkwy`/`Parkway`
+ `Ste`/`Suite`, a city-state fragment inside a full street address, OCR
letter-spacing on a policy number, `Travelers` vs `The Travelers Indemnity
Company`, `$1M` vs `1000000`, a limits composite vs its bare twin, FEIN with and
without the dash, four phone spellings, `LLC` vs `Limited Liability Company`,
`Sole Proprietor` vs `Sole Proprietorship` - and every genuine difference still
conflicted.

#### AAIS - CHECKED, AND IT IS NOT COVERED

The client's source screenshot offers three carrier candidates: EMPLOYERS MUTUAL
CASUALTY COMPANY / **AAIS** / EMC Property & Casualty Company. AAIS is the
American Association of Insurance Services - a rating and advisory BUREAU whose
name appears on a policy because it wrote the coverage FORMS, never because it
wrote the policy.

Grepped the whole backend: **`AAIS` appears only in the ISO/AAIS FORM-NUMBER
convention** (`extraction_service._looks_like_a_form_number`,
`pdf_service._FORM_NUMBER_RE`). There is no rule anywhere saying a bureau is not
a carrier. Measured:

    normalize_carrier("AAIS")                  -> "aais"   (a carrier family)
    compare("carrier_name", [EMC..., "AAIS"])  -> conflict
    dir(extraction_service) matching bureau    -> []

So the client's screenshot card would still offer AAIS today, and a producer who
picks it stamps "AAIS" as the carrier on a signed ACORD form. **SYS-06 territory,
NOT covered by SYS-06's ship** - its kit contained no bureau name. Reported, not
fixed: a new "these names are never a carrier" rule is a decision, and it should
be derived (ISO, AAIS, NCCI, NAIC, AAIS-style bureau names) rather than a list of
one.

#### Verification

* Full suite **5929 passed / 1 failed / 14 skipped** - the documented `httpx`
  ImportError. Was 5839/1 before this change; **+90 tests, zero regressions.**
* Fuzz: 20/20 labelled affirmatives, 26/26 refusals, 33 cross-type pairs.
* Tests: `tests/test_normalization_fuzz_20260905.py` (new) and the widened
  separator / digit-guard cases in `test_sys07_boolean_normalization_20260904.py`.

#### Standing lesson

**Both defects in this round were found by a sweep and neither by reading the
diff.** The separator list looked complete because the one live example it was
built from passed. Write the fuzz table from the DOCUMENT SHAPES the world
prints, not from the values the last run happened to produce.

### ROOT CAUSE OF THE WRONG FORM ANSWERS (2026-09-05) - DIAGNOSIS ONLY

Owner: *"we are having wrong answers on the form, and i want to first know the
root cause... go deep and find the root cause and then we can fix it properly."*

#### It is already written down, and that is the finding

`fix-form-stamping.md` (repo root, 1,716 lines, 2026-08-09) states it in one
sentence and nothing about it has changed:

> **"We stamp a value onto the form after stripping away the context that
> qualifies it. The pipeline treats a value being PRESENT IN THE DOCUMENT as
> sufficient reason to stamp it."**

with six qualifiers nobody checks - GRANT, OWNERSHIP, SHAPE, ROW INTEGRITY,
ROLE, AUTHORSHIP - and a prediction test: *"take any field, ask which of the six
is checked before it stamps. If the answer is 'none', that field is already
broken or one document away from it."*

**Seven of the nine defects on the 5 Sep forms land in that table.** Mapped:

| Defect | Qualifier missing |
|---|---|
| NATURE OF BUSINESS = RESTAURANT on a food wholesaler | OWNERSHIP (whose business is the prose describing?) |
| AAIS offered as the carrier | OWNERSHIP (carrier vs rating bureau) |
| Producer block holds the applicant's contact | OWNERSHIP (the M5 case, already documented) |
| One GL class code printed in three rows | ROW INTEGRITY |
| Additional Interest named "Certificate Holder" | ROW INTEGRITY / SHAPE - a LABEL is not a name |
| Cyber ticked twice (enumerated + "Other") | M4b, already documented |
| `$ $4,275` | SHAPE (M6: format validators not wired to stamping) |

The two that do NOT fit are not stamping defects at all: the false "no GL class
codes" warning is a CHECK reading a key nothing writes (H1-C phantom-key
family), and "0% subcontracted" is EXTRACTION inventing a value from silence
(GAP 1). Worth separating - they need different fixes.

#### THE DEEPER CAUSE: the rule is known, the ENFORCEMENT is per-field

The six qualifiers are not a gate every value passes. They are enforced **one
hand-written rescue at a time, added after each live run reports the one field
that broke.** `_derive_indicator` alone now carries five:

    _derive_symbol_indicator            covered-auto symbol grid
    _resolve_legal_entity_indicator     mutually exclusive entity boxes
    _derive_no_prior_losses_indicator   evidence-driven, multi-input
    the `is_contractor` rescue          nature-of-business (2026-08-09)
    the `coverage_lines` corroboration  lines_of_business (2026-08-10)

Underneath all five the primitive is unchanged - the last line of the loop:

    if match_val.lower() in val_str:
        return "Yes"

**A bare substring test on free text.** Measured across `_INDICATOR_RULES`:

    46 indicator rules total
    17 read a FREE-TEXT or list fact by bare substring
     8 of those (lines_of_business) DID get the corroboration guard in August
     9 of those (operations_description) DID NOT

#### WHY THE EXISTING RESCUE DOES NOT HELP - measured, not argued

The nature-of-business rescue fires only when `is_contractor` is affirmatively
TRUE, because the reported case in August was a contractor. Run against seven
ordinary businesses:

    BUSINESS              WE TICK                                        SHOULD BE     WRONG
    Food wholesaler       Restaurant, Wholesale                          Wholesale       1
    Commercial cleaning   Retail, Service, Office                        Service         2
    Truck repair shop     Retail, Service                                Service         1
    Machine shop          Manufacturing                                  Manufacturing   0
    Property manager      Apartments, Condominiums                       Service         2
    Plumbing supply       Wholesale                                      Wholesale       0
    Wholesale bakery      Restaurant, Service, Wholesale, Institutional  Wholesale       3
                                                                         TOTAL           9

**Five of seven ordinary businesses get at least one wrong tick on a signed
application.** And the rescue is wrong in BOTH directions - with
`is_contractor=True` the same wholesaler gets **every** box blanked, including
the correct one.

That is the shape of the whole problem: a rescue written from ONE reported case,
under-inclusive for every other case and over-inclusive when it does fire.

#### WHY IT KEEPS RECURRING

A business narrative names OTHER PEOPLE'S businesses as a matter of course -
customers, premises, markets. *"...to grocery and restaurant accounts"*,
*"cleaning service for office buildings and retail centers"*, *"supplying
restaurants, hotels and institutional accounts"*. The client said this in their
own words and it is quoted in the file:

> *"Primble is treating policy language describing who COULD be covered as
> evidence that the entity or condition EXISTS."*

Same sentence, one layer over: we treat prose describing who the applicant SELLS
TO as evidence of what the applicant IS.

#### PROPOSED FIX - the class, not the case (NOT IMPLEMENTED, awaiting approval)

1. **A classification question is answered by the CLASSIFICATION, not by prose.**
   The applicant's own `naics_code` / `sic_code` / `is_contractor` say what the
   business IS. `services/naics_suggester.py` already scores an operations
   description into ~60 industries with strong/weak keywords AND a negation
   stripper - a real classifier that already exists and is not consulted here.
2. **NATURE OF BUSINESS is a single-choice family.** The machinery for that
   already shipped ("Single-choice checkbox families", client #4). If prose
   alone matches two or more boxes we cannot tell which is primary - so the
   classification breaks the tie, and with no classification the family goes
   BLANK rather than ticking several.
3. **Retire the bare substring primitive for free-text facts**, the same way
   `lines_of_business` was retired in August - a tick needs corroboration from a
   structured fact, not a word in a narrative.
4. **Then apply the prediction test to all 46 rules**, not just the nine that
   broke this week: which of the six qualifiers does each check? The ones
   answering "none" are the next report.

Scores and form output both move, so D6 applies.

---

## THE FORM WRONG-VALUE ROUND - SHIPPED 2026-09-05

Owner: *"fix all these ... do it properly and i really do not want to break
things that are working properly."*

**The full diagnosis and the shipped record live in `fix-form-stamping.md`** -
that file is the cross-chat owner of this defect family and it now carries a
2026-09-05 section plus a pointer from its START HERE block. Summary only here.

Six defects, all six of them one of the qualifiers `fix-form-stamping.md`
already named. The new finding is WHY the diagnosis stayed true after being
written: **the qualifiers were enforced as hand-written rescues, one per
reported field, over an unchanged primitive** (`if match_val in val_str`).
Measured: 46 indicator rules, 17 matching free text by bare substring, 8 guarded
in August, 9 not.

| Shipped | What it does |
|---|---|
| `pdf_service._resolve_business_type_indicator` | NATURE OF BUSINESS answered by CLASSIFICATION (is_contractor -> NAICS sector -> unambiguous prose -> ASK), never by a word in a narrative. **9 wrong ticks over 7 ordinary businesses -> 0**, nothing correct lost. |
| `normalization.is_insurance_bureau` | AAIS / ISO / NCCI are never the carrier. Applied at the comparison door, the picker and the merge. |
| `normalization.is_party_role_label` | "Certificate Holder" is a role, not a party. Applied at the merge and at a post-merge floor (the single-partial path bypasses the candidate loop). |
| `pdf_service._resolve_phantom_gl_hazard_row` | The August phantom-row suppression, finally WIRED - through a narrow wrapper, because registering the whole resolver would have blanked the grid whenever extraction merely missed the schedule. |
| `pdf_service._tokens_describe_same_line` second pass | "Cyber Liability" IS ACORD's "Cyber and Privacy" box, so the line stops being written into the OTHER row as well. The distinguishing words stay unstrippable. |
| `sqs_service` GL class-code check | Reads BOTH shapes LLM call 1 records class codes in. The false "no class codes found" warning is gone. |

**THE PREDICTION TEST IS NOW CI.**
`test_no_indicator_rule_decides_a_box_from_a_narrative_without_an_owner` fails
the build when a new rule decides a checkbox from a narrative with no owner.

**Two deliberately NOT done, both stated to the owner:**
* `$ $4,275` - we ADD the `$` and ACORD pre-prints one. Confirmed and the fix is
  safe in principle, but it moves every money box on all 17 forms and only three
  were verified. Owner decision.
* `% OF WORK SUBCONTRACTED: 0%` - EXTRACTION inventing a value from silence.
  Core principle 3 on the extraction side (GAP 1), not a stamping defect.

Tests: `tests/test_form_value_qualifiers_20260905.py` (91). Suite **6020 passed
/ 1 failed** (the documented `httpx` ImportError), **zero regressions.**

### FORM-VALUE LIVE TEST KIT - `formvalue_test_data/` (2026-09-05)

`py backend/scripts/make_formvalue_test_pdfs.py` -> three PDFs +
`README-HOW-TO-TEST.md`, self-verifying. **TWO uploads, two sessions, and BOTH
require form generation** - unlike the SYS-07 kit, almost nothing here shows on
the review screen, because every claim is about a value we STAMP.

| Package | Files | Forms | Claim |
|---|---|---|---|
| **A** | `A1_wholesaler_dec.pdf` + `A2_wholesaler_certificate.pdf` | 125 + 126 | a food WHOLESALER whose narrative names restaurant / retail / service / office, carrying NAICS 424490 -> **WHOLESALE ticked and nothing else**, plus five more checks |
| **B** | `B1_facility_services_application.pdf` | 125 + 126 | the CONTROL: names office / retail / service, **no NAICS anywhere**, not a contractor -> **NATURE OF BUSINESS entirely EMPTY** |

Package A carries five fixes at once because they all land on one applicant:
ONE GL class row (hazard rows B and C must be empty), a Cyber part titled
"Cyber Liability" (CYBER AND PRIVACY ticked once, the Other row empty), AAIS
named as the AUTHOR of the forms (never a carrier), a certificate whose remarks
describe the holder without naming one (no interest named "Certificate Holder"),
and class codes printed as a rating SCHEDULE (no false "no class codes found").
Package B carries TWO class rows, so the hazard grid must fill A and B and leave
C empty - proving the phantom-row rule is POSITIONAL, not "always blank".

**WHY B IS NOT OPTIONAL.** A proves we still tick the RIGHT box; B proves the
fix was not just switching the feature off. Ticking three boxes on B means the
fix did not land; ticking nothing on A means it went too far. Both have to be
right.

**PROVED THE KIT DISCRIMINATES**, replayed through the real resolvers with the
shipped code disabled and the exact narratives the PDFs print:

    OLD code, A:  Restaurant, Retail, Service, Wholesale, Office   (5 ticks)
    OLD code, B:  Retail, Service, Office                          (3 ticks)
    OLD code, A hazard row B: NOT an owned blank -> gap fill asked -> copied row A

    NEW code, A:  Wholesale                                        (1 tick)
    NEW code, B:  (empty - asked)
    NEW code, A hazard row B: owned blank

**Self-check runs the SHIPPED resolvers over the narratives the documents state**
and fails the generator if A does not resolve to Wholesale alone, if B resolves
to anything, if B's narrative does not genuinely name several types, or if
either hazard-row claim does not hold. A kit that cannot prove its own claim
never reaches the owner.

**Deliberate omissions, told to the owner in the README as "expected, do not
report":** the `$ $9,480` doubled dollar sign, the invented `0%` subcontracted,
and the producer block carrying the applicant's contact (SYS-09). All three are
real and all three are a different item.

### FORM RUN 2 - 5 OF 6 FIXES CONFIRMED LIVE, 1 MISSED (2026-09-05)

The owner re-ran the **SYS-07 kit** (Northgate / Blackwater), not the new
`formvalue_test_data` kit. That is a REGRESSION run rather than the targeted
one - and it is worth more than it looks, because Northgate is the package that
produced the original wrong values.

#### CONFIRMED FIXED, on the forms

| # | Was | Now |
|---|---|---|
| 1 | ACORD 125 NATURE OF BUSINESS: **Restaurant + Wholesale** on a food wholesaler | **WHOLESALE only** |
| 2 | LINES OF BUSINESS: Cyber ticked twice - the enumerated box AND a free-text "Cyber Liability" in an Other row | **Cyber and Privacy ticked once. The Other row is empty** |
| 3 | ACORD 126 hazard grid: `11288 / Sales / $9,300,000` repeated in **three** rows | **Row 1 only. Rows 2 and 3 completely empty** |
| 4 | Review screen: "GL coverage detected but no class codes found" on a package whose code stamps onto two forms | **Gone on Northgate** - and it STILL FIRES on Blackwater, which genuinely states none. Precise, not blanket |
| 5 | (bonus) ACORD 126 "% OF WORK SUBCONTRACTED: 0%" | **blank on both packages** |
| 6 | SYS-07 itself | still holding - Northgate "All confirmed", Blackwater still asks with `X` vs `N` |

**The Blackwater half is the strongest evidence.** Its NATURE OF BUSINESS came
back **MANUFACTURING only** from NAICS 332312 (Fabricated Structural Metal
Manufacturing), on a narrative - *"Structural steel fabrication and light
machining for commercial builders"* - that names no business-type keyword at
all. The classification decided it, which is exactly the design. And its hazard
grid printed LOC/HAZ/TERR with **no class code**, because that package states
none: the phantom-row rule is positional, not "always blank".

#### MISSED - "Certificate Holder" is still on ACORD 125 and 126

    NAME AND ADDRESS:     Certificate Holder
    REASON FOR INTEREST:  Certificate holder is an additional insured with respect
    ITEM DESCRIPTION:     2023 Freightliner M2 106 1FVACWDT

**The fix was built one layer too low.** Verified: `_strip_non_value_facts`
DOES remove `certificate_holder` and `additional_interest_name` from the merged
facts, and `is_party_role_label("Certificate Holder")` is True. But
`_ACORD_FIELD_RULES` has **no rule touching AdditionalInterest at all** - the
block is filled by **GAP FILL**, reading the certificate's remarks sentence
directly out of the raw text. A fact-layer guard can never reach a value that
never was a fact.

That is the same lesson as the AAIS attempt earlier the same day (a
`normalize_value` guard that was inert because the door used
`strict_entity_key`) and the phantom hazard row (a suppression that was never
wired): **the guard has to sit on the path the value actually travels.**

The right home is `_enforce_post_fill_guards` - the same place C22's type gate
and the checkbox-value guard already blank a gap-fill answer that cannot be
what the box asks for. A NAME box answered with a party ROLE is exactly that
shape, and the reason-for-interest sentence beside it is a second signal.

#### OBSERVED, NOT MINE, NOT FIXED - all gap-fill noise, all new this run

* ACORD 125 `METHOD OF PAYMENT: Annual Premium` and `AUDIT: A` (Northgate) /
  `AUDIT: O` (Blackwater). Neither box was filled on the earlier run - the model
  answered them this time. "Annual Premium" is not a method of payment and a
  bare "A"/"O" is not an audit answer.
* ACORD 126 for Blackwater printed a full set of GL LIMITS ($1,000,000
  aggregate, $100,000 damage to rented premises, $5,000 medical) that **neither
  B document states**. Invented, and on the money boxes that matter most.
* ACORD 125 page 3 Q4 answered **"Y"** on Blackwater and listed the
  submission's OWN policies as "other insurance with this company".
* Northgate gained a new advisory: comprehensive/collision covered-auto symbols
  not found. Correct - that package states Symbol 1 only.
* The `restaurant` -> crime-coverage ADVISORY still fires on Northgate. The
  CHECKBOX is fixed; this is a different consumer of the same word, in
  `sqs_service`, and it was never in scope. Same class, still open.
* `$ $4,275` doubled dollar sign - known, deliberately deferred.

#### Still untested

The `formvalue_test_data` kit was NOT run, so the **AAIS bureau rule** and the
"ambiguous narrative with NO classification must ask rather than tick" control
have no live evidence yet. Both are unit-tested; neither has been seen on a
real run.

### FORMVALUE KIT - LIVE RUN, 7 OF 8 PASS (2026-09-05)

Cedar Point Provisions (A, food wholesaler, NAICS 424490) and Harborlight
Facility Services (B, ambiguous narrative, NO NAICS). ACORD 125 + 126 each.

| # | Check | Result |
|---|---|---|
| 1 | A: NATURE OF BUSINESS = **Wholesale only** | **PASS** - the narrative names restaurant, retail, service AND office; the classification decided |
| 2 | A: Cyber ticked once, Other rows empty | **PASS** |
| 3 | A: ACORD 126 hazard rows 2 and 3 empty | **PASS** |
| 4 | A: no interest named "Certificate Holder" | **FAIL** - clean on 125, still there on 126 |
| 5 | A: AAIS never a carrier | **PASS** (see caveat) |
| 6 | A: no false "no GL class codes" warning | **PASS** |
| 7 | B: NATURE OF BUSINESS entirely EMPTY | **PASS** - asked, not guessed, and not nine "No"s |
| 8 | B: hazard rows 1 AND 2 fill, row 3 empty | **PASS** - `92663 / $3,400,000` and `97447 / $1,450,000`, row 3 blank |

**Checks 1 and 7 together are the whole root-cause fix, and both landed.** A
still ticks the RIGHT box from its classification; B, with nothing to classify
on, ticks nothing at all. The fix is not a blanket off-switch, and check 8
proves the same for the hazard grid - positional, not "always blank".

**Caveat on check 5, stated so nobody over-reads it.** AAIS appears nowhere as a
carrier and the Data Consistency panel offered no AAIS card - but this run
cannot distinguish "the bureau guard fired" from "the model never proposed AAIS
as a carrier in the first place". The outcome is right either way; the guard
itself is still only unit-proven.

#### CHECK 4 - the miss, and it got WORSE in a new place

    ACORD 126 page 1, LIMITS block:
        EMPLOYEE BENEFITS                                    $1,000,000
        Certificate holder is an additional insured with     $1,000,000
    ACORD 126 page 3:
        NAME AND ADDRESS:  Certificate Holder
        ITEM DESCRIPTION:  certificate holder

The certificate's remarks sentence is now also being written into an **"other
limit" row as a $1,000,000 LIMIT**. That is a money box on a legal form, which
is materially worse than the name box.

Cause is unchanged and already recorded: the fact-layer strip works
(`_strip_non_value_facts` removes it, `is_party_role_label` returns True) but
**nothing feeds these boxes from a fact** - they are GAP FILL reading the raw
sentence. The guard must move to `_enforce_post_fill_guards`, and it now has to
cover two shapes: a party ROLE in a NAME box, and a narrative sentence in a
LIMIT box.

Note ACORD 125 came back CLEAN on the same package, so this is not deterministic
- it is the model choosing differently per form. A guard is the only fix; there
is nothing to "correct" upstream.

#### NEW, deterministic, on BOTH packages - a value in the wrong column

    ACORD 126 page 1: PREMIUM BASIS column ....... BLANK on every row
    ACORD 126 page 2: "DESCRIBE THE TYPE OF WORK SUBCONTRACTED: Gross Sales"

One bug, not two: the hazard schedule's PREMIUM BASIS ("Gross Sales") is landing
in the CONTRACTORS block's type-of-work box and leaving its own column empty.
It happened on BOTH packages, so it is deterministic, and it did NOT happen on
the earlier SYS-07 kit - whose hazard table printed the basis as `Sales` under a
`BASIS` header rather than `Gross Sales` under `PREMIUM BASIS`. So the value
only mis-routes on the fuller printing, which is the commoner one on a real dec
page. ROLE qualifier, `fix-form-stamping.md`'s table. Not previously reported.

#### Smaller, recorded

* ACORD 125 (A) `GL CODE` box blank, though ACORD 126 carries `11288`. On the
  SYS-07 kit it filled. The class code reached the schedule but not the scalar.
* ACORD 126 (B) PRODUCTS row: `PRINCIPAL COMPONENTS = "office buildings and
  retail cente..."` - the customers again, in a components box.
* B's review screen correctly reports **"Key details missing: NAICS or SIC
  industry code"** and only ONE warning - the crime-coverage advisory off the
  word "retail". The CHECKBOX is fixed; that advisory is the same word read by
  `sqs_service`, still open, still the same class.
* `$ $9,480` doubled dollar sign - known, deferred by owner decision.

### GUARD THE BOX, NOT THE FACT - SHIPPED 2026-09-05

Two fixes, one lesson. Both came out of the formvalue live run.

#### THE LESSON, and it was learned three times in one day

* the AAIS guard was put in `normalize_value` and was **inert**, because the
  comparison door groups NAME fields on `strict_entity_key` and never consults
  the dispatcher;
* the phantom hazard-row suppression was written, tested, shipped in August and
  **never wired** into `_AUTHORITATIVE_BLANK_RESOLVERS`;
* the role-label strip was built at the FACT layer and the value **still reached
  three forms**.

**A guard only works on the path the value actually travels.** For the
additional-interest boxes there is no path at all - `_ACORD_FIELD_RULES` touches
no `AdditionalInterest` field, so every value in them comes from GAP FILL
reading the raw text. A fact-layer guard can never reach a value that was never
a fact.

#### Guard 3c - a ROLE is not a party, an ARRANGEMENT is not a coverage

`pdf_service._rejects_role_or_arrangement`, wired into
`_enforce_post_fill_guards` beside C22's type gate. Two shapes, both measured
live on the same package:

    ACORD 126 p3  NAME AND ADDRESS ....... "Certificate Holder"
    ACORD 126 p1  an "other" LIMIT row .... "Certificate holder is an additional
                                             insured with"        $1,000,000

The second is a MONEY box on a legal form. ACORD 125 came back CLEAN on the same
package, so the model chooses differently per form - there is nothing upstream
to correct, only a guard to add.

It rejects the WHOLE value being a party role (via
`normalization.is_party_role_label`) and a SENTENCE describing the arrangement
(a role word followed within 80 characters by is / are / shall be / named /
included / added / endorsed). **A REMARKS or DESCRIPTION OF OPERATIONS box is
exempt** - that is exactly where the sentence belongs - and a real company whose
name contains a role word ("Certificate Holdings Inc") is untouched, because the
role test is whole-value.

This is the client's own Part 11/12 principle one layer over: *"Primble is
treating policy language describing who COULD be covered as evidence that the
entity or condition EXISTS."*

#### Guard 3d + the translation - a RATING BASIS belongs in the rating-basis box

Live on BOTH packages, therefore deterministic, and NOT previously reported:

    ACORD 126 p1  PREMIUM BASIS column ................. BLANK on every row
    ACORD 126 p2  "TYPE OF WORK SUBCONTRACTED" ......... "Gross Sales"

One value, the wrong column - the ROLE qualifier. Fixed on both sides:

1. **The box now gets ACORD's own code.** `rating_basis_code` translates the
   words to the letter, and `_resolve_gl_hazard_row` uses it for
   `PremiumBasisCode`. **The legend is PRINTED ON THE FORM** - (S) GROSS SALES,
   (P) PAYROLL, (A) AREA, (C) TOTAL COST, (M) ADMISSIONS, (U) UNIT, (T) OTHER -
   and the tooltip says *"Enter code: an industry code designating the rating
   basis of the exposure amount."* So this is ACORD's table, not one we
   invented, exactly like the shipped `valuation_method` -> `R`/`A`. An
   unrecognised basis passes through unchanged rather than being dropped:
   blanking real data is the worse failure.
2. **`_rejects_misplaced_rating_basis`** blanks a bare basis term found OUTSIDE
   a rating-basis box. Bounded to values of three words or fewer, so a real
   answer that merely contains the word ("Framing and gross sales support
   work") is never touched.

Why it did not appear on the SYS-07 kit: that hazard table printed `Sales` under
a `BASIS` header. The formvalue kit prints `Gross Sales` under `PREMIUM BASIS` -
the fuller printing, and the commoner one on a real dec page.

#### Verification

* Suite **6053 passed / 1 failed / 14 skipped** - the documented `httpx`
  ImportError. Was 6020/1. **+33 tests, zero regressions.**
* `tests/test_form_value_qualifiers_20260905.py` now 124 tests.

#### Still open after this

* The `restaurant` / `retail` -> crime-coverage ADVISORY in `sqs_service`. The
  CHECKBOX is fixed; this is the last consumer of the same word-match.
* `$ $9,480` doubled dollar sign - owner decision, deferred.
* The AAIS bureau guard remains unit-proven only: the live run showed no AAIS
  anywhere, but cannot separate "the guard fired" from "the model never
  proposed it".

### THE REMAINING OPEN ITEMS - SHIPPED 2026-09-05

#### 1. The crime advisory - the LAST consumer of the word-match class

`cross_form_validator._check_crime_silent_exposure` read the same narrative with
the same bare `if kw in ops` test. Live, both packages:

    food WHOLESALER  -> "the business description mentions 'restaurant', 'retail'"
                        from "...to grocery, restaurant and retail service accounts"
    JANITORIAL firm  -> "...mentions 'retail'"
                        from "...for office buildings and retail centers"

Both times the word belonged to the CUSTOMERS.
`_cash_term_is_the_applicants` applies TWO conditions, strongest first:

1. **THE CLASSIFICATION.** A term naming a KIND of business (retail,
   restaurant, bar, tavern, bank, pawn, jewelry) is discounted when the
   applicant's own NAICS says it is something else - and CORROBORATED when the
   NAICS agrees.
2. **THE SENTENCE.** With no classification, a mention governed by a customer
   phrase ("to ... accounts", "for ... buildings", "... centers") is somebody
   else's premises. Every mention is checked, so one genuine mention still
   fires.

**Terms with no business-type meaning are NEVER discounted by rule 1** - cash,
vault, armored, currency, atm, teller-less money handling. Being a wholesaler
does not stop you handling cash.

**ONE OWNER for "what is this business".** The NAICS taxonomy moved to
`normalization.naics_business_type`, and both consumers - the ACORD 125 NATURE
OF BUSINESS boxes and this advisory - now ask it. They cannot disagree, so a
food wholesaler cannot be a wholesaler on the form and a restaurant in the
warning.

Measured, 9 cases: both live false positives gone; a real restaurant, a real
retail store, a bar, a cash-handling vending route and an armored-car operator
all still warn; the roofing contractor (the 2026-08-17 false positive) stays
silent.

#### 2. The doubled dollar sign - measured PER BOX, never blanket

I nearly got this wrong. `canonicalize_currency` adds a "$" and the form prints
one, so every live premium read `$ $4,275`. **But a blanket strip is WRONG:**
ACORD 126's LIMITS column prints a "$" and its PREMIUMS column does NOT, so
removing the symbol everywhere would lose it exactly where the form does not
supply it. That is why this was deferred rather than done in the earlier round.

`_fields_with_printed_currency(form_id)` reads the TEMPLATE: each widget's
`/Rect` gives the box, and the 26pt band immediately to its left is inspected
for a "$". Cached per form (`lru_cache`), and any failure returns an empty set
so the value keeps its own symbol exactly as today. Measured: **41 boxes on
ACORD 125, 13 on 126, 23 on 127** - and the 126 PREMIUMS boxes correctly are
NOT among them.

**NINE TESTS FAILED, and the CODE was right.** They asserted `== "$3,954"` on
boxes the form prints a "$" beside - pinning an incidental display detail while
actually testing *which box got which amount*. Each now compares the AMOUNT via
a local `_amt()` helper, so the intent is preserved and the display rule can
never break them again. Files: `test_form_fill_1sep.py`,
`test_form_fill_ownership_20260810_runf.py`, `test_raw_text_verification.py`,
`test_relationship_fixes_20260816.py`, `test_stamping_fixes_20260810.py`.

#### DELIBERATELY NOT FIXED, and why - these are NOT "done quietly"

* **`METHOD OF PAYMENT: Annual Premium`** - the box is declared *"Enter text:
  the method the policy will be paid"*, so it accepts free text and no type
  guard can reject this. "Annual Premium" is a weak answer, not a provably
  wrong one.
* **`AUDIT: A` / `AUDIT: O`** - the box is *"Enter code: the audit term"*, and
  **"A" is a legitimate ACORD audit-frequency code (Annual)**. Guarding it would
  need ACORD's own code list, which is not in the schema; inventing an
  allow-list I cannot verify would be exactly the fixture-fitting this whole
  arc has been removing. "O" is likely wrong, one value, low confidence.
* **`PRINCIPAL COMPONENTS = "office buildings and retail centers"`** - the
  customers in a components box. Same OWNERSHIP class, but a components box has
  no closed domain to check against and no classification to appeal to.
* **ACORD 125 `GL CODE` blank while 126 carries `11288`** - a GAP, not a wrong
  value. The code reached the schedule fact and not the scalar.
* **Gap fill inventing GL LIMITS** on a package that states none - the generic
  "gap fill invents" class, out of scope here.
* **The AAIS bureau guard is still unit-proven only.** The live run showed no
  AAIS anywhere, but that cannot separate "the guard fired" from "the model
  never proposed it".

#### Verification

Suite **6066 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, back at the baseline. Was 6053/1 before this round.
`tests/test_form_value_qualifiers_20260905.py` now **137 tests**.

### FORMVALUE RUN 3 - ALL FIVE CHECKS PASS, TWO ORPHAN HALVES FIXED (2026-09-05)

Cedar Point Provisions (A) and Harborlight Facility Services (B), ACORD 125 + 126.

| Check | Result |
|---|---|
| A: NATURE OF BUSINESS = **Wholesale only** | **PASS** |
| B: NATURE OF BUSINESS **entirely empty** | **PASS** |
| Cyber ticked once, Other rows empty | **PASS** |
| A: hazard rows 2-3 empty · B: rows 1-2 fill, row 3 empty | **PASS** |
| **ACORD 126 PREMIUM BASIS = `S`** on every row, both packages | **PASS** - was blank |
| **"Gross Sales" out of the subcontracted box** | **PASS** |
| **No "Certificate Holder"** - not a name, not a limit, either form, either package | **PASS** |
| **`$ 5,120` / `$ 9,480` / `$ 16,740` / `$ 13,900`** - single symbol | **PASS** - and ACORD 126's PREMIUMS column still shows its own |
| AAIS never a carrier | **PASS** |

**METHOD OF PAYMENT fixed itself.** It read "Annual Premium" on run 2 and now
reads **"Producer / Agency"** (A) and **"Direct Bill"** (B) - both real payment
methods. Nothing was changed for it; the model simply answered better with the
surrounding boxes cleaner. `AUDIT: A` persists and is still correct as
discussed - "A" is a legitimate ACORD audit-frequency code (Annual).

#### TWO ORPHAN HALVES, both created BY the fixes, both now closed

**A HALF-FIX IS ITS OWN DEFECT.** Both of these are the same shape: a guard
removed the wrong value and left its partner behind.

1. **An unlabelled $1,000,000 limit (A, ACORD 126).** Guard 3c correctly blanked
   *"Certificate holder is an additional insured with"* out of the OTHER
   coverage DESCRIPTION - and the amount beside it stayed, leaving a limit on a
   legal form that names no coverage. An "other coverage" row is precisely the
   one the form does NOT enumerate, so its description is what names it.
   `_blank_unnamed_other_rows` (Guard 3f) now blanks an OTHER amount whose
   description is empty - mechanism M4, the same rule Guard 2d already applies
   to line+number pairs. Enumerated limits are untouched: the form names those
   itself.

2. **`0%` in "DESCRIBE THE TYPE OF WORK SUBCONTRACTED" (B, ACORD 126).** The
   rating-basis guard removed "Gross Sales" and the model put a bare percentage
   there instead, while the "% OF WORK SUBCONTRACTED" column beside it stayed
   empty. Guard 3e: **a DESCRIBE box needs WORDS.** Identified from ACORD's own
   declaration - the field name says description AND the tooltip says "Enter
   text:" - because either condition alone is too loose. A real description
   carrying a percentage ("Roof work 40%") is untouched.

#### Observed, unchanged, NOT fixed

* **`EMPLOYEE BENEFITS $1,000,000` (A, ACORD 126)** - a NAMED limit nothing in
  the documents states. That is the generic "gap fill invents a limit" class,
  not the orphan class, and it is out of scope here.
* ACORD 126 PRODUCTS table came back empty on A this run where it carried
  `$11,600,000` last run, and B's `PRINCIPAL COMPONENTS = "office buildings and
  retail centers"` is gone. Both are model variance, neither a wrong value now.
* The review screens were not sent this run, so the **crime-advisory fix has no
  live confirmation yet** - it is unit-proven only (9 cases), like the AAIS
  guard.

#### Verification

Suite **6077 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. Was 6066/1. **+11 tests, zero regressions.**
`tests/test_form_value_qualifiers_20260905.py` now **148 tests**.

### SYS-07 ACCEPTANCE AUDIT - THE BROADER CLAUSE, AND WHAT IT COST (2026-09-05)

The owner asked the only question that matters: *"will it work on the client's
REAL data, or only on the example?"* So the fix was attacked with the shapes a
scanned / flattened broker document actually produces, not the ones it was
designed for. **11 of 21 shapes came back a FALSE CONFLICT.** Every one is now
closed, and the sweep is a permanent test.

#### What was missing, and why the first cut could not have caught it

The first cut read the vocabulary the CLIENT'S SCREENSHOT printed - Yes, true,
X, a checkbox. **A declarations page does not say "Yes".** It says the coverage
is `Covered` / `Elected` / `Purchased` / `Provided` / `Afforded`, or it says
`Not Covered` / `Declined` / `Waived`. Fitting the screenshot is fitting the
fixture, which is the one thing the change quality bar forbids, and it took an
adversarial sweep rather than more reasoning to see it.

| Shape | Before | Now |
|---|---|---|
| `Covered` / `Elected` / `Purchased` / `Applies` / `Provided` / `Afforded` / `Carried` / `Granted` | conflict | Yes |
| `Not Covered` / `No Coverage` / `Declined` / `Rejected` / `Waived` | conflict | No |
| `Label\nX` - a **two-line table cell**, one of the commonest flattened shapes | conflict | reads the mark |
| `Hired and Non-Owned Auto X` - a label and its mark, **one space** | conflict | reads the mark |
| `X]` / `[X` - OCR drops half a bracket | conflict | Yes |
| `Y e s` / `N o` - OCR letter-spacing on a scan | conflict | Yes / No |

**NEGATION IS STRUCTURAL, NOT ENUMERATED.** `not <affirmative>` is ONE rule
(`_YN_NEGATION_RE`), so an affirmative added tomorrow is negatable the day it is
added and cannot be half-covered - the shape that let the auto-symbol and
Umbrella SIR bugs each survive their first fix.

**`applicable` is deliberately NOT an affirmative.** If it were, the negation
rule would read `Not Applicable` as a **No** - turning an absence into a
negative, core principle 3, the exact inversion this item exists to prevent.
Pinned by `test_negation_never_turns_a_non_answer_into_a_no`.

#### The fix broke something, the existing suite caught it, and that is the point

Widening the separator to a single space made the greedy head keep the real
separator: `"Not Applicable - X"` split to head `"Not Applicable -"`, which is
**not** the string the non-answer table holds - so the label escaped every check
below and the `X` was read as a **Yes on a question that does not apply.** Three
pre-existing tests failed on it immediately. Head is now stripped of separator
characters (`_YN_SEP_CHARS`), and a head whose last word is a negation
(`Hired Auto Not Covered`) can never license its tail.

#### THE BIGGER FIND: policy-number formatting was still broken

The acceptance criteria does not stop at booleans - it says this is *"part of
the broader normalization requirement that ALSO applies to dates, addresses,
POLICY-NUMBER FORMATTING, and other equivalent values."* Dates, addresses,
names and amounts all passed a 35-case sweep. **Policy numbers did not.**

    picker card:  "BBC7263"  vs  "BBC7263 - 26"   ->  documents disagree

That is the client's OWN package - `BBC7263 - 26` on the dec page, `BBC7263` on
the certificate - and the producer was being asked to choose between one policy
and itself.

**ROOT CAUSE IS SYS-07'S OWN, ONE FACT TYPE OVER: the comparator existed, was
correct, and NOTHING ROUTED TO IT.** `same_policy_contract` has been right since
SYS-06. But the picker merges through `_merge_equivalent_value_groups` ->
`fact_equivalence.equivalent_index` -> `same_fact`, whose `KIND_IDENTIFIER`
branch was exact-alnum equality. Its own comment even conceded the gap - *"a
prefix is NOT merged here ... proving it needs the canonical joiner ... applied
upstream"* - and SYS-06 had already built exactly that context-free proof. The
branch never learned.

**Fixed by moving the rule DOWN a layer, not by adding a second copy.** It now
lives in `fact_equivalence` (beside `_alnum`, which it already used) and
`fact_comparison.same_policy_contract` DELEGATES - one implementation, import
direction unchanged, and `test_there_is_exactly_one_implementation` fails the
build if the regex ever reappears in the upper module.

Two supporting doors, both DERIVED and both owned by `normalization`:
* `is_policy_number_field` - from the key's own tokens, so
  `prior_policy_number`, `umbrella_policy_number` and `policy_number@auto` all
  answer True the day they are added. **`certificate_number` is False** - a
  certificate is not the contract.
* `strip_leading_label` - `"Policy No. BBC7263"` -> `"BBC7263"`, the SYS-07
  "value carrying its own label" shape one fact over. `POLICY-123` is untouched
  (no space, so it is part of the number).

**Still separates what must separate:** `BBC7263`/`BBC7264`, `POL123`/`POL12345`
(digits run together, not a printed term marker) and `BBC7263-26`/`GL-4471102-26`
(defect D-1, two carriers' GL policies on one line).

#### THE TRAP THAT ALMOST WON, for the third time this week

The first version of this fix was placed in `fact_comparison.compare`. Every
unit test passed and **the picker still drew the card**, because the picker does
not go through `compare` - it calls `equivalent_index` directly. Identical to
the AAIS guard, which was inert in `normalize_value` for the same reason, and to
the role-label fix, which was built at the fact layer while the value came from
gap fill.

**STANDING LESSON, now three for three: FIX THE LAYER THE SCREEN ACTUALLY
READS, and prove it by driving the screen - never the primitive.** Every test in
`test_policy_number_normalization_20260905.py` asserts through
`assess_underwriting_consistency`, not through the comparator.

#### Verification

**51 of 51** end-to-end picker cases correct - 40 that must fold (Y/N, dates,
policy numbers, addresses, names, amounts) and 11 that must stay a conflict.
Suite **6152 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. Was 6077/1. **+75 tests, zero regressions.**
New: `tests/test_policy_number_normalization_20260905.py` (27);
`test_sys07_boolean_normalization_20260904.py` 218 -> 308.

#### Honest residue

* **AAIS bureau guard and the crime advisory are still unit-proven only.** No
  live run has shown either firing.
* `"Yes"` vs `"Yes - $1,000,000"` folds as the same answer. **Pre-existing,
  verified against HEAD** (ordinary text containment, unrelated to this work),
  and correct: both affirm.
* Day-first numeric dates (`15/07/2025`) and compact 8-digit (`20250715`) are
  still not parsed - deliberate, they are ambiguous against US format.

### THE OPEN HALF OF THE YES/NO VOCABULARY - SHIPPED 2026-09-05

**Live runs C and D passed first time.** C (dec-page words vs certificate
marks, same policy printed two ways) produced **zero** Data Consistency cards -
`Covered`=`X`, `Elected`=`Y`, `Provided`=`[X]`, `Not Covered`=`N`, and both
`BBC7263 - 26`/`BBC7263` and `6E7-40-02---26`/`6E74002` merged into one policy
row sourced from BOTH files. D produced its five cards and printed the RAW
values (`Covered` against `Not Covered`), which is the finding that matters:
**the extraction model did NOT tidy the carrier's words upstream**, so C passed
because our reader folded them, not because the model hid the test.

#### The problem D confirmed we still had

A carrier writes its own forms. A declarations page says `Covered`, `In Force`,
`Bound`, `Endorsed`, `Scheduled`, `Written`. **The affirmative half of the
vocabulary is unlistable by construction**, and every word the deterministic
table did not hold cost the producer a card on two documents that agree.
Measured against 21 plausible unlisted words: 20 unreadable.

**The two sides are not symmetric, and that is the whole design.**
Affirmatives are open - anything asserting presence. Negatives are nearly
closed - not/no/non/un-/ex- plus excluded, declined, waived, rejected, void,
deleted, cancelled, lapsed. One side can be finished; the other cannot.

#### What shipped - `services/yes_no_lexicon.py`

Owner's call: *"can we just not let AI judge the meaning ... because there can
be thousand words?"* Yes - **but not as a new AI step.** The extraction model
already reads these documents. It is now asked, once per package, what the
words it could not read MEAN, and the answer is cached BY THE WORD.

    deterministic reader (normalization)  ->  cache  ->  one batched ask  ->  None

**Four things it is structurally forbidden to do**, each pinned by a test:

1. **Never override the deterministic reader.** `normalization` answers first,
   always. A reply saying `"Excluded" = Y` changes nothing.
2. **Never write a value onto a form.** The only consumer is *"do these two
   documents agree?"*. `pdf_service`'s checkbox writer and `_yn_gate` stay
   deterministic, so the worst a wrong reply can do is show or hide a CARD -
   never put a wrong value on a legal document.
3. **Never turn a NON-ANSWER into an answer.** `_is_classifiable` asks
   `answer_semantics.interpret_answer` - the door that already owns *"did they
   answer?"* - and refuses anything it does not call a PRESENT value.
4. **Never accept a key it did not ask about**, and learn nothing on any
   failure. Unsure leaves the card exactly where it was.

**Rule 3 was NOT in the first version, and my own test caught it.** An
adversarial stub replying `"Not Applicable" = N` was accepted, and an absence
became a NEGATIVE - core principle 3, the exact inversion SYS-07 exists to
prevent. The prompt already forbade it; **H1-K is the standing proof that a
prompt is not a guarantee**, so the condition is now structural and asks the
existing door rather than adding a second opinion.

#### Why the cache is shared, and why that is safe

The answer depends on the WORD alone - never the document, the applicant or the
package - so one lookup serves every session that ever meets it. That gives
three things at once: **cost converges to zero**, **two runs of one package
agree** (which is the property the deterministic-only design was protecting and
is not being given up - `lookup` is a dict read with no I/O, pinned by
`test_the_comparison_path_performs_no_io`), and **no customer data can enter
it** - a term must be <=40 chars, <=4 words, alphabetic and digit-free, so an
amount, a date, a code, a name, an address or a sentence is refused before the
call.

A 26-word seed ships warm so a fresh install needs no call at all.
Kill switch `YES_NO_LEXICON=0`. Cost entry: `improving-ll.md` C86.

#### Verification

Suite **6215 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. Was 6152/1. **+63 tests, zero regressions.**
`tests/test_yes_no_lexicon_20260905.py` (63). Live kit:
`py backend/scripts/make_sys07b_test_pdfs.py` -> `sys07b_test_data/`.

#### Still not confirmed live

The **crime advisory** and the **AAIS bureau guard** - neither trigger appears
in any kit run so far. Both are unit-proven only and should be folded into the
next kit rather than getting a third one.

#### LIVE RUN E FAILED, AND THE CAUSE WAS THE SAME TRAP A FOURTH TIME (2026-09-05)

Run E printed three unlisted words against certificate marks and produced
**three conflict cards** - `Issued`/`X`, `Withdrawn`/`N`, `Underwritten`/`Y`.
No cache file was ever written, so `learn()` had never succeeded.

**Root cause: I guessed the VALUE SHAPE.** The term collection was inline in
`extraction_pipeline._finalize_pipeline` and filtered `isinstance(_v, str)`.
A per-document fact is an **annotated envelope** - `{"value": ...,
"confidence": ...}`, written by `extraction_service._annotate_facts` - so the
filter dropped every fact in the package and the model was never asked. The
module was correct; nothing reached it.

**This is the AAIS / role-label / policy-contract defect in a new costume.**
Three of those were a fix wired into a layer the screen does not read. This
one is a fix wired into a SHAPE the data does not have. **Guessing the shape
fails exactly as surely as guessing the layer** - and 63 unit tests passed
through it, because every one of them fed a convenient bare string.

**Fix:** the collection moved into the lexicon as `terms_from_documents`,
which unwraps the envelope beside the rule that needs it, and the tests now
drive the REAL document shape. `test_the_call_site_does_not_reimplement_the_
collection` fails the build if the inline filter comes back.

#### WHAT RUN E DID CONFIRM - two fixes that had never been exercised live

* **The AAIS bureau guard WORKS.** E1 prints `American Association of
  Insurance Services (AAIS)` in its forms schedule and as a `Rating Bureau`
  row, and E2 repeats it. **AAIS was never offered as a Carrier** - no carrier
  card appeared at all, and the policies table shows only Buckeye Guaranty.
  First live confirmation.
* **The crime advisory WORKS.** E is a **janitorial** firm whose operations
  read *"for office buildings and retail centers"* - the literal sentence that
  produced a false crime-exposure warning before the fix. **No crime warning
  appeared.** First live confirmation.

#### RUN F - one control passed, one never ran

* **`Pending` vs `Yes` produced a card.** A non-answer is never classified,
  live. Core principle 3 holds.
* **`Underwritten` vs `Stricken` produced NOTHING**, and that is a KIT defect,
  not a code one: F1/F2 named a carrier and a policy but carried no auto
  coverage at all, so the auto question had nothing to attach to and the fact
  was never extracted. **A control that is not extracted is not a control.**
  F now carries a Business Auto coverage part, and the kit's self-check
  refuses to write unless both files contain one.

#### Verification

Suite **6228 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. Was 6215/1. `tests/test_yes_no_lexicon_20260905.py` now **76**.
Re-run `sys07c_test_data/` (regenerated).

#### THE FRAME WAS WRONG TWICE, AND THE MODEL WAS RIGHT BOTH TIMES (2026-09-05)

Live run E round 2: the plumbing worked - `yes_no_lexicon: asked 3 term(s),
learned 1, refused 2` - and `Withdrawn` folded while `Underwritten` and
`Issued` still drew cards.

**Round 1 asked: "what does this word mean as an answer on an insurance
form?"** Handed the bare word, the model refused - correctly. Rule 1 says
unknown is always safe, and out of context "issued" could as easily describe
the POLICY being issued as the coverage being elected.

**Round 2 added the question the box answers, taken from `FACT_REGISTRY`.** It
refused the same two, and was right again: `hired_auto_indicator` is registered
as *"Do employees drive hired or rented vehicles for business purposes?"* -
an EXPOSURE question, which "Underwritten" does not answer. **Real context,
and the WRONG context.** A dec page prints coverage STATUS beside a coverage
NAME; the registry holds an interview question. They are not the same thing.

**The frame was wrong, not the model.** This layer never needed to know what a
term answers. The comparison asks only whether two values mean the SAME THING,
so the question is **POLARITY**: does this word assert presence, or absence?
That is a property of the word alone - which is also precisely what licenses
caching by the word, so the fix made the design MORE coherent, not less.

**Measured live, one call, 19 terms:** `underwritten` `issued` `placed`
`in force` `bound` `endorsed` `quoted` -> **Y**; `withdrawn` `stricken`
`forgone` -> **N**; `not applicable` `pending` `tbd` `none` `silent`
`see schedule` plus an amount, a date and a person's name -> **unknown**.
**19/19, where the two earlier frames scored 1/4.** The registry-context
machinery was deleted rather than left in place unused.

**Standing lesson: when a model refuses, check the QUESTION before blaming the
model.** Two rounds were spent adding capability to a layer that was already
capable and simply being asked the wrong thing.

#### Verification

Suite **6231 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. `tests/test_yes_no_lexicon_20260905.py` now **79**, including
`test_the_prompt_asks_for_polarity_and_not_for_an_answer` and
`test_the_ask_carries_no_per_document_context`, which fail the build if the
answer-matching frame or a per-document payload comes back.

**Re-run `sys07c_test_data/` after restarting the backend** - refusals are held
in memory, so the two previously-refused terms are only re-asked in a fresh
process.

#### LIVE RUN E - CLEAN, THIRD ATTEMPT (2026-09-05)

**"Data Consistency - All confirmed." Zero cards.** All four carrier words the
deterministic table has never held - `Underwritten`, `Placed`, `Issued`,
`Withdrawn` - folded against the certificate's `X` / `Y` / `[X]` / `N`. The
polarity frame closed it on the first live run after the reframe.

Confirmed in the same run, all previously unproven:

| Fix | Evidence |
|---|---|
| The open Yes/No vocabulary | 4 unlisted words, 0 cards |
| **AAIS bureau guard** | AAIS printed twice in E; never offered as Carrier |
| **Crime advisory** | janitorial firm, ops say "retail centers"; no warning |
| Policy-number formatting | both lines correct, sourced from BOTH files |

The 3 remaining warnings are all legitimate and none is a normalization
issue: no covered-auto symbol, no driver schedule, UM/UIM not stated.

**Run F: the non-answer control holds.** `Pending` against `Yes` still draws
its card. A non-answer is never classified, live, however the model would have
answered.

#### ONE OPEN QUESTION, AND IT IS NOT IN THE LEXICON

F's second control - `Underwritten` (Y) against `Stricken` (N), *"learning must
not become an amnesty"* - produced **no card**, on a run where both words were
learned with opposite polarity. Three candidate causes were eliminated by
measurement, not by argument:

1. **The comparison door is right.** `_card("hired_auto_indicator",
   "Underwritten", "Stricken")` returns True with the real learned polarities -
   pinned by `test_the_polarity_frame_classifies_what_the_other_frames_refused`.
2. **B8 is not dropping it.** None of the four auto/cyber facts is a bare
   boolean, and `unevidenced_boolean_negative` returns False for `Stricken`,
   `Withdrawn`, `No`, `N`, `false` and `Not Covered`.
3. **Both files print the line**, verified from the PDFs themselves.

That leaves EXTRACTION: the two thin application documents are not producing
the same fact key from the same printed line - most likely one wrote
`hired_auto_indicator` and the other `auto_hired_nonowned`, giving each fact a
single value and nothing to compare. **A control that does not reach the
comparison is not a control**, the same lesson F already taught once. Closing
it needs the F session's facts, not another lexicon change.

---

## SYS-07 - FINAL VERDICT, 2026-09-05

**MET. Proven on live runs, not asserted.** Read this before reopening the item.

### The criteria, clause by clause

> *"Normalize common affirmative representations to one canonical true value
> and common negative representations to one canonical false value before
> comparison."*

`normalization.canonical_yes_no` returns exactly `"Yes"` / `"No"` / `None`.
One vocabulary, one owner. `None` means "cannot say" and never means No.

> *"Route this through the same pre-comparison canonicalization layer used for
> other equivalent values."*

`services/normalization.py` is that layer and `services/fact_comparison.py` is
the one door (C1/D3); `tests/test_comparison_has_one_owner.py` fails the build
if another module compares behind its back. Yes/No is not a side path - it is
`KIND_YESNO` inside the same `same_fact` that decides dates, addresses, names,
amounts and identifiers.

> *"...so warnings are created only after normalization and formatting or
> representation differences alone cannot produce a conflict."*

Measured end-to-end through `assess_underwriting_consistency` - the screen, not
the primitive: **40 pairs that must fold and 11 that must stay a conflict,
51/51 correct**, across Yes/No, dates, addresses, names, amounts and policy
numbers.

> *"This is part of the broader normalization requirement that ALSO applies to
> dates, addresses, POLICY-NUMBER FORMATTING, and other equivalent values."*

The broader clause was **not** met when the item was first called done. A
35-case sweep found dates, addresses, names and amounts clean and
**policy numbers broken on the client's own package** (`BBC7263` against
`BBC7263 - 26`). Fixed - see SYS-07b - and confirmed live.

### What was proven LIVE, and on which run

| Claim | Run | Evidence |
|---|---|---|
| `Yes` = `X` = `true` = a checked box | A/B (09-04) | 0 cards; B still disagreed |
| Carrier words vs certificate marks (`Covered`/`Elected`/`Provided`/`Not Covered`) | C (09-05) | 0 cards |
| **Raw carrier words survive extraction** | D (09-05) | cards printed `Covered` vs `Not Covered`, NOT `Yes`/`No` - so C folded them, the model did not hide the test |
| One policy printed two ways | C/E | `BBC7263 - 26`+`BBC7263` and `6E7-40-02---26`+`6E74002` merged, sourced from BOTH files |
| **Words nobody listed** (`Underwritten`/`Placed`/`Issued`/`Withdrawn`) | E (09-05) | "Data Consistency - All confirmed", 0 cards |
| A non-answer is never classified | F (09-05) | `Pending` vs `Yes` still cards |
| Two real policies still disagree | D | `BBC7263` vs `BBC7264` cards |
| AAIS is never the carrier | E | printed twice, never offered |
| Crime advisory silent on a customer's trade | E | janitorial firm, "retail centers", no warning |

### The honest residue - what is NOT proven

1. **F's amnesty control never reached the comparison.** `Underwritten` (Y)
   against `Stricken` (N) drew no card. The comparison door is right (pinned
   with the real learned polarities), B8 is not dropping it, and both PDFs
   print the line - so the two thin application documents are not producing the
   same fact key from the same printed line. **An extraction question, not a
   normalization one.** Needs F's session facts to close.
2. **Day-first numeric dates (`15/07/2025`) and compact 8-digit (`20250715`)
   are still unparsed.** Deliberate: ambiguous against US format. They fail to
   a card, never to a wrong date.
3. **An unknown word the model refuses still costs a card.** Measured: of 21
   plausible unlisted words, **zero were read backwards**. The failure
   direction is a question, never a wrong value on a form.
4. **`"Yes"` vs `"Yes - $1,000,000"` folds.** Pre-existing (verified against
   HEAD), by ordinary text containment, and correct - both affirm.

### Four defects were introduced BY these fixes and caught before shipping

Recorded because the pattern is the lesson, not the individual bugs:
`"Not Applicable - X"` read as a Yes when the separator widened (caught by the
existing suite); an absence classifiable as a No by any model reply (caught by
my own adversarial stub); the term collection filtering `isinstance(str)` when
a fact is an annotated envelope (caught only by LIVE RUN E - 63 unit tests
passed through it); and two wrong framings of the model prompt (caught by the
model refusing, correctly, twice).

**Suite 6231 passed / 1 failed** - the documented `httpx` ImportError.

---

## SYS-04 - Do not create WC issues when Workers' Comp is not in the submission - THE DIAGNOSIS

**Status: DIAGNOSIS ONLY, no code written. Awaiting owner sign-off on the approach.**
Date: 2026-09-05.

### What the client asked for

> **WHAT WE OBSERVED** - "Primble is surfacing a Workers' Compensation-related
> no-known-losses issue even though Workers' Comp is not identified as active in the
> declarations, underwriting narrative, or certificate. This is a false positive caused
> by treating a non-present line as though it were an active coverage requirement."
>
> **EXPECTED OUTCOME** - "Gate line-specific recommendations and loss requirements on
> evidence that the line is actually active or intentionally requested. If Workers'
> Compensation is not part of the submission, it should not generate Workers' Comp loss
> requirements, warnings, or remediation tasks."

Source screenshot: the package **BEST SOLUTIONS** panel - Loss History 40%,
Structural Completeness 72% (FEIN / Tax ID), Narrative Quality 75% reading
*"Narrative includes Account Overview, Operations Description, Years in Business,
Management Experience (+5 more), but does not include Employee / Payroll Context,
**WC Payroll / Class Code Context, EMOD / XMOD Information**"*, plus the matching
producer recommendation card ("up to +2 pts", Submit / Dismiss).

### Which half of that screenshot is SYS-04

The Loss History 40 row in the same screenshot is **SYS-02's** item ("Loss History
remains at 40 even when 'Check if none' is correctly populated") - a separate P0 in the
same handoff. The WC-specific content in that screenshot is the **Narrative Quality**
row and its card. SYS-04 is therefore read as: *the WC-specific asks must not be
generated on a non-WC package.* **Confirm with owner** - see "Open question" below.

### Confirmed in code - the root cause

`sqs_service.NARRATIVE_COMPONENT_LABELS` is a **fixed 12-component set**, and
`_calculate_narrative_quality` scores against it **unconditionally**:

    component_pct = present_count / total_count * 100     # total_count is ALWAYS 12

Three of the twelve are line-specific, and two of those are Workers' Comp **only** -
verified against their own signal vocabulary in `_NARRATIVE_SCORE_SIGNALS`:

| Component key | Label on screen | Vocabulary it scans for | Line |
|---|---|---|---|
| `growth_trends` | WC Payroll / Class Code Context | "wc class code", "payroll by class", "ncci class", "workers comp payroll" | **WC only** |
| `target_markets` | EMOD / XMOD Information | "experience modifier", "e-mod", "x-mod", "ncci mod", "rating bureau" | **WC only** |
| `employee_practices` | Employee / Payroll Context | "employees", "workforce", "hiring", "training", "full-time" | general - GL rates on payroll too. **NOT in scope.** |

On a package with no Workers' Comp those two can never be present, so:

1. the narrative pillar loses **2/12 of its component half permanently** (9/12 = 75%
   instead of 9/10 = 90%) - the client's exact 75%;
2. `_narrative_gap_message` prints both WC labels in the "does not include" sentence;
3. that same sentence is emitted as a producer **recommendation card** with a Submit
   control - i.e. a remediation task for a line that is not in the submission.

Both emit sites read the one function, so both inherit it:
- package: `calculate_package_sqs` -> `_miss_by_pillar["narrative_quality"]` -> `top_recs` (sqs_service.py:5296, 5307)
- per form: `calculate_sqs` -> `rec_narrative_components` (sqs_service.py:6771-6786)

### The gate ALREADY EXISTS one door over - and the scorer does not use it

`arq_service._maybe_inject_narrative_enrichment_questions` (arq_service.py:1796) has
carried this exact rule since it shipped:

    _WC_ONLY_COMPS = frozenset({"growth_trends", "target_markets"})
    has_wc = bool(flags.get("has_workers_comp"))
    for comp in _NARRATIVE_ENRICHMENT_ORDER:
        if comp in _WC_ONLY_COMPS and not has_wc:
            continue

So the **questionnaire** already refuses to ask a non-WC account for its X-Mod, while
the **scorer** deducts for the same missing answer and the **recommendation card** asks
the producer for it. Two places decide "does this WC topic apply", they disagree, and
the one that reaches the screen has no gate at all. Principle 1 (one canonical fact,
one reading) violated in the same shape as C4-S / H3-D.

Everywhere else this rule is already honoured: `coverage_evidence.wc_xmod_status`,
`wc_officer_treatment_status` and `wc_payroll_period_status` all open with
`if not _flag(flags, "has_workers_comp"): return STATUS_NOT_APPLICABLE`; the exposure
pillar's WC block is inside `if flags.get("has_workers_comp")`; C3 3.14 already removed
the WC fields from Structural Tier 2 for this very reason (*"a GL-only submission is no
longer marked down for Workers Comp data it can never have"*). **The narrative pillar
was the one that never got the treatment.**

### The spec conflict, stated out loud

`SQS_Scoring_Specification.docx.pdf` section 3.6 says verbatim:
*"Component coverage % = components present / 12 x 100 - Twelve components"*, and lists
"WC Payroll & Class Code Context" and "EMOD / XMOD Information" among them. SYS-04
changes that denominator. `v1-core-principles.md` DOCUMENT PRECEDENCE covers it - the V1
plan / this handoff outrank the older SQS spec - but it must be recorded, not slipped in.

### THE TRAP - do not use `coverage_flag_supported` as the gate

`coverage_evidence.coverage_flag_supported("has_workers_comp", facts, form_ids)` looks
like the right door and is **not**. It is a DEMOTION guard - "is there still ANY positive
evidence, so we may keep a flag that is already true". Its evidence set includes
`_EXTRA_LINE_EVIDENCE["workers_comp"] = ("total_payroll", "num_employees")`, so it
returns True for almost every submission that states a payroll or a headcount. Used as a
presence test it would answer "yes, WC applies" on the client's own package and the gate
would never fire.

### Proposed approach

**One door, one place, both halves of the client's sentence.**

1. **New helper in `sqs_service`** (next to the taxonomy it governs), something like
   `applicable_narrative_components(flags, form_ids) -> Dict[str, str]` - the label map
   minus any component whose line is not in the submission. `_WC_ONLY_COMPS` moves here
   and `arq_service` imports it instead of holding its own copy, so the two can never
   drift again.
2. **"In the submission" = active OR intentionally requested** - the client's own words:
   - `flags["has_workers_comp"]` is true (extraction saw WC named / EL / class codes), **OR**
   - a WC section form is selected - `fact_state.lines_applied_for(form_ids)` contains the
     WC family (this is why the flag alone is not enough: selecting ACORD 130 does **not**
     raise `has_workers_comp`, and a producer who selected 130 is applying for WC).
   Unknown / no opinion -> **keep the component** (fail toward asking, never toward a
   silently better score).
3. **Gate inside `_calculate_narrative_quality` only.** It returns the component dict that
   every consumer reads - the gap message, the absent list, `top_recs.missing`, the
   per-form `rec_narrative_components`. Shrinking the dict there fixes the score, the
   sentence and the card in one edit. No call site changes shape.
4. **`employee_practices` stays.** Payroll and headcount are GL/exposure facts too; it is
   not a WC-only ask and removing it would be the fixture-shaped fix, not the class fix.
5. **Generic by construction, not WC-special-cased.** The helper is keyed by
   component -> line, so an Auto-only or Property-only narrative component added later
   inherits the gate for free. Today WC is the only line with components.

### Score impact - D6 applies, Brent sees the numbers first

Scores go **UP** on every non-WC package. Worked from the client's own screenshot:
component half 75% -> 90%, narrative pillar 75 -> ~84, pillar weight 10% (11.1% when
umbrella is N/A) => **package +0.9 to +1.0 point**, and the narrative recommendation
card disappears entirely once the pillar clears the `< 80` emit gate. Small, but it is a
customer-visible number moving, so it is a Brent conversation, not a drive-by.

### A SECOND, INDEPENDENT root cause worth checking on the live session

`extraction_service`'s prompt (extraction_service.py:753) sets the flag on a **mention**,
not a grant:

> `has_workers_comp: true if document mentions workers compensation, WC, payroll by
> class code, experience modification factor, employers liability, or WC class codes.`

**Every ACORD 25 certificate prints a "WORKERS COMPENSATION AND EMPLOYERS LIABILITY"
section header whether or not the row carries a policy**, and the client's package
included a certificate. `apply_declared_absent_downgrades` only turns the flag off when
the document *explicitly denies* the line ("NO COVERAGE") - a blank WC row is neither a
grant nor a denial, so the flag survives. If `has_workers_comp` is True on the client's
session, the narrative gate above alone will not clear the screen. **Needs the live
session facts/flags to confirm which of the two is firing; the mention-vs-grant half is
the same class already recorded in the `form-stamping-mention-vs-grant` memory and in
`fix-form-stamping.md`.**

### Open question for the owner - **ANSWERED 2026-09-05, see "SYS-04 - VERIFICATION ROUND" below**

> **CLOSED.** The client had already answered it in his own triage table: the Loss History
> 40 is **SYS-02**, a separate P0. The WC content is the narrative row. Kept below for the
> reasoning; do not re-raise it. Two further things this section got wrong are corrected in
> the verification round: the proposed gate composition was **refuted**, and the naive
> "shrink the dict" fix is a **silent no-op on three of four return paths**.

SYS-04's observed text says "a Workers' Compensation-related **no-known-losses** issue".
Nothing in the loss-history pillar is line-specific - `calculate_p4_loss_history` is
package-level, there is no per-line loss-run requirement anywhere in the codebase, and
the "No Known Losses (stated in narrative)" string is `sqs_service.py:2665`, emitted
regardless of coverage line. The only WC content in the source screenshot is the
narrative row. **Confirm: is SYS-04 the WC narrative asks (my read), or did the client
see a WC loss requirement on a screen we have not been shown?**

---

## SYS-04 - VERIFICATION ROUND, 2026-09-05

**Still DIAGNOSIS ONLY. No code written.** This section supersedes the "Open question for
the owner" at the end of the diagnosis above and corrects two things that section got
wrong. Method: five parallel probes over the real code, each then handed to an
independent agent whose only job was to REFUTE it. **One of the five was refuted**, and
that refutation is the most valuable thing on this page - the composition it killed would
have shipped a gate that fires on the wrong packages.

### The open question is CLOSED, and it never needed the client

The diagnosis asked: *"is SYS-04 the WC narrative asks, or did the client see a WC loss
requirement on a screen we have not been shown?"*

**Neither. The client had already answered it in his own handoff.** The source PDF files
the two halves of that screenshot as **two separate P0 items**:

| ID | Area | Issue |
|---|---|---|
| SYS-04 | Coverage detection / recommendations | Do not create WC loss issues when WC is not part of the submission |
| **SYS-02** | **SQS scoring / Loss History** | **Loss History remains at 40 even when "Check if none" is correctly populated** |

The `Loss History 40%` row in the screenshot is SYS-02. The WC content is the Narrative
Quality row. He wrote one observation sentence describing one screen; the triage table
underneath it is the authority. **Asking him to disambiguate his own screenshot would have
been asking for something he had already filed.** SYS-02's root cause is now found too -
see the next section.

### THE NAIVE FIX IS A SILENT NO-OP - the single most important finding here

`_calculate_narrative_quality` has **FOUR return paths**, and only ONE of them builds
`components` from the keyword scan. Shrinking the dict at the top of the function does
nothing on the other three, and three union comprehensions **re-expand a shrunk dict back
to 12** with the dropped keys as `False`:

| Site | What it does | Effect on a shrunk dict |
|---|---|---|
| `sqs_service.py:4301` | `empty_components = {k: False for k in NARRATIVE_COMPONENT_LABELS}` | always 12 |
| `:4340-4351` | return path 1 - `components = dict(_prof_present)`; **its own denominator at 4346** | always 12 |
| `:4356-4358` | return path 2 - `dict(empty_components)` | always 12 |
| `:4359` | return path 3 - `empty_components` | always 12 |
| `:4374`, `:4389`, `:4396` | three unions, each re-keyed over `NARRATIVE_COMPONENT_LABELS` | **RE-EXPANDS to 12** |
| `:4400` | `total_count = len(components)` - the real denominator | reads whatever survived |

**So the gate must be applied at every construction site, or once as a final filter
immediately before each return.** A single shrink at the top passes review, passes most
unit tests, and changes nothing on three of four paths. Same shape as the
`fix-the-layer-the-screen-reads` lesson.

Everything the scorer hands OUT is safe: `sqs_service.py:4398-4400` and `:4346` both derive
the denominator from `len(components)` - no literal `12` to edit. Every consumer iterates
the dict or uses `.get()` / `in`; nothing indexes `growth_trends` / `target_markets`; **no
test asserts `len == 12` and no test pins the gap-message text.** The frontend holds a
duplicate 12-entry label map (`AcordModal.jsx:313-327`) and degrades safely - `:205`
returns null for a key the payload does not carry.

### THE FIRST PROPOSED GATE WAS REFUTED - do not build it

The obvious composition - *"WC is present if `lines_applied_for(form_ids)` contains
workers_comp, OR a producer asserted a `wc_` fact, OR a coverage_lines entry grants it"* -
**fails on two of its three steps.**

**Refutation 1 - `lines_applied_for` is not an intent signal, it is the header-identity
table.** `fact_state.lines_applied_for` reads `pdf_service._SECTION_FORM_LINE_PHRASES`,
which answers *"whose policy number goes on this form's header"*. Executed against the real
code:

    lines_applied_for(['ACORD_133'])  ->  frozenset({'workers_comp'})

ACORD 133 is mapped to workers compensation because its TEMPLATE first page really does
read *"WORKERS COMPENSATION INSURANCE PLAN / ASSIGNED RISK SECTION"* - and
`test_every_section_form_maps_to_the_line_its_template_names` pins that and passes today.
But this repo selects and labels 133 as **Builders Risk** everywhere else
(`forms_database/ACORD_133.json` -> `"ACORD 133 - Builders Risk Application"`,
`matching_flags: ["has_builders_risk"]`; `form_service.py:524`; the recommender at
`form_service.py:1566-1596` adds it on builders-risk facts alone). **A builders-risk-only
construction package would make this gate declare WC present** - the exact false-positive
class SYS-04 exists to kill.

**Refutation 2 - `_producer_asserts_family` reads the SOURCE, not the VALUE.**
`pdf_service.py:6109-6118` tests only that a `wc_`-prefixed fact carries
`source in {producer, client_arq, user, human}`. Driven through the real answer path
(`arq_service.py:4211` -> `answer_semantics.build_fact_envelope`), a client typing
**"None"**, **"N/A"**, **"not applicable"** or **"we have no workers comp coverage"**
returns **True in all four cases**. It is a do-not-override guard (its shipped use at
`:6301` returns `_SCHED_SKIP`), never an assertion of presence. Using it as one closes a
feedback loop: the weak `has_workers_comp` flag causes WC questions to be asked, and any
answer - *including an explicit denial* - then hard-asserts presence.

**The trap already recorded still stands:** `coverage_evidence.coverage_flag_supported` is a
DEMOTION guard, not a presence test. Verified live - it returns `True` on a bare
`total_payroll`.

### The gate that survives refutation

Ordered, first match wins. Nothing here is new machinery; it is existing doors put in the
right order.

1. **Human-stated ABSENCE wins over everything.** A `wc_` fact whose
   `fact_state.value_state_of(...)` is `explicit_no` / `not_applicable` -> **ABSENT**.
2. **Human-stated PRESENCE.** A `wc_` fact whose value_state is `present` -> **PRESENT**.
3. **`pdf_service._line_absent_from_package(facts, ("workers compensation", "employers
   liability"))`** -> **ABSENT** (the declared-denial door, census threshold 3).
4. **A `coverage_lines` entry passing BOTH `_line_entry_evidences_policy` AND
   `_entry_matches_line_strict`** -> **PRESENT**.
5. **Form intent, narrowly.** `"ACORD_130" in form_ids` - the one form whose selection is
   unambiguously WC in this repo. **Never `lines_applied_for`.** Label it INTENT, not
   coverage: 130 is an application for a policy that does not yet exist (which is why
   `pdf_service.py:6085` exempts it from WC suppression).
6. **Otherwise UNKNOWN -> keep the components.** Fail toward asking, never toward a
   silently better score (Principle 3, Principle 7).

`flags["has_workers_comp"]` may be a **tiebreak inside step 6 only**. It is a mention test
(see below) and must never be the first question.

**Note on step 4:** `extraction_service._LINE_EVIDENCE_KEYS = ("premium", "limit")`, so a
**limit alone grants**. A certificate WC row printing `E.L. EACH ACCIDENT $1,000,000`
passes `_line_entry_grants_coverage`. `_line_entry_evidences_policy` is the stronger door
(grants AND (premium OR a non-form policy number)) but it still accepts a COI row carrying
a policy number - so it proves *"a WC policy is documented somewhere"*, not *"this
applicant carries WC"*. If that distinction matters for the WC family, require a
**premium** and drop the policy_number branch.

### The mention-vs-grant half is CONFIRMED, not speculative

`extraction_service.py:753` is a bare-mention criterion with no "Do NOT set true" guard,
and two of its six triggers - *"workers compensation"* and *"employers liability"* - are
**preprinted static text on every ACORD 25**, alongside the three E.L. limit labels.
`apply_declared_absent_downgrades` only fires on an explicit denial; executed on a
realistic empty COI WC block it returns `set()`, while `"WORKERS COMPENSATION - NO
COVERAGE"` returns `{'has_workers_comp'}`. **A blank row is silence, and silence is never a
denial.** No other writer demotes the flag.

This is why the gate above is built on line evidence and not on the flag: **it is then
correct whether the flag is right or wrong**, and the fix does not depend on facts about
the client's session that we do not have.

### Score movement - MEASURED, three narrative shapes, D6 applies

Run against the real `_calculate_narrative_quality` with `has_workers_comp: False`:

| Narrative shape | Pillar before | after | delta | package | card `< 80`? |
|---|---|---|---|---|---|
| Thin, GL only | 40 | 40 | **+0** | +0.0 | stays / stays |
| The client's screenshot shape | 79 | 88 | +9 | +0.9 | **YES -> gone** |
| Rich, non-WC | 69 | 78 | +9 | +0.9 | stays / stays |

**The ceiling is +9 on the pillar and +0.9 on the package, and a weak submission does not
move at all** - the `has_narrative_doc` floor of 40 absorbs it. That matters for the Brent
conversation: this cannot inflate a bad package, and it retires the recommendation card
only where the narrative was already good.

### The spec argument - and the honest counter-argument

`SQS_Scoring_Specification.docx.pdf` section 3.6 (p.7) reads verbatim: *"Component coverage
% = components present / 12 x 100 - Twelve components, each present or absent"*, and lists
both WC components. SYS-04 changes that denominator.

**The counter-argument, stated so nobody leans on precedence as if it settles this:**
`v1-core-principles.md:56-60` grants precedence *"where this document conflicts"* and keeps
the SQS spec authoritative *"where this document does not modify an existing scoring
rule"*. SYS-04's own one-liner is about **loss issues and recommendations** and never names
section 3.6, the narrative pillar, or a denominator. Read strictly, changing /12 is
engineering's interpretation, and precedence clause 3 forbids a new scoring rule without
product approval.

**Two things answer it, and both are in the client's own documents:**

1. **The same SQS spec already does exactly this, one pillar over.** Section 3.1: *"The
   three Workers Comp fields drop out of both the missing list and the denominator when the
   submission has no WC coverage, so a complete non-WC submission can reach 100."* We are
   not inventing a rule - we are applying the spec's own existing pattern to the one pillar
   that never received it. C3 3.14 already shipped that treatment for Structural Tier 2.
2. **The handoff's own Core regression gate (PDF p.3)** is broader than the SYS-04
   one-liner: *"inactive coverage lines do not generate requirements."*

**The conservative alternative, named so the choice is deliberate:** suppress the
recommendation card and the ARQ question, leave `/12` intact. That satisfies SYS-04's
literal words with no override, no register entry and no D6 heads-up. **Rejected** - the
client's expected outcome names *"warnings, or remediation tasks"* and the regression gate
names *requirements*; leaving the deduction in place means the number he complained about
does not move, and he files it again. Half a fix is worse than none here.

### What this round did NOT settle

- **ACORD 133's identity** (see the status board row). The repo asserts two contradictory
  identities and an anti-rot test pins the WC one. **Owner decision, not engineering's** -
  Principle 7. Any WC presence door built on `fact_line` / `lines_applied_for` inherits it,
  which is precisely why the gate above uses neither.
- **Three surviving copies of "the twelve"** that a scorer-only fix leaves stale:
  `extraction_service.py:819` (RULE 11, *"For each of the 12 components"* - a **prompt**,
  so editing it forces an `improving-ll.md` update in the same commit and risks a
  `PROMPT_VERSION` bump invalidating the extraction cache - see D-A for the precedent that
  refused exactly that), `extraction_service.py:530-543` (`_EXTRACT_SCHEMA`), and
  `question_classifier.py:343` (a comment). **Leave the extractor emitting all twelve and
  gate in the scorer.**
- **Test-default flip:** most existing tests call `_calculate_narrative_quality` with no
  `flags`, so a flags-driven gate turns ON by default in every one of them. Re-read
  `test_flag_off_default_behaviour_unchanged` and `test_document_classification.py:173-176`
  and re-run the whole suite against the **6077 / 1 / 14** baseline.

### Standing lesson this item earned

**An adversarial pass on your own proposal is worth more than another pass on the bug.**
The diagnosis was right about the defect and wrong about the fix. The composition that
looked obvious - ask the form-selection door and the producer-assertion door - would have
declared WC present on a builders-risk package and on a client who typed "we have no
workers comp coverage". Neither would have been caught by a unit test written from the
same understanding that produced the fix.

---

## SYS-02 - Loss History stays 40 with "Check if none" ticked - THE DIAGNOSIS

**Status: DIAGNOSIS ONLY, no code written.** Date: 2026-09-05. Found while verifying
SYS-04, because both halves of the client's screenshot turned out to be separate P0 items.

### The client's item

> **SYS-02 | P0 - Systemic correction | SQS scoring / Loss History |** *"Loss History
> remains at 40 even when 'Check if none' is correctly populated."*

Related: **BUG-04** (*"Do not force a required loss-row Date of Occurrence when 'Check if
none' is selected"*) is the same control, one screen over.

### Root cause - a MISSING REVERSE MAPPING, not a mismatched key

The chain is correct at every step except one.

| Step | State |
|---|---|
| The control | `LossHistory_NoPriorLossesIndicator_A`, `/Btn`, ACORD 125 (also on 131) |
| The tick | `PDFJsViewer.jsx:355` sends the literal `"Yes"` - a value `attested_true` **does** accept (`_TRUTHY_TOKENS`) |
| The alias | `ACORD_125_alias.json:515` -> `loss_history_no_prior_losses_indicator` - **correct**, and it IS one of the two fact keys the scorer reads |
| **The write-back** | **BROKEN.** `form_routes.py:1944-1966` is the entire fact write-back in `update_pdf`, and it iterates **only** `_ACORD_FIELD_RULES`. All 332 patterns parsed: **none matches any `LossHistory_*` field.** The alias maps are fact-to-form only; nothing reads them in reverse. |
| The re-score | `form_routes.py:2060-2075` immediately re-runs `calculate_sqs(facts=updated_facts, ...)` on facts that never received the checkbox -> **the pillar recomputes to the identical 40** |

So the box is ticked on screen and in the stamped PDF, and the score cannot move. That is
the client's report exactly.

`_user_attested` (`sqs_service.py:2646-2650`) is true from exactly three inputs: the
`no_prior_losses` FLAG, and `attested_true()` on the facts `no_prior_losses` and
`loss_history_no_prior_losses_indicator`. The flag is derived from the second fact
(`extraction_pipeline.py:637-641`), so it contributes nothing the fact does not. **All
three roads run through a fact the producer's tick never reaches.**

### The compounding cause - the box is ALREADY ticked, with no producer edit at all

`pdf_service._derive_no_prior_losses_indicator` (`:7891-7913`, dispatched from
`_deterministic_map` at `:8237`) returns `"Yes"` when `narrative_states_no_losses` is set
**or** `num_claims == 0`. That is precisely the state that scores **40** at
`sqs_service.py:2665` - and `num_claims == 0` is a fourth input the scorer does not read at
all.

**So the default rendering is "box checked, pillar 40" before anyone touches anything.**
`_resolve_no_loss_indicator`'s own docstring (`:9024-9040`) claims the checkbox and the SQS
state are *"impossible to disagree by construction"*. **That claim is false as the client
experiences it:** the box reads `"Yes"` for BOTH the attested state (60) and the
narrative-only state (40), so a ticked box carries no information about which one produced
it. Fix the comment as well as the behaviour.

### Also worth knowing

`loss_history_state.user_attested_no_losses` (`:199-207`) is a **byte-equivalent second
copy** of the same three-input test, living in the module whose own docstring declares
itself *"the ONE owner of every loss-history state decision"* - and
`calculate_p4_loss_history` does not call it, it re-implements it inline at `:2646`. No
drift today. A latent Principle 1 violation, and the cheapest thing to fix while in there.

### CONFIRMED: there is no WC-specific loss rule anywhere

Swept the whole services layer. The loss pillar is entirely **line-blind** - no per-line
loss-run requirement, no WC-gated loss recommendation, and the *"No Known Losses (stated in
narrative)"* string at `sqs_service.py:2665` is emitted regardless of coverage line.
**SYS-04 therefore needs line-awareness ADDED to the narrative pillar; it is not a WC loss
rule to be removed.** This is what makes the SYS-04 / SYS-02 split in the handoff the
correct reading.

### Score impact - D6 applies

Fixing the write-back moves an affected package's Loss History pillar **40 -> 60** (or
**-> 85** on a business of 1-5 years, `BAND_ESTABLISHING`). At the 15% pillar weight that is
**+3.0 to +6.75 points of package SQS** - materially larger than SYS-04's +0.9, and in the
same upward direction. **Tell Brent about both together, with both numbers.**

---

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-AM | **The SYS-04 "open question for the owner" is closed WITHOUT asking the client.** | He had already answered it: his own triage table files the Loss History 40 as **SYS-02**, a separate P0 under "SQS scoring / Loss History", and the WC content as SYS-04 under "Coverage detection / recommendations". One observation sentence described one screen; the table underneath it is the authority. Asking would have been asking for something already supplied. |
| D-AN | **The WC presence gate is built on LINE EVIDENCE, never on `flags["has_workers_comp"]`.** | The flag is a MENTION test (`extraction_service.py:753`) whose triggers are preprinted on every ACORD 25, and no path demotes it on a blank row. Gating on it makes the fix correct only in the world where the flag happens to be right. Gating on evidence makes it correct in both worlds - and removes the need for live session data we do not have. The flag may be a tiebreak in the UNKNOWN branch only. |
| D-AO | **`lines_applied_for` and `_producer_asserts_family` are BOTH refused as presence signals.** | `lines_applied_for(['ACORD_133']) == {'workers_comp'}` - a builders-risk-only package would declare WC present. `_producer_asserts_family` returns True on a client answering "None", "N/A" or "we have no workers comp coverage", because it reads the fact's SOURCE and not its VALUE. Both were in the first proposed composition and both were killed by the adversarial pass, not by a test. |
| D-AP | **ACORD 133's contradictory identity is RECORDED, not patched.** | `_SECTION_FORM_LINE_PHRASES` says workers compensation (from the template's own printed title, pinned by a passing anti-rot test); `forms_database` and `form_service` say Builders Risk. The consequence is live - all 7 `builders_risk_*` facts answer `fact_line == "workers_comp"` and `coverage_flag_supported("has_workers_comp", {"builders_risk_project_cost": ...}, [])` returns True. Which one is wrong is a question about what the FORM is, not about how to gate a pillar. Same class as D-AG (ACORD 160). Principle 7 - surface it, do not improvise. |
| D-AQ | **The narrative denominator changes; the card-only alternative is rejected.** | Suppressing the recommendation and the ARQ question while leaving `/12` intact is spec-clean and needs no override - and it leaves the client's number exactly where it was, so he files it again. His expected outcome names *"warnings, or remediation tasks"* and the regression gate names *requirements*. The override is justified by the SAME spec's section 3.1, which already drops the three WC fields out of the Tier 2 denominator on a non-WC submission; this applies an existing pattern to the pillar that never got it. Recorded here rather than slipped in, per precedence clause 3. |
| D-AR | **The gate is applied at every construction site, never once at the top.** | `_calculate_narrative_quality` has four return paths and three union comprehensions that re-key over `NARRATIVE_COMPONENT_LABELS`. A single shrink at the top is silently re-expanded to 12 on three of four paths - a change that passes review and most unit tests while doing nothing. |

---

---

## SYS-04 - SHIPPED 2026-09-05

**Code written and green. NOT yet live-tested.** Read the two sections above first -
"THE DIAGNOSIS" for the defect, "VERIFICATION ROUND" for the two design mistakes the
adversarial pass killed before any code existed.

### The acceptance criteria, clause by clause

> *"Gate line-specific recommendations and loss requirements on evidence that the line is
> actually active or intentionally requested. If Workers' Compensation is not part of the
> submission, it should not generate Workers' Comp loss requirements, warnings, or
> remediation tasks."*

| Clause | Where it is satisfied |
|---|---|
| gate on evidence the line is **actually active** | `line_presence` steps 2-3: a stated value on the line's own facts, a `coverage_lines` entry evidencing a real policy, the document's own denial or granted-line census |
| ...**or intentionally requested** | `line_presence` step 1: the line's own application form is selected (`ACORD_130`). Decisive, and checked FIRST - you cannot be applying for a coverage that is not part of the submission |
| **recommendations** | `rec_narrative_components` (per form) and `top_recommendations` (package) both read the gated component dict |
| **warnings** | same dict, same function - one edit covers all three symptoms |
| **remediation tasks** | the Submit/Dismiss card is that recommendation; the ARQ question is gated by the same door |
| **loss requirements** | none exist. The loss pillar is line-blind - no per-line loss-run rule anywhere in the codebase. His own triage filed the Loss History 40 as **SYS-02**. |

### What shipped

**1. New leaf module `backend/services/line_presence.py`** - ONE door for *"is this
coverage line part of the submission?"*, answering **PRESENT / ABSENT / UNKNOWN**.

The three-value answer is the whole design. **UNKNOWN is not a failure**; a caller must
treat it as "keep asking" (Principle 3, Principle 7). That is what makes it safe against
document shapes nobody has seen: an input it cannot read returns UNKNOWN and behaviour is
unchanged. **The door can only ever REMOVE an ask on positive evidence. It can never
invent one.**

Resolution order, first match wins:

1. the line's application form is selected -> **PRESENT**
2. a stated value on one of the line's facts, or a `coverage_lines` entry passing
   `_line_entry_evidences_policy` + `_entry_matches_line_strict` -> **PRESENT**
3. a stated absence on one of the line's facts, `_line_absent_from_package`, or an
   explicitly false coverage flag -> **ABSENT**
4. evidence on BOTH sides -> **UNKNOWN** (Principle 4 - never silently resolve)
5. neither -> **UNKNOWN**

**2. `sqs_service.NARRATIVE_COMPONENT_LINES`** - component -> line. Two entries today,
both WC. A component with no entry is GENERAL and always applies, so `employee_practices`
is untouched (payroll and headcount are GL and exposure facts too - dropping it would be
the fixture-shaped fix).

**3. `sqs_service.applicable_narrative_components(facts, flags, form_ids)`** - the label
map minus components whose line is decisively ABSENT. **The returned map IS the
denominator**, so one call fixes the score, the "does not include ..." sentence and the
producer card together.

**4. `sqs_service.session_form_ids(session_data, form_results)`** - tolerant of every
shape the session row uses. Only ever ADDS "intentionally requested" evidence, so a shape
it misses can never drop a component that passing it would keep.

**5. `arq_service` lost its private copy.** `_WC_ONLY_COMPS` is gone; the questionnaire
calls the same door as the scorer, and both call sites now pass form ids.

### THE TRAP THIS FIX ITSELF HAD - one filter would have done nothing

`_calculate_narrative_quality` has **four return paths** and **three union comprehensions**
that re-key over the full label map. A single filter at the top is silently re-expanded
to twelve on three of the four paths. The gate is resolved ONCE into a local `_applicable`
and every construction site funnels through a local `_only_applicable()` helper - the
keyword scan, both `narrative_profile_present_map` reads, the enrichment map, and
`empty_components`.

**Proved by reverting it:** applying the naive top-only fix fails
`test_every_return_path_honours_the_gate`, `test_the_profile_path_denominator_shrinks_too`
and the scorer fuzz invariant - **3 failures**. Disabling the gate entirely fails **10**.

### Measured behaviour - every branch executed, not reasoned about

| Situation | Verdict | Components |
|---|---|---|
| **the reported case** - flag False, no WC anywhere | ABSENT | **10**, score 79 -> **88**, card gone |
| certificate: 3 policies + BLANK WC row, flag **True** | ABSENT | 10 |
| certificate with a REAL WC row (number + premium) | PRESENT | 12 |
| explicit `Workers Compensation - No Coverage` | ABSENT | 10 |
| **builders-risk package with ACORD_133 selected** | ABSENT | 10 |
| ACORD 130 selected, flag False | PRESENT | 12 |
| client answered "N/A" / "not applicable" / "no coverage" | ABSENT | 10 |
| `wc_payroll` stated + flag False (conflict) | UNKNOWN | 12 |
| only 2 granted lines (thin census) | UNKNOWN | 12 |
| flags `{}` / `None` / flag True / flag `"maybe"` | UNKNOWN | 12 |

The certificate row is the important one: **the fix clears the reported screen whether or
not `has_workers_comp` is wrongly true**, because the granted-line census reads a blank WC
row on a document that enumerates three other policies. That is why the gate was built on
line evidence rather than the flag (D-AN).

### Score movement - D6, tell Brent BEFORE he sees it

| | Pillar | Package |
|---|---|---|
| thin narrative, GL only | 40 -> 40 (**+0**) | +0.0 |
| the client's shape | 79 -> 88 (+9) | **+0.9** |
| rich non-WC narrative | 69 -> 78 (+9) | +0.9 |

**Ceiling +9 pillar / +0.9 package, and a weak submission does not move at all** - the
`has_narrative_doc` floor of 40 absorbs it. This cannot inflate a bad package; it retires
the card only where the narrative was already good. Pinned by
`test_fuzz_gating_never_lowers_the_score`.

### Tests - `backend/tests/test_sys04_line_gated_narrative.py` (47)

Written to the user's standing instruction: *"not just for example values but for any sort
of fuzzy data ... that data will be kept changing."*

* **The fail-safe invariants come first.** Nine parametrised cases that must NEVER drop -
  legacy flags dicts, `None` flags, an unrecognised flag value, a true flag, a thin census,
  a conflict, an empty submission.
* **The adversarial cases that killed the first design**, each as a named test: the
  builders-risk / ACORD_133 package, the human who typed "N/A", the blank certificate row,
  a real certificate row, applying for WC.
* **The four-return-path proof**, each path driven by the input that reaches it.
* **Four fuzz sweeps, 1,500 generated shapes each** (6,000 cases per invariant) over a
  value pool of nulls, blanks, negation words, envelopes, wrong types, lists and dicts:
  never raises; never invents a component; only line-bearing components are ever dropped;
  the breakdown keys always equal the denominator; the score stays 0-100; gating never
  LOWERS a score.
* **Anti-rot:** every gated component must name a line `line_presence` describes; and an
  **AST** test (not a text grep - the module must be free to NAME them in prose to explain
  why they are refused) fails the build if `line_presence` ever calls or imports
  `lines_applied_for`, `fact_line`, `coverage_flag_supported`, `_producer_asserts_family`
  or `_line_entry_grants_coverage`.
* **One-door test**, also AST-based: `arq_service` must hold no local `_WC_ONLY_COMPS`
  assignment and must call the shared function.

### Verification

* Full suite `py -m pytest -q -p no:randomly`: **6278 passed / 1 failed / 14 skipped**.
  The one failure is the long-documented `httpx`/`openai`
  `ImportError: cannot import name 'URL' from 'httpx'` - confirmed by re-running that file
  alone. **Zero regressions.**
* Frontend `VITE_API_BASE=https://api.primble.io npx vite build` - clean, built in 1.79s.
* **No frontend change was needed.** `AcordModal.jsx:205` already reads
  `if (!(key in (pkg.narrative_components || {}))) return null;`, so a dropped key renders
  nothing. Its duplicate 12-entry label map is now a superset and degrades correctly.

### HONEST RESIDUE - state these before anyone asks

1. **A long-form negation typed as free text reads as a value.**
   `fact_state.value_state_of` returns `present` for *"we have no workers comp coverage"*
   (it handles "N/A", "none", "no coverage", "not applicable"). That yields PRESENT ->
   components KEPT, which is the **fail-safe** direction - we keep asking rather than
   wrongly suppressing. Widening that vocabulary belongs to `fact_state` /
   `yes_no_lexicon` (SYS-07c owns it), not here, and has its own blast radius.
2. **The extractor still emits all twelve components.** `extraction_service.py:819`
   (RULE 11) and `:530-543` (`_EXTRACT_SCHEMA`) still say twelve, and
   `question_classifier.py:343` still comments twelve. Deliberate: editing RULE 11 is a
   **prompt** change - `improving-ll.md` in the same commit and a `PROMPT_VERSION` bump
   that invalidates every cached extraction (D-A refused exactly that trade). The scorer
   gates; the extractor over-supplies; `_only_applicable` discards the surplus.
3. **`has_workers_comp` is still set on a MENTION.** Not fixed - routed around (D-AN). The
   census closes the reported case regardless, but the flag remains wrong for every other
   reader of it.
4. **ACORD 133 still has two contradictory identities.** Not touched (D-AP). `line_presence`
   is immune by construction and there is an AST test to keep it that way, but
   `fact_equivalence.fact_line("builders_risk_project_cost")` still answers `workers_comp`
   for everything else in the codebase.
5. **Not live-tested.** Everything above is unit-level and measured offline.

### Files touched

| File | Change |
|---|---|
| `backend/services/line_presence.py` | **NEW** - the presence door, `_LINE_PROFILES`, `line_in_submission`, `line_is_absent` |
| `backend/services/sqs_service.py` | `NARRATIVE_COMPONENT_LINES`, `applicable_narrative_components`, `session_form_ids`; `_calculate_narrative_quality` gained `form_ids` and gates at all six construction sites; three call sites pass form ids |
| `backend/services/arq_service.py` | `_WC_ONLY_COMPS` deleted, delegates to the shared door; `form_ids` threaded from both generators |
| `backend/tests/test_sys04_line_gated_narrative.py` | **NEW**, 47 tests |

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-AS | **A new leaf module rather than a function inside `coverage_evidence`.** | `coverage_flag_supported` lives there and is a DEMOTION guard whose evidence set is deliberately permissive; putting a strict presence test beside it invites the next reader to call the wrong one. A separate file with a docstring naming the four refused doors is the cheaper protection. Matches the repo's leaf-module-per-question pattern (`lob_canon`, `loss_history_state`, `fact_comparison`). |
| D-AT | **The coverage flag is read ONLY in the False direction.** | Its unreliability is asymmetric. `True` can come from preprinted certificate text, so it proves nothing. `False` means the model saw none of six WC signals anywhere in the document set - real evidence of absence. Reading only the trustworthy half is what lets the gate fire on the reported case without trusting a flag we know is broken. |
| D-AU | **Conflicting evidence returns UNKNOWN, not a winner.** | Principle 4. A package whose documents grant WC while its flag denies it is a real question, and the caller's UNKNOWN behaviour (keep asking) is exactly the right answer to a question. |
| D-AV | **The extractor keeps emitting twelve components.** | Gating in the scorer is free; gating in the prompt costs a `PROMPT_VERSION` bump that invalidates every cached extraction, for no behavioural gain. D-A is the precedent. The surplus is discarded by `_only_applicable`. |
| D-AW | **The anti-rot tests are AST-based, not text greps.** | The first version of both failed the build on the module's own docstring, which must be free to NAME the contaminated doors in order to explain why they are refused. A test that cannot tell a citation from a call is a test that punishes documentation. |

---

---

## SYS-04 - THE OTHER HALF: THE FLAG ITSELF - SHIPPED 2026-09-05

The narrative gate did **not** satisfy the acceptance criteria on its own. Measured on a
GL+Property roofing contractor carrying **no Workers Comp at all**, with the mention-set
flag wrongly True:

| | flag correct | flag wrong |
|---|---|---|
| Package SQS | 51 | **48** |
| Exposure pillar | 92 | **78** |

The Exposure pillar's WC block, the WC supplemental bucket, the WC questions and the
umbrella Employers Liability warning all read `flags["has_workers_comp"]` directly. So the
client's *"should not generate Workers' Comp ... warnings"* was still being breached in a
pillar SYS-04's first pass never touched.

**Owner's ruling: fix the flag once, not five consumers.** Gating each reader separately
would be five copies of one rule - the defect SYS-04 already is.

### `line_presence.reconcile_line_flags(flags, facts, form_ids)`

Brings the coverage FLAGS into line with the coverage EVIDENCE, in place, both directions:

* **demote** a True flag when the line is decisively ABSENT. **No circularity** -
  `_flag_says_absent` only reads a FALSE flag, so a True flag contributes nothing to its
  own verdict; the denial, the census or a human answer has to carry it alone.
* **restore** a False flag on a decisive PRESENT. **Required, not symmetry for its own
  sake:** `form_routes.update_pdf` only ever demotes, so without this a flag reconciled
  away at extraction time would stay off after the producer selected ACORD 130, and a
  genuine WC application would lose every WC deduction.

UNKNOWN changes nothing. A key the caller never carried is never invented. Never raises.

Wired at two seams: `extraction_pipeline` immediately after
`apply_declared_absent_downgrades` (the text scan reads raw denials; this reads the
structured coverage evidence the scan cannot see), and `form_routes.update_pdf` beside the
existing demote-only block, with the selected form ids.

**Measured after:** the certificate package goes 48 -> **51** and Exposure 78 -> **92**; a
genuine WC package is untouched (`changed == {}`); selecting ACORD 130 restores a dropped
flag.

### Residue #1 closed the right way - an OPTION, not a better sentence reader

The owner's question was *"can we not just give him some options to select from?"* - and
the mechanism already existed (`services/answer_options.py`, 20 facts with curated lists).
`wc_xmod` was the WC field most likely to be answered with a sentence, and it had no list.

The measurement that decided the wording: `fact_state.value_state_of` reads
`"Not applicable - we do not carry workers compensation"` as **present**, while the bare
`"Not applicable"` reads as **not_applicable**. So the option text is chosen to be
something the state reader already understands rather than widening that vocabulary (which
belongs to `fact_state` / `yes_no_lexicon`, with its own blast radius):

| Option | value_state | line verdict |
|---|---|---|
| `Not applicable` | not_applicable | **ABSENT** |
| `No experience modifier has been assigned` | present | PRESENT (WC exists, no mod) |
| `1.00 - neither a credit nor a debit mod` | present | PRESENT |
| `Other` -> free text | as typed | `answer_semantics` as today |

### Verification

Full suite **6290 passed / 1 failed / 14 skipped** - the one failure is the documented
`httpx`/`openai` ImportError. `tests/test_sys04_line_gated_narrative.py` now **55 tests**,
including an idempotence fuzz over 600 shapes and a test that reconciliation never invents
a flag key the caller did not carry.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-AX | **Fix the FLAG once at the seam, not each of the five WC consumers.** | Owner's call. Gating the Exposure pillar, the supplemental bucket, the questions, the cross-form rules and the umbrella EL warning separately is five copies of one rule - literally the shape of the defect being fixed. One reconciliation at the seam makes every downstream reader correct without knowing this module exists. |
| D-AY | **The reconciliation RESTORES as well as demotes.** | `update_pdf` only demotes. Without the restore, a flag reconciled away at extraction time - before any form was selected - would stay off when the producer later applied for that line, and a real WC submission would silently lose every WC deduction. That is a worse failure than the one being fixed. |
| D-AZ | **The absence escape hatch is an OPTION whose text the state reader already parses.** | Measured: "Not applicable - we do not carry workers compensation" reads as a VALUE; bare "Not applicable" reads as not_applicable. Choosing the option wording to fit the existing reader costs one list; widening `fact_state`'s negation vocabulary touches every fact in the product. Fix the question, not the parser. |

---

---

## ACORD 133 - WRONG FORM, WRONG LABEL, WRONG LINE - FIXED 2026-09-05

Found while verifying SYS-04 (it was contaminating the Workers Comp evidence set), recorded
as D-AP, then fixed on the owner's instruction to *"think like an ACORD form expert and do
what is best"*.

### The evidence - the template settles it, nothing else was consulted

`backend/templates/ACORD_133.pdf`, page 1, verbatim:

> **WORKERS COMPENSATION INSURANCE PLAN** / **ASSIGNED RISK SECTION**
> *"THIS FORM ALONG WITH AN ACORD 130 WORKERS COMPENSATION APPLICATION CONSTITUTE AN
> APPLICATION FOR WORKERS COMPENSATION INSURANCE PLAN (ASSIGNED RISK) COVERAGE. THIS FORM
> MUST BE ATTACHED TO AN ACORD 130 FOR SUBMISSION."*

Its schema: **136 fields, 67 prefixed `WorkersCompensation`, ZERO builders-risk fields.**
The only two carrying "Risk" in the name are
`..._ElectsExclusionListOfEmployersTennesseeAssignedRisk...Indicator_A` - still Workers Comp.

**`_SECTION_FORM_LINE_PHRASES` was right all along.** `forms_database/ACORD_133.json`,
`form_service.py` and `fact_registry` were the copies that were wrong. CLAUDE.md contradicted
itself: line 89 said "Builders Risk Section" while line 2157, written during the compliance
pass, says *"ACORD 133 (a workers-comp form)"* - and the 38 disclosure questions that session
found were *prior WC coverage* and *unpaid premium disputes*. **A previous session saw the
truth and nobody reconciled it.**

### It was shipping a wrong form, not just a wrong label

`template_pending=True` is read by **nothing but an admin route** - it does not stop
generation. So a construction project matching builders-risk facts was offered
*"ACORD 133 - Builders Risk Application"* and generation stamped **the Workers Comp Assigned
Risk PDF** for it.

**Nothing was lost by removing that.** There has never been a builders-risk SECTION form in
this product - only this mislabelled one.

### What changed

| File | Change |
|---|---|
| `forms_database/ACORD_133.json` | name / description / `matching_flags` (`has_builders_risk` -> `has_workers_comp`) / `matching_keywords` / `coverage_types` (`property` -> `workers_comp`) |
| `services/form_service.py` | line map "Builders Risk" -> "Workers' Compensation"; the recommender no longer triggers on builders-risk facts and instead offers 133 on assigned-risk / residual-market wording **AND** `has_workers_comp` - a supplement is never offered without its parent line |
| `services/cross_form_validator.py` | the project-value hard stop and the 133-vs-140 duplication warning are re-keyed off the builders-risk EVIDENCE instead of ACORD_133's selection; both messages reworded |
| `services/fact_registry.py` | the seven `builders_risk_*` facts: `forms={"ACORD_133"}` -> `forms=set()` |
| `CLAUDE.md` | the supported-forms list corrected |

### The contamination, measured before and after

| | before | after |
|---|---|---|
| `fact_line("builders_risk_project_cost")` | `"workers_comp"` | **`None`** |
| `coverage_flag_supported("has_workers_comp", {"builders_risk_project_cost": "500000"}, [])` | `True` | **`False`** |
| `_line_evidence_keys("workers_comp")` | 23 keys, 7 of them `builders_risk_*` | **16, none** |

### Three tests were WRONG and were rewritten, not deleted

Each encoded the mislabel. The property under test was preserved in every case, and a new
test pins the corrected behaviour beside it.

1. `test_acord_133_selected_without_cost_still_hard_stops` -> renamed
   `test_builders_risk_evidence_without_cost_still_hard_stops`, now driven by the evidence
   rather than by putting a Workers Comp form in `triggered_ids`. Joined by
   `test_a_workers_comp_form_never_manufactures_a_builders_risk_hard_stop`.
2. + 3. The two "133 is recommended from builders-risk evidence" tests -> one test pinning
   that it is **never** recommended from builders-risk evidence, plus
   `test_133_recommended_on_assigned_risk_workers_comp` (which also pins that assigned-risk
   wording alone, with no WC line, does not trigger it).

Two new tests in `test_sys04_line_gated_narrative.py` read the real template schema and the
real registry so the identity cannot silently drift back.

### A fourth test was wrong for a DIFFERENT reason, and this one is the lesson

`test_v1_beta_exit_20260828.py::test_no_cross_form_rule_demands_wc_information_without_a_wc_gate`
started failing. Its detector collects every string constant in a `_check*` function and
flags the rule if any string over 40 chars names Workers Comp while the rule raises a
scoring issue. **It was tripped by the DOCSTRING explaining why the rule is deliberately not
a Workers Comp rule** - the rule's actual message never mentions WC at all.

`_strings` now excludes the function's own docstring. **This is the THIRD anti-rot test in
one day defeated by its own documentation** (the two in `test_sys04_line_gated_narrative.py`
were rewritten AST-first for the same reason - D-AW). A docstring cannot reach a producer;
the property is what a rule SAYS TO A USER.

**Proved the guard still bites** by stripping a real `has_workers_comp` condition from a
genuine WC rule - it fails immediately.

### Verification

Full suite **6293 passed / 1 failed / 14 skipped** - the one failure is the documented
`httpx`/`openai` ImportError. Frontend build clean.

### OPEN PRODUCT QUESTION FOR BRENT - builders risk now has no section form

Builders risk keeps: the ACORD 125 sections-attached indicator
(`Policy_SectionAttached_InstallationBuildersRiskIndicator`, ticked from `has_builders_risk`),
its extraction facts, and its project-value cross-form hard stop. It has **no section form**,
and never really did. The real ACORD builders-risk section is a different form number that
this product does not ship. **Whether to add one is his call** - Principle 7 says surface it,
do not improvise.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-BA | **The TEMPLATE decides a form's identity; `forms_database` is a label.** | The PDF is the artefact a broker signs. When a JSON description and the document itself disagree, the document wins - and here it was not close: 67 of 136 fields and the printed title. D-AG (ACORD 160) is the same family and is still open because there the question is which form to SHIP, not what the shipped one IS. |
| D-BB | **ACORD 133 is offered only alongside a Workers Comp line.** | Its own template says it "MUST BE ATTACHED TO AN ACORD 130". A supplement recommended on its own is a form a broker cannot submit. |
| D-BC | **The seven builders_risk facts declare `forms=set()` rather than being re-pointed at ACORD 125.** | They have no box on any of the 17 schemas; claiming 125 would be a second false statement in the registry to paper over the first. An empty set is the honest answer and makes `fact_line` return None, which is what killed the WC evidence contamination. |
| D-BD | **The builders-risk cross-form rules were re-keyed, not deleted.** | The spec names ACORD 133 only because that is what this product used to call the form. The underwriting checks it asks for - a project value must be stated, and construction-period values must not double-count completed-property values - are real and now stand on the builders-risk evidence itself. |

---

### SYS-04 LIVE TEST KIT - `sys04_test_data/` (2026-09-05)

    py backend/scripts/make_sys04_test_pdfs.py            # fresh random values
    py backend/scripts/make_sys04_test_pdfs.py --seed N   # reproduce a run

Six PDFs + `README-HOW-TO-TEST.md`, which lists the values THAT run generated.

**Every value is random; only the structure is fixed.** Owner's instruction:
*"test this on any random values not just some example because we don't know what a user
can upload or type."* Applicant, address, FEIN, carriers, NAIC, policy numbers, dates,
premiums, limits, payroll, headcount, class codes and mod are drawn fresh each run. What is
held constant is the only thing under test - **which lines the document evidences, and
how**. A fix that passed by memorising a value fails on the second run. **Run it twice.**

| File | Shape | Expected |
|---|---|---|
| W1 | GL + Property, no WC anywhere | no WC asks, no WC deductions |
| **W2** | **certificate: WC heading + 3 E.L. labels + BLANK row, above 3 real policies** | **same as W1 - the census must read the blank row even though the flag is True** |
| W3 | genuine WC policy, payroll, 3 class codes, mod | **every WC ask PRESENT** - the positive control |
| W4 | no WC; tester selects ACORD 130 by hand | asks absent, then **come back** after selection |
| W5 | schedule printing `Workers Compensation ... NO COVERAGE` | same as W1, by denial not census |
| W6 | p1 construction project, p2 assigned-risk WC | ACORD 133 never offered as "Builders Risk Application"; offered as the WC Assigned Risk section |

**Self-verified twice before shipping.** (1) Each PDF's extracted text was scanned against
the scorer's own `_NARRATIVE_SCORE_SIGNALS`: W1/W2/W4/W6 carry **zero** WC narrative signal
phrases (so they cannot credit `growth_trends` / `target_markets` by accident), W3 carries
six (so the positive control is real), and W5 is the only file that produces
`_lines_declared_absent -> {"has_workers_comp"}`. (2) Plausible extraction output for each
package was driven through the REAL `line_in_submission` / `reconcile_line_flags` /
`_calculate_narrative_quality`:

| case | verdict | components | flag after | narrative |
|---|---|---|---|---|
| W1 | absent | 10 | False | 72 |
| W2 (flag TRUE) | absent | 10 | **False** | 72 |
| W3 (flag TRUE) | present | 12 | True | 64 |
| W4 before ACORD 130 | absent | 10 | False | 72 |
| W4 after ACORD 130 | **present** | 12 | **True** | 64 |
| W5 | absent | 10 | False | 72 |
| W6 p1 (ACORD_133 selected) | absent | 10 | False | 72 |

Every branch of the door is exercised by at least one file, and W3 + W4-after are the two
that fail if the gate over-suppresses.


---

## SYS-04 - LIVE VERIFIED 2026-09-05 (kit seed 573189)

**Four packages run through the real app end to end. SYS-04 is CLOSED.**

### The component count is the proof, and it is arithmetic

| Session | Narrative Components rendered | WC entries | Narrative Quality | The sentence |
|---|---|---|---|---|
| **W1** no WC | **10** | **absent** | 78% | "...(+5 more), but does not include **Management Experience**" |
| **W2** blank certificate WC row | **10** | **absent** | 84% | **no narrative card at all** - the pillar cleared the `< 80` emit gate |
| **W3** genuine WC | **12** | **present** | 79% | "...(+7 more), but does not include **Management Experience**" |
| **W4** WC applied for (ACORD 130 selected) | **12** | **present** | 69% | "...but does not include Management Experience, **WC Payroll / Class Code Context, EMOD / XMOD Information**" |

The two sentences settle it without needing to trust the rendered list. Both name four
components and then a count: W1 says **(+5 more)** = 4 + 5 = **9 present, 1 absent, 10
total**. W3 says **(+7 more)** = 4 + 7 = **11 present, 1 absent, 12 total**. Same document
narrative, same one missing component, **two different denominators**. That is the gate.

### Every branch of the door fired live

* **W1** - the reported case. Flag false, no WC anywhere -> 10 components, WC labels gone
  from the sentence.
* **W2** - THE HARD ONE. A certificate printing the ACORD 25 Workers Comp heading and the
  three E.L. limit labels over a BLANK row. The Data Consistency policy table came back
  with **General Liability, Business Auto and Commercial Umbrella and NO Workers
  Compensation row at all** - so the granted-line census read the blank row exactly as
  designed, and the WC asks stayed gone even though the mention-based flag was on. The
  narrative pillar reached **84%**, above the emit gate, so **the recommendation card
  disappeared entirely** - which is the client's original screenshot, retired.
* **W3** - the positive control. 12 components, and the Positive Signals panel prints
  *"EMOD/XMOD provided"* and *"Payroll breakdown by WC class code provided"*. **The product
  has not simply stopped asking about Workers Comp.**
* **W4** - "intentionally requested". The recommender did **not** offer ACORD 130 on its own
  (correct - no WC evidence); selecting it by hand brought back all three WC asks (class
  codes, X-Mod, officer inclusion/exclusion) and both WC narrative components.

### The flag reconciliation is visible too

Every session prints **`WC Supplemental 100%`** under Exposure Consistency - the 6.4 bucket
charging nothing. On W1/W2 that is the reconciliation demoting a mention-set flag; on W3 it
is the data genuinely being present. Neither is deducting for Workers Comp on a package
that does not carry it, which was the half of the acceptance criteria the narrative gate
could not reach.

### ACORD 133

Not offered anywhere across nine sessions, and the string *"Builders Risk Application"*
appears nowhere in the product. W6's construction project produced no ACORD 133 and no WC
contamination.

### HONEST CAVEAT ON W4

Its Evidence Basis reads `wc payroll: Stated in narrative` - extraction mapped the
"Total Annual Payroll" line under EMPLOYEE INFORMATION onto `wc_payroll`. So step 2 of the
door (a stated value on one of the line's own facts) would have answered PRESENT even
without ACORD 130. The OUTCOME is correct, but W4 is not a clean isolation of the
form-intent clause. The generator should label that field `total_payroll` instead;
recorded rather than quietly re-run.

### KIT ARTEFACTS, not defects

W1's Property Integrity 0% and its COPE hard stop (the fixture states building and BPP
values but no occupancy or construction type); W5's umbrella hard stop (premiums but no
underlying limits); W6's missing revenue / employees / years (page 1 carries no narrative
block). All real behaviour on deliberately thin fixtures.

---

## FOUND LIVE, NOT SYS-04 - THE LOSS-RUN CONFLICT IS A FALSE POSITIVE

**Every one of the nine sessions** printed:

> **Loss History: Conflicting** - attested no losses but loss runs show claims
> **Losses extracted**
> Loss History **40%**, plus a *"Loss history conflict ... reconcile before submission"*
> card worth up to +8 pts.

**Not one of the six test files contains a loss run.** Every narrative states *"the
applicant reports no prior losses or claims in the last five years."*

The RULE is correct. `sqs_service._loss_history_conflict` requires
`no_loss AND (claims > 0 or incurred > 0)`, and
`loss_history_state.asserted_claims` is a careful door that counts a row only on positive
content. **Its INPUT is fabricated.** The regex claim-counter
(`extraction_service` ~:5669) is gated on `doc_type == "loss_run"` and none of these
documents were classified that way, so `num_claims` / `total_incurred` are coming straight
from the extraction model - it is returning a claim count or an incurred amount from a
document that states the opposite. Most likely a premium, a limit or a building value read
as a loss.

**Same class as the `has_workers_comp` mention flag, one fact over:** a correct consumer
fed by an extractor that infers a value the document does not state (Principle 3).

**Impact:** fires on every clean submission, prints a wrong loss-history STATE label, and
occupies a producer card. Bigger than SYS-02's reported case because it hits packages that
did nothing wrong. **Diagnosis needs the session row** - the actual stored `num_claims` /
`total_incurred` / `loss_history` values - not another screenshot.

**Also observed, cosmetic:** ACORD 186's recommendation reason reads *"Contractor
operations detected - supplements GL & WC"* on a package with no Workers Comp, and the
issue cluster *"WC / GL class code alignment"* renders on non-WC submissions carrying only
its GL item (`issue_registry.py:95-96`). Both name Workers Comp on a package that has none
- the exact shape SYS-04 was reported as. Neither moves a score.

---

---

## THE THREE DEFECTS THE LIVE RUN FOUND - SHIPPED 2026-09-05

All three were found BY the SYS-04 live run and none of them is SYS-04. Owner:
*"fix all the remaining bugs."*

### 1. THE LOSS-RUN CONFLICT FIRED ON EVERY CLEAN SUBMISSION

**Nine sessions of nine** printed *"Conflicting - attested no losses but loss runs show
claims"*, the state label *"Losses extracted"*, Loss History **40%** and a producer card
worth up to +8 pts - on documents containing **no loss run at all**, whose narrative read
*"the applicant reports no prior losses or claims in the last five years."*

**The rule was correct and its docstring was already right.** `_loss_history_conflict` has
said since it shipped that it fires when an attestation is contradicted *"by ACTUAL
loss-run claims"* - **and the code never checked a loss run existed.** `num_claims` and
`total_incurred` reach the extraction schema as bare `string or null` entries with **no
guiding rule at all** (`extraction_service` ~:296 / :323), so the model is free to return a
figure read off a premium, a limit or prose. The regex claim-counter that WOULD be
trustworthy is gated on `doc_type == "loss_run"` (~:5669) and never ran on any of these
documents.

**Same class as the `has_workers_comp` mention flag, one fact over:** a correct consumer
fed by an extractor inferring a value the document does not state (Principle 3).

**The fix - `loss_history_state.claims_are_corroborated(facts, has_loss_run_doc)`**, a new
door `_loss_history_conflict` consults after its existing test passes. Corroborated when:
a document was classified a loss run; `loss_run_age_days` is stated (a valuation age is
only derivable from a real loss run, never from prose); the client's own claims TABLE
carries a row with real content; or a claim figure is **not provably model-authored**.

**THE GATE IS DELIBERATELY NARROW, and that was a correction made mid-flight.** The first
cut suppressed on *any* uncorroborated scalar and broke three pinned properties -
`test_the_two_sources_agree_on_the_same_claim` (the scalar and the typed table are two
spellings of one fact and must score alike), `test_r08_conflict_is_created` and
`test_loss_conflict_caps_score_and_recommends_reconcile`. **Those tests were RIGHT.** A
bare scalar carries no provenance, so nothing can be asserted about who supplied it - the
same reasoning `fact_state.human_provenance_facts` already applies. The gate now refuses
only what it can PROVE: every claim figure present is explicitly `source: "ai"` (the shape
`extraction_service` actually writes, verified at :4216 / :4261) and nothing else backs it.
All three tests pass untouched.

`has_loss_run_doc` is threaded from the three call sites that can see document types -
`calculate_p4_loss_history`, `_get_loss_history_state`, and `extraction_pipeline` (which
derives it from `active_docs` inline). `arq_service._maybe_inject_loss_conflict_question`
gained the parameter and its `_lh_has_loss_run` computation **moved above** the call.

**A fuzz test caught a real edge in the fix itself:** `claims_are_corroborated({})`
answered True, because "no model-authored figure seen" is not the same as "corroborated".
An empty package now answers False.

**Scores go UP on every clean submission - D6.** The Loss History pillar stops being held
at the 45 ceiling by a phantom, and the +8 card disappears.

**NOT DONE, and recorded rather than improvised:** the true root cause is that the
extraction prompt gives `num_claims` / `total_incurred` no rule whatsoever. Adding one is a
**prompt** change - `improving-ll.md` in the same commit and a `PROMPT_VERSION` bump that
invalidates every cached extraction (D-A refused exactly that trade). The deterministic
gate is the established pattern for this class (D43 / H1-K).

### 2. A GL-ONLY FINDING RENDERED UNDER A WORKERS COMP HEADING

Live run: a GL + Property contractor with no Workers Comp saw the cluster heading
**"WC / GL class code alignment"** over a single item reading *"GL coverage detected but no
class codes found"*. `issue_registry` mapped both `gl_codes_no_operations` and the legacy
row to a cluster whose TITLE names a line the submission does not carry.

**A cluster title is language, and the client's criterion covers language** - *"it should
not generate Workers' Comp loss requirements, warnings, or remediation tasks"*. The GL-only
code and its legacy row moved to **"GL class code alignment"**;
`wc_gl_class_code_mismatch`, which genuinely compares the two, keeps naming both.

### 3. THE CONTRACTOR FORM'S REASON HARD-CODED WORKERS COMP

`form_service` offered ACORD 186 with `reason_label="Contractor operations detected -
supplements GL & WC"` at **two** sites, on packages with no Workers Comp. Now built from
`flags.get("has_workers_comp")` - it names the GL section always and Workers Comp only when
the line is there.

### Test kit corrections (`make_sys04_test_pdfs.py`)

Three fixture faults the live run exposed, all recorded in the previous section as
artefacts and now fixed:

* **W4 stated a payroll.** *"Total Annual Payroll"* was extracted as `wc_payroll`, so
  `line_presence` answered PRESENT from the FACT and W4 stopped isolating the
  "intentionally requested" clause it exists to test. Replaced with Annual Gross Sales; the
  kit self-check now fails the build if W4 mentions payroll at all.
* **W5 had premiums but no limits**, firing an unrelated umbrella-attachment hard stop that
  capped the package at 60 and drowned the WC denial under test. Underlying limits added.
* **W6 page 1 had no applicant profile**, so revenue / employees / years read as missing.
  A short block added.

### Verification

Suite **6304 passed / 1 failed / 14 skipped** - the one failure is the documented
`httpx`/`openai` ImportError. Frontend build clean. `tests/test_sys04_line_gated_narrative.py`
is now **67 tests**, including the conflict gate's own fuzz sweep and two tests that fail
the build if WC language returns to a GL-only cluster or to the ACORD 186 reason.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-BE | **The loss conflict is gated on evidence, not on the claim figure alone.** | The rule's docstring already said "ACTUAL loss-run claims"; only the code disagreed. Enforcing the word it already used is a correction, not a new rule - so no product approval is owed, unlike a denominator change. |
| D-BF | **The gate refuses only PROVABLY model-authored figures; a bare scalar is left alone.** | Three existing tests pinned the scalar/table parity and they were right - a bare value carries no provenance and inferring "the model wrote this" from its absence would be an inference about an inference. Narrow beats clever: the live defect is fixed and not one pinned property moved. |
| D-BG | **The extraction prompt was NOT changed.** | `num_claims` / `total_incurred` having no rule is the true root cause, and fixing it costs a `PROMPT_VERSION` bump that invalidates every cached extraction for a defect a deterministic gate already closes. D-A is the precedent; D43 / H1-K are the pattern. Recorded as open. |
| D-BH | **A cluster TITLE counts as WC language.** | SYS-04's criterion is about what a non-WC package is SHOWN, and a heading is shown. Splitting the GL-only code out costs one table entry; leaving it would have kept the exact shape the client reported, one layer up from the row that was fixed. |

---

---

## THE LOSS CONFLICT - THE REAL ROOT CAUSE, FOUND IN THE SESSION DATA 2026-09-05

**The first fix was correct and did not clear the screen.** Re-run: W2 went quiet, W1 / W3
/ W4 still printed *"Conflicting - attested no losses but loss runs show claims"*. W2's
silence was a red herring - that document simply yielded no claims at all, so the gate
never ran there.

**No screenshot could show why. The stored session row could**, and this is the third time
on this arc that reading the session beat reasoning about the code (H1-G, the blank
operations boxes, and now this).

### New tool: `backend/scripts/why_is_loss_conflicting.py`

    py backend/scripts/why_is_loss_conflicting.py [N]     # last N sessions, default 6

Read-only. Prints every input `_loss_history_conflict` reads - the attestation flags, each
claim fact with its **source and confidence**, the document types, whether a loss-run doc
is present - then `asserted_claims`, `claims_are_corroborated` and the verdict, so a
"Conflicting" can be traced to the exact fact that produced it.

### What it found, identical on W1, W3 and W4

```
loss_history = [{"date": null, "claim_date": null,
                 "description": "no prior losses or claims in the last five years",
                 "amount": null, "paid": null}]
```

**The extraction model wrote the NO-LOSS SENTENCE INTO THE CLAIMS TABLE AS A ROW.**

`asserted_claims` counted a row on *any* non-blank detail column - and
`_CLAIM_ROW_DETAIL_COLUMNS` includes `description` - so **the sentence saying there are no
claims was counted as a claim**, which then contradicted the attestation it restates.
`claims_are_corroborated` could not help and was never wrong: a typed claims row IS
corroboration, and this looked exactly like one.

Not `num_claims`. Not `total_incurred`. Not provenance. The table.

### The fix - one door, `loss_history_state._row_states_a_claim(row)`

Both readers now ask it, so a row can never count as a claim for one and not the other -
that split is precisely what let the defect survive the first fix.

* money on the row wins outright: a real amount is a claim whatever the description says;
* otherwise a detail column counts only when it is **not a no-loss assertion**, decided by
  `normalization.detect_no_loss_assertion` - the SAME door that already sets the
  `narrative_states_no_losses` flag and ticks `pdf_service`'s "Check if none" box, so the
  three cannot disagree.

**Measured against that detector before trusting it.** Still claims: *"Slip and fall at job
site"*, *"water damage to stockroom"*, *"rear-end collision, no injuries"*, *"No injuries
reported on this claim"*. No longer claims: *"no prior losses or claims in the last five
years"*, *"No Known Losses"*, *"loss-free"*. The suppression is **per ROW, never per
table** - a genuine claim filed beside the boilerplate still raises the conflict.

### Verified against the OWNER'S OWN LIVE SESSIONS, not a fixture

The six stored sessions from the live run were replayed through the fixed code with
`why_is_loss_conflicting.py`. Every one now returns:

    asserted_claims = claims=0 incurred=0.0     _loss_history_conflict = False

Same data, same session rows, fixed verdict. That is the strongest verification available
short of a fresh upload.

### Both gates are kept

`claims_are_corroborated` (the first fix) stays. It closes a different hole - a
model-authored `num_claims` scalar with no loss run behind it - which this row fix does not
touch. Neither is redundant; they gate different inputs to the same rule.

### Verification

Suite **6316 passed / 1 failed / 14 skipped** - the documented `httpx` ImportError.
`tests/test_sys04_line_gated_narrative.py` is now **77 tests**, including the live row shape
verbatim, four real claim descriptions that must survive, three attestation phrasings that
must not, money-beats-description, mixed tables, and an AST test that fails the build if
`asserted_claims` and `claims_are_corroborated` ever stop sharing the row door.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-BI | **A `loss_history` row restating the no-loss attestation is not a claim.** | The model put the sentence in the table; counting it made the attestation contradict itself. Decided by `detect_no_loss_assertion`, the door that already answers this question for the flag and the form checkbox - a fourth opinion would be a fourth thing to drift. |
| D-BJ | **Per ROW, never per table.** | A genuine claim filed beside the boilerplate must still raise the conflict. Suppressing the table would trade a false positive for a false negative, and a hidden real claim is far worse than a visible false one. |
| D-BK | **Both gates stay.** | `claims_are_corroborated` closes the model-authored SCALAR; `_row_states_a_claim` closes the model-authored ROW. Removing either because the other cleared the live screen would leave a hole that the next document shape walks through. |
| D-BL | **Read the session row before theorising.** | The first fix was correct and cleared one session of four. Two rounds of reasoning about provenance would not have found a description column carrying the attestation. Third time on this arc that the stored data beat the argument - hence a committed tool rather than a scratch script. |

---

### LOSS CONFLICT - LIVE CONFIRMED, AND A D6 NUMBER CORRECTED (2026-09-05)

Re-run after `_row_states_a_claim`, W1 and W3, fresh uploads:

| | Loss History panel | Conflict card | Components |
|---|---|---|---|
| W1 | **"Narrative states no losses" / "None stated"** | **gone** | 10 |
| W3 | **"Narrative states no losses" / "None stated"** | **gone** | 12 |

*"Conflicting - attested no losses but loss runs show claims"* and *"Losses extracted"* are
both retired, and the **"Loss history conflict ... reconcile before submission"** card
worth up to +8 pts no longer renders. The remaining *"No Known Losses (stated in
narrative)"* card is correct and expected - it moved from **+1** to **+3 pts** because the
loss-history STATE is no longer `conflicting`.

**CORRECTION TO THIS FILE'S OWN CLAIM.** Earlier entries said the fix makes scores go UP.
On packages of this shape it does **not**, and the number matters for D6:

| Package shape | Loss History before | after |
|---|---|---|
| narrative-only no-loss statement (W1 / W3) | 40 | **40 - no change** |
| the same, WITH real loss runs and a current valuation | 45 *(held at the conflict ceiling)* | **100** |

The 45 conflict ceiling only bites when the package EARNS more than 45, and a
narrative-only attestation earns 40 either way. **So: no movement on thin submissions; up
to +55 on the Loss History pillar (~+8 package points at the 15% weight) on packages that
uploaded real loss runs and were being held at 45 by the phantom row.** Those are exactly
the well-documented submissions, which is the worst possible place to have been wrong.

Tell Brent that pair of numbers, not "scores go up".


---

## SYS-02 + THE PROMPT GUARDS - SHIPPED 2026-09-05

Owner: *"fix all the remaining bugs ... build others cleanly"*, with builders risk (#3)
explicitly excluded as a product decision.

### SYS-02 - "Check if none" now reaches a fact

**The class was MEASURED before the fix was shaped, and it has exactly one member.** Of the
fact keys `sqs_service` reads, precisely **one** has an ACORD box (via the alias maps) and
no `_ACORD_FIELD_RULES` pattern covering it: `loss_history_no_prior_losses_indicator`. So
fixing that one IS the class fix, and
`test_every_scored_fact_with_a_box_can_be_written_back` recomputes the gap set on every run
and fails the build if a second ever appears.

**Why not just add a row to `_ACORD_FIELD_RULES`.** That table is primarily the FACT ->
FORM stamping map; an entry added there to fix a write-back would change what Pass 1
STAMPS. New `pdf_service._FORM_FIELD_WRITEBACK` is deliberately separate, consulted by
`update_pdf` **only when no stamping rule matched**, so nothing that works today changes
route. `test_the_writeback_table_never_shadows_a_stamping_rule` pins the separation.

**A `/Btn` sends "Yes" or "Off", not a word.** "Off" reads as neither true nor false to
`attested_true`, so `normalize_writeback_value` maps it rather than leaving every reader to
guess. **An untick is an explicit No, not a blank** - a blank would read as "never
answered" and silently keep the attested score.

**Measured, the client's literal report:**

| | Loss History |
|---|---|
| before (the tick never reached a fact) | 40 |
| ticked | **60** |
| ticked, business of 1-5 years | **85** |
| unticked (retraction) | back to 40 |

At the 15% pillar weight that is **+3.0 to +6.75 package points** - the largest single
score movement in this whole arc. **D6.**

### The two prompt guards - v17 -> v18

Full accounting in `improving-ll.md` **C84** (required by CLAUDE.md in the same commit).
Summary: `has_workers_comp` changed from a MENTION test to a GRANT test and now names the
certificate-heading case; new **RULE 12b** forbids deriving `num_claims` / `total_incurred`
from a premium, limit, deductible or payroll, and forbids writing the no-loss sentence into
`loss_history` as a row.

**The cache cost is real and was accepted:** `PROMPT_VERSION` / `SCHEMA_VERSION` move to
**v18**, so every cached extraction is invalidated and every existing session re-extracts
at full price on next touch. Cheap here - 0 production users, localhost.

**The deterministic gates stay and remain load-bearing.**
`line_presence.reconcile_line_flags`, `_row_states_a_claim` and `claims_are_corroborated`
do not trust the model at all. A prompt is guidance, not a guarantee (D43's standing
lesson); this reduces the garbage at source so the gates have less to catch, and if the
model ignores it nothing regresses.

### Two existing tests were PINS that asked to be updated, and were

* `test_extraction_schema_carries_the_counts_and_moved_to_v17` - a bare version pin, now
  v18. Its real H3 assertions are unchanged.
* `test_general_liability_and_workers_comp_are_deliberately_left_alone` - its docstring
  read *"If a client ever reports a false GL or WC tick, harden them then - with that
  report as the evidence."* **The evidence arrived.** Split into
  `test_general_liability_is_deliberately_left_alone` (unchanged reasoning, GL still
  untouched) and `test_workers_comp_was_hardened_and_here_is_the_evidence`, which records
  the case the original reasoning missed: the deterministic downgrade scanner only fires on
  an explicit denial, and **a blank certificate row is neither a grant nor a denial**.

### Verification

Suite **6330 passed / 1 failed / 14 skipped** - the documented `httpx` ImportError.
Frontend build clean. `tests/test_sys04_line_gated_narrative.py` is now **93 tests**.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-BM | **The write-back table is SEPARATE from `_ACORD_FIELD_RULES`.** | That table drives Pass 1 stamping too. Fixing a write-back by adding a stamping rule would change what lands on generated forms - a far larger blast radius than the defect. Consulted only when no stamping rule matched, so no existing path changes. |
| D-BN | **The class was measured, and it has one member.** | "Fix the class, not the case" is only meaningful once the class is counted. 105 scored facts, one with a box and no write-back. A test recomputes that set every run so the answer cannot quietly become two. |
| D-BO | **An untick is an explicit No, never a blank.** | A blank reads as "never answered" and would silently keep the attested score after the producer retracted it - a wrong number with a human's fingerprints on it, which is worse than the original defect. |
| D-BP | **The prompt was changed AND the deterministic gates kept.** | The gates are the guarantee; the prompt reduces what they have to catch. Shipping only the prompt would trust a model that has already demonstrated it will write an attestation into a claims table. |
| D-BQ | **The cache invalidation was accepted, not worked around.** | 0 production users and localhost only make it near-free today, and it will never be cheaper. D-A refused the same trade when the prize was smaller and the blast radius larger - the asymmetry is the whole reason this one is a yes. |


---

## SYS-02 - SHIPPED + LIVE-VERIFIED 2026-09-05

> **SYS-02 | P0 | SQS scoring / Loss History |** *"Loss History remains at 40 even when
> 'Check if none' is correctly populated."*

**The client was right about the symptom and the cause was one layer over from where he
pointed. The box WAS correctly populated - by US.**

### Part 1 - the producer's tick never reached a fact

`form_routes.update_pdf` writes an edit back by walking `_ACORD_FIELD_RULES`, and the whole
`LossHistory_*` family is absent from that table. Ticking the box updated the PDF and the
field state and never touched a fact; the re-score that follows recomputed the identical
number.

**The class was MEASURED before the fix was shaped.** Of the fact keys `sqs_service` reads,
exactly **one** has an ACORD box (via the alias maps) and no `_ACORD_FIELD_RULES` pattern
covering it. So the one-row table IS the class fix, and
`test_every_scored_fact_with_a_box_can_be_written_back` recomputes that set every run.

New `pdf_service._FORM_FIELD_WRITEBACK`, deliberately SEPARATE from `_ACORD_FIELD_RULES`
(which also drives Pass 1 stamping - an entry there would change what gets STAMPED), and
consulted by `update_pdf` **only when no stamping rule matched**.

**LIVE-VERIFIED by the owner, all three steps:**

| | Loss History | Package |
|---|---|---|
| pre-ticked (derived) | 40 | 58 |
| unticked | 40 | 58 |
| **re-ticked (a producer edit)** | **60** | **62 earned, held at 60** |

### Part 2 - and the box could not be used as an input, because we had already ticked it

The re-tick only worked because the owner unticked FIRST. On a fresh package the box ships
ticked - so there is nothing to tick, and the producer can never attest.

`_derive_no_prior_losses_indicator` ticked on `narrative_states_no_losses` **or**
`claims == 0`. `_resolve_no_loss_indicator` - a SECOND function deciding the same box -
ticked on the same flag plus a raw-text `detect_no_loss_assertion` scan. **So the form
printed an attestation nobody made, on a document the applicant signs.**

**THE CLIENT HAS RULED ON THIS THREE TIMES, and this was checked before writing any code:**

* `SQS_Scoring_Specification.docx.pdf`, two adjacent lines - *"No known losses, attested by
  the insured **60**"* / *"No known losses, mentioned only in narrative prose **45**"*.
  Two tiers, two numbers, his.
* The 1 Sep handoff's **Core regression gate** - *"a **confirmed** no-loss state updates
  both **form requirements** and Loss History scoring"*. **Impossible to demonstrate while
  we pre-confirm it ourselves** - which is precisely what the owner hit.
* His ACORD 125 document, point 5 (recorded at `v1-20AUG.md:2821`) - *"a narrative 'no known
  losses' must not be treated as verified history"*, with the note that a narrative phrase
  earning the attestation tier was *"still wrong"*.

**So this is not a new rule and did not need Brent** - it is his existing rule, applied to
the side we missed. The SCORE never moved; only what the form prints.

### The fix - `pdf_service.no_loss_attestation_verdict(facts, raw_text="")`

ONE door, both resolvers delegate. `"Yes"` / `"No"` / `None` (leave BLANK), in order:

1. **A HUMAN's answer outranks everything, in BOTH directions.** Without this the
   derivation RE-TICKS the box on the next generation after a producer unticked it - our
   inference silently overwriting a person (D18).
2. Real claim data -> `"No"`. Never attest "none" above a populated claims table.
3. A genuine attestation on file - the indicator fact from an uploaded ACORD, or the
   `no_prior_losses` flag, which `extraction_pipeline` derives from that same fact and
   nothing else (verified at `:652-663`, not narrative-derived).
4. Anything weaker - a narrative mention, a raw-text no-loss phrase, a zero claim count -
   is **None**. The producer is asked by the "No Known Losses" card that already exists.

`claims == 0` is deliberately gone: *"we found no claims"* is not *"they attested none"*
(Principle 3), and **RULE 12b now makes the model emit `"0"` on every no-loss statement**,
so that route would have ticked almost every package - our own prompt fix would have made
this defect worse.

### The false claim is gone too

`_resolve_no_loss_indicator`'s docstring asserted the box and the SQS state were
*"impossible to disagree by construction"*. **They disagreed on screen.** A claim of
impossibility is not a mechanism; delegation to one door is.
`test_the_box_and_the_score_read_the_same_definition` asserts the PROPERTY over the four
states that matter, rather than restating the claim.

### Verified against the owner's OWN live sessions

| session | box prints | Loss History | agree? |
|---|---|---|---|
| W1, producer re-ticked | **Yes** | **60** | yes |
| W1, untouched | **blank** | 40 | yes |
| W2 | **blank** | 40 | yes |

### Verification

Suite **6340 passed / 1 failed / 14 skipped** (the documented `httpx` ImportError).
**Zero regressions - not one existing test depended on a narrative mention ticking the
box.** Frontend build clean. `tests/test_sys04_line_gated_narrative.py` is now **103 tests**.

### D6 - what to tell Brent

**No score moves.** Generated ACORD 125s print that box **blank** until someone confirms,
where they previously printed it ticked off a narrative sentence. That is his own two-tier
rule reaching the form, and it is what makes his Core regression gate satisfiable.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-BR | **A narrative mention never ticks the attestation box.** | The client's own spec prints the two tiers as two lines with two numbers. The scorer already honoured the split; the form did not. Applying an existing client rule to the side we missed is not a new rule, so Principle 7 does not require Brent - he is TOLD, per D6. |
| D-BS | **A human's answer outranks the derivation, in both directions.** | Without it, regenerating re-ticks a box the producer just unticked. An inference silently overwriting a person is worse than the defect being fixed, and D18 already forbids it. |
| D-BT | **`claims == 0` is not an attestation.** | Principle 3, and newly urgent: RULE 12b makes the model emit "0" on every no-loss statement, so our own prompt fix would have turned this route into a near-universal auto-tick. |
| D-BU | **The write-back table is separate from `_ACORD_FIELD_RULES`, and the class was counted first.** | That table drives Pass 1 stamping; fixing a write-back through it would change generated form output. And "fix the class not the case" only means something once the class is counted - it has one member, and a test recomputes the set so it cannot quietly become two. |
| D-BV | **A docstring claiming impossibility was replaced by a mechanism.** | "Impossible to disagree by construction" was written about two functions that both had to be right independently. One door plus a property test is the version that is actually true. |

---

---

## ADVERSARIAL SAFETY SWEEP - 100,000 MESSY SHAPES (2026-09-05)

Owner: *"check this first on random fuzzy data yourself and then tell me what to do so I
should not be embarrassed in front of client."* Fair challenge: every SYS-04 test to that
point used PDFs written in-house - clean text layer, chosen layout, predictable extraction.

**New: `backend/scripts/fuzz_sys04_safety.py`.** It cannot run the extraction model, but it
drives everything downstream against the shapes a messy extraction actually produces:
OCR-mangled line names (*"Workers Compensat1on"*, *"W0rkers Compensation"*, *"WC"*,
*"Workmans Compensation"*), envelopes where scalars are expected, nulls, wrong types,
malformed rows, `"No Coverage"` / `"Statutory"` / `"TBD"` in money columns, missing keys.

### Four SAFETY properties. All zero, at 100,000 iterations.

| | | |
|---|---|---|
| **P1** | WC asks dropped on a package that really carries WC | **0** |
| **P2** | a loss conflict raised without corroborated claims | **0** |
| **P3** | the attestation box printed ticked with no attestation | **0** |
| **P4** | crash, or a component map that grew | **0** |

P1 is the one that matters most: **suppressing WC on a real WC account is worse than the
defect being fixed.** Any WC evidence against a false flag resolves to UNKNOWN and keeps
all twelve components - the conflict branch doing exactly the job it was written for.

### EFFECTIVENESS, reported and never asserted

| population | asks removed | left as today's behaviour |
|---|---|---|
| adversarial garbage (100k) | **60.3%** | 39.7% |
| **realistic well-formed packages** | **83%** | **17%** |

**The 17% is ONE shape**: the model flags WC true **and** the package carries fewer than
three evidenced policies **and** nothing denies WC. A GL-only or GL+Property package with a
stray WC mention. On BOTH real non-WC documents run through v18 the flag came back
**false**, so that shape did not occur - but it is the honest residual and it must be
quoted, not hidden.

**Deliberately NOT closed.** Lowering the three-line census threshold would pick up those
two shapes and would risk suppressing a real WC policy whose row lost its premium and
number in extraction. Miss = the old bug still shows (visible, safe). False suppression =
WC asks vanish from a Workers Comp account (invisible, dangerous). The asymmetry decides
it.

### TWO ORACLE BUGS WERE FOUND, AND THIS IS THE POINT

The first run reported **1,082 P1 failures and 237 P3 failures**. Every one was the
HARNESS, not the product:

* the generator built a granted WC row, then dropped `coverage_lines` from the facts on a
  later coin-flip - the row existed nowhere and the oracle still insisted the package
  carried WC;
* the oracle passed a RAW fact envelope to `_attests_no_loss` while the code unwraps it
  with `_fv`, so every genuine attestation extracted from an uploaded ACORD read as a
  false positive.

Both were reproduced individually before either was touched, and the ORACLE was corrected -
never the code. **An oracle that watches the generator instead of the finished artefact is
not an independent oracle.** `wc_evidence_present(facts, form_ids)` now reads only the
finished package, exactly as the product does.

### Wired into the build

`test_adversarial_safety_sweep` imports the harness and runs 3,000 iterations on every
suite run, asserting all four properties. Suite **6341 passed / 1 failed / 14 skipped**
(the documented `httpx` ImportError). `tests/test_sys04_line_gated_narrative.py`: **104
tests**.

### WHAT IS STILL UNTESTED, stated plainly

**No real insurance document has been run through any of this.** Every PDF was generated
in-house with a clean text layer. The absence census leans on `coverage_lines` extracting
cleanly, and its behaviour on a scanned, OCR-noisy, 271-page package is unknown. The v18
prompt was verified on two documents, once each, and extraction is non-deterministic.

**The single remaining de-risking step is to run ONE of the client's own documents** -
ideally the package behind the original report. Nothing else removes the scan / OCR / scale
unknowns.

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-BW | **Safety is asserted; effectiveness is reported.** | A miss leaves today's behaviour - unfixed, never wrong - so failing the build on it would be asserting a percentage rather than a property. The number is published instead, so nobody has to guess at it in front of the client. |
| D-BX | **The three-line census threshold stays.** | Lowering it would fix two realistic shapes and risk suppressing a real WC policy whose row lost its premium and number in extraction. A visible miss beats an invisible deletion. |
| D-BY | **The oracle was corrected, never the code.** | 1,319 reported failures were the harness's. Reproducing each individually before changing anything is what kept a passing product from being "fixed" into a broken one. |


---

## SYS-04 DEMO PACK - `sys04_demo/` (2026-09-05)

    py backend/scripts/make_sys04_demo.py            # deterministic, rehearsable
    py backend/scripts/make_sys04_demo.py --seed N   # fresh values, same structure

Two PDFs plus `DEMO-SCRIPT.md`. **Not** the `sys04_test_data` kit - that one is
diagnostic and deliberately thin, and it fills the screen with four unrelated but
CORRECT warnings (no producer name, COPE incomplete, no valuation method, no GL class
codes). Brent should not have to look past true warnings to find the one being shown.

### The pair IS the demo

| | |
|---|---|
| **DEMO-A** | complete GL + Property contractor, **no Workers Comp** |
| **DEMO-B** | identical applicant, limits and narrative, **plus a real WC policy** - payroll, three class codes, experience mod, EL limits |

One document can only show the WC asks are ABSENT. It cannot show they are absent for the
RIGHT REASON - a product that had simply stopped asking about Workers Comp looks identical.
**DEMO-B is the half that makes the claim checkable.**

Both are COMPLETE submissions: producer agency + address, NAICS, SIC, GL limits and rating
schedule, building / BPP values, occupancy, construction, year built, roof year, sprinkler,
protection class, hydrant distance, valuation method, AOP deductible, coinsurance.

**Management Experience is omitted on purpose** on both, so the narrative sentence still has
something honest to name. An empty sentence could not distinguish a working gate from a
silenced message.

### THE TRAP THE DEMO'S OWN SELF-CHECK CAUGHT

The first cut headed DEMO-A's GL table **"GL CLASS CODE"**. `"class code"` is a literal
`growth_trends` signal phrase, so it CREDITED the *WC Payroll / Class Code Context*
component on the non-WC file. Measured: `_score_narrative_components` returned
`growth_trends = True` on DEMO-A in both loose and strict mode.

**Consequence if it had shipped: had the gate ever failed to fire, that component would
have read PRESENT, the sentence would not have named it, and the demo would have looked
like a pass FOR THE WRONG REASON** - masking the exact failure it exists to expose. A demo
that cannot fail is not a demo.

Fixed by wording: **"ISO CODE" / "RATING CLASSIFICATION"** state the same thing and match no
signal phrase. Verified: DEMO-A now credits neither WC component, DEMO-B credits both.

### The proof Brent can check himself

Open Narrative Components on each: **10 on DEMO-A, 12 on DEMO-B.** And the sentences print
their own denominators - DEMO-A `(+5 more)` = 4 + 5 = 9 of 10; DEMO-B `(+7 more)` =
4 + 7 = 11 of 12. Same narrative, same one missing component, two denominators. Arithmetic,
not assertion.

`DEMO-SCRIPT.md` carries the click-by-click steps, the expected screens, the line to use
(*"it is not that we stopped asking - DEMO-B shows we still do"*), and the residual to state
BEFORE he finds it (83% of realistic non-WC packages corrected, 17% fall back; a miss never
produces a wrong answer and never hides WC asks from a package that has the line).

### Decision register (continued)

| # | Decision | Reasoning |
|---|---|---|
| D-BZ | **The demo is a PAIR, and the WC half is the important one.** | Absence alone is not evidence of discrimination. Without DEMO-B, a product that had gone silent on Workers Comp would demo identically to a fixed one - and that is the failure mode a sceptical funder should be able to rule out for himself. |
| D-CA | **Demo fixtures are COMPLETE; diagnostic fixtures stay thin.** | Two different jobs. The thin kit finds defects; a screen with four true-but-unrelated warnings buries the finding it is meant to show. Neither should be asked to do the other's work. |
| D-CB | **A demo must be able to FAIL.** | The first draft's own wording would have masked a gate failure. Fixtures get the same adversarial reading as code: ask what the artefact would look like if the fix were broken, and if the answer is "the same", rebuild it. |


### DEMO PACK - FIRST LIVE RUN, AND FOUR FIXTURE FAULTS FIXED (2026-09-05)

**The demo works.** DEMO-A rendered **10** narrative components, DEMO-B **12**, with
DEMO-B's Positive Signals printing *"EMOD/XMOD provided"* and *"Payroll breakdown by WC
class code provided"* and its policy table carrying the Workers Comp line, carrier and
NAIC. Loss History read *"Narrative states no losses / None stated"* on both. Structural
Completeness **100%** on DEMO-A - every key detail in place, which is what a demo fixture
is for.

**Four warnings on those screens were the FIXTURE's fault, not the product's.** Each was
traced to the rule that produced it and fixed in the generator:

| On screen | Cause | Fix |
|---|---|---|
| *"Total Annual Payroll: documents disagree ($4,940,000, $1,976,000)"* | the GL rating table printed TWO exposure rows and extraction read both as the package total | one row, one amount, equal to the stated payroll |
| *"ACORD 101 required: operations description is insufficient"* | `cross_form_validator` needs **>= 4 WORDS** (H1-I changed that rule from characters to words); *"commercial electrical fit-out"* is three | operations are now a full sentence |
| *"Property deductible defined but basis not specified"* | the AOP deductible was stated, `deductible_basis` was not | *"Deductible Basis: Flat dollar amount per occurrence"* added |
| *"RCV selected on a building built in 1978 (48 years old)"* | the advisory fires above 40 years with RCV and a value over $500k (`cross_form_validator:1182-1186`) | `year_built` moved to 2004-2018 |

**The payroll conflict deserves a note.** The product HAS a rule for this - a class-schedule
row states the RATING BASIS for one classification, never the account total
(`_CLASS_SCHEDULE_EXPOSURE_FIELDS`). It could not fire because the table was deliberately
re-headed **"ISO CODE / RATING CLASSIFICATION"** to avoid crediting the WC narrative
component, and that wording is not recognisable as a class schedule. **One demo constraint
broke another.** Resolved by removing the second amount rather than by re-introducing the
signal phrase.

### AND THE DEMO SCRIPT WAS WRONG, corrected before anyone read it to Brent

It promised the *"Narrative includes ... but does not include ..."* sentence on both files,
with the `(+5 more)` / `(+7 more)` arithmetic as the headline proof. **That card does not
render on these files** - it is emitted only below a Narrative Quality of **80**, and both
demos score **90** precisely because they are complete submissions.

The script now leads with the COUNT (10 vs 12), states plainly that the sentence will not
appear and why - *its absence on DEMO-A is itself the point, since the client's original
screenshot HAD that card naming two Workers Comp topics* - and points at the thin
`sys04_test_data` fixtures for anyone who wants the arithmetic visible too.

**Promising a screen that will not appear is how a demo dies in the room.**

| # | Decision | Reasoning |
|---|---|---|
| D-CC | **A demo fixture is debugged against the rules it trips, not "cleaned up".** | Each of the four warnings was traced to the exact check and threshold that produced it before anything was changed. Three were fixture gaps; the fourth revealed that one demo constraint (avoid the WC signal phrase) had broken another (be recognisable as a class schedule). |
| D-CD | **The demo script is verified against a real run, not written from the design.** | It promised a recommendation card that a COMPLETE submission never renders. The design said it would be there; the run said otherwise, and the run wins. |


---

## SYS-02 - ACCEPTANCE AUDIT AGAINST THE CLIENT'S OWN WORDING, AND THE LAST CLAUSE CLOSED (2026-09-05)

The client's card was read clause by clause rather than from memory. **Eight of nine met
before this session; one gap, and it was the clause he wrote most explicitly.**

### Met

| His words | Where |
|---|---|
| *"Treat a confirmed 'no known losses' / 'check if none' state as affirmative loss-history information rather than missing data"* | the write-back: tick -> **40 -> 60** (85 in the 1-5 year band) |
| *"recalculate the Loss History pillar using the approved rubric"* | Brent's own years-in-business ladder, untouched |
| *"A client-confirmed no-loss answer is not equivalent to carrier loss runs"* | confirmed 60 vs loss runs up to 100 |
| *"must still update the category state"* | `narrative_states_no_losses` -> `user_states_no_losses` |
| *"related recommendations"* | the card changes from *"stated in narrative - confirm with the insured"* to *"attested by user - attach loss runs to fully confirm"* |
| *"and form scoring"* | owner-verified live, 40 -> 60 -> 40 |
| observed *"total losses at $0"* | that box is right-or-blank (`_loss_history_total_from_schedule`); it never manufactures a `$0` |
| observed *"the box selected"* with nobody confirming | it no longer auto-ticks from a narrative sentence |

### THE GAP - his third evidence state was collapsed

> *"a narrative stating no losses, a client confirming no losses, and **carrier loss runs
> not being provided** are different evidence states and **should not be collapsed into the
> same result**."*

Measured:

| his named state | score | label shown |
|---|---|---|
| narrative states no losses | 40 | "None stated" |
| client confirms no losses | 60 | "None corroborated" |
| **carrier loss runs not provided** | 25 | **"Unknown"** |
| *nothing at all* | 25 | **"Unknown"** |

The first two were already distinct. The third fell into the `unknown` bucket **alongside
"we know nothing"** - and because the panel prints the internal label directly above the
client bucket, it rendered as two contradicting lines:

    No loss runs available          <- the internal label, correct
    Unknown                         <- the bucket, denying it

### Fixed as a CLASS - three states, not the one he named

An enumeration of all fifteen internal states against their buckets found **three** that
asserted "Unknown" over a label describing something known. Only `no_information` belongs
there.

| internal state | was | now |
|---|---|---|
| `no_loss_runs_available` | Unknown | **"Loss runs not provided"** (his wording) |
| `loss_runs_pending` | Unknown | **"Loss runs requested"** |
| `prior_claims_exist` | Unknown | **"Claims known - loss runs not provided"** |

A requested loss run and a known prior claim are stated ANSWERS. Leaving those two while
fixing only the reported one would have been the fixture-shaped fix.

**The original five client-approved words are untouched** and pinned by
`test_the_original_five_client_words_are_untouched`. Widening the vocabulary has precedent
in the same table - `not_applicable` was added for a verified new venture on exactly this
reasoning, that none of the five could truthfully describe the state.

**No score moves.** Display only; the states, the rubric and the scores are unchanged, and
`test_relabelling_moved_no_score` pins 40 / 60 / 25.

### The anti-rot guard is the class, not the case

`test_no_state_is_labelled_unknown_while_its_own_label_states_a_fact` walks every internal
state and fails the build if any state other than `no_information` renders as "Unknown".
The panel prints both lines together, so a bucket contradicting its own label is visible to
a producer, not just wrong in a table.

### NOT ours to change

At 5+ years in business, *"no loss runs available"* and *"nothing at all"* both score **25**.
That is **Brent's own ruling** (Q11, 2026-08-24: *"we can't treat 'N/A' as '0' ... check
against the number of years in business"*), shipped as the years-in-business ladder. The
LABEL collapse was our defect; the SCORE is his decision. If he wants them scored apart he
has to say so - flag it, do not improvise it.

### Verification

Suite **6346 passed / 1 failed / 14 skipped** (the documented `httpx` ImportError).
Frontend build clean. `tests/test_sys04_line_gated_narrative.py`: **109 tests**.

| # | Decision | Reasoning |
|---|---|---|
| D-CE | **The client's five-word vocabulary was widened, not reinterpreted.** | The five he approved still read exactly as he approved them, pinned by a test. Three states that no bucket could truthfully describe got honest labels instead - the same reasoning that already added `not_applicable`. |
| D-CF | **All three contradicting states were fixed, not only the one reported.** | He named one; the enumeration found three with the identical defect. His stated principle is about collapsing DIFFERENT states, not about that one row. |
| D-CG | **The 25-vs-25 score collapse is left alone and flagged.** | Brent ruled it. The label was ours to fix; the rubric is his to change, and improvising a new score here is exactly what Principle 7 forbids. |


### SYS-02 - OWNER-VERIFIED LIVE, THE FULL LOOP (2026-09-05)

The box **shipped blank** (the auto-tick from a narrative sentence is gone), the producer
ticked it, and everything downstream moved:

| | box blank | after ticking |
|---|---|---|
| Loss History pillar | **40** | **60** |
| category status | **Limited** | **Partial** |
| package | 58 | **62 earned**, held at 60 by the unrelated COPE hard stop |

**Both halves of the defect are demonstrated by one click.** Before this arc the box arrived
pre-ticked from a narrative mention, so there was nothing to tick and the pillar sat at the
missing-data baseline - the client's report exactly. Now the box is an INPUT: blank until
someone confirms, and confirming is affirmative loss-history information that recalculates
the pillar, moves the category state and updates the form score.

The package rising to 62 and being held at 60 by the COPE hard stop is correct and
unrelated - the W1 fixture is deliberately missing occupancy and construction type.

**The evidence state and the recommendation moved with it** - the two clauses hardest to
demonstrate any other way:

| | box blank | after ticking |
|---|---|---|
| evidence state | `Narrative states no losses` / `None stated` | **`User states No Known Losses`** / **`None corroborated`** |
| recommendation | *"No Known Losses (stated in narrative) - **confirm with the insured**, or attach loss runs..."* | *"No Known Losses (**attested by user**) - attach loss runs or a signed no-known-loss letter to fully confirm"* |
| remaining gain offered | +3 pts | **+6 pts** |

So on one screen the client can see his own sentence satisfied - *"a narrative stating no
losses, a client confirming no losses, and carrier loss runs not being provided are
different evidence states"* - with the first two states rendered distinctly and the third
now carrying its own label since the bucket fix above.

**SYS-04 regression holds in the same session:** Narrative Components still **10**, neither
WC entry present.

**Both SYS-02 and SYS-04 now meet every clause the client wrote. Neither is CLOSED until he
retests** - that is his call, and the one remaining unknown for both is that no real client
document has been through any of this.


---

## SYS-09 - Separate the client contact from the brokerage contact - SHIPPED 2026-09-05

**Read this before touching `_ROLE_BLIND_FACTS`, `merge_facts`' primary loop, or either
party-contact resolver in `pdf_service`.** The obvious fix for this item is a REGRESSION
on its own, and the reason is arithmetic, not opinion - see "The trap" below.

### The client's item

*"Separate client contact and brokerage contact when populating ACORD forms"* (P0,
systemic). Two manifestations, opposite directions, one class:

- **(A) The Data Consistency picker** offered the BROKERAGE's contact person
  (`Terri Wroblewski`, from a COI issued by CRS Insurance Brokerage) as a candidate for
  the APPLICANT's `contact_name`, conflicting against the real one from the applicant's
  own submission narrative.
- **(B) The generated ACORD 125** printed the correct agency NAME above the APPLICANT's
  contact person, phone, email and street address (`Dana Whitcomb` / Northgate, live run
  2026-09-05 on the SYS-07 kit). Recorded at line 2820 of this file, then deliberately
  deferred - *"expected, do not report"*. It was never diagnosed until now.

### Three root causes, each confirmed by reading the code, not by analogy

1. **`fact_comparison._ROLE_BLIND_FACTS["certificate"]` never listed the contact fields.**
   Structural, not stylistic: **ACORD 25 has exactly three contact fields and all three are
   `Producer_ContactPerson_*`; its `NamedInsured` block carries a name and a mailing address
   and nothing else.** There is no box on a certificate in which an applicant's contact
   person can be printed, so every contact person a COI names is the PRODUCER'S.
2. **`merge_facts` enforced document ROLE on only half the merge.** The gate filters
   `non_primary` (`extraction_service.py:8674-8709`); the loop underneath then wrote
   `mf[k] = v` for every primary fact, consulting nothing. The file's own comment, twenty
   lines above, names this exact defect class: *"A rule enforced in one place and not
   another is the defect class this codebase keeps paying for."*
3. **`_resolve_applicant_contact` had no producer-side mirror, and `_resolve_producer_mailing`
   stepped aside on absence.** The applicant guard shipped 2026-08-10 off three live runs of
   other parties' contacts landing in the insured's block. The identical defect in the other
   direction ran unguarded, and the producer address block's own contract said it out loud -
   *"No fact - the resolver steps aside and gap fill keeps its coverage."*

### THE TRAP - why the obvious fix is a regression on its own

Blinding the certificate to `contact_name` **without** root cause 2 makes the reported case
WORSE, and the arithmetic proves it:

- `_DOC_TYPE_PRIORITY` ranks `certificate` **7th** and `narrative` **21st**, and
  `select_primary_truth` picks strictly by that order. The client's own package - a COI plus
  a submission narrative - therefore makes **the COI the PRIMARY document**.
- The PICKER filters every active document, primary included
  (`underwriting_consistency.py:2083`). The MERGE did not.
- So blinding alone removes the certificate's candidate from the picker - **the conflict row
  disappears** - while its wrong value still wins the merge and still stamps, and confirming
  in that picker (`extraction_pipeline.py:796-798`) was the producer's only way to correct it.

**Silencing the one screen a human could have caught it on, while the wrong name ships.**
Both halves go together or neither does. Pinned by
`test_THE_PROOF_THE_GATE_BITES_a_sighted_primary_still_overwrites`.

### What shipped

- **`fact_comparison.py`** - `contact_name` / `contact_phone` / `contact_email` added to the
  `certificate` blind set. `producer_*` deliberately NOT added: naming the issuing agency is
  what a certificate is FOR, and blinding it would break the ACORD 25 roster.
- **`extraction_service.merge_facts`** - the primary loop now consults the same role gate.
  **NARROW BY CONSTRUCTION:** a role-blind primary may not OVERWRITE a sighted witness, but
  is still free to be the SOLE source. So it can only ever swap one document's value for
  another's - it can never blank a fact, and on a single-document package it does nothing.
- **`pdf_service._resolve_producer_contact`** (new) - the mirror of `_resolve_applicant_contact`.
  A real producer contact fact -> step aside; none at all -> the family is an authoritative
  blank and the model is never asked. `\w+_[A-N]` because the family differs per form
  (ACORD 130 adds `CellPhoneNumber`, 133 carries an `EmailAddress` on row C) - 16 fields
  across 125/130/133/25/28.
- **`pdf_service._resolve_producer_mailing`** - absence is now an owned blank instead of a
  step-aside. It was already registered; a resolver that steps aside on absence owns the easy
  case and abandons the one that bites.

### The wider rule was deliberately NOT taken

Blinding the primary **outright** (so a lone loss run stops stating the policy it is claiming
against) is the doctrinally clean version and is **not** in this change. It blanks sole-source
facts on certificate-primary and loss-run-primary packages, which moves scores. That is
Brent's call under D6, not a side effect of a contact fix.

### Three existing tests failed. Each was judged on its own merits, none was deleted

| Test | Verdict |
|---|---|
| `test_producer_mailing_without_the_fact_keeps_llm_coverage` | **The TEST was wrong.** It pinned the exact contract the live run disproved - "keep the LLM's coverage" - whose only measured output was the applicant's address in the producer block. Reversed and renamed, with the reason in its docstring. |
| `test_producer_address_no_longer_pulls_named_insured_address` | **Stale sentinel, intent strengthened.** It asserted `== "UNMATCHED"` ("ask the model"); the answer is now an owned blank. Rewritten to assert the GUARANTEE (the producer box never carries the insured's address) rather than the mechanism. |
| `test_the_primary_loop_does_not_blindly_overwrite_list_fields` | **The CODE was right; the test was brittle.** It sliced 1,800 characters from a comment marker, so it measured comment length, not behaviour. Re-anchored on the loop itself. |

`test_authoritative_blank_contract.py`'s ledger moved **117 -> 125 of 548 (22.8%)**, +3
producer contact and +5 producer mailing; the 25% ceiling was NOT touched. The non-grid
scalar cap went **29 -> 37** (ceiling 30 -> 40) - raised in the open, with the cheap way out
refused: both blocks could have been declared "grids" to keep the number flat, but a grid
here means a REPEATING structure (`_A.._N`) and each of these is one party's single block
split across component boxes. The prose in that file had also drifted (it said 113/25 while
the code stood at 117/29); both numbers are now restated from a measured run.

### Verification

Suite **6376 passed / 1 failed / 14 skipped** - the one failure is the documented
`httpx` ImportError (`test_arq_acord125_missing_only`), identical to the baseline taken
before any edit. Zero regressions. New file
`tests/test_sys09_contact_party_separation.py` (**28 tests**), driving the real
`merge_facts`, the real `select_primary_truth` and the real stamper routing, with the
client's own values and the ACORD 25 schema re-read at test time so the blind entry can
never stand on a stale premise.

### Score movement - D6 applies, tell Brent BEFORE he sees it

`contact_name` / `contact_phone` / `contact_email` are `TIER1_CONTACT` (`sqs_service.py:544`)
and feed the package Tier 1 check, the ACORD 125 checklist and fill rate. The code's own
comment measures the size of one such swing: *"answering `contact_name` moved ACORD 125 from
63 to 68"* (`sqs_service.py:590`).

- On a package where a certificate previously supplied or won `contact_name`, the merged value
  can now change on regeneration - **scores can move in either direction.**
- `_resolve_producer_contact` and the producer mailing blank remove up to 8 previously
  (wrongly) filled boxes from the filled set, which changes `confidence_fill_rate`'s weighted
  average on any form that had the defect. **Direction: the score reflects a form that is now
  honestly blank rather than confidently wrong.**

Neither is measured on a live package yet. **Not shipped to a client-visible run until Brent
has the numbers.**

### Still open after this

1. **Manifestation A when the certificate is the ONLY document.** Nothing else supplies the
   value, the narrow guard lets a sole source through, and a COI's contact person is the
   producer's. Closing it means the wider rule above - Brent's call.
2. **A within-document entity mislabel is still uncatchable.** If extraction writes the wrong
   person's name INTO `producer_contact_name` itself, every guard here passes: the box reads
   its own party's fact. RULE 15 is prompt text with no code enforcement, and there is no
   second document to cross-check against. This is the residual LLM risk, not a code bug.
3. **The address bleed guard remains partial.** `_drop_third_party_address_bleed` inspects
   only `LineOne`, compares only against `mailing_address` (never `physical_address`), and
   only touches gap-filled values. The owned blank now covers the absent-fact case, which is
   the one that was live; a bleed with a producer_address fact PRESENT is still only
   partially guarded. **The LineTwo widening proposed during review was NOT taken** - its own
   author called the root cause "plausible", and it had no confirming session data.

| # | Decision | Reasoning |
|---|---|---|
| D-CH | **The role-blind entry and the primary-loop gate ship together, never separately.** | Alone, the blind entry silences the picker while the wrong value still stamps - strictly worse than the reported bug. Measured from `_DOC_TYPE_PRIORITY`, not argued. |
| D-CI | **The primary gate is narrow: it may not overwrite a sighted witness, but may still be a sole source.** | It can then only ever swap one document's value for another's. It cannot blank a fact, so it cannot cost data on any package, and single-document sessions are untouched. |
| D-CJ | **Only the applicant's contact fields are blinded on a certificate; producer identity is not.** | ACORD 25's own schema: three contact fields, all `Producer_ContactPerson_*`, and no applicant contact box exists. The defect is the applicant's box being filled from the producer block, not the producer block existing. |
| D-CK | **The wider "blind the primary outright" rule is deferred to Brent.** | It blanks sole-source facts on certificate- and loss-run-primary packages, which moves scores. D6 - not a side effect of a contact fix. |
| D-CL | **The LineTwo address-guard widening was refused.** | Proposed during review on an unconfirmed root cause. The owned blank addresses the case that was actually measured live; guessing at the other one adds a guard nobody can prove bites. |
| D-CM | **The scalar ceiling was raised in the open rather than dodged.** | Both new blocks could have been reclassified as "grids" to keep the count flat. A grid means a repeating row structure; these are single blocks split across boxes. Counted honestly, ceiling moved, arithmetic stated. |

---

## TWO DEFECTS THE SYS-09 LIVE RUN EXPOSED - SHIPPED 2026-09-05

Found on the first live run of the SYS-09 kit. **Neither is SYS-09**, and neither
was caused by the SYS-09 fix - both were sitting in the generated ACORD 125.

### 1. The certificate holder printed as an Other Named Insured

`Kestrel Terminal Authority` - the CERTIFICATE HOLDER - came out of
`additional_named_insureds` and stamped onto ACORD 125 as **`NAME (Other Named
Insured)`** with its own address. An Other Named Insured shares the policy, so
the form asserted coverage for a party the policy does not name. Same family as
SYS-09 (a third party landing in the applicant's block), different party pair.

**An ADDITIONAL INSURED IS NOT AN ADDITIONAL NAMED INSURED.** The document said
*"certificate holder is an additional insured with respect to operations"* -
the single most common sentence on a COI. That grants limited status by
endorsement; it never makes the holder a named insured. So the drop is correct
even when the document says exactly that.

**Nothing is lost by dropping rather than re-routing:** `AdditionalInsured_
FullName` appears in **NO** ACORD schema (verified across all 17), so the only
live consumer of this fact is the Named Insured roster, and the holder already
has its own extraction field (`certificate_holder_name`).

### THE REAL ROOT CAUSE WAS THE SEAM, AND IT IS THE SAME ONE SYS-09 HAD

`_drop_transaction_party_rows` **already existed and was already correct.** It
has always known how to drop the producer, the carrier and their addresses out
of person and address schedules. It was simply **unreachable from the primary
document**: it runs inside `_merge_list_fields`, which `merge_facts` calls on
the NON-PRIMARY documents only, and the union underneath then merged the
primary's uncleaned list straight back in. On a **single-document session it
never ran at all.**

That is the identical shape as the SYS-09 defect fixed hours earlier in the same
function, one loop apart - a rule enforced on the non-primary branch and not the
primary one. **Measured, not reasoned:** the first fix (adding a name-list
branch to the helper) passed every unit test and changed nothing on the form,
which is the trap this codebase documents as *"an offline probe proves the
FUNCTION, never the SEAM."*

The filter now runs over the FINAL merged list for **every** key it knows -
`auto_drivers`, `wc_officers`, `property_locations`, `additional_named_insureds`
- so the wider class is closed, not just the reported key. Removal-only and
idempotent: re-running it on an already-filtered list is a no-op, and it can
never add a row. **Verified as a side effect: the producer's own office is now
dropped from the premises schedule when it arrives on the primary document,
which it never was before.**

### 2. A refrigerated warehouse was scored as a RESTAURANT

`infer_lob` tested **bare substrings**: `any(w in desc for w in ["restaurant",
"food", ...])`. The kit's operations line reads *"cold storage of packaged FOOD
products"*, so the account classified as a restaurant, and
`LOB_RULES["restaurant"]` then charged it for `occupancy_type` - a field a
warehouse can never have. The label is also **displayed** beside the Total
Package Score, so the client sees it.

Every list had the same defect: `"app"` matched apparel and appliance, `"tech"`
matched technician and geotechnical, `"platform"` matched a platform trailer,
`"delivery"` matched the delivery of janitorial services.

**Three structural conditions now, and all three are load-bearing:**
1. **Word boundaries** - `"food products"` no longer answers a question about
   restaurants.
2. **Unambiguous evidence only** - phrases from more than one bucket resolve to
   `generic`. That disposes of *"restaurant construction contractor"*.
3. **Whose trade is it** - a phrase governed by a customer clause is somebody
   else's business. *"Janitorial services for grocery, restaurant and retail
   accounts"* is the CLIENT'S OWN reported example of this mistake, and it names
   exactly one bucket in whole words, so conditions 1 and 2 both pass it.

Condition 3 **reuses `cross_form_validator`'s customer-phrase regexes** rather
than writing a third copy - they were built for this identical defect on this
identical live run, one consumer over.

**Every failure resolves to `generic`**, whose rule set is the least demanding,
so a classification this gets WRONG can never score an account harder than
making no claim at all. That is the invariant, and it is pinned.

**NOT routed through `_ops_to_industry`, deliberately.** Tried and rejected: it
answers a different question with a different tolerance for error (its verdict
is cross-checked against the policy's class codes before it can move a score),
and it maps *"electrical equipment manufacturing"* to construction - which would
have handed a manufacturer the CONTRACTOR rule set, a **harsher** one, on a
wrong guess.

**`NAICS_TO_LOB` 311 / 312 -> restaurant were deleted.** Those are Food and
Beverage MANUFACTURING; a cannery is not a restaurant, and this file's own
`_NAICS_SECTOR_INDUSTRY` has always called 31/32/33 manufacturing. One copy
hardened, the other not - again.

**A robustness bug fixed on the way:** `infer_lob` called `.lower()` on the raw
fact, so an `operations_description` that arrived as a list, an int or bytes
raised `AttributeError` **inside both score computations**. That is the shape of
H1-G, the live run that lost its Total Package Score with no reproducible
trigger. Found by fuzzing, not by reading.

### The adversarial pass found three things, and two were my own tests

Run against deliberately hostile inputs before shipping:
- **`"logistics"` was removed from the transportation tokens.** Every token there
  must imply what the bucket's rule set then demands - a vehicle schedule,
  drivers, a radius. A freight broker or 3PL arranges transport without owning a
  truck. It cost a fuzzed case (*"cold chain logistics"*) and was removed rather
  than argued with.
- **Two "failures" were correct behaviour and wrong expectations.** *"Software
  development FOR restaurants"* returns `technology`, and that is right - the
  customer-phrase rule stripped somebody else's trade and left one bucket. The
  test was rewritten to say so, with a note about what does not belong in the
  ambiguity list.

### Known, accepted, stated rather than hidden

- A cert holder written with a suffix variant (`Kestrel Terminal Authority,
  Inc.`) is **not** dropped - the comparison is an identity key, never a
  substring. Fails toward KEEPING a row: a missed drop is a visible wrong value
  a broker can fix, a wrong drop is invisible.
- A caterer described as *"catering company serving corporate clients"* returns
  `generic` rather than `restaurant`: the shared customer-regex sees "clients"
  within its window. Costs coverage, never correctness - `generic` asks for
  less. Not worth widening a regex another consumer depends on.
- **`NAICS_TO_LOB["541"] -> technology` was left alone and is wrong for most of
  that sector** (541 is Professional / Scientific / Technical Services - law
  firms and accountants as well as software), and that label is displayed. It
  moves scores across a large sector and was not the reported defect. Flag it,
  do not improvise it.

### Verification

Suite **6435 passed / 1 failed / 14 skipped** - the one failure is the
documented `httpx` ImportError, identical to the baseline. **Zero regressions
from a change that touched the merge for every schedule key.** New file
`tests/test_roster_party_and_lob_20260905.py` (**59 tests**), every roster test
driving the real `merge_facts` rather than the helper, because the helper being
right while the form was wrong is the entire lesson of item 1.

The SYS-09 kit re-tests both fixes unchanged - it already carries the
certificate holder and the "food products" operations line. `README-HOW-TO-TEST.md`
gained checks 4 and 5 for them.

### Score movement - D6

- Dropping third parties from the roster and the premises schedule removes rows
  that were being counted. A package that had the defect can move.
- The industry reclassification changes which `LOB_RULES` set applies. Every
  change is from a harsher bucket to `generic` or to a correct bucket, so
  **affected accounts should move UP**, and only accounts that were misclassified
  move at all.
- Run 1 baseline on the kit, for comparison: **ACORD 125 = 81, package = 62**,
  Exposure Consistency 37%.

| # | Decision | Reasoning |
|---|---|---|
| D-CN | **The party filter runs on the FINAL merged list, for every key it knows.** | It was reachable from the non-primary branch only, so a single-document session never filtered at all. Fixing only the reported key would have left the identical hole open for drivers, officers and premises. |
| D-CO | **A certificate holder is dropped from the roster, not re-routed.** | `AdditionalInsured_FullName` exists in no ACORD schema, so nothing is lost, and the holder already has its own fact. An additional insured is not an additional named insured. |
| D-CP | **The roster drop fails toward keeping a row.** | Identity-key equality, never substring. A missed drop is visible and correctable; a wrong drop deletes a real insured silently. |
| D-CQ | **`infer_lob` gets word boundaries, single-bucket evidence AND an ownership test - not just the first.** | The client's own janitorial example passes the first two. A test that is necessary but not sufficient needs a structural second condition. |
| D-CR | **`infer_lob` is NOT routed through `_ops_to_industry`.** | Different error tolerance: that one is cross-checked against class codes before it can fire. Routing through it made a manufacturer a CONTRACTOR - a harsher rule set on a wrong guess. |
| D-CS | **Every classifier failure resolves to `generic`.** | `generic` is the least demanding rule set, so a wrong answer can never score an account harder than making no claim at all. This is the invariant, and it is pinned by test. |
| D-CT | **NAICS 541 -> technology was left wrong, and recorded.** | It mislabels law and accounting firms and the label is displayed, but it moves scores across a large sector and was not reported. Brent's call. |

---

## LIVE RUN 2 - THE ROSTER FIX HAD MISSED, AND WHY - SHIPPED 2026-09-06

The 2026-09-05 certificate-holder fix **did not work live**. Run 2 still printed
`Kestrel Terminal Authority` in ACORD 125's `NAME (Other Named Insured)`, now with
a Frankenstein address under it (the APPLICANT's `Ste 300` over the HOLDER's ZIP
`98421`). The industry fix DID work - the `restaurant` chip is gone.

### Root cause: the guard read a drawer that does not exist

`_NAME_LIST_BLOCKED_PARTIES` listed five fact keys. Four are real. The fifth,
`certificate_holder_name`, **does not exist at the top level anywhere in this
codebase.** Extraction writes the holder's name in two other places:

* top-level **`certificate_holder`** - no `_name` suffix (`_EXTRACT_SCHEMA` :297),
  which is what every other consumer reads (`pdf_service.py:1503`,
  `sqs_service.py:1521`, `form_service.py:959`, `cross_form_validator.py:2364`);
* nested **`risk_transfer.certificate_holder_name`** (:386), inside a
  `_STRUCTURED_DICT_FIELDS` dict that nothing flattens.

So `facts.get("certificate_holder_name")` returned `None`, the
`len(b) >= _PARTY_NAME_MIN_CHARS` guard discarded the empty key, and the blocked
set never contained the holder. **The filter worked for four parties and was dead
for exactly the one that was reported.**

### And the tests could not have caught it - the fixture invented the drawer

`tests/test_roster_party_and_lob_20260905.py` built `_IDENTITY` with a TOP-LEVEL
`certificate_holder_name`, a shape extraction never emits. All 24 tests shared
that one fixture. **This is the change-quality bar's own trap, verbatim: the
fixture was easier than reality (D22).** Two other test files in this repo
already used the correct nested shape, so the evidence was on disk and unread.

Second time in two days the same class landed: 2026-09-05 it was the SEAM (the
helper was right, nothing called it on the primary document); 2026-09-06 it is
the SHAPE (the call was right, the key was fiction). Both passed every test.

### THE FIX IS A DOOR, NOT A LONGER LIST

**Owner ruling 2026-09-06:** *"There can be more than 3 places as well, can we
just fix the root cause."* Correct - a hand-written list of key names goes
silently dead the next time extraction adds, renames or nests a key, and the
symptom is a wrong name on a signed form.

`extraction_service.third_party_identity_names(facts)` is now the single door for
*"which names does this package state for a party that is not the applicant?"*
Membership is **worked out from what a key MEANS**, not from a list:

* `_THIRD_PARTY_ROLE_TOKENS` - words that name a non-applicant party (producer,
  agency, broker, carrier, insurer, certificate_holder, mortgagee, lienholder,
  loss_payee, lender, trustee, additional_interest);
* `_PARTY_ATTRIBUTE_TOKENS` - words that mark a key as that party's ATTRIBUTE
  rather than its identity, so `certificate_holder_address` and
  `producer_contact_phone` are excluded while `certificate_holder` and
  `wc_prior_carrier` are not;
* the walk covers structured containers as well as the top level, so **which
  drawer a fact sits in stops being something a caller has to know.**

`_APPLICANT_SELF_KEYS` stays separate and is documented as such: the applicant is
blocked from its own roster for a different reason - row A already prints it, so
a match there is a DUPLICATE, not a foreign party.

**`_party_match_keys` handles the name-plus-address shape.** The questionnaire
asks for the holder's *"name and address"* in one box (`arq_service.py:431`), so
exact equality alone missed `Kestrel Terminal Authority, 1201 Port of Tacoma Rd,
Tacoma WA 98421`. Each comma-prefix whose REMAINDER carries a 5-digit ZIP is also
a candidate key - no vocabulary, no allow-list, and `Acme, Inc.` is never split.
**One-way and load-bearing:** only the PARTY value is ever shortened, never the
roster entry. Shortening the roster entry, or matching on substrings, would drop
`Kestrel Terminal Authority Holdings LLC` - a different company, and the reason
`test_a_DIFFERENT_entity_with_a_similar_name_survives` exists.

### The anti-rot guard is the actual answer to "there can be more places"

`test_every_party_identity_fact_is_visible_to_the_door` scrapes the REAL
`_EXTRACT_SCHEMA` and fails the build if any party-name key in it is invisible to
the door. `test_the_fixture_matches_what_extraction_can_actually_emit` fails if
either real holder key is renamed, so the tests above can never go vacuous again.
A future party fact cannot silently reopen this hole - the build stops it.

### The ADDRESS half, and why `<` alone was the wrong fix

Clearing the NAME does not clear the boxes under it. With an emptied roster, gap
fill wrote an address into `NamedInsured_MailingAddress_*_B` beneath a blank
name. The post-fill net written for exactly this
(`_unanchored_schedule_row_fields`) was **skipping row B**:

    if _ROW_LETTERS.find(letter) <= min_offset.get(root, 0): continue

`NamedInsured` is the only root with `min_offset = 1` (row A is the applicant),
and `find("B") == 1`, so row B - its FIRST LIST ROW - was exempted along with row
A. Row C was judged; row B never was.

**Plain `<` is not the fix and was refused:** it would start judging row A on
every offset-0 root, which is precisely what that guard's own comment forbids
(judging row A once cleared a genuine equipment description). The two exemptions
were conflated into one comparison and are now separate: row A is always exempt,
and rows below a root's `min_offset` are exempt. Measured blast radius:
**`NamedInsured` is the only root of 17 with a non-zero offset**, so exactly one
root changes and it is the reported one.

The net CLEARS rather than pre-empts, deliberately. Owning the row outright would
claim ~52 more fields on ACORD 125 and blow the authoritative-blank ledger's
scalar ceiling - a much larger decision than this defect justifies. The form
ships blank either way.

### "If it never reaches the AI, where does the answer come from?" - owner, 2026-09-06

It does not come from anywhere, and that is the point. `additional_named_insureds`
is declared `[string]` - **names only, no address field exists** - so the row's
address boxes have no possible source in any document. The model was not
retrieving an answer, it was assembling one from whatever sat nearby. The choice
was never "answer versus blank"; it was "wrong answer versus blank", and blank
routes to the producer or the questionnaire like every other unstated fact.
Capturing those addresses for real means upgrading the fact from names to rows -
new capture, not a bug fix, and not done here.

### The additional-insured ruling - block on IDENTITY, never on membership

**Owner, 2026-09-06:** *"don't block every one, but if there is some genuine
value then it should go on."*

`risk_transfer.additional_insured_names` is deliberately NOT a blocked source. An
additional insured is not an additional NAMED insured, but blocking the whole
list is the one change here that can delete a REAL second insured - a genuine
subsidiary is sometimes listed as both, and a missing name is far harder to spot
than a wrong one.

So the rule is identity, not membership: an additional insured who is ALSO
independently identified as the certificate holder, the mortgagee or the loss
payee is caught by that identity; one with no other role keeps its place on the
form. Both directions are pinned by test.

**Honest residual:** if extraction drops a name into the roster and ALSO fails to
record it under any third-party role, nothing catches it. Recorded, not sealed.

### Verification

Suite **6467 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. **Zero regressions.**
`tests/test_roster_party_and_lob_20260905.py` is now **91 tests**.

**The fixture was rewritten to the real shape BEFORE the code was touched, and
13 tests failed** - proof the suite can now catch this defect. They pass on the
fix. A test that has never failed for the reason it exists proves nothing, which
is what the previous 24 were.

Verified end to end through the real `merge_facts` and the real stamper, in every
configuration: one document, two documents, either order, holder-only roster
(-> empty), holder carrying an address tail, and both real fact shapes
separately.

### Also confirmed from run 2, none of it ours

* **The `restaurant` chip is gone** - the industry fix working. Display-only: the
  chip is gated on `lob !== "generic"`. **CORRECTION to the 2026-09-05 entry:**
  that fix does NOT move Exposure Consistency. P2 comes from
  `_calculate_exposure_consistency`, which contains zero references to
  `lob`/`LOB_RULES`; `LOB_RULES`' only consumer is a variant its own docstring
  calls "retained for backwards-compatible imports only". The earlier claim that
  it charged the account for `occupancy_type` was wrong.
* **`oducer / agency bill`** is a PDF RENDERING CLIP, not a truncated string. The
  widget is centre-aligned and 68pt wide; the value measures 85.82pt, so ~8.9pt
  is clipped off each end. The underlying value is gap fill borrowing a SIBLING
  checkbox's tooltip, which the echo guard cannot see because it only ever reads
  a field's OWN tooltip. Pre-existing, unrelated to both fixes.
* **`DATE BUSINESS STARTED = 2012`** - no code derives it; the model computed
  2026 - 14 itself. Pre-existing gap fill.
* **CONTACT TYPE = "Client Contact For This Submission"** - the fixture's section
  HEADING stamped as a value. No rule and no alias bridge for that box.

### The operational finding, and it outranks the bug

**Form generation never re-merges.** `select_forms_bulk` reads the stored
`session["facts"]`, written once at upload (`extraction_pipeline.py:1322`). So a
merge-layer fix reaches a session ONLY if that session's upload ran after the
fix; an older session keeps its bad data permanently, through every
regeneration. **Re-testing any merge fix means a fresh upload, not a
re-generate.**

| # | Decision | Reasoning |
|---|---|---|
| D-CU | **Blocked-party membership is DERIVED from key meaning, not listed.** | A list of key names dies silently the next time extraction renames or nests a fact - which is exactly how this defect shipped. Owner: "there can be more than 3 places, fix the root cause." |
| D-CV | **The door walks structured containers as well as the top level.** | The same party is written under two different key names in two different containers. Which drawer a fact sits in must stop being a caller's problem. |
| D-CW | **A build-breaking test scrapes the real extraction schema.** | The only durable answer to "there may be more places": a new party-name fact that the door cannot see fails the build instead of quietly reopening the hole. |
| D-CX | **The fixture was rewritten to the real shape and watched to FAIL first.** | 24 tests passed against a shape the system never emits. A test that has never failed for its own reason proves nothing. |
| D-CY | **Party values are shortened at a comma only when a ZIP follows; roster entries never are.** | Matches "Name, address, ZIP" without substring matching, which would delete `... Holdings LLC`, a different company. |
| D-CZ | **`additional_insured_names` is not blocked wholesale; identity decides.** | Owner ruling: do not block everyone, let genuine values through. An AI who is also the holder is caught by identity; one with no other role keeps its place. |
| D-DA | **Row A stays exempt from the post-fill net; only `NamedInsured` gains row B.** | `<` alone would judge row A on all 17 roots, which that guard's own history forbids. Measured: one root of 17 changes. |
| D-DB | **The address boxes are CLEARED after fill, not owned before it.** | Owning the row would claim ~52 more fields and blow the authoritative-blank scalar ceiling - a far bigger decision than this defect warrants. The form ships blank either way. |

---

## THE BARE-SUBSTRING CLASS - ONE DOOR SHIPPED 2026-09-06

Run 3 of the SYS-09 kit passed both fixes and raised a NEW false warning: *"The
business description mentions 'bank'"* on an applicant at **2255 SHOREBANK
Avenue**. There is no bank in that submission. `"bank" in ops` found four letters
inside a street name.

That is the third time in three days this exact class has appeared, so it was
swept rather than patched.

### The sweep: 38 candidates, 33 CONFIRMED, 5 refuted

Six agents over the whole backend, then an adversarial pass that tried to REFUTE
each hit by importing the real function and running it - **every confirmation has
a matching CONTROL input that stays silent**, so the misfire is attributable to
the keyword and not to the fixture. Five were refuted or downgraded and are NOT
in the fix list (`_enforce_post_fill_guards` Guard 1 has zero incremental harm;
`_NARRATIVE_SIGNALS` and four of five `DOC_TYPE_KEYWORDS` are outweighed by a
real document's own signals; `detect_no_loss_assertion`'s ACORD 125 checkbox
consequence no longer exists).

Measured misfires, each reproduced live:

| Term | Found inside | Consequence |
|---|---|---|
| `bank` | 2255 SHORE**BANK** AVENUE | buy Crime coverage |
| `atm` | wastewater TRE**ATM**ENT plants | buy Crime coverage |
| `bar ` | RE**BAR** AND structural steel | buy Crime coverage |
| `vault` | **VAULT**ED ceilings | buy Crime coverage |
| `tech` | HVAC service **TECH**NICIANS | buy Cyber Liability |
| `tech` | GEO**TECH**NICAL drilling | buy Cyber Liability |
| `siding` | tenants RE**SIDING** on site | industry = construction, **-15** |
| `hauling` | OVER**HAULING** of pumps | industry = transportation, **-15** |
| `California` | 1450 **CALIFORNIA** STREET, DENVER **CO** | **the CALIFORNIA state form shipped** |
| `building` | OUT**BUILDING** VALUE: 45,000 | **form generation REFUSED** |
| `5403` | payroll **5403**00 | a roofing class code on a clerical risk |
| `farm` | **FARM**INGTON HILLS MI | vehicle USE = Farm |
| `coi` | **COI**NSURANCE_ENDORSEMENT.PDF | classified a certificate |
| `no claims` | FRES**NO CLAIMS** SERVICE CENTER | a clean loss history credited |

### THE ROOT CAUSE IS THE COPIES, NOT THE BOUNDARIES

The one-line fixes were never the problem. There was no shared door, so each of
33 copies rotted on its own - and the proof is in this file's own history:
`_lob_from_operations` was given word boundaries, a single-bucket rule and an
ownership test on **2026-09-05**, while its twin `_ops_to_industry`, **78 lines
below it in the same file**, kept the bare substring. Same file, same question,
one fixed and one not, because they were two copies.

### What shipped - `services/term_match.py`

**Stdlib only, and it imports nothing from `services` / `utils` / `config` /
`routes`.** That is load-bearing, not tidiness: `lob_canon` is the deepest leaf
in the service layer and a consumer, and `sqs_service` <-> `cross_form_validator`
already import each other lazily in both directions. The door sits BELOW all
three, so all three import it at module level with no try/except and no fallback.
`test_the_door_imports_nothing_from_the_app` fails the build if that changes.

Four layers, because the class is four problems and only one of them is
boundaries:

* **`fold(value)`** - any value to a lowercase, space-separated, space-PADDED
  string. Padding is what makes a whole-word test `" term " in folded` with no
  regex in the hot path, and folding makes `workers' compensation`, `E-COMMERCE`
  and `S.I.C.` free. A container folds to its LEAVES, never its repr - the
  punctuation in `[{'code': ...}]` is exactly how a payroll became a class code.
* **`present` / `find` / `mentions` / `matched`** - `find` returns a POSITION
  because earliest-keyword-wins is a real rule here (`_vehicle_use_class`).
* **`sole_bucket`** - two buckets matching means the text singles out none, so
  the answer is None. Disposes of "restaurant construction contractor".
* **`describes_the_subject`** - absorbs `cross_form_validator`'s customer-clause
  regexes, which now have exactly ONE definition (re-exported from their old
  home so nothing else breaks). Deliberately runs on the RAW text, not the
  folded string: its cues are bounded by `[^.]`, and folding turns every full
  stop into a space, which would let a cue leak across two sentences.

**`stem` and `plural` default OFF.** A default `s?` would silently reintroduce a
fixed defect - `_has_explicit_follow_form` breaks the instant "following form"
matches "following forms", which IS its bug. Callers opt in.

**Every function is total.** These run inside score computations, where an
exception does not surface as a bug report, it surfaces as a MISSING SCORE
(H1-G). Verified against **30,000 randomly-generated hostile pairs - zero
raises** - plus None, bools, bytes, nested dicts, sets, `10**50`, lone
surrogates, a 100k-char document, and unhashable TERMS (a term arriving as a
list is unhashable and `lru_cache` raises on it before the body runs - found by
fuzzing, not by reading, and fixed).

### Routed this round, and what each one cost

| Site | Fix | Effect |
|---|---|---|
| `cross_form_validator` `_CASH_TERMS` | door | the client's `bank` warning stops; a real bank still warns |
| `cross_form_validator` cyber_keywords | door | HVAC / geotechnical stop being sold Cyber |
| `cross_form_validator._cash_term_is_the_applicants` | door | its ownership walk was ITSELF `ops.find(term)`, so it was inspecting the same accidental hit |
| `sqs_service._ops_to_industry` | door + single-bucket + ownership | the -15 at :3363 and :3411 stops on 6 measured shapes |
| `sqs_service._lob_from_operations` | door | my own 2026-09-05 copy folded in; its `except: return True` **fail-open** fallback deleted - an import blip used to restore the bug |
| `form_service._extract_state_code` | **reorder** | the CALIFORNIA-form defect |
| `underwriting_consistency` building value | `\b` | generation-blocking false conflict |

### Two that are NOT boundary fixes, and were not treated as such

* **`_extract_state_code`** - every pattern was ALREADY `\b`-anchored. The
  state-NAME sweep simply ran FIRST and returned on its first hit, so the
  trailing "CO 80202" was unreachable. A state name in free text is the WEAKEST
  signal available (it is also a street, a city and a county); the positional
  shapes are structural. Order reversed, name kept last so "Denver, Colorado"
  still answers CO.
* **`property_building_value`** - one `\b`, but it is the highest-consequence
  boundary bug found: this is the ONLY key in
  `GENERATION_BLOCKING_RECONCILABLE_KEYS`, so a false conflict does not warn, it
  REFUSES TO GENERATE FORMS - over a shed.

### HONEST RESIDUE - the class is NOT closed, and nobody should say it is

**Boundaries fix 22 of the 33.** The other 11 fail because the term genuinely IS
a whole word: "aerial **PLATFORM** lift", "occupational **HEALTH** and safety
program", "**ARMORED** cable and conduit". Those need a longer phrase or a second
condition, decided rule by rule - a vocabulary question, not a matching one. The
cyber check carries that note at its call site.

A different class was also found and NOT fixed: **meaning inversion**.
`"unlicensed"` contains `"licensed"`, `"disqualified"` contains `"qualified"` -
the narrative scorer credits a control for a sentence that says the opposite.
Boundaries make it worse, not better (the whole word is there). Recorded.

Not routed this round, deliberately: `_value_in_raw_text`, `lob_canon.canon_line`
(it turns "Automatic Sprinkler Leakage" into **auto** - real, but it touches
coverage-line identity everywhere) and `_INDICATOR_RULES`. Each needs a full term
audit first and does not belong in the same change as everything else.

### Verification

Suite **6551 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. **Zero regressions.** New file
`tests/test_term_match_20260906.py` (**84 tests**): every measured false positive
as its own case, a control that must still fire beside each one, the opt-in
rules, ownership, ~30 hostile data shapes for both haystack AND term, and three
anti-rot guards - the leaf-import rule, the single definition of the customer
regexes, and both industry classifiers proving they still ask the door.

### Score movement - D6, BOTH DIRECTIONS

* **UP:** false Crime and Cyber warnings stop (each was capping at 85); the
  ops/class-code **-15** stops on misclassified accounts; a false
  building-value conflict stops blocking generation.
* **DOWN, and honestly:** `_has_explicit_follow_form` is NOT yet routed, but when
  it is, a false "follow form confirmed" stops suppressing a real **-10**; the
  narrative scorers were over-crediting on `telemarketing`/`marketing` and
  `websites`/`sites`.
* Only accounts that were MISCLASSIFIED move at all. A correctly-read submission
  scores exactly what it scored before.

| # | Decision | Reasoning |
|---|---|---|
| D-DC | **One shared door, not a 33rd local fix.** | The one-liners were never the problem. `_lob_from_operations` was fixed while its twin 78 lines below it was not, because they were separate copies. |
| D-DD | **The door is stdlib-only and imports nothing from the app.** | `lob_canon` is the deepest leaf and a consumer; two other consumers already import each other lazily. Any service import here hands all three a cycle. Pinned by test. |
| D-DE | **`stem` and `plural` default OFF.** | A default `s?` reintroduces the `_has_explicit_follow_form` defect on day one. Looseness is opted into per call site, never inherited. |
| D-DF | **Every function is total; ambiguity returns None/False.** | They run inside score computations, where a raise costs a Total Package Score (H1-G) and a guess costs a wrong answer. 30,000 fuzzed pairs, zero raises. |
| D-DG | **`_extract_state_code` was reordered, not re-anchored.** | Its patterns were already `\b`-anchored. A state NAME in free text is also a street, a city and a county - the weakest signal, so it goes last. |
| D-DH | **22 of 33 fixed; the rest recorded, not papered over.** | Where the term is genuinely a whole word, boundaries change nothing. Saying the class is closed would be false. |
| D-DI | **Three wide-blast-radius sites deferred.** | `lob_canon.canon_line` turns "Automatic Sprinkler Leakage" into `auto` and touches coverage-line identity everywhere. It needs its own term audit, not a shared commit. |

---

## SYS-09 RUN 4 - ACCEPTANCE AUDIT, AND THE OPEN ITEMS CLOSED (2026-09-06)

Run 4 confirmed the contact separation holds - Delphine Ostrander in the producer
block, Marguerite Vasseur in the applicant block, the certificate holder out of
the Named Insured roster, and the false `bank` Crime warning gone (7 items back
down to 6). Then the acceptance criteria was read line by line, and it named
something never tested.

### THE HONEST GAP: only ONE of the two forms in the criteria had ever been run

> *"Erin Royal is the client contact that belongs on the **ACORD 125**
> applicant/contact context, while the brokerage contact belongs on the
> **ACORD 25** producer/broker context."*

**Four live runs, and an ACORD 25 was never generated once.** The system itself
said so on run 2 - *"ACORD 25 is not in the selected forms. Add ACORD 25 to
satisfy the request"* - and that was read as a cross-form recommendation instead
of as the criteria naming the test.

Checked deterministically offline: on ACORD 25 only `Producer_ContactPerson_*`
fills, with the brokerage contact, and the client contact appears NOWHERE (that
form has no applicant-contact box at all - its only three contact fields are the
producer's). But that is the DETERMINISTIC path, and every defect in this arc
lived in gap fill, which only runs against a real document. **Offline is weaker
evidence than it looks and is not counted as met.**

A second scenario was also untested: both contacts in the SAME document. The kit
put them in two files, so it tests "does one document overwrite the other" and
never "are two people on one page collapsed into one", which is what the
criteria's own words describe.

### Also honest: the role separation was never the broken part

`contact_name` and `producer_contact_name` have been separate facts all along.
What was fixed is a LEAK - a certificate being allowed to supply the applicant's
contact, and the merge skipping its own role rules for the primary document. If
the criteria is read as "build role-aware contact facts", they already existed.

### Closed this round

**1. The city box read "Suite 300 Tacoma".** Runs 2 and 4 printed it; run 3 did
not, which is exactly why it looked fixed for a day - run 3's extraction emitted
a second comma and the ordinary parse worked. **Luck, not a fix**, and it was
reported as luck at the time.

Root cause: `_parse_address` splits on commas, so
`"2255 Shorebank Avenue, Suite 300 Tacoma, WA 98402"` puts `parts[-2]` -
`"Suite 300 Tacoma"` - straight into the city. Recovery 2 in that function
already knows this shape (`_ADDR_UNIT_THEN_CITY_RE`), but it only runs when the
city is still UNKNOWN, and here the comma split had already filled it wrongly.

New recovery 4 splits a city that BEGINS with a unit designator and nothing else
(`_ADDR_UNIT_ONLY_RE`), so `Suite 300 / Ste 400 / # D13 / Floor 3 / Unit B` move
to line two and the remainder is the city. It can never cut at a street name,
and `"1 Plaza, Suite City, NY"` is left alone - the leading chunk there is not a
unit-and-nothing-else. **This is not a malformed-address fix: every ACORD and
letterhead prints the unit on the street line and the city on the next.**

**2. The AUDIT box printed a bare "A".** Three runs, on a package that states no
audit term anywhere. The PAYMENT PLAN box beside it was closed for the identical
invention on 2026-08-14 - "AN", which the model derived from *"Audit Period:
Annual"* - and the comment recording that fix is four lines above the box that
was still unowned. `_resolve_audit_frequency` is the missing sibling:
`audit_period` (an extracted fact with a registry question since 2026-08-14)
stamps when a document really prints one, otherwise the box is an owned blank.
A CODE abbreviates a printed word, so no verbatim or echo check can ever see
this class of invention - fact-or-blank is the only honest resolution for that
whole row.

**3. The kit gained SESSION B** - `S3_one_document_both_contacts.pdf`, one page
naming both people a few lines apart, each under its own party heading. The
README now instructs generating **ACORD 125 AND ACORD 25 together** in session A,
which is the sentence in the acceptance criteria.

### DELIBERATELY NOT DONE, and it is not an oversight

The certificate holder now has no deterministic route into the ADDITIONAL
INTEREST block: run 3 printed it there correctly with ADDITIONAL INSURED ticked,
run 4 printed nothing. That is gap-fill nondeterminism, and it is tempting to
close by binding `certificate_holder` to that block.

**Refused for now.** The old code never placed it correctly either - it put the
holder in the NAMED INSURED box, which was the defect; run 3's good placement
was the model guessing well, not a binding. So the roster fix removed a wrong
behaviour, not a right one. Adding NEW form-filling behaviour to a legal
document - and an interest TYPE tick is a coverage assertion - immediately
before a full acceptance test round is the wrong trade. Recorded as an open
item with its own reasoning rather than gold-plated in.

### Verification

Suite **6571 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. **Zero regressions.** New file
`tests/test_run4_fixes_20260906.py` (20). The authoritative-blank ledger gained
`_resolve_audit_frequency: 1`.

Two test expectations were wrong and were corrected, not the code: display
canonicalisation abbreviates `"Suite 300"` to `"Ste 300"` on the stamped value
by design, and rows B-N of the audit box ARE claimed deliberately, like every
sibling resolver in that family.

| # | Decision | Reasoning |
|---|---|---|
| D-DJ | **The acceptance criteria is NOT met until ACORD 25 is generated live.** | It names two forms; four runs tested one. An offline deterministic check does not count, because every defect in this arc lived in gap fill, which needs a real document. |
| D-DK | **A second fixture was added for both contacts in ONE document.** | Two separate files test overwriting. The criteria's own words are about COLLAPSING two people into one generic contact, and one page naming both is where that happens. |
| D-DL | **The city split fires only on a unit-and-nothing-else prefix.** | It can then never cut a city at a street name, and a real city beginning with a unit word ("Suite City") is untouched. |
| D-DM | **The AUDIT box is fact-or-blank, like the payment plan beside it.** | A code abbreviates a printed word, so no verbatim check can see the invention. The row's other boxes were closed this way in August; this one was simply missed. |
| D-DN | **The certificate holder was NOT given a route into Additional Interest.** | An interest-type tick is a coverage assertion, the old code never placed it correctly anyway, and new form-filling behaviour does not belong immediately before an acceptance test. |

---

## SYS-09 ACCEPTANCE ROUND - CONTACTS PASS, THE ADDRESS DID NOT (2026-09-06)

Two sessions run against the acceptance criteria for the first time, including
**ACORD 25 - the second form the criteria names, never generated until now.**

### The criteria's contact clauses: MET

| | Session A (S1+S2) | Session B (S3, one document, both contacts) |
|---|---|---|
| ACORD 125 applicant contact | Marguerite Vasseur | Marguerite Vasseur |
| ACORD 125 producer contact | Delphine Ostrander | Delphine Ostrander |
| **ACORD 25 producer contact** | **Delphine Ostrander** | n/a |
| Client contact anywhere on ACORD 25 | **none** | n/a |
| Other Named Insured | blank | blank |

**Session B is the one that mattered.** One page naming both people a few lines
apart, each under its own party heading, and they did not collapse - the exact
sentence in the criteria (*"should not be collapsed into one generic contact
name"*), and the case two separate files structurally cannot test.

### THE FAILURE, AND A CORRECTION TO WHAT WAS WRITTEN HERE YESTERDAY

Both forms in session A printed the PRODUCER block as
`2255 Shorebank Ave, Ste 300, Tacoma WA 98402` - byte-identical to the INSURED
block beneath it. The applicant's address, in the agency's box, on a certificate.

**The guard was intact.** Verified: the field names match on both forms and
`_resolve_producer_mailing` still returns an owned blank when `producer_address`
is absent. So the value can only have come from the FACT - extraction wrote the
applicant's address into `producer_address`, and the box then correctly stamped
its own party's fact.

The 2026-09-05 entry says of exactly this shape: *"none of these fixes catches
it ... it remains a pure LLM-comprehension risk, not a code bug."* **That was
wrong.** A value that is a plausible INVENTION is uncatchable. A value that is an
EXACT COPY of another party's is not - two parties at one address means one of
them is wrong, and that is a structural test, not a guess.

`_echoes_another_partys_value` now gates both producer resolvers. **Two
comparisons, because "the same address" and "the same string" are different
questions:** folding equates case and punctuation but not ABBREVIATIONS, and a
fixture pairing `Ste 300` with `Suite 300` slipped through the first cut - caught
by this file's own test, not by a live run. `_address_identity_key` (street
number + ZIP5), the door `_drop_transaction_party_rows` already uses for the same
question, is immune to both.

**ASYMMETRIC ON PURPOSE - only the PRODUCER side ever yields.** The applicant's
address is corroborated all over a submission (insured block, premises schedule,
FEIN block) and is a Tier 1 field; the producer's is stated once. On an exact
duplicate the producer's is overwhelmingly the borrowed one, and blanking the
applicant's instead would cost more than the defect does. Pinned by
`test_the_applicants_own_side_is_NEVER_the_one_blanked`.

### Also fixed: a role riding along in the contact NAME box

Session B printed `CONTACT NAME: "Marguerite Vasseur, Controller"` while
`CONTACT TYPE`, the box beside it, printed `Controller`.

**NO TITLE VOCABULARY, deliberately.** "Smith, John" is a legitimate way to write
a name and a job-title list would blank it the first time somebody was called Mr
Controller. The tail is removed only when that row's own CONTACT TYPE box
already prints the same text - which proves it is the role rather than half the
name, and means nothing is lost, because the value survives in the box that
exists for it.

### Score movement observed - D6

Exposure Consistency **37% -> 42%** and Cross-Document Consistency **95% -> 100%**
between the pre-fix runs and this one: the `_ops_to_industry` fix no longer
inventing an industry. Session A package **62**, session B **63**, both forms
**81**. That is the baseline Brent should be shown.

### STILL OPEN on ACORD 25 - one family, deliberately not rushed

All four are certificate gap-fill, all observed this run, none of them SYS-09:

1. `DAMAGE TO RENTED PREMISES` and `PERSONAL & ADV INJURY` both print
   **$1,000,000**; neither document states either. Copied from the each-occurrence
   limit.
2. **"Commercial Auto" printed as a LIMIT LABEL** inside the auto limits box with
   $1,000,000 beside it - a label stamped as a value.
3. **ADDL INSD "Y" ticked on the WORKERS COMP row** of a submission with no WC
   coverage - an additional-insured assertion on a policy that does not exist.
   The most serious of the four.
4. The certificate holder prints `Kestrel Terminal Authority / Tacoma WA 98421`
   with the street line missing.

They belong in one focused round with their own repro, not bolted onto a contact
fix. Recorded rather than half-done.

### Verification

Suite **6591 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. **Zero regressions.**
`tests/test_run4_fixes_20260906.py` is now **40 tests**.

| # | Decision | Reasoning |
|---|---|---|
| D-DO | **An exact copy of another party's value IS catchable, and the earlier claim that it is not was wrong.** | Only a plausible invention is invisible. Byte-equality with a value we hold for a different party is structural evidence that one of them is borrowed. |
| D-DP | **Only the producer side yields on a duplicate.** | The applicant's address and contact are corroborated across a submission and are Tier 1; the producer's are stated once. Blanking the applicant's would cost more than the defect. |
| D-DQ | **The copy test asks the ADDRESS question with the address door, not string equality.** | `Ste 300` and `Suite 300` fold differently and name one building. `_address_identity_key` already answers this and is reused rather than re-derived. |
| D-DR | **The contact-name role strip needs the role printed in its own box, and no title list.** | "Smith, John" is a name. A vocabulary would blank it; the sibling box is proof, and it means the value is never lost. |
| D-DS | **The four ACORD 25 gap-fill defects were recorded, not fixed in this change.** | They are one family with a shared cause and deserve their own repro. Bolting them onto a contact fix is how a change stops being reviewable. |

---

## SYS-09 ACCEPTANCE - PASSED ON BOTH FORMS, BOTH SESSIONS (2026-09-06)

Re-run of both sessions after the copy guard.

### The criteria is MET

| | Session A (S1+S2) | Session B (S3, one document) |
|---|---|---|
| ACORD 125 producer address | **blank** | **blank** |
| **ACORD 25 producer address** | **blank** | n/a |
| ACORD 25 producer contact | Delphine Ostrander | n/a |
| ACORD 125 applicant contact | Marguerite Vasseur | Marguerite Vasseur |
| Client contact anywhere on ACORD 25 | none | n/a |
| Other Named Insured | blank | blank |

The producer block on BOTH forms is now blank rather than carrying the
applicant's address, on the same package that produced the failure. The
`, Controller` that rode along in the contact NAME box last run is also gone -
the sibling CONTACT TYPE box still prints it, which is where it belongs.

**And the certificate holder landed correctly on its own:** ACORD 125 page 3
prints `Kestrel Terminal Authority / 870 Wharfside Blvd / Tacoma WA 98421` in
ADDITIONAL INTEREST with EVIDENCE **CERTIFICATE** and ADDITIONAL INSURED ticked.
That is the right box for it, reached without the binding that was deliberately
not added (D-DN) - so the decision to leave it alone was correct.

### Closed this round: sub-limits copied sideways on a certificate

Session A's ACORD 25, on a package stating ONE GL limit and NO umbrella:

    DAMAGE TO RENTED PREMISES ....... $1,000,000
    PERSONAL & ADV INJURY ........... $1,000,000
    UMBRELLA LIAB  EACH OCCURRENCE .. $1,000,000

None stated in either document - the each-occurrence figure copied sideways into
every empty money box in the column. **The umbrella one is the serious case: a
certificate is the document a landlord or terminal relies on, and this one
asserted umbrella cover that does not exist.**

`_resolve_stated_limit_cell` closes it for the six boxes with a fact of their own
(`gl_fire_damage_limit`, `gl_medical_expense`, `gl_personal_advertising_injury`,
`gl_products_aggregate`, `umbrella_limit` x2). **Every one already had a Pass-1
rule pointing at its own fact** (`:1322-1325`, `:1564-1565`), so a policy that
states a sub-limit still prints it - only the absent-fact case was falling
through to gap fill. Same shape and same remedy as the deposit, the fax, the
payment plan and the audit box.

**A LIMIT IS NOT INFERABLE.** Sub-limits do not track the each-occurrence figure
(damage to rented premises is typically $50-100k against a $1M occurrence
limit), so a copied number is not a good guess - it is a wrong figure on a
signed certificate.

**DELIBERATELY EXCLUDED: the two PRIMARY GL limits.** `EachOccurrence` and
`GeneralAggregate` are what a dec page prints largest, extraction gets them, and
on a rare miss gap fill reading them off the raw text beats a blank. The measured
failure is the copy INTO the siblings, so that is what is closed and nothing
wider. Boxes affected live on ACORD 25 / 126 / 131 / 160; the ACORD 125
authoritative-blank ledger is unchanged because that form does not carry them.

### Verification

Suite **6608 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. **Zero regressions.**
`tests/test_run4_fixes_20260906.py` is now **57 tests**.

### Still open on ACORD 25, unchanged and recorded

1. **"Commercial Auto" / "AUTOMOBILE" printed as a TYPE-OF-INSURANCE label**
   inside the GL block, with a tick beside it. A label stamped as a value.
2. The certificate holder's **street line is missing on ACORD 25** while the same
   holder prints in full on ACORD 125's Additional Interest block - so the fact
   is there and only the 25's binding drops it.
3. `METHOD OF PAYMENT` still carries an invented value ("Direct Bill",
   "...oducer / agency bill" clipped by a 68pt centre-aligned widget). Neither
   document prints a billing word; the value is gap fill borrowing a SIBLING
   checkbox's tooltip, which `_is_tooltip_echo` cannot see because it only ever
   reads a field's OWN tooltip.

| # | Decision | Reasoning |
|---|---|---|
| D-DT | **Unstated GL sub-limits and the umbrella row are owned blanks.** | They already had Pass-1 rules to their own facts; only absence fell through. A sub-limit does not track the each-occurrence figure, so a copy is a wrong number, not an estimate. |
| D-DU | **The two primary GL limits stay with gap fill.** | They are the largest figures on a dec page and extraction gets them; on a miss, reading them off the raw text beats a blank. Only the measured failure was closed. |
| D-DV | **The certificate-holder binding stayed unbuilt, and that was right.** | It reached ADDITIONAL INTEREST correctly on its own, with EVIDENCE: CERTIFICATE ticked. Adding a coverage-asserting tick would have been new form-filling for no gain. |

---

## THE LAST THREE ACORD 25 DEFECTS - SHIPPED 2026-09-06

All three root-caused, and **the first cut of two of them was WRONG and was caught
by an adversarial pass before it shipped.** That is the story worth keeping.

### 1. A coverage-type LABEL stamped as a value

`GeneralLiability_OtherCoverageDescription_A` printed **"Commercial Auto"** with
its checkbox ticked; the auto block printed **"AUTOMOBILE"**. ACORD's tooltip says
the box is for coverage *"not found on the form"* - and Commercial Auto has its
own block eight rows down.

**THE FIRST CUT BLANKED ALL 16 BOXES AND WAS WRONG.** Six measured kills, every
one a correct value deleted:
* `GeneralLiability_OtherCoverageLimitAmount` has a live Pass-1 rule to
  `gl_deductible` (:1341) - the GL deductible stopped printing on certificates;
* `Vehicle_OtherCoverage_*` is the auto limit column's spare row, where every
  broker prints `Uninsured Motorist $1,000,000` (`auto_um_uim_limit` is a fact);
* `WorkersCompensationEmployersLiability_OtherCoverageIndicator` is the
  `PER STATUTE | OTH-` selector, so blanking it means a WC policy written ABOVE
  statutory limits could only print PER STATUTE - **a coverage misstatement by
  omission, arriving through the fix**;
* `Vehicle_OtherCoveredAutoIndicator` is the "Other symbol" box the 2026-08-07
  auto-symbols work deliberately ticks for ISO symbols 5 / 19;
* `Excess Employers Liability`, `Stop Gap` and `Employee Benefits Liability` are
  correct broker wording in exactly these boxes - and Guard 2f's own comment
  already names EBL as a genuine other coverage.

**A coverage NAME is the right content for these boxes. That was never the
defect.** What shipped instead is a post-fill guard that removes only a name of a
section THIS FORM ALREADY PRINTS, using the same `_CERT_SECTION_CANONS` set
`_resolve_certificate_other_row` reasons about - plus a STRUCTURAL SECOND
CONDITION, because canon alone is necessary and not sufficient: "Excess Employers
Liability" canonicalises to `umbrella` and "Stop Gap" to `workers_comp`. A
borrowed header is built only from the section's own title words; a real coverage
adds a word of its own ("employers", "benefits", "stop gap"). Measured: 9 headers
removed, 9 genuine coverages kept, 20,000 fuzzed strings, zero raises.

### 2. The certificate holder's street line

`certificate_holder_address` is a first-class extraction fact with a
`FACT_REGISTRY` entry scoped to ACORD 25 and its own producer question - **bound
to no ACORD field anywhere**. The five holder boxes map to the `_addr_*`
pseudo-keys, which `_deterministic_map` correctly restricts to `NamedInsured_*`
so the insured's address cannot bleed into a third party's block. Correct
restriction; it left the holder's own boxes with no source at all.

**THE FIRST CUT WAS ALSO TOO LOOSE**, and this kill is the worst in the round:
`_parse_address` assumes a US `ST ZIP` tail, so

    "1200 Rue Sherbrooke O, Montreal, QC H3A 1H6" -> state 'H3A', postal '1H6'

**QC discarded entirely, half a postal code stamped in the province box.** Today
gap fill reads `QC` off the certificate and gets it right. The fix would have
traded ONE MISSING BOX for TWO WRONG ONES on a legal document - and Tacoma is a
cross-border port, so a Canadian holder is an ordinary input.

Now: a COMPLETE US parse or nothing. All four parts must resolve, the state must
be a real US code, the ZIP a real ZIP, and line one must be street-shaped (a
digit, PO Box, RR or HC) - which also disposes of the name-blob and "Attn:"
shapes that would otherwise put the holder's NAME in the street box. Everything
else steps aside and keeps gap fill's measured-good coverage.

**No copy-refusal here, deliberately, and unlike the producer block:** a food
distributor placed at the terminal that HOLDS the certificate genuinely shares
that address, and blanking on a match would empty a correct block.

### 3. The invented METHOD OF PAYMENT

Mechanism confirmed **from the schema, not inferred**. The two checkboxes beside
the box carry the ACORD tooltips *"...the policy is to be DIRECT BILLED"* and
*"...to be PRODUCER / AGENCY BILLED"* - verbatim the two strings that printed.
`_is_tooltip_echo` is handed `schema.get(field)`, so a SIBLING's tooltip is
outside its input by construction, in both its paths.

Fact-or-blank on `billing_plan`, like the four boxes already closed in that row.

### A pre-existing crash the fuzzing found

`_parse_address` went straight to `addr.split(",")`, so a fact arriving as a
bool, int, list or dict raised **inside form generation** - where an exception
does not surface as a bug report but as a form that failed to produce. 315 of
5,000 fuzzed fact dicts crashed on that one line (`mailing_address = True`).
Shape-guarded; 8,000 fuzzed generations across both forms now raise zero.

### Verification

Suite **6683 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. **Zero regressions.**
`tests/test_acord25_final_three_20260906.py` (**75 tests**) pins every
adversarial kill as its own case.

### Recorded, not fixed

* `_LOB_FIELD_ALLOWED_RE` allow-lists the marker `CoverageDescription`, which
  disables `LOB_NAME_OUT_OF_PLACE` on **53 fields across 9 other forms**; and
  `_LOB_NAMES` recognises only 1 of the 10 section headers ACORD 25 prints
  ("AUTOMOBILE LIABILITY", "UMBRELLA LIAB", "EXCESS LIAB" all read False). The
  allow-list is CORRECT for these boxes - a coverage name belongs there - so the
  general fix needs per-form section knowledge, not a wider net.
* Gap-fill batch packing crossed over on the live-computed union (28 vs 27) now
  that ~15 more fields are owned. First-fit can lose to one-unit-per-bin at low
  field counts. Not touched: it is a tuned cost engine whose own docstring flags
  batch DENSITY as the accuracy risk.

| # | Decision | Reasoning |
|---|---|---|
| D-DW | **The other-coverage guard removes a section HEADER, never a coverage.** | A coverage name is the correct content for these boxes; blanking the family deleted the GL deductible, UM/UIM, the WC OTH- selector and three genuine wordings. |
| D-DX | **Canon plus a title-word subset test - canon alone is not sufficient.** | "Excess Employers Liability" canonicalises to umbrella and "Stop Gap" to workers_comp; both are real coverages the first cut deleted. |
| D-DY | **The holder address stamps only on a COMPLETE US parse.** | A foreign address turns one missing box into two wrong ones. Gap fill was already right on four of five, so the failure direction must be today's behaviour. |
| D-DZ | **No copy-refusal on the holder block, unlike the producer's.** | An insured operating out of the terminal that holds the certificate legitimately shares its address. |
| D-EA | **`_parse_address` shape-guards its input.** | It is called inside form generation; a bool fact raised, and 315 of 5,000 fuzzed dicts hit it. |

---

## THE UNOWNED WORKERS-COMP BAND, AND AN OPERATIONS BOX OWNED BY THE WRONG
## RESOLVER - SHIPPED 2026-09-07

Live acceptance run 2026-09-06 (Harborline Provisions, GL + Business Auto, **no
workers comp anywhere in the documents**). ACORD 25 printed the applicant's
operations sentence in the WORKERS COMPENSATION block's limits column, a bare
"Y" in the workers-comp band, and left DESCRIPTION OF OPERATIONS - where that
sentence belongs - **empty**. Two root causes; the first explains the second's
symptom, because the model had narrative to place and nowhere legitimate to put
it.

### 1. The census floor of THREE made the whole WC band a question

`_line_absent_from_package` only calls a line absent on an explicit denial or a
census of **three or more** granted lines. Harborline grants two, so all 8-12 WC
fields fell through to gap fill - on the commonest small-commercial shape there
is. The field the operations sentence landed in was identified from the
TEMPLATE GEOMETRY, not guessed: at y 288-300, `PER`/`STATUTE` prints at x=442.8
and `OTH-`/`ER` at x=493.1, and the only text field in the limits column (x>=518)
on that row is `WorkersCompensationEmployersLiability_OtherCoverageDescription_A`
- 72.0pt at `/F2 8 Tf`, i.e. the 19 characters "Refrigerated wareho" that printed.

The form had **already** decided it could not identify a WC policy:
`_resolve_current_policy_line_cell` returns an owned blank for the WC policy
number and both dates on this same package. It then asked the model Yes/No
questions about that policy.

**The obvious fix was killed by the adversarial pass, and rightly.** Gating the
band on `has_workers_comp` being False DELETED three correct, verbatim
$1,000,000 E.L. limits from a certificate that really did carry workers comp,
and it did not even fix the reported box when the flag was True. Six kills in
total, including blast radius onto ACORD 131's underlying grid and onto sessions
with no `coverage_lines` at all.

**What shipped:** the floor drops from 3 to 2 **only when
`_family_has_no_evidence` corroborates** - not one fact of the family carries a
value, from any source. An E.L. limit, a stated payroll, a class code, a carrier,
a producer's typed answer or an affirmative flag all keep the band open.
Evidence, not truth. One granted line is still never a census, and a session with
no inventory is byte-identical to before.

**Then the EXISTING suite caught a real bug in my fix**, which my own new tests
did not. `line_presence.line_in_submission` keeps flags in a SEPARATE dict, so
the facts it passes can never contain a WC fact - my rule read that as "no
evidence" and **overrode an affirmative `has_workers_comp = True`**, exactly the
kill the adversarial pass had warned about, arriving by a path it never tested.
Absence of evidence is not evidence of absence: silence now means something only
when the family's coverage FLAG KEY is present, proving the pipeline actually
evaluated the family. Two red tests, both correct, both now green.

### 2. ACORD 25's operations box was claimed as a general remarks box

`_REMARK_TEXT_RE = ^\w*_?RemarkText_[A-N]$` is a NAME-SHAPE test with no
structural second condition. It claims 28 fields across 16 schemas. 27 really are
general-remarks boxes; ACORD's own tooltip defines the 28th as the opposite -
*"records information necessary to identify the operations, locations and
vehicles for which the certificate was issued."* So the box was an owned blank,
invisible to gap fill AND to Pass 1.5 (its alias entry exists and was
unreachable), and the certificate shipped with an empty operations box.

`_resolve_certificate_operations_box` now owns it and stamps
`operations_description`. **ONE fact, deliberately:** the richer chain through
`certificate_description_of_operations` was measured shipping a carrier forms
schedule and the CGL "WHO IS AN INSURED" clause verbatim into that box.

### Two more pre-existing container crashes, same class as `_parse_address`

`_resolve_declared_absent_line_row` and `_family_has_no_evidence` both did
`(facts or {}).get(...)`, which raises on a non-dict that is merely truthy - an
int, a string, a populated list. Inside form generation an exception is not a bug
report, it is a form that never gets produced. Shape-guarded.

### NOT SHIPPED, and deliberately: ACORD 125 Q4 "ANY OTHER INSURANCE"

CONFIRMED defect. `_resolve_other_policy_cell` sources the grid from
`coverage_lines`, which `extraction_service` RULE 16 defines as *"the per-line
breakdown of THIS policy"* - so Q4 is structurally guaranteed to print the
policies being applied for, under a question asking for OTHER ones. ACORD's
tooltips confirm the two forms mean different things: on 125 "the line of
business of the **other** policy", on 25 the certificate's free OTHER row with
its own limits, dates and insurer letter.

**Held for Brent (D6), not fixed unilaterally**, for one reason: audit
2026-08-15 round 9 deliberately made Q4 print those lines ("Q4 prints 1 of 4
policies"). Reversing a recorded decision that changes what a client sees is his
call, not mine. The fix is ready - form-scope to ACORD 125, owned blank, which
also closes the second face where the Pass-1 substring rule
`("Policy_PolicyNumberIdentifier", "policy_number")` stamps the package's own
number into row A when `coverage_lines` is absent.

### Verification

Suite **6725 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. **Zero regressions.**
`tests/test_acord25_wc_band_and_ops_box_20260907.py` (41).
Live package end-to-end: operations box carries the sentence, WC band ALL EMPTY,
certificate holder complete, producer block correct.

| # | Decision | Reasoning |
|---|---|---|
| D-EB | **The census floor drops to 2 only with fact-side corroboration.** | Two lines alone is thin and the 2026-08-15 audit was right; two lines AND not one fact of the family is a different, much stronger statement. |
| D-EC | **Evidence, not truth: any value keeps the band open.** | Gating on the flag deleted three correct E.L. limits from a certificate that carried them. |
| D-ED | **Silence counts only when the family's flag KEY is present.** | `line_in_submission` passes facts without flags; without this the rule overrides an affirmative flag. Absence of evidence is not evidence of absence. |
| D-EE | **ACORD 25's operations box is not a remarks box.** | A name-shape test with no second condition claimed it against ACORD's own tooltip. |
| D-EF | **That box takes `operations_description` and nothing else.** | The fallback chain was measured shipping a forms schedule and a CGL exclusion clause onto a legal document. |
| D-EG | **ACORD 125 Q4 is held for Brent.** | A confirmed defect, but reversing a recorded 2026-08-15 decision changes what the client sees - D6. |

---

## THE PRECONDITION THAT COULD NOT FIRE, AND A FUZZ THAT FINALLY COVERS THE
## LAYER THAT PRODUCES WRONG VALUES - 2026-09-07 (second round)

The 2026-09-07 live run proved two of three fixes and failed the third:
DESCRIPTION OF OPERATIONS filled correctly, the operations sentence was gone
from the workers-comp limits column, **and the stray "Y" was still there.**

### The rule was right; its precondition could never hold on live data

`_family_has_no_evidence` required `has_workers_comp` to be PRESENT in facts
before silence could mean anything. That precondition was added the same day,
correctly, because `line_presence.line_in_submission` keeps flags in a separate
argument and the first version overrode an affirmative `has_workers_comp = True`.

**But the extraction prompt sets `has_workers_comp` true only when a document
actually evidences workers comp** (`extraction_service.py:753` - a preprinted
ACORD 25 heading explicitly does not count). On a package carrying no workers
comp the key is simply ABSENT. So the suppression silently never fired on
exactly the packages it was written for. Measured, all three WC boxes:

    flag present & False   -> owned blank        (the test fixture)
    flag MISSING entirely  -> ASKED              (every real package)
    flag present & True    -> ASKED              (correct)

Two wrong versions shipped before the right one, and **neither was caught by the
file that tested it**: v1 by the existing SYS-04 suite, v2 by the live form.

**The right question is not "is this family's flag here?" but "were coverage
flags computed at all?"** - only then is the family's absence from them evidence.
`_flags_were_computed` answers it structurally: two or more keys matching
`^has_[a-z][a-z0-9_]*$`, which is how every writer of a coverage flag names one
(`extraction_service` emits ~28). `form_service` merges `{**facts, **flags}`
before form fill so the render path always qualifies; `line_in_submission` passes
facts that structurally cannot contain one and correctly abstains. Two, not one,
so a hand-built fixture carrying a single `has_*` key is never mistaken for a
computed package.

**And the test fixture was the other half of the failure.** `LIVE` carried a
single `has_workers_comp` key; a real package arrives with the whole flag set.
That is D22 exactly - the fixture was easier than reality, and it made a rule
that could not fire look proven. Fixed to the merged shape.

### The fuzzing now covers the layer that actually produces wrong values

Every earlier fuzz ran FACTS through the stamper. Most wrong values do not come
from facts - they come from the gap-fill model. That was the honest hole, and it
is closed:

* **11,900 generations across ALL 17 schemas** (700 per form, 700/700 clean on
  every one; a separate 4,250-run sweep agrees), fuzzing facts AND `pre_filled_gpt`
  (the gap-fill envelope, `filled_values` / `raw_text_fields` / `question_
  grounding`) with 36 value shapes including bool, bytes, empty containers,
  envelopes, nested dicts, 300-char strings and foreign addresses -> **0 crashes.**
* **PROPERTY TEST, 3,000 randomised ACORD 25 packages** with the WC boxes
  answered by a fuzzed gap fill:
  - **NO INVENTION: 0.** Not one package lacking workers-comp evidence printed a
    workers-comp box. The property holds across randomised packages, not on a
    fixture.
  - **NO DELETION: attributable count 0.** 76 of 1,500 evidenced packages lost
    every WC box; running the identical sweep with `_family_has_no_evidence`
    forced off gives **the same 76**, so none of them are mine. They are the
    pre-existing, correct refusal to state a WC policy's number or dates when no
    WC line is identified.

Crash-freedom is robustness, not correctness - which is why the invention and
deletion properties are measured separately and the deletion count is
ATTRIBUTED by differencing against the rule disabled, not merely reported.

### Verification

Suite **6736 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError, identical to baseline. Zero regressions.
`tests/test_acord25_wc_band_and_ops_box_20260907.py` (53).

| # | Decision | Reasoning |
|---|---|---|
| D-EH | **"Were flags computed?", not "is this flag present?"** | The family's own flag is absent precisely on the packages the rule exists for, so requiring it guaranteed the rule could never fire. |
| D-EI | **Two coverage flags, not one.** | One `has_*` key is a hand-built fixture; a computed package carries dozens. |
| D-EJ | **The fixture carries the merged flag set.** | D22: a single-flag fixture made a rule that could not fire on live data look proven. |
| D-EK | **Deletions are ATTRIBUTED by differencing, not reported.** | 76 losses looked like damage; with the rule disabled there are exactly 76, so none are mine. |
| D-EL | **Fuzz the gap-fill envelope, not just facts, on all 17 forms.** | Facts are not where wrong values come from; the model is. |

---

## SYS-09 ACCEPTANCE: THE "AND VICE VERSA" HALF - SHIPPED 2026-09-07

The criterion reads *"Client contact values should not overwrite
producer/brokerage contact values, and vice versa."* Four shapes were tested
against the live stamper; three passed and the fourth did not.

| Shape | Before |
|---|---|
| both contacts present | clean |
| only the CLIENT contact exists | producer block blank - no leak |
| only the PRODUCER contact exists | applicant block blank - no leak |
| **extraction collapses them onto the broker** | **the broker's name printed as the CLIENT's contact** |

The fourth is the ORIGINAL SYS-09 failure shape. `_resolve_producer_contact`
already refused a producer contact that is an exact copy of the applicant's -
the FABRICATION case, where a submission states no producer contact and gap fill
reaches for the only contact it can see. **Its mirror never existed**, so a
collapse in the other direction printed a brokerage employee as the insured's
contact and nothing objected. A guard written for one direction of a symmetric
defect is half a guard - which is what the file already said about the first
one, one direction too early.

**Switching the mirror on ALONE made it worse, and this was measured, not
reasoned.** Each rule refuses a value that is an exact copy of the other party's;
when the two facts are identical, "the other one is the copy" is true from BOTH
sides, so both blocks refused and BOTH shipped blank - deleting a real contact.

**The tiebreak is the email's own domain.** `_contact_email_party` matches it
against each organisation's name, with corporate and trade suffixes ("LLC",
"Insurance", "Agency", "Services") stripped first - they appear in every third
company name and would make the rule fire on unrelated domains. It is
deliberately SILENT when the domain matches both or neither, and both callers
then keep their prior behaviour rather than guess.

Measured, all five shapes:

    both present                    producer=Delphine   applicant=Erin Royal
    collapsed onto the BROKER       producer=Delphine   applicant=BLANK
    producer fabricated from CLIENT producer=BLANK      applicant=Erin Royal
    only the CLIENT contact         producer=BLANK      applicant=Erin Royal
    only the PRODUCER contact       producer=Delphine   applicant=BLANK

ACORD 25 carries only the producer context and no applicant-contact block at
all - "populate each form according to the ACORD field context", satisfied by
the form's own field set.

**Known and accepted:** a personal-domain contact (gmail, outlook) gives the
tiebreak no signal, so a collapse onto such an address is not caught. Silence
there is by design - the alternative is guessing which party a neutral domain
belongs to, and a wrong guess misattributes a named person to the wrong company,
which is the defect itself.

Tests: `tests/test_sys09_role_separation_both_ways_20260907.py` (30).
Suite **6766 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. Zero regressions.

| # | Decision | Reasoning |
|---|---|---|
| D-EM | **The mirror ships with a tiebreak or not at all.** | Both rules alone blank both blocks and delete a real contact - measured. |
| D-EN | **The email domain decides which party a collapsed contact belongs to.** | Structural, works on any data, no allow-list. |
| D-EO | **Corporate and trade suffixes are stripped before matching.** | "Insurance", "Agency", "LLC" would match unrelated domains. |
| D-EP | **A neutral domain means no opinion, never a guess.** | A wrong guess misattributes a person to the wrong company - the defect itself. |

---

## THE WC SUPPRESSION COULD NEVER FIRE - TWO CAUSES, FOUND FROM LIVE SESSION
## DATA - 2026-09-07

I asserted three times that the workers-comp band was fixed. It was not, and
each time I reasoned from a fixture instead of the session. Dumping the real
session (`c8a5c547-1c36-4cd5-82c5-c11ab697a347`, ACORD 125 + 25) settled it in
one command. Both causes were mine.

### CAUSE 1 - payroll is not workers-comp evidence

`_FAMILY_EVIDENCE_PREFIXES` carried `total_payroll`, `num_employees`,
`class_code` and a bare `wc_` prefix. The live session:

    has_workers_comp = False, 27 coverage flags computed
    wc_el_each_accident, wc_payroll, wc_prior_carrier, wc_xmod ... ALL null
    total_payroll      = {"value": "$3,120,000", ...}
    wc_payroll_period  = {"value": "annual", ...}
    -> _family_has_no_evidence = FALSE

**Every commercial application states payroll.** Counting it as workers-comp
evidence makes the rule unfireable on any real package - and the `wc_` prefix
swept in `wc_payroll_period`, which the H1-K entry above already documents as an
AI-inferred false positive. Evidence now has to be something that could not
exist WITHOUT the coverage: an E.L. limit, a WC policy or carrier, a class-code
schedule, an experience mod, officer treatment, an affirmative flag.

### CAUSE 2 - a certificate never prints premiums, so no line was ever "granted"

With cause 1 fixed the band was STILL asked. `_line_entry_evidences_policy`
called `_line_entry_grants_coverage` FIRST, and that function reads only
`premium` or `limit`. Its own twin's docstring states the consequence in terms:

> *"A certificate of insurance never prints premiums, so most COI rows are
> `grants=False`."*

The live rows carried a carrier, a NAIC, a policy number and a full term, and
scored **False** on both - purely because `premium` was null. So on a
CERTIFICATE-LED package no line ever counted as granted, the census always saw
zero, and **every absence inference built on it was unreachable** - not just
workers comp.

The grant precondition is replaced by a DENIAL check. The premium-or-number rule
the predicate was written for is now the only test, which is what its docstring
always described: a real policy states a premium or its own number; a
requirement-shaped limits-only row states neither and is still refused
(the umbrella's schedule of REQUIRED underlying limits, the case it exists for).

    LIVE COI row (number, no premium)   -> True   (was False)
    a premium, no number                -> True
    REQUIREMENT-SHAPED: limits only     -> False
    bare line name / denial / form number / empty / non-dict -> False

### Verified on the session itself, not on a fixture

    BEFORE  _family_has_no_evidence = False   WC band is ASKED OF THE MODEL
    AFTER   _family_has_no_evidence = True    WC band is an OWNED BLANK

`scripts/dump_session_wc_facts.py` runs the real functions against a real
session and prints that verdict. **It is the tool that should have been written
three rounds earlier** - every wrong conclusion in this arc came from testing a
fixture I had built rather than the data the pipeline actually holds.

**Blast radius, deliberately widened:** more lines now count as granted, so
absence inference reaches MORE packages - every family in
`_DECLARED_ABSENT_LINE_FAMILIES`, not only WC. That is the intended correction;
the census was previously blind on the commonest submission shape there is.

Suite **6802 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. Tests: `tests/test_acord25_wc_band_and_ops_box_20260907.py` (63).

| # | Decision | Reasoning |
|---|---|---|
| D-EQ | **Payroll, employee counts and generic class codes are NOT coverage evidence.** | Every commercial application states them; counting them made the rule unfireable on live data. |
| D-ER | **A policy NUMBER evidences a policy as well as a premium does.** | A certificate never prints premiums - the code's own docstring says so - so the premium gate blinded the census on certificate-led packages. |
| D-ES | **A requirement-shaped limits-only row still evidences nothing.** | The umbrella's schedule of required underlying limits is why the predicate exists. |
| D-ET | **Diagnose from the session, never from a fixture.** | Three wrong conclusions in this arc, all from fixtures easier than the data. `dump_session_wc_facts.py` is the standing tool. |

---

## SYS-01 - Critical tagging in the client questionnaire - SHIPPED + LIVE-VERIFIED 2026-09-07

**Read this before touching `question_classifier.priority`, `sqs_service._tier1_entries` /
`_tier2_entries`, or the Send-to-Client modal's metric chips.**

**VERDICT: CLOSED.** All three acceptance clauses met; three live sessions, every predicted
count hit exactly (A `5 Critical (2 agency)`, B `0 Critical`, C `11 Critical (3 agency)`).
Suite **6802 / 1 / 14** (the documented `httpx` ImportError), frontend build clean. TWO items
carried forward and named rather than buried: the *"satisfied by a prior answer"* half of
clause 2 is unit-covered but not live-observed, and NAICS / SIC are Critical in the AGENCY
bucket rather than the Client bucket the ticket's wording implies - an owner-approved
deviation, see D-FS.

### The client's words

> **WHAT WE OBSERVED:** *"The live test identified specific client questions that should be
> treated as Critical when the information is still unresolved, including core items such as
> FEIN/Tax ID, annual revenue, employee count, and NAICS or SIC. The fact that several of these
> happened to appear first in the test is incidental; list position does not make a question
> Critical."*
>
> **EXPECTED OUTCOME / ACCEPTANCE CRITERIA:** *"Apply the Critical tag to the business-defined
> questions when their underlying fact is still unfulfilled. If the fact has already been
> satisfied by the submission or a prior answer, it should not remain Critical. Critical status
> should be driven by the question/fact rule, not by the order in which the question appears."*

Screenshot evidence: the Send-to-Client modal reading `325 Client | 16 Agency | 0 Critical |
315 Optional | 30 duplicates merged`, `11 selected`, with FEIN / Annual revenue / Employee count
cards all badged **Important + Suggested + SQS**. The pre-form Review screen on the **same
session** read *"Key details in place: Applicant legal name · Proposed effective date ·
Operations description · Years in business"* and *"Key details missing: FEIN / Tax ID · Annual
revenue · Number of employees · NAICS or SIC industry code."*

### THE DIAGNOSIS - one defect, not two

`priority` was a **STATIC tier label**. `question_classifier.py:153`:

```python
CRITICAL_FIELDS = (_TIER1 | _TIER1_CONTACT) - {"producer_name"}
```

Resolved at runtime (measured, not read): `{applicant_name, contact_email, contact_name,
contact_phone, effective_date, entity_type, lines_of_business, mailing_address}`. Every Tier 2
fact - `fein`, `total_revenue`, `num_employees`, `years_in_business`,
`operations_description`, `naics_code` - lands in `IMPORTANT_FIELDS` and could **never** be
Critical, however absent. Measured through the real function:

```
fein           aud=client    pri=important   <- the screenshot, byte for byte
total_revenue  aud=client    pri=important
num_employees  aud=client    pri=important
naics_code     aud=producer  pri=internal
sic_code       aud=producer  pri=internal
```

The card titles are literal strings in `arq_service._FIELD_PRODUCER_LABEL_MAP` (`:563-571`):
`"FEIN / Tax ID"`, `"Annual revenue - rating basis"`, `"Employee count"`, `"Annual gross
payroll - rating basis"`. The client's screenshot reproduces exactly.

So on a package whose Tier 1 was complete there was **nothing left that could be Critical**,
and `AcordModal.jsx:1428` then printed *"All critical fields were already answered from your
uploaded documents"* - a false statement, contradicted by the same session's own Review card.

**One sentence:** Critical described *what a complete submission needs in general*, never *what
THIS submission is missing*. It never read the facts.

### THE MEASUREMENT THAT DECIDED THE RULE

Tier 2 is six facts. On the reported run:

| In place (Review card) | Missing (Review card) |
|---|---|
| Operations description, Years in business | FEIN, Annual revenue, Number of employees, NAICS or SIC |

The client named, as needing Critical: **FEIN, annual revenue, employee count, NAICS or SIC.**
Exactly the four that were missing. Not three, not five, not a curated pick - he read his own
*"Key details missing"* line back to us.

**That is the proof the rule is "required AND still missing", not a list of four names**, and it
is why a fix that hardcoded those four would be a symptom fix (gate 1 of the CHANGE QUALITY
BAR). A package missing `years_in_business` instead would have got nothing: same bug, new
screenshot.

### THE FIX - ONE SOURCE, TWO VIEWS

`_tier1_entries` / `_tier2_entries` are now the single definition of what a submission owes, as
`(fact_keys, label)` pairs. Everything else is a projection:

| Projection | Consumer |
|---|---|
| `_tier1_items` / `_tier2_items` (LABEL view) | `check_tier1` / `check_tier2` (the Structural score) and `key_details` (the pre-form card). **Byte-identical output** - pinned by `test_label_view_is_unchanged_by_the_refactor`. |
| `core_missing_fact_keys` (KEY view) | `question_classifier._promote_missing_core_requirements` - the Critical rule. |

**A projection cannot disagree with what it projects.** Two lists keeping separate ideas of
"core" is what produced the defect; the fix deletes one of them rather than synchronising them.

Three properties fall out of reading the entries instead of writing a second list, and each one
closes a way this could have gone wrong:

- **Answered facts are absent** from the missing set, so a satisfied requirement can never be
  Critical - the client's second acceptance clause, guaranteed by construction rather than by a
  check somebody can forget.
- **Not Applicable facts are absent**, because C3 3.6 already removes them from the denominator.
- **A paired requirement contributes BOTH its keys or NEITHER.** `Contact information` is one
  item over three keys (client 9.1, *"any one contact method satisfies Tier 1"*); `NAICS or SIC`
  is one item over two (client 3.13, interchangeable).

### Decision register

| # | Decision | Reasoning |
|---|---|---|
| D-FN | **Read the required-and-missing set from the scorer's OWN entries; never write a second list.** | The two screens disagreeing IS the defect. A new `CORE_CRITICAL_FIELDS` set beside `CRITICAL_FIELDS` would have satisfied the screenshot and re-created the disease one layer over. Guarded by `test_the_key_details_card_and_the_critical_rule_name_the_same_gaps` and `test_every_missing_label_resolves_to_at_least_one_fact_key`. |
| D-FO | **Refactor `_tier1_items` / `_tier2_items` into `(fact_keys, label)` entries rather than adding a parallel key-returning function.** | A sibling function would be a second copy of the checklist rules - the exact duplication class that let the Umbrella SIR and auto-symbol bugs survive their first fixes. The label view is now derived from the entry view, so a future checklist change reaches both consumers or neither. |
| D-FP | **Promote in `decorate_questions` (the STATE layer), never in `classify_question` (the STATIC layer).** | `classify_question` takes no `facts` argument by design; the split is "what tier is this fact?" versus "what does THIS submission still owe?". Corroborating evidence that the layering is right, not merely convenient: the entire existing priority test surface (`test_question_controls.py`) is written against `classify_question` and stayed green untouched, including `test_tier2_and_coverage_fields_are_important`, which still legitimately asserts `fein` / `total_revenue` are IMPORTANT **at that layer**. |
| D-FQ | **Run the promotion LAST, after `apply_eligibility`.** | Eligibility legitimately re-routes questions to the producer (client 4.4 / 9.1) and legitimately demotes a contact question whose requirement another method already met (`REASON_CONTACT_SATISFIED`). Running last means those decisions stand. It is also SAFE to run last, and not by luck: the entries treat contact as ONE item, so a satisfied contact requirement contributes none of its three keys and there is nothing here to undo the demotion with. Pinned by `test_one_contact_method_satisfies_the_whole_contact_requirement`. |
| D-FR | **ADDITIVE ONLY - raise a priority, never lower one; never touch `audience` or `bucket`.** | Owner, verbatim: *"keep the list 1 as it is for critical and add more to it."* Routing is another door's decision and this pass has no business in it. Pinned two ways: `test_the_promotion_only_ever_raises_a_priority` (compares against the pre-change pipeline with the pass monkeypatched out) and `test_the_promotion_function_is_additive_in_isolation` (drives the function directly). |
| D-FS | **NAICS / SIC stay in the AGENCY bucket and gain the Critical tag there.** | Owner ruling, verbatim: *"no keep them in agency and put a critical tag on naic and sic as well."* Honours client PART 13 (2026-08-12): *"We should not be asking the client for the NAICS or SIC class codes; those come from the producer or underwriter"* - a classification code drives class assignment and rate, so an insured guessing is worse than blank. Verified safe: `apply_default_selection` gates pre-ticking on `audience == client`, so an Agency Critical is flagged but **never** auto-sent to the insured (`test_an_agency_critical_is_never_pre_selected_for_the_client`). |
| D-FT | **`producer_name` is excluded from the promotion.** | It is a Tier 1 SCORING field but has been out of `CRITICAL_FIELDS` since the taxonomy shipped ("the agency's own name - a producer-side item, not a client question"). This door was not asked to revisit that and must not reverse it silently. `_CORE_CRITICAL_EXCLUDED_KEYS` is the ONLY exclusion and it mirrors an existing decision rather than inventing a second list. |
| D-FU | **Gate on `suppressed_reason`, NOT on `suppressed`.** | **A trap worth remembering:** `classify_question` sets `suppressed = True` for every `audience in (internal, producer, do_not_send)`. It means *"keep out of the default CLIENT set"*, **not** *"hide"* - `AcordModal.isAgency` does not filter on it, which is why the 16 Agency questions render at all. Gating on `suppressed` would have skipped NAICS/SIC entirely and silently produced no change at all for the owner's own ruling. The gate is `_ANSWER_ALREADY_KNOWN_REASONS = {already_provided, stated_in_narrative, raw_schema_prompt}` - the reasons that mean *we have the answer by a route the tier check cannot see*. |
| D-FV | **Only the `client` and `agency` buckets are promotable.** | `underwriting` holds cross-form conflict flags, which already carry their own severity-driven priority (`is_cross_form` + `severity == hard_stop` sets CRITICAL); `do_not_send` (producer fax) must never gain urgency. Pinned by `test_underwriting_and_never_send_buckets_are_never_promoted`, whose fax case deliberately carries a core canonical key as the worst case. |
| D-FW | **`_finalize_schedule_taxonomy`'s `IMPORTANT` write becomes a FLOOR, not a clamp.** | It runs AFTER `decorate_questions`, so an unconditional write would silently defeat the promotion for any schedule-backed fact on the checklist. **No such fact exists today** - `locations` is in neither tier - which is precisely why it would have failed silently the day one was added, with every unit test green. Two lines, provably inert now, pinned by `test_a_schedule_question_floor_never_clobbers_a_critical`. Same class as `fix-the-layer-the-screen-reads`. |
| D-FX | **Extract `_score_impact_labels` as one door.** | `score_impact` now has TWO writers (`classify_question` from the static tier, the promotion from the fact state). `question_eligibility`'s `REASON_CONTACT_SATISFIED` block already had to hand-correct the "Submission readiness" badge for want of this function - one badge builder, or the third writer repeats the same bug. |
| D-FY | **The frontend counts Critical across BOTH buckets, renders the chip in the Agency panel, and sorts that panel by priority.** | `AcordModal.jsx:1401` counted `clientQuestions` only, and `renderRow`'s priority chip was gated on `!showAudienceBadge` - so under D-FS the owner's own ruling would have produced **no visible change whatsoever**: still "0 Critical", still no badge. A flag nobody can see is not a flag. The chip prints `N Critical (M agency)` so the split names its owner; the Agency chip is shown for `critical` only, so the panel does not gain an "Internal" badge on all 16 rows (which is why it was hidden originally). |
| D-FZ | **The false banner is rewritten, with a third branch.** | *"All critical fields were already answered from your uploaded documents"* must never print while a required fact is missing. Three states now: client Criticals exist -> unchanged prompt; only Agency Criticals -> *"No critical questions for the client - N required detail(s) still missing and waiting for your agency below"*; genuinely nothing missing -> *"All required details are already answered..."*. |
| D-GA | **Did NOT flip `ENABLE_CLASSIFICATION_SUGGESTIONS`.** | The owner did not rule on it. Flagged as open below - see "Still open" - because it materially affects this feature: NAICS is essentially never on a dec page, so the Critical will fire on nearly every submission, and the `naics_suggester` that would make it answerable is off. |
| D-GB | **Did NOT add any fact to the Tier 1 / Tier 2 lists.** | Those lists are the client's own (`SQS_Scoring_Specification.docx.pdf`; `TIER2_FIELDS`' comment: *"Six fields, exactly as the client lists them"*). Widening what counts as "required" is a business decision, not an engineering one. The fix makes the two screens agree; it does not make the underlying list smarter - stated honestly rather than quietly extended. |
| D-GC | **Tests isolate the new pass by monkeypatching it out, not by diffing `classify_question` against the finished question.** | **Methodological lesson, learned the hard way in this arc.** The first two versions of the additivity tests FAILED and both were the TEST being wrong: they blamed this pass for `apply_eligibility`'s legitimate client->producer re-route (`effective_date`, `lines_of_business` - client 9.1) and its legitimate contact demotion. Verified causally by running the pipeline with `_promote_missing_core_requirements` stubbed to a no-op and confirming both behaviours persisted. **When asserting "my change is additive", the baseline must be the pipeline WITHOUT the change, never an earlier stage of it.** |
| D-GD | **The live kit is THREE packages, not one - and C was added only after the owner asked.** | A and B both carry a complete Tier 1, so neither can prove an OLD Critical still fires: there is nothing missing for it to fire on. The owner's question - *"check if new fields are there as critical and all the old as well there"* - exposed that the kit could answer only half of its own claim. C (thin broker summary: no address, no entity type, no dates, no contact) is the other half, and it produced all six old Tier 1 Criticals live. **A kit that cannot fail is not a test.** |
| D-GE | **Keep the carrier NAIC and the `LLC` suffix in the fixtures, and document the variance.** | Every real declarations page prints a carrier NAIC and every real company name carries its entity suffix. Removing them to get a cleaner expected count is D22 - the fixture easier than reality. Both were left in, both documented as things to watch, and both behaved correctly live (carrier NAIC never read as NAICS; entity type not inferred from the suffix). |
| D-GF | **Read the generated PDFs BACK before shipping the kit.** | Two fixture defects were invisible in the generator source and obvious in the extracted text, and BOTH would have produced a false pass - a "NOTE" narrating the four absent facts, and a mid-word wrap corrupting the operations description under test. A generated fixture is not verified until its OUTPUT has been read. |

### Acceptance criteria - audit against the client's own wording

| Clause | Verdict | Evidence |
|---|---|---|
| *"Apply the Critical tag to the business-defined questions when their underlying fact is still unfulfilled"* | **MET** | Replayed with the reported session's facts: `fein` / `total_revenue` / `num_employees` -> `critical` / client; `naics_code` / `sic_code` -> `critical` / agency. `test_the_reported_session_produces_the_clients_four_criticals`. |
| *"...including core items such as FEIN/Tax ID, annual revenue, employee count, and NAICS or SIC"* | **MET** - all four | Same test. Note the rule is general: all 14 checklist facts are promotable, of which these four were the ones missing on his run. |
| *"...satisfied by the SUBMISSION... should not remain Critical"* | **MET - live** | Run B: the documents state FEIN / revenue / employee count / SIC and the modal reports `0 Critical`. A satisfied fact is absent from `core_missing_fact_keys`, so there is nothing to promote; a filled fact's question is also suppressed upstream (`already_provided`), which the reason gate blocks independently. |
| *"...satisfied by a PRIOR ANSWER... should not remain Critical"* | **MET in code, NOT OBSERVED LIVE** | Same mechanism, one input earlier: a client/producer answer lands in `facts` and is read by the same `answer_semantics.fact_answered` door. Unit-covered for a stored answer (`source: client_arq`), an answered ABSENCE (`"N/A"`, per Brent 2026-08-24) and a Not Applicable envelope - `test_a_satisfied_fact_is_never_critical` (3 params), `test_a_not_applicable_fact_is_never_critical`, `test_a_question_we_already_have_the_answer_to_is_never_promoted` (2 params). **No live run has had a client answer a question and come back.** Low risk, explicitly not claimed as observed. See "Still open". |
| *"Critical status should be driven by the question/fact rule..."* | **MET** | The rule reads `core_missing_fact_keys`, a pure function of facts + flags. |
| *"...not by the order in which the question appears"* | **MET, and it was already true** | Audited before building: no positional logic assigns priority anywhere. Position only decides which duplicate survives `_merge_form_ids_into_question` (both duplicates share a canonical key, so they share a priority) and which questions the 28-cap pre-ticks. Recorded as a clarification of the requirement, **not** a second defect - no work was invented to match it. Now pinned anyway: `test_priority_is_independent_of_list_position` decorates the same set forward and reversed and asserts identical priorities. |

**Two honest qualifications, neither a gap in the criteria:**

1. ~~NOT YET LIVE-VERIFIED~~ - **LIVE-VERIFIED 2026-09-07**, three sessions, every predicted
   count hit exactly. See "Live verification" below.
2. **NAICS / SIC deviate from the ticket's literal wording**, which lists them among *"client
   questions"*. They are Critical in the AGENCY bucket per D-FS. This is a deliberate,
   owner-approved reading: the ticket's mention is one item in a passing list (no NAICS card
   appears in any of the three screenshots), against an explicit, reasoned instruction on
   record from 2026-08-12. If Brent pushes back the answer is one line: *"You told us on 12
   Aug the client must never be asked for these. We flagged it Critical for the agency
   instead."*


### The test kit - `sys01_test_data/`, standing asset

    py backend/scripts/make_sys01_test_pdfs.py

**THREE packages, one file each, three separate sessions. Forms: ACORD 125 + 126 on all
three** - the minimum carrying every fact under test, verified against the real schemas
(125 holds `fein` / `naics_code` / `sic_code` / `operations_description`; 126 holds
`num_employees`; revenue is a curated question on either). More forms only add unrelated
questions and bury the Critical count.

| Package | Shape | Proves |
|---|---|---|
| **A** `A1_dec_page_core_gaps.pdf` | GL dec page, Tier 1 COMPLETE, four Tier 2 gaps | the NEW Tier 2 facts fire - the client's reported shape, which under the old code showed `0 Critical` |
| **B** `B1_dec_page_core_satisfied.pdf` | same account, gaps closed, industry code as **SIC ONLY** | a SATISFIED fact does NOT fire, and the NAICS-or-SIC pair is ONE requirement |
| **C** `C1_submission_summary_thin.pdf` | thin broker summary: no address, no entity type, no dates, no contact | the OLD Tier 1 facts still fire - **nothing was lost** |

**Why C had to exist.** A and B both carry a complete Tier 1, so **neither can prove the old
behaviour survived** - there was nothing missing for an old Critical to fire on. The owner
asked the right question (*"check if new fields are there as critical and all the old as well
there"*) and the answer was that the kit could not yet say. C was added for exactly that.

**Two hazards left in the fixtures ON PURPOSE, both cleared live:**
- Every package prints `Carrier NAIC: 24988`, because every real declarations page does. This
  repo has history of the carrier's `naic` being read as the business's `naics_code`. Run C
  asked *"What is your insurance company's NAIC number?"* as its own producer question,
  entirely separate from the NAICS classification code. Removing the carrier NAIC would have
  made the kit easier than reality (D22).
- `HARBOR RIDGE ROOFING **LLC**` keeps its entity suffix. If extraction infers `entity_type`
  from it, C yields 10 Criticals rather than 11 - documented as an acceptable pass. It did
  not occur on the live run.

**TWO FIXTURE DEFECTS WERE FOUND BY READING THE GENERATED PDFs BACK**, not by trusting the
writer, and both would have produced a FALSE PASS:
1. A "NOTE" paragraph on Package A narrating all four absent facts (*"This declarations page
   does not state the insured's federal tax identification number, annual revenue..."*). A
   real dec page does not announce what it omits, and a sentence naming all four is precisely
   the shape that invites the extractor to write `"not stated"` into them - closing the gap
   for the wrong reason. Deleted; the absence is now genuine.
2. A character-slice wrap splitting the operations description mid-word as `"No ho / t tar"`,
   corrupting the very `operations_description` the kit puts under test. Now word-aware
   (`_wrap`).

**Standing lesson:** a generated fixture is not verified until its OUTPUT has been read back.
Both defects were invisible in the generator source and obvious in the extracted text.

### Live verification - 2026-09-07, three sessions, kit `sys01_test_data/`

Generated by `backend/scripts/make_sys01_test_pdfs.py`. Forms: **ACORD 125 + 126** on all
three (the minimum carrying every fact under test - verified against the real schemas:
125 holds FEIN / NAICS / SIC, 126 holds the employee count).

| Run | Predicted offline | Observed live | |
|---|---|---|---|
| **A** `A1_dec_page_core_gaps.pdf` - Tier 1 complete, 4 Tier 2 gaps | `5 Critical (2 agency)` | `5 Critical (2 agency)` | PASS |
| **B** `B1_dec_page_core_satisfied.pdf` - gaps closed, SIC only | `0 Critical` | `0 Critical` | PASS |
| **C** `C1_submission_summary_thin.pdf` - thin broker summary | `11 Critical (3 agency)` | `11 Critical (3 agency)` | PASS |

**Run A** - the client's reported shape. FEIN / Annual revenue / Employee count all badged
**Critical** + `SQS` + `Submission readiness` (they were `Important + Suggested` before);
NAICS and SIC **Critical** at the top of the Agency panel.

**Run B** - the control that a per-key fix breaks. A stated **SIC** satisfied the
`NAICS or SIC` requirement, so **neither** fired: NAICS listed in Agency carrying no
Critical badge, SIC gone entirely (its fact is answered). Zero Criticals.

**Run C** - the OLD half, which A and B structurally cannot test (both carry a complete
Tier 1). All six Tier 1 items still fire:

| Old Tier 1 item | Bucket | Result |
|---|---|---|
| Mailing address | client | Critical, pre-ticked |
| Legal entity type | client | Critical, pre-ticked |
| Primary contact - name / phone / email | client | Critical, pre-ticked (3 separate cards) |
| Policy effective date | **agency** | Critical - client 9.1, *"client does not need to interpret policy period"* |

8 client Criticals + 3 agency = 11. `10 selected` = the 8 client Criticals + two scoring
Importants (no-known-losses attestation, submission urgency). **The three AGENCY Criticals
are visibly UNTICKED** in the screenshot - D-FS confirmed on screen, not just by test: a
required fact the insured cannot answer is flagged for the broker and never auto-sent.

`entity_type` DID appear, so the documented "LLC suffix may be inferred" variance (10 vs 11)
did not occur on this run - extraction did not read the entity type out of the company name.

**Two hazards the kit deliberately carried, both cleared:**
- **Carrier NAIC vs business NAICS.** Every package prints `Carrier NAIC: 24988`, because
  every real dec page does. Run C's Agency panel asks *"What is your insurance company's NAIC
  number?"* as its own producer question, entirely separate from the NAICS classification
  code - the two never conflated. (Removing the carrier NAIC would have made the kit easier
  than reality - D22.)
- **`Policy expiration date`** correctly stayed **Producer decision, NOT Critical**: only
  `effective_date` is a Tier 1 item, and 9.1 routes both to the producer.

**Two fixture defects were found by reading the generated PDFs back rather than trusting the
writer**, and both would have produced a false pass: a "NOTE" paragraph narrating all four
absent facts (the shape that invites the extractor to write `"not stated"` into them), and a
character-slice wrap splitting the operations description mid-word as `"No ho / t tar"` -
corrupting the very `operations_description` under test. Both fixed before the kit shipped.

### Corrections made to my own earlier reading - recorded so nobody repeats them

- **"NAICS/SIC is hidden entirely" - WRONG.** It renders in the Agency panel and is part of
  the "16 Agency" count. `isAgency` does not filter on `suppressed`. What was actually wrong
  is that it carried `priority=internal` - the same label as form plumbing - so it was being
  asked in a whisper. This mistake is exactly what D-FU exists to prevent.
- **"The ticket directly contradicts PART 13" - OVERSTATED.** One passing mention against an
  explicit instruction is a clarification to seek, not a contradiction to litigate.
- **"These facts can NEVER be Critical" - IMPRECISE.** They can, via the `is_cross_form` +
  `severity == "hard_stop"` branch - but that branch also sets `audience=internal`, so such a
  question never renders as a client Critical and never reaches the chip. The correct
  statement is *"never CLIENT-Critical"*.

### Files touched

| File | Change |
|---|---|
| `backend/services/sqs_service.py` | `_tier1_entries` / `_tier2_entries` (renamed from `_items`, now `(keys, label)`); `_tier1_items` / `_tier2_items` become label projections; new `core_missing_fact_keys` + `_CORE_CRITICAL_EXCLUDED_KEYS`. |
| `backend/services/question_classifier.py` | New `_promote_missing_core_requirements`, `_ANSWER_ALREADY_KNOWN_REASONS`, `_CORE_CRITICAL_BUCKETS`, `_score_impact_labels` (extracted); `decorate_questions` gains `flags`; module `logger`. |
| `backend/services/arq_service.py` | `PRIORITY_CRITICAL` import; `flags=` passed at all THREE `decorate_questions` call sites; `_finalize_schedule_taxonomy` priority write becomes a floor. |
| `frontend/src/components/form/AcordModal.jsx` | `criticalClient` / `criticalAgency` / `criticalCount`; chip counts both buckets; Critical chip rendered in non-client panels; Agency panel sorted by priority; three-branch banner. |
| `backend/tests/test_sys01_critical_tagging.py` | NEW, 26 tests. |
| `backend/scripts/make_sys01_test_pdfs.py` | NEW. Generates `sys01_test_data/` (3 PDFs + `README-HOW-TO-TEST.md`). |
| `1stSep-liveTestFixes.md` | This section + the status-board row. |

### Verification

- **Suite 6802 passed / 1 failed / 14 skipped** (`py -m pytest -q -p no:randomly`). The one
  failure is the long-documented `httpx`/`openai` `ImportError`, reproduced in isolation and
  unrelated.
- Frontend production build clean (`VITE_API_BASE=https://api.primble.io npx vite build`).
- **Two failures in `test_acord25_wc_band_and_ops_box_20260907.py` appeared on the FIRST full
  run and were chased, not waved off.** That file is **untracked in-flight work**; it sits at
  collection position 5 against this change's position 167 (so this file cannot pollute it); it
  passes alone (63) and with files 1-5 together (192); and it did not reproduce on two further
  full runs. Order-dependent flakes in someone else's uncommitted work.

### Blast radius - D6, Brent sees this before it ships

- **No SQS score moves.** Nothing here touches a scoring path. `score_impact["points"]` (15 vs
  8) is display and pre-select ordering only; `apply_default_selection` ranks on the measured
  `sqs_points`, not on it.
- **More questions pre-tick.** Client Criticals are pre-selected up to `DEFAULT_SELECT_CAP`
  (28). The reported run's "11 selected" will rise by the number of missing client-side core
  facts (4 on his data). Well under the cap; nothing currently selected is displaced.
- **The Critical count will rarely be 0.** NAICS/SIC is essentially never printed on a
  declarations page, so an Agency Critical will fire on nearly every dec-page-led package.
  That is correct behaviour, but Brent should hear it from us rather than report it as a new
  defect.

### Still open, deliberately

- **The "satisfied by a PRIOR ANSWER" half of acceptance clause 2 is not live-observed.** The
  submission half is (Run B). The prior-answer half is unit-covered and rides the identical
  `answer_semantics.fact_answered` door one input earlier, so the risk is low - but nobody has
  watched a client answer a question and seen the Critical retire. **Five minutes closes it:**
  on a Run A session answer the FEIN question, reopen Send to Client, expect FEIN to disappear
  and the chip to read `4 Critical (2 agency)`. Recorded rather than claimed.
- **`ENABLE_CLASSIFICATION_SUGGESTIONS` is still `false`** (turned off 2026-08-25 under C3
  3.13, for reasons unrelated to this). Consequence now visible: we raise a Critical on
  nearly every submission for a code the broker must look up by hand, while
  `services/naics_suggester.py` - which proposes candidates from the operations description,
  and which Brent praised - sits switched off. One env var. Owner has not ruled.
- **The Tier 1 / Tier 2 lists themselves are unchanged (D-GB).** If a fact matters to an
  underwriter but is not on Brent's lists, it still will not be Critical. The upside of the
  one-source design: the day he adds one, it becomes correct on the score, the Review card
  and the questionnaire simultaneously.
- **`_hide_machine_worded_questions` still runs after the promotion** and can demote a
  promoted question to `suppressed`. That is correct - an unreadable machine-worded question
  should not be Critical - and is noted only so the ordering is not "fixed" later by mistake.

---

## THE WC BAND IS CLEAN LIVE. TWO MORE, BOTH IN THE "OTHER COVERAGE" ROWS
## 2026-09-07

Live run confirms the previous round end to end: **the WC block is completely
empty**, and the additional-insured "Y" now prints in the ADDL INSD column of
the GL row - the row that actually carries the policy - instead of on the empty
OTHER row. Producer/client contacts, certificate holder and the operations box
all correct on both forms.

### 1. AN ORDERING BUG I INTRODUCED

A naked `$1,000,000` printed in ACORD 25's auto limits column, one row under
PROPERTY DAMAGE, with no coverage named. Not the model's fault and not a missed
field - a guard ordering I created:

    _blank_unnamed_other_rows      runs early, sees the description present,
                                   correctly KEEPS its amount
    _drop_section_name_...         runs at the end, blanks that description
    -> nothing re-checks the amount, and the orphan ships

`_blank_unnamed_other_rows`' own comment names this exact failure: *"THE
HALF-FIX IS ITS OWN DEFECT: a naked amount in an OTHER row asserts a coverage
nobody can name."* I created a fresh instance of it by blanking a description
after that sweep had already passed. The sweep is now re-run whenever the
section-name guard removes anything; it is idempotent and only ever clears an
amount whose description box is now empty.

### 2. `LOB_NAME_OUT_OF_PLACE` IS EXACTLY INVERTED ON THESE ROWS

Found by my own regression test, not by a report:

    GL other-coverage row + "AUTOMOBILE LIABILITY"       -> KEPT
    GL other-coverage row + "Employee Benefits Liability" -> DELETED

Backwards in both directions, and pre-existing. `_LOB_NAMES` lists the genuine
specialty coverages that BELONG in an other-coverage row - employee benefits,
liquor, professional, fiduciary, errors and omissions, garagekeepers - and does
NOT list the section headers ACORD 25 actually prints (AUTOMOBILE LIABILITY,
UMBRELLA LIAB, EXCESS LIAB). On any other box the list is right; on these rows
it is precisely wrong, because here a coverage NAME is the correct content.

The `...OtherCoverageLimitDescription_` boxes now belong to
`_drop_section_name_in_other_coverage_row`, which reasons about the form's OWN
printed sections plus the title-word subset test, and `_LOB_FIELD_ALLOWED_RE`
steps aside there. `_LOB_NAMES` is untouched - it is correct everywhere else.

    SECTION HEADER "AUTOMOBILE LIABILITY"  -> removed, and its amount with it
    "Employee Benefits Liability"          -> kept, amount kept
    "Liquor Liability"                     -> kept, amount kept
    "UMBRELLA LIAB"                        -> removed, and its amount with it

Suite **6802 passed / 1 failed / 14 skipped** - the documented `httpx`
ImportError. Zero regressions.

| # | Decision | Reasoning |
|---|---|---|
| D-EU | **A guard that blanks a description must re-run the orphan-amount sweep.** | Blanking a description after the sweep leaves a naked amount - the defect that sweep exists to prevent. |
| D-EV | **The other-coverage rows are owned by the section-name guard, not by `_LOB_NAMES`.** | On those rows a coverage name is CORRECT content; the hand-list is inverted there and right everywhere else. |

---

## ACORD 25 CLEAN END TO END - 2026-09-07 (final round)

The live run confirmed the WC work: **the WC block is completely empty**, and
the additional-insured "Y" prints in the ADDL INSD column of the GL row - the
row that carries the policy - instead of on the empty OTHER row. Three residual
defects closed, two of them mine.

### 1. A guard-ordering bug I created

`_blank_unnamed_other_rows` runs early, sees the description present and
correctly keeps its amount; `_drop_section_name_in_other_coverage_row` then
removes that description at the end of the pass. Nothing re-checked, so a naked
`$1,000,000` shipped in the auto limits column. That sweep's own comment names
the failure - *"a naked amount in an OTHER row asserts a coverage nobody can
name"* - and I created a fresh instance of it. The sweep is re-run whenever the
section-name guard removes anything.

### 2. `LOB_NAME_OUT_OF_PLACE` is exactly inverted on these rows

Found by my own regression test, not by a report:

    "AUTOMOBILE LIABILITY"        (a section header)  -> KEPT
    "Employee Benefits Liability" (a real coverage)   -> DELETED

`_LOB_NAMES` lists the genuine specialty coverages that BELONG in an
other-coverage row and omits the section headers ACORD 25 actually prints. Right
on every other box, precisely wrong on these, because here a coverage NAME is
the correct content. The `...OtherCoverage(Limit)?Description_` boxes now belong
to the section-name guard; `_LOB_NAMES` is untouched elsewhere.

### 3. A designation box holds a NAME, not a sentence

`"Two leased delivery vans are operated under a long-term lease"` - true,
grounded, and narrative, in a box whose siblings read "Uninsured Motorist" and
"Symbol 19 - mobile equipment". The certificate already has a box for narrative
four rows down. A FINITE VERB separates a sentence from a name.

**PARTICIPLES ARE DELIBERATELY EXCLUDED, and the first cut got this wrong.**
"leased", "rented", "owned", "covered", "included" are adjectives in a
designation - *Leased equipment*, *Owned trailers*, *Rented premises*, *Covered
autos - symbol 8*, *Included endorsements* are all real entries and the first
verb list deleted every one of them. Only auxiliaries and third-person singular
forms make a sentence.

A section name in the paired AMOUNT box is cleared too: the ordinary amount
guards are deliberately permissive there ("Statutory", "Included", "See
schedule" are legitimate limits), so a coverage name walked straight through.

### 4. A street line repeating its own locality

ACORD 125's ADDITIONAL INTEREST printed `870 Wharfside Blvd Tacoma, WA 98421`
in the street box while CityName / StateOrProvinceCode / PostalCode each
correctly held Tacoma / WA / 98421 - the locality twice, once in a box that is
not for it. `_trim_address_line_repeating_its_own_locality` removes only a
TRAILING repetition of values that remain visible in their own boxes, so a
street legitimately named after its town (*Tacoma Avenue South*) survives, and
it declines entirely when trimming would empty the line. Generic across the
**39 distinct address-line fields** on all 17 schemas - the block is the field
name's own prefix, so there is no per-form list and no address parsing.

### Verification

* **Every wrong value this package has ever produced, replayed in ONE run with
  grounding quotes attached** - the condition that defeated two earlier fixes:
  **13 of 13 blanked**, and every correct value survives.
* **PROPERTY CHECK, 2,500 randomised ACORD 25 packages:** 0 WC boxes printed
  without WC evidence, 0 section headers surviving a description box, 0 genuine
  coverages deleted from a GL/umbrella row.
* **6,800 fuzzed generations across all 17 schemas** through the gap-fill
  envelope: 0 crashes. Plus 2,000 fuzzed address blocks: 0 raises.
* Suite green at the documented single `httpx` failure.

| # | Decision | Reasoning |
|---|---|---|
| D-EW | **A guard that blanks a description re-runs the orphan-amount sweep.** | Otherwise it leaves the naked amount that sweep exists to prevent. |
| D-EX | **The other-coverage rows belong to the section-name guard, not `_LOB_NAMES`.** | On those rows a coverage name is CORRECT content; the hand-list is inverted there and right everywhere else. |
| D-EY | **A finite verb marks narrative; a participle does not.** | "Leased equipment" and "Owned trailers" are designations - the first verb list deleted them. |
| D-EZ | **A street line never repeats the locality that has its own boxes.** | Trailing-only, declines if it would empty the line, so it can shorten but never lose. |

---

## BUG-04 - the ACORD 125 loss row - CLOSED, live-verified 2026-09-08

> Client: *"Do not force a required loss-row Date of Occurrence when 'Check if none'
> is selected."* Filed as "related" under the SYS-02 diagnosis and never built.

### Root cause - one class, three instances

**A name-shaped test that cannot tell a table CELL from a section SUMMARY box.**
`_acord125_row_started` used `startswith(prefix_) and endswith(_A)`, and three
ACORD 125 loss fields end `_A` without being row cells: the "Check if none" tick,
"for the last N years", TOTAL LOSSES. So ticking "no losses" marked the whole claim
row required - Required went **2 -> 7**, demanding a date of occurrence, a claim
date, a paid amount and a reserve for a claim that does not exist. The only state
that escaped was a wholly blank loss section, i.e. the one genuinely incomplete.
Exactly inverted.

**The same confusion reappeared TWICE inside its own fix** - in
`_resolve_phantom_schedule_row` (blanking the stated 5-year period; caught by the
owner's next run) and in a third reader, `_resolve_loss_overflow_remark` (caught by
review). The rule now comes from the SCHEMA - a base is row-scoped when the form
prints it with more than one row letter - and the registry decides cell-vs-summary.

### What shipped

| # | fix | where |
|---|---|---|
| 1 | row/summary split derived from the schema; a ticked box never raises a loss-row requirement | `pdf_service._row_scoped_bases`, `apply_acord125_missing_field_highlights` |
| 2 | the no-loss SENTENCE no longer prints as a claim. **One door, two callers** (stamp + phantom) so an emptied row can never fall through to gap fill | `loss_history_state.claim_rows`, `pdf_service._countable_schedule_rows` |
| 3 | a row named by `claim_number` / `claim_date` still prints - the first cut of #2 deleted real claims | `claim_rows`, printing side only |
| 4 | the overflow REMARKS box counts the same rows the grid prints | `_resolve_loss_overflow_remark` |
| 5 | `_attests_no_loss` delegates to `attested_true` - was a divergent copy, so "None" / "loss free" scored 60 while the box printed unticked | `pdf_service` |
| 6 | a no-loss claim carrying a **loss amount**, or an **exceptive connector**, contradicts itself | `normalization.detect_no_loss_assertion` |
| 7 | a time phrase is not a money threshold - *"no losses over the past five years"* was being discarded | same |
| 8 | a document DENYING it has loss runs is not a loss run; `never` denies on both sides of a phrase | `extraction_service._content_scores` |
| 9 | the SQS panel is marked stale while edits are unsaved, and a Refresh clears the marker | `PDFJsViewer.jsx`, `AcordModal.jsx` |
| 10 | `no_prior_losses` derivation is two-way (`elif`, never `else`) | `extraction_pipeline` - latent, hardening only |

### Live verification (owner, runs 1-5)

Claim grid empty and unhighlighted as generated; **40 -> 60 on tick, back to 40 on
untick**; a typed date yellows its row (the control); clearing it goes clean; the
5-year period and TOTAL LOSSES print; and the denial-wording file scores **40**,
not 60 with *"Loss runs attached"*.

**Runs 1-3 failed for reasons that were not the fix.** The score only updates on
Done Editing (#9), and the FIRST TEST KIT classified as a **loss run** - its own
filename matched `_FILENAME_SIGNALS["loss_run"]` - so the pillar took the
runs-uploaded path and the tick could not move it. A whole live run spent on the
wrong branch. The generator now re-reads its own PDF through `classify_document`
and refuses to ship one that lands anywhere but `application`.

### The "infinite phrasing" problem, and the honest limits

Owner: *"it can be anything, we cannot predict, there is infinite possibility."*
Right about LOSSES, not about GRAMMAR. What is unbounded is the loss ("a fire",
"the forklift thing") - which is why no peril list works and #6 names none. The
words JOINING "everything clean" to "this one thing" are a closed function-word
class (~15 exceptives). Two rules split the space: an exception naming a FIGURE is
caught with no vocabulary at all; one naming none is caught by the closed class.
Peril words were tried and REJECTED - they co-occur with the negation itself
(*"no claims or accidents"*) and refuse the attestations they were meant to protect.

**Not covered, recorded not hidden:** a LEADING exceptive (*"Other than the fire,
clean loss history"*) - checking the head would refuse legitimate preambles; the
classifier still counts *"unavailable"* / *": none"* (safe direction); an unlisted
exceptive attests, i.e. today's behaviour, never worse. **The document path was
never at risk** - a sentence in a PDF reaches the narrative tier (40) and can never
tick the box.

### D6 - scores move BOTH ways, tell Brent

**Down:** accounts attesting off a half-read sentence; packages credited with loss
runs on documents saying loss runs were not attached.
**Up:** genuine attestations phrased *"no losses over the past five years"* that
were being thrown away.

### Decisions

| # | Decision | Reasoning |
|---|---|---|
| D-BW | Row-scoping is DERIVED from the schema, never a list of exception fields. | A list is a fixture in disguise - right for the three reported boxes, silent on the next form. |
| D-BX | A column printed on only one row reads as a summary, and that is the safe error. | A missing highlight nags nobody; a false one demands a claim that does not exist. |
| D-CG | "No schedule" and "a schedule with no claims" are different answers. | Conflating them turns a filtered row into a gap-fill question, and the model reinvents the claim just removed. |
| D-CJ | A root word does not identify a table cell; the registry does. | The same shape was twice introduced BY a fix for the previous instance. |
| D-CK | The registry gate is scoped to the NEW branch only. | The `idx >= capacity` path judging by root is what suppresses C46's phantom vehicle rows. |
| D-CP | A no-loss claim is refused by the AMOUNT it carries, never by a list of perils. | Perils are unbounded and co-occur with the negation. An amount is structural and self-contradicting. |
| D-CQ | Exceptive CONNECTORS may be listed; losses may not. | Function words are a closed grammatical class, nouns are not. That distinction is the whole fix. |
| D-CR | A failing test that encodes a product ruling reverts the CODE, not the test. | A "buttons only" storage rule was built and REVERTED: `test_none_fills_a_negative_polarity_fact` is Brent's ruling that "None" is the affirmative answer on a negative-polarity fact. The buttons already exist - `answer_options` gives the fact two options and no `OTHER`, so the UI renders a select; only storage was permissive, and #6 closes the defect without overturning a decision. **Hard-refusing off-list text is a Brent call, on 2 facts.** |
| D-CS | Claim IDENTITY lives on the printing side, not in the shared gate. | The phantom row carries a status column; admitting status as identity in the shared definition resurrects the defect that gate exists to stop. |
| D-CD | A test generator must verify its own output through the product's readers. | Nothing about the PDF said "this reads as a loss run", and no amount of care reading it by eye would have. |

### Artefacts

`tests/test_acord125_loss_row_required.py` (46), `tests/test_loss_row_is_a_claim.py`
(60+), `tests/test_denied_keywords_do_not_classify.py` (27).
`scripts/make_bug04_test_pdf.py` - two files plus a self-check;
`scripts/verify_bug04_matrix.py` - the whole matrix offline, no upload, no API cost.
Blast-radius suite **821 passed / 0 failed**; frontend build clean. A full-suite
number is NOT claimed: `test_answer_options.py` and `main.py` changed mid-run, so
another process was editing the tree.

---

## BUG-06 - the correction modal - CLOSED, live-verified 2026-09-08

**Reported:** "Something went wrong applying your answer" on Umbrella Effective /
Expiration Date (`07/15/25`, `07/15/26`). **Found: seven defects behind one sentence.**
Six were never reported - the 500 hid them, because nothing downstream could be reached.

| # | Defect | Root cause | Fix |
|---|---|---|---|
| 1 | **Every producer answer in the product 500'd** except New Venture | `arq_service.py` bound `_nv_delete` only inside `elif canon == NEW_VENTURE_FIELD:` and read it on every path -> `UnboundLocalError`. Shipped in `d6d09c7` | Bind it up front, as the sibling `apply_arq_answers_to_session` already does |
| 2 | **5 dropdowns where EVERY option was refused** (`valuation_method`, `sprinkler_system`, `fire_protection_class`, `period_of_restoration`, `wc_xmod`; +2 partial) | `answer_semantics` step 0b returned the option LABEL verbatim, on a comment asserting it was canonical. The fact's `validate` is canonical, and extraction already writes that shape (`"valuation_method": "RCV"\|"ACV"\|null`) | Reduce the label to a value the fact holds, **testing each candidate against the fact's own validator** - generic, self-checking, no per-fact table |
| 3 | **A 500 never reached the browser** | Starlette puts `ServerErrorMiddleware` OUTSIDE `CORSMiddleware`, so the JSON 500 carried no `Access-Control-Allow-Origin`; `fetch` rejected and every caller's catch printed a generic string | Echo the origin from the SAME policy object the middleware uses (`_CORS_KWARGS` feeds both) |
| 4 | **Carrier-Grade COPE rendered twice** | `carrier_grade_cope_incomplete` missing from `_LEGACY_SUPERSEDED_BY_CODE` | Add the row - **after** widening the coded resolution to the legacy six |
| 5 | **A successful save reported as failed**; `"Other"` unusable on every choice field | `onApplied` sat inside the try; `isOther` was inferred from the value, so the first keystroke unmounted its own box | Move `onApplied` out; track Other-mode in state |
| 6 | **Answering the renewal umbrella card produced 2 unresolvable HARD STOPS** (SQS 60) | One fact key, two footings: `umbrella_*_date` is EXPIRING from extraction, PROPOSED when a human answers the card. The helper decided footing from `renewal_dates_routed` alone | Footing by **provenance** (`fact_state._HUMAN_SOURCES`); downgrade to warning when the package term is itself `derived`. Same fix applied to the Auto/WC sibling |
| 7 | **"Applied - but it raised a new issue"** on a fix that raised nothing | `_issues_bound_to_fact` keyed on the MESSAGE; COPE's "Missing: ..." list shrinks as fields are filled, so a shorter sentence read as a new issue | Key on the rule CODE; message rides along for display |

### Decisions

| # | Decision | Reasoning |
|---|---|---|
| D-GG | The option label is NOT canonical - the fact's own validator is. | Extraction and the validator already agreed on `RCV`/`ACV`. Storing the label would give one fact two shapes depending on who supplied it. |
| D-GH | Canonicalise by testing candidates against the fact's OWN validator, never a per-fact map. | A map is a fixture in disguise. This cannot emit a value the door then rejects, and a fact with no validator is untouched. |
| D-GI | `valuation_method` offers only RCV/ACV; Agreed Value and Market Value were REMOVED, not accommodated. | ACORD 140's tooltip lists four methods, but widening the fact means moving the extraction schema, the validator and the stamping map together. **Owner call, not a side effect of a bug fix.** |
| D-GJ | `"Other"` is refused at the door on every fact. | It is the affordance that reveals the free-text box. Stored bare it prints the word "Other" on a legal document - blank over wrong. |
| D-GK | Widen the coded COPE resolution BEFORE suppressing its legacy twin. | Measured: with coinsurance the only missing item, `evaluate_stops` emits ONLY the legacy warning - there is no dedicated coinsurance card. Naive suppression would have deleted the producer's only way to type it. |
| D-GL | A rule no correct answer can satisfy is the defect, not the producer. | Measured on #6: the proposed term hard-stopped, the derived proposed term hard-stopped, and only the EXPIRING term - the wrong answer to the question asked - cleared it. |
| D-GM | A human's STATED value is never hard-stopped against a value we DERIVED. | The proposed renewal term is computed and flagged `low_confidence` for confirmation. Capping at 60 because it disagrees with our own guess inverts who is authoritative. |
| D-GN | Issue identity is the rule code, never its sentence. | Messages embed lists that shrink as fields are filled. Re-learned here; already recorded in the `issue-diff-is-cluster-level` memory. |
| D-GO | A failing existing test that encodes the defect is REWRITTEN, not worked around. | `test_every_option_round_trips_as_its_own_value` asserted `value == label` - the false premise itself. Its real intent (never re-read a chosen option as a non-answer) was preserved. |
| D-GP | Replay the client's LITERAL input last. | Every test used four-digit years; the client typed `07/15/25`. It passes and is now pinned - a fix can clear every synthetic test and miss the reported case. |

### Also found while fixing

Four more dead rows in `_LEGACY_SUPERSEDED_BY_CODE`, caught by the new phrase-side
guard. One was a **live duplicate** (`umbrella_gl_period_misaligned` named a phrase no
engine emits - the real string is "policy periods misaligned"), so that pair had been
rendering twice all along. Three Auto/WC rows named messages the legacy engine has
never produced; removed, matching the file's own 2026-08-14 precedent.

### Artefacts

`tests/test_bug06_producer_answer_20260908.py` (82) - includes the **executable**
write-door test that did not exist (all three prior references assert on SOURCE TEXT,
which is how a NameError walked through 4,800 green tests), an AST guard for the
conditionally-bound-name class, the options<->validator contract over every catalogue,
and the non-renewal hard-stop regression guard.
`scripts/verify_bug06.py` - the whole matrix offline in 5s, no server, no upload;
exit 1 while broken, 0 when fixed. `scripts/make_bug06_test_pdfs.py` - ONE file
raising all four resolution modes at once, self-verified through the real warning engine.
Updated: `test_answer_options.py`, `test_h4_core_fact_matrix.py`,
`test_umbrella_aware_date_resolver.py`, `test_issue_resolution.py` (shape changes).
Suite **7140 passed / 1 failed** (the documented `httpx` ImportError) **/ 17 skipped**;
frontend build clean.

### Scores move UP - tell Brent (D6)

COPE, property and WC cards now apply at all (they were unresolvable); false 60 caps on
renewal umbrella packages are gone. Live run: package **66 -> 76**, ACORD 125 **79 -> 85**,
Property Integrity **50% -> 90%**. The residual 85 is `SOFT_STOP_CAP` from the missing
vehicle/driver schedules - genuine, and an artefact of the fixture carrying no fleet.

### Not done - owner calls

- Collapsing the **8** "For Carrier-Grade COPE provide: ..." recommendation cards, and
  reconciling the **three** different definitions of Carrier-Grade COPE (legacy warning 6
  fields, coded warning 4, recommendations 8). Each card carries score credit, so merging
  them moves scores.
- Widening `valuation_method` to Agreed Value / Market Value (see D-GI).


## BUG-01 / BUG-02 / BUG-03 - questionnaire progress, the two badges - CLOSED, live-verified 2026-09-08

> Client: questionnaire showed **"1/11 - 9%"** and *"Auto-saving in progress"* before
> the client answered anything; an unexplained green **"1"** on the help/contact
> control; producer workspace showed **"Sent to Client (2)"** on a session that had
> sent nothing.

### Root cause - ONE class, three faces

**Progress measured whether a field HELD content, not whether the CLIENT put it
there.** A schedule question ships PRE-FILLED with the rows extraction found (by
design - the client edits a known fleet instead of retyping it), so our own
pre-fill counted itself. Scalars could never do this: both serializers hard-force
`current_value: ""`. Tables were the one path nobody applied that rule to.

Same confusion three layers deeper, none of it reported:
- an untouched pre-filled table posted back, overwrote `facts`, re-stamped the
  forms and wrote a **`client_arq` audit row** for rows the insured never scrolled to;
- the receipt told the client *"2 vehicles provided"* for that table;
- `fields_answered_count` was `len(posted_answers)`, and the page posts every
  question back - so it had always been the question count wearing a label.

**BUG-02** was the same counter: the badge was absolutely positioned but a SIBLING
of the Submit button inside a `position:fixed` stack, so it anchored to the
stack's corner - the "Contact Your Agent" card.

**BUG-03 was a different object entirely.** The badge read `/api/arq/notifications`
- rows written when a client SUBMITS, i.e. inbound, on an outbound button - and
that query is `WHERE user_id=$1` with **no session filter**, so a workspace
inherited submissions from every other package. `POST /api/arq/notifications/read`
had **no caller anywhere in the frontend**, so it could only ever count up.

### The rule (one door, browser and server)

> A question counts when the client **touched** it AND there is content on one
> side or the other - theirs now, or ours that they cleared.

Both halves load-bearing. Touch alone counts a box typed-in-then-emptied; a
seed-vs-now diff alone UNCOUNTS delete-then-retype-identical, the one direction a
progress bar must never move. `touched` is STICKY. The server re-derives the same
verdict from its OWN copy of the seed, so the browser's list can only ADD the two
cases the seed cannot see (emptied, or changed and changed back).

### What shipped

| # | fix | where |
|---|---|---|
| 1 | the progress rule, pure and shared by ring / badge / card styling / receipt | `utils/questionnaireProgress.js` (new) |
| 2 | seed frozen at load; touch recorded by DIFFING prev vs next in the ONE `setAnswers` choke point | `ClientQuestionnaire.jsx` |
| 3 | draft stores ONLY touched fields, so its key set IS the touch record across a reload - no new column | same + `saveDraftToServer` |
| 4 | an untouched pre-filled table is never stored as a client answer | `arq_service.client_supplied_schedule` |
| 5 | an EMPTIED pre-filled table IS stored - it is the answer "we do not have any", and was being silently dropped | `submit_arq_answers` |
| 6 | receipt: presence AND content decide; emptied reads *"Confirmed none - the pre-filled X were removed"* | `arq_receipt_service` |
| 7 | `fields_answered_count` and the activity-log `fields` both count what the server ACCEPTED | `arq_routes` |
| 8 | badge wrapped with the Submit button in a `position:relative` parent | `ClientQuestionnaire.jsx` |
| 9 | producer badge reads `openArqCount(arqSessions)` - per-session, status `pending`, not expired | `utils/arqStatus.js` (new), `AcordModal.jsx` |
| 10 | `InfoTip` split into `useTipPopover` + `TipBubble` + new `HoverTip`; badge tooltip is the SQS popover, not a native `title` (~1s delay), and FLIPS above when short of room | `AcordModal.jsx` |
| 11 | progress breakdown moved into the dark header as three chips | `ClientQuestionnaire.jsx` |

### Live run 1 found the fix was incomplete - the rest of the row survived the row

Deleting both vehicles blanked year/make/model/VIN and kept printing a **garaging
address, a $1,000 collision deductible and a full set of ticked coverage boxes**.
"Schedule-bound" meant the columns the capture table binds - **9 of ACORD 127's 67
per-vehicle fields**. The other 58 came from Pass 1 and answered to nobody once the
row was gone. `_clear_orphaned_schedule_rows` sweeps them.

### Then the sweep itself was destroying applicant data - CAUGHT BY AUDIT, REPRODUCED

`row_family_roots` guarded against a root claimed by TWO schedules. It never asked
whether a root ALSO carries applicant-level fields wearing ACORD's universal `_A`
suffix. **It does:** `BusinessInformation` (a real `property_locations` root) holds
the 12 nature-of-business checkboxes and the parent organisation name; `LossHistory`
holds the **No Prior Losses attestation**. So *"we have no separate locations"*
erased a contractor's own trade classification, and *"no claims"* erased the tick
the score reads.

**A ROW LETTER IS NOT A ROW INDEX.** A field is part of a repeating row only when
its base name appears at MORE THAN ONE row letter on that form. Measured: protects
15 applicant fields on ACORD 125 locations and 3 on its loss history, costs nothing
on 127 (all 67 vehicle and 20 driver bases are genuinely multi-row).

### And a pre-fix draft reintroduced the whole bug

Touch was DERIVED from the draft's keys. The old code stored the WHOLE answer map,
pre-fill included - so any questionnaire open at deploy restored everything as
touched, showed 1/11 again, AND posted the pre-fill back as a client answer.
Drafts now carry `__draft_touched_v2__`; unmarked (legacy) drafts fall back to
"touched only where the value DIFFERS from the seed".

### Also fixed, reported live

`YEAR_RE` is `^(19|20)\d{2}$`, but the message said *"must be a 4-digit year"* - so
typing `2122` produced an error naming a rule the value already satisfied. Now
**"must be between 1900 and 2099"**, on both copies. Rule unchanged.

### Live verification (owner, 3 rounds)

Ring **0/8 - 0%** at open, no auto-save bar, no badge. Counts 1/2/1/2 through
answer / not-sure / clear / retype. Pre-filled table untouched = no change; edit
+1; **change-back, delete-both, retype-identical all held**. Empty driver table
add-then-delete = no change. Reload and incognito preserved everything. Receipt
*"Confirmed none - the pre-filled vehicles were removed"*. Producer row **"3 answers
submitted by client"** (not 8). ACORD 127 vehicle rows blank INCLUDING garaging and
deductibles; keep-one/delete-one left row 1 whole. Badge absent before sending,
tracked open requests up and down, hover instant and flipped above. **A brand-new
session shows no badge** - the cross-session leak, the only proof of BUG-03's root
cause. Year error reads the new sentence.

### Standing lessons

1. **Fix the layer the screen reads.** `components/arq/ARQStatusPanel.jsx` is
   imported by NOBODY - the live panel is defined inline in `AcordModal.jsx`. The
   first expiry fix went into the dead copy. **Kept as-is on owner's call**; delete
   when the tree is clean.
2. **A guard that proves one thing does not prove the other.** "No two schedules
   claim this root" said nothing about applicant data under the same root.
3. **Derived state has a version problem.** Reconstructing the touch record from
   draft keys was correct only for drafts the new code wrote.
4. **Fix one copy of a rule, its twin stays broken.** `fields_answered_count` was
   fixed and `record_event`'s `fields` - one line below - was not. Audit caught it.
5. **A message must describe the rule it enforces**, or the user cannot act on it.

### Artefacts

`tests/test_questionnaire_progress_20260908.py` (55) - proven to bite: removing the
row-letter guard fails 4. `scripts/make_bug01_03_test_pdf.py` -> `bug01_03_test_data/`,
ONE self-verifying PDF (fails the build if the fleet stops reflowing as rows, or if
any of ten forbidden words leaks in and deletes a question) plus the numbered steps.
Frontend has **no test runner**; the two browser modules are pure and were driven
under node (25 + 30 checks). Suite **7263 passed / 1 failed** (the documented `httpx`
ImportError) **/ 17 skipped**; frontend build clean.

### Not done - owner calls

- Blocker 1 is proven offline and by 4 biting tests, and its code path ran live, but
  the NATURE OF BUSINESS boxes sit on a later ACORD 125 page and were never
  visually confirmed. One screenshot would close it.
- `CommercialVehicleLineOfBusiness_GarageStorageDescription_A` still prints after an
  emptied fleet. **Correct** - it is line-level, not per-vehicle; deleting it would
  be the same over-reach as the applicant-field bug. Worth a producer's eye.
- The audit hit its session limit on 3 of 13 agents (BUG-01 safety + tests skeptics,
  and the synthesis). The 10 that ran found both blockers.

---

## BUG-05 - remediation actions returning Network / unsupported-action errors - CLOSED, live-verified 2026-09-08

**Report (P0):** normal remediation returns red errors. One card answers *"Network
error. Please try again."*; another offers a direct-answer box and Submit, then
rejects it with *"This item can't be answered directly."*

**Six defects. Three from the report, THREE the owner's live runs exposed.**
All four acceptance clauses met and seen on screen.

### The class

Answerability was **inferred at the display layer instead of declared at the
source**. `AcordModal` used `answerable = !!rec.field`; the server used
`arq_service._canonical_key`. Two layers, two definitions of one predicate. The
identical contract had existed on the ISSUE side since 2026-08-08
(`issue_registry.RESOLUTION_MAP` + two guards in `test_legacy_rules.py`);
recommendations were never brought under it.

### 1 - "Network error" was a 500 the browser was not allowed to read

`_nv_delete` was bound only inside `elif canon == NEW_VENTURE_FIELD:` and read on
EVERY path at the tail of `apply_producer_answer_to_session` -> `UnboundLocalError`
on every fact except New Venture (commit `d6d09c7`). Starlette builds
`ServerErrorMiddleware -> user middleware (CORS) -> router`, so an app-level
`Exception` handler's response is produced OUTSIDE `CORSMiddleware` and never gets
`Access-Control-Allow-Origin`. **Measured on this repo's Starlette 0.50.0: a 200
carries the header, a 500 does not.** Cross-origin the browser discards it, `fetch`
REJECTS, and the catch block prints "Network error". Fixed in the prior session -
`scripts/verify_bug06.py`.

### 2 - the narrative card named a read-only alias

`rec_narrative_components` / `rec_narrative_substance` declared `acord101_remarks`.
The writable fact is `additional_remarks_text`. Box drawn, answer refused, on every
package with a narrative gap.

### 3 - NOT REPORTED, AND WORSE: a typed scalar destroyed an extracted table

`rec_auto_vin_schedule` / `rec_wc_class_codes` name LIVE CAPTURE SCHEDULES. The card
drew a one-line box; typing replaced the whole fleet with that string and printed
**"Resolved"**. Reproduced before the fix.

### 4 - blockers with nothing to click

Four cap-gate sentences had no `_LEGACY_MESSAGE_RULES` row, so they rendered under
"Other validations" with no fix control. Two were internal rule names printed to a
broker: **"Property integrity gate"**, **"Property integrity warning"**.
**The anti-rot harvester could not see them** - it AST-walks `evaluate_stops`'
`append` sites, and the gates pass their sentence to `_resolve_cap` instead. They
became visible to producers on 2026-08-31 and the build stayed green.
Also: `reopen_issue` shipped the stop ARRAYS with no `grouped_issues`, so the
pre-form banners fell back to dead text.

### 5 - LIVE RUN: a false statement to a broker

`sqs_service` emitted `"Umbrella detected but no underlying GL/Auto limits"` whenever
the pillar hit 0. The pillar reaches 0 TWO ways - genuinely no underlying, or
ordinary deductions stacking past 100. The 60-cap gate was corrected for exactly this
on 2026-08-31 via `_umbrella_has_underlying`; **this sibling was left behind**, so one
screen showed both, on a package plainly stating $300,000 GL and $300,000 auto CSL.
The card was worse than the sentence: *"Provide underlying limits"* - values already
on file - while the missing umbrella limit went unasked. Reproduced by running the
scorer, not by reading.

**Third copy found while fixing it:** `evaluate_stops` had its own hand-written "is
underlying stated" test. It tested the raw string while the door parsed to an int, so
on the four conventions an ACORD document really uses - `"Included"`, `"Statutory"`,
`"See schedule"`, `"$0"` - **all four disagreed**. Split into two honestly-named
questions: `_umbrella_has_underlying` (NUMERIC, pillar only - widening it moves every
umbrella score) and `_umbrella_underlying_stated` (PRESENCE, every wording site). No
score moved.

### 6 - LIVE RUN: two more, both mine

- The **package** HARD STOPS block was text-only. Only the per-form one had been made
  clickable. Both now ship `cap_hard_stop_items`.
- That match was **byte-exact** on the message. `cross_form_validator` appends
  `"(Affects: ACORD 140. Fix: ...)"` AFTER the issue is captured, so the box lost its
  Open to fix again. `issue_registry._present_in` has used a PREFIX rule for this
  since it was written; now this does too.

### 7 - LIVE RUN: an answer that saves but does not close the gap

The umbrella card names four things. Supplying one saves the value, and
`mark_recommendation_answer_recorded` deliberately does not stamp `action` - so it
never reaches Reviewed either. The card was optimistically moved to Reviewed, then
`loadDismissedRecs` reconciled it straight back out: **gone from Open AND from
Reviewed, with no acknowledgement**. Now the server's `open_recommendations` decides,
the card stays open holding the typed value, and says *"Saved. This one needs more
than one value, so it stays open."*
Also: the narrative textarea had **no keyboard submit at all** (every other card
submits on Enter; Enter is a newline here). Ctrl+Enter now submits.

### The fix - one door, four declared modes, nothing invented

**`services/answer_routing.py`** answers "what can the producer do with this item?"
returning the FOUR modes the inline-resolution feature already speaks -
`field` / `schedule` / `narrative` / `none` - so `ResolutionModal`, `resolve_issue`
and `ScheduleTable` needed no new concepts.

**Every rule is DERIVED from a declaration we already maintain**: `_canonical_key`,
`schedule_capture.SCHEDULE_DEFS`, `narrative_facts.NARRATIVE_FACT_KEYS`, the
extraction schema's `"key": [{` (a table) vs `[string]` (typeable), and
`FACT_REGISTRY[...]["validate"]` (somebody wrote the reader for a typed value).
**No allow-list of known-bad names anywhere.** Unknown resolves to `none`, never a
typed box.

- The scorer stamps `answer_mode` on every rec it returns; the card renders what it
  is told. A session scored before this carries no `answer_mode` and behaves exactly
  as before.
- `POST /api/audit/answer` re-decides the mode server-side and never trusts the wire.
  Narrative answers APPEND via `arq_service.append_producer_narrative` (extracted
  from `resolve_issue`, so the two cannot drift).
- **The write door itself refuses a typed scalar over a POPULATED table**, so the
  resolution modal and the held-client-answer review are covered too. Narrow: a
  non-empty list of DICTS with no declared validator. An EMPTY row fact still takes a
  typed answer; a list of STRINGS is never protected (`lines_of_business`);
  `auto_covered_symbols` keeps its `parse_symbols` free-text path.
- The property gate names its own cause (`_prop_hard_because` / `_prop_soft_because`),
  phrased so `classify_legacy` matches and the row inherits a real fix. Three rows
  added; the BI one was being SHADOWED by the generic "Business income limit" FORMAT
  row.
- `audit_routes._form_selection_view` - the grouped view travels with the stops on
  every panel-refresh response. `BareStopRow` is the floor underneath it.

**Dead code left in place by owner instruction** - the legacy `!!rec.field` render
fallback, the text-only cap-block fallback, and every pre-`answer_mode` path stay, so
a session stored before this renders exactly as it did.

### Standing lessons

1. **An anti-rot harvester is only as wide as the emission path it walks.** Four
   unfixable blockers shipped with a green build because the cap gates reach
   producers through `_resolve_cap`, not through `evaluate_stops`' `append`. **When
   you add a new way to SURFACE something, extend the harvester in the same commit.**
2. **Fix one copy of a claim, its twin stays broken.** The umbrella conflation was
   corrected in the gate and left in the Key Issues line and the card - and a THIRD
   copy sat in `evaluate_stops` disagreeing with both.
3. **Two questions that sound alike need two names.** "Can I read this as a number"
   and "is it mentioned at all" are not the same question; one implementation
   answering both moves scores the moment you widen it.
4. **Byte-exact message matching is a trap** - messages get suffixes appended
   downstream. The prefix rule already existed one module over.
5. **An answer that saves but does not resolve must SAY so.** Silence reads as
   failure, and the optimistic-then-reconcile pattern can delete a card from both
   lists.

### Artefacts

`services/answer_routing.py` (the door). Tests: `tests/test_answer_routing.py` (58,
driving the REAL scorer over all 17 real schemas with every coverage flag on) and
`tests/test_legacy_rules.py` (+3, now 78: `_harvest_cap_gate_reasons` closes the
harvester blind spot; no cap sentence may be an internal rule name;
`_prop_hard`/`_prop_soft` may only be raised through the helpers that record the
reason). Every guard proved to bite by reverting its fix.
`scripts/verify_bug05.py` - offline before/after check, no server, no upload.
`scripts/make_bug05_test_pdfs.py` -> `bug05_test_data/` - TWO self-verifying
packages, 13 numbered checks. Two is the floor: a schedule card fires only when the
schedule is ABSENT (so "it opens a table" needs an empty fleet and "the rows survive"
needs a populated one), and the cap ladder COPE -> umbrella -> property means an
umbrella cap SHADOWS the property sentence inside its own package.
Suite **7264 passed / 1 failed** (the documented `httpx` ImportError) / 17 skipped;
frontend build clean.

### Not done - owner calls

- **The WC class-code table was never seen live.** Same code path as the vehicle
  table (verified live end to end) and pinned across all 17 schemas, but the WC
  table's own column set - `description` + `payroll` required, `code` and `rate`
  producer-only - has not been rendered by a human. 60 seconds whenever an ACORD 130
  next appears.
- ACORD 101 was not generated in the final run, so the narrative APPEND was confirmed
  by the card going Resolved twice rather than by reading both paragraphs off the PDF.
- `period_of_restoration` and `business_income_limit` print on **no ACORD form** -
  verified across all 17 schemas. Scoring facts only. Do not send anyone looking for
  them on the 140.

---

## PROD-02 - Two documents printing different BOILERPLATE are not a conflict - SHIPPED 2026-09-09

**Client:** the pre-form **IMPORTANT** band - the 5-second "fix these first" shortlist -
led with

> *"Conflicting values for Specific Wording Requirements across documents - Dec Page: If
> the insured's whereabouts for service of process cannot be determined through reasonable
> effort, the insured agrees to designate and irrevocably appoint us as the agent of the
> insured for service of process, pleadings or other filings in a civil action brought
> against the insured., Certificate of Insurance: If the certificate holder is an
> ADDITIONAL INSURED, the policy(ies) must have ADDITIONAL INSURED provisions or be
> endorsed. If SUBROGATION IS WAIVED... **Fix:** Review and confirm the correct value."*

Their ask was framed as a product decision - *"confirm the business rule; if it is
informational or policy boilerplate, downgrade or remove it."* **It was not a product
decision.** It was a defect with a root cause already named in this repo.

### Neither side was ever a value

The first is a **service-of-process policy CONDITION** - legal housekeeping present in
essentially every carrier's wording. The second is the **ACORD 25's own PREPRINTED
FOOTER**, printed on every certificate ever issued before anyone types into it.

There is no correct value to confirm. They are not two answers to one question.

### Root cause - the comparator, not the paragraph

`extraction_service.detect_source_conflicts` compared **normalised strings** and read "not
identical" as "conflict". Two paragraphs are essentially never identical, so on a prose
fact it fired every time.

**`fact_comparison.py`'s own header has recorded this since C1 (2026-08-21).** Of the five
places that decided *"do these documents disagree?"*, it listed what each one had:

```
underwriting_consistency  (the Data Consistency picker)   equivalence filter: yes
sqs_service.check_doc_consistency                          3 of its 8 fields only
extraction_service.detect_source_conflicts                 none          <-- this one
sqs_service._check_loss_run_insured_match                  FEIN + policy compared raw
extraction_service._consolidate_property_locations         its own address regex
```

**"none."** It was named as the worst offender and was the only one never migrated. The
build guard (`test_comparison_has_one_owner.py`) watches three function names -
`values_conflict`, `distinct_normalized`, `entity_identity_conflict` - and this site
imports `normalize_value`, which is not one of them, so it passed the build for 19 days.

### The rule it was missing was already shipped, and it is the client's own

The client said this on **2026-08-17**, about Additional Remarks:

> *"A paragraph containing policy numbers, dates, limits, premiums, exclusions, etc. should
> not be treated as one competing value. The individual facts within it need to be
> interpreted in their appropriate context."*

We answered it in two halves, both live since C1: `fact_equivalence._PROSE_WORD_FLOOR`
(*"nobody picks between two true paragraphs"* -> INCOMPARABLE), and `narrative_facts.py`,
which mines the STATEMENTS inside a paragraph so it can EXPLAIN a conflict rather than be
one. **`detect_source_conflicts` simply never asked.** Proof on the client's literal text:

```
word counts: 45 and 37   (prose floor = 25)
TODAY   (normalize_value only)  -> 2 distinct values  => CONFLICT RAISED
ONE DOOR (fact_comparison)      -> incomparable       => NO CARD
```

### The fix - a SECOND gate, never a replacement

New `extraction_service._door_conflict`. The original distinct-normalised test still runs
first; the door is asked **only when that test already says conflict**, so a card needs
BOTH to agree. Both gates are suppressive, so the net effect is strictly one-way: nothing
suppressed today can start firing, and no new card can ever appear.

**That ordering is load-bearing, and the first attempt got it wrong.** Replacing gate 1
re-opened the carrier-alias suppression - `"Employers Mutual Casualty Company"` vs
`"EMC Property & Casualty Company"` started drawing a card - because the door groups entity
names on `strict_entity_key` and **deliberately not** on `normalize_carrier` (its own
comment: Round 10 fix 46 - folding aliases there would pronounce two real carriers
consistent before the typed comparator ever saw them). **Caught by the suite, not by
reasoning**, and now pinned by `test_the_door_can_only_remove_a_card_never_add_one`.

Also wired: the package's `PackageContext` is built once and passed in, so two printings of
one policy number are not read as two policies; and the door's `_usable` drops a **rating
bureau standing in for an insurer** (AAIS was in the client's own carrier card).

### Blast radius, measured not assumed

Exactly **6 of 176** registry facts are narrative-kind and therefore stop raising a
source-conflict card: `operations_description`, `additional_remarks_text`,
`account_description`, `certificate_description_of_operations`,
`wc_description_of_operations`, `garage_operations_type`. Every **enumerated** text field
still competes - `construction_type`, `entity_type`, `valuation_method`, `occupancy_type` -
which is the boundary that matters and is pinned from both sides (here, and
`fact_equivalence.test_no_enumerated_type_field_is_treated_as_narrative`).

A genuinely different INSURED is still caught by `applicant_name`, which is a hard stop.

### What this fixed, in one change

| Complaint | Result |
|---|---|
| Boilerplate card exists | Gone - never raised |
| Ranked #1 in IMPORTANT | Gone with it; no tier change needed |
| Said "Fix:" but had no control (`mode: none`) | Gone with it |
| Capped the SQS at 85 | Gone with it |

**D6 - scores go UP.** Fewer soft stops on any multi-document package that hit this.
Brent sees the numbers before it ships.

### Checked and deliberately NOT changed

- **The boilerplate is still stored as a fact.** `risk_transfer.specific_wording_
  requirements` still holds the ACORD 25 footer. Traced every consumer: `sqs_service.
  risk_transfer_check` is its only reader and **has zero callers anywhere in the backend,
  and the frontend has no reference to `risk_transfer` at all** - the advisory checklist is
  dead code. The value never reaches a screen or a form, so a boilerplate-detection
  heuristic (which could drop a GENUINE wording requirement) buys nothing today. Named
  here rather than fixed blind.
- **The IMPORTANT tiering.** See "Still open, deliberately" - owner's call.

Tests: `backend/tests/test_prod02_prose_conflicts.py` (28), including the client's literal
paragraphs, the top-level prose shape, an assertion through `build_grouped_view` (the layer
the screen reads), a spy proving both code paths actually reach the door (the seam, not the
function), the gate-ordering property, and the fail-open direction. Suite
**7460 passed / 1 failed / 21 skipped** - the one failure is the documented `httpx`
ImportError. Zero regressions.

### LIVE VERIFIED 2026-09-09 - session `299cd414`, and NOT by the screenshot

`prod02_test_data/` (2 files, one session). On screen: **no wording card anywhere**, while
`Mortgagee Name` and `Certificate Holder Name` both still raised their conflicts, `Loss
Payee` stayed silent on two printings of one name, the carrier alias folded to one
`Employers Mutual Casualty Company` on both policy rows, and the policy number labelled
itself *"2 POLICIES, 2 VALUES - NOT A CONFLICT"*. IMPORTANT now leads with the auto-symbol
gap and the missing vehicle schedule in 2 of its 3 slots.

**A screenshot cannot tell a fix from an absent fact**, so the session was read back
(`scripts/dump_session_facts.py`). The fact was populated on BOTH documents, and the two
values are not the two this kit planted:

```
P1_dec_page.pdf   14 words  "Additional insured status is provided where required by
                             written contract executed prior to loss."
P2_certificate.pdf 37 words  the ACORD 25 preprinted footer, verbatim
```

The model preferred the shorter, more relevant sentence on the dec page over the 45-word
service-of-process clause. Replaying the REAL values through both gates:

```
GATE 1 (the old code)  2 distinct normalised strings  ->  WOULD HAVE FIRED
GATE 2 (the door)      verdict = equivalent           ->  no card
```

**That is a stronger proof than the kit was designed for.** Only ONE side cleared the
25-word prose floor (`is_prose` False / True), so the suppression came from the
narrative-KIND merge rather than the floor - a harder case than the client's, where both
sides are paragraphs. The client's exact both-sides-prose pair stays pinned by
`test_the_clients_two_boilerplate_paragraphs_raise_no_card`.

### Found by the live run, PRE-EXISTING, and NOT PROD-02

**One conflict, two screens, contradictory instructions.** `Certificate Holder` and
`Mortgagee Name` each render as a Data Consistency picker row (radio buttons, both source
files, a working **Confirm**) AND as a warning card saying *"it can't be applied
automatically"* - one panel apart. Extraction writes these names in TWO places, top-level
(`certificate_holder`, `mortgagee_name`) and nested under `risk_transfer`;
`_auto_scalar_keys` auto-discovers the top-level scalars into the picker's `skip_fields`
and cannot see the nested copies, so each engine owns one. **UI-13 does not catch it** -
that suppression keys on `underwriting_reconciliation_*` and these carry
`source_conflict_*`. Same defect, different door. Both engines behaved this way before
2026-09-09; the kit only made it visible by putting two clean conflicts on one screen.

**Standing lesson:** `fact_comparison.py` listed this exact site as unmigrated, in its own
header, for 19 days. A migration is not finished while its own docstring still names a
holdout - and a build guard that watches three function names cannot see a fourth.
