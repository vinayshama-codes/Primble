# Primble - Changes & Product Decisions (Session by Vinay)

---

## Workstream 4 — ACORD Form Recommendation Logic: Audit & Fix

### What Was Audited

A full end-to-end code audit was performed against all 7 engineering action items from the Beta Report §7.2 (Workstream 4). Every requirement was verified directly from source code — engine, both API pipelines, the producer-questionnaire feedback loop, and the React rendering layer.

---

## Audit Results

### Fully Implemented (No Changes Needed)

| Item | Requirement | Verdict |
|------|------------|---------|
| 7.2 Item 1 | Form recommendation reasons | Implemented |
| 7.2 Item 2 | Recommendation tiers (Required / Recommended / Optional / Needs Confirmation) | Implemented |
| 7.2 Item 3 | Confidence indicators (low fill score does not bury a relevant form) | Implemented |
| 7.2 Item 4 | State-specific form filtering (CA/CO only when state + exposure match) | Implemented |
| 7.2 Item 6 | Distinguish uploaded source documents from forms to generate | Implemented |
| 7.2 Item 7 | Line-of-business logic for ranking (contractor grouping example) | Implemented |
| ACORD 101 escalation | Large losses, data conflicts, prior carrier issues, unusual operations → Recommended | Implemented |
| State form neutrality | 137/138 CA/CO always Needs Confirmation regardless of evidence | Implemented |

### Partially Implemented (Left As-Is Per Decision)

| Item | Requirement | Status |
|------|------------|--------|
| 7.2 Item 5 | Reduce overly broad recommendation lists | Partially implemented — see Product Decisions below |

---

## Open Gaps (Kept As-Is Per Instructions)

### Gap 1 — Item 5: Weakly-related forms are de-emphasized, not removed
Optional forms that serve none of the confirmed coverage lines and don't fit the detected business class are visually dimmed with an explanatory note, but they remain visible in the recommendation list. True removal or hiding of these forms has not been built.

**Status: Kept as-is. No change made.**

### Gap 2 — Item 5: "User-selected goals" is inferred, not user-entered
Coverage goals are derived from extracted LLM flags, not from an actual broker input. There is no goal-selection UI control on the recommendation screen.

**Status: Kept as-is. No change made.**

---

## Code Change Made

### Gap 3 — ACORD 131 Umbrella Tier Fix

**Problem:** The client stated clearly: *"Umbrella confirmed = ACORD 131 Required."* The other four primary line forms (ACORD 126, 127, 130, 140) all go Required on a confirmed LLM flag alone. ACORD 131 was the only exception — a confirmed umbrella flag without corroboration (no extracted umbrella limit and no literal "umbrella"/"excess liability" wording in the text) produced Needs Confirmation instead of Required. This directly contradicted the client's written rule and created an inconsistency across the five primary line forms.

**Fix:** ACORD 131 now goes Required on a confirmed `has_umbrella` flag alone, exactly like the other four primary line forms. Corroboration (an extracted umbrella limit or literal wording) now only refines the reason text shown to the broker — it no longer affects the tier.

**Tier behavior after fix:**
- Confirmed umbrella flag (with or without supporting limits/wording) → **Required**
- Dec-page umbrella line without the structured LLM flag → **Needs Confirmation** (unchanged)
- No flag and no line → form not added (unchanged)

**Files Changed:**

- `backend/services/form_service.py` — Updated ACORD 131 tier logic: tier is now driven purely by whether the LLM confirmed the flag; corroboration only refines the reason label.
- `backend/tests/test_form_recommendation.py` — Updated the one regression test that locked the old client-contradicting behavior (`test_131_needs_confirmation_when_umbrella_flag_uncorroborated` renamed and updated to `test_131_required_when_umbrella_flag_confirmed_even_uncorroborated`).

**Test Results After Fix:**
- Recommendation suite: 79/79 passed
- Combined suite (recommendation + SQS scoring + workstream-3): 181/181 passed via pytest

---

## Product Decisions (Confirmed by Client — Brent)

### 1. Required vs Recommended Boundary
If coverage is confirmed and the form is the primary form for that coverage line, it is **Required**. Supplemental forms are **Recommended**.
- GL confirmed = ACORD 126 Required
- Auto confirmed = ACORD 127 Required
- WC confirmed = ACORD 130 Required
- Umbrella confirmed = ACORD 131 Required
- Property confirmed = ACORD 140 Required
- ACORD 186, 141, 133 remain Recommended (supplemental)

### 2. ACORD 101 Escalation Rule
ACORD 101 is not always Optional. It escalates to **Recommended** when Primble detects:
- Large losses (claim count > 3, or total incurred > $100k)
- Data conflicts or cross-document inconsistencies
- Missing context (multi-line submission with no operations description)
- Prior carrier adverse action (nonrenewal, cancellation, declination — confirmed by producer)
- Unusual financial operations (payroll/revenue ratio > 85%)
- Subcontracting > 30% with no WC payroll on file

It stays **Optional** for minor clarifications (vague operations, split limit gaps, renewal missing prior carrier name).

### 3. State-Specific Forms (137/138 CA/CO) Stay at Needs Confirmation
Even when auto coverage is confirmed and the insured is clearly in California or Colorado, ACORD 137 CA/CO and ACORD 138 CA/CO remain at **Needs Confirmation**. Not every carrier requires these forms. This keeps Primble carrier-neutral.

Display reason: *"State-specific supplemental form may be required depending on carrier requirements."*

### 4. Prior Carrier Issues — Do Not Over-Trigger ACORD 101
ACORD 101 must NOT be triggered simply because a prior carrier is present (almost every submission has one). Only trigger on genuine underwriting concerns: nonrenewal, cancellation, carrier declined renewal, carrier exited market, coverage restrictions imposed, significant adverse loss history.

For V1, a producer questionnaire ("Why are you marketing this account?") is the more reliable signal than document extraction for carrier-leave reasons.

### 5. Recommendation List Reduction — Current Approach Accepted
Tight trigger logic (requiring money/limit signals near coverage keywords, excluding ambiguous words like "building" or "payroll" alone) plus visual de-emphasis of weakly-related Optional forms is the current approach. True removal from the list was not built in this session and is a potential future enhancement if the client requests it.

---

## Workstream 6 — Loss History Pillar (§6.4): Audit, Bug Fixes & Product Decisions

### What Was Audited

Full source-code audit of the §6.4 Loss History requirements across `sqs_service.py`, `extraction_pipeline.py`, `extraction_service.py`, and `arq_service.py`. All 4 client engineering action items, all acceptance criteria, and client Q-answers on year tiers / recency / ownership were verified against actual code.

---

### Audit Results (Already Implemented - No Change Needed)

| Requirement | Verdict |
|-------------|---------|
| Loss-history states (10 states: no info, user attests, narrative attests, pending, uploaded, parsed, match insured, do-not-match, reconciled, conflicting) | Implemented |
| Tie loss runs to insured matching before crediting | Implemented - strong / moderate / possible / no-match tiers with hard cap on unmatched runs |
| Differentiate user confirmation vs narrative vs source-document evidence | Implemented - three distinct evidence channels with separate labels and state names |
| Update score and status after loss remediation (ARQ apply) | Implemented - answer mirrored into canonical facts + flag, recompute triggered |
| Year tiers: 5yr = 100, 3-4yr = 80, 1-2yr = 40 | Implemented |
| Pending loss runs = 70 | Implemented |
| User/narrative attests no losses = 60 | Implemented |
| No information = 25 | Implemented |
| Prior carrier +10 / missing -10 adjustment | Implemented on year-tier and uploaded paths; correctly NOT applied to attestation/pending/no-info floors |
| >90 day loss runs: warn + reduce score (max -25) | Implemented |
| High claim frequency warning and score reduction | Implemented |
| "No Known Losses" industry term surfaced to users | Implemented |

---

### Bugs Fixed

#### Fix 1 - "none" treated as affirmative no-loss attestation

**Problem:** The attestation parser's truthy-token set contained the literal string `"none"`. Since the falsy set did not contain it, `"none"` resolved to an affirmative "No Known Losses" - the same as a user answering "Yes." Every other null-handling path in the codebase (extraction null set, normalization, emptiness checks) treats `"none"` as "no value." Only this one token table flipped it to true, creating an inconsistency that could silently award loss-history credit on a null placeholder.

**Fix:** Removed `"none"` from the truthy-token set. An empty or null placeholder on the no-loss indicator is now correctly treated as "not attested."

**File:** `backend/services/sqs_service.py`

---

#### Fix 2 - Unknown recency received full credit

**Problem:** When the loss-run valuation date could not be determined from the document (i.e., the LLM did not extract a valuation date or a stated age), the scoring engine gave the full year-tier credit (up to 100) and only appended a soft advisory note. This violated the client's intent that full credit requires "currently valued" loss runs - an unverifiable date cannot meet that bar.

**Fix:** When recency is unverifiable (no valuation date and no stated age), a fixed -10 point penalty is applied and the warning message is updated to "recency unverified." This is below the maximum -25 penalty for a known-stale run (giving benefit of the doubt) but ensures full credit is not awarded for loss runs whose currency cannot be confirmed.

**Constant added:** `_LOSS_RECENCY_UNKNOWN_PEN = 10`

**Affected paths:** both the year-tier path (years >= 1) and the "uploaded but years not confirmed" path (has loss run doc, years = 0).

**File:** `backend/services/sqs_service.py`

---

### Product Decisions (Confirmed by Client — Brent, §6.4)

#### 1. Loss History is not a hard requirement for Quote Ready
Missing loss runs impact the score but do not block a submission. New ventures, pending runs from incumbent carriers, and attested no-loss accounts can all still be marketed and quoted. This is implemented - the no-information floor (25) and the attestation path (60) keep submissions moving.

#### 2. Scoring tiers (client-confirmed)
- 5 years current loss runs + prior carrier present = 100
- 5 years current loss runs, no prior carrier = 90 (100 base - 10 carrier adjustment)
- 3-4 years current = 80 base (+/-10 for carrier)
- 1-2 years current = 40 base (+/-10 for carrier)
- Loss runs requested / pending = 70 (no carrier adjustment applied)
- Insured attests no prior losses = 60 (no carrier adjustment applied)
- No loss information = 25 (no carrier adjustment applied)

Note: the scoring explanation shared with the client during beta testing incorrectly described "5yr, no prior carrier = 80." The code correctly computes 90. The client's own answer ("+10 for carrier, -10 for missing" as separate adjustments) is consistent with the code's 90, not the 80 in the explanation. No code change was made - the code was already correct.

#### 3. Ownership match hierarchy (client-confirmed)
- Strong: Name + FEIN or Name + Policy Number
- Moderate: Name + Address (client explicitly sanctioned this tier)
- Weak / Possible: Name only
- No match: name present but does not match
Confidence scoring applied based on match strength. The code already implements all four tiers.

#### 4. Unknown recency = capped credit
When the valuation date cannot be determined, a -10 point reduction is applied rather than awarding full credit. Client's "currently valued" requirement cannot be met by an unverifiable date.

---

*Last updated: 2026-06-19*
