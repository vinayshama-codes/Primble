# Fix Tracking - 2026-08-15 - Relationship Preservation (client Tuesday deliverable)

Client direction: "Optimize for preserving what each value means and where it belongs."
Root causes: RC1 flat global facts erase policy/line identity; RC2 no meaning guard on
numeric gap fill; RC3 conflict detection does not gate stamping. Plus one rule bug
(expired-term hard stop ignores is_renewal).

## Fix 1 - Renewal-aware expired-term stop  [DONE]
- `sqs_service.validate_policy_term_not_expired` + new `_is_renewal_submission`:
  when `is_renewal` is affirmative, the >30-days-expired HARD stop becomes a SOFT
  "confirm the proposed renewal term" warning (message still matches the
  `_LEGACY_MESSAGE_RULES` "Policy term already expired" row, so cluster/resolution
  carry over). Non-renewal behavior unchanged.

## Fix 2 - Renewal date routing  [DONE]
- `extraction_service._route_renewal_dates`, called at the very END of `merge_facts`
  (after dec-entry backfill so nothing resurrects the routed dates): on a renewal
  whose extracted term has already ENDED, effective/expiration move to
  prior_effective_date/prior_expiration_date (never overwriting an extracted prior
  term), current keys cleared, `renewal_dates_routed: true` set. Future-dated terms
  untouched; non-renewals untouched.
- `pdf_service._resolve_renewal_proposed_period`: owns `Policy_EffectiveDate_[A-N]` /
  `Policy_ExpirationDate_[A-N]` when routing ran - stamps a producer/client-supplied
  proposed date, else authoritative blank (gap fill excluded, because the raw text
  prints the expiring term and the LLM would copy it back). ACORD 25/28 exempt
  (certificates document the EXISTING policy). Tier-1 lists the missing proposed
  effective date, so the questionnaire asks for the real term.

## Fix 3 - Line-scoped policy identity  [DONE]
- `pdf_service._resolve_section_policy_identity` + `_SECTION_FORM_LINE_PHRASES` +
  `_section_carrier_pair`: `Policy_PolicyNumberIdentifier_A`,
  `Policy_EffectiveDate/ExpirationDate_A`, `Insurer_FullName/NAICCode_A` on section
  forms (126/127/130/131/133/137x/138x/140/141/160/186/28) resolve from the
  `coverage_lines` entry matching THAT form's line (token matching via the proven
  `_lob_tokens`/`_tokens_describe_same_line` machinery). Carrier+NAIC only ever as a
  pair from ONE entry - a recombined pair is structurally impossible. Untrustworthy
  line list (`_line_list_is_trustworthy`) -> blank. No `coverage_lines` -> legacy
  scalar path byte-identical. 125/101 keep package-level scalars (correct there);
  ACORD 25 per-line rows remain owned by `_resolve_current_policy_line_cell`.
- `_form_id` context injected as a shallow facts copy in `map_facts_to_form` and
  `compute_form_gaps`; resolvers registered in `_AUTHORITATIVE_BLANK_RESOLVERS`
  and wired into `_deterministic_map` ahead of the rules loop, so both the Pass-1
  door and the alias door are closed and gap fill never sees an owned blank.

## Fix 4 - Numeric meaning gate  [DONE]
- `pdf_service._enforce_numeric_meaning_gate` (+ `_amount_category`,
  `_build_amount_witnesses`, `_document_states_a_zero`), called beside
  `_enforce_post_fill_guards` in map_facts_to_form. Gap-fill amounts only:
  (1) an amount whose verified witnesses (dec_page_entries labels +
  gl_class_code_schedule premium_basis/exposure pairs) ALL belong to a different
  category (sales/payroll/premium/limit/deductible) than the field is blanked -
  $39,300 witnessed only as payroll can never stamp into Annual Gross Sales;
  (2) a gap-filled $0 with no literal zero stated in the document is blanked.
  No witnesses / mixed witnesses = no opinion (value stands). No prompt change,
  no LLM call change (improving-ll.md untouched by design).

## Fix 5 - Unresolved conflicts stamp blank  [DONE]
- `underwriting_consistency`: `umbrella_limit` curated as a currency reconcilable
  field (ACORD_131); new `CONFLICT_WITHHOLD_KEYS = {umbrella_limit}` +
  `unresolved_withheld_keys()`.
- `extraction_pipeline`: after `assess_underwriting_consistency`, unresolved
  withheld keys are written to `merged_facts["_uw_conflicted_keys"]` (recomputed on
  every pipeline run; the confirm endpoint re-runs the pipeline, so confirming in
  the picker clears the withhold with no extra wiring).
- `pdf_service._resolve_conflicted_fact_blank`: first door in `_deterministic_map` -
  any field fed by a withheld fact (Pass-1 rules or alias canonical) is an owned
  blank; `alias_stamper.stamp_form_fields` also skips withheld extraction keys.
  The FACT stays in facts - SQS pillars/warnings/picker keep reading it.

## Tests  [DONE - 40/40]
- `backend/tests/test_relationship_preservation_20260815.py` (40 tests), all
  fixtures using the client's literal Orbin values: 6J7/6E7/BBC7263/6C7, EMC P&C
  25186 vs Employers Mutual 21415, $39,300 payroll-vs-sales, $0 foreign sales,
  $3M-vs-$1M umbrella withhold, 07/15/2025-07/15/2026 renewal term.
- `backend/tests/test_extraction_json_salvage.py` (15 tests, Fix 6).
- Full suite after ALL SIX fixes: **2742 passed / 2 failed / 2 skipped** - the same
  two pre-existing failures as the documented baseline
  (test_arq_acord125_missing_only, test_normalization). ZERO regressions.

## Fix 6 - Upload 500 on the fresh Orbin run (found in live testing, NOT caused by 1-5)  [DONE]
Live: `RuntimeError: _safe_json_parse: could not parse valid JSON after 3 attempts` ->
HTTP 500, whole 271-page upload lost. Verified NOT a regression from Fixes 1-5: the only
extraction_service change above is appended to the END of `merge_facts`, which runs long
after per-chunk parsing. Three defects in one path (full detail in improving-ll.md C51):
- `utils/json_salvage.py` (NEW): deterministic recovery of a reply truncated at the output
  cap. `pdf_service._salvage_truncated_json` now delegates to it - the gap-fill stage has
  had this since the C-series; extraction never got it and went straight to an LLM repair
  fed only the first 3,000 chars of a possibly 60,000-char reply (a fragment of a fragment,
  re-truncated on each of 3 attempts). Salvage drops the half-written element rather than
  closing it into a partial dec entry / vehicle row.
- `extraction_service._EXTRACT_MAX_OUTPUT_TOKENS` (env `EXTRACT_MAX_OUTPUT_TOKENS`,
  default 32,000, was a hardcoded 16,000): the cap the huge fact+schedule+dec_entries reply
  was hitting. Does not raise the bill - output is billed on what is actually written.
- `extraction_service._gather_chunks_async._one`: a JSON/schema failure no longer `raise`s
  past every degradation path (per-chunk retry, smaller-chunk document retry, PARTIAL
  coverage reporting). It retries, then degrades to `chunk_failed` - which is loud, not
  silent. An all-chunks-failed document still raises.
- Tests: `backend/tests/test_extraction_json_salvage.py` (15).

## ROUND 2 - the ROOT causes (round 1 fixed the last mile only)  [DONE]
Round 1 stopped wrong values reaching the paper but left the SOURCE corrupt, so
131/127 shipped blank identity boxes instead of correct ones. The live log:
`merge coverage_lines FINAL` showed ONE policy number (6C7, inland marine) on
all EIGHT lines. Everything downstream was reading a fact whose line->policy
relationship had already been destroyed.

- **7. `_repair_coverage_lines_from_entries`** (extraction_service, in merge_facts):
  when the line list is self-contradictory (one policy number on 2+ different
  canonical lines), each line's policy number AND carrier are rebuilt from the
  VERIFIED `dec_page_entries` - which carry `line_of_business` / `section` /
  `owner` and are checked verbatim against the document. A line the entries
  cannot settle is CLEARED, never guessed. A healthy list is never touched.
  Also `_canon_line`: specific coverage names beat the generic word "liability"
  (a first version ranked by phrase LENGTH and read "Commercial Liability
  Umbrella" as General Liability - caught by test, not by production).
- **8. `_resolve_section_prior_policy`** (pdf_service): ACORD 131's EXPIRING
  POL # is `PriorCoverage_PolicyNumberIdentifier_A` - SINGLE-segment, so the
  prior-coverage grid regex never matched it and it took the global scalar.
  Now resolved from this form's own line, and any value the package states as a
  CURRENT policy number is refused outright (BBC7263 is in force, so it cannot
  be the expiring policy whatever line it belongs to).
- **9. Carrier + NAIC as a matched pair, enforced.** Once a line's carrier is
  established from per-line evidence, its NAIC may come ONLY from that same
  evidence - never from the package-level `carrier_naic` scalar. That fallback
  is exactly how "Employers Mutual" acquired EMC Property & Casualty's 25186.
  Per `orbin_ground_truth.json`, NO NAIC is printed on any of the 271 pages, so
  blank is the only correct answer on this package.
- **10. Expired-term stop now turns on PROVENANCE, not on `is_renewal`.**
  THE ORBIN PACKAGE NEVER SAYS "RENEWAL" (verified against the ground truth:
  271 pages, zero renewal wording; the one hit is the form TITLE "Cancellation
  And Nonrenewal"). Gating on `is_renewal` would have fixed nothing. What
  decides it is who stated the term: a producer-typed dead period is still a
  hard stop; a term read off an uploaded carrier document is a confirm-the-dates
  WARNING. `_dates_are_producer_asserted` reads the `source`/`confidence` the
  fact envelope already carries. `_backfill_is_renewal` stays as a second,
  independent signal for packages that DO say it.
- **11. Repeating-row guard compares NORMALIZED values.** ACORD 25 shipped one
  carrier in five INSURER slots because row A held the merge winner in CAPS and
  gap fill wrote title case into C-F; the exact-string compare missed every one.
  Formatting-only key (`_same_value_key`). `normalize_carrier` was tried here
  and REVERTED - it collapsed "EMC Property & Casualty Company" into "Employers
  Mutual Casualty Company", two different real carriers on this very package.
- **12. Intra-document conflicts.** The $3M/$1M umbrella disagreement is inside
  ONE uploaded package, which the cross-DOCUMENT reconciler cannot see. The
  merge's own rejected-candidate list is now consulted: a limit chosen over a
  materially different rival is withheld from stamping pending confirmation.
  The pipeline's withhold list is a UNION, so a cross-doc conflict can never
  silently release an intra-doc one.

## Client-side acceptance audit (all 17 checks PASS)
Driven through the real resolvers with the LIVE run's own `coverage_lines`:
131 policy = 6J7 / 127 = 6E7 / 126 = BBC7263; EXPIRING POL # not BBC7263;
GL carrier = EMC Property & Casualty, Umbrella = Employers Mutual, NAIC blank on
both; $39,300 refused from Gross Sales and KEPT as Payroll; $0 Foreign Gross
Sales blanked; $3M/$1M withheld and stamping blank; no expired-term hard stop
(warning instead); renewal term routed to prior_*; ACORD 25 no longer repeats a
carrier across five slots.

## ROUND 3 - regressions and escapes found on the 2026-08-15 fresh run  [DONE]
Three defects, ALL introduced or missed by rounds 1-2. Owned, not explained away.

- **13. I blanked ACORD 125's PROPOSED EFF/EXP DATE (a regression).** `is_renewal`
  now detects correctly (RENEW ticks on 125 - new), so the routing fired and
  emptied both boxes. PROPOSED EFF DATE is a Tier-1 field, so it immediately
  came back as "ACORD 125 minimum field missing" and the producer had to type a
  date the document already answers. Wrong in both directions. `_route_renewal_
  dates` now DERIVES the proposed term - a renewal takes effect when the
  expiring policy ends, which is what renewing means - carrying
  `source="derived"` / `confidence="low_confidence"` so the E&O layer flags it
  for one-click confirmation. An odd-length expiring term derives the effective
  date only; the new expiry stays unset rather than extrapolated.
- **14. ANN GROSS SALES = $350,000 escaped the meaning gate.** That is GL class
  91585's "Prem Basis: Total Cost" - the subcontracted-work cost, and
  `orbin_ground_truth` names it the package's strongest revenue decoy. My
  category table had no row for cost/subcontract, so the figure registered NO
  witness and the gate stood aside. Added a `cost` category plus
  `_PREMIUM_BASIS_CATEGORY` for ACORD's printed one-letter basis codes
  (P/S/C/A/U/M/T).
- **15. $0 Employee Benefits Liability limits escaped the zero gate.** The check
  asked "does the document state ANY zero?" - and the umbrella's SIR really is
  $0, so one legitimate zero unlocked every fabricated one. `_zero_is_stated_
  for(facts, category)` now requires the zero to have been printed against the
  same KIND of figure.

## ROUND 4 - the dec-entry fallback, and the run that proved it  [DONE]
- **16. `_policy_number_from_dec_entries`** (pdf_service): the section-identity
  resolver now asks the VERIFIED dec entries directly, not only the
  `coverage_lines` summary. Two bugs made it unreachable at first and both are
  the interesting part: (a) the untrustworthy-list branch returned blank BEFORE
  consulting the entries, and (b) `coverage_lines` rows carrying no premium fail
  `_line_entry_grants_coverage`, so the resolver returned _SCHED_SKIP before the
  fallback. The evidence was in the package the whole time and was never asked
  for. Positive evidence only, so the legacy scalar path is untouched.

### Verified on the fresh run of 2026-08-15 (forms read field by field)
FIXED and confirmed on paper:
- **ACORD 131 POLICY NUMBER = 6J7-40-02---26** - the client's headline defect,
  correct for the first time (was the Auto number, then blank).
- ACORD 131 underlying GL row pairs **EMC Property & Casualty Company with
  BBC7263** - the two-carrier split now survives to the form.
- ACORD 25 lists BOTH real carriers (A = Employers Mutual, B = EMC P&C).
- ACORD 125 PROPOSED EFF/EXP = **07/15/2026 - 07/15/2027**: the derived renewal
  term, correct and no longer demanding manual entry.
- ANN GROSS SALES blank, FOREIGN GROSS SALES blank, EBL $3,000,000 gone,
  ACORD 127 deductible $1,000 (was $1,000,000), 127 Q9 policy-wording answer
  gone, 125 Q3 pollution-boilerplate "Y" gone, no expired-term hard stop.

STILL WRONG (all of one class - see below):
- ACORD 127 header POLICY NUMBER still blank (131 resolved, 127 did not).
- ACORD 131 header EFFECTIVE DATE still 07/15/2025 (the expiring date).
- ACORD 25 INSURER E duplicates INSURER B - Guard 2 compares each row to row A
  ONLY, so a duplicate between two non-A rows survives.
- Sections for coverage the policy does NOT carry are still being filled:
  Employers Liability rows and the ACORD 25 WC row (WC = "No Coverage"),
  watercraft (LENGTH 4800 - the street number), apartments, EBL retained $0,
  advertising "MEDIA USED: Print", 131 Care/Custody VALUE $39,300 (payroll).
- ACORD 25 CERTIFICATE NUMBER still holds a policy number.

**The remaining defects are one class, and it is NOT the relationship class the
client reported.** Every item above is gap fill answering a question about a
coverage part this policy does not have, using the nearest plausible token in
683k chars. The next fix is the same shape as C46's phantom vehicle rows:
suppress whole form SECTIONS when the document states the coverage is absent,
so the model is never asked. Deterministic, free, and it removes most of the
list above at once.

## Files touched
- backend/services/sqs_service.py            (Fix 1)
- backend/services/extraction_service.py     (Fix 2 routing)
- backend/services/pdf_service.py            (Fixes 2/3/4/5 stamping side)
- backend/services/underwriting_consistency.py (Fix 5 keys + helper)
- backend/services/extraction_pipeline.py    (Fix 5 injection)
- backend/services/alias_stamper.py          (Fix 5 alias door)
- backend/utils/json_salvage.py              (Fix 6, NEW - shared salvage parser)
- backend/tests/test_relationship_preservation_20260815.py (new)
- backend/tests/test_extraction_json_salvage.py (new)
- improving-ll.md                            (C51 - required for any LLM-call change)

## Verification on the fresh Orbin upload (client's dec page)
ACORD 131: policy number = 6J7-40-02---26 or blank (never 6E7/BBC7263); expiring
policy number never BBC7263; carrier+NAIC a matched pair; Annual Gross Sales blank;
Foreign Gross Sales blank; umbrella limit blank + Data Consistency card until
confirmed; effective date not 07/15/2025 (asked in questionnaire instead).
ACORD 127: policy number still 6E7-40-02---26 (now by construction, not by luck).
ACORD 125: header stays package-level; Q4 grid pairs line+number per row.
Review screen: no "Policy term already expired" hard stop (soft confirm-renewal
warning instead); score ceiling 85 not 60; resolving/confirming visibly moves score.

## ROUND 5 - independent audit of rounds 1-4, then the remaining fixes  [DONE]
An adversarial re-verification (code + the attached run's forms + a full-suite
run), then five fixes. Two audit findings correct the record of rounds 1-4:

- **The round-2 "17-check acceptance audit" repeated the documented resolver
  trap.** It drove `_deterministic_map` directly; the 131 header date was
  CORRECT there and WRONG on paper, because `map_facts_to_form`'s
  umbrella-period override (the Policy_EffectiveDate_A override near the
  per-form overrides, added for the C14-era umbrella-period feature) re-stamped
  the probed EXPIRING date over the derived term. That is the root cause of
  "131 header EFFECTIVE DATE still 07/15/2025", which round 4 logged as
  unexplained. Every end-to-end claim must be verified through
  `map_facts_to_form`, never the resolver alone - the codebase already says so
  in the _AUTHORITATIVE_BLANK_RESOLVERS block comment.
- **Fix 5/12 (the $3M/$1M umbrella withhold) has never been exercised live.**
  The attached forms stamp $3,000,000 in five places. The withhold chain is
  code-complete and unit-tested end to end, but the 271-page package alone
  contains no $1M umbrella evidence (ground truth: the umbrella's own limits
  ARE $3M) - the client's $1M is in a separate COI document. **The Tuesday
  regression upload MUST include the COI, or requirement #5 ships on unit
  tests alone.** Also note the deliberate scope: CONFLICT_WITHHOLD_KEYS and
  _CONFLICT_SENSITIVE_LIMITS each hold exactly one key (umbrella_limit).

The five fixes (tests: `backend/tests/test_remaining_relationship_fixes_20260815.py`,
27, all end-to-end through the real map_facts_to_form/compute_form_gaps with the
real schemas; suite after: 2818 passed / 2 failed - the same two pre-existing):

- **17. Umbrella-period override yields to a routed renewal** (pdf_service, the
  ACORD_131 Policy_EffectiveDate_A/ExpirationDate_A override): skipped when
  `renewal_dates_routed` unless `_umbrella_period_is_current` (the umbrella's
  own expiration parses to a future date - a real renewal umbrella dec still
  wins). ACORD 25's twin override is deliberately NOT gated (a certificate
  documents the EXISTING policy). The probe itself is untouched.
- **18. Guard 2 pairwise for NAME-family fields only** (`_NAME_VALUE_FIELD_RE`):
  the live certificate duplicated INSURER B into INSURER E - two non-A rows,
  invisible to the row-A-only compare. Name rosters never legitimately repeat
  an entity, so those compare against every earlier row. Everything else keeps
  the row-A-only compare BYTE-COMPATIBLE, deliberately: pairwise on repeat-prone
  data columns (garaging city on a fleet) would create a brand-new deletion
  surface, and C18's asymmetry (wrongly DELETED is invisible; wrongly repeated
  gets fixed by the broker) decides that trade.
- **19. ACORD 131 UnderlyingPolicy_* grid owned** (`_resolve_underlying_policy_row`):
  Automobile/GeneralLiability/EmployersLiability rows resolve identity attrs
  (insurer, policy number, the policy's OWN eff/exp - never the derived
  proposed term) from `coverage_lines` via the same line-matching machinery as
  the header resolver, with the dec-entries fallback shared through the new
  `_policy_number_for_line_phrases` (refactored out of
  `_policy_number_from_dec_entries` - one implementation, two callers).
  OtherPolicy rows are owned blanks whenever per-line evidence exists: no fact
  can name a fourth underlying policy, so anything there is a fabrication (the
  live run: the AUTO number + the DERIVED 07/15/2026-07/15/2027 dates, via
  Pass-1 scalar rules - the flat-fact funnel, not gap fill). No coverage_lines
  -> _SCHED_SKIP, legacy path byte-identical.
- **20. Declared-absent coverage suppression** (`_resolve_declared_absent_line_row`
  + `_line_declared_absent`): positive evidence only - a coverage_lines entry
  for the line whose own detail matches extraction's `_COVERAGE_DENIAL_RE`
  ("No Coverage"), with NO granted entry for the same line (an uploaded new WC
  quote defeats the package's denial). Suppresses the WC/EL family
  (`WorkersCompensationEmployersLiability_*`, `Policy_WorkersCompensation*`,
  `UnderlyingPolicy_EmployersLiability_*`) on 131/25/etc; ACORD 130 exempt -
  it is an application FOR workers comp. Kills the live 25's phantom WC row
  (dates + three EL limits) and 131's phantom EL underlying row at the
  question, not the answer.
- **21. Producer-assigned certificate IDs + name fragments.** The Pass-1 rule
  mapping CertificateOfInsurance_CertificateNumberIdentifier -> policy_number
  (the ACTUAL source of the policy number in the CERTIFICATE NUMBER box - an
  explicit rule, not gap-fill drift) is deleted; the field family is owned by
  `_resolve_certificate_producer_ids` (blank unless a certificate_number /
  certificate_revision_number fact exists, so a producer-supplied value still
  stamps). Guard 3 additionally rejects a single-letter value in a
  name-family field ("a driver named E"), with Initial-suffixed fields exempt
  (one letter is legitimate there).

Audit facts worth keeping (verified, not assumed):
- Driver identity columns are ALREADY authoritative blanks when no
  auto_driver_schedule fact exists (pinned by test) - the phantom "E" driver
  came through a path that no longer exists at HEAD; the fragment guard covers
  the name fields that remain gap-fillable (insurer roster, contacts).
- "6E74002" on 131's underlying auto row is CORRECT - page 148 prints the auto
  policy number exactly that way (ground truth `schedule_of_underlying_
  insurance_page_148`). Do not "fix" it into 6E7-40-02---26; both printings
  are the same policy and either is right.
- The attached round-4 forms are STALE relative to HEAD for: retroactive-date
  boxes, watercraft/apartments/media/EBL, Care/Custody $39,300, UM/UIM $1M,
  tail date (all verified blanked or never-asked in the end-to-end harness).
  Still expected on a fresh run and OUT OF SCOPE here: ModificationFactor
  ("SEE ITEM FOU" / "4.00") and other rating-mod junk on 131's underlying
  grid (left gap-fillable - a real mod is only ever in raw text), 127's
  TERR/SIC/NET VEH DR/CR token borrows, and 127 Q12's false "N" (the accepted
  ~2-3 borrowed-negation residual, an LLM limitation).

Fresh-run checklist ADDITIONS for the re-test (on top of the list above):
131 header EFFECTIVE DATE = 07/15/2026 (the derived term); 131 UNDERLYING
INSURANCE shows ONLY the GL row (EMC P&C + BBC7263) and the Auto row (their
own 07/15/25-07/15/26 term), EL and both Other rows EMPTY; ACORD 25 has NO WC
row content, CERTIFICATE NUMBER empty, and INSURER E is not a duplicate of any
other insurer row; upload set INCLUDES the $1M COI and the umbrella limit
boxes then stay blank with the Data Consistency card open.

## ROUND 6 - the fresh run of 2026-08-15 (round-5 build), verdict + fixes  [DONE]
The fresh forms PROVE fixes 17/19-partial/21 live: 131 header EFFECTIVE DATE =
07/15/2026 (the client's #6, finally on paper), CERTIFICATE NUMBER empty, the
OtherPolicy fabricated identity rows gone from 131, ACORD 125 fully clean
(single premises, full operations text, correct premiums/total/renewal term,
every trap field blank). Two round-5 mechanisms did NOT engage live, both
root-caused by replaying the run's own line-name shapes, both fixed:

- **22. A bare generic "Liability" line was stealing rows.** The live package
  premium table names GL as the word "Liability"; subset token matching let
  that entry satisfy ("workers compensation", "employers liability"), so
  `_resolve_underlying_policy_row` DETERMINISTICALLY paired the Liability
  row's carrier + dates onto the 131 EL underlying row (the printed defect,
  reproduced cell-for-cell in the harness, including the GL row's blank
  carrier - two liability-classed entries with two carriers = ambiguity).
  FIX: `_entry_matches_line_strict` - both sides classified by extraction's
  own `_canon_line` ("Liability" -> general_liab, "Employers Liability" ->
  workers_comp); canons must agree when both classify; token matching survives
  only for names the canonicalizer cannot place. Wired into the underlying
  grid AND `_line_declared_absent`. Section-header matching deliberately
  untouched - a bare "Liability" SHOULD satisfy ACORD 126's header.
- **23. The WC denial never reaches `coverage_lines`.** RULE 16 tells
  extraction to leave denied lines OUT, so "Workers' Compensation ... No
  Coverage" survives only as a verified dec-page ENTRY - and round 5's
  declared-absent check read `coverage_lines` alone, so it never fired and
  the 25's WC row + 131's EL limits still filled. FIX: `_line_declared_absent`
  now also reads `dec_page_entries` (label/line_of_business matched strictly,
  value matched by extraction's `_COVERAGE_DENIAL_RE`); a granted WC line
  still defeats any denial.
- **24. The meaning gate waved every sub-$100 figure past.** Fresh run:
  FOREIGN GROSS SALES = "$34" - the umbrella's TRIA terrorism premium. The
  `amt < 100` skip (built for counts/percents) now applies only to values
  with no dollar marker; "$34" witnessed as premium is gated out of a sales
  box like any other cross-category borrow.
- **25. ACORD 25's OTHER row owned** (`_resolve_certificate_other_row`): the
  fresh run paired the IM number 6C7-40-02---26 with the DERIVED
  07/15/2026-07/15/2027 dates plus a fabricated SUBR WVD "Y" and borrowed
  limit strings. The row now resolves from the ONE granted line whose canon
  class is outside the certificate's four printed sections (Orbin: Inland
  Marine - number 6C7, its OWN 07/15/25-26 term, name in the description);
  zero/several leftovers or any unclassifiable granted line = every cell
  blank; waiver/letter/limit cells never fabricate. Legacy (no
  coverage_lines) untouched.

Tests: +10 in `test_remaining_relationship_fixes_20260815.py` (37 total, all
end-to-end with the live run's own line-name shapes). Suite after round 6:
**2828 passed / 2 failed** - the same two pre-existing failures, zero
regressions. One regression was caught BY the suite mid-round and fixed
before landing: the OtherPolicy_* family is FORM-OVERLOADED (ACORD 125's Q4
grid vs ACORD 25's OTHER row share the field names), and the new certificate
resolver hijacked the 125 grid until form-gated to ACORD_25
(test_paired_rows_and_reformatted_dupes caught it - 3 failures, now green).

STILL OPEN after round 6, honestly - the gap-fill/extraction classes, none of
them the deterministic-relationship class (report to owner before Tuesday):
- **INSURER E = "Emcasco Insurance Company"** - a carrier NOT on this package,
  from page 124's CA8214.1 notice (the ground truth's "single worst adjacency").
  The dedup can only kill duplicates; a fabricated DIFFERENT insurer needs the
  roster restricted to carriers attributed in coverage_lines/dec entries -
  recommend next.
- **The EBL block on 131** filled with the GL limits ($1M/$2M), retained $0,
  retro date, and the ops description as "benefit program name" - phantom
  coverage (EBL is never granted OR denied in print, so positive-evidence
  suppression cannot fire). The planned phantom-SECTION suppression is the fix.
- **Retroactive-date boxes** (PROPOSED 07/15/2026 / CURRENT 07/15/2025) on an
  occurrence-basis policy, and the TAIL EFF DATE - dates have no meaning gate.
- **127 vehicle rating boxes reshuffled** (CLASS 111 / SIC 91580 / FACTOR 7383
  / FARTHEST TERMINAL 111), watercraft LENGTH/HP = 2012, apartments 1/0/0,
  vehicles-grid zeros and the "0 - 25" band in an integer box, MEDIA Print,
  ISO edition 09-97 (the IM form's), Q9 "Y" grounded in CA9910 endorsement
  WORDING (mention-vs-grant), Q7 fabricated "Y", telematics describe
  boilerplate - all retrieval/evidence-gate residuals.
- **Driver row prints a single letter again ("R") with the garaging city** -
  the letter sits in a field the fragment guard covers only if it is a
  name-family field; live session facts needed to see which field carried it
  (extraction may now be building a 1-entry driver schedule from the CA9910
  Drive-Other-Car individual, which ground truth explicitly forbids).
- **Auto/GL policy-number attribution still fails extraction-side** (127
  header and the 131 auto-row number ship blank; right-or-blank holding). The
  numbers are printed on pages 85/148/205 - check the live `dec_entries
  VERIFIED` log for why the auto and GL sections' numbers are not being
  captured or attributed.

## ROUND 7 - third fresh run (2026-08-15): the remaining root causes closed  [DONE]
The third set of forms proved round 6's canon-strict matching and dec-entry
denial worked as far as they could see - and exposed the four mechanisms
underneath everything still printing. All four closed deterministically; suite
2840 passed / 2 failed (same two pre-existing), 49 tests in
`test_remaining_relationship_fixes_20260815.py`.

- **26. Requirement-shaped line entries are not policies**
  (`_line_entry_evidences_policy`). The EL row kept printing its carrier +
  $1M/$1M/$1M because extraction emits the umbrella's underlying-REQUIREMENT
  wording as an "Employers Liability" line - carrier beside required limits,
  no premium, no policy number - and a bare `limit` satisfies
  `_line_entry_grants_coverage`. Grant-grade now requires a premium or a
  policy number everywhere stamping decides line presence: the underlying
  grid, the declared-absent check, and the new census below. A real WC quote
  (premium) still defeats suppression.
- **27. The line-inventory CENSUS** (`_line_absent_from_package`): a package
  whose verified line map grants two or more policies and never WC is
  positive evidence WC is not carried - the denial text does not need to
  survive extraction (RULE 16 drops denied lines; the third run had no WC
  denial dec entry either). Kills the 25 WC row and the 131 EL limits on the
  live shape. Thin inventories (<2 evidenced lines) suppress nothing. EBL
  joined the family table (`ExcessUmbrella_EmployeeBenefits_*` - the block
  had been filled with GL limits, then "Business Auto Coverage Form" as the
  benefit program name). ACORD 130 stays exempt.
- **28. Dependent rows without their trigger** (Guard 6 registry): watercraft
  rows are dependents of Q27 (three runs of junk: 4800/07, 2012/26680),
  the tail EFF DATE of Q6, and the PROPOSED/CURRENT RETROACTIVE dates of the
  CLAIMS MADE election - an occurrence policy structurally has none. An
  affirmative election keeps them (guard-level test); an ungrounded "Yes"
  dies at the evidence gate and its dependents rightly follow.
- **29. Facts are meaning-gate witnesses; "value" is a category.** ANN GROSS
  SALES = $10,663 was the package total premium THIS PIPELINE reconciled, and
  CCC VALUE = $300 the IM line premium - no dec entry happened to witness
  either, so the gate stood aside. `coverage_lines` premiums,
  `total_policy_premium` and `umbrella_limit` now witness by construction,
  and property-VALUE boxes have their own category.
- **30. Two guards:** a driver row with no name carries nothing (Guard 2b -
  the third run printed "R" + the garaging city as driver 1; name columns
  are already owned blanks without a schedule, the rest of the row now
  anchors to them), and the insurer roster seats only ATTESTED carriers
  (Guard 2c - "Emcasco Insurance Company" from the page-124 notice, then the
  mutant "Employers Property & Casualty Company"; a slot may hold only a
  carrier the package's own per-line evidence names; inert for legacy
  sessions with no per-line data). `UnderlyingPolicy_*_ModificationFactor`
  is an owned blank - a rating mod is never an extractable fact and drew
  junk on all three runs.

### FOURTH fresh run (2026-08-15): round 7 verified on paper, one addition
Every round-7 target confirmed dead: EL underlying row empty, EBL block empty,
retro dates empty, watercraft AND apartments rows empty, ANN GROSS SALES empty,
CCC VALUE empty, rating mods empty, 25 WC limits gone, 127 driver table fully
empty, insurer roster = exactly the two real carriers (A Employers Mutual, B
EMC P&C), ISO edition finally correct (04/13), MEDIA USED empty, vehicles-grid
fabricated counts and the "0 - 25" band gone. BONUS: the 125 PRIOR CARRIER
grid now documents the expiring GL (EMC P&C + BBC7263) and Auto (Employers
Mutual + 6E74002) with correct line-scoped pairing.
- **31. Q17 telematics sub-fields registered as Guard-6 dependents**
  (`CommercialVehicleLineOfBusiness_KAHCode_A` -> percentage, utilization
  indicators, both describe cells): the run filled "100%", "Virus and
  Hacking" (cyber wording) and "NAMES OF INDIVIDUALS ERIN ROYAL" (CA9910)
  with Q17 itself blank. Suite after: 2842 passed / 2 failed (same two),
  51 tests in the regression file.
- **NAIC 21415 appeared for Employers Mutual on the 25/125 headers.** The
  pairing is correct (21415 IS Employers Mutual's NAIC, per the client's own
  letter) but the 271-page ground truth prints NO NAIC anywhere. Either this
  run's upload included a document that prints it (a COI - then also expect
  the $1M umbrella conflict, which did NOT surface; $3M stamped uncontested)
  or it was fabricated from model knowledge. NEEDS the upload manifest +
  session log before Tuesday.
Residual junk on this run, all small, all retrieval-class: 131 PROPERTY
HAULED "PRIV PASSENGER" x4 (no anchor question exists), 25 GL sub-row
endorsement names ($33/$500), "Commercia" truncation fragments, 131 page-6
UM/UIM/MedPay carrying the underlying auto's figures, 131 location NAME cell
holding the address, 127 SIC/FACTOR/FARTHEST/NET-VEH token borrows, the
CU7001A form-code string in Q6's explain area, "Drive Other Car" ticked as an
OTHER line of business on the 125.

## ROUND 8 - the independent audit's findings, closed  [DONE]
An independent code audit (2026-08-15) confirmed the renewal + section-form
work and proved the PACKAGE forms were never covered: ACORD 125 still carried
two of the client's seven defects verbatim. All findings closed except one,
declined with a reason. Suite 2861 passed / 2 failed (same two pre-existing);
70 tests in the regression file.

- **32 (audit #1). Package-header PAIR guard** (`_resolve_package_header_identity`):
  pairing is a property of the PAIR, not of the form. On 125/101/25 headers a
  NAIC now stamps only as an ATTESTED pair - an evidenced line entry carrying
  the header's carrier WITH that NAIC. The client's literal recombination
  (Employers Mutual + 25186) is structurally impossible on every form now;
  an attested 21415 still stamps. Per-line carrier evidence with no attested
  pair -> blank; no per-line data -> legacy scalar path untouched.
- **33 (audit #2). No single package policy number -> blank header.** The
  125/101 header stamps a number only when the evidenced lines agree on ONE
  (a true package policy). Several distinct numbers = the ground truth's
  "five candidates, no package number" = blank, never the AUTO's. The
  round-1 test pinning the old scalar behavior was updated - it pinned the
  defect.
- **34 (audit #3). "Inland Marine" is not a person** - a value
  `_canon_line` classifies is a coverage line name, exempt from the
  person-name rejection (the rule, not another _NOT_A_NAME_WORDS entry).
  Plus Guard 2d: a Q4 LINE+NUMBER pair lives or dies together - when any
  guard blanks one half, the stranded half is dropped too.
- **35 (audit #4, partial by nature). Gate witnesses hardened**: "prem" (the
  schedule's own printed abbreviation) categorizes as premium, and every
  premium COLUMN of `gl_class_code_schedule` rows witnesses by construction -
  page 211's $500/$803/$1,198 component premiums can no longer stamp into
  limit boxes. Honest limit: a label naming NO category ("General Liability
  Elite Extension" as a dec-entry label with no schedule row) still yields no
  witness; keyword coverage is inherently partial and the full fix is
  categorized dec entries upstream.
- **36 (audit #5). Census safety**: threshold raised to THREE evidenced lines
  (a GL+Auto-only package is ordinary, not a census), and producer/client-
  sourced facts for a family (`wc_*`, `ebl_*` with source
  producer/client_arq/user/human) defeat suppression outright - a human's
  answer outranks an inference.
- **37 (audit #6). The 131 OTHER underlying row fills from a real leftover**:
  exactly one evidenced line whose canon class is outside
  {auto, general_liab, workers_comp, umbrella, inland_marine, property,
  crime} fills the row with its own carrier/number/dates/type (verified with
  a cyber line); zero/several/unplaceable stays blank. PolicyTypeCode/
  Description joined the owned attrs (they were gap-fillable while their row
  was blank - the audit's inconsistency). KNOWN canon limit: liquor and
  professional liability canonicalize to general_liab and therefore stay
  blank-safe rather than filling.
- **38 (audit #7). Prior term moves as a PAIR or not at all**
  (`_route_renewal_dates`): with a genuine prior_effective_date and no prior
  expiration, the old per-slot guards fabricated a prior term from halves of
  two different terms. Now both prior slots must be empty before routing
  writes either.
- **39 (audit upstream note). Term-matched prior-grid fallback**
  (`_current_number_from_prior_grid`): on a renewal the expiring policy IS
  the in-force policy, so a `prior_coverage_by_line` row for THIS line whose
  term equals the line's in-force term supplies the header number the other
  evidence missed - 127's header now fills 6E74002 instead of shipping blank
  while the 125 prior grid printed the same number. Term equality is the
  guard: a mismatched or undated row never stamps.
- **DECLINED (audit #8): widening CONFLICT_WITHHOLD_KEYS.** The intra-doc
  detector reads the merge's REJECTED candidates, and C23's composite
  reconciliation deliberately rejects the umbrella's $3M for
  gl_each_occurrence on every multi-part package - a RESOLVED cross-part
  difference, not an unresolved conflict. Widening the key set would withhold
  correct GL limits package-wide. Prerequisite: teach
  `_flag_intra_document_limit_conflicts` to ignore candidates the composite
  reconciliation already explained; then widen. Post-Tuesday work, named
  here so it is debt, not amnesia.

## ROUND 9 - the audit's second pass, closed  [DONE]
The audit confirmed rounds 1-8 (seven of the client's requirement areas PASS
or MOSTLY PASS on its own harnesses) and found the pair rule had a relocated
hole plus one inert rewrite. Suite 2873 passed / 2 failed (same two
pre-existing); 82 tests in the regression file.

- **40 (CRITICAL). Insurer_NAICCode rows B-F were wide open** - the delivered
  certificate printed "077" (not NAIC-shaped, printed nowhere) beside the
  second real carrier. Two doors closed: the package-header resolver now owns
  every NAIC row when per-line carrier evidence exists (rows beyond A are
  owned blanks - their carrier is unknown at Pass-1 time and an identifier
  the model can only fabricate must never be ASKED), and Guard 2c-N
  re-checks after the roster names fill: malformed shape -> blank (even in
  legacy sessions), no carrier in the row -> unpaired -> blank, attested
  carriers present -> the (name, NAIC) pair must be attested by an evidenced
  entry. Known safe asymmetry: an attested pair for a row-B carrier still
  ships blank (ownership wins); right-or-blank, producer fills it.
- **41. The specialty-leftover rule was inert** ("reads well and cannot
  fire") - `_canon_line` buckets liquor/professional/pollution/EBL into
  general_liab, which sat in the covered set. `_specialty_leftover_lines`
  splits the class: a name built only of generic GL vocabulary IS the GL
  policy; a distinguishing token marks its own line. Both the 131 OTHER
  underlying row and the 25 OTHER row now actually fire (verified with a
  liquor policy). Garagekeepers canonicalizes to auto and stays covered -
  documented, defensible.
- **42. The Q4 grid prints every recoverable policy** - a line whose number
  the coverage_lines summary lost recovers it from a TERM-MATCHED prior-grid
  row (same rescue as the 127 header). On the live shape the grid goes from
  1 row to GL+Auto+Umbrella+IM, each pair whole. Lines with no number from
  either source still take no row.
- **43. The 131 underlying GL carrier rescue** - two liability-classed
  entries with two carriers used to mean a permanent blank; the term-matched
  prior-grid row now settles it (EMC P&C, from the 125's own prior grid).
- **44. Vehicle rating-row borrows (requirement #3, non-currency)** - Guard
  2e: SpecialIndustryClassCode / PrimaryLiabilityRatingFactor /
  NetRatingFactor blanked when they equal the row's own CLASS or TERRITORY
  or a GL class code; FarthestZoneCode blanked when it equals the territory.
  Kills SIC 91585/7383, FACTOR 7383, FARTHEST 111 across runs; genuine
  values (a real SIC, a decimal factor, a different zone) survive.
- **45. Label-echo OTHER-coverage rows** - Guard 2f: an OtherCoverage
  description built ONLY of the form's own limit vocabulary ("Damage To
  Premises Rented To", "Medical Expense Limit", "General Aggregate Limit",
  "Commercial Liability Umbrella") is an echo; the whole row (description +
  amount + indicator) ships blank. "Employee Benefits Liability" / "Stop
  Gap" / "Hired Auto Physical Damage" survive.

Still open, unchanged and on the record: the withhold-widening decline (needs
composite-aware conflict detection first), the COI still absent from every
upload (requirement #5 remains proven by unit tests only), and the
retrieval-class residuals (127 Q8 "Y" from a subrogation-waiver quote - the
borrowed-quote LLM residual, "MEDIA USED: Print", "Drive Other Car" as an
OTHER line of business, the "2012 SUBAF" fragment, and this run's dropped
collision deductible - extraction jitter, needs the session log).

## ROUND 10 - the detection layer was blind; the latent landmines  [DONE]
The round-10 audit found the deepest one: every stamping guard built in
rounds 1-9 sits BELOW a conflict-detection layer whose comparators merge
different legal entities - so "unresolved conflicts must remain unresolved"
was broken before any guard ran. Root cause of the recurrence: the shared
normalizers were audited once at ONE call site (insurer dedup, round 2 #11)
and the equivalence semantics were never swept across the other consumers -
the exact one-shared-helper failure the 2026-08-08 scan-shape incident
documented. Suite 2886 passed / 2 failed (same two pre-existing); 95 tests
in the regression file.

- **46 (audit #1/#2). Strict entity identity for the CONFLICT layer**
  (`normalization.strict_entity_key` / `entity_identity_conflict` + the
  promotion hook in `assess_underwriting_consistency`): the coarse
  normalizers stay for the consumers whose semantics they fit (document
  clustering, submission matching, the foreign-entity drop - the auditor's
  "delete the table" was too blunt; family-collapse is CORRECT there). The
  reconciler now re-splits a coarsely-merged group when the sources name
  materially different entities: token-subset compatibility, spelling-only
  canon (Co/Company, Inc/Incorporated, L.L.C./Limited Liability Company).
  Proven: Employers Mutual vs EMC P&C -> conflict + picker; Orbin LLC vs
  Orbin Inc -> conflict on the hard-stop field; casing/truncation/suffixless
  variants stay consistent (zero new noise); Travelers-vs-Travelers-P&C and
  Hartford Fire-vs-Casualty separate correctly.
- **47 (audit #3, latent). The gate's exposure-box bug** - ACORD's Exposure
  tooltip ends "...used in calculating the premium", so name+tooltip
  classification called the box a premium box and deleted the client's OWN
  $39,300 payroll exposure as a cross-category borrow whenever it arrived
  via gap fill. Field NAME is now authoritative (tooltip only breaks ties)
  and Exposure-named boxes are exempt - an exposure IS a payroll/sales/cost
  figure.
- **48 (audit #4, latent). Guard 4 deleted the single-location address** -
  mailing == physical == premises is the ordinary case; the same string in
  three families read as boilerplate and every copy died. A value matching
  the applicant's own mailing/physical/garaging address facts is data,
  exempt.
- **49 (audit #6). `underlying_policies` is finally consumed** - extracted as
  {line, limit, carrier, policy_no}, purpose-built for the 131 grid, never
  read anywhere. It now OUTRANKS coverage_lines in
  `_resolve_underlying_policy_row` (per-line strict match; single value
  stamps, internal disagreement blanks, silence falls through) and works
  even when coverage_lines is absent.
- **50 (audit #5). WC class codes reach ACORD 130** - the registry bindings
  pointed at field names on no schema; the real names
  (`WorkersCompensation_RateClass_ClassificationCode/DutiesDescription/
  RemunerationAmount/Rate`) are bound. Dead aliases retained per the
  vehicle-schedule precedent. Remaining dead schedules (wc_officers,
  inland_marine_items, auto_garaging_addresses) still open - named debt.
- **51 (open door #1). The umbrella's own UM/UIM/med-pay election owned**
  (`_resolve_umbrella_um_election`): every run carried the underlying auto's
  $1M/$1M/$5,000. Umbrella-scoped facts (or a producer answer) or blank;
  gap fill never asked. **52 (open door #2). AdvertisersLiability joined the
  census family** (phrase = bare "advertisers" - "advertisers liability"
  canonicalizes to general_liab and the GL line would falsely attest it):
  "MEDIA USED: Print" is dead.

Answer to "did we address 'information losing its meaning, relationship, or
context'": rounds 1-9 rebuilt the STAMPING layer around it (line-scoped
identity, attested pairs, meaning gate, dependents, census, borrow guards) -
the audit's own scorecard has requirements 1/3/4/6/7 at PASS on the forms.
Round 10 extended it to the DETECTION layer (the reconciler can now see the
disagreements the client asked to be asked about) and defused the guards
that would have deleted correct meaning under gap fill. Remaining, named:
COI still needed in an upload for #5's live proof, withhold-widening behind
composite-aware detection, dead schedules above, and the borrowed-quote
Yes/No residual (LLM-class).

## ROUND 11 (2026-08-16) - the researcher's four leftovers, verified  [DONE]
Each claim checked against HEAD before acting. Suite 2889 passed / 2 failed
(same two pre-existing); 98 tests in the regression file.

- **Claim "underlying_policies unused": STALE** - consumed since round 10
  (fix 49), re-verified: the dedicated fact outranks coverage_lines and works
  without it. wc_class_codes likewise bound since fix 50.
- **53. VehicleFleet grid owned** (`_resolve_vehicle_fleet_grid`): all 56
  `VehicleFleet_*` cells are authoritative blanks whenever an
  `auto_vehicle_schedule` exists - four runs produced four different junks
  there ("PRIV PASSENGER" as PROPERTY HAULED, the "0 - 25" band, fabricated
  zeros/radii, IM class names). The 127's schedule is the real fleet
  evidence; the model is never asked. No schedule -> legacy path.
- **54. wc_officers bind to ACORD 130's real fields**
  (`WorkersCompensation_Individual_FullName/TitleRelationshipCode/
  OwnershipPercent`) - the Officer_*/Owner_* bases matched no schema field.
  IncludedExcludedCode deliberately unbound: the fact carries two booleans,
  the form one code - a mapping, not a binding; named debt.
- **inland_marine_items: UNBINDABLE, verified** - ACORD 141's schema (364
  fields) contains no per-item schedule fields at all. The capture has no
  landing zone on any of the 17 forms; surfacing it belongs to ARQ/ACORD 101
  remarks, not a binding. Documented, not forced.
- **auto_garaging_addresses: string-shaped** (extraction emits `[string]`),
  so component binding to Vehicle_PhysicalAddress_* needs a parsing resolver.
  Deliberately deferred: the garaging boxes have printed CORRECTLY on all
  four live runs, so this is debt without a defect attached.
- **Withhold scope + COI: unchanged and standing** - one key, widening still
  gated on composite-aware detection, requirement #5 has no live proof until
  a COI is in the upload set. The architecture point (flat identity scalars
  with form-boundary defense) is acknowledged: the boundary now carries
  UNIVERSAL backstops (package pair guard, NAIC pair rule, strict conflict
  comparator) rather than per-field lists; migrating the five identity
  scalars to per-line facts remains the long-term architecture item the
  client explicitly did not order for Tuesday.

## ROUND 12 (2026-08-16) - the auditor's three, all mine, all closed  [DONE]
Suite 2914 passed / 2 failed (same two pre-existing); 104 tests in the
regression file. (During this round the tree briefly showed 3 failures in
test_reopen_recommendation.py - caused by a PARALLEL session's uncommitted
edits to arq_service/audit_service, files this work has never touched; they
cleared in the same hour. Noted for the record, not owned here.)

- **55 (#1). The fleet-grid resolver read a phantom key** - written
  "auto_vehicle_schedule", extraction writes `auto_vin_schedule`; the
  resolver never fired and all 56 cells stayed asked. The 2026-08-07
  phantom-fact-key signature, reproduced by the very person who had just
  read that entry. One-word fix, plus the durable guard the audit demanded:
  `TestReadWhatIsWritten` pins EVERY fact key the relationship resolvers
  consume against the extraction source, and greps pdf_service for the
  phantom spelling.
- **56 (#2). The umbrella UM fix was right by accident** - the resolver read
  three keys nothing wrote, so the defect was closed but a genuine umbrella
  UM election could never be captured, invisibly. The three keys are now in
  LLM call 1's schema with a RULE-1 scoping clause (the umbrella's OWN
  election; the underlying auto's figures belong to auto_um_uim_limit and
  must never be copied; null when unstated). improving-ll.md round-12
  addendum logs the prompt change.
- **57 (#3). The dedicated fact no longer OUTRANKS - it CROSS-CHECKS.** The
  audit proved a single confidently-wrong underlying_policies row put the
  AUTO number back on the umbrella form (defect #1 reopened by its own fix,
  since the fact gets no repair while coverage_lines does). Both sources now
  resolve independently: agreement stamps, a lone voice stamps, and
  disagreement on a line's identity is a CONFLICT - blank, ask. Spelling
  variants ("&" vs "and") compare through strict_entity_key so two printings
  of one carrier are not a conflict. The round-10 test that pinned the
  outranking was updated - it pinned the defect.
- **#4 standing, unchanged**: CONFLICT_WITHHOLD_KEYS = {umbrella_limit},
  widening gated on composite-aware detection, and requirement #5 has never
  executed live - THE $1M COI MUST BE IN TUESDAY'S UPLOAD.

Confirmed FIXED on the third run's paper (for the record): 131 header dates,
EL underlying row's junk dates gone, foreign-sales $34 gone, EBL amounts gone,
25 junk OTHER row gone, WC row dates gone, cert number empty, 127 Q9/Q12
clean, INSURER C = the real EMC P&C. Remaining after round 7 (retrieval
class, not relationship class): the 127 vehicle rating-box shuffle
(CLASS/SIC/FACTOR tokens), 131 vehicles-grid counts ("0 - 25" band, zeros, IM
class names as PROPERTY HAULED - no anchor question exists for that grid),
apartments row (no anchor question in the schema), ISO edition date jitter,
Q7 fabricated Y, and the extraction-side auto/GL number attribution above.

---

## ROUND 13 - 2026-08-16 client audit of the fresh Orbin run (fixes 58-64)

**The headline the client asked for.** Six of the seven relationship
requirements are demonstrably working on the delivered forms: line-scoped
policy numbers (131 header = 6J7-40-02---26, its own), carrier+NAIC as a pair
(no NAIC anywhere - none is printed in the package), $39,300 stays payroll
(ANN GROSS SALES blank), unknown stays unknown (FOREIGN GROSS SALES blank, was
"$0"), conflicts stay unresolved (see below), and renewal chronology (125
PROPOSED 07/15/2026-07/15/2027 while the underlying grid keeps 2025-2026).

**Requirement #5 fired live for the first time, and the form proves it.**
Measured both ways: with no conflict `umbrella_limit` stamps $3,000,000 into
EA OCC and AGG; with the key flagged conflicted BOTH boxes blank while
RETAINED LIMIT still stamps $0. The delivered 131 shows exactly the second
signature. The $1M COI was in this upload and Primble refused to pick a side.
CONFIRM THE DATA CONSISTENCY CARD ON THE REVIEW SCREEN.

### The three "regressions" were a code gap, not extraction non-determinism
Reproduced by constructing this run's fact shape and driving the real
resolvers - the delivered PDFs come out byte-for-byte. `coverage_lines`
arrived with the auto and GL entries carrying a premium and a term but NO
policy number; `underlying_policies` carried both numbers, which is why ACORD
131's underlying grid printed them correctly. Three other surfaces needed the
same numbers and none of them asked that fact. The 2026-08-15 lesson - "never
let a corrupt summary stand in for absent evidence" - one fact over.

- **58. `_underlying_rows_for_line` / `_underlying_policy_number` /
  `_underlying_carrier`** - one reading of the dedicated fact, used by every
  caller: strict line matching, form numbers rejected, an answer only when it
  settles the line unambiguously, and **the umbrella dropped before matching**
  (it is never underlying to itself, so a corrupt row can never feed the 131
  header). Wired into `_resolve_section_policy_identity` (both branches) and
  `_resolve_other_policy_cell`. 127 header -> 6E74002; Q4 -> 4 of 4 correctly
  paired.
- **59. `_prior_rows_from_underlying_policies`** - the 125 PRIOR CARRIER grid
  was empty while the session held both expiring policies. On a ROUTED RENEWAL
  (is_renewal affirmative AND both prior_* dates present) the in-force
  underlying policies ARE the coverage expiring at renewal. Gated on exactly
  that, stamped with the expiring term, premium never derived, and exempt from
  the current-policy filter because these rows are BUILT from the prior term.
  Not a renewal, or no routed term -> derives nothing.
- **60. A line of business must be PROVEN, not merely unrefuted.** Third
  incident, third token set, one defect: the filter was a denylist, so
  "Premium for Attached Items 4." and "Premium for Endorsements" (dec-page
  premium subtotals) printed as ticked lines of business, after "Drive Other
  Car" last run. Now `_names_a_line_of_business`: a money-label head is never
  a line, and the name must share a token with ACORD's OWN LOB checkbox
  vocabulary (`_acord_lob_vocab`, derived from `_lob_indicator_index`). 13/13
  on a hand-checked corpus. Cost: a line named entirely outside ACORD's
  vocabulary ships blank - accepted, and logged.
- **61. The physical-damage deductibles were extracted and never stamped.**
  `auto_deductible_comp` / `auto_deductible_collision` are extracted,
  registered, reconciled and read by four checks - and appeared in
  `pdf_service.py` exactly once, in a COMMENT. The `auto_covered_symbols`
  signature from 2026-08-07 verbatim. `_resolve_vehicle_deductible_cell` binds
  them with policy-level inheritance over real rows only.
- **62. "ACV" in a dollar box.** An amount box now rejects a value written as
  an ABBREVIATION that names an adjacent `/Btn` checkbox in the same field
  family (`_value_names_a_sibling_checkbox`, schema-derived). **The corpus
  caught two over-reaches before they shipped**: the first cut also matched
  whole words and rejected "Included" on 73 ACORD 160 fields; a 2-char acronym
  floor rejected "N/A" on 17 ACORD 28 fields. Final rule - acronyms of 3+
  chars, value written in caps - is 0 false positives across 15,450 pairs.
  "ALS" is rejected and that is CORRECT: ACORD 160 has an
  `ActualLossSustainedIndicator` beside it.
- **63. The umbrella is not underlying to itself; ADDITIONAL INTERESTS has no
  fact.** The whole `UnderlyingCoverage_*` family had ONE resolver, so the
  rest was gap-fill guesswork - two of three ticks were wrong.
  `_resolve_underlying_coverage_grid` drives the OTHER rows from
  `_specialty_leftover_lines` with the same covered-canon set the policy rows
  use (umbrella excluded by construction, not by a name check), and owns
  ADDITIONAL INTERESTS as a blank whenever per-line evidence exists.
- **64. An address is not a name; a symbol is not a rating credit.** Guard 2g
  blanks an address-shaped value in any `FullName` / `PropertyDescription` /
  `OccupancyDescription` box (13/13 corpus, company names untouched). Guard 2e
  gained the covered-auto symbol cells as borrow sources, leading zeros
  stripped - NET VEH DR/CR = 07 was the comp symbol two cells away.

### The Y/N explanations: the explanation IS the grounding quote
The client's "sometimes they even mention the paragraph" identified the
mechanism without seeing the code - a kept Yes writes its grounding quote into
the paired Explanation box, so an explanation is only ever as good as the
sentence cited. ACORD 127 Q9 cited the CA 99 10 Drive-Other-Car endorsement
DEFINING who would be an insured. Every existing rejector looks for the
CONTRACT as grammatical subject; here the subject is "any individual".

`_quote_is_policy_form_wording` adds two form-only signals, never topical:
SELF-REFERENCE (the sentence points at its own document - "of this
endorsement", "in PARAGRAPH B.1.") and DEFINED TERMS IN QUOTES (two or more,
the ISO drafting convention). Applied to Y and N: an endorsement defining who
would be an insured answers neither. **11/11 genuine applicant sentences
survive, including the two C46 recorded as wrongly blanked.**

**Two further rules were built, measured and DELETED rather than shipped** -
recorded in the code so nobody rebuilds them. (1) "every significant word is
coverage vocabulary" was inert at the narrow vocab and, when widened to reach
"subrogation", rejected "Subcontractors are required to carry coverage."
(2) `_quote_asserts_something` on the Yes side returns True for the Q8 title
list and False for the legitimate "Crime Coverage Policy No. BBC7263" - wrong
in both directions. Q8 stays the documented wrong-subject borrow.

### Verification
Full delivered-run reproduction re-run after the fixes: 127 header, both 127
deductibles, both 125 prior-carrier rows, 131 header, both 131 underlying
rows, Q4 4-of-4, zero fabricated LOB rows - all PASS.
Tests: `backend/tests/test_relationship_fixes_20260816.py` (76, all through
the real `map_facts_to_form` / `compute_form_gaps`, including the C46-shaped
anti-rot guard `TestAmountConventionsSurviveTheCheckboxRule` and the
read-what-is-written key pin). Suite **3009 passed / 2 failed** - the same two
pre-existing unrelated failures, zero regressions.

### Standing, unchanged
`CONFLICT_WITHHOLD_KEYS` = {umbrella_limit}; widening still gated on
composite-aware conflict detection. Pre-existing and deliberately untouched:
the coverage-PART denylist also drops genuine specialty lines ("Pollution
Liability"), pinned by test as a decision rather than a surprise - loosening
it would print MORE values, the opposite of what the client asked for. ACORD
127's empty driver block needs eyes on the source package; ISO edition-date
jitter and Q8's borrowed quote remain.

---

## ROUND 14 - 2026-08-17: "ACORD 125 and 127 contain no unsupported critical values"

Scope narrowed by the owner to 125/127, with one standard: nothing on those two
forms may be a value the document does not support. Under-filling is acceptable;
fabrication is not. Evidence for this round is the client's fresh run plus
`dec_index_c89a7dca-...json` (275 verified declarations entries).

**Caveat respected throughout: the dec index covers DECLARATIONS PAGES ONLY, not
the whole package.** Absence from it is not proof of fabrication - the evidence
gate verifies against the full raw text. Values confirmed REAL and left alone:
`CLASS 7383`, `ACV`, and - found while checking - `COMPREHENSIVE ACV 1000 DED` /
`COLLISION ACV 1000 DED`, so the $1,000 deductibles ARE in the source and the
open item there is extraction lifting them, not the form binding.

- **65. The package header took one line's policy number** (ACORD 125 printed
  6E7-40-02---26, the AUTO number - the client's defect #1 on a new form).
  Measured cause: **the header and Q4 used different evidence bars.** Q4 fills a
  row from any entry with a line name and a number; the header only counted
  entries that also passed the GRANT test (premium or limit). This run's entries
  stated numbers but no premium, so `evidenced` fell under 2, the resolver
  returned `_SCHED_SKIP`, and the flat scalar stamped. Now: a policy number is
  IDENTITY evidence - several distinct numbers in the inventory means the
  package has none of its own, whatever was captured about premiums. Verified: a
  genuine single-policy package still stamps; no-`coverage_lines` sessions keep
  the scalar path byte-identical.
- **66. One policy printed two ways took two of Q4's four slots and displaced
  the umbrella.** `6E74002` and `6E7-40-02---26` are the same Commercial Auto
  policy - the `---26` tail is the term marker, and the umbrella's schedule of
  underlying insurance refers to the auto policy without it. `_same_policy_
  contract` merges them only when the tail is printed SEPARATED (`---26`,
  ` - 26`) over a base of 5+ chars, so `POL123`/`POL12345` stay two policies
  (7/7 on the separation corpus). `_dedupe_rows_by_policy_contract` then keeps
  the entry that names a standard line, so "Covered Autos Liability" (a coverage
  PART on the auto dec) yields to "Business Auto". Q4 now prints all four real
  policies, umbrella included.
  **The coverage-part vocabulary test was tried first and REJECTED by
  measurement** - it classes "Business Auto" and "Commercial Liability Umbrella"
  as parts while missing "Covered Autos Liability". It would have deleted the
  two real lines and kept the fake one.
- **67. The entire enumerated LINES OF BUSINESS grid was model-guessed.** ACORD
  125 shipped CYBER AND PRIVACY ticked with no premium; "cyber" appears 0 times
  in 275 dec entries and the one "privacy" hit is a General Liability EXCLUSION
  title (`Form CG 00 69 12 23`). Measured: **all 15 named boxes were asked of the
  model**, because `_INDICATOR_RULES` maps each to a flag and `_derive_indicator`
  returns None when the flag is absent - so "the document never said" became
  "let the model decide". That is why last round's fabrication moved from the
  OTHER rows (hardened) to the named boxes beside them. `_resolve_standard_lob_
  box` now ticks only what a granted or number-bearing `coverage_lines` entry
  names, or what an existing flag already answered Yes - nothing that ticked
  before stops ticking. **Two of my own false positives were caught before
  shipping**: a bare "Liability" row ticked Fiduciary AND Liquor (fixed by the
  existing "fits several boxes, places none" rule), and the first evidence bar
  blanked four boxes that were ticking correctly (fixed by accepting a stated
  policy number as identity evidence, same distinction as fix 65).
- **68. NO. OF MEMBERS AND MANAGERS printed a fabricated "1".** No fact carries
  it and no declarations page states an LLC's member count - organisational data
  the producer supplies. Owned blank on every form, rows A/B/C, and declared in
  the ownership-contract test.
- **69. An elided citation is not a citation.** ACORD 127 Q8 ("any hold harmless
  agreements?") answered Y on `"Blanket Additional Insured status ... on a
  primary and noncontributory basis ..."`. The gate's whole contract is that a
  quote is a CONTIGUOUS phrase in the document; an internal ellipsis says the
  model joined two fragments, and the per-sentence paraphrase fallback accepted
  the join. Rejected now, on Y and N. 0 false positives across the real-evidence
  corpus. **Honest limit: I could not confirm from the delivered PDF alone that
  the stored quote carries the ellipsis rather than a renderer adding it, so
  this may or may not be what produced that particular Y.** The rule is correct
  either way; Q8's underlying wrong-subject borrow remains the documented
  residual.

### Verified after the fixes, on the delivered shape
125 header blank (was the auto number) and not asked; CYBER blank; NO. OF
MEMBERS blank; LOB grid ticking exactly Business Auto / Inland Marine / Umbrella;
Q4 printing all four policies with the umbrella restored and no half-rows.
Tests: `backend/tests/test_no_unsupported_values_20260817.py` (31). Suite
**3356 passed / 2 failed** - the same two pre-existing unrelated failures, zero
regressions. Note: total test count rose sharply this round because a parallel
session has added files to this tree.

### Still open on 125/127, named not hidden
`auto_deductible_comp` / `_collision` are not being lifted out of the dec labels
`COMPREHENSIVE ACV 1000 DED` / `COLLISION ACV 1000 DED`, so the two deductible
boxes stay blank (under-fill, extraction side). ACORD 127's MODEL cell reads
"Outback Sedan" with BODY TYPE empty. The Drive-Other-Car endorsement is still
indexed as a declarations section, which is what put a coverage PART into the
line inventory in the first place - fix 66 contains it at the form, but the
upstream attribution is untouched. 127's driver block is empty and needs eyes on
the source package.

---

## ROUND 15 - 2026-08-18: the last three unsupported values on ACORD 125/127

The 08/17 run shipped 125, 127 AND 131, so the client's four 131-only examples
were verifiable for the first time since 08/16. Evidence: those three forms plus
`dec_index_ac1f3c69-...json` (338 verified declarations entries).

**Client's seven examples, on that paper:** #2 carrier+NAIC, #3 $39,300 stays
payroll, #4 foreign sales blank, #6 renewal chronology - all FIXED and holding.
#1 FIXED on 131 (header 6J7-40-02---26, EXPIRING POL # blank) but NOT on 125,
which still printed the Auto number. #5 NOT fixed - EA OCC and AGG both stamped
$3,000,000. #7 not observable on paper.

**All three fixes below closed a defect that had already survived a fix aimed at
the same thing.** That is the pattern of this whole arc and it is worth stating
plainly: harden one surface and the same defect reappears on the next surface
that shares the weakness.

- **70. The package header counted one fact's opinion, not the policies.**
  Round 14 blanked the 125 header when `coverage_lines` itself stated two or
  more policy numbers. On the 08/17 run the numbers arrived through
  `underlying_policies` and the dec index instead - Q4 and the PRIOR CARRIER
  grid both filled correctly while `coverage_lines` carried none - so the count
  saw fewer than two and the flat scalar stamped the Auto number again. One
  fix, one source, one run later. `_distinct_package_policies` now reads EVERY
  per-line source the forms themselves read (`coverage_lines`,
  `underlying_policies`, `prior_coverage_by_line`, `dec_page_entries`), counting
  CONTRACTS via `_same_policy_contract`, and it runs AHEAD of the
  `coverage_lines` gate. Verified across all four arrival paths; a genuine
  single-policy package still stamps, including when printed with and without
  its term marker; a session with no per-line evidence anywhere is untouched.
  Pinned by an anti-rot test so a fifth source cannot be added without being
  counted.
- **71. RADIUS printed 07 while the auto dec states "RADIUS = NA" twice.** The
  comp/collision symbol, three cells right, in its own zero-padded formatting.
  Guard 2e already owns this borrow class; `Vehicle_RadiusOfUse` and
  `Vehicle_SeatingCapacityCount` were simply not in its column list.
  **The obvious fix was measured and was exactly backwards.** Comparing RADIUS
  to the symbol cell: the symbol stamps as "7", so an exact compare KEPT the
  padded borrow and DELETED a genuine 7-mile radius; a zero-insensitive compare
  deletes a real radius of 7 on any vehicle whose symbol is 7. No sibling is
  used. ACORD declares both boxes "Enter number:" - a quantity is never written
  "07", a code is - so the padding alone settles it, and the branch is TERMINAL
  so an unpadded quantity never reaches the code comparisons.
- **72. ACORD 127 Q8 "any hold harmless agreements?" = Y.** `"hold harmless"`
  appears 0 times in 338 dec entries. Two independent faults, so two rules:
  * **A seam proves the quote was assembled, not cited.**
    `"...executed prior to loss.mary an"` - a sentence-ending period followed
    immediately by a lowercase letter cannot occur in copied prose. Same defect
    the round-14 ellipsis rule catches, in the shape carrying no ellipsis.
    URL/e-mail guarded.
  * **A BARE instrument noun is still the contract as its own subject.**
    "Additional insured provisions apply...", "waiver of recovery applies only
    when..." - grammatically identical to "these provisions apply", which
    `_POLICY_SELF_SUBJECT_RE` already rejected. The determiner was never what
    made it contract language.
    **Making the determiner optional was reverted the same minute by
    `test_no_acord_tooltip_is_flagged`**, which flagged 14 of ACORD's OWN
    tooltips ("Enter deductible: The deductible amount that is to apply to this
    subject of insurance."). That guard exists to stop this pattern learning to
    blank legitimate answers, and it earned its keep. The separation is
    ADJACENCY: a bare-noun subject must be followed by its operative verb
    directly, allowing one "of <noun>" and an adverb; a determiner-led subject
    keeps the proven 60-character window. `waivers?` completes the instrument-
    noun class.
    Measured 8/8 rejected, **0 false positives across 15 real sentences plus
    ACORD's own tooltip - including "The applicant signed a hold harmless
    agreement with the general contractor", which is the LEGITIMATE Yes for
    this very question and must survive.** The 5,852-tooltip sweep passes.

**Confirmed supported and deliberately left alone**, checked against the index
rather than assumed: `COST NEW 26680` (printed twice - I had wrongly flagged it
as possibly invented in round 14), `COMPREHENSIVE/COLLISION ACV 1000 DED` (the
deductibles now stamp), `CLASS 7383`, `TERR 111`, `ACV`, `DIRECT BILL`, all four
line premiums, `$10,663`. `SEAT CP` blank is correct - "seating capacity"
appears 0 times. And `cyber` now appears twice in the index, **both as
exclusions** - proof the round-14 Cyber fix was reading an exclusion as coverage.

Tests: `backend/tests/test_no_unsupported_values_20260818.py` (43). Suite
**3399 passed / 2 failed** - the same two pre-existing unrelated failures, zero
regressions.

### Named, not fixed
125's AUDIT box prints "A": partly supported (the GL dec says "Audit Period =
Annual") but the Umbrella dec says "PREMIUM NOT SUBJECT TO AUDIT", so one
package-level code asserts something the lines disagree about, and "A" is our
abbreviation rather than the document's word. Owner's call.
On 131 (not this round's scope): the $3M umbrella limit still stamps against the
$1M COI; a limit is concatenated with a line name ("$3,000,000 Commercial Ge...");
Q7 answers Y with text listing what IS insured against a question about what is
NOT; a document title sits in the underlying-coverage-information box; the ISO
edition date reads "04 13". 127's driver block is empty and needs eyes on the
source package.
