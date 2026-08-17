# 17 Aug 2026 - False Conflicts & Insurance Context (client items 1 and 2)

Client direction, verbatim: **"Primble should escalate judgment, not formatting."**
Second directive: **"an unresolved fact remains unresolved downstream rather than
another part of Primble independently selecting a value."**

This file is the working record for that arc: every issue found, the decision
taken, and why. Round 13 and earlier live in `FIX_TRACKING_2026-08-15.md`; this
is Round 14 and continues the same discipline (measure before deciding, positive
evidence only, right-or-blank).

---

## How the issues were found

Not by reading code - by running it. Five probe documents were generated
(`backend/scripts/generate_conflict_probe_pdfs.py`) and uploaded in four
combinations. The session facts were then inspected offline with a new tool
(`backend/scripts/dump_session_facts.py`), which prints merged facts, flags,
per-document facts, the dec index, and a replay of every Data Consistency row
with its inputs and which value was suggested.

**Three of four predictions made from code-reading alone were WRONG.** That is
the standing lesson of this round and the reason both scripts are committed:
this area cannot be reasoned about, only measured.

Probe sessions (kept for regression):

| Run | Session | Upload | Rows produced |
|-----|---------|--------|---------------|
| A | `fd1dcf66` | PROBE1 alone (self-contradicting) | 1 (4 real contradictions MISSED) |
| B | `14ee33d1` | PROBE2 + PROBE3 (dec + certificate) | 12 (1 real, 11 false) |
| C | `2cf0e39e` | PROBE2 + PROBE4 (two policies, two terms) | 4 false + **HARD STOP, score 60** |
| D | `3bf00996` | PROBE2 + PROBE5 (dec + narrative) | 3 false |

A sixth measurement - an equivalence sweep of 42 realistic "same fact written
two ways" pairs against the live comparator - returned **24 false conflicts**
across **8 shape families**. The client had reported 2 of those families.

---

## The root cause

Facts are stored **flat, untyped, and without their policy context**. Extraction
captures the context perfectly (`dec_page_entries` carries label + value +
policy_number + line_of_business, verified against the document), and then the
flattening step throws it away, keeping one value per fact name.

Three separate places then ask *"is this a conflict?"* -
`underwriting_consistency.assess_underwriting_consistency`,
`sqs_service.check_doc_consistency`, and
`extraction_service.detect_source_conflicts` - and **none of them reads the
index that has the answer.** Each carries its own private, hand-maintained list
of fields it understands (16, ~9, and 0 respectively) against 173 real facts.

Out of that one weakness grow **four distinct missing abilities**, and each
needs its own fix:

1. Cannot tell "same value written differently" from "genuinely different value"
2. Cannot tell "this value does not belong in this field"
3. Cannot tell "these two values belong to different policies"
4. No single gate that every surface consults for "this fact is unresolved"

**Evidence for the flattening claim** (Run A, verbatim from the session):

```
INDEX (kept everything)                         FLAT FACTS (what the panel reads)
General Aggregate Limit  = $2,000,000           gl_aggregate   = $2,000,000
General Aggregate Limit  = $3,000,000                      (the $3,000,000 deleted)
Umbrella Each Occurrence = $3,000,000           umbrella_limit = $1,000,000
Umbrella Each Occurrence = $1,000,000                      (the $3,000,000 deleted)
Annual Gross Sales       = $1,500,000           total_revenue  = $2,400,000
Annual Gross Sales       = $2,400,000                      (the $1,500,000 deleted)
Number of Employees      = 47                   num_employees  = 62
Number of Employees      = 62                              (the 47 deleted)
Named Insured  = ORBIN CONTRACTING LLC          applicant_name = ORBIN CONTRACTING LLC
Named Insured  = ORBIN CONTRACTING INC                     (the INC deleted)
```

Ten values became five. The losers ARE recorded (`_merge_rejected`,
extraction_service:3484), exactly ONE function reads them (:6714, umbrella only),
and then they are deleted (:6717). The one row Run A did produce came from a
separate raw-text scanner that happened to match the label "Annual Gross Sales".

**Why the winner is arbitrary:** the merge scores candidates as
`authority + log(frequency) + confidence`. In Run A every candidate appeared
once at the same confidence, so every score tied - and the winners were the
first value twice and the second value three times. No pattern.

---

## Issue register

### A. Client-reported (8)

| # | Issue | Fix |
|---|-------|-----|
| C1 | `$2,000,000` vs `$2,000,000 General Aggregate` escalated (x3 limits) | Fix 1 |
| C2 | Full street address vs `Denver, Colorado` escalated | Fix 1 |
| C3 | Two Additional Remarks paragraphs treated as competing values | Fix 1 |
| C4 | Facts inside a paragraph not routed to their own fields | **DEFERRED - scoped, not shipped** |
| C5 | False conflicts dragging Exposure Consistency / SQS down | Fix 1 (consequence) |
| C6 | `GL Form Type: BUSINESS AUTO COVERAGE FORM` vs `Commercial General Liability` | Fix 5 |
| C7 | Three policy numbers on a three-policy account escalated | Fix 1 (context) |
| C8 | Panel says umbrella unresolved; Form Recommendation prints `$3,000,000` | Fix 4 |

### B. Found by the probe runs (15)

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| F1 | Two policies with different terms -> **HARD STOP, SQS capped at 60** | Critical | Fix 3 |
| F2 | "Suggested" badge picks the LONGEST string - recommends `BUSINESS AUTO COVERAGE FORM` and an exclusions clause | Critical | Fix 2 |
| F3 | Package premium `$10,663` vs auto line premium `$2,991` escalated | High | Fix 1 |
| F4 | Composite limits string: 5 limits vs 4 (a subset) escalated | Medium | Fix 1 |
| F5 | Lines of business `GL, Auto, Umbrella` vs `Business Auto` (subset) escalated | Medium | Fix 1 |
| F6 | `Commercial roofing contractor` vs `Contracting` escalated | Low | Fix 1 (descriptive) |
| F7 | Same-document contradictions silently deleted at merge | High | Fix 6 |
| F8 | Single-doc detection covers only 9 of 173 fields, by label luck | High | Fix 6 |
| F9 | **Blank becomes "No"** - 44 flags, none may say unknown | Critical | Fix 7 |
| F10 | The PDF's title line stored as Additional Remarks | Medium | **DEFERRED** |
| F11 | A date from a remarks sentence became the umbrella's effective date | High | **DEFERRED** (Fix 4 stops it publishing) |
| F12 | Same conflict rendered 4x across sections | Low | Fix 8 |
| F13 | Dates and paragraphs filed under "Financial figure conflicts" | Low | Fix 8 |
| F14 | "documents disagree" on a SINGLE-document upload | Low | Fix 8 |
| F15 | Crime-coverage warning fires on a roofer with no cash exposure | Low | **DEFERRED - unrelated rule** |

### C. Found by the equivalence sweep - families the client has not hit yet (6)

| # | Family | Example | Fix |
|---|--------|---------|-----|
| S1 | Phone / email / website format | `303-996-7800` vs `3039967800`; `orbin.com` vs `www.orbin.com` | Fix 1 |
| S2 | Code with its description | `91580` vs `91580 Contractors - Executive Supervisors` | Fix 1 |
| S3 | Yes/No written differently | `Yes` vs `Y` vs `true` | Fix 1 |
| S4 | Number with a unit | `50` vs `50 miles`; `47` vs `47 full-time` | Fix 1 |
| S5 | Abbreviation vs full word | `CO` vs `Colorado`; `RCV` vs `Replacement Cost` | Fix 1 |
| S6 | Same identifier printed differently | `6C7-40-02---26` vs `6 C 7 - 4 0 - 0 2---26` | Fix 1 |

**29 issues. 24 of 42 sweep pairs fail today.**

---

## Design decision: why a FILTER, not a new comparator

The equivalence logic runs **after** today's grouping, as a merge pass over the
groups it produced - never as a replacement for `normalize_value`.

Three properties follow structurally, not by care:

1. **It can only REMOVE a conflict.** There is no code path that splits a group.
   Creating new noise is impossible, so the change is one-directional.
2. **Failure is a no-op.** Wrapped; any exception leaves today's behaviour.
3. **It never changes a stamped value.** The merge still decides what goes on the
   form. This decides only what we ASK about.

Rejected alternative (recorded so nobody rebuilds it): changing
`normalize_value` itself. It is shared with `field_qa`, the merge and document
clustering, whose semantics are deliberately different - Round 10 fix 46 exists
precisely because one coarse normalizer served consumers that needed different
answers.

## Design decision: the conflict SOURCE for intra-document differences

Measured before choosing. Grouping the dec index by heading and asking about
every multi-value heading was tried on two real Orbin packages and produced
**11 "differences" per package of which ~0 were real** - they were different
cells of one table row (`'02 $ 5,000 EACH INSURED . 35.00'` vs `'35.00'`),
different line items under one section heading, and OCR letter-spacing of the
same policy number.

So heading-grouping is NOT the source. The merge's own `_merge_rejected` record
is: it is already resolved to "these are rival candidates for ONE fact key",
which is exactly the question a picker answers.

**Open measurement (Fix 6 step one): stop deleting `_merge_rejected`, run one
real Orbin upload, and count how many survive the equivalence filter.** No UI
change until that number exists.

---

## Fix log

Each fix records: what changed, why, what could break, and the guard.
Baseline before any change: **3102 passed / 2 failed** - the two documented
pre-existing failures (`test_arq_acord125_missing_only`, `test_normalization`).

### Fix 1 - `services/fact_equivalence.py` (NEW): one equivalence comparator  [DONE]

`same_fact(field, a, b) -> SAME | DIFFERENT | INCOMPARABLE`, plus
`equivalent_index()` which callers run as a FILTER over the groups their
existing logic already produced.

**Why a filter and not a new comparator.** Three properties follow structurally
rather than by care: it can only ever REMOVE a conflict (no code path splits a
group, so new noise is impossible); a failure is a no-op (wrapped, fail-open);
and it never changes a stamped value (the merge still decides what reaches the
form - this decides only what we ASK a human about).

**REJECTED, recorded so nobody rebuilds it:** changing
`normalization.normalize_value` itself. It is shared with `field_qa`, the merge
and document clustering, whose equivalence semantics are deliberately different
- Round 10 fix 46 exists precisely because one coarse normalizer was serving
consumers that needed different answers.

Nine rules, every one driven by a type the codebase ALREADY declares
(`FACT_REGISTRY`'s validator, `normalization`'s identity tables): money compares
by amount; count/percent numerically; phone by digits; web/email canonically;
dates as dates whatever the key is called; yes/no by a synonym set; a code by
its code (word boundary required); an identifier ignoring spacing; text by
whole-token containment; prose is INCOMPARABLE.

Wired into `underwriting_consistency.assess_underwriting_consistency` via
`_merge_equivalent_value_groups` (sources are carried into the surviving group,
so attribution is never lost - only the question disappears) and into
`sqs_service.check_doc_consistency` via `_still_differs`, so the two surfaces
can never disagree about whether something is a conflict.

**Measured:** the 42-pair sweep went 18/42 -> 41/42 SAME with the control set of
8 genuine differences untouched. Client's four literal examples: all SAME.

### Fix 2 - Honest ranking; no "Suggested" badge on a tie  [DONE]

`_value_completeness` scored EVERY auto-discovered field by raw string length,
so the longest string won - and the longest string is the one carrying an
annotation or a mis-extraction. Probe run B badged **"BUSINESS AUTO COVERAGE
FORM"** over "Occurrence", **"$2,000,000 (any one premises)"** over
"$2,000,000", and an **exclusions clause** over the real operations
description. A false conflict costs a click; a wrong recommendation puts a wrong
value on a legal form.

Now: address/FEIN keep their precise structural scoring (and it is DERIVED from
the value's kind, so an auto-discovered `premises_address` finally gets it too);
length survives only for genuinely descriptive text; typed values score 0.0 and
ranking falls through to DOCUMENT AGREEMENT, which is real evidence.
`_suggest_for_field` now returns None at "low" confidence - a genuine tie gets
no badge and no pre-select. Precedent: C23, where frequency ranking once picked
an UMBRELLA limit as the GL limit.

### Fix 3 - Policy context on the identity hard stops  [DONE]

Probe run C (PROBE2 package dec + PROBE4 auto dec, both correct, each with its
OWN term) fired TWO hard stops and capped an ordinary two-policy account at 60.

`check_doc_consistency` now builds a `PackageContext` (once, at the top of the
function - the first cut built it lower down, so the identity checks called it
before it existed and the fail-open guard silently swallowed the error; a fix
that looks applied and is not is worse than no fix). Then:

* `_dates_owned_separately` - PROVEN different owners -> no issue at all.
* Two or more contracts evidenced -> the date hard stop DOWNGRADES to a warning
  with an explanatory note. Not silenced: the producer still sees it and the
  picker still resolves it. A single-contract package is untouched, and so is a
  package with no dec index.
* Lines of business now compare by CANONICAL line and a SUBSET is not a
  disagreement ("Commercial Auto" vs "Business Auto" is one line; a certificate
  naming fewer lines than the package dec is not a conflict).

### Fix 4 - One "unresolved" gate  [DONE]

`underwriting_consistency.is_withheld(facts, key)`. The withhold list has worked
since 2026-08-15 but only two modules ever read it, both on the STAMPING side -
so the form correctly shipped a blank umbrella limit while the recommendation
panel printed "$3,000,000" on ACORD 25 AND 131. Reproduced in three lines.

`form_service._build_trigger_facts` now consults it. **Scope confirmed with the
owner before landing: this does NOT change which forms are recommended, their
tier or their order.** It only drops the evidence phrase appended to a
recommendation's reason, and only for a fact that is currently unresolved;
verified that a form with another good fact falls through to that fact, and a
form with none falls back to its generic message (an existing, supported path).

### Fix 5 - A foreign-line value is not a candidate  [DONE]

`fact_line()` + `names_a_foreign_line()`. Client: *"GL Form Type: BUSINESS AUTO
COVERAGE FORM vs Commercial General Liability - those are different lines of
business, not competing GL values."* A fact's line is derived by intersecting
its own `FACT_REGISTRY["forms"]` with `pdf_service._SECTION_FORM_LINE_PHRASES`;
ACORD 125/101 are deliberately absent from that table, so package-level facts
correctly get no line. `_drop_foreign_line_values` never empties a field.

**REGRESSION CAUGHT BY THE SUITE, and it is the important entry here.** The
first cut required only SOME of a fact's forms to be a line section, which gave
`carrier_name` (forms 125 + 126) the General Liability line - and then read the
word "Property" inside **"EMC Property & Casualty Company"** as the Property
line and DELETED a real carrier, killing Round 10's two-carrier conflict.
`test_the_two_real_carriers_finally_conflict` failed, exactly as written to.
Two independent guards now: EVERY form must be a line section, AND a
name/address/narrative value is never tested for a line at all. One guard would
have sufficed; two, because deleting a real carrier is unrecoverable for the
user and the failure is silent.

### Fix 6 - Facts are never replaced wholesale  [DONE - found during testing,
### unrelated to items 1 and 2, and more damaging than either]

**Owner's live report:** two forms at SQS 68, package 67; answered "no known
losses" - a POSITIVE answer - and both forms fell to 23, package to 37.

Session `f50825ae` held **ONE** fact (`loss_history_years`) where a healthy
session of the same package holds 71. The facts had been destroyed; the scorer
faithfully scored an empty set. `d034dbbe` was found mid-failure with
`facts = None`.

Two pieces, each harmless alone:
1. `_decrypt_facts` returns `facts = None` when the blob cannot be decrypted -
   deliberate, so a key mismatch shows an empty session instead of crashing.
2. `upd_processing_session`'s facts merge is additive ONLY when the existing
   value is a dict. `None` is not a dict -> wholesale-replace branch -> the
   entire fact set becomes whatever that write carried.

And `_encrypt_facts` short-circuits on a falsy value, so the substituted `None`
was written back as `null` - destroying recoverable ciphertext on the next write
of ANY kind, including writes that never mentioned facts.

Fixed in `repositories/session_repository.py`: the ciphertext is PRESERVED under
a private marker and written back byte-for-byte; the merge REFUSES to replace
facts whenever there is anything to lose (undecryptable blob, or an unparseable
non-dict) while still accepting a genuinely new session's first write; the
marker is stripped on the read path so raw ciphertext can never reach an API
response. Readers still see `facts = None` - that behaviour is unchanged.

**NOT diagnosed:** WHY that session's blob became undecryptable (key change,
double-encrypt, partial write). The mechanism above turns any such hiccup into
permanent silent total data loss, so it is worth fixing whatever the cause -
but the cause is still open.

### Verified NOT the cause: the dec-index purge

The owner asked whether deleting `dec_page_entries` after generation caused the
collapse. Measured, three sessions, A/B with the index removed:

```
34efbef4  tier2 WITH index=22   WITHOUT=22   loss=0
7e95e3ae  tier2 WITH index=11   WITHOUT=11   loss=0
c200aff1  tier2 WITH index=22   WITHOUT=22   loss=0
```

The index is not a scoring input and never was - it is a RETRIEVAL aid added
2026-08-12 to help LLM call 2 find values in a 271-page document. Facts have
always lived separately. The purge's only real cost is the one below.

### RESOLVED - the purge vs the multi-contract downgrade (no change needed)

`PackageContext` reads `dec_page_entries`, which IS purged after generation, and
it DOES run after generation (every producer answer re-runs the pipeline). The
concern was real: lose the multi-contract evidence and the date hard stop comes
back, so the score drops 85 -> 60 after a producer does something helpful.

A change was proposed (retain the contract-key list past the purge) and then
**measured before being built - and it turned out to be unnecessary.** Two
independent survivors:

1. **`coverage_lines` survives the purge** and carries the policy numbers.
   Verified on a real session by stripping `dec_page_entries` in memory:
   `contracts={BBC7263-26, 6E7-40-02---26, 6J7-40-02---26, 6C7-40-02---26}`,
   `is_multi_contract` still True.
2. **Per-document `dec_page_entries` are untouched** - the purge deletes only
   the MERGED session fact, not each document's own copy.

So: nothing extra is retained, no new PII, the purge is unchanged, and the
downgrade keeps working after generation. `test_dec_index_purge.py`'s known-file
list records the decision with this reasoning.

**Noted, out of scope:** the purge is therefore less complete than its own
comment implies - the per-document copies remain in the session. That is a
data-minimisation question for the owner, not a correctness one.

### A note on how the storage tests are written

The first version of `test_facts_never_replaced_20260817.py` drove the real
repository against real DB rows. It passed in isolation and failed nine ways in
the full suite: `test_arq_acord125_missing_only.py` installs a **stub asyncpg**
so the suite runs with no database at all. A DB-bound test would have failed in
CI for everyone.

The fix was not to work around it but to make the code better: the decision was
extracted into `repositories.session_repository.resolve_facts_write`, a pure
function with no I/O. The most dangerous logic in that module is now unit-tested
exhaustively - undecryptable blob, unreadable non-dict, new session, blank-value
race, no mutation of the caller's dict - with no database anywhere.

### Tests

* `backend/tests/test_fact_equivalence_20260817.py` - 104 tests with
  `test_facts_never_replaced`. The GATE is
  `TestTheUmbrellaConflictSurvives`: $3,000,000 vs $1,000,000 must survive the
  pure value test, the group filter AND a full package context. It caught a real
  over-reach mid-build (see below).
* `backend/tests/test_facts_never_replaced_20260817.py` - drives the REAL
  repository functions against real rows, because the defect lives in the
  interaction between two functions and a mock of either would have passed while
  production lost data.

**Two of my own bugs were caught by these tests before landing**, both worth
recording: (1) `"$1,000,000"` is a contiguous token run inside
`"$1,000,000 / $2,000,000"`, so the containment rule merged a single limit with
a composite - a money field now never gets a text opinion once both sides have
been read as money; (2) `is_component_of_package` asked only "is this value
line-attributed?", which made the umbrella's OWN $3,000,000 a "component" and
merged it with the COI's $1,000,000 - the component rule now requires positive
evidence on BOTH sides (one line-level, one package-level).

### Scripts committed with this work

* `backend/scripts/generate_conflict_probe_pdfs.py` - the five probe documents.
* `backend/scripts/dump_session_facts.py` - offline inspection of any session:
  merged facts, flags, per-document facts, the dec index, and a replay of every
  Data Consistency row with its inputs and which value was suggested.

Both are committed because three of four predictions made from code-reading
alone were WRONG on 2026-08-17. This area cannot be reasoned about, only
measured.

### Measured result on the four probe runs

| Run | Rows before | Rows after |
|-----|-------------|------------|
| A (single self-contradicting doc) | 1 | 1 (the real one) |
| B (dec + certificate) | 12 | 3 |
| C (two policies, two terms) | 4 + **HARD STOP, score 60** | 2, **warnings only** |
| D (dec + narrative) | 3 | 1 |
| **Total** | **20** | **7** |

The umbrella conflict survives in run B. What remains: `contractor_type`
("Contracting" vs "Commercial roofing contractor" - see the deliberate decision
below), `umbrella_effective_date` (a date extraction lifted out of a remarks
sentence - F11, deferred) and run C's two date rows, which are now warnings and
which the producer SHOULD confirm.

### Fix 7 - `services/narrative_facts.py` (NEW): read the facts INSIDE a remark  [DONE]

Client's second half of the Additional Remarks item: *"The individual facts
within it need to be interpreted in their appropriate context."*

**What it emits is STATEMENTS, not facts.** That distinction is the whole
design. Probe run B showed the naive version: extraction lifted `07/25/2025` out
of *"...reduced from $3,000,000 to $1,000,000 effective 07/25/2025"* and stored
it as the UMBRELLA'S EFFECTIVE DATE - an endorsement date in a policy-inception
box. A number inside a sentence is not a value; it is part of a statement.

```
{subject: umbrella_limit, from: $3,000,000, to: $1,000,000,
 as_of: 07/25/2025, policy_number: 6J7-40-02---26, quote: "<verbatim>"}
```

**Deterministic, no LLM, no cost.** An LLM pass was the first design and would
have been nearly free (measured: 188 / 1,077 / 1,288 characters of narrative on
three real Orbin packages). It was not taken for a better reason than cost: the
subject must be a fact key we already own and the amounts must be strings the
document literally printed - both are LOOKUPS against tables that already exist
(`arq_service._FIELD_PRODUCER_LABEL_MAP`, plus the package's own dec-index
labels, which is the document teaching us its vocabulary). A model would add the
one failure this feature cannot afford - an invented subject - to solve a
problem that is already a lookup.

**The consumer EXPLAINS a conflict; it never resolves one.** The same client
required that *"an unresolved fact remains unresolved downstream rather than
another part of Primble independently selecting a value"*, so the picker row
gains a `narrative_note` and nothing else - no value chosen, no pre-select, no
fact written:

> **Umbrella / Excess Limit - values differ, confirm**
> $3,000,000 *(dec.pdf)* vs $1,000,000 *(coi.pdf)*
> **From the submission:** The submission's remarks state this was reduced from
> $3,000,000 to $1,000,000 effective 07/25/2025 under policy 6J7-40-02---26.
> Confirm which applies.

Verified end-to-end through the real picker on the client's literal paragraph.

**Two defects found and fixed during the build, both worth recording:**
* `$6,720` (a total premium) was being attached to `gl_aggregate`, because
  "total premium" is not in the vocabulary and "general aggregate" was still
  inside the distance window. A label may no longer reach across a coordinating
  conjunction or a comma - a clause boundary ends its reach.
* The policy number rendered as its match key (`6j7400226`). The printing is now
  recovered from the sentence by allowing the document's own separators between
  the key's characters, so `6J7-40-02---26` and `BBC7263 - 26` both come back as
  printed.

Frontend: one amber note under the conflict row in `AcordModal`, rendered only
when `narrative_note` is present.

Tests: `backend/tests/test_narrative_facts_20260817.py` (21). Most of them are
guards rather than features - a bare date never becomes a statement, a date is
never emitted as a value, a label cannot cross a conjunction, a statement never
spans a sentence boundary, an unknown subject is dropped, an unknown policy
number is not attributed, "ranges from X to Y" is not an amendment, and the
explanation never names a winner.

**Honest scope - what is NOT mined, and why.** Loss/claim rows (*"a water damage
claim dated 03/14/2023 was paid at $18,400 and is closed"*), exclusion clauses
(*"excludes any work performed above three stories"*) and negative assertions
(*"the insured confirms no subsidiaries"*) genuinely need language
understanding, not a lookup. Producing them from regex would put wrong data on a
legal form. They remain scoped work and are recorded at the bottom of the module.

---

## ROUND 2 - the probe re-run, 2026-08-17 (fixes 8-11)

The owner re-ran all four probes on the round-1 build. Three behaved; run 1 did
not, and the miss is the important entry here.

### Fix 8 - THE MISS: the date hard stop fired from a SECOND engine  [DONE]

Probe run 1 came back with the downgraded WARNING *and* a hard stop capping the
score at 60, for the same two dates, on the same screen.

`check_doc_consistency` was fixed in round 1. `extraction_pipeline`'s own
hard-stop escalation over `underwriting["fields"]` was not - it re-derives
blocking from `HARD_STOP_RECONCILABLE_KEYS` and knew nothing about the
downgrade. **Two engines, one rule each, exactly the duplication CLAUDE.md
warns about in four separate entries, walked into anyway.**

Fixed by moving the decision to ONE place:
`underwriting_consistency.CONTRACT_SCOPED_HARD_STOP_KEYS` = {effective_date,
expiration_date} - the hard-stop keys that belong to a CONTRACT rather than to
the APPLICANT. A package has one insured and one FEIN however many policies it
carries, so those stay blocking; it does not have one policy term. The
reconciler sets `blocking_downgraded` on the row and both engines read it.

Verified on the owner's session: `blocking_downgraded=True` on both dates, zero
hard stops.

### Fix 9 - The narrative note never appeared  [DONE]

Round 1's `narrative_note` was correct code reading the wrong source. It mined
`merged_facts["additional_remarks_text"]`, and the merge had kept PROBE2's short
title while discarding the certificate's paragraph - the one carrying the
umbrella sentence. `statements_for_facts` now reads EVERY document. Remarks
accumulate (that is the whole reason two paragraphs are not rival values), so
every copy has to be read. Confirmed present on the owner's session.

### Fix 10 - A composite listing fewer limits is not disagreeing  [DONE]

`Gl Limits`: the dec page printed three limits, the certificate the same three
plus "damage to rented premises". Same rule as lines of business - only sets
that EACH carry something the other lacks genuinely disagree.

**BOTH sides must be composites.** A first cut allowed a single amount against a
composite, which merged `$1,000,000` with `$1,000,000 / $2,000,000` and undid
`test_a_composite_amount_is_never_flattened`. Caught by that test.

### Fix 11 - The four residual defects, closed  [DONE]

**F9 - absence became "No"** (client item 3). Full detail in `improving-ll.md`
C63. Three `risk_transfer` booleans gained `or null`; the 40 `has_*` coverage
flags deliberately did not. Plus a deterministic check that removes a `false`
whose topic the document never mentions - run PER DOCUMENT, because the
cross-document detector compares per-doc facts and dropping only from the merge
would have left the cards in place.

**F11 - an endorsement date became a policy date.**
`_drop_endorsement_dates_from_policy_facts`: a policy-date fact whose value is
the `as_of` of an amendment the narrative states, and which no declarations page
prints against a date label, is removed. Positive evidence on both sides, so a
policy whose term genuinely starts on an endorsement date keeps it.

**F10 - the document's title stored as a remark.**
`_drop_page_furniture_remarks`. **"Near the top" is not the signal, "IS the top"
is** - a first cut used "within the first 200 characters" and dropped a REAL
remark, because an ACORD 101 is mostly remarks and they start right after a
one-line header. Now the document must BEGIN with the value, and the value must
be short enough to be a heading (120 chars; 250 was tried and dropped a real
142-character remark). Five shapes pinned by test.

**F15 - the crime warning that fired on every submission.** The trigger was
`has_cash_exposure or num_employees > 10`. Ten employees is below almost every
commercial account, so it fired on all four probe runs - including a ROOFING
CONTRACTOR - and the message then asserted that "the business description
indicates potential employee dishonesty or cash-handling exposure", which the
description never said. The spec says *"high internal cash handling"* and says
nothing about headcount; the headcount clause was never spec'd. Removed.
Detection WIDENED to the narrative fields to compensate, and the message now
NAMES the matched evidence so a producer can check whether we read the document
correctly.

### Measured result on the four probe runs, round 2

| Run | Original | After round 1 | After round 2 |
|-----|----------|---------------|---------------|
| A (single self-contradicting doc) | 1 | 1 | 1 (the real one) |
| B (dec + certificate) | 12 | 4 | 2 + the umbrella's explanation |
| C (two policies, two terms) | 4 + **HARD STOP 60** | 2 + **HARD STOP 60** | 2, **warnings only** |
| D (dec + narrative) | 3 | 1 | 1 |

Also gone across runs B and D: the three "Dec Page: No" cards, and the crime
warning from every run.

Tests: `test_absence_and_context_20260817.py` (27). Suite **3295 passed / 2
failed** - the same two pre-existing, zero regressions.

### Not owned here

`test_producer_answer_validation.py::...[wc_el_each_accident-Statutory]` failed
during this round. Confirmed to be a PARALLEL session's uncommitted edit to
`routes/audit_routes.py` (stashing their change made it pass 11/11); it cleared
on its own within the hour. Recorded, not owned - same as the round-12 note in
FIX_TRACKING_2026-08-15.md.

### Deliberate decisions not to act

* **`contractor_type` "Contracting" vs "Commercial roofing contractor" stays a
  conflict.** Merging it needs a stem/semantic rule, and the same rule would
  silence `construction_type` "Frame" vs "Joisted Masonry" - a real
  disagreement. Low value, real risk. Left visible.
* **`6E7-40-02---26` vs `6E74002` is not merged by the pure value test.** A
  strict alphanumeric prefix is not proof on its own; it merges only through
  `PackageContext.same_contract_printing`, which reuses
  `pdf_service._canonical_policy_printing`'s election rule (exactly one
  canonical key may claim a printing).
