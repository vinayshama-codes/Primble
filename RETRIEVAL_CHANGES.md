# Gap-Fill Text Selection ("retrieve before you ask")

**Status:** Steps 1 AND 2 shipped 2026-08-12. Step 3 not started.
**Kill switch:** `GAP_FILL_TEXT_SELECTION=0` restores the previous behaviour exactly.
**Owner note:** every decision below is recorded with *why*, so it can be argued
with or reverted without re-deriving the reasoning.

---

## The end goal this serves

1. Values must be **correct**.
2. The form must be filled **more**, not less.
3. LLM cost must stay the same or **go down**.
4. **If a value is on the declarations page, it must reach the form.**

Point 4 is the hard constraint. Everything below is designed around never
violating it, and #2 is the reason this work exists at all.

---

## The measured problem

From the client's own run, 271-page package, ACORD 125 only:

```
raw_text_chars=683601   prompt_chars=724348   chunk 1/1
LLM_SPEND stage=gap_fill in=174664 tokens
gpt_fill: sent=31 filled=14 | sent=40 filled=12 | sent=40 filled=5
          sent=40 filled=10 | sent=8  filled=1
```

* The **entire** 683k-char package is sent in **every** call. The document is
  never chunked - the per-call budget is ~907k chars, so nothing splits below
  that. "We are chunking" was never true in practice.
* The field list is ~7.6k of a ~724k prompt: **~1% of the prompt is the question.**
* **42 of 159 fields filled = 26%.**

The model is not failing to read. It is being asked ~40 unrelated questions
inside a 174k-token haystack, most of which is standard policy wording that
contains a plausible-looking wrong answer to almost every question.

---

## Decision 1 — filter the DOCUMENT, do not retrieve per call

**Rejected:** per-batch retrieval (each call gets its own retrieved passages).

**Why rejected:** OpenAI's automatic prefix cache is the only reason the current
pipeline is affordable - the logs show `cache_pct=98-99%` after the first call.
Per-call text differs per call, so the prefix stops matching and **every call
pays full price**. Measured estimate: ~640k billed tokens today vs ~530k with
naive per-call retrieval. That is a wash on cost and buys only accuracy.

**Chosen:** ONE filtered document, identical across every call in a run.
Caching survives untouched, and the document itself shrinks. Cost falls roughly
in proportion to the document, with no change to call count.

---

## Decision 2 — reuse `_window_authority`, do not write a classifier

`extraction_service._window_authority()` already scores a span
0.0 (prose) → 1.0 (dense tabular) using only line length and figure/date
density. It ships today, it is tested, and
`test_authority_needs_no_insurance_vocabulary` fails the build if it ever
acquires domain keywords.

**Why this matters:** a second classifier would drift from the first. This
codebase already has a name for that failure (C3: "re-estimating what another
function renders"). The thresholds used here are the SAME constants
(`_AUTHORITY_TIER_CUTS[0]`, `_AUTHORITY_WINDOW_CHARS`), not new ones.

**Why it is generic:** the signal is structural, not lexical. A declarations
page is short lines dense with money and dates; a policy form is long wrapped
prose with almost no figures. That holds for any carrier, any client, any
document we have never seen. **Nothing is hardcoded to one client's paperwork.**

---

## Decision 3 — the four guarantees that stop this losing data

This is the part that must never be weakened.

| # | Guarantee | Mechanism |
|---|---|---|
| 1 | Small documents are never filtered | below `MIN_CHARS` (60k) the text is returned unchanged - a short submission is cheap and every part of it may matter |
| 2 | A kept region keeps its neighbours | kept windows are **dilated** by one on each side, so a schedule cut by a window boundary cannot be half-dropped |
| 3 | **Every already-extracted fact stays visible** | after filtering, each scalar fact value is searched for in the kept text; if it is missing, the window containing it is **restored**. Extraction already proved these values are real data |
| 4 | If the signal fails to discriminate, do nothing | if the kept share would be below `MIN_KEEP_RATIO` or above `MAX_KEEP_RATIO`, the original text is returned unchanged |

Guarantee 4 mirrors `_partition_by_shape`, which returns its input unchanged
when every candidate fails - "the last case being the one that guarantees a
value is never lost".

---

## Decision 4 — verification still reads the FULL document

**This is the subtlest and most dangerous part of the change.**

`map_facts_to_form` uses `raw_text` for the evidence gate, `_value_in_raw_text`,
the NAIC guard and the classification-code guard. Those VERIFY what the model
produced.

If verification saw the filtered text, any value grounded in a dropped region
would be wrongly blanked - the change would start deleting correct answers.

So: **only the gap-fill PROMPT is filtered.** Filtering happens inside
`combined_gap_fill`, on the copy handed to the model. Every downstream guard
continues to read the complete document. The two must never be unified.

---

## Decision 5 — a prose-only document must survive

A narrative or supplemental application is prose by construction. Scored on
tabular-ness it would be deleted entirely.

Guarantee 4 covers this: a uniformly-prose document produces a kept share below
the floor, and the filter declines to act. Guarantee 1 covers the common case,
since narratives are small.

---

## Measured impact (offline, zero API cost)

Fixture: a realistic package - 8 declarations pages against 90 blocks of standard
policy wording, mirroring the minority share declarations occupy in the client's
271-page file.

```
realistic_package   in=447,879  out=75,000  kept=16.7%  applied=True
                    declarations values preserved: 71/71
                    tokens/call: 111,969 -> 18,750   (84% less)
```

Position of the declarations page makes no difference - **71/71 preserved** with
the dec page at the very start, the very end, or buried in the middle, down to
3.4% of the document kept.

| | Before | After |
|---|---|---|
| Document per call | 683k chars | filtered, logged per run |
| Input tokens per call | 174k | **~84% less on this mix** |
| LLM calls | unchanged | **unchanged** |
| Prefix caching | 98-99% | unchanged (one document per run) |
| Declarations values lost | - | **zero** |
| Fill rate | 26% | **must go up - that is the test** |

**Cost falls in proportion to the document. Call count does not change.**

**The reduction on YOUR document cannot be predicted from here** - it depends on
the declarations-to-policy-wording ratio of that specific package. The run will
log it (`TEXT_SELECTION ... APPLIED n -> m chars`). A package that is mostly
declarations will correctly be left alone.

### The control that proves the fact-rescue is real

A fact planted only inside dropped prose survives **when the facts are supplied**
and does **not** survive when they are not. Without that second half the first
would pass by luck and guarantee 3 would be untested
(`test_the_rescue_is_what_saves_it_not_luck`).

### Two bugs found in the tests themselves, worth knowing

* An earlier harness asserted "all facts visible" and reported losses on
  documents it had returned **unchanged** - the fixture simply never contained
  those strings. The invariant must be *present in the input ⇒ present in the
  output*, never *present at all*.
* Passing a ~350KB fixture as a `parametrize` value puts it in the pytest test
  id, which is exported to the environment - and Windows caps an environment
  variable at 32,767 chars. Every such case errored before its body ran. Build
  large fixtures lazily and parametrize on the NAME.

---

---

## Decision 6 — the absolute cut FAILED on the real document (2026-08-12, round 2)

First live result:

```
TEXT_SELECTION SKIPPED label=ACORD_125 kept ratio 97.4% outside [2%, 90%]
```

**97.4% kept. The filter did nothing.** Guarantee 4 correctly refused to act, so
no data was lost - but no benefit either, and the prompt stayed at 174k tokens.

**Why.** `_window_authority` is `0.5*figure_density + 0.5*brevity`, and
pdfplumber's native extraction emits SHORT LINES ON EVERY PAGE. `brevity` sat
near 0.86 throughout that document: a policy-form page scored ~0.44, a
declarations page ~0.83 - **both far above the absolute 0.25 cut**. The two page
types were cleanly separated; the constant was simply in the wrong place, and no
constant can know how a given PDF extractor renders lines.

**Fix: take the cut from the document's own distribution** (Otsu's method - the
threshold maximising between-class variance). Parameter-free, so it adapts to
any extractor.

### The danger this creates, and the two gates that stop it

On a document that is ALL declarations, a purely relative cut still finds "a"
split inside the noise and would **delete half the real data**. So a relative cut
must first PROVE the distribution is two-humped:

| Gate | Default | Purpose |
|---|---|---|
| `TEXT_SELECT_MIN_VAR_EXPLAINED` | 0.60 | the split must explain this share of total variance |
| `TEXT_SELECT_MIN_MEAN_GAP` | 0.15 | the two class means must be this far apart |

**Both are required, and the measurement proves why.** An all-declarations
document scores **`var_explained=0.71`** - it PASSES the variance gate. Only
`mean_gap=0.01` stops it being split down the middle. Either gate alone
reintroduces the data loss.

**The adaptive cut may only ever TIGHTEN** (`if _bimodal and _o_cut > _cut`). A
looser Otsu cut would let this change reduce what is dropped on a document that
already worked.

### Measured

```
reproduction (short lines everywhere, as pdfplumber gives us)
  46/46 windows above the absolute cut 0.25          <- the bug, reproduced
  otsu_cut=0.77 var_explained=0.97 mean_gap=0.39 bimodal=True
  APPLIED 137,377 -> 36,000 chars (26.2% kept)   declarations values 14/14 OK

all_declarations       otsu=0.89 var=0.71 gap=0.01 bimodal=False -> untouched
all_prose_short_lines  otsu=0.47 var=0.71 gap=0.01 bimodal=False -> untouched
small_document                                                   -> untouched
long-prose regression                          11-26% kept, 14/14 OK
```

Kill switches: `TEXT_SELECT_ADAPTIVE=0` reverts to the absolute cut;
`GAP_FILL_TEXT_SELECTION=0` reverts the whole feature byte-for-byte.

---

## Decision 7 — Otsu was the wrong tool (2026-08-12, round 3)

Second live result. The adaptive cut FIRED and still kept 96.1%:

```
TEXT_SELECTION DISTRIBUTION windows=228 min=0.00 median=0.39 max=0.70
  otsu_cut=0.34 var_explained=0.61 mean_gap=0.19 bimodal=True
TEXT_SELECTION SKIPPED kept ratio 96.1%
```

**Otsu maximises `w0*w1*(mu0-mu1)^2`, which is dominated by class BALANCE.** On a
271-page policy the declarations pages are ~5% of the document, so the most
"balanced" split is not the one that matters: it separated the ~4% of near-empty
windows (`min=0.00`) from the other 96% and left the real boundary - between the
~0.39 bulk and the ~0.70 declarations tail - untouched.

It also corrected my model of the document. I had estimated dec≈0.83 /
form≈0.44; the truth is dec≈0.70 / bulk≈0.39.

**Replaced with the LARGEST GAP in the sorted scores, searched only among splits
whose kept group is at most half the document.** That is what "separate a
minority top group" actually means, it is immune to class imbalance, and the gap
width is itself the quality measure.

**The variance-explained gate was REMOVED, not just re-tuned.** For a
largest-gap search it is actively wrong: a genuine 5% declarations tail scores
LOW on it by construction, so the gate would reject exactly the split it exists
to find. The single gate is now the gap width.

```
realistic package   gap=0.19 -> separable, 26.2% kept, 14/14 values preserved
all declarations    gap=0.00 -> refused outright
all policy wording  gap=0.01 -> refused outright
long-prose fixture  gap=0.44 but cut 0.22 < 0.25 -> absolute cut wins (only-tighten)
```

The all-declarations case is now refused **decisively** (`gap=0.00`) rather than
narrowly surviving on a second gate.

`_otsu_cut` was renamed `_separation_cut`: a function name that lies is a comment
that lies.

### A fourth bug, caught by a unit test

The search started *strictly* above the median (`lo = n // 2`), which excluded
the boundary of an exactly-50/50 document. Correct bound: the kept group is at
most half, i.e. `lo = ceil(n/2) - 1`. Found because a fixture happened to split
precisely at the median and returned `None`.

### A third test bug worth recording

`test_the_adaptive_cut_only_ever_tightens` first asserted
`cut_kind == "absolute"` on the long-prose fixture. That was an assumption about
that fixture's distribution, not a property of the rule - and it was wrong. The
invariant is *the effective cut is never below the absolute one*; assert the
invariant, never the fixture's incidental outcome.

---

## How to revert

`GAP_FILL_TEXT_SELECTION=0` in the environment. No code change, no redeploy of
logic, no data migration. The filter is one call at the top of
`combined_gap_fill`; deleting that call restores the previous behaviour byte for
byte.

---

## How to tell whether it worked

Grep a run for:

```
TEXT_SELECTION            - what was kept, dropped, and why
TEXT_SELECTION FACT_RESCUE - a fact whose window had to be restored (guarantee 3)
TEXT_SELECTION SKIPPED    - the filter declined to act, with the reason
gpt_fill: ... sent=N filled=M   - the number that must improve
LLM_SPEND stage=gap_fill        - the number that must not get worse
```

**Judge `filled` and correctness together, never `filled` alone.** Removing
fabricated values lowers the fill count and is a win; this change should raise
it again with real ones.

---

## Decision 8 — Step 2 SHIPPED: the footer is the signal that works where density failed (2026-08-12, round 4)

Third live result: even the largest-gap cut declined on the client's package -
`separation gap 0.07` against the 0.15 floor. pdfplumber renders BOTH page kinds
as short figure-bearing lines there, so no density statistic separates them. The
filter skipped, the prompt stayed 174k tokens, the fill rate stayed 26%.

**An ISO standard form declares itself in its own page footer** - `CG 00 01 04
13`, two letters then four 2-digit groups, printed on every page of the form.
That is a positive identification of boilerplate, independent of line rendering.
Implemented as a stage between dilation and the fact rescue:

| Rule | Why |
|---|---|
| Carrier codes (`CA7000A 02-22`) do not match | different shape - and the client's own DEC PAGE prints one as the program code |
| >2 distinct codes in a window = KEPT | that is a FORMS AND ENDORSEMENTS schedule (dec content), not a footer |
| a window ADJACENT to a schedule-like window is never marked | a schedule cut by a window boundary spills 1-2 codes into its neighbour, which otherwise looks exactly like a footer page - caught by a test fixture before shipping |
| runs BEFORE the fact rescue | guarantee 3 stays absolute: an extracted fact on a form page restores its window |
| `_FOOTER_MIN_WINDOWS` (3) and the [2%, 90%] ratio gates still apply | fewer marked windows is noise; the combined result must still discriminate |

Measured on the density-inseparable fixture (both page kinds short-lined and
figure-bearing, gap 0.00): **108,873 -> 3,000 chars (2.8% kept), every dec value
preserved, and with `TEXT_SELECT_FORM_FOOTER=0` the document returns unchanged -
byte-for-byte the old behaviour.**

Kill switch: `TEXT_SELECT_FORM_FOOTER=0` (this stage alone).

---

## Not done yet

* **Step 3** - raise `_FIELD_FILL_BATCH` once the noise is gone. `40` was tuned
  against a 174k-token prompt; it is almost certainly too low for a clean one.
  **Requires the golden set first** - it is an accuracy trade, not a free win.
