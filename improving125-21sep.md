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
