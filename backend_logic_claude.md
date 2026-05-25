# Backend Logic — Bug Fixes & Analysis Log

> **Purpose:** Retain context across chat sessions. Documents every issue identified, root cause, and fix applied so new sessions can pick up exactly where this left off.
>
> **Project:** Acordly — ACORD Form Processing Platform
> **Last updated:** 2026-05-25 (Session 2)

---

## Session Context

The user uploaded `ACORD_125_Application_Data-v2.pdf` (a PDF generated from `ACORD_125_dummy_answers.json`) to test end-to-end form filling. The goal was to understand why GPT wasn't filling everything when the source document contained explicit values for all fields.

---

## System Architecture (Quick Reference)

Form filling happens in two passes inside `backend/services/pdf_service.py`:

**Pass 1 — Deterministic (`map_facts_to_form`)**
- `_resolve_schedule_row` → fills repeating rows (loss history, vehicles, drivers, etc.) from structured fact lists
- `_ACORD_FIELD_RULES` scan → maps field name substrings to scalar fact keys
- `_derive_indicator` via `_INDICATOR_RULES` → fills checkbox fields with "Yes"/"No" from boolean flags

**Pass 2 — GPT (`_fill_unmatched_with_gpt`)**
- All fields that returned "UNMATCHED" from Pass 1 are batched into a single prompt
- GPT fills what it can from the raw OCR text
- Only fills fields that are explicitly mentioned and identifiable in the raw text

**Field buckets (ACORD 125, schema=548):**

| Bucket | Count | What happens |
|--------|-------|-------------|
| `det` (deterministic) | ~207 | Filled by Pass 1 rules/registry |
| `nonfill` | 68 | Blocked from GPT entirely (signatures, premiums, carrier codes) |
| `blank_sched` | ~10 | Schedule field resolved in registry but list is shorter than row index (empty rows C/D/E) |
| `gpt_fields` | ~263 | Sent to GPT for filling |

**GPT fill rate:** ~20/263 (7.6%) — almost exclusively `AdditionalInterest_*` fields.

---

## Root Cause Analysis — Why GPT Fills So Little

### 1. Schedule Registry Name Mismatches (FIXED)

`pdf_service._SCHEDULE_REGISTRY` maps field base names to fact list sub-keys. The ACORD 125 PDF schema uses different field names than what the registry had entries for. As a result, the following fields fell through to GPT as "UNMATCHED" even though the data existed in the extracted `loss_history` list.

**Affected fields before fix:**

| ACORD 125 schema field name | Old registry entry | Result |
|----------------------------|--------------------|--------|
| `LossHistory_PaidAmount_A` | `LossHistory_AmountPaid` (wrong name) | → GPT, usually missed |
| `LossHistory_OccurrenceDescription_A` | Only `LossHistory_LossDescription` / `LossHistory_Description` | → GPT, usually missed |
| `LossHistory_ClaimDate_A` | No entry | → GPT, usually missed |
| `LossHistory_LineOfBusiness_A` | No entry | → GPT, usually missed |
| `LossHistory_ReservedAmount_A` | No entry | → GPT, usually missed |
| `LossHistory_ClaimStatus_OpenCode_A` | No entry (`LossHistory_OpenIndicator` exists but different field name) | → GPT, usually missed |
| `LossHistory_ClaimStatus_SubrogationCode_A` | No entry | → GPT, usually missed |

These fields also exist as rows B, C, D, E — so the total number of misrouted fields was 7 × 5 = 35 fields going to GPT unnecessarily.

### 2. Extraction Schema Missing Sub-fields (FIXED)

The `loss_history` extraction schema in `extraction_service.py` only had:
`date`, `description`, `amount`, `paid`, `claim_number`, `open` (boolean)

The missing fact sub-keys (`claim_date`, `reserved_amount`, `line_of_business`, `open_code`, `subrogation_code`) meant there was nothing in the extracted facts for the registry to pull from — even after adding registry entries.

### 3. `CommercialPolicy_Question_*Code_A` Fields — No Pass 1 Rules (ONGOING)

16 fields like `CommercialPolicy_Question_KAACode_A`, `CommercialPolicy_Question_ABCCode_A`, etc. are Y/N underwriting question codes. They have:
- No entry in `_ACORD_FIELD_RULES`
- No entry in `_INDICATOR_RULES`
- No equivalent extracted fact key

They go to GPT as UNMATCHED but GPT consistently returns null for them. These need either:
- Dedicated extracted fact keys per question (complex — 16 separate questions)
- Hardcoded `_ACORD_FIELD_RULES` entries with a new `commercial_policy_questions` fact dict
- Or improved GPT prompting (the 263-field prompt is ~194K chars which may cause attention failure)

### 4. ACORD 133 False Trigger (FIXED)

The Builders Risk form (ACORD 133) was being recommended for every general contractor because the keyword set included generic terms like "builder", "construction project", "new construction", "renovation" — all present in any contractor application.

---

## Fixes Applied

### Fix 1 — `backend/services/extraction_service.py`

**What changed:** Extended `loss_history` list schema with 5 new sub-fields.

**Before:**
```python
'  "loss_history": [{"date": string or null, "description": string or null, '
'"amount": string or null, "paid": string or null, "claim_number": string or null, '
'"open": boolean}],\n'
```

**After:**
```python
'  "loss_history": [{"date": string or null, "claim_date": string or null, '
'"description": string or null, "amount": string or null, "paid": string or null, '
'"reserved_amount": string or null, "claim_number": string or null, '
'"line_of_business": string or null, "open": boolean, '
'"open_code": "O" or "C" or null, "subrogation_code": "Y" or "N" or null}],\n'
```

**Also added RULE 7** in the extraction instructions explaining each new field:
- `date` = occurrence/loss date
- `claim_date` = date claim was filed/reported (can differ from occurrence date)
- `open_code` = "O" for open, "C" for closed (text code version of the `open` boolean)
- `subrogation_code` = "Y" if subrogation being pursued, "N" if not
- `reserved_amount` = reserves held but not yet paid (distinct from `paid`)
- `line_of_business` = line of insurance the claim falls under ("GL", "Auto", "Property", etc.)

> **Note:** The extraction caches results. These new fields only appear on the **next fresh extraction** (after cache expiry or with new document content). Old cached results won't have them.

---

### Fix 2 — `backend/services/pdf_service.py` — `_SCHEDULE_REGISTRY`

**What changed:** Added 7 new registry entries to map ACORD 125 schema field names to the correct `loss_history` fact sub-keys.

**Added entries (lines ~148–161):**
```python
"LossHistory_ClaimDate":                  _ScheduleDef("loss_history", "claim_date"),
"LossHistory_OccurrenceDescription":      _ScheduleDef("loss_history", "description"),
"LossHistory_PaidAmount":                 _ScheduleDef("loss_history", "paid"),
"LossHistory_ReservedAmount":             _ScheduleDef("loss_history", "reserved_amount"),
"LossHistory_LineOfBusiness":             _ScheduleDef("loss_history", "line_of_business"),
"LossHistory_ClaimStatus_OpenCode":       _ScheduleDef("loss_history", "open_code"),
"LossHistory_ClaimStatus_SubrogationCode":_ScheduleDef("loss_history", "subrogation_code"),
```

**Impact:** ~35 fields (7 base names × rows A–E) moved from GPT-territory to Pass 1 deterministic fills. `blank_sched` count rises (rows C/D/E correctly resolve to empty when no 3rd/4th/5th claim exists — this is correct behavior, not a bug).

**How `_resolve_schedule_row` handles the new types:**
- `open_code` returns "O" or "C" (string) — no boolean conversion path hit
- `subrogation_code` returns "Y" or "N" (string) — same
- `LossHistory_OpenIndicator` (existing) uses the `open` boolean key and correctly converts to "Yes"/"No" via the `isinstance(val, bool)` branch at line ~235

---

### Fix 3 — `backend/services/form_service.py` — ACORD 133 Keyword Tightening

**What changed:** Removed overly broad construction keywords from the ACORD 133 (Builders Risk) trigger set.

**Before:**
```python
_133_kw = {
    "builder", "builders risk", "under construction", "renovation",
    "project value", "completion date", "construction loan",
    "project cost", "ground-up construction", "new construction",
    "builder's risk", "construction project", "contract value",
}
```

**After:**
```python
_133_kw = {
    "builders risk", "builder's risk", "course of construction",
    "construction loan", "ground-up construction",
}
```

**Why:** "builder", "construction project", "new construction", "renovation", "project value", "completion date", "contract value" all appear naturally in any general contractor application. This caused ACORD 133 to be recommended for every contractor submission even when no builders risk project was involved. The `has_builders_risk` LLM-extracted flag remains as the primary trigger and is accurate because the extraction model evaluates context, not just keywords.

---

## Pass 1 Fill Rate — How 207 Fields Get Filled Deterministically

This is a common point of confusion: there are far fewer than 207 non-None `_ACORD_FIELD_RULES` entries, yet Pass 1 fills 207 fields.

**Three mechanisms contribute:**

1. **`_ACORD_FIELD_RULES` scalar facts** (~80 fields): Text fields like `NamedInsured_FullName_A`, addresses, dates, FEIN — mapped directly from scalar fact keys.

2. **`_INDICATOR_RULES` via `_derive_indicator`** (~100+ fields): Every matched checkbox field returns "Yes" OR "No" — both are non-null and count as deterministic fills. This is why the count is high: entity type checkboxes (9 types × named insured slots), LOB checkboxes (16+), business type (10), billing plan, hired/non-owned auto, valuation method, GL form type, etc. — all get explicit Yes/No.

3. **`_resolve_schedule_row`** (~27 fields): Repeating list rows (loss history A/B, prior coverage A/B/C, etc.) resolved from structured fact lists.

**`_is_nonfillable_field` blocks 68 fields from GPT entirely** — substrings: `"Signature"`, `"_Sig"`, `"InsurerLetterCode"`, `"Attachment_"`, `"Hazard_"`, `"Premium"`, `"Rate_"`, `"Revision"`, `"EditionIdentifier"`, `"NeedAppearances"`, `"Underwriter"`, `"CarrierCode"`, `"PolicyNumber_Carrier"`.

---

## Form Recommendation Scoring (Quick Reference)

Located in `backend/services/form_service.py`:

```
blended_confidence = 0.6 × field_coverage + 0.4 × trigger_weight
floor              = trigger_weight × 0.55  (triggered forms never buried)
```

**Trigger weights:**
- `1.0` — always required (ACORD 125)
- `0.95` — flag-based triggers (has_general_liability, is_contractor, has_workers_comp, etc.)
- `0.85` — keyword/rule-based triggers (ACORD 101, 133, 186 keyword fallback)
- `0.65` — state-unknown auto variants

**Forms without fieldmap → `field_coverage = 0` → `confidence = trigger_weight` directly.**

All fieldmaps except ACORD 125 were moved to `backend/forms_database/deprecated/`. ACORD 125 is the only form with field-coverage-based scoring.

---

## Dummy Answers File

**File:** `backend/forms_schemas/ACORD_125_dummy_answers.json`

The dummy answers file was comprehensively rewritten to cover all 548 ACORD 125 schema fields, including:
- Full AdditionalInterest block (Arapahoe County as certificate holder)
- CommercialPolicy_Question_*Code_A Y/N answers (16 fields)
- 3-year PriorCoverage detail (carriers, policy numbers, dates)
- Detailed LossHistory with new field names matching the schema:
  - `LossHistory_OccurrenceDescription_A/B` (not `LossHistory_LossDescription`)
  - `LossHistory_PaidAmount_A/B` (not `LossHistory_AmountPaid`)
  - `LossHistory_ClaimDate_A/B`
  - `LossHistory_ReservedAmount_A/B`
  - `LossHistory_ClaimStatus_SubrogationCode_A/B`
  - `LossHistory_ClaimStatus_OpenCode_A/B`
- Signature block fields
- BusinessType using correct schema names:
  - `BusinessInformation_BusinessType_RetailIndicator_A` (NOT `MercantileIndicator`)
  - `BusinessInformation_BusinessType_WholesaleIndicator_A` (NOT `WholesalerIndicator`)

---

## Session 2 Fixes (2026-05-25) — OpenAI SDK & Runaway Loop

### Fix 4 — `backend/config/settings.py` — `max_completion_tokens` Parameter Routing

**Problem:** `gpt-5.x` and `o1/o3/o4` model families reject `max_tokens` with HTTP 400:
`"Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."`

This caused every extraction chunk to fail with HTTP 400 → 3 retries per chunk → 18 failed calls → majority-failed → 10 smaller chunks × 3 retries = 48 total wasted API calls. The entire extraction returned empty data.

**Fix:** Added `_uses_max_completion_tokens(model)` helper and dynamic parameter selection in `_openai_chat`:

```python
def _uses_max_completion_tokens(model: str) -> bool:
    m = model.lower()
    return m.startswith("o1") or m.startswith("o3") or m.startswith("o4") or "gpt-5" in m

# In _openai_chat:
token_param = "max_completion_tokens" if _uses_max_completion_tokens(model) else "max_tokens"
r = await client.chat.completions.create(
    model=model, messages=messages, temperature=temperature,
    **{token_param: max_tokens},
)
```

**Note:** `_openai_chat` only retries on 429/500/502/503 — NOT 400. The extraction service's chunk-retry loop was the one burning 3 retries per chunk on permanent 400s (see Fix 5).

---

### Fix 5 — `backend/services/extraction_service.py` — Fail-Fast on Permanent Errors

**Problem:** The `_one()` function inside `_gather_chunks_async` (line ~1834) catches all exceptions and retries them 3 times. HTTP 400 and `TypeError` (SDK signature mismatch) are **permanent** errors — retrying will never succeed but burns API quota and creates runaway loops.

**Root cause of the runaway loop** (user had to suspend Render service to stop it):
1. Each page refresh/re-upload created a new job
2. Each job: 6 chunks × 3 retries = 18 failed calls → majority-failed → 10 smaller chunks × 3 retries = 30 more = **48 wasted calls per document**
3. Watchdog could re-queue failed jobs up to 5 times

**Fix:** Added permanent-error guard before the retry sleep:

```python
except Exception as ex:
    # HTTP 400 = permanent API error (bad parameter, unsupported model flag)
    # TypeError = SDK signature mismatch (e.g. unknown kwarg in installed openai version)
    # AttributeError = SDK shape mismatch
    if (
        getattr(ex, "status_code", None) == 400
        or isinstance(ex, (TypeError, AttributeError))
    ):
        logger.error(f"chunk {idx}: permanent error — not retrying: {type(ex).__name__}: {ex}")
        raise
    # ... rest of retry logic
```

**Result:** Chunks now fail in 1 attempt instead of 3. No more 48-call storms.

---

### Fix 6 — `backend/requirements.txt` — OpenAI SDK Upgraded 1.10.0 → 1.54.4

**Problem:** `openai==1.10.0` (Jan 2024) does not know about `max_completion_tokens` — it raises `TypeError: AsyncCompletions.create() got an unexpected keyword argument 'max_completion_tokens'` at the Python SDK level (before any HTTP call). This is a `TypeError`, not an HTTP 400, so the status_code guard alone was insufficient.

**Fix:** Bumped to `openai==1.54.4` in `requirements.txt`. The Fix 5 `TypeError` guard provides defense-in-depth for any future SDK mismatches.

**Local venv:** Run `pip install openai==1.54.4` in the backend venv (done — confirmed installed successfully).

**Render:** Redeploy picks up the new version via `pip install -r requirements.txt`.

---

### Env Var Discrepancy — Two Separate LLM Model Variables

**Important:** There are **two separate env vars** controlling which model is used:

| Env Var | Used by | Default | Purpose |
|---------|---------|---------|---------|
| `LLM_MODEL` | `extraction_service.py` | `gpt-4.1-nano` | Extraction (OCR text → facts) |
| `GPT_MODEL` | `pdf_service.py` line 23 | `gpt-4.1-nano` | Form fill Pass 2 (GPT filling unmatched fields) |

Setting only `LLM_MODEL=gpt-5.4-mini` in Render will upgrade extraction but **not** form-fill. Both must be set.

**Render dashboard — set on BOTH web and worker services:**
```
LLM_MODEL = gpt-5.4-mini
GPT_MODEL  = gpt-5.4-mini
```

**Observed in logs (12:25 run):** Extraction used mini (14s per chunk), but form-fill showed `model=gpt-4.1-nano` because `GPT_MODEL` was not set.

**Fill rate impact:** Setting `GPT_MODEL=gpt-5.4-mini` expected to increase ACORD 126 form fill from 4/187 (2%) to ~95/187 (51%) based on prior model comparison.

---

## Outstanding Issues (Not Yet Fixed)

### 1. `CommercialPolicy_Question_*Code_A` — 16 Y/N Fields Not Filled

Fields: `KAACode`, `ABCCode`, `AAHCode`, `AADCode`, `KABCode`, `KAMCode`, `KANCode`, `KAOCode`, `AAICode`, `AAJCode`, `AABCode`, `AAKCode`, `ABBCode`, `KACCode`, `KADCode`, `KAECode`

No Pass 1 rules, no extraction fact keys. These always go to GPT but GPT returns null even when the source document explicitly contains "Y" or "N" for them. Suspected cause: prompt is ~194K chars and GPT loses attention on deeply embedded single-character values in a large JSON block.

**Proposed fix (not yet implemented):**
- Add a `commercial_policy_questions` dict to the extraction schema, keyed by code (e.g. `{"KAA": "Y", "ABC": "N", ...}`)
- Add `_ACORD_FIELD_RULES` entries that pull from this dict: `"CommercialPolicy_Question_KAACode": ("commercial_policy_questions", "KAA")`

### 2. Diagnostic Logging in `_absorb` (pdf_service.py)

Diagnostic `logger.debug` / `logger.info` statements added during debugging are still present in the `_absorb` function. Not harmful but adds noise. Confirm with user before removing.

### 3. GPT_MODEL and LLM_MODEL Consolidation (Not Yet Done)

Two separate env vars (`LLM_MODEL` for extraction, `GPT_MODEL` for form-fill) is a footgun — setting one and forgetting the other leaves half the system on the old model. Consider unifying to a single `LLM_MODEL` var read by both services.

### 4. SQS / ARQ Async Processing — Ongoing Blocker

Documented in CLAUDE.md. Not related to form filling but blocks background job processing for production workflows.

### 5. Worker numInstances for 3 Concurrent Demo Users

`render.yaml` has `numInstances: 2` for the worker. For 3 truly simultaneous demo users each submitting a document, the 3rd user will queue until a worker frees. Bump to `numInstances: 3` before investor demos if needed.

---

## Key File Locations

| File | Role |
|------|------|
| `backend/services/pdf_service.py` | Pass 1 rules, schedule registry, GPT fill, `map_facts_to_form` |
| `backend/services/extraction_service.py` | LLM extraction schema, fact key definitions, merge logic |
| `backend/services/form_service.py` | Form recommendation engine, scoring, flag-to-form mapping |
| `backend/forms_schemas/ACORD_125_schema.json` | 548 ACORD 125 field definitions (ft, tu, required) |
| `backend/forms_schemas/ACORD_125_dummy_answers.json` | Comprehensive test document with realistic values for all fields |
| `backend/forms_database/deprecated/` | Old fieldmap JSONs (moved here, no longer used for scoring) |
| `backend/requirements.txt` | Python dependencies — openai pinned to 1.54.4 (was 1.10.0) |

---

## Infrastructure Notes (Render Deployment)

| Service | Setting | Value | Notes |
|---------|---------|-------|-------|
| Web | `WEB_CONCURRENCY` | `2` | 2 gunicorn+uvicorn workers |
| Web | `ENABLE_ASYNC_PROCESSING` | `true` | Web tier enqueues only, worker processes |
| Web | `LLM_MAX_CONCURRENT` | `15` | Redis-distributed cap across all processes |
| Web | `OCR_PROVIDER` | `easyocr` | Must change to `textract` — easyocr 400MB × 2 workers = 800MB, OOMs on 512MB Starter |
| Worker | `numInstances` | `2` | Handles 2 simultaneous jobs; 3rd queues |
| Worker | `WORKER_MAX_JOB_RETRIES` | `5` | Dead-letters job after 5 watchdog resets |
| Worker | `STUCK_JOB_THRESHOLD_MINUTES` | `30` | Jobs in `processing` >30min → reset to `pending` |
| Both | `LLM_MODEL` | `gpt-5.4-mini` | Set in Render dashboard |
| Both | `GPT_MODEL` | `gpt-5.4-mini` | **Must also set** — separate var for form-fill |

**RAM requirement:** Render Standard (2GB) required minimum with easyocr. If switching to Textract, Starter (512MB) may work but Standard is safer.

**OpenAI Tier:** Tier 1 (500 RPM) is sufficient for 2–3 demo users. Nano retry failures were model quality issues, not rate limits.
