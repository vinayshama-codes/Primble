# Form Extensibility Guide

This document answers the four extensibility audit questions and describes how to add a new ACORD form template.

---

## Q1: Checklist to add a new form (e.g. ACORD 130)

1. **Drop the PDF template** into `backend/templates/ACORD_130.pdf`.
2. **Create the form JSON** at `backend/forms_database/ACORD_130.json` with at minimum:
   ```json
   {
     "form_id": "ACORD_130",
     "form_name": "ACORD 130 - Workers Compensation Application",
     "template_file": "ACORD_130.pdf",
     "always_include": false,
     "matching_flags": ["has_workers_comp"],
     "required_fields": ["applicant_name", "effective_date", ...],
     "tier1_minimum_fields": [...]
   }
   ```
3. **Create the fieldmap** at `backend/forms_database/ACORD_ACORD_130_fieldmap.json` — maps PDF field names to fact-keys. Used by `pdf_service.map_facts_to_form` and `form_service._build_form_required_keys`.
4. **Update `forms_index.json`** — change the existing entry from:
   ```json
   { "form_id": "ACORD_130", ..., "template_pending": true }
   ```
   to:
   ```json
   { "form_id": "ACORD_130", "template_file": "ACORD_130.pdf", "detail_file": "ACORD_130.json" }
   ```
5. **Remove `template_pending=True`** from the `_add("ACORD_130", ...)` call in `backend/services/form_service.py` (`match_forms_deterministic`).

**Minimum diff:** Steps 1–4 are config/data only. Step 5 is a one-line code change (remove `template_pending=True`).

---

## Q2: Is adding a new template a CONFIG-ONLY operation?

**Almost — one line of code must change.** Trigger logic in `match_forms_deterministic` (form_service.py) uses an explicit `template_pending=True` flag on the `_add(...)` call. Removing that flag for an existing pending form requires editing one line of Python.

For a **brand-new form** with no existing `_add(...)` call, you would also need to add the trigger rule (e.g. `if flags.get("has_new_flag"): _add("ACORD_NNN", ...)`). That is by design — trigger logic encodes business rules that cannot be inferred from the PDF alone.

**To make activation fully config-only for pending→active transitions**, `form_service.py` could read `template_pending` directly from `forms_index.json` instead of having it as a Python keyword argument. Ticket raised for future sprint.

---

## Q3: Hardcoded form-count assumptions or per-form if/elif chains?

**Trigger rules** in `match_forms_deterministic` are per-form `if` blocks, which is by design: each form has its own activation condition. These are not fragile `elif` chains — they are independent guards, so adding a new form adds one new `if` block without touching existing ones.

**No hardcoded form counts** exist in the codebase. `load_all_forms()` reads from `forms_index.json` dynamically. The admin endpoint `/api/admin/forms-status` derives all counts at runtime.

**One hardcoded list to watch:** `filter_available_forms` in `form_service.py` checks `os.path.exists(TEMPLATE_DIR / template_file)` — this is data-driven (reads from form JSON), not hardcoded.

No `if form_id == "ACORD_125": ...` style conditionals exist in the hot path.

---

## Q4: Is trigger logic and field map isolated per form?

**Yes — each form is isolated:**

| Concern | Location | Isolation |
|---------|----------|-----------|
| Trigger rule | `match_forms_deterministic` in `form_service.py` | One `if` block per form |
| Field map | `backend/forms_database/ACORD_<id>_fieldmap.json` | One file per form |
| Form metadata / required fields | `backend/forms_database/<id>.json` | One file per form |
| PDF template | `backend/templates/<id>.pdf` | One file per form |

Shared functions (`_add`, `_compute_confidence`, `_score_field_coverage`) are generic helpers that work for any form. They contain zero per-form logic.

The fieldmap and form JSON are loaded by `pdf_service.map_facts_to_form` and `form_service._build_form_required_keys` respectively — both are data-driven lookups keyed by `form_id`.

---

## Currently Active vs Pending Forms

| Status | Forms |
|--------|-------|
| **Active** (PDF generates) | ACORD 25, ACORD 125, ACORD 126, ACORD 140 |
| **Pending** (shown in UI, no PDF) | ACORD 127, ACORD 130, ACORD 131, ACORD 141 |
| **No trigger yet** | ACORD 101, ACORD 133, ACORD 160, ACORD 186, ACORD 28 |
