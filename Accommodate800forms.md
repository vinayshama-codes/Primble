# Accommodating 800+ ACORD forms - analysis (30 Oct 2026, no code yet)

Source material: `All-800PlusForms-Kit-by-Brent/` (Brent's two emails of 30 Oct + the kit).
Deadline from Brent: **by Fri 6 Nov a user can search / select ANY ACORD form, and Primble fills,
generates and downloads it.** He accepts the missing 10-30% on non-core forms for now.

---

## 1. What Brent sent

| Item | What it is |
|---|---|
| `Primble ACORD Underwriting Readiness.pdf` (5 pages) | A written spec: for each of the 6 core forms, what must be completed and confirmed so an underwriter gets a clean submission; how to treat Y/N questions; the discrepancies in his sample; a pre-marketing checklist; what is NOT needed for an initial quote. |
| `Primble ACORD 6 Forms.pdf` (28 pages, flattened, no fillable boxes) | The matching **sample filled package** - a fictional electrical contractor ("TRAIN-0001"), stamped "PRIMBLE UW REVIEW - Y/N = ANSWER MUST BE CONFIRMED - EXAMPLES ARE NOT VERIFIED", colour-highlighted (green = sample value, yellow = Y/N to answer, blue = conditional / unknown, red = correct / sign). 125 (pp 1-10), 127 (11-14), 130 (15-19), 131 (20-28); 126 and 140 pages are image-only (no text layer). "One document corresponds with the other" = the readiness PDF explains this sample. |
| `Most Common ACORD Forms/` | 15 form folders from ACORD, each with: AdobeFillable PDF, AdobeStatic PDF, IBM XFDL, **FIG** (Form Implementation Guide), and for several an **EForms** folder holding the **Mapping List.csv** (every box -> its ACORD e-label) and a **Toolkit**. The `.zip` names are already-unpacked folders. |
| `Key.png` | Folder suffix legend: **A** = top of the list from Bryan, **B** = secondary on Bryan's list, **P** = Primble's own priority. |

Kit forms (folder name = form + key): 1 (B), 2 (B), 25 (A), 27 (A), 35 (A), 37 (B), 50 (B), 75 (A),
80 (B), **125 (AP), 126 (AP), 127 (BP), 130 (BP), 131 (P), 140 (AP)**. Brent: "use these six as the base".

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
