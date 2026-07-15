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

### Stage 3 (Pass 1.5) — Alias Stamping  ← NEW (feature-flagged)
`services/alias_stamper.py` loads 17 alias maps from `backend/forms_aliases/`.
Each alias map: `{ACORD_field_name: canonical_snake_case_name}`.
A bridge dict (`CANONICAL_TO_EXTRACTION`, 24 entries) maps canonical names → extraction fact keys.
Fills additional fields deterministically. Gated by `ENABLE_ALIAS_STAMPING=true`.

### Stage 4-6 (Pass 2) — Combined Gap Fill  ← NEW (feature-flagged)
`pdf_service.py → combined_gap_fill()` + `compute_form_gaps()`.
Deduplicates unmatched fields across ALL selected forms, runs ONE shared LLM pass,
distributes results back to each form. Gated by `ENABLE_COMBINED_GAP_FILL=true`.

**Without flags:** Each form gets its own LLM gap-fill call (old behavior, still works).
**With flags:** Shared extraction → alias stamp → one combined gap fill.

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
ENABLE_ALIAS_STAMPING=true             # Pass 1.5 deterministic alias fill
ENABLE_COMBINED_GAP_FILL=true          # Stages 4-6 shared LLM gap fill
ENABLE_DISPLAY_CANONICALIZATION=true   # Clean/standardized display formatting
ENABLE_FIELD_QA=true                   # Post-generation per-field QA + review surfacing
ENABLE_FULL_FIELD_RECONCILIATION=true  # Cross-document conflict picker for every field
ENABLE_EVIDENCE_GATED_FILL=true        # Figure 30/33: drop ungrounded Y-N/narrative answers, all forms
ENABLE_ACORD101_OVERFLOW=true          # Figure 29: overflow narrative to ACORD 101

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

| Flag | Default | Effect when true |
|------|---------|-----------------|
| `ENABLE_ALIAS_STAMPING` | false | Activates Pass 1.5: fills fields from alias maps without LLM |
| `ENABLE_COMBINED_GAP_FILL` | false | Stages 4-6: one shared gap fill instead of per-form LLM calls |
| `ENABLE_DISPLAY_CANONICALIZATION` | false | Standardizes date/currency/address/name/state display formatting on stamped values (non-destructive; raw value stays in the fact envelope) |
| `ENABLE_FIELD_QA` | false | Runs post-generation per-field QA (confidence threshold + source-fact agreement); surfaces fail/review items in the pre-download modal. Advisory only, never blocks or mutates |
| `ENABLE_FULL_FIELD_RECONCILIATION` | false | Extends the underwriting cross-document conflict picker to every scalar fact, not just the curated set |
| `ENABLE_EVIDENCE_GATED_FILL` | false | Figure 30/33, generalized: gates **every** gap-fill Yes/No answer on every form (compliance "…Question_*Code_*" fields, every `/Btn` checkbox regardless of topic, and any other field whose tooltip is the ACORD Y/N-entry convention) plus their paired "…Explanation"/"…OtherDescription"/"…ResolutionDescription" narrative, dropping either when not grounded in the uploaded document text |
| `ENABLE_ACORD101_OVERFLOW` | false | Figure 29: routes oversized operations/classification narrative + accumulated remarks in full to ACORD 101's Additional Remarks rows (lossless) |
| `ENABLE_PRODUCER_ANSWERS` | true | "Submit" on a recommendation card writes a producer-provenance fact and re-runs SQS/cross-form rules, instead of only dismissing. Set false to fall back to dismiss-only |
| `ENABLE_ASYNC_PROCESSING` | false | Returns 202 + runs jobs in worker.py background process |
| `DEV_ROUTES_ENABLED` | false | Enables dev/test endpoints |

**All 5 flags above marked default `false` but effectively on in this deployment are set `true` in `backend/.env`** (see the env var block above) — the table default is what a fresh environment gets without that file.

---

## Critical Issues & Roadmap

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

### Gap-Fill Prompt Wraps Every Single-Row Field as a Fake "Repeating Group" (Priority #2 — perf/cost, not yet fixed)
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
- **Feature flags default to false** — old pipeline behavior is always the fallback.
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
