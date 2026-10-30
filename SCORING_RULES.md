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

## The points shown on items
- P1 **Every item a user must solve to reach 100 shows a number above zero** - hard stops,
  warnings, cross-form checks, recommendations, Data Consistency picks, key details,
  document requests. If whole points cannot go round, it shows "under 1 pt". Never blank,
  never 0, never only "counts once X is fixed".
- P2 **The numbers add up to exactly 100 - score**, on every screen (review pages, editor
  side panel after forms, download screen), and again after every answer.
- P3 **Even spread.** Points that are only released when a GROUP is done (a cap lifted
  when its last holder is fixed) are split evenly across the group, whole points by
  largest remainder; each item also keeps its own measured gain. The wording says the
  condition: "+1 pt (counts when all 6 warnings are fixed)".
- P4 **No negatives, nothing counted twice.** A mirror (the same fix shown in two places)
  is counted once.
- P5 **Not a score item = not listed with a number.** An item whose answer moves nothing
  and holds nothing reads "No effect on the score" or is not listed.
- P6 **One door.** Every screen prints the points from the same plan
  (`services/review_plan.py`); no screen computes its own.

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
- The final guard on the plan: `review_plan.enforce_contract` (run last in
  `build_review_plan`). It repairs any breach of P1 / P2 / P4 / P5 instead of
  showing it - a mirror's own points go to its first place, negatives to 0, a
  surplus off the largest numbers, a shortfall or points on no item (`left`) to
  the score items, a 0 score item to "under 1 pt", nothing numbered at 100 - logs
  `SCORING_CONTRACT_REPAIRED` with the rule and item ids (never values), and puts
  the rules on the plan as `contract_repaired`. The proof fails on any repair: a
  repair means a root cause to fix.
- I1 doors: every deduction names a box (`sqs_service.coverage_deduction_items`;
  a comparison row also offers the other side, `also_facts` ->
  `review_recommendations.fix_route_for_row`); the safety net
  `sqs_service.charge_only_answerable` / `release_unanswerable_holds`.
- The random-package proof: `tests/test_scoring_contract.py` (40 build seeds +
  after forms + the download screen via node; `SCORING_CONTRACT_SWEEP=N` for the
  slow sweep), generators `tests/reach100_harness.contract_package` /
  `contract_problems` / `solve_contract`.
