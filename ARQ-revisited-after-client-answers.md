# ARQ Revisited - After Client Answers (Workstream 5)

Status: APPROVED spec, implementation in progress.
Date: 2026-07-01
Owner: Lead Architect

This is the agreed, decision-locked spec for reworking the ARQ (Agent Report
Questionnaire) curation into the client's clarified 3-bucket model. It supersedes
the earlier 5-audience presentation. The engine's finer-grained routing is kept
internally; the buckets are a derived view on top of it, so nothing that works
today regresses.

Guiding rule for this change set: **minimal, additive changes only.** Do not
rewrite working code. The app must behave identically except for the specified
re-bucketing. Mobile/responsive layout must remain intact, and iOS/macOS must
keep working exactly as Windows/Android do.

---

## 1. Client's model (verbatim intent)

Three buckets, separated by WHO should answer:

1. **Client** - only what the insured can reasonably answer. Examples (NOT an
   exhaustive whitelist - the routing must stay generic): operations, revenue,
   payroll, number of employees, years in business, locations, property details,
   loss history, safety practices, all drivers (full name, DOB, DL#, state) with
   the VINs they drive, subcontractor usage as a % per class code, "do vehicles
   return to the place of business / yard?".
2. **Agency** - producer / CSR / account manager answers: producer info, agency
   contact info, carrier information, policy numbers, prior carrier info, ACORD
   form edition, submission goal, market selection, coverage intent.
3. **Underwriting / Internal Review** - NOT auto-sent to the client; shown as
   internal flags: cross-form conflicts, ACV vs RCV mismatch, underlying umbrella
   support missing, form-recommendation uncertainty, coverage-gap detection,
   conflicting named insureds, conflicting addresses.

Metrics to surface (not just total volume): Client count, Agency count, Critical
count, Optional count, Duplicate/Merged questions removed.

V1 default: pre-select **only critical Client questions**. Agency + Internal are
deselected by default but the producer can manually add (tick) any of them.

---

## 2. Locked decisions (all open questions resolved)

- **ACORD form edition** -> Agency (client stated).
- **Internal/agency items are promotable** -> Yes; producer can tick them into the
  send list ("Allow push to client email" option chosen). No new producer-answer
  panel is built in V1 - reuse the existing send/apply/recalc pipeline.
- **"Duplicate/Merged removed"** -> surfaced as a real metric.
- **Coverage intent** -> means producer STRATEGY (submission goal / market
  selection / why-marketing / urgency) -> Agency. The insured's DESIRED LIMITS
  (GL/umbrella/auto/property amounts) STAY in the Client bucket and keep driving
  SQS. Re-bucketing is audience-only; SQS scoring is untouched.
- **Cross-form conflicts** -> Underwriting/Internal flags by default (never
  auto-sent). Keep generating the resolution question so the producer can
  one-click escalate the ones whose fix is a clean client-answerable fact
  (Option B). Purely-judgment conflicts (ACV/RCV, conflicting insureds/addresses)
  have no resolution-question entry, so they never become client questions.
- **Policy numbers (current + prior) and prior-carrier info** -> Agency.
- **Never-useful fields** (producer fax, barcodes, system IDs) -> kept in a
  separate, non-selectable "Never send" row inside the Internal area.
- **Subcontractor % per class code** -> keep the single overall
  `percent_subcontracted` question + capture the per-class-code detail as a
  free-text remark. No structured repeatable UI in V1.
- **Yard question** -> add as a curated client question; stored as context/fact.
- **Examples != whitelist** -> the bucketing stays generic/pattern-driven. The
  named examples become regression tests proving the generic rules cover them,
  not a hardcoded allowlist. Rule 7 (uncurated raw field -> internal) stays as the
  safety valve against the ~1,700-field explosion.

---

## 3. Buckets are DERIVED from audience (no destructive rename)

Keep the 5 internal audiences (routing precision + existing tests). Add a coarse
`bucket` derived from audience:

| audience     | bucket        |
|--------------|---------------|
| client       | client        |
| producer     | agency        |
| carrier      | underwriting  |  (carrier's OWN underwriter / uw conditions)
| internal     | underwriting  |
| do_not_send  | do_not_send   |  (rendered as the non-selectable "Never send" row)

Note: "Carrier INFORMATION" the agency supplies (insurer name/policy/phone/
address, policy numbers, prior carrier) is routed to the **producer** audience via
new agency patterns -> Agency bucket. This is distinct from the `carrier` audience
(the carrier's own underwriter / cancellation-nonrenewal underwriting), which
stays Underwriting.

---

## 4. Implementation (files + exact changes)

### 4.1 backend/services/question_classifier.py
- Add `BUCKET_*` constants, `_AUDIENCE_TO_BUCKET`, `BUCKET_LABELS`, `BUCKET_ORDER`.
- Add `_AGENCY_PATTERNS` (prior_carrier, prior_policy, policy_number, insurer,
  carrier_marketing, submission_urgency/goal, market_selection, coverage_intent,
  acord/form edition, umbrella underlying schedule / follow-form). Checked AFTER
  carrier patterns (so `insurer_underwriter*` stays carrier) and BEFORE the
  critical/important/curated client branches.
- Remove `policy_number`, `prior_policy_number` from `_CLIENT_WHITELIST` (they are
  Agency now). Keep naics/sic/contact/class-code whitelisting.
- Cross-form branch: default `audience = AUDIENCE_INTERNAL` (bucket underwriting),
  keep `priority` critical/important for severity display, keep
  `hard_stop_resolution`. It is suppressed from the default client set.
- Compute `escalatable_to_client` = cross-form AND field resolves to a
  client-answerable fact (critical/important/curated/whitelisted) AND not matched
  by do_not_send/producer/agency/carrier patterns.
- Return `bucket`, `bucket_label`, `escalatable_to_client` in the taxonomy dict.
- `apply_default_selection`: add `bucket_client/bucket_agency/bucket_underwriting/
  bucket_do_not_send` counts. Default-selection logic unchanged (only client +
  critical, capped).

### 4.2 backend/services/arq_service.py
- Add an optional `stats` out-param to `generate_arq_questions` /
  `generate_arq_questions_from_facts`; increment `stats["merged_removed"]` at the
  canonical-merge dedup site. Backward compatible (default None).
- Route umbrella evidence questions to Agency automatically via the new agency
  patterns (no code change needed beyond the pattern list; they are already
  classified through `decorate_questions`).
- Add two curated client questions (generic, additive):
  - `vehicles_return_to_premises` (yard question) - injected when auto coverage
    present, unanswered. field_type text.
  - `subcontractor_pct_by_class_code` (per-class-code % as free-text remark) -
    injected when GL coverage present, unanswered. field_type text.
  Both added to `_FIELD_QUESTION_MAP` + `_FIELD_HINT_MAP`, so they become canonical
  facts (via `_canonical_fact_keys()`) and flow to `facts` on answer. Both classify
  as OPTIONAL client -> shown in Client panel, not pre-selected (safe, opt-in).

### 4.3 backend/routes/arq_routes.py
- `/generate`: pass a `stats` dict into the generator(s); after
  `apply_default_selection`, set `selection_summary["merged_removed"]` = generator
  merges + the route-level cross-form-vs-per-form dedup count.
- `/send`: carry `bucket`, `bucket_label`, `escalatable_to_client` through the
  sanitizer; hard-drop any question with bucket/audience == do_not_send (defense in
  depth; the UI already makes them non-selectable).

### 4.4 frontend/src/components/form/AcordModal.jsx
- Add `bucketOf(q)` with audience fallback for legacy stored ARQs.
- Group into: Client panel (grouped by topic, only bucket==client && !suppressed);
  Agency collapsible; Underwriting/Internal Review collapsible (flags; show an
  "Add to client" hint on `escalatable_to_client` items); non-selectable
  "Never send" row (bucket==do_not_send).
- Header metric chips from `selection_summary`: Client / Agency / Critical /
  Optional / "N merged".
- No em-dashes in new copy. No layout/responsive changes beyond relabeling and
  regrouping the existing rows. `renderRow` reused unchanged.

### 4.5 backend/tests/test_question_controls.py
- Update the cross-form test to the new contract (internal/underwriting default,
  not auto-client; escalatable_to_client True; hard_stop_resolution preserved).
- Add: prior_carrier/policy_number/insurer -> Agency bucket; bucket derivation;
  bucket counts + merged metric shape.

---

## 5. Verification (do not trust tests/comments alone)

1. `python -m pytest backend/tests/test_question_controls.py -v` green.
2. Run the full backend test suite to catch regressions in dismiss-credit /
   sqs-scoring / acord125 / workstream3 tests.
3. Functional smoke: a standalone script that builds a synthetic question set
   (client facts + agency fields + cross-form conflict + raw plumbing), runs
   `decorate_questions` + `apply_default_selection`, and asserts the bucket split,
   default-selection count, and metrics are correct end-to-end.
4. `npm run build` (frontend) passes - no syntax/type errors.

---

## 6. Non-goals / guardrails

- No new producer-answer panel / DB columns.
- No change to SQS scoring, cross-form validation rules, or the apply/recalc math.
- No change to the ACORD-125 yellow-field send guard behavior.
- No responsive/layout redesign; iOS/macOS parity preserved (pure JS/JSX, no
  platform-specific APIs introduced).
