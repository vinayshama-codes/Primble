# PROD-02 live test - "Specific Wording Requirements" boilerplate card

**One session. Upload BOTH files together.**

    P1_dec_page.pdf
    P2_certificate.pdf

## Why two files and not one

This is a **cross-document** conflict. The code that raises the card returns
nothing unless the session has 2+ documents, and one uploaded file is one
document. A single PDF cannot produce the card even on the OLD code, so a
one-file run would prove nothing either way.

## What was reported

The pre-form review screen's **IMPORTANT** band - the 5-second "fix these
first" shortlist - led with:

> Conflicting values for Specific Wording Requirements across documents -
> Dec Page: *If the insured's whereabouts for service of process cannot be
> determined...*, Certificate of Insurance: *If the certificate holder is an
> ADDITIONAL INSURED, the policy(ies) must have ADDITIONAL INSURED provisions
> or be endorsed...*
> **Fix:** Review and confirm the correct value.

Neither side is a requirement anyone imposed on this insured. The first is a
service-of-process policy **condition**; the second is the text **ACORD prints
on every certificate** before anyone fills it in. There was no correct value to
confirm, the card had no control to confirm it with, and it capped the SQS
at 85.

Both files below print those clauses **verbatim**.

## A - In the WARNINGS section (this is the code path that changed)

| # | Check | Expected | What it proves |
|---|---|---|---|
| A1 | Anything mentioning **Specific Wording Requirements** | **NOTHING** - not in IMPORTANT, not in Warnings | the fix |
| A2 | **Mortgagee Name** - First National Bank of Toledo vs Wells Fargo Bank NA | a card, printing **both** names | a genuine conflict on the same path still fires |
| A3 | **Certificate Holder Name** - Kestrel Terminal Authority vs Brandt Logistics Group Inc | a card, printing **both** | same, second witness |
| A4 | Anything about the **Loss Payee** | **NOTHING** | "Midwest Equipment Leasing Company" vs "...Leasing Co." is one name twice |

**A2 and A3 matter as much as A1.** A run where everything went quiet is a
**failure**, not a pass - it would mean the fix silenced the whole family.

## B - In the DATA CONSISTENCY section (a different engine - must be undisturbed)

Every top-level scalar fact is owned by the Data Consistency picker, so these
never reach the function that changed. They are here to prove nothing else
moved, and since UI-13 they render **only** in Data Consistency, not as
warnings.

| # | Check | Expected |
|---|---|---|
| B1 | **Number of employees** 47 vs 62 | a picker row - a real disagreement |
| B2 | **Carrier** - "Employers Mutual Casualty Company" vs "EMC Property & Casualty Company" | **NOTHING** - one carrier, two printings |
| B3 | **Annual revenue** `$5,000,000` vs `5000000` | **NOTHING** - formatting |
| B4 | **Policy number** `BBC7263 - 26` vs `BBC7263` | **NOTHING** - one contract, two printings |

B2 is the one to look hardest at: the first version of this fix replaced the
alias-folding gate instead of adding to it, and that pair started drawing a
card.

## Read the fact, not just the screen (30 seconds)

Check 1 can pass for the wrong reason: extraction is a model, and it may simply
not have filed either clause under the wording fact. Confirm the fact was
actually populated:

    py backend/scripts/dump_session_facts.py <session_id>

Look for `risk_transfer` -> `specific_wording_requirements`.

* **Populated on both documents, and no card on screen** - the real pass.
* **Empty or on one document only** - inconclusive. The pipeline never had two
  values to compare, so the card was never in play. Say so in the report; it is
  not a failure, and it is not a pass either.

## Report back

1. Screenshot of the whole **Warnings** section, IMPORTANT band included.
2. The **Data Consistency** section, in full.
3. The `risk_transfer` block from the fact dump.
4. The package **SQS**. It should NOT be capped at 85 by a wording item; a cap
   from the mortgagee / certificate-holder conflicts is expected and correct.

## Known, and not what this kit tests

The IMPORTANT band still ranks by TIER, and every real underwriting warning
(umbrella attachment, property COPE, auto symbols, WC payroll) sits in the
LOWER tier than any cross-document conflict. Removing this card frees the top
slot; it does not reorder the list. That is a separate, owner-level decision -
see "Still open, deliberately" in `1stSep-liveTestFixes.md`.
