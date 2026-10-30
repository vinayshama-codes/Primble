# Live test kit, run 3 (29 Oct 2026): Ridgeline + an outside ACORD 807

Same fictional insured as the main kit: **Ridgeline Mechanical Services LLC**, FEIN 84-5512309, 4150 S Kalamath St, Denver CO 80223. The dec's renewal term is **12/01/2026 - 12/01/2027**.

The new piece in this run is an **ACORD 807 (Directors & Officers Liability Section, 2016/03)**. An outside agency (Bluestem Risk Advisors LLC) filled it, then it was flattened. Primble has no 807 template, so the Transcriber has to read this form.

## Files

| File | Pages | What it is | Goes to ASG Transcriber? |
|---|---|---|---|
| `01_declarations_package.pdf` | 23 | Same dec package as the main kit (GL, Auto, WC, Umbrella, Property). Unchanged copy. | No |
| `04_loss_runs_2021_2023.pdf` | 5 | Loss runs for terms 12/2020 - 12/2023, valued 01/10/2024 (3 years only). Unchanged copy. | No |
| `later_05_loss_runs_2024_2026.pdf` | 5 | Loss runs for terms 12/2023 - 12/2026, valued 10/20/2026. Unchanged copy. | No |
| `807_outside_do_ridgeline_flattened.pdf` | 3 | ASG's sample ACORD 807. Every field was cleared and refilled for Ridgeline. It was then flattened: no form fields, no AcroForm, no `/PrimbleRecord`, and ASG's "Sample" watermark removed. Each page prints "ACORD 807 (2016/03)" and "Page n of 3". Page 1 also prints "ACORD CORPORATION". | **Yes, 3 pages** |
| `scripts/make_807.py` | - | The generator: `backend/.venv/bin/python -I test_kit_29oct/run3/scripts/make_807.py "<Sample-ACORD 807 (2016-03) Filled.pdf>" <out.pdf>` | - |

**Expected Transcriber cost: 3 pages**, only once (on the first upload of the 807). The dec, the loss runs and the Primble forms from Package A are never sent.

### What the 807 says (all sections filled)

- **Header:**
  - Agency Bluestem Risk Advisors LLC, customer ID RIDG-0412, completed 10/27/2026.
  - Carrier Larkspur Specialty Insurance Company, NAIC 38145, policy DOL-2290417-25.
  - First named insured Ridgeline Mechanical Services LLC.
  - Requested 01/15/2027 - 01/15/2028.
- **Coverages:** all primary.

  | Coverage | Requested limit | Current limit | Retention requested / current |
  |---|---|---|---|
  | A D&O | $2M / $2M | $1M / $1M | $0 / $0 |
  | B Company reimbursement | $2M / $2M | $1M / $1M | $25k / $25k |
  | C Entity | $2M / $2M | $1M / $1M | $35k / $25k |
  | Employment Practices | $1M / $1M | $500k / $500k | $15k / $15k |
  | Fiduciary Liability | $500k / $500k | $500k / $500k | $0 / $0 |

  - Separate defense costs limit: Y, $250,000, outside.
  - Pending and prior litigation date: 12/01/2019.
  - Shared limits N; additional coverages attached Y.
  - Sections included: EPLI, Fiduciary, Other "Cyber Liability Supplement".
- **Endorsements:**
  - Worldwide coverage (LSI-DO 104).
  - ODL for profit (LSI-DO 118).
  - BI/PD exclusion amendatory (LSI-DO 212).
  - Colorado Changes (LSI-DO 900 CO).
- **Financials:** prepared 03/31/2026; outside auditor Y; auditor changed N; going concern N.

  | Year | Total revenue | Total assets | Net income |
  |---|---|---|---|
  | FY2025 (current) | **$8,975,000** | $6,420,000 | $612,000 |
  | FY2024 (prior) | $7,910,000 | $5,880,000 | $498,000 |

  - Not for profit: fund balances blank, tax exempt N.
- **Ownership:**
  - Owners: 2, 1,000 voting units, all held by directors.
  - Directors / officers: **Laura Kesler** (Member / CFO, affiliation Colorado Mechanical Contractors Association) and Gregory Hale (Managing Member).
  - Other proposed insureds: Marcus J. Delgado (Field Operations Manager) and Dana L. Ruiz (Controller).
  - Subsidiary: **Ridgeline Mechanical Wyoming LLC** (Cheyenne branch, 04/01/2023, 100%).
  - Shareholders: Laura Kesler 50% (board Y), Gregory Hale 50% (board Y). "5% holders on board" Y. Parent blank.
- **General information:** 12 Y/N codes in 11 numbered questions (Q7 holds two codes and shares one explanation box). Every question has a short explanation.
  - Two are **Y**: Q2, a management change (Controller hired 02/2024), and Q3, Ridgeline Mechanical Wyoming LLC formed 04/01/2023.
  - All the others are N.
- **Attachments / remarks:** schedule of shareholders, Other "FY2025 CPA financials". Remarks: "D&O / EPL / Fiduciary marketed with the 12/2026 package renewal ... Increase to $2M requested by the members."
- **Signature:** Gregory Hale, Managing Member, 10/27/2026. Producer Jordan Pike, CO licence 0461275, NPN 18834502.

## Planted inconsistencies (807 vs the dec package)

**Expected result (corrected 30 Oct after the expert review): none of these three becomes a Data Consistency card.** The 807 is a D&O application. Its term is the D&O term, not the package term. Its financial-statement revenue and its officer list sit in boxes none of our 17 forms prints. So all three show only under "View values read from the form". If any one shows up as a card, or replaces a package value, that is a bug.

| # | Fact | Declarations (01) | ACORD 807 | Where on the 807 |
|---|---|---|---|---|
| 1 | Total / annual revenue | **$8,450,000** (Insured Information page, "Annual Gross Revenue") | **$8,975,000** (Financial Statement, current year FY2025 Total Revenue) | page 1 |
| 2 | Proposed term | renewal **12/01/2026 - 12/01/2027** | requested **01/15/2027 - 01/15/2028** | page 1 header |
| 3 | Officer / member name | **Laura Kessler** (Member, 50%; also the primary contact, CFO) | **Laura Kesler** (one "s"), in the director/officer list and the shareholder list | page 2 |
| - | Named insured (control, NOT a conflict) | Ridgeline Mechanical Services LLC | Ridgeline Mechanical Services LLC (exactly the same, so one insured) | page 1 |

**Not conflicts, but worth watching:**
- Producer: dec = Peak & Prairie, 807 = Bluestem. The login outranks both.
- Ridgeline Mechanical Wyoming LLC appears only on the 807, as a subsidiary. It must NOT become a second named insured or raise "Different insured" / "Possible multiple submissions".
- FY2024 revenue of $7,910,000 is a prior-year figure. It must not be compared with the dec's revenue.
- The D&O carrier, policy and limits are a line the dec does not carry. They must not overwrite any GL / Umbrella limit or carrier.

## Live test plan (do these in order)

### Package A: build the real Primble forms

1. Start a new package. Upload **01 + 04** together.
2. **Loss History:** check that it asks for more years. 04 covers only 12/2020 - 12/2023, and the business is 15 years old, so it needs 5 years.
3. **Answer everything on the pre-form screen until the score is exactly 100.** At every step:
   - every listed item shows a number;
   - the shown points add up to 100 minus the current score.

   Write down the answers you give, because Package B must not ask them again. Leave the Loss History years open. Package B closes them with later_05.
4. Generate **ACORD 125, 126, 127, 140**.
5. Download all four. These are real Primble forms, and each one carries the encrypted Primble record. Keep them for Package B.

### Package B: new package, same account

1. Start a **new** package. Upload **01 + the four Primble forms downloaded in A + `807_outside_do_ridgeline_flattened.pdf` + 04** in one upload.
2. Expected on upload:
   - **The 807 goes to Transcriber.** In the backend log, look for `TRANSCRIBER_SUBMIT env=... pages=3 ... label=807` and then `TRANSCRIBER_DONE ... status=... forms=...`. There must be exactly one submit, 3 pages.
   - **The Primble forms are read in-house and never sent.** There is no `TRANSCRIBER_SUBMIT` for them.
   - The dec and the loss run are read normally.
   - Document tags:
     - the 807 shows **"Read by ACORD Transcriber"**;
     - the four Primble forms are typed as their ACORD forms, with no "Different insured";
     - 01 is Declarations and 04 is Loss Runs.
3. Expected on the pre-form screen:
   - **The answers from A are restored. Nothing you answered in A is asked again.** A warning that A already solved must not come back.
   - **Only NEW item: Loss History years, still short.** The three planted 807 differences (revenue, D&O term, Kesler) must NOT appear as Data Consistency cards, and must not change the package's revenue, term or officers.
   - The 807 feeds only the insured name (please verify). The producer stays the login's. The D&O carrier, limits, financials, officers and the Wyoming subsidiary feed nothing. The subsidiary must not become a second named insured, and "Gregory Hale" must not become an additional named insured.
   - The rest are listed under **"View values read from the form"**. They must not be labelled as AI fills or as document-verified facts.
4. Add **`later_05_loss_runs_2024_2026.pdf`** with Add documents. Loss History is then complete: the "more years" ask clears, and the claims from both runs are listed.
5. Answer the rest, and pick a value on each Data Consistency card. The score reaches **exactly 100**, and the points add up at each step.
6. Generate the forms. Check that:
   - the side-panel numbers and the download-screen numbers match;
   - each set adds up to 100 minus the score (0 left at 100);
   - the download screen lists the hard stops, warnings and cross-form checks still open, with the same points as the side panel (key details and score rows stay in the side panel, so the download screen alone does not add up to 100 minus the score).

### What to look for in the log

| Log line | Expected |
|---|---|
| `TRANSCRIBER_PRESUBMIT files=N sent=1` | Only the 807 is sent early |
| `TRANSCRIBER_SUBMIT ... pages=3 ... label=807` | Exactly one, 3 pages |
| `TRANSCRIBER_DONE ... forms=...` | The 807 is returned |
| `TRANSCRIBER_CACHE_HIT` | Only if the same 807 is uploaded again; no new pages are billed |
| `TRANSCRIBER_FALLBACK` / `TRANSCRIBER_SKIP` | Must NOT appear. If one does, the 807 went to the "Needs Verification" path. Note the `kind=` / `reason=` |
| Any `TRANSCRIBER_SUBMIT` for a 125 / 126 / 127 / 140 | Must NOT appear: the Primble forms are in-house reads |

**Page cost: 3 Transcriber pages for the whole run**, all from the 807.
