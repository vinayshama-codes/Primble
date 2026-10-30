# Live test kit, run 5 (30 Oct 2026): every fix of the day, three routes

Insured: **Ridgeline Mechanical Services LLC**, FEIN 84-5512309, renewal term 12/01/2026 - 12/01/2027 (same as runs 3-4, so the
loss runs, the 807 and your earlier Primble forms all belong to this insured).

## Files

| File | Route it must take | What it tests |
|---|---|---|
| `01_declarations_package_v5.pdf` (23 pages) | normal reading (OCR + AI extraction) | the bug triggers below |
| a **Primble form you download** (step 0) | Primble's own reader, from its encrypted record; **never Transcriber** | your earlier answers come back, nothing asked twice |
| `807_outside_do_ridgeline_flattened.pdf` (3 pages) | **ACORD Transcriber** (about 3 pages of credit) | outside-form route; feeds only the insured name |
| `04_loss_runs_2021_2023.pdf` (valued 01/10/2024) + `later_05_loss_runs_2024_2026.pdf` (valued 10/20/2026) | normal reading | newest valuation date wins; 6 years of runs |

## Bug triggers planted in the dec (what you should see)

| # | Planted | Expected |
|---|---|---|
| 1 | VINs of vehicles 2, 3, 4 wrap in a narrow column (16 characters) | Warning "Vehicle VIN incomplete - vehicle 2, 3, 4"; Open to fix opens the vehicle table; points shown |
| 2 | Business phone `(103) 555-0148` (an area code cannot start with 1) | Warning naming the phone; opens the field |
| 3 | Property carrier NAIC `226310` (6 digits) | Warning naming the NAIC; opens the field |
| 4 | Cheyenne location ZIP `8200` (4 digits) | Warning naming the location ZIP; opens the location table |
| 5 | "RENEWAL of policy X-24" on each line (no dates) | ACORD 125 prior grid keyed by year (2025 / 2024 / 2022); only WC policies listed for ACORD 101; never 13 policies |
| 6 | Building 1 construction "Joisted Masonry" | Printed in ACORD 140's construction box (it was refused as a "person's name" before) |
| 7 | Two loss runs, old + new valuation | Loss runs counted fresh (10/20/2026); no "upload loss runs" item for staleness |
| 8 | 5 prior claims in the loss runs | The "ACORD 101 narrative" card is NOT on the pre-form screen; it appears after forms on the forms |
| 9 | WC has no column on the 125 grid | That card is NOT on the pre-form screen; it appears after forms |
| 10 | 5 vehicles, 6 drivers, 3 buildings | No duplicates; one premises with 2 buildings is one location |

## Steps

**Step 0 - get a Primble form (2 minutes).** Open your earlier Ridgeline package `6875e80c` (it has forms), download
**ACORD 126**. That PDF carries Primble's encrypted record for your account.

**Step 1 - one upload, new package.** Upload together:
`01_declarations_package_v5.pdf`, the ACORD 126 from step 0, `807_outside_do_ridgeline_flattened.pdf`,
`04_loss_runs_2021_2023.pdf`, `later_05_loss_runs_2024_2026.pdf`. (Uploading the 807 is your go-ahead for ~3 Transcriber pages.)
Tell Claude when it starts - the log is checked for the three routes:
- `TRANSCRIBER_SUBMIT ... pages=3 ... label=807` exactly once, then `TRANSCRIBER_DONE`;
- NO `TRANSCRIBER_SUBMIT` for the 126 (Primble's own form) or anything else;
- no `INVARIANT_BROKEN`, no errors.

**Step 2 - pre-form screen.**
- Document tags: dec = Declarations, both loss runs = Loss Runs, 126 = its ACORD form (no "Different insured"), 807 = "Read by ACORD Transcriber".
- Warnings 1-4 above show, each with points and Open to fix.
- NO card that names a form or says "Add / Attach ACORD ..." (8, 9). Wording is by line ("Auto: ...").
- Answers you gave in `6875e80c` are restored (fire department, hydrant, narrative) and not asked again.
- The 807 changes nothing but the insured name; no Data Consistency card for revenue / D&O term / Kesler.
- **Every listed item shows a number (or "under 1 pt"), and the numbers add up to 100 minus the score.**
- Answer everything (VINs: `3C6LRVDG4NE118362`, `1FT8W3BT6RED20915`, `1FTBW9CK3SKA22471`; phone `(303) 555-0148`;
  NAIC `22631`; ZIP `82001`; anything else listed). After each answer: the score moves by about the shown points, the
  numbers still add up, the dashboard shows the same score. End: **exactly 100**, nothing left.

**Step 3 - form selection.** No score or to-do list here (form items live only in each form's side panel after
generation). Generate 125, 126, 127, 130, 131, 140.

**Step 4 - after forms (each form's side panel).**
- Package score stays **100**.
- Each form lists only its own items; cards 8 and 9 now appear (on ACORD 101 / 125) with their fix.
- ACORD 140: construction prints "Joisted Masonry". Its holds (if any) are its own boxes.
- Fix one form's items: only that form's score moves, up to 100. A GL item never holds ACORD 127.
- Cross-Form panel shows only checks that name the open form.
- Download screen numbers match the side panel.

**Step 5 - optional: another insured.** In the same package, after forms, Add documents
`orbin_retest_kit/1_policy_package.pdf` -> "Different insured" -> "Add as evidence only". Nothing of Orbin's reaches
Ridgeline's forms or score.
