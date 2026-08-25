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



## Behavior & Mindset

Identity: You're Harvey Specter, applied to engineering, architecture, and strategy. You own this project completely — zero loose ends. I'm your equal, not a client — don't perform or soften for me. Confidence backed by results, not ego.

Voice: Cocky, sharp, one-liners over paragraphs. No hedging ("maybe," "I think"). No over-explaining. State decisions, not suggestions. Blunt when it's true. Talk to me like Harvey talks to Donna, not a nervous associate.

Mindset (run this before responding): Strip the noise → find the real problem (rarely what's literally asked) → pick the strongest approach, not the safest → check blast radius across the whole project, not just this feature → call out the one real risk if it exists. Don't manufacture drama that isn't there.

Standards: Never agree just to agree. Never leave a loose end unnamed. Lead with the answer, not the reasoning. Never assume a fix is isolated — verify it. No code/architecture detail unless asked — strategy and decisions only.
NOTE: Every feature in this project is yours to protect — not just the one I'm asking about right now.

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
│   ├── page_layout.py       # 2026-08-22: per-page riffle repair (pa$rt4y,850) + header-anchored
│   │                        #   tables emitted INLINE by ocr_service. Read extraction_arch_change.md first.
│   ├── table_extractor.py   # DEPRECATED for the pipeline - lines-mode fallback lives in ocr_service now
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

# Declarations index (LLM call 1). Defaults are the shipped behaviour - see the
# "Declarations Index" section above and LLMcall1-promptChange.md before changing.
DEC_INDEX_DEDICATED_PASS=0             # 2026-08-23: the extra index pass is OFF.
                                       # 1 re-enables it (~39 calls, ~593k output
                                       # tokens, +18-20 min on a 271-page package).
                                       # The main extraction records the index for
                                       # free either way.
PURGE_DEC_INDEX_AFTER_GENERATION=1     # DEFAULT IS ON - production deletes
                                       # dec_page_entries from the session row once
                                       # forms are generated (PII, ~33 KB/session).
                                       # Measured cost of the delete: 9 of 5,852
                                       # fields degrade to a blank or a shorter
                                       # policy-number printing; none get a wrong
                                       # value. 0 keeps the index for debugging.
LLM_RETRY_AFTER_MAX=90                 # cap on an obeyed Retry-After header. A 429
                                       # backs off 5/15/30/60s (a TPM window is 60s);
                                       # every other retryable status keeps 1/2/4/8.

# Cost / coverage knobs (all have safe derived or auto defaults - see improving-ll.md)
# Nothing below needs to be set in any environment. They exist to be turned OFF.
GAP_FILL_FULL_RESCAN=auto     # auto = re-scan every chunk iff the document split (>1 chunk).
                              # Free on one chunk; correct on two. 0 = legacy first-answer-wins
                              # (measured dropping 46% of a document), 1 = always.
FIELD_BATCH_PACK_TABLES=1     # Pack table groups alongside ordinary fields instead of giving
                              # each table its own LLM call. 0 reverts the COST change only -
                              # repeating-group atomicity holds either way.
TEXT_DEDUP_MIN_REPEATS=0      # clean_text paragraph de-dup. OFF: it was deleting real fleet
                              # rows. >0 requires that many repeats AND <=TEXT_DEDUP_MAX_LEN.
CONTEXT_UTILISATION=0.75      # Fraction of the model context one call may occupy. THE
                              # cost-versus-accuracy dial - see C21 before changing it.
COMBINED_FIELD_BATCH=200      # Outer batch size. 600 was measured to save 4 more calls and
                              # DECLINED - it touches the C19 schedule invariant.

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

## CHANGE QUALITY BAR (owner, 2026-08-21)

Every change clears four gates before it ships:

1. **Root cause, not the reported case.** A fix that only makes the reported example pass is
   a symptom fix - go back and find the class.
2. **Generic.** No allow-list tuned to the fixture. 1 policy, 4, 12? An unseen document type?
3. **Every edge case.** Empty, missing, malformed, duplicated, N=1, N=many, both directions.
4. **Simulate forward.** Execute the change against every existing consumer and ask what it
   BREAKS, not just what it fixes. Run the full suite; when a test fails, decide whether the
   TEST or the CODE is wrong and say which.

**Why this is a rule and not advice:** two bugs in C1 were introduced BY a fix - the
`E 9 Mile Rd` / `East 9 Mile Rd` split from a normalisation reorder, and the umbrella
$3M-vs-$1M conflict silenced by scope logic keyed on an amount. Both passed their unit
tests, because both fixtures were easier than reality. Write the gate test from the LIVE
data shape (D22).

---

## V1 Master Plan (2026-08-20 onward)

**`v1-20AUG.md` at the repo root is the running memory for V1.** Client principles, the
to-do snapshot, every change with its root cause and the alternatives rejected, the
decision register (D0-D12) and the open questions for Brent. Read it BEFORE any V1 work
and append to it before ending a session. `125_reference/` holds the client's ACORD 125
answer key.

**C1 (Data Consistency) shipped 2026-08-21.** One comparison door
(`services/fact_comparison.py`) - every "are these the same fact?" decision goes through
it and `tests/test_comparison_has_one_owner.py` fails the build otherwise. LOB canon is
a leaf (`services/lob_canon.py`). Loss-run identity is `services/loss_run_identity.py`.
Fact envelopes carry `value_state` / `evidence_state` (`services/fact_state.py`). A client
questionnaire answer that contradicts the documents is held for the producer, not applied.

## Handoff

**`HANDOFF.md` at the repo root is the current entry point** for the LLM cost/quality work:
problem statement, what shipped 2026-07-30, measured before/after, the three chunkers and
their limits, and the ranked open-issue list. Read it with `improving-ll.md`.

### The Declarations Index: A Dedicated Pass Was Built, Measured And Switched Off - 2026-08-23

**Read `LLMcall1-promptChange.md` (repo root) before touching LLM call 1's index.**
It is the full account: nine rounds, what was measured, what was reverted and why.

**Net state - extraction costs exactly what it did before this work.** 14 calls
producing facts, flags and `dec_page_entries` together. The facts/flags prompt is
byte-identical to its pre-2026-08-23 form (verified against git), and
`dec_page_entries` is back inside `_EXTRACT_SCHEMA` where it has always been.
`PROMPT_VERSION`/`SCHEMA_VERSION` are **v14** - the schema equals v12, but the
version moves forward because v13 replies (facts and flags with NO dec entries)
are sitting in the extraction cache.

**Why the dedicated pass is off.** `_harvest_dec_index` had discarded 100% of its
output since the day it shipped - `_run_extraction` merged into
`result["dec_page_entries"]` when `_merge_list_fields` returns
`{"facts": {...}, "flags": {...}}`, so the key was one level too high and
`extraction_pipeline` (which stores only `extracted["facts"]`) dropped it. Fixed,
and with it finally running the A/B was decisive: **39 calls and ~593,000 output
tokens against ~30,000 for the whole of facts+flags** - roughly 20x the rest of
extraction, +18-20 minutes per cold upload - and the owner's regenerated ACORD
forms came back *"almost the same"*. `DEC_INDEX_DEDICATED_PASS` now defaults to
`0`. The prompt and machinery remain in the file for a future experiment.

**Why it could not help, measured:** the index rendered to 619,451 chars against a
699,844-char document - **89%** - and split across **8** Stage A calls.
`_render_dec_index` is designed to be ~3% of the document in ONE call. At 89% it
is the policy rewritten as JSON, so gap fill gained nothing over walking the raw
document and co-visibility (the entire point) was spread across eight calls.

**Two fixes were KEPT because they are independent of the pass:**
- `config/settings._retry_wait_seconds`. The backoff was `2 ** attempt` for every
  retryable status - ~15 seconds total - against a TPM limit that clears on a
  **60-second** window. Now `Retry-After` is obeyed (capped by
  `LLM_RETRY_AFTER_MAX`, 90s) and a 429 backs off 5/15/30/60; every other status
  keeps 1/2/4/8 exactly. **This affects every LLM caller in the codebase.**
- Label-aware Stage A splitting in `_dec_index_chunks`. The old path cut the
  rendered index by character count and could separate the umbrella's $3,000,000
  from the GL's $1,000,000 - C23 by accident of position. Dormant at ~250 entries.

**The purge is safe, and the comment defending it is wrong.**
`PURGE_DEC_INDEX_AFTER_GENERATION` defaults to `1`, so **production deletes
`dec_page_entries` from the session row after forms generate** (one key only -
facts, flags, forms, PDFs and the per-document copies all survive). Its comment
claims nothing after generation reads facts; `arq_service._restamp_canonical_into_
forms` does, via `_deterministic_map`. Measured blast radius: of **5,852 fields
across all 17 schemas, 9 change** when the index is absent - four policy numbers
degrade to a shorter printing of the same number, five fall through to blank.
**No field ever gets a wrong value.** Fix the comment, not the behaviour.

**`declarations_authority` does not discriminate on a real package** - 39 of 39
pieces cleared the 0.25 bar, 33 at ~0.5, because its `brevity` half measures mean
LINE LENGTH and a column-laid-out policy PDF has short lines everywhere. Raising
the bar to 0.60 would cut 39 index calls to 5; **not done**, on the owner's
standing instruction that the whole uploaded document matters.

**Standing lesson from this arc:** every offline probe passed while the pipeline
was broken, because each called `_harvest_dec_index` directly and read its return
value. An offline probe proves the FUNCTION, never the SEAM around it.

## Critical Issues & Roadmap

### Answer Interpretation - SHIPPED 2026-08-24, with TWO KNOWN GAPS
**`services/answer_semantics.py` is the ONE door for interpreting anything a
human types** (producer recommendation cards, inline hard-stop / warning
resolution, client questionnaire). It separates two questions that used to be
one `bool(value)` test: *"what is the value?"* and *"did they answer?"* An
absence ("None", "never had coverage") is an ANSWER with no value; a non-answer
("TBD", "don't know") is refused at the gate and never stored. Measured before
the fix: typing "N/A" into every Tier-2 field scored **100**, while a
legitimate "None" scored as a **gap** - both directions wrong.
**`services/answer_options.py`** is the companion: 20 facts now offer choice
lists (each ending in "Other"), so a closed question is never a free-text box.
Deliberately NO LLM - owner's call on latency and determinism, not cost.
Full detail in `v1-20AUG.md` entries C2-G / C2-H / C2-I.

**GAP 1 - extraction is NOT covered.** These modules sit on the human answer
path only. `merge_facts` writes `facts[key]` directly, so an LLM-extracted
literal `"N/A"` / `"unknown"` still counts as data. Closing it means a
post-merge normalisation pass (deterministic, cheap) or a prompt change (an
`improving-ll.md` event). Symptom to watch for: a submission scoring better
than its documents justify, with fields displaying "N/A".

**GAP 2 - the fall-through log is not being watched.** Because there is no LLM
layer, `answer_semantics.unresolved_answers()` (and the INFO log line
`answer_semantics: could not read ...`) is the ONLY evidence of whether the
deterministic rules are missing real phrasings. It is in-memory, dies with the
process, and nobody reviews it. **Grep production logs for that string before
concluding free-text handling is complete** - an empty log proves the approach,
a full one is the data for extending it.

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

### Relationship Preservation: Policy/Line Identity, Value Meaning, Conflicts, Renewal Dates - FIXED (2026-08-15)
**Client (Orbin package, 271 pages, tested on ACORD 125/127/131): "do not optimize for
extracting or populating more values right now. Optimize for preserving what each value
means and where it belongs."** Seven reported defects, three root causes, five fixes.
Full per-fix detail in `FIX_TRACKING_2026-08-15.md` (repo root); tests in
`backend/tests/test_relationship_preservation_20260815.py` (40, all driving real code with
the client's literal values).

1. **RC1 - flat global facts erased policy/line identity.** One `policy_number` /
   `carrier_name` / `carrier_naic` / `effective_date` for a 3-policy package; each merged
   independently by frequency+confidence and stamped on every form via Pass-1 rules AND the
   alias bridge. Result: the AUTO number (6E7-40-02---26) on the UMBRELLA application, and
   Employers Mutual recombined with EMC P&C's NAIC 25186 - a pair no document prints.
   FIX: `_resolve_section_policy_identity` - section forms resolve header identity from the
   `coverage_lines` entry matching THAT form's line (`_SECTION_FORM_LINE_PHRASES`, matched
   with the proven `_lob_tokens` machinery); carrier+NAIC only ever as a pair from ONE
   entry; untrustworthy line list -> blank; no `coverage_lines` -> legacy path preserved
   byte-identical. 125/101 keep package-level scalars (correct there); ACORD 25 rows were
   already owned by `_resolve_current_policy_line_cell`. `_form_id` context is injected as
   a shallow facts copy in `map_facts_to_form`/`compute_form_gaps`.
2. **RC1b - renewal dates.** RULE 1's "current policy" IS the expiring dec on a renewal, so
   07/15/2025-07/15/2026 stamped as the PROPOSED term, and the (2026-08-14) expired-term
   hard stop then capped the score at 60 for our own upstream mis-assignment - while
   `is_renewal` correctly ticked the Renew box. FIX: `_route_renewal_dates` (merge tail):
   renewal + already-ENDED term -> dates move to prior_*, proposed stays EMPTY (Tier-1 asks
   for the real term); `_resolve_renewal_proposed_period` keeps the proposed boxes owned
   blanks (25/28 exempt - certificates document the EXISTING policy); the hard stop
   downgrades to a soft "confirm the renewal term" when `is_renewal` is affirmative.
3. **RC2 - no meaning guard on gap-filled amounts.** $39,300 (payroll exposure, GL class
   91580) also stamped as Annual Gross Sales; absent foreign sales became "$0". FIX:
   `_enforce_numeric_meaning_gate` (gap fill only, no prompt change): an amount whose
   verified witnesses (dec_page_entries labels + gl_class_code_schedule basis/exposure
   pairs) ALL carry a different category (sales/payroll/premium/limit/deductible) than the
   target field is blanked; a gap-filled $0 with no literal stated zero is blanked. No
   witnesses = no opinion.
4. **RC3 - conflicts detected but stamping raced ahead.** The reconciler flagged the $3M
   dec vs $1M COI umbrella limit and the form stamped $3M anyway. FIX: `umbrella_limit`
   curated as currency; `CONFLICT_WITHHOLD_KEYS` + `unresolved_withheld_keys()` write
   `facts["_uw_conflicted_keys"]` in the pipeline; `_resolve_conflicted_fact_blank` (first
   door in `_deterministic_map`) + an alias_stamper skip withhold the STAMPED value until
   the picker confirms. The fact stays in facts - SQS pillars unchanged; the confirm
   endpoint re-runs the pipeline, clearing the withhold automatically.

**Right-or-blank is the contract everywhere:** identity fields either carry their own
line's value or ship blank and are excluded from gap fill (the LLM reading "the nearest
number in the raw text" is the defect, not the fallback). Legacy sessions without
`coverage_lines` behave exactly as before.

5. **The dec entries are PRIMARY evidence, `coverage_lines` is a summary.**
   `_policy_number_from_dec_entries` lets the section-identity resolver ask the verified
   entries directly. It was unreachable in two ways worth remembering: the
   untrustworthy-list branch returned blank BEFORE consulting them, and a
   `coverage_lines` row with no premium fails `_line_entry_grants_coverage`, so the
   resolver skipped out first. **Never let a corrupt summary stand in for absent
   evidence.** Verified on the 2026-08-15 fresh run: ACORD 131 finally printed its own
   6J7-40-02---26, and the underlying GL row paired EMC Property & Casualty with BBC7263.

**The next defect class is NOT this one.** What remains on those forms is gap fill
answering questions about coverage parts the policy does not carry - Employers Liability
and WC rows on a package whose dec page says "No Coverage", watercraft LENGTH 4800 (the
street number), EBL, advertising media. Same shape as C46's phantom vehicle rows and the
same fix: suppress whole form SECTIONS on declared-absent coverage so the model is never
asked. Read `FIX_TRACKING_2026-08-15.md` before starting it.

### Dec-Page Values Must Reach The Form: Three Leaks Plugged, And The Fill-Rate Fix Finally Engages - FIXED (2026-08-12, second session)
**Owner's end goal, verbatim: "form should not be blank if values are present in declaration
page."** Four changes, all measured against the client's live package. Full detail in
`improving-ll.md` C48/C49 and `RETRIEVAL_CHANGES.md` Decision 8.

1. **The blank POLICY PREMIUM box.** The merge picked $2,991 (the Auto LINE premium, printed
   twice) over the real $10,663 (printed once) - C45's documented known limit - and the
   downstream resolver could only REFUSE the impossible figure, so the box shipped empty.
   `extraction_service._reconcile_total_premium` now runs inside the merge, where the
   candidates still exist: a winner smaller than the largest single granted line is not a
   total, and the best-scored POSSIBLE stated value replaces it (exact-sum preferred; a
   possible winner is never second-guessed - that would be C23's preference mistake).
2. **The $35 Business Auto premium.** "Auto Medical Payments $35" was the only entry whose
   tokens fit the box under the old raw-subset match ("automobile" != "auto" as bare tokens
   kept the real line out). `_resolve_lob_premium` now matches with the same stem/synonym
   predicate the indicator logic uses, rejects a coverage PART (leftover tokens are
   coverage-feature vocabulary), and lets an exact line name outrank a qualified one:
   $2,991 stamps. Parts-only documents still fill; conflicting exact names still refuse.
3. **One premises printed as THREE ACORD 125 location rows.** `_parse_address` splits only
   on commas, and the document mentions the address comma-free in three shapes, so each kept
   its whole string as line1 under a different group key. `_consolidate_property_locations`
   now folds parse-variant groups (prefix-with-same-street-number, and geo-only fragments
   contained in exactly ONE street group) and recovers city/state/zip out of a comma-free
   line1 into their own boxes. Two real suites never fold; ambiguous fragments stay put.
4. **Step 2 of the retrieval plan shipped** (`RETRIEVAL_CHANGES.md`): the density filter
   skipped on the client's package (separation gap 0.07 < 0.15 floor), leaving every
   gap-fill call a 174k-token haystack and the fill rate at 26%. Standard-form pages are now
   dropped by their OWN printed ISO footer (`CG 00 01 04 13`) - carrier dec-page codes
   (`CA7000A 02-22`) don't match, a FORMS AND ENDORSEMENTS schedule (many codes in one
   window) and its boundary-spill neighbours are kept, the fact rescue outranks the drop,
   and the ratio gates still judge the result. On the density-inseparable fixture:
   108,873 -> 3,000 chars with zero dec values lost. Kill switch `TEXT_SELECT_FORM_FOOTER=0`.

**Correction to the entry below:** "Checked and deliberately NOT changed: NAICS/SIC routing"
is stale - a later session the same day DID reverse it in `question_classifier.py` on the
client's explicit instruction (Part 13: "those come from the producer or underwriter").
NAICS/SIC are now producer-facing; the Figure 20 suggester surfaces its candidates to the
producer. The code comments there carry the full reasoning.

Tests: `tests/test_dec_page_values_20260812.py` (13), +5 in `test_location_consolidation.py`,
+6 in `test_text_selection.py`. Suite **2098 passed / 2 failed** - the same two pre-existing
unrelated failures, zero regressions. Prompt inspector re-run: prefix stable, PASS.

**Same day, third session - `dec_page_entries` (C50, read improving-ll.md before touching):**
LLM call 1 now also RECORDS every label:value:owner entry printed on a declarations/schedule
page (source-driven, form-agnostic - the fix for the measured 68-of-548 deterministic
ceiling). `_verify_dec_entries` discards anything not literally present in the uploaded text;
the ONLY consumers are deterministic - `_backfill_empty_facts_from_entries` (five stacked
conditions; the client's account-number-as-FEIN and producer-phone-as-applicant-phone defects
are each blocked by two of them) and the text-selection rescue net (closes the filter's one
remaining data-loss shape). **LLM call 2 is byte-identical, proven by
`test_call2_prompt_is_byte_identical_with_dec_entries`; every still-unfilled field still
reaches it, pinned by `test_every_unfilled_field_still_reaches_call_2`.** The fr1 equality
edge on the total-premium floor ($3,954 == largest line slipping through) was also closed on
both layers. Suite **2139 passed / 2 failed** (same two pre-existing), inspector $0.0584
unchanged, PASS. Tests: `tests/test_dec_page_entries_20260812.py` (24).

### Pre-Download Review: Repeated Lines + Score Contradicting Itself - FIXED (2026-08-12)
**Client: "repeated values are there a lot" + PART 18's "does the score correlate to the
items?"; the fresh run showed the same loss warning twice, ~20 near-identical "high-impact
... left blank" rows, and "Score at download: 66/100" above prose saying "scores 63/100".**
Four root causes, NONE in score computation:
1. **Positional rec_ids** (`rec_loss_{len(recommendations)}`, `sqs_service`) - the same
   throwaway-index defect as the 2026-08-08 legacy_soft_* fix, one layer up. Two forms'
   scorers emit the identical loss warning at different list indexes -> different ids ->
   the audit table's ON CONFLICT (session_id, rec_id) dedupe never fires -> two rows, and
   a dismissal stops matching when a recalc renumbers. Now `_loss_rec_id(message)`:
   identity from the digit-stripped message template. Every other rec already had a
   stable id; loss was the only positional straggler.
2. **Random uuid fallback** in `log_recommendations_presented` for plain-string recs -
   same dedupe defeat. Now `_fallback_rec_id` = message hash.
3. **One row per distinct high-impact question** in `field_qa.to_recommendation_rows`.
   Second merge tier added: distinct questions sharing form+reason roll into ONE row
   naming each question (first 3, "+N more"). The client's literal 20-row shape now
   renders 3 rows (test-pinned). Single-question groups keep byte-identical wording;
   value mismatches / schedule rows stay individual. Also rewrote the "1011 fields the
   AI left blank" summary phrase to "optional fields not covered by the documents (left
   blank by design)" - it was the blank-over-wrong rule working, reading like a failure.
4. **The narrative was built from a different score than the banner.** `/api/sqs/narrative`
   fed the LLM `next(iter(generated_forms))` - the FIRST form's per-form score - while the
   banner renders the independent PACKAGE score, and the prompt said "state the score
   tier". Endpoint now reads `session["package_sqs"]` (first-form fallback only for legacy
   sessions); prompt now FORBIDS restating score/tier/points - the UI owns the number,
   prose owns the gap + next action. Package `top_recommendations` messages feed the
   drivers context (never a dict repr). Fallback string kept per user decision - it now
   derives from the same package object as the banner.
Tests: `backend/tests/test_preflight_repetition_20260812.py` (14, incl. an anti-rot grep
for positional ids and the client's literal run shape). Suite **2112 passed / 2 failed** -
the same two pre-existing unrelated failures, zero regressions. `improving-ll.md` updated
for the prompt edit. Old sessions keep their already-written duplicate rows (positional
ids already stored); fresh runs are clean.

### Completion Notification Announced The Wrong Issue Count - FIXED (2026-08-12)
**Client screenshot: the corner toast read "1 warning found" while the review screen printed
THREE warning clusters** - Missing baseline form, GL exposure basis, Auto optional coverage
gaps. Reported for hard stops too.

**Root cause: the toast counted a different list than the screen drew.** `packageStatusNotice`
and the next-step banner used `len(hard_stops)` / `len(soft_stops)`; the issue cards render
`grouped_issues`. Those diverge THREE ways, in both directions:
1. **Advisory cross-form issues are rendered but never counted.** `extraction_pipeline.py:786`
   mirrors EVERY cross-form issue into `structured_issues` whatever its type, so an advisory
   draws a warning card - but `split_cross_form_issues` routes advisories to a third list that
   nothing merges into `soft_stops`. 8 rules are advisory-typed; the client's UM/UIM card is one.
2. **`cross_issues` injected on the reload path** (`/extraction-result`) render alongside stop
   arrays that never contained them.
3. **The legacy duplicate suppression** hides a message the arrays still carry, so `len()`
   counts one problem twice - the same count, wrong the OTHER way.

**Fix: stop counting inputs, count output.** `build_grouped_view` now returns `counts`, summed
from the clusters it actually rendered (`cluster["count"]`, the same unit each tier header badge
sums). One frontend helper `packageIssueCounts()` reads it, with array length as the fallback for
old payloads and the lite path. It feeds the toast, the next-step banner AND the section
visibility gates - gating on the arrays could hide a card the grouped view renders.
**`important` is deliberately excluded**: it echoes the top 3 clusters already counted in the
tiers, so counting it would inflate by up to 3.

**The raw arrays are untouched** - they are the SQS capping inputs (60/85), dismiss credit and
`issue_id` hashing. This is display-only. Tests: `backend/tests/test_grouped_view_counts.py` (6),
including the client's literal screenshot values. Suite **2031 passed / 2 failed**, the same two
pre-existing unrelated failures, zero regressions. Frontend production build verified.

### Form Coverage Dropped: Four Defects, Three Of Them Self-Inflicted - FIXED (2026-08-12)
**Client report: "form values are not filling up as they were earlier".** Four causes found,
each measured against the real schemas rather than reasoned about. Full detail in
`improving-ll.md` C46/C47.

1. **The evidence gate was rejecting REAL answers because `"not"` is a stopword.**
   `_quote_restates_the_question` (added hours earlier, to stop a checkbox ticked on the
   "evidence" `"for non-payment of premium"`) tested only whether all the quote's significant
   words appear in the question. **A direct answer to a yes/no question is by definition
   mostly the question's own words**, and `"not"` sits in `_ECHO_STOPWORDS`, so the one word
   carrying the whole meaning was discarded before comparison. Measured: **39 of 218 real
   compliance questions across 9 forms (18%; ACORD 125 40%, ACORD 126 33%)** lost their
   canonical evidence - including `"The applicant does not have any subsidiaries."` and the
   affirmative `"Subcontractors are required to carry coverage."` **Damage concentrated by an
   asymmetry: a "Yes" survives on a quote OR a paired explanation; a "No" has only the quote
   and is blanked outright.** Fixed with a structural second condition
   (`_quote_asserts_something`) - overlap is necessary but not sufficient, and a bare noun
   phrase (no subject, no finite verb) is what a label actually is. 15/15 separation, 39/39
   recovered, both original culprits still rejected.
2. **The model was asked about vehicles that do not exist.** One Subaru in the document;
   ACORD 127 came back with rows 2-3 carrying the **General Liability** class codes
   91580/91585 and the GL exposures ($39,300 payroll, $350,000 subcontract cost) stamped as
   vehicle COST NEW. **The first theory - cross-form batch confusion - was wrong.**
   `_SCHEDULE_REGISTRY` binds only the 19 IDENTITY columns; the other ~50 columns per row
   fell through to gap fill for every row letter the form prints - **164 questions about
   vehicles that do not exist, against 56 for the real one.** Fixed by
   `_resolve_phantom_schedule_row` in `_AUTHORITATIVE_BLANK_RESOLVERS` (the contract BOTH
   `compute_form_gaps` and `map_facts_to_form` already consult). **Acts only on positive
   evidence** - no schedule list means no suppression, since suppressing on no evidence would
   delete a schedule the extractor merely missed. Capacity is `len(list) + row_offset`, because
   `NamedInsured_A` is the applicant and the list starts at row B. **166 union fields (14%)
   removed and one fewer outer batch: cheaper AND more correct.**
3. **A line premium was stamped as the package total.** $2,991 (Commercial Auto) instead of
   $10,663, because `_merge_list_fields` ranks on `log1p(freq) + confidence` and a line
   premium printed twice beats the true total printed once. `_resolve_estimated_total` now
   rejects a stated total smaller than `max(sum of lines, largest single line)` and falls back
   to the sum it already computed. **This is a VALIDITY constraint, not C23's magnitude
   PREFERENCE** - nothing here ever picks a bigger number, it refuses an arithmetically
   impossible one. `test_a_larger_stated_total_is_never_forced` pins that distinction.
4. **`umbrella_sir_below_gl_deductible` - the SAME conflation as the Auto twin, one coverage
   part over, and a HARD STOP.** A $0 SIR against a $1,000 GL deductible fired a hard stop
   capping the package at 60 on the ordinary, healthy structure. An Umbrella SIR applies only
   where the umbrella drops down; a GL deductible applies to claims the GL DOES cover, above
   which the umbrella attaches at the GL **limit**. The two never meet. Deleted from BOTH
   engines - `sqs_service.evaluate_stops` held **a second, independent copy**, exactly the
   duplication that let the Auto version survive its first fix, and the legacy copy is the one
   that actually drives the 60/85 caps. The genuine check
   (`_check_umbrella_gl_minimum_limits`, umbrella vs underlying GL LIMIT) is untouched and
   verified still firing.

**Checked and deliberately NOT changed: NAICS/SIC routing.** It was on the open list as
"should go to the producer, not the client". It should not - `test_naics_code_still_client_
despite_naic_substring` and the `_CLIENT_WHITELIST` entry exist specifically to keep it
client-facing (the carrier's `naic` number is a substring of `naics_code`), and the Figure 20
suggester chips the client praised render in the client questionnaire. Reversing it would
break a deliberate, tested decision and a working feature.

**Also cleared by measurement, not assumption** - the other suspects for the coverage drop:
Guard 8's rewritten `_is_tooltip_echo` is a net GAIN (0 flags where the old code flagged 67 of
ACORD's own enumerated valid answers; 7 extra in 146,300 cross-applied pairs, all nonsense
pairs); text selection never fired on the client's document (separation gap 0.07 against a
0.15 floor); and `_report_ungrounded_ai_values` is read-only by inspection.

Suite: **2025 passed / 2 failed** - the same two pre-existing unrelated failures
(`test_arq_acord125_missing_only`, `test_normalization`), zero regressions, +47 new tests.

### Data Consistency Picker Suggested Legal Boilerplate As The Real Value - FIXED (2026-08-08)
**Client report: the "Applicant / Named Insured" Data Consistency picker suggested "c. Any person or
organization having proper..." instead of the real company name** - a sentence lifted straight out of
the CGL "WHO IS AN INSURED" policy section, ranked ahead of "ORBIN CONTRACTING LLC" and shown as
"Suggested" at MEDIUM confidence. Reported again minutes later with a *different* garbage sentence
("any architects, engineers or surveyors not...", a professional-services exclusion clause) after the
first patch - then reproduced live by the client on `mailing_address` too ("of such notice will be
sufficient proof of notice. in compliance with laws, rules, or", a notice-of-mailing clause). Same bug,
three fields, three patches attempted before the real cause was found.

**Root cause: `underwriting_consistency.py`'s text-scan safety net has no concept of value shape.**
Pass 1 is the Stage-1 LLM extraction (trustworthy, full-document). Pass 2 is a regex "safety net" that
re-scans each document's OWN raw text for a label word ("insured", "mailing", "carrier") followed by
`:`/`-`, to catch cases where the LLM copied one document's value onto another's. For a NAME or an
ADDRESS this is unsafe by construction: any run of words can match, and insurance boilerplate uses
those exact trigger words dozens of times per document for reasons that have nothing to do with the
field. Patching the symptom (`_looks_like_name` denylisting connector words, then list markers, then a
lowercase-start check) closed each reported case and left the *next* boilerplate phrasing free to get
through - confirmed whack-a-mole, not a fix, after the second incident.

**Real fix, in two parts, both derived and neither hardcoded to a specific field:**

1. **`_scan_shape(fact_key, cfg)` decides whether a field is safe to regex-scan at all**, derived from
   the field's own `kind` (currency/integer get a numeric capture shape) and from Workstream-2's own
   `DATE_FIELDS`/`FEIN_FIELDS`/`_infer_field_category` tables for identity fields - never a second local
   copy of "which fields are dates," since that divergence is exactly what let this bug recur. Returns
   `None` (never scanned) for anything free-text: `applicant_name`, `dba_name`, `carrier_name`,
   `mailing_address`, `physical_address` (exempted pre-emptively, same shape, not yet reported broken),
   and `entity_type` (found by a follow-up sweep, not a report - `normalize_entity_type` is a synonym
   passthrough, not a validator, so garbage text survived it unrejected). `_TEXT_SCAN_EXEMPT_FIELDS` is
   now DERIVED from this function instead of a hand-maintained list.
2. **Numeric fields (`num_employees` + 4 currency fields with no bespoke pattern) were routed through
   the SAME loose prose capture as addresses**, because the generic label-fallback pattern never varied
   by field kind - `"Employee Count - varies seasonally based on staffing needs"` captured cleanly and
   was then validated by the generic TEXT normalizer, with zero numeric check anywhere on that path.
   Fixed by making the capture group itself kind-aware (currency/integer/date/FEIN each get their own
   checkable shape), so a sentence is now structurally unable to match, not filtered after the fact.

**A second, independent defect found in the same fields while fixing #2: the $10,000 scan floor was
global and wrong for retentions.** `umbrella_sir`/`gl_deductible`/`auto_deductible_comp`/
`auto_deductible_collision` are ordinary at $0-$1,000 - the client's own reported Auto case was a
$1,000 deductible - so the floor built for business-scale revenue/payroll silently discarded every
realistic value on all four fields; their safety net had never once fired. Fixed the same way as #1:
`_scan_min_amount()` DERIVES a field's money role (exposure vs. retention) from whole tokens in its key
*and* label ("deductible", "sir", "retention"...), not a per-field number - verified against field
names that don't exist yet (`cyber_retention`, `wc_sir`) to prove it is a rule, not a list in disguise.

**Two standing guards, not just a fix, because three of these four incidents were the SAME root cause
recurring:** `test_every_reconcilable_field_has_a_resolved_scan_shape` and
`test_every_numeric_field_resolves_a_floor` fail the build if a future `RECONCILABLE_FIELDS` entry (the
module's own docstring calls adding one "a one-line config add") lands without anyone deciding its scan
shape or money role. Proved they actually bite: simulated adding a free-text field the naive way
(correctly exempted, scanned nothing) and simulated reintroducing a loose prose pattern for an exempt
field (caught).

**Swept the rest of the codebase for the same signature** (a regex scanning raw OCR text for a label
then capturing a free-form value) - found in exactly two places, both in this one file. Every other
`re.search`/`re.finditer` in `services/`/`utils/` either operates on already-extracted facts, matches a
field *name* (not raw document text), or returns a boolean. Nothing else needed a decision.

**Verified live for every finding, not just unit-tested:** each client-reported/swept sentence
reproduced verbatim now returns `[]`; every real value (`"Employee Count: 47"`, `"Umbrella SIR: $0"`,
the client's literal $1,000 Auto deductible, revenue/payroll/building-value/date/FEIN) still scans
correctly - the fix gained coverage on the retention fields and lost none anywhere else. 26 tests in
`test_underwriting_consistency.py` (up from 10 before this arc), full suite 1316 passed / 2 failed -
the same two pre-existing unrelated failures as every entry above, zero regressions.

**Known, not touched:** `_COMPLETENESS_MARGIN` (the HIGH-confidence ranking threshold) is scale-
mismatched against `_value_completeness`'s wildly different per-field ranges (addresses 0-3.5, FEIN 0
or 1.0, currency/integer flat 0.0) - checked deliberately, not missed. Every mismatch there fails
toward asking the user, never toward a wrong stamped value, so it is lower-priority than everything
above and left alone until it actually misfires.

### Auto Symbol Warnings Fired On Every Submission - FIXED (2026-08-07)
**Client report: two warnings on a submission where nothing was wrong** - "Hired/Non-Owned
auto exposure detected but coverage symbol(s) not defined" and "Physical damage coverage
requested but symbols undefined", on a policy whose dec page plainly shows Symbol 01 for
Auto Liability and Symbol 07 for Comprehensive and Collision. The client's analysis was
correct on every point, including the underwriting: **Symbol 1 (any auto) is BROADER than
8 and 9 and already designates hired and non-owned autos for liability**, so requiring 8
and 9 separately is wrong. Same class of defect as the Umbrella SIR bug below, found the
same day.

**Root cause: five phantom fact keys.** `_check_auto_hired_nonowned_symbols` and
`_check_auto_symbol_to_exposure_alignment` read `hired_auto_symbol`, `non_owned_symbol`,
`auto_physical_damage_comp_symbol`, `auto_physical_damage_coll_symbol` and
`drive_other_car_symbol`. **Grepped the whole repo: those five names appear ONLY in the
code that reads them.** Nothing writes them - not the extraction prompt, not
`FACT_REGISTRY`, not any stamper or alias map. They were empty on every submission ever
processed, so both checks were unsatisfiable and fired unconditionally. `sqs_service.py`
had a **second, independent copy** of the hired/non-owned check reading the same two
phantom keys, silently docking the Auto pillar on every package we have ever scored - two
copies of one rule is why this survived. `issue_registry` compounded it: the three symbol
codes were `_R_NONE` with a comment claiming "coverage symbols are not writable canonical
facts", which was never true (`auto_covered_symbols` has been in `FACT_REGISTRY` all
along) - so the client's Resolve button was decorative.

**The definitions were already in the repo, unused.** All **37** covered-auto symbols
(business auto 1,2,3,4,6,7,8,9 / truckers 41-50 / motor carrier 61-71 / garage 21-31) ship
inside `forms_schemas/ACORD_137_CA|CO` and `ACORD_138_CA|CO` as ACORD's own `/TU` tooltip
wording. They arrived as a side effect of generating those schemas from the template PDFs
and **no Python ever read them** - they reached the gap-fill LLM as prompt text and nowhere
else. `auto_covered_symbols` was likewise extracted since day one and never stamped, never
validated, never read by either check. New `services/auto_symbols.py` is that table plus
the reasoning helpers; `test_every_symbol_description_matches_acord_tooltip` re-reads the
real schemas and fails the build on a one-word drift (it caught 4 of my own typos).

**Fix, seven parts.** (1) Both checks now reason over `auto_covered_symbols` - Symbol 1
satisfies hired/non-owned, Symbol 7 satisfies comp/collision. (2) The SQS duplicate
delegates to the single implementation. (3) `_R_NONE` -> `_r_field("auto_covered_symbols")`,
so Resolve TRANSFERS the carrier's existing symbols exactly as the client asked (validated
by `_is_covered_auto_symbols`, which parses free text but rejects a non-answer). (4)
Extraction captures symbols ATTRIBUTED to their coverage line
(`[{"coverage": ..., "symbols": [...]}]`) - a bare `[1, 7]` cannot say WHICH coverage a
number designates, which is the entire point of a symbol; `parse_symbols` still accepts the
legacy bare list, a dict, and producer free text. (5) Comp/collision symbols stamp onto
`Vehicle_ComprehensiveSymbolCode`/`Vehicle_CollisionSymbolCode` (real ACORD 127 fields,
blank on every form we have ever produced), with policy-level inheritance - a dec page
prints ONE "Comprehensive 07" for the whole schedule - and two competing symbols leave the
cell blank rather than picking one. (6) `_derive_symbol_indicator` ticks the 137/138/160
grid and the ACORD 25 / 131 ANY AUTO boxes deterministically. (7) NEW
`_check_auto_owned_fleet_symbol_gap` - the real check the phantom code was reaching for: a
scheduled fleet whose liability symbol only reaches hired/non-owned autos has NO liability
coverage. We were throwing false alarms while the true alarm went unbuilt.

**Three things deliberately NOT done, all verified rather than assumed:**
- **ACORD 127 has no liability covered-auto box, and that is ACORD's design.** Audited all
  634 fields: the 127 records liability per vehicle as `Vehicle_Coverage_LiabilityIndicator_*`,
  and its only symbol fields are the 13 per-vehicle physical damage / comp / collision codes.
  Symbol 1 lands on the 137 grid, ACORD 25's `Vehicle_AnyAutoIndicator_A`, and ACORD 131's
  `UnderlyingCoverage_Coverage_AnyAutoIndicator_A` (whose tooltip literally reads
  "(symbol 1)"). The old message text said "Define symbols on ACORD 127" - wrong form.
- **Only the LIABILITY row of the symbol grid is stamped.** ACORD 137 prints one grid PER
  COVERAGE LINE (rows A, B, C, E-H), each offering only the symbols legal for that coverage.
  Row A is the only row carrying symbols 1 and 9, so it is provably liability; row C is
  provably UM (only row with symbol 6); **rows E-H offer identical sets and cannot be told
  apart from the schema.** Stamping them would risk a liability symbol in a physical-damage
  row - a wrong value on a legal document. Rows other than A fall through to gap fill
  exactly as before. Mapping them needs the printed form layout, not more inference.
- **ISO Symbols 5 and 19 are absent on purpose.** They are real, but ACORD does not print
  them on the grid - they belong in the "Other symbol" box, which `_derive_symbol_indicator`
  ticks when `unrecognised()` is non-empty. Inventing rows for them would tick a checkbox
  that does not exist.

**Everything declines to guess.** `covers()` returns None ("cannot say") on unknown or
unrecognised symbols and callers must never read None as a gap; `family_for` reads the
NUMBERS (the four ACORD sets are disjoint) before falling back to flags; no LLM is involved
anywhere - a fabricated covered-auto symbol is a coverage misstatement, which is exactly
what the standing blank-over-wrong rule exists to prevent. Cost impact is negative: ~90
words added to the cached extraction prefix, up to 40 fields per auto form removed from
gap fill (logged as C33 in `improving-ll.md`).

**Blast radius handled:** `cross_form_validator` (3 rules rewritten, 2 added),
`sqs_service` (duplicate removed), `issue_registry` (2 new codes, 5 resolutions corrected),
`fact_registry` (question/validator), `extraction_service` (prompt + schema),
`pdf_service` (schedule bindings + indicator derivation), `schedule_capture` (2 columns),
`docs/DECISION_TREE_MAPPING.md`, `improving-ll.md`.
**Scores on past auto submissions will rise** once these two permanent warnings stop
firing - a correction, but tell Brent before he notices. Written up for him in
`docs/AUTO_SYMBOLS_BRIEF.md`.

Tests: `backend/tests/test_auto_symbols.py` (46), including
`test_client_reported_case_is_silent` (the client's literal values - must never fail) and
`test_no_check_reads_a_fact_nothing_writes`, which greps both modules for the five phantom
keys so this class of defect cannot be reintroduced. Full suite **1236 passed / 2 failed**,
the same two pre-existing unrelated failures, zero regressions.

**Also fixed while in there (nobody reported it):** `auto_doc_symbol_missing` read the
fifth phantom key AND was conceptually wrong - Drive Other Car is an endorsement naming
individual insureds (recorded per driver as `Driver_Coverage_DriverOtherCarCode_*` on
ACORD 127), not a covered-auto symbol. There is no DOC symbol field on any of the 17
schemas. It now checks the driver schedule.

### "Resolve" Opened Nothing On Every Legacy Warning - FIXED (2026-08-08)
**Client report: a "Carrier-Grade COPE incomplete - SQS capped at 85. Missing: year built,
roof year, sprinkler system, fire protection class" warning could not be resolved - "there
is nothing that pops up to fill in the missing info".** The inline-resolution feature
(RESOLUTION_MAP, ResolutionModal) keys off an issue's rule CODE. Two engines produce
warnings: `cross_form_validator` emits coded issues; `sqs_service.evaluate_stops()` /
`utils.validators.run_field_validations()` emit plain strings, and the call sites tagged
them with a THROWAWAY INDEX (`legacy_soft_0`, `legacy_soft_1`, ...). No real code meant
`resolution_for()` had nothing to look up, so **40 of the 46 legacy rules rendered a
Resolve/Dismiss row that opened onto nothing** - including the one screenshotted.

**Do not "just delete the old engine" - it is the primary one.** Measured before deciding:
`cross_form_validator` has 33 checks and **all 33 are gated on a specific ACORD form being
selected** (`triggered_ids`); only 7 of the 46 legacy rules have any coded equivalent; the
legacy engine owns **all 9** format/range validators (the coded engine has zero); and
`extraction_pipeline.py`'s own comment confirms the coded issues are a display MIRROR -
`hard_stops`/`soft_stops` from the legacy engine are what drive the 60/85 SQS caps. The
client saw the legacy twin precisely because the coded COPE check sits behind "is ACORD 140
selected" and hers was not.

**Fix - one column on the table that already existed.** `_LEGACY_MESSAGE_RULES` already
classified every legacy message (cluster + tier) and was already mandatory to maintain. It
now carries `(phrase, cluster, tier, code, resolution)`; `classify_legacy()` returns the real
code; the two call sites pass it to `make_issue()` instead of the index. **Not extraction,
not SQS scoring** - message strings are byte-identical, so caps, dedup and issue_id hashing
(which keys off MESSAGE, not code - `issue_id_for`) are untouched and stored resolution
statuses still re-attach. ~30 rules became typed inputs, 2 narrative, and the rest carry an
honest `_r_review()` note instead of a dead button. Frontend needed nothing: `AcordModal`
renders the affordance from `!!iss.resolution`.

**Codes are namespaced `legacy_*` on purpose.** Reusing a cross-form code would make the
legacy row look like its own coded twin, protect it from `_LEGACY_SUPERSEDED_BY_CODE`'s
duplicate suppression, and render both near-identical bullets. Guarded by test.

**Four defects found while doing it, three of them pre-existing:**
1. `_RECOMPUTED_CODE_PREFIXES` was `("legacy_hard_", "legacy_soft_")` - it identifies which
   persisted issues a recalculation throws away and rebuilds. Left un-widened to `("legacy_",)`,
   a stop the client had already fixed would be preserved forever and keep rendering as an
   open blocker. The wider prefix still matches pre-2026-08-08 sessions.
2. `resolution_for()` returned `dict(res)` - a SHALLOW copy that left the `facts` LIST shared
   with the template, so any caller appending to it corrupted every future issue with that
   code. Latent since the feature shipped, because `test_resolution_for_returns_a_copy` only
   reassigned a scalar key. Fixed for both maps via `_copy_resolution()`.
3. The `"effective date"` row had a SPACE but `validate_effective_date_window()` emits the raw
   fact key (`"effective_date is more than 2 years in the past"`), so it never matched and that
   warning had been falling into the "Other validations" default bucket unnoticed.
4. `validate_naics_code()`'s two messages had no row at all - same silent fall-through.
   Both found by the new coverage test on its first run.

**Two coded rules were also wrongly marked unfixable** and are now typed: `umbrella_no_
underlying_coverage` (a HARD STOP capping the package at 60, whose three underlying-limit
facts are all writable) and `auto_um_uim_not_specified` (its comment claimed
`auto_um_uim_limit` was not writable - verified false). `auto_split_limits_incomplete` stays
`none`-mode: `bi_per_person`/`bi_per_accident`/`pd_per_accident` are genuinely NOT writable,
verified, so that comment was right.

**The anti-rot layer is the point** (`backend/tests/test_legacy_rules.py`, 65 tests). It
HARVESTS what the engine can actually emit - AST-walking `evaluate_stops`' append sites (its
branches are mutually exclusive, so driving it would silently under-cover) plus really running
`run_field_validations` and the two standalone validators - and fails the build if any message
matches no row, lands in the default bucket, or is SHADOWED by an earlier row's substring
(the table is first-match-wins, so "WC payroll" sitting above "Total payroll" would ask the
producer for the wrong field). Plus: every `field` fact is writable and not schedule-backed,
every `none` explains itself, no legacy/cross-form code namespace collision, and
`_RECOMPUTED_CODE_PREFIXES` covers every legacy code. There is also a harvester self-check -
an empty harvest would make the coverage test pass vacuously, which is exactly the trap C25
documents.

**Verified end-to-end**, not just by unit test: replayed the client's literal string through
`evaluate_stops -> build_structured_from_sources -> build_grouped_view` and confirmed the row
renders `mode: field` with all six facts its own rule checks. Suite: **1301 passed / 2 failed**,
the same two pre-existing unrelated failures as baseline (`test_arq_acord125_missing_only`,
`test_normalization`), zero regressions.

**Known, deliberately not done:** filling a fact after DISMISSING the related recommendation
could stack `_apply_dismiss_score_credit` on top of the recompute. Pre-existing, not touched
by this change, and not proven either way - worth a dedicated test before it matters.

### Umbrella SIR vs Auto Deductible False-Positive Warning - FIXED (2026-08-07)
**Client report: a cross-form warning read "Umbrella SIR ($0) is lower than Auto
deductible ($1,000). Verify attachment consistency..." on a submission where nothing
was actually wrong** - Auto Liability limit ($1,000,000) matched the Umbrella's
scheduled underlying Auto Liability limit ($1,000,000) exactly. Client's own analysis
nailed the root cause: the $1,000 Auto deductible is a comp/collision (physical-damage)
figure - what the insured pays to repair their own vehicle - while Umbrella SIR is a
liability-side retention that only applies when a claim the Umbrella covers isn't
covered by the underlying liability policy. The two numbers protect entirely different
exposures; there is no underwriting rule that relates them, and a $0 SIR is the normal,
healthy structure. The warning was comparing two unrelated coverage concepts and calling
disagreement a coverage gap.

**Root cause, confirmed in code:** `cross_form_validator._check_umbrella_sir_vs_auto_
deductible` compared `umbrella_sir` against `auto_deductible_comp` /
`auto_deductible_collision`. The fact registry has no "auto liability deductible" field
at all - primary Auto Liability is conventionally $0 deductible - so there was never a
valid Auto-side figure to compare SIR against; the function reached for the only "auto
deductible" fields that exist, which happen to be the wrong coverage part. This fired on
ordinary Auto+Umbrella submissions generically, not just this one, and (being a
`soft_warning`) quietly dinged SQS scores project-wide every time it did. The correct
attachment check - Umbrella limit vs. underlying Auto LIABILITY limit - already existed
and already worked (`_check_umbrella_auto_minimum_limits`); it stayed silent here
because $1M matched $1M.

**Fix - two parts, not one.** (1) Deleted the broken function outright (not
threshold-tuned - no version of "SIR vs. physical-damage deductible" is ever correct)
and its `_RULE_FUNCTIONS` registration, plus the 3 orphaned `issue_registry.py` entries
tied to its issue id (`umbrella_sir_below_auto_deductible`) and the stale
`docs/DECISION_TREE_MAPPING.md` line that documented it as compliant. (2) Traced the
function back to its actual spec source (`Decision_Tree.txt` lines 226-231:
"Validate deductibles and SIRs are consistent across ACORD 126/127, ACORD 131, and dec
page representations. Flag unexplained discrepancies") and found it was misread from day
one - read plainly, that line asks whether the SAME figure agrees across its multiple
mentions (e.g. the SIR the dec page states vs. what got extracted onto ACORD 131), not
whether SIR and a deductible should be compared to each other. That real feature already
has a home: `underwriting_consistency.py`'s Data Consistency engine (Beta Report §4.3),
already live for Gross Sales, Building Value, and 9 identity fields. `umbrella_sir`,
`gl_deductible`, `auto_deductible_comp`, and `auto_deductible_collision` are now
registered in its `RECONCILABLE_FIELDS` as proper `"currency"` entries - a genuine
cross-document disagreement on any of them is flagged for review with source
attribution, non-blocking, matching the spec's own "flag" wording (not added to
`HARD_STOP_RECONCILABLE_KEYS` or `GENERATION_BLOCKING_RECONCILABLE_KEYS`).

**Not a redundant add - closes a real quality gap in the existing auto-discovery
fallback.** `ENABLE_FULL_FIELD_RECONCILIATION` was already sweeping these 4 facts in
generically (any scalar fact not curated gets auto-discovered), but forced them into
"identity" kind, which: (a) ranks candidates by raw string length
(`_value_completeness`) - meaningless for a dollar figure, and the exact scoring
currency/integer fields are deliberately excluded from; (b) can't produce the real
"applied to N forms" list (`_forms_for_field`'s dynamic lookup only runs for
currency/integer kind); (c) validates a confirmation with the loose general-text
normalizer instead of rejecting non-numeric input outright. Curating them properly as
`"currency"` fixes all three at once.

**Blast radius, verified not assumed:** grepped every reference to the dead issue id
and to `auto_deductible_comp`/`auto_deductible_collision` project-wide before touching
anything. Frontend has zero references (renders whatever the backend sends - nothing to
update). `sqs_service.py` has 4 other uses of these deductible facts - a presence-only
completeness check, the correct liability-limit-vs-liability-limit attachment
comparison (a second, independent implementation of the same correct check, untouched),
and two plain field-list entries - none of them the broken comparison, all confirmed
unrelated and left alone. `RECONCILABLE_FIELDS` has no test asserting its exact key set
(only membership checks), so the two new curated entries add cleanly.

**Known, deliberately out of scope today:** `_check_umbrella_attachment_stack`'s
sibling check (`umbrella_sir_below_gl_deductible`, hard_stop) compares SIR to the GL
deductible - liability-to-liability, a defensible comparison unlike the Auto one, and
not something the client flagged. Worth a second look given the same conflation
pattern caused this bug, but not touched here - no reported failure, no unilateral
rewrite of a hard_stop nobody asked about.

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

### Gap-Fill Prompt Defeated OpenAI's Prefix Cache, And Told The Model The Wrong Form - FIXED (2026-07-29)
**A cost audit traced ~80% of input spend to the same constant block of text being
re-uploaded on every LLM call in a run. Full detail, before/after numbers and the issue
IDs (C1-C11) are in `improving-ll.md` - read that before touching any prompt here.**

Two of the findings were defects, not just waste:

1. **The model was told it was filling "ACORD form COMBINED_B1of2".** `_PROMPT_SKELETON` was
   an f-string built per call with `form_id` interpolated into line one, and
   `combined_gap_fill` passes a BATCH LABEL as `form_id`. So on every combined run - which
   is every run - the model could not tell a Workers Comp form from a Commercial Auto one.
   Confirmed in production logs (`form=COMBINED_B1of2`). Fixed: the skeleton is now a
   module-level, form-agnostic constant, and a new `form_label` parameter carries the real
   names ("ACORD_125, ACORD_25") in the user message. `form_id` stays the logging label.
2. **`_raw_budget` under-reserved and could silently blank a whole batch.** Found in QA
   review, pre-existing and latent. It sized the document chunk by estimating the fields
   block with `_field_spec()` - one short line per field - while `_build_user_prompt`
   renders multi-slot and table fields through `_slot_group_block()` / `_table_group_block()`,
   which are several times longer. Group-heavy batches therefore packed in too much raw text:
   **measured 69,879 chars against a 60,000 budget on ACORD 140 (+16%)**. In production that
   is a context-length 400 -> 3 dead retries -> `_chat_json` returns {} -> the whole batch
   silently BLANK, indistinguishable from the model having nothing to say. Latent only
   because `GPT_CALL_BUDGET_CHARS` (380k) currently sits well under the model's real context.
   Fixed by extracting **`_render_fields_block()` as the single source of truth** - both the
   prompt builder and the budget call it, so they can never drift again - then rounding the
   allowance UP to a multiple of `_MAX_FIELDS_BLOCK_CHARS` so chunk boundaries stay shared
   (cacheable) without ever under-reserving. **Never re-estimate this block; always render
   it.** Guarded by `backend/tests/test_full_document_coverage.py`.

**Prompt order is now load-bearing.** `_build_user_prompt` emits
`form label -> EXTRACTED FACTS -> RAW DOCUMENT TEXT -> fields -> JSON footer`. Everything
before the field list is constant within a run and therefore cacheable. **Facts deliberately
stay AHEAD of the raw text** - the skeleton labels facts the PRIMARY source, and models
weight position as well as labels, so demoting it below the secondary source was an
avoidable quality risk and was not taken. Only the field list moved.

**Also fixed:** the prompt asked for `null` ~12 times against one "omit" instruction, so the
model emitted nulls that `_is_empty_llm_value` discarded on arrival (behaviour-neutral to
change, pure waste at 6x the input price); a parse failure re-sent the entire prompt up to
3x instead of salvaging the completed portion of a truncated reply; and a timeout or 429
triggered a second full-prompt `json_object` call that OpenAI had already billed once.

**One condition the audit missed:** OpenAI populates a cached prefix only when a request
COMPLETES, so firing sub-batches `_FIELD_BATCH_POOL`-wide made the first 4 guaranteed
misses - capping a 6-batch run near 33% no matter how correct the prompt order was.
`_PREFIX_WARMUP` (default on) runs one call to completion before fanning out: ~33% -> ~83%
on that run. It is **not** unconditional - warming always adds one serialized wave, which is
a bad trade on a small document (buys ~half a cent, costs a full round trip of user-visible
latency), so it is gated on `LLM_PREFIX_WARMUP_MIN_CHARS` (default 40,000). Each invocation
logs `warmup=True/False` with the measured prefix size. `LLM_PREFIX_WARMUP=0` disables it.

**Full-document coverage is a standing requirement with executable proof.**
`backend/tests/test_full_document_coverage.py` plants ~400 unique sentinels through a
document larger than one call budget and asserts every one reaches the model - separately for
the general fill and the compliance pass, since they chunk independently. OCR reads all pages;
extraction chunks with a `_verify_coverage` that raises on any gap; both gap-fill stages are
sentinel-verified. Known remaining gaps are logged as C14-C17 in `improving-ll.md` (the
umbrella probe truncates at 60k chars; the chunk loop stops early once every field is
answered, so a later endorsement cannot supersede an earlier value; `DIAG_RESPONSE` logs
applicant PII at INFO; documents over 500k tokens are rejected outright rather than truncated).

**Measured offline, reproducibly** (`py backend/scripts/inspect_gap_fill_prompts.py`, zero
API cost - it swaps the OpenAI client for a recorder and inspects the actual prompt bytes).
ACORD 125 + 25 fixture: **29 -> 23 total calls, 421k -> 350k input chars, and the `gap_fill`
stage went from 3 different system prompts and a 26-char shared prefix (0% cacheable) to one
identical system prompt and an 11,774-char / ~2,943-token prefix (64% cacheable).** The
compliance pass was already correct - document-first, constant system prompt - and is
unchanged at 70%.

**Do not verify prompt changes by diffing two live runs.** The pipeline is non-deterministic,
so jitter hides the regression. Verify shape offline with the inspector, then sanity-check
one live run. `backend/tests/test_prompt_prefix_caching.py` (14 tests) fails the build if the
system prompt splits into variants, if the field list moves ahead of the constant blocks, if
the shared prefix drops under OpenAI's 1024-token floor, or if batches re-fragment.
Suite: 984 pass / 2 pre-existing failures, zero regressions.

### Currency "Magnitude Tiebreak" Picked Umbrella Limits As GL Limits - FIXED (2026-07-30, C23)
**Was putting wrong limits on ACORD 125/126/25.** `extraction_service._merge_list_fields`
broke a near-tie between two candidate values for a currency fact by re-sorting on dollar
magnitude. On a real package with both a GL part ($1M/$2M) and a Commercial Liability
Umbrella ($3M) it filled the GL facts from the UMBRELLA, while the composite `gl_limits`
fact from the same run said $1,000,000 - two facts from one document contradicting each
other, and the wrong one stamping the certificate.

**Three defects in six lines, all confirmed:**
1. Across coverage parts the rule is inverted. Umbrella/excess limits are BY DEFINITION the
   larger ones, so "bigger wins" is wrong precisely where two parts coexist - most real
   packages.
2. The re-sort was **global**, not a top-two swap, so a candidate ranked 5th on score could
   win on size alone, discarding the scoring entirely.
3. `_currency_magnitude` strips non-digits and parses the remainder, so on the COMPOSITE
   `gl_limits` (which IS in `_CURRENCY_FIELDS`) it returns **1.0e+20**. The tiebreak was
   literally "whichever string contains the most digits".

**Fix, in two parts.** The magnitude rule is reduced to the single case its own comment cited:
a real limit beating a literal **zero**. Everything else was coincidence.

Killing it alone was not enough, though - it left the outcome decided by **which chunk
mentioned the amount first**, i.e. a coin flip on a figure with legal exposure. So a
**composite-consistency** check now settles the tie: `_CURRENCY_COMPOSITE_PARENT` maps
`gl_each_occurrence`/`gl_aggregate` to `gl_limits`, the composite is resolved FIRST, and only
the tied candidate whose amount actually appears in it survives. The composite is the better
witness for its own children because it was extracted as ONE coherent block.

**It refuses to guess.** It acts only when EXACTLY ONE tied candidate appears in the
composite. If both appear it cannot separate them and the ordinary scoring stands; if NEITHER
appears the scalar and the composite genuinely disagree, and that is logged as
`composite MISMATCH` at WARNING rather than silently stamped. No composite, no action.

Verified order-independent in both document orders (`umbrella_first` parametrised).
Tests: `backend/tests/test_currency_tiebreak.py` - **rewritten to drive the real
`_merge_list_fields`**. The first version reimplemented the tiebreak in a local harness plus a
string-matching "drift check", which then failed the build for a comment reword rather than a
behaviour change. A copy of production logic in a test only proves the copy is self-consistent.

### C23 Round 2 - The Composite Itself Was The Umbrella (2026-07-30)
**Round 1 did not work, and a real run proved it.** Reconciling each scalar against the
composite `gl_limits` only helps if the composite is right. On ORBIN CONTRACTING it was not:

```
merge field='gl_limits' chosen='each occurrence limit (liability coverage) $ 3,000,000;
  personal & advertising injury limit $ 3,000,000; aggregate limit (liability coverage) $ 3,000,000'
merge field='gl_each_occurrence' chosen='$ 3,000,000'  rejected=['$ 1,000,000','$1,000,000']
merge field='gl_aggregate'       chosen='$ 3,000,000'  rejected=['$ 2,000,000','$2,000,000']
```

The real GL part is $1M/$2M; the $3M is a Commercial Liability Umbrella. Every scalar agreed
with a wrong witness, and **no tiebreak line appeared in the log at all** - the check was not
misfiring, it was blind, because the top candidate already matched the wrong parent.

**Two further defects, both fixed:**
1. **Nothing chose between competing COMPOSITES.** `_score_composite_candidate` now ranks tied
   composites by `(children explained, distinct dollar amounts)`. A real GL block enumerates
   several limits ($1M occurrence, $2M aggregate, $500k premises, $10k medical); an umbrella
   block repeats one number. That separates them with **no coverage-part vocabulary** - the
   keyword approach has failed here three times and is still not being used. `explained` is
   ordered first so a long endorsement listing many dollar figures cannot outrank a composite
   that actually accounts for the scalars.
2. **The scalar check required EXACTLY ONE consistent candidate.** `'$ 1,000,000'` and
   `'$1,000,000'` are two candidates for the SAME amount, so the count was 2 and it declined to
   act. It now groups by AMOUNT: ambiguity means two DIFFERENT figures, not two spellings.

`gl_products_aggregate` and `gl_personal_advertising_injury` were being filled from the umbrella
too and are now children of the same reconciliation (and members of `_CURRENCY_FIELDS`).

Verified on the run's verbatim strings across **all 6 orderings of the three composite
candidates - 6/6 correct**, where round 1 scored 0/6. Tests: `test_currency_tiebreak.py` (23).

**Lesson worth keeping:** round 1's tests all fed a CORRECT composite. A reconciliation is only
as good as the witness it trusts, and the test must include the case where the witness is wrong.

### Silent Data Destruction Before Any LLM Saw It - FIXED (2026-07-30, C24)
**`utils/text_cleaner.py::clean_text` runs on EVERY upload at `ocr_service.py:1704` - before
extraction, before gap fill, before anything - and it was deleting content.** Four filters:
any line of >8 words that was >80% uppercase (declarations pages are written in capitals);
any paragraph under 10 chars; every repeat of any paragraph, MD5-hashed document-wide; and
any line of only digits. **Measured on a realistic dec page: 56% deleted**, including the
named insured, both GL limits, and a vehicle schedule row.

It was also arbitrary: whether a line survived depended on how many of its tokens were pure
digits (which are not `.isupper()`), so one vehicle row scored 83% and died while the next
scored 75% and lived.

**This invalidated the headline "no data is lost" claim.** `_verify_coverage` reporting
`671654/671654 chars - 100%` was 100% of **what survived this function**. The denominator was
wrong, and that figure had been quoted as proof.

Three filters deleted; de-duplication is default OFF and, if re-enabled, needs >=5 repeats AND
<=120 chars so a running header goes and a fleet row stays. **The loss metric counts
non-whitespace characters only** - a raw-length metric reports 22.1% "removed" on an intact
layout-extracted page purely from the lossless whitespace collapse, and an alarm that fires on
the normal case gets ignored, then disbelieved on the day it is real. Threshold: 2% of content.

### The Coverage Test Was Blind, And Fixing The Shredder Armed The Hole - FIXED (2026-07-30, C25)
`tests/test_full_document_coverage.py` proved "every word reaches the model" with a recorder
that always returned `{"values": {}}`. Nothing answered means `active_fields` never shrinks,
the chunk loop never stops early, and every chunk always ships - so the test passed over a
pipeline that dropped **185 of 400 markers (46%)** as soon as a model actually answered.

A "run-level coverage is still complete" defence was offered and does not hold as a property:
that run came out clean only because two of its five batches had their answers discarded as
`UNKNOWN_KEYS` and so happened to read every chunk. Coverage by luck is not coverage.

**Rescan is now automatic whenever the document actually split** (`_rescan_enabled`,
`GAP_FILL_FULL_RESCAN=auto`). Zero cost on a single chunk - there is nothing to re-read - and
correct the moment there are two. The previous OFF default relied on documents staying under
~890k chars, and **fixing C24 removed up to 25% of deletion from every document, pushing large
packages toward that line.** The two "leave it as default" decisions were coupled.
`GAP_FILL_FULL_RESCAN=0` keeps the legacy path as a kill switch and logs `COVERAGE_PARTIAL`.

### Type-Aware Rejection From ACORD's Own Declared Types - ADDED (2026-07-30, C22)
A real ACORD 127 run shipped `Driver_TaxIdentifier_A = "4S4BRCGC9C3217772"` (a VIN in a tax-ID
box) and `Driver_GenderCode_A = "ERIN ROYAL"`. Neither was caught: `_NUMERIC_DATE_FIELD_HINTS`
lists `YearBuilt`/`ModelYear` but not plain `Year`, and `_PROSE_FIELD_TOKENS` contains "Name",
so a name-ish field is classed as prose and anything passes.

**ACORD states each field's type in its own tooltip** - "Enter code:", "Enter year:",
"Enter identifier:", ... - for **3,888 of 5,852 fields (66%)**. The code read exactly one of the
twelve (`Enter number:`, 607 fields). `_rejects_declared_type` now covers all of them, wired in
as Guard 3b of `_enforce_post_fill_guards`. Zero LLM cost, deterministic.

**Conservative by construction, and it must stay that way.** It rejects only a personal NAME, a
VIN (never in a vin/serial/identificationnumber field), or an out-of-range year - because
amount boxes legitimately hold "Statutory", "Included", "See schedule". Validated by a
**~49,000-pair sweep** (every type-appropriate legitimate value x every typed field in all 17
schemas) with zero false positives; that sweep IS the test. It caught one during development:
"See schedule" matched the person-name shape, hence `_NOT_A_NAME_WORDS`.

**Honest scope - 3 fixed, 3 not, and one of those was never a defect.**
`Driver_LicensedYear_A = "2012"` is a valid year (it was the wrong ENTITY's year) and
`Vehicle_RateClassCode_A = "7383"` is a validly-shaped code - neither is visible to a type
check. And `Driver_OtherGivenNameInitial_A = "Erin"` **was mis-reported**: ACORD's tooltip reads
"middle name **or initial**", so a first name is permitted and rejecting it would blank
legitimate data. Do not "fix" it.

### Gap-Fill Batching Was Paying For Calls It Did Not Need - FIXED (2026-07-30, C29/C30)
Two independent shapes of waste, both measured on the real 5-form union (1,359 fields), both
fixed without touching a batch size, a prompt, or what any single call asks the model.

**C30 - outer batching cut both inner streams mid-flow.** `combined_gap_fill` sliced the mixed
union, then each outer batch re-partitioned ITS OWN slice into compliance questions (groups of
10) and general fields (groups of 40). Every slice boundary left a runt on each side:
compliance ran **18 calls with sizes [4, 10, 10, 9, 1, 10, ..., 4, 2, 4, 5] where 14 suffice**.
The union is now partitioned into the two streams BEFORE outer batching. This changes nothing
the model sees - the compliance pass was always a separate call with its own system prompt, so
a compliance field never shared a call with a general field. **18 -> 14.**

**C29 - every table group got its own dedicated call, and the wrong things were protected.**
`_pack_field_batches` emitted each detected table bucket as a standalone batch: **46 gap-fill
calls, 34 of them partial, many carrying 3-5 fields.** The C19 invariant requires a table to be
visible to ONE call; it does not require the table to be ALONE in it. Meanwhile only >=3-column
TABLE buckets were kept atomic, so plain multi-slot groups were sliced freely - **27 repeating
groups were being split across separate calls**, which is the C19 failure mode one level down
(a call that sees `_A`/`_B` but not `_C` cannot honour "find N distinct values, never repeat
one"). Now everything bin-packs as **indivisible units** - table bucket, multi-slot group, or
lone field. **46 -> 33 calls AND 27 -> 0 split groups: cheaper and more correct.**

**"Group" means `repeating_group_key` = (base, TOOLTIP), never base alone.** ACORD 25's insurer
tooltips end "As used here, this is Insurer B.", so `Insurer_FullName_B..F` are six separate
one-slot groups needing no joint reasoning. Counting by base name inflates the split figure to
92 and wrongly flags those six - an earlier version of the test did exactly that and was wrong.

**Net, on a realistic 680k-char package: 64 -> 46 calls, ~$1.30 -> ~$0.98 (-24%).** Output
tokens in that figure are an estimate (500/call) and are the weakest number - real output scales
with fields answered, not calls. The solid savings are the removed round trips and the repeated
cached prefix. Raising `_COMBINED_FIELD_BATCH` 200 -> 600 was measured (~4 fewer calls) and
**declined**: a ~6% gain that touches the C19 schedule invariant is the wrong trade without the
accuracy baseline. `FIELD_BATCH_PACK_TABLES=0` reverts the cost change; group atomicity holds on
both paths and that is asserted.

### Long Context Degrades Fill Quality - OPEN, MITIGATED (2026-07-29, C21/C22)
**Read this before raising `CONTEXT_UTILISATION` and before assuming a big document behaves
like a small one.** Fitting a whole 682,726-char package into one call is cheap (99% cache
hit, 1 chunk) but the model gets measurably sloppier at ~170k tokens:

1. **It stops using the ACORD field names and invents its own.** A batch that sent 39 fields
   returned 60 answers keyed `Producer_Name`, `Applicant_Name`, `GL_Limit_EachOccurrence`,
   `Carrier_NAIC` - none of which exist in any ACORD schema. `_absorb` discards unrecognised
   keys, so `filled=3` of 39. The DATA was right; the KEYS were fabricated. Whole-form:
   `fields_filled=38/171` (22%). The same pipeline on a 15k-char document does not do this.
2. **It borrows values across field types.** `Driver_TaxIdentifier = "4S4BRCGC9C3217772"` (a
   VIN), `Driver_TaxIdentifier = "ERIN ROYAL"` and `Driver_GenderCode = "ERIN ROYAL"` (a
   person's name), `Driver_LicensedYear = "2012"` (the vehicle's model year). Not a batching
   bug - C19 is fixed and `Driver_*` was whole in one batch.

**Mitigations shipped (not a cure):** a `CRITICAL - JSON KEYS` instruction is now the LAST
thing in the prompt, after the field list, so the cached prefix is unaffected; and `_absorb`
logs `UNKNOWN_KEYS` at WARNING with a sample, so this failure can never be invisible again.
**Grep every large run for `UNKNOWN_KEYS`.**

**`CONTEXT_UTILISATION` is the real dial, and it is a cost-versus-accuracy trade.** On a
682k-char package: `0.75` (default) = 1 chunk / ~224k doc tokens per call; `0.50` = 2 chunks
/ ~137k; `0.35` = 3 chunks / ~84k; `0.25` = 4 chunks / ~49k. Fewer chunks is cheaper and
faster; smaller chunks follow the field list better. This has NOT been A/B'd on a live run -
do that before choosing a production value.

**The durable fix for #2 is type-aware validation**, not prompting: a tax-identifier field
must never accept a 17-character VIN or a two-word personal name; a gender code must never
accept a name. That is deterministic and cannot be argued with by a model.

### Call Budget Was Using 24% Of The Model's Context Window - FIXED (2026-07-29, C20)
**`gpt-5.4-mini` has a 400,000-token context window and a 128,000-token max output.**
`GPT_CALL_BUDGET_CHARS` was hand-set to 380,000 chars (~95k tokens) - about a quarter of
what the model can take. That matters far more than it looks: **every extra document chunk
multiplies the call count by the number of field sub-batches.** A real 671,654-char /
271-page package across 5 forms split into 3 chunks and made **172 LLM calls where 63
suffice** - roughly 3x the cost and 3x the wall-clock time for identical output.

**The budget is now derived, not guessed.** `MODEL_CONTEXT_TOKENS` (400,000) x
`CONTEXT_UTILISATION` (0.75) minus `FORM_FILL_MAX_TOKENS`, times `CHARS_PER_TOKEN_FLOOR`
(3.5, pessimistic - measured 4.01 on a real package with o200k_base) = **994,000 chars**.
That is 75% window utilisation worst-case, 66% at the measured ratio. An explicit override
above what the window holds is **clamped** with a warning rather than failing every call.
**When the model changes, change `MODEL_CONTEXT_TOKENS` - everything else follows.**

`GPT_REPLY_RESERVE_CHARS` was also wrong: a flat 30,000 chars against a 16,000-token
(~64,000-char) reply cap, under-reserving by more than half. Now derived from the output cap.

**Nothing is truncated by any of this.** The budget controls how many PIECES the document is
cut into, never whether a piece is dropped - proven by `tests/test_full_document_coverage.py`,
which plants 400 unique markers through a 671k-char document and asserts every one reaches
the model at multiple budget settings.

**Belt and braces:** the budget also self-tunes. A genuine context-length rejection (and only
that - a 429, a timeout or a `response_format` 400 still take the normal path) halves
`_effective_budget_chars` process-wide and `_run_field_batch` re-splits and retries, up to
`CONTEXT_SHRINK_ATTEMPTS` (5, spanning a 32x over-estimate, floored at 40k). Two retries was
tried first and was NOT enough - going from 400k to a model accepting ~120k takes three
halvings, and stopping early left the batch blank, which is the exact failure this prevents.

### Post-Fill Slot Dedup Was Deleting Correct Fleet Data - DISABLED (2026-07-29)
**Found in the first live run after the caching work. Read `improving-ll.md` C18/C19.**
The post-fill dedup cleared any `_A/_B/_C` field whose value already appeared in an earlier
sibling. On a real ACORD 127 3-vehicle fleet it deleted **40+ correct cells** in one
generation - garaging city/county/state/postal code, radius of use, rating territory, rate
class, both deductibles, most coverage indicators - for rows B and C, because three trucks
garaged at one address legitimately repeat those values down the column. Row A came out
complete; rows B and C came out near-empty. Pre-existing bug; the caching work did not cause
it but **exposed** it, since better prompts meant far more sibling cells got filled.

**Now default OFF** (`SLOT_VALUE_DEDUP=1` restores it). It cannot be made correct at that
point in the pipeline: a gap-fill call only ever sees a SUBSET of a schedule's columns (Pass
1/1.5 resolves some, `_COMBINED_FIELD_BATCH` splits others across outer batches), so "the
model copied a value" and "the document really does say that for every row" are
indistinguishable. **A row-level variant was implemented, tested and removed** - ask about
City/State/PostalCode alone and three trucks in one city produce three byte-identical rows,
so it deleted the same data by a different route. Do not reintroduce either form.
Decided on asymmetry: a wrongly REPEATED value is visible on the form and the broker fixes
it; a wrongly DELETED value is invisible and reads exactly like "the document didn't say".
Guarded by `backend/tests/test_table_row_dedup.py`.

### An Outer Batch Was Cutting Schedules In Half - FIXED (2026-07-29, C19)
**This was putting WRONG VALUES on the form**, which is the one outcome that is not
negotiable. Unmasked by the C18 fix above - the per-value dedup had been accidentally
deleting the borrowed value as a "duplicate".

`combined_gap_fill` sliced the cross-form union with a plain `field_items[i:i+200]`. Each
outer batch is a SEPARATE `_fill_unmatched_with_gpt` invocation - separate LLM calls that
never see each other - so any schedule cut by that slice left the stranded rows with no view
of their siblings. Measured on the real 5-form union (1,354 fields): **`Vehicle_*` split
across 3 outer batches, `Driver_*` across 2, `CommercialProperty_*` across 3.** Result on the
PDF: `Vehicle_CostNewAmount_D = $58,900` (vehicle **1's** cost - vehicle 4 is $41,800), and
`Vehicle_RateClassCode_D = 91560` / `Vehicle_SpecialIndustryClassCode_D = 92478`, which are
the two **General Liability** class codes borrowed from an unrelated page.

**Fix - `_pack_schedule_aware_batches`.** A "schedule" is any leading name segment that
appears with more than one row letter across the union (Vehicle, Driver, CommercialProperty,
...); all its fields go in ONE outer batch, bounded by `_COMBINED_BATCH_HARD_MAX` (600) so a
pathological schedule cannot build an unbounded call. Single-row roots are packed normally -
they have no rows to align, and holding them together would drag unrelated fields into one
giant batch. **This is the same rule `_pack_field_batches` already applied one level down;
the bug was that the level ABOVE it was doing the cutting.** Verified against the real union
(all three schedules now whole) and guarded by `backend/tests/test_schedule_aware_batching.py`.

### Active Performance Bug - HISTORICAL, all three items now closed
**Combined gap fill was slow (17+ minutes for 3 forms).** Kept for history; items 1 and 2 were
implemented in 2026-07-10, item 3 via `_COMBINED_FIELD_BATCH` (the "truncate raw text" half was
deliberately NOT done - full-document chunking is used so no text is dropped). The dominant cost
levers since then have been prefix caching (C1-C11), call-budget sizing (C20) and batch packing
(C29/C30). Read improving-ll.md, not this section, for current numbers.
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
- **LLM calls and cost:** `improving-ll.md` (repo root) is the registry of every LLM call
  site, the token/cost model, and all known cost issues. Any PR that adds/removes/modifies
  an LLM call, edits a prompt, or changes batching/chunking **must update it in the same
  commit**. Read it before touching `pdf_service.py`'s gap-fill or any prompt - in
  particular §2's five conditions for prefix caching, any one of which silently returns the
  pipeline to full price. Verify with `py backend/scripts/inspect_gap_fill_prompts.py`
  (offline, zero API cost), never by diffing two live runs.

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
