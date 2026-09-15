# Chat 3 - Which coverages and forms the package has (problems 9, 10)

Real package: Orbin, session `e7084347`. All verification is OFFLINE on the current code
(stored per-document facts re-merged, no paid LLM calls). `11sep-form-improvement.md` numbers
these two as client items 2 and 7.

## 1. Problems I owned

9. Coverages the insured does not have (Property, Crime, WC, Farm, Liquor, EPLI, OCP and others) shown as active lines
10. ACORD 137 CO not produced for Colorado auto - and whether it would fill correctly if it were

## 2. Per problem

### Problem 9

- **Reproduced on real data? Yes.**
  - OCR `271page_test_data/271page-testdec.txt:30-36`: `1 Property No Coverage`,
    `3 Crime and Fidelity No Coverage`, `6 Workers' Compensation No Coverage`, then `7 Umbrella $3,418.00`.
  - OCR: 55 endorsement headers "This endorsement modifies insurance provided under the following"; the
    phantom names are their menus, e.g. lines 8877-8880 `FARM COVERAGE PART`, `LIQUOR LIABILITY COVERAGE PART`,
    `OWNERS AND CONTRACTORS PROTECTIVE LIABILITY COVERAGE PART`; line 9078 `EMPLOYMENT-RELATED PRACTICES ...`.
  - Session: `lines_of_business` holds 17 names; flags `has_property_coverage`, `has_crime`,
    `has_workers_comp` = False.
  - Before my fixes (measured in this chat; cannot be re-run on current code): the line door returned
    9 lines incl. Property, Crime, WC, Liquor, Pollution; ACORD 130 was recommended; the questionnaire asked
    the producer 4 WC / Employers Liability questions.
- **Root cause.**
  - First wrong point: `lines_of_business` is a bare `[string]` in the extraction schema with no definition
    in the prompt (`extraction_service.py:181`). The model lists every coverage name it reads, menus included.
    Class **(b) prompt + (c) schema**. Not (f): the model was never told what the field means.
  - The model also put "Employers Mutual Casualty Company" on the 13 menu rows and 3 denied rows of
    `coverage_lines` (no premium, no number). Handled in code.
  - Then five rules treated a mention as coverage - class **(e)**, and **(d)** at the recommender:
    1. `lob_canon._row_identifies_policy` (`lob_canon.py:806`) took a carrier NAME as proof of a policy.
    2. `lob_canon._flag_families` (`lob_canon.py:666`) read sub-flags (`property_has_bi_coverage`) as the line.
    3. `cover_service._cover_lines_of_business` read `facts["flags"]`, a key facts never carry - the cover never saw the false flags.
    4. `form_service._dec_line_present` (`form_service.py:948`) read the NEXT row's premium ($3,418 umbrella) as WC's money signal - the row-to-line tie was broken - so ACORD 130 was recommended.
    5. `arq_service._drop_not_applicable_questions` dropped questions only on a literal denial row; Orbin's rows have none.
  - Also: `form_service._FORM_EVIDENCE_FACTS` showed contractor / equipment / builders-risk facts on the
    137 / 138 / 133 recommendation cards.
- **Status: FIXED** (rules layer). The prompt definition is **NOT done - NEEDS OWNER DECISION**.
- **What changed:** a line counts only on evidence - a premium or limit, a NAIC or its own policy number, or a
  true `has_<line>` flag; a false flag beats identity-only rows. The cover receives the flags; the recommender
  ignores a row that prints its own denial; the questionnaire drops questions about a line `line_presence`
  calls ABSENT (ACORD 130 selected still asks).
- **Verified now** (fresh re-merge, current code): 17 mentioned -> 4 carried; the cover prints
  `Liability, Inland Marine, Automobile, Umbrella`; `line_presence` workers_comp = absent; the recommender
  offers 125 / 126 / 127 / 131 (required), 137_CO and 25 (needs confirmation), 186, 160 - no ACORD 130.

### Problem 10a - "not produced"

- **Reproduced? No.** It IS produced: `match_forms_deterministic` returns `ACORD_137_CO`, tier `needs_confirmation`
  (fresh re-run on the real session).
- **Root cause:** none. A recorded client direction: `form_service.py:1423-1427` ("Client direction (Brent):
  keep all state-specific forms at Needs Confirmation"), tier set at `form_service.py:1434`.
- **Status: NOT A DEFECT / NEEDS CLIENT DECISION** (only Brent can promote the tier). Untouched.

### Problem 10b - "would it fill correctly"

- **Reproduced? Yes** (offline, deterministic stamping only, before my fix; measured in this chat):
  - the $1M CSL box was forced blank;
  - Med Pay, UM and the comp / collision symbols were unbound;
  - symbol rows B-H were blanked as "phantom vehicles";
  - the owned collision deductible was stamped into the hired physical damage box (and, on a 3-vehicle fleet,
    into the Truckers / Motor Carrier sections);
  - 327 of the 137's boxes were sent to gap fill.
  - Extraction was right: `$ 1,000,000` CSL, `$ 5,000` med pay, `$ 1,000,000` UM, `$ 1000 DED` comp / coll,
    and a symbol per coverage.
- **Root cause:** class **(e)** + **(d) at form filling**. On a 137 a row letter is a coverage row or a section,
  never a vehicle, but three 127-shaped resolvers read it as a vehicle:
  - `pdf_service._resolve_auto_liability_limit_cell` (`pdf_service.py:2014`): the shared "CSL / BI EA PER" box treated as split-only;
  - `pdf_service._resolve_phantom_schedule_row` (`:2331`): grid rows B-H blanked as vehicles 2-8;
  - `pdf_service._resolve_vehicle_deductible_cell` (`:8364`): the 127 owned deductible stamped into 137 boxes.
  - Nothing bound Med Pay / UM / symbols to the 137.
- **Status: FIXED** (offline-verified on the real facts). What changed: new `services/state_auto_grid.py` owns
  every 137 `Vehicle_*` box. The section comes from the template's page heading; the three resolvers step aside
  for 137 boxes. A single-amount box takes only a fact that states exactly one amount.
- **Not fixed:**
  - **UIM: NOT A DEFECT.** The 137 CO prints no UIM box; Colorado UM includes UIM.
  - **Hired physical damage deductible** ($1,000 via the Auto Elite Extension CA7450 M): no fact carries it, so
    it is asked of gap fill. Making it deterministic needs a new extraction fact - **NEEDS OWNER DECISION** (prompt).
  - **Found, not fixed - NEEDS OWNER DECISION:** `display_canonicalizer.canonicalize_currency`
    (`display_canonicalizer.py:273`) keeps only the digits:
    - `$1M` prints `1`, and `$5K` prints `5`;
    - `$1,000,000 / $2,000,000` prints `10,000,002,000,000`.

    It was there before my work and formats 911 money boxes on 16 forms. Orbin prints right (full digits).
    Pinned by 2 strict xfails.

## 3. Every change I made

Line numbers are the current ones on disk.

| file | function / constant | new / modified | what it does now | why |
|---|---|---|---|---|
| `backend/services/state_auto_grid.py` | whole file (untracked): `SKIP`, `ASK`, `FORMS`, `_FAMILIES`, `_PAGE_HEADINGS`, `SPECIFIED_CAUSES`, `ROW_COVERAGE`, `LIMIT_BASIS_ROW`, `_GRID_FAMILY`, `_GRID_RE`, `_BASIS_RE`, `_CELL_RE`, `_PD_BASES`, `_OWNED_PD_DEDUCTIBLE_FACT`, `_LIABILITY_PART`, `_UM_PART`, `_NUMBER_RE`, `_SPLIT_PART_RE`, `field_families`, `_val`, `_amount`, `_one_amount`, `_flag`, `families`, `_designated`, `_read_limit`, `liability_limits`, `um_limits`, `_unstated`, `_grid_cell`, `_basis_cell`, `_cell`, `resolve` | new | Decides every ACORD 137 CA/CO `Vehicle_*` box: a value, an owned blank, "ask the document", or "not mine" | 10b |
| `backend/services/pdf_service.py` | `_resolve_state_auto_grid` (8338), `_resolve_state_auto_grid_owned` (8353), `_state_auto_grid_decides` (8360) | new | Call the grid for `ACORD_137*` only; SKIP on every other form | 10b |
| `pdf_service.py` | `_AUTHORITATIVE_BLANK_RESOLVERS` (2493) | modified | `_resolve_state_auto_grid_owned` added, before `_resolve_vehicle_deductible_cell` | Owned blanks never reach gap fill; `authoritative_expected_value` takes the first owner |
| `pdf_service.py` | `_deterministic_map_inner` (11710-11715) | modified | Asks the grid after the uncarried-coverage block, before the vehicle resolvers | 10b |
| `pdf_service.py` | `_resolve_auto_liability_limit_cell` (2023), `_resolve_phantom_schedule_row` (2337), `_resolve_vehicle_deductible_cell` (8368) | modified | One gate line each: SKIP when the grid decides the box | Stop 127 logic on 137 boxes |
| `backend/services/form_service.py` | `import COVERAGE_DENIAL_RE` (11), `_ROW_DOLLAR_RE` (923), `_row_denies_line` (926) | new | A row that prints its own denial before any `$` | 9: ACORD 130 offered on a WC denial |
| `form_service.py` | `_dec_line_present` (948, change at 967) | modified | Skips a denied row | 9 |
| `form_service.py` | `_FORM_EVIDENCE_FACTS` entries `ACORD_133` (65), `ACORD_137_CA/CO` (78, 80), `ACORD_138_CA/CO` (85, 87) | modified | 133 -> `total_payroll` / `wc_payroll`; 137 -> `auto_liability_limit` / `auto_um_uim_limit`; 138 -> `garage_liability_limit` / `garagekeeper_liability_limit` | Card evidence named the wrong form |
| `backend/services/lob_canon.py` | `_flag_families` (666) | modified (created by the 11 Sep chat) | Only `has_<line>` flags name a line | Sub-flags evidenced Property |
| `lob_canon.py` | `_flag_denied_families` (694) | new | Families whose `has_` flags are all False | A false flag beats identity-only rows |
| `lob_canon.py` | `carried_lines_of_business` (722) | modified (created by the 11 Sep chat) | Grant rows vs identity rows split; identity minus flag-denied; the no-rows branch drops flag-denied lines; its evidence docstring | 9 |
| `lob_canon.py` | `_row_identifies_policy` (806), `_IDENTITY_PLACEHOLDERS` (803) | modified (created by the 11 Sep chat) / new | NAIC or own policy number only; placeholders and denial text rejected | Carrier name on 16 non-lines |
| `backend/services/cover_service.py` | `_cover_lines_of_business` (24) | modified (created by the 11 Sep chat) | Takes `flags`; falls back to `facts["flags"]` | The cover never saw flags |
| `cover_service.py` | call sites 88, 125, 178, 215, 361; fallback calls 632, 635; `_build_cover_page_fallback(..., flags=None)` (638, 648) | modified | Every path passes the flags, the plain-text fallback included | Same |
| `backend/services/line_presence.py` | `line_of_fact_key` (141) | new | Which described line a fact key belongs to | Questionnaire witness |
| `backend/services/arq_service.py` | `_asks_about_an_absent_line` (2918) | new | Is a question about a line `line_presence` calls ABSENT, or an absent-coverage box the stamper leaves blank? ACORD 130 selected keeps WC | 9 |
| `arq_service.py` | `_drop_not_applicable_questions` (2977) | modified | `flags` parameter; `form_ids = list(form_ids)`; the early `if not denied: return` removed; the old test runs only `if denied`; new witness added | 9 |
| `arq_service.py` | call sites 3507, 3662, 3924 | modified | Pass `flags=flags` | 9 |
| `backend/tests/test_coverage_presence_14sep.py` | whole file | new (119 tests) | Dec rows, recommender, line door, card evidence, questionnaire, fuzz | |
| `backend/tests/test_state_auto_grid_14sep.py` | whole file | new (73 tests) | Layout vs both templates, Orbin end to end, edge cases, fuzz | |
| `backend/tests/test_screen_level_coverage_14sep.py` | whole file | new (14 tests + 2 strict xfails) | Rendered cover PDF, scorer row, 137 through `map_facts_to_form`, questionnaire fuzz | |
| `CLAUDE.md` | form list lines for 137, 138, 141, 160 | modified | Template titles; 141 / 160 marked OPEN | Wrong form names |
| `v1-20AUG.md` | sections at 10526 ("... safe half"), 10658 ("... full pass"), 10686 ("items 9/10 checked through what the client sees") | new sections | Change log | |
| `11sep-form-improvement.md` | status rows 2 (line 42) and 7 (line 49); section `# 14 SEP - items 2 and 7 ...` (line 1723 to end) | modified (file created by the 11 Sep chat) | Log | Owner asked |
| `~/.claude/projects/.../memory/acord-141-160-leave-alone.md` + one `MEMORY.md` line | outside the repo | new | Owner: do not touch 141 / 160 | |
| `14sep_reports/chat-3-lines-and-137.md` | this report | new | | |

**NOT mine, although in files I touched:**
- `arq_service.py`: `_guard_blanked_fields`, and the `_form_id` / `_schema_context` changes in
  `_backfill_and_resolve_present`, `_restamp_canonical_into_forms` and `_restamp_schedule_into_forms`.
- `lob_canon.py`: `import logging` / `logger` and the original 11 Sep block.
- `sqs_service.py`: `_ok("lines_of_business")`.

No frontend change (`AcordModal.jsx` is not mine), and no change to `extraction_service.py` or `improving-ll.md`.
A transcript scan of every Edit / Write I made confirms this list; my only shell writes were pytest logs into
scratch files. No git commands.

## 4. Tests I changed or deleted (not added)

**None.** No pre-existing test file was edited or deleted.

For transparency, three of my OWN new tests were corrected while I built them:
- **`test_state_auto_grid_14sep` layout test:** a +-8pt label window caught the neighbouring row's label. It now
  uses the nearest label within 14pt. The TEST was wrong; the code was unchanged.
- **`test_coverage_presence_14sep` legacy expectation:** the fuzz found the no-rows branch returning flag-denied
  lines. The CODE was wrong and was fixed; the expectation followed.
- **`test_screen_level_coverage_14sep` cover parser:** it read only the ReportLab layout. In a full run,
  `tests/test_production_guards.py:31` stubs `reportlab.platypus`, so the cover comes out of the plain-text
  fallback. The parser now reads both. The TEST was wrong.

## 5. Prompt / LLM changes

- **Prompt, schema, batching, chunking, model:** no change.
- **PROMPT_VERSION / SCHEMA_VERSION:** never edited by me. On disk now: `"v21"` / `"v21"`
  (`extraction_service.py:53-54`), set by another chat. Unverified what it was when I started.
- **LLM cost:** when ACORD 137 CO is selected, boxes sent to gap fill drop from 327 to 25 (measured with
  `compute_form_gaps` on the real session facts, offline). Calls were not measured live. The questionnaire
  change uses no LLM. Nothing else changes.
- **Model change recommended: No.** Neither problem is class (f). The 137 facts were extracted correctly; the
  phantom lines come from an undefined prompt field plus rules.
- **Proposed, NOT done (owner approval needed):**
  - add a `lines_of_business` definition to the extraction prompt;
  - add a hired-auto physical damage fact (limit + comp / coll deductibles).

  Neither adds a call; together they add about 100-150 tokens to the cached prefix, and they need a
  PROMPT_VERSION bump plus an `improving-ll.md` entry.

## 6. Shared code I touched

- **`carried_lines_of_business`** - callers: `cover_service.py:38`, and `sqs_service.py:4561` (`_compute_category_breakdown`).
  Checked by fuzz (900 packages, 1,000 denied rows, 1,000 priced rows), the scorer screen test and the full suite.
- **`_row_identifies_policy`, `_flag_families`, `_flag_denied_families`** - used only inside `carried_lines_of_business` (grep).
- **`_dec_line_present`** - `match_forms_deterministic` for GL / WC / Auto / Umbrella / Property (`form_service.py:1170, 1187, 1213, 1256, 1280`).
  Checked with denied-row and priced-row tests for all five phrase sets.
- **`_FORM_EVIDENCE_FACTS`** - the card evidence builder (`form_service.py:103`). A test anchors each entry to the template's printed title.
- **`_drop_not_applicable_questions`** - all three questionnaire generators. Checked by a 480-package fuzz:
  non-WC and mention-only questions are never dropped; ACORD 130 selected keeps every WC question.
  Behaviour change: the "nothing denied" early return is gone, so the new witness runs on every package - it
  acts only on a decisive ABSENT.
- **`line_of_fact_key`** - arq only.
- **`_AUTHORITATIVE_BLANK_RESOLVERS`, `_deterministic_map_inner` and the three gated resolvers** - every form, plus
  `field_qa` via `authoritative_expected_value`. The grid returns SKIP unless `_form_id` starts with `ACORD_137`.
  Covered by the tests "other forms untouched", the ACORD 127 regression and the ACORD 25 CSL box.

## 7. Scores that move

- **Headline SQS:** no change from my code on Orbin. The only scorer reader of the line door is
  `_compute_category_breakdown` (display sub-rows: the legacy Applicant Info row and the fallback Coverage Info
  row). It can only go DOWN, and only where a package's line evidence was a carrier-only row, a sub-flag, or
  identity rows its own false flags deny. Orbin, re-run now: Applicant Info 80, Coverage Info 100.
  Tier 1 (`_SCORED_FACT_KEYS`, `sqs_service.py:4049`) still reads the raw fact.
- **ACORD 137 per-form:** more boxes filled deterministically when a 137 is generated, so its fill rate goes UP
  (not measured as a score).
- **Recommendations:** a form whose declarations row prints "No Coverage" is no longer recommended (ACORD 130 on
  Orbin). No warning keys off that list - the only "Missing baseline form" warning is ACORD 125 (`issue_registry.py:145`).
- **Questionnaire:** fewer WC / Employers Liability questions on no-WC packages.
- **No** hard stop, cap or warning was added or removed by my code.

## 8. Live test checklist (Orbin)

| # | Where to look | Expected when FIXED | Looks like this if still BROKEN |
|---|---|---|---|
| 9 | Cover page PDF, LINES OF BUSINESS | `Liability, Inland Marine, Automobile, Umbrella` | Also Property, Crime, Workers' Comp, Farm, Liquor, EPLI, OCP, Pollution |
| 9 | Form selection screen | 125, 126, 127, 131 required; 137 CO and 25 "Needs Confirmation"; 186; 160 (known wrong form, owner: leave). **No ACORD 130, 140 or 141** | ACORD 130 or 140 offered |
| 9 | ACORD 125 LINES OF BUSINESS checkboxes | Business Auto, Commercial General Liability, Inland Marine, Umbrella ticked; premiums 2,991 / 3,954 / 300 / 3,418 | Property, Crime or Workers' Comp ticked |
| 9 | Producer questionnaire | No Employers Liability each-accident / disease limit or EL policy-number questions | EL limit questions on ACORD 131 |
| 9 | ACORD 137 CO recommendation card | Evidence: auto liability limit `$ 1,000,000`, UM/UIM limit `$ 1,000,000` | "Contractor type: commercial general contractor" |
| 10a | Form selection screen | `ACORD_137_CO` under Needs Confirmation (Brent's ruling); the producer ticks it | Missing |
| 10b | 137 CO page 1, Business Auto: CSL box `Vehicle_CombinedSingleLimit_LimitIndicator_A` + "CSL / BI EA PER" `Vehicle_BodilyInjury_PerPersonLimitAmount_A` | Ticked + `1,000,000`; BI each accident and PD boxes blank | Blank, or EACH PERSON ticked |
| 10b | Med Pay `Vehicle_MedicalPayments_PerPersonLimitAmount_A` | `5,000` | Blank |
| 10b | UM: CSL box `Vehicle_CombinedSingleLimit_LimitIndicator_B` + `Vehicle_UninsuredMotorists_BodilyInjuryPerPersonLimitAmount_A` | Ticked + `1,000,000` | Blank |
| 10b | UIM | No box on the 137 CO (Colorado UM includes UIM) | - |
| 10b | Business Auto symbol grid | 1 on liability (row A), 2 on Med Pay (B), 2 on UM (C), 7 on comp (F), 7 on collision (H); towing (E) blank; nothing else ticked | Rows B-H blank, or symbol 1 ticked on every row |
| 10b | Truckers and Motor Carrier pages | Completely blank | Any value or tick |
| 10b | Hired PD deductibles `Vehicle_Comprehensive_DeductibleAmount_A` / `Vehicle_Collision_DeductibleAmount_A` | `1,000` (gap fill reading CA7450 M) or blank | Any other amount |

Observed on the same re-run, NOT my work (section identity, another chat): the 137 CO header shows
`6E7-40-02---26` / EMPLOYERS MUTUAL CASUALTY COMPANY / 21415.

## 9. Not done, not verified, risks

- **Needs owner decision:** the money formatter; the two prompt additions; the 137 tier (Brent); ACORD 141 / 160
  wrong forms (owner said leave).
- **Not verified live.** Everything is an offline replay of the stored per-document facts, with no paid gap fill.
  A fresh v21 extraction may produce different `coverage_lines` / flags; my rules read both, so they should
  hold - unverified.
- **After generation** `PURGE_DEC_INDEX_AFTER_GENERATION=1` deletes `dec_page_entries`, so the questionnaire and
  cover rely on the persisted flags. The replay used the session flags; unverified on a purged live session.
- **Residuals seen on the real session, not fixed:**
  - the umbrella's own Employers Liability indicator boxes (`ExcessUmbrella_EmployersLiability_*`) and the
    liquor / pollution exposure boxes on ACORD 131 are still in the question list (audience "internal";
    unverified whether any screen shows them);
  - 127 "PD per accident" is asked on a CSL policy;
  - the loss-payee question says "property policy";
  - a Truckers / Motor Carrier deductible written "$2,500 each auto" is blanked by a post-fill guard;
  - ACORD 131's per-form Structural counts EL on a no-WC package (score - Brent).
- **Assumption:** an explicitly false `has_<line>` flag is trusted as absence (the same rule `line_presence`
  uses). If extraction wrongly sets a flag False on a real line backed only by identity rows, that line drops
  off the cover. A premium or limit row still wins.
- **Conflict risk:** `pdf_service.py` is edited by several chats. My grid hook must stay BEFORE the vehicle
  resolvers in `_deterministic_map_inner` (11710), and my registry entry before `_resolve_vehicle_deductible_cell`
  (2493); a reorder would let 137 boxes fall back. `carried_lines_of_business` is shared with the 11 Sep chat's work.
- **Test isolation:** `tests/test_production_guards.py:31` stubs `reportlab.platypus` in `sys.modules` and never
  restores it. It was there before; I did not touch it.
- **Phantom suite failures:** my earlier full-suite run showed 9 failures because another chat rewrote
  `extraction_service.py` mid-run (`inspect.getsource` read shifted lines); all 9 passed alone.

## 10. My test results

`py -m pytest -q -p no:randomly tests/test_coverage_presence_14sep.py tests/test_state_auto_grid_14sep.py tests/test_screen_level_coverage_14sep.py`
(from `backend/`, run for this handoff): **206 passed, 0 failed, 2 xfailed.**

The 2 xfails are strict pins on the held formatter defect - they flip to failures the day it is fixed:
- `test_the_137_prints_shorthand_limits_at_their_real_size`
- `test_two_amounts_are_never_glued_into_one_number`

Last full suite I ran (14 Sep, before handoff): 8,314 passed / 1 failed (the known `httpx` import) /
21 skipped / 2 xfailed.
