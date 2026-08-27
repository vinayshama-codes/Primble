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
| `test_data_c9/` + `backend/scripts/make_c9_test_pdfs.py` | Three packages, four PDFs, for client section 9 / H4, plus `README-HOW-TO-TEST.md` with 13 numbered checks. P1 (2 files, ONE submission) routing + contact demotion + entity normalisation + the WC payroll-period charge; P2 new-venture sole proprietor; **P3 states EVERYTHING and is the GUARD RAIL** - every H4 rule must stay silent on it | Live validation of H4. **Regenerate before every run** (dates are computed from today). The generator's `_verify()` FAILS THE BUILD on a broken OMIT contract, and after the first live run it also enforces a STRUCTURAL condition: the token "payroll" may appear EXACTLY ONCE across the two P1 files. The first version printed `PREMIUM BASIS: Payroll` in the GL hazard table, which satisfies the annual test and silently disarmed the one check P1 exists for - every word-level ban passed (H4-B) |
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
| C5 | Source Lineage & E&O Audit Record | **SHIPPED 2026-08-26 (C5-A..C5-E). All 13 clauses + the four headline complaints, live-verified across three scenarios on the real system. Nothing open.** | New door `services/fact_lineage.py` recovers Document + Page by re-joining each merged fact against every document's OWN stored extraction and its `[Document page N]` text - deterministic, zero LLM cost. Export rebuilt: it read `session.doc_summary`, a key never persisted, so SOURCE DOCUMENTS said "(none recorded)" on EVERY export since the feature shipped; it also never read `acord_audit_log` (the full open-items list, per download), `underwriting_confirmation_audit` (C1's candidates - a table with NO reader) or `arq_receipts`. New append-only `audit_events` + 5.12 snapshots on the client's exact trigger list. **Evidence-destruction fixes: `update_pdf` replaced the fact ENVELOPE with a bare string** (our own edit path manufacturing the "Source: unspecified" the client reported), two `log_field_change` sites hardcoded `previous_value=None`, and client-ARQ apply / schedule saves / retractions logged nothing. **Two latent bugs fixed on sight: `run_facts_retention` had NEVER run** (UPDATE against a `facts` column that does not exist - `data->'facts'` is the truth), and **`sqs_history` was dead code** (the repository's append-only merge only engages when the key is passed explicitly and no caller ever did - `delta_this_session` was permanently 0 and the score-improvement panels could never render). Q18 answered by the owner: **6 months**. Read C5-A for root causes, C5-D for the seven defects the live run exposed, C5-E for the clause-by-clause closure and the four stated caveats |

### V1 - HIGH
| # | Item | Status | Notes |
|---|------|--------|-------|
| H1 | Coverage-Specific SQS Gap Closure | **SHIPPED 2026-08-26, LIVE-VERIFIED 2026-08-27 (H1-A..H1-M). CLOSED ON SCORING** - every 6.3 / 6.4 clause implemented and confirmed on the running app over two uploads, including the guard rail (the WC payroll -3 fires on a bare figure and stays silent on a document that states the period). 6.1 / 6.2 / 6.5 regression-pinned, nothing to implement. **STILL OPEN:** Q19-Q21 await Brent's confirmation (owner-ruled defaults, shipped); two NON-SCORING observations never seen live (the `OUT_OF_BATCH_KEYS` log line, the ACORD 127 USE checkbox); the split-limit restamp fix never seen live; Q22's root cause unknown (hardened, and the score has not vanished since). **Read H1-M for the closure ledger.** | One door: `services/coverage_evidence.py` (owned-vs-HNOA, the five Auto Completeness items, the three supplemental WC states, coverage-flag support). Two new Exposure buckets `auto_completeness` (cap 25) / `wc_supplemental` (cap 10); the two "+ Warning" items go through the LEGACY engine so they cap at 85 without also charging the cross-document bucket. New fact `auto_vehicle_use` (extraction v15, C80). HNOA-only accounts mark the five owned-vehicle facts Not Applicable and stop asking for them. **Edit-path flag demotion fixed** (an auto line with no limit and no schedule lost every auto penalty on the first field edit) plus the human-set flags a re-merge discarded. **Four phantom-key bugs fixed on the way** (split limits unsatisfiable hard stop, deductible basis, COPE building/BPP collapse, 127 garaging key). D6 applies in both directions. Read H1-A for the audit, H1-B for what shipped, H1-C for the phantom ledger |
| H2 | Early Score / Readiness Presentation | **SHIPPED 2026-08-27 (H2-A), LIVE-VERIFIED (H2-B). Closed on the owner's scope.** | The pre-form "Submission Readiness NN%" was `tier2_score` - a Tier 2 completeness ratio, not the SQS. Replaced by the STATUS LABEL of the package SQS as it stands (new one door `sqs_service.current_package_sqs`, stateless before generation, persisted score after) plus a "Key details in place / missing" split from the score's own Tier 1 + Tier 2 lists (`key_details`). Remediation counts live on the Hard Stops / Warnings sections ("N items still need attention · M handled"), and the Review step now re-loads stored Resolve/Dismiss marks. Client 7.2's countdown shipped at section level by owner's call. Read H2-A |
| H3 | Workers Compensation Data Capture | **SHIPPED + LIVE-VERIFIED 2026-08-27 (H3-A audit, H3-B build, H3-C kit, H3-D live run 1 + 7 fixes, H3-E live run 2 confirmation). Suite 4761 passed / 1 failed (documented `httpx` ImportError), 64 tests.** Round 1 passed every FORM check and found 7 defects on the way to a HUMAN; round 2 confirmed 6 of the 7 on the regenerated forms and questionnaire (the 7th needs the pre-form screen). **Client section 8 is delivered: 8.1 / 8.2 / 8.3 all built and seen live.** STILL TO TEST (3, in H3-E): the pre-form screen for the effective-date fix; the W3 producer step (8.3 "retain producer-entered codes", the one clause never seen live); the client questionnaire link itself. **Q29 deliberately NOT built** - a rows-vs-stated-payroll warning is a new rule, for Brent. Observed and NOT fixed (none are section 8): an invented `# CLAIMS` in the prior-carrier grid, label text in the premium block's Other cells, a second officer's title extraction missed | One door `coverage_evidence`; two tables on the EXISTING facts; extraction v17. **Read H3-A for the audit, H3-D for the 7 live defects and their root causes, H3-E for what remains** |
| H4 | Core Submission Information Coverage | **CLOSED ON THE MATRIX 2026-08-27 (H4-A..H4-D). MEASURED: routing 29/29, scoring home 29/29, key rules 28/29 (one partial), Desired Outcome 8/8 stages owned** - see H4-D for the scorecard and how it was produced. Only 8 of the 29 rows were broken; the other 21 came from C1-C5/H1-H3 and were verified, not rebuilt. Date hard stop investigated and deliberately UNCHANGED (H4-C). Suite 4824 passed / 1 failed** (the documented `httpx` ImportError), +47 tests, zero regressions. **Not live-verified - the owner's next upload is the check.** Three items open for Brent (Q31, Q32, Q33 - Q33 is a WRONG VALUE on ACORD 125 and is the most serious) | Section 9 is an ACCEPTANCE MATRIX, not a field list. 21 of 30 rows already held; 9 deviated in 5 classes. Shipped: **F15 CLOSED** (the client questionnaire destroyed "None"/"N/A" before `answer_semantics` - and closing it exposed 4 more defects on the same lines, all fixed); `prior_carrier` reaches the client again (Brent Q8 + 9.1); expiration date / GL form type / audit period / billing plan routed to the producer; **entity type made one vocabulary** (5 live false Data Consistency conflicts on ACORD's own wording, a validator refusing 8 of our own 13 dropdown options, and a stamper that ticked the WRONG box for "S Corporation" and "Non-Profit Corporation" and NOTHING for "Sole Proprietorship"); Tier 1 contact demoted not suppressed; new venture is a valid Years-in-Business state; WC payroll period N/A when annual is clear. New standing gate `tests/test_h4_core_fact_matrix.py` (47). **Read H4-A before touching any routing, answer-interpretation or entity path** |
| H5 | ACORD 25 Multi-Carrier Mapping | Not started | |
| H6 | ACORD 125 Form-Generation Foundation | Not started | Answer key is the 125_reference/ folder. Form edition already correct (2025/03) - see D5 |
| H7 | Audit / Edit History Completion | **DELIVERED 2026-08-27, LIVE-VERIFIED over two rounds (H7-A audit, H7-B build, H7-C kit, H7-D live run 1 + 5 defects, H7-E live run 2 + closure). All 8 client events, all 7 attributes and the Desired Outcome confirmed on the running app. Suite 4890 passed / 1 failed** (the documented `httpx` ImportError), +65 tests, zero regressions, frontend build clean. **STILL OPEN:** S2 (the multi-insured integrity override) never run live; the pre-form hard-stop rail unreachable after generation; the override classification under-claims on some boxes (measured, safe direction) | **Read H7-A for the root cause, H7-B for what shipped, H7-D for the 5 live defects, H7-E for the clause-by-clause closure.** Root cause was ONE class: the operational tables were made to double as the audit trail - correctly MUTABLE for dismiss-credit / the download gate / the issue rail / reopen, and an audit trail must not be, so history died every time the workflow moved on. Fix is D49: workflow tables hold STATE, `audit_events` holds HISTORY, and the event is emitted by the writer the action already goes through. New pure door `services/audit_history.py`; `record_material_change` called from INSIDE the eight existing audit writers; actor resolved once per export and rendered everywhere (it was rendered NOWHERE); `previous_source` closes the generated-value override; `activity_service` became an adapter over the spine (D50); `submission_integrity_audit` got its first reader; retention 180 -> 365 (D48). **Two defects found while building and three more on the live run**, including the owner's own reported "answer not saving" (the record was right, the CARD lied - D56) and a machine `"null"` competing as a VALUE that manufactured TWO false hard stops (D55). **Scores move UP on both - D6.** Source lineage inside the one model is met by design decision (D36), not construction - tell Brent in those words |
| BE | **V1 Beta Exit Criteria** - verification + fixes | **VERIFIED AND 7 FIXED 2026-08-28 (BE-A..BE-E). 40 of the client's 49 criteria held against the CODE; 9 did not. Seven shipped this session, two are recorded as NOT fixed with reasons. Suite 4917 passed / 1 failed (the documented `httpx` test - see BE-D, its CLAUDE.md description is now WRONG), +27 tests, zero regressions, no frontend change.** | **Read BE-A for what was measured, BE-B for the seven fixes, BE-C for the two left alone.** Fixed: `gl_class_code_schedule` asked the CLIENT for GL class codes (core principle 5); an ungated ACORD 186 HARD STOP demanded WC payroll from GL-only packages (71 -> 60); a field CLEAR was audited but never persisted (D18 not followed); a dismiss was silently dead after any Download Anyway and its credit reverted; the schedule save never rescored; derived provenance was lost on every override; and the client's own `loss_history` claims TABLE was invisible to the no-loss contradiction guard (one door `loss_history_state.asserted_claims`). **D6 BOTH WAYS: GL-only contractor packages go UP, a typed claim contradicting an attestation goes DOWN.** NOT fixed: bare `GL`/`WC`/`BAP` in `lob_canon` (blocked by D9 - needs Brent or an owner override) and extraction's literal `"N/A"` counting as data (CLAUDE.md GAP 1 - needs a measured pass, not a one-liner) |

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
| D36 | **Fact lineage is COMPUTED at export time, never stored on the fact.** Both sides of the join already persist - each document keeps its OWN extracted facts and its OWN page-marked text - so the E&O record re-joins them on demand. Adding a per-fact lineage table (or copying multi-source evidence onto every envelope) was rejected | 2026-08-26 | C5-A. Client 5.3 explicitly permits "a different schema ... as long as these relationships are recoverable". Storing it would duplicate evidence that can drift from the documents; computing it cannot. Zero LLM cost, and the 2026-08-23 dec-index arc already measured what asking the model for page numbers costs (~593k tokens, +18-20 min, switched off) |
| D37 | **Right-or-blank applies to LINEAGE, not just to values.** A page is cited only when the value is literally locatable under a page marker; a document only when its own extraction agrees (via `fact_comparison`) or its text literally contains the value; nothing under `_TEXT_VERIFY_MIN_CHARS` (4 normalised chars) is ever cited. A markerless document cites page 1 ONLY because `ocr_service` provably marks every multi-page document - with `OCR_PAGE_MARKERS=0` it declines again | 2026-08-26 | C5-A / C5-E. A false citation in an E&O record is worse than no citation: it is the one artefact a producer would rely on in a claim. Pinned in both directions by `test_markerless_text_declines_a_page_when_markers_are_off` |
| D38 | **A producer's resolution settles the FACT's state; the disagreement lives on in the resolution record, not as a permanent `conflicting` state.** `derive_value_state` skips the CONFLICTING branch when `evidence_state == user_confirmed` | 2026-08-26 | C5-D, found on the owner's live run: the record printed "UNRESOLVED (conflicting / user_confirmed)" one line under the DATA CONSISTENCY RESOLUTIONS entry that had just resolved it. The `_uw_conflict_keys` superset records that the DOCUMENTS disagree, which stays true forever, so no confirmation could ever clear it. Client 1.5 + 5.10: retain the history, but a resolved fact is resolved. An UNRESOLVED conflict still reads `conflicting` - the fix must never widen |
| D39 | **A fact scored only on a per-form checklist has NO submission-level weight (spec section 10 / D29), so a client rule about "total submission SQS" is built as an Exposure BUCKET, never by feeding a form score into the package.** H1 6.3 / 6.4 are `auto_completeness` and `wc_supplemental` inside `_calculate_exposure_consistency`, each with the client's own cap | 2026-08-26 | H1-A: the entire defect class is "form-only facts". Wiring `tier2_score` or the 127 score into the package would breach D29 and the spec's independence rule |
| D40 | **A "+ Warning" the client attaches to a deduction is emitted through the LEGACY engine (`evaluate_stops`), never as a cross-form issue.** A cross-form soft warning lands in `soft_stops` AND in the Exposure cross-document bucket, so one gap would deduct twice in one pillar; a legacy soft stop only sets the 85 ceiling, which is what "+ Warning" means | 2026-08-26 | H1-B; verified at `extraction_pipeline.py` where `cf_soft` is merged into `soft_stops`. Pinned by `test_the_warnings_cap_at_85_but_never_charge_the_cross_bucket` |
| D41 | **OWNER 2026-08-26: an auto line that says neither owned nor hired/non-owned is PRESUMED OWNED for 6.3.** HNOA-only needs positive evidence (symbols reaching only hired/non-owned, an explicit "no owned vehicles", or every granted auto line naming HNOA). `auto_exposure_kind` still returns UNKNOWN so the trace can say "presumed" | 2026-08-26 | The client's "genuinely Hired/Non-Owned only" reads as evidence to exempt, and the empty ACORD 127 is exactly the submission 6.3 exists to catch. Brent to confirm (Q19) |
| D42 | **A coverage flag is demoted on the edit path only when NO positive evidence for the line remains** - no section form selected for it, no `coverage_lines` grant, no fact of that line answered - decided by `coverage_evidence.coverage_flag_supported`, which derives the line's facts from the registry. Never "the two facts the penalty reads are blank" | 2026-08-26 | H1 audit: `form_routes.update_pdf` dropped `has_auto_coverage` when the limit and the schedule were both blank - the most incomplete auto account lost every auto penalty on the first edit of any field, and the score rose. Same shape for property / umbrella / WC |
| D43 | **"Known to exist", "clearly annual" and "applicability indicated" are read from NAMED evidence, never inferred from a category.** Officers exist when individuals are NAMED (never from entity type); a payroll figure is annual when its OWN label / source MEANS annual (synonyms, not one spelling); an X-Mod applies when the document or the producer SAYS so (effective date, "pending", "see worksheet") | 2026-08-26 | Owner rulings 5 and 6 (2026-08-26). Principle 3: silence is not a value. The alternative readings fire on nearly every WC account and turn a real check into noise |
| D44 | **A capture TABLE owns its own audience split.** A column is hidden from the client by `Column(producer_only=True)`; a whole table is the producer's by `ScheduleDef(producer_only=True)` (honoured by `_finalize_schedule_taxonomy`, refused by the send path, skipped by `client_view`). `question_eligibility.overlay_for` never judges a `field_type == "schedule"` question by its canonical key | 2026-08-27 | H3-B: `wc_class_codes` IS an insurance-judgment fact, but the TABLE is the client's payroll-by-group answer with the code column stripped. Judging the table by its key flagged the client's own exposure table "producer review" for a column the client never sees |
| D45 | **A WC class code is right-or-blank: only the structured row may print one.** Every ACORD 130 code box (`RateClass_ClassificationCode`, `RateClass_DescriptionCode`, `Individual_RatingClassificationCode`) is schedule-OWNED, so with no extracted or typed row it is an owned blank - the gap-fill LLM is never asked for it | 2026-08-27 | Client 8.3: "Primble should not generate or recommend WC class codes in V1." A code box the model can fill from prose IS a recommendation. Measured before H3: the officer code boxes and the description-code boxes reached the LLM whenever no table existed |
| D46 | **A capture TABLE is never a "machine-worded" question.** `arq_service._hide_machine_worded_questions` skips `field_type == "schedule"` outright, and `schedule_capture.question_text`'s default template must never begin with `_MACHINE_QUESTION_PREFIX` ("Please provide your "). Both conditions, not either | 2026-08-27 | H3-D: that default WAS the banned prefix, so both WC tables were built, routed to Client/Agency, and then hidden one step later - the client's whole section 8 capture invisible while 54 unit tests passed. The four original schedules escaped only by each having a hand-written override. A table carries a column spec and a human label; it cannot be "a PDF box with a sentence wrapped round its name", which is all that filter exists to catch |
| D47 | **A label owned by another subject standing immediately in front of it is not this field's label.** `underwriting_consistency._label_has_foreign_subject` drops a text-scan match whose preceding two words on the SAME line name a foreign subject (experience / modification / rating / anniversary / retro / birth / hire ...). Deny-list on purpose: it can only ever DROP a rival candidate, never invent one | 2026-08-27 | H3-D: `\b(?:policy\s+)?effective(?:\s+date)?` matches inside "Experience Modification Effective Date:", so the X-Mod's date became a rival POLICY effective date - a false conflict card and an 85 cap on EVERY WC package printing a mod date. Applies to every reconcilable field, not just WC. Same structural shape as H1-K's payroll gate and the 2026-08-08 boilerplate fix |
| D48 | **OWNER 2026-08-27: the E&O event spine is retained for 365 days, not 180.** `AUDIT_EVENTS_RETENTION_DAYS` default and floor both move to 365, matching `AUDIT_LOG_RETENTION_DAYS`. This SUPERSEDES the 180-day half of the Q18 ruling; the 6-month floor for session facts (`run_facts_retention`, free/essentials = 180) is unchanged and still honours it | 2026-08-27 | H7-A: `audit_events` (180d) was expiring BEFORE the mutable tables it exists to explain (`field_source_audit` / `sqs_recommendation_audit` / `acord_audit_log`, all 365d) and before six tables that are never swept at all. From month 7 to month 12 the record would have been exactly what client section 12 calls out - current state with the history already deleted. `test_six_month_retention_ruling_is_implemented` pins the literal `"180"` string and MUST be updated in the same commit; the ruling it pins is not being weakened, it is being extended |
| D49 | **The workflow tables hold STATE; `audit_events` holds HISTORY; the event is emitted by the writer the action already goes through, never by the exporter.** `sqs_recommendation_audit`, `submission_issue_status`, `marketing_reason_audit` stay mutable upserts - dismiss-credit, the download gate, the issue rail and reopen all read them as current state and must keep doing so. Every material act ALSO appends one immutable envelope to the spine | 2026-08-27 | H7-A root cause: the operational tables were made to double as the audit trail. They are correctly mutable, an audit trail must not be, and one table cannot be both - so history was destroyed every time the workflow moved on. Replacing them with an event-sourced projection was REJECTED: it touches C1, C3, C5, H1 and H2 at once for a record the producer can already read |
| D50 | **OWNER 2026-08-27: ONE MODEL, not a dual-write.** `activity_service.record_event` stops being an independent writer and becomes an adapter over the spine; the navbar Activity Log reads a user-scoped projection of the same rows. `activity_events` is kept read-only for pre-existing rows. Three additive changes make it possible: `package_label` on `audit_events`, an index on `(user_id, created_at)`, and a `visibility` marker separating product-history events from E&O-only ones | 2026-08-27 | Client section 12 verbatim: *"one underlying event/history model that can serve: product history; debugging; source lineage; E&O Audit Record."* Measured before the ruling: the two tables have near-identical schemas and record the SAME acts under different names - `answers_applied` / `client_answers_applied`, `sqs_scored` / `sqs_snapshot`, and one download writing THREE rows across three stores |
| D51 | **"Role" is the workflow role - producer / client / system - DERIVED, never a new column on `users`.** producer = the session owner acting; client = `source='client_arq'`, named from the immutable `arq_receipts` row; system = no acting user (auto-resolve, scheduler, extraction). Agency RBAC (CSR / principal) is explicitly NOT in V1 | 2026-08-27 | OWNER 2026-08-27. No RBAC exists to read - `admin_users` is an email allow-list and `users` has no role column (verified). The client's section 12 list pairs "actor" with "role", which reads as *who acted and in what capacity on this submission*, not org hierarchy |
| D52 | **A reason is PLUMBED on every material change and PROMPTED on none.** `field_source_audit` and the spine envelope both carry `reason`; no new reason box appears on the form-edit path | 2026-08-27 | OWNER 2026-08-27, consistent with Q17's standing "not now" on dismissal reasons. The column existing costs nothing and closes the schema gap the client named; a prompt on every field edit is a UX decision nobody has asked for |
| D53 | **A document's ROLE is a property of ONE document; "these two describe different real-world objects" is a property of the PAIR.** `fact_comparison._ROLE_BLIND_FACTS` may only say "this role does not STATE this fact" - true for a loss run's "period covered" (a claims window, not a policy term), false for a declarations page and a policy term. It must NEVER be used to suppress a comparison between two documents that both genuinely state the fact: that SILENCES a conflict instead of resolving it (P4), and it deletes the `_scoped` verdict that already resolves genuine multi-policy packages. Pair-level decisions belong in the DOWNGRADE gate, not the role table | 2026-08-27 | H4-C. Making a dec page blind to policy dates fixed the reported case and was refuted three ways by independent review - it silenced dec-vs-dec and dec-vs-certificate conflicts outright, and it would have hidden a wrong value that still ships on ACORD 125 (Q33) |
| D54 | **A predicate feeding the Not Applicable axis must be FLAG-INDEPENDENT.** `fact_state` calls `coverage_evidence.h1_fact_not_applicable(fact_key, facts)` with NO flags, and `facts["_flags"]` exists only for the duration of one `annotate_fact_states` pass. Any rule there that reads a coverage flag is BLIND at `overlay_for`, `_tier2_not_applicable` and `is_not_applicable_for` time and will mark its fact Not Applicable on EVERY package. **A deduction whose question has been retired is worse than the gap it was written for** | 2026-08-27 | H4-A. The first cut of the WC payroll-period rule routed through `wc_payroll_period_status`, whose first line reads `has_workers_comp`; it charged the -3 and asked nobody. My own probe missed it by passing `_flags` inside the facts dict - a harness shape. Pinned by `test_h4_core_fact_matrix::test_the_payroll_period_deduction_always_has_a_route_to_remediation` |
| D55 | **A MACHINE non-value is never a candidate.** `underwriting_consistency._normalize` returns None for `""` / `"null"` / `"none"` on every kind, so an extractor's own spelling of "nothing found" can never become a competing VALUE in the Data Consistency picker. Deliberately narrow: a HUMAN typing "None" is an ANSWER with no value and is handled by `answer_semantics` on a different path (C2-G); `_normalize` only ever sees document-extracted candidates | 2026-08-27 | H7-D defect 5, live: the picker reported *"Policy Effective Date: documents disagree (09/17/2026, null)"* and the same for the expiration - TWO false hard stops capping a perfectly consistent two-document package at 60. `_normalize("null","date")` returned the truthy string `'null'`, which passed every `if not norm: continue` guard. The module ALREADY knew the rule - its own scalar reader `_fv` drops exactly these three - it was simply never applied on the paths that BUILD candidate groups. One rule, two copies, one dormant: the same shape as C1's five comparison sites and H1-C's phantom keys. Principle 3. Scores move UP - D6 |
| D56 | **A "confirm X" recommendation must retire once X is answered EITHER way.** Gate the prompt on "has this been ANSWERED" (`loss_history_state.new_venture_answered`), never on "is the answer YES" (`new_venture_confirmed`) - C2-G's split between *what is the value* and *did they answer*. The genuine underlying gap keeps its own separate recommendation and correctly stays open | 2026-08-27 | H7-D defect 1, the owner's own reported bug: `_NEW_VENTURE_CONFIRM_REC` was appended whenever loss history was absent, with no reference to whether it had been answered. "Yes" makes the pillar Not Applicable so the rec stops being generated and the card closes; "No" - the honest answer on most accounts - changed nothing the scorer reads, so the rec came back identical, auto-resolve had nothing to stamp, and the card reappeared Open with an empty dropdown. The answer was saved correctly at every layer - fact, envelope and audit row - and only the CARD lied. The owner answered it three times before reporting it. A blank is still unanswered (Principle 3) |
| D57 | **The three bare coverage abbreviations `GL` / `WC` / `BAP` canonicalise, and they match as WHOLE TOKENS, never as substrings.** `lob_canon._ABBREVIATIONS`, checked AFTER `_SPECIFIC` so "Excess GL" stays umbrella. Exactly these three; a fourth is a fresh D9 decision and `test_the_ruling_covers_exactly_three_abbreviations` fails the build if one is added quietly | 2026-08-28 | **OWNER RULING 2026-08-28**, the product approval D9 reserves. Open as O2 since 2026-08-26: the most common shorthand in commercial insurance was being treated as *"terminology not covered by a known normalization rule"* (client 1.7), so a line printed `GL` was routed to the producer as an unrecognised coverage part and could never be DENIED. **D9 was right to hold it, and the reason is the matching mechanism, not the equivalence**: `_SPECIFIC` / `_GL_PHRASES` match by SUBSTRING, and "burglary and theft", "plate glass" and "roofing shingles" all CONTAIN "gl" - a naive append would have read a crime line, a property line and a roofer's own trade as General Liability. Measured, then built token-wise: 0 regressions across the existing vocabulary, 0 adversarial failures |

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

| Q18 | **How long must the E&O audit record live?** C5 built the record from two kinds of store: durable audit tables and the session blob (per-document text/facts, which the new Document + Page lineage reads). Today `acord_audit_log` / `field_source_audit` / `sqs_recommendation_audit` are swept at 365 days (`AUDIT_LOG_RETENTION_DAYS`), the new `audit_events` table is deliberately never swept, and the facts-retention purge (which had NEVER actually run - broken SQL, fixed 2026-08-26) tombstones free/essentials facts at 30/180 days while leaving `docs[].text` untouched. E&O claims can arrive years after a submission; a 365-day sweep and an E&O record are not obviously compatible, and widening the facts purge to docs would delete the lineage evidence. Needs a product retention ruling; engineering will not pick a number (Principle 7) | C5 | 2026-08-26 | **OWNER 2026-08-26: 6 months.** Implemented: `audit_events` swept at `AUDIT_EVENTS_RETENTION_DAYS` (default 180, floored at 180); free-tier facts retention raised 30 -> 180 so the record's inputs survive the ruled window (the 30-day purge had never actually run - broken SQL - so no live data behaves differently); the three operational audit tables keep their 365-day SOC 2 floor, which exceeds 6 months. Brent's copy of the question updated to state the set default |
| Q19 | **Auto line requested, nothing says owned or HNOA-only** (no vehicle list, no covered-auto symbols, no physical damage): apply the 6.3 deductions (presume owned) or route to the producer with no deduction? Engineering built presume-owned on the owner's ruling (D41) | H1 | 2026-08-26 | **OWNER 2026-08-26: presume owned.** Shipped. In Brent's doc as an assumption to confirm |
| Q20 | **"Owners/officers known to exist"** - only individuals named in the package or by a person, or every corporation/LLC by definition? Built narrow (named individuals only); the broad reading fires on nearly every WC account | H1 | 2026-08-26 | **OWNER 2026-08-26: "go with your instincts"** -> narrow. Shipped (D43). In Brent's doc to confirm |
| Q21 | **"Clearly annual" payroll** - is the figure's own printed label ("Estimated Annual Payroll", "per annum", "12 months") or a class-code schedule row enough, with no separate period field? Built yes, by MEANING not spelling; the -3 fires only for a bare figure with no period anywhere | H1 | 2026-08-26 | **OWNER 2026-08-26: yes, and match the meaning not the exact words.** Shipped (D43). In Brent's doc to confirm |
| Q24 | **H3 8.1 employee count per group: full-time + part-time (two columns, form-true - ACORD 130 prints `RateClass_FullTimeEmployeeCount` AND `PartTimeEmployeeCount` per row) or ONE number as the client's example shows?** One number would have to land in the full-time box - a wrong value for a mixed group. Engineering default: FT + PT | H3 | 2026-08-27 | **OWNER 2026-08-27: "fix things properly" - engineering default authorised.** Shipped (H3-B) |
| Q25 | **H3 8.1 "job title / employee group" and "description of actual duties" as ONE table column?** ACORD 130 has no job-title box; `RateClass_DutiesDescription`'s own tooltip asks for "the classification description or a brief statement regarding the duties". Two columns need a computed stamp key and break `test_every_schedule_column_binds_to_a_live_acord_field`. Engineering default: one column, placeholder "Field employees - roofing installation" | H3 | 2026-08-27 | **OWNER 2026-08-27: "fix things properly" - engineering default authorised.** Shipped (H3-B) |
| Q26 | **H3 8.2 ACORD 130 `Individual_IncludedExcludedCode` vocabulary** - the tooltip says only "Included or Excluded"; the printed form column reads INC / EXC. Engineering default: stamp "INC" / "EXC" from the two extracted booleans | H3 | 2026-08-27 | **OWNER 2026-08-27: "fix things properly" - engineering default authorised.** Shipped (H3-B) |
| Q27 | **H3 8.2 officers table PRODUCER-only, whole table?** C4 already routes `wc_officers` to the producer (4.4 "owner/officer inclusion/exclusion"); officer NAMES are factual but the treatment is judgment, and one table cannot split audiences by row. Engineering default: producer-only, whole table (needs a table-level `producer_only` flag - today `_finalize_schedule_taxonomy` forces EVERY table to the client) | H3 | 2026-08-27 | **OWNER 2026-08-27: "fix things properly" - engineering default authorised.** Shipped (H3-B) |
| Q28 | **H3 8.2 retire the free-text `wc_payroll_by_state` client question once the group table carries a state per row?** Plan derives the by-state map from the rows (every row must have state AND payroll, labelled `derived`, never overwriting a stated value - D28); the scalar question then falls out as already-provided. Engineering default: yes | H3 | 2026-08-27 | **OWNER 2026-08-27: "fix things properly" - engineering default authorised.** Shipped (H3-B) |
| Q29 | **H3 - is a "group rows do not sum to the stated WC payroll" warning wanted?** NOT built. It is a NEW validation rule (Principle 7 / precedence note); the existing 20% `wc_payroll_mismatch` compares wc_payroll to total_payroll only. Engineering default: not built until ruled | H3 | 2026-08-27 | **NOT BUILT (H3-B).** The precedence note forbids a new validation rule without product approval; the owner's go-ahead covered the defaults, not a new rule. Needs Brent - not yet in `20Aug_questions_brent.md` (owner to say if it should be) |
| Q30 | **H3 - let the dormant 10% state-total-vs-total-payroll HARD STOP go live?** `_check_wc_multi_state_payroll_breakdown` reconciles only a LIST shape while the merge has always written a DICT, so `wc_state_payroll_total_mismatch` has never fired on live data. It is spec, dead by accident - but waking it can cap packages at 60 that were never capped (D6, scores DOWN). Engineering default: fix the shape and let it run | H3 | 2026-08-27 | **OWNER 2026-08-27: "fix things properly" - engineering default authorised.** Shipped (H3-B) |

| Q31 | **Physical address is charged in the ACORD 125 fill rate on EVERY package.** Section 9.1 says it "Applies When: Exposure/location requires it" with the key rule *"Do not universally require"*, and 3.12 already makes the WARNING exposure-gated - but `sqs_service.FORM_FIELD_INVENTORY["ACORD_125"]` lists `physical_address`, so `calculate_sqs_from_facts` counts it as an owed field on a single-location GL-only account that needs no separate premises address. Engineering did NOT change it: removing an inventory entry moves scores UP on those accounts, which is a scoring decision, and D32 forbids fixing it by silencing the question instead (the package would keep paying for a blank nobody can be asked for). Options: (a) leave it - one owed field, uniform across packages; (b) make the entry conditional on the same exposure test 3.12 uses | H4 | 2026-08-27 | |
| Q32 | **The client is asked for a WC payroll-by-class-code breakdown that the H3 employee-group table already collects.** `narrative_growth_trends` is a narrative slot repurposed to ask for class code + description + payroll; H3 correctly routed it to the producer, but it is still INJECTED alongside the table that answers it (and the X-Mod is likewise asked twice, via `wc_xmod` and `narrative_target_markets`). Suppressing the injection is not free: `_narrative_enrichment_present` credits the Narrative Quality component ONLY from that fact key, so dropping the question costs ~5 points of that pillar on every WC package unless the component is re-credited from the table rows. Engineering default: NOT changed - a D6 score move nobody has signed off | H4 | 2026-08-27 | |

| Q33 | **A declarations page's EXPIRING policy term wins the merge and stamps into ACORD 125's PROPOSED EFFECTIVE DATE box.** Measured 2026-08-27: `_DOC_TYPE_PRIORITY` ranks `dec_page` (0) above `application` (1), so on the most common upload shape - current dec page + new application - `merge_facts` gives `effective_date` the term that is ENDING. RC1b fixed this for RENEWALS via `_route_renewal_dates` (gated on `is_renewal` AND an already-ended term); a rewrite to a new carrier is neither and falls through, and `_resolve_renewal_proposed_period` is gated on the same flag so the box is not even an owned blank. Engineering did NOT fix it: it is a change to primary-truth selection, which every fact flows through, and it has had no adversarial round. Recommended shape: extend RC1b rather than reorder the priority list - for `effective_date` / `expiration_date` ONLY, a PROSPECTIVE document (application / supplemental application / quote) outranks a BOUND one (dec page / policy / certificate / binder / endorsement), and the bound term routes to the existing `prior_*` namespace. **The cross-document date hard stop is currently the only thing on any screen pointing at this box, which is why it must not be silenced first** | H4 | 2026-08-27 | |

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

---

## Session 2026-08-26 - C4 Contextual Questionnaire Logic (client section 4)

**Source documents:** the client's "4. Contextual Questionnaire Logic" master-plan
section and `v1-core-principles.md`. Both take precedence over
`SQS_Scoring_Specification.docx.pdf` where they conflict.

### C4-A - What the client is actually asking for, and what was already shipped

Audited every clause of section 4 against the code before writing a line.
**Roughly two thirds of section 4 was already built.** Recorded so nobody rebuilds it:

| Clause | State before this session |
|---|---|
| 4.1 vocabulary | `fact_state.py` already writes `value_state` / `evidence_state` in the client's exact words |
| 4.5 normalisation | 5 of 8 items already fold silently through `fact_comparison` -> `fact_equivalence` |
| 4.6 client-answer conflict | Shipped in C1-D (`client_answer_review.py`) |
| 4.12 (1) coverage | `_drop_not_applicable_questions` existed on 2 of 3 paths |

**The one real hole:** `question_classifier.classify_question` decides WHO answers a
question by matching substrings against the FIELD NAME plus membership in the SQS
scoring tiers. It takes no `facts` argument and reads neither state axis. The
client's whole 4.1 flow is about state. The machinery existed; the questionnaire
had never been plugged into it.

### C4-B - THE DECISION THAT MATTERS: Step 3 is not implemented literally

Step 3 reads *"is the value merely Suggested? ... the client MAY be asked."*
Implemented literally this re-asks nearly the entire package. **Measured, not
assumed**, against the real writers on 2026-08-26:

* `extraction_service._annotate_facts` (line ~1566) writes
  `confidence: "ai_high" | "ai_low"`, `source: "ai"` on EVERY extracted fact.
* `fact_state.derive_evidence_state` returns SOURCE_VERIFIED only for
  `verified_in_text is True`, `source in {dec_entry, policy_doc_text}`, or
  `confidence in {deterministic, filled}`.
* `verified_in_text` has exactly ONE writer in the whole backend
  (`extraction_service.py:7096`, the dec-entry backfill).

**So virtually every LLM-extracted fact is `evidence_state == "suggested"`.**
Un-suppressing them all would rebuild the "full insurance application" the
client's own Desired Outcome and 4.12 forbid.

**Implemented instead:** a Suggested value changes ROUTING, not whether we ask -
which is Step 3's own second sentence. A Suggested value on an INSURANCE-JUDGMENT
fact goes to the producer; a Suggested value on an ordinary business fact stays
suppressed exactly as today. Low volume, matches the clause, cannot flood anyone.

**This is the honest limit of C4:** until something writes `verified_in_text` on
ordinary extracted facts, Step 2's "Source Verified" and Step 3's "merely
Suggested" are not distinguishable for most of the package. Closing that is an
EXTRACTION change (a grounding-quote check per fact), not a questionnaire one, and
was deliberately NOT bundled here. **Flagged for Brent, see C4-F.**

### C4-C - The one door: `services/question_eligibility.py` (new)

Same pattern as `fact_comparison.py` and `answer_semantics.py`. Holds the client's
Step 1-5 flow and the 4.4 routing table (`INSURANCE_JUDGMENT_FACTS`, 43 facts,
every key verified to exist in `FACT_REGISTRY`).

**Structural safety property, not a careful one:** every overlay it can emit does
one of three things - move a question CLIENT -> PRODUCER, suppress it, or hold a
conflicting fact for the producer. **There is no code path that routes anything TO
the client.** So a bug here can only ever produce "the producer sees one item too
many", never "the insured was asked something they cannot answer". Pinned by
`test_overlay_never_widens_client_exposure`, which drives EVERY registry fact.

**Ordering note.** The client lists Conflicting as Step 5, but it is evaluated
FIRST. A conflicting fact carries a VALUE, so `_fact_is_filled` marks it "already
provided" and the already-known branch would swallow it before Step 5 could route
it. Pinned by `test_conflicting_beats_already_known`.

**Wiring:** `decorate_questions` gained an OPTIONAL `facts=` argument. Omitting it
skips the overlay entirely, so every legacy call site is byte-identical
(`test_missing_facts_argument_changes_nothing`). All three generation paths now
pass it.

**Path parity fixed while here:** `generate_cross_form_arq_questions` was the only
one of the three paths that never ran `_drop_not_applicable_questions`, so a
cross-form conflict about a declined coverage was still asked. It now runs it with
the same arguments and the same fail-open behaviour as path A.

### C4-D - Routing moves, and the two reversals

Moved to producer per 4.4 + core principle 5: all GL/umbrella/auto/garage limits,
all deductibles, valuation method, coinsurance, period of restoration, business
income limit, retro date, X-Mod (+ its effective date), WC officer
exclusions/officers, WC payroll period, WC + GL class codes, covered-auto symbols,
`lines_of_business`, `effective_date`.

**Deliberately NOT moved** (4.3 keeps them client-eligible), listed explicitly in
`CLIENT_ELIGIBLE_DESPITE_TOPIC` so a future tidy-up cannot sweep them in by
pattern: building/BPP values, construction type, occupancy, year built, roof year,
sprinkler, fire protection class, total/WC payroll, payroll by state, percent
subcontracted, radius of operation.

**TWO REVERSALS OF OUR OWN TESTED DECISIONS.** Both were deliberate, both pinned,
both now overruled by the client - the same shape as the 2026-08-12 NAICS reversal:

1. `_CLIENT_WHITELIST` kept `gl_class_codes` / `wc_class_codes` client-facing with
   the note *"Same carrier-assigned argument arguably applies; flagged, not
   assumed."* 4.4 and principle 5 name them explicitly. Flag resolved, entries
   removed. (`gl_class_codes` was never a real registry fact - only
   `gl_class_codes_by_location` is.)
2. `test_desired_limits_stay_client_not_agency` pinned the July ruling that
   "coverage intent -> Agency" must not drag DESIRED limits out of the Client
   bucket. 4.4 says "Coverage limits" are producer-only. Test rewritten as
   `test_coverage_limits_route_to_the_producer`, with the reversal recorded in its
   docstring. `property_building_value` kept in the test precisely because it must
   NOT move.

`test_c3_sqs_integrity.py::test_tier2_removals_are_still_asked_for` was updated,
not deleted: the property it protects is *"we still ASK"*, not *"we ask the
CLIENT"*. X-Mod / payroll period / officer exclusions now assert audience=producer
AND bucket=agency; payroll and claims stay client.

**No score moves.** Verified rather than assumed: `sqs_service` mentions
`question_classifier` only in a COMMENT and never imports it, and neither
`audience` nor `bucket` is read anywhere in the scorer. Re-routing changes who is
asked, never a number.

### C4-E - The hidden Underwriting bucket

`SHOW_UNDERWRITING_REVIEW_BUCKET = false` in `AcordModal.jsx` (client request,
temporary). **I initially warned the owner that re-routed questions would vanish
into it. That was wrong and is corrected here:** `AUDIENCE_PRODUCER` maps to
`BUCKET_AGENCY`, and the Agency bucket renders unconditionally - it has no `SHOW_`
flag. Nothing disappears.

Because that mistake was easy to make, it is now impossible to repeat silently:
`test_no_judgment_fact_lands_in_a_hidden_bucket` fails the build if any
producer-routed fact lands in the hidden bucket.

Kept hidden as instructed. Fixed FOR its return: `ARQ_ELIGIBILITY_META` renders the
new reasons ("Producer decision", "Conflict - resolve", "Not applicable", "Could
not determine"), visible in Agency today and already correct when the flag flips.

Also verified safe rather than assumed: every select-all predicate in the modal
gates on `isClientFacing`, so hidden rows can never be ticked, and the init effect
force-deselects them.

### C4-F - OPEN FOR BRENT / PRODUCT

1. **Nothing verifies an extracted value against the document text**, so almost
   every fact is `suggested` and Step 2 vs Step 3 cannot be told apart. Closing it
   is an extraction change. Do we want it, and at what LLM cost?
2. **`claims_made` and `prior_acts` are not canonical facts.** Claims-made is a
   FLAG (`gl_is_claims_made`); prior acts exists only as a cross-form question
   field. 4.7 names both as GL-relevant. Needs a product call before adding facts.
3. **Five 4.3 client-eligible items have no question at all**: states of
   operation, payroll by group, employee/job groups, actual job duties, new-venture
   confirmation. Not built in this session - they are new facts + new questions,
   not routing.

### C4-G - Verification

Full backend suite: **4373 passed, 1 failed, 14 skipped**. The single failure is
`test_arq_acord125_missing_only`, the known pre-existing `httpx`/`openai`
`ImportError: cannot import name 'URL' from 'httpx'` - documented in CLAUDE.md and
unrelated. `test_normalization`, the other historical failure, now passes.
**Zero regressions.** New: `tests/test_question_eligibility.py` (44 tests).
Frontend production build verified clean.

**Not taken on faith:** the 44 new tests passed on their first run, which this file
has repeatedly shown is a reason for suspicion. Routing was re-verified by driving
`decorate_questions` directly and printing before/after for six facts - three moved
to producer/agency, three stayed client/client.

### C4-H - Live test fixtures

`backend/scripts/make_c4_test_pdfs.py` -> `test_data_c4/` (9 PDFs + README).
Seven scenarios, one per testable clause: S1 GL+property routing, S2 WC, S3 auto,
S4 umbrella, S5 conflicting revenue (2 files), S6 same-facts-different-printing
(2 files), S7 declined property with a select-ACORD-140 control run.

Fixture self-check is executable, not a comment: S7 is scanned after generation
and the script EXITS NON-ZERO if any property characteristic leaked into it,
because that absence is the entire scenario. Text was read back through
pdfplumber to confirm no column interleaving (the 2026-08-22 defect).

S6's expected result was predicted offline through the real `fact_comparison.
verdict` door before shipping the fixture - all five variant pairs (LLC/L.L.C.,
E 9 Mile St/East 9 Mile Street, CO/Colorado + ZIP+4, entity type, spaced policy
number) return `same`. If S6 raises a conflict live, the defect is in the
comparator's CALLERS, not in normalisation.

**Stated in the README rather than implied:** a click-through cannot separate 4.1
Step 2 from Step 3 (see C4-B), and 4.6 needs a send-and-answer round trip these
files cannot drive.

### C4-I - Live test run 2026-08-26, and the four defects it found

**Owner ran S1-S7 through the real app.** The run did what a click-through is for:
it found four defects no unit test caught, three of which are the same shape -
**a routing rule keyed on a NAME instead of on the canonical fact.**

**What passed.** S1: retro date, valuation, AOP deductible and coinsurance all
reached Agency carrying the "Producer decision" badge, and ZERO limits /
deductibles / class codes reached Client - the headline defect is fixed. S6: no
conflict on address, ZIP, LLC/L.L.C. or the spaced policy number (4.5 confirmed
live, matching the offline `fact_comparison.verdict` prediction). S7: no property
question of any kind on a package declining property (4.12 criterion 1). S3:
vehicle and driver tables stayed Client (4.9).

**FIXES**

1. **SIC reached the CLIENT on ACORD 130.** The field is `NamedInsured_SICCode_A`
   -> `namedinsured_siccode_a`, which does NOT contain `_PRODUCER_PATTERNS`'
   entry `"sic_code"` - the pattern carries an underscore, ACORD's name does not.
   `naics_code` / `sic_code` had been left OUT of `INSURANCE_JUDGMENT_FACTS` on
   the assumption the name pattern covered them. **That assumption is the exact
   fragility this module exists to remove**; both are now in the table, so
   routing no longer depends on how a given form spells the field.

2. **The X-Mod question reached the CLIENT.** `arq_service._FIELD_QUESTION_MAP`
   maps `narrative_target_markets` to *"What is your workers comp experience
   modifier (EMOD / XMOD)?"* - an X-Mod question wearing a narrative key, so
   `wc_xmod` never matched it. It is NOT a `FACT_REGISTRY` fact, so it cannot go
   in the main table without breaking the anti-rot guard; new
   `INSURANCE_JUDGMENT_QUESTION_KEYS` holds it, and
   `test_judgment_question_keys_are_not_registry_facts` fails the build if the
   two tables ever start overlapping. The test also asserts the question TEXT
   still asks for the EMOD, so the entry retires itself if the key is repurposed.

3. **"Please list the vehicles to be insured" on ACORD 131 and ACORD 25.**
   `schedule_capture.schedule_list_key_for_field` falls back to a loose
   `base.startswith(prefix + "_")` match, so ACORD 131's
   `Vehicle_CombinedSingleLimit_EachAccidentAmount_A` (an umbrella underlying
   limit) and ACORD 25's `Vehicle_AnyAutoIndicator_A` (a certificate coverage
   box) were both claimed as fleet rows. Neither form has a vehicle schedule.
   **The loose fallback is deliberately LEFT INTACT** - ACORD 127 resolves 268
   genuine vehicle fields through it. New `binds_a_capturable_column` answers the
   different question the caller actually needs (*is this a column the client
   could type into?* = an EXACT registry hit), and `_partition_schedule_fields`
   now runs two passes: pass 1 finds forms with a real column, pass 2 collapses
   only those. Measured: 131 loose=4/capturable=0 -> no question; 25
   loose=16/capturable=0 -> no question; **127 loose=268/capturable=36 -> schedule
   still works.** A form with no capturable column KEEPS its fields on the
   ordinary question path - `test_partition_does_not_lose_a_field_it_declines_to_
   collapse` pins that, because collapsing into a schedule that is never asked
   would be silent data loss.

4. **"Needs client input: NAICS or SIC industry code"** on the Submission
   Readiness banner (`AcordModal.jsx`). A SECOND surface, independent of the
   questionnaire, telling the producer to ask the insured for a classification
   code Primble now routes to the agency. Its own comment claimed *"every field
   this check tracks ends up asked via the client questionnaire"* - true when
   written, false since C4-D. Relabelled "Still needed:", accurate for both
   audiences, one line preserved.

**Standing lesson, and it is the same one C4-B already recorded once:** three of
these four are a rule keyed on a field NAME. The client's whole section 4 is a
complaint about exactly that. When adding a routing rule, key it on the canonical
fact; a name pattern is a fallback for uncurated fields, never a routing decision.

**Fixture weakness, recorded honestly.** S2, S3 and S4 STATED the judgment values
in the document, so they extracted and were correctly suppressed as
already-provided - meaning those three scenarios could not exercise the routing
they were written for. All live routing evidence came from S1 and S6. The
regenerated fixtures must OMIT any value whose routing the scenario is testing.

**Verification.** Full backend suite **4378 passed / 1 failed** - the same known
`httpx`/`openai` `ImportError` documented in CLAUDE.md, unrelated. Zero
regressions. Five new regression tests, each replaying the live defect with the
literal ACORD field name. Frontend production build clean.

**Still unproven after this run:** 4.1 Step 5 (S5 raised no revenue conflict and
no conflict tag - S5B classified "Financial Statements / Needs review", so its
facts may never have merged), package SQS scores (never reported, so the
"routing must not move a score" check is unverified live), and S7's ACORD-140
control run.

### C4-J - Fixtures rebuilt on an executable OMIT contract (2026-08-26)

The first fixture set could not test what it was written to test: S2, S3 and S4
each PRINTED the judgment values whose routing they existed to prove, so
extraction found them, `_fact_is_filled` marked them already-provided, and no
question was ever generated. Three scenarios produced zero routing evidence and
looked like passes.

**The rule, now written into the generator and enforced by it:** a scenario can
only test the ROUTING of a value it does NOT state. Each scenario STATES only
what makes the coverage applicable and OMITS exactly the values under test.

`_FORBIDDEN` is that contract as code - a per-file list of terms that must be
absent - and `make_c4_test_pdfs.py` EXITS NON-ZERO if any reappears. It caught
its own author on the first run: S4 closed with prose naming "follow form
status", one of the terms S4 omits. A comment-only rule would not have.

Eleven files now (was nine). S5B changed from a "Financial Summary" to a second
APPLICATION - the live run classified the old one as Financial Statements /
Needs review, so its facts may never have merged and the revenue conflict the
scenario exists to create was never created. S3 driver hire dates are now full
MM/DD/YYYY (the live run showed "3 rows need attention" on every driver from a
bare year). NEW S8 (application + loss run listing 2 claims / $65,700) makes
clause 4.6 testable end to end for the first time: the client attests "no
losses" against a document that reports two.

Still not testable by clicking: 4.1 Step 2 vs Step 3, for the reason in C4-B.

### C4-K - Live run round 2: four root causes, all in shared plumbing (2026-08-26)

The rebuilt fixtures did their job. S1 came back a clean pass (18 Client / 18
Agency: every property characteristic Client, every limit, deductible, valuation,
coinsurance, business income and period of restoration Agency), S6 confirmed 4.5
live, S7 run A confirmed 4.12, and the round-1 fixes (SIC, EMOD, officer
exclusions, phantom vehicle schedule, banner copy) all held. **Scores did not
move: S7 run A 71, run B 71.**

Four failures remained. **None of them was in the C4 routing layer** - every one
was a hole in shared plumbing that the routing work merely made visible.

**1. ACORD 130 produced TWENTY ordinal location cards** ("...(1st location)"
through "(19th location)"). This was a REGRESSION FROM MY OWN C4-I FIX:
`binds_a_capturable_column` correctly reported that no real column bound on that
form. It was right, and that was the hole - the `Location_PhysicalAddress_*`
family was **never registered** in `pdf_service._SCHEDULE_REGISTRY`, on
**ACORD 130, 133, 160 and 28**. So those addresses could never be STAMPED from a
known `property_locations` list either; they fell through to gap fill. Registered
the seven address columns. Measured after: 130 21/24 capturable, 133 23/25, 160
15/19, 28 5/6 - all collapse; 131/25/160 vehicles still correctly suppressed
(0 capturable); ACORD 127 still 36. Deliberately NOT registered:
`Location_HighestFloorCount`, `Location_FullName`, `Location_TaxCode`,
`Location_LocationDescription`, `Location_PrimaryPremisesIndicator`,
`Location_Primary_PhoneNumber` - not columns of the location table.

**2. Selecting ACORD 140 did not bring the property questions back** (S7 run B:
140 scored 8/100 with not one property question). TWO doors had the same hole and
neither honoured the producer override:
  * `arq_service._drop_not_applicable_questions` applied the override in its
    early-exit GATE, then called `is_not_applicable`, which re-reads the FULL
    denied set;
  * `pdf_service.apply_fact_state_confidence_labels` labels a box
    `not_applicable`, and the ARQ form scan skips every field with that label.
Fixed with ONE door - `fact_state.is_not_applicable_for(facts, key, form_ids)` -
that both now call, plus `fact_state.lines_applied_for`. An envelope explicitly
marked `not_applicable` (a human said so) is never overridden: that is a
statement about the FACT, not an inference from a coverage line.

**3. The revenue conflict was detected and then dropped on the floor.** S5 showed
"All clear" with no revenue item anywhere. Replayed offline:
`assess_underwriting_consistency` returns `status=conflict, review_required=True`
and the pipeline correctly writes `_uw_conflicted_keys`. **The engine was never
the problem.** A conflicted fact HAS a value, so `_fact_is_filled` calls it
already-provided and the coverage-guarantee injector skips it - no question is
built, and `question_eligibility`'s Step 5 overlay can only decorate questions
that EXIST. Conflicted facts are now re-admitted to the injector; the door then
routes them to the producer tagged "Conflict - resolve". They can never reach the
client - that door has no path to the client audience.

**4. ACORD 127 was the ONLY form with an EMPTY `FORM_FIELD_INVENTORY`.** The
coverage-guarantee injector walks that table, so a Business Auto package asked
the client for vehicles and drivers and asked NOBODY for the liability limit,
comp/collision deductibles, physical-damage valuation or covered-auto symbols.
Added the nine-entry inventory. Two of them (`auto_covered_symbols`,
`auto_physical_damage_valuation`) had no curated question either, so the injector
would still have skipped them silently - both added, worded for the producer,
since 4.9 makes them producer-only and that is now the only audience that reaches
them.

**THE PATTERN, AND IT IS THE SAME ONE AS C4-I.** Round 1 was three rules keyed on
a field NAME. Round 2 is four tables with a MISSING ROW - an unregistered field
family, an override applied in one of two doors, a question that was never built,
an inventory that was empty. Every one is silent by construction: an empty entry
produces no question and no error. Hence
`test_no_form_has_an_empty_inventory`, which fails the build if any form's
inventory goes empty again, and
`test_acord130_locations_collapse_into_the_table`, which drives the four real
schemas rather than a fixture.

**KNOWN RESIDUAL, not fixed, stated rather than buried:** the client-facing
vehicle table still carries `comp_symbol` / `coll_symbol` columns. 4.9 makes
symbols producer-only, and there is now a producer question for them, so the
columns are a duplicate route. They are optional and bind to real ACORD 127
boxes, and hiding a column from the client but not the producer needs frontend
work the schedule renderer does not have. Flagged for a decision, not silently
left. Also unfixed: umbrella attachment point and follow-form still surface no
question (they are producer-routed by pattern but have no inventory entry on 131).

**Verification.** Full suite **4378 passed / 1 failed** - the known
`httpx`/`openai` ImportError documented in CLAUDE.md, unrelated. Zero
regressions. `tests/test_question_eligibility.py` now 55 tests.

### C4-L - Round 3: the two deferred residuals, and why S5 could never have worked

Round 2 was verified live: **S2's twenty location cards collapsed to one table,
S3's auto structure (liability limit, covered-auto symbols, comp + collision
deductibles, physical-damage valuation) all appeared in Agency, and S7 run B
brought the property questions back (Property - 9).** S5 still showed nothing.

**I had deferred two items with "your call" and the owner rightly pushed back.
Both are now fixed, and chasing the first one uncovered the S5 root cause.**

**THE S5 ROOT CAUSE - `conflicting` was unreachable in production.**
`derive_value_state` tested one key:

    facts["_uw_conflicted_keys"]     <- built by `unresolved_withheld_keys`,
                                        which filters on CONFLICT_WITHHOLD_KEYS
                                        ... and that frozenset is **EMPTY**, by
                                        Brent's Q4 / D16 ruling that a
                                        conflicted value still stamps.

So the key is never populated and the branch never fired. The real set is the
SUPERSET the pipeline writes at `extraction_pipeline.py:895`,
**`facts["_uw_conflict_keys"]`** (no "-ed"), from `unresolved_conflict_keys` -
every fact the documents still disagree about, whatever the stamping decision.
One character apart, and every reader was on the wrong one.

**Whether a fact IS conflicting and whether we WITHHOLD its value are two
different questions.** `derive_value_state` answers the first, so it now reads
the superset (both keys, union). C4-K's re-admission fix was necessary but not
sufficient: it put the question back on the list, and then the state said
`present`, so the Step 5 overlay had nothing to tag. Verified end to end:
`value_state -> conflicting`, question routes `producer / agency /
conflicting_route_to_producer`.

`test_conflicting_is_reachable_from_the_superset_key` asserts
CONFLICT_WITHHOLD_KEYS is still empty, so if Brent ever reverses D16 the test
tells the next person to re-check which key is the right signal.

**RESIDUAL 1 - covered-auto symbols were a second route to the wrong audience.**
4.9 makes symbols a producer decision and C4-K gave them a producer question,
but `comp_symbol` / `coll_symbol` remained columns in the CLIENT's vehicle
table. `Column` gained a `producer_only` flag, honoured in exactly ONE place -
`arq_routes.client_view`, where the client's copy of the table is built. The
producer's table (served whole by `/generate`), the schedule pre-load endpoint
and the stamping path all keep every column, so nothing the agency fills is
lost. Client now sees year / make / model / vin / body_type / gvw.

**RESIDUAL 2 - the umbrella asked for a limit and an SIR and nothing else.**
4.11 names seven items; ACORD 131's inventory carried two. Added
`umbrella_attachment_point`, `umbrella_follow_form`, `underlying_policies` and
`employers_liability_limits` to the inventory, wrote the three missing curated
questions, and named `underlying_policies` in `INSURANCE_JUDGMENT_FACTS` (the
`_AGENCY_PATTERNS` entry is "underlying_insurance", which does not match it).
All four verified routing to producer / agency.

**THE ANTI-ROT TEST THEN FOUND 54 MORE.**
`test_every_inventory_fact_has_a_question_or_is_a_schedule` generalises the
shape that hid BOTH the ACORD 127 and ACORD 131 gaps - an inventory entry with
no curated question, skipped in silence by the coverage-guarantee injector - and
it immediately reported **54 entries across 12 forms** (137/138 garage and
auto-structure facts, 141/160 inland-marine items, 186 contractor supplemental,
133 builders-risk, ACORD 101 remarks, and more).

**They are NOT fixed, and the test was NOT weakened to hide them.** Each needs
real plain-language wording and an audience decision - a product call, not a
rename. The known set is pinned as `KNOWN_WITHOUT_A_QUESTION` so the count can
only go DOWN: a NEW entry fails the build immediately, and REMOVING one without
updating the baseline also fails, so the ratchet keeps tightening. Recorded here
rather than hidden, per the no-silent-caps rule.

**Verification.** Full suite **4388 passed / 1 failed** - the known
`httpx`/`openai` ImportError, unrelated. Zero regressions.
`tests/test_question_eligibility.py` now 59 tests. Frontend build clean.

**Lesson, and it is the third variant of the same one.** C4-I was rules keyed on
a field NAME. C4-K was tables with a MISSING ROW. C4-L is a reader on the WRONG
KEY - `_uw_conflicted_keys` versus `_uw_conflict_keys`. All three are silent by
construction: no exception, no log, just a feature that never fires. The only
defence that has actually worked in this arc is a test that enumerates the real
data (all 17 schemas, the whole inventory) instead of asserting one example.

### C4-M - S4 confirmed; S5 narrowed to writer-vs-reader (2026-08-26)

**S4 PASSES live.** All four 4.11 umbrella items now render in Agency -
attachment point, follow-form confirmation, Schedule of Underlying Insurance and
Employers Liability limits. Agency count 13 -> 19.

**Polish found by the same run:** five of the questions added in C4-K/C4-L had no
`_FIELD_PRODUCER_LABEL_MAP` entry, so the card fell back to the FULL question
text as its title - "At what underlying limit does the umbrella attach? (For
example: ...)" sitting beside short rows like "Umbrella SIR". Labels added for
umbrella_attachment_point, underlying_policies, employers_liability_limits,
auto_covered_symbols and auto_physical_damage_valuation. Cosmetic, but it made
the new work read as unfinished.

**S5 STILL SHOWS NO CONFLICT, and the fix is not disproven - it is unverified.**
C4-L fixed the READER (`derive_value_state` now consults `_uw_conflict_keys`).
Offline that is proven: the engine returns status=conflict and the question
routes producer/agency/conflicting_route_to_producer. What is NOT proven is that
the WRITER fires on the live session - i.e. that `assess_underwriting_consistency`
flags the two revenue figures when run over the real per-document facts, and that
`_uw_conflict_keys` survives onto the session the ARQ generator reads.

Guessing further would be the third round of reasoning against the code instead
of against a real session - the exact mistake `dump_session_facts.py` was built
to end. That script already replays the conflict engine (section 6); it now also
prints **section 4b, `_uw_conflict_keys`**, so one run separates the two cases:

  * section 6 lists a total_revenue conflict but 4b is "(none)"  -> PERSISTENCE:
    the key is computed and lost before the questionnaire sees it.
  * section 6 lists nothing                                      -> DETECTION:
    the engine does not flag it on the real per-document facts, and the S5
    fixture or the extraction is what needs changing, not the routing.

Command: `py backend/scripts/dump_session_facts.py <session_id>`.

**Suite 4388 passed / 1 failed** (known httpx ImportError), zero regressions.

### C4-N - S5 isolated to DETECTION, and the diagnostic that was still ambiguous

The owner ran `dump_session_facts.py` on the live S5 session. It settles the
writer-vs-reader question from C4-M **decisively**:

  * section 3 - DOC 1 `total_revenue = $2,400,000`, DOC 2 `total_revenue =
    $3,850,000`. Both documents carry the fact, with different values.
  * section 4b `_uw_conflict_keys` = **(none)**
  * section 6 CONFLICT REPLAY = **0 conflict rows, 2 active documents**

So this is **DETECTION, not persistence**. The C4-L reader fix is correct and
necessary, but nothing ever reaches it: `assess_underwriting_consistency`
produces no conflict row for `total_revenue` on the real session, even though the
two per-document values plainly differ.

**Five offline replays, all flagging conflict** - envelope facts and bare
scalars; 2-key and full 179-key per-document fact sets; application/application
and application/financial_statements; document text under `raw_text` and under
the real `text` key (so the Pass-2 scan genuinely ran). Every one returned
`total_revenue -> conflict [$2,400,000, $3,850,000]`. **The offline harness
cannot reproduce the live behaviour**, which is the C4-B lesson repeating: an
offline probe proves the FUNCTION, never the SEAM around it.

**Why the diagnostic could not close it either.** Section 6 printed only rows
whose status is `conflict`. That cannot distinguish "the engine never assessed
this field" from "it assessed it and called it consistent" - and those need
OPPOSITE fixes. Printing the negative space is the whole point of a diagnostic;
omitting it cost a full live round. Section 6 now prints:

  * every assessed field with its status, review flag and grouped values;
  * the `uw_confirmations` on file (a confirmed field is reported resolved, not
    conflicting - a silent suppressor nothing was showing);
  * the reconcilable fields NEVER assessed, so an absent field is visible as
    absent rather than inferred from a missing line.

**Next run answers it in one shot:** `total_revenue` present with
status=consistent means the grouping merged two different amounts (a
`fact_equivalence` / normalisation defect); absent from the assessed list means
the field never entered the sweep (a gating defect); present under
confirmations means a stored confirmation is suppressing it.

Nothing was changed in the conflict engine this round - changing code against a
hypothesis the data has not confirmed is what the C4 arc keeps punishing.

### C4-O - S5: assessed, one value group, and the two candidates left (2026-08-26)

Section 6 with the C4-N instrumentation returned the decisive line:

    total_revenue   consistent   review=False   [$2,400,000]
    confirmations on file: (none)

So: the field IS assessed (not a gating miss), nothing is confirmed (not a
suppressor), and it resolves to **ONE value group** even though section 3 shows
DOC 1 = $2,400,000 and DOC 2 = $3,850,000.

**Ruled OUT this round, each by direct execution rather than reading:**
  * `fact_comparison.verdict("total_revenue", "$2,400,000", "$3,850,000")` ->
    `different`. Same for payroll, GL limits, building value, employee counts.
    The comparison door is correct.
  * `document_witnesses("application", "total_revenue")` -> True. The client-1.2
    role gate is not dropping either document.
  * `_normalize` -> "2400000" / "3850000". The normalizer separates them.
  * `_fv` is a plain envelope unwrap - the same read the dump prints from.
  * Seven offline replays now: envelope vs bare scalar, 2-key vs full 179-key
    fact sets, application/application vs application/financial_statements, text
    under `raw_text` vs the real `text` key, and with `dec_page_entries` +
    `coverage_lines` present so the equivalence CONTEXT is built. **All seven
    return conflict with two groups.** The offline harness still cannot
    reproduce the live result.

**Two candidates remain, and they need opposite fixes:**
  1. both documents contribute and the two groups are merged AFTERWARDS ->
     an equivalence / grouping defect;
  2. only one document ever contributes -> a gating or data-shape defect.

Section 6 now prints, per assessed field, the SOURCE COUNT behind each value
group and the value `_fv` reads out of each document. One group carrying 2
sources is case 1; one group carrying 1 source, with the per-doc line showing
both amounts, is case 2. A row is no longer able to hide which one it is.

**No production code changed this round** - seven replays disagreeing with
production is a reason to instrument, not to edit.

### C4-P - S5: both documents contribute, and the collapse is in the GROUPING KEY

The C4-O instrumentation returned the decisive shape:

    total_revenue   consistent   review=False   [$2,400,000<-2src]
      engine reads per-doc: S5A=$2,400,000; S5B=$3,850,000

ONE value group carrying TWO sources, while `_fv` demonstrably reads two
different amounts. That is **case 1** from C4-O: both documents contribute and
the groups collapse. It is NOT a gating or data-shape defect.

**Ruled out this round, every one by execution:**
  * `_merge_equivalent_value_groups` / `fact_equivalence.equivalent_index` ->
    returns None for every differing-amount pair tried (revenue, payroll, GL
    limits, building value, employee counts), WITH and WITHOUT a real
    `PackageContext` built by `fact_comparison.build_context`. It is not
    folding them.
  * `_drop_class_exposure_candidates` -> keeps both groups even when
    `gl_class_code_schedule` carries BOTH amounts as class exposures (the S5
    fixture prints the class basis equal to the revenue in each file, which was
    the strongest hypothesis).
  * A ninth full replay, now with the real 179-key merged facts, both
    `coverage_lines`, `gl_class_code_schedule`, `gl_class_codes_by_location`,
    `locations` and per-document raw text -> `conflict [(2.4M,1),(3.85M,1)]`.

**What is left.** `groups` is keyed on `_normalize(raw, kind, fact_key)`. One
group with two sources means both documents produced the SAME normalized key at
runtime. Offline, `_normalize` returns "2400000" and "3850000" - distinct. So
either `kind` is not `currency` in the live call, or `_normalize` behaves
differently there. Nothing in the diagnostic showed the normalized key, which is
why nine replays could not find this: **the grouping key was the one step
between reading a value and declaring no conflict that was invisible.**

Section 6 now prints, per document, the value AND its normalized grouping key,
plus the resolved `kind`. Equal norms confirm the collapse is in normalisation;
different norms mean the live `groups` dict is not being built from these reads
at all, which would point at a second code path.

**No production code changed for four rounds on this defect** - nine offline
replays contradicting production is evidence the harness is wrong, not the
engine, and editing on that basis is how the C4 arc created its own regressions.

### C4-Q - The two remaining gaps closed at their root (2026-08-26)

Two of the three open items from the honest C4 status are now fixed, and both
turned out to be ONE defect wearing two faces: **a fact can be perfectly well
defined and still be unreachable, because the code reads a different table than
the one holding the answer.**

**GAP A - "a dozen client-eligible facts have no question."**
Wrong diagnosis. `fact_registry.FACT_REGISTRY[key]["question"]` already carried
good plain-language wording for most of them; the coverage-guarantee injector
gates on `arq_service._FIELD_QUESTION_MAP` ALONE, so a fact with a registry
question was silently skipped. Measured: of 42 inventory entries with no curated
question, **19 already had one in the registry**.

Fixed with one door - `arq_service._curated_question_for(field_name)` - which
reads `_FIELD_QUESTION_MAP` first (the client-tuned wording still wins, so no
rendered question changes by a character) and falls back to the registry. The
injector and the anti-rot test now both call it. That is `wc_payroll_by_state`,
`wc_description_of_operations` (job duties), `auto_radius_of_operation`,
`auto_garaging_addresses`, `gl_form_type` (claims-made status),
`umbrella_effective_date` / `_expiration_date` (policy periods) and eleven more,
in one line instead of 19 hand-copied strings that would drift.

`new_venture_indicator` was the ONLY 4.3 item with no question in either table;
written, client-facing.

**GAP A2 - 23 of the 42 were not facts at all.** `deductible_aop`,
`project_cost`, `owner_name`, `remarks_text`, `transit_exposure`... none exist in
`FACT_REGISTRY`. A phantom inventory key can never be filled or asked, **and it
inflates the fill-rate denominator**, so ACORD 133/141/160/186 have been scoring
against fields that cannot exist. 18 remapped to the real key they clearly meant
(`property_deductible_aop`, `builders_risk_project_cost`, ...), 5 that named
nothing were removed. **Those four forms' scores will RISE** - a correction, not
a regression. Pinned by `test_no_inventory_entry_names_a_fact_that_does_not_exist`.

The `KNOWN_WITHOUT_A_QUESTION` backlog is now **empty** and the ratchet is a
plain equality: any regression on either side fails immediately.

**GAP B - Step 2 vs Step 3 made real, deterministically and for free.**
`derive_evidence_state` calls a value `source_verified` only for
`verified_in_text is True`, a `dec_entry` source or a deterministic confidence -
and `verified_in_text` had exactly ONE writer in the backend. Every LLM-extracted
fact was therefore `suggested`, "Source Verified" was unreachable, and the
client's Step 2 could not be distinguished from Step 3.

New `fact_state.annotate_text_verification(facts, docs)`: a fact whose value is
LITERALLY present in the uploaded document text is marked verified. No LLM, no
cost - the same test `extraction_service._verify_dec_entries` already applies to
the dec index. Four guards, each load-bearing:
  1. only ever ADDS - absence of proof is never demotion;
  2. never overrides `user_confirmed` / `derived` / already-verified;
  3. a specificity floor of 4 normalised characters - "34", "CO" and "8" appear
     by accident in almost any document, and a FALSE verification is worse than
     none because Step 2 uses it to STOP asking;
  4. scalars only.
Verified safe for scoring first: `evidence_state` has exactly three readers in
the backend (the client-answer conflict gate, the audit export, and
question_eligibility) and **no scorer reads it**.

**Step 3 then completed, narrowly.** A judgment fact whose value is merely
suggested is re-admitted to the injector and routed to the producer to confirm -
which is Step 3's own second sentence. Deliberately bounded: insurance-judgment
keys only (~43, not 179), `suggested` only, producer-only. **It cannot add a
single question to the client's list.** Taken literally Step 3 would re-ask
nearly the whole package, which is the C4-B measurement and the reason this is
narrow rather than faithful.

**STILL OPEN, and honestly: S5.** Eleven offline replays cannot reproduce the
live collapse. Rather than a twelfth, `dump_session_facts.py` section 6b now
WRAPS every group-reducing step inside the real engine and reports what each did
to the real session data, plus the normalised grouping key per document. No
production code was changed for the conflict engine across five rounds - a
harness that disagrees with production eleven times is evidence about the
harness.

**Verification.** Full suite **4393 passed / 1 failed** (known httpx
ImportError), zero regressions, +5 tests (64 in test_question_eligibility.py).
Frontend build clean.

### C4-R - S5 SOLVED. `is_component_of` was silencing the conflict (2026-08-26)

Five rounds, twelve offline replays that all disagreed with production, and the
answer came from instrumenting the real engine rather than rebuilding the
harness a thirteenth time. Section 6b of `dump_session_facts.py` named it in one
line:

    total_revenue: _merge_equivalent_value_groups
       before 2: ['$2,400,000', '$3,850,000']
       after  1: ['$2,400,000']

**THE ROOT CAUSE.** `equivalent_index` has three context rules. Two were already
gated. The third, `is_component_of` ("one is a LINE figure, the other the
PACKAGE figure - a piece, not a rival"), was gated only by KIND:
`value_kind(fact_key) in {money, count, percent}`.

Measured: that admitted **75 registry facts** - every limit, every deductible,
employee counts, percentages - none of which is a premium, and a premium is the
rule's entire justification.

On S5 the verified dec index records the per-location class exposure
`$3,850,000` as a LINE-level value and the other document's revenue
`$2,400,000` as a PACKAGE-level one. `is_component_of` therefore pronounced a
genuine revenue disagreement "a piece of the other" and folded it. The producer
screen read **"All clear"** on two applications differing by $1.45M.

**THE FIX.** `_component_split_allowed` is now a NAMED SET
(`_COMPONENT_FACTS = {"total_policy_premium"}`), not a kind test. A part/whole
reading between two candidate answers to the SAME fact is real only where the
package figure is genuinely COMPOSED of line figures. That is premiums, and
nothing else on this schema: two documents stating the insured's revenue are
RIVAL ANSWERS, not a part and a whole. Registry facts admitted: **75 -> 0**;
`total_policy_premium` still qualifies (it resolves to money by KEY SHAPE, which
is why the kind gate covered it - the defect was breadth, never exclusion).

The per-class payroll case the kind gate was reaching for is already handled
properly by `underwriting_consistency._drop_class_exposure_candidates`, which
demands positive evidence from the package's own class schedule AND refuses to
touch an extraction-sourced candidate. That is the right mechanism; this one was
a blunt duplicate of it.

**A PINNED TEST WAS CHANGED, DELIBERATELY AND ON EVIDENCE.**
`test_a_quantity_still_gets_the_component_rule` asserted that
`gl_each_occurrence`, `umbrella_limit`, `total_payroll` and `num_employees` DO
get the rule, on the premise that "quantity" was a sufficient gate. S5 is live
proof it is not. Split into
`test_the_component_rule_survives_for_its_own_purpose` (premium only) and
`test_a_quantity_alone_does_not_get_the_component_rule` (the four, plus
`total_revenue`, `property_building_value`, `gl_deductible`). The guarantee got
STRONGER: fewer facts can now be silenced, not more.

**THIS IS THE THIRD TIME** a context rule keyed on a value's own characters has
destroyed a real conflict - C1-H/B14 (`different_owners`, the umbrella $1M
inheriting the GL policy's ownership), 2026-08-23 Run B (`is_component_of` on
two addresses), and now S5. The first two were fixed by gating the rule; this
one is fixed by gating it PROPERLY. The standing lesson: a rule that reasons
about a value's characters must name the FACTS it may speak about, and "kind" is
not specific enough to be that name.

### Suite status, stated precisely

`py -m pytest -q -p no:randomly` -> **4395 passed, 2 failed, 14 skipped.**
  1. `test_arq_acord125_missing_only` - the known `httpx`/`openai` ImportError
     documented in CLAUDE.md. Pre-existing, unrelated.
  2. `test_dec_index_purge::test_every_consumer_of_the_index_runs_at_or_before_
     generation` - flags `audit_service.py:1173` as a new `dec_page_entries`
     consumer. **NOT THIS WORK.** `audit_service.py` carries 331 uncommitted
     insertions from someone else's session, and line 1173 is a line that
     EXCLUDES `dec_page_entries` (`if key.startswith("_") or key ==
     "dec_page_entries": continue`) - a grep-based test flagging an exclusion.
     Left alone: it is not mine to decide.

**A note worth keeping:** the default run showed **8** failures, the fixed-order
run **2**. The suite uses `pytest-randomly`, and six of those eight pass both
individually and file-at-a-time - pre-existing cross-test pollution, exposed by
ordering, not caused by this work. Anyone measuring a baseline here should use
`-p no:randomly` or they will chase ghosts.

---

## Session 2026-08-26 - C5 Source Lineage & E&O Audit Record (client section 5)

### C5-A - Full audit + implementation - SHIPPED (2026-08-26)
**Priority:** V1-CRITICAL
**Principle(s) touched:** 1, 6, 7 (Preserve Provenance is the whole section)

**Problem.** The client's live audit sample: SOURCE DOCUMENTS "(none recorded)",
90 captured values labelled only "AI extraction from document", structured
values "Source: unspecified", no modification history, "Downloaded with 9 open
items" with no record of WHICH nine. His verdict - "the shape of an audit
record without sufficient provenance underneath it" - was correct, verified
symptom by symptom in code.

**Root cause - three classes, not thirteen bugs.**
1. *The record read the narrowest stores and skipped the richest.* The export
   read `session.doc_summary` - a key that only ever existed in HTTP responses
   (4 sites, all inside `JSONResponse`), never persisted - so SOURCE DOCUMENTS
   was "(none recorded)" on EVERY export since the feature shipped. It never
   read `acord_audit_log` (which records the FULL open-items list + score +
   checksum on every download), `underwriting_confirmation_audit` (C1's
   candidates snapshots - a table with NO READER anywhere), or `arq_receipts`.
2. *Provenance was a method enum, not a reference.* The fact envelope is
   `{value, confidence, source:"ai"}`; document identity dies in
   `merge_facts` (extraction_service.py:7864-7875, pseudo-partials drop
   filename), page numbers die at the OCR flatten (ocr_service.py:1776), and
   `_annotate_facts` passes lists/dicts through UNANNOTATED (:2315) - which is
   exactly the client's 5.6 "unspecified" list. `sqs_service.py:3192` says it
   in as many words: `"ai" = extracted from *some* document`.
3. *No append-only spine.* Reopen NULLed `action_at`; statuses/reasons upsert
   over history; two `log_field_change` call sites hardcoded
   `previous_value=None`; client-ARQ apply, schedule saves, restamps and
   retractions logged nothing; `update_pdf` REPLACED the fact envelope with a
   bare string (destroying provenance our own audit record then reported as
   "unspecified"); no SQS snapshot store existed.

**Fix.**
- *New door* `services/fact_lineage.py`: Document + Page attribution computed
  at export time by re-joining each merged fact against every document's OWN
  stored extraction (`docs[i].facts`) and its page-marked OCR text
  (`[Document page N]`, ocr_service). Sameness via `fact_comparison.values_agree`
  (D3 - one comparison owner); literal presence via `fact_state._verify_norm`
  with the same 4-char floor as `annotate_text_verification`. Right-or-blank
  for lineage: a page is cited only when locatable, a document only when its
  own extraction agrees or its text literally prints the value. Lists get
  contribution attribution (which doc supplied rows). Zero LLM cost.
- *Export rebuilt* (`get_audit_trail_export`): documents from `session.docs`
  (doc_summary kept as legacy fallback) with new `uploaded_at`/`uploaded_by`
  (stamped in extraction_pipeline); per-fact `sources`, `derivation`, `scope`
  (D19's `_scoped`), value/evidence states now derived WITH the facts dict
  (the conflicting / not_applicable branches were unreachable before -
  `derive_states` was called without it); `_`-sidecars and `dec_page_entries`
  no longer render as junk rows; `_rejected_facts` surfaced as "VALUES SEEN
  AND REFUSED"; plus sections from the stores that existed unread:
  Data Consistency resolutions (first reader of
  `underwriting_confirmation_audit`), full download log with open-items lists
  + checksums (`acord_audit_log`), client questionnaire receipts (new
  session-scoped reader in arq_receipt_service), producer answers including
  answered-but-still-open (new `get_producer_answers`).
- *Append-only spine*: new `audit_events` table (INSERT-only, excluded from
  the 365-day sweep) + `log_audit_event`. Events: documents_uploaded,
  client_answers_applied, recommendation_reopened / issue_reopened (carrying
  the prior action/action_at/score the reopen UPDATE then nulls),
  sqs_snapshot.
- *5.12 snapshots*: `log_sqs_snapshot_if_changed` stores the scorer's own
  emitted trace (D33) keyed on the exact trigger signature the client listed
  (raw, displayed, any pillar, ceiling added/removed, ceiling reason) - never
  per invisible recalc; a download always snapshots. Wired at all seven
  recompute/persist sites (select_forms_bulk, worker, reclassify, update_pdf,
  ARQ recalc, dismiss-credit, both download endpoints).
- *5.7 derivation stamped at every deriving writer* (extraction_service):
  `years_in_business`, the renewal-routed proposed effective/expiration dates
  (the client's own worked example), the dec-entry backfill (with the printed
  entry's label + owner), `is_renewal` (with the matched phrase), and
  `billing_plan` all carry `derivation: {rule, inputs, ...}` on the envelope;
  `_flatten_fact` renders it. Additive key - envelopes already carry ad-hoc
  keys (verified_in_text, reconciled); the 412 tests over those writers pass
  unchanged.
- *Evidence-destruction fixes*: `update_pdf` writes a producer envelope
  (`{value, confidence: filled, source: producer}`) instead of a bare string -
  which also un-breaks `sqs_service._producer_supplied_dates` (it reads
  `source` and could never see an edited date); `log_field_change` now records
  the CANONICAL fact key (was a copy of the PDF field name - unjoinable);
  `previous_value` captured at both hardcoded-None sites; client-ARQ apply
  logs per-fact before/after rows (`source='client_arq'` - allowed by the
  CHECK since day one, written never) + one event; schedule saves (PUT route
  and resolve-issue mode=schedule) log row-count changes; reopen logs the
  retraction of the producer's fact; dismiss/answer/resolve upserts now
  record the ACTING user (was: whoever the rec was presented to) and answers
  get `answered_at` (was: permanently untimed on the upsert branch);
  draft downloads now record the open list alongside the override (the most
  serious override used to record the least); underwriting confirmations
  accept an optional producer `note` (5.10).
- *Two latent bugs fixed on sight* (owner instruction "fix bugs you find"):
  (1) `run_facts_retention` UPDATEd a `facts` column that does not exist on
  `processing_sessions` (data lives at `data->'facts'`) - it had failed
  silently EVERY night since it shipped, so no free/essentials session was
  ever purged. Now `jsonb_set(ps.data, '{facts}', tombstone)` with the same
  payload + a purge guard in the export so a tombstone never renders as fact
  rows. (2) `sqs_history` was dead: the scorer appends and returns it inside
  `package_sqs`, but `session_repository`'s append-only merge only engages
  when the key is passed EXPLICITLY and no caller ever did - so the history
  was forever one entry, `delta_this_session` forever 0, and the frontend
  score-improvement panels could never render. Every package_sqs persist site
  now passes it.

- files: services/fact_lineage.py (new), services/audit_service.py,
  services/arq_service.py, services/arq_receipt_service.py,
  services/extraction_pipeline.py, services/scheduler_service.py,
  models/schemas.py, routes/form_routes.py, routes/audit_routes.py,
  routes/arq_routes.py, routes/download_routes.py, worker.py,
  frontend/src/components/form/AcordModal.jsx (record renderer + label map -
  `derived`/`dec_entry`/`user_confirmed`/`policy_doc_text` etc. no longer
  print raw or "unspecified").
- tests: tests/test_audit_lineage_20260826.py (27: lineage door incl. the
  5.4 both-documents case and the no-marker no-page-claim case, export
  assembly with junk-row + tombstone guards, all 5.12 trigger permutations,
  snapshot skip-unchanged/always-on-download, and anti-rot pins on every
  evidence-destruction fix).
- suite result: see C5-B below.

**Why this and not the alternative.** (a) Asking the LLM for page numbers per
fact - already tried and lost (the dec-index dedicated pass: ~593k tokens,
+18-20 min, switched off 2026-08-23); pages are derivable free from stored
text. (b) A stored per-fact lineage table with char offsets - overkill for
V1; 5.3 explicitly allows "a different schema as long as the relationships
are recoverable", and both sides of the join are already persisted.
(c) Fattening the session JSON with multi-source copies - computed at export
instead; durable tables only for what must outlive the session.

**Blast radius checked.** `update_pdf`'s envelope write flows into
calculate_package_sqs + the facts merge: envelopes are the NORMAL fact shape
(bare strings were the anomaly), the merge's D15 protection now correctly
sees the edit as human-sourced, and the expired-term check starts working on
edited dates (a producer typing an already-ended term now correctly trips the
stop - scores can move on that edge, D6 heads-up to Brent). `derive_states`
gaining the facts arg only in the EXPORT path - no scorer reads
evidence_state (verified in C4-Q). New envelope key `derivation` is additive
(envelopes already carry ad-hoc keys: verified_in_text, reconciled). The
retention fix activates a delete that never ran - localhost MVP, 0 users, but
flagged loudly to the owner. Full suite + frontend build to verify.

**Known / deliberately not done.**
- Gap-fill grounding quotes (`question_grounding`) are still discarded at
  pdf_service.py:19699 - persisting them means threading a third return
  through `map_facts_to_form`, the most landmine-dense seam in the codebase,
  for values that already carry `ai_verified`. Deferred with reasons, not
  forgotten.
- Field-QA's DELETE+reinsert refresh still discards per-row
  `downloaded_anyway` stamps on fieldqa_/fieldmap_ rows - harmless now that
  every download's open-items list is preserved in acord_audit_log and
  rendered; preserving those rows risked stale findings lingering in the
  preflight forever.
- `marketing_reason` stays latest-wins (documented product decision) - a
  change event could be added to audit_events later if Brent wants history.
- The retention purge still leaves `docs[].text` + per-doc facts in the
  session blob (only the `facts` key is tombstoned) - a data-minimization gap
  that predates this work; ALSO now the audit export's lineage depends on
  docs surviving, so widening the purge is a Brent decision (Q18), not an
  engineering default.
- `audit_events` and the other E&O tables are excluded from the 365-day
  sweep by default; the operational tables (`field_source_audit`,
  `sqs_recommendation_audit`, `acord_audit_log`) are still swept at 365d -
  whether an E&O record must outlive that is Q18.

### C5-B - Verification (2026-08-26)
Baseline before any C5 work, measured in this tree: **4393 passed / 1 failed
/ 14 skipped** (the known httpx/openai ImportError in
test_arq_acord125_missing_only). After all C5 changes: **4425 passed / 1
failed / 14 skipped** - the SAME single known failure, +29 new tests
(test_audit_lineage_20260826.py), zero regressions. The +32 delta is 29 new
tests plus the ordering jitter this file's own tail-note documents
(pytest-randomly cross-test pollution) - the 412 tests over the
derived-fact writers and the 77 over dec-entry/renewal routing were also run
targeted with `-p no:randomly`, all green. One anti-rot test fired exactly as
designed - test_dec_index_purge's consumer grep caught the export's new
`dec_page_entries` EXCLUSION line; decided and recorded in its known-list
(an exclusion is not a consumer; the purge stays safe). A mid-edit background
suite run transiently showed failures in test_v1_c1_canonical_facts /
test_v1_c1d_client_answer_review; both re-verified passing deterministically
after the edits settled. Frontend production build clean (pre-existing
chunk-size warning only; the localhost VITE_API_BASE guard refuses prod
builds by design - build verified with a prod-shaped URL).

**D6 heads-up for Brent (owed, not yet sent):** two behaviours can move
scores. (1) A producer-edited effective/expiration date now carries
`source: producer`, so the expired-term check finally applies to edited
dates - a producer typing an already-ended term now trips the stop it was
always supposed to trip. (2) `delta_this_session` and the score-improvement
panels start working (they were structurally dead), so users will start
SEEING score movement that was always happening silently.

### C5-C - Q18 ANSWERED (6 months) + the live test kit (2026-08-26)

**Retention ruling, owner verbatim: "Lets keep the record for 6 months now."**
Implemented as three concrete changes, each pinned by
`test_six_month_retention_ruling_is_implemented`:
1. `audit_events` (the E&O spine) is now swept by
   `run_audit_log_retention` on its own knob - `AUDIT_EVENTS_RETENTION_DAYS`,
   default 180, FLOORED at 180 so no environment can undercut the ruling.
   The append-only property is unchanged from the application's side; the
   scheduler owns the lifecycle (schemas.py comment updated to match).
2. Free-tier facts retention raised 30 -> 180: the record's captured-inputs
   section reads session facts, and purging them at day 30 would blank it
   inside the ruled window. No live data behaves differently - the purge SQL
   had never successfully run before the C5-A fix.
3. The three operational audit tables keep their 365-day SOC 2 floor
   (`AUDIT_LOG_RETENTION_DAYS`), which already exceeds 6 months; they also
   serve auth/payment auditing, so the E&O ruling does not shorten them.
Brent's copy of the retention question now states the set default and asks
only whether his E&O practice needs longer.

**Live test kit: `c5_test_data/` + `backend/scripts/make_c5_test_pdfs.py`.**
Five PDFs, three scenarios, README-HOW-TO-TEST.md with 24 numbered checks
mapped one-to-one to the client's 5.x clauses:
- S1 (package 4-pager + agreeing COI, upload together, generate 125+127):
  documents section, Document + Page evidence, both-sources-kept,
  schedules-not-unspecified, derived years-in-business, then the action
  flows - field edit, producer answer, dismissal with reason, reopen (event
  log preserves the erased timestamp), client questionnaire, download-with-
  open-items (list + note + checksum + snapshot).
- S2 (renewal dec whose SIX-MONTH term already ended, generate 125): the
  client's own 5.7 worked example (proposed effective derived from the prior
  expiration, rule + inputs printed) AND the refused proposed expiration in
  VALUES SEEN AND REFUSED (a 183-day term must not be assumed annual).
- S3 (umbrella $3M package + $1M COI, generate 125+131): the record shows
  `conflicting` BEFORE resolution, the picker shows both values with their
  files, and after confirming, DATA CONSISTENCY RESOLUTIONS carries every
  competing value + source + choice + actor + timestamp (5.10).
Design rule (the inverse of C4's): a lineage fixture must PRINT the value on
the page its check cites - `_verify()` re-reads every PDF with pdfplumber and
fails the build if a cited value is missing from its page, if S1A is not
multi-page (page markers exist only then), if a fixture accidentally prints a
value that must be DERIVED ("Years in Business"), or if S2's term stopped
being expired/non-annual (dates are computed from today). The lineage door was
also dry-run offline against the real generated PDFs: `gl_each_occurrence ->
"S1A_package_policy.pdf - page 2; S1B_certificate_of_insurance.pdf"`, the
schedule row -> contribution attribution, and the employee count "24"
correctly gets NO citation (the 4-char floor; noted in the README so it is
not reported as a failure).

**One renderer fix found while scripting the checks:** an envelope-less
structured fact printed `Source: unspecified` ABOVE its new Evidence line -
the exact words the client reported. The renderer now labels such a row
"AI extraction from document" whenever document evidence was recovered;
"unspecified" survives only for a value with no envelope AND no evidence,
which is the honest case.

Suite after C5-C: **4426 passed / 1 failed / 14 skipped** - the same single
known httpx failure, zero regressions (C5 total is now 30 tests). Fixture
`_verify()` green, offline lineage dry-run green, frontend production build
clean.

### C4-S - S5 SOLVED live; S6/S1 regression-checked; one S1 item to confirm

**S5 PASSES.** The Agency bucket now carries:

    ACORD 126 | Producer-facing | Conflict - resolve
    Annual revenue - rating basis

Two applications differing by $1.45M produce a producer-routed conflict row.
Clause 4.1 Step 5 and core principle 4 are satisfied live for the first time.
The client bucket carries no revenue question - the adjudication never reaches
the insured, which is the half of Step 5 that matters most.

**S6 PASSES as a regression check on C4-R.** Narrowing `_component_split_allowed`
to a named set did NOT resurrect any formatting-only conflict: no row for the
address, the ZIP+4, `LLC` vs `L.L.C.` or the spaced policy number. The
equivalence layer still folds what it should; it has simply stopped folding what
it should not.

**S1 - one item to confirm, stated plainly rather than assumed.** Property went
from 9 questions to 7 between runs. Two facts stopped being asked:

  * `occupancy_type` - CORRECT. The rebuilt S1 fixture prints "Occupancy:
    Cabinet shop and warehouse" (verified by reading the PDF back), so the fact
    is known and the question is rightly suppressed. The EARLIER run asking it
    was the anomaly.
  * `construction_type` and `fire_protection_class` - UNEXPLAINED. Reading the
    generated PDF back confirms the document contains neither "construction"
    nor "fire protection" nor "protection class" anywhere, which the fixture
    self-check also enforces.

Two possible causes, needing opposite responses, and I will not guess between
them again:
  1. extraction produced a value for them this run and did not last run (LLM
     variance) - the suppression is then CORRECT, but a GUESSED construction
     type is now stamped on ACORD 140, which is its own concern: it is exactly
     the "merely Suggested value ships silently" case, and C4-Q only routes
     JUDGMENT facts for confirmation, not client-eligible ones like this;
  2. something in C4-Q/C4-R suppresses them - a real regression.

Reviewed against my own changes first: `is_not_applicable_for` and
`_curated_question_for` can only ADD questions, ACORD_140s inventory is intact
(all 16 keys including occupancy_type / construction_type /
fire_protection_class), the component gate touches only conflict grouping, and
text verification LABELS values, it cannot create them. For the question to
vanish the FACT must now hold a value - which points at (1). Not proven.

DECISIVE CHECK: open ACORD 140 and look at the Construction Type and Protection
Class boxes. Filled -> case 1 (correct suppression, and a separate question
about whether we should stamp a guess). Blank -> case 2, a real regression, and
the questionnaire is hiding a gap the form still has.

---

## C4 CLOSING STATE - SUPERSEDED, see "C4 FINAL STATE + OPEN BACKLOG" at the end of this file (2026-08-26)

`C4-A` through `C4-S` are the working record. This is the summary a future
session should start from.

### What shipped

**ONE DOOR: `services/question_eligibility.py`.** The client's 4.1 Step 1-5 flow
plus the 4.4 routing table (`INSURANCE_JUDGMENT_FACTS`). Structural safety
property: every overlay it can emit moves a question CLIENT -> PRODUCER,
suppresses it, or holds a conflict. **There is no code path that routes anything
TO the client**, so a bug here can only ever over-inform the producer. Pinned by
`test_overlay_never_widens_client_exposure`, driven over every registry fact.

`decorate_questions` gained an OPTIONAL `facts=` argument; omitting it skips the
overlay entirely, so every legacy call site is byte-identical.

### Clause status, verified LIVE unless marked

| Clause | State |
|---|---|
| 4.2 / 4.3 / 4.4 routing | **DONE, live** (S1 18/18 split) |
| 4.7 GL | **DONE, live** |
| 4.8 Property | **DONE, live** |
| 4.9 Auto | **DONE, live** (S3; symbols off the client table) |
| 4.10 WC | **DONE, live** (S2) |
| 4.11 Umbrella | **DONE, live** (S4, all 7 items) |
| 4.1 Step 1 applicability | **DONE, live** (S7 both runs, form override works) |
| 4.1 Step 5 conflicting | **DONE, live** (S5, "Conflict - resolve") |
| 4.5 normalisation | **PARTIAL** - 6 of 8 verified; see gaps |
| 4.1 Steps 2/3 | **PARTIAL** - mechanism built, applied narrowly |
| 4.6 client-answer conflict | **BUILT, NEVER TESTED LIVE** |
| 4.12 criteria 1/3/4/5 | **DONE** |
| 4.12 criteria 2/6 | **NOT DONE** |

### The five root causes this arc actually found

Every one was silent by construction - no exception, no log, a feature that
simply never fired:

1. **Rules keyed on a field NAME** (C4-I). `NamedInsured_SICCode_A` does not
   contain the pattern `"sic_code"`. Three defects, one shape.
2. **Tables with a MISSING ROW** (C4-K). An unregistered field family
   (`Location_PhysicalAddress_*` on four forms), an override applied in one of
   two doors, an EMPTY `FORM_FIELD_INVENTORY` for ACORD 127.
3. **A reader on the WRONG KEY** (C4-L). `_uw_conflicted_keys` versus
   `_uw_conflict_keys`, one character apart. `value_state == conflicting` was
   unreachable in production.
4. **TWO tables, one read** (C4-Q). `FACT_REGISTRY[k]["question"]` versus
   `_FIELD_QUESTION_MAP`; 19 facts had a good question that was invisible. Plus
   23 inventory entries naming facts that do not exist.
5. **A gate too coarse to be a gate** (C4-R). `is_component_of` admitted 75
   facts by KIND when its entire justification is premiums, and folded a real
   $1.45M revenue conflict.

**The standing lesson, earned three separate times:** a rule that reasons about a
value's own characters must NAME the facts it may speak about. "Kind" is not
specific enough to be that name. And the only defence that has actually worked
here is a test that enumerates the REAL data - all 17 schemas, the whole
inventory - never one asserted example.

### KNOWN OPEN - do not close C4 without deciding these

1. **S1: `construction_type` / `fire_protection_class` stopped being asked** and
   the S1 document states neither. Either extraction guessed values (correct
   suppression, but a guess is stamped on ACORD 140) or something suppresses
   them (regression). **Decisive check: are those two boxes on the generated
   ACORD 140 filled or blank?** Unresolved.
2. **4.6 has never been exercised live.** S8 exists (application + loss run with
   2 claims). The round trip - send, answer contradicting the loss run, confirm
   the answer is HELD not applied - has not been run.
3. **4.5 residual, three items:** ACORD 25 insurer-letter mapping is absent;
   deterministic date derivation exists only on the renewal branch, so a
   non-renewal with an effective date and no expiration is ASKED instead of
   derived; `lob_canon.canon_line` returns None for `GL`, `WC` and `BAP`.
4. **4.1 Step 3 is implemented narrowly, ON PURPOSE.** A merely-Suggested value
   is surfaced for confirmation only for the ~43 INSURANCE-JUDGMENT facts.
   Applied to all 179 it would re-ask nearly the whole package (measured, C4-B).
   A guessed CLIENT-eligible value (item 1 above may be a live example) still
   ships silently. **This is a product decision, not an engineering one.**
5. **4.12 criterion 2 (exposure does not apply)** - only coverage-line denial
   exists. No vehicles -> auto questions are still asked.
   **4.12 criterion 6 (would not meaningfully improve)** - nothing REMOVES a
   zero-value question; ranking and the 28-cap affect pre-selection only.
6. **`tests/test_dec_index_purge` fails** on `audit_service.py:1173`. NOT this
   work - that file carries 331 uncommitted insertions from another session, and
   the flagged line EXCLUDES `dec_page_entries`. Someone must decide it.

### Measuring this suite correctly

`py -m pytest -q -p no:randomly` -> **4395 passed, 2 failed, 14 skipped.**
The default run reports **8** failures; six pass individually and
file-at-a-time. The suite uses `pytest-randomly` and has pre-existing
cross-test pollution. **Always baseline with `-p no:randomly`** or you will
chase ghosts that belong to nobody.

### Fixtures

`backend/scripts/make_c4_test_pdfs.py` -> `test_data_c4/` (11 PDFs + README).
Built on ONE rule, enforced by the generator itself: **a scenario can only test
the ROUTING of a value it does NOT state.** A stated value is extracted and
correctly suppressed, so the first fixture set proved nothing. `_FORBIDDEN` is
that contract as code and exits non-zero when violated - it caught its own
author on the first run.

### C5-D - LIVE RUN: all three scenarios PASS; 7 defects the run exposed, all fixed (2026-08-26)

**The owner ran the full kit on the live system.** Every C5 headline behaviour
verified on real records: both documents with types + upload times; Document +
Page evidence ("S1A_package_policy.pdf - page 2; S1B_certificate_of_insurance.pdf"
on gl_each_occurrence - 5.4 and 5.5 in one line); schedules with contribution
evidence instead of "unspecified" (5.6); years_in_business and the renewal
proposed-date with their derivation rules and the refused expiration with its
reason (5.7, the client's own worked example); the edit 24 -> 30 with actor +
canonical fact key; the reopen event preserving the erased dismissal timestamp
(5.9/5.11); the client's answers with name/email/time (5.8); the download
carrying all 9 open items + checksum (5.13); the conflict showing
`conflicting` before resolution and the full DATA CONSISTENCY RESOLUTIONS
entry after (5.10: both values, each tagged with its source file, choice,
timestamp).

**Seven defects the live records exposed - the fixtures were easier than
reality exactly once per defect (D22's lesson, again):**
1. **A resolved conflict still read `UNRESOLVED (conflicting /
   user_confirmed)`** one line under the resolution entry that settled it.
   Root cause: `derive_value_state`'s CONFLICTING branch reads the superset
   key (`_uw_conflict_keys` = "the documents still disagree"), which stays
   true FOREVER - so no confirmation could ever clear the state. Fixed at the
   reader: a fact whose evidence_state is USER_CONFIRMED is not conflicting
   (client 1.5 - the producer's resolution settles the FACT; the
   disagreement's history lives in the 5.10 resolution record). The
   evidence_state is re-derived when the caller did not pass it, so every
   caller agrees. An UNRESOLVED conflict still reads conflicting, test-pinned
   both directions. question_eligibility (64) + canonical-facts + C3 suites
   all green - no scorer reads these states.
2. **Two internal marker facts rendered as captured inputs**
   ("renewal_dates_routed: True / Source: unspecified",
   dec_states_payroll_basis) - filtered by CLASS, not name: a BARE Python
   boolean can only be pipeline bookkeeping, because _annotate_facts wraps
   every real extracted boolean into an envelope as the string "True"/"False".
3. **risk_transfer ([structured value]) printed "Source: unspecified" with no
   evidence** - structured dicts now get the same contribution attribution
   schedules do (fact_lineage.dict_sources).
4. **The upload event said "184 value(s)" while the record said 47** - the
   event counted raw fact keys including empties; now counts non-empty, the
   same thing the record prints.
5. **A duplicate score snapshot fired because the cap's wording gained its
   " Fix: ..." remediation suffix** on a different render path - the suffix is
   presentation, stripped from the 5.12 signature.
6. **"score 70, held at 85" read as nonsense** - the renderer now prints
   "held at N" only when the cap binds the displayed score, else
   "cap N in effect".
7. **"Chosen: $3,000,000 (was: $3,000,000)"** - under D16 the suggested value
   stamps before confirmation, so confirming the suggestion printed an
   identical "was". Suppressed when unchanged.

**Also observed working as designed, called out so nobody "fixes" them:**
inferred booleans (agreed_value_endorsement "False") cite their documents
without a page - the per-document extraction genuinely produced them and the
`suggested` state says they are unverified; the mailing address cites page 4,
not page 1, because page 1 prints it split across two rows and the citation
requires the value contiguous; a dismissal on a card WITH an answer box
records no reason - that is Q17, the owner's own "not now" ruling, and the
dismissal itself was still recorded (the reopen event proved it).

- files: services/fact_state.py, services/audit_service.py,
  services/fact_lineage.py, routes/form_routes.py,
  frontend/src/components/form/AcordModal.jsx
- tests: +4 in test_audit_lineage_20260826.py (35 total in the file)
- suite result: **4428 passed / 1 failed / 14 skipped** - the same single
  known httpx failure, zero regressions. Frontend production build clean.

**Verdict: C5 is verified live end to end.** The record is regenerated on
every click, so all fixes apply to existing submissions immediately after a
backend restart + browser refresh.

### C5-E - CLAUSE-BY-CLAUSE CLOSURE + the last gap (2026-08-26)

**Asked directly by the owner: "is every issue the client raised closed?"**
Answered clause by clause against the OWNER'S OWN LIVE RECORDS (S1-before,
S1-after, S2-record, S3-before, S3-after), not against intent. One gap was
found while answering it and closed before the answer was given.

**THE LAST GAP - the client's 5.4 example prints "COI.pdf - Page 1" and we
printed the COI with no page at all.** C5-A deliberately declined to name a
page for a markerless document, reasoning it "could be a 40-page text". That
reasoning was half right and therefore wrong: `ocr_service._PAGE_MARKER` is
emitted for EVERY multi-page document with content, so while markers are
enabled a markerless text is PROVABLY single-page and its value is on page 1
by definition. `fact_lineage.build_doc_index` now cites page 1 for that case,
reading `ocr_service._PAGE_MARKERS_ON` lazily so the honest no-page behaviour
returns the moment `OCR_PAGE_MARKERS=0` - the only configuration where a
markerless text really could be 40 pages. Both directions test-pinned
(`test_every_supporting_document_is_retained`,
`test_markerless_text_declines_a_page_when_markers_are_off`). The record now
prints the client's example verbatim: **"S1A_package_policy.pdf - page 2;
S1B_certificate_of_insurance.pdf - page 1"**.

**Verdict: all 13 clauses + the four headline complaints CLOSED.** Each row
proven by a specific artefact in the owner's live records:

| Clause | Proof |
|---|---|
| Headline (no source docs / "AI extraction" only / "unspecified" / no modification history) | All four visibly gone from S1/S2/S3 |
| 5.1 material facts | Every fact in the store gets the treatment - no curated subset to defend |
| 5.2 document record | id, filename, type + confidence, upload time, uploader - both files |
| 5.3 fact lineage | key, raw value, both states, scope, document + page (clause itself permits a different schema if relationships are recoverable) |
| 5.4 all supporting sources | "S1A - page 2; S1B - page 1" - his example, verbatim, after C5-E |
| 5.5 Document + Page | live on every verifiable value |
| 5.6 structured "unspecified" | **zero** occurrences in the S3 re-run; every example he listed (symbols, drivers, coverage lines, locations, underlying policies) carries evidence |
| 5.7 derived facts | his own worked example runs verbatim in S2: rule + inputs + evidence |
| 5.8 user-supplied | producer answers with actor/time; client answers with name, email, time, per question |
| 5.9 overrides | "24" -> "30" with actor + time; retractions logged; reopen preserved the prior dismissal timestamp |
| 5.10 conflict history | S3-after IS the requirement: both values each tagged with its file, choice, timestamp |
| 5.11 event log | append-only table; upload / answers / reopen / snapshots all observed live |
| 5.12 snapshots | all four triggers fired in S1-after, nothing redundant; content matches his list |
| 5.13 download with open items | acknowledgment + all 9 items + score + checksum preserved |

**THE FOUR CAVEATS, stated so nobody is ambushed by them** (each has a
one-sentence answer that ends the conversation):
1. Values under `_TEXT_VERIFY_MIN_CHARS` (4 normalised chars, e.g. "24") get
   no page citation - "24" occurs by accident in any document, and a false
   citation in an E&O record is worse than none. Blank-over-wrong, applied to
   lineage.
2. Dismissing a card that HAS an answer box records no reason - that is Q17,
   the owner's own 2026-08-26 "not now" ruling, not a C5 gap. The dismissal
   itself is still recorded (the reopen event carried `prior action:
   dismissed at ...`).
3. 5.10's "any resolution note" is plumbed end to end (column, writer, API
   field, renderer) but the picker UI has no note box yet - the clause says
   the note is optional, so nothing is unmet; it is a ~20-minute UI add.
4. A value a document only IMPLIES (`agreed_value_endorsement: False`) cites
   its documents without a page - there is no printed line to point at, and
   the `suggested` evidence state says so honestly.

**Suite: 4429 passed / 1 failed / 14 skipped** - the same single known
httpx/openai ImportError, zero regressions, 33 tests in
`test_audit_lineage_20260826.py`. Fixture `_verify()` green, frontend build
clean, `c5_test_data/` + README regenerated so check 2 states the page-1
expectation.

**Owed to Brent before he notices (D6), unchanged from C5-B:** the
edited-expired-date path now trips the stop it always should have, and
score-improvement deltas start rendering because `sqs_history` was structurally
dead until C5-A. Both are corrections, both move numbers.

### C4-T - The S1 ACORD 140 answers it: BLANK AND UNASKABLE, again (2026-08-26)

The owner supplied the generated ACORD 140. It settles C4-S item 1, and NOT the
way I guessed - I had reasoned toward extraction variance. It is a real defect,
and it was pre-existing rather than a C4 regression.

**CONSTRUCTION TYPE is BLANK on the form AND absent from the questionnaire.**
PROT CL carries "1" (junk, see below) which correctly suppresses its question;
YR BUILT is blank and IS asked. Construction type is the odd one out.

**ROOT CAUSE.** `_backfill_and_resolve_present` computes a FORM-AWARE present
set and states its own contract: *"if nothing could be stamped, the fact is left
OUT of the present set so the client is still asked for it."* The form SCAN
honours it. The coverage-guarantee injector did NOT - it asked
`_fact_is_filled(facts.get(key))`, which is true for any value sitting in
`facts` whether or not it ever reached a box. A fact that is present in facts
but cannot stamp therefore produced a BLANK BOX AND NO QUESTION.

This is the same shape as S7 run B (a property form blank and unaskable) one
layer down, and the fourth variant of the arc-long pattern: two views of the
same question, and the code consulted the weaker one. Fixed: the injector uses
the caller-supplied form-aware set when there is one, and keeps the facts-only
test as the fallback for callers that supply nothing.

**SEPARATE AND MORE SERIOUS - the 140 is full of mined junk.** Not a
questionnaire defect; recording it because it is worse than anything C4 has
fixed. On the sparse S1 property page, gap fill filled unrelated boxes:

  CARRIER               = "Applied For"   (a coverage STATUS as a carrier name)
  BLANKET SUMMARY BLKT# = "91340"         (the GL CLASS CODE)
  DIST TO HYDRANT/FIRE STAT/FIRE DISTRICT/CODE NUMBER/PROT CL = "1" each
                                          (all mined from the words "Location 1")
  # GUARDS / WATCHMEN   = "28"            (the EMPLOYEE COUNT)
  BURGLAR ALARM TYPE    = "safe" / "premises"  (word fragments)
  PREMISES FIRE PROTECTION = "Building characteristics and coverage terms are
                              to be confirmed before b"  (the fixture disclaimer)
  R/L/FRONT/REAR EXPOSURE = "4820 Marshall Street, Wheat" (the address)
  VALUATION             = "R"

This is the C21/C22 class - a thin document gives the model little to work with
and it borrows the nearest token. `fire_protection_class = "1"` then SUPPRESSES
its own question, so a garbage value both ships on a legal form and silences the
only mechanism that would have caught it. **The questionnaire cannot fix this;
it is a gap-fill grounding problem and belongs with the C21/C22 work.**

Suite after the fix: **4429 passed / 1 failed** (`-p no:randomly`; the known
httpx ImportError). `test_dec_index_purge` now passes - the other session"s
audit_service work moved on. +1 test (66 in test_question_eligibility.py).

---

## C4 FINAL STATE + OPEN BACKLOG (2026-08-26) - SUPERSEDES the "C4 CLOSING STATE" entry above

That earlier closing entry was written before C4-T. Read THIS one. The only
material change is item 1 of its open list: it is no longer unresolved, it was a
real defect and it is fixed.

### VERDICT

**Client section 4 is delivered.** Clauses 4.1-4.4 and 4.7-4.11 are implemented
and verified in the running app against fixtures built so they cannot pass
vacuously. What remains is a short, named follow-up list, plus one problem that
is NOT section 4 and is more serious than anything section 4 fixed.

### PROVEN LIVE (scenario in brackets)

| Clause | Evidence |
|---|---|
| 4.2 / 4.3 / 4.4 routing | S1 - 18 Client / 18 Agency, clean split |
| 4.7 General Liability | S1 |
| 4.8 Property | S1 |
| 4.9 Commercial Auto | S3 - symbols off the client table |
| 4.10 Workers Comp | S2 |
| 4.11 Umbrella | S4 - all seven 4.11 items in Agency |
| 4.1 Step 1 applicability | S7 runs A and B - producer form selection overrides |
| 4.1 Step 5 conflicting | S5 - "Conflict - resolve", producer-routed |
| 4.5 normalisation | S6 - 6 of 8 items |
| 4.12 criteria 1, 3, 4, 5 | across S1-S7 |

Scores did not move: S7 run A 71, run B 71.

### OPEN BACKLOG - nothing here blocks calling section 4 delivered

**O1. Clause 4.6 has never been exercised end to end.** OWNER ACTION.
S8 is built (application + loss run listing 2 claims / $65,700). The owner
deleted both pre-filled claim rows but has not SUBMITTED. The remaining step is:
submit, return to the producer view, and confirm the loss history is HELD (with
a "Use the client's value" / "Keep the source" choice) rather than silently
emptied. One click from an answer. If it empties, 4.6 is failing and it is a
principle-4 violation.

**O2. Clause 4.5 - three residuals.** ENGINEERING, no decisions needed, ~half a day.
  * ACORD 25 insurer-letter mapping is ABSENT - every `*InsurerLetterCode` field
    is a hard-coded owned blank and sits in `_NONFILLABLE_SUBSTRINGS`. Blank on
    every certificate we have ever produced.
  * Deterministic date derivation exists only on the renewal branch
    (`_route_renewal_dates`). A NON-renewal with an effective date and no
    expiration date is ASKED instead of derived (expiration = effective + 12mo).
  * `lob_canon.canon_line` returns None for `GL`, `WC` and `BAP`. It knows
    "Commercial General Liability", "General Liability" and "CGL" but not the
    bare abbreviations, which is 4.5's "equivalent coverage terminology".

**O3. Clause 4.12 criteria 2 and 6.** NEEDS A PRODUCT CALL on aggressiveness.
  * (2) "exposure does not apply" - only coverage-LINE denial exists. No
    exposure-driven suppression: a package with no vehicles is still asked auto
    questions.
  * (6) "would not meaningfully improve the submission" - nothing REMOVES a
    zero-value question. `sqs_points` ranking and `DEFAULT_SELECT_CAP=28` affect
    PRE-SELECTION only, so the long tail still renders.

**O4. Clause 4.1 Step 3 breadth.** BRENT'S CALL.
A merely-Suggested value is surfaced for producer confirmation only for the ~43
INSURANCE_JUDGMENT facts. Applied to all 179 it would re-ask nearly the whole
package (measured, C4-B). So a guessed CLIENT-ELIGIBLE value still ships
silently - and the S1 ACORD 140 (C4-T) is a live example of exactly that. The
question for Brent: should a guessed client-eligible value be surfaced too, and
if so, surfaced how - a question, or just the unverified highlight (O5)?

**O5. Cheap win, not yet done: drive the field highlight from
`verified_in_text`.** The viewer already colours by confidence
(`ai_verified` -> pink "found in docs", `low_confidence` -> review). C4-Q built
`fact_state.annotate_text_verification`, which knows deterministically whether a
value appears in the uploaded text. Feeding that into the existing colour makes
every gap-fill guess VISIBLE to the producer with no new UI and no new question.
Small, safe, and it is the cheapest mitigation for O6.

### O6 - NOT SECTION 4, AND MORE SERIOUS THAN ANYTHING IN IT

**The generated ACORD 140 is full of mined junk** (full table in C4-T). Carrier
reading "Applied For", the GL class code in the blanket number box, the words
"Location 1" scattered as `1` across hydrant / fire station / fire district /
code number / protection class, the employee count `28` in # GUARDS/WATCHMEN,
the fixture's own disclaimer sentence in PREMISES FIRE PROTECTION, the street
address in all four EXPOSURE boxes.

All of it is Pass-2 gap fill. The existing type guard (`_rejects_declared_type`,
C22) only rejects a personal NAME, a VIN or an out-of-range year; these values
are TYPE-PLAUSIBLE, so nothing catches them.

**It also interacts with the questionnaire in the worst way:**
`fire_protection_class = "1"` is a garbage value that then SUPPRESSES its own
question - so it ships on a legal form AND silences the one mechanism that would
have surfaced it.

Proposed fix, three parts, cheapest first - all extending machinery that already
exists, none of it new invention:
  1. **DO NOT ASK.** Section-level suppression: a COPE / protection / exposure
     sub-block with zero supporting evidence is removed from the gap-fill field
     list. This is already the documented next step -
     `FIX_TRACKING_2026-08-15.md` says verbatim *"suppress whole form SECTIONS on
     declared-absent coverage so the model is never asked"* - and is the same
     shape as `_resolve_phantom_schedule_row`. Cheaper AND more correct.
     **Must carry the S7 rule: the producer selecting the form overrides.**
  2. **Extend `_enforce_numeric_meaning_gate` from amounts to counts and codes.**
     A gap-filled `1` whose only witness is the token "Location 1" is not a
     protection class.
  3. **A borrowed-value check.** A gap-filled value identical to another FACT's
     value, on a field unrelated to that fact, is a borrow -> blank. Catches the
     employee count in the guards box, the class code in the blanket box, the
     address in the exposure boxes. Generalises the RC2 fix that already shipped.

Every one of these BLANKS a value, so each must be positive-evidence-only and
fail-open, and part 1 needs the most care.

**MEASURE BEFORE BUILDING.** The S1 fixture is DELIBERATELY sparse - that is what
makes it a good routing test and a BAD sample for judging gap fill. Run a real
client package, generate ACORD 140, and count the junk boxes. Sizing this from a
fixture designed to be thin would be exactly the mistake this whole arc kept
punishing.

### Measuring the suite

`py -m pytest -q -p no:randomly` -> **4429 passed, 1 failed, 14 skipped.**
The single failure is `test_arq_acord125_missing_only`, the known
`httpx`/`openai` ImportError documented in CLAUDE.md. The DEFAULT run reports
more failures because the suite uses `pytest-randomly` and carries pre-existing
cross-test pollution; those pass individually and file-at-a-time. **Always
baseline with `-p no:randomly`.**

---

## Session 2026-08-26 - H1 Coverage-Specific SQS Gap Closure (client section 6)

### H1-A - Audit: the defect is one class, "form-only facts" (2026-08-26)
**Priority:** V1-HIGH
**Principle(s) touched:** 1 (one canonical fact), 3 (missing does not mean no),
6 (provenance), 7 (unknown edge cases default to producer review)

**What Brent is saying, plainly:** a half-empty ACORD 127 or 130 scores badly on its
own form and barely moves the package, because the form score is the only place those
gaps cost anything and the form score does not feed the package.

**Root cause, one for both 6.3 and 6.4 [VERIFIED]:** spec section 10 / D29 - per-form
scores never feed the package, by design. Any fact scored ONLY on a per-form checklist
therefore has zero submission-level weight. Auto completeness (schedule, drivers,
garaging, radius) lived only on the 127 checklist (`sqs_service` ~5687); X-Mod /
officers / payroll period left Tier 2 under C3 3.14 and were given ONLY the 130
checklist as a home. Package Exposure for auto was -10 limit / -5 symbols / -8
vehicles-without-coverage; for WC payroll / class codes / multi-state only.

**Measured before building (four read-only sweeps, 148 tool uses):**
* Exposure-bucket consumers: exactly ONE breaks on a new bucket key -
  `_compute_category_breakdown`'s hardcoded five-tuple silently DROPS unknown keys
  (panel shows 5 rows, trace 7, "100 minus every bucket" tooltip false). Frontend is
  fully data-driven (`Object.entries(cats)`), never reads `score_trace.exposure`.
* Flag demotion sites: exactly TWO lower a coverage flag after extraction.
  `apply_declared_absent_downgrades` (text denial - correct). And
  `routes/form_routes.update_pdf` - keyed on the very facts whose ABSENCE is the
  penalty: `has_auto_coverage` dropped when limit AND schedule blank, and likewise
  property / umbrella / WC. Runs on EVERY edit of ANY field; persisted; inherited by
  every later recalc; restored only by a `_finalize_pipeline` re-run - so the score
  oscillated between two paths. Also found: re-runs discard the human-set
  `new_venture_confirmed` / `prior_carrier_adverse_action` flags.
* Phantom keys: 178 keys read across the six scoring / questionnaire modules, 40+
  with NO writer. The outcome-changing ones are in H1-C.
* The 16 target facts' plumbing (the fourth sweep died on an API error; covered by
  direct reads): `auto_garaging_address` (singular) read by the 127 checklist -
  nothing writes it; `auto_radius_of_operation` extracted, asked, scored, never
  deterministically stamped (the 127 stamper reads the dec-index entry and the
  schedule row instead); `wc_officer_exclusions` / `wc_payroll_period` never stamped;
  officer include/exclude never prints (`Officer_*` bindings match no real field);
  `wc_payroll_period` in the schema with NO definition text; no fact at all for
  vehicle use.

**Owner rulings 2026-08-26:** (1) vehicle-use: ADD the fact; (2) fix the edit-path
demotion and anything of the same shape; (3) D6 noted; (4) auto line with nothing
either way: PRESUME OWNED; (5) officers "known to exist": named individuals only;
(6) "clearly annual": the label is enough, by MEANING not spelling.

### H1-B - SHIPPED (2026-08-26)

**One door: `services/coverage_evidence.py`.** Answers, once, for the package
scorer, the ceiling engine, the ACORD 127 checklist, the fact-state axis (-> the
questionnaire) and the edit path:
* `auto_exposure_kind` -> OWNED / HNOA_ONLY / NONE / UNKNOWN, positive evidence
  only. OWNED: a real vehicle row, a symbol designating owned/scheduled autos
  (`auto_symbols` decides), `auto_has_physical_damage`, a comp/collision
  deductible, a garaging address. HNOA_ONLY: symbols recognised and reaching only
  hired/non-owned, a human "no owned vehicles" on the schedule, or every granted
  auto line naming HNOA. UNKNOWN is presumed owned for scoring (D41).
* `auto_completeness_gaps` - the client's five items and points verbatim; cap 25.
* `wc_xmod_status` / `wc_officer_treatment_status` / `wc_payroll_period_status` ->
  SATISFIED / NOT_APPLICABLE / MISSING / UNKNOWN; only MISSING deducts (-5/-5/-3,
  cap 10); UNKNOWN routes to the producer with no deduction (his own 6.4 rule).
* `coverage_flag_supported` - the edit-path rule (D42), line facts DERIVED from the
  registry through `fact_equivalence.fact_line`, never hand-listed.

**Scoring:** two new buckets in `_calculate_exposure_consistency` -
`auto_completeness`, `wc_supplemental`. Existing auto (-10/-5) and WC (-12/-10/-15/-8)
deductions untouched, as 6.3 / 6.4 both require. The two "+ Warning" items are
emitted by `evaluate_stops` (LEGACY engine), with `_LEGACY_MESSAGE_RULES` rows
resolving via `_r_schedule` - deliberately NOT cross-form issues (D40).
`_compute_category_breakdown` now renders every bucket the scorer emitted, in table
order, and only those (a stored five-bucket payload must not render the missing
bucket as 0%).

**The new fact:** `auto_vehicle_use` - extraction schema + RULE 2c (v14 -> v15, C80
in `improving-ll.md`), FACT_REGISTRY (client-eligible, factual), answer options (the
ACORD 127 USE column as printed), curated question / hint / producer label,
`FORM_FIELD_INVENTORY["ACORD_127"]`, `_INDICATOR_RULES` for row A and
`_resolve_vehicle_use_indicator` inheriting the fleet's use into every REAL row
(row C beyond a two-vehicle schedule stays blank - pinned).

**`wc_payroll_period` made real:** RULE 2c definition ("read the period off the
figure's own label; never assume annual"), producer question (it had a registry
question but no curated one, so the coverage-guarantee injector could never
guarantee it), options, `FORM_FIELD_INVENTORY["ACORD_130"]`, and a validator that
accepts MEANING (`per year`, `12 months`, `annualized`) instead of five spellings.

**Purge-safe derivations at the merge tail** (`_derive_from_dec_entries_h1`, same
pattern as `dec_states_payroll_basis`): `auto_radius_of_operation` from the auto
dec entry (one numeric radius; "NA" and two radii derive nothing),
`wc_payroll_period = annual` when the payroll label MEANS annual, `wc_xmod` from a
factor printed under "Experience Modification" (the generic backfill cannot route
that label - it wants the key's own tokens), and `wc_xmod_applicability` from
pending / not-rated wording. Each `evidence_state: derived` with rule + inputs.
`test_dec_index_purge` allow-list updated with the reasoning.

**Questionnaire:** HNOA-only marks the five owned-vehicle facts Not Applicable in
`fact_state.derive_value_state` (the same axis `denied_lines` uses, one level finer)
and `is_not_applicable_for` honours it even with ACORD 127 selected - the producer
override is for LINE-level denial, and an HNOA-only account does apply for the line.
The eligibility door then suppresses the questions (suppression is the one direction
it permits). Owned / unknown accounts keep asking.

**Edit path:** `form_routes.update_pdf` demotes a flag only when
`coverage_flag_supported` says no evidence remains (D42). `_finalize_pipeline` gained
`prior_flags`; `_carry_human_flags` carries the two human-set flags while their fact
survives with human provenance, never overriding what the merge decided. The four
re-run callers that already pass `prior_facts` now pass `prior_flags`.

**Verification:** `tests/test_h1_coverage_gap_closure.py` - 107 tests, every one
driving the real scorer / ceiling engine / fact-state / stamper on live-shaped
fixtures: the owned-vs-HNOA matrix (16 cases incl. "1 with 8 and 9 is owned", "a
schedule outranks an HNOA symbol", "'employees drive rented cars' is NOT HNOA-only"),
each item retiring its own points, the caps, the three WC matrices (15 / 10 / 13
cases), no Tier 2 fact moving either bucket, the trace and breakdown carrying both
buckets, HNOA suppression through the door, the flag-support matrix, the human-flag
carry, purge survival, the phantom fixes, the USE-column stamping.
`tests/test_h1_coverage_regression.py` - 30 pins for 6.1 / 6.2 / 6.5 (spec 3.2 rows,
the COPE ladder, every 3.5 deduction, the GL / property / umbrella cross-form rules
by CODE - `_check_gl_class_code_vs_operations` had zero references before). Targeted
run over every touched area: **632 passed** before the new files.

**Measuring the suite - H1:** `py -m pytest -q -p no:randomly` -> **4582 passed, 1 failed,
14 skipped** after H1-D (4577 after H1-B; 4440 / 1 without the two H1 files). The one failure is
`test_arq_acord125_missing_only`, the known `httpx`/`openai` ImportError. Zero
regressions. LESSON: the first full run reported two extra failures in package-scoring
tests that passed alone, whole-file, and behind the H1 files - it had been started while
`sqs_service.py` was still being edited, so modules imported mid-edit disagreed. Finish
every edit, THEN run the suite; a mid-run edit manufactures "pollution" that is not there.

**Blast radius - D6, both directions, tell Brent BEFORE he sees it:**

| What | Direction |
|---|---|
| Owned-auto packages missing vehicles / drivers / garaging / radius / use | DOWN, up to 25 Exposure points + the 85 ceiling |
| WC packages with an indicated-but-missing X-Mod, undecided named officers, or an unlabelled payroll figure | DOWN, up to 10 Exposure points |
| Split-limit auto policies (the unsatisfiable hard stop is gone) | UP, off the 60 ceiling |
| Property policies with a deductible and a stated basis (phantom warning gone) | UP, off the 85 ceiling |
| ACORD 127 form score where garaging was extracted (phantom key) | UP |
| Any package whose coverage flag had been dropped by a field edit | penalties RETURN - DOWN |

**Known / deliberately not done:**
* 6.3's overlaps with existing rules are REPORTED, not removed (D31): garaging -5
  beside the 3.12 physical-address warning; schedule -15 beside the agreed-value
  cross-form warning. Different conditions, same gap - Brent's call.
* The radius fact is still not stamped from `auto_radius_of_operation` onto
  `Vehicle_RadiusOfUse` when it comes from a human answer (the stamper reads the dec
  entry and the schedule row). Form-side; H6.
* `wc_officer_exclusions` / `wc_payroll_period` / officer include-exclude still do not
  print on ACORD 130. Form-side; H6.
* The live before/after on real packages has NOT been run.

### H1-C - The phantom-key ledger (2026-08-26)
Keys read by the scoring / questionnaire modules that NOTHING writes. 178 checked.

**Fixed in this change (deterministic name mismatches that changed outcomes):**

| Key read | Real key | Effect before |
|---|---|---|
| `bi_per_person` / `bi_per_accident` / `pd_per_accident` (both engines) | `auto_bi_per_person` / `auto_bi_per_accident` / `auto_pd_per_accident` | "Split liability limits incomplete" HARD STOP on every split-limit policy, unsatisfiable, package held at 60; Resolve marked impossible |
| `property_deductible_basis` | `deductible_basis` | warning on every property policy with any deductible; resolution "narrative only" |
| `has_building_coverage` / `has_bpp_coverage` (flags, default = the fact) | none - spec says building OR BPP | `has_x and not has_x`: a property submission with NEITHER value never told so by the coded rule |
| `auto_garaging_address` | `auto_garaging_addresses` | 127 checklist garaging satisfiable only via `locations` |

**Reported, NOT fixed - each needs a product/fact decision (Principle 7):**
* `num_owners`, `auto_has_drive_other_car`, `auto_drive_other_car` - both Drive Other
  Car checks can never fire; `issue_registry` rows for them describe issues that
  cannot exist.
* `wc_private_carrier_requested` / `wc_requested_private_carrier` / `wc_carrier_type`
  / `wc_state_fund_acknowledged` - the monopolistic-state private-carrier HARD STOP is
  unreachable; every monopolistic package takes the soft warning.
* `auto_effective_date` / `auto_expiration_date` / `wc_effective_date` /
  `wc_expiration_date` - umbrella-vs-auto and umbrella-vs-WC period alignment can
  never fire (per-line dates live inside `coverage_lines`).
* `prior_acts_confirmation` - fires on every claims-made GL policy; its own ARQ
  question cannot clear it (not a canonical fact).
* `form_reference` / `explanation_of_yes_answers` / `remarks_text` - ACORD 101 form
  score permanently capped at 75 / 66.
* `acord101_remarks` as the `field` of two ACORD 101 recommendation cards - Resolve
  can never write it (`additional_remarks_text` is the real key).
* `_extraction_quality`, `has_subcontractors`, `wc_gl_class_mismatch`,
  `has_certificate_holder_requirement`, `has_property_evidence_request`,
  `has_mortgagee_requirement`, `has_loss_payee_requirement`, `auto_pip_limit`,
  `auto_um_limit` / `auto_uim_limit`, `underlying_schedule` /
  `underlying_insurance_schedule`, `policy_notes`, `policy_period_explanation`,
  `property_actual_cash_value` / `property_replacement_cost`, `vehicle_schedule`,
  `auto_vehicles_detected`, `loss_run_pending` - dead `or` fallbacks or unreachable
  branches; no wrong outcome, listed so nobody trusts them.

**Standing lesson:** a key that is only ever READ is a rule that never runs. Two
tests in this repo already grep for phantom keys in one module each
(`test_no_check_reads_a_fact_nothing_writes`); a registry-wide version is the obvious
follow-up and was not built here.

### H1-D - The remaining items, closed (2026-08-26, second pass)
Owner: *"close all the remaining items properly."* Each of the residuals named in
H1-B is now closed or handed over with a kit; nothing is left as a note.

| Residual | Closure |
|---|---|
| 6.3 "Questionnaire behavior should instead focus on the applicable HNOA exposure" - NOT done in H1-B | `hired_auto_indicator` / `non_owned_auto_indicator` (the facts behind ACORD 127's own Hired / Non-Owned boxes, registry questions, deterministic stamping) added to `FORM_FIELD_INVENTORY["ACORD_127"]`. They were in NO inventory, so once the vehicle questions were suppressed an HNOA-only account was asked nothing. Both classify as client questions; pinned |
| Garaging -5 beside the 3.12 physical-address warning (two cards, one gap) | `_check_identity_address_distinction` now treats a street-shaped `auto_garaging_addresses` row as satisfying the requirement, exactly as a location row does - 3.12 names auto garaging as the reason the requirement exists. A label ("Yard") still fires the control |
| Schedule -15 beside the agreed-value cross-form warning (two cards, one gap) | Display de-dupe through the existing `_LEGACY_SUPERSEDED_BY_CODE` mechanism: the coded `auto_agreed_value_requires_schedule` (stricter condition, same schedule resolution) is kept and the legacy "Vehicle schedule not provided" string is hidden when both fire; re-clustered under "Auto completeness". SCORING untouched on both sides - the legacy string still caps at 85, the coded issue still feeds the cross bucket as spec section 7 defines. The legacy row still renders alone when the coded twin is absent (pinned) |
| The producer was still asked for an X-Mod the dec page said does not apply | `coverage_evidence.h1_fact_not_applicable` (one door, replaces the owned-vehicle-only hook in `fact_state`): `wc_xmod` is Not Applicable when the derived `wc_xmod_applicability` is `not_applicable` or New Venture is confirmed. Unknown still asks |
| A radius the producer typed never reached `Vehicle_RadiusOfUse` | `_resolve_vehicle_rating_cell` step 3: the policy-level `auto_radius_of_operation` fact, for rows that hold a real vehicle (row A alone when there is no schedule), when the dec is SILENT on the column. A printed "RADIUS: NA" still vetoes (the 2026-08-16 rule, re-pinned) |
| "Nothing has been run live" | **Live test kit:** `backend/scripts/make_c6_test_pdfs.py` -> `c6_test_data/` + `README-HOW-TO-TEST.md`. FIVE one-file packages (owner asked for 4-5, not 17), each self-verified for the absences that make it a test - merging is safe because every check reads its OWN row: P1 everything missing (6.3 empty fleet with the agreed-value card de-duped, 6.4 three gaps, 6.2 no values + no basis, 6.1 three GL gaps, 6.5 four umbrella shortfalls; steps for the edit path and for answering the WC cards), P2 everything complete (every control, USE/radius on the 127, mod on the 130, garaging satisfies 3.12), P3 HNOA-only + "not experience rated" (the N/A paths), P4 new venture + the reclassify re-run, P5 split limits PD-missing with the typed Resolve + partial fleet (-15) + PO Box address control + mod-effective-date-only with quarterly payroll. Fixture rule learned building it: a class-code schedule with remuneration amounts satisfies the payroll period by D43, so B1 prints codes WITHOUT amounts. Engineering cannot run the app here - the owner runs it, same as C1-C5 |

**Not closed, by design (not H1's scope):** the 30-odd phantom keys in H1-C that
belong to other rules (Drive Other Car, monopolistic private carrier, umbrella
period alignment, ACORD 101's form score). Each needs a fact or product decision.

**6.1 / 6.2 / 6.5 - what "regression-test existing behavior" means here.** The
client's own text says do not redesign and add nothing unless beta shows a
failure. No beta failure has been reported, so there is NOTHING to implement:
the deliverable is `tests/test_h1_coverage_regression.py` (30 pins), which
makes any future drift in those three areas fail the build. 6.1's "Location
Review" is a confirmation, also pinned: the location facts and the location
schedule question exist, and no GL location deduction was added.

### H1-E - FIRST LIVE RUN (c6 kit, 5 packages): 4 of 5 pass, 5 defects found, all fixed (2026-08-26)
**Priority:** V1-HIGH. Owner ran P1-P5 and sent the screens.

**Passed live:** P1 Auto -25 / WC -10 / Operations -15 / Property 0 / COPE hard stop
naming "building or BPP value" / typed deductible-basis card / agreed-value card once
/ both schedule cards / **edit path held** ("I edited phone fields and nothing
moved") / answering the mod card retired its 5. P2 every new row 0, Property 100,
Umbrella 100, no physical-address warning, mod 0.92 printed on the 130. P3 Auto 0,
WC 0, no schedule warnings, HNOA questions asked, tables badged Not applicable, no
X-Mod card. P5 split-limit hard stop + 60 + reason, WC -5, address warning.

**Defects the run found, root cause, fix (all pinned in `test_h1_coverage_gap_closure.py` section 11):**
| Seen | Root cause | Fix |
|---|---|---|
| P2 + P4 Operations 85 on clean accounts | `_codes_to_industry`: each printed its governing class (4299 printing / 2003 bakeries, neither in the lookup table) BESIDE clerical 8810, which IS in the table - so only the standard exception voted, the account read "office", and the ops/class mismatch fired on two clean submissions | `_WC_STANDARD_EXCEPTION_CODES` (8810 / 8742 / 8871 / 7380) do not vote **when a real class sits beside them**, with the codes read from their own STRUCTURE (`_class_code_tokens`) so a payroll figure is never mistaken for a governing class. **THE EXCLUSION IS CONDITIONAL, and the first cut got it wrong:** a policy whose ONLY class is clerical has no governing class, so on a roofing contractor that IS the mismatch the client asked for (his own example). The over-broad version deleted that check and `test_workstream3_closure.py` caught it - three tests, exactly the "is the TEST or the CODE wrong" gate. Both halves are now pinned together in `test_h1_coverage_gap_closure.py` section 11 |
| P1 Umbrella 40 not 25 | the document sentence "schedule of underlying insurance was not supplied" was extracted AS the schedule value (GAP 1 / C51 shape) | `coverage_evidence.umbrella_schedule_present` - a negation is an absence (Principle 3); all three scorer reads go through it |
| P5 Coverage Info -10 + a CSL producer card | every reader looked only at `auto_liability_limit`, empty by design on split limits | `auto_liability_stated` (CSL or split parts) at the exposure -10, the umbrella hard stop, adequacy's "required but absent", the 127/131/137 checklists and cross-form `_check_gl_missing_when_umbrella`; the CSL question is Not Applicable when split limits are stated. The below-$1M CSL comparison is NOT attempted on split parts - no opinion |
| P5 Auto Completeness -10 not -15 | extraction inferred a use / radius / garaging the document never printed | RULE 2c "never infer" sentences, v16 (C81) |
| P3 deductible / valuation / return-to-yard cards on a no-vehicle account | not in the HNOA N/A set | `HNOA_INAPPLICABLE_FACTS` = the five + comp/coll deductibles + physical-damage valuation + `vehicles_return_to_premises` |
| P1 vehicles and drivers asked twice | the coverage-guarantee injector emitted a scalar for a schedule-backed fact the table already asks | injector skips `schedule_capture.get_def` facts |
| P4 two EMOD questions would survive a New Venture confirm | the narrative slot `narrative_target_markets` is not the fact | it inherits `wc_xmod`'s applicability |
| P1 could not exercise the period -3 | class-code amounts satisfy the period by D43 once the extractor attributes the total to rows | the gap moved to P4 (codes without amounts). Fixture, not code |

**Corrected README expectation:** producer "Experience mod" / "Officer" cards DO show on a
complete package - they are C4 step-3 "confirm the suggested value" cards, not gaps.

**Round 2 = three uploads** (P2, P4 with its four steps, P5 with its step); P1 optional
for the umbrella row; P3 needs nothing.

**Suite: 4590 passed / 1 failed** (`test_arq_acord125_missing_only`, the documented
`httpx` ImportError). Zero regressions across all seven fixes.

**Every round-2 number was VERIFIED against the real scorer before the README claimed
it** (a wrong prediction wastes the owner's run): P2 Exposure 100 with all seven buckets
clean, Property 100, Umbrella 100; P4 WC Supplemental 97 (-3, the period only) and
Operations 100; P5 Coverage Info 100 (was 90), Auto Completeness 85 (-15, was 90), WC
Supplemental 95, split hard stop still firing; P1 Umbrella 25 (live read 40 - exactly
the -15 the negated sentence suppressed). The vehicle-schedule de-dup was also replayed
through `build_grouped_view`: the "Auto completeness" cluster renders the coded
agreed-value card + the driver card, with the legacy vehicle line suppressed - which is
the `Auto completeness 2` the live screenshot showed.

**Two things the run confirmed that are NOT H1's to fix, recorded so they are not
rediscovered:**
1. **P2's ACORD 127 driver rows carry the LOCATION's city/ZIP** ("Lancaster 17603" - the
   garaging address, not the driver's own). A driver's address is not the business
   premises. Form-side (H6), pre-existing, same family as the 2026-08-16 `auto_drivers`
   row defects. Not touched here.
2. **P1's application was classified `Underwriting Narrative`**, so its Evidence Basis
   reads "Stated in narrative" for every fact and Narrative Quality scored 59. Document
   classification, not scoring. Worth a look when H6 opens; it does not move any H1 row.

**Owner labelling note for anyone reading the run:** the screenshots label P3's SQS
section "S4". The tell is the industry word on the headline - `technology` is P3
(consulting), `restaurant` is P4 (bakery). P3 was fully captured and passed.


### H1-F - ADVERSARIAL REVIEW OF H1-E: my own fixes had six defects, two of them worse than the bug (2026-08-26)
**Priority:** V1-HIGH. Five independent reviewers over the H1-E diff, then a refute pass on every
finding. Nothing here came from a test - the tests were green.

**THE HEADLINE, and the lesson: fix 2 was more dangerous than the defect it fixed.**
`value_states_absence` scanned the whole schedule value for a negation near a supply verb. A REAL
broker schedule almost always names a line the umbrella does not sit over - "GL $1M/$2M; Auto $1M
CSL; Employers Liability not included" - so **13 of 14 realistic schedules were deleted and charged
-15**. That is a wrong VALUE, the direction blank-over-wrong exists to prevent, and it is the exact
shape of the 2026-08-12 `_quote_restates_the_question` defect where "not" sat in the stopword list.

The rule now has a STRUCTURAL first condition, as that fix eventually did:
1. a value carrying schedule DATA (a limit, in any spelling) **is** a schedule, whatever else it says;
2. otherwise absence only when the negation's own subject is the DOCUMENT ("the schedule ... was not
   supplied") or the whole value is a we-do-not-have-it token;
3. anything else is PRESENT - Principle 7, no invented penalty - and is logged by
   `unreadable_absence_values()`, which must be WATCHED, like `answer_semantics.unresolved_answers()`.
Measured after: **24/24 real schedules preserved, 27/27 absences caught.**

**Fix 2 was also DEFEATED UPSTREAM and left three readers disagreeing** - it moved a score and left
the remedy behind:

| Door | Was | Now |
|---|---|---|
| `extraction_pipeline` raw-text backfill | a bare substring test, so the document's own "was not supplied" sentence made it WRITE a synthetic "referenced in submitted documents" fact at `confidence: filled` - manufacturing the evidence whose absence is the -15 | `text_references_schedule_as_present` (mention unless the sentence negates it; a dec-page HEADING has no verb, so requiring an affirmative word would break the legitimate case) |
| ARQ `_maybe_inject_umbrella_evidence_questions` | truthiness, so the negated sentence suppressed the only question that could fix what we now charge for | through the door |
| `_derive_evidence_labels` | truthiness, so the payload carried a -15 AND `extracted_from_source` for one fact | through the door |

**The class-code fix (H1-E) was ALSO wrong twice, and the second was mine to catch:**
* over-broad: excluding standard exceptions unconditionally deleted the client's own lone-clerical
  mismatch. Caught by `test_workstream3_closure.py` - three tests - which is the CHANGE QUALITY BAR's
  "decide whether the TEST or the CODE is wrong" gate doing its job;
* then: the vote still ran `code in code_str` over the stringified blob, so table code **5403** matched
  inside a **payroll of 540300**; and excluding an exception could narrow an AMBIGUOUS vote into a
  single verdict, **creating** a -15 that did not exist (a wholesale bakery with a retail shop:
  2003 unmapped + 8017 retail + 8810).
  Rule now: vote over the structural TOKENS, and **an unmapped governing class means NO VERDICT** -
  which also makes the table monotone (adding a correct code can only add a verdict, never move one
  sideways). 15 cases pinned, including the real detection (restaurant ops + roofing class) that must
  still fire.

**Split limits - five more, all mine:**
1. **the producer could clear a 60 cap over a blank form.** The stop is now resolvable by typing the
   three limits; `_restamp_canonical_into_forms` never found the boxes because all three
   `_ACORD_FIELD_RULES` entries pointed at `auto_liability_limit`. Each box now maps to its own fact
   (stamping is unaffected - the resolver intercepts long before that loop). Replayed end to end:
   9 boxes stamp where 0 did.
2. `pdf_service` gated split stamping on the **flag**, which a producer answer never sets -> the facts
   decide too, through the same door.
3. marking `auto_liability_limit` Not Applicable **REVERTED**: it relabelled the three STAMPED split
   boxes `not_applicable` and dropped real document-sourced values out of `confidence_fill_rate`,
   numerator and denominator. An unnecessary producer card is recoverable; deleting real data is not.
4. `any(parts)` in `_split_indicated` was dead code reading phantoms; live, one stray figure on a CSL
   policy became a 60 cap. A stated CSL now means not-split.
5. removing the umbrella's -20 left an inadequate $100k/$300k/$50k policy scoring **exactly like an
   adequate one**. It cannot be compared to a COMBINED baseline and inventing that rule is forbidden
   (Principle 7), so it is surfaced in `review_items` - which, unlike the warning list, is not
   suppressed at full credit. `_get_umbrella_state` and `_check_umbrella_auto_minimum_limits` were
   left CSL-only and are now consistent.

**Questionnaire - the de-dup was guarding the wrong producer.** My skip sat in the coverage-guarantee
injector; the duplicate vehicle/driver scalar comes from the scorer's recommendation seed. Replaced by
`_drop_scalar_duplicates_of_schedule_questions` at ASSEMBLY in both generators - one door no producer
can defeat. It also fixes two findings for free: with `ENABLE_SCHEDULE_CAPTURE` off no table exists so
the curated scalar survives, and a conflicted fact re-admitted for the producer is no longer dropped.

**And the "blank and unaskable" defect, for the third time in this codebase:** the ACORD 127 checklist
docked an HNOA-only account 4 of 6 items for the very facts the questionnaire marks Not Applicable and
refuses to ask. They now leave the DENOMINATOR (C3 3.6's rule on a per-form checklist): HNOA 100,
an owned account with identical gaps still 33.

**And a SEVENTH, in the stamping H1-E added:** the ACORD 127 USE column's seven boxes are MUTUALLY
EXCLUSIVE, and H1-E ticked them with seven INDEPENDENT `_INDICATOR_RULES` substring entries. An
ordinary multi-word value stamped TWO of them - **"Commercial - Retail Delivery", the example written
into this codebase's own extraction prompt**, ticked Commercial AND Retail. The same pattern
(`Vehicle_Use_[A-Za-z]+Indicator`) also swallowed `Vehicle_Use_UnderFifteenMilesIndicator` /
`..._FifteenMilesOrOverIndicator`, which are the RADIUS pair - answering those "No" asserts a radius
nobody stated. The whole column now has ONE owner
(`pdf_service._resolve_vehicle_use_indicator` + `_vehicle_use_class`): the seven boxes are named
explicitly so the radius pair cannot match, and the EARLIEST keyword in the value wins, because the
leading word is the classification and the rest elaborates. An unrecognised-but-stated use ticks
ACORD's own `Other`. 12 values pinned, every one producible by a real document or by this kit's own
answer options.

**Verification:** 42 findings raised across five lenses, each re-executed against the real code by an
independent refuter; 40 refuted (most because they were already fixed while the pass ran), **2
confirmed** - the restamp gap and the USE column, both above, each naming the blocking line exactly.
**Suite 4665 passed / 1 failed** (the documented `httpx` ImportError). H1 tests 225.

**STANDING LESSON.** Every one of these shipped with a green suite and a fixture I wrote myself. A
negation scan over free text, and a lookup keyed on a stringified blob, are both the same mistake this
codebase has now made four times: **a test that is necessary but not sufficient needs a STRUCTURAL
second condition** - does the value carry the data, is the negation's subject the document, is the
code a real token. Write the adversarial case first: the REAL schedule that mentions a gap, the
payroll that contains a class code.


### H1-G - A FAILED PACKAGE SCORE ERASED THE GOOD ONE (live run R2, 2026-08-27)
**Reported:** R2 (`P4_new_venture.pdf`, ACORD 125 + 130) showed **no Total Package Score at all**.

**TRIGGER NOT FOUND - say so, do not guess.** The section renders on `{packageSqs && ...}`
(`AcordModal.jsx:6818`) and every frontend setter is guarded (`if (data.package_sqs)`), so it can
only fail to set, never clear. The one remaining door is `form_routes`' `except` handler setting
`package_sqs = None`. **The scorer could not be made to throw**: it is pure (no DB write - session_id
/ user_id are only echoed into the result), and it returned a score on the P4 shape as raw scalars,
as fact ENVELOPES, with and without per-form results, with auto absent. The H1 code was fuzzed over
**2,574 combinations** - 13 facts x 22 odd shapes (None, "", 0, True, [], {}, nested envelopes, NaN,
"N/A", list-of-dicts) x 9 entry points - with zero crashes. **`ROOT CAUSE NOT FOUND` for the initial
failure.** The next run must produce the log line.

**What WAS found, proven, and fixed - the reason it never came back.** All three sites persisted the
failed `None`:

| Site | |
|---|---|
| generate (`:1363` -> `:1364`) | `except` -> `package_sqs = None` -> **persisted** |
| edit (`:2007` -> `:2075`) | same |
| reclassify (`:800`) | same shape (unreachable today - a raise skips the block - guarded anyway) |

`upd_processing_session` replaces this key **wholesale** (`session_repository.py:334`, the merge
loop's `else`), and the modal's reload path reads it straight back
(`AcordModal.jsx:4059`, `sessData.package_sqs || null`). So **one transient failure removed the score
for the REST of the session**, long after its cause had passed - and destroyed the evidence with it.

**The precedent was already in the same file.** `upd_processing_session`'s own docstring says the
`facts` merge is deliberately additive so "an in-flight writer can never blank a value another writer
just set". `package_sqs` never got that protection. A failed score is now simply **not written**, in
one identical shape at all three sites, and both failure logs now name `session=`, `forms=` and
`trace=` - previously they named none of them, which is exactly why a user report could not be tied
to a log line.

**Class of bug removed:** *any* transient package-scoring failure - this one, a DB hiccup, a future
fact shape - converting into permanent, silent loss of the session's score.

Pinned by `test_a_failed_package_score_is_never_persisted_over_a_good_one` (AST, not a substring
grep: no dict literal reaching `upd_processing_session` may carry a bare `package_sqs` key) and
`test_the_package_score_failure_log_identifies_the_run`. **The AST test earned its place immediately -
it caught the third site, which I had read past twice.** Suite **4667 passed / 1 failed** (the
documented `httpx` ImportError).

**STILL OPEN - Q22:** what made the P4 run throw. Re-run R2 and grep the backend log for
`calculate_package_sqs failed`; the traceback names the line.


### H1-H - THE CLASS-CODE FIX WAS UNREACHABLE ON A SECOND PATH (live run, 2026-08-27)
**Reported as a number, not a bug:** two CLEAN live packages - P4 (a bakery) and P2 (a printer) -
both scored **Operations 85%**, where 100 was expected.

**It was not a length threshold.** Executed across descriptions of 6, 22, 58 and 413 characters the
operations bucket is FLAT; the only length rule in the area (`cross_form_validator` `len(ops_desc)
< 30`) feeds the ACORD 101 advisory and `cross_document_consistency`, never Operations. The 85 was a
false **-15 "class code does not match operations"** verdict.

**Root cause - my own H1-E conservatism.** `_codes_to_industry` kept a fallback: *"Unrecognised shape
- the legacy blob read, unchanged, so a fact we cannot parse behaves exactly as it did before this
function existed."* That branch has NONE of the three rules that make a verdict safe - no standard-
exception exclusion, no word boundary, no unmapped-primary-means-no-verdict - so **H1-F's defect
survived on it**, for precisely the inputs we understand least:

| shape | before | after |
|---|---|---|
| rows keyed `class_code` / `wc_class_code` | **office** (-15) | no verdict |
| `{"OR":[{"class_code":"2003","payroll":"540300"}]}` | **construction** - class 5403 matched INSIDE the payroll | no verdict |
| unknown key entirely | **office** (-15) | no verdict |

`_class_code_tokens` read only `code` / `codes`, so any other row key returned an empty set and
routed the fact into the pre-fix code. Both live packages print their governing class (2003 Bakeries
/ 4299 Printing - neither in the deliberately conservative table) BESIDE 8810 Clerical, so on the
fallback 8810 was the only match and the account was declared an office that disagrees with itself.

**Fix, two parts, neither touching the lookup table:**
1. the fallback returns **None**. `_class_code_tokens`' own docstring already promised the caller
   treats an empty set as "cannot tell" - **the caller simply did not honour its own contract.** A
   shape we cannot PARSE is strictly less knowable than an unmapped code, so rule 3 ("silence is the
   only defensible answer") applies with more force here, not less.
2. `_class_code_tokens` reads the realistic alternate keys BY NAME (`class_code`, `wc_class_code`,
   `governing_class`) and recurses one level into a state-keyed map. **Deliberately NOT a scan of
   every cell** - a description ("2026 remodel") or a payroll (540300) would then vote, which is the
   defect itself.

**Guard rails, verified still firing:** the client's own lone-8810-on-a-roofer mismatch, and
restaurant operations under a roofing class. An over-broad version of this fix deleted exactly those
in H1-E, so they are pinned.

**Scores go UP** on any account whose governing class is outside the conservative table - which is
most of them. **D6: tell Brent.** ~3.75 points of Total Package Score per affected submission
(Exposure is 25%), and it also shows on the per-form breakdown.

**The adversarial tests were written FIRST and failed before the fix** (3 failed / 2 guard rails
passed), per H1-F's standing lesson. Suite **4672 passed / 1 failed** (the documented `httpx`
ImportError).

**STANDING LESSON, now the fifth time:** a "keep the legacy path for shapes we do not recognise"
fallback is not conservative - it is the old bug, preserved exactly where the input is least
understood. And when a helper's docstring states a contract ("the caller treats this as cannot
tell"), CHECK THE CALLER: this one had not honoured it since the day it was written.


### H1-I - THE TWO REMAINING LIVE-RUN DEFECTS (2026-08-27)
Both found by rechecking the R2 log rather than by a test. Neither moves any score.

**1. `UNKNOWN_KEYS` cried wolf on the ordinary case** (`pdf_service`, the `_absorb` closure).
`_unknown_total = sum(1 for f in values if f not in sent)` measured against **`sent`, THIS BATCH's
slice** - so a REAL ACORD field was reported as an invented name whenever it had already been
stamped by Pass 1/1.5 or belonged to another batch. The live run warned about
`NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A` on an **1,877-character**
document, in a batch that logged `already_filled_hits=9`, and advised lowering
`CONTEXT_UTILISATION` - **the opposite of the long-context condition the warning exists to
detect**; its `_B` sibling was accepted normally one batch later.
Now classified against the invocation's `eligible_fields | already_filled`:
  * name on NO selected form -> **WARNING**, unchanged wording, still the C21 detector;
  * real field answered outside its own batch -> **INFO `OUT_OF_BATCH_KEYS`**, correctly discarded.
Nothing about what is absorbed changed. This matters because CLAUDE.md instructs the reader to
"grep every large run for UNKNOWN_KEYS" - a detector that fires on every ordinary run is one nobody
believes on the day it is real.

**2. The ACORD 101 "operations description is insufficient" advisory counted CHARACTERS**
(`cross_form_validator`, `len(ops_desc) < 30`). Wrong in both directions, measured:

| description | chars | before |
|---|---|---|
| `Tree trimming and removal` | 25 | **fired** - a complete trade description |
| `Retail bakery and cafe` | 22 | **fired** - the live P4 case |
| `We provide a wide variety of services to our valued clients` | 59 | silent - says nothing |

Now `len(ops_desc.split()) < 4`. `Bakery` and `Roofing` still ask for the narrative; a named trade
does not. **Costs no score either way - verified by execution** (`type=advisory`; Exposure,
operations and cross_document_consistency all 100 whether it fires or not). A correction to an
earlier note in this file: this advisory does NOT feed `cross_document_consistency`.

**Deliberately NOT done:** building a free-text "is this narrative meaningful" judge. That is the
shape H1-F's standing lesson warns about, for an advisory that costs nothing.

**Still open - not a code defect, needs one datum (Q23).** P4 scored `WC Supplemental 100%` where
-3 was expected. The rules are provably correct offline: a bare payroll figure returns MISSING and
charges 3, and nothing reads a bare "Payroll" label as annual. So the live facts differ. Three
candidates, separated by the facts panel:
  1. `wc_payroll_period` populated -> the extractor inferred a period the document never prints,
     against v16's explicit "never assume annual" -> a prompt fix, not a scoring one;
  2. a `wc_class_codes` row carries a payroll amount -> `_payroll_source_is_annual` satisfies the
     period from ANY WC class row with an amount (D43). P4 prints codes with NO amounts, so the
     extractor would have attributed the $210,000 itself -> the fix is to stop spreading an
     unallocated total onto class rows;
  3. `wc_payroll` absent -> then Payroll/Employee should not have scored 100 and the bug is elsewhere.

Suite **4674 passed / 1 failed** (the documented `httpx` ImportError). The suite EXCLUDING the two
H1 files is **4440**, byte-identical to the pre-H1 baseline - every C1-C5 guard file re-run green
(301 / 396 / 41 / 65 / 61) plus 138 in the gap-fill and prompt-caching area this touched.


### H1-J - THE SUB-ROW `i` ICONS, AND WHAT THE LIVE FACTS FINALLY SETTLED (2026-08-27)

**The icons: the client never asked for them.** Their ask (C3) is one sentence - *"every material
score must be traceable through Canonical Fact -> Validation Rule -> Pillar -> Raw SQS -> Ceiling ->
Displayed SQS"*. An `i` on every CATEGORY row was OUR implementation of that, shipped in `85f7b8d`,
its comment attributing the "arithmetic in the tooltip, not on the row" call to the owner on
2026-08-25. Owner's decision 2026-08-27: **icons on the 6 pillars only.**

Removed from the category rows; the reconciliation was NOT dropped - it moved UP into the pillar
tooltip, which now prints every category's arithmetic in the pillar's own terms: a weighted pillar
lists `score x weight = contribution ... they add up`, a deduction pillar lists `Deducted: X -15;
Y -5` and says the pillar is 100 minus those. **One hover instead of seven, and C3 still holds.**
InfoTips 13 -> 11. Frontend production build verified (the `VITE_API_BASE` localhost guard is a
pre-existing deploy check, not a code error).

**The live facts dump settled both open questions at once** (session 6a60e036):

1. **The backend was never restarted.** Scoring the dump's EXACT facts through the fixed code
   returns **Exposure 100 / Operations 100**; the screen showed 80 / 85. `wc_class_codes` came back
   in the canonical `code`-keyed shape (2003 + 8810) and `gl_class_codes_by_location` as
   `{"codes":["10100"]}` - both parse, both yield NO verdict, so H1-H's fix covers this package
   exactly. Nothing further to fix here; Python does not reload edited modules without `--reload`.

2. **Q23 answered - the EXTRACTOR manufactured the payroll period.** `wc_payroll_period = "annual"`
   while the dec index shows the label is the bare `Payroll = $210,000`. v16's prompt says, in
   terms: *"Set null when the payroll figure carries no period wording at all - never assume
   annual."* It assumed annual. The scoring rule is correct and was never the problem - it read a
   stated period and satisfied the check, exactly as specified. `dec_states_payroll_basis = True`
   is the same inference wearing a second hat.

   **This is CLAUDE.md's documented GAP 1 in the flesh** - `answer_semantics` guards what a HUMAN
   types, and nothing guards what the LLM extracts. Proposed fix (deterministic, no prompt reroll,
   consistent with the standing preference): an AI-sourced `wc_payroll_period` claiming an annual
   meaning must be corroborated by actual annual wording in the document - `payroll_label_states_
   annual()` already answers precisely that question and already returns False for a bare "Payroll"
   label. Uncorroborated -> null -> the -3 fires and routes to the producer. A producer or client
   answer (`source` in producer / client_arq) is never gated; only the inference is.
   **Not yet implemented - owner's call, and it lowers P4's score by 3 (D6).**


### H1-K - D43 WAS BEING DEFEATED UPSTREAM: THE EXTRACTOR INVENTED THE PAYROLL PERIOD (2026-08-27)
**Not a new rule - the restoration of one already ruled and shipped.** Q21 asked what "clearly
annual" means; the owner ruled 2026-08-26 and it shipped as **D43**: *"read from NAMED evidence,
never inferred from a category ... a payroll figure is annual when its OWN label / source MEANS
annual"*, and the -3 *"fires only for a bare figure with no period anywhere"*.

**Live run 2026-08-27, session 6a60e036.** The dec index printed the bare label
`Payroll = $210,000` - no period word in 1,877 characters - and the merged fact came back
`wc_payroll_period = "annual"`. The 6.4 rule then read a stated period, satisfied the check, and the
-3 the client specified could never fire. **The rule was right; its INPUT was manufactured.** The
extraction prompt already forbids this in terms (*"Set null when the payroll figure carries no
period wording at all - never assume annual"*, v16) and the model assumed anyway.

**Same class as H1-F**, where the schedule-absence rule was defeated by a raw-text backfill that
manufactured the evidence it tested for. A prompt is not a guarantee; the guarantee has to be
deterministic. This is also **CLAUDE.md's documented GAP 1 in the flesh** - `answer_semantics` guards
what a HUMAN types and nothing guarded what the model extracts.

**The fix, in two pieces:**
* `coverage_evidence.payroll_period_corroborated(period, entries, text)` - does the DOCUMENT name
  the period this fact claims? **Structural, not proximity**: the period word must QUALIFY the
  payroll word in the same phrase, crossing no sentence end or line break. A distance window would
  have corroborated "annual" from the `Policy Period 09/17/2026 to 09/17/2027` row printed one line
  above `Payroll $210,000` - so `policy year/period/term` is deliberately absent from the raw-text
  alternation (it stays in `_ANNUAL_RE`, which only ever reads a payroll-LABELLED entry).
* `extraction_service._gate_inferred_payroll_period(mf, docs)` in the merge tail, **before**
  `_derive_from_dec_entries_h1` - which never overwrites, so an invented period would otherwise keep
  the real one from ever being derived from its own label.

**PROVENANCE DECIDES (Principle 6).** A producer / client / derived value is never gated - only the
model's own inference, and only when the document names the period nowhere. Dropping it invents no
penalty: the question goes back to `wc_payroll_period_status`, which still satisfies from a
class-code schedule (D43's other half) before charging anything.

**Measured on the live facts:** period `annual` -> dropped -> status `missing` -> **-3**, Exposure
100 -> 97, `wc_supplemental` 100 -> 97, operations unaffected at 100.

**The extraction cache is untouched** - `PROMPT_VERSION`/`SCHEMA_VERSION` stay **v16** because no
prompt changed. The gate lives in `merge_facts`, which runs on every upload whether the extraction
cache hits or not, so a re-test of an already-uploaded document is gated correctly.

**Correction to H1-J:** `dec_states_payroll_basis = True` is NOT the same inference wearing a second
hat. It answers a different question - does the document state a GL exposure BASIS - and is
correctly true here. Not touched.

**Adversarial cases written FIRST** (6, all failing before the fix): the live bare-label case; five
real spellings of annual that must KEEP their satisfaction, by meaning not spelling; a body-text
"annual payroll" with no dec entry; P5's "Quarterly Payroll (most recent quarter)"; every named
source surviving the gate; and a class schedule WITH amounts still satisfying at 0.

**D6 - scores move DOWN** on any WC account whose payroll carries no period wording. Tell Brent.
Suite **4680 passed / 1 failed** (the documented `httpx` ImportError); every C1-C5 guard file green
(301 / 396 / 41 / 65 / 61) plus 101 in the extraction and merge area.


### H1-L - LIVE CONFIRMATION, AND THE TOOLTIP WENT TOO FAR (2026-08-27)

**Every code fix from 2026-08-27 is now CONFIRMED ON THE RUNNING APP**, backend restarted, two
uploads:

| | P4 (125+130) | P2 (125+127+130) |
|---|---|---|
| Operations | 85 -> **100** | 85 -> **100** (Exposure 80 -> 95) |
| WC Supplemental | 100 -> **97** (the -3) | **100** - unchanged, the guard rail |
| Exposure Consistency | 80 -> **92** | 80 -> **95** |
| Total Package | 75 -> **78** | 78 -> **83** |
| ACORD 101 "insufficient" advisory | **gone** (2 -> 1) | n/a |
| payroll-period gate in the log | **fired** | **silent** |

**The guard rail is the result that matters.** P2 prints "Estimated Annual Payroll $980,000" and its
WC class rows carry amounts; the gate stayed silent on it and fired only on P4's bare
`Payroll = $210,000`. Confirmed two ways - no gate line in P2's trace, and its Exposure landing at 95
rather than 92. A rule that fires on the ordinary case is the failure this codebase has made four
times; this one does not.

The producer question **"WC payroll period / basis"** now appears on P4, routed to the producer as
6.4 specifies. Sub-row `i` icons are gone; the pillars keep theirs.

**AND A DEFECT OF MY OWN, reported on sight:** when the sub-row icons were removed I folded every
category's arithmetic INTO the pillar tooltip to preserve C3 traceability. On screen that rendered as
a **wall of text covering the panel** - "Rows: Core Application (Tier 1) 100% x 40% = 40; Underwriting
Profile (Tier 2) 100% x 35% = 35; Form Fill Rate 89% x 25% = 22.25..." Reverted to the original
one-liner (weight, score, contribution). **Traceability did not need it:** every category is already
listed directly underneath the pillar with its own percentage, and `score_trace` carries the full
ledger for the E&O record. The tooltip only ever had to say what the PILLAR weighs.

**Standing note:** "preserve the requirement" is not a licence to move a paragraph into a hover. When
a UI element is removed for being cluttered, the fix is rarely to relocate its content - check first
whether the information is already on screen.

**Still not live-confirmed** (needs a post-generation log and the 127 PDF): the `OUT_OF_BATCH_KEYS`
reclassification, and the ACORD 127 USE column ticking exactly one box per row. Neither can move a
score - one is a log line, the other a checkbox - but neither has been seen working.


### H1-M - CLOSURE LEDGER (client section 6, 2026-08-27)

**Verdict: CLOSED ON SCORING. Not "nothing open" - four items below are named honestly.**

#### What the client asked for, clause by clause

| Clause | Client's direction | State |
|---|---|---|
| **6.1 GL** | regression-test only; confirm location info reaches facts + questionnaire; **no** new GL location deduction | 10 regression pins; location facts present and askable; no deduction added |
| **6.2 Property** | regression-test only; no redesign | 9 regression pins; untouched |
| **6.3 Auto** | new Auto Completeness bucket in Exposure, owned/scheduled only, -15/-10/-5/-5/-5, cap -25, existing auto deductions still separate, HNOA-only exempt | Built and live-verified. Cap binds at 40 raw. HNOA-only charges nothing and marks the facts Not Applicable. Missing limit still costs 10 pillar points INDEPENDENTLY of the bucket |
| **6.4 WC** | 4 fields out of generic Tier 2; X-Mod -5 only when applicability indicated, unknown -> producer, New Venture / N-A -> nothing, never ask the client; officer -5; payroll period -3; cap -10 | Built and live-verified. All four X-Mod branches, all three officer branches, all four period branches. Cap binds at 13 raw. X-Mod and officers are producer-facing |
| **6.5 Umbrella** | regression-test only | 8 regression pins; untouched |

**The client's Desired Outcome** - *"a materially incomplete submission should receive an
appropriately weaker total SQS regardless of which ACORD form contains the missing information"* -
is met: the two new buckets sit in the PACKAGE pillar, so a half-empty 127 or 130 now moves the
submission score, which spec section 10 / D29 previously made impossible.

#### Live verification, 2026-08-27, backend restarted

| | P4 (125+130) | P2 (125+127+130) |
|---|---|---|
| Operations | 85 -> **100** | 85 -> **100** |
| WC Supplemental | 100 -> **97** | **100** (unchanged) |
| Exposure | 80 -> **92** | 80 -> **95** |
| Package | 75 -> **78** | 78 -> **83** |
| payroll-period gate | **fired** | **silent** |

The P2 column is the guard rail and the reason this can be called closed: a rule that fires on the
ordinary case is the failure mode this codebase has hit four times, and this one does not.

#### Defects found and fixed AFTER the original ship (all mine, all in H1-F..H1-L)

1. USE column ticked two mutually exclusive ACORD 127 boxes on a multi-word value
2. A failed package score was PERSISTED, wiping the last good one for the rest of the session
3. The class-code blob fallback kept H1-F's defect alive (a payroll of 540300 voting as class 5403)
4. `UNKNOWN_KEYS` reported a real ACORD field as a hallucination
5. The ACORD 101 advisory counted characters, not words
6. Sub-row `i` icons (never a client ask), then the over-long tooltip that replaced them
7. The extractor invented the payroll period, defeating D43 from upstream

#### STILL OPEN - do not let these disappear

| # | Item | Can it move a score? |
|---|---|---|
| 1 | **Q19 / Q20 / Q21** - owner-ruled defaults shipped, awaiting Brent's confirmation (in `20Aug_questions_brent.md`) | Yes, if Brent rules differently |
| 2 | **`OUT_OF_BATCH_KEYS`** never observed - the log capture stopped before form generation | No - a log line |
| 3 | **ACORD 127 USE column** never observed printing exactly one box | No - a checkbox on a form |
| 4 | **Split-limit restamp** (typed limits reaching the 127) verified offline only - 9 boxes stamp where 0 did | No - form output |
| 5 | **Q22** - what made a package score throw. Never reproduced; a failure can no longer wipe the good score and both logs now name session/forms/trace | No - hardened |

**D6 applies in BOTH directions and Brent has not seen the live numbers.** Auto and WC packages with
real gaps go DOWN; the split-limit, deductible-basis, garaging and class-code fixes move many
packages UP. Tell him before he notices.

#### Standing lessons this arc produced, in the order they were learned

1. An offline probe proves the FUNCTION, never the SEAM around it.
2. A test that is necessary but not sufficient needs a STRUCTURAL second condition - and the
   adversarial case must be written FIRST.
3. A "keep the legacy path for shapes we do not recognise" fallback is not conservative; it is the
   old bug preserved exactly where the input is least understood.
4. When a helper's docstring states a contract, CHECK THE CALLER - `_class_code_tokens` promised
   "the caller treats this as cannot tell" and the caller never did.
5. **An explicit prompt instruction is not a guarantee.** Where its violation is silently scoreable,
   it needs a deterministic guard downstream.
6. Removing a UI element for clutter is not a reason to relocate its content into a hover.


## Session 2026-08-27 - H2 Early Score / Readiness Presentation (client section 7)

### H2-A - SHIPPED (2026-08-27)
**Priority:** V1-HIGH
**Principle(s) touched:** 1 (one canonical fact - one score), 6 (provenance - the label is
read off the scorer's own output, never recomputed for display), 7 (no invented rule)

#### What the client asked for
*"The problem is not that a low number looks bad. The problem is that the interface can
blur: SQS; submission status; information-gathering progress."* V1 decision: no large
numeric percentage on the early information-gathering screen; show the qualitative status
of the current SQS band (7.1); show missing / remediation progress separately (7.2); the
number stays in the dedicated SQS experience (7.3).

#### Root cause - the percentage was never the SQS
The Review step printed **`tier2_score` as "Submission Readiness NN%"** with a coloured bar
(`AcordModal.jsx`, the `tier2-bar`). `tier2_score` is `check_tier2()` - the Tier 2
completeness ratio over the client's six general-business facts (C3 3.5 / 3.6), i.e. ONE
CATEGORY of the Structural pillar. Under a readiness name and a percentage format it read as
the score. The owner's own screenshot: **"Submission Readiness 100%" directly beneath
"Review 12 warnings"** - twelve warnings cap the SQS at 85, so the real band was "Almost
There" at best. The class: a per-component metric surfaced as the headline readiness figure.

The structural half: **no package SQS existed before form generation** on four of the five
pre-form paths (upload, `/extraction-result` reload, integrity resolve, confirm-value) - only
the reclassify path scored pre-generation (§4.2 item #5). So the screen could not have shown
a band even if it had wanted to.

#### What shipped

| Piece | Where | What |
|---|---|---|
| `_tier1_items` / `_tier2_items` | `sqs_service` | The Tier 1 / Tier 2 rules as `(applicable labels, missing labels)`. `check_tier1` / `check_tier2` are now projections of these - byte-identical results, pinned |
| `key_details(facts, flags)` | `sqs_service` | `{satisfied, missing}` over Tier 1 + Tier 2, from the SAME lists the score uses. N/A in neither (3.6); producer-exempt in neither (3.3); a human "none" is in place (Brent 2026-08-24) |
| `score_package_pre_generation` / `current_package_sqs` | `sqs_service` | The one door for "the package SQS as it stands". Forms generated -> the persisted, credit-bearing `package_sqs` (D33); integrity review pending -> None; otherwise the reclassify recipe (per-form facts scorer over the RECOMMENDED forms -> `calculate_package_sqs`, stage `initial_extract`) run STATELESSLY - nothing persisted, no `sqs_history` entry, no 5.12 snapshot. Scorer failure -> None and the log names the session (H1-G) |
| `_pre_form_status` | `form_routes` | One helper, five responses: upload, integrity resolve, reclassify, confirm-value, `/extraction-result`. Each now carries `package_sqs` + `key_details`, withheld exactly as `tier2_score` is |
| The card | `AcordModal.jsx` | "Current Submission Readiness: <tier>" (owner's wording, live review 2026-08-27) (label + colour from the scorer's own `tier` / score, same ladder as the SQS panel), "Key details in place: ...", "Key details missing: ...". No percentage, no bar. Audience-neutral wording kept (C4-I: NAICS/SIC are producer-only) |
| Section progress | `AcordModal.jsx` | "N items still need attention · M handled" under the Hard Stops and Warnings titles, summed from the same per-item statuses the cluster pills read. Owner's call: counts live on the sections, never on the status card |
| Review-step reload of marks | `AcordModal.jsx` | `loadIssueStatuses` ran only on editor/lite - a refresh on the Review step forgot every stored Resolve/Dismiss mark. Now loads on every step that renders the controls |
| Generate-handler guard | `AcordModal.jsx` | `setPackageSqs(data.package_sqs || null)` - the pre-generation score in state must never surface as the Total Package Score when the generation scorer fails (H1-G's class, client side) |

#### Two deliberate changes to the reclassify path (it now calls the same door)
1. Its cross-form input is the pipeline's own `cross_form_issues` **with hard stops demoted
   pre-selection** (C75). It used to feed the legacy `cross_validate` output raw, so a
   RECOMMENDED form's rule could cap the reclassify score at 60 through `hard_cross` while the
   card beside it said "warning" - the display/score mismatch C75 exists to prevent.
2. A package with no recommended form is scored through the 3.7 no-form path instead of
   skipped. Persist + 5.12 snapshot on reclassify are unchanged.

#### Rejected
- **Relabelling `tier2_score` into a band.** The bug in a new coat - the screenshot above
  would have printed "Submission Ready" beside twelve warnings.
- **Persisting the pre-generation score at upload.** The session list reads
  `data->'package_sqs'->>'package_sqs_score'` and prints "Quote Ready / Not Quote Ready" from
  it, and an `initial_extract` history entry would move `delta_this_session`'s baseline. A
  visible behaviour change nobody asked for, so the pre-form score is derived, never stored.
- **A single top-of-screen countdown** ("7 items still need attention · 2 handled" on the
  card). Owner: keep the counts on the Hard Stops / Warnings sections; the card says only
  which key details are in place and which are missing.

#### Known, stated honestly
- **The label can move at generation.** A cross-form hard stop demoted pre-selection (C75)
  returns to full force once its form is selected (cap 85 -> 60), and the Form Fill Rate joins
  Structural at 25%. "Almost There" on the Review step can become "Major Gaps" on the editor
  for some packages. By design; **D6 - tell Brent** (presentation only, no score changed).
- **Client 7.2 as written** (one countdown with completed / unresolved / remaining lists) is
  shipped at SECTION level, not as one figure - owner's call 2026-08-27. A warning that clears
  as a side effect of fixing something else drops out of the count without a "handled" mark.
- ~~Not seen live yet.~~ **Live-verified 2026-08-27 - see H2-B.**

#### Verification
Full suite **4713 passed / 1 failed / 14 skipped** (3m44s) - the one failure is the documented
`httpx` ImportError in `test_arq_acord125_missing_only`, unchanged. Baseline before this work
was 4680 / 1 (H1-K); the +33 are this arc's tests, zero regressions. Targeted C3 / H1 / SQS /
issue-view suites: 616 passed. Frontend production build clean
(`VITE_API_BASE=https://api.primble.io npx vite build`).

### H2-B - LIVE CONFIRMATION + the label wording (2026-08-27)
**Owner's live run, Review step, backend restarted.** The card rendered exactly as built:

```
Review 5 warnings below before continuing
Current Submission Readiness                                   Not Ready
Key details in place: Producer / Agency name · Applicant legal name · Applicant mailing
  address · Proposed effective date · Lines of business requested · Business entity type ·
  Contact information · FEIN / Tax ID · Operations description · Years in business
Key details missing: Annual revenue · Number of employees · NAICS or SIC industry code
```

No percentage and no bar anywhere on the screen. The label is the package scorer's own
`tier` for the facts as they stood ("Not Ready" = below 60 - five warnings cap at 85, the raw
score sat under the cap); the two key-details lines are the score's Tier 1 + Tier 2 lists.

**One change from the review:** the card title is **"Current Submission Readiness"**, not
"Current Submission Status" - owner's wording. Label only; nothing behind it moved.

#### Client section 7, clause by clause

| Clause | Client's direction | State |
|---|---|---|
| **V1 decision** | *"Do not display a large numeric percentage on the early questionnaire / information-gathering screen"* | **Met.** The only pre-form percentage in the app is gone; the number lives on the SQS panel and the Clarity results step |
| **7.1 Qualitative status** | *"Show the qualitative status associated with the current displayed SQS band"* - Submission Ready / Almost There / Needs Work / Major Gaps / Not Ready | **Met.** The label is `tier_for_score` on the package SQS as it stands - the same ladder and the same scorer as the SQS panel, never a relabelled Tier 2 ratio. Live: "Not Ready" |
| **7.2 Information progress** | *"Display missing / remediation progress separately"*; example "7 items still need attention", counting down; show completed, unresolved, remaining | **Met on the owner's scope, stated honestly.** Separately from the label the card lists the key details in place and the key details missing (moves as facts get answered), and each Hard Stops / Warnings section carries "N items still need attention · M handled", counting down as rows are Resolved / Dismissed, with handled rows keeping their badge. NOT built: one single countdown figure across the whole screen and a dedicated "completed items" list - owner 2026-08-27: counts stay on the sections, the card says only which key details are in place and which are left |
| **7.3 Numeric SQS** | *"remains available in the dedicated SQS / results experience"* | **Met, untouched.** Editor Total Package Score panel and the Clarity step still print the number |
| **Desired result** | the producer understands where the submission stands AND what still needs completing, without mistaking one for the other | **Met.** Two things, two places: a band at the top, lists and counts underneath; nothing on the screen can be read as a score |
| **A+/A/A- grading** | V2 | Not touched |

**Verdict: section 7 CLOSED on the owner's scope.** The one residual is the literal 7.2 single
countdown, deliberately not built (recorded above so nobody mistakes it for an oversight).

**Still worth one line to Brent (D6):** the band can move at generation - a hard stop on a
merely recommended form is a warning until the form is selected (C75), and the fill rate
joins the score. Presentation only; no score changed.

---

## Session 2026-08-27 - H3 Workers Compensation Data Capture (client section 8)

### H3-A - Full audit of section 8 - ANALYSIS COMPLETE, NOT YET BUILT (2026-08-27)
**Priority:** V1-HIGH
**Principle(s) touched:** 1 (one canonical fact), 3 (missing is not no), 5 (never ask the
client to classify), 6 (provenance), 7 (no new rule without product approval)

**Read-only session. No code, no UI, no test was changed.** Everything below was read in
the code or executed offline (`compute_form_gaps("ACORD_130")` with sample WC facts), not
taken from a markdown file. Owner asked for the analysis and the open questions only.

**What Brent is saying, plainly.** One total payroll number tells him nothing. Let the
business list its people in GROUPS - office, sales, field crew - with how many, what they
actually do, annual payroll per group, the state, and the WC class code if one is already
known. Keep the other WC facts (total payroll, payroll by state, owners/officers in or out,
X-Mod, subcontracting %, payroll period). And Primble must NOT guess or suggest WC class
codes - copy what a document or the producer supplies, tidy the format, run the checks
that already exist. Section 8 defines NO new score rule; "improves SQS" means the existing
WC rules get better input (Principle 7 - nothing new is scored).

#### Status - ~55% exists [VERIFIED]

Already there:
* Extraction reads a WC class table into `wc_class_codes` rows (code, description,
  state, payroll, rate) and officers into `wc_officers` (name, title, ownership %,
  include, exclude, state) - `extraction_service.py:280, 431`.
* ACORD 130 prints code / duties / payroll per row (offline run: rows A-C stamped) and
  officer name / title / ownership % (`_SCHEDULE_REGISTRY` bindings repaired 2026-08-15/16).
* Every 8.2 fact exists with a question: `total_payroll`, `wc_payroll`,
  `wc_payroll_by_state`, `wc_officers`, `wc_officer_exclusions` (choice list),
  `wc_xmod` + `wc_xmod_effective_date` + derived applicability, `percent_subcontracted`,
  `wc_payroll_period` (choice list, meaning-based validator, H1-K gate).
* 8.3 already holds: nothing generates a WC code. `_codes_to_industry` only COMPARES;
  `naics_suggester` is NAICS/SIC only; when no class table was extracted the rating-table
  code boxes are OWNED BLANKS - `RateClass_ClassificationCode_A-N` sit in the
  deterministic-blank set, never in the LLM gap list (offline run, both `[]` and absent key).

Missing:
1. **No capture table.** `schedule_capture.SCHEDULE_DEFS` has vehicles / drivers /
   locations / losses only. Its NOTE ("wc_class_codes / wc_officers ... match ZERO real
   schema field") is STALE - the real ACORD 130 bindings were added 2026-08-15/16 but the
   table never was. The only human input is the scalar free-text `wc_class_codes`
   question (producer-only) and the `wc_officers` list question - and a string typed into
   a list fact stamps nothing and scores nothing (`_resolve_schedule_row` needs a list;
   `coverage_evidence._rows` returns `[]` on a string).
2. **Employee count per group** - not extracted, not bound, not stamped.
   `RateClass_FullTime/PartTimeEmployeeCount_A-C` reach the LLM (offline run).
3. **State** - extracted per row, printed nowhere. `RateState_StateOrProvinceName_A` and
   `PartOne_StateOrProvinceCode_A-J` reach the LLM.
4. **Officer include/exclude** - extracted as two booleans;
   `Individual_IncludedExcludedCode` unbound -> LLM. Officer state / duties /
   remuneration -> LLM.
5. **`wc_payroll_by_state`** is a free-text client question that stamps nowhere, and
   `cross_form_validator._check_wc_multi_state_payroll_breakdown` reconciles only a LIST
   shape (`cross_form_validator.py:600`) while the merge writes a DICT
   (`extraction_service.py:3764`) - `wc_state_payroll_total_mismatch` has never run live.
6. **One 8.3 leak:** `Individual_RatingClassificationCode_A-D` and
   `RateClass_DescriptionCode_*` DO reach the LLM with no schedule present (offline run) -
   code boxes the model can fill from prose.

#### Root cause [VERIFIED]

WC exposure was built as a **rating table for the FORM** (extractor reads it, stamper
prints it), never as a **fact a HUMAN can enter**. Every human-facing WC input is a
scalar free-text box over a list-shaped fact, so the answer is invisible to the stamper,
the scorer and the 130 checklist. Same class Figure 15 fixed for fleets (2026-07-21) and
H1-E fixed for auto ("a schedule-backed fact is asked ONCE, as its table"). WC was left
out of `SCHEDULE_DEFS` on 2026-07-21 because its bindings were dead THEN; the bindings
were repaired in August, the table was never added, the NOTE went stale.

#### Plan - reuse the schedule machinery; one table, no new fact key, no LLM

1. **`wc_class_codes` joins `SCHEDULE_DEFS`** ("Employee groups / WC payroll"). Column keys
   REUSE the extraction row keys so extraction -> table -> facts -> stamping is ONE shape
   (Principle 1): `description` ("Employee group and what they do", required),
   `full_time_employees`, `part_time_employees`, `payroll` (annual, required), `state`,
   `code` (**producer_only** - Principle 5, the same flag that hides comp/coll symbols
   from the client), `rate` (producer_only, so extracted rates survive a round trip). Two
   new registry bindings for the FT / PT count boxes; the extraction row gets the same two
   keys (v16 -> v17, C83 in `improving-ll.md`, ~15 tokens on the cached prefix, extraction
   cache invalidated once).
2. **State from the rows, positive evidence only.** Rating-sheet state printed only when
   every row shares ONE state (our template has a single sheet - a form limit);
   `PartOne_A-J` = the distinct row states; `wc_payroll_by_state` DERIVED (state ->
   summed payroll) only when every row has state AND payroll, labelled `derived`, never
   overwriting a stated value - the D28 / `_derive_from_dec_entries_h1` shape. Fix the
   dict/list defect (item 5) on the way.
3. **Officers table** (`wc_officers`), PRODUCER-only (C4 routes `wc_officers` to the
   producer). Needs a table-level `producer_only` flag honoured by
   `_finalize_schedule_taxonomy`, which today hard-codes every table to CLIENT - default
   off, the four live tables unchanged. Bind `Individual_StateOrProvinceCode` -> `state`
   and `Individual_IncludedExcludedCode` -> computed from the two booleans (Q26).
4. **Routing seam.** `question_eligibility.overlay_for` will tag the class-code table as
   insurance-judgment because its canonical key is `wc_class_codes`;
   `_finalize_schedule_taxonomy` then overrides the audience but leaves
   `eligibility_reason` / `producer_review` stale. Make `overlay_for` skip
   `field_type == "schedule"` - inside a table the column flags own the split. The scalar
   producer question "What types of work do your employees perform?" drops by itself
   (`_drop_scalar_duplicates_of_schedule_questions`). Retarget
   `wc_multi_state_no_breakdown` from `_R_NARRATIVE` to `_r_schedule("wc_class_codes")`
   so Resolve opens the table.
5. **Close the 8.3 leak** (item 6): the officer class-code and description-code boxes
   become owned blanks like the rating-table code box already is. A light normaliser
   splits a "8810 Clerical" cell into code + description ("normalize known formatting");
   suffixes untouched. Register `code` + `state` as the `_SCHEDULE_DEDUP_KEYS` identity so
   a class table printed on two pages does not survive the chunk union twice
   (`_NATURAL_ID_SUBKEYS` has no `code` - pre-existing).
6. **SQS: no new rule.** Only movements: a filled table fills `wc_class_codes` (the -10
   retires) and the payroll-period -3 retires because a typed annual-payroll column is
   annual by construction (`coverage_evidence._payroll_source_is_annual` reads row
   `payroll`). D6 - tell Brent.

**Why this and not the alternative.**
* A new `wc_job_groups` key beside `wc_class_codes` - two canonical facts for one
  exposure; the stamper, scorer, 130 checklist and class-code vote all read
  `wc_class_codes` (Principle 1).
* A separate "job title" column - ACORD 130 has no job-title box (Q25).
* One "employees" number - the form has FT and PT; one number lands in FT, a wrong value
  for a mixed group (Q24).
* Deriving `wc_payroll` / `total_payroll` from the row sum - a partial table gives a wrong
  total (H1-F class). Reconcile only; a rows-vs-stated warning is a NEW rule (Q29).
* Any LLM involvement - none; the client's 8.3 boundary and the standing blank-over-wrong
  rule both forbid it.

**Forward simulation (executed against every 8.x item).**
* 8.1, three groups typed by the client: rows -> `facts["wc_class_codes"]` -> restamp
  prints code / duties / payroll / FT / PT for A-C, sheet state "CO", PartOne A = CO,
  by-state derived. `_is_ops_class_code_mismatch` reads only the `code` key - 8810 / 8742
  are standard exceptions, 5551 governs, no false -15. `_class_exposure_amounts` picks
  money columns by NAME token (`_discover_class_schedule_money_columns`), so FT / PT counts
  are never read as amounts. Period status SATISFIED. HELD.
* Client leaves codes blank: column is producer-only anyway; code boxes stay owned blanks;
  the producer's table shows the same rows WITH the code column - "retain
  producer-entered codes". HELD.
* Extraction found 2 rows, client adds one: `current_rows` pre-loads; dedup on
  (description, state). HELD.
* Multi-state rows: sheet state blank (form limit, producer sees it), PartOne lists both,
  by-state derived, `wc_multi_state` re-derived from the dict, the hard stop satisfied -
  and the dormant 10% state-total hard stop RUNS for the first time (Q30).
* Empty table / no documents: nothing derived, nothing stamped, questions asked. HELD.
* Legacy sessions: old extracted rows lack FT / PT -> those cells blank. HELD.
* 8.2 facts: untouched except by-state (derived) and officer treatment (now printable).
  X-Mod / period / subcontracting paths unchanged. HNOA / Not-Applicable logic untouched.
* Tests expected to move: the column-binding test (must pass with the new bindings),
  `test_issue_resolution` schedule-mode keys (the retarget in step 4),
  `test_h1_coverage_gap_closure` officer shapes (unchanged). The
  `test_judgment_facts_route_to_producer` pins are scalar-question tests - unaffected.
* NOT testable offline: live render of a `number` column (`ScheduleTable` uses plain text
  inputs for every type; server `validate_cell` has NO `number` branch - add one);
  officer overflow (`ROW_CAPACITY` is a global 14, the form has 4 officer rows - the
  overflow notice would be wrong for officers); the producer-only table flag against the
  four existing tables (must default off).

**Blast radius.** Schedule plumbing (shared by the 4 live tables), question routing, the
extraction schema version, ACORD 130 stamping, one cross-form check. No SQS rule changes.
Nothing in C1-C5 / H1 / H2 moves except the payroll-period status behaving as H1 intends.

**UI.** No frontend change made, and NONE expected: `ScheduleTable.jsx` renders any column
spec the server sends, `ClientQuestionnaire.jsx` renders any `field_type: schedule`
question, and the producer pre-load panel in `AcordModal.jsx` iterates
`GET /api/arq/schedules`, which walks `SCHEDULE_DEFS` - a new table appears in both places
with zero frontend edits. The only visible difference after the build: two new tables
(client: employee groups; producer: officers) and the free-text WC questions they replace.

**Risks, named.** (1) The routing seam in step 4 - miss it and the client never sees the
table, or sees it flagged "producer review". (2) The state-total hard stop waking (Q30) -
scores DOWN on mismatched packages, an existing rule but D6. (3) `PROMPT_VERSION` bump
invalidates the extraction cache - a re-upload of an already-processed package re-extracts
once (~14 calls).

**Open for the owner - Q24-Q30 in the register above.** Nothing is built until they are
ruled; every default is stated there.

### H3-B - SHIPPED (2026-08-27)
**Priority:** V1-HIGH
**Principle(s) touched:** 1, 3, 5, 6, 7

**Owner ruling that unblocked it:** *"fix things properly ... fix all the client's
requirements of part 8 ... do not over engineer."* Read as approval of the engineering
defaults stated in Q24-Q30, EXCEPT Q29 - a rows-vs-stated-payroll warning is a NEW
validation rule and the precedence note forbids one without product approval. Q24-Q28 and
Q30 are recorded as owner-authorised defaults; Q29 stays open for Brent.

#### What shipped, by clause

| Clause | Client's direction | What now happens |
|---|---|---|
| **8.1 job group** | title / group, employees, duties, annual payroll, state, known class code | ONE client table on the existing `wc_class_codes` fact: "Employee group and what they do" (one cell - ACORD 130 has no title box, Q25), full-time + part-time (the form's two boxes, Q24), annual payroll, state; `code` and `rate` producer-only (Principle 5). Stamps rows A-N: code / duties / payroll / FT / PT; Part 1 states = the DISTINCT row states; the rating sheet's state label only when every row shares one |
| **8.2 total payroll / payroll period / X-Mod / subcontracting** | support when applicable | Unchanged - each already had a fact, a question and (for X-Mod / period) H1's evidence rules. A typed annual-payroll column satisfies the 6.4 period check by construction |
| **8.2 payroll by state** | support when applicable | DERIVED {state: summed payroll} from a COMPLETE table (every row has state AND payroll), `evidence_state: derived` with rule + inputs, never over a stated value, recomputed on every save and dropped when the rows stop supporting it (Q28). The free-text question falls out as already-provided. The multi-state hard stop's Resolve now opens the table |
| **8.2 owners / officers, inclusion / exclusion** | support when applicable | Producer-only officers table (Q27), 4 rows (the form's capacity). Included / Excluded is a typed word or the extractor's booleans, read ONCE by `coverage_evidence.officer_treatment_code`, printed as INC / EXC (Q26) on `Individual_IncludedExcludedCode`; officer state prints; unknown treatment stays an owned blank and still counts as unresolved for 6.4 |
| **8.3 extract / retain / normalize / compare, never recommend** | boundary | Extract: v17 row schema. Retain: producer-typed codes round-trip through the table. Normalize: "8810 Clerical" -> code 8810 + wording, suffixes untouched, never invents. Compare: the existing class-code vote, unchanged. Never recommend: EVERY ACORD 130 code box is schedule-owned - right-or-blank, the LLM is never asked (D45). `naics_suggester` verified WC-blind |

#### Root causes, and what each fix closes

1. **No human-enterable WC fact** (the class): `SCHEDULE_DEFS` lacked both WC schedules
   (stale NOTE from 2026-07-21; bindings repaired 2026-08-15/16, table never added). Fixed
   by two `ScheduleDef`s on the existing keys. Closes: free text typed into a list fact
   stamping nothing and scoring nothing, for every WC input.
2. **Per-row counts / state / treatment unbound** -> gap fill. Fixed by seven registry
   bindings; the family-level phantom-row logic already suppresses rows beyond the list.
3. **`_check_wc_multi_state_payroll_breakdown` read a LIST, the merge writes a DICT.**
   Fixed to read both (and the derived envelope). The 10% state-total hard stop runs for
   the first time - D6, scores can go DOWN (Q30, authorised).
4. **8.3 leak** - `Individual_RatingClassificationCode_A-D` and `RateClass_DescriptionCode_*`
   reached the LLM with no table. Fixed by owning them (D45).
5. **Class rows duplicated across chunks** (no natural id on a rating row). Fixed by a
   bespoke identity code + state + payroll - two locations' rows for one class do NOT fold
   (payroll differs); an exact reprint does.
6. **The eligibility overlay judged a TABLE by its canonical key** - `wc_class_codes` is
   insurance-judgment, so the client's own payroll table would have carried "producer
   review". Fixed at the door: a schedule question is never overlaid (D44).

#### Files
* `services/coverage_evidence.py` - `officer_treatment_code` / `_label`,
  `wc_class_row_states`, `wc_class_shared_state`, `wc_payroll_by_state_from_rows`,
  `normalize_wc_class_row`; `wc_officer_treatment_status` now reads the one helper.
* `services/schedule_capture.py` - `ScheduleDef(producer_only, row_capacity)`, the two
  defs, `capacity_for`, `is_producer_only`, `number` cell type, officer treatment cell on
  read, code normaliser on write, overflow against the schedule's OWN capacity, stale
  NOTE corrected.
* `services/pdf_service.py` - seven `_SCHEDULE_REGISTRY` bindings; `_resolve_schedule_row`
  answers the sheet state / Part 1 states / INC-EXC through `coverage_evidence`.
* `services/extraction_service.py` - v16 -> v17 (two row keys, C83 in `improving-ll.md`),
  `_wc_class_dedup_keys`, `derive_wc_facts_from_class_rows` (merge tail, before the
  multi-state flag re-derivation, which now unwraps the derived envelope).
* `services/arq_service.py` - producer-only taxonomy, `producer_only` + per-schedule
  capacity on the question payload, `_derive_wc_row_facts` on both save paths.
* `routes/arq_routes.py` - send path refuses a producer-only table; `client_view` skips
  it; per-schedule capacity.
* `services/question_eligibility.py` - schedule questions skipped (D44).
* `services/issue_registry.py` - `wc_multi_state_no_breakdown` (both engines) -> table.
* `services/cross_form_validator.py` - dict / envelope shape in the state-total check.
* `tests/test_h3_wc_data_capture.py` - 54 tests, every one against the real ACORD 130
  schema or the real merge helper. **No frontend file changed.**

#### Verification
* Offline, real schema, the client's own 8.1 example: rows A-C print code / duties /
  payroll / FT / PT; sheet "CO"; Part 1 A = CO, B-C owned blanks; by-state `{"CO":
  "$800,000"}` derived with provenance; officer A `INC`, state CO; officer with a typed
  "Excluded" -> `EXC`; a nameless treatment -> owned blank. Two states: sheet blank, Part 1
  CO / TX, by-state summed per state. Empty / absent table: NO code box in the LLM gap
  list. Partial table: nothing derived. Stated by-state value: untouched.
* Guard suites first (532 across schedule capture, eligibility, issue resolution, legacy
  rules, H1 x2, auto symbols, prompt caching, C3, C4): green. Then the full suite, LAST:
  **4751 passed / 1 failed** (`test_arq_acord125_missing_only`, the documented `httpx`
  ImportError), 14 skipped. Baseline was 4680 / 1.

#### Blast radius - tell Brent (D6, both directions)
* DOWN: any multi-state WC package whose by-state figures do not sum to the 125 payroll
  within 10% is now capped at 60 by an existing spec rule that had never fired.
* UP: a filled employee-group table retires the -10 "no WC class codes" and the -3 payroll
  period item.
* Cost: the v17 bump invalidates the extraction cache once per already-processed package
  (~14 calls on the next upload); +~15 tokens on the cached prefix.

#### Known / deliberately not done
* Q29 - rows-vs-stated-payroll warning: NOT built (new rule). Brent.
* `WorkersCompensation_RateState_StateOrProvinceName_A1` (the page-2 copy of the sheet
  label) does not match the row regex and still reaches the LLM. Same value either way.
* Officer rows B-D's UNBOUND columns (birth date, duties, remuneration, location number)
  still reach the LLM while a row exists - pre-existing; the root-level phantom capacity is
  the max over both WC lists. Not a code box, not an 8.3 concern.
* Not live-verified. The owner's next upload with a WC package is the check: expect the
  employee-group table in the client list (no code column), the officers table in the
  Agency bucket and the pre-load panel, and the 130's Part 1 / rating-sheet state printed.

### H3-C - LIVE TEST KIT + the defect the dry run caught before the owner did (2026-08-27)

**Kit:** `py backend/scripts/make_h3_test_pdfs.py` -> `h3_test_data/` with three
one-file packages and `README-HOW-TO-TEST.md` (what to upload, what to read on the
pre-form screen, which forms to generate, what to check on each and where, what counts
as a failure, and what is known-and-expected).

| Package | Proves |
|---|---|
| **W1** groups complete, ONE state | 8.1 the whole table on the 130 (code / duties / FT / PT / remuneration), 8.2 officers INC+EXC / X-Mod / subcontracting, payroll-by-state derived and AGREEING - the guard rail: the new hard stop must stay SILENT; 8.3 a compound "8810 Clerical" cell split; the same rating row printed TWICE folded to one |
| **W2** two states, totals disagree | Part 1 lists CO and TX, the rating sheet's state label stays BLANK, and the 10% state-total HARD STOP fires - the spec rule that had never once run |
| **W3** no class table | 8.3: every code box BLANK on a roofing account (5551 is the obvious code and Primble must not write it), the empty table still ASKED, a producer-typed code stamps, and the H1-K payroll-period -3 still fires |

Three uploads, 125 + 130 on each. Fixture rules recorded in the script's docstring
(a class row carrying an amount satisfies the period by itself - D43; W2 may print no
WC payroll TOTAL or the pre-existing 20% rule fires too and hides the one under test).

#### THE DEFECT - and it was mine, in H3-B, shipped and green

The dry run drives the real pipeline with the facts these documents produce.
W1's rows came back **6 printed -> 6 folded**, the derived payroll-by-state
**DOUBLED to $1,600,000**, and the new hard stop fired on the package built to prove
it stays silent.

**Root cause.** `_wc_class_dedup_keys` built its identity from the RAW code cell
(`re.sub(r"[^0-9A-Za-z]", "", ...)`), and the union runs BEFORE
`normalize_wc_class_row`. A premium summary printing `8810 Clerical` and a rating
sheet printing `8810` therefore produced `8810CLERICAL` and `8810` - two keys, two
rows, one row counted twice.

**Blast radius beyond the fixture, which is why it matters:** that is how real WC
packages print - a summary with a combined "CLASS CODE / CLASSIFICATION" column and a
rating sheet with separate columns. Any such document doubled its own payroll-by-state
and manufactured a false 60-cap.

**Fix at the root, one door:** `coverage_evidence.wc_class_code_token` is now the ONE
reading of "what code does this cell carry?", used by the normaliser AND by the union
identity, so the two cannot drift. Verified after the fix: 6 -> 3 rows, counts 2 / 3 / 8,
part-time 2 on the roofing row, by-state `{CO: $800,000}`, hard stop silent.

**Why the unit test did not catch it:** `test_the_same_rating_row_printed_twice_folds`
fed both printings in the SAME shape. A fixture easier than reality, exactly the trap
the change quality bar names. Now pinned by
`test_the_same_row_printed_in_TWO_SHAPES_folds` (the live shapes) and
`test_the_code_token_has_one_reader`.

**Standing lesson, and it is H1's lesson arriving one layer down:** an offline probe
proves the FUNCTION; only the SEAM catches this. The H3-B unit suite was 54 green
against a defect that would have shown up on the owner's first upload. **Build the kit
and dry-run it against the real code BEFORE calling a section shipped.**

#### Also found, not a defect - recorded so it is not chased

`WorkersCompensation_RateClass_Rate_*` is NON-FILLABLE in the ACORD template (a rate
is the carrier's to compute), so the RATE column never prints. The value is still
retained in the fact and still shown in the producer's table - preserved, not
discarded. Written into the kit's "known and expected" section.

**Suite after the fix: 4751 passed / 1 failed** (the documented `httpx` ImportError),
56 H3 tests. **Still not live-verified - the three uploads are the check.**

### H3-D - FIRST LIVE RUN (W1-W3): the form passed, the questionnaire did not - 7 defects, all fixed (2026-08-27)

**The owner ran all three packages and sent back the three generated ACORD 130s plus the
pre-form / questionnaire screens.** Everything H3-B built for the FORM worked on the first
attempt. Everything that had to reach a HUMAN was invisible. Seven defects, each traced to
a root cause in code before any fix was written.

#### What the run PROVED (do not re-test)

* the same rating row printed twice folded to **3 rows, not 6**;
* the compound cell split - code box `8810`, not `8810 Clerical`;
* per-group counts **2 / 3 / 8**, and the company headcount 15 never reached a group box;
* W1 Part 1 = `CO` only (three CO groups are ONE state); sheet = `CO`;
* W2 Part 1 = `CO TX`, and the rating sheet's state **BLANK** - it refuses to name one
  state for a two-state account;
* **the derivation works end to end**: W2's hard stop reads *"totals $800,000"*, a figure
  printed NOWHERE in the document - it was summed from the rows;
* the dormant 10% hard stop **fired**, capped at 60, and the trace reconciled
  ("70 earned, held at 60 = 60 / Why ...");
* W3: **zero class codes anywhere** on a roofing account - 8.3 holds;
* W3 WC Supplemental **97%** - H1-K's payroll-period -3 still fires;
* the officers table never reached the client.

#### The seven defects

| # | Symptom | Root cause | Mine? |
|---|---|---|---|
| 1 | **Neither WC table was ever asked.** Both appeared only in the producer's "Fill schedules yourself" strip | `schedule_capture.question_text`'s DEFAULT template began `"Please provide your "` - which IS `arq_service._MACHINE_QUESTION_PREFIX`. `_hide_machine_worded_questions` runs at line 3004, AFTER `_finalize_schedule_taxonomy`, and routed both tables to internal. The four original schedules escaped only because each happened to carry a hand-written override starting "Please list" | **YES (H3-B)** |
| 2 | The client was asked *"Provide your WC payroll breakdown by class code … (For example: 5183 Plumbing - $320,000)"* | `narrative_growth_trends` - a narrative slot repurposed into a classification question, so `wc_class_codes` in the judgment table never matched it. **The identical defect as `narrative_target_markets` (C4-S), one slot over, missed when that one was found** | no |
| 3 | W1 grew a third "officer" with duties *Roofing installation* and $520,000; **W2 printed three officers on a package with none**, carrying the three group payrolls; W3 printed $640,000 as an officer's pay | The officer row's four unbound columns (BirthDate / DutiesDescription / RemunerationAmount / LocationProducerIdentifier) fell to gap fill, and the model filled them from the employee-group table beside them | **YES (activated by H3-B)** |
| 4 | PART 3 OTHER STATES repeated Part 1 (`CO TX` / `CO` with Part 1 blank) | `PartThree_*` unbound -> the model copied Part 1. Part 3 means states NOT in Part 1 | no |
| 5 | INCREASED LIMITS = `1,000,000` (the EL LIMIT as a rating multiplier); ASSIGNED RISK SURCHARGE = the experience mod | seven `StateCoverage_*_ModificationFactor_*` boxes unbound -> gap fill took the nearest number | no |
| 6 | W2's premium block printed `STATE: CO` while the sheet directly above it correctly refused | `RateState_StateOrProvinceName_A1` - two trailing characters, so `_SCHED_ROW_RE` never matched it and the H3-B binding missed it | **YES (H3-B)** |
| 7 | *"Policy Effective Date: documents disagree (09/17/2026, 07/13/2026)"* - a false Data Consistency card, an Important warning and an **85 cap**, on W1 and W2 | `\b(?:policy\s+)?effective(?:\s+date)?` matches inside **"Experience Modification Effective Date:"**. Verified: that is the only "ffective" line in W1. Fires on EVERY WC package printing a mod effective date; the control is W3, which prints no mod and showed no conflict | no |

#### The fixes

1. **A TABLE IS NEVER A RAW SCHEMA PROMPT** - `_hide_machine_worded_questions` skips
   `field_type == "schedule"` (structural), AND the default template now reads
   "Please list your ...", AND both WC schedules got proper client-worded overrides.
   Three conditions because the wording alone is what failed.
2. `narrative_growth_trends` added to `INSURANCE_JUDGMENT_QUESTION_KEYS`. The
   "Subcontracted %" question and its HINT also dropped "(class code)" and the worked
   code examples - the FACT stays client-eligible (client 4.3), only the jargon went.
3. **Every remaining column of both WC schedules is now BOUND**, so nothing inside a WC
   row can be invented. Chosen over widening `_resolve_phantom_schedule_row`, which keys
   capacity on the FIRST name segment and so shares one capacity between officers and
   rating rows - narrowing that would change the Vehicle family's deliberately
   conservative "supported by EITHER list" rule for no gain here.
4. `PartThree_StateOrProvinceCode` bound to a new always-blank sub-key (`_wc_never`).
5. New `_resolve_wc_premium_cell` in `_AUTHORITATIVE_BLANK_RESOLVERS`: the experience mod
   fills its own box from `wc_xmod`; **every other rating factor is an owned blank**.
6. The same resolver owns `..._A1` and answers it from `wc_class_shared_state` - the
   premium block can never disagree with the sheet above it.
7. `underwriting_consistency._label_has_foreign_subject` - a label owned by another
   subject standing immediately in front of it is not this field's label. Structural
   (same line, last two words only), and a DENY-list so it can only ever drop a rival
   candidate, never invent one. Same shape as H1-K's payroll-period gate.

#### Verified after the fix (real code, real PDFs)

* zero WC boxes reach the LLM on all three packages (was 26);
* officer remuneration A/B/C = blank on W2; duties C blank on W1;
* Part 3 blank; IncreasedLimits / AssignedRisk blank; ExperienceOrMerit = 0.92 / 1.05,
  and blank on W3 which states no mod;
* premium STATE = `CO` on W1, **blank** on W2, blank on W3;
* `_text_scan_values(W1_text, "effective_date")` -> `[]` (was `['07/13/2026']`), while
  "Policy Effective Date: 09/17/2026" and a bare "Effective Date:" still scan;
* the real `generate_arq_questions` now emits **wc_class_codes -> client** and
  **wc_officers -> producer/agency**, neither suppressed, and no client question asks for
  a classification code.

**Blast radius, measured:** every field bound here exists on **ACORD 130 and no other
form** (267 fields; the other 16 schemas carry none). The questionnaire fixes are
form-agnostic but touch routing only.

Tests: `tests/test_h3_wc_data_capture.py` **64** (+8 for H3-D, each pinned to its live
shape). Guard suites 553 green. Suite **4761 passed / 1 failed** (the documented `httpx`
ImportError).

#### Standing lessons

1. **The seam, again, and this time it hid the whole feature.** H3-B's unit tests drove
   `_finalize_schedule_taxonomy` directly and were green while the step AFTER it undid
   the result. An offline probe proves the FUNCTION; only running the pipeline proves the
   ORDER. Third time in this file.
2. **A default that is the one string a downstream filter rejects is a trap, not a
   default.** `question_text`'s template had been that since Figure 15; four schedules
   survived only by each having an override. The next schedule would have failed too.
3. **When a defect is found in one instance of a pattern, sweep the pattern.** C4-S found
   one repurposed narrative slot and fixed that one; the sibling shipped to a client
   questionnaire for a month. The sweep is now a test.
4. **A necessary condition is not a sufficient one** - the classification sweep itself
   needed a structural second condition, or it would have flagged `gl_class_codes`, whose
   copy correctly says *"your agent will assign the classification code."*

### H3-E - ROUND 2 LIVE: all seven H3-D fixes CONFIRMED on the forms (2026-08-27)

Same three packages re-uploaded. **Six of the seven fixes are visible in the generated
ACORD 130s and the questionnaire, and all six hold. The seventh (the false
effective-date conflict) needs the PRE-FORM screen, which was not captured this round.**

| Fix | Round 1 | Round 2 |
|---|---|---|
| 1 tables never asked | absent from both buckets | **W1/W2/W3: "WC class codes" table in the CLIENT list** under a new "Workers Compensation" group; **owners/officers table in AGENCY** on all three |
| 2 client asked for class codes | client-facing, with NCCI examples | **gone from the client**; on W3 it now sits in Agency as "Producer-facing / Producer decision". "Subcontracted %" reads "by type of work" |
| 3 phantom officers | W1 grew a 3rd officer (*Roofing installation*, $520,000); **W2 printed 3 officers with none on file** ($90,000/$410,000/$300,000); W3 $640,000 | **W1 shows exactly Dana + Marcus, row C empty; W2's officer block is entirely EMPTY; W3 empty** |
| 4 Part 3 Other States | W2 "CO TX", W3 "CO" with Part 1 blank | **blank on all three**, Part 1 still correct (W1 CO, W2 CO TX, W3 blank) |
| 5 invented rating factors | INCREASED LIMITS = 1,000,000 / 1.05; ASSIGNED RISK = the mod | **only EXPERIENCE OR MERIT carries a factor** (0.92 / 1.05), blank on W3 which states none |
| 6 premium-block state | W2 said CO while the sheet refused | **W2 blank**, W1 CO, W3 blank |
| 7 false date conflict | card + 85 cap on W1 and W2 | **not observable** - pre-form screen not captured. Verified offline; still to see live |

Also confirmed: the per-row NAICS that used to print against row A alone is now blank on
all three; W3's rating table is still completely empty (8.3 holds).

**`producer_label` checked, NOT changed.** The producer's review screen shows the short
label "WC class codes" over the table. That map is stripped by the client-view whitelist
(verified: `producer_label` appears nowhere in `routes/arq_routes.py`), so the CLIENT sees
only "Please list your employees by group ...". Working as designed - a label change here
would have been a fix to a defect that does not exist.

#### Observed in round 2, none of them section 8, none of them fixed

1. **`# CLAIMS` invented in the prior-carrier grid** - `2` on W1, `1` on W2, on packages
   that state no claims at all. Round 1 put `1.05` in that grid's MOD column instead, so
   this is jitter in the same unbound family. **A wrong number on a legal form**, and the
   next thing worth owning - but it is the loss-history grid, not WC (the same
   pre-existing family that puts the CURRENT policy numbers under PRIOR CARRIER).
2. **"Experience Modification Factor" / "Experience Modification Effective" /
   "Workers Compensation"** written as TEXT into the premium block's "Other" description
   cells. Labels, not numbers - noise rather than a misstatement. `_WC_RATING_FACTOR_RE`
   owns the FACTOR boxes only.
3. **Marcus Ruiz's TITLE prints blank** on W1 where the document plainly shows
   "Vice President". The binding is proven correct (`Individual_TitleRelationshipCode_B`
   stamps when the row carries a title), so extraction did not capture the SECOND
   officer's title. Round 1 hid this because the LLM had put it in the DUTIES box; the
   form is now honest but less complete. An extraction-quality item.
4. **W2 lost the Q6 subcontractor "Y / 5%"** it answered in round 1. Compliance-pass
   jitter, untouched by H3.

#### Still to test - three things, nothing else

* the **pre-form screen** on W1/W2 (fix 7);
* the **W3 producer step** - type a group row carrying `5551 Roofing`, save, confirm it
  stamps and the payroll-period -3 clears. This is 8.3's "retain producer-entered codes",
  the only section 8 clause never yet seen live;
* the **client questionnaire link itself** - the table has only ever been seen in the
  PRODUCER's review list, never rendered as the client's editable grid.

---

## Session 2026-08-27 - H4 Core Submission Information Coverage (client section 9)

### H4-A - SHIPPED (2026-08-27)
**Priority:** V1-HIGH
**Principle(s) touched:** 1 (one canonical fact), 2 (normalize before comparing),
3 (missing is not No), 4 (do not silently resolve conflicts), 5 (never ask the client to
classify), 6 (provenance), 7 (unknown -> producer review)

#### What the client is actually asking for

Not "add fields". His own Current Problem section says it: *"The problem is not simply
whether a field exists. A fact may currently be: extracted; normalized incorrectly; asked
again; scoped incorrectly; scored in the wrong place; poorly sourced; treated as missing
when it is actually N/A."*

Sections 1-8 each fixed one feature. **Section 9 is the cross-cutting audit of the ~30
facts that decide a submission**, and 9.1 is its acceptance spec - four columns per fact:
when it applies, who is asked, where it scores, and the one rule not to get wrong. It
defines NO new scoring rule (principle 7 holds throughout).

#### Status before this session: ~75%. 21 of 30 rows held; 9 deviated, in FIVE classes

| Class | Defect | Rows |
|---|---|---|
| A | Routing keyed on a field NAME instead of the canonical fact | prior carrier, expiration date, GL form type |
| B | The client questionnaire DESTROYED "None" / "N/A" before the answer door | FEIN, prior carrier, every Tier 2 fact |
| C | "Applies When" never consulted before asking | contact name/phone/email |
| D | Entity type had FIVE vocabularies and none of them was ACORD's | entity type |
| E | A derived STATE existed but nothing wrote the FACT it implies | years in business, WC payroll period |

#### What shipped, by clause

| 9.1 row | Client's key rule | What now happens |
|---|---|---|
| **Prior Carrier** | *"Client factual answer allowed; Producer final"*, *"N/A / New Venture allowed"* | Reaches the CLIENT again (`_CLIENT_WHITELIST`). Brent's Q8 ruling (*"skip shortcut and ask client"*) was never implemented - `_AGENCY_PATTERNS` matched the substring and routed it producer-only, so the insured was never asked the one fact the -10 turns on. "Producer final" was already built (D12/D17) and is not re-implemented. Scope is structural: `prior_carrier_naic` and `prior_policy_number` stay agency because the whitelist is EXACT set membership, never a substring |
| **Proposed / Expiration date** | *"Client does not need to interpret policy period"* | `expiration_date` (plus `audit_period`, `billing_plan`) routed to the producer. It is a yellow REQUIRED box on ACORD 125, drives the effective-before-expiration hard stop, and is reassigned by `_route_renewal_dates` on a renewal - none of which an insured can reason about. **Still asked** (D32), in the Agency bucket |
| **Entity Type** | *"Normalize equivalent legal formats"* | ONE vocabulary. New `normalization.entity_family` (9 ACORD families) read by the validator and the stamper; `_ENTITY_TYPE_SYNONYMS` corrected. See the defect ledger below - this row had the most wrong with it |
| **Contact Name/Phone/Email** | *"Any one contact method satisfies Tier 1"* | The scorer always knew; the questionnaire asked all three as CRITICAL and pre-ticked them. Now DEMOTED to Important once any one is answered - **never suppressed** |
| **Annual Revenue / Number of Employees** | *"Explicit zero differs from missing"*, *"Zero/new venture can be valid"* | Already correct at every layer (validator, `interpret_answer`, `_fact_is_filled`, scorer). Verified, not assumed; now pinned |
| **Years in Business** | *"New venture is valid state"* | A confirmed New Venture derives `years_in_business` as **Not Applicable** (never "0" - see below), so Tier 2 stops charging 1/6 for history the business cannot have and the question retires. Withdrawn confirmation retracts it via `delete_facts` (D18) |
| **WC Payroll Period** | *"N/A if annual basis is clear"* | 6.4's four branches already decided it; the verdict only ever reached the SCORE. Now reaches the FACT, so nobody is asked the period of a figure that does not exist or is already annual by construction |
| **FEIN** | *"Do not invent"* | Unchanged and verified (C50's five stacked backfill conditions). What changed is that "N/A" is now an ANSWER rather than a discarded string |
| **Physical Address** | *"Do not universally require"* | **NO CODE CHANGE - deliberately.** See "Rejected" |
| GL/WC class codes, auto symbols, COPE, umbrella, loss status, payroll | - | Already compliant (C2/C3/C4/H1/H3). Now pinned by the matrix |

#### Class B, in full - closing F15 exposed four more defects on the same lines

F15 was recorded in C3-C on 2026-08-25 and never fixed: `arq_service._clean_answer_ex`
dropped `("n/a","na","?","unknown","none","null","-","--","tbd","unsure")` outright, so a
CLIENT answering "None" to our own question *"Who provided your business insurance most
recently? (If none, write 'None')"* had the answer thrown away, while the PRODUCER path
read the identical word correctly through `answer_semantics`. Two doors, two meanings, on
the exact question Brent ruled on.

The door is now `answer_semantics`, as C2-G always claimed. **Placement is load-bearing** -
three things stay ABOVE it, and each is a measured failure rather than a precaution:

1. **`is_not_sure_value`.** `_UNCERTAIN_RE` is `\b`-anchored and underscore is a word
   character, so `__NOT_SURE__` does NOT match "not sure" - the door returns VALUE and the
   sentinel would be stored and stamped as a real answer.
2. **The "null" / punctuation drop.** The door reads "null" as ordinary free text.
3. **The checkbox / indicator branch.** The door reads a bare "no" as an ABSENCE, which
   would empty every ACORD Yes/No box answered "No".

And four defects the change surfaced, all fixed:

* **THE BLOCKER: the raw string reaches the ACORD box BEFORE the fact envelope.**
  `field_state[field_name] = new_val` runs independently of `build_fact_envelope`, and
  `pdf_service._fill_and_highlight` skips only `('', 'null', 'None')` - **case
  sensitively**. So capital-N "None" was stopped by accident while "none", "N/A", "nil"
  and "not applicable" would PRINT on a legal form, labelled `client_arq` (green, "client
  supplied"). An absence now stamps "" and carries its meaning in `value_state`, which is
  what the producer path already did through `_deterministic_map`.
* **A Yes/No answer is never an absence.** The first cut re-interpreted the CANONICALISED
  "No" at the apply path and would have blanked every Yes/No box on every form. Caught by
  adversarial review; fixed with a structural second condition.
* **A required identity fact can never be "not applicable".** `fact_answered` credits both
  absence states and `_tier2_not_applicable` removes an N/A fact from the DENOMINATOR, so
  "Applicant legal name = N/A" scored as ANSWERED - one word in every box bought a perfect
  Structural pillar. Closed at the one door, using FACT_REGISTRY's own `required` flag, so
  the PRODUCER path is fixed in the same stroke. Brent's ruling is about facts whose
  absence is MEANINGFUL (a prior carrier, a claim count) and was never about the
  applicant's name.
* **A client "None" could silently delete an extracted narrative.**
  `verdict("operations_description", "Roofing contractor", "None")` returns SAME, so the
  P4 hold declined and the absence overwrote the fact. `_client_answer_conflicts_with_
  source` now has a structural first condition in the one direction the comparator
  provably cannot judge.

**Two live bugs fixed on the way, both independent of section 9:** a client typing "I will
confirm later" / "no idea" / "waiting on my accountant" was STAMPED on the form while an
empty envelope wiped the extracted fact (wrong in both directions in one pass); and a
client with no umbrella typing "nil" into a currency box had the WHOLE submission refused
with a 422 they had no correct answer for.

#### Class D, in full - entity type had five vocabularies

`answer_options.ENTITY_TYPE_OPTIONS`, `FACT_REGISTRY`'s literal uppercase set,
`pdf_service._INDICATOR_RULES`' nine substring rules, Guard 1's `_fact_entity_indicator`,
and `display_canonicalizer._ENTITY_DISPLAY`. Measured defects, all against the real
schemas:

* **Five live FALSE Data Consistency conflicts**, including ACORD 125's own checkbox
  wording: `values_conflict("entity_type", ["LLC", "Limited Liability Corporation"])` was
  **True**, because the full phrase was not a synonym key so "limited"->"ltd" and
  "corporation"->"corp". Also Sole Proprietor/Sole Proprietorship, Nonprofit/Non-Profit,
  Corporation/Incorporated, Partnership/General Partnership. `entity_type` IS a
  reconcilable field, so these reached a producer as review items on two values that are
  the same company. **This is literally the client's key rule for this row failing.**
* **Our own dropdown refused by our own validator.** `_validate_producer_answer` rejected
  8 of the 13 options `answer_options` offers - "Limited Liability Company", "S
  Corporation", "Joint Venture", "Association", "Municipality or Government Entity" - with
  *"That does not look right for this field"*.
* **The stamper ticked the wrong box.** "Sole Proprietorship" ticked NOTHING (ACORD's box
  is Individual); "S Corporation" ticked Corporation; "Non-Profit Corporation" ticked both
  Corporation and NotForProfit in Pass 1 and Guard 1 then collapsed to the WRONG one; and
  **any unrecognised value, including the empty string, asserted nine explicit "No"s** -
  principle 3 written on a legal document - while never reaching gap fill at all.
* **The two forms print DIFFERENT sets**, verified across all 17 schemas: ACORD 125 has
  Individual and NotForProfit; ACORD 130 has SoleProprietor and UnincorporatedAssociation
  and neither of those two. So a family maps to a SET of box words, not one name.

Fixed by one owner, `pdf_service._resolve_legal_entity_indicator`, copied in contract from
`_resolve_vehicle_use_indicator` (which exists because seven substring rules ticked two
mutually exclusive ACORD 127 USE boxes - H1-F). ACORD's own tooltip decides the shape:
*"Indicates the legal entity CODE for the named insured IS 'Corporation'"* - singular.
`entity_family` is ADDITIVE: `normalize_entity_type` still owns comparison (D3), and the
new validator is a proven strict SUPERSET of the literal set it replaces.

**`_entity_type_is_recognized` is deliberately NOT named `_is_entity_type`**:
`extraction_service`'s dec-page backfill enrols candidate validators by
`v_name.startswith("_is_")`, so that rename would silently add `entity_type` to a backfill
it has never taken part in. The name is load-bearing and says so.

#### Root causes, and what each fix closes as a CLASS

1. **Routing decided by a field NAME rather than the canonical fact** - the defect section
   4 exists to remove, and C4-I already recorded three instances. Closes: any fact whose
   ACORD spelling happens to contain (or miss) a pattern token.
2. **A door that predates `answer_semantics` keeping its own token list.** Closes: every
   place the client path and the producer path disagreed about the same English word.
3. **A rule that reads a coverage FLAG being consulted from a flag-free seam.** Closes: a
   whole family of "not applicable on every package" bugs - see the guard rail below.
4. **A mutually exclusive checkbox GROUP expressed as independent substring rules.**
   Closes: wrong-single-tick and multi-tick on any ACORD box group.
5. **A derived STATE with no corresponding FACT.** Closes: the scorer knowing something
   the questionnaire and Tier lists cannot see (H1's X-Mod and H3's payroll-by-state were
   the same shape).

#### The guard rail, and it caught me

The first cut of the WC payroll-period rule routed the Not Applicable decision through
`wc_payroll_period_status`, which reads `flags`. But `fact_state` calls
`h1_fact_not_applicable(fact_key, facts)` with **no flags**, and `facts["_flags"]` exists
only for the duration of one `annotate_fact_states` pass (set at line ~493, popped in a
`finally`). So the first line of that status function -
`if not _flag(flags, "has_workers_comp"): return NOT_APPLICABLE` - marked the fact Not
Applicable **on every package**, while the client's -3 was still being charged: **a
deduction with no route to remediation**, which is worse than the gap it was written for.

My own offline probe missed it because I passed `_flags` inside the facts dict - a
test-harness shape, not the production shape. **That is this file's own standing lesson,
verbatim: an offline probe proves the FUNCTION, never the SEAM around it.** Two independent
adversarial reviewers found it within minutes of each other. The predicate is now
FLAG-INDEPENDENT and reads facts only, and `test_h4_core_fact_matrix::test_the_payroll_
period_deduction_always_has_a_route_to_remediation` fails the build if a deduction is ever
charged on a fact the questionnaire has retired.

A second loop closed with it: `annotate_fact_states` writes DERIVED states back onto the
envelope, and `wc_payroll_period_status` read `_recorded_state` as authoritative - so once
a package had been annotated, adding a real payroll figure could never make the -3 fire
again. `_human_recorded_state` gates that on provenance: a person's "does not apply"
persists; our own conclusion is recomputed from the evidence every time.

#### Rejected, with the reasoning

* **Suppressing the physical-address question.** It looked like the obvious reading of
  *"Do not universally require"* and it is a **D32 violation**: 3.12's wording is about
  Structural Completeness (a SCORING statement), while `FORM_FIELD_INVENTORY["ACORD_125"]`
  still charges fill rate for `physical_address` on every package. Suppressing the question
  would leave the submission paying for a blank **nobody - client or producer - can be
  asked for**, which is precisely the measured precedent D32 exists to prevent. The
  measured cost of leaving it alone is one unticked OPTIONAL card (`points=3`, never
  pre-selected), and the form is unaffected either way (`_resolve_special('_loc')` falls
  back to `mailing_address`, so a blank physical address already prints correctly). Two
  further reasons it would have been wrong: `flags == {}` is the live shape from
  `proc_session.get("flags", {})`, so the filter would have silently stopped asking on any
  legacy session; and `_looks_like_street_address` returns True for a PO Box, so the
  question would have vanished on exactly the package the physical-vs-mailing rule exists
  for. **The residual is a SCORING question, raised as Q31 rather than decided here.**
* **Deriving `years_in_business = "0"` on a new venture.** Measured: a derived "0" makes
  `years_in_business_band` YOUNG, which makes route 2 of `loss_history_not_applicable` fire
  **on the band alone** - so the moment the New Venture confirmation was withdrawn,
  `calculate_p4_loss_history` returned **None (the Loss History pillar DELETED)** where it
  had returned 60. The N/A envelope gives band=unknown, leaves the pillar at 60, still
  retires the Tier 2 charge and the question, and displays as "NOT APPLICABLE" - which is
  what the client calls this state. It also stops arguing with Brent's *"we can't treat
  'N/A' as '0'"*.
* **Demoting the contact siblings to OPTIONAL.** `apply_default_selection` sends OPTIONAL
  to `default_selected=False; suggested=False`, so the ACORD 125 Contact Full Name and
  Email boxes would be blank AND unasked - three separate form fields behind one Tier 1
  requirement. IMPORTANT frees the pre-ticked slot (the entire measured cost) and keeps the
  cards visible.
* **Deleting or "fixing" `FACT_REGISTRY["tier"]`.** The audit's premise that it has no
  reader is **factually wrong**: `extraction_service._get_field_tier` maps it to
  `_TIER_WEIGHTS` and `_score_value` multiplies the merge score by it. It is a merge
  authority prior, not an SQS tier, and the two genuinely differ. Left alone; noted.
* **Suppressing the `narrative_growth_trends` injection** once the H3 employee-group table
  exists. Its ROUTING was already fixed by H3; stopping the INJECTION would take ~5 points
  off Narrative Quality on every WC package, because `_narrative_enrichment_present`
  credits that component only from that fact key. A D6 score move nobody signed off - Q32.

#### Files

* `services/normalization.py` - `entity_family` + `ENTITY_FAMILIES` + `_ENTITY_FAMILY_RULES`
  (additive; the comparator is untouched); six corrected `_ENTITY_TYPE_SYNONYMS` entries.
* `services/fact_registry.py` - `_entity_type_is_recognized` replaces the literal set.
* `services/pdf_service.py` - `_resolve_legal_entity_indicator` + `_ENTITY_BOX_WORDS`;
  the nine entity `_INDICATOR_RULES` retired.
* `services/arq_service.py` - the semantics door in `_clean_answer_ex`; the pre-stamp
  interpretation + C3 3.8 fill-rate label at the apply path; the P4 structural first
  condition; `_apply_new_venture_derivations` on both save paths; `new_venture_confirmed`
  retraction (pre-existing bug).
* `services/answer_semantics.py` - `_is_required_fact` + the required-fact gate.
* `services/loss_history_state.py` - `apply_new_venture_derivations`.
* `services/coverage_evidence.py` - `_payroll_period_already_settled` (flag-independent),
  `_human_recorded_state`.
* `services/question_eligibility.py` - four judgment facts; the Tier 1 contact demotion
  with its `score_impact` correction; the Step 1 audience leak.
* `services/question_classifier.py` - `prior_carrier` whitelisted.
* `services/sqs_service.py` - the Prior Carrier display row removed from Narrative Quality.
* `frontend/.../AcordModal.jsx` - the `contact_already_provided` badge.
* `tests/test_h4_core_fact_matrix.py` (47, new), plus corrected fixtures in
  `test_h1_coverage_gap_closure.py`, `test_question_controls.py`,
  `test_structured_input_types.py`.

#### Verification

**Suite: 4824 passed / 1 failed / 14 skipped** (`py -m pytest -q -p no:randomly`).
Baseline before this work, measured this session: **4777 / 1**. The one failure is
`test_arq_acord125_missing_only`, the documented `httpx` ImportError. **+47 tests, zero
regressions.** Frontend production build clean.

**Three test fixtures were corrected rather than deleted**, each with the superseded
assertion recorded in its own docstring:
* `test_structured_input_types::test_not_sure_and_blank_still_yield_no_answer` - its
  `_clean_answer_ex("n/a","total_payroll") == (None,"")` line WAS the test-side pin of F15.
* `test_h1_coverage_gap_closure::test_vehicle_use_..._payroll_period_is_the_producers` -
  passed `facts={}`, i.e. a package with NO PAYROLL, for which the period is genuinely Not
  Applicable. It was asserting the routing of a question that should not be asked, and
  passed only because the Not Applicable branch leaked `audience: client`. Both the code
  leak and the fixture are fixed.
* `test_question_controls::test_prior_carrier_and_policy_numbers_are_agency` - overruled by
  9.1's own routing column and Brent's Q8.

#### Blast radius - D6, tell Brent BOTH directions

| What | Direction |
|---|---|
| A client answering "None" / "N/A" now earns explicit-no credit or leaves the fill-rate denominator | **UP** |
| The no-prior-losses attestation typed as "None" finally sets its flag (~5 pts, Loss History) | **UP** |
| Confirmed new ventures stop being charged 1/6 of Tier 2 for Years in Business | **UP** |
| Entity-type false conflicts stop raising Data Consistency review items | UP (fewer cards) |
| Submissions previously refused with a 422 for typing "nil" now complete | **UP** |
| "N/A" typed into a REQUIRED identity field no longer buys a Tier 1 credit | **DOWN** (correctly) |
| A client absence that contradicts a document is now HELD for the producer | neither - a new picker row |
| Prior carrier reaching the client may close the -10 sooner | UP, per account |

**Presentation only, no score:** the Prior Carrier row leaves the Narrative Quality panel.

#### Known / deliberately not done

* **Not live-verified.** The owner's next upload is the check. Expect: prior carrier in the
  client list; expiration date, GL form type, audit period and billing plan in the Agency
  bucket; one entity checkbox ticked on the 125; and a client "None" surviving as an answer.
* **The schedule branch still eats absences.** `schedule_capture.decode_answer` returns `[]`
  for "None", "N/A" and "we have no vehicles" alike, so a client saying there are none is
  indistinguishable from one who never opened the table. Per D44 the right fix is an
  explicit "there are none" control on the table widget, not free-text parsing. Out of scope.
* **The producer is asked for the X-Mod TWICE** (`wc_xmod` and `narrative_target_markets`,
  both injected on any WC package, both producer-routed). Pre-existing; C4-I fixed the
  routing of the second and left the duplication. Same shape as Q32.
* **`_derive_indicator`'s two dead rules** (`NamedInsured_EntityType`,
  `NamedInsured_BusinessEntity`) match no field in any of the 17 schemas. Harmless, noted.
* **ACORD 130 prints no Not-For-Profit box**, so a non-profit employer's WC application has
  nowhere deterministic to go and the group is left to the evidence-gated fill. A form
  limit, not a defect; pinned by the matrix so nobody "fixes" it into a wrong tick.

### H4-B - FIRST LIVE RUN (c9 kit, 3 packages) + the owner's two UI questions (2026-08-27)

**Owner ran P1-P3 through the real app and sent the screens.** Recorded in full: three
H4 fixes are confirmed live, one fixture defect meant a fourth check tested nothing, and
two of the owner's questions turned out to be answered by the client's own spec.

#### What the run PROVED live

| Check | Result |
|---|---|
| **Prior carrier reaches the CLIENT** (H4-A class A) | **PASS** - "Prior / incumbent carrier ... Client sees: Who provided your business insurance most recently? (If none, write 'None')" sits in the Client bucket on P1 and P2 |
| **Expiration date / GL form type / audit period / billing plan reach the PRODUCER** | **PASS** - P2's Agency bucket carries "Policy expiration date"; P1's carries the GL retro date, GL limits and deductible; P3 asks for none of them because it states them all |
| **Contact demotion** (H4-A class C) | **PASS** - P1 supplied a phone only, and "Primary contact - name" and "Primary contact - email" both came back **Important / Suggested** carrying the new **"Contact already provided"** badge, still visible and still selectable. Zero Critical questions on the whole package |
| **The WC payroll-period guard rail** | **PASS on P3** - the package whose payroll label states the period asks nobody and is charged nothing (WC Supplemental 100%, no period question anywhere) |
| **The Prior Carrier display row is gone** | **PASS** - P1/P2/P3 all render Narrative Quality with its own row only; "Prior Carrier / Marketing Reason" no longer appears as a scoring sub-row (it correctly remains in the NARRATIVE COMPONENTS taxonomy, which is a different thing - whether the narrative discusses it) |

#### THE FIXTURE DEFEAT: check 4 tested nothing, and every word-level guard passed

P1 exists to prove the WC payroll-period **-3 fires AND the producer is asked** - the one
branch where the client's 6.4 deduction is charged. The live run showed the opposite:
`WC payroll period / basis` badged **"Not applicable"**, WC Supplemental **100%**, no
charge. The deduction and the question still AGREED (which is the property that matters,
and it held), but the charging branch was never exercised.

**Cause, measured.** P1A printed its GL schedule of hazards as
`PREMIUM BASIS: Payroll / EXPOSURE: $1,240,000`, and
`coverage_evidence._payroll_source_is_annual` accepts a payroll or remuneration rating
basis on ANY class-code schedule - including a General Liability one - as a statement that
the package's payroll is annual (a rating schedule states annual remuneration by
definition). So the period resolved to SATISFIED.

Measured side by side: basis `Payroll` -> `satisfied`; basis `Gross Sales` -> `missing`.

**This is the C4-J lesson one level deeper.** A scenario cannot test a value it states -
and P1 stated it OBLIQUELY, through a different coverage line's rating basis. Every
`_FORBIDDEN` word ban passed, because the fixture never used the words "annual payroll".
The fix is a STRUCTURAL check, not another banned word: across both P1 files the token
"payroll" may now appear **exactly once** (the bare WC figure) and never as a rating
basis. Proved non-vacuous by reverting the basis and confirming the generator exits
non-zero.

#### The owner's two questions, answered from the spec rather than from opinion

**1. "Policy date mismatch across documents - did the client ask for this?"** YES, verbatim.
`SQS_Scoring_Specification` section 4, *"Conditions: complete hard-stop list"* ->
**Cross-document identity conflicts, 4 conditions**: applicant legal name, FEIN,
*"3. Effective date differs across uploaded documents"*, *"4. Expiration date differs
across uploaded documents"* - all feeding the 60 ceiling, with the note *"Items 3 and 4
downgrade to warnings when a document carries an explanation that specifically addresses
the policy period."* The rule stays. What was wrong was where it FIRED - see H4-C.

**2. "Remove Tier 1 / Tier 2 - did the client ask for this?"** YES - they are the client's
own vocabulary. Spec section 3.1 IS the formula
(`Structural = Tier 1 x 0.35 + Tier 2 x 0.30 + Fill rate x 0.35`, reweighted to
40/35/25 by master-plan 3.2) and names *"Tier 1 - six fields plus contact"* and
*"Tier 2 - twelve fields"*; master-plan section 9.1's own **"V1 Scoring Home"** column
reads "Structural Tier 1" / "Structural Tier 2 + identity consistency" on roughly fifteen
rows.

**Owner's decision after being shown that: hide the two rows in the UI ONLY.** Done, and
the distinction is enforced by where the change lives - a
`HIDDEN_SQS_CATEGORY_KEYS = new Set(["tier1","tier2"])` filter in `AcordModal.jsx`, beside
the existing `_rollup` filter. Verified after the change: `_structural_parts` still emits
`tier1 (0.40) / tier2 (0.35) / fill (0.25)` summing to the same pillar (78.2 on the
owner's own screenshot values), `check_tier1` / `check_tier2` are untouched, and
`build_score_trace` still carries the whole C3 ledger. **Form Fill Rate is deliberately
NOT hidden** - it is the one Structural input that is not tier jargon and the producer acts
on it directly.

**Nothing is lost to the producer**, and that is worth stating because C3's Desired Outcome
is traceability: the SAME Tier 1 + Tier 2 content still reaches them in plain language on
the pre-form Review card as "Key details in place / missing" (H2's `key_details`, which
reads the identical two lists), and the full arithmetic remains in `score_trace`.

#### A THIRD defect the run exposed: New Venture was being asked to the CLIENT

Two of the three packages showed **"New venture confirmation - Client sees: Is this a
brand new business with no prior operating history?"** in the CLIENT bucket - including P3,
a twelve-year-old business with a stated prior carrier.

`FACT_REGISTRY["new_venture_indicator"]` sets `question: None` and `forms: set()`, and its
own comment reads *"Producer confirmation (client 2.2: 'if the producer confirms') - it is
answered from the Loss History card, **never asked to the client**."* It was asked anyway:
`arq_service._FIELD_QUESTION_MAP` carries curated wording for the key, which makes
`is_curated_client` true, which routes it CLIENT / optional. A documented intent and the
behaviour had drifted apart - section 9's "asked again / scoped incorrectly" class exactly.

**Not cosmetic.** `apply_arq_answers_to_session` sets `flags["new_venture_confirmed"]` from
this answer exactly as the producer path does, and a confirmed New Venture takes the whole
Loss History pillar to Not Applicable (C2 2.2) and now also marks Years in Business Not
Applicable (H4-A). That is a scoring-material determination about the account, and client
2.2 gives it to the producer in terms. Fixed by adding `new_venture_indicator` to
`INSURANCE_JUDGMENT_FACTS`; the producer keeps answering it exactly where C2 put it, on the
Loss History recommendation card, which is a different surface and is untouched.

#### Still unproven after this run

* **Check 5, the headline** - a client answering "None" / "N/A" and it surviving the round
  trip. Needs a send-and-answer, which a forms click-through cannot do.
* **Checks 7-10 (P2)** - the New Venture confirmation was never given, so the derived
  Years-in-Business Not Applicable, the score movement and the retraction are all unproven.
* **Checks 6 / 12** - the generated ACORD 125 LEGAL ENTITY boxes were not sent back.
* **Check 4** - now reachable for the first time after the fixture fix.

### H4-C - THE POLICY-DATE HARD STOP: investigated, NOT changed, and the real defect it is pointing at (2026-08-27)

**Owner's question:** *"Did the client ask us to do this? If not, remove it from the SQS
screen"* - about the P1 message *"Policy date mismatch across documents. Score is capped at
60 unless the difference is explained."*

**Answer: YES, verbatim, and it stays.** `SQS_Scoring_Specification` section 4,
*"Conditions: complete hard-stop list"* -> **Cross-document identity conflicts, 4
conditions**: 1. applicant legal name, 2. FEIN, **3. Effective date differs across uploaded
documents**, **4. Expiration date differs across uploaded documents** - all feeding the 60
ceiling, with the client's own escape hatch: *"Items 3 and 4 downgrade to warnings when a
document carries an explanation that specifically addresses the policy period."*

**OWNER'S RULING, 2026-08-27:** *"if different docs shows different values of same thing
then we can show it to the user."* That is already the shipped behaviour and it is why
nothing changed here. Measured on the live shape (application 10/01/2026 + dec page
10/01/2025):

```
DATA CONSISTENCY row - effective_date
  status: conflict   review_required: True   merged_value: 10/01/2025
    candidate '10/01/2026'  <- P1A_application.pdf
    candidate '10/01/2025'  <- P1B_dec_page.pdf
```

Both values, each attributed to its own file, with a one-click resolve. The rule detects
it, the panel shows it, the producer decides. **No code change.**

#### The fix I proposed was REFUTED by all three reviewers, and they were right

The proposal was to add `dec_page` to `fact_comparison._ROLE_BLIND_FACTS` for
`effective_date` / `expiration_date`, the way C1-I added `loss_run`. It works on the
reported case - measured, `app+dec` goes clean and Tier 1 does not regress - and it is
still wrong, three ways:

1. **It silences REAL conflicts (P4).** Two dec pages with different terms, a dec page and
   the COI issued off it with different terms, and `app+dec+dec` where the two dec pages
   disagree with EACH OTHER all go **CLEAN** - not downgraded, deleted from every surface.
   The picker row disappears entirely (0 witnesses -> no values -> field skipped), and
   `detect_source_conflicts` cannot pick up the slack because both keys sit in
   `extraction_pipeline`'s static `_consistency_owned` skip set. The dec-page-vs-certificate
   case is the C1/Orbin $3M-vs-$1M shape one field over, and it is one of the
   highest-signal conflicts the picker catches.
2. **It destroys the output of a strictly better mechanism.** `facts["_scoped"]` (D19)
   already covers `effective_date` / `expiration_date`. On a genuine two-policy package
   whose `coverage_lines` attribute each term to its own line, the picker TODAY returns
   `status: scoped, review_required: False` with both values retained under their scope -
   the right answer, with evidence. Role blindness deletes that verdict too.
3. **It makes the role table assert something false.** `_ROLE_BLIND_FACTS` means "this role
   does not state this fact". For a loss run and a policy date that is true - C1-I's own
   note says the loss run's "period covered" is a 5-year claims window, not a policy term.
   For a declarations page it is the exact opposite: a dec page is the single most
   authoritative statement of a policy term in the package.

**Why the existing downgrade did not fire, measured.** `CONTRACT_SCOPED_HARD_STOP_KEYS` is
already exactly `{effective_date, expiration_date}` and both engines already consult one
downgrade decision - but both gate it on `eq_context.is_multi_contract`, which is literally
`len(contracts) >= 2` where `contracts` is the set of distinct POLICY NUMBERS from the dec
index. An application proposing a term carries no policy number, so `app + dec` is ONE
contract and the downgrade never runs:

```
app + dec, index carries 1 policy number  -> [hard_stop] date_conflict, [hard_stop] expiration_conflict
app + dec, index carries 2 policy numbers -> [warning]   date_conflict, [warning]   expiration_conflict
```

Same two documents, same two dates; only the number of indexed contracts changed. The
mechanism was written for "three policies, three terms" (probe run C, 2026-08-17) and
nobody wrote the "one bound policy + one proposed term" case. `_dates_owned_separately`
fails for the same reason - the application's date is unattributed in `value_owner`.

**A bound-vs-prospective downgrade was also proposed and also NOT taken.** It is the right
AXIS (a dec page / policy / certificate / binder / endorsement documents a policy that
EXISTS; an application / supplemental application / quote describes the term being APPLIED
FOR - two different real-world objects, so their dates are not rival answers), and it
belongs behind one door because the comment at `CONTRACT_SCOPED_HARD_STOP_KEYS` records
what happened last time each engine held its own copy. It was not taken because a
downgrade only moves the ceiling **60 -> 85**, not to uncapped - measured, not assumed - so
it half-fixes a package that is not actually defective, while the owner's ruling
("show it to the user") is already satisfied by the picker. Recorded here so the next chat
starts from the measurement instead of re-deriving it.

#### THE REAL DEFECT UNDERNEATH - NOT FIXED, and it is the one that matters

**The declarations page's EXPIRING effective date wins the merge and is what stamps into
ACORD 125's PROPOSED EFFECTIVE DATE box.** Measured end to end through the real merge:

```
_DOC_TYPE_PRIORITY: dec_page = 0, application = 1
select_primary_truth(app 10/01/2026, dec 10/01/2025) -> dec_page
merge_facts(...)["effective_date"]                   -> 10/01/2025   <- the EXPIRING term
```

So on the most common commercial-lines upload shape - current dec page plus a new
application - the form ships the term that is ENDING in the box that asks for the term
being APPLIED FOR. **The hard stop is crude and fires for the wrong reason, but it is
currently the only thing on any screen pointing at that box.** That is the single strongest
argument against silencing it, and it is why this entry changes nothing.

This is a known class, half-fixed: `FIX_TRACKING_2026-08-15.md` RC1b records exactly this
defect ("RULE 1's 'current policy' IS the expiring dec on a renewal, so 07/15/2025-07/15/2026
stamped as the PROPOSED term") and fixed it with `_route_renewal_dates` - which fires ONLY
when `is_renewal` is affirmative AND the term has already ENDED. A rewrite to a new carrier
is neither, so it falls straight through. `_resolve_renewal_proposed_period` is gated on
`renewal_dates_routed`, which only `_route_renewal_dates` sets, so the proposed-date boxes
are not owned blanks either. **There is nothing between the merge and the PDF.**

**Deliberately not fixed in this pass.** It is a change to `merge_facts` / primary-truth
selection, which every fact and every package flows through, and it has not been through an
adversarial round. Raised as **Q33**. Recommended shape when it is taken: extend RC1b's own
mechanism rather than reordering `_DOC_TYPE_PRIORITY` - for `effective_date` /
`expiration_date` ONLY, a PROSPECTIVE document's stated term outranks a BOUND document's,
and the bound term routes to the existing `prior_*` namespace.

#### Also worth knowing (found while tracing, none of it acted on)

* `policy_effective_date` / `policy_expiration_date` are DEAD KEYS - present in
  `_FIELD_CONFIDENCE_SOURCES`, `normalization.DATE_FIELDS` and the alias map, with zero
  writers and no FACT_REGISTRY entry. The same dead pair already sits inside the `loss_run`
  role entry, where it has never done anything.
* The picker's role skip is a `continue` at the TOP of the per-document loop, so any role
  entry suppresses Pass 1 (LLM fact), Pass 1b (per-coverage-line) AND Pass 2 (raw-text
  scan) together. A role entry is total, never partial.
* **CLAUDE.md's standing note that `test_normalization` is a known pre-existing failure is
  STALE** - it is green at HEAD (28 passed). Anyone using that note as cover for a red
  `test_normalization` would be waving through a real regression.

---

## Session 2026-08-27 - H7 Audit / Edit History Completion (client section 12)

### H7-A - Full audit of section 12 - ANALYSIS COMPLETE, NOT YET BUILT (2026-08-27)
**Priority:** HIGH
**Principle(s) touched:** 1 (One Canonical Fact), 6 (Preserve Provenance)
**Relationship to C5:** section 5 built the RECORD. Section 12 asks for the MODEL under it.
C5 is not being reopened; nothing in C5-A..C5-E is contradicted by anything below.

#### What the client is actually asking for
Not a new report. He is asking us to stop **generating** history and start **recording** it.
His own words: the record must be *"generated from real system history rather than
reconstructed later from incomplete current state"*, and one event model must serve four
consumers - product history, debugging, source lineage, E&O Audit Record.

#### Status - ~55% [VERIFIED]
| Piece | State |
|---|---|
| Append-only spine exists (`audit_events`) | shipped C5-A |
| Field-level before/after log (`field_source_audit`) | writes at 8 call sites |
| Conflict resolutions durable + append-only (`underwriting_confirmation_audit`) | yes |
| Source lineage (`fact_lineage.py`, computed at export - D36) | yes |
| **All 8 client-listed events reach the spine** | **1 of 8** |
| **Actor rendered anywhere in the record** | **0 of 12 sections** |
| **Role** | no column anywhere |
| **Reason on a field change** | no column |
| **One model serving all four consumers** | four disconnected mechanisms |

#### ROOT CAUSE - one class [VERIFIED]
**The operational tables were made to double as the audit trail.** They are correctly
MUTABLE - dismiss-credit, the download gate, the issue rail and reopen all read them as
current state - and an audit trail must not be. One table cannot be both, so history was
destroyed every time the workflow needed to move on.

`get_audit_trail_export` (audit_service.py:1101) visits EIGHT tables plus the live session
blob and returns 15 disjoint arrays. It is an aggregator, not a reader of a history.

#### The five verified consequences

**1. Only 1 of the client's 8 events is an event.**

| Client event | Where it lands today | History? |
|---|---|---|
| producer edit | `field_source_audit` INSERT | partial - no reason, no role, actor not rendered |
| client answer | `field_source_audit` + `client_answers_applied` event | the only one on the spine |
| producer override | `download_audit` / `submission_integrity_audit` | NO - and the integrity table has ZERO readers |
| conflict resolution | `underwriting_confirmation_audit` INSERT | append-only, but not on the spine |
| issue resolution | `submission_issue_status` **UPSERT** | NO - latest-wins, one row |
| recommendation dismissal | `sqs_recommendation_audit` **UPSERT** | NO - latest-wins, one row |
| form edit | same path as producer edit | not distinguished |
| generated-value override | nothing | not modelled at all |

The asymmetry is the tell: **reopen** writes an event (`recommendation_reopened`,
`issue_reopened`) because C5 needed to rescue state the UPDATE was about to erase.
**Dismiss and resolve do not.** History was added where it was rescued, not where it belongs.
Also destructive: `mark_recommendation_answer_recorded` OVERWRITES `producer_answer` and
`answered_at`, so answer -> reopen -> re-answer keeps only the last value.

**2. The record never names a human.** `user_id` is stored in `field_source_audit`,
`sqs_recommendation_audit`, `submission_issue_status`, `underwriting_confirmation_audit` and
`audit_events`. `get_field_change_log` and `get_download_audit_log` do not even SELECT it.
Nothing anywhere resolves a `user_id` to a name or email. The renderer prints
`Changed by: producer edit` - a METHOD, not an ACTOR. The only named human in the whole
record is the client, from `arq_receipts`.

**3. Two parallel event logs with near-identical schemas.**
`activity_events` (product history, navbar Activity Log, 9 event types, NEVER swept) and
`audit_events` (E&O only, 5 event types, swept at 180d). They record the SAME acts under
different names: `answers_applied` / `client_answers_applied`, `sqs_scored` / `sqs_snapshot`,
and **one download writes three rows across three stores** (`download_audit`,
`acord_audit_log`, `sqs_snapshot(trigger=package_downloaded)`). This IS the client's
"separate reporting subsystem disconnected from the actual workflow". Closed by D50.

**4. The spine expired BEFORE the state it explains.** Four clocks: `audit_events` 180d;
`field_source_audit` / `sqs_recommendation_audit` / `acord_audit_log` 365d;
`underwriting_confirmation_audit`, `submission_issue_status`, `submission_integrity_audit`,
`marketing_reason_audit`, `download_audit`, `arq_receipts`, `activity_events` NEVER;
session facts 180d (free/essentials). Closed by D48.

**5. One common path destroys audit rows.** `sync_field_qa_findings` and
`sync_field_mapping_findings` run a DELETE of every `fieldqa_` / `fieldmap_` prefixed row in
`sqs_recommendation_audit` then reinsert (audit_service.py:132, :220) - and they run on
**every producer field edit** (form_routes.py:2178). A dismissed field-QA item and its typed
reason are erased on the next edit and vanish from DISMISSED ITEMS.
**Bounded honestly: NO SCORE MOVES.** Those rows carry `score_impact: None`
(field_qa.py:574 etc.), so `dismiss_earned_credit` was always False. Audit loss only.
The spine fixes this for free - once the dismissal is an immutable event, the DELETE only
clears the work queue, and C5-A's stale-findings concern is respected unchanged.

#### THE FIX - agreed shape (owner rulings 2026-08-27, D48-D52)
Five changes. **No migration of an existing table, no touch to scoring, gating or
dismiss-credit.**

- **A. One envelope, one writer.** `audit_service.record_material_change(...)` wrapping
  `log_audit_event`, enforcing the client's seven attributes in a fixed shape:
  `{fact_key, field_name, form_id, previous_value, new_value, previous_source,
  actor:{id,name,email}, role, action, reason, occurred_at}`.
- **B. Emit from INSIDE the existing writers, never from the routes** - `log_field_change`,
  `mark_recommendation_dismissed`, `set_issue_status`, `log_underwriting_confirmation`,
  `log_document_reclassified`, `log_integrity_resolution`. A call site cannot forget. Same
  one-door idiom as `fact_comparison` (D3) and `coverage_evidence` (H1).
- **C. The three data holes.** Actor: one lookup of id / full_name / email over the distinct
  user ids per export, rendered on every row. Role: derived per D51.
  Generated-value override: at form_routes.py:1791-1793 `prev_state` AND the prior
  `confidence` dict are both already in scope before the edit applies - pass the prior
  confidence as `previous_source`, and `ai_high` / `ai_low` vs `filled` vs empty separates
  "overrode a generated value" from "corrected a human entry" from "filled a blank".
  **The client's 8th event, for one argument.**
- **D. One chronological section.** Export gains a `history` array from the spine; the
  frontend gains ONE "COMPLETE HISTORY" section. The existing 12 sections stay as detail
  views, so nothing regresses.
- **E. One model (D50).** `activity_service.record_event` becomes an adapter over the spine;
  the Activity Log reads a user-scoped projection. `activity_events` kept read-only for
  pre-existing rows. Needs three additive changes on `audit_events`: `package_label`, an
  index on (user_id, created_at), and a visibility marker separating product-history events
  from E&O-only ones.
- **F. `submission_integrity_audit` gains its first reader** (owner: "fix it as well") -
  document reclassification and multi-insured overrides are two of the client's "producer
  override" events, written at three sites and invisible. Same defect C5-A fixed for
  `underwriting_confirmation_audit`; it recurred.

**Rejected, with reasons.** (a) *One unified events table replacing all nine* - correct in
the abstract, but `sqs_recommendation_audit` drives dismiss-credit, the download gate and
reopen, and `submission_issue_status` drives the issue rail; rebuilding them as projections
touches C1, C3, C5, H1 and H2 at once. Rejected on blast radius. (b) *Add actor to the record
and stop* - that is the symptom; six months later a new action ships with no event, exactly
as dismissal did. (c) *Preserve dismissed rows through the fieldqa DELETE* - C5-A already
recorded the stale-findings risk; the spine makes the DELETE harmless instead.
(d) *A role column on `users`* - no RBAC exists to read (D51).

#### FORWARD-SIMULATION - what breaks, before anyone writes code
**Holds:** `test_audit_events_table_is_registered_and_append_only` pins that nothing in
`audit_service` UPDATEs or DELETEs `audit_events` - every change here is INSERT-only. The
5.12 snapshot dedupe filters on `event_type='sqs_snapshot'` (audit_service.py:912), so new
event types cannot disturb it. No change to `sqs_recommendation_audit` semantics,
`active_score_credits`, `_apply_dismiss_score_credit` or any cap. C1's `candidates` snapshot
is read and re-emitted, never modified. H1-G, C3's `score_trace` (D33) and H2's
`current_package_sqs` untouched.

**BREAKS - must ship in the same commit:**
1. **`test_six_month_retention_ruling_is_implemented`** asserts the literal 180-day getenv
   expression in `scheduler_service`. D48 changes it. Update the test WITH the ruling
   recorded above - the 6-month floor is being extended, not weakened, and the
   facts-retention half of Q18 is untouched.
2. **The frontend EVENT LOG renderer** has a hardcoded if/else per event type
   (AcordModal.jsx:4989); unknown types print a bare name with no detail.
3. **PII rule inversion (D50 consequence).** `activity_service`'s docstring rule is
   "no fresh PII - client FIRST name only, never the email, so the table needs no
   field-level encryption". `audit_events` ALREADY stores `client_email` in
   `client_answers_applied` (arq_service.py:4344). Merging makes the product-history store
   inherit that. Not a blocker - the spine is already the more sensitive table - but the
   activity_service rule becomes obsolete and must be retired deliberately, not by accident.
4. **`activity_events` is never swept; the spine is swept at 365d (D48).** Product history
   that is permanent today starts being deleted at 365 days. Deliberate, tell Brent (D6).
5. **Volume.** Every field edit writes 2 rows instead of 1 (a 100-field form edit becomes
   200). Not a problem at 0 users; stated so it is not a surprise later.

**Checked and NOT a problem:** `arq_sessions.session_id` is NOT NULL, so the five
`record_event` call sites reading `arq.get("session_id")` cannot in practice hand a NULL to
`audit_events.session_id` (which IS NOT NULL). One defensive guard, not a redesign.
`source='ai'` is allowed by the `field_source_audit` CHECK and has never been written by any
caller - the change log starts at the first human touch, which is correct: all 8 of the
client's events are human acts, and ingestion is already covered by `documents_uploaded`.

#### Owner rulings received 2026-08-27 (all five open questions closed)
1. **Retention** - "yes raise it". -> D48 (365d, supersedes the 180 half of Q18).
2. **`submission_integrity_audit`** - "fix it as well". -> in scope, item F.
3. **`activity_events` vs `audit_events`** - "one model". -> D50.
4. **Reason on a plain form edit** - "leave ui alone". -> D52 (plumb the column, no prompt).
5. **Role** - "Okay" to workflow role, not RBAC. -> D51.

#### STILL OPEN - one clarification before implementation
**D50's "one model" is being implemented as one WRITE PATH and one STORE going forward,
with `activity_events` frozen read-only - not as a big-bang migration of existing rows and
not as a rewrite of the Activity Log UI.** If the intent is literally one table with the
existing rows migrated and `activity_events` dropped, say so before A-F start: it is a
different size of job. Everything else is decided.

**Nothing has been built. No code changed, no suite run. Analysis only.**

### H4-D - CLOSURE LEDGER (client section 9, 2026-08-27)

**Verdict: CLOSED ON THE MATRIX. Not "nothing open" - three items are named honestly
below, and one of them puts a WRONG VALUE on ACORD 125.**

#### The scorecard, MEASURED not asserted

Section 9.1 is 29 rows x 4 columns. Three of those columns are mechanically checkable, and
every number below was produced by driving the REAL code - `classify_question` +
`decorate_questions` (which runs the eligibility overlay) for routing, `TIER1_FIELDS` /
`TIER2_FIELDS` read out of `sqs_service` for the scoring home, and the owning door for each
key rule. Nothing here is read off a markdown file.

| Column | Result |
|---|---|
| **Default Question Routing** - who is asked | **29 / 29** |
| **V1 Scoring Home** - where it scores | **29 / 29** |
| **Key Rule** - the substance | **28 / 29**, one PARTIAL |
| **Desired Outcome** - the 8-stage pipeline | **8 / 8** stages have a shipped owner |

Zero routing mismatches. Zero scoring-home mismatches. The one partial is Physical Address
(see below).

**The Desired Outcome pipeline, stage by stage, with the door that owns it:**
Extract (`extraction_service`, v17) -> Normalize (`fact_comparison` / `fact_equivalence` /
`normalization`, D3's one comparator) -> Scope (`facts["_scoped"]`, D19) -> Reconcile (the
Data Consistency picker, C1-C) -> Determine Applicability (`question_eligibility` +
`fact_state`'s two axes, C4) -> Remediate (questionnaire + resolution cards, C2 / C4) ->
Score in the Correct Home (C3 3.5 / 3.14 moved payroll, claims and the WC fields out of
Structural; H4 removed the last prior-carrier display row) -> Preserve Source
(`fact_lineage` + `audit_events`, C5).

#### What H4 actually changed, and what was already delivered

**Only 8 of the 29 rows were broken.** The other 21 were already correct from C1-C5, H1, H2
and H3, and were VERIFIED here rather than rebuilt - which is the point of running the
matrix as a test instead of re-implementing the section.

| Row | What was wrong before H4 |
|---|---|
| Proposed Effective Date | expiration date, GL form basis, audit period and billing plan all asked the CLIENT |
| Entity Type | five live false Data Consistency conflicts (including ACORD's own checkbox wording against "LLC"), a validator refusing 8 of our own 13 dropdown options, and a stamper ticking the WRONG box for "S Corporation" / "Non-Profit Corporation" and NOTHING for "Sole Proprietorship" |
| Contact Name/Phone/Email | all three asked as CRITICAL and pre-ticked while Tier 1 already counted them as one satisfied requirement |
| FEIN | a client's "N/A" DESTROYED before it could become an answer (F15) |
| Prior Carrier | never reached the client at all; "None" destroyed by the same door |
| Years in Business | a producer-confirmed new venture still charged 1/6 of Tier 2 for history it cannot have |
| WC Payroll Period | the producer asked about the period of a figure that was already annual, or did not exist |
| Physical Address | investigated; deliberately NOT changed - see the partial |

Plus one cross-cutting fix that touches EVERY client-answerable row (the `answer_semantics`
door in `_clean_answer_ex`), and `new_venture_indicator` being asked of the client, found on
the owner's own run.

#### THE ONE PARTIAL

**Physical Address - "Do not universally require".** Routing and scoring home are correct,
and it is properly out of Tier 1 and Tier 2. But `FORM_FIELD_INVENTORY["ACORD_125"]` still
lists it, so `calculate_sqs_from_facts` counts it as an owed field on every package,
including a single-location GL risk whose mailing address IS its premises.

Deliberately not changed, and the reasoning is worth keeping because the obvious fix is the
wrong one: suppressing the QUESTION would be a **D32 violation** - the package would keep
paying fill-rate for a blank that nobody, client or producer, can be asked for. The correct
fix is on the SCORING side and moves scores upward, so it is **Q31** and it is Brent's.

#### STILL OPEN - do not let these disappear

| # | Item | Can it move a score? | Worse than that? |
|---|---|---|---|
| 1 | **Q33 - a declarations page's EXPIRING term stamps into ACORD 125's PROPOSED EFFECTIVE DATE box.** `_DOC_TYPE_PRIORITY` ranks `dec_page` above `application`, so on the commonest upload shape the merge hands `effective_date` the term that is ENDING | No | **YES - a wrong value on a legal document.** The cross-document date hard stop is currently the only thing on any screen pointing at that box, which is exactly why H4-C did not silence it |
| 2 | **Q31 - physical address charged universally in the ACORD 125 fill rate** | Yes, UP on single-location non-property accounts | No |
| 3 | **Q32 - the WC payroll breakdown and the X-Mod are each asked twice** (confirmed live on the owner's run) | Yes, DOWN ~5 Narrative Quality points if the duplicate is dropped without re-crediting from the H3 table | No |
| 4 | **Live proof missing for the headline fix** - a client answering "None" / "N/A" and it surviving the round trip (kit check 5), and the whole New Venture flow (checks 7-10). Neither is provable offline | - | - |

#### Standing lessons this arc produced, in the order they were learned

1. **An offline probe proves the FUNCTION, never the SEAM (now D54).** I shipped the WC payroll-period
   rule with a probe that passed `_flags` inside the facts dict - a test-harness shape.
   Production never carries it, so the rule marked the fact Not Applicable on EVERY package
   while the -3 was still charged: a deduction with no route to remediation. Two independent
   reviewers caught it within minutes of each other. The repo had already written this lesson
   down once; I re-learned it anyway.
2. **A guard rail is not optional in a test kit.** P3 (states everything, must stay silent)
   is the reason this can be called closed. A rule that fires on the ordinary case is this
   codebase's single most repeated failure - five times now.
3. **A fixture can disarm itself OBLIQUELY.** P1 stated the payroll basis in a *General
   Liability* rating column and silently satisfied a *Workers Comp* period check. Every
   word-level ban passed. A necessary-but-not-sufficient guard needs a STRUCTURAL second
   condition - the same lesson H1-F recorded, one layer further out.
4. **Answering "did the client ask for this?" is a research task, not a judgement call.**
   Both of the owner's removal requests turned out to be client-specified in the spec's own
   words. The five minutes spent extracting `SQS_Scoring_Specification` section 4 and section
   3.1 prevented deleting a named hard stop and the traceability C3 was built to deliver.
5. **Fix the GUARD, not the TABLE (now D53).** The proposed dec-page role-blindness fixed the reported
   case and was refuted three ways - it silenced real conflicts, destroyed the `_scoped`
   verdict that already resolves genuine multi-policy packages, and would have made
   `_ROLE_BLIND_FACTS` assert something false about the most authoritative document in the
   package. The mechanism was already there and correct; only its predicate was too narrow.
6. **Do not silence an alarm before checking what it is pointing at.** The policy-date hard
   stop fires for the wrong reason AND is the only surface flagging a genuinely wrong value.
   Removing it first would have shipped that value in silence.

#### Verification

**Suite: 4824 passed / 1 failed / 14 skipped** (`py -m pytest -q -p no:randomly`), against a
measured baseline of **4777 / 1** before this arc. The one failure is
`test_arq_acord125_missing_only`, the documented `httpx` ImportError. **+47 tests, zero
regressions.** Frontend production build clean. New standing gate:
`tests/test_h4_core_fact_matrix.py` (47) turns 9.1 into a contract that fails the build on
drift.

**CORRECTION TO CLAUDE.md, verified at HEAD:** its standing note that `test_normalization`
is one of two known pre-existing failures is **STALE** - the file is green (28 passed). The
only pre-existing failure is `test_arq_acord125_missing_only`. Anyone using the old note as
cover for a red `test_normalization` would be waving through a real regression.

#### Blast radius - D6, tell Brent BOTH directions

Full table in H4-A. Net: **UP** for a client answering "None" / "N/A" (credit instead of a
discarded answer), for the no-prior-losses attestation finally setting its flag, for
confirmed new ventures, for submissions previously refused with a 422, and for entity-type
false conflicts no longer raising review items. **DOWN** in exactly one place, correctly:
"N/A" typed into a required identity field no longer buys a Tier 1 credit.
**Presentation only, no score:** the Prior Carrier row left the Narrative Quality panel, and
the Tier 1 / Tier 2 sub-rows are hidden in the UI (owner's call - the scorer, the blend and
`score_trace` are untouched, and the same content still reaches the producer as the pre-form
"Key details in place / missing").

### H7-B - SHIPPED (2026-08-27)

**Baseline before any H7 work, measured in this tree: 4824 passed / 1 failed / 14
skipped** (the documented `httpx`/`openai` ImportError in
`test_arq_acord125_missing_only`). **After: 4882 passed / 1 failed / 14 skipped** -
the same single known failure, +58 tests, zero regressions. Frontend production
build clean (pre-existing chunk-size warning only).

#### What shipped, by clause

**A. One envelope.** New `services/audit_history.py` - the pure, DB-free half of
the spine: the event vocabulary, `derive_role`, `change_kind`,
`build_change_envelope`, `normalize_event`, `actor_ids_in`. Every event now
carries the client's seven attributes in FIXED positions
(`fact_key` / `field_name` / `previous_value` / `new_value` / `actor_id` /
`role` / `reason` + `action`), with `detail` the only free-form part - which is
where they hid before.

**B. One writer, emitted from INSIDE the eight existing audit writers**
(`audit_service.record_material_change`). `log_field_change`,
`mark_recommendation_dismissed`, `mark_recommendation_answer_recorded`,
`set_issue_status`, `log_underwriting_confirmation`, `log_integrity_resolution`,
`log_document_reclassified`, `log_download_with_open_recs` - plus
`arq_service`'s `client_answers_applied`, which moved off raw `log_audit_event`
so the summary carries the same seven attributes as everything else. A route can
forget; a writer the act must already pass cannot (D49, same one-door idiom as
`fact_comparison` D3 and `coverage_evidence` H1).

**C. The three data holes.**
- *Actor*: `resolve_actors()` - ONE query over the DISTINCT ids per export, not
  one per row; every section of the record now prints the person AND the role.
  Two readers gained `user_id` in their SELECT (`get_field_change_log`,
  `get_download_audit_log`) and two more were added
  (`get_dismissed_recommendations`, `get_issue_statuses`).
- *Role*: derived, no `users` column (D51).
- *Generated-value override*: `field_source_audit.previous_source` +
  `form_routes._prior_provenance`, which prefers the FACT envelope (it STATES
  provenance) over the form-highlight label (it only implies it).

**D. One chronological history.** Export gains `history`; the record gains
"COMPLETE HISTORY (chronological)". The old EVENT LOG section was REMOVED - it
rendered the same rows with less on each, and keeping two views of one history
inside the fix for "two views of one history" would have been absurd. Its bespoke
per-type wording was carried across into `_historyDetail`.

**E. One model (D50).** `activity_service` is now an adapter: it writes
`audit_events` with `visibility='product'` and reads a UNION of the spine and the
frozen legacy `activity_events` rows, so no producer loses feed history. The nine
event-type STRINGS, `record_event`'s signature and the read shape the UI consumes
are all unchanged, so `ActivityLogModal` needed no edit and cannot regress.
`audit_events` gains `package_label` + `visibility` + a `(user_id, created_at)`
index, all additive on both the CREATE and ALTER paths.

**F. `submission_integrity_audit` gets its first reader** (`get_integrity_audit_log`)
and a "PRODUCER OVERRIDES" section. `integrity_assessed` is excluded - that is
the system's own verdict, not a human act, and the resolution row already carries
the verdict it acted on.

**D48. Retention 180 -> 365**, floored, matching the operational tables.

#### Two defects found while building, both mine, both pinned

1. **`change_kind` consulted `previous_source` BEFORE asking whether there was a
   previous value at all.** Filling a BLANK required box whose highlight label
   happens to be AI-ish would have recorded *"the producer overrode an
   AI-generated value"* against a box the AI never filled - a false statement
   about a human, in an E&O record. Order is now: retraction -> fill -> override
   -> correction, pinned by
   `test_a_field_that_was_empty_can_never_have_been_overridden`.
2. **The first version keyed AI provenance off the wrong vocabulary.** There are
   TWO: the FACT envelope's (`ai_high` / `ai_low`, pinned by
   `field_source_audit.confidence`'s CHECK) and the FORM HIGHLIGHT's
   (`low_confidence` / `ai_verified` / `filled` / `missing_required`, written by
   `pdf_service`). `update_pdf` holds the second. `_AI_SOURCES` now knows both
   rather than asking call sites to translate - translating at the call sites is
   how the two drifted apart. **Also found: `_load_fieldmap` is a stub returning
   an empty fieldmap and an empty ai_set, so `update_pdf`'s `ai_set` membership
   test is dead code** - it was the obvious provenance signal and it is always
   empty.

#### Verification (executed, not reasoned)
- Suite 4882/1/14 as above; `test_h7_audit_history.py` (58) +
  `test_audit_lineage_20260826.py` (33, two updated for D48 + the constant move).
- **INSERT column-count vs placeholder-count checked on all 16 statements** in
  the two files touched - zero mismatches.
- **End-to-end offline seam run** against a fake pool: all eight material acts
  written, all eight read back through `get_audit_trail_export`, every one naming
  a human, and the client answer correctly reading **role=Client** despite being
  applied under the producer's user id.
- **Failure isolation proven in BOTH directions**: with the whole DB down every
  writer returns its failure value and nothing claims success; with only the
  SPINE failing, the act still returns success and the underlying row still
  lands - a lost history row never undoes a completed action, and it logs with a
  traceback (D35).
- Frontend production build re-run AFTER the final JSX edit (the first run
  predated it).

#### Blast radius - D6, tell Brent
1. **Volume**: every field edit now writes 2 rows (index + event) instead of 1.
2. **Product history now expires at 365 days** (D48). It never expired before,
   because `activity_events` was never swept. Deliberate.
3. **`activity_service`'s "no fresh PII" docstring rule is retired** - it
   described the old table. The spine already carried `client_email` on
   `client_answers_applied` before this change. Call sites still pass first names
   only; the reasoning that the table needs no encryption no longer holds.
4. No score moves. Nothing in this change touches scoring, gating, dismiss-credit
   or reopen - `sqs_recommendation_audit` and `submission_issue_status` keep
   their upsert semantics exactly (pinned by
   `test_the_mutable_workflow_tables_were_not_turned_into_history`).

#### Known / deliberately not done
- **The `fieldqa_` / `fieldmap_` DELETE+reinsert is untouched.** It still clears
  those rows on every producer field edit, but the dismissal is now an immutable
  spine event, so the history survives and C5-A's stale-findings concern is
  respected. Measured again this session: those rows carry `score_impact: None`,
  so `dismiss_earned_credit` is always False - **no score has ever moved on this
  path.** Audit loss only, and now closed.
- **`recommendation_reopened` / `issue_reopened` / `documents_uploaded` still
  write raw `log_audit_event` payloads**, not envelopes. They already carry the
  prior state C5-A added and `normalize_event` gives them actor + role from the
  row, so converting them would add risk without adding information.
- **One act can produce two events** (answering a recommendation emits
  `recommendation_answered` AND `field_changed`). That is two true statements
  about one click, in ONE store with ONE shape, adjacent in time - not the
  two-disconnected-stores duplication section 12 is about.
- **Not live-verified.** Everything above is suite + offline seam + build. The
  owner's next upload is the real check, and C5's own standing lesson applies:
  an offline probe proves the FUNCTION, never the SEAM around it - the fake-pool
  run is closer than a unit test but it is still not the running app.
- **The override classification UNDER-claims on some boxes, by design, and it
  was measured.** `change_kind` can only say "the producer overrode an
  AI-generated value" when the edited PDF box resolves (via
  `_ACORD_FIELD_RULES`) to a canonical fact that EXISTS in the store - that
  envelope is what states the model produced it. Driving the real stamper over
  ACORD 125: **8 of 13 populated boxes qualify.** The clearest miss is
  `BusinessInformation_FullTimeEmployeeCount_A`, which is alias-stamped from
  `num_employees` while the field rules map the BOX to `num_employees_full_time`
  - **a key nothing writes** (the phantom-key class H1-C catalogued; NOT chased
  here, it is a pre-existing field-rules defect, not an H7 one). Those edits
  record `corrected an existing entry` instead. That is the safe direction: it
  can miss a real override, it can never invent one, and an invented override is
  a false statement about a human in an E&O record. The h7 kit tests BOTH
  outcomes deliberately so the limit is visible rather than buried.

### H7-C - LIVE TEST KIT (2026-08-27)

`py backend/scripts/make_h7_test_pdfs.py` -> `h7_test_data/` (3 PDFs +
README-HOW-TO-TEST.md, 19 numbered checks mapped to the client's clauses).

Small on purpose: section 12 is about HISTORY, and history is made by ACTIONS,
so the click sequence is the test and the documents only have to make each of
the eight events REACHABLE. Two events need no document at all
(`document_reclassified` - the control is on every session, not just flagged
ones; `package_downloaded` - any download with an open item).

- **S1** (H7A package + H7B certificate): reclassify -> resolve the umbrella
  conflict -> generate 125 + 131 -> override an AI value -> the contrast edit ->
  answer a rec -> reopen and answer DIFFERENTLY -> dismiss with a reason ->
  resolve an issue with NO reason -> client questionnaire -> download with open
  items -> read the record. Covers all eight events plus the Activity Log checks.
- **S2** (H7A + H7C, a DIFFERENT insured): the multi-insured review, overridden
  with "Continue anyway" - the `overridden=True` half of `producer_override`,
  which is the half that sat in a table with no reader until H7. Kept in its own
  scenario so a foreign entity never contaminates S1's facts.

**Dry-run against the REAL code before shipping the kit** (not reasoned - each
one drove the production function): `assess_submission_integrity` returns
`high / review_required=False` on S1 and `low / review_required=True` on S2 with
both entities named; `values_agree("umbrella_limit", $3M, $1M)` is False and
`umbrella_limit` is a curated `currency` reconcilable, so the picker will appear;
and the stamper run above chose the override target by measurement.

**`_verify()` caught a real fixture defect and was itself wrong once.** Its first
version failed because H7A's umbrella page also prints `$1,000,000` - as the
UNDERLYING GL limit, which is what a real umbrella declarations page looks like.
Sanitising that away would have been building the convenient fixture D22 warns
about, so the CHECK was fixed instead: what matters is that the CERTIFICATE must
not print the policy's limit (that direction would make the documents agree and
no conflict would be raised at all).

### H7-D - FIRST LIVE RUN (S1): the record PASSES, and 5 defects it exposed (2026-08-27)

**The owner ran S1 on the live system and supplied the record.** Every H7
headline behaviour is confirmed on real data:

- `COMPLETE HISTORY (chronological)` present; the old `EVENT LOG` gone.
- **Every row names a human** - `vinay sharma <vinaysharma@astreait.com>
  (Producer)` - across all 18 rows and all six older sections. Not one
  `By: unknown`. Before H7 the record named nobody, anywhere.
- **Both generated-value overrides labelled correctly**: the ACORD 125
  operations description and the ACORD 131 umbrella SIR each carry
  `Change: overrode an AI-generated value`, and `MODIFICATION HISTORY` prints
  `How: Entered/edited by producer (previous value: AI extraction (high
  confidence))`.
- **The answer -> reopen -> different answer sequence is fully preserved**:
  three `Recommendation answered` events with their distinct values, the
  retraction to blank, and the `Recommendation reopened` carrying
  `prior action: resolved at ... (answer retracted)`. The upsert used to keep
  only the last answer.
- Conflict resolution, download-with-open-items + reason, and the SQS snapshots
  all present. **Activity Log clean** - nine product events only, no field
  edits, older packages intact (D50 verified live).

**Not exercised this run:** `PRODUCER OVERRIDES` is `(none)` - the owner did not
reclassify a document, and could not reach the hard-stop / warning rail after
generation (see OPEN below). `issue_status_changed` therefore still has no live
proof; S2 was not run.

#### The five defects, three of them mine

1. **THE OWNER'S REPORTED BUG - "reopened, submitted a different answer, not
   getting saved".** It WAS saved: the fact, the envelope and the audit row were
   all correct on his own record. **The card lied.**
   `_NEW_VENTURE_CONFIRM_REC` was appended by `calculate_p4_loss_history`
   whenever loss history was absent, with no reference to whether it had been
   answered. Answering **Yes** makes the pillar Not Applicable, so the rec stops
   being generated and the card closes; answering **No** - the honest answer on
   most accounts - changes nothing that function reads, so the rec came back
   identical, the auto-resolve pass had nothing to stamp, and the card
   reappeared Open with an empty dropdown. He answered it three times.
   **The class: a confirm-X prompt only ONE of whose two answers can retire
   it.** New door `loss_history_state.new_venture_answered` (deliberately
   separate from `new_venture_confirmed` - C2-G's "what is the value" vs "did
   they answer" split) gates `_new_venture_prompt`. The genuine gap
   ("No loss history provided") keeps its own rec and correctly stays open.
   A blank still counts as unanswered (Principle 3).

2. **A no-op recorded as a modification (mine).** Submitting the same answer
   twice produced `"No ..." -> "No ..."  /  Change: corrected an existing
   entry` - an E&O record stating the producer altered something they did not.
   `update_pdf` has always skipped unchanged fields; the producer-answer and
   resolve-issue paths never did. Guarded in `log_field_change` itself so a
   future writer inherits it, with `record_unchanged=True` as the documented
   exception for the two SCHEDULE paths, whose before/after is a ROW COUNT
   (editing a VIN in row 2 of three leaves "3 row(s)" -> "3 row(s)" while
   genuinely changing the data).

3. **`"$3,000,000" -> "$3,000,000"` on the conflict resolution (mine).** C5-D
   fix 7 killed exactly this in the resolutions section - under D16 the
   suggested value stamps BEFORE confirmation, so confirming the suggestion
   leaves previous == chosen. The new history section reintroduced it one layer
   up. Suppressed when unchanged, same rule as C5-D.

4. **`Reason: No reason provided` printed as a reason (mine).** That string is
   the UI's SENTINEL for an unexplained dismissal - `dismiss_earned_credit`
   already treats it as no reason. Now one named `_NO_REASON_SENTINELS`, shared
   by the credit predicate and the record so the score and the E&O record
   cannot disagree about what counts as a reason.

5. **A machine `null` was a competing VALUE - two FALSE HARD STOPS.** The
   pre-form screen reported *"Policy Effective Date: documents disagree
   (09/17/2026, null)"* and the same for the expiration, **capping a perfectly
   consistent two-document package at 60**. Root cause:
   `_normalize("null", "date")` returned the truthy string `'null'`, so it
   passed every `if not norm: continue` guard and became a rival candidate.
   **The module already knew the rule** - its own scalar reader (`_fv`, line
   ~701) drops `""` / `"null"` / `"none"` - it was simply never applied on the
   paths that BUILD candidate groups (per-coverage-line and text scan). One
   rule, two copies, only one of them running: the same shape as C1's five
   comparison sites and H1-C's phantom keys. Fixed in `_normalize`, narrowly:
   only the MACHINE's own spellings of "no value found". A human typing "None"
   is an ANSWER with no value and is handled by `answer_semantics` on a
   different path (C2-G); this function only ever sees document-extracted
   candidates. Verified both directions - `Nonesuch Holdings LLC` and
   `Nonprofit Alliance Inc` survive.
   **SCORES MOVE UP on any package where an extractor emitted a bare "null" -
   D6, tell Brent.** This is a correction, and it removes hard stops.

#### Also shipped this session - TWO UI elements hidden, neither a client ask
**The "Quality Fill Rate: N% -> N%" delta line** and **the whole "Session delta"
card** ("+N pts this session" / "Started at X -> now Y") are hidden, via
`SHOW_FILL_RATE_DELTA` and `SHOW_SESSION_SCORE_DELTA` next to the existing
`SHOW_COMPLETION_METRICS`. Markup intact on both, backends untouched.

**The owner asked the right question - "did the client ask for this, or are we
showing it?" - and the answer was checked against the SOURCES, not our notes.**
`SQS_Scoring_Specification.docx.pdf` (24,688 chars) has ZERO hits for
"this session", "delta", "started at", "progress" or "before and after"; its
only two "improvement" hits are 3.11's credit-stacking rule. Client section 7 IS
the score-presentation section and asks for exactly three things - a qualitative
status label, remediation progress shown SEPARATELY, and the numeric SQS kept in
the dedicated results experience. A session delta is none of them.

It was our own panel, and it had been **structurally dead since it shipped** -
`sqs_history` was never persisted, so `delta_this_session` was permanently 0 and
the card never rendered. C5-A's fix to `sqs_history` is the only reason it became
visible, which is why it surfaced on the very first H7 live run.

**The backends stay.** `delta_this_session` / `sqs_history` feed the 5.12 audit
snapshots and the SQS narrative's model context (where the prompt already forbids
restating any number - the 2026-08-12 fix), and `fill_rate_before` /
`fill_rate_after` still carry the section 6.2 remediation delta. Deleting either
would break the E&O record to hide a line.

**Standing lesson:** a feature nobody asked for can hide indefinitely behind a
bug, then arrive looking like a regression the moment the bug is fixed. Two of
the three hidden panels here were found that way.

#### OPEN, from the run itself
**The hard-stop / warning rail is unreachable after generation.** The owner
could not resolve or dismiss a pre-form issue once forms existed, so
`issue_status_changed` has no live proof and defect 5's two false hard stops
could not be cleared from the UI at all. The SQS panel's Cross-Form Validation
section does carry Resolve / Dismiss, which writes the same event - that is the
post-generation route to test it. Whether the full pre-form rail should be
reachable later is a product question, not an H7 one.

#### Observed, NOT fixed, none of them H7
- `is_renewal` holds a whole sentence ("This declarations page is issued in
  connection with the policy identified above and supersedes any prior issue.")
  instead of a boolean - an extraction defect.
- `property_locations` still prints `Source: unspecified` while every other
  structured fact carries contribution evidence - one straggler from C5-D fix 3.
- `DOWNLOADS` prints `Score at download: 60` while `SCORE HISTORY` records 53 at
  the same instant. 60 is the FORM score (ACORD 131) and 53 the package score,
  so both are true; the label does not say which. Cosmetic, worth a word.

- suite: **4889 passed / 1 failed / 14 skipped** - the same single known
  `httpx` ImportError, +7 tests, zero regressions. Frontend build clean.

### H7-E - ROUND 2 LIVE: the last three events confirmed; SECTION 12 CLOSED (2026-08-27)

**Owner-confirmed on the running app**, closing the three events H7-D's first
run left unproven:

1. **Pre-form -> reclassify a document's type -> `producer_override`.**
   `submission_integrity_audit` had three writers and NO reader anywhere before
   H7 - the same defect C5-A fixed for `underwriting_confirmation_audit`,
   recurring one table over. It now has a reader (`get_integrity_audit_log`) and
   its own PRODUCER OVERRIDES section, and the before -> after document type,
   the timestamp and the actor all render.
2. **SQS panel -> Cross-Form Validation -> Resolve the ACORD 25 item ->
   `issue_status_changed`.** This is the event the old export could not show at
   all: it printed issue rows only when they happened to carry a `reason`, so a
   plain Resolve was invisible, and `submission_issue_status` is a latest-wins
   UPSERT that keeps no history of the transition.
3. **Send to Client -> answer -> submit -> `client_answers_applied` +
   per-fact `field_changed` rows reading role = CLIENT.** The subtlest
   correctness property in the whole change: the questionnaire is applied under
   the SESSION OWNER's user id because the client has no account, so deciding
   role on "is there a user_id" would file every client answer as a producer
   action. `derive_role` checks `source` FIRST, and that ordering is what the
   live run confirms (D51).

**Note on scope, stated precisely:** the `producer_override` CLAUSE is verified
via document reclassification. The SECOND writer of that same event type - the
`overridden=True` multi-insured integrity override, scenario S2 in the h7 kit -
has still not been run live. The event type, the reader and the rendering are
proven; that one writer is not.

#### SECTION 12 CLOSURE LEDGER - the client's own structure

| Client's words | State |
|---|---|
| *"cannot be reliable if the product does not consistently capture meaningful state changes"* | **Closed.** 1 of 8 events reached an append-only store before H7; all 8 do now, emitted from INSIDE the writer each act must pass (D49), so a call site cannot forget |
| *"should not become a separate reporting subsystem disconnected from the actual workflow"* | **Closed.** The record is no longer assembled by the exporter from mutable current state. Two near-identical event logs became one (D50) |
| **one model -> product history** | **Closed, live.** `activity_service` is an adapter over the spine; the navbar feed renders from it, clean, with older packages intact |
| **one model -> debugging** | **Closed.** One store, one envelope, one write path; every history write logs its own failure with a traceback (D35) |
| **one model -> source lineage** | **Met by DESIGN DECISION, not by construction - say this to Brent plainly.** The RECORD is unified, but lineage stays COMPUTED at export (D36) rather than evented. That was measured, not assumed: asking the model for page numbers cost ~593k output tokens and +18-20 min and was switched off 2026-08-23. The spine carries provenance-of-CHANGE; `fact_lineage` carries provenance-of-ORIGIN |
| **one model -> E&O Audit Record** | **Closed, live.** `COMPLETE HISTORY (chronological)` is built from the spine |
| affected fact/field | **Closed, live** |
| original value | **Closed, live** |
| new value | **Closed, live** |
| actor | **Closed, live.** Zero `By: unknown` across every row and every section. Before H7 the record named no human in any of its 12 sections |
| role | **Closed, live**, both directions - Producer on edits, **Client** on questionnaire answers |
| timestamp | **Closed, live** |
| reason / action when relevant | **Closed, live.** Action on every event; reason wherever one was given, and the "No reason provided" SENTINEL is no longer printed as though it were one |
| producer edit | **Closed, live** (H7-D) |
| client answer | **Closed, live** (H7-E) |
| producer override | **Closed, live** (H7-E, via reclassification; S2's integrity writer untested) |
| conflict resolution | **Closed, live** (H7-D) |
| issue resolution | **Closed, live** (H7-E) |
| recommendation dismissal | **Closed, live** (H7-D) |
| form edit | **Closed, live** (H7-D) |
| generated-value override | **Closed, live** (H7-D), with the measured under-claim in H7-B's known list |
| *"generated from real system history rather than reconstructed later from incomplete current state"* | **Closed.** Every row was written by the workflow at the moment the act happened |

**VERDICT: client section 12 is DELIVERED.** All eight events, all seven
attributes and the Desired Outcome are verified on the running app across two
rounds. One clause - source lineage inside the one model - is met by a recorded
design decision rather than by construction, and Brent should hear that in those
words rather than discover it.

#### D6 - what to tell Brent, in priority order
1. **Scores move UP** wherever an extractor emitted a bare `"null"`: that string
   was competing as a VALUE and manufacturing false date conflicts. On the H7
   fixture alone it produced TWO hard stops capping a clean two-document package
   at 60 (H7-D defect 5). This is a correction and it removes hard stops.
2. **Scores can move** on the new-venture path: the confirm card now retires on
   either answer, so packages stop carrying an unretirable recommendation.
3. **Three UI panels are hidden**, none of them a client ask - Form Completion /
   Quality Fill Rate, the fill-rate delta, and the session score delta. Backends
   all intact.
4. Every field edit now writes two rows (index + event); product history now
   expires at 365 days, where `activity_events` never expired.

#### STILL OPEN after section 12 - do not let these disappear
- **S2 (the multi-insured integrity override) has never been run live.** Three
  clicks: upload `H7A` + `H7C`, Continue anyway, generate ACORD 125, read the
  record. The kit is built and self-verified.
- **The pre-form hard-stop / warning rail is unreachable after generation.** The
  owner could not clear the two false hard stops from the UI at all on round 1.
  Cross-Form Validation is the post-generation route for the issue rail; whether
  the full pre-form rail should be reachable later is a product question.
- **`is_renewal` holds a whole sentence** ("This declarations page is issued in
  connection with the policy identified above and supersedes any prior issue.")
  instead of a boolean - an extraction defect, not section 12.
- **`property_locations` still prints `Source: unspecified`** while every other
  structured fact carries contribution evidence - one straggler from C5-D fix 3.
- **The generated-value override UNDER-CLAIMS on some boxes** - measured, 8 of 13
  populated ACORD 125 fields qualify. Safe direction (never invents an
  override), root cause is a phantom canonical key in `_ACORD_FIELD_RULES`
  (H1-C's class), deliberately not chased here.

#### Standing lessons this arc produced
1. **A feature nobody asked for can hide behind a bug, then arrive looking like a
   regression the moment the bug is fixed.** Two of the three panels hidden this
   session were invisible only because `sqs_history` was dead. When something new
   appears on screen, ask who asked for it - the owner did, and the answer was no.
2. **The record can be right while the CARD lies.** The owner's "not getting
   saved" bug had a correct fact, a correct envelope and a correct audit row; the
   only broken thing was a recommendation that could not be retired by one of its
   two answers. Check what the user SEES, not only what was stored.
3. **One rule in two copies means one of them is dormant.** `"null"` was dropped
   by the scalar reader and honoured as a value by the candidate builder, in the
   same file. Same shape as C1's five comparison sites and H1-C's phantom keys.

**The two standing rules this arc produced are D55 and D56** in the decision
register (a machine non-value is never a candidate; a confirm-X prompt retires on
either answer). Both were live defects, not theory.

#### Files and tests
- new: `services/audit_history.py`, `tests/test_h7_audit_history.py` (65),
  `backend/scripts/make_h7_test_pdfs.py` -> `h7_test_data/` (3 PDFs + a
  19-check README).
- changed: `services/audit_service.py`, `services/activity_service.py`,
  `services/arq_service.py`, `services/loss_history_state.py`,
  `services/sqs_service.py`, `services/scheduler_service.py`,
  `services/underwriting_consistency.py`, `models/schemas.py`,
  `routes/form_routes.py`, `routes/audit_routes.py`, `routes/arq_routes.py`,
  `frontend/src/components/form/AcordModal.jsx`,
  `tests/test_audit_lineage_20260826.py` (2 updated for D48).
- suite: **4890 passed / 1 failed / 14 skipped** - the same single documented
  `httpx`/`openai` ImportError, zero regressions. Frontend production build
  clean (pre-existing chunk-size warning only).

---

## Session 2026-08-28 - V1 BETA EXIT CRITERIA: verified against the code, 7 defects fixed

### BE-A - The verification, and what it found (2026-08-28)

**The client issued a beta-exit checklist - 49 criteria across Data Integrity,
Data Consistency, Loss History, SQS, Questionnaire, Coverage-Specific and
Provenance / Audit. Every one was checked against the CODE, never against this
file.** That distinction is the whole point: this log has recorded, repeatedly,
work that was "done" and unreachable in practice - a result key one level too
high (`_harvest_dec_index`), a question hidden by a machine prefix (D46), a
fallback preserving the defect it was meant to fix (H1-H), a hard stop reading
keys nothing writes (H1-C). A change-log entry is not evidence.

**Method.** Full suite; frontend production build; the 809 pinning tests across
the sections under review re-run individually; then ~20 probes driving the REAL
modules - `calculate_package_sqs`, `calculate_p4_loss_history`, `overlay_for`,
`coverage_evidence`, `fact_comparison`, `run_cross_form_validation` - each with
the adversarial direction as well as the happy one.

**Result: 40 of 49 hold. 9 did not.** Seven were cleanly fixable and shipped in
this session (BE-B). Two are recorded below and NOT fixed, for stated reasons.

#### What the probes confirmed working (not assumed - measured)

| Area | Evidence |
|---|---|
| Address / name / FEIN equivalence | `E 9 Mile Rd` vs `East 9 Mile Road`, `Suite 100` / `Ste 100` / `#100`, `48201` vs `48201-1234`, `ABC Roofing LLC` vs `ABC Roofing, L.L.C.`, `12-3456789` vs `123456789` all agree; a genuinely different address still conflicts |
| "No Coverage" is not active | `denied_families` returns `workers_comp`; the row grants nothing |
| Auto owned vs HNOA-only | Exposure pillar **67** (owned, five items missing) vs **92** (HNOA-only) vs **92** (no auto line) - the client's 6.3 ask, working |
| X-Mod is never guessed | new venture -> `not_applicable`, mod present -> `satisfied`, nothing known -> `unknown`, and UNKNOWN never deducts |
| Loss History ladder | 83 cases through the real scorer, **0 mismatches** against Brent's ruled table; every number in the 100/85/70 structure found in code |
| Ceilings never floor | raw 45 + hard stop = **45**; raw 50 + warning = **50**; hard + soft = 60, not 45 |
| Issue-status clicks | resolve / dismiss / reopen / Download Anyway touch no scorer and no `package_sqs` |
| NAICS / SIC | producer-routed through the real door |

### BE-B - The seven fixes (2026-08-28)

Each carries the client's own criterion, the measured defect, and - where the
defect is a CLASS rather than one line - a structural guard so the next
instance fails the build. Tests: `tests/test_v1_beta_exit_20260828.py` (25) plus
2 in `tests/test_question_eligibility.py`.

**1. "GL/WC class codes never reach the client" was FALSE on one fact.**
`gl_class_code_schedule` survived `question_eligibility.overlay_for` as
`audience=client`, asking the insured verbatim to *"Provide the GL rating
schedule per class code (class code, premium/exposure basis, exposure amount
i.e. payroll or gross sales, territory, and subcontracted %)"* - five insurance
classifications in one box, a direct breach of core principle 5.
It escaped every guard for a reason worth keeping: it is **not** in
`SCHEDULE_DEFS`, so D44's table-level audience split never applied (that rule
protects `wc_class_codes` by stripping its producer-only `code` column, and
there is no table here to strip), and its key ends `_schedule` rather than the
`_codes` its siblings share. **A hand-maintained list of 50 keys cannot guard
itself**, so `test_no_classification_question_ever_reaches_the_client` now
DERIVES the check from every registry question's own TEXT. Matched on the ASK,
not the key name - deliberately, because `narrative_target_markets` and
`narrative_growth_trends` are both real X-Mod / class-code questions wearing
narrative keys (C4-S, H3-D) and a key-name rule is what let those through.
No score moves; routing only.

**2. "WC-specific information no longer penalizes non-WC submissions" - one
cross-form rule was ungated.** `_check_acord186_subcontracting_vs_gl_wc` raised
a **HARD STOP** keyed on WC payroll with no WC gate at all. Measured: a GL-only
roofing contractor (`has_workers_comp` False, forms 125/126/186, 40%
subcontracted, no payroll) raised *"no Workers Comp payroll is provided. WC
payroll is required"* and the package fell **71 -> 60**. The remediation asks
for `wc_payroll`, so the producer could only clear it by inventing a WC figure.
Gated in the shape its five siblings already use, and slightly broader - the
flag alone is enough, so a WC package that did not select ACORD 130 keeps the
check. **Strictly narrower than the behaviour it replaces: it can only remove a
false stop, never add one.** The subcontractor exposure is a real GL concern and
is not lost, only no longer stated as a missing WC figure; a GL-side rule for it
would be a NEW validation rule and belongs to Brent (Principle 7).
**SCORES GO UP on GL-only contractor packages carrying ACORD 186 - D6.**

*The structural guard was vacuous on its first draft and that is worth
recording:* every one of these rules also names `ACORD_130` in its issue's
`forms` list, so scanning the function body for the gate string found a "gate"
that gates nothing - the test passed over the UNFIXED rule. It now reads only
`ast.If` **test** expressions. Verified by removing the fix and watching all
three tests fail, then restoring.

**3. "Overrides preserve prior values" - a CLEAR was recorded but never
persisted.** `update_pdf` sets a cleared fact to `None`, and the facts merge is
deliberately ADDITIVE (`resolve_facts_write` skips None so an in-flight writer
can never blank another's value), so the clear was audited as *"removed a
value"* and silently dropped: the store kept the old value, the next
`recalculate_session_scores` scored it as present, and
`_restamp_canonical_into_forms` could put it back on the form. **The E&O record
and the fact store disagreed** - the mirror image of the C5-A envelope
destruction. **D18 already governs exactly this** ("never a bare pop") and was
not being followed. Now the cleared keys go through `delete_facts`.
Read off the FINAL state, never the loop: two ACORD fields can map to one fact,
and `delete_facts` is applied after the merge, so collecting a key at clear-time
would delete what the same request just wrote.

**4. "Downloads with unresolved issues preserve the open-item state" - a dismiss
was dead after any Download Anyway.** `log_download_with_open_recs` stamps
`action='downloaded_anyway'` on every unresolved row; the dismiss upsert's
`WHERE action IS NULL` therefore matched nothing on every later dismiss - while
the function still logged *"Marked rec dismissed"*, returned True and appended
`recommendation_dismissed` to the event spine. **DISMISSED ITEMS and COMPLETE
HISTORY then contradicted each other**, the item stayed "unresolved" on every
later download record, and `active_score_credits` (which reads
`action='dismissed'`) never re-applied the credit - so a typed-reason credit was
granted once and **silently reverted on the next rescore**.
`downloaded_anyway` is a MARKER that the producer shipped with the item open,
not a terminal resolution. Its two siblings on the same table -
`mark_recommendation_resolved` and `mark_recommendation_answer_recorded` -
already accepted it; **the dismiss writer was the odd one out, which is why
nobody noticed**. Genuinely terminal actions are still never overwritten, and a
test now pins all three writers to the same rule.

**5. "Material changes trigger full recalculation" - the schedule save did not
rescore.** `PUT /api/arq/schedules/{id}` wrote `facts[list_key]` and restamped
the forms but never scored, so a producer pre-loading `wc_class_codes`,
`auto_vin_schedule` or `auto_drivers` changed the very facts the H1 -10 / -15
rules and the 6.3 bucket read, and the score stayed stale until an unrelated
trigger rebuilt it. Every other human-write path recalculates - including the
resolve-issue schedule mode, which calls the same `save_session_schedule` and
then the same function. Non-fatal by design: the save has already succeeded and
been audited, so a scoring failure must not turn a persisted change into a 500.

**6. "Derived values retain derivation lineage" - lost on every override.**
`_prior_provenance` consulted `confidence` before `source`, and a derived fact
carries both, so overriding `years_in_business` or `wc_payroll_by_state`
recorded *"corrected an existing entry"* with the derived origin gone, and a
renewal-routed date (D28 / RC1b) was recorded as an AI override. `source` is the
axis that STATES how a value was produced (client 1.4's four evidence states);
confidence only grades an AI value's strength and describes nothing on a derived
fact. **Deliberately NOT added to `audit_history._AI_SOURCES`**: a derivation is
deterministic and document-grounded, so filing it as "overrode an AI-generated
value" would be a false statement about the producer in an E&O record - the same
class H7-B fixed when an empty field was called an override. It classifies as a
correction, and the record now names `derived` as what was corrected.

**7. "Contradictory no-loss evidence remains visible and appropriately capped" -
the client's own claims table was invisible to the guard.** Every consumer read
the scalars `num_claims` / `total_incurred`; nothing read the `loss_history`
TABLE (`SCHEDULE_DEFS["loss_history"]`: date, line, description, paid,
reserved). Nothing derives one from the other - extraction only counts claims
out of loss-run TEXT - so a claim the insured or the producer **typed** was
invisible. Measured on the real scorer:

```
attested "no prior losses" + one typed claim row  -> 60, no conflict, no rec
the same claim as num_claims=1                    -> 45 + conflict
```

**The more explicit the evidence, the less it counted.** The same blindness sat
in `prior_operations_evidence`, so a typed claim could not stop a New Venture
confirmation from making Loss History Not Applicable.
New ONE DOOR `loss_history_state.asserted_claims(facts) -> (claims, incurred)`,
read by both. Returns a **MAXIMUM, never a sum**: a loss run stating 3 claims
and a table listing those same 3 rows is one set of facts printed twice, and
adding them would manufacture 6 (the C23 / B1 lesson).
**The adversarial case was written first** and it is the one that matters: the
mirror of this bug is worse than the bug, because a half-typed or empty row
inventing a claim would cap a genuinely CLEAN submission at 45 and call the
insured's attestation a contradiction. A row counts only on positive content -
a real date, description, line or money figure. Verified: `[]`, `[{}]`, all-blank
rows, a non-dict row and a `$0` row all yield `(0, 0.0)` and score 60.
**SCORES GO DOWN where a typed claim contradicts an attestation - D6.**

### BE-C - NOT fixed, and why (2026-08-28)

**Neither is an oversight; both are recorded so they are not mistaken for one.**

**1. ~~"Equivalent coverage terminology" - bare `GL` / `WC` / `BAP`~~ - SUPERSEDED
the same day. The owner ruled 2026-08-28 and it is FIXED - see BE-F and D57.**
Left here as written, because the REASON it sat unfixed is the point: the change
is two minutes and **D9 blocked it** - *"Folding a phrase into an existing
family, or adding a family, needs product approval."* That is a permission
blocker, not a technical one, and engineering was right not to self-approve it:
when the fix was finally written, the naive version of it was measured to be
actively dangerous (BE-F).

**2. "Missing information does not become unsupported negative/default values"
is closed on the HUMAN path and open on EXTRACTION.** `answer_semantics` handles
every human answer correctly, but `merge_facts` writes `facts[key]` directly, so
an LLM-extracted literal `"N/A"` still counts as data - measured, `fein="N/A"`
scores **Tier 2 100**. This is CLAUDE.md's own **GAP 1**, still open at HEAD.
`services/placeholder_detector.is_placeholder_value` already exists and is used
by `field_qa` and `pdf_service` but is **never called by the merge**; wiring it
in is the right shape and touches every fact in the system, so it needs a
measured run against a real package before it ships. **Not a same-day fix, and
not to be done as a one-liner.**

**Also still open from earlier arcs, re-confirmed at HEAD by this pass:**
`_report_ungrounded_ai_values` is still shadow / report-only (F-1, invented GL
class codes); **O6** (the ACORD 140 mined-junk fill) is untouched; **O1**
(clause 4.6) has still never been exercised end to end; Q31 / Q32 / Q33 are with
Brent, and **Q33 is a wrong value on a generated ACORD 125**.

### BE-D - Verification (2026-08-28)

* Suite before: **4890 passed / 1 failed / 14 skipped**.
  After, attributable to this session: **4917 passed / 1 failed / 14 skipped**
  (+27: 25 in `test_v1_beta_exit_20260828.py`, 2 in `test_question_eligibility.py`).
  **Zero regressions.**
* **The whole tree currently measures 5038 passed / 1 failed / 14 skipped /
  1 xfailed**, because six untracked `tests/test_v1_regpack_*.py` files
  (121 tests + 1 xfail, describing themselves as the client's *"REQUIRED V1
  REGRESSION TEST PACK"*) appeared in `backend/tests/` during this session from
  work outside it. They all pass and NOTHING here touched them - recorded only
  so the next person reconciling the count knows where the extra 121 came from
  and does not attribute them to the beta-exit fixes.
* The single failure is `test_arq_acord125_missing_only`, and **its description
  in CLAUDE.md is now wrong.** In ISOLATION it dies on the documented
  `httpx`/`openai` ImportError (it self-stubs `httpx`). Inside the full suite,
  where real `httpx` is already imported, it gets further and fails on a STALE
  pre-C4 assertion instead - it expects `{"applicant_name"}` and receives the
  post-C4 question set. Dead either way, not a regression, but the "known
  `httpx` failure" line no longer describes what happens in a full run.
* Frontend production build clean. **No frontend file was touched** - none of
  these fixes needs a UI element, and none was added.
* Probes and their verbatim output are in the session scratchpad, not the repo.

### BE-E - Standing lessons from this pass

1. **A criterion is verified against the code or it is not verified.** Seven of
   the nine defects sat behind passing tests and a change log that said "done".
2. **A guard that scans a whole function body for a gate string finds mentions,
   not gates.** The first structural test here passed over the very rule it was
   written for. Always remove the fix and watch the guard fail (C25).
3. **Three writers on one table will disagree eventually.** `resolved` and
   `answer_recorded` learned that `downloaded_anyway` is not terminal; `dismiss`
   never did, and nothing compared them until now.
4. **When one fact has two spellings, the one a HUMAN types is the one that gets
   forgotten** - the machine's `num_claims` was read everywhere, the client's own
   claims table nowhere.

---

## Session 2026-08-28 - REQUIRED V1 REGRESSION TEST PACK (client's 18 scenarios)

### RP-A - BUILT AND GREEN, one confirmed gap (2026-08-28)

The client's "REQUIRED V1 REGRESSION TEST PACK" (18 numbered scenarios, to be
retained as recurring regression scenarios) is now executable. **121 tests, 120
passing, 1 strict xfail.** Six files, one per theme, all sharing the
`test_v1_regpack_` prefix so the whole pack runs as a unit:

```
py -m pytest -q -p no:randomly tests/ -k v1_regpack      ->  121 passed, 1 xfailed
```

| File | Client tests |
|------|--------------|
| `tests/test_v1_regpack_identity.py` | 1 (address equivalence), 3 (ACORD 25 multi-insurer), 4 (loss-run name) |
| `tests/test_v1_regpack_coverage_scope.py` | 2 (terminology), 11 (property-only), 12 (HNOA-only) |
| `tests/test_v1_regpack_loss_history.py` | 5 (new venture), 6 (Path C 50), 7 (attested 60), 8 (contradicted 45) |
| `tests/test_v1_regpack_classification.py` | 9 (NAICS/SIC), 10 (WC class code), 13 (owned auto, no schedule) |
| `tests/test_v1_regpack_provenance.py` | 14 (client answer conflict), 15 (producer override), 16 (derived date) |
| `tests/test_v1_regpack_audit_score.py` | 17 (download with open issues), 18 (SQS ceiling) |

**17 of the client's 18 scenarios PASS against current code.** Every number the
client quoted reproduces exactly on the real engines: Path C 50 / attested 60 /
contradiction cap 45 (`_LOSS_CONFLICT_CAP`), Auto Completeness -15, and all
three ceiling examples (88+warning->85, 88+hard->60, 42+hard->42, ceiling never
a floor).

### THE ONE GAP - client test 3, "insurer letters map correctly"

`tests/test_v1_regpack_identity.py::test_r03_insurer_letters_map_to_their_line`
is an **`xfail(strict=True)`**. It is **H5 "ACORD 25 Multi-Carrier Mapping",
which the ledger has always said is Not started** - measured, not assumed, on
the real ACORD 25 schema with a 3-carrier package:

* `_ACORD_FIELD_RULES` maps `Insurer_FullName` to the ONE package-level
  `carrier_name` scalar, so on three distinct carriers `Insurer_FullName_A` is
  filled and **B-F are blank**.
* every `*_InsurerLetterCode_*` has rule value `None` AND sits in
  `_RAW_TEXT_SKIP_PATTERNS`, so no coverage line can point at its own insurer
  row - deliberately never invented, but never mapped either.

**The rest of test 3 PASSES and is pinned as passing tests:** per-line policy
numbers stay on their own certificate rows (GL BBC7263 / Auto 6E7-40-02---26 /
Umbrella 6J7-40-02---26), a line the package does not carry stays **blank rather
than borrowed** (WC), and three carriers raise **no conflict** - `carrier_name`
comes back `status: "scoped"` through C1b's `_scoped` store. Remove the xfail
when H5 ships; `strict=True` means it fails the build the day it starts working,
so it cannot be forgotten.

### WHAT THE POSITIVE CONTROLS CAUGHT - the reason to keep them

Three of this pack's tests were passing **vacuously** on the first run and were
only caught because every negative assertion carries a positive control:

1. `match_loss_run_identity` reads `d["facts"]`, **not** `d["extracted"]["facts"]`.
   A fixture using the latter gives the matcher no name at all, so it returns
   `POSSIBLE` for **every** input - including a completely different company.
   Test 4 ("formatting alone does not reduce Loss History") would have passed
   because nothing was ever compared. The control
   (`test_r04_a_different_insured_is_still_caught`) failed and exposed it; with
   the real shape, `Summit Mechanical Services Inc` correctly returns `no_match`.
2. `assess_underwriting_consistency` reads `d["facts"]` too. Test 1's "no
   warning" was passing on a document the engine could not see. Fixed, it now
   asserts the stronger `status == "consistent"` on a row the engine really
   compared - and the control confirms a Boulder address still conflicts.
3. The multi-insurer carrier test needed `facts["_scoped"]` - the C1b store
   `merge_facts` always writes. Without it a healthy 3-carrier package DOES
   read as a conflict; with it, `scoped`. A control pins the other direction:
   two carriers on the SAME line is still a real conflict.

**Standing lesson, and it is D22 again:** a fixture missing the key the
production reader actually uses does not fail - it passes for the wrong reason.
Every scenario in this pack therefore asserts a positive control, and three
tests carry an explicit comment naming the key that must not be changed back.

### TWO BEHAVIOURS WORTH KNOWING (neither is a defect)

* **`_drop_not_applicable_questions` fails OPEN** (`return kept or questions`):
  when every question would be dropped it returns the original list. A test
  feeding it only auto questions therefore sees none dropped. The pack's
  property-only fixtures always include the applicable property question, which
  is also the realistic shape.
* **HNOA-only owned-vehicle questions are NOT suppressed by that filter** - an
  HNOA account declines nothing, so `denied_lines` is empty and the filter never
  engages. The door that actually silences them is
  `question_eligibility.overlay_for` **Step 1** (`value_state == not_applicable`),
  which the pack now drives directly, including with ACORD 127 selected.

### Suite

`py -m pytest -q -p no:randomly` from `backend/` -> **5038 passed, 1 failed,
14 skipped, 1 xfailed.** The one failure is the documented
`test_arq_acord125_missing_only` `httpx` ImportError. Verified over **three
consecutive full runs**; the pack adds zero regressions. (One earlier run
reported two extra failures in `test_sqs_scoring_fixes_20260816` and
`test_v1_c1_canonical_facts`; both pass in isolation and did not recur in three
subsequent full runs - consistent with this suite's documented pre-existing
cross-test pollution, not with anything the pack introduced.)

### BE-F - `GL` / `WC` / `BAP` canonicalise: the owner ruled, and the naive fix was dangerous (2026-08-28)

**OWNER RULING 2026-08-28**, giving the product approval D9 reserves: add the
three bare abbreviations. Recorded as **D57**. This closes the eighth of the
nine beta-exit criteria and retires **O2**, open since 2026-08-26.

#### Why it sat unfixed, stated plainly

**It was never a technical blocker. It was a permission one.** D9: *"Folding a
phrase into an existing family, or adding a family, needs product approval."*
`canon_line` decides whether two documents are naming the SAME coverage line,
and getting that wrong in either direction is a class of defect this file has
already recorded twice - **G3** (a money rule folded Denver into Lakewood) and
**B14** (the umbrella $3M-vs-$1M conflict scoped into silence). So "engineering
does not unilaterally decide what counts as the same coverage" is a rule with
scar tissue behind it, and holding a two-minute change for a one-sentence
ruling was the correct trade.

#### And D9 was right, for a reason nobody had written down

The obvious implementation - append `"gl"` to `_GL_PHRASES`, `"wc"` to the
Workers Comp tuple - **is actively wrong**, because `_SPECIFIC` and
`_GL_PHRASES` match by **SUBSTRING** (`p in s`, `lob_canon.py:132`). That is
safe for a multi-word phrase and catastrophic for a two-letter one. Measured
BEFORE writing the fix:

| Printed line | contains | naive result |
|---|---|---|
| `Burglary and theft` | `gl` | a **CRIME** line read as General Liability |
| `Plate glass` | `gl` | a **PROPERTY** line read as General Liability |
| `Roofing shingles` | `gl` | a roofer's **own trade** read as General Liability |
| `Glazing contractors` | `gl` | ditto |
| `Showcase coverage` / `Newcastle Mutual` | `wc` | read as **Workers Comp** |

**The danger was never the equivalence - it was the matching mechanism.** A
one-line append would have manufactured coverage lines out of ordinary English
on exactly the accounts this codebase serves (a roofing contractor's schedule
contains "shingles"; a property schedule contains "plate glass"; a crime line
IS "burglary"). That is a normalisation change silencing or inventing a line,
which is the G3 / B14 failure mode, arriving through the front door.

#### What shipped

New `lob_canon._ABBREVIATIONS`, matched on **whole tokens** via `s.split()` -
the same test the bare-`liability` branch beneath it already used, so no new
mechanism was invented. Three entries, `gl` / `wc` / `bap`, and nothing else.

**Order is load-bearing and deliberate:** abbreviations are checked AFTER
`_SPECIFIC`, so `"Excess GL"` resolves to **umbrella**, exactly as
`"Excess General Liability"` always has. Checking them first would let an
excess policy masquerade as the primary line it sits over - **the C23 defect**,
which put a $3,000,000 umbrella limit into the GL boxes. Never the other way
round.

#### Measured

* The three that were broken: `GL` -> `general_liab`, `WC` -> `workers_comp`,
  `BAP` -> `auto` (and lower-case / padded spellings).
* **0 adversarial failures** across the eleven substring traps above.
* **0 regressions** across the 23-phrase existing vocabulary (GL, CGL, bare
  `Liability`, WC, Employers Liability, Business Auto, Umbrella, Excess, all
  six specialty families, `Widget Liability` -> None, `""` -> None).
* **700 passed** across the ten suites that touch `lob_canon`.
* Client-visible symptom now closed, end to end: a carried line printed `GL` no
  longer lands in `unmapped_material_lines` (Primble telling the producer it
  does not recognise the commonest abbreviation in commercial insurance), and
  `WC ... No Coverage` can now be DENIED - which was impossible while
  `canon_line` returned None for it, since `denied_families` skips a line it
  cannot place.

#### Known limit, deliberately not built

`G.L.` and `W/C` still return None: `_clean` strips punctuation to `"g l"` /
`"w c"`, so dotted or slashed initials are a MULTI-TOKEN sequence and matching
them needs a different mechanism. The ruling covered three abbreviations, not a
general initialism parser. `test_the_ruling_covers_exactly_three_abbreviations`
fails the build if a fourth is added quietly - **D9 is applied here, not
repealed.**

Tests: 6 in `tests/test_v1_beta_exit_20260828.py` (now 31 in that file).
