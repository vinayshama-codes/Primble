# C2 Loss History - live test packages (regenerated 2026-08-24)

Five SEPARATE packages. Upload each scenario's file(s) as its OWN new session,
select **ACORD 125 only**, generate, then read the results in the review screen:

* **Loss History pillar + state**: right sidebar -> "Total Package Score" ->
  expand -> the **Loss History** row (number) and the state label under it.
  Click the label for the provenance card. "Matched on: ..." renders there too.
* **Cards**: the recommendations list (loss cards name their action).
* **Data Consistency / issues**: the validation & issues area (S3 only).
* **Client questionnaire**: the "Send to Client" question list (S1, S4).

| # | Upload | Expect | Old system said |
|---|--------|--------|-----------------|
| S1 | 1A + 1B | Loss History **60**, state "Loss runs match insured", Matched on: name, fein, policy number. Card says pinned at 60 / confirm claim years. **NO prior-carrier card, NO valuation-date deduction.** ARQ does NOT ask "how many years of claims history can you provide" | 45 (unknown-date -15) |
| S2 | 2A + 2B | Loss History **85** exactly. TWO cards prefixed "Underwriting advisory (no score effect)" (frequency + loss ratio). State "Loss data reconciled" | 50 (80 +10 carrier -25 freq -15 ratio) |
| S3 | 3A + 3B | Loss History **45** (capped), state "Conflicting". A conflict card ("reconcile before submission") AND a Data Consistency advisory ("held at 45"). ARQ offers the explain-the-discrepancy question | 45 cap existed; the DC card is NEW |
| S4 | 4A only | Loss History **25**, state "No loss information provided". TWO cards: the attestation card AND "confirm New Venture status". **Then**: answer the New Venture card with `Yes` -> pillar shows **N/A**, package score recomputes (loss AND umbrella both N/A -> the remaining four pillars rescale), ARQ list drops prior-carrier / claim-count / years questions | No New Venture concept at all |
| S5 | 5A + 5B | Loss History **50**, state "Loss runs requested / pending" | 70 |

S4 second path (fresh session, optional): instead of New Venture, answer the
attestation card / client question "No - no claims or losses in the past 5
years" -> pillar 60. Then (third path, optional) answer "Yes - we have had
claims or losses" -> pillar 25 and the ARQ gains the NEW loss-run availability
select ("Have loss runs been requested, or are any available to upload?").

What to send back per scenario: the Loss History pillar number, the state label,
the Matched-on line (S1/S2/S3), and which cards you saw. Screenshots beat prose.

Caveats
* Regenerate before every run (dates are relative to today) - the standing
  stale-fixture rule.
* S1 depends on the model NOT inventing claim years; if S1 shows a state of
  "Loss data reconciled" the model hallucinated dates - send the extracted
  facts and we adjust the fixture, not the code.
