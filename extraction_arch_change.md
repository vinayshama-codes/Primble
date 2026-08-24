# Extraction architecture change - document text extraction step only

**Scope:** the step that turns an uploaded file into the text the LLM reads
(`services/ocr_service.py`, `utils/table_extractor.py`, the assembly in
`services/extraction_pipeline.py` up to the first LLM call). Nothing after that
point - no prompt, no schema, no comparison layer, no rules - is touched.

**Goal:** the text handed to LLM call 1 must be (a) complete - every character
on every page, native or scanned, (b) clean - no `pa$rt4y,850`, (c) structured -
tables arrive as tables, headings stay attached to what sits under them, page
boundaries are visible, and (d) byte-identical to today on every page that was
already extracting correctly.

**Running log - append, never rewrite history.** Every measurement, decision,
rejected alternative and test result goes here. **Each `### ... (Nth pass)` entry records
what was true AT THAT TIME** - earlier entries quote superseded figures (322 tables, then
21, now 15) on purpose, so the progression stays auditable. **§4 Verification is the only
place with current numbers.**

**Where things stand (2026-08-22, after six passes):**

| | |
|---|---|
| Suite | **3698 passed / 2 failed / 2 skipped** - the two failures pre-date this work |
| Identity corpus (49 pages) | exactly **1** page changes, asserted as an exact set |
| Character loss | **zero**, on every page of a 271-page real policy package |
| 271-page package | 699,844 chars, 271 page markers, 15 tables, 172 pages reordered, 16 despaced |
| Status | shipped, uncommitted; extraction is no longer the bottleneck - see §5 |

---

## 1. What was measured before changing anything (2026-08-22)

All numbers from running the real code on the real files, not reasoning.

### 1.1 The pipeline today

```
PDF -> pdfplumber page.extract_text()            (native text layer, chars sorted by x/y)
    -> _extract_page_text_smart()                (scoped two-column reflow, fires on a bare-label fingerprint)
    -> Google Vision for scanned pages / embedded images (flat text; word boxes read for confidence then DISCARDED)
    -> pages joined with "\n"                    (no page markers)
    -> clean_text()                              (whitespace collapse; filters removed 2026-07-30 C24)
    -> extraction_pipeline appends table_extractor output at the END of the document
    -> one flat string -> classify_document -> LLM call 1
```

### 1.2 Defects confirmed

| # | Defect | Evidence | Root cause |
|---|---|---|---|
| D1 | Character interleaving: `pa$rt4y,850`, `premis$e1s2,300` | `test_data_v1_c1/4_loss_run.pdf`; description word ends x=384, PAID column starts x=360 | pdfplumber default sorts CHARACTERS by x0 across the line; two runs overlapping in x are shuffled together |
| D2 | Table extraction never fires | 0 tables on all 4 test PDFs; `page.extract_tables()` default needs ruled lines; insurance schedules are whitespace-aligned | Wrong detector for the document class. Also skipped entirely above 40 pages |
| D3 | Tables (when found) appended at END of document, far from their page | `extraction_pipeline.py:259` | Design |
| D4 | No page boundaries in the text | pages joined with `\n` | Design |
| D5 | Vision word geometry discarded | `_extract_low_conf_from_annotation` walks words for confidence only, returns `annotation["text"]` | Design |
| D6 | Empty table extraction is silent | `logger.info("found 0 tables")` | Design |

### 1.3 Things that were claimed broken and are NOT (from EXTRACTION_BRIEF.md review)

- **The column reflow does not damage clean pages.** On the current dec page:
  raw = reflow = clean_text = 1,700 chars, byte-identical. The brief compared a live
  session that ran on an OLDER generated PDF (sessions <= 18:20 UTC, PDFs regenerated
  18:39 UTC) against the new one. See memory `stale-test-fixture-trap`.
- **`use_text_flow=True` globally is NOT the fix.** Measured: on the two-column
  reflow fixture it makes things WORSE (bare labels 9 -> 12, reflow -> 0); on
  `templates/ACORD_125.pdf` p1 105 lines differ; on ACORD 127 `AGENCY CARRIER NAIC CODE`
  becomes `NAIC CODE CARRIER AGENCY`. Stream order is not reading order on real forms.
  It fixes ONE shape (D1) and breaks another. Must be scoped to the lines that need it.
- **pdfplumber text-strategy tables are garbage.** `COMMERCIAL PA | CKAG | E`, ZIP split
  `802 | 16-3121`, `Orbin Contra`, a 31-row "table" out of application prose. Never use.
- **Relationship loss downstream was NOT observed on this package.** Per-doc facts had
  dec `umbrella_limit=$3M` / cert `umbrella_limit=$1M` / both `gl_each_occurrence=$1M`;
  the dec index carried `line_of_business` per entry. The model recovered `$4,850` from
  `pa$rt4y,850`. But it did NOT recover `BBC7263-26` from `ComBpBaCny7263-26`
  (`coverage_lines[0].policy_number = "7263-26"` in the live session) and the dec index
  had NO `PAID` entries. The scramble costs real data; the model papers over some of it.

### 1.4 Interleave detector threshold - measured

Adjacent-character horizontal overlap ratio (`overlap / min(width)`) on x-sorted lines:

| File | max ratio | lines > 0.3 | lines > 0.5 |
|---|---|---|---|
| 1_dec_page / 2_certificate / 3_application (reportlab) | 0.00 | 0 | 0 |
| ACORD_125 / 127 / 140 templates | 0.00 | 0 | 0 |
| 125 data map (Acrobat) | 0.10 | 0 | 0 |
| SQS spec (Word, kerned) | 0.40 | 7 | **0** |
| **4_loss_run (the defect)** | **1.05** | 2 | **2** |

Kerning never exceeds 0.40. Interleaving sits above 1.0 and alternates for several
characters. Rule: a line is interleaved when **>= 2 adjacent pairs overlap >= 0.5,
or any single pair overlaps >= 0.9**. Zero false positives on the corpus.

---

## 2. Design

> **NOTE (added after the fifth pass).** §2.2 below is the ORIGINAL design, kept as
> written because this file is a running log. It describes three components; five
> shipped. `despaced_words`, `column_bands` / `_horizontal_bands` / `_parallel_region`
> were added in passes 3-5 and are specified in their own change-log entries. §2.2 item 8
> also names the page marker `[Page N of M]`; that was corrected to `[Document page N]`
> before wiring (bug 3). **The pipeline as it actually stands today:**
>
> ```
> PDF -> despaced_words()      rejoin letter-spaced (teletype) lines        [pass 4]
>     -> page_words()          repair character riffling, scoped to the line [pass 1]
>     -> page_text()           + column_bands(): two-column PROSE read down
>                                each column; side-by-side IDENTITY blocks
>                                split; label/value tables never moved    [passes 3+5]
>     -> detect_tables()       header-anchored, per page, prose-gated      [passes 1+2]
>     -> Vision for scanned pages / embedded images, word boxes kept, same
>        detector applied in pixel space                                   [pass 1]
>     -> assembled per page: [Document page N] -> text -> table block ->
>        embedded-image blocks (each with its own table block)             [pass 1]
>     -> clean_text() -> classify_document -> LLM call 1
> ```
>
> Every transform is scoped to a page that shows its own defect; a page showing none
> comes out byte-identical to `pdfplumber.extract_text()`, pinned by
> `test_clean_pages_are_byte_identical_to_pdfplumber` over a 49-page corpus.

### 2.1 Principle

Best-in-class document readers (Claude's PDF path, Document AI, Textract, Docling)
share four things: look at layout BEFORE reading, find tables visually not by ruling
lines, keep structure all the way to the model, keep page/position on every element.
This change moves the text step toward that without changing what the LLM call
receives type-wise (still a string) and without touching any consumer.

### 2.2 Components

**`utils/page_layout.py` (new, pure functions, no service imports).**

1. `page_words(page)` - words for a pdfplumber page/crop with interleaving repaired.
   - Cluster `page.chars` into lines (y tolerance 3 = pdfplumber's default).
   - Flag lines by the 1.4 rule.
   - Unflagged lines -> words from `page.extract_words()` exactly as today.
   - Flagged lines -> words from `page.extract_words(use_text_flow=True)` restricted to
     that line's y-band, then sorted by x0. Stream-order SEGMENTATION fixes the merge;
     x0 SORTING restores reading order. Text flow is never applied to the page as a whole.
   - Returns `(words, repaired_line_count)`. Zero repaired lines == `extract_words()`.
2. `page_text(page)` - `page.extract_text()` when nothing was repaired (byte-identical);
   otherwise the page rebuilt from `page_words`, lines in top order, words joined by one
   space. A test asserts the rebuild equals `extract_text()` on every clean page in the
   corpus, so the rebuild path cannot drift.
3. `detect_tables(words)` - header-anchored, scale-free (thresholds relative to median
   word height so pdfplumber points and Vision pixels both work):
   - Cells = runs of words separated by a gap > 0.75 x median word height.
   - Header = a line with >= 3 cells, no cell ending in `:`.
   - Column assignment by LEFT EDGE: a body cell belongs to the right-most header column
     whose x0 <= cell.x0 + tol. Data overflows to the right; headers do not.
   - Data row = maps to >= 2 columns AND its first cell starts in column 0.
   - Continuation row = first cell starts in a later column -> appended to the previous
     row's cell with `; ` (certificates stack several limits in one cell).
   - Table ends at: a line with a single cell, a line whose first cell ends in `:`
     (`Total Incurred:` is a summary, not a row - structural, no vocabulary), or a line
     that maps to < 2 columns.
   - Accept when >= 2 data rows, or >= 1 data row with >= 4 columns.
   - Section = nearest preceding single-cell line within 3 lines whose letters are
     >= 70% uppercase (`SCHEDULE OF COVERAGE PARTS`, `CLAIM DETAIL`, `COVERAGES`).
4. `render_tables(tables, page_no)` - single-newline block, clean_text-safe:
   ```
   [Table - page 1 - SCHEDULE OF COVERAGE PARTS]
   LINE OF BUSINESS | CARRIER | POLICY NUMBER | PREMIUM | EFF / EXP
   Commercial General Liability | EMC Prop & Cas Co | BBC7263-26 | $6,720 | 07/15/26-07/15/27
   [End table]
   ```
   Every cell is a verbatim join of printed words, so `_verify_dec_entries` still finds
   every label and value literally in the text.

**`services/ocr_service.py` (edits).**

5. `_extract_page_text_smart` uses `page_text` / `page_words` instead of
   `page.extract_text()` / `page.extract_words()`. On clean pages this is byte-identical
   (proved by test). The two-column reflow logic is unchanged.
6. Per-page tables computed in the same pdfplumber pass and emitted INLINE right after
   that page's text, before any embedded-image block. Lines-mode `page.extract_tables()`
   kept as a per-page fallback only where the header-anchored detector found nothing
   (keeps ruled-table capability; still capped at 40 pages, the new detector is not).
7. `_OcrResult.words` (new field, default `[]`) - Vision word boxes carried out of both
   the REST and gRPC annotation parsers. Scanned pages run the same `detect_tables`.
   Existing test fakes construct `_OcrResult` by keyword and are unaffected.
8. Page markers `[Page N of M]` at the top of each page, multi-page documents only
   (single-page text stays byte-identical). Kill switch `OCR_PAGE_MARKERS=0`.

**`services/extraction_pipeline.py` (edits).**

9. Remove the end-of-document table append (tables are now inline per page).
10. Fail loud: after classification, a `loss_run` or `dec_page` with no `[Table` block
    logs WARNING `EXTRACTION_NO_TABLES`. Log only - no user-visible flag, because a
    dec page written entirely as label: value lines is legitimate.

### 2.3 Rejected alternatives

| Alternative | Why not |
|---|---|
| `use_text_flow=True` globally | Breaks ACORD 125/127 and the two-column case (1.3) |
| pdfplumber text-strategy tables | Garbage (1.3) |
| Delete the column reflow | It is correct and tested; the brief's evidence was a stale fixture |
| Send page images to the LLM | Right idea, wrong step - it changes the LLM call, the wrapper is text-only, and cost must be modelled first. Follow-up, not this change |
| Google Document AI / Textract layout API | External service + cost + credentials decision. Follow-up. Note: Textract was replaced by Vision for OCR accuracy; Vision is table-blind |
| Camelot | Disabled by default for memory; unchanged |

### 2.4 Blast radius checked before writing code

Consumers of the extracted string and why each is safe:

- `classify_document` - keyword scoring; markers/pipes are inert.
- `extract_facts_long` / chunkers / `_verify_coverage` - text-agnostic.
- `_harvest_dec_index` + `declarations_authority` - more label/value density on dec pages, never less.
- `_verify_dec_entries` - every cell and every marker-free line is verbatim page text.
- text selection (density / ISO form-footer filter) - operates on windows; markers do not match footer codes.
- `clean_text` - single newlines only (same rule the embedded-image marker already follows).
- stored `docs[].text` - gains table blocks and markers; the `_REEXTRACT_DOC_TYPES` path re-reads it unchanged.
- tests: `test_ocr_column_reflow.py` (page-level, must stay byte-identical), `test_ocr_embedded_images.py` (`in` / `count` assertions, not equality).

---

## 3. Change log

### 2026-08-22 - shipped

**New: `backend/utils/page_layout.py`** (pure functions, no service imports)

| Function | What it does |
|---|---|
| `interleaved_bands(chars)` | Lines whose x-sorted characters collide. Strict same-baseline clustering (1pt) + a vertical-overlap pair test. Rule: >= 2 adjacent pairs overlapping >= 0.5, or one pair >= 0.9. Non-upright glyphs (diagonal watermarks) excluded |
| `page_words(page)` | `page.extract_words()` with flagged lines re-segmented from `extract_words(use_text_flow=True)` restricted to that line's band. `(words, repaired_count)`; 0 == pdfplumber's own words |
| `page_text(page, pw=None)` | `page.extract_text()` unless a line was repaired; then the page rebuilt with pdfplumber's own `cluster_objects` line clustering and single-space join. `pw` accepts a precomputed `page_words` result so the table pass reuses it |
| `detect_tables(words)` | Header-anchored, scale-free. Cells split at gap > 0.75 x median word height OR at a word sitting on a header column anchor (+-0.15h). Body cells assigned by left edge. Continuation rows fold with `; `. Ends at a label:value line (any token in the first gap-cell ends in `:`) or a single-cell line. Accept: >= 2 rows (or 1 row with >= 4 cols), >= 60% of rows truly aligned to >= 2 anchors, and not letter-soup (> 25% single-letter alphabetic tokens) |
| `render_tables(tables, page_no)` | `[Table - page N - SECTION]` / header / rows / `[End table]`, cells joined with ` \| `, single newlines only |
| `vision_words(annotation)` | Word boxes from a Vision REST dict or gRPC proto. Never raises |

Env knobs (all default on / measured values): `PAGE_LAYOUT_DEINTERLEAVE`, `PAGE_LAYOUT_TABLES`,
`PAGE_LAYOUT_CELL_GAP=0.75`, `PAGE_LAYOUT_OVERLAP_PAIR=0.5`, `PAGE_LAYOUT_OVERLAP_HARD=0.9`.

**Edited: `backend/services/ocr_service.py`**

- `_OcrResult.words` (default `[]`) - Vision word boxes out of both `_vision_rest_batch` and
  `_vision_grpc_batch`. Every existing test fake builds `_OcrResult` by keyword; unaffected.
- `_extract_page_text_smart(page, pw=None)` - "default" is now `page_text`; the reflow's
  words, zone words, zone default and before/after slices all come from `page_words` /
  `page_text`, so a zone that is both riffled and column-scrambled is repaired on both axes.
  On a page with no riffle every one of these is byte-identical to the pdfplumber call it
  replaced (test-pinned across the corpus).
- `_pdfplumber_extract_pages_structured(path) -> [(text, table_block)]` - one pass computes
  `page_words` once per page and feeds both text and tables. Lines-mode `page.extract_tables()`
  is the per-page fallback when the header-anchored detector finds nothing (still capped at
  `TABLE_EXTRACT_PAGE_LIMIT=40`; the new detector runs on every page).
  `_pdfplumber_extract_pages` is now a thin wrapper - same signature, same output.
- `extract_text_from_pdf` assembly, per page: `[Document page N]` (multi-page only, only
  when the page has content) -> text -> table block (native, or Vision-box detector on a
  scanned page) -> embedded-image blocks, each followed by its own table block if the
  image's OCR words form one. INFO log of tables emitted per document.
- `_PAGE_MARKER = "[Document page {page}]"` - NOT "Page N of M": `clean_text` strips that
  pattern as page furniture. `OCR_PAGE_MARKERS=0` disables.

**Edited: `backend/services/extraction_pipeline.py`**

- End-of-document table append removed (import, block, and `_format_tables_as_text` body;
  the function is kept as a no-op for any external caller).
- `EXTRACTION_NO_TABLES` WARNING after classification when a `loss_run` / `dec_page` has
  no `[Table - page` block. Log only, never a flag.

**Edited: `backend/utils/table_extractor.py`** - deprecation docstring; module kept importable.

**New: `backend/tests/test_page_layout.py`** (22 tests at first ship; **34 after pass 5**,
all against real files).

### Bugs found and fixed DURING this change (the "keep your eyes open" list)

1. **First cut of the riffle detector fired on 10 of 12 blank ACORD template pages.** Two
   stacked 6pt box labels 5.5pt apart ("TYPE" over "BODY") are bridged into one 3pt-chain
   cluster by the glyphs between them; x-sorted, their characters "collide" at ratio 1.0 on
   different baselines. My earlier measurement (section 1.4) used anchor-to-first clustering
   and missed it. Fix: strict 1pt baseline clustering for detection + a vertical-overlap
   requirement on every pair. Re-measured: 0 bands on all 12 template pages, 2 on the loss run.
2. **First cut of the cell splitter left `$4,850` inside the DESCRIPTION cell** (the
   description overruns INTO the PAID column, so there is no gap) and glued the trailing `-`
   onto `NO COVERAGE`. Fix: a word whose left edge sits on a header anchor starts a cell.
3. **`[Page N of M]` would have been deleted by `clean_text`** before reaching the model.
   Caught by reading `text_cleaner.py` before wiring. Marker reworded.
4. **Blank-form letter soup rendered as tables** (`( C E O a M a B cc IN id E e D nt )` on
   ACORD 25). The soup is pdfplumber's own `extract_words` on stacked 6pt labels and is
   already in today's page text; the table block must not echo it. Fix: single-letter ratio
   gate. ACORD 25: 1 -> 0 tables; ACORD 127: 5 -> 1 (the real driver grid).
5. **A blank 3-page scan would have become 35 chars of markers** and slipped past the
   pipeline's `len(text) < 30` skip. Fix: marker only when the page has content. Test-pinned.
6. **Path A embedded images (a dec page pasted into a text PDF) got OCR text but no table
   pass** in my first wiring. Fixed; table block follows its own image block. Test-pinned.
7. **One new test was order-dependent.** `test_multi_page_markers_only_on_pages_with_content`
   passed alone (22/22) and failed in the full suite: its blank page 2 reached the real
   Vision path, and `tests/test_arq_acord125_missing_only.py` installs a permanent
   `sys.modules` stub of `circuitbreaker` (already documented in
   `test_ocr_embedded_images.py`) that changes how that path fails. Reproduced by running
   the two files together; fixed by stubbing the breaker and the provider the way every
   sibling test does. The marker logic itself was never wrong.

### 2026-08-22 (second pass) - the 271-page package broke the table detector

**Found by the owner running a real 271-page policy package**, not by the suite. My whole
corpus was structured documents (dec pages, certificates, loss runs, blank ACORD forms,
Word tables). A real policy package is ~90% **legal wording laid out in two columns** - a
document class I had never measured. Textbook CHANGE QUALITY BAR failure: the fixture was
easier than reality.

**Measured on the client's package, before the fix:** 322 tables, **149,235 chars = 17.8%
of the document**. Roughly 300 of them were policy wording re-emitted as pipe-separated
rows - a duplicate of text already on the page.

**Why no geometric test can fix it:** two-column policy wording IS a grid. Measured on
page 10, the prose "table" scores **1.00 anchor occupancy and 0.00 cell-count deviation** -
better-formed than the client's own dec-page schedule (0.32-0.73). Anchor occupancy,
cell-count consistency and column count were all measured and all failed to separate.

**What does separate them is the text, not the layout: a record does not begin
mid-sentence.** Two gates, both measured across 40 genuine tables (client package, ACORD
templates, Word tables, the package's real schedules) vs 48 policy-wording blocks:

| Gate | Where | Genuine | Prose | Threshold |
|---|---|---|---|---|
| Header cells starting lowercase | `_is_header` | median 0.00, **max 0.00** | median 0.83 | `> 0.25` rejects |
| Body rows starting lowercase | `_is_running_prose` | median 0.00, max 0.40 | median 0.67 | `> 0.5` rejects |
| Cells ending on `,` `;` or a function word | `_is_running_prose` | median 0.00 | median 0.41 | `> 0.25` **with** row-lowercase `> 0.25` |

The two weaker tests are required TOGETHER because either alone costs a real table - a
wrapped description legitimately ends in a conjunction (pinned by test).

**Result on the 271-page package: 322 -> 21 tables, 17.8% -> 1.8% of the document, 838,754
-> 701,853 chars.** Every genuine table survived, verified per source: client package
1/1/0/1, SQS spec 7, ACORD 125/127/130/140 4/1/6/4, the package's own real schedules 13/13.
Prose pages 48 -> 1.

**No data was lost, proven not asserted.** Stripping the table blocks from both runs and
comparing the page text: **13,804 lines, identical except one word** - `Dy Von Jantin` vs
`Day Von Jantin`, a signature block OCR'd from an embedded image, and both spellings appear
in the run's own low-confidence token list. That is Google Vision's run-to-run variance, not
this change. Every dropped prose block is still present verbatim as page text.

About 7 of the surviving 21 are still prose fragments (~2,500 chars on a 700k document).
Deliberately not chased: additive, negligible, and tightening further starts rejecting real
tables.

Cost on the full package: **38.7 s** for OCR + text + tables over 271 pages.

### 2026-08-22 (third pass) - two-column reading order

**Owner's analysis of the 271-page run.** Verified claim by claim before acting; the
scorecard is at the end of this section.

**The defect (confirmed, and the worst one found so far).** A policy form prints two
columns. Read straight across, page 151 produced:

```
d. Workers' Compensation And Similar Laws  This exclusion does not apply to the extent that
valid "underlying insurance" for the employer's
Any obligation of the insured under a workers'
```

The left column is an EXCLUSION; the right column is the EXCEPTION that reinstates
coverage. Spliced line by line they form sentences that do not exist in the document.
Endorsements are what amend limits and add or remove coverage, so this is meaning
corruption, not cosmetic. **164 of 271 pages.**

**A textbook XY-cut does not work here, measured.** Page 151's widest run of zero ink
coverage inside the text block is **2pt**, and only 28% of lines respect it - a projection
histogram finds no gutter at all. What IS true is that **zero lines straddle x=315**. So
the gutter is scored by **crossings**, not by whitespace.

**Two guards the first cut needed, both found by running the real document:**

1. **Running headers and footers veto the gutter.** Page 12's four full-width lines
   (`AAIS`, `CL 0600 01 15`, `-- PLEASE READ THIS CAREFULLY --`, the endorsement title)
   put crossings at 7.5% and blocked a channel that no body line crosses. The top and
   bottom 10% of the text extent are now excluded from SCORING only - they still end a
   band, so they are never reordered.
2. **A hanging indent strands its own number.** Page 12's right column outdents `2.` and
   `3.` from their paragraphs, leaving a narrow secondary channel. The first fix picked an
   x inside it and emitted `1. The following definitions are added. 2.` with `3.` orphaned.
   The gutter is now the **midpoint of the widest run of minimum-crossing x values**, which
   centres it in the real channel.

**Why only prose bands are reordered - the decisive measurement.** Page 205 carries BOTH
shapes under ONE gutter:

| Lines | Content | Reordering would |
|---|---|---|
| 4-8 | `Named Insured \| Producer`, then two addresses | help (splits the merge) |
| 14-23 | `Each Occurrence Limit \| $1,000,000` | **orphan every amount from its label** |

Identical geometry. The separator is the text, reusing the table gates' signal: prose
continues across lines, a label:value row does not. Measured across the package: **141
prose bands reordered, 8 label/value bands held back** (lowercase-start 0.59-0.82 vs 0.00).

**The `Named Insured | Producer` merge is therefore NOT fixed, deliberately.** Splitting a
label/value row would orphan values on every declarations page in the book. Blank-over-wrong
applies to reading order too. That defect needs a narrower, separately-measured rule.

**Verification**

| Check | Result |
|---|---|
| Page 151 | left column reads as one continuous exclusion, right column follows whole |
| Page 12 | numbered items 1, 2, 3 in order, no orphaned markers |
| Page 205 / page 1 | **0 bands** - untouched, limits and premiums intact |
| Character multiset, every page | **0 mismatches across 271 pages** - reordering never adds or drops a character |
| Identity corpus (49 pages: reflow fixtures, client docs, 6 ACORD templates, Word, Acrobat) | 1 change, the loss-run riffle repair. Everything else byte-identical |
| Tables on the package | 21, unchanged. Test-package table counts unchanged (1/1/0/1, SQS 7) |
| Package totals | 701,853 chars, 271 markers, 21 tables |

**Scorecard on the owner's analysis**

| Claim | Verdict |
|---|---|
| Read-across on two-column forms, ~107 pages | **Right** - measured 164 |
| Page 205 Named Insured merged with Producer | **Right** - reproduced verbatim |
| Strip headers/footers before gutter detection | **Right** - required, page 12 proved it |
| Recursive XY-cut on ink projection | **Wrong for this document** - 2pt of whitespace; crossings work, projection does not |
| "322 fake tables, 18% of the file" | **Stale** - already 21 / 1.8% after the second pass |
| Issue 3 says the merge resolves itself once columns are split | **Wrong** - the limits block shares the same gutter; splitting it blindly destroys page 205 |
| Duplicate prose + `;` injection (Issue 5) | Re-measure: both were artefacts of the 322-table run |
| Page classification / segmentation (Issue 3), section scoping, page images (Issue 5, 7) | Real, but **outside the text-extraction step** - they change document routing and the LLM call. Listed in section 5 |

### 2026-08-22 (fourth pass) - letter-spaced declarations pages

**Found by inspecting the owner's fresh 271-page run, not by any analysis.** Page 85 and
page 3 - EMC's teletype-style auto and inland-marine declarations - arrived as:

```
* 6 E 7 - 4 0 - 0 2---26 *
N A M E D I N S U R E D :   P R O D U C E R :
```

**This is a defect CLAUDE.md already records as having reached a client's ACORD 125**
("the Inland Marine number keyed WITH its OCR spacing, `6 C 7 - 4 0 - 0 2---26`, which
then printed that way on the client's ACORD 125"). It was previously treated as an OCR
artefact. It is not - it is native text, and it is fixable here.

**Root cause, measured.** On those pages the gap between GLYPHS is **6.56pt against a
6.41pt glyph**. On ordinary text in the same document the gap between glyphs is **0.07pt**
and the gap between WORDS is **6.56pt** - the identical figure. pdfplumber splits on
anything over its 3pt tolerance, so it cannot tell letter tracking from a word break.

**Fix (`despaced_words` / `_despace_line`).** The ambiguity only exists per character; per
LINE it disappears, because on a letter-spaced line the small gap is about a full glyph
wide. Detect on `median_gap / median_glyph >= 0.5`, then re-split at gaps wider than
`1.8 x` that tracking - the line's real word breaks (19.5pt and 90.9pt on the measured
line) stand clear of it. Result: `6C7-40-02---26`, `NAMED INSURED: PRODUCER:`.

**Two bugs in my own first cut, both caught by re-measuring rather than by the suite:**

1. **Negative gaps were DROPPED from the sample.** Kerned pairs have a slightly negative
   gap; filtering them left only the wide COLUMN gaps, so an ordinary three-cell table row
   scored a median "tracking" of 14pt and was rebuilt as letter-spaced text. It cost the
   SQS spec 4 of its 7 tables and fired on 158 pages instead of ~20. Fixed by clamping
   negative gaps to zero instead of discarding them.
2. **The replaced-word band padded by `_Y_TOL` and swallowed the neighbouring line**,
   deleting its words with nothing put back: **112 pages of real character loss**. Fixed
   with a tight midpoint-containment test, plus a guard that abandons the rebuild for the
   whole page if it would not replace at least as many words as it produces.

**Verification**

| Check | Result |
|---|---|
| Pages despaced on the package | 20 of 271 (the EMC teletype sections) |
| Character multiset, all 271 pages | **0 mismatches** |
| Identity corpus (now 6 ACORD templates + Word + Acrobat + client docs) | exactly 3 pages change: the loss-run riffle, `(Y / N)` -> `(Y/N)` on ACORD 140 p2, `N / A` -> `N/A` on ACORD 130 p2 |
| Table counts | client package 1/1/0/1, SQS spec 7 - all unchanged |

The identity test is now an EXACT SET of allowed changes (`_EXPECTED_CHANGES`), so it fails
both when a new page starts changing and when a repair silently stops working.

### 2026-08-22 (fifth pass) - the insured/producer merge, and four false positives

Owner's analysis of the fresh run. Verified claim by claim; scorecard at the end.

**Bug 1 - `Named Insured | Producer` merged. FIXED.** The stated cause ("the gutter
fails a 60% page-height test") was not the mechanism - there is no such test - but the
*direction* was right. Measured on page 205: the identity block and the limits table sit
in ONE column band (lines 4-27) under one gutter, so the band as a whole reads as
label/value and nothing moves.

Two mechanisms, both needed:

1. **`_horizontal_bands` - the other half of the XY-cut.** Split at vertical gaps several
   times the page's own line pitch, THEN look for columns inside each band. Page 205 has a
   **60.5pt gap** between `Organization Type: LLC` and `Limits of Insurance` against a
   5-8pt pitch. At the first threshold (2.5x pitch) the 19pt gap under `Named Insured |
   Producer` cut the header off its own address block; **4.0x** is the measured value.
2. **`_parallel_region` - anchored, not a prefix.** Page 1 opens with five single-column
   lines above the identity block, and a plain prefix dragged the account number and
   `Common Declarations` into the middle of the insured's address. The region is anchored
   on the header row carrying a short label in BOTH columns, and ends at the first row
   whose right cell is an amount.

**Five false positives found while building it, each fixed by measurement:**

| Where | What happened | Gate added |
|---|---|---|
| Page 85 | Anchored on box art (`*---*`), splitting `POLICY PERIOD: FROM 07/15/25 TO 07/15/26` | row under the anchor must carry >= 2 alphanumeric words in BOTH columns |
| Page 85 | Coverage/premium schedule reordered - would orphan every premium | `_has_amount` anywhere in a right cell -> label/value, never a block |
| Page 85 | `POLICY PERIOD: ... TO` ends in a function word, so the tail test alone called a boxed header "prose" | prose is now two-tier (`lower > 0.5`, or `lower > 0.25` AND tail), same as the table gate |
| ACORD 125/126/127/130/140 | Blank form label grids split - on a FILLED application that separates a printed label from its box | cell length cap (45 chars) + a postal line required in BOTH columns |
| ACORD 126 p5 | A 4-line fraud paragraph reordered into nonsense | prose bands need >= 8 lines (package median is 38; only 9 of 199 fall under 8) |

**Bug 2 - shredded prose tables. FIXED, 21 -> 15.** The owner's rule ("a real table cell
is never the word *and*") is right and is now a hard reject. Its first cut used the full
`_PROSE_TAIL_WORDS` list and **deleted page 1's entire coverage-and-premium grid** on the
row `8 | Other` - `other` was in the list. `_BARE_CONNECTIVES` is a deliberately narrower
set: an ACORD schedule legitimately prints `Other`, `Any`, `Not` and `This` as whole cells.

**Bug 3 - do not reject headerless forms lists. HEEDED, no change needed.** Pages 4, 87,
144, 145, 207, 208 and 241 are all retained. The warning was against a change I did not
make: the header check is structural (does a cell begin mid-sentence), never a vocabulary
match, so a forms schedule passes on its own shape.

**The `;` injection is fixed.** `Confidential Or Personal; Material Or Information` was a
WRAPPED description, not two values. `; ` is now used only when the continuation carries
an amount - which is the case it was built for (a certificate stacking `Each Occurrence
$1,000,000` over `General Aggregate $2,000,000` in one cell).

**Bug 4 - segmentation. NOT DONE, and out of scope by instruction.** Page classification
changes what gets routed to which LLM call, not how a page's text is read. It stays
follow-up #2 with the forms-list shortcut recorded.

**Also fixed this pass (found by inspection, not in the analysis):** page 241's contents
page was welding `Coverage A -` into `CoverageA-`. Dot leaders are 25 separate
one-character "words", which scored 0.89 on the letter-spacing test. Only ALPHANUMERIC
words are counted now.

**Verification**

| Check | Result |
|---|---|
| Identity corpus (4 fixtures, 3 client docs, 6 ACORD templates, Word, Acrobat - 49 pages) | **exactly 1 change**, the loss-run riffle. `_EXPECTED_CHANGES` is now empty and the test asserts the exact set |
| Pages 1, 85, 205 | `Named Insured` owns its own address; `Producer` owns its own |
| Pages 151, 12 | still reordered correctly; 172 of 271 pages reordered |
| Page 205 limits, page 85 premiums, page 1 grid | untouched, all values paired |
| Character multiset, all 271 pages | **0 mismatches** |
| Tables | 15 (was 21); 0 with a bare function-word cell; every forms list retained |

### 2026-08-22 (sixth pass) - fresh-run verification and the AI-readiness question

No code change. The owner re-ran the 271-page package through the live pipeline and asked
whether the result is workable for the AI layer.

**The run reproduces the offline measurements exactly**: 699,844 chars, 271/271 page
markers, 15 tables, 5 embedded-image blocks. Every defect probe is clean - `pa$rt4y` 0,
`ComBpBaCny` 0, `6 C 7 - 4 0` 0, `N A M E D` 0, `CoverageA-` 0.

**The question that actually decides it - can the model tell which `Each Occurrence` is
which?** Those three figures sit up to 62 pages apart and none of them names its coverage
part on its own line:

| Page | Line | Its page header | Resolves to |
|---|---|---|---|
| 143 | `Each Occurrence Limit (Liability Coverage) $ 3,000,000` | `COMMERCIAL UMBRELLA DECLARATIONS` + `6J7-40-02---26` | Umbrella |
| 148 | `Each Occurrence $ 1,000,000` | `COMMERCIAL UMBRELLA SCHEDULE` (underlying) | Underlying GL |
| 205 | `Each Occurrence Limit $1,000,000` | `General Liability Declarations` + `BBC7263 - 26` | GL |

Every page is now a self-contained unit - its own header, policy number and coverage part
within 27-46 lines - and `[Document page N]` keeps that binding. **This is the property
that makes the umbrella-vs-GL judgement possible from text alone, and it did not exist
before this work.**

**Chunking does not break it.** Extraction chunk = 56,000 chars against a median page of
2,713 chars, so a chunk carries **~20 whole pages**, with 14,285 chars of overlap. A
page's header and its limits stay together.

**The honest remaining limit is volume, not extraction.** 699,844 chars is ~175,000
tokens across 13 chunks, and only **59 of 271 pages carry a dollar amount** - roughly 78%
of the budget is policy wording. `improving-ll.md` C21 documents this model degrading at
~170k tokens (inventing field names, borrowing values across field types). The text is now
clean enough for the model to judge correctly; whether it does is governed by how much
irrelevant wording it has to wade through. That is segmentation (follow-up #1), and page
206's complete 36-form list is the shortcut.

**Recommendation recorded:** stop tuning extraction. The next measurement is an end-to-end
run on this package - does `umbrella_limit` come back $3M with GL still $1M, and does
`coverage_lines` carry all four policy numbers intact?

### Known limits, accepted and documented

- A multi-word cell that physically overflows into the next column is an inherent
  ambiguity at word granularity: a word that STARTS past the next anchor is assigned to
  that column. Only the page image resolves this (follow-up).
- A first-column value that wraps onto its own line (single cell in column 0) ends the
  table rather than folding. Certificates wrap LIMITS (column 3), which folds correctly.
- On blank ACORD forms the detector still emits readable form grids (`PRIMARY | HOME |
  BUS | CELL`, `SINKHOLE COVERAGE | ACCEPT | REJECT`). On a FILLED form those carry the
  box-label -> value relationship, which is the point. A page footer aligned under the
  grid can be absorbed as a last row (ACORD 130 p1).
- ~7 prose fragments survive the gates on a 271-page policy package (~2,500 chars of
  ~700,000). Additive, never a replacement for page text. Tightening further starts
  rejecting genuine tables - measured, not assumed.
- The gates are English-convention: they assume a record does not begin with a lowercase
  letter. That holds for ACORD forms, carrier declarations and loss runs. A document in a
  language without case would fall back to the geometric tests alone.
- ~~`Named Insured | Producer` still merges~~ **FIXED in the fifth pass** (above). The
  stray leading comma on page 1 is in the SOURCE PDF - the glyph run literally begins `,O`
  at x0=36 - so extracting it is faithful, not a defect.
- The identity split requires a POSTAL line in BOTH columns. Two side-by-side blocks with
  no address (a schedule of names, say) will not be separated. Deliberate: without that
  evidence the same rule splits blank ACORD label grids, which on a filled application
  separates a printed label from its box.
- Two-column PROSE needs >= 8 lines to be reordered. A genuinely short two-column passage
  is left as-is; the alternative was scrambling 4-line paragraphs that merely happen to
  align.
- Three-column layouts are not handled: the gutter search returns a single x. No
  three-column page appeared in the corpus. The band machinery would recurse cleanly if one
  ever does.
- A band is reordered as a whole, so a page whose columns SWAP role partway (left column
  ends, right column continues into a new topic) is still emitted left-then-right. Correct
  for every page measured; a genuinely interleaved layout would need region detection.
- pdfplumber's `extract_words` merging of stacked 6pt labels on dense forms is a
  pre-existing text-quality issue and is untouched (fixing it means replacing pdfplumber's
  line clustering page-wide, which breaks the identity guarantee).

---

## 4. Verification

**Current state after six passes** (numbers re-measured 2026-08-22, not carried forward):

| Check | Result |
|---|---|
| **Full suite** | **3698 passed / 2 failed / 2 skipped** - the two failures are the pre-existing `test_arq_acord125_missing_only` and `test_normalization`, identical to the 3664/2/2 baseline taken before the first edit. **Zero regressions across all six passes.** |
| `tests/test_page_layout.py` | **34 passed** |
| Targeted: reflow + embedded images + text selection + dec entries + full-document coverage | **183 passed** |
| **Identity corpus** - 49 pages: 4 reflow fixtures, 3 client docs, ACORD 125/126/127/130/140/25, SQS spec (Word), 125 data map (Acrobat) | **exactly 1 page changes** - the loss-run riffle repair. `_EXPECTED_CHANGES` is asserted as an exact set, so the test fails both if a new page starts changing and if a repair silently dies |
| Character multiset, every page of the 271-page package | **0 mismatches** - no transform ever adds or drops a character |
| **271-page package totals** | 699,844 chars, 271/271 page markers, **15 tables**, 5 embedded-image blocks |
| Pages transformed on that package | 172 reordered (two-column), 16 despaced (teletype), 2 riffled lines (loss run) |
| Loss run | `03/28/2024 Business Auto Insured vehicle rear-ended third party $4,850 $0 Closed`; PAID lands in the PAID cell |
| Client test package tables | dec 1 (`SCHEDULE OF COVERAGE PARTS`, 6 rows), certificate 1 (continuation folded), loss run 1, application 0 |
| Identity blocks | pages 1, 85, 205 - `Named Insured` owns its address, `Producer` owns its own |
| Label/value protected | page 205 limits, page 85 premium schedule, page 1 coverage grid - all values still paired |
| Table quality | 0 tables with a bare function-word cell; every forms list (pages 4, 87, 144, 145, 207, 208, 241) retained |
| False positives | 125 data map 0; ACORD 25 0; SQS spec 7 genuine tables |
| Vision pixel space (loss-run words x 300/72) | identical table - one detector serves native and scanned pages |
| Cost | +5-9 ms/page of new work; **38.7 s** for OCR + text + tables over the full 271 pages |

**Status: SHIPPED 2026-08-22, six passes.** Nothing committed - owner pushes. Files touched:
`backend/utils/page_layout.py` (new), `backend/tests/test_page_layout.py` (new),
`backend/services/ocr_service.py`, `backend/services/extraction_pipeline.py`,
`backend/utils/table_extractor.py` (docstring), `CLAUDE.md` (one pointer), `v1-20AUG.md` (entry X1).

**Historical suite readings** (kept so the progression is auditable): baseline 3664/2/2 ->
after wiring 3664/2/2 -> +new tests 3686/2/2 -> after prose gates 3686/2/2 -> after columns
3691/2/2 -> after despacing 3695/2/2 -> after the identity split **3698/2/2**.

---

## 5. Follow-ups deliberately NOT in this change

**Re-ranked after the sixth pass. Extraction is no longer the bottleneck - do not keep
tuning it.** The text is clean, page-scoped and character-complete. What limits the AI now
is how much irrelevant wording it must read, and what happens to the facts downstream.

**Closed since this list was first written:**

- ~~`Named Insured | Producer` on one line~~ - **FIXED, fifth pass.**
- ~~Re-measure duplicated prose and `;` injection~~ - **DONE.** Both were artefacts of the
  322-table run. Tables are now 15 (1.8% of the document) and the `; ` join is restricted
  to continuations that carry an amount.

**Open, in priority order:**

0. **End-to-end fact check on the 271-page package** - cheap, and it tells you whether any
   of the rest is worth doing. Does `umbrella_limit` come back $3M with `gl_each_occurrence`
   still $1M, and does `coverage_lines` carry all four policy numbers intact? Extraction now
   makes this answerable; nobody has run it.
1. **Page classification and segmentation** (owner's Issue 3) - **now the top build item.**
   The 271-page package is
   typed `dec_page` as a whole and runs **~175k tokens across 13 chunks**, while only
   **59 of 271 pages carry a dollar amount** - roughly 78% of the budget is policy wording.
   `improving-ll.md` C21 documents this model degrading at ~170k tokens (inventing field
   names, borrowing values across field types), so the package sits exactly on that line.
   Classify each page, collapse runs into sub-documents, and for `standard_form` pages
   record the printed form number and edition instead of ingesting the wording - every ISO
   and AAIS page prints its own id, and **page 206 lists all 36 applicable forms** (now
   extracted cleanly as a table), which also gives a nearly free forms-reconciliation
   finding. **This is document ROUTING, not text extraction** - it changes what reaches
   which LLM call, which is why it stayed out of scope here.
2. **Five findings rules from EXTRACTION_BRIEF Part 1** (#2 GL loss run filed on the auto
   policy, #3/#4 certificate omissions, #5 auto limit absent on the dec, #6 symbol 7
   without a schedule, #8 property declined vs described premises). Zero matching code
   exists; the data already reaches facts. Pure rule work, no extraction dependency.
3. **Section scoping on every value** (owner's Issue 5). A running heading stack so
   `Each Occurrence Limit $1,000,000` carries `General Liability Declarations` and can
   never be compared against an umbrella limit. Partly present already: `dec_page_entries`
   carries `section` and `line_of_business`. **Lower priority than it was** - the sixth
   pass showed every page now carries its own header within 27-46 lines, so the coverage
   part is recoverable without a schema change.
4. **Page image alongside text** for structure-critical pages (dec, schedules, loss runs,
   scans). Needs multimodal content parts in the LLM wrapper, selective routing on
   `declarations_authority`, and a cost model. Do this AFTER segmentation - 53 data-bearing
   pages is affordable, 271 is not.
5. `page` + `bbox` on `dec_page_entries` (schema + prompt change - LLM call 1).
6. Layout-engine evaluation (Document AI / Textract AnalyzeDocument) with numbers.
