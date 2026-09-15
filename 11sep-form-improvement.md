# 11 Sep 2026 - Form Improvement (client Orbin audit)

Running log. Read this before touching per-line identity, `coverage_lines`
evidence tests, or anything that stamps a carrier / NAIC / policy number.

---

## Client report (11 Sep) - 11 items, 3 defects

| # | What he saw | Real defect |
|---|---|---|
| 1, 3, 5 | Wrong carrier, NAIC no document pairs, form number as policy number, false conflicts | **D1** one evidence test answering three different questions |
| 2, 5, 6, 8, 10 | Phantom coverages, $2M compared to a Yes/No box, GL class on the Auto form, a disclaimer as a named party | **D2** facts have no TYPE |
| 4, 9 | Old producer on the new application, $3M vs $1M umbrella | **D3** facts have no ROLE or TIME axis |
| 7 | No ACORD 137 for Colorado auto | not a defect - the rule fires, it sits in "Needs Confirmation" |
| 11 | Re-asked for the Subaru, "Driver 25" | already fixed by BUG-07 (8 Sep). Only "confirm what we found" is missing |

### Status - AFTER ROUND 6 (14 Sep) - offline-verified, awaiting live run 4

**10 of 11 client items fixed; 1 is not a defect.** Item 9 left "parked" on
14 Sep (round 6, owner's go-ahead). Three live runs, each verifying the last
round's fixes on the generated forms and exposing the next layer:

| run | what it verified | what it found |
|---|---|---|
| 1 | items 1, 2, 3, 4, 8 on the forms | F1 - F7 |
| 2 | F1, F4, F5, F3 closed; v19's columns arriving | R1 - R5 |
| 3 | **all five of R1 - R5 closed on the forms** | N1, N2 - one class, one fix |
| 4-5 | offline only - N1/N2, the producer card, address line two, the agent in the applicant contact (fuzzed; live Run 3 documents re-merged) | awaiting live run 4 |
| 6 | offline only - items 3 / 5 / 10 comparison guards, item 9 as a dated change (both real packages replayed; 75-input break-it pass, 23 breaks fixed) | awaiting live run 4 |

Suite: **7,840 passed / 1 failed / 21 skipped** (the documented `httpx`
ImportError). Zero regressions. +400 tests across five rounds. After round 6:
**8,301 passed**, only `httpx` failing (+149 tests in round 6).

**Open, in order:** live run 4 to confirm rounds 4-6 on the forms - a FRESH
upload, since round 6 moved extraction to v21; Brent sees the D6 contact
numbers (Run A 70 -> 68, Needs Work -> Major Gaps) before round 5 ships, and
round 6's D6 (mostly up). Remaining form defects are under "STILL OPEN after
round 5" and "STILL OPEN after round 6" near the end.

| # | Item | State |
|---|---|---|
| **1** | Carrier / NAIC / policy tied to their LOB | **FIXED + LIVE-VERIFIED** on the kit. 14 Sep: on the REAL package the post-generation late-stamp re-wrote the wrong pair - **FIXED offline**, see "ORBIN ROUND 3 (14 Sep)" |
| **2** | Phantom coverages | **FIXED + LIVE-VERIFIED** on the stamped boxes. 14 Sep: the cover, score, recommendations and questionnaire still listed Property / Crime / WC / Farm / Liquor / EPLI / OCP - **FIXED offline**, see "14 SEP - items 2 and 7" |
| **3** | `IM 7100 06 04` as a policy number; false conflicts | **FIXED + LIVE-VERIFIED** on the kit. 14 Sep: on the REAL package the card offered it, the producer confirmed it, 125 printed it - **FIXED offline**, see "ORBIN ROUND 3 (14 Sep)" |
| **4** | Expiring vs submitting producer | **FIXED + LIVE-VERIFIED** |
| **8** | A disclaimer stamped as a party | **FIXED + LIVE-VERIFIED** |
| **5** | Carrier pairing + comparisons that should never happen | **FIXED** - pairing and the typed-binding half verified live; the Claims Made control was inert because ONE value reached `gl_form_type`, and that is now the F4 fix: the STATED basis outranks the detector |
| **6** | Cross-line codes | **FIXED** - the fence is BIDIRECTIONAL since v19. `91580` off the Subaru (verified live), `7398` and `6679` off the GL grid (measured on the live values). 14 Sep: on the REAL package 126 TERR 6679 and 127 CLASS 91580 still came from gap fill - **FIXED offline**, see "ORBIN ROUND 3 (14 Sep)" |
| **10** | Comparison guardrails | **FIXED** - no false carrier/policy conflicts (live); F1's false-alarm class closed; `is_renewal` stays by design (SYS-07) |
| **7** | ACORD 137 for Colorado | Offered: **NOT A DEFECT** - the rule fires (`ACORD_137_CO`, tier `needs_confirmation`); promoting the tier reverses Brent's own ruling, so it is his call. Filled: **WRONG, FIXED 14 Sep offline** - the $1M CSL was forced blank and Med Pay / UM / symbols wiped; `state_auto_grid` now prints them. See "14 SEP - items 2 and 7" |
| **11** | Do not re-ask for the Subaru | **FIXED 8 Sep (BUG-07), not captured live** - measured offline: 24 questions on an empty ACORD 127, 0 ghosts, the Subaru not re-asked. "Show what we found for confirmation" is an unbuilt feature, not a defect |
| **9** | Umbrella $3M -> $1M | **FIXED offline, round 6 (14 Sep)** - the COI's dated reduction is a change, not a conflict: $1,000,000 stamps on 131 / 25, $3,000,000 is kept as history. Anything the documents do not state as a done change, with a date inside the term, stays a conflict. Awaiting the live run |

Live evidence for each row is in "LIVE RUN 1 / 2 / 3"; the fixes that produced
it are in "What shipped", "ROUND 2" and "ROUND 3". Round 6 (14 Sep) also closed
the rest of items 3 / 5 / 10 - the $2M-vs-Y/N-box, tick-vs-form-title and
policy-vs-form-number comparisons - see "ROUND 6" near the end.

### ROUND 2 - what shipped (all four live findings)

| Finding | Root cause | Fix |
|---|---|---|
| **F1** (my own regression) | The stamper gained a line axis; `field_qa` still resolved "the source value" from the package scalar | `pdf_service.authoritative_expected_value` - the checker asks the SAME resolver chain that filled the box. **Both directions**: agreeing with the scalar is not proof of correctness either |
| **F5** | `additional_named_insureds` was a bare `[string]` with no rule anywhere - the `lines_of_business` shape again. The INTEREST word is gone by the time the roster sees it | v19 defines both insured lists + `_names_the_document_calls_additional_insureds` reads the VERIFIED dec entries. Positive evidence **both ways**, so the owner's 2026-09-06 ruling holds |
| **F4** | Two channels for one truth: `gl_form_type` (stated) and `gl_is_claims_made` (detector). Nothing compared them, and only the detector gated anything | `coverage_evidence.gl_is_claims_made` - one door, four consumers. The STATED basis outranks the detector where the document has spoken |
| **F2 / F3** | `auto_vin_schedule` declared no class or territory column, so the fence had no auto witness and ACORD 127's CLASS box had no fact | v19 adds `class_code` + `territory`. The fence is bidirectional and the box fills deterministically. `improving-ll.md` **C87** |

---

## D1 - ROOT CAUSE

`_line_entry_grants_coverage` demands a premium or a limit. Correct for its own
question ("does this package HAVE this coverage?", added 2026-08-09 for the
"PROPERTY - NO COVERAGE" checkbox defect).

It was then reused to answer **"which policy IS this coverage line?"**, which
needs different evidence. A row printing a carrier, a NAIC and a policy number
has identified its contract whether or not we captured its premium.

Worse: `_LINE_EVIDENCE_KEYS = ("premium", "limit")` and **the extraction schema
for `coverage_lines` has no `limit` key** - `{line, carrier, naic,
policy_number, premium, effective_date, expiration_date}`. So the grant test is
really "did we capture a premium", one field, one chance. And the prompt orders
the model to leave it null when the dec page shows one package total (*"never
divide or estimate one"*).

**Result: an ordinary combined-premium declarations page switched the entire
per-line identity system off, for every form and every client.**

### Measured, on data that is 100% correct

Per-line carrier, NAIC, policy number and dates all right. Only the per-line
premium absent:

```
                        stamped on ACORD 126        ground truth
  Insurer_FullName_A    'Employers Mutual Casualty' 'EMC Property & Casualty'
  Insurer_NAICCode_A    '25186'                     '25186'      <- a pair no document prints
  Policy_Number_A       'IM 7100 06 04'             'BBC7263 - 26'  <- an AAIS form number
  Policy_EffectiveDate  None                        '07/15/2026'
```

Extraction was not wrong. The stamper refused to look.

### Value-independent, not a fixture bug

2,160 combinations of carrier / NAIC / policy-number / line-name spellings
(unicode, OCR damage, punctuation, 1-char and 60-char names, injection strings):

```
premium_on_neither  -> LEGACY_SCALAR   identical for all 360 value combos
no_coverage_lines   -> LEGACY_SCALAR   identical for all values
malformed_rows      -> LEGACY_SCALAR   identical for all values
```

The values never change the outcome. The data shape always does.

---

## What shipped

### 1. `extraction_service._line_entry_identifies_policy` (new)

Identity evidence = carrier, NAIC or policy number, and not a denial. Keys
**derived** from the schema's own `coverage_lines` declaration, not curated:
`line` is the subject, `premium` is the grant test's evidence, dates belong to
the term. A new sub-key is a deliberate decision, not a silent one.

`_line_entry_grants_coverage` is **unchanged** and still owns coverage-flag
downgrades and the ACORD 125 line-of-business checkboxes, where demanding money
is right.

### 2. `pdf_service._section_matched_lines` - three questions, three answers

| Question | Answer |
|---|---|
| does the package have this coverage? | `_line_entry_grants_coverage` (unchanged) |
| which contract is this line? | `_line_entry_identifies_policy` (new pool) |
| is this form's line present at all? | `matched`, computed over **all non-denied rows** |

**The first cut got the third one wrong** and broke a case the fix was meant to
protect: an Umbrella row naming the line and nothing else was dropped from the
pool, so ACORD 131 could not tell its own line existed and blanked a number it
should have inherited. Presence is about the line being THERE; identity is about
which contract it is. A row with no identity data contributes no value, so
admitting it is free - and excluding it loses the one thing it proves.

### 3. One line-identity door - `_section_line_names_this_form`

Two implementations of "which coverage line is this?" disagreed on **4 of 14**
real spellings:

```
  printed on the document          canon_line()   section matcher
  Liability Coverage Part          general_liab   False   <-- DISAGREE
  GL                               general_liab   False   <-- DISAGREE
  CGL                              general_liab   False   <-- DISAGREE
  Premises/Operations Liability    general_liab   False   <-- DISAGREE
```

Same wording resolved a policy number through the dec index, then failed to
match the form that needed it. `canon_line` (the door the whole dec index uses)
is now tried first; the token matcher stays as fallback. **Strictly additive** -
every pairing that matched before still matches. Two unplaceable strings are
never "the same line" (None != None).

The ACORD 131 prior-coverage grid was routed through the same door, so the
EXPIRING box cannot disagree with the CURRENT box on one form.

### 4. `_section_carrier_pair` - the package-wide borrow, gated

Old behaviour, reproduced and **value-independent across 360 combinations**:

```
  ACORD 126, package = one Business Auto line only
     -> stamped the AUTO carrier and AUTO NAIC on a GENERAL LIABILITY form,
        for a line the package does not even carry.
```

Three conditions now, each found by testing the previous one:

1. **this form's line must be present** (`matched`) - an absent line has no
   carrier to borrow for;
2. **the package must name exactly ONE carrier entity** (`strict_entity_key`,
   the strict key - `normalize_carrier` is a FAMILY key and fuses EMC P&C with
   Employers Mutual, which is the recombination this exists to stop);
3. **the borrow must not contradict what this line states** - found by the edge
   matrix: a GL row carrying NAIC 11111 and no carrier name, beside an Auto row
   carrying "Acme Mutual"/22222, was handed Acme Mutual AND 22222.

Spelling variants of one company now fold and the fullest legal name wins.
Needed, not cosmetic: the pool now admits every identifying row rather than only
priced ones, so one carrier printed two ways became a new way to blank a box.

### 5. "The package's only policy number" fallback - tightened

Found by the invariant fuzz, not by reading: a package whose only readable
number sat on the **Umbrella** row satisfied "exactly one number in the package"
and stamped it on the **General Liability** form.

*"We could only read one number"* is not the fact *"this package has one
policy"*. A row we cannot place does not block (it may be ours); a row that
names a different, identifiable line does.

### 6. A FORM number is not a POLICY number - at the source AND at the box

`_looks_like_a_form_number` has existed since 2026-08-13 and was applied at
~12 **consumers**, never where the fact is born. So `IM 7100 06 04` became the
merged `policy_number` scalar, was labelled `filled` (shown to the producer as
verified) and printed wherever the per-line inventory was thin.

- **Source:** `_drop_form_numbers_from_policy_facts` in the merge tail. Key rule
  is derived (`policy_number`, `*_policy_number`, `*_policy_no`), so a future
  fact key is covered without anyone remembering.
- **Box:** post-fill Guard 3b-ii. Clearing the fact hands the box to gap fill,
  which reads the raw document where the form number is printed. **Guarding the
  source and leaving the box open is how this defect came back the first time.**
  Keyed on the ACORD box name (46 boxes on 16 forms, 0 false positives, 0
  misses), so it holds for every form and every filling path.

Blank, never a substitute - the correct per-line numbers arrive through their
own resolvers.

---

## Decisions taken

| # | Decision | Why |
|---|---|---|
| D1-a | Split the predicate; do **not** widen the grant test | Widening it would tick coverage boxes for merely mentioned lines - the 2026-08-09 defect |
| D1-b | Do **not** add a `limit` key to the `coverage_lines` schema | Prompt change = `improving-ll.md` event + PROMPT_VERSION bump + cache invalidation. The conflation is the root cause; the missing key only affects the grant question, which currently fails conservatively. **Logged as open** |
| D1-c | `matched` (presence) is NOT filtered by identity evidence | Making it so broke the single-policy-package case. Three questions, three tests |
| D1-d | `canon_line` first, token matcher as fallback - not a replacement | Replacing it would change behaviour for wording only the token matcher places. Additive can only recover, never lose |
| D1-e | Keep the package-wide carrier borrow, gate it with 3 conditions | Deleting it outright regresses genuine single-carrier packages. The defect was the missing conditions, not the fallback |
| D1-f | Strict entity key, not the family key | H5 (2026-09-02): the family key fused EMC P&C with Employers Mutual and manufactured "two policies on one line" |
| D1-g | Form-number guard at BOTH the merge and the box | One without the other is defeated by the other path. Measured: clearing the fact alone leaves gap fill free to re-stamp it |
| D1-h | Blank over a borrowed value, everywhere | House rule. These are identity fields on a legal document |

### One test was wrong and was corrected

`test_relationship_preservation_20260815::test_single_policy_package_still_fills`
printed its one policy number against a line called **"Liability"** - which this
repo's own `canon_line` places on General Liability - and asserted it onto the
**Umbrella** application. That is the client-reported defect this very file
records (*"ACORD 131's EXPIRING POL # came back BBC7263 - the GENERAL LIABILITY
policy number, on the UMBRELLA application"*), written down as the expected
result. The independent fuzz found the same shape on ACORD 126.

Its **intent** - a genuine single-policy package still fills - is right and is
what it now tests (number printed against a row naming no specific line). A
companion test pins the opposite case.

---

## Verification

| Check | Result |
|---|---|
| Killer repro (perfect data, no premium) | carrier, NAIC, number and date all correct |
| Edge matrix, 13 shapes | all correct; legacy path byte-identical |
| Invariant fuzz, 2,500 packages x 14 section forms | **0 violations, 0 exceptions** |
| 4,000 realistic policy numbers | 0 mistaken for form numbers |
| 10 real ISO/AAIS form numbers | 10/10 caught |
| 5,000 random strings through the merge guard | 0 wrongly cleared |
| Policy-number box detector, all 17 schemas | 46 matched, 0 false positives, 0 misses |
| New tests `tests/test_line_identity_11sep.py` | **73 passed** |
| Full suite | **7,461 passed / 1 failed / 21 skipped** - the failure is the documented `httpx` ImportError. **Zero regressions** |
| Do the new tests bite? | Patched the old conflation back in -> tests fail. Side by side: `'EMC Property & Casualty'/'25186'/'BBC7263 - 26'` vs `'Employers Mutual Casualty'/'25186'/'IM 7100 06 04'` |

**Invariants the fuzz enforces** (standing guard in the test file):
no fabricated carrier/NAIC pair; no value taken from another line; no package
scalar leaking onto a section form; no form number in a policy box.

### D6 - scores and values move

Per-line carrier / NAIC / policy number / dates now FILL on packages that
previously blanked or printed the wrong value. Fill rates go **up**; some wrong
values become **blank**. Tell Brent before he sees it.

---

## D2 - COVERAGE TRUTH HAD TWO CHANNELS (item 2)

**Root cause.** The package carries two coverage facts and only one was ever
defined. `coverage_lines` is structured and gated. `lines_of_business` is a bare
`[string]` in the extraction schema with **no rule in the prompt at all**,
unioned across every chunk - so one mention anywhere in 271 pages sticks.

The ISO endorsement header is a MENU (*"THIS ENDORSEMENT MODIFIES INSURANCE
PROVIDED UNDER THE FOLLOWING: COMMERCIAL PROPERTY ... FARM ... LIQUOR
LIABILITY ..."*). We read it as an inventory. The client's phantom list is that
boilerplate word for word.

The corroboration rule **already existed, inline, inside the ACORD 125 checkbox
resolver** (2026-08-10). It was never available to the cover page, the scorer or
the recommender - so the same phantom line was refused on the form and printed
on the cover of the same package.

**Shipped:** `lob_canon.carried_lines_of_business(facts, flags)`. Evidence is a
granting row, a row that IDENTIFIES a policy (the D1 lesson - an unpriced dec
page still names its lines), or a coverage flag. **The flag-to-line map is
derived from the flag's own name** (`has_property_coverage` -> "property
coverage" -> `property`), so there is no table to maintain beside the flags.
Routed: the cover page (PDF table, text fallback and both narrative prompts) and
`sqs_service._ok`. `lines_of_business` itself is untouched - it stays the MENTION
record for the questionnaire, the unmapped-line advisory and the picker.

Measured on the client's shape: **11 mentioned lines -> 4 carried.**

---

## D3 - FACTS CARRIED NO ROLE (item 4)

**Root cause.** One `producer_name` fact, picked by frequency. An expiring
policy prints its agency on every page header; the submission names the new one
once. Frequency wins, and the new application is filed under the agency being
replaced. The role axis exists (every document is classified) and was not read
here.

**Shipped:** `extraction_service._route_producer_identity` in the merge tail.
A submission-role document (application / supplemental / narrative / quote /
acord_form) **wins outright** over any number of dec pages, and the displaced
agency is recorded as `expiring_producer_name` - the separate field the client
asked for. Box side: `_resolve_submitting_producer` makes the ACORD Producer
block an owned blank once only the expiring agency is known, so gap fill cannot
read the old name back off the same page headers.

**A test caught this fix over-reaching, and the test was right.** The first cut
also cleared `producer_name` when ONLY expiring-programme documents named one -
and a COI + narrative submission lost its producer entirely
(`test_the_certificates_producer_name_still_survives_the_merge`). An incumbent
broker re-marketing their own account **is** both producers, and nothing in the
documents separates that from a real change of agency.

**Honest limit:** the one thing that can separate them is the logged-in agency
(`users.organization_name`), which the merge does not receive today. Until it
does, silence leaves the box exactly as it was; only positive evidence of a
different submitting agency clears it. That covers the client's reported case.

---

## D4 - FACTS AND BOXES CARRIED NO TYPE (items 5, 10)

**Root cause.** `_ACORD_FIELD_RULES` matches by SUBSTRING, and
`...GeneralAggregate_LimitAppliesPerProjectIndicator_A` contains
`GeneralLiability_GeneralAggregate` - so four checkboxes inherited
`gl_aggregate`. Separately, every scalar fact not curated in
`RECONCILABLE_FIELDS` is auto-registered as `identity` kind and compared as raw
text, so whatever a document put in a fact became a candidate answer for it.

Measured: only **36%** of the 344 fact->box bindings have a type declared on
both sides today; deriving from ACORD's tooltips, `/Btn` and naming conventions
reaches **99%** (residual 2 facts).

**Shipped, two halves:**

1. **Binding.** `fact_to_form_fields` drops a binding from a MEASURED fact
   (amount / date / count / percentage - read off the fact's own registry
   validator) to a `/Btn` box. Removes 8 bindings on ACORD 126 and 25.
   **A CHOICE fact driving a checkbox is how ACORD expresses a choice**
   (`gl_form_type`, `auto_liability_structure`) and is deliberately untouched -
   that binding is correct, and the defect there is the VALUE, not the binding.
2. **Value.** `underwriting_consistency._drop_values_outside_declared_domain`
   joins the existing drop chain. A candidate that is not legal for the field -
   judged by the fact's own `FACT_REGISTRY["validate"]` **and** its
   `answer_options` list, both of which already existed and neither of which was
   read here - is not a rival answer. **Never empties the field:** if every
   candidate is illegal there is no basis to prefer one, so all are kept.

---

## D5 - CODES HAD NO LINE FENCE (item 6)

**Root cause.** Guard 2e is a hand-listed set of six column names on one form,
and `Vehicle_RateClassCode` - the exact box the client reported - is not in it.
It is read there only as the thing to compare AGAINST, never checked itself.
Surface: **1,289 of 1,352 code / identifier boxes have no fact bound**, so gap
fill decides them, and the numeric meaning gate covers only "Enter amount" /
"Enter number" boxes.

**Shipped:** Guard 2d-ii, stated once by LINE instead of once per column.
The box's line comes from its own leading name segment (`Vehicle_` -> auto),
falling back to the form's line; the value's line comes from the schedule fact
that prints it (`gl_class_code_schedule` -> general_liab). **Both derived
through `canon_line` - no table.** A value every witness attributes to other
lines is blanked. Positive evidence only: no witness, no opinion; a code two
lines share is never judged; values under 3 characters are never judged.

Verified in both directions: 91580 (GL) blanked on the ACORD 127 vehicle row,
7383 (auto) blanked on the ACORD 126 hazard grid, 7383 kept on the vehicle row.

**Known limit:** the client's territory `6679` came from an Auto *Drive Other
Car* endorsement, which no schedule fact captures - so there is no witness and
the guard is silent on it. Fixing that needs the value extracted into a
schedule, not a wider guard.

---

## D6 - PARTY BOXES HAD NO ENTITY TEST (item 8)

**Root cause.** Of the six facts feeding the 65 party-name boxes,
`certificate_holder`, `additional_named_insureds`, `loss_payee_name`,
`mortgagee_name` and `dba_name` all carry `validate = None`.

**Shipped:** `field_mapping_integrity.names_a_party` - **structural, not a
phrase list**, because the 2026-08-08 Data Consistency defect is the standing
lesson (three successive denylists each closed the reported sentence and left
the next phrasing free). A party name is a NOUN PHRASE; boilerplate is a CLAUSE:
it opens with a preposition or demonstrative, closes on a qualifying adverb, or
contains a finite verb. Any one disqualifies, and a name must ALSO carry a
positive signal (legal suffix or proper-noun shape) - two conditions, per H1-F.

Wired as Guard 3c-ii, scoped by `is_party_name_field` (49 boxes, 15 forms,
derived from ACORD's own naming). Companion to the existing role guard, which
already caught "Certificate Holder", "See Attached", "Various" and "N/A".

**16/16 real parties accepted, 15/15 boilerplate refused, plus a 500-phrase
generated clause sweep with zero acceptances.**

---

## Still open (round 1 snapshot - see STILL OPEN after round 2 for current)

| Item | Note |
|---|---|
| **9 - umbrella $3M -> $1M** | **PARKED ON A CLIENT RULING, deliberately.** The amendment logic ALREADY EXISTS: `services/narrative_facts.py` mines `{subject, from, to, as_of, policy_number}` and its own docstring is literally this case. It understands **5 of 10** realistic phrasings and reads only 7 narrative fact keys. It ANNOTATES and refuses to resolve - quoting the client's **17 Aug** instruction (*"an unresolved fact must remain unresolved downstream rather than another part of Primble independently selecting a value"*) - while his **11 Sep** note asks us to pick (*"the current limit appears to be $1M"*). He has told us both things in writing. **Get the ruling first; then the work is (a) widen the input beyond 7 narrative fields, (b) widen the phrasing, (c) resolve-vs-annotate.** |
| 7 - ACORD 137 | Rule fires (`ACORD_137_CO`, tier `needs_confirmation`). Promote the tier or leave it - it reverses Brent's own ruling |
| 11 - confirm or correct | Measured at HEAD: 24 questions on a fully-empty ACORD 127, 0 ghosts, the Subaru not re-asked. With rows present we ask **nothing**; the client wants them shown for confirmation. A feature, not a defect |
| `limit` key on `coverage_lines` | Would make the GRANT test two-sided as its own constant claims. Prompt change = `improving-ll.md` event + version bump |
| Territory 6679 | Came from an Auto Drive Other Car endorsement that no schedule captures, so D5 has no witness for it. Needs the value extracted, not a wider guard |
| Producer: the logged-in agency | `users.organization_name` is the only thing that can tell an incumbent broker from a replaced one. Not plumbed into the merge. D3's limit |
| Type coverage residual | 2 facts (`billing_plan`, `certificate_holder`) have no derivable type |

---

## D6 - SCORES AND VALUES MOVE (tell Brent first)

| Change | Direction |
|---|---|
| Per-line carrier / NAIC / policy number / dates now fill where they blanked | fill rates **UP** |
| Phantom lines leave the cover page and `_ok("lines_of_business")` | a package with NO real coverage scores **DOWN**; a real package is unaffected |
| Wrong values become blanks (borrowed carriers, form numbers, GL codes on auto rows, disclaimer parties) | fill rates **DOWN** slightly, correctness up |
| False Data Consistency cards disappear (illegal rivals, `gl_aggregate` vs checkboxes) | caps released, scores **UP** |

---

## Files touched

```
backend/services/extraction_service.py   _line_entry_identifies_policy (new)
                                         _LINE_IDENTITY_KEYS (new)
                                         _is_policy_number_fact (new)
                                         _drop_form_numbers_from_policy_facts (new)
                                         merge tail: form-number guard wired in
backend/services/pdf_service.py          _section_line_names_this_form (new)
                                         _line_names_a_different_line (new)
                                         _carrier_entity_key (new)
                                         _is_policy_number_box (new)
                                         _section_matched_lines (rewritten)
                                         _section_carrier_pair (rewritten)
                                         _resolve_section_policy_identity (fallback tightened)
                                         post-fill Guard 3b-ii (new)
backend/services/lob_canon.py            carried_lines_of_business (new)
                                         _flag_families / _row_identifies_policy (new)
backend/services/cover_service.py        _cover_lines_of_business (new), 6 call sites routed
backend/services/sqs_service.py          _ok("lines_of_business") reads the evidenced door
backend/services/field_mapping_integrity.py  names_a_party (new)
                                             is_party_name_field (new)
backend/services/underwriting_consistency.py _declared_domain_check (new)
                                             _drop_values_outside_declared_domain (new)
                                             joined the existing drop chain
backend/services/extraction_service.py   _route_producer_identity (new)
                                         _norm_name_key (new), merge tail wired
backend/services/pdf_service.py          _resolve_submitting_producer (new, authoritative blank)
                                         _line_code_witnesses / _cross_line_code_borrows (new)
                                         _fact_is_measured / _is_checkbox_field (new)
                                         fact_to_form_fields: measured facts never bind /Btn
                                         post-fill Guard 2d-ii and Guard 3c-ii (new)
backend/tests/test_line_identity_11sep.py                    NEW - 73 tests
backend/tests/test_form_improvement_11sep.py                 NEW - 91 tests
backend/tests/test_relationship_preservation_20260815.py     1 fixture corrected, 1 test added
```

---

## Standing lessons

- **A guard applied at twelve consumers and not at the source is a guard with a
  hole.** Kill the value where the fact is born, then guard the box for the
  paths that do not read the fact.
- **One test answering two questions is a fix waiting to become a defect.** The
  2026-08-09 coverage-grant fix silently disabled per-line identity for a month.
  I made the same mistake inside this fix, one level down, on line presence.
- **A test can encode the defect as the expected result.** One did, for four
  weeks, and passed every run.
- **Value fuzzing proves the class; edge matrices find the defects.** The fuzz
  said "the shape decides, not the values". Every actual bug in this session was
  found by the 13-row edge matrix or by an invariant, never by reading the diff.
- **The definitions were already in the repo, unread.** Every fix here routed an
  existing declaration to a layer that had never asked it: `canon_line` for the
  line, the flag's own NAME for its family, `FACT_REGISTRY["validate"]` and
  `answer_options` for the domain, the schedule KEY for a code's owner, ACORD's
  `/Btn` for a checkbox. Nothing needed a new curated table, and that is the
  test of whether a fix generalises.
- **Structural, never a phrase list.** `names_a_party` refuses a CLAUSE rather
  than the sentence that was reported - the 2026-08-08 denylist arc is the
  standing proof that the next wording always gets through.

---

## LIVE RUN 1 - PRE-FORM (11 Sep) - one real defect in my own fix

The kit's pre-form screens found a defect the whole test suite had missed.

**`_drop_values_outside_declared_domain` was INERT in production.** It read
`group["value"]`; the engine builds `{normalized, display, sources:[{raw}]}` and
has **no `value` key**. Every candidate read as `None`, every candidate passed.
14 unit tests were green because they invented the shape. **D22 exactly - the
fixture was easier than reality.** Live symptom: a card comparing `is_renewal`
`"true"` with `"Renewal of BBC7263 - 25"`.

Fixed by reading the printings the engine actually builds. Tests rewritten to
the real shape, plus one that drives the ENGINE end to end - the only kind that
could have caught it. Proved they bite (reverting the reader = 3 failures).

**Then the narrower fix broke six SYS-07c tests, and that was the more important
find.** Reading `FACT_REGISTRY["validate"]` as a domain fights a shipped design:
SYS-07 / SYS-07c exist because documents express Yes/No in OPEN vocabulary -
"Underwritten", "X", a tick, "Incl." - and the lexicon LEARNS those words. A
boolean validator applied here deleted the very cards that module raises.

**Decision: the domain check reads a CLOSED `answer_options` list only, never a
bare validator.** That covers the client's actual example (`gl_form_type` is
Occurrence or Claims-Made; a coverage-form NAME is neither) and leaves
open-vocabulary booleans to the module that owns them. Second condition kept: a
NON-ANSWER ("TBD", "N/A") is never dropped - an absence is not a wrong value, it
is the producer's question.

**`is_renewal` "true" vs "Renewal of BBC7263 - 25" is therefore NOT fixed, and
should not be** - it is the document's way of saying yes, a normalisation job
for SYS-07, logged below.

Suite **7,629 passed / 1 failed / 21 skipped**.

### Findings from the same screens - none are regressions

| # | Finding | Verdict |
|---|---|---|
| L1 | `is_renewal` compares a boolean to a sentence | SYS-07 normalisation gap, not item 10. Open |
| L2 | `EMC Property and Casualty Company` renders as a THIRD, unplaced carrier row beside `EMC Property & Casualty` | `strict_entity_key` does not strip a trailing "Company". Cosmetic, fails safe (no conflict raised). Open |
| L3 | Producer still draws a "values differ - confirm" card although the fact now routes correctly | the FACT is routed, the COMPARISON is not - the picker reads per-document facts and never sees the role split. Same class as "guarded the source, not the box". Open, and the card does suggest the right value |
| L4 | Submission integrity warns "Multiple carriers referenced across documents" on a legitimately two-carrier package | pre-existing, untouched by this work. Worth a look |
| L5 | No `gl_form_type` conflict card appeared on Run A | the control may be INERT - needs one check: does `expiring_dec.pdf`'s Review data show `gl_form_type = Occurrence`? If not, the dec's value was never extracted and the control never armed |

### What the pre-form screens CANNOT prove

The Policies table is built by `_line_record_rows`, which never used the grant
test - so **a correct per-line table does not confirm D1**. The fix is in the
STAMPER. ACORD 126's three header boxes are the only proof.

---

# LIVE RUN 1 - GENERATED FORMS (11 Sep) - SCORECARD

Kit: `11sep_test_data/`. Run A = HALVORSEN (dec + narrative, 125/126/127/131).
Run B = MERIDIAN (control dec alone, 125/126/127).

## THE HEADLINE - ROOT CAUSE CONFIRMED FIXED

ACORD 126, on a package where **no coverage line states a premium**:

```
                       BROKEN (predicted)          ACTUAL
  AGENCY               Commercial Risk Solutions   ThinkSmith Agency        PASS
  CARRIER              Employers Mutual Casualty   EMC Property & Casualty  PASS
  NAIC CODE            25186 (wrong pair)          25186 (right pair)       PASS
  POLICY NUMBER        IM 7100 06 04               BBC7263 - 26             PASS
  EFFECTIVE DATE       (blank)                     07/15/2026               PASS
```

ACORD 127 -> `Employers Mutual Casualty / 21415 / 6E7-40-02---26`.
ACORD 131 -> `Employers Mutual Casualty / 21415 / 6J7-40-02---26`.
ACORD 131's underlying grid pairs **each line with its own carrier**, the GL row
reading `EMC Property & Casualty  BBC7263 - 26`.

**D1 is closed on the forms.**

## SCORECARD

| # | Check | Result |
|---|---|---|
| 1-6 | per-line carrier / NAIC / number / dates on 126, 127, 131 | **PASS** |
| 7 | 25186 never printed beside Employers Mutual | **PASS** |
| 8 | ACORD 125 package policy number blank (5 policies) | **PASS** |
| 9 | `IM 7100 06 04` nowhere on any form | **PASS** |
| 10 | Q4 grid pairs each line with its own number; `6E74002` folded | **PASS** |
| 11 | no "multiple policy numbers" conflict | **PASS** |
| 12-14 | cover page LOB = the four real lines only | **PASS** |
| 15 | ACORD 125 LOB ticks = same four | **PASS** |
| 17-18 | Producer block = ThinkSmith / Michelle Smith, old agency absent | **PASS** |
| 20-21 | $2,000,000 in the AMOUNT box, applies-per ticks clean | **PASS** |
| 24-26 | vehicle CLASS `7383` (not 91580); GL grid keeps 91580 / 91585 | **PASS** |
| 25 | no `$91,580` / `$350,000` in a vehicle box | **PASS** |
| 29-30 | real parties kept; **both disclaimers absent from all 8 forms** | **PASS** |
| 34-38 | RUN B: carrier borrowed, per-line numbers, **producer NOT wiped**, LOB, party | **PASS** |
| 23 | gl_form_type conflict card | **INERT** - one value reached the fact (F4) |
| 28 | territory `6679` | **KNOWN LIMIT CONFIRMED, worse than predicted** (F3) |
| 33 | `BM 1234 05 21` | **DROPPED, as pre-measured.** Absent from the Q4 grid |
| 16, 31, 32 | recommendations / 137 CO / questionnaire | not captured |

**Items 1, 2, 3, 4 and 8 verified fixed on the generated forms. Item 5 verified
on the binding half. Item 6 partially - see F2 / F3.**

## FINDINGS

### F1 - MY FIX CREATED A FALSE-ALARM CLASS. Highest priority.

The cover page reports these as Field QA failures:

```
Policy PolicyNumberIdentifier on ACORD 127 shows "6E7-40-02---26"  source value "BBC7263 - 26"
Insurer NAICCode             on ACORD 127 shows "21415"           source value "25186"
Policy PolicyNumberIdentifier on ACORD 131 shows "6J7-40-02---26"  source value "BBC7263 - 26"
Insurer NAICCode             on ACORD 131 shows "21415"           source value "25186"
```

**Every stamped value is CORRECT. Every "source value" is the package scalar.**
`field_qa` compares a stamped box against the flat fact, and the stamper is now
line-aware while the checker is not - so the more correct the forms get, the more
QA failures appear. This is the L3 class one level over: the FACT gained an axis,
the CONSUMER did not.

**Fix:** on a section form, `field_qa` must resolve the expected value from
`_line_records` for that form's line, not from the package scalar - the same door
the stamper uses.

### F2 - Cross-line codes: the guard's reach is narrower than the defect

RUN B's ACORD 126 hazard grid, on a package with **no GL schedule at all**:

```
LOC 1  HAZ 1  CLASS 7398  BASIS "OCCURREI"  TERR CO
LOC 1  HAZ 1  CLASS 7398  BASIS 1           TERR 7398
CLASSIFICATION DESCRIPTION: 7398
```

`7398` is the **vehicle** class from the auto schedule, printed on the GL grid
twice, beside a truncated "OCCURRENCE" in a premium-basis box.

Tested offline: the guard **would** have blanked it if `auto_vin_schedule`
carries the class under any `*class*` / `*code*` sub-key. It did not fire, so
either the class never reached the schedule fact, or the build under test
predates this work. **One diagnostic settles it: Review data on
`control_dec.pdf` - does `auto_vin_schedule` carry `7398`?**

RUN A, ACORD 127 vehicle row: `CLASS 7383` correct, but `TERR 7383` - the class
copied into the territory box. `Vehicle_RatingTerritoryCode` is missing from
Guard 2e's column list, the same omission that left `RateClassCode` out.

### F3 - Territory 6679 landed on the GL form, not the auto form

Predicted as a known limit; it is worse than predicted. The Drive Other Car
territory printed in **ACORD 126's** hazard grid (`TERR 6679` on the GL row). No
schedule witnesses a DOC territory, so no guard can fire. Needs the value
extracted into a schedule, not a wider guard.

### F4 - The claims-made cascade, on a dec that says OCCURRENCE

One sentence in the narrative produced three warnings, and **ACORD 126 was
stamped `PROPOSED RETROACTIVE DATE 07/15/2026`** - an invented retro date - while
neither CLAIMS MADE nor OCCURRENCE is ticked. Field QA simultaneously reports
`GeneralLiability OccurrenceIndicator on ACORD 131 shows "No" but the source
value is "OCCURRENCE"`, so the merged fact IS Occurrence.

Check 23 was therefore inert because only one value reached `gl_form_type` - and
a SECOND signal drives claims-made behaviour independently of the fact.
`gl_form_type` also has **no document authority** (25 facts declare one; this is
not among them), so a narrative can out-vote a declarations page about the
policy's own form basis.

### F5 - Additional insureds promoted to OTHER NAMED INSURED

ACORD 125 printed `Kestrel Terminal Authority` and `City Of Aurora` - both listed
as **Additional Insured** on the dec - in the NAME (Other Named Insured) blocks.
An additional insured is not a named insured. Same class as SYS-09's
certificate-holder defect (2026-09-05) with a different INTEREST word.
`names_a_party` passes them correctly; the defect is the ROUTING, not the
validation.

### F6 - Smaller, all real

| Where | What |
|---|---|
| Cover page | `PRIOR CARRIER: Commercial Risk Solutions` - an AGENCY in a carrier field |
| ACORD 125 additional interest | `PHONE (303) 555-0110` on Wells Fargo's row - the OLD AGENCY's phone on a lender's interest |
| ACORD 127 | phantom vehicle row 2, `2012 Subaru Outback` with no VIN - one vehicle in the document |
| ACORD 126 | `EMPLOYEE BENEFITS $1,000,000` invented - the documented SYS-06 open item, still open |
| ACORD 126 | `UNINSURED / UNDERINSURED MOTORIST: $1,000,000` - the AUTO limit on the GL section |
| ACORD 126 | `OtherCoverageLimitAmount 1,000` - the GL deductible in a limits box |
| ACORD 125 | CARRIER = `EMC Property and Casualty Company` - one line's carrier as THE package carrier. The NAIC beside it correctly stayed blank |
| interests | address line 1 repeated into line 2 (`800 Walnut St` twice) |
| RUN B ACORD 125 | CONTACT NAME = `Dana Whitfield` - the AGENT in the APPLICANT's contact box, SYS-09 recurring |
| ACORD 127 | driver name renders `Erin` / `toya Royal` - mangled cell |
| RUN B ACORD 127 | `$ 7` in a deductible box - comp/collision symbol 07 bleeding in |

### F7 - Boundary probe: cost measured

`BM 1234 05 21`, a real policy number in ISO edition shape, is **absent from the
Q4 grid**. Pre-measured and confirmed. Blank over wrong, so not a correctness
failure - but ask Brent whether any carrier in his book numbers policies this way.

## RUN B - the control did its job

Producer `Cascade Risk Partners` **survived** (the regression my own fix caused
once and a test caught). Single carrier borrowed onto 126 and 127 with the right
per-line policy numbers. Per-line premiums stamped correctly - the OLD priced
path is unchanged. Party filled. Cover LOB correct.

**Its one real failure is F2**, and that is what a control is for.

## STANDING LESSON FROM THIS RUN

**Making one layer line-aware makes every layer that is not line-aware start
lying.** D1 fixed the stamper and immediately turned `field_qa` into a
false-alarm generator, because the checker still resolves "the source value"
from a flat scalar. When a fact gains an axis, every consumer of that fact needs
the axis in the same commit - the rule this project already learned for
harvesters ("when you add a new way to SURFACE something, extend the harvester in
the same commit").

---

## F2 RESOLVED - it is an EXTRACTION gap, and my guard is one-directional

> **SUPERSEDED by ROUND 2.** The fix below was shipped on the same day -
> `auto_vin_schedule` gained `class_code` and `territory` in prompt v19 and
> the fence is now BIDIRECTIONAL. Kept for the witness census and the D22
> table, which are still accurate. See **F2 / F3** under ROUND 2.

`Review data` on `control_dec.pdf` settles it:

```
Auto Vin Schedule
  vin: 1FT7W2BT5KEC12345; make: Ford; year: 2019; model: F-250;
  coll symbol: 07; comp symbol: 07          <- NO CLASS. 7398 is absent.

Dec Page Entries
  ... 1FT7W2BT5KEC12345, 7398, ...          <- present, but UNLABELLED
```

The extraction schema declares
`auto_vin_schedule: [{year, make, model, vin, body_type, gvw, comp_symbol,
coll_symbol}]` - **no class, code or territory column.** The model was never
asked for the vehicle class, so no witness could exist and the guard could not
have fired. **The guard is innocent; the schema is the gap.** Deployment is NOT
implicated.

### The witness census - measured, not assumed

| schedule fact | line | can witness a code? |
|---|---|---|
| `gl_class_code_schedule` | general_liab | YES - `class_code`, `classification`, `territory` |
| `gl_class_codes_by_location` | general_liab | YES - `codes` |
| `wc_class_codes` | workers_comp | YES - `code` |
| `auto_vin_schedule` | auto | **NO** |
| `auto_drivers` | auto | **NO** |
| `auto_covered_symbols` | auto | **NO** |
| `inland_marine_items` | inland_marine | **NO** |

So the fence is **one-directional**: a GL code landing in a vehicle box is
caught (the client's reported case, verified live - `91580` blanked); a VEHICLE
code landing in a GL box cannot be, because nothing witnesses it.

### D22, THREE TIMES IN ONE SESSION - name the class

Every defect I introduced this session was the same shape: **a check reading a
key the extraction schema does not emit, with a test fixture that invented it.**

| # | Check | Key it read | Reality |
|---|---|---|---|
| 1 | `_drop_values_outside_declared_domain` | `group["value"]` | engine builds `{normalized, display, sources:[{raw}]}` |
| 2 | `_LINE_EVIDENCE_KEYS` (pre-existing) | `"limit"` | `coverage_lines` declares no limit |
| 3 | `_line_code_witnesses` | `*class*` on `auto_vin_schedule` | no code column exists |

All three passed their unit tests. **A guard is only as real as the keys its
inputs actually carry** - and the fixture is where that lie lives.

`test_every_witness_subkey_is_declared_in_the_extraction_schema` is the standing
guard: it fails the build if a witnessing schedule loses its code column, and it
fails the build if `auto_vin_schedule` GAINS one (a signal to invert the
one-directional test, not to leave a stale claim behind).
`test_the_fence_is_ONE_DIRECTIONAL_and_this_pins_why` asserts the real behaviour
so nobody mistakes it for symmetry again.

### The fix, when approved

Add `class` (and `territory`) to `auto_vin_schedule` in the extraction schema.
Not shipped here - it is a prompt change (`improving-ll.md` event, PROMPT_VERSION
bump, extraction cache invalidation) and it moves values, so D6.

**It pays twice:** the guard gains its missing witness, AND ACORD 127's CLASS box
starts filling deterministically instead of from gap fill - which is where Run
A's `7383` came from, and why Run B's `7398` reached the GL grid in the first
place.

### Also visible in the same dump - root cause of a Run B finding

```
Contact Name           Dana Whitfield      <- the APPLICANT's contact person
Producer Contact Name  Dana Whitfield      <- the PRODUCER's contact person
```

The agent's name is written to BOTH, which is why ACORD 125 printed
`Dana Whitfield` in the applicant's contact box. RULE 15 forbids it explicitly;
the model disobeyed, and `_ROLE_BLIND_FACTS` blinds `contact_*` on a
**certificate** only (SYS-09) - never on a dec page. The structural argument
SYS-09 used for certificates applies here too: a declarations page has a
producer/agent block and no applicant-contact box. Candidate fix, owner's call.

Tests after the correction: `test_form_improvement_11sep.py` +
`test_line_identity_11sep.py` = **170 passed**.

---

# ROUND 2 (11 Sep) - the four live findings, at their root cause

Round 1 shipped the stamper fixes and a live run verified five client items on
the generated forms. It also produced four findings, one of them a regression
of my own. This section is what closed them.

## F1 - THE CHECKER DID NOT FOLLOW THE STAMPER

**Root cause, and it is a class rather than a bug.** On 11 Sep the section-form
identity boxes stopped reading the package scalar: ACORD 127's policy number
comes from the AUTO coverage line, ACORD 131's from the UMBRELLA line. The FACT
gained an axis; `field_qa` did not. So it compared every stamped box against
the flat fact and reported four failures whose stamped values were all correct.

```
Policy PolicyNumberIdentifier on ACORD 127 shows "6E7-40-02---26"  source "BBC7263 - 26"
Insurer NAICCode             on ACORD 127 shows "21415"           source "25186"
Policy PolicyNumberIdentifier on ACORD 131 shows "6J7-40-02---26"  source "BBC7263 - 26"
Insurer NAICCode             on ACORD 131 shows "21415"           source "25186"
```

Reproduced verbatim offline, then reduced to **0** by the fix. The negative
control still fails, and now names the RIGHT expected value (`6E7-40-02---26`
on the auto form, not the GL number).

**`pdf_service.authoritative_expected_value(form_id, field, facts, schema)`** is
the fix. It asks the same `_AUTHORITATIVE_BLANK_RESOLVERS` chain that FILLED the
box - the contract `map_facts_to_form` and `compute_form_gaps` already consult -
so the checker cannot drift from the filler and there is no second list to keep
in step. Three answers, and the caller acts on each differently:

| result | meaning | what QA does |
|---|---|---|
| `_AUTH_UNOWNED` | nothing claims this box | compare against the source fact, exactly as before |
| a value | the owner's value | THAT is the expected value |
| `None` | an owned blank | the scalar is provably not this box's source of truth - nothing to compare |

### The first cut was wrong, and a test I wrote caught it

I consulted the owner only when the naive check DISAGREED - cheaper, and it
closed all four reported failures. It also left the client's own reported
defect passing silently: ACORD 131 stamped with the GENERAL LIABILITY policy
number **equals** `policy_number`, so the naive check agreed and the owner was
never asked.

**Agreeing with the package scalar is not proof of correctness.** The owner is
now asked first, on every box that has a bound fact and a stamped value.
Measured cost on a 5-form package at a realistic 40% fill: **398 ms**, 30 owner
lookups. On the pathological case (all 1,959 fields stamped) it is ~450 ms
added to a post-generation advisory pass. Acceptable, and it is the only shape
that is correct in both directions.

## F5 - AN ADDITIONAL INSURED IS NOT AN ADDITIONAL NAMED INSURED

**Root cause: the fact was never defined.** `additional_named_insureds` is a
bare `[string]` in the extraction schema with **no rule in the prompt at all** -
the identical shape D2 found on `lines_of_business`. Two roles one word apart,
and nothing told the model, the merge or the stamper which was which. The
declarations printed a SCHEDULE OF INTERESTS whose INTEREST column read
"Additional Insured" verbatim; the names came back here and
`_SCHEDULE_REGISTRY` stamped them into `NamedInsured_FullName_B/C` - ACORD
125's Other Named Insured roster. An Other Named Insured shares the policy.

**Two halves, because a prompt is not a guarantee (H1-K).**

1. **v19 defines both lists**, each naming the other as the correct home.
2. **`_names_the_document_calls_additional_insureds`** reads the VERIFIED dec
   entries - the one fact that still carries the interest word, copied verbatim
   and checked against the uploaded text. A roster name is blocked only when
   the entries print it under an ADDITIONAL INSURED label **and never** under a
   NAMED INSURED one. The interest word counts whether it is the row's label or
   the schedule's section heading.

**This keeps the owner's 2026-09-06 ruling intact, and that is the whole design
of it.** That ruling refused a wholesale block on `additional_insured_names`
because *a genuine subsidiary is sometimes listed as an additional insured too*.
Positive evidence in BOTH directions is what lets both be true: a party printed
under both labels keeps its place; one printed only as an additional insured
does not. No dec entries, or entries that never name the party, means no
opinion at all.

Measured: reported case dropped, subsidiary kept, legacy sessions unchanged,
SYS-09's certificate-holder door still biting.

## F4 - TWO CHANNELS FOR ONE TRUTH, AND ONLY THE WEAKER ONE WAS READ

The package carries the GL coverage basis twice:

```
  gl_form_type        the STATED value  ("OCCURRENCE", off the declarations page)
  gl_is_claims_made   a DETECTOR        (a boolean over the whole document text)
```

Nothing compared them, and the detector alone gated all four consumers - the
retroactive-date resolver, the cross-form rule and two SQS deductions. One
narrative sentence set the flag on a package whose dec says OCCURRENCE, and
ACORD 126 printed **PROPOSED RETROACTIVE DATE 07/15/2026**: a date no document
states, for a concept an occurrence policy does not have.

**v18's prompt already forbids this in terms** - *"do NOT set true when the
document states the GL form is written on an OCCURRENCE basis"* - and the model
did it anyway. H1-K, live.

**`coverage_evidence.gl_is_claims_made(facts, flags)`** is the one door, and all
four consumers read it; `test_every_consumer_reads_the_door` greps `services/`
and fails the build on a fifth raw read. The rule: **the stated basis outranks
the detector, and only where the document has actually spoken.**

- dec says OCCURRENCE, flag true -> **not** claims-made. Retro boxes owned blank.
- dec says CLAIMS MADE, flag false -> claims-made. *A gain: that policy's retro
  boxes used to be blanked for the wrong reason.*
- dec says nothing -> the detector decides, exactly as before.
- dec cell names BOTH (GL occurrence + EBL claims-made, the commonest real
  shape) -> no verdict. Resolving that by word order would be a coin flip on a
  coverage fact.

## F2 / F3 - THE FENCE WAS ONE-DIRECTIONAL BECAUSE THE SCHEMA HAD NO AUTO CODE

`auto_vin_schedule` declared `{year, make, model, vin, body_type, gvw,
comp_symbol, coll_symbol}` and **no class, code or territory column**. So ACORD
127's CLASS box had no fact and fell to gap fill, and Guard 2d-ii had no witness
for an auto code - a GL class on a vehicle row was caught, a vehicle class on
the GL hazard grid could not be.

**v19 adds `class_code` and `territory`** (`improving-ll.md` **C87**). Measured
on the live values:

```
  ACORD 126 (GL)    CLASS 7398   -> BLANKED   "printed by this package's auto schedule"
                    TERR  6679   -> BLANKED   <- F3, previously unwitnessable
                    GL class     -> kept
  ACORD 127 (auto)  CLASS 91580  -> BLANKED   <- the client's reported case
                    CLASS 7383   -> kept
```

### F3's territory is on the DRIVER, not the vehicle - caught before the run

Reading the kit rather than trusting the fix: the client says *"territory 6679 ... appears
in the Auto **DRIVE OTHER CAR** section"*, and that schedule prints its territory against
the NAMED INDIVIDUAL. `auto_vin_schedule.territory` alone left 6679 unwitnessed, so v19
also adds `territory` to `auto_drivers`.

**Evidence only** - ACORD 127 has no driver territory box, so it fills nothing and gives
the fence its witness. **`class_code` is deliberately NOT added there**: a driver schedule
prints an NCCI class (the kit's trap row carries `8810`, Clerical) and calling that an AUTO
code would let the fence blank a real WC class on the ACORD 130. A territory has no twin.

```
  witnesses   6679 -> auto        8810 -> workers_comp      7383 -> auto
  ACORD 126   TERR 6679  -> BLANKED       GL class 91580 -> kept
  ACORD 130   WC 8810    -> kept
```

`Vehicle_RatingTerritoryCode` also joined Guard 2e - it was read there as the
thing to compare AGAINST and never checked itself, the same omission that left
`RateClassCode` out. That was F2's other half (`TERR 7383`, the class copied one
cell right).

### It broke the ghost-row sweep, and two existing tests caught it

Registering the two columns made a RATING code an identity anchor, so a phantom
row carrying only a leaked GL class code "had an identity" and survived - the
2026-08-13 defect resurrected by its own fix.

`_unanchored_schedule_row_fields` now derives its anchors through the same
`_CODE_SUBKEY_RE` the fence uses (one definition, hoisted to the top of the
file): **a rating code says what a row COSTS, never what it IS.** Measured
reach: 10 of 131 registered columns - the two v19 ones, six WC code columns and
two loss-status codes. Wider than intended and correct anyway, because the sweep
only ever clears a GAP-FILLED cell: a real WC class row is deterministic and
never a candidate, while a bare class code invented in row C with no payroll,
state or duties beside it is the fabricated-rating-row defect H3-D reported.
`test_no_schedule_root_loses_every_identity_anchor` pins that no root is left
without anchors.

---

## ROUND 2 - decisions taken

| # | Decision | Why |
|---|---|---|
| R2-a | The checker asks the STAMPER's chain, not a copy of its rules | A second list drifts. `_AUTHORITATIVE_BLANK_RESOLVERS` is already the shared contract, so a resolver added there is honoured by QA on the same commit |
| R2-b | Ask the owner on EVERY bound+stamped box, not only on disagreement | Agreeing with the package scalar is not proof of correctness - that shortcut let the client's own reported defect pass silently |
| R2-c | An owned blank means "do not compare", not "report a mismatch" | The scalar is provably not that box's source of truth; comparing to it can only manufacture a false alarm |
| R2-d | F5 reads the DEC ENTRIES, not `additional_insured_names` membership | Membership alone would reverse the owner's 2026-09-06 ruling. The entries carry both labels, so the test can be positive in both directions |
| R2-e | The STATED basis outranks the DETECTOR, never the reverse | A declarations page is the policy stating its own basis; a flag raised somewhere in 271 pages is a mention, and a mention has never been proof anywhere else in this pipeline |
| R2-f | A value naming BOTH bases returns no verdict | GL occurrence + EBL claims-made in one cell is the commonest real shape. Word order is not evidence |
| R2-g | Fix F2/F3 with a SCHEMA column, not a wider guard | It pays twice - the fence gains its witness AND the CLASS box fills deterministically instead of from gap fill, which is where the wrong codes came from |
| R2-h | A rating code is never a row identity | Derived through the fence's own regex so "is this a code?" has one answer in this file. Two copies is how these two layers drifted apart |

## ROUND 2 - files touched

```
backend/services/pdf_service.py           authoritative_expected_value (new, public door)
                                          _AUTH_UNOWNED (new sentinel)
                                          _resolve_claims_made_dates -> the one door
                                          Vehicle_RateClassCode / RatingTerritoryCode bound
                                          Guard 2e: RatingTerritoryCode now checked
                                          _unanchored_schedule_row_fields: rating codes
                                            are not identity anchors
                                          _CODE_SUBKEY_RE hoisted to one definition
backend/services/field_qa.py              the owner is consulted before the package scalar
backend/services/coverage_evidence.py     gl_form_basis / gl_is_claims_made (new door)
backend/services/cross_form_validator.py  routed to the door
backend/services/sqs_service.py           routed to the door (2 sites)
backend/services/extraction_service.py    prompt v19 (3 schema definitions)
                                          _names_the_document_calls_additional_insureds (new)
                                          _roster_blocked_names folds it in
backend/tests/test_form_findings_11sep.py NEW - 38 tests
backend/tests/test_form_improvement_11sep.py  the one-directional pair INVERTED
backend/tests/test_h3_wc_data_capture.py  version pin v18 -> v19
improving-ll.md                           C87
```

## ROUND 2 - D6, values and scores move

| Change | Direction |
|---|---|
| Vehicle CLASS / TERRITORY fill deterministically instead of from gap fill | fill rates **UP**, correctness up |
| Cross-line codes blank on BOTH forms | fill rates **DOWN** slightly, correctness up |
| False claims-made warnings disappear on occurrence policies (3 rules) | caps released, scores **UP** |
| Additional insureds leave the ACORD 125 Other Named Insured roster | fill rate **DOWN** slightly, correctness up |
| Field QA stops reporting correct per-line values as failures | the QA fail count drops on every multi-line package |
| Every cached extraction is invalidated by the v19 bump | first upload per document after deploy pays a full extraction |

## ROUND 2 - the file recovery, recorded because it cost real time

Mid-session I ran `git checkout -- services/extraction_service.py` to undo a
botched prompt edit and **wiped the whole of round 1's uncommitted work in that
file** - `_line_entry_identifies_policy`, `_LINE_IDENTITY_KEYS`, the producer
routing, the form-number guard and the merge-tail wiring.

Recovered in full from `services/__pycache__/extraction_service.cpython-314.pyc`
(written at 13:19, after the edits): `marshal.loads` on the code object gives
every function's bytecode, constants, names AND its complete docstring. The
rebuild was then proved rather than assumed - instruction-by-instruction
comparison of the recompiled source against the lost build:

```
  _drop_form_numbers_from_policy_facts   IDENTICAL BYTECODE  (97 instrs)
  _is_policy_number_fact                 IDENTICAL BYTECODE  (37)
  _line_entry_identifies_policy          IDENTICAL BYTECODE  (104)
  _norm_name_key                         IDENTICAL BYTECODE  (19)
  _route_producer_identity               IDENTICAL BYTECODE  (406)
  merge_facts call order                 IDENTICAL
```

**Lessons, both worth keeping.** `git checkout --` on a file with hours of
uncommitted work is not an undo, it is a delete - stash or copy first. And a
fresh `.pyc` is a complete recovery source for logic AND comments, which is
worth knowing before assuming the work is gone.

---

## STILL OPEN after round 2

| Item | Note |
|---|---|
| **9 - umbrella $3M -> $1M** | **PARKED ON A CLIENT RULING.** The client said opposite things on 17 Aug (*an unresolved fact must remain unresolved*) and 11 Sep (*the current limit appears to be $1M*). `services/narrative_facts.py` already mines `{subject, from, to, as_of, policy_number}` and its docstring is literally this case; it handles 5 of 10 realistic phrasings and only ANNOTATES. Get the ruling, then: widen the input beyond 7 narrative fields, widen the phrasing, decide resolve-vs-annotate |
| 7 - ACORD 137 tier | The rule fires at `needs_confirmation`. Promoting it reverses Brent's own ruling - his call |
| 11 - confirm or correct | An unbuilt feature. With rows present we ask NOTHING; the client wants them shown for confirmation |
| F6 (11 smaller findings) | Logged in the round 1 section. None blocking. The two with a named root cause are `contact_*` on a dec page (`_ROLE_BLIND_FACTS` blinds it on certificates only) and `PRIOR CARRIER` holding an agency name |
| F7 - `BM 1234 05 21` | A real policy number in ISO edition shape, dropped as a form number. Blank over wrong, so not a correctness failure - ask Brent whether any carrier in his book numbers policies this way |
| `limit` key on `coverage_lines` | Would make the GRANT test two-sided as its own constant claims |
| Producer: the logged-in agency | `users.organization_name` is the only thing that can tell an incumbent broker from a replaced one. Not plumbed into the merge. D3's honest limit |
| `ClassificationDescription` holding a bare code | The fence is scoped to CODE boxes; widening it to description boxes risks blanking legitimate descriptions that mention a code. With the class column now bound the real description should arrive from the GL schedule |

## ROUND 2 - standing lessons

- **When a fact gains an axis, every consumer needs the axis in the same
  commit.** F1 is that rule violated one week after this project wrote it down
  for harvesters. The general form: *a fix that makes one layer smarter makes
  every layer that did not move start lying.*
- **Agreement is not proof.** A checker that only investigates disagreement
  cannot see a wrong value that happens to match the thing it compares against -
  which was the client's literal reported defect.
- **Two channels for one truth, and nobody picked a winner.** D2 found it on
  coverage lines, F4 on the coverage basis. Both times the STATED value was
  right and the derived one was being read instead.
- **A prompt is not a guarantee - proved twice more this round.** v18 forbade
  the claims-made inference in the exact words the model then ignored. Every
  prompt change here shipped with a deterministic partner.
- **An anti-rot test that fires is the test working.** Both guards that failed
  this round printed their own instructions for what to do next, and both were
  right.

---

# ROUND 3 (11 Sep) - LIVE RUN 2, and ONE sentence behind five defects

Run A = HALVORSEN (dec + narrative, 125/126/127/131). Run B = MERIDIAN
(control dec alone, 125/126/127).

## WHAT ROUND 2 CLOSED, CONFIRMED ON THE FORMS

| Check | Result |
|---|---|
| **F1** - the four Field QA identity failures | **GONE.** One value mismatch left on the whole cover page, and it was R4 below |
| **F4** - PROPOSED RETROACTIVE DATE on 126 | **BLANK.** 131 prints `COVERAGE BASIS: OCCURRENCE`. No claims-made warnings anywhere |
| **F5** - Kestrel / City of Aurora as Other Named Insureds | **GONE at the source.** v19 sent them to `risk_transfer.additional_insured_names`; `additional_named_insureds` does not exist on the package |
| **F3** - territory 6679 on the GL hazard grid | **GONE** |
| Per-line identity, all three section forms | 126 `EMC Property & Casualty / 25186 / BBC7263 - 26`, 127 `Employers Mutual / 21415 / 6E7-40-02---26`, 131 `.../ 6J7-40-02---26` |
| 131 underlying grid | Auto row `Employers Mutual Casualty`, GL row `EMC Property & Casualty BBC7263 - 26` |
| 125 Q4 grid | four lines, four numbers, each its own |
| 125 LOB ticks | the four real lines; no phantom |
| Producer block, all four forms | `ThinkSmith Agency` / `Michelle Smith`; the old agency absent |
| v19 columns arrived | `class code: 7383` (A), `class code: 7398` (B), `territory: 6679` on the DRIVER row (A) |

## THE ONE SENTENCE

Every defect left was the same thing in a different place:

> **An empty box beside a populated record gets filled from whatever is
> nearest, and nothing asks whether that thing belongs there.**

Five faces, five root-cause fixes.

## R1 - A GRID WITH NO EVIDENCE FOR ITS OWN LINE

**Run B's ACORD 126 schedule of hazards, on a package with no GL classification
at all:**

```
  LOC 1  HAZ 1  CLASS -   BASIS "Symbol 07"  EXPOSURE 1   TERR CO
  LOC 1  HAZ 1  CLASS -   BASIS "NO"         CLASSIFICATION DESCRIPTION: F-250
  LOC 1  HAZ 1  CLASS -   BASIS "NO"         CLASSIFICATION DESCRIPTION: 2019
```

The class-code boxes were clean - round 2's fence did its job. Everything
*else* in the row is the auto schedule, laundered through a General Liability
form.

**Root cause: `_resolve_gl_hazard_row` returned `"UNMATCHED"` when the GL
schedule fact was ABSENT**, on the stated reasoning that *"suppressing on no
evidence would delete a schedule the extractor merely missed"*. That was a
PREDICTION, and it was never measured. Three live runs have now measured it:

| run | schedule missing | what gap fill actually produced |
|---|---|---|
| 2026-08-13 | `auto_vin_schedule` | GL class `91585` as a vehicle's RATE CLASS, `$10,000` COST NEW, the UM deductible |
| 11 Sep r1 | GL schedule | vehicle class `7398` twice, `TERR 7398`, `TERR CO` |
| 11 Sep r2 | GL schedule | `Symbol 07`, `CO`, `NO`, `F-250`, `2019` |

**Not once did it recover a schedule.** Gap fill cannot read a schedule that is
not in the document, and it cannot attribute what it does find to a line - that
is the whole D1/D5 lesson. Asked for classifications a package does not have,
it reaches for the nearest table.

**Fixed, and scoped to the ACORD 126 schedule of hazards only** - inside the
two resolvers that already own that grid. The producer is not left guessing:
the package already raises *"GL coverage detected but no class codes found (up
to +12 pts)"* on exactly these packages, which is where a gap belongs.

### I GENERALISED IT TO EVERY LINE-SCOPED GRID AND THAT WAS WRONG

The first cut applied the same rule to the vehicle and WC grids through
`_resolve_phantom_schedule_row`. **Three existing tests caught it inside one
suite run** - `test_table_row_dedup` (x3), `test_phantom_schedule_rows`,
`test_raw_text_verification` - and they were right. Reverted.

**The two grids are not the same case:**

| | alternative source? | verdict |
|---|---|---|
| ACORD 126 hazard grid | **NO.** Its only input is the GL classification schedule, so with no such fact anything gap fill writes there came from another line's table | blank |
| ACORD 127 vehicle grid | **YES.** The vehicles are in the uploaded document as text, so gap fill reading them is a plausible RECOVERY | leave it |

Blanking the vehicle grid would delete a real fleet extraction merely missed -
a **bigger** deletion than the defect being fixed. And the measured 2026-08-13
defect was in row **B**, which `_unanchored_schedule_row_fields` already sweeps.

**A second, independent reason it failed:** nothing separated a grid CELL from
a per-form field that merely repeats.
`Vehicle_Question_ModifiedEquipmentDescription_A/B` is a General Information
answer printed twice, and a "repeats across rows" test blanks it as a vehicle
row - the row-versus-singleton confusion that resolver already carries a scar
from.

**This is the round's own lesson:** the measurement supported ONE grid, and I
extended it to a class on the strength of the sentence rather than the
evidence. The reversal is pinned by
`test_the_vehicle_grid_is_deliberately_NOT_blanked`.

**TWO EXISTING TESTS PINNED THE OLD PREDICTION AND WERE CORRECTED, not worked
around.** `test_no_schedule_at_all_still_reaches_gap_fill` and
`test_no_schedule_at_all_still_reaches_the_model` both asserted "UNMATCHED"
with the falsified reasoning in their docstrings. Same shape as
`test_single_policy_package_still_fills`: a test can encode a prediction that
reality has since refuted. Their INTENT is kept by
`test_a_real_schedule_still_fills_every_cell`.

## R2 - ONE ENTITY, TWO DOCUMENTS, TWO ROWS

ACORD 127 printed a **second 2012 Subaru Outback with no VIN**. Both rows were
correct:

```
  expiring_dec.pdf   year 2012, make Subaru, model Outback, VIN 4S4BRCGC9C3217772
  narrative.pdf      year 2012, make Subaru, model Outback
```

**Root cause: `_dedupe_schedule_rows` merges only on NATURAL IDENTIFIERS.** The
narrative states no VIN, so its row has no key and is never merged. Any two
documents describing one entity produce this whenever the thinner one omits the
identifier - D1's lesson again, one level down: evidence that IDENTIFIES and
evidence that DESCRIBES are different things.

**Fixed:** `_fold_unkeyed_into_matching_rows`. An identifier-less row folds into
a keyed row when it CONTRADICTS NOTHING - every field it states is present and
equal after normalisation - and exactly ONE keyed row matches. A real second
vehicle disagrees somewhere or carries its own VIN; two identical-looking
vehicles with different VINs make a bare "2012 Subaru" ambiguous, and an
ambiguous row is kept rather than folded into a coin flip.

## R3 - AN ADDRESS IS NOT AN IDENTIFIER

On **four forms across both runs**, ACORD's REFERENCE / LOAN # box - tooltip
*"Enter identifier: The loan number, account number or other controlling
number"* - held the interest holder's own street:

```
  Wells Fargo Equipment Finance   REF / LOAN #: 800 Walnut Street, Des Moines...
  Boulder Valley Bank             REF / LOAN #: 1600 Broadway, Boulder, CO...
```

The address is already in the address lines two boxes up. **Root cause:** C22's
declared-type check covers identifier boxes but rejects only a person's NAME, a
VIN and an out-of-range year. An address is none of those.

**Fixed:** `_looks_like_a_street_address` - a street number AND a street WORD
AND a locality (a comma-led one, or a postcode anchored to the end). Three
structural conditions, **no street-suffix vocabulary**, because the 2026-08-08
denylist arc is the standing proof that the next spelling always gets through
one.

**The first draft was measured and tightened.** A 4,000-value sweep of
generated loan / account / policy numbers put **25** through: `2215 73 133
57140,4289` has a leading number and a five-digit RUN, and an unanchored
postcode pattern reads that as a ZIP. With the street word required and the
postcode anchored: **1 of 4,000**, and 1,922 of 1,922 real addresses still
caught. Accepted miss: a bare `8815 Walnut Ave` with no locality - separating
that from an identifier needs the vocabulary this refuses to adopt.

## R4 - AN AMOUNT BOX HOLDS THE AMOUNT

The only value mismatch left on the whole cover page:

```
  Vehicle CombinedSingleLimit EachAccidentAmount on ACORD 131
  shows "1,000,000" but the source value is "$1,000,000 Combined Single Limit"
```

Both are right. `auto_liability_limit` carries the amount AND the STRUCTURE in
one string, because that is how a declarations page prints it; the box takes
only the amount. **Same shape as the address split `expected_value_for_field`
has always done** - a box that receives ONE PIECE of a composite fact must be
compared against that piece.

**Fixed:** an amount box (ACORD's own `*Amount` naming) whose source states
EXACTLY ONE currency figure is compared on the figure. Two figures
(`$1,000,000 / $2,000,000`) state two and are left whole, because picking one
would be a guess.

## R5 - A PARTY STATED UNDER ONE ROLE IS NOT A PARTY UNDER ANOTHER

ACORD 127 printed **`Kestrel Terminal Authority` - an ADDITIONAL INSURED - as
the NAME OF OTHER OWNER of the applicant's Subaru.** A false statement of
vehicle ownership on a signed application.

This is SYS-09's class (certificate holder printed as a named insured,
2026-09-05) and F5's class (additional insured printed as a named insured) in a
third wording. F5 moved the name out of the roster; gap fill re-homed it.

**Fixed:** `_party_in_the_wrong_role_box`. Positive evidence both ways:

* the box must NAME a role. ACORD marks its per-slot clause with *"As used
  here,"* - row C of `AdditionalInterest_FullName` says *"this is the name of
  the other OWNER of the vehicle"*, row A says nothing beyond the shared
  preamble. **An unasserted box is never judged**, which is what leaves an
  ordinary loss payee row alone.
* the DOCUMENT must state roles for that party (`stated_party_roles`, read off
  the verified dec entries - the only fact that still carries the interest
  word). Silence is no opinion.
* none of the party's stated roles may match the box's. A party the document
  calls an owner keeps the owner row.

**The role words are HARVESTED from ACORD's own schemas** -
`..._Interest_<Role>Indicator_*` across all 17 - so a form that gains an
interest type is covered the day it ships and there is no vocabulary to drift.

*First cut failed and the test caught it:* reading the WHOLE tooltip made every
row assert "additional" (from the shared preamble), so a party labelled
"Additional Insured" matched every row and the guard was inert. The *"As used
here"* marker - a convention this file already relies on - is what separates the
slot's own clause from the boilerplate.

### AND THE ROLE SOURCE WAS WRONG - D22, FOURTH TIME

Caught by reading run 3's pre-form data instead of trusting the fix. The first
version read the party's role off the verified dec entries' LABEL and SECTION.
That works when a document prints `Additional Insured: Acme Corp` as a
label:value pair - which is what my fixture assumed - and does **not** work on a
TABLE, which is how every real schedule of interests is laid out. Extraction
records one entry PER CELL, so the live kit gives:

```
  label   "NAME OR ORGANIZATION"                    <- the role is NOT here
  section "SCHEDULE OF ADDITIONAL INTERESTS"
  value   "Kestrel Terminal Authority"
  ---- and the role is a SIBLING cell ----
  label   "INTEREST"
  value   "Additional Insured"
```

Read that way, Kestrel arrives as `{name, organization, schedule, additional}`:
the word "insured" absent, and "additional" present for **every party in the
table including a legitimate owner**. The guard would have fired on the right
case for a reason that cannot tell the cases apart.

**The FACT KEY carries the role reliably on every layout.**
`risk_transfer.additional_insured_names`, `loss_payee_name`, `mortgagee_name`
and `certificate_holder` say the role in their own name, structurally. That is
now the source, with the entry label kept only where it names the role itself.

**A second condition was needed too:** only an ACORD ROLE WORD counts as a
stated role. A column heading is not a relationship, and `{name, organization}`
was making a party with no role at all look like a party with the wrong one.

Measured on the live fact shape, all six directions:

```
  Kestrel Terminal Authority     additional/insured -> BLANKED from the owner row
  City of Aurora                 additional/insured -> BLANKED
  Wells Fargo Equipment Finance  loss/payee         -> BLANKED
  John A. Smith                  mortgagee          -> BLANKED
  Rocky Mountain Leasing LLC     (no stated role)   -> KEPT
  A Company Nobody Mentioned     (not in the package)-> KEPT
  ...and the GENERIC interest row keeps every one of them.
```

**F5's deterministic guard has the same blind spot and is left as is** - it
reads the same label/section for "additional insured AND NOT named insured",
and on a cell-per-entry table it contributes nothing. Its braces hold: v19's
prompt change routes those names away from the roster at the source, proven on
two live runs. Logged rather than papered over.

## VERIFICATION

| Check | Result |
|---|---|
| 400 random ACORD 126 packages through the REAL stamper | **0 violations, 0 exceptions.** 199 blanked the grid with no GL evidence, 201 filled it with evidence, 400/400 kept their limits boxes |
| 150 random ACORD 127 packages | **0 violations, 0 exceptions.** No GL code reached a vehicle row |
| SEAM check through `compute_form_gaps` | ACORD 126 with no GL schedule: **0 hazard cells asked of the model**, 33 owned. With a real schedule: the genuinely empty columns stay open |
| SEAM check through `_enforce_post_fill_guards` | R3 and R5 on the live values: address BLANKED / real loan number KEPT / additional insured in the owner row BLANKED / loss payee in the generic row KEPT |
| 3,000 two-document vehicle packages | **0 wrong.** 1,522 same-vehicle pairs folded, 1,478 different-vehicle pairs kept |
| 4,000 generated identifiers vs the address shape | 1 false positive |
| 1,922 generated addresses with a locality | 0 missed |
| New tests `tests/test_form_findings_11sep_round3.py` | **52 passed** |
| Full suite | **7,730 passed / 1 failed / 21 skipped** - the failure is the documented `httpx` ImportError. **Zero regressions** |

## D6 - WHAT MOVES

| Change | Direction |
|---|---|
| A line-scoped grid with no evidence ships blank instead of fabricated | fill rates **DOWN**, correctness up. The gap was already on the score as a recommendation |
| One vehicle stops printing as two | vehicle counts correct; a phantom row's invented cells disappear |
| An address leaves the REFERENCE / LOAN # box | fill rates **DOWN** slightly |
| Field QA stops reporting the CSL amount as a mismatch | QA fail count drops on every split/CSL package |
| A party leaves a role box the document does not give it | fill rates **DOWN** slightly |

## STILL OPEN after round 3

| Item | Note |
|---|---|
| **The producer picker suggests the WRONG value** | `Commercial Risk Solutions` and `Terri Wroblewski` are marked **Suggested** - the expiring agency, which is item 4's whole subject. `_value_completeness` ranks identity candidates by STRING LENGTH, and "Commercial Risk Solutions" (25) beats "ThinkSmith Agency" (17). The FACT routes correctly (the forms print ThinkSmith); the COMPARISON never sees the role axis. **Display only - `CONFLICT_WITHHOLD_KEYS` is empty, so nothing is withheld from the forms.** Fix: route the picker through the same role door `_route_producer_identity` uses |
| **9 - umbrella $3M -> $1M** | PARKED on the client ruling. 131 prints `$3,000,000` |
| Run B lost its per-vehicle comp/coll symbols | Round 1's control carried `coll symbol: 07; comp symbol: 07`; round 2 captured the symbol policy-level instead. One observation, could be v19 shifting attention or ordinary jitter. Watch it |
| `gl_form_type` missed on Run B | The control dec prints `OCCURRENCE` and it reached `dec_page_entries`, but not the fact - so "Specify GL form type (+6 pts)" fires on a package that states it. A `_backfill_empty_facts_from_entries` candidate |
| 127 Q1 answered "Y" on an encumbrance | The question says *"with the exception of any encumbrances"*; a loss payee IS an encumbrance. A quote-topic mismatch, the documented un-fixable class. The NAME half is closed by R5 |
| `EMC Property and Casualty Company` as a third carrier | L2. `strict_entity_key` does not strip a trailing "Company". Cosmetic, fails safe |
| `certificate_holder` still holds the disclaimer | The BOX is guarded, the FACT is not - the same two-sided rule the form number needed |
| `PRIOR CARRIER: Commercial Risk Solutions` | An agency in a carrier field, cover page. F6 |
| Run B `CONTACT NAME = Dana Whitfield` | The agent in the applicant's contact box. `_ROLE_BLIND_FACTS` blinds `contact_*` on a certificate only, never on a dec page. Owner's call |
| 131 ticked `GL WITH STANDARD ISO POLLUTION EXCLUSION` | Nothing in the package states a pollution endorsement. New, unverified |

## ROUND 3 - standing lessons

- **"No evidence, so change nothing" is not neutral.** On a form whose grid is
  about one line, leaving it unowned is an invitation, and three measured runs
  filled it with another line's data. Neutrality has to be earned by
  measurement, not assumed from the shape of the sentence.
- **A test can pin a PREDICTION.** Two did, for months, in their own
  docstrings. Both were corrected against three measurements rather than worked
  around - and the intent they protected was re-tested explicitly.
- **Fixing where a wrong value LIVES does not stop it moving.** F5 got the
  additional insured out of the named-insured roster; gap fill put it in the
  vehicle-owner box instead. A value with no legitimate home needs the role
  rule, not another eviction.
- **Read the whole tooltip and you read the boilerplate.** Every repeating slot
  shares a preamble; only the *"As used here"* clause says what THIS slot is.
  The first cut of R5 was inert for exactly that reason.
- **Measure the sweep before trusting the shape.** R3's first draft looked
  obviously right and put 25 of 4,000 identifiers at risk.

---

# LIVE RUN 3 (11 Sep, 17:37 UTC) - ROUND 3 VERIFIED ON THE FORMS

Kit unchanged: `11sep_test_data/`. Fresh uploads (R2 lives in the merge, so a
regenerate would have proved nothing). Run A = HALVORSEN (dec + narrative,
125/126/127/131). Run B = MERIDIAN (control dec alone, 125/126/127).

## ALL FIVE ROUND-3 FIXES CONFIRMED

| Fix | Evidence on the generated forms |
|---|---|
| **R1** a grid with no evidence for its own line | **Run B's ACORD 126 schedule of hazards is COMPLETELY EMPTY** - all three rows, every column, including both CLASSIFICATION DESCRIPTION cells. Run 2 carried `Symbol 07`, `1`, `CO`, `NO`, `F-250`, `2019`. And Run A's grid still fills correctly from its own schedule: `1 / 1 / 91580 / C / $91,580` and `1 / 2 / 91585 / P / $350,000`, TERR blank |
| **R2** one entity, two documents, one row | **Run A's ACORD 127 prints ONE vehicle.** Row 2 is entirely blank - no year, make, model or VIN. Run 2 printed a second `2012 Subaru Outback` with no VIN |
| **R3** an address is not an identifier | **All six REFERENCE / LOAN # boxes blank** - 125/126/127 on both runs. Run 2: `800 Walnut Street, De` and `1600 Broadway, Bould` |
| **R4** an amount box holds the amount | **Zero value mismatches on either cover page.** The `Vehicle CombinedSingleLimit EachAccidentAmount` line is gone |
| **R5** a party stated under one role | **ACORD 127 Q1 is blank** - no `Y`, no `Kestrel Terminal Authority` as the vehicle's other owner |

## THREE IMPROVEMENTS NOT PREDICTED

| What | Why it moved |
|---|---|
| Run B's ACORD 125 **CONTACT TYPE is now clean** | R3's declared-type check. Run 2 printed `Dana Whitfield` in a CODE box as well as the name box; the type rule caught the name |
| ACORD 131 **no longer ticks GL WITH STANDARD ISO POLLUTION EXCLUSION** | Nothing in the package states a pollution endorsement. Run 2 ticked it |
| **SQS up on Run A** - 125 `70 -> 75`, package `68 -> 69`; warnings 8 -> 7 | The "ACORD 125 missing: contact info" warning retired |

## TWO NEW FINDINGS - the same class, a third and fourth time

Round 3's own standing lesson, proved again within one run:

> **Fixing where a wrong value LIVES does not stop it moving.**

R5 evicted `Kestrel Terminal Authority` from the vehicle-owner box. It
reappeared twice.

### N1 - Kestrel is an additional interest on ACORD 127, ticked LOSS PAYEE

```
  INTEREST row 2   [X] LOSS PAYEE        Kestrel Terminal Authority
                       ADDITIONAL INSURED  <- what the document actually says
                                            1201 Port Of Tacoma Rd
                                            Tacoma  WA 98421
```

**The ROW is right and that is R5 working** - an additional insured belongs in
the additional-interest block, and Kestrel landed there instead of in the
owner row. **Only the TICK is wrong.**

**Root cause, two halves, both in `_resolve_additional_interest_type`:**

1. `_INTEREST_TYPE_FACTS` knows exactly two roles -
   `("loss_payee_name", "LossPayee")` and `("mortgagee_name", "Mortgagee")`.
   An ADDITIONAL INSURED has no entry, so nothing can ever tick that box.
2. The resolver owns **row A only** - `if m.group(2) != "A": return
   _SCHED_SKIP`. Row B has no owner at all, so it inherited row A's interest.

Same shape as everything else this arc: the role is known
(`risk_transfer.additional_insured_names`), and the consumer never asks.

### N2 - Kestrel is a company the applicant LEASES EMPLOYEES TO

ACORD 126 page 4, Q17 *"DO YOU LEASE EMPLOYEES TO OR FROM OTHER EMPLOYERS?"*:

```
  LEASE TO   Kestrel Terminal Authority
```

Pure fabrication - nothing in the package says anything of the kind.

**Root cause: R5's SCOPE, not its rule.** The guard only looks at boxes
`field_mapping_integrity.is_party_name_field` recognises, and that matches the
ACORD party families (`AdditionalInterest|CertificateHolder|LossPayee|
Mortgagee|NamedInsured|...`). The employee-leasing box is in none of them, so
the guard never sees the value.

**The rule is scoped to boxes that LOOK like party boxes, when what it is
really about is any box that asserts a RELATIONSHIP to a named party.** That is
the correction N2 asks for, and it subsumes N1.

## UNCHANGED - all previously logged, none new

| Where | What |
|---|---|
| every interest block, both runs | address line 1 repeated into line 2 (`800 Walnut St` twice; Run B repeats `Boulder`) |
| ACORD 126 | `EMPLOYEE BENEFITS $1,000,000` invented - the documented SYS-06 open item |
| ACORD 125 | CARRIER = `EMC Property and Casualty Company`, one line's carrier as THE package carrier. NAIC correctly blank |
| Run B ACORD 125 | CONTACT NAME = `Dana Whitfield` - the AGENT in the APPLICANT's contact box (SYS-09; `_ROLE_BLIND_FACTS` blinds `contact_*` on a certificate only, never on a dec page) |
| ACORD 127 | driver name splits across the cell - `Erin` / `Royal` |
| ACORD 127 | `FARTHEST TERMINAL 6679`. **The cross-line fence is correct to stay silent** - 6679 is an AUTO value on an AUTO form, so this is a within-line misplacement, a different defect from F3 |
| pre-form | the producer picker still marks `Commercial Risk Solutions` / `Terri Wroblewski` as **Suggested**. Display only - `CONFLICT_WITHHOLD_KEYS` is empty, and the forms print ThinkSmith / Michelle Smith correctly |
| ACORD 131 | Umbrella `$3,000,000` - item 9, parked on the client ruling |
| both runs | `Contact Name` now carries the PRODUCER's contact on Run A as well as Run B. Readiness improved for the wrong reason - the applicant-contact box was filled with the agency's contact |

## SCORES

| | run 2 | run 3 |
|---|---|---|
| Run A - 125 / 126 / 127 / 131 | 70 / 76 / 75 / 80 | **75** / 76 / 75 / 80 |
| Run A package | 68 | **69** |
| Run B - 125 / 126 / 127 | 53 / 29 / 49 | 53 / 29 / 49 |
| Run B package | 42 | 43 |

Run B is unchanged by design: its 29 on ACORD 126 is driven by *"Provide GL
class codes"*, *"Specify GL form type"*, COPE and loss history - every one of
them a genuine gap in the control document. **R1 made that form more honest,
not higher-scoring**, which is the correct outcome: the fabricated hazard grid
was never earning those points.

## WHAT RUN 3 SETTLED ABOUT R1

The reversal it rests on - *"no evidence, so change nothing"* - was reversed on
three measurements. Run 3 is the fourth, and the first to show the corrected
behaviour end to end:

```
  Run B, no GL schedule in the package
     run 2   grid filled with an auto row      (Symbol 07 / CO / NO / F-250 / 2019)
     run 3   grid EMPTY, and the package still says
             "GL coverage detected but no class codes found (up to +12 pts)"
```

The gap reaches the producer as a recommendation instead of reaching the
carrier as a fabricated classification. That was the whole argument for the
reversal, and it holds on a live form.

## NEXT - N1 and N2 are ONE fix

Do not patch them separately. N1 is "the interest tick has no owner past row A
and knows only two roles"; N2 is "the role guard is scoped to boxes that look
like party boxes". Both dissolve into one rule:

> **A box that asserts a RELATIONSHIP to a named party must agree with the role
> the package states for that party - and where the package states a role, the
> box that records it must be filled from that role, not inherited from the row
> above.**

The inputs already exist and are already derived: `stated_party_roles` (the
fact key carries the role), `_acord_interest_roles` (harvested from the 17
schemas). What is missing is the SCOPE - the guard reads
`is_party_name_field`, which is a list of ACORD's party NAME families, not the
set of boxes that make a claim about a party.

---

# ROUND 4 (11-14 Sep) - N1/N2 as one fix, and the producer card

## N1 + N2 - one fix, as predicted
- **N2's root cause was INFLECTION, not scope.** The box tooltip says "leased"; the harvested role is "lease". `_roles_a_box_asserts` now matches the stem plus s/es/d/ed/ing. Honest limit: "contracting" matches "contract"; measured blast radius is the 8 employee-leasing boxes, nothing else.
- **N1:** `_interest_tick_contradicts_its_party` (Guard 2d-iv). Pass 1 clears a tick with ZERO overlap with the row party's stated roles. Pass 2 sets the one tick whose role set equals / contains / is contained by the stated roles - only when exactly one box qualifies and no tick survives on the row.
- The fuzz broke my first cut twice: one pass was ORDER-DEPENDENT (-> two passes), and a row ticked "Other" was not counted as claimed (184 cases; -> every surviving tick claims its row). Partial overlap (LendersLossPayable vs Loss Payee) never sets.
- Tests: `test_form_findings_11sep_round4.py` (21). Fuzz: 8,000 packages, 0 violations.

## The producer card - item 4's surviving half
- Root: both agencies came from one document each, so the name-like tiebreak fell to string LENGTH - `Commercial Risk Solutions` (25) beat `ThinkSmith Agency` (17).
- Fix: `_suggest_for_field` reads the role axis already on every source. Producer identity keys only, and only when exactly ONE candidate is submission-backed. Confidence high (a text-scan-only value is still demoted by the old rule).
- Tests: `test_producer_picker_11sep.py` (29). Fuzz: 6,000 calls, 0 violations.
- Found, not touched: the picker throws on 270 of 288 junk-shaped inputs - identical for `applicant_name`, so pre-existing. Only my helper was hardened.

# ROUND 5 (14 Sep) - two items off the UNCHANGED list

## Address line two repeating its own block
- Root: a third-party address has NO fact (`_addr_*` returns UNMATCHED outside NamedInsured), so each component is its own gap-fill answer and the model copies line one, or the city, into line two.
- Fix: Guard 2d-v `_line_two_repeats_its_block`. LineTwo is blanked when its words appear IN ORDER inside its own LineOne, or when every word is its own city / state / ZIP / county. Only LineTwo is ever touched. Covers all 8 address roots in the 17 schemas (harvest test).
- The unit marker is kept as a token - NOT `normalize_address`, which drops it: "Suite 100" beside "100 Main St" is a real suite. A bare-number line two is never compared with line one.
- Tests: `test_form_findings_11sep_round5.py` (34). Fuzz: 8,000 packages, independent oracle, ZIP+4 included, 0 violations.
- **Incident:** the patch script's `\b` / `\1` collapsed into a BACKSPACE and chr(1) (Bash heredoc escaping). The ZIP+4 fold was dead code while 386 tests passed. Repaired; a test now pins no control characters in the guard's source; every file touched this arc scanned clean.

## The agent in the applicant's contact box (SYS-09, a third wording)
- Measured on the stored per-document facts, both runs: ONE document wrote the agent into BOTH `contact_*` and `producer_contact_*`.
  - Run A narrative: Michelle Smith + phone + email in both pairs.
  - Run B dec page: Dana Whitfield + phone in both pairs.
- The box guard could not act (it needs an email domain; Run B's dec prints none), and the FACT was wrong - so readiness counted Tier 1 contact as answered by the broker's own person.
- Fix at the FACT, per document, before the merge: `separate_contact_twins`. Evidence is the email domain (the SYS-09 door, now ONE copy in extraction_service - pdf_service delegates) or the document's own owner-tagged index entries CONTAINING the value. Disagreeing or absent evidence -> no change. The copy leaves that document only; another document's real applicant contact still merges.
- **D22 check done first, and it changed the design:** Run A's narrative has no index entries at all, so an owner-tag rule alone fixes Run B only. Run B's entry is three cells JOINED - `Cascade Risk Partners | Dana Whitfield | (720) 555-0188`, owner=producer - hence containment, not equality.
- Seam verified: the live Run 3 documents re-merged through `merge_facts` - `contact_*` gone on both runs, `producer_contact_*` intact, per-document copies cleaned (the picker reads those).
- Tests: `test_contact_twins_11sep.py` (24); all SYS-09 suites green. Fuzz: 10,000 documents, independent oracle, 0 violations.

## D6 - SCORES MOVE DOWN. Brent sees this before it ships.

| | before | after |
|---|---|---|
| Run A package (pre-generation) | 70 - Needs Work | **68 - Major Gaps** |
| Run B package (pre-generation) | 37 - Not Ready | 35 - Not Ready |

- Only cause: Tier 1 "Contact information" goes missing (-20 on Tier 1). It had been "answered" by the agent's own name. The label drop on Run A is the honest score, not a regression - and the questionnaire will now ask the client for their contact.

## VERIFICATION
- Full suite: **7,840 passed / 1 failed / 21 skipped** (the documented `httpx` ImportError). +87 tests in rounds 4-5 (picker 29, line two 34, contact 24); zero regressions.

## STILL OPEN after round 5
- ACORD 126 `EMPLOYEE BENEFITS $1,000,000` invented (SYS-06 open item).
- ACORD 125 CARRIER = one line's carrier printed as THE package carrier.
- ACORD 127 driver name split across the cell (`Erin` / `Royal`).
- ACORD 127 `FARTHEST TERMINAL 6679` - within-line misplacement.
- The `certificate_holder` FACT still holds the disclaimer; only the box is guarded.
- F5's dec-entry guard is inert on cell-per-entry tables.
- Item 9 (Umbrella $3M -> $1M) - parked on the client ruling.

## LIVE RUN 4 - what to look at
- Every interest block: line two blank where it repeated line one or the city; a real suite kept.
- ACORD 125 applicant CONTACT boxes blank on both runs; the producer block still prints the agent; readiness lists "Contact information" missing.
- Data Consistency, Producer Name: `ThinkSmith Agency` badged Suggested.
- ACORD 125/127 interest ticks: Kestrel ticks ADDITIONAL INSURED, never LOSS PAYEE; the employee-leasing box stays blank.

## ROUND 4-5 - standing lesson
- A scripted edit can corrupt source behind a green suite. Write patch scripts with the Write tool, `py_compile`, and scan for control characters after every scripted edit.

## 14 SEP - items 4 and 8 on the REAL Orbin package (party chat)
- Item 4 "LIVE-VERIFIED" was measured on HALVORSEN, whose narrative prints the new agency. The real Orbin package names ThinkSmith nowhere - it is the logged-in account - and on the 14 Sep code it still printed CRS / Terri. Fixed from the account; see v1-20AUG.md "ORBIN - who is this party".
- L3 closed: the producer card is not offered once the submitting and expiring agencies are separated.
- STILL OPEN "certificate_holder FACT still holds the disclaimer" - closed at the merge. The COI's own OCR spelling `ForInformationalPurposesOnly` passed the box guard; now refused.
- Live run 4 checklist changes: no Producer Name card on HALVORSEN; Run B (MERIDIAN) prints the TESTER's own agency from the login, not Cascade.

# ROUND 6 (14 Sep) - comparisons that should never happen, and the umbrella as a dated change (comparison chat)

Client items 3, 5, 9, 10. Diagnosed by offline replay of e7084347 / 5037f1a6 plus the literal Field QA rows the producer saw (`sqs_recommendation_audit`). Not the model - no model change, $0.

## Root causes - what he saw, and why
| He saw | Root cause |
|---|---|
| $2M compared with the Per Location / Per Project Y/N box | Dead rule: `..._LimitApplies -> None` sat BELOW `GeneralLiability_GeneralAggregate -> gl_aggregate` (first match wins) |
| A Claims Made tick compared with "Commercial Liability Umbrella Coverage Form" | Field QA compared a TICK with the fact's wording. `gl_form_type` had no definition, so it held the umbrella's form title. 131's umbrella ticks read the GL fact |
| A policy number compared with a form number | The producer confirmed `IM 7100 06 04` (10 Sep). Only `apply_confirmations` stopped reading it - the card, both conflict-key lists and Field QA still did. The carrier's own form references (`CU7001A 11-15`) were offered as policy numbers |
| Separate policies (the four correct 125 Other Policy numbers) as conflicts | Field QA compared line-owned boxes with the one package scalar |
| Umbrella $3M -> $1M as a conflict | No comparison had a time axis. The miner missed a subject AFTER the verb ("Reduced Umbrella Limit from ..."). The withhold read the COI remark's two amounts as rivals |

## Safe half
- `pdf_service.expected_tick_for_box` - a checkbox is compared by the tick its fact implies, never by the fact's wording.
- The specific `LimitApplies*` None rules moved above `gl_aggregate`. `LimitAppliesToCode` (text box) keeps its route.
- `answer_options.option_named_by` - "OCCUR" names Occurrence (the option, or an unambiguous 4+ character truncation). The card folds two printings of one option.
- `underwriting_consistency.usable_confirmations` - one door. A confirmed form number stays on record, never read as an answer.
- Tests: `test_comparison_guards_14sep.py` (40).

## Remaining half
- **A time axis in the one door:** `fact_comparison.dated_change` (+ `fact_term`, `document_as_of`). "Changed" only when: a dated amendment names THAT fact inside the term; exactly two amounts, equal to its from / to; the stating document prints the new one; every old printing is another document dated on or before the change. Anything else stays a conflict.
- The merge writes the current value (`source: document_amendment`, prior kept as history) and the withhold no longer fires on it. Card row `changed`, no review. `narrative_facts` reads a subject after the verb.
- **Prompt v20 -> v21** (`improving-ll.md` C89): `gl_form_type` = the GL part's trigger only; new `umbrella_form_type`. `coverage_basis` canonicalises each document at merge (CG 00 01 -> Occurrence, CG 00 02 -> Claims-made). 131's umbrella ticks read `umbrella_form_type`.
- `_drop_unknown_form_references` - a form-shaped policy-number candidate is set aside only when a verified dec index exists, it names no known contract, and a kept candidate IS one. Never empties the field.
- **One box door:** `pdf_service.box_expectation` - owner first (an owned blank is not compared), then tick or value. Field QA, `verify_stamped_consistency` and the stamper's choice boxes all ask it.
- UI: a read-only "Changed during the policy term - not a conflict" row (now / before / the document's sentence).
- Tests: `test_remaining_fixes_14sep.py` (65). v21 pins moved; `test_dec_index_purge` records the new purge-safe consumer.

## Break-it pass - owner: "tested with all the values that can break them?"
- 75 hostile inputs through merge -> card: **23 breaks in my own fixes. All fixed.**
- Negated / requested / conditional / questioned changes ("was not reduced", "requests it be reduced", "if approved ... will be reduced") stamped $1M silently -> `narrative_facts._asserts_the_change`. An unasserted statement is never a change and never explained as one; the endorsement-date reader still sees its date.
- A reduction then a reversal, or two reductions -> stays a conflict (`dated_change` counts distinct amount pairs).
- "$3M" read as $3 -> the K / M / MM / B multiplier is kept.
- "CLAIMS-MADE OCCUR" (both captions, tick lost) and "Per Occurrence" read as a basis; words that contradict the ISO number -> no basis.
- Real `BOP 7654321 01 26`-shaped policy numbers read as form references -> a form series never runs 5 digits together.
- The checker could not read 131's umbrella ticks -> `umbrella_form_type` joined the option catalogue.
- Tests: +44 (`TestBreakValues`).

## Verified offline on the real packages (e7084347, 5037f1a6)
- `umbrella_limit` changed, merged $1,000,000, nothing withheld. ACORD 131 / 25 print $1,000,000.
- GL basis ticks: Occurrence Yes / Claims-Made No on 126 / 131 / 25.
- `policy_number` scoped. The only conflict left is `producer_name` (party chat).
- The one amendment sentence in either package stays asserted.
- 131 ExcessUmbrella Occurrence / Claims-Made: UNMATCHED (gap fill) until a v21 extraction supplies `umbrella_form_type`.

## D6 - mostly UP (Brent first)
- The umbrella 85 cap goes where it was the only soft stop; 131 fills its umbrella limit; GL basis ticks become deterministic; fewer policy-number conflicts.
- One small DOWN until re-extraction: 131's two umbrella trigger ticks go to gap fill on v20 sessions.
- Cost: v21 busts the extraction cache - one fresh extraction per package, no new call.

## VERIFICATION
- Suite 8,301 passed / 6 failed. 5 were `test_screen_level_coverage_14sep`, rewritten by another chat mid-run; they pass on re-run (14 + 2 xfail). Only `httpx` left. Frontend build clean.
- NOT tested: a live v21 extraction; the "changed" row in a browser.

## Files touched
- services: `answer_options`, `underwriting_consistency`, `pdf_service`, `field_qa`, `fact_comparison`, `narrative_facts`, `extraction_service`.
- frontend: `AcordModal.jsx`.
- tests: `test_comparison_guards_14sep.py` (40), `test_remaining_fixes_14sep.py` (109); pins in `test_h3_wc_data_capture`, `test_line_binding_14sep`, `test_dec_index_purge`.
- docs: `improving-ll.md` C89; `v1-20AUG.md` (three ORBIN comparison entries).

## STILL OPEN after round 6
- ACORD 160 liquor aggregate bound to `gl_aggregate` - owner: leave 160 alone.
- `..._LimitAppliesToCode` (126 "other" text box) keeps its route.
- `producer_name` conflict - party chat.
- Stale 09-10 values on 127 / 131 (renewal-shifted dates, GL NAIC) - line identity.
- Residual risk: a real policy number with a 4-digit-or-shorter series and an MM YY tail can still be hidden from the card's choices. It never changes a stamped value.

## LIVE RUN - what to look at (fresh upload, so it extracts at v21)
- Data Consistency: the umbrella row reads "Changed during the policy term - not a conflict", Now $1,000,000 / Before $3,000,000.
- ACORD 131 / 25 umbrella $1,000,000; 131's umbrella Occurrence / Claims-Made from the umbrella's own trigger.
- GL Occurrence Yes / Claims-Made No on 126 / 131 / 25.
- Field QA: no "$2M vs Per Location", "Claims Made vs form title" or "policy number vs form number" rows.
- Policy number card scoped; no carrier form reference offered.

## ROUND 6 - standing lessons
- The client's literal remark put the subject AFTER the verb; the paraphrased fixture put it first and stayed green (D22, again).
- 105 green tests, then 23 breaks on hostile input. A rule that SETTLES a conflict must prove the sentence asserts the change - write the adversarial case first.

# 14 SEP - items 2 and 7: which lines the package has, and the ACORD 137 fill (lines chat)

The brief called these items 9 and 10. Offline replay of e7084347 (the real 271-page Orbin package), no paid calls.
Detail and rejected alternatives: v1-20AUG.md "ORBIN - which lines and forms the package has" (safe half, full pass)
and "items 9/10 checked through what the client sees".

## Root cause, by layer

| Symptom | Layer | Why |
|---|---|---|
| Cover, score, recommendations and questions listed Property, Crime, WC, Farm, Liquor, EPLI, OCP | **Rules** - fixed | Five doors decided "the package has line X" on a MENTION: a carrier name, a sub-flag, the next row's premium, identity with no grant, a flag the cover never received |
| same | **Extraction** - prompt NOT changed, waiting on owner | `lines_of_business` has no definition in the prompt, so ISO "modifies insurance provided under the following" menus fill it |
| same | **LLM** - handled in code | It put "Employers Mutual Casualty Company" on all 13 endorsement-menu rows and the 3 denied rows |
| ACORD 137 CO filled wrong | **Rules only** | Extraction was right ($1M CSL, $5K Med Pay, $1M UM, $1,000 deductibles, a symbol per coverage). Every 127-shaped resolver read the 137's row letters as vehicles |

## Round 1 - safe half
- `lob_canon._row_identifies_policy`: a NAIC or the row's own policy number only - a carrier name no longer proves a policy. `_flag_families` reads `has_<line>` flags only (`property_has_bi_coverage` was evidencing Property). Live shape: 17 mentioned -> 4 carried.
- `form_service._dec_line_present`: a row printing its own denial before any `$` no longer borrows the next row's premium. ACORD 130 is no longer offered on "Workers' Compensation No Coverage".
- `_FORM_EVIDENCE_FACTS`: 137 -> auto limits, 138 -> garage limits, 133 -> WC payroll (were contractor / equipment / builders risk facts). CLAUDE.md form list corrected (137, 138, 141, 160).

## Round 2 - full pass
- New `services/state_auto_grid.py` owns every 137 `Vehicle_*` box. The section comes from the template's own page heading; the row tables are pinned against both templates' printed labels. The vehicle deductible, phantom row and CSL-or-split resolvers step aside for those boxes.
- Orbin 137 CO: CSL tick + $1,000,000 in "CSL / BI EA PER"; Med Pay $5,000 + sym 2; UM CSL $1,000,000 + sym 2; sym 7 on comp and collision. 264 Truckers / Motor Carrier boxes blank and never asked. Gap-fill questions 327 -> 25.
- The 137 has no UIM box - Colorado UM includes UIM.
- Hired physical damage (the page-1 COMP / COLL deductible boxes) is asked of the document. Orbin's $1,000 comes from the Auto Elite Extension (CA7450 M), which no fact carries. Latent bug closed: on a fleet of three the owned collision deductible landed in the Truckers and Motor Carrier sections.
- `lob_canon`: an explicitly false `has_<line>` flag outranks an identity-only row (a borrowed policy number cannot revive Property / Crime / WC); the no-rows branch drops flag-denied lines (found by the fuzz).
- `cover_service`: every path now receives the session flags. It read `facts["flags"]`, a key facts never carry, so the cover and the score could disagree.
- `arq_service._drop_not_applicable_questions`: a second witness - the stamper's absent-coverage owner for ACORD boxes, `line_presence` for facts (`line_of_fact_key` added). ACORD 130 selected still asks. Orbin's producer no longer gets 4 WC / Employers Liability questions.

## Round 3 - checked through what the client sees
- Asserted on the rendered cover PDF (ReportLab and the plain-text fallback), the narrative fallback, the scorer's Applicant Info row, the 137 through `map_facts_to_form`, and the questionnaire filter.
- Found + fixed: a 137 split-limit part holding four amounts printed `25,000,050,000,010,000,050,000`. A box printed for one amount now only takes a fact stating exactly one (`state_auto_grid._one_amount`); otherwise the document is asked.
- Found, **HELD for the owner's go-ahead**: `display_canonicalizer.canonicalize_currency` keeps only the digits.
  - `$1M` -> `1`, `$5K` -> `5`, `$1,000,000 / $2,000,000` -> `10,000,002,000,000`, `25/50/25` -> `255,025`, `Item 3 $1,000` -> `$31,000`.
  - 911 money boxes on 16 forms; pre-existing. Orbin's own values are full digits, so Orbin prints right. Extraction keeps amounts "as-is", so shorthand reaches facts whenever a document prints it.
  - Proposed fix: expand K / M / million; print a multi-amount value as written. Only changes outputs that are wrong today; no score moves, no LLM cost. Pinned by 2 strict xfails in `test_screen_level_coverage_14sep.py`.

## Verification
- Tests: `test_coverage_presence_14sep.py` 119, `test_state_auto_grid_14sep.py` 73, `test_screen_level_coverage_14sep.py` 16 (14 + 2 xfail) - 208.
- Fuzz, 0 violations after the fixes: the 137 resolver 480 packages + 24 through `compute_form_gaps`; the 137 through `map_facts_to_form` 30; carried lines 900; denied rows 1,000; priced rows 1,000; questionnaire filter 480.
- Suite: 7,999 (round 1) -> 8,238 (round 2) -> **8,314 passed / 1 failed (httpx) / 21 skipped / 2 xfailed** (round 3).
- Test wrong, twice: the layout test's +-8pt window caught the neighbouring row's label (now the nearest label within 14pt); the cover parser only read the ReportLab layout.
- Code wrong, once, found by fuzz: the legacy branch of `carried_lines_of_business` returned flag-denied lines.

## Files touched (lines chat)
- NEW `services/state_auto_grid.py` - owns every 137 `Vehicle_*` box; `_one_amount` (round 3).
- `services/pdf_service.py` - `_resolve_state_auto_grid` (+ `_owned`, registered in `_AUTHORITATIVE_BLANK_RESOLVERS`), `_state_auto_grid_decides` gates in the vehicle deductible, phantom row and auto limit resolvers, one line in `_deterministic_map_inner`.
- `services/form_service.py` - `_row_denies_line`, `_FORM_EVIDENCE_FACTS`.
- `services/lob_canon.py` - `_flag_families`, `_flag_denied_families`, `_row_identifies_policy`, `carried_lines_of_business`.
- `services/cover_service.py` - flags passed on every path, fallback renderer included.
- `services/line_presence.py` - `line_of_fact_key`.
- `services/arq_service.py` - `_asks_about_an_absent_line`; `_drop_not_applicable_questions` takes flags (all three call sites).
- Tests: `test_coverage_presence_14sep.py`, `test_state_auto_grid_14sep.py`, `test_screen_level_coverage_14sep.py` (all new).
- Docs: CLAUDE.md form list (137, 138, 141, 160); v1-20AUG.md (three "ORBIN - which lines" entries); this file.

## D6
- A generated 137 fills more boxes. `_ok("lines_of_business")` can only go DOWN, and only where the line evidence was a carrier-only row, a sub-flag, or identity rows the package's own false flags deny. Orbin unchanged.

## Decisions
- The 137 recommendation tier is Brent's ruling - untouched.
- ACORD 141 / 160 wrong forms: owner said leave alone.
- A 137 page with no evidence either way stays on today's path - never guessed. Two auto families present -> limits and deductibles go to the document.
- No prompt change without the owner.

## Waiting on the owner
1. The money formatter fix (above).
2. Two prompt additions: a `lines_of_business` definition; a hired-auto physical damage fact (limit + comp / coll deductibles). No new calls, ~100-150 tokens on the cached prefix, one fresh extraction per package; can ride v21 if no package has run on it yet.

## STILL OPEN (lines chat)
- ACORD 131 per-form Structural counts EL on a no-WC package (score - Brent).
- The questionnaire still offers some owned-blank boxes (127 PD per accident on a CSL policy).
- The loss-payee question says "property policy".
- A Truckers / Motor Carrier deductible written "$2,500 each auto" is blanked by a post-fill guard (blank, not wrong).
- `tests/test_production_guards.py:31` stubs `reportlab.platypus` at import and never restores it, so later cover tests in a full run get the fallback renderer.
- Not live-verified (a paid run).

## Standing lessons
- A resolver can be right and the PDF still wrong: the display formatter runs after every resolver. Fuzz through `map_facts_to_form`, not the resolver.
- A full-suite run while another chat edits a service produces phantom `inspect.getsource` failures (9 this time). Rerun them alone before believing them.

# ORBIN ROUND 3 (14 Sep) - which value lands in which box (line-binding chat)

Five client defects on the REAL Orbin package (session e7084347, 271 pages): carrier / NAIC / policy / dates not staying with their line; `IM 7100 06 04` in ACORD 125's policy-number box; 126 = Employers Mutual Casualty + 25186; territory 6679 on 126; GL class 91580 on the 127 vehicle row. Scope: every one-line box on 125 / 126 / 127 / 131.
Method: offline replay (plaintext per-document facts -> `merge_facts`; the deployed code exported with `git archive`), the stored `field_state` (the download renders it), and the audit tables. No paid call. **Not the model - no model change.** Short version also in `v1-20AUG.md` "ORBIN ROUND 3"; prompt change in `improving-ll.md` C88.

## Correct answers (the client's)
| Line | Carrier | NAIC | Policy |
|---|---|---|---|
| GL | EMC Property & Casualty | 25186 | BBC7263-26 |
| Auto | Employers Mutual Casualty | 21415 | 6E7-40-02---26 |
| IM | Employers Mutual Casualty | 21415 | 6C7-40-02---26 |
| Umbrella | Employers Mutual Casualty | 21415 | 6J7-40-02---26 |

Term 07/15/2025 - 07/15/2026. One vehicle: 2012 Subaru Outback, VIN 4S4BRCGC9C3217772, class 7383.

## What he saw, who wrote it, why
| Box (deployed) | Written by | Root cause | Layer |
|---|---|---|---|
| 125 policy number `IM 7100 06 04` | post-generation late-stamp | Card offered only `IM 7100 06 04` vs `IM 7201 10 02`; producer confirmed it (00:33:39), forms generated (00:36:36), the late-stamp door stamped it after generation had refused it | extraction + relationship |
| 126 Employers Mutual / 25186 | `arq_service._backfill_and_resolve_present` | Door called `_deterministic_map` with no `_form_id` and no schema, so section forms took the package scalars; the merge had recombined dec `carrier_name` with the COI's `carrier_naic` | relationship |
| 127 / 131 NAIC 25186 | same door | same | relationship |
| 126 TERR 104 / 6679 | gap fill | A real hazard row with an empty territory was sent to gap fill; the model read the auto pages | rule |
| 127 CLASS 91580 | gap fill | No auto class fact; gap-fill chunks carried every line's GL classes; the fence had no dec-entry witnesses | extraction + rule |
| 131 underlying Auto carrier / number, GL number blank | stamper | Compare did not use the same-contract / same-entity doors (`6E74002` vs `6E7-40-02---26`; "Co." vs "Company") | rule |
| 125 term 07/15/2026 - 07/15/2027 | merge | `is_renewal` read off ISO cancellation wording ("or if it is a renewal of a policy issued by") -> term shifted a year | rule |
| 126 EBL $1,000,000 + "0 - 25" | stamper / gap fill | Nothing checked the EBL part is carried; the band came from `num_employees` | rule |

- Extraction, 2 of 2 runs: `coverage_lines` fabricated ties - page-1 rows pairing 6C7 with EMC Mutual, ten "Coverage Part" boilerplate rows, "EMC Insurance", an AAIS / `IM 7100` row (bureau as carrier, form as policy).
- Gap fill: 7 chunks a call, the auto pages in one of them, the facts block showing every line's classes.
- `_carriers_by_line` counts phone numbers as carriers - **deliberately not changed**; header binding does its job now.

## Fixes
**Extraction (`extraction_service`)**
- RULE 16 tightened: entries only from declarations / summary / schedule pages; carrier / NAIC / policy null when the row does not print them; a FORM number is never a policy number; a rating bureau (ISO, AAIS) is never the carrier. v19 -> v20. **Round 6 has since moved both versions to v21.**
- `_scrub_non_contract_identifiers` - per document, before the merge: form-number policy cells and bureau carriers cleared from `coverage_lines`, `underlying_policies`, `prior_coverage_by_line`, `dec_page_entries`.
- `_bind_carriers_to_contracts` - the carrier printed in the first 6 header lines of pages whose header names exactly ONE contract (contracts folded by the same-contract door). Rows rewritten by contract number, or by line when the line has one current contract. A NAIC paired with a replaced carrier is dropped.
- `_pair_carrier_naic_scalars` - `carrier_naic` = the NAIC printed with `carrier_name`'s entity, else dropped (source `derived`).
- `_backfill_vehicle_codes_from_text` - CLASS / TERR from the page, attributed to the NEAREST VIN on the same page; equidistant -> nobody; fills a missing value only, one distinct value only.
- `_renewal_phrase_is_a_statement` - a renewal phrase inside an if / unless / whether / when / provided / except clause is not a statement. Orbin's three ISO clauses rejected; "RENEWAL OF: 6E7-40-02---25", "RENEWAL DECLARATIONS", "This policy is a renewal of BBC7263-25." still read.

**Stamper (`pdf_service`)**
- `_section_carrier_pair`: NAIC via `_naic_printed_with` when the row has none (IM gets 21415 through its entity).
- `_resolve_underlying_policy_row`: carriers keyed by entity, numbers folded by contract (`_fold_contracts`), cross-check through `_same_policy_contract`.
- `_resolve_uncarried_coverage_part` (EBL): owned blank unless `coverage_lines` or a dec entry carries employee benefits. No `coverage_lines` -> today's path.
- `_resolve_gl_hazard_row` / `_resolve_phantom_gl_hazard_row`: a real row printing no territory -> owned blank, never asked.
- `_line_code_witnesses` also reads verified dec entries whose LABEL is a code label - the fence has witnesses on dec-only packages.
- `_schema_context` - a context manager that restores the previous schema.
- **Line-scoped gap fill:** `build_line_page_scopes` gives each line its own policy's pages (header / footer match; a page naming no policy inherits the last one named). `_facts_for_line` drops other lines' facts and dec entries. `combined_gap_fill(..., line_scopes=)` runs `_combined_gap_fill_core` per line. Wired in `form_routes`. Kill switch `GAP_FILL_LINE_SCOPE=0`.

**Post-generation (`arq_service`)**
- `_backfill_and_resolve_present` and `_restamp_canonical_into_forms` pass `_form_id` + the form's schema, and never reopen a guard blank. `_restamp_schedule_into_forms` passes `_form_id`.

**Card (`underwriting_consistency`)**
- `_is_form_number_policy_value`: never a candidate, refused on confirm (`underwriting_invalid_value`), a stored form-number confirmation dropped with a warning. Round 6's `usable_confirmations` now owns the read side.

## Owner rulings
- Ended term: **the printed term stays**, with the "confirm the new term" soft warning (not a renewal shift).
- No paid runs from this chat; the owner runs live.
- Page scoping and a re-extraction: approved.

## Before / after - real facts, offline
| Box | Deployed | After |
|---|---|---|
| 125 policy number | `IM 7100 06 04` | blank (four policies) |
| 125 term | 07/15/2026 - 07/15/2027 | 07/15/2025 - 07/15/2026 |
| 126 insurer / NAIC / policy | Employers Mutual / 25186 | EMC P&C / 25186 / BBC7263 - 26 |
| 126 TERR | 104 / 6679 | blank |
| 127 insurer / NAIC / policy | NAIC 25186 | EMC Mutual / 21415 / 6E7-40-02---26 |
| 127 CLASS / TERR | 91580 | 7383 / 111 |
| 131 insurer / NAIC / policy | NAIC 25186 | EMC Mutual / 21415 / 6J7-40-02---26 |
| 131 underlying Auto | carrier / number blank | EMC Mutual / 6E7-40-02---26 |
| 131 underlying GL | number blank | EMC P&C / BBC7263 - 26 |
| Card, policy number | `IM 7100 06 04` vs `IM 7201 10 02` | scoped, 4 policies, no form numbers |
| Late-stamp door | wrote the wrong values | writes nothing wrong |

- 125 insurer now EMC Mutual / 21415 - a correct pair, but "one line's carrier as THE package carrier" (round 5 open item) is a separate question and stays open.
- Closes offline: round 5's "EBL $1,000,000 invented", round 6's "stale 127 / 131 dates and GL NAIC".

## Gap-fill cost - offline recorder, same package
| | calls | prompt chars | ~tokens |
|---|---|---|---|
| before | 205 (128 fill + 77 compliance) | 27,403,562 | ~6.85M |
| line-scoped | 114 (80 + 34) | 13,900,368 | ~3.48M |

- Scopes: IM pp 3-84 (226,411 chars), Auto 85-142 (160,171), Umbrella 143-204 (172,870), GL 205-271 (193,568). Whole document 711,577.
- The target boxes are no longer asked at all. `inspect_gap_fill_prompts.py` PASS ($0.0601).
- First cut (page-level only) left each scope ~94% of the document and ADDED calls (228). Inheriting the last policy named fixed it.

## Tests
- New `test_line_binding_14sep.py` (34), on the literal Orbin shapes. Green again on the current tree after round 6's v21 pin move.
- Changed: `test_h3_wc_data_capture` version pin; `test_form_findings_11sep_round3` hazard-grid test (the contract changed: an empty territory on a real row is owned, not asked); `test_text_selection` now inspects `_combined_gap_fill_core`.
- Suite at the time: **7,874 passed / 1 failed (httpx) / 21 skipped** (baseline 7,840).

## Errors on the way
- The deployed code's replay did not reproduce the 126 values - because the late-stamp door wrote them, not the stamper. A probe of that door reproduced all three exactly.
- Vehicle codes v1 cut the window at the next VIN, so vehicle 2's "TERR: 222" landed on vehicle 1 -> nearest-VIN attribution.
- 8 order-dependent failures: the late-stamp change leaked the schema context into later tests -> `_schema_context` restores it. Code wrong, not the tests.
- One fixture of mine was wrong ("Acme Mutual" and "Acme Mutual Co." are two entities).

## Where this disagrees with earlier entries here
- Item 3 "LIVE-VERIFIED" was true of the merged scalar on the 11sep kit. On the real package the card still offered the form number, the producer confirmed it, and the late-stamp door stamped it. No earlier entry mentions `_backfill_and_resolve_present`.
- "126 = EMC P&C / 25186" held on the kit. On the real facts the stamper left it blank and the late-stamp door wrote the wrong pair.
- "6679 gone" relied on the model filing it under driver territory. On the real package the 126 TERR went to gap fill.
- Agreed: the form number is born in extraction; the fence must be bidirectional.

## D6 - values move (Brent first)
- 126 carrier / NAIC, 127 / 131 NAIC, 131 underlying numbers, the term back to the printed one, TERR / EBL blanks, vehicle class / territory filled.
- Scores may shift: the renewal-shift path is replaced by the ended-term soft warning (dates read from a document are soft either way). Not measured.
- Cost DOWN: gap fill ~half. v20 (now v21) busts the extraction cache - one fresh extraction per package.

## STILL OPEN (line-binding chat)
- Not live-verified - owner runs it.
- The card still lists an unplaced "EMC Insurance" carrier candidate (scoped, no conflict) - conflict-card area.
- 125 package carrier (above); 127 `FARTHEST TERMINAL 6679`; driver name split - not touched.
- Nothing committed. `ocr_service.py` was changed by another chat, not this one.

## Standing lessons
- A value can be right at generation and wrong at download: the post-generation doors write too. Check `field_state` and every door that writes it, not just the stamper.
- A kit that passes is not the client's package. Replay the real session before calling an item live-verified.

# Round 6 - pre-Brent fixes (2026-09-15)
Full entry: `v1-20AUG.md` "ORBIN pre-Brent round". Short version:
- 131 P&AI third limit no longer prints the umbrella's pre-reduction $3M (item 9's last leak).
- Rows B..N never take a scalar rule, stamper and questionnaire alike (`scalar_rules_reach`).
- Producer blank when the logged-in account can't be read (item 4); prior carrier derived from the expiring policies.
- Client questions 32 -> 29 on the live run; legal name / mailing address are confirm items now, not questions (item 11).
- Cover page SQS paragraph names the score correctly and cannot name the wrong best form (C92).
- Own-diff review fixed three more: the derived prior carrier no longer counts against a New Venture; a New Venture's N/A years is never overwritten; derived years follow a corrected start date.
- D6: an unreadable account blanks the producer (client package 74 -> 72); the derived prior carrier moved nothing on Orbin.
- Still open: 126 Q7/Q8 "N", a fresh three-document live run, 125 package carrier + proposed dates (Brent).

# Round 7 - the remaining items (2026-09-15)
Full entry: `v1-20AUG.md` "ORBIN remaining items". Short version:
- 125 page 1 follows Brent's own answer key: carrier / NAIC / policy number / premiums blank unless the proposal or a person states them; QUOTE ticked; proposed dates = next term, asked once the term has ended; current policies in the prior-carrier grid.
- Signed PDFs no longer blank in Acrobat. Vehicle use follows "USE: NA". One class's payroll is not total payroll. 131 stops docking EL without WC. Specified Causes of Loss has its own symbol key.
- D6: Orbin package 63 -> 59, client 72 -> 68 (proposed date and vehicle use now asked).
- Still open: 126 Q7/Q8 "N" (owner: leave), prompt items (owner: skip), a fresh three-document live run.

# Round 8 - live run 10 (2026-09-16)
Full entry: `v1-20AUG.md` "ORBIN live run 10". Short version:
- Cover summary is told the prior carrier and the current term (it said "no prior carrier detail"); its cache follows its prompt.
- 125 Q4 "other insurance with this company" is blank until the receiving carrier is known.
- 126 OTHER limit row: only a limit the GL declarations print with no box of its own - never the GL deductible, never gap fill.
- Cover POLICY PERIOD "To be confirmed (current term ...)"; the other-named-insured rows no longer listed as "left blank by the AI".
