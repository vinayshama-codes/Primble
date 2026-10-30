# SCORING RULES - the contract every package must satisfy (owner, 29 Oct 2026)

These rules hold for ANY package a user uploads - any documents, any order, any answers.
They are not tuned to a test package. A change that breaks one of them is a bug, whatever
it fixes elsewhere. `backend/tests/test_scoring_contract.py` proves them on hundreds of
random packages; it must stay green.

## The score
- R1 **Caps.** An open hard stop holds the package score at 60; an open warning at 85.
  Only fixing (or a correct answer to) the item lifts its cap.
- R2 **Exactly 100 when everything is answered.** A user who answers every item the
  screens list reaches 100 - never above, never below. Any order of answering.
- R3 **Never stuck.** If the score is below 100, at least one item is listed whose answer
  moves it. "98 with nothing to fix" is a bug.
- R4 **Never above 100.** No answer, credit or restore takes the score past 100.
- R5 **A cap holds the number down; it never gives points (owner, 30 Oct 2026).** Every package
  has a REAL score - the pillars, every deduction counted, no cap. The SHOWN score is the real
  score held down by the strictest open cap:
  - any open hard stop -> shown = min(real, 60);
  - no hard stop, any open warning -> shown = min(real, 85);
  - neither -> shown = real.
  Every item carries ONLY its own points - what its own deduction costs the real score. A cap
  is not a deduction and is never turned into points on any item. While a cap holds, the screen
  shows both numbers: the shown score and the real score ("60 - held by 1 hard stop; real score
  83"), so the points can be read against the real one.
  Worked example: one hard stop open (its own deduction 10), real score 83, two recommendations
  worth 7 together. Shown 60, real 83. Points on screen: hard stop +10, recommendations +7
  -> 83 + 10 + 7 = 100. Fix the hard stop -> the cap lifts, the shown score becomes the real
  score: 83 + 10 = 93. Fix the recommendations -> 100. Same with warnings and 85. With hard
  stops AND warnings open, fixing the last hard stop shows min(real, 85); fixing the last
  warning shows the real score.
  An item whose only effect is to hold a cap (no deduction of its own) shows no points; it
  reads "Holds the score at 60 until fixed" / "Holds the score at 85 until fixed".
  The real score is kept on every payload; the dashboard, the review page, the side panel, the
  cover and the download screen all print the SAME shown and real score from the SAME
  calculation (one package, one pair of numbers at any moment).

## Final decisions (owner, 30 Oct 2026) - the build follows these
1. **Cross-document bucket** (Exposure) stays as the spec has it: cross-form checks only, -15 a hard
   check, -5 a warning, at most -20 in all (5 package points). Data Consistency conflicts do not go in it.
2. **Unpriced items are cap-only**: no points, "Holds the score at 85 / 60 until fixed" (P1).
3. **Both numbers while a cap holds**: "85 - held by warnings (real score 97)" (R5).
4. **A pillar or bucket limit (REVISED after the build's tests, 30 Oct 2026):** each item shows what its
   answer moves the REAL score done in page order, in whole points (they telescope, so they add up
   exactly). A proportional split was built and dropped: it inflated a gate item (undone last it looks
   huge) and shrank every other number below what its answer really moves (the upload row read 4 for a
   real 6). Under a shared limit the first items in page order may read their hold or a smaller number;
   every number is what that answer really does.
   - Points the page-order walk cannot place go first to the items that answer them done ALONE (an item
     whose box an earlier item touched moved 0 in order) - logged `SCORING_ORDER_OWNED`; only what no item
     answers is `SCORING_UNOWNED_DEDUCTION` (an error) and is split in proportion so the screen adds up.
   - A follow-up's points belong only to the step that raised it, never to the last step by default.
   - A number that includes what the answer raises next reads "up to" (`exact` false), e.g. a loss-run
     upload whose points come from the question it unlocks.
5. **One place** in the P4 order - hard stops included: a FEIN / name conflict shows in Data Consistency
   only, its row reading "Holds the score at 60 until fixed" (`issue_registry` UI-13 + supersession;
   `review_plan.page_items` never lists a card about a fact Data Consistency lists).
6. **Dismissing (the spec, section 9; the credit is the SERVER's price - `audit_routes` caps the
   browser's `score_impact` at the package plan's number for that row):** a hard stop or warning marked Resolved / Dismissed changes
   nothing - it clears only when fixed, the cap still holds. A recommendation dismissed WITH a written
   reason earns its price and counts as done; without a reason it earns nothing and stays open.
7. **After forms:** the package score never changes because forms exist. Each form's score = the
   package's open items + that form's own items (its checklist, hard stops, warnings, recommendations,
   cross-form checks). Its side panel and its one-form download screen list exactly those; switching
   forms switches the list. Download-all lists everything.
8. **Form-specific items never show before forms and never hold the package score** (F1 / F2).
9. **Rounding:** the real score rounds down to a whole number (spec); item points are whole numbers and
   still total exactly 100 - real score.
10. **One calculation:** the dashboard copy, review page, side panel, download screen and cover all read
   the same result.
11. **Tell Brent before deploying:** the points shrink to their real size; conflicts and format errors
   read "Holds the score at 85" instead of +1 / +2.

## The points shown on items
- P1 **An item shows points only if the spec prices it; otherwise it shows its hold (owner, 30 Oct
  2026).** Prices are the spec's own (`SQS_Scoring_Specification.docx.pdf` section 3 pillar tables,
  section 10 per-form checklists) - nothing is invented. A priced item shows its points ("under 1 pt"
  when whole points cannot go round). An item the spec does not price (a Data Consistency conflict, a
  format error such as a 6-digit NAIC or a 4-digit ZIP, an underwriting check with no pillar row) has
  NO points - it only holds the cap and reads "Holds the score at 85 until fixed" / "... at 60 ...".
- P2 **The numbers add up to exactly 100 - the REAL score (R5) - by construction, not by repair
  (owner, 30 Oct 2026).** Item points come from the score's own ledger: every deduction
  (fact -> rule -> pillar) is worth (deduction x pillar weight) of the real score, and every
  deduction belongs to exactly ONE item on the screen; an item's points are the sum of its
  deductions. So real score + all item points = 100, always. Only two pieces of arithmetic sit
  between a deduction and its item, both shown in the ledger:
  - a pillar or bucket limit (e.g. a bucket that deducts at most 25 while its items' deductions
    total 30): the limited amount is split across those items in proportion to their deductions;
  - whole points: fractions are rounded so the total stays exact (largest remainder), never more
    than 1 point moved per item.
  **A deduction with no item must never happen - and is never silent if it does.** Its causes are
  source defects: a deduction for a fact no card / question / table asks; a card hidden (deferred,
  form-scoped) while its deduction still counts; a stale card dropped while its deduction stays; a
  deduction only a document fixes with no "upload" item. Two layers:
  - by design: every deduction has an owner item; `tests/test_scoring_contract.py` and the
    real-package acceptance run fail on any deduction without one;
  - live fallback, so the screen still adds up to exactly 100: the unowned points are split across
    the listed items in proportion to their own points (largest remainder), AND the deduction is
    logged as `SCORING_UNOWNED_DEDUCTION` (an error) naming pillar, rule, fact, points and why no item
    carries it, so it is fixed at the source. The user never sees a broken total; we always see the bug. An item with no deduction shows its cap hold (R5) or "No
  effect on the score", never borrowed points.
- P3 **No cap shares (owner, 30 Oct 2026; replaces the old "even spread").** A cap's release is never
  split across items or credited to the last holder. An item that only holds a cap shows its hold (R5), not points.
- P4 **No negatives; one problem, one place, one price (Brent; owner, 30 Oct 2026).** A problem two
  checks find is shown ONCE, in the first section of this order that holds it: Data Consistency, then
  Hard Stops, then Warnings, then Recommendations, then key details. It is hidden everywhere else and
  its points (if priced) are counted once.
- P5 **Not a score item = not listed with a number.** An item whose answer moves nothing
  and holds nothing reads "No effect on the score" or is not listed.
- P6 **One door.** Every screen prints the points from the same plan
  (`services/review_plan.py`); no screen computes its own.

## After forms: where every open item shows (owner, 31 Oct 2026)
- A1 **The package score never reads form selection.** Line flags (WC / auto / property in the
  submission) follow the facts and a person's answers only (`form_routes.update_pdf` calls
  `line_presence.reconcile_line_flags` without the selected / generated forms). A generated ACORD 130
  no longer turns WC on for the package (live Orbin fb83c9c6: 99 -> 85 -> 96).
- A2 **Nothing raised after forms goes back to the package page.** `issue_registry.package_page_view`
  drops form-only cards after forms exactly as `pre_form_view` does before; it records what it drops
  (`form_items`).
- A3 **Every open item has exactly one place after forms:**
  - about a GENERATED form -> that form's side panel (Hard Stops / Warnings / Cross-Form / its own
    Recommendations) and its one-form download;
  - not form-specific -> **Total Package Score -> Package items** (side panel, same on every form):
    the package plan (hard stops, warnings, Data Consistency, key details, package recommendations,
    documents - each with its points or hold) plus `issue_registry.package_items_after_forms` (a
    check about a form NOT generated, or form-only and naming no form - with its fix, e.g.
    "Add ACORD 101"). The Recommendations section keeps only the open form's own.
- A4 **What holds a form is on its download.** `needs_attention.form_hold_rows`: a form held by its
  own required boxes / gate gets a Warnings (85) or Hard Stops (60) row on its download and on
  download-all, so the screen opens and the SQS summary shows. A form at 100 with nothing open
  downloads directly (Brent, 26 Oct).
- A5 **One problem, one download row.** `needs_attention.fold_twin_issues`: the twin table, the same
  issue id / words, and the same RULE about the same thing worded differently (code + forms + the
  sentence before its detail list); per-building / per-location copies stay apart.
- A6 **A card offers only a fix that moves its points.** A loss "years covered" card routes to the
  typed box only when the runs on file show no readable claim period (`sqs_service.
  loss_recommendation_field(message, facts)`); otherwise its fix is uploading loss runs.
- A7 **Follow-ups are declared for realistic answers**, not only the sample (`review_plan.
  _declare_alone_follow_ups` tries one other count / choice per item: "6 employees" declares the WC
  question "0" did not).

## Package checks and form checks (owner, 30 Oct 2026)
- F1 **Every check has a scope**: `package` (reads the package's documents / answers) or `form` (its fix adds or
  chooses a form, or it reads the form itself - boxes, rows, layout). One table, `issue_registry.issue_scope`;
  `tests/test_issue_scope_30oct.py` fails the build on an unscoped check.
- F2 **Before forms only package checks show.** A form check is deferred (`cross_form_validator.defer_form_choices`):
  no hold, not on the review screens. Package checks are worded by line ("Auto: ..."), never by form number
  (`issue_registry.pre_form_view`, a copy - stored messages and issue ids never change).
- F3 **The package score is independent of the forms.** For the same facts the package score after forms equals the
  pre-form score (fill rate out, form checks never hold the package). Generating forms never moves it; only new data
  or documents do.
- F4 **Each form's score is its own.** A form is held at 60 by its own hard stops / download blocker
  (`sqs_service._form_download_blocker`) and at 85 by its own warnings, a required box on a row it uses, or a
  non-advisory check naming it (`_form_open_warning`). A stop naming another form, or another line's stop, never
  holds it (`stops_for_form`, line read from the rule group). Optional boxes and Please verify never hold a form.
  Filling exactly the holding items brings the form to its raw score. No points are shown per form item yet (parked).
- F5 **Form items live only in each form's side panel after generation** - never on the pre-form screen, never as a
  preview line on form selection.
- F6 **A one-form download reviews only that form**: rows tied to it plus package rows its own score takes
  (`needs_attention.rows_for_form`, `GET /api/audit/open/{id}?form_id=`); a whole-package download reviews everything.

## The items raised
- I1 **A raised item must be answerable** on the screen that shows it, and a correct
  answer must clear it. An item no answer can clear is not charged (the safety net,
  `sqs_service.charge_only_answerable`) - hard stops are never released that way.
- I2 **Real problems only.** A Data Consistency card needs two DOCUMENTS (or a document
  and a person) stating different values for the same fact and scope. One document's own
  schedule (a value per building, a payroll per class) is never a disagreement.
- I3 **Same answer, same result.** A Primble form re-uploaded restores the answers given
  in Primble (same insured, same account) and nothing is asked again; the score equals
  the score before download unless documents were added or removed.

## Always-on checks (30 Oct 2026)
- `services/invariants.py` runs on every package after merge, pre-form scoring, generation and every
  recalculation, and logs `INVARIANT_BROKEN rule=... stage=... session=...` (log only, `INVARIANTS=0` off). Grep live
  logs for it: a breach is a bug class showing up on real data.
- `tests/shape_fuzz_harness.py` / `tests/test_shape_fuzz_30oct.py`: generated packages of many shapes through the real
  deterministic pipeline, before and after forms, against the same rules (`SHAPE_FUZZ_N` for a wider sweep).

## Global behaviour rules G1-G17 (owner, 30 Oct 2026: "every package must act the same")
Each rule holds on ANY package. "Enforced" = the code door that makes it true; "checked" = `services/invariants.py`
(logs `INVARIANT_BROKEN` on every live package) and / or the random-package tests (`test_scoring_contract`,
`test_shape_fuzz_30oct`). A breach is a bug class: fix it in the door, never per package or per warning.

| # | Rule | Enforced by | Checked by |
|---|---|---|---|
| G1 | A fix window offers only the boxes that need fixing (all boxes only when every one holds a good value, and always on a relationship card - a conflict / mismatch / misaligned term / figure to verify, `issue_registry.is_relationship_code` - where a well-formed value can be the wrong one) | `issue_registry.boxes_that_need_fixing` in `build_grouped_view` | `fix_windows_offer_only_needed_boxes` |
| G2 | A correct answer never raises an item that was not listed, except its declared follow-ups (`leads_to`); everything to solve is listed up front | review plan + one row per missing item | `solve_contract` NEW check |
| G3 | Term pairs (proposed / prior / umbrella) run forward and come from one source; a form's effective date takes its expiration | `extraction_service.follow_proposed_expiration` | `terms_run_forward` |
| G4 | Fixed-format values (VIN, FEIN, NAIC, ZIP, phone, umbrella term) from documents are valid or warned, one card per wrong box | `services/identifier_checks.py` | `fixed_format_identifiers` |
| G5 | Every listed item has a fix that works and a correct answer clears it | `answer_routing`, `charge_only_answerable` | `every_item_answerable`, `solve_contract` |
| G6 | Each form is held only by its own items; package checks never depend on forms | F1-F6 above | `form_score_matches_holds`, fuzz after forms |
| G7 | Points add up to 100 - score; answering everything reaches exactly 100 | `review_plan.enforce_contract` | `points_add_up`, `solve_contract` |
| G8 | The dashboard shows the page's score | `_remember_pre_form_score` (every write + page load) | `dashboard_equals_page` |
| G9 | No fact from another insured; a person's value is never overwritten | `insured_scope`, merge person carry | `no_foreign_insured_facts`, fuzz |
| G10 | The insured is never a carrier or the agency (name, FEIN, mailing address) | merge party routing | `insured_is_not_carrier_or_agency` |
| G11 | No duplicate rows (VIN, driver, claim, premises building) | merge folds (`_dedupe_schedule_rows`, `_fold_misread_vins`) | `no_duplicate_rows` |
| G12 | Limits make sense (GL occurrence <= aggregate; another line's limit is never this line's) | `_settle_line_limits` | `limits_make_sense` |
| G13 | An answer never lowers the score unless the plan declares its cost | scorer | `solve_contract` DROP check |
| G14 | Before forms no card names a form number (the Tier 1 sentence prints "Key detail missing: X" under "Missing key details"; the scorer's own sentence, the stop lists and issue ids keep the form name) | `issue_registry.pre_form_view` | `no_form_numbers_before_forms` |
| G15 | No card listed twice on one screen | grouped view de-duplication | `no_item_listed_twice` |
| G16 | Every "Open to fix" opens a box, a table or a narrative | `answer_routing` | `every_fix_opens_something` |
| G18 | Every form deduction has a card: with the package at 100, answering every card a form lists takes it to exactly 100 (any form, any package) | `sqs_service._cards_for_uncarded_pillars` - a pillar a form charges with no card of its own gets cards for the facts its OWN checks read (`_form_check_facts`, parsed from `calculate_sqs` + `_CHECK_HELPER_FACTS`; a fill-scored form uses its inventory), skipping a fact the form prints in its header, an either-or partner already answered (`_EITHER_OR_FACTS`) and anything no box / table / narrative takes; umbrella cards only on ACORD 131 copies. An answer on an umbrella layer's copy is that layer's (`umbrella_layers.write_layer_answer`); a section form's policy number / insurer / NAIC goes to its own policy record (`apply_producer_answer_to_session(form_id=)`). A card appears whenever its pillar deducts (no threshold) | `every_form_deduction_has_a_card`; `tests/test_every_form_reaches_100_30oct.py` (10 random packages x all 17 forms -> exactly 100; every fact a form's checks read is declared) |
| G17 | After forms every scheduled vehicle (up to the form's rows) prints on ACORD 127 | stamper schedule resolvers | `schedule_counts_match_forms` |

## Where it is enforced
- One door for points: `review_plan.build_review_plan` (the ordered simulation
  `_Sim` + `_apply`, `_whole_points`, follow-ups `_follow_ups`, mirrors credited to
  their first place, cap shares `_share_group_releases`, `_no_listed_zero`) ->
  `sqs_service.complete_screen_shares` / `_complete_screen_shares_plan` ->
  `sqs_service.apply_review_plan` (writes the plan's numbers onto
  `top_recommendations`, key details, `screen_*`) -> every screen. Before forms
  through `form_routes._pre_form_status`; after forms through
  `form_routes.screen_points_after_forms` (`GET /api/session/{id}/screen-points`).
- The frontend prints, never computes: `utils/screenPoints.js` (`screenPoints` ->
  `fromPlan`, `screenPointsText`, `underText`), `utils/recommendations.js`
  (`pointsFor`, `pointsText`), `utils/editorPlanList.js` (`editorPlanRows`, the
  editor side panel after forms), `utils/downloadPlanPoints.js` (download review +
  checklist). "under 1 pt" = the plan item's `under: true` (points 0), with its
  condition when it shares a hold: "under 1 pt (counts when all 11 warnings are
  fixed)". Points stay whole numbers, so P2 is exact integer arithmetic.
- **TO BE REPLACED (owner, 30 Oct 2026 - P2 / P3 / R5 rewrite):** `review_plan.enforce_contract` today REPAIRS a
  breach (moves surplus / shortfall / `left` points onto other items, logs `SCORING_CONTRACT_REPAIRED`) and the
  plan shares cap releases (`_share_group_releases`). Both go: points come from the ledger (P2), a deduction no item
  owns is reported as `SCORING_UNOWNED_DEDUCTION` and fixed at its source, never moved.
- I1 doors: every deduction names a box (`sqs_service.coverage_deduction_items`;
  a comparison row also offers the other side, `also_facts` ->
  `review_recommendations.fix_route_for_row`); the safety net
  `sqs_service.charge_only_answerable` / `release_unanswerable_holds`.
- The random-package proof: `tests/test_scoring_contract.py` (40 build seeds +
  after forms + the download screen via node; `SCORING_CONTRACT_SWEEP=N` for the
  slow sweep), generators `tests/reach100_harness.contract_package` /
  `contract_problems` / `solve_contract`.
