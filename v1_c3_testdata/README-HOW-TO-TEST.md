# V1 C3 - SQS Scoring Integrity: how to test

Generated 2026-08-26. **Regenerate before every run**
(`py backend/scripts/make_v1_c3_test_pdfs.py`) - the policy dates are computed
from today, so a stale set can drift into an expired-term path and change what
you see for reasons that have nothing to do with C3.

## The two rules that make or break this

1. **One scenario = one session.** Start a NEW submission for each scenario.
   They are deliberately different companies; mixing them lets cross-document
   identity matching bleed and you will chase ghosts.
2. **Where a scenario lists two files, upload them TOGETHER in that one
   session.** For S2, S5 and S7 the second document is the entire test.

## Where to look

Almost every check below lives in the same place: open the submission, expand
**Total Package Score**, and read the **How** line plus the pillar rows. Click a
pillar to expand its sub-rows.

---

## S1 - Declarations page only  (clause 3.3)

**Upload:** `S1_dec_page_only.pdf` (one file)
**Generate:** ACORD 125

A dec page is issued by the carrier, so it prints no agency name and no
applicant contact details. It should be forgiven for the first and NOT the
second.

**Expect**
- A recommendation asking for **contact information**, and it is worth **real
  points** (not "0").
- A recommendation asking for **producer / agency name**, and it is worth
  **0 points** - still asked for, cannot move the score.
- Structural sub-rows show **Core Application (Tier 1) 80%**.

**Send back:** the package score, and a screenshot of the expanded Structural
rows plus those two recommendation cards.

---

## S2 - Dec page PLUS application  (clause 3.3)

**Upload:** `S2A_dec_page.pdf` **and** `S2B_application.pdf` **together**
**Generate:** ACORD 125

Same missing details as S1, but the dec page is no longer the only document.
The exemption must switch off entirely.

**Expect**
- **Both** producer name and contact information asked for, and **both worth
  real points now**.
- Structural sub-rows show **Core Application (Tier 1) 60%**.
- Package score roughly **2 points lower** than S1's.

**Send back:** the package score and the expanded Structural rows.

---

## S3 - GL only, no payroll and no Workers Comp  (clauses 3.5 / 3.14)

**Upload:** `S3_application_gl_only.pdf`
**Generate:** ACORD 125 + ACORD 126

This submission carries all six Tier 2 facts and deliberately no payroll, no
X-mod and no WC data. Before this fix it was marked down for all of them.

**Expect**
- Structural sub-rows show **Underwriting Profile (Tier 2) 100%**.
- **No recommendation** anywhere saying annual payroll, X-mod, WC payroll period
  or owner/officer exclusions are missing **from Structural Completeness**.
- NAICS is **not** asked of the client, and there are **no suggested-code chips**
  in the questionnaire (clause 3.13).

**Send back:** the Tier 2 row, and the full recommendation list.

---

## S4 - Revenue and payroll both absent  (owner ruling)

**Upload:** `S4_application_no_revenue_no_payroll.pdf`
**Generate:** ACORD 125 + ACORD 126

No revenue figure and no payroll figure are printed anywhere. Revenue is a
Tier 2 field, so Structural should charge for it - **once**. Exposure
Consistency must not charge again.

**Expect**
- Structural's **Underwriting Profile (Tier 2) is 83%**, and its tooltip lists
  **Annual revenue** as the missing item.
- Expand **Exposure Consistency**: **Revenue/Sales is 100%**. That is the whole
  test. If it is below 100, revenue is still being charged twice.
- Payroll/Employee sits at **92%**. The missing 8 is the separate
  "employees but no Workers Comp coverage" rule, not a completeness charge.

**Send back:** the expanded Structural rows AND the expanded Exposure rows.

---

## S5 - Two documents, two different revenues  (clause 3.8)

**Upload:** `S5A_dec_page_revenue_2_4M.pdf` **and**
`S5B_application_revenue_3_15M.pdf` **together**
**Generate:** ACORD 125 + ACORD 126

$2,400,000 on the dec page, $3,150,000 on the application.

**Expect**
- A **Data Consistency** entry for annual revenue showing both figures.
- A value **is still stamped** on the form - a conflict does not blank the box.
- The submission is **not** treated as fully complete on that field.

**Send back:** the Data Consistency panel, and what the revenue box on ACORD
125 actually contains.

---

## S6 - Physical address  (clause 3.12). TWO separate sessions.

**Session A - upload:** `S6A_property_with_location_schedule.pdf`
**Session B - upload:** `S6B_property_no_location_schedule.pdf`
**Generate (both):** ACORD 125 + ACORD 140

Both are property risks with a PO Box for mail. A carries a location schedule
with real street addresses; B does not.

**Expect**
- **A: NO warning** about physical versus mailing address. The schedule already
  says where the risk is.
- **B: the warning DOES fire.** This is the control - if B is silent too, the
  rule has been switched off rather than made smarter.

**Send back:** the warning list for both, side by side.

---

## S7 - Invalid policy period  (clause 3.9 + the traceability ask)

**Upload:** `S7_application_invalid_policy_period.pdf` (ONE file now)
**Generate:** ACORD 125 + ACORD 126

The effective date falls AFTER the expiration date. That is field-level hard
stop #1 in the specification, on a single document, so nothing stands between it
and the scorer.

> The first version of this scenario used two conflicting FEINs and never got
> this far: it tripped the "Possible multiple submissions" integrity gate before
> forms were generated. The second version still fired the wrong stop, because
> the coverage block printed a VALID policy period beside the invalid proposed
> dates and the document contradicted itself. It now prints one period only.

**Expect** - this is the headline check for the whole of C3:
- **How** reads **"71 earned, held at 60 = 60"** (the raw number will vary).
- **Why** names the **policy period**, not a date disagreement between
  documents. There is only one document now, so nothing can disagree.
- The displayed score is **60**.
- Expand the pillars: hover any sub-row for the arithmetic, and the Structural
  rows reconstruct the Structural pillar.

**Send back:** a screenshot of the whole expanded Total Package Score panel.
If the How and Why lines are missing, stop and tell me - nothing else in C3
matters until that renders.

---

## S8 - Credits  (clauses 3.10 / 3.11). Do these in order.

**Upload:** `S8_application_loss_runs_pending.pdf`
**Generate:** ACORD 125 + ACORD 126

### First, find the right card - by its SHAPE, not its wording

A dismissal only earns a credit when it carries a **reason**, and the reason
control appears **only on cards with no fillable field** - a gap no typed value
can close, only an arriving document.

**So: scroll the Recommendations list and find the one card that shows a
"Select a reason" dropdown.** That is the card. Do not go looking for a
particular sentence - which card it is depends on how the document classifies,
and on the last run it was *"Loss run valuation date not detected - recency
unverified"*. Any card with that dropdown works.

Every other card shows only **Open** and **Dismiss**. Dismissing those records
"Dismissed without reason" and is worth zero - by design, not a fault.

### The steps

**1.** Note the **Total Package Score**. Call it **A**.

**2.** On the card WITH the reason dropdown: pick any reason, then Dismiss.
Note the score. Call it **B**.
-> **B should be higher than A.** That is the credit.

**3.** Open either generated form, change **any** field, save.
Note the score. Call it **C**.
-> **C must still include the credit. It must not fall back toward A.**

Step 3 is the whole point. Before this fix, editing any field silently destroyed
every credit a producer had earned.

**Send back: A, B, C.** Three numbers.

> **Scope, stated honestly.** S8 live-tests ONE of clause 3.11's four rules - the
> one that was actually broken. The other three (credits added before the
> ceiling, retiring once the data is filled, never paying twice for one fact)
> need states you cannot reach by clicking, and are covered by unit tests. A
> click-through does not prove them and I am not going to imply it does.

---

## What to send back overall

For each scenario: the **package score**, and the screenshot named under it.
If any scenario behaves differently from the Expect list, send that one first
with the score and the screenshot - a single failing scenario is worth more than
seven passing ones.

Two things worth flagging even though they are expected:
- **S1 and S2 score LOWER than they would have before.** That is the fix, not a
  regression - we were waiving contact information that neither the client's
  document nor the SQS specification ever waived.
- **No NAICS suggestion chips appear anywhere.** Also deliberate (clause 3.13).
