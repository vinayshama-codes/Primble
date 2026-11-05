# Accommodating 800+ ACORD forms - running log (started 30 Oct 2026)

**This is THE file for "any ACORD form" (generate / download any of ACORD's 800+ forms). Update it at every
step: findings, decisions, builds, measurements, Brent / ASG answers - real dates and times only.**
Related: `ASG_TRANSCRIBER.md` (ASG API contract, pilot agreement, every live ASG call - the READING side),
`ACORD_INTAKE.md` (how uploaded filled ACORDs are read). This file is the GENERATING side.

Source material: `All-800PlusForms-Kit-by-Brent/` (Brent's e-mails of 29 Oct, section 0a, + the kit) and
`ASG_DOCUMENTATION/` (ASG's API docs, confidential, never committed).
Deadline from Brent: **by Fri 6 Nov a user can search / select ANY ACORD form, and Primble fills,
generates and downloads it.** He accepts the missing 10-30% on non-core forms for now.
The owner is on leave 6, 9 and 11 Nov, so the working deadline is **Thu 5 Nov**.

---

## 0. Where things stand (3 Nov 2026, 17:37 IST) - PARKED until Brent's production credentials

- **Done on UAT. NOT committed, NOT for customers yet.**
  - A producer can search ASG's 1,174 forms on "Select Forms to Generate", add up to 8, and generate, edit and
    download them like our 17.
  - The owner live-tested it on localhost on 3 Nov (10.8, 10.19-10.22).
  - Owner, 3 Nov: wait for Brent's production credentials.
- **WHEN THE OWNER TESTS NEXT - ask him FIRST to run the six verification calls (10.22):**
  - ACORD 125 CIS and ACORD 25 INS (variants);
  - ACORD 137 TX and ACORD 50 NY (state versions);
  - two plain forms.

  Only a live call shows whether ASG honours our guessed variant parameter. A wrong form is refused either way.
- **Waiting on Brent:**
  - the PRODUCTION ASG account / credentials - removes the "Sample" watermark (8.19);
  - the scope (P&C only?);
  - the cap (8?).
- **Waiting on ASG:**
  - the variant parameter's name;
  - whether every listed form has a fillable version;
  - what INS / CIS / ONI / PCIS mean, and how to fetch the 12 non-state variants;
  - a forms list API for a weekly refresh (10.18);
  - two list entries that contradict themselves (10.21).
- **Before commit:**
  - one full suite on the final code, with the owner's yes - the last full run (16:11) predates the search sweep and
    the identity check;
  - `git add` the 7 new files (10.10).
- **Before PROD / customers:**
  - fix L-4 / L-5 - ASG forms have no line identity, so a D&O form printed the package's main insurer and another
    policy's coverage part. Deferred by the owner ("accuracy later, as Brent said"), 10.19;
  - one owner-approved PROD test call (8.20);
  - then `ASG_FORMS=1` on Render.
- **How we got here:**
  - analysis 30 Oct (sections 1-7);
  - the plan and the PoC on the morning of 3 Nov (8.x);
  - the build 12:49-15:41, with 11 review rounds (10.1-10.17);
  - the full suite at 16:11;
  - the owner's live test 15:49-17:35 (10.19-10.22).
- **Expectation for the pitches:**
  - Brent's 70-90% is the share of DATA the base forms carry, not the share of boxes filled - a thin package fills a
    thin form (8.3);
  - generic forms fill less than our 17 (they lack our per-form rules) - blank over wrong (10.20).

---

## 0a. Brent's e-mails (29 Oct 2026) - what he asked, in his words where it matters

**Mail 1 (the brief).**
- **Uploaded forms, by Fri 30 Oct:** extract data from ANY ACORD form inside an uploaded package; offload the
  extraction / e-labelling to Transcriber. Long term, Transcriber needs Primble on AWS "for that link so we
  don't burn through our Transcriber API usage". **Done 29-30 Oct** (`ASG_TRANSCRIBER.md`; OFF on primble.ai
  until production terms exist).
- **Why people upload filled packages** (re-uploading our own package is the minor case):
  (a) a producer finished a package ELSEWHERE and runs it through Primble to double-check and validate it;
  (b) a carrier underwriter scores a received package for triage - low scores go to the bottom of the queue
  or back to the producer.
- **Fillable / downloading forms, by next Friday (Diwali, Fri 6 Nov):** users can generate and download ANY
  ACORD form. "There must be a way to sync/pull forms through ASG instead of downloading them from ACORD.
  Please investigate this concept, because if you do not find a way to do it, then I'll have to ask ASG to
  build it as soon as possible."
- The 125 plus the core forms are the basis for all other forms (e-label overlap, 70-90% depending on the
  form). **"As of right now, I don't care about the missing 10-30% of data on those other forms ... as long
  as the user can search/select any ACORD form to fulfill/generate/download now."**
- **E-mail integration** (Transcriber can read users' e-mails): lower priority than the forms, "experiment
  with that sooner rather than later" - on the radar.
- **Business:** the ASG / ACORD agreement lets Primble push into the market "as soon as the full ACORD form
  suite is supported"; investors will not fund pre-seed, so seed needs paying customers ASAP; pitches over
  the next 1.5 weeks on the ASG / ACORD partnership and "support all the forms"; Michelle introduces Primble
  to insurance networking groups with the same message; target **40 paying customers by year end**, about
  5 selling weeks after Diwali.

**Mail 2 (29 Oct, 06:05).** The six core forms for the ACORD base: 125, 126, 127, 130, 131, 140. "One
document corresponds with the other" (the readiness PDF explains the 28-page sample package).

**Mail 3 (the kit).** "A ZIP containing 14 forms files. Our focus being these six forms ... I know the
attachment has other forms and certificates, but just use these ones please as the base." (The folder holds
15 form folders - section 1.)

---

## 1. What Brent sent

| Item | What it is |
|---|---|
| `Primble ACORD Underwriting Readiness.pdf` (5 pages) | A written spec: for each of the 6 core forms, what must be completed and confirmed so an underwriter gets a clean submission; how to treat Y/N questions; the discrepancies in his sample; a pre-marketing checklist; what is NOT needed for an initial quote. |
| `Primble ACORD 6 Forms.pdf` (28 pages, flattened, no fillable boxes) | The matching **sample filled package** - a fictional electrical contractor ("TRAIN-0001"), stamped "PRIMBLE UW REVIEW - Y/N = ANSWER MUST BE CONFIRMED - EXAMPLES ARE NOT VERIFIED", colour-highlighted (green = sample value, yellow = Y/N to answer, blue = conditional / unknown, red = correct / sign). 125 (pp 1-10), 127 (11-14), 130 (15-19), 131 (20-28); 126 and 140 pages are image-only (no text layer). "One document corresponds with the other" = the readiness PDF explains this sample. |
| `Most Common ACORD Forms/` | 15 form folders from ACORD, each with: AdobeFillable PDF, AdobeStatic PDF, IBM XFDL, **FIG** (Form Implementation Guide), an **EForms** folder holding the **Mapping List.csv** (every box -> its ACORD e-label; checked 3 Nov: ALL 15 forms have one) and a **Toolkit** (print-vendor files: .crd, .hp3, .ps, .emf, .wmf - not needed). The `.zip` names are already-unpacked folders. |
| `Key.png` | Folder suffix legend: **A** = top of the list from Bryan, **B** = secondary on Bryan's list, **P** = Primble's own priority. |

Kit forms (folder name = form + key): 1 (B), 2 (B), 25 (A), 27 (A), 35 (A), 37 (B), 50 (B), 75 (A),
80 (B), **125 (AP), 126 (AP), 127 (BP), 130 (BP), 131 (P), 140 (AP)**. Brent: "use these six as the base".

### 1b. The "Most Common ACORD Forms" folder in plain words (3 Nov 2026)
Each sub-folder is ONE ACORD form. Its name = the form number + Brent's priority letter (`Key.png`): **A** = top
of Bryan's list, **B** = second on Bryan's list, **P** = Primble's own priority. So "1 - B" = ACORD 1, second
priority; "125 - AP" = ACORD 125, top priority for Bryan and for Primble.

Inside every form folder (the same set each time, ACORD's standard "forms kit"):

| File / folder | What it is | Do we need it? |
|---|---|---|
| `<n>_<edition>_AdobeFillable.pdf` | The blank form you can type into - but in Adobe's newer XFA style, with long box names (`F[0].P1[0]...`) | No - our engine cannot use this copy |
| `<n>_<edition>_AdobeStatic.pdf` | The same form, flat, for printing on paper - no boxes | No |
| `<n>_<edition>_IBMFillable.xfdl` | The same form for IBM's forms software | No |
| `<n>_<edition>_FIG.pdf` | **Form Implementation Guide** - ACORD's manual for the form: what goes in every box, its format and rules | Reference only |
| `EForms` folder (named `<n>_$<edition>` or `<n>_..._EForms`) -> `... Acroform.pdf` | **The classic fillable form with plain box names** (`Producer_FullName_A`) - the same kind of file ASG's Download API returns and our 17 templates are | This is the useful one - but ASG gives it to us |
| same folder -> `... Mapping List.csv` | A spreadsheet: every box's e-label name, row letter, section and description - the form's "dictionary" | Reference - the same names are inside the PDF itself |
| same folder -> `... Mapping Key.pdf` | The form printed with each box labelled by its e-label number - a picture of the dictionary | Reference |
| `Toolkit` folder (named `<n>_$<edition> 2` or `<n>_..._Toolkit`): `.crd`, `.crd3`, `.hp3`, `.ps`, `.emf`, `.wmf`, FIG `.xls` | Files for companies that build forms-printing software (printer and Windows graphics formats) | No |

Next to the folders: `Primble ACORD 6 Forms.pdf` (Brent's 28-page SAMPLE filled package for the six core forms) and
`Primble ACORD Underwriting Readiness.pdf` (his written spec of what "complete and correct" means for those six).
**Bottom line: with ASG's Download API the folder is reference material only.** Everything we need from it (the
fillable form and its box names) comes from ASG on demand.

## 2. What he means - the catch

There is no contradiction between "focus on 6" and "all forms". They are two different jobs:

1. **Depth on the six core forms (125, 126, 127, 130, 131, 140).** These are the BASE: their data
   (applicant, locations, operations, GL hazards, vehicles / drivers, WC classes / payroll / owners,
   umbrella underlying, COPE) is what every other ACORD form reuses. They must be filled correctly and
   scored / checked deeply - the readiness PDF is the spec for that depth. Primble already supports all
   six (plus 11 more); this job is "make them match the readiness spec", mostly verification + a few
   cross-form checks (section 6).
2. **Breadth: any of the 800+ forms, filled from that base.** ACORD names every box by an **e-label**
   (`Producer_FullName_A`, `NamedInsured_MailingAddress_LineOne_A`, `Policy_EffectiveDate_A`, ...).
   The SAME e-label means the SAME data on every form - that is Brent's "70-90% overlap". Our 17
   schemas, our deterministic rules (`_ACORD_FIELD_RULES`), alias maps and the fact model are already
   keyed on these names. So a new form = its fillable template + its schema (box names read from the
   PDF) -> our existing engine fills every box whose e-label it already knows; the rest stay blank
   (Brent: fine for now).

**The catches (things that decide whether 6 Nov is real):**

- **Where do 800 templates come from?** The kit has 15. We need the AdobeFillable PDF (and ideally the
  Mapping List.csv) for every form. Brent asked us to investigate pulling them from **ASG** instead of
  ACORD; if we cannot, he will ask ASG to build it. This is the critical path - without a template
  source there is nothing to fill. (Licensing: Brent says the ASG / ACORD agreement now covers this -
  confirm in writing that we may store and distribute the PDFs.)
- **A generic form gets no Primble judgement.** No recommender rule (the user picks it - and the
  recommender must not change, owner rule), no per-form hard stops / warnings, no per-form SQS
  checklist. It is "fill what the base knows, leave the rest blank, let the user edit and download".
  The package SQS is unchanged (it is form-independent - G18 / Z35). Decide whether a generic form
  shows a score at all (recommend: no score, just "N of M boxes filled from your package").
- **No AI gap fill on generic forms at first.** Gap fill costs LLM calls per form and is where wrong
  values come from; Brent explicitly accepts the missing 10-30%. Blank over wrong. (Can be switched on
  per form later.)
- **Editions.** Each form has editions; the kit's **ACORD 130 is 2026/08, ours is 2026/01** (the other
  five match: 125 2025/03, 126 2025/03, 127 2015/12, 131 2017/11, 140 2016/03). A form's e-labels can
  change between editions - the template, its schema and its alias map must move together.
- **State variants and supplements** (137 CA / CO, 138, state WC supplements): the search must show
  them as separate forms; our `form_instances` (copies like `ACORD_131__excess`) is unrelated.
- **Box names that are NOT e-labels.** Some older / third-party fillable PDFs use their own field
  names. Then the Mapping List.csv (box -> e-label) is required, or the form fills nothing.
- **Scale of the stamping code.** Several resolvers are form-specific (`_resolve_*` for 125 / 131 /
  140 ...). They stay for the 17. A generic form uses only the e-label-generic rules - good enough for
  the 70-90%, and safe.
- **Repeating rows.** Schedules (vehicles, drivers, locations, classes) use the same e-label with row
  suffixes `_A`, `_B` ... On a generic form, rows fill only where the e-label + suffix convention is
  the one our schedule registry already binds.
- **Transcriber reading uploads is a different track** (done 30 Oct) - it reads ANY uploaded ACORD
  into the base; this document is about GENERATING any ACORD from the base.

## 3. How "any form" would work (design sketch - not built)

1. **Template library**: `backend/templates/acord/<form>_<edition>.pdf` + its Mapping List
   (`backend/forms_elabels/<form>_<edition>.csv`), loaded from ASG (or ACORD) - a script, run once, plus a
   refresh when editions change. Never hand-edited (same rule as `forms_schemas/`).
2. **Catalogue**: form number, title, edition, line(s), state - from the Mapping List / FIG title rows
   (`Form_Title` e-label), so the user can search by number or title.
3. **Schema on demand**: the existing `extract_form_schema` reads the box names + tooltips from the
   fillable PDF (the 17 keep their checked-in schemas; generic forms are read and cached).
4. **Fill**: Pass 1 `_ACORD_FIELD_RULES` + alias stamping on e-labels only; no form-specific resolvers,
   no gap fill; display canonicalisation as today. Unknown boxes blank.
5. **Editor + download**: the existing PDF viewer / editor and download path (a person can type into any
   box; their values stay). The Primble encrypted record can ride along like on the 17.
6. **UI**: "Add any ACORD form" - a search box on form selection and in the editor's add-form window.
   The recommender's suggestions stay exactly as they are.
7. **Measure**: for each new form, report "boxes filled from the package / total" on 2-3 real packages;
   start with the kit's 9 extra forms (1, 2, 27, 35, 37, 50, 75, 80 + the 130 2026/08 edition).

## 4. The six core forms - Brent's readiness spec vs Primble today

Status words: **Have** = built and tested; **Check** = built, verify against this spec on his sample;
**Gap** = not built.

### ACORD 125 - application
- Agency / applicant, entity type, FEIN, contacts, mailing address, requested dates - **Have**.
- Operations, years / date in business, sales, employee counts, all locations / buildings, ownership or
  tenancy - **Have** (premises interest, location table).
- Coverage requested = each line quoted, incl. WC if part of the package; requested lines must match the
  applications attached - **Check** (lines applied for, Z28).
- Prior carriers / numbers / terms / expiring premiums; reportable losses with dates, description, paid,
  reserved, open / closed - **Have** (prior grid + ACORD 101 overflow, loss table).
- Every applicable Y/N answered, Yes explained - **Have** (evidence gate, Y/N not guessed).
- NOT required for an initial quote: carrier policy number, underwriter name, new quoted premium - **Have**
  (Brent's 125 page-one rules, 8 Oct).

### ACORD 126 - GL
- Occurrence / claims-made, limits, options, deductible / SIR - **Have**.
- Hazard schedule: LOC #, HAZ #, classification, verified class code, rating basis, exposure - **Have**
  (GL classification window), **Check** HAZ # numbering.
- Operations incl. height, underground, special hazards - **Check** (narrative topics).
- Subcontractors: type, cost / proportion, certificates, contractual transfer, sub limits - **Check**.
- Products / completed operations - **Have** (product rows guarded).
- Claims-made retro / tail only when claims-made - **Have** (conditional questions).
- Contractors supplement (186) when the risk triggers it - **Have** (recommender; do not change).

### ACORD 127 - business auto
- Drivers (name, DOB, licence state / number, experience, assignments) - **Have** (driver table).
- Vehicles (year, make, model, VIN, garaging, GVW, use, radius, ownership, cost, PD) - **Have**.
- Attach state ACORD 137 for symbols / limits / elections - **Have** (137 CA / CO only - other states
  are generic-form territory).
- Fleet Y/N (ownership, hiring, MVRs, maintenance, telematics, inspections, vehicles omitted) - **Have**
  (Y/N gate). **Gap:** Brent's two consistency rules - telematics details given but the question
  unanswered; "No" to a recruiting method with a Yes-style explanation. A generic "explanation
  contradicts its Y/N" check is not built.
- Lienholders / loss payees, auto loss history - **Have**.

### ACORD 130 - workers comp
- Insured, locations, operations, entity, years in business, policy period - **Have**.
- All states, other-states, EL limits - **Have**.
- Payroll by state / location / class, FT / PT counts, no owner wages twice - **Have** (WC class table),
  **Check** the "owner wages counted twice" reconciliation.
- Owners / officers, duties, %, remuneration, included / excluded - **Have** (officer table).
- 5-year prior carrier history, mods, claims, paid / reserved - **Have**.
- 24 general questions + Yes explanations - **Have** (Y/N gate).
- Never guess mod, class codes, premium - **Have** (rules since H3).
- **Edition:** kit 130 is **2026/08**, ours **2026/01** - template update needed (see section 2).

### ACORD 131 - umbrella / excess
- Umbrella vs excess, occurrence vs claims-made, limits, retention / attachment - **Have** (Z35 SIR or
  attachment).
- Underlying GL / Auto / EL: insurer, number, dates, limits, premiums - **Have**; "verify with
  declarations rather than assuming follow form" - **Have** (never guess follow-form).
- Exposure questions (vehicles, subcontracting, pollution, products, aircraft, watercraft, foreign) -
  **Have** (Y/N gate; C104 coverage sections not carried are not asked).
- Claims over $10,000 in 5 years; **a small WC loss does not answer the umbrella liability-loss
  question** - **Check** (loss-scope rules exist; this exact case not pinned).
- Vehicle count / radius on 131 must agree with the narrative / 127 - **Gap** as a cross-form check.

### ACORD 140 - property
- Premises / building numbers, address, use, ownership / lease - **Have**.
- Building, BPP, stock values, valuation, cause of loss, coinsurance, deductible - **Have**.
- COPE: construction, year built, stories, basement, sq ft, roof type / age, updates; occupancy;
  protection (hydrant, station, class, sprinklers, alarms); exposures - **Have** (per-building table),
  **Check** stories / basement / updates columns.
- BI / extra expense, ACORD 810 when requested - **Check** (810 is not one of our forms - generic track).
- Page 2 (additional premises) only when there is a second premises - **Have** (unused rows not a gap).
- Every 140 premises must appear on 125 with the same location / building numbers - **Have**
  (`prior_policy_placed_once`-style rules exist for locations; **Check** on his sample).

### Y/N rules (all forms) - Brent's wording vs ours
- "Y/N is not an answer", "a No must be deliberate - silence is not No", "conditional questions not
  forced", "a Yes needs its detail" - **Have** (evidence-gated fill; G1-G18; questionnaire).

## 5. Cross-form discrepancies Brent planted in his sample (page 5) - can Primble catch them?

| Discrepancy | Primble today |
|---|---|
| Second warehouse on 140 not on 125 | **Check** (location consolidation / premises rules) |
| Mailing vs work address differ across 130 / 125 / 140 | **Have** (physical vs mailing, Data Consistency) |
| Work at heights: 125 "none over 15 ft" vs 130 "16-25 ft" | **Gap** - no height consistency check |
| Ownership: 125 LLC with 2 members vs 130 one owner 100% | **Gap** - no members vs owners check |
| Start date April 2015 vs "9 years in business" (Oct 2026) | **Gap** - no start date vs years-in-business check |
| Website descriptions differ | **Gap** (not compared) |
| 127 recruiting "No" with a Yes explanation; telematics details with no answer | **Gap** - no Y/N vs explanation contradiction check |
| Is WC a requested line on 125; state auto form; umbrella underlying vs declarations | **Have** / **Check** |
| Illustrative class codes, missing loss runs / mod / COPE evidence | **Have** (never guessed; asked) |
| Sample premiums vs real quotes; umbrella defence / attachment | **Have** (page-one premium rules; SIR / attachment card) |

The five **Gap** rows are one family: **the same fact stated differently on two applications**. They
fit Data Consistency (`underwriting_consistency`) - not built, owner's call.

## 6. Questions for Brent

1. Template source: can ASG supply the fillable PDFs + e-label mapping lists for all forms (and
   edition updates)? If not, will ASG build a sync - and what is our licence for storing / serving them?
2. Generic forms: show NO score (just "filled from your package: N of M boxes"), or a basic score?
3. Search scope for 6 Nov: all 800+, or a first wave (the kit's 15 + the most-used list from Bryan)?
4. Bryan = ? (the A / B list) - a customer / partner whose priority order we should follow?
5. ACORD 130: switch to the 2026/08 edition now?
6. The five cross-form gaps in section 5: build them as Data Consistency warnings?

## 7. Plan (when the owner says go)

1. Template source (ASG) - unblock first; meanwhile build on the kit's 15.
2. Generic fill path (sections 3.1-3.5) behind one switch; the 17 untouched.
3. Search UI + add-form window.
4. Measure fill on 2-3 real packages per new form; report to Brent.
5. Separately: the 130 edition update; the section 5 cross-form gaps (if approved).

(Superseded 3 Nov by section 8.8.)

---

## 8. 3 Nov 2026 analysis - the lead and where to look next

### 8.1 The lead
**Template from ASG's Download API (one call per form + edition + state, kept forever) -> Primble's existing
deterministic engine fills it by e-label -> our editor and download.** Brent's "there must be a way to pull
forms through ASG" - **there is, it is documented, and we proved it on 29 Oct** (`ASG_TRANSCRIBER.md` section 8:
`GET {uat-api-v1}/oauth/forms/download?formNumber=36&latestEdition=true` -> 200, ACORD 36 (2007/01), fillable,
63 boxes). Brent does NOT need to ask ASG to build a sync. What we need from ASG is smaller (8.7).

**ASG's Population API is the fallback, not the road.** It takes e-label JSON / XML and returns a filled PDF of
any form. As the main path it would: spend ASG usage on EVERY generation (the pilot quota is metered and has a
hard stop); return a finished PDF that skips our post-fill guards, the editor, Field QA and the encrypted
Primble record; and still need a facts -> e-label export, which is exactly what our engine already produces.
Keep it for forms the Download API has no fillable template for ("This form has no acroform PDF for download").

### 8.2 What the kit proves (measured 3 Nov 2026, offline, read-only)
**Every box on every kit fillable is named by its e-label** (`F[0].P1[0].Producer_FullName_A[0]` -> leaf
`Producer_FullName_A` = e-label `Producer_FullName` + counter `A`): 15 of 15 forms, 100% of boxes. So a
template ALONE tells us the e-labels; the Mapping List.csv is confirmation plus a description per box (the
same wording as the box tooltip). Templates from ASG are the same AcroForms, so no Mapping List is needed.

| Form | Title | Edition | Boxes | Box names also on our 17 forms |
|---|---|---|---|---|
| 1 | Property Loss Notice | 2019/07 | 108 | 42 (39%) |
| 2 | Automobile Loss Notice | 2019/07 | 260 | 61 (23%) |
| 25 | Certificate of Liability Insurance | 2025/12 | 128 | 128 (100%) - same edition as ours |
| 27 | Evidence of Property Insurance | 2016/03 | 88 | 49 (56%) |
| 35 | Cancellation Request / Policy Release | 2017/05 | 101 | 53 (52%) |
| 37 | Statement of No Loss | 2008/01 | 30 | 25 (83%) |
| 50 | Insurance Identification Card | 2007/02 | 54 | 33 (61%) |
| 75 | Insurance Binder | 2016/03 | 147 | 108 (73%) |
| 80 | Homeowner Application (personal lines) | 2026/03 | 826 | 198 (24%) |
| 125 / 126 / 127 / 131 / 140 | the core forms | same editions as ours | | 100% |
| 130 | Workers Compensation Application | **2026/08** (ours 2026/01) | 484 | 483 |

- **Editions:** all 17 of our templates were checked against their printed edition; only the 130 differs from
  the kit. The 2026/08 130 adds 2 boxes (`NamedInsured_Signature_C`; the tax-liens explanation is now `_A`)
  and drops 2 (`..._TaxLiensOrBankruptcyWithinLastFiveYearsExplanation_W`,
  `WorkersCompensation_RateState_StateOrProvinceName_A1`). Small, but the stamper / gate rules that name the
  dropped boxes must move with it.
- **Brent's 70-90% matches the commercial forms' NAME overlap** (52-83%); loss notices and personal lines are
  much lower (23-39%) because they ask for claim / home data a commercial submission never has.

### 8.3 How much a new form fills today (measured 3 Nov 2026, offline, no AI, network blocked)
Method: the Orbin live package `b8d6` (dec-only, 81 facts; fixture
`tests/fixtures/needs_attention_live_30sep.json`, no database read) run through
`pdf_service.map_facts_to_form(..., allow_llm=False)` on each kit fillable's own boxes, as a form id the
engine has never seen; plus the boxes whose e-label had a value on that package's generated ACORD 125.
Script (scratchpad, not in the repo): `anyform/fill.py`. No repo file changed.

| Form | Boxes (unique) | Engine fills, no AI | Copy from the 125 by e-label | Either |
|---|---|---|---|---|
| 1 | 106 | 12 | 12 | 12 |
| 2 | 257 | 16 | 12 | 16 |
| 25 | 128 | 44 | 12 | 45 |
| 27 | 88 | 12 | 12 | 12 |
| 35 | 101 | 12 | 11 | 12 |
| 37 | 30 | 6 | 6 | 6 |
| 50 | 54 | 14 | 10 | 14 |
| 75 | 146 | 31 | 9 | 31 |
| 80 | 821 | 38 | 22 | 38 |
| 125 (ours, for scale) | 547 | 62 | 81 | 82 |
| 126 / 127 / 130 / 131 / 140 | 254 / 633 / 479 / 392 / 355 | 31 / 35 / 33 / 45 / 11 | | |

What it shows:
- **The engine fills an unknown form with no change and no crash**: producer, insured name and address,
  insurer, policy dates, the vehicle on the 50 (2012 Subaru Outback). Values checked by eye: right boxes.
  The post-fill guards ran too (they blanked a `Policy_EffectiveDate_B` on the 35 / 50 - no second policy).
- **Copying values across forms by e-label adds almost nothing** beyond the engine: the engine already reads
  the same facts. Not needed for the first version.
- **The fill is thin because the PACKAGE is thin.** One dec page; our own 125 without AI fills 62 of 547 (with
  AI and answers the stored 125 had 81). A new form will mirror whatever the package holds - a full
  application package fills more. So Brent's 70-90% = the share of a form's DATA the base forms carry, NOT
  the share of boxes Primble will fill. Tell him before the pitches say "filled forms".
- **Limit of this measure:** one package, dec-only, no AI. Repeat on a full package (Choice Electric) before
  quoting a number to Brent - that needs the owner's yes for a database read, or a fixture.

### 8.4 What it takes in our code (read-only code map, 3 Nov 2026)
**Short answer: no allow-list of the 17 forms exists anywhere; the stamping, editor and download are
form-agnostic. Four things actually stop a new form, and five side effects must be designed around.**
Paths below are under `backend/` unless they start with `frontend/`.

**Box names - which template file to use.** The kit's `*_AdobeFillable.pdf` files carry XFA and dotted box names
(`F[0].P1[0].Producer_FullName_A[0]`); our schema reader (`pdf_service._collect_fields_pikepdf`) reads the field's
own name, so those would not match, and `fill_pdf` never strips XFA. **ASG's downloaded template (ACORD 36) and the
kit's `EForms/... Acroform.pdf` copies have NO XFA and plain e-label names (`Producer_FullName_A`) - exactly like our
17 templates.** Use those. (8.2 / 8.3 read the leaf names, so their numbers stand.)

**What stops a new form today (must change):**
1. **The per-package form list is a snapshot.** Extraction copies the catalogue onto the session row
   (`session["all_forms"]`, `extraction_pipeline.py:1783,1929`); generation finds a form through it
   (`form_instances.form_meta_for`). A form not in it is skipped silently by `select_forms_bulk`
   (`routes/form_routes.py:1778-1781`, also `worker.py:331-335`; 400 if it was the only one), UNKNOWN_FORM in
   `form_addition.py:198-200`, dropped by the dry run. A generic form must be looked up in the catalogue at
   selection time, not from the snapshot.
2. **Adding a form after generation only takes forms an open issue asks for** (`form_addition.py:195-196`,
   NOT_REQUESTED); `policy_line_routes.py:323-345` only takes forms the server offers; a second generation is
   refused once forms exist (`form_routes.py:1670`). "Add any ACORD form" in the editor needs its own door.
3. **`forms_database/<id>.json` must carry `form_name`** - `process_single_form` reads it with a hard key
   (`form_service.py:2731`); a missing key is swallowed and the form just disappears.
4. **"Add more ACORD forms" lists every non-recommended form at 0%** (`form_service.score_extra_forms`,
   `:2303-2334`). With 800+ forms that list - and the per-session `all_forms` JSON - become huge. Search must
   replace it for generic forms; the catalogue must stay OFF the session row.

**Side effects to design around:**
1. **Do NOT put generic schemas in `forms_schemas/`.** `extract_form_schema` writes a schema file there on a cache
   miss (`pdf_service.py:16213-16261`), and "has a schema file" means "one of our forms" to the upload reader
   (`acord_intake/recognize.py:43-55`, `reverse_map.is_known_form` / `learned_targets`), two cached scans in
   `pdf_service` and `field_mapping_integrity`. An uploaded ACORD 27 would then count as known with no
   reverse-map entry and LOSE its current reading. Three tests also pin exactly 17 forms. Keep generic schemas in
   their own store; the viewer already falls back to a stored schema (`viewer_form_schema`, `:39693-39711`).
   A template with no fillable boxes caches `{}` for ever - refuse it instead.
2. **Header identity on single-line forms.** A form not in `_SECTION_FORM_LINE_PHRASES` is treated like 125 / 101
   by `_resolve_package_header_identity` (`pdf_service.py:14844-14850`) - on ACORD 27 (evidence of property) it
   could print the PACKAGE policy number. Generic forms need "blank unless one policy" here.
3. **Edits write back to the package.** `update_pdf` turns box edits into package facts through
   `_ACORD_FIELD_RULES` (`form_routes.py:2764-2790`): editing `NamedInsured_FullName_A` on a generic form would
   change `applicant_name` everywhere. Recommend: a generic form's edits stay on that form.
4. **A per-form score is still computed and shown** for any form (`process_single_form:2710`, `update_pdf:2994`,
   the cover page). Gate those three for generic forms (no score, "N boxes filled from your package").
5. **`_form_edition_identifier` globs `ACORD_1*.pdf`** (`pdf_service.py:2954-2977`) - ACORD 1 could stamp
   the 101's / 125's edition. Several regexes assume 2-3 digit form numbers (`needs_attention.py:2259,2262`,
   `sqs_service.py:11035,11055`, `cover_service.py:53`, `issue_registry.py:737,741`, `recognize.py:26`) -
   harmless, but ACORD 1 / 2 do not match them.

**Already fine:**
- **Pass 1** (`_ACORD_FIELD_RULES`, ~349 name rules, `pdf_service.py:1921`) is form-agnostic; the form-specific
  resolvers (`_resolve_page_one_receiving_carrier`, certificate rows, 186 starred questions, ...) are gated on
  their own form ids and stand down on a new one. The blank-forcing resolvers key on box names, so they protect
  new forms that reuse those e-labels.
- **Pass 1.5** (alias maps) loads at import and adds little for a new form (its bridge has ~45 entries, `_A` boxes
  only) - skip it; Pass 1 does the work. `scripts/generate_alias_maps.py` is build-time only.
- **No AI:** `map_facts_to_form(..., allow_llm=False)` (`pdf_service.py:36827-36867`). Gap fill has one entry,
  `form_service.shared_gap_fill` (`:2368-2524`): skip generic ids in its loop (`:2426`) and pass
  `allow_llm=False` in the per-form fallback (`:2656`).
- **The recommender never sees a new form** - `match_forms` ignores `all_forms` (`form_service.py:2337`). Owner
  rule kept with no work.
- Every per-form table (`_FORM_EVIDENCE_FACTS`, the per-form checklists in `sqs_service`, `question_classifier`,
  `policy_lines.SECTION_FORMS`, `field_qa`'s 140 gate, ...) is read with `.get` / `else`: skips harmlessly.
- **Editor, save, download, regenerate and the encrypted Primble record** need only `generated_forms[id]` and the
  template (`form_routes.get_form_fields` / `get_pdf` / `update_pdf`, `download_routes.py:412-606`,
  `primble_record.py:330`).
- **Frontend has no form catalogue** - labels come from the id (`frontend/src/utils/formInstances.js:29`); the only
  static list is marketing copy (`AboutPage.jsx:4-7`). Form selection is backend-driven
  (`AcordModal.jsx:3583, 5734, 9348-9384`).

**Size of the job:** a catalogue + template store, a generic-form door at selection and in the editor, the five
side effects above, gap fill skipped, the per-form score hidden, a search box. No change to Pass 1, the recommender,
the 17 forms or the package score.

### 8.5 ASG - what exists and what does not (from `ASG_DOCUMENTATION/`, re-read 3 Nov)
- **Download API** (template): `GET .../oauth/forms/download?formNumber=&edition=YYYY/MM` (or
  `latestEdition=true`) `&geoCode=XX&geoCodeSuffix=`, headers OAuth token + `x-api-key`,
  `Accept: application/pdf` (else base64). One call per form / edition / state. Proven 29 Oct.
- **Population API** (filled PDF): `POST .../oauth/forms/populate?inputFormat=ELABEL&outputFormat=PDF&forms=<n>`
  (+ `multiForm`, `latestEdition`, `geoCode`; a state form without a geoCode gets the state with the most
  recent edition). Usage per call. Fallback only (8.1).
- **There is NO list / catalogue endpoint** in the 11 documents or the 2 Postman collections. The docs link a
  help article, "Supported ACORD forms"
  (`support.acordsolutions.com/hc/en-us/articles/8040911707149-Supported-ACORD-forms`). Tried 3 Nov (public
  page, no API, no credits): Cloudflare challenge on the page, and the help centre's JSON API answers
  "Couldn't authenticate you" - **it needs the portal login.**
- **Usage:** the pilot counts one transaction per extractable PAGE. Whether a template download counts is not
  written anywhere - ask.
- **Contract:** the pilot PROHIBITS production use and customer access (`ASG_TRANSCRIBER.md` 7.7, clauses 2.2
  and 6.4). The ACORD forms warning in it makes Primble "solely responsible for using the CURRENT editions" -
  so templates come from the Download API and are refreshed, never an old copy kept silently.

### 8.6 Blockers and risks for Thu 5 Nov
1. **Contract (Brent).** A production right for primble.ai to call ASG for customers, plus PROD credentials;
   and the ACORD licence must cover storing templates and handing filled forms to users (end-user agencies may
   need their own ACORD licence - free for Big "I" / PIA members under $50M revenue; memory
   `asg-partnership-pilot`). Without it, "any form" can only run on localhost / UAT.
2. **Catalogue.** Search over 800+ forms needs the list (number, title, editions, state variants). No endpoint;
   the page needs a login. Guessing form numbers and probing the Download API would cost 1,000+ calls - no.
3. **The owner's per-call rule** for ASG (memory `transcriber-calls-need-permission`) against a library of
   ~800-1,500 downloads. Either the owner runs one download script himself, once (plus edition refreshes),
   or he allows lazy fetch: the first user to pick a form triggers ONE download, kept for everyone.
4. **Storage.** Render's disk resets on every deploy. Templates average ~210 KB (the kit's 15 = 3.2 MB), so
   ~170 MB for 800 forms, ~300 MB with editions and state variants. Options: the repo (`backend/templates/`,
   like the 17 - licence question, repo grows), Postgres (durable, but Supabase egress went over in Oct - so
   keep a local disk copy per server and read the database only on a miss), or object storage.
5. **Expectations.** Thin packages give thin forms (8.3). The message should be "any ACORD form, filled from
   your submission where the data exists - the rest you type in our editor".
6. **Editions and states.** A form has several editions and some have state variants; the catalogue lists each
   state variant as its own entry and a generated form keeps the edition it was made from.
7. **Forms with no fillable template.** Population fallback or "not available yet" - needs ASG's list.

### 8.7 Open questions
For **Brent**:
1. The production agreement with ASG and ACORD: may primble.ai call ASG (Download API) for customers? When do
   PROD credentials arrive? Can we read the agreement?
2. ACORD licence: may Primble store ACORD templates and give filled forms to users? Do users need their own
   ACORD licence?
3. Is "any form, filled where the submission has the data" the right promise for the pitches (8.3)?
4. Generic forms: no score, just "N boxes filled from your package" (section 6, Q2 - still open).
5. Switch ACORD 130 to the 2026/08 edition now (section 6, Q5 - still open)?
6. The five cross-form checks in section 5 (section 6, Q6 - still open).

For **ASG** (through Brent):
7. A machine-readable list of supported forms (number, title, editions, state codes) - or a list endpoint.
8. Do template downloads count against the transaction quota? Any rate limit?
9. Which forms have no fillable template, and does Population cover them?

For **the owner**:
10. Template library: run one download script yourself, once, or allow lazy fetch at runtime (one call per
    form, on first use only)?
11. Open "Supported ACORD forms" in the ASG portal (logged in) and save it (PDF or CSV) into
    `All-800PlusForms-Kit-by-Brent/`.

### 8.8 Proposed build, ordered for Thu 5 Nov (not started - waits for the owner's go)
1. **Catalogue**: a table (number, title, edition, state, line) seeded from ASG's list; a search endpoint.
2. **Template store**: download through ASG (owner-approved, 8.7 Q10), keep a durable copy + a local disk cache;
   read the schema off the template (the existing schema reader); refuse a template whose boxes are not
   e-labels (logged).
3. **Generic form path**: deterministic engine only (Pass 1 + 1.5 + guards), NO gap fill, NO per-form score
   or checks, behind one switch; the 17 forms untouched. Shape decided by 8.4.
4. **Search UI**: "Add any ACORD form" on form selection and in the editor's add-form window. The
   recommender stays exactly as it is (owner rule).
5. **Editor + download** for generic forms (existing viewer; the Primble record rides along).
6. **Measure** on 2-3 packages and send Brent the numbers.

Not in scope for 6 Nov: AI gap fill on generic forms, per-form scores or checks, AL3, e-mail integration, the
130 edition switch, the section 5 cross-form checks. (Revised by 8.9: the owner wants AI gap fill on generic
forms too, and search by number removes the catalogue from the Friday path.)

### 8.9 The owner's on-demand flow (3 Nov 2026, 03:30 IST) - analysis, no code
**Owner's proposal:** the user searches a form ("802"), it appears, he clicks; we pull the form from ASG at that
moment (no library of 800 stored), read its boxes, fill what our facts know, send the rest + the facts + the
declaration text to the AI exactly as today, stamp the answers, editor, download.

**Verdict: it works, and nearly all of it exists today.** Step by step:
1. **Search -> fetch.** Download API with `formNumber`, `latestEdition=true` and, for a state form, the package's
   state as `geoCode` (8.5). One call per click. Proven on ACORD 36 (29 Oct).
2. **Read the form.** Our schema reader takes every box's name, description (tooltip) and type off the template.
   ASG's templates use plain e-label names like our 17 (checked 3 Nov, 8.4). Nothing is OCR'd - a blank form's
   "text" is its box list.
3. **Fill what we know, no AI.** **There is nothing to map per form.** ACORD names every box from one shared
   dictionary (the e-label): `NamedInsured_FullName_A` is the insured's name on any form, exactly as on the 125.
   Our ~349 Pass 1 rules work by those names, so they fill a form they have never seen (measured, 8.3). The
   names ARE the map - that is what makes 800 forms possible without 800 mapping jobs.
4. **AI for the rest - same procedure as today.** The remaining boxes (name + ACORD's own description) + the
   facts + the document text go through the existing gap fill, then the post-fill guards that key on box
   names / types (the Y/N evidence gate, identifier and role guards) run as they do now.
5. **Stamp, editor, download** - unchanged (8.4 "Already fine").

**Two corrections to the proposal:**
- **"Do not store it" cannot be literal.** Every reopen, edit save, signature, regenerate and download rebuilds
  the PDF from the blank template. With no copy kept, each of those is a NEW ASG call (latency, usage), and when
  ASG is down a user cannot open his own form. Keep a copy of **only the forms users actually pick** (expect
  dozens, ~210 KB each - never the 800), and re-check the edition on a schedule (the ACORD licence requires
  current editions). The catalogue LIST (a few hundred KB of text) is not the forms and is fine to keep.
- **"Map it quickly" is not needed** (point 3).

**Search without ASG's list (the Friday answer to the catalogue blocker):** search by NUMBER needs no list - the
user types 802, we ask ASG for that number; it returns the form (whose printed title we read and show) or "not
found". Brokers know form numbers. Search by NAME ("garage", "binder") needs ASG's supported-forms list (8.7 Q7) -
add it when it arrives. The 17 + the kit's 15 can be searched by name from day one (titles known).

**What Brent means by the six base forms (plain words):** ACORD built all its forms from one shared dictionary
of data items. The six - 125 (applicant, producer, locations, prior carriers, losses), 126 (GL), 127 (vehicles,
drivers), 130 (WC payroll, classes, officers), 131 (umbrella / underlying), 140 (property / COPE) - together ask
for almost every item a commercial submission has. Every other ACORD form (certificates 25 / 27 / 28, binder 75,
ID card 50, cancellation 35, state supplements, ...) re-asks a SUBSET of those same items plus a few of its own.
So: make the six right and deep (his readiness PDF is the definition of "right"), and every other form fills from
the same data by e-label. **He is not saying "support only six"; he is saying "put the quality work into these
six - the other 800 ride on them."** His "missing 10-30%" = the items unique to the other form (a binder number,
a claim description), which nothing in a submission holds. In Primble the base is really our FACTS: the six forms
define which facts must be right, and every form - the 17 or a new one - is stamped from those facts.

**Risks of the on-demand flow:**
1. **AI on forms nobody has tested.** The generic guards apply; the per-form guards built for the 17 do not.
   Recommend: AI fill on generic forms behind a switch, its values labelled "Please verify", tried on the kit's 9
   extra forms before it goes to customers.
2. **Cost and time per form.** Unmatched boxes go to the AI; a big form (ACORD 80: 821 boxes) means more calls
   and minutes. Brent does not need the 10-30%, so the switch can stay off where it is not worth it.
3. **State forms** need the state (taken from the package; the user can change it).
4. **Forms with no fillable version** - ASG says "no acroform"; show "not available yet" (or Population later).
5. **Every click is a live ASG call** - needs production terms (the pilot forbids it) and, from the owner, a
   standing yes for this one endpoint in production instead of the per-call rule.
6. The four blockers and five side effects in 8.4 still apply (edits on a generic form must not rewrite the
   package's facts; no per-form score; the header policy number on single-line forms).

**Decisions waiting for the owner:**
1. Keep a copy of each form the first time a user picks it (recommended) - or truly re-fetch every time?
2. AI gap fill on generic forms: on, off, or on behind a switch (recommended: switch, start on for the kit's 9 in
   testing)?
3. Friday search = by form number (recommended), name search when ASG's list arrives?

### 8.10 Owner's rules, 3 Nov 2026 03:40 IST - never store ASG forms; treat them exactly like ours
**Owner (decisions, supersede 8.9 decisions 1 and 2):**
- **ASG forms are NEVER stored in Primble** - no PDF, no schema, no box list, unlike our 17. "We have to depend on
  ASG's integration totally." Every time a form is needed it comes from ASG.
- **Treat them like our own forms in every way**: AI fill, hard stops, empty / missing values, Please verify -
  "every single thing should be same; just the forms are getting by ASG".
- How users search is decided later; first prove the integration.

**Does ASG provide the integration? Yes - and we already have it (evidence):**
1. **The service:** `ASG_DOCUMENTATION/Download-HomePage.pdf` - "The Forms download API ... returns a PDF based on
   the parameters Form Number, Geocode, Geocode suffix and Edition." Any form number; latest or a named edition;
   state forms by geoCode.
2. **The key:** `backend/.env` holds the UAT credential set it needs - `TRANSCRIBER_CLIENT_ID`,
   `TRANSCRIBER_CLIENT_SECRET` (-> OAuth token from `nonprod-token-transcriber.acordsolutions.net`) and
   `TRANSCRIBER_API_KEY` (the `x-api-key` header). `TRANSCRIBER_ENV=uat`. Production needs PROD credentials.
3. **It worked:** 29 Oct, one call with the owner's yes - `GET uat-api-v1-transcriber.acordsolutions.net/oauth/
   forms/download?formNumber=36&latestEdition=true` -> 200, ACORD 36 (2007/01), fillable, 63 boxes with plain
   e-label names (`asg_dec_test_data/transcriber_probe/ACORD_36_template_from_asg.pdf`; `ASG_TRANSCRIBER.md` 8).
4. **Our client already speaks it:** `services/asg_transcriber.TranscriberClient` (`token()`, `_headers()`) - the
   same token + key the Download API takes. No new contract or code from ASG is needed.

**Not proven yet:** any form number other than 36 (one call so far); the PROD host with PROD credentials; whether
downloads count against the transaction quota; rate limits; production / customer use (the pilot forbids it).

**Proof-of-concept script (outside the repo, not run - the owner runs ASG calls himself):**
`/private/tmp/claude-501/-Users-vinaysharma-Downloads-Primble-16thsep/427f82bb-424b-4678-bf06-9112a9013561/scratchpad/anyform/asg_form_poc.py`.
For each form number: ASG token -> Download API -> the form held IN MEMORY only -> reads its boxes -> fills it
with Primble's engine from the Orbin test package (a fixture, no database, no AI) -> prints what filled. `--save`
writes only the FILLED form for viewing (the blank one is never kept). Cost: 1 token + 1 download per form.

**What "never store" means for the design:**
- **We store answers, never forms.** The package keeps the box values (the user's data, as today) and the form
  number + EDITION it was made from. Every generate / open / edit save / sign / download fetches that exact
  edition from ASG (`edition=YYYY/MM`, not "latest" - a newer edition can rename boxes and the answers would land
  in the wrong place) and reads the boxes again (milliseconds).
- **Cost:** about 5-20 ASG downloads per form per package (every open and download). Only acceptable if downloads
  are not metered like extractions - ask ASG.
- **ASG down = the user cannot open or download that form** (his answers are safe). An in-memory copy for a few
  minutes inside one server (gone on restart, never on disk) would cut the repeat calls - the owner's call
  whether that counts as storing.
- **"Same as our forms" - what transfers automatically and what does not:**
  - Same with no work: AI gap fill (every box's ACORD description is in the form itself), the post-fill guards
    that key on box names and types (Y/N evidence gate, identifier and role guards), Please verify labels,
    Missing / empty-box rows, Field QA, the editor, signatures, download, the encrypted Primble record, every
    PACKAGE hard stop and warning.
  - Not automatic: the hard stops, warnings and checklists written BY HAND for each of the 17 (for example the
    140's COPE gate, the 131's underlying-limits stop). A new form gets the generic checks only, unless someone
    writes its own. Same for its per-form score (the scorer has a generic branch).
- **More from the owner / ASG that would help:** the PROD credentials and the production agreement; the
  portal's "Supported ACORD forms" list; whether the portal has a forms library / search page (if it does, an
  API behind it lists the forms - ask ASG for that list endpoint); ASG's word on download quota and rate limits.

### 8.11 The ASG documents added on 3 Nov 2026 (read 11:05-11:20 IST)
Six new files in `ASG_DOCUMENTATION/`:

| File | What it says | What it means for us |
|---|---|---|
| `SUPPORTED-ACORD-FORMS-ASG.pdf` (253 pages) | The full list of forms and editions Transcriber supports "for Extraction and Population": form name, edition, title, page count | **The catalogue we lacked.** Parsed: **316 form numbers, 1,199 entries counting state versions (934 of them state / variant forms such as `137_CA`, `130_FL_IS`), 3,881 form + edition rows.** All our 17 are in it. Its newest editions are 2026/03 - but for some core forms it stops early: 25 at 2016/03 (ACORD has 2025/12), 130 at 2017/09 (ACORD has 2026/01 and 2026/08). So it is the EXTRACTION / POPULATION list, not necessarily everything the Download API serves. |
| `AcordForms-homePage.pdf` | ASG's "ACORD Forms" (= Forms Download) feature: search by form number, title, business domain (Life, Health, Annuity, P&C, Surety), broad line, line, state; "All versions/revisions of ACORD Forms are supported"; PDF output only; a specific edition can be downloaded; custom forms too once mapped in the Training Tool; a "Download Postman Collection" button on the portal's Forms Download tab | Confirms the Download API serves ANY form and ANY edition. The portal SEARCHES ASG's own catalogue - so ASG has a search service behind its portal that is not in our API docs. |
| `Transcriber-Dashboard .pdf` (screenshots) | (1) WebForms tab "Webform Client App": form number, edition, geo code, prefilled form data (JSON / XML), load form - ASG's own form-filling screen. (2) Forms Download tab (`uat-transcriber.acordsolutions.net/transcriber/#/home/forms-download`): columns Form Number, Form Title, Form Edition, Geo Code, Geo Code Suffix, PDF; **"Showing 1-10 of 4164"**; tooltip "This utility will always download latest version (ASG recommended)..." | **4,164 downloadable versions** - more than the 3,881 rows of the supported list. The "Download Postman Collection" button on that tab is the fastest way to see the exact requests the portal uses, possibly including the search. |
| `Error-Handeling.pdf` | Error replies for all services. Download, invalid form: `{"code": "Invalid Form", "message": "This form has no acroform PDF for download."}`. Population, invalid form: "The requested form is not available, form number=77, geo code=null". Missing key: 403 "Forbidden" | The exact messages our "form not available" path must recognise. |
| `1-ACORD CONVERTOR.pdf` | Marketing for ASG Converter: maps data between AL3, XML, JSON, eLabel, EDIFACT; works with Transcriber for "extraction, data transformation, and population, such as generating certificates" | Not needed for forms. Relevant later for AL3 export and data exchange. |
| `2-Client onboarding questionnaire - ACORD Converter.xlsx` | Converter onboarding: organisation, users, **IP whitelisting ("IP addresses / range of IP addresses*")** | Converter only - but it shows ASG whitelists caller IPs. If PROD Transcriber does too, Render's outbound IPs must be registered (Render publishes fixed outbound IP ranges per region). |

**Two observations that matter:**
1. **"800+ forms" in numbers:** 316 form numbers; 1,199 counting state versions; 3,881 editions in the
   supported list; 4,164 downloadable versions in the portal. Primble's search should show one row per form +
   state (latest edition), filtered to P&C (the portal's Business Domain filter shows Life / Health / Annuity /
   Surety forms are in the library too).
2. **Edition currency:** the supported list lags ACORD on some core forms (25, 130). Before we promise "latest
   edition", one PoC call (`formNumber=130&latestEdition=true`) shows which 130 edition the Download API serves.

### 8.12 THE PLAN - "any ACORD form" through ASG, step by step (3 Nov 2026, 11:20 IST; not started)
**Updated 3 Nov 11:40 IST by 8.13-8.14:** step 0.1 DONE (PoC passed); step 0.2 DONE (no search API exists -
the text list is the search); the RAM copy (0.3b) is DROPPED - ONE ASG download per form per package at
generation, then the FILLED copy is stored per package (`session_pdf_bytes`) and Step 3's "where the PDF comes
from" door reads that stored copy for every later open / edit / sign / download (re-stamping writes EVERY box,
blanks included, onto the stored copy; a signature is painted on a fresh re-stamp, never on top of an old one);
Step 7 = a search bar on top of the form selection screen + a side notice, recommended forms unchanged; plus a
setting for the per-user cap on ASG forms (number from the owner / Brent) and a "Getting ACORD N from ACORD
Solutions..." progress message. Still open: PROD credentials, the standing yes for production downloads.

**Shape in one line:** the user searches ASG's catalogue -> picks a form -> Primble downloads that form + edition
from ASG at that moment, reads its boxes in memory, fills it with the SAME pipeline as our 17 (rules, AI gap fill,
guards, checks) -> editor, sign, download - every one of which fetches the form from ASG again. **Primble stores
the ANSWERS and the form's number / edition / state, never the form.**

**Step 0 - inputs from the owner (before any code):**
1. **Run the PoC** (`scratchpad/anyform/asg_form_poc.py`, 8.10) - or say "yes, run it" - on: `27 75 80` (plain
   forms), `137 --state CA` (state form), `130` (which edition is "latest"?), `130 --edition 2017/09` (a named
   edition), and one number that should fail. Proves: any number, state, edition, the error shape, real timing.
   About 1 token + 6 downloads.
2. **Click "Download Postman Collection" on the portal's Forms Download tab** and save it into
   `ASG_DOCUMENTATION/`. If it holds the search request, Primble searches ASG live and stores nothing at all.
3. **Decisions** (recommendations first):
   a. Catalogue: **live ASG search if (2) has it; otherwise keep a text index** (form number, title, edition,
      state - from the supported list / portal) - metadata, not forms. Is a text index acceptable under "never
      store"?
   b. **A short in-memory copy** (RAM only, minutes, gone on restart, never on disk or in the database) so one
      editor session does not call ASG on every click - acceptable?
   c. **Our 17 stay ours** (their own templates and per-form rules) even when a user finds them in ASG search -
      yes?
   d. **P&C forms only** in Primble's search - yes?
   e. **A standing yes for the Download API in production** (the per-call rule cannot hold for customer clicks).
4. **PROD credentials** (client id, secret, API key) - into Render only (`TRANSCRIBER_ENV=prod`), never in chat.
5. **Ask ASG (through Brent):** do downloads count against the transaction quota; any rate limit; do they
   whitelist caller IPs in PROD (Render's outbound ranges); is there a documented search / list API.

**Step 1 - the ASG form door (backend, one module).** `fetch_form(number, edition, state)` -> PDF bytes: OAuth
token + `x-api-key` (the existing `TranscriberClient`), `GET /oauth/forms/download`, retries on 429 / 5xx with the
existing backoff and circuit breaker, "Invalid Form" -> a clean "not available from ASG" answer, the optional RAM
copy (3b). Log form / edition / timing only. Tests on a stub, never the network (like the Transcriber tests).

**Step 2 - read the form in memory.** Box name, ACORD's description, type and page order straight from the bytes
(the existing `_collect_fields_pikepdf` logic, without the write into `forms_schemas/` - side effect 1 in 8.4).
Refuse a form with no fillable boxes (never cache an empty schema).

**Step 3 - one "where does this form's PDF come from" door.** Today every reader opens
`templates/<file>.pdf` from disk (generate, `get_pdf`, `update_pdf`, regenerate, signatures, download, the
Primble record). One function returns the bytes: from disk for our 17, from Step 1 for an ASG form;
`fill_pdf` takes bytes. Everything downstream stays as it is.

**Step 4 - an ASG form is a form in the package.** Id `ASG_<number>[_<state>]`; its record on the package keeps
`source: asg`, number, EDITION, state, title. Fix the four blockers in 8.4: selection reads the catalogue, not the
upload-time snapshot; add-a-form after generation accepts an ASG pick; the record carries `form_name`; the 0%
"Add more ACORD forms" list is not built from 800+ forms.

**Step 5 - fill exactly like ours (owner's rule).** Pass 1 rules (by e-label) -> the shared AI gap fill, which
includes ASG forms (their boxes + ACORD's descriptions + the facts + the document text - the same prompt) -> every
post-fill guard -> Please verify / Missing rows -> Field QA. Side effects from 8.4: the header policy number on
one-policy forms, the edition-box glob for ACORD 1 / 2. Edits write back to the package like our forms do (same
e-label = same fact). Measure AI cost on a big form (ACORD 80, 821 boxes) before customers.

**Step 6 - checks and score, like ours.** Every package hard stop / warning applies; the generic per-form checks
(missing boxes, Y/N evidence, identifier formats) apply; the per-form score uses the scorer's generic branch.
The hand-written checks of the 17 do not exist for an ASG form - written per form later if Brent asks.

**Step 7 - search + pick (frontend).** "Add any ACORD form" on form selection and in the editor: type a number or
words, see title / edition / state, pick. The recommender's own suggestions stay exactly as they are.

**Step 8 - editor, sign, download.** Unchanged screens; their PDF comes through Step 3. If ASG is down: "This form
is temporarily unavailable from ACORD Solutions - your answers are saved" and a retry - never a blank form.

**Step 9 - test before customers.**
1. Offline suite on the stub (no network), plus the full suite.
2. Localhost with UAT: the kit's 9 extra forms + a state form on the Orbin and Choice Electric packages - fill
   counts, AI cost, time per form, an edit, a signature, a download, re-open after a server restart.
3. Render with PROD credentials, behind a switch (`ASG_FORMS=1`), owner first, then Brent.

**Rough time:** steps 1-4 one day, steps 5-8 one day, step 9 half a day - if step 0 is done first.
**Risks named:** ASG down = the form cannot open (answers safe); per-download usage if metered; AI fill on forms
nobody has tested (generic guards only); the supported list lagging ACORD's editions; IP whitelisting on PROD.


### 8.13 Proof of concept RUN - 3 Nov 2026, 11:35 IST (owner's yes, cap 7 ASG calls, 7 used)
Script: `scratchpad/anyform/asg_form_poc.py` (outside the repo; hard cap of 7 calls built in). UAT credentials
from `backend/.env`. The owner's list plus the token was 8 calls, so ACORD 80 (homeowner, personal lines) was
dropped. Each form: downloaded, read in memory, filled from the Orbin test package with NO AI, the blank copy
deleted; only the filled test copy written to the scratchpad for viewing.

| Call | Request | Result | Time |
|---|---|---|---|
| 1 | OAuth token | OK | 2.8 s |
| 2 | ACORD 27, latest | 200, ACORD 27 (2016/03), 1 page, 89 boxes, **89 of 89 with ACORD's description**; Primble filled 12 | **22.5 s** (first call, cold) |
| 3 | ACORD 75, latest | 200, ACORD 75 (2016/03), 2 pages, 147 boxes (147 described); filled 31 | 4.7 s |
| 4 | ACORD 137, state CA, latest | 200, ACORD 137 CA (2023/01), 3 pages, 403 boxes (403 described); filled 13 | 10.0 s |
| 5 | ACORD 130, latest | 200, **ACORD 130 (2026/08)**, 5 pages, 481 boxes (481 described); filled 34 | 4.6 s |
| 6 | ACORD 130, edition 2017/09 | 200, ACORD 130 (2017/09), 4 pages, 478 boxes (478 described); filled 34 | 4.3 s |
| 7 | ACORD 9999 (does not exist) | **HTTP 400** `{"code":"Invalid Form","message":"This form has no acroform PDF for download."}` | 1.4 s |

**Proven:** any form number; state forms (`geoCode`); a named edition; latest edition; the exact error for a form
that does not exist; every box arrives with its key (e-label), type and ACORD's description; Primble's engine fills
a form it has never seen without a code change. **Timing:** 4-10 s per form, 22 s on a cold first call - a
"fetching" message is required. The UAT credentials we already have serve downloads.

**Two findings:**
1. **The Download API serves NEWER editions than ASG's supported list.** The list stops the 130 at 2017/09; the
   download's "latest" was **2026/08**. So the list is good for SEARCH (number, state, title) but never for
   editions - always ask ASG for `latestEdition=true` and store the edition it returns.
2. **Our own ACORD 130 template (2026/01) is one edition behind ASG's latest (2026/08).** The ACORD forms warning
   makes Primble responsible for current editions. Separate small job (8.2 lists the box differences).

### 8.14 Owner's decisions, 3 Nov 2026 11:30 IST (supersede 8.10 / 8.12 where they differ)
1. **Search list: YES** - keep a text list (form number, state, title) for search. ASG has no search API (owner
   checked the dashboard; the support page's Postman collections are only Extraction and Population - the two we
   already have).
2. **Where search lives:** the form selection screen keeps showing ONLY the recommended forms, as today. A search
   bar at the top, and a friendly side notice telling the user he can search any ACORD form by name or number;
   matching forms appear as options; he ticks them and generates together with the recommended ones, in the same way.
3. **Storage:** the BLANK form is never stored (unlike our 17 templates). Primble calls ASG at generation, gets the
   form and its box details, fills it - and the FILLED copy is stored per package in the database, exactly like
   every other generated form today. Opening, editing, signing and downloading later use that stored filled copy.
   (Primble already keeps each generated form's PDF in `session_pdf_bytes`, one row per package per form.)
   **This replaces the RAM-copy idea: ONE ASG download per form per package, at generation.**
4. **Our 17 stay ours** even when found through the search.
5. **Limit:** a cap on how many ASG forms a user can add / generate (misuse and ASG usage) - the number comes from
   the owner after he talks to Brent; build it as a setting.
6. **Speed / feedback:** fast, with a spinner and a clear message while forms are fetched.
7. **Credentials:** the UAT set in `.env` already serves downloads (proven, 8.13). Production needs ASG's PROD set
   (8.15 Q-cred).
8. AI fill: yes, exactly like our forms (8.10).

### 8.15 Answers to the owner's questions (3 Nov 2026)
- **How many forms does ASG support?** In ASG's own list: **316 form numbers; 1,199 counting state versions as
  separate forms; 780 of those have an edition from 2010 or later (current forms); 3,881 form + edition rows.**
  The portal shows **4,164** downloadable versions. So "800+ forms" = the ~780 current forms counted with their
  state versions; ASG's marketing "4,700+ versions of 800+ forms" counts editions. The list says nothing about
  "100+".
- **"P&C only" (8.12 decision d) explained:** ASG's library is not only business insurance - the portal filter
  shows Life, Health, Annuity, P&C (property and casualty = business / personal insurance like GL, auto,
  property, WC, umbrella) and Surety forms. Primble is a commercial P&C product, so life / health / annuity forms in
  the search would be noise. The supported list has no domain column; until ASG gives one, search shows every form
  and ranks the P&C ones (by line words in the title) first.
- **"Standing yes" (8.12 decision e) explained:** this is about MY rule, not ASG's. The owner told me never to call
  ASG without his yes for each call. In production, the SERVER calls ASG every time a user generates an ASG form -
  nobody can ask the owner first. So the rule must become: "the server may call the Download API for users in
  production" (with the per-user limit, decision 5). The rule stays for anything I run by hand.
- **Credentials:** the three in `.env` (client id, client secret, API key) are ASG's **UAT** (test) set - they work
  for downloads (8.13). ASG issues one set per environment, so primble.ai needs the **PROD** set, from ASG's
  production onboarding (Brent / ASG support). They go into Render only (`TRANSCRIBER_ENV=prod`,
  `TRANSCRIBER_CLIENT_ID`, `TRANSCRIBER_CLIENT_SECRET`, `TRANSCRIBER_API_KEY`). Primble refuses UAT keys in
  production unless `TRANSCRIBER_ALLOW_UAT_IN_PROD=1` - a stop-gap only.
- **Why IP whitelisting was asked:** the pilot agreement (`ASG_TRANSCRIBER.md` 7.7) says "ASG may limit access to
  white-listed IP addresses", and the Converter onboarding sheet asks for IPs. Every call so far came from the
  owner's Mac to UAT. PROD calls will come from Render. If PROD whitelists, the first Render call fails with 403
  and we register Render's outbound IPs then. Not a blocker; nothing to do now.
- **Search API:** none (owner confirmed). The text list (decision 1) is the search.

**The six base forms, in plain words.** The six (125 application, 126 GL, 127 auto, 130 WC, 131 umbrella, 140
property) are ACORD's MASTER application: between them they ask every question a carrier asks about a business.
Almost every other ACORD form is a SLIP that copies parts of it: a certificate (25) copies the insured, the
policies and the limits; a binder (75) the insured, policy and premium; an ID card (50) the insured and the
vehicle; a state supplement a few state questions. ACORD gives the same question the same box name on every form,
so whatever Primble knows for the six lands on every slip automatically (8.13: 12-34 boxes on forms the engine had
never seen). That is what Brent means: **make the six excellent, and the 800 come free.**
- **Do we need to work on the six now?** No, not for Friday. All six are already among our 17, with months of
  rules behind them. Brent's readiness PDF (section 4) shows most items "Have"; what is left is depth: the five
  cross-form consistency checks (section 5), a few "Check" items, and the 130 edition update (8.13). Every
  improvement to the six later lifts every ASG form at the same time. Order: **ASG forms first (breadth, Friday),
  the six's depth items after.**

**What happens in the background when a user picks "190 TX" (example; ASG lists 190 as "Supplemental Property
Application", 2013/09):**
1. Search: the text list matches "190" -> shows number, state, title. No ASG call.
2. The user ticks it and clicks Generate -> spinner: "Getting ACORD 190 from ACORD Solutions...".
3. Server: ASG token (kept about 1 hour), then `GET /oauth/forms/download?formNumber=190&geoCode=TX&
   latestEdition=true` -> the blank fillable PDF in memory (4-10 s).
4. Server reads every box out of that PDF, in memory: **the key** (e-label, e.g. `NamedInsured_FullName_A` - the
   SAME keys our 17 forms' schemas use), **the type** (text or tick box), **ACORD's description** ("Enter text: The
   full name of the named insured..." - the exact text our AI prompt sends), the page, and the tick-box options.
   Proven on 6 forms today: 100% of boxes carry all of it. **This is exactly what `forms_schemas/<form>_schema.json`
   holds for our 17 - those files were made by reading the template PDF in this same way.** So yes: everything the
   AI call needs comes from ASG's PDF.
5. Fill: Primble's rules fill the keys they know (insured, producer, policy, dates...) -> the AI gets the
   remaining keys + their descriptions + the package's facts + the document text -> answers -> the guards check
   them -> stamped onto the PDF.
6. The FILLED PDF is stored for the package (`session_pdf_bytes`) with the form's number, state and edition;
   the values like every form. The blank copy is dropped.
7. Editor, edits, signature, download: from the stored filled copy - no more ASG calls.

**What ASG does NOT give (and what that means):** the hand-written per-form rules we built for the 17 (special
checks and fill rules) - an ASG form gets the general ones only; the alias map (not needed - our rules work by key);
our form metadata file (title comes from the search list); "required" flags (ACORD's PDFs do not mark them; ours
are mostly unset too).


### 8.16 Owner's review of the PoC + decisions, 3 Nov 2026 11:58 IST
**1. "Sample" watermark on ASG's forms (owner opened `ACORD_130_2017-09_filled.pdf`).** Checked offline (no ASG
call): every ASG download - all five today AND the 29 Oct ACORD 36 - carries an extra picture on the page (`/Im2`)
that our own templates do not have; it is not a watermark annotation or a layer, and Primble's fill adds nothing.
So **ASG puts it there, almost certainly because these are UAT (test) credentials.** We must NOT strip it ourselves
(it is ASG's licensed output). Customers must get clean forms -> **PROD credentials are needed for real forms**, and
the first PROD download must be checked for the watermark. Question for Brent / ASG: "Do PROD downloads come
without the 'Sample' watermark?"

**2. Search list must not be static (owner).** ASG can add forms, rename titles and publish editions at any time;
calling ASG on every search costs calls. Design:
- **Editions never come from the list** - generation always asks ASG for `latestEdition=true` and stores the edition
  it returns (8.13). A newer edition changes nothing in the list.
- **Titles in the list are display only** - the real title is read off the PDF at generation.
- **New forms:** (a) the list is refreshed from ASG's supported-forms list on a schedule (owner re-saves the PDF
  from the portal, or ASG sends it as a spreadsheet - Brent question); (b) a number the list does not have can
  still be tried: "Not in our list yet - check ACORD Solutions" -> ONE ASG call, only when the user asks; ASG's
  "Invalid Form" reply answers it; (c) ask ASG for the list API their own portal uses (its Forms Download tab
  searches 4,164 versions, so one exists behind it) - then search is live and nothing is kept.
- Typing in the search box never calls ASG.

**3. Search UI (owner).** On the form selection screen: while the user is searching, ONLY the matching forms show,
in the SAME card format as the recommended forms; he ticks the ones he wants and presses a **Done** button next to
the search; the search clears, the normal sections come back (recommended, required, etc., same order), and the
picked forms appear at the BOTTOM of the visible list (not in the hidden drop-down) under their own heading - e.g.
"Additional ACORD forms" / "Forms you added". Then Generate as usual. A friendly notice tells the user he can
search any ACORD form by name or number.

**4. "ASG sends only the blank PDF" - is that enough, or ask ASG for the mapping?** The Download API returns only
the PDF - but the PDF itself carries the mapping: every box's key (e-label), type and ACORD's description, on 100%
of the boxes of all six forms tested. That is the same information as ASG's "Mapping List" files (in Brent's kit)
and as our 17 forms' schema files. Asking ASG for a separate mapping API would add a call per form and give nothing
new. Asking ASG to FILL the form (their Population API) would skip our rules, AI, checks and editor. **Verdict: not
needed.** Worth asking ASG only for the forms LIST (point 2c) and the form's line-of-business / domain (point 7).

**5. Fill order - confirmed, the same as our 17 forms:** every pre-form screen answer (stored as facts with the
person's label), the extracted facts and flags -> stamped first by our rules and resolvers that work by box key ->
the shared AI gap fill gets the boxes still empty (their descriptions + the facts + the document text) -> the
post-fill guards -> stamped -> Please verify / Missing rows -> score and checks.

**6. Where the filled copy lives (owner asked to confirm).** In THAT user's package only: the values in the
package's row and the filled PDF in `session_pdf_bytes` (rows keyed by that package's id). Primble has ONE
database for all packages - there is no separate database per user - but the filled form belongs to the
package: only its owner can open it (every route checks the package's user), it never enters Primble's form
library (`templates/`, `forms_schemas/` in the code, where our 17 live), and it is deleted with the package
(retention) like every other generated form.

**7. P&C only** - for now search shows every form with business-insurance (P&C) forms ranked first. **Brent
question:** show only P&C forms, or Surety too, or everything (Life / Health / Annuity)?

**8. ASG calls - the rule (owner, 11:58 IST):** the SERVER may call ASG for real users in production (generation
of an ASG form, the "check ACORD Solutions" button). **Claude may NOT call ASG without the owner's yes for each
test**, ever (memory `transcriber-calls-need-permission`).

**9. Credentials on Render (owner listed them):** `TRANSCRIBER=1`, `TRANSCRIBER_ALLOW_UAT_IN_PROD=1`,
`TRANSCRIBER_API_KEY`, `TRANSCRIBER_CLIENT_ID`, `TRANSCRIBER_CLIENT_SECRET`, `TRANSCRIBER_ENV=uat`,
`TRANSCRIBER_TOKEN_URL`. **For downloads these are enough technically** - the Download API uses the same token +
API key as the Transcriber extraction (proven today with the same set). Nothing else is needed to make it work.
**But they are the UAT (test) set**, which is why the forms carry "Sample" (point 1), and UAT is ASG's test
environment. For customers: ASG's PROD set, then on Render `TRANSCRIBER_ENV=prod`, the three PROD keys,
`TRANSCRIBER_TOKEN_URL` = the prod token URL (or removed - the code defaults to it), and
`TRANSCRIBER_ALLOW_UAT_IN_PROD` removed. The feature will add two settings of our own when built: a switch
(e.g. `ASG_FORMS=1`) and the cap (`ASG_FORMS_MAX=8`).

**10. IP whitelisting:** Brent gave ASG India and the USA at sign-up - covers the Mac and Render (US). Settled.

**11. Cap: 8 ASG forms per package for now** (setting). Brent question: is 8 right, per package or per user /
month?

**Questions for Brent (collected):**
1. Do PROD downloads come WITHOUT the "Sample" watermark (confirmed on every UAT download, 8.17), or must ASG
   enable licensed downloads for our organisation - which `orgId` do we send? When do we get the PROD credentials?
2. Search scope: P&C only, P&C + Surety, or every domain?
3. The cap: 8 ASG forms per package - right number? Per package or per user per month? Do downloads count against
   our ASG usage?
4. Can ASG give us the forms list as a spreadsheet (with domain and line of business), or the list API their portal
   uses, so search stays current without us re-saving the PDF?
5. Our own ACORD 130 is 2026/01; ASG serves 2026/08 - switch now? (also section 6, Q5)


### 8.17 The "Sample" watermark - confirmed, 3 Nov 2026 12:05 IST (offline, no ASG call)
- **Confirmed:** the extra picture on ASG's pages (`/Im2`, 1108 x 775, colour with a transparent background) IS the
  word "Sample", drawn over the whole page by the page's own drawing instructions. It is on **every** ASG download
  (ACORD 27, 75, 137 CA, 130 2026/08, 130 2017/09 today; ACORD 36 on 29 Oct).
- **Not on any form from ACORD itself:** Brent's kit (`Acroform.pdf` and `AdobeFillable.pdf` of 1, 125, 126, 127,
  130 2026/08, 131) and our 17 templates carry only the ACORD logo picture. So ASG adds it.
- **No ASG document mentions a watermark, "sample" mode or licence switch.** The only related knobs: the Download
  API's optional `orgId` ("Org ID if applicable - Organisation name") and `userId`; the WebForms component's
  `orgName`. We have never sent `orgId` / `userId`.
- **Likely causes (unproven):** (a) UAT is ASG's test environment and stamps every download; (b) ASG stamps
  downloads for an organisation whose ACORD forms licence it does not see (we send no `orgId`); (c) the pilot
  account itself.
- **We do NOT remove it ourselves** (owner rule: gather the correct forms; it is ASG's licensed output).

**Ways to get clean forms WITHOUT asking Brent - each needs the owner's yes before any call:**
1. **Owner, no API call:** download the same form (e.g. ACORD 27) from the portal's Forms Download tab while logged
   in, and drop the file into the scratchpad. Clean = the API needs a parameter the portal sends (test 2);
   watermarked = the account / environment does it.
2. **API, 2 calls (token + download):** ACORD 27 with `orgId=<our organisation name as on the ASG portal>` and
   `userId=<the portal login e-mail>`. Clean = we send these on every download; done.
3. **API, 1 more call:** Population (`/oauth/forms/populate?inputFormat=ELABEL&outputFormat=PDF&forms=27`) with a
   one-box e-label payload - shows whether ASG's filled output is also stamped. (May count as a population
   transaction.)
4. If all show "Sample": only PROD credentials (or ASG enabling clean downloads on our account) can fix it ->
   Brent / ASG.

**Question for Brent (logged, 8.16 Q1 sharpened):** "Every form ASG's Download API gives us on our UAT credentials
carries a 'Sample' watermark across the page. Forms from ACORD directly (your kit) do not. Do PROD credentials give
clean forms, or does ASG need to enable licensed (watermark-free) downloads for Primble's organisation - and what
organisation ID should we send?"

**Ready to implement?** Yes for BUILDING: every piece is proven (any form, state, edition, error reply, keys and
descriptions for the AI, our engine fills it) and every owner decision is made (8.14, 8.16). The watermark blocks
only the CUSTOMER launch - the code is the same with clean or stamped forms (the credentials decide). Needs: the
owner's "go" to code; Brent's answers can arrive while we build (cap number, search scope, PROD credentials).


### 8.18 Watermark: organisation ID or UAT? (3 Nov 2026, 12:13 IST, offline)
- **New file** `ASG_DOCUMENTATION/transcriber.forms-download.postman_collection.json` (the portal's Forms Download
  "Download Postman Collection" button): ONE request - the download we already use, on the AWS-signature host
  (`/v2/forms/download?formNumber=&edition=`), headers `x-api-key` + `Accept: application/pdf`, no values filled
  in. **No search request, no `orgId`, nothing about watermarks.**
- **What `orgId` is for, by the docs:** it sits beside custom-form features - the Download page's "Custom forms ...
  mapped with eLabels using Training Tool ... can be downloaded", and Extraction's `formSource` ("Used only for
  Organization Name") with `customForm=true`. It picks an ORGANISATION'S OWN custom forms; nothing ties it to
  licensing or watermarks. **So `orgId` is unlikely to be the cause.**
- **Most likely cause: UAT.** UAT is ASG's test environment (and the pilot agreement forbids production use on
  it); a "Sample" stamp on everything served there fits. A web search found nothing public either way.
- **The owner's screenshot:** the portal's "Business Domains" filter offers Annuity, Health, Life, P&C, Surety - ASG
  HAS each form's domain (Brent question 4: ask for it in the forms list). Typing 27 in Form Number matches 27 AND
  127 (43 rows) - the portal searches by "contains".

**How to settle it without an API call (owner, in the portal):**
1. In the UAT portal's ACORD Forms tab (your screenshot), click the red PDF icon on the row "27 - Evidence of Property
   Insurance - 2016/03" and put the file in `ASG_DOCUMENTATION/`. Stamped too = the account / UAT does it, not our
   API call.
2. Open the menu under your name (top right) - note the organisation name and any plan / environment shown
   ("pilot", "trial", "UAT").
3. Try logging into the PRODUCTION portal, `https://transcriber.acordsolutions.net` (no "uat-"), with the same
   login. If it lets you in, download the same ACORD 27 there: clean = PROD credentials fix it.
4. Optional, for Brent question 2: pick Business Domain "P&C" with no other filter and note "Showing 1-10 of N".
If all portal downloads are stamped: Brent / ASG (8.16 Q1).


### 8.19 Watermark SETTLED: it is our UAT account, not our API call (3 Nov 2026, 12:20 IST)
Owner's portal checks (8.18 steps 1-4):
1. **ACORD 27 downloaded by hand from the UAT portal** (`ASG_DOCUMENTATION/Acord27-template-downloadedfromASG.pdf`):
   checked offline - the SAME full-page "Sample" picture (`/Im2`, 1108 x 775), same 89 boxes, same edition 2016/03
   as our API download. **So nothing we send (or do not send, like `orgId`) causes it: ASG stamps every form for
   this account / environment.** Primble can only get sample forms today.
2. **The UAT account** (portal "User Profile"): username `vinaysharma`, role **User**, organisation **"Primble"**.
   No plan or environment label is shown. (If an `orgId` is ever needed, it is "Primble".)
3. **Production portal** (`transcriber.acordsolutions.net`): the same login is REFUSED ("Login Unsuccessful.
   Incorrect username or password"). **Primble has no production ASG account yet** - only UAT.
4. **Scope numbers:** the portal's Business Domain filter "P&C" shows **3,821** of the **4,164** downloadable
   versions (92%); the other ~343 are Life / Health / Annuity / Surety. Showing P&C only loses little.

**Conclusion:** clean, real forms need a PRODUCTION ASG account (portal login + PROD API credentials) for
organisation "Primble" - Brent / ASG. The owner is taking it to Brent. **The build is unaffected** (same code;
Render's credentials decide UAT or PROD); until PROD arrives every ASG form carries "Sample".

**Brent question 1, final wording:** "Our ASG account is UAT only (organisation 'Primble', role User). Every form it
downloads - by API or by hand in the portal - carries a 'Sample' watermark; the production portal does not accept
our login. We need a PRODUCTION Transcriber account and PROD API credentials (client id, client secret, API key)
for Primble, with licensed (watermark-free) form downloads. When can ASG set this up?"
**Brent question 2, with numbers:** "92% of ASG's downloadable forms are P&C (3,821 of 4,164). Show P&C only, or
include Surety / Life / Health / Annuity?"


### 8.20 Build on UAT now, switch to PROD by environment later (owner's proposal, 3 Nov 2026, 12:38 IST) - AGREED
**Yes.** The ASG door reads everything from the environment (`TRANSCRIBER_ENV`, the three keys, token URL, base
URL), so the code is identical on UAT and PROD. Rules that make the switch truly "change env and done":
1. **The switch on Render:** `TRANSCRIBER_ENV=prod`; the three PROD keys; `TRANSCRIBER_TOKEN_URL` = the prod token
   URL (or removed); `TRANSCRIBER_ALLOW_UAT_IN_PROD` removed. **This also moves the upload reading (Transcriber
   extraction) to PROD at the same moment** - same variables.
2. **Check the PROD host on the first call.** ASG's docs spell the production API host two ways
   (`prod-api-v1-transcriber...` and `prod-api-transcriber...`); our default is the first. If it is the other,
   `TRANSCRIBER_BASE_URL` fixes it - still env only.
3. **Forms generated on UAT keep "Sample" for ever** - the FILLED copy is stored per package. So until PROD: the
   feature stays behind its switch, on for the owner / test accounts only, never for customers; any package made
   on UAT is regenerated after the switch.
4. **Automatic check:** each download is checked for ASG's "Sample" picture (a full-page image the forms from ACORD
   do not have) and logged (`ASG_SAMPLE_FORM`), never removed. After the switch the log proves the forms are clean -
   and catches it if PROD ever serves sample forms.
5. **One test after the switch, with the owner's yes:** one download (ACORD 27) - clean, right edition, time.
   PROD may differ in editions, quota counting or IP whitelisting (Brent registered India + USA).


## 10. BUILD LOG - "any ACORD form" through ASG (owner's go: 3 Nov 2026)

### 10.0 CURRENT STATE (3 Nov 2026, 17:37 IST) - PARKED until Brent's production credentials; 10.1-10.22 are the history

**DONE - UAT, localhost; the owner live-tested it on 3 Nov:**
- **Search:**
  - 1,174 forms from ASG's supported list (`forms_catalog/asg_forms_index.json`), text only - it never calls ASG;
  - the sweep (10.21) made every form findable by number, state, variant and title, through plurals, punctuation,
    shorthand and misspellings, with a note whenever it widens;
  - 1-20 ms per search.
- **Selection:**
  - Done adds ASG forms under "Additional ACORD forms"; our own forms tick in their own place (L-2);
  - cap 8; Remove; ticks kept across searches and reloads;
  - no Back / Generate while typing, with our own X (L-3); the search bar is there on arrival (L-1).
- **Generate:**
  - every ASG form is pre-downloaded (own 8-thread pool, 120 s, failures remembered) and checked against the identity
    its footer prints (10.22);
  - "Sample" is logged;
  - filled by the same pipeline as our 17;
  - the values-only copy is stored per package, and nothing calls ASG after generation (D-ASG-11 - proven live).
- **Editor / downloads:**
  - the "Test copy" note; edit + save + reopen;
  - one-form and package downloads, with the encrypted Primble record;
  - certificates follow our 25 / 28's date rules.
- **Tests:**
  - ASG tests 137 / 137 (stub only); the screen-reading tests 296;
  - full suite 22,751 / 2 / 46 at 16:11 - before the search sweep and the identity check.

**Live test (10.8 table):**
- T1-T9 and T12-T14 PASS: ACORD 807 and 137 TX were added, ACORD 807 generated.
- T10 partly: the note was seen; the certificate check was not run.
- T11 not run (owner's choice). Sign not tried.

**NEXT TEST - ask the owner first:** the six verification calls (10.22, memory `next-asg-test-six-calls`).

**WAITING:**
- Brent: PROD credentials, scope, cap;
- ASG: the "Open" list below;
- the owner: O-ASG-1, the six calls, the full suite before commit.

**BEFORE COMMIT:** the full suite on the final code (the owner's yes); `git add` the 7 new files (10.10) - without
them the server will not start.

**BEFORE PROD:**
- L-4 / L-5 - line identity for ASG forms, design in 10.19;
- the PROD test call (8.20);
- the switches below.

**Local backend:** still running on http://127.0.0.1:8000, with `ASG_FORMS=1` given at launch (log
`<scratchpad>/anyform/backend_local4.log`). `backend/.env` is untouched - a restart without it turns the feature
off. Use a package uploaded ON LOCALHOST (primble.ai packages may not decrypt here).

**How it works:**
1. A search box on "Select Forms to Generate" (text list, never calls ASG) -> Done -> "Additional ACORD forms".
2. Generate pre-downloads every ASG form and checks its footer identity. Any failure = 503, nothing generated.
3. The same fill as our 17: rules, the shared AI gap fill, guards, checks.
4. The filled form plus a values-only copy are stored per package; every later render uses the copy, never ASG.
5. Certificates / evidence forms from ASG follow our 25 / 28's rules (existing term, no record attached).

**Switches (Render):**
- `ASG_FORMS=1` turns it on;
- on UAT credentials in production `ASG_FORMS_ALLOWED_EMAILS` is REQUIRED (empty = nobody - fail closed);
- `ASG_FORMS_MAX` (default 8);
- real (non-"Sample") forms need ASG's PROD credentials (`TRANSCRIBER_ENV=prod` + the three PROD keys) - Brent.

**Open:**
- O-ASG-1 - the values kept in the stored copy (owner);
- L-4 / L-5 - deferred, fix before PROD;
- Brent questions (8.16 / 10.4): PROD account, scope, cap;
- ASG questions:
  - the variant parameter's name, and whether every listed form has a fillable version (10.22);
  - the suffix meanings (INS / CIS / ONI / PCIS) and the 12 non-state variants;
  - a forms list API (10.18);
  - two contradictory list entries (10.21);
- the live timing of a heavy package with 8 ASG forms (improving-ll.md C113);
- Sign on an ASG form and a certificate (ACORD 27) - untested live.

**Deferred features (D-ASG-10):**
- adding an ASG form after generation;
- the applicant e-signature on ASG forms;
- the async path;
- "Not in our list - check ACORD Solutions" (R1-14);
- a "Show 25 more" button (offered, 10.18).

Sections 10.5 / 10.6 describe the build AS FIRST WRITTEN (13:05); the review tables (10.9-10.17) and the live-test
sections (10.19-10.22) say what changed after. Where they differ, the later section wins.

Owner's rules for this build: build it properly, break nothing that works, check every step, keep this file
updated, log every decision, NO ASG call without his yes. Built and tested on UAT ("Sample" forms); PROD later by
environment only (8.20).

### 10.1 Design decisions (3 Nov 2026, 12:49 IST) - read before touching this feature
- **D-ASG-1 Form id = the ACORD style `ACORD_<number>[_<STATE>[_<SUFFIX>]]`** (e.g. `ACORD_27`, `ACORD_137_TX`,
  `ACORD_137_FL_INS`) so every label, file name and the frontend's `formLabel` work unchanged ("ACORD 27").
  An id is an ASG form when it is in the ASG index AND not one of our 17 (`forms_database/forms_index.json`);
  a search hit that IS one of our 17 returns OUR id - our 17 stay ours (owner).
- **D-ASG-2 The search list** = `backend/forms_catalog/asg_forms_index.json`, text only (number, state, suffix,
  title, newest listed edition), built from ASG's supported-forms PDF by `scripts/build_asg_forms_index.py`.
  Owner-approved; refreshed by re-running the script. Typing never calls ASG. Odd entries ASG names in no
  number/state shape ("125/130/160_A NI", "25 -S") are skipped (logged by the script).
- **D-ASG-3 What is stored, per package only:** (a) the rendered filled form, in `session_pdf_bytes` as every form;
  (b) a VALUES-ONLY filled copy (the ASG form with the box values written and nothing else - no fitted fonts, no
  highlight colours, no signatures) as a second row of the same table, form id `<id>::asg_base`. Why (b): every
  later render (edit, sign, download) must start from the clean form, because a render writes fitted font sizes,
  highlight boxes and signatures INTO the PDF; clearing (b)'s values in memory gives back the exact blank form, so
  Primble never stores an empty form and never calls ASG again for that package. Both rows are deleted with the
  package (every delete is by `session_id`). No new table or column.
- **D-ASG-4 One ASG download per form per generation run.** The shared gap fill (needs the box list) and the form's
  fill (needs the PDF) share a RAM copy for the run (60 minutes, at most 48 MB by size since rounds 1 / 3, never on disk or in the
  database). The edition ASG returns is read off the PDF and kept on the package's form record.
- **D-ASG-5 One template door.** Every place that opened `templates/<file>.pdf` asks one function for the template:
  a path for our 17 (unchanged), the cleared base bytes for an ASG form. `fill_pdf` and the box-position reader
  accept bytes.
- **D-ASG-6 Fill exactly like our forms:** the same `process_single_form` - rules by key, the shared AI gap fill
  (ASG forms included), guards, Please verify / Missing, field validations, the per-form score's generic branch.
  Our per-form hand-written rules key on our 17 ids and stand down. Multi-policy packages already leave the
  header policy number blank on any non-section form (`_resolve_package_header_identity`).
- **D-ASG-7 Switch + cap:** `ASG_FORMS=1` turns it on (default OFF); `ASG_FORMS_ALLOWED_EMAILS` (comma list)
  limits it to those users - owner / test accounts until PROD; `ASG_FORMS_MAX` = 8 per package (owner,
  Brent to confirm). The server refuses an ASG form when off, not allowed, or over the cap. **Since F-3 (10.16) it
  fails closed:** in production on UAT credentials the allow-list is REQUIRED (empty = nobody), and the search is
  offered only when a download can work (credentials or the test stub present). With PROD credentials, or off
  production (localhost), an empty allow-list means everyone.
- **D-ASG-8 "Sample" check:** each download is checked for ASG's full-page sample picture and logged
  `ASG_SAMPLE_FORM` (never removed); the form record carries `asg_sample: true`.
- **D-ASG-9 Tests never reach ASG:** `ASG_FORMS_STUB_DIR` (set by `tests/conftest.py`) serves PDFs from disk;
  stub mode always wins over the network.
- **D-ASG-10 Not in this build (logged, later):** adding an ASG form from the editor AFTER generation (today's
  add-form door only takes forms an open issue asks for - the form selection screen says so, F-8); the applicant
  e-signature lines on ASG forms (read off our own templates by path - the editor says so on every ASG form, F-9);
  the async worker path (production runs synchronously).

### 10.2 Steps
| # | Step | Status |
|---|---|---|
| 1 | Search index + build script | DONE 12:56 - 1,186 forms at first; 1,174 since round 1 (12 non-state variants left out) |
| 2 | `services/asg_forms.py` (index, ids, meta, download, RAM copy, stub, sample check, schema, base, clear) | DONE 12:56 - checked offline (10.3) |
| 3 | Template door + `fill_pdf` / position reader accept bytes | DONE 13:05 (10.5) |
| 4 | Generation: `form_meta_for`, `shared_gap_fill`, `process_single_form`, generate route (switch, cap) | DONE 13:05 (10.5) |
| 5 | Re-render paths: regenerate, edit save, signature, editor boxes, needs-attention, re-stamp | DONE 13:05 (10.5) |
| 6 | Storage of the base row (`session_repository`) | DONE 13:05 (10.5) |
| 7 | Search API | DONE 13:05 - `GET /api/asg-forms/search` |
| 8 | Frontend: search bar, notice, results, Done, "Additional ACORD forms", fetch message | DONE 13:05 (10.6), build clean |
| 9 | Tests (stub only) + related suites + one full suite | ASG tests 107 / 107 after the fresh review (10.17); related suites 1,998 / 0; full suite 22,751 / 2 / 46 (16:11) - the known failure + one outdated test, fixed and green |
| 10 | Owner's live localhost test - real ASG + AI calls (10.8) | DONE 3 Nov 15:49-17:35 - passed; 3 screen issues + the search sweep + the identity check fixed (10.19-10.22) |
| 11 | Full suite on the final code + commit (with the 10.10 `git add` list) + deploy dark | waits for the owner |
| 11b | The six verification calls (10.22) | at the owner's next test |
| 12 | PROD credentials -> watermark-free forms -> open to customers | waits for Brent / ASG |


---


### 10.3 Step 2 checks (3 Nov 2026, 12:56 IST, offline, no ASG call)
- Ids: `ACORD_27` / `ACORD_137_TX` are ASG forms; `ACORD_25` / `ACORD_137_CA` are ours (stay ours); an unknown number
  is neither. Search: "27" -> ACORD 27 first; "137 tx" -> ACORD 137 TX; "binder" -> 75 / 76 / 275 / 276; "acord 25" ->
  OUR 25 first; Life forms rank after P&C.
- **The stored copy promise (D-ASG-3), measured on all 17 of our templates as stand-in ASG forms:** clearing the
  values-only copy gives back the blank form EXACTLY (every box's every key, every page's drawing), and filling the
  cleared copy gives EXACTLY the same PDF content as filling the blank. 0 of 17 differ.
  Two defects found and fixed on the way: a cleared tick box came back "/Off" where the blank had no value, and
  ACORD 140's pre-printed default (its edition box) was wiped - fixed by keeping each written box's blank state on
  the box (`/PrimbleBlankState`) and putting it back exactly.
- Why a values-only copy and not the rendered form: a render writes fitted font sizes (`_fit_text_to_box` shrinks a
  box's font permanently), highlight colour boxes into the page drawing, and signatures - a rendered form can never
  be turned back into the blank.

### 10.4 Brent, 3 Nov 2026 (relayed by the owner)
"We have secured additional licensing with ASG, which will move us out of their pilot and into a full production
suite. We are also preparing a joint press release in the coming weeks to publicly announce their commitment to
submission quality control with us listed as a partner." -> The e-mail's question 1 now asks WHEN the production
account / credentials are ready and to confirm production downloads are watermark-free.


### 10.5 Backend - what changed, file by file (3 Nov 2026, 13:05 IST). Our 17 forms' code paths are unchanged:
every edit is an `if ASG form: ... else: <the old code, untouched>` branch, or an additive key.
- NEW `services/asg_forms.py` - the module (ids, search, meta, the ONE download `fetch_blank`, RAM copy, stub,
  "Sample" check, edition reader, box reader, values-only copy, clean rebuild, `template_source`, `layout_source`).
- NEW `forms_catalog/asg_forms_index.json` + `scripts/build_asg_forms_index.py` - the search list.
- NEW `routes/asg_forms_routes.py` (registered in `main.py`) - `GET /api/asg-forms/search?q=` ->
  `{enabled, max_per_package, results}`; off / not allowed = `enabled: false`, no results.
- `services/form_instances.form_meta_for` - an id not in the package's form list and not a copy: the ASG row
  (None for anything else, exactly as before).
- `services/form_service.process_single_form` - ASG meta: download (RAM copy), boxes from the PDF, the form's
  record gets `edition` + `asg_sample`, the result gets `asg_base_pdf`. `shared_gap_fill` - an ASG form's box list
  from its download; a failed download skips that form (logged), as any form's failure always did.
- `routes/form_routes.select_forms_bulk` - refuses ASG forms when off / not allowed (403) or over the cap (400);
  an ASG form skips the template-file check; `AsgFormUnavailable` -> the form is listed in the response's new
  `asg_not_generated` (since round 2 a failure normally stops the run BEFORE generation - the pre-download). `get_form_fields` (editor boxes) and `update_pdf` (edit save) - ASG branch.
- `routes/signature_routes`, `services/signature_boxes` (producer signature render; `template_path_for` = None
  for an ASG form, so its applicant e-signature lines are not read - D-ASG-10), `services/needs_attention.
  widget_positions` - ASG branch.
- `services/pdf_service` - `_template_input`: `fill_pdf`, `extract_form_fields_with_positions`,
  `get_page_dims_pikepdf` accept the form's bytes (a path behaves exactly as before); `regenerate_pdf_for_form` -
  ASG branch (503 `CANNOT_SHOW` since round 2 - never "your answers are saved").
- `repositories/session_repository` - `asg_base_pdf` never goes into the session JSON; saved / loaded as the row
  `<form id>::asg_base` of `session_pdf_bytes`. A form without one writes exactly the one row it always did.
- `tests/conftest.py` - `ASG_FORMS=0`, `ASG_FORMS_STUB_DIR` always set (stub wins over network);
  `tests/fixtures/asg_forms_stub/` (27.pdf, 137_TX.pdf = two of our templates standing in for ASG's forms).
- Not changed on purpose: the essentials ("lite") paths (recommended forms only), `form_addition` (after-forms
  add - D-ASG-10), `form_dry_run` (its checks list our forms only), the worker (async off in production).
- Small known gap: the editor's Y/N "answer cell" refinement reads printed lines off a template FILE, so ASG forms
  get the plain box (no refinement) - display only.

### 10.6 Frontend (3 Nov 2026, 13:05 IST)
- NEW `components/form/AcordFormSearch.jsx`: a short notice ("Need another ACORD form? Search ACORD's full form
  library by form number or name ... filled from your submission just like the forms below"), a search box, and -
  only while something is typed - the matching forms in the SAME card style as the recommended forms (the normal
  sections hide while searching). Tick, then **Done**: the search clears, the normal sections come back, and the
  picked forms sit at the bottom under **"Additional ACORD forms"** (ticked; can be unticked). One of our own 17
  found by search is labelled "Primble form"; an ASG form "From ACORD Solutions - fetched when you generate". The
  cap shows as "You can add up to 8 extra ACORD forms to one package." Typing waits 250 ms and never calls ASG.
- `AcordModal.jsx`: the search shows only when the server says it is on for this user; the generation overlay
  adds the stage "Getting Forms from ACORD Solutions" when an added ASG form is ticked; a form ACORD Solutions
  could not give shows a toast ("ACORD Solutions could not provide ACORD 27 right now. Your other forms are
  ready."). "Add more ACORD forms" no longer repeats a form already added by search.
- `App.css`: the search styles. Build clean (`vite build`).


### 10.7 Checks so far (3 Nov 2026, 13:09 IST) - no ASG call, no database, no AI
- New tests `tests/test_asg_forms_3nov.py`: 42 of 42 (search, ids, switch / cap, stub download, "Sample" check,
  edition, the stored copy exact on all 17 templates, generation, re-render, gap fill box list, storage
  round trip, editor positions, the route).
- Offline end-to-end (scratchpad `anyform/e2e_offline.py`): ACORD 125 (ours) + ACORD 27 + ACORD 137 TX (ASG, stub)
  generated with no AI, then every reader generation runs after: stamped consistency, stops, package score, field
  QA, needs-attention (3 forms), box positions, re-render with NO ASG call, our 125 re-render, the producer
  signature, the encrypted Primble record, no applicant lines (D-ASG-10), the session JSON. All OK.
- Related existing suites (21 files, 925 tests): 924 passed, 1 failed - `test_no_form_file_path_is_built_from_a_copy_id`
  caught the stub building a file path from a form id without `base_form_id`. **The CODE was wrong** (the rule
  is the project's), fixed: the stub's file name goes through `base_form_id`; file green.
- Full suite: stopped at 38% (runner fault, fixed); the final run waits for the owner's yes.


### 10.8 Owner's localhost test - DONE on UAT 3 Nov (results in the table; written 13:10 IST; rewritten 15:58 IST for the build after 10.17)
**Status: RUN on 3 Nov 15:49-17:35 IST - results in the table below and in 10.19-10.22.** The next test starts
with the six verification calls of 10.22.

**ASG calls in this test: about 3** - 1 sign-in + 1 download per ASG form generated (ACORD 27 and ACORD 137 TX). The
owner's clicks are the yes. Search, edit, sign and download make NO ASG call. The AI gap fill runs (OpenAI cost), as
on any generation.

**Setup (done 15:49 IST):**
- backend: `cd backend && source .venv/bin/activate && ASG_FORMS=1 uvicorn main:app --host 127.0.0.1 --port 8000`
  - no `--reload` (it can stall silently);
  - `.env` untouched;
  - no allow-list needed locally.
- frontend: `cd frontend && npm run dev` (it already points at `http://localhost:8000`).

**Use a package uploaded ON LOCALHOST.** Localhost and primble.ai share the database but not the encryption key. A
package made on primble.ai may not decrypt here: the backend log shows `FIELD_ENCRYPTION_KEY mismatch`, and the forms
would fill from partial data. This was already the case before this feature.

| # | Step | Expect | Result |
|---|---|---|---|
| T1 | Open the package, reach "Select Forms to Generate" | the notice "Need another ACORD form? ..." and a search box above the recommended forms | PASS 16:04 (package `93646570`) - but the bar appeared about a second AFTER the screen and pushed the list down: L-1 (10.19) |
| T2 | Type `27` | ONLY search results show (recommended list hidden); ACORD 27 first, tagged "From ACORD Solutions - fetched when you generate" and "Edition ... or newer" | PASS (16:27) - owner's screenshots; results only while typing, tags shown |
| T3 | Tick ACORD 27, press Done | the search clears; the recommended list comes back; ACORD 27 ticked at the bottom under "Additional ACORD forms", with Remove | PASS (16:27) - the owner added ACORD 807 (D&O) and ACORD 137 TX: both ticked under "Additional ACORD forms" with Remove; the note above Generate shows. FOUND L-2 (a Primble form picked in search was also listed there) |
| T4 | Search `137 texas` (also try `137tx`), tick ACORD 137 TX, Done | added under the same heading | PASS (16:27) - "137 texas": 2 found, 137 TX first, then 137 TX INS with its Variant tag |
| T5 | Search `acord 25`, then `coi` | ACORD 25 first, tagged "Primble form" (ours) | PASS (16:27) - "acord 25": our 25 first as "Primble form", then 25 INS |
| T6 | Search `137` | "Showing 25 of 60 - add a state or more words to narrow it"; our 137 CA / CO first | PASS (16:27) - "Showing 25 of 60 - add a state or more words to narrow it"; our 137 CA / CO first. FOUND L-3 (Back / Generate shown greyed while searching) |
| T7 | Tick a form, then clear the box without Done | "Ticked, not added yet: ... Press Done to add it. Untick all"; Generate waits ("Press Done to add the forms you ticked.") | |
| T8 | Reload the page on form selection | the added forms come back, with their ticks | |
| T9 | Generate (ACORD 125 + ACORD 27 + ACORD 137 TX) | the overlay shows "Getting Forms from ACORD Solutions"; the log shows 2 x `ASG_FORM_DOWNLOAD` and 2 x `ASG_SAMPLE_FORM` (UAT) | PASS 16:22:49-16:24:00 (about 71 s) - the request held ONE form, ACORD 807 (D&O): 125 and 137 TX were not ticked at Generate. Pre-download 24.2 s (first sign-in + download, UAT), `ASG_SAMPLE_FORM` logged; fill and checks about 47 s. Details 10.20 |
| T10 | Open ACORD 27 (Evidence of Property Insurance) in the editor | values from the package; the "Sample" watermark; the note "Test copy from ACORD Solutions. ..." and "The applicant's e-signature is not added to this form ..."; the policy dates are the EXISTING policy's term (or blank), as our ACORD 25 prints them - never the proposed next term (ACORD 27 is a certificate, F-1 / R9-2) | PARTLY (16:50) - on ACORD 807 the owner SAW the note "Test copy from ACORD Solutions. ... The applicant's e-signature is not added ...". The certificate-dates check (ACORD 27) was not run |
| T11 | Open ACORD 137 TX | filled from the package by the shared rules and the AI gap fill. Our 137 CA / CO's own hand-written rules do not apply to it (D-ASG-6), so expect fewer boxes than on our 137 - wrong values are the defect to look for, not blanks. The same note | NOT RUN - 137 TX was unticked at Generate |
| T12 | Edit a box, save, reopen; sign; download one form, then the package | the edit is kept; the signature is on the producer box; both downloads work; NO new `ASG_FORM_DOWNLOAD` in the log | PASS (16:50) - edit + save + reload + reopen kept the value (`update-pdf` 200); one-form download PASS (`download-pdf` 200) and package download PASS; NO new ASG call. Sign not tried (optional) |
| T13 | Reload while in the editor | the note on ASG forms is still there | PASS (16:50) - the owner saw the note after reloads |
| T14 | (optional) Untick an added form before Generate | it is not generated | PASS - 137 TX stayed listed but unticked and was NOT generated (no download for it) |
| T15 | (optional) Try to add a 9th ASG form | "You can add up to 8 extra ACORD forms to one package - remove one to add another." | |

**After the test, Claude reads the backend log** (`ASG_FORM_DOWNLOAD` seconds, `ASG_SAMPLE_FORM`,
`ASG_FORM_DOWNLOAD_FAILED`, the AI fill time) and records each result in this table and in the section 9 log.

**Possible failure messages and what they mean:**
- "Adding ACORD forms from ACORD Solutions is not set up on this server yet. ..." - credentials or sign-in.
- "Nothing was generated. ACORD Solutions could not provide ..." - ASG is down or slow; retry.
- "... has no fillable version of ..." - ASG's own answer for that form.

**To turn it off:** restart the backend without `ASG_FORMS=1`; the search disappears. On Render nothing changes until
`ASG_FORMS=1` is set there - the deploy is dark by default.


### 10.9 Review round 1 (3 Nov 2026, 13:17-13:38 IST) - three read-only reviewers; every real finding fixed
Owner's process (3 Nov): fix, log, run all three reviewers again, repeat until none finds a bug; then ONE more
general reviewer (does everything work together?); then the full suite - once, at the end.

**Backend findings and fixes**
| # | Sev | Finding (who) | Fix |
|---|---|---|---|
| R1-1 | CRITICAL | Most routes load a package WITHOUT its PDFs (`get_processing_session` default), so an ASG form had no copy: the editor's boxes 404'd and preview / edit save went back to ASG on every call - on the event loop, ungated, failures uncached (functionality + breaker) | `session_repository._attach_asg_base_rows`: every read of a package that HAS ASG forms attaches each one's stored copy (`_asg_base_stored`) - one small query; packages without ASG forms make no extra query. `template_source` NEVER calls ASG any more (None -> 503 "temporarily unavailable - your answers are saved"). **D-ASG-11** |
| R1-2 | HIGH | Network / parse errors (timeout, refused, HTML token reply) escaped as raw exceptions -> 500s and no "could not be fetched" notice (both) | `_network_fetch` wraps `httpx.HTTPError` / `ValueError` / `KeyError` into `AsgFormUnavailable("asg_error")` |
| R1-3 | HIGH | `update_pdf` with no template stored the edit with no PDF and dropped the signature (breaker) | refuses with 503 BEFORE anything changes when an ASG form has no stored copy |
| R1-4 | HIGH | The clean-form rebuild ran on the event loop in edit save and signing (both) | `run_in_executor` in both routes; `regenerate_pdf_for_form` rebuilds only after its cache checks |
| R1-5 | HIGH | `_form_edition_identifier` globs `ACORD_1*` -> ASG forms 1 / 2 / 12 / 13 / 18 printed the 101 / 25 / 125 / 130 / 186 edition (functionality) | returns None for an ASG form (its own printing stays); our 17 unchanged |
| R1-6 | MEDIUM | `" ACORD_27"` / repeated ids slipped past the cap and were stored twice; the cap counted the request, not the package (breaker) | the route takes every id in one spelling first (`asg_forms.clean_form_ids`) and counts the package (`asg_count_in_package`) |
| R1-7 | MEDIUM | A box listed twice in a malformed PDF leaked its value into the "clean" form (breaker) | the blank state is recorded on the FIRST visit only |
| R1-8 | MEDIUM | After a reload an ASG form's schema came back key-sorted (JSONB) - the Y/N -> explanation pairing reads positions; our 17 recover order from `forms_schemas/`, ASG forms cannot (functionality) | the printed box order is kept as a list (`asg_box_order`) and restored on every read (`prepare_loaded_session`) |
| R1-9 | LOW | Adding a document after forms re-downloaded the ASG forms, ungated (breaker) | the shared gap fill reads the package's own copy; a NEW download only during a first generation with the switch on |
| R1-10 | LOW | 12 list entries carry a 2-letter code that is not a state ("126_GL", "25_FR", "60_US", "130_IS" ...) and would send `geoCode=GL` (breaker) | left OUT of the list (`skipped_variants` in the index) until ASG says how to fetch them - **question for ASG**. List now 1,174 |
| R1-11 | LOW | The edition reader let ACORD 1 read "ACORD 125 (2025/03)" (breaker) | the number must end where the form number ends |
| R1-12 | LOW | RAM copy could expire mid-generation (15 min) -> a second download | 60 minutes; the token's Bearer flag read under its lock |
| R1-13 | - | The stored copy | saved with object streams: about HALF the bytes, same content (27: 84 -> ~32 KB; 137: 300 -> ~153 KB) |
| R1-14 | MEDIUM | The owner's 8.16 "Not in our list yet - check ACORD Solutions" button was not built (functionality) | **Deferred, logged (D-ASG-10)**: a form outside the list cannot pass the id check; refreshing the list (re-run the script) covers new forms |

**Frontend findings and fixes**
| # | Sev | Finding | Fix |
|---|---|---|---|
| F1 | HIGH | Added forms and a typed search carried over to the next package (all three reviewers) | cleared in `resetFormTicks` (all 5 of its call sites: session load, new package, dashboard, upload, integrity) |
| F2 | HIGH | Ticks from an earlier search were lost on Done | ticks kept as a Map (id -> row) across searches; Done adds them all |
| F3 | MEDIUM | Ticks were dropped silently if the search was left without Done; Generate stayed live | clearing the search drops its ticks; Generate is disabled while a search is open, with "Press Done to add the forms you ticked, or clear the search." |
| F4 | MEDIUM | The cap counted differently from the server; an added form could not be removed | each added form has **Remove** (frees its place); the cap counts added ASG forms + ticked ones |
| F5 | MEDIUM | Done skipped `formTicksTouched` (the review page's checks follow the ticks) | set on Done and Remove |
| F6 | LOW | `max_per_package || 8`; a late reply after clearing; a "No match" flash; an unticked added form shown ticked; `setNote` inside a state updater; "added by you from ACORD's full library" on our own forms; no `aria-live`; Life / Health forms not marked | `?? 8`; stale replies ignored; results show only for the search they answer; the tick follows the package's ticks; note set outside; heading "added by you"; `aria-live="polite"`; "Life / health / annuity form" tag |
| - | LOW | The async (202) path drops `asg_not_generated` | not fixed: production runs synchronously (noted) |

**Decision D-ASG-11 (3 Nov 2026):** after generation an ASG form is ALWAYS drawn from the package's stored copy,
which is read with the package on every request (for packages that have ASG forms). No read, edit, signature or
download ever calls ASG. Cost: those packages read their copies (~30-150 KB per ASG form, compacted) with each
request - none for packages without ASG forms.

**Checks after the fixes:** `tests/test_asg_forms_3nov.py` 59 / 59 (17 new, one per finding; one old test updated -
it ran a first generation with the switch off, which the code now correctly refuses); related suites 925 / 925;
frontend build clean. The full suite runs once at the end (the earlier run was stopped at 38%: the runner's
`split -n` does not exist on macOS, so it ran as one process - runner fixed).


### 10.10 Review round 2 (14:01 IST) - all round-1 fixes confirmed; new findings fixed
Round 1 confirmed FIXED by the reviewers (functionality: all but the deferred button; breaker: 7 fixed, 3 partly -
the partly ones are closed below; frontend: all but two accepted items).

| # | Sev | Finding (who) | Fix |
|---|---|---|---|
| R2-1 | MEDIUM | A form ASG fails to give DURING generation stayed in the package list and could never be added later; the editor could even open on it (functionality + breaker) | **Every ASG form is downloaded BEFORE generation**, in parallel, off the event loop (`asg_forms.try_fetch`); any failure stops the run with "ACORD Solutions could not provide ACORD 27 right now, so nothing was generated. Remove it from your selection, or try again in a few minutes." - nothing generated, the user can retry. A form that still fails mid-run is dropped from the package list (never listed, never opened). |
| R2-2 | MEDIUM | A failing form was downloaded twice and serially on the shared generation threads (functionality) | the pre-download is the only attempt (the run's RAM copy serves the rest); connect timeout 10 s |
| R2-3 | HIGH | Box positions re-read from the copy once per "New document says" row, on the event loop: 3.6 s per request on a 40-row form (breaker) | positions cached per copy (`needs_attention._asg_widget_positions`, keyed by the copy's bytes) |
| R2-4 | PARTLY | A token reply of the wrong JSON shape still escaped (breaker) | every non-AsgFormUnavailable error in the download becomes "unavailable" |
| R2-5 | PARTLY | A copy present but unreadable: edit save still stored no PDF and dropped the signature (breaker) | edit save refuses (503) whenever the template cannot be rebuilt - nothing is saved first (checked: `update_pdf` writes nothing before that point) |
| R2-6 | LOW | Every read of an ASG package pulled every copy from the database (~1.2 MB per request for 8 forms; the ai-fill poll runs every 3 s) (both) | the copies never change after generation, so each process keeps the ones it read (`asg_forms.cached_copies` / `remember_copies`, at most 32 MB, oldest out first): one database read per package per process |
| R2-7 | LOW | 503 text said "your answers are saved" when the edit was refused (both) | three honest messages: "This form cannot be shown right now - its stored copy could not be read. Please contact support." / "Your edit was not saved - ..." / "The form was not signed - ..." |
| R2-8 | LOW | Frontend: an added Primble form later recommended showed twice and Remove unticked it; ACORD 127 added by search did not tick its state 137; the review page's dry run could never match ASG ticks; a failed search read as "no match"; the cap counted a re-picked form twice; the screen-reader note was hidden; Remove was a small touch target | added list shows only forms no tier lists, Remove keeps a recommended form ticked; Done ticks the 137 companions; ASG ids left out of the review page's ticks; "Search is not available right now - please try again."; re-picks not double counted; note kept on screen (empty takes no space); Remove 44 px on mobile |

**Not fixed, on purpose (logged):**
- The ASYNC (202) path drops `asg_not_generated` - production is synchronous.
- Two parallel generate requests for one package can both pass the "no forms yet" check - a race that exists for
  every form today (not new); the frontend disables Generate while a run is on.
- Package download ("all forms"): a form whose copy cannot be read is skipped like any form that fails to render
  (existing behaviour) - with D-ASG-11 the copy is always there.
- `clean_form_ids` also tidies our own forms' requests (trim + once each) - only malformed requests change.

**OPEN QUESTION FOR THE OWNER (O-ASG-1):** the stored copy keeps the values from generation time. If a person later
corrects or deletes a value (a wrong FEIN), the OLD value stays inside that copy until the package is deleted (it
is never shown or printed - every render clears it - but it is personal data at rest). Options: (a) keep as is;
(b) store the copy WITHOUT values - still one copy per package (never a library), and the filled form itself is
stored separately and always current. **Recommendation: (b).**

**BEFORE COMMITTING (deploy safety):** these files are NEW and must be added with `git add`, or the server will not
start (`main.py` imports the search route; the package loader imports the ASG module):
`backend/services/asg_forms.py`, `backend/routes/asg_forms_routes.py`, `backend/forms_catalog/asg_forms_index.json`,
`backend/scripts/build_asg_forms_index.py`, `backend/tests/test_asg_forms_3nov.py`,
`backend/tests/fixtures/asg_forms_stub/` (2 PDFs), `frontend/src/components/form/AcordFormSearch.jsx`.
**UPDATED 4 Nov 2026 (full-feature review): the list above is INCOMPLETE - commit EVERY untracked file `git status`
shows (`git status --short | grep '^??'`).** Also needed or startup / build fails: `backend/services/captcha.py`
(`auth_routes` imports it), `backend/services/document_fingerprints.py` (`init_db` imports it),
`frontend/src/components/auth/TurnstileWidget.jsx`, `frontend/src/utils/smsShare.js`, `OPEN_ITEMS.md`, and the new test
files (`test_captcha_3nov`, `test_document_fingerprints_3nov`, `test_sms_share_3nov`, `test_stripe_guards_3nov`,
`test_stripe_review*_fixes_3nov` x6). `ASG_DOCUMENTATION/` stays out of git (`.gitignore`; ASG-confidential) - the
built `backend/forms_catalog/asg_forms_index.json` is what ships.

**Checks:** ASG tests 67 / 67 (8 new for round 2); related suites 925 / 925; frontend build clean.


### 10.11 Review round 3 (14:16 IST) - round-2 fixes confirmed; the new pre-download hardened
Round 2 confirmed FIXED by all three reviewers (positions: 40 rows 3.63 s -> 0.09 s; copies: 5 reads of 2 packages
-> 2 queries; 503 texts; mid-run failures out of the package).

| # | Sev | Finding (who) | Fix |
|---|---|---|---|
| R3-1 | MEDIUM | The pre-download ran on the app's SHARED thread pool (8 threads on the Mac): 8 ASG forms could stall every user's preview / edit / signing for the download time (both) | its own pool of 4 threads (`asg_forms.download_pool`) and a 45 s deadline for the whole pre-download |
| R3-2 | MEDIUM | Nothing marked the package busy during the pre-download - a second Generate or a pre-form change could race the run for those seconds (both) | the package is marked "preparing" (`asg_preparing_at` on the row - every server sees it) before the download, cleared when the run's own marker is written or the download fails, expires by itself after 120 s; the three refusal checks (`_refuse_once_forms_exist`, the audit / documents door, the policy-lines door) answer 409 "Forms are being prepared for this package - wait a moment." The package page's run state is untouched. |
| R3-3 | LOW-MEDIUM | Other users' downloads could push a run's forms out of the RAM copy between its pre-download and its fill (a count-bounded cache; each download took 2 slots) (functionality) | the RAM copy is bounded by SIZE (48 MB), one entry per download whatever its keys, least recently used out first |
| R3-4 | LOW | Failures were never remembered: each Generate click re-asked ASG (breaker) | remembered per form + edition: 6 h for "no fillable version", 3 min for an outage / sign-in error |
| R3-5 | LOW | ASG was called, then the request refused with "too many jobs" (both) | the in-flight check now runs BEFORE any download |
| R3-6 | LOW | A reply starting `%PDF-` that is not a readable fillable form passed and stayed cached; generation then failed silently (breaker) | a download must read as a form with at least one box, else "not available" (never cached); ANY failure of an ASG form during the run lists it in `asg_not_generated` |
| R3-7 | LOW | A setup problem (no credentials / UAT keys in production) said "try again in a few minutes" (functionality) | "Adding ACORD forms from ACORD Solutions is not set up on this server yet. Please contact support." |
| R3-8 | LOW | Frontend: Done re-ticked a state 137 the user had unticked; one-or-several grammar in the not-fetched notice; the alert's "Retry Generation" ignored an open search; a failed search showed "0 found" and could not be re-run (frontend) | declined 137s respected; "it is" / "they are"; Retry hidden while searching; no count on failure + a "Try again" link |

Accepted, unchanged (logged earlier): two simultaneous Generate requests can still both pass in the instant before
either writes "preparing" (milliseconds, as for every form); the 202 path; O-ASG-1.

**Checks:** ASG tests 73 / 73 (6 new for round 3); related suites + the refusal-check files 1,158 / 1,158; frontend
build clean.


### 10.12 Review round 4 (14:30 IST) - frontend: NO new findings; backend: round-3 fixes confirmed, 4 new fixed
Frontend reviewer: A1-A4 fixed, both new backend messages (409 "being prepared", 503 "not set up") display
correctly in the existing handlers - **no new findings; the frontend is closed** (it did not change in this round).

| # | Sev | Finding (who) | Fix |
|---|---|---|---|
| R4-1 | MEDIUM | The 45 s pre-download deadline counted time queued for the 4 download threads: 8 cold forms (2 waves x ~22 s) or 2-3 users generating at once failed with a healthy ASG, and a timeout named EVERY form, finished ones included (both) | 8 download threads (one package's whole selection in one wave), a 120 s deadline, and `asyncio.wait`: only forms that had not arrived are reported; queued ones are cancelled, arrived ones stay in the RAM copy |
| R4-2 | LOW | A request stopped between the "preparing" mark and the run's marker (a dropped connection, the queue failing, the marker write failing) left the mark for up to 120 s - every action on the package got 409 (all three) | a `try / finally` clears the mark unless the run's marker was written (also on a cancelled request); it still expires by itself |
| R4-3 | LOW | One malformed reply ("%PDF-" but no boxes) blocked the form for 6 hours (functionality) | its own reason `bad_file`, remembered 3 minutes; 6 h only for ASG's own "no fillable version" |
| R4-4 | LOW | On an archived package the "preparing" write was refused but swallowed, and the downloads still ran (breaker) | the archive door's refusal now stops the request BEFORE any download |

**Checks:** ASG tests 76 / 76 (3 new route-level tests: the mark is cleared after a failure, a failed download
answers 503 and clears it, an archived package is refused before any download); ASG + related suites 1,234 / 1,234.


### 10.13 Review round 5 (14:34 IST) - round-4 fixes confirmed; 2 low timing items fixed
Both backend reviewers: round 4 FIXED (A/B/C, N1/N2); our 17 forms' generate path unchanged (the try / finally does
nothing without ASG forms).

| # | Sev | Finding (who) | Fix |
|---|---|---|---|
| R5-1 | LOW-MEDIUM | The "preparing" mark lived 120 s, exactly the pre-download deadline - on a slow ASG it could expire just before the run's marker, reopening the race (both) | `PREPARING_TTL_SECONDS` 300 s; a test keeps it at least 60 s past the deadline |
| R5-2 | LOW | A hung ASG kept a download thread for minutes of retries after the deadline (functionality) | no new attempt starts once 45 s are spent (`_DOWNLOAD_BUDGET_SECONDS`) |
| R5-3 | cosmetic | Failed forms were named in a random order (breaker) | named in the order the user picked them |

**Checks:** ASG tests 79 / 79 (3 new); with the run-state / multi-user files 205 / 205.


### 10.14 Review round 6 (14:37 IST) - functionality: NO new findings; breaker: 1 low fixed
Functionality reviewer: D and E fixed, **no new findings** (backend functionality closed). Breaker: the round-5 item
fixed; one new LOW.

| # | Sev | Finding | Fix |
|---|---|---|---|
| R6-1 | LOW | A sign-in service that hangs: each of the 8 download threads waited for the token lock and then tried its OWN sign-in (~70 s each) - the pool blocked for minutes (breaker) | a failed sign-in is remembered for 60 s under the lock: the waiting threads fail at once; one sign-in attempt, not one per form |

**Checks:** ASG tests 80 / 80 (1 new; the sign-in state is reset between tests).


### 10.15 Review round 7 (14:40 IST) - the sign-in memory confirmed; 2 low wording / memory items fixed
Both reviewers: the round-6 fix holds (one sign-in attempt, not one per form; download 401 unaffected; our 17 untouched).

| # | Sev | Finding | Fix |
|---|---|---|---|
| R7-1 | LOW | During the 60 s after a REFUSED sign-in (wrong credentials), other forms failed as "asg_error" -> "try again in a few minutes" instead of "not set up" (both) | the remembered sign-in failure keeps its own reason and text ("auth" -> NOT_SET_UP) |
| R7-2 | LOW | Those quick sign-in failures were also remembered against each FORM for 3 minutes - longer than the 60 s sign-in block (functionality) | a sign-in failure is marked `sign_in` and never written to the per-form memory; when sign-in recovers, the forms are available at once |

**Checks:** ASG tests 82 / 82 (2 new).


### 10.16 Final reviews (15:00 IST) - a general reviewer and a STRICT end-user reviewer (owner's request); all fixed
General verdict: coherent, safe to deploy dark, our 17 forms untouched. End-user: walked every journey a producer can
take (typing, picking, generating with ASG slow / down / refusing, after generation, mobile, screen reader).

| # | Sev | Finding (who) | Fix |
|---|---|---|---|
| F-1 | HIGH | ASG certificates / evidence forms (ACORD 27, 20-24, 25 INS ...) were filled as APPLICATIONS: the proposed (next) term printed on a document sent to a lender, an edit of the dates moved the PACKAGE's proposed term, and the download carried the encrypted package record (end-user) | `asg_forms.is_certificate_form` (title: certificate / evidence of / ID card - 65 list entries) joins our 25 / 28 everywhere they are special: `pdf_service._is_certificate_form` (renewal dates, proposed-term write-back, OTHER-row rule) and `primble_record` (no record) |
| F-2 | HIGH | Search stopped at 25 results and said "25 found": "137" (60 matches) never showed 137 TX (end-user) | the route returns the total; the screen says "Showing 25 of 60 - add a state or more words to narrow it" |
| F-3 | HIGH / MEDIUM | An empty allow-list let EVERY user in - with Render's `TRANSCRIBER_ALLOW_UAT_IN_PROD=1`, turning the feature on would have given every customer "Sample" forms; `asg_sample` was never shown (both) | fail closed: production on UAT credentials REQUIRES the allow-list; the search is offered only when a download can work; the editor shows "Test copy from ACORD Solutions. This form carries a "Sample" watermark - do not send it to a client or carrier." |
| F-4 | MEDIUM | Common spellings found nothing ("137tx", "137-TX", "137 texas", "texas 137", "ACORD-25", "form 27", "#27", "0027", "COI"); "FL" matched title fragments (end-user) | query parsing: punctuation / "form" / "#" stripped, "137tx" split, leading zeros dropped, state NAMES -> codes, COI / EOI / WC / GL synonyms; titles matched by whole-word prefixes; our 17 first, the plain form before state versions before variants |
| F-5 | MEDIUM | Clearing the search silently dropped every tick (end-user) | ticks wait, listed ("Ticked, not added yet: ... Press Done to add them. Untick all"), until Done or Untick; Generate waits meanwhile |
| F-6 | MEDIUM / LOW | A permanent "no fillable version" said "try again in a few minutes" (both) | "ACORD Solutions has no fillable version of ACORD X, so it cannot be generated - remove it from your selection." |
| F-7 | MEDIUM | Look-alike results ("125" CIS / INS / ONI / PCIS, same title) (both) | each row shows "Edition YYYY/MM or newer" and 'Variant "INS"'; variants rank after the plain form; their meaning is an ASG question |
| F-8 | MEDIUM | A reload on form selection dropped the added forms; after generation an ASG form can never be added (end-user) | added forms kept per package in the browser (restored and re-ticked on return; cleared on generation / last Remove); a note before Generate: "Forms from ACORD Solutions can only be added before you generate - add every form you need now."; the not-generated notice says it "cannot be added to it later" |
| F-9 | MEDIUM | The applicant's e-signature silently skips ASG forms (end-user) | the editor's notice on every ASG form: "The applicant's e-signature is not added to this form - sign it by hand if it needs one." (adding it stays deferred, D-ASG-10) |
| F-10 | MEDIUM | AI cost / time of a full ASG selection never measured (general) | measured offline and logged: 8 forms -> 927 unmatched boxes -> ~+24 gap-fill calls per chunk (improving-ll.md C113); live timing on the owner's test |
| F-11 | LOW | Our own error blamed ACORD Solutions in the notice; the cap note did not mention Remove; our own form added by search showed ASG's title; a deleted package's copies stayed in memory; a stale comment; a dead helper (both) | neutral "could not be generated"; "... - remove one to add another."; our form keeps our name; `forget_package` on delete; comment fixed; `has_asg_forms` removed |
| F-12 | LOW | Docs behind: CLAUDE.md "analysis only", ASG_TRANSCRIBER.md silent on the Download API, section 10 details out of date (general) | CLAUDE.md section rewritten; ASG_TRANSCRIBER.md entry; 10.0 current state + stale lines corrected |

**Checks:** ASG tests 100 / 100 (18 new: every spelling, the total, fail-closed production, not offered when it
cannot work, certificates, delete eviction, messages); frontend build clean; no em-dash in any new UI text.


### 10.17 Fresh review of the final fixes (15:41 IST) - nothing HIGH, nothing touching our 17; all fixed
Scope: only the changes made after round 8 (10.16) and their regressions. Verified unchanged: our 17 forms
(`_is_certificate_form` equals the old set on all 17 ids and copies; `primble_record` and `proposed_term_fact`
unchanged for ours), search and generate agree on every switch combination, no cross-package leak, hooks order safe.

| # | Sev | Finding | Fix |
|---|---|---|---|
| R9-1 | MEDIUM | The editor's ASG notice ("Sample" warning, no applicant e-signature) vanished after any reload - only the generate reply carried the form's record | `GET /api/session` now carries `form: {source, asg_sample}` for ASG forms (ours unchanged) |
| R9-2 | MEDIUM | F-1 was half fixed: an ASG certificate's OTHER date boxes (e.g. `OtherPolicy_PolicyEffectiveDate_A`) still printed the proposed term on a routed renewal | `pdf_service._resolve_asg_certificate_term`: on an ASG certificate every box whose rule writes the policy dates prints the moved current term or an owned blank; our 25 / 28 keep their own resolvers |
| R9-3 | MEDIUM | On tablet / phone the editor notice took half the editor (the layout gives every child of `.editor-main` half the height) | `.editor-main > .acord-asg-editor-note` sized to its content |
| R9-4 | MEDIUM / LOW | "id card" searched Idaho; "auto id card" found nothing | a bare two-letter word is a state only beside a form number or alone |
| R9-5 | LOW | A restored list re-ticked forms the user had unticked, and kept ASG forms after the switch was turned off or the cap lowered | each saved form keeps its tick; once the server's answer arrives, ASG forms leave the list when the feature is off for the user and the list is trimmed to the cap |
| R9-6 | LOW | "acord25" (no space) found nothing; ACORD 50 FL ("...INSURANCE IDENTIFICATION") was not a certificate; the all-failed 503 still blamed ACORD Solutions for our own error; account delete / retention left copies in memory | split letter-digit; title rule adds "insurance identification" (and checked it does NOT catch ACORD 771, a lab form - 64 certificate forms); our own error -> the plain 400; account delete forgets the packages' copies and every copy leaves memory after 6 h |
| R9-7 | design | While ticks waited for Done with an empty box, the whole recommended list was hidden | the list hides only while something is typed; Generate still waits for Done |

**Checks:** ASG tests 107 / 107 (7 new); frontend build clean. Next: the full suite (owner: "go follow the steps").


### 10.18 Can the search go straight to ASG? (owner's question, 3 Nov 2026, 16:02 IST) - NO; there is no search API
**Checked again, offline:**
- ASG's three Postman collections hold 8 requests in all - `/v2/forms/download`, `/v2/forms/extract` (+ its GET) and
  `/v2/forms/populate`. None lists or searches forms.
- The PDF docs add only upload / large-file variants of those calls. The bare `/v2/forms` in `Download-HomePage.pdf`
  is the download URL broken across a line.
- The search ASG does have ("ACORD Forms (earlier termed as Forms Download) allows the user to search ... filters,
  such as domain or LOB") is a page in their web PORTAL - a person logs in and clicks. Primble cannot call it.

**So Primble's search box searches ASG's own published list.** It is built into our text index (1,174 forms) from
`SUPPORTED-ACORD-FORMS-ASG.pdf` by `scripts/build_asg_forms_index.py`. Typing never calls ASG; only the picked forms
are downloaded, at Generate. Why this is the right default:
- it answers instantly while typing;
- it costs no quota;
- it keeps working when ASG is down;
- it adds no ASG call per keystroke - against the owner's rule of no needless calls.

**What "straight from ASG" could still mean - two options, neither built:**
1. **An exact-number check** - the deferred R1-14 button "Not in our list yet - check ACORD Solutions".
   - It sends the typed number to the Download API: 1 call, 4-10 s, "Invalid Form" when the form does not exist.
   - It finds a form missing from our list, but by exact number only - no titles, no partial match - and only on a
     button press, never per keystroke.
   - Worth building only if users need forms that are not on ASG's own list.
2. **Ask ASG for a list / search endpoint** (e.g. number, state, edition, title, updated since). Our list would then
   refresh itself, and the portal's 4,164 versions would be fully covered.
   - At 12:32 the owner DROPPED this question from Brent's e-mail, because we hold ASG's list (section 9).
   - It goes back in only if a live search is wanted.

**Until then:** when ASG publishes a new supported-forms list, save it from the portal and re-run the script. That takes
minutes and needs no code change. The list's one risk is going stale: a form ASG adds after our copy is not searchable
until the list is refreshed.


**Owner, 17:05: can we get ASG's updated list by an API call - weekly - and refresh ours?** Not with the APIs we have.
The full inventory exists only in two places:
- the supported-forms PDF in their documentation;
- the search page inside their portal, which needs a person to log in.

So:
1. **Ask ASG (through Brent) for a list endpoint** or a stable download link of the list (form number, state,
   edition, title, ideally "changed since"). With it, a weekly job in our scheduler rebuilds the list by itself; the
   builder script already converts their list. Draft question: *"Could ASG provide an API endpoint (or a stable
   download link) that returns the full list of ACORD forms available for download - form number, state, edition and
   title - so Primble can refresh its forms list automatically each week?"*
2. **Until then:** refresh by hand when ASG publishes a new list - save the PDF from the portal, run
   `scripts/build_asg_forms_index.py`, deploy. A couple of minutes, no code change.
3. **Not options:**
   - scraping their portal - a logged-in page, breaks on any change, likely against their terms;
   - test-downloading every number weekly - thousands of calls on our quota.

**What "a form ASG adds later" means:** our list is a copy of ASG's list as of the PDF we hold. A brand-new form
NUMBER (or a new state version) that ASG adds afterwards is not in our search until we refresh - typing its number
says "No ACORD form matches". New EDITIONS of forms already listed are NOT affected: Generate always asks ASG for the
latest edition.

**Top 25:**
- The list shows the best 25 - the exact number first, our forms first, the plain form before its state versions and
  variants, P&C before Life / Health.
- The screen says "Showing 25 of N - add a state or more words to narrow it".
- Broad test words: `auto` 292, `application` 348, `property` 102, `liability` 74, `137` 60, `garage` 57,
  `id card` 39.
- Narrowed: `auto texas` 7, `new york auto` 7, `137 virginia` 1, `workers compensation texas` 1.
- No "show more" button yet - offered to the owner.


### 10.19 Live test findings (owner's localhost test, 3 Nov 2026 - package `93646570`, Choice Electric, 7 decs)
| # | Sev | Finding | Cause | Fix | Status |
|---|---|---|---|---|---|
| L-1 | LOW (looks broken, works) | Arriving on "Select Forms to Generate" from the pre-form screen's "Skip to form selection", the search bar appeared about a second AFTER the screen and pushed the recommended list down (owner, 16:04) | `AcordModal` asks the server whether the feature is on for this user (`GET /api/asg-forms/search?q=`) only when the form selection step opens, and draws the bar only after the answer. The answer passes the login check against the shared database (~0.5-1 s locally, slower while the suite runs on the same Mac) | Ask once when the package opens (the user is still on the review pages), keep the answer, refresh it quietly on form selection - the bar is there on arrival. Frontend only, one effect. | FIXED 16:27, with L-2 / L-3 (the owner asked for fixes) - the switch is asked once when the package opens and refreshed quietly on form selection - **VERIFIED LIVE by the owner (16:50)** |
| L-2 | MEDIUM | A PRIMBLE form (one of our 17) picked in the search was listed under "Additional ACORD forms" (owner, 16:27) | `addSearchedForms` put every pick in the added list; that list is for ACORD Solutions forms | Owner's rule: our form is just ticked where it normally sits - in its tier when recommended, else in "Add more ACORD forms", which OPENS by itself so the tick is seen. Only ASG forms go under "Additional ACORD forms" (`addedShown` ASG only; the browser-saved list keeps ASG forms only and forgets an old list holding only ours) | FIXED 16:27 - **VERIFIED LIVE by the owner (16:50)** |
| L-3 | LOW | While searching, "Back to review" and a greyed "Generate N Forms Now" (+ "Press Done ...") stayed at the bottom; the X to leave the search showed only on hover (Chrome's own) (owner, 16:27) | the footer was drawn whatever the step's state; the clear button was the browser's | While something is typed the footer is hidden. Our own X sits in the box whenever it holds text (the browser's is hidden), and Esc does the same: both clear the search and bring the list and the buttons back. Ticks not yet added with Done stay listed (Done / Untick all), as F-5 decided | FIXED 16:27 - **VERIFIED LIVE by the owner (16:50)** |
| L-4 | HIGH (wrong value) | ACORD 807 (a D&O section) printed INSURER = "AMERISURE INSURANCE COMPANY" - the package's main carrier; the D&O coverage part sits on the Federal Insurance (Chubb ForeFront) policy (Claude's check, 16:50) | An ASG form has NO LINE identity: our section forms resolve the insurer / NAIC / policy number from their own line (`_SECTION_FORM_LINE_PHRASES` -> `_resolve_section_policy_identity`, right-or-blank); an ASG form falls to the package header rule, which owns the policy number and NAIC but NOT `Insurer_FullName_A` - so the generic rule stamps the package `carrier_name` | Give every ASG form the line its TITLE names (the line canon knows D&O, EPL, cyber ...) through one accessor used by the section-identity and scoped-evidence doors (20 call sites); a title naming no single line = package-level, insurer printed only when ONE company writes every policy (Brent's 8 Oct rule for the 125) | **DEFERRED by the owner (17:05): "we can worry about the accuracy of the forms later on, as said by Brent".** Caveat logged: Brent's 10-30% is MISSING data; this is a WRONG value - fix before the PROD credentials go live (until then every form says "Sample") |
| L-5 | MEDIUM (wrong value) | ACORD 807 printed "Cyber Incident Response Team" as an attached section (`Policy_SectionAttached_OtherSectionDescription_B`) - a coverage part of the separate CYBER policy (Claude's check, 16:50) | Same root cause: with no line, `scoped_evidence.foreign_policy_text` cannot tell another policy's text from this form's (its sibling "Commercial Automobile Coverage Part" was caught by `LOB_NAME_OUT_OF_PLACE`). The right values are this policy's own parts (its Item 4: EPL, Fiduciary, Crime, K&R, Employed Lawyers, Workplace Violence) | the L-4 fix | **DEFERRED by the owner (17:05): "we can worry about the accuracy of the forms later on, as said by Brent".** Caveat logged: Brent's 10-30% is MISSING data; this is a WRONG value - fix before the PROD credentials go live (until then every form says "Sample") |
| L-6 | MEDIUM | A word + a state typed by its NAME found nothing: "auto texas" = 0, while "texas" = 22 and "137 texas" = 2 (Claude, checking search counts for the owner, 17:05) | `_parse_query` turns "texas" into "tx"; the fresh review's rule (R9-4: a bare two-letter word beside other words is a word, "id" in "id card") then made it the title word "tx", which no title holds | `asg_forms._named_state`: a state typed by its full name always filters (a form whose title names the state also matches); bare two-letter words keep R9-4. "auto texas" / "texas auto" = 7, "new york auto" = 7; "id card", "137 tx", "TX", "texas", "137" unchanged. Test added; ASG tests 108 / 108; backend restarted 17:05 | FIXED 17:05 |

### 10.20 First live generation with an ACORD Solutions form (3 Nov 2026, 16:22:49-16:24:00 IST) - PASSED
Package `93646570` (Choice Electric, 7 decs, localhost); the owner generated ONE form, **ACORD 807 - Directors &
Officers Liability Section** (its D&O data is on the Chubb / Federal Insurance management liability dec).

**ACORD Solutions:**
- 1 sign-in + 1 download - the feature's first real calls;
- `ASG_FORM_DOWNLOAD form=807 edition=latest bytes=211365 seconds=24.2`, edition read off the PDF: 2016/03;
- `ASG_SAMPLE_FORM` logged (UAT credentials - expected).

**Fill - the same pipeline as our 17:**
- 270 boxes; 6 by rules, 227 to the shared AI gap fill;
- AI calls: 12 gap fill + 3 Y/N (compliance) + 2 evidence judge = **17 calls**. Input 401k tokens, 76% cached; output
  5.3k tokens;
- **50 values printed. 98 AI values thrown out by the generic guards** (`GUARD_BLANKS count=98`), among them:
  - the owner's own name - the PRODUCER, from the login - as the insured's director / officer (`DROP_FOREIGN_ENTITY`);
  - the three carriers as additional interests (`insurer_as_party`);
  - a $10,000 deductible as a limit (`meaning-gate`);
  - an 80% shareholding no document states (`UNSTATED_PERCENTAGE`);
  - "Commercial Automobile Coverage Part" as an attached section (`LOB_NAME_OUT_OF_PLACE`);
  - policy boilerplate in name boxes (`boilerplate_bleed`) and copied rows (`row_dedup`);
  - 2 Yes / No answers the judge refused.

  On a form Primble has never seen, the protections hold: blank over wrong.
- Package score after generation: 42 (Not Ready) - the package's own number; forms do not move it.

**After generation:**
- editor boxes, PDF, reload and the package download (through the download review) were all served from the stored
  copy;
- **0 further ASG calls, 0 errors** (D-ASG-11 holds live).

**Still to see on screen (owner):**
- the "Sample" note;
- the values - the D&O limits / retentions against the dec. "Requested" columns copied from the current policy would
  be an assumption to flag;
- the endorsement rows and their ticks.

**Claude's own checks after the owner's steps (16:50) - no database or ASG access, the backend log + the owner's downloaded files only:**
- **The downloaded ACORD 807** (copied to the scratchpad and read there):
  - 3 pages, 270 boxes, 52 values: the 50 from generation, the owner's edit, and the form's own pre-printed edition box;
  - no internal `/PrimbleBlankState` left in it;
  - the "Sample" images on the pages;
  - **the encrypted Primble record in the document info** (`enc:`, 11 KB);
  - the package ZIP holds the same file.
- **Where the 50 printed values came from:**
  - 6 straight from the extracted facts by our rules (insured name, producer, insurer, the two policy dates, the
    completion date);
  - 44 from the AI gap fill.
- **The stored copy is in the DATABASE, not just in memory.** The in-memory copy is filled ONLY from a database read
  (`session_repository._session_from_db` / `_attach_asg_base_rows`), and the editor drew 807 right after generation -
  so it survives a restart / deploy.
- **The D&O limits being blank is RIGHT.** The Chubb ForeFront dec lists 7 coverage parts (Item 4) but prints only the
  EPL part's numbers ($1,000,000 aggregate "shared with" D&O / Fiduciary / Employed Lawyers, $10,000 retentions,
  03/01/2022). The AI copied those EPL figures into the D&O boxes, and the guard refused them, 23 times
  (`DROP_MISPLACED: NOT_THIS_COVERAGES_EVIDENCE`): no document states a D&O limit.
- **Two wrong values found - L-4 (the insurer) and L-5 (another policy's coverage part), 10.19.**
- Still exactly 1 ASG call and 0 errors.

**Still to run (optional):** Sign on an ASG form; a certificate (ACORD 27, T10). Edit + save + reopen and both downloads PASSED.

### 10.21 Search sweep - "type keywords and find all such bugs" (owner, 3 Nov 2026; finished 17:23 IST) - FIXED
**Method (offline, no ASG call):** a harness in the scratchpad (`anyform/search_sweep/`) typed every one of the 1,174
forms the ways people type them, then about 150 real-world words, then junk:
- by number; "ACORD-n";
- number + state code / state name, in both orders; squashed ("137tx");
- its variant code;
- its full title, as printed and in lowercase;
- its title words + its state name or code;
- about 150 real-world words and abbreviations;
- 3,000 random junk strings.

**Bugs found - six classes, all fixed in `asg_forms` (`_parse_query`, `_search_readings`, `_term_in_title`,
`_matching_forms`, `search_full`):**
1. **Variant codes ignored** - "137 tx ins", "125 cis", "1 ins" found nothing (53 of 65 variants). Now the typed code
   selects the variant and puts it first.
2. **Punctuation inside a word** - apostrophes / "&" / "?" broke matching ("workers' compensation", "employer's ...";
   113 full titles failed). Every mark now separates words exactly as in the titles. "D&O" / "E&O" / "P&C" are one
   word, and also match the spelled-out words.
3. **Plurals** - "binders" / "certificates" / "drivers" = 0; "claims" 3 vs "claim" 9. A plural is read as its stem.
4. **A state code beside words** - "ny auto" / "auto ny" / "wc ny" / "ca gl" = 0. The code is read BOTH ways (a state
   filter, or a word as in "id card"), and both readings are shown.
   - Small words never block: "auto in texas", "auto for texas", "directors and officers".
   - Two states: "texas or oklahoma".
   - Run-together names: "newyork".
5. **Misspelling / edition** - "accord 25", "ACORD 25 2016", "25 (2016/03)" = 0. "accord" is ignored like "acord";
   an edition typed after the number is ignored.
6. **Shorthand** - cgl / bop / epli / epl / d&o / dno / e&o / "workmans comp" / trucking found nothing.
   - They now match the words they stand for, OR themselves exactly when a title prints them ("FORM K-WC 113").
   - "gl" is never a prefix (no "glass").

**Widening, always said on screen (`note` in the API reply, shown above the results by `AcordFormSearch`):**
- A number inside a title ("ho 4", a title quoting "ACORD 60 MA") - searched as a title word.
- No version for the state ("gl ca", "notice of cancellation georgia") - the GENERAL forms only, never another state's:
  "No California version found - showing the general forms."
- No form holds every word ("texas auto id card" - the Texas card's title is "TEXAS LIABILITY INSURANCE CARD") - the
  forms holding the most: "No form matches every word - showing the closest matches." The same for a number plus a
  stray word ("137 xx").
- An exact search is never widened.

**After:**
- Every check: 0 failures across about 9,000;
- the 3,000 junk strings: 0 crashes;
- 1-20 ms per search;
- ASG tests 131 / 131 (23 new, including one that walks all 1,174 forms and one junk test);
- frontend build clean;
- backend restarted 17:23.

**Left as they are (correct):**
- Words no ACORD title holds: malpractice, fidelity, kidnap, ransom, pollution, environmental, habitational, audit,
  sov, hnoa.
- Numbers that do not exist; "acord" / "form" alone; junk.
- Three numbers whose plain form is a Life form (66, 661, 703) list their P&C state versions first - P&C before Life
  is the rule.

**For ASG - their list contradicts itself:** "ACORD 63 OK" is titled "Ohio Fraud Statement" and "ACORD 136 OH" is
titled "Missouri Commercial Auto Coverages/Limits Section".

### 10.22 Is the form ASG sends always the one we asked for? (owner, 3 Nov 2026; answered + built 17:34 IST)
**The keyword is never sent to ASG.** Search reads our list. At Generate we send each PICKED form's identity:
- `formNumber`;
- `geoCode` = its state code;
- `geoCodeSuffix` = its variant code;
- `latestEdition=true`.

**What was proven vs not, before this change:**
- **Proven live:** plain forms - 27, 75, 130 latest, 130 @2017/09 (the PoC) and 807 (the live test). One state version,
  137 CA (PoC). An unknown number answers "Invalid Form", and nothing is generated.
- **Not proven:**
  - the other state versions - the same `geoCode` parameter, so very likely fine;
  - the **65 variants** (INS / CIS / ONI / PCIS / HAZ / C / S / API / ARI / CLAP / COV / IS / LOB / PCS / PLSS). ASG's
    download documentation says the service picks a form by "Form Number, Geocode, Geocode suffix and Edition", but its
    parameter table names only `formNumber`, `geoCode` and `edition`. **The variant parameter's name is our guess**
    (`geoCodeSuffix`). If ASG ignores it, it sends the PLAIN form, and we used to fill that under the variant's name;
  - whether every listed form HAS a fillable version - ASG says "This form has no acroform PDF for download", and we
    show "no fillable version ... remove it". Nothing is generated.
- **Nothing checked that the PDF returned IS the requested form.**

**Built (17:34) - `asg_forms.identity_check` on every network download, inside `fetch_blank`:**
- Every ACORD form prints its identity in its footer - "ACORD 137 CA (2023/01)", "ACORD 27 (2016/03)" - checked on all
  17 of our templates, on ASG's own ACORD 27 and on the owner's ACORD 807 download.
- A download is used only when its footer names the requested number, its state code for a state version, its variant
  code for a variant, and no state code on a plain form.
- Otherwise: refused (`ASG_FORM_MISMATCH`), remembered 6 h (no repeat calls), nothing generated, and the screen says
  "ACORD Solutions sent a different form than ACORD X, so it was not used - remove it from your selection."
- A footer that cannot be read is used, but logged `ASG_FORM_IDENTITY_UNREAD`.
- The test stubs (our forms standing in for ASG's) skip it.

**Tests:**
- all 17 templates accepted against themselves;
- 4 mismatches refused: another state, a state version for the plain form, the plain form for a variant, another
  number;
- the refusal remembered with no second call, and the message;
- ASG tests 137 / 137; name guards green; backend restarted 17:34.

**So now:** a wrong form can no longer be filled silently - every form is the requested one, or it is refused. The
variants are still UNPROVEN: they will be refused if ASG ignores `geoCodeSuffix`.

**To settle it:**
1. One verification run with the owner's yes - about 6 calls: two variants (125 CIS, 25 INS), two state versions
   (137 TX, 50 NY), two plain forms - with this check on.
2. Ask ASG: the exact name of the "geo code suffix" parameter, and whether every form on their supported list has a
   fillable (acroform) version for download.

---

### 10.23 Hard review of everything since the 800+ forms build (owner, 3 Nov 2026; pass 1 fixed 22:46 IST)
The owner asked for a hard reviewer over the post-ASG work, and passes "until it is clean". Pass 1 found 17; all fixed
and pinned by tests. The search part:
- A state code beside words matched OTHER states by prefix: "commercial auto al" found Alaska's forms ("al" as a
  word prefix). A code read as a word is now matched only as that exact word (`=al`).
- A small word typed beside a number was a state filter: "137 in tx" filtered on Indiana as well as Texas. Small words
  ("in", "or", ...) are dropped as filters when another state is typed (`_effective_codes`); typed alone they stay states.
- "virginia" matched West Virginia's forms (`_title_names_state` removes the longer state names first).
- Our 17 forms ranked below ASG's copies on a word search ("commercial auto" put ACORD 163 ahead of our 137s): ours now
  take an 8-point lead (`_NOT_OURS`).
- "125 126" found nothing (several numbers = each one listed); "washington dc" read as Washington state (`_STATE_ALIASES`).
- "id card" read "id" as Idaho: a code that is also everyday shorthand (id, ins) is first read as the word; "25 ins"
  still gives the INS variant first (a variant code beside a NUMBER takes the lead).
- Checked and left: "auto ins" lists the INS variants first (titles holding both words); a life / annuity plain form
  ranks below a state's P&C version for its number (P&C first, by design); ACORD 63 OK's catalog title says "Ohio"
  (ASG's data).
Tests: `tests/test_asg_forms_3nov.py` (141). Sweep re-run: every form findable by number, number + state, title.
Pass 2 (23:23 IST, a fresh reviewer): a typed state still widened to every state in the "closest" fallback ("tx auto
id card"), "id" beside a state filtered on Idaho (now "id" = identification OR insurance card), "125 tx" listed other
states' 125s (now the general forms + "No Texas version found"), "texas tx" found nothing (a code repeating a named
state is dropped), "washington d.c." read as Washington state. All fixed; `_split_codes` decides once which typed codes
are states. Tests: 155 in the file.
Form selection: after generation the added-forms list was forgotten in storage but kept on screen, so the next tick
wrote it back - now emptied too. Captcha, SMS, client IP and the document alert fixes: `OPEN_ITEMS.md` "In progress".

### 10.24 Brent's answers, 4 Nov 2026 (built 00:07 IST)
- **"Please show only the P&C forms, not the others."** The search lists P&C only: ACORD's Life, Annuity & Health
  numbers (650-799, 950-999 - every 7xx is a life application, examiner report, replacement notice or group-benefit
  proposal; 951-969 are 1035 / annuity forms) plus the title words in `_NON_PC_TITLE_RE`. `asg_forms.is_pc_form`;
  generation refuses a non-P&C ASG id.
- **"Let's limit each package to 15 forms (total ASG or Primble combined)."** `asg_forms.max_forms_per_package()`
  (`PACKAGE_FORMS_MAX`, 15) and `package_form_count` (distinct base forms; an umbrella layer copy is one form) - held
  at select-forms-bulk, at resolve-issue `add_form`, in the search (no 16th tick) and on Generate. The message names
  support@primble.ai for an upgrade. `ASG_FORMS_MAX` (8) still limits ASG's share.
- ASG: Brent wrote to them about the login / API / "Sample" watermark.
- Pass 3 of the hard review (4 Nov): "130 in" / "or auto" (a small-word state), "28 ny" hiding ACORD 28 behind ACORD
  283 NY, "877 california" ranking the "(except California)" form first - fixed; tests 167 in the file.

## 9. Log
- **30 Oct 2026, 16:06 IST** - first analysis (sections 1-7), no code.
- **3 Nov 2026, 03:15 IST** - Brent's three e-mails recorded (0a). Kit measured: every box is its e-label,
  Mapping List on all 15, only the 130 edition differs from ours (8.2). Fill measured offline on Orbin
  `b8d6` with no AI (8.3). ASG docs re-read: Download API is the template source, no catalogue endpoint, the
  supported-forms page needs the portal login (8.5). No code changed (owner: MD files only).
- **3 Nov 2026, 03:25 IST** - read-only code map added (8.4): no allow-list exists; four blockers (session form
  snapshot, add-form gate, `form_name` key, the 0% extra-forms list) and five side effects (schema folder, header
  identity on single-line forms, edit write-back, per-form score, edition glob). Checked: ASG's downloaded
  template has plain e-label box names and no XFA, same as our 17; the kit's AdobeFillable files carry XFA -
  use the `EForms/... Acroform.pdf` copies or ASG downloads.
- **3 Nov 2026, 03:30 IST** - the owner's on-demand flow analysed (8.9): it works with today's pipeline; no
  per-form mapping (e-labels are the map); keep copies only of forms users pick; search by number needs no ASG
  list; Brent's "six base forms" explained. Three owner decisions listed in 8.9.
- **3 Nov 2026, 03:41 IST** - owner's rules (8.10): ASG forms are never stored, and are treated exactly like our
  own forms (AI fill, hard stops, missing values). Evidence that ASG provides the integration collected (doc,
  credentials, the 29 Oct call, our client). Proof-of-concept script written in the scratchpad, NOT run (owner
  runs ASG calls). The kit folder explained in plain words (1b).
- **3 Nov 2026, 11:20 IST** - Brent's production go recorded (owner). Six new ASG documents read (8.11): the
  supported-forms list (316 numbers / 1,199 with states / 3,881 editions), the ACORD Forms page (any form, any
  edition, portal search + Postman button), the dashboard (4,164 downloadable versions), error replies, Converter
  (IP whitelisting). Final step-by-step plan written (8.12) with the owner's step-0 inputs. No code changed.
- **3 Nov 2026, 11:35 IST** - PoC run with the owner's yes, 7 ASG calls (cap 7): ACORD 27, 75, 137 CA, 130 latest
  (= 2026/08), 130 @2017/09 all downloaded and filled with no AI; 9999 -> 400 "Invalid Form"; 4-10 s per form,
  22 s cold (8.13). Owner's decisions recorded (8.14): search list yes, search bar + side notice on form selection,
  blank form never stored but the FILLED copy stored per package, our 17 stay ours, a per-user form cap, spinner.
  Owner's questions answered (8.15). No repo code changed.
- **3 Nov 2026, 11:58 IST** - owner reviewed the PoC (8.16): "Sample" watermark traced offline to an image ASG adds
  on every UAT download (not our fill) - PROD credentials needed for clean forms; search list made refreshable +
  number fall-through; search UI defined (results only while searching, Done, picked forms at the bottom under
  their own heading); filled copy confirmed per package; ASG call rule (server yes, Claude ask); Render's
  Transcriber variables enough technically but UAT; IPs settled (India + USA); cap 8. Five Brent questions listed.
- **3 Nov 2026, 12:05 IST** - watermark confirmed offline (8.17): the extra page picture on every ASG download is the
  word "Sample"; Brent's ACORD kit and our 17 templates have none; no ASG doc mentions it. Three ways to test for
  clean forms listed (owner portal download; `orgId` / `userId` on the download; Population) - each waits for the
  owner's yes. Brent question sharpened. Verdict: ready to BUILD; the watermark blocks only the customer launch.
- **3 Nov 2026, 12:13 IST** - the portal's forms-download Postman file read (one download request, no search, no
  `orgId`); `orgId` is for custom forms, so UAT is the likely watermark cause; portal steps to settle it with no API
  call listed (8.18).
- **3 Nov 2026, 12:20 IST** - watermark settled (8.19): the owner's hand download of ACORD 27 from the UAT portal
  carries the same "Sample" picture; UAT profile = organisation "Primble", role User; the production portal refuses
  the login (no PROD account); P&C = 3,821 of 4,164 versions. Brent questions 1 and 2 reworded with these facts.
- **3 Nov 2026, 12:32 IST** - Brent e-mail finalised by the owner: (1) production account - "Sample" is MAYBE caused
  by our UAT account; can ASG set us up with production; (2) scope (P&C 3,821 of 4,164); (3) should extra forms be
  limited, and to what number. DROPPED from the e-mail: the forms-list question (we already hold ASG's supported
  list, 3,881 rows - we build the search list ourselves and refresh it from the portal / list; no ASG ask) and the
  ACORD 130 edition (owner: if all forms are integrated through ASG we may move the 17 to ASG later too - ask the
  owner first; not now).
- **3 Nov 2026, 12:38 IST** - owner's proposal agreed (8.20): build and test on UAT "Sample" forms now, switch to PROD by
  environment variables only; the feature stays owner-only until PROD; packages made on UAT are regenerated after;
  a "Sample" check logs every download; one owner-approved PROD test call after the switch.
- **3 Nov 2026, 12:49 IST** - BUILD STARTED (owner's go). Design decisions D-ASG-1..10 and the step table in section 10.
- **3 Nov 2026, 12:56 IST** - steps 1-2 done: search list (1,186 forms) and `services/asg_forms.py`; the stored-copy
  promise measured exact on all 17 templates (10.3; two defects fixed). Brent's production-licensing news logged
  (10.4). Next: step 3, the template door.
- **3 Nov 2026, 13:05 IST** - steps 3-8 built (10.5 backend, 10.6 frontend); new tests 42 of 42 green (stub only);
  frontend build clean. Related existing suites and the full suite next. No ASG call made.
- **3 Nov 2026, 13:09 IST** - checks (10.7): offline end-to-end OK; related suites 924 / 1 (a guard caught the stub's
  file path - code fixed, green); full suite started.
- **3 Nov 2026, 13:17 IST** - owner asked for strict reviews: three read-only reviewers started (functionality vs the
  owner's spec + no change to our 17; an adversarial breaker; the frontend search screen). Findings and fixes will
  be logged in section 10.9. Full suite still running.
- **3 Nov 2026, 13:38 IST** - review round 1: 1 critical, 4 high, 5 medium, 4 low backend + 2 high, 3 medium, 7 low
  frontend findings - all fixed or logged (10.9, D-ASG-11). 59 / 59 + 925 / 925 green. Round 2 next.
- **3 Nov 2026, 14:01 IST** - review round 2: 1 high, 3 medium, several low - all fixed (10.10); owner question O-ASG-1
  (values kept in the stored copy); `git add` list for the new files. 67 / 67 + 925 / 925. Round 3 next.
- **3 Nov 2026, 14:16 IST** - review round 3: 2 medium + 6 low (pre-download hardening, frontend polish) - all fixed
  (10.11). 73 / 73 + 1,158 / 1,158. Round 4 next.
- **3 Nov 2026, 14:30 IST** - review round 4: frontend clean (no new findings); backend 1 medium + 3 low fixed (10.12).
  76 / 76; 1,234 / 1,234. Round 5 (the two backend reviewers) next.
- **3 Nov 2026, 14:34 IST** - review round 5: 2 low + 1 cosmetic fixed (10.13). 79 / 79. Round 6 next.
- **3 Nov 2026, 14:37 IST** - review round 6: functionality clean; breaker 1 low fixed (10.14). 80 / 80. Round 7 (breaker) next.
- **3 Nov 2026, 14:40 IST** - review round 7: 2 low fixed (10.15). 82 / 82. Round 8 next.
- **3 Nov 2026, 14:41 IST** - review round 8: BOTH backend reviewers report NO new findings (the frontend reviewer had
  none since round 4). The review loop is closed after 8 rounds. Next (owner's process): one fresh general reviewer
  for "does everything work together", then the full suite.
- **3 Nov 2026, 14:43 IST** - owner asked for one more reviewer: a STRICT end-user overwatch (a random producer on a bad
  day, every journey and worst case). Running alongside the general reviewer. Owner rule: ask before running the full
  suite.
- **3 Nov 2026, 15:00 IST** - final reviews (general + strict end-user): 3 high, 7 medium, several low - all fixed
  (10.16); 10.0 "current state" added at the top of section 10; CLAUDE.md, ASG_TRANSCRIBER.md, improving-ll.md (C113)
  updated. ASG tests 100 / 100. Next: related suites, then the full suite ON THE OWNER'S YES.
- **3 Nov 2026, 15:10 IST** - after the final-review fixes: the ASG tests plus every related file (certificate rules,
  proposed-term rule, Primble record, ACORD intake / round trip, downloads, signatures, needs-attention, run state,
  multi-user, Stripe review) - **1,998 passed, 0 failed**. Waiting for the owner's yes to run the full suite.
- **3 Nov 2026, 15:28 IST** - owner: "go follow the steps" - (1) one FRESH reviewer, scoped to the changes made after
  round 8 (the final-review fixes) and their regressions; (2) if clean, no more reviews: the full suite; (3) then the
  owner's localhost test with real ASG / AI calls (10.8).
- **3 Nov 2026, 15:41 IST** - fresh review of the final fixes: 4 medium + 3 low + 1 design item, all fixed (10.17).
  107 / 107. Full suite started (owner's go).
- **3 Nov 2026, 15:49 IST** - local backend started for the owner's live test (owner: "run the backend, i want to
  test it on the localhost"):
  - `ASG_FORMS=1` given at launch only (`backend/.env` untouched);
  - no allow-list (development needs none); daily jobs off; `/api/health` healthy;
  - the full suite keeps running alongside (3 shards).
- **3 Nov 2026, 15:52 IST** - the owner opened the app locally (Google login, dashboard, one package). No ASG call.
  The backend log shows `FIELD_ENCRYPTION_KEY mismatch` while reading that package. This was already the case before
  this feature: localhost and primble.ai share the database but not the encryption key. The test plan now says to
  use a package uploaded on localhost.
- **3 Nov 2026, 15:58 IST** - owner: "update md files properly and live test is still remaining". Done:
  - section 0 rewritten - it still said "nothing built";
  - 10.0 / 10.2 / 10.8 brought up to the current build; D-ASG-7 (fail closed) and D-ASG-10 corrected;
  - the test plan rewritten: 15 steps with a Result column, its search and certificate expectations checked offline
    against the code (no ASG call);
  - CLAUDE.md, ASG_TRANSCRIBER.md, improving-ll.md (C113) and the memory now say "live test remaining".

  Suite at 15:58: shards at 71 / 60 / 80%, with one F where the known `test_arq_acord125_missing_only` runs - to
  confirm when it ends. **Live test: REMAINING.**
- **3 Nov 2026, 15:53-15:59 IST** - the owner uploaded the Choice Electric package on localhost (7 decs: auto,
  cyber, EPL, excess, package, umbrella, WC). Package `93646570`:
  - 0 errors, 0 ASG / Transcriber calls (no ACORD pages in it);
  - 11 extraction calls (181k in, 133k cached, 57k out);
  - 7 forms recommended (125, 126, 127, 130, 131, the excess 131, 140).

  Four of the seven extraction replies were flagged "CUT OFF" at 3.7k-8k output tokens - far under the 32k cap - and
  retried once each. That is the false cut-off flag the owner PARKED on 30 Oct (memory `extraction-cutoff-continue`),
  not this feature: about 4 extra calls and about 80 s on this upload; the first replies' 203 keys were kept.
- **3 Nov 2026, 16:02 IST** - owner: "can i search the forms directly from the asg or not?" - **NO.** ASG has no
  search or list API (3 Postman collections, 8 requests: download / extract / populate; the portal's search is a web
  page). Our search box searches ASG's own published list; only the download goes to ASG. Two options logged, neither
  built: the exact-number check button, or asking ASG for a list endpoint (10.18). **Live test: REMAINING** - the
  owner is on the package's review page.
- **3 Nov 2026, 16:04 IST** - live test T1 PASS, with one finding: the search bar appears about a second after the form
  selection screen and pushes the list down (L-1, 10.19 - fix after the test). The owner searched "12", "125", "8",
  "80", "800"; every search answered 200 with no ASG call.
- **3 Nov 2026, 16:15 IST** - **full suite done (15:41-16:11): 22,751 passed, 2 failed, 46 skipped.**
  - `test_arq_acord125_missing_only` - the known failure.
  - `test_ui_items_16_17_19_9oct` - the TEST pinned the form screen's old text (`resetFormTicks` on one line; two
    inline `checkedFormsForReview` calls) that F1 and R2-8 changed on purpose. Updated to pin the behaviour; that file
    + the ASG tests 123 / 123.

  No code changed for it. CLAUDE.md's suite baseline updated. **Live test: still running** - the owner is on form
  selection; no generation yet.
- **3 Nov 2026, 16:27 IST** - owner's live test, form selection (screenshots): T2-T6 PASS (searches, tags, totals, Done, Remove, the generate note). Two issues FIXED (10.19), plus L-1 (the late search bar):
  - L-2: a Primble form picked in the search is ticked in its own place, and "Add more ACORD forms" opens;
  - L-3: no Back / Generate while searching; our own X (and Esc) clears the search.

  Frontend only (`AcordModal.jsx`, `AcordFormSearch.jsx`, `App.css`). Build clean; the 8 files that read this screen
  + the ASG tests: 296 / 296. **Live test continues** - next: Generate (T9).
- **3 Nov 2026, 16:33 IST** - **first live generation with an ASG form PASSED** (ACORD 807, 16:22:49-16:24:00, about
  71 s):
  - 1 sign-in + 1 download (24.2 s, "Sample" logged);
  - 17 AI calls; 50 values printed and 98 impossible AI values thrown out by the guards - including the owner's own
    name as the insured's officer;
  - editor, reload and the package download served from the stored copy, 0 further ASG calls, 0 errors.

  T9 / T14 PASS, T12 / T13 partly, T10 / T11 not run (10.20). Left: edit / save, Sign, the one-form download, a
  certificate.
- **3 Nov 2026, 16:50 IST** - the owner VERIFIED LIVE: L-1, L-2, L-3; the ASG note on 807; edit + save + reopen; the
  one-form download.
  - Claude's checks: the downloaded file is complete (the record is in, no internal markers); the stored copy is in
    the database; the D&O blanks are right; 6 values by rules, 44 by AI.
  - TWO WRONG VALUES on 807: L-4, the insurer = the package's main carrier; L-5, another policy's coverage part.
  - Root cause: ASG forms have no line identity. Plan in 10.19, proposed to the owner.
- **3 Nov 2026, 17:05 IST** - owner: form accuracy later (Brent) -> L-4 / L-5 DEFERRED, with the caveat logged (fix
  before PROD). Answered:
  - no ASG list API exists - ask ASG for one, refresh by hand meanwhile (10.18);
  - what "a form added later" means;
  - how the top 25 works, with test words.

  Checking those counts found L-6 ("auto texas" = 0) - FIXED, test added, 108 / 108, backend restarted.
- **3 Nov 2026, 17:23 IST** - owner: "check the search box ... find all such bugs". The search sweep (10.21): 6 bug
  classes fixed (variant codes, punctuation, plurals, a state code beside words, misspelling / edition,
  shorthand), plus the three widenings with an on-screen note.
  - 0 failures across about 9,000 checks; 0 crashes in 3,000 junk strings; 1-20 ms per search;
  - ASG tests 131 / 131; frontend build clean; backend restarted.
- **3 Nov 2026, 17:34 IST** - owner: "with the keyword we send it to ASG it matches always and is correct, are you
  sure?" - NO, not for every form (10.22). Proven: plain forms + one state version. Unproven: the variant
  parameter, which is our guess. BUILT the footer identity check: a download that is not the requested form is
  refused, never filled. 137 / 137; backend restarted. Verification run (about 6 calls) waits for the owner's yes.
- **3 Nov 2026, 17:37 IST** - owner: wait for Brent's production credentials - **the feature is PARKED: done on UAT,
  not committed.**
  - Sections 0 / 10.0 / 10.8 / step table rewritten to the final state.
  - Owner's instruction recorded (here + memory `next-asg-test-six-calls`): at his next test, ask him first to run
    the six verification calls.
  - Before commit: the full suite on the final code (his yes) + the git-add list.
  - Before PROD: L-4 / L-5.
- **3 Nov 2026, 22:46 IST** - hard review pass 1 (10.23): 17 findings fixed; pass 2 next.
- **3 Nov 2026, 23:23 IST** - hard review pass 2: 11 findings (search, alert, captcha, limiter, SMS) fixed; pass 3 next.
- **4 Nov 2026, 00:07 IST** - Brent's answers built (P&C only; 15 forms per package) + review pass 3 fixed (10.24).
- **4 Nov 2026, 00:24 IST** - review pass 4: the 15-form cap moved into the one add-form door (two routes bypassed it); P&C rule keeps the Extraordinary Life Circumstances supplements (166 hidden); layer copies count as forms; titles never borrow a state.
- **4 Nov 2026, 02:41 IST** - ASG PRODUCTION onboarding doc received (`Transcriber_Onboarding_AccountSetup_PRIMBLE_PROD.pdf`, Downloads, 02:33); the owner completes it first thing on 5 Nov. A production download (`template (2).pdf`, ACORD 144, 3 pages, 253 fillable boxes) has NO "Sample" watermark per `asg_forms.has_sample_watermark` (the 3 Nov UAT ACORD 807 reads True - the detector separates them). Next: production credentials into `.env` / Render, the six verification calls, one full suite, then the one commit + deploy.

### 4 Nov 2026, 11:38 IST - FIRST PRODUCTION CALLS (owner's yes: "a few, only those needed")
**Calls made: 21 HTTP requests in all** - 3 token, 12 form downloads, 1 extraction submit, 4 status polls (+ 1 token for
the poll run, counted in the 3). Transcriber pages read: **1**. Downloads: 12 (6 were spent by our own bug, below).
- **Form downloads (`/oauth/forms/download` on prod-api-v1) WORK on production** - the undocumented OAuth route is
  confirmed. BUT production sends the PDF **base64-encoded as text** (body starts `JVBERi0`, still labelled
  `application/pdf`); UAT sent raw PDF bytes. Our code took only raw bytes, so the first run of the 6 forms refused all
  six although ASG answered 200 (6 downloads wasted). Fixed: `asg_forms._pdf_from_reply` accepts both; test added.
- **The six verification forms (production, no "Sample" watermark on any):**
  ACORD 27 - right form, 2016/03, 1 page, 89 boxes; ACORD 75 - right form, 2016/03, 2 pages, 147 boxes;
  ACORD 137 TX - right STATE version (2015/12, 3 pages, 439 boxes) -> `geoCode` works;
  ACORD 50 NY - right form ("New York State Insurance Identification Card", 1 page, 9 boxes);
  ACORD 125 CIS - right VARIANT ("Contact Information Schedule", 1 page, 217 boxes) -> `geoCodeSuffix` works for CIS;
  **ACORD 25 INS - ASG sent the plain ACORD 25** -> our identity check refused it ("ACORD Solutions sent ACORD 25 instead
  of ACORD 25 INS"), as designed. Open: ask ASG how 25 INS is requested, or whether PROD has it.
- **Footer reader widened:** 50 NY prints "ACORD 50 NY (1/98)" and 125 CIS prints "APPLIED 125CIS (2009/08)" - both
  were right forms but unread; `_FOOTER_IDENTITY_RE` now reads ACORD or APPLIED and 1-4 / 2-4 digit dates. Test added.
- **Filled-ACORD reading (Transcriber extraction) WORKS on production:** page 1 of an outside-filled ACORD 137 TX
  (`~/Downloads/ACORD 137_TX (2015-12) Filled.pdf`, sent alone = 1 transaction): recognised as 137 TX 2015/12,
  accuracy 98, done in 21.2 s (1 submit -> 202, 4 polls at 3 s). Of 123 typed boxes it returned, 120 values match
  exactly; the 3 others: the hidden edition box, and two vehicle-table STATE boxes where Transcriber put rows A, B and
  C into row A ("KY OH TN") - a Transcriber quirk on repeated state rows, not ours.
- No usage was written to our database (the test ran the client without the usage hook). The local backend now runs on
  the production settings (restarted 11:38 IST).

### 4 Nov 2026, 12:12-12:15 IST - the owner's live localhost run on production keys (log `backend_local9.log`)
- **Filled-ACORD reading: PASS.** The fresh 137 TX test form (3 pages, no Primble record) ->
  `TRANSCRIBER_SUBMIT env=prod pages=3 label=137 TX`, `TRANSCRIBER_PRESUBMIT files=1 sent=1`, then
  `TRANSCRIBER_DONE status=done forms=['137-TXx3']`. 3 pages.
- **Generation of ACORD 101 + 25 INS + 137 TX INS:** 101 never went to ASG (our template); exactly 2 downloads (21.5 s
  and 25.0 s). **Both INS came back as the PLAIN form** (`ASG_FORM_MISMATCH ... printed='ACORD 25'` / `'ACORD 137 TX'`)
  - refused by the identity check, nothing generated (503, by design: ASG forms cannot be added later).
- **So the edition fix (variant_edition) did not bring INS:** ASG ignores `geoCodeSuffix=INS` (CIS worked with it this
  morning). ASG's download page names a separate "form source" parameter beside geo code / geo code suffix - INS is most
  likely a form source. **Ask ASG: the exact parameter (name + value) for INS forms.** The edition fix stays (harmless).
- Fixed after the run (12:22 IST): the download log printed `edition=latest` even when an edition was asked - now
  `suffix=... asked_edition=...`; the failure message read "so it was not used - remove them" for two forms - now
  "A and B, so they were not used". Tests 177 passed. Backend restarted (`backend_local10.log`), which also clears the
  server's 6-hour memory of the two refused forms.

### 4 Nov 2026, 12:29 IST - a form ASG refused is never asked for again (owner)
Owner: users would press Generate again and again on a form ASG answers wrongly and waste our ASG allowance. Built:
`asg_forms.remember_refused` / `refused_forms` - a form ASG answered with ANOTHER form (`wrong_form`) or with no fillable
version (`not_available`) is remembered for `ASG_REFUSED_DAYS` (30) in Redis (key `asg:refused:<form id>`, shared by
every worker, survives restarts; in-process fallback when Redis is down). `fetch_blank` answers a remembered refusal
WITHOUT calling ASG; the search marks the row `available: false` and the screen will not let it be ticked ("Not
available from ACORD Solutions - choose another form."). Passing problems (busy, timeout) still clear in minutes. No
database change. Tests 180 passed; frontend build clean. Local Redis seeded with the two forms refused in the 12:15 run
(25 INS, 137 TX INS) - no ASG call. On Render each refused form is learned at its first refusal (one call), then never
again for 30 days. To retry a form sooner (e.g. once ASG tells us the INS parameter): delete its Redis key.

### 4 Nov 2026, 12:36 IST - why INS forms do not download (investigation, no ASG call)
- **Our form list comes from ASG's "Supported ACORD forms" PDF**, whose own first line reads "ACORD Transcriber supports
  the following forms and editions for Extraction and Population." It is the list of forms Transcriber can READ / FILL,
  not the download catalogue. It writes variants as one name: `125_INS`, `125_CIS`, `1_CA`, `25_INS` (76 INS rows, 1
  CIS row, all on pages 58-59, no legend explaining INS).
- `build_asg_forms_index.py` split such names: a US state after the number -> `geoCode`; anything else -> our guessed
  `geoCodeSuffix`. The Download spec's parameter table lists only formNumber, orgId, geoCode, userId, edition (its prose
  mentions "Geocode suffix" and "form source" without parameter names).
- **Results:** geoCode (137 TX, 50 NY) -> right form; geoCodeSuffix=CIS -> right form; geoCodeSuffix=INS -> the PLAIN
  form (25, 137 TX), with "latest" and with the INS form's own edition alike. So "INS" is NOT the geo code suffix ASG's
  download service knows; an unknown suffix is ignored and the base form is returned.
- **Not known yet:** whether the INS versions exist in ASG's DOWNLOAD catalogue at all (the portal's Forms tab, 4,164
  versions, has a "Geo Code Suffix" column) or only in the extraction / population library.
- **Decisive check (owner, ~2 min, 1 download):** PROD portal -> Forms -> search 25 -> is there a row with an INS suffix,
  and what exactly does its "Geo Code Suffix" column say? If listed: open the browser's developer tools (Network tab),
  click its PDF, and read the request's parameters - that is the exact way ASG asks for it. If not listed: INS forms are
  not downloadable; hide them from our search.

### 4 Nov 2026, 12:52 IST - ASG's REAL download catalogue captured; the INS cause found (no ASG transaction)
- The owner captured the portal Forms tab's own list (`GET .../search?pageSize=5000&pageNum=0&geoCode=All`) ->
  `ASG_DOCUMENTATION/Prod-forms-download-catalogue.json`: 4,012 entries (1,162 distinct forms, every edition), each with
  number, name, edition, **geoCode, geoCodeSuffix**, title, source (all "ACORD") and **downloadInd** ("1" on 1,328
  entries = the downloadable editions, "0" on 2,682).
- **Cause of the INS failures:** 25 INS and 137 TX INS DO NOT EXIST in the download catalogue (25 has plain editions up
  to 2025/12, 25_GA, 25_FR, 25-S, 25_-N; 137 TX has only plain editions). ASG returned the plain form because there is no
  INS version to download. Only 16 INS entries exist anywhere, 2 downloadable (84 INS, 36 INS). Our search list came from
  the "Supported ACORD forms" PDF = what Transcriber can READ / POPULATE, which never marks downloadability.
- **Our list vs the catalogue:** 901 forms downloadable; our list 1,174; 866 in both; **308 in our list are not
  downloadable** (all 50 INS, 125 ONI / PCIS, 126 HAZ, 130 API / ARI / PCS, many state versions ...); **35 downloadable are
  missing** (plain 137 and 138, 25 GA, 200, 201, 212, 61, 62, 65, 38 CA / CT / IL ...); 57 have a newer downloadable edition
  than our list shows (130 -> 2026/08, 137 GA -> 2025/08 ...).
- Caveat: 125 CIS is not in this ACORD-source catalogue yet downloaded correctly (an Applied Systems form) - the
  catalogue does not cover every form ASG can serve; being in it as downloadable is the strong signal.
- **For later (not Friday):** ASG now offers newer editions of several of OUR 17 forms - 25 (2025/12), 125 (2025/03),
  126 (2025/03), 130 (2026/08), 133 (2025/05), 137 CA (2023/01), 131 (2017/11). The ACORD licence makes current editions
  Primble's responsibility - compare with our templates.
- Proposed: rebuild `forms_catalog/asg_forms_index.json` from this catalogue (downloadable editions only). Waiting for the
  owner's go.

### 4 Nov 2026, 12:55 IST - what the captured catalogue does and does not give us (owner asked "do we have everything?")
**The file:** `ASG_DOCUMENTATION/Prod-forms-download-catalogue.json` (5.4 MB, UTF-8). Captured by the owner from the
PRODUCTION portal's Forms tab (Chrome developer tools -> Network -> the page's own request
`search?pageSize=5000&pageNum=0&geoCode=All` -> Copy response; saved with `pbpaste`). No ASG transaction.
**Complete for ACORD forms:** 4,012 entries = exactly the "Showing 1-10 of 4012" the portal shows; 1,162 distinct forms
with every edition; per entry ASG's own number, title, edition, geoCode, geoCodeSuffix and download flag. No guessing of
which forms exist or of their codes any more.
**Catches:**
1. ACORD-source only (all 4,012 `source = "ACORD"`). Forms of other publishers ASG can serve are not in it (125 CIS -
   an Applied Systems form - downloaded fine on 4 Nov but is not listed).
2. `downloadInd` ("1" on 1,328 entries / 901 forms) is our reading, not documented: it fits the evidence (137 TX flag 1
   downloaded; 25 INS absent -> plain form). Prove both ways later with one or two downloads (a flag-0 form; 84 INS).
3. A snapshot of 4 Nov. The portal fetches it with the owner's LOGIN; whether our API keys may call that address is
   unknown - refresh = repeat the 5-minute capture (monthly), or ask ASG for API access to the list.
4. Non-state geo codes (FR, US, WM ...) and the two real INS forms are untested downloads.
5. It describes forms, not their boxes - boxes still come from the downloaded form (as now).
**Decision (owner, 12:55 IST): rebuild our search list from it** - downloadable forms only, ASG's own codes and newest
downloadable editions; keep 125 CIS (proven 4 Nov); leave untested non-state geo codes out for now.

### 4 Nov 2026, 13:04 IST - search list REBUILT from ASG's real catalogue (and a correction)
- **Correction:** `downloadInd` does NOT mean "cannot be downloaded" - ACORD 50 NY is "0" in the catalogue yet downloaded
  correctly from production at 11:38. The earlier "308 of our forms are not downloadable" leaned on the flag and was
  OVERSTATED. What the catalogue settles is EXISTENCE + ASG's own codes.
- **Rule now** (`scripts/build_asg_forms_index.py build_from_catalogue`): every form + US state + variant the catalogue
  lists (any flag), its newest edition, ASG's own geoCode / geoCodeSuffix; a state form ASG coded only in its NAME
  ("61_VA", empty geoCode) is kept with the state from the name when no properly coded entry exists; non-state geo codes
  (FR, US, WM, S, e) left out until one is proven; 125 CIS kept as proven (Applied, outside the ACORD catalogue).
- **Result:** `backend/forms_catalog/asg_forms_index.json` = **1,140 forms** (was 1,174 from the "Supported forms" PDF).
  **Dropped 72** that are NOT in ASG's catalogue at all (38 INS incl. 25 INS / 137 TX INS, 13 other guessed variants -
  ONI, PCIS, HAZ, COV, API, ARI, PCS, IS, S - plus life / annuity forms already hidden, Australia 3831, ACORD 601, the
  mis-titled 136 OH). **Added 38** (25 GA 2026/09, 130 OH / OK / OR / PA / PR / RI, 200, 201, 212, 1001-1003, 38 CA / CT /
  IL ...). Real INS forms kept: 84 INS, 36 INS, 143 INS ... Old list backed up in the scratchpad.
- Tests: 5 named 25 INS / 137 TX INS (the TEST was outdated - those forms do not exist) -> switched to 84 INS / 36 INS.
  `test_asg_forms_3nov.py` 180 passed; the 18 other files touching the feature 1,066 passed.
- Refresh: re-capture the catalogue monthly and re-run `py backend/scripts/build_asg_forms_index.py
  "ASG_DOCUMENTATION/Prod-forms-download-catalogue.json"`.

### 4 Nov 2026, 13:57 IST - full-feature review (owner: "check if everything is in and correct") - fixed
A fresh reviewer read the whole any-form feature + Transcriber reading (no ASG / network / database). Fixed:
- **B1 HIGH (deliverable 2):** `acord_intake/recognize._FOOTER_RE` read only "ACORD + 2-3 digits (YYYY/MM)", so an
  outside filled ACORD 1 / 2 loss notice, a 4-digit form (1001), an older "(1/98)" edition, an INS variant or an Applied
  form was never sent to Transcriber. Now every shape ("ACORD 1", "ACORD 84 INS", "ACORD 137 TX INS", "ACORD 50 NY
  (1/98)" -> 1998/01, "APPLIED 125CIS"); `footer_number` / `footer_edition` shared by recognize + `_plan_image`.
- **B2:** 7 state insurance cards (50 TX / AR / GA / IA / KY, 51 GA, 830) were not certificates (printed the PROPOSED
  term, carried the record, wrote the package term back) - `_CERTIFICATE_TITLE_RE` widened; exactly those 7 change.
- **B3:** the list offered forms with NO fillable file at ASG (130 OH / OK / OR / PA / PR / RI, 133 MT / NC, 1001-1003, 200,
  201, 66 AR, 7 INS ...): each would spend a call, get "no fillable version" and lock for 30 days. The builder now keeps
  only editions whose ASG file is `..._ACRO.pdf` (every form proven to download has one), newest such edition (141 INS
  -> 2003/07, 134 FL, 97 SC); empty titles borrow the plain form's. List: **1,116 forms**.
- **B4:** a plain request accepted a variant footer ("ACORD 163 INS") - refused now (`_VARIANT_CODES`).
- **B5:** after generation, a generated ASG form whose stored copy did not load was downloaded again by the gap fill -
  now only a first generation downloads (`elif _rec is None and _asg.feature_on()`).
- **B6 (edition half):** `pdf_service._form_edition_identifier` decided "ASG form" from the search list; a form a later
  rebuild drops would print one of OUR editions (ACORD 2 -> "ACORD 25 (...)") - now decided from our own list.
- **Withdrawn:** "variants ask for their listed edition" (built 11:53 on the wrong INS guess; a variant's listed
  edition often equals its plain form's). Variants ask for the LATEST again (proven for 125 CIS). New, narrower rule:
  plain 60 / 68 / 80 ask for their listed edition (`ask_edition`) - ASG filed newer state forms under those plain
  numbers with no state code.
- **Commit list corrected** (10.10): every untracked file, incl. captcha.py / document_fingerprints.py /
  TurnstileWidget.jsx / smsShare.js - the old list would have broken startup and the frontend build.
- Tests: `test_asg_forms_3nov.py` 186 passed (6 new); the 51 files touching the feature / upload reading 2,908 passed.
**Open, not fixed:** B6 certificate half (an already generated ASG certificate dropped by a FUTURE list rebuild loses
its certificate rules - decide from the stored record; low, only after a rebuild); first production call from RENDER
unproven (ASG IP allow-list); INS downloads unproven (36 / 84 / 139 / 141 / 163 / 829 INS - the six left in the list); L-4 / L-5 (now on real forms).
**Tell Brent (by design):** ASG forms cannot be added after generation; an outside
filled form's boxes with no fact behind them are not carried onto a generated ASG copy of that form.
- **4 Nov 2026, 14:26 IST - full suite on this code: 22,989 passed, 1 failed (the known `test_arq_acord125_missing_only`),
  46 skipped** (3 shards, 13:57-14:26). The local backend was restarted at 13:57 on the fixed code and the 1,116-form list;
  its log showed no ASG call and no error over the next 30 minutes. Nothing committed.
- **4 Nov 2026, 14:40 IST - the applicant's e-signature on ASG forms BUILT (was D-ASG-10; owner's ask, uncommitted).**
  Why it was missing: the line-finder read a template FILE from disk, and an ASG form has none (it is rebuilt in memory
  from the package's stored copy). Now `signature_boxes.applicant_lines_for(generated_form)` reads the lines the same way
  for both (an applicant SIGNATURE box whose printed cell label says SIGNATURE, its date paired by row), the ASG lines
  cached by the stored copy's SHA-256; `template_for` gives the render path or the in-memory bytes; `applicant_signing.
  signable_form_ids` uses the new door, so Send to Client pre-ticks the signature question for an ASG form. On 137 TX the
  three applicant lines (A / B / C) are signed and dated; initials and the producer's boxes are untouched. The producer's
  saved signature never goes on the applicant's line. Editor: the "not added" sentence removed, the "Sample" warning
  kept. Tests `tests/test_asg_signatures_4nov.py` (10). Live check on localhost: owner.
- **4 Nov 2026, 14:45 IST - related tests after the e-signature build: 3,230 passed, 0 failed, 15 skipped** (every test file
  touching signatures, applicant signing, ASG forms or the editor). Frontend build clean.

### 10.25 Live localhost test of the recent work (4 Nov 2026, started 14:54 IST - owner's go)
Plan: 15 checks; ASG budget = 4 downloads (137 TX, 25 GA, 60, 84 INS), 0 Transcriber calls; package from
`orbin_retest_kit/1_policy_package.pdf`. No ASG call beyond those 4 without the owner's yes.
- **14:56 - checks 1-3 PASS (no ASG call).** Search: life / annuity hidden ("life" finds only ACORD 66 "Extraordinary Life
  Circumstances" personal supplements - P&C), 25 INS / 137 TX INS gone, 212 title fixed, limit 15. Upload of the Orbin
  package: package `2f4ad0f4`, 90 s, no Transcriber call. 16 of our forms at Generate: refused (400, "A package can hold
  up to 15 forms ... would have 16"), nothing generated. **Found:** some ASG catalogue titles carry "?" for a lost dash
  (ACORD 66 "Personal Insurance Supplement ? Extraordinary ...") - fix in the builder, no call.
- **15:00 - Generate:** 4 ASG downloads, all production copies (base64 decoded, no "Sample"): 60 asked its listed edition
  2010/04 (34 KB), 25 GA latest (84 KB), 137 TX latest (319 KB), 84 INS latest (412 KB). **84 INS came back as the plain
  ACORD 84** (`ASG_FORM_MISMATCH printed='ACORD 84'`) - refused and remembered 30 days; the run stopped by design
  ("Nothing was generated ... remove it from your selection"). Search then showed 84 INS "Not available from ACORD
  Solutions" (no call). Generate again without it: 82 s, **0 ASG calls** (the three blanks came from memory). 25 GA prints
  the CURRENT term 07/15/2025-07/15/2026 (certificate rule); 125 the proposed 07/15/2027-07/15/2028. Re-rendering all four:
  no ASG call. **INS finding:** ASG ignores the INS variant for 84 too (as for 25 / 137 TX) - the 6 INS forms in the list
  likely all fail the same way; owner to decide (hide them, or ask ASG for the variant parameter).
- **15:01 - checks 8-9 PASS (no ASG call).** Edit on 137 TX saved (19 s) and kept on reopen. Sign (producer, saved
  signature): all three producer boxes painted, the three applicant lines untouched and undated, edit kept. **Accuracy
  find (L-4/L-5 round):** 137 TX ticks Symbol 1 AND prints "1" in the Other-symbol box (`Vehicle_BusinessAutoSymbol_
  OtherSymbolCode_A`) - that box is only for symbols the grid does not print.
- **15:14 - checks 10-12 PASS; then a REAL BUG found and fixed.** Send to Client: the signature question pre-ticked,
  naming ACORD 125 + ACORD 137 TX; e-mail sent; the client saw only it, signed (forms 125 + 137 TX), submitted (score
  62 -> 62). Boxes: 137 TX three applicant lines painted + dated 11/04/2026, three producer boxes painted, 15 initials
  blank; 125 applicant line painted + dated. **But the rendered 137 TX showed NO signature on pages 1 and 3** (images
  drawn 4x2 pt in the corner) - in the viewer AND the download. Cause: `_get_page_content_scale` GUESSED the page's
  drawing scale from its first 500 bytes; our own highlight overlay is prepended to each page, so with many
  highlighted boxes the template's "0.12 0 0 0.12 0 0 cm" sat past byte 500 and the guess said 1.0. Not ASG-only:
  any signed page with many highlighted boxes, OUR forms too (live in production today). The DRAFT watermark had the
  same class worse - never compensated at all, a 19-pt mark in the corner on every form. **Fix:** no guess -
  `pdf_service._seal_page_content` wraps the page's own content in q ... Q, then the signature / watermark is drawn
  in plain page space (the qpdf / pypdf overlay technique). `SIGNATURE_SCOPE` bumped ("producer|sealed") and the
  applicant render key carries it, so every signed PDF cached before repaints. Tests (+5, built from the REAL page
  shape - the stub opens with the cm, which is why the first 10 passed) fail with the fix off (4 of 4) and pass on.
  **Also found:** 210 of 474 Send-to-Client questions are raw ASG box names ("form edition identifier", "flood
  coverage nfip building accept indicator") - to fix after the run.
- **15:26 - signature fix verified live; checks 13-15 PASS; second bug fixed (ACORD 60).** After a backend restart on
  the fix, 137 TX shows both signatures on all three pages (pages 1 + 3 were invisible). download-all: Primble record in
  60 / 125 / 137 TX (and the cover), NOT in 25 GA (certificate rule); 137 TX carries 6 full-size signatures, 125 one.
  Edit after signing: 137 TX's applicant signatures + dates drop (send again), the producer's stay, 125 keeps its
  applicant signature. **Totals: 4 ASG downloads (as approved), 0 Transcriber calls, 0 request errors** (4 tracebacks =
  shutdown CancelledError from my two backend restarts). **Bug 2:** ACORD 60 was never offered for signing - it prints
  "Applicant's Signature" to the LEFT of its line; our rule read only a label ABOVE the box. Now a same-row left label
  counts, only for a line that stands alone (nothing printed just above it) - ACORD 130's Minnesota attestation has
  "(Applicant's Signature):" to its left too, inside its paragraph, and stays excluded (the pinning test caught the
  first cut). Live: the signature question now covers ACORD 125, 137 TX and 60. Not signed live (a second e-mail).
- **15:28 - CORRECTION + titles.** The "210 raw ASG box questions" finding above was WRONG: all 435 "Please provide your
  <box>" questions are already held in the hidden internal panel (`_hide_machine_worded_questions`); the client /
  producer lists show 28 questions, all properly worded. I had counted the raw API output. Nothing to fix. **Titles:**
  ASG's catalogue lost quotes / apostrophes / dashes as "?" in 15 titles ("Operator?s", "Supplement ? Selection",
  "?Workers Compensation Act?") - restored in the builder (`_TITLE_FIXES`, plain ASCII), rebuilt: 1,116 forms, only
  those 15 titles changed, none left with "?".
- **Run summary (owner's go, 14:54-15:28):** 15 checks; 14 PASS as planned, two real bugs found and fixed on the way
  (signatures invisible on pages that start with many highlights - ours too; ACORD 60's left-hand signature label),
  one wrong finding retracted. ASG: exactly the 4 approved downloads; Transcriber: 0. Open: 84 INS = plain 84 (the
  third INS failure - the 6 INS forms left in the list likely all fail: owner to decide hide / ask ASG); 137 TX
  Other-symbol box (L-4/L-5 round); ACORD 60 signing not done live (needs a second client e-mail); uvicorn prints a
  shutdown CancelledError traceback on every stop (noise, every Render deploy too).
- **15:40 - related tests after the fixes: 84 files, 3,916 passed, 0 failed, 17 skipped** (signatures, applicant signing,
  ASG forms, the editor, the painter, the watermark, downloads). Backend restarted on the final code + rebuilt list.
- **16:18 - owner's localhost test kit** in `~/Downloads/Primble test 4 Nov/` (fresh made-up Florida insured, Sunline
  Coastal Builders LLC): 1) a 2-page dec (GL / auto with 3 VIN-valid vehicles and 4 drivers / FL WC 5645-8810-5606,
  mod 0.94, officers incl. / excl.); 2) a filled ACORD 25 from an "outside agency" (appearances drawn - 1 Transcriber
  page); 3) today's Primble-downloaded ACORD 125 (Orbin, carries the record - must make NO Transcriber call); README
  with the steps. Edge-case ASG forms for the owner to generate (2 downloads): **ACORD 130 FL** (a state version of one
  of OUR form numbers - our 130 rules, WC tables, signature / attestation layout) and **ACORD 163** (driver schedule -
  repeating rows on a form we do not own; "163" must rank before 163 INS). Full suite started (owner's yes); log watch
  on. Owner commits tomorrow after his own localhost check; first Render ASG call after tomorrow's deploy.
- **16:21 - why INS fails (catalogue read, no call).** The list is right: ASG's catalogue has all 6 INS forms, each with its own
  fillable file (84 INS = edition 2013/09, `..._201309_84_INS_ACRO.pdf`). Our request is the problem: we send
  `formNumber=84&latestEdition=true&geoCodeSuffix=INS`; every INS form is an OLD edition (84 INS 2013/09 vs plain 84
  2026/03), so "latest" resolves to the plain form and the suffix does not override it. `geoCodeSuffix` is our guess -
  ASG's doc never names a variant parameter. The 11:53 "ask the listed edition" idea was withdrawn on 25 INS / 137 TX INS,
  which do not exist in the catalogue at all - it was never tried on an INS form that exists. Next: ONE test call (84 INS
  asking edition 2013/09; the plain 84 at 2013/09 is marked not downloadable, so ASG should answer with the INS file) -
  needs the owner's yes and clearing 84 INS from the local refusal memory. 163 INS / 829 INS share their edition with a
  downloadable plain form, so they may still need ASG's answer.
- **16:23 - the same cause beyond INS (catalogue read, no call).** "latest edition" resolves to the NEWEST row of the
  number (+ state); 1,104 listed forms ARE that row, so they are safe (what 137 TX / 25 GA / 60 / 50 NY / 27 / 75 proved).
  10 visible forms are not: the 6 INS forms (newest row is the plain form); 61 VA and 80 MS (ASG files them under the
  plain number with NO state code, so geoCode=VA / MS may find nothing); 97 SC and 134 FL (the newest edition has no
  fillable file). 701 ME has the same shape but is a Life form, hidden. One fix for all 10: ask the form's own listed
  edition (61 VA / 80 MS without the state code). Proof = 3 calls, one per pattern, owner's yes. 125 CIS works with
  "latest" (proven), so the suffix parameter is honoured for CIS - INS differs only in being an older edition.
- **16:26 - ASG's Postman collection** (`ASG_DOCUMENTATION/transcriber.forms-download.postman_collection.json`, owner
  downloaded it from the portal; gitignored; no secrets in it - every key field is empty). ONE request:
  `GET https://{env}-api-transcriber.acordsolutions.net/v2/forms/download?formNumber={formnumber}&edition={YYYY/MM}`,
  AWS SigV4 + x-api-key, Accept application/pdf (the SigV4 family - we use the OAuth family's /forms/download, which
  works). Documented selectors: **formNumber + edition only** - no geoCode, no geoCodeSuffix, no latestEdition. Our state
  downloads prove geoCode is accepted anyway; the suffix was never documented. So an INS form can only be picked by its
  edition: 84 INS = formNumber 84 + edition 2013/09 (+ suffix INS, in case ASG uses it to tell the plain 2013/09 from the
  INS 2013/09). Still needs one proving download.
- **16:33 - the portal's own download request** (owner, DevTools, row 84 FL): `download?formNumber=84&edition=2026/03&
  orgId=<our org>&geoCode=FL` -> ACORD 84 FL (2026/03), 4 pages, fillable. The portal ALWAYS sends the row's explicit
  edition, never "latest" - same as the Postman collection. Implication: asking the LISTED edition (+ state code) for
  every form, as the portal does, fixes the 10 risky forms in one rule. Still open: what the portal sends for the INS row
  (whether a suffix parameter exists) - one more click on the 84 | 2013/09 | INS row.
- **16:37 - CORRECTION: the INS failure was OUR footer check, not ASG and not "latest".** The owner's portal download of
  the 84 | 2013/09 | INS row (`formNumber=84&edition=2013/09&geoCodeSuffix=INS` - so `geoCodeSuffix` IS ASG's own
  parameter name) is 411,801 bytes and prints only **"ACORD 84 (2013/09)"** - no "INS" anywhere. Our 15:27 download of
  "84, latest, suffix INS" was also exactly 411,801 bytes: almost certainly the same, correct INS file. The identity
  check (`asg_forms.identity_check`: `if suffix and suffix not in rest: continue`) demanded "INS" in the footer and
  refused it. My 16:21 / 16:23 / 16:26 entries ("latest resolves to the plain form") were wrong. Plan, after the suite:
  (1) identity check - a variant whose footer prints no suffix is accepted when its printed edition equals the edition
  asked for; a different edition is refused; a plain request still refuses a printed variant; (2) the request mirrors
  the portal (the row's own edition + its geoCode only when the row has one + its suffix) - still needed for 97 SC /
  134 FL (newest edition not fillable) and 61 VA / 80 MS (no geoCode on ASG's row); 125 CIS keeps its proven request;
  (3) the refusal memory key gets a version so forms refused under the old check get one fresh try.
- **16:46 - DEEP CHECK (owner: "are we doing this with other forms, and does the fix let users generate ANY form ASG
  provides, like their dashboard?") - analysis only, no code, no call.** Inputs: ASG's download catalogue (4,012 rows,
  1,155 distinct forms), our list, today's logs, the owner's two portal captures.
  - **Three root causes, all one shape - we GUESSED ASG's contract instead of copying it:**
    1. *The request.* We send number + "latest" + our own reading of state / suffix. The portal sends each row's own
       fields: number + that row's edition + geoCode only when the row has one + geoCodeSuffix when it has one.
       Simulated over every listed form, today's request misses **7** (61 VA, 80 MS: ASG's row has no state code, so
       ours matches nothing; 63 OK, 97 SC, 134 FL, 139 MS, 141 INS: "latest" lands on a flat, non-fillable edition).
       The row-addressed request is **unambiguous for all 1,115** (no two forms share number / geo / suffix / edition).
    2. *The footer check.* We required the state / suffix code to be PRINTED. ASG's INS files print only "ACORD 84
       (2013/09)" - so all 6 INS forms are refused while ASG sends the right file. Fix: identity = number + the edition we
       asked for + no code we did not ask for; a printed code is a bonus, not a requirement.
    3. *The refusal memory.* Refusals made under the wrong check stick 30 days - version the key.
  - **Parity gap found:** 8 state forms are listed ONE EDITION BEHIND ASG's newest, because ASG filed the newest edition
    without a state code (60 MA, 61 AZ, 65 MA, 65 PA, 80 CO, 137 LA, 138 LA, 852 TX - e.g. 137 LA: we list 2024/10, ASG's
    newest is 2026/02). The builder should list the newest fillable row whether or not ASG coded its state.
  - **What the dashboard has that we would still not offer:** 24 P&C forms ASG has only as FLAT PDFs (no boxes - our
    pipeline fills boxes; e.g. 130 OH / OK / OR / PA / PR / RI, 133 MT / NC, 1001-1003, 200, 201, 350, 360, 370, several
    INS); 11 P&C forms with non-state codes (25 FR, 25 S, 126 S, 155 BM, 60 / 62 / 64 / 66 US, 75 N, 50 WM, 829 LOB,
    829 CLAP) - fillable, excluded by our "US state codes only" builder rule; older editions (~2,850 rows - the
    dashboard lists every edition, we list the newest fillable); Life / Health (Brent's P&C rule).
  - **Verification after the fix = 4 calls, one per pattern:** 84 INS (code not printed), 61 VA (row without a state
    code), 97 SC (latest is flat), 137 LA (newest edition filed without a code).
- **16:49 - full suite: 23,007 passed, 1 failed (the known), 46 skipped** (3 shards, 16:15-16:48). The INS / request fix
  waits for the owner's go (he asked to see the findings first).
- **17:29 - THE FIX, BUILT (owner's go: "fix it properly - a user can search any form from Primble that is provided by ASG
  and on dashboard search and generate it"; 11 odd-code forms "add now"; flat-only left out; newest edition only).**
  - `scripts/build_asg_forms_index.py` `build_from_catalogue`: one entry per form + state + variant at its newest
    FILLABLE row; `_row_identity` reads ASG's non-state geo codes (FR, US, WM, N, S, BM, CLAP, LOB, e) and suffixes
    (INS, S) as VARIANTS, and codes ASG kept only in the row name ("61_VA", "137_LA" 2026/02, "25-S", "131_-S") from the
    name; each entry records `request` = what ASG's portal sends for that row; a row whose request is shared with
    another row is never chosen (0 such). `_TITLE_FIXES` kept. 125 CIS: `{"latest": true, "geoCodeSuffix": "CIS"}`.
  - `services/asg_forms.py`: `meta_for` carries `asg_request`; `requested_edition` = the row's own edition;
    `_network_fetch` sends the row's own geoCode / geoCodeSuffix (log line now `geo=` / `suffix=` from the request);
    `printed_footers` + `normalize_edition` ("2013/09", "1/98", "Oct-97"); `identity_check(pdf, meta, asked_edition)`
    = number + no unasked code (states + every variant code in the list) + printed edition == asked edition, the codes
    asked for printed OR proven by the edition; the refusal names the printed edition ("ACORD 84 (2026/03)");
    `edition_from_pdf` reads the same footers; refusal memory `asg:refused:v2:`.
  - Real-file check: the owner's portal 84 INS -> accepted; 84 FL for INS / INS for FL / INS for plain 84 -> refused;
    today's 137 TX / 25 GA / 60 print exactly the edition now asked; all 17 of our templates still accepted.
  - List 1,116 -> 1,131; 8 editions moved to ASG's newest; skipped names only "50_WM TR_NJ" (a Travelers card), "63_life_OK",
    "form38"; 28 identities with no fillable file.
  - Tests: `test_asg_forms_3nov.py` + `test_asg_signatures_4nov.py` 231 passed. Three old tests pinned the guessed
    contract ("latest", ask_edition, the code-in-footer rule, the 3 Nov non-state exclusion) - the TESTS were outdated,
    rewritten to the portal's contract; new: every form's request unambiguous, footer cases from real shapes, editions,
    the 12 new forms found by "number code", refusal key versioned.
  - **Proof pending (owner's yes): 5 downloads** - 84 INS, 61 VA, 97 SC, 137 LA, 829 LOB.
- **17:49 - PROOF (owner's yes: exactly 5 downloads; guard = one request per form, no retry; 1 sign-in):** 84 INS (edition
  2013/09 + suffix INS) **accepted** - 5 pages, 679 boxes, footer "ACORD 84 (2013/09)": the INS fix is proven. 97 SC
  (2006/08 + SC) **accepted** - the fillable edition, not the flat newer one. 829 LOB (2009/05 + geoCode LOB)
  **accepted**. 61 VA and 137 LA 2026/02 (asked with NO geoCode - their code only in ASG's row name) **refused by ASG:
  "no acroform PDF"** - their stored files are named "UXX" (ASG's "no state"): an ASG data gap, not a request we can
  fix. **Correction built:** the builder never chooses a row whose code is only in its name (137 LA and the 7 others
  back on their coded editions; 61 VA, 80 MS, 131 S, 140 S leave the list until ASG fixes its data); a refusal is keyed
  to the exact request (form + edition + geo + suffix), so 137 LA's coded 2024/10 row is not blocked by the refusal of
  its code-less row. List 1,127 (vs 1,116 this morning: +12 ASG-code P&C forms, +951 E Life hidden, -61 VA, -80 MS).
- **17:49 - every form checked, nothing generated, no ASG call:** all 970 P&C forms found on the live backend by number +
  code (top 25) and by title; none shown "not available"; 0 of 157 Life / Health forms leak into search. Every one of
  the 970 uses a request shape now proven on production (state code + edition 745, plain + edition 206, ASG's other code
  + edition 11, suffix + edition 7, latest + CIS 1). The three proof downloads fill and render offline through our steps.
- **17:49 - three more fixes from the proof files:** (1) **signature TIME boxes** ("SignatureTime", its AM / PM ticks -
  ASG's 97 SC) were classed as SIGNATURE by their name, so the Sign button would have painted them - now `KIND_TIME`
  (`signature_boxes._SIGNED_TIME_TIP`), never painted, never a line, never an applicant step; none of our 17 forms has
  one. (2) **label UNDER the line** (97 SC "APPLICANT'S SIGNATURE" printed below) - accepted for a stand-alone line, like
  the left label. (3) **"Other symbol" code box** - an AI value that is a symbol the grid prints is blanked
  (`pdf_service._blank_grid_symbols_in_other_box`; ASG's 137 TX ticked Symbol 1 and printed "1" there; our 137 / 138
  have the same boxes). Tests +4 (101 passed with the applicant-signature file). Two adversarial reviewers running.
- **18:12 - adversarial review A (list / request / footer check): 5 real problems, all FIXED and pinned.**
  1. HIGH: the footer check took a matching edition as proof when the state / ASG code was not printed - but 49 state
     forms (125 FL, 82 MD, 877 CA, 84 FL ...) and 829 LOB / CLAP share their edition with the plain form, so the PLAIN
     form would have been accepted as them. Now (evidence by category: every real state / ASG-code download printed its
     code; only ASG's SUFFIX files - INS - do not): an unprinted code is accepted only for a suffix variant, a form whose
     edition is its own among the number's fillable rows (builder: `unique_edition`, 405 forms share one), or a state
     form whose first page names its state. Residual, inherent: an INS form and its plain twin at the same edition (84,
     163, 36, 139) print identical footers - we rely on ASG honouring the suffix (proven: 84 INS = the portal's file).
  2. MEDIUM: 61 NY's row says 2026/04, its file is 2025/04 - the right file would have been refused for 30 days. The
     builder records the file-name edition (`request.file_edition`, only 61 NY today); both are accepted.
  3. LOW: a foreign code on ANY page now refuses (was: first matching footer won).
  4. LOW: "25s" / "25's" read as a plural (it had turned into the 1995 "25 S" form and hidden our ACORD 25).
  5. LOW: refusal key now carries the check's version (`asg:refused:v3:`, bump with every `identity_check` change);
     `ASG_REFUSED_DAYS=0` turns the memory off (it was clamped to 1 day).
  Builder: "Oct-97" editions read; a newest row passed over for ambiguity is reported (`ambiguous_rows_passed_over`);
  a suffix that reads as a state is skipped, not merged; names without separators ("902CA") read. The reviewer's 19
  break tests: the 10 that showed bugs now fail; the 9 left are the shapes that must hold (and the INS twin). +13 tests.
  **Open (needs one call, owner's yes):** 59 listed forms have files ASG stores under "UXX" while we send a geoCode (84
  SC, 137 LA 2024/10, 60 / 62 US, 137 / 138 NC SC TN VA ...). No proof yet has that shape; one call on 84 SC settles it.
- **18:23 - adversarial review B (signatures / drawing / Other-symbol guard): 7 problems, all FIXED and pinned.**
  1. HIGH: the new LEFT-label rule signed ACORD 130 (2026/08)'s Minnesota and Utah "I have no employees" attestations -
     that edition leaves a blank line between the paragraph and its signature row, so "nothing printed just above"
     held. Now a LEFT or UNDER label counts only when the line has its OWN applicant date box on its row (attestations
     have none; ACORD 60 and 97 SC do). Old vs new over 29 real PDFs: identical on 27 (our 17 included, 130 2026/08 signs
     only its real line C); the two changes are the intended ones (97 SC and 60 gain their lines).
  2. MEDIUM: the time rule matched every "Enter time:" box (125's policy effective time, 141 / 160 business hours) -
     3 existing tests failed and the dry run sent those boxes to "Sign". Now only a time the form was SIGNED.
  3. MEDIUM: reading an ASG form's lines cold takes ~1 s per form (~3 s a package) and ran ON the event loop in the
     signature-status route, sign / finalize and the form-fields view - now `run_scoring` (off the loop).
  4. LOW-MED: a cached signed ASG form rebuilt its template on every view - the rebuild now follows the cache check.
  5. LOW-MED: the Other-symbol guard judged the whole family, not the ROW (row E - towing - prints only 3 / 7, so a 2
     belongs in its Other box), blanked company symbols ("7A", "S2") and left the Other tick on. Now per row from the
     form's own ticks, words other than "symbol" keep the value, and the paired AI Other tick is cleared with it.
  6. LOW: an applicant's signing-time box is an applicant step (it never holds a form at 85; it leaves the to-do list
     once the applicant signs).
  7. LOW: a box at the page edge (zero-width band) raised in pdfplumber and wiped out every line of the form - bands
     of no size read as nothing.
  +8 tests. Reviewer B's own repro scripts confirm each fix.
- **21:23 - PROOF ROUND 2 (owner's yes: exactly 4 downloads; same guard; 1 sign-in; no refusal memory written):**
  84 SC (file "UXX", geoCode SC) **right form**; 60 US (file "UXX", geoCode US) **right form**; 61 VA asked WITH geoCode VA
  (its row keeps VA only in the name) **ASG served the right form** - prints "ACORD 61 VA (2023/07)" for its row
  labelled 2023/08 - and our check refused it on the edition; 137 LA 2026/02 asked WITH LA **right form**. So: (1) the
  58 "UXX" forms are proven; (2) a row with its state only in its NAME downloads when asked with that state - the
  builder now does so (61 VA, 80 MS back; 60 MA, 61 AZ, 65 MA, 65 PA, 80 CO, 137 LA, 138 LA, 852 TX at ASG's newest
  edition; list 1,129); a VARIANT code only in the name (131 S, 140 S, 25 N, 350 / 360 / 370 WM) stays out, unproven;
  (3) a form that prints exactly the codes asked for is accepted when ASG's catalogue edition label differs (logged
  `ASG_FORM_EDITION_DIFFERS`); a form with no code printed still needs its edition. Refusal key `asg:refused:v4:`.
  All four files: accepted as themselves, refused as every other form of the number. ASG tests 256 passed (6 tests
  pinned this afternoon's rules and were updated to what the calls proved). Memory updated; ASG is not asked (owner).
  Full suite started.
- **21:56 - full suite: 23,059 passed, 1 failed (the known), 46 skipped** (on the code after proof round 2). Review C
  (embarrassment hunt) reported; the two hide-or-not decisions are parked in OPEN_ITEMS.md; the rest being fixed now.
- **22:10 - REVIEW C (what would embarrass us) - fixed (offline, no ASG call); two decisions parked in OPEN_ITEMS.md.**
  - **Edition labels (the class behind 61 VA):** ASG's catalogue label vs its own file name disagree on only 3 of 3,699
    fillable rows, but a form can PRINT another edition than both (61 VA). A form printing its codes was already safe;
    now a form whose footer prints NO code (206 plain forms, 7 suffix forms) is accepted on a differing edition unless
    that edition is its TWIN's (the other form of the number with a code-less footer - plain 84 vs 84 INS); the builder
    records `twin_editions` (8 plain forms have an INS / S twin).
  - **Rows that contradict themselves** (builder `_contradiction`): file is another form (137 WA 2024/02 = Maryland's
    EUIM file -> its 2016/12 edition), titled after another state (63 OK "Ohio Fraud Statement" -> removed, no other
    row), presents itself as one of our core applications under another number (66 CO = the Commercial Insurance
    Application -> removed). Every passed-over row is reported (`contradictory_rows_passed_over`). 856 CA's file is the
    BOP application CHECKLIST -> titled so. 3827's blank title reads from its file name.
  - **Titles:** typos (Floirda, Liabiilty, Addenedum, "New Yorker"), en-dash / curly quotes -> plain ASCII, double spaces.
    Older titles that START with the newest are kept for search (`aka`, 45 forms) - "tria" / "terrorism" find 60 / 62 /
    64 US.
  - **Search:** our 17 are found by their own names (+ "commercial"): "commercial umbrella" -> 131, "commercial auto" ->
    127, "assigned risk" -> 133; typed words side by side outrank scattered ones ("insurance card" no longer leads with
    the NFIP credit-card form; one word may sit between - "Employment Related Practices"); synonyms tria, businessowners,
    boiler; the 16 Australian forms (`region: AU`) rank after US forms (still listed - owner's call).
  - **Certificates:** Oklahoma's security-verification ID forms and the financial-responsibility forms (54, 57) print the
    current term; the NFIP floodproofing certificates (307, 308 - a building, not coverage) do not.
  - **Scoring:** ASG's 186 SC (an auto UM form) no longer inherits our 186's GL lines (`asg_forms.same_subject_as_ours`
    - the only form sharing one of our numbers with another subject).
  - **Screen:** "Edition X or newer" -> "Edition X" (the request pins that edition).
  - List 1,127 forms. Tests: ASG files 274 passed (+19 new; 2 updated - "commercial auto" now leads with our 127, the
    our-forms-first test). Full suite started. Parked for the owner: hide non-submission forms (25), hide very old
    variants (OPEN_ITEMS.md). Accuracy-round items (not now): 137 TX "$7" deductible / "$185" hired cost / "CO" in 18
    state cells; 25 GA "Fungi Or Bacteria Exclusion ($33)".
- **22:37 - full suite on review C's fixes: 23,077 passed, 1 failed (the known), 46 skipped.**
