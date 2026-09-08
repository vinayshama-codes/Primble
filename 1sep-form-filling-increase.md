# 1 Sep 2026 — Form Fill Rate: issues, evidence, fixes

**Purpose.** Running reference for the work to raise ACORD form fill quality.
Every issue below is *measured*, not reasoned about — each one names the command
that produced the number, so a future session can re-run it and check whether the
change held. If we need to go back, each fix records what to revert.

**Read this before touching `pdf_service.py`'s gap fill, `extraction_service.py`'s
merge, or `utils/helpers.py`'s address parser.**

---

# ⚡ STATE OF PLAY — read this first, everything else is detail

## WHERE IT STANDS — run 10, 2 Sep 2026

| | day 1 | run 6 | run 9 | **run 10** |
|---|---|---|---|---|
| Correct | 142 | 176 | 176 | **178** |
| **Wrong values** | 10 | 1 | 1 | **0** |
| **Precision** | 93.4% | 99.4% | 99.4% | **100.0%** |
| Recall | — | 80.5% | 80.0% | 80.9% |
| ROW-CELL | 74.0% | 92.2% | 92.2% | **92.2%** |
| Cross-row contamination | 11 | 0 | 0 | **0 — ten runs straight** |
| Y/N wrong / fabricated | — | 0 / 0 | 1 / 0 | **0 / 0** |

**Run 10 is the first run with NO wrong value anywhere on any form.** Everything
that remains is a BLANK box, not a wrong one — which is the correct side of the
line for a signed application. Recall has been flat at ~80% for four runs: the
deterministic work is essentially done, and what is left is model recall on a
fixed set of hard cells plus ONE real defect class (the products grid).

**Suite: 5207 passed / 1 known `httpx` failure.**

## DECLARATION-PAGE COVERAGE — measured on run 10 (2 Sep 2026)

"How much of what the dec pages state actually reaches a form?" — measured by
matching every `dec_page_entries` value against every stamped AcroForm value on
the three generated PDFs, at ATOM level (an entry like
`POLICY PERIOD FROM = "03/15/2026 TO 03/15/2027"` is a COMPOSITE whose two dates
stamp separately, so a whole-string match understates coverage badly — the naive
version reported 60.9% and was wrong).

| | count | share |
|---|---|---|
| Dec entries carrying a value | 207 | |
| **Fully on a form** | **138** | **66.7%** |
| Partly (a composite whose parts landed) | 24 | 11.6% |
| **Nothing reached a form** | **45** | **21.7%** |
| *Substance on a form (full + partial)* | *162* | ***78.3%*** |

**Of the 45 that reached nothing, most SHOULD reach nothing:**

| ~count | what | verdict |
|---|---|---|
| 15 | ISO endorsement titles (`CG 00 01 04 13 = Silica Or Silica-Related Dust Exclusion` ...) | **correct** — no box on 125/126/131 asks for an endorsement schedule |
| 3 | narrative context sentences ("Territory 104 is the Denver metropolitan...") | **correct** — not values for any box |
| 6 | the FOURTH named insured's identity (Legal Entity, Business Started, FEIN 92-0668311, SIC 6512, NAICS 531120) | **capacity** — ACORD 125 prints 3 rows and the document has 4 entities. SAME CLASS as the loss-run overflow, and NOT yet disclosed anywhere |
| 8 | the Contractors Pollution underlying row on ACORD 131 (insurer, number, dates, CSL, premium) | **real miss** — the answer is in `coverage_lines` |
| ~4 | `GENERAL AGGREGATE LIMIT APPLIES PER = "Per Project"`, the applicant's business phone (x2), prior-year gross receipts | **real miss** |
| ~9 | match artifacts (`AUDIT PERIOD = Annual` prints as the code "A"; `Symbol 1 - Any Auto` is a ticked BOX not a text value) | **stamped, not counted** |

**Honest headline: roughly 15-20 of 207 dec values (8-10%) are ones we should
have stamped and did not.** Everything else either has no box on these three
forms, is a composite already stamped in pieces, or is a form-capacity overflow.

## OWNER DIRECTIVES — standing, not negotiable

1. **NEVER change LLM call 1's facts/flags prompt.** Owner, 1 Sep 2026: *"its
   working perfectly and dont touch it."* `PROMPT_VERSION` / `SCHEMA_VERSION` are
   `v17` and must stay there. This kills the "just extract the hazard rates"
   plan — see §3b for what replaces it.
2. **Focus on LLM call 2.** *"we are dependent on it to get answers for most of
   the fields."*
3. Score in four buckets and steer by **ROW-CELL**, never by a fill percentage.

## Shipped

### Batch 1 - measured live (142 → 165 correct)

| | what | measured effect |
|---|---|---|
| **I2** | schedule-row dedup (claim number; line+policy; class+territory+exposure) | loss 8→5, underlying 8→4, hazards 6→3 |
| **I5** | comma-free address split (unit → line 2, city recovered) | every form gains line 2; a lost city recovered |
| **I1 + I3½** | dec-index rating carve-out in `map_facts_to_form` | 4 premium boxes on ACORD 131 |
| **B1/B9/B10** | three doors that compared addresses on line 1 alone | all fixed; two were data-deleting |

**Live result: 142 → 165 correct, 10 → 6 wrong, precision 93.4% → 96.5%,
ROW-CELL 74.0% → 88.3%, cross-row contamination 11 → 0.**

### Batch 2 - shipped, NOT yet measured live (all of it is LLM call 2)

| | what | measured effect (offline) |
|---|---|---|
| **I6** | row-oriented table framing - 3 parts | **+212 columns** row-framed across 13 forms, **0 lost** |
| **I7** | every categorised scalar fact is a witness; a sentence is not an amount | the live wrong $1,804,000 blanked, the real $2,145,000 kept |
| **I8** | "an empty table is the correct answer" in the row block | prompt half; the root cause was I6 |
| **I10** | a quote opening with a printed ISO form number is a citation | 4/4 citations rejected, 8/8 real quotes kept |
| **§3b (part)** | LOC # and HAZ # on the ACORD 126 hazard grid | +6 boxes, 0 lost, 16 other forms untouched |
| **B3 (doc)** | the misleading "corrupt package" warning + docstring | behaviour unchanged on purpose - see B3 |
| **B11/B12** | two bugs my own tests introduced or exposed | both fixed |

### Batch 3 - the two defects RUN 3 EXPOSED (1 Sep 2026, evening)

| | what | measured |
|---|---|---|
| **R1** | the EXPIRING programme was being read as the policy applied for | **8 policy-number boxes corrected across 8 forms, 0 lost** |
| **R2** | the CONTACT's phone was written into the NAMED INSURED's box | the box that knocked a 3-row table down a row |

**Suite after batch 3: 5166 passed / 1 known `httpx` failure.** Zero regressions.
Nothing that worked was changed.

### Batch 5 - TWO GUARDS WERE DELETING CORRECT VALUES (3-4 Sep 2026)

**Measured on a DIFFERENT kit** - the SYS-05 two-document package
(`sys05_test_data/`: a dec page plus a certificate of the same programme), not
the T1 kit, so these numbers do not extend the run-10 table above. They belong
in this file because every one of them is a box that shipped BLANK while the
fact was present - the deletion side of fill rate.

| | what | measured |
|---|---|---|
| **G1** | `_is_truncated_copy_of_a_held_value` blanked any narrative that is a PREFIX of another held value | **2 boxes recovered on ACORD 125, 0 lost** |
| **G2** | Guard 4 clustered fuzzily but demanded BYTE EQUALITY to exempt a field's own value | reproduced deleting a value over one trailing period |
| **G3** | `_lob_tokens` read "Bodily Injury And **Property** Damage Liability" as the Commercial Property line | one policy number spanned two lines, `_line_list_is_trustworthy` rejected the list, **total policy premium was `None`**; now $18,605 |
| **G4** | a LOB premium box accepted only ACORD's own tooltip wording | the Crime line printed under its ISO name, so its **premium box shipped blank**; now $1,225 |
| **G5** | a certificate's LIMIT became `property_building_value` | the merge's role gate covered LISTS only; scalars sailed through |
| **G6** | `operations_description` stated against the PREMISES never reached the applicant-level box | derived from the schedule when every row agrees |

**G1 is the one to remember.** On a two-document package the facts were:

```
operations_description                = "...warehousing of food products"
certificate_description_of_operations = "...warehousing of food products.
                                         Certificate holder is an additional
                                         insured with respect to..."
```

The second is the first **plus a new sentence** - a certificate appends its own
additional-insured wording to the same opening description. Two different facts
sharing an opening sentence, not one value cut in half. `_normalize_for_search`
strips punctuation, so the sentence boundary that tells them apart was invisible
and BOTH operations boxes on ACORD 125 shipped empty.

Fix: the structural second condition (H1-F's rule again). A real truncation stops
mid-word or mid-clause; a complete statement stops at a sentence boundary.

**Proved strictly additive on the real session before believing the form** - the
shipped code against the same code with `_is_cut_off_mid_sentence` forced to
`True` (the exact old behaviour), diffed over every populated field:

```
fields filled  OLD=62  NEW=64
GAINED (2)  BuildingOccupancy_OperationsDescription_A
            CommercialPolicy_OperationsDescription_A
LOST (0)    CHANGED (0)
```

Both guard fixes can only ever REFUSE to blank, and that is measured here rather
than asserted. **Suite after batch 5: 5503 passed / 1 known `httpx` failure**
(plus the separately-documented `confidence_fill_rate` truncation defect, which
predates this work and is held for Brent).

**THE PROCESS LESSON, and it cost six hypotheses.** G1 was chased through the
withhold list, the value's length, a three-field Guard 4 repro, the fact envelope
shape, Guard 4's ownership and the declared-type guard - all reasoned from the
CODE, all wrong. It took four minutes once the real session was loaded and INFO
logging was on, because **these guards already announce themselves by name**:

```
truncated_copy blanked=CommercialPolicy_OperationsDescription_A
  - it is the cut-off head of '...warehousing of food p...', which we hold in full
```

That is exactly why `dump_session_facts.py` exists (2026-08-17: *"three of four
predictions were wrong, and every one because the reasoning was done against the
CODE instead of a real session's facts"*). Same mistake, same cost, second time.
**When a box is blank and the code says it should not be: load the session and
turn INFO logging on BEFORE forming another hypothesis.**

New tool: **`backend/scripts/why_is_ops_blank.py`** - no arguments. Reads the
newest session through the decrypting repository and prints the merged facts,
each document's contribution, the premises schedule, the package flags, the
withhold list and what the stamper produces, then says how to read it:

```
section 1 empty            -> extraction/merge never produced the fact
section 1 filled, 6 None   -> the stamping rule is the problem
sections 1 and 6 filled    -> a POST-FILL GUARD is blanking it
```

Full write-up, client context and decision register: `1stSep-liveTestFixes.md`.

### ✅ RUN 4 CONFIRMED BATCH 3 — a CLEAN A/B, for the first time

Run 4's facts are **identical to run 3's** (only `_scoped` metadata and the
`coverage_lines` R1 repairs differ), so this is the first true before/after in
this whole effort. **R1 and R2 both landed exactly as designed.**

| | run 3 | run 4 | |
|---|---|---|---|
| correct | 149 | **158** | **+9** |
| wrong | 10 | **2** | **−8** |
| **precision** | 93.7% | **98.8%** | **+5.1** |
| recall | 67.7% | **71.8%** | +4.1 |
| must-be-blank hit | 7 | 13 | **+6** ⚠️ (products grid, I8) |
| ROW-CELL | 92.2% | 92.2% | held |
| cross-row | 0 | **0** | held |

**Against the original baseline: 142 → 158 correct, precision 93.4% → 98.8%,
ROW-CELL 74.0% → 92.2%, cross-row 11 → 0.**

### Batch 4 - everything remaining that CAN be fixed safely (2 Sep 2026)

| | what | measured |
|---|---|---|
| **Y1** | the reuse cap counts ANSWER UNITS - the option boxes of one question are one answer | unblocks the 4 safety-programme boxes; 0 compliance questions leak (all 17 schemas) |
| **L1** | TOTAL LOSSES derived from the whole schedule, inside the EXISTING owner | `$568,495` - reproduces the stated figure to the dollar |
| **S1** | a column bound to a live schedule fact stamps BEFORE the name gate | +40 fields incl. `wc_class_codes.rate`; no rate ever reaches the model |
| **J1** | TABLE_JOIN - one schedule printed as two buckets is asked as ONE table | the named-insured address+identity split (12 blanks on run 4) |
| **I8** | the borrowed-value backstop **measured and REJECTED** | **0 true positives / 54 false positives** - pinned so it cannot arrive quietly |

**Suite after batch 4: 5181 passed / 1 known `httpx` failure.** Zero regressions.

### Run 5 scored + batch 5 shipped (2 Sep 2026, late)

**Run 5: 160 correct / 8 wrong / precision 95.2% / cross-row 0.** NOT comparable
to run 4 (19 of 106 fact keys differ - extraction moved again, dec entries
238 -> 181). What run 5 proved on the printed forms: **L1 exact ($568,495), the
I1 carve-out live (all four ACORD 131 underlying premiums printed), I7 exact
($2,145,000 in the subcontract box), ACORD 131 wrong = 0, loss grids 20/20.**
What it exposed: the expiring programme leaked back through THREE new doors -
all fixed the same night as batch 5:

| | what run 5 exposed | fix |
|---|---|---|
| **R3a** | the expiring block's prior numbers sat in entry VALUES; the attribution field carried the package number, so R1's section rule found nothing | `_prior_programme_sections` counts prior numbers in VALUES too |
| **R3b** | the prior-grid rescue matched on the package-level routed prior term and stamped the EXPIRING number (131 header) and EXPIRING carrier (126 header) as CURRENT | the line's own term outranks the routed term - the routed term is now a fallback for UNDATED lines only, in BOTH twins (number + carrier) |
| **R3c** | `_carriers_by_line` indexed "EXPIRING INSURER" entries - the only GL carrier evidence sat inside the expiring block, and the merge repair wrote the OUTGOING carrier onto coverage_lines | prior-programme sections are excluded from the carrier index (fail-open when facts are absent) |
| **R3d** | the merged named-insured table slid AGAIN (row C took row B's company). The known `FullName_B/C` cells are deterministic and were INVISIBLE to the table block - FullName is never an ACTIVE column | known cells are harvested from the bucket ROOT family; a known row with open fields is ANCHORED ("_B belongs to: FullName=Halewood...") and the ordinal rule yields to anchors |

**Suite after batch 5: 5187 passed / 1 known failure.** 6 new tests (R3).
**The expiring programme has now produced FIVE distinct defects (R1, R3a-d).
Standing instruction: any future wrong-identity report - check the expiring
block FIRST.**

### ⭐ RUN 6 - THE BEST RUN, AND THE FIXES ALL HELD (2 Sep 2026)

| | baseline | run 6 | |
|---|---|---|---|
| correct | 142 / 220 | **176 / 220 (80.0%)** | **+34** |
| wrong | 10 | **1** | **−9** |
| missing | 59 | **39** | −20 |
| must-be-blank hit | 13 | **7** | −6 |
| **precision** | 93.4% | **99.4%** | **+6.0** |
| ROW-CELL | 74.0% | **92.2%** | +18.2 |
| cross-row | 11 | **0** | six straight runs |

Per form: **125 = 117/128, 1 wrong, precision 99.2%, recall 91.4%** (the anchored
table finally landed - all three named insureds carry their OWN codes, FEIN,
phone AND address); **126 = 37/57, 0 wrong** (all 7 blank-hits are the products
grid); **131 = 22/35, 0 wrong**.

Confirmed live this run: all four safety-programme option boxes ticked (Y1),
row anchoring (R3d), TOTAL LOSSES $568,495, subcontract cost, the 126 header
carrier = Cascade Summit (R3c), EXPIRING POL # correctly ...25.

**One more expiring-block escape found and closed the same night (R3e):** run 6's
extraction glued each expiring row into ONE entry value ("GENERAL LIABILITY
Sentinel Prairie Casualty Company GL 7784120 25 $54,120"), so the whole-value
equality test missed the prior numbers and the 131 header shipped blank.
`_prior_programme_sections` now finds prior numbers by SUBSTRING of the
normalised value (10+ alphanumerics - unambiguous). **All FIVE stored extraction
variants now resolve both section headers correctly.**
**Suite: 5188 passed / 1 known failure.**

### Batch 6 - the rest of the list (2 Sep 2026, after run 6)

| | what | proof |
|---|---|---|
| **M1** | **the rating MOD box SHIPPED** - inside `_resolve_underlying_policy_row` (its one owner), per the adversarial stress test's own prescription | 0.94 and 1.00 stamp; the stress test's 11 wrong-value cases ALL stay refused |
| **M1** | `_dec_index_rating_value` hardened: exclusive label matching, value-shape by concept, raw-label disqualifiers (TOTAL/EXPIRING/DATE...), one-entry-one-box reverse uniqueness, expiring-block exclusion | the LIVE 10-box ACORD 160 spray -> 0; "SEE ITEM 4", "$500", ARAP, increased-limits, effective-date all refused; the four T1 premiums all still stamp |
| **P1** | table columns now render `_FIELD_SPEC_CLARIFICATIONS` (they never did) + the business-phone caution | run 6's one wrong cell was that gap |
| **P1** | table rule (g): the applicant's BUSINESS ITSELF is never a schedule row | aimed at the products grid's four-run pattern |

**How the MOD box honours the owner's condition** ("no hardcoding, works on real
client docs"): every condition is structural - the label's own leftover words
must be the line's vocabulary or nothing; the value must have the shape the
column's concept demands (a factor is a bare decimal, a premium is currency,
neither is ever a date); one printed figure may fit ONE box; the expiring block
never transcribes. The adversarial cases are the permanent M1 test suite, so
the rule cannot quietly widen back into the junk the original ruling recorded.

**The old accident-pin flipped by design**: `test_i1_the_rating_mod_box...`
froze the box blank so it could not fill BY ACCIDENT; it now pins the approved
transcription instead, and M1 is what keeps it narrow.

**Suite after batch 6: 5204 passed / 1 known failure.** 16+ new tests.

### What remains — CURRENT list (2 Sep 2026, after run 10)

Nothing below is a WRONG value. Run 10 had none. These are blanks and one
fabrication cluster.

| count | what | status |
|---|---|---|
| **6** | **ACORD 126 products grid** | **THE one real open defect.** Five runs, five different shapes, all the applicant itself (trade as a product, revenue as sales, revenue HISTORY as three products' sales, operations text as intended use). Run 10 SHUFFLED them rather than reducing them. Needs the bucketing extraction — see the retired `_zero_evidence_table_rows` docstring for the design and the two ways it failed |
| 12 | ACORD 126 hazard rates / premiums | **OWNER DECISION, still open.** Fill needs a grid-parser that 3 of 4 adversarial reviews rejected (stamps last year's rates on a renewal). The clean alternative is to declare them producer-owned blanks so they leave the denominator |
| ~4 | ACORD 125 Q1a/Q1b/Q4/Q2 detail blocks | Their dependent blocks carry NO explanation-shaped name at all (`Subsidiary_*`, the `OtherPolicy_*` grid, the `FormalSafetyProgram_*` boxes), so rules 2/4/5 are still unenforced there. The 2 Sep pairing fix does NOT reach them — it needs a different mechanism than name-token matching |
| 3 | fabricated EL limits on ACORD 131 | $1,000,000 x3 where the document states NO EL limit. The same run REFUSES that figure one box over in a guarded must-be-blank trap — a gap-fill leak on an UNGUARDED field family. Extend the guard |
| ~10 | Y/N jitter | model dice on a fixed set. Wrong and fabricated are both at ZERO; what varies is which few come back blank |
| 2 | underwriter name, package policy number | owned blanks by OUR right-or-blank rule, NOT blocked by the call-1 freeze (corrected 2 Sep). Unblocking them is a risk decision |

**Cosmetic / low priority, seen on run 10:** ACORD 131's coverage-information box
duplicated its own sentence; area values now carry a "sq ft" suffix the form
already prints as a label; the additional-interest address prints line 1 whole
AND its components separately (the known C48 comma-free-address shape).

### OLD what-remains list (pre-batch 6)

| count | what | status |
|---|---|---|
| 7 | ACORD 126 products grid fabrication | the ONLY wrong-value source left; no safe deterministic rule (0 TP / 54 FP measured); shrank 13 -> 7 with the anchor/join work |
| 1 | row A business phone took the CONTACT's number via gap fill | ONE cell; the doc prints both numbers side by side |
| ~19 | 126 missing (hazard rates 12 - OWNER DECISION; Y/N jitter rest) | rates blocked by "producers rate, we don't" + no fact |
| ~12 | 131 missing (mod factor 2 - APPROVED, awaiting stress test; rest jitter/no-fact) | |
| 2 | underwriter name box + package policy number | no fact / I4 closed-as-measured |

## THE TWO ROW PROBLEMS — do not confuse them

This is the single most-confused point in this whole effort.

| | problem | status |
|---|---|---|
| **Row duplication** | extraction stored the same row twice when the document printed it twice, so the form printed duplicate rows | ✅ **FIXED** (I2). cross-row 11 → 0 |
| **Column-wise framing** | gap fill asks each COLUMN separately — *"find 3 values in document order"* — with no concept of a row, then staples unrelated answers together | ✅ **FIXED** (I6), awaiting a live re-run |

Both are now closed in code. The second was the big one, it was a CALL 2 problem,
and this is the live proof it existed — a clean one-row slide:

```
NamedInsured_Primary_PhoneNumber_A  ->  the CONTACT's phone
NamedInsured_Primary_PhoneNumber_B  ->  insured A's phone
NamedInsured_Primary_PhoneNumber_C  ->  insured B's phone
NamedInsured_SICCode_C / NAICSCode_C ->  insured B's codes
```

...while `NamedInsured_MailingAddress` — a proper 5-column TABLE — came back
**100% correct** on the same run. That contrast is the entire argument for I6.

## RELATIONSHIP PRESERVATION — scorecard

The client's standing instruction is *"optimize for preserving what each value
means and where it belongs"* (`FIX_TRACKING_2026-08-15.md`). Where we stand:

| relationship | state |
|---|---|
| row identity inside a schedule (is this row one real entity?) | ✅ solid — dedup fixed it |
| a value's line of business (GL vs Auto vs Umbrella) | ✅ holding — every bleed trap passed |
| a value's role (identity vs boilerplate vs clause) | ✅ holding — every role trap passed |
| street ↔ unit ↔ city on one address | ✅ fixed |
| **column ↔ row inside a gap-filled table** | ✅ **FIXED (I6)** - three parts, +212 columns framed |
| a figure's MEANING ↔ the box it lands in | ✅ tightened (I7) - every categorised fact now witnesses |
| a policy-level figure ↔ the row it belongs to | ⚠️ guarded by refusing to fill (single-row rule) |

## Next, in order — CURRENT (after run 10)

1. **The products grid.** The only wrong-value cluster left. The EVIDENCE TEST is
   right (no cell filled anywhere in a table = no rows, measured 0 correct cells
   lost); the BUCKETING is what must be reused, not reinvented — `_table_prefix`
   / `_TABLE_ROOT_BUCKETS` / `_row_universe` / `_claim_bucket`, which today live
   as a CLOSURE inside `_build_user_prompt`. Extracting it is the work, and the
   refutation warned it must not dissolve batch 4's J1 merged named-insured
   table. Do not add a third bucketing — that attempt broke the C18 fleet-row
   guards.
2. **The 3 fabricated EL limits (ACORD 131).** Cheapest real win after the grid:
   the guard already refuses that same figure one box over.
3. **The hazard rates — OWNER DECISION.** Fill (risky) or declare owned blanks
   (clean). 12 boxes either way.
4. **ACORD 125's four unpaired questions.** Needs a dependent-block mechanism
   that does not rely on an explanation-shaped NAME. Riskiest of the four; do it
   last and measure every new pair before shipping (that discipline caught 68
   false pairs on 2 Sep).

**Do NOT spend time on:** the wrongly-blank Y/N tail (model recall, precision is
already 100%), ACORD 131's "dateless loss run" (verified NOT a defect — its only
date column asks when the claim was FILED and the document prints occurrence
dates), or `NamedInsured_Primary_WebsiteAddress_B/C` (already blanked by the
row_dedup guard).

## Next, in order — HISTORICAL (kept for the reasoning)

1. **RE-RUN (run 5).** Batch 4 is unmeasured live. Diff the facts first (rule 8).
2. **I8 — the products grid.** The candidate deterministic backstop was measured
   and is DEAD: **0 true positives, 54 false positives** over two runs against the
   key (every address and prior policy number legitimately co-occurs across
   families). What remains live against it: J1 (the grid is now one framed table
   with its own name) and the empty-table rule. If run 5 still fabricates, the
   honest remaining options are an extraction-side products signal (call 1 -
   frozen) or a human-facing flag, not a value-blanking rule.
2. **The rating MOD box (2 boxes)** — **OWNER APPROVED 1 Sep 2026** ("works, and
   i dont want this to be hardcoded and it should work correctly for real client
   docs"). NOT YET BUILT: it is waiting on the adversarial stress-test of
   `_dec_index_rating_value` (what label wordings real carriers use; five ways to
   fool the four conditions; whether a mod factor's SHAPE should be checked).
3. **§3b — ship the 40 already-bound, unreachable fields.** Verified. Not on the
   three test forms, so it goes AFTER run 4 to keep attribution clean. The grid-parser
   route was designed, adversarially reviewed and **rejected 3-of-4** — see §3b.
4. **I9** — the Yes-quote reuse cap. **An experiment, not a code change**: one run
   with `EVIDENCE_YES_QUOTE_REUSE_MAX=12`.
5. **I4 / B3 / B4** — investigated on the real fact set and **deliberately left
   alone**. The measurement is recorded below so nobody re-opens it blind.

## What to check on the re-run, in this order

| | now | must be |
|---|---|---|
| cross-row contamination | 0 | **still 0** — I6 must not undo I2 |
| precision | 96.5% | **not below 96.5%** |
| the phone/SIC/NAICS slide | 6 wrong | **0** (I6) |
| ACORD 126 products grid | 14 must-be-blank hits | **fewer** (I6 + I8) |
| ACORD 126 hazard grid LOC #/HAZ # | blank | **001/001, 002/001, 004/001** (§3b) |
| `Contractors_SubcontractorsPaidAmount_A` | $1,804,000 (wrong) | **blank or $2,145,000** (I7) |
| `BusinessInformation_ForeignGrossSalesAmount_A` | prose | **blank** (I7) |
| Section policy numbers (126/127/131/140/…) | last year's | **this year's** (R1) |
| ACORD 131 header | `XSU 55 210934 25` | **`XSU 55 210934 26`** (R1) |
| Named-insured rows A/B/C | slid one row down | **aligned** (R2) |

A rise in `correct` with a fall in precision is a regression however good the
headline looks.

**AND CHECK THE FACTS FIRST.** Dump both sessions and diff them before reading a
single score - see §4d. Run 3 differed from run 2 on **18 of 103 fact keys** and
the headline "165 → 149" was almost entirely that.

---

## 0. The test kit (build this first, it is the instrument)

| file | what it is |
|---|---|
| `backend/scripts/make_t1_test_pdfs.py` | builds the kit; self-verifies and fails the build if a cited value or trap is missing from the PDF |
| `backend/scripts/_t1_data.py` | single source of truth — document and answer key are both generated from it, so they cannot disagree |
| `backend/scripts/score_form_fill.py` | grades generated PDFs: 4 buckets + ROW-CELL + owned-blank census |
| `t1_test_data/T1_verdant_slope_package.pdf` | 70 pages, 296,884 extracted chars, 20 planted traps |
| `t1_test_data/T1_answer_key.json` | 220 expectations, 72 must-be-blank, 15 scoped forbidden traps, 4 row groups |
| `t1_test_data/README-HOW-TO-TEST.md` | what each trap proves |

```
py backend/scripts/make_t1_test_pdfs.py
py backend/scripts/score_form_fill.py --key t1_test_data/T1_answer_key.json \
    --pdf-dir <folder with the generated PDFs> [--facts facts.json]
py backend/scripts/dump_session_facts.py <session_id> --json > facts.json
```

**Score in four buckets, never two** — `correct / wrong / missing / stamped-where-must-be-blank`
— plus **ROW-CELL** (does a cell carry the right value *for the row it sits in*).
A run can score 90% on fields and 50% on row-cells; the second number is the one
that tracks the defect class this work exists to fix.

---

## 1. BASELINE — live run, 1 Sep 2026 (session `4a527824`)

Upload `T1_verdant_slope_package.pdf`, generate ACORD 125 + 126 + 131.

**THE MEASURING STICK WAS FIXED FIRST, before any pipeline code changed.** The
first baseline scored `1` against an expected `001` and `6,500 sq ft` against
`6,500` as WRONG — 8 of 18. A broker calls neither a defect, and banking those
as "improvements" later would have been dishonest. `score_form_fill.norm` now
strips a redundant unit the form's own label already states, and compares whole
numbers without leading zeros. **No pipeline code was involved in this change.**

| | correct | wrong | missing | owned blank | must-be-blank hit | ROW-CELL |
|---|---|---|---|---|---|---|
| ACORD 125 | 92/128 | 9 | 21 | 6 | 0/18 | 35/39 (90%) |
| ACORD 126 | 32/57 | 1 | 23 | 1 | **12**/30 | 9/18 (50%) |
| ACORD 131 | 18/35 | 0 | 15 | 2 | 1/24 | 10/20 (50%) |
| **package** | **142** | **10** | **59** | 9 | **13** | **54/73 (74.0%)**, cross-row **11** |

Precision **93.4%**, recall **64.5%**.

*Two earlier readings of this same run, kept so nobody confuses them with a
result. Neither involved any pipeline code — all three differ only in how
honestly the scorer measured:*
* *134 correct / 18 wrong / precision 88.2% / ROW-CELL 64.9% — the over-strict key.*
* *141 correct / 11 wrong / precision 92.8% / ROW-CELL 70.1% — after the unit and
  leading-zero fix, before B7 (a LOC # of "1" read as a checkbox) and B8 (the key
  demanding a date column ACORD 131 does not have).*

**Test suite baseline, same commit: `5062 passed, 1 failed, 14 skipped, 1 xfailed`**
(`py -m pytest -q -p no:randomly` from `backend/`). The one failure is the
documented `httpx`/`openai` `ImportError` in `test_arq_acord125_missing_only`.
CLAUDE.md's "4824 passed" line is stale; the suite has grown.

### Where the 1,196 boxes across the three forms actually go

| | boxes | |
|---|---|---|
| filled deterministically from call-1 facts | 305 | |
| **empty, never handed to call 2** | **358** | **30%** |
| handed to call 2 | 533 | it answered 84 (**16%**) |

Of the 220 key expectations: **132 (60%)** come from call-1 facts with no AI at
fill time, **45 (20%)** go to call 2 (it got 24 right — **53%**), and
**43 (20%)** are blanked before either gets a look.

**Everything table-shaped is call 1.** Schedule columns are bound to call-1 facts
and call 2 is *forbidden* from touching them by the right-or-blank contract. So
every row defect is an extraction defect.

---

## 2. VERIFIED NOT BROKEN — do not spend time here

Measured with `scratchpad/audit_call2.py` (real `combined_gap_fill`, OpenAI client
stubbed at `ps._get_openai_form_fill_client_sync`, zero API calls):

* **Call 2 receives every field it is given** — 519 of 520 asked. The one miss is
  an artifact of the audit's own regex (`_R` row suffix), not a pipeline gap.
* **Call 2 receives 100% of the document** — 75/75 spaced probes reached the
  model, in both `--answer none` and `--answer all` modes.
* **No early-exit truncation.** 296,884 chars against a ~994,000-char budget = one
  chunk, so there is nothing to skip. `GAP_FILL_FULL_RESCAN=auto` covers the
  multi-chunk case.
* **`Quarterly - 25% Down` is stored correct and complete** in
  `Policy_Payment_PaymentScheduleCode_A`. The `arterly - 25% Do` on screen is the
  widget being too narrow with no auto-shrink — a rendering fix, not a data
  defect. **This closes the earlier "leading characters lost" report.**

**Trap to remember:** an audit whose stub answers `{}` can never see early-exit
truncation, because `active_fields` never shrinks and every chunk always ships.
Always run the answering mode too. (Same shape as the C25 lesson.)

**Second trap, learned the hard way here:** a stub that answers every field the
*same* value makes the guards reject 100% of it, which measures nothing. Realistic
per-field answers or no conclusion.

---

## 3. ISSUES

### I1 — Boxes are switched off by NAME before Pass 1 runs  🔴 biggest

`_is_nonfillable_field` (`pdf_service.py` ~12722) sets `mapped[field] = None` for
anything whose name contains `Premium`, `Rate`, `ProducerIdentifier`,
`Underwriter`. It runs *before* deterministic resolution, so a value we already
hold can never reach the box.

**Measured: 135 of the 358 withheld boxes; 27 of the 220 key expectations (12%).**

The GL hazard allow-list is `ClassCode|PremiumBasisCode|Exposure|TerritoryCode|Classification`
— **exactly** the five columns that came back correct. LOC #, HAZ #, both rates and
both premiums are excluded — **exactly** the six that came back blank. Also kills
all five underlying-policy premiums on the 131 and all three prior-carrier
premiums on the 125, all of which are printed on the dec page.

The rule was built to stop the model *inventing* rating figures. It also blocks
*transcribing* them. Those are different acts.

### ⛔ THE FIX AS FIRST PROPOSED IS WRONG AND DANGEROUS — DO NOT BUILD IT

A blast-radius trace (1 Sep) measured the original proposal — "move the gate off
the deterministic path" — and it fails on three counts:

1. **It auto-signs 16 of 17 forms.** `_is_nonfillable_field` has **12 call
   sites**, not the 2 I first counted. It is also what blocks 55 `Signature`
   fields, 11 `_Initials`, 9 `StateLicense`, 15 `Producer_NationalIdentifier`
   and 16 `CustomerIdentifier`. Removing the early gate puts **427** fields into
   `unmatched`; a second gate (`_RAW_TEXT_SKIP_PATTERNS`) drops most, leaving
   **123 that reach the model — and every one is a signature, an initial, a
   licence number or an agency identifier.** That is the complete set of the four
   live-reported hallucinations, restored. Client report #20 (an auto-signed
   application) is one of them. `fix-form-stamping.md:1125`: *"No confidence
   colour makes an auto-signed application acceptable."*
2. **It delivers nothing for the 131 anyway.** `UnderlyingPolicy_*PremiumAmount_*`
   contains "Premium", so `_RAW_TEXT_SKIP_PATTERNS` drops it at
   `pdf_service.py:10485`, and the gap-fill prompt itself says *"5. Do NOT fill
   premium/rate/underwriter-computed fields — omit them."* The box ships blank
   exactly as today, now while also costing a batch slot.
3. **It inflates batch packing** — 427 ineligible fields fragment the eligible
   ones across more outer batches (a C29/C30 regression).

**The real distinction is AUDIENCE, not grounding.** A dec page can print an
agent number, and a grounding test would happily stamp it in the producer-licence
box — which is a live defect that already happened. Signatures, initials,
attestations and agency-assigned identifiers must stay blank **however well
evidenced**. Only `Premium`, `Rate_`, `Hazard_` and `Underwriter` (242 fields)
are legitimately in scope.

### ✅ THE CORRECT SHAPE — and it already exists in the codebase

`map_facts_to_form` ALREADY carves out two premium families on the deterministic
path while leaving the gap-fill path blocked: prior-coverage premiums
(`:18177`) and `_is_lob_premium_field` (`:18187`). `improving-ll.md:2318` records
the asymmetry as deliberate: *"`_is_nonfillable_field` still blocks premium boxes
inside `compute_form_gaps`, so the gap-fill LLM is never asked for a premium —
the deterministic path was unblocked in `map_facts_to_form` only."*

So the fix is a **third carve-out of the same shape**, fed by a new deterministic
resolver that reads `dec_page_entries` by label (this is I3-half-1, and I1 cannot
work without it — see point 2 above). Narrow, precedented, and it never opens a
Group-A box.

### ✅ SHIPPED 1 Sep 2026 — in the redesigned shape, not the first one

`_dec_index_rating_value` (`pdf_service.py`) + a **third carve-out** inside
`map_facts_to_form`, beside the two that already exist. **The gate is untouched**,
so `compute_form_gaps` still refuses and the gap-fill LLM is still never asked
for a premium.

Four structural conditions, all positive-evidence, none of them a lookup table:

1. the field names a LINE that canonicalises through the shared `_canon_line`
   door — "Other Policy" does not canonicalise, so that grid is excluded *by
   construction* rather than by a list;
2. the field is SINGLE-ROW on this schema — a dec index is policy-level and has
   no row concept, so it can never fill row A of a repeating grid (this is what
   keeps it off the ACORD 126 hazard rows);
3. the dec entry must be for THAT line — the auto dec prints both "AUTOMOBILE
   PREMIUM" ($32,170) and "AUTO COMBINED SINGLE LIMIT PREMIUM" ($18,240);
4. every word of the field's own COLUMN must appear in the entry's LABEL, and
   exactly one entry may match. Two matches is a conflict, not a ranking.

**Blast radius, measured across all 17 schemas with the live facts: 4 fields,
all on ACORD 131.** Zero effect on the other 16 forms.

```
UnderlyingPolicy_GeneralLiability_PremisesOperationsPremiumAmount_A = $46,900
UnderlyingPolicy_GeneralLiability_ProductsPremiumAmount_A          = $14,555
UnderlyingPolicy_Automobile_CombinedSingleLimitPremiumAmount_A     = $18,240
UnderlyingPolicy_EmployersLiability_PremiumAmount_A                = $71,410
```

**Four adversarial tests written FIRST**, all passing before and after: the form
must not sign itself (checked over every Signature / _Sig / _Initials field on
three forms); Group-A identifiers must never enter `unmatched` (checked over all
17 schemas); the LOB premium column must not go dark; and no field the predicate
blocks may reach the gap-fill union.

**One of those guards failed before I changed anything** — I had asserted "no
field containing 'Premium' reaches the model", and `GeneralLiability_Hazard_
PremiumBasisCode_*` does, legitimately (the premium BASIS, "(p) Payroll", is a
data column a broker fills). The assertion now states the invariant against the
PREDICATE, not the substring. That is what a guard test is for.

**Revert:** delete `_dec_index_rating_value` and the third carve-out.
**Status:** ✅ SHIPPED (I3 half 1 shipped with it — they are one change).

---

### I2 — Extraction stores the same row twice  🔴

Your document prints the losses on page 30 and again on page 44. Both were kept.

```
loss_history            8 rows for 5 losses   (same claim_number twice)
gl_class_code_schedule  6 rows for 3 classes
underlying_policies     8 rows for 4 policies
property_locations      6 rows for 5 premises (+1 phantom, "Golden equipment yard")
```

`_SCHEDULE_DEDUP_KEYS` (`extraction_service.py:3112`) registers **three** schedules
(`auto_drivers`, `coverage_lines`, `wc_class_codes`). Everything else falls back to
`_NATURAL_ID_SUBKEYS`, which knows six identifiers — all vehicle- or person-shaped.
A loss run's identifier is a **claim number**; it is not in the set, so no key is
produced and the row is never merged.

**Consequences, all traced:**
* The 131 loss grid printed 6 rows for 5 losses — **all 11 cross-row cells**.
  That grid is 100% deterministic (`LossHistory_*` is schedule-bound), so the LLM
  never touched it. *This corrects an earlier attribution to table framing.*
* `UnderlyingPolicy_EmployersLiability_PolicyNumberIdentifier_A` shipped blank
  because the duplicated `coverage_lines` disagreed with itself.
* `_resolve_phantom_schedule_row` derives row capacity from list length, so a
  poisoned list also disables phantom-row suppression.

### ✅ SHIPPED 1 Sep 2026

Three changes in `extraction_service.py`:

| | key | result on the live data |
|---|---|---|
| `_NATURAL_ID_SUBKEYS` | `+ "claim_number"` | loss_history **8 → 5** |
| `_underlying_policy_dedup_keys` | `(line, policy_no)` PAIR | underlying_policies **8 → 4** |
| `_gl_hazard_dedup_keys` | `(class_code, territory, exposure)` | gl_class_code_schedule **6 → 3** |

**`policy_number` was NOT added to the generic set** — the existing comment
forbids it for a measured reason (one contract carries many coverage parts, so
merging on it deletes real lines). Underlying policies key on the PAIR, mirroring
`_coverage_line_dedup_keys`. Pinned by `test_i2_policy_number_is_not_a_generic_natural_identifier`.

**Location is deliberately NOT in the GL hazard key**, and this is the one place
it differs from its `_wc_class_dedup_keys` sibling: extraction put the WRONG
location on the duplicate row (`002` against class 91340, whose real location is
`001`), so keying on it would have kept both rows. Territory is the geographic
dimension that survived intact, and the first row's correct location wins the merge.

**`property_locations` was considered and DECLINED.** `_address_identity_key`
(street number + ZIP) exists and would slot straight in, but two real premises at
the same street number in one ZIP would fold and DELETE a location. The live run
needed no such merge, and `_consolidate_property_locations` already owns location
folding — a second door onto one decision is the duplication defect this codebase
keeps re-learning. Recorded in the code comment so nobody "completes" the set.

**The merge GAINS data.** The two printings are complementary — the summary block
has no reserve column, the supplemental block does — so the ACORD 125/130/131
loss grids now carry reserves that were blank before.

**Measured blast radius** (`snapshot_deterministic_fill.py`, all 17 schemas):

```
ACORD_125   filled 163->169 (+6)   ACORD_130  filled 61->64 (+3)
ACORD_131   filled  95->94 (-1)    every other form: unchanged
```

The 131's −1 is the fix working: row F loses its values because there are only
five losses. Rows D and E now carry the auto and property claims instead of
re-printing rows A and B. **Cross-row contamination should read 0 on the re-run.**

**Tests:** 12 in `tests/test_form_fill_1sep.py` (defect + guard + anti-rot).
Regression sweep: 881 passed, 0 failed.
**Revert:** remove the two key functions and the three registry lines.
**Status:** ✅ SHIPPED.

---

### I3 — The dec-page index is built, verified, and never shown to call 2  🔴

Call 1 already produced **49 label:value pairs**, mechanically verified to appear
in the document:

```
GL PREMISES/OPERATIONS PREMIUM           = $46,900
GL PRODUCTS/COMPLETED OPERATIONS PREMIUM = $14,555
AUTO COMBINED SINGLE LIMIT PREMIUM       = $18,240
EMPLOYERS LIABILITY PREMIUM              = $71,410
OTHER POLICY PREMIUM                     = $4,860
EMPLOYERS LIABILITY MODIFICATION FACTOR  = 0.94
GL COVERAGE FORM EDITION DATE            = 04 13
```

Seven of the fourteen values missing on the 131 — already extracted, then thrown
away because their boxes are named "Premium" (I1).

`_render_dec_index` produces **4,738 chars = 1.6% of the document**. It is passed
to call 2 **only** on the `DEC_INDEX_DEDICATED_PASS` path, which defaults to OFF,
and is otherwise used only to widen the evidence haystack for *verifying* answers
(`pdf_service.py:18507`) — never to *supply* them.

**Fix, two halves:**
1. Deterministic backfill — match a box to a dec-index entry by label and stamp.
   No LLM, no prompt, no cost.
2. Include the index in the call-2 prompt alongside the raw text (1.6% is cheap).
   NB: the *dedicated pass* was measured and rejected (39 calls, ~593k output
   tokens) — this is not that. See `LLMcall1-promptChange.md`.

### ⚠️ CORRECTION 1 Sep 2026 — HALF 2 WAS ALREADY SHIPPED, IN HEAD

The claim above that the index reaches call 2 "only on the `DEC_INDEX_DEDICATED_PASS`
path" **is wrong**, and it was wrong when it was written. `_fill_unmatched_with_gpt`
has a **STAGE A** that runs unconditionally whenever `dec_page_entries` exists: every
field batch is asked against the index BEFORE it walks the raw document
(`_dec_index_chunks` / `_run_index_batch`, grep `gpt_fill STAGE_A`). It is part of
CALL2_RETRIEVAL_REDESIGN (D11) and it is in `git show HEAD` — verified, not assumed.

So I3 is CLOSED. Half 1 (the deterministic label-matched stamp) shipped with I1;
half 2 was already there. **The same correction applies to I9's third bullet below** —
"the dec index is not offered as a source" is false.

**Status: ✅ CLOSED** (half 1 shipped 1 Sep; half 2 already in HEAD).

---

### I4 — The package policy number is blanked by its own guard  🟠

`_resolve_package_header_identity` blanks `Policy_PolicyNumberIdentifier_A` when
the session evidences more than one distinct policy number. On this run it counted
**eight** — including the four **expiring** policies from last year:

```
CPP 4Q 887214 26, XSU 55 210934 26, WC 9930221 26, CPL 3308821 26,
GL 7784120 25, CA 7784121 25, CF 7784122 25, XSU 55 210934 25
```

A prior-term number is by definition not this package. **ACORD 125 has 17
policy-number boxes in 6 groups** (1 this-policy, 4 other-insurance, 12
prior-coverage) — the form expects many numbers; the guard read that as a
contradiction. Built for a real defect (an auto number stamping as the package
number) and over-corrected.

### ⛔ "COUNT ONLY THE PACKAGE'S OWN LINES" DOES NOT WORK — DO NOT BUILD IT

Measured, not reasoned about (blast-radius trace, 1 Sep, driving the real
`map_facts_to_form` against the real ACORD 125 schema):

| case | today | proposed |
|---|---|---|
| numbers arrive only via `underlying_policies` | blank ✅ | **stamps the AUTO number** ❌ |
| numbers arrive only via the prior grid | blank ✅ | **stamps the AUTO number** ❌ |
| **T1 — the reported defect** | blank ❌ | **still blank** ❌ |

It breaks 5 pinned tests *and* does not fix the thing it was written for. The T1
package evidences **two** distinct contracts inside its own coverage lines — the
CPP and the separately-written umbrella `XSU 55 210934 26`. `2 > 1`, so the guard
still fires. Excluding the four expiring policies removes half the count and
changes nothing.

### ✅ THE DIRECTION THAT SURVIVES — a positive pre-gate, measured 11/11

Do **not** change the count. Add a gate *ahead* of it:

> A **package policy** is one contract covering **two or more distinct canonical
> coverage lines**. When exactly one such contract exists in `coverage_lines`
> (grouped by `_same_policy_contract`, lines canonicalised through
> `lob_canon.canon_line`), that contract IS the package policy and stamps.
> Otherwise fall through to the existing multi-source count, unchanged.

It reads a positive structural property rather than subtracting a category, so it
cannot reopen defect #70 through a fifth door. Verified against all nine
adversarial cases including the Orbin original (blank ✅) and T1 (`CPP 4Q 887214
26` ✅).

**⚠️ BLOCKED on a contradiction that must be settled first.** The exact signal
this gate reads as *"this is a package policy"*, two other functions read as
*"corrupt extraction"*:

* `_line_list_is_trustworthy` (`pdf_service.py:2748`) returns **False** when one
  number appears against 2+ lines of business — the definition of a CPP. Live on
  the T1 run: *"policy number 'cpp4q88721426' is attached to 3 different LINES OF
  BUSINESS … it cannot identify a policy"*. Downstream that costs
  `_sum_of_coverage_line_premiums` its fallback sum and pushes
  `_resolve_section_policy_identity` into its "corrupt" branch on 126/127/140.
* `_repair_coverage_lines_from_entries` (`extraction_service.py:7385`) fires on
  the same signal inside `merge_facts` and **clears `policy_number` to `None`**
  on lines the dec entries cannot settle — so the live fact set may hold FEWER
  numbers than the document printed.

**One codebase cannot hold both readings.** Settle it in one place before
touching either. Do not design this fix against a reconstructed fact set — dump
the real session first.

**Adversarial cases to write FIRST** (all nine are enumerated in the trace
report; the two that matter most): the Orbin five-candidate original must stay
blank, and the box must never carry the CURRENT umbrella's own number.

### ⛔ MEASURED ON THE REAL FACT SET, 1 Sep 2026 — DO NOT BUILD EITHER HALF

The blocker named above was investigated properly this time, against the LIVE merged
facts (`scratchpad/t1run/facts.json` → `merged_facts`, 107 keys, 8 coverage lines, 49
dec entries — the real dump the earlier note said to get). Both halves fail.

**B3 is right for the wrong reason, and fixing the reason breaks the outcome.**
The obvious repair — *"corruption is one LINE under several NUMBERS, not one number
across several lines"* — is correct about what a package policy IS, and shipping it
would be a regression:

```
coverage_lines (live, 8 entries, FOUR different contracts):
  CGL 61,455 | Property 31,205 | Auto 32,170 | Inland Marine 4,900   <- the CPP
  Umbrella 23,900        <- a separately written policy
  Employers Liability 71,410   <- the WC policy's
  Contractors Pollution 4,860  |  TRIA 1,000
                                        SUM = $230,900
  The document's stated package premium  = $148,730
      ( = CGL 61,455 + Property 31,205 + Auto 32,170 + Umbrella 23,900, exactly )
```

Declare the list trustworthy and `_sum_of_coverage_line_premiums` returns **$230,900** —
half as large again as the truth — and `_resolve_estimated_total`'s validity rule then
reads the correct stated $148,730 as arithmetically impossible. **The list genuinely
cannot be summed, for a reason the docstring never stated: it mixes lines belonging to
DIFFERENT policies with nothing to say which the package total covers.**

**And its supposed collateral damage is not there.** B3's claim that
`_resolve_section_policy_identity` takes a "corrupt" branch on 126/127/140 is **false on
the live data** — every section form resolves correctly through the dec-entry fallback:

```
126 127 130 140 186 28 -> CPP 4Q 887214 26     131 -> XSU 55 210934 26
133 138_CA 138_CO 141 160 -> blank   (lines this package does not carry)
```

**What WAS done:** the misleading warning text and docstring are corrected in place, so
the next session does not "fix" a working predicate. Behaviour byte-identical.

**I4's positive pre-gate does not survive the Orbin case either.** Reconstructed from
the docstring's own record (6C7 on Liability/InlandMarine/Automobile/Umbrella, BBC7263
on General Liability): exactly ONE contract covers 2+ canonical lines — 6C7 — so the
gate stamps **the inland-marine/auto number as the package number**, which is client
defect #1 restored. The earlier "measured 11/11" was against a reconstructed fact set,
which is exactly what the note above warned against. **The payoff is ONE box.**

**B5 folded in:** excluding the four EXPIRING policies from `_distinct_package_policies`
is unambiguously correct and measurably moves nothing (8 → 4, still > 1).

**Status:** ⛔ CLOSED AS MEASURED. Do not reopen without a real Orbin fact dump AND a
re-measurement of the sum against a stated total.

---

### I5 — `_parse_address` cannot split a comma-free address  🟠

```
"1188 Larimer Crossing Ste 400 Denver CO 80204"
  -> line1 "1188 Larimer Crossing Ste 400"   (unit never separated)
"15 Foothills Service Rd Golden CO 80401"
  -> line1 "15 Foothills Service Rd Golden"  (city lost entirely)
```

Line 2 is only written from a 4+ comma-part address (`utils/helpers.py:129`), and
city recovery needs a unit designator as its anchor — location 4 has none.
Five blank LineTwo boxes plus one missing city.

**Fix (tested 13/13 before proposing, including adversarial cases):** pull the unit
out FIRST, then split street from city on the **last** street-suffix token.

```
1188 Larimer Crossing Ste 400 Denver  ->  1188 Larimer Crossing | Ste 400 | Denver
15 Foothills Service Rd Golden        ->  15 Foothills Service Rd |       | Golden
100 Golden Rd Denver                  ->  100 Golden Rd           |       | Denver
77 Park Ave Court Denver              ->  77 Park Ave Court       |       | Denver
12 Main St Grand Junction             ->  12 Main St              |       | Grand Junction
PO Box 4417 Cheyenne                  ->  unchanged - no house number, no guess
```

The first draft took the *first* suffix and failed four real addresses. Greedy /
last-suffix is required.

### ✅ SHIPPED 1 Sep 2026 — including a regression it caused and the mitigation

Two edits, and **both were needed**:

1. **`utils/helpers.py`** — two new anchors, applied in a strict order.
   Rule 3 (`_ADDR_SUFFIX_THEN_CITY_RE`) finds the city when there is no unit;
   rule 4 (`_ADDR_TRAILING_UNIT_RE`) lifts the unit onto line 2. **Rule 4 runs
   LAST on purpose** — rule 2 uses the unit as its city anchor, so lifting it
   earlier would remove the anchor before it was used. Both require a leading
   house number, so a PO box is never split.

2. **`extraction_service._consolidate_property_locations`** — the premises group
   key now spans **line1 AND line2**.

**Edit 2 is not optional, and this is the interesting part.** C48's fold rules
depend on two suites in one building diverging inside the key: *"Two different
suites diverge before the tail … so they never fold."* That held only while the
unit sat inside line1. With edit 1 alone, `Ste 400` and `Ste 900` became the same
key and **two real premises collapsed into one ACORD 125 row — a deleted
location.** The guard test predicted it, and it fired exactly as predicted the
moment edit 1 landed alone.

Joining the two lines keeps the key **byte-identical** either way —
`normalize_address("4800 DAHLIA ST # D13")` equals
`normalize_address("4800 DAHLIA ST" + " " + "# D13")` — so a legacy session
regrouped after this change lands on the keys it already had.

**Measured blast radius** (all 17 schemas): every form that prints a mailing
address gains `MailingAddress_LineTwo_A` and loses the suite from `LineOne_A`.
**Zero fields lost a value.** On a fresh extraction the premises grid also gains
its line-two boxes and — the one that was silently broken —
`15 Foothills Service Rd Golden` now yields city `Golden` instead of burying it
in the street box.

**5 existing tests asserted `line1 == "4800 Dahlia St # D13"`** and were updated.
Each one pinned the *old shape*, not a safety property; every structural
assertion in them (row counts, city/state/zip, the two-suites case) passed
untouched. The `test_line_two_is_owned_by_the_parsed_mailing_address` assertion
was replaced with the requirement it was a proxy for — *the unit is not printed
twice* — which is now stated directly and is strictly stronger.

**Tests:** 17 in `tests/test_form_fill_1sep.py`, including the two-suites guard
and an end-to-end consolidation check (the seam, not just the function).
**Revert:** remove rules 3 and 4 from `_parse_address` **and** restore the
line1-only group key. Reverting only one of the two reintroduces the collapse.
**Status:** ✅ SHIPPED.

---

### I6 — A printed table is asked column-by-column instead of row-by-row  🟠

`_table_prefix` (`pdf_service.py:10576`) buckets table columns by the first **two**
name segments. ACORD names most columns `Root_Column` (two segments), so each
column becomes its own bucket of one and can never reach the 3-column threshold —
it falls back to `_slot_group_block`: *"find up to N separate real values in the
document, in the order they appear."* A column-wise scavenger hunt with no concept
of an entity.

Best-case measurement (assume every row cell unfilled — the most generous input the
detector can get):

| form | table-framed | column-wise fallback | single-slot |
|---|---|---|---|
| 125 | 206 cells | 136 | 206 |
| 126 | 39 | 45 | 170 |
| 127 | 239 | **329** | 62 |
| 131 | 50 | 101 | 242 |

The ACORD 127 driver schedule is not a table. Loss history on 125/131 is not a
table. The 126 products grid is not a table — which is why three years of revenue
became three product rows.

**Where table framing DID apply, cross-row contamination was zero** (126 hazards,
125 premises). That is the argument for the fix, made by the pipeline itself.

**But framing alone is not sufficient** — two failures happened *inside* framed
tables:
* `NamedInsured_MailingAddress` is framed (5 columns) and still slid — insured B
  got Aurora / 80011, which is **premises 2**, a different schedule. The row block
  says "each row is one real-world entry" and never says *from which table*.
* `GeneralLiability_Hazard` is framed (11 columns) but my fixture prints that
  schedule as two stacked blocks (identity+exposure, then rates+premiums), the way
  real dec pages do. It filled from the first and never joined the second.

### ✅ SHIPPED 1 Sep 2026 — all three parts

**Part 1 — the bucketing rule, and it is ADDITIVE BY CONSTRUCTION.**

> 1. A 2-segment prefix bucket that already reaches 3 columns is a demonstrably
>    coherent printed grid. It KEEPS its bucket, unchanged, and it is claimed FIRST.
> 2. Every column rule 1 does not claim is an ORPHAN. Orphans group by
>    **(schedule ROOT, row universe)**; 3+ of them is a table.

Measured across all 17 real schemas: **+212 columns gain row framing, ZERO lose it.**
Pinned by `test_i6_bucketing_can_only_ever_add_table_framing`, which recomputes
both rules over every schema and fails the build if rule 2 ever takes a column
away from a qualifying prefix bucket.

**Rule 2 needs BOTH halves of its key, and this was measured, not reasoned.**
Keying on the root ALONE was tried first and over-merged: it swept ACORD 140's
Spoilage limit/deductible pair into the Premises grid (breaking
`test_non_table_pair_still_uses_ordinary_repeating_group`, which exists to pin
exactly that) and put ACORD 127's per-vehicle "modified equipment" General
Information answer (rows A/B) inside the 4-row vehicle schedule. The ROW UNIVERSE
separates them by construction: a real column of a grid repeats over that grid's rows.

**The row universe is every row a column has ON THE FORM** — the rows still being
asked about PLUS the rows Pass 1/1.5 already resolved — never just the active ones.
That is precisely why the original code comment rejected matching on row sets:
different Pass 1 mechanisms fill different rows of different columns, so the ACTIVE
sets disagree run to run while the schema's do not. Taking the union makes the key a
property of the FORM, not of the run. **`already_filled` is what makes this possible,
and it is already passed in.**

The universe is widened with already-filled rows only when the base maps to ONE
repeating group. ACORD reuses a base for two roles split by tooltip — on ACORD 127
`AdditionalInterest_FullName_A/B` is the lienholder schedule and `_C/_D` is "the
other owner of the vehicle" — and widening across that split would merge the two
roles `repeating_group_key` exists to separate. Pinned.

**Part 2 — a table now names its own schedule and disowns the others.** The old row
block said *"each row is one distinct real-world entry"* and never said one entry OF
WHAT, which is how a correctly-framed `NamedInsured_MailingAddress` still pulled
insured B's city from **premises 2**. It now reads *"This is the Named Insured table.
Every row is ONE DISTINCT real-world Named Insured entry, and it must come from the
document's own Named Insured information - never from a different list"*, and when
more than one table is in the same call it names the others explicitly as off-limits.
The label is DERIVED from the ACORD name (`NamedInsured#ABC` → "Named Insured"), never
a hand-kept table, so a new schedule names itself.

**Part 3 — a table printed as two blocks.** New rule (f): *"ONE table is often
PRINTED as TWO OR MORE separate blocks - identity and exposure columns in one, rates
and premiums in another, sometimes pages apart. If a column's values are not in the
block where you found the row, look for a later block and match it to the row by that
entry's OWN identifier - NEVER by its position on the page."*

**Batch size.** Table units are indivisible (C19) and the rule makes them bigger. The
largest new atomic unit is **ACORD 127's Driver grid at 221 fields** (17 columns × 13
rows, worst case with nothing pre-filled). That is larger than any orphan unit today
but SMALLER than units the packer already accepts (`WorkersCompensation_RateClass`
154, `PropertyCoverage_Other` 143, `CommercialProperty_Premises` 112), and
`_pack_field_batches` already handles an over-cap unit by giving it its own batch.

**Kill switch:** `TABLE_ROOT_BUCKETS=0` reverts to rule 1 alone. It can only ever
REMOVE row framing, never add a wrong value.
**Tests:** 9 in `tests/test_form_fill_1sep.py` (defect, guard, anti-rot, kill switch).
**Status:** ✅ SHIPPED. Not yet measured live.

### ⬆️ WHY IT WAS THE TOP PRIORITY (owner directive, 1 Sep 2026)

It is a **call 2** problem, and call 2 is where the owner wants the effort. It
also owns two of the three biggest remaining defect clusters — the phone/SIC
slide and the fabricated products grid.

**The design, and the two things a prefix fix alone will NOT solve.**

*Part 1 — bucket columns correctly.* `_table_prefix` takes the first TWO name
segments. ACORD names most table columns `Root_Column` (two segments), so each
column becomes its own bucket of one and can never reach the 3-column threshold.
Keying on the ROOT instead is closer to the printed truth (ACORD 127's vehicle
schedule really is one wide table), but it must not drag in a per-form singleton
that merely shares the prefix — `Vehicle_Question_ModifiedEquipmentDescription_A`
is a General Information answer, not a schedule cell. A second condition is
required: the columns must share a row-letter set, or the root must be a
registered schedule family.

*Part 2 — a table must know WHICH schedule it belongs to.* Measured on the
baseline: `NamedInsured_MailingAddress` IS table-framed and still pulled insured
B's city from **premises 2** — a different schedule entirely. The row block says
"each row is one distinct real-world entry" and never says *from which table*.

*Part 3 — a wide table split across two printed blocks must be joined.* The
ACORD 126 hazard schedule prints as identity+exposure then rates+premiums, the
way real dec pages do. The pipeline filled from the first block and never found
the second.

**Baseline to beat on the re-run:** phone/SIC slide gone (6 boxes), products
grid blank (14 must-be-blank hits), and cross-row must STAY at 0.

---

### I7 — Values with no fact key at all  🟡

* `Contractors_SubcontractorsPaidAmount_A` got `$1,804,000` (the payroll). There is
  no `subcontract_cost` fact; the real `$2,145,000` exists only inside
  `gl_class_code_schedule[1].exposure_amount` with basis "Total Cost". This box
  **was** sent to call 2 — it just had no anchor, so it took the nearest labelled
  money figure.
* `BusinessInformation_ForeignGrossSalesAmount_A` got the prose
  `"no foreign gross sales"` in a money box.
* `LossHistory_TotalAmount_A` got `$129,400` — the model summed the three rows it
  could see instead of reading the stated `$568,495`.
* Underwriter name and employees-covered: never extracted.

### ✅ SHIPPED 1 Sep 2026 — 2 of 3, and the lever already existed

**Do not build a new resolver here.** `_enforce_numeric_meaning_gate` (RC2,
2026-08-15) exists to blank exactly this: a gap-filled amount whose witnesses all
carry a DIFFERENT category. It classified the field correctly ("cost", from
`subcontractors` in its own name) and stood aside anyway, because **$1,804,000 had no
witness at all**. The gate consulted dec-page entries, the GL schedule, coverage lines
and three hard-coded fact keys — and the payroll is a plain scalar fact.

**(a) Every CATEGORISED scalar fact is now a witness.** The fact KEY carries the
category, read by the same `_amount_category` primitive the dec labels use — no second
vocabulary, and a new fact classifies itself (`payroll` → payroll, `total_revenue` →
sales, `subcontract_cost` → cost, `gl_deductible` → deductible).

Only a value that is ONE amount end to end is taken (`_SINGLE_AMOUNT_RE`). A composite
like `gl_limits` ("each occurrence $1,000,000; aggregate $2,000,000") would otherwise
register the digits of the whole string as one nonsense figure — **the exact
`_currency_magnitude` mistake C23 was written for.** Pinned.

Measured on the live values: the wrong `$1,804,000` is blanked, the real `$2,145,000`
survives (witnessed as a cost twice — the fact and the GL row whose basis is Total
Cost), and revenue in a gross-receipts box is untouched.

**Careful — a new witness can only ever cause MORE blanking**, so the ordinary case is
pinned by its own guard test. The known cost: a building VALUE that legitimately
equals a building LIMIT is now blanked in the limit box. That trade already existed
for any document whose dec page prints the value; this extends it to sessions where
the index missed it. Consistent with blank-over-wrong.

**(b) A sentence is not an amount.** `no foreign gross sales` in a money box is now
blanked. Deliberately narrow — **three or more words AND a negation cue AND no digit
anywhere** — because "Included", "Statutory", "None" and "Not applicable" are ACORD's
own answers for an amount box and every one of them must survive. All four pinned.

**(c) NOT DONE — `LossHistory_TotalAmount_A` summed 3 rows instead of reading the
stated $568,495.** There is no `loss_total` fact and creating one is a call-1 change.
Owner directive 1 rules it out. Same for the underwriter's name.

**Tests:** 8 in `tests/test_form_fill_1sep.py`.
**Revert:** remove the scalar-fact witness loop and the negated-prose branch.
**Status:** ✅ SHIPPED (a + b). (c) blocked on a fact that cannot be created.

---

### I8 — The 126 products grid is fabricated whole  🟡

12 must-be-blank violations, all in one grid, on a contractor whose document says
*"The applicant manufactures no products."*

```
ProductName_A            = "Roofing Contractor."
AnnualGrossSalesAmount_A = $9,410,000     (the revenue)
UnitCount_A / _B / _C    = 51 / 17 / 5    (employees, fleet, ?)
InMarketMonthCount_B     = 04/02/2009     (the business start date)
ExpectedLifeMonthCount_B = 20             (the warranty years)
IntendedUse_B            = "roof survey"  (the drone sentence)
```

Root cause is I6 (each of the 7 columns is its own one-column bucket) compounded by
phantom-row suppression acting only on positive evidence — with no products
schedule at all there is nothing to suppress against.

### ✅ ROOT CAUSE SHIPPED (I6) + a prompt rule. NO BLANKING RULE — and why not.

The root cause named above **is** I6, and I6 shipped: all seven product columns are
two-segment names, so each was its own one-column bucket, and they are now ONE
row-framed `ProductAndCompletedOperations#ABC` table that says which schedule it is.

**Plus the missing instruction.** The row block told the model what to do with FEWER
entries than rows and never what to do with NONE — on a document that says *"The
applicant manufactures no products."* New rule (c) tail: *"If the document describes
NO entry of this kind at all - or says there are none - return NOTHING for this table:
no rows, no cells. An empty table is the correct answer to a schedule the applicant
does not have."* Generic across every table, zero cost.

**The deterministic blanking rule was DESIGNED AND NOT BUILT, deliberately.** The
candidate was "reject a table cell whose value is already stamped elsewhere on this
form in a different family" — which kills every one of the live violations
($9,410,000 = the revenue, 51 = the employee count, 04/02/2009 = the business start
date). It can also blank real data (a location's city legitimately equals the mailing
city), and **the live gap-fill output is not in the repo**, so the false-positive rate
cannot be measured. Writing a value-blanking rule with no measurement is the thing
this file's own quality bar forbids. The re-run measures I6's effect first; baseline
is 14 must-be-blank hits in that grid.

**Status:** ✅ root cause + prompt shipped. Blanking rule deferred to measurement.

---

### I9 — Call 2 answers about half of what the document actually states  🟡

Of the 45 key expectations routed to call 2, it answered 24 (**53%**). Across all
533 fields it was asked, it put a value in 84 (**16%** — but most of those 533 are
optional boxes the document genuinely does not address, so 16% is not the quality
number; 53% is).

Contributors, not yet separated:
* No retrieval — every call carries the whole 297k-char document (~74k tokens) and
  the model must locate a value in 70 pages. See `improving-ll.md` C21.
* The dec index (I3) is not offered as a source.
* Evidence-gate attrition on Yes/No answers — the four safety-programme boxes and
  their 126 twin all came back blank off one real sentence. **Suspected** the
  Yes-quote reuse cap (`_EVIDENCE_YES_QUOTE_REUSE_MAX=1`), not proven.
  **Cheap experiment:** re-run with `EVIDENCE_YES_QUOTE_REUSE_MAX=12`. If the boxes
  fill, it is confirmed and it is a two-line fix.

### ⚠️ TWO CORRECTIONS, AND WHY NO CODE CHANGED (1 Sep 2026)

* **"The dec index is not offered as a source" is false.** STAGE A asks every field
  batch against the index before it walks the document, unconditionally, and it is in
  HEAD. See the I3 correction above.
* **"No retrieval" is stale.** `CALL2_RETRIEVAL_REDESIGN.md` shipped chunk routing and
  family-partitioned batches (D4). The document is still large, but the call is no
  longer a blind sweep.

**The reuse cap was NOT changed, and that is a decision, not an omission.** Two
structural refinements were designed and both fail:

1. *"Count DISTINCT QUESTIONS, not distinct fields"* — real (two forms asking one
   question share a quote legitimately), but it does not explain the reported symptom.
   The four safety-programme boxes are four DIFFERENT sub-questions.
2. *"Reuse is free within one question GROUP (the shared name prefix)"* — this would
   make reuse free across the entire `..._Question_...` family, which is exactly where
   the borrow happens. It reopens the false-N/false-Y flood the cap was built to stop.

`_EVIDENCE_YES_QUOTE_REUSE_MAX=1` was added after a measured live defect. Loosening it
on reasoning alone, with no A/B, is the mistake this file exists to prevent. **Run the
env-var experiment; it is one run and it settles the question.**

**Status:** OPEN — an experiment, not a code change.

---

### I10 — Yes/No answers jitter run-to-run, and an endorsement TITLE can ground a "Yes"  🟡

Two runs of the **identical document**, three questions that moved:

| ACORD 126 question | run 1 | run 2 | truth |
|---|---|---|---|
| Vendors coverage required? | blank | **Y** | the document never mentions vendors coverage |
| Does applicant lease equipment to others? | Y | **blank** | Y — the document says so plainly |
| Do you rent or loan equipment to others? | Y | **blank** | Y |

So the model **lost two correct answers and gained one fabrication** between two
runs of the same file. That is the honest size of Y/N variance today.

The fabricated "Y" is grounded on `CG 20 10 12 19 Additional Insured - Owners,
Lessees Or Contractors` — an endorsement **title** sitting in the noise pages.
The evidence gate already refuses a Yes grounded on an *exclusion* title
(`_EXCLUSION_TITLE_RE`); an additional-insured endorsement title is the same
shape — a form name, not a statement about the applicant — and is not covered.

### ✅ SHIPPED 1 Sep 2026 — the form NUMBER, not the title

`_quote_is_a_form_citation`: a "Yes" whose grounding quote **BEGINS with a printed ISO
form number** is a line off the forms-and-endorsements schedule, not a statement about
this applicant — whatever the title says.

**This is NOT the "endorsement titles as proof" rule that `pdf_service`'s ACORD 127 Q8
block records as measured-and-rejected.** Both candidates there judged the TITLE's
vocabulary and lost real data doing it (one rejected *"Subcontractors are required to
carry coverage."*, a sentence C46 recorded as wrongly blanked). This judges only the
printed form NUMBER at the start, which no applicant statement carries.

It reuses `text_selection._ISO_FORM_CODE_RE` — the same definition of a form number the
text selector drops standard-form pages by — so there is one answer in the codebase to
"is this a form code?".

Anchored at the START on purpose, and Y-only. *"the applicant had a molestation claim
in 2023; CG 21 46 was added at renewal"* is a real Yes that merely MENTIONS a form and
must survive; over-firing on the "No" side deletes correct answers with no fallback.

Measured: **4 of 4 form citations rejected, 0 of 8 real quotes lost** (the 8 are real
affirmative quotes from past live runs plus sentences a previous session measured as
wrongly blanked). All 12 pinned individually.

**Status:** ✅ SHIPPED. The `I9` half of this investigation is still an experiment.

---

## 3b. THE HAZARD RATES — re-planned, because the call-1 prompt is off limits

18 of the ~51 remaining boxes are the ACORD 126 hazard grid's LOC #, HAZ #, two
rates and two premiums. The original plan was to extend call 1's extraction
schema to capture them. **That plan is dead** — owner directive 1.

What is true about them, measured:

* they are **not** in `dec_page_entries` (checked: `3.412`, `44,970`, `8.114` all
  absent), so the I1/I3 carve-out cannot reach them;
* they **are** printed in the document, in a second stacked table block;
* `GeneralLiability_Hazard_*Rate_*` and `*PremiumAmount_*` are blocked by
  `_is_nonfillable_field`, so they never enter `unmatched`;
* and even if they did, `_RAW_TEXT_SKIP_PATTERNS` drops them inside
  `_fill_unmatched_with_gpt`, **and** the gap-fill prompt says *"5. Do NOT fill
  premium/rate/underwriter-computed fields — omit them."*

**So there are THREE independent gates between these boxes and an answer.** Any
call-2 route has to open all three, in the right order, and only for a grid whose
rates the document actually prints. That is a real piece of work and it belongs
AFTER I6 — I6's part 3 (joining a table split across two printed blocks) is the
same problem seen from the other side, and may make this one much smaller.

**Do not attempt this by loosening `_is_nonfillable_field` globally.** See the ⛔
block under I1 for what that costs.

### ✅ 6 OF THE 18 SHIPPED 1 Sep 2026 — LOC # and HAZ #, deterministically

**Two of those "18 rate/premium boxes" were never rate or premium boxes at all.**
`GeneralLiability_Hazard_LocationProducerIdentifier` (LOC #) and
`..._HazardProducerIdentifier` (HAZ #) were blocked by the broad `ProducerIdentifier`
substring in `_is_nonfillable_field`, which exists for AGENCY-assigned codes. Neither
is one — ACORD's own tooltips read *"the location number of the risk's location"* and
*"a unique (within location) number distinguishing this unit-at-risk from the others"*.
**The identical carve-out was already made for
`CommercialStructure_Location_ProducerIdentifier_` one form over**, for the same reason,
in the same function.

* **LOC #** is the `location` key `gl_class_code_schedule` has carried since v1 and
  **nothing ever read**. No extraction change, no LLM.
* **HAZ #** is DERIVED from ACORD's own definition — this row's ordinal WITHIN its
  location — and only when the row states a location. A naive ROW ordinal would print
  1/2/3; the three T1 rows are at three different locations, so the answer is
  001/001/001 and the naive version is wrong on every row but the first. Zero-padded to
  the location's own width, because a document that writes LOC 001 writes HAZ 001.

Measured on the live schedule: **001/001, 002/001, 004/001** — matching the answer key
exactly; two hazards at one location correctly number 001/002; a row with no location
falls through to gap fill rather than being labelled by a guess; a row past the end of
the schedule stays blank (C46's phantom-row rule).

**Blast radius, all 17 schemas (`snapshot_deterministic_fill.py --diff`): 6 fields
gained, 0 LOST A VALUE, 0 re-routed, 16 other forms byte-identical.**
Guarded by a test that sweeps all 17 schemas for any `NationalIdentifier` /
`CustomerIdentifier` / `StateLicense` / `Signature` / `_Initials` field this change
might have opened. None.

### 🔄 OWNER RULING 1 Sep 2026 - "LEAVE THEM BLANK" WAS REJECTED

Verbatim: *"can we not find a way to fix these properly, can we not do anything,
and dont just pin it to acord 126 issue, this is bigger and more forms might have
this issue as well. So, i need you to find a solution for related issues like
these."*

So this is no longer a decision to be taken - it is **a design problem to be
solved, generically, across all 17 forms**. The constraints are unchanged and
they are what makes it hard: call 1 is frozen, the rates are not in
`dec_page_entries`, three independent gates block the fields, and every previous
attempt to let a model answer a rating box produced junk.

### ⛔ THE GRID-PARSER ROUTE WAS DESIGNED, ADVERSARIALLY REVIEWED AND REJECTED

Two independent designs were built and each was judged twice (2026-09-01,
11 agents, ~2.4M tokens). **Three of the four verdicts were REJECT.**

| design | verdicts |
|---|---|
| Row-Anchored Column Proof — locate the row by the cells we already stamped, solve the header→column assignment under hard constraints, stamp only on a unique solution that reproduces every known value | REJECT (2), REJECT (3) |
| The Printed Header Contract — bind the printed header to ACORD column names by ACORD's own tooltip vocabulary as a 1:1 assignment, prove it by replaying the columns we already fill | REJECT (3), SHIP_WITH_CHANGES (6) |

**THE KILLER, and it is the ordinary case rather than an edge case: a RENEWAL.**
On a renewal the broker submits the EXPIRING carrier's coverage-part declarations,
and that is very often the ONLY place a full classification schedule is printed.
Both designs prove their column binding by replaying the facts we already hold —
so the proof CONFIRMS the expiring grid, and the design stamps **last year's rates
as this year's**. The self-verification is confirming, not discriminating, and that
is structural: no threshold fixes it.

**This codebase has already fixed that exact defect class twice** (CLAUDE.md RC1b:
*"RULE 1's current policy IS the expiring dec on a renewal"*), and R1 above is the
third time. A grid parser would reintroduce it at 110-field scale.

Other measured objections worth keeping:
* the tooltip vocabulary is not ACORD's declared identity — the header cell
  `PAYROLL BASE` scored a binding to `..._TerritoryCode` because that column's
  tooltip contains the word *"based"*;
* a value-shape test cannot separate a premium from an exposure — `$42,044` and
  `1,318,000` are the same shape, so "the last candidate standing" binds a rating
  box with zero name evidence;
* the real carrier package prints a TWO-LINE header
  (`271page-testdec.txt:6076-6077`), which promotes a data row to header and
  disarms the cross-grid conflict check entirely.

**Do not rebuild this without solving PROVENANCE FIRST** — a printed grid must
carry an identity (which policy, which term, which coverage part) resolved from
its own page context, and must be required to AGREE with a fact the wrong grid
would DISAGREE with. Positive-anchor replay alone is structurally incapable of it.

### ✅ WHAT THE INVESTIGATION DID FIND — 40 FIELDS ALREADY BOUND AND UNREACHABLE

**Verified independently, not taken on the agent's word.** Four
`_SCHEDULE_REGISTRY` bindings are already written, already point at live facts,
and **can never fire, because `_is_nonfillable_field` runs BEFORE the registry
lookup** (`pdf_service.py:13072` vs `:13086`):

| binding | fact | fields | forms |
|---|---|---|---|
| `WorkersCompensation_RateClass_Rate` | `wc_class_codes.rate` — **an extracted v17 fact** | 14 | 130 |
| `WorkersCompensation_RateClass_LocationProducerIdentifier` | row label | 14 | 130 |
| `WorkersCompensation_Individual_LocationProducerIdentifier` | row label | 4 | 130 |
| `Location_ProducerIdentifier` | `property_locations.location_number` — live | 8 | 101/130/133/160 |

This is the SAME shape as the §3b LOC #/HAZ # fix already shipped and measured
(+6 fields, 0 lost): a printed ROW LABEL blocked by a substring meant for agency
credentials. ACORD's own tooltips settle it — *"The producer assigned vehicle
number"*, *"The building number for the premises"*. **14 of the 35 Group B
columns are `*ProducerIdentifier` row labels, not credentials.**

**NOT SHIPPED YET, deliberately:** none of these 40 fields appears on ACORD
125/126/131, so it cannot move run 4's number and would only muddy attribution
again. Queued for straight after.

### THE CENSUS, for whoever picks this up

225 per-row schedule fields (50 columns) are refused across the 17 schemas.
**176 fields / 35 columns are GROUP B** (the prize; only 4 fill today),
31 fields / 10 columns are GROUP A (stay blocked forever), 18 / 5 are
form-attachment metadata. `_is_nonfillable_field` is the ONLY gate that matters:
`_RAW_TEXT_SKIP_PATTERNS` is a strict subset of it, and prompt rule 5 never sees
the class at all.

**Three traps recorded so nobody trips them:**
* `NamedInsured_SignatureDate_A..C` (137) looks like an ordinary date column and
  is the ATTESTATION date. Stays blocked.
* `Producer_NationalIdentifier_A..C` (137_CO) looks like a per-row identifier and
  is the agency NPN repeated on three state pages. Stays blocked.
* `NamedInsured_Initials_A..E` (131) has FIVE row letters and is five STATE
  attestation boxes, not a grid — its tooltips name Louisiana and New Hampshire.
  **A row-letter suffix does not prove a schedule row.**
* And one in the other direction: `CommercialProperty_Premium_OtherDescription_A..D`
  (160) is free TEXT caught by the word "Premium" sitting in its parent's name.

**A cohort test almost separates Group A from Group B structurally** (columns
sharing a first name segment and an identical row-letter set: Group B scores
3-65, Group A scores 1-2) — but ACORD 137_CO's signature family scores 3, so
**audience, not structure, must remain the Group A gate.**

### 🟠 UNTIL THAT LANDS, THE 12 ARE STILL OWNED BLANKS

The four rate/premium columns × 3 rows. Everything about them is now established:

* `gl_class_code_schedule` has **no key** for a rate or a premium. Adding one is a
  call-1 extraction-schema change — **ruled out by owner directive 1.**
* They are **not** in `dec_page_entries` (checked: `3.412`, `44,970`, `8.114` absent),
  so the I1/I3 carve-out cannot reach them.
* Reaching them from call 2 means opening THREE gates (`_is_nonfillable_field`,
  `_RAW_TEXT_SKIP_PATTERNS`, and the prompt's rule 5) against a standing ruling —
  *"producers rate, we don't"* — backed by every live run stamping junk in rating boxes.

**Pinned as owned blanks by `test_3b_the_rate_and_premium_columns_are_still_owned_blanks`
so they cannot start filling by accident.** Same shape as the rating MOD box: two
decisions for the owner, both recorded, neither taken as a drive-by.

---

## 4. THE POLICY DECISION — owner instruction, 1 Sep 2026

> *"If any field is not filled by the deterministic pass, it should go to call 2
> definitely, without any chance of not letting it go there."*

Today 358 boxes (30%) are withheld. Each withholding resolver was added **after** an
LLM invented a value there and it shipped on a signed form — a fabricated underlying
policy, a phantom vehicle row, one policy number sprayed across three prior-coverage
columns.

**Agreed direction: ask about everything, but keep the acceptance test.**
Separate the two decisions the code currently conflates:

| today | proposed |
|---|---|
| "we won't ask, because the answer might be wrong" | **always ask** |
| (no role check on what comes back) | **accept only what is grounded in the document AND whose dec-index label matches the box's own meaning** |

The second half is the part that makes the first half safe, and it is exactly what
I3 unlocks — the index carries **labels**, so it can answer *"does this value belong
in this box?"*, not merely *"does this string exist somewhere?"*. Presence alone has
already been recorded in `CLAUDE.md` as necessary-but-not-sufficient; the label is
the structural second condition.

**Risk if we open the 358 without the label gate:** we reintroduce the exact defects
those resolvers were written for. Do not ship half of this change.

---

## 4b. BUGS FOUND WHILE IMPLEMENTING — 1 Sep 2026

Reported because they were found, not because they were asked for. Two are mine,
caught before shipping; four are pre-existing and still open.

### B1 — MINE, caught by a guard test: two suites collapsed into one premises
Lifting the unit designator out of line1 (I5) silently made `Ste 400` and
`Ste 900` the same premises group key, **deleting a real location from ACORD
125**. Predicted before writing the code, pinned by
`test_i5_two_suites_in_one_building_stay_two_premises`, and it fired the instant
the parser change landed alone. Fixed by widening the group key to line1+line2.
**Shipped fixed. This is the single most dangerous thing in this batch, and it
is exactly what a "small, self-contained" change looked like from the outside.**

### B2 — MINE, in the scorer: an unchecked box read as an affirmative "No"
`score_form_fill.blank()` normalised before testing for emptiness, so pikepdf's
`/Off` (what every untouched checkbox reads as) folded into the false-ish set and
came back as `"no"`. Effect: a missing "Yes" scored WRONG instead of MISSING, and
an untouched must-be-blank box scored as a VIOLATION. It inflated the first
baseline by 1 wrong and 2 must-be-blank hits. **Fixed** — `blank()` now tests the
raw value first.

### B3 — PRE-EXISTING, live on this very run: a real package policy is called "corrupt"
`_line_list_is_trustworthy` (`pdf_service.py:2748`) returns False when one policy
number covers 2+ lines of business, which is the *definition* of a commercial
package. The T1 run emits it live:

```
coverage_lines: policy number 'cpp4q88721426' is attached to 3 different LINES OF
BUSINESS (BusinessAuto, CommercialGeneralLiability, CommercialProperty)
- it cannot identify a policy, so the per-line premiums cannot be de-duplicated
```

Downstream cost: `_sum_of_coverage_line_premiums` returns None, so
`_resolve_estimated_total` loses both its fallback sum and its sanity check, and
`_resolve_section_policy_identity` takes its "corrupt" branch on ACORD 126/127/140.
**Not caused by anything in this batch.** It is also the blocker on I4.

### B4 — PRE-EXISTING: the repair pass can delete real policy numbers
`_repair_coverage_lines_from_entries` (`extraction_service.py:7385`) fires on the
same signal as B3, inside `merge_facts`, and **sets `policy_number` to `None`** on
any line the dec entries cannot settle unambiguously. On a genuine package that
means the stored facts may carry fewer numbers than the document printed.
**Consequence for anyone working here: never design against a reconstructed fact
set — dump the real session.**

### B5 — PRE-EXISTING: `_distinct_package_policies` counts last year's policies
It reads `prior_coverage_by_line` as evidence of what THIS package is. A prior-term
number is by definition not this policy. Four of the eight numbers it counted on
the T1 run are expiring contracts. Folded into I4's redesign rather than fixed
separately, because fixing it alone does not move the box (measured).

### B7 — MINE, in the scorer: a LOC # of "1" was compared as a checkbox
`TRUEISH` contained `"1"`, `"x"` and `"on"`, so `norm("1")` returned `"yes"` and
location 1 scored WRONG against an expected `"001"` while locations 2-4 scored
correct. Fixed: **the key decides the type.** Only a boolean WORD on the expected
side (`y/yes/n/no/true/false`) triggers a boolean comparison; `1`/`x`/`on` are
how a ticked box reads out of the PDF and are never how a key states an
expectation. Self-checked against 14 pairs.

### B8 — MINE, in the answer key: ACORD 131 has no occurrence-date column
The key's 131 loss row-set mapped its `date` column to `LossHistory_ClaimDate`.
Checked against the real schema: **131 has no `LossHistory_OccurrenceDate` at
all**, and `ClaimDate`'s own tooltip reads *"the date the claim was filed"* — a
different fact this document never states. The key was demanding a value the form
has no box for, reporting 5 phantom missing cells on a grid that was in fact
perfect. Removed; the 131 loss grid scores **20/20**. ACORD 125 keeps its `date`
column because it really does print `LossHistory_OccurrenceDate`.

### B9 — MINE, found AFTER the suite went green: the location table deleted the suite
`schedule_capture.SCHEDULE_DEFS["property_locations"]` had **no `address_line2`
column**. `rows_from_facts` rebuilds every row from the columns alone and
`arq_service` writes the result back over `facts[list_key]` **wholesale** — so a
sub-field with no column is destroyed the first time anyone opens the location
table. Harmless while the unit sat inside line1; with the unit now on line two it
**deleted every suite number in the file**, and `*_PhysicalAddress_LineTwo` would
then stamp blank on ACORD 125/130/133/140/160/28 after the first save.

Worse: with `dedup_keys=("address_line1","address_city")`, Suite 100 and Suite
200 in one building became byte-identical rows and `validate_rows` returned
`duplicates: [1]` — telling the client their two premises are the same one.
**Fixed**: `address_line2` is now a column and a dedup key. Measured round-trip:
suites preserved, `duplicates: []`.

### B10 — MINE, same review: a real premises deleted as "the producer's office"
`_is_location_entry` compared `normalize_address(line1)` against the producer's
line1 key. With the unit lifted off both sides, the agency's Suite 400 and the
INSURED's Suite 100 in the same building collapsed to one key. **Measured: two
premises in, one out — the insured's own location silently deleted.**

Fixed the same way as the grouping key: the comparison spans line1 + line2. This
also settles the *inverse* defect recorded in the code from 2026-08-12 (the
producer's office printing as premises #4 because the suite landed on line2 for
one side and line1 for the other). Same building **and** same unit is the
producer; same building, different unit is not.

> **The standing lesson from B1 / B9 / B10.** Moving a value between two fields
> breaks *every* comparator that reads only one of them. There were **three**
> such doors — the grouping key, the schedule columns, and the producer-office
> check. I found one by prediction, and the full suite was green with the other
> two still broken. When you relocate a value, grep for every reader of the field
> it left.

### B11 — MINE, and it took 16 UNRELATED TESTS DOWN
My I6 kill-switch test called `importlib.reload(services.pdf_service)` to pick up an
env var. The module defines identity sentinels — **`_SCHED_SKIP` is a bare
`object()`** — so a reload leaves every other module holding the OLD sentinel while
the resolvers return the NEW one, and every `is _SCHED_SKIP` comparison in the codebase
silently starts returning False. The full suite went from 1 failure to 18; all 16 new
ones passed file-at-a-time, which is exactly what makes this look like the documented
cross-test pollution and not like a bug someone just introduced.
**Fixed** — the flag is monkeypatched on the module and nothing is re-imported.
**Standing rule: never call `importlib.reload` inside a test in this suite.**

### B12 — PRE-EXISTING, latent, exposed by I6: the retrieval recorder counted column LABELS as fields
`test_call2_retrieval.Recorder.general_fill_batches` harvested field names with
`^\s+- (NAME)`. A TABLE block does not list its fields that way: it prints a
`Columns:` section of short COLUMN labels ("GenderCode", "BirthDate") and then the real
names under "Exact field names per row". So `family_of("GenderCode")` returned
`"GenderCode"` — a family that does not exist — and every table block registered as a
topically-mixed batch. Harmless while few tables were detected; I6 made table framing
the common case and the artifact took over the measurement, failing two D4 assertions
that were about the CODE. **Fixed in the test**: the Columns section is excluded and the
per-row lists are parsed. The code was never wrong.

### B13 — DATA TRAP: the saved live facts have had the dec index PURGED
`scratchpad/t1run/facts.json` and `facts_deduped.json` both carry
`dec_page_entries: None` — `PURGE_DEC_INDEX_AFTER_GENERATION` defaults to `1` and the
dump was taken after generation. **`snapshot_deterministic_fill.py` therefore cannot
measure anything that reads the dec index**, including I1's rating carve-out, which
shows as `owned_blank` in every snapshot regardless of the change. Not a bug in the
code; a trap that will waste an hour. (`facts.json`'s `merged_facts` DOES carry all 49
entries — it is the top-level convenience copy that is empty.)

### B6 — DOCUMENTATION: the suite baseline in `CLAUDE.md` is stale
It records "4824 passed / 1 failed". Actual at this commit: **5062 passed, 1
failed, 14 skipped, 1 xfailed**. Same single known failure. Worth correcting so a
future session does not read growth as regression.

---

## 4h. BATCH 4 - THE REMAINING FIXES, AND ONE MEASURED REFUSAL (2 Sep 2026)

### Y1 - the reuse cap counts ANSWER UNITS, not fields ✅ SHIPPED

ACORD asks some questions as ONE question plus a row of option boxes:

```
2. IS A FORMAL SAFETY PROGRAM IN OPERATION?            -> answered Y
   [ ] SAFETY MANUAL [ ] SAFETY POSITION [ ] MONTHLY MEETINGS [ ] OSHA   -> ALL BLANK
```

One document sentence legitimately ticks all four - it is ONE answer to ONE
question. But `_quote_use_count` counted one use per FIELD, so the cluster size
was 4, `4 > _EVIDENCE_YES_QUOTE_REUSE_MAX` (1), and every one was blanked -
identical on runs 3 and 4, on a form that answered the parent question Y and then
left its options empty.

**`_checkbox_option_group`**: a `/Btn` whose tooltip does NOT carry a question of
its own (no `response to the question,`, no "Enter Y for a Yes response" prefix)
is an OPTION of the question named by its parent name segment. The reuse cap now
counts one use per (option-group | field).

**The exclusion is the whole safety argument.** Each `..._Question_<code>Code_`
field is a DIFFERENT question, where a shared quote IS a borrow - the false-Yes
flood the cap was built for. Swept all 17 schemas: 1,413 checkboxes receive an
option group, **0 of them carry their own question**. This SUPERSEDES the I9
`EVIDENCE_YES_QUOTE_REUSE_MAX=12` experiment - that would have loosened the cap
for every field; this loosens it for nothing and fixes the counting.

### L1 - TOTAL LOSSES is the schedule's arithmetic or a blank ✅ SHIPPED

Runs 3 and 4, identical: the model summed the THREE rows the ACORD 125 grid
displays ($129,400) while the schedule holds FIVE losses and the document states
$568,495. Now DERIVED - paid + reserved over every extracted row - which
reproduces the stated figure to the dollar. Right-or-blank: a row with no
parseable paid figure, or no schedule at all, makes the box an OWNED BLANK
(gap fill can only re-run the defect). Reserved is optional per row; paid is not.

**Built as a second resolver first, and the ownership contract test caught it** -
`_resolve_loss_history_summary` already owns the summary row, and two doors onto
one field is the documented duplication defect. The derivation now lives INSIDE
the existing owner; `test_run_20260813h`'s "opens up with a real signal" pin was
updated - the box now opens up STRONGER than gap fill.

### S1 - a bound schedule column is DATA, not an owned blank ✅ SHIPPED

The §3b finding, shipped: `_is_nonfillable_field` ran BEFORE the
`_SCHEDULE_REGISTRY` lookup, so 4 binding families (40 fields) that already
pointed at live facts could never fire - `WorkersCompensation_RateClass_Rate` →
`wc_class_codes.rate` (an extracted v17 fact), two WC location row-labels, and
`Location_ProducerIdentifier` → `property_locations.location_number` (101/130/133/160).

**The order is the whole fix.** The registry wins only when it HAS a value; no
value and the box stays exactly as blocked as before, so a rate can only ever be
TRANSCRIBED from the extracted schedule and the model is still never asked
(pinned: nothing the predicate blocks enters `unmatched`). Group A swept across
all 17 schemas: no signature/initials/licence/agency field is registry-bound.

### J1 - one schedule printed as two buckets is ONE table ✅ SHIPPED

Run 4's diagnosis: `NamedInsured_MailingAddress` qualifies as a table by itself
(rule 1) while the identity columns form the orphan bucket `NamedInsured#ABC` -
one printed schedule asked as TWO tables, and the address half returned nothing
for rows B/C (12 of ACORD 125's 20 remaining blanks).

**TABLE_JOIN**: a legacy bucket merges into an orphan bucket sharing its ROOT and
its ROW UNIVERSE. It can only MERGE two tables that each already qualified - it
never promotes an unframed column, so the additive property holds and ACORD 140's
Spoilage pair stays unreachable. Guarded: ACORD 127's 4-row vehicle schedule can
never absorb the 2-row `Vehicle_Question` pair (root shared, rows not).

**Fallout handled, all three named:** the "disowns the others" test now uses two
genuinely different schedules (its old second table was this very split - the
join fixing it was the point); two batching pins were geometry-updates
(the C29 strict-reduction claim is preserved under `TABLE_ROOT_BUCKETS=False`,
the geometry it was measured in; the >40-field exception now accepts one
SCHEDULE ROOT, the join's own key); and `test_batch_packing_and_budget`'s
recorder had B12's column-label bug - **the second copy of it** - now fixed the
same way.

### I8 - the borrowed-value backstop: MEASURED, AND THE ANSWER IS NO ⛔

The rule everyone reaches for - "reject a table cell whose value already appears
in a different family on the same form" - kills every live products-grid
violation. Measured over TWO live runs against the answer key before building:

```
TRUE POSITIVES  (key says must-be-blank, rule refuses):   0
FALSE POSITIVES (key EXPECTS the value, rule destroys):  54
```

Every mailing address, every physical address, every prior policy number and
every effective date legitimately appears in 2+ families on a real form. The
grid's fabricated cells never trip it because the model REWORDS what it borrows
("Roofing Contractor" as a product name is not a verbatim copy of anything).
**0/54. Do not build it.** Pinned by
`test_i8_the_borrowed_value_rule_stays_unbuilt`, which greps the module - remove
that test only WITH a new measurement.

---

## 4g. RUN 4 - THE FIRST CLEAN A/B (2 Sep 2026)

Session `e5c32ea2`. **Rule 8 applied first**: the facts were dumped and diffed
against run 3 BEFORE any score was read. Only **2 of 100 keys differ** —
`_scoped` metadata, and `coverage_lines`, which is R1's own repair working inside
the merge. Everything else is byte-identical, so run 3 → run 4 isolates batch 3.

| | run 3 | run 4 | |
|---|---|---|---|
| correct | 149 / 220 (67.7%) | **158 / 220 (71.8%)** | +9 |
| wrong | 10 | **2** | −8 |
| missing | 55 | 54 | −1 |
| owned blank | 6 | 6 | — |
| must-be-blank hit | 7 | **13** | +6 ⚠️ |
| precision | 93.7% | **98.8%** | +5.1 |
| ROW-CELL | 71/77 (92.2%) | 71/77 (92.2%) | held |
| cross-row | 0 | **0** | held |

Per form: **125** 96→**103** correct, wrong **10→2**, precision 90.6→**98.1%**.
**126** 35→**37** correct, wrong 0, blank-hits 7→**13**. **131** 18→18 (net zero -
gains and losses cancelled).

### R2 WORKED — the three-row table snapped into alignment

Every identity column of the named-insured schedule is now right on all three rows:

```
                        run 3                      run 4
PhoneNumber_A     (303) 555-0147  (contact's)  ->  (303) 555-0142  ✅
PhoneNumber_B     (303) 555-0142  (A's)        ->  (719) 555-0178  ✅
PhoneNumber_C     (719) 555-0178  (B's)        ->  (720) 555-0133  ✅
SICCode_B / _C          blank / 1751 (B's)     ->  1751 / 7359     ✅
NAICSCode_B / _C        blank / 238350 (B's)   ->  238350 / 532412 ✅
TaxIdentifier_B / _C    blank / 87-2205518     ->  87-2205518 / 88-1740662 ✅
```

**One wrong deterministic cell had been moving nine of them.** That is the whole
finding, and it is why R2 was worth more than its one-line diff suggests.

### R1 WORKED — every policy-number box now names this year's policy

```
ACORD 125 OtherPolicy_A   GL 7784120 25  ->  CPP 4Q 887214 26  ✅
ACORD 125 OtherPolicy_B   CF 7784122 25  ->  XSU 55 210934 26  ✅
ACORD 125 OtherPolicy_C   CA 7784121 25  ->  CPL 3308821 26    ✅
ACORD 126 header          GL 7784120 25  ->  CPP 4Q 887214 26  ✅
ACORD 131 header          XSU 55 210934 25 -> XSU 55 210934 26 ✅   (EXPIRING POL # correctly keeps ...25)
```

### THE ONE NUMBER THAT WENT THE WRONG WAY, AND IT IS ALL ONE GRID

Must-be-blank hits 7 → 13. **All 13 are the ACORD 126 products grid; ACORD 125 and
131 are at 0 of 18 and 0 of 24.** It is now the ONLY source of wrong values left in
the package. Across four runs of the same document the grid has fabricated
**12 → 14 → 7 → 13** cells. The batch-2 prompt rule (*"an empty table is the correct
answer"*) reduced it once and does not hold it — the grid is pure gap fill on
unbound columns and the model is not deterministic.

**I8's deterministic backstop was deferred in batch 2 for want of a false-positive
measurement. Four runs is that measurement.** It is now the top item.

### THE REMAINING MISSING ARE A SHORT, NAMED LIST

ACORD 125's 20 missing, in order of size:

| count | what | issue |
|---|---|---|
| **12** | named-insured MAILING ADDRESS + entity indicator, rows B and C | see below |
| 4 | the safety-programme checkboxes | I9 |
| 2 | `Question_KANCode` / `Question_ABCCode` | I9 |
| 1 | `Policy_PolicyNumberIdentifier_A` | I4 (closed as measured) |
| 1 | the underwriter's name | no fact — call 1 frozen |

And only **2 wrong in the entire package**: `LossHistory_TotalAmount_A` (summed the
rows instead of reading the stated total — I7(c), needs a fact) and one Yes/No that
came back N instead of Y (I9 jitter).

### THE ADDRESS HALF OF THE NAMED-INSURED TABLE — NEWLY DIAGNOSABLE

Rows B and C now carry the right phone, SIC, NAICS and FEIN, and a **blank
address**. In run 3 those same boxes carried the WRONG address (premises data), so
this is wrong → blank: precision up, recall flat. But the addresses ARE in the
document.

**Why the two halves behave differently is now clear.** `NamedInsured_MailingAddress`
reaches 3 columns on its own, so I6 rule 1 claims it as its own table; the identity
columns are orphans and form `NamedInsured#ABC`. **One schedule, two tables.** The
identity table aligned perfectly the moment R2 fixed row A; the address table, asked
separately, produced nothing for B and C.

The fix is I6 part 2 done properly — merge a legacy bucket into the orphan bucket
when they share a root AND a row universe, so the model fills ONE nine-column row
per company. **This was deliberately not done in batch 2** to keep the bucketing
provably additive (it would have broken
`test_non_table_pair_still_uses_ordinary_repeating_group`, which pins ACORD 140's
Spoilage pair). Run 4 is the evidence that it is worth revisiting - with that test
kept green.

---

## 4d. RUN 3 - THE SCORE FELL, THE PIPELINE DID NOT (1 Sep 2026, evening)

Same document, same three forms, new session (`c51ec010`). Scored with the same
scorer and key as run 2 (`bae97070`).

| | run 2 | run 3 | |
|---|---|---|---|
| correct | 165 / 220 (75.0%) | 149 / 220 (67.7%) | −16 |
| wrong | 6 | 10 | +4 |
| missing | 44 | 55 | +11 |
| owned blank | 5 | 6 | +1 |
| must-be-blank hit | 15 | **7** | **−8** ✅ |
| precision | 96.5% | 93.7% | −2.8 |
| recall | 75.0% | 67.7% | −7.3 |
| ROW-CELL | 68/77 (88.3%) | **71/77 (92.2%)** | **+3.9** ✅ |
| cross-row | 0 | **0** | held ✅ |

Per form: **125** 108→96 (precision 94.7→90.6), **126** 32→**35** (blank-hits
15→**7**, hazard cells 9/18→**12/18**), **131** 25→**18**.

### ⛔ THE TWO RUNS ARE NOT COMPARABLE, AND THAT IS THE FIRST FINDING

Both sessions were dumped from the database and their facts diffed.
**18 of 103 fact keys differ.** `PROMPT_VERSION` never moved - a fresh upload is
a new document, the extraction cache missed, and call 1 answered differently:

```
dec_page_entries            167 -> 238 rows   (+43%)
property_locations            6 -> 7
coverage_lines                7 -> 8
contractor_high_hazard_ops    6 -> 0 rows
gl_class_codes_by_location    5 -> 3
property_bpp_value      $410,000 -> None
certificate_description_of_operations  <real text> -> "None"
```

**Never compare two runs' scores without diffing the facts first.** Add it to the
re-run checklist; it is now there.

### FINDING 1 - MORE EXTRACTION MADE THE FORMS WORSE

Run 3 read **43% more** off the declarations pages. That should be strictly good.
The extra entries were the **expiring programme's** policy numbers, and nothing
downstream could tell them from the in-force ones:

```
line-identity: dec entries name 2 policy numbers for line ('general liability',)
(['CPP 4Q 887214 26', 'GL 7784120 25']) - box left blank rather than choosing
```

Refusing is the right instinct, and it cost **seven of eight coverage lines**
their policy number, filled ACORD 125's OTHER INSURANCE grid with three expiring
policies, and stamped the **expiring** umbrella number on the ACORD 131 header.
That is most of the 16-point fall. Fixed as **R1**.

### FINDING 2 - ONE WRONG CELL MOVED A WHOLE TABLE

`NamedInsured_Primary_PhoneNumber_A` is ACORD's **BUSINESS PHONE #** box -
its own tooltip reads *"The named insured's primary phone number."* A Pass-1 rule
filled it from `contact_phone`, so row A got the controller's direct line
`(303) 555-0147` instead of the company's `(303) 555-0142`.

The table block then reports row A as ALREADY CAPTURED. The model looks for the
company's real phone among the captured rows, does not find it, and **starts the
schedule one row down**: insured A lands in row B, B lands in row C, C falls off
the form. Fixed as **R2**.

### WHAT WAS ATTRIBUTABLE TO BATCH 2, MEASURED

* **§3b shipped and is correct on the live document** - LOC #/HAZ # printed
  001/001, 002/001, 004/001, matching the key exactly. Hazard row cells 9/18 → 12/18.
* **I8 + I6 on the products grid** - fabricated cells **15 → 7**. The business
  start date, the employee count and the "5 units" inventions are gone.
* **I7 verified against run 3's OWN facts**: the payroll is refused from the
  subcontract box, the correct $2,145,000 is kept, prose is refused from a money
  box. `Contractors_SubcontractorsPaidAmount_A` came back blank because gap fill
  **did not answer it** this run (the box's fate is `gap-fill`), NOT because the
  gate blanked it - checked directly, do not re-litigate.
* **cross-row stayed 0 and ROW-CELL went UP.**

### THE ONE PLACE I6 MADE THINGS WORSE, AND WHY IT IS NOT REVERTED

I6 merged the named-insured ADDRESS columns into the same table as
phone/SIC/NAICS. Before: addresses correct, phone column slid. After: the whole
table slides as one unit. It is **more coherent** - every cell of row C describes
the same company - but one row off. I6 did not cause the slide (R2 did); it
widened its blast radius. R2 removes the cause. If run 4 still shows the slide,
turn the new grouping off with `TABLE_ROOT_BUCKETS=0` - one env var, no revert.

---

## 4e. R1 - THE EXPIRING PROGRAMME IS NOT THE POLICY BEING APPLIED FOR ✅ SHIPPED

**One door, in `extraction_service`, used by both the merge side and the
stamping side** (two implementations of "which policy covers this line" is how
the pairing gets lost in the first place):

| | |
|---|---|
| `prior_term_policy_numbers(facts)` | the numbers the session evidences as last year's |
| `_prior_programme_sections(entries, prior)` | which declarations SECTIONS document the expiring programme |
| `current_numbers_by_line(entries, facts)` | `_policy_numbers_by_line` with that evidence set aside |

**Where "prior" comes from: `prior_coverage_by_line`.** That is the fact whose
entire MEANING is "the expiring programme", so the structure says it and no
vocabulary has to. Our fixture prints `EXPIRING PROGRAMME SUMMARY`; a real
carrier prints `PRIOR POLICY`, `RENEWAL OF`, or nothing. **Matching heading
wording would be a fixture allow-list** and is pinned against by
`test_r1_the_section_rule_reads_no_heading_vocabulary`.

**Why the SECTION and not just the number.** Measured on the live run: ONE entry
inside the expiring block carried the **current** package number under a garbled
header label (`"LINE EXPIRING INSURER POLICY N"`). That made the package number a
third candidate for the UMBRELLA line, so the box still refused even after last
year's umbrella number was removed. The number is perfectly real elsewhere - it
is its POSITION inside the expiring block that makes that one attribution
worthless. A section qualifies as the expiring block when **two or more distinct
prior-term numbers** are printed under it: one is a renewal note in passing
("Renewal of policy GL 7784120 25" sits under COMMON POLICY DECLARATIONS and must
not condemn it), two is a summary table.

**The same-number renewal is protected.** A renewal often keeps its number, and
then the prior grid documents the policy still IN FORCE -
`_current_number_from_prior_grid` relies on exactly that. A number that IS the
session's own `policy_number` is never reported as prior.

**TIE-BREAKER ONLY. This is the safety property.** A line whose every candidate
comes from the expiring block keeps them ALL, so the filter can never empty a set
and can therefore never turn a box that resolves today into a blank.

**Measured, all 17 schemas, both fact sets, with ONLY the filter toggled** (the
facts are byte-identical on both sides - an earlier A/B that removed
`prior_coverage_by_line` was contaminated, because that fact also feeds the
PRIOR CARRIER grid):

```
run 2:  +0 filled, -0 LOST, 0 changed      (no expiring block -> no-op, as designed)
run 3:  +0 filled, -0 LOST, 8 changed      ALL of them last year's -> this year's
        126 / 127 / 137_CA / 137_CO / 140 / 186 / 28  ->  CPP 4Q 887214 26
        131                                           ->  XSU 55 210934 26
```

**Revert:** make `prior_term_policy_numbers` return an empty set.
**Tests:** 8 in `tests/test_form_fill_1sep.py`.

---

## 4f. R2 - THE CONTACT'S PHONE IS NOT THE NAMED INSURED'S PHONE ✅ SHIPPED

ACORD settles it with its own tooltips, on the same form:

| field | tooltip |
|---|---|
| `NamedInsured_Primary_PhoneNumber_A` | *"The named insured's primary phone number."* |
| `NamedInsured_Contact_PrimaryPhoneNumber_A` | *"The primary phone number of the contact."* |

`_ACORD_FIELD_RULES` wrote `contact_phone` into **both**. The contact box is
correct and keeps its value; the business-phone rule is removed and the box now
reaches gap fill **with its two siblings**, so all three rows are found together.

**No fact replaces it** - extraction records no scalar business phone (the three
real numbers exist only inside `dec_page_entries`). Blank beats the wrong number.

**Two dead rules went with it**, both the identical category error and both
verified to match NO field on any of the 17 schemas: `NamedInsured_PhoneNumber`
← `contact_phone` and `NamedInsured_EmailAddress` ← `contact_email`. The second
was found by the anti-rot test on its first run, not by looking.

**Verified across all 17 schemas:** `contact_phone` now lands in exactly one
box - `ACORD_125:NamedInsured_Contact_PrimaryPhoneNumber_A`. All four
`NamedInsured_Primary_PhoneNumber` fields (125 rows A/B/C, 130 row A) route to
gap fill.

**Anti-rot:** `test_r2_no_rule_writes_a_contact_fact_into_a_named_insured_identity_box`
fails the build if any `contact_*` fact is ever mapped into a `NamedInsured_*`
box that is not a `*_Contact_*` box.
**Tests:** 4 in `tests/test_form_fill_1sep.py`.

---

## 5. WORK ORDER

### Done

| issue | status |
|---|---|
| **I2** — duplicate schedule rows | ✅ SHIPPED |
| **I5** — comma-free addresses | ✅ SHIPPED (+ the B1 mitigation) |
| measuring stick | ✅ FIXED before any pipeline change |

### Also done, 1 Sep 2026 (batch 2 — all of it LLM call 2)

| issue | status |
|---|---|
| **I6** — table framing, 3 parts | ✅ SHIPPED (+212 columns framed, 0 lost) |
| **I7** — meaning gate: scalar-fact witnesses + prose in a money box | ✅ SHIPPED (a + b of 3) |
| **I8** — root cause (I6) + "an empty table is a valid answer" | ✅ SHIPPED (no blanking rule — deferred to measurement) |
| **I10** — a leading ISO form number is a citation, not evidence | ✅ SHIPPED |
| **§3b** — LOC # and HAZ # | ✅ SHIPPED (6 of 18 boxes) |
| **I3** | ✅ CLOSED — half 2 was already in HEAD (Stage A) |
| **B3 / B4 / I4** | ⛔ CLOSED AS MEASURED — see the block under I4 |

### Also done, 1 Sep 2026 evening (batch 3 — both found BY run 3)

| issue | status |
|---|---|
| **R1** — the expiring programme is not the policy applied for | ✅ SHIPPED (8 boxes corrected, 0 lost) |
| **R2** — the contact's phone is not the insured's phone | ✅ SHIPPED (+2 dead rules removed) |
| run 3 scored, attributed, and both new defects traced to root cause | ✅ §4d |

### Left

| # | item | what it actually is |
|---|---|---|
| 1 | **RE-RUN (run 5)** | Batch 4 unmeasured. Diff the facts first (rule 8). |
| 2 | **The rating MOD box** (2 boxes) | **APPROVED**, not built. Waiting on the no-hardcoding stress-test. |
| 3 | ~~§3b 40 bound fields~~ | ✅ SHIPPED in batch 4 (S1). |
| 3b | **§3b — the grid parser** | ⛔ DESIGNED AND REJECTED 3-of-4. Needs provenance solved first; do not rebuild blind. |
| 4 | ~~I9 env-var experiment~~ | SUPERSEDED by Y1 - the counting was wrong, not the cap. |
| 5 | ~~I7 (c) loss total~~ | ✅ SHIPPED in batch 4 (L1) - derived, no new fact needed. The underwriter's name stays blocked (no fact, call 1 frozen). |
| 6 | ~~I8's blanking rule~~ | ⛔ MEASURED DEAD: 0 TP / 54 FP. Pinned unbuilt. |
| 7 | **§4 policy change** | Ask everything, gate on label. Must ship whole. **Read the I1 ⛔ block first — "ask about everything" must never include a signature box.** |

### Known, still open, NOT ours (seen on run 3)

* `coverage_lines` in run 3 attributed **Employers Liability to the CPP number**
  while `underlying_policies` says `WC 9930221 26`, so the ACORD 131 underlying
  grid leaves that box blank on a conflict. An extraction attribution problem;
  R1 does not reach it.
* ACORD 125's OTHER INSURANCE grid (*"any other insurance with this company"*)
  is being fed prior-coverage rows. Pre-existing, unmeasured, and untouched by
  R1 - do not assume it is fixed.

### ✅ OWNER APPROVED 1 Sep 2026 — the rating MOD box (NOT YET BUILT)

Verbatim: *"works and i dont want this to be hardcoded and it should work
correctly for real client docs."*

**Approved, not shipped.** The condition attached to the approval is the whole
job: it must not be tuned to the one label our fixture prints. Before it ships it
needs (a) what label wordings real carriers actually use for an experience or
rating modification, (b) at least five realistic dec-entry sets constructed to
FOOL the four conditions, and (c) a decision on whether the VALUE's own shape
should be checked - a mod factor is a small decimal near 1.0, and the junk this
ruling was written after (`33.211`, `SEE ITEM FOU`, `$500`) is not. That
stress-test is in flight. `test_i1_the_rating_mod_box_is_still_an_owned_blank`
keeps the box blank until it lands.

### THE ORIGINAL RULING, for the record — the rating MOD box

`UnderlyingPolicy_*_ModificationFactor_A` is **not** blocked by name. It is
blanked by `_resolve_underlying_policy_row` under an explicit ruling:

> *"A rating MOD is never an extractable fact - every live run stamped junk
> there (33.211 the GL rate, 'SEE ITEM FOU', $500 an endorsement premium).
> Owned blank whenever per-line evidence exists; producers rate, we don't."*

The dec index on the T1 document prints `EMPLOYERS LIABILITY MODIFICATION FACTOR
= 0.94` and `AUTO MODIFICATION FACTOR = 1.00`, and the new rule's line + label +
unique-match test transcribes both correctly — verified. **Not taken**: that is a
two-box change against a documented ruling backed by repeated live evidence, and
reversing it is the owner's call, not a drive-by. Pinned as-is by
`test_i1_the_rating_mod_box_is_still_an_owned_blank` so it cannot start filling
by accident.

**Count: 8 shipped (I1, I2, I3, I5, I6, I7, I8, I10 + §3b part), 1 closed as
measured (I4/B3/B4), 1 open as an experiment (I9), 2 open as owner decisions.**
Nothing that was working was changed. Every regression the shipped work caused
(B1, B9, B10, B11) was found and fixed before the next measurement.

**RE-RUN NOW.** Everything that can move a number without a live measurement has
shipped. The check-list is in the STATE OF PLAY block at the top of this file.

**Prompt changes:** only one is still on the table, and it shrank. Most of what I
first said needed extraction changes turns out to be **already extracted** (I3).
What genuinely is not captured: the GL hazard rate/premium columns (they sat in a
second stacked table block), the underwriter's name, and the stated loss total.
Hold that until after the deterministic fixes — it may not be worth making.
Any prompt change requires an `improving-ll.md` entry in the same commit.

---

## 6. RULES FOR THIS WORK

1. **Re-baseline before and after every change** with `score_form_fill.py`. Four
   buckets. ROW-CELL is the number to steer by.
2. **Write the adversarial case first** for I1 and I4 — both loosen guards added
   after real defects. The guard must still refuse what it was built to refuse.
3. **Never edit a source file while a test run is in flight** — several anti-rot
   tests read their target via `inspect.getsource`, and a mid-run edit produces
   failures indistinguishable from a real regression.
4. **An offline probe proves the function, never the seam around it.** Verify
   through `compute_form_gaps` / `map_facts_to_form`, not by calling a resolver
   directly and reading its return value.
5. Suite baseline: `py -m pytest -q -p no:randomly` from `backend/` →
   **5166 passed, 1 failed, 1 xfailed** (1 Sep 2026, after batch 3).
   The one failure is the documented `httpx`/`openai` `ImportError`. Always use
   `-p no:randomly`. CLAUDE.md's "4824" line is stale.
6. **Never call `importlib.reload` inside a test here.** `pdf_service` defines
   identity sentinels; reloading it makes 16 unrelated tests fail in the full suite
   and pass file-at-a-time, which reads exactly like the documented pollution and
   costs an hour to trace. See B11.
7. **A test's measuring instrument is code too.** Two of the 18 failures in this
   batch were the TEST scraping a prompt with a regex that never matched a table
   block. Before believing a metric moved, check what it counts. See B12.
8. **DIFF THE FACTS BEFORE READING A SCORE.** Two runs of the same document are
   not comparable unless call 1 returned the same answer. Run 3 differed from run
   2 on **18 of 103 fact keys** and the whole "165 → 149" headline was that. Dump
   both sessions (`scripts/dump_session_facts.py <id> --json`; the session id is
   in `processing_sessions` ordered by `created_at`) and diff before concluding
   anything. See §4d.
9. **An A/B must toggle ONE thing.** The first R1 blast-radius run disabled the
   filter by deleting `prior_coverage_by_line` from the facts - which also emptied
   the PRIOR CARRIER grid that fact feeds, and reported eight "gains" that were
   nothing to do with the change. Patch the FUNCTION, keep the data identical.

---

## 7. CHANGELOG

| date | change | before → after | files |
|---|---|---|---|
| 2026-09-01 | Test kit + scorer built; first baseline | — → 134/220 correct, ROW-CELL 64.9% | `make_t1_test_pdfs.py`, `_t1_data.py`, `score_form_fill.py`, `t1_test_data/` |
| 2026-09-01 | **B2** unchecked checkbox read as "No" — scorer bug | 18 wrong / 13 blank-hits → 18 / 13 (−1 wrong, −2 hits on re-score) | `score_form_fill.py` |
| 2026-09-01 | Measuring stick: redundant units + leading zeros | **134 → 141 correct, 18 → 11 wrong, ROW-CELL 64.9% → 70.1%** (no pipeline code changed) | `score_form_fill.py` |
| 2026-09-01 | All-schema deterministic snapshot tool added | — | `snapshot_deterministic_fill.py` |
| 2026-09-01 | **I2** schedule-row dedup | loss 8→5, underlying 8→4, GL hazard 6→3; 125 +6 filled, 130 +3, 131 row F correctly blank | `extraction_service.py` |
| 2026-09-01 | **I5** comma-free address split + **B1** group-key mitigation | every form gains `MailingAddress_LineTwo`; premises row D regains its city; 0 values lost | `utils/helpers.py`, `extraction_service.py` |
| 2026-09-01 | 5 existing tests updated to the new line1/line2 split | all structural assertions untouched | `test_run_20260814c_fixes.py`, `test_run_d_fixes_20260810.py`, `test_location_consolidation.py`, `test_form_fill_ownership_20260810.py` |
| 2026-09-01 | 29 new tests | — | `tests/test_form_fill_1sep.py` |
| 2026-09-01 | **B7** scorer read a LOC # of "1" as a checkbox; **B8** key demanded a date column ACORD 131 does not have | baseline restated 141→142 correct, ROW-CELL 70.1%→74.0% (no pipeline code) | `score_form_fill.py`, `make_t1_test_pdfs.py` |
| 2026-09-01 | **LIVE RE-RUN after I2+I5** | **142→165 correct, 10→6 wrong, 59→44 missing, precision 93.4→96.5%, ROW-CELL 74.0→88.3%, cross-row 11→0** | — |
| 2026-09-01 | **B9** location schedule had no `address_line2` column - destroyed every suite on first save, and flagged two real premises as duplicates | suites preserved, `duplicates: []` | `schedule_capture.py` |
| 2026-09-01 | **B10** a premises in the producer's building was deleted as the agency's own office | 2 premises in, 2 out (was 1) | `extraction_service.py` |
| 2026-09-01 | 4 more tests for B9/B10 | suite **5095 passed / 1 known failure** | `test_form_fill_1sep.py` |
| 2026-09-01 | **I10** found: key strengthened with the vendors-coverage question | must-be-blank 14 → 15 on run 2, 13 on baseline (unchanged) | `_t1_data.py` |
| 2026-09-01 | **All 15 mechanically-checkable traps verified HELD** on the new run | forbidden 0, wrong-shape 0, overflow-leak 0 | — |
| 2026-09-01 | **I1 + I3 half 1** — dec-index rating carve-out | 4 boxes on ACORD 131 fill deterministically; 0 effect on the other 16 forms; suite **5105 passed / 1 known failure** | `pdf_service.py`, `test_form_fill_1sep.py` |
| 2026-09-01 | **I6** row-oriented table framing (3 parts) | **+212 columns row-framed across 13 forms, 0 lost**; largest atomic unit 221 fields (under existing 154/143/112) | `pdf_service.py`, `test_form_fill_1sep.py` |
| 2026-09-01 | **I7** every categorised scalar fact witnesses; a negated sentence is not an amount | live wrong $1,804,000 blanked, real $2,145,000 kept; Included/Statutory/None/Not applicable all survive | `pdf_service.py` |
| 2026-09-01 | **I8** "an empty table is the correct answer" in the row block | prompt only; root cause shipped as I6 | `pdf_service.py` |
| 2026-09-01 | **I10** a quote opening with an ISO form number is a citation | 4/4 citations rejected, 0/8 real quotes lost | `pdf_service.py` |
| 2026-09-01 | **§3b** LOC # + HAZ # on the ACORD 126 hazard grid | **+6 fields, 0 lost, 16 other forms byte-identical** (all-schema snapshot) | `pdf_service.py` |
| 2026-09-01 | **B3** corrected the misleading "corrupt package" warning + docstring | behaviour byte-identical - the fix would have broken it, see I4 | `pdf_service.py` |
| 2026-09-01 | **B11** my kill-switch test reloaded `pdf_service` and broke 16 unrelated tests | 18 failed → 1 | `test_form_fill_1sep.py` |
| 2026-09-01 | **B12** the retrieval recorder counted table COLUMN LABELS as field names | 2 D4 assertions restored; the code was never wrong | `test_call2_retrieval.py` |
| 2026-09-01 | 39 new tests; **full suite 5144 passed / 1 known failure** | zero regressions | `test_form_fill_1sep.py` |
| 2026-09-01 | **LIVE RUN 3** scored, then proven NOT COMPARABLE to run 2 | 165→149 correct, but **18 of 103 fact keys differ**; dec entries 167→238 | — |
| 2026-09-01 | run 3 confirmed batch 2: hazard LOC#/HAZ# correct, products grid **15→7** fabricated, ROW-CELL 88.3→**92.2%**, cross-row **0** | — | — |
| 2026-09-01 | **R1** the expiring programme is not the policy applied for | **8 policy-number boxes corrected across 8 forms, 0 lost**; run 2 a no-op | `extraction_service.py`, `pdf_service.py` |
| 2026-09-01 | **R2** the contact's phone is not the named insured's phone (+2 dead rules) | `contact_phone` now lands in exactly ONE box across all 17 schemas | `pdf_service.py` |
| 2026-09-01 | 12 new tests; **full suite 5166 passed / 1 known failure** | zero regressions | `test_form_fill_1sep.py` |
| 2026-09-01 | **§3b grid-parser designed, adversarially reviewed, REJECTED 3-of-4** | it would stamp last year's rates as this year's on any renewal — the RC1b class, a third time | — |
| 2026-09-01 | **§3b census + 40 already-bound unreachable fields found and verified** | 225 refused per-row fields, 176 Group B; 4 dead `_SCHEDULE_REGISTRY` bindings incl. `wc_class_codes.rate` | — (not shipped) |
| 2026-09-02 | **LIVE RUN 4 — the first CLEAN A/B** (facts differ on 2 of 100 keys) | **149→158 correct, wrong 10→2, precision 93.7→98.8%**, cross-row 0 | — |
| 2026-09-02 | R1 confirmed live: 5 policy-number boxes across 3 forms now name THIS year's policy | — | — |
| 2026-09-02 | R2 confirmed live: **9 named-insured identity cells snapped into alignment** across rows A/B/C | — | — |
| 2026-09-02 | **I8 is now the ONLY source of wrong values left** — 13 of 13 blank-hits, measured 12→14→7→13 over four runs | — | — |
| 2026-09-02 | **Y1** reuse cap counts answer units - option boxes of one question are one answer | 0 compliance questions leak (17 schemas); supersedes the I9 experiment | `pdf_service.py` |
| 2026-09-02 | **L1** TOTAL LOSSES derived from the whole schedule, inside the existing owner | `$568,495` to the dollar; the ownership test caught my two-door first draft | `pdf_service.py`, `test_run_20260813h.py` |
| 2026-09-02 | **S1** bound schedule columns stamp before the name gate | +40 fields incl. WC rates; no rate reaches the model (pinned) | `pdf_service.py` |
| 2026-09-02 | **J1** TABLE_JOIN - one schedule, one table | the 12-blank named-insured address split; 2 geometry pins updated, B12's second recorder copy fixed | `pdf_service.py`, `test_batch_packing_and_budget.py` |
| 2026-09-02 | **I8 backstop MEASURED DEAD: 0 TP / 54 FP** over 2 runs vs the key | pinned unbuilt by `test_i8_the_borrowed_value_rule_stays_unbuilt` | `test_form_fill_1sep.py` |
| 2026-09-02 | 13 new tests; **full suite 5181 passed / 1 known failure** | zero regressions | — |
| 2026-09-02 | **LIVE RUN 5** (facts differ on 19 keys - not comparable) | 160 correct / 8 wrong / 95.2% precision / cross-row 0; L1+I1+I7 confirmed EXACT on the printed forms | — |
| 2026-09-02 | **R3a-c** the expiring programme leaked back through 3 new doors (values, term-rescue twins, carrier index) | 131 header + 126 carrier now correct on ALL FOUR stored fact sets | `extraction_service.py`, `pdf_service.py` |
| 2026-09-02 | **R3d** merged-table rows ANCHORED by known cells from the root family | run 4's empty rows and run 5's slide are the two halves this closes | `pdf_service.py` |
| 2026-09-02 | 6 new tests; **full suite 5187 passed / 1 known failure** | zero regressions | `test_form_fill_1sep.py` |
| 2026-09-02 | **LIVE RUN 6 - best run**: **176 correct / 1 wrong / precision 99.4% / recall 80%**; anchoring + Y1 + R3 all confirmed live | baseline -> now: 142->176 correct, 10->1 wrong, ROW-CELL 74->92.2%, cross-row 11->0 | — |
| 2026-09-02 | **R3e** glued expiring-row values hid the prior numbers from the section rule | substring match; ALL FIVE extraction variants now resolve both headers | `extraction_service.py` |
| 2026-09-02 | 1 new test; **full suite 5188 passed / 1 known failure** | zero regressions | `test_form_fill_1sep.py` |
| 2026-09-02 | **M1: the rating MOD box SHIPPED** (owner-approved) inside its one owner + `_dec_index_rating_value` hardened per the stress test | 11/11 adversarial refused, 10-box spray -> 0, four live premiums intact, 0.94/1.00 stamp | `pdf_service.py` |
| 2026-09-02 | **P1**: table columns render field cautions; rule (g) "never the business itself"; business-phone caution | run 6's one wrong cell | `pdf_service.py` |
| 2026-09-02 | the accident-pin on the MOD box flipped to pin the APPROVED behaviour | — | `test_form_fill_1sep.py` |
| 2026-09-02 | 16 new tests; **full suite 5204 passed / 1 known failure** | zero regressions | `test_form_fill_1sep.py` |
| 2026-09-02 | **LIVE RUN 7** (facts differ on 17 keys): **177 correct / 2 wrong / precision 98.9% / recall 80.5%** - best correct count | **the MOD boxes print 1.00 and 0.94 live** (M1); 126 header carrier + PREM/OPS $46,900 live; products grid 13->7->6; cross-row 0 (seven straight runs) | — |
| 2026-09-02 | **Pass-1 CATEGORY ERROR removed**: `ProductAndCompletedOperations_AnnualGrossSalesAmount -> total_revenue` stamped the COMPANY's revenue into a PER-PRODUCT sales cell (ACORD tooltip: "realized by THIS PRODUCT OR SERVICE"). Now `None` - the box reaches call 2 like its six siblings, it is NOT an owned blank | fired on EVERY ACORD 126 carrying a revenue fact, at confidence `filled` - past the evidence gate and every post-fill guard, no model involved. Verified at the seam: `$9,410,000` -> `None`. Suite 5204/1 known | `pdf_service.py:1569` |
| 2026-09-02 | **RUN 10: 178 correct / ZERO WRONG / PRECISION 100.0% / recall 80.9% / ROW-CELL 92.2% / cross-row 0 (ten straight).** Y/N: **wrong 0, fabricated 0** | **FIRST RUN WITH NO WRONG VALUE ANYWHERE.** All four audit fixes visible on the page: TOTAL LOSSES **$348,495**; the REMARKS box carries "ADDITIONAL LOSSES NOT SHOWN... (2 of 5 total)" naming the **$212,880** hail loss; `www.` / `dostrander@` lowercase and **`N.A.`** correct; ACORD 131 Q6 tail is a clean **N** with the orphan explanation GONE. Also recovered: Q1b subsidiaries **Y** (the audit's biggest single finding), Q3 flammables Y+explanation, EL policy number `WC 9930221 26` | — |
| 2026-09-02 | Run 10 residuals: the products grid still fabricates 6 cells (SHUFFLED, not fixed - names moved to rows B/C, IntendedUse to all three); safety-programme sub-boxes went blank on jitter; ACORD 131's coverage-information box DUPLICATED its own sentence (new, cosmetic) | products grid remains THE open defect | — |
| 2026-09-02 | **GENERICITY MEASURED, not asserted.** Today's diff: **zero T1 literals in logic** (every grep hit is inside a docstring explaining the defect) and **zero form-id branching**. Reach per fix, counted from the real schemas: Y/N type gate **1,899 boxes on 16 of 17 forms**; explanation pairing **186 pairs on 10 of 17**; loss-overflow **3 of 17 forms have a loss grid and capacity is read PER FORM (125=3, 130=5, 131=6)**, never assumed; machine-token + dotted-initialism guards are **field-agnostic - every field on every form** | the mechanisms are structural (ACORD tooltips, field-name segments, schema-counted capacity), not fixture-tuned | — |
| 2026-09-02 | **AUDIT FIX 1 - the loss total was INCURRED in a box ACORD scopes to PAID.** `_loss_history_total_from_schedule` summed paid + reserved and reproduced the document's printed "TOTAL LOSSES $568,495" exactly - but that headline is TOTAL INCURRED and the same document prints TOTAL PAID $348,495 one line up. Now paid-only | **$568,495 -> $348,495**, a 63% overstatement removed from the number an underwriter reads first. The ANSWER KEY was wrong too and is corrected. **Standing lesson: reproducing a number the document prints is not evidence it belongs in the box - the tooltip is the contract** | `pdf_service.py`, `T1_answer_key.json` |
| 2026-09-02 | **AUDIT FIX 2 - losses the grid cannot print are now DISCLOSED.** `_resolve_loss_overflow_remark`: capacity is counted from the FORM's own schema (never assumed to be 3), and when the schedule exceeds it the dropped losses are written into the form's REMARKS box - an owned blank until now | ACORD 125 prints 3 rows, the document reported 5. The two dropped included **$212,880 hail damage, the largest loss in the package**, with nothing on the form saying so. Silent truncation of a loss run is the worst failure mode here: not a wrong value a broker can spot, a missing one they cannot | `pdf_service.py` |
| 2026-09-02 | **AUDIT FIX 3 - a URL or an e-mail is never re-cased.** Website/e-mail boxes are classed as "name", so the name title-caser printed `Www.verdantslopebuilders.com` and `Dostrander@...` on a filed ACORD 125. Fixed at `canonicalize_for_field` (before dispatch) rather than by re-categorising fields - it is true of EVERY category. Plus `_DOTTED_INITIALISM_RE`: `N.A.` (a US national bank's designation) was printing as `N.a.` | an e-mail local part is case-SENSITIVE per RFC 5321 - re-casing one can make it undeliverable | `display_canonicalizer.py` |
| 2026-09-02 | **AUDIT FIX 4 - the pairing blind spot, fixed INSIDE the existing door.** ACORD 131's tail-coverage question sits ONE position from its explanation, with an EffectiveDate box named under a DIFFERENT root between them, so `_dependent_block_for`'s same-stem-run rule could never form a block. Unpaired = rules 2/4/5 OFF, and that box shipped an ORPHAN explanation on the wrong subject | **131 pairs 25 -> 26; 125 and 126 unchanged.** Structural second condition (same section root) proved necessary: without it the widening paired an ACORD 126 inland-marine field to a GL explanation | `pdf_service.py` |
| 2026-09-02 | **TWO NEAR-MISSES CAUGHT BY MEASURING, both mine.** (a) A first version scanned from `i+2` to skip the distance-1 case - which never EXAMINED `i+1`, so ACORD 140's `WindClass_OtherIndicator` was jumped over and `SemiResistiveIndicator` paired to the OTHER box's description: **68 false pairs across 8 forms**, and the naked-Yes guard would then have blanked correct ticks. (b) The helper ran BEFORE the primary rule and OVERRODE correct distance-1 pairs - caught by `test_guard4_does_not_blank_confirmed_yes_explanation_shared_with_other_fields`. Then found the repo ALREADY had a third fallback for this exact shape, so the whole helper was deleted and the fix moved inside it - one door | **do not add a door; find the one that exists.** Both bugs were invisible to reasoning and obvious to a measurement | — |
| 2026-09-02 | AUDIT FINDING **REFUTED** by direct check: "ACORD 131 ships a dateless loss run" is NOT a defect. 131's only date column is `LossHistory_ClaimDate` - *"the date the claim was FILED"* - and the document prints OCCURRENCE dates, not filing dates. ACORD 125 has both columns; 131 has only this one. **Blank is correct**; the audit called right-or-blank a bug | do not "fix" it | — |
| 2026-09-02 | 13 new tests (X1). **Suite 5194 passed / 1 known failure** | zero regressions | `test_form_fill_1sep.py` |
| 2026-09-02 | **RUN 9 DEEP Y/N + EXPLANATION AUDIT (10 agents, all 368 Y/N boxes on 3 forms vs the source doc - the scorer's key only spans 220 fields).** Result: **326/368 correct (91.4%)** - 283 correctly BLANK, 43 correctly filled, **9 wrong values** (ACORD 126: ZERO), 25 wrongly blank | it FAILS SAFE: 25 of 34 errors are a missing answer, not a wrong one. **Every planted trap was refused** - auto territory did not bleed into the GL grid, "INLAND MARINE" did not answer the marine/watercraft questions, the $10,000 SIR did not answer "self-insured in any state" | — |
| 2026-09-02 | **CLIENT RULE 3 ("an N carries no explanation"): ZERO violations across all three forms.** Every N ships with an empty pair | the owner's rule is holding exactly | — |
| 2026-09-02 | **ROOT CAUSE OF EVERY ORPHAN AND NAKED-YES: `_question_explanation_pairs` only pairs a STRICTLY ADJACENT, same-name-stem field.** It returns 30/37/25 pairs on 125/126/131 and MISSES: ACORD 125's four highest-value questions whose detail block uses a different name root (AAI/AAJ -> `Subsidiary_*`, AAH -> the `OtherPolicy_*` grid, KAA -> the `FormalSafetyProgram_*` boxes); ACORD 131's ACF (missed by ONE position - a date field sits between); and ACORD 131's whole Exposure column | **rules 2, 4 and 5 are UNENFORCED on all of those.** 100% of this run's orphans, all 4 naked-Yes ticks, and the false "other insurance = Y" (backed by two RIVAL carriers' policy numbers) live in that one hole. Cheapest high-value fix on the board | `pdf_service.py` |
| 2026-09-02 | Audit found an **ANSWER-KEY ERROR**: `LossHistory_TotalAmount_A` - ACORD's tooltip says "the amount PAID on all losses"; the document prints TOTAL PAID $348,495 and TOTAL INCURRED $568,495. Key expects the INCURRED figure. Form is 63% overstated in the number an underwriter reads first | fix the KEY and the fill; the tooltip is the contract | `T1_answer_key.json` |
| 2026-09-02 | Audit found **ACORD 131 ships a DATELESS loss run on every package ever produced** - `_SCHEDULE_REGISTRY` binds `LossHistory_OccurrenceDate -> loss_history.date`, but **ACORD 131 has no `OccurrenceDate` field**; `ClaimDate` is its only date column and extraction leaves `claim_date` null. The value is in the document AND in the facts and is unreachable on that form by construction | structural, not model | `pdf_service.py` |
| 2026-09-02 | Audit found **ACORD 125 silently drops 2 of 5 losses including the LARGEST** ($212,880 hail, and $6,215 auto) - the grid has 3 slots, the document reports 5. An underwriter sees 3 GL claims totalling $129,400 beside a stamped total of $568,495 with no indication anything was omitted. `RemarkText_A` is blank - exactly where this project's own ACORD 101 overflow convention belongs | silent truncation of a loss run | — |
| 2026-09-02 | Audit found **3 FABRICATED Employers Liability limits on ACORD 131** ($1,000,000 x3). The document states an EL carrier, number, premium and mod and **never states an EL limit**; $1,000,000 is the GL occurrence / auto CSL / pollution CSL, so the borrow is invisible. The SAME run REFUSED that same figure in `ExcessUmbrella_EmployeeBenefits_*` - a guarded must-be-blank trap. Same number, same page, opposite outcomes: **a gap-fill leak on an UNGUARDED field family** | the guard works where applied; these sit where it is not | — |
| 2026-09-02 | **RUN 9: 176 correct / 1 wrong / precision 99.4% (BEST EVER) / recall 80.0% / ROW-CELL 92.2% / cross-row 0 (nine straight)** | **the contact-phone guard fired live** - row A's business phone is now BLANK instead of carrying the controller's line, and it is the ONLY wrong value that left. Correct count dipped 180 -> 176 on model jitter, not on any change | — |
| 2026-09-02 | Run 9 vs 8, field level: FIXED 5 (all products-grid cells - ProductName_C, UnitCount_A, IntendedUse_A/B/C). NEW 6 - SafetyManualIndicator_A, MailingAddress_LineTwo_C, 2 Contractors Question codes, and **AnnualGrossSalesAmount_B/C now hold `$8,275,000` and `$6,940,000` - THREE YEARS OF COMPANY REVENUE HISTORY stamped as three PRODUCTS' sales.** New fabrication shape, same empty grid | the products table keeps finding a different applicant-level list to pour into itself. Every shape so far is the business itself | — |
| 2026-09-02 | Y/N family run 7->8->9: wrong 1/1/1, fabricated 1/0/0, missing 8/8/11. The SAME handful of boxes flip run to run | the deterministic Y/N work is done; this tail is model variance | — |
| 2026-09-02 | **CONTACT-PHONE GUARD SHIPPED** - `_blank_contact_value_in_an_entity_box`, last in `_enforce_post_fill_guards`. A box whose ACORD name carries a Contact/Person segment describes a HUMAN; the same-typed box without it describes the ENTITY. One number cannot be both, so on collision the ENTITY box loses (it is the one with no evidence). Digits-only compare, so `(303) 555-0147` == `303-555-0147` | kills run 8's remaining wrong value. Structural, no field list, no fixture strings. Verified: clears row A, KEEPS the contact box and row B's own number | `pdf_service.py` |
| 2026-09-02 | **ZERO-EVIDENCE TABLE RULE: BUILT, MEASURED, REVERTED.** The evidence test was right (no cell filled ANYWHERE in the table = no rows) and measured 0 correct cells lost. The BUCKETING was wrong twice: (1) a 2-segment prefix makes each `ProductAndCompletedOperations_<Column>` its own 1-column bucket, so **it never fired on the grid it was written for**; (2) its 927 withheld questions were all BYSTANDER tables - it broke `test_fleet_rows_sharing_a_city_are_not_gutted` and `test_identical_looking_rows_are_kept_not_guessed_away`, the standing C18 guards written after post-fill dedup deleted 40+ correct fleet cells | **A table is not defined by a name prefix.** `_table_prefix`/`_TABLE_ROOT_BUCKETS`/`_row_universe`/`_claim_bucket` already own that question - but they are a CLOSURE inside `_build_user_prompt`, so reusing them needs an extraction the refutation warned would dissolve batch 4's J1 merged named-insured table. Analysis kept in the retired helper's docstring | `pdf_service.py` |
| 2026-09-02 | **RUN 8 (first run after the Y/N type gate): 180 correct / 2 wrong / precision 98.9% / recall 81.8% / ROW-CELL 92.2% / cross-row 0 (eight straight)** | best correct count. **6 of the 8 newly-fixed fields are exactly what the gate targeted** - MonthlyMeetings_B, OSHA_B (both were blocked by a garbage stamp), KAHCode_A (was a fabricated N), AAGCode_A, ACACode_A, ExcessUmbrella_Occurrence. Plus phone row C and `Contractors_SubcontractorsPaidAmount_A` $2,145,000 - one of the six "no fact" boxes, found by CALL 2, confirming call 1 never needed unfreezing | — |
| 2026-09-02 | Run 8 cost of the gate, as designed: 3 boxes that used to carry a FAKE value are now honest blanks the model did not answer (`CorporationIndicator_B`, `LLCIndicator_C`, 2 Question codes). Traded fake values for blanks; the model filled 6 of ~9 | Y/N family: wrong 1, **fabricated 1 -> 0**, missing 8 | — |
| 2026-09-02 | Run 8 REGRESSION, and the ONLY one that grew: the ACORD 126 products grid **6 -> 8 fabricated cells**. The Pass-1 revenue rule is gone, so the LLM now writes `$9,410,000` itself, plus "Unmanned Aerial Systems" (equipment the applicant OWNS, not a product it sells) and a 3rd row | removing a deterministic wrong value moves it to the model unless the box is also gated. **Top open item** | — |
| 2026-09-02 | Y/N EXPLANATION AUDIT (owner asked): every "Y" explanation on all 3 forms is SPECIFIC and document-grounded - names entities, counts, terms. No vague filler. Every "N" carries no explanation, per the client rule. The pairing is enforced BOTH ways in code (`explanation_without_yes` blanks an orphan explanation; `NAKED_YES_BLANKED` blanks a Y whose explanation was blanked) - which is why ACORD 125 Q3 went blank/blank together rather than leaving a naked Y | relationship IS preserved | `pdf_service.py` |
| 2026-09-02 | **Y/N ROOT CAUSE FOUND AND CLOSED - the Y/N TYPE GATE.** `_ACORD_FIELD_RULES` matches by SUBSTRING and NOTHING checked what a deterministic rule may PUT in a box, so rules pasted a fact's raw value into a checkbox: `gl_aggregate` **$2,000,000** into 4 "limit applies per" indicators, `gl_form_type` **CG 00 01 04 13** (an ISO form number) into Occurrence/Claims-Made, **Combined Single Limit** into a /Btn, **O/C** into the CLAIM OPEN "Y / N" column | **21 boxes on 8 of 17 forms -> 0.** The damage was DOUBLE and that is why it hid: Pass 1 claiming the box removes it from `unmatched` so **call 2 is never asked**, then `_enforce_post_fill_guards` blanks the garbage - box empty AND model never given the chance. Read as a model failure; it was ours | `pdf_service.py`, `alias_stamper.py` |
| 2026-09-02 | The gate sits on **all four deterministic writers**, found one at a time by tracing the seam: `_deterministic_map` (8 callers incl. `arq_service`), Pass 1.5 `stamp_form_fields`, and `_resolve_schedule_row` (gated at the PRODUCER, not its 2 call sites - one door) | 1,673 Y/N boxes now correctly reach call 2. Gap fill has had `_rejects_declared_type` (C22) since July; Pass 1 had no equivalent - this is it | — |
| 2026-09-02 | `_coerce_yn_by_field_concept`: rescues an answer we ALREADY HAVE when spelled in the source system's vocabulary, licensed by the FIELD'S OWN NAME (a box named `...OpenCode` may read O=Y/C=N; the same token on any other field is dropped). Never guesses a tick | CLAIM OPEN column `O,C,O` -> `Y,N,Y`. Call 1 stays FROZEN - its prompt states the O/C contract, we convert at the stamping side | `pdf_service.py` |
| 2026-09-02 | **13-agent design+refutation round: ALL THREE big designs REFUTED 3/3** - (a) products applicant-echo guard: FP on a single-product manufacturer, and its own condition 1 exempted the real defect above; (b) dec-index entity-block resolver: its 6 "generic" tokens were the test document's labels verbatim, and it lost 3 correct values on the repo's own captured extraction; (c) Y/N option-group relaxation: the grouping key strips the row letter so it merges SCHEDULE rows (951 fields), and left the reported case unchanged | NONE SHIPPED. Cost ~2.4M subagent tokens, saved three regressions | — |
| 2026-09-02 | Refutation also cleared a suspected defect: `NamedInsured_Primary_WebsiteAddress_B/_C` echoing entity A is **already blanked** by the row_dedup post-fill guard - nothing wrong ships | do not "fix" it | — |
| 2026-09-02 | Run 7 residuals: the row-A phone took the contact's number again (caution rendered, model dice), one Y/N flip (AAJ) | both are model behaviour - every deterministic gate is shipped | — |
| | *(next entry goes here)* | | |

## 4c. RESULT — live re-run, 1 Sep 2026, after I2 + I5

Same document, same three forms, new session. **Both runs re-scored with the same
corrected scorer and key, so this is apples to apples.**

| | baseline | after I2 + I5 | |
|---|---|---|---|
| correct | 142 / 220 | **165** | **+23** |
| wrong | 10 | **6** | **−4** |
| missing | 59 | **44** | **−15** |
| owned blank | 9 | 5 | −4 |
| must-be-blank hit | 13 | 15 | **+2** ⚠️ |
| precision | 93.4% | **96.5%** | +3.1 |
| recall | 64.5% | **75.0%** | +10.5 |
| ROW-CELL | 54/73 (74.0%) | **68/77 (88.3%)** | +14.3 |
| **cross-row contamination** | **11** | **0** | **−11** ✅ |

Per form:

| | correct | wrong | must-be-blank | row groups |
|---|---|---|---|---|
| ACORD 125 | 91 → **108** | 10 → **6** | 0 | premises **24/24**, loss **15/15** |
| ACORD 126 | 32 → 32 | 1 → **0** | 12 → **14** | hazards 9/18 |
| ACORD 131 | 18 → **25** | 0 | 1 → **0** | loss **20/20** |

**All three acceptance criteria met:** cross-row 0, precision up, and the one
number that rose is accounted for below.

### The +2 must-be-blank is NOT a regression, and it is provable

14 of the 15 violations are the ACORD 126 **products grid** — issue I8,
explicitly not fixed. It went 12 → 14 because that grid is pure gap fill on
unbound columns and the model is not deterministic. The 15th is I10 below.

The proof that it is not ours: the all-schema snapshot diff shows the shipped
changes moved exactly **nine field families**, and none is within reach of it:

```
LossHistory_ClaimStatus_SubrogationCode   NamedInsured_MailingAddress_LineOne
LossHistory_LineOfBusiness                NamedInsured_MailingAddress_LineTwo
LossHistory_OccurrenceDescription         Producer_MailingAddress_LineOne
LossHistory_PaidAmount                    Producer_MailingAddress_LineTwo
LossHistory_ReservedAmount
```

### What the remaining 44 missing actually are

| count | cause | issue |
|---|---|---|
| 18 | ACORD 126 GL hazard LOC # / HAZ # / rates / premiums | **I1** |
| 5 | ACORD 131 underlying premiums + mod factor | **I1** |
| 3 | ACORD 131 other-policy number / CSL / premium | **I3** |
| 6 | 125 named-insured SIC / NAICS / state / entity for rows B and C | **I6** |
| 1 | package policy number | **I4** |
| 11 | Yes/No answers, member-manager counts, underwriter name | I9 / owned blanks / no fact |

**Two thirds of what is still missing is I1 and I3** — the two fixes the
blast-radius trace stopped me shipping in the wrong shape.

### And the 6 remaining wrong are one defect, three times

```
NamedInsured_Primary_PhoneNumber_A   got the CONTACT's phone
NamedInsured_Primary_PhoneNumber_B   got insured A's phone
NamedInsured_Primary_PhoneNumber_C   got insured B's phone
NamedInsured_SICCode_C               got insured B's SIC
NamedInsured_NAICSCode_C             got insured B's NAICS
LossHistory_TotalAmount_A            summed 3 rows instead of reading $568,495 (I7)
```

A clean one-row slide down the phone and code columns. `NamedInsured_Primary` is
a 2-column bucket and `NamedInsured_SICCode` / `_NAICSCode` are 1-column buckets,
so all three fall to the column-wise scavenger hunt. **This is I6, isolated.**
Meanwhile `NamedInsured_MailingAddress` — a 5-column TABLE — came back 100%
correct, including the row that slid on the baseline. The contrast is the
argument for I6 in one screenshot.

---

### FORECAST for the re-run (deterministic only, no LLM involved) — as written before the run

Computed by replaying the shipped code over the live session's facts with the
address parts re-derived, exactly as a fresh upload would. **The live run should
beat every number below, because gap fill adds to it.**

| | baseline (live, incl. gap fill) | forecast (deterministic only) |
|---|---|---|
| correct | 141 / 220 | **133 / 220 without any LLM** |
| ROW-CELL | 54/77 (70%) | **68/82 (83%)** |
| **cross-row contamination** | **11** | **0** |
| 125 premises | 23/24 | **24/24** |
| 125 loss history | 12/15 | **15/15** |
| 131 loss history | 10/20, 11 cross-row | **20/25, 0 cross-row** |

`126 gl_hazards` stays at 9/18 — the other nine cells are the rate/premium
columns, which are I1's job and are still switched off.

**What to check on the re-run, in this order:** cross-row must be **0**;
must-be-blank hits must not rise above 13; precision must not fall below 92.8%.
A rise in `correct` with a fall in precision is a regression however good the
headline looks.

### Tools added this session

| file | what it does |
|---|---|
| `backend/scripts/snapshot_deterministic_fill.py` | Records every field's fate (filled / owned-blank / to-gap-fill) across **all 17 schemas** from a real session's facts, with no LLM. `--diff before after` shows exactly what moved and flags anything that **LOST** a value. This is the safety net for "don't break what works" — every fix in this file was checked through it. |
| `scratchpad/audit_call2.py` | Real `combined_gap_fill` with the OpenAI client stubbed at `ps._get_openai_form_fill_client_sync`. Reports fields asked vs owed and document coverage. Run it in **both** `--answer none` and `--answer all` modes. |

---

## 8. CHANGELOG - BATCH 5 (3-4 Sep 2026)

Measured on the SYS-05 two-document kit, not the T1 kit. Every row is a box that
shipped blank while the fact was present.

| date | change | before -> after | files |
|---|---|---|---|
| 2026-09-03 | **G3** `_lob_tokens` read "Bodily Injury And Property Damage Liability" as the Commercial Property line, so one policy number appeared to span two lines | **total policy premium `None` -> $18,605**; real Property lines still match their own checkbox | `lob_canon.py`, `pdf_service.py` |
| 2026-09-03 | **G4** a LOB premium box accepted only ACORD's own tooltip wording; the Crime line printed under its ISO name | **CRIME premium box blank -> $1,225**; `auto` deliberately excluded from the fallback (three boxes claim it) | `pdf_service.py` |
| 2026-09-03 | **G5** the merge's role gate read `k not in _LIST_FIELDS or witnesses(...)`, so a role-blind SCALAR sailed straight through | a certificate's LIMIT no longer becomes `property_building_value`; COPE honestly reports it missing again | `extraction_service.py`, `fact_comparison.py` |
| 2026-09-03 | `_gate_inferred_valuation_method` - a closed choice (`"RCV"|"ACV"|null`) the model picked from rather than leaving null | invented `ACV` dropped; the valuation advisory stops firing on a method no document names | `extraction_service.py`, `coverage_evidence.py` |
| 2026-09-04 | **G6** `operations_description` stated against the PREMISES never reached the applicant-level box | derived when every premises agrees; refuses when they differ | `extraction_service.py` |
| 2026-09-04 | **G2** Guard 4 clustered fuzzily but demanded byte equality to exempt a field's own value | one trailing period deleted both operations boxes; now exact / near-duplicate / directional containment | `pdf_service.py` |
| 2026-09-04 | **G1** `_is_truncated_copy_of_a_held_value` treated any PREFIX as a truncation | **2 boxes recovered, 0 lost, 0 changed** on the real-session field diff | `pdf_service.py` |
| 2026-09-04 | `why_is_ops_blank.py` - one command, names the failing layer | six code-based hypotheses had been wrong first | `scripts/why_is_ops_blank.py` |
| 2026-09-04 | 48 + 71 + 21 new tests | **suite 5503 passed / 1 known `httpx` failure** | `test_two_document_regressions_20260904.py`, `test_inferred_value_gates_20260903.py`, `test_advisory_presentation_20260903.py` |

### What to check on the next form-fill run

1. **ACORD 125 Description of Operations AND Description of Primary Operations**
   must both be filled on a multi-document package. They were the G1 symptom.
2. **Total Policy Premium must not be blank.** A blank there means the line list
   was rejected again - grep the log for `spans 2 different LINES OF BUSINESS`.
3. **Every ticked LOB checkbox must carry its premium.** A ticked line with an
   empty premium box is G4 recurring under a different printed name.
4. **Grep the run for `truncated_copy blanked=` and `post_fill_guard`.** Both
   guards log by name; a legitimate value named in either line is a regression.
5. **A certificate must not supply COPE or exposure values.** If building value
   stops being reported missing on a dec-plus-certificate package, G5 regressed.
