# fix-form-stamping.md

Shared context for every chat fixing "the form has the wrong thing stamped on it".

**Read this before you touch a checkbox, an indicator, or a paired amount/description
field on any of the 17 ACORD forms.** Client keeps reporting these one at a time. They
are not separate bugs. They are four mechanisms sitting on one root cause.

**Status legend:** `DIAGNOSED` = root cause proven in code, fix specified, NOT shipped.
`SHIPPED` = in the tree with tests. Update the log at the bottom when you ship.

---

## THE ROOT CAUSE (one sentence)

**We stamp a value onto the form after stripping away the context that qualifies it.**
The pipeline treats a value being *present in the document* as sufficient reason to
stamp it. Four qualifiers get dropped on the way, and **every client report so far is
one of these four missing:**

| Qualifier | The question nobody asks | What it looks like when it's missing |
|---|---|---|
| **GRANT** | Does this coverage *exist*, or is it declined? | `Crime and Fidelity - No Coverage` ticks the Crime box |
| **OWNERSHIP** | *Whose* value is this - applicant, carrier, or producer? | The carrier's website `www.emcins.com` stamped as the applicant's |
| **SHAPE** | Is this even a valid instance of the thing? | `0482854` (7 digits) in a 9-digit FEIN box |
| **ROW INTEGRITY** | Is this row a real entity at all? | A tax ID `84-` in a Named Insured row with no name |

**Predicting the next report:** take any field, ask which of the four qualifiers is
checked before it stamps. If the answer is "none", that field is already broken or one
document away from it.

---

## THE GRANT FAMILY - four mechanisms

Measured across all 17 real schemas: **1,541 `/Btn` checkbox fields. 89 stamped by
Pass 1 (deterministic). 1,452 answered by the gap-fill LLM.** Both paths are broken,
differently.

### M1 - The evidence gate never checks polarity on a "Yes"
[`pdf_service.py:7510`](backend/services/pdf_service.py#L7510)
```
if negative and not _quote_expresses_negative(quote): return False
```
Polarity is verified **only for "No" answers**. A "Yes" (a ticked box) only has to cite
a quote that *exists somewhere in the document*. `"Commercial Property - No Coverage"`
exists. It grounds the tick. This governs all **1,452** LLM-answered checkboxes.

### M2 - Pass 1 is exempt from the gate entirely
[`pdf_service.py:7377`](backend/services/pdf_service.py#L7377), our own comment:
> *"Deterministic (Pass 1 / alias) values never enter gpt_filled_set, so they are
> untouched here - a checkbox Pass 1 already filled **from a real extracted fact** is
> never re-litigated by this gate."*

The premise is false. **A flag is not a fact.** `has_crime=true` means the word "crime"
appeared once in 600k characters. Those **89** boxes are stamped with zero evidence
check, forever.

### M3 - Coverage flags are keyword presence, OR-merged across chunks
- [`extraction_service.py:461-462`](backend/services/extraction_service.py#L461):
  `has_crime` / `has_cyber` are defined as *"true if document **mentions**..."*. Six
  sibling flags (`has_inland_marine`, `has_umbrella`, `has_property_coverage`,
  `has_builders_risk`, `has_auto_coverage`, `is_contractor`) already carry an explicit
  `Do NOT set true...` guard. Crime and Cyber never got one.
- [`extraction_service.py:3808`](backend/services/extraction_service.py#L3808):
  `mg[k] = mg.get(k, False) or v` - **one chunk saying true wins permanently.** A
  prompt-only fix gets swallowed by this OR. Any downgrade must run *after* the merge.
  Precedent for post-merge repair already exists at
  [`extraction_pipeline.py:370`](backend/services/extraction_pipeline.py#L370).

### M4 - The paired value box is orphaned, so nothing can contradict the tick
ACORD pairs every checkbox with a corroborating field. We fill the box and leave the
pair empty, so the form never shows the contradiction and we never had a cross-check.

On ACORD 125 alone: **15 line-of-business premium boxes**
(`CrimeLineOfBusiness_PremiumAmount_A`, `CommercialVehicleLineOfBusiness_PremiumAmount_A`,
...). **No per-line premium fact exists anywhere in the system** - not in the extraction
schema, not in `FACT_REGISTRY`, not in the alias bridge. That column can only ever be
blank. The dec page prints all of them.

Same shape: every `*_OtherIndicator_*` -> `*_OtherDescription_*` pair, and every
indicator whose limit/amount sibling is unmapped.

### M4b - "Other" rows have no mutual exclusion with the enumerated rows
Gap fill is handed only the *unmatched* fields. It is never told which enumerated boxes
Pass 1 already ticked. So it re-answers the same coverage into the free-text `Other:`
row. That is the pink `Commercial Auto` / `Commercial Liability Umbrella` duplicate.
Generalizes to every `Other / Describe` row on all 17 forms.

---

## THE OWNERSHIP / SHAPE / ROW FAMILY - three more mechanisms

### M5 - Facts have no owner, so the LLM grabs whichever value it finds
Three entities appear in every submission: the **applicant**, the **carrier**, and the
**producer**. We model that at fact level for a few keys (`applicant_name` vs
`carrier_name` vs `producer_name`) and nowhere else.

**There is no `website` fact at all** - not in the extraction schema, not in
`FACT_REGISTRY`. So `NamedInsured_Primary_WebsiteAddress_A` is answered purely by gap
fill, and a dec page's only URL is the *carrier's*. The model didn't malfunction; it
grabbed the only website in the document because nothing told it whose website the box
wants.

**Free deterministic cross-check nobody is running:** we already know `carrier_name` and
`producer_name`. A value equal to (or on the same domain as) a known carrier/producer
value must never stamp into an applicant field. No LLM, no cost, works on all 17 forms.

### M6 - Format validators exist and are not wired to the stamping step
[`fact_registry.py:46`](backend/services/fact_registry.py#L46) defines `_is_fein`
("9 digits, with or without hyphen"). It rejects **both** bad values on the client's
form. It never runs on the value that reaches the PDF - `pdf_service` imports
`FACT_REGISTRY` for its **keys only**
([`pdf_service.py:142`](backend/services/pdf_service.py#L142)).

The one stamp-time type check we do have, C22's `_rejects_declared_type`
([`pdf_service.py:5801`](backend/services/pdf_service.py#L5801)), reads ACORD's own
declared type from the tooltip - but for `identifier` and `code` it only rejects a
**person's name** or a **VIN**. A malformed identifier sails straight through. And
`NamedInsured_Primary_WebsiteAddress_A` is declared type `text`, which has **no check at
all**.

C22 was deliberately conservative and that was right. The gap is that identity fields
with a legally defined shape (FEIN, NAIC, ZIP, NAICS, SIC, phone, email) were never given
their shape check.

### M7 - No orphan-row suppression anywhere
`NamedInsured_TaxIdentifier_B` was stamped `84-` while `NamedInsured_FullName_B` is
blank. **A second named insured with a tax ID and no name is structurally impossible.**
Grepped the whole services tree: no rule anywhere checks that a repeating row has an
identity anchor before filling the rest of it.

This is the multi-slot prompt rule ("find N distinct values") pushing the model to
produce *something* for row B when only one entity exists.

---

## OWNERSHIP OF ALL 17 FORMS - MANDATORY

**The client reports one form. You fix the class, on every form it touches.** The fields
differ per form; the four missing qualifiers do not. Before you close any issue here,
sweep the other 16 schemas for the same shape and either fix it or write down why it
doesn't apply.

Predicted, from the four qualifiers - treat as a to-do list, not a guess:

| Qualifier | Where it will bite next |
|---|---|
| **GRANT** | Every checkbox on all 17 forms (1,541 of them). Coverage-election boxes on 140 / 28 / 160. `Included` / `Excluded` / `No Coverage` wording anywhere on a dec page. |
| **OWNERSHIP** | Producer vs carrier vs applicant **name, address, phone, email, website, FEIN** - on every form with a header block. ACORD 25: certificate holder vs named insured. ACORD 127: driver vs registered owner. ACORD 140/28: mortgagee / loss payee vs insured. ACORD 131: underlying carrier vs umbrella carrier. |
| **SHAPE** | FEIN (9), NAIC (5), NAICS (6), SIC (4), ZIP (5/9), phone (10), email, policy number, driver licence, VIN (17), class codes, percentages, dates. Every one of these appears on multiple forms. |
| **ROW INTEGRITY** | Every schedule on every form: vehicles (127/137/138), drivers (127), locations (125/140), loss runs (125), additional insureds, underlying policies (131), WC class codes (130), scheduled IM items (160). |

---

## VERIFIED CLEAN - DON'T WASTE TIME HERE

Checked so nobody re-runs it:
- `_INDICATOR_RULES` ([`pdf_service.py:1417`](backend/services/pdf_service.py#L1417)):
  55 rules swept against all 5,852 fields in all 17 schemas. **0 fields matched by more
  than one rule. 0 non-`/Btn` fields captured.** The substring targeting is sound. The
  problem is the *inputs* to those rules, not the matching.

---

## RULES FOR ANY FIX IN THIS AREA

1. **Never reduce fill to gain accuracy.** Do not tighten the criteria for setting a
   flag *true*. Only ever add a **downgrade** that fires when the document *explicitly
   states* the coverage is absent. Silence is not a "no".
2. **Fix both doors.** [`pdf_service.py:1694`](backend/services/pdf_service.py#L1694):
   a `False` flag stamps the box "No" (gap fill never sees it); a **missing** flag
   returns `None` and the LLM decides. Closing one leaves the other open.
3. **Deleting a bad `_INDICATOR_RULES` entry is not a fix** - the field falls through to
   the LLM and gets ticked anyway. Repoint it, or make it resolve to an explicit "No".
4. **Tick the box and fill its pair in the same change.** If you can't source the paired
   value, say so - don't ship a lone checkmark.
5. **Two kinds of checkbox, two kinds of proof:**
   - *About the policy* (lines of business, coverage sections like EDP / Open Cargo /
     Glass & Sign): needs a stated limit, premium, or a distinct coverage part.
   - *About our own package* (Vehicle Schedule, Driver Information Schedule, Loss
     Summary, Statement of Values): **no document sentence can ever prove this.** Derive
     it from what we actually generate. Never let the LLM answer it.
6. **No topic/keyword matching between a quote and a question.** Tried three times,
   regresses worse. See the `evidence-gate-design` memory.
7. **A shape check rejects only the provably impossible.** C22's bar, and it holds: a
   `limit` box legitimately holds "Statutory" / "Included" / "See schedule". Validate
   FEIN-shape in a FEIN box, not "must contain a digit" everywhere. C22 was proved safe
   by a ~49,000-pair sweep with zero false positives - match that bar or don't ship.
8. **An orphan row needs ALL its anchors blank, not one.** A vehicle with no VIN but a
   real year/make/model is a real vehicle. Define anchors per schedule as a set, clear
   the row only when every one of them is empty.
9. **Fix the class on all 17 forms, not the field that was reported.** See the ownership
   section above.
10. Update [`improving-ll.md`](improving-ll.md) in the same commit if you touch a prompt
   or a call.

---

## ISSUE LOG

| # | Symptom (client-visible) | Form | Mechanism | Fix | Status |
|---|---|---|---|---|---|
| 1 | Commercial Property ticked; decs say `Property - No Coverage` | 125 | M1 + M3 | Post-merge negation downgrade + Yes-polarity check | DIAGNOSED |
| 2 | Crime ticked; decs say `Crime and Fidelity - No Coverage` | 125 | M2 + M3 | Give `has_crime` the `Do NOT set true` guard its 6 siblings have + negation downgrade | DIAGNOSED |
| 3 | Cyber and Privacy ticked from an EDP "Virus and Hacking" extension (GL policy has a **cyber exclusion**) | 125 | M2 + M3 | Same as #2 for `has_cyber`: needs a distinct coverage part, not an extension inside another line | DIAGNOSED |
| 4 | Open Cargo Section ticked on every inland marine job | 125 | M2 | [`pdf_service.py:1484`](backend/services/pdf_service.py#L1484) hard-maps `OpenCargoIndicator -> has_inland_marine`. **Any** IM ticks ocean cargo. Repoint to a real open/ocean cargo signal and resolve to explicit "No" otherwise (per rule 3) | DIAGNOSED |
| 5 | Driver Information Schedule ticked with no driver schedule attached | 125 | M4/rule 5 | Derive from the package we generate, not from `auto_drivers` presence | DIAGNOSED |
| 6 | Pink duplicate rows: `Commercial Auto`, `Commercial Liability Umbrella` in the `Other` line boxes | 125 | M4b | Suppress an `Other` description that maps to an enumerated box already ticked | DIAGNOSED |
| 7 | Entire LOB **premium column blank** while 4 premiums are printed on the decs ($2,991 / $3,954 / $300 / $3,418) | 125 | M4 | Add per-line premium facts; stamp the 15 premium boxes; use premium-or-limit as the box's proof | DIAGNOSED |
| 8 | `FEIN OR SOC SEC #` = `0482854` (7 digits) on the first named insured | 125 | M6 | Wire `_is_fein` (already written, already correct) to stamp time. Reject-only on a provably impossible shape | DIAGNOSED |
| 9 | `FEIN OR SOC SEC #` = `84-` on the **second** named insured, whose name/address/phone are all blank | 125 | M7 + M6 | Orphan-row suppression: a repeating row with no identity anchor gets cleared | DIAGNOSED |
| 10 | `WEBSITE ADDRESS` = `Www.emcins.com` - that is **EMC Insurance, the carrier**, not Orbin Contracting | 125 | M5 | Add an attributed `applicant_website` fact + a known-carrier/producer value exclusion on applicant fields | DIAGNOSED |
| 11 | `NO. OF MEMBERS AND MANAGERS` = `0 - 25` - a range in a field ACORD declares as a **count** | 125 | M6 | Found in sweep, client did not report it. A count is one integer; C22's `number` check allows prose-free ranges | DIAGNOSED |

*(Correctly ticked on the same run, do not regress: Business Auto, Commercial General
Liability, Commercial Inland Marine, Umbrella, Vehicle Schedule, Electronic Data
Processing Section. Also correct: business phone `303-996-7800`, LLC entity type,
applicant name and mailing address.)*

---

## BLAST RADIUS - THESE FLAGS ARE NOT COSMETIC

Before changing any `has_*` flag, know what else reads it:

| Flag | Also drives |
|---|---|
| `has_property_coverage` | ACORD 140 + 28 recommendation ([`form_service.py:825`](backend/services/form_service.py#L825)); ~10 cross-form property rules; **8 mandatory fields in the SQS property pillar** ([`sqs_service.py:2247`](backend/services/sqs_service.py#L2247)); ARQ property questions |
| `has_crime` | **Early-return guard** on the silent-crime-exposure warning ([`cross_form_validator.py:686`](backend/services/cross_form_validator.py#L686)) - a false `true` *silences* a real warning |
| `has_cyber` | Same, silent-cyber-exposure ([`cross_form_validator.py:722`](backend/services/cross_form_validator.py#L722)) |
| `has_inland_marine` | Open Cargo box (M2), form recommendation |

**Expect scores to move.** Removing false property/crime/cyber flags lifts SQS on past
submissions and surfaces previously-muted advisories. That is a correction, not a
regression - tell Brent before he notices.
