# SQS Model - Agreed Design (Package SQS vs Form SQS)

**Status:** Agreed in design discussion 2026-06-18. NOT yet implemented.
**Scope:** How Package SQS and Form SQS are computed, how stops cap them, how they update live, and the download/submission label.
**Related:** Builds on the existing single-form parity + pillar-averaging invariant already in `backend/services/sqs_service.py` (`calculate_package_sqs`).

---

## 1. The two scores

```
Form SQS     = weighted_sum(that form's own 6 pillars)      - form-scoped caps
Package SQS  = weighted_sum(the package's OWN 6 pillars)     - package-scoped caps
```

**The Package is computed INDEPENDENTLY of the per-form scores** (the current,
client-approved model). It does NOT average the per-form headlines and does NOT
average the per-form pillars. Each package pillar is derived directly from the
merged facts / flags / session evidence by the package-level calculators, and the
headline is the weighted sum of those six pillars. Because the package uses its
own P1 structural blend (tier1/tier2/form-fill) and none of the per-form
structural cap gates, plus cross-form caps no single form can see, the package
score genuinely differs from any individual form - even when only one form is in
the submission. A short UI explainer tells the user this, so divergence reads as
insight, not a bug.

---

## 2. Pillars

The package computes its OWN six pillars from the merged facts (identical for one
form or many - no averaging, no per-form pinning):
  - Structural Completeness 25% - package blend: tier1*0.35 + tier2*0.30 + form-fill-avg*0.35
  - Exposure Consistency 25% - `_calculate_exposure_consistency(facts, flags, hard_cross, warn_cross)`
  - Property Integrity 15% - `_calculate_cope_score(facts, flags)`
  - Loss History Alignment 15% - `calculate_p4_loss_history(facts, flags, ...)`
  - Umbrella Adequacy 10% - `_calculate_umbrella_adequacy(facts, flags)` (None = N/A)
  - Narrative Quality 10% - `_calculate_narrative_quality(facts, ...)`
  - Umbrella N/A -> its 10% is redistributed proportionally across the other five.
  - Headline = WEIGHTED SUM of these six package pillars.
  - **Single form:** the package still computes its own pillars/headline - it is
    NOT pinned to the form's `sqs_score`. The two can legitimately differ.
  - Status: in code (`calculate_package_sqs`).

---

## 3. Capping rule (the new behaviour)

Stops are classified by **origin**, and the classification persists until the stop is resolved.

| Stop origin | Caps what | Lifts when |
|---|---|---|
| **Pre-selection** - present on the initial / recommendation screen, before forms are chosen (doc-consistency from `check_doc_consistency` + field-level from `evaluate_stops`) | **ALL forms + package** (hard -> 60, soft -> 85) | the stop is actually resolved |
| **Post-generation, cross-form** - from `run_cross_form_validation`, only computable once forms exist | **package only** | resolved |
| **Post-generation, form-specific** - a field stop that newly appears (rare) | **that one form only** | resolved |

Rules:
- A pre-selection stop **stays global** even after forms are generated. It keeps capping every form + the package until the user resolves it via **ARQ answers, recommendation answers, or filling form values**.
- Caps are **live** at every recompute. No stops remaining -> no cap -> the true score shows.
- **Net effect:** Form cap = pre-selection (global) stops. Package cap = pre-selection stops + cross-form stops. That extra cross-form layer is exactly "the package has a little more than the form."

Hard = cap at 60. Soft / warning = cap at 85. Hard and soft are treated the same way (each caps to its own level).

---

## 4. Live updates

Every ARQ answer / recommendation answer / field edit rewrites `facts`, then recomputes every form SQS, then recomputes the package SQS.
- Single form: both move in lockstep (parity).
- Multiple forms: the edited form moves more; the package moves less (it is an average).

---

## 5. Download / submission label (package-driven)

**Current (as the code stands today)** - `frontend/src/components/form/AcordModal.jsx:3496`:

```
package_sqs_score >= 90  ->  "Ready to Send Submission"
package_sqs_score <  90  ->  "Ready to Download Forms"
```

**Desired:**

```
package_sqs_score >  90  ->  "Ready for submission"
package_sqs_score <= 90  ->  "Ready to Download Forms"
```

Two tiny deltas:
1. The boundary - today 90 exactly shows "Ready to Send Submission"; we want 90 to show "Ready to Download Forms" (i.e. `>` instead of `>=`).
2. Wording - "Ready to Send Submission" vs "Ready for submission".

Separately, note the **tier** label (a different thing) also uses `>= 90` -> "Submission Ready" in `calculate_package_sqs`. We keep those consistent.

Why this is safe: a hard stop caps the package at 60 (<= 90), so a conflicted bundle can never show "Ready for submission" - the cap gates the label automatically, no extra logic needed.

---

## 6. UI copy (locked)

```
SQS
  Submission completeness and underwriting readiness
Match %
  How strongly uploaded documents fit each form (shown per form, not here)
Score
  Weighted sum of the 6 pillars - not a plain average. Weights shown as (%) on each row below.

Form SQS rates each form on its own. Package SQS rates the whole submission
and includes cross-form checks, so the two can differ.
```

All plain hyphens, no em-dashes (project UI rule).

---

## 7. Built vs. needs work

| Item | Status |
|------|--------|
| Package computes its OWN pillars (independent of forms) | Done (see section 8, final change) |
| Single form NOT pinned to form score (genuine divergence) | Done |
| Live recompute on ARQ / edit | Done |
| 60 / 85 caps applied live | Done |
| Forms not capped by cross-form stops; package still is | Done (2-line change, see section 8) |
| Label boundary `>90` + wording | Done |
| UI explainer line (Form vs Package) | Done |

---

## 8. Implementation surface - AS IMPLEMENTED

**The snapshot/partition approach originally sketched here was not needed.** While tracing the code, two facts made it redundant:

1. The per-form scorer (`calculate_sqs`) caps off its `hard_stops`/`soft_stops` **param** plus the form's own structural gates (COPE/umbrella/property). `cross_issues_full` only feeds labels/breakdown - it does **not** cap. So a form is capped by exactly the stop list its caller passes.
2. Field-level stops are recomputed live (`evaluate_stops`) at every stage, so the recomputed field-level set already IS the live "global" stop set - a persisted snapshot would be redundant state.

So the design's net effect ("forms = global stops; package = global + cross-form") reduces to: **stop passing cross-form stops to the per-form scorer in the two recompute paths.** Generation already did this (per-form uses `session.hard_stops`, which has no cross-form); only the recompute paths leaked `cf_*` into the per-form cap.

**Actual changes made:**
- `backend/routes/form_routes.py` - `update_pdf` per-form `calculate_sqs`: `hard_stops`/`soft_stops` changed from `fresh_hard_stops`/`fresh_soft_stops` (field + cross-form) to `list(_re_hard)`/`list(_re_soft)` (field-level only). Package call left untouched (still capped by cross-form via `fresh_*` + `cross_issues`).
- `backend/services/arq_service.py` - `recalculate_session_scores` per-form `calculate_sqs`: `hard_stops`/`soft_stops` changed from the combined `hard_stops`/`soft_stops` to `re_hard`/`re_soft` (field-level only). Package call left untouched.
- `backend/tests/test_sqs_scoring.py` - added `test_cross_form_issue_does_not_cap_per_form_score` guarding the invariant the change relies on (cross_issues_full does not cap a form; a real hard stop still caps at 60).
- `frontend/src/components/form/AcordModal.jsx` - banner boundary `>=90`->`>90` + wording "Ready to Send Submission"->"Ready for submission"; added the Form-vs-Package explainer line to the existing SQS legend box.
- `backend/services/sqs_service.py` - `calculate_package_sqs` tier ladder top boundary `>= 90` -> `> 90` so the package `tier` ("Submission Ready") matches the submission banner at exactly 90. Only this boundary changed - no other tiers, weights, or scoring touched. The non-live `calculate_package_sqs_spec_compliant` variant and the per-form `calculate_sqs` tier ladder were left as-is.

**Not changed (deliberately):** scoring math, weights, pillar/averaging logic, single-form parity, generation path, clarity/lite path, the per-form tier ladder, and `process_single_form` - all already correct or out of scope. No new session state added.

**Edge note:** the "post-generation form-specific stop caps only its form" sub-case from section 3 is not separately implemented - field-level stops cap all forms (their existing behaviour, and consistent with "global stops cap all forms"). Cross-form stops cap the package only, which was the actual gap.

---

### Final change - Package made fully INDEPENDENT (supersedes the averaging/anchor model)

Per client direction, the package is now its own genuinely-separate number instead of being averaged from / pinned to the per-form scores. In `backend/services/sqs_service.py` -> `calculate_package_sqs`:

- **Removed** the per-form pillar-averaging override (the block that replaced p1-p6 with `_pillar_avg(...)` across forms).
- **Removed** the single-form anchor block (which pinned the headline to the one form's `sqs_score` then re-applied cross caps).
- **Kept** the package's own pillar computation (p1 = tier1/tier2/form-fill blend; p2-p6 from the package-level calculators on facts) and the weighted-sum headline.
- **Kept the cap block exactly as-is**: `if hard_stops or hard_cross: min(raw,60); elif soft_stops: min(raw,85)`. Cross-document conflicts (building-value / FEIN, etc.) are emitted as `hard_stop` -> they cap the package at 60. (`warn_cross` continues to feed the exposure pillar as a deduction; it is not a separate ceiling.)

Net effect: the package score is now computed independently of the form for both single-form and multi-form submissions. The per-form scorer (`calculate_sqs`) was NOT touched.

**Pillar audit (client clarification doc):** verified against the live code - P2 exposure, P3 COPE, P4 loss (incl. claim-frequency-vs-exposure at sqs_service.py claims_per_m), P5 umbrella (excess folded in via the `has_umbrella` extraction flag), and P6 narrative all already match the client spec; 5yr-loss requires prior carrier for the full 100 (without carrier = 90). The only genuine gap - a "Supporting Documents" sub-component in P1 - was deferred (client said "keep V1 / future release").

**Tests:** `backend/tests/test_sqs_scoring.py` package tests rewritten to lock the independent-computation behavior (`test_single_form_package_computed_independently`, `test_single_form_package_hard_cross_issue_caps_at_60`, `test_single_form_package_soft_cross_issue_never_raises_package`, `test_multi_form_package_pillars_computed_independently`). Two pre-existing stale tests (unrelated to this change) were aligned to current APIs: `test_document_classification` (2->3 tuple from `_calculate_narrative_quality`) and `test_arq_acord125_missing_only` (exclude synthetic narrative-enrichment questions, matching its own documented intent). Full backend suite: 310 passed, 2 skipped.
