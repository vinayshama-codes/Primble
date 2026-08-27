# Client section 6 (V1 H1) - live test kit, five packages - ROUND 2

Generated 2026-08-27. **Regenerate before every run**
(`py backend/scripts/make_c6_test_pdfs.py`). Extraction is now v16, so every
upload re-extracts under the stricter rule - do not reuse round-1 sessions.

## What round 1 proved (do NOT redo)

| Package | Passed on the first run |
|---|---|
| P1 | Auto Completeness -25, WC Supplemental -10, Operations -15, Property 0, the COPE hard stop naming "building or BPP value", the typed deductible-basis card, the agreed-value card shown once, both schedule cards, the EDIT PATH (nothing moved), answering the mod card |
| P2 | Auto 0, WC 0, Property 100, Umbrella 100, no physical-address warning, mod 0.92 printed on the 130 |
| P3 | Auto 0, WC 0, no schedule warnings, HNOA questions asked, vehicle / driver tables marked Not applicable, no X-Mod card |
| P5 | the split-limit hard stop, ceiling 60 with the reason, WC Supplemental -5, the physical-address warning |

## What round 1 found, and what changed

| Seen | Cause | Fix |
|---|---|---|
| P2 and P4: Operations 85 on clean accounts | each printed its governing class (4299 printing / 2003 bakeries - neither in the lookup table) beside clerical 8810, which IS in it, so only the standard exception voted and the account read "office" | a standard-exception class (8810 / 8742 / 8871 / 7380) does not vote **when a real class sits beside it**. A LONE 8810 still does - on a roofing contractor that is the mismatch you asked for |
| P1: Umbrella 40, not 25 | the sentence "schedule of underlying insurance was not supplied" was stored AS the schedule | a negation is an absence (Principle 3) |
| P5: Coverage Info -10 "no liability limit" and a CSL card | split limits leave the CSL box empty by design | split parts = the limit is stated |
| P5: Auto Completeness -10, not -15 | extraction inferred a use / radius / garaging the document never printed | rule 2c now forbids inference; v16 |
| P3: comp / collision deductible, physical-damage valuation and return-to-yard cards on an account with no vehicles | not in the HNOA-only N/A set | added |
| P1: vehicles and drivers asked twice (table + free text) | the coverage-guarantee injector did not know they are tables | schedule-backed facts are tables only |
| P1 could not show the payroll-period -3 | a class-code schedule with amounts satisfies the period (D43) once the extractor attributes the total to the rows | the period gap moved to P4, which prints codes without amounts |

## What to run now - three uploads, two of them short

* Every package is ONE PDF and its OWN session.
* Open **Total Package Score > Exposure Consistency**; hover a row for the arithmetic.
* "Facts panel" = the extracted-facts view; when a row disagrees, copy the fact named.

### R1 - `P2_everything_complete.pdf`   (re-run: the 8810 fix)
**Generate: 125 + 127 + 130** - three, not six. Property Integrity and Umbrella
Adequacy are PACKAGE pillars computed from the facts, so they read 100 whether or
not you generate the 140 and the 131; the 127 and the 130 are here only because
you are reading a box printed on them.

**Expect:** Exposure > **Operations 100** (was 85). Everything else exactly as
round 1: Auto Completeness 0, WC Supplemental 0, Property 100, Umbrella 100,
no physical-address warning.
**Agency bucket, corrected expectation:** cards such as "Experience mod" and
"Officer inclusions / exclusions" DO appear on this package - they are
"confirm this suggested value" cards (master plan 4.1 step 3: a producer
decision the documents state but no human has confirmed), not "missing"
cards. That is by design. What must NOT appear is a **WC payroll period**
card.
**Send back:** the Exposure pillar. Optionally page 1 of the 127 - RADIUS 50 on
rows A and B, and **exactly one** USE box ticked (Retail) on rows A and B, none on
row C. If you see two USE boxes ticked on any row, send that page: the seven boxes
are mutually exclusive and one is the only correct answer.

### R2 - `P4_new_venture.pdf`   (the steps you did not get to, plus the period gap)
**Generate:** 125 + 130

The bakery prints a bare "Payroll: $210,000" with no period wording, class
codes without amounts, and no mod anywhere.

**On upload**
- Exposure > **Operations 100** (round 1 read 85 - the 8810 fix).
- **WC Supplemental deducted 3** - the payroll period only (hover). The mod is
  UNKNOWN: asked, never deducted.
- Agency: an X-Mod card and a **WC payroll period / basis** card. (Round 1
  also showed a second EMOD question under "Experience mod detail" - both go
  away in step 2.)
- Loss History shows the **"confirm New Venture status"** card.

**Step 2 - confirm New Venture** on the Loss History card (answer Yes).
- Loss History becomes **Not Applicable**.
- **Both X-Mod cards disappear** from the Agency bucket. WC Supplemental stays
  at 3 until step 3.

**Step 3 - answer the period card:** pick *Annual*. -> WC Supplemental **0**.

**Step 4 - a re-run must keep the confirmation.** In the documents panel
change this document's type to any other type, then back.
- Loss History **still Not Applicable**, the X-Mod cards **still gone**.

**Send back:** the Exposure pillar on upload and after step 3; the Agency
bucket and Loss History state after each of steps 2 and 4.

### R3 - `P5_split_limits_partial_fleet_mod_indicated.pdf`   (the split-limit fix + your step 2)
**Generate:** 125 + 127 + 130

**On upload**
- Hard stop **"Split liability limits incomplete"**, ceiling 60 - as before.
- Exposure > **Coverage Info 100** (round 1 read 90: "no liability limit" on a
  split-limit policy).
- Exposure > **Auto Completeness 85** = 5 garaging + 5 radius + 5 use (round 1
  read 90). If it still reads 90, send the facts panel values of
  `auto_vehicle_use`, `auto_radius_of_operation`, `auto_garaging_addresses` -
  one of them was filled from text that does not print it.
- WC Supplemental 95 and the physical-address warning - as before.
- Agency: **no** "Auto liability limit - CSL" card (split limits are the limit).

**Step 2.** Open the split-limit hard stop: its Open-to-fix must show **three
typed fields** with BI per person and BI per accident pre-filled. Type
**$100,000** into PD per accident, save.
- The hard stop clears; the ceiling lifts to 85 (the address warning remains).

**Send back:** the Exposure pillar; the hard-stop card open before step 2;
the score before and after step 2.

### Optional - `P1_everything_missing.pdf`   (only if you want the umbrella row re-checked)
**Generate: 125 only** - the umbrella pillar is package-level. Expect **Umbrella 25** (round
1 read 40 because "was not supplied" counted as a schedule). Nothing else
changed for P1 and nothing else needs re-checking. P3 needs no re-run.

## What to send back overall

R1's Exposure pillar; R2's four captures; R3's three captures. One table,
PASS / DIFFERS per line. One failing line with its facts beats the rest
passing.
