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
ENABLE_ALIAS_STAMPING=true    # Pass 1.5 deterministic alias fill
ENABLE_COMBINED_GAP_FILL=true # Stages 4-6 shared LLM gap fill

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
| `ENABLE_ASYNC_PROCESSING` | false | Returns 202 + runs jobs in worker.py background process |
| `DEV_ROUTES_ENABLED` | false | Enables dev/test endpoints |

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
