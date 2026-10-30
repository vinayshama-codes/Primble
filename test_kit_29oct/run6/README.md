# Live test kit, run 6 (30 Oct 2026, primble.ai): three routes, reach 100, after forms, download screen

Insured: **Ridgeline Mechanical Services LLC** (same as runs 3-5). The two outside ACORD files are NEW bytes, so
Transcriber cannot answer them from its cache (about 8 pages of credit in total).

| File | Route | Transcriber pages |
|---|---|---|
| `01_declarations_package_v5.pdf` | Primble's own extraction | 0 |
| `04_loss_runs_2021_2023.pdf`, `later_05_loss_runs_2024_2026.pdf` | Primble's own extraction | 0 |
| a Primble form you download (step 0) | Primble's encrypted record, never Transcriber | 0 |
| `outside_acord_125_ridgeline_flattened.pdf` (5 pages, another agency's 125) | Transcriber (a copy of one of our 17 forms) | 5 |
| `807_outside_do_ridgeline_v6_flattened.pdf` (3 pages, D&O) | Transcriber (a form outside our 17) | 3 |

The outside 125 plants differences from the dec on purpose (suite 210 vs 200, start date, phone, revenue $9.2M,
FT / PT 58 / 4, NAICS 238210, term 01/01/2027, building 2 area 25,000, one auto claim paid, VIN 2 last digit, a
driver DOB). Expect Data Consistency picks for these. The 807 feeds only the insured name.

Scripts: `scripts/make_807.py` (ASG's sample 807, completion date 10/30/2026), `scripts/make_125.py` (the run-1
generator, 125 only, run-5 data).
