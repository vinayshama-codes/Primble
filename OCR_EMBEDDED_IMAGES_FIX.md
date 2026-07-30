# OCR Embedded-Image Fix - Review Briefing

**Purpose of this document:** hand a fresh reviewer everything needed to audit this
change without prior context. It states the original defect, the design and why each
decision was forced, what was measured, and - importantly - where the residual risk is
concentrated so a reviewer knows where to attack.

**Status:** implemented, tested, not committed.
**Scope:** `backend/services/ocr_service.py` (modified), plus two new files.

**Revision 2 (2026-07-29)** - an adversarial review found six further defects in
this change, three of which reintroduced the original bug class (silent loss,
success reported). All six are fixed; see §10 for what they were and how each is
now guarded. §4.3, §4.5, §7 and §8 have been corrected where they were wrong.

---

## 1. System context

Primble is an ACORD insurance-form processing platform. The pipeline is:

```
upload (PDF / image / zip)
   -> ocr_service.extract_text()          <-- THIS CHANGE
   -> utils.text_cleaner.clean_text()
   -> extraction_service (chunked LLM fact extraction)
   -> pdf_service (deterministic field rules, alias stamping, LLM gap fill)
   -> stamped ACORD PDFs
```

If `extract_text()` fails to return a piece of text, **nothing downstream can recover
it**. The LLM cannot extract a policy number it never received. That makes this
function the single highest-consequence data-loss point in the product.

OCR provider is Google Cloud Vision. Credentials are an API key
(`GOOGLE_VISION_API_KEY` in `backend/.env`), so the REST path is the live one; a
service-account/gRPC path also exists in code.

---

## 2. The problem statement (original defect)

`extract_text_from_pdf()` decided whether to OCR at the **document** level:

```python
# OLD CODE (git HEAD, backend/services/ocr_service.py)
text = await loop.run_in_executor(_OCR_EXECUTOR, _pdfplumber_extract, pdf_path)

low_conf = []
if len(text.strip()) < _MIN_NATIVE_TEXT_LEN:          # 100 chars, WHOLE DOCUMENT
    img_paths = await loop.run_in_executor(_OCR_EXECUTOR, extract_images_from_pdf, pdf_path)
    for ip in img_paths:
        page_text, page_low = await ocr_image_file(ip)
        text += page_text + "\n"
        ...
return text.strip(), low_conf
```

**Failure mode.** A PDF that is mostly typed text but contains a declarations page
pasted in as an **image** has more than 100 characters of native text, so the
`if` never fires and OCR never runs. The image's contents - carrier, policy number,
limits, effective dates - are silently discarded. The upload reports success. The
broker sees a form with missing fields and no error.

**Why it was easy to miss:** uploading the same dec page as a standalone `.jpg`/`.png`
worked perfectly (that path calls `ocr_image_file` directly). The bug was specific to
images *embedded inside* a PDF.

**Reproduction (pre-fix):** a 1-page PDF with ~900 chars of narrative text plus a
300x200pt embedded dec-page image. Native layer contains no policy data; old code
returns only the narrative. Confirmed by direct differential run (section 7).

---

## 3. Constraints that shaped the fix

These are non-obvious and each one ruled out a simpler design. A reviewer should
verify these independently, because if any is wrong the design is wrong.

### C1 - `clean_text` de-duplicates paragraphs by exact MD5

`backend/utils/text_cleaner.py`:

```python
for para in text.split('\n\n'):
    stripped = para.strip()
    if len(stripped) < 10:
        continue
    h = hashlib.md5(stripped.encode()).hexdigest()
    if h not in seen:
        seen.add(h); out.append(stripped)
```

Consequence: you **cannot** fix this by OCR-ing the whole page and appending the result
to the native text. Two OCR engines never produce byte-identical output, so the MD5
dedup will not collapse it and **every page would appear twice** in the LLM input.
This is what forced the "OCR only the embedded image, not the page" design.

It also drops paragraphs under 10 characters, which is why the marker line is joined
to the OCR text with a single newline (one paragraph) rather than separated by a blank
line.

### C2 - a prior fix lives in the same function and must not be reverted

Commit `77b19da` added `_extract_page_text_smart()` - a scoped two-column reflow
recovery. Without it, a drifted two-column dec page extracts as `CARRIER: 84-2210987`
(the FEIN) instead of the carrier name. An earlier proposed patch for the embedded-image
bug was written against a pre-`77b19da` copy of the file and silently reverted this.
`tests/test_ocr_embedded_images.py::test_pdfplumber_extract_pages_applies_column_reflow`
now fails the build if it is reverted again.

### C3 - Google Vision `images:annotate` caps at 16 images per request

Verified live against the project's own API key: 16 returns 16 responses; 17 returns
`HTTP 400 "Too many images per request"`. The old code sent exactly one image per HTTP
call, which is the entire source of the latency problem on scanned documents.

### C4 - "searchable PDFs" are the main trap

Adobe Scan, ABBYY and essentially every office scanner emit a *searchable PDF*: the page
bitmap **plus an invisible text layer** (PDF render mode 3) holding that scanner's own
OCR. Such a page has both a full native text layer and a full-page image. Naive handling
double-counts the whole page. These are very common in broker workflows.

---

## 4. The fix

### 4.1 Per-page routing, two paths

`extract_text_from_pdf()` now decides per page, not per document:

| Page condition | Path | Behaviour |
|---|---|---|
| native text < 100 chars | **B** (scan) | render page at 2x, OCR it, use the OCR text; fall back to native if OCR returns nothing |
| native text >= 100 chars | **A** (text page) | **keep the native text verbatim**, and additionally OCR each embedded image from its own stored raster, **appending** the result |

Path A appends and never replaces. Rationale: forced by C1 (appending page-level OCR
duplicates), by C2 (native layer carries the reflow fix), and by the error asymmetry -
a false positive costs one batched sub-call and appends a company name, a false negative
loses policy data. That asymmetry is why the image filter is deliberately permissive.

Path B replaces rather than appends. Verified live: a scanned page's own typed header is
visible in the render, so Vision returns it too; appending would emit it twice.

### 4.2 Batched OCR

Single primitive, two feeders. `_ocr_payloads()` groups images into batches bounded by
**both** count (<=16, C3) and total bytes (6 MB, since Vision limits the whole request
and base64 inflates ~33%), dispatched with bounded concurrency (4).

`_ocr_batch_sync()` is circuit-broken and **failure-isolating**: on a whole-request
failure it splits the batch in half and retries each half, so one undecodable image
cannot destroy the 15 valid images travelling with it. Recursion is bounded by
log2(batch). It never raises; a permanently failing payload yields `ok=False`.

`_is_retryable()` retries transport errors, timeouts, 429 and 5xx only. Retrying a
permanent 4xx burns the backoff budget at every level of the split recursion.

**Deliberately NOT used:** Vision's `files:annotate`, which accepts a PDF directly and
rasterises server-side. It was verified to work with this API key, but it adds a second
response shape, a silent 5-page truncation trap (a 10-page PDF returns HTTP 200 with only
5 page responses and no error), sub-PDF splitting, and is API-key-only. The benefit
(server-side rasterisation) was measured to be unnecessary - a 2x page render read 5pt
text in a 300 DPI embedded scan correctly.

### 4.3 The searchable-scan guard (C4) - the most delicate part

On Path A, an embedded image is **skipped** only when a dense native text layer already
covers it. Two independent signals must both agree:

- **glyph area** - fraction of the image's box covered by native word boxes (>= 6%)
- **band spread** - fraction of the image's **inked** vertical extent that contains
  native words, in 10 bands (>= 80%)

Band spread is measured against where the image actually has ink (`_image_ink_bands()`,
a ~64px greyscale render costing 0.64 ms), **not** against the page. A scanned
certificate whose content fills only the top 40% still carries a complete OCR layer over
that 40%; judging it against the full page would re-OCR and duplicate it.

**Both inputs to this guard were wrong in revision 1. Read §10.1 and §10.2 before
touching it.** Word boxes were compared against the image rect in a *different
coordinate frame* on any rotated page, and "ink" was a fixed near-white cutoff that
real scanner paper trips, which silently reduced the ink-relative measure to the
page-relative one it exists to replace.

Two further properties this guard now depends on:

- **Ink is relative to the image's own paper** (90th-percentile luminance of the probe
  render, minus a margin), never a fixed value. Paper at byte 249 or darker - routine,
  from lamp falloff, paper tint and JPEG noise - otherwise makes every band "inked".
- **At least 3 of 10 bands must be inked** before the ink-relative basis is used at all.
  A nearly-empty image inks one band, and any native text landing in that band would
  score 1/1 = 100% spread and skip the image on a single-band coincidence. Below the
  floor it falls back to the page-relative measure, which errs toward OCR'ing.

Measured on realistic documents (a scanned ACORD 25, not synthetic text):

| case | words | area | ink-band spread | decision |
|---|---|---|---|---|
| real searchable ACORD 25 dec page | 95 | 8.3% | 100% | skip |
| searchable scan, content top 60% | 77 | 7.2% | 100% | skip |
| searchable scan, content top 40% | 77 | 7.2% | 100% | skip |
| partial OCR layer over full-page scan | 38 | 3.5% | 50% | **OCR** |
| scan + diagonal CONFIDENTIAL watermark | 27 | 5.4% | 70% | **OCR** |
| scan + header AND footer blocks | 90 | 4.2% | 40% | **OCR** |
| scan + 14-line native header | 84 | 4.4% | 30% | **OCR** |
| scan + Bates / confidential banner | 14 | 1.0% | 20% | **OCR** |
| pasted exhibit, no overlap | 0 | 0.0% | 0% | **OCR** |

Both thresholds fail toward OCR-ing, i.e. toward duplication (a cost) rather than
skipping (unrecoverable loss).

**A text-similarity backstop was considered and deliberately rejected**: it would have
introduced a new path capable of dropping a legitimate exhibit.

### 4.4 Embedded-image candidate filter

The load-bearing gate is the **stored raster size**, not displayed area: decorative icons
are stored at 32-64px regardless of page scaling, while any raster that could hold legible
text is materially larger. Displayed geometry is a secondary gate.

Content-hash dedup (SHA-256 of the normalised payload) means a letterhead repeated on 200
pages is OCR'd **once** and appended only on its first page.

### 4.5 Robustness

- Every `fitz.open()` is paired with `_safe_close()` in a `finally`. An unclosed
  PyMuPDF document holds an OS handle; on Windows that makes the caller's `os.remove()`
  fail with WinError 32, which `form_routes` swallows as a bare `OSError`, stranding
  uploaded PII on disk. Verified reproducible.
- Page renders go to memory, not `UPLOAD_DIR`, eliminating the temp-file leak class.
- Documents are processed in **windows** of 24 pages so peak memory does not grow with
  document length. The document is opened once per window, not once per page.
- Very large rasters (> 25 Mpx) are never fully decoded - a 1200 DPI scan would be ~400 MB
  of RGB. The page region is rendered at bounded zoom instead.
- Formats Vision cannot read (JBIG2, JPX, CCITT - routine in scanned PDFs) are transcoded
  to PNG; oversized images are downscaled, never dropped.
- Alpha is dropped before any JPEG encode (PyMuPDF raises `ValueError: cannot have alpha`).
- Page renders obey the same 25 Mpx ceiling embedded images do. PDF permits sheets up to
  200 inches; a 34x44in E-size drawing renders to 31 Mpx (~93 MB of RGB) at 2x, and a
  window of 24 pages is built before anything is dispatched. Zoom is clamped instead
  (§10.5).
- Caps degrade **loudly** - *all* of them, which was not true in revision 1 (§10.3).
  Over `OCR_MAX_PAGES_PER_DOC`, or either embedded-image cap, native text is still kept,
  the count of what was dropped is logged at ERROR, and `needs_manual_review` is raised.
- A provider failure on an embedded image is distinguished from an image that genuinely
  had no text, logged at ERROR and flagged for review (§10.4).
- With no Vision credentials at all: no crash, native text preserved, flagged for review.

---

## 5. Files changed

| file | status | notes |
|---|---|---|
| `backend/services/ocr_service.py` | modified | +1191 / -87 |
| `backend/tests/test_ocr_embedded_images.py` | new | 76 tests (58 + 18 added in rev 2) |
| `backend/verify_ocr_fix.py` | new | manual tool, safe to delete |

### Functions a reviewer should read first

Line numbers are as of revision 2. If they have drifted again, find them by name -
do not trust the numbers.

| function | line | why |
|---|---|---|
| `extract_text_from_pdf` | 1460 | the orchestrator; page routing and assembly |
| `_build_window_jobs` | 1362 | per-window payload construction, budget accounting |
| `_page_is_blank` | 1343 | blank-page skip (silent-loss risk if wrong) |
| `_image_candidates` | 1160 | the filter gates, incl. the searchable-scan guard |
| `_image_ink_bands` | 1089 | ink-relative band reference - see §10.2 |
| `_native_text_coverage` | 1057 | area + band measurement |
| `_native_word_boxes` | 1017 | **coordinate-frame correction** - see §10.1 |
| `_extract_page_text_smart` | 751 | **unchanged** prior fix - verify it is still wired in |
| `_group_payloads` | 555 | count and byte bounded batching |
| `_ocr_batch_sync` | 499 | circuit breaker + split-on-failure |

---

## 6. Key configuration (all env-tunable, defaults shown)

```
_MIN_NATIVE_TEXT_LEN        100        page-level Path A / Path B threshold
_VISION_HARD_MAX_BATCH      16         API limit, clamped not merely defaulted
_VISION_MAX_BATCH_BYTES     6 MB       OCR_VISION_BATCH_BYTES
_VISION_MAX_IMAGE_BYTES     4 MB       OCR_VISION_IMAGE_BYTES
_OCR_BATCH_CONCURRENCY      4          OCR_BATCH_CONCURRENCY
_OCR_PAGE_WINDOW            24         OCR_PAGE_WINDOW
_OCR_MAX_PAGES_PER_DOC      400        OCR_MAX_PAGES_PER_DOC
_PAGE_RENDER_ZOOM           2.0        OCR_PAGE_RENDER_ZOOM

_EMB_MIN_RASTER_LONG_PX     150        primary icon filter
_EMB_MIN_RASTER_SHORT_PX    40
_EMB_MIN_DISPLAY_PT         20.0
_EMB_MIN_AREA_RATIO         0.0015
_EMB_MAX_IMAGES_PER_PAGE    12
_EMB_MAX_IMAGES_PER_DOC     60
_EMB_MAX_DECODE_PIXELS      25,000,000

_EMB_NATIVE_COVER_RATIO     0.06       searchable-scan guard, glyph area
_EMB_NATIVE_COVER_BANDS     0.80       searchable-scan guard, ink-band spread
_EMB_NATIVE_COVER_MIN_WORDS 8
_EMB_NATIVE_BAND_COUNT      10
```

---

## 7. Evidence

**Differential vs the actual old implementation** (extracted from git HEAD, same fake OCR,
12 document shapes): **zero content regression**. Every substantive line the old code
produced is still present. Searchable scan is 637 -> 637 chars with 0 Vision calls,
identical to old behaviour.

**Test suite (re-measured at revision 2):** **1019 passed / 9 failed**, identical
failures to the pre-change baseline on the same tree - zero regressions. All 9 are
pre-existing and unrelated to OCR; each also fails in isolation:
`test_arq_acord125_missing_only` (the known httpx/openai version conflict),
`test_normalization`, and 7 in `test_full_document_coverage` /
`test_prompt_prefix_caching` which belong to the separate `improving-ll.md` prompt-caching
work. **The "945 passed / 2 failed" in revision 1 of this document did not reproduce** -
do not use it as a baseline. 76 OCR tests. Pyflakes clean.

**Live Google Vision, 4 scenarios, 6 critical values each:**

| scenario | recovered | duplication |
|---|---|---|
| text page + large embedded dec image | 6/6 | 1x |
| text page + small (1.5% of page) embedded dec image | 6/6 | 1x |
| searchable scan (scanner OCR layer present) | 6/6 | 1x, **0 Vision calls** |
| Bates-stamped scan (no scanner layer) | 6/6 | 1x |

**Performance:** plain 200-page text PDF +3%; 200-page PDF with logos -4%. 32-page pure
scan 10.1s in 3 requests vs ~101s in 32 requests before (~10x). 200-page searchable scan:
0 Vision calls, no duplication. Ink probe 0.45 ms per image.

**Concurrency:** 4 documents x 20 scanned pages simultaneously - no deadlock, perfect
per-document isolation, batch cap held, executor not saturated.

**Downstream:** 11/11 critical values from realistic dec-page OCR survive `clean_text`.
The only lines it drops are ACORD legal boilerplate ("THIS CERTIFICATE IS ISSUED AS A
MATTER OF INFORMATION ONLY...") via a pre-existing all-caps filter, which carry no
underwriting data.

---

## 8. Where to attack (read this before reviewing)

Development history matters here, because it shows where the risk concentrates.

**A regression was introduced and fixed during development, and the first fix for it was
itself wrong.** The searchable-scan case (C4) was initially not handled at all, causing
every searchable PDF to be double-counted. The first guard gated on **native word count**
inside the image. Measurement showed that a full-page scan carrying only a Bates stamp
already has 14-50 native words inside the image's box, so that guard would have
**discarded the entire scan** - the original bug class, reintroduced. It was caught by
measuring, not by reasoning. Concentrate scrutiny accordingly.

Specific things worth attacking:

1. **The searchable-scan guard thresholds (6% area / 80% ink-band spread) are calibrated
   on documents that were generated, not on real scanner output.** Real output varies by
   vendor, DPI and compression. This is the single largest residual risk. Both are
   env-tunable and both fail toward OCR-ing (duplication, not loss), but a reviewer should
   push real scanned files through `verify_ocr_fix.py`.

   Revision 1 named this the top risk but pointed at the wrong number. The measurement
   table above was produced on synthetic pure-white pages, and the *fixed* near-white ink
   cutoff it depended on is tripped by essentially all real scanner paper (§10.2) - so on
   real files the ink-relative rows of that table would not have reproduced at all. That
   specific defect is fixed; the broader "calibrated on generated documents" caveat
   stands, and now genuinely is about the 6% / 80% values.

   Note the asymmetry when re-tuning: this guard's *safe* failure is duplication, and
   duplication is not free in this pipeline. Per `improving-ll.md` C21/C22 the model
   measurably degrades at long context (it starts inventing ACORD field names around
   ~170k tokens), so a duplicated dec page costs answer quality, not just tokens.

2. **`_page_is_blank()`** skips OCR entirely for a page it judges empty. If it is ever
   wrong, that is silent data loss. It was probed against annotation-only pages,
   widget-only pages, nested Form XObject vector content, shading fills, outlined glyph
   strokes and white-on-white text, and held in all six - but it is the highest-severity
   single predicate in the file.

   Independently re-verified at revision 2 against a filled AcroForm-widget-only page
   (the shape this product actually ingests) and a free-text-annotation-only page:
   PyMuPDF's `get_text("text")` picks up both, so neither is judged blank. This one
   holds.

3. **The gRPC / service-account provider path is unit-tested but never exercised against
   the live API** (only an API key is configured). If the deployment ever switches to
   `GOOGLE_APPLICATION_CREDENTIALS`, that path needs live testing first.

4. **Path B replaces the short native remnant with OCR text**, where the old code appended.
   Verified live that a scanned page's typed header appears in the render and therefore in
   Vision's output, so nothing is lost - but this is a behavioural change from the old code
   and deserves a second opinion.

5. **Cross-page image dedup attaches a repeated image's text to its first page only.** If
   the same image is genuine content repeated at different points in a document, its text
   appears once rather than at each occurrence. Judged correct (no data loss, avoids
   flooding), but it is a judgement call.

6. **A sparse searchable-scan OCR layer** (below 6% glyph area) falls under the guard and
   gets OCR'd, duplicating that page. Accepted: a cost, not a loss.

### Known pre-existing issues, deliberately NOT fixed here (out of scope)

- `tests/test_production_guards.py:32` and `tests/test_arq_acord125_missing_only.py:38`
  install permanent `sys.modules` stubs (`google.auth`, `google.oauth2`, `circuitbreaker`)
  with no teardown. They leak into every test module imported afterwards. The new tests are
  hermetic against this; future ones will not be.
- `/api/upload-declaration` runs the whole extraction synchronously inside the HTTP request
  while holding a heavy-ops semaphore whose Redis TTL is 300s
  (`utils/concurrency.py:_SEM_TTL_MS`). Any extraction longer than 5 minutes releases its
  slot while still running. There is also no page cap on upload
  (`MAX_UPLOAD_SIZE_MB=50` x `MAX_FILES_PER_UPLOAD=10`, unbounded pages). This change makes
  extraction much faster and adds an OCR page cap, but does not address the request-level
  architecture.
- `clean_text` drops all-caps lines with more than 8 words. Verified harmless for
  underwriting data (only ACORD legal boilerplate is affected), but it is a blunt filter.

---

## 9. How to verify independently

```bash
cd backend

# 1. Test suite. Expect 945 passed / 2 failed (both pre-existing).
./venv/Scripts/python.exe -m pytest tests/ -q

# 2. Just this area, in isolation.
./venv/Scripts/python.exe -m pytest tests/test_ocr_embedded_images.py tests/test_ocr_column_reflow.py -v

# 3. Old vs new on YOUR OWN real PDFs. Makes live Vision calls (~$1.50/1000 pages).
./venv/Scripts/python.exe verify_ocr_fix.py "C:\path\to\real.pdf" [more.pdf ...]
```

`verify_ocr_fix.py` runs the old implementation and the new one on the same file and
reports:

- **RECOVERED** - text the old code silently dropped. Non-zero means the fix is working.
- **LOST** - text the old code had and the new code does not. **Must be zero.**
- **DUPLICATED** - lines emitted more than once. Near zero expected; a real scanned dec
  page showing every line twice means the guard's thresholds need tuning.

Test with, at minimum: a dec page pasted into a document as an image; a PDF straight out
of Adobe Scan or an office MFP; anything Bates-stamped or watermarked; **and at least one
landscape or sideways-scanned page** (see §10.1 - rotation was completely untested in
revision 1, and broke in both directions).

`verify_ocr_fix.py` now also prints a per-image disposition breakdown. **Read it.** LOST
is a *regression* check - it compares new output against old, so it is structurally blind
to an image this filter discarded, because the old code did not have that text either.
Every one of the six defects in §10 reported `PASS: nothing lost`. Under-recovery shows
up as "dropped at a cap" and "covered by a text layer".

Runtime log lines to watch:

```
ocr_service: <file> - N/M page(s) OCR'd, K embedded image(s) OCR'd
ocr_service: dispatching N image(s) in M Vision batch(es)
```

`K > 0` confirms embedded images are being recovered. Batch count should be far below
image count; 1:1 means batching regressed.

---

## 10. Revision 2 - defects found by adversarial review, and their fixes

Six defects. Three (10.1, 10.3, 10.4) reintroduced the exact bug class this change
exists to eliminate: content dropped, upload reports success, nothing in the review
flag. Each is now covered by a regression test that was **verified to fail against the
pre-fix behaviour** - a test that passes either way guards nothing.

### 10.1 Rotated pages measured the wrong region of the page (silent loss AND duplication)

`page.get_text("words")` reports boxes in the page's **unrotated** space.
`page.get_image_bbox()` - the only rect they are ever compared against - reports in the
**rotated (displayed)** space. `_native_text_coverage` compared them directly, so on any
`/Rotate 90/180/270` page the searchable-scan guard measured a region unrelated to the
image, and then fired, or failed to fire, essentially at random.

Proven on one document saved at four rotations, differing only in `/Rotate`
(`get_image_rects` confirms the true rect is identical at all four):

```
rot=  0  bbox=(45,45,345,245)    coverage= 0.0%  spread=  0%  -> image recovered
rot= 90  bbox=(547,45,747,345)   coverage= 2.2%  spread= 30%  -> image recovered
rot=180  bbox=(267,547,567,747)  coverage=20.1%  spread= 30%  -> image recovered
rot=270  bbox=(45,267,245,567)   coverage=86.2%  spread=100%  -> *** DISCARDED ***
```

At 270 degrees a pasted declarations page was dropped and logged as
`1 covered by text layer` - a reassuring message for the precise failure this change
exists to prevent. **It breaks in both directions:** a searchable scan at 90/180/270 was
*not* recognised as one and got re-OCR'd, duplicating the whole page into the LLM input.

Rotated pages are routine in broker submissions - landscape schedules, MFP auto-rotation,
sideways-fed scans.

**Fix:** `_native_word_boxes` maps boxes through `page.rotation_matrix`, so they land in
the same frame as the bbox. Coverage is now 0.0% at all four rotations for the case above.
`page.rotation == 0` short-circuits, so unrotated documents are untouched.

The bbox is *correct* for `page.get_pixmap(clip=...)`, which renders the rotated page -
so `_image_ink_bands` and the oversized-raster region render were always right. Only the
word-box comparison needed correcting. **Do not "fix" the other two.**

Guarded by `test_embedded_image_is_recovered_on_a_rotated_page[0/90/180/270]`,
`test_searchable_scan_is_not_duplicated_on_a_rotated_page[0/90/180/270]` and
`test_native_word_boxes_are_reported_in_the_image_bbox_frame`.

### 10.2 "Ink" was a fixed cutoff, making the ink-relative band test inert on real scans

`_image_ink_bands` treated any pixel below byte 250 as ink. Measured:

```
paper 255 (pure white)  -> ink bands [0]          ink-relative, correct
paper 252               -> ink bands [0]          ink-relative, correct
paper 249               -> ink bands [0..9]       DEGENERATE
paper 229               -> ink bands [0..9]       DEGENERATE
```

Real scanner output essentially never renders paper at 250+: lamp falloff, paper tint and
JPEG ringing put it at 240-250. So on real files every band read as "inked", the
denominator became the whole image, and the ink-relative measure silently collapsed into
the page-relative one it exists to replace - re-OCR'ing and duplicating any searchable
scan whose content does not fill the sheet. The section 4.3 table's ink-relative rows were
produced on synthetic pure-white pages and would not have reproduced on a real scan.

**Fix:** paper level is measured per image (90th-percentile luminance of the probe
render) and ink is anything darker than paper minus a margin.

**This fix moves the failure direction**, which is why it carries a second guard. A
smaller ink set is a smaller denominator and therefore a *higher* spread, i.e. more
skipping - the direction that loses data. `_EMB_INK_MIN_BANDS` (3 of 10) requires enough
ink to divide meaningfully before the ink-relative basis is trusted at all; below it the
guard falls back to the page-relative measure, which errs toward OCR'ing. Without that
floor a nearly-empty image inks one band and any native text landing in that band scores
1/1 = 100% and skips the image on a single-band coincidence.

Guarded by `test_searchable_scan_on_tinted_paper_is_not_duplicated`,
`test_ink_probe_ignores_tinted_paper`, and - for the direction that matters -
`test_bates_stamped_scan_is_still_ocrd`, which asserts a full-page scan carrying only a
Bates banner is still OCR'd.

### 10.3 The embedded-image caps degraded in total silence

Section 4.5 claimed "Caps degrade **loudly** ... Never silent." That was true of the page
cap and false of both image caps. Measured with 6 unique dec-page images and a cap of 3:

```
images planted: 6   recovered: 3   LOST: 3
low_conf: []        needs_manual_review: False
log: "3 embedded image(s) OCR'd (3 examined: ... 0 over cap)"
```

`_build_window_jobs` skipped whole pages with a bare `continue` once the cap was spent, so
`images_examined` never counted them, the partition self-check balanced at 3 == 3, and
even the tally-mismatch warning stayed quiet. A separate bug in the same area incremented
`skipped_capped` by 1 and then `break`ed, under-reporting an N-image drop as 1 and
*tripping* the partition check.

**Fix:** pages skipped at the cap are counted (`pages_images_unexamined`), every dropped
candidate is counted rather than just the first, and either image cap biting now raises
an ERROR naming the counts plus `needs_manual_review` - exactly as `pages_over_cap`
already did.

Guarded by `test_document_image_cap_is_flagged_for_review`,
`test_page_image_cap_is_flagged_for_review`, and
`test_document_image_cap_counts_every_dropped_candidate`.

### 10.4 `_OcrResult.ok` was never read outside the tests

The field exists specifically to separate "this logo has no words in it" from "the
provider failed". Both arrive as empty text and only the second is data loss. `_dispatch`
branched on `res.text.strip()` and ignored `ok`, so a hard Vision failure lost the image's
text, raised no flag, and was counted in the summary as a **successful** OCR
(`3 embedded image(s) OCR'd ... 0 unreadable` when one had hard-failed).

**Fix:** `_dispatch` branches on `ok` - logs ERROR naming the page, counts the failure
separately in the summary, and raises `needs_manual_review`. An *empty but successful*
read is still deliberately not flagged; that is the case the original comment was about.

Guarded by `test_failed_embedded_image_ocr_is_flagged_not_counted_as_success`.

### 10.5 Page renders had no pixel ceiling

Section 4.5's "very large rasters are never fully decoded" applied only to embedded
images. `_render_page_png` rendered at a flat 2x: a 34x44in E-size sheet produced 31.0 Mpx
(~93 MB of RGB), above the 25 Mpx guard, and a window builds up to 24 pages before
dispatching. **Fix:** zoom is clamped to the same ceiling (with a 0.99 margin, because
PyMuPDF rounds each pixel axis up and the unclamped result landed at 25.004 Mpx).
Reduced resolution degrades OCR slightly; exhausting memory loses the document. Only
sheets far larger than any ACORD form are affected - a letter page at 2x is 1.9 Mpx.
Guarded by `test_oversized_page_render_respects_the_pixel_ceiling`.

### 10.6 Repeated assets were fully rebuilt on every page before dedup

Content-hash dedup cannot run until the payload exists, so a letterhead on 30 pages was
extracted, transcoded and hashed 30 times to be discarded 29 times - measured, 30 payload
builds for 1 Vision call. Cheap for an in-budget JPEG; for JBIG2/CCITT/JPX (which this
module's own comments call "routine in scanned PDFs") it is a full decode and PNG
re-encode per page.

**Fix:** an xref pre-check (`budget.seen_xrefs`) before any payload work. `seen_xrefs` is
populated **only when an image is actually accepted**, never when one is dropped at a cap
or skipped by the searchable-scan guard - otherwise a capped or guarded image would
suppress its own later occurrences and turn a cost into silent loss. The content hash is
retained: it still catches the same asset re-embedded under a *different* xref, which the
xref check cannot see. Guarded by
`test_repeated_asset_payload_is_built_once_not_once_per_page`.

### What revision 2 did NOT change

- The 6% / 80% thresholds. They still want calibrating against real scanner files
  (section 8, item 1).
- The gRPC / service-account path, still never exercised live (section 8, item 3).
- Path B replacing the short native remnant (item 4) and first-page-only image dedup
  (item 5) - both re-read, both still judged correct.
- The pre-existing issues in section 8's final subsection, all still out of scope.

### How revision 2 was verified

A 20-check before/after harness covering every scenario these fixes could touch
(all four rotations in both directions, tinted-paper searchable scans, Bates scans,
both caps, provider failure, oversized pages, repeated letterheads, and a plain typed
page as the do-no-harm control). **10 checks failed before, 0 after.** Then the full
backend suite for regressions, then each new test re-run against a plugin that restores
the corresponding pre-fix behaviour, confirming every one of them actually fails without
its fix.
