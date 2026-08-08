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
