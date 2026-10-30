# ACORD intake - reading uploaded, filled ACORD forms exactly (27 Oct 2026 -)

Living design + build log. Read this before touching `backend/services/acord_intake/`.

## Problem (Brent, 26 Oct)
Producers upload completed ACORD forms inside packages. Today they are read like any document: the
fillable values become "label: value" text (`utils/form_field_text.py`), the AI extracts facts from it,
and the keyword classifier types the document. Brent re-uploaded our own generated forms: 97 -> 60
(130 read as a narrative, 28 as a dec; proposed vs current term and building vs total value as false
conflicts; answers with no box lost; locations 2 -> 6). Deadline: all current forms by Fri 30 Oct.

## Decisions (owner, 27 Oct)
- Build it ourselves; Transcriber later plugs into the scanned-form slot.
- Merge rules built now, Brent confirms (one table - `merge_rules.py`).
- An uploaded ACORD form is pre-ticked at form selection (recommender untouched).
- No template / flattened unknown form / scans: today's AI path, flagged "Needs Verification".
- Test packages allowed: 3 on the owner's localhost account (round trip, mixed, flattened).

## Measured facts that shaped the design
- Box names in an outside filled ACORD 125 == our template == our schema (547 boxes, same per-page split).
  Recognition of a fillable page = a name match against the 17 schemas.
- Reversing the FILL RULES alone maps very little: ACORD 125 24 rule boxes + 119 table cells of 548,
  ACORD 160 51 of 1,135. Most boxes are filled by resolvers or by the AI gap fill, and many boxes (Y/N
  questions, form-only details) have NO fact behind them at all.
  => The reverse map is LEARNED by probing our own stamper (markers in, see which box prints which),
  and boxes with no fact are CARRIED box-to-box to the same form + kept as evidence text.
- Per-document fact envelope (what the AI path produces): `{"value", "source", "confidence"}`;
  list facts are plain row lists. The ACORD read produces the same shape, source `acord_form`.

## Design
`backend/services/acord_intake/`
- `recognize.py` - per page: fillable (box names vs schemas) / flattened (printed footer) / not ACORD.
- `read.py` - fillable read by box name (`form_field_text` fields, which now carry `name`) + the fact builder.
- `overlay.py` - flattened read: template page by the printed "Page n of m" (127 repeats its captions), offset
  from captions printed once on both pages, a box = the new characters inside its rectangle; a tick = a new
  char or drawn mark inside a checkbox that is not the box's own frame (a flattener draws frames).
- `carry.py` - boxes with no fact print back on the same form at generation (`form_service.process_single_form`),
  only over a blank or an AI guess, never over a fact's value; two uploaded copies that disagree carry nothing.
- `primble_record.py` - an ENCRYPTED record in every generated PDF's document info (`signature_boxes.
  regenerate_pdf_for_form`, the one download door): the package's person answers + the AI-filled boxes. Our own
  forms re-uploaded restore answers no box prints (occupancy type) and keep AI boxes AI. Key-bound: a form from
  primble.ai restores on primble.ai only. PRIMBLE_FORM_RECORD=0 off. (Owner's point, 27 Oct: answers that
  reach no form would otherwise be asked again on a re-upload.)
- `reverse_map.py` - box -> fact / list cell / tick meaning, from the learned map file.
- `merge_rules.py` - owner per kind of fact (applicant + submission = ACORD; current policies = dec).
- One seam: `extraction_pipeline.extract_document`.

## Build log (27 Oct)
- Built: `recognize.py` (box names >= 90% one schema, or the footer; CA/CO by footer; a box-light page of a
  fillable form stays fillable), `read.py` (fillable read by name via `form_field_text` - FilledField now
  carries `name`; copies split when the template page number does not move forward), `reverse_map.py`,
  `merge_rules.py`, `intake.py` (the seam), `scripts/build_acord_reverse_map.py` ->
  `backend/forms_reverse/acord_reverse_map.json` (~2 min, all 17 forms).
- Reverse map = ONE lookup `box_targets`, in order: scope override (ACORD 125 page one is the PROPOSED policy:
  Carrier -> `submission_carrier_name`, its NAIC / policy number carried) -> structural ACORD naming (prior
  grid by line + row, line-of-business ticks, Renew tick, 140 coinsurance / valuation codes, per-line premium
  boxes CARRIED never mapped) -> the stamper's `_SCHEDULE_REGISTRY` name bindings (VIN / year / make / model /
  driver names - the probe cannot mark a VIN the VIN check refuses, nor a year) -> the learned probe map ->
  a state / county / line-two sibling of a mapped address.
- Probe pitfalls found and fixed: a fillable ACORD prints "No" in unticked boxes - "No" is OFF (the first
  build said every entity option ticked every entity box); option facts are probed tick-by-tick against a
  baseline; markers keep each fact's shape (FEIN, NAIC, policy number with digits, dates, money).
- Seam: `extraction_pipeline.extract_document` -> `intake.read_for_document`: a document of only fillable
  ACORD pages makes NO extraction call; a mixed PDF sends only its other pages; exact facts overlay any model
  fact of the same document; flags from the lines read AND from the forms themselves (126 = GL ...).
  Doc types: 125 -> application, 25 / 28 -> certificate, others -> acord_form (all proposal roles, so Data
  Consistency's proposed-term skip already keeps the proposed term out of the current-term comparison).
- Merge (`extraction_service.merge_facts`): `fold_acord_lists` folds schedule rows printed on several ACORD
  forms by identity (location+building, VIN / year-make-model, licence / name+DOB, claim number, line+term) -
  only ACROSS documents, never two rows of one form (two identical vans are two vans); on copies only.
  `apply_owner_rules` after the authoritative-source override: applicant + submission = ACORD, current-policy
  facts = declarations, a person's answer untouched, a prior-year ACORD (term began > 30 days ago or ended)
  gives identity only.
- Own derived text never read as a statement ("See the attached ACORD 101 ..."); Primble's own vehicle
  continuation on ACORD 101 ("Vehicle 5 | 2004 CHEVROLET ... | Cost new ... | Class ...") read back.
- Round trip (Choice Electric 6e58bd73's 10 forms, offline harness scratchpad acord/offline_rt.py, 0 model
  calls): 58 (first live upload 96ede04c) -> 60 -> rising; 37 of 40 scalar facts identical.
- TELL BRENT (27 Oct, owner) - what a re-uploaded form brings back, in client-checklist-25oct.md "Tell Brent (next
  mail)": 18 of 26 pre-form answers and all 3 saved tables are in the boxes; the other 8 have no box and travel in
  the encrypted record - only on Primble's own downloaded PDF, on the same server (primble.ai and localhost keys
  differ; a re-save or print through another tool drops it); ACORD 25 / 28 never carry it.
- KNOWN LIMITS, tell Brent: a forms-only round trip cannot bring back what no ACORD box holds (loss runs
  as documents -> Loss History, an answer with no box such as occupancy type, drivers past the 127's 4
  rows); the 137 symbol grid rows other than A cannot be told apart (auto_symbols.py note).

## Results (27 Oct)
- Flattened vs fillable, box by box, 10 Choice Electric forms: 490 of 491 identical, 0 false ticks (the one
  miss is text the printed box itself clips: "Commercial Liability Umbre").
- Offline round trip of Choice Electric 6e58bd73's forms (0 model calls for the ACORD forms):
  58 (first) -> 60 -> 81 (Primble record) -> 82 (excess layer, liability symbol) ; forms + the 2 loss-run
  spreadsheets: 90 Submission Ready, no cap (2 model calls, the spreadsheets). Left: the loss-run ownership
  step (asked again - the old answer was for the old runs' documents, correct) and the prior carrier's name.
- Facts read back: 37 of 40 scalars identical on the first pass; 17 of 17 vehicles (4 on the 127 + 13 on
  Primble's 101 continuation), 12 of 12 drivers, 2 of 2 buildings (125 + 140 + 130 folded), 3 WC class rows,
  4 prior-carrier rows, entity type, coinsurance, valuation, liability symbol 1.
- Form selection: an uploaded APPLICATION form is pre-ticked once (`uploaded_application_form` on the
  recommendation, `formSelection.withUploadedForms`); ACORD 25 / 28 certificates never are.
- Unread ACORD pages (scanned / no template) keep today's path with LOW type confidence = "Needs Verification".
- Tests: `backend/tests/test_acord_intake.py` (48).

## Review (27 Oct)
Adversarial review of the build above. Every defect was reproduced on a real PDF built from our templates (or the
owner's Choice Electric kit), pinned by a test written FAILING first in `backend/tests/test_acord_intake_review.py`
(69), then fixed at the class. Two fixtures of `test_acord_intake.py` were wrong (a record of a package naming "x" /
nobody laid into a Pinecrest form - the cross-insured case below) and now name the form's own insured.

**Wrong values with exact confidence (fixed):**
1. Flattened overlay aligned by a median OFFSET only: a 97% "fit to page" print read ~200 boxes of garbage (applicant
   = the street, effective date = "APPLICANT", entity Trust, template captions as loss rows). `overlay._fit`: scale +
   offset per axis (Theil-Sen), at least half the template page's captions within 2 pt, uniform scale - else the page
   is NOT read (needs verification). Shifted / 90% / 97% pages now read identically or not at all.
2. A dec page printing "ACORD 125 (2025/03)" was read AS an ACORD 125 (garbage facts, invented flags) and its text never
   reached the model. `recognize.footer_of`: the footer counts only in the page's footer band (bottom 15%, by geometry;
   last 400 chars for OCR text) - plus (1).
3. ACORD 25's insurer roster was read by POSITION (Insurer B = Business Auto), so a certificate whose auto is written
   by A and WC by B gave auto the WC insurer. `reverse_map.roster_targets`: joined by each row's INSR LTR via the
   stamper's own `_CERT_SECTION_POLICY_COLUMN`; one listed insurer affords every row.
4. Section-form headers: the PROPOSED date merged into the dec's current policy (seen on the Choice Electric round
   trip: GL "effective 01/01/2027, expiration 01/01/2026"); ACORD 160 read as a CYBER policy (+has_cyber), 138 as
   INLAND MARINE. `proposal_targets`: header dates are the proposed term (`pdf_service.proposed_term_fact`, the
   editor's own door); carrier / NAIC / number only into the form's OWN title line (`reverse_map.FORM_FAMILIES`,
   shared with intake's flags) - Brent's "section forms keep the current identity" - else carried. Certificates keep
   their reading. Excess / umbrella layer identities survive (no withheld umbrella limit).
5. Prose boxes: the 125 remarks became a LOSS ROW (claim number = the whole remark); the 101's composed box was read
   whole into BOTH `additional_remarks_text` and `qn_carrier_narrative` (5k chars, printed twice on regeneration).
   ACORD's remarks boxes are the remarks (structural rule); `read.own_blocks_removed` cuts Primble's own continuation
   blocks (headings read off the stamper's constants); a prose box never fills a table cell; a box printing two
   whole facts is carried (`sound_targets`).
6. A redacted FEIN ("XX-XXXXXXX") became the package FEIN over the dec's, silently. `read.fits_fact`: a box's text
   must pass its fact's person-answer check (`fact_registry.answer_refusal`; "Statutory" still reads).
7. A prior-year ACORD outvoted this year's dec (revenue $3M over $5M, employees 22 over 40). `merge_rules`: a prior
   application fills only a GAP in identity (`PRIOR_IDENTITY_FACTS`); its other facts are removed.
8. **Security:** a hand-written plaintext `/PrimbleRecord` was accepted as producer answers (`decrypt_field` passes
   non-"enc:" text through). `primble_record.read` takes only an authenticated "enc:" blob under 1 MB.
9. A record restored into ANOTHER insured's form (an agent re-using Primble's filled 125 as a template) and a
   prior-year form's record restored last year's typed revenue / term as PERSON answers. Record v2 names its insured;
   answers restore only into a same-insured, current-term form (v1 records - 27 Oct localhost only - as before).
10. Every multi-page fillable form was split into one COPY PER PAGE (AGENCY CUSTOMER ID repeats on every page): boxes
    on pages 2+ were carried under "ACORD_125#2" (never printed), the 130's class row split in two. Template page by
    page-unique boxes; a new copy only on a repeated template page (fillable and flattened; out-of-order pages stay
    one copy, two copies stay two).
11. A prior-carrier grid row set `has_*` flags (a 2022 property policy -> has_property_coverage -> COPE hard stop).
12. A PDF combined without its `/AcroForm` (pages copied, form dictionary not): the ACORD pages read as "flattened,
    0 boxes", were dropped from the model too - lost. Widgets are read from the pages (`read_filled_fields(...,
    require_acroform=False)`); a copy that read no box is unread (model + needs verification).
13. ACORD 137's liability amount is the CSL or the BI-per-person limit by its row's tick (ACORD's own tooltips);
    always read as the CSL. `tick_scoped_targets`. The same rule makes an ADDITIONAL INTEREST the loss payee only
    when its Loss Payee tick is on (our 125 prints the landlord there - it re-read as the loss payee).
14. A certificate (25 / 28) owned the applicant facts (its description of operations replaced the applicant's); a
    certificate first in a PDF typed the whole PDF "certificate", whose role drops revenue / employees.

**Lost values (fixed):** a ticked "No" box (ACORD 133's 19 Yes/No pairs) read as unticked; a checkbox whose /V names
no state it shows (/AS Off) read as ticked (`form_field_text`, shared); a row B..N box wrote a package scalar (131
subsidiary employee count; `pdf_service.scalar_rules_reach`); other named insureds stored as junk keys
"additional_named_insureds#0" (now the list); scanned ACORD pages were never recognised (OCR page text now finds the
footer -> needs verification); designer-prefixed names ("form1[0].X[0]") unrecognised (`recognize.box_name`);
disagreeing grid rows (coinsurance 80 / 90) gave the first; carried text lost its line breaks and was cut at 8,000
chars (`FilledField.raw`); with no page markers, unread pages could be dropped.

**Refuted / held:** the stored map is NOT stale (in-memory rebuild of all 17 forms: 0 differences); 220 of 229
learned scalar targets re-verified by a SOLO probe (the 9 others are the remarks box and per-vehicle deductibles, by
design); identical vans stay two, one VIN folds, buildings fold across 125 / 140 / 130 with and without LOC #;
proposed vs current term raises no card, a real FEIN difference does; another insured's ACORD still trips Submission
Integrity; a tampered or foreign-key record is ignored; a carry never replaces a fact's value; the excess copy's carry
lands on ACORD_131__excess only; placeholders / our pointer text are never statements.

**Measured after the fixes:** Choice Electric kit (record) 82, as before; flattened 490 of 491 boxes identical, 0
false ticks; 42-page fillable PDF 10.8 s (was 17 s), 42-page flattened 36 s (~0.85 s / page, the overlay).

**Judgement calls NOT changed - owner / Brent:**
- The record rides on ACORD 25 / 28 certificates sent to third parties (encrypted, but every person answer of the
  package). Recommend: no record on certificates.
- Downloads are no longer byte-deterministic (Fernet IV): each download's checksum differs; the manifest still
  matches the delivered file.
- Restored answers arrive in a NEW package as person answers ("producer"), tagged `restored_from` only.
- Until the producer settles Submission Integrity, another insured's ACORD wins the applicant identity (owner rule);
  recommend the vote while insureds differ.
- An OUTSIDE section form's header carrier is read as the line's current carrier (Brent's section rule) - a new
  market there raises a carrier card against the dec.
- One row, two boxes, one fact: first box wins (131 occurrence vs aggregate -> umbrella_limit; 126 BI / PD / Other
  deductible -> gl_deductible). The Partnership tick (3 options) reads no entity type.
- Excess carry is keyed by position: a lone excess layer generates as ACORD_131 (carry not applied); a 2-excess tower
  carries onto the first excess slot.
- A carry can fill a box the engine leaves blank on purpose (186 starred questions beside a 126) - no marker tells an
  owned blank from no rule.
- Pre-tick still follows the text-stamp detector; its label says "values were read" also for a scan.
- ACORD 25's description box reads as `operations_description` (now unowned); the registry's fact for that box is
  `certificate_description_of_operations`.
- `business_start_date` "2011" (a year our own 125 prints) fails the date check and is not re-read.
- ACORD variants built with radio groups are not covered (no template of ours has one).

## Re-review (27 Oct)
The lead's four changes, re-reviewed adversarially (tests in `test_acord_intake_review.py`, 85 now):
1. **No record on ACORD 25 / 28** (`_NO_RECORD_FORMS`, by base id) - holds; pinned for 25, 28 and a 125 that keeps it.
2. **Another insured's application owns nothing** - right idea, wrong comparison. `entities_materially_differ` is
   the strict legal-entity re-split test: a loss run's "Choice Elec. LLC", "The Choice Electric Company", "Choice
   Electric Inc", a DBA on the dec ("ROCKET ROOFING" vs the 125's "Acme Holdings LLC" dba Rocket Roofing) and a
   heading read as the insured ("S.B. MO.") all counted as ANOTHER insured - and the whole owner table stood down,
   handing the dec's CURRENT term back over the ACORD's PROPOSED one. Now `merge_rules.names_this_insured`: Submission
   Integrity's own matcher (`_names_match`, the door that asks the producer) + `normalization.same_entity_name`
   (glued OCR names) + the application's DBA + an equal FEIN; non-party names ignored; positive evidence only (an
   application or documents naming nobody keep the ownership); one document naming it is enough. Front Range vs
   Choice Electric still owns nothing, and its prior-year form fills no gap.
3. **Carry skips owned blanks** - over-blocked. `_owned_blank_claim` is True for a box an owner leaves blank for want
   of a FACT too: on the Choice Electric round trip it blocked 14 of 135 carried boxes (the excess 131's whole
   underlying schedule, the 125's audit code, the 126's EBL count, the 137's symbol rows B-H). Now
   `carry._blank_by_package_rule`: blank under this package and NOT blank under the form alone or under every form =
   a package rule (186's starred questions beside a 126 - verified on the real resolver), which beats the upload;
   anything else carries. Round trip: 0 of 135 blocked. Cost: ms per box, ~1.8 s once on a 137 (the state auto grid's
   first build), stamper grid memo reused. The lead's stub test encoded the over-broad rule and was corrected.
   Also: `_Attachment_` ticks (which forms are attached) are the package's own fact - never read, never carried.
4. **ACORD 25's description box -> `certificate_description_of_operations`** - holds. Note: the stamper prints
   `operations_description` in that box, so an uploaded certificate's own wording does not reprint on our 25.

Re-confirmed: `test_acord_intake.py` + `test_acord_intake_review.py` + `test_filled_form_fields_14oct.py` 181 passed;
offline round trip ce_forms2 82, ce_flat 60; flattened vs fillable 490 of 491.

## Round trip on the live harness (27 Oct, evening)
Package A = Choice Electric (7 decs + 2 loss-run CSVs), answered to 100 on the pre-form screen, 11 forms generated
and downloaded through the real download route (Primble record attached). Re-uploaded as B1 (the 11 forms alone)
and B2 (the 11 forms + the 7 decs + the 2 CSVs). Harness: scratchpad `e2e/` (run3.sh, compare.py, formdiff.py -
B's no-model stamp + carry against what A PRINTED, boxes_only.py - the forms read with the record OFF).

**Final: B2 = 100 Submission Ready with zero clicks; B1 = 87** (loss runs ~12 and radius 1 - no ACORD box holds
either; the dec states "LOCAL" and the 127's radius box takes miles). All 26 person answers and 3 tables restore
on both. Boxes alone (record off): 18 of 26 answers + the 3 tables; the other 8 have no box on any form in the
package (fire department type, period of restoration, occupancy type, EQ / flood deductibles - 160 only, umbrella
follows form, "we had claims", loss-run ownership) and ride in the record only.

Defects the round trip found, each fixed by class (tests: `backend/tests/test_acord_round_trip_27oct.py`, 50):
1. **A redacted fleet printed twice** (34 vehicles): rows joined only on a VIN. `merge_rules.fold_rows` joins a
   VIN-less vehicle ONE-TO-ONE with another document's vehicle its description agrees with (year + make/model,
   no disagreeing cost / class / territory / VEH #) - across a declaration and an ACORD form only, never two
   ACORD forms (the 127 and its 101 continuation list different vehicles: two 2022 Equinoxes stay two);
   `_FOLD_WITH_DECLARATIONS`; the native form leads a fold (`_SCHEDULE_HOME_FORMS`, the 127 before the 101).
2. **Box readings judged as model guesses** (the 127's "Service" tick dropped by `drop_unlabelled_vehicle_use`):
   `merge_rules.lift_box_readings` / `restore_box_readings` take the readings (`record["read_keys"]`) out of the
   per-document pre-pass; `extract_document` overlays them after its three AI checks; `fact_state.
   FORM_BOX_SOURCES` joins `_PERIOD_NAMED_SOURCES` (the inference gates). A record-named AI box stays policed.
3. **The prior term lost** (loss window counted from today, 4 of 5 years): the 125's proposed term displaced the
   decs' current term before the renewal router ran. `_keep_displaced_current_term` (pair, both slots empty, ends
   on/before the proposal within one term, `routed_from: current_term`) and, forms only, `_prior_term_from_grid`
   (+ `prior_carrier` from that term's grid rows); both set `renewal_dates_routed` (section forms print the
   proposal).
4. **Umbrella vs excess** - (a) the picker: an ACORD application source agreeing with a policy's own dec places
   nothing (`_scope_by_policy_record`; alone in its group it still decides nothing; certificates never); (b) the
   merge's in-document conflict counted the excess dec's own $4M as the umbrella's rival
   (`_excess_layer_only_amounts`, latent on A - its vote order happened to reject nothing); (c) the excess 131's
   limit kept on its line row reaches the layer view (`umbrella_layers.record_layer_evidence`: the one
   umbrella-family row stating a limit).
5. **ACORD 140 grid read positionally** (the schedule's per-row $5,000 became the policy AOP deductible against
   the dec's "$500, exceptions see schedule"): `read._premises_grid` / `_apply_premises_grid` -> `_property_coverages`
   sections (used only when no document's text prints a schedule); building / BPP by subject; scheduled BI rows,
   per-row deductibles and their "$" answer the BI, AOP and basis checks (`property_coverages.
   schedule_states_limit` / `schedule_states_deductible`).
6. **The 131's UNDERLYING INSURANCE section** read as `underlying_policies` (`read._underlying_schedule`, one row
   per line it states; two 131s fold by `_row_key`).
7. **Per-vehicle garaging / cost new / stated amount** read into the vehicle rows (`reverse_map.garaging_targets`,
   from the stamper's own `VEHICLE_GARAGING_ROW_COLS` and box patterns); a vehicle row's own garaging answers the
   garaging item (`coverage_evidence.auto_completeness_gaps`).
8. **A person's answer read as documents' printings** (the producer's 50% wind vs the dec's 2% - 11 "documents"):
   `primble_record.apply` RETURNS the answers / tables (`doc["acord"]["restored"]`), never writes them into the
   document's facts; `merge_rules.apply_restored_answers` puts them on the package (two forms disagreeing restore
   neither); a box printing the answer is the answer (`apply` pops it; a box changed after download stays and the
   old answer is not restored); `drop_answer_echoes` does the same for certificates, which carry no record, on the
   stored documents before the fold.
9. Smaller: a refused box value is carried (`refused`); a tick naming several options of one fact is carried as a
   tick; the 125's OTHER line rows carry; a digits-only state slot is a postal code (`helpers._parse_address`, the
   Indian PIN in the producer's state box); a year range in a loss-run date column is a period total
   (`loss_history_state._row_is_a_period_total`).

Left, by design or for later: the 101's AI-filled "page 1 of 1"; wording only ("1.08" vs "1.0800", "Commercial
Umbrella" vs "Commercial Liability Umbrella"); the WC endorsement schedule on the 101 needs the WC dec; a record
holds only AI vs person provenance - a calculated box (low_confidence) reads back as the form's statement. Model
re-reads of the SOURCE documents vary run to run (B2's auto dec gave Specified Causes symbol 7, A's did not - the
dec's symbol table is garbled in the text; needs a look at the PDF).

## Orbin round trip (27 Oct, night)
Package A (Orbin, `f45958f5`, 7 forms, 97) downloaded and re-uploaded three ways:

| Re-upload | Score | Why not A's |
|---|---|---|
| O1 forms only | 81 (85 cap) | no loss runs (Loss History 25); the re-uploaded ACORD 130 makes WC part of the submission, so the umbrella now asks for Employers Liability limits (answerable) |
| O2 cover + forms | 81 | same as O1 - the cover's record restores the answers, not documents |
| O3 decs + loss runs + forms + cover | 96 | the WC / auto coverage question did not exist when A was answered (now answerable) |

**Defects found (box-by-box against A's printed forms):**
1. **FIXED - the GL P&AI limit read "6"** (126 / 131, O3). Two causes: (a) a policy's quick-reference index line
   ("Personal And Advertising Injury Liability Exclusions ... 6", a page number) was taken as the limit -
   `extraction_service._NOT_A_LIMIT_LABEL_RE` (exclusions / endorsements / coverage forms / page are policy wording,
   never a limit) and `_MIN_LIMIT_AMOUNT` ($100) in `_line_limit_witnesses`; (b) the re-uploaded 125's Prior Carrier grid
   (which prints a renewal's current policies) marked the GL dec's own BBC7263-26 as a prior term, so its real
   $1,000,000 was set aside - `prior_term_policy_numbers`: a number that is its line's only live record is never history.
2. FIXED - forms only lost the Inland Marine line: the 125's question 4 rows ("other insurance with this company",
   line + number as a pair) were never read; with no IM section form they were its only record
   (`read._other_insurance_rows` / `_join_line_rows`).
3. FIXED - one claim counted twice / three times: the 131 prints a claim with its report date only, the 125 with its
   occurrence date, the loss runs with its number. `merge_rules._describes_same_claim` (every column both state agrees,
   one shared day; one-to-one) and `_LISTS_OF_RECORD` (an ACORD row restating a claim the loss runs list adds none).
4. FIXED - one premises became two: the 186's "6 full-time employees" became a location row with no address
   (`merge_rules._fold_identity_less_locations` - joins the one premises, dropped beside several).
5. NOT A DEFECT - the 125 BuildingOccupancy description A printed was an AI fill of a GL class name ("Contractors -
   Executive Supervisors"); B leaving it blank is right.

**Re-run after the fixes (forms only, `2d53ebc5`): every box of all 7 forms matches A's printed forms - 0 lost, 0 new,
1 changed (the 131 HNOA description, AI wording).** Was 2 lost / 6 changed / 14 new. The score stays 81 for two
correct reasons: no loss runs in a forms-only upload, and the re-uploaded ACORD 130 makes WC part of the submission,
so the umbrella asks for the Employers Liability limit (an answerable warning). Tests: +2 in
`tests/test_acord_round_trip_27oct.py`; the intake files 207 passed. Full suite (before this fix) 21,283 / 1 known / 19.

## Live round trips on three packages (28 Oct, 00:40-03:40)
Each package: source documents uploaded -> every pre-form item answered through the real routes (the page's own plan)
-> forms + cover generated and downloaded -> re-uploaded several ways -> each re-upload's page answered again.

| Package | Pre-form | Forms + decs | Cover + decs | Forms only | Cover alone |
|---|---|---|---|---|---|
| Choice Electric (7 decs + 2 loss runs, 11 forms) | 53 -> 100 | **100** | **100** | 85 -> 100 answered | 75 -> 100 answered |
| Orbin 2526 (dec + loss runs, 4 forms) | 68 -> 100 | - | - | 87 -> 92 (+ loss runs file: 99 -> 100) | 74 -> 91 (loss runs to upload) |
| CH125 (one package PDF, 3 forms) | 85 -> 100 (two claim report dates typed) | 85 -> 100 (two Data Consistency picks) | **100** | 54 -> 92 (loss runs to upload) | 51 -> 91 (loss runs to upload) |

**Fixed during the runs (tests in `tests/test_acord_round_trip_27oct.py`, intake files green):**
- the record carries the narrative's `typed_parts` and its stored reading (`_narrative_reading`, keyed to the text's
  hash): the restored narrative scored 89 against 100 - forms + decs and cover + decs 98 -> 100;
- a cover uploaded alone restores the insured's name and the proposed term from its record, into gaps only (60 -> 75);
- two buildings at one street address stay two rows (`_consolidate_property_locations` keyed the street alone; a row
  naming no building joins building 1) - this was not round-trip only: any dec printing buildings at one address;
- the 131's "Any auto" tick reads back as liability symbol 1 (it became the envelope's keys);
- a box the AI filled comes back onto its own box only (it became a fact and printed in two more deductible boxes);
- "Last, First" driver names split surname / given correctly; an additional interest that is not a loss payee is
  carried, not dropped.

**Open:** CH125 forms + decs - re-reading the same PDF picks a different GL limit (the PDF prints both the expiring and
the requested one; extraction is not repeatable) -> Data Consistency picks, answerable on the page; CH125 package A lists one driver twice ("Gregory L.
Szymanski" and "Szymanski, Gregory"); the empty table save answers "applied: true"; the plan's sample answer for
percent subcontracted (25) cannot foresee a true 35% raising the WC payroll item.

## Answers given AFTER generation (28 Oct, live)
Orbin uploaded fresh, 4 forms generated with everything open, then the side panel's items solved after generation
(contact information, driver schedule, the No Known Losses / claims conflict). Forms + cover downloaded, re-uploaded:

| Re-upload | Solved items back? | Score (original 79 after solving) |
|---|---|---|
| Forms + decs | no | 81 -> **bug, see below** (expected 79) |
| Cover + decs | no | 79 |
| Forms only | no | 72 (no loss runs / document-only facts; the UM/UIM notice holds no points) |

The record is built AT DOWNLOAD from the package's current answers / tables / stores, so a post-generation answer is in
every file downloaded after it (read back from ACORD 125, 126 and the cover: 23 answers + 3 tables each). The
"add ACORD 101" form-choice notice has no answer by design (form selection). Dismiss / Mark resolved marks are not
carried (review marks, they move no score).

**Bug found - the loss runs vouched for themselves (81 vs 79).** The declarations print no FEIN; the loss runs do, so
the package FEIN (printed on the 125) was the loss runs' own. Re-uploaded, the 125's FEIN read as the application's,
the loss runs matched it ("strong" instead of "possible"), and Loss History went 85 -> 100 with no one confirming the
runs belong to the insured. Fix: the record lists the facts only loss runs stated (`primble_record.
_loss_run_only_facts`, record key `loss_run_only`); their box readings are marked `echo_of: loss_run` (`apply`) and
`loss_run_identity._package_identity` leaves them out - the M3 "no self-verify" rule, now also through our own forms.
A value the declarations print too still counts. Test: `test_a_value_only_the_loss_runs_stated_never_verifies_the_
loss_runs`. **Live re-check 28 Oct (session ae2f4c99, fresh download, forms + decs + loss runs): 79 = the original 79; loss runs `possible` (matched on name only, FEIN / policy / address no longer self-verify). Fixed.**

## Review (28 Oct) - hostile round-trip review
Offline replay of the owner's three test packages (Orbin `432c8594`, Choice Electric `790d6faf`, CH125 `17eeeb33`):
forms + cover downloaded through the real door, re-read with 0 model calls beside A's own stored source documents,
finalized with the DB save intercepted (scratchpad `rv28/replay.py`). Before -> after: Orbin forms + decs 81 -> **79**
(= A), CH125 forms + decs 85 -> **100** (= A), all cover + decs and forms + cover + decs = A; forms-only always below A.
Fixed (tests: `backend/tests/test_round_trip_review_28oct.py`):
1. Our own form's text was document evidence (the narrative scan reads every body): own forms (record authenticated,
   same insured) store only their unread pages' text (`intake` `stored_text`); `text_key` keeps the duplicate check.
2. AI boxes: only "ai*" labels were recorded and only whole-fact boxes recognised - an unverified ("low_confidence")
   guess, an AI table cell (vehicle cost new, COPE), tick or address part read back exact. The record now lists every
   AI box (a calculated / fact-backed "low_confidence" box excepted), its label and a fingerprint of what it printed;
   `read._strip_ai_boxes` takes them out before the reading and carries them back with their AI label (a box typed over
   after download is the form's statement).
3. Forms-only lost every declaration flag, so flag-gated charges vanished: the record carries the TRUE business flags
   (never line flags, never loss / narrative / document flags); they fill only flags no document states.
4. Data Consistency picks (`underwriting_confirmations`) were not in the record - they ride it now and are re-applied.
5. One set of forms vouched for itself: its ACORD 28 was the "other document" naming the insured, so Choice Electric's
   forms beside Orbin's decs restored 23 answers and took the identity (`merge_rules.identity_witnesses`).
6. Wrong readings: the 125 contact block (a schedule: row A is not the package contact); the payment-method box
   (ACH read as the billing plan); a current-policy fact the form states and a dec AGREES with was outvoted by the
   first other dec (umbrella $5M -> the excess's $4M).
7. Duplicates: drivers (127 names vs the dec's rows), prior policies (125 grid) and underlying policies (131) fold
   with the declarations' rows by description; the same form uploaded twice folds identical rows.
8. Loss runs verifying themselves through two round trips (`echo_of` honoured in `_loss_run_only_facts`).
9. Flattened forms: glyphs a box CLIPS (a long remarks box running over the loss rows) were read as values - the
   overlay now keeps only glyphs with new ink on the rendered page and leaves a box with hidden or overprinted text
   unread (blank over wrong).
Known, not fixed: Submission Integrity resolutions and document reclassifications are per document and do not ride the
record; a form with no record (old download, re-printed) is an outside form; forms-only CH125 needs occupancy again.

### Live round trip after the two reviews (28 Oct, localhost)

Fresh downloads of A, re-uploaded through the real routes, then the pre-form page answered.

| Package (A) | Forms + decs | Cover + decs | Forms only | Cover only |
|---|---|---|---|---|
| Orbin (100) | **100** | **100** | 85 -> 92 answered (loss runs to upload) | 74 -> 91 answered (loss runs to upload) |
| CH125 (100) | 85 -> **100** after the echo fix | **100** | 46 -> 92 answered | 49 -> 91 answered |

Echo fix: CH125 forms + decs opened at 85 on three Data Consistency cards (comp deductible, medical expense, vehicle use). In A those were the AI's reading of the CH125 PDF; the re-read gave $500 / $10,000, and our form printing A's reading counted as a second document disagreeing. The record now carries `document_read` (every scalar no person put), `apply` marks a box printing it `echo_of="documents"`, and `underwriting_consistency` skips an echo when a non-echo document states the fact (forms only: the echo still speaks; a box changed after download is the form's own word). Tests: 3 in `tests/test_round_trip_review_28oct.py`. Box differences on the 125 / 127 in the decs variants come from the dec's fresh extraction (cover + decs shows the same), not intake.

### Review (29 Oct, 30-min hostile pass) - 2 fixed, 1 risk open
- FIXED: a hand edit after download was overridden by the stale answer riding ANOTHER form's record
  (`primble_record.apply` names the contradicted keys as `edited`; `merge_rules._edited_answers` keeps
  them out of the restore - the form's new word wins). Tests: `tests/test_round_trip_review_29oct.py`.
- FIXED: our own form with a retyped insured name (a typo) stored its whole text as document evidence
  (`AcordRead.carries_record`; a file carrying our record never stores its text, whatever the insured).
- OPEN, owner's call: `merge_rules._PRIOR_YEAR_DAYS = 30` - our own form re-uploaded more than 30 days
  after its proposed effective date is judged "last year's application" and restores NOTHING (Choice
  Electric's 01/01/2027 term: the same files give 100 today and a far lower score from 1 Feb 2027).
  Proposed: a form carrying our authenticated record is prior only when its term has ENDED.
- Also noted: `_fact_backed` returns True on any exception (an AI box could read back exact); dismiss /
  resolve marks, integrity resolutions and reclassifications do not ride the record (known).
- Orbin replay on the fixed code: forms + decs 79 = A, cover + decs 79 = A; intake files 247 passed.
- **29 Oct, DECIDED by the owner and BUILT:** a form carrying our authenticated record is "last year's
  application" ONLY when its term has ENDED (`merge_rules.is_prior_application(own_record=True)`, used by
  `read.read_acord`, the summary record and `intake`); outside forms keep the 30-day rule. Test:
  `test_our_own_form_is_prior_only_when_its_term_has_ended`.
- **29 Oct, owner: ACCOUNT BINDING built.** Every record carries `account` = a one-way key of the user who
  downloaded it (`primble_record.account_key`); `extraction_pipeline.extract_document` sets the uploader
  (`uploading_account`, a ContextVar); `apply` and `summary_payload` restore nothing for another account
  (`same_account`) - the form reads as an outside form, its AI boxes still AI and its echoes still echoes.
  Records written before 29 Oct carry no account and keep today's behaviour. Test:
  `test_a_record_restores_only_for_the_account_that_wrote_it`.

### Production fuzz (29 Oct 2026, offline, no model) - 4 fixed
Sweep: random fillable / flattened / bound / shuffled / rotated / truncated / bit-flipped / encrypted / zero-page
PDFs from our 17 templates through `intake.read_for_document` + `overlay_facts` (scratchpad `fuzz29/run_read.py`,
~3 s a case), and a property fuzz of `merge_rules.fold_rows` (`fuzz29/fold_fuzz.py`, 10,500 packages: the folded
count must equal the union). Crash rate 0 before and after (every failure inside the reader already fell back).
Fold: vehicles / claims / drivers fold to the union with VINs in any case / dashes / spaces and money / dates in any
spelling; the only misses (0.2-0.3% of vehicle packages) are VIN-less rows of two vehicles with the SAME year, make
and model - genuinely ambiguous, left as is.
Fixed (tests: `backend/tests/test_production_fuzz_29oct.py`):
1. **Two insureds' forms bound in one PDF became ONE Frankenstein application, all exact**: the first insured's name
   with the second's FEIN, entity type and expiration date, both insureds' rows in one schedule. `read._one_insured`:
   the first form naming an insured names the document's; a form naming another (the merge's own
   `names_this_insured`) is set aside unread - its pages are flagged "names another insured than this document's
   first form", NOT sent to the model, and the document is typed Needs Verification (low confidence).
2. **Two copies of one form that disagree** (a draft and a revised 125 in one file): the first copy's box won and the
   second filled the gaps. `read.boxes_to_facts` now reads a scalar only when every copy stating it agrees (the one
   comparison door, so "ALPHA ROOFING, L.L.C." = "Alpha Roofing LLC"); an address is one copy's parts, never one
   copy's street with another's city / ZIP.
3. **The proposed term is one application's pair** (`merge_rules.apply_owner_rules`): two current applications of one
   insured gave the first one's start and the second one's end; the end now comes from the application giving the
   start (or is left to the declarations / the picker).
4. **ASG Transcriber readings printed as exact** in two places: a tick-derived scalar (entity type) in a MIXED document
   (fillable + Transcriber copies) stayed `acord_exact` - now labelled from the copies whose ticks chose it; boxes a
   Transcriber copy CARRIED (Y/N answers, form-only details) printed "filled" - now "ai_verified" (Please verify)
   unless an exact read of another upload states the box (`read.transcriber_carried`, record `carried_transcriber`,
   `carry.carried_transcriber_boxes`). `test_asg_transcriber_29oct` pinned the old "left exact" - the TEST was wrong.
Open: Transcriber-read TABLE cells (vehicles, claims, locations) still print `filled` (rows carry no envelope - needs a
per-row reader mark the stamper reads); a disagreement between two DOCUMENTS' applications still lets the first
upload's scalar win at the merge (the per-document copies raise the Data Consistency card).

## Data items 4 / 7 / 8 / 9 (29 Oct 2026 night, Builder A, offline, uncommitted)
- **7 One claim = one row.** `merge_rules.same_claim_event` (claim numbers decide when both print one; else the date of
  loss is the same day, the lines are compatible - a cut LOB box "General Lia" / "Commercia" stands for every line name
  it begins, `claim_line_families` - and carriers do not differ; amounts never decide) drives the fold
  (`unique_claim_match`) and the loss-runs-of-record filter (`restates_record_claim`; several loss runs printing one
  claim are one claim; two claims of a day and line are narrowed by amount, else the ACORD row stays). Kit: 12 claims ->
  9; the auto claim keeps the loss run's $18,420.
- **4 Rows matched across documents.** Vehicles: `_truncated_vin_of` reads make / model as words (`_desc_compatible`:
  "ProMaster 2500" = "ProMaster Cargo Van 2500" - kit 6 vehicles -> 4); `near_vin_same_vehicle` joins two full VINs
  one character apart only when both schedules give it the SAME VEH #, neither document prints the other's VIN and
  only one candidate exists (otherwise two vehicles - consecutive serials). Drivers: a name listed once on each side
  joins only when neither licence nor birth date disagrees (one side does not print it); same name + two birth dates
  = two people, a licence match makes the date a rival. After the merge `services/row_rivals.attach_row_rivals` matches every
  merged row back to each document's own row (VIN / truncated / one-off; licence, else a unique name; LOC + BLDG /
  street + BLDG; claim number, else date + line), keeps the authoritative value in the cell (loss run > declarations >
  other > ACORD form; a person's saved table is never judged) and records `row["_rivals"][col] = {kept: {value,
  documents}, others: [{value, documents}]}`. Compared cells: VIN / year / cost new, DOB / licence / licence state /
  hire date, building area / year built / roof year, paid / reserved. A truncated VIN is no rival.
- **Row-level Data Consistency card** (`row_rivals.row_fields`, appended by ONE call in
  `assess_underwriting_consistency`): key `row:<list>:<col>:<hash of the disputed values>` (stable across re-merges,
  never a row position; carried by the Primble record's `confirmations`), label "<schedule> row <n> (<row label>):
  <column>", `conflict_reason` "Documents disagree (Declarations: 12/03/1991; ACORD Form: 12/08/1991)", `row_level:
  true`. It holds 85 and is a plan "dc" item like any picker row (`stops_now` reads it unchanged). The pick goes through
  `/api/underwriting/confirm-value` (and `-in-editor`): `validate_row_confirmation` (the row must exist; N/A / TBD
  refused), then `apply_confirmations` -> `apply_row_confirmations` writes that one cell (copy-on-write). Frontend: the
  existing picker renders it; one line "One schedule row - your pick changes only this value on this row."
- **8 Outside 125 phone / revenue / staff.** `reverse_map.applicant_row_a_targets`: BUSINESS PHONE # ->
  `applicant_business_phone` (the stamper's own `_APPLICANT_ROW_A_FACTS`; registered in `FACT_REGISTRY`, tier None;
  an applicant fact in the owner table). `acord_intake/document_settle.settle_acord_document` (run per ACORD document
  at the start of `merge_facts`, idempotent): promotes a stored document's CARRIED phone box; derives
  `total_revenue` / `num_employees_full_time` / `_part_time` / `num_employees` from the premises rows (each premises
  once; one location = the row, several = the sum) when the form states none, marked `derived_from: location_rows` -
  a derived sum never outvotes a stated total (`apply_owner_rules`), it meets it as a card.
  `cross_form_validator._check_location_revenue_over_total` (warning, verify-a-figure on `total_revenue`): one
  premises' revenue above the business total.
- **9 Address blocks.** `document_settle.parse_address_block` reads a name / street / suite / city / state / ZIP block
  once (lines before the first street line - a name - dropped); `read._compose_address` uses it, the separate boxes
  fill only what the block lacks; `repair_block_address` settles a stored garbled value at the merge. Kit:
  "4150 S Kalamath St, Suite 210, Denver, CO 80223", printing Ste 210 / Denver / CO / 80223 in their boxes.
Tests: `tests/test_build_data_items_29oct.py` (34).

- **LOC # is the premises' (29 Oct 2026 night, Builder A).** `_consolidate_property_locations` threw away a LOC # a document printed and `assign_location_numbers` numbered by row, so building 2 at premises 1 read LOC 2 in the table, on 125 / 140 and on the row card. Now the printed LOC # is kept as `premises_number`; a printed number claimed by two different streets decides nothing; a building at a numbered premises' street takes its number; buildings at one street with none printed share one new number; rows without building numbers number 1, 2, 3 as before. Kit: LOC 1 / BLDG 1, LOC 1 / BLDG 2, LOC 2 / BLDG 1 on 125 and 140; the row card reads "(Loc 1 Bldg 2 - 4150 S Kalamath St)". Still separate: the address-only echo row (Michelle's list) takes the next number (LOC 3 on the 125).
- **An address echo at a documented premises is that premises (29 Oct 2026 night, Builder A).** In `_consolidate_property_locations`, a row that states only an address (no building or premises number, no premises data) joins the first building at the same street (line 1 + city - its suite does not make it another premises); `assign_location_numbers` compares premises by line 1 + city too. A row at another street, with its own building data or its own building number stays. Kit: 3 location rows (was 4) - LOC 1 / BLDG 1, LOC 1 / BLDG 2, LOC 2 / BLDG 1 on 125 and 140; no echo row, no COPE item for it.
- **Same street, another city = another premises (29 Oct 2026 night, Builder A).** The address-only joins in `_consolidate_property_locations` (the existing "row naming no building joins the first building" and the echo join) now require the city and the 5-digit ZIP to agree when both rows state them (`_same_place`); a side stating none may still join.

### Clipped names (strict review, 29 Oct 2026)
A flattened ACORD read by template overlay / a transcriber clips a long name at the box edge: the 125's GL carrier
read "Summit Peak Casualty Compai" while the dec printed "Summit Peak Casualty Company", so the 131's underlying GL
insurer box was left blank as a two-source conflict (`_resolve_underlying_policy_row`). `normalization.same_entity_name`
now also joins two printings whose words are equal in order except the last, where the shorter last word (>= 4
letters) is a prefix of the other's - or is once its own last letter (the half-letter at the cut) is dropped. Read on
the strict tokens and the plain words (the strict key canonicalises "Corporation" -> "corp", "Corpor" never got
there). Never joined: "ABC Roofing" / "ABC Roofers Supply", "ABC Roofing" / "ABC Roofers", "Summit Peak Casualty" /
"Summit Peak Insurance", LLC / Inc, a 3-letter stub. Equality only - `entity_compact_key` (a grouping key) is exact.
The 131 box prints the whole name (`fuller_entity_printing`). Tests in `tests/test_strict_review_29oct.py`.

## Keep everything Transcriber reads (29 Oct 2026; ASG_TRANSCRIBER.md "Keep everything")
- Every Transcriber box is kept ENCRYPTED on the document (`acord.transcriber.elabels_enc`,
  `transcriber_intake.seal_elabels` / `read_elabels`) - never plaintext on the session row.
- `reverse_map.box_targets` for a form outside our 17: the learned-map slot is `learned_targets` ->
  `shared_targets` (ACORD's shared field dictionary: the meaning every known form printing the eLabel agrees on;
  disagreeing, scope-sensitive and one-form schedule names are not guessed). Known forms are unchanged
  (`is_known_form`; pinned by test). The sibling layer reads through the same door.
- The boxes no fact sits behind are shown to the owner, never scored: `GET /api/session/{id}/documents/{doc_id}/form-values`,
  "View values read from the form" on both Documents lists. Probe as an unknown form: 8 -> 24 facts.
- `acord.carried` holds only forms we regenerate (`intake._regenerable_only`); the dictionary is built once per process
  and warmed at startup (`reverse_map.build_shared_dictionary`).
