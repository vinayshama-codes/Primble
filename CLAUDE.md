Primble: ACORD Form Processing Platform

## Overview

**What it does:** Automates ACORD insurance form filling by extracting facts from uploaded policy documents (OCR + LLM), then deterministically stamping ACORD form fields and using a shared LLM gap-fill pass for anything that couldn't be matched.

**Who uses it:** Insurance brokers and agents.

**Client:** Brent (funding development).

**Stage:** MVP (no paying customers yet, localhost deployment only).

**Current version:** 12.4.0

---

## Business Context

| Aspect | Details |
|--------|---------|
| **Problem Solved** | Reduces manual ACORD form filling for insurance professionals using AI |
| **Target Users** | Insurance brokers/agents |
| **Revenue Model** | Pre-revenue (subscription model planned) |
| **Team Size** | 2-3 people |
| **Your Role** | Lead Architect |
| **Users Currently** | 0 (no production users) |
| **Submissions/Day** | 0 (MVP, localhost only) |

---

## Technical Stack

### Backend
- **Framework:** FastAPI (Python)
- **Database:** PostgreSQL (psycopg2)
- **API Version:** 12.4.0
- **Web Server:** Uvicorn

### Frontend
- **Framework:** React
- **Build:** Vite
- **Authentication:** Google OAuth

### AI / Processing
- **LLM:** OpenAI (`gpt-5.4-mini` via `LLM_MODEL` / `GPT_MODEL` env vars)
- **OCR Provider:** Google Cloud Vision (primary; `OCR_PROVIDER=google`)
- **PDF Processing:** pdfplumber, pikepdf, reportlab

### Infrastructure
- **Job Queue:** DB-backed (`JOB_QUEUE_BACKEND=db`) — supports db / memory / local_file / sqs backends
- **Async Processing:** Disabled by default (`ENABLE_ASYNC_PROCESSING=false`)
- **Caching / Rate Limiting:** Redis (with in-memory fallback)
- **Email:** Resend (`EMAIL_FROM=noreply@primble.io`)
- **Payments:** Stripe API

### AWS (partially wired, not actively used)
- S3, SQS, Textract — commented out in .env, not in active use

---

## Supported ACORD Forms (17 forms)

All schemas live in `backend/forms_schemas/` (read-only, 129–1135 fields each).
Metadata lives in `backend/forms_database/`.

- ACORD 25 — Certificate of Liability Insurance
- ACORD 28 — Evidence of Commercial Property Insurance
- ACORD 101 — Statement of No Loss / Narrative Schedule
- ACORD 125 — Commercial Insurance Application
- ACORD 126 — Commercial General Liability Section
- ACORD 127 — Business Auto Section
- ACORD 130 — Workers Compensation Application
- ACORD 131 — Umbrella / Excess Section
- ACORD 133 — Builders Risk Section
- ACORD 137_CA / 137_CO — Contractors / Subcontractors (state variants)
- ACORD 138_CA / 138_CO — Contractors Equipment (state variants)
- ACORD 140 — Property Section
- ACORD 141 — Inland Marine Section
- ACORD 160 — Cyber Liability Section
- ACORD 186 — Contractors Supplemental Application

---

## Architecture: LLM Extraction Pipeline

This is the core of the system. Understanding it is critical before touching any extraction or form-fill code.

### Stage 1 — OCR + Chunked Extraction (one-time per document)
`extraction_service.py` sends the full document to the LLM in 11 chunks (~66k chars each).
Output: ~65 structured facts (producer name, policy dates, limits, etc.) stored in session.
Also produces boolean flags (coverage indicators) via `extraction_pipeline.py`.
This stage runs ONCE regardless of how many forms are selected.

### Stage 2 (Pass 1) — Deterministic Field Rules
`pdf_service.py → map_facts_to_form()` applies `_ACORD_FIELD_RULES` substring matching.
Fills fields directly from the extracted facts dict. No LLM call.

### Stage 3 (Pass 1.5) — Alias Stamping
`services/alias_stamper.py` loads 17 alias maps from `backend/forms_aliases/`.
Each alias map: `{ACORD_field_name: canonical_snake_case_name}`.
A bridge dict (`CANONICAL_TO_EXTRACTION`, 24 entries) maps canonical names → extraction fact keys.
Fills additional fields deterministically. `ENABLE_ALIAS_STAMPING` is hardcoded `True`.

### Stage 4-6 (Pass 2) — Combined Gap Fill
`pdf_service.py → combined_gap_fill()` + `compute_form_gaps()`.
Deduplicates unmatched fields across ALL selected forms, runs ONE shared LLM pass,
distributes results back to each form. `ENABLE_COMBINED_GAP_FILL` is hardcoded `True`.

**Effective pipeline:** shared extraction → alias stamp → one combined gap fill.
The legacy per-form gap-fill path still exists in code but is no longer reachable
via configuration.

### Known Performance Issue in Combined Gap Fill (not yet fixed)
- 1531 fields × ~400 chars/field = 612k char fields block → only 33k chars left for raw text → 22 chunks
- No `max_tokens` cap: model returns ~174k output tokens per call, saturating 200k TPM limit instantly
- Parallel chunk dispatch (4 workers) fires all 22 calls at once → constant 429 rate limits
- Fix plan documented in `CHANGES_THIS_CHAT.txt` and the "Known Issues" section at end of this file

---

## Code Structure

```
backend/
├── config/
│   └── settings.py          # All env vars, LLM wrappers (groq_chat/openai), feature flags
├── models/
│   └── schemas.py           # Pydantic schemas
├── repositories/            # Data access layer (session, job, user repos)
├── routes/
│   ├── auth_routes.py       # Google OAuth + JWT
│   ├── form_routes.py       # Upload, extraction, select-forms-bulk (main pipeline entry)
│   ├── download_routes.py   # Generate + download completed PDFs
│   ├── stripe_routes.py     # Subscription payments
│   ├── signature_routes.py  # Digital signature handling
│   ├── arq_routes.py        # Agent Report Questionnaire endpoints
│   ├── admin_routes.py      # Admin-only endpoints
│   ├── audit_routes.py      # Audit log access
│   ├── job_routes.py        # Job queue status
│   └── dev_routes.py        # Dev/test endpoints (DEV_ROUTES_ENABLED=true)
├── services/
│   ├── extraction_service.py     # Chunked LLM extraction, fact merging, reconciliation
│   ├── extraction_pipeline.py    # Orchestrates extraction + flag derivation
│   ├── pdf_service.py            # Pass 1/1.5/2 field filling, PDF stamping, combined_gap_fill
│   ├── form_service.py           # process_single_form(), schema loading
│   ├── alias_stamper.py          # NEW: deterministic alias-map stamping (Pass 1.5)
│   ├── naics_suggester.py        # NEW: NAICS/SIC candidate suggestion (Figure 20)
│   ├── fact_registry.py          # FACT_REGISTRY: canonical fact schema (~80 keys)
│   ├── cross_form_validator.py   # Cross-form business rule validation / hard stops
│   ├── ocr_service.py            # OCR provider abstraction
│   ├── s3_service.py             # S3 upload/download
│   ├── sqs_service.py            # SQS queue integration
│   ├── job_queue.py              # Multi-backend job queue (db/memory/file/sqs)
│   ├── arq_service.py            # ARQ workflow processing
│   ├── audit_service.py          # Audit logging
│   ├── auth_service.py           # Auth helpers
│   ├── cover_service.py          # Cover page generation
│   ├── email_service.py          # Resend email integration
│   ├── scheduler_service.py      # APScheduler background jobs
│   └── stripe_service.py         # Stripe billing logic
├── utils/
│   ├── llm_limiter.py       # Redis-distributed adaptive semaphore (cap=12, Redis TTL=180s)
│   ├── crypto.py            # Field-level encryption (FIELD_ENCRYPTION_KEY)
│   ├── table_extractor.py   # Table extraction (skips docs >40 pages)
│   ├── helpers.py           # Address parsing, misc
│   ├── concurrency.py       # Async helpers
│   ├── rate_limiter.py      # API rate limiting
│   ├── validators.py        # Input validation
│   ├── mime_validator.py    # File type validation
│   ├── virus_scanner.py     # Upload scanning
│   └── json_logging.py      # Structured JSON logging
├── forms_database/          # Form metadata JSON (17 forms + forms_index.json)
├── forms_schemas/           # ACORD field schemas JSON — READ ONLY, never modify
│                            # 17 files, 129–1135 fields each
├── forms_aliases/           # NEW: alias maps for Pass 1.5 (17 ACORD_xxx_alias.json)
├── scripts/
│   ├── generate_alias_maps.py    # Generated forms_aliases/ — run only if schemas change
│   ├── generate_fieldmaps.py     # Field map generation
│   ├── encrypt_facts_data.py     # Data migration: encrypt existing facts
│   ├── encrypt_signature_data.py # Data migration: encrypt existing signatures
│   └── rekey_encryption.py       # Encryption key rotation
├── templates/               # PDF templates
├── tmp/                     # Upload staging (auto-cleaned)
└── main.py                  # FastAPI app, startup validation, middleware

frontend/
├── src/
│   ├── components/
│   │   ├── form/            # AcordModal.jsx, PDFJsViewer.jsx (modified this session)
│   │   └── ...
│   ├── utils/
│   │   └── formatters.js    # (modified this session)
│   └── ...
└── vite.config.js
```

---

## Key Environment Variables

```bash
# LLM
LLM_MODEL=gpt-5.4-mini
GPT_MODEL=gpt-5.4-mini
LLM_REQUEST_TIMEOUT=300
OPENAI_MAX_CONCURRENT=8

# OCR
OCR_PROVIDER=google   # google | google_vision | vision (all mean Google Cloud Vision)

# Feature flags (new pipeline)
# NOTE: the 7 new-pipeline features (alias stamping, combined gap fill, display
# canonicalization, field QA, full-field reconciliation, evidence-gated fill,
# ACORD 101 overflow) are NO LONGER env vars — they are hardcoded `True` in
# backend/config/settings.py. Nothing to set in any environment.
ENABLE_SCHEDULE_CAPTURE=true           # Figure 15: bulk vehicle/driver/location/loss tables

# Job queue
JOB_QUEUE_BACKEND=db          # db | memory | local_file | sqs
ENABLE_ASYNC_PROCESSING=false

# Auth / Admin
ADMIN_EMAILS=vinaysharma@astreait.com
DEV_ROUTES_ENABLED=true       # NEVER true in production

# Limits
MAX_UPLOAD_SIZE_MB=50
MAX_FILES_PER_UPLOAD=10
SESSION_TTL_H=8
```

---

## Feature Flags Reference

### Always on — hardcoded in `backend/config/settings.py`, NOT env-configurable

These seven are part of the shipped pipeline. They are set to `True` in code so
no deployment has to configure them and no environment can turn them off. Their
legacy "off" paths survive at the call sites only as import-failure fallbacks.

| Constant | Effect |
|------|-----------------|
| `ENABLE_ALIAS_STAMPING` | Activates Pass 1.5: fills fields from alias maps without LLM |
| `ENABLE_COMBINED_GAP_FILL` | Stages 4-6: one shared gap fill instead of per-form LLM calls |
| `ENABLE_DISPLAY_CANONICALIZATION` | Standardizes date/currency/address/name/state display formatting on stamped values (non-destructive; raw value stays in the fact envelope) |
| `ENABLE_FIELD_QA` | Runs post-generation per-field QA (confidence threshold + source-fact agreement); surfaces fail/review items in the pre-download modal. Advisory only, never blocks or mutates |
| `ENABLE_FULL_FIELD_RECONCILIATION` | Extends the underwriting cross-document conflict picker to every scalar fact, not just the curated set |
| `ENABLE_EVIDENCE_GATED_FILL` | Figure 30/33, generalized: gates **every** gap-fill Yes/No answer on every form (compliance "…Question_*Code_*" fields, every `/Btn` checkbox regardless of topic, and any other field whose tooltip is the ACORD Y/N-entry convention) plus their paired "…Explanation"/"…OtherDescription"/"…ResolutionDescription" narrative, dropping either when not grounded in the uploaded document text |
| `ENABLE_ACORD101_OVERFLOW` | Figure 29: routes oversized operations/classification narrative + accumulated remarks in full to ACORD 101's Additional Remarks rows (lossless) |

### Still env-configurable

| Flag | Default | Effect when true |
|------|---------|-----------------|
| `ENABLE_PRODUCER_ANSWERS` | true | "Submit" on a recommendation card writes a producer-provenance fact and re-runs SQS/cross-form rules, instead of only dismissing. Set false to fall back to dismiss-only |
| `ENABLE_SCHEDULE_CAPTURE` | true | Figure 15: repeating-row fields (vehicles, drivers, locations, loss runs) collapse into ONE table question per schedule with CSV/XLSX import, row validation, duplicate detection and VIN decode - instead of one ordinal-labelled card per field. Default ON because the prior behaviour is the reported defect; set false to restore legacy per-field questions |
| `ENABLE_ASYNC_PROCESSING` | false | Returns 202 + runs jobs in worker.py background process |
| `DEV_ROUTES_ENABLED` | false | Enables dev/test endpoints |

---

## Critical Issues & Roadmap

**TL;DR of the 2026-07-16 Yes/No evidence-gate work (read the full entries below before touching
this area again):**
1. ACORD 126/140/25 schemas had every field tooltip truncated to 80 chars — compliance
   questions were cut off *before the actual question text*, so the AI was answering
   questions it couldn't read. Fixed: removed the truncation, regenerated those 3 schemas'
   tooltips from the template PDFs (tooltip text only, field definitions untouched).
2. One gap-fill call carrying 200+ fields made the model answer only ~27% of them. Fixed:
   field-level batching (`_FIELD_FILL_BATCH`=40).
3. Yes/No compliance questions buried in that general batch made the model default to "N"
   and borrow unrelated sentences as fake proof. Fixed: pulled them into their own dedicated
   pass (`_COMPLIANCE_SYSTEM_PROMPT`) with small batches (`_COMPLIANCE_BATCH`=10) and a
   Yes-only evidence-reuse cap (`_EVIDENCE_YES_QUOTE_REUSE_MAX`=1).
4. That dedicated pass initially only recognized ONE of ACORD's three Yes/No field
   conventions (a text-field tooltip shape), so it silently missed forms using a different
   shape — e.g. ACORD 133 had 0 of 38 real disclosure questions covered. Fixed: `_is_
   compliance_question` now recognizes all three (text-field, checkbox-pair, and
   high-impact disclosure checkbox), verified per-form against the real schemas — 15 of 17
   forms now route real questions through the dedicated pass (101 and 28 correctly have zero
   — neither has any genuine Yes/No disclosure question, verified not assumed).
- Net effect: false "N" flood and missed "Y" answers are fixed, generically across every
  form that has Yes/No compliance questions, not just ACORD 126; blank stays blank when the
  document doesn't address a question. Full details, exact numbers, and the one known
  residual (~2-3 borrowed false "N"s per run, an LLM limitation, not a bug) are in
  "Dedicated Compliance Yes/No Question Pass" and the two sections above it, below.

### NAICS/SIC Help Text Showed The Same Roofing Example To Every Business - FIXED (2026-07-21)
**Client report (Figure 20): the Form Assistant's answer about NAICS codes was praised for
reducing friction ("you can leave it blank"), with one ask - "for future versions, add
examples based on the detected business". Engineering note: "use retrieval/context to
generate suggested NAICS/SIC candidates with confidence, but keep them clearly marked as
suggestions until confirmed."**

Two of the five sub-requirements were already satisfied (the assistant explains the code in
plain English; the field is optional with a blank escape hatch). A third - the assistant
knowing anything about the business - was closed separately by the Figure 19 active-field
work (`_assistant_package_context` feeds it `BUSINESS` + `WHAT THE BUSINESS DOES`). The
remaining two are what this entry covers:

1. **The on-screen example was one hard-coded string.** `_FIELD_HINT_MAP["naics_code"]` read
   "e.g. '238160' for roofing contractors" and was shown verbatim to every applicant - a
   bakery, a law firm, a restaurant. Nothing was derived from the business.
2. **There were no candidates at all.** No suggestion mechanism, no confidence, no
   "unconfirmed until tapped" concept existed anywhere in the codebase.

**Fix - `services/naics_suggester.py` (new) + `_attach_classification_suggestions` in
`arq_service.py`, wired into all three question-generation paths.** A curated ~60-industry
table scores the business's own operations text (`operations_description`, falling back to
`certificate_description_of_operations` / `wc_description_of_operations` / `applicant_name` /
`dba_name`) by strong keywords (name the trade, +3) and weak ones (only support it, +1),
then ranks and rates confidence high/medium/low. The top candidate rewrites the hint to name
THAT business's code; the candidate list rides the question as `suggestions` and renders as
tappable chips in `ClientQuestionnaire.jsx`.

**Deliberately deterministic, not an LLM.** A NAICS code drives class assignment and rate;
a model inventing a plausible-but-nonexistent 6-digit code is exactly what the standing
"blank over wrong" rule exists to prevent (see `user-prefers-blank-over-wrong` memory). No
keyword match means NO suggestion - the fallback hint stays, reworded to be explicitly an
illustration of the format rather than a claim about this business. It also costs zero
tokens on an already-expensive path. Broadening coverage means adding rows to
`_INDUSTRIES`, not adding a model.

**Nothing is ever auto-filled.** The box ships empty; the client must tap a chip; tapping
shows "not confirmed - your agent will check it"; the assistant is handed the candidates
labelled `NOT confirmed` and is required to say they need agent confirmation. Verified live:
asked "is that definitely my code?" the assistant answered "No, not definitely."

**Two defects found during live testing, both fixed - read before touching this area:**
- **A third question serializer silently dropped the candidates.** There are THREE whitelists
  between generation and the client: `/generate` (passes questions whole), `send_arq` (line
  ~244), and `client_view` (line ~396). `hint` is a plain string that survived all three, so
  the personalized hint appeared on screen while the chips did not - the feature looked half
  broken with every backend test green, because the tests only covered generation. `send_arq`
  never copied `suggestions`, so nothing was ever stored. Both serializers now route it
  through one shared `_sanitize_suggestions()` helper (it was briefly two inline copies -
  that duplication is what caused the miss). `test_both_question_serializers_preserve_
  suggestions` fails the build if any serializer stops carrying it.
- **Keyword matching was blind to negation.** A full-service restaurant picked up a phantom
  "Bar or drinking establishment" candidate purely from the sentence *disclaiming* one
  ("There is no nightclub, no dance floor, and no live entertainment") - the word `nightclub`
  scored as evidence FOR a bar. Serious here because ACORD applications describe a risk as
  much by what they exclude ("no manufacturing is performed", "no vehicles are owned", "no
  work above three stories"). `_strip_negated_clauses` now drops clauses whose subject is
  negated, before scoring: clause-scoped (not sentence-scoped, since these disclaimers stack
  inside one sentence), splitting on punctuation but never on "and" (that would sever real
  multi-word trades like "heating and air conditioning"), with the cue required in the first
  4 tokens. It only ever REMOVES text, so it can cost a match but can never invent one.
  Confirmed a genuine bar ("operates a neighborhood bar and cocktail lounge serving liquor")
  still matches 722410 high.

**No feature flag.** Additive and fail-open at every layer: no match, no `suggestions` key,
and the questionnaire renders exactly as it did before. Every enrichment step is wrapped so
a failure can never break question generation.

**Verified end-to-end against the live app with three documents** (not just unit tests):
a roofing contractor (238160/1761, high), a full-service restaurant (722511/5812, high -
the decisive test, since a roofing doc alone cannot distinguish "derived" from
"hard-coded"), and an unrecognizable trade (mobile falconry-based bird abatement - correctly
produced NO chips and no invented code). Tests: `backend/tests/test_naics_suggester.py` (43).
Full suite 800 passed / 2 failed, the same two pre-existing unrelated failures
(`test_arq_acord125_missing_only` - the known `httpx`/`openai` version conflict - and
`test_normalization`), zero regressions.

**Known limitation, accepted:** the table covers ~60 common commercial-lines industries.
An obscure trade gets no suggestion by design. Ask Brent which trades matter to his book
before extending `_INDUSTRIES`.

### Fleet Questionnaire Exploded Into One Card Per Field - FIXED (2026-07-21)
**Client report (Figure 15): the "Send to Client" list showed "Please provide the following
details for this vehicle ... (141th vehicle)" repeated for the 141st, 142nd, 143rd ... entry.**
Three separate defects, all fixed:

1. **One question per repeating FIELD.** `generate_arq_questions` turned every empty
   repeating-row field into its own question and labelled it with a running counter
   (`_group_label` + `_ordinal`). The counter incremented per FIELD, not per vehicle, so
   "141th vehicle" was really "the 141st vehicle-related box" - the number was meaningless as
   well as unusable. Fixed by `services/schedule_capture.py` +
   `_partition_schedule_fields` / `_build_schedule_questions`: schedule-backed fields are
   pulled out of the per-field flow and replaced by ONE `field_type: "schedule"` question
   carrying a column spec, rendered as an editable table
   (`frontend/src/components/arq/ScheduleTable.jsx`) with CSV/XLSX import
   (`frontend/src/utils/scheduleImport.js`, parsed in-browser via the existing `jszip` dep -
   no new dependency, no upload endpoint), per-cell validation, composite duplicate
   detection, and NHTSA vPIC VIN decode (proxied via `POST /api/arq/decode-vin`).
2. **`_ordinal` was wrong above 10.** It held a literal list for 1-10 and fell back to
   `f"{n}th"`, producing the "141th" in the screenshot. Now correct for any n.
3. **The vehicle schedule could never stamp its identity columns.** `_SCHEDULE_REGISTRY`
   mapped `Vehicle_VIN` / `Vehicle_Make` / `Vehicle_Model` / `Vehicle_BodyStyle` - base names
   that exist in NO real ACORD schema. The names ACORD 127 actually uses
   (`Vehicle_VINIdentifier`, `Vehicle_ManufacturersName`, `Vehicle_ModelName`,
   `Vehicle_BodyCode`) were unmapped, so `extraction_service` extracted VIN/make/model into
   `auto_vin_schedule` and they had nowhere to land - only `year` and `gvw` ever stamped.
   This is the SAME class of bug already fixed for drivers (see
   `tests/test_driver_schedule_mapping.py`); vehicles were missed. Fixed additively (the dead
   aliases are retained, harmless).

**Audit result worth knowing:** 50 of 87 `_SCHEDULE_REGISTRY` entries match no real schema
field. Six schedules (`wc_class_codes`, `wc_officers`, `underlying_policies`,
`prior_coverage_by_line`, `inland_marine_items`, `additional_named_insureds`) have ZERO live
bindings, so a capture table for them would silently discard input. They are deliberately NOT
defined in `SCHEDULE_DEFS`; only the four with live bindings are (vehicles, drivers,
locations, loss history). `test_every_schedule_column_binds_to_a_live_acord_field` fails the
build if a column is ever added without a real ACORD binding. Mapping the remaining six is
the obvious follow-up.

**Data path:** schedule answers ride the EXISTING answer pipeline as JSON under a reserved
`schedule::<list_key>` key (no DB column, no new answer plumbing). `arq_routes._sanitize_answers`
special-cases them so they escape the `str(v)[:500]` clamp that would have truncated a fleet
to two vehicles. On apply they are written to `facts[list_key]` and stamped by the same
resolver Pass 1 uses. The agent can pre-load a schedule before sending
(`GET/PUT /api/arq/schedules/{session_id}`, provenance `producer`); the client edits on top
(provenance `client_arq`). Rows beyond the form's 14-row physical capacity are retained in
facts and surfaced as an overflow notice rather than silently dropped.

Tests: `backend/tests/test_schedule_capture.py` (33). Full suite 672 passed / 3 failed, versus
baseline 608 passed / 3 failed at HEAD - the same three pre-existing failures
(`test_arq_acord125_missing_only`, `test_download_gate`, `test_normalization`), zero
regressions.

### Active Performance Bug (Priority #1)
**Combined gap fill is slow (17+ minutes for 3 forms).**
Three specific bugs in `backend/services/pdf_service.py`:

1. No `max_tokens` cap in `_call_llm_sync()` → model returns ~174k output tokens per call,
   instantly saturating the 200k TPM OpenAI limit.
   Fix: add `max_tokens=_FORM_FILL_MAX_TOKENS` (16000) to the `create()` call.

2. Parallel chunk dispatch breaks progressive narrowing + causes 429 floods.
   Fix: change `_chunk_pool_size = min(len(raw_chunks), 4)` to
   `_chunk_pool_size = 1 if len(field_list) > 200 else min(len(raw_chunks), 4)`

3. 1531 fields → 612k char fields block → only 33k chars for raw text → 22 chunks.
   Fix: in `combined_gap_fill()`, batch fields into groups of 100 and truncate
   raw text to first 160k chars (declarations pages only).
   Full code in `CHANGES_THIS_CHAT.txt`.

Expected result after fix: 17 minutes → 3–4 minutes.

**Status note (2026-07-10):** items 1 and 2 above are already implemented in current code
(`max_completion_tokens=_FORM_FILL_MAX_TOKENS` in `_call_llm_sync()`; `_chunk_pool_size = 1
if (len(field_list) > 200 or _is_combined_batch) else min(...)`). Item 3's field-batching
is done via `_COMBINED_FIELD_BATCH` (200/batch), but the "truncate raw text to 160k chars"
half was deliberately NOT implemented — full-document chunking is used instead so no text
is dropped. See the repeating-group bug below for a newly-found root cause of the
"~400 chars/field" bloat this section cites.

### PDF Text Extraction Can Scramble Label/Value Pairs — FIXED (2026-07-11)
**Was the root cause of carrier/agency swaps and address bleeds into unrelated fields.**
`services/ocr_service.py::_pdfplumber_extract()` called `page.extract_text()` with no
layout mode. On a two-column dec page (labels in one column, values in another) whose row
heights drift even slightly between the two columns, pdfplumber's default reading order
interleaves the wrong label with the wrong value — e.g. "CARRIER: 84-2210987" (the FEIN)
instead of the real carrier name.

Confirmed by direct A/B test (2026-07-10): identical source content, submitted once as a
clean `.txt` and once as an equivalent two-column PDF. The `.txt` run filled carrier,
policy #, effective date, all 6 limits, and both Y/N explanation fields correctly. The PDF
run produced a carrier/agency swap, an address bled into an unrelated Additional Interest
block, and blank limits/dates — same code, same flags, only the input format differed.

**Both originally-proposed fix candidates were tested and REJECTED** — `extract_text
(layout=True)` and Google Vision's `document_text_detection` both reproduce the identical
wrong pairing on a drifted two-column layout. Neither understands semantic label/value
correspondence; both just impose a different global reading order.

**Actual fix — scoped column-reflow recovery**, in `ocr_service.py` (`_extract_page_text_smart`,
`_reflow_two_column_words`, `_cluster_words_into_lines`, wired into `_pdfplumber_extract`):
1. Detect the corruption by its fingerprint — a meaningful fraction of lines are a bare
   label with nothing after it on the same line (`"Legal Entity:"` alone), which a
   correctly-paired document essentially never produces.
2. If absent, return `extract_text()` unchanged — zero risk to normal documents.
3. If present, isolate the y-band containing the scrambled lines only (via
   `page.within_bbox()`), split that band's words into two x-clusters at the largest
   horizontal gap, and pair lines by ORDINAL position within each column (not by matching
   absolute y-coordinates, which is what breaks under drift).
4. Content above/below that band (a heading, an unrelated table further down the same
   page) is extracted normally and spliced back in untouched.
5. If the reflow doesn't actually reduce the bare-label count, fall back to default
   extraction rather than ship a guess.

Verified against 4 cases before shipping: the original scrambled repro (fixed), a normal
single-column paragraph (byte-identical to default), a genuine 3+ column table alone
(byte-identical to default — the critical false-positive guard), and a composite page with
a scrambled identity block AND a real table on the same page (identity block fixed, table
untouched — the critical regression guard). Full backend suite (440 tests) run before and
after with zero new failures. Regression tests: `backend/tests/test_ocr_column_reflow.py`.

### Evidence Gate Only Covered ~8 Forms' Compliance Questions, Not Every Yes/No Field — FIXED (2026-07-15)
**Client requirement: "in all the forms... certain fields where Y/N/Yes/No to be filled...
only fill if we found concrete evidence... if yes, add explanation in the adjacent field;
if no, no explanation needed."** `ENABLE_EVIDENCE_GATED_FILL` (Figure 30) already did exactly
this, but only for fields matching the `_Question_<code>Code_` naming convention — the
compliance-question family on 8 forms (125/126/127/130/131/141/160/186). A prior session
(Figure 33 audit) had already extended it to the auto ownership/HNOA checkbox pairs on
137/138 that lack that name. Neither covered the other 1500+ `/Btn` checkbox fields across
all 17 schemas (sink hole, mine subsidence, building improvements, entity type, LOB
selection, ...) or the `/Tx` "Enter Y for a Yes response..." text-field convention used on
forms like 140/25 that don't use `_Question_Code_` naming at all — a gap-fill hallucination
on any of those shipped to the PDF completely unchecked.

**Fix — `services/pdf_service.py`:** a new `_is_yes_no_field(field, schema)` recognizes a
Yes/No field via three schema-driven signals (any one sufficient): the `_Question_<code>
Code_` name pattern, `ft == "/Btn"` (any checkbox, not just high-impact ones), or a tooltip
starting with the ACORD "Enter Y for a "Yes" response..." boilerplate. The evidence-gate
Pass A/B logic (`_is_gated_field` inside `map_facts_to_form`) now delegates to it instead of
name-matching alone, and the gap-fill prompt's rule 8 now asks for a grounding quote on
every such field, not just Question-code/high-impact ones (the two sides must move
together — the gate blanks anything ungrounded, so the prompt must actually ask for
grounding wherever the gate now checks for it, or every newly-covered field would get
wiped). `_question_explanation_pairs` (the "…Explanation"/"…OtherDescription" adjacency
pairing) was separately broadened to include `/Btn` checkboxes — this is exactly the very
common ACORD `"…OtherIndicator_<row>"` → `"…OtherDescription_<row>"` convention ("Other"
checked → please specify), present on 10+ forms and previously invisible to this function.

**Deliberately did NOT** extend pairing to the tooltip-only signal: auditing all 17 real
schemas found 2 cases (out of 175 candidate pairs) where a `/Tx` Yes/No field by tooltip
convention sits directly before an unrelated `Explanation`/`OtherDescription` field from a
different form section — a checkbox's PDF layout position is a stronger structural signal
than an arbitrarily-ordered text field's, so pairing trusts `_Question_Code_` naming and
`/Btn` type but not the broader tooltip signal (which is still used to gate that field's own
answer, just not to pair it with a neighbor). Deterministic Pass 1 / alias-stamped values are
untouched either way — this only ever governs what the gap-fill LLM guesses.

Verified against the real schemas (not just synthetic test fixtures): confirmed the fix adds
69 legitimate pairs across 6 forms that previously had zero pairing coverage (140/186/28),
and confirmed both known-bad coincidental adjacencies are excluded by name. Full backend
suite (556 tests) run before and after with zero new failures (2 pre-existing, unrelated
failures: an `openai`/`httpx` version conflict and an unrelated `normalize_general` gap).
Regression tests added to `backend/tests/test_raw_text_verification.py`.

### Quote-Reuse Cap Missed Reworded Boilerplate — FIXED (2026-07-15), One Residual Limitation Accepted
**Live client report:** a real ACORD 126 test document (which addresses only ~2-3 of ~22
General Information Yes/No questions) came back with ~20 of 22 stamped "N", each "grounded"
by the gap-fill model reusing one of the only 1-2 real negation sentences in the document.
The evidence gate's reuse cap (`_quote_use_count` in `map_facts_to_form`) only ever counted
**exact** normalized-string matches — sufficient when the model quotes the same sentence
verbatim, but the model does not need to: reworded slightly each time ("no parking facilities
owned or rented" vs "parking facilities are not owned or rented by the applicant" vs "the
applicant does not own or rent any parking facilities"), each rewording hashed to a different
key and never reached the reuse threshold. Reproduced directly against the real model to
confirm the mechanism before touching any code.

**Fix — `services/pdf_service.py`:** the reuse cap now clusters grounding quotes by
token-Jaccard near-duplicate similarity (`_sim_tokens` / `_is_near_duplicate_text`) instead of
exact string match — the same technique Guard 4 already uses for cross-field boilerplate
bleed on mapped explanation *values*, applied here to grounding *quotes*. This compares
quote-to-quote similarity, never quote-to-question topic, so it does not reopen the standing
"no topic/keyword matching" rule (see evidence-gate-design memory). The threshold was also
tightened from ">2 reuses allowed" to ">1" given the demonstrated severity — two different
fields citing the identical quote is already more likely "one real answer plus one borrowed
one" than two genuinely distinct facts sharing a citation, and per the standing "blank over
wrong" product preference, collapsing a rare genuine double-use to blank/ARQ is the correct
failure mode. Verified: a 5-variant reworded-reuse repro that previously let 3 of 5 survive
now lets at most 1 through; a lone, genuinely unique, once-cited answer is confirmed
unaffected (no new false negatives from the tightened threshold in isolation).

**Residual, deliberately accepted limitation:** re-running the full real end-to-end
reproduction after the fix (both ACORD 126 and 127, real model calls, not synthetic) confirmed
a large improvement (126: ~26 of 30 Question-code fields now correctly blank, vs ~28 of 30
wrongly answered before) but also surfaced a *different*, smaller failure mode the reuse cap
cannot touch: in a large batch of similarly-shaped Yes/No questions, the model occasionally
attaches a real, present, correctly-negation-shaped quote to the **wrong** question entirely
(e.g. citing "none are leased or borrowed" as proof for "is there a vehicle maintenance
program?" instead of "are any vehicles not solely owned by the applicant?"). The quote is
genuine and grounded - the model just mis-attributed it. This cannot be detected without
comparing the quote's *topic* to the *question's* topic, which is exactly the heuristic three
prior sessions already tried and found causes worse regressions (blanking legitimate answers
phrased differently from their question - see evidence-gate-design memory). Accepted as a
known trade-off consistent with this codebase's established design philosophy, not silently
ignored. A real fix would mean isolating each Yes/No question (or small groups) into its own
LLM call so the model has less to conflate - a materially larger, costlier change that cuts
against the already-documented Active Performance Bug priority (fewer calls, not more) and
was deliberately left for a separate decision rather than bundled into this fix.

Full backend suite (576 tests) run before and after with zero new failures (same 2
pre-existing, unrelated failures as above). Regression tests added to
`backend/tests/test_raw_text_verification.py`.

**UPDATE 2026-07-16 — the reuse cap's `>1` threshold was REVERSED to a generous,
env-tunable `_EVIDENCE_QUOTE_REUSE_MAX` (default 12).** The aggressive `>1` cap was
compensating for the tooltip-truncation root cause below; once that was fixed the cap
began blanking *correct* answers and was relaxed. See the next section — read it first.

### ACORD 126/140/25 Came Back Blank/Wrong Because Their Schema Tooltips Were Truncated to 80 Chars — FIXED (2026-07-16)
**This was the real root cause behind "lots of N/blank/broken" on ACORD 126 Yes/No fields —
not the evidence gate, which several prior sessions kept tuning.** Schema extraction
(`_collect_fields_pikepdf`, `pdf_service.py`) truncated every field's `/TU` tooltip to
`[:80]` chars, and that truncated text was baked into the cached
`forms_schemas/ACORD_126_schema.json` (also 140 and 25 — the three forms whose JSON
`max_tu` == 80). The compliance-question tooltip format is
`"Enter Y for a "Yes" response. Input N for "No" response. The response to the question,
"<ACTUAL QUESTION>"?"` — the boilerplate preamble alone is ~85 chars, so an 80-char cut
severed the tooltip **before the actual question text ever began**. The gap-fill LLM was
being asked to answer compliance questions it literally could not read (it saw only
"…The response to the que"), so it guessed — mostly "N", or wrong. The ACORD template PDFs
themselves hold the full text (max /TU ~300-570 chars); only our extraction dropped it.
A SECOND truncation compounded it: the prompt builder (`_field_spec` / `_slot_group_block`)
re-cut every tooltip to `[:80]` even for the 14 forms whose JSON *had* full tooltips, so
those forms' question text never reached the model either.

**Fix — three parts:**
1. `_collect_fields_pikepdf` now stores the full tooltip (cap `_SCHEMA_TOOLTIP_MAX`=1000).
2. The prompt builder now shows up to `_PROMPT_TOOLTIP_MAX`=500 chars (was 80), so the
   full question text reaches the model for **all** forms.
3. Regenerated `ACORD_126/140/25_schema.json` from their template PDFs, updating **only**
   the `tu` values (field set, order, `ft`, `required` preserved byte-for-byte; 100% field
   match, verified). This is a data *repair* of a generation-time truncation, not a change
   to ACORD field definitions — the "never modify forms_schemas" rule is about the field
   structure, which is untouched.

**Second fix — field-level batching for completion (`_fill_unmatched_with_gpt`).** Even
with readable tooltips, a single gap-fill call carrying 200+ heterogeneous fields made the
model answer only ~27% of them (it silently drops fields it *could* fill). The field list
is now split into focused sub-batches of `_FIELD_FILL_BATCH` (40), dispatched with bounded
parallelism (`_FIELD_BATCH_POOL`=4, llm_limiter is the TPM backstop); each sub-batch owns
local accumulators and merges cleanly (sub-batches are disjoint). `_absorb` was refactored
to take its accumulators as params for thread-safety. The old within-call parallel-chunk
machinery (`_chunk_pool_size`/`_is_combined_batch`) is replaced by this; raw-text chunks
within a sub-batch stay sequential (progressive narrowing preserved).

**Result (real model, full 255-field ACORD-126-alone pipeline, not synthetic):** grounded
Yes/No completion went from ~0 correct → **13 of 15** representative watch questions correct
(install=Y+explanation, R&D=N, guarantees=Y+explanation, blasting=N, medical=N,
radioactive=N, hazmat=Y+explanation, watercraft=N, parking=N, recreation=N, day care=N,
safety=Y+explanation). Raw model completion rose 33 → ~90+ of 205 fields. Two residual
edge cases (NOT systemic): one question got a wrong "Yes" from a model misreading a quote
that actually supports "No" (a model-comprehension error, undetectable without the forbidden
quote-topic matching), and one legitimate "No" whose only proof is a positively-phrased
requirement ("subcontractors are *required* to submit a COI" → answer to "allowed *without*
COI?" is No) is blanked by the negation-cue check — the safe direction (blank over wrong),
left for ARQ.

### Dedicated Compliance Yes/No Question Pass — ADDED (2026-07-16)
**The general 200-field fill prompt buried the ~40 Yes/No underwriting questions among
hundreds of heterogeneous fields, so the model defaulted them to "N" and borrowed unrelated
negative sentences as fake proof (the false-"N" flood reported on real ACORD 126 tests).**
Yes/No questions (tooltip begins with the ACORD "Enter Y for a Yes response…" convention —
Question-code fields + …YesNoCode_ text fields; generic /Btn checkboxes are excluded) are
now pulled OUT of the general fill and answered by a dedicated pass in
`_fill_unmatched_with_gpt`:
- `_COMPLIANCE_SYSTEM_PROMPT` — a focused prompt whose entire job is answer-or-omit, with
  hard rules: silence≠"N", never borrow a subject-A sentence for a subject-B question, every
  Y/N needs a quote specifically about THAT subject, never reuse a quote, detect YES by
  meaning (fixed the hazmat case that used to come back "N" with a hazmat explanation), read
  negatively-phrased questions carefully.
- **Small batches** (`_COMPLIANCE_BATCH`=10, bounded-parallel): all ~40 in one call makes the
  model rush and borrow; ~10 per call it reads each carefully and omits the unaddressed ones.
  This was the single biggest lever against false "N"s.
- **Yes-only reuse cap** (`_EVIDENCE_YES_QUOTE_REUSE_MAX`=1): a genuine "Yes" has its own
  unique sentence; a "Yes" whose quote is shared with another question is a borrow → blanked.
  The shared quote's other use is usually a "No", so this kills false "Yes"es (foreign
  products, vendors coverage) with zero collateral on legitimate ones. Negatives keep the
  generous `_EVIDENCE_QUOTE_REUSE_MAX` (a broad negation may truly answer several exposures).
- **Gate is not authoritative over the pass:** Pass B "rescue a stranded grounded Yes" no
  longer promotes a compliance question the pass deliberately left blank to "Y" from a stray
  explanation the general fill wrote (that had manufactured a false "Yes").

**UPDATE 2026-07-16 — generalized to all 17 forms, not just ACORD 126 (client explicitly
asked: "i need it generic").** Initial ship only recognized the "Enter Y for a Yes
response…" TEXT-field convention, so it silently covered only the forms happening to use
that shape. Audited every form's actual schema (not assumed) and found two more real gaps,
both now fixed in `_is_compliance_question` inside `_fill_unmatched_with_gpt`:
1. **Checkbox-PAIR compliance questions** — same convention, expressed as two `/Btn` fields
   (`..._Question_<code>YesIndicator_A` / `..._NoIndicator_A`) with tooltip "Check the box
   (if applicable): Indicates a "Yes"/"No" response to the question, "<Q>"". Present on
   125/126/127/130/131/**133**/141/160/186 — ACORD 133 specifically had ZERO fields caught
   by the text-field convention (0 of 121 unmatched fields) despite having 38 genuine
   disclosure questions (prior WC coverage, unpaid premium disputes) that were reaching the
   general fill completely unprotected. Detected via the tooltip marker `"response to the
   question,"`, which is present in both the text and checkbox-pair shapes.
2. **High-impact disclosure checkboxes without that tooltip wording** — hired/non-owned
   auto, leasing, hazardous materials, maintenance program on ACORD 137/138 (already
   detected via the existing `_is_high_impact_checkbox_field`, now wired into the pass
   selector too, not just the gate).
   Deliberately NOT extended to every `/Btn` checkbox: audited a real checkbox-heavy form
   (ACORD 137_CA, 391 unmatched fields, 192 of them `/Btn`) and found only 46 are genuine
   disclosure questions — the rest are coverage-SELECTION checkboxes ("which auto symbol
   applies", "is this agreed-amount valuation") that are a different risk category (usually
   Pass-1/alias-resolved, and not what caused the false-N bug); routing all 192 would waste
   ~14 extra LLM calls per form for zero benefit.

`_compliance_question_text` was also tightened to stop at the question's own "?" — the
checkbox-pair tooltip often has trailing instructional text about A DIFFERENT field
immediately after the question ("...state?". As used here, if there was no prior coverage,
indicate why by checking..."), which must not be presented to the model as part of the
question itself.

**Coverage after the fix, form-by-form (unmatched fields routed to the dedicated pass vs
total unmatched, computed from the real schemas with `compute_form_gaps`):**
125=21, **126=48**, 127=44, 130=24, 131=22, **133=38 (was 0)**, 137_CA=46, 137_CO=46,
138_CA=7, 138_CO=7, 140=8, 141=50, 160=48, 186=88, 25=12. **101=0 and 28=0 are correct, not
gaps** — 101 is a narrative "no loss" statement form with no Y/N questions at all; 28's
`/Btn` fields are 100% coverage-existence/election flags ("does Building Coverage apply"),
not disclosure questions, same category as the auto-symbol selections above.

Verified end-to-end against the real model on ACORD 133 (a workers-comp form, structurally
unrelated to 126) with a fresh scenario (never previously carried WC coverage, no premium
disputes) — both checkbox-pair questions answered "No" correctly with no Yes/No
contradiction on either pair. Full backend suite (582 tests) green before and after (same 2
pre-existing unrelated failures).

**Result (real model, full ACORD 126, temp 0):** all "Yes" answers correct with no false
positives; hazmat correctly "Y"; the ~10 completely-unaddressed questions the client listed
(excavation, joint ventures, labor interchange, demolition, social events, operations sold,
products recalled, …) now correctly BLANK instead of false "N". **Residual, honestly
documented:** ~2-3 borrowed false "N"s still slip through per run (the model cites a real
negation sentence about a different subject; a "No" sharing a broad negation is
indistinguishable from a borrow without the forbidden quote-topic matching), and they jitter
run-to-run because the real API is not perfectly deterministic at temp 0. A couple correct
"No"s are also blanked by the negation-cue check or omitted by the model. Knobs to tune:
`COMPLIANCE_BATCH`, `EVIDENCE_QUOTE_REUSE_MAX`, `EVIDENCE_YES_QUOTE_REUSE_MAX`. A future
LLM-as-judge verification pass could cut the residual borrows further at the cost of one
extra call — deliberately not added yet (diminishing returns vs added latency/complexity).

### Gap-Fill Prompt Wraps Every Single-Row Field as a Fake "Repeating Group" — FIXED (already in code)
NOTE (2026-07-16): this is **already implemented** — `_build_user_prompt` routes a field
through `_slot_group_block()` only when `len(_base_to_slots[base]) > 1`; singletons fall
through to `_field_spec()`. The "not yet fixed" note below is stale; kept for history.

### Gap-Fill Prompt Wraps Every Single-Row Field as a Fake "Repeating Group" (Priority #2 — perf/cost, HISTORICAL)
`_ROW_SUFFIX_RE` in `pdf_service.py::_fill_unmatched_with_gpt()` matches any field ending
in `_A`–`_N` and renders it via `_slot_group_block()` — "REPEATING GROUP … RULE: find N
distinct values … leave null if fewer distinct values exist than expected" — even when
that field has zero siblings (no `_B`, `_C`, …). Because ACORD's schema convention suffixes
nearly every field with a row letter, most fields get this treatment regardless of whether
they're a real schedule row or a one-off narrative field.

Measured on a real ACORD 126 gap-fill prompt: 156 of 181 "REPEATING GROUP" blocks were fake
1-slot groups. Rendering those as plain single-line specs instead would cut that prompt
from 114k to an estimated ~78k chars (~30% waste) — very likely the dominant contributor to
the "~400 chars/field" figure the Active Performance Bug section above cites for the 612k
char field-block problem.

Fix (surgical, not yet applied): in the `active_groups` partition inside
`_build_user_prompt()`, only route a field through `_slot_group_block()` when
`len(_base_to_slots[base]) > 1`; singletons should fall through to the plain
`_field_spec()` line. Real multi-row groups are unaffected.

### Security / Compliance Gaps (before production)
- Field-level encryption is implemented (`utils/crypto.py`) but may not be applied everywhere
- Audit logging exists (`audit_service.py`) but coverage is incomplete
- No staging environment — localhost only

### No Automated Tests
- Zero test coverage; all testing is manual
- Needed before any production launch

### SQS / ARQ Async Processing
- `ENABLE_ASYNC_PROCESSING=false` — background job processing via SQS not in active use
- Job queue runs DB-backed synchronously for now

### Deployment
- Localhost only — no Docker, no cloud deploy, no CI/CD

---

## Key Architectural Decisions

**What's working well:**
- Chunked LLM extraction with adaptive semaphore (handles large docs cleanly)
- Feature-flag gated new pipeline (safe to deploy without breaking anything)
- Multi-backend job queue abstraction (easy to swap to SQS later)
- Schema-driven ACORD forms (reusable, all 17 forms consistent)
- Google Cloud Vision OCR (replaced Textract — more reliable)

**Known workarounds:**
- `groq_chat()` function name is kept for backwards compatibility but actually calls OpenAI
- AWS services (S3, SQS, Textract) are wired but not actively used in current deployment
- `MONGO_URI` in .env is unused — PostgreSQL is the actual database

---

## Notes for Future Contributors

- **Never modify `forms_schemas/*.json`** — these are permanent ACORD field definitions.
- **`forms_aliases/` was generated** by `scripts/generate_alias_maps.py` — do not hand-edit.
- **The 7 new-pipeline feature constants are hardcoded `True`** in `config/settings.py` —
  they are not env vars, so don't add them to any `.env` or deployment config.
  Remaining flags (`ENABLE_SCHEDULE_CAPTURE`, `ENABLE_PRODUCER_ANSWERS`,
  `ENABLE_ASYNC_PROCESSING`, `DEV_ROUTES_ENABLED`) are still env-driven.
- **Data is sensitive:** PII, insurance claims, financial data, signed documents.
  Any change touching facts, form output, or signatures needs a security review.
- **Ask Brent** about compliance requirements before any data-handling changes.

## Database Schema Conventions

**Single source of truth: `backend/config/database.py::init_db()`.** It runs
automatically on every app startup (`main.py`'s `@app.on_event("startup")` calls
`await init_db()`) and is fully idempotent — safe to run against an empty database
or one that already has the tables/columns.

When adding a new table or column, edit `init_db()` only, using this exact pattern:

1. **New table:** add a `CREATE TABLE IF NOT EXISTS ...` block with the complete
   column list (as if creating it fresh).
2. **New column on an existing table:** add it to the `CREATE TABLE IF NOT EXISTS`
   block above (so a brand-new database gets it immediately) **AND** add a matching
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` statement (so an existing database
   picks it up on next restart, no manual migration step). See the `users` table's
   `for col, definition in [...]` loop and the `acord_audit_log` entries in the
   `for stmt in [...]` list near the bottom of `init_db()` for the established style.

This is what makes the schema **portable**: point `DATABASE_URL` at any empty
Postgres instance and start the app — `init_db()` builds the entire schema with no
separate migration command required. Never require a manual step to stand up a new
environment.

**Do not use `backend/migrate.py` or `backend/alembic/` for new schema changes.**
Both exist in the repo but neither runs automatically at startup (confirmed: only
`init_db()` is called from `main.py`) — they are legacy/inactive paths. Adding a
column there will not reach a real deployment.

## UI / Copy Rules

- **No em-dashes (`—`) in UI text.** Use a plain hyphen-minus (`-`) instead. This applies to all labels, titles, banners, tooltips, and inline copy throughout the frontend.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
