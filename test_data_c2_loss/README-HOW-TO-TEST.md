# C2 Loss History - live test packages (regenerated 2026-08-25)

Five SEPARATE packages. Upload each scenario's file(s) as its OWN new session,
select **ACORD 125 only**, generate, then read the results in the review screen:

* **Loss History pillar + state**: right sidebar -> "Total Package Score" ->
  expand -> the **Loss History** row (number) and the state label under it.
  Click the label for the provenance card. "Matched on: ..." renders there too.
* **Cards**: the recommendations list (loss cards name their action).
* **Data Consistency / issues**: the validation & issues area (S3 only).
* **Client questionnaire**: the "Send to Client" question list (S1, S4).

Every number below was produced by running the REAL scorer against the fact
shape each package should extract to - not estimated.

| # | Upload | Expect | Previously |
|---|--------|--------|-----------------|
| S1 | 1A + 1B | Loss History **60**, state "Loss runs match insured", Matched on: name, fein, policy number. Card says pinned at 60 / confirm claim years. **NO prior-carrier card, NO valuation-date deduction.** ARQ does NOT ask "how many years of claims history can you provide" | 45 (unknown-date -15) |
| S2 | 2A + 2B | Loss History **85** exactly. TWO cards prefixed "Underwriting advisory (no score effect)" (frequency + loss ratio), each with NO points chip. State "Loss data reconciled" | 50 |
| S3 | 3A + 3B | Loss History **45** (capped), state "Conflicting". A conflict card AND, on the pre-form Review screen, a Data Consistency warning ("held at 45") | 45 cap; DC card added |
| S4 | 4A only | Loss History **25**, state "No loss information provided". Two cards: attestation + "confirm New Venture status" | no New Venture concept |
| S5 | 5A + 5B | Loss History **50**, state "Loss runs requested / pending" | 70 |
| **S6** | 6A + 6B | **100**, tier `strong`, **Matched on: dba_name, fein, policy number**. The run is issued to the trade name "CF Logistics" that the application itself declares | 25 (was `no_match`) |
| **S7** | 7A + 7B | **92**, tier `moderate`, note: *"tax ID matches ... Confirm the prior name or the entity relationship"*. The run's insured name appears nowhere else in the package | 25 (was `no_match`) |
| **S8** | 8A only | **25** at first. Answer the attestation "No - no claims or losses in the past 5 years" -> **85**, because the business is 3 years old. (A 5+ year business answering identically reaches only 60 - that is the ladder working) | 60 flat, no age awareness |
| **S9** | 9A + 9B | **90** with a "Prior carrier name missing" card. Answer that card with **None** -> **100**: the applicant is previously uninsured, not missing a carrier | 90, no way to clear it |
| **S10** | 10A only | Not a loss test - this one checks the **hard stop and warning** controls. Select **ACORD 140** as well as 125. Expect a "Minimum Viable COPE incomplete" HARD STOP and a "Carrier-Grade COPE incomplete" WARNING. Click **Open to fix** on each: occupancy, construction, sprinkler, protection class, valuation and period of restoration are now **dropdowns**; building value and year built stay typed inputs | every one was a bare text box |

S4's three answer flows (each on a FRESH session):
* **New Venture = Yes** -> pillar **N/A**, package rescales (loss AND umbrella
  both N/A), loss questions disappear from the client list.
* **"No - no claims or losses in the past 5 years"** -> pillar **N/A**, state
  *"Not applicable - under a year in business"*. **This is new**: S4's own
  application dates the business 60 days ago, so it falls in Brent's 0-1 year
  band - a business too young to have loss runs is no longer scored as if it
  withheld them. It scored 60 before his ruling.
* **"Yes - we have had claims or losses"** -> **25**, state "Prior claims known
  - runs not provided", and the client list gains the availability select
  ("Have loss runs been requested, or are any available to upload?").

What to send back per scenario: the Loss History pillar number, the state label,
the Matched-on line (S1/S2/S3), and which cards you saw. Screenshots beat prose.

Caveats
* Regenerate before every run (dates are relative to today) - the standing
  stale-fixture rule.
* S1 depends on the model NOT inventing claim years; if S1 shows a state of
  "Loss data reconciled" the model hallucinated dates - send the extracted
  facts and we adjust the fixture, not the code.
* S4 / S8 / S9 depend on `years_in_business` being derived from the printed
  business start date. If a score comes back on the wrong rung of the ladder,
  check that figure on the review screen FIRST - the band, not the scorer, is
  the likely culprit.
* S6 depends on the DBA being extracted from the application. If the tier
  comes back `no_match`, look at whether `dba_name` was captured before
  suspecting the ruling logic.
