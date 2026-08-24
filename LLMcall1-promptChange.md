# LLM Call 1 - Prompt & Index Pass Changes (2026-08-23)

One page, one purpose: **the declarations index now has exactly one producer, and
that producer no longer fails silently.**

Read this before touching `_EXTRACT_SCHEMA`, `_DEC_INDEX_SYSTEM_PROMPT` or
`_harvest_dec_index` in `backend/services/extraction_service.py`.

---

## 1. What LLM call 1 is, and the two jobs inside it

Uploading a PDF runs three stages:

| Stage | What happens |
|---|---|
| OCR | `ocr_service.extract_text()` turns pages into text, tables inline as `[Table - page N]` |
| **LLM call 1** | reads that text, produces **facts**, **flags** and the **declarations index** |
| LLM call 2 | reads the index first (Stage A), then fills ACORD form fields |

Inside LLM call 1 there were always **two separate LLM jobs**:

- **Job A** - the main extraction call. One prompt, one reply:
  `{"facts": {...}, "flags": {...}}`. Facts and flags are two keys in the **same**
  reply from the **same** call. Until today `dec_page_entries` was a third thing,
  a key living *inside* `facts`.
- **Job B** - a dedicated index-only call (`_harvest_dec_index`), its own system
  prompt, run only on declarations-dense chunks.

Both wrote into the same `dec_page_entries` list, in **two different shapes** -
Job A produced 6 keys per entry, Job B produces 13.

---

## 2. The defect this change fixes

Job B had been returning **zero entries on every real run**, and nobody could tell,
because every error path in `_harvest_dec_index` was caught and turned into `[]`
with a `logger.warning`. The pipeline carried on and built a normal-looking index
entirely from Job A.

Proof, from session `c3d49f5a-6d6a-4759-b6ec-286ecab8e6be`:

```
251 raw entries x 6 keys  [Job A]
  0 raw entries x 13 keys [Job B]
```

**Root cause, measured - not guessed.** A live single-chunk probe logged:

```
LLM_SPEND stage=extraction in=10047 out=16000 cache_pct=94
_safe_json_parse [dec_index[0]]: reply was not valid JSON
  (almost always truncation at the output cap) - SALVAGED ...
```

`out=16000` is `DEC_INDEX_MAX_TOKENS` **exactly**. The 13-key atomic schema costs
~86 output tokens per entry against ~51 for the old 6-key one, so **every** Job B
call now runs to the cap. On a 7,835-char fixture. Real chunks are ~56,000 chars.

Chain of failure:

1. Every call maxes out the output cap → every call is the slowest possible.
2. All eligible chunks fired at once through a bare `asyncio.gather` with no
   pacing of its own (unlike the main extraction, which has an adaptive semaphore).
3. ~14 maximal calls = roughly half a million tokens in one burst against a
   200k TPM ceiling → 429 storm.
4. Five retries with 1/2/4/8s backoff (~15s) nowhere near clears a TPM window.
5. Every call raises → every error swallowed → `[]` → silent.

That is why "the v3 prompt did nothing". The prompt was never wrong. Its calls died.

---

## 3. Changes made

All in `backend/services/extraction_service.py` unless noted.

### 3.1 `dec_page_entries` removed from Job A's schema

The key and its ~1,400-character instruction block are gone from `_EXTRACT_SCHEMA`.
Job A now returns facts and flags only.

**Why.** Two prompts writing one list in two shapes, and the weaker one usually won
because Job A runs on *every* chunk while Job B only runs on declarations-dense
ones. The measured cost of asking in Job A was never in doubt either: the model
budgets one reply across ~170 keys, so the index came back thin - ~19 entries per
chunk against a 150 allowance, from pages carrying an estimated ~750. Attention is
the constraint; separation is the fix.

**The facts/flags prompt is otherwise byte-identical.** No field added, none
removed, no rule reworded. It went 39,633 → 38,219 chars - purely the deleted block.

### 3.2 `PROMPT_VERSION` / `SCHEMA_VERSION` → `v13`

**Mandatory, not cosmetic.** These are part of the extraction cache key. The
facts/flags prompt genuinely changed this time, so without the bump every cached
extraction would keep serving replies built from the old schema.

### 3.3 `DEC_INDEX_MAX_TOKENS` 16,000 → 50,000

This caps what the model may **write back**. It is not the prompt size.

Raising it **does not raise the bill** - output is billed on what the model
actually writes, so the cap only decides where the text is severed. The model
allows 128,000, so 50,000 keeps 2.5x headroom and still stops a looping model from
writing forever and hanging the request. **Kept as a runaway guard; it is not the
mechanism that guarantees a complete reply.**

### 3.4 NEW `DEC_INDEX_CHUNK_CHARS` = 15,000 - *this* is the mechanism

Measured: 7,835 chars of declarations text produced >16,000 output tokens - **over
2 output tokens per input character.** Projecting the extraction chunk the router
hands us:

| Input chunk | Output tokens needed |
|---|---|
| 56,000 chars (what it used to get) | **~114,000** |
| 30,000 chars | ~61,000 |
| 20,000 chars | ~41,000 |
| **15,000 chars (new)** | **~31,000** |

The model's absolute output ceiling is 128,000. A 56,000-char chunk sits at 89% of
it with no margin - **no cap value fixes that; the reply simply cannot fit.**

Note the distinction that matters: the 400,000-token *context window* is for
**input**. The **output** ceiling is separate and much smaller. Input size is the
only lever that moves output size, so the index pass now re-splits its chunks on
line boundaries before calling.

Cost of splitting is small and worth naming: total **output** is unchanged (same
document, same entries, divided differently) and output is the expensive half. The
extra cost is re-sending the instruction prefix, which runs at a measured 94% cache
hit.

### 3.5 NEW `DEC_INDEX_POOL` = 3 - bounded concurrency

The bare `asyncio.gather` over every eligible chunk is replaced by an
`asyncio.Semaphore`. **This is the actual bug fix** - the thing that made Job B
work standalone and die in the pipeline.

### 3.6 NEW `DEC_INDEX_SPLIT_RETRIES` = 3 - truncation is detected, not salvaged

Nothing in the codebase reads `finish_reason`; the API tells us plainly when a
reply was cut off and we ignored it completely. Rather than change the shared LLM
wrapper (every call site uses it), `_harvest_dec_index` now parses the reply
itself: **a complete JSON reply parses on its own.** One that does not was severed
at the cap, so the piece is split in half and both halves retried, up to 3 levels
(one 15,000-char piece → eight ~1,900-char pieces).

The old behaviour accepted whatever `_safe_json_parse` could salvage from the
completed portion - silent, unmeasurable data loss. Salvage is still the fallback
at max depth, so a stubborn piece still contributes what the model wrote.

### 3.7 `DEC_ENTRY_MAX` 1,200 → 3,000 - and why not higher

> **SUPERSEDED by Round 2 §11.** It is now **50,000**, a pure runaway guard.
> This section is kept because the reasoning below is exactly why it *could not*
> be raised until the splitter was fixed - and why nobody should reinstate a low
> ceiling without re-reading §11 first.

1,200 was sized for the 6-key shape where one printed row became one entry. The
atomic schema splits that row into one entry **per cell**, so the old ceiling
truncates a large package's index long before the token cap fires.

**25,000 was tried first and a test caught it.**
`tests/test_dec_index_stage_a.py::test_a_full_index_fits_in_one_call` failed: a
maximum index renders to **1,804,092 chars against a 222,878-char single-call
budget** and splits into **twelve** Stage A calls.

Splitting is not a cost problem, it is a **correctness** problem: it puts the
umbrella's $3,000,000 and the GL's $1,000,000 back into separate calls under
identical labels - the exact C23 defect Stage A exists to prevent. At ~72 rendered
chars per entry the budget holds ~3,088, so **3,000 is the ceiling with a margin.**

Raising the budget instead was considered and rejected: it would take
`GAP_FILL_DEC_INDEX_BUDGET_MULT` from 2 to ~8, putting ~225k tokens in one call -
squarely inside the long-context degradation already measured in `improving-ll.md`
C21 (the model stops copying field names and invents its own).

The ceiling is kept rather than removed for a second reason: entries land in the
session row, and an unbounded list lets a looping model write unbounded data into
Postgres.

### 3.8 Zero harvest is now an ERROR

Job B is the **only** producer of the index now, so "nothing harvested from chunks
that ARE declarations" is a broken run, not a quiet nothing. It logs at `ERROR`
with the piece count. It stayed silent for two full runs and cost days.

### 3.9 Seven stale test pins re-pinned

Seven tests asserted exact phrases from the pre-v3 prompt. Every guarded
**behaviour** is still present in v3 - only the wording changed (case, "weld" for
"concatenate", "label == value" for "SAME TEXT as its value"). Each was re-pinned
to v3's actual words with a comment saying why. **No guarantee was dropped.**

`test_the_prompt_asks_for_one_entry_per_cell` additionally had its second
assertion inverted: it used to require the rule in *both* recording prompts; it now
asserts `dec_page_entries` is **absent** from `_EXTRACT_SCHEMA`, so if the key ever
reappears there the two-shapes defect fails the build.

---

## 4. Does this affect the deterministic form-fill pass?

**The deterministic pass stays, unchanged.** Pass 1 (`_deterministic_map`,
`_ACORD_FIELD_RULES`) and Pass 1.5 (alias stamping) fill form fields from **facts**.
No code path in either was touched.

**But yes - Job A's dec entries DID feed the deterministic layer.** They are read
in ~30 places, and several are deterministic resolvers:

| Consumer | What it does |
|---|---|
| `_backfill_empty_facts_from_entries` | fills facts that merged empty |
| `_repair_coverage_lines_from_entries` | `_policy_numbers_by_line`, `_carriers_by_line` |
| `_resolve_section_policy_identity` | gives a section form its own policy number |
| `_entries_state_payroll` | drives `dec_states_payroll_basis` and the GL exposure warning |
| `text_selection` rescue net | keeps dec values out of the density filter's bin |
| Stage A of LLM call 2 | `_render_dec_index` |

**None of them changed, and none of them care which job produced an entry** - every
one reads the merged `facts["dec_page_entries"]`. The merge, the verbatim gate
(`_verify_dec_entries`) and the key canonicaliser are untouched.

**The residual risk, stated plainly:** that list now has a single producer. If Job B
yields nothing, the list is *empty* rather than *thin*, and those consumers lose
their evidence. That is precisely why 3.5, 3.6 and 3.8 exist. The old safety net was
a second prompt in a different shape - which was itself the defect.

---

## 5. Measured before / after

Single-chunk live probe on `test_data_v1_c1/5_complex_tables.pdf`:

| | Before | After |
|---|---|---|
| output tokens | **16,000 (capped, cut off)** | 20,114 (complete) |
| entries returned | 187 (salvaged from a truncated reply) | **232** |
| keys per entry | 13 | 13 |
| truncation retries | n/a - loss was silent | 0 needed |

**+45 entries (+24%) from one chunk, purely by not being truncated.**

Full suite: **3698 passed / 2 failed** - `test_arq_acord125_missing_only` and
`test_normalization`, the same two pre-existing unrelated failures as every entry
in `improving-ll.md`. **Zero regressions.**

---

## 6. Where things live, and how to look at them

Both prompts are in **one file**, `backend/services/extraction_service.py`. There
is no prompts directory and nothing is loaded from disk.

| | Constant | Dump of it |
|---|---|---|
| Job A (facts + flags) | `_EXTRACT_PROMPT_PREFIX` (embeds `_EXTRACT_SCHEMA`) | `LLM_CALL1_PROMPT_FACTS_FLAGS.txt` |
| Job B (the index) | `_DEC_INDEX_SYSTEM_PROMPT` | `LLM_CALL1_PROMPT_DEC_INDEX.txt` |

```powershell
cd backend

# facts + flags (and the per-document raw data)
py scripts/dump_session_facts.py <session_id> --json > facts.json
#   top-level keys: session_id, merged_facts, flags, documents

# the declarations index that LLM call 2 reads - BEFORE generating forms
py scripts/dump_dec_index.py <session_id>
#   writes dec_index_<session_id>.json
```

**To check whether Job B ran**, the merged index is the wrong place - the verifier
rebuilds every entry from six keys and drops label-null entries. Use the raw
per-document copy:

```powershell
py -c "import json;d=json.load(open('facts.json',encoding='utf-8'));e=d['documents'][0]['facts']['dec_page_entries'];print(len(e),'entries |',len(e[0]),'keys')"
```

**6 keys = Job B did not run. 13 keys = it did.**

---

## 7. Known, deliberately not done

- **The verifier still strips the new keys.** `_verify_dec_entries` rebuilds every
  entry from the original six (`label, value, section, owner, policy_number,
  line_of_business`) and drops any entry with an empty label - which discards every
  `standalone` / `heading` / `statement` / `footer` / `index` entry v3 produces.
  So `id`, `page`, `kind`, `path`, `row`, `col`, `value_type` and `qualifiers`
  reach nothing downstream today. **Until that is widened, the extra structure buys
  nothing.** Separate change, wider blast radius (the render, the dedup key, ~30
  consumers) - decide it on its own.
- **v3 has no `section` key**, and the verifier reads one, so every merged entry now
  carries `section = null`. `_render_dec_index` groups by section, so call 2 sees one
  flat group per policy/line instead of per-page groups, and the dedup key
  `(label, value, section)` loses its third term. `path` carries that information
  now but nothing reads it. Watch for a thinner-looking merged index for this reason
  rather than a prompt-quality reason.
- **`finish_reason` is still unread by the shared LLM wrapper.** Job B detects
  truncation by parsing; other call sites remain blind to it.

---

## 8. Rollback

- Job B off: `DEC_INDEX_DEDICATED_PASS=0` - **but the index is now empty if you do
  this**, because Job A no longer records entries. To fully revert, restore the
  `dec_page_entries` block into `_EXTRACT_SCHEMA` from git history **as well**, or
  the two shapes fight again.
- Caps back to old behaviour: `DEC_INDEX_MAX_TOKENS=16000`, `DEC_ENTRY_MAX=1200`.
- Splitting off: `DEC_INDEX_CHUNK_CHARS=56000` (reproduces the truncation).
- Concurrency back to unbounded-ish: `DEC_INDEX_POOL=32`.

---

## 9. Next run - what to check

1. `grep dec_index_pass` in the backend console. Expect
   `harvested N raw entries from M piece(s)`, **no `ERROR`**, and no
   `chunk N failed`.
2. Raw per-document entries carry **13 keys**.
3. Compare entry count against baseline session `555b8079` (79 verified, old prompt)
   and `c3d49f5a` (227 verified, Job A only).
4. If `DEC_ENTRY_MAX` fires, the log says so - that is a signal, not routine.

---
---

# ROUND 2 (same day) - the index stops losing data, and the new keys survive

Round 1 made Job B *run*. Round 2 makes what it produces *arrive*. Four changes,
labelled A-D throughout.

The owner's objection to Round 1 drove it, and it was right: *"we cannot just miss
the data and leave things out... we should cover whole data."* Round 1 protected
correctness by capping entries at 3,000 - which means dropping declarations values
on a large package. That trade was accepted too quickly.

## 10. A - the index splits BY LABEL, never by character

**What was actually wrong.** `_dec_index_chunks` cut the rendered index with
`_split_text_on_boundaries` - a blind **character** cut. It had no idea which
entries needed to stay together, so it separated the umbrella's $3,000,000 from
the GL's $1,000,000 by accident of position. That made splitting unsafe, which
forced a low entry ceiling, which dropped data. **Two bad outcomes from one dumb
splitter.**

**The property that matters is narrow.** Two entries must share a call when they
share a **label** - that is the only case where the model has to tell them apart
("Each Occurrence Limit" is $1,000,000 for GL and $3,000,000 for the umbrella).
So: group entries by normalised label, bin-pack whole groups. A label can never
straddle two pieces, at any index size.

**A design was measured and rejected first.** The initial idea was to find the
"contested" labels and repeat them in every piece. On the live 227-entry package:

```
distinct labels  : 148
CONTESTED labels : 34   (same label, different value/policy/line)
entries in them  : 105  = 46% of the index
```

At 46% the duplication costs more than the split saves. Grouping costs nothing.

**The normal case is byte-identical.** An index that fits returns early, exactly as
before. Label-packing runs only on a package big enough to need it.

## 11. B - `DEC_ENTRY_MAX` 3,000 → 50,000, a runaway guard

Only possible because of A. It is **not** removed: entries land in the session row
in Postgres, and an unbounded list lets a looping reply write unbounded data. At
50,000 - roughly forty times the largest package measured - it cannot fire on a
real document, so if it ever does that is a signal to chase, and it logs one.

## 12. C - `section` recovered, and `row`/`col` carried through

**`section` was silently broken by v3 and this fixes it.** v3 has no `section` key;
it sends a `path` array of enclosing headings, outermost first. The verifier reads
`section`, so **every entry was arriving section-less** - which collapses
`_render_dec_index` into one flat group and strips the third term from the dedup
key. That is C23 arriving by the back door. `path[0]` *is* what section has always
meant ("the heading at the top of the page"), so it now falls back to it. Derived
from the model's own output, never invented, and still faces the printed check.

**`row` and `col` are carried, and `row` joins the dedup key.** That is a bug fix,
not a preference: two rows of one rating table printing the same rate under the
same column used to **collapse into one entry**. Proven on realistic data - two
rows both reading `6.119` now both survive, where before one vanished.

**`row` renders as a prefix, only when present:** `  (91580) RATE: 6.119  [policy]`.
Every non-table line renders exactly as before, so existing render tests hold.

**`page`, `kind`, `value_type`, `qualifiers`, `path` are carried as inert extra
keys**, each validated against its closed vocabulary or dropped. Safe because
**no consumer of these entries iterates their keys** - all ~30 read named keys.
That was audited before the change, not assumed.

## 13. D - a captionless value is data, not junk

The verifier dropped any entry with an empty label as malformed. Under v3
`label: null` is **deliberate** - it marks headings, footers, statements and, the
case that matters, a **carrier name printed bare on a masthead**. Rule 16 exists to
capture exactly that, and the gate was deleting it.

Now: a missing **value** is still malformed. A missing **label** is not. `path[-1]`
supplies the nearest printed caption when there is one; otherwise the entry is kept
with an empty label and **only its value is verified** - an absent label is not a
fabrication risk, an invented one would be.

**Empty string, never `None`.** Every reader in the codebase guards with
`str(x.get("label") or "")`, but `_backfill_empty_facts_from_entries` slices
`entry["label"][:60]` directly, which `None` would crash. `""` is identical at
every guarded site and cannot crash the unguarded one. This was found by auditing
all 25 label readers, not by testing and hoping.

## 14. Round 2 verification

End-to-end on realistic v3 entries against a real document:

| Check | Result |
|---|---|
| captionless carrier kept | **yes** |
| it reaches `_carriers_by_line` | `{'general_liab': {'EMC Property & Casualty Company'}}` |
| `section` derived from `path` | yes, on every entry that has a path |
| two rating rows with the same rate | **both survive** (one was lost before) |
| fabricated `$99,999,999` | **still dropped** - verification intact |
| `row` visible to call 2 | `(91580) RATE: 6.119` / `(91585) RATE: 6.119` |

Full suite: **3702 passed / 2 failed** - the same two pre-existing unrelated
failures. **+4 net tests. Zero regressions.**

## 15. Tests whose contract genuinely changed

Two, both updated with the reason written into the docstring rather than quietly
re-pinned:

- `test_a_full_index_fits_in_one_call` → **`test_a_realistic_index_still_fits_in_one_call`**.
  It used to force `DEC_ENTRY_MAX` to stay small enough to fit one call - which is
  precisely what dropped data. It now pins the realistic case (3,000 entries, over
  ten times the largest package measured) and the split safety moved into two new
  tests.
- `test_an_entry_missing_a_half_is_dropped_not_rendered_blank` →
  **`test_an_entry_missing_its_value_is_dropped_not_rendered_blank`**. Missing value
  still dropped; missing label now kept as a bare line.

Three tests added for the new invariants:

- `test_a_split_never_separates_two_entries_sharing_a_label` - the C23 property at
  any index size
- `test_a_split_loses_no_entry_and_duplicates_none` - every entry appears exactly
  once across all pieces
- `test_a_captionless_value_is_kept_and_still_verified` +
  `test_a_captionless_value_borrows_its_heading_as_a_caption`

## 16. Still open after Round 2

**The joins do not use `row` and `col` yet.** The data now survives all the way to
LLM call 2 and is visible in the rendered index, but the ~30 deterministic
resolvers still match on label alone. Teaching them to join on `row` changes how
form fields get filled and deserves its own change, its own tests and its own
before/after on a real upload. **That is the only remaining piece of the original
13-key argument.**

Also unchanged: `finish_reason` is still unread by the shared LLM wrapper (Job B
detects truncation by parsing instead), and no prompt was touched in Round 2.

## 17. Round 2 rollback

- `DEC_ENTRY_MAX=3000` restores the Round 1 ceiling.
- The label-aware split has no switch - it only runs where the old code would have
  split anyway, and the old behaviour was measurably unsafe. Revert
  `_dec_index_chunks` from git history if it must go.
- C and D are additive; reverting means restoring `_verify_dec_entries` and
  `_render_dec_index` from git history.

---
---

# ROUND 3 - the slowdown I caused, and the cost bug underneath it

**Reported from a live run: "it took thrice the time to recommend forms."** True,
and Round 1's chunk sizing caused it. Round 3 fixes that and the older cost bug it
exposed. No prompt changed; no behaviour removed.

## 18. What went wrong

`DEC_INDEX_CHUNK_CHARS = 15,000` was set from the output cap alone, before any call
had been timed. It turned a 13-chunk package into **47 index calls**, which
`DEC_INDEX_POOL = 3` then serialised into 16 waves.

**One call, timed:** 7,907 chars in -> 21,672 output tokens in **89.2s = 243
tokens/sec**. So 47 calls at pool 3 is **~34 minutes** of index pass alone.
Individual calls never came close to the 300s timeout (a 15,000-char piece needs
~128s) - the cost was pure volume.

## 19. The cost bug underneath, which is older than Round 1

`declarations_authority` returns the **MAXIMUM over page-sized windows**. That is
correct for ROUTING a chunk - a real dec page occupying 14% of a 56,000-char chunk
must not be averaged away, and the function's own docstring argues exactly that.
It is wrong for BILLING one: **a chunk containing a single dec page among fifty
pages of policy wording clears the gate, and all 56,000 chars were then indexed.**

On the client's package - roughly 30 declarations pages out of 271 - that sent
~240 pages of wording to the model to produce nothing. It was invisible while every
reply was being truncated at 16,000 tokens anyway.

## 20. The fix

**Split first, then score each piece.** The routing gate keeps its sensitivity (a
piece is close to page-sized, and the max is taken over it, so nothing
declarations-dense is skipped) while the wording that merely travelled in the same
chunk is dropped before it costs anything. A chunk whose pieces ALL fall below the
bar keeps its single best piece - the chunk did clear the bar, so something in it
is declarations content and must not vanish.

**`DEC_INDEX_CHUNK_CHARS` 15,000 -> 22,000**, sized from the measurement rather than
the cap. At ~2.05 output tokens per input char a 22,000-char piece projects to
~45,000 tokens and ~185s - inside both the 50,000-token cap and the 300s timeout,
with margin - and cuts the call count by a third.

**`DEC_INDEX_POOL` 3 -> 6.** 3 was set blind. 6 is still half the `llm_limiter` cap
of 12, so the main extraction and any concurrent user keep room.

| | calls | waves | worst case |
|---|---|---|---|
| Before Round 1 | 13 | 1 | fast, but every reply truncated |
| Round 1 (15k, pool 3) | 47 | 16 | **~34 min** |
| Round 3 (22k, pool 6) | <=32 | <=6 | **~18 min**, and the piece gate cuts it far below that |

The worst case assumes every piece is declarations-dense. On a real package most
pieces are wording and never make a call at all.

## 21. Still unexplained: the index came back EMPTY

Session `3c4f0538` produced 51 facts, 44 flags and **0 dec entries**. Job A no
longer records them (by design, §3.1) and Job B yielded nothing, so the index is
empty rather than thin - exactly the single-producer risk named in §4.

The timing theory is DEAD: at 243 tokens/sec no individual call approaches the
300s timeout. The remaining candidates are a 429 burst or a parse failure, and
`_harvest_dec_index` logs the reason per chunk at WARNING plus an ERROR summary
(§3.8). **That log line is the only thing that can settle it** - the console for
that run holds the answer:

```
grep -E "dec_index_pass|ERROR" <backend console>
```

Until it is read, do not guess. The fixes in Round 3 reduce load by ~4x, which
would make a 429 cause disappear on its own - if that is what it was, the next run
will simply work, and the ERROR line will confirm which.

---

## 22. THE REAL COST BUG: the authority gate is blind on a real package

Measured on the client's 699,844-char package (session `2f7517cf`):

```
extraction chunks                : 14
chunks clearing the 0.25 gate    : 14  (100%)
pieces at 22,000 chars           : 39
pieces clearing the 0.25 gate    : 39  (100%)
authority distribution           : {0.4: 1, 0.5: 33, 0.6: 4, 0.7: 1}
```

**Thirty-three of thirty-nine pieces score exactly ~0.5.** The gate is not
separating declarations from policy wording on this document - it is passing
everything, so the pass indexes all 271 pages. §20's piece-level re-gate is
correct and costs nothing, but on THIS package it drops nothing, because there
is nothing the gate is willing to drop. That claim in §20 was too optimistic and
is corrected here.

**Why.** `_window_authority` is `0.5 * figure_density + 0.5 * brevity`, and
`brevity` measures mean LINE LENGTH against a 75-char prose baseline. This
document's text layer breaks lines at the PDF's own visual line breaks, so even
policy wording arrives as short lines - **brevity saturates at ~1.0 everywhere
and hands every piece a free 0.5.** A 0.25 bar is then cleared by any text at
all. The signal was designed for wrapped prose vs printed schedule rows; a
column-laid-out policy PDF defeats the prose half of it.

Raising the bar works, and the numbers are stark:

| bar | calls | share of the document |
|---|---|---|
| 0.25 (today) | 39 | 100% |
| 0.50 | 38 | 97% |
| **0.60** | **5** | **13%** |
| 0.70 | 1 | 3% |

0.60 requires real figure density on top of the free brevity 0.5, which is
exactly the declarations signal. ~30 declarations pages out of 271 is 11% - so
13% is the right order of magnitude, independently.

**NOT CHANGED UNILATERALLY.** `_DEC_INDEX_MIN_AUTHORITY` shares its scale with
`_AUTHORITY_TIER_CUTS`, which ranks facts during the merge, and a document whose
text layer DOES wrap prose normally would score brevity near 0 and could never
reach 0.60 however dense its figures. A safe change is a threshold that belongs
to the index pass alone, defaulted around 0.55-0.60, with the old value one env
var away. That is a decision, not a tidy-up, and it is the next thing to make.

## 23. Job B itself is not broken - proven on the real document

One real 22,000-char piece from the client's package, through the live call path:

```
dec_index_pass: 1 of 1 chunk(s) are declarations-dense (authority >= 0.25)
LLM_SPEND  in=13798 cached=0 out=9820
dec_index_pass: harvested 120 raw entries from 1 piece(s) across 1 chunk(s)
RESULT: 120 entries in 41.1s
keys: ['col','id','kind','label','line_of_business','owner','page','path',
       'policy_number','qualifiers','row','value','value_type']
```

**120 entries, all 13 keys, 41 seconds.** The prompt, the call path, the parse,
the split-retry and the verifier all work. Whatever emptied the index on the full
run is a scale effect, not a code defect - and the per-chunk WARNING plus the
zero-harvest ERROR (§3.8) name it. That console line is still the missing
evidence; sessions `3c4f0538` and `2f7517cf` both have 0 raw entries and neither
console was captured.

Note `cached=0` on that call: the 30,418-char system prompt is not being served
from the prefix cache on a cold run, so each call pays ~7,600 input tokens in
full. Worth watching once the pass runs at scale again.

## 24. `DEC_INDEX_POOL` back to 3, with the arithmetic this time

Raised to 6 in §20 to claw back wave count. That was a second blind tune and the
measurement says it does not fit:

```
one measured call: in=13,798  out=9,820  over 41s  =  ~35,000 tokens/minute
pool 6 -> ~210,000 TPM   over the 200,000 ceiling, before extraction's own calls
pool 3 -> ~105,000 TPM   with room beside the main pass
```

Wave count is the wrong thing to optimise while the pass still indexes the whole
document. The fix for that is §22, not more parallelism.

---
---

# ROUND 4 - the actual root cause: a 429 is a clock, not an error

## 25. Proven from the live log

Session at 20:48 on 2026-08-22, from the owner's console:

```
extract_facts: cache HIT key=1e9599c0 - returning cached result, no LLM call   (x14)
gather_chunks chunks=14 failed=0 llm_calls=14
dec_index_pass: 14 of 14 chunk(s) are declarations-dense
dec_index_pass: 14 chunk(s) -> 39 piece(s) of <=22000 chars (0 dropped)
LLM_SPEND ... out=8938  cache_pct=69   HTTP 200 OK
LLM_SPEND ... out=20944 cache_pct=53   HTTP 200 OK
LLM_SPEND ... out=29409 cache_pct=52   HTTP 200 OK   ... every call 200 OK
```

**The main extraction made ZERO real API calls on this run - all 14 were cache
hits**, because the same document had been uploaded before. No first burst. And
Job B worked: every call returned 200, no 429, no error.

That is the controlled experiment the earlier runs were missing:

| run | main extraction | first burst | index result |
|---|---|---|---|
| 3c4f0538, 2f7517cf | cold cache, 14 real calls | yes | **0 entries** |
| 20:48 run | warm cache, 0 real calls | no | calls succeed |
| offline probe (§23) | not run at all | no | 2,215 entries |

Cold cache -> burst -> empty. Warm cache -> no burst -> works. The prompt, the
parse and the verifier were never the problem.

## 26. The bug, in one line

`config/settings._openai_chat` backed off `2 ** attempt` for EVERY retryable
status: 1s, 2s, 4s, 8s, then raise. **Fifteen seconds of total patience against
a tokens-per-minute limit that clears on a SIXTY-second window.** Every index
call gave up while the limit still had 45 seconds to run, and
`_harvest_dec_index` caught every failure and returned `[]`.

## 27. The fix

Two narrow changes in the shared wrapper, and nothing else:

1. **`Retry-After` wins.** OpenAI states the wait in a response header and we
   ignored it completely. It is now read and obeyed, capped at
   `LLM_RETRY_AFTER_MAX` (90s) so a mistaken header cannot stall the pipeline.
2. **429 gets a schedule that crosses a minute**: 5s, 15s, 30s, 60s. Every other
   retryable status - 500, 502, 503, timeout - keeps the original 1/2/4/8
   exactly, because those clear in milliseconds and slowing them helps nobody.

Verified across every branch:

```
429, no header   : [5, 15, 30, 60, 60]     (was [1, 2, 4, 8, 16])
500, no header   : [1, 2, 4, 8]            unchanged
timeout          : [1, 2, 4, 8]            unchanged
Retry-After 42   : 42
Retry-After 9999 : 90                      capped
Retry-After junk : 30                      falls back to the 429 schedule
total 429 patience: 110s   (was 15s; the window is 60s)
```

**Caught during the change:** the new helper was annotated `status: Any` and
`Any` is not imported in `settings.py`. Python 3.14 defers annotation
evaluation, so it ran fine and every test passed - but `typing.get_type_hints()`
raised `NameError`. Changed to `object`. Worth remembering: on 3.14 a bad
annotation is invisible until something introspects it.

## 28. What was deliberately NOT done

**The authority gate stays at 0.25 - the whole document keeps being indexed.**
§22 proposed raising it to 0.60 to cut 39 calls to 5. The owner's instruction
overrides it: *"Whole document uploaded by user is important."* Filtering to 13%
would drop declarations values on the skipped pages, and which page a form needs
cannot be known in advance. The proposal is withdrawn, not deferred.

**Merging the index back into the main extraction was analysed and rejected**,
twice asked and twice measured:
- Rate limits count TOKENS, not calls. The index is ~600,000 output tokens
  however it is packaged; 14 big calls hit the same ceiling as 39 small ones.
- One 56,000-char chunk needs ~43,000 output tokens for the index ALONE, against
  Job A's 32,000 cap. It cannot fit, which is exactly why the merged version
  only ever recorded ~19 entries per chunk.
- A truncated merged reply loses **facts and flags**, not just index entries.

**No settle delay between the two passes.** It was considered and dropped: with
correct 429 handling the burst self-corrects in one backoff, and an
unconditional sleep would tax every run for a problem that now fixes itself. If
a future run still shows a burst, `DEC_INDEX_POOL` is the dial.

Full suite: **3702 passed / 2 failed** - the same two pre-existing unrelated
failures. Zero regressions.

## 29. What to expect on the next cold run

- ~39 index calls, ~600,000 output tokens, **roughly 3-5 minutes** for the index
  pass. That is the floor for 46x more data; it is not a fault.
- Some calls WILL take a 429 and now wait 5-60s instead of dying. Expect
  `OpenAI 429 on attempt N, retrying in 15s` in the log - that line is the fix
  working, not a problem.
- `dec_index_pass: harvested N raw entries` with N in the low thousands.
- If it still comes back empty, the ERROR line names the reason and it is
  something new - the 429 path is now closed.

---
---

# ROUND 5 - THE ACTUAL BUG. One wrong key path, there since day one.

**Rounds 2, 3 and 4 all chased the wrong thing.** The rate-limit theory was
wrong. The calls were never failing.

## 30. What the owner's 23:04 log proved

```
23:04:47  dec_index_pass: 14 chunk(s) -> 39 piece(s) of <=22000 chars
23:05:20  LLM_SPEND ... out=7921   HTTP 200 OK
23:05:45  LLM_SPEND ... out=14110  HTTP 200 OK
```

**The index calls SUCCEEDED.** No 429. No timeout. Real output. And the session
still stored **0 entries**.

That killed every theory to date and pointed at the plumbing between the call
and the session.

## 31. The bug

`_merge_list_fields` returns `{"facts": {...}, "flags": {...}}`. Dec entries live
at `result["facts"]["dec_page_entries"]`.

The merge block in `_run_extraction` read and wrote the **top level**:

```python
_base = result.get("dec_page_entries")          # always None - wrong level
_base = _base if isinstance(_base, list) else []
result["dec_page_entries"] = _base + _extra     # filed one level too high
```

Nothing reads that key. `_validate_extraction_output` forwards it as an
unrecognised extra, and `extraction_pipeline` stores only `extracted["facts"]`.
**Every entry the dedicated pass ever produced was thrown away at this line.**

Proven directly:

```
Job B produced        : 1 entries
landed at TOP level   : 1
landed inside facts   : 0     <- what every consumer reads
```

## 32. Why it hid for so long

While the MAIN extraction also recorded dec entries, those went into `facts`
correctly. The index looked populated - 251, 245, 273, 350 entries across past
sessions - and the dedicated pass's contribution silently evaporated beside it.
**The dedicated pass has never once contributed an entry to a real session.**

Removing that key from the main schema (§3.1) took the last working producer
away and exposed it. Three consecutive live runs then logged successful index
calls and stored zero.

Every offline probe in §23 and §25 passed because they called
`_harvest_dec_index` **directly** and read its return value - which was always
correct. The defect is one line further downstream, and only the full pipeline
crosses it.

## 33. The fix

Read and write `result["facts"]["dec_page_entries"]`. Four lines, plus a
defensive rebuild if `facts` is somehow absent. The log line that printed the
same wrong key is corrected too.

Verified through the real path - merge, then
`extraction_pipeline._validate_extraction_output`:

```
Job B produced         : 2215
inside result[facts]   : 2215
stray at top level     : 0
survives validation    : 2215   <- what the session stores
VERDICT: FIXED
```

## 34. What the earlier rounds were worth

- **Round 4 (429 backoff)** - not the cause, but a real latent defect: 15s of
  patience against a 60s window. Kept.
- **Round 3 (22k pieces, pool 3)** - not the cause. The sizing is measured and
  correct; keep it.
- **Rounds 1-2 (the caps, the concurrency, the split-retry)** - all real, all
  needed once entries actually flow. `DEC_ENTRY_MAX` at 1,200 would have
  truncated ~7,000 entries down to 1,200 the moment this fix landed.

The lesson, and it is the repo's own standing rule: **the offline probe proved
the FUNCTION, never the PIPELINE.** Three rounds of theory came from testing one
component in isolation and assuming the seam around it was sound.

Suite after the fix: unchanged pre-existing failures only.

---
---

# ROUND 6 - IT WORKS. First real v3 index, and what it shows.

Session `e7f46273`, 2026-08-22 23:48, cold cache, full 271-page package:

```
DOC 0: 6687 entries x 13 keys  [dedicated pass (13-key)]
MERGED (verified, what LLM call 2 reads): 5635 entries
```

**6,687 raw -> 5,635 verified.** Against ~250 six-key entries before. The
plumbing fix (§33) was the last blocker; every earlier round's work was needed
for these numbers to survive - `DEC_ENTRY_MAX` at 1,200 would have cut 5,635 to
1,200 on its own.

## 35. What is now proven working

- **The C23 discriminator, on real data.** `Each Occurrence Limit` = $1,000,000
  under General Liability and $3,000,000 under Commercial Umbrella, in one index,
  correctly keyed. That is the defect the whole Stage A design exists to prevent.
- **4 distinct policy numbers**, 758 entries keyed to one.
- **5,392 of 5,635 entries carry a line_of_business** (96%).
- **56 carrier-owned entries**, up from a handful.
- **Label quality is good**: 1 label==value in 5,635; 5 inversions.

## 36. What the index shows that needs deciding - NOT yet acted on

**1,607 entries (29% of the index) come from POLICY WORDING pages**, which rule
9a tells the model to record nothing from:

```
  86  PERILS EXCLUDED
  85  SECTION V - DEFINITIONS
  82  SECTION II - WHO IS AN INSURED
  81  HOW MUCH WE PAY
  74  SUPPLEMENTARY PAYMENTS - COVERAGES A
  64  SECTION III - LIMITS OF INSURANCE
```

This is the model not obeying rule 9a, and it is the same thing the authority
gate failed to catch (§22) - two independent filters, both blind to the same
content. It is not a correctness disaster (those entries are verified verbatim,
so nothing is fabricated) but it is:
  - ~29% of the index budget spent on text that cannot fill a form field
  - ~29% of the 15-minute runtime
  - real noise in Stage A's prompt, competing with declarations values

**681 entries have an empty label** (12%). Those are the captionless values §13
deliberately started keeping - most are legitimate, but at 12% it is worth
sampling before assuming.

**`Account Number 0482854` arrives with `policy_number: "0482854"`** in the raw
copy - the account number keyed as a contract. `_canonicalise_dec_entry_keys`
has a guard for exactly this and runs after verification; confirm it fired on
the merged copy before treating it as a defect.

**Runtime: ~15 minutes** for the index pass (23:33 -> 23:48), 39 calls, cold
cache. Every call HTTP 200, no 429 observed - the Round 4 backoff was not even
exercised on this run.

## 37. Nothing changed in Round 6

Analysis only. The wording-page question is a decision (tighten rule 9a? fix the
authority signal? accept the noise?) and the owner's standing instruction -
*"Whole document uploaded by user is important"* - has to shape it. Recording
policy wording is not the same as reading the whole document, but that
distinction is the owner's to draw.

---
---

# ROUND 7 - the index is an index again

**Owner: "I filled the form and got no major changes"** and **"18-20 minutes is
too much."** One cause, measured.

## 38. Why the form did not change

```
original document : 699,844 chars
rendered index    : 619,451 chars  =  89% of the document
Stage A calls     : 8   (the design is 1)
```

`_render_dec_index`'s own docstring sets the target at ~3% of the document. At
89% the index is not a summary, it is the policy rewritten as JSON. LLM call 2
gained nothing over walking the raw document, and the co-visibility the whole
Stage A design exists for was spread across eight calls. Identical input,
identical form.

## 39. Where the bulk was

By character count, on the live 6,687-entry run:

| value_type | entries | chars | share | fills a box? |
|---|---|---|---|---|
| **text** | 5,780 | 478,564 | **93%** | no - prose |
| code | 319 | 8,446 | 2% | yes |
| money | 210 | 8,940 | 2% | yes |
| name / date / status / address / number / phone / percent | 378 | 21,742 | 3% | yes |

93% prose - definitions, exclusions, WHO IS AN INSURED. Rule 9a of the index
prompt already forbids recording it; the model does it anyway. **So the guard
belongs in code, where it cannot be ignored.**

## 40. The filter

`_dec_entry_is_indexable`, applied in `_verify_dec_entries` after the verbatim
gate:

- a **fillable `value_type`** (money, date, percent, number, code, phone,
  address, name, status) is kept outright
- **any** entry whose `section` or `path` names a declarations or schedule page
  is kept - that is where a prose classification legitimately lives
- everything else is dropped, and counted in the `dec_entries VERIFIED` log line
  as `dropped_prose`

**BACKWARD-SAFE BY CONSTRUCTION:** an entry with no `value_type` predates this
prompt, so there is no basis to judge it and it is KEPT. Re-running an old
session cannot gut its index. Kill switch `DEC_INDEX_PROSE_FILTER=0`.

**An earlier variant was measured and rejected**: fillable types ONLY gave 6% of
the document but dropped `"Contractors - Executive Supervisors"`, a real
classification ACORD 126 asks for.

## 41. Measured on the live 6,687-entry index

```
raw from the model : 6687
into the index     : 1341   (was 5,635)
rendered           : 118,102 chars = 17% of the document   (was 89%)
Stage A calls      : 1      (was 8)
```

Every value that must survive, does - class codes 91580 and 91585 AND their
classification wording, both the GL $1,000,000 and the umbrella $3,000,000
occurrence limits, all four policy numbers, both carrier names, the applicant,
the $10,663.00 package premium, the premises address.

**Facts and flags untouched.** `_EXTRACT_SCHEMA` and `_EXTRACT_PROMPT_PREFIX`
are byte-identical; this change lives entirely in the dec-entry verifier.

## 42. Runtime - what this does and does not fix

It does **not** cut the 18-20 minutes. The filter runs AFTER the model has
already written the prose; it fixes index QUALITY, not generation cost.

The runtime lever is not sending the wording pieces at all, and the pre-call
authority gate cannot currently tell them apart (§22: it scores by line length,
and this PDF has short lines everywhere). The measured replacement signal is
FIGURE DENSITY - a declarations page is thick with money, dates and codes; a
definitions page has almost none - and it can be validated against this run,
because we now know which pieces produced fillable entries.

Deliberately not done in the same change. Fix the form first, measure it, then
spend on speed - otherwise a speed change lands on top of an unverified quality
change and neither can be attributed.

---
---

# ROUND 8 - the dedicated pass is switched OFF. Verdict on the whole arc.

**Owner, after regenerating with the working index: "forms were almost same."**
That settles it.

## 43. The A/B, in numbers

|  | calls | output tokens | result |
|---|---|---|---|
| facts + flags (the whole extraction) | 14 | ~30,000 | the forms you have |
| the dedicated index | 39 | **~593,000** | forms "almost the same" |

**~20x the cost of everything else in extraction, 18-20 minutes per cold
upload, no measurable change to the product.** The pass does not earn it.

## 44. What was restored

- **`dec_page_entries` is back in `_EXTRACT_SCHEMA`**, verbatim from git.
  Verified byte-identical to the pre-2026-08-23 schema. It produces ~250 entries
  as a passenger on a call that is already happening, at no extra cost - which
  is what every deterministic consumer has actually run on for months.
- **`_verify_dec_entries` reverted to its original**, verified identical to git.
  The row/col carry, the section-from-path fallback, the captionless-value
  keeping and the prose filter all existed to serve the 13-key shape; with no
  13-key producer they were untested surface area, so they are gone.
- **`_DEC_INDEX_DEDICATED_PASS` now defaults to 0.** No index calls, no extra
  cost, no 18 minutes.
- **`PROMPT_VERSION` / `SCHEMA_VERSION` -> v14.** The schema is byte-identical to
  v12 again, but the version moves FORWARD: v13 replies (facts and flags with no
  dec entries) are in the cache and reusing "v12" would serve them as current.

## 45. What was deliberately KEPT

- **The 429 backoff (§27).** Not the cause of anything here, but a genuine
  latent defect - 15 seconds of patience against a 60-second window - and it
  helps every caller in the codebase, not just this pass.
- **The label-aware Stage A split (§10).** Only fires when an index is too big
  for one call, which the ~250-entry index never is. It replaced a blind
  character cut that could separate the umbrella's $3,000,000 from the GL's
  $1,000,000. Strictly safer, dormant in practice.
- **The pass itself, disabled not deleted.** Its machinery is measured and
  correct, and ONE configuration was never tried on a form: the FILTERED index
  (1,341 entries, 17% of the document, one Stage A call - §41). The version that
  was A/B'd was the bloated one, 89% of the document across 8 Stage A calls,
  which is the shape least likely to help. `DEC_INDEX_DEDICATED_PASS=1` runs the
  experiment if anyone wants it; nothing calls it otherwise.

## 46. Tests

`3700 passed / 2 failed` - the same two pre-existing unrelated failures
(`test_arq_acord125_missing_only`, `test_normalization`). Six tests were
adjusted, none weakened:
- four machinery tests in `test_dec_index_dedicated_pass.py` now switch the pass
  on explicitly, because the default is a product decision and they test the
  code
- `test_the_prompt_asks_for_one_entry_per_cell` checks both recorders again
- the two captionless-value tests added in Round 2 are removed with the
  behaviour they pinned

## 47. What this arc actually bought

Honestly: **one real bug fixed, and a measurement that settled a design
question.**

- The key-path bug (§31) meant the dedicated pass had discarded 100% of its
  output since the day it shipped. It was dead code that looked alive. Now known.
- The 429 backoff was genuinely broken for every caller.
- And the question "is a rich declarations index worth 20x the extraction cost"
  now has an answer backed by a real form comparison instead of an argument.

The cost was several rounds chasing rate limits, chunk sizes and caps - all
downstream of a defect that only the full pipeline could expose. **The standing
lesson, again: an offline probe proves the FUNCTION, never the SEAM around it.**

---
---

# ROUND 9 - final state, and two findings that outlived the experiment

## 48. Where the code ended up

| | state | verified how |
|---|---|---|
| facts/flags prompt | **byte-identical to the start of this work** | compared against `git show HEAD` |
| `dec_page_entries` in that schema | **restored** | present, ~250 entries per package |
| `_verify_dec_entries` | **reverted to the original** | compared against `git show HEAD` |
| dedicated index pass | **OFF** (`DEC_INDEX_DEDICATED_PASS=0`) | no calls made |
| `PROMPT_VERSION` / `SCHEMA_VERSION` | **v14** | v12 schema, forward-moving version |
| extraction cost per run | **unchanged from before this work** | 14 calls, ~30,000 output tokens |

Suite: **3700 passed / 2 failed** - the two pre-existing unrelated failures.

## 49. Finding kept: the ARQ re-stamp reads facts after the purge

The purge block in `form_routes.py` justifies deleting `dec_page_entries` with:

> *"Everything AFTER generation - download, signature, the ARQ confidence updates -
> reads `generated_forms[...]["mapped"]`, which is already-stamped values, never
> the facts."*

**That claim is false.** `arq_service._restamp_canonical_into_forms` calls
`_deterministic_map(schema_field, facts)` - it reads FACTS, after generation,
after the purge. That path was added in July, before the comment was written.

**Measured blast radius**, every field in all 17 schemas resolved with the index
and again without it, on the client's real session facts:

```
fields checked : 5,852
fields that change when the index is purged : 9
```

| form | field(s) | with index | purged |
|---|---|---|---|
| 125 | `PriorCoverage_{GeneralLiability,Automobile}_PolicyNumberIdentifier_A/B` | `BBC7263 - 26`, `6E7-40-02---26` | `BBC7263`, `6E74002` |
| 127 | 4 vehicle rating fields | `None` | `UNMATCHED` |
| 131 | `UnderlyingPolicy_GeneralLiability_FormEditionDate_A` | `04 13` | `UNMATCHED` |

**No field ever receives a WRONG value.** Four degrade to a shorter printing of
the same policy number (the index is what elects the fuller form); five fall
through to blank, and after generation there is no gap fill to fall through to.
The re-stamp is also surgical - it only touches fields whose canonical key
matches the fact the client just answered - so a client would have to answer a
question about a policy number or a vehicle rating factor for any of the nine to
move at all.

**Verdict: safe, and the purge default stays ON in production.** The comment
should be corrected; the behaviour should not.

## 50. Finding kept: production purges, local does not

`PURGE_DEC_INDEX_AFTER_GENERATION` defaults to **"1"**. The owner's local `.env`
sets `0`. `delete_facts` is genuinely implemented in
`session_repository.upd_processing_session` (it is not a no-op), and it removes
exactly one key from the session row - facts, flags, generated forms, PDFs and
the PER-DOCUMENT entry copies all survive, which is why
`scripts/dump_raw_entries.py` still works on a purged session.

## 51. Product lifecycle, confirmed in code

The owner's rule - *"once forms are generated in a session, we do not go back and
generate more"* - is what the purge is designed around, and the code matches it:
`select-forms-bulk` writes `"generated_forms": results` as a wholesale replace
with `combined_ids = req.form_ids` (no union with a previous selection), and no
product route returns to form selection. After generation, only ARQ answers and
resolved recommendations modify the forms, and they do so **deterministically -
`_deterministic_map`, no LLM.**

## 52. Artifacts left behind

| file | what it is |
|---|---|
| `backend/scripts/dump_raw_entries.py` | raw per-document entries, all keys, no PowerShell encoding trap |
| `backend/scripts/make_v1_c1_tables_pdf.py` | generates `test_data_v1_c1/5_complex_tables.pdf` - 5 complex tables, a TOC, captionless carriers |
| `LLM_CALL1_PROMPT_FACTS_FLAGS.txt` | the live facts/flags prompt, verbatim |
| `LLM_CALL1_PROMPT_DEC_INDEX.txt` | the v3 index prompt, verbatim (dormant) |
| `LLM_CALL1_OVERVIEW.txt` | how call 1 is wired |

## 53. The lesson, stated once

Three rounds were spent on rate limits, chunk sizes and output caps. The actual
defect was a key one level too high in a dict, and **every offline probe passed**
because each one called `_harvest_dec_index` directly and read its return value -
which was always correct. **An offline probe proves the FUNCTION. It says nothing
about the SEAM around it.** The repo's own standing rule already said to write
the gate test from the live data shape; this is what ignoring it costs.
