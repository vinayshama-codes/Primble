# Live test kit, run 4 (30 Oct 2026): Ridgeline, a changed dec

Same insured, FEIN, policy numbers and term (12/01/2026 - 12/01/2027 renewal) as run 3, so the loss runs and
the ACORD 807 still belong to this insured. The dec content changed:

| Item | Run 3 | Run 4 |
|---|---|---|
| Annual revenue | $8,450,000 | **$9,120,000** |
| Employees FT / PT | 62 / 6 | **70 / 4** |
| Vehicles | 4 (veh 4 = 2021 Chevrolet Express 3500) | **5**: veh 4 = 2025 Ford E-Transit 350 (Cheyenne, Ford Credit lien), new veh 5 = 2024 Chevrolet Silverado 2500HD (Denver) |
| Drivers | 5 | **6** (new: Luis E Carrasco, CO, hired 01/12/2026, veh 5) |
| GL exposures | 98482 $1,240,000 / 98483 $860,000 / 91342 $385,000 | **$1,315,000 / $905,000 / $442,000** |
| WC payroll 5537 CO / 5183 | $1,240,000 / $860,000 | **$1,315,000 / $905,000** |
| Experience mod | 0.92 | **0.88** |
| Premiums GL / Auto / WC / Umb / Prop | 28,416 / 41,980 / 36,750 / 14,200 / 18,640 | **30,036 / 52,080 / 33,627 / 15,350 / 19,975** (total $151,068; every total adds up) |
| Bldg 1 roof year | 2018 | **2022** |

Files: `01_declarations_package_v4.pdf` (23 pages), `04_loss_runs_2021_2023.pdf`, `later_05_loss_runs_2024_2026.pdf`,
`807_outside_do_ridgeline_flattened.pdf` (copies from run 3). Generator: `scripts/data.py` + `scripts/make_dec.py`
(run-4 copies; run 3's generator is untouched).

Test plan: run 3's README (Package A, then Package B). Package A = `01_declarations_package_v4.pdf` + `04_loss_runs_2021_2023.pdf`.
