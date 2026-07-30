# Primble — LLM cost & quality work, handoff

**Date:** 2026-07-30 · **Status:** nothing committed, all changes in the working tree
**Read alongside:** `improving-ll.md` (the authority on LLM calls/cost) and `CLAUDE.md`

---

## 1. The problem statement

> Reduce OpenAI cost per submission while keeping ACORD form-fill quality **exactly the
> same or better**. Never trade a correct field for a cheaper run.

Two hard rules that govern every decision here:

1. **No uploaded document text may be dropped.** Chunk it; never truncate it. A sentence
   that never reaches the model produces a blank field indistinguishable from a legitimate
   omission.
2. **A blank field beats a wrong field.** Wrong values on an insurance form are the worst
   outcome — they carry legal exposure. Blanks route to a human.

**Model:** `gpt-5.4-mini` — 400,000-token context window, 128,000 max output.
$0.75/1M input · $0.075/1M cached input · $4.50/1M output.
Measured 4.01 chars/token on real insurance text.

**Decision already taken: do NOT use the Batch API.** It halves every price but is
asynchronous (up to 24h) and it is unproven whether prefix caching survives batch
scheduling — if it does not, cost goes UP ~2.3x. Ruled out by the user.

---

## 2. What was wrong when this started

An earlier session had shipped prefix caching and batching work and reported it as done.
An adversarial audit found the headline claim was false:

| ID | Defect | Evidence |
|---|---|---|
| **C24** | `clean_text` deleted document content **before any LLM saw it** — all-caps lines, short paragraphs, repeated paragraphs, bare-digit lines. Declarations pages are written in capitals. | **56% of a realistic dec page deleted**, including the named insured and both GL limits |
| **C25** | The test proving "every word reaches the model" used a mock that answered *nothing*, so the early-stop path never ran | With an answering mock: **185 of 400 markers (46%) never shipped** |
| **C23** | Currency tiebreak picked the larger dollar amount, so **Umbrella limits filled General Liability fields** | `gl_each_occurrence = $3,000,000` when the real GL part is $1,000,000 |
| — | `_verify_coverage` reported "100% coverage" — of what survived C24. **Wrong denominator**, quoted as proof nothing was lost. | |

---

## 3. What was done

### Correctness

| ID | Fix |
|---|---|
| **C24** | Removed the three destructive filters from `clean_text`. De-dup default OFF; if enabled needs ≥5 repeats AND ≤120 chars. Loss metric now counts **non-whitespace characters only** (a raw-length metric false-alarms at 22% on any column-formatted PDF, purely from lossless whitespace collapse). Threshold 2%. |
| **C25** | Rescan is now **automatic whenever the document actually splits** (`GAP_FILL_FULL_RESCAN=auto`). Free on one chunk, correct on two. The old OFF default relied on documents staying under ~890k chars — and fixing C24 pushed documents *toward* that line, so **the shredder fix had armed this hole**. |
| **C23** | **Fixed in two rounds; round 1 did not work and a live log proved it.** Round 1 killed the magnitude sort and reconciled each scalar against the composite `gl_limits`. A real run still stamped $3,000,000 because **the composite itself was the umbrella block** — every scalar agreed with a wrong witness. Round 2: (a) `_score_composite_candidate` ranks competing composites by *(children explained, distinct amounts)* — a real GL block lists several limits, an umbrella block repeats one number, **no coverage-part keywords used**; (b) the scalar check grouped by AMOUNT instead of requiring exactly one candidate, because `'$ 1,000,000'` and `'$1,000,000'` are two spellings of one figure. Verified on the run's verbatim strings: **6/6 document orderings correct** (was 0/6). |
| **C22** | Type-aware rejection from **ACORD's own tooltips** — they declare a type ("Enter code:", "Enter year:", …) for **3,888 of 5,852 fields (66%)**; the code read 1 of 12. Validated by a **~49,000-pair sweep, zero false positives**. |
| **C16** | Applicant PII (names, addresses, FEINs) moved off INFO logging to DEBUG. |
| **C14** | **Closed 2026-07-30.** The umbrella-period probe truncated the document to 60,000 chars — in a *fallback* that only fires when extraction has already failed, so it searched the opening 8.8% of a real package, the part we know didn't have the dates. It now chunks the whole document through the shared `_split_text_on_boundaries` and stops as soon as both dates are known, so the common case still costs exactly one call. A failing chunk no longer abandons the rest. 21 tests; 4 verified to fail against the restored pre-fix code. |
| **C32** | **C31's "overlap decoupled" claim was false where it mattered, and the change was not behaviour-neutral.** The constant was read only by `_compute_prompt_overhead` (which *reserves* budget); both functions that EMIT the tail still computed `max_chars // 7`. With the chunk size moving 100,000 → 56,000, the real carry-over silently went **14,285 → 8,000 (−44%) while boundaries roughly doubled** — less inherited context at more splits. C31's own guard tested only the already-correct site. Fixed at both emit sites; the dead third overlap knob (`overlap_pct=0.15`, never read) is pinned as a no-op. 4 new tests measuring the emitted tuples, 3 verified to fail against the old expression. |
| **C31** | Extraction chunk size was one hand-typed literal (`100_000`) with no provenance, no capacity guard, and an overlap coupled to it as `raw // 7`. Now `min(quality, capacity)` from the same model constants gap fill uses, clamped with a warning, overlap decoupled. **Deliberately behaviour-neutral** — still 14,000 tok/call; capacity is 20x larger and that headroom is the distance from the C21 cliff, not waste. |

### Cost

| ID | Fix | Effect |
|---|---|---|
| **C30** | Compliance questions and general fields are **partitioned before outer batching**. Previously every slice boundary left runt batches on both sides (compliance ran sizes `4,10,10,9,1,10,…,4,2,4,5`). | **18 → 14 compliance calls** (the arithmetic ideal) |
| **C29** | Table groups are **packed alongside ordinary fields** instead of each getting a dedicated call. The row-alignment rule requires a table be *visible to one call*, not *alone in one*. **Also fixed a pre-existing correctness bug**: only ≥3-column tables were kept whole, so **27 repeating groups were being split across calls** — the same failure mode that once shipped `Vehicle_CostNewAmount_D = vehicle 1's cost`. | **46 → 33 gap-fill calls AND 27 → 0 split groups** |
| **C27** | Warm-up memoised per (stage, prefix) instead of per outer batch — an 8-batch run was paying up to 16 serialized round trips to warm an already-warm cache. | latency only |
| **C28** | Overflow detection moved to a `threading.local`; the call budget resets per submission. Previously one thread's context error made **every** in-flight batch discard completed work, and the shrink was permanent for the worker's life. | removes wasted retries |

### Measured result

Offline, reproducible, zero API cost:
`py backend/scripts/inspect_gap_fill_prompts.py --forms ACORD_125 ACORD_126 ACORD_127 ACORD_140 ACORD_25`

| | Before | After |
|---|---|---|
| Total LLM calls | 63 | **47** |
| Repeating groups split across calls | 27 | **0** |
| Fixture cost | $0.2782 | **$0.2186** (−21%) |
| On a realistic 680k package | ~$1.30 | **~$0.98** (−24%) |

**No batch size, prompt, or per-call question was changed.** `FIELD_FILL_BATCH=40` and
`COMPLIANCE_BATCH=10` remain frozen by prior accuracy work.

**Tests:** 1,047 → **1,144 passing**, same 2 known pre-existing failures
(`test_arq_acord125_missing_only` — an httpx/openai version conflict — and
`test_normalization`). Two adversarial passes, both clean.

---

## 4. Verified against a real production run

271-page package, 5 forms (125/126/127/140/25). Dashboard **$6.76 → $8.05 = $1.29**.

Reconciled from the `LLM_SPEND` log lines:

| Stage | Cost |
|---|---|
| Extraction (14 chunks + cert + narrative + reconcile) | $0.30 |
| Gap fill (46 calls) | $0.99 |
| **Total** | **$1.29** |

The offline projection was $0.98 for gap fill; the measured residual was $0.99.
**The cost model is validated to within a cent — there is no hidden waste.**

Confirmed working in that run's logs:
- `clean_text: content_chars 3136 -> 3136 (lost 0, 0.00%)` — C24 holding
- `coverage=100.0%`, `683601/683601 chars` — extraction loses nothing
- `compliance=131` → **14 calls** — C30 holding
- `schedule-aware batching kept 29 schedule(s) whole` — C19 holding

Confirmed **still broken** in that run (now fixed by C23 round 2, not yet re-run live):
```
merge field='gl_limits' chosen='each occurrence limit (liability coverage) $ 3,000,000; ...'
merge field='gl_each_occurrence' chosen='$ 3,000,000'  rejected=['$ 1,000,000','$1,000,000']
merge field='gl_aggregate'       chosen='$ 3,000,000'  rejected=['$ 2,000,000','$2,000,000']
```

---

## 5. How chunking actually works — three separate chunkers

This confused everyone including me. There are **three** places that decide "how much
document per call", with three different limits.

| Stage | Limit | Where it comes from | On a 683,601-char doc |
|---|---|---|---|
| **Extraction** | 56,000 chars | Derived (**C31**): `min(quality, capacity)`. Quality = `EXTRACTION_DOC_TOKENS_PER_CALL` (14,000 tok) and **binds**; capacity is 20x larger. Was a hand-typed `100_000`. | **14 chunks** |
| **Gap fill** | 899,393 chars | Derived: `(400,000 tok × 0.75 − 16,000) × 3.5` = 994,000, minus reply reserve, prompt, fields block | **1 chunk** — the whole document in every call |
| **Compliance** | same budget | own arithmetic, same inputs | **1 chunk** |

**Why 46 gap-fill calls if the document isn't split?** Because *fields* are batched, not
the document: 1,104 general fields ÷ 40 = 32 calls, plus 131 compliance ÷ 10 = 14. Each of
those 46 calls carries the complete 271-page document.

**The inconsistency matters:** extraction's small chunks (14k tokens/call) work well; gap
fill's one big chunk (170k tokens/call) is where quality degrades. The stale hand-typed
number is accidentally the safer one.

---

## 6. Open issues — ranked

### Real problems

| Issue | Effect on a form | Difficulty |
|---|---|---|
| **C21 — 170,000 tokens per call is the measured quality cliff** | The model stops copying ACORD field names and invents its own; those answers are discarded and the box ships blank. Measured: a batch sent 39 fields and filled 3; a whole form came out 38/171 (22%). | **Easy** — cap document tokens per call at ~90,000. +$0.18 on a 271-page doc, £0 on small ones. **Not implemented — awaiting a `grep -c "UNKNOWN_KEYS"` on a real log to confirm it is biting.** |
| **C15 — compliance answers are first-answer-wins** | A "No" grounded on page 10 is never rechecked against page 250. Logged as `COMPLIANCE_PARTIAL`. | **Hard** — changing that pass's merge rule risks reopening the false-"N" flood it was tuned to stop |
| **C22 residual** | Wrong-*entity* values of the right *type*: `Driver_LicensedYear = "2012"` was the *vehicle's* year. No type check can see this. | **Hard** — needs cross-field reasoning |

### The actual gap

| Issue | Why it matters |
|---|---|
| **No accuracy baseline has ever been run** | Every number produced this month is cost, cache rate, or coverage. **Nobody has measured whether the filled forms are more correct.** This is the only evidence that supports "same or better quality", and it would settle C21 in one afternoon. **Do this before any further optimisation.** |

### Cost — effectively exhausted

| Issue | Value | Verdict |
|---|---|---|
| Extraction chunk size | ~$0.11/run | **C31 done — but deliberately behaviour-neutral.** The literal is gone and it is now derived + clamped, still at 14,000 tok/call. Raising it toward capacity (20x headroom) would push extraction toward the same cliff as gap fill. Do not, without an accuracy baseline. |
| C9 alias bridge | $0.02–0.06/run | Earlier claimed as 19% — **that was wrong**. 4,530 of 4,571 alias names have no extracted fact to bind to. Noise. |
| `_COMBINED_FIELD_BATCH` 200 → 600 | ~$0.07/run | Declined — touches the C19 schedule invariant |

### Minor

- Searchable-scan detection thresholds (6% area / 80% bands) never tuned on real scanned
  files. Low risk: fails toward duplicated text, not lost text.
- Google Vision gRPC/service-account path never exercised live. Only matters if the API key
  is retired.
- Extraction retries the whole request on an unparseable reply; gap fill already salvages
  the completed portion instead (C6). Same fix applies.
- C17 — documents over ~2M chars are rejected outright. Correct: a clear refusal, not a
  silent cut.

---

## 7. Cost behaviour by document size (generic, not tuned to one file)

Calls are set by **field count** (which forms are selected), not document size.

| Document | Gap fill | Extraction | Total |
|---|---|---|---|
| 10 pages (15k chars) | $0.18 | $0.01 | **$0.20** |
| 50 pages (125k) | $0.32 | $0.05 | **$0.37** |
| 271 pages (684k) | $0.98 | $0.27 | **$1.25** (measured $1.29) |
| 600 pages (1.5M) | $3.42 | $0.59 | **$4.01** |

Small documents are near-fixed cost. Large ones scale linearly — **except one cliff**: past
~890k chars the document splits into 2 chunks and the call count doubles, so cost more than
doubles. That is auto-rescan working correctly (it must read both halves), but know it exists.

**Caching does not decay.** It is per-prefix, not a quota. Within one submission the first
call populates the prefix and the other 45 hit it — that is where ~44% of the bill at cached
rate comes from. Across submissions there is zero sharing and none is needed. **$1.29 is the
steady-state price, not a promotional one.** The only risk is idle TTL: if a run stalls
(repeated 429 backoff), a late call can miss and re-pay. Watch `cache_pct` per call — it
should read ~99 on gap-fill calls after the first of each stage. Extraction's 26–31% is
permanent and correct: each chunk is unique text, only the prompt prefix caches.

---

## 8. Rules for whoever picks this up

1. **`improving-ll.md` is the authority.** Any change to an LLM call, a prompt, or
   batching/chunking must update it in the same commit. Read §2's caching conditions first.
2. **Verify prompt shape offline**, never by diffing two live runs — the pipeline is
   non-deterministic and jitter hides regressions.
   `py backend/scripts/inspect_gap_fill_prompts.py`
3. **Never modify `backend/forms_schemas/*.json`** (ACORD field definitions) or hand-edit
   `backend/forms_aliases/`.
4. **Do not change `FIELD_FILL_BATCH=40` or `COMPLIANCE_BATCH=10` to save cost.** Frozen by
   accuracy work.
5. **Tests:** `py -m pytest` from `backend/`. Baseline **1,169 pass / 2 known failures**
   (`test_arq_acord125_missing_only`, `test_normalization`).
6. **Every LLM pass that carries the uploaded document must chunk through
   `pdf_service._split_text_on_boundaries`.** Three hand-rolled copies of that loop existed
   and one of them had already decayed into a truncation (C14). There is now one
   implementation; only the per-pass *budget* is local.
7. **The recurring failure mode on this project is documentation and tests claiming more
   than the code delivers** — "100% coverage" over a shredded document, a coverage proof
   with a silent mock, a comment promising a blank the code never writes, a fix whose tests
   only fed a correct input, **a constant that was "decoupled" only in the function that
   reserves budget for it while both functions that use it kept the old expression (C32)**.
   **Every change should ship with a test that would fail if the claim were false — and the
   test must exercise the site the claim is about, not a neighbouring one.**

---

## 9. Files changed (uncommitted)

```
backend/services/pdf_service.py          C22, C25, C27, C28, C29, C30, C16
backend/services/extraction_service.py   C23 (both rounds)
backend/utils/text_cleaner.py            C24
CLAUDE.md, improving-ll.md               documentation

new tests:
backend/tests/test_batch_packing_and_budget.py    C27/C28/C29/C30 + e2e guards
backend/tests/test_declared_type_guard.py         C22, incl. the 49k-pair sweep
backend/tests/test_currency_tiebreak.py           C23, incl. the live ORBIN replay
backend/tests/test_text_cleaner_preserves_content.py   C24
backend/tests/test_full_document_coverage.py      C25
backend/tests/test_extraction_chunk_sizing.py     C31, C32
backend/tests/test_umbrella_probe_coverage.py     C14 + the shared splitter
```

---

## 10. Suggested next steps, in order

1. `grep -c "UNKNOWN_KEYS" <logfile>` on the last real run. Non-zero → implement the
   90,000-token cap. Zero → leave the default and make it opt-in. **Still the blocker on
   C21, and it cannot be settled from the repo — there is no log file checked in.** This
   needs one real run's output from whoever has it.
2. **Run the accuracy baseline.** Same document, before/after, count correct fields. This is
   the missing evidence for the whole "same or better quality" claim.
3. Re-run the 271-page package and confirm the C23 fix live — the merge log should now show
   `gl_each_occurrence = $1,000,000`, not `$3,000,000`.
4. Confirm C14 live: on a package whose umbrella dec page sits past the first 60,000 chars,
   `map_facts UMBRELLA_PERIOD form=ACORD_131` should now log real dates instead of `None`.

**Audited 2026-07-30 and found clean** (recorded so the next reader does not re-derive them):
`clean_text` (C24) removes page furniture only; `_chunk_by_sections`'s
`text[:max_chars]` fallback is genuinely unreachable for non-empty text, because
`_find_section_boundaries` seeds `boundaries = [0]`, so `sections` is never empty; the
compliance pass's early break is correct rather than lossy — its absorber is strictly
first-wins, so once every question is answered the remaining chunks provably cannot change
an answer (C15's residual is supersession only, not coverage); and `raw_text` reaches
`combined_gap_fill` unmodified from `session["docs"]`.

**Two things found that are NOT fixed here, deliberately:**

- **SQS narrative scan, `_NARRATIVE_LLM_MAX_CHARS` = 16,000.** State this precisely,
  because the short version overstates it: **SQS does read the whole document** — via
  facts, from the full extraction pipeline. Five of six pillars (structural 0.25, exposure
  0.25, property 0.15, loss history 0.15, umbrella 0.10 = **90% of the weight**) never
  touch raw text. Only **P6 Narrative Quality, weight 0.10**, reads document bodies.

  And within P6 the cap is **conditional**. `_extract_narrative_doc_text` returns the
  **full, uncapped** body of any doc classified `narrative` (verified: 58,000 chars in,
  58,000 out). The 16,000 cut applies only to the *fallback* that fires when classification
  found no narrative at all. Real exposure: classification missed the narrative **and** the
  substance sits past 16,000 chars → a 0.10-weighted pillar under-credits. **No ACORD field
  can be affected.** Worth knowing: the fallback joins bodies in session order *then* cuts,
  so the first document can consume the whole allowance and later documents are read as
  zero chars rather than trimmed proportionally.

  Left alone deliberately — it moves a tuned score, and SQS thresholds and the
  dismiss-credit caps have their own calibration. Needs an SQS baseline, i.e. Brent's call,
  not a bug fix.

- `_build_narrative_scan_text` applies the 16,000 cap **unconditionally**, including to a
  correctly-classified narrative — and has **zero callers repo-wide** (verified by grep).
  It changes no score today, but its docstring reads like the intended entry point, so
  whoever wires it up silently caps the primary path too. Deleting it or fixing its cap is
  a **safe cleanup, not a scoring decision** — nothing calls it, so nothing can move.
- `truncation_warning` is plumbed end-to-end — `extraction_pipeline` → session → the
  `/upload` response → the frontend — and **nothing anywhere ever sets it.** It is a
  phantom safety net: a UI channel for "we cut your document" that cannot fire. Harmless
  today (the document paths above genuinely do not truncate), but it should either be wired
  to a real signal or deleted, so nobody reads its silence as evidence.
