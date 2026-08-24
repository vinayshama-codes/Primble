# Run A and Run B - what to upload and what each result means

Supersedes the upload instructions in `README-HOW-TO-TEST.md` (its 10 checks are
still correct except **check 8** - see the correction below).

Two **separate submissions**. Do not mix them, and do not upload either one in
bunches - every clause in client section 1 is a cross-document question, so a
split upload makes checks pass for the wrong reason.

---

## RUN A - "nothing false fires"

Upload **1, 2, 3, 4, 5** together. Generate ACORD **125, 126, 127, 131**.

This is the existing 10-check list. Two corrections before you score it:

### Correction to check 8
`5_complex_tables.pdf` carries a genuine **second** location -
`002  1220 W Colfax Ave, Aurora, CO 80011`. The correct answer on ACORD 125 is
now **TWO** location rows, not one:

- LOC 1 - `4800 Dahlia St D13` / Denver / CO / 80216
- LOC 2 - `1220 W Colfax Ave` / Aurora / CO / 80011

Three rows for the Denver address alone is still a FAIL. Two rows for two real
premises is a PASS.

### Two rows in Run A are FIXTURE bugs, not product bugs
Ignore these when scoring - files 1 and 5 are dec pages for the same package and
should agree, but they do not:

| Row you will see | Cause |
|---|---|
| Umbrella **Self-Insured Retention** `$0` vs `$10,000` | file 1 says `$0`, file 5 says `$10,000` |
| **Producer** `Summit Commercial Insurance` vs `Commercial Risk Solutions, Inc.` | files 2/3 vs file 5 |

Both are curated or auto-discovered reconcilable fields, so both **will** open a
conflict row. The engine is right; the fixture is wrong. Say the word and I will
fix the generator.

### Not a defect - leave it alone
File 5 marks Workers Comp `NO COVERAGE` in its premium summary while its own
umbrella underlying schedule lists `Employers Liability - Pinnacol Assurance -
$500,000` (which canonicalises to `workers_comp`). That is one document
contradicting itself, and the denial logic is deliberately cross-document only.
It should produce **nothing**.

---

## RUN B - "real problems do fire"

Upload **1, 2, 3, 4, 5 AND 6_conflicting_dec.pdf** as a **new submission**.

`6_conflicting_dec.pdf` is a second declarations page from a rival carrier. Every
row below is planted and **must** appear. **A quiet Run B means the checks are
dead, not passing** - that is the whole point of this run.

### Must FIRE - score each PASS / FAIL

| # | Planted | Where to look | What must appear |
|---|---|---|---|
| B1 | **Address** `2255 S Wadsworth Blvd Ste 410, Lakewood, CO 80227` vs the Denver address | Data Consistency | A conflict row. Reason should read *"the documents point to materially different locations"* |
| B2 | **DBA** `Orbin Electrical Services` vs `Orbin Roofing` | Data Consistency / warnings | A row or a warning. Must **not** be a hard stop |
| B3 | **Employees** `47` vs `18` | Data Consistency | A conflict row |
| B4 | **Two GL carriers, same line, same period** - `Travelers Property Casualty Company of America` (`GL-4471102-26`) against `EMC Property & Casualty Company` (`BBC7263-26`) | Data Consistency | **THE IMPORTANT ONE.** A conflict row whose reason reads *"two policies on the same coverage line in one submission - confirm which applies"*. If this comes back **scoped** or silent, that is the C1-H regression and stop the run |
| B5 | **GL limits** `$2,000,000` / `$4,000,000` vs `$1,000,000` / `$2,000,000` | Data Consistency | Conflict row(s) on each occurrence and aggregate |
| B6 | **Commercial Property GRANTED** here (carrier, policy number, `$3,880` premium, `$1,450,000` building limit) while files 1 and 5 both print `NO COVERAGE` | Warnings / coverage issues | A lines-of-business conflict. This is the only test of client 1.7's *"materially disagree about whether coverage exists"* in the fire direction |

### Must STAY QUIET - the in-run control

File 6 repeats Auto and Umbrella **identical** to file 1 on purpose. If a second
dec page simply floods the screen, these light up too and the detection is not
targeted.

| # | Must stay silent |
|---|---|
| B7 | No conflict on **Auto** carrier or policy number (`6E7-40-02---26`) |
| B8 | No conflict on **Umbrella** carrier or policy number (`6J7-40-02---26`) |
| B9 | Umbrella limit still shows the `$3,000,000` vs `$1,000,000` conflict from Run A - and only that one |
| B10 | Loss run still matches the insured (Run A check 7 must not regress) |

---

## What to send back

1. Run A - the 10 results, with check 8 scored against the corrected expectation.
2. Run B - B1 to B10, PASS / FAIL / NOT SURE.
3. A screenshot of the **Data Consistency** section expanded, for each run.
4. Exact on-screen wording where something fails - copied, not summarised.
5. **The audit export** after generation, if you can get it. It is the only
   surface that renders `value_state` / `evidence_state`, so it is the only way
   to judge client clauses 1.3 and 1.4 from a run.

Backend logs worth grepping in both runs:

```
scope                 - values retained under their own policy or item
withhold active       - a value was held back from a form
UNKNOWN_KEYS          - the model invented field names
held for producer     - a client answer was held
composite MISMATCH    - a scalar disagrees with its own composite
```
