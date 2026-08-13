# LLM Call Registry & Cost Issues

**Purpose:** single source of truth for every place Primble talks to an LLM, what each call
costs, and every known inefficiency. This file exists because a cost audit found ~80% of
input spend was byte-identical text being re-uploaded on every call, and nothing in the
codebase measured token usage at all.

> ## MAINTENANCE RULE
> Any PR that adds, removes, or modifies an LLM call, edits a prompt, or changes
> batching/chunking **MUST update this file in the same commit.**

**Line numbers drift.** Each entry names the *function*, which is stable — grep for the
function name rather than trusting the line number.

**Model:** `gpt-5.4-mini` — **400,000-token context window**, **128,000-token max output**.
The context window is shared by input and output. Our own output cap
(`FORM_FILL_MAX_TOKENS`) is 16,000 — a cost/rate guard, far below the model's limit.
Measured tokenizer ratio on a real 271-page package (o200k_base): **4.01 chars/token**.

**Pricing:** **$0.75 / 1M input**, **$4.50 / 1M output**.
Cached input bills at roughly 10% of input price. **Output is 6× input**, so wasted output
tokens hurt disproportionately.

---

## 0. Handoff / current state

**`HANDOFF.md` (repo root) is the entry point for anyone new to this work.** It carries the
problem statement, everything fixed on 2026-07-30, the measured before/after, the three
separate chunkers and their limits, and the ranked open-issue list.

**Three chunkers exist and they do NOT share a limit.** This has confused every reader so
far, so it is stated here once:

| Stage | Limit | Origin | On a 683,601-char doc |
|---|---|---|---|
| Extraction | 56,000 chars | Derived (**C31**, was a hand-typed `100_000`): `min(quality, capacity)` where quality = `EXTRACTION_DOC_TOKENS_PER_CALL` (14,000 tok) and capacity = the window minus overhead and reply reserve. **Quality binds; capacity is 20x larger.** | 14 chunks |
| Gap fill | 899,393 chars | Derived: `(400,000 tok x 0.75 - 16,000) x 3.5`, minus reply reserve/prompt/fields block | 1 chunk |
| Compliance | same budget | own arithmetic, same inputs | 1 chunk |

Gap fill makes ~46 calls on that document not because the document is split, but because
1,104 general fields / 40 + 131 compliance questions / 10 = 46 **field** batches. Each call
carries the complete document.

**The inconsistency is not academic:** extraction's 14k tokens/call behaves well; gap fill's
170k tokens/call is where C21 degradation was measured. The extraction number was accidentally
the safer one. It is now *derived and clamped* (C31) but deliberately **still 14k** — deriving
it was about provenance and a capacity guard, NOT about scaling it up. Raising it toward
capacity would trade a known-good stage for ~$0.11 a run. Do not.

---

## 1. LLM call-site inventory

Verified by grepping `groq_chat(`, `completions.create(`, `messages.create(` across
`backend/`, excluding `venv/` and tests. **11 application call sites.**

### Hot path — fires on every form generation

| File | Function | Fires | Output cap | Cached |
|---|---|---|---|---|
| `services/pdf_service.py` | `_chat_json` (inside `_fill_unmatched_with_gpt`) | **once per field sub-batch × doc chunk — dominant cost** | 16000 | ✅ since 2026-07-29 |
| `services/extraction_service.py` | `extract_facts` | once per document chunk | 16000 | ✅ prefix-first |

`_chat_json` serves BOTH hot-path stages and tags each with a `stage` label that appears in
its `LLM_SPEND` line and its `prompt_cache_key`:

* `stage=gap_fill` — the general field fill (`_PROMPT_SKELETON` system prompt).
* `stage=compliance` — the dedicated Yes/No pass (`_COMPLIANCE_SYSTEM_PROMPT`).

They are **separate cache families** because the system prompt differs. That is correct and
expected; do not try to merge them.

`_chat_json` also contains a second `create()` call — a `json_object` fallback used **only**
for a genuine `response_format` rejection. See C7.

### Conditional — fires only on specific conditions

| File | Function | Fires | Output cap |
|---|---|---|---|
| `services/extraction_service.py` | `_safe_json_parse` | **JSON repair** when a reply won't parse (up to 2×) | 4096 |
| `services/extraction_service.py` | reconciliation | only on cross-document fact conflicts | 4096 |
| `services/pdf_service.py` | `_fetch_umbrella_period_sync` | only when ACORD 131/25 is selected **and** extraction already missed the umbrella dates — then once per document chunk until both are found (usually 1) | 500 |
| `services/arq_service.py` | `_humanize_field_names` | ARQ question generation (module-level cached) | 1500 |
| `services/arq_service.py` | `_classify_other_reason_adverse` | producer selects "Other" reason | 5 |

### Download-time only — never during generation

| File | Function | Output cap |
|---|---|---|
| `services/cover_service.py` | cover page generation (2 sites) | 4096 |
| `services/sqs_service.py` | `generate_sqs_narrative` | 1024 |

**`generate_sqs_narrative` prompt edited 2026-08-12** (same single call, no cost change;
prompt a few words longer, replies typically shorter): the model is now FORBIDDEN from
restating the numeric score / tier / point totals - the UI renders the live number, and
prose that restates it can only agree by luck (client screenshot: banner 66/100, summary
paragraph "scores 63/100" on the same screen). The score/tier stays in the prompt as
context. Paired fix in `routes/audit_routes.py`: the endpoint now feeds this call the
PACKAGE result (the same object the banner renders) instead of the first form's per-form
result, which was the source of the 63.

### User-triggered chat bots — AUDITED CLEAN, do not investigate again

| File | Endpoint | Output cap |
|---|---|---|
| `routes/assistant_routes.py` | `POST /api/assistant/chat` | 400 |
| `routes/arq_routes.py` | `POST /api/arq/chat/{token}` | 300 |

Both are POST-only, require auth or a valid unexpired ARQ token, clamp history to the last
6 messages, and are tightly capped. **`services/scheduler_service.py` contains zero LLM
calls** — it only runs DB cleanup. Neither bot can fire unattended. They were suspected of
background spend during the audit and definitively cleared.

### Dead code

| File | Note |
|---|---|
| `services/pdf_service.py` | `_fill_empty_from_raw_text` — the pre-`_fill_unmatched_with_gpt` fill, marked "Do NOT call this function". **Zero callers, verified by grep across the repo.** Costs nothing; candidate for deletion. Its prompt still contains the old "return JSON null" convention — deliberately left alone rather than edited, since editing dead code is pure risk. |

---

## 2. Cost model

For a form-generation run:

```
gap_fill_calls ≈ (non_compliance_fields ÷ FIELD_FILL_BATCH)
               + (compliance_fields    ÷ COMPLIANCE_BATCH)     … × doc_chunks
```

Every sub-batch re-sends the **entire** constant block. Measured from a real 2-form run
(ACORD 125 + ACORD 25, `raw_text_chars=5226`), solving `4 fields → 24,619 chars` against
`40 fields → 31,573 chars`:

| Component | chars | constant within a run? |
|---|---|---|
| `_PROMPT_SKELETON` | 8,599 | yes |
| Facts block | ~10,021 | yes |
| Raw document text | 5,226 | yes |
| **Fixed overhead per call** | **23,846** | **yes — this is the problem** |
| Per-field | 193 | no |

That run made ~17 gap-fill calls → **~405,000 chars (~101,000 tokens) of pure repetition.**

**This holds at every document size.** On a small document the fixed overhead dominates; on
a 270-page package the document dominates. Either way the repeated part is ~94% of each
prompt, so prefix caching is the correct fix in both regimes.

**Batch sizes are deliberately NOT the lever.** `COMPLIANCE_BATCH=10` and
`FIELD_FILL_BATCH=40` were tuned in commit `7fa0d43` (2026-07-20) to fix a false-"N" flood
on Yes/No compliance questions. That commit raised document shipments ~6.9× as a side
effect, but the answer is to make each shipment nearly free via caching — **not** to undo
the accuracy work.

### How prefix caching actually engages — read before touching any prompt

Four conditions, **all** required. Breaking any one silently returns the run to full price.

1. **The system message must be byte-identical** across every call in a stage. It is matched
   from token zero.
2. **Everything constant must precede everything variable** in the user message. The cache
   matches a *prefix*; nothing after the first divergent byte can be reused.
3. **Chunk boundaries must be stable.** Any budget derived from a batch's own size produces
   different document slices per batch, i.e. different bytes, i.e. a miss (C3).
4. **The prefix must be ≥1024 tokens.** Below OpenAI's floor, nothing caches at all.

There is also a fifth, non-obvious condition that is easy to lose:

5. **Concurrency defeats a cold cache.** OpenAI populates a cached prefix only when a request
   *completes*. Firing N sub-batches at once through the thread pool makes the first
   `_FIELD_BATCH_POOL` of them all misses. `_PREFIX_WARMUP` (default on) runs one call to
   completion first, then fans out the rest — on a 6-batch run that is the difference between
   ~33% and ~83% of calls hitting cache. `LLM_PREFIX_WARMUP=0` disables it.

---

## 3. Open issues

### C53 — the 52-page trap packet: five deterministic fixes, no LLM change (2026-08-12)

The owner built a synthetic EMC package full of deliberate traps and audited the generated
ACORD 125 against it. The form dodged most traps (NO-COVERAGE lines unchecked, FEIN/website/
phone correctly blank, drones blank despite the unmanned-aircraft exclusion) and exposed
five real defects. All five are aggregation/guard bugs - none needed a prompt or call
change. Tests: `tests/test_dec_traps_20260812.py` (20), every fixture the packet's literal
trap string.

1. **The Additional Insured schedule lost a 11-vs-1 vote.** The AI schedule lives on ONE
   page; one chunk returned the three scheduled names, ten chunks that never saw that page
   returned an all-empty `risk_transfer`, and the vote chose empty (log:
   `chosen=... freq=11 rejected=[...names...](freq=1)`). For a structured fact, ABSENCE of
   data must never outvote PRESENCE: `_merge_risk_transfer` now unions across chunks
   (booleans OR, name lists union, scalars first non-empty) and again across documents
   (the primary-wins doc loop would otherwise clobber a companion doc's data).
2. **Q3 FLAMMABLES = naked "Y" quoting the pollution exclusion - two stacked holes.**
   (a) `_POLICY_DEFINITION_RE` (the gate's contract-language rejector) now also rejects
   exclusion/grant clauses: "this insurance does not apply", "exclusions are deleted",
   "coverage for ... is included/excluded". What a policy covers is never evidence of the
   applicant's exposure - the client's own rule. (b) THE recreation mechanism, finally
   pinned in code order: the policy-contract-language guard at the END of map_facts_to_form
   blanks the explanation the gate wrote, AFTER Guard 9 already passed. New
   `_final_yn_coherence` runs as the LAST mutation - anything that edits `mapped` must be
   inserted above it - and re-blanks any affirmative whose paired explanation ended up
   empty, whatever ate it.
3. **SAFETY MANUAL ticked under a blank Q2** (off "sample written safety manuals ... may be
   requested" - availability read as adoption). New rule: a question's QUALIFIER checkboxes
   (the consecutive /Btn run after a `_Question_<code>Code_` field sharing one name
   segment) may only stand when the parent is answered Yes. **Audited against all 17
   schemas before shipping: exactly six runs exist, five genuine** (125 safety program +
   cancellation reasons, 126/160 pool features, 141 audit-performed-by) **and one false
   positive - ACORD 125's NATURE OF BUSINESS grid - which the audit caught before it could
   blank the Contractor checkbox.** Excluded by name; scoped to AI-authored ticks so Pass-1
   flag-derived boxes are never touched; a standing harvest test fails the build if a
   future schema regeneration grows a new, unclassified run.
4. **Loss-history "Check if none" ticked off "NOT ON FILE".** The deterministic resolver's
   silence used to fall through to gap fill, which quoted "Prior Term Loss Experience: NOT
   ON FILE" - UNKNOWN, not "no losses" - as its evidence. `_resolve_no_loss_checkbox_owned`
   joins `_AUTHORITATIVE_BLANK_RESOLVERS`: flags/facts still answer Yes/No, silence is an
   owned EMPTY box the model never gets to guess (the one checkbox the client explicitly
   said requires confirmation). Extraction's `asserts_no_known_losses` flag guidance now
   states that NOT ON FILE / NOT REPORTED / absence = unknown.
5. **The producer's office stamped as premises LOC 4** - past the packet's own "this is not
   a location of the named insured" note - because the consolidation filter compared
   normalized line1 for EQUALITY and the entry carried "Ste 400" inside line1 while the
   producer fact parsed it onto line2. The filter now also blocks on (street number, ZIP5)
   identity - `_address_identity_key`, the comparator `_drop_transaction_party_rows`
   already trusts - for both producer and carrier. Plus address-shape validation: a state
   either is/converts to a real postal code ("Colorado" -> "CO") or is None; a ZIP matches
   \d{5}(-\d{4})? or is None; and a "ZIP" that is actually a state name means the whole
   city/state/zip split was one shifted mis-parse and all three clear ("VARIOUS JOB SITES,
   STATE OF COLORADO" had printed city="State", state="of", zip="Colorado").

**Re-run addendum (2026-08-13).** The owner regenerated after the fixes: producer office
gone, job-sites row clean, ambiguity logged (`lob-premium: matched 2 different amounts`),
prior-carrier grid correctly refusing current-term data, borrowed-N gone, GROUNDING_SHADOW
not_in_document=0. Two traps half-survived by mutating and are now closed at the gate:
Q3 kept a "Y" quoting the exclusion's own section HEADING ("POLLUTION EXCLUSION -
FLAMMABLES, EXPLOSIVES AND CHEMICALS" - a bare noun phrase no clause pattern matched), and
Q2 came back "Y" grounded on the carrier's loss-control OFFER ("may be requested ... does
not obligate"). New `_quote_cites_contract_machinery` rejects both classes - any quote
containing "exclusion(s)", plus offer clauses in `_POLICY_DEFINITION_RE` - while the
KEPT_YES dec-page coverage rows from the same run ("LIABILITY 01 $1,000,000 COMBINED
SINGLE") are pinned as still-valid evidence. The still-ticked "Check if none" on that run
is the extraction CACHE, not the fix: the chunk results were served from Redis with flags
produced by the pre-fix prompt, and the resolver honors an explicit flag by contract -
validate with a cache-busted upload. The Additional Insured section is still empty because
the union fixed the FACT and nothing yet STAMPS AdditionalInterest rows from
`risk_transfer.additional_insured_names` - a missing stamper, proposed as follow-up, not a
regression. Suite 2177/2 pre-existing.

Known and deliberately not chased: the Business Auto premium box blank on this packet is
honest ambiguity, not a bug - the document states the auto premium twice with different
values ($2,991 at inception, $5,829 after the September endorsement) and the resolver
refuses to pick; "prefer inception vs current" is a product decision. The "N" on Q8 whose
likely evidence is the driver-schedule sentence "this is not a fire code violation" is the
documented borrowed-negation residual. Suite **2174 passed / 2 failed** - the same two
pre-existing unrelated failures; the authoritative-blank census test gained the new owner
(+1, classified in place).

### C52 — text selection DEFAULTED OFF: LLM call 2 reads the whole document (2026-08-12, owner decision), cost +input, quality per owner's live judgement

**Coverage DROPPED on a live 700k-char run with filtering on, and the owner ordered the
filter removed.** The mechanism was C51's own entry-anchored mode: it keeps ONLY windows
carrying an already-known value (a fact or a verified entry), and a dec window whose values
extraction never captured - the audit basis, the billing block, the underwriter line - has
no anchor. Those are EXACTLY the fields only call 2 can fill, so anchoring cut their source
text out of the prompt. The safe-direction stages (density, footer) erred toward keeping;
anchoring inverted that and erred toward dropping. Wrong default for the end goal.

`GAP_FILL_TEXT_SELECTION` now defaults to **0**: production sends the complete document to
every gap-fill call, byte-for-byte the pre-filter behaviour. The filter code and its 40+
tests remain (opt back in with `=1`; the suite opts in via `tests/conftest.py`), and the
known costs of whole-document mode stand measured in this file - ~120-174k tokens per call
and the C21 long-context failure modes. If fill rate or borrowed values regress to the
26%-era numbers, the dial is here; the owner judges from live runs.

**Also in this change, unrelated to the filter:**
1. **Guard 9 - no naked Yes.** Owner saw "Y" stamped with an empty adjacent explanation on
   two live decs. The evidence gate blanks an ungrounded Yes at fill time, but LATER guards
   can eat the explanation it wrote (the NAKED_YES diagnostic caught the tooltip-echo guard
   doing it). Guard 9 runs LAST on final state: an affirmative whose ACORD-paired
   explanation ends up empty is blanked with it - "if yes, add explanation in the adjacent
   field" is the client's own rule, and the form prints EXPLAIN ALL "YES" RESPONSES. Only
   `_question_explanation_pairs` fields are touched; a No never needs an explanation.
2. **Location fold vs OCR unit spacing.** The 3-row smear returned on a cold-cache run;
   compact-form comparison ("D 13" == "D13" with spaces stripped) now folds keys the
   token-level prefix cannot see, while two real suites still never fold.

Tests: `tests/test_whole_document_default_20260812.py` (7), including a pin that the
production default really is whole-document. Suite **2154 passed / 2 failed** - the same two
pre-existing unrelated failures, zero regressions.

### C51 — first live run of C50: entry-anchored keep + strict-reverse backfill (2026-08-12), cost NEGATIVE

**The first production run of C50 worked and taught two lessons, both fixed the same hour.**
Live numbers (271-page EMC package): reconciliation swapped $2,991 -> $10,663 and the PDF
shows it; one clean premises row; **161 entries verified, 12 fabrications discarded at the
gate** - and then:

1. **The filter kept 66.4% because EMC's boilerplate is carrier-proprietary.** Density
   declined again (gap 0.07) and the ISO-footer stage caught only 82/228 windows - pages
   like "FORM CU7000A ED. 01-07" match no ISO shape, calls stayed ~120k tokens, fill rate
   moved only 26%->31%. **Fix: entry-anchored keep.** The 161 verified entries ARE the dec
   fingerprint - keep the windows their values live in, and stop trying to identify
   boilerplate at all. Carrier-agnostic by construction (the entries come from whatever the
   dec pages say), guarantee 3 satisfied by construction (anchors = every protected value),
   ratio gates unchanged, engages only at >=`TEXT_SELECT_ENTRY_MIN` (20) verified entries,
   `TEXT_SELECT_ENTRY_ANCHOR=0` kill switch. Fixture self-check proves the old path declines
   on the EMC shape before the anchored test asserts anything.
2. **The backfill filled ZERO facts - the forward label rule was the binding constraint.**
   The dec prints "PAYROLL"; the key is `total_payroll`; the unmatched "total" blocked it -
   and the run's ONE warning ("GL coverage detected but no revenue or payroll found") stood
   while the dec printed $39,300. **Fix: strict-reverse matching** - allowed only when every
   significant label token matches a key token AND every unmatched key token is a generic
   QUALIFIER ("total", "annual", ...). The asymmetry is the safety argument: dropping
   "total" from total_payroll still names payroll; dropping "gl" from gl_deductible names a
   DIFFERENT thing, so "Deductible" and "Premium" stay refused (both pinned by tests).

Also added: `merge coverage_lines FINAL` diagnostic (GL/Umbrella premium boxes went blank on
this run where the previous run filled them, and nothing logged which line names the merge
kept - next occurrence is diagnosable from the log alone).

Known from this run, deliberately not chased yet: `Insurer_NAICCode_A` came back 21407 vs
21415 (the EMC group prints several writing companies' NAICs - an attribution case for the
entries' owner tags, not solvable inside call 2 under the no-touch rule);
`CommercialPolicy_RemarkText_A` was stamped with a dec-header blob (literally present, so
grounding cannot catch it); two of four parallel gap-fill batches missed the cache (the
known warmup race, C27 territory). Tests: +8 in `test_dec_page_entries_20260812.py` (32
total). Suite **2147 passed / 2 failed** - same two pre-existing, zero regressions.

### C50 — dec_page_entries: LLM call 1 records the dec pages; only deterministic code consumes it (2026-08-12), cost ~+1c output, call 2 BYTE-IDENTICAL

**The owner's end goal, verbatim: "if values are present in declaration pages uploaded by
user then they should be correctly stamped on the form" - WITHOUT touching LLM call 2.**

**The measured gap this closes.** Extraction is DESTINATION-driven: ~173 registry keys
capture what the forms are known to ask for. Measured ceiling: with all 173 facts perfectly
filled, only 68 of ACORD 125's 548 fields resolve deterministically; anything a dec page
prints outside the key list (audit basis, deposit, program code, servicing contacts, FEIN
when the model misses it) evaporates and can only be re-found by gap fill inside the
haystack. This change makes call 1 SOURCE-driven as well: record every label:value pair a
declarations/schedule page prints - label, value, owner, policy - and decide who consumes it
later.

**The decisions, each with its reason:**
1. **In call 1, not a new call.** The chunks are already read; recording costs only output
   tokens on the 1-3 dec-bearing chunks (~$0.01 at mini pricing). A separate labeling call
   was designed first and rejected by the owner as unnecessary - correctly.
2. **Verbatim or gone (`_verify_dec_entries`).** Every entry's label AND value must be
   literally present (normalized) in the uploaded text; anything else is discarded before
   any code can read it. A labeling pass is checkable in a way free-form answers never were,
   and this check is what makes the rest of the design trustworthy.
3. **Only deterministic consumers.** (a) `_backfill_empty_facts_from_entries`: fills a
   registry fact that merged EMPTY under five stacked conditions - never overwrite; typed
   NAMED validator must pass (86 registry facts qualify + `total_policy_premium` via an
   explicit supplement, because registry membership would spawn a new ARQ client question);
   every token of the fact key must appear in the entry label (stem match) - 'fein' is not
   in 'Account Number', so the client's literal defect cannot route; owner compatibility -
   producer_* facts take only producer-owned values, everything else takes only
   applicant/policy-owned, the deterministic form of the client's "never place producer or
   carrier contact information into applicant fields"; and all matching entries must agree
   on ONE value - ambiguity stays blank for the ARQ. (b) text_selection's fact rescue now
   also anchors on entry VALUES, closing the one data-loss shape the filter had left open
   (a dec value the 173 keys never captured, living on a dropped window). Rescue only ever
   ADDS kept text.
4. **LLM call 2 is byte-identical, proven not promised.** `dec_page_entries` is excluded
   from the gap-fill facts block (`_GAP_FILL_FACTS_EXCLUDE`), and
   `test_call2_prompt_is_byte_identical_with_dec_entries` builds real call-2 prompts with
   and without the key and asserts equality. Inspector re-run: 12 calls, $0.0584, prefix
   stable - unchanged, PASS.
5. **Every unfilled field still reaches call 2** (owner's explicit requirement): the
   backfill removes a field from the gap-fill set only by actually FILLING its fact -
   pinned by `test_every_unfilled_field_still_reaches_call_2` against the real ACORD 125
   schema.
6. **Deliberately NOT done: open-vocabulary matching of entry labels onto the 5,852 ACORD
   field names.** That is a hand-rolled NLU layer, the exact heuristic class this codebase
   has repeatedly burned on (echo guards, keyword matching). Entries reach fields only
   through the typed fact layer, where validators and owner rules exist.
7. **Diagnostic only, zero behaviour change: `NAKED_YES`.** Owner reported a "Y" standing
   without its explanation; one candidate mechanism is the evidence gate keeping a grounded
   Yes whose paired explanation Guard 8 then blanks as a tooltip echo. That path now logs
   `post_fill_guard NAKED_YES` so the next live report pins the mechanism instead of
   guessing.

Tests: `backend/tests/test_dec_page_entries_20260812.py` (24) - every trap fixture is the
client's literal reported defect (account number 0482854 vs FEIN, producer's 303-996-7800
vs applicant phone, carrier website vs applicant website). Suite **2139 passed / 2 failed**,
the same two pre-existing unrelated failures, zero regressions. One existing fixture
updated, not weakened: `test_a_failure_falls_back_to_the_full_document`'s error injection
raised on `.values()` and `_fact_values` now reads `.items()` - the fixture raises on both,
same invariant.

**How to see it working on a live run:** grep for `dec_entries VERIFIED`,
`dec_entries BACKFILL fact=...`, `dec_entries DROPPED_UNVERIFIED`, and
`TEXT_SELECTION FACT_RESCUE`. Backfills carry `source="dec_entry"` in the fact envelope.

### C48 — Step 2 shipped: standard-form pages dropped by their OWN printed footer (2026-08-12), cost NEGATIVE

**The fill-rate lever finally engages on the client's document.** The density filter
(RETRIEVAL_CHANGES.md) skipped on the client's real package twice - final state
`separation gap 0.07` against the 0.15 floor - so every gap-fill call still carried the full
683k-char haystack and the measured fill rate stayed at 26%. The complementary signal that
plan named as Step 2 is now in `services/text_selection.py`: an ISO standard form declares
ITSELF in its page footer (`CG 00 01 04 13` - two letters, then four 2-digit groups), and
that identification is independent of how a PDF extractor renders lines, which is exactly
where the density signal failed.

Decisions that must survive future edits:
1. **Carrier dec-page codes do not match.** `CA7000A 02-22` (printed on the client's OWN dec
   page as the program code) is a different shape, verified by test. So is `CO 80216-3121`.
2. **A FORMS AND ENDORSEMENTS schedule is dec content and is kept** - it lists MANY codes in
   one window where a real footer is 1-2 (`_FOOTER_MAX_PER_WINDOW`). A window ADJACENT to a
   schedule-like window is also never marked: a schedule cut by a window boundary spills 1-2
   codes into its neighbour, which otherwise looks exactly like a footer page. That edge was
   caught by its own test fixture before it shipped, not by a client.
3. **Order: after dilation, before the fact rescue.** Positive boilerplate identification
   outranks a neighbour-of-a-dec-page guess; the rescue outranks everything, so an extracted
   fact living on a form page always restores its window (guarantee 3 is absolute).
4. **The ratio gates judge the combined result.** A document with fewer than
   `_FOOTER_MIN_WINDOWS` (3) marked windows, or where the final kept share falls outside
   [2%, 90%], is returned unchanged - same refusal discipline as the density stage.
5. **One filtered document per run, so the §2 prefix-caching conditions hold.** Inspector
   re-run after the change: gap_fill prefix 13,312 chars / 52%, compliance 64%, $0.0584 -
   unchanged, PASS.

Kill switches: `TEXT_SELECT_FORM_FOOTER=0` (this stage alone), `GAP_FILL_TEXT_SELECTION=0`
(the whole feature). Tests: 6 new in `tests/test_text_selection.py`, including a self-check
that the fixture really is density-inseparable (footer off -> returned unchanged), so the
footer tests cannot pass by density accident.

### C49 — the arithmetic reconciliation C45 called "the next step" (2026-08-12), no LLM change

C45's known limit, verbatim: authority "does NOT separate two rivals that both sit on the
declarations page - a line premium against the package total... That case needs the
arithmetic reconciliation... and is not in this change." It is now in
`extraction_service._reconcile_total_premium`, running inside `_merge_list_fields` after the
list merge, while the candidate buckets still exist: a `total_policy_premium` winner smaller
than the largest single GRANTED coverage-line premium is arithmetically not a total, and the
best-scored candidate that IS possible replaces it (exact-sum match preferred among the
possible ones; a possible winner is NEVER second-guessed - that would be C23's preference
mistake). No coverage lines, or no possible candidate, and the merge result stands - the
pdf_service resolver still refuses downstream, which is what shipped the client's BLANK
POLICY PREMIUM box: the resolver could only blank, because by resolver time the $10,663 was
gone from the fact dict. Now it never leaves.

Two sibling deterministic fixes in the same batch (same client run, same end goal - "a value
on the dec page must reach the form"): `_resolve_lob_premium` no longer lets a coverage
PART's premium fill its line's box ($35 "Auto Medical Payments" stamped as the Business Auto
line premium; now $2,991 stamps - stem matching reaches "Automobile", part-vocabulary
leftovers reject parts, exact line names outrank qualified ones, parts-only documents still
fill); and `_consolidate_property_locations` folds parse-variant groups (ONE premises
printed as THREE ACORD 125 rows because `_parse_address` splits only on commas; the folded
row recovers street/city/state/zip into their own boxes). Tests:
`tests/test_dec_page_values_20260812.py` (13) + 5 in `tests/test_location_consolidation.py`.
Suite 2098 passed / 2 failed - the same two pre-existing unrelated failures, zero
regressions.

### C47 — the evidence gate was rejecting REAL answers because "not" is a stopword (2026-08-12), cost ~neutral

**Quality regression, not a cost issue — but it is the reason a form came back emptier and
belongs in the same log as the fills it removed.**

`_quote_restates_the_question` (added earlier the same day) exists to stop two real
failures: a checkbox ticked on the "evidence" `"for non-payment of premium"`, another on
`"additional insured"` — each the field's own label read back. Correct target.

It tested only **token overlap**: "are all the quote's significant words already in the
question?". That cannot work alone, because *a direct answer to a yes/no question is by
definition mostly the question's own words* — and `"not"` sits in `_ECHO_STOPWORDS`, so the
single word carrying the entire meaning was discarded before the comparison.

Measured against the shipped schemas, synthesising the canonical way a document denies each
genuine compliance question:

```
form        questions   rejected   rate
ACORD_125          15          6    40%
ACORD_126          21          7    33%
ACORD_127          12          3    25%
...
TOTAL             218         39    18%
```

Casualties included `"The applicant does not have any subsidiaries."`,
`"The applicant does not install, service or demonstrate products."` and — an affirmative —
`"Subcontractors are required to carry coverage."`

**The damage was concentrated by an asymmetry.** A "Yes" survives on a quote *or* a paired
explanation; a "No" has only the quote, and `_evidence_supports` failing on a negative
blanks the field outright. Most compliance answers are "No".

**Fix — a structural second condition, `_quote_asserts_something`.** Overlap is now
necessary but not sufficient: the quote must also fail to assert anything. Both live
culprits are bare noun phrases (no subject, no finite verb); real evidence is a complete
predication. Measured 15/15 separation across both populations, then 39/39 recovered with
both culprits still rejected. Guarded by `tests/test_quote_label_vs_statement.py`, which
harvests the questions from the real schemas rather than hand-listing them, and asserts the
check carries no insurance vocabulary.

### C46 — the model was asked about vehicles that do not exist (2026-08-12), cost NEGATIVE

**This one put WRONG VALUES on a legal document, and it is also a free cost saving.**

Client's live ACORD 127: the document describes ONE vehicle, a 2012 Subaru Outback. The
generated form came back with vehicle rows 2 and 3 carrying the **General Liability** class
codes 91580/91585 and the GL exposures — `$39,300` payroll and `$350,000` subcontract cost —
stamped as vehicle **COST NEW**, plus a duplicated Subaru.

The first theory was cross-form batch confusion (`Vehicle_*` sharing a call with
`GeneralLiability_*`). **That was wrong.** `_SCHEDULE_REGISTRY` binds only the **19 identity
columns** of the vehicle schedule (VIN, make, model, body). `_resolve_schedule_row` already
holds the right contract for those — *"if the row is out of range, mark as authoritative
blank, do NOT send to GPT, we know the row doesn't exist"* — but the other ~50 columns per
row (cost new, rate class, territory, symbols, coverage indicators) are unbound, so they
fell through to gap fill for **every row letter the form prints**:

```
ACORD_127, one vehicle in the document
  row A (the real vehicle) :  56 fields
  rows B..D (NO vehicle)   : 164 fields   <- questions about nothing
```

Asked "what is vehicle B's cost new?" with no vehicle B to describe, the model does the only
thing it can and borrows a plausible figure from the document.

**Fix:** `_resolve_phantom_schedule_row`, registered in `_AUTHORITATIVE_BLANK_RESOLVERS` —
the contract both `compute_form_gaps` and `map_facts_to_form` already consult, so one
resolver covers both paths. It applies the SAME rule `_resolve_schedule_row` enforces, to
the whole row rather than the registered columns of it. Generic across all 16 schedule roots
and all 17 forms.

**It acts only on positive evidence.** An absent or empty schedule list means the row count
is unknown, so nothing is suppressed and behaviour is unchanged — suppressing on no evidence
would delete a schedule the extractor merely missed. Capacity is `len(list) + row_offset`,
because some roots do not draw their first row from the list (`NamedInsured_A` is the
applicant; `row_offset=1`). Using `len()` alone there would blank a real named insured.

**Measured on the 5-form union** (125/126/127/140/25, one location, one vehicle, one driver):

| | before | after |
|---|---|---|
| union fields sent to gap fill | 1,206 | **1,040** |
| ACORD 127 alone | 318 | **154** |
| outer batches | 7 | **6** |

**166 fields (14%) removed, one fewer outer batch, and the removed ones were exactly the
questions that had no correct answer.** Cheaper and more correct.
`tests/test_phantom_schedule_rows.py` pins both directions — phantom rows suppressed, real
rows and the no-evidence case untouched.

### C45 — THE root cause under C43: the merge ranks by REPETITION, so the declarations page always loses (2026-08-12), no LLM change

**C43 fixed two spellings of one value splitting their own vote. This is the layer under
it: even with variants pooled correctly, the vote itself is the wrong question.**

`_score_value` ranks competing values by `tier x (log1p(freq) + confidence)`. Measured
against the real scorer:

```
RIGHT value, declarations page,  1 chunk,  ai_high :  1.543
WRONG value, boilerplate,        2 chunks, ai_low  :  1.599   <- wins
WRONG value, boilerplate,       16 chunks, ai_low  :  3.333   <- wins
```

**A wrong value needs only TWO mentions to beat the right one stated once at high
confidence.** Now consider what a declarations page is: it states each figure EXACTLY ONCE,
while the policy forms behind it mention rival figures page after page. Across 17 chunks the
authoritative statement is structurally the minority vote. **The more of the document we
read, the worse the answer gets** - which is the whole reported phenomenon, and it is
arithmetic, not model attention.

It also explains the asymmetry nobody could account for: on a ONE-chunk document every
candidate has `freq == 1`, the frequency term is a constant, confidence decides, and the
answer is right. Small documents were never being handled better - they simply have no vote
to lose. The codebase had already written half of this down at `_partition_by_shape`
("a low-confidence value seen twice beats a high-confidence value seen once"), and answered
the *value validity* half while leaving *source credibility* unranked.

**Fix - source authority as a dominant QUANTIZED tier.**
`declarations_authority(text)` scores a span 0..1 on how much it looks like a
declarations/schedule page, and `_gather_chunks_async` stamps it onto every partial;
`_merge_list_fields` credits each candidate with the most authoritative place it was seen.

Four decisions worth keeping, each of which was wrong on the first attempt:

1. **Structural, not vocabulary.** A dec page is TABULAR (short lines, dense money and
   dates); a policy form is PROSE. A keyword list would be a per-carrier lookup in disguise
   and would not survive a carrier whose wording we have not seen.
   `test_authority_needs_no_insurance_vocabulary` fails the build on drift.
2. **Quantized tier, not a continuous weight.** Within a tier the expression is byte-for-byte
   the old formula, so a document that cannot be discriminated (all prose, or all tabular)
   does not merely rank *similarly* to before - it ranks *identically*. Asserted by
   `test_within_one_tier_the_ranking_is_the_old_arithmetic_exactly`, not claimed.
   `_AUTHORITY_GAIN=10.0` dominates the widest possible base spread (200 chunks -> 6.30).
3. **Windowed MAX, never the chunk mean.** This nearly shipped as a no-op. An extraction
   chunk is 56,000 chars and a real dec page is a few thousand: scoring the mean, a genuine
   declarations page at 14% of its chunk scored **0.174 against pure prose at 0.061 - both
   tier 0, signal gone**, on exactly the documents the fix exists for. Taking the max over
   3,000-char windows holds down to a 4% share. Max is the deliberately SENSITIVE choice: a
   false positive flattens the signal, which is today's behaviour, while a false negative
   costs the entire fix.
4. **Narrative facts opt out.** Authority says the dec page wins, which for a DESCRIPTION is
   backwards - the fuller operations narrative lives out in the prose, and ranking a tabular
   fragment above it would have *entrenched* the reported "COMMERCIAL GENERAL CONTRA"
   truncation. Derived from the VALUE shape (>100 chars AND >12 words), not a list of fact
   keys: `FACT_REGISTRY` has no `kind` column and a name pattern would miss the next
   narrative fact somebody adds.

**Coverage cannot fall** - authority reorders candidates that already exist and never drops
one. Proven over 200 randomised partial sets: the merged key set is identical with the term
on and off.

**Cost: zero.** No prompt, no call, no chunking change; `raw_text` is untouched, so the
cached prefix and `test_full_document_coverage` are unaffected. Scoring costs **58 ms of CPU
for a whole 17-chunk document**. Inspector re-run after the change: 12 calls, $0.0584,
gap_fill prefix 13,312 chars / 52%, compliance 64% - unchanged, PASS.

**Found while doing it:** the new `_MONEY_TOKEN_RE` silently shadowed an existing CAPTURING
pattern that `_money_amounts` parses with `float()`, turning all 12 C23 currency-tiebreak
tests red. Renamed to `_AUTHORITY_FIGURE_RE`, and
`test_no_module_level_regex_name_is_defined_twice` AST-walks the module so a counting
pattern can never again share a name with a parsing one.

**Known limit, deliberate:** authority separates dec-page values from boilerplate values. It
does NOT separate two rivals that both sit on the declarations page - a line premium against
the package total lands in the same tier and frequency decides as before. That case needs
the arithmetic reconciliation (parts must sum to the stated total), which is the next step
and is not in this change.

Tests: `backend/tests/test_merge_authority_20260812.py` (23). Suite **1895 passed / 2
failed** - the same two pre-existing unrelated failures, zero regressions.

---

### C44 — the same vote-split bug in a SECOND function; "absence" is not a value (2026-08-11), no prompt change

Audit of a real 25-page Orbin declarations run. No LLM-call or prompt change; all six are
decision-layer fixes.

1. **Every line-of-business premium box came out BLANK** on a dec page that prints all four.
   `_resolve_lob_premium` de-duplicated matched premiums by RAW STRING, so `"$ 3,954.00"`
   and `"$3,954"` from different chunks counted as two different amounts, tripped the
   "ambiguous - leave blank" branch, and suppressed the box. Same disease as C43's merge
   vote-splitting, in a second function; comparing on digits is the same cure.
2. **The PRIOR CARRIER grid held the policies being APPLIED FOR** - carriers, premiums and
   the proposed term. `_prior_coverage_grid` now discards any entry carrying the CURRENT
   policy number (including per-line numbers from `coverage_lines`) or the CURRENT
   effective/expiration date. Equality tests against facts we already hold; a genuine prior
   policy is untouched.
3. **A declarations page states absence in its own vocabulary** - "None Scheduled",
   "NOT PURCHASED", "NOT ATTACHED", "NOT INCLUDED", "NOT RATED", "NO COVERAGE",
   "NOT REPORTED" - and those phrases were being stamped as VALUES, including into the
   coded STATE and COUNTRY boxes of the additional-interest block. All added to
   `_LLM_EMPTY_SENTINELS`.
4. A non-committal ownership sentence ("owned, rented **or** occupied by the named
   insured") no longer ticks the "Other" interest box; alternatives joined by "or" leave
   the interest unknown, while "Tenant (leased office space)" and "Licensee under a
   shared-use agreement" still resolve.
5. The CITY LIMITS "Other" box is schedule-bound (it had been ticked with the insured's
   street address as its description).
6. A field ACORD declares as "Enter percentage:" keeps its value only when the document
   actually prints that figure as a percentage - two runs of the same dec produced 0%/0%
   then 100%/100% from a document stating no percentage at all.

Plus more SELECTED-CONDITIONS anchors in `_POLICY_CONTRACT_LANGUAGE_RE` ("legal action
against us", "no person or organization", "exclusions are deleted", "concealment,
misrepresentation", ...) - each verbatim from this dec, each previously quotable as
"evidence" for an applicant-history question.

---

### C43 — THE LARGE-DOCUMENT ROOT CAUSE: cross-chunk vote splitting (2026-08-11), no cost change

**Why a 271-page package fills worse than a 7-page one, measured rather than assumed.**
Extraction asks EVERY chunk for EVERY scalar fact. A 7-page dec is one chunk: one coherent
answer per key. A 271-page package is 14 chunks: up to 14 partial answers per key, and
`_merge_list_fields` picks the winner by frequency. That vote was keyed on
`sval.lower()`, so two SPELLINGS of one value became two rivals splitting their own
frequency. Verbatim from the run's own merge log:

    effective_date          '07/15/25'(4)        vs '07/15/2025'(3)
    producer_contact_phone  '303-996-7800'(3)    vs '(303)996-7800'(3)
    mailing_address         '..., denver, co'(3) vs '... denver co'(3)
    auto_deductible_comp    '$1000 ded'          vs '1000 ded'

The address split also surfaced a phantom "documents disagree" conflict on a submission
containing ONE document. Fix: `_variant_group_key` folds formatting (dates through the
shared `normalize_date`, everything else to alphanumerics) so variants pool their votes,
and `_fold_truncated_groups` merges a MID-WORD truncation into its complete twin
("commercial general contra" -> "commercial general contractor"). A qualified value is
explicitly NOT a truncation ("$1,000,000" vs "$1,000,000 each accident" - the
continuation starts at a word boundary), which is the whole safety argument. Genuinely
different values (four policy numbers, two NAIC codes) still compete.

**Second root cause, same document, not fixed by grouping:** a 271-page package is ~7%
declarations and ~93% policy forms, so for any Yes/No question some clause contains the
question's own noun. Q3 ("flammables, explosives, chemicals?") came back "Y" quoting the
POLLUTION DEFINITION; Q5 came back "Y" off a cancellation condition. `_POLICY_DEFINITION_RE`
(a quoted term followed by "means", or "as used in this policy") and cancellation-condition
patterns now disqualify such quotes as evidence and as narrative values.

No prompt change, no call-count change.

---

### C42 — a stated package total replaces a computed one; three more families owned (2026-08-11), cost NEGATIVE

Graded against both a synthetic 7-page fixture and the real 271-page package on the same day.

1. **EXTRACTION PROMPT: `total_policy_premium` added (~60 words, cached prefix).** The only
   prompt change here. The ACORD 125 POLICY PREMIUM box was computed by summing per-line
   premiums; on the 271-page package that summed to **$9,438 against a stated $10,663**
   because one line's premium was missed at extraction. A stated total is a COPY, a sum is
   an INFERENCE - `_resolve_estimated_total` now prefers the stated total (currency-checked)
   and keeps the sum as the fallback for documents that print no overall total.
2. Field-set / code only: the transaction-status TIME boxes are owned unconditionally (a
   dec page prints only the POLICY's "12:01 A.M." inception hour, lifted into them on two
   runs); the thirteen additional-interest TYPE boxes are owned by the captured interest
   fact (one stated Loss Payee had produced three ticks); a row-B narrative that
   near-duplicates row A's is blanked (the primary insured's operations were copied into
   "DESCRIPTION OF OPERATIONS OF OTHER NAMED INSUREDS"). This last one is deliberately NOT
   the banned slot dedup (C18) - gap-fill values only, rows B+ only, >= 40 chars of free
   text only, and schedule-bound cells never reach it.

Field count to the LLM falls again (status times, 13 interest boxes when the fact exists).
Calls unchanged.

---

### C41 — graded-fixture round: county joins the location schema; nine field families hardened (2026-08-10), cost NEGATIVE

A synthetic 7-page dec fixture with a full grading key (TEST_DEC_PAGE_ACORD125.txt) was run
live; ~85% of the key passed and the nine failures were each fixed with the run's literal
values as tests:

1. **EXTRACTION PROMPT: `property_locations` gained a `"county"` sub-field** (~25 words,
   cached prefix; the only prompt change in this entry). County is now schedule-bound end
   to end — the last premises column a model could free-associate into is owned.
2. Field-set / code only: prior-grid premium cells exempted from the "Premium"
   non-fillable substring (fill from `prior_coverage_by_line`); `NamedInsured_FullName`
   rows B+ bound to `additional_named_insureds` (row_offset=1); the producer mailing block
   owned by one `producer_address` parse; business-type mention-ticks suppressed for
   contractors; a "Yes" whose support text LEADS with a negation is blanked by the gate;
   negation sentences blanked from name boxes; Q8/9/10 incident dates anchored to their
   explanations; an insured's own name blanked from AdditionalInterest (loss-payee fact
   seeds the row instead).

Net LLM field count falls again (county, producer block, prior premiums, 2nd-insured name
all leave the prompts when facts exist). Calls unchanged.

---

### C40 — schedule row count bounds whole field families; package total is arithmetic (2026-08-10), cost NEGATIVE

Run-E findings. Field-set changes only; call count unchanged.

1. **`_resolve_schedule_family_row`**: rows beyond a KNOWN schedule length are owned blanks
   for EVERY column of the family — including columns with no schedule binding. Solves the
   client's original "ZIP = 4800 D / Denve" report for good: those fragments were in the
   COUNTY boxes (beside ZIP on the printed form), the one premises column not bound to
   `property_locations`, so it alone kept reaching the model as a "find 4 distinct values"
   group. Ambiguous families (Vehicle: two list keys) are exempt; unknown/empty lists keep
   full LLM coverage.
2. **`_resolve_estimated_total`**: ACORD 125's POLICY PREMIUM box (name carries no
   "Premium" token, so it was LLM-fillable and flip-flopped between the GL line premium
   and the true package total across runs) is owned: the sum of granted line premiums,
   with coverage-part entries and duplicate policy numbers excluded; blank when any line
   lacks a figure. The model is never asked.
3. **NAIC hard shape** (3-6 digits): the carrier's NAME was stamped into the NAIC CODE box.
   +40 NAICCode fields under `_shape_violation`, swept per the C22 precedent.
4. Q4's line label is withheld when it names a line whose coverage flag is explicitly
   False (post-downgrade) — the number still stamps.

---

### C39 — applicant-contact + line-two families owned; absence sentinels widened (2026-08-10), cost NEGATIVE

Run-D findings, all field-set / response-handling changes (no prompt text change):

1. **`NamedInsured_Contact_*` (24 fields on ACORD 125) is owned**: authoritative blank when
   extraction found no applicant contact fact (three consecutive live runs filled the block
   with producer/carrier claims-line contacts — a dec page has no applicant contact to
   find). Family reopens when a real contact fact exists. Fields leave every gap-fill
   prompt on the no-contact case.
2. **`*_MailingAddress/PhysicalAddress_LineTwo_A` owned** from the party's parsed address
   fact ("# D13" was re-written into line two by the model on two runs).
3. **`_LLM_EMPTY_SENTINELS` widened** ("not present", "not stated", ... ) — the literal
   string "not present" was stamped into the NAIC box.
4. LLM-sourced single-choice contradictions are cleared, not demoted (ISSUE+RENEW both
   ticked); `lines_of_business` checkbox ticks need grant corroboration when per-line data
   exists; statutory fraud-warning anchors added to the policy-language guard; carrier
   identity blanked from AdditionalInterest names; BusinessStartDate == policy date
   blanked; Form_CompletionDate now stamps the GENERATION date.

Net field count to the LLM drops again (~24+ fields on the common case); calls unchanged.

---

### C38 — reply keys recovered instead of discarded; more owner-resolved families off the LLM (2026-08-10), cost NEGATIVE

1. **`_absorb` now recovers answers returned under near-miss key names** via
   `_recover_sent_field`: normalized-exact match (case/punctuation drift) and dropped-row-
   suffix match, each accepted only when UNAMBIGUOUS; everything else still rejected and
   counted as UNKNOWN_KEYS. This converts already-paid-for answers into filled boxes on
   long documents (the measured failure: 57 of 60 answers discarded over key names on a
   single call). Zero new calls; logs `recovered=` per chunk and `KEY_RECOVERED` per field.
2. **More field families left the gap-fill prompts**: `Policy_Status_*` is owned
   deterministically when `is_renewal` is affirmative; `StateLicense*`,
   `Producer_NationalIdentifier`, `Insurer_Product*` are non-fillable (agency-profile /
   carrier-filing identifiers that never appear correctly on a dec page); "Other" LOB rows
   additionally exclude coverage-part entries. Field count per 125 run: 277 → 273 on the
   small fixture; larger drop on renewal packages (whole Policy_Status family).

---

### C37 — gap-fill gained an entity-discipline rule; owner blanks stopped shipping to the LLM (2026-08-10), cost NEGATIVE

Two changes in one entry, both logged per the standing rule:

1. **Prompt: `_PROMPT_SKELETON` rule 9 (ENTITY DISCIPLINE), ~1,050 chars.** The extraction
   prompt has had RULE 15 (never copy one party's detail into another party's field) since
   2026-08-09; the GAP-FILL prompt never got an equivalent, and the live client form showed
   the result: the carrier's "Claim Reporting: (888) 362-2255" line in the APPLICANT's
   contact block, phone numbers in email fields, and a dec-page "Agent Number" stamped as
   the State Producer License. Rule 9 names the three parties, forbids cross-party borrowing
   and label reassignment, and says omit instead. Sits in the constant system prompt →
   cached after call 1; cost impact negligible.

2. **`compute_form_gaps` gained the authoritative-blank branch `map_facts_to_form` already
   had.** Its docstring claimed the two "mirror exactly"; they did not. In the combined
   (production) path every owner-resolved blank — the whole prior-coverage grid, Q4
   other-policy rows, producer printed name, section-attached boxes, and the new Other-LOB
   rows — was listed as an LLM question whose answer the fill stage then discarded. Fixing
   the mirror removes those fields from every gap-fill prompt: fewer field lines per call,
   occasionally a whole batch fewer. Cost direction strictly negative; stamped output
   unchanged (the fill stage never consumed those answers).

Also in this change set (no LLM-call impact): `_resolve_other_lob_row` deterministically
owns ACORD 125's "Other" LOB rows from `coverage_lines` (granted lines matching no standard
checkbox); locations consolidation drops bare unit fragments and the producer's own address;
`CommercialStructure_PhysicalAddress_LineTwo` is schedule-bound; unanchored entity rows are
cleared rather than demoted.

---

### C36 — gap-fill prompt stopped calling facts "already verified" (2026-08-10), cost ~neutral

Two edits to the GAP-FILL prompt, both in text that is constant within a run and therefore
sits in the cacheable prefix (structure and ordering untouched — verified with
`inspect_gap_fill_prompts.py` after the change):

1. The facts-block header read `PRIMARY SOURCE — already verified by document analyzer`.
   **No verification of extraction output against the document exists anywhere in the
   pipeline** (`_value_in_raw_text` appears zero times in the extraction layer), so the
   prompt asserted a guarantee the system does not provide and told the model to prefer
   possibly-wrong inferences over the document. Header now reads `unverified hints from a
   previous pass — the RAW DOCUMENT TEXT below is authoritative`; the raw-text header
   changed from `SECONDARY SOURCE` to `AUTHORITATIVE SOURCE`.
2. The system skeleton's source description changed to match: facts are hints, the
   document wins on conflict, and boolean facts may *support* a checkbox answer but every
   such answer still needs its own grounding quote (rule 8 — unchanged).

Char delta: +~320 chars system prompt, +~40 chars user prefix — cached after call 1, cost
impact negligible. Facts stay AHEAD of raw text (position unchanged, per the C1-C11 cache
work); only the claimed trust changed. Quality direction: fewer wrong facts echoed by the
model on conflict; the evidence gate and compliance pass are unchanged.

---

### C35 — RULE 16 gained a "what a line premium is not" clause (2026-08-09), cost ~neutral

~450 chars added to the EXTRACTION system prompt, which is constant per run and therefore
sits in the cached prefix (billed at 10% after the first call of a run).

**Why.** A live run put `$35` in the ACORD 125 Business Auto premium box. The figure is on
the page; it is a fee or surcharge line, not the coverage part's annual premium. RULE 16
now says a line premium is the annual premium charged for that coverage part, and is not a
terrorism (TRIA/TRIPRA) charge, a policy or service fee, a state surcharge or tax, a
minimum premium, an endorsement or audit adjustment, or one vehicle's or location's share -
and that if the only amount against a line is one of those, `premium` must be null.

**A deterministic guard was considered and rejected.** The same document has a legitimate
$300 Inland Marine premium, so any absolute floor or relative-magnitude rule that catches
$35 also destroys $300. Prompt-side is the only place this distinction is visible.

**Cost direction is still negative**, for the same reason as C34: a correct per-line
premium keeps those boxes on the deterministic path instead of returning them to gap fill.

---

### C34 — extraction prompt grew two rules (2026-08-09), cost impact ~neutral

Logged here because CLAUDE.md requires any prompt edit to be recorded, not because it
costs anything measurable.

**Added to the EXTRACTION system prompt** (constant per run, so it sits in the cached
prefix and is billed at 10% after the first call of a run):
* **RULE 15 - ENTITY DISCIPLINE** (~1,200 chars). Names the owning party for every
  identity fact and states that `null` is correct when a party's own value is absent.
  Generalises RULE 14, which already did exactly this for the single
  `naics_code` / `carrier_naic` pair.
* **RULE 16 - coverage_lines** (~800 chars). Per-line premium/carrier/policy breakdown.

**Net effect is expected to be negative cost.** Both rules move work OFF the gap-fill
LLM and onto deterministic stamping: the 15 ACORD 125 line-of-business premium boxes and
the producer identity block now resolve in Pass 1. `_is_nonfillable_field` still blocks
premium boxes inside `compute_form_gaps`, so the gap-fill LLM is never asked for a
premium - the deterministic path was unblocked in `map_facts_to_form` only.

**Verified with the inspector, not a live diff** (`py backend/scripts/inspect_gap_fill_prompts.py`):
`PASS - prefix is stable and cacheable`, system prompt IDENTICAL across all 13 gap-fill
calls, cacheable prefix 11,774 chars / ~2,943 tokens - unchanged from the C1-C11 baseline,
as expected since none of the gap-fill prompt was touched.

**Still to come in this workstream** (will need re-verification when it lands): the
gap-fill skeleton's Rule 3 examples currently say `"Yes" ... else "No"` two lines after
Rule 3 itself forbids defaulting to "No", and Rule 5 forbids filling any premium field.
Both are being corrected; the plan is to DELETE the bad examples while adding the new
rules so the skeleton does not grow.

| ID | Sev | Issue | Location | Status |
|---|---|---|---|---|
| **C21** | **CRITICAL — fill quality** | **At very long context the model stops using the ACORD field names and invents its own.** Observed live on a real 682,726-char / 280-page package (one call = ~170k tokens): a batch that `sent=39` fields got back `total_returned=60` answers keyed `Producer_Name`, `Applicant_Name`, `Contact_Name`, `GL_Limit_EachOccurrence`, `Carrier_NAIC`, `Umbrella_Limit`, … **none of which exist in any ACORD schema.** `_absorb` skipped every unrecognised key, so `filled=3` of 39. The extracted DATA was correct; the keys were fabricated, so 57 of 60 answers were thrown away. Whole-form effect: `COMBINED_B3of7 fields_filled=38/171` (22%). **This is the cost of a single huge chunk** — the same pipeline on a 15k-char document does not do this. Mitigated, not solved: a `CRITICAL - JSON KEYS` instruction is now the LAST thing in the prompt (after the field list, so caching is unaffected), and `_absorb` logs `UNKNOWN_KEYS` at WARNING so it can never be invisible again. **The real lever is `CONTEXT_UTILISATION`** — lower it to trade cost for instruction-following. | `pdf_service.py` → `_build_user_prompt`, `_absorb` | **OPEN — mitigated, needs a live A/B on `CONTEXT_UTILISATION`** |
| **C15** | MED | **Progressive narrowing can miss a supersession.** `_run_field_batch` breaks out of the chunk loop once every field in the batch has an answer, and the compliance pass breaks once every question is answered. Correct for cost, but it means a value stated on page 2 is never re-checked against an endorsement on page 40 that changes it. Majority-vote conflict resolution silently degrades to a single vote. Pre-existing, unrelated to the caching work. Fix is a policy decision (always read the whole document vs. accept first-answer-wins), not a bug fix. | `pdf_service.py` → `_run_field_batch`, `_run_one_compliance_batch` | OPEN |
| **C17** | INFO | **Hard document ceiling.** `_check_cost_guardrail` raises `ValueError` above `ACORDLY_MAX_DOC_TOKENS` (500,000 tokens ≈ 2M chars). This is a **reject, not a truncation** — correct behaviour, no silent data loss — but a very large multi-policy package will fail the upload rather than degrade. Raise the env var if a real submission hits it. | `extraction_service.py` → `_check_cost_guardrail` | ACCEPTED |
| **C8** | LOW | `_FORM_FILL_RESPONSE_FORMAT` is a `json_schema` **without `"strict": true"`**, so it is advisory and does not by itself prevent explicit nulls. **Do not "fix" by adding `strict: true`** — OpenAI Structured Outputs rejects open-ended key maps (`additionalProperties: {type: string}`), which would 400 and silently force the `json_object` fallback. C5 addressed the nulls from the prompt side instead. | `pdf_service.py` → `_FORM_FILL_RESPONSE_FORMAT` | WONTFIX (documented) |
| **C9** | INFO | Pass 1 + Pass 1.5 resolve only ~22% of fields; the rest go to the LLM. Root cause: `CANONICAL_TO_EXTRACTION` has just **43 entries** while alias maps cover all fields. Measured: ACORD 125 → 344 of 548 unmatched; ACORD 140 → 326 of 356. | `services/alias_stamper.py` → `CANONICAL_TO_EXTRACTION` | DEFERRED |

**C9 is the only issue that removes work rather than repricing it.** Every concept added to
the bridge permanently drops fields from the LLM path across all 17 forms. Deferred because
it needs per-field validation, not because it is low value. **Caching has now landed, so
this is the next thing to pick up.**

---

## 4. Resolved issues

All resolved 2026-07-29 in one change set. Files touched:

| File | What changed |
|---|---|
| `backend/services/pdf_service.py` | C1–C7, C10, C11 — primary target |
| `backend/config/settings.py` | C10 — `LLM_SPEND` logging in `_openai_chat` |
| `backend/scripts/inspect_gap_fill_prompts.py` | **new** — offline prompt-prefix inspector |
| `backend/tests/test_prompt_prefix_caching.py` | **new** — 14 prefix-cache regression guards |
| `backend/tests/test_full_document_coverage.py` | **new** — 6 guards proving every word of a multi-chunk document reaches BOTH stages, and that no prompt exceeds the call budget |
| `CLAUDE.md` | pointer + a section describing this work |

| ID | Sev | Issue | Fix |
|---|---|---|---|
| **C33** | LOW — cost-neutral, removes LLM work | *(2026-08-07)* **Covered-auto symbols were extracted and then discarded, so 37 checkbox fields and 3 text fields per form were left to the gap-fill LLM to guess.** `auto_covered_symbols` has been in the extraction schema all along but nothing read it: no stamper binding, no validator, no alias bridge. Meanwhile the symbol definitions ACORD ships in its own field tooltips (`Vehicle_BusinessAutoSymbol_*Indicator` etc., 37 of them across 137/138/160) were reaching the model only as prompt text. A covered-auto symbol is a coverage designation with legal effect, so a guessed one is the exact failure the "blank over wrong" rule exists to prevent. | New `services/auto_symbols.py` holds the table (ACORD's own wording, guarded against drift by `tests/test_auto_symbols.py`). `pdf_service._derive_symbol_indicator` stamps the liability row of the symbol grid and the ACORD 25 / 131 ANY AUTO boxes deterministically; `_SCHEDULE_REGISTRY` binds the three per-vehicle symbol codes on ACORD 127, with policy-level inheritance. **Prompt change:** one new extraction rule (RULE 2b, ~90 words, in the constant system prompt and therefore inside the cached prefix) asks for symbols attributed to their coverage line — `[{"coverage": ..., "symbols": [...]}]` instead of a bare `[int]`, which could not tell any consumer WHICH coverage a number designates. Net effect on cost: **negative** — ~90 words added once per run to the cached prefix, against up to 40 fields per auto form removed from the gap-fill field list. No new call sites, no new batches. |
| **C14** | **MED — silent data loss in a FALLBACK** | *(closed 2026-07-30)* **The umbrella-period probe truncated: `text = raw_text[:_UMBRELLA_PERIOD_MAX_CHARS]` (60,000).** The worst possible placement for a hard cut, because this probe is a *backup*: `map_facts_to_form` fires it only when the main extraction pass has ALREADY failed to produce `umbrella_effective_date` / `umbrella_expiration_date`. So it was pointed at the opening 60,000 chars — on a real 684,000-char package, **the first 8.8%, and precisely the region we already know did not yield the dates. The backup read strictly less than the thing it backs up.** Umbrella dates came back blank on ACORD 125/131/25, and a blank from a truncated read is indistinguishable from a date the document never stated. | The whole document is now chunked through the shared `_split_text_on_boundaries` and scanned **in order, stopping the moment both dates are known**. Cost is unchanged in the common case — an umbrella dec page near the front still answers on chunk 1, i.e. exactly ONE call, same as before; only a document that genuinely does not state the dates early pays to read further, and only when an umbrella/excess form was selected. Chunked at `UMBRELLA_PERIOD_CHUNK_CHARS` (56,000 — extraction's measured-good regime), **not** the gap-fill call budget: a two-key question does not need 170k tokens of context and C21 measured instruction-following degrading there. A failing chunk is skipped rather than abandoning the document (the old single-call code returned `None` on any error; chunking without this would have been strictly worse than the truncation it replaced). The two dates resolve independently, so a dec page stating the effective date and a later endorsement stating the expiration both land. `None` (probe could not run) stays distinct from `{None, None}` (document does not state them). Guarded by `tests/test_umbrella_probe_coverage.py` (21 tests), four of which were **verified to fail against the restored pre-fix implementation**. |
| **C32** | MED | *(found auditing C31's own claim, 2026-07-30)* **The extraction carry-over overlap was never actually decoupled, and the change was not behaviour-neutral.** C31 says the tail became its own constant, `_EXTRACTION_OVERLAP_CHARS` (14,285). It did — in `_compute_prompt_overhead`, which only *reserves* budget for it. **Both functions that actually EMIT the tail — `_chunk_by_sections._flush_cur` and `_split_lines_into_chunks._flush` — kept computing `max_chars // 7`.** Since C31 moved the chunk size 100,000 → 56,000, the real carry-over silently moved **14,285 → 8,000, a 44% cut**, while the number of chunk boundaries roughly doubled: *less* context inherited at *more* boundaries, which is the exact direction that loses a fact spanning a split. The budget meanwhile reserved 14,285 for a tail that was 8,000 — self-inconsistent in the safe direction, and at a chunk size of 150,000 it inverts and **over-runs the reservation**. C31's own guard, `test_overlap_is_independent_of_chunk_size`, exercised `_compute_prompt_overhead` only — the one site that was already correct — so it passed over the defect. | Both emit sites now use `_EXTRACTION_OVERLAP_CHARS`. Restores the historical 14,285-char carry-over and makes the budget reservation exact rather than a guess at a different number. Costs ~6,285 extra chars on each chunk after the first (~$0.016 on a 14-chunk package) and buys back the boundary context C31 removed without saying so. The third notion of overlap in that file — `overlap_pct=0.15`, passed by `_run_extraction` and **never read by anything** — is now pinned as an explicit no-op so nobody wires it to a fourth meaning. Guarded by four tests in `tests/test_extraction_chunk_sizing.py` that measure the **emitted** tuples, three of which were verified to fail against the restored `max_chars // 7`. |
| **C1** | HIGH | Prompt assembled variable-part-first, so the ~23,846-char constant block never entered the cached prefix. Hit rate 0%. | `_build_user_prompt` now emits **form label → facts → raw text → fields → JSON footer**. Facts deliberately stay AHEAD of raw text (the prompt calls facts the PRIMARY source and models weight position); only the field list moved. |
| **C2** | HIGH | `combined_gap_fill` passed `batch_id` (`"COMBINED_B1of2"`) as `form_id`, which was f-string-interpolated into `_PROMPT_SKELETON`. **Two defects: killed caching AND the model never learned which ACORD form it was filling.** | `_PROMPT_SKELETON` hoisted to a module-level, form-agnostic constant. New `form_label` parameter carries the real names (`"ACORD_125, ACORD_25"`) in the user message, where it is constant per run and stays inside the cached prefix. `form_id` remains the logging label. |
| **C3** | MED | `_raw_budget` subtracted the batch's own `fields_chars`, so batches got different document chunk boundaries → different bytes → miss. | Subtracts a constant `_MAX_FIELDS_BLOCK_CHARS` (`FIELD_FILL_BATCH × 250`). **`max(constant, actual)`, not a bare constant** — `_pack_field_batches` emits table groups as unbounded atomic batches, and a fixed allowance alone would push those past the call budget into a context-length error → 3 dead retries → silently blank fields. Same treatment applied to the compliance pass via `_MAX_COMPLIANCE_BLOCK_CHARS`. |
| **C4** | MED | `_pack_field_batches` flushed a partially-filled batch whenever it met a table group. Real log: 186 fields → **8 calls** `[40,4,11,24,18,40,40,9]`. | Table groups stay atomic (row alignment needs it) but `current` is no longer flushed. Measured on the ACORD 125 + 25 fixture: **24 → 18 gap-fill calls.** |
| **C5** | MED | `_PROMPT_SKELETON` said "return JSON null" ~12× against one "omit" block, so the model emitted nulls that `_absorb` discarded on arrival — waste at 6× input price. | Every null instruction reworded to omission, including `_slot_group_block` and `_table_group_block`. **Behaviour-neutral by construction:** `_is_empty_llm_value` already discarded nulls, so omitted and null were always identical to the caller. The anti-borrow / anti-invent wording in the table blocks was preserved verbatim in meaning. |
| **C6** | MED | `json.loads()` sat **inside** the retry `try`. A reply truncated by the 16000-token cap raised `JSONDecodeError` → the whole prompt re-sent up to 3×, after the wasted output was already billed. | Transport failures and parse failures are now handled separately. A parse failure first calls `_salvage_truncated_json`, which rewinds to the last completed element and closes the open brackets — the answers the model *did* finish are kept, at zero extra cost. |
| **C7** | LOW | `_inner()` fell back to `json_object` on **any** exception, so a timeout or 429 — where OpenAI had already processed and billed the first request — immediately fired a second identical full-prompt call. A context-length 400 re-billed a call that could never succeed. | New `_is_response_format_rejection` gates the fallback: 400 **and** the message names `response_format`/`json_schema`/`additionalProperties`, or a local SDK `TypeError`/`ValueError` where no request was sent. |
| **C10** | INFO | No token accounting anywhere — `resp.usage` read in zero application files. | Every hot-path and umbrella call emits `LLM_SPEND stage=… form=… in=… cached=… out=… cache_pct=…`. All wrapped in `try/except`: telemetry can never break a fill. |
| **C20** | **HIGH (cost + latency)** | *(diagnosed from the 271-page live run; closed once the real model spec was confirmed — 400k context / 128k output)* **`GPT_CALL_BUDGET_CHARS` was hand-set to 380,000 ≈ 95k tokens, i.e. only 24% of the window**, and it is the dominant cost and latency term on a large package. Every extra document chunk multiplies the call count by the number of field sub-batches. Measured on the real 671,654-char / 271-page submission across the same 5 forms: **380k budget → 3 chunks → 172 calls**; **760k budget → 1 chunk → 63 calls.** Same fields, same document, **63% fewer calls** — and the cacheable prefix goes from 8.5k chars to 680k. Raising it was previously unsafe: an over-large budget means every call returns a context-length 400, all three retries burn, `_chat_json` returns `{}` and whole batches ship **BLANK** with nothing on screen. | The budget now **self-tunes**. `_is_context_length_error` recognises a genuine context rejection (and only that — a 429, a timeout, or a `response_format` 400 still take the normal path); the first one halves `_effective_budget_chars` process-wide, and `_run_field_batch` re-splits and retries, up to `_CONTEXT_SHRINK_ATTEMPTS` (5, spanning a 32x over-estimate, floored at 40k so it always terminates). A wrong guess costs one wasted call instead of a form full of holes. **And the budget is no longer guessed at all** — it is derived from `MODEL_CONTEXT_TOKENS` (400,000), `CONTEXT_UTILISATION` (0.75) and `FORM_FILL_MAX_TOKENS`, giving **994,000 chars**: 75% window utilisation at the pessimistic 3.5 chars/token, 66% at the measured 4.01. The reply reserve was also wrong — a flat 30,000 chars against a 16,000-token (~64,000-char) reply cap — and is now derived too. **Result on the real 271-page package: 172 calls → 63, cacheable prefix 8.5k chars → 680k, projected gap-fill cost $6.82 → $1.29.** Guarded by `tests/test_context_budget_selftune.py`. |
| **C31** | MED | **Extraction chunk size was one hand-typed literal.** `_MODEL_CHUNK_CHARS = {"claude": 28_000, "openai": 100_000}` — no comment, no calculation, predating the current model. Three defects, only one of which was the number: **(1) no provenance** — nothing said where 100,000 came from or what would make it wrong, while gap fill derived its budget from the model spec, so the two halves of the pipeline disagreed about the same model (56,357 chars/call vs 899,393); **(2) no capacity guard** — nothing compared it to the real window, so an over-large value would have failed every call on context length with no import-time warning; **(3) the carry-over overlap was `raw // 7`**, coupling two unrelated concerns, so changing the chunk size silently changed how much context each chunk inherited from the previous one. | Now `min(quality, capacity)`: quality = `EXTRACTION_DOC_TOKENS_PER_CALL` (14,000 tok, **the binding ceiling**), capacity = `MODEL_CONTEXT_TOKENS x EXTRACTION_CONTEXT_UTILISATION - EXTRACTION_REPLY_TOKENS`, clamped with a WARNING if an override cannot fit. The window constant is read from the **same env var pdf_service uses**, so one edit moves both halves when the model changes. The overlap is its own constant (`EXTRACTION_OVERLAP_CHARS`, default 14,285 = the historical `100_000 // 7`). **Deliberately behaviour-neutral**: effective size 56,357 -> 56,000 chars (0.6%), asserted to produce the identical chunk count on a 1.14M-char fixture. Capacity is **20x** the quality ceiling and that gap is NOT reclaimable waste — it is the measured distance from the C21 cliff. Guarded by `tests/test_extraction_chunk_sizing.py` (12 tests), including one that fails if capacity ever becomes the binding ceiling. |
| **C30** | **HIGH (cost)** | **Outer batching cut BOTH inner streams mid-flow.** `combined_gap_fill` sliced the mixed union, then each outer batch re-partitioned ITS OWN slice into compliance questions (groups of `_COMPLIANCE_BATCH`) and general fields (groups of `_FIELD_FILL_BATCH`). Every slice boundary therefore left a runt batch on each side. Measured on the real 5-form union (1,359 fields, 133 compliance): **compliance ran 18 calls with sizes [4, 10, 10, 9, 1, 10, …, 4, 2, 4, 5] where 14 suffice.** A 1-question call pays a full call's fixed overhead. | The union is partitioned into compliance and general items BEFORE outer batching. General items keep schedule-aware packing (C19); compliance items chunk plainly, and `_COMBINED_FIELD_BATCH` is a multiple of `_COMPLIANCE_BATCH` so each outer group divides into full inner batches. **Changes nothing the model sees** — the compliance pass was always a separate call with its own system prompt, so a compliance field never shared a call with a general field. Batch sizes (40/10) untouched. **18 → 14 compliance calls.** |
| **C29** | **HIGH (cost + a pre-existing correctness bug)** | **Every table group got its own dedicated LLM call.** `_pack_field_batches` emitted each detected table bucket as a standalone batch. Measured on the real union: **46 gap-fill calls, 34 of them partial, many carrying 3-5 fields** — 820 fields shipped in 46 calls where 21 would hold them. The row-alignment invariant (C19) requires a table to be visible to ONE call; it does **not** require the table to be ALONE in that call, so this was a much stronger condition than correctness needed. **And it protected the wrong set:** only >=3-column TABLE buckets were kept atomic, so plain multi-slot groups were sliced freely — measured **27 repeating groups split across separate calls**, which is the C19 failure mode one level down (a call seeing `_A`/`_B` but not `_C` cannot honour "find N distinct values, never repeat one"). | `_pack_field_batches` now bin-packs **indivisible units**: a detected table bucket, a multi-slot repeating group, or a lone field. A unit either fits the current batch or starts a new one, and is never cut. A single group larger than the cap still gets its own oversized batch (only tables reach that; ACORD row letters stop at N). Result on the real union: **46 → 33 gap-fill calls AND 27 → 0 split groups** — cheaper and more correct. "Group" means `repeating_group_key` = (base, **tooltip**), never base alone: ACORD 25's insurer tooltips end "As used here, this is Insurer B.", so those six slots are six one-slot groups needing no joint reasoning; counting by base name inflates the split figure to 92 and is the wrong denominator. `FIELD_BATCH_PACK_TABLES=0` reverts the COST change only — group atomicity holds on both paths, asserted. |
| **C22** | **HIGH** | **Wrong values in the ACORD 127 driver schedule.** `Driver_TaxIdentifier_A/B = "4S4BRCGC9C3217772"` (a **VIN** in a tax-identifier field), `Driver_TaxIdentifier_I/J = "ERIN ROYAL"` (a **person's name**), `Driver_GenderCode_A = "ERIN ROYAL"`. None was caught by the existing guards: `_NUMERIC_DATE_FIELD_HINTS` lists `YearBuilt`/`ModelYear` but not plain `Year`, and `_PROSE_FIELD_TOKENS` contains "Name", so a name-ish field is classified as PROSE and anything passes. | **Guard 3b — ACORD's own declared types.** Each field's tooltip states its type ("Enter code:", "Enter year:", "Enter identifier:", …) for **3,888 of 5,852 fields (66%)**; only the 607 `Enter number:` ones were being read. `_rejects_declared_type` now covers all twelve. Conservative BY DESIGN — it rejects only a personal NAME, a VIN (never in a vin/serial/identificationnumber field), or an out-of-range year, because amount boxes legitimately hold "Statutory"/"Included"/"See schedule". Validated by a **~49,000-pair sweep** (every type-appropriate legitimate value × every typed field in all 17 schemas) with **zero false positives**; the sweep is the test. It caught one during development: "See schedule" matched the person-name shape, hence `_NOT_A_NAME_WORDS`. **Honest scope — 3 of the reported items are fixed, and the other 3 are NOT type errors:** `Driver_LicensedYear_A = "2012"` is a valid year (wrong ENTITY's year — invisible to any type check), `Vehicle_RateClassCode_A = "7383"` is a validly-shaped code, and `Driver_OtherGivenNameInitial_A = "Erin"` **was never a defect** — ACORD's own tooltip reads "middle name **or initial**", so a first name is permitted and rejecting it would blank legitimate data. Guarded by `tests/test_declared_type_guard.py` (31 tests). |
| **C28** | MED | **Budget shrink was process-global, never reset, and cross-contaminated.** `_effective_budget_chars` only ever decreased for the life of the worker, so one pathological document doubled the chunk count and cost of **every later submission** until restart. Worse, concurrent sub-batches all tested `if _effective_budget_chars < budget_before`, so ONE thread's overflow made every other in-flight batch discard completed work and re-run every chunk. **Introduced by the C20 fix.** | Overflow is now tracked in a `threading.local` (`_note_context_overflow` / `_consume_context_overflow`), so only the batch that actually overflowed re-splits. `reset_call_budget()` runs once per submission from `combined_gap_fill`, keeping the within-run learning and dropping the cross-run leak. Guarded by `tests/test_batch_packing_and_budget.py`. |
| **C27** | MED | **Warm-up was scoped per outer batch, not per run.** `_warmup_enabled` was local to `_fill_unmatched_with_gpt`, which runs once per outer batch, so an 8-batch run paid up to **16 serialized warm-up round trips** (8 gap-fill + 8 compliance) and batches 2-8 each warmed a prefix batch 1 had already warmed. | `_claim_warmup(stage, prefix_key)` memoises in a module-level set; `reset_prefix_warmup()` clears it per submission. The prefix is identical across outer batches by construction (that is the point of C1's reordering), so one warm-up per (stage, prefix) is exactly right. Guarded by `tests/test_batch_packing_and_budget.py`. |
| **C26** | MED | **Majority-vote conflict resolution was dead code.** `all_filled[field] = max(candidates, key=…)` implies multiple votes per field, but the chunk loop stopped once a batch's fields were answered, so every count was exactly 1. | Fixed as a side effect of C25's auto-rescan: on a multi-chunk document every field is now re-asked against every chunk, so the resolver receives real votes. Still vacuous on a single-chunk document, which is correct — there is only one chunk to vote. |
| **C16** | MED | **PII in logs.** `_absorb` logged `DIAG_RESPONSE … sample=<up to 2000 chars of model output>` at INFO on every call — real applicant names, addresses and FEINs, which CLAUDE.md classes as sensitive and `utils/crypto.py` encrypts at rest. | INFO now carries field NAMES and the response size only; the values moved to DEBUG behind an `isEnabledFor` check. **Correction to the original report:** `FIELD_SOURCE_AUDIT` was also named there but logs only the field name and an agreement count — no values — so it was left alone. |
| **C19** | **CRITICAL** | *(found in the second live run — WRONG VALUES ON THE FORM)* `combined_gap_fill` sliced the cross-form union with a plain `field_items[i:i+200]`. Each outer batch is a separate `_fill_unmatched_with_gpt` invocation — separate LLM calls that never see each other — so a schedule cut by that slice left the stranded rows with no view of their siblings. Measured on the real 5-form union (1,354 fields): **`Vehicle_*` split across 3 outer batches, `Driver_*` across 2, `CommercialProperty_*` across 3.** It shipped wrong values: `Vehicle_CostNewAmount_D = $58,900` (vehicle **1's** cost; vehicle 4 is $41,800), and `Vehicle_RateClassCode_D = 91560` / `Vehicle_SpecialIndustryClassCode_D = 92478` — the two **General Liability** class codes, borrowed from an unrelated page. C18's fix unmasked it: the per-value dedup had been accidentally deleting `CostNewAmount_D` as a "duplicate" of row A. | New `_pack_schedule_aware_batches`. A "schedule" is any leading name segment appearing with more than one row letter across the union; its fields are kept in ONE outer batch, bounded by `_COMBINED_BATCH_HARD_MAX` (600) so a pathological schedule cannot build an unbounded call. This is the same rule `_pack_field_batches` already applied one level down — the level ABOVE it was doing the cutting. Verified on the real union: all three schedules now whole. Guarded by `tests/test_schedule_aware_batching.py`. |
| **C24** | **CRITICAL — silent data destruction** | *(found by an independent review, 2026-07-30. Invalidated the headline "no data is lost" claim.)* `utils/text_cleaner.py::clean_text`, called at `ocr_service.py:1704` **before extraction, before gap fill, before anything**, deleted content: (1) any line of >8 words that was >80% uppercase — declarations pages are written in capitals; (2) any paragraph under 10 chars; (3) every repeat of any paragraph, MD5-hashed across the whole document; (4) any line of only digits. Measured on a realistic dec page: **56% deleted**, including the named insured, both GL limits, and a vehicle schedule row. Whether a line survived depended on how many of its tokens were pure digits (not `.isupper()`), so a mailing address with three numeric tokens scored 70% and lived while the line above scored 100% and died. A 3-vehicle fleet's garaging address collapsed 3 → 1. **`_verify_coverage` reporting `671654/671654 chars — 100%` was 100% of what survived this function; the denominator was wrong**, and that figure was quoted as proof that nothing was lost. | Filters 1, 2 and 4 **deleted**. Paragraph floor 10 → 1 (empty only). De-duplication is now **default OFF** and, when enabled, requires ≥`TEXT_DEDUP_MIN_REPEATS` (5) occurrences AND ≤120 chars, so a 271-page running header still goes and a fleet row still stays. The saving it gave was ~2.4% of a real package, which at a 99% cache rate is noise. `clean_text` now accounts for every character it removes on every call. **The metric counts NON-WHITESPACE characters only, and the threshold is 2%.** A raw-length metric was tried first and was useless: pdfplumber pads columns with runs of spaces, so a perfectly intact layout-extracted declarations page reports **22.1% "removed"** purely from the lossless whitespace collapse and trips the alarm. An alarm that fires on the normal case gets ignored and then disbelieved on the day it is real — which is precisely how the original 56% deletion survived several rounds of review. The log line reports content-lost and whitespace-collapsed separately. Guarded by `tests/test_text_cleaner_preserves_content.py` (16 tests). |
| **C25** | **HIGH — the coverage test was blind** | *(same review)* `tests/test_full_document_coverage.py` proved "every word reaches the model" using a recorder that always returned `{"values": {}}`. With nothing ever answered, `active_fields` never shrank, the chunk loop never stopped early, and every chunk always shipped. With a recorder that ANSWERS, as production does: one 40-field batch against a 2-chunk document sent **1 call instead of 2 and skipped 38% of the document**. The test written to guard against dropped text could not see text being dropped. A "run-level coverage is still complete" defence was offered (0/400 markers missing on a 120-field run) and **does not hold as a property**: re-measuring showed that run came out clean only because two of its five batches had their answers discarded as `UNKNOWN_KEYS` and therefore happened to read every chunk. With a single batch that fills up, **185 of 400 markers (46%) never ship**. Coverage by luck is not coverage. | Recorder now answers fields and derives the stage from the system prompt. **Rescan is now AUTOMATIC whenever the document actually split** (`_rescan_enabled` → `GAP_FILL_FULL_RESCAN=auto`): zero cost on a single chunk because there is nothing to re-read, and correct the moment there are two. The previous OFF default relied on documents staying under ~890k chars — and fixing C24 removed up to 25% of deletion from every document, pushing large packages TOWARD that line, so **the shredder fix had armed this hole.** `GAP_FILL_FULL_RESCAN=0` keeps the legacy first-answer-wins path as a kill switch and logs `COVERAGE_PARTIAL` when it drops text. Also revives C26. |
| **C23** | **HIGH** | *(independently confirmed by an outside review, which found two further defects in the same six lines)* The currency tiebreak re-sorted candidates by dollar magnitude on a near-tie. Three defects: **(1)** across coverage parts it is inverted — a package with a GL part ($1M/$2M) and a Commercial Liability Umbrella ($3M) had `gl_each_occurrence` filled from the UMBRELLA, while the composite `gl_limits` from the same run said $1,000,000; **(2)** the re-sort was global, not a top-two swap, so a 5th-ranked candidate could win on size alone; **(3)** `_currency_magnitude` strips non-digits, so on the composite `gl_limits` (which IS in `_CURRENCY_FIELDS`) it returns **1.0e+20** — the tiebreak was literally 'most digits wins'. | **Fixed in two rounds; the first round did not work and the live log proved it.** Round 1 reduced the magnitude rule to the one case its own comment cited (a real limit beating a literal zero) and reconciled each scalar against the composite `gl_limits`. **A real run on 2026-07-30 (ORBIN CONTRACTING) still stamped $3,000,000** because the COMPOSITE ITSELF was the umbrella block (`'each occurrence limit (liability coverage) $ 3,000,000; ...'`) — so every scalar agreed with a wrong witness, and the check logged nothing because the top candidate already matched. Round 2 fixed two further defects: **(a)** nothing was choosing between competing composites — `_score_composite_candidate` now ranks them by (how many of the four scalar children it explains, how many distinct dollar amounts it lists), which picks the real GL breakdown over an umbrella block that repeats one number, using no coverage-part vocabulary; **(b)** the scalar check required EXACTLY ONE consistent candidate, and `'$ 1,000,000'` / `'$1,000,000'` are two candidates for the same amount — it now groups by AMOUNT, so ambiguity means two DIFFERENT figures rather than two spellings of one. `gl_products_aggregate` and `gl_personal_advertising_injury` were also stamped from the umbrella and are now children of the same reconciliation. Verified on the run's verbatim strings across **all 6 orderings of the three composite candidates: 6/6 correct**. Guarded by `tests/test_currency_tiebreak.py` (23 tests). |
| **C18** | **CRITICAL** | *(found in the first live run, pre-existing, NOT latent — it was actively destroying data)* The post-fill slot dedup cleared any `_A/_B/_C` field whose value had already appeared in an earlier sibling. On a real ACORD 127 fleet it deleted **40+ correct cells** in one generation — garaging city/county/state/postal code, radius of use, rating territory, rate class, collision and comprehensive deductibles, and most coverage indicators for rows B and C — because three trucks garaged at one address legitimately repeat those values down the column. Row A survived complete; rows B and C came out near-empty. My caching work did not cause it but **exposed** it: better prompts meant the model filled far more sibling cells, so far more hit the dedup. | **Default OFF** (`SLOT_VALUE_DEDUP=1` restores it). It cannot be made correct here — a call sees only a SUBSET of a schedule's columns, so "model copied a value" and "the document really says that for every row" are indistinguishable. A row-level variant was implemented, tested, and **removed**: ask about City/State/PostalCode alone and three trucks in one city produce three byte-identical rows. Decided on asymmetry: a wrongly repeated value is visible and broker-correctable; a wrongly deleted one is invisible and reads as "not in the document". Guarded by `tests/test_table_row_dedup.py`. |
| **C12** | **HIGH** | *(found in QA review, pre-existing, latent)* `_raw_budget` sized the document chunk by estimating the fields block with `_field_spec()` — one short line per field — while `_build_user_prompt` renders multi-slot and table fields through `_slot_group_block()` / `_table_group_block()`, which are **several times longer**. On a group-heavy batch the estimate under-counted, too much raw text was packed in, and the assembled prompt ran past the call budget. **Measured: 69,879 chars against a 60,000 budget on ACORD 140** (+16%). In production that is a context-length 400 → 3 dead retries → `_chat_json` returns `{}` → the whole batch silently BLANK, indistinguishable from the model having nothing to say. Latent only because `GPT_CALL_BUDGET_CHARS` (380k) currently sits well under the model's real context. | Extracted `_render_fields_block()` as the **single source of truth**; `_build_user_prompt` and `_raw_budget` now both call it, so the two can never drift again. The allowance is then rounded **up** to a multiple of `_MAX_FIELDS_BLOCK_CHARS`, which keeps chunk boundaries shared across similar-sized batches (caching) while never under-reserving. Guarded by `tests/test_full_document_coverage.py`. |
| **C13** | MED | *(found in QA review, in C11's own fix)* Warm-up always adds one serialized wave: with N batches and pool P, waves go `ceil(N/P)` → `1 + ceil((N-1)/P)`. Worth it for a large prefix; a bad trade for a tiny one, where it buys ~half a cent and costs a full round trip of user-visible latency. | Gated on `_PREFIX_WARMUP_MIN_CHARS` (default 40,000 — i.e. roughly a 10k-token prefix). Below it, latency wins and the run is short anyway; above it, cost wins. Logged per invocation as `warmup=True/False`. |
| **C11** | MED | *(found during implementation, not in the original audit)* Sub-batches fan out `_FIELD_BATCH_POOL`-wide, and OpenAI only populates a cached prefix when a request **completes** — so the first 4 concurrent calls were guaranteed misses, capping a 6-batch run near 33% regardless of C1–C3. | `_PREFIX_WARMUP` (default on) runs one call to completion, then fans out the rest. Applied to both the compliance pass and the general fill. Also added `prompt_cache_key` (content-derived, per submission) so the router sends prefix-sharing calls to the same cache; it self-disables process-wide if any API rejects it, so it can never fail a run. |

---

## 5. Measured baselines

### Offline prompt-shape measurement — reproducible, zero API cost

`py backend/scripts/inspect_gap_fill_prompts.py` runs the real `combined_gap_fill` over real
schemas with the OpenAI client swapped for a recorder. Fixture: ACORD 125 + ACORD 25,
3,213-char document (449 unmatched fields).

| Metric | Before (`0d64b9f`) | After | Δ |
|---|---|---|---|
| Total LLM calls | 29 | **23** | −21% |
| Total input chars | 421,190 | **350,115** | −17% |
| `gap_fill` calls | 24 | **18** | −25% |
| `gap_fill` system prompt | **3 variants — caching dead** | identical | — |
| `gap_fill` cacheable prefix | **0 chars** | **11,774 chars (~2,943 tok)** | — |
| `gap_fill` cached-input ceiling | **0%** | **64%** | — |
| `compliance` cached-input ceiling | 70% | 70% | unchanged |

**The compliance pass was already caching correctly** — document-first, constant system
prompt. All of the loss was in `gap_fill`, which sat at literal zero. The two "before"
numbers that matter: 3 different system prompts, and a shared user prefix of **26 chars**.

The −17% input-char figure is the *pre-cache* saving (fewer, less fragmented calls). The
cache saving lands on top of it: the 64% share of `gap_fill` input that is now prefix bills
at ~10% instead of 100%.

### Measured effect of the 2026-07-30 cost work (C29 + C30)

Offline, reproducible, zero API cost. Real schemas, real cross-form union
(`py scripts/inspect_gap_fill_prompts.py --forms ACORD_125 ACORD_126 ACORD_127 ACORD_140 ACORD_25`).

| Metric | Before | After | Δ |
|---|---|---|---|
| Total LLM calls | 63 | **47** | −25% |
| `gap_fill` calls | 46 | **33** | −28% |
| `compliance` calls | 18 | **14** | −22% (the ideal) |
| Repeating groups split across calls | **27** | **0** | correctness, not cost |
| Fixture cost | $0.2782 | **$0.2186** | −21% |

On a realistic **680,000-char, 5-form package** (where the cached prefix is
~170k tokens per call, so a removed call is worth far more):

| | Before | After |
|---|---|---|
| Calls | 64 | **46** |
| Cached input | 10.6M tok | **7.5M tok** |
| Cost | ~$1.30 | **~$0.98** (−24%) |

**Output tokens are an estimate** (500/call, from the live-run average) and are the
weakest number here — real output scales with fields answered, not with call count,
so treat the output line as indicative. The solid savings are the removed round
trips and the repeated cached prefix. **None of this changed a batch size, a
prompt, or what any single call asks the model.**

**Measured and deliberately declined:** raising `_COMBINED_FIELD_BATCH` from 200 to
600 removes 4 further calls (34 → 30) by reducing outer-batch remainders. Declined
— it is a ~6% gain that touches the schedule-batching invariant (C19), and the
standing requirement is that a cost change leave quality the same or better. Revisit
only with the accuracy baseline in hand.

### Live token measurement

Populate from `LLM_SPEND` lines on a real run.

| Date | Scenario | Calls | Input tok | Cached | Output tok | Cost | Note |
|---|---|---|---|---|---|---|---|
| 2026-07-29 | **Same 5 forms, 682,726-char 275-page package, single-chunk budget** | 7 outer batches, ~1 chunk each | ~170k/call | **99%** | ~500/call | **$1.17** | The budget fix landed: `prompt_chars=713268`, `chunk 1/1`, `cache_pct=99` on every call after the first of each stage. Down from ~$1.75 on the previous 3-chunk run. Extraction was effectively free — 13 of 13 `extract_facts: cache HIT` (same document re-uploaded), so this figure is almost entirely gap fill. One wasted call at process start from the `prompt_cache_key` mis-detection (C23 note) — now fixed by SDK inspection. |
| 2026-07-29 | **Same 5 forms, 671,654-char 271-page package** | **172 calls** (138 gap_fill + 34 compliance) | ~11.1M | ~90% (implied) | — | **$1.75** | 3 document chunks × 46 field sub-batches. Cost is arithmetically correct for the design, not a bug — but 63 calls suffice at a single-chunk budget. See C20. Extraction: 13 chunks, 671,654/671,654 chars covered, `_verify_coverage` OK. OCR: 0/271 pages needed Vision (pdfplumber read the text natively), 7 embedded images OCR'd. `table_extractor` skipped at 271 > 40 pages (supplementary pass only; main text unaffected). |
| 2026-07-29 | **ACORD 125+126+127+140+25, 15,302-char 10-page PDF** | 6 outer batches | — | **66-92%, avg ~82%** | avg ~450/call | **$0.24** | **FIRST LIVE RUN — caching CONFIRMED working.** OpenAI dashboard $0.18 → $0.42. Projected $0.33, actual $0.24 (27% under; the projection's 700 out-tok/call was conservative — real average ~450, helped by C5's omit-instead-of-null). `rejected=0` on every call, versus the pre-fix `sent=4 filled=0 rejected=4` that motivated C5. `warmup=True` at prefix~41,007 vs the 40,000 threshold. Zero retries, zero 429s, zero permanent failures. |

**Success criterion: `cache_pct` of 80–95% on every gap-fill call after the first.** If it
stays near 0, the prefix is diverging — run the inspector, which will name which of the four
conditions in §2 broke.

### Reference points from the audit

- OpenAI dashboard, 2026-07-12 → 07-27: **$26.78 · 34,084,828 tokens · 2,479 requests.**
  Solving against list pricing gives **input ≈ 33.76M (99%), output ≈ 0.32M (1%)** —
  input caching is therefore nearly the entire lever.
- Field counts are real, from `forms_schemas/`: 17 forms, **5,852 fields** total.
  Largest: ACORD 160 (1,135), ACORD 127 (634), ACORD 125 (548).
- Compliance (Yes/No) fields per form, computed with the production detection logic:
  125=27, 126=48, 127=44, 130=24, 131=22, 133=38, 137_CA/CO=46, 138_CA/CO=7, 140=8,
  141=50, 160=48, 186=88, 25=12. **101=0 and 28=0 are correct** — neither form has genuine
  Yes/No disclosure questions.

---

---

## 5b. Full-document coverage — the standing product requirement

**Every word of every uploaded document must reach the model.** A sentence that never
ships produces a blank field that is indistinguishable from a legitimate omission, and
nobody downstream can tell the difference. Chunk when the text exceeds a call budget;
never truncate.

Verified by `backend/tests/test_full_document_coverage.py`, which plants ~400 unique
sentinel tokens through a document deliberately larger than one call budget and asserts
every one of them appears in the text actually shipped — separately for **both** hot-path
stages, since they chunk independently and a regression in one is invisible from the other.

Current state, audited 2026-07-29:

| Path | Behaviour |
|---|---|
| OCR (`ocr_service`) | Iterates **all** pages, and native text is kept for every page. There ARE resource caps — `OCR_MAX_PAGES_PER_DOC` (400) on full-page OCR and `OCR_EMB_MAX_IMAGES_PER_DOC` (60) / `OCR_EMB_MAX_IMAGES_PER_PAGE` (12) on embedded images. Exceeding one does not silently truncate: it logs at ERROR and appends `needs_manual_review`. A >400-page **scanned** document is the real exposure, since those pages have no native text to fall back on. (This row previously read "No page cap", which was wrong.) |
| Extraction (`extraction_service`) | Chunks by section with `_verify_coverage`, which **raises** on any gap. `max_chunks` is explicitly advisory — "never drop sections". The one `text[:max_chars]` is a fallback that fires only when zero chunks were produced (an empty document). |
| Extraction size ceiling | `_check_cost_guardrail` **rejects** above `ACORDLY_MAX_DOC_TOKENS` (500k tokens). A reject, not a silent cut. See C17. |
| `clean_text` (`utils/text_cleaner`) | **Runs before everything, on every upload.** Removes page furniture only. Was deleting 56% of a realistic dec page — see C24. Accounts for every character it drops. |
| Gap fill (`_split_raw_text`) | Full coverage; boundaries at paragraph/line breaks. ✅ sentinel-verified **with an ANSWERING model** — the original test used a silent one, see C25. |
| Compliance pass | Own chunker, full coverage. ✅ sentinel-verified |
| Umbrella probe | Own chunker (`_split_text_on_boundaries`), full coverage, early exit once both dates are known. ✅ sentinel-verified — `tests/test_umbrella_probe_coverage.py`. Was `raw_text[:60_000]`, see C14. |
| `table_extractor` | Skips documents over `TABLE_EXTRACT_PAGE_LIMIT` (40) pages. This is a *supplementary* table pass; the main text still ships in full. |

Two behaviours that are coverage-adjacent and worth knowing about: the chunk loops stop
early once every field/question in a batch has an answer (correct for cost, but see C15 on
supersession), and `eligible_fields` deliberately excludes schedule fields and
underwriter-computed premium/rate fields from the LLM path — those are resolved elsewhere
or must not be guessed at all.

---

## 6. Rules for anyone touching this area

1. **Never** modify `backend/forms_schemas/*.json` — permanent ACORD field definitions.
2. **Never** hand-edit `backend/forms_aliases/` — generated by `scripts/generate_alias_maps.py`.
3. Do not change `COMPLIANCE_BATCH` / `FIELD_FILL_BATCH` to save cost. See §2.
4. Product rule: **blank is better than wrong.** A change that fills more fields but
   introduces wrong values is a regression.
5. The pipeline is **non-deterministic** — `GPT_TEMPERATURE=0.0` but no seed is pinned.
   Byte-identical output across runs is not achievable. Never try to verify a prompt change
   by diffing two live runs; the jitter hides the regression. Verify prompt *shape* offline
   (`scripts/inspect_gap_fill_prompts.py`), then sanity-check one live run.
6. **Before changing any prompt in `pdf_service.py`, re-read §2's five caching conditions**,
   then run the inspector. `tests/test_prompt_prefix_caching.py` fails the build if the
   system prompt splits into variants, if the field list moves ahead of the constant blocks,
   if the shared prefix drops under OpenAI's 1024-token floor, or if batches re-fragment.
7. Tests: `py -m pytest` from `backend/` (use `py`, not `python`). Baseline as of
   2026-07-29: **984 pass / 2 known pre-existing failures**
   (`test_arq_acord125_missing_only` — an `httpx`/`openai` version conflict — and
   `test_normalization`).

### Environment knobs added by this work

| Var | Default | Effect |
|---|---|---|
| `LLM_PREFIX_WARMUP` | `1` | Run one call to completion before fanning out, so the rest hit a warm cache. Set `0` for pure parallel (lower cache hit rate, one less serialized wave). |
| `LLM_PREFIX_WARMUP_MIN_CHARS` | `40000` | Skip warming when the constant prefix is smaller than this — below it the extra wave costs more latency than the repeated prefill costs money. |
| `GPT_CALL_BUDGET_CHARS` | **derived: 994,000** | Input chars per call. No longer a hand-set guess — computed from `MODEL_CONTEXT_TOKENS × CONTEXT_UTILISATION − FORM_FILL_MAX_TOKENS`, times `CHARS_PER_TOKEN_FLOOR`. An explicit override above what the window can hold is **clamped** with a warning. |
| `MODEL_CONTEXT_TOKENS` | `400000` | The model's real context window (gpt-5.4-mini). **Change this when the model changes** — everything else follows from it. |
| `CONTEXT_UTILISATION` | `0.75` | Fraction of the window we occupy. The rest absorbs tokenizer variance and the reply. **This is also the cost-versus-accuracy dial** — see C21. Bigger chunks are cheaper and faster; the model follows the field list worse at ~170k tokens. On a 682k-char package: `0.75` → 1 chunk / ~224k doc tokens per call; `0.50` → 2 chunks / ~137k; `0.35` → 3 chunks / ~84k; `0.25` → 4 chunks / ~49k. |
| `MIN_RAW_CHUNK_CHARS` | `2000` | Floor on the raw-text slice, only so the chunk loop makes progress. Deliberately small — a large floor overrides the call-budget guard and lets the prompt overflow (measured 60,363 vs a 60,000 budget). Hitting it logs an ERROR. |
| `CHARS_PER_TOKEN_FLOOR` | `3.5` | Pessimistic chars/token. Measured 4.01 on a real package (o200k_base); the floor guards dense VIN/class-code/money tables. |
| `GPT_REPLY_RESERVE_CHARS` | **derived: 64,000** | Was a flat 30,000, which under-reserved by more than half against a 16,000-token reply cap. Now `FORM_FILL_MAX_TOKENS × 4`. |
| `CONTEXT_SHRINK_ATTEMPTS` | `5` | How many budget halvings one batch may ride out before giving up. |
| `PROMPT_CACHE_KEY` | auto-detected | Routing hint only. **Detected from the installed SDK at import**, never assumed — the deployed venv runs `openai==1.54.4`, which predates the parameter. Automatic prefix caching works without it (measured 99% cache_pct with it disabled). Set `0` to force off. |
| `EXTRACTION_DOC_TOKENS_PER_CALL` | `14000` | Document tokens per extraction call — **the quality dial for extraction** (C31). 14,000 is the measured-good point; ~170,000 is where the model starts inventing field names. Raising it saves ~$0.11/run and moves extraction toward that cliff. Needs an accuracy baseline first. |
| `EXTRACTION_OVERLAP_CHARS` | `14285` | Carry-over tail from the previous extraction chunk so a fact spanning a boundary stays readable. Its own constant now — **and as of C32 the chunkers actually read it**; until then only the budget reservation did, while the emit sites still computed `chunk_size // 7`. |
| `UMBRELLA_PERIOD_CHUNK_CHARS` | `56000` | Document chars per umbrella-probe call. A **chunk size, not a ceiling** — the probe reads the whole document, stopping once both dates are found (C14). Sized to extraction's measured-good regime, not the gap-fill budget. |
| `EXTRACTION_CONTEXT_UTILISATION` | `0.75` | Fraction of the window one extraction call may occupy. A backstop only — the quality ceiling binds first. |
| `EXTRACTION_REPLY_TOKENS` | `16000` | Reply reserve for an extraction call. Input and output share the window. |
| `GAP_FILL_FULL_RESCAN` | `auto` | Re-ask every field against every document chunk. **`auto` = on iff the document split into >1 chunk** — free on the single-chunk common case, correct on a split one. `1` forces it on, `0` restores the legacy first-answer-wins path (measured dropping 46% of a document for a batch that fills up; logs `COVERAGE_PARTIAL`). |
| `FIELD_BATCH_PACK_TABLES` | `1` | Pack table groups alongside ordinary fields instead of giving each table its own call (C29). Set `0` to revert the cost change; repeating-group atomicity is unconditional either way. |
| `TEXT_DEDUP_MIN_REPEATS` | `0` (**off**) | Paragraph de-duplication in `clean_text`. Off because it was deleting real fleet rows (C24). When >0 a paragraph must repeat at least this many times AND be ≤`TEXT_DEDUP_MAX_LEN` (120) chars. |
| `SLOT_VALUE_DEDUP` | `0` (**off**) | Restores the post-fill per-value sibling dedup. Off by default because it was measured deleting 40+ correct fleet cells in one run — see C18 before turning it on. |
| `MAX_FIELDS_BLOCK_CHARS` | `FIELD_FILL_BATCH × 250` | Constant fields-block allowance that keeps document chunk boundaries stable. |
| `MAX_COMPLIANCE_BLOCK_CHARS` | `COMPLIANCE_BATCH × 800` | Same, for the compliance pass. |
