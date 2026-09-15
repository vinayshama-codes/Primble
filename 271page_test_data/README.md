# 271-Page Test Package - Ground Truth Kit

## What this is

Human-verified ground truth for the 271-page / 699,844-char **Orbin Contracting LLC**
package policy - the same fixture referenced throughout `CLAUDE.md`'s fix history
(C19, C20, C22, C23, C29/C30, C46, C48, RC1/RC1b/RC2/RC3, the H1 series, and more).
It exists in this repo as two files:

- `271page-testdec.txt` (repo root, 718,677 bytes) - a saved raw-OCR debug dump from
  `ocr_service.py`, `TYPE: dec_page`, `CHARS: 699844`, session
  `76c5b64f-65e7-4dd1-a843-84890dc1e8b6`.
- `backend/tmp/bede02c75b3f4464a72d0c30f5c52311_2526 Package Policy (Complete Copy) (4).pdf`
  (3.98 MB) - the original upload the text was OCR'd from. Still sitting in upload
  staging (normally auto-cleaned; wasn't this time).

**Every one of the 271 pages was covered** - either read directly or confirmed
boilerplate via a full-document structural grep (`[Document page N]`, `[Table`,
`NAMED INSURED`, `DECLARATIONS`, `SCHEDULE OF`, `POLICY NUMBER`) that would have
caught any dec/schedule page hiding inside a long boilerplate stretch. Nothing was
skipped without checking.

## Document shape (why this matters for batching)

~35 pages are genuinely dense (declarations, schedules, class codes, vehicle/driver
rows). ~236 pages are verbatim ISO/AAIS policy-form boilerplate - the same legal text
any policyholder with that form attached would get, already summarized by each line's
own endorsement schedule table. Reading linearly wastes effort; the efficient approach
was to map the document's structure first (grep for table/declarations markers), then
read only the dense ranges in full and verify the boilerplate ranges via full-file grep
rather than transcribe them.

| Coverage line | Dense pages | Boilerplate pages | Policy # | Carrier |
|---|---|---|---|---|
| Common Declarations | 1-2 | - | 0482854 (account #) | - |
| Inland Marine | 3-9 | 10-84 | 6C7-40-02---26 | Employers Mutual Casualty Co. |
| Business Auto | 85-93 | 94-142 | 6E7-40-02---26 | Employers Mutual Casualty Co. |
| Commercial Umbrella | 143-148 | 149-194 | 6J7-40-02---26 | Employers Mutual Casualty Co. |
| (shared conditions) | - | 195-204 | - | - |
| General Liability | 205-212 | 213-257 | BBC7263 | **EMC Property & Casualty Co.** (different entity) |
| (shared conditions, tail) | - | 258-271 | - | - |

Property, Crime & Fidelity, and Workers' Compensation are all **No Coverage** -
confirmed both by the page-1 summary and by the total absence of any dedicated
declarations page for them anywhere in the 271 pages.

## Files

- **`ground_truth.json`** - the structured key. Every fact and schedule row, each
  tagged with its source page. Not pre-merged across duplicate mentions (e.g. the
  agent number appears 3 different ways in the source - all 3 are recorded, not
  collapsed) because the point is to test whether the SYSTEM reconciles them
  correctly, not to hide the ambiguity from the test. Includes a
  `validation_checklist` block with concrete pass/fail assertions tied to specific
  documented bugs (C22, C23, C46, RC1, ...).
- **This README** - provenance and methodology.

## How to use it

1. Run this package (the PDF in `backend/tmp/`, or re-upload if that's been cleaned)
   through the real pipeline: extraction → alias stamping → combined gap fill →
   stamped PDFs.
2. Pull the session's extracted `facts` dict and the generated PDF field values.
3. Diff against `ground_truth.json` into four buckets:
   - **Correct** - matches.
   - **Missed** - blank where the ground truth has a value.
   - **Wrong** - has a value that doesn't match.
   - **Invented** - has a value with no source anywhere in the document (check
     against `known_ocr_identity_variances` before calling something invented - it
     might just be a different rendering of the same real value).
4. Grade schedule/table rows (vehicles, class codes) **by row**, not by cell - a
   shifted or duplicated row is a different failure than one wrong number.
5. Walk the `validation_checklist` block explicitly - each item names the exact
   field(s) and the bug it's guarding against.

Before running the live test, consider setting `PURGE_DEC_INDEX_AFTER_GENERATION=0`
for that session so `dec_page_entries` survives generation for inspection too -
production deletes it by default after forms are generated.

## Batching method (for reproducing this on a future large document)

Read tool caps a `.txt` read at ~25,000 tokens per call (confirmed empirically, not
a fixed line/page count). For a document this dense, ~1,200-1,600 lines per call
stayed safely under that. Rather than reading every such window in full:

1. Grep the whole file once for structural markers (`[Document page`, `[Table`,
   `NAMED INSURED`, `DECLARATIONS`, `SCHEDULE OF`, `POLICY NUMBER`, coverage-part
   header phrases) to get exact line numbers for every page and every dense section.
2. Read the dense ranges in full, in ~1,200-1,600 line windows.
3. For ranges the grep sweep confirms carry no such marker, treat as boilerplate -
   log the form numbers (already captured from that line's own endorsement schedule
   table) and move on, rather than transcribing legal text with zero form-fill value.
4. Spot-verify by directly reading at least one "confirmed boilerplate" range in full
   before trusting the inference pattern for the rest (done here for pages 226-248 -
   came back exactly as predicted).
