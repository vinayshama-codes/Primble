# V1 Master Plan - 20 Aug 2026

**This file is the running memory for V1.** It carries the rules, the to-do list, and
every change and decision made while implementing them. Different chats, one file.
Read this before starting any V1 task; append to it before ending one.

**Where things stand:** jump to **LIVE TEST RESULTS** for the current verdict on every
client requirement, and **C1 AT A GLANCE** for the issue ledger. The change log below has
the reasoning; those two have the answers.

---

## DOCUMENT PRECEDENCE

This master plan defines the changes and implementation requirements moving forward.

- Where this document conflicts with the existing `SQS_Scoring_Specification`, **this document takes precedence**.
- Where this document does not modify an existing scoring rule, the **current SQS specification remains authoritative**.
- Engineering should not introduce new insurance, scoring, validation, or questionnaire rules outside these documents **without product approval**.

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

## CORE V1 ENGINEERING PRINCIPLES

These rules apply throughout V1 and should guide implementation whenever a specific edge
case is not separately described.

### 1. One Canonical Fact
A material fact should have one canonical representation that feeds:
- Data Consistency
- SQS
- questionnaire / remediation
- generated forms
- Submission Brief
- E&O Audit Record

Different features should not independently determine different versions of the same
underlying fact.

### 2. Normalize Before Comparing
Primble should compare the **meaning** of facts, not raw extracted strings.
Formatting, terminology, abbreviations, document structure, and differing levels of
specificity should be normalized before deciding that two values conflict.

### 3. Missing Does Not Mean No
Lack of evidence must never automatically become:
- `No`
- `False`
- `$0`
- `0`
- `None`
- another unsupported value

Primble should distinguish between information that is actually negative and information
that simply was not found.

### 4. Do Not Silently Resolve Genuine Conflicts
If two materially incompatible values remain after normalization and scope matching,
Primble should not arbitrarily select one. The conflict should remain visible and route to
the **producer** for resolution.

### 5. Do Not Ask the Client to Perform Insurance Classification
The client questionnaire is for factual business and exposure information.
It should **not** ask clients to determine:
- NAICS
- SIC
- WC class codes
- GL class codes
- coverage symbols
- policy interpretation
- other insurance-specific classifications

### 6. Preserve Provenance
Material information should remain traceable through:

`Source -> Extracted Value -> Normalized Fact -> Human Changes -> Final Value -> SQS / Output`

### 7. Unknown Edge Cases Default to Producer Review
If Primble encounters a material field, exposure, condition, or conflict for which no V1
rule exists:
- preserve the information
- do not invent a value
- do not invent a new SQS penalty
- do not automatically ask the client
- surface the item to the producer when necessary
- give it no new scoring effect until a rule is explicitly defined

**"Needs Producer Review" is preferable to Primble or engineering improvising an insurance rule.**

---

## REFERENCE MATERIAL

Source documents this plan is built against. Read the relevant one before starting an item.

| Path | What it is | Use it for |
|------|-----------|------------|
| `SQS_Scoring_Specification.docx.pdf` | The existing scoring spec | Authoritative where this file does not override it (see DOCUMENT PRECEDENCE) |
| `125_reference/ACORD 125 - data map 8-19-26.pdf` | Vertafore's completed field-mapping example of ACORD 125 (2025/03), all pages | H6 ACORD 125 form-generation foundation. The field-by-field answer key |
| `125_reference/ACORD 125 - field completition 8-19-26.docx` | Client's written walkthrough: a synthetic account (Front Range Electrical Contractors LLC) and exactly what a correct 125 should and should not contain | C1 value states, C2 loss history, H6. **This is the master 125 test case** |
| `test_data_v1_c1/` + `backend/scripts/make_v1_c1_test_pdfs.py` | Four generated PDFs reproducing every section-1 defect, plus `README-HOW-TO-TEST.md` with 10 numbered checks | Live validation of C1. **Regenerate before every run.** Check 5 (the $3M/$1M umbrella conflict) is the gate; see LIVE TEST RESULTS for the scorecard. **Check 8 now expects TWO location rows** (file 5 carries a real Aurora premises) and **check 3 must require the scoped-row badge, not the absence of a row** - see C1-Q |
| `test_data_v1_c1/6_conflicting_dec.pdf` + `backend/scripts/make_v1_c1_adversarial_pdf.py` | The NEGATIVE control: a rival carrier's dec page planting seven disagreements that MUST fire, with Auto and Umbrella repeated identically to file 1 as an in-run control | **Run B.** Upload as a SEPARATE submission from Run A. `README-RUN-A-AND-B.md` is the scorecard. A quiet Run B means the checks are dead, not passing (C1-Q) |
| `CLAUDE.md` | Project brief + full historical fix log | Blast-radius checks. Do not treat as current truth without reading the code |
| `improving-ll.md` | LLM call registry, cost model, prompt rules | Mandatory before touching any prompt or batching |
| `FIX_TRACKING_2026-08-15.md` | Relationship-preservation fixes (policy/line identity) | C1 scope work builds directly on this |

### What the 125 reference establishes (client's own words, condensed)

1. **"Blank does not equal No."** If the source does not answer Question 9 (bankruptcy),
   Primble must output `Unverified - insured confirmation required`, not `N`. This is
   Principle 3, stated by the client against a concrete field.
2. **Four states for every material field**, and a forbidden fifth:
   - `VERIFIED` - source supports the value exactly
   - `CONFIRMED` - insured answered it through Primble
   - `NOT APPLICABLE` - intentionally blank
   - `UNRESOLVED` - information is needed before submission
   - **`ASSUMED` must not exist.** Client: *"That is where your hallucination /
     data-transfer problem starts."*
3. **A box existing is not permission to fill it.** NAIC code, GL class code, payment plan,
   policy premium, policy number: populate only from a verified source.
4. **Do not manufacture prior-carrier history.** Populate only the years the source
   substantiates; request the rest.
5. **A narrative phrase is not a loss history.** "No known losses" must not become a
   verified five-year record.
6. **Form edition**: client flagged ACORD 125 (2025/03) as the current edition and asked
   whether we ship the older 2016/03. **We already ship 2025/03** - verified by reading the
   edition line out of `backend/templates/ACORD_125.pdf` (5 pages, footer reads
   `ACORD 125 (2025/03) Page 1 of 5`). No action needed; tell the client.

---

## TO-DO - PRIORITY SNAPSHOT

### V1 - CRITICAL
| # | Item | Status | Notes |
|---|------|--------|-------|
| C1 | Data Consistency, Canonical Facts & Normalization | **In progress - 6 clauses complete, 2 partial, all remaining gaps are Brent's** | **Updated 2026-08-24 (C1-Q FIX 10).** 1.3 / 1.6 / 1.7 / 1.8 complete - 1.3's "No subcontracting" now reaches `explicit_no` via a schema-derived, self-verifying mechanism (FIX 10), not a third hand-typed case; "No Property coverage" stays `not_applicable`, a genuine box-choice question for Brent, not an engineering gap. **1.1 / 1.2 complete on everything engineering can decide** (C1b closed D-1); account/entity scope axis deliberately not built - zero reported defect, owner-confirmed unnecessary. **1.5 blocked only on Brent** (Suggested-vs-Verified scoring). 1.4 correct but unconsumed by scoring - same Brent item. Open for Brent: Q3a/Q3b, Q8, Q9 (Q10 CLOSED) - **all four are carried by the Loss History chat's list in `20Aug_questions_brent.md`** (consolidated 2026-08-24: every Data Consistency question turned out to be the same decision the Loss History list already asks - the DBA/FEIN tiers ARE Loss History scoring, prior carrier feeds its -10, and the AI weights are SQS. Section 1 has NO question of its own left). BI=Building wrong test DELETED 2026-08-24 (C1-R). Q5 closed 2026-08-24, was stale. **Independent audit 2026-08-24 (C1-R) executed every clause: 1.1 / 1.2 / 1.3 / 1.6 / 1.7 / 1.8 COMPLETE, 1.4 / 1.5 complete on facts, blocked on Q9 for scoring** |
| C2 | Loss History - Scoring, Evidence & Questionnaire Logic | **CLOSED 2026-08-25 (C2-A..C2-M). All 11 clauses + all 7 Brent rulings, live-verified over six runs. Nothing open.** | One state owner (`services/loss_history_state.py`); client tables 2.1-2.11 implemented verbatim (freq/ratio advisory-only, new-venture N/A + generic pillar rescaling via `_weighted_pillar_sum`, Path A/B/C revised numbers, strong pin terminal at 60, prior_carrier/num_claims out of Structural, 2.6 Data Consistency routing, state-gated questionnaire). Identity matcher was already DONE under C1/F4. **Brent ruled on all seven open questions 2026-08-24 (C2-E): DBA+EIN = verified match, EIN+unknown-name = probable match, prior-carrier-from-dec DECLINED, AI weights confirmed, and TWO corrections to what C2-A shipped - the years-in-business ladder ("we can't treat N/A as 0") and previously-uninsured vs missing prior carrier.** Read C2-A then C2-E at the end of this file BEFORE touching any loss-history code |
| C3 | SQS Scoring Integrity & Critical-Field Weighting | **SHIPPED 2026-08-26 (C3-A..C3-J). All 14 clauses + the traceability Desired Outcome, live-verified over five runs across 8 scenarios. Two product questions open (Q14, Q15).** | Structural blend 40/35/25 (SUBMISSION ONLY - spec sections 3.1 and 10 give forms their own checklist); no-form rescale 53.3/46.7; Tier 2 cut to the client's six; Not Applicable leaves the DENOMINATOR; all four fill-rate rules; dec-page Tier 1 exemption narrowed to producer name on an ONLY-dec-page package; credits de-duplicated per fact and re-applied on EVERY rebuild path. `sqs_service.build_score_trace` emits the ledger on the package and every form. **`ENABLE_CLASSIFICATION_SUGGESTIONS` is OFF** (3.13). **Nine bugs found on the way, three of them pre-existing and invisible until this work made them reachable** - see C3-G / C3-I / C3-J. **NOT addressed here: F-1** (invented GL class codes) is a form-fill grounding defect, not a scoring one, and stays open under H6. Q9's `CONFIDENCE_SCORE`-vs-`evidence_state` switch is CLOSED for V1: Brent confirmed the weights as-is and 3.8 forbids the redesign this pass |
| C4 | Contextual Questionnaire Logic | Not started | |
| C1c | **Route `submission_integrity.py` through the one door** | **Done** | LIVE RUN 2026-08-21: it still reports "Multiple distinct policy numbers found", "Location address differs", "Operations descriptions differ" on a clean multi-policy package. It is the SIXTH comparison site and does not use `fact_comparison` |
| C1b | **Scoped fact store (D19)** - carry scope ON the fact, additively | **Done 2026-08-23 (C1-Q FIX 7)** | `facts["_scoped"][key]` written once at the end of `merge_facts` from the settled `coverage_lines`; read by `_scope_from_store` BEFORE the character-keyed path. Additive - `mf[key]` untouched, private key skipped by every fact loop. Closed D-1 Layer 1: Run A scopes two carriers on different lines, Run B conflicts two on the same line |
| C5 | Source Lineage & E&O Audit Record | Partly started | C1 added `value_state`/`evidence_state`/`evidence_actor` to every envelope and the export, `candidates`+`reason` to the confirmation audit, and (C1-D) human-provenance survival across re-runs. Remaining: full lineage chain (Principle 6) |

### V1 - HIGH
| # | Item | Status | Notes |
|---|------|--------|-------|
| H1 | Coverage-Specific SQS Gap Closure | Not started | |
| H2 | Early Score / Readiness Presentation | Not started | |
| H3 | Workers Compensation Data Capture | Not started | |
| H4 | Core Submission Information Coverage | Not started | |
| H5 | ACORD 25 Multi-Carrier Mapping | Not started | |
| H6 | ACORD 125 Form-Generation Foundation | Not started | Answer key is the 125_reference/ folder. Form edition already correct (2025/03) - see D5 |
| H7 | Audit / Edit History Completion | Not started | |

**Status vocabulary:** `Not started` | `In progress` | `Blocked` | `Done` | `Deferred`

---

## LIVE TEST RESULTS - C1 (last updated 2026-08-24, C1-R)

> **C2's verdict** is in the C2 session block (all 11 clauses closed 2026-08-25).
> **C3's verdict** is in `LIVE TEST RESULTS - C3` immediately after the
> Decision Register - eight scenarios, five runs, every clause verified.

**Read this first.** Everything below was observed on the real application with real
uploads, not in a unit test. Full reasoning for each item is in the change log.

### The fixture

```
py backend/scripts/make_v1_c1_test_pdfs.py     ->  test_data_v1_c1/
```

Four text-extractable PDFs + `README-HOW-TO-TEST.md` (10 numbered checks). **Regenerate
before every run** - the generator has been corrected twice. Deliberately **FOUR** policies,
not the client's three, so the scope logic cannot be tuned to the reported case.

| File | What it carries |
|---|---|
| `1_dec_page.pdf` | 4 policies, 2 carrier entities, ZIP+4 address, umbrella **$3,000,000**, 2 lines marked NO COVERAGE, `Date Business Started 06/15/2014`, `Comprehensive / Collision Symbol 07` |
| `2_certificate.pdf` | same address spelled out, comma'd name, FEWER lines, different terminology, umbrella **$1,000,000** |
| `3_application.pdf` | `Denver, Colorado` only, TRUNCATED insured name, a Professional Liability policy with a different carrier |
| `4_loss_run.pdf` | FEIN with no dashes, policy number spaced, carrier under a group alias |

### The 10 checks - FINAL

| # | Check | Result | Live evidence |
|---|---|---|---|
| 1 | Address trio raises no issue / warning / cap | **PASS** | all three under "Resolved formatting difference - treated as equivalent" |
| 2 | N policies are scoped, not a conflict | **PASS** | 4 policies + 4 policy numbers raise nothing |
| 3 | Two carriers each kept under their own line | **PASS** | no carrier row; ACORD 131 pairs Auto->Employers Mutual, GL->EMC P&C |
| 4 | Truncated name does not cap at 60 | **PASS** | `Orbin Contract` listed as equivalent; no hard stop |
| 5 | **GATE - the $3M vs $1M umbrella conflict SURVIVES** | **PASS** | "Values differ - confirm / the documents state different amounts", both sources named |
| 6 | Umbrella box filled, not blank (Brent Q4) | **PASS** | ACORD 131: `$3,000,000` EA OCC + AGG while the conflict is open |
| 7 | **Loss run matches the insured** | **PASS** | "Loss data reconciled / **Matched on: name, fein, policy number**" - `strong` |
| 8 | ONE premises row with city + state | **PASS** | ACORD 125 LOC 1: `4800 Dahlia St D13` / Denver / CO / 80216 |
| 9 | Professional Liability not treated as GL | **PASS** | no GL/PL carrier conflict; PL is its own family |
| 10 | NO COVERAGE lines stay unticked | **NOT CONFIRMED** | the LOB checkbox area was not captured in the screenshots |
| 11 | Client-answer conflict panel (optional) | **NOT RUN** | needs a questionnaire round trip |

### Client section 1, clause by clause - FINAL

**Re-graded 2026-08-24 (C1-R) by an independent audit that EXECUTED the client's
literal examples through the live code** - the address trio, all 13 LOB phrases, all
8 loss-run normalizations, 15 value-state cases, and `calculate_p4_loss_history` per
tier - after FIX 7 (scoped store), FIX 9 (D-2 / D-3) and FIX 10. The 2026-08-23
version of this table pre-dated those fixes and still read "partial" on 1.1 / 1.2 /
1.5 with "`grep _scoped` is empty"; that was true on the 23rd and false by the 24th.

| Clause | Verdict | Live proof / what is missing |
|---|---|---|
| 1.1 Canonical fact flow | **COMPLETE** (engineering side) | One door (`fact_comparison`), SIX sites through it, AST guard. Scope is STORED at merge (`_build_scoped_fact_store`, C1b / FIX 7) and read BEFORE the comparator (`_scope_from_store`) - the client's order, D8 honoured. D-3 (prose typed as a conflict) closed by FIX 9 |
| 1.2 Fact scope | **COMPLETE on every axis with a reported defect** | Line/coverage (stored, FIX 7), item (location/vehicle, C1-P), policy period (multi-contract downgrade + renewal routing to `prior_*`), document role (`document_witnesses`). D-2 (class-code payroll bases as rivals) closed by FIX 9. Account/entity axis NOT built - owner ruled unnecessary, zero defects in 9 live runs |
| 1.3 Value states | **COMPLETE** | All six written, all six have writers. Executed 2026-08-24: "No prior losses" -> `explicit_no`, "No subcontracting" -> `explicit_no`, "No Property coverage" -> `not_applicable` on all 26 property-line facts, bare `False` -> `not_stated` (B8), tri-state `false` -> `explicit_no`, `_uw_conflicted_keys` -> `conflicting`, rejected -> `unable_to_determine` |
| 1.4 Evidence states | **COMPLETE on facts + audit; NOT consumed by scoring** | `ai_high`/`ai_low` -> `suggested` -> displays UNRESOLVED; `dec_entry`/`deterministic`/`verified_in_text` -> `source_verified`; humans -> `user_confirmed` with actor. `CONFIDENCE_SCORE` still reads the old tag (0.85). **Q9 - Brent** |
| 1.5 Selection rules | **COMPLETE except Q9** | Conflict retains values + sources + scope + reason (survived Run A; Run B rival GL carrier now CONFLICTS, FIX 7). Confirm appends an immutable audit row (id, user, timestamp, candidates, reason, previous). Client answer contradicting source is HELD (D12/D17), resolved on the forms screen, audited. Suggested displays UNRESOLVED but scores 0.85 - same Brent item |
| 1.6 Address | **COMPLETE - all 4 acceptance criteria, BOTH directions** | Trio -> `equivalent`; 10 formatting variants -> `same`; Denver vs Lakewood, N vs S Main, ZIP 80216 vs 80217 -> `different`. Run A: no issue / warning / deduction / ceiling. Run B fired |
| 1.7 Lines of business | **COMPLETE - all 3 acceptance criteria, BOTH directions** | All 13 client phrases map; `Widget Liability` / `Kidnap and Ransom` -> None and route to the producer (FIX 2). Denial withdrawn when another doc grants -> conflict, not silence. Run A info / Run B warning |
| 1.8 Loss-run identity | **COMPLETE on normalization; two TIERS unruled** | All 8 normalizations executed and pass; `calculate_p4_loss_history` on 5 clean years = **100 / 92 / 85 / 25** by tier. **Q3a / Q3b open** - and the code CANNOT distinguish "a DBA we've never seen" from "a different company", so the client-facing ask was collapsed to one rule + one question (C1-R) |

**Check 3 is now graded on the badge, not on absence.** FIX 8's live confirmation
shows the scoped `Carrier` row rendering with `3 policies, 3 values - not a
conflict` on Run A. The earlier "no carrier row" proof is retired.

### The seven live runs, and what each one caught

**Every one of these was found by running the real package. None by the 3,600-test suite.**

| Run | What it exposed | Entry |
|---|---|---|
| 1 | **GATE FAILED** - umbrella conflict scoped into silence (`$1,000,000` inherited the GL policy's ownership because owners key on the amount) | C1-H |
| 2 | Loss run testifying about policy identity; an extra Professional Liability line called the package inconsistent | C1-I |
| 3 | LOB denial rule matched a document AGAINST ITSELF; submission integrity was the SIXTH comparison site | C1-J |
| 4 | A CERTIFICATE row read as a DENIAL - absence of evidence treated as evidence | C1-K |
| 5 | Combined `Comprehensive and Collision` label dropped the collision symbol; "years in business" asked while the dec page states the start date | C1-L |
| 6 | Pre-form screen signed off; Readiness 67% -> **78%** | C1-M |
| 7 | Forms generated: 1.8 confirmed; eight form-fill defects catalogued (F-1..F-8) | C1-N |

**Six of the bugs fixed in this arc were introduced BY a C1 fix.** All shared one signature:
*the fixture was easier than the live document.* That is why the fixture now lives in the
repo, why D22 exists, and why the CHANGE QUALITY BAR is a standing gate.

### Suite history

| After | Result |
|---|---|
| C1-C (implementation) | 3515 passed / 2 failed |
| C1-D (client-answer routing) | 3539 passed / 2 failed |
| C1-E (carrier family + address ordering) | 3562 passed / 2 failed |
| C1-F (Brent Q2/Q4 + B13) | 3569 passed / 2 failed |
| C1-I (document role + LOB denial) | 3593 passed / 2 failed |
| C1-J (submission integrity) | 3602 passed / 2 failed |
| C1-K (explicit denial) | 3604 passed / 2 failed |
| C1-L (symbols + derived years) | 3625 passed / 2 failed / 2 skipped |
| C1-P (item scope + two dead states) | 3664 passed / 2 failed / 2 skipped |
| C1-Q (Run A/B + Tier A fixes) | 3738 passed / 2 failed / 2 skipped |
| C1-Q FIX 4 (merge list union) | 3764 passed / 2 failed / 2 skipped |
| C1-Q FIX 5 (component-rule gate) | 3782 passed / 2 failed / 2 skipped |
| C1-Q FIX 6 (explicit_no + abbreviations) | 3812 passed / 2 failed / 2 skipped |
| C1-Q FIX 7 (C1b scoped fact store) | 3830 passed / 2 failed / 2 skipped |
| C1-Q FIX 8 (picker entity grouping) | 3834 passed / 2 failed / 2 skipped |
| C1-Q FIX 9 (gl_limits / class exposure / contractor_type) | 3866 passed / 2 failed / 2 skipped |
| C1-Q FIX 10 (generic Explicit No + class-exposure derivation) | 3880 passed / 2 failed / 2 skipped |
| C1-R (independent audit + cleanup: wrong test deleted, dead `"none"` entry removed) | 3923 passed / 1 failed / 2 skipped - the BI/Building failure is gone; only `test_arq_acord125_missing_only` (httpx/openai) remains |
| **C1-S (`ai_verified` scored zero - fixed at 0.85 + label-coverage anti-rot test)** | **3931 passed / 1 failed / 2 skipped** - same single pre-existing failure, +8 tests, zero regressions |

The 2 failures are the SAME pre-existing pair throughout
(`test_arq_acord125_missing_only` - the known httpx/openai conflict;
`test_normalization::test_insurance_terms_equivalent` - the `BI`/`Building` synonym).

**Correction 2026-08-23: the second one is not "unrelated", it is a WRONG TEST.**
It asserts `normalize_general("BI") == normalize_general("Building")`. In
commercial lines `BI` is Bodily Injury or Business Interruption; mapping it to
Building is precisely the over-mapping client 1.7 forbids and D9 requires product
approval for. **The code is right and the assertion is wrong** - it has been
carried as a known failure for the whole arc. Delete the pair or correct it; do
not "fix" `normalize_general` to satisfy it.
**DONE 2026-08-24 (C1-R): the `("BI", "Building")` pair is deleted from
`test_normalization.py` with a comment saying why; the other nine pairs stand.**
The only remaining pre-existing failure is `test_arq_acord125_missing_only`.
**Zero regressions across the entire arc.** New C1 tests: 181 in
`test_v1_c1_canonical_facts.py`, 31 in `test_v1_c1d_client_answer_review.py`, 4 in
`test_comparison_has_one_owner.py`.

### Known FIXTURE defects (corrected - do not chase as product bugs)

| Symptom | Cause |
|---|---|
| GL policy extracted as `7263-26` instead of `BBC7263-26` | reportlab placed the CARRIER and POLICY NUMBER columns close enough that pdfplumber interleaved them: `...Casualty ComBpBaCny7263-26`. Generator now uses wider columns AND repeats each line's carrier/policy as plain `label: value` pairs |
| "no covered-auto symbol found for collision" | **NOT a fixture defect - a real bug.** See L6 / C1-L |

### FORM-SIDE defects still open (C3 / H6, not C1)

`F-1` invented GL class codes (**CRITICAL** - `8810` / `5645` appear in NO uploaded
document), `F-2` ACORD 126 header carrying the Auto policy number (**re-check on a clean
fixture first**), `F-3` dates in a count box, `F-4` `C` in a Y/N box, `F-5` a water-damage GL
claim answering "product liability loss?", `F-6` the Auto deductible on the GL form,
`F-7`/`F-8` cosmetic. Full table with evidence in **C1-N**.

**F-1 is the one that matters** - the fill layer inventing a rating classification on a
document an underwriter prices from, against the client's explicit *"a box existing is not
permission to fill it"*.

---

## HOW TO USE THIS FILE

Every work session on a V1 item ends with an entry in the Change Log below. No exceptions -
this file is the only thing that survives between chats.

Each entry answers four questions:
1. **Problem** - what was actually wrong, in plain terms, with the evidence that proved it.
2. **Root cause** - the mechanism, not the symptom.
3. **Fix** - what changed, which files, which tests.
4. **Why this and not the alternative** - the options rejected and the reason. This is the
   part that stops a future chat from undoing the decision.

Also update the status cell in the to-do table above in the same edit.

---

## CHANGE LOG

_Newest entries at the top._

### C1 AT A GLANCE - issues found and what we decided

Short index for a future chat. Full reasoning is in the entries below.

| # | Issue found | Decision / solution |
|---|---|---|
| B1 | 3+ printings of one value became a conflict (client's address trio; Orbin's 3 policies) | Clique merge in `equivalent_index`; the ambiguity guard is kept, not deleted (D4, D7) |
| B2 | Loss-run FEIN and policy number compared as RAW strings; policy taken from "the first document" | Rebuilt as `loss_run_identity.py`; everything through the one door; policy matched per line (F4) |
| B3 | `applicant_name` hard-stopped (cap 60) on a truncation or a DBA suffix | `check_doc_consistency` routes ALL 8 fields through the door (F3) |
| B4 | A client questionnaire answer silently overwrote the documents | Held for the producer, never applied (D12); resolved on the generated-forms screen (D13) |
| B5 | `detect_source_conflicts` had no equivalence filter | Skipped for scalars in production; booleans now excluded via `not_stated` |
| B6 | `_canon_line` hidden in a 7k-line module behind `lambda: None` fallbacks | Leaf module `lob_canon.py`; fallbacks deleted (D9) |
| B7 | Location consolidation used its OWN address regex - client's trio made 2 premises rows on ACORD 125 | Fragment fold calls `normalize_address` (F9) |
| B8 | A boolean `False` meaning "this COI never mentioned it" manufactured a conflict + 85 cap | No evidence = `not_stated`; only `present`/`explicit_no` are ever compared (F5) |
| B9 | **Routing error in C1-C:** held client answers sent to the Data Consistency picker, which WIPES generated forms | New "Needs your decision" section on the SQS panel; `apply_producer_answer_to_session` patches forms in place (D13, D14) |
| B10 | Q7 - human answers destroyed by every pipeline re-run | `prior_facts` + `human_provenance_facts`; restore or hold, no product ruling needed (D15) |
| B11 | **Mine (C1-C):** a carrier ALIAS raised a false "does not match" note on the loss run | `carriers_same_family()` - corroboration uses the alias map, conflict keeps the strict key |
| B12 | **Mine (C1-C):** `E 9 Mile Rd` != `East 9 Mile Rd` - the unit-join ran before the directional mapping | Directionals collapse first, glued unit markers split, join excludes directional letters |
| L6 | **LIVE RUN, dismissed by me TWICE as a fixture artefact:** `Comprehensive and Collision  Symbol 07` parsed as comprehensive only - collision's symbol was dropped | `normalize_coverages()` returns EVERY coverage a combined label names (C1-L) |
| L7 | **LIVE RUN:** the questionnaire asked "years in business" while the dec page printed "Date Business Started: 06/15/2014" | `_derive_years_in_business` - client 1.4 Derived, positive evidence only, labelled `derived` (C1-L) |
| B16 | **Mine (C1-I/J), third attempt at one warning:** a CERTIFICATE row (policy number, no premium) was read as a DENIAL of that line | `grants` / `denies` / `silent` are THREE states. New `_line_entry_denies_coverage` requires an EXPLICIT denial (C1-K) |
| L5 | **LIVE RUN:** submission integrity called a clean package "Warning" over a component address, a multi-policy package's policy numbers, and two prose operations descriptions | It was the SIXTH comparison site - counted distinct strings. Routed through the door; carrier uses the FAMILY comparator (C1-J) |
| B15 | **Mine (C1-I):** the LOB denial rule matched a document AGAINST ITSELF - a dec page both denies Property and lists it | Denial and active listing must come from DIFFERENT documents (C1-J) |
| L1/L3 | **LIVE RUN:** the loss run's policy number and carrier were compared as rival statements about the policy | A document's ROLE decides which facts it witnesses - `document_witnesses()`, fail-open (C1-I) |
| L2 | **LIVE RUN:** an application naming Professional Liability made the whole package "inconsistent" and capped SQS at 85 | A LOB conflict needs a DENIAL, not a different list. Silence is not denial (C1-I) |
| B14 | **Mine (C1-C), caught on the FIRST LIVE RUN:** the umbrella $3M-vs-$1M conflict was scoped into silence - `$1,000,000` inherited the GL policy's ownership because owners are keyed by the amount | A fact pinned to one line never scopes; money never scopes and never owner-splits (C1-H) |
| B13 | **Mine (C1-D):** releasing a held client answer cleared nothing - the facts merge is ADDITIVE, so a bare `pop` is a no-op | Retract with `delete_facts`, the codebase's own escape hatch |
| F-1 | **LIVE RUN 2026-08-22:** ACORD 126 filled GL class codes `8810` / `5645` that appear in NO uploaded document, with wrong descriptions (`8810` is Clerical Office, labelled "Roofing Contractor") | **OPEN - root cause found, fix already written and switched off. See C1-O.** THREE layers failed: the box is asked by design (Principle 3), typed boxes carry no grounding contract (the evidence gate is Y/N-only), and the named guard is blind - 36 covered vs **38 blind** classification-code fields across the 17 schemas. `_report_ungrounded_ai_values` already catches it generically (4/4 on the live values) but is report-only. Routed to C3 |
| D-1 | **RUN B 2026-08-23:** a genuine SECOND General Liability carrier (Travelers vs EMC, same line, same period) produced NO conflict row and NO scoped row | **FIXED, both layers.** TWO losses upstream of the comparator: no dec page produces a scalar `carrier_name`, AND `merge_facts` overwrote every LIST field with the primary doc. **Layer 2 FIXED (FIX 4, union not replace); Layer 1 FIXED (FIX 7 / C1b - per-line values are candidates WITH stored scope).** Run B now conflicts; Run A scopes (FIX 8) |
| D-2 | **RUN A 2026-08-23:** the picker asked the producer to choose between `$1,880,000` total payroll and three GL class-code payroll BASES from the same package | **FIXED (FIX 9 / FIX 10).** `_drop_class_exposure_candidates` removes a text-scan-only candidate that is literally a class-schedule exposure column; columns DERIVED from the schema, not hand-typed (FIX 10) |
| D-3 | **RUN A 2026-08-23:** two descriptions of one business ("Licensed electrical and roofing contractor" / "Commercial General Contractor - Roofing and Electrical") opened a conflict | **FIXED (FIX 9).** `contractor_type` stays `KIND_TEXT` (so truncation/containment still run) and `_SOFT_TEXT_FACT_KEYS` returns INCOMPARABLE instead of DIFFERENT as the final fallback. Explicit list, never a shape heuristic |
| D-4 | **RUN B 2026-08-23:** every identity conflict rendered TWICE, and the legacy copy reprinted the address spellings the picker had folded | **FIXED (C1-Q).** Pair by FACT, not phrase; reuse the existing display-only supersession; never hide a hard stop behind a warning |
| G1 | **The one-door guard was blind.** Its regex could not see an indented import, and `underwriting_consistency` had been importing `entity_identity_conflict` - on the guard's own forbidden list - for weeks | **FIXED (C1-Q).** Guard parses the module (AST); the breach routed through `fact_comparison.entities_materially_differ`; the private `_fe` back channel now has a pinned user set |
| G2 | **Client 1.7's second half was never built** - an unrecognised coverage part was left unmapped and routed nowhere | **FIXED (C1-Q).** `unmapped_material_lines` + an ADVISORY issue: visible, scores nothing until Brent rules (Principle 7) |
| G3 | **A context rule keyed on a value's CHARACTERS silenced a real conflict - for the SECOND time.** `is_component_of` (a money rule) folded Denver into Lakewood | **FIXED (C1-Q FIX 5).** `_component_split_allowed` gates it to money/count/percent, mirroring `_owner_split_allowed`. Also fixed `"policy"` outranking money in `value_kind`: 7 amount keys corrected, 0 identifiers broken |
| - | Bug CLASS: **a fixture that can only pass.** Nine of the ten checks were "must NOT fire", so a dead check and a working fix looked identical. Check 3 has been graded PASS on "no carrier row" since C1-N - which is equally consistent with never comparing | Build a NEGATIVE control (`6_conflicting_dec.pdf`, C1-Q) and require the scoped-row badge, not its absence |
| - | Bug CLASS: **a fixture simpler than the live document.** SIX bugs in this arc were introduced BY a C1 fix, and every one was caught by a real upload, not by 3,600 tests | Build gate fixtures from the LIVE data shape (D22); the fixture now lives in the repo |
| - | Bug CLASS: every "exactly ONE candidate" guard is blind to 3+ equivalents | Count equivalence CLASSES, never raw candidates (D7) |


### C1-S A DOCUMENT-VERIFIED AI FIELD SCORED ZERO - FIXED (2026-08-24)

**Found by answering the owner's question "did Brent tell us to set AI weights?"**
Chasing which labels the form-fill path actually emits showed that the 0.85 the Q9
draft was asking Brent to re-tune applied to NOTHING - and that the label that
does get emitted was scoring zero.

**Problem.** `sqs_service.confidence_fill_rate` reads
`CONFIDENCE_SCORE.get(label, 0.0)`. `pdf_service` emits exactly five per-field
labels: `filled`, `ai_verified`, `low_confidence`, `missing_required`,
`missing_required_gate` (`form_routes` adds `client_arq`). Two of those were
not in the table. `missing_required_gate` -> 0.00 by accident is the right
number. **`ai_verified` -> 0.00 is the defect**: it is the label for an AI value
CONFIRMED present word-for-word in the uploaded document (pdf_service's own
raw-text verification, painted pink "AI-OK"), and it scored LESS than
`low_confidence` (0.50), the label for a guess the check could NOT find.
Verification made the score worse.

**Measured before the fix:** ten document-verified AI fields -> **0%** fill
rate; ten unverified guesses -> 50%; a realistic mix (4 deterministic, 4
verified, 2 guesses) -> 50% where 84% is right. Fill rate is 35% of Structural
Completeness (25% of the package), so every submission with AI-filled fields
has under-scored since the label shipped. `git log -S` confirms `ai_verified`
has NEVER been in the table - it was added to `pdf_service` (commit `77b19da`
era) without touching the scorer, and nothing checked.

**Root cause (the class, not the case):** a per-field label can be introduced
in the fill layer with no obligation to give it a weight, and `.get(..., 0.0)`
hides the omission. The `ai_high` / `ai_low` entries that WERE in the table are
FACT-level labels from extraction and are never assigned to a form field - so
the table looked complete while covering the wrong vocabulary.

**Fix.**
- `CONFIDENCE_SCORE["ai_verified"] = 0.85` - the AI-high slot the ladder already
  had. It is the highest confidence the AI path can reach (the value is on the
  page) but it was placed by the model, not read deterministically, so not 1.00.
  Brent may re-tune the NUMBER (Q9); its slot in the ladder is not in question.
- `CONFIDENCE_SCORE["missing_required_gate"] = 0.00` - explicit, so zero is a
  decision rather than a default.
- `ai_high` / `ai_low` / `deterministic` kept, labelled as fact-level, so a
  fact-level caller keeps working.
- **Anti-rot:** `tests/test_confidence_score_covers_every_label.py` harvests every
  `confidence[...] = "<label>"` assignment (incl. the ternary form) from
  `pdf_service.py` and `form_routes.py` and fails the build if any label is not
  a key in the table. Harvester self-check included (C25) so an empty harvest
  cannot pass vacuously. Plus the ladder invariant (`filled >= ai_verified >
  low_confidence > missing`) and the measured defect shape (ten verified fields
  must not read as an empty form).

**Blast radius, simulated forward.** Only `confidence_fill_rate` reads the
table. It feeds the per-form `sqs.confidence_fill_rate` and the package P1
average. Scores RISE on every session with AI-verified fields, next recompute.
**D6 applies - Brent is told in `20Aug_questions_brent.md` Q4 before he sees
it.** No test pinned the broken number (`test_sqs_scoring` computes the parity
blend from the live value). The UI "form completion / quality fill rate"
section is currently hidden (commit `480fdb4`), so the visible movement is the
Structural pillar and the headline score.

**Q9 is REFRAMED, not answered.** The draft asked Brent to re-tune a 0.85 that
scored nothing. The real question is what a Suggested value that IS on the page
should weigh versus one that is NOT. The doc now shows him the four buckets,
tells him the second one was broken and is fixed at 0.85, and proposes keeping
0.85 / 0.50 so the fix is the only score movement.

**Files:** `services/sqs_service.py` (table + `confidence_fill_rate` docstring),
`tests/test_confidence_score_covers_every_label.py` (new, 8),
`20Aug_questions_brent.md` (Q4 rewritten), this file.

---

### C1-R INDEPENDENT AUDIT OF SECTION 1 + CLEANUP - DONE (2026-08-24)

**Problem.** The owner asked a separate chat to verify, deep in the code, that every
clause of the client's Section 1 was actually done - and to vet the four questions
drafted for Brent. Nothing was taken from this file's own grades; every clause was
EXECUTED against the live code.

**What was executed (all pass):** the client's literal address trio + 10 formatting
variants + 4 must-differ pairs through `fact_comparison.verdict`; all 13 LOB phrases
+ 2 unknowns through `lob_canon.canon_line`; all 8 loss-run normalizations through the
door (`feins_match`, `identifiers_match`, `carriers_same_family`, `values_agree`);
15 value-state cases through `derive_value_state` incl. all three client Explicit No
examples; 11 evidence-state cases; `calculate_p4_loss_history` on 5 clean years per
tier = 100 / 92 / 85 / 25; 637 C1 tests (636 pass, the 1 failure being the wrong
`BI`/`Building` assertion). Confirm-endpoint -> `log_underwriting_confirmation`
traced: append-only row with id, user, timestamp, `candidates`, `reason`,
`previous_value`; `client_answer_review.resolve_client_answer` audits the same way.

**Verdict:** 1.1 / 1.2 / 1.3 / 1.6 / 1.7 / 1.8 COMPLETE; 1.4 / 1.5 complete on the
fact layer and blocked on Q9 for scoring. The clause table above is re-graded to
match. The "C1 AT A GLANCE" rows for D-1 / D-2 / D-3 read "half fixed / OPEN / OPEN"
while FIX 7 and FIX 9 had closed them - corrected; a future chat reading the old rows
would have redone the work.

**Three factual problems found in the first Brent draft, all corrected in
`20Aug_questions_brent.md`:**
1. **Q3a split a case the code cannot see.** "Trading name only on the loss run" is
   indistinguishable from "a different company" - `loss_run_identity` only knows the
   DBAs the package DECLARES. Collapsed to one recommended rule (declared-DBA match =
   name match) + one question (Q3b).
2. **Q8's rule was circular.** "Ends when the new term starts" - the new term start on a
   renewal is DERIVED from the expiring expiration. Re-stated as the rule the code
   already applies to dates ("term has already ended") and made PER LINE, because no
   scalar `carrier_name` exists on a multi-policy package (D-1 Layer 1) and ACORD 125's
   prior-carrier section is per line anyway.
3. **Q9 asked for one Suggested weight.** `ai_high` and `ai_low` BOTH map to
   `suggested`; one number collapses 0.85 / 0.50 into one tier. Now asks for two
   (recommends 0.70 / 0.40), proposes Derived = 1.00, and says plainly it is not a
   one-line switch (form-field tag vs fact label).
Q10 was a coin flip; it now recommends line = `explicit_no`, fields = `not_applicable`.

**Owner review of the question doc, 2026-08-24 - three challenges, all correct:**
1. **"Is the DBA rule hardcoded to the client's names?"** No - PROVEN, not asserted.
   `grep -rniE "orbin|dahlia|roofing"` over `services/` `routes/` `utils/` `config/`
   returns zero production hits (only comments recording where a bug was found). Three
   unrelated fictional businesses (a bakery, a law firm, a trucking company) were run
   through `match_loss_run_identity` live: all three DBA cases returned
   `matched_on=['dba_name','fein']` + `NOTE_DBA`; the FEIN-only cases returned
   `matched_on=['fein']` + `NOTE_FEIN_NAME_DIFFERS`; the control (different name, different
   FEIN) returned `matched_on=[]` and no note. **The MECHANISM is generic and shipped; only
   the SCORE is unruled.** The doc was still at fault for illustrating it with the client's
   real name, which made a generic rule read as a special case - rewritten with a neutral
   illustration.
2. **"Are the 0.85 / 0.50 weights Brent's?"** No - see the Q9 row. The code said "per
   spec" and the spec does not contain them.
3. **"Do we even need to ask about No Property coverage?"** No - Q10 CLOSED, see its row.
   He answered it in his own spec; Q6 sets the precedent for closing rather than asking.

**Cleanup shipped:**
- `test_normalization::test_insurance_terms_equivalent` - the `("BI", "Building")`
  pair DELETED with a comment. This file had called it a wrong test three times and
  nobody had removed it.
- `fact_state._NEGATION_STRINGS` - `"none"` removed. It was also in `_EMPTY_STRINGS`
  (tested first), so it was unreachable dead weight; a bare "None" stays `not_stated`,
  which is the correct reading (the extractor emits "None" for null). Zero behaviour
  change, comment explains why.
- `QUESTIONS_FOR_BRENT.md` was referenced in three places and **did not exist in the
  tree**. Replaced by `20Aug_questions_brent.md`; every reference updated.
- `sqs_service.CONFIDENCE_SCORE` + `confidence_fill_rate` - the false *"per spec"*
  attribution on the 0.85 / 0.50 weights corrected in both places, with the evidence in
  the comment so nobody defends those numbers as a client decision again. **Comment only;
  the weights are untouched and no score moves.**

**Not done, stated:** live checks 10 (NO COVERAGE boxes stay unticked) and 11
(client-answer round trip) remain unrun - they need the app, not a unit test. The
`"n/a"` string sits in both `_NOT_APPLICABLE_STRINGS` and `_EMPTY_STRINGS`; left alone
because `_is_blank` relies on it and the not-applicable check runs first, so it is
reachable, unlike `"none"`. `bop_property_limit` resolves to line `cyber` (registry
`forms={ACORD_160}`) - odd, not C1, not touched.

**Files:** `backend/tests/test_normalization.py`, `backend/services/fact_state.py`,
`20Aug_questions_brent.md` (new), this file.

---

### C1-Q RUN A / RUN B + TIER A FIXES - SHIPPED (2026-08-23)
**A negative-control fixture was built, both runs were executed live, and three
of the four defects they exposed are fixed. Suite 3738 passed / 2 failed** - the
same two pre-existing unrelated failures, zero regressions, +38 tests
(`test_doc_conflict_supersession.py` 18, `test_unmapped_coverage_line.py` 18,
`test_comparison_has_one_owner.py` +2).

#### The fixture was one-sided, and that is why it could not fail

Nine of the ten checks in `README-HOW-TO-TEST.md` are *"this must NOT fire"*.
Only the umbrella gate tested the other direction. **A fixture shaped that way
cannot distinguish "the fix works" from "the check is dead"** - C25's trap, one
level up. `scripts/make_v1_c1_adversarial_pdf.py` now generates
`6_conflicting_dec.pdf`: a rival carrier's declarations page planting seven
disagreements that MUST fire, plus Auto and Umbrella repeated identically to
file 1 as an in-run control. `README-RUN-A-AND-B.md` is the scorecard.

**It immediately earned its place.** Run B fired 5 of 6 - and the one that did
not is the single most important check on the sheet.

#### Live results

| Run | Result |
|---|---|
| A (files 1-5) | Address trio, 4 policies, truncated name, LOB terminology, loss run - all silent. **The $3M/$1M umbrella gate survived.** Two real defects found |
| B (files 1-6) | Address / DBA / employees / GL limits / **Commercial Property granted vs NO COVERAGE** all fired. Auto, Umbrella and the loss run stayed silent. **B4 failed** |

**B6 is the strongest result in the arc:** `lines_of_business` rendered as
*info, "treated as equivalent"* in Run A and as a **warning** in Run B. Client
1.7's acceptance criterion, proven in BOTH directions for the first time.

#### The four defects, and what happened to each

**D-1 ROOT CAUSE FOUND 2026-08-23 (second Run B, session
`10e6a861-b538-4055-8b41-10e3a6089fa2`). It is not in the comparison layer at
all - it is TWO independent losses upstream of it.**

**Layer 1 - no declarations page produces a scalar `carrier_name` or
`policy_number`.** Per-document facts from the live session:

| Doc | `carrier_name` | `policy_number` |
|---|---|---|
| 1 dec_page | **None** | **None** |
| 2 certificate | EMC Property & Casualty Company | BBC7263-26 |
| 3 application | **None** | **None** |
| 4 loss_run | EMC Insurance Companies | 6E7 40 02 26 |
| 5 dec_page | EMC Property & Casualty Company | BBC7263-26 |
| 6 dec_page | **None** | **None** |

A multi-policy dec page prints one carrier PER COVERAGE PART, so extraction
declines to elect a package-level scalar - defensible on its own. But the
picker compares per-document SCALARS, so after role-blinding the loss run it
saw one value group and returned `consistent`. **Travelers was never a
candidate.** Nothing was silenced; nothing was ever offered.

**Layer 2, and the serious one - `merge_facts` DELETES every non-primary
document's coverage lines.** `extraction_service.merge_facts` merges the
non-primary docs' list fields, then applies the primary doc as a "legacy
fallback for unmapped fields":

```python
for k, v in primary.get("facts", {}).items():
    if not _is_empty(v):
        mf[k] = v          # <- overwrites LIST fields too
```

The override loop immediately BELOW it guards itself with
`if field in _LIST_FIELDS: continue`, so the need for list handling was known -
this loop simply has no such guard. Live result: merged `coverage_lines` is
`1_dec_page.pdf`'s four rows byte-for-byte. **Travelers' GL, Travelers'
Commercial Property and Hartford's Professional Liability are all gone from the
fact layer.** Reproduced offline and deterministically with a two-document
`merge_facts` call: 2 rows in, 2 rows out, Travelers absent.

**This is client 1.2 violated at the MERGE - before any comparison can happen.**
*"Different values with different valid scope: retain each under its correct
scope."* The scope machinery is fine; the second policy no longer exists by the
time it runs.

**It also means check 9 has been passing for the wrong reason.** *"Professional
Liability is not treated as General Liability"* was recorded PASS because no
PL/GL carrier conflict appeared - but `3_application.pdf`'s Hartford PL row is
DELETED by this same loop. The check cannot distinguish "correctly kept
separate" from "deleted". That is the same grading failure as check 3, in a
second place, found by the same run.

#### FIX 10 - EXPLICIT NO AND CLASS-EXPOSURE FILTERING MADE GENERIC, NOT HAND-TYPED (2026-08-24)

**Suite 3880 passed / 2 failed**, the same two pre-existing. +14 tests in
`tests/test_generic_absence_and_exposure_derivation.py`.

**The gap:** re-tested the client's own three named Explicit No examples
directly against the live code. Only "No prior losses" worked. **"No
subcontracting" had NO route to `explicit_no` at all** -
`percent_subcontracted` is a bare string fact with no tri-state contract and
no absence flag; `"0%"` read as `present`, `"None"` read as `not_stated`.
Owner's instruction: fix it, and make the MECHANISM generic rather than add a
third one-off case.

**What "generic" means here, and what it deliberately does not.** Two separate
mechanisms, both schema-derived, neither a blind auto-everything:

1. **`ASSERTION_FLAG_NAMES`** - every `asserts_no_*` flag is now DISCOVERED
   from the schema by naming convention, mirroring `TRISTATE_BOOLEAN_FACTS`'s
   own `boolean or null` discovery. WHICH fact(s) an assertion is about cannot
   be derived from string shape - "no known losses" is about `loss_history`
   by domain knowledge, not by spelling - so `ABSENCE_ASSERTION_FLAGS` stays an
   explicit table. What makes it generic rather than ad hoc: it is now ONE
   centralised table with TWO anti-rot tests -
   `test_every_assertion_flag_is_registered` fails the build the moment a new
   `asserts_no_*` flag is added to the schema with no table entry, and
   `test_every_registered_flag_still_exists_in_the_schema` catches the mirror
   case. A third example can never again silently fail to reach `explicit_no`.
2. **`_CLASS_EXPOSURE_COLUMNS`** (FIX 9's two-entry hardcoded tuple) is now
   DERIVED: a list field whose NAME contains "class" (both `gl_class_code_
   schedule` and `wc_class_codes` are named for exactly that), and whichever
   of ITS OWN columns are money-shaped, reusing `fact_equivalence._MONEY_
   TOKENS` rather than inventing a second classifier.

**The blind version was tried first, measured, and rejected - kept as the
documented reason for the narrower selector.** A naive "any list field with a
money-shaped column" scan against the real schema swept in `dec_page_entries.
value` (the PRIMARY EVIDENCE source every other backfill reads FROM -
excluding it from candidacy would have been actively destructive, the
opposite of the fix's intent), `coverage_lines.premium` (owned by
`is_component_of`'s own, already-correct line-vs-package logic),
`property_locations.building_value` / `inland_marine_items.value` (per-ITEM
values that belong to C1b's item-scope axis, a different mechanism entirely),
and even `loss_history` (via `open_code`, a STATUS code, not a rating class -
caught because "code" alone is too loose a signal). The field-NAME-contains-
"class" selector excludes every one of them while still finding the two real
schedules; `test_a_selector_scoped_to_class_schedules_not_any_money_column`
and `test_a_field_merely_containing_a_status_code_column_is_not_swept_in` pin
the exclusions, not just the inclusion.

**"No subcontracting" now works end to end**, via the SAME generic mechanism
as losses, not a bespoke path: a new schema flag `asserts_no_subcontractors`
(worded identically to `asserts_no_known_losses` - "true ONLY when the
document EXPLICITLY states...", judged by meaning not exact wording, FALSE on
mere discussion or a nonzero percentage), registered in
`ABSENCE_ASSERTION_FLAGS` against `percent_subcontracted`. Verified: asserted
-> `explicit_no`; a real percentage always wins over the assertion; the flag
being false or absent asserts nothing; the pre-existing losses wiring is
untouched by adding a second entry.

**"No Property coverage" (the client's third example) was deliberately left
alone**, unchanged from FIX 9's finding: it already resolves to
`not_applicable` via a declared-absent coverage line, and whether that is the
right box or whether it should move to `explicit_no` is a genuine product
question - the client's own vocabulary places the example under Explicit No,
but both readings are defensible engineering choices. Not decided here.

**Also deliberately NOT done:** the account/entity scope axis (1.2) and
extending C1b's stored-scope mechanism to every material fact rather than the
5 line-scoped identity keys. Both were explicitly ruled unnecessary by the
owner in the same conversation that ordered this fix - zero reported defects
from either gap, and building them now would be preparing for a problem that
has not occurred once across 9 live runs, not fixing one.

**Found and NOT fixed, out of scope, flagged for the record:** `sqs_service.py`
reads `flags.get("has_subcontractors")` in its scoring-deduction path
(`if flags.get("is_contractor") or flags.get("has_subcontractors")`) - a
PHANTOM flag matching the exact class of bug CLAUDE.md's Auto Symbol Warnings
entry already documents ("five phantom fact keys... nothing writes them").
Grepped: nothing in the schema or anywhere else ever writes `has_subcontractors`,
so the `or` clause is permanently dead and `is_contractor` alone drives that
deduction. Not a regression from today's work and not touched - it is SQS
scoring logic (C3 territory), out of bounds for a Data Consistency fix.

---

#### FIX 9 - THE THREE FALSE CONFLICTS LEFT ON THE LIVE RUN A SCREEN (2026-08-24)

**Suite 3866 passed / 2 failed**, the same two pre-existing. +30 tests in
`tests/test_false_conflicts_20260824.py`. Confirmed against the real Run A
session (`6b66c9f8-4e65-4b40-96cd-d090d07e7b35`) before and after: **7 rows ->
5 rows, conflict_count 6 -> 4.** The four survivors are the umbrella gate
(must survive) and the three pre-flagged fixture bugs (producer name/address,
umbrella SIR) - zero product false conflicts remain on that screen.

All three are the client's OWN opening paragraph, verbatim - values that "mean
the same thing but represent them differently" because of formatting,
abbreviations, **levels of detail**, or document structure.

**1. `Gl Limits` - a limits schedule is long, but it is not prose.** Three
printings of one set of GL limits:
```
"$1,000,000 Each Occurrence / $2,000,000 General Aggregate / $2,000,000
 Products/Completed Ops Aggregate"                                        (1_dec_page.pdf)
"Each Occurrence $1,000,000; General Aggregate $2,000,000"                (2_certificate.pdf)
"$1,000,000 Each Occurrence / ... / $100,000 Damage to Premises Rented
 to You / $5,000 Medical Expense"                                         (5_complex_tables.pdf)
```
The money branch of `same_fact` already owned this exact case ("a COMPOSITE
that lists FEWER limits is not disagreeing - it is saying less"), but the
36-word fullest printing tripped the 25-word PROSE FLOOR, which runs first and
returned `INCOMPARABLE` before the money rule ever got to run. Root-caused by
reproducing the mapping directly: `equivalent_index` returned `{0: 1, 1: 0, 2:
0}` - a CYCLE, violating its own documented keeper-final contract, because the
malformed pairwise verdicts (`0<->1: same`, `0<->2: incomparable`, `1<->2:
incomparable`) fed a clique algorithm that assumes consistent pairwise answers.

Fixed with a positive, structural exception: when the field is money-kind and
BOTH sides already parse to 2+ amounts, the prose gate is skipped and the
existing subset rule decides. A narrative field is untouched (`KIND_NARRATIVE`
is still checked first); a paragraph on a money field that merely quotes a
couple of figures still has to survive the subset test on its actual amounts,
so it is not exempted by word count alone. Verified: the malformed cycle is
gone, a genuinely different limit set (Run B's $2M/$4M/$4M) still conflicts,
`test_a_composite_amount_is_never_flattened`'s guard is untouched, and a real
two-paragraph pair on a money field stays `incomparable`.

**2. `Total Annual Payroll` - a per-class rating basis is not the package
total.** The picker offered `$1,880,000` (the real total) against `$285,000` /
`$640,000` / `$95,000` - the payroll BASES for GL classes 91580, 98305 and
91340 out of the package's own SCHEDULE OF HAZARDS (which don't even sum to
one). Source: `_text_scan_values` looks for a "payroll" label followed by an
amount, and a hazard schedule prints that phrase once per class row -
confirmed directly: the scan returns all four amounts for `total_payroll`.

`_drop_class_exposure_candidates` removes a TEXT-SCAN-ONLY candidate when the
amount is literally an `exposure_amount` / `payroll` column on one of this
package's OWN `gl_class_code_schedule` / `wc_class_codes` rows. Two guards, both
load-bearing: (1) positive evidence only - no schedule, no opinion; (2) a
candidate any document's EXTRACTION produced for this fact (not text-scan)
survives untouched, because a single-class business can legitimately have a
total equal to its one class basis, and the extractor naming it `total_payroll`
is independent evidence the text scan alone does not have. A real payroll
disagreement between two stated TOTALS still surfaces.

**3. `Contractor Type` - a free-text characterisation with no enumeration.**
*"Licensed electrical and roofing contractor"* (certificate) vs *"Commercial
General Contractor - Roofing and Electrical"* (dec page). Same trade, two
phrasings; the schema defines no enumeration for `contractor_type` so the model
returns whatever words each document used.

**First attempt reclassified the field as `KIND_NARRATIVE` outright and was
wrong** - `test_equivalence_families[contractor_type-...]` failed:
`"Commercial roofing contractor"` vs `"Commercia"` (an OCR mid-word truncation)
stopped returning SAME, because a true narrative field exits `same_fact`
unconditionally before containment or truncation ever run. Correct for an
actual paragraph; wrong for a short phrase that legitimately needs those
checks too. **Kept `contractor_type` at `KIND_TEXT`** so the full pipeline still
runs - exact match, containment, mid-word truncation, the WS-2 synonym table -
and only softened the FINAL fallback: a field in `_SOFT_TEXT_FACT_KEYS` that
survives every one of those checks without finding SAME returns
`INCOMPARABLE` instead of `DIFFERENT`, rather than being routed away from them
entirely. Both properties hold simultaneously: the truncation pair is SAME
again, the Run A phrasing pair is INCOMPARABLE (not a conflict), and both are
pinned by test.

**An explicit list, not a shape heuristic**, and deliberately so: 39 facts
classify `KIND_TEXT` and most are ENUMERATED terms - `construction_type`,
`occupancy_type`, `valuation_method`, `sprinkler_system`, `entity_type` - where
two different values ARE a real disagreement. A "looks like a phrase" rule
would have silenced every one of them; `test_no_enumerated_type_field_is_
treated_as_soft_text` fails the build if one is ever added without a decision.

**Known residual, stated rather than hidden:** two documents naming genuinely
DIFFERENT trades ("roofing contractor" vs "restaurant") also stop being a
conflict under this rule. Judged the lesser risk - a different insured is
caught by `applicant_name`, and today's behaviour asks the producer a question
about wording they cannot meaningfully answer either way.

**LIVE CONFIRMATION, both runs, 2026-08-24 - matches the unit-tested prediction
exactly, no surprises.**

Run A: **7 rows -> 4 rows.** `Gl Limits`, `Total Annual Payroll`, `Contractor
Type` all gone. Survivors: the scoped `Carrier` info row (3 policies, 3 values,
not a conflict - C1b), `Umbrella SIR`/`Producer Name`/`Producer Address` (the
pre-flagged fixture bugs, not product bugs) and the umbrella $3M-vs-$1M gate.
Zero product false conflicts left on the screen.

Run B: **14 rows, exactly as predicted** - `Gl Limits`, `Total Annual Payroll`,
`Contractor Type` gone as false conflicts; every real disagreement still fires
(`DBA`, `Mailing Address`, `Carrier`, `Employee Count`, `Umbrella Limit`,
`Total Policy Premium`, all four GL limit fields, `Policy Number`). **`Gl
Limits` is the one worth reading closely**: the three REAL printings (files 1,
2, 5) now fold into ONE value while file 6's genuinely different limits
($2M/$4M/$4M vs $1M/$2M/$2M) stay a separate, correctly-reasoned conflict -
proof the fix distinguishes "same limits, different detail" from "different
limits" rather than just suppressing the field. `Total Policy Premium` and all
four GL fields now read *"the documents state different amounts"* (FIX 6's
`_conflict_reason` money branch), not the generic fallback or the wrong
*"different identifiers"* string from before.

One unrelated item appeared on Run B this run - *"Property deductible defined
but basis not specified"* (Recommended before quoting tier). Not caused by
anything in this fix; consistent with the extraction jitter already logged
above (C1-Q, "extraction is not deterministic") surfacing a field this
particular run that a prior run didn't.

---

#### FIX 8 - ROUND 10 FIX 46 HAD COME BACK ONE LAYER UP (2026-08-23)

**Suite 3834 passed / 2 failed**, the same two pre-existing. Found by the FIRST
live run after C1b shipped.

**Run A grew a Carrier CONFLICT it had never had**, reason *"two policies on the
same coverage line"* - on a package whose three carriers sit on three DIFFERENT
lines. The store itself was correct (verified on session
`6b66c9f8`): `general_liab -> EMC Prop & Cas Co`, `auto/umbrella/inland_marine
-> Employers Mutual Cas Co`, `professional -> Hartford`.

**The comparison door grouped them correctly too** - three groups, checked
directly. The fault was in the picker's OWN first-pass grouping:
`_normalize(..., kind="identity")` calls `normalize_value`, which dispatches a
carrier to `normalize_carrier` - **the curated alias map, which folds
`EMC Property & Casualty Company` and `Employers Mutual Casualty Company` BOTH
to `emc`**. The merged group then owned the GL line AND the Auto line, and
collided with itself.

**D10 already records this exact rule, for the door:** *"the coarse normalisers
fold two real carriers into one token; that is Round 10 fix 46 and it must not
come back one layer up."* The door was fixed. The picker's own grouping never
was - and it was invisible until C1b made the per-line carriers candidates,
because with one carrier spelling on the package there was nothing to mis-merge.

Entity-kind values now group on `strict_entity_key`, mirroring the door.
**Splitting here is safe**: `_merge_equivalent_value_groups` runs afterwards and
re-merges through the door, which folds abbreviations while keeping distinct
entities apart. Grouping too finely costs a merge pass; grouping too coarsely
cannot be undone.

**Result on the live session:** `carrier_name` -> **scoped**, `EMC Property &
Casualty Company -> ['general_liab']`, `Employers Mutual Casualty Company ->
['auto','inland_marine','umbrella']`, `Hartford -> ['professional']`.
conflict_count back to 6. The rival-GL case still conflicts.

**EIGHTH bug of this arc, and the fourth caught by running Run A rather than
Run B.** The control run has now found more defects than the adversarial one.

---

#### FIX 7 - C1b / D19: SCOPE IS STORED ON THE FACT. D-1 LAYER 1 CLOSED (2026-08-23)

**Suite 3830 passed / 2 failed**, the same two pre-existing. +18 tests in
`tests/test_scoped_fact_store.py`.

Owner, 2026-08-21: *"we should carry relationship, we should store it somehow,
not just this but for every other important fact."* Client 1.1 puts
Scope/Association BEFORE Reconciliation. Until now scope was recovered INSIDE
the comparator from the value's own characters, and that weakness had already
produced three defects: **B14** (the certificate's umbrella `$1,000,000`
inheriting the GL policy's owner), **G3** (a Denver address folded into a
Lakewood one), and the reverted **Pass 1b** (a carrier printed
`EMC Prop & Cas Co` on one page and `EMC Property & Casualty Company` on
another losing its scope entirely).

**`extraction_service._build_scoped_fact_store` writes `facts["_scoped"]`** as
the LAST step of `merge_facts` - after the list union, after the entry repair,
after renewal routing - while the line -> carrier -> policy relationship still
exists:

```python
facts["_scoped"]["carrier_name"] = [
    {"value": "EMC Prop & Cas Co",
     "scope": {"line": "general_liab",
               "line_printed": "Commercial General Liability",
               "policy_number": "BBC7263-26"}}, ...
]
```

**ADDITIVE, exactly as D19 specifies.** `mf[key]` is untouched, so all 776
existing fact reads stay valid, and the key is PRIVATE so every consumer's
`startswith("_")` skip already excludes it (verified in
`underwriting_consistency`, `pdf_service`, `fact_state`).

**`underwriting_consistency._scope_from_store` is the reader**, consulted
BEFORE the character-keyed `_scope_values` - order pinned by test, because
consulting `owners_of` first would re-introduce the very defect the store
removes. A spelling variant still finds its scope, because value matching goes
through the one door (D3).

**Measured on the live data shapes:**

| | before C1b | after C1b |
|---|---|---|
| **Run A** - EMC on GL, Employers Mutual on Auto/IM/Umbrella | false **conflict**, `scope=None` | **`scoped`** - `EMC P&C -> ['general_liab']`, `Employers Mutual -> ['auto','inland_marine','umbrella']` |
| **Run B** - Travelers AND EMC both writing GL | **silent** (never a candidate) | **`conflict`** - *"two policies on the same coverage line in one submission - confirm which applies"* |

**D-1 Layer 1 is closed.** Pass 1b is reinstated - a per-line value is now a
candidate - and it is safe only because the scope arrives WITH it instead of
being inferred afterwards. That is the whole difference between this and the
attempt that was reverted four hours earlier.

**What this closes in the client's spec:** 1.1's ordering (scope before
reconciliation) and its single canonical fact for the comparison path; 1.2's
line/coverage axis and the client's own *"GL carrier and Auto carrier may
legitimately differ"* worked example, in BOTH directions.

**Known, deliberately not gold-plated:** on Run B the `policy_number` row now
lists all six numbers rather than only the two sharing a line. The row is
correct and actionable (the reason names the problem), but the value list is
noisier than it needs to be. Display refinement, not a correctness gap.

**Still character-keyed, and still worth watching:** `PackageContext.owners_of`
remains the path for any package with no `coverage_lines`, and for facts the
store does not cover. The store only removes the guesswork where it has
evidence.

---

#### FIX 6 - EXPLICIT NO IS REACHABLE FROM A DOCUMENT + CARRIER ABBREVIATIONS (2026-08-23)

**Suite 3812 passed / 2 failed**, the same two pre-existing. +30 tests in
`tests/test_explicit_no_from_source.py`.

**1.3 - `explicit_no` had no route from a document.** All three of the client's
own examples (*No prior losses*, *No subcontracting*, *No Property coverage*)
landed as `not_stated`; only a human answer or a literal negation STRING reached
it. Two grounded routes now exist, and neither weakens B8:

* **Tri-state facts.** `extraction_service.TRISTATE_BOOLEAN_FACTS` is DERIVED
  from the schema string by regex over `"key": boolean or null`. That contract
  tells the model to answer `null` when the document is silent, so a `false`
  IS the document saying no. Every other boolean in the schema is a bare
  `boolean` and stays `not_stated` - that is B8, where a certificate which never
  mentioned subcontractors produced `false` and manufactured a conflict plus an
  85 cap. Derived, never hand-listed, so a field demoted to a bare boolean stops
  being an Explicit No automatically. Pinned by
  `test_the_tristate_set_is_derived_from_the_schema_not_hand_listed`.
* **Absence assertions.** `ABSENCE_ASSERTION_FLAGS` connects a flag that
  affirmatively states absence to the facts it is an Explicit No about. Today:
  `asserts_no_known_losses` -> `loss_history` / `num_claims` /
  `total_incurred` / `loss_history_years`. The schema already asked for that
  flag precisely (*"true ONLY if the document affirmatively states the insured
  has had NO prior or known losses"*); nothing had ever connected it to the
  fact. **Gated on a blank value** - a real claim always wins - and a missing or
  false flag asserts nothing.

`annotate_fact_states(facts, flags)` carries the flags for the duration of the
pass and does not persist them, so nothing downstream gains a second copy.

**Carrier ABBREVIATIONS were splitting one carrier into two entities.** The
client's opening paragraph names abbreviations as a difference that must not
become a contradiction. `_STRICT_TOKEN_CANON` already expanded `cas`/`co`/`mut`
but stopped there, so:

```
EMC Prop & Cas Co            -> emc prop casualty company
EMC Property & Casualty Co   -> emc property casualty company     TWO ENTITIES
Travelers Prop Cas Co of Am  vs  Travelers Property Casualty Company of America
```

Added `prop`, `amer`/`am`/`american`, `intl`, `gen`, `assn`, `fin`, `svc(s)`,
`guar`, `exch`, `reins`, `agcy`, `underwrs`. **Every entry expands a
CORPORATE-FORM or GEOGRAPHIC word, never the distinguishing name**, so it is
structurally unable to fold two real carriers. Swept both directions, 12 pairs,
0 failures - including the ones that MUST stay different: `EMC Property &
Casualty` vs `Employers Mutual Casualty` (Round 10 fix 46), `Hartford Fire` vs
`Hartford Casualty`, `Travelers Property Casualty` vs `Travelers Casualty and
Surety`, `Liberty Mutual Insurance` vs `Liberty Insurance`.

#### D-1 LAYER 1 - ATTEMPTED, MEASURED, REVERTED. It needs C1b, not a patch.

The picker compares one SCALAR per document, and no declarations page produces
one for `carrier_name` - so a rival GL carrier was never a candidate. The
obvious patch is to raise the per-line values from `coverage_lines` as extra
candidates ("Pass 1b"). **Built it, measured it on the live data shapes, and
took it out.**

It fixed Run B - `policy_number` came back with exactly the right verdict,
*"two policies on the same coverage line in one submission - confirm which
applies"*. **And it broke Run A**, turning the client's own worked example
(*"GL carrier and Auto carrier may legitimately differ"*) into a false conflict:

```
RUN A  carrier_name  conflict   Employers Mutual Cas Co / EMC Property & Casualty Company
                                scope=None on both
```

Two reasons, and both say the same thing:

1. The per-line spellings are ABBREVIATED (`EMC Prop & Cas Co`) while the
   scalar is not, so they arrived as separate groups. FIX 6's abbreviation work
   closes this one - but only by luck of the spellings involved.
2. `PackageContext.owners_of` keys on the value's exact characters, so the
   group's DISPLAY spelling had no owner and `_scope_values` could not attribute
   it. **Scope silently unavailable is the failure mode that produces a false
   conflict**, and it is the same character-keyed weakness as B14 and G3.

**The lesson is structural, not incidental.** The picker's model is one scalar
per document; a line-scoped fact does not fit it, and bolting per-line
candidates into it re-derives scope from spelling at exactly the moment scope
matters most. That is what **C1b / D19** exists to fix - scope STORED on the
fact, written once at merge, read rather than re-derived. `_LINE_SCOPED_FACT_COLUMN`
(the fact -> `coverage_lines` column map) is kept in
`underwriting_consistency`, because C1b needs exactly that table.

**Seventh bug of the arc, caught before it shipped** - by running Run A as well
as Run B. A negative control that only checks the thing you are fixing is not a
control.

---

#### FIX 5 - THE ADDRESS CONFLICT CAME BACK AS "EQUIVALENT". Root cause: a money rule with no fact gate (2026-08-23)

**Suite 3782 passed / 2 failed**, the same two pre-existing.

**Reported from the live Run B after FIX 4:** `4800 Dahlia St # D13, Denver, CO
80216-3121` and `2255 S Wadsworth Blvd Ste 410, Lakewood, CO 80227` rendered
under *"Resolved formatting difference - treated as equivalent"*. The client's
ORIGINAL complaint, produced by the machinery built to fix it, and B1 regressed
from PASS.

**Not extraction, and not the union.** Verified per document on session
`12a16455`: file 6 extracted Lakewood correctly and all four printings reached
the comparison. Bisected the comparator instead:

```
compare(mailing_address, [D+4, D, D+4, Lakewood])   WITHOUT context -> conflict
                                                    WITH    context -> equivalent
pairwise: Denver+4 vs Lakewood  ctx=same  noctx=different
          Denver   vs Lakewood  ctx=different (both)
```

**`PackageContext.is_component_of` fired on an ADDRESS.** It answers "is one of
these a PIECE of the other?" and its whole docstring is about money - a LINE
premium inside a PACKAGE premium. It compares `_alnum(value)`, which on an
address yields `4800DahliaStD13DenverCO802163121`. The package index happened to
hold the Denver printing as a line-level value and the Lakewood one as
package-level, so the rule pronounced two different premises one fact.

**THIS IS THE SECOND TIME A CONTEXT RULE KEYED ON A VALUE'S CHARACTERS HAS
SILENCED A REAL CONFLICT.** The first was C1-H / B14 - the certificate's
umbrella `$1,000,000` inheriting the GL policy's ownership. `_owner_split_allowed`
was the gate added then, and it gates the OWNER rule by fact key.
`is_component_of` was left ungated for a year. Both context rules must now
declare which FACTS they may speak about: `_component_split_allowed` allows only
`money` / `count` / `percent`. An address, a name, a date, an identifier can
never be a "component" of anything.

**The gate then failed a test, and the TEST was right.**
`test_a_line_premium_is_a_component_of_the_package_total` broke, because
`value_kind("total_policy_premium")` returns **`identifier`** - so the rule's own
headline example was excluded by my gate. Root cause: `"policy"` sat in
`_IDENTIFIER_TOKENS_STRONG`, which is tested BEFORE `_MONEY_TOKENS`, so
`{total, policy, premium}` resolved on `policy` and every `policy_*` AMOUNT was
an identifier. That is also why Run B printed *"the documents carry different
identifiers"* about `$14,961` vs `$18,381`.

Demoted `"policy"` to WEAK (tested after money). **Swept before changing:
7 keys corrected** (`total_policy_premium`, `policy_premium`, `policy_limit`,
`policy_deductible`, `gl_policy_premium`, `auto_policy_premium`,
`umbrella_policy_limit`), **0 identifiers broken** - `policy_number`,
`prior_policy_number`, `policy_form_type`, `policy_term_months` and
`policy_effective_date` all keep their kind, because none carries a money token.

**Verified on the live session after the fix:** Denver+4 vs Lakewood ->
`different`; Denver+4 vs Denver ZIP5 -> `same` (formatting still folds); the
trio -> `conflict`; and `check_doc_consistency` emits the address WARNING again
instead of the `[info]` row. +19 tests.

**Standing lesson, and it is now recorded twice:** a rule that identifies a value
by its own characters must declare which FACT KINDS it may speak about. Any new
`PackageContext` predicate needs a gate before it is wired into
`equivalent_index`.

**Follow-on found by the same run:** `_conflict_reason` had no `money` branch.
A CURATED field arrives with kind `currency`/`integer` and is answered by the
first line of that function; an AUTO-DISCOVERED one arrives as `identity`
whatever it holds, and the only thing that knows better is `value_kind` - which
the function consulted for date / name / address / identifier and not for
money. So `gl_each_occurrence`, `gl_aggregate`, `gl_products_aggregate` and
`total_policy_premium` all printed *"materially different values remain after
normalization and scope matching"* against two plain dollar figures. Fixed;
`contractor_type` correctly keeps the generic wording, because free text is
exactly what it is.

#### LIVE CONFIRMATION - sessions `b0a47245` (Run A) / `a18829b7` (Run B), 2026-08-23

Both fixes verified on the real application, not on fixtures:

| Check | Result |
|---|---|
| Run A picker rows | **6** - unchanged from before the whole arc. No noise added |
| Run A `coverage_lines` | **5 rows incl. `Professional Liability / PL-99881-26`** - previously deleted |
| Run A mailing address | `[info]` on the two Denver spellings only - correct, no Lakewood in this run |
| Run B `coverage_lines` | **7 rows: BOTH GL policies (`BBC7263-26` AND `GL-4471102-26`), plus `Commercial Property / CP-4471103-26`** |
| Run B mailing address | **conflict, *"the documents point to materially different locations"*** - FIX 5 holds |
| Run B `check_doc_consistency` | emits the `[warning]`, not the `[info]` |
| `merge:` role log | `4_loss_run.pdf contributes no ['coverage_lines', 'lines_of_business']` |
| **ACORD 126 GL header** | `Policy_PolicyNumberIdentifier_A` -> **None**, `Insurer_FullName_A` -> **None**, logging *"2 different policy numbers attached to this line, box left blank"* |

That last row is the client's right-or-blank contract working on real data for
the first time: before FIX 4 the box stamped EMC's number with confidence
because Travelers had been deleted from the fact layer.

#### EXTRACTION JITTER IS REAL, AND IT IS NOW THE LOUDEST REMAINING NOISE

Same six PDFs, four runs, materially different facts each time. Observed:

* `umbrella_limit` came back `$1,000,000` in one run and `$3,000,000` in the
  next - the GATE value itself, decided by a coin flip
* `contractor_type` gained `Contracting` **from the loss run** and
  `Electrical Services` from file 6 on different runs
* `entity_type` merged to `LLC` in one run and `Limited Liability Company` in
  the next
* `check_doc_consistency` reported **4** contracts in one run and **5** in the next

The mechanism is visible in the merge log: most of these print
`score=1.54 freq=1` on BOTH sides. The scoring is tied and the winner is
whichever candidate the model happened to emit first. **This is not a
comparison defect and no amount of work on the comparison layer will settle
it** - it is upstream, in extraction and in the merge's tiebreak. It is also
why the same fixture never produces a byte-identical screen twice, which makes
every future live test harder to read. Ranked as the next thing worth attacking
after D-1 Layer 1.

---

#### FIX 4 - LAYER 2 IS FIXED (2026-08-23). Layer 1 is not.

**Suite 3764 passed / 2 failed**, the same two pre-existing, +26 tests in
`tests/test_merge_list_union.py`.

`merge_facts` now UNIONS a list field instead of replacing it. Primary rows go
first, so anything reading "the first matching row" keeps today's answer and a
companion can only ADD. De-duplication uses the schedule de-duplicator the
chunk-level merge already owns - one definition of "same vehicle / driver /
coverage part", not a second one.

**Fixing the LOOP rather than adding a fourth bespoke block was the point.**
`dec_page_entries` and `risk_transfer` each already carried a private
workaround for this exact defect; `coverage_lines`, `lines_of_business` and
`auto_covered_symbols` never got one. A fourth special case would have left the
next list field exposed - gate 1 of the quality bar.

**Measured on the live session, before -> after:**

| | before | after |
|---|---|---|
| `coverage_lines` | 4 | **7** - Travelers GL `GL-4471102-26`, Travelers Property `CP-4471103-26` and Hartford PL `PL-99881-26` recovered, all four original rows keeping their own policy numbers |
| `lines_of_business` | 4 | **6** - Professional Liability and Commercial Property recovered |
| `auto_covered_symbols` | 3 | 8 rows / **5 coverages** - `parse_symbols` gained `medical` and `um_uim` from the second dec page |

**Two defects the A/B caught that reasoning had not** - this is why the change
was measured on the real session instead of shipped on unit tests:

1. **The repair pass cleared EVERY policy number** (`4 cleared, 0 repaired`).
   The loss run pairs the AUTO number with BOTH `Business Auto` and
   `General Liability` - the CLAIMS' lines - so one number spanned two canonical
   lines and `_coverage_lines_are_self_contradictory` correctly read the list as
   corrupt. Fixed by giving the list union the same DOCUMENT ROLE scope every
   cross-document comparison already uses: `coverage_lines` and
   `lines_of_business` are now in `fact_comparison._ROLE_BLIND_FACTS["loss_run"]`,
   alongside the scalar `policy_number` / `carrier_name` that were already there
   (D23). Fail-open, so an unknown doc type still contributes everything.
2. **`lines_of_business` came out with 11 entries for a 6-line package** -
   `Commercial General Liability` AND `General Liability`, `Commercial
   Automobile Liability` AND `Automobile Liability` AND `Business Auto`. A text
   union cannot see that those are one coverage part, which is client 1.7's
   complaint exactly. It now de-duplicates by canonical FAMILY, first printing
   wins, and unmappable terminology still falls back to its own text and is
   never folded (D9).

**`coverage_lines` identity is the PAIR (line, contract)**, registered in
`_SCHEDULE_DEDUP_KEYS`. Neither half works alone and both failures are already
on the record: policy number alone folds two real coverage parts (`BBC7263-26`
carries GL *and* Employee Benefits Liability - the measured case in the
`_NATURAL_ID_SUBKEYS` comment), line alone folds two real policies, which IS
D-1. No canonical line means no key and no merge.

**THE FORM SIDE IS NOW CORRECT, and it is a visible change.** Executed against
`_resolve_section_policy_identity`: with two carriers claiming General
Liability, ACORD 126's policy-number and insurer boxes now come back **blank**,
logging *"2 different policy numbers attached to this line, box left blank"*.
Before the fix it stamped EMC's number with full confidence, because Travelers
had been deleted. Right-or-blank, and the resolver needed no change - it was
already built for this and had simply never been shown the second policy.
A row with no policy number (a certificate row) costs the form nothing: the
resolver ignores it. Both pinned by test.

**LAYER 1 REMAINS OPEN, and D-1 is therefore HALF fixed.** Re-running the
picker on the live session after the fix: **12 conflict rows, still no
`carrier_name` row.** The data is now present and the forms behave correctly,
but the producer is still never ASKED, because the picker compares per-document
SCALARS and no declarations page produces one. Closing it means teaching the
picker to raise a candidate from `coverage_lines` when the scalar is absent -
a structural change to how it gathers candidates, affecting every reconcilable
field. **Not bundled with this fix**; six bugs in this arc were introduced BY a
fix, and every one came from doing two things at once.

**The original blast-radius note, kept for the record:** The
correction is to UNION the primary's list rows into the merged list (through
the existing `_dedupe_schedule_rows`) instead of replacing. Note the primary's
own rows are NOT in the merged list today - `_merge_list_fields` is called on
`non_primary` only - so a bare `continue` would delete the primary's lines
instead. Consumers that move: `_resolve_section_policy_identity` (form
stamping), `_resolve_lob_premium`, `denied_families` / the LOB conflict,
`PackageContext.contracts` -> `is_multi_contract` (which downgrades date hard
stops), and every other `_LIST_FIELDS` member - vehicles, drivers, loss
history, locations, class codes - which are all being clobbered the same way
and would start unioning.

**The original D-1 note, kept because the elimination work is what narrowed it:**

**B4: a genuine second GL carrier produced SILENCE.**
Travelers writing GL `GL-4471102-26` against EMC writing GL `BBC7263-26`, same
period, same line: no conflict row AND no scoped row. The comparison layer was
cleared by execution - `verdict("carrier_name", EMC, Travelers)` returns
`different`, a 3-way `compare` returns three distinct groups,
`_drop_foreign_line_values` keeps both (the "Property in the carrier's name"
theory was wrong), and with both GL rows present `_scope_values` returns exactly
*"two policies on the same coverage line in one submission"*. So the door is
right and something UPSTREAM never handed it the second carrier.
**Not guessed further** - `scripts/dump_session_facts.py`'s own docstring is the
precedent: *"three of four predictions about conflict behaviour were wrong, and
every one was wrong because the reasoning was done against the CODE instead of
against a real session's facts."* Needs the Run B dump of `carrier_name`,
`policy_number` and `coverage_lines`.

**Note for the reader: check 3 has been graded too generously since C1-N.** Its
recorded evidence is *"no carrier row"* - but the UI renders scoped rows with a
`N policies, N values - not a conflict` badge (`AcordModal.jsx`), and none
appeared in either run. **"No row" means never compared, not correctly scoped.**
Check 3 cannot tell those apart and must be rewritten to require the badge.

**D-2 (OPEN) - class-code exposures offered as rivals to the package total.**
Run A asked the producer to choose between `$1,880,000` total payroll and
`$285,000` / `$640,000` / `$95,000` - the per-class payroll BASES from file 5's
SCHEDULE OF HAZARDS (classes 91580 / 98305 / 91340, two locations). They are not
rival totals and do not even sum to one.
**This is NOT an item-scope gap, and C1-P already ruled on why:** *"EXACT match,
never a suffix: `total_payroll` ends with `payroll`, a wc_class_codes column, and
a package total is emphatically not a per-class figure."* Combined with D20
(money never scopes), scope was never the route. The defect is one layer earlier
- the exposures were accepted as CANDIDATES for `total_payroll` at all. The fix
is a witness/meaning gate on the candidate list; `_enforce_numeric_meaning_gate`
already does exactly this job but runs only in gap fill, never in the picker.

**D-3 (OPEN) - prose is not being typed as prose.** *"Licensed electrical and
roofing contractor"* vs *"Commercial General Contractor - Roofing and
Electrical"* opened a Data Consistency conflict. That is the client's own
opening paragraph - *"levels of detail"* - and prose is supposed to return
INCOMPARABLE. The generic fallback reason string proves `value_kind` never
classified it. Root cause not yet found.

**D-4 (FIXED) - every identity conflict rendered TWICE.** See below.

#### FIX 1 - one disagreement, one row (D-4)

Run B showed *"DBA / trade name differs across documents: ..."* directly above
*"DBA / Trade Name: documents disagree (...)"* in ONE cluster. Mailing Address
did the same, **and the legacy copy printed all THREE address spellings
including the two the picker had correctly folded** - so the older row read
exactly like the bug the folding fixed.

Root cause: two engines compare the same eight identity fields and both render.
`check_doc_consistency` emits `doc_conflict_(hard|warn)_*`; the picker emits
`underwriting_reconciliation_*`. Nothing paired them.

**Fixed by REUSING the mechanism that already existed** rather than building a
second one: `build_grouped_view` has carried a display-only supersession block
since 2026-08-14 (`_LEGACY_SUPERSEDED_BY_CODE`). The new block sits directly
beneath it under the same contract - gated on the superseding row actually being
present, and **the caller's `hard_stops` / `soft_stops` are never mutated**, so
SQS caps, dismiss credit and `issue_id` hashing are untouched (pinned by
`test_the_callers_stop_arrays_are_not_mutated`).

Pairing is by FACT, not by phrase: `doc_conflict_fact_key()` and
`picker_fact_key()` in `issue_registry`. Most doc-consistency issues already
carry `field=<fact_key>` and need no remap; four predate that convention and are
listed in `_DOC_CONFLICT_CODE_TO_FACT` - **and nowhere else**, replacing a
duplicate of that map which had been sitting in `AcordModal.jsx`.

**A BLOCKER CAN NEVER BE HIDDEN.** A hard-stop twin is suppressed only when the
surviving picker row is ALSO a hard stop. Today the sets agree exactly
(`HARD_STOP_RECONCILABLE_KEYS` is precisely the four fields
`check_doc_consistency` hard-stops on) and both engines downgrade the two date
rules on a multi-contract package - so this guard is not needed today. It exists
so that a future drift degrades to a duplicate row instead of a 60 cap with
nothing on screen explaining it.

**E9 collapsed into this fix.** The folded-spellings row was going to be patched
separately; hiding the legacy row entirely removes it at the source.

#### FIX 2 - an unrecognised coverage part now reaches the producer (1.7)

Client 1.7: *"Leave it unmapped **or route it for producer review when
material**."* Only the first half was ever built - `canon_line` returns None and
every call site skips it, verified across all 20 call sites. A coverage part
Primble could not place was silently invisible: never compared, never scored,
never asked about, and nobody told.

`lob_canon.unmapped_material_lines()` returns the ORIGINAL printed names of
lines that cannot be canonicalised AND that the package's own documents show are
CARRIED - a premium or limit on the entry, the same positive-evidence test
`denied_families` uses to withdraw a denial. **The material gate is what stops a
review item appearing on every ordinary certificate**, whose rows carry no
premium (D26: silence is not evidence).

**ADVISORY, and that is Principle 7 not timidity.** We do not know what the line
IS, so we cannot know what it should cost: *"give it no new scoring effect until
a rule is explicitly defined."* The issue goes to `structured_issues` only and
never into `hard_stops` / `soft_stops`, so it renders and moves nothing. Pinned
by a source-level test, because a test that drove the pipeline would prove
today's wiring rather than the rule.

#### FIX 3 - the one-door guard was blind, and a breach was live

`test_comparison_has_one_owner` matched imports with a regex whose lookahead
required the statement to end at column 0 or a blank line. **An indented import
inside a function body never matched** - and
`underwriting_consistency.py:1391` had been importing
`normalization.entity_identity_conflict`, a name on the guard's OWN forbidden
list, for weeks with the test green. Proved by running an AST walk against the
same file: AST finds it, the regex returns `[]`.

Three changes: the guard now parses the module (so indentation, line wrapping,
placement and `import X as Y` aliasing are all visible); the breach is routed
through the door as `fact_comparison.entities_materially_differ()` - **pure
delegation, behaviour byte-identical**, documented as the third question the
door answers (`conflict` asks about a whole value list; this is the narrow
RE-SPLIT test the picker applies after a merge has already collapsed a group);
and the private `fact_comparison._fe` back channel now has a PINNED user set, so
a new bypass fails the build instead of appearing quietly.

`test_the_guard_can_actually_see_an_indented_import` is a C25 self-check: the
previous guard passed while a real breach sat in the tree, so the replacement
has to prove it bites on the exact shape it used to miss.

#### Two Tier-A items were DROPPED, deliberately, and this is the reason

Both were listed as "safe" because they only ever REMOVE a comparison. Safe is
not the same as justified.

* **More document roles** (`_ROLE_BLIND_FACTS` has one entry, `loss_run`).
  Neither run produced a single defect attributable to a certificate,
  application or dec-page role. Adding blindness with no observed defect is
  inventing an insurance rule - Principle 7 - and it can only DELETE a
  legitimate comparison.
* **Enforcing `is_comparable` at the comparison sites.** Traced it: the door's
  `_usable()` already drops empty strings and a boolean `False` stringifies to
  `""`, so booleans never reach a comparison anyway; and both `not_applicable`
  and `unable_to_determine` are gated on an EMPTY value, so neither can carry a
  rival. **Wiring it would be a no-op dressed as a fix.**

#### Also corrected in this session: a stale grade

`"none"` was listed as a one-line ordering bug in `fact_state._EMPTY_STRINGS`
vs `_NEGATION_STRINGS`. **It is not, and fixing it that way would reintroduce
B8 generically.** `extraction_service._NULL_STRINGS` is
`{"null", "none", "n/a", "na", "unknown", ""}` - `"none"` is how the model
writes a NULL - and `extraction_service.py:5397` already records the same
finding for denial phrases: *"'none' appears all over a dec page"*. The entry in
`_NEGATION_STRINGS` is unreachable dead code; `explicit_no` needs a grounded
document negation, not a bare token. **Left alone, deliberately.**

#### Files

`services/issue_registry.py`, `services/lob_canon.py`,
`services/extraction_pipeline.py`, `services/fact_comparison.py`,
`services/underwriting_consistency.py`,
`tests/test_doc_conflict_supersession.py` (new),
`tests/test_unmapped_coverage_line.py` (new),
`tests/test_comparison_has_one_owner.py`,
`backend/scripts/make_v1_c1_adversarial_pdf.py` (new),
`test_data_v1_c1/6_conflicting_dec.pdf` (new),
`test_data_v1_c1/README-RUN-A-AND-B.md` (new).

#### Tell Brent (D6)

FIX 2 can add a review item to packages that previously had none. It is
advisory and caps nothing, but it is a new row on the screen.

---

### C1-P 1.2 ITEM SCOPE + 1.3's TWO DEAD STATES - SHIPPED (2026-08-22)
**The last two partials in client section 1. Both were the same shape: the fact
layer could not express something the spec requires.** Suite **3664 passed / 2
failed / 2 skipped** - the same two pre-existing unrelated failures, zero
regressions, +39 tests in `tests/test_v1_c1b_scope_and_states.py`.

#### 1.2 - the picker had ONE scope axis, and it was the policy

`_scope_values` could separate two values by CONTRACT or by LINE. Nothing could
separate them by the thing they physically describe, so a package with two
BUILDINGS raised a Data Consistency question for every column where the two
buildings legitimately differ - year built, construction type, building value.

**`PackageContext` gains an ITEM axis** (`item_owner`, `item_columns`,
`items_of`, `different_items`, `is_item_scoped_fact`), built from the package's
OWN schedule rows: `property_locations[1]` is a different building from
`property_locations[0]`, so two values printed by those two rows are two facts.

**TWO GATES, and B14 is why both are needed.** `value_owner` keys on a value's
characters, which is how the certificate's umbrella `$1,000,000` inherited the
GL policy's ownership and silenced the client's real conflict.
  1. **The fact must be PROVEN per-item** - its key is literally a column name
     in one of this package's schedules. **EXACT match, never a suffix**:
     `total_payroll` ends with `payroll`, a wc_class_codes column, and a package
     total is emphatically not a per-class figure.
  2. **Ownership disjoint and non-empty on both sides.** A coincidental
     character match can only ADD owners, which makes overlap MORE likely and
     scoping LESS likely - the failure mode is "show the conflict".

**Contract indexes are excluded, and DERIVED rather than named:** a list whose
rows carry `policy_number` / `line` / `line_of_business` is a contract index
(`coverage_lines`, `dec_page_entries`) and belongs to the policy axis, which has
its own overlap rules. Letting them in would give `policy_number` a second,
weaker route to being scoped that bypasses the "two policies on the same
coverage line" check.

**One ordering bug caught by forward simulation, before shipping:** the item
branch was first placed behind `_scope_values`' `is_multi_contract` gate. That
gate is a precondition of the POLICY axis - it asks whether there are two
contracts to tell apart. Two buildings on ONE policy is completely ordinary, so
the branch would have been unreachable on exactly the packages it exists for.

**The gate holds:** `test_the_umbrella_conflict_survives_item_scope` -
`umbrella_limit` is not a column in any schedule, so gate 1 refuses it whatever
the amounts coincide with.

#### 1.3 - `not_applicable` and `unable_to_determine` had ZERO writers

Both were declared, documented and derivable. Grepped: nothing in the pipeline
ever set `not_applicable` on an envelope or wrote `rejected_by` / `withheld`.
Every blank fact read `not_stated` whatever the reason for the blank.

**`not_applicable` <- an explicitly declined coverage line.** `lob_canon` now
owns `COVERAGE_DENIAL_RE` (ONE definition; `extraction_service` re-binds the
name it exports), plus `denies_coverage(entry)` and `denied_families(lines)`.
A denial is **withdrawn the moment any entry GRANTS the same family** - two
sources disagreeing about whether a coverage exists is a conflict for the
producer, which is client 1.7's own acceptance criterion, not a quiet N/A. The
line NAME can never deny itself (only detail columns carry a verdict), unmapped
terminology gets no opinion (1.7), and a fact that HAS a value always wins.

**`unable_to_determine` <- the rejection ledger.** Several components already
found a value, judged it unusable and DISCARDED it - an endorsement date that is
not an inception date, a page heading mistaken for a remark, a renewal whose
proposed term length is stated nowhere. Each logged its reasoning and dropped
the fact, making the result indistinguishable from a document that never
mentioned the subject. `_record_fact_rejection` records the judgement already
made; it never makes one, never resurrects a value, and changes nothing any
existing consumer reads.

**`value_state_of(facts, key)` is the new public query, and the absent case is
the point.** Both new states are answers about fields we do NOT have a value
for, so a state readable only off an existing envelope can never express either.

#### The consumer, and the hole forward-simulation found in my own change

A state nothing reads is theatre, so the questionnaire now skips questions about
a declined coverage. **First cut was wrong and would have shipped a real harm:**
`coverage_lines` is read off the uploaded declarations page, which on a RENEWAL
is the EXPIRING policy - so "COMMERCIAL PROPERTY - NO COVERAGE" states what they
HAD, not what they are applying for. A producer who selected ACORD 140 is
applying for property now, and suppressing those questions would have left that
form blank AND unaskable.

**The selected forms override the documents.** `_lines_the_producer_is_applying_for`
reads the same `_SECTION_FORM_LINE_PHRASES` table `fact_line` uses, so the two
cannot drift. Selecting the section is the producer's own positive evidence and
it wins. A missing form list suppresses nothing - a filter that REMOVES
questions must never act on an input it was not given.

What survives the override is the real target: a package that declines property,
does NOT select ACORD 140, and was still asking the client for the building's
year built off ACORD 125's premises grid.

---

### C1-O F-1 ROOT CAUSE - three layers, and the fix is already written (2026-08-22)
**Investigation only. No code changed. Awaiting go-ahead.**

F-1 (ACORD 126 stamped GL class codes `8810` / `5645`, present in NO uploaded document)
is not one bug. THREE independent layers had to fail, and each failure is worth recording
separately because two of them are general, not specific to class codes.

**Layer 1 - the box was ASKED, correctly.** `_resolve_gl_hazard_row` returns `"UNMATCHED"`
when `gl_class_code_schedule` is empty, by explicit design: *"suppressing on no evidence
would delete a schedule the extractor merely missed"* (Principle 3). Right call. The
consequence is that gap fill is asked a question the package cannot answer.

**Layer 2 - nothing required the answer to come FROM the document.** The evidence gate
covers Y/N fields only. A typed identifier box carries no grounding contract; the prompt's
"copy verbatim, omit if not found" is an instruction, not a constraint. Asked for a 4-digit
code with no evidence, the model emitted the highest-frequency codes of that shape in its
training data. **The proof is what it paired them with:** `Classification = "Roofing
Contractor"` IS in the document; `ClassCode = "8810"` is not - and 8810 is actually
*Clerical Office Employees NOC*. Copyable half copied, uncopyable half invented. That
hybrid is the signature of a model filling a FORMAT, not reading a document.

**Layer 3 - the guard built for this defect is blind by NAME.**
`_drop_ungrounded_classification_codes` matches field names against three fragments:
`SICCode`, `NAICSCode`, `GeneralLiabilityCode`. The field is
`GeneralLiability_Hazard_ClassCode_A`. **None is a substring of it.** Swept all 17 schemas:

```
covered fields = 36     blind fields = 38
```

Blind: ACORD 126 GL hazard codes, ACORD 127 vehicle rate + special industry class,
ACORD 130 WC classification (14+4), ACORD 140/160 protection class, ACORD 141/160 safe
vault, 125/126 scheduled-item class. **More than half the classification-code boxes in the
product have never been protected.** The guard is an allow-list of the three defects
someone happened to see - the exact anti-pattern the CHANGE QUALITY BAR forbids.

**The fix already exists and is switched off.** `_report_ungrounded_ai_values` is generic:
it derives strict / lenient / skip from **ACORD's own declared type** (`_TOOLTIP_TYPE_RE`,
3,888 of 5,852 fields), skips what the pipeline legitimately reformats (dates, years,
percentages, checkboxes), and is already running on every generation. Its own docstring
sets the bar for enabling it: *"the decision must be backed by a measured run, not by this
function looking reasonable."* Driven against the four live values:

```
GROUNDING_SHADOW checked=4 skipped=0 not_in_document=3
  WOULD_BLANK GeneralLiability_Hazard_ClassCode_A[strict]='8810'
  WOULD_BLANK GeneralLiability_Hazard_ClassCode_B[strict]='5645'
  WOULD_BLANK GeneralLiability_Hazard_Classification_B[lenient]='Electrical Work'
```

**4 of 4 correct** - both invented codes flagged, the invented description flagged, and
`"Roofing Contractor"` correctly LEFT ALONE because it is genuinely in the text. The named
guard, on the same four values, blanked **nothing**.

**Scope limit of that evidence, stated honestly:** this proves the verdict on four values.
It does NOT establish the false-positive rate across a whole form. That number is already
being logged on every real run - `grep GROUNDING_SHADOW <run log>` for the
`checked=` / `not_in_document=` counts. Pull it before enabling.

**Proposed fix (NOT started):** promote the generic guard from report to enforce, rather
than adding a fourth name to the allow-list. Widening `_CLASSIFICATION_CODE_LABELS` would
fix ACORD 126 and leave 35 other boxes exposed - a symptom fix by gate 1 of the quality
bar. Enforcing the declared-type check makes F-1 structurally impossible across all 5,852
fields, deterministically, with no LLM involved. F-3 (a date in a count box) and F-4 (`C`
in a Y/N box) are the same family and are covered by the same move.

---

### C1-N FORMS GENERATED - 1.8 verified, form-side defects catalogued (2026-08-22)
**Priority:** V1-CRITICAL for the C1 verdict; the defects below are FORM-FILL, i.e. C3/H6.

#### 1.8 Loss-Run Identity - PASSES LIVE. The last untested clause in section 1.

```
Loss History
  Loss data reconciled
  Losses extracted
  Matched on: name, fein, policy number
```

`strong`, on a loss run whose FEIN has no punctuation (`842210987` vs `84-2210987`), whose
policy number is spaced (`6E7 40 02 26` vs `6E7-40-02---26`) and whose carrier is a group
alias (`EMC Insurance Companies`). All three normalisations proven end to end, and no false
"carrier does not match" note. **Client section 1 is now live-verified in full.**

#### Other form-side PASSES

* **ACORD 131 header** carries the UMBRELLA policy `6J7-40-02---26` + Employers Mutual - the
  2026-08-15 relationship-preservation work holding under a 4-policy package.
* **ACORD 131 underlying table** pairs Auto -> Employers Mutual -> `6E7-40-02---26` and
  GL -> EMC P&C correctly. Two carriers, two lines, no cross-contamination.
* **ACORD 125 premises**: ONE row, `4800 Dahlia St D13` / `Denver` / `CO` / `80216`
  (check 8).
* **ACORD 125 umbrella-driven boxes filled**, not blank - Brent's Q4 ruling working
  (check 6): ACORD 131 shows `$3,000,000` EA OCC / AGG while the conflict is still open.
* **STATUS OF TRANSACTION = RENEW** ticked; loss rows and `$17,150` total correct.

#### FIXTURE DEFECT, not a product bug - recorded so it is not chased again

`1_dec_page.pdf` extracted as `...Casualty ComBpBaCny7263-26` - reportlab placed the CARRIER
and POLICY NUMBER columns close enough that pdfplumber interleaved their characters, so
`BBC7263-26` reached extraction as `7263-26`. That looked exactly like a truncation bug.
**The generator now uses wider columns AND states each line's carrier/policy as plain
`label: value` pairs**, which no column geometry can scramble. Re-generate before re-testing.

#### FORM-SIDE DEFECTS FOUND (ranked). None are Data Consistency; all are form fill.

| # | Defect | Evidence | Severity |
|---|---|---|---|
| F-1 | **GL class codes INVENTED.** ACORD 126 Schedule of Hazards shows `8810 Roofing Contractor`, `5645 Electrical Work`, `8810 Clerical Office Employees NOC` | Verified: **none of `8810`, `5645` appears in ANY uploaded document**, and the pre-form screen itself said "GL coverage detected but no class codes found". Both are WC codes, and 8810 is Clerical Office - mislabelled "Roofing Contractor" | **CRITICAL** - the client's 125 doc says verbatim: *"A box existing is not permission to fill it. NAIC code, GL class code, payment plan, policy premium, policy number: populate only from a verified source"* |
| F-2 | **ACORD 126 header carries the AUTO policy number** `6E7-40-02---26`, while its CARRIER is correctly the GL carrier | `_resolve_section_policy_identity` returns `7263-26` for ACORD_126 when driven directly - so the live `coverage_lines` must have differed. Likely downstream of the fixture garbling; **must be re-checked on a clean run before chasing** | HIGH |
| F-3 | **Dates in a COUNT box.** ACORD 126 `# OF UNITS` = `07/15/2026`, `07/15/2027` | C22's type-aware rejection covers name/VIN/year shapes; a full date in a units box is not yet one of them | MEDIUM |
| F-4 | **`C` in a Y/N box.** ACORD 125 CLAIM OPEN Y/N shows `C` (from "Closed") | Should be `N` | MEDIUM |
| F-5 | **ACORD 131 Q24 "Product liability loss in past 3 years?" = Y**, citing `11/02/2022 General Liability Water damage to customer premises` | Water damage to a customer premises is not a PRODUCTS loss, and 11/2022 is outside a 3-year window from 08/2026. Two errors in one answer | MEDIUM |
| F-6 | **ACORD 126 BODILY INJURY deductible `$1,000`** | The only `$1,000` in the package is the AUTO comprehensive/collision deductible. Cross-line contamination - the same class as the 2026-08-15 umbrella/auto conflation, one coverage part over | MEDIUM |
| F-7 | ACORD 126 Products table: `Performed At Customer Locatio` (truncated) in PRODUCTS; business revenue `$4,250,000` in ANNUAL GROSS SALES for products | Narrative fragment placed in a structured column | LOW |
| F-8 | `Emc Property & Casualty Company` - acronym lowercased by display canonicalisation | Cosmetic on a legal document | LOW |

**F-1 is the one that matters.** It is not a formatting problem: it is the fill layer
inventing a rating classification that appears nowhere in the submission, on a document an
underwriter prices from. F-3, F-4 and F-5 are the same family one level down - a value that
is the wrong TYPE or drawn from the wrong EVIDENCE for the box it lands in.

**Proposed fix direction (NOT started, needs go-ahead):** the client already named the
remedy - a "verified source only" gate for the five families they list (NAIC code, GL class
code, payment plan, policy premium, policy number). That is the evidence gate generalised
from Y/N answers to typed identifier boxes: a value must be literally present in the
uploaded text or be blanked. Deterministic, no LLM, and it makes F-1 structurally impossible
rather than prompt-discouraged.

---

### C1-M SIXTH LIVE RUN - PRE-FORM SCREEN SIGNED OFF (2026-08-21)
**Priority:** V1-CRITICAL
**Status: the pre-generation half of C1 is DONE and live-verified.**

#### Confirmed on real documents

```
Submission Readiness : 78%   (was 67% - the derived years_in_business closed a Tier-2 gap)
Submission integrity : Documents verified
Auto symbol warning  : GONE  (combined "Comprehensive and Collision" label now parsed)
Needs client input   : Prior carrier name, NAICS/SIC only  (years in business dropped)
Data Consistency     : 1 row - Umbrella $3,000,000 vs $1,000,000
```

#### Client section 1, clause by clause, LIVE-VERIFIED

| Clause | Live evidence on the pre-form screen |
|---|---|
| 1.6 Address | all three spellings under "treated as equivalent"; no issue, no warning, no cap |
| 1.7 Lines of business | "Coverage terms: ... - treated as equivalent" - the info path, not a warning |
| 1.5 Selection rules | the umbrella conflict retains both values, both sources and a reason |
| 1.2 Fact scope | 4 policies + 2 carriers raise nothing; the loss run no longer testifies about policy identity; **two buildings are two facts, not a conflict (C1-P)** |
| 1.4 Evidence states | `years_in_business` derived and labelled `derived` |
| 1.1 Canonical flow | one comparison door; six sites routed through it |
| 1.3 Value states | written on every envelope; **all 6 now have a writer (C1-P)** |
| 1.8 Loss-run identity | NOT yet visible - needs the Loss History card after generation |

Every false conflict the client reported in section 1 is gone on real documents, and the one
real conflict survives.

#### Deliberately NOT derived - raised instead of guessed

The screen still asks for **prior carrier name**, and the dec page does name carriers. It is
tempting to derive it. **It is an insurance judgment, so Principle 7 applies:** the carrier
on a RENEWAL dec is the prior carrier only when the uploaded dec is the EXPIRING one. A
renewal quote from a NEW carrier names the incoming carrier instead, and
`_route_renewal_dates` only treats a term as expiring when it has actually ENDED - this
fixture's term has not. Deriving it would be inventing a rule the client has not written.
**Raised as Q8.**

`years_in_business` was different and that distinction is the point: today minus a stated
start date is arithmetic, not judgment.

---

### C1-L FIFTH LIVE RUN - pre-form screen CLEAN; 2 defects I had wrongly dismissed (2026-08-21)
**Priority:** V1-CRITICAL

#### The pre-form screen is done

```
Submission integrity : Documents verified
Lines of business    : "Coverage terms: ... - treated as equivalent"   (info, not a warning)
Data Consistency     : 1 row - Umbrella $3,000,000 vs $1,000,000
```

Every false conflict the client reported in section 1 is gone on real documents, and the one
real conflict survives. The LOB difference now renders in "Resolved formatting difference",
which is exactly the acceptance criteria's wording.

#### I had dismissed the auto-symbol warning TWICE as a fixture artefact. It was a real bug.

`normalize_coverage` maps a label to ONE coverage - the first pattern that matches. A dec
page prints physical damage as a COMBINED label:

```
Comprehensive / Collision   Symbol 07   Deductible $1,000
```

`parse_symbols([{"coverage": "Comprehensive and Collision", "symbols": [7]}])`
-> `{"comprehensive": [7]}`. **Collision was dropped**, so the check reported "no
covered-auto symbol was found for: collision" on a policy that plainly shows Symbol 07 for
both. Generic, not fixture-specific: "Comp/Coll", "OTC & Collision" and
"Physical Damage (Comprehensive and Collision)" all failed the same way.

**Fix:** `normalize_coverages()` returns EVERY coverage a label names; `parse_symbols`
assigns the symbol to all of them, on both the structured and the free-text producer path.
The scalar `normalize_coverage` is unchanged for its other callers. The umbrella term is
dropped when the specific parts are present, so a symbol is never counted under a third key
no ACORD box uses.

**Lesson recorded:** I called it a fixture artefact twice without checking. The quality bar
says verify, not assume - that applies to dismissing an issue just as much as to fixing one.

#### "Years in business" was asked while the dec page states the answer

The screen said *"Needs client input: ... Years in business"* while `1_dec_page.pdf` prints
**"Date Business Started: 06/15/2014"**. That is client 1.4's **Derived** state
(*"deterministically calculated from supported facts using a known rule"*) with no producer,
and it is Brent's own Q1 point: if the paperwork says it, do not ask.

**Fix:** `_derive_years_in_business` in the merge tail. Positive evidence only - never
overwrites an existing value, requires a parseable date, refuses a FUTURE date (the policy
inception date landing in that box is a known defect), bounds the result at 500 years, and
labels the value `evidence_state: derived` so the E&O record shows it was computed, not read.

#### What remains on the screen is CORRECT

* **Umbrella $3,000,000 vs $1,000,000** - the real conflict. It must stay.
* **"GL coverage detected but no class codes found"** - the fixture genuinely has none.
* **"UM/UIM not specified"** - the documents genuinely do not state it.
* **"Prior carrier name", "NAICS or SIC"** - genuinely absent / deliberately producer-facing.

Tests: +21 (181 in the C1 file). **Full suite: 3625 passed / 2 failed / 2 skipped** - the
two pre-existing unrelated failures. Zero regressions.

---

### C1-K FOURTH LIVE RUN - integrity clean; the LOB warning's REAL cause found (2026-08-21)
**Priority:** V1-CRITICAL

#### C1c confirmed live

Submission integrity now reads **"Documents verified - the uploaded documents appear to
belong to the same submission"**, and all four documents show a match verdict. The three
false review notes are gone on real extraction, not just in a fixture.

#### The LOB warning survived TWO of my fixes. Here is why.

I had used `not _line_entry_grants_coverage(entry)` as the denial test. That function
answers *"is there positive proof of a grant?"* - a premium or a limit. **Its FALSE means
"not proven", not "denied".**

**A certificate of insurance never prints premiums.** So on the live package every COI row
- `{"line": "General Liability", "policy_number": "BBC7263-26"}` - failed the grant test,
was read as a DENIAL of General Liability, and contradicted the dec page that lists it
active. The warning was manufactured by the fix meant to remove it.

That is **absence of evidence turned into evidence**: Principle 3's forbidden move,
committed inside the code enforcing Principle 3.

**Root cause, and why the previous two attempts missed it:** the codebase had a `grants`
predicate and no `denies` predicate, so I improvised one by negating the wrong primitive.
Silence, grant and denial are THREE states, not two.

**Fix:** `extraction_service._line_entry_denies_coverage` - the twin of
`_line_entry_grants_coverage` and explicitly NOT its negation:

```
grants  -> premium or limit present     = positive proof of coverage
denies  -> a detail literally says NO   = positive proof of absence
neither -> the document is SILENT
```

Pinned by `test_grants_and_denies_are_twins_not_negations`, which asserts all three states
on the same three entries, and by `test_a_CERTIFICATE_row_is_not_a_denial` using the live
COI shape.

#### The pattern across all four of my C1 bugs

| # | Bug | The error underneath |
|---|---|---|
| B12 | `E 9 Mile Rd` != `East 9 Mile Rd` | ordering assumption not checked against a real address shape |
| B14 | umbrella conflict scoped into silence | fixture gave `$1,000,000` no owner; the live dec page gives it one |
| B15 | LOB denial matched a document against itself | "cross-document" not enforced across documents |
| B16 | a COI row read as a denial | **absence of evidence treated as evidence** |

B14, B15 and B16 are one family: **I tested against a shape simpler than the live
document.** Every one was caught by the owner running the real package, not by the suite.
That is what D22 and the CHANGE QUALITY BAR are for, and it is why the live fixture now
lives in the repo.

Tests: +2 (160 in the C1 file). **Full suite: 3604 passed / 2 failed / 2 skipped** - the two pre-existing unrelated
failures. Zero regressions.

#### Remaining on the pre-form screen, both correct

* **Umbrella $3,000,000 vs $1,000,000** - the real conflict. It must stay.
* **"no covered-auto symbol found for collision"** - the fixture writes `Symbol 07` in a
  table cell and extraction did not bind it to collision. A FIXTURE limitation, not a C1
  defect; the auto-symbol machinery is the 2026-08-07 work and is out of section 1's scope.

---

### C1-J THIRD LIVE RUN - the sixth comparison site closed; 1 more bug of mine (2026-08-21)
**Priority:** V1-CRITICAL

#### My own L2 fix had the same shape as the bug it fixed

The LOB warning was STILL firing on the third run. Cause: my denial rule unioned every
document's denials and every document's active lines, so it matched a document
**against itself**. A dec page routinely BOTH prints `COMMERCIAL PROPERTY - NO COVERAGE`
and lists Commercial Property in the coverage table its own extraction reads - the exact
shape of the fixture. Verified directly: `_lines_declared_absent()` on the dec page returns
`{has_property_coverage, has_crime}`, and the same document's `lines_of_business` carries
Commercial Property.

**Fix:** the denial and the active listing must come from **different documents**. A
document contradicting itself is an extraction artefact `apply_declared_absent_downgrades`
already settles - not two sources disagreeing.

This is the third bug introduced by a C1 fix (after the `E 9 Mile Rd` split and the
umbrella-scope silencing). All three shared a signature: **the fixture was easier than the
live document.** That is why the quality bar and D22 exist.

#### C1c - `submission_integrity.py` was the SIXTH comparison site

It produced three false review notes on a clean package and downgraded the verdict to
"Warning - review recommended":

| Note | Why it was wrong |
|---|---|
| "Location address differs across documents" | `Denver, Colorado` is a COMPONENT of the full street address |
| "Multiple distinct policy numbers found" | a 4-policy package has four policy numbers. That is what a package IS |
| "Operations descriptions differ across documents" | two documents describing the same operations in different words. Prose is INCOMPARABLE |

**Root cause:** `_soft_divergence_reasons` counted **distinct normalised strings**. It never
asked whether the values were different FACTS. It slipped past
`test_comparison_has_one_owner` because it never imported the comparators - it had its own
private logic, which is the definition of the problem.

**Fix:** every field now goes through `fact_comparison`, which brings address containment,
prose-incomparability, document-role scope and multi-contract awareness in one move. Plus:
a package the verified dec index shows as multi-contract is EXPECTED to carry several
policy numbers, so that is no longer a divergence signal at all.

Live fixture: verdict `Warning` -> **`high`**, `reasons: []`.

#### The two-comparator split, hit for the SECOND time - now a standing decision (D25)

The suite caught this immediately: `test_carrier_alias_does_not_flag_soft_divergence`
started failing. **The test was right and my code was wrong.**

Submission integrity asks *"do these documents belong to the same SUBMISSION?"* - a
CLUSTERING question. EMC Property & Casualty and Employers Mutual Casualty are one carrier
group, and a package where one writes the GL and the other the Auto is the Orbin ground
truth. The CONFLICT picker asks a different question about the same two names and must keep
answering "different entities" (Round 10 fix 46).

So carrier uses `carriers_same_family` here, and `conflict()` there. Same split as
`loss_run_identity`. Verified both directions: EMC group -> `high`, no reason; Travelers vs
Hartford -> `medium`, "Multiple carriers referenced".

#### Edge cases executed

Real address divergence, real entity-type divergence and real carrier divergence all still
fire. Two REAL insureds still BLOCK (`status: low`, `review_required: true`) - that path is
name/FEIN clustering and was not touched. Single doc, no docs, and a missing comparator
(fail-open to the legacy count) all safe.

Tests: +9 in `test_v1_c1_canonical_facts.py` (158). **Full suite: 3602 passed / 2 failed / 2 skipped** - the two pre-existing unrelated
failures. Zero regressions.

#### Blast radius - tell Brent

**More submissions will read "high / no review needed" instead of "Warning - review
recommended".** On a normal multi-document, multi-policy package all three notes were false.
The blocking path (two genuinely different insureds) is unchanged.

---

### X1 Extraction architecture - the document text step - SHIPPED (2026-08-22)
**Priority:** V1-HIGH (precondition for every finding; the C1 test package exposed it)
**Full record: `extraction_arch_change.md` at the repo root - measurements, design, rejected
alternatives, the six bugs caught during the change, and the verification table. Read it
before touching `ocr_service.py`, `utils/page_layout.py` or anything that consumes the
extracted text.**

One paragraph for the next session: the text handed to LLM call 1 was a flat string built by
sorting characters left to right, so two runs overlapping in x were riffled together
(`pa$rt4y,850` on the client's loss run), and table extraction had never once fired on an
insurance document (pdfplumber's default needs ruled lines). Now: riffled lines are repaired
in place (scoped - global `use_text_flow` was measured to BREAK ACORD 125/127 and the
two-column reflow fixture); every page's whitespace-aligned schedules are emitted inline as
`[Table - page N - SECTION]` blocks (native pages AND scanned pages via Vision word boxes AND
pasted-in images); multi-page documents carry `[Document page N]` markers. Every page without
a riffle is byte-identical to before (38/38 pages pinned). Suite: 3664 passed / 2 known
failures before and after; +22 new tests in `tests/test_page_layout.py`.

**Also in that file: the review of `EXTRACTION_BRIEF.md`.** Three of its seven root causes
came from comparing a live session that ran on OLD generated PDFs against the regenerated
ones (memory `stale-test-fixture-trap`). Its "delete the column repair" and "global text
flow" recommendations were measured and rejected; its header-anchored table design and its
findings list (Part 1) were right and are used. The five findings RULES it asks for (#2 GL
loss run on the auto policy, #3/#4 certificate omissions, #5 auto limit absent on the dec,
#6 symbol 7 without a schedule, #8 property declined vs described premises) have zero
matching code today and are the obvious next V1 item - the data already reaches facts.

---

### C1-I SECOND LIVE RUN - gate PASSES; 2 remaining false conflicts fixed at root (2026-08-21)
**Priority:** V1-CRITICAL

#### The gate now passes on real documents

```
Umbrella / Excess Limit    Values differ - confirm
the documents state different amounts
  $3,000,000  from 1_dec_page.pdf
  $1,000,000  from 2_certificate.pdf
```

Also confirmed live under "Resolved formatting difference - treated as equivalent":
the address trio, the applicant-name trio INCLUDING the `Orbin Contract` truncation, and
both policy dates. Data Consistency went 3 rows -> 2. The C1-H fix held.

#### Two false conflicts remained. Both had ONE cause each, and both are the client's own words.

**L1/L3 - a document has a ROLE (client 1.2: "carrier role", "insured/producer role").**
The picker asked the producer to choose between the certificate's GL policy number and the
LOSS RUN's Auto policy number, and between the dec's carrier and the loss run's carrier.
Neither is a competing statement:

| Loss-run fact | What it actually means |
|---|---|
| `policy_number` | the policy the CLAIMS sat under - already consumed by `loss_run_identity` |
| `carrier_name` | who ISSUED the loss run (a reporting role) |
| `effective_date` / `expiration_date` | the loss run's "period covered" - a 5-year window, not a 1-year policy term |

That last row was a landmine that had not fired yet: a 5-year loss window compared against a
policy term is a guaranteed false date conflict the moment extraction picks it up.

**Fix:** `fact_comparison.document_witnesses(doc_type, fact_key)` - one table, consulted by
BOTH cross-document comparators. **Fail-open by construction:** an unlisted doc_type
witnesses everything, so an unknown or future document type behaves exactly as today, and
the rule can only ever REMOVE a comparison - it cannot manufacture a conflict.

**L2 - silence is not denial (Principle 3), applied to lines of business.**
The old rule called two lists disagreeing when "each carries a line the other lacks". On the
live package the application named **Professional Liability** - a real policy with a
different carrier, which a package dec has no reason to list - and the whole submission was
called inconsistent and capped at 85.

Client 1.7 acceptance says a conflict needs sources that *"materially disagree about whether
coverage exists"*. **Two positive lists can never establish that.** A COI certifies selected
coverages; a narrative names relevant lines; an application may name a line placed elsewhere.

**Fix:** a LOB conflict now requires POSITIVE EVIDENCE ON BOTH SIDES - one document DENIES a
line on its own `coverage_lines` ("PROPERTY - NO COVERAGE") while another lists that same
line as active. No denial anywhere -> the difference renders as `[info]`, which is exactly
what the acceptance criteria ask for.

#### Result on the live fixture

```
check_doc_consistency  : CLEAN (was: LOB warning capping SQS at 85)
Data Consistency       : 1 row - the umbrella conflict. Correct.
```

#### Edge cases executed, both directions

Role table: loss run blind to policy/carrier/dates, still witnesses name / FEIN / address;
every other role including unknown and `None` witnesses everything. LOB: a denied line
listed active elsewhere STILL conflicts; a denial nobody contradicts does not; a certificate
listing fewer lines does not; an extra line does not. Two REAL dec pages with different
policy numbers still conflict. Loss run alone does not crash.

Tests: +15 in `test_v1_c1_canonical_facts.py` (149). **Full suite: 3593 passed / 2 failed / 2 skipped** - the two pre-existing unrelated
failures. One superseded test (`test_lines_of_business_genuinely_different_warns`) was
REWRITTEN, not deleted: it encoded the pre-1.7 rule that two disjoint lists warn. Its
replacement asserts the ruled behaviour, and a companion test keeps the REAL contradiction
(denied-vs-active) covered.

#### Blast radius - tell Brent

**Scores go UP again:** the LOB warning was capping any package whose documents list
different coverage sets at 85. That was most multi-document packages.

#### Still open from the live run, NOT C1

`submission_integrity.py` reports "Multiple distinct policy numbers found", "Location
address differs across documents" and "Operations descriptions differ across documents" on
this package. That is a DIFFERENT module with its own comparison logic - it does not use the
one door. It is the sixth comparison site, and it should be routed through
`fact_comparison` the same way the other five were. **Logged as the next C1 task.**

---

### C1-H FIRST LIVE RUN - the gate FAILED, root cause found and fixed (2026-08-21)
**Priority:** V1-CRITICAL
**Trigger:** the owner uploaded the four-document fixture. Nine checks behaved. **Check 5,
the gate, did not.**

#### What the screen showed

```
Umbrella / Excess Limit
2 policies, 2 values - not a conflict
  $3,000,000   umbrella      1_dec_page.pdf
  $1,000,000   general liab  2_certificate.pdf
```

The $3,000,000-vs-$1,000,000 umbrella conflict - **the one conflict the client praised** -
was scoped into silence and labelled "not a conflict". This is worse than the original bug
and no unit test caught it.

#### Root cause - an accidental identity, and a rule I had backwards

`PackageContext.value_owner` keys ownership on **the value's own characters**. The dec page
prints `$1,000,000` as the **GL Each Occurrence** limit, so `owners_of("$1,000,000")` returns
the **GL policy**. The certificate's UMBRELLA `$1,000,000` is a different fact that happens
to be the same number - and it inherited the GL policy's ownership. Two disjoint owners ->
"different policies" -> merged/scoped -> no conflict. Reproduced in three lines.

**Why no test caught it:** every gate fixture I wrote gave `$1,000,000` NO owner. The live
dec page gives it one. The test was easier than reality.

**Two independent paths were silencing it**, and fixing one was not enough:
1. `underwriting_consistency._scope_values` (C1-C, mine)
2. `fact_equivalence.equivalent_index`'s `different_owners` merge (2026-08-17, older)

#### The fix - two rules, both structural

* **A fact pinned to ONE coverage line can never be scoped across policies.**
  `umbrella_limit` IS the umbrella's limit; it cannot have one value per policy, so two
  values are a real disagreement. **C1-C had this exactly backwards** - it treated "the
  registry can place this fact on a line" as a reason to ALLOW scoping. It is the reason to
  FORBID it. `_line_scoped_by_registry()` is replaced by `_facts_pinned_to_one_line()`.
* **Money never scopes, and never splits by owner.** Amounts collide by value; identifiers,
  carrier names and dates do not. `policy_premium` / `total_policy_premium` removed from
  `LINE_SCOPED_FACT_KEYS`; `fact_equivalence._owner_split_allowed()` refuses
  `different_owners` for single-line facts and for every money fact.

What still scopes: `policy_number`, `carrier_name`, `carrier_naic`, `effective_date`,
`expiration_date` - all identifiers, names or dates.

Tests: +4 in `test_v1_c1_canonical_facts.py`, the first of which rebuilds the LIVE index
(with `$1,000,000` owned by the GL policy) instead of the convenient one.

#### Also seen on the same run - NOT yet fixed, ranked

| # | Symptom | Assessment |
|---|---|---|
| L1 | **Carrier picker offers the loss run's carrier** (`EMC Property & Casualty` vs `EMC Insurance Companies`) | REAL. Client 1.2 lists **carrier role** as a scope dimension: a loss run's carrier is the REPORTING carrier, not a competing policy carrier. It should not enter the package carrier reconciliation at all |
| L2 | **LOB "differ" warning** because doc 3 names Professional Liability, which the dec does not carry | REAL. Client 1.7: a source naming an EXTRA line is more information, not a contradiction. The subset rule should compare only lines BOTH sources reference. (The specialty split itself worked - PL is correctly its own family) |
| L3 | **Policy Number conflict** `BBC7263-26` (cert, GL) vs `6E7 40 02 26` (loss run, Auto) | REAL, same cause as L1: the loss run's policy number has no line attribution, so scope cannot fire |
| L4 | **"Contractor Type" conflict** - `Licensed electrical and roofing contractor` vs `Contracting` | REAL but lower: differing LEVELS OF DETAIL (client 1.2). Token containment misses it because "contracting" is not a token of "...contractor" |
| L5 | **Submission Integrity: "Multiple distinct policy numbers found"** | Separate module (`submission_integrity.py`), untouched by C1. False positive on any multi-policy package |

**What PASSED on the live run:** the address trio, the applicant-name trio (including the
truncation), entity type and both policy dates all appear under **"Resolved formatting
difference - treated as equivalent"**. That is checks 1 and 4, on real documents.

---

### C1-G Live test package + the scope decision (2026-08-21)
**Priority:** V1-CRITICAL

#### The live test fixture

`backend/scripts/make_v1_c1_test_pdfs.py` generates four text-extractable PDFs into
`test_data_v1_c1/`, with `README-HOW-TO-TEST.md` next to them (10 numbered checks +
an optional questionnaire round trip). Regenerate any time; nothing is committed
binary.

Deliberately **FOUR** policies, not the client's three - the owner's point is that a
package carries any number, so the fixture proves the scope logic is not quietly tuned
to the reported case.

Every reported defect plus the two conflicts that must SURVIVE:

| Doc | Carries |
|---|---|
| `1_dec_page.pdf` | 4 policies, 2 carrier entities, ZIP+4 address, umbrella $3,000,000, 2 lines marked NO COVERAGE |
| `2_certificate.pdf` | Same address spelled out, comma'd name, FEWER lines, different terminology, umbrella **$1,000,000** |
| `3_application.pdf` | `Denver, Colorado` only, TRUNCATED insured name, a Professional Liability policy with a different carrier |
| `4_loss_run.pdf` | FEIN with no dashes, policy number spaced, carrier under an alias |

**Check 5 is the gate:** the $3M-vs-$1M umbrella conflict must still be raised. If it is
missing, the fix went too far and that is worse than the original bug.

#### The scope decision (D19) - owner overruled my deferral, correctly

I recommended deferring "store scope on the fact" until after C2-C5 because changing
`merged_facts` from `{key: envelope}` to `{key: [scoped envelopes]}` touches **776 fact
reads across 27 files**. The owner's answer: store it anyway, generically, for every
material fact.

**They are right, and my framing of the cost was wrong.** The expensive version is the one
that CHANGES the existing shape. An ADDITIVE one does not:

```
merged_facts[key]            -> unchanged. All 776 readers keep working.
merged_facts["_scoped"][key] -> [{scope, value, sources, evidence_state}, ...]
```

Scope is written ONCE, at merge time, from the evidence that already exists
(`dec_page_entries` + `coverage_lines`). Consumers that care read the scoped store; the
rest never notice. That removes the two-mechanism drift risk
(`_scope_values` vs `pdf_service._resolve_section_policy_identity`) without a big-bang
rewrite, and it is what client 1.1 actually asks for - scope BEFORE comparison, carried
on the fact.

**To be done as its own change, with a cross-check test as step one:** pick a fact, ask
both mechanisms which policy it belongs to, assert the same answer. That converts a silent
drift risk into a loud one and is worth landing even before the store exists.

**Correction to an earlier note in this file:** nothing was ever hardcoded to three
policies - `_scope_values` loops over N and the fixture now proves it at four. The defect
was re-deriving scope, not a hardcoded count.

---

### C1-F Brent answered Q2 and Q4 - IMPLEMENTED, + 1 more bug of mine (2026-08-21)
**Priority:** V1-CRITICAL

#### Brent's answers, and what changed

| Q | Brent's answer | Implementation |
|---|---|---|
| **Q2** | *"implement this behaviour properly: holds both and asks the agent to pick"* | **CONFIRMED - already built** (F7 + C1-D). No behaviour change; the kill switch stays but the default is now the ruled behaviour |
| **Q4** | *"we should patch the suggested value"* | `CONFLICT_WITHHOLD_KEYS` is now **empty**. A cross-document conflict stamps the merge's suggestion instead of an owned blank. The conflict is still detected, still shown in Data Consistency with both values and sources, still routed, still confirmable |

**Q4 reverses part of a 2026-08-15 client note** ("unresolved conflicts must remain
unresolved ... rather than choosing whichever value seems most likely"), which is what put
`umbrella_limit` in that set over the $3M-vs-$1M case. Brent has now answered the narrower
question directly, and the owner's point stands: the conflict is *already* asked in Data
Consistency, so an empty box adds no information and costs a sendable form. Client rule 1.4
is still satisfied - it requires the conflict to *remain visible and route to the producer*,
which it does. **Reverting is one line: put the key back.**

**Scoped deliberately:** `extraction_service._flag_intra_document_limit_conflicts` writes
the same `_uw_conflicted_keys` for a conflict INSIDE one document. Brent was asked about
two documents disagreeing; Principle 7 forbids extending a ruling past the question, so
that path still blanks. Pinned by `test_an_INTRA_document_conflict_still_blanks`.

#### BUG B13 (mine, C1-D) - releasing a held answer released nothing

`upd_processing_session`'s facts merge is **additive**: a key simply absent from
`updates["facts"]` is PRESERVED. So `facts.pop("_client_answer_conflicts")` cleared nothing
in the database - the hold would have reappeared on the next read. The codebase already had
the escape hatch (`delete_facts`, added for exactly this in `clear_producer_answer_from_session`)
and I did not use it. Both call sites now retract explicitly.

Found by checking whether the session key I write to even exists - it does (the session is
a JSONB blob, so no column was needed), but the check surfaced this instead.

Tests: +9 in `test_v1_c1d_client_answer_review.py` (31 total). **Full suite: 3569 passed / 2 failed / 2 skipped** - back to the two pre-existing
unrelated failures. Three tests were UPDATED, not deleted: one test double predated the
`delete_facts` kwarg, and two pinned the pre-Brent blanking behaviour (rewritten to assert
the ruled behaviour, with the withhold MECHANISM still covered for the intra-document path).

---

### C1-E Clause-by-clause audit + bug hunt - 2 BUGS FOUND, BOTH FIXED (2026-08-21)
**Priority:** V1-CRITICAL
**Method:** every acceptance criterion and every enumerated item in the client's section 1
EXECUTED against the shipped code. Then ~45 adversarial probes against my own C1-C/C1-D
work. Nothing below is read off a checklist.

#### BUG 1 (mine, C1-C) - a carrier ALIAS raised a false "does not match" note

Client 1.8 lists *"known carrier-name variations"*. The loss-run carrier check used
`values_agree("carrier_name", ...)`, which routes through the **strict entity key** -
right for CONFLICT detection, wrong for corroboration:

```
EMC Insurance Companies  vs  Employers Mutual Casualty
  alias map  : 'emc' == 'emc'                       -> one carrier group
  strict key : 'emc insurance company' != '...'     -> different entities
  -> "Carrier on the loss run does not match" on an ordinary EMC package
```

**Fix:** `fact_comparison.carriers_same_family()` - a corroboration comparator that DOES
consult the curated alias map plus token-subset truncation. Used only by the loss-run
check; the conflict path is untouched. Gate:
`test_GATE_the_family_check_never_leaks_into_conflict_detection` asserts both halves -
EMC P&C and Employers Mutual are one FAMILY and still a CONFLICT.

#### BUG 2 (mine, C1-C) - `E 9 Mile Rd` and `East 9 Mile Rd` became different addresses

The unit-join regex I added ran BEFORE the directional mapping:

```
E 9 Mile Rd    -> join fires (single letter + number) -> "e9 mile rd"
East 9 Mile Rd -> "east" is 4 letters, no join        -> "e 9 mile rd"    MISMATCH
```

A false address conflict - the exact defect class C1 exists to remove, introduced BY the
C1 fix. Real shape: grid/rural addresses ("E 9 Mile", "N 5 Highway", "S 40 Road").

**Fix (order is now load-bearing):** directionals collapse FIRST, then a glued unit marker
is split (`Apt4` -> `apt 4`, a pre-existing miss found in the same probe), then the join
runs with directional letters excluded - `E 9` is East 9th, a street, never unit E9.
Pinned by `TestAddressNormalizerOrdering` (15 cases, both directions).

#### Everything else probed - 0 further bugs

~45 probes, all passing: `carriers_same_family` over-merge (generic-token-only names,
Travelers/Hartford, empty); clique edge cases (chains must NOT merge, singles, empties);
`lob_canon` ordering collisions (Employers vs Employment vs Employee Benefits); short
policy stubs; `0` is `present` not `explicit_no`; loss-run self-verify and malformed
shapes; the F7 guard on lists/dicts/prose/formatting-only answers; malformed held-answer
maps; human-fact restore carrying ONLY human facts; partial owner overlap refusing to
scope; and the Orbin two-carrier shape scoping correctly.

#### Acceptance criteria - executed

* **1.6** all four PASS on the client's literal trio: no Data Consistency issue, no
  warning, no SQS deduction, no warning ceiling (`cap = None`).
* **1.7** all three PASS: different terminology -> no conflict; subset/detail -> no
  conflict; GL vs Workers Comp still conflicts; unknown terminology stays unmapped.
* **1.8** all eight normalizations PASS after BUG 1. `Orbin Contracting LLC` vs
  `Orbin Contracting Company` correctly stays `no_match` - a different entity TYPE is not
  a formatting variation, and merging them would undo `test_llc_vs_inc_is_a_different_entity`.

#### 1.2 - what is and is not scoped

| Dimension the client lists | State |
|---|---|
| line of business / coverage | **BUILT** - `LINE_SCOPED_FACT_KEYS` + registry-derived |
| policy period, effective/expiration | separate fact keys (`prior_*` vs current) - never compared |
| carrier role, insured/producer role | separate fact keys - never compared |
| account/entity | n/a - one submission is one insured |
| location, vehicle, property item | **NOT BUILT** - no per-item scope on a fact |

Rows 2 and 3 pass **by key separation, not by a scope mechanism**. Correct today; a future
fact that mixes roles under one key would not be protected.

#### 1.3 - grep-confirmed: two of six states have ZERO writers

`not_applicable` and `unable_to_determine` are defined and derivable but nothing ever sets
them. Their writers are the evidence gate and section suppression - both on the form-fill
path (C4).

#### 1.5 - verified sub-rule by sub-rule

Merge retains ALL sources (3 documents -> 3 filenames). A conflict retains each value,
each source, its scope and a reason. **"Do not silently choose a winner" remains PARTIAL:**
`CONFLICT_WITHHOLD_KEYS` holds one key, so every other conflicting field stamps a best
guess while showing the conflict. That is Q4.

Tests: +22 in `test_v1_c1_canonical_facts.py` (125 total). **Full suite: 3562 passed / 2 failed / 2 skipped** - the same two pre-existing unrelated
failures as every entry above. Zero regressions.

---

### C1-D Held client answers had nowhere to go - ROUTING CORRECTED, UI SHIPPED (2026-08-21)
**Priority:** V1-CRITICAL
**Principles touched:** 1, 4, 5, 6, 7
**Trigger:** the owner asked, repeatedly, *"where do we even show the conflict?"* - and
the honest answer turned out to be **nowhere**. Tracing it found a design error in C1-C,
not a missing screen.

#### THE ERROR IN C1-C (this is the correction; do not route it back)

C1-C sent a held client answer to the **Data Consistency picker**. That door is CLOSED by
the time a client answers:

* The picker resolves through `confirm_underwriting_value` -> `_finalize_pipeline`, and
  that function sets **`"generated_forms": {}`** - it WIPES the producer's forms.
* `extraction_pipeline.py` says so itself: *"once forms have been generated the producer
  can no longer return to this screen."*
* `recalculate_session_scores` (the ARQ path) does **not** re-run
  `assess_underwriting_consistency` at all - verified by reading its import list. So the
  picker object was frozen at generation time and could never have shown the held answer
  even if the door had been open.

Sequence, which is the whole point:

```
1 upload -> 2 extract -> Data Consistency computed -> 3 producer reviews -> forms GENERATED
4 questions sent to client        <- forms already exist
5 client answers
6 apply_arq_answers_to_session    <- C1-C held the conflict HERE
7 recalculate_session_scores      <- rebuilds stops/SQS, NOT the picker
8 producer opens the editor       <- saw nothing
```

Net effect of C1-C alone: **a silent hold.** Strictly safer than the old silent overwrite
(no wrong value reached the PDF) but it did not satisfy *"route it to the producer"*, and
a hold nobody can see is not a feature.

#### The door that DOES work post-generation

`arq_service.apply_producer_answer_to_session` -> `_restamp_canonical_into_forms`: writes a
producer-provenance fact and patches the **existing** forms in place. No wipe, no
regeneration. That is what "Use the client's answer" now calls.

#### What shipped

| # | What | Where |
|---|------|-------|
| 1 | **`services/client_answer_review.py`** (new leaf): `build_review_rows` turns the held map into producer rows; `resolve_client_answer` applies `use_client` (stamp into existing forms) or `keep_source` (discard), releases the hold on BOTH copies, writes the audit row with both candidates, and recomputes stops/SQS | new module |
| 2 | **`POST /api/client-answer/resolve`** + `ClientAnswerResolveRequest`; `GET /api/session/{id}` now returns `client_answer_review` - that endpoint is what restores a session that already HAS generated forms, i.e. exactly the sessions that can have had a questionnaire | `routes/form_routes.py`, `models/schemas.py` |
| 3 | **"Needs your decision" section on the SQS left panel** of the generated-forms screen. Hidden when nothing is held. One card per held answer showing both values and two buttons | `AcordModal.jsx` |
| 4 | **Loss-run notes rendered** on the Loss History card (`loss_run_match_detail.notes` + `matched_on`). C1-C returned these in the payload and nothing displayed them - the producer saw "Loss runs do not match insured" with no reason | `AcordModal.jsx` |
| 5 | **Scoped rows rendered** in Data Consistency, read-only, each value labelled with its policy/line. C1-C computed `status: "scoped"` and the panel filtered it out, so three policies became invisible instead of visible-and-fine | `AcordModal.jsx` |
| 6 | **`conflict_reason` rendered** on conflict rows | `AcordModal.jsx` |
| 7 | **Q7 fixed.** `_finalize_pipeline` takes `prior_facts`; `fact_state.human_provenance_facts` extracts every producer/client value; on re-merge each one is restored when the documents are still silent or agree, and HELD (client rule 1.5) when the documents now disagree. All four session-bearing callers pass it, pinned by a test that counts them | `extraction_pipeline.py`, `fact_state.py` |

#### Why Q7 needed no product decision after all

C1-C logged Q7 as *"needs a precedence ruling: human value vs re-extracted value."* That
framing was wrong. A re-run reads **the same documents** - nothing new can appear to
contradict a human answer, so there is no winner to pick. Three outcomes, all already
covered by the client's own rules:

* documents still silent -> restore the human fact (Principle 6);
* documents agree -> restore it, keeping human provenance;
* documents disagree -> client rule 1.5, hold for the producer.

Nothing invented. **Q7 is closed as a question and fixed as a bug.**

#### Questions retired by this entry

* **Q1** (three rows or one) - not a product question. The client's 1.5 says *"retain each
  under its correct scope"*; retain means show. Three read-only rows, one per policy.
* **Q6** (bare "Liability") - the client already answered it in 1.7, which lists
  **Liability** in the General Liability family. Asking would be asking him to re-answer
  his own spec. Code was already correct.
* **Q7** - see above.

#### Verified

**Suite: 3539 passed / 2 failed / 2 skipped** - the same two pre-existing, unrelated
failures as every entry above (`test_arq_acord125_missing_only` = the known httpx/openai
version conflict; `test_normalization::test_insurance_terms_equivalent` = the BI/Building
synonym). Zero regressions; +24 tests on top of C1-C's 107.

`tests/test_v1_c1d_client_answer_review.py` (24). Includes
`test_the_picker_path_really_does_wipe_generated_forms` - if `_finalize_pipeline` ever
stops resetting `generated_forms`, that test fails and this decision gets re-examined
rather than silently assumed - and `test_resolution_uses_the_post_generation_stamper`,
which fails if anyone re-routes this through `confirm_underwriting_value`.
Frontend production build: **clean** (`vite build`, 2.20s).

#### Known / deliberately not done

* The section is driven by its own session key, NOT by `structured_issues` /
  `grouped_issues`. Squeezing it into the cluster machinery would have needed a new cluster,
  a new tier and a `replace_recomputed_issues` source - for a list that is a plain
  two-button decision. Revisit only if the producer wants it counted in the issue badges.
* `keep_source` discards the client's answer. It is recorded in the confirmation audit
  (with both candidates) but the ARQ answer row itself is unchanged - the client's original
  submission is still on the `arq_sessions` record.

---

### C1-C Data Consistency - IMPLEMENTED (2026-08-21)
**Priority:** V1-CRITICAL
**Principles touched:** 1, 2, 3, 4, 6, 7
**Plan executed:** F1-F11 from C1-B, in full. Two corrections to the plan were made
while building and are recorded below (they are the kind of thing the next chat would
otherwise "fix" back).

#### What shipped, by fix

| ID | What | Where |
|----|------|-------|
| F1 | **One comparison door.** `compare / conflict / values_agree / verdict / identifiers_match / feins_match / build_context`. Every site that decides "same fact?" calls it. An anti-rot test fails the build if any other module imports the pairwise comparators or does `_fv(..) == _fv(..)` | `services/fact_comparison.py` (new), `tests/test_comparison_has_one_owner.py` (new) |
| F2a | **Clique merge.** A connected component in which EVERY pair is SAME merges whole; a component with any unpartnered pair falls through to the old exactly-one rule untouched | `fact_equivalence.equivalent_index` |
| F2b | **Scope before compare.** Picker: pure value-equivalence first, then `_scope_values` (every group attributed to an owner, owners disjoint, no two owners on one coverage line) -> status `scoped`, values retained each with its `scope`, no conflict. Only THEN the package-context merge, and only if not scoped. `PackageContext` now records `contract_line`; `different_owners` no longer treats two contracts on the SAME line as different scopes | `underwriting_consistency.py`, `fact_equivalence.PackageContext` |
| F3 | `check_doc_consistency` routes ALL eight fields through the door, hard stops included. `_still_differs` deleted | `sqs_service.py` |
| F4 | **Loss-run identity rebuilt** as `services/loss_run_identity.py`: name/FEIN/policy/address/carrier all through the door; policy matched against EVERY package policy number (doc scalars + `coverage_lines`), not the first one found. Returns an explainable verdict (`tier`, `matched_on`, `failed_on`, `notes`, `per_document`); `calculate_package_sqs` exposes it as `loss_run_match_detail`. The old function name delegates, same string contract | `services/loss_run_identity.py` (new), `sqs_service.py` |
| F5 | **Two state axes on the envelope.** `value_state` (client 1.3's six) and `evidence_state` (client 1.4's four) + `evidence_actor`, derived from signals already present and written additively at the end of every pipeline run. `display_state()` is the 125 doc's four-word projection. First consumer: booleans are excluded from cross-document comparison (B8) | `services/fact_state.py` (new), `extraction_pipeline.py`, `extraction_service.detect_source_conflicts`, `audit_service._flatten_fact` |
| F7 | **Client answer vs source.** `_client_answer_conflicts_with_source` guards the ARQ write: source present + not human-owned + door says DIFFERENT -> the answer is HELD on the session (`client_answer_conflicts`), not written, not stamped. Kill switch `ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING` (default on). **CORRECTED IN C1-D:** this entry originally said the held answer surfaces in the Data Consistency picker and is resolved by the confirm endpoint. That was WRONG - that path wipes `generated_forms` and the ARQ recalc never rebuilds the picker, so the hold was invisible. The picker plumbing survives for a PRE-generation hold; the post-generation door is C1-D | `arq_service.py`, `underwriting_consistency.py`, `extraction_pipeline.py`, `config/settings.py` |
| F8 | **LOB canon is a leaf module** with explicit allow-lists. Known specialty liability lines get their OWN family (`professional`, `epli`, `pollution`, `directors_officers`, `employee_benefits`, `liquor`); `Computer Coverage` -> inland marine; unknown -> None. All three `lambda _s: None` fallbacks deleted; `GL_GENERIC_TOKENS` has one home | `services/lob_canon.py` (new), `extraction_service._canon_line` (delegates), `pdf_service`, `sqs_service`, `fact_equivalence` |
| F9 | Location fragment fold compares FULL normalised addresses through `normalize_address`; city/state without a ZIP is recovered into its own boxes | `extraction_service._consolidate_property_locations` |
| F10 | Producer resolution persists `candidates` (every competing value + sources + scope) and `reason`. Columns added on both DDL paths | `models/schemas.py`, `config/database.py`, `audit_service.log_underwriting_confirmation`, `extraction_pipeline.confirm_underwriting_value`, `routes/form_routes.py` |
| F11 | Derived writers label themselves: dec-entry backfill -> `source_verified` + `verified_in_text`; premium arithmetic -> `evidence_state: derived`; renewal routing already wrote `source: derived` | `extraction_service.py` |
| - | `normalize_address` joins a split unit designator (`D-13` / `D 13` -> `d13`), applied symmetrically | `normalization.py` |

#### Two corrections made while building (read before "fixing" them back)

1. **The door's cheap first pass must group entity names on the STRICT key, not the
   coarse normaliser.** First cut grouped on `normalize_value`, which for carriers is
   `normalize_carrier` - and that folds `EMC Property & Casualty` into `Employers Mutual
   Casualty` (both -> `emc`). Two real carriers were pronounced consistent before the typed
   comparator ever saw them: Round 10 fix 46, reintroduced one layer up. Caught by my own
   smoke test, not by the suite. Pinned by
   `TestTheDoor::test_entity_names_group_on_the_strict_key_not_the_coarse_one`.
2. **Scope must be decided BEFORE the package-context merge, not after.** The existing
   `different_owners` rule merged two different-contract values into one group, so
   `_scope_values` saw one group and the "two GL policies in one period" case was silently
   merged into "consistent". Now: value-only merge -> scope -> context merge only if not
   scoped. Same fix made `different_owners` refuse two contracts on the same line.

#### Verified (executed, not reasoned)

Every reproduced case from C1-A/C1-B now behaves:

| Case | Before | After |
|---|---|---|
| Client's address trio, picker | 0 conflicts | 0 conflicts |
| Client's address trio, `check_doc_consistency` | warning, cap 85 | **clean** |
| Same trio with `D-13` hyphen | conflict | clean |
| Orbin's 3 policies | conflict | **scoped**, 0 conflicts |
| Orbin's 2 carriers (EMC P&C on GL, Employers Mutual on Auto) | merged OR conflict | **scoped, both retained** |
| Two GL policies, one period | silently merged | conflict, reason "two policies on the same coverage line" |
| `Orbin Contracting LLC` vs `Orbin Contract` | **hard stop (60)** | clean |
| Loss run FEIN `84-2210987` vs `842210987` | moderate | strong |
| Loss run policy `6E7-40-02---26` vs `6E7 40 02 26` | possible | strong |
| Loss run address `Denver, Colorado` | possible | moderate |
| 3-policy account, loss run = Auto policy | possible | strong |
| Loss run under the DBA | no_match, silent | no_match + producer note (Q3a open) |
| `has_subcontractors` True vs False | conflict, cap 85 | clean (booleans never compared) |
| Location trio on ACORD 125 | 2 premises rows | 1 row, city + state filled |
| `Professional Liability` | -> General Liability | -> `professional` |
| Client answer `25` over source `18` | overwritten + re-stamped | held (nothing stamped). **Visible to the producer only after C1-D** |

Gates held: `test_the_umbrella_conflict_survives_every_rule`,
`test_a_fragment_matching_two_hosts_is_not_merged`, `test_the_two_real_carriers_finally_conflict`,
`test_a_liquor_policy_fills_the_131_other_underlying_row`.

Tests: `tests/test_v1_c1_canonical_facts.py` (103), `tests/test_comparison_has_one_owner.py` (4).
**Suite result: 3515 passed / 2 failed / 2 skipped** - the two failures are the same
pre-existing, unrelated ones every entry in CLAUDE.md reports (`test_arq_acord125_missing_only`
= the known httpx/openai version conflict; `test_normalization::test_insurance_terms_equivalent`
= the `BI`/`Building` synonym). **Zero regressions, +107 tests.**

#### Blast radius (both directions - tell Brent BOTH)

* **Scores go UP** on packages that were capped by a formatting difference (address trio,
  truncated name, loss-run FEIN/policy punctuation, boolean silence).
* **Some packages gain a REAL conflict** they were missing: two GL policies in one period;
  a Professional/EPLI/Pollution/D&O line that was silently read as General Liability; an
  `LLC` vs `Inc` applicant the coarse normaliser used to fold.
* **Client questionnaire behaviour changes** (F7): an answer that contradicts the documents
  no longer moves the score instantly - it waits for the producer. Kill switch exists. Q2.
* The picker can emit `status: "scoped"`. **C1-C shipped this with no UI, so three policies
  became invisible rather than visible-and-fine. Rendered in C1-D.**

#### Known / deliberately not done

* **Scoring still reads `confidence`, not `evidence_state`.** `CONFIDENCE_SCORE` gives
  `ai_high` 0.85; under the new axis that value is `suggested`. Making SQS read evidence is
  a score change for Brent (C3 territory), not a C1 fix. The label is there; nothing
  consumes it for points yet.
* `unable_to_determine` is derived from `rejected_by` / `withheld` envelope markers that
  nothing writes yet; `not_applicable` from a `not_applicable` marker that nothing writes
  yet. The evidence gate and section suppression are the writers - wiring them is the next
  F5 step and belongs with C4 (questionnaire) because that is where the states are consumed.
* ~~`_client_answer_conflicts` survives a pipeline re-run, but ORDINARY client answers do
  not.~~ **FIXED in C1-D** (`prior_facts` + `human_provenance_facts`). Q7 closed.
* `detect_source_conflicts` still compares the three `_STRUCTURED_DICT_FIELDS` per sub-key
  on normalised text, not through the door. Low volume; left as is.
* Frontend: no change **in C1-C**. `conflict_reason`, `scope` and `loss_run_match_detail`
  were rendered in C1-D. `value_state` / `evidence_state` remain backend + audit-export only,
  which is what the client asked for in V1 ("primarily backend/audit behavior in V1").

#### HONEST SCORECARD AFTER THE FIX - section 1 is ~80%, not 100%

The percentages in C1-A below are the BEFORE state and are now stale. These are the AFTER
numbers. Anyone reading this file for "is C1 finished" should read THIS table, not that one.

| § | After | Done | NOT done |
|---|---|---|---|
| 1.1 Canonical Fact Flow | ~75% | The behaviour runs in the client's order and every consumer compares through one door | No canonical fact OBJECT. Scope lives on the picker ROW, not on the fact - so form stamping still resolves policy identity by its own separate mechanism (`_resolve_section_policy_identity`). **Two mechanisms, not one** |
| 1.2 Fact Scope | ~60% | Line-of-business scope for policy number / carrier / NAIC / dates on multi-policy packages - the set that was causing false conflicts | Scope is not STORED on the fact. Location / vehicle / property-item scope not built. (Mailing-vs-physical address and prior-vs-renewal dates were already separate fact keys, so they pass trivially rather than by design) |
| 1.3 Value States | ~65% | All six defined and written on every envelope. `present` / `explicit_no` / `not_stated` / `conflicting` genuinely get set. Booleans are `not_stated`, never `False` | **`not_applicable` and `unable_to_determine` have ZERO writers** (verified by grep). Only the comparison layer and the re-run guard consume states; forms / SQS / questionnaire do not read them |
| 1.4 Evidence States | ~85% | All four states, actor separately identifiable, in the E&O export. `suggested` never silently becomes `source_verified`. Client said "primarily backend/audit in V1" - met | Nothing CONSUMES it for scoring |
| 1.5 Selection Rules | ~90% (C1-D) | All 7 sub-rules have a working path: scope retention renders, client-answer routing reaches the producer post-generation, resolution history persists | **"Do not silently choose a winner" is half-done**: the merged fact still picks and stamps a winner for every key except `umbrella_limit`. Widening blanks more boxes - Q4 |
| 1.6 Address | ~95% | Every listed normalization, containment, clique merge, form-side location fold. All four acceptance criteria met | Nothing material |
| 1.7 Lines of Business | ~90% | All families, subset rule, No-Coverage, specialty split, Computer Coverage, unmapped stays unmapped | *"route it for producer review when material"* - an unmapped LOB raises no review item |
| 1.8 Loss-Run Identity | ~90% | All 8 normalizations, per-line policy scope, explainable verdict | DBA and FEIN-with-different-name tiers are Q3a / Q3b |

**The five reasons it is not 100%, ranked by who is blocking:**

1. **Four items are blocked on PRODUCT, not engineering** (Q1, Q2, Q3a/b, Q4). Principle 7
   forbids improvising an insurance rule; stopping was compliance, not incompleteness.
2. **One item is a deliberate deferral to C3.** Scoring reads `confidence`, not
   `evidence_state`. Switching it moves every historical score - Brent's call, not a bug fix.
3. **One item is scope discipline.** `not_applicable` / `unable_to_determine` writers live in
   the evidence gate and section-suppression code (form-fill path = C4). Wiring them here
   would have been scope creep into a different CRITICAL item.
4. **One item is a judged risk I declined to take in the same pass as bug fixes.** Making the
   fact carry its own scope means changing `merged_facts` from `{key: envelope}` to
   `{key: [scoped envelopes]}` - that touches essentially every consumer in the codebase. Two
   mechanisms for "which policy does this belong to" is the honest residue of that decision,
   and it is the single biggest remaining gap in 1.1/1.2.
5. ~~One item is a pre-existing defect I found and did NOT fix (Q7).~~ **FIXED in C1-D.**
   The "needs a precedence decision" framing was wrong: a re-run reads the SAME documents,
   so no rival value can appear. Restore when silent or agreeing; hold (rule 1.5) when the
   documents disagree. No product ruling was required.

**And one honesty note about the word "done":** 3,515 unit tests pass and every reproduced
defect was re-executed against the shipped code. **No live package has been run through this
yet.** "Done" here means done and offline-verified, not proven in production. The live test
plan (T1-T10) exists; until it has been run, treat C1-C as verified-not-validated.

---

### C1-B Self-review of the C1-A plan - FLAGS FOUND, PLAN CORRECTED (2026-08-21)
**Priority:** V1-CRITICAL
**Principles touched:** 1, 2, 3, 6, 7
**Method:** re-read C1-A as an adversary and executed the code again wherever a claim could
be wrong. Five flags against my own plan, one new defect, one new bug CLASS. Everything
below was reproduced, not reasoned.

#### FLAG 1 - F2 discovers scope inside the comparator. The client's flow puts scope BEFORE comparison.

Client 1.1: `Raw Extraction -> Normalization -> Scope/Association -> Reconciliation`.
F2 as written ("component held together by `different_owners` -> return as scoped facts")
works out scope at comparison time, from pairwise evidence. That is the wrong layer, and it
is wrong for a concrete reason: the scalar `policy_number` on a 3-policy package is
**unscoped by construction** - one dec page, three policies, one scalar slot. No comparator
can recover what was never stored. The scoped data already exists one key over, in
`coverage_lines` (per-line `policy_number`, `carrier`) and `dec_page_entries`
(per-entry `line_of_business`, `policy_number`). `_resolve_section_policy_identity`
(2026-08-15) already reads it for STAMPING. The conflict layer must read the same thing.

**Correction:** F2 splits into two.
* **F2a (comparator):** clique detection only. Three printings of ONE value, every pair
  `SAME`, merge. No scope logic in the comparator.
* **F2b (scope, the real fix):** on a multi-contract package, a line-scoped fact
  (`policy_number`, `carrier_name`, `carrier_naic`, `effective_date`, `expiration_date`,
  and every fact `fact_equivalence.fact_line()` can place) is compared **per line**, from
  `coverage_lines` / `dec_page_entries`, and the unscoped scalar is not compared at all.
  Package-level facts (`applicant_name`, `fein`, `mailing_address`) compare exactly as now.
  This is the client's 1.2 list, implemented as "compare within scope" rather than
  "explain away after comparing".

#### FLAG 2 - D2 merged two different axes into one. Corrected.

Client 1.3 lists SIX value states (Present / Explicit No / Not Stated / Not Applicable /
Unable to Determine / Conflicting). Client 1.4 lists FOUR evidence states (Source Verified /
User Confirmed / Derived / Suggested). The 125 doc's four (VERIFIED / CONFIRMED /
NOT APPLICABLE / UNRESOLVED) mix both: VERIFIED and CONFIRMED are *evidence*, NOT APPLICABLE
and UNRESOLVED are *value*. D2 adopted the 125 doc's four as THE value states - that would
leave no way to say "present but only suggested" or "explicitly no, confirmed by the
insured". **D2 is rewritten below.** The model is two axes; the 125 doc's four are the
display projection the producer sees.

#### FLAG 3 - "the picker is correct" was too generous. It is lucky.

C1-A said the picker handles the address trio and `check_doc_consistency` does not, because
the picker pre-groups by normalized string and so hands `equivalent_index` TWO values, not
three. True - but that means the picker only works when two of the three printings
normalize to the *identical* string. `4800 Dahlia St #D13` vs `4800 Dahlia St D-13`
(a hyphen inside the unit) would normalize differently, give three groups, and the picker
would fail exactly like `check_doc_consistency`. Pre-grouping is not the fix; F2a is.

#### FLAG 4 - `_canon_line` over-maps. Client 1.7 says the opposite.

Client: *"If terminology is not covered by a known normalization rule, do not automatically
assume equivalence."* `_LOB_CANON_GENERIC` maps the bare word `liability` to General
Liability whenever nothing specific matched. Reproduced:

```
Professional Liability            -> general_liab   WRONG (E&O, its own line)
Employment Practices Liability    -> general_liab   WRONG (EPLI)
Pollution Liability               -> general_liab   WRONG
Directors and Officers Liability  -> general_liab   WRONG
Employee Benefits Liability       -> general_liab   arguable (usually a GL endorsement)
Liquor Liability / Products Liab. -> general_liab   acceptable (GL parts)
```

This is the mirror image of the client's complaint: instead of calling equal things
different, it calls different things equal - and then a COI listing "Professional
Liability" agrees with a GL dec page it has nothing to do with, or a GL carrier gets a
D&O carrier as a "conflict". The 2026-08-15 log shows the bare-`liability` rule was
already bitten once (`test_auto_beats_bare_liability_in_line_canonicalisation`). Specific
exclusions are patches; the generic fallback itself is the defect.

**Added to F8:** bare `liability` maps to GL only when the phrase is one of an explicit
allow-list (`liability`, `general liability`, `commercial general liability`, `cgl`,
`premises liability`, `premises operations`, `products completed operations`,
`liquor liability`). Any other `* liability` phrase returns `None` = unmapped = no
equivalence assumed, exactly as the client asks. New named families only on product
approval (Principle 7).

#### FLAG 5 - F4's DBA rule and FEIN-alone were product decisions dressed as engineering.

The client's 1.8 tiers are `name + FEIN/policy`, `name + address`, `name only`, `no match`.
A loss run under the DBA with a matching FEIN is not in that list; neither is a matching
FEIN with a changed legal name. I wrote "accept the DBA" as a fix. It is a rule the client
has not written. Under Principle 7 the engineering default is: DBA match with FEIN ->
surface to the producer as *"loss run appears to be filed under the trade name - confirm
ownership"* with **no scoring effect until Brent rules** (Q3 stays open, now Q3a/Q3b).

#### NEW DEFECT B7 - a FIFTH comparison site, with a FIFTH opinion, in location consolidation.

`_consolidate_property_locations` (`extraction_service.py:5341`) folds a geo-only fragment
into a street group using its **own regex** (`_geo_only_re`: requires a 2-letter state AND a
ZIP). `Denver, Colorado` has neither, so the client's literal third string does not fold.
Reproduced: the trio consolidates to **2 location rows** (street group + an orphan
`Denver, Colorado` row) - that is an extra premises row on ACORD 125 from a formatting
difference. It never calls `normalize_address`, which would have reduced it to `denver co`
and matched. Same root cause (A): a consumer re-deriving meaning locally.

#### NEW DEFECT B8 - boolean facts cannot say "not found", so a conflict is manufactured from silence.

Reproduced: `has_subcontractors: True` in one document and `False` in another ->
`detect_source_conflicts` emits a conflict -> `soft_stops` -> 85 cap. The extraction prompt
asks the model to set flags true/false; nothing distinguishes *"the document says no
subcontractors"* from *"this document is a COI and never mentions subcontractors"*. That
`False` is Principle 3's forbidden case made into a fact, and then scored. This is the
sharpest concrete instance of root cause (C) and the first thing F5 must fix: a boolean
with no evidence is `NOT_STATED`, not `False`, and `NOT_STATED` never enters a comparison.

#### NEW BUG CLASS - "exactly one" guards break at n >= 3 equivalents.

B1 is not unique. The codebase uses the pattern *"act only when exactly ONE candidate
matches"* as its standard anti-guessing device, and it is the right instinct - but every
instance is blind to the case where several candidates are the same thing printed several
ways. Found by grep, all in the comparison/consolidation paths:

| Site | Guard | Breaks when |
|---|---|---|
| `fact_equivalence.equivalent_index` | exactly one partner | 3 printings of one value (B1) |
| `_consolidate_property_locations` fragment rule | contained in exactly ONE street group | 2 printings of one street + a fragment |
| `PackageContext.same_contract_printing` | exactly ONE canonical key may claim a printing | the same contract indexed under two printings |
| `_merge_list_fields` composite tiebreak (C23 round 2) | exactly one tied candidate appears in the composite | - already fixed by grouping by AMOUNT; the precedent |

C23 round 2 (2026-07-30) hit exactly this on currency (`'$ 1,000,000'` and `'$1,000,000'`
counted as two candidates) and fixed it by **grouping equivalents before counting**. That
is the general rule and it becomes a standing decision (D7): *every "exactly one" guard
counts equivalence CLASSES, never raw candidates.* An anti-rot test enumerates these guards
and feeds each three printings of one value.

#### FUTURE-PROOFING - what stops a sixth comparison site next month

Fixing five sites is still per-site. The structural guard, added to F1:
* `services/fact_comparison.py` is the ONLY module allowed to import `same_fact`,
  `equivalent_index`, `values_conflict`, `distinct_normalized`, `entity_identity_conflict`.
* `tests/test_comparison_has_one_owner.py` greps `services/` and `routes/` and FAILS if any
  other module imports them, or performs `==` between two `_fv(...)` reads of the same key
  across documents. Same device as `test_no_check_reads_a_fact_nothing_writes` (2026-08-07).
* Every new material fact must declare its scope level (`package` | `line` | `location` |
  `vehicle` | `driver`) in `FACT_REGISTRY`, and a test fails when one is missing - the
  2026-08-08 `test_every_reconcilable_field_has_a_resolved_scan_shape` pattern.

#### Corrected fix plan (supersedes the C1-A table)

| ID | Fix | Covers | Priority |
|----|-----|--------|----------|
| F1 | One comparator module + the import-ownership test above | 1.1; kills the "Nth site" class | CRITICAL |
| F2a | Clique merge in `equivalent_index` (all pairs `SAME`) - no scope logic here | 1.6 literal case, B1 | CRITICAL |
| F2b | Scope BEFORE compare: line-scoped facts compared per line from `coverage_lines`/`dec_page_entries`; unscoped scalar not compared on a multi-contract package; `FACT_REGISTRY` declares scope level | 1.2 entire list, 1.5 "different valid scope", 3-policy case | CRITICAL |
| F3 | `check_doc_consistency` routes all 8 fields through F1, hard stops included | B3, 1.6 acceptance criteria | CRITICAL |
| F4 | Loss-run identity through F1: normalize FEIN + policy, address containment, scope `main_pol` to the loss run's own line. DBA -> producer review, no score change, pending Q3 | 1.8 (4 of 5 rows); row 4 pending product | CRITICAL |
| F5 | Two-axis state on the envelope: `value_state` (client's six) x `evidence_state` (client's four). First consumer: booleans - no evidence = `NOT_STATED`, never `False`, never compared | 1.3, 1.4, B8, Principle 3 | HIGH |
| F6 | (folded into F5) | | |
| F7 | Client-answer guard: source value exists and `DIFFERENT` -> candidate + producer conflict, not overwrite | 1.5, B4 | HIGH |
| F8 | `_canon_line` to a leaf module; bare-`liability` allow-list; `Computer Coverage`; kill the `lambda: None` fallbacks | 1.7 both directions, B6, FLAG 4 | HIGH (was MEDIUM - FLAG 4 raised it) |
| F9 | `_consolidate_property_locations` fragment rule calls `normalize_address`, not its own regex | B7, 1.6 on the FORM not just the picker | HIGH |
| F10 | Producer resolution persists all competing values + sources + scope + reason, not just `previous_value` (`underwriting_confirmation_audit` today stores one prior value) | 1.5 "Producer Resolution", feeds C5 | MEDIUM |
| F11 | Derived facts (`_reconcile_total_premium`, `_route_renewal_dates`, `_backfill_empty_facts_from_entries`) write `evidence_state: derived`, not `deterministic` | 1.4 "Derived" | MEDIUM |

#### What the review did NOT change

Root cause (A)/(B)/(C) stands. The "already correct" list stands, with one demotion:
`_canon_line` is correct on the client's listed families and WRONG on the generic fallback.
The blast-radius statement stands, and F8 adds a second direction: some packages will gain
a real conflict (a Professional Liability carrier will stop silently agreeing with the GL
carrier). Tell Brent both directions.

---

### C1-A Data Consistency - full code audit, root cause found - ANALYSIS COMPLETE, NOT YET FIXED (2026-08-20)
**Priority:** V1-CRITICAL
**Principles touched:** 1, 2, 3, 4, 6
**Method:** read and EXECUTED the real code. Every claim below was reproduced by running
the shipped functions, not inferred from documentation. Baseline before any change:
`147 passed / 1 failed` across `test_fact_equivalence_20260817.py`,
`test_underwriting_consistency.py`, `test_normalization.py` - the 1 failure is the known
pre-existing `test_insurance_terms_equivalent` (`BI`/`Building`).

#### Where section 1 actually stands

> **STALE - this is the BEFORE state, kept as the baseline the fix was measured against.
> For the current position read "HONEST SCORECARD AFTER THE FIX" in entry C1-C above.**

| Client item | Built | Note |
|---|---|---|
| 1.1 Canonical fact flow | 45% | Stages exist as separate modules; the canonical fact OBJECT does not |
| 1.2 Fact scope | **DONE** | policy / line / role axes shipped C1-C..C1-J; the LOCATION / VEHICLE / ITEM axis shipped C1-P |
| 1.3 Value states | **DONE** | all six states carry a real writer at fact level (C1-P). The SQS PILLAR statuses of the same name are a different, unrelated concept |
| 1.4 Evidence states | 45% | `source` + `confidence` on the envelope; no `Suggested` state |
| 1.5 Canonical selection rules | 60% | 3 of 6 sub-rules done; see below |
| 1.6 Address normalization | 85% | Normalizer complete; the reported conflict still fires (bug B1) |
| 1.7 LOB normalization | 85% | `_canon_line` covers every family the client lists except `Computer Coverage` |
| 1.8 Loss-run identity | 35% | 5 of 5 realistic cases fail. Worst item in the section |

#### THE root cause

**Facts are stored as bare values, not as objects that carry their own meaning.**
`merged_facts` is a flat dict of `{value, confidence, source}`. There is no slot for state,
no slot for evidence class, no slot for scope. `services/normalization.py` says it outright
at line 22: *"Normalization is COMPARISON-ONLY. It never mutates stored facts."*

Three consequences, and every defect in section 1 is one of them:

* **(A) Normalizing is a decision each caller makes separately.** Four comparison sites
  exist. They do not agree.

  | Site | Equivalence filter wired? |
  |---|---|
  | `underwriting_consistency.assess_underwriting_consistency` (the picker) | yes |
  | `sqs_service.check_doc_consistency` | **3 of its 8 fields only** |
  | `extraction_service.detect_source_conflicts` | **no** |
  | `sqs_service._check_loss_run_insured_match` | **no** |

  The comment at `sqs_service.py:1427` claims the picker and `check_doc_consistency` "can
  never disagree". **Reproduced: they disagree.** On the client's literal address trio the
  picker returns `conflict_count 0` and `check_doc_consistency` emits
  `[warning] field=mailing_address`. The picker passes normalized GROUPS; `_still_differs`
  passes RAW values. Different input, different answer.

* **(B) The comparator can only answer "same" or "conflict".** `fact_equivalence.equivalent_index`
  returns a merge map or `None`. Client rules 1.2 and 1.5 require a THIRD
  answer - *different, correctly, under different scope*. That answer is unrepresentable, so
  three policies with three legitimate terms and three documents genuinely disagreeing are
  indistinguishable downstream.

* **(C) There is nowhere to record what we know about a fact.** No value state, no evidence
  state, no scope. Hence 1.3 at 5% and 1.4 at 45%.

#### Reproduced defects

**B1 - the "3 or more" ambiguity guard. ONE cause, TWO client-reported issues.**
`fact_equivalence.equivalent_index` refuses to merge any value that matches more than one
partner. That guard exists to stop `"Denver, Colorado"` merging two DIFFERENT streets, and
it is correct for that. It cannot tell that case apart from three printings of ONE fact.

```
address, client's literal 3 strings         -> None  => false conflict => SQS capped at 85
policy_number, Orbin's 3 real policies      -> None  => false conflict
   (BBC7263-26 GL / 6E7-40-02---26 Auto / 6J7-40-02---26 Umbrella, all correctly attributed
    in PackageContext: is_multi_contract=True, contracts=3)
same inputs but only TWO of each            -> merges correctly
```

The distinguishing signal already exists and nobody read it: in the genuine two-address
case `same_fact(host1, host2) == DIFFERENT`; in a false-conflict clique every pair is
`SAME`. And in the 3-policy case the pairs are `DIFFERENT` but joined by
`context.different_owners` - which is the scope answer (B) cannot express.

**B2 - loss-run identity compares 2 of its 4 fields raw.** `sqs_service.py:2959-2960`:
`doc_fein == main_fein` and `doc_pol == main_pol`, raw strings. `normalize_fein` exists in
this codebase and is not called. Name and address ARE normalized. Someone normalized half
the function. Reproduced, with the SQS cost from `match_credit`
(`strong 50 / moderate 42 / possible 35 / no_match 15`):

| Case | Returns | Should be | Cost |
|---|---|---|---|
| FEIN `84-2210987` vs `842210987` | `moderate` | `strong` | -8 |
| Policy `6E7-40-02---26` vs `6E7 40 02 26` | `possible` | `strong` | -15 |
| Loss-run address `Denver, Colorado` | `possible` | `moderate` | -7 |
| Loss run filed under the DBA | `no_match` | `strong` | **-35** + "loss runs do not match insured" |
| 3-policy account, loss run = Auto policy | `possible` | `strong` | -15 |

`main_fein` / `main_pol` / `main_addr` take the FIRST non-empty value from ANY non-loss-run
document - no scope at all. That is the last row.

**B3 - `applicant_name` is a HARD STOP (cap 60) with no equivalence filter.** Reproduced:
`Orbin Contracting LLC` vs `Orbin Contract` (truncation) and vs
`Orbin Contracting LLC dba Orbin Roofing` both hard-stop, while `same_fact` returns `SAME`
for both. `fein` is safe (`normalize_fein` is digits-only). Dates are safe on a
multi-contract package (`_dates_owned_separately`) and unsafe otherwise.

**B4 - a client questionnaire answer silently overwrites the source value.**
`arq_service.py:3418`: `facts[canon] = {...}` unconditionally, then re-stamps every form.
No comparison against the extracted value, no conflict raised. Client rule 1.5 says the
opposite: *"Do not automatically overwrite the source value. Create a conflict and route it
to the producer."*

**B5 - `detect_source_conflicts` has no equivalence filter at all.** Severity is LOWER than
it first looks and the honest number matters: with `ENABLE_FULL_FIELD_RECONCILIATION=True`
(hardcoded), `assessed_keys` covers every scalar fact, so this engine is skipped for
scalars in production. What still reaches it raw: the 3 `_STRUCTURED_DICT_FIELDS`
(`risk_transfer`, `wc_payroll_by_state`, `wc_monopolistic_payroll`) and boolean facts. Its
output goes to `soft_stops` -> `SOFT_STOP_CAP` 85.

**B6 - `_canon_line` lives in a 7,085-line module and is imported lazily by three others
with `except: lambda _s: None` fallbacks** (e.g. `sqs_service.py:1666`). A circular-import
blip silently disables LOB canonicalization with zero signal.

#### Verified as ALREADY CORRECT (do not rebuild these)

* `normalize_address` handles every abbreviation the client lists in 1.6 - St/Street, Ave,
  Rd, Blvd, Ste, Unit/#, case, punctuation, whitespace, ZIP+4 -> ZIP5, all 50 state names,
  compass directionals. The client's three literal strings all reduce correctly and
  `same_fact` returns `SAME` for all three pairs. **The normalizer is not the bug; B1 is.**
* `_canon_line` canonicalises every family in 1.7: `Liability` / `General Liability` /
  `Commercial General Liability` -> `general_liab`; `Automobile` / `Commercial Auto` /
  `Commercial Automobile Liability` -> `auto`; all four umbrella spellings -> `umbrella`;
  `Contractors Equipment` / `Installation Floater` -> `inland_marine`. Only
  `Computer Coverage` returns `None`.
* LOB subset rule (a COI naming fewer lines is not a disagreement) - done.
* Active vs listed coverage - done: `_line_entry_grants_coverage` demands a premium or
  limit and rejects a value that is itself a denial; `apply_declared_absent_downgrades`
  turns flags off on an explicit "NO COVERAGE".
* `PackageContext` - real, positive-evidence-only, built from verified `dec_page_entries`.
* Loss-history STATE machine already separates a narrative assertion from verified runs
  (`narrative_states_no_losses` -> `none_stated`), which is most of the client's 125-doc
  point 5. Residual for C2: `calculate_p4_loss_history:2009` ORs
  `narrative_states_no_losses` into `no_loss_attested`, so a narrative phrase earns the
  same tier as a signed attestation. Milder than the client feared, still wrong.
* ACORD 125 template is already the **2025/03** edition. No version work needed.

#### The fix plan

| ID | Fix | Covers | Priority |
|----|-----|--------|----------|
| F1 | One comparator, one entry point: `services/fact_comparison.py` exposing `resolve(fact_key, values, ctx)`. Every conflict site calls it. No site picks its own | 1.1, and the CLASS behind 1.6/1.7/1.8 | CRITICAL |
| F2 | Connected components in `equivalent_index`. All-`SAME` clique -> merge. Component held together only by `different_owners` -> return as SCOPED facts, not a conflict | 1.6 literal case, 1.2 3-policy case, 1.5 "different valid scope" | CRITICAL |
| F3 | `_still_differs` on all 8 fields incl. the hard stops, fed normalized groups not raw values | 1.6, 1.1, B3 | CRITICAL |
| F4 | Loss-run identity through F1: normalize FEIN + policy number, accept the DBA, address containment, scope `main_pol` to the loss run's own line | 1.8 entirely | CRITICAL |
| F5 | `value_state` on the envelope, using the CLIENT'S four names: `VERIFIED` / `CONFIRMED` / `NOT_APPLICABLE` / `UNRESOLVED`. `ASSUMED` must be unrepresentable | 1.3, and the 125 doc's core ask | HIGH |
| F6 | `evidence_state` incl. a real `suggested` state | 1.4 | HIGH |
| F7 | Guard the client-answer write: if a source value exists and `same_fact == DIFFERENT`, store as a candidate and raise a producer conflict | 1.5, B4 | HIGH |
| F8 | Move `_canon_line` to a leaf module, delete the three silent `lambda: None` fallbacks, add `Computer Coverage` | 1.7 residual, B6 | MEDIUM |

#### Why this and not the alternative

* **Rejected: make `normalize_value` do everything.** `fact_equivalence`'s own docstring
  rejects it and is right - clustering and conflict detection need OPPOSITE answers on the
  same input (`EMC Property & Casualty` vs `Employers Mutual Casualty` must collapse for
  document clustering and must NOT collapse for the conflict picker). Two comparators, one
  dispatcher.
* **Rejected: fix the four reported symptoms at their call sites.** That is exactly what
  the last four sessions did, and it is WHY there are four comparison sites with four
  behaviours. A symptom fix here guarantees a fifth site next month.
* **Rejected: delete the ambiguity guard.** It is protecting a real case
  (`test_a_fragment_matching_two_hosts_is_not_merged`). F2 keeps it and adds the missing
  distinction instead.
* **Rejected: widening `CONFLICT_WITHHOLD_KEYS` (currently ONE key, `umbrella_limit`) as
  part of this work.** Rule 1.4 arguably demands it, but it blanks more boxes on real
  forms. That is a product trade, not a bug fix - raised as Q4 below.

#### Blast radius

F2 and F3 can only ever REMOVE a conflict; F4 can only ever RAISE a match tier. So:
**scores on past submissions will go UP.** Same category as the 2026-08-07 auto-symbols
correction - it is a correction, not a regression, and **Brent must be told before he
notices**.

Gate tests that must survive unchanged: `test_a_fragment_matching_two_hosts_is_not_merged`
(verified compatible - that trio is not a clique), and
`test_the_umbrella_conflict_survives_every_rule` (verified compatible - $3M vs $1M is
`DIFFERENT` with no owner evidence on either side).

#### Known / deliberately not measured

* How OFTEN real packages hit the 3-way clique vs the 2-way case. The mechanism is proven;
  the frequency is not.
* F5/F6 end to end - no live session or database in this environment. The schema was read,
  no migration was run.

---

<!--
ENTRY TEMPLATE - copy this block, do not delete it.

### [ID] Short title - STATUS (YYYY-MM-DD)
**Priority:** V1-CRITICAL | V1-HIGH
**Principle(s) touched:** 1..7

**Problem.**

**Root cause.**

**Fix.**
- files:
- tests:
- suite result:

**Why this and not the alternative.**

**Blast radius checked.**

**Known / deliberately not done.**
-->

---

## DECISION REGISTER

Standing decisions that outlive a single change. If a later chat wants to reverse one of
these, it has to argue with what is written here first.

| ID | Decision | Date | Rationale |
|----|----------|------|-----------|
| D0 | This file takes precedence over `SQS_Scoring_Specification.docx.pdf` where they conflict | 2026-08-20 | Product direction for V1 |
| D1 | `125_reference/` is the master answer key for ACORD 125. A generated 125 is judged against it, not against "looks complete" | 2026-08-20 | Client's own framing: *"source packet -> correct 125 -> expected unresolved fields -> expected recommendations"* |
| D2 | **(rewritten 2026-08-21)** Facts carry TWO axes: `value_state` = client 1.3's six (present / explicit_no / not_stated / not_applicable / unable_to_determine / conflicting) and `evidence_state` = client 1.4's four (source_verified / user_confirmed / derived / suggested). The 125 doc's VERIFIED / CONFIRMED / NOT APPLICABLE / UNRESOLVED are the DISPLAY projection of those two axes, not a third model. `ASSUMED` is unrepresentable on either axis | 2026-08-21 | C1-B FLAG 2: the first draft merged value and evidence into one list and lost "present but only suggested" |
| D3 | Section 1 is fixed at the COMPARATOR, not at the call sites. One entry point; no site chooses its own normalization | 2026-08-20 | Four sites, four behaviours, all created by per-site fixes. A fifth site is otherwise inevitable |
| D4 | The ambiguity guard in `equivalent_index` is KEPT and refined, never deleted | 2026-08-20 | It protects `test_a_fragment_matching_two_hosts_is_not_merged`, a real case. The defect is that it cannot see a clique, not that it exists |
| D5 | ACORD 125 form-version work is CLOSED with no code change - we already ship 2025/03 | 2026-08-20 | Verified from `backend/templates/ACORD_125.pdf` footer, not from documentation |
| D6 | Fixes that raise past scores are shipped, and Brent is told BEFORE he sees the movement | 2026-08-20 | Same handling as the 2026-08-07 auto-symbols correction. A silent upward correction reads as a bug |
| D7 | Every "act only when exactly ONE candidate matches" guard counts equivalence CLASSES, never raw candidates | 2026-08-21 | C1-B: B1, location consolidation and contract-printing election all share this blindness; C23 round 2 already proved the fix on currency |
| D8 | Scope is attached to a fact BEFORE comparison (F2b), never inferred inside the comparator | 2026-08-21 | Client 1.1 order. An unscoped scalar on a multi-policy package cannot be rescued after the fact |
| D9 | **(amended 2026-08-21)** `lob_canon.canon_line` maps a phrase to a family only from explicit allow-lists. A KNOWN specialty liability line gets its OWN family (professional / epli / pollution / directors_officers / employee_benefits / liquor) - a distinction, not an equivalence. Truly unknown terminology returns None. Folding a phrase into an existing family, or adding a family, needs product approval | 2026-08-21 | Client 1.7; C1-B FLAG 4. Returning None for a known specialty line would have made `_specialty_leftover_lines` treat it as unplaceable and blank the ACORD 131 Other-policy row (`test_a_liquor_policy_fills_the_131_other_underlying_row`) |
| D10 | The door's cheap first pass groups entity names on `strict_entity_key`, never on `normalize_name` / `normalize_carrier` | 2026-08-21 | C1-C correction 1: the coarse normalisers fold two real carriers into one token; that is Round 10 fix 46 and it must not come back one layer up |
| D11 | In the picker, scope is decided after the pure-value merge and BEFORE the package-context merge; a scoped field skips the context merge | 2026-08-21 | C1-C correction 2: merging first hid "two GL policies in one period" as consistent. Client 1.5: retain each under its scope |
| D12 | A client questionnaire answer that materially disagrees with a present, non-human source value is HELD for the producer, never applied. Agreement or a blank source applies immediately | 2026-08-21 | Client 1.5 verbatim. Kill switch `ENABLE_CLIENT_ANSWER_CONFLICT_ROUTING` pending Q2 |
| D13 | A held client answer is resolved on the **generated-forms screen**, never through the Data Consistency picker. The picker resolves via `_finalize_pipeline`, which sets `generated_forms: {}` and wipes the producer's forms; the ARQ recalc never rebuilds the picker either. Post-generation decisions go through `apply_producer_answer_to_session`, which patches existing forms in place | 2026-08-21 | C1-D. C1-C shipped the wrong routing and the hold was invisible. `test_the_picker_path_really_does_wipe_generated_forms` re-opens this decision if the wipe ever stops being true |
| D14 | Post-generation producer decisions get their OWN session key and their own panel section, not a `structured_issues` cluster | 2026-08-21 | C1-D: the cluster machinery would need a new cluster, tier and `replace_recomputed_issues` source for what is a two-button decision. Revisit only if these must count in the issue badges |
| D27 | One coverage label may name TWO coverages ("Comprehensive and Collision"). Symbol parsing assigns to ALL of them | 2026-08-21 | C1-L: the scalar `normalize_coverage` dropped the second, losing the collision symbol |
| D28 | A value the documents let us COMPUTE is never a client question. Derive it, label it `evidence_state: derived`, and only ever from positive evidence that never overwrites a stated value | 2026-08-21 | Client 1.4 Derived + Brent Q1 ("if the paperwork says a value we don't need it from the client"). C1-L: years_in_business |
| D26 | Coverage evidence has THREE states - `grants`, `denies`, `silent` - and `not grants` is NEVER `denies`. A certificate never prints premiums, so most COI rows are silent | 2026-08-21 | C1-K: negating the grant predicate manufactured a false LOB warning three runs in a row. Principle 3 |
| D25 | **The two-comparator split is permanent and must be chosen per QUESTION.** "Do these documents disagree about the carrier?" -> `conflict()` (strict key; two real carriers must surface). "Do these belong to the same submission / is this loss run ours?" -> `carriers_same_family()` (alias map). Hit twice now - loss-run corroboration and submission integrity | 2026-08-21 | C1-E and C1-J. Using the conflict comparator for a clustering question raised a false note both times |
| D23 | A document's ROLE decides which facts it may witness in a cross-document comparison (`fact_comparison.document_witnesses`). Fail-open: an unlisted doc_type witnesses everything | 2026-08-21 | Client 1.2 lists carrier role and insured/producer role as scope dimensions. C1-I: a loss run's policy number / carrier / dates describe the CLAIMS, not the submission |
| D24 | A lines-of-business conflict requires one source to DENY a line another lists as active. Two positive lists never conflict | 2026-08-21 | Client 1.7 acceptance + Principle 3. C1-I: an extra line is information, not contradiction |
| D20 | Scope applies ONLY to identifiers, names and dates - never to money. `PackageContext` keys ownership on the value's characters, so two facts sharing an amount share an owner | 2026-08-21 | C1-H: that accidental identity silenced the client's umbrella conflict on the first live run |
| D21 | A fact `fact_line()` can place belongs to ONE line and must NEVER be scoped across policies. C1-C had this inverted | 2026-08-21 | C1-H. `umbrella_limit` IS the umbrella's limit; two values for it are a disagreement, not two policies |
| D22 | Gate fixtures must be built from the LIVE index shape, not a convenient one | 2026-08-21 | C1-H: every umbrella gate test gave `$1,000,000` no owner. The real dec page gives it one, and that is the whole bug |
| D19 | **OWNER 2026-08-21, overruling the deferral:** scope must be STORED on the fact, generically, for ANY number of policies and for every material fact - not re-derived at each point of use. Implementation is ADDITIVE: `merged_facts[key]` keeps its current shape (all 776 fact reads stay valid) and a parallel `facts["_scoped"][key] = [{scope, value, sources, evidence_state}]` carries the relationship. Consumers that need scope read the scoped store; everyone else is untouched | 2026-08-21 | Owner: *"they can have many or less depending on dec pages ... we should carry relationship, we should store it somehow, not just this but for every other important fact."* Storing it removes the two-mechanism drift risk without a 776-site rewrite. NOTE: nothing was ever hardcoded to 3 - `_scope_values` loops over N - but re-deriving was the real defect |
| D16 | **BRENT 2026-08-21 (Q4):** a cross-document conflict STAMPS the suggested value; it never ships an owned blank. The conflict stays visible in Data Consistency and stays confirmable. `CONFLICT_WITHHOLD_KEYS` is empty; intra-document limit conflicts are NOT covered by this ruling and still blank | 2026-08-21 | Owner: the conflict is already asked in Data Consistency, so an empty box adds nothing and costs a sendable form. Partially reverses the 2026-08-15 note - recorded in C1-F so nobody restores it by accident. Revert = put the key back |
| D17 | **BRENT 2026-08-21 (Q2):** a client answer that contradicts the documents is held and the agent picks. Confirmed as the shipped default | 2026-08-21 | Already built (F7 + C1-D); Brent's answer makes it the ruled behaviour, not a proposal |
| D18 | Any code that must REMOVE a fact key uses `upd_processing_session(..., delete_facts=[...])`, never a bare `pop` | 2026-08-21 | B13: the facts merge is additive by design, so a pop is a silent no-op |
| D15 | A human-supplied fact survives every pipeline re-run. Restored when the documents are still silent or agree; HELD (rule 1.5) when they now disagree | 2026-08-21 | C1-D closes Q7. A re-run reads the same documents, so no precedence ruling was ever needed - that framing in C1-C was wrong |
| D29 | **C3 3.2's 40 / 35 / 25 is the SUBMISSION Structural formula ONLY.** Per-form Structural stays that form's own ACORD checklist minus the OCR penalty. Do not "unify" them; `calculate_sqs`'s `tier2_score` parameter is unread BY DESIGN | 2026-08-25 | `SQS_Scoring_Specification` prints both formulas side by side TWICE (section 3.1 and section 10's scope table) and the master plan modifies only the submission line. Precedence: an unmodified rule stays authoritative. The owner's *"for both per form as well as package"* ruling carries *"wherever applicable"*, and this is the one place it is not |
| D30 | **A ceiling and a pillar deduction may BOTH charge for the same fact.** That is not double counting | 2026-08-25 | 3.9 preserves the ceilings verbatim and adds *"Individual pillar deductions continue to reflect the volume/severity of underlying issues"*; spec section 7 says the same. Settles what the de-duplication work may and may not touch |
| D31 | **Double counts the client did not NAME are reported, never removed** - except the two the owner explicitly ruled on (2026-08-25: operations description, revenue). Engineering does not decide which deductions disappear | 2026-08-25 | Precedence note: no new scoring rules without product approval; Principle 7. C3-D records why the revenue removal could not be naive - the same -15 was payroll's ONLY home after 3.14 |
| D32 | **Removing a field from the SCORE never removes it from the QUESTIONNAIRE.** Fields dropped from Tier 2 are pinned by name in `question_classifier._SCORE_REMOVED_STILL_ASKED` | 2026-08-25 | Measured before the pin: `total_payroll`, `wc_payroll_period` and `wc_officer_exclusions` all fell to audience=internal / suppressed - Primble would have stopped asking anyone for annual payroll, a far worse regression than the scoring bug 3.14 fixes |
| D33 | **The score trace is emitted BY the scorer, never reconstructed for display**, and anything that credits a score goes through `sqs_service.apply_credits_to_score` so the headline and the trace move together | 2026-08-26 | C3-J: FOUR call sites patched the headline and left the trace stale, printing "81 earned = 85" in the one panel built to make the arithmetic reconcile. A second computation "for the panel" is how the panel and the score drift apart again - the defect C3 exists to close |
| D34 | **`COALESCE` is not a guard on jsonb.** Every `jsonb_array_elements` / `jsonb_each` / `jsonb_array_length` argument uses `CASE WHEN jsonb_typeof(x) = 'array'` (or `'object'`) | 2026-08-26 | C3-I: COALESCE substitutes only for SQL NULL. A stored JSON **null** is a valid jsonb value, reaches the expansion as a scalar, and raises `cannot extract elements from a scalar`. It was live in five places and silently broke dismissal credits |
| D35 | **Observability code is production code.** A `try` that wraps both the work AND the reporting of it can lose work that already succeeded; every blanket `except Exception` logs with `exc_info=True` | 2026-08-26 | C3-G / C3-I: a log line interpolating an unbound variable turned a completed credit into a null response, and a bare `str(ex)` made three different failures read identically. One traceback from the owner's logs settled what three of my diagnoses could not |

---

## LIVE TEST RESULTS - C3 (last updated 2026-08-26, C3-J)

**Read this for the C3 verdict.** Every row below was observed on the real
application with real uploads, not reasoned about. Test data and the numbered
checks are in `v1_c3_testdata/` (regenerate with
`py backend/scripts/make_v1_c3_test_pdfs.py` - the policy dates are computed
from today, and a stale set drifts into paths the scenario was not built for).

**Baseline before any C3 work: 4291 passed / 1 failed. After: 4329 passed /
1 failed** - the same `httpx`/`openai` environment conflict throughout, zero
regressions at any stage. Frontend production build clean.

### The eight scenarios

| # | What it proves | Verdict |
|---|---|---|
| S1 | Dec page ONLY - producer name exempt, contact information NOT | **PASS.** Tier 1 80%, contact owed, producer-name card reads 0 pts |
| S2 | Dec page + application - the exemption switches OFF | **PASS.** Tier 1 60%, both owed, package 65 against S1's 69 |
| S3 | GL-only - Tier 2 reaches 100 with no payroll or WC data | **PASS.** Tier 2 100%, zero WC recommendations, no NAICS chips |
| S4 | Revenue charged ONCE, not again in Exposure | **PASS.** Tier 2 83% listing "Annual revenue", Exposure Revenue/Sales 100% |
| S5 | A conflicting value surfaces and does not read as complete | **PASS.** Data Consistency shows both figures; value still stamps (D16) |
| S6A / S6B | Location schedule satisfies the physical-address rule; the control still fires | **PASS both directions** |
| S7 | Ceiling 60 **with the reason named** - the headline check for all of C3 | **PASS.** *"77 earned, held at 60 = 60"* + the invalid policy period |
| S8 | A credit is earned, and SURVIVES a field edit | **PASS.** A 81 -> B 85 (*"81 earned + 6 credited, held at 85 = 85"*) -> C 85 |

### Clause by clause

| Clause | State |
|---|---|
| 3.1 pillar weights | No change needed - already 25/25/15/15/10/10. Now test-pinned |
| 3.2 Structural 40/35/25 | **Shipped, SUBMISSION only** (D29) |
| 3.3 Tier 1 fields + exceptions | **Shipped.** Exemption narrowed twice - `_only_dec_page`, and contact information is no longer waived |
| 3.4 Tier 1 scoring | No change needed - verified equivalent, not assumed |
| 3.5 / 3.14 Tier 2 fields | **Shipped.** Six fields; the four removed are pinned into the questionnaire (D32) |
| 3.6 NA out of the denominator | **Shipped.** 80, not 83 - and it needed a `fact_state` seam fix to be reachable at all |
| 3.7 no-form rescale | **Shipped.** 53.3 / 46.7, DERIVED from 3.2 rather than typed |
| 3.8 fill-rate rules | **All four shipped** via confidence labels; the denominator is untouched, as 3.8 requires. See Q15 |
| 3.9 ceilings | No change needed - verified against his four worked examples and the no-stacking rule |
| 3.10 recalculation | **Shipped.** The field-edit path re-applies credits; Download Anyway, the issue toggle and a junk resolve were verified already correct |
| 3.11 credits | **Shipped.** One credit per fact; survives every rebuild (D33) |
| 3.12 physical address | **Shipped.** Auto garaging added; a location schedule satisfies it |
| 3.13 NAICS / SIC | **Shipped** - already producer-routed; suggestions off behind a flag. See Q16 |
| **Desired Outcome** (traceability) | **Shipped.** `build_score_trace` on the package AND every form; the breakdown reconstructs its pillar to the point |

### The nine bugs, and who owns them

**Pre-existing, invisible until C3 made them reachable:**
1. `pkg_base` UnboundLocalError in `_apply_dismiss_score_credit` - live since 2026-08-16 (C3-G)
2. **`COALESCE` does not catch a JSON null** - broke dismissal credits outright, in five places (C3-I)
3. A field edit destroyed earned credits - live since 2026-08-16 (C3-D / F5)

**Mine, found by the owner's live runs:**
4. `locations` row shape guessed as dict; it is a list of strings (C3-E)
5. An exempt card advertising +5 points from a measured zero (C3-E)
6. A non-binding ceiling claiming *"held at 85 = 81"* (C3-H)
7. A credit applied but not displayed - *"81 earned = 85"* (C3-H)
8. The same trace defect on four more paths (C3-J)
9. A dismissed card springing back into the open list (C3-H)

**Plus four fixture faults, all mine**, every one a shape ASSUMED rather than
read from the writer (C3-E, C3-F).

### What C3 did NOT do

* **F-1 (invented GL class codes) is untouched** and stays open under H6. It is a
  form-fill grounding defect, not a scoring one; C3 changes what a gap COSTS,
  never what fills a box.
* **Q9's `CONFIDENCE_SCORE` -> `evidence_state` switch is closed for V1.** Brent
  confirmed the weights as-is (2026-08-24) and 3.8 forbids the redesign this pass.
* **Per-form Structural is unchanged** - see D29.
* **The live before/after measurement for Brent has NOT been run.** Scores moved
  in both directions and he has not seen real numbers. D6 applies.

### Standing lesson from this arc

**The scoring engine was right from the first run.** Every failure after that was
in the layer that EXPLAINS the score - a ceiling claiming to hold a score it was
not holding, a credit applied but not shown, then shown and unshown again on a
different path. Each was the same shape: **a number changing without the thing
that explains it changing too.**

And C3-H closed with the words *"any future patch-the-headline path has the same
hazard"* - after which one path was fixed and four were left, and the next run
reproduced the defect somewhere else. **A hazard named in a log entry is not a
hazard mitigated.** When a defect is "this can happen anywhere that does X", make
X impossible - one door plus a test that fails on a second one.

---

## OPEN QUESTIONS FOR PRODUCT

Anything that needs Brent's answer before engineering can proceed. Do not guess these -
Principle 7 applies.

| ID | Question | Blocking | Raised | Answer |
|----|----------|----------|--------|--------|
| ~~Q1~~ | ~~Three rows or one?~~ **CLOSED 2026-08-21, not a product question.** Client 1.5: *"retain each under its correct scope"* - retain means show. Three read-only rows, one per policy, shipped in C1-D | - | 2026-08-20 | Answered by the spec |
| Q14 | **Two double counts the client did not name.** After his own 3.5 / 3.14 removals, `operations_description` is still charged in Structural Tier 2 AND in Exposure, and `total_revenue` is charged in Tier 2 AND in Exposure whenever payroll is also absent. **The owner ruled on these two 2026-08-25 ("remove them as well") and they are DONE** - see C3-D for why the revenue removal could not be naive. This row stays open only for Brent's confirmation, since it changes scores on accounts missing those facts | C3 | 2026-08-25 | **Owner: remove. SHIPPED.** Brent not yet told (D6) |
| Q15 | **What does Brent think the fill-rate denominator is?** 3.8's *"Not Applicable fields must not reduce fill rate"* only bites if the denominator contains UNFILLED fields; ours counts only FILLED ones, so it is an average confidence rather than a fill rate. **Measured 2026-08-25: the bullet is NOT a no-op** - a box holding the literal `"N/A"` dragged a form from 100 to 75, and a box holding `"None"` scored 0. Both are fixed via confidence labels WITHOUT touching the denominator, which 3.8 forbids this pass. Open question: does he want filled / applicable (a redesign), or is the current measure what he meant? | C3 | 2026-08-25 | |
| Q16 | **The Figure 20 NAICS chips have been dark since 2026-08-12** - `suggestions` renders only in `ClientQuestionnaire.jsx` and NAICS moved to the PRODUCER audience that day, so a praised feature stopped reaching a screen and nobody noticed. 3.13 now defers classification assistance to Section 19 anyway, so V1 leaves it dark behind `ENABLE_CLASSIFICATION_SUGGESTIONS=false`. **A disclosure, not a decision** - D6: he hears it from us rather than discovering it | C3 | 2026-08-25 | Tell Brent; no action needed |
| Q17 | **Should a card WITH a fillable field also offer dismiss-with-reason?** Spec section 9 says any dismissal with a written reason earns credit and draws no distinction, but the control renders only on cards with NO fillable field (`answerable = !!rec.field && onAnswer`), so on every other card `Dismiss` sends an empty reason and earns nothing - and a filled text box beside it is silently discarded | C3 | 2026-08-26 | **OWNER 2026-08-26: not now, maybe in future.** Semantics unchanged for V1 |
| ~~Q2~~ | ~~Do we hold a contradicting client answer for the agent?~~ **ANSWERED 2026-08-21: YES** - *"implement this behaviour properly."* Already built (F7 + C1-D); now the ruled default. See D17 | - | 2026-08-20 | **Brent: yes, hold and let the agent pick** |
| Q3a | Loss run filed under the DBA, FEIN matches: what tier? **Measured cost of the default (2026-08-21): 5 clean years scores `strong`=100 / `moderate`=92 / `possible`=85 / `no_match`=**25** on the Loss History pillar (`_LOSS_NO_MATCH_CAP`). So "no credit" is a 75-point swing on that pillar, not a nudge.** Engineering default stays `no_match` + the note `NOTE_DBA`, rendered on the Loss History card. **C1-R 2026-08-24: the first draft asked Brent to split "DBA matches the declared DBA" from "trading name only on the loss run" - the second is NOT detectable (`loss_run_identity` only knows DBAs from `pkg["dba"]`; an unseen name is indistinguishable from a different company), so it IS Q3b. Client doc now recommends: a match against a DECLARED DBA is a name match and the normal tiers apply. Implementation if accepted: `dba_ok` joins `name_ok` in the tier branch** | F4 row 4 | 2026-08-20 | **BRENT 2026-08-24: verified match.** *"Treat it as a verified match if the DBA is listed by the applicant and the EIN matches."* SHIPPED (C2-E): a declared-DBA name is a name match; ordinary tiers follow |
| Q3b | Loss run where FEIN matches but the legal NAME does not (name change, merger): what tier? Client spec only lists name+FEIN. Same default (`no_match`, same 100->25 swing) and the note `NOTE_FEIN_NAME_DIFFERS`, rendered on the Loss History card. **C1-R: client doc recommends 92 + keep the note (a 9-digit FEIN is unique per entity and survives a name change; the name cannot be corroborated)** | F4 | 2026-08-21 | **BRENT 2026-08-24: probable match.** *"Treat it as a probable match and ask for confirmation of the prior name or entity relationship."* SHIPPED (C2-E): `moderate` + confirmation note |
| ~~Q6~~ | ~~Bare "Liability" = General Liability?~~ **CLOSED 2026-08-21.** The client already answered it in 1.7, which lists **Liability** in the General Liability family. Code was already correct; asking would have been asking him to re-answer his own spec | - | 2026-08-21 | Answered by the spec |
| ~~Q4~~ | ~~Blank box or best guess when two documents disagree?~~ **ANSWERED 2026-08-21: patch the suggested value.** `CONFLICT_WITHHOLD_KEYS` emptied; conflict still shown and confirmable in Data Consistency. See D16 and C1-F | - | 2026-08-20 | **Brent: patch the suggested value** |
| ~~Q7~~ | ~~Client answers lost on a pipeline re-run - needs a precedence ruling.~~ **CLOSED AND FIXED 2026-08-21 (C1-D).** The precedence framing was wrong: a re-run reads the SAME documents, so no rival value can appear. Restore when silent or agreeing; hold (rule 1.5) when they disagree. No product decision required | - | 2026-08-21 | Answered by the spec |
| Q8 | On a RENEWAL, is the carrier named on the uploaded dec page the PRIOR carrier? Deriving it would stop asking the client (Brent's Q1 principle), but it is only true when the uploaded dec is the EXPIRING policy - a renewal quote from a new carrier names the incoming one. Engineering will not guess (Principle 7). **C1-R 2026-08-24: the first draft's proposed rule ("term ENDS when the new term starts") was CIRCULAR - on a renewal the new term start is DERIVED from the expiring expiration (`_route_renewal_dates`). The checkable rule the code already uses for dates is "the uploaded term has ALREADY ENDED"; the client doc now proposes extending exactly that to the carrier. Second correction: on a multi-policy package there is no scalar `carrier_name` (D-1 Layer 1) - carriers live per line in `_scoped`, and ACORD 125's prior-carrier section is per line, so the derivation must be PER LINE, not into one `prior_carrier` box** | C1 / C4 | 2026-08-21 | **BRENT 2026-08-24: DECLINED.** *"That's not really how brokers work. For now, skip shortcut and ask client. We'll pull something more concrete together with if/and/or."* Nothing built; keep asking the client. He will bring rules later |
| ~~Q5~~ | ~~The 125 doc says a narrative "no known losses" must not be treated as verified history. Today it earns the same tier as a signed attestation (60, not the 100 year-tier). Is attestation-tier acceptable, or must a narrative score lower?~~ **CLOSED 2026-08-24, was already stale when raised.** Verified against the live `calculate_p4_loss_history`: `_user_attested` -> 60, narrative-only (`narrative_states_no_losses` with no attestation flag) -> **45**, both distinct from `no_match`'s 25. The split already existed, per the function's own `§6.4` comment citing the client's approved scoring table - Q5's premise ("today it earns the same tier") was wrong when written; nobody had re-checked the code before drafting it. Not sent to Brent (kept out of `20Aug_questions_brent.md`), to avoid asking him to re-answer something already decided | C2 | 2026-08-20 | Answered already, by the original spec |
| Q9 | **The 0.85 / 0.50 confidence weights were NEVER the client's - the code claimed they were.** `sqs_service.CONFIDENCE_SCORE`'s comment read *"per spec (producer=1.00, AI-high=0.85, AI-low=0.50)"* and `confidence_fill_rate`'s docstring said *"Spec: ..."*. **Both false, verified 2026-08-24 (C1-R): `SQS_Scoring_Specification.docx.pdf` extracted in full (24,689 chars) and searched - `0.85` and `0.50` appear ZERO times.** The spec requires only a *"confidence-weighted"* fill rate and never sets weights. Comments corrected; the ask to Brent is reframed from "change your numbers" to "you never set these". **C1-S (same day): the `ai_high` 0.85 this row worried about is NEVER assigned to a form field - the field label is `ai_verified`, and it was MISSING from the table, scoring 0.00. FIXED at 0.85 (see C1-S). Q9 now asks Brent for the weight of a Suggested value that IS on the page (0.85, shipped) vs one that is NOT (0.50), plus Derived = 1.00.** **A "Suggested" value scores the same as a Source Verified one.** `services.fact_state` writes the client's four-level evidence axis correctly on every fact, but `sqs_service.CONFIDENCE_SCORE` still keys on the older `confidence` tag - an AI-suggested value scores `ai_high`=0.85, identical whether or not it was ever confirmed. Not fixed unilaterally: switching the read moves EVERY historical score. Client 1.4/1.5's own rule ("a Suggested material value should not silently become Source Verified") is unmet in SCORING specifically, though the fact-level labelling is correct. **C1-R: the first draft asked for ONE Suggested weight - wrong, because `ai_high` (0.85) AND `ai_low` (0.50) both map to `suggested`, so one number collapses two tiers. Client doc now asks for Suggested-high / Suggested-low (recommends 0.70 / 0.40) and proposes Derived = 1.00. Also NOT a one-line switch: `CONFIDENCE_SCORE` is per FORM FIELD (`confidence_dict` from `pdf_service`), `evidence_state` is per FACT - needs the field -> source-fact map. Ship for new sessions only (D6)** | C1 / C3 | 2026-08-24 | **BRENT 2026-08-24: confirmed as-is.** *"Those assignments will do for now."* 1.00 / 0.85 / 0.50 stand; the `ai_verified` 0.00 defect fix (C1-S) is the only movement |
| ~~Q10~~ | ~~**"No Property coverage" - Explicit No or Not Applicable?**~~ **CLOSED 2026-08-24 (C1-R), not a product question - same precedent as Q6.** The client ALREADY answered it: 1.3 lists "No Property coverage" under Explicit No in his own words, so asking would be asking him to re-answer his own spec. And on inspection the two readings do not even compete: his example is about the coverage **LINE**; our `not_applicable` is on the **FIELDS UNDER** the line. Different objects. We simply record no state on the line object at all today - only `denied_lines()` knows. **Build it to match his wording (line = `explicit_no`, fields stay `not_applicable`); do not ask.** Removed from `20Aug_questions_brent.md`. The line-level envelope is NOT yet built - owner's call on when it ships. Original text: Client 1.3 lists it as an Explicit No example; a declared-absent coverage line currently records as `not_applicable` instead. Functionally near-identical downstream (neither is asked about, neither penalises fill rate) - a labelling/audit-trail question, not a behaviour bug. Both readings are defensible; not decided unilaterally. **C1-R: client doc now RECOMMENDS instead of coin-flipping: the coverage LINE is `explicit_no`, the fields under it are `not_applicable` - the two do not compete. Verified 2026-08-24: all 26 property-line facts resolve `not_applicable` on a declared-absent line. If accepted, the only engineering add is a per-line envelope so the audit export shows the line itself as `explicit_no` (today only `denied_lines()` knows)** | C1 | 2026-08-24 | |
| Q11 | **"No Loss Runs Available" is a 2.9 STATE but 2.5 gives it no SCORE.** Shipped default: 25 alone (the Nothing Provided value), 60 when paired with a no-loss attestation - fails toward no invented credit. One-line swap in `calculate_p4_loss_history` when Brent rules | C2 | 2026-08-24 | **BRENT 2026-08-24: our default was WRONG.** *"we can't treat 'N/A' as '0' ... If 'no known losses', check against the number of years in business."* SHIPPED (C2-E) as the years-in-business ladder. The 1-5 band's exact numbers are our derivation, flagged to him |
| Q12 | **"Fully valued" requires claim statuses/financials to be READABLE, but no deduction is defined when years parse and statuses don't** - and extraction has no per-claim readability signal to check. Shipped default: no separate deduction (the other three fully-valued components each have their own). A real signal means an extraction-schema change (improving-ll.md rule applies) | C2 | 2026-08-24 | **BRENT 2026-08-24: confirmed, V2.** *"Good ... V2 - Adding it would mean reading claim-by-claim details from every carrier's layout."* No V1 deduction |
| Q13 | **An ESTABLISHED business that never carried insurance** ("None" to prior carrier): is prior carrier "applicable"? 2.3 only exempts New Venture, so the -10 applies today. Defensible (no prior coverage on an operating business IS an underwriting gap) but the client never said it | C2 | 2026-08-24 | **BRENT 2026-08-24: our default was wrong.** *"the applicant would be 'previously uninsured', which is very different from 'missing prior carrier' ... there probably shouldn't be a deduction here for now."* SHIPPED (C2-E): the -10 now needs positive evidence prior coverage existed |

**`20Aug_questions_brent.md` at the repo root is the ONE client-facing list: Q3a, Q3b, Q8,
Q9** (Q10 closed; the C2 items Q11-Q13 were ANSWERED 2026-08-24 - see "BRENT'S RULINGS - ALL CLOSED" below) - written for Brent, not for engineering.
**Consolidated 2026-08-24:** the Data Consistency and Loss History chats had each drafted
the same four decisions; the Loss History wording is the one kept (it owns the pillar
those decisions score), so Section 1 no longer has a section of its own in the doc. (The earlier
`QUESTIONS_FOR_BRENT.md` this paragraph used to name was never in the tree - found missing
2026-08-24, C1-R.) **Owner rule 2026-08-24: that doc carries QUESTIONS ONLY** - the doubt,
what the code does today, a proposed answer, the ask. No status, no "what we shipped", no
verification results, no score-movement tables; the D6 heads-up about scores moving goes
to Brent separately, not in this doc. Update both files together; this table is the
engineering register (why each is open, what the code does today), the other is the ask.

---

## Session 2026-08-22/23 - the declarations index: built, measured, switched off

**Full account: `LLMcall1-promptChange.md` at the repo root (nine rounds).** This
is the V1 summary and the decisions worth carrying forward.

### Net effect on V1: none of the C1 work changed. Extraction costs what it did before.

The facts/flags prompt is **byte-identical** to its pre-session form (verified
against git) and `dec_page_entries` is back inside `_EXTRACT_SCHEMA`. One LLM call
per chunk still produces facts, flags and the index together. `PROMPT_VERSION` and
`SCHEMA_VERSION` moved to **v14** - the schema equals v12, but the version must
move FORWARD because v13 replies (facts and flags with no dec entries) are in the
extraction cache.

### D18 - a richer declarations index does not earn its cost. DECIDED, on a form comparison.

The dedicated index pass was made to work, then A/B'd against the ~250-entry index
the main extraction produces for free:

```
facts + flags (whole extraction) : 14 calls,  ~30,000 output tokens
dedicated index pass             : 39 calls, ~593,000 output tokens  (+18-20 min)
```

Owner regenerated the ACORD forms: **"almost the same"**. `DEC_INDEX_DEDICATED_PASS`
now defaults to `0`. The mechanism is measurable, not opinion: the rich index
rendered to **89% of the document** and split across **8** Stage A calls, where the
design is ~3% in one - so LLM call 2 gained nothing over walking the raw document.

**Do not re-open this on an argument.** The one untried configuration is the
FILTERED index (fillable `value_type`s plus anything on a declarations/schedule
page = 1,341 entries, 17%, ONE Stage A call, every key value surviving). Rebuild it
from `LLMcall1-promptChange.md` §40 if it is ever worth another test run.

### D19 - the whole uploaded document stays in scope. OWNER RULING.

`declarations_authority` was measured NOT discriminating on a real package - 39 of
39 pieces cleared the gate, 33 at ~0.5, because its `brevity` half scores mean LINE
LENGTH and a column-laid-out policy PDF has short lines on every page. Raising the
bar to 0.60 would have cut index work by 87%. **Rejected on the owner's
instruction:** *"Whole document uploaded by user is important."* Recorded so nobody
re-proposes it as a cost saving.

### Bug fixed that had been silent since the pass shipped

`_run_extraction` merged the index into `result["dec_page_entries"]`, but
`_merge_list_fields` returns `{"facts": ..., "flags": ...}` - one level too high,
so `extraction_pipeline` (which stores only `extracted["facts"]`) discarded every
entry the pass ever produced. Invisible while the main extraction also recorded
entries. Fixed; kept even with the pass off.

### Kept, independent of all of the above

- **`_retry_wait_seconds`** (`config/settings.py`): the backoff was ~15 seconds
  total against a 60-second TPM window, for every LLM caller in the codebase.
  `Retry-After` is now obeyed; a 429 backs off 5/15/30/60.
- **Label-aware Stage A splitting**: the old splitter cut the index by character
  count and could separate the umbrella's $3M from the GL's $1M. Dormant at ~250
  entries, safe if one ever grows.

### Verified for production, not assumed

- `PURGE_DEC_INDEX_AFTER_GENERATION` defaults to **1**, so production DOES delete
  `dec_page_entries` after generation (one key; facts, flags, forms, PDFs and the
  per-document copies survive). Local `.env` has it at 0.
- Its justifying comment - *"nothing after generation reads the facts"* - is
  **false**: `_restamp_canonical_into_forms` calls `_deterministic_map(field, facts)`.
  Measured: of **5,852 fields across all 17 schemas, 9** change when the index is
  absent (4 policy numbers shorten, 5 go blank). **None gets a wrong value.** Safe;
  the comment needs correcting.
- The product lifecycle is confirmed in code: `select-forms-bulk` writes
  `generated_forms` as a wholesale replace with no union, and no route returns to
  form selection. After generation only ARQ answers and resolved recommendations
  change the forms, and they do it **deterministically, without an LLM**.

### New test asset

`test_data_v1_c1/5_complex_tables.pdf` (+ `backend/scripts/make_v1_c1_tables_pdf.py`)
- 4 pages carrying a premium summary with NO COVERAGE rows, a table of contents, a
4-row schedule of hazards, a 3-vehicle schedule, a driver schedule and an umbrella
schedule of underlying, plus captionless carrier names. Built to break the index;
now the standing fixture for any table-extraction work.

### Standing lesson

Three rounds were spent on rate limits, chunk sizes and output caps while the real
defect was a dict key one level too high. Every offline probe passed, because each
called the function directly and read its return value. **An offline probe proves
the FUNCTION, never the SEAM around it** - which is the D22 rule already written
here, learned again the expensive way.

---

## Session 2026-08-24 - C2 Loss History: the client's section 2, end to end

### C2-A Loss History scoring, evidence, states and questionnaire - SHIPPED (2026-08-24)
**Priority:** V1-CRITICAL
**Principle(s) touched:** 3 (absence is not evidence), 6 (auditability), 7 (never guess a rule)

**Precedence applied (owner instruction, this session):** the client's C2 document
overrides `SQS_Scoring_Specification.docx.pdf` where they conflict; the spec stays
authoritative where C2 is silent. Engineering added no scoring/questionnaire rule
outside the two documents - every unspecified point shipped on a flagged default
(Q11-Q13) that failed toward "no invented credit". **All three were answered by
Brent on 2026-08-24 and are now implemented - see the rulings section below.**

**Problem.** Client: Loss History spans document recognition, insured matching,
claim years, valuation dates, prior carrier, questionnaire, structural
completeness, scoring and Data Consistency - "a problem that appears in the
questionnaire may originate in scoring". Plus a revised scoring table (2.1-2.11).

**Root cause - three structural, the rest spec deltas.**
1. **No owned loss-history STATE.** The scorer's branch order, the display state
   fn and each ARQ injector all re-derived "what loss evidence do we have?" from
   raw facts/flags independently - three derivations that could disagree, which
   IS the client's complaint sentence.
2. **"Applicability" did not exist.** prior_carrier and num_claims were scored as
   unconditionally expected in TWO pillars at once (Tier-2 structural AND P4) -
   the second-independent-copy class again - and a new venture was docked for
   history it cannot have.
3. **N/A rescaling was umbrella-only, hand-inlined in THREE weighted sums**
   (package, spec_compliant, per-form). Adding loss-N/A naively would have made a
   fourth divergence.
Also 2.1 as a principle change: freq/ratio deductions measured risk desirability,
not submission quality.

**Fix.**
- files: **NEW `services/loss_history_state.py`** - the ONE owner of every
  loss-history state decision (the C1 one-door pattern): `attested_true` moved
  here verbatim (sqs_service imports it back under its old name; every existing
  import unchanged), the 2.9 canonical states (+ an explicit
  `no_loss_narrative_only` - the list said "at minimum"), new-venture
  confirm/contradict/applicable, prior-carrier applicability,
  `parse_loss_run_status` (one reader for extraction scalars AND questionnaire
  option texts), `suppressed_question_fields` (2.10).
- `services/sqs_service.py`: `calculate_p4_loss_history` rewritten to the C2
  tables - Path A 100/85/70, recency 0/-10/-20 flat/-25 + unknown -15 (Path A
  only), match 0/-8/-15 + no-match cap 25, carrier 0/-10-when-applicable (the
  +10 bonus is GONE everywhere); Path B strong = 60 PINNED AND TERMINAL (the
  client's literal "drops to 45 on a missing valuation date" bug - the pin used
  to be followed by the deduction block), moderate 42/possible 35/no-match 15
  with recency only when a date exists and NO unknown-date -15; Path C
  60/50/40/25 with attestation-before-pending preserved (attest+pending=60,
  claims+pending=50, claims+nothing=25); freq/ratio -> "Underwriting advisory
  (no score effect)" recs; new venture -> returns None. `_result` now carries
  recs accumulated before a terminal branch (found by the new tests - a literal
  msgs list silently dropped the contradicted-new-venture notice).
  `_weighted_pillar_sum` replaces all three inline sums (generic N/A rescale -
  umbrella, loss, or both). prior_carrier/num_claims OUT of `TIER2_FIELDS`, the
  ACORD 130 per-form checklist and the supp-doc display proxy (2.7/2.8; the
  spec's 130 checklist lists prior carrier - C2 precedence, because a form
  checklist cannot see new-venture applicability). `_get_loss_history_state`
  + label maps gained `new_venture_not_applicable` / `no_loss_runs_available` /
  `prior_claims_exist`; the client 5-bucket map gained `not_applicable`.
  `_LOSS_RECOMMENDATION_FIELDS` gained the new-venture/status/advisory rows.
- `services/extraction_pipeline.py`: 2.6 - the attestation-vs-claims conflict now
  emits a producer-routed Data Consistency row, **ADVISORY on purpose**: the
  client caps the PILLAR at 45 (`_LOSS_CONFLICT_CAP`, already live); a hard/soft
  stop here would wrongly ceiling the whole package at 60/85. Same routing
  precedent as `unmapped_coverage_line`; no RESOLUTION_MAP entry (the orphan
  guard test forbids non-CLUSTER_MAP codes there).
- `services/arq_service.py`: `_apply_loss_state_question_gate` runs AFTER every
  injector in BOTH generators - new venture suppresses prior-history questions
  (incl. the prior-policy trio and the loss schedule table); uploaded runs
  suppress the availability-class questions; a CONTRADICTED new-venture answer
  suppresses nothing (2.10's "unless contradictory source information").
  `_maybe_inject_loss_run_status_question` (Prior Claims Exist -> select, option
  text stored, blank is not an answer). The producer's New Venture confirmation
  rides the existing Loss History card -> `new_venture_indicator` -> both apply
  paths set `flags["new_venture_confirmed"]`.
- `services/fact_registry.py`: `new_venture_indicator` (producer-only, never a
  client question, stamped nowhere) + `loss_run_status` entries.
- `frontend/src/components/form/AcordModal.jsx`: labels + provenance rows for
  the three new states. Pillar N/A rendering needed NOTHING - the isNA branch
  was already generic for every pillar (verified, not assumed).
- tests: NEW `tests/test_loss_history_c2.py` (28 - every client table row, the
  literal 60-not-45 case, cap-is-a-ceiling both directions, rescaling incl.
  both-N/A, gating incl. the contradiction clause). Updated pins:
  `test_sqs_scoring.py` (7 tests to the C2 numbers; the stale-strong test now
  asserts the PIN and moves recency to the non-pinned tier - the old test
  pinned exactly the behaviour the client killed, so the TEST was wrong),
  `test_loss_recommendation_routing_20260817.py` (narrative 45->40; the
  nothing-provided card now also offers New Venture confirmation).
- suite result: **3918 passed / 2 failed** - the same two pre-existing
  unrelated failures as every prior entry (`test_arq_acord125_missing_only`,
  `test_normalization`), zero regressions. One additional test was CORRECTED
  during the run: `test_form_and_package_scores_stay_independently_computed`
  asserted the form and package HEADLINES are never equal - but two
  independently computed weighted sums may legitimately collide on one fixture
  (they did, 65 == 65, after the C2 renumbering moved both for different
  reasons; its pillar-level asserts, the real property, still passed). Replaced
  the fragile inequality with a structural proof: the package headline
  reconstructs from the package's OWN pillars via `_weighted_pillar_sum`, which
  a copy-the-form-headline regression would fail. File re-run: 38 passed.

**Why this and not the alternatives.**
- Patch numbers in place: leaves cause #1 alive - rejected.
- LLM state classification: deterministic facts exist; blank-over-wrong; cost
  rule - rejected.
- Copy the umbrella N/A branch for loss: creates the fourth divergence - rejected.
- Delete freq/ratio code: client wants them as future advisories - kept as recs.
- Infer new venture from business_start_date / the marketing dropdown: 2.2 says
  "the producer CONFIRMS"; inference is not confirmation - rejected.

**Blast radius checked.**
- Caps stay ceilings everywhere (min(); conflict 45 over the strong pin verified
  by test). Raw-score preservation untouched.
- `check_tier2` denominator shrinks (13->11; non-WC 10->8): Tier-2 scores on
  past sessions RISE. ACORD 130 checklist 6->5: 130 form scores shift. Path C
  pending 70->50 and narrative 45->40: those states DROP. 1-2yr runs 40->70,
  3-4yr 80->85, stale/undated strong runs 35-45->60, freq/ratio accounts up to
  +40: RISE. D6 applies - Brent is told first (the C2 questions doc, when it is written -
  `QUESTIONS_FOR_BRENT.md` never existed in the tree; see C1-R).
- Frontend: unknown states already fall back to the raw key; the N/A pillar
  renders through the existing umbrella path. Verified by esbuild JSX parse -
  a full `vite build` is env-gated on this machine (vite.config.js rejects
  VITE_API_BASE=localhost for production builds; pre-existing, not C2's).
- No LLM call, prompt, chunking or batching change anywhere in this arc -
  improving-ll.md deliberately untouched (checked against its rule).
- `loss_run_status` equality checks ("pending"/"requested") were replaced by
  `parse_loss_run_status` in BOTH the scorer and the state fn - the new
  questionnaire option texts would have silently failed string equality.

**Known / deliberately not done.**
- Q11 (No Runs Available score), Q12 (statuses-unreadable deduction + the
  missing extraction signal), Q13 (never-insured established business) - shipped
  on flagged defaults - ALL THREE ANSWERED 2026-08-24 and implemented (C2-E).
- Q3a/Q3b (DBA / FEIN-name tiers) unchanged - already with Brent; they slot into
  the SAME tier table when ruled.
- `loss_integrity_coefficient` (sqs_service) has ZERO callers - dead code,
  flagged here; left for a trivial cleanup commit rather than bundling an
  unrelated deletion into C2.
- The carrier-marketing "New venture" dropdown answer deliberately does NOT set
  the flag (it is a client answer, not a producer confirmation); it could
  pre-seed the producer card later (C4 material).

**Decisions (register additions).**

| ID | Decision | Rationale |
|----|----------|-----------|
| D29 | Claim frequency / loss ratio NEVER move the SQS - advisory recs only, prefixed "Underwriting advisory (no score effect)" | Client 2.1: SQS measures submission quality, not risk desirability. Also retires the undefined "$1M of exposure" denominator as a scoring input |
| D30 | Pillar N/A is GENERIC: a None pillar drops out of `_weighted_pillar_sum` and the remaining ORIGINAL weights rescale proportionally. Never hand-inline a weighted sum again | Client 2.2 "same mechanism"; three drifting copies was the defect class |
| D31 | Path B strong match = 60 is a PIN (terminal assignment), not a cap and not a floor. No recency/carrier/unknown-date deduction may follow it; only the 2.6 conflict CEILING (45) outranks it | Client: "remains fixed at 60". The old code charged the same unreadability twice (60 - 15 -> 45) |
| D32 | New Venture is a PRODUCER CONFIRMATION (flag/fact), never inferred from documents; contradicted by positive evidence of prior operations it suppresses nothing and scores normally with a conflict notice | Client 2.2 "if the producer confirms" + 2.10's contradiction clause; fails toward scoring, never toward N/A |
| D33 | prior_carrier and num_claims are scored in Loss History ONLY - never in any structural checklist (package Tier-2, per-form 130, display proxies). One gap, one pillar | Client 2.7/2.8 double-counting; a checklist cannot see applicability |

### C2-B FIRST LIVE RUN - 3 of 5 scenarios verified; 2 ran a STALE PROCESS; 1 polish fix (2026-08-24)

Owner ran all five `test_data_c2_loss/` packages on the real app and sent full
screen captures. Verdict per scenario, against the expected table:

| # | Expected | Observed | Verdict |
|---|----------|----------|---------|
| S1 strong pin | 60, "Loss runs match insured", matched on name/fein/policy, pinned-at-60 card, NO carrier nag, ARQ drops availability questions | ALL of it, exactly - including the questionnaire suppression (no years question, no attestation question; the claims schedule table correctly remains) | **PASS - the client's literal 45->60 case, live** |
| S2 Path A + advisories | 85 with two advisory-prefixed cards | **50**, with the OLD messages ("High loss frequency: ... ", "Loss ratio ... - review with underwriter") | **STALE PROCESS** (see below) |
| S3 contradiction | capped 45, Conflicting state, conflict card + DC advisory | 45 + Conflicting + conflict card; DC advisory NOT seen | **PASS on the cap; DC card unconfirmed** - re-check after restart |
| S4 nothing + New Venture | 25, attestation card + New Venture card | Both cards, +9 pts measured on the New Venture card; flow (answer Yes -> N/A) not yet exercised | **PASS so far; flow steps pending** |
| S5 pending | 50 | **70**, old message path | **STALE PROCESS** |

**The stale-process proof, so nobody debugs a ghost:** S2's observed 50 is the
OLD arithmetic byte-for-byte (80 base + 10 carrier - 25 freq - 15 ratio) and its
card wording ("High loss frequency:", "- review with underwriter") **no longer
exists anywhere in the tree** - `grep -rn "review with underwriter|High loss
frequency" services/` returns zero hits. Same for S5's 70. The backend process
serving those runs predated the C2 edits; S1/S4 ran after a reload picked them
up. Action: restart the backend, re-run S2 / S3 / S5.

**Hand-verified from the same captures:** every package headline reproduces the
generic rescaled weighted sum exactly - S1: (89*.25+72*.25+100*.15+60*.15+40*.10)/0.90
= 75; S3: 68; S4: 68. `_weighted_pillar_sum` is doing on the live app what the
unit tests say it does.

**One real find, fixed from this run:** the S2 capture showed the advisory cards
offering "up to +8 pts" - the per-form loss-rec loop stamps a typed
`score_impact: 8` literal, impact measurement skips field-less recs so it never
got corrected, the chip contradicted the card's own "no score effect" text, and
dismiss-with-reason would have CREDITED those phantom points. Advisory and
informational New-Venture notices now carry `score_impact: 0` / priority 3 (the
frontend chip hides itself at 0 - verified, `!(pts > 0)` guard). Test:
`test_advisory_loss_cards_carry_zero_points` drives the real per-form scorer.

**Still to observe live after the restart:** S2=85 + prefixed advisories with no
pts chip; S5=50; S3's Data Consistency advisory ("held at 45") in the issues
panel; S4's three answer flows (New Venture Yes -> pillar N/A + both-N/A rescale
+ question suppression; attest no losses -> 60; had claims -> 25 + the new
loss-run availability select).

### C2-C SECOND LIVE RUN - scoring verified end to end; 3 fixes from the run (2026-08-24)

Round 2 after the backend restart, same `test_data_c2_loss/` packages:

| # | Expected | Observed | Verdict |
|---|----------|----------|---------|
| S2 | 85 + advisory-prefixed cards, no pts chip | **85 exactly**, both advisories correctly prefixed, **no pts chip** (C2-B fix verified live), state "Loss data reconciled" | **PASS** |
| S5 | 50 | **50**, "Loss runs requested / pending" | **PASS** (was 70) |
| S3 | capped 45 + DC advisory | **45 capped**, Conflicting state, conflict card. DC advisory not in the capture - offline probe proves it lands in the grouped view's **Warnings section** (renders, no cap; the advisory-severity-in-warnings-tier placement is pre-existing display behaviour shared with `unmapped_coverage_line`, noted, not changed) | **PASS on scoring; card location documented** |
| S4 Flow A | answer New Venture "yes" -> pillar N/A + rescale | Package headline went 68 -> **76 = EXACTLY the both-N/A rescale** ((73*.25+80*.25+100*.15+40*.10)/0.75) - the recompute WORKED - but the pillar row still read 25 and the state stayed stale. **Frontend partial-refresh bug, not scoring** | **Backend PASS; UI bug found + fixed (below)** |
| S4 Flow B | attest -> 60 | INVALID RUN - the answer was typed into the "contact info" card by mistake (the free-text answer box accepted it; `contact_name` has no validator - pre-existing looseness, noted) | re-run |
| S4 Flow C | had-claims answer -> 25 + availability select in ARQ | 25 held; pillar/state stale on screen for the same UI reason; the ARQ select appears on the Send-to-Client screen, which was not opened | re-check after fix |

**Three fixes from this run:**

1. **The answer path patched only the HEADLINE.** `/api/audit/answer` returned
   just `new_package_sqs_score` + per-form score/grade/tier, and
   `handleAnswerRec` patched exactly those - but an ANSWER changes FACTS, so
   pillar rows, loss-history state, category breakdown and recommendations all
   change too. The screen went internally inconsistent (package 76 beside a
   pillar row reading 25). Fixed at the class: the route now returns the full
   recomputed `package_sqs` and each form's full `new_sqs`; the frontend
   replaces them wholesale (guarded - older/partial responses keep the old
   patch behaviour). The identical block also existed in the DISMISS handler -
   patched there too, where the guard correctly makes it a no-op (dismiss
   changes credits, not facts, and its endpoint sends no full payload). This
   matches the established pattern - six other call sites already do
   `if (data.package_sqs) setPackageSqs(...)`.
2. **Loss-run carrier note false-positived on the ordinary renewal shape** (S2:
   run issued by the prior carrier -> "Carrier on the loss run does not match
   any carrier on the package"). `loss_run_identity._package_identity` now
   collects `prior_carrier` / `wc_prior_carrier` (per-doc AND merged facts)
   into the carrier bucket - a loss run normally comes FROM the prior carrier
   the package itself names. Both directions tested: prior-carrier run silent,
   genuinely foreign carrier still notes.
3. (From C2-B, verified live this round: advisory cards carry no pts chip.)

- tests: +2 in `test_loss_history_c2.py` (prior-carrier note both directions);
  focused suites green (128 passed); py_compile + esbuild parse clean.
- suite result: **3922 passed / 2 failed** - the same two pre-existing
  unrelated failures as every baseline (`test_arq_acord125_missing_only`,
  `test_normalization`), zero regressions from the round-2 fixes.

**Standing lesson re-confirmed:** round 1's S2/S5 "failures" were a STALE
BACKEND PROCESS - the old wording had zero grep hits in the tree. Verify the
process, not just the code, before debugging a live mismatch.

### C2-D THIRD LIVE RUN - ALL SIX CHECKS PASS; C2 CLOSED (2026-08-24)

Round 3 on the restarted backend + refreshed frontend. Every number below was
re-derived by hand from the rescaled weighted sum and matches exactly.

| Check | Observed | Sum check | Verdict |
|---|---|---|---|
| 1. Reopen the old S4 session | Loss History **N/A**, sub-row "Not applicable", package **78** | (80*.25+80*.25+100*.15+40*.10)/0.75 = 78.6 -> 78 | **PASS** |
| 2. Fresh S4, Flow A live | Pillar flipped to **N/A on the spot**, no reload; package **76**; the "New Venture confirmed" info card carries **no pts chip** (C2-B fix) | (74*.25+80*.25+100*.15+40*.10)/0.75 = 76.3 -> 76 | **PASS** - the full-payload refresh (C2-C fix) verified live |
| 3. Flow B on the correct card | Attestation -> **60**, "No Known Losses (attested by user)" card; package **73** | 66.5/0.9 = 73.9 -> 73 | **PASS** |
| 4. Flow C | Had-claims -> **25** with the NEW "Prior claims are known ... request loss runs" message; state refreshed live; Send-to-Client shows the NEW select "Loss run availability status" under Loss History; package **67** | 61/0.9 = 67.8 -> 67 | **PASS** - prior_claims_exist state + 2.10 injector verified |
| 5. S3 DC card | FOUND on the pre-form Review screen: "Data consistency: a No Known Losses attestation conflicts with claims found in the uploaded loss runs. Loss History is held at 45..." - in the Important cluster and under "Other validations" with Resolve/Dismiss | - | **PASS** - 2.6 routing verified live |
| 6. S2 re-upload | **85**, "Matched on: name, fein, policy number" with the carrier note GONE (C2-C prior-carrier fix verified); advisories prefixed, no pts chips | - | **PASS** |

**C2 is closed.** Every requirement 2.1-2.11 is implemented, unit-tested
(suite 3922/2 baseline) and now verified on the live application in all three
paths (A/B/C), both N/A rescaling shapes, the contradiction routing, the
questionnaire gating and all three producer-answer flows. Remaining items are
Brent's alone: Q11 (No-Runs-Available score), Q12 (statuses-unreadable
deduction), Q13 (never-insured established business), plus the older Q3a/Q3b
tier rulings - each a one-line swap in `calculate_p4_loss_history`.

**Known cosmetic quirk, documented not changed:** the advisory-severity DC card
renders inside the pre-form "Warnings" section (whose header says "Caps your
SQS at 85") and counts toward the warnings badge. It does NOT cap anything -
advisories never enter hard/soft stop lists. Pre-existing display behaviour
shared with `unmapped_coverage_line`; changing the grouped-view tiers touches
the toast counts globally and is not a C2 decision.

**Leftover in the owner's first S4 sandbox session:** the mis-aimed answer
("No - no claims...") recorded on the contact-info card is still there -
reversible via its Reopen button. The free-text answer box accepting arbitrary
text for a contact field is a pre-existing validation looseness, noted for C3
(verified-source gate work), not fixed here.

### C2-E BRENT'S RULINGS APPLIED - Q3a / Q3b / Q8 / Q9 / Q11 / Q12 / Q13 ALL CLOSED (2026-08-24)

Brent answered every open Loss History question in one pass, before testing.
His replies are quoted verbatim in the code at each decision point. Two were
confirmations, four changed behaviour, and **one was a correction to what C2-A
shipped** - recorded as such rather than quietly folded in.

| # | Ruling (verbatim) | What changed |
|---|---|---|
| Q3a DBA | *"Treat it as a verified match if the DBA is listed by the applicant and the EIN matches. That is enough to confirm the loss runs belong to the insured."* | A name matching a DBA **the applicant declared** is now a name match, and the ordinary tiers follow: DBA + FEIN/policy = `strong`, DBA + address = `moderate`, DBA alone = `possible` (note retained). `pkg["dba"]` only ever holds DBAs the package's own NON-loss-run documents state, so a trade name appearing solely on the run can never be promoted - test-pinned |
| Q3b FEIN, unknown name | *"Treat it as a probable match and ask for confirmation of the prior name or entity relationship."* | `no_match` -> **`moderate`**, note reworded to carry the confirmation ask |
| Q8 prior carrier from the dec | *"That's not really how brokers work. For now, skip shortcut and ask client. We'll pull something more concrete together with if/and/or."* | **Do not build it.** Nothing was built, so nothing to revert - Q8 closes as declined, and he will bring rules later |
| Q9 AI weights | *"Those assignments will do for now."* | 1.00 / 0.85 / 0.50 confirmed, no change |
| Q11 + the "N/A is not 0" correction | *"we can't treat 'N/A' as '0'. These are not the same. 'No known losses' is a legitimate answer ... If 'no known losses', check against the number of years in business."* 0-1 yr: *"will not have loss runs because the business is too young"*; 1-5 yr: *"a satisfactory answer would be 'no known losses' (or 'loss runs pending' ...) to get through a submission, though the submission would likely not bind without them"*; 5+ yr: *"loss runs are pretty much required"* | **The years-in-business ladder** (below). C2-A's "no runs available scores 25 like nothing provided" was WRONG and is corrected |
| Q12 unreadable claim details | *"Good ... V2"* | Confirmed: no deduction in V1; the per-claim extraction work is V2 backlog |
| Q13 never-insured business | *"Somewhat incorrect. To be safe, there probably shouldn't be a deduction here for now ... the applicant would be 'previously uninsured', which is very different from 'missing prior carrier'."* Example: a solo owner adding WC for the first time | **The -10 now requires positive evidence that prior coverage existed** |

**The years-in-business ladder.** `years_in_business_band()` in
`loss_history_state.py`; the 5+ / unknown column IS the client's own 2.5 table,
untouched, so a package whose years we cannot read scores exactly as it did.

| State | 0-1 yr | 1-5 yr | 5+ yr / unknown |
|---|---|---|---|
| No known losses attested | **Not Applicable** | **85** | 60 |
| Loss runs requested / pending | **Not Applicable** | **70** | 50 |
| No loss runs available | **Not Applicable** | **50** | 25 |
| "No losses" in narrative only | **Not Applicable** | **60** | 40 |
| Nothing said at all | 25 | 25 | 25 |

Three properties, all test-pinned:
* **Silence never buys N/A.** The 0-1 row requires an affirmative answer
  (attestation, pending, or "none available"); a blank questionnaire on a
  young business still scores 25. Blank-over-wrong survives the ruling.
* **The same contradiction guard as 2.2.** A loss-run document, a named prior
  carrier, recorded claims or a renewal flag all block the N/A, so a wrong
  `years_in_business` cannot silently delete 15% of the score.
* **2.5's ordering holds inside every band** - attestation > pending >
  narrative > nothing - asserted parametrically across all three bands.

**Prior carrier: three states, not two.** `prior_carrier_applicable()` now
returns False for a confirmed new venture, for an applicant who answered
"None" (`previously_uninsured()` - the curated question already invites exactly
that answer), AND when nothing in the package evidences that prior coverage
existed. The -10 survives only where a prior policy demonstrably existed (a
renewal, prior-policy facts, or uploaded loss runs) and the carrier is still
absent - which is the literal meaning of MISSING, and exactly Brent's
distinction.

**Blast radius.** Scores rise for: young businesses with a no-loss answer (now
N/A), 1-5 year businesses on any no-loss/pending/none-available answer,
DBA-filed loss runs (25 -> up to 100), FEIN-matched runs with an unexplained
name (25 -> 92 on Path A / 42 on Path B), and previously-uninsured or
new-business applicants (no -10). Nothing falls. 5+ year and unknown-years
packages are byte-identical to C2-A unless they carried one of the two
identity cases.

- files: `loss_run_identity.py` (tiers + note), `loss_history_state.py`
  (bands, `previously_uninsured`, `prior_coverage_evidence`,
  `loss_history_not_applicable`), `sqs_service.py` (ladder, carrier gate, N/A
  routing, labels), `AcordModal.jsx` (one new state label + provenance row).
- tests: +13 in `test_loss_history_c2.py` (64 total), each quoting the ruling
  it pins, plus the negative controls - trade-name-only-on-the-run stays
  no_match, silence still scores 25, a contradicted young business still
  scores, and the band ordering holds parametrically.
- suite result: **3950 passed / 4 failed -> 3 of those 4 were STALE TESTS, now
  corrected.** `test_v1_c1_canonical_facts.TestLossRunIdentity` pinned the
  pre-ruling defaults - one of them says so in its own docstring (*"Q3a is
  open: engineering default is the spec's own verdict"*). The TEST was wrong,
  not the code: Brent closed Q3a/Q3b, so `no_match` is no longer the answer.
  Rewritten to assert the RULINGS, and each kept its protective intent:
  `test_a_different_entity_TYPE_is_not_a_name_variation` still proves LLC vs
  Company never reads as one NAME (only the tier moved), and two new guards pin
  that a DBA with no identifier stays `possible` and a trade name the applicant
  never declared stays `no_match`. **Confirming re-run after the corrections:
  3955 passed / 1 failed** - the single pre-existing
  `test_arq_acord125_missing_only` (`test_normalization` was fixed elsewhere
  this session, so the baseline is now ONE). Zero regressions.

**Fixture set extended for the rulings** (`test_data_c2_loss/`, 16 PDFs):
S6 = loss run under a DECLARED DBA with a matching tax ID (expect `strong`,
100); S7 = tax ID matches, insured name is a former name found nowhere else in
the package (expect `moderate`, 92, confirmation note); S8 = a 3-year-old
business with zero loss documents (25, and 85 once attested - where a 5+ year
business reaches only 60); S9 = loss runs with no prior carrier named anywhere
(90, and 100 once the card is answered "None"). The generator self-checks the
properties each scenario depends on - S6's DBA must be on the applicant's own
paper, S7's former name must NOT be, S9 must name no carrier, S8 must carry no
loss vocabulary - so a fixture defect fails at generation instead of mid-run.
**Expected numbers were produced by running the real scorer against each
scenario's fact shape, not estimated** - but that is a FUNCTION probe, not a
SEAM probe (D22): only the live upload proves extraction feeds it correctly.

**Still open, and only these:** nothing on Loss History. Brent's "We'll pull
something more concrete together with if/and/or" on prior carrier (Q8) is a
future input from him, not a blocker. The 1-5 band's exact numbers (85 / 70 /
50 / 60) are OUR derivation from his structure using values already in his own
spec - flagged to him as an assumption, not presented as his ruling.

### C2-F FREE-TEXT ANSWERS - the producer card is a TEXT BOX, not a select (2026-08-24)

**Owner's question, and it was right:** *"if user types something different than
this but it means same will it also be applicable ... just in case if you have
hardcoded it."* Probed all four C2 parsers against the phrasings a real
producer would type. Four genuine holes, all fixed:

| Field | Answer that SILENTLY did nothing | Now |
|---|---|---|
| Attestation | **"None"**, "Nil", "Nothing", "Zero claims", "0 claims", "loss free", "claims-free", "clean loss history" | attests |
| Prior carrier | "First time buying insurance", "No prior coverage - new to insurance", "Never carried insurance" | previously uninsured |
| Loss-run status | "Ordered", "We have ordered them", "awaiting receipt", "in progress", "expected next week", "Carrier cannot provide them" | pending / no-runs |
| New venture | "brand new operation", "just started trading", "newly formed" | confirms |

**Why this mattered.** The client questionnaire offers a two-option SELECT, so
it was safe. The producer's recommendation card is a free-text box - and the
round-3 run showed the owner typing a curated option string by hand. Anyone
typing the obvious one-word answer ("None") got no score movement and no
explanation, which reads as the feature being broken.

**The fix reuses the door that already exists.** Free text now routes through
`normalization.detect_no_loss_assertion` - the SAME detector the ACORD
LossHistory checkbox and the narrative scan use - so the three surfaces cannot
disagree, and its threshold guard comes along free. A second phrase list would
have been a fifth comparison site.

**A pre-existing bug found by the probe and fixed:** `attested_true("no losses
exceed $10,000")` returned **True** - a THRESHOLD statement (losses exist, none
above a cap) read as an attestation. `detect_no_loss_assertion` has always
refused it, but the loose legacy fallback (`"no " in s and "loss" in s`)
re-admitted it underneath. Same guard now applies to the fallback.

**Two deliberate NON-changes, both the safe direction:**
* A bare **"No"** still does NOT attest. On this fact it carries the legacy
  meaning *"no, we HAVE had losses"*; inverting it would silently re-label every
  answer stored before the curated wording shipped. Test-pinned both ways.
* A bare **"new business"** does NOT confirm a new venture. On an ACORD
  submission that is the TRANSACTION TYPE - a 20-year-old company changing
  carriers is "new business" too - and reading it as a new VENTURE would remove
  the pillar for an established insured. Unrecognised text returns None, which
  scores normally.

- files: `services/loss_history_state.py` (all four parsers).
- tests: +59 parametrised cases in `test_loss_history_c2.py` (132 total),
  including the negative controls - real carrier names never read as
  "uninsured", threshold statements never attest, and "No loss runs have been
  REQUESTED" reads as an availability answer rather than pending (ordering).
- suite result: PENDING-AT-WRITE.

**Standing lesson:** every one of these parsers was written against the curated
option text and tested against it. The option text is what the QUESTIONNAIRE
sends; the CARD sends prose. Any future two-state answer needs both paths
tested, or a select on the card - which is the better structural fix and is
noted for C4.

### C2-G ANSWER SEMANTICS - one deterministic door for every human answer (2026-08-24)
**Priority:** V1-CRITICAL (scoring integrity)
**Principle(s) touched:** 3 (absence is not evidence), 6 (auditability)

**Owner's instruction:** *"check this over all such cases, including all
recommendations / hard stops / warnings that user answers ... build it so it can
judge the MEANING rather than depending on hardcoded fixed answers, and remember
the user can answer in any manner."*

**The measured defect, and it was worse than synonyms.** Typing **"N/A" into
every Tier-2 field scored 100** - identical to a fully answered submission.
"unknown" for sprinklers / roof year / fire class still scored COPE at 80.
Meanwhile a legitimate **"None" scored as a GAP**, because "none" sits in
`_EMPTY_VALUES`. Both directions wrong from ONE root cause: *"what is the
value?"* and *"did they answer?"* were the same test, `bool(value)`.

**Root cause.** Three different meanings collapsed into one stored string:

| Meaning | Example | Was | Now |
|---|---|---|---|
| VALUE | "Travelers" | stored | stored (canonicalized) |
| ABSENCE - a real answer | "None", "never had coverage" | penalised as a gap | `value=""` + `explicit_no`, **counts as answered** |
| NON-ANSWER | "TBD", "don't know", "N/A"* | **counted as filled data** | refused at the gate, never stored |

\* "N/A" is `not_applicable` - an ANSWER, per Brent (*"we can't treat 'N/A' as
'0'. These are not the same."*). Only genuine uncertainty is refused.

**Fix - `services/answer_semantics.py`, the ONE door.** Every path a human
answer can take now goes through it: the producer recommendation card, inline
issue/hard-stop/warning resolution (`RESOLUTION_MAP` field mode - 39 facts) and
the client questionnaire.

**Why this is not a list of accepted answers.** It encodes **how English
expresses four ideas**, applied identically to all 175 facts - adding a fact
needs no entry here, which is the test of whether it generalises:
negative existence / uncertainty / inapplicability / affirmation-denial. What a
given field ACCEPTS comes from the field's OWN declaration
(`arq_service._FIELD_INPUT_TYPE` first, then the registry's format hint), never
from a per-field synonym list.

**Precedence is where meaning is actually judged** - a keyword scan cannot do
any of these, and each is test-pinned:
* uncertainty BEFORE negation - *"no idea"* contains "no" but means unknown
* a parseable value BEFORE negation - *"0"* employees is a VALUE, not an absence
* negation needs SCOPE - carrier *"Nationwide"* is never read as "no", and a
  long descriptive sentence containing *"do not perform work above three
  stories"* stays a value
* NEGATIVE-POLARITY facts invert it - on `loss_history_no_prior_losses_
  indicator` the fact's own NAME asserts an absence, so "None" FILLS it.
  Detected from the key's shape, so a future `no_known_subcontractors` works
  the day it is added; the existing readers (`attested_true`) are untouched.

**Numbers and dates however a person writes them:** "five"/"twelve"/"twenty
five", "about 12", "~9", "$2M"/"2m"/"2mm"/"2 million"/"1.5k"/"3bn",
"2,000,000", "July 15 2026"/"15 July 2026"/"2026-07-15". Language-level
parsing, so it serves every numeric and date fact at once.

**NO LLM - owner's call, and the reasons that matter are not tokens.** A
classification call is ~0.03% of a submission's measured LLM spend. The real
costs are (a) an interactive click waiting on a round trip and (b) a scoring
input that could differ between two runs of the same answer.
`unresolved_answers()` logs every answer the deterministic rules could not
read, so coverage is MEASURED rather than assumed - if that log fills with real
phrasings we extend the rules with evidence.

**Three real bugs found in my own code by the existing suite - all fixed:**
1. **Identifier codes were numerically coerced.** `fein "84-2210987"` became
   `84` and was then refused by its own validator. An identifier is a STRING of
   digits, not a quantity; `code` is now a kind that is never coerced.
2. **The documented monetary leniency broke.** "Not covered" / "Waived" /
   "Statutory" / "See schedule" were refused. An amount answer with NO digits
   is legitimate descriptive data (mirrors `pdf_service._rejects_declared_
   type`'s permissive-by-default rule); only an answer that HAS digits and
   still will not parse is refused. Extended to percent-typed boxes too, which
   is what the earthquake-deductible case exposed.
3. **A malformed number was silently truncated.** "12.34.56" became `12`. The
   leading-number path now requires the remainder to be prose.

**Blast radius.** `check_tier1`, `check_tier2` and the category-breakdown `_ok`
now ask ANSWERED (`_answered`) instead of HAS-A-VALUE; `_fact_is_filled`
delegates to `fact_answered`. Value-semantics reads are untouched and still see
an empty value for an absence - so `has_carrier`-style checks stay correct
while completeness stops penalising a legitimate "none". Every wiring point is
wrapped so a failure falls back to today's behaviour.

**Scores move BOTH ways, which is Brent's distinction working:** UP where a
legitimate "None" was penalised; DOWN where "TBD"/"N/A" was credited as data.
D6 applies - tell Brent before he sees it.

- files: NEW `services/answer_semantics.py`; wired in `routes/audit_routes.py`
  (`_validate_producer_answer`), `services/arq_service.py` (both apply paths),
  `services/sqs_service.py` (`_fact_is_filled`, `_answered`, `check_tier1`,
  `check_tier2`, `_ok`).
- tests: NEW `tests/test_answer_semantics.py` (141), plus the reshaped
  `test_loss_recommendation_routing_20260817.py` - its old cases pinned
  "reject words", which the semantic layer deliberately replaces with
  "understand words"; the protection that MATTERS (text never silently
  becoming a bogus 0) is now asserted directly.
- suite result: **4030 passed / 1 failed** - the single pre-existing
  `test_arq_acord125_missing_only`. Zero regressions.

**Known / deliberately not done.**
* Extraction can still write "N/A" into a fact - this closes the HUMAN answer
  path, which is where the reported problem lives. An extraction-side pass
  would be a separate, prompt-touching change (improving-ll.md rule).
* The producer card is still a free-text box. A select on two-state answers
  would make a wrong answer structurally impossible; noted for C4 as the
  better fix, not bolted on here.

### C2-H ANSWER OPTIONS - offer the choices wherever the answer set is knowable (2026-08-24)
**Priority:** V1-CRITICAL (answer quality)

**Owner's instruction:** *"Look for every answer that we are expecting, we need
to give all possible option that a user can think of answering"* - modelled on
the dismiss-reason dropdown (screenshot: every realistic reason, ending in
**Other**). Free typing stays for *"names, phone, email, amounts, dates, codes,
percentages"*.

**Why a dropdown beats a text box here.** C2-G taught the lesson: understanding
prose will always be a rearguard action. The real fix is not to ASK for prose
when the answer set is knowable. C2-G stays underneath as the safety net for
"Other", for legacy stored answers, and for extraction - the two are
complementary, not alternatives.

**The full surface, measured, not guessed: 90 answerable facts** across
recommendations, hard stops and soft stops (`RESOLUTION_MAP` field mode + the
loss rec table + Tier 1/2 + every `"field":` a scorer emits + the questionnaire
map). **69 stay free text / typed; 20 now offer choices.**

**`services/answer_options.py`** is the catalogue. Three rules every list follows:
1. **The option TEXT is the stored value** - no hidden codes, no mapping table
   to drift (the contract `_NO_LOSS_OPTIONS` has proven since 2026-08-17).
2. **Every list ends with "Other"**, which drops to free text. The only two
   exceptions are the genuinely binary questions (attestation, new venture) -
   "Other" on "have you had claims, yes or no?" would be nonsense.
3. **Options read as an ANSWER a person gives**, never a schema token.

Lists added: entity type (13), lines of business (15, multi), construction type
(ISO's six classes), occupancy (17), valuation method, sprinkler, ISO protection
class 1-10, period of restoration, agreed value, GL form type, umbrella
follow-form, vehicles-return, WC officer exclusions, additional insureds
(multi), covered-auto symbols (multi). The auto symbols are **read from
`services/auto_symbols.py`** - ACORD's own tooltip wording, harvested in the
2026-08-07 work - so the dropdown can never drift from the definitions the
validators reason over. The five option sets that already existed
(`_NO_LOSS_OPTIONS`, `_CARRIER_MARKETING_OPTIONS`, `_FOLLOW_FORM_OPTIONS`,
`NEW_VENTURE_OPTIONS`, `LOSS_RUN_STATUS_OPTIONS`) are REFERENCED, never copied.

**Where a dropdown would be WRONG, and is deliberately not offered.** Carrier
names, class codes and NAICS/SIC have universes in the thousands and change
constantly - forcing a list makes "Other" the usual answer, which is worse than
typing. Those keep free text (NAICS already has the Figure 20 suggester chips:
suggest, never constrain).

**One hazard found and closed while building it.** Options such as *"No - all
owners and officers are included"* and *"Not stated - underwriter review
recommended"* were being re-read by C2-G as an ABSENCE and a NON-ANSWER. An
option chosen from the field's own list is BY DEFINITION a value, so
`interpret_answer` now matches the fact's declared options FIRST and returns
the catalogue's exact wording. `test_every_option_round_trips_as_its_own_value`
pins all 20 lists - a reworded option that stops reading back as itself fails
the build.

**Wired at three points**, each additive and exception-wrapped:
* `sqs_service.calculate_sqs` - every answerable recommendation card now ships
  `answer_options` / `answer_control` / `answer_multi`.
* `arq_service._attach_answer_options` - both question generators; a curated
  `select` that already carries its own options is left untouched.
* `AcordModal` - the producer card renders a choice list when the card carries
  options, with "Other" revealing free text (the same control the dismiss
  reasons have used all along), and falls back to today's text box otherwise.

- files: NEW `services/answer_options.py`; `services/answer_semantics.py`
  (declared-option match), `services/sqs_service.py`, `services/arq_service.py`,
  `frontend/src/components/form/AcordModal.jsx`.
- tests: NEW `tests/test_answer_options.py` (102) - round-trip on every option,
  an escape on every list, normalizer survival (entity types must not collapse
  onto one canonical token; RCV/ACV must still resolve), the loss controls still
  driving the pillar, and the negative controls that keep names/amounts/dates/
  codes OUT of dropdowns.
- suite result: **4273 passed / 1 failed** - the single pre-existing
  `test_arq_acord125_missing_only`. Zero regressions.

**Known / deliberately not done.**
* The inline ResolutionModal (hard stop / warning "Open to fix") still renders
  its own inputs; it should read `control_for()` the same way. Same metadata,
  one more render site - next increment.
* `prior_carrier` is the one hybrid worth building later: free text, but with
  an explicit "none - previously uninsured" choice, since that state cannot be
  expressed by typing a carrier name. C2-G understands it as prose today.

### C2-I HARD / SOFT STOPS GET THE CHOICES TOO + TWO STANDING GAPS (2026-08-24)

**The gap C2-H left, now closed.** Recommendation cards gained answer choices,
but a hard stop or warning resolved inline renders through a DIFFERENT path -
`ResolutionModal`, driven by `resolution.facts` - and it was still drawing a
bare *"Type the correct value..."* box for every fact. Fixed at
`issue_registry._copy_resolution`, the ONE function every resolution is copied
through (RESOLUTION_MAP, tier-1, legacy message fallback), so no render path
can be missed. `_tier1_resolution` was returning `_r_field(...)` directly and
bypassing it - now routed through the same door. Each fact carries
`{control, options, multi}`; the modal renders a select when options exist,
with "Other" revealing free text.

Verified live-shape: `minimum_viable_cope_missing` now offers occupancy (17)
and construction (6) as lists with the two values as typed money inputs;
`carrier_grade_cope_incomplete` offers sprinkler (3) and protection class
(1-10) as lists with year built / roof year typed.

- tests: +3 in `test_answer_options.py` - every field-mode resolution in
  RESOLUTION_MAP carries controls (25+ checked), tier-1 does too, and the COPE
  hard stop offers the real lists while amounts stay typed.
- suite: **4276 passed / 1 failed** (the pre-existing one). Zero regressions.
- fixture: `test_data_c2_loss/10A_property_dec_incomplete_cope.pdf` - a
  property submission with deliberately incomplete COPE, because none of the
  loss scenarios carry property coverage and the richest dropdowns were
  therefore untestable.

---

## STANDING GAPS - ANSWER INTERPRETATION (opened 2026-08-24, C2-G..C2-I)

**Read this before assuming the answer path is airtight.** Two things are
knowingly NOT covered. Both are real, both are cheap to forget, and neither is
a reason to distrust what shipped - they bound it.

### GAP 1 - extraction writes facts WITHOUT interpretation

`answer_semantics` sits on the HUMAN answer path only: the producer card, the
inline hard-stop / warning resolution, and the client questionnaire. **The
extraction pipeline writes `facts[key]` directly.** So if the LLM extracts the
literal string `"N/A"`, `"unknown"` or `"TBD"` out of a document, it is stored
as a VALUE and counts as data everywhere - exactly the defect C2-G measured on
the human path (typing "N/A" into every Tier-2 field scored 100).

* **Why it was left:** the reported problem was the human path, and closing the
  extraction side means either a post-merge normalisation pass over every fact
  or a prompt change - the latter is an `improving-ll.md` event with a cost and
  a cache-invalidation cost. Not something to bolt onto this arc.
* **The cheap version if it ever bites:** run `interpret_answer` over merged
  facts at the end of `merge_facts` and demote UNKNOWN intents to
  `value_state: not_stated` WITHOUT touching the stored value. Deterministic,
  no prompt change, no LLM cost.
* **How you would notice:** a submission scoring far better than its documents
  justify, with fields whose displayed value reads "N/A" or "unknown".

### GAP 2 - `unresolved_answers()` must be WATCHED, not assumed

The owner declined an LLM interpretation layer (2026-08-24) on latency and
determinism grounds, not cost. `answer_semantics._record_unreadable` is what
keeps that decision honest: **every answer the deterministic rules could not
read is logged** (INFO, `answer_semantics: could not read ...`), and
`unresolved_answers()` returns the last 200.

* **That log is the evidence base for extending the rules.** If it stays empty,
  the deterministic approach is proven. If it fills with real phrasings, we
  extend the patterns WITH EVIDENCE instead of guessing - or revisit the LLM
  decision with data.
* **Nobody is watching it yet.** There is no dashboard, no alert, no periodic
  review. It is an in-memory list that dies with the process.
* **The cheap version:** persist it, or grep production logs for
  `answer_semantics: could not read` after a week of real use and read what
  comes back.

### C2-J FOURTH LIVE RUN (S1-S10) - 7 PASS, 3 REAL BUGS, ALL FIXED (2026-08-25)

Owner ran all ten scenarios. **Every Brent ruling scored correctly**; the three
failures were all in the SEAM around the scorer, which is the D22 lesson again.

| # | Result |
|---|---|
| S1 | **PASS** 60, "Loss runs match insured", matched name/fein/policy |
| S2 | **PASS** 85, advisories with NO points chip, carrier note gone (C2-C fix live) |
| S3 | **PASS** 45 capped, Conflicting, DC warning on the Review screen |
| S4 | **PASS** all three flows - run a N/A, run b N/A (the years-band ruling), run c 25 + the availability select |
| S5 | **PASS** 50 |
| S6 | Pillar **100** with **"Matched on: dba name, fein, policy number"** - Brent's Q3a ruling works - **but a HARD STOP capped the package at 60** (BUG 2) |
| S7 | Pillar **92**, "probable match" note verbatim - Q3b works - hard stop correct here (see below), **but the card text was backwards** (BUG 3) |
| S8 | **PASS** 25 -> 85 |
| S9 | **BUG 1** - answered "no", then "none", nothing moved (76 -> 76 in the logs) |
| S10 | Dropdowns confirmed live on both loss cards ("Select an answer..."); COPE hard stop + 4 cross-form issues fired. One modal defect (below) |

**BUG 1 - MINE, and the exact class the owner warned about.** C2-G started
storing an absence as an EMPTY value carrying `value_state: explicit_no`.
C2-E's `previously_uninsured()` still read the value TEXT, found `""`, returned
False - so the -10 stayed and the producer's answer visibly did nothing. **Two
mechanisms I built in the same session disagreed about where the meaning
lives.** Fixed: the state is authoritative, checked before the text. Verified
across "no" / "none" / "None" / "never had coverage" / "N/A" -> 90 -> 100, and
a named carrier still reads as insured.

**BUG 2 - the DBA ruling was being undone one layer up.** The loss-run matcher
scored S6 exactly as Brent ruled, while `check_doc_consistency` raised
*"Applicant name differs across documents: CASCADE FREIGHT INC, CF Logistics"*
- a HARD STOP capping the submission at 60 for a trade name **the applicant
declared on their own application**. One package asserting both things at once.
Fixed in the name-conflict collector.

**The first version of that fix was wrong and the suite caught it.** Dropping
any value that matches a declared DBA also dropped the LEGAL name, because a
DBA is usually a prefix of it ("Orbin" for "Orbin Contracting LLC") - which
silenced a genuine two-company conflict
(`test_doc_consistency_messages_have_no_code_or_list_leak`). The correct rule
needs BOTH halves: a value is a trade name only when some document declares it
as a DBA **and that same document gives a different legal name**. Negative
controls pinned: a real third party still hard-stops.

**S7's hard stop is CORRECT and was left alone.** Brent ruled the SCORE is a
probable match (92); he did not rule the identity conflict away, and the spec
lists *"Applicant legal name differs across uploaded documents"* as a
cross-document hard stop. Both are true at once by design - test-pinned so
nobody "fixes" it later.

**BUG 3 - the `moderate` card asserted the wrong identifiers.** It read *"name
and address match but FEIN/policy number not confirmed"* on S7, where the FEIN
DID match and the name did not - backwards. `moderate` now has two causes
(name+address, and Brent's Q3b), so the message names neither; the panel note
carries the specific reason. Routing phrase preserved.

- tests: +6 in `test_loss_history_c2.py` (138), each driving the live scenario.
- suite: **4282 passed / 1 failed** (the pre-existing one). Zero regressions.

**STILL OPEN - S10 ResolutionModal follow-up (not fixed, reported).** Applying
a value that raises a NEW issue shows *"You can settle it here - fill in
Occupancy Type / Construction Type / Property Bpp Value above and apply
again"*, but the modal's input list does NOT refresh to the new issue's facts -
only the original two were rendered - and the submit then errors *"Enter at
least one value."* The message names fields the form does not show. Pre-existing
in the follow-up flow (`ResolutionModal`), unrelated to the answer-controls
work, and it is a dead end for the producer. Next increment.

### C2-K THE RESOLUTION FOLLOW-UP DEAD END - ROOT CAUSE AND FIX (2026-08-25)

**Reported (S10 live run):** applying Building Value + BPP Value on the
Minimum-Viable-COPE modal returned *"You can settle it here - fill in Occupancy
Type / Construction Type / **Property Bpp Value** above and apply again"*, and
the re-apply then refused with *"Enter at least one value."* A dead end.

**ROOT CAUSE - a remediation list that never checks what is already provided.**
`audit_routes._trade_off_note` built its "fill in ..." list as
*the new issue's facts ∩ the facts on this screen, minus the ONE field this
request applied*. Two consequences, and the second is the dead end:
1. The producer applies several fields; each is a separate POST, so only the
   LAST is excluded - every other field they just filled is still named. Hence
   "Property Bpp Value", which they had entered seconds earlier.
2. Being told to fill something already filled, the natural move is to press
   Apply again without typing. `applyField` only submits TOUCHED fields (a
   deliberate rule - see its comment), `touched` is cleared when the note
   shows, so nothing is submitted and the modal answers "Enter at least one
   value." **The message asked for work that was already done, then punished
   doing nothing.**

**Fix - name only what is STILL MISSING, judged against the post-apply session
facts.** `_trade_off_note` now takes the session's facts and filters through
`_fact_is_filled`, so it reflects what is genuinely on file - which also covers
a value that arrived from a document or an earlier field in the same batch,
not just this request's own write. And because `_fact_is_filled` is
answered-aware since C2-G, a producer who answered **"None"** is not asked
again either. When nothing on the screen is still missing it stops promising a
fix it cannot deliver and says *"Resolve it from the validation panel when you
are ready."*

**Second half - the form was stale while being told to "apply again".** The
modal held its pre-apply snapshot, so the values that had just landed were not
visible. `ResolutionModal` now re-reads the session (`prefillNonce`) when a
follow-up note appears. `touched` still clears, which is correct: only a fresh
edit should re-submit.

**Checked for the same class elsewhere, as asked.** The pre-form screen's
"Needs client input" list comes from `check_tier2`, which C2-G already routed
through the answered-aware predicate - so an absence answer no longer appears
there as a gap. The other remediation strings (`minimum_viable_cope_missing`
etc.) compute their "missing:" list inside the rule from live facts, so they
cannot name a satisfied field. `_trade_off_note` was the one builder that
enumerated facts WITHOUT consulting them.

**A brittle test corrected, not worked around.**
`test_the_note_is_advisory_and_never_fails_the_write` asserted on a fixed
±400-character window around the call; adding two lines pushed the "non-fatal"
guard out of view and failed a test whose subject had not changed. Rescoped to
the ENCLOSING try/except and strengthened (the guard must also never re-raise,
or the successful write would be lost).

- files: `routes/audit_routes.py` (`_trade_off_note` + its call site),
  `frontend/src/components/form/ResolutionModal.jsx` (prefill refresh).
- tests: +5 in `test_issue_resolution.py` including the S10 literal case, the
  nothing-left-to-fill case, and the absence-counts-as-provided case.
- suite: **4287 passed / 1 failed** (the pre-existing one). Zero regressions.

### C2-L FIFTH LIVE RUN - the SECOND and THIRD copies (2026-08-25)

S9 passed. S10's follow-up note is fixed (the modal now shows Occupancy and
Construction as dropdowns with the two amounts pre-filled). S6 and S7 each
exposed **another copy of the thing I had just fixed** - the defect signature
this codebase keeps producing.

**S6 - the DBA ruling was enforced in ONE engine, and the package immediately
raised the same hard stop from the OTHER.** C2-J fixed
`sqs_service.check_doc_consistency`; the live run then produced *"Applicant /
Named Insured: documents disagree (CASCADE FREIGHT INC, CF Logistics)"* from
`underwriting_consistency` - the Data Consistency reconciler, a completely
separate path. Same question, two engines, one fixed.

**Fixed by giving the rule ONE OWNER**, not by patching the second site:
`fact_comparison.is_declared_trade_name(value, docs, ctx)` now holds it (the
same door decision D3 made for every other comparison), and BOTH sites ask it -
`check_doc_consistency` and a new `_drop_declared_trade_names` filter in
`underwriting_consistency`, built on the existing `_drop_foreign_line_values`
pattern. `test_the_trade_name_rule_has_exactly_one_owner` pins the rule
directly, including the prefix guard ("Orbin" must never swallow "Orbin
Contracting LLC"), and the negative control now asserts on BOTH engines.

**S7 - a THIRD copy of the backwards message.** C2-J replaced two occurrences
of *"name and address match but FEIN/policy number not confirmed"*; a third
lived on the Path A insured-match adjustment and was what the live run
actually printed. Now grep-guarded:
`test_no_copy_of_the_backwards_moderate_message_survives` asserts the wording
exists NOWHERE in `sqs_service`, so a future copy fails the build rather than
surfacing on a client screen.

**Standing lesson, third time in this arc.** Fixing the site that produced the
symptom is not fixing the defect. Both of these were found only because the
owner re-ran the same scenario after the "fix" - `replace_all` reported success
on two matches while a third existed, and one engine went quiet while its twin
kept talking. **Grep for the rule, not for the message; and when two subsystems
answer the same question, give the answer one owner.**

- files: `services/fact_comparison.py` (new `is_declared_trade_name`),
  `services/underwriting_consistency.py` (`_drop_declared_trade_names`),
  `services/sqs_service.py` (uses the shared rule; third message copy).
- tests: +4 in `test_loss_history_c2.py` (142) - both engines, both directions,
  the prefix guard, and the grep guard.
- suite: **4291 passed / 1 failed** (the pre-existing one). Zero regressions.

### C2-M SIXTH LIVE RUN - S6 AND S7 CONFIRMED, C2 CLOSED (2026-08-25)

| # | Before | After | Verdict |
|---|---|---|---|
| S6 | form 60 D / package 60, "Hard stops need attention" | **form 83 B / package 80, NO hard stop**, Loss History 100, "Matched on: dba name, fein, policy number" | **PASS** - both engines now honour Brent's Q3a ruling |
| S7 | card read "name and address match but FEIN/policy number not confirmed" | card reads **"confirm the run belongs to this insured (see the note on the Loss History panel)"**; Loss History 92; the hard stop correctly REMAINS | **PASS** |

Package arithmetic re-derived by hand from the observed pillars, both exact:
S6 `(80*.25 + 72*.25 + 100*.15 + 100*.15 + 40*.10) / 0.90 = 80`.
S7 raw `(74*.25 + 72*.25 + 100*.15 + 92*.15 + 40*.10) / 0.90 = 77`, displayed
**60** under the applicant-name hard stop - the ceiling working exactly as the
owner's rule requires (raw preserved, only the display capped).

**Score movement to tell Brent:** a package whose loss run is filed under the
insured's declared DBA was losing **20 points** to a false identity hard stop
(60 -> 80 on this fixture). Add it to the D6 list alongside the other C2
movements.

**C2 IS CLOSED.** All eleven clauses (2.1-2.11) implemented, all seven of
Brent's rulings applied, and every one verified on the live application across
six runs. Nothing in the Loss History workstream is open. The remaining
follow-ups are logged elsewhere and are not C2: the two STANDING GAPS on
answer interpretation (extraction-side values, and watching
`unresolved_answers()`), and the ResolutionModal control parity noted in C2-H.

---

## BRENT'S RULINGS - ALL CLOSED (received 2026-08-24, live-verified 2026-08-25)

**Read this before reopening anything in Loss History.** Brent answered every
outstanding question in one reply, before testing. Each is recorded verbatim,
with where it lives in code and how it was proven. Nothing here is awaiting a
decision.

| # | Brent, verbatim | What it means in code | Proven by |
|---|---|---|---|
| 1 | *"DBA + matching EIN: Good suggestion. Treat it as a verified match if the DBA is listed by the applicant and the EIN matches. That is enough to confirm the loss runs belong to the insured."* | A name matching a DBA **the applicant declared** is a name match; the ordinary tiers follow (`loss_run_identity`). The rule that decides "is this the insured's own trade name?" has ONE owner, `fact_comparison.is_declared_trade_name` | **S6 live:** Loss History **100**, *"Matched on: dba name, fein, policy number"*, form 83 / package 80 |
| 2 | *"Matching EIN + unknown name: Treat it as a probable match and ask for confirmation of the prior name or entity relationship. The EIN match is strong evidence, but the unexplained name should still be verified."* | `no_match` -> **`moderate`** (92 on a clean 5-year run), plus a note carrying the confirmation ask | **S7 live:** Loss History **92**, note printed verbatim, *"Matched on: fein, policy number"* |
| 3 | *"Prior carrier: That's not really how brokers work. For now, skip shortcut and ask client. We'll pull something more concrete together with if/and/or."* | **Do not build it.** Nothing was ever built, so nothing to revert - we keep asking the client. Q8 closes as DECLINED; he will bring rules later | n/a - nothing shipped |
| 4 | *"AI confidence: Those assignments will do for now."* | 1.00 / 0.85 / 0.50 stand unchanged. The only movement is the separate `ai_verified` 0.00 defect fix (C1-S) | n/a - no change |
| 5 | *"we can't treat 'N/A' as '0' ... 'No known losses' is a legitimate answer ... If 'no known losses', check against the number of years in business."* 0-1 yr *"too young"*; 1-5 yr *"a satisfactory answer"*; 5+ yr *"loss runs are pretty much required"* | **The years-in-business ladder** (`loss_history_state.years_in_business_band`). This CORRECTED what C2-A shipped | **S4 live:** run a and run b both -> **N/A**. **S8 live:** 25 -> **85** on a 3-year business |
| 6 | *"Good. When a loss run's years are readable but the claim statuses and amounts aren't, we don't deduct anything extra for that. V2 - Adding it would mean reading claim-by-claim details from every carrier's layout"* | Confirmed: no V1 deduction. The per-claim extraction work is **V2 backlog**, not a gap | n/a - confirmed as shipped |
| 7 | *"Somewhat incorrect ... there probably shouldn't be a deduction here for now ... the applicant would be 'previously uninsured', which is very different from 'missing prior carrier'."* | The -10 now needs POSITIVE evidence that prior coverage existed (a renewal, prior-policy facts, or uploaded runs), and an applicant who answers "None" is `previously_uninsured` and never deducted | **S9 live:** answering the card **None** moved Loss History **90 -> 100** |

### The ladder his ruling 5 produced

The 5+ / unknown column IS the client's own 2.5 table, untouched - so a package
whose years cannot be read scores exactly as it did before.

| State | 0-1 yr | 1-5 yr | 5+ yr / unknown |
|---|---|---|---|
| No known losses attested | **Not Applicable** | **85** | 60 |
| Loss runs requested / pending | **Not Applicable** | **70** | 50 |
| No loss runs available | **Not Applicable** | **50** | 25 |
| "No losses" in narrative only | **Not Applicable** | **60** | 40 |
| Nothing said at all | 25 | 25 | 25 |

Three properties, all test-pinned: **silence never buys N/A** (the 0-1 row needs
an affirmative answer); **the same contradiction guard as 2.2** blocks the N/A
when a loss run, prior carrier, claims or a renewal flag says otherwise; and
**2.5's ordering holds inside every band** (attestation > pending > narrative >
nothing).

### What his ruling 7 does and does NOT model - stated honestly

Brent's example is *"a solo-owner adding employees for the first time ... adding
a new line for workers comp"*. Both readings of that example are covered by the
single `prior_carrier` fact:
* a business with **no prior insurance at all** answers "None" -> previously
  uninsured -> no deduction;
* a business that **already carries GL** and is adding WC names its GL prior
  carrier -> the fact is filled -> no deduction either way.

**Not modelled:** prior carrier PER LINE of business. There is one
`prior_carrier` fact (plus `wc_prior_carrier`), not one per line, so Primble
cannot express "has a GL carrier, none for WC". No reported defect needs it, and
Brent's own example does not - but if the per-line prior-carrier work he
mentioned ("something more concrete together with if/and/or") lands, this is the
fact model it would change.

### The exact numbers that are OURS, not his

Ruling 5 gave the STRUCTURE (three bands, what is satisfactory in each) but no
numbers. The 1-5 column above - 85 / 70 / 60 / 50 - is our derivation, built
only from values already in his own 2.5 table. Flagged to him as an assumption
in `20Aug_questions_brent.md`, not presented as his ruling. If he moves them it
is a one-line change per row in `calculate_p4_loss_history`.

### Score movements to tell Brent (D6)

| What | Direction |
|---|---|
| Loss run filed under the insured's declared DBA - a false identity hard stop was costing **20 points** (S6: package 60 -> 80) | UP |
| Tax-ID-matched run with an unexplained name (25 -> 92) | UP |
| 1-2 years of real loss runs (40 -> 70); 3-4 years (80 -> 85) | UP |
| Matched runs with a missing or stale valuation date (45 / 35 -> 60) | UP |
| Accounts previously docked for claim frequency or loss ratio (up to 40 points back) | UP |
| Businesses under a year old, and previously-uninsured applicants | UP |
| Prior carrier and claim count no longer double-counted in Structural Completeness | UP |
| Loss runs merely requested / pending (70 -> 50) | DOWN |
| "No losses" in prose with no attestation (45 -> 40) | DOWN |

---

## Session 2026-08-25 - C3 SQS Scoring Integrity & Critical-Field Weighting

### C3-A Full audit of section 3 - ANALYSIS COMPLETE, NOT YET FIXED (2026-08-25)
**Priority:** V1-CRITICAL
**Principle(s) touched:** 1 (one canonical fact), 6 (preserve provenance), 7 (unknown edge
cases default to producer review)

**The client's ask is traceability, not a better number.** Section 3's Desired Outcome is
one sentence: every material score must be traceable through
`Canonical Fact -> Validation Rule -> Pillar -> Raw SQS -> Ceiling -> Displayed SQS`.
The formula changes (3.2, 3.5-3.7, 3.14) are mechanical. The audit below is what has to be
true before any of them can be verified.

#### What was found (measured, not reasoned)

| # | Finding | Evidence |
|---|---|---|
| F1 | **The on-screen breakdown is not the formula.** `_compute_category_breakdown` takes `tier1_score` and `tier2_score` and reads NEITHER. Its own docstring claims the Structural sub-rows "ARE the P1 formula". They are not - it renders five unrelated rows computed from a different set of facts | `sqs_service.py:3351`; grep of the function body returns the two parameter lines and nothing else |
| F2 | **The audit trail already exists and is invisible.** `raw_sqs_score`, `cap_applied`, `cap_reason`, `credits_applied` are all returned by the scorer. **Zero** references anywhere in `frontend/src` | grep |
| F3 | **`producer_fields_exempt` is wider than 3.3 allows.** 3.3 waives producer name "when the ONLY source document is a declarations page". The flag is set from the PRIMARY document, so a dec page + application + loss run package still waives producer name AND contact - 40 points of Tier 1 forgiveness on a submission that has the producer's name available | `extraction_pipeline.py:450` - `mflags["_doc_type"] = primary.get("doc_type", "unknown")` |
| F4 | **The questionnaire misreports SQS impact in BOTH directions.** Live `classify_question`: `naics_code` gives `sqs: False, points: 0` while it is 1/6 of Tier 2. `total_payroll` / `wc_xmod` / `wc_payroll_period` / `wc_officer_exclusions` give `sqs: True, points: 8`, a number derived from `TIER2_FIELDS` membership - which flips to 0/False the moment 3.14 removes them, while payroll still moves Exposure by up to 27 | executed against the live classifier |
| F5 | **A producer field edit destroys earned dismissal credits.** 3.11 requires credits to survive recalculation. `form_routes.update_pdf` (3.10's "field edit" / "form edit" trigger) rebuilds every score and never calls `active_score_credits`. Only `recalculate_session_scores` re-applies them | grep: `active_score_credits` has zero call sites in `routes/form_routes.py` |
| F6 | **`physical_address` is asked of NOBODY.** The classifier returns `audience: internal, suppressed: true`, yet its absence raises a soft warning that caps the package at 85 on any property or multi-location account. It IS resolvable from the issue card, so not a dead end | `question_classifier` executed; `issue_registry.py:308` `_r_field("physical_address")` |
| F7 | **The Figure 20 NAICS suggestion chips are ALREADY DARK in production.** `suggestions` is rendered ONLY by `ClientQuestionnaire.jsx`. `naics_code` is producer-audience + suppressed, and `isClientFacing = bucket === "client" && !suppressed`, so the question never reaches the component that draws the chips. The feature went dark on 2026-08-12 when NAICS was re-routed to the producer; nobody noticed because the tests only cover generation | grep: `suggestions` appears in `ClientQuestionnaire.jsx` only |
| F8 | **`tier2_score` is a dead parameter in the per-form scorer** - threaded through five call sites into `calculate_sqs` and never read. **This is CORRECT per spec section 10:** per-form Structural is that form's own ACORD checklist by design. The two rival meanings of "Structural Completeness" on one screen are therefore INTENDED, not a defect. Remove the dead parameter for clarity; do not wire it | grep of `calculate_sqs`'s body; spec section 10 scope table |

#### The double-count claim, measured precisely

An earlier draft of this audit named four fields. **Two of them were wrong and are corrected
here** - the discipline being that a double-count claim has to name the second deduction,
not assume it.

| Fact | Structural Tier 2 | Exposure Consistency | Field-level stop | Verdict |
|---|---|---|---|---|
| `total_payroll` | yes (until 3.14) | -15 (no payroll/revenue), -12 (WC) | "Workers Comp detected but payroll is missing" | **Triple counted today. 3.14 fixes it** |
| `total_revenue` | yes | -15, shared with payroll | "GL coverage detected but no revenue or payroll found" | **Still triple counted after 3.14. NOT named by the client** |
| `operations_description` | yes | -10 (or masked by the -20 class-code branch) | none | **Still double counted after 3.14. NOT named by the client** |
| `num_employees` | yes | the +8 fires when employees ARE present with no WC - a coverage-gap check, not a completeness one | none | **NOT double counted.** Earlier claim withdrawn |
| `naics_code` | yes | only via `_is_ops_class_code_mismatch`, which needs a code to be present | `validate_naics_code` fires only on a MALFORMED code, never on a missing one | **NOT double counted.** Earlier claim withdrawn |
| `fein`, `years_in_business` | yes | none | none | clean |

**Two fields remain genuinely double counted after the client's own removals, and he named
neither.** Principle 7 and the precedence note say the same thing: do not invent the rule.
Measure it, report it, let product decide. See Q14.

#### Owner rulings received 2026-08-25

| Ruling | Effect |
|---|---|
| **"All the things mentioned are for both per form score as well as package wherever applicable"** | **CORRECTED 2026-08-25 after reading the spec.** The word that decides it is *"wherever applicable"*. `SQS_Scoring_Specification` **section 10** explicitly splits the two: *"Structural input - Individual form score: that form's own ACORD checklist, minus an OCR confidence penalty of up to 30 points. Total submission score: Tier 1 x 0.35 + Tier 2 x 0.30 + fill rate x 0.35."* The master plan's 3.2 modifies the SUBMISSION line only, so under the precedence note the per-form structural input **stays a checklist**. Everything else in section 3 - Tier 2 field list, Not-Applicable removal, ceilings, credits, recalculation, traceability - applies to BOTH. `tier2_score` in `calculate_sqs` is therefore dead by DESIGN, not an unwired feature; the earlier reading in this entry was wrong |
| **"Form fill rate and quality fill rate ... keep them disabled but still apply changes to them"** | `SHOW_COMPLETION_METRICS` stays `false` in `AcordModal.jsx`. The underlying numbers still change. Do not re-enable the section as a side effect of the reweight |

#### ASSUMPTION REGISTER - C3

Every one of these is a place where the client's document does not say, and engineering
chose. Listed so a later chat argues with the assumption rather than rediscovering it.

| ID | Assumption | Basis | If wrong |
|----|-----------|-------|----------|
| **A1** | **RETRACTED 2026-08-25.** 3.2's 40/35/25 is the SUBMISSION Structural formula only. Per-form Structural keeps its own ACORD checklist plus the OCR penalty | `SQS_Scoring_Specification` section 10's scope table states both formulas side by side and the master plan modifies only the submission one. Precedence note: unmodified rules stay authoritative | changing per-form Structural is a change BEYOND both documents and needs Brent's approval |
| **A2** | A fact may deduct inside a pillar AND independently trigger a ceiling. That is not double counting | 3.9 preserves the ceilings verbatim and adds *"Individual pillar deductions continue to reflect the volume/severity of underlying issues"* | the ceiling model collapses into the pillar model - a far larger rewrite than section 3 describes |
| **A3** | Double counts NOT named in 3.5 / 3.14 stay exactly as they are. Engineering reports them (Q14), never removes them | Precedence note: no new scoring rules without product approval. Principle 7 | `total_revenue` and `operations_description` keep costing a submission twice |
| **A4** | **RETRACTED 2026-08-25 (C3-B).** The spec grants exactly ONE Tier-1 exemption - producer name, dec-page-only - and the master plan repeats that sentence verbatim. `producer_fields_exempt` waives producer name AND contact, and keys on the PRIMARY document rather than the only one. Both deviations are engineering-added and outside both documents | spec section 3.1; master plan 3.3 | conforming drops dec-page-led Tier 1 by up to 40 points. D6 applies |
| **A5** | Brent's 1.00 / 0.85 / 0.50 confidence weights stand | Ruling 4, 2026-08-24 (*"Those assignments will do for now"*); the master plan sets no numbers and 3.8 forbids the redesign | every fill rate in the system moves |
| **A6** | Credit MAGNITUDES are untouched. Only stacking, retirement and survival are fixed | 3.11: *"Retain the existing V1 recommendation-credit mechanism unless separately revised"* | package credits keep being a number measured against a FORM's scale |
| **A7** | A captured `locations` schedule carrying the address satisfies 3.12's physical-address requirement | 3.12: *"It becomes applicable when the exposure requires it"* - if the schedule already carries it, the exposure's requirement is met | more 85 ceilings than the client expects on property accounts |
| **A8** | "Form Fill Rate" in 3.2 IS the existing `confidence_fill_rate`, denominator unchanged | 3.8: *"Continue using the current confidence-weighted fill-rate implementation"* + *"Do not redesign the full confidence-weighting algorithm in this V1 pass"* | See Q15. The denominator counts ONLY FILLED fields, so it is an average confidence, not a fill rate, and 3.8's *"Not Applicable fields must not reduce fill rate"* is already a no-op |
| **A9** | Adding auto garaging as a physical-address trigger is authorised, because 3.12 names it as an example | 3.12's own example list | a new warning fires on auto accounts that did not have one |
| **A10** | The per-form checklists keep emitting their recommendations after they stop being the score | otherwise ~30 form-specific recommendation cards vanish silently | the producer loses the form-specific gap cards |
| **A11** | The OCR-confidence penalty (up to -30 on per-form Structural) survives the reweight | the plan does not mention it; unmodified existing rules remain authoritative | per-form Structural moves again |

#### Questions raised for product

* **Q14** - `total_revenue` and `operations_description` are still double counted after the
  client's own removals. Same treatment, or leave them? Engineering will not decide it.
* **Q15** - the fill-rate denominator. 3.8's first bullet only bites if the denominator
  contains unfilled fields; ours contains only filled ones. Confirm ours stands (the bullet
  is a no-op) or he wants filled / applicable, which is the redesign the same section forbids.
* **Q16** - **F7 is a regression to disclose, not a question to ask.** The Figure 20 chips he
  praised have been dark since 2026-08-12. 3.13 now says leave classification assistance to
  V2 / Section 19, so the correct V1 action is to leave them dark and TELL him - D6 applies,
  because he will otherwise discover a praised feature is gone.

**Known / deliberately not done.** Nothing shipped in this entry. No code changed.

### C3-B Second pass - full spec read, 6 more findings, 2 retractions (2026-08-25)
**Priority:** V1-CRITICAL
**Trigger:** owner asked for a complete re-analysis with nothing left for later.
`SQS_Scoring_Specification.docx.pdf` was extracted in full (24,688 chars) and read
end to end for the first time in this arc. C3-A had been written against the code
plus the master plan only.

#### What the spec settles, verbatim

| Spec | Quote | Consequence |
|---|---|---|
| §3.1 | *"Submission level: Structural = (Tier 1 score x 0.35) + (Tier 2 score x 0.30) + (Fill rate x 0.35)"* then *"Individual form scores use that form's own checklist"* | 3.2's reweight is **submission-only**, stated twice (again in §10's scope table). Per-form Structural keeps its checklist plus the OCR penalty |
| §3.1 | *"Producer name is not required when the only source document is a declarations page."* | The ONLY Tier-1 exemption the spec grants. It does **not** exempt contact information |
| §3.1 | *"Certificate-only submissions are judged on two items instead: applicant legal name and effective date."* | Matches `check_tier1`'s certificate branch exactly. No change |
| §8 | *"What each recalculation runs, in order: ... 7. Re-application of any outstanding earned credits"* | Credit re-application is a SPEC requirement of every recalculation, not just a master-plan wish. F5 is a defect against both documents |
| §9 | *"They are scoped per form by which recommendations that form actually carries; the submission score uses the full total"* | The package using the session-wide credit total is SPEC'D. C3-A's concern that package credits are "measured on a form's scale" is **retracted** - that is the designed behaviour |
| §7 | *"the pillars already carry the severity ... Stacking cap penalties on top would count the same gap twice"* | Confirms A2: a fact may deduct in a pillar AND trigger a ceiling. Not double counting |
| §3.3 | Property Integrity model, incl. *"Valuation method is deliberately excluded from the Tier-2 credits"* | `_calculate_cope_score` matches the spec line for line. No change |
| §4 | 7 field-level hard stops | All 7 verified present in `evaluate_stops` + `run_field_validations`. No change |

#### New findings

| # | Finding | Evidence |
|---|---|---|
| F9 | **Credit stacking on one fact is reachable today.** `_LOSS_RECOMMENDATION_FIELDS` maps **four** distinct messages to `loss_history_years`, two to `fein`, and two to `loss_history_no_prior_losses_indicator`. Each message has its own stable `rec_id`, so two cards for the SAME missing fact can each be dismissed with a written reason and each earn a credit. 3.11: *"never stack on top of the same improvement twice"* | `sqs_service._LOSS_RECOMMENDATION_FIELDS`; `audit_service.active_score_credits` sums rows without deduping on `field` |
| F10 | **An explicit "No" answer stores an EMPTY value, so it can never count as a completed response.** `answer_semantics.build_fact_envelope` writes `value: interp.value`, which is empty for an ABSENCE, plus `value_state: explicit_no`. `_answered()` reads the state and credits Tier 1 / Tier 2 correctly - but `_fv()` returns empty, nothing stamps on the form, and `confidence_fill_rate` never sees a filled field. 3.8's *"Explicit No may count as a valid completed response"* is unmet | `answer_semantics.py:508` and its own docstring: *"the value ... is empty for an absence"* |
| F11 | **A conflicting fact receives FULL fill-rate credit.** `CONFLICT_WITHHOLD_KEYS` is an empty frozenset (D16 / Brent Q4), so `_uw_conflicted_keys` is always empty and `_resolve_conflicted_fact_blank` never fires. The conflicted value stamps with an ordinary confidence label and scores 0.85 or 1.00. 3.8's *"Conflicting fields should not receive full completed-field credit"* is unmet. **D16 and 3.8 do not conflict** - D16 says STAMP the value, 3.8 says give it less fill-rate CREDIT | `underwriting_consistency.py:548`; `pdf_service.py:4813` |
| F12 | **R2 quantified by simulation, not theory.** Removing the four fields from `TIER2_FIELDS` and re-running the live classifier: `total_payroll`, `wc_payroll_period` and `wc_officer_exclusions` all fall to `audience=internal, priority=suppressed` - **we would stop asking anyone for annual payroll.** `wc_xmod` survives only because it is already pinned by name in `IMPORTANT_FIELDS` | executed against `question_classifier` with the removal simulated |
| F13 | **Per-form `category_breakdown` is computed and never drawn.** `calculate_sqs` returns it; the frontend's per-form section renders only `activeSqs.breakdown` (the six pillar bars). Same shape as F2 - the detail exists in the payload and no surface reads it | `sqs_service.py:5849`; `AcordModal.jsx` per-form breakdown block |
| F14 | **`_estimate_score_impact` is dead code.** Defined, never called. It reads `TIER1_FIELDS` / `TIER2_FIELDS` so it looks like a consumer of the tier lists and is not | grep: one hit, the definition |

#### Retractions from C3-A

* **A4 is RETRACTED.** C3-A assumed the dec-page **contact-information** waiver survives as an
  applicability removal. The spec grants exactly one Tier-1 exemption - producer name - and the
  master plan repeats that sentence word for word. `producer_fields_exempt` waives producer name
  **and** the whole contact requirement, and it keys on the **primary** document rather than the
  only one. **Two deviations, both making the exemption wider than either document allows, worth
  up to 40 Tier-1 points on a dec-page-led package.** Conforming lowers those scores - D6 applies.
* **The package-credit-scale concern is RETRACTED** - §9 specifies it (see table above).

#### Corrected scope table - which score each item touches

| Item | Submission | Per-form |
|---|---|---|
| 3.1 pillar weights | already correct | already correct |
| 3.2 40/35/25 | **change** | no - spec §3.1 / §10 assign forms a checklist |
| 3.3 Tier 1 applicability (F3 + A4 retraction) | **change** | **change** - the ACORD 125 checklist calls `producer_fields_exempt` too |
| 3.4 Tier 1 scoring | already correct | n/a |
| 3.5 / 3.14 Tier 2 fields | **change** | no - WC fields already live on the ACORD 130 checklist, which is what 3.14 asks for |
| 3.6 NA out of the denominator | **change** (small) | n/a |
| 3.7 no-form rescale | **change** | n/a |
| 3.8 fill-rate rules (F10, F11) | **change** | **change** - `conf_rate` is per form |
| 3.9 ceilings | already correct | already correct |
| 3.10 recalculation (F5) | **change** | **change** |
| 3.11 credits (F9) | **change** | **change** |
| 3.12 physical address | **change** | no - cross-form issues never cap a form (§10) |
| 3.13 NAICS | **change** (dead-code removal) | n/a |
| Traceability (the Desired Outcome) | **change** | **change** (F13) |

#### Risk R6 downgraded - the field-to-fact link already exists

C3-A recorded that 3.8's conflicting-field rule may be unbuildable because conflicts are per
FACT and the fill rate is per FIELD. **That link is already written and in production:**
`_resolve_conflicted_fact_blank` resolves a form field to its source fact through
`_ACORD_FIELD_RULES` and then through the alias map plus `CANONICAL_TO_EXTRACTION`. Extract
that resolution into one shared helper and both 3.8 bullets become reachable for every
deterministically-stamped field. Gap-filled fields keep their existing AI labels, which is
correct - a model's guess has no source fact to be in conflict with.

**Known / deliberately not done.** Nothing shipped in this entry. No code changed.

### C3-C Owner answers verified; Q15 answered by MEASUREMENT, not reasoning (2026-08-25)
**Priority:** V1-CRITICAL
**Baseline before any change:** `py -m pytest -q` from `backend/` -> **4291 passed, 1 failed,
4 skipped, 191.87s**. The single failure is `test_arq_acord125_missing_only` -
`ImportError: cannot import name 'URL' from 'httpx'`, the documented environment conflict.
**CLAUDE.md's quoted baseline of "2139 passed / 2 failed" is STALE** - the suite has doubled,
and `test_normalization` (the second documented failure) now passes.

#### Owner rulings 2026-08-25 (second set)

| # | Ruling | Verified? |
|---|---|---|
| 1 | *"remove them as well"* - the two unnamed double counts | **Partially executable.** See below - 3.5 explicitly KEEPS operations description and annual revenue in Tier 2, so the removal can only happen on the Exposure side |
| 2 | *"recheck it for him"* - the fill-rate denominator | **Done, and the answer is NOT an assurance.** Two real defects found by measurement. See Q15 CLOSED below |
| 3 | *"follow him properly"* - the dec-page exemption | Accepted. Conform to 3.3: producer name waived ONLY when the ONLY source document is a dec page; contact information NOT waived at all |
| 4 | *"Download Anyway ... and mark as resolve without any significant value ... should not change"* | **Already correct on all three doors.** Verified, see below |

#### Q15 CLOSED BY MEASUREMENT - both fill-rate bullets are real defects

Executed against the live `confidence_fill_rate`:

```
one good field                        -> 100
same form + one "N/A" field           ->  75      <-- NA REDUCES the fill rate
a field holding the string "None"     ->   0      <-- explicit No gets ZERO credit
```

* **3.8 bullet 1 is NOT a no-op.** `_fv` returns the literal string `"N/A"` verbatim
  (confirmed: `_fv({'k':'N/A'},'k') == 'N/A'`), it stamps onto the form, and
  `confidence_fill_rate` counts it as a filled field at whatever confidence label it
  carries - dragging the average down. Brent was right; C3-A's reading that the bullet
  was already satisfied is **retracted**. This is the scoring-side consequence of the
  extraction gap already recorded as GAP 1 in CLAUDE.md.
* **3.8 bullet 4 is broken in the opposite direction.** `confidence_fill_rate`'s filled
  test is `str(val).strip() not in ("", "null", "None")`, so a field legitimately holding
  `"None"` scores **0**, not credit.

#### NEW FINDING F15 - the client questionnaire DESTROYS "None" before the semantics door

`_clean_answer_ex` (arq_service ~1110) returns `(None, "")` for
`"n/a", "na", "?", "unknown", "none", "null", "-", "--", "tbd", "unsure"`. A client typing
**"None"** to a prior-carrier question has the answer **discarded outright** - it never
becomes a fact, never gets `value_state: explicit_no`, and the gap stays open. The producer
path reads the same word correctly as an ANSWER via `answer_semantics`.

**Two doors, two behaviours, on the exact question Brent ruled on** (*"we can't treat 'N/A'
as '0' ... 'No known losses' is a legitimate answer"*). C2-G's claim that
`answer_semantics` is "the ONE door ... (producer recommendation cards, inline hard-stop /
warning resolution, client questionnaire)" is **false for the client questionnaire**:
`_clean_answer_ex` runs FIRST and eats the answer before `apply_arq_answers_to_session`
ever calls `interpret_answer`. Partially masked in practice because `answer_options`
(C2-H) offers long option strings such as "No - no claims ..." which survive the filter,
but a free-text "None" still dies.

#### Ruling 4 verified - all three doors already correct

| Door | Behaviour today | Verdict |
|---|---|---|
| "Download Anyway" | `download_routes` only READS `sqs_score` for the cover page and the audit row. No scorer call, no write | correct |
| Issue Resolved / Dismissed toggle | `/api/issues/status` -> `set_issue_status`, display-only, never calls a scorer | correct |
| Resolve an issue by typing junk | `resolve_issue` -> `_validate_producer_answer`, which calls `interpret_answer` and returns `(False, message)` when `not interp.accepted`. Verified live: `"TBD"`, `"dont know"`, `"?"`, `"-"` all resolve to `not_stated` / not accepted | correct |

**One hardening worth doing anyway:** `apply_producer_answer_to_session` and the client
apply path both call `build_fact_envelope` **without** checking `interp.accepted`, so the
refusal lives only at the route. A future caller bypasses it silently. Move the gate inside
the function - defence in depth, no behaviour change on today's callers.

#### Ruling 1 - what "remove them as well" can and cannot mean

**3.5 explicitly lists "Operations description" and "Annual revenue" under V1 Tier 2.** They
cannot be removed from Structural without contradicting the client's own document, so the
de-duplication has to happen on the EXPOSURE side.

| Exposure deduction | Same trigger as Tier 2? | Action |
|---|---|---|
| -20 GL coverage with no class codes at all | no - different fact (class codes) | **keep** |
| -10 class codes present but no operations description | **yes** | **remove** |
| -15 GL class code does not match the operations description | no - requires ops to be PRESENT | **keep** |
| -10 no GL coverage and no operations description | **yes** | **remove** |
| -10 WC coverage with no class codes / -15 WC mismatch | no | **keep** |
| -15 no payroll and no revenue anywhere | **partly** - fires only when BOTH are absent, and this is the bucket 3.14 sends PAYROLL to | **OWNER DECISION - see below** |

**The -15 is the one judgement call.** 3.14 says the WC/payroll requirements are *"handled
through WC/Exposure rules instead"*, so Exposure is payroll's new and only home. Deleting
the -15 removes revenue's double count AND payroll's home in one stroke; payroll would then
score only through `-12 WC coverage with no payroll` plus the soft stop. That is defensible
(GL is revenue-rated; WC is payroll-rated, and each keeps its own rule) and it gives every
fact exactly one pillar - but it is a scoring change beyond either document and needs an
explicit owner confirmation, not an inference.

**Known / deliberately not done.** Nothing shipped in this entry. No code changed.

### C3-D Section 3 SHIPPED (2026-08-25)
**Priority:** V1-CRITICAL
**Principle(s) touched:** 1 (one canonical fact), 3 (missing does not mean no),
6 (preserve provenance), 7 (unknown edge cases default to producer review)

**Suite: 4291 passed / 1 failed (baseline) -> 4298+ passed / 1 failed.** The one
failure is `test_arq_acord125_missing_only` (`ImportError: cannot import name
'URL' from 'httpx'`), the documented environment conflict, unchanged. Frontend
production build verified (`vite build`, clean).

#### What shipped, by clause

| Clause | Change | File |
|---|---|---|
| 3.1 | none needed - weights already 25/25/15/15/10/10 | - |
| **3.2** | Structural blend 35/30/35 -> **40/35/25**, as `_W_TIER1` / `_W_TIER2` / `_W_FILL` read by BOTH package scorers. **Submission only** - spec sections 3.1 and 10 print both formulas side by side and 3.2 modifies only the submission one | `sqs_service` |
| 3.3 | `producer_fields_exempt` narrowed TWICE: keys on the new `_only_dec_page` (every active document) instead of `_doc_type` (the primary one), and **contact information is no longer waived** - producer name is the only exemption either document grants. Applied to BOTH copies of the rule (`check_tier1` and the ACORD 125 checklist) | `sqs_service`, `extraction_pipeline` |
| 3.4 | none needed - N/A already contributes no -20, and Tier 1 deducts per missing item rather than dividing, so "removed" and "counted as answered" are the same arithmetic. **Verified, not assumed** | - |
| **3.5 / 3.14** | Tier 2 is now exactly the client's six. `total_payroll`, `wc_xmod`, `wc_payroll_period`, `wc_officer_exclusions` removed; `_TIER2_WC_FIELDS` and the `has_workers_comp` gate deleted with them | `sqs_service` |
| **3.6** | Not Applicable now leaves the DENOMINATOR (`_tier2_not_applicable`), which is different arithmetic from counting it answered: 6 fields with 1 N/A and 1 missing is **80**, not 83 | `sqs_service` |
| **3.7** | No-form rescale 53.8/46.2 -> **53.3/46.7**, DERIVED from 3.2's weights rather than typed, so the ratio survives a future change | `sqs_service` |
| **3.8** | All four rules. New `apply_fact_state_confidence_labels` reads each stamped box back to its source fact and labels it `not_applicable` (excluded from the fill rate entirely), `explicit_no` (full credit) or `conflicted` (half credit) | `pdf_service`, `sqs_service`, `underwriting_consistency`, `extraction_pipeline` |
| 3.9 | none needed - verified against the client's four worked examples and the no-stacking rule, now test-pinned | - |
| **3.10** | `form_routes.update_pdf` re-applies outstanding credits. Verified already-correct: Download Anyway never touches a score, the issue Resolved/Dismissed toggle is display-only, and a junk resolve ("TBD", "?") is refused by `_validate_producer_answer` | `form_routes` |
| **3.11** | One credit per FIELD, largest of the competing rows | `audit_service` |
| **3.12** | Auto garaging added as a trigger (3.12 names it); a `locations` schedule that already carries an address SATISFIES the requirement instead of warning | `cross_form_validator` |
| **3.13** | `ENABLE_CLASSIFICATION_SUGGESTIONS`, default **off** | `settings`, `arq_service` |
| **Desired Outcome** | `build_score_trace` - the ledger, emitted BY the scorer, on both the package and every form | `sqs_service`, `AcordModal.jsx` |

#### The owner's ruling on the two unnamed double counts

*"remove them as well"*. Executed, but NOT where it first appears: **3.5
explicitly lists Operations description and Annual revenue as V1 Tier 2 fields**,
so they cannot leave Structural. The de-duplication happened on the EXPOSURE
side, and only for deductions that fire on the SAME condition Tier 2 charges for:

* **removed** - "class codes present but no operations description" (-10) and
  "no GL coverage and no operations description" (-10);
* **removed** - "no payroll and no revenue anywhere" (-15);
* **kept** - missing CLASS CODES (-20, a different fact), the ops/class-code
  MISMATCH (-15, which requires ops to be PRESENT and so can never collide),
  and "WC coverage with no payroll" (-12).

**The -15 was the delicate one and the reasoning is worth keeping.** It was
simultaneously revenue's second charge AND, after 3.14, payroll's only home.
Deleting it naively would have contradicted 3.14's own instruction that those
fields are *"handled through WC/Exposure rules instead"*. Resolved by giving each
fact exactly one home: revenue -> Structural Tier 2; payroll -> the WC bucket
(-12) plus the "GL coverage with no revenue or payroll" warning, which is a
CEILING and not a deduction (3.9 and spec section 7 keep those separate). A
GL-only account is revenue-rated and a WC account is payroll-rated, so neither
loses a check that was ever meaningful for it.

#### A seam defect found while implementing 3.6, and fixed

`answer_semantics.build_fact_envelope` stores an answered N/A as
``value: "" + value_state: "not_applicable"``. `fact_state.derive_value_state`
re-derives from signals and looked only for an older ``not_applicable: True``
flag, so it returned `not_stated`. Measured: `fact_answered(env)` returned True
while `value_state_of(...)` returned `not_stated` **on the same envelope**. Two
modules, two vocabularies, one fact.

That made 3.6 unreachable for any human answer, and left
`_drop_not_applicable_questions` re-asking questions already answered. Fixed at
the one door, deliberately narrow so it can only REFINE and never override:
gated on a BLANK value, honouring only `not_applicable` / `explicit_no`, and
placed ahead of the package-level derivations so an explicit human answer
outranks "we could not read this".

#### F7 - a regression to DISCLOSE, not a question

**The Figure 20 NAICS chips have been dark since 2026-08-12.** `suggestions` is
rendered by exactly one component, `ClientQuestionnaire.jsx`; NAICS and SIC moved
to the PRODUCER audience that day on the client's earlier instruction, and a
producer-audience question never reaches that component. We kept computing
candidates nobody could see. 3.13 now defers classification assistance to Section
19 anyway, so the flag makes an accidental state deliberate. **Tell Brent** - he
praised that feature (D6). `naics_suggester` and its 44 tests are untouched; one
env var restores it.

#### Tests

`tests/test_c3_sqs_integrity.py` - **30 tests**, four of them anti-rot for defects
that had already happened once:
* `test_tier2_removals_are_still_asked_for` - measured before the pin:
  `total_payroll`, `wc_payroll_period`, `wc_officer_exclusions` all fell to
  audience=internal / suppressed. **Primble would have stopped asking anyone for
  annual payroll.** `wc_xmod` survived only because it was separately named.
* `test_the_trace_reconciles_*` - the ledger's contributions must sum to the raw
  score, and the Structural rows must reconstruct their own pillar. Drift now
  fails the build instead of reaching a producer.
* `test_one_improvement_earns_one_credit` - 8 + 5 on one field is 8, not 13.
* `test_no_fact_is_deducted_in_two_pillars` - driven through the REAL scorers,
  because a comment claiming a deduction was removed is not evidence.

Updated rather than deleted, each with the superseded rule recorded in the
docstring: `test_check_tier2_wc_fields_excluded_when_no_wc` (now
`test_tier2_carries_no_wc_or_payroll_field_at_all`),
`test_the_dec_page_exemption_is_shared_by_both_scorers`,
`test_the_card_is_still_raised_even_when_exempt`,
`test_wi3_structural_rows_are_client_approved`, and the two
`_attach_classification_suggestions` tests (now behind a `suggestions_on`
fixture, so Section 19 does not inherit dead code).

#### Blast radius - tell Brent BOTH directions (D6)

| What | Direction |
|---|---|
| WC accounts: four fields no longer docked in Structural | UP |
| Operations description and revenue no longer charged twice | UP |
| A location schedule carrying the address no longer trips the 85 physical-address ceiling | UP |
| Fields holding a literal "N/A" no longer drag the fill rate down | UP |
| An answered "None" now earns fill-rate credit instead of zero | UP |
| Credits survive a field edit instead of being wiped | UP |
| Dec-page-led packages: contact information is owed again, and the producer-name waiver needs EVERY document to be a dec page | **DOWN, up to 40 Tier 1 points** |
| Two cards about one missing fact now pay once | DOWN |
| Conflicting values earn half fill-rate credit instead of full | DOWN |
| Weight moved off Form Fill Rate (35% -> 25%) | mixed, per account |

**Not measured on live sessions yet.** The before/after on real packages is the
next step and goes to Brent before anyone sees a moved number.

#### Known / deliberately not done

* **Per-form Structural is untouched** and stays that form's own ACORD checklist
  plus the OCR penalty. The owner's *"for both per form as well as package"*
  ruling carries the words *"wherever applicable"*, and this is the one place it
  is not: spec sections 3.1 and 10 print the two formulas side by side, 3.2
  modifies only the submission one, and the precedence note keeps an unmodified
  rule authoritative. `tier2_score` in `calculate_sqs` is therefore dead BY
  DESIGN - remove it for clarity if you like, do not wire it.
* **Q15 is CLOSED by measurement** (see C3-C): both 3.8 bullets were real
  defects, not the no-ops an earlier reading claimed. The denominator itself is
  unchanged, per 3.8's *"do not redesign the full confidence-weighting
  algorithm in this V1 pass"*.
* **`apply_fact_state_confidence_labels` covers deterministically-stamped fields
  only.** A gap-filled box has no source fact, so it can be neither in conflict
  with the documents nor a recorded Explicit No. That is correct, not a gap.
* **The five old Structural sub-rows survive as a fallback** for callers that
  pass no `structural_parts` (stored payloads), so an old session renders detail
  rather than an empty panel.

### C3-E FIRST LIVE RUN - 4 of 8 scenarios PASS, 2 code bugs, 2 fixture faults (2026-08-25)
**Priority:** V1-CRITICAL

The owner ran S1-S8 and sent the panels back. Recorded here in full, because two
of the four problems were MINE and both are instances of a rule this file already
carries.

#### PASSED, exactly as documented

| Scenario | Evidence |
|---|---|
| **S1** | Tier 1 **80%**, only "Contact information" missing, producer name exempt. Structural 91 = 32 + 35 + 24.25 |
| **S2** | Tier 1 **60%**, BOTH producer name and contact owed. Package **65 against S1's 69** - the -4 predicted in C3-C |
| **S3** | Tier 2 **100%** with no payroll, X-mod or WC data anywhere. Zero WC recommendations. NAICS and SIC sit in the producer "Agency" bucket, **no suggestion chips** |
| **S6B** | The control fires - physical-address warning present with no location schedule |

The **How / Why** lines rendered on every scenario ("69 earned, held at 85 = 69"
plus the naming reason), and the Structural rows reconstruct their pillar to the
point on all of them. That was the headline check for the whole of C3.

#### BUG 1 (mine) - S6A warned with two street addresses in its schedule

`_check_identity_address_distinction`'s new satisfied-check tested
`isinstance(row, dict)` only. **`facts["locations"] is a list of plain
STRINGS`** - `extraction_service` line ~6468 ends with
``facts["locations"] = [str(o["address"]) for o in consolidated if o.get("address")]``.
The dict shape survives only on paths that skip consolidation, so the check never
fired on a real session.

I guessed the row shape from schedule capture instead of reading the writer -
the same class of error as D22 ("gate fixtures must be built from the LIVE index
shape") one layer over. Fixed to accept both shapes.

The second cut then let `"Location 1"` through, because it has a digit and
letters. A street address needs **three tokens and a digit**: that separates
"1450 Lantern Court" from both "See attached" (no digit) and "Location 1" (two
tokens). Five cases now pinned.

#### BUG 2 (mine) - an EXEMPT card advertised "up to +5 pts"

On S1 the producer-name card offered +5 while the pillar it belongs to could not
move at all. `_measure_recommendation_impacts` MEASURED zero correctly, then fell
into its `elif declared > 0 and headroom > 0` fallback - the branch that exists
because "no movement" might mean the probe was the wrong shape for the field.
True in general; wrong here, because the emitter already knows the check was
excluded from the pillar.

The ACORD 125 checklist now stamps `unscored: True` on a card whose check is not
scored, and the measurer returns `(0, True)` for it before any fallback.

**My own test passed while this was live.**
`test_the_card_is_still_raised_even_when_exempt` supplied `contact_name`, so the
pillar sat at 100, headroom was 0, and the fallback returned 0 for the wrong
reason. Rewritten to leave contact MISSING so there is real headroom for a bad
fallback to claim, and to assert the contact card is still worth >0 - otherwise
it would pass against a scorer that simply zeroed everything.

#### FIXTURE FAULT 1 - S4 proved nothing

S4 omitted the operations description. Extraction READ one anyway, out of the
class code's classification text ("Building Material Dealers"), so Tier 2 came
back **100** and there was no gap to observe.

Redesigned: the absent facts are now **revenue and payroll**. A dollar figure
that is not printed cannot be inferred from a trade name. Measured on the new
fixture: Tier 2 **83** listing "Annual revenue", Exposure Payroll/Employee
**92 (-8)** - and the -8 is the "employees but no WC coverage" rule, a different
check. Before the de-duplication it would have been 77 (-23).

#### FIXTURE FAULT 2 - S7 never reached the scorer

Two conflicting FEINs tripped the **"Possible multiple submissions" integrity
gate** before form generation, so the ceiling and the trace - the headline check
for all of C3 - never rendered.

Redesigned as a SINGLE document with the effective date AFTER the expiration
date. That is field-level hard stop #1 in spec section 4, one document, nothing
standing in front of the scorer. Verified: `evaluate_stops` returns the invalid-
period hard stop and `_resolve_cap` returns `(60, <that reason>)`.

#### OPEN - S8 could not be tested, and it is a real product question

The owner reported: *"I dismissed but i couldnot able to write, i just got to
dismiss it altogether"*, and both cards recorded **"Dismissed without reason"**,
so no credit was earned and the score did not move.

**Cause:** in `AcordModal`, `answerable = !!rec.field && typeof onAnswer === "function"`.
The dismiss-reason picker renders only on the NON-answerable path; an answerable
card's Dismiss calls `onDismiss(rec, sqsScore, "")` with an empty reason. Every
recommendation in the C3 test data has a fillable field, so the credit mechanism
was unreachable throughout.

**Not changed unilaterally.** There is a defensible design behind it - if you can
answer a card, answer it, and credits are for gaps you cannot fill - but spec
section 9 states plainly *"Dismiss a recommendation with a written reason ->
EARNS CREDIT"* and draws no such distinction. **Q17** raised. 3.11's other three
clauses (added to raw before ceilings, retire when filled, never stack) are
covered by unit tests and unaffected.

#### Improvement shipped from the run - Exposure buckets now show their arithmetic

Exposure sub-rows rendered a completeness WORD. The S4 fix moves Payroll/Employee
from 77 to 92, which reads as "Strong" versus "Complete" and proves nothing to
anyone. The buckets reconstruct their pillar exactly (headline = 100 minus the
sum of the deductions), so each row now carries `deducted` and the panel prints
`-8` or `no deduction`. Same principle as the Structural rows, applied to the
other pillar that can support it.

#### Verification

Backend suite re-run clean after all edits. Frontend production build clean.
`tests/test_c3_sqs_integrity.py` is **37 tests**, up from 30: the strengthened
exempt-card test, five parametrised location-schedule shapes (including the two
label cases that must still warn), and the auto-garaging trigger.

### C3-F SECOND LIVE RUN - both code fixes CONFIRMED; 2 more fixture faults, both mine (2026-08-26)
**Priority:** V1-CRITICAL

#### CONFIRMED FIXED by the run

| | Evidence from the owner's panels |
|---|---|
| **S6A** (BUG 1) | The physical-address warning is **GONE**. Two warnings remain, both unrelated (AOP deductible, crime coverage). S6B still fires it, so the control holds |
| **S1** (BUG 2) | The producer-name card now shows **no points line at all**; contact info still reads "up to +5 pts" |
| **Tooltip** | Sub-rows render bare percentages - "Core Application (Tier 1) 80%" - with the arithmetic moved into the hover, per the owner's 2026-08-25 instruction |
| **S4** (the double count) | **Exposure Revenue/Sales = 100%** while Structural Tier 2 = 83% carrying "Annual revenue". Revenue is charged ONCE. Structural reconciles: 100x0.40 + 83x0.35 + 92x0.25 = 92.05 -> **92**, the printed pillar |
| **Ceiling + trace** | Rendered on every scenario. S7 printed **"71 earned, held at 60 = 60"** with a named reason |

#### FIXTURE FAULT 3 (mine) - S7 fired the WRONG hard stop

The panel's Why read *"Policy Effective Date: documents disagree (09/15/2026,
09/29/2027)"* - on a scenario that is now a **single document**. Nothing can
disagree with itself across documents.

Cause: `_gl_coverage` hardcoded the module-level `EFF`/`EXP`, so S7 printed its
deliberately-invalid proposed period AND a perfectly valid policy period in the
same file. Two effective dates in one document tripped the date-conflict check,
which won the race to become the cap reason.

**The ceiling still read 60 and the trace still rendered** - so C3's mechanism
was never in doubt. But a fixture that passes for the wrong reason is worse than
one that fails, because it retires a question that was never asked.

Fixed: `_gl_coverage(..., eff=, exp=)` and S7 passes its own dates. A new
self-check refuses to ship S7 if the ordinary `EFF`/`EXP` appear anywhere in it.
Verified: the file now prints one period only, `09/30/2027 to 09/30/2026`.

#### FIXTURE FAULT 4 (mine) - class codes were never extracted, on ANY scenario

Exposure's Operations bucket was docked on S1 (72%), S4 (80%), S7 (80%) and S8
alike, and *"GL coverage detected but no class codes found"* was the cap reason
on several. Not a scoring defect - the fact was **empty**.

`gl_class_codes_by_location`'s extraction contract is
``[{"location": string, "codes": [string]}]`` and my schedule-of-hazards table
had **no LOCATION column**, so there was nothing to populate it with. Pure
fixture noise, and it masked what each scenario was actually testing.

Fixed: the table now leads with LOCATION.

#### S8 - the card exists, my INSTRUCTIONS named the wrong one

The run did produce a card carrying a reason dropdown - *"Loss run valuation
date not detected - recency unverified"*, whose `loss_recommendation_field` is
None. The credit path is reachable.

But the document classified as a **loss run** rather than an application (the
panel shows *"Loss runs attached"*, *"Matched on: name"*, Loss History 60), so
the card I predicted - "Loss runs requested / pending" - never appeared, and the
owner was hunting for text that was not there.

**The fixture is NOT being changed.** It already produces what the test needs,
and fighting the classifier to hit an exact message would trade a working
scenario for a guess. The INSTRUCTIONS now identify the card **by its shape** -
"the one card showing a Select a reason dropdown" - which cannot go stale when
classification shifts. Recorded because the lesson generalises: pin a live test
to a STRUCTURAL property, never to a sentence a model chose.

#### Standing lesson from C3-E and C3-F together

Four fixture faults across two runs, all mine, and every one was a shape I
ASSUMED rather than read: the `locations` row shape, the ops-description that
extraction could infer, the integrity gate standing in front of the scorer, and
a helper printing its own dates. **The self-verification block in the generator
caught none of them**, because each check tested what I remembered to doubt.
It now also refuses to ship S7 with a contradictory period - one more doubt,
added after the fact, which is the honest pattern.

### C3-G THIRD LIVE RUN - S7 PASSES; a MONTHS-OLD credit bug found (2026-08-26)
**Priority:** V1-CRITICAL

#### S7 PASSES - the headline check for all of C3

*"How: **77 earned, held at 60 = 60**"*, and *"Why: Effective date is on or
after expiration date - policy period is invalid"*. One document, one hard stop,
the ceiling binding and naming itself. The date-conflict that masked it in C3-F
is gone, and the LOCATION column fix landed too: **Operations 100%**, Exposure
92% (the residual 8 is the employees-without-WC rule, as designed).

#### THE BUG - a debug string had been eating the credit response for months

Owner, verbatim: *"I selected an option from dropdown and clicked submit ...
Dismissed **+6 pts credited** ... But score didnot change."*

`audit_routes._apply_dismiss_score_credit` binds `pkg_base` **only inside its
LEGACY branch**, then interpolates it unconditionally in the success log:

```python
if existing_pkg_raw is not None:
    new_pkg_score = final_score_with_credits(...)      # pkg_base NEVER bound
else:
    pkg_base = ...                                      # bound only here
...
logger.info(f"... pkg({pkg_base}+{score_impact}->{new_pkg_score} ...)")
```

Every session scored since `raw_sqs_score` shipped (2026-08-16) takes the first
branch, so that f-string raises **UnboundLocalError**, the blanket
`except Exception` catches it, and the function returns
`new_package_sqs_score: None`.

**The database UPDATE runs BEFORE the log line.** So the credit was genuinely
applied and committed - it simply never reached the response, the frontend had
nothing to apply, and the producer watched a card announce "+6 pts credited"
beside a score that did not move. Reproduced exactly before touching anything.

**NOT introduced by C3.** It has been live since 2026-08-16 and means no
dismissal has visibly moved an on-screen score since. It surfaced now only
because C3-F finally made the credit path reachable in a test.

**Fixed, in two parts:**
1. `pkg_base` is bound on both branches.
2. **The success log now sits in its own `try`.** The work is committed by that
   point; a diagnostic must never be able to convert a completed credit into a
   null result. The outer handler also gained `exc_info=True` - the bare message
   made an UnboundLocalError read exactly like a database failure.

Guarded by `test_the_dismiss_credit_response_survives_its_own_logging`, which
asserts both properties on the source (the function needs a live database, so
the structure is what can be pinned).

**Lesson worth keeping: the observability code is production code.** A log line
took out the feature it was describing, and the blanket `except` turned a
NameError into a silent wrong answer. Any `except Exception` that wraps both the
work AND the reporting of it can lose work that already succeeded.

#### Display fix - a ceiling that is not binding must not claim to be

Owner asked what *"81 earned, held at 85 = 81"* means. The answer: the ceiling
exists (warnings are open) but sits ABOVE the score, so it holds nothing -
`min(81, 85)` is just 81. Saying "held at 85 = 81" describes a cap that did not
happen, and 81 is neither held nor equal to 85.

The How line now names the ceiling **only when it actually binds**. Otherwise it
reads *"81 earned = 81"* with the ceiling explained in the hover, and the Why
line is suppressed for the same reason - it is the reason a ceiling EXISTS, not
a reason the score was reduced. S7's binding case is unchanged and still loud,
because that is the case worth seeing.

### C3-H FOURTH LIVE RUN - the credit WORKS; two display defects it exposed (2026-08-26)
**Priority:** V1-CRITICAL

#### CONFIRMED WORKING

| | Evidence |
|---|---|
| **The credit** | **A = 81 -> B = 85.** The C3-G fix landed once the backend was restarted (no `--reload` is configured, so the running process had held the pre-fix module in memory - which is why the third run looked identical to the second) |
| **Non-binding ceiling wording** | A read *"81 earned = 81"*, not the old *"held at 85 = 81"*. A ceiling above the score no longer claims to be holding it |
| **S7** | Passed in C3-G: *"77 earned, held at 60 = 60"* with the invalid policy period named |

**Seven of eight scenarios now verified live.**

#### DEFECT 1 (mine) - "81 earned = 85", a sum that does not add up

B rendered **"81 earned = 85"**. The credit was applied but never displayed: the
dismiss handler patched only `package_sqs_score` and `tier`, leaving
`credits_applied` at 0 and `score_trace.arithmetic` stale. So the How line -
the one element built specifically to make the arithmetic reconcile - printed
arithmetic that does not.

The backend already returns `credits_total`, `package_raw` and
`package_ceiling` (added in C3-G for diagnosis). The handler now applies all
three, so the line reads *"81 earned + 6 credited, held at 85 = 85"* and the
`binds` test sees 87 > 85 and correctly says "held".

**Worth noting: I built the reconciliation and then broke it from the one code
path that changes a score without recomputing it.** The trace is emitted by the
scorer, but this path patches the score WITHOUT the scorer, so nothing enforced
the invariant. Any future patch-the-headline path has the same hazard.

#### DEFECT 2 - the dismissed card sprang back into the open list

Owner: *"it never reached the reviewed block, i could see it again"*.

`loadDismissedRecs` does `setDismissedRecs(new Set(next.keys()))` - a wholesale
REPLACE from the server's reviewed list. The dismiss handler adds the id
optimistically and then calls it, so whenever that list has not caught up the
optimistic entry is wiped: the card leaves Reviewed and returns to the open
list, while the score change (already committed) stays. The producer sees a card
they just dismissed, still open, and a score that moved for no visible reason.

Fixed by passing the just-dismissed id and retaining it, plus its locally-known
reason and credited points, when the server has not returned it yet. Safe
against the reopen path: reopen deletes its id AFTER this runs and never passes
one, so nothing can be resurrected.

#### The owner's question, answered - Submit versus Dismiss

*"if i dismiss and there is something in the text box then it is sent with
dismiss, then what is apply for"*

It is **not** sent. `dismiss = () => onDismiss(rec, sqsScore, "")` - always an
empty reason, whatever is typed. Only the **Submit** button uses the input, and
it means different things per card type:

| Card | Submit does | Dismiss does |
|---|---|---|
| Has a fillable field (`Type your answer…`) | Writes the value as a FACT, re-runs the pipeline, stamps the form. The pillar earns the points | Hides the card. Empty reason, no credit. **The typed text is discarded** |
| No fillable field (`Select a reason…`) | Dismisses WITH the reason -> credit | Hides the card. No reason, no credit |

So: **Apply changes the SUBMISSION. Dismiss-with-reason changes only the SCORE**
and records a human judgement that the gap cannot be closed.

**Known trap, NOT fixed:** on an answerable card a filled text box sits beside a
Dismiss button that throws it away. The owner ruled on the related question
(*"not now maybe in future"* - should answerable cards offer dismiss-with-reason)
so the semantics stay as they are for V1. Recorded here rather than silently
left: the discard is invisible to the producer.

### C3-I THE REAL CAUSE, from the owner's logs - COALESCE does not catch a JSON null (2026-08-26)
**Priority:** V1-CRITICAL

**C3-G's diagnosis was WRONG and is corrected here.** The `pkg_base`
UnboundLocalError is real and worth having fixed, but it was never the one
biting: the failure happens EARLIER, so `pkg_base` was never reached.

#### The traceback (owner's log, and the reason `exc_info=True` was added)

```
ERROR routes.audit_routes: Failed to apply dismiss score credit:
      cannot extract elements from a scalar
  File "audit_routes.py", line 199, in _apply_dismiss_score_credit
    affected_rows = await conn.fetch(
asyncpg.exceptions.InvalidParameterValueError: cannot extract elements from a scalar
```

`COALESCE(ge.value->'sqs'->'recommendations', '[]'::jsonb)` substitutes only
when the value is **SQL NULL**. A stored JSON **null** - what a session carries
whenever a list was written as `None` - is a perfectly valid jsonb value, so it
passes straight through COALESCE into `jsonb_array_elements`, which refuses a
scalar.

**This throws BEFORE the package UPDATE.** So the credit never reached the
database at all, and C3-G's claim that "the credit really was applied, it just
never reached the response" was wrong. The audit row was written (a different
statement, already committed), which is why the card said *"+6 pts credited"*
next to a score that had genuinely not changed.

Why it looked intermittent: the session that DID work (81 -> 85) had proper
arrays in every form's `sqs.recommendations`. A session where one form stored
`null` there takes the fault. Same code, different data shape.

#### Fixed everywhere, not just where it threw

`jsonb_typeof(x) = 'array'` (or `'object'`) is the only test that means "is this
really a list". Applied to **five** call sites - the four others were the same
landmine waiting for a different session shape:

| File | What was unguarded |
|---|---|
| `routes/audit_routes.py` | `sqs.recommendations`, the `$2` credit array, `generated_forms`, `hard_stops`, `soft_stops`, `cross_issues_last` |
| `repositories/session_repository.py` | `generated_forms` (x2) |
| `routes/form_routes.py` | `generated_forms` (x2) |
| `scripts/restore_session_facts.py` | `docs` |

Guarded by `test_no_live_sql_expands_jsonb_behind_only_a_coalesce`, which scans
`routes/`, `repositories/` and `services/` for any jsonb expansion whose
argument is a bare COALESCE and fails the build naming file and line.

#### Two display fixes from the same run

* **"81 earned = 85"** - the dismiss handler patched only the headline score,
  leaving `credits_applied` at 0 and `score_trace.arithmetic` stale, so the one
  element built to make the arithmetic reconcile printed arithmetic that does
  not. It now applies `credits_total` / `package_raw` / `package_ceiling` from
  the response and reads *"81 earned + 6 credited, held at 85 = 85"*.
* **The dismissed card sprang back into the open list.** `loadDismissedRecs`
  REPLACES the set from the server's reviewed list, wiping the optimistic entry
  whenever that list has not caught up. It now retains the just-dismissed id and
  its locally-known reason and points; the reopen path is unaffected because it
  deletes its id afterwards and never passes one.

#### Owner request - a recalculation indicator

*"unless all the recalculation gets done add some spinner or something"*.
The How line now reads **"Recalculating the score…"** while a dismissal is in
flight, cleared in a `finally` so a failed request can never leave it spinning.
Directly relevant to this arc: with no indicator the producer cannot tell "still
working" from "nothing happened", which is exactly how a genuinely broken credit
survived three test runs.

#### THE LESSON, and it is about me

Three diagnoses in three messages, two of them wrong, and the thing that
actually settled it was **one traceback from the owner's logs**. `exc_info=True`
went in on a hunch in C3-G and immediately earned its place.

A blanket `except Exception` that logs only `str(ex)` turns every failure into
the same sentence. `cannot extract elements from a scalar` reads exactly like a
database problem, an UnboundLocalError reads exactly like a database problem,
and neither is distinguishable from the other without a stack. **Stop reasoning
about which of several hypotheses is true and go get the traceback.**

### C3-J S8 PASSES END TO END - and the trace defect recurs on a fourth path (2026-08-26)
**Priority:** V1-CRITICAL

#### S8 PASSES. C3's last scenario is closed.

| Step | Result |
|---|---|
| **A** | **81** - *"81 earned = 81"*, no ceiling claimed |
| **B** dismiss with a reason | **85** - *"81 earned + 6 credited, held at 85 = 85"*, Why names the open warning, card sits in Reviewed with its reason and badge |
| **C** edit a field, save | **85** - **the credit SURVIVED** |

Step C is the 2026-08-16 defect (`form_routes.update_pdf` rebuilt every score and
never re-applied credits) proven fixed against a live session. **All eight C3
scenarios are now verified live.**

The 85 rather than 87 is correct and is the ceiling doing its job: 81 + 6 = 87
held at the 85 warning ceiling, with two points earned, stored, and released the
moment the warning clears - Brent's own rule that credits land on the RAW score
before the ceiling.

#### THE DEFECT - "81 earned = 85" came back at step C

B was right and C was wrong, on the same session, minutes apart. The edit path
REBUILDS the score (fresh trace, `credits: 0`) and re-applies the credit
**afterwards** - patching the headline and leaving `score_trace.arithmetic`
holding the scorer's zero.

**FOUR independent copies** were doing this: package and per-form in
`form_routes.update_pdf`, and package and per-form in
`arq_service.recalculate_session_scores`. A fifth wrote the DB directly from
`audit_routes`, so a plain page reload after a dismissal resurrected it too.

**Fixed with one door.** `sqs_service.apply_credits_to_score(sqs, credits, cap,
score_key)` moves the headline, `credits_applied` and the trace together, and is
now the only way in. The SQL path updates the stored trace in the same statement
(`create_missing=false`, so a payload without a trace is left alone rather than
gaining half-built keys).

Guarded by two tests: one drives the helper and asserts the trace carries the
same credit and displayed score as the headline; the other fails the build if
`form_routes` or `arq_service` ever calls `final_score_with_credits` directly
again.

#### THE LESSON - I wrote the warning and then did not act on it

C3-H closed with, verbatim: *"Any future patch-the-headline path has the same
hazard."* I wrote that, shipped the fix for ONE path, and left the other four.
The next run reproduced the identical defect somewhere else.

**A hazard named in a log entry is not a hazard mitigated.** When a defect is
"this can happen anywhere that does X", the fix is to make X impossible - one
door plus a test that fails on a second one - not to fix the instance in front
of you and write the general case down for later. Three of this session's
recurrences (the second stamping copy, the second cap copy, and now the fourth
credit copy) are the same shape as defects this file already documents.
