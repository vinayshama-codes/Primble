# UX-05 - "Add form" from a validation finding

**SHIPPED + LIVE-VERIFIED 2026-09-09.** Suite 7308 passed / 1 failed (the
documented `httpx` ImportError). Frontend build clean.

A validation that says "ACORD 186 is missing" used to offer only Dismiss / Mark
resolved - neither adds the form, and after generation there was no route back
to the form list. It now offers **Add ACORD 186**.

## Why this was already owed

`Decision_Tree.txt` L501: *"Missing certificate when requested = user-facing
failure ... **Prompt user to generate ACORD 25/28 post-bind**."* We built the
warning and never built the prompt-to-generate. This closes that half.

## The rule class - and why it is not all 17

Only FOUR rules EMIT on a form's absence, because those are the only ones the
spec asked for. (Swept `cross_form_validator` for `not in triggered_ids`: 25
hits, 21 are skip-guards.)

| Decision_Tree.txt | Rule | Form |
|---|---|---|
| L74 "Missing 125 -> hard stop" | `acord125_missing` | 125 |
| L459 "Missing 186 -> big SQS hit" | `contractor_missing_acord186` | 186 |
| L501 "Prompt user to generate ACORD 25/28" | `certificate_requested_but_acord25_missing`, `property_evidence_requested_but_acord28_missing` | 25, 28 |
| L515 "require ACORD_101" | `acord101_required` | 101 |

**Do not confuse with RECOMMENDATIONS** (`form_service.match_forms` +
`matching_flags`): those cover all 17 and already have a checkbox on Select
Forms. A recommended form is NOT missing.

**17 emit sites are annotated, not 4** - the class is every message telling the
producer to add or attach a form, which includes every "or attach ACORD 101".

## Owner rulings (both binding)

1. **2026-09-08:** *"no form can only be added after the generation of forms if
   our system finds that a form is missing, user can't add it later on."* No
   free-form "add any form later". The 2026-08-13 no-regeneration rule is
   NARROWED, not reversed. Enforced server-side by
   `form_addition.requested_form_ids()`.
2. **Reopen never removes a generated form.** It can carry producer edits, ARQ
   answers and a signature; `reopen_issue` already refuses to auto-clear a
   schedule for the same reason. A wrongly-KEPT form is visible; a wrongly-
   DELETED one is not. **No "remove form" action exists, deliberately.**

## Architecture

* **`add_forms` is a CAPABILITY on a resolution, not a fifth mode.** It composes
  with all four: `acord101_required` keeps its narrative textarea AND gains the
  offer; `contractor_missing_acord186` is `none` mode whose only fix IS the form.
* **Declared at the emit site**: `cross_form_validator._issue(..., add_forms=[])`.
  The rule that WRITES "Add ACORD 186" knows which form it means. A regex over
  the prose was tried and rejected - it cannot tell "Add ACORD 186" from "Add EL
  limits **on** ACORD 130". That regex now lives in the TEST only.
* **Filtered in ONE place**: `_filter_add_forms` drops anything already in
  `triggered_ids`. No rule re-derives "is it selected?".
* **`services/form_addition.py`** generates ONE form and merges it. Re-scoring is
  `recalculate_session_scores` - the existing door.
* **`mode=add_form` on `/api/audit/resolve-issue`**, not a new route, so the
  response tail (`updated_forms`, `grouped_cross_issues`, form-selection view) is
  the same code the panel already consumes.
* **Two surfaces, two costs.** Pre-generation the button just TICKS the form and
  jumps to Select Forms (free). Post-generation it GENERATES (minutes + LLM).

## Landmines

1. **Never reuse `/api/select-form(s-bulk)`.** `generated_forms` merges per id,
   but `selected_form_ids` / `active_form_id` / `cross_issues_last` /
   `package_sqs` are replace-wholesale - posting one id collapses the package.
   Regenerating ALL forms is also wrong: it rebuilds `field_state` and destroys
   producer edits that have no fact write-back.
2. **Adding a form widens `triggered_ids`**, so form-scoped rules that were dark
   switch on. Clearing one warning can raise two. Correct, but surface it.
3. **The dec index is already purged** at first generation, so an added form runs
   the pre-2026-08-13 pipeline. Measured: 9 of 5,852 fields degrade to blank;
   **no field is ever wrong.** Decision recorded in `test_dec_index_purge.py`.
4. **Free tier**: do NOT re-apply `select_forms_bulk`'s `downloads_used >= 3`
   gate - the package's credit is already spent. Only the account lock is checked.

## Conditionality - measured over the real engine

| Signal | Offers |
|---|---|
| no signals | nothing |
| `is_contractor` | 186 only |
| certificate holder | 25 only |
| mortgagee / loss payee | 28 only |
| >2 real claims | 101 only |
| 2 claims (under the bar) | nothing |
| contractor, ACORD 126 not selected | nothing |
| every signal, every form selected | nothing |

Every rule is form-scoped AND signal-gated. Pinned by
`test_each_offer_needs_its_own_signal_and_only_its_own`.

## Eight defects found and fixed (all but two came from live runs)

| # | Defect | Root cause |
|---|---|---|
| 1 | grouped view lost the Add button | `make_issue` re-derives resolution from the CODE, which knows nothing about THIS package - "fix the layer the screen reads" |
| 2 | a cluster offered a form its headline never asked for | `_make_clusters` borrows a resolution from the first member that has one |
| 3 | `location_address_mismatch` never declared its form | its "or add ACORD 101" is split across source lines; found by the harvester, not by reading |
| 4 | Reopen dropped the row into a void, then blinked it mid-flight | a row that is neither live nor resolved renders NOWHERE; older and wider than UX-05 |
| 5 | `acord101_required` could be overruled but never SATISFIED | the rule read neither half of its own message (form in package, narrative on file) |
| 6 | a composite card lost the added form from the list | four exits to `onApplied`; the LAST reply won and carried no `added_form` |
| 7 | Add button vanished for a RECOMMENDED-but-unticked form | `all_available_forms` is the NOT-recommended remainder, not "all forms" |
| 8 | acting on a row made it say the fix was impossible | the button hides once ticked, and the empty list flipped `explainOnly` |

Also: the harvester's own first draft was wrong twice - `ast.literal_eval`
returned "" for f-string/`+` messages (blind on 9 rules while green), and
message-wide cue matching gave 4 false positives.

## Follow-ups from the parallel chat, 2026-09-09

* **"Attach ACORD 101" when it was already attached - FIXED.** The closing
  sentence was a fixed string, so once the form was added the row told the
  producer to attach a form sitting in their own package, while the only thing
  still missing - the narrative - stayed buried mid-sentence. It now branches:
  *"Attach ACORD 101 with narrative"* when absent, *"ACORD 101 is in this
  package - add the narrative"* when present. Same defect shape as the
  satisfaction gate above: the message did not read the state. The reasons list
  is byte-identical either way, and `_filter_add_forms` already drops the button
  in the second branch, so message and affordance agree.

  **That ternary would have blinded the harvester** - `_literal_str` returned
  "" for an `ast.IfExp`, so a state-dependent message goes invisible to every
  guard while they all stay green. Second occurrence of the C25 trap in this
  file (the first was f-strings). Fixed, and pinned by
  `test_the_harvester_can_read_a_branching_message`.

* **ACORD 28 row with no Add button - ALREADY FIXED, see defect 7.** Cause was
  `all_available_forms` being the NOT-recommended remainder rather than "all
  forms", so a recommended-but-unticked form lost its button. `tickableFormIds()`
  is the union of `recommendations` and `allAvailableForms`. Verified still in
  place 2026-09-09.

## Standing lessons

* **When one surface can perform TWO writes, the second reply is not a superset
  of the first. Merge, do not replace.** (Third time this shape appeared.)
* **A list named "available" was doing double duty** as "everything" and as "the
  leftovers". Read the producer, not the name.
* **Distinguish "nothing to offer" from "already done"** at the layer that
  renders - inferring from an empty list is the BUG-05 class.
* **The fixture must be the live data shape (D22).** An offline probe paired
  `is_contractor` with a RETAIL operations sentence - a combination extraction
  never produces - and "proved" an offer the live screen does not show.

## Three flagged risks - CHECKED, none was a defect

* **Download gate**: `check_hard_block` blocks only on `placeholder_value` and
  `missing_required_gate` (ACORD 140 COPE). Blanks do NOT block, and no add-form
  rule offers 140.
* **ARQ**: `generate_arq_questions` iterates `generated_forms`, so the next
  questionnaire covers the added form. Only an ALREADY-SENT one is stale - true
  of any post-send change.
* **Signatures**: per-form and keyed on `generated[form_id]`. `_save_pdf_bytes`
  does `if pb is None: continue`, so a recalc can never blank stored bytes.

## Test kit

```
py backend/scripts/make_ux05_test_pdf.py   ->  ux05_test_data/
```

One PDF. Tick **only ACORD 125 + 126** (126 is required - the contractor rule
needs the GL section), generate, then four Add buttons: 186 / 25 / 28 / 101.
Pre-generation the Review screen shows **one** offer (ACORD 25) - the rest are
recommended, so not missing. Full checks in `README-HOW-TO-TEST.md`.

## Guards

`tests/test_add_form_resolution.py` (41). The one that matters:
**`test_every_add_a_form_message_declares_the_form`** AST-walks the real
`cross_form_validator` and fails the build when a message tells the producer to
add a form without declaring it - a new missing-form rule cannot ship a dead
card. `test_the_harvester_is_not_vacuous` gives it a floor (C25 trap);
`test_no_rule_declares_a_form_its_message_never_mentions` is the reverse guard.

## Still open

* **D6: scores move both ways, Brent has not seen live numbers.** A required form
  landing lifts Structural Completeness; rules that switch on with it can cap.
* **Not exercised live:** the double-click / `already_present` refusal, and the
  Reopen spinner (shipped, confirmed by code path only).

## Key files

`services/form_addition.py` (new) · `services/cross_form_validator.py` (`_issue`,
`_filter_add_forms`, the 17 emit sites) · `services/issue_registry.py`
(`RESOLUTION_MAP`, `make_issue`, `_make_clusters`) · `routes/audit_routes.py`
(`resolve_issue` mode=add_form, `reopen_issue` `still_live`) ·
`frontend/.../ResolutionModal.jsx` (`addedRef`/`withAdded`) ·
`frontend/.../AcordModal.jsx` (`pendingAddForms`, `tickedAddForms`,
`tickableFormIds`, `reopeningIds`)

---

# UX-04 - Explain Exclude / Supporting only / Review data - SHIPPED 2026-09-09

Three controls on each Documents Processed row carried only a bare native
`title`, so the producer committed a pipeline re-run blind.

| Control | Tooltip |
|---|---|
| Exclude | Ignores this document everywhere - forms, score, recommendations. Use it if the file doesn't belong here. Click "Include" to undo. |
| Supporting only | Still uses this document's values, but never as the main source. If documents disagree, this one gives way. Click again to undo. |
| Review data | See exactly what Primble read from this document. Read-only, changes nothing. |

Truth checked in `extraction_pipeline.py`: `exclude` drops the doc from
`active_docs` (L439); `supporting_only` keeps its facts but removes it from
`_primary_candidates` (L451); `review data` is a read-only GET.

One `DOC_ACTION_TIPS` map (`AcordModal.jsx` ~L687), consumed by a `HoverTip` on
each button. The native `title` is REMOVED on those three (two tooltips on one
control is worse than none). Copy only: no behaviour, no scores, no backend.

A summary `InfoTip` on the Documents Processed header was built and then
**removed on the owner's call (2026-09-09)** - live, its bubble covered the
document rows it described. Do not re-add it. `HoverTip` is hover/focus only, so
the guidance is desktop-only; accepted.

---

# UX-03 - Clarify Resolved versus Dismissed - SHIPPED + LIVE-VERIFIED 2026-09-09

Client: define both at the point of action, say whether each changes the
underlying data or score, and delete the generic "These come from the submission
itself..." paragraph. Copy only, plus ONE behaviour fix (below). No backend, no
scoring. Frontend build clean.

## The class: one word, three meanings

Answerability was declared per surface, so `Resolve` / `Dismiss` / `Resolved` did
not mean the same thing twice on one screen:

| Control | Meaning | Score moves? |
|---|---|---|
| Warnings + Cross-Form Validation rows | work-tracking bookmark | **No** (endpoint isolated from scoring) |
| Recommendation card `Dismiss` | skips a real gap | **No** without a reason |
| Recommendation card `Submit` + reason | waives the gap | **Yes** - `audit_service.dismiss_earned_credit` |
| Recommendation card "Resolved" pill | you ANSWERED it | **Yes** |

A single shared sentence would have been a lie on at least one of them. That is
why the copy is per-BEHAVIOUR, not per-screen.

## What shipped

* `ACTION_TIP` (`AcordModal.jsx`, above `IssueStatusControl`) - one definition per
  behaviour, read by every surface. Rendered through the existing **`HoverTip`**,
  the same component UX-04 uses one section up; a native `title` beside a styled
  bubble on the same screen was the first attempt and was wrong.
* The generic paragraph is **deleted** (0 occurrences).
* The rec card's **"Resolved" pill is now "Answered"** - the Reviewed section
  already used that word. After this, "Resolve" means exactly one thing app-wide.
* The Reviewed row's `Reopen` was the last raw browser `title` on that panel -
  converted, so all three Reopen buttons look alike. Their TEXT still differs:
  reopening a credited item genuinely takes the points back.
* `activeOpenRecs` hoisted - the rec list was gated on the UNFILTERED array.

## The behaviour fix - a card refusing what the server accepts

`acord101_required` is `mode: narrative`. `ResolutionModal` has spoken narrative
since the mode shipped (textarea -> `additional_remarks_text` via the same
`resolve_issue` endpoint), and the editor's Cross-Form panel opens any row with a
descriptor - so the SAME row was fixable AFTER generation and a dead end BEFORE
it, printing *"Needs a written explanation, not a value."*

Cause: `itemResolveAndStatus` hard-coded `canResolve = field || schedule`. Now it
includes `narrative`, and `explainOnly` is `mode === "none"` alone. **BUG-05's
class mirrored** - there the card offered what the server refused; here it refused
what the server accepts. Live-verified: the typed narrative prints on the ACORD
101 Additional Remarks Schedule.

Also: narrative prefill was deliberately non-blocking, so "Already on ACORD 101"
popped in a beat after an empty box. It now holds the same spinner field mode
holds (client #3, one mode over).

## Owner rulings during the build (both reverse an earlier step)

1. **No on-screen explainer.** An in-panel box shipped first (top of the stops
   group, and above the rec list). Owner: hover only, remove it from the top.
2. **No label renaming.** "Resolve"/"Dismiss" -> "Handled"/"Not applicable" was
   built and REVERTED on instruction, as was "Dismiss without reason" on the rec
   card. Labels stay; the hovers carry the whole difference.
3. **Every `Dismiss` shows the identical sentence**, on all three surfaces. The
   two card-specific variants were deleted, not left dead. Nothing is lost: the
   reason-earns-points line lives on `Submit`, the control that does it.

## Known gap, accepted

`HoverTip` is hover/focus only by design, and the on-screen box was removed, so
**on touch there is now no explanation anywhere**. UX-04 solved the same problem
with a section-header `InfoTip`; that was deliberately NOT added here (ruling 1).
One line on the Warnings header closes it if beta reports it.

## Found while testing, NOT fixed - both belong to UX-05

* **The ACORD 28 row says "Add ACORD 28" and offers no Add button**, while ACORD
  25 beside it does. Same defect as UX-05 #7: `score_extra_forms`
  (`form_service.py:1853`) builds `all_available_forms` by EXCLUDING recommended
  forms, so a form that is recommended-but-unselected falls in a hole.
* **`acord101_required`'s message still says "Attach ACORD 101 with narrative
  before submission" when ACORD 101 is already in the package.** One-sentence copy
  fix in `_check_acord101_triggers`; untouched because another session had an open
  edit in that exact function.

## Key files

`frontend/.../AcordModal.jsx` (`ACTION_TIP`, `IssueStatusControl`, `SidePanelRec`,
`itemResolveAndStatus`, `activeOpenRecs`, Reviewed `Reopen`) ·
`frontend/.../ResolutionModal.jsx` (narrative `prefillLoading` gate)

---

# UI-01 - "insurance broker", not "insurance agent" - SHIPPED 2026-09-09

* **47 strings, 9 files, not the one reported header.** Swept `your agent` /
  `Your Agent` / `insurance agent` / `their agent` / `agent or broker` across the
  whole client surface: questionnaire (21), `arq_service` question texts + hints
  (13), `arq_routes` assistant rules + fallbacks (8), naics/schedule copy (3).
* A producer with no `full_name` was introduced to the client as **"Your Agent"**
  in the invite AND reminder email subject. Now "Your Broker".
* **NOT changed, decided:** `naics_suggester._INDUSTRIES` ("insurance agent" is a
  TRADE keyword, NAICS 524210 - renaming breaks industry detection); ACORD's own
  schema tooltips; `pdf_service.py:20936` (quotes uploaded-document text);
  `AcordModal.jsx:393` (producer-facing, out of scope - flagged).
* Two tests were terminology PINS (`test_h3_wc_data_capture`,
  `test_naics_suggester`) and now accept either word.
* Suite **7327 / 1 failed** (documented `httpx`). Build clean. `improving-ll.md`
  C-UI01: prompt copy only, `PROMPT_VERSION` deliberately unmoved.

---

# UI-02 - Assistant greeting names itself + one open question - SHIPPED 2026-09-09

* Copy shipped as requested. **The real defect was the RULE:** the greeting had
  its OWN "answered" test (`!answers[f].trim()`, schedules skipped) beside
  `questionnaireProgress.hasResponded`. A producer-preloaded untouched table read
  ANSWERED to one and REMAINING to the bar; a questionnaire whose only gaps were
  schedules got the "everything is answered" greeting. Now reads `respondedTo` -
  the same door as the progress bar and the receipt.
* Free with it: "I'm not sure" counts as responded, so the greeting never
  re-offers a question the client deliberately handed to the broker.
* **The `?`-button branch is kept**, not replaced by the generic sentence - it
  names a MORE relevant question, the one just tapped. All three branches say
  "automated forms assistant".
* "form" -> "questionnaire" on the client's side: panel subtitle and
  `_ARQ_ASSISTANT_RULES` 1 / 4 / 9 (the model called it "this form" in every
  answer). Panel title "Form Assistant" + `?` tooltips left alone - flagged.
* Suite **7327 / 1 failed**. Build clean. `improving-ll.md` C-UI02.

---

# UI-08 - "available for" rather than "applied to" on Umbrella-related forms

**SHIPPED + LIVE-VERIFIED 2026-09-09.** Frontend build clean. Display only -
one string. No backend change, no score moved.

The Data Consistency confirmed row read:

    Umbrella / Excess Limit   Confirmed: $3,000,000 - applied to ACORD 131, ACORD 25

## Root cause

The form list was being described as a HISTORY when it is a CAPABILITY.
`_forms_for_field` -> `pdf_service.forms_consuming_fact` derives it from the
stamping paths: it is where a confirmed value CAN land. On the pre-form screen
no form exists yet, so "applied to" asserted a write that had not happened -
and while the conflict is unresolved the value is actively WITHHELD from
stamping (`CONFLICT_WITHHOLD_KEYS`), so the sentence was at its most wrong
exactly where it was printed.

`AcordModal.jsx:7006` now renders `- available for ${formsLabel}`.
**"Applied to" is reserved for a confirmed write event.**

## Blast radius - swept, not assumed

* Only ONE site in the frontend renders a verb over a form list. The other two
  (`AcordModal`'s issue rows, `ResolutionModal`'s header) draw bare form chips
  with no verb.
* The scoped-policy row (`confirmed_scopes`, :6931) prints no form list.
* The **"Confirm & apply to forms" button was left alone here** - that button
  DOES perform a write, so "apply" was correct on it. It was shortened later
  the same day for a different reason: see UI-07 below.
* Backend `applied to` hits are all comments/docstrings except
  `client_answer_review.py:213` ("The client's answer has been applied to the
  forms"), which is a real write event and stays as it is.
* No test asserted the old string.

## Live kit

`py backend/scripts/make_ui08_test_pdfs.py` -> `ui08_test_data/` (2 PDFs +
`README-HOW-TO-TEST.md`). TWO documents, because `assess_underwriting_
consistency` compares PER-DOCUMENT facts - one document cannot disagree with
itself, so a single upload yields no conflict and no Confirm button. The values
are the client's literal Orbin pair: dec page $3,000,000, COI $1,000,000.

The script self-verifies before it writes: it drives the REAL reconciler
(conflict carries both amounts; `forms == ['ACORD_131', 'ACORD_25']`;
confirming flips it to `status: confirmed` keeping that list) and reads the REAL
`AcordModal.jsx` for the fixed string. That last check was proved to BITE by
pointing it at a file holding the old text.

`carrier_name` is the kit's CONTROL row - it disagrees too but has an empty
forms list, so it must confirm to `Confirmed: <value>` with no form clause at
all. It proves the clause is still conditional and the fix was not stapled onto
every row.

**Live-verified 2026-09-09:** `Umbrella / Excess Limit  Confirmed: $1,000,000 -
available for ACORD 131, ACORD 25`.

## One thing to know before re-testing

The sentence only exists on a CONFIRMED row. On the "VALUES DIFFER - CONFIRM"
state there is no form clause to read, and there never was - the first live look
was taken on the unconfirmed row and read as "it did not appear at all".

---

# UI-12 - "MERGE REJECTED" in the extracted-data popup

**SHIPPED + LIVE-VERIFIED 2026-09-09.** Suite 7327 passed / 1 failed (the
documented `httpx` ImportError). Display only - no backend behaviour, no
frontend change, no score moved.

The Review data popup opened with a row headed MERGE REJECTED followed by a wall
of unpunctuated values.

## Root cause

`_merge_rejected` is the merge's private note of the candidates it did NOT
elect. `merge_facts` pops it at the package level; the per-DOCUMENT path never
does, so it stays in `doc["facts"]`. The endpoint walked every key with no
filter and the popup's CSS uppercased the humanised label:
`"_merge_rejected"` -> `"Merge Rejected"` -> **MERGE REJECTED**.

A leading underscore is this codebase's marker for "machinery, not a fact", and
~20 other generic walkers already honour it - `audit_service` shipped the
identical fix on 2026-08-26 after `_scoped: [structured value]` reached the same
client. This popup was the last one that did not.

## Fix

`routes/form_routes.py`: row building extracted to **`_document_fact_rows`** (one
door, testable through the seam the screen reads) which skips any key starting
with `_`.

**Suppressed, not deleted.** The note is the INPUT to
`_flag_intra_document_limit_conflicts` -> the Data Consistency picker, which is
the plain-language "let the user choose" the same ticket asks for in its place.
Stripping it at extraction would silence that picker on single-document
packages - a fix that breaks the feature the client wants.

## Live verification

Live session, one document: 61 stored fact keys, private keys still stored
(`['_merge_rejected']` holding 4 losing values), **59 rows rendered, 0 private,
exactly one key dropped**. The 61st is `risk_transfer`, an all-empty dict that
has always rendered blank. Data Consistency still raised the Gross Sales
conflict ($4,850,000 / $5,240,000) with radio buttons - both halves of the
ticket met.

## Live kit

```
py backend/scripts/make_ui12_test_pdf.py   ->  ui12_test_data/
```

ONE 27-page PDF, and the length is load-bearing, not padding. The note is only
written when a SINGLE document splits into 2+ extraction chunks (56,000 chars,
`_effective_chunk_size`), so the disagreeing figures must sit tens of thousands
of chars apart with real policy wording between them - and clear of the
14,285-char context carry-over, or both blocks land in one chunk and nothing
fires. Six conflicts planted (GL occurrence/aggregate, umbrella limit, policy
number, gross sales, total premium) so one model wobble does not blank the test.
The script self-verifies through the REAL `_effective_chunk_size`,
`_chunk_by_sections` and `_merge_list_fields`.

## Guards

`tests/test_ui12_private_facts_not_displayed.py` (19), driven with the live
run's literal values. It HARVESTS every private fact key the pipeline writes
out of `services/` + `routes/` source, so a key added later is covered without
anyone remembering the file exists; `test_the_harvester_actually_harvests` gives
it a floor (C25 trap). `test_the_endpoint_still_goes_through_this_door` fails
the build if the route grows an inline fact loop again.
**Proved it bites:** reverting the one-line filter fails 15 of 19.

## Deliberately NOT changed

* **`Dec Page Entries`** still renders as a 90-value comma soup. Same class -
  internal machinery, and `audit_service` suppresses it by name - but nobody
  reported it and it is not in UI-12. Owner ruled no. One line, same door.
* **`Agreed Value Endorsement: False`** and the two Cyber Controls rows LOOK
  like debug output and are not: they are real extracted "no" answers carried in
  envelopes with `value_state: explicit_no`. Dropping them would blank real data.

## Key files

`routes/form_routes.py` (`_document_fact_rows`, `get_document_extracted_data`) ·
`backend/scripts/make_ui12_test_pdf.py` (new) ·
`backend/tests/test_ui12_private_facts_not_displayed.py` (new)


---

# UI-07 - shorten "Confirm & apply to forms" to "Confirm"

**SHIPPED 2026-09-09.** Frontend build clean. Copy only - one label, its busy
state, and the in-flight banner. No behaviour, no score, no endpoint changed.

## The real complaint

Not the length. The label named the PROPAGATION as if it were a second thing
the producer had to opt into, when the mapping is deterministic: confirming a
canonical value IS applying it. `confirm_underwriting_value` records the choice
and re-runs `_finalize_pipeline` on the stored documents - re-stamp, re-validate,
re-score - and the endpoint hands back `recommendations`, `hard_stops`,
`soft_stops`, `grouped_issues`, `package_sqs`, `key_details` and `flags` in the
same response. One action, already.

* `Confirm & apply to forms` -> **`Confirm`**
* busy state `Applying…` -> **`Confirming…`**
* in-flight banner "Applying your confirmation and updating the forms" ->
  "Confirming and updating everything this value affects" (pre-generation there
  are no forms yet to update, so the old sentence was also inaccurate there)

## What deliberately did NOT change

**The line-scoped label keeps its scope: `Confirm for umbrella`.** SYS-06 makes
that answer true of ONE coverage line instead of the submission, and collapsing
it to a bare "Confirm" would hide the difference at the only moment it is
visible. Short is not the goal; not implying a second operation is.

`Use client's <value>` (the held-client-answer row) keeps `Applying…` - that
one really is a separate apply decision.

## The acceptance criteria's third clause, answered with the code

*"If a value is intentionally withheld from a destination, surface the reason
rather than silently failing to apply it."*

**Nothing is withheld on this path, by Brent's own ruling.**
`CONFLICT_WITHHOLD_KEYS` is EMPTY (D16 / Q4, 2026-08-21: *"we should patch the
suggested value"*), so a cross-document conflict stamps its suggested value
rather than shipping an owned blank - and confirming replaces it everywhere.
There is no silent non-application here to explain.

**Two things left standing, named rather than quietly folded in:**

1. `extraction_service._flag_intra_document_limit_conflicts` still writes
   `_uw_conflicted_keys` and blanks the box for a conflict INSIDE one document.
   Brent was asked about two documents disagreeing, and Principle 7 forbids
   stretching a ruling past the question, so that path is untouched. It is not
   reachable from this button.
2. `verify_stamped_consistency` compares only NON-BLANK stamped values - a
   destination that came out blank is `continue`d, so a mismatch is reported but
   an absence is not. That is a real hole in "surface the reason", it predates
   this item, and it needs its own decision rather than a copy change. Recorded,
   not fixed.

## Verification

Frontend build clean. The UI-08 live kit (`ui08_test_data/`) is the same
package: its README now says click **Confirm**.

---

# UI-09 - Clarify enterprise-only integration access - SHIPPED 2026-09-09

**Where:** SQS panel after generation -> More Actions -> Integrations (Share to
Epic / Share to Vertafore). Restricted-state popup, `AcordModal.jsx`.

**Copy, per the client's literal acceptance criteria:**
- was: `Enterprise only for now` / `Join the waitlist to get early access.`
- now: `Enterprise Only` / `Contact sales for access.`

Waitlist language is gone from the whole frontend (grep clean). "Contact sales"
now matches what the Pricing page and Upgrade modal already say for Enterprise.

**`Contact sales` is a link.** It closes the popup and opens the existing
`ContactModal` ("Contact Primble" - the navbar box), same wiring
`UpgradeModal` and `PricingPage` already use. No new component, no new endpoint.

## Owner rulings on the rest of the ticket

- **Button face unchanged.** `Share to Epic` / `Share to Vertafore` still read
  as live for non-enterprise users. The ticket's "reads like an immediately
  available share action" was raised and the owner kept it as is - the popup
  carries the whole message.
- **Backend gate NOT added.** `/api/send-to-epic` and `/api/send-to-vertafore`
  do not check `subscription_tier`; the gate is frontend-only by owner decision.
  Both endpoints are stubs today ("EPIC integration coming soon"), so nothing
  real leaks. Revisit when either integration goes live.

**Verification:** frontend build clean. Display only - no score, no fact, no
backend path touched.

---

# UI-10 - Auto-dismiss all toast notifications - SHIPPED 2026-09-09

Build + eslint clean. Display only - no score, fact or backend path.

**Root cause: toast LIFETIME was never modelled.** Each surface hand-rolled its
own state, then invented or forgot its own dismissal. One class, two opposite
faces - `AcordModal`'s job toasts had NO timer (the reported defect); `App`'s
overage pill auto-dismissed at 8s but had NO close button and leaked two
uncleared `setTimeout`s into an unmounted component.

**`frontend/src/hooks/useToasts.js` (new) is the one door** - ids, timers,
duration policy, unmount cleanup. Both surfaces consume it and keep their own
markup. **success/info 8s** (owner set 8 over the proposed 5), **warning/error
10s** - those carry an instruction to read and ACT on. Manual close stays on
both (`x` + click anywhere); the overage pill gained an `x` it never had.

**Auto-dismiss loses nothing** - verified, not assumed: generated forms live in
the left rail, counts in the Hard Stops / Warnings sections, fed by the same
`packageIssueCounts()` helper the toast reads.

**Owner ruling - no pause-on-hover/focus.** Hover, focus and tooltip behaviour
app-wide is untouched. Consequence: the timer runs while the card is being read,
which is why the dwell is 8s and not 5s.

**Responsive (iOS + Windows):** both stacks pin left AND right instead of sizing
off `100vw` (includes the scrollbar on Windows, never fit a phone); cards are
`min(340px, 100%)` / `min(420px, 100%)`, no media query; the pill's un-shrinkable
`left: 50%` + translate is gone; close target 22 -> 30px; `touchAction:
manipulation` + `WebkitTapHighlightColor` kill iOS Safari's 300ms double-tap wait
and grey flash. `viewport-fit=cover` NOT added - app-wide layout change on
notched iPhones, far too much blast radius for a toast. Stack is
`role="status" aria-live="polite"`, kept mounted when empty.

**Swept, not toasts:** `saveSuccess`, `epicSuccess`/`vertaforeSuccess`,
`dcHighlight`, `pkgStatusMsg` (already 12s + Dismiss). OS notification banners
are out of scope - dismissed in the Action Center.

**Smoke test:** `window.__primbleTestToast()` -> 8s, `(false)` -> 10s.
**Known gap:** no frontend test runner, so nothing fails the build if a future
surface hand-rolls `useState` + `setTimeout` and walks past the hook.

---

# UI-03 - Spell out Submission Quality Score wherever a cap is introduced

**SHIPPED 2026-09-09.** Suite 7327 passed / 1 failed (documented `httpx`).
Frontend build clean. Display only - no score, cap, fact or rule changed.

- Cap copy was authored per surface: 6 frontend labels + 5 backend messages, each
  with its own phrasing (bare "SQS", bare "Score", or nothing). Fixed as a class,
  all tiers - not just the screenshotted banner.
- Frontend `AcordModal.jsx`: lite hard stops/warnings (:6206/:6216), pro Hard
  Stops/Warnings banners (:7186/:7220), SQS panel package (:7810) and per-form
  (:8144). All now "...Submission Quality Score (SQS) at NN".
- Backend: `sqs_service` COPE warning (85), FEIN conflict, both date conflicts,
  `top_recs` hard-stop action; `cross_form_validator` COPE detail warning.
- `.stops-title-meta` gets `text-transform: none` - it is a nested span
  inheriting the heading's uppercase, which is why the screenshot shouts.
- Safe: `_LEGACY_MESSAGE_RULES` and `_LEGACY_SUPERSEDED_BY_CODE` match on the
  phrase BEFORE the changed text; FEIN/date messages are coded, never reach the
  phrase table.
- **Known cost:** `issue_id_for` hashes the MESSAGE, so Resolve/Dismiss marks
  stored against these 5 sentences pre-change will not re-attach. 0 prod users.
- Fixtures modelling live emission refreshed (`test_bug06`, `test_issue_diff`);
  the 2 verbatim client replays in `test_legacy_rules` left as reported.

---

# UI-13 - a Data Consistency row does not also print as a warning - SHIPPED + LIVE-VERIFIED 2026-09-09

**The control was a symptom.** "Fix in Data Consistency" only scrolled the page
up, because the row it sat on was a SECOND printing of a card already on the
same screen: `extraction_pipeline:1129` emits one warning per picker field with
`review_required`, so Carrier / Policy Number / Contact Name rendered in Data
Consistency (values, source, suggestion, Confirm) and again under REQUIRED
BEFORE SUBMISSION with nothing but a jump link. Owner: remove the warnings copy,
touch nothing else.

- **One line, in the one door.** `build_grouped_view` drops an issue whose
  `picker_fact_key(code)` resolves AND whose resolved severity is not
  `hard_stop`. By CODE, so it is derived from the emitter - a fact added to
  `RECONCILABLE_FIELDS` is covered the day it ships, no list to maintain.
- **Decided on the severity this view resolves**, not the emitter's: a blocker
  keeps its red card (the 4 `HARD_STOP_RECONCILABLE_KEYS`), and a `promote_codes`
  row keeps its card - since UI-13 that promotion is the ONLY thing keeping a
  score-capping conflict on the screen.
- **The local `soft_stops` trim is load-bearing.** The sentence stays in the
  caller's array (the 85-cap input), and the safety net re-adds anything missing
  from `enriched` - without the trim the row came back as `uncovered_soft_stop`
  under "Other validations". Same contract as the two supersession blocks above
  it: local copies only, caller's arrays untouched, `hard_stops` deliberately not
  filtered (a picker sentence in the blocking array while this view calls it a
  warning must fail toward a VISIBLE row).
- **Free with it:** the doc-consistency twin of these rows was already hidden by
  the 2026-08-23 supersession, so a warning-level conflict now prints once, in
  the picker, instead of three times.
- Counts, tier badges, the "Important" preview, the completion toast and the
  section visibility gates all sum what this function renders, so they follow
  with no frontend change. `hasWarnings` is counts-driven - no empty amber box.
- Display only. No score, cap, credit or `issue_id` moved. The remediation diff
  builds both sides through the same function, so nothing reports as "resolved".
- `services/issue_registry.py` only. Tests: `test_ui13_picker_rows_not_in_
  warnings.py` (31, sweeping every real `RECONCILABLE_FIELD_KEYS` entry; proved
  it bites - 21 fail with the change reverted). 3 older tests re-pinned to the
  new contract (2 in `test_doc_conflict_supersession`, 1 promotion count delta in
  `test_package_cap_is_visible`). Suite **7358 passed / 1 failed** (documented
  `httpx`).
- **Kept, not removed:** the `FixInDataConsistencyButton` itself. It is no longer
  redundant - it only renders on blocking / promoted conflict rows, where the row
  must stay and the jump is the only route to the picker.
- **LIVE RUN, sys07b package D (2026-09-09).** Data Consistency: 5 rows ("4 to
  fix" - Policy Number correctly reads "2 policies, 2 values - not a conflict",
  plus the 4 boolean conflicts). Warnings: **5, none of them a picker row** -
  ACORD 125 contact info, auto symbols, vehicle schedule, auto completeness,
  UM/UIM. Header reads "4 items need your input below, plus 5 warnings to
  review", and Required(1) + Recommended(3) + Binder(1) = 5, so the counts agree
  with the cards. Before the change those 4 boolean conflicts printed a second
  time as warnings.

---

# UI-06 - the equivalence block stops shouting - SHIPPED 2026-09-09

Client: *"The Submission Integrity section lists a very long 'Coverage terms'
equivalence string and later repeats normalization conclusions that were already
resolved above. This adds visual noise and can make users think there is still an
unresolved coverage problem."* Acceptance: *"Keep the concise normalization
outcome and remove the verbose duplicate coverage-term dump. If detailed
normalized values are needed for auditability, place them behind an expandable
details control rather than in the primary review flow."*

- **The defect is LENGTH, not the coverage field.** `sqs_service.py:2213` joins
  EVERY document's raw `lines_of_business` list into one `[info]` string, and the
  card printed every row's raw printings inline at any length. Reproduced at
  **465 characters** on a two-document package. A four-document address row does
  the same thing. So the collapse threshold is applied to every row identically
  and `test_the_collapse_rule_names_no_field` fails the build if a field name
  ever appears in that logic - an allow-list tuned to the client's screenshot
  would have fixed the case and left the class open.
- **`NormalizationDiffRow` (new, `AcordModal.jsx`).** Under
  `NORMALIZATION_INLINE_MAX_CHARS` (160, about one line of this card) the row is
  **byte-identical to what UI-04 shipped** - values, wording, category pill, and
  no control of any kind, because nothing is hidden. Over it, the row collapses
  to its outcome ("N versions - treated as equivalent") behind **the app's own
  chevron** - `CollapsibleSection`'s glyph, size, colour and 90-degree rotation,
  asserted against that component's source so it cannot drift into a lookalike
  (owner, 2026-09-09: a dropdown, not a text link; the first cut shipped a
  "View details" link and was replaced).
- **Expanded, each document's printing gets its own line.** The reported row was
  one 465-character run-on *because* two lists were joined into a single
  sentence; re-printing that inside a dropdown would move the wall, not remove
  it. Nothing is ever truncated -
  `test_the_detail_is_expandable_and_never_dropped` greps for `slice`/`substring`
  to keep it that way.
- **The second half - a fact declared resolved AND asked about.** The `reasons`
  list has been deduped against open Data Consistency conflicts since UI-04; the
  equivalence rows never were, only because they carried no fact key to match on.
  **UI-04 gave them one**, so this is the SAME guard applied to the other half of
  the card, not a new rule. The severity chip now counts `normalizedRows`, not
  the raw payload, so a block that deduped to nothing cannot leave a "Resolved
  formatting difference" chip labelling empty space.
- **Display only.** No backend change at all. `normalized_differences` still
  carries every printing - collapsing is a browser decision, and "View details"
  would have nothing to show otherwise.
  `test_no_scoring_path_reads_the_render_threshold` walks every backend module to
  prove the constant never leaked into scoring.
- **A legacy string payload opts OUT of the dedup** (`field: ""`), so a session
  open across a deploy keeps its block rather than losing rows to a key it never
  had.
- **Deliberately NOT done:** the other six rows were left alone. Each is already
  one line and readable; the noise was the paragraph. The client asked for three
  things and got three.
- **One UI-04 test was updated, not deleted.**
  `test_the_card_renders_the_category_and_one_info_icon` anchored on the inline
  row body, which this change extracted into a component. Every guarantee it made
  is now asserted on BOTH halves - heading and component. The TEST was stale, the
  code was not.
- Tests: `test_ui06_normalization_noise.py` (21) + the reworked UI-04 test.
  Suite **7432 passed / 1 failed** (the documented `httpx` ImportError), zero
  regressions. Frontend build clean.

## Live run 2026-09-09 - three refinements, all display

1. **Text link -> the app's chevron** (owner). `View details` / `Hide details`
   became `CollapsibleSection`'s glyph and rotation. A test reads that
   component's source so the two cannot drift apart, and fails if both controls
   ever exist at once.
2. **Expanded values, one line per document.** The reported row was one 465-char
   run-on *because* two lists were joined into a sentence. Reprinting that inside
   a dropdown would move the wall, not remove it.
3. **The chevron got its own column.** Without it the one collapsible row sat
   ~14px right of its neighbours and the block read ragged. Short rows reserve
   the column and leave it empty - spacing, not a hidden control.

**A test was fixed too, not just the code.** `_component()` sliced a fixed 3000
chars of the JSX; the component grew past it and a test asserting the row still
renders its values started failing for a reason unrelated to the row. It now
reads to the next top-level declaration. **Fixed-window source slicing is a trap
- it fails late and blames the wrong thing.**

**Suite flake, named not buried:** one full run reported 12 failures
(`test_v1_c1_canonical_facts`, `test_two_document_regressions_20260904`,
`test_v1_beta_exit_20260828`, ...). Re-ran: 1. Those three files alone: 262
passed. Pre-existing cross-test pollution - nothing in a JSX component can reach
a canonical-facts test.
- **Live kit:** `py backend/scripts/make_ui06_test_pdfs.py` -> `ui06_test_data/`
  (2 PDFs, `README-HOW-TO-TEST.md`). Two files, not one, because
  `check_doc_consistency` compares documents against EACH OTHER - a single upload
  emits none of these notices. Self-verified: it refuses to build if either file
  denies coverage (which would turn the `[info]` into a warning) or if the two
  files share a spelling (which would test string equality, not normalization).
- **Found while building the kit, NOT fixed:** `Suite`/`Ste`, `Court`/`Ct` and
  `WA`/`Washington` all normalize; **`Building 3` vs `Bldg 3` and `South` vs `S`
  do not** - the first fixture draft raised a real "Physical address differs"
  WARNING on one address printed two ordinary ways. Separate normalization gap,
  recorded in the generator, out of scope here.
- **Key files:** `frontend/src/components/form/AcordModal.jsx`
  (`normalizationRow`, `NormalizationDiffRow`, `renderIntegrityStatus`),
  `backend/tests/test_ui06_normalization_noise.py`,
  `backend/scripts/make_ui06_test_pdfs.py`.

---

# UI-04 - "treated as equivalent" now says WHY - SHIPPED + LIVE-VERIFIED 2026-09-09

Client: the card marks values equivalent after normalization but never says what
rule made two visibly different values the same. Asked for a concise tooltip plus
the normalization category per row.

- **The reason was computed and thrown away one layer before the screen.**
  `check_doc_consistency` tags every notice with its rule
  (`code=effective_date_normalized`); TWO parsers stripped the token - the inline
  one in `extraction_pipeline` and `sqs_service.split_doc_consistency_issues`.
  A lost field, not a missing feature.
- **One parser: `sqs_service.parse_normalization_notice`** -> `{code, field,
  label, values[], category, message}`. Both `[info]` branches call it. `message`
  is byte-identical to the old strip and the door still returns STRINGS - its
  contract is pinned by `test_sqs_scoring_fixes_20260816` and read as text by
  `doc_consistency_stops`.
- **Category is DERIVED, not a table.** `normalization.equivalence_category`
  walks the same dispatch `normalize_value` uses to decide the values are equal.
  A key added to any `*_FIELDS` set is labelled the day it ships. One documented
  exception: `lines_of_business` is compared by `_canon_line_leaf`, so it names
  itself. Codes are NOT renamed - `name_normalized` / `lob_normalized` are
  aliased to their fact key inside the parser (a rename costs two tests, buys
  nothing).
- **Values split on `" | "` (`_INFO_VALUE_SEP`), `[info]` rows only.** A comma
  cannot separate values that contain commas - the client's screenshot read
  "Orbin Contracting, LLC, ORBIN CONTRACTING LLC". Hard stops and warnings keep
  `_show`'s comma join: their text is hashed into `issue_id`s and matched by
  `classify_legacy`, so it must not move.
- **Frontend:** ONE `InfoTip` on the block heading (owner ruling 2026-08-27 - not
  one per row) + a category pill per row. A legacy string payload still renders,
  so a session open across a deploy keeps its block.
- **Live audit caught one row failing the client's own ask:** the `entity_type`
  pill read "Entity type" - the row's OWN label - and was the wrong word ("LLC"
  vs "Limited Liability Company" is two accepted terms, not two formats). Now
  **"Accepted terminology"**. `test_no_category_merely_repeats_its_own_row_label`
  fails the build if any pill is a subset of its row label.
- **Display only.** No score, cap, credit or `issue_id` moved. An `[info]` row is
  never an issue, never hashed, never scored, never persisted.

## Follow-up, same day - the block survives a refresh

Not a reopen: on F5 the block DISAPPEARED, so nothing unexplained was shown.
Separate pre-existing defect on the same card, fixed on the owner's call.

- **`/extraction-result` never returned `normalized_differences`**, though its own
  docstring promises "the same shape as the synchronous upload response". F5
  emptied the block AND dropped its chip (severity derives from the list being
  non-empty).
- **`sqs_service.doc_consistency_normalizations(session)`** recomputes from stored
  docs. Deterministic, no LLM, read-only (pinned), nothing persisted.
- **Mirrors the UPLOAD path, not its sibling `doc_consistency_stops`** - the
  contract is "a refresh shows what the upload showed". Copies `active_docs`'
  `[not excluded] or all` fallback and reduces confirmations with
  `parse_confirmation_key`, so a SYS-06 line-scoped resolution
  (`effective_date@auto`) still counts. `doc_consistency_stops` compares raw keys
  and would miss it - deliberately not copied.
- **Fails open to `[]`, exactly what the endpoint returned before**, so the worst
  case of the change is the behaviour it replaces. Proved: made
  `check_doc_consistency` raise - got `[]`, an ERROR log, no escape.
- **Also fixes a LATENT bug nobody had hit.** The async upload path
  (`ENABLE_ASYNC_PROCESSING=true`) reads its payload from the SAME endpoint
  through the shared handler, so turning async on would have shipped the blank
  block on every upload. Sync upload was always fine.
- No frontend change: all five `setNormalizedDiffs` sites already read the key.

## Verification

- `tests/test_ui04_equivalence_category.py` (**71**): anti-rot count of the
  `[info]` emit sites, a guard that `extraction_pipeline` never re-parses the
  token, refresh-equals-upload, excluded / all-excluded / no-facts / malformed
  sessions, confirmed + line-scoped confirmations, a read-only pin, and the
  reload endpoint driven END TO END (`get_extraction_result` with a stubbed
  session - the source grep alone passes with the screen still broken).
  **Every guard proved to bite.** Suite **7432 passed / 1 failed** (documented
  `httpx`). Frontend build clean.
- **Live kit:** `py backend/scripts/make_ui04_test_pdfs.py` -> `ui04_test_data/`
  (2 PDFs, 6 rows). It reads `AcordModal.jsx` and prints PRE-FIX / POST-FIX, so
  the before/after run is self-identifying. The test fixture also states a
  `physical_address` (7 rows) to cover the address loop's third code; the PDFs
  print only a mailing address, which is the ordinary shape.

## Read this before touching the render

**UI-06 (above) replaced the inline row body with `NormalizationDiffRow`** -
rows over 160 chars collapse behind the app's chevron. The parser, the category
and the `field` key are unchanged and UI-06 depends on both (its dedup matches on
the `field` UI-04 introduced). Start from UI-06's entry for anything visual.

**Pre-existing, NOT touched:** `frontend/src/App.css` has one unbalanced `}` at
HEAD (1033 open / 1034 close). esbuild warns on every build and silently drops
the rules after it. Unrelated to this work.

---

# PROD-02 - a boilerplate paragraph is not a conflict

**SHIPPED + LIVE-VERIFIED 2026-09-09** (session `299cd414`). Suite **7460 passed /
1 failed** (documented `httpx`). Backend only, no frontend change.

Client: the IMPORTANT band led with *"Conflicting values for Specific Wording
Requirements across documents"* + a wall of legal text, and asked whether it
belonged there at all. **Not a product decision - a defect.** Both sides were
boilerplate: a dec-page **service-of-process CONDITION** and the **ACORD 25's own
preprinted footer**. No correct value to pick, no control to pick it with
(`mode: none`), and it capped the SQS at 85.

## Root cause - the last unmigrated comparator

`detect_source_conflicts` compared normalised STRINGS and read "not identical" as
"conflict". Two paragraphs are never identical, so a prose fact conflicted every
time. `fact_comparison.py`'s own header has listed this site since C1
(2026-08-21) - of five places that decide "do these documents disagree?", it had
**"none"**, and was the only one never migrated. The build guard
(`test_comparison_has_one_owner`) watches `values_conflict` /
`distinct_normalized` / `entity_identity_conflict`; this site imports
`normalize_value`, so it passed for 19 days.

The rule it was missing is the **client's own 2026-08-17 ruling**, shipped since
C1: `fact_equivalence._PROSE_WORD_FLOOR` (*"nobody picks between two true
paragraphs"* -> INCOMPARABLE) plus `narrative_facts`, which mines the STATEMENTS
inside a paragraph so prose can EXPLAIN a conflict instead of being one.

## The fix - a SECOND gate, never a replacement

`extraction_service._door_conflict`. The original distinct-normalised test runs
first; the door is asked only when that test already says conflict, so a card
needs BOTH. Both gates suppress, so nothing quiet today can start firing and no
new card can appear.

**The first attempt REPLACED gate 1 and broke carrier aliases** - "Employers
Mutual Casualty Company" vs "EMC Property & Casualty Company" started drawing a
card, because the door groups entity names on `strict_entity_key` and
deliberately NOT on `normalize_carrier` (Round 10 fix 46). Caught by the suite,
not by reasoning. Pinned by
`test_the_door_can_only_remove_a_card_never_add_one`.

Also wired in: one `PackageContext` per call (two printings of one policy number
are not two policies) and the door's rating-bureau drop (AAIS was in the
client's own carrier card).

## Blast radius - measured

**6 of 176** registry facts stop raising a source-conflict card - the
narrative-kind ones (`operations_description`, `additional_remarks_text`,
`account_description`, `certificate_description_of_operations`,
`wc_description_of_operations`, `garage_operations_type`). Every ENUMERATED text
field still competes (`construction_type`, `entity_type`, `valuation_method`,
`occupancy_type`) - the boundary that matters, pinned from both sides. A
genuinely different insured is still caught by `applicant_name` (hard stop).

**D6: scores go UP** on multi-document packages that hit this. Brent first.

## Live verification - the screenshot was not enough

On screen: no wording card anywhere; `Mortgagee Name` and `Certificate Holder
Name` still raised; `Loss Payee` silent on two printings of one name; carrier
folded to one `Employers Mutual Casualty Company`; policy number labelled *"2
POLICIES, 2 VALUES - NOT A CONFLICT"*. IMPORTANT now leads with the auto-symbol
gap and the missing vehicle schedule in 2 of 3 slots.

**A screenshot cannot tell a fix from an absent fact**, so the session was read
back (`dump_session_facts.py`). The fact WAS populated on both documents - but
not with what the kit planted:

```
P1_dec_page.pdf     14 words   "Additional insured status is provided where
                                required by written contract executed prior to loss."
P2_certificate.pdf  37 words   the ACORD 25 preprinted footer, verbatim
```

Replaying the REAL values: GATE 1 -> 2 distinct strings, **WOULD HAVE FIRED**;
GATE 2 -> `equivalent`, no card. **A harder case than the kit was built for** -
only ONE side cleared the 25-word floor, so the suppression came from the
narrative-KIND merge, not the floor. The client's both-sides-prose pair stays
pinned by unit test.

## Live kit

```
py backend/scripts/make_prod02_test_pdfs.py   ->  prod02_test_data/
```

**TWO files, and that is the floor** - `detect_source_conflicts` returns `[]` on
`len(docs) < 2`, so one PDF cannot raise the card even on the OLD code.

**The controls had to be `risk_transfer` SUB-KEYS, and the first draft got that
wrong.** Live, `skip_fields = RECONCILABLE_FIELD_KEYS | assessed_keys` and
`ENABLE_FULL_FIELD_RECONCILIATION` auto-discovers every SCALAR, so
`num_employees` / `carrier_name` / `total_revenue` / `policy_number` never reach
this function. `_auto_scalar_keys` explicitly skips **dicts** - which is exactly
why the client's card came from `risk_transfer`.

The script refuses to write unless it BITES: it drives the real function twice
(door forced on, then forced to always agree) and requires the wording card to
appear in the "before" and vanish in the "after". Proved by reverting - it
prints *"the wording card STILL fires"* and exits non-zero.

## Still open - neither is PROD-02

1. **IMPORTANT ranks by TIER, and the tiers are wrong.** Removing the card freed
   the slot; it did not reorder the list. `required` is document-conflict
   prefixes + 10 coded rules; **43 rules - umbrella attachment, property COPE,
   auto symbols, WC payroll, claims-made, business income, coinsurance - are
   `recommended`**. A coverage gap can never outrank a cross-document text
   conflict (`_cluster_rank_key`'s form count only sorts WITHIN a tier).
   **Owner's call** - it changes what every producer sees first.
2. **One conflict, two screens, contradictory instructions** (pre-existing).
   `Certificate Holder` and `Mortgagee Name` each render as a Data Consistency
   picker row (radios, sources, working **Confirm**) AND as a warning card saying
   *"it can't be applied automatically"*. Extraction writes these names BOTH
   top-level and nested under `risk_transfer`; the picker auto-discovers the
   scalars, `detect_source_conflicts` owns the nested copies. **UI-13 does not
   catch it** - that keys on `underwriting_reconciliation_*`, these carry
   `source_conflict_*`. Same defect, different door.

## Deliberately NOT changed

The ACORD 25 footer is still STORED as
`risk_transfer.specific_wording_requirements`. Traced every consumer:
`sqs_service.risk_transfer_check` is the only reader and has **zero callers in
the backend**; the frontend has no reference to `risk_transfer` at all. Dead
code - the value never reaches a screen or a form, so a boilerplate-detection
heuristic (which could drop a GENUINE wording requirement) buys nothing.

## Standing lesson

`fact_comparison.py` named this exact site as unmigrated, in its own header, for
19 days. **A migration is not finished while its own docstring still names a
holdout - and a build guard watching three function names cannot see a fourth.**

## Key files

`services/extraction_service.py` (`_door_conflict`, `detect_source_conflicts`,
`_structured_dict_field_conflicts`) · `services/fact_comparison.py` (header
corrected) · `tests/test_prod02_prose_conflicts.py` (28) ·
`backend/scripts/make_prod02_test_pdfs.py` (new). Full entry in
`1stSep-liveTestFixes.md`.
