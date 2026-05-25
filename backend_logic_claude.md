# Backend Logic — Bug Fixes & Analysis Log

> **Purpose:** Retain context across chat sessions. Documents every issue identified, root cause, and fix applied so new sessions can pick up exactly where this left off.
>
> **Project:** Acordly — ACORD Form Processing Platform
> **Last updated:** 2026-05-25

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

## Outstanding Issues (Not Yet Fixed)

### 1. `CommercialPolicy_Question_*Code_A` — 16 Y/N Fields Not Filled

Fields: `KAACode`, `ABCCode`, `AAHCode`, `AADCode`, `KABCode`, `KAMCode`, `KANCode`, `KAOCode`, `AAICode`, `AAJCode`, `AABCode`, `AAKCode`, `ABBCode`, `KACCode`, `KADCode`, `KAECode`

No Pass 1 rules, no extraction fact keys. These always go to GPT but GPT returns null even when the source document explicitly contains "Y" or "N" for them. Suspected cause: prompt is ~194K chars and GPT loses attention on deeply embedded single-character values in a large JSON block.

**Proposed fix (not yet implemented):**
- Add a `commercial_policy_questions` dict to the extraction schema, keyed by code (e.g. `{"KAA": "Y", "ABC": "N", ...}`)
- Add `_ACORD_FIELD_RULES` entries that pull from this dict: `"CommercialPolicy_Question_KAACode": ("commercial_policy_questions", "KAA")`

### 2. Diagnostic Logging in `_absorb` (pdf_service.py)

Diagnostic `logger.debug` / `logger.info` statements added during debugging are still present in the `_absorb` function. Not harmful but adds noise. Confirm with user before removing.

### 3. SQS / ARQ Async Processing — Ongoing Blocker

Documented in CLAUDE.md. Not related to form filling but blocks background job processing for production workflows.

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
