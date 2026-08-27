# Client section 8 (V1 H3) - live test kit, three packages

Generated 2026-08-27. **Regenerate before every run**
(`py backend/scripts/make_h3_test_pdfs.py`). Extraction moved to **v17**, so every
upload re-extracts - do not reuse an older session for these checks.

Three uploads, three separate sessions. Each is ONE PDF. Generate **ACORD 125 + 130**
on all three - nothing here is read off any other form.

---

## ROUND 2 - what round 1 proved, and the 7 fixes to re-check

**The PDFs are unchanged.** Round 1 passed everything on the FORM (rows, counts, states,
the derived payroll-by-state, the hard stop, the 8.3 boundary) and found seven defects.
All seven are fixed; re-upload the same three files and check only the lines marked
**[R2]** below, plus everything in "What round 1 already proved".

### What round 1 already proved - do NOT redo
3 rows not 6 · code `8810` not `8810 Clerical` · FT 2/3/8 with the headcount 15 never
leaking · W1 Part 1 = CO only · W2 Part 1 = CO TX · W2 rating sheet state BLANK · the
$800,000 in W2's hard stop was DERIVED (never printed in the document) · W3 zero class
codes anywhere · W3 WC Supplemental 97% (the -3 still fires).

### The 7 fixes - what to look for now

| # | Round 1 showed | [R2] expect now |
|---|---|---|
| 1 | Neither WC table appeared in the questionnaire | **The employee-group table in the CLIENT list** and **Owners and officers in AGENCY**. Root cause: the auto-generated wording began "Please provide your ", the exact marker that routes a question out of the workflow |
| 2 | Client asked *"Provide your WC payroll breakdown by class code … (For example: 5183 Plumbing - $320,000)"* | **That question is gone from the client list.** It was a narrative slot repurposed into a classification question - principle 5 breached. The "Subcontracted %" question also no longer says "class code" |
| 3 | W1 grew a 3rd "officer" doing *Roofing installation* for *$520,000*; **W2 printed 3 officers on a package with none**, carrying $90,000 / $410,000 / $300,000; W3 showed $640,000 as an officer's pay | **The officer block carries only real officers.** W2's is empty. W1 shows exactly Dana Whitfield and Marcus Ruiz |
| 4 | PART 3 OTHER STATES repeated Part 1 (W2 "CO TX", W3 "CO" with Part 1 blank) | **PART 3 is blank** on all three |
| 5 | INCREASED LIMITS = `1,000,000` (the EL limit as a multiplier); ASSIGNED RISK SURCHARGE = the mod | **Only EXPERIENCE OR MERIT MODIFICATION carries a factor** (0.92 / 1.05). Every other factor row blank |
| 6 | W2's premium block said `STATE: CO` while the sheet above it correctly refused | **W2's premium STATE is blank too**; W1 still says CO |
| 7 | *"Policy Effective Date: documents disagree (09/17/2026, 07/13/2026)"* - a false conflict + an 85 cap on W1 AND W2 | **No Data Consistency card, no date warning.** 07/13 was the X-Mod's effective date being read as the policy's. W1 and W2 should now cap at 85 only if something else earns it |

**Score movement to expect:** W1 and W2 lose the false-conflict warning, so their SQS may
rise. W2 keeps its 60 cap - the payroll hard stop is real and is the point of that package.

---

| Package | Proves |
|---|---|
| W1 | 8.1 the whole employee-group table on the 130; 8.2 officers INC/EXC, X-Mod, subcontracting; payroll-by-state derived and AGREEING (the new hard stop must stay silent); 8.3 a compound "8810 Clerical" cell split; a duplicated rating row folded |
| W2 | two states on the form; the 10% state-total hard stop - a spec rule that has NEVER run on live data |
| W3 | 8.3 the boundary: no class table -> every code box BLANK, the table still ASKED, a producer-typed code stamps; the payroll-period -3 still fires |

Where things live: the **pre-form screen** is what you see right after upload (score,
hard stops, warnings). The **question buckets** (Client / Agency) and the **schedules
panel** appear after you generate forms, because both are built from the generated forms.

---

## Upload 1 - `W1_groups_complete_single_state.pdf`

A Colorado roofing contractor. Three employee groups, exactly the client's own 8.1
example: Clerical 2 / $100,000, Outside sales 3 / $180,000, Roofing installation 8 /
$520,000. Total payroll $800,000. Two officers, one included one excluded. Mod 0.92.

### A. Pre-form screen

1. **No WC hard stop.** The groups sum to $800,000 and the application states
   $800,000, so the new state-total rule must stay SILENT. This is the guard rail -
   a rule that fires on the ordinary case is the failure mode this codebase has hit
   four times.
2. Open **Total Package Score > Exposure Consistency**. **WC Supplemental = 100**
   (X-Mod stated, officers resolved, payroll annual) and **Operations = 100** (5551
   roofing matches the operations; 8810 and 8742 are standard exceptions and must
   not vote).

### B. Generate ACORD 125 + 130, then read the 130

3. **The classification section** (CLASS CODE / DESCRIPTION / # FULL-TIME /
   # PART-TIME / ANNUAL REMUNERATION / RATE) - three rows:

   | Code | Description | FT | PT | Remuneration |
   |---|---|---|---|---|
   | 8810 | Clerical - office and administrative | 2 | 0 | $100,000 |
   | 8742 | Outside sales | 3 | 0 | $180,000 |
   | 5551 | Roofing installation | 8 | 2 | $520,000 |

   * **THREE rows, not six.** The same rows are printed twice in the document (a
     premium summary and the rating sheet); they must fold into one set.
   * **Row 1's code box must read `8810`, not `8810 Clerical`.** The premium
     summary prints that cell combined and 8.3's normalizer splits it. Either
     wording may win the description box ("Clerical" or "Clerical - office and
     administrative") - whichever printing the extractor read first. Both are
     correct; only the CODE box is being tested here.
   * **No count box may read 15.** 15 is the company-wide headcount; the group
     counts are 2 / 3 / 8. A 15 anywhere in those columns is the old bug.
4. **The state boxes.** The "Part 1" states box reads **CO** and nothing else -
   three Colorado groups are ONE state, not three. The rating sheet's state name
   reads **Colorado**.
5. **The officers section** - Dana Whitfield / President / 60% / **INC**, and
   Marcus Ruiz / Vice President / 40% / **EXC**. Both rows carry state **CO**.

### C. The question buckets and the schedules panel

6. **Client bucket:** ONE question, *"Please provide your employee groups and
   payroll"*, rendered as a table pre-loaded with the three rows. It must show
   the columns *Employee group and what they do / Full-time / Part-time / Annual
   payroll / State* - and **NO "WC class code" column**. The class code is the
   producer's (core principle 5).
7. **What must NOT be in the client list:** *"What types of work do your employees
   perform?"*, *"Please provide your payroll broken out by state and job
   classification"*, or any *"owners or officers"* question. All three are now
   answered by a table or by the producer.
8. **Agency bucket / schedules panel:** an **Owners and officers** table with the
   two rows and the words Included / Excluded. This table must never appear in the
   client's copy - if you open the client questionnaire link, it is not there.

**Send back:** the Exposure pillar, the 130's classification + officers sections,
and a screenshot of the client bucket showing the table without a code column.

---

## Upload 2 - `W2_two_states_total_mismatch.pdf`

A plumbing contractor with Colorado and Texas payroll. The three groups sum to
$800,000; the application states a total annual payroll of **$1,150,000**.

### A. Pre-form screen

1. **A HARD STOP you have never seen before:** *"WC payroll by state totals
   $800,000 but ACORD 125 reports total payroll of $1,150,000 - 30% variance.
   Reconcile payroll totals."* The package score is capped at **60**.
   This rule has been in the code since it shipped and has never once run - it read
   a list while the data was always a dict (H3-B). **D6: this can lower the score on
   real multi-state accounts. Brent should hear it from you first.**
2. You may ALSO see *"WC payroll differs from total payroll ..."*. That is the
   pre-existing 20% rule, not the one being tested; ignore it for this check.
3. Resolve on the state-total card asks you to type the total payroll. That is
   existing behaviour and is correct - the disagreement may be in the 125 figure.

### B. Generate ACORD 125 + 130, then read the 130

4. **The Part 1 states box lists CO and TX** - the two distinct states, in row
   order, not "CO, CO, TX".
5. **The rating sheet's state name is BLANK.** The form prints one rating sheet
   and this account has two states, so no single state may be claimed. Blank and
   owned - not a guess, and not something the AI is asked to fill.
6. Three classification rows, with the full-time counts 2 / 6 / 4 and their own
   states.

**Send back:** the hard-stop card, the ceiling reason, and the 130's states box.

---

## Upload 3 - `W3_no_class_table.pdf`

A residential roofing contractor with WC coverage and **no classification schedule
anywhere**. The operations text says "residential roofing" - which is exactly the
temptation: NCCI 5551 is the obvious code, and Primble must not write it.

### A. Pre-form screen

1. **WC Supplemental shows -3** for the payroll period: the document prints a bare
   *"Payroll: $640,000"* with no period word. This is H1's rule still working after
   the H3 change (regression check).
2. X-Mod and officers are **UNKNOWN**, not missing - neither deducts. They reach the
   producer, never the client.

### B. Generate ACORD 125 + 130, then read the 130

3. **EVERY code box on the form is blank** - the classification section's code
   column, the carrier description-code column, and the class-code column in the
   officers section. This is client 8.3: Primble may extract, retain, normalize and
   compare a class code, but never generate one. **A 5551 anywhere on this form is
   a failure of the whole section.**

### C. The question buckets - and the producer step

4. **The employee-group table is still ASKED**, empty, in the client bucket. A blank
   form box must never mean "nobody is asked" - that is the defect the table exists
   to fix.
5. **The producer step (8.3 "retain producer-entered codes"):** open the schedules
   panel, type one row into **Employee groups and payroll** - description
   `Roofing installation`, full-time `9`, annual payroll `$640,000`, state `CO`, and
   in the producer-only code column `5551 Roofing`. Save.
6. Re-open the 130. The row must now print **code `5551`** and **description
   `Roofing installation`** (the compound cell split again), remuneration `$640,000`,
   full-time `9`, the Part 1 state `CO`, and the rating sheet state `Colorado`.
7. The payroll-period **-3 is now gone**: a typed annual-payroll column is annual by
   construction. The score goes UP by 3 - that is correct, not a bug.

**Send back:** the blank 130 (step 3), then the same section after the producer row
(step 6), and the WC Supplemental row before and after.

---

## What counts as a failure

* Any WC class code on a form that no document printed and no producer typed (W3).
* A group's employee count showing the company-wide headcount (W1, 15).
* Six classification rows where three were printed twice (W1).
* The client being shown a WC class code column, or the officers table (W1).
* The state-total hard stop firing on W1, where the numbers agree.
* A state name on W2's rating sheet, where two states share one form.
* The employee-group table missing from W3's question list.

## Known and expected - do not report these

* `WorkersCompensation_RateState_StateOrProvinceName_A1` (the page-2 copy of the
  sheet's state label) is still filled by the AI. Same value, different box.
* **The RATE column does not print on the 130.** ACORD marks that box read-only
  (a rate is the carrier's to compute), so it ships blank by design. An extracted
  or producer-typed rate is still retained in the data and still shows in the
  producer's table - it is preserved, not discarded.
* Officer rows print only name / title / ownership % / state / INC-EXC. Birth date,
  duties and remuneration for officers are not captured by any table yet.
* W2 may show two payroll hard stops (check 2 above).
