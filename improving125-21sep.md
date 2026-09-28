# improving125 - 21 Sep 2026

Running log for the ACORD 125 work. Append, never rewrite.

## The kit

| | |
|---|---|
| **Upload this** | `271page_test_data/A125_meridian_package.pdf` (100 pages) |
| **Answer key** | `271page_test_data/A125_answer_key.json` (all 548 boxes) |
| What each trap proves | `271page_test_data/README-A125-HOW-TO-TEST.md` |
| Regenerate both | `python3 backend/scripts/make_a125_test_pdf.py` (from the repo root) |
| Edit the data | `backend/scripts/_a125_data.py` - one source, PDF and key cannot disagree |

Key verdicts: **250 expect · 252 blank_no_data · 27 blank_by_rule · 8 not_applicable · 11 not_scored = 548.**
Of the 250 expectations, **21 are graded on MEANING** (narrative boxes) and
**229 on the EXACT value** - see `match_modes` in the key.

## Dumping a run

`py` is not a command on this Mac. From the **repo root**, with the venv active:

```bash
python3 backend/scripts/dump_a125_run.py --list
python3 backend/scripts/dump_a125_run.py <session_id> > a125_run.json
```

`PURGE_DEC_INDEX_AFTER_GENERATION=0` is optional - the per-document copies of the
declarations index survive the purge and the dump captures them either way. SQS
does not read the index at all.

Do not grade the downloaded PDF: `pikepdf` renders blank templates on this
machine. The stored values are intact.

---

# TEST 1 - 21 Sep 2026

Kit uploaded, ACORD 125 generated, no human touched it. Graded by transcribing
the generated form box by box and running `score_form_fill.py` against
`A125_answer_key.json`. Session dump not captured (`py` is not a command on
this Mac), so a handful of blank-vs-owned-blank splits are inferred.

## Scorecard

| | boxes | |
|---|---|---|
| Must carry a value | **250** | |
| &nbsp;&nbsp;correct | **149** | 59.6% of what it should fill |
| &nbsp;&nbsp;wrong value | **26** | |
| &nbsp;&nbsp;missing (blank, should be filled) | **75** | |
| Must stay empty | **287** | |
| &nbsp;&nbsp;violated - a value appeared | **10** | |
| **Fabricated** (scoped decoy landed) | **0** | every invention trap held |
| **Wrong shape** (FEIN / ZIP / code format) | **0** | |
| **Overflow leak** (a no-slot row displacing a real one) | **0** | |
| Not scored (generation metadata, account-sourced producer block) | 11 | |

**Accuracy of what it did fill: 149 / 185 = 80.5%.**
**Coverage of what it should fill: 149 / 250 = 59.6%.**

Three further boxes matched on meaning but not spelling (`Ste` vs `Suite`) and
are counted correct; the key's normalisation now covers address abbreviations.

## Row-cell

| group | cells expected | correct | cross-row | orphan |
|---|---|---|---|---|
| losses | 21 | **21** | 0 | 0 |
| premises | 32 | 28 | 0 | 0 |
| named insureds | 24 | 14 | **3** | 0 |
| prior coverage year one | 0 | 0 | 0 | **7** |

## What held

| | |
|---|---|
| Question 9 (bankruptcy) | **BLANK** - never asked in the document, not defaulted to `N` |
| Question 12 (foreign operations) | **BLANK** - same rule, second instance |
| OSHA checkbox | **BLANK** - blank-is-not-No at checkbox level |
| Applicant website | blank - `www.cascadiaharbor.com` is in all 100 page headers and did not land |
| FEIN row A | `93-2841760` - the 7-digit account number `4471100` did not land in a 9-digit box |
| 10 non-Contractor nature boxes | blank - "fabrication", "offices", "service" all appear in the prose |
| 8 `CancelNonRenew` boxes | blank - question 5 is N |
| 8 `OtherPolicy` boxes | blank - the four expiring policy numbers were not listed |
| Crime / Cyber / Liquor / Boiler / WC | not ticked - each is NAMED beside a denial |
| Every premium, policy number, underwriter | blank - the quote rules held exactly |
| `TOTAL LOSSES` | `$77,810` (paid), not `$90,310` (incurred) - the meaning trap held |
| Loss history | 3 rows x 8 columns, all correct, through a riffled source |
| Premises | 4 rows, no cross-row; Tigard's county correctly blank; only Location 004 outside city limits |
| Signatures, initials, NPN, licence, privacy notice | blank - authorship held |
| 4th claim (no slot) | disclosed in REMARKS, displaced nothing |

## Issues

| # | Issue | Boxes | Severity | Root cause |
|---|---|---|---|---|
| **I1** | Prior-carrier grid printed year TWO in row A and dropped the expiring year entirely. Row A = `2024 / Pinnacle Grange / GL 3318740 24 / $68,150`; should be `2025-2026 / Cascadia Harbor / GL 4471102 25 / $73,410`. Rows B and C blank. OTHER (umbrella) column blank. | 15 wrong + ~20 missing | **Wrong values** | RC1 |
| **I2** | Named-insured row C carries row B's identity: FEIN `26-0459318`, SIC `3441`, NAICS `332312`, GL code `91580`. Row B's own FEIN, SIC, NAICS, phone, website and address all blank. | 4 wrong + 12 missing | **Wrong values** | RC2 |
| **I3** | Three explanation boxes print the QUESTION instead of the answer (Q3, Q10, Q14). | 3 wrong | Wrong values | RC3 |
| **I4** | Q8 RESOLUTION box asserts a resolution on an **open** fire-code violation. The document says it has not been re-inspected. | 1 violated | **Material misstatement** | RC3 |
| **I5** | CARRIER and NAIC blank though the cover sheet names `Northbridge Atlantic / 41394`. STATUS ticked RENEW, not QUOTE. Q4 blanked as a chain effect. | 2 missing + 1 violated + 1 missing | Wrong + missing | RC4 |
| **I6** | Commercial Inland Marine not ticked though requested. The only requested line with no expiring policy behind it. | 1 missing | Missing | RC4 |
| **I7** | All 5 attachment boxes blank (Contractors Supplement, Statement of Values, Loss Summary, Vehicle Schedule, Driver Information Schedule) - blocked by `_is_nonfillable_field`'s `Attachment_` substring. | 5 missing | Missing | RC5 |
| **I8** | Per-location full-time and part-time employee counts blank on all four premises. | 8 missing | Missing | RC6 |
| **I9** | Subsidiary name and both ownership percentages blank though Q1a and Q1b are both Y and the document states all three. | 3 missing | Missing | RC7 |
| **I10** | Second additional interest (`Vaughn Street Holdings LP`) entirely absent, even from the name slot. `Item_LocationProducerIdentifier` and CERTIFICATE missing. | 3 missing | Missing | RC7 |
| **I11** | Contact B: type `Accounting` filled, name blank, its phone landed in contact A's SECONDARY slot, e-mail blank. | 2 missing + 2 violated | Missing + violated | RC7 |
| **I12** | `DESCRIPTION OF PRIMARY OPERATIONS` printed the GENERAL operations paragraph. The document carries both under separate headings. Other-named-insured operations blank. | 1 wrong + 1 missing | Wrong | RC8 |
| **I13** | Safety POSITION not ticked though a Director of Safety is named; a spare box ticked carrying `Written safety manual: Yes` as its description. | 1 missing + 2 violated | Missing + violated | RC3 |
| **I14** | Row C address line two printed the literal string `(None)`. | 1 violated | Placeholder leak | RC2 |
| **I15** | Additional interest: country code `US` invented; `Equipment finance agreement` ticked as an interest TYPE instead of filling REASON. | 3 violated | Minor invention | RC7 |
| **I16** | AUDIT printed `Annual` where ACORD's tooltip asks for the code `A`. | 1 wrong | Cosmetic | RC8 |
| **I17** | REMARKS holds the overflow-loss notice instead of the document's remarks. Arguably correct behaviour; the stated remarks are lost. | 1 wrong | By design? | - |
| **I18** | Member/manager counts blank on rows A and C; no entity type ticked on rows B and C. | 4 missing | Missing | RC2 |

## Root causes

| | Root cause | Issues |
|---|---|---|
| **RC1** | The prior-carrier grid has no recency ordering and no OTHER-line routing. It takes whichever year the list happens to yield first. | I1 |
| **RC2** | `additional_named_insureds` is a bare `[string]`. It carries a NAME and nothing else, so rows B and C have no FEIN, SIC, NAICS, phone, website, address, entity type or member count to draw from - and whatever filled row C came from row B. | I2, I14, I18 |
| **RC3** | Dependent narrative blocks are filled from the question, not the answer - and a narrative may be split across the wrong sub-box (explanation text landing in RESOLUTION). | I3, I4, I13 |
| **RC4** | Page one does not read the broker's cover sheet, so the carrier receiving the submission, the QUOTE status and a requested-but-new line are all unknown. | I5, I6 |
| **RC5** | `_is_nonfillable_field` blocks by name substring, killing five true attachment boxes. | I7 |
| **RC6** | Per-location employee counts have no binding. | I8 |
| **RC7** | Facts with no route to their box: subsidiary name/percentages, second additional interest, contact B, interest reason. | I9, I10, I11, I15 |
| **RC8** | Wrong paragraph in the right box; a word where ACORD asks for a code. | I12, I16 |

## Three answer-key corrections made before this was written

All three were MY errors, not the pipeline's. Expectations moved 258 -> 250.

1. **`LossHistory_ClaimStatus_OpenCode` is a Y/N box**, not an `O`/`C` code - ACORD's tooltip reads *"Enter Y for a Yes response... Indicates if the claim is still open."* I had predicted a defect here; the run was right. The self-consistency gate then caught my half-fix when the row-set still held the old vocabulary.
2. **The producer block is resolved from the LOGGED-IN ACCOUNT by design** (`v1-20AUG.md`, "ORBIN - who is this party"). `Astrea It Services` / `Vinay Sharma` is correct behaviour. Ten producer fields moved to `not_scored`.
3. **`Subsidiary_*` row A is question 1a's PARENT block, row B is 1b's SUBSIDIARY block** - confirmed against the printed form. I had both on row A.

## Wording contract added

An LLM may legitimately reword a narrative; it may not reword an identifier. The
key now carries `match_modes`, derived from ACORD's own tooltip plus the field
name:

- **21 expectations graded on MEANING** - descriptions, explanations, remarks,
  relationship and operations text.
- **229 graded EXACT** - every FEIN, policy number, date, amount, code, name,
  address and checkbox. "Close enough" is a wrong value on a signed application.

## Standing lessons

- **The guards are not the problem any more.** 0 fabrications, 0 shape failures,
  0 overflow leaks, every grant and authorship rule held. Stop hardening them.
- **A bare `[string]` list fact cannot fill a table.** Three named insureds, one
  usable row. The same shape sits under additional interests.
- **Write the key from ACORD's tooltip, not the field name.** I got `OpenCode`
  wrong by reading the name; the tooltip said Y/N all along.

---

# ROUND 1 FIXES - 21 Sep 2026

Two root causes closed. Both chosen by PROPAGATION, not by where the defect was
reported - the anchor-form goal only pays off if a fix lands on every form that
prints the same family.

| Root cause | Boxes | Forms | Status |
|---|---|---|---|
| RC7 AdditionalInterest | 182 | 6 | open |
| **RC3 Explanation / Resolution** | **129** | **7** | **FIXED** |
| RC6 EmployeeCount | 111 | 9 | open |
| **RC1 PriorCoverage** | **90** | **3** | **FIXED** |
| RC2 NamedInsured rows B-N | 78 | 8 | open |
| RC5 Attachment | 53 | 5 | open |

## RC1 - the prior-carrier grid deleted the expiring programme

**Root cause, and it is not what the symptom suggested.** The ordering logic was
already newest-first and correct. The rows were gone before it ran. The log
named it once I asked for it:

```
prior-coverage: dropped CURRENT policy 'GL 4471102 25' from the prior grid
prior-coverage: dropped CURRENT policy 'CF 4471104 25' from the prior grid
prior-coverage: dropped CURRENT policy 'BA 4471106 25' from the prior grid
prior-coverage: dropped CURRENT policy 'XSU-9920415-25' from the prior grid
```

`_prior_coverage_grid` discards an entry whose policy number appears in
`coverage_lines`, on the rule *"the current policy is not prior coverage"*. That
rule is right and stays. What was wrong is that **a policy number has no time
axis.** On a renewal being re-marketed to a new carrier, `coverage_lines`
describes the EXPIRING policies - they are the only contracts the documents
detail - so every genuine year-one row matched and was deleted.

The filter's OTHER test, on the effective date, was correct all along and did
not fire (10/01/2025 is not the proposed 10/01/2026). Only the number test had
no time axis.

**Fix.** A number match is evidence only when the entry's own term IS the term
being applied for, or when it states no term at all. One condition, derived from
facts already held.

**A wrong fix I nearly shipped, and why I did not.** My first plan was to gate on
`renewal_dates_routed` - the signal `_prior_rows_from_current_policies` uses for
"the term has moved". I checked the facts before writing it: **it is `null` on
this package.** The term never needed moving, because the submission states the
proposed term and the declarations state the expiring term as separate facts
from separate documents. The fix would have compiled, passed a fixture and done
nothing. Verify the signal exists before you build on it.

**Decisions taken**

- The number test is narrowed, not deleted. An entry with a matching number and
  NO stated term is still dropped - conservative, and it preserves the
  pre-21-Sep behaviour wherever we cannot date an entry.
- `PriorCoverage_PolicyYear` prints a single year (`2025`), not a span. ACORD's
  own tooltip reads *"Enter year: The year for which you are providing
  information."* **The key was wrong; the product was right.**
- `PriorCoverage_OtherLine_LineOfBusinessCode_A` takes the line as the document
  prints it (`Commercial Umbrella`). Key corrected.

**Result on the kit:** row A = 2025 with all four lines including the umbrella on
its third carrier; row B = 2024 with three; row C blank. **PriorCoverage family
against the key: 35 correct / 3 key errors / 0 missing / 0 blank violations.**

## RC3 - Guard 12: an explanation that is its own question, and an undated resolution

All five explanation boxes come from **gap fill**, not from deterministic code -
checked before designing anything. This is the model restating the question.

**Guard 12a - an explanation may not restate its own question.** Structural, and
it cannot reject a genuine narrative: the value must carry its own `?`, the text
up to it must be accounted for by the field's OWN question, and there must be
nothing of substance after it.

**The first version of the test was wrong and the run caught it.** I used the
existing `_is_near_duplicate_text` (symmetric Jaccard). ACORD's tooltip question
is usually LONGER than the echo - *"...during the last five (5) years?"* against
*"Has applicant had a judgment or lien?"* - so it scored 0.36 and let the echo
through. The right test is one-way **containment**: does the head say anything
the question did not. Threshold 0.8, which leaves room for exactly the spelling
difference the live run produced (`judgment` against a tooltip that says
`judgement`).

**Guard 12b - an undated resolution has not happened.** Question 8's RESOLUTION
came back *"Abatement is scheduled, the premises has not yet been
re-inspected"* - a sentence that DENIES a resolution, printed in the box that
asserts one. ACORD pairs every `…ResolutionDescription` with its own
`…ResolutionDate` on the same row, so the invariant needs no reading of the
text: **a resolution nobody dated has not occurred.** Derived from the schema, so
a new pair on any form is covered the day it appears.

**Decisions taken**

- **Blank, never strip the echo.** Right-or-blank is the contract, and a blanked
  box reaches the producer's review; a half-repaired one does not.
- **An echo followed by a real explanation is KEPT whole.** It answers the box.
  This is the C47 lesson: a direct answer to a yes/no question is by definition
  mostly the question's own words, so overlap alone is never sufficient.
- **D6 - two correct `Y` answers become blanks.** Blanking an explanation trips
  Guard 5's pre-existing "naked Yes" rule, which blanks the affirmative too. The
  document plainly answers Y, so this is a real loss of two boxes. Kept
  deliberately: an affirmative whose only justification was a restatement of the
  question is not evidenced, and the ARQ will ask. **Tell Brent.**

## Verification

| | |
|---|---|
| New tests | `tests/test_a125_fixes_21sep.py` - **16 passed** |
| Adversarial cases written FIRST | the misfiled-current-policy case, the real-explanation case, the echo-then-explanation case |
| Proved the tests bite | RC1: reverted, **6 of 8 failed**. RC3: removed Guard 12, **3 failed** - and in both cases every false-positive control stayed green, which is the correct signature |
| Full suite | **9475 passed / 2 failed / 18 skipped** |

**The second failure is NOT from this work.**
`test_confidence_score_covers_every_label::test_verified_ai_values_never_read_as_an_empty_form`
asserts `confidence_fill_rate >= 85` and gets `84`. It lives in `sqs_service.py`,
which this work never touched. It is the truncation defect CLAUDE.md already
records as open item 2 - `return int((weighted / filled_count) * 100)`, where
`10 x 0.85` lands on `84.99999999999999`. **The test is right and the code is
wrong**, and the one-character fix moves every score sitting on such a boundary,
so it is Brent's call under D6, not a drive-by. Left alone deliberately.

**CLAUDE.md's "1 pre-existing failure" baseline is stale - it is 2.**

## Still open, in propagation order

| RC | What | Boxes | Forms | Needs |
|---|---|---|---|---|
| RC7 | AdditionalInterest has no structured fact | 182 | 6 | schema change + `PROMPT_VERSION` bump |
| RC6 | Per-location employee counts unbound | 111 | 9 | binding only |
| RC2 | `additional_named_insureds` is a bare `[string]` | 78 | 8 | schema change + `PROMPT_VERSION` bump |
| RC5 | `_is_nonfillable_field` blocks 5 real attachment boxes | 53 | 5 | narrow the substring |
| RC4 | Page one does not read the broker cover sheet | ~5 | 1 | resolver |
| RC8 | Wrong paragraph / word-for-code | 2 | 1 | binding |

RC5 and RC6 are cheap and touch no schema - the natural next pair. RC2 and RC7
are the two that need a prompt version and should each get their own run so the
movement is attributable.

---

# ROUND 2 FIXES - 21 Sep 2026

Two more root causes closed, one parked with a reason, and **three corrections
to my own earlier findings**.

## RC5 - the ATTACHMENTS family had no owner, only a name block

**Ruling taken.** The ACORD ATTACHMENTS block asks what accompanies the
application *Primble* produces. The uploaded file's own cover sheet describes a
DIFFERENT submission - a broker's old attachment list cannot say what will be
stapled to ours. So a box ticks only when this package provably contains what it
names: **a form we generate, or a schedule we fill.** Everything else is an
owned blank, deliberately.

`_resolve_attachment_indicator` replaces the `"Attachment_"` substring in
`_is_nonfillable_field`, which reached the right answer for the wrong reason: it
blanked the boxes nobody can know AND the ones this package can prove, and could
never tick either. The package form list is carried on the facts dict as a
private `_package_form_ids` key, exactly the way `_form_id` already is - **so
the `map_facts_to_form` signature change `fix-form-stamping.md` recorded this
item as blocked on was never needed.**

**Two mistakes I made here, both caught before shipping:**

1. **The first regex matched only ACORD 125's prefix** and left 11
   `<LineOfBusiness>_Attachment_*` boxes on 126/127/130/140 owned by nothing the
   moment the substring came out - an invention surface opened by the fix meant
   to close one. Caught by sweeping all 17 schemas, which is now a standing test.
2. **The first version also claimed `Policy_SectionAttached_*`, and that family
   already had an owner.** `_resolve_section_attached_indicator` +
   `_INDICATOR_RULES` covers it, with a WEAKER rule replaced by mine: the
   existing one requires a driver row to carry more than a name, because a
   DRIVE OTHER CAR endorsement naming an individual is not a driver schedule.
   **The suite caught it** (`test_run5_authorship_and_attachment`), four boxes
   that fill correctly today would have gone dark. Scope narrowed to
   `*_Attachment_*`, and a test now pins that this resolver never claims the
   other family.

## RC8 - the audit box takes ACORD's CODE, not the document's word

ACORD's tooltip: *"Enter code: ... A - annual, S - semi-annual, Q - Quarterly,
M - Monthly, O - Other."* The document prints the word; the box takes the letter.

**`semi-annual` is tested before `annual`, deliberately** - it contains the
substring, so the obvious ordering silently codes a semi-annual audit as annual,
which changes how often the carrier audits the payroll the premium is rated on.
A period with no ACORD code is an owned blank, never the raw word.

## RC6 and RC4 - PARKED, with reasons

- **RC6 (per-location employee counts).** Not a stamping gap. The binding
  already exists (`BusinessInformation_FullTimeEmployeeCount` ->
  `property_locations.full_time_employees`) and **stamps correctly** when the
  fact carries the column - measured `'12'`, `'3'`, `'21'`. The live run's
  extraction did not populate those two columns off a whitespace premises table.
  **That is an extraction miss and it is not diagnosable without the session
  dump.**
- **RC4 (page-one carrier / QUOTE status).** The merge marks
  `carrier_is_current_policy` unless a document whose `doc_type` is a PROPOSAL
  names the carrier. The kit is ONE PDF whose first two pages are a broker
  submission cover sheet and whose remaining 98 are declarations, so it types as
  `dec_page` and no proposal document exists. Fixing it properly means
  PAGE-level classification - the segmentation work `extraction_arch_change.md`
  lists as the top open build item and explicitly scopes out of stamping.
  **Not guessed at.** Splitting the kit into separate files to suit the code was
  available and refused: real clients upload one combined PDF, and a fixture
  easier than reality proves nothing.

## THREE CORRECTIONS TO MY OWN EARLIER FINDINGS

**1. "31 checkboxes stamped `No` where ACORD wants blank" - WRONG, withdraw it.**
`fill_pdf` writes `/Off` for any `/Btn` value that is not a Yes, so those boxes
render **unticked, which is correct**. The string `"No"` exists only in the
`mapped` dict. I reported it from a deterministic probe instead of from the
form; the form was right. The run-1 scorecard, which was graded from the form,
correctly showed 10 violations, not 31.

**2. `LossHistory_ClaimStatus_OpenCode` is a Y/N box** (round 1) - the run was
right, my key was wrong.

**3. `Subsidiary_*` row A is the PARENT block, row B the SUBSIDIARY block**
(round 1) - confirmed against the printed form.

## Where the deterministic layer now stands

Extraction assumed perfect, scored at the form's own render semantics:

| | before round 1 | after round 2 |
|---|---|---|
| correct | 118 | **150** |
| wrong | 23 | **1** |
| must-be-blank violated | 31 | **0** |

The one remaining wrong value is REMARKS holding the overflow-loss notice
instead of the document's remarks - the overflow disclosure is deliberate
behaviour and arguably the more useful of the two. Flagged, not "fixed".

Of the 94 expectations the deterministic layer does not reach, **82 are handed
to LLM call 2** and 12 are owned blanks.

## Verification

| | |
|---|---|
| New tests | `tests/test_a125_fixes_21sep.py` - **26 passed** |
| Existing tests corrected (the decision changed, not the test's subject) | `test_run4_fixes_20260906` (audit box takes the code), `test_authoritative_blank_contract` (claimant census + ceilings) |
| Full suite | **9487 passed / 2 failed / 18 skipped** - the same two pre-existing failures |

**On the withholding ceiling.** Adding the attachment resolver moved
`_is_authoritative_blank_field` from 127 to 155 of 548 (28.3%), past a 25%
ceiling. Measured before touching it: those 28 boxes were **already** withheld
from the model by `_is_nonfillable_field`, which that counter never saw.

```
withheld by a registered resolver   127 -> 155
withheld by _is_nonfillable_field    88 ->  60
withheld by EITHER                  202 -> 202   <- UNCHANGED
```

Nothing new is hidden; 28 fields moved from an uncounted mechanism to a counted
one and **gained the ability to be answered**. The ceiling was raised in the
open with that measurement recorded, rather than the family being relabelled a
"grid" to keep the number flat - the same refusal this file recorded on
2026-09-05.

## Standing lessons from round 2

- **Check whether the thing already has an owner.** I reimplemented
  `_resolve_section_attached_indicator` with a weaker rule and the suite caught
  it. Grep the family before writing a resolver for it.
- **A probe against `mapped` is not the form.** `"No"` on a checkbox renders
  `/Off`. Grade at the render semantics or withdraw the finding.
- **When a ceiling test fires, measure what it was standing in for** before
  moving it. Here the true invariant - what the model never sees - had not
  changed at all.

---

# TEST 2 - 21 Sep 2026 (retest after rounds 1 and 2)

Same kit, same single form, no human edits. Graded by transcribing the generated
form box by box and scoring it against the CURRENT `A125_answer_key.json`.

**Test 1 has been RE-SCORED against the same current key** so the two columns are
comparable. The key moved between the runs (250 -> 245 expectations; the
`PolicyYear`, `OtherLine` and `OpenCode` corrections), so the originally published
149/26/75 is not the number to compare against. Re-scored, test 1 is 148/27/70.

A scoring bug of my own was fixed first: the grader read `"1"` in the LOC # box as
a checkbox tick, because `1` is in the tick vocabulary. A tick vocabulary now
applies only to a `/Btn` field. It cost one box in each run.

## Scorecard

| | TEST 1 | TEST 2 | change |
|---|---|---|---|
| Must carry a value | 245 | 245 | |
| &nbsp;&nbsp;**correct** | 148 | **178** | **+30** |
| &nbsp;&nbsp;**wrong value** | 27 | **3** | **-24** |
| &nbsp;&nbsp;missing (blank, should be filled) | 70 | **64** | -6 |
| Must stay empty | 292 | 292 | |
| &nbsp;&nbsp;**violated - a value appeared** | 10 | **6** | -4 |
| **Fabricated** (scoped decoy landed) | 0 | **0** | 0 |
| Wrong shape (FEIN / ZIP / code format) | 0 | 0 | 0 |
| Overflow leak (a no-slot row displacing a real one) | 0 | 0 | 0 |
| Not scored (generation metadata, account-sourced producer block) | 11 | 11 | |
| **Accuracy of what it filled** | 84.6% | **98.3%** | **+13.7 pts** |
| **Coverage of what it should fill** | 60.4% | **72.7%** | **+12.3 pts** |

48 boxes became correct; 18 regressed. Net +30.

## Row-cell - the metric to steer by

| group | cells due | T1 correct | T2 correct | T1 cross-row | T2 cross-row | T2 orphan |
|---|---|---|---|---|---|---|
| losses | 24 | 24 | 24 | 0 | 0 | 0 |
| premises | 56 | 55 | 55 | 0 | 0 | 0 |
| named insureds | 38 | 20 | **27** | 4 | **1** | 2 |
| prior coverage | 35 | **0** | **35** | **15** | **0** | 0 |

**The prior-carrier grid went from 0 of 35 with 15 cells carrying another row's
policy, to 35 of 35 with none.** That is RC1, confirmed on a live run.

## What the fixes actually did

| Fix | Shipped in | Live? | Evidence on the form |
|---|---|---|---|
| **RC1** prior-coverage grid | round 1 | **YES** | row A = 2025 / Cascadia Harbor / 4 lines incl. the umbrella in OTHER; row B = 2024 / Pinnacle Grange / 3 lines; row C blank. 38 boxes newly correct |
| **RC3** Guard 12a (echo) | round 1 | **YES** | Q3, Q10 and Q14 no longer print their own question back |
| **RC3** Guard 12b (undated resolution) | round 1 | **YES** | Q8's RESOLUTION is blank. The material misstatement is gone |
| **RC5** attachments | round 2 | no signal | a 125-only package contains no ACORD 186 or 127, so the boxes are correctly blank either way. Untested by this run, as predicted |
| **RC8** audit code | round 2 | **NO - see J1** | the box still prints `Annual` |

## Issues

| # | Issue | Boxes | Severity | Root cause |
|---|---|---|---|---|
| **J1** | **The run did not contain round 2.** AUDIT prints `Annual`. Today's code cannot produce that value by ANY path - `_resolve_audit_frequency` is registered, its regex matches, and `compute_form_gaps` / `map_facts_to_form` both return `A` with the fact and an owned blank without it. A word can only reach that box from a build that predates the fix. | 1 observed | **Process, not code** | server not restarted after 16:37 |
| **J2** | Questions 1a, 1b, 2 and 8 came back **entirely blank** - answers, parent/subsidiary names, relationship text, the safety-programme boxes and the fire-code date. All were filled in test 1. **No change I made has a mechanism that reaches them**, and all are call-2 owned. | 13 | Coverage loss | LLM call 2 variance (unproven - needs the dump) |
| **J3** | **The Guard 12 cascade is wider than I predicted.** I said 3 boxes. It is 5: the three `Y` answers plus the judgement/lien OCCUR DATE and RESOLVE DATE, which were CORRECT values. Guard 9 blanks the naked Yes, then the late dependent sweep clears the dates under it. | 5 | **D6 - tell Brent** | my change, deliberate, cost larger than stated |
| **J4** | **NEW: row B's website `www.cedarbluffsteel.com` landed on row A.** Meridian has no website in the document; Cedar Bluff does. Row B's own website box is blank. A cross-entity leak that did not exist in test 1. | 2 | **Cross-row** | RC2 |
| **J5** | `(None)` printed as address line two on rows B **and** C. One instance in test 1, two now - row B gained an address and the placeholder with it. | 2 | Placeholder leak | RC2 |
| **J6** | Contact B's phone `(503) 555-0193` still sits in contact A's SECONDARY slot; contact B's type, name and phone are blank and a BUS tick sits on an empty phone. | 1 violated + 4 missing | Violated + missing | RC7 |
| **J7** | Country code `US` still invented on the additional interest. | 1 | Minor invention | RC7 |
| **J8** | CARRIER and NAIC blank, STATUS ticked RENEW not QUOTE, Commercial Inland Marine not ticked. | 4 | Wrong + missing | RC4 (parked) |
| **J9** | Per-location full-time and part-time employee counts blank on all four premises. | 8 | Missing | RC6 (parked) |
| **J10** | Subsidiary block (name, both percentages, both relationship lines) and the second additional interest still have no route to a box. | 6 | Missing | RC7 |
| **J11** | `DESCRIPTION OF PRIMARY OPERATIONS` holds the GENERAL operations paragraph. Other-named-insured operations blank. | 1 wrong + 1 missing | Wrong | RC8 |
| **J12** | REMARKS holds the overflow-loss notice instead of the document's remarks. Deliberate behaviour; the stated remarks are lost. | 1 | By design | - |

## What held, again

| | |
|---|---|
| Invention traps | **0 of 11 landed**, both runs. Every scoped decoy held |
| Loss history | 3 rows x 8 columns, all correct, through a riffled source |
| `TOTAL LOSSES` | `$77,810` (paid), not `$90,310` (incurred) - the meaning trap held twice |
| Premises | 4 rows, 55 of 56 cells, no cross-row, Tigard's county blank, only Location 004 outside city limits |
| FEIN row A | `93-2841760`; the 7-digit account number `4471100` never reached a 9-digit box |
| Every premium, policy number, underwriter on page one | blank - the quote rules held |
| Signatures, initials, NPN, licence, privacy notice | blank - authorship held |
| Q9 (bankruptcy), Q12 (foreign operations) | **BLANK** both runs - never asked in the document, never defaulted to `N` |
| 4th claim (no slot) | disclosed in REMARKS, displaced nothing |

## The honest reading

**Improved, decisively, on everything I could verify.** Wrong values fell 27 -> 3
and accuracy of what the form actually filled is 98.3%. The two fixes that could
show on this run both showed.

**But this run is not a clean test of round 2.** J1 proves the generating process
was running round-1 code. RC8 is unverified, RC5 is unverifiable on a 125-only
package, and the 18 regressions were measured against a build that is not the one
on disk.

**And I still have no session dump.** J2 - 13 boxes - is the single largest
remaining loss and I cannot tell you whether call 2 answered differently or a
guard ate them. Every one of the 18 regressed boxes is call-2 owned; not one is
deterministic. That is the whole argument for capturing the dump next time.

## Standing lessons from test 2

- **An offline probe proves the FUNCTION, never the SEAM - and neither proves the
  BUILD.** I verified `_resolve_audit_frequency` three ways and it was right every
  time. The form still printed the word, because the process serving the request
  had not imported the file. Add "which build produced this artefact" to the
  evidence list, not just "which code is on disk".
- **Name the cascade's real width before shipping it.** I told Brent two boxes.
  It is five, and two of them were correct dates. The guard is still right; the
  estimate was not.
- **A grader is a fixture and gets the same scrutiny.** `"1"` read as a tick cost
  a box in both runs. It was caught only because a LOC # box appeared in the
  wrong list with an expected value that normalised to the same string.

---

# ROOT CAUSES OF WHAT IS STILL BROKEN - 21 Sep 2026

Every root cause below is stated as a **class**, with the blast radius measured
across all 17 real schemas. None of them is specific to the Meridian kit - the
kit is how they were found, not what they are. Where a fix would only make this
fixture pass, that is called out and rejected.

## Master table - ranked by propagation

| RC | Class | Boxes | Forms | Issues | Fix shape | Cost |
|---|---|---|---|---|---|---|
| **RC-C** | No deterministic floor under compliance questions | 312 | 9 | J2 | facts + bindings | `PROMPT_VERSION` bump |
| **RC-B** | No absence normalisation between the LLM and the box | **all 5,852** | **17** | J5 | post-fill guard | **cheap, no prompt** |
| **RC-E** | A code the document never states is invented | 246 | 13 | J7 | grounding enforcement | cheap |
| **RC-A3** | AdditionalInterest has no structured fact | 182 | 6 | J10 | schema change | `PROMPT_VERSION` bump |
| **RC-A1** | Named-insured rows B-N have no per-row fact | 66 | 8 | J4, J5, J10 | schema change | `PROMPT_VERSION` bump |
| **RC-G** | An abbreviated table header has no lexical bridge to its fact | 40 | 4 | J9 | prompt synonyms | `PROMPT_VERSION` bump |
| **RC-D** | One narrative fact, two distinct ACORD boxes | 15 | 4 | J11 | resolver | cheap |
| **RC-A2** | Contact rows B-N have no per-row fact | 12 | 1 | J6 | schema change | `PROMPT_VERSION` bump |
| **RC-A4** | Subsidiary / parent has no fact at all | 6 | 1 | J10 | schema change | `PROMPT_VERSION` bump |
| **RC-F** | Page-level document classification (carrier / QUOTE) | ~5 | 1 | J8 | segmentation | large, parked |

---

## RC-A - THE DOMINANT ONE: a single-entity fact model against N-row ACORD tables

**This one class produces J4, J5, J6, J10 and most of what was RC2 and RC7.**

The extraction schema models the applicant as **one entity with singular
attributes**. ACORD forms print **tables of entities**. Measured, from
`_EXTRACT_SCHEMA` itself:

| The document may state | The fact model offers | The form prints |
|---|---|---|
| a website per named insured | `applicant_website`: `string or null` | 3 rows |
| a contact per role | `contact_name` / `contact_phone` / `contact_email`: singular | 2 blocks |
| N named insureds with FEIN, SIC, NAICS, phone, address, entity type | `additional_named_insureds`: **`[string]`** - names only | 3 rows x 13 columns |
| a parent and subsidiaries with % owned | **no fact exists** | 2 blocks x 3 columns |
| N additional interests | **no fact exists** | 1 block x 25 boxes, +ACORD 45 |

**Why this is generic and not a fixture artefact.** When N entities compete for
1 slot, the value has exactly three fates, and the run showed all three:

1. **It lands on the primary entity.** `www.cedarbluffsteel.com` is row B's
   website; the only slot is `applicant_website`; Pass 1 stamps that on row A.
   **J4.** This happens on ANY package where a non-primary insured states an
   attribute the primary one does not - a holding company with its own phone, a
   DBA with its own website. It is not about websites.
2. **It lands in an adjacent slot.** Contact B's phone in contact A's SECONDARY
   box. **J6.** Any second contact, any role.
3. **It never lands.** Subsidiaries, second additional interest. **J10.**

**Fate 1 is the dangerous one** - it is a wrong value on a signed application,
not a blank, and it passes every existing guard because the value is real, is
literally present in the document, and is correctly shaped.

**The fix shape, and the precedent is already in the repo.** `property_locations`,
`auto_vin_schedule`, `wc_class_codes` and `auto_drivers` are already row-bearing
list facts whose columns bind to real ACORD fields. These five families must
become the same shape.
`test_every_schedule_column_binds_to_a_live_acord_field` already fails the build
if a column is added with no live binding, so the guard exists.

**CLAUDE.md already names this.** The Figure 15 entry lists
`additional_named_insureds` among six schedules with **ZERO live bindings** and
calls mapping them "the obvious follow-up". That was 2026-07-21. This is the
bill for not doing it.

**Rejected:** binding row B's website to `applicant_website` when row A has none.
That makes THIS kit pass and silently mis-attributes an attribute on any package
where both state one. A fixture-shaped fix for a data-model defect.

---

## RC-B - no absence normalisation between the LLM and the box

**Symptom (J5):** `(None)` printed as address line two on two rows.

**Root cause, in two layers.**

**Layer 1 - the path has no door at all.** `services/answer_semantics.py` is the
ONE door for reading a human's answer, and it knows "None" means absence. It is
**never consulted for an AI-extracted or gap-filled value.** `merge_facts` writes
`facts[key]` directly. This is not a new discovery - CLAUDE.md records it
verbatim as **GAP 1** under "Answer Interpretation", including the symptom to
watch for: *"a submission scoring better than its documents justify, with fields
displaying N/A"*. This run is that symptom, on a legal document.

**Layer 2 - the door's own vocabulary is defeated by decoration.** Measured
against the real module:

```
'None'    -> read as an absence      'N/A'     -> NOT read as an absence
'none'    -> read as an absence      'unknown' -> NOT read as an absence
'NONE'    -> read as an absence      'TBD'     -> NOT read as an absence
'(None)'  -> NOT read as an absence  '-'       -> NOT read as an absence
```

One pair of parentheses is the whole difference between the two columns' first
rows. Any model wrapping its "nothing here" token in brackets, quotes or a dash
walks straight through.

**Why generic:** this is not about `(None)` and not about address line two. ANY
of the ~5,852 boxes on any of the 17 forms can receive an absence token from
either LLM call. The blast radius is the whole surface.

**Fix shape:** (1) strip surrounding decoration before matching, inside the
existing door - so the vocabulary is not copied; (2) a post-fill guard that runs
LAST and routes every stamped value through that one door, so Pass 1, Pass 1.5
and call 2 are all covered by one rule. No prompt change, no schema change, no
new vocabulary list.

**Rejected:** adding `"(None)"` to a denylist. That is the exact whack-a-mole the
2026-08-08 boilerplate incident recorded three times before the real fix landed.

---

## RC-C - ACORD 125's entire GENERAL INFORMATION section has no deterministic floor

**Symptom (J2):** questions 1a, 1b, 2 and 8 were fully answered in test 1 and
fully blank in test 2. 13 boxes moved with no code change between them.

**Root cause, measured against `_EXTRACT_SCHEMA`:**

```
safety_program   NO FACT      judgement/judgment  NO FACT      drone      NO FACT
formal_safety    NO FACT      lien                NO FACT      flammable  NO FACT
parent_company   NO FACT      fire_code           NO FACT      country    NO FACT
parent_organ     NO FACT      bankrupt/foreclos   NO FACT
```

**Not one of the 15 general-information questions has a backing fact**, and the
`fates` replay confirms every one of the 13 regressed boxes is `to_gpt`. So the
entire section - the questions, their explanations, their occurrence dates, the
parent/subsidiary names and percentages, the four safety-programme boxes - is
answerable **only** by a non-deterministic LLM call, with nothing underneath it.

**That is why they flip between runs. It is structural, not bad luck.** Two runs
of the same document over the same code will disagree on this section, and there
is no mechanism that can make them agree.

**Why generic:** 312 compliance-question boxes across 9 forms sit on exactly this
footing. ACORD 126 has 22 of them, ACORD 186 has 88.

**Fix shape:** facts for the disclosures the documents actually state, so call 1
records them once and a deterministic rule stamps them, leaving call 2 as the
fallback it is supposed to be. Start with the ones a commercial package states in
plain text - formal safety programme and its four sub-boxes, parent/subsidiary
with % owned, and the five "during the last five years" disclosures.

**Deliberately NOT proposed:** re-running the compliance pass and taking the
majority answer. It triples the cost of the most expensive stage to paper over a
missing fact, and two wrong answers still outvote one right one.

---

## RC-E - a code the document never states is invented

**Symptom (J7):** `AdditionalInterest_MailingAddress_CountryCode_A` = `US`. The
document states no country anywhere, and there is no `country` fact.

**Root cause:** a field with no fact, no resolver and no grounding requirement is
free real estate. The model fills what is overwhelmingly probable. For a US
address `US` is even *correct* - which is what makes the class dangerous: the
same mechanism supplies a plausible state code, a plausible NAIC, a plausible
class code, and nothing distinguishes the lucky guess from the wrong one.

**The detector already exists and does not enforce.**
`_report_ungrounded_ai_values` is read-only by inspection - CLAUDE.md records
this. So the pipeline already KNOWS which AI values are absent from the document
text and does nothing with the knowledge.

**Why generic:** 246 country/state-code boxes across 13 forms, and the same rule
extends to any box whose legitimate value must be a literal token in the source.

**Fix shape:** promote the existing detector from advisory to enforcing for a
narrow, safe class - fields whose ACORD tooltip declares a CODE and whose value
must therefore appear verbatim in the document. Not for amount boxes, which
legitimately hold "Statutory", "Included", "See schedule" (the C22 lesson).

---

## RC-G - an abbreviated table header has no lexical bridge to its fact

**Symptom (J9):** per-location full-time and part-time employee counts blank on
all four premises.

**I said in round 2 this was "an extraction miss, not diagnosable without the
dump". The form itself diagnoses it.** The kit prints one table:

```
LOC  BLDG  FT  PT  REVENUE  OCCUPIED  PUBLIC  TOTAL  LEASED
```

**Four of those columns stamped correctly on all four rows** - REVENUE, OCCUPIED,
PUBLIC, TOTAL. So the table was found, its rows were aligned, and its cells were
read. Only FT and PT were dropped.

**The columns that landed are exactly the columns whose header word appears
inside the fact name** (`REVENUE` -> `annual_revenue`, `OCCUPIED` ->
`occupied_area`, `PUBLIC` -> `open_to_public_area`, `TOTAL` ->
`total_building_area`). The two that did not land are the only two whose header
is an **abbreviation with no lexical overlap** with `full_time_employees` /
`part_time_employees`.

The column exists in `property_locations`, the ACORD binding exists and was
measured stamping correctly in round 2. Nothing downstream is broken.

**Why generic:** real broker schedules abbreviate constantly - `FT`/`PT`, `EFF`/
`EXP`, `GVW`, `TIV`, `BPP`, `YR`, `AMT`. Every one of them is the same defect
waiting for a different column.

**Fix shape:** name the common abbreviations beside the column in the extraction
prompt, taken from the ACORD form's OWN printed label (`# FULL TIME EMPL`), so
the synonym set is derived from a source we already maintain rather than invented.
**Still to confirm from the dump** whether `property_locations` came back without
the columns (extraction) or with them (merge) - one line settles it, and the fix
differs.

---

## RC-D - one narrative fact, two distinct ACORD boxes

**Symptom (J11):** `DESCRIPTION OF PRIMARY OPERATIONS` holds the general
operations paragraph; `DESCRIPTION OF OPERATIONS OF OTHER NAMED INSUREDS` is
blank. The document carries both, under separate headings.

**Root cause:** `operations_description` is one scalar. ACORD 125 prints
`CommercialPolicy_OperationsDescription_A` and `_B` as different questions about
different subjects. One fact cannot answer two questions, so it answers the first
and the second goes empty - or worse, takes the same paragraph.

**Why generic:** 15 operations-narrative boxes across 4 forms, and the class is
wider than operations - any ACORD pair that splits one topic by SUBJECT.

**Fix shape:** the box with no fact of its own is an **owned blank**, never the
other box's paragraph. That is the right-or-blank contract and it needs no prompt
change. A second fact for the other-named-insureds narrative is the follow-up.

---

## What I am NOT proposing

- **Re-running LLM call 2 for stability.** Cost triples, and it papers over RC-C.
- **A denylist of bad strings.** RC-B's fix goes through the existing door.
- **Splitting the kit into separate files** so RC-F's classifier can see a cover
  sheet. Real clients upload one combined PDF (D22).
- **Binding row B's website to `applicant_website`.** Passes this kit, corrupts
  the next one.

## Recommended order

1. **RC-B** - whole surface, cheap, no prompt bump, no schema change.
2. **RC-E** and **RC-D** - cheap, the detector and the contract both already exist.
3. **RC-A** - one `PROMPT_VERSION` bump covering all five families at once, so
   the cache is invalidated once rather than five times.
4. **RC-C** - the largest, and the one that decides whether two runs of the same
   document can ever agree.
5. **RC-G** - fold into the RC-A prompt bump; confirm the layer from the dump first.
6. **RC-F** - segmentation, its own project.

---

# THE COMPLETE FIX - 21 Sep 2026

Six of the seven root causes closed. Every change is a RULE derived from a
source we already maintain - ACORD's own tooltips, the existing schedule
pattern, the existing absence door - and none of them is tuned to the Meridian
kit.

## What the deterministic layer does now

Measured with the offline harness (`a125_v22.py`), extraction assumed correct,
graded at the form's own render semantics against `A125_answer_key.json`:

| | before round 1 | after round 2 | **after this work** |
|---|---|---|---|
| correct | 118 | 150 | **230** |
| wrong | 23 | 1 | **1** |
| must-be-blank violated | 31 | 0 | **0** |
| still missing | - | 94 | **14** |

**+80 boxes.** The one remaining wrong value is REMARKS holding the
overflow-loss notice, which is deliberate behaviour and was flagged, not fixed.

## The fixes

### RC-B - a placeholder is not a value

**Root cause, pinned exactly - and it is NOT what I first wrote.** My earlier
note said `(None)` "is not read as an absence". That was measured against
`fact_answered`, which is the wrong door. `interpret_answer` handles it fine.

The real defect is one line. `_is_empty_llm_value` already owned this question
and already held the vocabulary (`_LLM_EMPTY_SENTINELS`), but its membership
test is a BARE exact match:

```python
if value.strip().lower() in _LLM_EMPTY_SENTINELS:   # "None" -> caught
                                                    # "(None)" -> not caught
```

**One pair of parentheses was the whole difference** between a blank box and the
literal string `(None)` printed on two rows of a signed application.

**Fixed at the source, not just backstopped.** New `answer_semantics.
is_placeholder_text` is the one door for "does this text say anything"; both the
absorb-time check and a new Guard 13 call it.

**It is deliberately NARROWER than `_ABSENCE_TOKENS`, and that is the whole
design.** That set contains `0`, `zero`, `no` and `n`, because it reads a
HUMAN's answer to a KNOWN fact and has the fact's declared kind to tell it when
a zero is real. A form box has no such context: `$0` reserved on a claim, `0`
square feet open to the public and `N` on every Y/N question are values a broker
signs. Reusing the absence vocabulary would have deleted them.

Also deliberately NOT in the set, though all were drafted into it: `see
attached`, `see schedule` (C22 records that amount boxes legitimately hold
"Statutory", "Included", "See schedule"), `pending`, `not required`. The test is
"carries no information", not "sounds unhelpful".

### RC-A - a single-entity fact model against N-row ACORD tables

**The mechanism, traced end to end.** `_resolve_applicant_website` returned the
package-level `applicant_website` scalar for **every row letter A-N**. Guard 2
then de-duplicated rows B and C as echoes of row A. So one scalar was broadcast
across the table and all but one copy deleted - leaving the wrong entity's
website in the row that survived and the right entity's box empty.

**The fix is ADDITIVE, not a reshape, and that decision is the important one.**
`additional_named_insureds` has ~20 consumers across the scorer, the validators,
the questionnaire and the stamper. Changing it from `[string]` to `[dict]` would
have put every one of them at risk. The codebase already has the answer: it
carries both `locations` AND `property_locations`. So seven new facts ride
alongside and nothing existing changes shape.

**`_SCHEDULE_REGISTRY` was the obvious door and was the WRONG one.**
`_resolve_schedule_row_inner` returns `None` - an owned blank - when its list
fact is missing. Binding these families through it would have darkened every one
of those boxes on every session extracted before v22, **including the ones gap
fill gets right** (test 2 filled row B's FEIN, SIC and NAICS correctly from call
2 alone). The new resolvers return `_SCHED_SKIP` when their fact is absent, so a
pre-v22 session behaves exactly as it does today. Pinned by a test.

### RC-C - a deterministic floor under the GENERAL INFORMATION block

**The topic is derived from ACORD's own question text, never from the field name
and never from the question CODE.** The code is not unique: ACORD 125 carries
both `CommercialPolicy_Question_ABBCode_A` ("Has business been placed in a
trust?") and `CommercialStructure_Question_ABBCode_A` ("Any area leased to
others?"). Matching on the code would have answered a premises question with a
trust answer, on all four premises rows.

Verified across all 17 schemas: matching whole tooltips produced one collision;
matching `_compliance_question_text` produces **zero**. Both are pinned by a
standing test that sweeps every schema.

**The absence contract is deliberately conservative.** When the fact exists but
holds no entry for a topic, the resolver returns `_SCHED_SKIP`, not `None`.
Returning `None` would make the box an owned blank and finally make "silence is
not a No" deterministic - it is the stronger fix and it is the one I did not
ship, because asserting that a document is silent because extraction did not
mention it, before knowing how often extraction simply misses, trades a flapping
box for a permanently empty one. **Measure call 1's recall on a live run, then
tighten.**

**Evidence is required, not just an answer.** The shipped compliance pass demands
a grounding quote for every Y/N on every form; a deterministic answer that
skipped it would be a hole in the same rule on the same boxes. No quote, no
assertion - the gated LLM path runs exactly as today.

### RC-D, RC-E, RC-G

- **RC-D**: `other_named_insured_operations` is its own fact and its own
  resolver, which steps aside when there is no second insured so
  `_resolve_party_scoped_row` keeps owning that case.
- **RC-E**: the additional-interest COUNTRY box is an owned blank even with no
  fact. Swept all 17 schemas - every country box in the product is an
  AdditionalInterest one (4 boxes), `_ACORD_FIELD_RULES` maps it to `None`, and
  nothing else can supply it, so a value there is provably not read from the
  document. **Correction to my earlier note: the "246 boxes across 13 forms"
  figure lumped in STATE codes, which are legitimately filled. The real invented-
  code surface here is 4 boxes.**
- **RC-G**: abbreviation hints on the FT / PT columns, taken from the ACORD
  form's own printed label (`# FULL TIME EMPL`) rather than invented.

## Two mistakes caught during the work, both by my own tests

1. **My anti-rot test found a vocabulary I did not know existed.** Asserting
   "pdf_service must not carry its own placeholder list" failed immediately -
   on `_LLM_EMPTY_SENTINELS`, which predates this work and turned out to be the
   door that SHOULD have caught `(None)`. That reframed RC-B from "add a guard"
   to "fix the bare membership test", which is a better fix.
2. **Registration is not wiring.** All seven resolvers were registered in
   `_AUTHORITATIVE_BLANK_RESOLVERS`, reported as owning their boxes, and stamped
   NOTHING - because that registry only closes the GAP-FILL door. A resolver
   that produces a VALUE must also be wired into `_deterministic_map`. The
   harness caught it: 66 boxes moved off call 2 and the score did not move.

## What is still open

| | Boxes | Why |
|---|---|---|
| **RC-F** page-one carrier / QUOTE / Inland Marine | 3 | needs page-level document classification; parked with reasons |
| Row A's own phone / GL code / member count | 3 | row A has no per-entity fact by design - needs its own scalars |
| Contact phone-kind indicators | 2 | `_resolve_applicant_contact` already owns that regex; extending it is a separate change |
| `InstallationRepairWork` percentages, loss-history year count | 3 | no fact exists |
| Q4 "other insurance with this company" | 1 | **traced, and it is correct.** `_resolve_page_one_receiving_carrier` owns it: the question is *"any other insurance with THIS COMPANY"* and is unanswerable until the receiving carrier is known. The carrier box is an owned blank on this package, so Q4 is too - the same chain effect test 1 recorded as I5. It resolves the moment RC-F does, and the existing stricter owner correctly outranks the new disclosure floor |
| Multiple incidents of one disclosure topic | - | the fact allows it; the resolver fills row A only. No document in hand states two, and D22 says do not build against a fixture that does not exist |

## The honest limit of all of this

**Every number above assumes extraction works.** The harness supplies the seven
v22 facts by hand and measures the STAMPER. What is proven is that when call 1
produces these facts, the form is right. What is NOT proven is that call 1
produces them - that needs one live run on the bumped prompt, and it is the
only thing that can prove it.

---

# HOW TO CHECK EXTRACTION - 22 Sep 2026

Every number in this file above this line assumes extraction works. That
assumption is where the 21 Sep defects actually lived, and nothing in the repo
measured it: `score_gap_fill.py` grades LLM call 2, `score_form_fill.py` grades
the finished PDF, and **nothing graded LLM call 1.**

That gap has a specific shape. The second named insured's website was extracted
correctly, stored correctly, spelled correctly, and attached to the **wrong
company**. On the form it is indistinguishable from a clean fill. No
value-level metric can see it, because every check in the pipeline asked *"is
this value right?"* and none asked *"is it right FOR THIS ENTITY?"*.

Two instruments now answer that, and they are deliberately complementary.

## 1. `services/fact_relationships.py` - NO answer key

Checks the facts against **each other**, so it runs on a real client package
where no key exists - which is the only place it matters.

| code | severity | what it catches |
|---|---|---|
| `IDENTITY_FILED_UNDER_THE_WRONG_PARTY` | warn | a website or email whose own domain names a DIFFERENT known party better than the one it is filed under |
| `SHARED_FEIN` | error | one legally unique identifier under two parties - a cross-row copy, with no innocent explanation |
| `ORPHAN_DETAIL_ROW` | error | a detail row describing a party the roster does not name |
| `DISCLOSURE_CONTRADICTS_DETAIL` | error | "has subsidiaries: N" beside a subsidiary row |
| `UNKNOWN_DISCLOSURE_TOPIC` / `BAD_DISCLOSURE_ANSWER` / `UNKNOWN_ORG_ROLE` | error | a value outside the declared enum - no resolver can place it, so it silently never reaches the form |
| `EVIDENCE_QUOTE_NOT_IN_DOCUMENT` | error | a grounding quote the document does not contain - a fabricated warrant for an assertion on a legal form |
| `COLUMN_SHAPE` | warn | a 7-digit account number in a 9-digit FEIN column |

**It is built to stay quiet.** Pinned by adversarial tests written first: a
group genuinely running every subsidiary off one domain is silent; affiliates
sharing a switchboard are silent; no raw text means no opinion about quotes.
Only the FEIN - which cannot legitimately be shared - is treated as proof.

**A bug in its first version is worth recording.** The domain check did not
fire on the very defect it was written for, because a real domain welds the
name together (`cedarbluffsteel`) and a token-set intersection against
`{cedar, bluff, steel}` is **empty**. Substring matching, not set intersection.
Pinned by `test_a_concatenated_domain_still_matches_its_owner`.

It runs automatically inside `dump_a125_run.py`, so the next dump prints its
findings without anyone remembering to ask.

## 2. `scripts/score_a125_extraction.py` - against the kit's key

```bash
python3 backend/scripts/dump_a125_run.py <session_id> > a125_run.json
python3 backend/scripts/score_a125_extraction.py a125_run.json
```

**ENTITY-CELL is the number to steer by**: of the cells that should carry a
value, how many carry the right value **for the entity they are attached to**.
Rows are matched by NAME, never by position, so a correct table in a different
order scores 100% and a table whose columns were mixed does not.

## Why ENTITY-CELL and not a fill rate - demonstrated

Two fixtures: the kit's facts extracted perfectly, and the SAME values with
row B's website on row A, two FEINs swapped and two contact phones swapped.

| | perfect | mis-attributed |
|---|---|---|
| scalars correct / wrong / missing | 11 / 0 / 0 | **11 / 0 / 0** |
| rows found | all | all |
| **ENTITY-CELL** | **89/89 = 100%** | **84/89 = 94.4%** |
| **cross-entity cells** | **0** | **4, each one named** |
| relationship findings (no key) | clean | the website, caught |

**The scalar line is identical in both runs.** Every value was found. A fill
rate, a coverage percentage and a "wrong value" count all report a perfect
extraction. Only ENTITY-CELL and the relationship checks see that four cells
describe the wrong company.

## What to do with it on the next run

1. Regenerate the kit (`python3 backend/scripts/make_a125_test_pdf.py`) - the
   extraction prompt is v22 now, so the cache is cold either way.
2. Upload, generate ACORD 125, dump the session.
3. Run the extraction grader FIRST, before looking at the form. If ENTITY-CELL
   is low, the form's score is not worth reading - fix the attribution first.
4. `relationship_findings` in the dump is the half that will keep working on
   real client packages once the kit is retired.

**Still not covered, honestly:** neither instrument can catch a value that is
mis-attributed *consistently* with nothing to contradict it - a document that
states one website and one party, read onto the wrong one, looks correct from
every angle. That needs the document, not the facts.

## BASELINE MEASURED on the test-2 session (v21 extraction), 22 Sep

Run against session `9b55a690` - the one that produced the TEST 2 form. It was
extracted at **v21**, so the six new facts do not exist yet. That is the point:
this is the "before" line the v22 re-run is measured against.

```
SCALARS   9 correct / 1 wrong / 1 missing
  WRONG    operations_description   want 'Licensed mechanical and structural...'
                                    got  'Commercial mechanical contracting...'

LISTS                        rows    cells  right  cross  blank
  additional_named_insureds   2/2        2      2      0      0   (+1 unexpected)
  named_insured_details       0/2       17      0      0     17
  applicant_contacts          0/2        5      0      0      5
  additional_interests        0/2        8      0      0      8
  property_locations          5/5       34     24      0     10
  organization_relationships  0/2        4      0      0      4
  disclosure_answers         0/14       14      0      0     14

  ENTITY-CELL  26/84 = 31.0%   cross-entity 0   blank 58

RELATIONSHIP CHECKS (no answer key)
  [warn] IDENTITY_FILED_UNDER_THE_WRONG_PARTY
         'www.cedarbluffsteel.com' is filed under Meridian Ironworks &
         Mechanical, LLC but its domain names 'Cedar Bluff Steel Fabricators'
```

**Three things this proved on the first run, none of them by argument.**

1. **The relationship checker caught the real J4 defect** on the real session,
   automatically, with no answer key and nobody looking for it.
2. **RC-G is confirmed, precisely.** `property_locations` extracted 5/5 rows and
   24 of 34 cells - and the 10 blanks are **exactly** `full_time_employees` x5
   and `part_time_employees` x5. Every word-headed column from that same
   riffled table (REVENUE, OCCUPIED, PUBLIC, TOTAL) landed on every row. The
   only two that failed are the only two whose header is an abbreviation.
   That was a hypothesis yesterday; it is a measurement now.
3. **J11 is an EXTRACTION defect, not a stamping one.** `operations_description`
   holds the general paragraph, not the primary-operations one, in the FACT.
   No amount of stamper work could have fixed it.

**And it corrected me once.** The grader first reported `property_locations` at
19/39 with 20 blanks, because I had it grading `city` and `state`. Those are
NOT declared columns - the `address` string carries the whole address and the
stamper parses it - so ten of those "blanks" were correct by design. A grader's
expectations are a fixture and get the same scrutiny as the code.

**Read the 31.0% correctly:** 48 of the 58 blanks are the six v22 facts, which
could not exist on a v21 extraction. This number is the floor, not a verdict.

## VERIFICATION - final

| | |
|---|---|
| Full suite | **9601 passed / 2 failed / 18 skipped** |
| The 2 failures | both documented pre-existing: `test_arq_acord125_missing_only` (the `httpx` ImportError) and `test_confidence_score_covers_every_label` (the `int()` truncation, Brent's call under D6) |
| New tests | `test_a125_complete_fix_21sep.py` (96), `test_fact_relationships_21sep.py` (18) |
| Existing tests corrected | 4 version pins (v21 -> v22) and 2 claimant-census entries - in every case the TEST's subject was preserved and only the incidental value moved |
| Deterministic layer, v22 facts supplied | **231 correct / 1 wrong / 0 blank violations** (from 150/1/0) |
| Deterministic layer, NO v22 facts (every existing session) | **150 / 1 / 0 - unchanged**, with MORE boxes reaching call 2 than before |
| Cross-form sweep | no form loses a box; six gain (125, 126, 127, 140, 160, 28) |

## A defect the suite found in THIS work, and it is the same mistake as last time

The `ProducerIdentifier` fix unblocked three boxes on ACORD 127 -
`AdditionalInterest_Item_VehicleProducerIdentifier_A/_B` and the boat one -
**that no fact can fill.** A widened substring opened an invention surface while
closing one. That is verbatim the RC5 mistake from round 2, repeated three weeks
later by the same reasoning.

`test_call2_retrieval::test_family_grouping_collapses_mixed_batches` caught it -
not because it knows anything about additional interests, but because four extra
fields reaching gap fill changed the batch composition enough to erase its
margin. **A test that fails for a reason it was not written for is still the
suite doing its job.**

Isolated properly rather than guessed at: stashing `pdf_service.py` made it
pass, then disabling ONLY the nonfillable allow made it pass with the resolvers
still live - which proved the resolvers innocent and named the cause exactly.

Fixed twice over:
1. The allow now names only boxes a resolver can actually answer. Vehicle, boat,
   aircraft and scheduled-item numbers stay blocked - the honest state, because
   we cannot fill them.
2. `AdditionalInterest_Item_LocationProducerIdentifier` is
   **deterministic-or-blank**, like the country box, because it wants OUR
   location numbering - the index into the premises schedule this application
   prints - which no amount of reading the document produces.

**Standing lesson, now recorded twice: when a name-substring block comes off,
count what it was holding back. A box is only unblocked when something can
fill it.**

---

# ADVERSARIAL REVIEW - 22 Sep 2026

Seven reviewers over the real diff, every finding then attacked by an
independent skeptic instructed to refute it. **46 raw findings, 32 confirmed.**
Four were critical. The review cost more than the work it reviewed and was
worth it: two of the four are defects the fix REINTRODUCED, and two are in code
that shipped the day before.

## Fixed

### C1 - a detail row was read by POSITION, not by entity

**The worst finding, and the most embarrassing kind.** Row B is the one place on
ACORD 125 where the NAME comes from one fact (`additional_named_insureds`) and
every other column comes from another (`named_insured_details`). Reading the
second by ordinal assumes the two lists keep the same length and order forever,
and three separate mechanisms break that:

* `_drop_transaction_party_rows` filters the ROSTER and not the detail - the
  codebase records that firing live on 2026-09-05 - so one dropped
  certificate-holder shifts every detail row up by one;
* `_merge_list_fields` unions each list across chunks independently and
  `_natural_id_keys` has no `name` subkey, so two partial rows for one party
  never merge and the lists desync;
* the model can simply answer in a different order.

Any of those prints one insured's FEIN, SIC, website and address **under
another insured's name**. That is RC-A's own *"Fate 1 is the dangerous one"* -
reintroduced by the fix for it.

The reviewer quoted my own instrument back at me: `score_a125_extraction.py`
says *"rows are matched by NAME, never by position"*. **I got it right in the
grader and wrong in the code.**

Fixed: matched through `normalization.strict_entity_key`. Verified against
reversed order, applicant-prepended, and a roster entry with no detail row -
which is now an owned blank rather than its neighbour's values.

### C2 - a partial contact row DELETED correct scalars

`applicant_contacts` declares every column `string or null`, so a partial row is
permitted by construction and is the ordinary case. `_detail_cell` returns an
owned blank the moment a row exists but a column is empty - so a row carrying
only a name turned populated `contact_phone` and `contact_email` into empty
boxes that gap fill was never asked about.

Every OTHER detail resolver was already guarded: the named-insured one offsets
past row A, the premises one has a structural pre-v22 escape. This was the only
one that claims row A, and row A is the only place a competing populated scalar
exists. Row A's PRIMARY columns now fall back to their scalars; the SECONDARY
boxes keep their owned blank, because that is the defect the row-A claim exists
for and no scalar can fill them.

### C3 - the deterministic disclosure path was WEAKER than the LLM path

`_resolve_disclosure_answer` requires an `evidence_quote` and **cannot verify
it** - a resolver is handed `(field, facts)` and never sees the document. The
evidence gate blanks an ungrounded Y/N from gap fill; the same value with the
same invented quote stamped straight from a fact.

Reproduced: five `N` answers quoting a sentence nowhere in the document stamped
fraud/arson, abuse & molestation, declined coverage, judgment-or-lien and
bankruptcy on a declarations-only package. **"Blank is not No" failing on the
five most material questions on the form.**

Fixed at the merge tail - the one place holding both the facts and the text -
through `fact_relationships`, which already owns the question. An unverifiable
warrant is dropped before it can answer anything. Silent when there is no text:
absence of the document is not evidence against the quote.

### C4 - RC5 never worked, twice over

`_resolve_attachment_indicator` shipped on 21 Sep, returns `"Y"` correctly, and
**has never ticked a box on any form.** Measured: resolver -> `'Y'`,
`_deterministic_map` -> `'UNMATCHED'`, `compute_form_gaps` -> `None`.
Registration in `_AUTHORITATIVE_BLANK_RESOLVERS` only closes the GAP-FILL door.
That is the same "registration is not wiring" defect that hid this session's own
seven resolvers - in code that shipped a day earlier.

And it was broken a second, independent way: `_package_form_ids` was built from
`session["selected_forms"]`, **a key no writer puts at the top level of a
session row.** Verified against a real session: `selected_forms` absent,
`selected_form_ids` present. So the list always collapsed to `[this form]` on a
first generation and the boxes could only ever tick on a RE-generation.

Both fixed, and pinned by a test that fails if `form_service` ever reads a
session key nothing writes.

## Still open - roughly 28 confirmed findings

Not yet addressed. The headline ones:

| | |
|---|---|
| Guard 12b deletes every extracted resolution the document does not date | high |
| Guard 12a blanks short-but-substantive explanations; Guard 9 then deletes the affirmative | high |
| `_ENTITY_WORD_TO_INDICATOR` is a second, weaker copy of `normalization.entity_family` | high |
| The `named_insured_details` "name" instruction contradicts itself and licenses the applicant into the list | high |
| Several v22 columns are dead behind older owners (`fax`, `member_manager_count`) | medium |
| `disclosure_answers` and `organization_relationships` answer the same ACORD question with no reconciliation | medium |
| **D6:** the disclosure floor systematically raises `confidence_fill_rate` | medium |
| `_DISCLOSURE_TOPIC_PHRASES` is in practice an ACORD 125 table - 19 of 322 disclosure boxes across 9 forms | low, but honest |

## The standing lesson, now earned three times in two days

**Registration is not wiring, and an offline probe proves the function, never the
seam.** CLAUDE.md has recorded that since the declarations-index arc. It has now
caught: round 2's attachment resolver (registered, never called), this session's
seven resolvers (same), and a package list reading a key nobody writes. Every
one of them passed a unit test against the function.

*"Not one of the 141 new tests crosses the seam - they all call the resolver
functions directly"* was the reviewer's line, and it was right.

## REVIEW ROUND 2 - nine more confirmed findings fixed

| # | Finding | Why it mattered |
|---|---|---|
| **R1** | A dependent box with no value was claimed as an owned blank | Extraction found a judgment/lien and quoted it; the explanation column was null, the resolver claimed the box, Guard 9 then deleted the correct `Y`. A material disclosure shipped as a blank question. Silence in a fact is not a statement that a box is empty - the resolver's own docstring said so and the role branch did not honour it |
| **R2** | Guard 12b read the DATE box | *"A resolution nobody dated has not occurred"* is true of ACORD's LAYOUT, not of documents. It deleted every real undated remedy and made `disclosure_answers.resolution` dead by construction. It now reads the SENTENCE through `answer_semantics.describes_incomplete_action`, which is two-sided - and catches the case the date test never could: a DATED resolution whose own words deny completion |
| **R3** | Guard 12a's tail test was a LENGTH proxy | *"...judgment or lien during the past five (5) years? Lien filed 03/2024."* carries a lien and a date in three long tokens - below the threshold - so the whole value went and Guard 9 deleted the `Y`. Containment now: does the tail add any token the question did not already contain |
| **R4** | `_ENTITY_WORD_TO_INDICATOR` was a weaker copy of `normalization.entity_family` | It silently dropped six of the eight words the v22 schema tells the model to use - "Not For Profit", "S Corporation", "LLP", "Limited Partnership", "Sole Proprietorship", "Association". Row A ticked them correctly; row B printed a name with no entity type and the box was removed from gap fill. Deleted; both rows read one door |
| **R5** | The schema licensed the applicant into the detail list | *"must match a name in additional_named_insureds **or applicant_name**"* followed two clauses later by *"The FIRST named insured is NOT in this list"*. A model obeying the first half puts the applicant at index 0 |
| **R6** | Three v22 columns were extracted, paid for and thrown away | `phone_kind`, `member_manager_count` and the interest's `fax` were intercepted by older whole-FAMILY resolvers that blank by name shape. The detail loop runs early now - a fact carrying THIS row and THIS column is strictly narrower than a family default, and only the conflicted-fact withhold outranks it |
| **R7** | `phone_kind` had no consumer at all | It now ticks its own box - and a kind with NO number ticks nothing, which is the live J6 defect ("a BUS tick sits on an empty phone") |
| **R8** | Row A of the applicant table had no fact for three of its columns | `applicant_business_phone`, `applicant_gl_class_code`, `applicant_member_manager_count` - plus the two sales-split percentages. Added as a ROW-A resolver, never a substring rule: a substring matches every row letter, which is the RC-A broadcast defect |

## Where the deterministic layer finished

| | before round 1 | after round 2 | after the fix | **after the review** |
|---|---|---|---|---|
| correct | 118 | 150 | 232 | **241** |
| wrong | 23 | 1 | 1 | **1** |
| must-be-blank violated | 31 | 0 | 0 | **0** |
| missing | - | 94 | 12 | **3** |

**241 of 245, and the 3 that remain are exactly the parked RC-F boxes** - CARRIER,
NAIC and Commercial Inland Marine, which need page-level document
classification. Nothing else on ACORD 125 is unreachable.

The one remaining wrong value is REMARKS holding the overflow-loss notice,
which is deliberate behaviour and was flagged rather than "fixed".

## FINAL VERIFICATION - 22 Sep 2026

| | |
|---|---|
| Full suite | **9706 passed / 2 failed / 18 skipped** |
| The 2 failures | both documented pre-existing (`httpx` ImportError; the `int()` truncation that is Brent's call under D6) |
| Deterministic layer, v22 facts supplied | **241 correct / 1 wrong / 0 blank violations**, 3 missing |
| The 3 missing | CARRIER, NAIC and Commercial Inland Marine - exactly the parked RC-F set |
| Deterministic layer, NO v22 facts (every existing session) | **151 / 1 / 0** - one BETTER than the 150 baseline, no regression anywhere |
| Cross-form sweep | **no form loses a box**; eight gain (101, 125, 126, 127, 133, 140, 160, 28) |
| New tests | `test_a125_complete_fix_21sep.py` (134), `test_fact_relationships_21sep.py` (18) |

## THE PATTERN ACROSS ALL THIRTEEN FIXES

Not one of the thirteen defects the review found was a logic error. Every single
one was **ordering or ownership**:

* a resolver registered but never wired (twice - round 2's attachment fix, and
  this session's own seven);
* a specific fact sitting behind a family default (three columns);
* a scalar read by POSITION where an identity key existed (the cross-entity one);
* a guard reading the wrong signal (the date box instead of the sentence);
* a package list reading a session key nothing writes;
* a second vocabulary quietly narrower than the door it duplicated.

Every one of those functions was correct in isolation, and every one had a
passing unit test. **CLAUDE.md's standing lesson - an offline probe proves the
FUNCTION, never the SEAM - earned its keep four separate times in two days.**

The reviewer's sharpest line was the true one: *"Not one of the 141 new tests
crosses the seam - they all call the resolver functions directly."* The tests
that now exist for the attachment wiring, the package-list key and the
sparse-row shadowing are seam tests, and each of them fails on the code as it
stood yesterday.


---

# ROUND 2 - the Front Range kit, graded against the CLIENT's own answers - 28 Sep 2026

Round 1 graded every run against an answer sheet I wrote (the Meridian kit), so a
box I misunderstood scored "correct" against my own mistake - the prior-carrier
OTHER code box is the proof (F5 below). Round 2 grades against the answer sheet
the client wrote: `125_reference/ACORD 125 - field completition 8-19-26.docx`,
the Front Range Electrical Contractors LLC case.

| asked | where it landed |
|---|---|
| 1. A ~100-page kit, table-heavy, fuzzy, hard to extract | `fr125_test_data/` - built by `backend/scripts/make_fr125_test_pdf.py` from `_fr125_data.py` |
| 2. Check the rules we wrote still hold on a NEW package | `backend/scripts/audit_125_rules.py` - 23 rules, no answer key needed |
| 3. Round 2 results in this file, in the round 1 format | `backend/scripts/report_125_run.py` writes the section; **TEST 1 RESULTS below are pending the live run** |
| 4. Grade on meaning, not word for word | done in `score_form_fill.py`, for narrative boxes only - reasoning below |

## 1. The kit - `fr125_test_data/`

**One upload: `FR125_front_range_package.pdf`, 100 pages.** 49 content pages (tables,
decs, schedules), 4 scanned image pages with NO text layer, 1 landscape page, 47
pages of policy wording - roughly the shape of a real package.

**The answers are the client's.** Carrier = the carrier RECEIVING the submission
(Granite Arch, named only on the cover letter); NAIC blank (never stated for that
carrier); policy number blank; status QUOTE; premium blank; proposed term
10/01/2026-10/01/2027; prior carrier = only the 2025 year the documents
substantiate; one auto claim, paid $4,850.

**Answer key: all 548 boxes decided.** 106 must carry a value (6 of them graded on
meaning), 242 must stay empty because nothing is stated, 54 must stay empty because
a rule says so, 134 belong to rows with no entity, 12 not scored. Only the 40
Additional Interest boxes fall to the default, correctly - none is documented.

### What makes it hard

| technique | where | what it tests |
|---|---|---|
| **scanned page, no text layer** | questionnaire p.2, faxed old loss run, articles, W-9 | OCR. Questions 8-15 exist ONLY on the scan - a miss there is OCR's first |
| **X in a column** | questionnaire p.1 | an answer read from its position under YES / NO |
| **abbreviated headers** | premises table: FT, PT, OCC SF, PUB SF, TOT SF, LSD, CL, INT | RC-G beyond the two columns fixed on 21 Sep |
| **two-line headers** | work-in-progress schedule ("CONTRACT" over "VALUE") | a header word alone on its line |
| **landscape page** | statement of values | wide-table reading order |
| **teletype** | GL declarations (`P O L I C Y  N O  G L - 1 2 3 4 5 6`) | letter-spaced text repair |
| **riffled cells** | premises, profile, job sites, auto loss run | a description running under the next column |
| **two-column drift** | contacts, operations | column reflow |
| **dot leaders** | applicant profile | label and value 70 characters apart |
| **spelled three ways** | revenue ($4,250,000 / "about $4.25 million" / 4,250 in $000), employees, areas, start date | normalisation |
| **placeholders in the source** | "--", "N/A", "(none)" in address line 2, fax, member count | they must end up EMPTY, never printed |
| **one claim, two valuations** | current loss run (closed, $4,850) + 2024 fax (open, $3,200 / $1,650) | latest wins, never two rows |

### The traps - 29 decoy values in 22 scoped boxes, and 104 values that must appear nowhere

Every decoy is printed in the document and forbidden only in the boxes it would be
wrong in: the current carrier and its NAIC on page one, the expiring policy number
and premiums on a quote, the current term as the proposed term, the carrier's
website and phone in the applicant's boxes, an 8-digit state tax account and a
7-digit USDOT as the FEIN, the GL class as the NAICS, the projected 2026 revenue,
the payroll and the **work-in-progress backlog ($6,451,100)** as revenue, total
headcount (20) as full-time, **6 agency temps** as part-time, the old fax's paid and
reserve, the WC carrier in the umbrella's OTHER column, the landlord as a named
insured or interest, and another agency's customer id. 45 customer job sites and
**28 certificate holders** (company names and addresses printed next to the word
"insurance") must never become a premises, a named insured or an interest.

### The kit is proved fair before it is used

* every expected value is printed in the text layer (or, for the 8 scanned-only
  facts, drawn on the scan) - a trap that is not in the document tests nothing;
* every decoy is printed;
* the scanned-only facts do NOT leak into the text layer - they are reachable by
  OCR alone, or the OCR test is fake;
* the key scores itself 106 / 106, and an EMPTY form raises no violation;
* the two scans were looked at, not assumed: skewed, speckled, fax-banded, legible.

## 2. "Are the rules we wrote still applicable?" - `audit_125_rules.py`

A new client package has no answer key, and that is exactly where a rule written
for one fixture can quietly stop holding. So every rule is stated WITHOUT the right
answers - the form against the documents and against itself.

**Every rule also says whether this package EXERCISED it.** A package with no
losses never tests the loss-total rule; the report says "not exercised" instead of
counting a pass. That is the honest half of "still applicable".

| id | rule | source |
|---|---|---|
| C1 | Status is QUOTE, and only QUOTE | client |
| C2 | Page-one carrier is the carrier RECEIVING the submission (a REVIEW, not a fail, on a renewal with the incumbent) | client |
| C3 | NAIC only if verified - and it belongs to the NEAREST carrier name | client |
| C4 | Policy number blank on a new-business quote | client |
| C5 | Premium blank at submission stage unless known | client |
| C6 | Proposed dates are the NEXT term | client |
| C7 | Prior carrier: only what the documents substantiate | client |
| C8 | "No known losses" is never converted into loss history | client |
| C9 | Loss total is the PAID amount (ACORD tooltip) | client |
| C10 | Blank is not No - unanswered questions listed as UNRESOLVED | client |
| C11 | A Yes carries its explanation / detail | client |
| C12 | A No (or blank) leaves its whole block empty | client |
| C13 | Other named insureds only if the documents state them AS insureds | client |
| C14 | Additional interest only if documented AS one | client |
| C15 | Form edition 2025/03 | client |
| C16 | Every Yes / No answer has its own sentence in the documents (needs a dump) | client |
| S1 | No placeholder reaches a box | standing |
| S2 | Nothing signs or attests for a person | standing |
| S3 | Every code box holds the shape its ACORD tooltip declares | standing |
| S4 | Every printed value is found in the documents (the made-up detector) | standing |
| S5 | No entity printed twice in one table | standing |
| S6 | public area <= occupied <= building | standing |
| S7 | Dates are possible | standing |

**The audit imports the product's own rule tables** - the question dependent
blocks, the explanation pairs, the disclosure topic map, the loss-overflow marker,
the placeholder door - so it can never disagree with the stamper about which box
belongs to which question.

### Measured

| run | result, with NO key |
|---|---|
| Meridian test 1 (21 Sep) | **3 fail**: Renew ticked instead of Quote; a Yes on "has subsidiaries" with nothing named; "(None)" printed as an address - exactly the defects round 1 fixed |
| Meridian test 2 | **2 fail**: the status pair, and two placeholders |
| Meridian test 5 | **clean** - 21 pass, 1 unanswered question listed for the client |
| a perfect Front Range form | **0 fail, 0 review** - no false positives |
| 22 defects planted into that perfect form | **22 of 22 caught**, on the real 100-page text |

**What it cannot see, and says so:** a REAL value in the WRONG box. The backlog as
revenue and the agency temps as part-time were both planted - the audit passes
them, because both values are genuinely printed. That class needs the answer key
(this kit) or the extraction relationship checker. And test 5's made-up
"foreign operations = Y" is only catchable with a session dump: rule C16 reads
extraction's own evidence sentence for each answer, which a bare PDF does not carry.

## 3. How round 2 results are reported - `report_125_run.py`

One command writes the section in the round 1 format, led by the four numbers asked
for:

| number | what it counts |
|---|---|
| **Correct** | split into EXACT, CODE (ACORD's code written as its word) and BY MEANING, so nothing is hidden |
| **Wrong** | the box contradicts the documents; PARTIAL = right but incomplete, counted wrong and shown apart |
| **In the documents, missing from the form** | split by where it was printed (a scanned page = OCR first) and, from a dump, by which pass owned the box |
| **Made-up values** | a value where the documents state NOTHING - kept apart from a box a RULE owns and from a trap value in its trap box (a real value, the wrong role) |

Plus the round 1 scorecard, row-cell, extraction ENTITY-CELL (read it before the
form), the 23-rule audit, and every box that is not right, with the reason.

## 4. Meaning, not word for word - my answer

**Yes - for narrative boxes only.** A model rewrites a sentence; it never needs to
rewrite a FEIN. A "close enough" number is a wrong number. So meaning-matching is
allowed on the boxes ACORD itself marks as free text ("Enter text:" AND a
Description / Explanation / Remark / Operations name) - on this kit, 6 of 106. Every
identifier, amount, date, code, name and address stays exact after formatting.

**The old scorer was wrong in BOTH directions** - and the Meridian key had already
promised meaning-grading on 21 boxes that the scorer never read:

* it passed wrong numbers: `$73,410` = `$734,100`, `1711` = `17110`,
  `238210` = `2382101` (any 4-character substring counted). Building this kit, it
  flagged the key's OWN correct FEIN `12-3456789` as the forbidden USDOT `3456789`;
* it failed good paraphrases: "Applicant stores limited quantities of common jobsite
  adhesives/solvents in approved containers" scored WRONG against the client's
  sentence.

**Now, three tiers in order:**

1. **exact** - after formatting: `12-3456789` = `123456789`, `06/15/2014` =
   `June 15, 2014`, `Ste 310` = `Suite 310`. Word containment only on WHOLE words
   and only when both sides carry the same numbers.
2. **code** - `AN` = `Annual`, `A` = `annual`, read from ACORD's own tooltip table
   for that box, never typed.
3. **meaning** - narrative boxes only, and ALL four must hold: 70% of the expected
   content words present; at least half of what the box says is grounded in the
   expectation (a pasted page contains every word and says nothing); no word negated
   on one side and affirmed on the other ("stores flammables" vs "no flammables");
   no invented number of two digits or more.

Measured both ways: 12 of 12 hand cases, including the two operations paragraphs
swapped either way (a real trap in this kit) and a paraphrase that drops the
"no utility-line construction" exclusion (PARTIAL, counted wrong).

**Re-scored on the five real forms from round 1:** six verdicts moved. Five are the
audit box - `Annual` in a box whose tooltip says `A - annual`, now correct. The
sixth exposed a stale key (F4).

## Found while building round 2 - all fixed

| # | what | kind | fix |
|---|---|---|---|
| **F1** | **`answer_semantics.is_placeholder_text("--")` was False** - also `-`, the two long dashes, `---`. It stripped the dashes as decoration, found nothing left, and answered "already blank - not our business". A printed dash is not a blank. `_LLM_EMPTY_SENTINELS` and `placeholder_detector` also passed it, so **no net anywhere caught the most common "nothing here" mark on a dec page** | **product** | the one door now reads pure decoration as a placeholder; whitespace still is not. Pinned both ways (dashes blank; `-5`, `$`, `%`, `#1`, `0`, `N` untouched) |
| F2 | the scorer's substring rule passed wrong numbers | grader | the tiers above |
| F3 | the scorer's `norm` expands address abbreviations, so the audit code `S` read as "south" and `N` as "north" | grader (mine, caught before use) | codes and Y/N compare literally |
| F4 | Meridian key expected REMARKS to hold the applicant's remark alone. `_resolve_loss_overflow_remark` (2 Sep) correctly adds the 4th loss the 3-row grid cannot print. The old substring rule hid the stale key | key | expectation now includes the overflowed loss |
| **F5** | **I was wrong on 21 Sep.** "`PriorCoverage_OtherLine_LineOfBusinessCode_A` takes the line as the document prints it (`Commercial Umbrella`). Key corrected." ACORD's tooltip says **"Enter code"**. The repo has no ACORD line-of-business code table | key | NOT SCORED in both kits until a code table exists - pinning either a phrase or an invented code would be guessing |
| F6 | the audit's first role check used a character radius, so a role word two lines away - or on the previous page ("Insured vehicle rear-ended...") - was credited to the wrong party, and "does not require the landlord to be named as an additional insured", wrapped over two lines, lost its "not" | audit (mine) | structural ownership: same line, a heading above, or the record below; wrapped sentences rejoined; the NAIC belongs to the NEAREST carrier |

F1 can move a score slightly: a box holding only "--" no longer counts as filled.
Direction is correct; size is a handful of boxes at most. Tell Brent with the next
D6 batch.

## Still open

* `PriorCoverage_OtherLine_LineOfBusinessCode_A` - needs ACORD's line-of-business
  code list (F5).
* RC-F (receiving carrier / NAIC / Inland Marine) - the Front Range kit now tests
  the carrier half directly: the receiving carrier is named ONLY on the cover letter.
* `disclosure_answers` is not yet surfaced as UNRESOLVED to the producer or client
  (the audit's C10 lists them per run meanwhile).
* The audit cannot see a real value in the wrong box without a key (above).

## Tests

`tests/test_fr125_kit_28sep.py` (49): the scorer's three tiers both ways; the kit
decides every box, every decoy scope reaches a real box, the key agrees with its
own scorer, the client's rules are in it, every expected fact is a real extraction
fact; the audit passes a perfect form, catches 22 planted defects, reads a negated
role as no role, reports NOT EXERCISED instead of passing, and imports the
product's rule tables. `tests/test_a125_complete_fix_21sep.py` +16 (the dash
placeholders, and whitespace is not one).

Full suite (`-p no:randomly`): **10,169 passed / 1 failed / 19 skipped** - the one
failure is the documented pre-existing `test_arq_acord125_missing_only`. Baseline
was 10,107 / 1 / 19; the +62 are this work's tests.

---

# ROUND 2 - TEST 1 RESULTS - the Orbin client package - 28 Sep 2026

**What ran:** `orbin_retest_kit/` (the client's real Orbin Contracting submission,
rebuilt: EMC package policy + certificate + narrative), **ACORD 125 only**, generated
09/28/2026. Session `9fc52210`. Graded from the stored session (the downloaded PDF
matches it box for box).

**This is NOT the Front Range kit.** Orbin has no answer key, so every expectation
below was built box by box from the three documents - the narrative is the
applicant's own statement - plus the client's 8-19-26 rules and the owner's recorded
decisions. Nothing is scored against a value the documents do not print.

## The four numbers

| | boxes | |
|---|---|---|
| **Correct** | **43** of 49 | 42 exact, 1 by meaning (the premises description) |
| **Wrong** | **1** | the primary-operations box is PARTIAL - right, but half the meaning is missing |
| **In the documents, missing from the form** | **5** | the prior-carrier OTHER column (umbrella / inland marine) |
| **Made-up values** - the documents do not state them | **3** | BLD # `001`; FOR THE LAST `5` YEARS; TOTAL LOSSES `$0` |
| A rule says blank, and it was filled | 1 | CONTRACTORS SUPPLEMENT ticked - ACORD 186 was not generated |
| Wrong role - a real value in the wrong box | 1 | METHOD OF PAYMENT = `DIRECT BILL` (that is the billing plan) |

**Accuracy of what it filled: 43 / 44 = 97.7%.  Coverage: 43 / 49 = 87.8%.**
(Corrected after test 2: the VEHICLE SCHEDULE tick was first counted correct; it is
disputed and now counted neither way - see test 2, finding T2-7.)
**After today's two fixes (replayed on this session): made-up 3 -> 1, rule-says-blank
1 -> 0.** Exactly 3 boxes change; nothing else moves.

Not counted either way:
* **GL CODE** - the GL declarations print TWO classes for Location 001 (91580
  executive supervisors, 91585 subcontracted work). The client's rule is "only from a
  verified classification source"; it does not say which of two. Right-or-blank left
  it empty. The narrative ("the principals ... act as the executive supervisors")
  points to 91580. **Client call.**
* **Q4 "other insurance with this company" = Y, listing all four EMC policies** -
  counted correct because it is the owner's 24 Sep decision ("125 Q4 list back").
  **It conflicts with the client's own key:** on Front Range the client answers Q4 =
  N, because "this company" is the RECEIVING carrier. Here the CARRIER box is blank,
  so Q4 answers a question about an unnamed company. **Needs Brent.**

## Box by box

| group | result |
|---|---|
| Edition, QUOTE, the four lines of business (Auto, CGL, Inland Marine, Umbrella) | correct - no phantom lines despite five "No Coverage" lines on the common dec |
| Carrier / NAIC / policy number / premiums | correctly BLANK - quote, receiving carrier not named |
| Proposed dates | correctly BLANK - the current term ended 07/15/2026, so they are asked (pre-form warning) |
| Producer | the login (Astrea It Services / Vinay Sharma); the old broker (Commercial Risk Solutions / Terri Wroblewski) appears nowhere - client item 4 holds |
| Vehicle Schedule tick | **disputed - not counted** (see test 2, T2-7) |
| Billing plan DIRECT, audit `A` | correct - "DIRECT BILL" and "Audit Period: Annual" are printed |
| Applicant name, address, LLC, CONTRACTOR | correct |
| FEIN, SIC, NAICS, phone, website, start date, county, contacts, employees, revenue, areas | correctly BLANK - none printed. The only phones are the agent's, claims and carrier lines; the only contact is the old broker's |
| Premises row | correct (LOC 1 = "Location 001") - except BLD # |
| Questions 1-3 and 5-15 | correctly BLANK = UNRESOLVED - the documents answer none of them |
| Prior carrier 2025, GL and Auto columns | correct, all 10 cells |
| "Check if none" | correctly BLANK - see F8 |

## Every box that is not right

| box | printed | should be | why | status |
|---|---|---|---|---|
| CONTRACTORS SUPPLEMENT | ticked | blank | ACORD 186 was not generated. Generation read the RECOMMENDED forms as the package | **FIXED - F7** |
| FOR THE LAST __ YEARS / TOTAL LOSSES | `5` / `$0` | blank | the narrative's "There have been no losses in the past 5 years" converted into a verified 5-year history - the client's 8-19-26 key word for word | **FIXED - F8** |
| BLD # | `001` | blank | no building number is printed anywhere; extraction copied "Location 001" into `building_number` | open - O1 |
| METHOD OF PAYMENT | `DIRECT BILL` | blank | the tooltip asks how the policy will be PAID (check, EFT, card); "DIRECT BILL" is the billing plan, already ticked beside it | open - O2 |
| Prior carrier OTHER column (5 cells) | empty | umbrella 6J7-40-02---26, $3,418 (or inland marine 6C7, $300) | two "other" lines, one column, and no rule picks | open - O3 |
| DESCRIPTION OF PRIMARY OPERATIONS | the account overview only | overview + operations | drops "the principals supervise every project ... trade work is subcontracted" - the core underwriting fact for a general contractor. Meaning recall 0.49 = partial | open - O4 |

## The pre-form screen - checked

* **Submission Integrity** - right. The equivalences (LLC, address and date formats,
  three spellings of the coverage names) are all genuinely one thing.
* **Data Consistency** - right. Four policies, two carriers (Employers Mutual and EMC
  Property & Casualty), NAICs 21415 / 25186, inland marine's NAIC correctly unknown.
  Worth knowing, not visible: `coverage_lines` also carries five junk rows - the
  common dec's "No Coverage" lines (Property, Crime, Workers Comp) and two duplicate
  GL rows ("Liability", and `BBC7263` without its suffix). Harmless on this form
  (no phantom ticks), but it is the list every "which lines are carried?" reader walks.
* **Warnings** - all three right. Proposed effective date: the term ended, so asking
  is correct. Contact information: correct - the only contact printed is the old
  broker's. Driver schedule: the known Orbin D6 item (the policy schedules no
  drivers).

## The rules audit on this run - and what it missed

The first key-free audit of this run **passed everything** - it had three blind spots,
all closed today and pinned:
* **C8** only fired on loss ROWS; a summary with no rows (this run) was "not
  exercised". It now fails a loss total or period with no rows and no attestation.
* **C17 (new)** - an ATTACHMENTS tick must name a form this package contains. The
  dump now records the generated package.
* **S4** cannot judge values of two characters or fewer (`0`, `5`) - a stated limit,
  now covered by C8 for the loss row.

Re-run: **C8 FAIL (the 5 / $0), C17 FAIL (the contractors supplement)**, 13 pass,
8 not exercised.

## Root causes, and the two fixes

**F7 - the package was the recommendations (my round 1 seam, again).**
`package_form_ids` reads `selected_form_ids`. Every generation route - the sync route,
both lite paths, the worker - writes that key AFTER it generates, so during generation
the row still holds what the analyze step wrote: the RECOMMENDED forms. ACORD 125
generated alone ticked CONTRACTORS SUPPLEMENT because 186 had been recommended. The
same stale list fed the shared gap fill's package (the 186's starred questions) and
the per-form cross-form checks. My round 1 test proved `package_form_ids`; nothing
proved the route feeding it - the third time the seam lesson has been earned.
**Fix:** `form_service.bind_generation_package` - every entry binds the request's
forms before generating (add-form binds what was generated plus the added form), so
what the readers see mid-generation equals what is stored after. **The seam test walks
all six generation entries and fails the build if any generates before binding;
removing the sync route's bind made it fail.**
**D6:** a contractor package generated WITHOUT ACORD 186 now shows the per-form
"contractor without ACORD 186" warning the stale list was hiding - the per-form 125
can cap at 85 where it did not. The package score is unchanged (the route already
scored the requested list). Tell Brent.

**F8 - a narrative became a verified loss history.** "Check if none" reads
`no_loss_attestation_verdict`, where a narrative is not an attestation (client ruling,
5 Sep). The summary row beside it still opened on `asserts_no_known_losses`, which
extraction sets for ANY no-loss sentence - so the box stayed unticked while the AI
printed 5 years / $0 next to it. **Fix:** the summary row reads the same verdict. A
genuine attestation (a person, or an uploaded ACORD's own box) still opens it.
`test_run_20260813h` changed: it encoded the 13 Aug view that the flag was "a real
signal", which the 5 Sep ruling and the 8-19-26 key both overturn.
**D6:** narrative-only no-loss packages print two fewer boxes; the producer is asked.

## Open

| # | what | next |
|---|---|---|
| O1 | BLD # invented by extraction (`building_number` = the location number) | a building number must be printed beside a building label - deterministic, like the NAIC pairing |
| O2 | METHOD OF PAYMENT takes the billing plan | give the box an owner, fact-or-blank - the same disease the payment-plan box had (`_PAYMENT_SCHEDULE_RE`'s comment) |
| O3 | prior-carrier OTHER column empty with two "other" lines | a rule for which line takes the column, the other to REMARKS / ACORD 101 - owner decision |
| O4 | primary operations keep only the overview paragraph | extraction's `operations_description` should carry the operating model (supervision, subcontracting) |
| O5 | Q4 - owner decision vs the client's key | Brent |
| O6 | GL CODE with two printed classes | the client: pick the governing class, or leave it? |

## Also measured today - the Front Range upload (session 426afb35), extraction only

The Front Range kit was uploaded this morning, but **no form was generated on that
session** - the form sent above is Orbin. Extraction can be graded without the form:

| check | result |
|---|---|
| ENTITY-CELL | **29 / 33 = 87.9%** (the Meridian v21 baseline was 31.0%) |
| Scalars | **12 correct / 2 wrong / 0 missing** - the 2 are the proposed term read as the current one (below). The extraction grader compared strings and first reported 4 wrong: `June 15, 2014` vs `06/15/2014` and `Limited Liability Company (LLC)` vs `LLC` are the same values - it now judges them the way the form scorer does |
| OCR - the 8 questions printed ONLY on the scanned fax | **8 / 8** read correctly |
| Questionnaire page 1 - answers given by an X in a column | **5 / 8** - questions 1a, 2 (formal safety program = YES) and 5 missed |
| The OSHA trap | **fell** - `safety_program_elements` includes "OSHA", from an injury LOG |
| Loss history - one claim, two valuations | correct - one row, the latest valuation |
| Contacts, premises | all correct, including the abbreviated headers (FT / PT / OCC SF / TOT SF) |
| Nothing invented | no additional interest, no extra named insured, no relationship |

**One finding that will shape the whole form:** the 100-page upload was typed as ONE
document - a **narrative**. Everything downstream followed: `is_renewal = Y` (from the
incumbent's "RENEWAL OF GL-104471"), the proposed term = the CURRENT term
(10/01/2025-10/01/2026), and `carrier_name` = the CURRENT carrier (Timberline), not the
receiving one (Granite Arch). The rules that separate the existing policy (a dec page)
from the submission (a narrative) cannot work when a single upload gets a single type
- and real clients send one combined PDF all the time. **This is the root cause to
expect in round 2 test 2.**

---

## Verification

| check | result |
|---|---|
| Full suite (`-p no:randomly`) | **10,182 passed / 1 failed / 19 skipped** - the one failure is the documented pre-existing `test_arq_acord125_missing_only` |
| New tests | `tests/test_orbin_r2t1_28sep.py` (10), incl. the seam test over all six generation entries - removing the sync route's bind made it fail |
| Test changed (the decision changed) | `test_run_20260813h.test_total_losses_opens_up_with_a_real_signal` |
| Replay of this session on the fixed code | exactly 3 boxes change (contractors supplement, loss period, loss total), all intended |

---

# ROUND 2 - TEST 2 RESULTS - the Front Range kit - 28 Sep 2026

**What ran:** `fr125_test_data/FR125_front_range_package.pdf` (100 pages, one upload),
**ACORD 125 only**, session `31e49fa7`, generated 09/28/2026 on the restarted backend
(today's two fixes live - the CONTRACTORS SUPPLEMENT stayed blank on a contractor
package with ACORD 186 recommended but not generated). Graded against the **client's
own answer key** (`125_reference/`, 8-19-26) by `report_125_run.py`. The dump graded
"as printed" and the downloaded PDF give **identical counts**.

## The four numbers

| | boxes | |
|---|---|---|
| **Correct** | **74** of 106 | 73 exact, 1 code written as its word (payment plan "Annual") |
| **Wrong** | **4** | carrier, the two proposed dates, the premises description |
| **In the documents, missing from the form** | **28** | 20 = the prior-carrier grid; 3 unanswered questions; underwriter + office; QUOTE; DIRECT |
| **Made-up values** - the documents do not state them | **15** | 8 = the Q4 "other insurance" list; RENEW; AGENCY bill + method; NAIC; OSHA; two phone types |
| Wrong-role values - a trap value in its trap box | 4 | the CURRENT carrier, its NAIC, the CURRENT term (both dates) |
| A rule says blank, and it was filled | 1 | DRIVER INFORMATION SCHEDULE - ACORD 125 was generated alone |
| Wrong shape | 1 | PAYMENT PLAN holds "Annual (paid in full)" - the box takes the code AN |

**Accuracy of what it filled: 74 / 78 = 94.9%.  Coverage: 74 / 106 = 69.8%.**

## What held - the hard parts of the kit

| trap | result |
|---|---|
| **8 questions printed ONLY on a scanned fax** | **8 / 8** answered correctly - OCR works |
| Decoy identifiers: 8-digit CO tax account, 7-digit USDOT, the GL class as NAICS | none landed - FEIN 12-3456789, NAICS 238210, SIC 1731 |
| GL CODE from the classification schedule | **92478** - the client's rule, met |
| The carrier's website and phone in every running header | not taken - the applicant's own printed |
| Abbreviated premises headers (FT / PT / OCC SF / PUB SF / TOT SF / LSD / CL / INT) | **all 8 cells right**: 18 FT (not 20 headcount), 2 PT (not 6 agency temps), $4,250,000 (not the projection, the payroll or the $6.45M backlog), 5,000 occupied / 15,000 building / 500 public, inside, tenant, N |
| Two contacts in drifting columns | 8 / 8 |
| Start date spelled three ways | 06/15/2014 (not the 2019 relocation) |
| Operations: two narratives | PRIMARY OPERATIONS exact, word for word |
| One claim on two valuations | ONE row at the LATEST valuation - $4,850 paid, $0 reserved, closed; total = PAID |
| Placeholders "--" / "N/A" / "(none)" in source cells | none printed (F1) |
| Certificate holders, landlord, job sites | none became an interest, a named insured or a premises |
| Lines of business | exactly the four requested - the property form's tool / installation / dishonesty EXTENSIONS did not tick Inland Marine or Crime |
| Flammables = Y with the client's explanation | exact |
| Row-cell | premises 8/8, contacts 8/8, losses 5/5 - no cross-row value anywhere |

## Every box that is not right - and why

| # | boxes | what printed | root cause |
|---|---|---|---|
| T2-1 | RENEW ticked, QUOTE blank | a renewal | **RC-I** |
| T2-2 | CARRIER, NAIC | Timberline Mutual / 27413 - the CURRENT carrier | **RC-I + RC-F** |
| T2-3 | Q4 list (8 boxes) beside Q4 = **N** | Timberline's four policies as "other insurance with this company" | **RC-I** (the list follows the page-one carrier) - and the form contradicts itself |
| T2-4 | PROPOSED EFF / EXP | 10/01/2025 - 10/01/2026, the CURRENT term | **RC-H** |
| T2-5 | Prior-carrier grid (20 boxes) | empty | **RC-H** (the grid fills from the term once it moves) |
| T2-6 | BILLING AGENCY, METHOD "Agency bill - Quarterly installments" | the current GL dec's billing | **RC-H** - billing has no current-policy marker (the premium has one) |
| T2-7 | DRIVER INFORMATION SCHEDULE ticked; VEHICLE SCHEDULE ticked | schedules we did not attach | the rule is package-blind. The client's own instruction: tick "only when Primble actually creates and attaches a completed driver-information schedule". Vehicle Schedule **disputed** (below) |
| T2-8 | Q1a, Q2, Q5 blank; the safety elements ticked beside a blank Q2 | 5 of 8 page-one answers read | extraction misses an answer given as an X under YES / NO |
| T2-9 | OSHA ticked | from the OSHA 300A injury LOG | extraction: a log is not a programme element |
| T2-10 | Underwriter / office blank | the cover letter's "ATTN: Dana Whitfield, ... Denver Branch" | extraction: no fact for it |
| T2-11 | Contact phone type BUS (both) | not stated | an inference |
| T2-12 | Premises DESCRIPTION OF OPERATIONS | the primary-operations sentence | RC-D (one narrative, two boxes) - the premises paragraph (office, warehouse, storage) exists |

### RC-I - a renewal marker on the INCUMBENT's page decided THIS transaction
Extraction set `is_renewal = Y` from the old GL declarations' "RENEWAL OF GL-104471" -
a statement about the policy being REPLACED. The cover letter says "new business ...
QUOTE requested". One wrong fact then runs three ways:
* the status boxes tick RENEW;
* `extraction_service._mark_page_one_current_policy` exempts "a renewal written by ONE
  carrier", because on a genuine one-carrier renewal that carrier IS the receiving one -
  so the current carrier and its NAIC print on page one;
* Q4's list follows the page-one carrier, so the current programme prints as "other
  insurance with this company".

### RC-H - one upload, one document type
The 100 pages were typed as ONE document - a **narrative**. Every rule that separates
the existing programme (declarations) from the submission (cover letter) keys on the
document type, and here there is only one. The current term is "stated by a
submission document", so it stays as the proposed term; the prior-carrier grid, which
fills from the moved term, stays empty; the current dec's billing wins over the cover
letter's. **Real clients send one combined PDF.** This is the root cause most likely to
recur on live packages.

### RC-F - no fact for the carrier the submission is addressed to
"TO: Granite Arch Casualty Company" is extracted as nothing. And even typed correctly,
a cover letter is a `narrative`, which `_PROPOSAL_ROLES` excludes by design - so the
receiving carrier can structurally only come from a quote or an application. Page one
can therefore only ever print the current carrier or a blank.

### T2-7 - the VEHICLE / DRIVER SCHEDULE ticks need one owner decision
Two recorded statements disagree:
* the owner's principle (`fix-form-stamping.md`): Vehicle / Driver Schedule are "about
  our own package ... derive it from what we actually generate", and the client's own
  instruction on the driver box (quoted in `pdf_service`): tick "only when Primble
  actually creates and attaches a completed driver-information schedule";
* an early Orbin list, "correctly ticked, do not regress", that includes Vehicle
  Schedule - and in the same sentence the EDP section and the AGENT's phone as the
  business phone, both since overturned as wrong.
The product ticks both from the extracted schedules alone. **Scored: Driver = violation
(the client's explicit words); Vehicle = not counted either way, on both round 2 runs.**

## The key-free rules audit on this run

C1 FAIL (RENEW), C6 FAIL (the current term), **C12 FAIL x12** (the Q4 list under an N,
the safety elements under a blank Q2), S3 FAIL (the payment-plan shape); C16 PASS
(every Y/N answer has its sentence in the documents), C17 PASS (no attachment names an
absent form). **What it cannot see without the key:** the carrier - C2 stands down on a
ticked RENEW, and RENEW itself is the error.

## Two grader defects of my own, found on this run and fixed

* **An unticked checkbox counted as a made-up value.** A dump stores an unticked box
  as "No"; the PDF prints it EMPTY. The first report said 37 made-up values; 26 were
  empty boxes. `score_form_fill.as_printed` now grades what the PDF prints - verified
  equal to grading the downloaded PDF itself, count for count.
* **A qualifier broke the code tier.** "Annual (paid in full)" states the plan AN; the
  wrong SHAPE is still reported.
Pinned in `tests/test_fr125_kit_28sep.py` (+2).

## Fix plan - by leverage, NOT started

Not started on purpose: RC-H and RC-F change extraction (a prompt and a
`PROMPT_VERSION` bump re-extract every cached package - the owner's call per
CLAUDE.md), and T2-7 needs the owner's ruling.

| order | fix | fixes | notes |
|---|---|---|---|
| 1 | **RC-I:** `is_renewal` only from a statement about THIS transaction - never from a declaration's "RENEWAL OF <policy number>" | T2-1, T2-2, T2-3 (12 boxes) | deterministic scrub after extraction, like the form-number door |
| 2 | **RC-H:** type documents per SECTION, not per upload - a combined PDF carries a cover letter, declarations and loss runs | T2-4, T2-5, T2-6 (26 boxes) | the largest change and genuinely new work - the nearest existing piece, `declarations_authority`, scores chunks and is documented as NOT discriminating on a real package |
| 3 | **RC-F:** a `submission_carrier` fact from a cover letter's addressee, and the page-one resolver reading it | T2-2 | prompt change + version bump |
| 4 | T2-7 ruling, then the two attachment rules follow the package | 1-2 boxes | owner |
| 5 | extraction: X-in-a-column answers, a LOG is not a programme, the ATTN line | T2-8, 9, 10 (6 boxes) | prompt |

**If 1-3 land: 74 -> 100 of 106 correct, and 15 -> 3 made up** (OSHA and the two
phone types remain) - counted on this run's own boxes, not estimated from a fixture.

---

# THE FR125 KIT, VERSION 2 - dense, and filled like the client's data map - 28 Sep 2026

**Why a version 2.** The owner checked version 1: *"100 pages but most of the pages
are empty"* - measured, **38 of its 100 pages held under 800 characters** (one short
section per page) and 47 were repeated policy wording; 246,601 characters in all. And
the form it asked for stays mostly blank by the client's own rules (106 of 548 boxes).
The owner asked for the opposite on both counts: every page nearly full, at least
300,000 characters, and a form filled the way the client's Vertafore **data map**
(`ACORD 125 - data map 8-19-26.pdf`, 121 numbered boxes) is filled.

**Version 1 is archived, not deleted** - `fr125_test_data/v1_round2_test2/` (PDF, key,
generator, data). Round 2 test 2 was graded against it and stays reproducible.

## What changed

| | version 1 | **version 2** |
|---|---|---|
| Pages | 100 | **100** |
| Text-layer characters | 246,601 | **513,010** |
| Pages under 800 characters | 38 | **0** - every text page holds at least 3,103 |
| Content / policy wording / scanned / landscape | 49 / 47 / 4 / 1 | **69 / 26 / 4 / 1** |
| Boxes the key expects filled | 106 | **312** |
| Decoys | 29 | 28, re-aimed at the new boxes |

**Layout.** Content now FLOWS: a document pours down the page and on to the next; a
table crossing a page break repeats its header; a scanned or landscape insert waits
until the page in progress has filled instead of cutting it short. A long value
shortens its dot leader, then wraps - no value is ever clipped at the page edge
(version 2's first build cut `IM-GA-220915` to `IM-GA-22`; caught by looking at the
rendered page, fixed at the root).

**Fill - every value STATED, no client rule bent.** Receiving carrier with its NAIC
(printed on the carrier's own acknowledgement, so "only if verified" is met), program
name and code, underwriter and office, QUOTE, the four lines, Direct / Monthly (MO) /
EFT / audit A; **three named insureds** (the applicant plus a subsidiary and a sister
company, each with FEIN / SIC / NAICS / GL / phone / website / address / members);
both contacts with **phone types and secondary numbers and e-mails**; **four premises**
(two owned, two leased, one outside city limits, one partly leased to others); the
**mortgagee** block complete (rank, loan number, amount, end date, phone, fax, e-mail,
reason, location / building / item) plus a second interest; **fourteen YES answers**
with every detail ACORD asks for - parent and subsidiary, all five safety elements,
the other policies with this company, two non-renewals with their reasons and the
condition corrected, the EEOC charge, and the fire-code, repossession and lien blocks;
**three prior-carrier years**; **three claims** with paid $23,550.

Still blank by rule, and the key says so: policy number / premium / deposit /
minimum on a quote, the attachments (ACORD 125 is generated alone), signatures, the
account-sourced producer block.

**Still hard.** 8 questions and the LLC member count exist ONLY on scans; page-one
answers are X marks under YES / NO; abbreviated and two-line headers; riffled cells;
teletype; drifting columns; dot leaders; a landscape statement of values; figures
spelled three ways; "--" and "N/A" in source cells; one claim on two valuations; and a
new one - **the fire-code "resolution" has not happened** ("service is scheduled for
10/05/2026"), so that box must stay EMPTY.

## Proven before use

* every expected value is printed (or drawn on a scan); every decoy is printed; the
  scanned-only facts do NOT leak into the text layer; the key scores itself 312 / 312
  and an empty form raises nothing;
* four pages were LOOKED AT, not assumed - which found and fixed two defects of the
  kit itself: question text overlapping the YES column (it would garble the X), and the
  census naming a different safety manager than the safety programme;
* the key-free audit passes a perfect version-2 form with **0 flags** and catches
  **22 of 22** planted defects on the real 100-page text.

## Two audit weaknesses the denser kit exposed - fixed

* **"Every word exists somewhere" is not grounding.** In 513,000 characters every
  common word is printed somewhere, so an INVENTED loss description ("water damage to
  warehouse from a burst pipe") passed the made-up detector. Grounding is now LOCAL:
  the value's content words must stand together in one passage. Its first cut counted
  function words and flagged a faithful paraphrase on Meridian test 5; it now counts
  content words, and both directions are pinned.
* **A name given another role on its own line** ("Landlord: Commerce Way Partners LP")
  was credited to a "SCHEDULE OF NAMED INSUREDS" heading above it. That line now
  decides, and a heading's reach ends at a blank line.

Tests: `tests/test_fr125_kit_28sep.py` now 54 (version-2 rules, the density ask,
locality, role-on-own-line); with the Orbin and 21 Sep files, **214 pass**.

---

# ROUND 2 - TEST 3 RESULTS - the FR125 kit, version 2 - 28 Sep 2026

**What ran:** `fr125_test_data/FR125_front_range_package.pdf` (version 2, 100 dense
pages, one upload), **ACORD 125 only**, no human edits, session `4c734a06`. Graded
against the kit's answer key (312 boxes that must carry a value, 220 that must stay
empty) by `report_125_run.py`, and against the documents alone by `audit_125_rules.py`.

## The four numbers - as the run printed, and after the fixes

| | as run | after the fixes (replayed) |
|---|---|---|
| **Correct** | **220** of 312 | **297** of 312 |
| **Wrong** | **48** | **1** |
| **In the documents, missing from the form** | **44** | **14** |
| **Made-up values** | **8** | **0** |
| Wrong-role values (a trap value in its trap box) | 3 | 0 |
| A rule says blank, and it was filled | 1 | 0 |
| **Accuracy of what it filled** | 82.1% | **99.7%** |
| **Coverage of what it should fill** | 70.5% | **95.2%** |
| Rules audit (no key) | 1 fail, 1 review | 0 fail, 1 review |

The first report said 219: one explanation was marked "opposite polarity" by a grader
defect of mine (below). Both columns are graded by the corrected grader.

**Extraction (LLM call 1) was not the problem:** entity-cell 81 / 82 = 98.8%, scalars
16 / 0 / 0, nothing invented, relationship checks clean. The four named insureds,
four premises, two contacts and three losses came out of a 100-page package with no
cross-row value anywhere. Almost every wrong box was made AFTER extraction.

**How "after" was measured.** The stored run replayed through the fixed code
(`map_facts_to_form` on the stored facts, with the stored gap-fill answers standing in
for call 2). Two call-2 answers the live evidence gate had accepted (question 5's "Y"
and its description) are restored in the replay, because a dump keeps no grounding
quotes. A live run will differ where gap fill is non-deterministic - re-run the kit to
confirm.

## Why each box was wrong - one cause, many boxes

| cause | boxes | what printed | fix |
|---|---|---|---|
| **The incumbent's "RENEWAL OF GL-104471" decided this transaction** (T2's RC-I, again) | RENEW, QUOTE, CARRIER, NAIC, trap x2 | a renewal to Timberline Mutual | The document's statement about THE SUBMISSION ("SUBMISSION - NEW BUSINESS - REQUEST FOR QUOTATION", "Transaction ... New business - quote") is recorded as `submission_is_new_business`. RENEW never ticks on it, QUOTE does, and the page-one "one-carrier renewal" exemption no longer applies. `is_renewal` itself is NOT overwritten - it also routes renewal dates, where "the expiring programme is replaced" is true of a new-business quote too (Meridian is exactly that). |
| **The receiving carrier sat under a bare "Carrier" label** | CARRIER, program code | blank / the incumbent | The index already held "Carrier: Granite Arch Casualty Company" in "GRANITE ARCH CASUALTY COMPANY - ACKNOWLEDGEMENT OF SUBMISSION". A bare carrier label inside a section headed as the SUBMISSION (never declarations / policy / schedule / prior / current) is the addressee; two sections naming two carriers is no answer. The program, underwriter and office read ONLY from that same section - Brent's key: "named underwriter if submission is directed to one". Gap fill stays blocked from those boxes. |
| **The current year was missing from PRIOR CARRIER** | 60 grid cells shifted a year | 2024 as year one, 2023 as year two, 2023's third row empty | The current policies joined the grid only after a renewal ROUTING. The test is now the dates: a current policy that ends on or before the proposed effective date, and began before it, is the term that precedes the proposal. When the proposal IS the current term nothing changes. |
| **A carrier that renewed was deleted as a duplicate** | 3 insurer names | blank in 2023 | Guard 2 treats insurer names as a roster that never repeats. The prior grid is a table of YEARS; a year the grid's own fact states is grounded. |
| **Three companies in one building read as one address** | 4 address boxes | blank | Guard 11 blanked "8000 Commerce Way, Suite 130" because it contains row A's "8000 Commerce Way" - row A is Suite 120. A row its own fact states is grounded, and a different unit number is a different address. The unit now prints on LINE TWO (both kit keys and the client's data map put it there). "4800 Dahlia St # D13" - no comma - is untouched, and the live duplicate Guard 11 was built for is still caught. |
| **The company's phone deleted as a contact's** | BUSINESS PHONE | blank | The office line was also the inspection contact's SECONDARY number. A collision with a contact's secondary number keeps the company box when the company's own fact states that number; a collision with a contact's PRIMARY line still blanks. |
| **Question 4 listed the incumbent's policies** | 8 boxes (4 made up) | Timberline's GL / auto / property / umbrella | The document ANSWERS question 4 - "YES: Workers Compensation WC-GA-448120; Commercial Inland Marine IM-GA-220915" - and its answer now decides the list (numbers read from the grounded quote only). A NO lists nothing (FR v1, Meridian). A package that does not answer - Orbin - keeps the owner's 24 Sep inferred list. |
| **"Policy copy not required; do not send bills"** | POLICY, SEND BILL (made up) | ticked | The test was `"policy" in text`. Read per clause now: a clause that names the item and negates it declines it. |
| **NAME OF TRUST printed the loss payee** (trap) | 1 | Rocky Mountain Equipment Finance LLC | ACORD reuses `AdditionalInterest_FullName_B` for question 11 - its tooltip: "As used here, this is the name of the trust." The tooltip decides now: the trust's name when question 11 is YES and names it, an owned blank when it is NO, and - silence being no answer - the gated gap fill when the documents never address question 11. Never a second interest. The tooltip is read from the schema of the form `_form_id` names, so a re-stamp with another form's schema left on the thread cannot mistake ACORD 127's real second interest for a trust. |
| **A scheduled date printed as a resolve date** | 1 (made up) | 10/05/2026 | The description ("service is scheduled") was already refused as unresolved; its paired date now goes with it, and any resolve date after today is a plan. |
| **PAYMENT PLAN / METHOD** | 2 | blank / "Direct bill" | "monthly EFT" reached the code box raw and the type guard read it as a name. A plan word becomes the code from the box's OWN tooltip ("AN - Annual, MO - Monthly, QT - Quarterly") - MO. METHOD reads a stated payment method (EFT, ACH, check, card, wire, premium finance) first; the billing plan is still the fallback, so a package stating only "Direct Bill" prints what it printed before. |
| **E-mail domains shortened** | 2 | jsmith.site@example.com | The model kept the mailbox and dropped part of the domain. An address the documents do not contain is replaced by the ONE address they print with the same mailbox; none or several - left as extracted. |
| **DRIVER INFORMATION SCHEDULE on a 125-only package** | 1 | ticked | The client's words: tick "only when Primble actually creates and attaches a completed driver-information schedule" - that is ACORD 127's. Package-aware now when the package is known. VEHICLE SCHEDULE deliberately unchanged (the client's own "do not regress"). |
| **Explanations lost detail** | 3 narratives | "owns one DJI Mavic 3 ... drone for roof and site inspections" (dropped "flown by a Part 107 certified employee") | The explanation box printed the model's paraphrase of the grounded quote. When the explanation IS a paraphrase of the quote (70%+ of its content words), a sentence of 8+ words and not the question-and-checkbox line, the document's own sentence prints. |
| **Safety programme OTHER restated the listed elements** | 2 | "Safety Manual, Safety Position, Monthly Meetings, OSHA" | Guarded against the closed four-element vocabulary; a real other element survives. Kept to the safety programme on purpose: 60+ "Other" option groups across the 17 forms legitimately reuse option words ("Hired Physical Damage"). |
| **Loss line printed "GL"** | 1 | GL | ACORD asks for text ("e.g. General Liability"). A bare abbreviation the line canon knows prints as the line's name. |

## The bigger picture - three classes, not fifteen bugs

1. **A statement about something ELSE decided this box.** The incumbent's renewal
   line decided this submission's status; the lender's declined items became
   requested ones; the loss payee filled the trust box; a scheduled date became a
   resolve date. Each is now read against what the statement is ABOUT - the
   transaction, the clause, the tooltip, the tense.
2. **A guard that protects a roster deleted a history.** Guard 2, Guard 11 and the
   phone guard each assumed a repeat is a duplicate. Every one now asks the
   per-row fact first: a row the document itself states is not an echo.
3. **The document answered, and an inference was preferred.** Question 4, the
   payment method, the receiving carrier and the current term all had the
   document's own answer in hand. The answer outranks the inference now; the
   inference remains for packages that do not answer.

## Blast radius - checked on every stored run, box by box

| run | boxes that move | verdict |
|---|---|---|
| Orbin (round 2 test 1, stored) | 4 | 3 are the earlier seam / no-loss fixes; the 4th turns a printed "No" checkbox into blank, which prints identically. Payment method still "DIRECT BILL". |
| FR125 v1 (round 2 test 2, stored) | 14 | 74 -> 75 correct, made up 15 -> 5, **nothing that was correct moved**. CARRIER goes from the wrong incumbent to blank (v1's index has no submission section). |
| Meridian (A125 kit) | key corrected | its key expected the SECOND interest in the trust box; the package answers question 11 NO, so the box is blank by rule and the interest is its trap. 8 key entries change, all for that one box. |

**D6 - for Brent:** no score rule changed. The forms change where listed above, and a package's fill rate moves with them (more boxes right, fewer made up).

## Still open - 14 missing, 1 wrong - all need extraction to capture more

| boxes | why | fix |
|---|---|---|
| NAIC 21334, program name, underwriter, office | the index captured only "Program code" from the acknowledgement; NAIC is printed in the section's heading line | **prompt (v23):** the submission's addressee - carrier, NAIC, program, underwriter, office - as facts |
| Q5 reason ticks (3), condition-corrected text | question 5 answered as an X in a YES / NO column - no disclosure row | prompt: X-in-a-column answers |
| Safety OTHER "Daily job hazard analysis" | the prompt allows only the four named elements | prompt: allow "Other: <text>" |
| REMARKS | extraction took a certificate footnote, not "REMARKS FOR THE APPLICATION" | prompt |
| Secondary phone types (2) | no fact for a secondary phone's kind | prompt |
| Premises 3 "Suite 210", interest BLD # | extraction dropped them | prompt |
| Fire-code explanation (wrong, partial) | the quote is a 7-word fragment; the full sentence names the fire department | prompt |

**Owner decision:** these need `PROMPT_VERSION` v23 (re-extracts every cached
package, `improving-ll.md` updated in the same commit). Recommended - it is the whole
remaining gap on this kit.

## A grader defect of mine, fixed

`score_form_fill.meaning` marked a whole clause negated when "not" appeared anywhere in
its first six words, so "a solar installer not part of this submission" read as the
opposite of "a solar installer that is not part of this submission". A negation now
governs only the words after it; real flips ("does not own" vs "owns", "No
manufacturing" vs "Manufacturing") are still caught.

## Tests

**One existing test changed, and why.** `test_run_20260814c_fixes.
test_a_genuinely_printed_payment_plan_stamps` asserted the plan prints as the word
"MONTHLY". Its point - a stated plan stamps - still holds; the box's own tooltip asks
for the CODE ("MO - Monthly") and both FR125 keys expect it, so it now asserts "MO".
The suite also caught two defects of mine before they shipped: the trust box claimed
an owned blank on SILENCE (the disclosure resolver's contract is that silence goes to
gap fill), and the tooltip lookup trusted a schema another test had left on the
thread. Both fixed; the second is now a test.

`tests/test_fr125_v2_run_28sep.py` (46) - every fix above plus the grader, each with
its adversarial twin (the Dahlia duplicate still caught, a contact's primary line
still blanked, ACORD 127's second interest untouched, a contested renewal not marked,
a declarations carrier never the addressee, two addressees no answer, the proposal
equal to the current term adds nothing). `tests/test_fr125_kit_28sep.py` (54) green
after the audit learned the trust box (C14 no longer judges it as an interest;
question 11 owns it as a far block).

## Where this run is kept

`fr125_test_data/runs/` - so the next run is compared against this one, not against memory:

| file | what |
|---|---|
| `r2t3_4c734a06_dump.json` | the session as generated (facts, stamped boxes, document text) |
| `r2t3_4c734a06_report.md` | **every** box that is not right, as run - 48 wrong, 44 missing, 8 made up, in full |
| `r2t3_4c734a06_numbers.json` | the as-run numbers (220 / 48 / 44 / 8) - pass to `--compare` |
| `r2t3_replayed_numbers.json` | the same run replayed through the fixes (297 / 1 / 14 / 0) |

`backend/scripts/replay_125_run.py` replays any stored dump through the current code -
a code change measured on a graded run, no upload, no LLM cost.

---

# ROUND 2 - TEST 4 RESULTS - the same kit, live, on the fixed code - 28 Sep 2026

**What ran:** the same `FR125_front_range_package.pdf` (version 2), restarted backend,
**ACORD 125 only**, no human edits, session `a7ef6f98` (`ACORD_125_FILLED 9.pdf`). Graded
from the session dump AND from the downloaded PDF - identical counts.

## The four numbers

| | test 3 as run | **test 4 live** | test 4 replayed through the second fixes |
|---|---|---|---|
| **Correct** | 220 of 312 | **281** | **306** |
| **Wrong** | 48 | **2** | 1 |
| **In the documents, missing from the form** | 44 | **29** | 5 |
| **Made-up values** | 8 | **3** | 0 |
| Wrong-role values | 3 | **0** | 0 |
| A rule says blank, and it was filled | 1 | **0** | 0 |
| **Accuracy of what it filled** | 82.1% | **99.3%** | 99.7% |
| **Coverage of what it should fill** | 70.5% | **90.1%** | 98.1% |
| Rules audit (no key) | 1 fail | 1 fail (C12 x3), 1 review | 0 fail, 1 review |

**The first fixes held live.** QUOTE ticked and RENEW blank; CARRIER Granite Arch
Casualty Company with NAIC 21334, PROGRAM CODE CSP-EL and UNDERWRITER Dana Whitfield;
question 4 lists WC-GA-448120 and IM-GA-220915; PRIOR CARRIER 2025 and 2024 with
Timberline in every year; NAME OF TRUST Ortega Family Trust; both other named insureds
at 8000 Commerce Way with Ste 130 / Ste 140 on line two; BUSINESS PHONE 303-555-0175;
both e-mails with the right domain; payment plan MO; no resolve date beside the
fire-code violation; POLICY / SEND BILL empty; no DRIVER SCHEDULE tick. Extraction this
run also caught Q5, Suite 210, the safety OTHER element and the secondary e-mails.

## What test 4 got wrong - and why

Every item is the SAME document read twice: something test 3 printed right that test 4
lost, or the other way round. Call 1 is not deterministic; the fixes make the form stop
depending on which half of the document it happened to keep.

| boxes | printed | root cause | fix |
|---|---|---|---|
| Q1a (blank beside a printed parent) - C12 x3 | "Is the applicant a subsidiary?" blank, parent "Front Range Holdings Inc 80%" printed | extraction skipped question 1a's entry this run; the parent block prints from its own fact, so the form contradicted itself | **the question follows the block it owns** - a named parent row answers Q1a YES, a subsidiary row Q1b, when no entry answers it (an explicit NO still wins; no row stays silence) |
| PRIOR CARRIER 2023 (20 boxes) | row C empty | the prior-coverage extraction returned 2024 only; test 3's returned 2023 too | **the verified index held every row both runs** ("General Liability: Timberline Mutual Insurance Company GL-091233 $16,900 10/01/2023 10/01/2024"). A whole row - PRIOR / EXPIRING / PREVIOUS section, a line the canon knows, exactly carrier + number + premium + two dates - joins the fact; a policy already listed is never added twice |
| METHOD OF PAYMENT | Direct bill | the plan came out "Monthly (MO)" this time, without "EFT" | **read where the document labels it** - "Method of payment EFT (automatic ACH debit)"; the first word of the closed method vocabulary on a labelled line; two lines naming two methods is left empty |
| Q5 OTHER + "Agent no longer represents carrier" (2 made up) | OTHER ticked beside a ticked AGENT NO LONGER REPRESENTS CARRIER | gap fill restated a listed option as "other" | **an OTHER that restates an option already ticked is cleared - on every form.** Compared against the label ACORD PRINTS beside each option (read once from the template: the tooltip says "writing business for the insurer", the page says "REPRESENTS CARRIER"), and only when that option is itself ticked. "Hired Physical Damage" beside a ticked "physical damage" survives |
| ITEM CLASS "Contractors Equipment" (made up) | beside a building mortgage | the loan summary prints "Scheduled item class ... N/A"; gap fill borrowed a property-extension sentence | **the interest's own detail** - with the interest's row in hand and no class stated, an owned blank (the COUNTRY rule; both kit keys expect it empty) |
| UNDERWRITER OFFICE | blank | "Denver Branch" was in the carrier's own section - and the type guard refused it as a PERSON'S NAME | **a personal name never contains an organisation noun** (Branch, Office, Department, Bank, Company, LLC, ...) - a category, and it can only make the rejector reject less, the direction its contract calls safe |
| PROGRAM NAME | blank | printed in the cover letter's submission section, not the acknowledgement | the program / underwriter reader falls back from the carrier's own section to **the submission itself**; one value or no answer |
| (found by replay) | - | once "Suite 130" moved to line two, a second guard pass read "8000 Commerce Way" as row A's and deleted it | Guard 2 now applies Guard 11's unit rule: a different suite on either line is a different address |

## Still open - 5 missing, 1 wrong - need the v23 prompt

Q5 UNDERWRITING tick (the index holds "Reason (ACORD): Underwriting"); REMARKS; the two
secondary phone kinds; the interest's BUILDING number; the fire-code explanation (the
full sentence names the fire department). Owner decision, as before.

## Blast radius

Replayed every stored run through the second fixes: test 3 holds at 297, Orbin moves the
same 4 boxes as before, FR125 v1 unchanged at 75. Tests: `tests/test_fr125_v2_run_28sep.py`
now 61 (+15 for test 4).

## Kept

`fr125_test_data/runs/`: `r2t4_a7ef6f98_dump.json`, `r2t4_a7ef6f98_report.md` (every box,
as run), `r2t4_a7ef6f98_numbers.json` (281 / 2 / 29 / 3 - compare the next run with it),
`r2t4_replayed_report.md` and `r2t4_replayed_numbers.json` (306 / 1 / 5 / 0).

---

# ROUND 2 - TEST 5 RESULTS - live on the second fixes - 28 Sep 2026

Session `b63c3e25` (`ACORD_125_FILLED 10.pdf`), same kit, ACORD 125 only, no edits.

| | test 3 | test 4 | **test 5** |
|---|---|---|---|
| **Correct** of 312 | 220 | 281 | **298** |
| **Wrong** | 48 | 2 | **1** |
| **Missing** | 44 | 29 | **13** |
| **Made up** | 8 | 3 | **2** |
| Accuracy / coverage | 82.1% / 70.5% | 99.3% / 90.1% | **99.7% / 95.5%** |

**The second fixes held live:** Q1a = Y, the 2023 prior year (Harbor Excess on the
umbrella), METHOD = EFT, ITEM CLASS empty, the three companies' suites on line two.

**What this run lost - all of it the same document read differently:**
- **The whole CARRIER block (6 boxes).** This run's index recorded the acknowledgement's
  NAIC, program code, underwriter and office but NOT its "Carrier" line; the carrier's
  name survives only in the section heading ("GRANITE ARCH CASUALTY COMPANY -
  ACKNOWLEDGEMENT OF SUBMISSION"). With no addressee, page one correctly refuses the
  incumbent and leaves the block blank. Three runs, three different subsets of that
  section - the case for a dedicated extraction fact.
- **Q5:** UNDERWRITING ticked (new), but AGENT NO LONGER REPRESENTS CARRIER went into
  OTHER as text instead of its own box (2 made up). The option is not ticked, so the
  "restates a ticked option" guard correctly did not delete it.
- **Safety OTHER** "Daily job hazard analysis" - printed on test 4, not on test 5 (gap fill).
- Still never captured: REMARKS, the two secondary phone kinds, the interest's BUILDING #;
  the fire-code explanation is still a shortened paraphrase.

Kept: `fr125_test_data/runs/r2t5_b63c3e25_*` (dump, full report, numbers).

## The fixes after test 5 - code backups plus extraction v23

**Why test 5 lost what test 4 had:** the same document is read differently each run,
and the extraction instructions never ASKED for the carrier the submission goes to,
question 5's reasons, the safety OTHER element, the secondary phone kinds or the
interest's building number. When found, they were found by luck.

**Extraction v23** (`improving-ll.md` C98) asks for each by name: the six
`submission_*` facts (carrier, NAIC, program name and code, underwriter, office),
`nonrenewal_reasons`, "Other: <text>" safety elements, `secondary_phone_kind`,
`item_building_number` / `item_class`, a definition of the remarks fact, and "the
document's own complete words" for explanations. Every cached package re-extracts once.

**Code, no extraction needed:**
- the carrier's name is read from its section's own heading when the index lost the
  "Carrier" line ("GRANITE ARCH CASUALTY COMPANY - ACKNOWLEDGEMENT OF SUBMISSION"), and
  the addressee counts as package evidence for the insurer guard (which had deleted it);
- an OTHER that is word for word a printed option's label moves the tick to that
  option ("Agent no longer represents carrier");
- **page-one REMARKS was never wired** - registered as its box's owner in August and
  never called, so it printed blank on every run. Now wired, and it prints the remarks
  fact only when the document heads that text REMARKS / PROCESSING INSTRUCTIONS - never
  a certificate footnote (test 3) or a certificate's operations note (Orbin).

**Measured on the stored test 5 session:** the code backups alone on its v22 facts
**306 of 312, 0 made up**; with the v23 facts copied from the document, **311 of 312,
0 missing, 0 made up**. Orbin: the same 4 boxes as before, no remark. Test 3 replay: no
footnote printed. Test 4 and test 5 replays: the real remark prints.

---

# ROUND 2 - TEST 6 RESULTS - the first live run on extraction v23 - 28 Sep 2026

Session `c3059a2d` (`ACORD_125_FILLED 11.pdf`), same kit, ACORD 125 only, no edits.

| | test 3 | test 4 | test 5 | **test 6** | test 6 replayed through the fixes |
|---|---|---|---|---|---|
| **Correct** of 312 | 220 | 281 | 298 | **304** | **312** |
| **Wrong** | 48 | 2 | 1 | **6** | 0 |
| **Missing** | 44 | 29 | 13 | **2** | 0 |
| **Made up** | 8 | 3 | 2 | **4** | 0 |
| Wrong-role | 3 | 0 | 0 | **1** | 0 |

**What v23 fixed live:** REMARKS ("Please quote General Liability..."), question 5's
AGENT NO LONGER REPRESENTS CARRIER + UNDERWRITING ticks, the safety OTHER element, both
secondary phone kinds, the lender's BUILDING 1, program name and code, underwriter and
office - 11 boxes that no earlier run printed together.

**What went wrong, and why - every item traced on the stored session:**

| boxes | printed | root cause | fix |
|---|---|---|---|
| CARRIER + NAIC (and a trap) | "Timberline Mutual Insurance Company" beside NAIC 21334 | the new fact named the INCUMBENT as the addressee, with the addressee's NAIC; my code trusted the fact first - one company's name beside another's number | the merge rejects an addressee equal to the carrier page one has already ruled the CURRENT one, then reads the letter's own "TO:" line (a company, in a letter about a submission); a NAIC is kept only when printed on the SAME line as that name; at stamp time, two witnesses naming two carriers is no answer, and a "TO" line in the index counts as an addressee |
| Question 4 (8 boxes, 4 made up) | the incumbent's four policies | extraction put the numbers in the EXPLANATION and quoted the checkbox line; a second YES row was about old paperwork; the reader used the first row's quote only, found nothing, fell back to the inferred list | every YES row, quote and explanation, numbers the document prints (`other_insurance_policies`, derived at the merge); and when the documents name the addressee, the inferred list keeps only THAT carrier's policies |
| CONDITION CORRECTED tick | blank beside a printed description | the reasons list left it out | the tick follows the corrected condition the same answer describes |
| Explanations 8-10 (3 wrong) | "Yes. A leased compact excavator was repossessed in April 2022." | MY v23 wording ("the narrative sentence, not a table cell") sent extraction to the questionnaire's one-line answer instead of the text the document LABELS "EXPLANATION:" - v22 had it right three times | v24 wording (copy the labelled EXPLANATION; never a bare Yes/No line); the merge takes the text the question's own block labels Explanation / Describe (bounded by the next question number); an explanation never starts with "Yes." / "No." |
| Premises 3 SUITE | blank | the row dropped "Suite 210" this run | a row with no unit takes the ONE unit the document prints right after that street (none or several - left alone; "Suite occupied" is not a unit) |
| Loss descriptions (presentation) | "General Liability Customer ceiling..." | the description repeated its own LINE column | an exact leading repeat of the row's line is removed |

**Found on the way, by replaying every stored run:** the first unit-repair cut read FR125
v1's lease sentence "8000 Commerce Way, Suite occupied 5,000 SF" as Suite "Occupied". A
unit identifier now needs a digit or is a single letter, in all three unit readers.

**Blast radius (replayed):** test 3 -> 299, test 4 -> 307, test 5 -> 306 (all on their
own v22 facts; test 3 was first written here as 307 - a misread of a truncated listing,
corrected after test 7), FR125 v1 74 -> 76 with made-up 15 -> 5, Orbin the same 4 boxes as before.

Kept: `fr125_test_data/runs/r2t6_c3059a2d_*` (dump, full report, numbers) and
`r2t6_replayed_*`.

---

# ROUND 2 - TEST 7 RESULTS - live on extraction v24 - 28 Sep 2026

Session `5af86855` (`ACORD_125_FILLED 12.pdf`), same kit, ACORD 125 only, no edits. The
dump and the downloaded PDF grade the same.

| | test 3 | test 4 | test 5 | test 6 | **test 7** | test 7 replayed through the fix |
|---|---|---|---|---|---|---|
| **Correct** of 312 | 220 | 281 | 298 | 304 | **310** | **312** |
| **Wrong** | 48 | 2 | 1 | 6 | **0** | 0 |
| **Missing** | 44 | 29 | 13 | 2 | **2** | 0 |
| **Made up** | 8 | 3 | 2 | 4 | **1** | 0 |
| Accuracy of what it filled | 82.1% | 99.3% | 99.7% | 98.1% | **100%** | 100% |

**Every test 6 fix held live:** CARRIER Granite Arch Casualty Company / 21334 with its
program, code, underwriter and office; question 4 = WC-GA-448120 and IM-GA-220915 only;
question 5 with all three reasons and no OTHER; the labelled EXPLANATIONs for 8-10; Suite
210; the loss descriptions without their line repeated; remarks; no wrong value anywhere.

**What was left - one sentence, three boxes:**

| boxes | printed | root cause | fix |
|---|---|---|---|
| BILLING PLAN (1 made up + 1 missing) | AGENCY | extraction took `billing_plan = "quarterly agency billing"` from "The old Timberline paperwork still shows the old audit and quarterly agency billing." - a sentence about the OLD carrier's paperwork. The submission says "Billing preference Direct bill" and "Direct bill, monthly EFT please". `billing_plan` had no definition | page one's billing is the SUBMISSION's: statements under a DECLARATIONS / CURRENT / EXPIRING / PRIOR heading, or in a sentence about old / prior / expiring paperwork, are the old policy's; when the rest agree on one plan, it wins (never over a person's entry) |
| AUDIT (missing) | blank | the same sentence gave `audit_period = "old audit"` - words that name no period, so the box could not code it | a value that names no period is dropped; the submission's own audit statement ("Premium audit ... Annual (audit period code A)") decides when unique |
| (audit only) C16 on question 1a | - | question 1a is now answered by the printed parent block, which the key-free audit did not know | C16 treats a filled parent / subsidiary block as question 1a / 1b's statement |

Both facts are now DEFINED in the extraction instructions (**v25**, `improving-ll.md` C100):
the SUBMISSION's billing and audit, never the old policy's.

**Blast radius (replayed):** Orbin - the same 4 boxes as before (its billing and audit are
only ever the declarations', so nothing changes); FR125 v1 76 -> 77 (billing now DIRECT,
made up 5 -> 4); tests 3 / 4 / 5 / 6 unchanged at 299 / 307 / 306 / 312.

**One test corrected:** `test_a125_complete_fix_21sep.test_a_second_additional_interest_
can_reach_the_form` asserted a second interest in ACORD 125's `AdditionalInterest_
FullName_B` - the trust-name box by its own tooltip, the misreading already corrected in
the A125 key. It passed only while no schema was in context. It now asserts the second
interest on ACORD 127 and the trust box on ACORD 125.

Kept: `fr125_test_data/runs/r2t7_5af86855_*` and `r2t7_replayed_*`.

---

# ROUND 2 - TEST 8 RESULTS - live on extraction v25 - 28 Sep 2026

Session `e3cebd88` (`ACORD_125_FILLED 13.pdf`), same kit, ACORD 125 only, no edits.

| | test 3 | test 4 | test 5 | test 6 | test 7 | **test 8** | test 8 replayed through the fix |
|---|---|---|---|---|---|---|---|
| **Correct** of 312 | 220 | 281 | 298 | 304 | 310 | **312** | **312** |
| **Wrong** | 48 | 2 | 1 | 6 | 0 | **0** | 0 |
| **Missing** | 44 | 29 | 13 | 2 | 2 | **0** | 0 |
| **Made up** | 8 | 3 | 2 | 4 | 1 | **3** | 0 |

**Every box the key expects is right** - 312 of 312, 100% coverage, nothing wrong, nothing
missing. Test 7's fix held: BILLING PLAN = DIRECT, AUDIT = A.

**The 3 made-up boxes, and one near miss - both from a second extraction row for a question
already answered, written by the chunk that reads the incumbent's pages:**

| what | printed | root cause | fix |
|---|---|---|---|
| Question 4 rows C / D (3 made up) | GL-123456 and BA-456789 after the right two | a second YES row listed Timberline's four policies; the derived list read every YES row and those numbers ARE printed in the document - "printed" was not enough | "this company" is the addressee: a number the documents pair with ANOTHER carrier (the coverage lines, the prior grid, the line records), or a row naming another carrier, is not insurance with this company; the line column is words only |
| Question 5 (audit C16) | Y - right, by luck | a second row answered NO, quoting "The old Timberline paperwork still shows the old audit..." - the form took the first row | when rows for one question disagree, the answer the document corroborates wins (a dated event, a resolution, question 5's reasons, question 4's own policy number, the parent / subsidiary rows, the safety elements, a named trust); with no corroboration either way the question is left unanswered - never decided by row order |

**Replayed:** test 8 -> 312, 0 made up, audit clean; tests 3-7 unchanged (299 / 307 / 306 /
312 / 312); FR125 v1 77; Orbin the same 4 boxes. No extraction change this round.

Kept: `fr125_test_data/runs/r2t8_e3cebd88_*` and `r2t8_replayed_*`.

---

# ROUND 2 - TEST 9 - the same kit on the same v25 extraction (next)

No prompt change this round, so the next upload of the same PDF reuses test 8's extraction
from the cache - it re-proves the fix on the same facts. Expect **312 of 312, 0 made up**.
Grade with `--label "ROUND 2 - TEST 9" --compare fr125_test_data/runs/r2t8_e3cebd88_numbers.json`.

