# fix-form-stamping.md

> ## START HERE - handoff, 2026-08-09
>
> **Baseline to compare against:** `py -m pytest -q` from `backend/` gives
> **1758 passed / 2 failed / 2 skipped** (was 1715 before the run-5 pass). The two failures
> (`test_arq_acord125_missing_only`, `test_normalization`) are **pre-existing and
> unrelated** - they failed before any of this work. Anything else is yours.
>
> **What shipped:** 14 workstreams, ~270 new tests, zero regressions. Of the
> client's 22 reported ACORD 125 issues: **18 fully closed, 2 partly, 1 corrected
> as not-a-defect, 1 open.** Plus **8 defects found by sweep that nobody had
> reported** - including auto liability limits misstating coverage on
> certificates, and a routing bug that silently undid several fixes.
>
> **The four highest-value things to know before touching anything:**
>
> 1. **`return None` from a resolver means "ask the LLM", NOT "leave blank".**
>    See "CRITICAL - authoritative blank" below. This silently undid several
>    shipped fixes and every unit test still passed. If you add a resolver that
>    must suppress a box, register it in `_AUTHORITATIVE_BLANK_RESOLVERS`.
> 2. **`SCORE_SHAPE_PARTITION` is in SHADOW mode.** The candidate-ranking root fix
>    is built and logging but NOT changing output. Grep a real run for
>    `SHAPE_PARTITION`, read the disagreements, then set `=on`.
> 3. **Verification is offline only.** Everything is proven against the client's
>    literal values, never against a live end-to-end run. The remaining gap is a
>    field-by-field diff on the Orbin documents proving total filled fields went
>    UP. That needs real documents + an API key.
> 4. **Yes/No rules are protected.** The user's standing instruction: no change
>    that reduces Yes/No coverage. See "VERIFIED - judged by MEANING" for what was
>    measured and the 0.8% case deliberately left alone.
>
> **UPDATE 2026-08-09 (second pass)** - two real ACORD 125s were diffed field by
> field and **three of the previous pass's claims did not hold live**: the four
> per-line premiums never landed (the column is byte-identical to the old run),
> Commercial Property is still ticked, and the prior-coverage grid fills nothing
> rather than "more than before". Three regressions were also introduced by that
> pass. See "SHIPPED 2026-08-09 (second pass)" below. **The lesson repeated: run
> the app, then believe the PDF, not the write-up.**
>
> **Still open, in priority order:**
> - **Package-derived attachment boxes (client #6)** - blocked on a
>   `map_facts_to_form` signature change; highest-value item remaining.
> - Deposit box, Program Code/Name, and ACORD 125 Question 1a/5 dependents all
>   have **no owning rule at all** - they are gap-fill's by default. A box with
>   no owner is a box the model owns; that is the mechanism behind every new
>   regression this session.
> - FEIN `0482854` still stamps (now orange, not falsely "verified"); business
>   phone still the producer's; website still wrong - all three need a fresh
>   extraction to exercise the new entity facts, then re-measure.
> - `Business Auto $35` - extraction produced a wrong per-line premium.
> - `# D13` duplicated in address line 1 and 2 (client #12).
> - Additional-interest address/phone, `subsidiary`/`50%`, state producer licence
>   `W6258-0001`, Driver Information Schedule tick.
> - Alias bridge (`alias_stamper.CANONICAL_TO_EXTRACTION`) still holds the
>   duplicate `contact_*` pairing - harmless today because Pass 1 resolves those
>   fields first, but a trap if anyone reorders the passes.
> - Garage comp/collision (138/160) and GL BI/PD deductible (126) - same
>   one-fact-many-columns shape, need per-part facts, unreported.
>
> **Files that carry the context:** this file (mechanisms + issue log),
> `Acord125-test-result.txt` (the client's full 22-issue report),
> `improving-ll.md` C34 (prompt/cost record), `CLAUDE.md` (project rules).
> Memory: `form-stamping-mention-vs-grant`.

---

## SHIPPED 2026-08-09 (second pass) - three live-run regressions, and the two items I DIDN'T ship

**Found by diffing two real generated ACORD 125s (`test1` old, `test2` new), not by
unit tests.** The previous pass's own write-ups claimed things the live PDFs falsify -
that is the standing lesson of this file, and it repeated.

### W1 - a `coverage_lines` MENTION was being read as a GRANT
`apply_declared_absent_downgrades` refused to downgrade a flag when any
`coverage_lines` entry's name contained the line word. So a bare
`{"line": "Commercial Property"}` - which is exactly what the model produces when the
dec page says `PROPERTY - NO COVERAGE` and RULE 16 is not obeyed - vetoed the
downgrade and **Commercial Property stayed ticked on the client's own package.**

**The `coverage_lines` feature DISABLED the fix for the line the client reported.**
The veto did not exist before it shipped. This is the project's oldest root cause -
mention-versus-grant - reappearing one layer up, inside the mechanism built to fix it.

An entry now vetoes only when it carries corroborating detail beyond its own name
(premium / policy number / carrier / NAIC / dates) **and** none of that detail is
itself a coverage denial - the client's run literally stamped `"No Coverage"` into the
premium box, so that shape is observed, not hypothetical. A `line` value that reads
like a CARRIER name ("EMC Property & Casualty Company" contains "property") cannot
veto either; it reuses `field_mapping_integrity.looks_like_carrier` rather than a
second copy.

**Coverage is protected by test, not by assertion:** four parametrised cases prove a
line with a real premium / policy number / carrier / effective date is never
downgraded. Requiring a *premium specifically* was considered and rejected - RULE 16
tells the model to leave premium null rather than divide a package total, so a real
line legitimately has none.

### W2 - every ownership guard we own runs on the deterministic path only
The new run stamped `BusinessInformation_ParentOrganizationName_A = "Emc Insurance
Companies"`, so a signed ACORD 125 asserted **the applicant is a subsidiary of its own
insurer**, and put the producer's phone + the carrier's claim line into the applicant's
secondary-phone boxes. Three layers all missed it: `_FACT_ENTITY`/`_entity_mismatch`
guard Pass 1 only; the raw-text check passes because the carrier's name IS in the
document; and `field_mapping_integrity`'s own docstring records parent/subsidiary
organization names as **"deliberately excluded"** - a judgement made when the risk was
theoretical and now falsified by a real form.

`_drop_foreign_entity_values` is the gap-fill counterpart: a value-IDENTITY match
against facts we already hold for a DIFFERENT party, the same shape as
`_drop_third_party_address_bleed`. Not a heuristic, no topic matching, and it cannot
fire when we hold no carrier/producer fact.

**`normalize_carrier` is load-bearing here.** "Emc Insurance Companies" and "Employers
Mutual Casualty Company" are not equal as strings; only the carrier-family
normalisation makes them match. **This reverses an earlier recommendation in this
session to delete `normalization._CARRIER_ALIASES` as a hardcode** - it is the one
thing that catches the reported case. The correct follow-up is to make it GENERIC (an
acronym-expansion rule works for GEICO / AIG / CNA / USAA and every other carrier),
not to remove it.

**Scope was decided by sweep, and the exclusions matter as much as the inclusions.**
In: `NamedInsured_*`, `BusinessInformation_*` (all 23 field families across 17 forms
verified applicant-owned), `Subsidiary_*`, `Driver_*`. **Permanently OUT:
`UnderlyingPolicy_*` (ACORD 131) and `OtherInsurance_*` (ACORD 160) - a carrier name
is the CORRECT value there**, and adding them would blank legitimate data. There is a
standing test that fails if anyone widens the tuple onto them.

`Driver_*` was added on evidence, not theory: `improving-ll.md` C22 records a real
ACORD 127 run with the PRODUCER's name in `Driver_TaxIdentifier_I` and
`Driver_GenderCode_A`, and explicitly notes the gender-code case was **invisible to a
type check**. It is not invisible to ownership. 269 fields x 15 driver-appropriate
values = 4,035 pairs, zero false positives.

**False-positive sweep, matching C22's bar:** 291 in-scope fields x 23 legitimate
applicant values = **6,693 pairs, zero false positives**, plus the 4,035 above.
Ambiguity fails toward KEEPING the fill: a value that is also one of the applicant's
own facts is never blanked.

### W3 - the SIC grounding gate was open on every document
`_CLASSIFICATION_CODE_LABELS` required the document to name the code system, and the
SIC token was the three-character string `"sic"` matched as a bare substring.
**`basic`, `classic`, `physician`, `intrinsic`** all satisfy it, so the SIC half of
that guard has never once rejected anything. That is how an EMC rate/class code
reached the SIC box. Now whole-word (`\bsic\b`), applied uniformly to all three label
families rather than special-casing the one that broke. NAICS (5 chars) and the GL
phrases were never exposed.

### Two items I did NOT ship, and why - read before re-planning them
* **Giving `sic_code` a `tier` so it reaches the client questionnaire: WRONG.** ARQ
  questions are not generated from `FACT_REGISTRY` tier at all -
  `generate_arq_questions` iterates each form's **confidence map**, so an empty or
  low-confidence FORM BOX is what becomes a question. Tier drives hard gates. Changing
  it would have done nothing and risked the gating.
  **Real residual:** on ACORD 125 only `missing_required` empty boxes become
  questions, so a blanked non-managed box there has no recovery path. That is the
  honest limit of W3 and it needs the ACORD 125 managed-set question answered before
  anyone blanks more fields on that form.
* **Deriving the `Policy_SectionAttached_*` boxes from the package we generate
  (client #6): BLOCKED, not skipped.** `map_facts_to_form(facts, schema, form_id,
  raw_text, pre_filled_gpt)` has no knowledge of which OTHER forms are selected, and
  `process_single_form` only receives its own `form_meta`. Doing it properly is a
  signature change on the most-called function in the codebase and earns its own
  workstream. **It is the highest-value item still open** - it closes Driver
  Information Schedule, Open Cargo, EDP and Contractors Supplement generically on all
  17 forms. Note `CommercialPolicy_Attachment_ContractorsSupplementIndicator` contains
  the substring `Attachment_`, which is in `_NONFILLABLE_SUBSTRINGS`, so its
  `_INDICATOR_RULES` entry is **dead code today** - that collision must be resolved in
  the same change.

**No prompt and no LLM call was touched, so `improving-ll.md` needs no entry** (its
maintenance rule is scoped to prompts, call sites and batching). Checked, not assumed.

Tests: `backend/tests/test_entity_and_grant_guards.py` (35). Suite **1618 passed / 2
failed / 2 skipped** against a **1583 / 2 / 2** baseline - +35 is exactly the new file,
and the two failures are the same pre-existing unrelated ones
(`test_arq_acord125_missing_only`, `test_normalization`). Zero regressions. The 61
full-document-coverage / prefix-caching / umbrella-probe / text-cleaner guards were
re-run separately and are green; `GAP_FILL_FULL_RESCAN=auto` still resolves to off on
one chunk and on at two.

---

## SHIPPED 2026-08-09 (run 5) - AUTHORSHIP: who is entitled to say this?

Run 5 confirmed three of run 4's fixes held live - FEIN blank, producer printed name
blank, `Emcasco Insurance Company` gone from the subsidiary box. Five defects remained.
Four of the five are one question the pipeline never asked: **who is entitled to say
this?** Not "is the value right" - the values were all real strings from the document.

**Suite: 1758 passed / 2 failed / 2 skipped.** Same two pre-existing failures
(`test_arq_acord125_missing_only`, `test_normalization`). +43 tests, zero regressions.

### 1. Policy METADATA was being read as a coverage GRANT

`extraction_service._LINE_EVIDENCE_KEYS` accepted `policy_number`, `carrier`, `naic` and
`effective_date` as proof that a `coverage_lines` entry was real. Extraction attached the
**Inland Marine** policy number (`6C7-40-02---26`) to an entry it named "Property", and
that one borrowed number vetoed the dec page's own printed `PROPERTY - NO COVERAGE`.

**Three symptoms, one cause:** Commercial Property stayed ticked, took an "other line of
business" row, AND filled a Q4 row.

Narrowed to `("premium", "limit")`. **Money is the grant** - a carrier charges a premium
or promises a limit only for coverage it is writing, so either genuinely conflicts with a
printed denial and coverage wins. A number, a carrier, a NAIC or a date can all sit
against a line that is merely REFERENCED (a cancellation notice, a prior-carrier block, a
schedule cross-reference) and says nothing about whether it is being written.

This changed an existing coverage-protection test, deliberately and with the reasoning
written into it: `test_policy_metadata_cannot_outrank_a_printed_denial`. The property
that must never be relaxed - `test_real_coverage_is_never_downgraded` - now covers
premium and limit, and `test_metadata_plus_money_still_keeps_the_coverage` proves the
realistic granted shape (a number AND a premium) is untouched.

### 2. `NamedInsured_Initials_A` - the machine initialling for the insured

Tooltip: *"Initial here:"*. The signature block was already closed; the initials box was
not, and gap fill put a text fragment in it. Added `"_Initials"` to
`_NONFILLABLE_SUBSTRINGS` - with the leading underscore, so ACORD 127's
`Driver_OtherGivenNameInitial_A`, a legitimate NAME field, is untouched. 11 boxes across
the schemas, all covered, guarded by a harvest test.

### 3. Four "Section attached" boxes had no rule and fell through to the model

`Policy_SectionAttached_*Indicator` asserts something about **the submission we are
producing**, never about the carrier's dec page. Four of the eight had a rule (builders
risk, open cargo, vehicle schedule, driver schedule). The other four - **Electronic Data
Processing**, Glass and Sign, Dealers, Accounts Receivable / Valuable Papers - had none,
so the model saw "Electronic Data Processing" printed on an inland-marine schedule and
ticked the box. Mention versus grant, one level up.

`_resolve_section_attached_indicator` defers to any existing `_INDICATOR_RULES` entry and
returns an authoritative blank otherwise, so **wiring a new section later needs nothing
here**. `test_the_family_is_fully_partitioned_on_every_form` asserts every member of the
family either has a rule or is closed - a new ACORD section cannot quietly reopen.

### 4. The policy talking about itself, in a box about the applicant

`Subsidiary_ParentSubsidiaryRelationshipDescription_A` came back holding endorsement
wording. The client had already written the rule for the Y/N gate - *"Never convert
generic policy terminology into applicant-history facts"* - and the gate never saw this,
because **the gate only runs on Yes/No fields**.

`_is_policy_contract_language()` reuses the same two anchors (`_POLICY_CONTRACT_LANGUAGE_RE`,
`_EXCLUSION_CLAUSE_RE`) on gap-filled narrative, with a 40-char floor and Remarks exempt
(ACORD 101's overflow rows carry policy text by design). Measured: **5/5 contract clauses
caught, 0/10 legitimate applicant statements touched** - including "We have had no claims
in the past five years", which is the sentence that makes topic-word matching unsafe.

### 5. The invented applicant website

Run 4 put the CARRIER'S site there; run 5 put `Http://go.cms.gov/mirnghp` - a Medicare
reporting address from policy boilerplate. **Both are valid URLs, so no shape check helps,
and neither matches a party value we hold, so no ownership guard helps either.** A dec
package essentially never states the INSURED'S website; every URL in it belongs to the
carrier, a regulator or a form vendor. `_resolve_applicant_website` reads the
RULE-15-scoped `applicant_website` fact or stays blank, which routes it to the client
questionnaire - the only place the real answer exists.

### Two defects I introduced and caught by measuring, not by testing

Worth reading before adding a shape token:

- **A substring match ran the count validator over a CHECKBOX.** ACORD 133's
  `Policy_NoPreviousCoverage_EmployeeCountIndicator_A` merely MENTIONS an employee count;
  the check would have blanked its tick. Tokens now match a **CamelCase segment suffix**
  (`FullTimeEmployeeCount` counts, `EmployeeCountIndicator` does not).
  `test_no_checkbox_is_ever_shape_checked` re-derives this from the real schemas.
- **`^\d{5}$` would have blanked a Canadian postal code**, and `^\d{1,7}$` would have
  blanked `1,200`. Two of the 59 postal boxes sit beside an
  `AdditionalInterest_MailingAddress_CountryCode` field, so a non-US code is legitimate
  there. Now: US 5/5+4 or Canadian A1A 1A1; a count is **exactly one number**, however
  written - the defect is TWO numbers (`0 - 25`) or NONE (`LLC`).

Shape-check scope went 40 -> **192 fields**, swept **841 legitimate pairs with 0 false
positives** before the bound moved (C22's precedent). `test_the_swept_scope_has_no_false_positives`
keeps it that way, with a non-vacuity assertion.

### Still open after run 5

- **`Business Auto $35`** - extraction picks a fee/surcharge line as the Business Auto
  premium. Fixed on the PROMPT side only (RULE 16 now excludes TRIA charges, policy and
  service fees, state surcharges, minimum premiums, endorsement/audit adjustments and
  per-vehicle shares). **A deterministic floor was considered and rejected**: this same
  document has a legitimate $300 Inland Marine premium, so any absolute or
  relative-magnitude floor that catches $35 also kills $300. Needs a live re-run to
  confirm the prompt rule holds.
- `PAYMENT PLAN "AN"` truncation; `STATUS` showing Issue and Renew both ticked; state
  producer licence `W6258-0001`.
- `SCORE_SHAPE_PARTITION` still in shadow - read a real run's `SHAPE_PARTITION` lines
  before enabling.

---

Shared context for every chat fixing "the form has the wrong thing stamped on it".

**Read this before you touch a checkbox, an indicator, or a paired amount/description
field on any of the 17 ACORD forms.** Client keeps reporting these one at a time. They
are not separate bugs. They are four mechanisms sitting on one root cause.

**Status legend:** `DIAGNOSED` = root cause proven in code, fix specified, NOT shipped.
`SHIPPED` = in the tree with tests. Update the log at the bottom when you ship.

---

## SHIPPED 2026-08-09 - Entity ownership (M5, the "mixture of client and carrier information")

**It was never the LLM.** `_ACORD_FIELD_RULES` mapped ONE fact into several
different parties' boxes deliberately: `contact_phone` fed
`Producer_ContactPerson_Phone` **and** `NamedInsured_PhoneNumber` **and**
`NamedInsured_Primary_PhoneNumber` **and** `NamedInsured_Contact_PrimaryPhoneNumber`.
Same for `contact_email` and `contact_name`. The alias bridge
(`alias_stamper.CANONICAL_TO_EXTRACTION`) held a second copy of the same pairing.

Three settled the ambiguity in the same direction, so `contact_*` is the
**applicant's**: `fact_registry` ("the best phone number to reach **you**"),
`arq_service` (which puts that question to the insured), and the ARQ answer path.

**What changed**
1. **Extraction now has entity-scoped identity facts** - `producer_contact_name`,
   `producer_contact_phone`, `producer_contact_email`, `producer_fax`,
   `producer_address`, `applicant_website`, `carrier_website`. Additive: these
   boxes had nothing correct to draw on before.
2. **`RULE 15 - ENTITY DISCIPLINE`** in the extraction prompt names the owning
   party for every identity fact and states plainly that `null` is the correct
   answer when a party's own value is not stated. Generalises RULE 14, which
   already did this for the single `naics_code` / `carrier_naic` pair.
3. **`_FACT_ENTITY` + `_entity_mismatch`** - a declarative fact→party table and a
   generic guard, wired into all three rule call sites (`_resolve_via_field_rules`,
   `_deterministic_map`, `_first_rule_fact`). Returns `UNMATCHED`, never blank, so
   gap fill can still read that party's own value. This is the general form of the
   `_addr_*` guard that already existed for addresses only.
4. **Two ROLE mappings corrected** - `NamedInsured_BusinessStartDate` read
   `years_in_business` (a duration, registry validator `positive int <= 500`) into a
   box ACORD declares "Enter date"; it now reads a new `business_start_date` fact.
   `BusinessInformation_PartTimeEmployeeCount` read the overall headcount, stamping
   the same number into both the full-time and part-time boxes.
5. **Named `_is_email` / `_is_phone` / `_is_url` validators** (none existed). The
   phone one now requires 7 real digits - the pattern it replaced accepted
   `"(   )   -    "`.

**Two traps worth knowing about, both caught by the existing suite:**
- `BusinessInformation_FullTimeEmployeeCount` **keeps** its fallback to the overall
  total. A live client answered "How many people does your business employ?" and the
  PDF box never changed; `test_employee_count_falls_back_to_the_scalar_total...`
  locks that in. The total is a defensible stand-in for ONE of the two boxes and
  never for both - which is exactly what `Contractors_PartTimeEmployeeCount` had
  already concluded and nobody generalised. `_FACT_FALLBACKS` carries the one hop.
- **Three separate indexes resolve a client answer back onto a form box**
  (`fact_to_form_fields`, `_backfill_and_resolve_present`, and
  `_restamp_canonical_into_forms`) and all three had to learn about the fallback or
  the questionnaire answer silently stops reaching the PDF. Two of them broke on
  the first run. `_canonical_keys_for` is the single helper they now share.

**Standing guard:** `test_no_live_rule_stamps_across_parties` sweeps all 55 rules
against all 5,852 fields in all 17 schemas and fails the build if any pairing
crosses a party boundary. `test_entity_prefixes_are_real_acord_prefixes` caught a
typo in my own table on its first run (`ParentCompany` matches no field on any form).

Tests: `backend/tests/test_entity_ownership.py` (23). Suite **1339 passed / 2
failed** - the same two pre-existing unrelated failures as baseline
(`test_arq_acord125_missing_only`, `test_normalization`), zero regressions.

**Not yet done in this area:** the producer's street address still has no
deterministic source (client #1), and the Pass 1.5 alias bridge still contains the
duplicate `contact_*` pairing - harmless today because Pass 1 resolves those fields
first, but it must be repointed before anyone reorders the passes.

---

## SHIPPED 2026-08-09 - Per-line coverage data (the blank premium column)

**The premium column was blank by instruction, twice over.** `"Premium"` is in
`_NONFILLABLE_SUBSTRINGS`, and `map_facts_to_form` blanks those **before any
deterministic resolution runs** - so no fact could ever have reached them, whatever
we extracted. The gap-fill prompt separately says "Do NOT fill premium/rate fields".
And no per-line premium fact existed anyway.

That block was doing two jobs and only one of them was right: the LLM must never
*invent* a premium, but a figure printed on the dec page is a **copy**, not a carrier
computation.

**What changed**
1. **New `coverage_lines` fact** - `[{line, carrier, naic, policy_number, premium,
   effective_date, expiration_date}]`. One list, because a package really is written
   per line and a single `carrier_name` / `policy_number` scalar structurally cannot
   represent two affiliated carriers. Extraction captures the whole structure; only
   the premium is stamped so far. **`RULE 16`** tells the model to leave a line out
   when the document says "No Coverage", and to leave `premium` null rather than
   divide a package total.
2. **Which box belongs to which line is read from ACORD's own tooltips** - the
   checkbox says *"Indicates that Business Auto line of business is being selected"*
   and the premium box says *"The premium amount for the Commercial Vehicle
   (Business Auto) line of business"*. Parsing those gives **15/15 pairs on ACORD 125**
   with **no hardcoded synonym table**, and it self-updates if a schema is regenerated.
3. **The nonfillable block was split by job.** `compute_form_gaps` still treats premium
   boxes as non-fillable, so the LLM is never asked for one; `map_facts_to_form` now
   resolves them deterministically from `coverage_lines`.

**It refuses to guess, in both directions.** A document line whose wording fits several
boxes (a bare "Liability" fits General Liability, Fiduciary **and** Liquor Liability) is
skipped rather than assigned to one; two document lines resolving to the same box with
different amounts leave it blank and log a warning. Blank beats plausible on a figure
that appears on a signed application.

**Verified on the client's literal amounts:** `$3,954` -> GL, `$300` -> Inland Marine,
`$2,991` -> Commercial Vehicle, `$3,418` -> Umbrella; Crime, Property and Cyber stay
blank because those lines are absent from `coverage_lines`. Four boxes that are empty
today now fill correctly.

**A real pre-existing defect fell out of the standing guard.** `lines_of_business` was
in `_LIST_FIELDS` but **not** in `_LONG_DOC_LIST_KEYS`, so the cross-chunk merge scored
it as a scalar and kept ONE chunk's list - a line named only in a later chunk was
discarded, taking its ACORD 125 checkbox with it (`_INDICATOR_RULES` reads that fact for
BOP / garage / truckers / liquor / fiduciary / yacht / motor carrier). Merging is a union
with dedup, so fixing it can only preserve lines, never invent one.

**The guard's own first version was vacuously green** - anchoring the harvest on
`^  "key": [` missed the two facts that share a line with another key, so it checked 16
of 18 and passed. That is exactly the trap `improving-ll.md` C25 documents. It now strips
nested `[{...}]` bodies instead, and carries a canary self-check.

Tests: `backend/tests/test_coverage_lines.py` (15). Suite **1354 passed / 2 failed** -
the same two pre-existing unrelated failures, zero regressions. Prompt shape re-verified
offline (`PASS - prefix is stable and cacheable`, system prompt identical across all 13
gap-fill calls). Logged as C34 in `improving-ll.md`.

**Not yet done:** `coverage_lines` carries carrier / NAIC / policy number per line but
only the premium is stamped. The multi-carrier header (client #3) and the prior-coverage
grid (client #17) are the next two consumers - see below.

## RUN 4 (2026-08-09) - what landed, and 3 more fixes

**Verified clean on the generated form:** the entire Additional Interest block is
now EMPTY (EMC's name, address, phone, reason and its Additional Insured /
Certificate / Policy ticks all gone); the prior-carrier grid is EMPTY (was the
current policy presented as history); the duplicate auto policy number is gone;
loss history is blank; payment plan, method and deposit are correct; the NAICS
garbage is gone; and the Y/N column carries no unsupported answers.

**Three defects this run exposed, all fixed:**

**Q4's two columns were SWAPPED.** The form read "Commercial General Liability /
6E7-40-02---26" (the AUTO number) and "Commercial Auto Liability / BBC7263" (the
GL number). The line and the number are two boxes on one row and gap fill filled
them INDEPENDENTLY - nothing tied them together. They are now stamped as a PAIR
from a single `coverage_lines` entry, so a mismatch is structurally impossible,
and a line with no policy number takes no row rather than shifting every row
beneath it.

**A premises row that was row A rewritten.** Row B read "4800 Dahlia St D13
Denver CO. 80216-3121" against a row A of "4800 Dahlia St # D13" - the same
location with the city and ZIP folded in. Guard 2 only collapses an EXACT
duplicate, so it walked straight past. Guard 11 compares on alphanumerics with
containment, floored at 10 characters; a genuinely different second location
survives (tested).

**Carrier bleed through the GAP-FILL path - fixed after run 4.** Every ownership
guard compared against a value we ALREADY HELD, which is why these three survived
four consecutive runs:

- **A carrier by SHAPE, not by name match.** `Emcasco Insurance Company` is a
  member of the carrier's GROUP and is never named as the carrier, so no
  comparison against `carrier_name` could catch it. `_looks_like_an_insurance_carrier`
  anchors on insurer noun PHRASES ("insurance company", "risk retention group"),
  never a bare word - measured 8 carriers rejected, 0 false rejections across 9
  real applicant names including "Summit Insurance Agency", "Denver Mutual Water
  Company" and "Casualty Restoration Services LLC". Stands down entirely if the
  APPLICANT is itself carrier-shaped.
- **An impossible value is now REFUSED, not coloured.** `0482854` kept landing in
  the FEIN box for four runs; demoting stopped us CLAIMING it was verified but
  the value stayed. **This is a deliberate narrowing of "stamp it and highlight
  it"**: that rule is for values we are UNSURE about, and a 7-digit string in a
  9-digit tax ID box is impossible, not uncertain. Scoped to the FOUR hard shapes
  (FEIN, email, phone, URL) and to GAP-FILL values only - an amount box holding
  "Statutory" is untouched, and everything merely uncertain still demotes.
- **The producer's printed name is anchored.** It returned "Scott R. Jean" one
  run and "Todd A. Strother" the next from the same document - EMC executives in
  policy boilerplate. It now reads `producer_contact_name` or stays blank: a
  signature block identifies the person signing, and if we do not know the
  producer contact, no model may nominate one. The signature beside it was
  already non-fillable.

**Still open after run 4:**
- `Business Auto $35` - extraction produces a wrong per-line premium.
- Q1a relationship still carries endorsement text ("Any legally incorporated
  subsidiary in which..."); the `50%` beside it is demoted but present.
- `Applicant's Initials` = "Or", a fragment of "Orbin".
- EDP attachment came back UNTICKED though the client wants it kept.

---

## THE CLIENT'S OWN THREE-WAY DISTINCTION - the sharpest statement of the root cause

From their Part 11 / Part 12 feedback, and worth quoting in full because it is
the best summary anyone has written of what this whole file is about:

> "The central defect is that Primble is not distinguishing among:
>   **Policy metadata** - dates, carriers and policy numbers
>   **Policy contract language** - bankruptcy, judgments, liens and cancellation
>     provisions
>   **Applicant-history facts** - actual bankruptcies, violations, cancellations
>  Only the third category belongs in these ACORD 125 questions."

> "Primble is treating policy language describing who COULD be covered as
>  evidence that the entity or condition EXISTS."

Two of their rules are now enforced generically:

**A policy date is never an event date** (Guard 9). Their words: *"A policy
effective date must never be repurposed as an occurrence, loss, violation or
incident date."* The live form had the policy inception `07/15/2025` in the
uncorrected-fire-code OCCURRENCE DATE. An equality test against the policy's own
metadata dates - no topic matching, no guessing the real date - across the **25
event-date boxes on ACORD 125 (18), 131 (6) and 127 (1)**. Format-independent via
the shared `normalize_date`, because a digits-only comparison is order-sensitive
and `2025-07-15` would have slipped past `07/15/2025`. A genuine violation date
survives; the policy's own date boxes are untouched.

**Policy contract language answers neither Y nor N.** Their words: *"That clause
describes how coverage operates after bankruptcy. It does not say that Orbin
Contracting filed for bankruptcy."* Applied to **both** directions, unlike the
exclusion checks - "Bankruptcy or insolvency of the insured will not relieve us
of our obligations" reads as a negation and was keeping a false **"N"** alive.
Anchored on the INSURER speaking as a party ("relieve us", "our obligations",
"under this policy"), never on a topic word, so an applicant writing *"We have
had no claims in the past five years"* is untouched - that exact sentence is a
test. Measured: 5 contract quotes rejected, 0 false rejections across 7 genuine
applicant statements.

**All three Part 11/12 items are now closed** (`test_provision_is_not_existence.py`):

**An unnamed additional interest asserts nothing.** EMC was stamped as an
ADDITIONAL INSURED with its servicing address and a phone, on the policy it
services - Primble had found blanket additional-insured wording and treated the
insurer as the named interest. The orphan-row rule now covers
`AdditionalInterest` and `CertificateHolder` **including row A**, on a principled
distinction: the Named Insured's row A always exists because the form is about
them, while an additional interest is OPTIONAL. A NAMED interest keeps every
detail; `test_the_named_insured_row_a_is_still_never_questioned` holds the other
side.

**Parent / subsidiary detail with nobody named.** `parent company`, `50%` and
`subsidiary` were filled with no parent or subsidiary NAME anywhere, inferred
from an endorsement that merely says a qualifying subsidiary WOULD be covered.
`_ANCHORED_DETAIL_GROUPS` pairs those boxes with the name field that gives them a
subject - the two families have different prefixes, so the row-and-prefix
grouping could not see them.

**The same policy listed twice.** `6E7-40-02---26` and the compact internal form
`6E74002` are one Commercial Auto policy. **Equality fails** - the keys are
`6E7400226` and `6E74002` - so the comparison is by PREFIX with a 6-character
floor, and the longer spelling wins because the client asked for "the consistent
declarations-page format". `test_genuinely_different_policies_are_all_kept` is
the load-bearing guarantee.

**Note on treatment:** the client asked for these to be *removed*; the standing
product instruction is *stamp and highlight*. The two unnamed-entity cases are
DEMOTED (value stays, turns orange) to honour that instruction - the duplicate
policy number IS cleared, because a duplicate is the one case where removing
loses no information. **If the client pushes back, the change is one line: move
those fields from `_shape_failures` to a blank.**

---

## RUN 3 (2026-08-09) - what the third generation proved, and 2 more fixes

**Confirmed working on the real form:** GL premium `$3,954` and Inland Marine
`$300` now stamp correctly (the premium column was 100% blank before); Open Cargo
is no longer ticked; EDP is back; Question 6's exclusion-grounded "Y" is gone;
the prior-carrier grid now puts EMC Property & Casualty against GL and Employers
Mutual against Auto with **Property and Other correctly empty** - the per-line
resolver is working.

**Y/N RULE RE-VERIFIED END TO END** after a report that Y/N looked empty. It is
intact: 27 compliance questions detected on ACORD 125, the dedicated pass is
wired (`_COMPLIANCE_SYSTEM_PROMPT`, `is_compliance_question`, `_COMPLIANCE_BATCH`
all still referenced), and the gate still accepts meaning-based answers with no
literal yes/no word - "scrap and used cutting fluid are removed by a licensed
hazardous-waste hauler" keeps its Y, "has no prior cancellations" keeps its N.
**Mostly-blank is the rule working**: a declarations page genuinely cannot answer
most of the 15 General Information questions, and blank routes them to the
client questionnaire.

**Two more real defects fixed from this run:**

**Guard 8 - tooltip echo.** `AdditionalInterest_FullName_B` (tooltip: *"The
additional interest's full name. As used here, this is the name of the trust."*)
came back stamped **"The Additional Interest's Full Name. As Used Here, This Is
The Name Of The Trust."** - our own prompt text, title-cased, reading as though a
real trust had been named. An earlier attempt at this feature was ABANDONED as
unsafe; the difference is the threshold. A 103,464-pair sweep measured false
positives at 86 (16 chars), 16 (20), 14 (25) and **ZERO at 30**. Below 30 it
blanks real answers like "Business Personal Property". `_TOOLTIP_ECHO_MIN_CHARS`
is pinned by test - **do not lower it.**

**Exclusion CLAUSE cannot ground a "Yes".** Question 3 ("any exposure to
flammables, explosives, chemicals?") came back "Y" on *"This insurance does not
apply to: Asbestos"*. The exclusion TITLE fix did not catch it - this is the
clause form. Y-GATE ONLY, deliberately not shared with `_COVERAGE_DENIAL_RE`:
"this insurance does not apply to flood" near the word Property would wrongly
downgrade the whole line. Measured 4 rejected / 0 false rejections across 8
genuine affirmative quotes.

**Known open from run 3, in priority order:**
- **Non-determinism**: NAICS, website and producer name differ between runs on
  the same document (`33.211` is not even a valid NAICS shape; the website is a
  `go.cms.gov` URL; the producer name alternated Todd / Scott). These are gap-fill
  inventions. The classification-code grounding guard exists and the "sic"
  substring bug is fixed, but NAICS shape is unvalidated and the producer name is
  being read off carrier boilerplate.
- `FEIN` now holds **`W6258-0001`** - the state producer licence number. Shape
  check correctly demotes it to orange but the value still lands.
- `PROGRAM CODE` holds the GL policy number; `COMPANY POLICY OR PROGRAM NAME`
  holds a form title.
- `METHOD OF PAYMENT` = `"thod the policy will l"` - a mid-word tooltip fragment,
  22 chars, **below the echo threshold and deliberately not chased**: the
  measured false-positive cost under 30 chars is worse than the defect.
- `NO. OF MEMBERS` = `"LLC"`; Q1a/1b now carry EMC group data as the applicant's
  parent/subsidiary; second Named Insured shows the producer's city/ZIP.

---

## SHIPPED 2026-08-09 - An exclusion title cannot ground a "Yes" (real run)

ACORD 125 Question 6 - *"any past losses or claims relating to sexual abuse or
molestation allegations, discrimination or negligent hiring?"* - came back **"Y"**,
grounded on **`BROAD ABUSE OR MOLESTATION EXCLUSION`**: a form title lifted off
the policy.

**An exclusion is the policy declining to cover a thing. It is never evidence the
thing happened.** Same exposure-versus-coverage conflation that ticked the Cyber
box, this time on the compliance pass.

`_EXCLUSION_TITLE_RE` rejects a Yes whose quote **is** a title - anchored to the
whole quote ending in "exclusion(s)". Deliberately NOT "contains the word
exclusion": *"the applicant had a molestation claim in 2023; an exclusion was
added at renewal"* is a real Yes that merely mentions one. Measured on 5 real form
titles and 5 genuine-event quotes: **5 rejected, 0 false rejections.**

---

## CRITICAL 2026-08-09 - "return None" meant "ask the model", not "leave blank"

**Found on a real run, after twelve workstreams had shipped. Read this before
writing any new resolver.**

A freshly generated ACORD 125 still showed one policy number sprayed across the
prior-coverage General Liability, Property and Other columns - the exact defect
`_resolve_prior_coverage_cell` exists to stop, with that resolver correctly
returning `None` for all three.

The resolver was right. The routing above it was not:

```python
result = _deterministic_map(field, facts)
if result == "UNMATCHED" or _is_empty_llm_value(result):
    unmatched[field] = schema[field]      # <- this means "ask the model"
```

**`None` out of `_deterministic_map` does not mean "leave blank". It means "no
rule had an answer, let GPT try the raw text."** So every deliberate blank was an
invitation to guess, and gap fill refilled it from the document.

**Every unit test passed**, because they all called `_deterministic_map` directly
and never exercised the routing above it. That is the lesson: *a resolver's
contract is only real if the caller honours it.* Test the routing, not the
resolver.

`_resolve_schedule_row` already had the right contract - *"If the row is out of
range, mark as authoritative blank (do NOT send to GPT - we know the row doesn't
exist)"*. `_is_authoritative_blank_field` now gives the three newer resolvers the
same treatment: a field an owning resolver claims but cannot fill is marked
deterministic-blank and never enters the gap-fill set.

**Bounded on purpose.** Only the three named resolvers confer ownership, and
`test_unowned_fields_still_reach_gap_fill` guards the other direction - this must
never become a blanket "blank everything" rule, or the fix costs fill everywhere.

Tests: `test_authoritative_blank_contract.py` (24). Suite **1571 passed / 2
failed**.

---

## ADVERSARIAL SWEEP 2026-08-09 - three defects found in MY OWN changes

After shipping twelve workstreams I went looking for what I had broken. Three
real defects, none reported by anyone, all now guarded.

**1. A minimum premium is not a line premium.** `_lob_premium_index` indexed
`BusinessOwnersLineOfBusiness_MinimumPremiumAmount_A` on ACORD 160, because its
tooltip names the same line as the real premium box. Two harms, and the second
was silent: it risked stamping the line premium into the minimum box, and because
the two boxes matched each other it tripped the ambiguity refusal and made the
**legitimate** Business Owners premium box on ACORD 160 permanently unfillable.
Excluded by ACORD's own wording ("minimum premium"), not by field name - General
Liability's real box is called `TotalPremiumAmount` and must stay.

**2. Stopping a wrong fill without providing a right one is a fill LOSS.**
`BusinessInformation_PartTimeEmployeeCount` and `NamedInsured_BusinessStartDate`
were repointed at correct new facts - registered `tier: None`, so the client
questionnaire never asks for them. The box goes blank and nothing can ever fill
it. **A pure fill loss dressed up as a correctness fix**, and the client had
already asked for both (#14 "Send these questions to the client", #15 "Obtain the
actual business inception date"). Both are now tier 2. Net new client questions
across the whole session: **four, every one client-requested.**

**3. A fact with no mapping can never receive its own answer.** `applicant_website`
was created, validated and asked for - and never wired to
`NamedInsured_Primary_WebsiteAddress`. `_canonical_key` resolves through
`_ACORD_FIELD_RULES`, so an unmapped box cannot receive a client-confirmed value
either. Found by `test_the_repointed_box_reads_its_new_fact` on its first run.

`test_no_orphaned_fill_loss.py` is the standing guard for the whole class: every
box repointed away from a wrong fact must have a recovery path, producer/carrier
details must NOT become questions for the insured, and every new fact must carry
a validator and a format hint or it escapes both the shape check and the ROLE
sweep.

**Also checked and clean** (so nobody re-runs it): the eight resolvers added to
`_deterministic_map` claim **zero overlapping fields**; all 35 rules they shadow
are the ones they deliberately replace; none raises on empty facts across all
5,852 fields; `_enforce_post_fill_guards` is idempotent; and the schema-keyed
caches cost ~3 ms per 50 calls on the largest form.

---

## SHIPPED 2026-08-09 - Auto liability: CSL vs split limits (sweep, unreported)

**The most serious thing found this session, and no client has reported it.**
`auto_liability_limit` was mapped into ALL FOUR liability boxes, so a single
$1,000,000 combined single limit stamped as:

    Combined Single Limit          $1,000,000
    Bodily Injury per person       $1,000,000
    Bodily Injury per accident     $1,000,000
    Property Damage per accident   $1,000,000

A real 100/300/50 policy carries three different figures. **On ACORD 25 - a
certificate a third party relies on - that is a material misstatement of
coverage.** 26 boxes across ACORD 25, 131, 137_CA and 137_CO.

A policy states its liability as a combined single limit **or** as split limits,
never both. `_resolve_auto_liability_limit_cell` routes on the `auto_split_limits`
flag extraction already produces, and three new facts (`auto_bi_per_person`,
`auto_bi_per_accident`, `auto_pd_per_accident`) give the split boxes something
correct to hold - previously there was no fact for them at all, which is why the
combined limit was being reused.

**It cannot cost the real fill.** An absent flag is treated as combined-single-
limit, which is both the common case and the existing behaviour for that box, so
the change only ever removes the three duplicates. And if a policy is flagged
split but the three figures were not captured, all four boxes stay blank -
falling back to the combined limit is exactly the misstatement being fixed.

Tests: `test_auto_liability_structure.py` (12), including a standing guard that
sweeps all 17 forms and fails if any split box shows the combined limit.

### Also closed: the ROLE sweep
`test_fact_field_type_agreement.py` asks generically whether a fact's own
declared type agrees with the ACORD type of the box it is mapped into - the
question that would have caught `years_in_business` landing in a box declared
"Enter date" without waiting for a client to notice. **290 mappings testable,
zero mismatches remaining.**

The sweep needed a second pass to be honest: a validator-only version returned
None for `years_in_business` (its validator is a lambda) and therefore SKIPPED
the exact bug it was written for. Adding the registry `format_hint` as a
secondary type signal fixed that, and `test_the_sweep_bites_on_the_bug_it_was_
written_for` proves it.

**Remaining sweep items, deliberately open:** garage comp-vs-collision (138/160)
and the GL BI/PD deductible split (126) are the same shape but need per-part
facts that no document reliably states, and neither has been reported. The
pattern and the fix are recorded above if they ever are.

---

## SHIPPED (SHADOW) 2026-08-09 - Candidate ranking now considers the value (L1)

The root cause from the pipeline trace. `_score_value` ranks competing values as
`tier_weight * (log1p(repetitions) + confidence)`, and `tier_weight` multiplies
every candidate of the same field equally - **so it cancels out of the ordering
and the ranking contains nothing about the value itself.** Most-repeated wins,
and on a dec page the most-repeated thing is the carrier's letterhead.

**A PARTITION, not another weight.** Candidates that pass their fact's own
registry validator rank ahead of ones that cannot possibly be valid; if none
qualify the list is returned untouched. It can only reorder - it can never drop
the last value, and `test_a_value_is_never_lost_when_every_candidate_is_invalid`
holds that line. No magic number to calibrate, which is why this beat the
weighted design I originally planned.

**Enforced on exactly 8 facts** (FEIN, the two contact emails, the two contact
phones, producer fax, and the two websites) - the same four hard validators
`pdf_service._shape_violation` uses. **Currency and date are deliberately
excluded**: C22's ~49,000-pair sweep established that an amount box legitimately
holds "Statutory" or "See schedule", and currency ordering belongs to C23's
composite-consistency logic, which this does not touch.

**SHADOW BY DEFAULT** (`SCORE_SHAPE_PARTITION=shadow`). The old winner still
ships; a disagreement logs at WARNING as `SHAPE_PARTITION field=... would_choose=
... instead_of=...`. This reorders candidates for every scalar fact in the
system, and that blast radius earns real-document evidence before it changes
output. **To enforce: `SCORE_SHAPE_PARTITION=on`.** Grep a real run for
`SHAPE_PARTITION` first and read the disagreements.

Demonstrated on the client's case - an EMC account number repeated three times in
a header versus the real FEIN stated once:

    shadow (default) -> 0482854          (unchanged, logged)
    enforced         -> 84-2210987

**The ENTITY half of L1 was deliberately not built here.** Penalising a candidate
that belongs to another party needs `carrier_name` / `producer_name` resolved
before the merge that resolves them, and `extraction_service` cannot import
`pdf_service` (the dependency runs the other way). It is already covered at three
other layers - extraction RULE 15, the `_FACT_ENTITY` stamping guard, and the
stamp-time shape demotion - so a fourth pass at merge time is low value for real
complexity.

Tests: `test_shape_partition_merge.py` (13). Suite **1516 passed / 2 failed**.

---

## VERIFIED 2026-08-09 - Yes/No is judged by MEANING, not by literal words

Asked directly: *"a dec page might not have specifically yes or no written, we
need to judge by the text."* Verified end to end rather than assumed. **It does,
on both sides, with one bounded and deliberate exception.**

**The compliance pass says so explicitly.** `_COMPLIANCE_SYSTEM_PROMPT` rule 5:
*"DETECT YES BY MEANING, not keywords. If the document describes the applicant
actually doing or having what the question asks, answer 'Y' **even if the word
'yes' never appears**"* - with a worked hazardous-waste example. Rule 6 does the
same for negatively-phrased questions.

**The gate agrees on the YES side.** Tested with quotes containing no "yes"
anywhere - all kept:
* "Scrap and used cutting fluid are stored on site and removed by a licensed
  hazardous-waste hauler"
* "The applicant operates a fleet of 3 owned vehicles"
* "Employee Dishonesty coverage limit $50,000"

**And on the NO side when the proof reads negatively** - "The applicant has no
prior cancellations", "Loss-free for the past five years" - both kept.

**The one exception, measured:** a "No" whose only proof is *positively phrased*
is blanked, because the gate requires a negation cue in the quote:
* "Every subcontractor is REQUIRED to provide a certificate of insurance"
  (answers *"allowed to work WITHOUT a certificate?"* = No)

**This affects 4 of 515 compliance questions across all 17 forms (0.8%)** -
swept, then hand-checked: a naive "negative phrasing" detector found 6, but two
were false ("with or **without** operators" is not a negation, and "will **never**
be left unattended" sits inside the procedure being asked about, not in the
question's polarity).

**Deliberately NOT fixed, and this is the reasoning to inherit:**
1. **Nothing is lost.** A blanked field becomes an ARQ question - *"Fields that
   are missing or empty become ARQ questions for the client"* - so those 4 go to
   the person who actually knows, rather than being guessed.
2. **The downside risk is the worst regression this codebase has had.** Loosening
   the negation requirement is how the false-"N" flood of 2026-07-15 happens
   again: ~20 of 22 questions answered "N" off borrowed sentences. Multiple
   sessions were spent fixing that.
3. **0.8% gained against reopening that is a bad trade.**

If this is ever revisited, scope it to the 4 questions by ID and require the
question's own polarity to be negative - never relax the cue globally.

---

## SHIPPED 2026-08-09 - The Yes-polarity hole (M1) - and the prompt edit NOT made

**M1 is closed.** The gate has always required a "No" to cite a quote that
actually denies something; a "Yes" only had to cite a quote that EXISTS. That
asymmetry is what let `Commercial Property - No Coverage` justify TICKING the
Commercial Property box. A denial is not proof of the opposite.

**The two sides are deliberately NOT symmetric, and that is the whole design.**
The "No" side keeps the broad `_NEGATION_CUE_RE`
(`no|not|none|never|without|free|clear|clean|...`) because its failure mode is a
blank. Using that same cue to reject a "Yes" would DELETE correct answers -
**measured, 7 of 10 realistic affirmative quotes trip it**:

    "Crime Coverage Policy No. BBC7263 - Employee Dishonesty $50,000"   <- "No."
    "The building is a free-standing masonry structure"                 <- "free"
    "Item No. 4 - Contractors Equipment Floater"                        <- "No."

"No" is the abbreviation for "number" and "free" is an ordinary adjective. So the
Yes side uses the NARROW `_COVERAGE_DENIAL_RE` ("no coverage" / "not covered" /
"coverage not provided") - **0 of 10 false rejections, all 4 real denials
caught** - shared with the declared-absent scan rather than copied.
`test_the_broad_negation_cue_would_have_been_unsafe_here` carries the
measurement, so anyone who tries to "tidy this into one helper" is told exactly
how many correct answers it would cost.

### The prompt edit I planned and did NOT make
Earlier analysis flagged Rule 3's examples for contradicting Rule 3 itself:

    - Policy_Status_BoundIndicator: "Yes" if the document is a bound policy, else "No"

two lines under *"If the document does not say one way or the other, OMIT the
field - do NOT default to 'No'."* Real contradiction, and I still did not touch
it. Reasons, in order:

1. **The gate already neutralises it.** An ungrounded "No" is dropped downstream
   because a "No" must cite a quote that denies something. The examples cannot
   produce a surviving false "No" on their own.
2. **Client #4 was the visible symptom, and it is fixed elsewhere** - by demoting
   contradictory single-choice ticks, which costs no fill.
3. **Editing them risks No-fill for no measured gain.** Every Yes/No change has
   to pay for itself in evidence, and this one could not.

If a client ever reports a false "No" that traces to these examples, rewrite them
to permit a *provable* No ("...; 'No' if the document states it is not bound;
omit if the document does not say") rather than deleting them - deletion would
stop the model answering No at all.

Tests: `test_yes_polarity_gate.py` (18). Suite **1503 passed / 2 failed**.
Prompt shape re-verified `PASS` (no prompt bytes changed).

---

## SHIPPED 2026-08-09 - Single-choice checkbox families (client #4)

**The client is partly wrong on this one, and the schemas prove it.** Report #4
says *"Both Issue Policy and Bound are populated ... Select the appropriate
status."* ACORD's own tooltips put those boxes in different families:

    Policy_Status_IssueIndicator - "the RESPONSE EXPECTED FROM THE COMPANY is an
                                    issued policy"
    Policy_Status_BoundIndicator - "Indicates the COVERAGE HAS BEEN BOUND"

One is a request, the other is a state of the coverage. **"Coverage is bound,
please issue the policy" is the ordinary broker workflow**, so making those two
exclusive would blank a legitimate tick - the exact coverage reduction that is
off-limits. There is a test asserting Issue + Bound is NOT flagged, so nobody
"fixes" it later on the strength of the client's wording.

What IS a contradiction is two members of the *expected response* family, since
only one response can be expected. The family is **derived from ACORD's own
phrase**, so the boundary is theirs rather than a guess: 3 boxes on ACORD 125,
3 on 130, 2 on 131, 1 on 133 (a group of one, so no conflict is possible).

**Nothing is blanked.** Which of two contradictory ticks is correct is genuinely
unknowable at this layer, and choosing would silently discard a right answer.
Both are demoted so the broker sees the conflict and decides.
`test_nothing_is_ever_blanked` is the load-bearing guarantee.

**Also worth knowing:** the client says "no bound date is provided", but
`Policy_Status_EffectiveDate_A`'s tooltip reads *"This date is used for policy
statuses of bound, change, and cancel"* - it is a SHARED box, and their form has
`07/15/2025 12:01 A.M.` in it. The date is present; the printed layout makes it
look like it belongs to the Cancel row. Nothing to fix.

Tests: `test_single_choice_groups.py` (10). Suite **1485 passed / 2 failed**.

---

## SHIPPED 2026-08-09 - Stamp-time shape checks + unanchored entity rows

**The real defect was the LABEL, not just the value.** `0482854` - an EMC account
number in the FEIN box - was painted **PINK**, which this codebase defines as
`ai_verified`: *"AI-filled AND confirmed present in the uploaded documents"*.
Asserting verified on an unverifiable value is worse than the value.

`fact_registry._is_fein` ("9 digits, with or without hyphen") has been correct
since long before the report and **never ran** - `pdf_service` imports
`FACT_REGISTRY` for its KEYS only. It is now wired to the form.

**Behaviour is DEMOTE, never blank** (the agreed rule): the value stays on the
form and its label drops to `low_confidence`, so the highlight layer paints it
orange "Verify". A shape failure **outranks every other label**, including
`filled` - which paints no highlight at all - and `ai_verified`. A test asserts
that ordering in the source, because getting it wrong silently reintroduces the
bug.

**Only four validators are enforced: FEIN, email, phone, URL.** C22's
~49,000-pair sweep established why: an amount box legitimately holds "Statutory",
"Included" or "See schedule", so a currency validator must never police a form
field. Adding a validator here is a one-line opt-in, never automatic.

**Measured: 40 fields of 5,852 are subject to a check, and ZERO false positives**
on appropriate values (email in email boxes, FEIN in FEIN boxes, and so on).
A first sweep reported 560 "failures" and was my own error - it put city names in
phone boxes. Cross-product sweeps must use field-appropriate values.

`Www.emcins.com` correctly passes the shape check: it IS a valid URL. What is
wrong with it is OWNERSHIP, which the entity guard owns. Keeping the two concerns
apart matters - a shape check has no basis to judge whose website it is.

### Unanchored entity rows (client #10)
*"A second LLC indicator, partial FEIN 84-, a member/manager range of 0-25,
another partial address record without a corresponding named insured. These are
not usable records."* A second named insured with a tax ID and no legal NAME is
not an entity - it is the repeating-slot prompt being asked to find an Nth value
that does not exist.

Scoped hard: rows B..N only (row A is the primary record and is never
questioned), only the verified `_FIELD_ENTITY_PREFIXES`, and only when the row
HAS a name box that is empty. **Measured: 27 rows across 9 forms.** Grouping by
raw name prefix instead would have swept in `CommercialStructure_*`, where a
building row legitimately has an address and no "name" - there is a test for
exactly that.

Tests: `test_stamp_time_shape_checks.py` (22). Suite **1475 passed / 2 failed** -
the same two pre-existing failures.

---

## SHIPPED 2026-08-09 - Coverage-flag guards + "Other" line de-duplication

### has_crime / has_cyber now require granted coverage (client #5)
Both were pure keyword-presence definitions - *"true if document **mentions**
cyber liability, data breach ... PCI, PHI"* - while six sibling flags had long
carried an explicit `Do NOT set true` guard. They now demand a **distinct
coverage part with a stated limit or premium**, the same bar `has_inland_marine`
and `has_umbrella` already use, and name the three situations that caused the
defect: an exclusion notice, a virus/hacking extension living inside another line
such as EDP, and a description of the applicant's data holdings.

**RULE 6's preamble was teaching the bug.** It told the model that *"we hold
customer health and card data" implies cyber*. That is an EXPOSURE, and
exposure-implies-coverage is exactly the conflation that ticked the box. The
preamble now states that a coverage flag describes what the policy GRANTS -
never an exposure, never a coverage named in order to exclude it - while keeping
the valuable half (judge by meaning, accept genuine paraphrases like "Network
Security and Privacy Liability").

**Two LOB-driving flags were deliberately NOT hardened, and the reasoning is
pinned in a test** (`test_general_liability_and_workers_comp_are_deliberately_left_alone`):
* **`has_general_liability`** - GL is on the overwhelming majority of commercial
  packages. A false positive is rare and cheap; a false negative unticks GL on a
  real GL policy and disturbs ACORD 126 recommendation. The asymmetry runs the
  wrong way.
* **`has_workers_comp`** - the client's actual case ("Workers Compensation - No
  Coverage") is already caught deterministically by
  `apply_declared_absent_downgrades`. A prompt guard buys nothing reported and
  risks dropping ACORD 130 for a genuine WC submission.

Neither was reported, and both fail toward MORE coverage. If a client ever
reports a false GL or WC tick, harden them then - with that report as evidence.

**Blast radius checked:** `has_crime` / `has_cyber` appear only in
`_COVERAGE_GOAL_LABELS` (display), not in any form-recommendation gate, so
hardening them cannot cost a recommended form.

### Guard 7 - an "Other line of business" that is not other (client #5)
*"The two 'Other' descriptions merely duplicate the standard Business Auto and
Umbrella selections."* The grid ends with blank Other rows for lines ACORD gives
no box to; two of them were used for lines already ticked two rows above.

Guard 7 blanks such a row **and its own Other tick** - but ONLY when the
enumerated box is actually ticked, so this removes a duplicate and never
information. Verified: "Professional Liability" survives (ACORD has no box for
it); "Commercial Auto" survives when the Auto box is NOT ticked (that row is then
the only place the line is declared); a vague "Liability" that fits three boxes is
left alone. Line matching reuses the same tooltip-derived vocabulary as the
premium boxes, via a new `_lob_indicator_index`.

Tests: `test_coverage_flag_definitions.py` (11), `test_coverage_lines.py` (20,
up from 15). Suite **1453 passed / 2 failed** - the same two pre-existing
failures. Prompt shape re-verified: `PASS - prefix is stable and cacheable`.

---

## SHIPPED 2026-08-09 - Declared-absent lines, Open Cargo, signatures, attestations

### Declared-absent coverage lines (client #5)
Coverage flags are keyword-presence booleans OR'd across every chunk, so a dec
page reading `PROPERTY - NO COVERAGE` set `has_property_coverage` TRUE forever.
`apply_declared_absent_downgrades` is the ONLY mechanism allowed to turn a
coverage flag off, and it is deliberately hard to trigger:
* the line name and the denial must sit within 40 characters **in the same row**;
* only unambiguous denials count. **"excluded" and "none" are deliberately NOT
  denial phrases** - the client's own GL policy carries a Cyber Incident
  exclusion, which does not remove the GL line, and "none" is everywhere on a
  dec page;
* a line present in `coverage_lines` is **never** downgraded - positive
  structured evidence always beats a text scan;
* **silence never downgrades anything.**

**A bug my own test caught before it shipped:** the 40-char window reached back
across a NEWLINE into the previous row, so `Umbrella $3,418` one line above
`Property - No Coverage` downgraded `has_umbrella` - the exact opposite of what
that page says. Splitting on column whitespace fixed that and broke the very
common two-column layout `PROPERTY      NO COVERAGE`. The rule that handles both
is **nearest line name wins**, one flag per denial.

Result on the client's decs: Property, Crime and Workers Comp off; Umbrella, GL,
Auto and Inland Marine untouched. **Cyber is NOT fixed by this** - their decs
never say "Cyber - No Coverage"; it is an exclusion notice, which this mechanism
correctly refuses to read as a denial. Cyber needs positive corroboration
(a premium or limit), which is the open half of client #5.

### Open Cargo (client #6)
`Policy_SectionAttached_OpenCargoIndicator` read `has_inland_marine`, so it
ticked on **every inland-marine submission we have ever produced**. Open Cargo is
OCEAN marine. Deleting the rule would not have fixed it - an unmapped field falls
through to gap fill, which ticks it anyway - so it now reads a new
`has_open_cargo` flag whose extraction definition explicitly rejects motor truck
cargo, transit extensions and installation floaters. False by default, so the box
resolves to an explicit "No".

### Signatures and attestations (client #19, #20) - the one justified blank
`map_facts_to_form` has always blanked signature fields. **The hole was in
`arq_service`.** Its two restamp paths write a client-confirmed value into any
schema field whose canonical key matches, and **neither consulted
`_is_nonfillable_field`**. `Producer_AuthorizedRepresentative_Signature_A`
resolves to a contact-name canonical, and *"Who is the main person we should
contact about this insurance application?"* is a **tier-1 question asked of every
client** - so answering it wrote that name into the producer's signature box and
labelled it `client_arq` (green, "client supplied") on a legal document. That is
almost certainly how `ERIN ROYAL` came to be signed.

`Policy_InformationPracticesNoticeIndicator` (ACORD 125 and 130) is now
non-fillable too: *"Copy of the Notice of Information Practices has been given to
the applicant"* is a statement that the AGENCY did something. No document can
evidence it and no model may assert it on the agency's behalf.

**This is the only place in this workstream where blank is the sole correct
answer.** No confidence colour makes an auto-signed application acceptable.
`test_glass_and_sign_is_not_mistaken_for_a_signature` keeps the block narrow -
"Sign" appears inside "GlassAndSign".

Tests: `test_declared_absent_coverage.py` (19), `test_never_ai_fill.py` (10).
Suite **1437 passed / 2 failed** - the same two pre-existing failures.

---

## SHIPPED 2026-08-09 - Question dependent blocks (client page 3, four items)

**The guard already existed and could not reach the fields.** Guard 5 blanks an
Explanation whose paired Question is not "Yes"; Guard 6 does the same for
non-adjacent dependents. Both were correct. Neither fired on ACORD 125's
Questions 8, 9 and 10 because `_question_explanation_pairs` requires STRICT
IMMEDIATE adjacency and ACORD puts an OccurrenceDate box in between:

```
CommercialPolicy_Question_KALCode_A                   <- the question
CommercialPolicy_JudgementOrLien_OccurrenceDate_A     <- +1, blocks pairing
CommercialPolicy_JudgementOrLienExplanation_A         <- +2, the explanation
CommercialPolicy_JudgementOrLien_ResolutionDescription_A
CommercialPolicy_JudgementOrLien_ResolutionDate_A
```

Missed by ONE position, so all three questions were permanently "unpaired" and
their boilerplate survived alongside an "N". The client reported every one:
*"Delete the fire-code occurrence date"*, *"Delete both bankruptcy boilerplate
explanations"*, *"Delete 'judgment or lien'"*.

**`_question_dependent_block` derives the whole block** - the run of consecutive
fields after a question that all share one name stem - and feeds it to both
guards as a third pairing fallback. **Requiring TWO OR MORE consecutive same-stem
fields is the entire safety argument:** single-field adjacency has documented
coincidences (this module already carries `_PAIRING_EXCLUDED` for two of them),
whereas several consecutive unrelated fields sharing one stem does not occur.

**Measured across all 17 schemas: exactly THREE questions qualify, all on ACORD
125, and all three are client-reported defects.** Perfect precision, zero noise.
`test_exactly_three_questions_qualify_across_all_seventeen_forms` pins that
number - if a schema change makes it jump, every new pair gets reviewed by hand.

**A wrong turn worth recording.** I first went after the "tooltip echo" - values
like `"The description of how the underwriting condition that caused t"` that are
our own field description read back. A **168,129-pair sweep** (40 realistic values
x every free-text field on all 17 forms) killed it: plain substring containment
produced **130-465 false positives**, blanking "Building" in a building-area box
and "Occurrence" in an occurrence-date box - legitimate answers that happen to be
words in their own tooltip. Two further corrections came out of that sweep:
the 63-char case is a TRUNCATED prefix so containment cannot match it at all, and
`"additional insured"` does not appear in its tooltip, so it was never a tooltip
echo - I had mis-attributed it. **Do not revive substring-vs-tooltip matching.**
The dependent-block fix reaches the same client complaints through structure
instead of string similarity.

Tests: `backend/tests/test_question_dependent_block.py` (12). Suite **1408 passed
/ 2 failed** - the same two pre-existing unrelated failures.

**Still open in this family:** `subsidiary`, `parent company` and
`additional insured` are single-word echoes of a nearby LABEL, not of their own
tooltip, and are not structurally separable from a legitimate short answer.
Guard 5 does not reach them because they sit in `RelationshipDescription` /
`InterestReasonDescription` boxes that have no Yes/No question at all. Needs a
different mechanism - do not reach for string similarity.

---

## SHIPPED 2026-08-09 - ACORD 25 certificate rows (found by sweep, NOT reported)

**The worst instance of the client's #3, on the document where it does the most
harm.** ACORD 25 is a certificate issued to a THIRD PARTY who relies on it, and
one `policy_number` scalar was filling the Automobile Liability, General
Liability **and Workers Compensation** rows; `effective_date` / `expiration_date`
filled three rows each. Telling a certificate holder that workers comp sits under
the auto policy number is a misstatement to someone acting on it.

`_resolve_current_policy_line_cell` reads `coverage_lines` per line. Attribution
is ordered and each step is deliberate:

1. the line names this value -> use it;
2. `coverage_lines` describes exactly ONE line and this is its column -> the
   package scalar unambiguously belongs to it, so use that (**this is why the fix
   costs no fill on single-line submissions**);
3. several lines but no value for this one -> blank; one policy number cannot be
   shown against three coverages;
4. **`coverage_lines` absent entirely -> `_SCHED_SKIP`, leaving the legacy scalar
   rules to answer exactly as before.** Sessions extracted before RULE 16 have no
   per-line data, and blanking them would be a pure regression with no
   correctness gain. The nine legacy rows in `_ACORD_FIELD_RULES` are therefore
   KEPT on purpose - the resolver runs first, so they only ever speak when there
   is no better answer.

**Umbrella reaches the Excess Liability row.** ACORD 25's column is
`Policy_ExcessLiability_*` while documents and ACORD 125 both say "Umbrella".
`_LINE_SYNONYMS` carries that one equivalence, and
`test_line_synonyms_are_corroborated_by_acord_tooltips` fails the build unless a
real shipped tooltip uses BOTH words for one coverage - ACORD's own
`ExcessUmbrella_*` tooltips read *"excess or umbrella liability policy"*. Same
discipline as `test_every_symbol_description_matches_acord_tooltip`. **Nobody can
add an equivalence ACORD's text does not state.**

**A test I wrote was wrong and the suite caught it.** The first standing guard
banned the per-line scalar rules outright - which contradicts rule 4 above and
would have blanked certificate policy numbers on every pre-RULE-16 session. It
now asserts the real invariant instead: with per-line data present, the package
scalar may appear ONLY in the column the document attributes it to.

Tests: `backend/tests/test_current_policy_line_columns.py` (15). Suite **1396
passed / 2 failed** - the same two pre-existing unrelated failures.

---

### CROSS-FORM SWEEP 2026-08-09 - the same defect on 8 more forms, unreported

Ran the one-fact-to-many-parallel-columns check across every rule x every real
schema field on all 17 forms. **The client has only reported the ACORD 125
instance. These are the same defect and will be reported eventually.** Ranked by
how much damage a wrong value does.

| Sev | Form(s) | Field | One fact | Columns it fills |
|---|---|---|---|---|
| ~~HIGHEST~~ **FIXED** | **25** | `Policy_PolicyNumberIdentifier_A` | `policy_number` | AutomobileLiability, GeneralLiability, **WorkersCompensationAndEmployersLiability** |
| ~~HIGH~~ **FIXED** | 25 | `Policy_{Effective,Expiration}Date_A` | `{effective,expiration}_date` | AutomobileLiability, ExcessLiability, GeneralLiability |
| HIGH | 131, 137_CA/CO, 25 | `Vehicle_PerAccidentLimitAmount_*` | `auto_liability_limit` | BodilyInjury, PropertyDamage |
| MED | 138_CA/CO, 160 | `GarageAndDealers_LimitAmount_*` | `garagekeeper_liability_limit`, `auto_dealers_inventory_value` | GarageKeepersCollision/Comprehensive, PhysicalDamageCollision/Comprehensive |
| MED | 126 | `GeneralLiability_DeductibleAmount_A` | `gl_deductible` | BodilyInjury, PropertyDamage |
| MED | 138_CA/CO | `Vehicle_PerAccidentLimitAmount_A` | `garage_liability_limit` | LiabilityAutoOnly, LiabilityOtherThanAutoOnly |

**ACORD 25 is the one to fix first, and it is worse than what the client
reported.** A 125 is an application the broker reviews; **a 25 is a certificate
issued TO A THIRD PARTY who relies on it.** Stamping the auto policy number on
the Workers Comp row tells a certificate holder that WC coverage exists under a
policy number that is not the WC policy. This is precisely client #3 ("Do not
present the Auto policy number as though it governs every selected line") landing
on the document where it does the most harm.

`coverage_lines` (shipped above) already carries `policy_number`, `carrier`,
`naic`, `effective_date` and `expiration_date` per line - it is the fact these
columns need. Reuse `_prior_coverage_column`-style attribution; do NOT write a
second matcher.

**Not defects, checked and dismissed:**
- `Producer_FullName_A <- producer_contact_name` across `AuthorizedRepresentative`
  / `ContactPerson` is a harvest artefact of collapsing two genuinely different
  fields that legitimately hold the same person's name.

**Judgement call on the BI/PD pairs:** a split-limit auto policy (100/300/50) has
genuinely different bodily-injury and property-damage figures, so filling both
from one `auto_liability_limit` is wrong. But that fact usually holds a COMBINED
single limit, which belongs in the CSL box and in neither of these. Both readings
say the current mapping is wrong; fixing it needs split-limit facts, which
CLAUDE.md records as deliberately not writable today. **Do not "fix" this by
picking one of the two boxes.**

---

## SHIPPED 2026-08-09 - The prior-coverage grid (client #17)

Same defect as the contact bug, on the LINE axis instead of the ENTITY axis:
**4 scalars sprayed into 16 boxes.** `prior_policy_number` alone filled the
General Liability, Automobile, Property AND Other columns; `prior_carrier`,
`prior_effective_date` and `prior_expiration_date` did the same. The client saw
it verbatim - *"BBC7263 under GL, Property and Other."* A scalar cannot say WHICH
line a policy covered, which is the entire purpose of that grid.

`prior_coverage_by_line` had the right shape all along and had **never stamped
anything**: 4 of its 5 `_SCHEDULE_REGISTRY` bindings name fields that exist on no
form (`PriorCoverage_InsuranceCarrier`, `_TypeOfInsurance`, `_EffectiveDate`,
`_Premium` - 0 real matches across all 17 schemas). Those entries are annotated
as dead rather than deleted, so nobody "restores" them.

**`_resolve_prior_coverage_cell` now owns every cell.** It runs FIRST in
`_deterministic_map` - ahead of the row-variant guard, which would otherwise
divert rows B and C to gap fill before the resolver could see them - and returns
None for an owned-but-empty cell so nothing can fall back to a scalar. The 16
rules are deleted with a comment telling the next person not to re-add them.

**Rows are policy TERMS, not per-column sequence.** There is one PolicyYear box
per row shared across all four columns, so row A must mean the same term
everywhere; otherwise row A would claim 2024 for GL and 2023 for Auto under a
single year label. Rows key off the year when every entry states one, and fall
back to per-column document order with the year labels left EMPTY rather than
asserting a term the document never gave.

**It fills MORE than before.** The carrier and premium columns had no fact behind
them at all - which is why the client reported them missing - and the "Other"
column's `LineOfBusinessCode` box now names the line it holds ("Add line-of-
business descriptions beside legitimate companion policies").

**Column attribution needed stem matching**, because ACORD uses different
vocabularies in different sections of the SAME form: the prior-coverage column is
`Automobile` while the lines-of-business grid and every real document say "Auto"
or "Vehicle". `_stem_match` treats one word as a prefix of the other at 4+ chars,
and callers require EVERY token to match - so "Liquor Liability" does NOT fall
into the "General Liability" column on the shared word alone. Verified against 12
line spellings.

**ACORD 130 and 131 are untouched.** They have a plain prior-coverage list with no
line columns (`PriorCoverage_PolicyNumberIdentifier_A`); the resolver's regex
requires two underscores after the prefix and cannot match them, so their scalar
mapping still works. Asserted by test.

**Never feed this grid from `coverage_lines`** - that fact is the CURRENT policy,
and presenting it as coverage history is the misstatement being fixed.

Tests: `backend/tests/test_prior_coverage_grid.py` (27), including a standing
guard that fails the build if a per-line prior-coverage row is re-added to
`_ACORD_FIELD_RULES`. Suite **1381 passed / 2 failed** - the same two pre-existing
unrelated failures, zero regressions.

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
| **ROLE** | Is this the value for *this* question, or a different one? | Policy effective date stamped as *application date* AND *business start date*; GL premium stamped as *deposit*; agent number as *state licence*; phone as *fax* and as *email* |
| **AUTHORSHIP** | Is this a field a machine may fill at all? | `ERIN ROYAL` auto-populated into the **producer signature** box |

**Predicting the next report:** take any field, ask which of the six qualifiers is
checked before it stamps. If the answer is "none", that field is already broken or one
document away from it.

**ROLE and AUTHORSHIP were added 2026-08-09** after reading the client's full report
(`Acord125-test-result.txt`) rather than only the screenshots. See the acceptance list
below - the reported count went from 11 to 22, and every new one lands in this same
table.

---

## PIPELINE TRACE - where the damage actually happens

**Before the user selects forms**
1. OCR -> `clean_text` (C24: three destructive filters removed, dedup now default OFF)
2. `_chunk_by_sections` -> N chunks. **Sound.** Never drops a section, carries
   `_EXTRACTION_OVERLAP_CHARS` between chunks, `_verify_coverage` raises on any gap.
3. One LLM call per chunk -> `{facts, flags}` per chunk
4. **`_merge_list_fields` -> `_score_value` picks ONE winner per scalar fact** <- L1
5. `merge_facts` across documents; **flags OR'd** - one chunk saying true wins forever

**After the user selects forms**
6. `process_single_form`: **`facts_with_flags = {**facts, **flags}`** <- L2
7. Pass 1 `_ACORD_FIELD_RULES` + `_derive_indicator`; **row guard sends every
   `_B`.. `_N` slot to gap fill** <- L4
8. Pass 1.5 alias stamping (bridge is only 24 entries)
9. `compute_form_gaps` -> unmatched fields
10. `combined_gap_fill`: system skeleton + form label + **facts block minus 5 PII keys**
    <- L3 + raw text chunk + field batch
11. Evidence gate - and a "Yes" only needs a quote that *exists*

### L1 - The merge ranks candidate values by POPULARITY, not correctness
[`extraction_service.py:2233`](backend/services/extraction_service.py#L2233)
```
tier_weight = _TIER_WEIGHTS[_get_field_tier(field)]      # depends on FIELD only
return tier_weight * (log1p(freq) + conf_score)
```
`tier_weight` is identical for every candidate of the same field, so **it cancels out of
the ranking entirely**. The score reduces to `repetitions + confidence`. **Nothing about
the value itself is scored** - not its shape, not its source, not whose it is.

The winner is whatever appears in the most chunks. On a declarations page the thing that
repeats on every single page is the **carrier's letterhead and URL**. The applicant's
website appears once, or never. `Www.emcins.com` didn't come from a confused model - it
won on frequency, exactly as designed.

Quantified: one extra repetition is worth `log1p(2)-log1p(1) = 0.405`. The whole gap
between `ai_high` (0.85) and `ai_low` (0.50) is **0.35**. **A low-confidence value seen
twice beats a high-confidence value seen once.**

### L2 - Extraction's guesses are relabelled "verified" at the boundary
[`form_service.py:1837`](backend/services/form_service.py#L1837) merges flags into facts.
That dict is then sent to the model under the header
`=== EXTRACTED FACTS (PRIMARY SOURCE - already verified by document analyzer) ===`, and
the system prompt ([`pdf_service.py:3382`](backend/services/pdf_service.py#L3382)) says:

> *"Boolean facts (has_general_liability, is_contractor, has_auto_coverage, etc.)
> **directly answer Yes/No checkbox fields**."*

So `has_crime=true` - derived from the word "crime" inside `Crime and Fidelity - No
Coverage` - reaches the model labelled **verified**, with an instruction to tick the box.
**The model did not hallucinate. It obeyed.** This is why the flags contaminate the
1,452 LLM-answered boxes as well as the 89 deterministic ones.

### L3 - We hide five facts from the model, then ask it for them
`_PII_EXCLUDE_KEYS` ([`pdf_service.py:105`](backend/services/pdf_service.py#L105)) strips
`fein`, `contact_phone`, `contact_email`, `mailing_address`, `physical_address` from the
facts block. Justified in-comment as *"decomposed by Pass 1"* - **true for row `_A`
only.** The row guard (L4) deliberately routes every `_B`/`_C`/`_D` slot to gap fill, so
for exactly those slots Pass 1 does *not* cover it, the real value is withheld, and the
model is asked to produce one anyway. It scavenges the raw text and returns `84-`.

**And the redaction protects nothing.** The full document text - containing that same
FEIN - is sent to the same model in the same request as the `RAW DOCUMENT TEXT` block.
We get zero privacy benefit and pay for it with a fabricated tax ID.

### L4 - The row guard's own comment states an assumption nothing enforces
[`pdf_service.py:2036`](backend/services/pdf_service.py#L2036):
> *"...-> gap-fill LLM fills them **only if a second entity exists in the doc**."*

Nothing enforces that. Gap fill is a completion engine: hand it a labelled empty box and
it finds something. Confirmed by grep - **no orphan-row check exists anywhere in the
services tree.**

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

## THE CLIENT'S OWN DIAGNOSIS - READ IT

`Acord125-test-result.txt` (repo root) is the client's **full** ACORD 125 report: **22
numbered issues**, not the 11 visible in the screenshots. It ends with their own list of
"product-level fixes for Primble", and it is worth quoting because they arrived at this
file's root cause independently:

> 1. Never use an account number as a FEIN. *(SHAPE + OWNERSHIP)*
> 2. Never place producer or carrier contact information into applicant fields. *(OWNERSHIP)*
> 3. Never convert policy boilerplate into applicant-history answers. *(GRANT)*
> 4. Never convert limits or exposures into revenue, employee counts or building area. *(ROLE)*
> 5. Never auto-populate a signature. *(AUTHORSHIP)*
> 6. **Require field-level provenance: every populated value should show the source page,
>    source label and confidence.**

**Rule 6 is the whole thesis.** The client is asking for exactly the context this pipeline
throws away. We already ship *confidence* (the highlight colours); we ship **no**
provenance. Any fix here should carry source information forward rather than discard it -
that is what makes the other five rules enforceable instead of aspirational.

### Acceptance list - all 22, mapped to a qualifier
Use this as the regression corpus. `#` matches the client's numbering.

| # | Issue | Qualifier | Status |
|---|---|---|---|
| 1 | Producer email = `ERIN ROYAL`; fax copied from producer phone; no producer street address | SHAPE, ROLE | **PARTLY SHIPPED** - fax now needs its own labelled fact; `_is_email` exists. Street address still unsourced |
| 2 | Application completion date = policy effective date | ROLE |
| 3 | One carrier / product / policy number presented as governing all 4 lines (package is multi-carrier); Program Code holds a carrier form string | OWNERSHIP, **cardinality** |
| 4 | Both `Issue Policy` and `Bound` ticked, no bound date | **mutually exclusive group** |
| 5 | Commercial Property / Crime / Cyber ticked; `Other` rows duplicate Business Auto + Umbrella | GRANT |
| 6 | Driver Information Schedule + Open Cargo ticked; Contractors Supplement missing though ACORD 186 is in the package | GRANT, package-claim |
| 7 | Deposit `$3,954` is actually the whole GL premium; DIRECT BILL used as plan + payment plan + method at once | ROLE |
| 8 | FEIN `0482854` is the EMC **account number** | SHAPE, OWNERSHIP |
| 9 | Insured phone = producer's phone; insured website = carrier's website | OWNERSHIP | **SHIPPED** 2026-08-09 |
| 10 | Other Named Insured row: LLC ticked, partial FEIN `84-`, members `0-25`, orphan address, **no name** | ROW INTEGRITY |
| 11 | Applicant contact block holds producer/carrier contacts; **phone numbers inside email fields** | OWNERSHIP, SHAPE | **PARTLY SHIPPED** - ownership done; email-shape rejection lands with W4 |
| 12 | `# D13` duplicated in Address Line One and Line Two | **intra-group duplication** |
| 13 | Tenant ticked; policy establishes no ownership interest | GRANT |
| 14 | 0 FT / 0 PT employees, $50,000 revenue, 220 sq ft, 0% + 0% work split - none in the document | **ungrounded value** | **PARTLY SHIPPED** - the FT/PT double-stamp is fixed; ungrounded numerics still open |
| 15 | Business start date = policy effective date | ROLE | **SHIPPED** 2026-08-09 |
| 16 | Operations = `COMMERCIAL GENERAL CONTRA` (truncated carrier shorthand) | **truncation** |
| - | EMC Insurance Companies stamped as an additional insured, with address/reason/phone | OWNERSHIP |
| - | Parent company / 50% ownership / subsidiary; cancellation narrative; fire-code date; two bankruptcy explanations; judgment or lien - all from **policy boilerplate** | GRANT |
| 17 | Prior-carrier grid filled with the **current** policy numbers, same number in GL + Property + Other columns; no carriers, no premiums; prior term = current term | OWNERSHIP, cardinality |
| 18 | 3 years / $0 losses with "Check if none" unticked and no loss runs | ungrounded value |
| 19 | Privacy-notice box ticked without an actual agency action | AUTHORSHIP |
| 20 | **Producer signature auto-populated with `ERIN ROYAL`** | AUTHORSHIP |
| 21 | State Producer Licence = `W6258-0001`, an **agent number** per the decs | ROLE, SHAPE |
| 22 | Applicant signature/date incomplete | (expected - not a defect) |

**Confirmed correct - must not regress** (the client's own list): ACORD 125 edition
2025/03, `Orbin Contracting LLC`, mailing address, LLC entity type, term
07/15/2025-07/15/2026, Direct Bill, `$10,663` total package premium, Contractor as nature
of business, the Business Auto / CGL / Inland Marine / Umbrella selections, and the
Vehicle Schedule + EDP attachments.

**Two new mechanisms this exposes**, both generic and both to be handled the same way as
the rest (stamp + relabel, never blank):
- **Mutually exclusive checkbox groups** (#4 Issue Policy vs Bound; also Owner vs Tenant,
  Occurrence vs Claims-Made, New vs Renewal). ACORD has these on every form. Nothing today
  checks that at most one member of a group is ticked.
- **Never-AI-fill fields** (#19, #20). A signature or an agency attestation is an *action*,
  not a value found in a document. These must be excluded from every fill path outright -
  the only case in this whole file where the right answer is genuinely "leave it empty".

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
- **No text is lost in chunking.** `_chunk_by_sections` never drops a section (the chunk
  cap is advisory), carries overlap between chunks, and `_verify_coverage` raises on any
  gap. The full raw text of **all** documents reaches gap fill, and
  `GAP_FILL_FULL_RESCAN=auto` re-reads every chunk when the document split (C25).
  **The loss is not in the text. It is in the value selection (L1) and the five
  deliberately withheld facts (L3).**

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


NOTE :This is for all the forms not just ACORD 125, we need to think about all the forms and relevant issues that can be pointed out in future. 