# LLM Call Registry & Cost Issues

**Purpose:** single source of truth for every place Primble talks to an LLM, what each call
costs, and every known inefficiency. This file exists because a cost audit found ~80% of
input spend was byte-identical text being re-uploaded on every call, and nothing in the
codebase measured token usage at all.

> ## MAINTENANCE RULE
> Any PR that adds, removes, or modifies an LLM call, edits a prompt, or changes
> batching/chunking **MUST update this file in the same commit.**

**Line numbers drift.** Each entry names the *function*, which is stable — grep for the
function name rather than trusting the line number.

**Model:** `gpt-5.4-mini` — **400,000-token context window**, **128,000-token max output**.
The context window is shared by input and output. Our own output cap
(`FORM_FILL_MAX_TOKENS`) is 16,000 — a cost/rate guard, far below the model's limit.
Measured tokenizer ratio on a real 271-page package (o200k_base): **4.01 chars/token**.

**Pricing:** **$0.75 / 1M input**, **$4.50 / 1M output**.
Cached input bills at roughly 10% of input price. **Output is 6× input**, so wasted output
tokens hurt disproportionately.

---

## 0. Handoff / current state

**`HANDOFF.md` (repo root) is the entry point for anyone new to this work.** It carries the
problem statement, everything fixed on 2026-07-30, the measured before/after, the three
separate chunkers and their limits, and the ranked open-issue list.

**Three chunkers exist and they do NOT share a limit.** This has confused every reader so
far, so it is stated here once:

| Stage | Limit | Origin | On a 683,601-char doc |
|---|---|---|---|
| Extraction | 56,000 chars | Derived (**C31**, was a hand-typed `100_000`): `min(quality, capacity)` where quality = `EXTRACTION_DOC_TOKENS_PER_CALL` (14,000 tok) and capacity = the window minus overhead and reply reserve. **Quality binds; capacity is 20x larger.** | 14 chunks |
| Gap fill | 899,393 chars | Derived: `(400,000 tok x 0.75 - 16,000) x 3.5`, minus reply reserve/prompt/fields block | 1 chunk |
| Compliance | same budget | own arithmetic, same inputs | 1 chunk |

Gap fill makes ~46 calls on that document not because the document is split, but because
1,104 general fields / 40 + 131 compliance questions / 10 = 46 **field** batches. Each call
carries the complete document.

**The inconsistency is not academic:** extraction's 14k tokens/call behaves well; gap fill's
170k tokens/call is where C21 degradation was measured. The extraction number was accidentally
the safer one. It is now *derived and clamped* (C31) but deliberately **still 14k** — deriving
it was about provenance and a capacity guard, NOT about scaling it up. Raising it toward
capacity would trade a known-good stage for ~$0.11 a run. Do not.

---

## 1. LLM call-site inventory

Verified by grepping `groq_chat(`, `completions.create(`, `messages.create(` across
`backend/`, excluding `venv/` and tests. **11 application call sites.**

### Hot path — fires on every form generation

| File | Function | Fires | Output cap | Cached |
|---|---|---|---|---|
| `services/pdf_service.py` | `_chat_json` (inside `_fill_unmatched_with_gpt`) | **once per field sub-batch × doc chunk — dominant cost** | 16000 | ✅ since 2026-07-29 |
| `services/extraction_service.py` | `extract_facts` | once per document chunk | 16000 | ✅ prefix-first |

`_chat_json` serves BOTH hot-path stages and tags each with a `stage` label that appears in
its `LLM_SPEND` line and its `prompt_cache_key`:

* `stage=gap_fill` — the general field fill (`_PROMPT_SKELETON` system prompt). Since
  2026-08-13 this covers **two sub-stages sharing one system prompt**: Stage A, which
  carries the declarations index in the document's position, and Stage B, the raw-document
  walk. They are logged `STAGE_A` / `chunk n/N` and share the `[system + form label +
  facts]` cached prefix by construction. See C54.
* `stage=compliance` — the dedicated Yes/No pass (`_COMPLIANCE_SYSTEM_PROMPT`).
  **Untouched by C54** — disclosure answers live in policy wording, which the dec-page
  recorder is instructed never to record.

They are **separate cache families** because the system prompt differs. That is correct and
expected; do not try to merge them.

`_chat_json` also contains a second `create()` call — a `json_object` fallback used **only**
for a genuine `response_format` rejection. See C7.

### Conditional — fires only on specific conditions

| File | Function | Fires | Output cap |
|---|---|---|---|
| `services/extraction_service.py` | `_safe_json_parse` | **JSON repair** when a reply won't parse (up to 2×) | 4096 |
| `services/extraction_service.py` | reconciliation | only on cross-document fact conflicts | 4096 |
| `services/pdf_service.py` | `_fetch_umbrella_period_sync` | only when ACORD 131/25 is selected **and** extraction already missed the umbrella dates — then once per document chunk until both are found (usually 1) | 500 |
| `services/arq_service.py` | `_humanize_field_names` | ARQ question generation (module-level cached) | 1500 |
| `services/arq_service.py` | `_classify_other_reason_adverse` | producer selects "Other" reason | 5 |

### Download-time only — never during generation

| File | Function | Output cap |
|---|---|---|
| `services/cover_service.py` | cover page generation (2 sites) | 4096 |
| `services/sqs_service.py` | `generate_sqs_narrative` | 1024 |

**`generate_sqs_narrative` prompt edited 2026-08-12** (same single call, no cost change;
prompt a few words longer, replies typically shorter): the model is now FORBIDDEN from
restating the numeric score / tier / point totals - the UI renders the live number, and
prose that restates it can only agree by luck (client screenshot: banner 66/100, summary
paragraph "scores 63/100" on the same screen). The score/tier stays in the prompt as
context. Paired fix in `routes/audit_routes.py`: the endpoint now feeds this call the
PACKAGE result (the same object the banner renders) instead of the first form's per-form
result, which was the source of the 63.

### User-triggered chat bots — AUDITED CLEAN, do not investigate again

| File | Endpoint | Output cap |
|---|---|---|
| `routes/assistant_routes.py` | `POST /api/assistant/chat` | 400 |
| `routes/arq_routes.py` | `POST /api/arq/chat/{token}` | 300 |

Both are POST-only, require auth or a valid unexpired ARQ token, clamp history to the last
6 messages, and are tightly capped. **`services/scheduler_service.py` contains zero LLM
calls** — it only runs DB cleanup. Neither bot can fire unattended. They were suspected of
background spend during the audit and definitively cleared.

### Dead code

| File | Note |
|---|---|
| `services/pdf_service.py` | `_fill_empty_from_raw_text` — the pre-`_fill_unmatched_with_gpt` fill, marked "Do NOT call this function". **Zero callers, verified by grep across the repo.** Costs nothing; candidate for deletion. Its prompt still contains the old "return JSON null" convention — deliberately left alone rather than edited, since editing dead code is pure risk. |

---

## 2. Cost model

For a form-generation run:

```
gap_fill_calls ≈ (non_compliance_fields ÷ FIELD_FILL_BATCH)
               + (compliance_fields    ÷ COMPLIANCE_BATCH)     … × doc_chunks
```

Every sub-batch re-sends the **entire** constant block. Measured from a real 2-form run
(ACORD 125 + ACORD 25, `raw_text_chars=5226`), solving `4 fields → 24,619 chars` against
`40 fields → 31,573 chars`:

| Component | chars | constant within a run? |
|---|---|---|
| `_PROMPT_SKELETON` | 8,599 | yes |
| Facts block | ~10,021 | yes |
| Raw document text | 5,226 | yes |
| **Fixed overhead per call** | **23,846** | **yes — this is the problem** |
| Per-field | 193 | no |

That run made ~17 gap-fill calls → **~405,000 chars (~101,000 tokens) of pure repetition.**

**This holds at every document size.** On a small document the fixed overhead dominates; on
a 270-page package the document dominates. Either way the repeated part is ~94% of each
prompt, so prefix caching is the correct fix in both regimes.

**Batch sizes are deliberately NOT the lever.** `COMPLIANCE_BATCH=10` and
`FIELD_FILL_BATCH=40` were tuned in commit `7fa0d43` (2026-07-20) to fix a false-"N" flood
on Yes/No compliance questions. That commit raised document shipments ~6.9× as a side
effect, but the answer is to make each shipment nearly free via caching — **not** to undo
the accuracy work.

### How prefix caching actually engages — read before touching any prompt

Four conditions, **all** required. Breaking any one silently returns the run to full price.

1. **The system message must be byte-identical** across every call in a stage. It is matched
   from token zero.
2. **Everything constant must precede everything variable** in the user message. The cache
   matches a *prefix*; nothing after the first divergent byte can be reused.
3. **Chunk boundaries must be stable.** Any budget derived from a batch's own size produces
   different document slices per batch, i.e. different bytes, i.e. a miss (C3).
4. **The prefix must be ≥1024 tokens.** Below OpenAI's floor, nothing caches at all.

There is also a fifth, non-obvious condition that is easy to lose:

5. **Concurrency defeats a cold cache.** OpenAI populates a cached prefix only when a request
   *completes*. Firing N sub-batches at once through the thread pool makes the first
   `_FIELD_BATCH_POOL` of them all misses. `_PREFIX_WARMUP` (default on) runs one call to
   completion first, then fans out the rest — on a 6-batch run that is the difference between
   ~33% and ~83% of calls hitting cache. `LLM_PREFIX_WARMUP=0` disables it.

---

## 3. Open issues

### C62 — THE FOURTH DOOR: alias stamping bypassed every resolver and every guard (2026-08-13), NO LLM change

**This is the root cause behind six runs of the same defect, and it is architectural, not
per-field.** `map_facts_to_form` has FOUR paths that write into `mapped`, and the guards
only ever covered two or three of them:

```
Pass 1    _deterministic_map            <- owning resolvers live here
Pass 1.5  alias_stamper                 <- writes mapped[field] DIRECTLY. Covered by NOTHING.
Pass 2    gap fill                      <- gpt_filled_set guards
post-fill resolvers / canonicalisation
```

`stamp_form_fields` never routes through `_deterministic_map`, so every authoritative-blank
resolver was invisible to it, and it never touches `gpt_filled_set`, so every guard scoped
to gap fill was invisible too. **Measured across all 17 alias maps: 137 fields that a
resolver OWNS were being overridden** — the FAX box, the deposit, REMARKS, the applicant
website, the no-loss attestation, all 64 prior-coverage cells, the producer's printed name.

The FAX box is the proof. Each fix closed a real door and the next run used another:
run 3 gap fill (C55) → run 5 the resolver trusting a bad fact (C60) → run 6 Pass 1's
substring rule (C61) → **run 7 the alias map**. `forms_aliases/ACORD_125_alias.json` line
12 is `"Producer_FaxNumber_A": "producer_fax_number"`, and an alias map is a pure
name→fact dictionary that cannot know a box has no legitimate document source.

**Two rules, both now enforced by `backend/tests/test_value_source_contract.py` (9):**
1. **An alias map may not override an authoritative blank.** Both alias call sites defer to
   `_is_authoritative_blank_field`; the test checks the guard is inside each LOOP BODY, not
   file-wide (an identically-named guard exists in the unmatched-set builder and a naive
   count passes on its back).
2. **A guard that judges whether a value is POSSIBLE FOR ITS BOX must be source-agnostic.**
   Only guards judging MODEL BEHAVIOUR (hallucinated keys, ungrounded quotes) may scope to
   `gpt_filled_set`. A sex code inferred from a first name and a licence year borrowed from
   a vehicle are wrong whichever pass stamped them — scoping them to gap fill is precisely
   what let Pass 1.5 deliver the same values unseen. The driver-personal and row-label
   guards now iterate `mapped`, checked structurally on their loop headers.

Replayed run 7's exact fact shape (the phone filed under BOTH `producer_fax` and the alias
key `producer_fax_number`): fax, deposit, remarks, driver sex, marital status and licensed
year all blank; a genuinely distinct fax still stamps through the alias path. Suite
**2394 passed / 2 failed**, same two pre-existing, zero regressions.

**The 184-entry question, measured rather than guessed.** The index IS thin — 211 verified
entries from ~30 declarations pages, where the ground-truth estimate is ~750. The cause is
NOT the caps (`DEC_ENTRY_MAX`=1200, per-chunk 150) and NOT the output ceiling: run 7's
per-chunk output was `[9458, 1913, 1837, 4738, 6304, 2254, 3910, 2970, ...]` against a
16,000 cap, median 2,970. 150 entries alone would need ~5,250 tokens. **The model simply
does not spend its attention there** — `dec_page_entries` is one key among ~170 in a single
JSON reply, and it satisfies "at most 150" by returning ~15.

**Deliberately NOT fixed in this commit**, and the reason is the standing rule about
bundling: tripling entry output is a real cost change (C21/C54 territory) with no evidence
yet that it improves stamped accuracy — Stage A already answers what it answers, and the
wrong values on run 7 came from the alias door, not from a missing entry. The clean fix is
a dedicated second call for dec entries, or splitting the extraction schema, and it should
be measured on its own. Raised as the next candidate, not smuggled in beside a root-cause fix.

### C61 — run 6: the warning appeared, five survivors closed, one wiring bug caught (2026-08-13), NO LLM change

**The warnings question is now CLOSED with evidence in both directions.** Run 6's screen
showed "GL coverage detected but no revenue or payroll found" — the engine was never
broken; this fresh extraction (cache-missed) didn't capture payroll where earlier cached
runs had. The pipeline surfaces exactly what `evaluate_stops` computes, run to run.

**Also visibly working on run 6's forms:** vehicle row 2 CLEAN (the C60 late sweep),
Q5/Q8/Q13 blank, deposit blank, REMARKS blank, Q4's policy numbers correct, form numbers
dropped ×9 in the log. The five survivors, each through a door the guards missed:

1. **FAX, 5th time — the THIRD door.** Gap fill was closed (C55 guard), the resolver was
   built (C60)… and run 6 stamped the phone through **Pass 1**: the generic substring rule
   `"Producer_FaxNumber" → producer_fax` stamped the mislabelled fact RAW, never consulting
   the resolver. **An owning resolver that is not consulted where values are produced owns
   nothing** — `_resolve_party_fax`/`_resolve_payment_deposit` now have explicit call sites
   in `_deterministic_map` before the rules loop, like every other owning resolver. The
   identity check also now sweeps EVERY phone-bearing fact, not a hand-list of two.
2. **Q3 via the bare label** — `"Limited Pollution Coverage - Work Sites"` with the $150
   dropped, so the money-tail requirement missed it. A text that IS exactly a printed dec
   LABEL is a field-name echo and needs no tail; label+value lines keep the tail standard,
   which is what protects `INSURED IS: LLC` and `Date of Issue: 07/16/2025`.
3. **Q9 AND Q10 via `ERIN ROYAL`** — a name-only record's name spent as evidence twice
   (Q10 asks about MVR *practice*; a name answers it not at all). The record was already
   ruled not-a-schedule for carrying nothing but the name; `_is_name_only_record_echo`
   rules its name carries exactly as much. A driver WITH a licence keeps their name as a
   real Q9 answer.
4. **A fabricated interest with no ordinal** — "Blanket Additional Insured Status For…"
   (an endorsement TITLE) as the party NAME, plus the producer's address and the account
   number. The row-label guard can't see it (no ordinal), but it IS a printed dec line:
   the artifact test now runs on interest NAME boxes; blanking the name unanchors the row
   and the late sweep clears the rest.
5. **Q14's orphan dep cells** — question blank, its conviction table carrying the
   insured's own city and a borrowed "1". `DEP_WITHOUT_YES`: dependents standing under a
   question that is not Yes are cleared — the mirror of `YES_WITHOUT_SUBSTANTIATION`,
   same principle as Guard 5, extended to table dependents. Gap-fill cells only.

Plus: the truncated-header guard (`COMMERCIAL GENERAL CONTRA`) widened beyond gap fill —
run 6 delivered it through a deterministic fact path into the premises box, and inside
`map_facts_to_form` every value is document-derived, so no provenance is overridden.

**A wiring bug the new tests caught before it shipped:** the C60/C61 late sweeps
referenced `_ai_verified_fields`, which is initialized AFTER those blocks — an unbound
local that killed a sweep mid-run, silently, inside its own try/except. The discards were
conceptually no-ops (verification runs later and never marks a None) and are removed.
That is the second time this session a fail-open handler hid a real defect; worth
remembering when reading "skipped" warnings in logs.

**Honest residuals:** the RETAIL/OFF-PREMISES `100%` pair (borrowed from Q17's monitoring
percentage — the percentage guard passes it because "100" is genuinely printed) and
`PAYMENT PLAN = "AN"` (the model truncating "Annual"). Both cosmetic-tier next to what
this arc closed; named so they are known, not missed. Tests:
`backend/tests/test_run_20260813f.py` (11). Suite **2385 passed / 2 failed**, same two
pre-existing, zero regressions. Inspector PASS, no LLM change.

### C60 — run 5: every survivor traced to the check it walked around (2026-08-13), NO LLM change

Run 5's form is the C59 fixes visibly working (remark blank, Q11 blank, member count blank,
loss years blank, form numbers off Q4, `other_policy: row dropped` x9 in the log) plus seven
survivors — each of which named its own hole:

1. **FAX, fourth time — through a NEW door.** The resolver made the box fax-fact-or-blank;
   this run, extraction itself filed "Agent Phone: 303-996-7800" under `producer_fax` and
   the resolver trusted the fact. Now value-identity: a fax digit-identical to the party's
   phone is a mislabel, whoever produced it.
2. **DEPOSIT = $31** — the terrorism premium, after run 3's $10,663. The walk hunts until
   the batch's last empty field finds a money-shaped value, and this package states no
   deposit. `_resolve_payment_deposit`: deposit fact or blank (contract test +1).
3. **Q3 = Y via `Location 000: Limited Pollution Coverage - Work Sites $150`** — the
   row-label PREFIX defeated exact membership, exactly the partial coverage predicted when
   the dec-line check shipped. `_ROW_LABEL_PREFIX_RE` strips it before matching.
4. **Q5 = Y via `CONTRACTORS EQUIPMENT $10,000`** — the item's dec ENTRY was dropped at
   verbatim verification (the carrier truncates it differently per page), blinding the
   dec-line check. But the item lives in the FACTS as an inland-marine schedule row:
   `_is_item_schedule_echo`, equality on normalized names against rows we already hold.
5. **Q8 = Y via "Please contact your agent to discuss any questions."** — an imperative has
   verbs, so the assertion test passes it. `_QUOTE_CTA_RE`: a sentence opening with a
   directive to the reader is an instruction, never a fact about the applicant.
   All three shapes unified as `_is_coverage_artifact_text`, applied to quotes,
   explanations AND dependent-table cells (an artifact-filled dep no longer substantiates).
6. **Q13 = Y "vehicles owned but NOT scheduled", explained by the VIN stamped in row 1 of
   the SAME form.** The form contradicts the answer; no topic matching needed — a
   supporting VIN found among the form's own `VINIdentifier` values blanks the Yes.
7. **THE ORDERING DISEASE, named as a class.** Vehicle row 2 leaked AGAIN (GL class 91585,
   $10,000) despite the anchor rule, and Q1 printed Y over an empty owner table despite the
   substantiation rule — both because those judgments ran while junk still stood: gap fill
   had copied identity into row B / filled dep cells, the later duplicate/artifact guards
   cleared them, and the judgment was never revisited. **Anchor state and substantiation
   are only true at the END of the pipeline.** Both checks now run a second, late pass just
   before the final Yes/No coherence sweep — idempotent, no-ops when the first pass was
   right.

**The warnings question, settled:** the upload path calls `run_extraction_pipeline`
(form_routes:355) → `evaluate_stops` → the C59 log line, which fired in the truncated log
region. This package is genuinely `hard=0 soft=0` when payroll and class codes are captured.
Grep the console for `evaluate_stops:` — if it ever reports non-zero while the screen shows
nothing, THAT is a display defect; so far it has not.

**Honest residual:** Q14 (convictions) = Y with junk deps (`DENVER CO.`, `5`) — the dep
cells are borrowed prose, not artifacts, and no deterministic test separates them from a
real conviction row without topic matching. If it survives the next run, the candidate rule
is "a conviction row needs its DATE or TYPE, not just a place" — a substance rule like the
driver schedule's. Tests: `backend/tests/test_run_20260813e.py` (16). Suite **2374 passed /
2 failed**, same two pre-existing, zero regressions. Inspector PASS, no LLM change.

### C59 — the ACORD 127 root causes, fixed at class level (2026-08-13), NO LLM change

**The owner's challenge, verbatim: "why can't we fix the root cause responsible for these
issues... it is about fixing for all the forms."** The honest accounting: this pipeline had
THREE root causes. Retrieval (C54) was fixed and held — it is why the 125 went from garbage
to mostly-correct. The 127 exposed the other two, and this entry closes them for every form.

**ROOT CAUSE 2 — the source is a POLICY, the form asks about the RISK.** The evidence gate
verified a Y/N quote EXISTS; it never asked whether the quote is a statement about the
APPLICANT or the policy describing its own coverage. Every wrong Y on the live 127 was that
one defect wearing different costumes: `Auto Elite Extension $250` proving "car modified",
`Limited Pollution Coverage - Work Sites $150` proving "chemical exposure", `ERIN ROYAL` (a
Drive Other Car name) proving "family use". Fixed at the gate, all 17 forms, judging only
the quote's OWN NATURE (never quote-vs-question topic, per the standing rule):
- a YES quote must assert something (`_quote_asserts_something`, C47) **or carry a data
  payload** — the exemption exists because `INSURED IS: LLC` and `Date of Issue:
  07/16/2025` are verbless AND legitimate, and the prior test corpus caught the first cut
  killing them;
- a YES quote or paired EXPLANATION that IS a verified dec-index line **with a money tail**
  is the carrier granting coverage, never the applicant reporting a fact
  (`_is_dec_coverage_line` — Stage A's index reused as a deterministic artifact detector;
  the money tail is what separates a coverage grant from a dec-page fact line);
- `_POLICY_SELF_SUBJECT_RE` now applies to quotes in both directions.
The explanation check matters as much as the quote check: a Y arriving with a paired
explanation used to skip every quote test, which is exactly how Q5 survived.

**ROOT CAUSE 3 — phantom-row protection depended on extraction.** C46's resolver acts only
on positive evidence, so a run where extraction misses `auto_vin_schedule` (measured: it
jitters) leaves all 220 vehicle questions to gap fill — and row 2 printed GL class code
91585 as its rate class, C46's literal defect through a different door.
`_unanchored_schedule_row_fields` needs no schedule fact: **a row whose registered identity
columns are all empty has no subject, so its details describe nobody.** Derived from
`_SCHEDULE_REGISTRY` (all 16 roots, all 17 forms), gap-fill values only, rows strictly
beyond the first list row — the first cut judged row A and cleared a genuine
`Vehicle_Question_ModifiedEquipmentDescription_A` (a General Information answer that merely
shares the Vehicle prefix); the test corpus caught it and the scoping is now pinned.

**Also closed:** driver PERSONAL columns (sex, marital status, DOB, licence, licensed year,
tax ID, hire date, experience) may no longer arrive via gap fill — `F` and `2012` are
valid-shaped and the defect is ATTRIBUTION: loose personal data in 271 pages cannot be
pinned to a scheduled driver by position; only the driver record can, and record values
arrive via the resolver. And the FAX box (three runs of the producer's phone) is now
`_resolve_party_fax`: a fax stamps from `producer_fax` or not at all — same shape as
`_resolve_applicant_website`.

**The warnings question, answered with the engine rather than a guess:** with the facts
page 211 actually prints (payroll $39,300, class codes 91580/91585) `evaluate_stops`
returns **hard=0 soft=0** — the clean run was the checks passing, not the engine failing.
`extraction_pipeline` now logs `evaluate_stops: hard=N soft=N` (and each message) so the
next "why no warnings" is answered by the log.

Tests: `backend/tests/test_run_20260813d.py` (25) — the literal Q5/Q9 reproductions fall
end-to-end, the genuine hazmat Yes survives, the row-2 leak clears, row-A singletons are
pinned safe. Suite **2354 passed / 2 failed**, same two pre-existing, zero regressions.
Prompt inspector PASS — no LLM call or prompt changed.

**Honest residuals:** the STATUS double-tick (ISSUE+BOUND) was left alone deliberately —
both ticked is defensible broker practice, and inventing an exclusivity rule ACORD does not
state is how false guards get built.

**C59 addendum, same day — the owner's Y/N rule, enforced structurally.** Stated verbatim:
*"if we have conclusive evidence of either yes or no, only then stamp the value... otherwise
leave it blank. And whenever there is a Y, there should be an explanation mandatory."* The
first half was already the gate (hardened above); evidence has never needed a literal Y/N in
the document — the model answers by meaning and the gate verifies the evidence. The second
half had a hole with a perfect fingerprint: **the six UNPAIRED questions on the live 127
were exactly the six wrong Ys** (not-solely-owned, >50% employees, modified equipment, ICC,
convictions, fleet) — questions whose explanation is a TABLE, invisible to the
`_question_explanation_pairs` machinery, so a quote alone kept the Yes with the owner/
conviction tables empty.

`_unpaired_question_deps` derives the pairing from ACORD's own layout rather than a hand
list: a question printed "(no explanation needed)" is followed IMMEDIATELY by the next
question in the schema (ABA, AAE, KAG → zero dependents, exempt); a question demanding
substantiation has its table between itself and the next question (AAJ → the owner-name
columns, AAI → the AccidentConviction table). Verified against the real 127 schema, pinned
by test. A kept Yes with every dependent empty is blanked (`YES_WITHOUT_SUBSTANTIATION`).

**Two corrections the corpus forced, kept on the record:** (1) a run of nothing but /Btn
checkboxes is a QUALIFIER set ("check all that apply" — safety manual/meetings/OSHA), an
optional refinement, not an explanation section — the first cut blanked a genuinely-quoted
safety-program Yes for having no qualifier ticked; the run must contain a text field to
count. (2) `test_a_yes_backed_by_an_affirmative_quote_survives` was UPDATED, not appeased:
it happened to test on Q1a ("is the applicant a subsidiary?"), where a Yes with no parent
company named is precisely what the owner's rule forbids — the test now makes its original
point (affirmative quote beats negation) on a dependency-free question, and the subsidiary
contract has its own tests. Suite **2358 passed / 2 failed**, same two pre-existing.

### C58 — third live run of 2026-08-13: four boxes, NO LLM change, cost ZERO

**1. ADDITIONAL INTEREST fabricated a third party.** Five boxes from four documents on a
policy with no additional interest: `Location 000` as the NAME, the insured's own city and
postcode, `Limited` as ITEM CLASS, the insured's own `2012 SUBARU OUTBACK` as ITEM
DESCRIPTION, and a pollution endorsement as REASON FOR INTEREST. **Checked why the existing
guard missed it rather than assuming:** `_drop_third_party_address_bleed` matches on the
STREET line only — deliberately, because a real mortgagee can share the insured's city,
state and ZIP — and the street box was empty. Widening it would delete genuine lenders, so
the NAME carries this case: `_is_row_label_not_a_name` rejects a bare schedule row label
plus an ordinal (`Location 000`, `Item 4`, `BLDG 3`), anchored end to end so
`Building 19 Holdings LLC` is untouched. Blanking the name unanchors the row and the
existing orphan sweep clears the other four boxes with it.

**2. `COMMERCIAL GENERAL CONTRA` under OTHER NAMED INSUREDS — the rule was narrowed
mid-build, and that is the entry worth reading.** The obvious fix was an anchored-detail
pair: describing the operations of an unnamed party is never right. **It broke
`test_a_genuinely_different_row_b_narrative_survives`**, a deliberate prior contract —
extraction can legitimately find a second insured's operations while missing their NAME, and
blanking a real narrative to punish a missing name loses more than it saves. What is
actually wrong with the value is that it is the truncated HEAD of one we hold in full
(`contractor_type` = `COMMERCIAL GENERAL CONTRACTOR`), which extraction had already judged
verbatim: *"a 25-char fragment seen 4 time(s) - repetition of a truncated header is not
quality"* — a judgement that was never persisted where gap fill could see it.
`_is_truncated_copy_of_a_held_value` is prefix containment, bounded three ways: narrative
fields only, ≥20 chars (so `Roofing` ⊂ `Roofing and siding` is out of scope), and the fuller
value must exceed it by ≥3 chars.

**3. REMARKS / PROCESSING INSTRUCTIONS is now an authoritative blank.** Two runs, two kinds
of wrong text, same box: the IL8384A terrorism notice, then a 36-entry `Forms Applicable`
schedule transcribed off the dec page. **A density rule was considered and rejected** — it
would have caught this run and left the next phrasing open, and a genuine remark naming an
endorsement (`CG 20 10 additional insured attached per contract`) is ordinary broker
practice, so any threshold trades real remarks for boilerplate. The box asks what the
PRODUCER wants done with THIS submission; a bound policy cannot answer it, same category as
the "section attached" boxes. **Not an ACORD 101 regression, verified not assumed:**
`_compose_acord101_remarks` reads the FACTS `acord101_remarks` / `additional_remarks_text`,
never this field, and `AdditionalRemark_*` rows are explicitly exempt. A remark we genuinely
hold still stamps — and is itself checked for being a forms schedule, since that is exactly
how the fact got filled this run.

**4. `FOR THE LAST 0 YEARS`.** Into `_NONZERO_COUNT_FIELDS` beside the member count.
`LossHistory_TotalLossAmount` is deliberately NOT there and must never be: zero losses is a
real, common, correct answer, and this package's own ground truth reports none in five
years. A test pins the table at exactly two entries.

Replayed end to end against the client's literal values: all five boxes blank, including the
orphaned phone that rode along with the fabricated name. Tests:
`backend/tests/test_run_20260813c.py` (36). Suite **2329 passed / 2 failed**, the same two
pre-existing, zero regressions. Prompt inspector PASS — no LLM call added, removed or
reprompted.

### C76 — the resolver stops trading one issue for another, and C75's fix reaches the resolve path (2026-08-14), NO LLM change, NO scoring-engine change

**Owner, verbatim: "The date resolver should be umbrella-aware — entering an expiration that
misaligns with the umbrella's 07/15/2026 should tell you so in the modal, instead of silently
trading one issue for another. That's the loop you've been stuck in."**

**The loop, measured on the live ORBIN package.** `legacy_policy_term_expired` offered exactly
two inputs, effective and expiration. The umbrella carries its OWN printed period (07/15/2026),
so any other expiration cleared the expired term and immediately raised
`umbrella_gl_expiration_misaligned` — a different issue, in a different column, with no
connection drawn between them. Fix one, another appears; fix that, the first returns. Both
engines were behaving correctly; nothing joined them up for the producer.

**Three changes.**

1. **`umbrella_expiration_date` is a third, OPTIONAL input on BOTH term rows**
   (`legacy_policy_term_expired` and `legacy_policy_term_expiring` — the same modal with the
   same trade; fixing only the reported half would leave the identical trap one rule over).
   No new UI plumbing: `_r_field` already renders one pre-filled box per fact, and the modal
   submits only the facts actually TOUCHED, so a blank umbrella box behaves exactly as before.
   The pre-fill is the quiet half of the fix — the umbrella's date is now **visible beside the
   date being changed**, so the conflict is legible before it is caused.
2. **`/api/audit/resolve-issue` reports what a value RAISED.** Snapshot before the write,
   snapshot after the recompute, difference = what this value caused. **Scoped to issues the
   applied fact is a DECLARED remedy for** (`RESOLUTION_MAP` — the same table that decides
   which inputs the modal renders), never by matching words in the message. That scope is
   load-bearing twice over: it keeps the feature rule-agnostic (any future rule listing a fact
   as a remedy is covered the day it is added, and `test_the_binding_comes_from_the_resolution_
   map_not_from_words` fails the build if keyword matching reappears), and it is what stops the
   note crying wolf on ordinary recompute churn — the stop arrays are rebuilt from scratch on
   every recalculation, so a bare before/after diff of every message would fire constantly.
   Advisory only: the write already succeeded and stands.
3. **C75 had leaked.** `form_routes.py` was fixed so the display reads the same arrays the
   scorer reads; **this route kept the old shape**, so severity silently flipped BACK to
   "warning" the moment you resolved anything. `classify_stops` still runs — its demotion still
   decides whether the producer MAY proceed — it just no longer decides what they SEE.

**Frontend (`ResolutionModal.jsx`):** a note holds the modal OPEN on an amber "Saved - one thing
to check" banner naming what was raised and, when the remedy is an input already on screen,
saying so. Filling both boxes in one pass reports nothing — the second write clears what the
first raised and only the last response is read. Because the first value did save, **every**
exit (Apply again, Cancel, X, Escape, backdrop) routes through one `finish()` helper that
refreshes the panel with the authoritative response.

Tests: `backend/tests/test_umbrella_aware_date_resolver.py` (23), including the live strings
verbatim and both anti-rot guards. Suite **2687 passed / 2 failed** — the same two pre-existing
unrelated failures, zero regressions. Frontend production build verified. No LLM call added,
removed or reprompted; prompt inspector untouched by this change.

### C75 — nothing may be invisible: severity on screen now equals severity in the score (2026-08-14), NO LLM change, NO scoring-engine change

**Owner's rule, verbatim: "If it is a hard stop then show it on the hard stop not on the
warning ... every hardstop/warning should be shown to user."** Three fixes, all display-side
or issue-routing; `calculate_package_sqs` is untouched and **no score moves**.

**1. The screen honoured a demotion the scorer ignored.** `classify_stops` demotes a hard
stop for the PROCEED decision; the display was handed the demoted lists while the scorer
kept reading the raw ones. Measured on the live ORBIN session: grouped counts
`{hard_stops: 0, warnings: 1}` and a banner reading "caps your SQS at 85", while the score
was capped at **60** by that same stop. All five route call sites now pass the display the
same arrays the scorer reads. `warning_stops` still carries `_downgraded` - that is what
powers the "proceed anyway" banner, so the demotion still decides whether you MAY proceed,
it just no longer decides what you SEE. **Verified: the demotion never dropped anything, it
relabelled** (pinned by a count-in/count-out test).

**2. A suggestion may not become a blocker.** Cross-form rules run against `triggered_ids`,
which pre-selection is the RECOMMENDED forms - so a form the producer never chose could
raise a hard stop about its own missing data and cap the score by 8 points. Client report:
"there should not be any Builders Risk questions or an ACORD 133 - there is no builders risk
exposure". Demoted **generically for every form-scoped rule** (test-pinned rule-agnostic, so
it cannot decay into an ACORD_133 special case); the issue stays VISIBLE as a warning with
its own card and returns to full hard-stop force once that form is actually selected.
**Audited while here: 18 of 19 flag-gated rules already require a corroborating extracted
fact** - the discipline was already the norm; the cascade was the real hole.

**3. Blocking means hard stop, and relevance is a precondition.** The client's Property
Integrity directive - quoted verbatim in `GENERATION_BLOCKING_RECONCILABLE_KEYS` - is
"generate a warning and require review BEFORE FORMS ARE GENERATED". That is blocking, and
the scorer has always capped at 60 for it; only the display called it a warning. It now
raises as a hard stop, routed from the two DECLARED sets in `underwriting_consistency`
(no second local list - that duplication is exactly how these layers drifted). **Gated on
relevance** per the owner: a building-value disagreement cannot block a package with no
property coverage - there is no ACORD 140 to generate and no box for the number - so it
stays a visible warning there instead of capping. Never dropped, only downgraded.

**CORRECTION to C74's audit triage, on the record.** Two of the eight findings I confirmed
were wrong on my part: (a) the legacy/coded suppression is ALREADY gated on the coded twin
being present (`_present_codes`) - I read the stripping line without the six lines above it;
(b) the building-value stop is NOT invisible - it always rendered a card, as a *warning*.
The real defect in both areas was severity mismatch, not disappearance.

Tests: `tests/test_stop_visibility_c75.py` (13). Suite **2660 passed / 2 failed** - the same
two pre-existing unrelated failures, zero regressions.

### C74 — the evidence-layer audit: 8 findings, all 8 reproduced, 4 closed at the mechanism (2026-08-14), **+1 LLM stage** (the evidence judge), fail-safe by construction

**An external audit of the Yes/No evidence layer was checked claim by claim rather than
accepted. All eight reproduced.** Two had inflated numbers (197 of 312 compliance questions
lack an explanation slot, 63% - not 369 of 515/71%); one was WORSE than reported (see #1);
and its central thesis is correct: sixteen stacked regexes were approximating a semantic
judgment, which is why every recent fix relocated the failure instead of closing it.

**1. ANSWER AND EVIDENCE WERE DECIDED BY DIFFERENT RULES - and it is live on the client's
package, contrary to my own note.** `candidate_counts` picks the value by MAJORITY VOTE
across chunks; `all_question_grounding` was LAST-WRITE-WINS. I had been asserting this
document never splits; `_GAP_FILL_DOC_CHARS_PER_CALL` is 112,000 and the package is 683,601
chars, so the raw walk runs **7 chunks with rescan auto-on** - a "Yes" can win the vote and
inherit the citation from the chunk that answered "No", and that citation is what the gate
judges and what the Explanation box PRINTS (the raw-quote overwrite at the KEPT_YES site is
finding #2, and this is its worst source). Fixed with `grounding_by_value[field][value]`
threaded through `_absorb` / both batch runners / `_merge` / the compliance absorber, and
the winner collects its own citation at selection time (`EVIDENCE_REBOUND` log). The
outward contract `question_grounding: {field: quote}` is byte-identical, so no consumer
changed. Pure plumbing, no model involvement.

**2. THE "No" TEST WAS INVERTED IN BOTH DIRECTIONS.** `_NEGATION_CUE_RE` contained bare
`no|free|clear|clean`: **4 of 4** dec-page identifier lines were admitted as proof of a
"No" (`Policy No. BBC7263`, `FEIN No. 84-2210987`, `toll free`, `free-standing`), while
**3 of 3** genuine implied denials were rejected ("All vehicles are owned by the
applicant"). The code already knew "no" abbreviates NUMBER - `_COVERAGE_DENIAL_RE`'s
comment says so and keeps the broad cue off the Yes side - it was never applied here.
`_strip_number_abbreviations` now removes it on two positive-evidence shapes only
("No."/"No:" + a digit-bearing token, or a preceded identifier label), so an ALL-CAPS
"THE APPLICANT HAS NO PRIOR CANCELLATIONS" is untouched. **My first cut used `re.I` on a
`[A-Z0-9]` lookahead - which makes it match lowercase - and blanked exactly that sentence;
the suite caught it in one run.** Over-firing on affirmative quotes fell 7/10 -> 3/10 and
`test_yes_polarity_gate`'s measurement was updated to the new number rather than deleted.

**3. THE 12-CHAR GROUNDING FLOOR SAT ABOVE REAL EVIDENCE.** "Direct Bill" normalizes to 10
characters, so the phrase this package prints on all four section dec pages **could never
ground anything, ever** - which is how the box shipped "No" against four printed DIRECT
BILLs before C70's fact backfill worked around it. Lowered to 6: still no fragments, no
longer excluding short printed VALUES, which is what a dec page states.

**4. STAGE A CITED THE INDEX IT WAS HANDED.** `_render_dec_index` builds `"Label: value
[owner]"` lines that exist in OUR prompt, not verbatim in the document, and the gate then
verified quotes against the raw document only - so a model that correctly cited what it was
given was blanked, with **no second chance** (Stage A removes answered fields from Stage B).
`_evidence_hay` now includes the rendered index. **This is not a relaxation:** every entry
already passed `_verify_dec_entries`' literal-presence check, so it admits nothing the
document does not print - only in the shape the model was shown.

**5. THE SEMANTIC JUDGE (`_judge_evidence_batch`) - the one thing regex cannot do.** One
batched call per form: *does this quote support this answer to this question?* It reviews
BOTH directions - rejecting a kept answer whose evidence does not support it, and rescuing a
"No" blanked only because a genuine implied denial carried no negation word. **Three safety
properties:** silence is never a verdict (an id the judge does not return keeps its
deterministic decision, so no API key / a 429 / a malformed reply / every offline test is a
strict no-op - which is why 2,647 tests pass unchanged); only fields that already have an
answer AND a quote are queued, capped at `EVIDENCE_JUDGE_MAX_FIELDS` (400) and batched 20;
and it reads **no document text**, so the calls are small. Cost: ~5-15 calls per package at
~1-2k input tokens each, roughly **+$0.01-0.02 per package** - the first deliberate cost
increase in this file, bought against the defect class that has consumed four runs. Kill
switch `EVIDENCE_JUDGE=0`. **The gap-fill and compliance prompts are untouched; inspector
PASS, prefix stable.**

**6. COVERAGE-EXISTENCE BOXES WERE UNEVIDENCEABLE BY CONSTRUCTION.** For "is Commercial
Auto on this policy?" the only possible proof is a printed dec line - and dec lines are
rejected as Yes evidence for every field. Narrow exemption by field NAME
(`Policy_LineOfBusiness_*`) so every EXPOSURE question keeps the full artifact rule; the
mention-versus-grant distinction is intact, and `_COVERAGE_DENIAL_RE` still stops
"Property - No Coverage" ticking Property.

**Reported, deliberately NOT changed:** the reuse-cap clustering iterates a `set` (real
nondeterminism, but the cap is now generous at 12 and the judge is the real arbiter);
and the 1,384-field routing split between the general prompt and the compliance gate -
rule 8 of `_PROMPT_SKELETON` already asks every checkbox for grounding, and the judge is
uniform across both, so re-routing 1,384 fields is blast radius without a measured gain.
Both stay on the open list rather than being half-fixed.

Tests: `tests/test_evidence_binding_and_judge.py` (27). Suite **2647 passed / 2 failed** -
the same two pre-existing unrelated failures, zero regressions.

### C73 — run 4 of 2026-08-14: every C72 fix verified on paper; the last standing defect (nameplate-as-evidence) closed via the index, NO LLM change

**Verified working on run 4's PDF:** clean page-1 address split (line1/city separated, the
_parse_address fix), PAYMENT PLAN empty (the resolver), genuine GL classifications in the
operations box (the coverage-meta demotion), one premises row, empty Additional Interest,
Direct Bill + method intact, and only the genuinely-true expired-term warning. Index: 278
raw twice in a row, content matching the ground-truth fixture including sub-limit captions.

**The one defect run 4 shipped: Q3 (flammables) = Y and Q6 (abuse/molestation claims) = Y,
both "explained" by "BUSINESS DESC: COMMERCIAL GENERAL CONTRA".** Root cause traced in the
session's own data, and it is a two-layer story: (1) the Yes rode the EXPLANATION path (a
Yes survives on a paired explanation, so the quote checks and the Yes-reuse cap never
decide alone); (2) the explanation artifact check's colon escape already knew this literal
string - `_is_labelled_fact_echo` tests FACT equality, and this run's `contractor_type`
merged to the EXPANDED "Commercial General Contractor" instead of the truncated header.
Fact jitter blinded a fact-keyed guard.

**Fix: `_is_applicant_attribute_echo`, keyed on the INDEX as well as the facts.** An entry
the extraction attributed to the APPLICANT (name, address, entity, business description) is
an identity attribute - who the applicant IS can never evidence that an event HAPPENED.
Equality-only with an 8-char floor, so "INSURED IS: LLC" stays pinned-legitimate short
evidence; wired into `_is_coverage_artifact_text` and its colon escape, which the quote
check AND the explanation pre-blank both consult. Replayed on run 4's live session: both
the full string and the bare tail now register as artifacts, and the end-to-end test drives
the literal two-question shape through the real gate to blank on both. No topic matching -
identity of the text against the applicant's own recorded attributes, nothing else.

### C72 — run 3 of 2026-08-14: locations/interest/payroll-warning fixes verified WORKING; the three remaining defects closed at rule level (one extraction-schema key added)

**Verified working on run 3:** ONE premises row, correctly decomposed (the C71 deadlock fix);
the Additional Interest block EMPTY (the index-owner borrow pool); the GL payroll warning
stood down (correctly - the document states a payroll basis, so only the genuinely-true
expired-term stop remains); index labels carrying real captions (the C71 caption rule -
'Deductible'/'Coinsurance'/'Catastrophe Limit' instead of a row id repeated).

**1. DESCRIPTION OF PRIMARY OPERATIONS held the POLICY's own coverage summary** ("...
equipment coverage and installation floater coverage are described, including coverage
for ...") - run-to-run jitter let the coverage-meta candidate out-score the genuine GL
classification text this run. Fix: `_COVERAGE_META_RE` demotion in the narrative merge,
the same demote-never-discard shape as the C45 fragment rule one block above it: a
candidate whose grammatical subject is the coverage/policy itself may not win a narrative
fact while a genuine candidate exists, and with no rival it still stamps (never blanks).

**2. The page-1 mailing street box printed "4800 Dahlia St # D13 Denver CO 80216-3121"
with the city/zip boxes ALSO filled.** Dec pages print addresses as one comma-free run and
`_parse_address` split only on commas - the fused line1 fed every `_addr_*`/`_loc_*`
component and the producer resolver alike. Fix at the parser, structure-anchored, never
guessed: a trailing "ST 12345" is extracted only when the 2-letter token and the ZIP
corroborate each other via `_state_from_zip` ("AVE NW 20500" stays put - NW is not what
20500 implies), and the city is split out only when a UNIT designator anchors the street's
end ("# D13 DENVER", "STE 400 ENGLEWOOD"); no unit anchor, no attempt. Fixes named
insured, producer, cert holder, additional interest and location components in one place.

**3. PAYMENT PLAN = "AN" on every run - closed for good.** The code is invented from
"Audit Period: Annual" (the GL's AUDIT term); a CODE abbreviates a printed word, so no
verbatim gate can ever see the invention. `_resolve_payment_schedule` joins the
authoritative-blank family (same shape as the deposit and fax boxes): stamps from the new
`payment_plan` extraction key when a document genuinely prints one, otherwise the box
stays EMPTY for the producer. **One extraction-schema key added** (`payment_plan`, beside
`billing_plan`) - constant per run, prefix intact, inspector PASS.

**Answered, no change needed:** run 3's single warning is CORRECT - the payroll warning
was the false alarm (C71 fix working), the expired-term stop is true. Entry-count jitter
(278 vs 221 vs 353 raw) is 13 independent calls at nonzero temperature; the systematic
half was the C71 label collapse, now fixed - judge the index by which VALUES it carries,
not the count. Tests: `tests/test_run_20260814c_fixes.py` (12) + the resolver registered
in `test_authoritative_blank_contract`.

### C71 — run 2 of 2026-08-14: three C70 fixes verified WORKING, two defects returned through OTHER doors, both closed at the root; one index-prompt regression owned and fixed

**Verified working on the fresh run:** Direct Bill ticked + METHOD OF PAYMENT = "DIRECT BILL"
(the C70 billing backfill firing live), the invented 100% installation split GONE
(quote-gated percentage guard), heading verbatim-copying (the letter-spaced
"D R I V E O T H E R C A R" heading survived verification), and the split GL table cells
recorded ('Prem Basis'='Payroll', 'Exposure'='$39,300', class codes with classifications).

**1. The tripled premises returned through Pass 1 - a THREE-VARIANT DEADLOCK in the C48
consolidator, found by replaying the live session's own facts.** The fold loop's "exactly one
host" ambiguity rule deadlocks when one premises prints in 3+ chained shapes ('...st d13' /
'...st d13 denver' / '...st d13 denver co 80216'): every key sees TWO hosts, nothing folds,
three rows stamp. Fixed: multiple hosts fold when they are pairwise the SAME premises
(mutually fold-related), into the longest. Fixing that exposed a PRE-EXISTING reverse hole
the new test caught immediately: when the more-specific shape found the bare fragment as its
single host, it absorbed a fragment that a DIFFERENT premises ('...d13 boulder') could claim
equally - so the fold now also requires no un-related third claimant on the pair's shorter
member. Replayed on the live session's verbatim facts: 3 rows -> **1 row, correctly
decomposed** (street / DENVER / CO / zip each in its own box). The stamp-time dedupe guard is
now SOURCE-AGNOSTIC as belt (its gpt-only first cut is what let Pass 1 walk through - and
"corrects values from any source" was the guards' charter all along).

**2. The fabricated Additional Interest returned wearing different clothes** - FullName =
"Persons Or Organizations With Whom You Have Agreed In A Written Contract Or Agreement"
(endorsement wording), the applicant's city/zip (allowed by design), and the SERVICING
CARRIER's phone - a number no ACORD 125 field stamps, so C70's form-side borrow pool was
blind to it. Fix: the borrow pool now also holds every verified dec-entry VALUE owned by
producer/carrier (the index records "SERVICING CARRIER: (720)200-3700" with its owner), and
that alone kills both live fabrications. **A name-witness rule ("the FullName must appear in
the index") was tried and REMOVED the same day**: the suite caught it blanking 'Meridian
Fleet Leasing, LLC' - the 2026-08-13 contract protects a third party named in document
PROSE, which is exactly what the index never records. A name-only fabrication with zero
borrowed details stays the accepted residual rather than a reason to blank named parties.

**3. "GL coverage detected but no revenue or payroll found" was firing against a printed
payroll basis.** The 2026-08-12 backfill ('PAYROLL'='$39,300' -> total_payroll) went blind
when C70's per-cell rule split the pair into 'Prem Basis'='Payroll' + 'Exposure'='$39,300'.
`_dec_entries_state_payroll` now answers the warning's own question from the verified index -
a payroll-labelled entry with a figure, or a basis entry whose value IS "payroll" - and the
warning stands down. Presence check only; no fact, no form field written.

**4. Owned regression: the per-cell index rule collapsed the IM schedule 80 -> 26 entries.**
The model labelled a dozen sub-limits 'CONTRACTORS EQUIPMENT 801' each; identical
(label,value,section) triples deduped away and distinct sub-coverages became
indistinguishable. Rule 5 now requires the label to carry the printed CAPTION (column
heading / coverage name), never a shared row id alone - 'CATASTROPHE LIMIT' and 'JOBSITE
LIMIT' are two labels - and names the basis-word case ('Payroll $39,300' = label+value, not
two entries). Run-to-run entry-count jitter (13 independent calls at nonzero temperature)
accounts for the rest of 344 -> 195; the prompt fix targets the systematic half.

**Reported, deliberately NOT keyword-patched:** Q3 flammables answered "Y" on the ISO
pollutant definition ("fumes, smoke, soot, vapor, and waste") and two borrowed "N"s (Q9/Q11).
That is the documented borrowed-quote residual of the evidence gate - detecting it needs
quote-topic matching, which three prior sessions proved causes worse regressions. Also
still open: PAYMENT PLAN "AN" (C70's known residual).

### C70 — four wrong-value clusters from the verified ORBIN run, closed at rule level (2026-08-14, second batch), one gap-fill prompt clause + one index-prompt clause, all guards deterministic

**The run behind this was VERIFIED against the ground-truth fixture, not eyeballed** (session
f26d8685; form values read back from `generated_forms`, the index from the per-doc copies).
Four defect clusters shipped to the PDF; each is now closed by a RULE with the live values
pinned in `tests/test_run_20260814b_form_fixes.py` (20 tests):

**1. A fabricated Additional Interest, half-killed and half-shipped.** FullName "Blanket
Additional Insureds" (a GL endorsement TITLE), city/zip/phone the PRODUCER's, email the
carrier's claims address, account number the GL policy number. Existing guards blanked 22 of
the row's fields and left these six. Fix: `_drop_fabricated_interest_rows` - an interest row
dies WHOLE when it has no FullName or when ANY identifying detail (line1/line2/city/zip/
phone/email, suffix-matched) is byte-equal normalized to a value stamped for the producer or
carrier. Sharing the APPLICANT's address is deliberately NOT a signal (a landlord at the
insured premises is legitimate). Only model-authored fields are touchable. No topics, no
keywords - value-equality against the other parties' own stamped fields.

**2. Direct Bill stamped "No" against four printed DIRECT BILLs.** `billing_plan` merged
empty because the phrase only prints FUSED into label runs ("DIRECT BILL AGENT PHONE: ...")
- the model never returned the fact, and the entry-backfill's label-match condition correctly
refused the fused entries. The empty fact fell to gap fill, which answered "No" from nothing.
Fix: `_backfill_billing_plan` in merge_facts - ACORD's billing method is a TWO-VALUE closed
vocabulary (direct/agency bill), the one raw-text scan shape this codebase allows itself
(same argument as `_LOB_NAMES`; word-bounded so "direct billing disputes" prose cannot
match). Fills only an EMPTY fact, only when exactly ONE method is printed. Plus
`Policy_PaymentMethod_MethodDescription -> billing_plan` in `_ACORD_FIELD_RULES`, so Pass 1
owns the METHOD OF PAYMENT box - the run had stamped the umbrella's audit note there.

**3. The percentage guard was document-wide and a live run defeated it.** The invented
INSTALLATION 100% survived because *some* unrelated page prints a "100%"; its invented 0%
sibling died only because the package happens never to print one. Anywhere-in-271-pages is
not evidence about a box. Fix: quote-gated, the same shape as the Yes/No evidence gate -
NEW rule 8d asks for a `question_grounding` quote on every percentage field, and
`_drop_unstated_percentages` now requires (a) the quote exists, (b) it is verbatim in the
document, (c) it contains this number AS a percentage. No topic matching - presence checks
only, per the standing evidence-gate design. **This is the one gap-fill PROMPT change**
(~90 words in `_PROMPT_SKELETON`, constant per run - the cached prefix stays one variant;
inspector re-run PASS). Fact-supplied percentages are untouched.

**4. One premises stamped as three location rows** ("4800 Dahlia St # D13 Denver" / a
street-less "Denver 80216-3121" fragment / "4800 Dahlia St D13 Denver"), one an orphan
whose street an earlier guard had blanked while leaving its city/zip. The C48 consolidator
folds these in FACTS; these rows were authored by gap fill, which bypasses it. Fix:
`_dedupe_stamped_premises_rows` - same folding rules at stamp time (normalized street
equality/prefix with zip agreement; street-less fragments fold on zip match), and a folded
row dies WHOLE including its description. **Scoped by NAME to
`CommercialStructure_PhysicalAddress`, deliberately not generic: the obvious generalization
is exactly C18** (three trucks garaged in one city legitimately print identical
Vehicle_PhysicalAddress rows), pinned by `test_garaging_rows_are_never_touched_c18_safety`.

**Also: the index prompt** now names the numeric table columns (rate, factor, exposure,
cost new, per-row premium - the run's remaining index misses) and forbids paraphrased
section headings (the model's own "COMMERCIAL UMBRELLA DECLARATIONS" rewording cost 17
entries their C23 attribution).

**Known, deliberately left:** `Policy_Payment_PaymentScheduleCode` "AN" (likely borrowed
from the GL's "Audit Period: Annual") has no clean deterministic rule yet - a code is an
abbreviation of a printed word, so verbatim checks cannot see it. Logged, not guessed at.

### C69 — the index must be COMPLETE: the cap, the gate, and the fusion, all three recall leaks closed (2026-08-14), prompt edit + routing change, cost = up to (dec-dense chunks − 8) extra index calls on pathological spreads

**The owner's requirement, verbatim: "i want full coverage" — the index is Stage A's whole
world, so anything it silently lacks is a value Stage A cannot stamp.** The 259-entry live
run (session 5d4e0cdd, vs ~750 printed entries on the ORBIN package) had ONE dominant cause —
the wrapper bug already fixed under C68, the run predated the fix — but tracing it surfaced
three GENUINE recall leaks that would have survived the restart. All three closed:

**1. `_DEC_INDEX_MAX_CHUNKS` defaulted to 8 and trimmed silently.** A package whose
declarations spread across more than 8 chunks lost the dedicated pass on the excess — no log
line, no way to know. Now **0 = uncapped by default**: every chunk clearing
`_DEC_INDEX_MIN_AUTHORITY` (0.25) is indexed. The authority gate IS the cost boundary (0.75
measured on a real dec page vs 0.00 on wording), and an upload is already bounded by
`MAX_UPLOAD_SIZE_MB`. Worst case on ORBIN: 14 index calls instead of 8 if every chunk were
dec-dense — it is not; the real package routes a handful. An env cap >0 remains as an
emergency valve and now **WARNS with exactly what it trimmed**.

**2. The verbatim gate was deleting real TABLE rows.** Live drops, logged: the ENTIRE GL
class table (`'Location 001' = '91580 Contractors - Executive Supervisors...'`) and every
`'Section N <part>' = 'No Coverage'` summary line — DROPPED_UNVERIFIED. Not fabrications: the
model joined two printed CELLS, OCR interleaves the neighbouring columns between them, so the
joined string is contiguous nowhere. Fix is `_entry_is_printed`: verbatim, OR ordered
containment within `_SECTION_TOKEN_GAP` (80 chars) per adjacent token — the SAME relaxation
`_section_is_printed` shipped 2026-08-13, via one shared engine (`_tokens_printed_in_order`)
so the two can never drift. **Numbers get no latitude**: digit tokens are always required,
and a text whose significant tokens are ALL digits never takes the relaxed path — a
reformatted `1000000`, a date rewritten `07/16/25 → 07/16/2025`, a re-grouped phone all stay
DROPPED, because a number failing the verbatim test is the exact fabrication the gate exists
to stop. Deterministic, zero LLM cost.

**3. The fusion is now also forbidden at the SOURCE.** Both recording prompts (the dedicated
pass rule 5, and the main-schema `dec_page_entries` instruction) now say: one entry PER
printed cell, label = column heading + row identifier, NEVER concatenate two cells. ~50 words
on each; the dedicated prompt is per-run constant, and the main-schema edit shifts the cached
prefix once (same class of edit as every schema change — constant within a run, cache
unaffected where it matters).

**Also: `_DEC_ENTRY_MAX` truncation can no longer be silent** — hitting the 1200 cap with
candidates still unprocessed logs a WARNING naming the loss (raise `DEC_ENTRY_MAX` and
`GAP_FILL_DEC_INDEX_BUDGET_MULT` together — see `_dec_index_chunks` for why they are coupled).

**Explicitly NOT changed:** Stage A→B in `pdf_service` (already correct: index first, every
field the index cannot answer walks the FULL raw document — pinned by the I2 invariant), the
facts/flags schema (byte-identical), `_verify_dec_entries`'s dedup and owner logic, and
`_section_is_printed`'s own semantics. Tests: +9 in `test_dec_index_dedicated_pass.py`
(fused row survives, two-column No Coverage survives, reformatted amount/date still dropped,
scattered words still dropped, uncapped default, env valve, prompt pins).

### C68 — a DEDICATED declarations-index call, two root causes, and the one stop nothing was making (2026-08-14), **+1 LLM stage**, cost bounded by routing

**THE INDEX CALL — the only LLM change in this arc, and the first one in a week.**
`dec_page_entries` was one key among ~170 in the main extraction schema, and the model budgets
its answer across all of them: ~19 entries per chunk against a 150 allowance and a
16,000-token output cap, **neither binding**. 250 entries recorded from ~30 declarations pages
carrying an estimated ~750. That index is what Stage A of LLM call 2 reads first, so a thin
index is a direct loss of fill quality - and it is the mechanism behind a defect that returned
five times ("Limited Pollution Coverage - Work Sites $150"): a guard keyed off the index is
blind to whatever the index never recorded.

Attention is the constraint, so the fix is **separation, not a bigger cap or a louder
instruction**. `_harvest_dec_index` runs one prompt with one job - enumerate every label:value
printed here - with no facts, no flags, no coverage judgments.

**Cost is bounded by ROUTING rather than by trimming the ask.** Only chunks whose
`declarations_authority` clears `_DEC_INDEX_MIN_AUTHORITY` (0.25) are sent - the same scorer
the retrieval filter already trusts, measured at **0.75 on a real dec page against 0.00 on
policy wording**. `_DEC_INDEX_MAX_CHUNKS` (8) caps a pathological package — **superseded by
C69 the same day: uncapped by default, the cap is now an opt-in env valve that warns when it
trims**. A package of pure wording costs **zero extra calls**, which is pinned by test.

**Nothing else moved.** The main extraction prompt is byte-identical, so LLM call 1's cached
prefix survives; entries are merged ADDITIVELY (`_verify_dec_entries` dedupes on
label+value+section, so an entry both passes found costs nothing and one only the main pass
saw is never lost); every entry still faces the unchanged verbatim gate, so this buys RECALL,
never trust. Inspector re-run: **PASS, prefix stable, gap fill $0.0650 unchanged.** Kill
switch `DEC_INDEX_DEDICATED_PASS=0`.

**TWO ROOT CAUSES, stated once by RULE instead of once per box** - the owner's explicit ask
("we cannot pinpoint things for all the forms"):

1. **A PERCENTAGE needs a source.** Live ACORD 125: "INSTALLATION 100%" and "OFF PREMISES
   100%", neither supported by anything in 271 pages; earlier runs produced "RETAIL 100%" and
   "% owned 50%". Measured first: ACORD declares "Enter percentage:" on **74 fields across 8
   forms** and **zero are fillable from any fact**, so every percentage we print was blank or
   a guess. The FIRST CUT was an authoritative blank and the suite rejected it correctly -
   `test_a_percentage_the_document_states_survives` plants a "15%" the document really does
   state, and closing the box threw it away. The measurement was right about FACTS and forgot
   the other legitimate source. Shipped as a guard instead: a percentage stamps from a fact
   (Pass 1, untouched) or when the document prints that number **as a percentage**. "100" as a
   radius of use is not evidence that 100% of work is off premises.
2. **A ROW about a party who is not on the form.** "DESCRIPTION OF OPERATIONS OF OTHER NAMED
   INSUREDS" held "COMMERCIAL GENERAL CONTRA" on a package with ONE insured. ACORD's own
   tooltip says what row B is - *"As used here, this is the description of operations for
   other named insureds"* - so the anchor is `NamedInsured_FullName_B`, a DIFFERENT field
   family, which is why the existing same-family unanchored-row sweep could not see it. Also a
   guard rather than a resolver, because the anchor is the STAMPED name: the first cut checked
   a fact and blanked a genuinely different row-B narrative whose second insured arrived by
   another route.

**THE ONE GENUINELY MISSING STOP.** Asked honestly what a dec-page package can be checked for
that nothing checks. Every date rule looks at the EFFECTIVE date - format, two years past, two
years future - and `validate_date_range` only asks whether effective precedes expiration.
**Nothing compared the EXPIRATION date to today.** So the client's own package, term
07/15/2025-07/15/2026, sailed through on 2026-08-14 with both dates printed under "PROPOSED
EFF/EXP DATE". `validate_policy_term_not_expired` is deliberately HARD: an expired term is not
a quality problem an underwriter can weigh, it is an application for a period that does not
exist. 30-day grace, so a renewal prepared at expiry is a warning.

Two things that had to be fixed alongside it, both anti-rot doing its job: the message needed
a `_LEGACY_MESSAGE_RULES` row (an unclassified legacy message reaches the user with no cluster
and no Resolve action), and the append had to be written as plain `hard.append` /
`soft.append` because `test_legacy_rules.py` harvests this function by walking its AST and a
`(hard if x else soft).append(...)` is invisible to it.

Also corrected: `test_the_kill_switch_exists_and_defaults_on` asserted the RUNTIME value of
the dec-index purge, so it failed the moment anyone set `PURGE_DEC_INDEX_AFTER_GENERATION=0` -
which is the documented way to inspect the index on a live run. It now tests the default.

Tests: `backend/tests/test_dec_index_dedicated_pass.py` (19). Suite **2563 passed / 2 failed**
- the same two pre-existing, zero regressions.

### C67 — the ACORD 125 scored clean, and the one blank box exposed a three-way Pass-1 split (2026-08-14), NO LLM change, cost ZERO

**C66 confirmed on the live form.** NAIC blank on both accounts, STATUS OF TRANSACTION blank,
Q3 flammables blank (the "Limited Pollution Coverage - Work Sites $150." explanation gone),
TOTAL LOSSES no longer $0. Scored against `tests/fixtures/orbin_ground_truth.json`:
**14 of 14 assertions correct, 13 of 14 applicable traps beaten** - the $10,663 total over five
decoys, the applicant phone blank over three real phone numbers, all four line premiums, one
location folded from three print variants, four real policy numbers with no invented
composite, and no boilerplate anywhere.

**The one real defect was a blank box, and it was mine from the day before.** ACORD 125's
per-premises DESCRIPTION OF OPERATIONS shipped EMPTY - one day after a rule was added
specifically to fill it from `operations_description`. The rule worked perfectly in
`_deterministic_map` and did nothing in the two functions that actually build a form:
`compute_form_gaps` and `map_facts_to_form` both call `_resolve_schedule_row` FIRST and
`continue` on its answer, so Pass 1 is never consulted for a schedule-backed field.

**The trap is what `None` means at row A.** The comment on `_deterministic_map`'s fallback
claims row A answers None "if and only if the schedule's list is COMPLETELY EMPTY". That is
false, and this package proves it: `property_locations` has ONE entry which carries no
`operations_description` key, so row A answers None with a non-empty list. The scalar fact was
sitting in `facts` the whole time and was never asked for. Same class as the defect
`compute_form_gaps`' own docstring already records - *"the docstring claimed this function
'mirrors exactly'"*.

Fixed by mirroring the row-A scalar fallback into both call sites. **Deliberately does not add
to `unmatched`**: an empty schedule cell with no scalar rule stays a deterministic blank, so
this buys a value and never an extra gap-fill question. A genuine per-location description
still wins over the package-level fact, and rows B+ stay blank.

**Also corrected: two values I wrongly called invented.** An earlier audit flagged PAYMENT
PLAN "AN" and AUDIT "A" as two-letter fragments. They are ACORD's own codes - the tooltip on
`Policy_Payment_PaymentScheduleCode_A` reads *"AN - Annual, MO - Monthly, QT - Quarterly"* -
and the dec page states "Audit Period Annual". Both correct, now pinned by test so nobody
"fixes" them.

Remaining misses on the 125, all data-present-box-blank rather than wrong: the GL CODE box
(91580/91585 are on page 211), the COUNTY cell, and the line-of-business label beside the
Inland Marine policy number in Q4.

Tests: `backend/tests/test_schedule_row_a_fallback_parity.py` (7), including an anti-rot check
that BOTH schedule call sites still carry the fallback - a refactor dropping either one
reintroduces a defect invisible to `_deterministic_map`'s own tests. Suite **2540 passed / 2
failed** - the same two pre-existing, zero regressions. **No LLM call added, removed or
reprompted.**

### C66 — the same document through two accounts produced two different forms (2026-08-13), NO LLM change, cost ZERO

**The most useful bug report of the arc, because it is a PROOF, not an observation.** The
owner ran one declarations package through two accounts and diffed the ACORD 125s. Two boxes
disagreed: **NAIC CODE was 25321 on one and blank on the other** (and 26247 on an earlier run
of the same document), and **ISSUE POLICY was ticked on one and blank on the other**.

A document cannot produce two answers to the same question. Divergence across accounts is not
model jitter to be tuned down - it is proof that the box was never answerable from the
document and that whatever filled it was guessing. Both closed at the source:

1. **`_drop_mislabeled_naic_codes` had a hole from the day it was written.** It asked "is this
   number labelled for the wrong entity?" and never "is this number in the document at all?".
   A value appearing NOWHERE set neither flag and sailed through - which is exactly how one
   document yielded three different NAIC codes. A NAIC is a copied identifier the pipeline
   never reformats (it is already in `_GROUNDING_MUST_APPEAR` for that reason), so literal
   absence is proof rather than a heuristic. The original mislabel check is untouched and
   pinned.
2. **STATUS OF TRANSACTION is now owned as a family** (`_resolve_policy_status`, 3 → 10 fields
   on ACORD 125). It previously returned `_SCHED_SKIP` for anything but a known renewal,
   leaving the family unowned and handing it back to gap fill. The boxes say what THIS
   SUBMISSION is - quote, issue, renew, change, cancel - which the producer decides when they
   send it; a bound policy's dec page has no opinion. Same category as "section attached" and
   REMARKS. A known renewal still ticks RENEW and only RENEW.

**The Q3 defect, fifth appearance, and this time the mechanism is named.** ACORD 125 "ANY
EXPOSURE TO FLAMMABLES, EXPLOSIVES, CHEMICALS?" = Y, explained by "Limited Pollution Coverage
- Work Sites $150." That value HAS been caught before - but only by `_is_dec_coverage_line`,
which is exact membership in the verified dec index, and that index captured ~250 of an
estimated ~750 entries on this package. **A guard that fires only when an upstream sampling
step got lucky is not a guard.** `_is_priced_coverage_line` reads the shape instead - a short
noun phrase terminated by a bare money amount with no verb - so it holds with no index at
all. Three guards keep a real sentence out: any auxiliary verb disqualifies, >12 words
disqualifies, and the amount must be last. Verified both directions including "The deductible
for each pollution incident is $1,000" and "The applicant paid $5,000 to settle a claim".

**The review screen was also its own problem.** The client's run rendered *"ACORD 125: 131
fields left blank on purpose - a value was found for each but could not be true for that
box"*. Only the first clause was true: almost all 131 were cells cleared **because their row
lost its anchor**, not 131 separate judgements, and 131 rows of it buries the three that need
a human. Cascade blanks are now tracked (`_cascade_blanked`) and excluded from the advisory
row - still blanked, still logged as a count, no longer reported as individual findings. Also
fixed: field QA raised *"auto drivers row 1: license number is required but missing"* for a
package whose ground truth has NO driver schedule - it was demanding a licence for a driver
the row resolver had already, correctly, declined to print.

**One guardrail bit and was honoured rather than bumped.**
`test_ownership_check_is_scoped_to_the_named_resolvers` caps how much of a form the blank
contract may own; adding the status family pushed ACORD 125 to 113/548 (20.6%) against a 20%
ceiling. Raised to 25% **with the arithmetic written out** - 88 of the 113 are two repeating
grids (prior-coverage, applicant contact) that are answered rather than withheld - and a
SECOND assertion added that the non-grid scalar count stays under 30, derived from the owning
resolvers rather than a guessed name prefix. That is the constraint the percentage was
standing in for.

Tests: `backend/tests/test_two_account_divergence_20260813.py` (28), including a determinism
test that runs the status family three times with different model guesses and asserts one
answer. Four existing tests were REVERSED with their reasoning recorded in place - they
pinned "let the model try" on boxes the two-account diff proved unanswerable. Suite **2533
passed / 2 failed** - the same two pre-existing, zero regressions. **No LLM call added,
removed or reprompted.**

### C65 — run 9 scored against the ground truth: five residuals closed, one refused (2026-08-13), NO LLM change, cost ZERO

**The first audit graded against the real document rather than against my own claims.**
`tests/fixtures/orbin_ground_truth.json` was built by reading all 271 pages by hand; run 9's
three PDFs were scored field-by-field against it. Result: **14 of 14 scored assertions
correct, and 9 of the 15 known traps beaten** — including the $10,663 total against five
decoys, the six GL limits against the umbrella's $3,000,000 sixty-two pages away, the
applicant phone against three real phone numbers, the IL0017 boilerplate that scores 2.3x the
real total on frequency, and the CA 8282 blank-form trap's $50,000. Five traps failed; four
are now closed:

1. **ERIN ROYAL printed as the sole ACORD 127 driver.** The fixture is explicit: no driver
   schedule exists, and that name is the individual on a CA 99 10 DRIVE OTHER CAR endorsement
   (page 92), the only personal name in 180 pages. `_schedule_has_substance` had ALREADY ruled
   the record "not a schedule" and logged it — the attachment box and the evidence gate both
   honoured that — but `_resolve_schedule_row` never asked, so the name stamped and dragged
   the APPLICANT'S address in beside it. **Scoped to driver schedules by
   `_NAME_ONLY_INVALID_SCHEDULES`**: a name-only additional named insured is a supported
   shape, and blanking those broke five tests when tried before. The first cut here was
   unscoped and broke `test_second_named_insured_stamps_from_the_extraction_fact` — caught,
   narrowed, pinned by a test that asserts the frozenset's exact contents.
2. **A THIRD schedule-of-hazards row** — row 1's code, basis and exposure with an invented
   territory — against a package with exactly two class codes. Same disease as C46's phantom
   vehicle rows, one form over: a row past the end of the schedule returned `"UNMATCHED"`,
   which hands the whole row to gap fill, and gap fill asked about a classification that does
   not exist copies the nearest one. Now an authoritative blank, **on positive evidence only**
   — no schedule at all still reaches the model.
3. **MAXIMUM DOLLAR VALUE SUBJECT TO LOSS = $1,000,000**, the Auto liability limit, in a box
   whose ACORD tooltip says "the highest value that the insurer would be subject to if a major
   automobile loss occurred". That is a property-damage exposure; the one vehicle is worth
   $26,680. `_resolve_max_vehicle_exposure` derives it from the schedule's cost-new figures or
   leaves it blank.
4. **"# FULL-TIME STAFF 1 / # PART-TIME STAFF 0"** on the 126, invented — while the ACORD
   125's identical boxes were correctly blank, which is the tell: two boxes asking the same
   question, one honest and one invented, because only one had an owning resolver. Scoped to
   `Contractors_*` after the first cut broke three pinned ACORD 125 behaviours.
5. **Q7 hazmat = Y, evidenced by "BUSINESS DESC: COMMERCIAL GENERAL CONTRA".** `_DATA_PAYLOAD_RE`
   exempts anything shaped `LABEL: value` from the assertion test, because "INSURED IS: LLC"
   and "Date of Issue: 07/16/2025" are legitimate evidence. The truncated business description
   wore a label and read as data. The label is not the evidence — the VALUE is — so a short
   leading label is now stripped and the remainder judged on its own; `_is_labelled_fact_echo`
   catches a line restating a scalar fact we already hold. Reached ONLY from the colon path:
   a bare fact value is a legitimate answer elsewhere.

**REFUSED, and this is the entry's most important line.** Run 9 also duplicated three values
across vehicle columns (CLASS→SIC, TERR→FARTHEST ZONE, SYM→NET VEH DR/CR). A "two columns must
not share a value" guard was built, tested, and **removed before shipping**: the fixture
confirms `Vehicle_ComprehensiveSymbolCode` and `Vehicle_CollisionSymbolCode` are BOTH
legitimately "07" on this package, and they are structurally indistinguishable by field name
from `RateClassCode` vs `SpecialIndustryClassCode`. Neither side is deterministic — no
`_SCHEDULE_REGISTRY` entry binds these columns — so there is no trustworthy witness and no
honest way to choose which duplicate dies. Blanking a covered-auto symbol is a coverage
misstatement; a wrong industry class is a figure the underwriter re-rates. The reasoning sits
in the code where the guard would have gone, and
`test_the_comprehensive_and_collision_symbols_may_legitimately_agree` fails the build if
someone deletes it.

Tests: `backend/tests/test_run_20260813i.py` (24), scored against the fixture and asserting the
fixture still says what they assume. Suite **2505 passed / 2 failed** — the same two
pre-existing, zero regressions. **No LLM call added, removed or reprompted.**

### C64 — run 9: a plural noun is not a verb, and a coverage line is not a product (2026-08-13), NO LLM change, cost ZERO

Run 9 (the three forms sent with the client's audit document) confirmed C63's guards fired —
the LIAB-I rating factor, the Q14 conviction junk, the fax, the deposit, the FEIN and the
prior-carrier spray are all gone — and exposed the next layer down. Five doors, all closed
deterministically, all with the client's verbatim values pinned in
`backend/tests/test_run_20260813h.py` (47 tests):

1. **THE FAKE-VERB HOLE, the big one.** `_quote_asserts_something`'s fallback read ANY
   ≥3-letter word ending in ed/es/s as a predicate — so every plural noun was a verb and
   every printed TITLE passed as a "statement": Q8 = Y off "WAIVER OF TRANSFER OF **RIGHTS**
   OF RECOVERY", Q9/Q10 = Y off "**NAMES** OF INDIVIDUALS ERIN ROYAL", 126 Q9 = Y off
   "J. BLANKET ADDITIONAL **INSUREDS**". The separation that holds is POSITION, not
   vocabulary: a finite verb sits between subject and object ("the applicant TRANSPORTS
   hazardous materials"); a title-noun hangs off an of/and/or chain or dangles at the end.
   Suffix-derived candidates now count only when not adjacent to of/and/or and not final;
   explicit auxiliaries are untouched. Every pinned genuine s-verb statement still asserts.
2. **QUOTED PRONOUNS.** ISO forms print defined terms in quotes — `"We" do not cover
   property that "you" lease or rent to others.` — and the quote characters defeated every
   \b-anchored contract-voice pattern. A quoted party term is now itself the register
   signature, and the regexes also run on a de-quoted copy. `_POLICY_SELF_SUBJECT_RE` gained
   "the following" and "may be <verb>" for the forms-revision advisory ("The following forms
   may be newly introduced to the policy: BROADENINGS OF COVERAGE" — offered as proof of
   hold-harmless agreements).
3. **THE APPLICANT'S OWN ADDRESS as evidence** (126 Q7 parking = the premises address,
   digit-payload-exempt from the assertion test). Identity is the DIGIT SKELETON — a
   verbless text whose every number appears in an applicant address fact IS that address,
   however OCR spells STREET vs ST #. A sentence containing the address keeps its verb.
4. **LOB NAMES AS DATA.** The 126 products schedule listed "Commercial Auto Liability" and
   "Commercial Inland Marine" as manufactured products, dated with the policy effective
   date. `_LOB_NAMES` is a closed vocabulary (same category as the auto-symbols table);
   the guard is field-aware — Q4's other-insurance LOB labels, loss-history LOB and every
   other legitimate home is allow-listed by name marker, swept against all 17 schemas by
   test (the sweep found `Insurer_ProductDescription`, whose tooltip asks for a line of
   business, before it could be blanked). Blanking a product NAME unanchors the row, so the
   late sweep clears the borrowed dates. Plus: a bare dollar amount in a `*Description` box
   describes nothing (run 9's "$2,000,000" in LIMIT APPLIES PER "OTHER").
5. **STRUCTURAL FABRICATIONS.** Claims-made retro dates stamped on an OCCURRENCE policy
   (both boxes = the effective date — the client's "never repurpose the effective date"
   rule made structural: `_resolve_claims_made_dates`, keyed on `gl_is_claims_made`);
   $0 TOTAL LOSSES with "Check if none" unchecked and no loss runs
   (`_resolve_loss_history_summary` — same client rule as the no-loss checkbox, applied to
   the amounts); the truncated "COMMERCIAL GENERAL CONTRA" premises box (now fills from the
   full `operations_description` fact via the existing row-A fallback — client item 16
   asked for exactly this); a Yes "explained" by the rating class description that also
   sits in this form's own Schedule of Hazards (SUPPORT_IS_A_CLASSIFICATION — value
   identity, no topic); and orphan dependents under PAIRED questions (126 Q5's equipment
   table under a blank question — the sweep skipped paired questions; it now judges their
   sibling tables while a paired Yes still stands on its explanation). `_YES_DEPS_MAX`
   14 → 20: the cap was silently excluding Q13's ~16-field sponsorship block.

Suite **2481 passed / 2 failed** — the same two pre-existing, zero regressions. **No LLM
call added, removed or reprompted; no prompt, batching or chunking touched** — every fix is
a deterministic register or possibility test.

### C63 — run 8: the policy was talking about itself, and the guards were talking to nobody (2026-08-13), NO LLM change, cost ZERO

Two findings, one code change each, and the second is the one the owner asked about four
times.

**1. Every surviving wrong "Yes" was the contract quoting itself.** The uploaded package is a
POLICY — ~271 pages of wording, endorsements and definitions, of which ~30 are declarations.
The form asks about the RISK. So for most Y/N boxes the only text available to ground an
answer is the contract describing its own operation, and every gate we had verified that a
quote EXISTS, never that it is a STATEMENT OF FACT ABOUT THIS APPLICANT:

```
Q8 "any hold harmless agreements?"        = Y
   <- "...waiver of transfer of rights of recovery against others TO US when agreed in
      writing."          (the blanket-AI / waiver-of-subrogation ENDORSEMENT)
Q9 "any vehicles used by family members?" = Y
   <- "Family member MEANS a person related TO YOU by blood, adoption, marriage or civil
      union recognized under Colorado law..."   (the Colorado Changes DEFINITIONS clause)
```

Neither was reachable by anything already built, and that is pinned by test:
`_POLICY_SELF_SUBJECT_RE` needs the sentence to OPEN with "this/such <policy noun>" and both
open with their own subject; `_quote_asserts_something` passes them because they are
grammatical sentences with finite verbs; `_is_dec_coverage_line` misses them because they are
body wording, not a printed dec label. They are well-formed English that is simply not about
the applicant.

`_is_contract_wording` is **two register tests**, and register is the right axis because it is
what separates the two documents that got merged into one text blob. **Neither compares the
quote's TOPIC to the question's** — that heuristic has been tried and reverted three times
here and is still banned.
  * A **definition** defines a word; it can never report that something happened. Anchored
    near the start so an ordinary sentence containing "means" is not swept up.
  * **Contract-party voice.** A policy is written in the second person — the insured is "you",
    the carrier is "we/us/our". A statement about the applicant, anywhere, is third person
    ("the applicant", "the insured", the company's own name). The pronoun must sit in a
    contractual frame ("to us", "we will", "you must", "your household") so a producer's
    casual "your" cannot trip it.

Applied to **Y and N alike**, per the owner's symmetric rule ("if we have conclusive evidence
of *either*... only then stamp"), and wired into `_is_coverage_artifact_text` so the
explanation, dependent-cell, party-name and late-sweep paths all inherit it from one predicate.

Three smaller items in the same class: `_QUOTE_CTA_RE` widened from `see (your|the)` to a bare
`see` plus `as shown/described/stated`, `per the/item/form` — run 8 stamped **"SEE ITEM FOUR
FOR HIRED OR BORROWED AUTOS"** as a conviction TYPE and extraction put **"SEE SCHEDULE FOR
DED ."** in `auto_deductible_collision`, the same shape twice, missed because the two words
after "see" happened not to be "your" or "the". The dependent-artifact check **dropped its
`_d in gpt_filled_set` scope** — the fourth-door rule one level down: "is this an artifact?"
is a question about the VALUE, so it may not ask who wrote it. And a **partially-filled**
dependent section whose surviving cells carry no letters at all no longer substantiates a Yes
(run 8's Q14: one cross-reference, blanked above, and a borrowed `3`); gated on *incomplete*
so a numeric table ACORD genuinely designed that way is never second-guessed.

**ACORD's 13th declared type.** C22 wired up twelve tooltip-declared types and missed
`"Enter rate:"`, which **44 fields across 5 forms** declare — so run 8 put `LIAB-I` (a
coverage code) in `Vehicle_PrimaryLiabilityRatingFactor_A`, whose tooltip literally reads "the
primary liability rating factor contains the NUMBER which is used...". **The first cut of the
rule was wrong and the C22 corpus caught it**: "a rate with no digit is not a rate" blanked
`"Included"` on all 44 fields, and a broker writing "Included" in a premises/operations rate
box is a real convention already listed in `_LEGIT_BY_TYPE["rate"]`. Rates are *not* the
exception to C22's word-convention rule; I assumed they were. The shipped rule is the shape
that actually separates the defect from the convention — an abbreviated CODE (digitless, >3
chars, uppercase runs joined by `/` or `-`: `LIAB-I`, `COMP/OTC`) versus an English word.
Zero false positives across 44 fields × 13 legitimate notations.

**2. THE MISSING FEEDBACK LOOP — why four consecutive runs showed "no hard stops or
warnings".** The stops engine was never broken. `evaluate_stops` validates **FACTS**, and on
this package the facts are clean, so `hard=0 soft=0` is the correct answer; on the one run
where extraction genuinely missed payroll it *did* fire on screen. Everything in the guard
region validates **STAMPED VALUES** — and nothing carried that second set anywhere a human
could see it. A form on which a dozen fabricated values were caught and removed was
indistinguishable from a form that was right the first time: same silence, same empty boxes,
and no way for the producer to tell a blank we never found a value for from a blank we
**refused** a value for.

Closed end to end. `map_facts_to_form` takes an **opt-in** `guard_report` list (default
`None`, so no existing caller or test changes) and fills it from a **diff** — every box
non-empty when the guard region began and empty at `return`. Deliberately a diff and not
per-guard plumbing: there are ~30 guards and a hand-maintained "which ones report" list would
be stale within a week, which is the exact rot that let the fourth door stay open. Guards
written after this change report themselves. `process_single_form` passes the list and returns
it on the form result; `field_qa` turns it into **one advisory row per FORM** (naming the
first three fields, "+N more") in the pre-download review — one row, not one per field,
because the client's 2026-08-12 "repeated values are there a lot" applies here more than
anywhere. Advisory always: a guard blank is the system working, so it never fails a run and
never blocks a download. Also `GUARD_BLANKS` at WARNING, one greppable line per form.

Tests: `backend/tests/test_run_20260813g.py` (40), including the two literal client quotes,
the ten genuine applicant statements that must survive, the all-schema rate sweep, and an
anti-rot test on the wiring between the three modules. Suite **2434 passed / 2 failed** — the
same two pre-existing, zero regressions. **No LLM call added, removed or reprompted; no
batching or chunking touched.**

### C57 — the declarations index is purged once forms are generated (2026-08-13), NO LLM change

**Owner's product rule, which is what makes this safe:** *"once any form is generated, user
cannot go back in that same package to generate another form, they have to restart new
package."* That removed the only argument for keeping the index — re-generating a different
ACORD form off the same extraction — so it is now deleted at the end of `select_forms_bulk`.

**Verified before deleting, not assumed.** Every consumer of `dec_page_entries` runs at or
before generation: the empty-fact backfill (merge time), the text-selection rescue net and
Stage A (gap fill), the single-printed-value guard (stamping), and `dec_index_coverage` (the
line immediately above the purge). Everything after generation — download, signature, the
ARQ confidence updates — reads `generated_forms[...]["mapped"]`, which is already-stamped
values, never the facts.

**Only on the real path.** `lite_generate_internal` also generates forms, silently, for
scoring and ARQ, and it runs BEFORE the producer has chosen anything; purging there would
leave the real generation with no index. Pinned by an AST test that asserts the purge call
lives in `select_forms_bulk` and nowhere else.

**Why it is worth doing at all:** a dec-page index is names, addresses and identifiers,
~33 KB a session, and `run_facts_retention` **skips the professional/enterprise tier
entirely** — so without this it survives until the session row is deleted at 180 days of
inactivity. It uses the repository's existing `delete_facts` retraction (atomic, versioned,
idempotent) rather than a read-modify-write, because the facts merge is additive and a
stale re-write would clobber whatever the extraction pipeline wrote in between.

**Degrades, does not break.** If a second generation ever reaches the session, Stage A
simply does not run and every field walks the raw document — the pre-2026-08-13 pipeline.
Kill switch `PURGE_DEC_INDEX_AFTER_GENERATION=0`, which is what to set the day the product
grows an "add another form" flow.

The coverage summary survives on purpose (written before the purge, and not a fact), so
"what did the declarations print that never reached a form" is still answerable afterwards.
**Known trade-off, named rather than hidden:** that summary's `unused` list carries the
label/value pairs of the entries that went nowhere, so it retains a PII subset of what the
purge just removed. Worth Brent's ruling on whether it should keep values or only counts.

Tests: `backend/tests/test_dec_index_purge.py` (10), including an anti-rot sweep that fails
if a NEW `dec_page_entries` consumer appears anywhere in `services/` or `routes/` — because
the purge is only safe while nothing downstream reads the entries. Suite **2293 passed / 2
failed**, the same two pre-existing, zero regressions.

### C56 — second live run of 2026-08-13: the fixes held, one regression, one revert, NO LLM change

**What the log proves worked.** `schedule_no_substance: auto_drivers has 1 row(s) carrying
nothing but a name` (ERIN ROYAL) — the DRIVER INFORMATION SCHEDULE tick is gone. DEPOSIT,
NO. OF MEMBERS and Q3 FLAMMABLES all shipped blank. The arithmetic reconciliation replaced
the $2,991 line premium with the real $10,663 total, and **C23 was beaten on the client's
own paper**: `gl_each_occurrence chosen='$1,000,000' rejected=['$ 3,000,000']`.

**1. REGRESSION — form numbers stamped as policy numbers.** Q4 "other insurance" had four
correct rows on the previous run. This run printed `IM 7100 06 04` and `IM 7201 10 02` —
AAIS **form** numbers, the coverage WORDING an insurer attached — while the umbrella's
`6J7-40-02---26` and the GL's `BBC7263` fell off the four printed rows entirely. Visible in
extraction: `merge coverage_lines FINAL: ... ('Installation Floater', 'None',
'IM 7100 06 04')`. `_looks_like_a_form_number` now drops the ROW, not just the cell — the
paired line name came from the same entry, and leaving it would consume a printed row.
Anchored end-to-end, verified against all five real policy numbers in the package plus the
carrier dec-page code `CA7000A 02-22`.

**2. `section` was being thrown away on the pages that need it.** 45 `SECTION_DROPPED`
lines, every one a coverage part the package demonstrably contains (`COMMERCIAL UMBRELLA
DECLARATIONS`, `COMMERCIAL UMBRELLA SCHEDULE`, `COMMERCIAL INLAND MARINE DECLARATIONS`).
Both the plain and the `POLICY` variant failed, so it is not the model guessing a name — a
dec-page heading is large centred type and does not survive OCR as one contiguous run.
`section` is the C23 discriminator (C54/D11), so the loss landed precisely on the umbrella
pages. `_section_is_printed` now requires ORDERED CONTAINMENT — every significant word
present, in order, within 80 characters of its predecessor. **Named as a relaxation, not
dressed up**: a heading could now be accepted from coincidentally-ordered body text. Bounded
— `label` and `value` still face the unchanged verbatim gate, so the worst case is a
mis-grouped index line, never a stamped value.

**3. An abstaining guard now says why.** C55's `_second_claim_on_a_single_printed_value` did
NOT fire on the FAX box (still `303-996-7800`, the producer's phone) and said nothing, so a
correct abstention and a missed catch were indistinguishable. The likely cause is its
"exactly one distinct label" condition — across 267 verified entries the same number is
probably recorded under label variants ("Agent Phone", "Producer Phone"). Those are not
separable from two genuinely-equal facts (a $1M/$1M GL policy) without vocabulary, **so the
rule was NOT relaxed on a guess**; it now logs `single_printed_value DECLINED` with the
labels it saw, whenever a duplicate exists and only the label test spared it. Decide from
the next run's data.

**4. TRIED AND REVERTED — do not rebuild it.** Q11 shipped `NAME OF TRUST: Emcasco Insurance
Company`, the carrier's own group company in a third-party box, inside an otherwise-empty
ADDITIONAL INTEREST block. "A name with no other detail is not a record" is the same
structural rule that fixed the driver schedule and it is **wrong here**: it broke 5 tests,
all correct. A name-only additional interest is a SUPPORTED shape — the vehicle-ownership
question answers itself by naming the owner and nothing else. Row shape cannot tell the
carrier's name from a lender's; only identity can, and the ownership guard missed `emcasco`
because it matches its family token `emc` by exact key rather than prefix. Whether a
3-character family token may match by prefix is a real question with a real case against it
(EMCOR Group is a genuine construction firm) and needs its own evidence.

**Still open from this run:** the FAX box; the premises DESCRIPTION OF OPERATIONS carrying
`COMMERCIAL GENERAL CONTRA` while the main operations box below it is correct (two boxes,
two sources); REMARKS carrying `SEE ATTACHED SCHEDULE FOR LIMITS AND DESCRIPTION OF
COVERAGES`; `PAYMENT PLAN = "AN"`. **And Stage A is unverified in production** — the pasted
log ends before any `STAGE_A` or `DEC_INDEX_COVERAGE` line, so C54's 135 → 49 remains
measured offline only.

Tests: `backend/tests/test_run_20260813b.py` (25), including the anti-rot test that pins the
reverted rule. Suite **2283 passed / 2 failed**, the same two pre-existing, zero regressions.

### C55 — five defects on the 2026-08-13 ACORD 125, fixed by class (2026-08-13), NO LLM change, cost ZERO

All five are deterministic. No prompt was edited, no call added or removed. Listed here
because two of them are only fixable *because* C54 exists, and because the first one is a
standing instruction about how not to fix this file.

**1. The contract-language guard was being maintained by enumeration, and lost again.**
Fourth incident of one defect:

```
2026-08-10  Q5 CONDITION CORRECTED  <- a fraud-warning clause
2026-08-12  Q3 FLAMMABLES           <- "this insurance does not apply to..."
2026-08-12  Q3 FLAMMABLES           <- '"pollutants" means ... chemicals'
2026-08-13  Q3 FLAMMABLES           <- "This exclusion applies even if the claims
                                        against any insured allege negligence or
                                        other wrongdoing in:"
```

The last one walked around every pattern because it is phrased **positively** and all
three pattern sets are phrased negatively (`does not apply`, `will not pay`,
`is excluded under`). A fifth alternative would have closed that sentence and left the
next phrasing open - the same whack-a-mole the 2026-08-08 `underwriting_consistency` arc
had to abandon after three rounds.

Replaced with a RULE: `_POLICY_SELF_SUBJECT_RE` matches a demonstrative pointing at the
document (`this exclusion`, `these conditions`) followed by an **operative verb**. The verb
list is the safety, not the noun list - *"This policy was cancelled for non-payment"* is a
legitimate Q5 answer and survives, because `was cancelled` is a past event, not a statement
of how the contract works. Plus `_is_dangling_clause`: a sentence ending at a colon with no
full stop is a fragment lifted from a sub-clause, which is what the reported value literally
is. **Swept against all 5,787 ACORD tooltips ≥40 chars: 0 flagged.** 7 contract shapes
rejected, 6 genuine applicant statements survive.

**2/3. The producer's PHONE in the FAX box, the total PREMIUM in the DEPOSIT box.** Both
boxes have no source in 271 pages, so gap fill reached for the nearest value of the right
shape and filed it twice. **The obvious rule - same parent, different leaf, equal value -
was written, swept, and thrown away**: 149 of 528 parents carry more than one amount/date
leaf, and `GeneralLiability_BodilyInjury_{EachOccurrence,Aggregate}LimitAmount` legitimately
coincide on an ordinary $1M/$1M policy. That rule deletes real limits.

What separates the cases is the document, and **C54's index is the first thing in this
pipeline that can say so**: a value the declarations print under exactly ONE label is one
fact and cannot answer two differently-named boxes; a `$1,000,000` printed under both "Each
Occurrence Limit" and "Personal & Advertising Injury Limit" is two facts that agree, and
both stamps stand. No vocabulary, no topic matching. Degrades to today's behaviour with no
index.

**4. `NO. OF MEMBERS AND MANAGERS = 0`** with the LLC box ticked. Zero is the model writing
"the document does not say" in the one form that reads as a fact. Scoped hard -
`_NONZERO_COUNT_FIELDS` has exactly one entry and a test forbids adding counts that can
legitimately be zero (losses, claims, vehicles).

**5. DRIVER INFORMATION SCHEDULE ticked with no drivers.** The checkbox was honest; the
fact was wrong. Extraction had read page 92's `CA 99 10 A DRIVE OTHER CAR COVERAGE - NAMES
OF INDIVIDUALS` as a driver schedule - the C22 decoy, the only personal name in the package.
Fixed **deterministically rather than by prompt** (zero cost): an ACORD driver schedule
exists to carry licence number, DOB and hire date, so `_schedule_has_substance` requires one
row with something besides a name. **Non-destructive** - the rows stay in the facts for
`Driver_FullName_*` and the questionnaire; only the "we are attaching a completed schedule"
claim is withdrawn. Two existing tests asserted the old contract (one using `"Erin Royal"`
verbatim) and were updated with the reasoning inline.

**Also added: `dec_index_coverage` / `log_dec_index_coverage`** - the owner's question
*"what about the data that was present in the declaration page and it didn't get stamped"*,
answered by subtraction rather than by eye. Every index entry is a value the declarations
printed; anything not stamped in any generated form is the gap, itemised and grouped by
section. **A REPORT, NOT A GUARD** - it changes no form. A dec page prints plenty no ACORD
field asks for, so the count is not a defect count; a section with ZERO consumed values is
what deserves a look. Logged as `DEC_INDEX_COVERAGE` and stored on the session.

Tests: `backend/tests/test_form_defects_20260813.py` (35), including an anti-rot test that
every field name used as a fixture exists on a real schema - the first cut used
`Producer_PhoneNumber_A`, which is on no ACORD form, and passed while an end-to-end replay
of the same values did nothing. Suite **2257 passed / 2 failed**, the same two pre-existing
unrelated failures, zero regressions.

### C54 — Stage A: gap fill asks the declarations index before the document (2026-08-13), cost NEGATIVE (135 → 80 calls, → 49 with the chunk knob)

**This supersedes C50's "call 2 stays byte-identical" constraint. The owner lifted it
explicitly.** Read C50 first for what the recorder is; read
`CALL2_RETRIEVAL_REDESIGN.md` D11 and §3b for the design and the measurements.

**Why the bill exploded, and why every earlier cost model missed it.** The owner ran ONE
form for $3+ against $1.50 for five forms before the D1 quality cap. Cause: the cap made a
716k package split into 13 chunks, and every field batch walks every chunk (D10 keeps full
coverage), so **13 calls became 135**. The §3a table predicted the call counts correctly
and the DOLLARS badly, because it modelled **700 output tokens per call**. At these call
counts output dominates - it is billed 6x input - and 700 was ~4x low. Re-modelled at
2,500/call the figures reconcile with what was actually paid.

> **Input cost is nearly FLAT across the chunking dial** - a batch reads the same bytes
> whether the document is 1 slice or 13. What the cap multiplied is ROUND TRIPS. **The
> lever is call count, and nothing else.** Any future cost work in call 2 that starts by
> reasoning about prompt size is starting in the wrong place.

**The change.** `dec_page_entries` (C50) is rendered as a `=== DECLARATIONS INDEX
(AUTHORITATIVE) ===` section, grouped by a new verbatim-verified `section` field (the
coverage-part heading printed on the source page), and gap fill asks the whole field list
against that ~3%-of-the-package index BEFORE any raw chunk. Fields it answers leave the
walk; the survivors re-pack and walk the entire document unchanged.

**Prompt-cache impact: none, by construction.** The index occupies the raw document's
POSITION in `_build_user_prompt`, so `[system + form label + facts]` is still the shared
prefix across both stages, and Stage A - being the first thing that runs and the smallest
call - now claims the `_should_warm` warm-up instead of Stage B. Verified by
`test_dec_entries_never_enter_the_facts_block`: the entries stay out of the facts block,
which would otherwise have added ~80k chars to the cached prefix of every call in the run.

**Measured, ACORD 125 alone, 716,342-char package, 85% answer rate:**

```
before all this work (1 chunk)      13 calls
D1+D10, no index (what was paid)   135 calls
index ON, 14k tok/chunk             80 calls   (10 Stage A + 70 Stage B)
index ON, 28k tok/chunk             49 calls   (10 Stage A + 39 Stage B)
```

The two levers compose. **`GAP_FILL_DOC_TOKENS_PER_CALL` was raised 14,000 -> 28,000 as the
shipped default later the same day, by owner decision**, so the 49-call row is what runs now.
Be honest about the trade: 14,000 was call 1's chunk size, borrowed because it was the one
figure proved to read carefully; 28,000 is unmeasured, and sits 6x below the ~170k-token
point where C21 measured the model abandoning ACORD field names. It broke
`test_call2_document_budget_matches_call_1_quality_budget` - the D1 fix expressed as a test -
which was **reformulated, not deleted**, against a named `_CALL2_BUDGET_RATIO_MAX = 2`. The
real defect D1 fixed was call 2 sizing from the CONTEXT WINDOW (917,000 chars, 16x call 1);
a small multiple is a dial, capacity is a different pipeline, and a second test pins that
917,000 can never come back. Revert with `GAP_FILL_DOC_TOKENS_PER_CALL=14000`, no deploy.

**Quality argument, not just a cost one.** 89% of a real package is ISO/AAIS boilerplate,
and every documented wrong-value defect in this repo (C22, C23, C46) has its source there.
The index contains none of it. C23 specifically becomes structural rather than heuristic:
the umbrella's $3,000,000 and the GL's $1,000,000 are 62 pages apart under the identical
label, and the index puts them under different headings **in the same call**, co-visible.
The 13-chunk walk sees them several calls apart and settles it by majority vote.

**The one trade.** An index-answered field no longer walks the document, so a later
endorsement cannot supersede it. Bounded: an endorsement that changes a declarations figure
prints its own schedule, schedule pages are recorded, so the superseding value is in the
index too, under its own heading.

**Caps raised as part of this** (they were throttling the index they now feed):
`_DEC_ENTRY_MAX` 500 → 1200, per-chunk prompt cap 80 → 150. A real package prints ~750
entries. Sized so the index still fits ONE call - splitting it re-creates C23, and
`test_a_full_index_fits_in_one_call` fails the build if the caps drift apart.

Kill switch `GAP_FILL_DEC_INDEX=0`, proved byte-identical rather than assumed. Tests:
`backend/tests/test_dec_index_stage_a.py` (23) + 3 rewritten in
`test_dec_page_entries_20260812.py`. Suite **2219 passed / 2 failed** - the same two
pre-existing unrelated failures, zero regressions.

**Still open after this:** the modelled dollar figures remain modelled. Call counts are
solid; the output-token estimate is now reconciled against one real bill rather than
measured directly. Confirm on the next live run.

### C53 — the 52-page trap packet: five deterministic fixes, no LLM change (2026-08-12)

The owner built a synthetic EMC package full of deliberate traps and audited the generated
ACORD 125 against it. The form dodged most traps (NO-COVERAGE lines unchecked, FEIN/website/
phone correctly blank, drones blank despite the unmanned-aircraft exclusion) and exposed
five real defects. All five are aggregation/guard bugs - none needed a prompt or call
change. Tests: `tests/test_dec_traps_20260812.py` (20), every fixture the packet's literal
trap string.

1. **The Additional Insured schedule lost a 11-vs-1 vote.** The AI schedule lives on ONE
   page; one chunk returned the three scheduled names, ten chunks that never saw that page
   returned an all-empty `risk_transfer`, and the vote chose empty (log:
   `chosen=... freq=11 rejected=[...names...](freq=1)`). For a structured fact, ABSENCE of
   data must never outvote PRESENCE: `_merge_risk_transfer` now unions across chunks
   (booleans OR, name lists union, scalars first non-empty) and again across documents
   (the primary-wins doc loop would otherwise clobber a companion doc's data).
2. **Q3 FLAMMABLES = naked "Y" quoting the pollution exclusion - two stacked holes.**
   (a) `_POLICY_DEFINITION_RE` (the gate's contract-language rejector) now also rejects
   exclusion/grant clauses: "this insurance does not apply", "exclusions are deleted",
   "coverage for ... is included/excluded". What a policy covers is never evidence of the
   applicant's exposure - the client's own rule. (b) THE recreation mechanism, finally
   pinned in code order: the policy-contract-language guard at the END of map_facts_to_form
   blanks the explanation the gate wrote, AFTER Guard 9 already passed. New
   `_final_yn_coherence` runs as the LAST mutation - anything that edits `mapped` must be
   inserted above it - and re-blanks any affirmative whose paired explanation ended up
   empty, whatever ate it.
3. **SAFETY MANUAL ticked under a blank Q2** (off "sample written safety manuals ... may be
   requested" - availability read as adoption). New rule: a question's QUALIFIER checkboxes
   (the consecutive /Btn run after a `_Question_<code>Code_` field sharing one name
   segment) may only stand when the parent is answered Yes. **Audited against all 17
   schemas before shipping: exactly six runs exist, five genuine** (125 safety program +
   cancellation reasons, 126/160 pool features, 141 audit-performed-by) **and one false
   positive - ACORD 125's NATURE OF BUSINESS grid - which the audit caught before it could
   blank the Contractor checkbox.** Excluded by name; scoped to AI-authored ticks so Pass-1
   flag-derived boxes are never touched; a standing harvest test fails the build if a
   future schema regeneration grows a new, unclassified run.
4. **Loss-history "Check if none" ticked off "NOT ON FILE".** The deterministic resolver's
   silence used to fall through to gap fill, which quoted "Prior Term Loss Experience: NOT
   ON FILE" - UNKNOWN, not "no losses" - as its evidence. `_resolve_no_loss_checkbox_owned`
   joins `_AUTHORITATIVE_BLANK_RESOLVERS`: flags/facts still answer Yes/No, silence is an
   owned EMPTY box the model never gets to guess (the one checkbox the client explicitly
   said requires confirmation). Extraction's `asserts_no_known_losses` flag guidance now
   states that NOT ON FILE / NOT REPORTED / absence = unknown.
5. **The producer's office stamped as premises LOC 4** - past the packet's own "this is not
   a location of the named insured" note - because the consolidation filter compared
   normalized line1 for EQUALITY and the entry carried "Ste 400" inside line1 while the
   producer fact parsed it onto line2. The filter now also blocks on (street number, ZIP5)
   identity - `_address_identity_key`, the comparator `_drop_transaction_party_rows`
   already trusts - for both producer and carrier. Plus address-shape validation: a state
   either is/converts to a real postal code ("Colorado" -> "CO") or is None; a ZIP matches
   \d{5}(-\d{4})? or is None; and a "ZIP" that is actually a state name means the whole
   city/state/zip split was one shifted mis-parse and all three clear ("VARIOUS JOB SITES,
   STATE OF COLORADO" had printed city="State", state="of", zip="Colorado").

**Re-run addendum (2026-08-13).** The owner regenerated after the fixes: producer office
gone, job-sites row clean, ambiguity logged (`lob-premium: matched 2 different amounts`),
prior-carrier grid correctly refusing current-term data, borrowed-N gone, GROUNDING_SHADOW
not_in_document=0. Two traps half-survived by mutating and are now closed at the gate:
Q3 kept a "Y" quoting the exclusion's own section HEADING ("POLLUTION EXCLUSION -
FLAMMABLES, EXPLOSIVES AND CHEMICALS" - a bare noun phrase no clause pattern matched), and
Q2 came back "Y" grounded on the carrier's loss-control OFFER ("may be requested ... does
not obligate"). New `_quote_cites_contract_machinery` rejects both classes - any quote
containing "exclusion(s)", plus offer clauses in `_POLICY_DEFINITION_RE` - while the
KEPT_YES dec-page coverage rows from the same run ("LIABILITY 01 $1,000,000 COMBINED
SINGLE") are pinned as still-valid evidence. The still-ticked "Check if none" on that run
is the extraction CACHE, not the fix: the chunk results were served from Redis with flags
produced by the pre-fix prompt, and the resolver honors an explicit flag by contract -
validate with a cache-busted upload. The Additional Insured section is still empty because
the union fixed the FACT and nothing yet STAMPS AdditionalInterest rows from
`risk_transfer.additional_insured_names` - a missing stamper, proposed as follow-up, not a
regression. Suite 2177/2 pre-existing.

Known and deliberately not chased: the Business Auto premium box blank on this packet is
honest ambiguity, not a bug - the document states the auto premium twice with different
values ($2,991 at inception, $5,829 after the September endorsement) and the resolver
refuses to pick; "prefer inception vs current" is a product decision. The "N" on Q8 whose
likely evidence is the driver-schedule sentence "this is not a fire code violation" is the
documented borrowed-negation residual. Suite **2174 passed / 2 failed** - the same two
pre-existing unrelated failures; the authoritative-blank census test gained the new owner
(+1, classified in place).

### C52 — text selection DEFAULTED OFF: LLM call 2 reads the whole document (2026-08-12, owner decision), cost +input, quality per owner's live judgement

**Coverage DROPPED on a live 700k-char run with filtering on, and the owner ordered the
filter removed.** The mechanism was C51's own entry-anchored mode: it keeps ONLY windows
carrying an already-known value (a fact or a verified entry), and a dec window whose values
extraction never captured - the audit basis, the billing block, the underwriter line - has
no anchor. Those are EXACTLY the fields only call 2 can fill, so anchoring cut their source
text out of the prompt. The safe-direction stages (density, footer) erred toward keeping;
anchoring inverted that and erred toward dropping. Wrong default for the end goal.

`GAP_FILL_TEXT_SELECTION` now defaults to **0**: production sends the complete document to
every gap-fill call, byte-for-byte the pre-filter behaviour. The filter code and its 40+
tests remain (opt back in with `=1`; the suite opts in via `tests/conftest.py`), and the
known costs of whole-document mode stand measured in this file - ~120-174k tokens per call
and the C21 long-context failure modes. If fill rate or borrowed values regress to the
26%-era numbers, the dial is here; the owner judges from live runs.

**Also in this change, unrelated to the filter:**
1. **Guard 9 - no naked Yes.** Owner saw "Y" stamped with an empty adjacent explanation on
   two live decs. The evidence gate blanks an ungrounded Yes at fill time, but LATER guards
   can eat the explanation it wrote (the NAKED_YES diagnostic caught the tooltip-echo guard
   doing it). Guard 9 runs LAST on final state: an affirmative whose ACORD-paired
   explanation ends up empty is blanked with it - "if yes, add explanation in the adjacent
   field" is the client's own rule, and the form prints EXPLAIN ALL "YES" RESPONSES. Only
   `_question_explanation_pairs` fields are touched; a No never needs an explanation.
2. **Location fold vs OCR unit spacing.** The 3-row smear returned on a cold-cache run;
   compact-form comparison ("D 13" == "D13" with spaces stripped) now folds keys the
   token-level prefix cannot see, while two real suites still never fold.

Tests: `tests/test_whole_document_default_20260812.py` (7), including a pin that the
production default really is whole-document. Suite **2154 passed / 2 failed** - the same two
pre-existing unrelated failures, zero regressions.

### C51 — first live run of C50: entry-anchored keep + strict-reverse backfill (2026-08-12), cost NEGATIVE

**The first production run of C50 worked and taught two lessons, both fixed the same hour.**
Live numbers (271-page EMC package): reconciliation swapped $2,991 -> $10,663 and the PDF
shows it; one clean premises row; **161 entries verified, 12 fabrications discarded at the
gate** - and then:

1. **The filter kept 66.4% because EMC's boilerplate is carrier-proprietary.** Density
   declined again (gap 0.07) and the ISO-footer stage caught only 82/228 windows - pages
   like "FORM CU7000A ED. 01-07" match no ISO shape, calls stayed ~120k tokens, fill rate
   moved only 26%->31%. **Fix: entry-anchored keep.** The 161 verified entries ARE the dec
   fingerprint - keep the windows their values live in, and stop trying to identify
   boilerplate at all. Carrier-agnostic by construction (the entries come from whatever the
   dec pages say), guarantee 3 satisfied by construction (anchors = every protected value),
   ratio gates unchanged, engages only at >=`TEXT_SELECT_ENTRY_MIN` (20) verified entries,
   `TEXT_SELECT_ENTRY_ANCHOR=0` kill switch. Fixture self-check proves the old path declines
   on the EMC shape before the anchored test asserts anything.
2. **The backfill filled ZERO facts - the forward label rule was the binding constraint.**
   The dec prints "PAYROLL"; the key is `total_payroll`; the unmatched "total" blocked it -
   and the run's ONE warning ("GL coverage detected but no revenue or payroll found") stood
   while the dec printed $39,300. **Fix: strict-reverse matching** - allowed only when every
   significant label token matches a key token AND every unmatched key token is a generic
   QUALIFIER ("total", "annual", ...). The asymmetry is the safety argument: dropping
   "total" from total_payroll still names payroll; dropping "gl" from gl_deductible names a
   DIFFERENT thing, so "Deductible" and "Premium" stay refused (both pinned by tests).

Also added: `merge coverage_lines FINAL` diagnostic (GL/Umbrella premium boxes went blank on
this run where the previous run filled them, and nothing logged which line names the merge
kept - next occurrence is diagnosable from the log alone).

Known from this run, deliberately not chased yet: `Insurer_NAICCode_A` came back 21407 vs
21415 (the EMC group prints several writing companies' NAICs - an attribution case for the
entries' owner tags, not solvable inside call 2 under the no-touch rule);
`CommercialPolicy_RemarkText_A` was stamped with a dec-header blob (literally present, so
grounding cannot catch it); two of four parallel gap-fill batches missed the cache (the
known warmup race, C27 territory). Tests: +8 in `test_dec_page_entries_20260812.py` (32
total). Suite **2147 passed / 2 failed** - same two pre-existing, zero regressions.

### C50 — dec_page_entries: LLM call 1 records the dec pages; only deterministic code consumes it (2026-08-12), cost ~+1c output, call 2 BYTE-IDENTICAL

> **PARTLY SUPERSEDED BY C54 (2026-08-13).** The recording half, the verbatim
> verification gate and the deterministic consumers below are all unchanged and still
> current. What changed is the headline constraint: the owner lifted "WITHOUT touching
> LLM call 2" on purpose, and the same verified entries are now ALSO the Stage A
> declarations index that gap fill reads first. Read C54 before acting on anything in
> this entry that says call 2 is untouched.

**The owner's end goal, verbatim: "if values are present in declaration pages uploaded by
user then they should be correctly stamped on the form" - WITHOUT touching LLM call 2.**

**The measured gap this closes.** Extraction is DESTINATION-driven: ~173 registry keys
capture what the forms are known to ask for. Measured ceiling: with all 173 facts perfectly
filled, only 68 of ACORD 125's 548 fields resolve deterministically; anything a dec page
prints outside the key list (audit basis, deposit, program code, servicing contacts, FEIN
when the model misses it) evaporates and can only be re-found by gap fill inside the
haystack. This change makes call 1 SOURCE-driven as well: record every label:value pair a
declarations/schedule page prints - label, value, owner, policy - and decide who consumes it
later.

**The decisions, each with its reason:**
1. **In call 1, not a new call.** The chunks are already read; recording costs only output
   tokens on the 1-3 dec-bearing chunks (~$0.01 at mini pricing). A separate labeling call
   was designed first and rejected by the owner as unnecessary - correctly.
2. **Verbatim or gone (`_verify_dec_entries`).** Every entry's label AND value must be
   literally present (normalized) in the uploaded text; anything else is discarded before
   any code can read it. A labeling pass is checkable in a way free-form answers never were,
   and this check is what makes the rest of the design trustworthy.
3. **Only deterministic consumers.** (a) `_backfill_empty_facts_from_entries`: fills a
   registry fact that merged EMPTY under five stacked conditions - never overwrite; typed
   NAMED validator must pass (86 registry facts qualify + `total_policy_premium` via an
   explicit supplement, because registry membership would spawn a new ARQ client question);
   every token of the fact key must appear in the entry label (stem match) - 'fein' is not
   in 'Account Number', so the client's literal defect cannot route; owner compatibility -
   producer_* facts take only producer-owned values, everything else takes only
   applicant/policy-owned, the deterministic form of the client's "never place producer or
   carrier contact information into applicant fields"; and all matching entries must agree
   on ONE value - ambiguity stays blank for the ARQ. (b) text_selection's fact rescue now
   also anchors on entry VALUES, closing the one data-loss shape the filter had left open
   (a dec value the 173 keys never captured, living on a dropped window). Rescue only ever
   ADDS kept text.
4. **LLM call 2 is byte-identical, proven not promised.** `dec_page_entries` is excluded
   from the gap-fill facts block (`_GAP_FILL_FACTS_EXCLUDE`), and
   `test_call2_prompt_is_byte_identical_with_dec_entries` builds real call-2 prompts with
   and without the key and asserts equality. Inspector re-run: 12 calls, $0.0584, prefix
   stable - unchanged, PASS.
5. **Every unfilled field still reaches call 2** (owner's explicit requirement): the
   backfill removes a field from the gap-fill set only by actually FILLING its fact -
   pinned by `test_every_unfilled_field_still_reaches_call_2` against the real ACORD 125
   schema.
6. **Deliberately NOT done: open-vocabulary matching of entry labels onto the 5,852 ACORD
   field names.** That is a hand-rolled NLU layer, the exact heuristic class this codebase
   has repeatedly burned on (echo guards, keyword matching). Entries reach fields only
   through the typed fact layer, where validators and owner rules exist.
7. **Diagnostic only, zero behaviour change: `NAKED_YES`.** Owner reported a "Y" standing
   without its explanation; one candidate mechanism is the evidence gate keeping a grounded
   Yes whose paired explanation Guard 8 then blanks as a tooltip echo. That path now logs
   `post_fill_guard NAKED_YES` so the next live report pins the mechanism instead of
   guessing.

Tests: `backend/tests/test_dec_page_entries_20260812.py` (24) - every trap fixture is the
client's literal reported defect (account number 0482854 vs FEIN, producer's 303-996-7800
vs applicant phone, carrier website vs applicant website). Suite **2139 passed / 2 failed**,
the same two pre-existing unrelated failures, zero regressions. One existing fixture
updated, not weakened: `test_a_failure_falls_back_to_the_full_document`'s error injection
raised on `.values()` and `_fact_values` now reads `.items()` - the fixture raises on both,
same invariant.

**How to see it working on a live run:** grep for `dec_entries VERIFIED`,
`dec_entries BACKFILL fact=...`, `dec_entries DROPPED_UNVERIFIED`, and
`TEXT_SELECTION FACT_RESCUE`. Backfills carry `source="dec_entry"` in the fact envelope.

### C51 — extraction had no truncation salvage, and one truncated chunk killed the upload (2026-08-15), cost NEGATIVE

**Live incident, the client's 271-page Orbin package: HTTP 500 on upload.**
`RuntimeError: _safe_json_parse: could not parse valid JSON after 3 attempts`. One chunk's
reply was unparseable; the whole document was lost.

**Three defects, all in the same failure path:**

1. **No deterministic salvage.** The gap-fill stage learned in the C-series that a parse
   failure is almost always TRUNCATION at the output cap, and that re-sending the prompt
   re-bills every input token to get the same truncation back at temperature 0 - hence
   `_salvage_truncated_json`. **Extraction never got that lesson.** It went straight to an
   LLM repair fed `raw[:3000]` - the first 3,000 CHARACTERS of a reply that can be 60,000 -
   so the repair saw a fragment of a fragment, and each further attempt re-truncated the
   previous repair's output. Measured on the incident log: repair call `in=858 out=842`,
   i.e. three paid calls that could not succeed by construction. The parser now lives in
   `utils/json_salvage.py` and BOTH stages call it. One implementation, not two - a drift
   between two copies of a parser is invisible until it eats a document.
2. **The output cap was the trigger.** `max_tokens=16000` bounded a reply carrying ~150
   scalar facts, every schedule, AND up to 150 `dec_page_entries` with six fields each.
   Now `_EXTRACT_MAX_OUTPUT_TOKENS` (env `EXTRACT_MAX_OUTPUT_TOKENS`, default **32,000**).
   **This does not raise the bill**: output tokens are billed on what the model actually
   writes; the cap only decides where the text is severed. `gpt-5.4-mini` permits 128,000
   output tokens, so this is 4x headroom and still a quarter of the model's own limit.
   Cost is NEGATIVE overall - a truncated chunk previously cost 1 wasted extraction call
   plus 2 futile repair calls, then lost the document anyway.
3. **A chunk failure was fatal.** `_gather_chunks_async._one` carried
   `except RuntimeError: raise` with the comment "not transient, do not retry". That raise
   blew through `asyncio.gather` and past every degradation path the extractor already has:
   the per-chunk retry budget, the halve-the-chunk-size document retry, and the PARTIAL
   coverage report (`failed_indices`, `failed_ranges`, `coverage=%`, `extraction_complete
   = False`). A JSON/schema failure now takes the ordinary retry path and then degrades to
   `chunk_failed` like every other error. An all-chunks-failed document still raises.
   Losing one chunk is a bad day; losing the document is a worse one.

**Salvage drops the half-written element rather than closing it.** Cutting at the last
comma at ANY depth leaves a partial object - a dec entry with a label and no value, a
vehicle row with a VIN and no make - which is exactly the broken half-relationship the
2026-08-15 client direction forbids. It now prefers the last comma SHALLOWER than the
truncation depth, and falls back to the old rule when there is none (the gap-fill shape,
where the innermost container is the payload and its finished pairs are what we want).

**No prompt bytes changed**, so the cached prefix and every prefix-caching test are
untouched. Tests: `backend/tests/test_extraction_json_salvage.py` (15).

### C48 — Step 2 shipped: standard-form pages dropped by their OWN printed footer (2026-08-12), cost NEGATIVE

**The fill-rate lever finally engages on the client's document.** The density filter
(RETRIEVAL_CHANGES.md) skipped on the client's real package twice - final state
`separation gap 0.07` against the 0.15 floor - so every gap-fill call still carried the full
683k-char haystack and the measured fill rate stayed at 26%. The complementary signal that
plan named as Step 2 is now in `services/text_selection.py`: an ISO standard form declares
ITSELF in its page footer (`CG 00 01 04 13` - two letters, then four 2-digit groups), and
that identification is independent of how a PDF extractor renders lines, which is exactly
where the density signal failed.

Decisions that must survive future edits:
1. **Carrier dec-page codes do not match.** `CA7000A 02-22` (printed on the client's OWN dec
   page as the program code) is a different shape, verified by test. So is `CO 80216-3121`.
2. **A FORMS AND ENDORSEMENTS schedule is dec content and is kept** - it lists MANY codes in
   one window where a real footer is 1-2 (`_FOOTER_MAX_PER_WINDOW`). A window ADJACENT to a
   schedule-like window is also never marked: a schedule cut by a window boundary spills 1-2
   codes into its neighbour, which otherwise looks exactly like a footer page. That edge was
   caught by its own test fixture before it shipped, not by a client.
3. **Order: after dilation, before the fact rescue.** Positive boilerplate identification
   outranks a neighbour-of-a-dec-page guess; the rescue outranks everything, so an extracted
   fact living on a form page always restores its window (guarantee 3 is absolute).
4. **The ratio gates judge the combined result.** A document with fewer than
   `_FOOTER_MIN_WINDOWS` (3) marked windows, or where the final kept share falls outside
   [2%, 90%], is returned unchanged - same refusal discipline as the density stage.
5. **One filtered document per run, so the §2 prefix-caching conditions hold.** Inspector
   re-run after the change: gap_fill prefix 13,312 chars / 52%, compliance 64%, $0.0584 -
   unchanged, PASS.

Kill switches: `TEXT_SELECT_FORM_FOOTER=0` (this stage alone), `GAP_FILL_TEXT_SELECTION=0`
(the whole feature). Tests: 6 new in `tests/test_text_selection.py`, including a self-check
that the fixture really is density-inseparable (footer off -> returned unchanged), so the
footer tests cannot pass by density accident.

### C49 — the arithmetic reconciliation C45 called "the next step" (2026-08-12), no LLM change

C45's known limit, verbatim: authority "does NOT separate two rivals that both sit on the
declarations page - a line premium against the package total... That case needs the
arithmetic reconciliation... and is not in this change." It is now in
`extraction_service._reconcile_total_premium`, running inside `_merge_list_fields` after the
list merge, while the candidate buckets still exist: a `total_policy_premium` winner smaller
than the largest single GRANTED coverage-line premium is arithmetically not a total, and the
best-scored candidate that IS possible replaces it (exact-sum match preferred among the
possible ones; a possible winner is NEVER second-guessed - that would be C23's preference
mistake). No coverage lines, or no possible candidate, and the merge result stands - the
pdf_service resolver still refuses downstream, which is what shipped the client's BLANK
POLICY PREMIUM box: the resolver could only blank, because by resolver time the $10,663 was
gone from the fact dict. Now it never leaves.

Two sibling deterministic fixes in the same batch (same client run, same end goal - "a value
on the dec page must reach the form"): `_resolve_lob_premium` no longer lets a coverage
PART's premium fill its line's box ($35 "Auto Medical Payments" stamped as the Business Auto
line premium; now $2,991 stamps - stem matching reaches "Automobile", part-vocabulary
leftovers reject parts, exact line names outrank qualified ones, parts-only documents still
fill); and `_consolidate_property_locations` folds parse-variant groups (ONE premises
printed as THREE ACORD 125 rows because `_parse_address` splits only on commas; the folded
row recovers street/city/state/zip into their own boxes). Tests:
`tests/test_dec_page_values_20260812.py` (13) + 5 in `tests/test_location_consolidation.py`.
Suite 2098 passed / 2 failed - the same two pre-existing unrelated failures, zero
regressions.

### C47 — the evidence gate was rejecting REAL answers because "not" is a stopword (2026-08-12), cost ~neutral

**Quality regression, not a cost issue — but it is the reason a form came back emptier and
belongs in the same log as the fills it removed.**

`_quote_restates_the_question` (added earlier the same day) exists to stop two real
failures: a checkbox ticked on the "evidence" `"for non-payment of premium"`, another on
`"additional insured"` — each the field's own label read back. Correct target.

It tested only **token overlap**: "are all the quote's significant words already in the
question?". That cannot work alone, because *a direct answer to a yes/no question is by
definition mostly the question's own words* — and `"not"` sits in `_ECHO_STOPWORDS`, so the
single word carrying the entire meaning was discarded before the comparison.

Measured against the shipped schemas, synthesising the canonical way a document denies each
genuine compliance question:

```
form        questions   rejected   rate
ACORD_125          15          6    40%
ACORD_126          21          7    33%
ACORD_127          12          3    25%
...
TOTAL             218         39    18%
```

Casualties included `"The applicant does not have any subsidiaries."`,
`"The applicant does not install, service or demonstrate products."` and — an affirmative —
`"Subcontractors are required to carry coverage."`

**The damage was concentrated by an asymmetry.** A "Yes" survives on a quote *or* a paired
explanation; a "No" has only the quote, and `_evidence_supports` failing on a negative
blanks the field outright. Most compliance answers are "No".

**Fix — a structural second condition, `_quote_asserts_something`.** Overlap is now
necessary but not sufficient: the quote must also fail to assert anything. Both live
culprits are bare noun phrases (no subject, no finite verb); real evidence is a complete
predication. Measured 15/15 separation across both populations, then 39/39 recovered with
both culprits still rejected. Guarded by `tests/test_quote_label_vs_statement.py`, which
harvests the questions from the real schemas rather than hand-listing them, and asserts the
check carries no insurance vocabulary.

### C46 — the model was asked about vehicles that do not exist (2026-08-12), cost NEGATIVE

**This one put WRONG VALUES on a legal document, and it is also a free cost saving.**

Client's live ACORD 127: the document describes ONE vehicle, a 2012 Subaru Outback. The
generated form came back with vehicle rows 2 and 3 carrying the **General Liability** class
codes 91580/91585 and the GL exposures — `$39,300` payroll and `$350,000` subcontract cost —
stamped as vehicle **COST NEW**, plus a duplicated Subaru.

The first theory was cross-form batch confusion (`Vehicle_*` sharing a call with
`GeneralLiability_*`). **That was wrong.** `_SCHEDULE_REGISTRY` binds only the **19 identity
columns** of the vehicle schedule (VIN, make, model, body). `_resolve_schedule_row` already
holds the right contract for those — *"if the row is out of range, mark as authoritative
blank, do NOT send to GPT, we know the row doesn't exist"* — but the other ~50 columns per
row (cost new, rate class, territory, symbols, coverage indicators) are unbound, so they
fell through to gap fill for **every row letter the form prints**:

```
ACORD_127, one vehicle in the document
  row A (the real vehicle) :  56 fields
  rows B..D (NO vehicle)   : 164 fields   <- questions about nothing
```

Asked "what is vehicle B's cost new?" with no vehicle B to describe, the model does the only
thing it can and borrows a plausible figure from the document.

**Fix:** `_resolve_phantom_schedule_row`, registered in `_AUTHORITATIVE_BLANK_RESOLVERS` —
the contract both `compute_form_gaps` and `map_facts_to_form` already consult, so one
resolver covers both paths. It applies the SAME rule `_resolve_schedule_row` enforces, to
the whole row rather than the registered columns of it. Generic across all 16 schedule roots
and all 17 forms.

**It acts only on positive evidence.** An absent or empty schedule list means the row count
is unknown, so nothing is suppressed and behaviour is unchanged — suppressing on no evidence
would delete a schedule the extractor merely missed. Capacity is `len(list) + row_offset`,
because some roots do not draw their first row from the list (`NamedInsured_A` is the
applicant; `row_offset=1`). Using `len()` alone there would blank a real named insured.

**Measured on the 5-form union** (125/126/127/140/25, one location, one vehicle, one driver):

| | before | after |
|---|---|---|
| union fields sent to gap fill | 1,206 | **1,040** |
| ACORD 127 alone | 318 | **154** |
| outer batches | 7 | **6** |

**166 fields (14%) removed, one fewer outer batch, and the removed ones were exactly the
questions that had no correct answer.** Cheaper and more correct.
`tests/test_phantom_schedule_rows.py` pins both directions — phantom rows suppressed, real
rows and the no-evidence case untouched.

### C45 — THE root cause under C43: the merge ranks by REPETITION, so the declarations page always loses (2026-08-12), no LLM change

**C43 fixed two spellings of one value splitting their own vote. This is the layer under
it: even with variants pooled correctly, the vote itself is the wrong question.**

`_score_value` ranks competing values by `tier x (log1p(freq) + confidence)`. Measured
against the real scorer:

```
RIGHT value, declarations page,  1 chunk,  ai_high :  1.543
WRONG value, boilerplate,        2 chunks, ai_low  :  1.599   <- wins
WRONG value, boilerplate,       16 chunks, ai_low  :  3.333   <- wins
```

**A wrong value needs only TWO mentions to beat the right one stated once at high
confidence.** Now consider what a declarations page is: it states each figure EXACTLY ONCE,
while the policy forms behind it mention rival figures page after page. Across 17 chunks the
authoritative statement is structurally the minority vote. **The more of the document we
read, the worse the answer gets** - which is the whole reported phenomenon, and it is
arithmetic, not model attention.

It also explains the asymmetry nobody could account for: on a ONE-chunk document every
candidate has `freq == 1`, the frequency term is a constant, confidence decides, and the
answer is right. Small documents were never being handled better - they simply have no vote
to lose. The codebase had already written half of this down at `_partition_by_shape`
("a low-confidence value seen twice beats a high-confidence value seen once"), and answered
the *value validity* half while leaving *source credibility* unranked.

**Fix - source authority as a dominant QUANTIZED tier.**
`declarations_authority(text)` scores a span 0..1 on how much it looks like a
declarations/schedule page, and `_gather_chunks_async` stamps it onto every partial;
`_merge_list_fields` credits each candidate with the most authoritative place it was seen.

Four decisions worth keeping, each of which was wrong on the first attempt:

1. **Structural, not vocabulary.** A dec page is TABULAR (short lines, dense money and
   dates); a policy form is PROSE. A keyword list would be a per-carrier lookup in disguise
   and would not survive a carrier whose wording we have not seen.
   `test_authority_needs_no_insurance_vocabulary` fails the build on drift.
2. **Quantized tier, not a continuous weight.** Within a tier the expression is byte-for-byte
   the old formula, so a document that cannot be discriminated (all prose, or all tabular)
   does not merely rank *similarly* to before - it ranks *identically*. Asserted by
   `test_within_one_tier_the_ranking_is_the_old_arithmetic_exactly`, not claimed.
   `_AUTHORITY_GAIN=10.0` dominates the widest possible base spread (200 chunks -> 6.30).
3. **Windowed MAX, never the chunk mean.** This nearly shipped as a no-op. An extraction
   chunk is 56,000 chars and a real dec page is a few thousand: scoring the mean, a genuine
   declarations page at 14% of its chunk scored **0.174 against pure prose at 0.061 - both
   tier 0, signal gone**, on exactly the documents the fix exists for. Taking the max over
   3,000-char windows holds down to a 4% share. Max is the deliberately SENSITIVE choice: a
   false positive flattens the signal, which is today's behaviour, while a false negative
   costs the entire fix.
4. **Narrative facts opt out.** Authority says the dec page wins, which for a DESCRIPTION is
   backwards - the fuller operations narrative lives out in the prose, and ranking a tabular
   fragment above it would have *entrenched* the reported "COMMERCIAL GENERAL CONTRA"
   truncation. Derived from the VALUE shape (>100 chars AND >12 words), not a list of fact
   keys: `FACT_REGISTRY` has no `kind` column and a name pattern would miss the next
   narrative fact somebody adds.

**Coverage cannot fall** - authority reorders candidates that already exist and never drops
one. Proven over 200 randomised partial sets: the merged key set is identical with the term
on and off.

**Cost: zero.** No prompt, no call, no chunking change; `raw_text` is untouched, so the
cached prefix and `test_full_document_coverage` are unaffected. Scoring costs **58 ms of CPU
for a whole 17-chunk document**. Inspector re-run after the change: 12 calls, $0.0584,
gap_fill prefix 13,312 chars / 52%, compliance 64% - unchanged, PASS.

**Found while doing it:** the new `_MONEY_TOKEN_RE` silently shadowed an existing CAPTURING
pattern that `_money_amounts` parses with `float()`, turning all 12 C23 currency-tiebreak
tests red. Renamed to `_AUTHORITY_FIGURE_RE`, and
`test_no_module_level_regex_name_is_defined_twice` AST-walks the module so a counting
pattern can never again share a name with a parsing one.

**Known limit, deliberate:** authority separates dec-page values from boilerplate values. It
does NOT separate two rivals that both sit on the declarations page - a line premium against
the package total lands in the same tier and frequency decides as before. That case needs
the arithmetic reconciliation (parts must sum to the stated total), which is the next step
and is not in this change.

Tests: `backend/tests/test_merge_authority_20260812.py` (23). Suite **1895 passed / 2
failed** - the same two pre-existing unrelated failures, zero regressions.

---

### C44 — the same vote-split bug in a SECOND function; "absence" is not a value (2026-08-11), no prompt change

Audit of a real 25-page Orbin declarations run. No LLM-call or prompt change; all six are
decision-layer fixes.

1. **Every line-of-business premium box came out BLANK** on a dec page that prints all four.
   `_resolve_lob_premium` de-duplicated matched premiums by RAW STRING, so `"$ 3,954.00"`
   and `"$3,954"` from different chunks counted as two different amounts, tripped the
   "ambiguous - leave blank" branch, and suppressed the box. Same disease as C43's merge
   vote-splitting, in a second function; comparing on digits is the same cure.
2. **The PRIOR CARRIER grid held the policies being APPLIED FOR** - carriers, premiums and
   the proposed term. `_prior_coverage_grid` now discards any entry carrying the CURRENT
   policy number (including per-line numbers from `coverage_lines`) or the CURRENT
   effective/expiration date. Equality tests against facts we already hold; a genuine prior
   policy is untouched.
3. **A declarations page states absence in its own vocabulary** - "None Scheduled",
   "NOT PURCHASED", "NOT ATTACHED", "NOT INCLUDED", "NOT RATED", "NO COVERAGE",
   "NOT REPORTED" - and those phrases were being stamped as VALUES, including into the
   coded STATE and COUNTRY boxes of the additional-interest block. All added to
   `_LLM_EMPTY_SENTINELS`.
4. A non-committal ownership sentence ("owned, rented **or** occupied by the named
   insured") no longer ticks the "Other" interest box; alternatives joined by "or" leave
   the interest unknown, while "Tenant (leased office space)" and "Licensee under a
   shared-use agreement" still resolve.
5. The CITY LIMITS "Other" box is schedule-bound (it had been ticked with the insured's
   street address as its description).
6. A field ACORD declares as "Enter percentage:" keeps its value only when the document
   actually prints that figure as a percentage - two runs of the same dec produced 0%/0%
   then 100%/100% from a document stating no percentage at all.

Plus more SELECTED-CONDITIONS anchors in `_POLICY_CONTRACT_LANGUAGE_RE` ("legal action
against us", "no person or organization", "exclusions are deleted", "concealment,
misrepresentation", ...) - each verbatim from this dec, each previously quotable as
"evidence" for an applicant-history question.

---

### C43 — THE LARGE-DOCUMENT ROOT CAUSE: cross-chunk vote splitting (2026-08-11), no cost change

**Why a 271-page package fills worse than a 7-page one, measured rather than assumed.**
Extraction asks EVERY chunk for EVERY scalar fact. A 7-page dec is one chunk: one coherent
answer per key. A 271-page package is 14 chunks: up to 14 partial answers per key, and
`_merge_list_fields` picks the winner by frequency. That vote was keyed on
`sval.lower()`, so two SPELLINGS of one value became two rivals splitting their own
frequency. Verbatim from the run's own merge log:

    effective_date          '07/15/25'(4)        vs '07/15/2025'(3)
    producer_contact_phone  '303-996-7800'(3)    vs '(303)996-7800'(3)
    mailing_address         '..., denver, co'(3) vs '... denver co'(3)
    auto_deductible_comp    '$1000 ded'          vs '1000 ded'

The address split also surfaced a phantom "documents disagree" conflict on a submission
containing ONE document. Fix: `_variant_group_key` folds formatting (dates through the
shared `normalize_date`, everything else to alphanumerics) so variants pool their votes,
and `_fold_truncated_groups` merges a MID-WORD truncation into its complete twin
("commercial general contra" -> "commercial general contractor"). A qualified value is
explicitly NOT a truncation ("$1,000,000" vs "$1,000,000 each accident" - the
continuation starts at a word boundary), which is the whole safety argument. Genuinely
different values (four policy numbers, two NAIC codes) still compete.

**Second root cause, same document, not fixed by grouping:** a 271-page package is ~7%
declarations and ~93% policy forms, so for any Yes/No question some clause contains the
question's own noun. Q3 ("flammables, explosives, chemicals?") came back "Y" quoting the
POLLUTION DEFINITION; Q5 came back "Y" off a cancellation condition. `_POLICY_DEFINITION_RE`
(a quoted term followed by "means", or "as used in this policy") and cancellation-condition
patterns now disqualify such quotes as evidence and as narrative values.

No prompt change, no call-count change.

---

### C42 — a stated package total replaces a computed one; three more families owned (2026-08-11), cost NEGATIVE

Graded against both a synthetic 7-page fixture and the real 271-page package on the same day.

1. **EXTRACTION PROMPT: `total_policy_premium` added (~60 words, cached prefix).** The only
   prompt change here. The ACORD 125 POLICY PREMIUM box was computed by summing per-line
   premiums; on the 271-page package that summed to **$9,438 against a stated $10,663**
   because one line's premium was missed at extraction. A stated total is a COPY, a sum is
   an INFERENCE - `_resolve_estimated_total` now prefers the stated total (currency-checked)
   and keeps the sum as the fallback for documents that print no overall total.
2. Field-set / code only: the transaction-status TIME boxes are owned unconditionally (a
   dec page prints only the POLICY's "12:01 A.M." inception hour, lifted into them on two
   runs); the thirteen additional-interest TYPE boxes are owned by the captured interest
   fact (one stated Loss Payee had produced three ticks); a row-B narrative that
   near-duplicates row A's is blanked (the primary insured's operations were copied into
   "DESCRIPTION OF OPERATIONS OF OTHER NAMED INSUREDS"). This last one is deliberately NOT
   the banned slot dedup (C18) - gap-fill values only, rows B+ only, >= 40 chars of free
   text only, and schedule-bound cells never reach it.

Field count to the LLM falls again (status times, 13 interest boxes when the fact exists).
Calls unchanged.

---

### C41 — graded-fixture round: county joins the location schema; nine field families hardened (2026-08-10), cost NEGATIVE

A synthetic 7-page dec fixture with a full grading key (TEST_DEC_PAGE_ACORD125.txt) was run
live; ~85% of the key passed and the nine failures were each fixed with the run's literal
values as tests:

1. **EXTRACTION PROMPT: `property_locations` gained a `"county"` sub-field** (~25 words,
   cached prefix; the only prompt change in this entry). County is now schedule-bound end
   to end — the last premises column a model could free-associate into is owned.
2. Field-set / code only: prior-grid premium cells exempted from the "Premium"
   non-fillable substring (fill from `prior_coverage_by_line`); `NamedInsured_FullName`
   rows B+ bound to `additional_named_insureds` (row_offset=1); the producer mailing block
   owned by one `producer_address` parse; business-type mention-ticks suppressed for
   contractors; a "Yes" whose support text LEADS with a negation is blanked by the gate;
   negation sentences blanked from name boxes; Q8/9/10 incident dates anchored to their
   explanations; an insured's own name blanked from AdditionalInterest (loss-payee fact
   seeds the row instead).

Net LLM field count falls again (county, producer block, prior premiums, 2nd-insured name
all leave the prompts when facts exist). Calls unchanged.

---

### C40 — schedule row count bounds whole field families; package total is arithmetic (2026-08-10), cost NEGATIVE

Run-E findings. Field-set changes only; call count unchanged.

1. **`_resolve_schedule_family_row`**: rows beyond a KNOWN schedule length are owned blanks
   for EVERY column of the family — including columns with no schedule binding. Solves the
   client's original "ZIP = 4800 D / Denve" report for good: those fragments were in the
   COUNTY boxes (beside ZIP on the printed form), the one premises column not bound to
   `property_locations`, so it alone kept reaching the model as a "find 4 distinct values"
   group. Ambiguous families (Vehicle: two list keys) are exempt; unknown/empty lists keep
   full LLM coverage.
2. **`_resolve_estimated_total`**: ACORD 125's POLICY PREMIUM box (name carries no
   "Premium" token, so it was LLM-fillable and flip-flopped between the GL line premium
   and the true package total across runs) is owned: the sum of granted line premiums,
   with coverage-part entries and duplicate policy numbers excluded; blank when any line
   lacks a figure. The model is never asked.
3. **NAIC hard shape** (3-6 digits): the carrier's NAME was stamped into the NAIC CODE box.
   +40 NAICCode fields under `_shape_violation`, swept per the C22 precedent.
4. Q4's line label is withheld when it names a line whose coverage flag is explicitly
   False (post-downgrade) — the number still stamps.

---

### C39 — applicant-contact + line-two families owned; absence sentinels widened (2026-08-10), cost NEGATIVE

Run-D findings, all field-set / response-handling changes (no prompt text change):

1. **`NamedInsured_Contact_*` (24 fields on ACORD 125) is owned**: authoritative blank when
   extraction found no applicant contact fact (three consecutive live runs filled the block
   with producer/carrier claims-line contacts — a dec page has no applicant contact to
   find). Family reopens when a real contact fact exists. Fields leave every gap-fill
   prompt on the no-contact case.
2. **`*_MailingAddress/PhysicalAddress_LineTwo_A` owned** from the party's parsed address
   fact ("# D13" was re-written into line two by the model on two runs).
3. **`_LLM_EMPTY_SENTINELS` widened** ("not present", "not stated", ... ) — the literal
   string "not present" was stamped into the NAIC box.
4. LLM-sourced single-choice contradictions are cleared, not demoted (ISSUE+RENEW both
   ticked); `lines_of_business` checkbox ticks need grant corroboration when per-line data
   exists; statutory fraud-warning anchors added to the policy-language guard; carrier
   identity blanked from AdditionalInterest names; BusinessStartDate == policy date
   blanked; Form_CompletionDate now stamps the GENERATION date.

Net field count to the LLM drops again (~24+ fields on the common case); calls unchanged.

---

### C38 — reply keys recovered instead of discarded; more owner-resolved families off the LLM (2026-08-10), cost NEGATIVE

1. **`_absorb` now recovers answers returned under near-miss key names** via
   `_recover_sent_field`: normalized-exact match (case/punctuation drift) and dropped-row-
   suffix match, each accepted only when UNAMBIGUOUS; everything else still rejected and
   counted as UNKNOWN_KEYS. This converts already-paid-for answers into filled boxes on
   long documents (the measured failure: 57 of 60 answers discarded over key names on a
   single call). Zero new calls; logs `recovered=` per chunk and `KEY_RECOVERED` per field.
2. **More field families left the gap-fill prompts**: `Policy_Status_*` is owned
   deterministically when `is_renewal` is affirmative; `StateLicense*`,
   `Producer_NationalIdentifier`, `Insurer_Product*` are non-fillable (agency-profile /
   carrier-filing identifiers that never appear correctly on a dec page); "Other" LOB rows
   additionally exclude coverage-part entries. Field count per 125 run: 277 → 273 on the
   small fixture; larger drop on renewal packages (whole Policy_Status family).

---

### C37 — gap-fill gained an entity-discipline rule; owner blanks stopped shipping to the LLM (2026-08-10), cost NEGATIVE

Two changes in one entry, both logged per the standing rule:

1. **Prompt: `_PROMPT_SKELETON` rule 9 (ENTITY DISCIPLINE), ~1,050 chars.** The extraction
   prompt has had RULE 15 (never copy one party's detail into another party's field) since
   2026-08-09; the GAP-FILL prompt never got an equivalent, and the live client form showed
   the result: the carrier's "Claim Reporting: (888) 362-2255" line in the APPLICANT's
   contact block, phone numbers in email fields, and a dec-page "Agent Number" stamped as
   the State Producer License. Rule 9 names the three parties, forbids cross-party borrowing
   and label reassignment, and says omit instead. Sits in the constant system prompt →
   cached after call 1; cost impact negligible.

2. **`compute_form_gaps` gained the authoritative-blank branch `map_facts_to_form` already
   had.** Its docstring claimed the two "mirror exactly"; they did not. In the combined
   (production) path every owner-resolved blank — the whole prior-coverage grid, Q4
   other-policy rows, producer printed name, section-attached boxes, and the new Other-LOB
   rows — was listed as an LLM question whose answer the fill stage then discarded. Fixing
   the mirror removes those fields from every gap-fill prompt: fewer field lines per call,
   occasionally a whole batch fewer. Cost direction strictly negative; stamped output
   unchanged (the fill stage never consumed those answers).

Also in this change set (no LLM-call impact): `_resolve_other_lob_row` deterministically
owns ACORD 125's "Other" LOB rows from `coverage_lines` (granted lines matching no standard
checkbox); locations consolidation drops bare unit fragments and the producer's own address;
`CommercialStructure_PhysicalAddress_LineTwo` is schedule-bound; unanchored entity rows are
cleared rather than demoted.

---

### C36 — gap-fill prompt stopped calling facts "already verified" (2026-08-10), cost ~neutral

Two edits to the GAP-FILL prompt, both in text that is constant within a run and therefore
sits in the cacheable prefix (structure and ordering untouched — verified with
`inspect_gap_fill_prompts.py` after the change):

1. The facts-block header read `PRIMARY SOURCE — already verified by document analyzer`.
   **No verification of extraction output against the document exists anywhere in the
   pipeline** (`_value_in_raw_text` appears zero times in the extraction layer), so the
   prompt asserted a guarantee the system does not provide and told the model to prefer
   possibly-wrong inferences over the document. Header now reads `unverified hints from a
   previous pass — the RAW DOCUMENT TEXT below is authoritative`; the raw-text header
   changed from `SECONDARY SOURCE` to `AUTHORITATIVE SOURCE`.
2. The system skeleton's source description changed to match: facts are hints, the
   document wins on conflict, and boolean facts may *support* a checkbox answer but every
   such answer still needs its own grounding quote (rule 8 — unchanged).

Char delta: +~320 chars system prompt, +~40 chars user prefix — cached after call 1, cost
impact negligible. Facts stay AHEAD of raw text (position unchanged, per the C1-C11 cache
work); only the claimed trust changed. Quality direction: fewer wrong facts echoed by the
model on conflict; the evidence gate and compliance pass are unchanged.

---

### C35 — RULE 16 gained a "what a line premium is not" clause (2026-08-09), cost ~neutral

~450 chars added to the EXTRACTION system prompt, which is constant per run and therefore
sits in the cached prefix (billed at 10% after the first call of a run).

**Why.** A live run put `$35` in the ACORD 125 Business Auto premium box. The figure is on
the page; it is a fee or surcharge line, not the coverage part's annual premium. RULE 16
now says a line premium is the annual premium charged for that coverage part, and is not a
terrorism (TRIA/TRIPRA) charge, a policy or service fee, a state surcharge or tax, a
minimum premium, an endorsement or audit adjustment, or one vehicle's or location's share -
and that if the only amount against a line is one of those, `premium` must be null.

**A deterministic guard was considered and rejected.** The same document has a legitimate
$300 Inland Marine premium, so any absolute floor or relative-magnitude rule that catches
$35 also destroys $300. Prompt-side is the only place this distinction is visible.

**Cost direction is still negative**, for the same reason as C34: a correct per-line
premium keeps those boxes on the deterministic path instead of returning them to gap fill.

---

### C34 — extraction prompt grew two rules (2026-08-09), cost impact ~neutral

Logged here because CLAUDE.md requires any prompt edit to be recorded, not because it
costs anything measurable.

**Added to the EXTRACTION system prompt** (constant per run, so it sits in the cached
prefix and is billed at 10% after the first call of a run):
* **RULE 15 - ENTITY DISCIPLINE** (~1,200 chars). Names the owning party for every
  identity fact and states that `null` is correct when a party's own value is absent.
  Generalises RULE 14, which already did exactly this for the single
  `naics_code` / `carrier_naic` pair.
* **RULE 16 - coverage_lines** (~800 chars). Per-line premium/carrier/policy breakdown.

**Net effect is expected to be negative cost.** Both rules move work OFF the gap-fill
LLM and onto deterministic stamping: the 15 ACORD 125 line-of-business premium boxes and
the producer identity block now resolve in Pass 1. `_is_nonfillable_field` still blocks
premium boxes inside `compute_form_gaps`, so the gap-fill LLM is never asked for a
premium - the deterministic path was unblocked in `map_facts_to_form` only.

**Verified with the inspector, not a live diff** (`py backend/scripts/inspect_gap_fill_prompts.py`):
`PASS - prefix is stable and cacheable`, system prompt IDENTICAL across all 13 gap-fill
calls, cacheable prefix 11,774 chars / ~2,943 tokens - unchanged from the C1-C11 baseline,
as expected since none of the gap-fill prompt was touched.

**Still to come in this workstream** (will need re-verification when it lands): the
gap-fill skeleton's Rule 3 examples currently say `"Yes" ... else "No"` two lines after
Rule 3 itself forbids defaulting to "No", and Rule 5 forbids filling any premium field.
Both are being corrected; the plan is to DELETE the bad examples while adding the new
rules so the skeleton does not grow.

| ID | Sev | Issue | Location | Status |
|---|---|---|---|---|
| **C21** | **CRITICAL — fill quality** | **At very long context the model stops using the ACORD field names and invents its own.** Observed live on a real 682,726-char / 280-page package (one call = ~170k tokens): a batch that `sent=39` fields got back `total_returned=60` answers keyed `Producer_Name`, `Applicant_Name`, `Contact_Name`, `GL_Limit_EachOccurrence`, `Carrier_NAIC`, `Umbrella_Limit`, … **none of which exist in any ACORD schema.** `_absorb` skipped every unrecognised key, so `filled=3` of 39. The extracted DATA was correct; the keys were fabricated, so 57 of 60 answers were thrown away. Whole-form effect: `COMBINED_B3of7 fields_filled=38/171` (22%). **This is the cost of a single huge chunk** — the same pipeline on a 15k-char document does not do this. Mitigated, not solved: a `CRITICAL - JSON KEYS` instruction is now the LAST thing in the prompt (after the field list, so caching is unaffected), and `_absorb` logs `UNKNOWN_KEYS` at WARNING so it can never be invisible again. **The real lever is `CONTEXT_UTILISATION`** — lower it to trade cost for instruction-following. | `pdf_service.py` → `_build_user_prompt`, `_absorb` | **OPEN — mitigated, needs a live A/B on `CONTEXT_UTILISATION`** |
| **C15** | MED | **Progressive narrowing can miss a supersession.** `_run_field_batch` breaks out of the chunk loop once every field in the batch has an answer, and the compliance pass breaks once every question is answered. Correct for cost, but it means a value stated on page 2 is never re-checked against an endorsement on page 40 that changes it. Majority-vote conflict resolution silently degrades to a single vote. Pre-existing, unrelated to the caching work. Fix is a policy decision (always read the whole document vs. accept first-answer-wins), not a bug fix. | `pdf_service.py` → `_run_field_batch`, `_run_one_compliance_batch` | OPEN |
| **C17** | INFO | **Hard document ceiling.** `_check_cost_guardrail` raises `ValueError` above `ACORDLY_MAX_DOC_TOKENS` (500,000 tokens ≈ 2M chars). This is a **reject, not a truncation** — correct behaviour, no silent data loss — but a very large multi-policy package will fail the upload rather than degrade. Raise the env var if a real submission hits it. | `extraction_service.py` → `_check_cost_guardrail` | ACCEPTED |
| **C8** | LOW | `_FORM_FILL_RESPONSE_FORMAT` is a `json_schema` **without `"strict": true"`**, so it is advisory and does not by itself prevent explicit nulls. **Do not "fix" by adding `strict: true`** — OpenAI Structured Outputs rejects open-ended key maps (`additionalProperties: {type: string}`), which would 400 and silently force the `json_object` fallback. C5 addressed the nulls from the prompt side instead. | `pdf_service.py` → `_FORM_FILL_RESPONSE_FORMAT` | WONTFIX (documented) |
| **C9** | INFO | Pass 1 + Pass 1.5 resolve only ~22% of fields; the rest go to the LLM. Root cause: `CANONICAL_TO_EXTRACTION` has just **43 entries** while alias maps cover all fields. Measured: ACORD 125 → 344 of 548 unmatched; ACORD 140 → 326 of 356. | `services/alias_stamper.py` → `CANONICAL_TO_EXTRACTION` | DEFERRED |

**C9 is the only issue that removes work rather than repricing it.** Every concept added to
the bridge permanently drops fields from the LLM path across all 17 forms. Deferred because
it needs per-field validation, not because it is low value. **Caching has now landed, so
this is the next thing to pick up.**

---

## 4. Resolved issues

All resolved 2026-07-29 in one change set. Files touched:

| File | What changed |
|---|---|
| `backend/services/pdf_service.py` | C1–C7, C10, C11 — primary target |
| `backend/config/settings.py` | C10 — `LLM_SPEND` logging in `_openai_chat` |
| `backend/scripts/inspect_gap_fill_prompts.py` | **new** — offline prompt-prefix inspector |
| `backend/tests/test_prompt_prefix_caching.py` | **new** — 14 prefix-cache regression guards |
| `backend/tests/test_full_document_coverage.py` | **new** — 6 guards proving every word of a multi-chunk document reaches BOTH stages, and that no prompt exceeds the call budget |
| `CLAUDE.md` | pointer + a section describing this work |

| ID | Sev | Issue | Fix |
|---|---|---|---|
| **C33** | LOW — cost-neutral, removes LLM work | *(2026-08-07)* **Covered-auto symbols were extracted and then discarded, so 37 checkbox fields and 3 text fields per form were left to the gap-fill LLM to guess.** `auto_covered_symbols` has been in the extraction schema all along but nothing read it: no stamper binding, no validator, no alias bridge. Meanwhile the symbol definitions ACORD ships in its own field tooltips (`Vehicle_BusinessAutoSymbol_*Indicator` etc., 37 of them across 137/138/160) were reaching the model only as prompt text. A covered-auto symbol is a coverage designation with legal effect, so a guessed one is the exact failure the "blank over wrong" rule exists to prevent. | New `services/auto_symbols.py` holds the table (ACORD's own wording, guarded against drift by `tests/test_auto_symbols.py`). `pdf_service._derive_symbol_indicator` stamps the liability row of the symbol grid and the ACORD 25 / 131 ANY AUTO boxes deterministically; `_SCHEDULE_REGISTRY` binds the three per-vehicle symbol codes on ACORD 127, with policy-level inheritance. **Prompt change:** one new extraction rule (RULE 2b, ~90 words, in the constant system prompt and therefore inside the cached prefix) asks for symbols attributed to their coverage line — `[{"coverage": ..., "symbols": [...]}]` instead of a bare `[int]`, which could not tell any consumer WHICH coverage a number designates. Net effect on cost: **negative** — ~90 words added once per run to the cached prefix, against up to 40 fields per auto form removed from the gap-fill field list. No new call sites, no new batches. |
| **C14** | **MED — silent data loss in a FALLBACK** | *(closed 2026-07-30)* **The umbrella-period probe truncated: `text = raw_text[:_UMBRELLA_PERIOD_MAX_CHARS]` (60,000).** The worst possible placement for a hard cut, because this probe is a *backup*: `map_facts_to_form` fires it only when the main extraction pass has ALREADY failed to produce `umbrella_effective_date` / `umbrella_expiration_date`. So it was pointed at the opening 60,000 chars — on a real 684,000-char package, **the first 8.8%, and precisely the region we already know did not yield the dates. The backup read strictly less than the thing it backs up.** Umbrella dates came back blank on ACORD 125/131/25, and a blank from a truncated read is indistinguishable from a date the document never stated. | The whole document is now chunked through the shared `_split_text_on_boundaries` and scanned **in order, stopping the moment both dates are known**. Cost is unchanged in the common case — an umbrella dec page near the front still answers on chunk 1, i.e. exactly ONE call, same as before; only a document that genuinely does not state the dates early pays to read further, and only when an umbrella/excess form was selected. Chunked at `UMBRELLA_PERIOD_CHUNK_CHARS` (56,000 — extraction's measured-good regime), **not** the gap-fill call budget: a two-key question does not need 170k tokens of context and C21 measured instruction-following degrading there. A failing chunk is skipped rather than abandoning the document (the old single-call code returned `None` on any error; chunking without this would have been strictly worse than the truncation it replaced). The two dates resolve independently, so a dec page stating the effective date and a later endorsement stating the expiration both land. `None` (probe could not run) stays distinct from `{None, None}` (document does not state them). Guarded by `tests/test_umbrella_probe_coverage.py` (21 tests), four of which were **verified to fail against the restored pre-fix implementation**. |
| **C32** | MED | *(found auditing C31's own claim, 2026-07-30)* **The extraction carry-over overlap was never actually decoupled, and the change was not behaviour-neutral.** C31 says the tail became its own constant, `_EXTRACTION_OVERLAP_CHARS` (14,285). It did — in `_compute_prompt_overhead`, which only *reserves* budget for it. **Both functions that actually EMIT the tail — `_chunk_by_sections._flush_cur` and `_split_lines_into_chunks._flush` — kept computing `max_chars // 7`.** Since C31 moved the chunk size 100,000 → 56,000, the real carry-over silently moved **14,285 → 8,000, a 44% cut**, while the number of chunk boundaries roughly doubled: *less* context inherited at *more* boundaries, which is the exact direction that loses a fact spanning a split. The budget meanwhile reserved 14,285 for a tail that was 8,000 — self-inconsistent in the safe direction, and at a chunk size of 150,000 it inverts and **over-runs the reservation**. C31's own guard, `test_overlap_is_independent_of_chunk_size`, exercised `_compute_prompt_overhead` only — the one site that was already correct — so it passed over the defect. | Both emit sites now use `_EXTRACTION_OVERLAP_CHARS`. Restores the historical 14,285-char carry-over and makes the budget reservation exact rather than a guess at a different number. Costs ~6,285 extra chars on each chunk after the first (~$0.016 on a 14-chunk package) and buys back the boundary context C31 removed without saying so. The third notion of overlap in that file — `overlap_pct=0.15`, passed by `_run_extraction` and **never read by anything** — is now pinned as an explicit no-op so nobody wires it to a fourth meaning. Guarded by four tests in `tests/test_extraction_chunk_sizing.py` that measure the **emitted** tuples, three of which were verified to fail against the restored `max_chars // 7`. |
| **C1** | HIGH | Prompt assembled variable-part-first, so the ~23,846-char constant block never entered the cached prefix. Hit rate 0%. | `_build_user_prompt` now emits **form label → facts → raw text → fields → JSON footer**. Facts deliberately stay AHEAD of raw text (the prompt calls facts the PRIMARY source and models weight position); only the field list moved. |
| **C2** | HIGH | `combined_gap_fill` passed `batch_id` (`"COMBINED_B1of2"`) as `form_id`, which was f-string-interpolated into `_PROMPT_SKELETON`. **Two defects: killed caching AND the model never learned which ACORD form it was filling.** | `_PROMPT_SKELETON` hoisted to a module-level, form-agnostic constant. New `form_label` parameter carries the real names (`"ACORD_125, ACORD_25"`) in the user message, where it is constant per run and stays inside the cached prefix. `form_id` remains the logging label. |
| **C3** | MED | `_raw_budget` subtracted the batch's own `fields_chars`, so batches got different document chunk boundaries → different bytes → miss. | Subtracts a constant `_MAX_FIELDS_BLOCK_CHARS` (`FIELD_FILL_BATCH × 250`). **`max(constant, actual)`, not a bare constant** — `_pack_field_batches` emits table groups as unbounded atomic batches, and a fixed allowance alone would push those past the call budget into a context-length error → 3 dead retries → silently blank fields. Same treatment applied to the compliance pass via `_MAX_COMPLIANCE_BLOCK_CHARS`. |
| **C4** | MED | `_pack_field_batches` flushed a partially-filled batch whenever it met a table group. Real log: 186 fields → **8 calls** `[40,4,11,24,18,40,40,9]`. | Table groups stay atomic (row alignment needs it) but `current` is no longer flushed. Measured on the ACORD 125 + 25 fixture: **24 → 18 gap-fill calls.** |
| **C5** | MED | `_PROMPT_SKELETON` said "return JSON null" ~12× against one "omit" block, so the model emitted nulls that `_absorb` discarded on arrival — waste at 6× input price. | Every null instruction reworded to omission, including `_slot_group_block` and `_table_group_block`. **Behaviour-neutral by construction:** `_is_empty_llm_value` already discarded nulls, so omitted and null were always identical to the caller. The anti-borrow / anti-invent wording in the table blocks was preserved verbatim in meaning. |
| **C6** | MED | `json.loads()` sat **inside** the retry `try`. A reply truncated by the 16000-token cap raised `JSONDecodeError` → the whole prompt re-sent up to 3×, after the wasted output was already billed. | Transport failures and parse failures are now handled separately. A parse failure first calls `_salvage_truncated_json`, which rewinds to the last completed element and closes the open brackets — the answers the model *did* finish are kept, at zero extra cost. |
| **C7** | LOW | `_inner()` fell back to `json_object` on **any** exception, so a timeout or 429 — where OpenAI had already processed and billed the first request — immediately fired a second identical full-prompt call. A context-length 400 re-billed a call that could never succeed. | New `_is_response_format_rejection` gates the fallback: 400 **and** the message names `response_format`/`json_schema`/`additionalProperties`, or a local SDK `TypeError`/`ValueError` where no request was sent. |
| **C10** | INFO | No token accounting anywhere — `resp.usage` read in zero application files. | Every hot-path and umbrella call emits `LLM_SPEND stage=… form=… in=… cached=… out=… cache_pct=…`. All wrapped in `try/except`: telemetry can never break a fill. |
| **C20** | **HIGH (cost + latency)** | *(diagnosed from the 271-page live run; closed once the real model spec was confirmed — 400k context / 128k output)* **`GPT_CALL_BUDGET_CHARS` was hand-set to 380,000 ≈ 95k tokens, i.e. only 24% of the window**, and it is the dominant cost and latency term on a large package. Every extra document chunk multiplies the call count by the number of field sub-batches. Measured on the real 671,654-char / 271-page submission across the same 5 forms: **380k budget → 3 chunks → 172 calls**; **760k budget → 1 chunk → 63 calls.** Same fields, same document, **63% fewer calls** — and the cacheable prefix goes from 8.5k chars to 680k. Raising it was previously unsafe: an over-large budget means every call returns a context-length 400, all three retries burn, `_chat_json` returns `{}` and whole batches ship **BLANK** with nothing on screen. | The budget now **self-tunes**. `_is_context_length_error` recognises a genuine context rejection (and only that — a 429, a timeout, or a `response_format` 400 still take the normal path); the first one halves `_effective_budget_chars` process-wide, and `_run_field_batch` re-splits and retries, up to `_CONTEXT_SHRINK_ATTEMPTS` (5, spanning a 32x over-estimate, floored at 40k so it always terminates). A wrong guess costs one wasted call instead of a form full of holes. **And the budget is no longer guessed at all** — it is derived from `MODEL_CONTEXT_TOKENS` (400,000), `CONTEXT_UTILISATION` (0.75) and `FORM_FILL_MAX_TOKENS`, giving **994,000 chars**: 75% window utilisation at the pessimistic 3.5 chars/token, 66% at the measured 4.01. The reply reserve was also wrong — a flat 30,000 chars against a 16,000-token (~64,000-char) reply cap — and is now derived too. **Result on the real 271-page package: 172 calls → 63, cacheable prefix 8.5k chars → 680k, projected gap-fill cost $6.82 → $1.29.** Guarded by `tests/test_context_budget_selftune.py`. |
| **C31** | MED | **Extraction chunk size was one hand-typed literal.** `_MODEL_CHUNK_CHARS = {"claude": 28_000, "openai": 100_000}` — no comment, no calculation, predating the current model. Three defects, only one of which was the number: **(1) no provenance** — nothing said where 100,000 came from or what would make it wrong, while gap fill derived its budget from the model spec, so the two halves of the pipeline disagreed about the same model (56,357 chars/call vs 899,393); **(2) no capacity guard** — nothing compared it to the real window, so an over-large value would have failed every call on context length with no import-time warning; **(3) the carry-over overlap was `raw // 7`**, coupling two unrelated concerns, so changing the chunk size silently changed how much context each chunk inherited from the previous one. | Now `min(quality, capacity)`: quality = `EXTRACTION_DOC_TOKENS_PER_CALL` (14,000 tok, **the binding ceiling**), capacity = `MODEL_CONTEXT_TOKENS x EXTRACTION_CONTEXT_UTILISATION - EXTRACTION_REPLY_TOKENS`, clamped with a WARNING if an override cannot fit. The window constant is read from the **same env var pdf_service uses**, so one edit moves both halves when the model changes. The overlap is its own constant (`EXTRACTION_OVERLAP_CHARS`, default 14,285 = the historical `100_000 // 7`). **Deliberately behaviour-neutral**: effective size 56,357 -> 56,000 chars (0.6%), asserted to produce the identical chunk count on a 1.14M-char fixture. Capacity is **20x** the quality ceiling and that gap is NOT reclaimable waste — it is the measured distance from the C21 cliff. Guarded by `tests/test_extraction_chunk_sizing.py` (12 tests), including one that fails if capacity ever becomes the binding ceiling. |
| **C30** | **HIGH (cost)** | **Outer batching cut BOTH inner streams mid-flow.** `combined_gap_fill` sliced the mixed union, then each outer batch re-partitioned ITS OWN slice into compliance questions (groups of `_COMPLIANCE_BATCH`) and general fields (groups of `_FIELD_FILL_BATCH`). Every slice boundary therefore left a runt batch on each side. Measured on the real 5-form union (1,359 fields, 133 compliance): **compliance ran 18 calls with sizes [4, 10, 10, 9, 1, 10, …, 4, 2, 4, 5] where 14 suffice.** A 1-question call pays a full call's fixed overhead. | The union is partitioned into compliance and general items BEFORE outer batching. General items keep schedule-aware packing (C19); compliance items chunk plainly, and `_COMBINED_FIELD_BATCH` is a multiple of `_COMPLIANCE_BATCH` so each outer group divides into full inner batches. **Changes nothing the model sees** — the compliance pass was always a separate call with its own system prompt, so a compliance field never shared a call with a general field. Batch sizes (40/10) untouched. **18 → 14 compliance calls.** |
| **C29** | **HIGH (cost + a pre-existing correctness bug)** | **Every table group got its own dedicated LLM call.** `_pack_field_batches` emitted each detected table bucket as a standalone batch. Measured on the real union: **46 gap-fill calls, 34 of them partial, many carrying 3-5 fields** — 820 fields shipped in 46 calls where 21 would hold them. The row-alignment invariant (C19) requires a table to be visible to ONE call; it does **not** require the table to be ALONE in that call, so this was a much stronger condition than correctness needed. **And it protected the wrong set:** only >=3-column TABLE buckets were kept atomic, so plain multi-slot groups were sliced freely — measured **27 repeating groups split across separate calls**, which is the C19 failure mode one level down (a call seeing `_A`/`_B` but not `_C` cannot honour "find N distinct values, never repeat one"). | `_pack_field_batches` now bin-packs **indivisible units**: a detected table bucket, a multi-slot repeating group, or a lone field. A unit either fits the current batch or starts a new one, and is never cut. A single group larger than the cap still gets its own oversized batch (only tables reach that; ACORD row letters stop at N). Result on the real union: **46 → 33 gap-fill calls AND 27 → 0 split groups** — cheaper and more correct. "Group" means `repeating_group_key` = (base, **tooltip**), never base alone: ACORD 25's insurer tooltips end "As used here, this is Insurer B.", so those six slots are six one-slot groups needing no joint reasoning; counting by base name inflates the split figure to 92 and is the wrong denominator. `FIELD_BATCH_PACK_TABLES=0` reverts the COST change only — group atomicity holds on both paths, asserted. |
| **C22** | **HIGH** | **Wrong values in the ACORD 127 driver schedule.** `Driver_TaxIdentifier_A/B = "4S4BRCGC9C3217772"` (a **VIN** in a tax-identifier field), `Driver_TaxIdentifier_I/J = "ERIN ROYAL"` (a **person's name**), `Driver_GenderCode_A = "ERIN ROYAL"`. None was caught by the existing guards: `_NUMERIC_DATE_FIELD_HINTS` lists `YearBuilt`/`ModelYear` but not plain `Year`, and `_PROSE_FIELD_TOKENS` contains "Name", so a name-ish field is classified as PROSE and anything passes. | **Guard 3b — ACORD's own declared types.** Each field's tooltip states its type ("Enter code:", "Enter year:", "Enter identifier:", …) for **3,888 of 5,852 fields (66%)**; only the 607 `Enter number:` ones were being read. `_rejects_declared_type` now covers all twelve. Conservative BY DESIGN — it rejects only a personal NAME, a VIN (never in a vin/serial/identificationnumber field), or an out-of-range year, because amount boxes legitimately hold "Statutory"/"Included"/"See schedule". Validated by a **~49,000-pair sweep** (every type-appropriate legitimate value × every typed field in all 17 schemas) with **zero false positives**; the sweep is the test. It caught one during development: "See schedule" matched the person-name shape, hence `_NOT_A_NAME_WORDS`. **Honest scope — 3 of the reported items are fixed, and the other 3 are NOT type errors:** `Driver_LicensedYear_A = "2012"` is a valid year (wrong ENTITY's year — invisible to any type check), `Vehicle_RateClassCode_A = "7383"` is a validly-shaped code, and `Driver_OtherGivenNameInitial_A = "Erin"` **was never a defect** — ACORD's own tooltip reads "middle name **or initial**", so a first name is permitted and rejecting it would blank legitimate data. Guarded by `tests/test_declared_type_guard.py` (31 tests). |
| **C28** | MED | **Budget shrink was process-global, never reset, and cross-contaminated.** `_effective_budget_chars` only ever decreased for the life of the worker, so one pathological document doubled the chunk count and cost of **every later submission** until restart. Worse, concurrent sub-batches all tested `if _effective_budget_chars < budget_before`, so ONE thread's overflow made every other in-flight batch discard completed work and re-run every chunk. **Introduced by the C20 fix.** | Overflow is now tracked in a `threading.local` (`_note_context_overflow` / `_consume_context_overflow`), so only the batch that actually overflowed re-splits. `reset_call_budget()` runs once per submission from `combined_gap_fill`, keeping the within-run learning and dropping the cross-run leak. Guarded by `tests/test_batch_packing_and_budget.py`. |
| **C27** | MED | **Warm-up was scoped per outer batch, not per run.** `_warmup_enabled` was local to `_fill_unmatched_with_gpt`, which runs once per outer batch, so an 8-batch run paid up to **16 serialized warm-up round trips** (8 gap-fill + 8 compliance) and batches 2-8 each warmed a prefix batch 1 had already warmed. | `_claim_warmup(stage, prefix_key)` memoises in a module-level set; `reset_prefix_warmup()` clears it per submission. The prefix is identical across outer batches by construction (that is the point of C1's reordering), so one warm-up per (stage, prefix) is exactly right. Guarded by `tests/test_batch_packing_and_budget.py`. |
| **C26** | MED | **Majority-vote conflict resolution was dead code.** `all_filled[field] = max(candidates, key=…)` implies multiple votes per field, but the chunk loop stopped once a batch's fields were answered, so every count was exactly 1. | Fixed as a side effect of C25's auto-rescan: on a multi-chunk document every field is now re-asked against every chunk, so the resolver receives real votes. Still vacuous on a single-chunk document, which is correct — there is only one chunk to vote. |
| **C16** | MED | **PII in logs.** `_absorb` logged `DIAG_RESPONSE … sample=<up to 2000 chars of model output>` at INFO on every call — real applicant names, addresses and FEINs, which CLAUDE.md classes as sensitive and `utils/crypto.py` encrypts at rest. | INFO now carries field NAMES and the response size only; the values moved to DEBUG behind an `isEnabledFor` check. **Correction to the original report:** `FIELD_SOURCE_AUDIT` was also named there but logs only the field name and an agreement count — no values — so it was left alone. |
| **C19** | **CRITICAL** | *(found in the second live run — WRONG VALUES ON THE FORM)* `combined_gap_fill` sliced the cross-form union with a plain `field_items[i:i+200]`. Each outer batch is a separate `_fill_unmatched_with_gpt` invocation — separate LLM calls that never see each other — so a schedule cut by that slice left the stranded rows with no view of their siblings. Measured on the real 5-form union (1,354 fields): **`Vehicle_*` split across 3 outer batches, `Driver_*` across 2, `CommercialProperty_*` across 3.** It shipped wrong values: `Vehicle_CostNewAmount_D = $58,900` (vehicle **1's** cost; vehicle 4 is $41,800), and `Vehicle_RateClassCode_D = 91560` / `Vehicle_SpecialIndustryClassCode_D = 92478` — the two **General Liability** class codes, borrowed from an unrelated page. C18's fix unmasked it: the per-value dedup had been accidentally deleting `CostNewAmount_D` as a "duplicate" of row A. | New `_pack_schedule_aware_batches`. A "schedule" is any leading name segment appearing with more than one row letter across the union; its fields are kept in ONE outer batch, bounded by `_COMBINED_BATCH_HARD_MAX` (600) so a pathological schedule cannot build an unbounded call. This is the same rule `_pack_field_batches` already applied one level down — the level ABOVE it was doing the cutting. Verified on the real union: all three schedules now whole. Guarded by `tests/test_schedule_aware_batching.py`. |
| **C24** | **CRITICAL — silent data destruction** | *(found by an independent review, 2026-07-30. Invalidated the headline "no data is lost" claim.)* `utils/text_cleaner.py::clean_text`, called at `ocr_service.py:1704` **before extraction, before gap fill, before anything**, deleted content: (1) any line of >8 words that was >80% uppercase — declarations pages are written in capitals; (2) any paragraph under 10 chars; (3) every repeat of any paragraph, MD5-hashed across the whole document; (4) any line of only digits. Measured on a realistic dec page: **56% deleted**, including the named insured, both GL limits, and a vehicle schedule row. Whether a line survived depended on how many of its tokens were pure digits (not `.isupper()`), so a mailing address with three numeric tokens scored 70% and lived while the line above scored 100% and died. A 3-vehicle fleet's garaging address collapsed 3 → 1. **`_verify_coverage` reporting `671654/671654 chars — 100%` was 100% of what survived this function; the denominator was wrong**, and that figure was quoted as proof that nothing was lost. | Filters 1, 2 and 4 **deleted**. Paragraph floor 10 → 1 (empty only). De-duplication is now **default OFF** and, when enabled, requires ≥`TEXT_DEDUP_MIN_REPEATS` (5) occurrences AND ≤120 chars, so a 271-page running header still goes and a fleet row still stays. The saving it gave was ~2.4% of a real package, which at a 99% cache rate is noise. `clean_text` now accounts for every character it removes on every call. **The metric counts NON-WHITESPACE characters only, and the threshold is 2%.** A raw-length metric was tried first and was useless: pdfplumber pads columns with runs of spaces, so a perfectly intact layout-extracted declarations page reports **22.1% "removed"** purely from the lossless whitespace collapse and trips the alarm. An alarm that fires on the normal case gets ignored and then disbelieved on the day it is real — which is precisely how the original 56% deletion survived several rounds of review. The log line reports content-lost and whitespace-collapsed separately. Guarded by `tests/test_text_cleaner_preserves_content.py` (16 tests). |
| **C25** | **HIGH — the coverage test was blind** | *(same review)* `tests/test_full_document_coverage.py` proved "every word reaches the model" using a recorder that always returned `{"values": {}}`. With nothing ever answered, `active_fields` never shrank, the chunk loop never stopped early, and every chunk always shipped. With a recorder that ANSWERS, as production does: one 40-field batch against a 2-chunk document sent **1 call instead of 2 and skipped 38% of the document**. The test written to guard against dropped text could not see text being dropped. A "run-level coverage is still complete" defence was offered (0/400 markers missing on a 120-field run) and **does not hold as a property**: re-measuring showed that run came out clean only because two of its five batches had their answers discarded as `UNKNOWN_KEYS` and therefore happened to read every chunk. With a single batch that fills up, **185 of 400 markers (46%) never ship**. Coverage by luck is not coverage. | Recorder now answers fields and derives the stage from the system prompt. **Rescan is now AUTOMATIC whenever the document actually split** (`_rescan_enabled` → `GAP_FILL_FULL_RESCAN=auto`): zero cost on a single chunk because there is nothing to re-read, and correct the moment there are two. The previous OFF default relied on documents staying under ~890k chars — and fixing C24 removed up to 25% of deletion from every document, pushing large packages TOWARD that line, so **the shredder fix had armed this hole.** `GAP_FILL_FULL_RESCAN=0` keeps the legacy first-answer-wins path as a kill switch and logs `COVERAGE_PARTIAL` when it drops text. Also revives C26. |
| **C23** | **HIGH** | *(independently confirmed by an outside review, which found two further defects in the same six lines)* The currency tiebreak re-sorted candidates by dollar magnitude on a near-tie. Three defects: **(1)** across coverage parts it is inverted — a package with a GL part ($1M/$2M) and a Commercial Liability Umbrella ($3M) had `gl_each_occurrence` filled from the UMBRELLA, while the composite `gl_limits` from the same run said $1,000,000; **(2)** the re-sort was global, not a top-two swap, so a 5th-ranked candidate could win on size alone; **(3)** `_currency_magnitude` strips non-digits, so on the composite `gl_limits` (which IS in `_CURRENCY_FIELDS`) it returns **1.0e+20** — the tiebreak was literally 'most digits wins'. | **Fixed in two rounds; the first round did not work and the live log proved it.** Round 1 reduced the magnitude rule to the one case its own comment cited (a real limit beating a literal zero) and reconciled each scalar against the composite `gl_limits`. **A real run on 2026-07-30 (ORBIN CONTRACTING) still stamped $3,000,000** because the COMPOSITE ITSELF was the umbrella block (`'each occurrence limit (liability coverage) $ 3,000,000; ...'`) — so every scalar agreed with a wrong witness, and the check logged nothing because the top candidate already matched. Round 2 fixed two further defects: **(a)** nothing was choosing between competing composites — `_score_composite_candidate` now ranks them by (how many of the four scalar children it explains, how many distinct dollar amounts it lists), which picks the real GL breakdown over an umbrella block that repeats one number, using no coverage-part vocabulary; **(b)** the scalar check required EXACTLY ONE consistent candidate, and `'$ 1,000,000'` / `'$1,000,000'` are two candidates for the same amount — it now groups by AMOUNT, so ambiguity means two DIFFERENT figures rather than two spellings of one. `gl_products_aggregate` and `gl_personal_advertising_injury` were also stamped from the umbrella and are now children of the same reconciliation. Verified on the run's verbatim strings across **all 6 orderings of the three composite candidates: 6/6 correct**. Guarded by `tests/test_currency_tiebreak.py` (23 tests). |
| **C18** | **CRITICAL** | *(found in the first live run, pre-existing, NOT latent — it was actively destroying data)* The post-fill slot dedup cleared any `_A/_B/_C` field whose value had already appeared in an earlier sibling. On a real ACORD 127 fleet it deleted **40+ correct cells** in one generation — garaging city/county/state/postal code, radius of use, rating territory, rate class, collision and comprehensive deductibles, and most coverage indicators for rows B and C — because three trucks garaged at one address legitimately repeat those values down the column. Row A survived complete; rows B and C came out near-empty. My caching work did not cause it but **exposed** it: better prompts meant the model filled far more sibling cells, so far more hit the dedup. | **Default OFF** (`SLOT_VALUE_DEDUP=1` restores it). It cannot be made correct here — a call sees only a SUBSET of a schedule's columns, so "model copied a value" and "the document really says that for every row" are indistinguishable. A row-level variant was implemented, tested, and **removed**: ask about City/State/PostalCode alone and three trucks in one city produce three byte-identical rows. Decided on asymmetry: a wrongly repeated value is visible and broker-correctable; a wrongly deleted one is invisible and reads as "not in the document". Guarded by `tests/test_table_row_dedup.py`. |
| **C12** | **HIGH** | *(found in QA review, pre-existing, latent)* `_raw_budget` sized the document chunk by estimating the fields block with `_field_spec()` — one short line per field — while `_build_user_prompt` renders multi-slot and table fields through `_slot_group_block()` / `_table_group_block()`, which are **several times longer**. On a group-heavy batch the estimate under-counted, too much raw text was packed in, and the assembled prompt ran past the call budget. **Measured: 69,879 chars against a 60,000 budget on ACORD 140** (+16%). In production that is a context-length 400 → 3 dead retries → `_chat_json` returns `{}` → the whole batch silently BLANK, indistinguishable from the model having nothing to say. Latent only because `GPT_CALL_BUDGET_CHARS` (380k) currently sits well under the model's real context. | Extracted `_render_fields_block()` as the **single source of truth**; `_build_user_prompt` and `_raw_budget` now both call it, so the two can never drift again. The allowance is then rounded **up** to a multiple of `_MAX_FIELDS_BLOCK_CHARS`, which keeps chunk boundaries shared across similar-sized batches (caching) while never under-reserving. Guarded by `tests/test_full_document_coverage.py`. |
| **C13** | MED | *(found in QA review, in C11's own fix)* Warm-up always adds one serialized wave: with N batches and pool P, waves go `ceil(N/P)` → `1 + ceil((N-1)/P)`. Worth it for a large prefix; a bad trade for a tiny one, where it buys ~half a cent and costs a full round trip of user-visible latency. | Gated on `_PREFIX_WARMUP_MIN_CHARS` (default 40,000 — i.e. roughly a 10k-token prefix). Below it, latency wins and the run is short anyway; above it, cost wins. Logged per invocation as `warmup=True/False`. |
| **C11** | MED | *(found during implementation, not in the original audit)* Sub-batches fan out `_FIELD_BATCH_POOL`-wide, and OpenAI only populates a cached prefix when a request **completes** — so the first 4 concurrent calls were guaranteed misses, capping a 6-batch run near 33% regardless of C1–C3. | `_PREFIX_WARMUP` (default on) runs one call to completion, then fans out the rest. Applied to both the compliance pass and the general fill. Also added `prompt_cache_key` (content-derived, per submission) so the router sends prefix-sharing calls to the same cache; it self-disables process-wide if any API rejects it, so it can never fail a run. |

---

## 5. Measured baselines

### Offline prompt-shape measurement — reproducible, zero API cost

`py backend/scripts/inspect_gap_fill_prompts.py` runs the real `combined_gap_fill` over real
schemas with the OpenAI client swapped for a recorder. Fixture: ACORD 125 + ACORD 25,
3,213-char document (449 unmatched fields).

| Metric | Before (`0d64b9f`) | After | Δ |
|---|---|---|---|
| Total LLM calls | 29 | **23** | −21% |
| Total input chars | 421,190 | **350,115** | −17% |
| `gap_fill` calls | 24 | **18** | −25% |
| `gap_fill` system prompt | **3 variants — caching dead** | identical | — |
| `gap_fill` cacheable prefix | **0 chars** | **11,774 chars (~2,943 tok)** | — |
| `gap_fill` cached-input ceiling | **0%** | **64%** | — |
| `compliance` cached-input ceiling | 70% | 70% | unchanged |

**The compliance pass was already caching correctly** — document-first, constant system
prompt. All of the loss was in `gap_fill`, which sat at literal zero. The two "before"
numbers that matter: 3 different system prompts, and a shared user prefix of **26 chars**.

The −17% input-char figure is the *pre-cache* saving (fewer, less fragmented calls). The
cache saving lands on top of it: the 64% share of `gap_fill` input that is now prefix bills
at ~10% instead of 100%.

### Measured effect of the 2026-07-30 cost work (C29 + C30)

Offline, reproducible, zero API cost. Real schemas, real cross-form union
(`py scripts/inspect_gap_fill_prompts.py --forms ACORD_125 ACORD_126 ACORD_127 ACORD_140 ACORD_25`).

| Metric | Before | After | Δ |
|---|---|---|---|
| Total LLM calls | 63 | **47** | −25% |
| `gap_fill` calls | 46 | **33** | −28% |
| `compliance` calls | 18 | **14** | −22% (the ideal) |
| Repeating groups split across calls | **27** | **0** | correctness, not cost |
| Fixture cost | $0.2782 | **$0.2186** | −21% |

On a realistic **680,000-char, 5-form package** (where the cached prefix is
~170k tokens per call, so a removed call is worth far more):

| | Before | After |
|---|---|---|
| Calls | 64 | **46** |
| Cached input | 10.6M tok | **7.5M tok** |
| Cost | ~$1.30 | **~$0.98** (−24%) |

**Output tokens are an estimate** (500/call, from the live-run average) and are the
weakest number here — real output scales with fields answered, not with call count,
so treat the output line as indicative. The solid savings are the removed round
trips and the repeated cached prefix. **None of this changed a batch size, a
prompt, or what any single call asks the model.**

**Measured and deliberately declined:** raising `_COMBINED_FIELD_BATCH` from 200 to
600 removes 4 further calls (34 → 30) by reducing outer-batch remainders. Declined
— it is a ~6% gain that touches the schedule-batching invariant (C19), and the
standing requirement is that a cost change leave quality the same or better. Revisit
only with the accuracy baseline in hand.

### Live token measurement

Populate from `LLM_SPEND` lines on a real run.

| Date | Scenario | Calls | Input tok | Cached | Output tok | Cost | Note |
|---|---|---|---|---|---|---|---|
| 2026-07-29 | **Same 5 forms, 682,726-char 275-page package, single-chunk budget** | 7 outer batches, ~1 chunk each | ~170k/call | **99%** | ~500/call | **$1.17** | The budget fix landed: `prompt_chars=713268`, `chunk 1/1`, `cache_pct=99` on every call after the first of each stage. Down from ~$1.75 on the previous 3-chunk run. Extraction was effectively free — 13 of 13 `extract_facts: cache HIT` (same document re-uploaded), so this figure is almost entirely gap fill. One wasted call at process start from the `prompt_cache_key` mis-detection (C23 note) — now fixed by SDK inspection. |
| 2026-07-29 | **Same 5 forms, 671,654-char 271-page package** | **172 calls** (138 gap_fill + 34 compliance) | ~11.1M | ~90% (implied) | — | **$1.75** | 3 document chunks × 46 field sub-batches. Cost is arithmetically correct for the design, not a bug — but 63 calls suffice at a single-chunk budget. See C20. Extraction: 13 chunks, 671,654/671,654 chars covered, `_verify_coverage` OK. OCR: 0/271 pages needed Vision (pdfplumber read the text natively), 7 embedded images OCR'd. `table_extractor` skipped at 271 > 40 pages (supplementary pass only; main text unaffected). |
| 2026-07-29 | **ACORD 125+126+127+140+25, 15,302-char 10-page PDF** | 6 outer batches | — | **66-92%, avg ~82%** | avg ~450/call | **$0.24** | **FIRST LIVE RUN — caching CONFIRMED working.** OpenAI dashboard $0.18 → $0.42. Projected $0.33, actual $0.24 (27% under; the projection's 700 out-tok/call was conservative — real average ~450, helped by C5's omit-instead-of-null). `rejected=0` on every call, versus the pre-fix `sent=4 filled=0 rejected=4` that motivated C5. `warmup=True` at prefix~41,007 vs the 40,000 threshold. Zero retries, zero 429s, zero permanent failures. |

**Success criterion: `cache_pct` of 80–95% on every gap-fill call after the first.** If it
stays near 0, the prefix is diverging — run the inspector, which will name which of the four
conditions in §2 broke.

### Reference points from the audit

- OpenAI dashboard, 2026-07-12 → 07-27: **$26.78 · 34,084,828 tokens · 2,479 requests.**
  Solving against list pricing gives **input ≈ 33.76M (99%), output ≈ 0.32M (1%)** —
  input caching is therefore nearly the entire lever.
- Field counts are real, from `forms_schemas/`: 17 forms, **5,852 fields** total.
  Largest: ACORD 160 (1,135), ACORD 127 (634), ACORD 125 (548).
- Compliance (Yes/No) fields per form, computed with the production detection logic:
  125=27, 126=48, 127=44, 130=24, 131=22, 133=38, 137_CA/CO=46, 138_CA/CO=7, 140=8,
  141=50, 160=48, 186=88, 25=12. **101=0 and 28=0 are correct** — neither form has genuine
  Yes/No disclosure questions.

---

---

## 5b. Full-document coverage — the standing product requirement

**Every word of every uploaded document must reach the model.** A sentence that never
ships produces a blank field that is indistinguishable from a legitimate omission, and
nobody downstream can tell the difference. Chunk when the text exceeds a call budget;
never truncate.

Verified by `backend/tests/test_full_document_coverage.py`, which plants ~400 unique
sentinel tokens through a document deliberately larger than one call budget and asserts
every one of them appears in the text actually shipped — separately for **both** hot-path
stages, since they chunk independently and a regression in one is invisible from the other.

Current state, audited 2026-07-29:

| Path | Behaviour |
|---|---|
| OCR (`ocr_service`) | Iterates **all** pages, and native text is kept for every page. There ARE resource caps — `OCR_MAX_PAGES_PER_DOC` (400) on full-page OCR and `OCR_EMB_MAX_IMAGES_PER_DOC` (60) / `OCR_EMB_MAX_IMAGES_PER_PAGE` (12) on embedded images. Exceeding one does not silently truncate: it logs at ERROR and appends `needs_manual_review`. A >400-page **scanned** document is the real exposure, since those pages have no native text to fall back on. (This row previously read "No page cap", which was wrong.) |
| Extraction (`extraction_service`) | Chunks by section with `_verify_coverage`, which **raises** on any gap. `max_chunks` is explicitly advisory — "never drop sections". The one `text[:max_chars]` is a fallback that fires only when zero chunks were produced (an empty document). |
| Extraction size ceiling | `_check_cost_guardrail` **rejects** above `ACORDLY_MAX_DOC_TOKENS` (500k tokens). A reject, not a silent cut. See C17. |
| `clean_text` (`utils/text_cleaner`) | **Runs before everything, on every upload.** Removes page furniture only. Was deleting 56% of a realistic dec page — see C24. Accounts for every character it drops. |
| Gap fill (`_split_raw_text`) | Full coverage; boundaries at paragraph/line breaks. ✅ sentinel-verified **with an ANSWERING model** — the original test used a silent one, see C25. |
| Compliance pass | Own chunker, full coverage. ✅ sentinel-verified |
| Umbrella probe | Own chunker (`_split_text_on_boundaries`), full coverage, early exit once both dates are known. ✅ sentinel-verified — `tests/test_umbrella_probe_coverage.py`. Was `raw_text[:60_000]`, see C14. |
| `table_extractor` | Skips documents over `TABLE_EXTRACT_PAGE_LIMIT` (40) pages. This is a *supplementary* table pass; the main text still ships in full. |

Two behaviours that are coverage-adjacent and worth knowing about: the chunk loops stop
early once every field/question in a batch has an answer (correct for cost, but see C15 on
supersession), and `eligible_fields` deliberately excludes schedule fields and
underwriter-computed premium/rate fields from the LLM path — those are resolved elsewhere
or must not be guessed at all.

---

## 6. Rules for anyone touching this area

1. **Never** modify `backend/forms_schemas/*.json` — permanent ACORD field definitions.
2. **Never** hand-edit `backend/forms_aliases/` — generated by `scripts/generate_alias_maps.py`.
3. Do not change `COMPLIANCE_BATCH` / `FIELD_FILL_BATCH` to save cost. See §2.
4. Product rule: **blank is better than wrong.** A change that fills more fields but
   introduces wrong values is a regression.
5. The pipeline is **non-deterministic** — `GPT_TEMPERATURE=0.0` but no seed is pinned.
   Byte-identical output across runs is not achievable. Never try to verify a prompt change
   by diffing two live runs; the jitter hides the regression. Verify prompt *shape* offline
   (`scripts/inspect_gap_fill_prompts.py`), then sanity-check one live run.
6. **Before changing any prompt in `pdf_service.py`, re-read §2's five caching conditions**,
   then run the inspector. `tests/test_prompt_prefix_caching.py` fails the build if the
   system prompt splits into variants, if the field list moves ahead of the constant blocks,
   if the shared prefix drops under OpenAI's 1024-token floor, or if batches re-fragment.
7. Tests: `py -m pytest` from `backend/` (use `py`, not `python`). Baseline as of
   2026-07-29: **984 pass / 2 known pre-existing failures**
   (`test_arq_acord125_missing_only` — an `httpx`/`openai` version conflict — and
   `test_normalization`).

### C54 — remaining relationship fixes: fields REMOVED from gap fill, zero prompt change (2026-08-15), cost NEGATIVE

Second pass on the client's relationship-preservation directive. **No prompt text, batch
size, chunking, or call structure changed** — every fix is deterministic ownership, so the
only LLM-visible effect is a SMALLER gap-fill union (fewer questions, same calls or fewer):

1. **ACORD 131 `UnderlyingPolicy_*` grid** (identity attrs of Automobile / GeneralLiability /
   EmployersLiability / OtherPolicy rows) resolves from `coverage_lines` or ships blank —
   ~20 fields off the union when per-line evidence exists. Was the source of the fabricated
   "AUTO policy number + DERIVED renewal dates" underlying row (Pass-1 scalar rules, not
   even gap fill — but the fields are now excluded from BOTH doors).
2. **Declared-absent coverage families** (`WorkersCompensation*`, `Policy_WorkersCompensation*`,
   `UnderlyingPolicy_EmployersLiability_*`) are owned blanks when the package prints the line
   as "No Coverage" and nothing grants it — ~12 more fields off the union on such packages.
   ACORD 130 exempt (it applies FOR workers comp).
3. **`CertificateOfInsurance_CertificateNumberIdentifier`/`RevisionNumberIdentifier`** —
   producer-assigned; owned blank unless a `certificate_number` fact exists. The Pass-1 rule
   that mapped certificate number to `policy_number` is deleted.
4. **The umbrella-period override on ACORD 131 yields to a routed renewal** unless the
   umbrella's own term verifiably has not ended. The PROBE itself is unchanged (still fires
   for 131/25 when the facts are silent — its result still serves the ACORD 25 row, which is
   exempt as a certificate), so probe call count and cost are untouched.
5. Guard-layer only (no LLM interaction): pairwise insurer-roster dedup, single-letter
   name-fragment rejection.

**Test-suite discipline note:** `map_facts_to_form` WITHOUT `pre_filled_gpt` takes the
legacy per-form branch and fires LIVE LLM calls. Every end-to-end test must pass the
combined-path envelope (`{"filled_values": ..., "raw_text_fields": ..., "question_grounding": ...}`)
— `tests/test_remaining_relationship_fixes_20260815.py` documents this at `_env()`.

**Round-12 addendum (2026-08-16 — ONE extraction-prompt change, everything else deterministic):**
LLM call 1's schema gains three keys (`umbrella_um_limit`, `umbrella_uim_limit`,
`umbrella_medical_payments_limit`) plus ~60 words of RULE-1 scoping ("the umbrella policy's
OWN UM/UIM/med-pay, never the underlying auto's; null when unstated") — the round-10
stamping resolver read these keys but nothing wrote them, so a genuine umbrella UM election
could never be captured. Cached-prefix cost ≈ zero (same C33 shape); call 2 untouched.
Deterministic side: the fleet-grid resolver's fact key corrected to `auto_vin_schedule`
(the key extraction actually writes — the round-11 spelling was a phantom that never fired),
and the `underlying_policies`-vs-`coverage_lines` precedence became a CROSS-CHECK
(disagreement on a line's identity blanks and asks; the unrepaired source never outranks
the repaired one). A read-what-is-written source guard now pins every fact key the
relationship resolvers consume against the extraction source.

**Round-7 addendum (2026-08-15, third fresh run — still zero prompt/call changes):** more
fields leave the gap-fill union deterministically: the WC/EL family now suppresses on the
line-inventory CENSUS (≥2 policy-evidenced lines, WC absent — no denial capture needed),
the EBL family (`ExcessUmbrella_EmployeeBenefits_*`) and every
`UnderlyingPolicy_*_ModificationFactor` are owned, watercraft/tail/retroactive-date boxes
became Guard-6 dependents of their trigger questions, and requirement-shaped line entries
(limits, no premium/number) no longer count as granted lines anywhere stamping decides
line presence. The meaning gate gained fact-based witnesses (line premiums, package total,
umbrella limit) and a property-"value" category — post-fill arithmetic only.

**Round-6 addendum (2026-08-15, fresh-run verdict — still zero prompt/call changes):**
the declared-absent suppression now also fires from a `dec_page_entries` denial (RULE 16
keeps denied lines out of `coverage_lines`, so on real runs round 5's version never
engaged — the WC family stays IN the union no longer), line matching is canon-strict (a
bare "Liability" row can no longer hand the EL row to gap fill's replacement), and ACORD
25's `OtherPolicy_*` row family (~9 fields) is owned. The meaning gate's `amt < 100` skip
now exempts only values with no dollar marker — "$34" (a TRIA premium) was stamping into
FOREIGN GROSS SALES through it. Net LLM effect remains: fewer questions, same calls.

### Environment knobs added by this work

| Var | Default | Effect |
|---|---|---|
| `LLM_PREFIX_WARMUP` | `1` | Run one call to completion before fanning out, so the rest hit a warm cache. Set `0` for pure parallel (lower cache hit rate, one less serialized wave). |
| `LLM_PREFIX_WARMUP_MIN_CHARS` | `40000` | Skip warming when the constant prefix is smaller than this — below it the extra wave costs more latency than the repeated prefill costs money. |
| `GPT_CALL_BUDGET_CHARS` | **derived: 994,000** | Input chars per call. No longer a hand-set guess — computed from `MODEL_CONTEXT_TOKENS × CONTEXT_UTILISATION − FORM_FILL_MAX_TOKENS`, times `CHARS_PER_TOKEN_FLOOR`. An explicit override above what the window can hold is **clamped** with a warning. |
| `MODEL_CONTEXT_TOKENS` | `400000` | The model's real context window (gpt-5.4-mini). **Change this when the model changes** — everything else follows from it. |
| `CONTEXT_UTILISATION` | `0.75` | Fraction of the window we occupy. The rest absorbs tokenizer variance and the reply. **This is also the cost-versus-accuracy dial** — see C21. Bigger chunks are cheaper and faster; the model follows the field list worse at ~170k tokens. On a 682k-char package: `0.75` → 1 chunk / ~224k doc tokens per call; `0.50` → 2 chunks / ~137k; `0.35` → 3 chunks / ~84k; `0.25` → 4 chunks / ~49k. |
| `MIN_RAW_CHUNK_CHARS` | `2000` | Floor on the raw-text slice, only so the chunk loop makes progress. Deliberately small — a large floor overrides the call-budget guard and lets the prompt overflow (measured 60,363 vs a 60,000 budget). Hitting it logs an ERROR. |
| `CHARS_PER_TOKEN_FLOOR` | `3.5` | Pessimistic chars/token. Measured 4.01 on a real package (o200k_base); the floor guards dense VIN/class-code/money tables. |
| `GPT_REPLY_RESERVE_CHARS` | **derived: 64,000** | Was a flat 30,000, which under-reserved by more than half against a 16,000-token reply cap. Now `FORM_FILL_MAX_TOKENS × 4`. |
| `CONTEXT_SHRINK_ATTEMPTS` | `5` | How many budget halvings one batch may ride out before giving up. |
| `PROMPT_CACHE_KEY` | auto-detected | Routing hint only. **Detected from the installed SDK at import**, never assumed — the deployed venv runs `openai==1.54.4`, which predates the parameter. Automatic prefix caching works without it (measured 99% cache_pct with it disabled). Set `0` to force off. |
| `EXTRACTION_DOC_TOKENS_PER_CALL` | `14000` | Document tokens per extraction call — **the quality dial for extraction** (C31). 14,000 is the measured-good point; ~170,000 is where the model starts inventing field names. Raising it saves ~$0.11/run and moves extraction toward that cliff. Needs an accuracy baseline first. |
| `EXTRACTION_OVERLAP_CHARS` | `14285` | Carry-over tail from the previous extraction chunk so a fact spanning a boundary stays readable. Its own constant now — **and as of C32 the chunkers actually read it**; until then only the budget reservation did, while the emit sites still computed `chunk_size // 7`. |
| `UMBRELLA_PERIOD_CHUNK_CHARS` | `56000` | Document chars per umbrella-probe call. A **chunk size, not a ceiling** — the probe reads the whole document, stopping once both dates are found (C14). Sized to extraction's measured-good regime, not the gap-fill budget. |
| `EXTRACTION_CONTEXT_UTILISATION` | `0.75` | Fraction of the window one extraction call may occupy. A backstop only — the quality ceiling binds first. |
| `EXTRACTION_REPLY_TOKENS` | `16000` | Reply reserve for an extraction call. Input and output share the window. |
| `GAP_FILL_FULL_RESCAN` | `auto` | Re-ask every field against every document chunk. **`auto` = on iff the document split into >1 chunk** — free on the single-chunk common case, correct on a split one. `1` forces it on, `0` restores the legacy first-answer-wins path (measured dropping 46% of a document for a batch that fills up; logs `COVERAGE_PARTIAL`). |
| `FIELD_BATCH_PACK_TABLES` | `1` | Pack table groups alongside ordinary fields instead of giving each table its own call (C29). Set `0` to revert the cost change; repeating-group atomicity is unconditional either way. |
| `TEXT_DEDUP_MIN_REPEATS` | `0` (**off**) | Paragraph de-duplication in `clean_text`. Off because it was deleting real fleet rows (C24). When >0 a paragraph must repeat at least this many times AND be ≤`TEXT_DEDUP_MAX_LEN` (120) chars. |
| `SLOT_VALUE_DEDUP` | `0` (**off**) | Restores the post-fill per-value sibling dedup. Off by default because it was measured deleting 40+ correct fleet cells in one run — see C18 before turning it on. |
| `MAX_FIELDS_BLOCK_CHARS` | `FIELD_FILL_BATCH × 250` | Constant fields-block allowance that keeps document chunk boundaries stable. |
| `MAX_COMPLIANCE_BLOCK_CHARS` | `COMPLIANCE_BATCH × 800` | Same, for the compliance pass. |

---

## C55 - 2026-08-16 relationship round 13: no prompt or call change, two fewer field families asked

**No LLM call was added, removed or re-batched, and no prompt byte changed.**
Logged anyway because the registry is meant to be able to prove that, and
because the deterministic surface moved in the direction that matters for cost.

**Fields REMOVED from gap fill** (deterministic answers or owned blanks, so the
model is never asked):
* `UnderlyingPolicy_*` on ACORD 131 and the section-form header policy numbers
  now resolve from the dedicated `underlying_policies` fact when
  `coverage_lines` has lost the number - answers that used to be a gap-fill
  guess are now deterministic.
* ACORD 125's Q4 grid and PRIOR CARRIER grid likewise.
* `UnderlyingCoverage_Coverage_AdditionalInterestsIndicator_*` and the four
  `Coverage_Other{Indicator,Description}` rows on ACORD 131 became owned blanks
  (no fact can state them; two of three live ticks were fabrications).
* ACORD 127's two physical-damage deductible columns now stamp from
  `auto_deductible_comp` / `auto_deductible_collision` on real fleet rows.

Measured on the delivered-run fact shape, three forms selected:
`ACORD_125 = 215`, `ACORD_127 = 265`, `ACORD_131 = 180` fields asked
(union 660). Direction is down; the change is small in isolation and is not the
point - it is a correctness change that happens not to cost anything.

**One quality-only change on the evidence gate.** `_quote_is_policy_form_wording`
rejects a grounding quote that points at its own document ("of this
endorsement", "in PARAGRAPH B.1.") or speaks in two or more quoted defined
terms. It runs post-fill, costs nothing, and matters because a kept Yes writes
its grounding quote into the paired Explanation box - so a policy-wording quote
was shipping as the applicant's own explanation.

**Two candidate rules were measured and deleted rather than shipped**, which is
the part worth remembering: a widened coverage-vocabulary test rejected
"Subcontractors are required to carry coverage." (one of C46's own recorded
false blanks), and `_quote_asserts_something` on the Yes side was wrong in both
directions. Neither is in the tree; both are documented at the call site so the
next session does not rebuild them.

## C56 - 2026-08-16 dec-index prompt: purpose + attribution keys, one pass, no call change

**Call sites touched: one system prompt (`_DEC_INDEX_SYSTEM_PROMPT`). No new call,
no batching change, no change to LLM call 1 or call 2.** The dedicated dec-index
pass already existed (C-series, `_harvest_dec_index`); this rewrites what it asks
for. `FACT_EXTRACTION_PROMPT` is byte-identical, so its cached prefix survives,
and call 2 never sees this pass.

**Why.** The old prompt opened "you have exactly one job: list every label:value
pair" and then governed `label`, `value` and `section` with seven rules -
leaving `owner`, `policy_number` and `line_of_business` with **no rule at all**.
Those three carry the relationship the client's 2026-08-15 letter is entirely
about. Measured on the live index for session 221b1da3 (212 verified entries):

| Defect | Count |
|---|---|
| `6E7-40-02---26` vs `6E74002` - one Auto policy, two keys | 77 / 4 |
| `BBC7263 - 26` vs `BBC7263` - one GL policy, two keys | 51 / 8 |
| `6 C 7 - 4 0 - 0 2---26` - Inland Marine keyed WITH its OCR spacing | 13 |
| `General Liability` vs `Commercial General Liability` | 37 / 40 |
| `Commercial Auto` vs `Commercial Auto Liability` | 77 / 4 |
| one phone number, `owner` = carrier on one page and producer on the next | - |
| entries whose label repeats their value (`"CG 21 06 12 23" : same`) | 18 |

Four keys for two policies. The spaced Inland Marine number reached the client's
ACORD 125 Q4 grid and printed there.

**The change, and then the correction.** First cut: an EVIDENCE-versus-KEY
distinction the old prompt never made, a purpose preamble, and four new rules -
7 (label repeating value), 8 (canonical policy number), 9 (fixed line
vocabulary), 10 (owner definitions).

**MEASURED ON A RE-RUN OF THE SAME PACKAGE, and half of it failed.** Scored with
`scratchpad/dec_score.py` against the 221b1da3 baseline:

| metric | was | first cut | verdict |
|---|---|---|---|
| entries | 212 | **261** | recall up - whole IM sub-limit schedule recovered |
| keys with OCR spacing | 1 | **0** | the string that printed on the client's 125, gone |
| label identical to value | 19 | **1** | rule 7 works |
| same value, two owners | 2 | **0** | rule 10 works |
| policies with >1 key | 2 | **3** | **rule 8 FAILED** - model invented `6J74002---26` |
| off-vocabulary line values | 2 | **7** | **rule 9 FAILED** - `Liability`, `Automobile`, ... |
| GL class table entries | 6 | **1** | **REGRESSION - see below** |

**The regression was mine.** The rewritten rule 5 added *"never split one printed
fact into two entries"* immediately before the `'Payroll $39,300'` example, and
the model read "do not split" as "collapse the row": the GL class table came back
as ONE entry (`"Location 001 91580 Prem Basis" = "Payroll"`), losing **$39,300,
$350,000, class 91585 and the Total Cost basis** - the client's own headline
number, gone from the index. Rule 5 is REVERTED to its pre-2026-08-16 wording,
which still emits basis and amount as two entries but preserves both values. A
recorded pair beats a tidy single entry with the number missing. (Severity note:
`gl_class_code_schedule` is extracted by LLM call 1 - untouched - and is the
meaning gate's witness for the payroll-vs-sales case, so the FORM was not at
risk. The loss was dec-index corroboration.)

**Rules 8 and 9 are deleted.** Asking a model to elect a canonical identifier is
identity arithmetic, not judgment, and it measurably got worse at it. That work
moved to `_canonicalise_dec_entry_keys`, called immediately after
`_verify_dec_entries` in `merge_facts`. On the same live file: 8 policy keys ->
5 (four real policies plus package-level `null`), off-vocabulary line values
7 -> 0, and `label`/`value` provably untouched so the verification guarantee
holds. Election order is longest-normalised, then fewest spaces, then longest
raw - the middle clause exists because the first tie-break elected
`'6 C 7 - 4 0 - 0 2---26'`, the exact string this whole entry is about. Pinned by
`tests/test_dec_entry_key_canonicalisation.py` (12), including anti-rot tests
that fail the build if rules 8/9 return to the prompt or if rule 5's preserving
wording is lost again.

**What survives in the prompt:** the purpose preamble, the evidence/key
distinction, rule 1's "exhaustiveness is never a judgment call", rule 7 and
rule 8 (owner definitions, renumbered from 10). All measured, all net-positive.

**Two things deliberately NOT done.**
1. *No form catalogue.* An earlier draft named the 17 forms and their lines. It
   was cut: the model does not choose forms, so it cannot act on the list, and
   naming forms creates pull toward "only record what fills a box" - which is
   the exact failure (under-reporting) this pass exists to fix. Rule 1 now
   states that exhaustiveness is never a judgment call and says where judgment
   DOES apply. Keep those together.
2. *No blocklist of observed failures.* A draft rule 5 listed the two specific
   violations seen in the file. Cut for the same reason the codebase rejects
   token blocklists elsewhere - third incident, third token set. Rule 5 states
   the principle that generates them instead.

**Rule 9's eight values are `_canon_line`'s eight classes, deliberately**, so the
model's answer and the canonicaliser agree by construction rather than the code
repairing the model. Do not add "Builders Risk" (`_canon_line` returns None) or
"Contractors Equipment" (maps to inland_marine).

**Cost, measured not estimated** (`ast.literal_eval` on both versions of the
constant): the system prompt goes 2,528 -> 4,383 chars, **~632 -> ~1,095 tokens,
so +463 tokens per indexed chunk**. An earlier draft of this entry said ~450 as a
guess, then the first cut measured +759; deleting rules 8 and 9 gave ~296 of that
back. The pass is gated to chunks clearing
`DEC_INDEX_MIN_AUTHORITY` (a handful per package), so the absolute add is small
against a dec chunk's own thousands of tokens - but it is not negligible on a
package whose declarations spread widely, and `DEC_INDEX_MAX_CHUNKS` remains the
emergency valve. It invalidates this pass's own cached prefix once, then
re-warms. No other stage is affected: `FACT_EXTRACTION_PROMPT` is byte-identical
and LLM call 2 never sees this pass.

**Known limit, stated rather than assumed.** A prompt raises the hit rate on a
canonical key; it does not make it deterministic. Rule 5 was already correct and
was violated twice in the file above. The durable form of this fix is
`_canonicalise_dec_entry_keys()` immediately after `_verify_dec_entries` - prompt
asks, code enforces, the same shape `_verify_dec_entries` already applies to
literal presence. Deliberately NOT shipped in this change so the prompt's own
effect can be measured on a re-run of the same package first.

## C58 - 2026-08-16 the declarations index now carries all six recorded fields

**Owner: "why cant we just send whole json, i dont want to reduce anything from it,
unless there is a reason ... make it use fully and not just for these two fields but
all the fields."**

`_render_dec_index` shipped four of the six recorded fields to LLM call 2 - section,
label, value, owner - and dropped `policy_number` and `line_of_business` at render
time. Those two are the join keys the entire deterministic layer runs on
(`_resolve_section_policy_identity`, `_policy_numbers_by_line`, `_line_denied_by_
document`, `_build_amount_witnesses`), so the C56 canonicalisation that finally gave
each of the client's four contracts ONE key improved the deterministic path and did
nothing at all for the model. Call 2 was left inferring a value's contract from the
page heading.

**Measured wrong six times on the client's own package.** The umbrella's SCHEDULE OF
UNDERLYING INSURANCE prints the GL policy's carrier, number, period and products
aggregate, plus the auto policy's carrier and number, under a heading reading
`C O M M E R C I A L  U M B R E L L A  S C H E D U L E`. The entries carry the right
keys; only the rendering threw them away.

**Shipped: group on (section, policy_number, line_of_business), not section alone.**
Headings become `[page section | policy <number> | <coverage line>]`. That one page
now renders as three headings - umbrella / GL / auto - each owning its own rows.

**Why not send the raw JSON, measured rather than argued:**

| option | chars | tokens | verdict |
|---|---|---|---|
| four fields (old) | 15,906 | ~3,976 | loses the two join keys |
| **all six, grouped headings** | **18,316** | **~4,579** | **shipped: +15%** |
| raw JSON compact | 51,435 | ~12,858 | 2.8x for the same six facts |
| raw JSON pretty | 62,398 | ~15,599 | 3.4x |

Nothing is reduced - the JSON's punctuation is. Keys ride the HEADING because they
are near-constant within a group; per-line repetition was ~60%. 33 -> 42 headings.
Index still renders as ONE part against the 224,000-char budget (12x headroom), so
the C23 co-visibility invariant is untouched. It sits inside the cached prefix, so
the marginal cost bills at ~10%.

**`owner: other` is now printed too** - it was suppressed as "the default, so it says
nothing". The live 261-entry package disproves that: exactly ONE entry carries it and
it is the Drive Other Car named individual (ERIN ROYAL), the value that has been
mistaken for a driver (C22) and for the applicant. `test_owner_is_rendered_only_when_
it_carries_information` encoded the old assumption and was reversed with the count.

**De-dup key widened to include the policy.** Keying on (section, label, value) alone
collapses one label:value printed for TWO policies into one entry and silently keeps
whichever came first - a real shape here, where three policies share a term.

Zero new LLM calls, zero change to Stage B, zero change to the compliance pass.
Tests: +5 in `test_dec_index_stage_a.py` including the client's literal
underlying-schedule shape. Suite **3025 passed / 2 failed** - the same two
pre-existing unrelated failures, zero regressions.

## C59 - 2026-08-16 dec-index rule 7 scoped so it stops arguing with rule 5

**The GL class table regression, fixed at the cause.** Rule 7 shipped in C56 as the
GENERAL instruction "Give the value the caption printed above or beside it". That is
a second theory of what a label IS, and on a rating table it beat rule 5's. Rule 5:
a basis word beside an amount labels THAT AMOUNT ('Payroll' labels '$39,300'). Rule 7
pointed one row higher at the column header ('Prem Basis'), made 'Payroll' the VALUE,
and the amount had no entry left to live in.

Measured across nine runs of the same package:

| | GL class-table entries | $39,300 | $350,000 | class 91585 | 'Total Cost' |
|---|---|---|---|---|---|
| 7 runs before C56 | 6 | present | present | present | present |
| 2 runs after C56 | 1 | GONE | GONE | GONE | GONE |

**Rule 5 was byte-identical across that change and was wrongly blamed first** - the
revert landed and the table stayed collapsed, which is what exonerated it. Diffing
the COMPILED prompt string rather than the file is what settled it; do that first
next time.

Rule 7 now states its one case (label and value would be the SAME TEXT) and yields
explicitly: "rule 5 wins: a basis word beside an amount labels THAT AMOUNT, and the
amount must still be recorded." The `label == value` defect it was built for (19 -> 1
on the C56 run) is untouched by the scoping - that shape is exactly identical text.

Cost: +524 tokens per indexed chunk against the pre-C56 baseline (was +463; the
yield clause is ~61). Prompt only - zero new calls, zero change to LLM call 2.
Tests: `test_rule_7_states_its_one_case_and_yields_to_rule_5` fails the build if
either the scope or the precedence clause is reworded away. Suite **3026 passed /
2 failed**, the same two pre-existing unrelated failures.

**CONFIRMED on run 47556cd2 (2026-08-16 06:14).** The GL SCHEDULE section returns
all six class-table entries - `Prem Basis: Payroll`, `Exposure: $39,300`,
`Prem Basis: Total Cost`, `Exposure: $350,000`, `91580 Contractors - Executive
Supervisors`, `91585 Contrctrs-sub work-in connection`. All four lost values are back.

**`SCHEDULE OF UNDERLYING INSURANCE` came back with it** - 20 entries -> 0 on the two
C56 runs, restored here, and now rendering as two correctly-keyed headings (BBC7263 /
General Liability and 6E7-40-02 / Commercial Auto) thanks to C58.

**Entry count fell and recall ROSE.** raw 400 -> 244, verified 261 -> 222, while 36 of
36 checked package values are present (every premium, limit, deductible, policy number,
carrier, class code, exposure, VIN and symbol on the Orbin ground-truth list). The count
was measuring duplicate and label-echo entries, not data. **Do not use entry count as a
recall metric on this pass** - it moved in the opposite direction to quality twice in
one day and cost two runs to work out.

Scorecard on the same run: 0 policies with more than one key, 0 off-vocabulary line
values, 0 values claimed by two owners, index renders in ONE part at 15,231 chars.

**Two residuals, neither a regression, both logged not fixed:**
1. Some auto rating rows come back as whole-row dumps rather than cells -
   `COVERED AUTOS LIABILITY: '01 $ 1,000,000 .$ 1,496.00'`, `COMPREHENSIVE:
   '07 SEE ITEM SIX . 134.00'`. Rule 5 forbids concatenating cells; the values are
   present and literally printed so verification passes, but a cell would retrieve
   better than a row.
2. The account number `0482854` is attributed as a `policy_number`, creating a
   phantom fifth policy. Blast radius is one entry - the account-number entry
   itself - and it carries no line, so no section resolver can act on it.

## C60 - 2026-08-16 two residuals from run 47556cd2: one code, one prompt

**Deliberately split by KIND, because the day's record is unambiguous.** On this pass,
prompt changes are 0-for-2 (rules 8/9 made both their own metrics worse; rule 7
collapsed the GL class table) and code changes are 2-for-2 (`_canonicalise_dec_entry_
keys`, the six-field render). So anything decidable from the recorded entries alone
goes in code, and only what genuinely needs the page in front of it stays in the prompt.

**1. The account number became a fifth policy - CODE.** The common declarations page
belongs to all four contracts, so asked which one an entry is from, the model reached
for the only identifier in front of it: `Account Number: 0482854` keyed itself.
`_entry_self_attributes_its_own_identifier` clears a `policy_number` when BOTH hold -
it equals the entry's own `value`, its own label does not say "policy", and no other
entry is filed under it. Runs BEFORE the printing election so a phantom key can never
become a head and pull real printings into its group.

**No denylist of label words** ("account", "agent no", "claim number", "form number").
The tell is structural and needs no vocabulary: a contract key is something OTHER
entries are filed under; an identifier supported only by the entry that prints it has
attributed nothing. `POLICY NUMBER: 6C7-40-02---26` is the same self-reference and is
KEPT because its own label says the value is a policy number. A thin document where a
real policy legitimately has one supporting entry is untouched by the second condition.
Verified on 47556cd2: 5 distinct policies -> 4, class table intact, the value `0482854`
still present as evidence (only the KEY was cleared, never the entry).

**2. Auto rating rows came back as whole rows in one cell - PROMPT, unavoidably.**
`COVERED AUTOS LIABILITY: '01 $ 1,000,000 .$ 1,496.00'`, `COMPREHENSIVE: '07 SEE ITEM
SIX . 134.00'`. Nothing is lost - the row IS printed, so `_verify_dec_entries` passes
it - but a symbol, a limit and a premium sharing one value cannot be retrieved as any
of the three. Splitting this in code is impossible: the column headings ("Covered
Autos", "Limit", "Premium") exist on the page and NOT in the entry, so code would have
to invent the labels, which is the one thing rule 5 forbids.

Fixed as an EXAMPLE appended to rule 5's existing anti-concatenation clause, not a new
rule. That distinction is the whole lesson of C59: a new rule competes with the old
ones and can win on cases nobody considered; an example narrows an existing rule's
scope. **Scoped to CAPTIONLESS runs of figures on purpose** - `Exposure: $39,300`
carries its own caption inside the value and is the exact shape that restored the class
table, so it must stay legal.

Cost: +about 45 tokens per indexed chunk. Suite **3031 passed / 2 failed** (same two
pre-existing), +5 tests including an anti-rot pair pinning both the new rule 5 wording
and the `Payroll $39,300` clause it must not displace.

**MEASURED on run c655a44b - item 1 shipped, item 2 REVERTED.**

Item 1 works. `[Common Declarations | policy 0482854]` is now `[Common Declarations]`,
distinct policies 5 -> 4, and the value `0482854` is still present as evidence: only
the false key was cleared.

Item 2 did nothing. The auto rows came back BYTE-IDENTICAL - `COVERED AUTOS LIABILITY:
'01 $ 1,000,000 .$ 1,496.00'`, `COMPREHENSIVE: '07 SEE ITEM SIX . 134.00'`. The example
was **removed rather than kept as harmless**, and that is the decision worth recording:
a measured-useless instruction is not neutral in this prompt. Rule 7 looked harmless
too and cost the GL class table for three runs. Every instruction here has to earn its
place or come out.

Nothing downstream needed the split. `auto_covered_symbols` owns the covered-auto
symbols with per-coverage attribution (2026-08-07), `_resolve_lob_premium` owns the line
premiums, the limits have their own facts. The cost of the row shape is a little Stage A
retrieval quality on those boxes - no value and no relationship is lost. Splitting a
rating row positionally in code is C46's phantom-row pattern and was not attempted.

**THE RECORD FOR THE DAY, because it should decide how the next defect is approached:**

| change | kind | outcome |
|---|---|---|
| C56 rules 8/9 (canonical keys, line vocabulary) | prompt | both metrics WORSE - deleted |
| C56 rule 7 (general caption instruction) | prompt | destroyed the GL class table |
| C59 rule 7 scoped | prompt | fixed what C56 rule 7 broke - net zero |
| C60 rule 5 example (split rating rows) | prompt | zero effect - reverted |
| `_canonicalise_dec_entry_keys` | code | worked first run |
| C58 six-field render | code | worked first run |
| C60 self-attributed key guard | code | worked first run |

Prompt 0-for-3 on net-new capability; code 3-for-3. **Anything decidable from the
recorded entries alone belongs in code.** Reserve the prompt for what genuinely requires
the page in front of it, and expect to pay a full run to find out whether it worked.

**State of the index at c655a44b (222 entries, stable across two consecutive runs):**
GL class table complete; 4 real policies each with ONE key; 0 off-vocabulary lines;
0 values claimed by two owners; carrier-to-policy pairing correct on both carriers;
`COMMERCIAL UMBRELLA SCHEDULE` and `SCHEDULE OF UNDERLYING INSURANCE` each split into
per-policy headings so call 2 can no longer read the GL carrier as the umbrella's.

## C61 - 2026-08-16 five audit findings traced to mechanism, five code fixes, zero prompt changes

**Method change, on the owner's direct instruction: attribute first, fix once.** Every
finding from the fresh-run audit (session 3855121c) was traced to its exact mechanism
before anything was edited. The dec-index JSON was CORRECT for all five - four breaks
were in call 2's guards/resolvers, one in a deterministic consumer. No LLM call, no
prompt, no batching was touched; the registry entry exists because the gate changes
alter what gap fill may ship.

| finding | mechanism | fix |
|---|---|---|
| 131 SQ FT OF BLDG OCC = 4800 (street no.) | number boxes outside the meaning gate; addresses witness nothing | "address" pseudo-witness (value-shape only) + address-only rule; "Enter number" boxes in scope for it (zero rule stays amount-only); "area" category added LAST |
| 131 Q2 ISO edition = "11 20" (the AUTO form's) | no resolver owned the field; gap fill borrowed across the line heading | `_resolve_underlying_gl_form_edition`: CG 00 01's own edition from GL-line entries or owned blank; endorsement editions never answer |
| 127 FACTOR=01 / SEAT=5 / RADIUS=50 vs printed "RADIUS: NA" | unbound schedule columns fell to gap fill; model invents rating cells | `_resolve_vehicle_rating_cell`: schedule row -> auto dec entry -> owned blank on positive auto-dec evidence; legacy sessions keep gap fill |
| 131 Q7 false "Y" on a composed sentence | punctuation-free table page = ONE "sentence"; 75% token coverage vs a page's vocabulary passed | `_QUOTE_SENTENCE_MAX_CHARS=400` cap on the paraphrase fallback only; verbatim containment untouched |
| 125: 6E7-40-02---26 in Q4, 6E74002 in prior grid | `underlying_policies` rows carry the raw printing; grid stamped it unjoined | `_canonical_policy_printing` joins any printing to the elected dec-index key; applied on a COPY in `_prior_coverage_grid` - the stored fact keeps its verbatim printing |

**A regression caught by probing the REAL index before shipping, not by a re-run:**
"location" as an address-label trigger captured the GL schedule's own row labels
("Location 001": "91580 Contractors...", "Location 000": "...$150"), making the class
codes and an endorsement premium address-only witnesses. The trigger was cut to the
VALUE's own structural shape (street/ZIP) plus the literal word "address". Verified on
the live 222-entry index: 91580/91585/150 carry no address witness; 26,680 stays cost;
300 stays premium; the address-only set is contact-block digits alone.

Tests: `tests/test_client_findings_20260816.py` (21, all driving real functions with
the run's literal values, including the pre-fix mechanism repro for the Q7 table-page
hole so the cap test cannot go vacuous). Suite **3052 passed / 2 failed** - the same
two pre-existing unrelated failures, zero regressions.

**Proven offline vs. needs the next run:** F1/F2/F3/F5 are deterministic and verified
against the real index/facts shapes offline. F4 closes the only structural hole in
`_quote_grounds_claim`, with the mechanism reproduced offline; whether the MODEL still
answers Q7 "Y" (to be then blanked by the gate) only a live run shows. NAIC stays
unpopulated by design - the numbers appear nowhere in the package's dec pages, and a
pair that cannot be evidenced is not stamped. The umbrella $3M/$1M conflict (client
defect 5) is deliberately deferred by the owner.

## C62 - 2026-08-16 round-2 audit findings: six code fixes, one deliberate non-fix, zero prompt changes

Run 34efbef4 confirmed all five C61 fixes held (SQ FT, ISO edition, rating cells, Q7,
prior-grid printings). These are the findings that surfaced once they did - same method,
attribute first, fix once, all deterministic. LLM calls, prompts and batching untouched;
registry entry because two guards change what gap fill may ship.

| finding (literal, from the forms) | fix |
|---|---|
| 127 interest block: name "Trust", an address, REFERENCE/LOAN # = the package's own GL policy number | `_blank_pseudo_entity_names` (a bare legal-structure word is an entity TYPE, not a name; de-named row falls to the orphan machinery) + `_blank_own_policy_as_reference` (canonical identity check - every printing of the contract caught) |
| 127 Q4 "Y" on '"autos" you lease, hire, rent or borrow' - the Business Auto form's own DEFINITION text, verbatim | `_is_policy_wording_fragment` veto in the gate's `_present`: ISO's quoted-lowercase-term drafting signature marks coverage-form language, which never evidences applicant conduct. Structural, not topical - the standing no-topic-matching rule is untouched. THE MOST "WE" PAY (uppercase) does not match |
| 131 #28: 0 swimming pools / 0 diving boards | REVERSED C61's number-box zero exemption, on measurement: the exemption shipped and the very next run fabricated count zeros. Number boxes now need a category-matched stated zero - deliberately without the untyped any-zero escape, or the umbrella's real $0 SIR unlocks every fabricated count |
| 125: BBC7263 in Q4 vs BBC7263 - 26 in the prior grid | `_join_policy_printings` - the canonical join now runs on EVERY PolicyNumber box after all passes; per-resolver joining was whack-a-mole |
| index: "CG 99 09 12 19" a fifth policy key | `_ISO_FORM_NUMBER_KEY_RE` clearing in `_canonicalise_dec_entry_keys` - two letters + four 2-digit groups is the ISO form+edition shape; WC-99-123 (three-digit group) and BBC7263 - 26 (three letters) cannot match. Verified on the real file: 5 keys -> 4 |
| 131 Q9 blank while the index PROVES it ($185 hired + $137 non-ownership premiums) | `_resolve_umbrella_hired_nonowned` - a premium paid IS the coverage provided; deterministic "Y" + an explanation built solely from the two verbatim figures. Conjunctive: one premium or a $0 falls through to the compliance pass |

**Deliberately NOT fixed:** "0 - 25" as # FULL TIME EMPL. The document literally prints
"NUMBER OF EMPLOYEES: 0 - 25"; blanking document-grounded data labeled by the document
itself would violate the standing rule against blanking legitimate answers. It is the
auto non-ownership rating band - noted, kept.

Tests: `tests/test_client_findings_round2_20260816.py` (18) + the C61 zero-exemption
test reversed in place with its measurement. Suite **3068 passed / 2 failed** - the
same two pre-existing unrelated failures, zero regressions (every evidence-gate suite
green under the wording-fragment veto). End-to-end proof on the real 34efbef4 index:
form-number key cleared, Q9 resolves "Y", Trust blanked, loan-ref blanked, Q4 printing
joined.

**Needs the next run:** whether the model still tries the Q4 "Y" (to then be vetoed)
and whether Q9's deterministic Y lands on the printed form. Everything else is proven
offline. Umbrella $3M/$1M conflict remains deferred by the owner; NAIC stays blank by
design.

## C63 - 2026-08-16 round 3 (run 7e95e3ae): class-level fixes, one withdrawn by the regression wall

All six client items and every round-1/2 fix HELD on this run - verified on the forms
before anything was touched. Four fixes shipped, one was written and WITHDRAWN before
shipping because the suite caught it destroying a pinned contract. Zero prompt changes.

| finding (literal) | fix |
|---|---|
| "0482854" back as a key with FOUR lines - multi-entry attribution outflanked the single-entry guard | THE INVARIANT, not another instance: a contract key must be printed under a policy-labelled entry somewhere ("POLICY NUMBER", "Policy", "POL"); an unwitnessed key is cleared everywhere it appears. CONDITIONAL on the document proving it labels policy numbers at all, so recordings without policy labels (and every older synthetic fixture) are untouched. Real file: 5 keys -> 4, each with one line |
| 127 RADIUS = 104 (the DOC TERRITORY, misfiled by call-1 into the schedule's radius column) | `_resolve_vehicle_rating_cell` REORDERED: the dec's own printed cell first, and its stated "NA" VETOES the schedule fact. A resolver must not trust a derived fact over the document's printed cell |
| 131 # EMPL = "1", row #28 "1 story / 1 unit" | `BusinessInformation_EmployeeCount` joins `_resolve_exposure_count` (stamps the document's own "0 - 25", owned blank without it); `_resolve_property_rating_row` owns the #28 family. EXACT pairing - see below |
| Q4 printed "6 C 7 - 4 0 - 0 2---26" (only the letter-spaced printing survived verification this run) | `_despace` on ELECTED keys only: fires on the OCR fingerprint (>=3 single alnum chars space-separated), so "BBC7263 - 26" can never match; entry VALUES keep the verbatim printing |

**WITHDRAWN before shipping - the 125 %-of-sales owned blank.** The suite caught it
red-handed: `test_a_percentage_the_document_prints_survives` pins the 2026-08-14
contract that a DOCUMENT-STATED percentage survives with its citation (rule 8d +
`_percentage_is_stated`). A blanket blank deletes legitimate answers; the fabricated
"30%" is a QUOTE-GATE defeat to be fixed from the run log's actual grounding - queued
with the 127 Q2/Q12 borrows.

**Tripped twice more and corrected in-session, which is the wall working:** widening
the exposure-count resolver to `(Contractors|BusinessInformation)_<any count>` re-made
a mistake whose history was already written in test_run_20260813i ("broke three pinned
ACORD 125 behaviours") - 5 suites went red, the regex was narrowed to exactly
`Contractors_(Full|Part)Time...` + `BusinessInformation_EmployeeCount`, all green.

Tests: `tests/test_client_findings_round3_20260816.py` (12, literal values, including
pins that the invariant stands aside without policy labels, that BBC7263 - 26 can never
be despaced, and that the percent boxes are DELIBERATELY not owned). Suite **3080
passed / 2 failed** - the same two pre-existing unrelated failures, zero regressions.
End-to-end on the real 7e95e3ae index: 4 clean keys, RADIUS blank against the polluted
schedule fact, # EMPL = "0 - 25", row #28 owned, the 125's employee boxes untouched.

**Open, waiting on the run log (grep `evidence_gate KEPT_YES` / `question_grounding`):**
127 Q2 "Y" (>50% employees), Q12 "N" (drivers not covered by WC - on a package whose
dec DENIES WC, "N" is at best unknowable), the 30% quote-gate defeat, and the CCC/Q6
text borrows. Umbrella $3M/$1M stays deferred by the owner.

## C64 - 2026-08-16 the producer's review screen: three false hard stops, an unresolvable fix loop, and the umbrella conflict

Reported from a live session on run f50825ae. No prompt change, no LLM call change.

**W1/W2 - "Umbrella policy period alignment" x3, none of them real, and none
fixable.** The screen read *"Umbrella effective date (07/15/25) does not match
GL/policy effective date (07/15/2026)"* and neither date is wrong:
`umbrella_effective_date` is read off the umbrella's own DEC PAGE (on a renewal, the
EXPIRING term) while `effective_date`, after `_route_renewal_dates`, is the DERIVED
PROPOSED renewal term. The validator compared expiring against proposed and called the
difference a misalignment - **the client's own chronology rule broken inside a
validator**, and as `hard_stop` it also capped SQS at 60.

It was UNRESOLVABLE by construction, which is what the producer hit: the fix panel
offers the two dates it compared, so 07/15/2026 -> 09/15/2026 simply re-raised the
issue as 09/15/2027. No value a human can type makes an expiring term equal a proposed
one. `_package_period_on_umbrella_footing` now returns the term that shares the
umbrella's footing - `prior_*` on a routed renewal - and STANDS DOWN when there is no
comparable term rather than falling back across footings. The message names which term
it used. The sibling Auto/WC check is untouched and still fires: those dates come off
their own dec pages, so they share the umbrella's footing by construction.

**W3 - "GL coverage detected but no revenue or payroll found"** on a package whose GL
schedule prints Prem Basis: Payroll / Exposure: $39,300. Two fixes: the AUTHORITATIVE
source is now checked first (`gl_class_code_schedule`'s basis+amount pair, the client's
own "exposure amount + exposure basis" relationship in one row - independent of the dec
index surviving, of which label shape the recorder chose, and of the derived flag); and
`dec_states_payroll_basis` is now derived BEFORE `_backfill_empty_facts_from_entries`
instead of after, because both sat in one try block whose except pops `dec_page_entries`
- any backfill exception took the payroll flag down with the entries.

**W4 - the $3M/$1M umbrella conflict (client defect 5).** The withhold machinery was
sound but could only see amounts the MERGE rejected, and a limit stated in a
certificate or a narrative sentence never arrives as a competing candidate for the same
fact - so one document in, no reject recorded, and the most-repeated figure stamped
unchallenged. `_stated_umbrella_limits` now reads the sources that DO carry it:
narrative remarks and umbrella-line `coverage_lines`. The clause is matched WHOLE to
the sentence end - a first-amount-only capture was tried and found half the evidence
(it returned the $3,000,000 the form already had and missed the $1,000,000 that makes
it a conflict). Narrow by construction: only clauses NAMING umbrella/excess, only
amounts of $1,000,000+, and extra amounts can only ever WITHHOLD a stamped value
pending confirmation - never change a fact, never fill a box.

Tests: `tests/test_review_screen_warnings_20260816.py` (13, the producer's literal
screen values), including pins that a genuine misalignment still fires, that a
non-renewal is byte-identical, that the Auto/WC check still fires, that agreement never
manufactures a conflict, and an anti-rot ordering check on the payroll derivation.
Suite **3093 passed / 2 failed** - the same two pre-existing, zero regressions.

**W1 HAD A SECOND COPY, found by the producer immediately after C64 shipped.**
`sqs_service.evaluate_stops` re-implemented the identical comparison
(`umbrella_effective_date` vs `effective_date`), so the screen still showed the legacy
copy's own wording - "Umbrella and GL policy periods misaligned." - with no dates in
it. **That is the THIRD time this exact duplication has cost a fix** (Auto hired/
non-owned symbols; Umbrella SIR - both in CLAUDE.md), and the legacy engine is the copy
that drives the 60/85 caps, so the hard stop survived the fix that was supposed to
remove it. The legacy site now delegates to `_package_period_on_umbrella_footing`
(lazy import - `cross_form_validator` already imports `sqs_service`, so a module-level
one would be circular) and falls back to the old pair only if the import fails.
Verified end-to-end on the client's fact shape: both misalignment messages and the GL
exposure warning are gone, a genuine misalignment still fires, and
`test_the_legacy_engine_delegates_instead_of_reimplementing` fails the build if anyone
re-derives the comparison there. Swept the remaining line-date comparisons: the Auto
and WC checks read their own dec-page dates and share the umbrella's footing by
construction - correct, untouched.

**Verified offline; needs the next run to confirm live.** W4 depends on where the
$1,000,000 actually lives in this package's facts - if the COI's figure is neither in
the narrative nor in `coverage_lines`, the withhold still will not fire and the real
gap is that certificates are excluded from the dec index by recorder rule 6 (the
one-clause change already scoped in C60).

## C65 - 2026-08-16 removing a false warning is only half the job: the real unknown now speaks

**Producer, immediately after C64: "if there are real warnings and hard stops then why
are you hiding them".** Correct instinct, and the gap was real. C64 removed a
comparison that could never be satisfied (the umbrella's EXPIRING dates against the
package's DERIVED PROPOSED dates - this package's umbrella and GL are perfectly
concurrent at 07/15/25-07/15/26, so there was no misalignment to report and no value a
human could type would create one). But it put NOTHING in its place, and there IS
something to say: on a renewal, every per-line date (`umbrella_*`, `auto_*`, `wc_*`,
`property_*`) is read off that line's own dec page, so every one of them is an EXPIRING
date - and the routing only ever handled the package pair, so each underlying line's
PROPOSED term stayed unknown and unannounced.

`_route_renewal_dates` now records `renewal_lines_expiring` (the lines whose stated
term has already ended) and `evaluate_stops` turns it into one message:

    Renewal: the umbrella's proposed policy term is not stated in the documents -
    confirm the proposed effective and expiration dates.

**Nothing is derived per line, deliberately.** The package term is derivable (a renewal
takes effect when the expiring policy ends); an underlying line's is NOT - the
underlying policies may renew on their own dates, and guessing is exactly what "unknown
must remain unknown" forbids. So the fact is recorded, the question is asked.

**recommended, not a hard stop** - an unknown the documents do not answer must not cap
the package at 60, which is the same mistake the expired-term stop made before C61.
Registered in `_LEGACY_MESSAGE_RULES` with cluster "Umbrella policy period alignment",
tier `recommended`, code `legacy_umbrella_renewal_term_unknown`, and resolution
`_r_field("umbrella_effective_date", "umbrella_expiration_date")` - verified live to
return `mode: field` with both dates, so Resolve opens two typeable boxes instead of
the dead button the legacy-rules work exists to prevent.

Tests: +6 in `test_review_screen_warnings_20260816.py` (22 total), including a
future-dated line NOT being flagged, the warning never appearing in `hard`, and the
full classify+resolve round trip. `test_legacy_rules.py` (65 anti-rot guards) green -
the new row is shadow-free and its code is namespaced. Suite **3102 passed / 2 failed**
- the same two pre-existing, zero regressions.

---

## C63 - "Absence is not No": the risk-transfer booleans get a third state (2026-08-17)

**Prompt change, LLM call 1 schema only. Cost impact: ~40 words added to the cached
extraction prefix. No new call, no new pass, no change to call 2.**

Client 2026-08-17 item 3: *"Absence of information should not become No... Primble
needs to distinguish an affirmative No from information that simply was not stated or
could not be determined."*

**Measured before changing anything.** Dumping a live session's flags:

```
FLAGS (44)
  TRUE  (11): ...
  FALSE (29): ...
  NULL  (0): -
```

**Zero of forty-four booleans could say "unknown".** Every text field in the schema is
`string or null`; the booleans were bare `boolean`, so the model had no third option
and answered `false`. Probe runs B and D then showed a dec page that never mentions
additional-insured status fighting a certificate that requires it - three conflict
cards about requirements nobody had asserted either way.

**Only three keys changed**, and the distinction is deliberate:

* `risk_transfer.additional_insured_required`, `.waiver_of_subrogation_required`,
  `.primary_noncontributory_required` are now `boolean or null`. These assert something
  about a CONTRACT REQUIREMENT, so `false` is a claim and needs to be earned.
* The 40 `has_*` coverage flags are UNCHANGED. There `false` means "no such coverage
  was detected in this document" - a finding, not a claim - and every consumer already
  reads them that way.

**Nothing downstream had to change to accept null**, verified rather than assumed: the
three readers in `sqs_service` all test `is True`; `_merge_risk_transfer` skips a
non-bool instead of OR-ing it; and an absent sub-key is skipped by
`_structured_dict_field_conflicts`. So "not stated" simply stops manufacturing an
answer.

**A prompt is a request, so there is also a check.**
`extraction_service._drop_unstated_risk_transfer` removes a `false` whose topic the
uploaded text never mentions, using the legally-standard printings of each requirement
("additional insured", "waiver of subrogation", "primary and non-contributory"). It
runs PER DOCUMENT in `extraction_pipeline` against that document's own text - the
cross-document detector compares per-doc facts, not the merge, so dropping only from
the merged set would have left the cards exactly where they were. A `true` is never
touched, and a `false` printed against real wording ("no waiver of subrogation is
required") survives because the phrase is present.

Tests: `backend/tests/test_absence_and_context_20260817.py` (27), including the probe
runs' literal shape, an affirmative "No" surviving on all three keys, a real
disagreement still conflicting, and an anti-rot guard that fails the build if any of
the three loses `or null`.

---

## C56 - 2026-08-18 round 15: no prompt or call change

Three deterministic fixes (package-header policy count, zero-padded quantity
rejection, two evidence-gate quote rules). **No LLM call added, removed or
re-batched; no prompt byte changed.** The two quote rules run post-fill and cost
nothing. Field counts move down slightly - the 125 header and the two vehicle
quantity boxes are owned blanks rather than questions. Logged so the registry
can still prove no prompt moved.

---

## C76 - 2026-08-22 dec-index prompt: three recall rules, one guard the verifier cannot enforce

**One prompt changed: `_DEC_INDEX_SYSTEM_PROMPT` (LLM call 1, dedicated dec-index
pass). No call added, removed or re-batched. `_EXTRACT_PROMPT_PREFIX` /
`_EXTRACT_SCHEMA` are byte-identical, so the facts/flags cached prefix is untouched
and `PROMPT_VERSION` / `SCHEMA_VERSION` stay at v12** - the index pass has no cache
(`_harvest_dec_index` does no `_cache_get`), so a prompt edit here can never serve a
stale index and a version bump would only force a needless full re-extraction of
every cached document.

Cost: 4,627 -> 7,806 chars of system prompt (~+800 tokens) per INDEXED chunk only -
the chunks clearing `DEC_INDEX_MIN_AUTHORITY`, not the whole document. It is a
constant system message, so it caches.

**ADDED**

- **Rule 6b - tables of contents and form indexes.** The only new rule the
  verification gate physically cannot enforce: in `SECTION III - LIMITS OF INSURANCE
  = 10` both halves ARE printed, so `_verify_dec_entries` passes the entry and the
  index then offers a bare `10` to anything looking for a limit. A TOC is the one
  page shape whose label:value pairs are structurally real and semantically empty.
- **Rule 9 - the unlabeled carrier.** The measured-upside rule. `_carriers_by_line`
  pairs a carrier with its NAIC out of ONE entry (FIX_TRACKING_2026-08-15 RC1) and
  starves when the carrier name was never recorded at all - the normal case, since a
  dec page prints the company name as a captionless header. The label fallback chain
  only ever names text the page prints, because `_verify_dec_entries` requires the
  LABEL to be literally present: an invented `Carrier` caption would be dropped and
  would take the carrier name with it.
- **Rules 10 and 11** - an address is ONE value (never one line labelling the next),
  and a forms-and-endorsements list gets the caption printed above it instead of each
  form number labelling itself (rule 7's identical-text case, which records nothing
  and spends `DEC_ENTRY_MAX` budget).
- **Rule 6a** states the endorsement case: a schedule block filled in with this
  insured's own values is declarations content wherever it is printed.
- A closing four-question checklist, and one header line on the cost of a wrong key.

**NOT ADDED - all three were measured or verified first, and all three were in the
draft that prompted this work**

- **A `page` key.** `_verify_dec_entries` rebuilds every kept entry from a fixed
  six-key whitelist, so it would never reach a consumer. Output tokens for nobody.
- **Page-scoped `policy_number`** ("only from the page it is printed on").
  `[Document page N]` markers exist only when the document has >1 page AND the page
  has content (`ocr_service._PAGE_MARKERS_ON`), and chunking cuts mid-page - so the
  entries at the top of every chunk would be forced to null, starving
  `_policy_numbers_by_line`, which is the evidence the 2026-08-15 section-identity
  fix runs on. The borrowed-number defect it targets is already handled AFTER
  verification by `_entry_self_attributes_its_own_identifier`, the ISO form-number
  clear and the printed-as-a-policy-number invariant.
- **A fixed `line_of_business` vocabulary.** That is deleted rule 9 (see the comment
  above rule 8): measured taking off-vocabulary line values 2 -> 7. The code already
  canonicalises after verification (`_canon_line` + `_DEC_LINE_DISPLAY`) and leaves
  unknown wording as printed, so the ask buys nothing and costs every line outside
  the list its attribution.
- **"Split any value holding more than one number."** That is C60 - measured
  byte-identical on run c655a44b, removed with an explicit do-not-retry note.

**Numbering is load-bearing.** Rules 1-5, 7 and 8 are byte-identical and nothing was
renumbered: rule 7 cites "rule 5 wins" by number and
`tests/test_dec_entry_key_canonicalisation.py` pins that phrase. New rules are 9-11;
the empty-list terminator moved 9 -> 12.

Suite: **3698 passed / 2 failed** - the same two pre-existing unrelated failures
(`test_arq_acord125_missing_only`, `test_normalization`), zero regressions. The three
pinned files (`test_dec_index_dedicated_pass.py`,
`test_dec_entry_key_canonicalisation.py`, `test_run_20260814b_form_fixes.py`) pass
79/79.

**Not yet measured live.** Prompt bytes cannot measure recall. The real verdict is one
run on the client's package, before and after, comparing entry count, entries carrying
`owner=carrier`, and whether any bare integer from an index page appears
(`py scripts/dump_dec_index.py <session_id>`).

---

## C77 - 2026-08-22 dec-index prompt: OWNER EXPERIMENT, 19-rule structured schema

**One prompt changed: `_DEC_INDEX_SYSTEM_PROMPT`, replaced wholesale with the owner's
version (19 rules, `kind` / `row` / `page` keys, four worked examples, a block-by-block
procedure and a line-by-line self-check). No other byte changed - not the verifier, not
the canonicaliser, not the render, not the facts/flags prompt.** 7,806 -> 19,688 chars of
constant system prompt per indexed chunk (~+3,000 tokens, cached).

**Purpose: measurement.** Upload `test_data_v1_c1` (now five files -
`5_complex_tables.pdf` carries a premium summary with NO COVERAGE rows, a table of
contents, a 4-row schedule of hazards, a 3-vehicle schedule, a driver schedule and an
umbrella schedule of underlying) and diff against session 555b8079 (79 verified entries,
old prompt, old OCR shape).

**What the unchanged code does to this prompt's output - read before judging:**
- `_verify_dec_entries` rebuilds every kept entry from the ORIGINAL six-key whitelist, so
  `kind`, `row` and `page` never reach the merged index or call 2.
- It drops any entry with an empty label as malformed, so every `standalone`, `heading`,
  `statement` and `footer` entry (label null by the prompt's own definition) is discarded
  before the index. Expect `dropped_malformed` to jump in the `dec_entries VERIFIED` log.
- The raw model output is intact in the per-document copies
  (`documents[].facts.dec_page_entries`) - judge the PROMPT there, judge what call 2
  SAW in the merged index.
- Rule 10's fixed line_of_business list is the deleted rule 9 of 2026-08-16 (measured 2 -> 7
  off-vocabulary). The code canonicaliser still runs after verification, so the merged
  index will look canonical either way; compare the RAW per-doc values to measure it.

**Tests: 1 failed / 3698 passed** - `test_rule_7_states_its_one_case_and_yields_to_rule_5`
pins the literal `"rule 5 wins"`; the owner's text renumbers tables to rule 14 and reads
`"rule 14 wins"`. Semantically identical; the pin is stale against this numbering. Left
failing deliberately - the owner asked for no other change. The two pre-existing failures
(`test_arq_acord125_missing_only`, `test_normalization`) are unchanged.

History notes that used to sit inline in the constant (the C60 revert, the rule 7/8
measurements, the deleted rules 8/9) are relocated verbatim to the comment block above it.

---

## C78 - 2026-08-22 dec-index prompt: OWNER EXPERIMENT v3, 21-rule atomic schema

**Supersedes C77 in the code (same constant, replaced again). Nothing else changed.**
19,688 -> 30,418 chars of constant system prompt per indexed chunk (~7.6k tokens,
cached). Adds `id`, `path`, `col`, `value_type`, `qualifiers`; keeps `kind`, `row`,
`page`; **drops `section`**.

**Consequences of the unchanged code, in order of how much they distort a reading:**
1. **Every merged entry now has `section = null`** - the verifier reads a key this prompt
   never emits. `_render_dec_index` groups by section, so call 2 sees ONE flat group per
   policy/line instead of per-page groups, and the verifier's dedup key
   `(label, value, section)` loses its third term - the same label:value printed under two
   headings collapses to one. `path` carries that information now but nothing reads it.
2. Label-null kinds (`standalone`, `heading`, `statement`, `footer`, `index`) are dropped
   as malformed before the index. Rule 16's captionless carrier entries are in this set.
3. `id`/`page`/`kind`/`path`/`row`/`col`/`value_type`/`qualifiers` never reach the index.
4. Output volume: fourteen keys per entry plus a `path` array roughly triples reply size
   against v1. `DEC_INDEX_MAX_TOKENS` is still 16,000 - a dense chunk may truncate, which
   `_safe_json_parse` reports as a parse failure for that chunk, not a partial result.
5. In the owner's text, rule 2 and rule 8 cite "rule 15" for the postal-address rule; the
   address rule is 17 in this numbering (15 is the resolution block). Left verbatim.

**Tests: 9 failed / 3691 passed.** Two pre-existing. Seven are string pins on the old
wording - every guarded behaviour is still stated, in different words:
`'No Coverage', 'Included', 'Waived'` (now lists NOT COVERED/COVERED between them);
`one entry PER printed cell` / `NEVER concatenate` (now upper-case / "NEVER weld");
`SAME TEXT as its value` (now "label == value"); `the amount's LABEL` (now "that
amount's LABEL"); `labels must differ exactly as the printed captions differ` (rule 5
now says "NEVER label several different cells with only the shared row identifier");
`never shorten, reorder or reword` (now capitalised). Left failing - owner asked for no
other change. Re-pin to the new wording if v3 is kept.

Judge the prompt from `documents[].facts.dec_page_entries`; judge call 2 from the merged
index. Baseline: session 555b8079 (79 verified, old prompt).

---

## C79 - 2026-08-23 THE NET RESULT of C76-C78. Read this before believing them.

**C76, C77 and C78 describe prompt changes that were REVERTED the same day.** They
are kept because their measurements are real and worth not repeating, but the
prompt they describe is not what runs. This entry is the state of the code.

### What runs now

| | state |
|---|---|
| facts/flags prompt (`_EXTRACT_PROMPT_PREFIX` + `_EXTRACT_SCHEMA`) | **byte-identical to pre-2026-08-23**, verified against git |
| `dec_page_entries` in the facts schema | **restored** - ~250 entries, no extra call |
| dedicated index pass (`_harvest_dec_index`) | **OFF** (`DEC_INDEX_DEDICATED_PASS` defaults to 0) |
| `_DEC_INDEX_SYSTEM_PROMPT` | still in the file (30,418 chars, the owner's v3) but nothing calls it |
| `_verify_dec_entries` | **reverted to the original**, verified against git |
| `PROMPT_VERSION` / `SCHEMA_VERSION` | **v14** (v12 schema, forward-moving version - v13 replies are in the cache) |

**Net LLM-call change for a run: ZERO.** Extraction is 14 calls producing facts,
flags and the dec index together, exactly as before this work started.

### Why the dedicated pass was switched off - the A/B

It ran end to end for the first time on 2026-08-22 (a key-path bug had been
discarding 100% of its output since the day it shipped - see below). Measured on
the client's 271-page package:

```
facts + flags (whole extraction) : 14 calls, ~30,000 output tokens
the dedicated index pass         : 39 calls, ~593,000 output tokens
```

~20x the cost of the rest of extraction, +18-20 minutes per cold upload. The
owner regenerated the ACORD forms and reported them **"almost the same"**. It
does not earn its cost.

The reason it could not help is measurable: the index rendered to **619,451
chars against a 699,844-char document - 89%**, and split across **8** Stage A
calls. `_render_dec_index`'s design target is ~3% in ONE call. At 89% it is the
policy rewritten as JSON, so LLM call 2 gained nothing over walking the raw
document, and co-visibility - the entire point - was spread over eight calls.

### THE BUG THAT WAS WORTH THE WHOLE EXERCISE

`_run_extraction` merged the dedicated pass's output into
`result["dec_page_entries"]`. `_merge_list_fields` returns
`{"facts": {...}, "flags": {...}}` - the entries belong at
`result["facts"]["dec_page_entries"]`. The key was one level too high, so
`_validate_extraction_output` forwarded it as an unrecognised extra and
`extraction_pipeline` (which stores only `extracted["facts"]`) dropped it.

**Every entry the dedicated pass ever produced was discarded at that line.** It
was invisible while the main extraction also recorded entries - the index looked
populated and the pass's contribution silently evaporated beside it. Fixed; the
fix is KEPT even though the pass is off, because a future experiment needs it.

### Also KEPT (independent of the pass)

- **`_retry_wait_seconds` in `config/settings.py`.** The backoff was
  `2 ** attempt` for every retryable status - 1/2/4/8s, ~15 seconds total - against
  a tokens-per-minute limit that clears on a **60-second** window. Now `Retry-After`
  is read and obeyed (capped at `LLM_RETRY_AFTER_MAX`, 90s), and a 429 backs off
  5/15/30/60. Every other status keeps 1/2/4/8 exactly. **This helps every caller
  in the codebase, not just the index pass.**
- **Label-aware Stage A splitting** in `_dec_index_chunks`. The old path cut the
  rendered index by CHARACTER COUNT, which could separate the umbrella's
  $3,000,000 from the GL's $1,000,000 - C23 by accident of position. It now packs
  whole label groups, so a caption can never straddle two calls. Dormant at ~250
  entries; strictly safer if an index ever grows.
- `DEC_ENTRY_MAX` 1,200 -> 50,000 (runaway guard only; the prompt's own
  "at most 150 entries" per chunk is what binds).

### Measurements worth not repeating

- One index call, timed: **7,907 chars in -> 21,672 output tokens in 89.2s**
  (~243 tok/s, ~2.05 output tokens per input char).
- `declarations_authority` **does not discriminate** on a real package: 39 of 39
  pieces cleared the 0.25 bar, 33 of them at ~0.5. Its `brevity` half measures
  mean LINE LENGTH, and a column-laid-out policy PDF has short lines on every
  page, handing every piece a free 0.5. Raising the bar to 0.60 would cut 39
  calls to 5 - **not done**, on the owner's instruction that the whole uploaded
  document matters.
- By character count, **93% of a v3 index is `value_type: "text"`** - definitions,
  exclusions, WHO IS AN INSURED. Rule 9a of that prompt forbids recording it and
  the model does it anyway.

### If anyone re-opens this

The one configuration never tried on a real form is the **filtered** index: keep
fillable `value_type`s plus anything on a declarations/schedule page ->
**1,341 entries, 17% of the document, ONE Stage A call**, with every key value
surviving (class codes and their classification wording, both occurrence limits,
all four policy numbers, both carriers, the applicant, the package premium). That
filter was built, measured and then removed with the revert. Rebuild it from
LLMcall1-promptChange.md §40 rather than from scratch.

---

## C51 - Extraction writes facts WITHOUT answer interpretation (open, 2026-08-24)

Not a cost item - a correctness boundary that touches this file because closing
it the thorough way means a PROMPT change.

`services/answer_semantics.py` (shipped 2026-08-24) interprets everything a
HUMAN types - producer recommendation cards, inline hard-stop / warning
resolution, the client questionnaire - so that "None" reads as an answered
absence and "TBD" is refused rather than stored as data. Measured defect it
closed: typing "N/A" into every Tier-2 field scored **100**, identical to a
fully answered submission.

**The extraction path is NOT covered.** `merge_facts` writes `facts[key]`
directly from the model's output, so an LLM that extracts the literal string
`"N/A"`, `"unknown"`, `"TBD"` or `"not provided"` out of a document has that
stored as a VALUE, and every completeness read counts it as real data.

**Two ways to close it, and the cheap one does NOT touch a prompt:**
1. **Deterministic post-merge pass (preferred).** Run `interpret_answer` over
   the merged facts at the end of `merge_facts`; where the intent is UNKNOWN,
   set `value_state: not_stated` and leave the stored value alone. No prompt
   change, no extra call, no cache invalidation, no token cost. The only risk
   is a false demotion, which fails toward "ask the client", the safe direction.
2. **Prompt change** telling the extractor to emit null rather than a
   placeholder string. Cleaner at source, but it invalidates the extraction
   cache and moves `PROMPT_VERSION` / `SCHEMA_VERSION` - i.e. a full re-extract
   for every cached session. Do not do this casually; see the v14 note above for
   what a version bump costs.

**Related, and also open:** the owner declined an LLM layer for interpreting
free-text ANSWERS (latency and determinism, not tokens - a classification call
is ~0.03% of a submission's spend). `answer_semantics.unresolved_answers()`
logs every answer the deterministic rules could not read, which is the evidence
base for revisiting that decision. **Nobody is watching that log.** Grep for
`answer_semantics: could not read` before concluding the deterministic approach
is sufficient.
