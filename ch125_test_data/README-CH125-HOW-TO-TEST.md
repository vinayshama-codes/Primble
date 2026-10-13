# CH125 kit - a 300,000-character submission for ACORD 125 (plus 126 / 127)

**Upload:** `CH125_cumberland_hearth_package.pdf` - exactly **300,000 characters** of text (sum(len(page.extract_text()) for page in pdfplumber pages)), 59 pages, no scanned images.  
**Key:** `CH125_answer_key.json` (machine, all 548 + 255 + 634 boxes) and `CH125_ANSWER_KEY.md` (human: every value, its page, its trap, the UNRESOLVED list, the expected recommendations).  
**Rebuild:** `backend/.venv/bin/python ch125_test_data/generator/make_kit.py && backend/.venv/bin/python ch125_test_data/generator/write_docs.py` (deterministic).

## Run it

```bash
# 1. restart the backend; keep PURGE_DEC_INDEX_AFTER_GENERATION=0 if you want the dec index in the dump
# 2. upload CH125_cumberland_hearth_package.pdf, select ACORD 125 + 126 + 127, generate, change nothing
backend/.venv/bin/python ch125_test_data/grade_kit.py --list
backend/.venv/bin/python ch125_test_data/grade_kit.py --session <id> --label "CH125 - TEST 1" --out ch125_test_data/runs/t1.md
# the 125 alone, in the FR125 report format (extraction ENTITY-CELL + the 23-rule audit too):
backend/.venv/bin/python backend/scripts/dump_a125_run.py <id> > ch125_test_data/runs/t1_dump.json
backend/.venv/bin/python backend/scripts/report_125_run.py --key ch125_test_data/CH125_answer_key.json --dump ch125_test_data/runs/t1_dump.json --label "CH125 - TEST 1"
```

Grade from the STORED session, not the downloaded PDF (this Mac's pikepdf can render blank templates). Row order of losses, drivers and vehicles is not a defect - read the ROW-CELL table.

## What makes it hard

| technique | where | what it tests |
|---|---|---|
| Receiving carrier only through an MGA | MGA acknowledgement | the insurer is Ridgeline, not the MGA that administers it; NAIC is in 4.3 pt fine print |
| Superseded values, newest wins | Aug worksheet vs CFO e-mail 09/30 | effective date 11/15 -> 12/01; Denise's cell 0109 -> 0190; location 3 area 3,400 -> 3,100 |
| Requested vs expiring | GL supplemental, cover e-mail, auto supplemental | 126 rented premises / medical limits, per-location aggregate, PD deductible; 127 vehicle 4 collision deductible, towing added |
| Blank is not No | 125 Q7, Q9; five 126 questions; 127 fleet | never answered by the insured - and the package contains a customer's Chapter 11, a repossession BY the applicant, fraud and bankruptcy clauses in policy wording |
| A No whose block is tempting | 125 Q8, Q10, Q11, Q14 | a CORRECTED citation; a judgment WON by the applicant; a shareholder's living trust; a drone SOLD in 2025 |
| Rescinded notice | Old Hickory cancellation + rescission | question 5 is a non-renewal for underwriting - NOT non-payment |
| Answers by an X in a column | 125 supplement, ARU program application | YES / NO read from the box position |
| Drifting two-column layout | ARU program application | labels and values sit 3.6 pt off each other's baselines |
| Riffled cells, abbreviated two-line headers | premises schedule, hazards, loss runs, certificates | LOC/BLD/CNTY/CITY LMTS/INT/OCC SF/PUB SF/TOT SF/LSD TO OTH |
| Teletype letter-spacing | GL and auto declarations | P O L I C Y  N O ... |
| Form boxes, label above value | intake worksheet | values separated from their labels |
| Dates in five formats | roster YYYYMMDD, MVR YYYY-MM-DD, hire DD-Mon-YYYY, Italian dd/mm/yyyy, prose | the same date, read right |
| Amounts in $000s and words | financial statements, CFO e-mail | 15,200 (in $000s) = $15.2 million = $15,200,000 |
| OCR-garbled fax text | Old Hickory 12/31/2025 valuation | 0/O and 1/l confusion on a SUPERSEDED valuation |
| Rotated watermark | 2024 application (2 pages) | SUPERSEDED - its letters land in the text layer |
| Former name, same insured | 2022 auto claim | Cumberland Restaurant Supply, LLC = the applicant before conversion - include it |
| Another entity's claim / an old claim | JV loss run; VF&M 2020 claim | excluded: a separate LLC; older than five years |
| Latest valuation | three valuations of one auto claim | 12/31/2025, the August summary, 09/15/2026 - the last wins |
| Two location numberings | property SOV, GL schedule (insurer 001-004) vs the application (1-3) | the application's numbers |
| Counting by status | HR census: HC / P/T / F/T / TMP | full time, part time, agency temps and head count are four different numbers |
| Percent of what | CFO e-mail | 18% and 17% of TOTAL SALES; 95% of service CALLS is a decoy |
| Role confusion | certificate holders, landlord, mortgagee, lienholders, staffing firm, subcontractors | each has exactly one box - or none |
| Sold / terminated / closed | auto endorsements, HR, premises footnote | E-350 and Express sold, Ambrose terminated, Visco Dr closed |

## Counts

| form | expect | blank (no data) | blank (rule) | not scored |
|---|---|---|---|---|
| ACORD_125 | 252 | 174 | 89 | 33 |
| ACORD_126 | 141 | 54 | 49 | 11 |
| ACORD_127 | 288 | 286 | 42 | 18 |

## Decision points (graded as the client's rule; an owner call may differ)

- **126 / 127 header** (carrier, NAIC, effective date, policy number): the key follows the client's 8-19-26 rule - the policy being applied for (Ridgeline, 12/01/2026, no number). The 15 Sep 'section forms keep the current policy's identity' rule may print the incumbent; that is a decision, not a fill defect.
- **125 Vehicle / Driver schedule attachment ticks** and the 127 SYM columns: not scored.
- **Producer NPN / licence / agency codes / customer id**: not scored - they depend on the logged-in account, and Primble has no source for NPN or licence today.

## Proved before use

- every expected value is printed in the text layer (in some format); every decoy is printed;
- the key scores a perfect form 100% and an empty form with zero violations on all three forms, through `backend/scripts/score_form_fill.py`;
- the character count is measured on the written PDF, not estimated.

