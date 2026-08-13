# LLM Call 2 (gap fill): retrieval redesign

**Status:** in progress, started 2026-08-13
**Owner decision:** approved after the measurement below
**Read with:** `improving-ll.md` (cost model), `RETRIEVAL_CHANGES.md` (the earlier,
partially-reverted attempt - read the "Why the earlier attempt failed" section here
before reusing anything from it)

---

## 1. The problem, measured

Measured offline with `py backend/scripts/inspect_gap_fill_prompts.py` against a
realistic 700,261-char package (dec pages + ISO policy wording), zero API cost.

**5 forms (125/126/127/140/25):**

```
43 calls · 30,735,514 input chars · ~7,683,878 input tokens
cacheable prefix per call: 177,606 tokens   <- the entire document
the field list:              ~2,500 tokens   <- 1.4% of the prompt
```

**3 forms (125/126/127):** 33 calls, 5,883,061 tokens, 834 union fields.

The document is never split. `_raw_budget` allows **917,000 chars** of raw text per
call; the document is 700,261. One chunk. Every call carries all 271 pages and asks
40 unrelated questions about them.

### The decisive comparison

Both stages read the same document with the same model:

| | document per call | 700k doc splits into | outcome |
|---|---|---|---|
| **LLM call 1** (`extraction_service`) | **14,000 tokens** | 13 chunks | works |
| **LLM call 2** (`pdf_service` gap fill) | **175,000 tokens** | 1 chunk | ~26% fill |

Call 2 sends **12.5x more document per call** than call 1's own limit.

`extraction_service._effective_chunk_size` states the principle explicitly:

> quality - how much document the model still reads carefully per call.
> `EXTRACTION_DOC_TOKENS_PER_CALL` (14,000 tok = 56,000 chars). **This is the one
> that binds.** ... Capacity is ~23x larger than quality here. That gap is not waste
> to be reclaimed - it is the measured difference between a stage that works and one
> that invents field names.

Call 2's budget is derived from **capacity** (what the window can hold), not from
**quality** (what the model can read). It reclaimed exactly the gap that comment
warns about. This is the root cause; everything below follows from it.

### Contributing factors, also measured

* **The haystack is adversarial.** In a realistic package, `general aggregate limit`
  appears 459x and only 12 of those carry a number (2.6%). `limited liability
  company` appears 447x and **zero** carry a value - it is boilerplate in *Who Is An
  Insured*, and it sits directly opposite an ACORD entity checkbox. Nothing in the
  prompt distinguishes a declarations page from a policy form; both arrive labelled
  `RAW DOCUMENT TEXT`.
* **Field identity is thin.** **4,014 of 5,852 ACORD fields (69%) have a tooltip that
  is not unique.** One tooltip is shared by 60 fields. The model gets a machine name
  plus a tooltip and, 69% of the time, that tooltip does not separate the field from
  at least one other.
* **Batches are topically incoherent.** `_pack_field_batches` bin-packs in dictionary
  order, so one call carries a VIN, a GL aggregate limit, a producer phone and a roof
  year - four unrelated retrieval problems in one call over 271 pages.
* **No retrieval infrastructure exists.** Grepped the backend for embeddings, BM25,
  TF-IDF, FAISS, vector stores, cosine similarity: zero hits outside `venv`. The only
  text filter (`services/text_selection.py`) is **default OFF in production** and
  enabled only by `tests/conftest.py`.
* **`_split_raw_text(active_fields)` uses the fields only to compute a byte budget,
  never to choose text.** That is the bug in one line (`pdf_service.py:6937`).

### Why nobody caught it

The offline inspector reports **PASS** on the run above. It measures prefix stability
and cost, and by those measures the pipeline is excellent - $0.99 against $5.90
uncached. **Nothing in the test suite measures whether the right value landed in the
right box.** The optimisation loop has been running against a metric that cannot see
the problem. Hence step 0 below.

---

## 2. Why the earlier attempt failed (`text_selection.py`)

It **deleted text globally** before the model saw it. One deletion, every field pays:
a window whose values extraction never captured has no anchor, gets dropped, and the
fields only call 2 could fill lose their source text. Coverage dropped on a live run
and the owner correctly set it default-OFF.

**The conclusion drawn was "send everything." The correct conclusion was "don't
delete - rank and route per field."** That distinction is the entire redesign:

> **Ranking decides the ORDER chunks are tried. It never decides WHICH chunks are
> tried.** A chunk that ranks last for one field group still gets read by that group
> if the group still has blanks, and is read by whichever other group ranks it first.
> Nothing is ever removed from the corpus.

---

## 3. The design

A grid. Rows = document chunks. Columns = field groups. Each fired cell = one call.

```
                 FIELD GROUPS ->
              Vehicle  Driver  GL-Limits  Property  NamedInsured
  chunk 1  [    .        .         X         .          X      ]  dec page
  chunk 2  [    X        X         .         .          .      ]  auto schedule
  chunk 3  [    .        .         .         X          .      ]  property / COPE
  chunk 4  [    .        .         .         .          .      ]  CGL wording
  ...                                                              (13 chunks)
```

Today: one row 12.5x too tall, 43 columns. Full sweep: 13 x 33 = ~430 calls, correct
but slow. The design fires the promising cells first and **walks the rest only when a
field is still blank**.

### The escalation ladder (this is the coverage guarantee)

For each field group:

```
for chunk in chunks_ranked_for_this_group:      # best first
    if no fields left blank: stop
    send (chunk, still-blank fields)
```

Termination: **every field is answered, or it has seen all 13 chunks.** There is no
cutoff at 3. Three is where most fields stop, not where the loop stops.

So: *does every field still see the whole document?* **Yes - if it needs to.** The
change is portion size and order, not coverage.

### Two invariants, asserted, not hoped

* **I1 - every field is asked.** Every field belongs to exactly one group, and its
  group walks chunks until the field is answered or the chunks are exhausted.
* **I2 - every chunk is read.** Early-stopping means a chunk can go unsent if every
  group answered before reaching it. After all groups finish, any chunk that was
  never sent is swept with the fields still blank (`_sweep_unread_chunks`). Enforced
  dynamically because the walk is answer-dependent and cannot be known statically.

### Cost envelope - ESTIMATED BEFORE BUILDING (kept for the record; it was wrong)

```
today                33 calls x 175k tok  =  5.88M tokens   $0.81   (3 forms)
ranking works       ~99 calls x  18k tok  =  1.80M tokens   cheaper
ranking useless    ~430 calls x  18k tok  =  7.90M tokens   ~= today's price
```

**This estimate did not survive contact with the implementation. See §4a.**

---

## 3a. MEASURED AFTER BUILDING - the cost estimate above was wrong

Measured on the same 700,261-char package, 5 forms, with a recording client that
answers a controlled fraction of the fields it is asked. Real runs sit somewhere in
the middle of this table, and pinning down where is exactly what §5 exists for.

```
DEFAULT - full coverage preserved (see D10)
  answer rate   0% | calls  650 | tokens 10.92M | $3.44
  answer rate  30% | calls  589 | tokens  9.75M | $2.97
  answer rate  60% | calls  522 | tokens  8.79M | $2.70
  answer rate  85% | calls  497 | tokens  8.46M | $2.62

GAP_FILL_ROUTED_EARLY_STOP=1 - opt-in, trades the coverage guarantee for cost
  answer rate  30% | calls  491 | tokens  8.16M | $2.51
  answer rate  60% | calls  334 | tokens  5.61M | $1.74
  answer rate  85% | calls  282 | tokens  4.77M | $1.49
                     -------------------------------------
  BEFORE (today)   |       43   |         7.68M | $0.99
```

**The predicted "~130 calls, worst case equals today's price" was wrong on both
counts.** Calls land at 283-650, not ~130, and cost is 1.5x-3.5x today rather than
flat. Two errors:

1. **Chunks-per-group was estimated at ~3. It is not bounded.** A group walks until
   its fields are answered; a group whose fields the document genuinely does not
   contain walks all 13. The floor is `groups x chunks`, not `groups x 3`.
2. **The first cut of D4 gave every family its own batch**, making the FAMILY COUNT
   the floor on the call count - 25-56 families x 13 chunks = **897 calls**. Raising
   the field batch 40 -> 160 barely helped (897 -> 611): a 9-field family is one
   batch at any cap. Fixed by packing families contiguously and flushing only for a
   family big enough to fill calls of its own (>= half a batch) - Vehicle (220) and
   Driver (130) stay pure, Producer (9) shares. **897 -> 650 at the floor,
   327 -> 283 at an 85% answer rate.**

**Caveat, because the dollar figure is soft.** Cross-call prefix caching now depends
on how OpenAI matches 13 distinct `[system + facts + chunk]` prefixes instead of
one. The offline inspector models a single global prefix and reports the pessimistic
bound ($12.59); the table above models per-chunk prefix groups and reports the
optimistic one, on a synthetically repetitive fixture that flatters it further.
**The truth is between $1.49 and $12.59 and will not be known until a real run. The
call counts are solid; the dollars are not.**

**The trade is therefore explicit, and it is the owner's to make:** a 12.5x smaller
haystack per call, for 7-15x the calls and probably 1.5-3.5x the spend. Worth it
only if fill quality actually improves - which is unmeasurable until §5 exists.
**Do not tune any knob in §6 before the harness is built.** That is the mistake this
entire document is about.

---

## 3b. THE BILL ARRIVED, AND THE MODEL ABOVE UNDERSTATED IT (2026-08-13)

The owner ran ONE form and paid **$3+**, against **$1.50 for five forms** before this
work. Both §3a tables are per-call-count correct and per-dollar wrong, for one reason:

**they modelled 700 output tokens per call.** At these call counts output is the
dominant term - it is billed at 6x input - and 700 was roughly 4x low. Re-modelled at
2,500/call the numbers reconcile with what the owner actually paid, and the shape of
the problem inverts:

> **Input cost is nearly FLAT across the whole chunking dial.** One 700k blob or 13
> 56k slices, a batch reads the same bytes either way. What the quality cap multiplied
> was ROUND TRIPS: 13 -> 135 for a single form. The lever is call count. Nothing else.

Measured, ACORD 125 alone, 716,342-char package, 85% answer rate:

```
 tok/call  chunks   walk   calls
   14,000      13   full    135     <- after D1/D10, what the owner paid for
   14,000      13  early     57
   28,000       7   full      75
   60,000       3   full      36
  250,000       1   full      13     <- before any of this work
```

`GAP_FILL_ROUTED_EARLY_STOP=1` is the cheap row and it is still the wrong answer: it
takes the FIRST-ranked answer, and on this exact package that is the $3,000,000
umbrella limit beating the $1,000,000 GL limit. It makes C23 worse, on the document
that produced C23.

### The fix that is not a knob: Stage A (D11)

```
config                                   calls   stageA   stageB    modelled
before all this work (1 chunk)              13        -       13       $0.58
today: quality cap, no index               135        -      135       $1.84
index ON, 14k/chunk                         80       10       70       $1.14
index ON, 28k/chunk                         49       10       39       $0.76
index ON, 40k/chunk                         40       10       30       $0.75
```

**The index and the chunk-size dial compose.** 135 -> 49 calls, a 64% cut, with the
quality cap intact. Stage A itself is 10 small calls; the saving is that 70% of the
field list stops being a passenger on a 13-chunk walk, and the survivors RE-PACK into
2 batches instead of 10.

**UPDATE, same day: the owner took the decision and the default IS now 28,000.** The
paragraph that stood here said 14,000 stays because doubling it is a quality decision
with no measurement behind it. That was the right thing to say and it is still the risk;
what changed is who is carrying it. Recorded honestly rather than rewritten:

* **It broke a test, and that test was the D1 fix.**
  `test_call2_document_budget_matches_call_1_quality_budget` asserted *"call 2 must not
  be handed more document than call 1 will"*. It was not deleted. It was reformulated as
  `test_call2_document_budget_stays_a_small_multiple_of_call_1` against a named
  `_CALL2_BUDGET_RATIO_MAX = 2`, because the defect D1 actually fixed was call 2 sizing
  itself from the CONTEXT WINDOW - 917,000 chars, **16x** call 1, one chunk for 271
  pages, 26% fill. A small multiple is a dial; escaping to capacity is a different
  pipeline. A second test pins that 917,000 can never return.
* **What moves next needs evidence, and it is the RATIO, not the token count.** Turning
  the tokens inside a 2x bound is a cost/quality dial the owner may turn. Raising the
  bound is a claim about the model.
* **Still env-overridable.** `GAP_FILL_DOC_TOKENS_PER_CALL=14000` reverts without a
  deploy, and nothing needs to be in any `.env` for the shipped value to apply.

### Guards audited for harshness while doing this

Asked for explicitly. Three findings, one acted on:

1. **`_DEC_ENTRY_MAX = 500` and "at most 80 entries" per chunk - TOO HARSH, raised.**
   The real package prints 30 dec pages at ~25 pairs each, so the recorder was
   discarding a third of the index it now feeds. 500 -> 1200, 80 -> 150. Sized so the
   index still fits ONE call (`test_a_full_index_fits_in_one_call`).
2. **Family flush costs 14 of 80 calls (18%) - MEASURED, DECLINED.** After Stage A the
   survivors are scattered thinly across families, and `_FAMILY_FLUSH` gives a 3-field
   family its own batch, i.e. its own 13-chunk walk. Turning family grouping off
   recovers 80 -> 66. It was not turned off: D4 is a measured quality decision and 18%
   is not worth reversing it blind. Named here so it is a known cost, not a mystery.
3. **`_verify_dec_entries`'s verbatim gate - CHECKED, NOT LOOSENED.** It is the only
   thing standing between a hallucinated dec entry and a prompt that now presents the
   index as AUTHORITATIVE. `section` was added under the same rule rather than exempted.

---

## 4. Decisions taken, and why

### D1 - Call 2's document budget derives from quality, not capacity
`_GAP_FILL_DOC_TOKENS_PER_CALL = 14000` (56,000 chars), the same constant and the
same reasoning as call 1. Not a new number, not a tuned one: the number the codebase
already proved works, applied to the stage that was not using it.
*Kill switch:* `GAP_FILL_DOC_TOKENS_PER_CALL`. Setting it high restores the old
single-chunk behaviour exactly.

### D2 - Ranking is deterministic. No embeddings, no vector DB, no new dependency
IDF-weighted token overlap between a field group's vocabulary (its field names,
CamelCase-split, plus its tooltips) and each chunk. An LLM ranker would add a call per
group to save a call per group. An embedding index adds a dependency, a build step and
a failure mode to a pipeline that already has enough. Roughly 200 lines, testable
offline, zero API cost.

### D3 - The strongest ranking signal is free: locate call 1's facts in the chunks
Call 1 already reads all 13 chunks and returns facts. Deterministic string search for
each extracted fact **value** tells us which chunk it was printed in - evidence from
having read the page, not a keyword guess. "Chunk 7 holds the vehicle schedule
because 14 VINs from `auto_vin_schedule` are in it" beats any lexical score.
We were already paying for this and discarding the location.
*Kill switch:* `GAP_FILL_ROUTE_BY_FACTS=0`.

### D4 - Field groups partition by family, derived from the field name
The leading underscore segment IS the family. Measured on the real 125+126+127 union:
834 fields, **25 families**, no new data and no hand-labelling.
```
Vehicle 220 · Driver 130 · GeneralLiabilityLineOfBusiness 71 · AdditionalInterest 60
NamedInsured 56 · GeneralLiability 55 · CommercialPolicy 54 · Policy 43 · ...
```
Family becomes the OUTER partition of `_pack_field_batches`. The existing
table-bucket and slot-group atomicity (C19/C29) is unchanged and still applies inside
a family. A group is then one topic, so the model performs one search rather than 40.
*Kill switch:* `FIELD_BATCH_GROUP_BY_FAMILY=0`.

**REVISED after measurement (see §3a).** "One batch per family" was too strong and
made the family count the floor on the call count (897 calls). Families are now laid
out CONTIGUOUSLY and packed continuously, flushing only when the next family is at
least half a batch. Big families keep pure calls; small ones share. A table bucket's
family is the BUCKET prefix, not its first column's - `AdditionalInterest`'s schedule
legitimately contains `CityName_*`, `PostalCode_*`, `StateOrProvinceCode_*`, and
filing it under `CityName` would scatter related tables apart.

### D9 - The compliance pass had the SAME root-cause bug, in its own budget
Found by `test_a_large_document_actually_splits`, not by reading: the dedicated
Yes/No pass computes its document budget independently of `_raw_budget`, so capping
the general fill left compliance still shipping the entire 700k package in one call.
It now takes the same quality cap. This matters at least as much as the general
fill - these are the underwriting disclosure questions, and answering one from
silence buried in 175k tokens is precisely how the false-"N" flood happens.

**Worth internalising: the bug was in the second copy of a budget expression.** The
test that caught it asserts on what the model was actually SENT, not on either
budget expression. Assertions about inputs to the model are the only ones that
cannot be fooled by a second implementation nobody remembered.

### D10 - REVERSED: routing reorders the walk, it does NOT shorten it
The first cut made routing imply early-stopping (walk ranked chunks, stop once the
batch has no blanks). That is where most of the saving lives - 650 -> 283 calls at
an 85% answer rate. It also failed
`test_full_document_coverage.py::test_an_answering_model_still_gets_the_whole_document`,
the standing guard that every word of the document reaches the model **even when the
model answers**, which exists because production was previously measured dropping
46% of a document in exactly that way.

**The guarantee wins; cost is what gives.** Rescan semantics are therefore unchanged
from before this work, and full coverage is the default. Ranking still earns its
place with rescan on - the best-evidenced chunk is seen FIRST, which decides
first-answer-wins in the compliance pass and orders the votes the general fill
resolves - it simply may not buy speed with coverage.

`GAP_FILL_ROUTED_EARLY_STOP=1` opts into the cheaper, lossier walk for anyone who
later decides the trade is worth it. It is off until the harness can price it in
quality, not just dollars.

**This is the second time in this document that a cost optimisation had to be
reverted because it quietly weakened a coverage guarantee** (the first was
`text_selection.py`, §2). That is the pattern to watch for in this area: the
cheapest thing to do is always to read less, and the whole failure mode of this
pipeline is reading the wrong thing.

### D5 - Ranked order supersedes document order; early stop is re-enabled
`_run_field_batch` already had the right loop shape (iterate chunks, stop when all
fields are answered). Two things blocked it: the document never split, and
`GAP_FILL_FULL_RESCAN=auto` forces a full rescan whenever it does. With **ranked**
order, first-answer-wins is materially safer than it was in document order, because
the first chunk tried is the best-evidenced one rather than page 1.
`GAP_FILL_FULL_RESCAN=1` still forces the full sweep for anyone who wants it, and I2
keeps the coverage guarantee either way.

### D6 - Chunking reuses call 1's chunker, not call 2's
`extraction_service._chunk_by_sections` cuts on section boundaries, carries an
overlap tail, preserves char offsets, and is covered by `_verify_coverage`, which
raises on any gap. Call 2's `_split_text_on_boundaries` is a simpler second
implementation of the same idea. One chunker means the two stages cannot drift, and
means the losslessness proof already written applies to both.
*Fallback:* if the import fails, call 2 falls back to its own splitter.

### D7 - Verification still runs against the COMPLETE document
Unchanged from the previous design and load-bearing. The evidence gate,
`_value_in_raw_text`, the NAIC and classification guards all verify against the whole
`raw_text`, never the chunk the answer came from. Pointing verification at a chunk
would blank any answer whose supporting sentence sits in a different chunk.

### D8 - Nothing about the guards, the evidence gate or the compliance pass changes yet
They exist because the model was guessing. If this works, several become
unnecessary - but removing a guard on the same day the retrieval changes makes both
unmeasurable. Retire them later, one at a time, against the harness.

### D11 - Stage A: ask the declarations index before asking the document (2026-08-13)

**The owner's design, and it was the right one.** Build a structured record of the
declarations pages once, fill from that first, and send only what is left to the full
document. Half of it was already in the repo and fenced off.

**What existed.** `dec_page_entries` (C50, 2026-08-12): LLM call 1 already records
every `label : value : owner` printed on a declarations or schedule page, and
`_verify_dec_entries` discards anything not literally present in the uploaded text.
Its consumers were deterministic only, and `pdf_service._GAP_FILL_FACTS_EXCLUDE` plus
`test_call2_prompt_is_byte_identical_with_dec_entries` existed specifically to keep it
out of LLM call 2 - a constraint the owner set at the time and has now lifted
explicitly. That test is rewritten, not deleted: it now proves the KILL SWITCH.

**What was added.**
- `section` on each entry: the coverage-part heading printed on the page the value
  came from, verified verbatim exactly like label and value. **This is the C23 fix as
  structure rather than heuristic.** The umbrella's $3,000,000 and the GL's $1,000,000
  are sixty-two pages apart under the identical label "Each Occurrence Limit"; in the
  index they sit under different headings, in ONE call, co-visible. A 13-chunk walk
  sees them several calls apart and settles it by majority vote, which is how the
  wrong one wins.
- `_render_dec_index` / `_dec_index_chunks`: the entries grouped by section as prompt
  text, ~3% of the package's size.
- Stage A in `_fill_unmatched_with_gpt`: the whole field list against the index, then
  the survivors RE-PACKED and walked against the raw document exactly as before.

**Three things this deliberately does NOT do.**

1. **The index never replaces the document.** Every field it fails to answer walks all
   13 chunks, unchanged. Pinned by
   `test_a_field_the_index_cannot_answer_still_sees_every_chunk`, which asserts the
   fixture actually splits before asserting coverage - the C25 anti-vacuous rule.
2. **The index does not enter the facts block.** That block is labelled "unverified
   hints" and is part of the cached prefix; 1,200 verified entries there would both
   mislabel document content and add ~80k chars to every call in the run. It gets its
   own section, in the raw document's position, so both stages still share the
   `[system + form label + facts]` prefix.
3. **The compliance pass is untouched.** Yes/No disclosure questions are answered from
   policy wording and endorsements - precisely what the recorder is instructed never to
   record - so an index pass there could only ever return nothing.

**The one real trade, stated plainly.** A field answered from the index no longer walks
the document, so a later endorsement cannot supersede its value. That is defensible
here and only here: an endorsement that CHANGES a declarations figure prints its own
schedule, a schedule page is recorded, so the superseding value is in the index too,
under its own heading, next to the value it supersedes. Co-visible beats sequential.

**The index must never split.** Splitting puts two conflicting values back in separate
calls and re-creates C23. `_DEC_INDEX_BUDGET_MULT` is sized so a maximum-size index
(`_DEC_ENTRY_MAX` entries) fits one call, and `test_a_full_index_fits_in_one_call`
fails the build if anyone raises the entry cap without raising the budget. Splitting
survives only as a bounded degradation for a pathological package, and is logged loudly.

**Fail-open at every layer.** No entries, unusable entries, an exception in the
renderer, or `GAP_FILL_DEC_INDEX=0` all land on the pre-2026-08-13 pipeline, which is
a complete pipeline. Measured: 135 -> 80 calls at the current chunk size, 135 -> 49 at
28k tokens/chunk. See §3b.

### D12 - The index earns its keep twice: as evidence, and as a coverage report (2026-08-13)

Two things became possible only because the index exists, and both shipped the day after it.

**As EVIDENCE.** The 2026-08-13 form put the producer's phone in the FAX box and the total
premium in the DEPOSIT box - two boxes with no source in 271 pages. The obvious guard (same
parent, different leaf, equal value) was written, swept against all 17 schemas, and thrown
away: 149 of 528 parents carry more than one amount/date leaf, and a $1M/$1M GL policy makes
`EachOccurrenceLimitAmount` and `AggregateLimitAmount` legitimately equal. That rule deletes
real limits.

The index settles it without vocabulary: **a value the declarations print under exactly ONE
label is one fact, and cannot be the answer to two differently-named boxes.** A $1,000,000
printed under both "Each Occurrence Limit" and "Personal & Advertising Injury Limit" is two
facts that agree, and both stamps stand. `_second_claim_on_a_single_printed_value`.

**As a COVERAGE REPORT.** Owner's question: *"what about the data that was present in the
declaration page and it didn't get stamped on the form".* Before the index there was no way
to answer it except by reading the PDF next to the package by eye. Now it is a subtraction -
`dec_index_coverage(entries, stamped_values)` - grouped by section, because "the GL SCHEDULE
page contributed 4 of its 31 values" is actionable and "440 unused" is not.

**It is a report and must stay one.** A dec page prints plenty no ACORD field asks for
(audit basis, program code, servicing contacts), and an ACORD 125 legitimately ignores what
an ACORD 127 wants. The number is not a defect count. A section with ZERO consumed values is
the signal.

---

## 5. Step 0, which is not optional

`backend/scripts/score_gap_fill.py` + a ground-truth fixture. Without a correctness
number, none of the above is verifiable and this document is an opinion. Built first.

---

## 6. Knobs

| env var | default | effect |
|---|---|---|
| `GAP_FILL_DOC_TOKENS_PER_CALL` | `28000` | Document tokens per call 2 request. **Was 14000 until 2026-08-13** - raised by owner decision for cost (13 chunks -> 7, 80 calls -> 49). Bounded by `_CALL2_BUDGET_RATIO_MAX`; raise high enough and the document stops splitting, which is the kill switch. |
| `FIELD_BATCH_GROUP_BY_FAMILY` | `1` | `0` reverts to dictionary-order bin packing (D4). |
| `GAP_FILL_CHUNK_ROUTING` | `1` | `0` = document order, no ranking. Coverage is unaffected either way. |
| `GAP_FILL_ROUTE_BY_FACTS` | `1` | `0` drops the fact-location signal, keeps lexical (D3). |
| `GAP_FILL_SWEEP_UNREAD` | `1` | `0` disables the I2 tripwire. Do not set in production. |
| `GAP_FILL_ROUTED_EARLY_STOP` | `0` | `1` stops a batch's walk once its fields are answered. The main cost lever, and it trades the full-coverage guarantee (D10). |
| `GAP_FILL_FULL_RESCAN` | `auto` | Unchanged. `1` forces every group to walk every chunk. |
| `GAP_FILL_DEC_INDEX` | `1` | Stage A (D11). `0` restores the exact pre-2026-08-13 pipeline - proved, not assumed, by `test_call2_prompt_is_byte_identical_when_the_index_is_off`. |
| `GAP_FILL_DEC_INDEX_BUDGET_MULT` | `2` | Index size ceiling, as a multiple of one raw chunk. **Not a tuning knob** - sized so the index never splits at `DEC_ENTRY_MAX`. Raise both together or neither. |
| `DEC_ENTRY_MAX` | `1200` | Verified dec entries kept per submission (was 500, which discarded a third of a real package's index). |

**The cheapest single change available today is `GAP_FILL_DOC_TOKENS_PER_CALL=28000`**
- 13 chunks become 7, and with Stage A on that is 135 -> 49 calls. It is a knob rather
than a new default because 14,000 is a measured quality constant (D1), not a guess.

---

## 7. What the full suite caught (all fixed)

A 30-minute suite run reported **22 failed / 2172 passed** against a 2-failure
baseline. Every one of the 20 new failures was worth having:

1. **12 failures in `test_text_selection.py`, plus 2 in `test_dec_page_entries`
   and 2 in `test_yes_polarity_gate` - caused by ONE line in the new test file.**
   `tests/test_call2_retrieval.py` set `os.environ["GAP_FILL_TEXT_SELECTION"]="0"`
   at module scope. `services/text_selection.py` resolves that env var ONCE at
   import, and pytest imports every test module before running any test - so a
   module-level env write in one file silently disabled the filter for the entire
   session and broke 16 tests in three files that had nothing to do with this
   work. Fixed with an autouse fixture that patches the resolved flag per test.
   **Lesson: never write `os.environ` at module scope for a flag that is read at
   import.** The failure appears in unrelated files, which is the worst possible
   place to start debugging.
2. **3 failures in `test_full_document_coverage.py`** - the D10 reversal above.
   These were the system telling the truth: the early-stop optimisation really
   did break the every-word guarantee. Fixed by keeping the guarantee.
3. **1 failure in `test_context_budget_selftune.py`** - a stale FIXTURE, not a
   regression. That test guesses a 400,000-char budget and expects a >120,000-char
   prompt to be rejected so the shrink-and-retry path runs. The quality cap now
   holds every prompt near 70,000, so the overflow never fired and the assertion
   guarding against a vacuous pass caught it. The recovery code is untouched; the
   test now lifts the quality limiter to reach the capacity path it tests.

**The two pre-existing failures** (`test_arq_acord125_missing_only`,
`test_normalization`) are unrelated and unchanged.

**Final clean run: 2,194 passed / 2 failed / 2 skipped in 51.78s** - the same two
pre-existing failures, zero regressions, +55 tests. The earlier run took 29
minutes: the leaked env var above had left text selection disabled, so a dozen
tests were grinding through documents they were built to filter. A 34x suite
slowdown was the loudest symptom of that bug and it was still nearly missed,
because slow is easy to blame on "the new chunking must be expensive."

---

## 8. Open / not done

* Authority labelling per chunk (declarations vs policy form) - planned, not built.
  `_window_authority` already computes the signal.
* Per-value citations (chunk id + quote) for every field, not just Yes/No - planned.
  This is what would let the post-fill guards be retired.
* The ranking's real hit rate is unknown until the harness runs. My estimate is that
  ~3 chunks covers most fields with round 2 mopping up. That is an estimate, and the
  design is built so that being wrong about it costs a cheap extra call rather than a
  wrong value.
