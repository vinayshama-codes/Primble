# Policy number by line - live test kit (3 files, 2 uploads)

Built 17 Sep 2026 for the client's question: *"a single policy number is still
trying to be represented across all - was this corrected?"*

| Upload | Files (together) | Insured |
|---|---|---|
| **1** | `1_renewal_package_policy.pdf` + `2_certificate_project_gl.pdf` | BRAMBLE & STONE CONSTRUCTION LLC |
| **2** | `3_renewal_summary_one_number.pdf` alone, in a SECOND new session | CINDERHOLT LANDSCAPE GROUP INC |

## 0. RETEST AFTER THE 17 SEP FIXES - START HERE

The first live run (17 Sep) came back as 7 blank PDFs (pikepdf, fixed) and, read
from the stored session data: upload 1 passed on policy numbers but blanked
General Liability everywhere and printed the umbrella's PRIOR carrier as its
current one; upload 2 printed `SRC-4410982` on every line. All fixed; every value
below is measured by replaying that run's own extraction through the fixed code
(`backend/tests/test_policy_by_line_live_kit_17sep.py`).

**Restart the backend first** (`uvicorn --reload` picks the files up, but restart
to be sure), then run the same short run: upload 1 -> ACORD **125, 126, 131, 25**;
upload 2 -> ACORD **126, 131, 25**.

**Retest 1 (17 Sep, pre-form review):** upload 1 matched R2-R4. Upload 2's session
was merged with a gap - the extraction numbered at most one row, and the per-line
fill copied `SRC-4410982` onto Commercial Auto and Umbrella after the withhold ran.
Fixed (the withhold now reads the rows AND the per-line index). **Upload 2 must be
uploaded again in a NEW session** - a session's facts are merged at upload, and
generating forms on the old session reuses them. Any of the three General
Liability cards (policy number, carrier or NAIC) now chooses the same policy.
The Inland Marine Total Value card and the Builders Risk warning depend on the
extraction and may or may not appear on a given upload.

### Upload 1 - pre-form screen, answer nothing

| # | Where | Expected now |
|---|---|---|
| R1 | Downloaded PDF | values are printed (not a blank template) |
| R2 | Policy Number card | **"two policies on the same coverage line (general liab)"**, offering `QPC5519 - 26` vs `LSG-4471102-26`, button **Confirm for general liab** |
| R3 | Carrier and Carrier NAIC cards | the same General Liability question: Quillon Property & Casualty Company vs Larchmont Specialty Insurance Co.; 91880 vs 93518 |
| R4 | Policies in this submission | Auto Quillon Mutual Casualty Company / 91872 / `4A8-21-07---26`; **two** General Liability rows - Quillon Property & Casualty Company / 91880 / `QPC5519 - 26` and Larchmont Specialty Insurance Co. / 93518 / `LSG-4471102-26`; Inland Marine **Quillon Specialty Insurance Company** / 91895 / `SIM-7730418`; Property Quillon Property & Casualty Company / 91880 / `QPC5519 - 26`; Umbrella **Quillon Mutual Casualty Company** / `4U8-21-07---26` (NAIC may show a dash); no Workers Comp row; **no Birchline anywhere** |
| R5 | ACORD 126 | POLICY NUMBER, CARRIER, NAIC **blank** - General Liability is the open question |
| R6 | ACORD 131 | CARRIER Quillon Mutual Casualty Company / NAIC 91872 / `4U8-21-07---26`; EXPIRING POL # `4U8-21-07---25`; underlying Auto `4A8-21-07---26`; underlying GL number blank (two GL policies) |
| R7 | ACORD 25 | Auto `4A8-21-07---26` **with** 01/01/2026 - 01/01/2027; Excess `4U8-21-07---26` 03/15/2026 - 03/15/2027; GL row number **and** INSR LTR blank; insurer list Quillon Property & Casualty Company 91880, Quillon Specialty Insurance Company 91895, Quillon Mutual Casualty Company **91872** - Auto and Excess lettered to Quillon Mutual Casualty Company |
| R8 | ACORD 125 page 1 / prior carrier grid | carrier, NAIC, policy number blank; 2025 row: `QPC5519 - 25`, `4A8-21-07---25`, `4U8-21-07---25` each beside its own dates |
| R9 | Pre-download review | **no** policy-number rows and **no** "Policy EffectiveDate ... source value" rows |
| R10 | Send to Client, then re-download 126 / 131 / 25 | nothing changes |

### Upload 1 - then confirm `LSG-4471102-26` for General Liability and regenerate

| # | Expected now |
|---|---|
| R11 | the three General Liability cards clear |
| R12 | ACORD 126: `LSG-4471102-26` / Larchmont Specialty Insurance Co. / 93518 |
| R13 | ACORD 25 GL row: `LSG-4471102-26`, lettered to Larchmont Specialty Insurance Co. (seated with 93518) |
| R14 | nothing else moved: 131, 25 Auto / Excess, Property row `QPC5519 - 26` |

(Confirming `QPC5519 - 26` instead gives 126 `QPC5519 - 26` / Quillon Property & Casualty Company / 91880 and takes Larchmont Specialty Insurance Co. off the certificate.)

### Upload 2 - `3_renewal_summary_one_number.pdf` alone

| # | Where | Expected now |
|---|---|---|
| R15 | ACORD 126 / 131 POLICY NUMBER | **blank** - the page says each coverage is a separate policy |
| R16 | ACORD 131 underlying GL and Auto rows | policy number **blank** |
| R17 | ACORD 25 GL / Auto / Excess rows | policy number **blank**; carrier SAGEBRUSH RIDGE CASUALTY COMPANY lettered A |
| R18 | Carrier on 126 / 131 | SAGEBRUSH RIDGE CASUALTY COMPANY |

**Known and not in this fix** (report, don't count as a regression):
the "Policy number" / carrier questions in the client questionnaire still write a
package-level answer that does not land on a per-line form box; the Inland Marine
Total Value card ($235,000 is the LLM's sum of two floaters); the "Umbrella
effective date ... 03/15/2024" and "Builders Risk requires a project value"
warnings; "Lines of business differ" listing No Coverage lines.

Sections 1-6 below are the ORIGINAL measurements against the 16 Sep and 9 Sep
builds, kept as the before picture.

### Short run - 4 forms + 3 forms (measured on both builds)

| Upload | Generate only | Given up |
|---|---|---|
| 1 | ACORD **125, 126, 131, 25** | 127 / 137 CO (auto is still checked on 131's underlying row and 25's auto row), 140 (the shared-number control - still visible as the Property row of the policies table), 101 (FOUND-2), 141 / 130 (no-coverage blanks), 138 CO (identity map; the carrier truncation still shows on 25's insurer list) |
| 2 | ACORD **126, 131, 25** | 125 and 127 - 131 alone shows the one number on three lines |

On the short run F3 reads: 16 Sep = exactly **1** Field QA row (ACORD 126, `QPC5519 - 26`
vs `QPC5519`); 9 Sep = **6-7** rows. For F2 re-download 125 and 131: 9 Sep
writes `4A8-21-07---26` into 125's policy number and `BSX-44120-24` into 131's
EXPIRING POL #. Checks that still apply: P1-P8, G1, G3-G5, G9-G15, G17, L1, C1-C2,
D1-D4.

**Before anything else:** download one generated form. If it is a blank
template, the environment cannot fill PDFs (on this Mac's `backend/.venv`,
pikepdf 9.3.0 has no `pikepdf.Boolean`, so `fill_pdf` returns the unfilled
template). Nothing below means anything on blank PDFs.

Every "Measured" value below comes from replaying these exact PDFs offline
through the real merge, stamper, Send-to-Client late-stamp, Field QA and Data
Consistency code, on the current build (16 Sep, `a8e6407`) and the 9 Sep build
(`162bfbd`). Section 6 says how, and what the live run can legitimately change.

---

## 1. IS THE 16 SEP FIX DEPLOYED? (upload 1)

The Data Consistency card is **not** a fingerprint in this kit - both builds show
the same package-wide question (see NEW-A). Use these instead:

| # | Where | 16 Sep build | 9 Sep build |
|---|---|---|---|
| F1 | ACORD 125 page 1, right after generating | CARRIER **blank**; "other insurance with this company" list **blank** | CARRIER `QUILLON MUTUAL CASUALTY COMPANY`; the list shows 3-4 policy numbers (sometimes a bare `-`) |
| F2 | Click **Send to Client**, then re-download ACORD 125, 101 and 141 | **nothing changes** - POLICY NUMBER stays blank on all three | `4A8-21-07---26` appears on all three - including ACORD 141, a line with **No Coverage** - beside NAIC `91880` |
| F3 | Pre-download review (Field QA) | **2-3** policy-number rows (3 when ACORD 137 CO is generated), and each compares two printings of the SAME policy (`QPC5519 - 26` vs `QPC5519`; `4A8-21-07---26` vs `4A82107`) | **9-11** rows where ANOTHER line's number is "expected", e.g. *ACORD 131 shows `4U8-21-07---26` but the source value is `4A8-21-07---26`* |
| F4 | supporting | Data Consistency never offers a form number | may offer `IM 7100 06 04` as a policy-number choice |
| F5 | supporting | ACORD 25 Workers Comp row blank | may print `4U8-21-07---26` on the Workers Comp row |

F1-F3 all left = 16 Sep build. Any of them right = pre-16-Sep build: stop, redeploy.

---

## 2. UPLOAD 1 - the package, the project certificate, every trap

### Truth

| Line | Carrier | NAIC | Current policy (all printings = one contract) | Term |
|---|---|---|---|---|
| General Liability | Quillon Property & Casualty Company | 91880 | `QPC5519 - 26` = `QPC5519` - **a package policy shared with Property** | 01/01/2026-01/01/2027 |
| Commercial Property | Quillon Property & Casualty Company | 91880 | `QPC5519 - 26` (same package policy) | 01/01/2026-01/01/2027 |
| Business Auto | Quillon Mutual Casualty Company | 91872 | `4A8-21-07---26` = `4A82107` = `4A8 21 07 26` | 01/01/2026-01/01/2027 |
| Umbrella | Quillon Mutual Casualty Company | 91872 | `4U8-21-07---26` = `4U82107` | **03/15/2026-03/15/2027** |
| Inland Marine | **Quillon Specialty Insurance Company** | 91895 | `SIM-7730418` = `SIM7730418` | 01/01/2026-01/01/2027 |
| Crime / Workers Comp | - | - | **No Coverage** | - |
| **Project GL (certificate only)** | Larchmont Specialty Insurance Company | 93518 | `LSG-4471102-26` - a SECOND real GL policy | 01/01/2026-01/01/2027 |

Prior terms: `QPC5519 - 25`, `QPC5519 - 24`, `4A8-21-07---25`, `4U8-21-07---25`;
the umbrella before that: Birchline Specialty Casualty Company `BSX-44120-24`.

**Rule for every policy-number box:** its own line's number (any printing) or
blank. FAIL = another line's number, a `-25`/`-24` number in a current box, a form
number (`IM 7100 06 04`, `CG 00 01 04 13`, `CA7001A 02-22`, `CU7001A 11-15`,
`CG 70 22A 04 17`), or an identifier shaped like one (`GS4618A-51207`, `LN-00917733`,
`0482917`, `LCOA-2026-114`, `NONE`).

### Traps in these two files

| Trap | Attacks |
|---|---|
| Page 1: lines + premiums only, group brand `QUILLON INSURANCE GROUP`, and ONE number in a correspondence note (`4A8 21 07 26`) | the live Orbin page-1 shape; the single-number push |
| Workers Comp "No Coverage" row right above the inland marine page | run 11 phantom WC |
| Three near-identical carrier entities; the inland marine one is an "Insurance **Company**" | family-key fusion; header carrier truncation |
| GL + Property on ONE package number | over-refusal (140 must fill) |
| Hired and Non-Owned Auto Liability printed on the package page | an auto-looking line carrying the package number |
| Auto page: "not part of package policy `QPC5519 - 26`" | a body sentence naming another contract |
| `RENEWAL OF` prior numbers in current page headers; a loss run with the same priors dated | prior term in a current box; prior-grid row alignment |
| Umbrella's schedule of underlying insurance (`Quillon P&C Co.`, `QPC5519`, `4A82107`, "Employers Liability - Not Scheduled") | run 8 polluted index; P&C abbreviation; phantom EL row |
| AAIS / ISO / carrier form numbers beside policy numbers; a forms schedule naming four contracts | form number as policy number |
| Certificate: project GL policy from another carrier, compressed printings, `NONE` on Workers Comp | the must-ask case; printing folds; phantom WC |

### Step 1 - pre-form screen (Data Consistency)

| # | Where | Correct | Measured, 16 Sep |
|---|---|---|---|
| P1 | Policy Number card | a question scoped to **General Liability only**: `QPC5519 - 26` vs `LSG-4471102-26` | **FAIL - NEW-A.** Package-wide *"these values could not be matched to a coverage line - confirm which applies"*, offering `4A8-21-07---26` vs `LSG-4471102-26`, with a plain **Confirm** button. 9 Sep: the same |
| P2 | Policies in this submission - Auto row | Quillon Mutual Casualty Company / 91872 / `4A8-21-07---26` | **FAIL - NEW-A.** No policy number; carrier Quillon Property & Casualty Company (or Quillon Specialty Insurance Company) with NAIC 91880 |
| P3 | Policies table - General Liability | `QPC5519 - 26` (and the project policy flagged) | **FAIL - NEW-A.** No policy number |
| P4 | Policies table - Property | Quillon Property & Casualty Company / 91880 / `QPC5519 - 26` | PASS |
| P5 | Policies table - Umbrella | Quillon Mutual Casualty Company / 91872 / `4U8-21-07---26` | PASS (on the Orbin-shaped extraction the carrier reads Quillon Specialty Insurance Company) |
| P6 | Policies table - Inland Marine | Quillon Specialty Insurance Company / 91895 / `SIM-7730418` | **FAIL - FOUND-6.** `QUILLON SPECIALTY INSURANCE`, NAIC blank |
| P7 | Policies table - row count | 5 lines (GL, Property, Auto, Umbrella, Inland Marine), no Workers Comp | **FAIL - FOUND-1.** A Workers Comp row numbered `4U8-21-07---26` |
| P8 | Any card | no form number, serial, loan, account or contract number offered as a policy number | PASS |

### Step 2 - generate without answering anything

Select **ACORD 101, 125, 126, 127, 131, 25** (+ 137 CO if offered), then **add
140, 141, 130 and 138 CO manually**.

| # | Where | Correct | Measured, 16 Sep |
|---|---|---|---|
| G1 | ACORD 126 POLICY NUMBER | `QPC5519 - 26` or blank - never `LSG-4471102-26`, `4A8-21-07---26`, `4U8-21-07---26`, `SIM-7730418` | `QPC5519 - 26` (printed while the GL question is still open - record) |
| G2 | ACORD 127 / 137 CO POLICY NUMBER | `4A8-21-07---26` - never `QPC5519 - 26` (hired-auto trap, body sentence), never `4A8-21-07---25` | `4A8-21-07---26` |
| G3 | ACORD 131 POLICY NUMBER | `4U8-21-07---26` | `4U8-21-07---26` |
| G4 | ACORD 131 underlying Auto / GL rows | Auto: `4A82107` printing + Mutual; GL: `QPC5519` printing + P&C | both PASS |
| G5 | ACORD 131 Employers Liability row and EXPIRING POL # | both blank | blank |
| G6 | **ACORD 140** POLICY NUMBER / CARRIER / NAIC | `QPC5519 - 26` / Quillon Property & Casualty Company / 91880 - **blank here is over-refusal** | PASS |
| G7 | ACORD 141 (Crime) and ACORD 130 (Workers Comp) | no policy number anywhere | blank |
| G8 | ACORD 138 CO | blank - no garage / dealers policy exists | **FAIL** - `SIM-7730418` (identity map still says inland marine) with carrier `QUILLON SPECIALTY INSURANCE` (FOUND-6) |
| G9 | ACORD 25 GL row | blank or `QPC5519 - 26` while GL is contested | blank |
| G10 | ACORD 25 Auto row | `4A8-21-07---26` | **FAIL - NEW-A.** blank |
| G11 | ACORD 25 Excess row | `4U8-21-07---26`, 03/15/2026 - 03/15/2027 | PASS |
| G12 | ACORD 25 Workers Comp row | blank | blank |
| G13 | ACORD 25 insurer roster | each company once, full legal name, own NAIC | **FAIL - FOUND-6.** `QUILLON SPECIALTY INSURANCE` without NAIC; on the Orbin-shaped extraction the same company is listed twice |
| G14 | ACORD 125 page 1 POLICY NUMBER / CARRIER | blank / blank | blank / blank |
| G15 | ACORD 125 prior carrier grid | GL column only `QPC5519` numbers, Auto only `4A8-21-07` numbers, `BSX-44120-24` only under OTHER, each number on the SAME row as its dates | **FAIL - FOUND-3.** Row A holds the 2025 numbers without dates; row B holds their dates without numbers |
| G16 | ACORD 101 POLICY NUMBER / CARRIER | blank / blank (several policies, several carriers) | blank / **FAIL - FOUND-2** `QUILLON MUTUAL CASUALTY COMPANY` |
| G17 | Field QA list | no policy-number rows | **FAIL - NEW-C.** 2-3 rows, each comparing two printings of one policy |

### Step 3 - Send to Client, then re-download 125, 101, 126, 127, 131, 140, 141

| # | Correct | Measured, 16 Sep |
|---|---|---|
| L1 | Nothing changes on any of them | PASS (9 Sep: `4A8-21-07---26` on 125 / 101 / 141, and QUILLON MUTUAL CASUALTY COMPANY and/or `91880` written into the carrier / NAIC boxes of the section forms) |

### Step 4 - answer the Policy Number card

The card only offers a plain **Confirm** (NEW-A). Choose `LSG-4471102-26`,
confirm, and generate again.

| # | Correct | Measured, 16 Sep |
|---|---|---|
| C1 | The answer is applied to General Liability only: 126 and the ACORD 25 GL row print `LSG-4471102-26` with Larchmont Specialty Insurance Company / 93518 | **FAIL - NEW-B.** The card reads "confirmed" and no form changes: 126 keeps `QPC5519 - 26`, the 25 GL row stays blank |
| C2 | No other line takes `LSG-4471102-26` | PASS - 127 / 131 / 140 / 138 unchanged, nothing sprayed |

---

## 3. UPLOAD 2 - one printed number, three separate policies

New session, `3_renewal_summary_one_number.pdf` alone. Select **ACORD 125, 126, 127, 131, 25**. The page
prints ONE number, `SRC-4410982`, never says which line owns it, and states
*"Each coverage above is issued as a separate policy."*

| # | Where | Correct | Measured, 16 Sep |
|---|---|---|---|
| D1 | ACORD 126 / 127 / 131 POLICY NUMBER | blank (or a question) | **FAIL - FOUND-7.** `SRC-4410982` on all three (9 Sep: same) |
| D2 | ACORD 131 underlying GL and Auto rows | blank | **FAIL.** `SRC-4410982` - the umbrella claims its underlying policies share its own number |
| D3 | ACORD 25 GL / Auto / Excess rows | blank | **FAIL.** `SRC-4410982` on all three (9 Sep left them blank when the rows carried no number) |
| D4 | Data Consistency | a question | **FAIL.** "consistent" |
| D5 | ACORD 125 page 1 POLICY NUMBER after Send to Client | blank | PASS (9 Sep: `SRC-4410982` - another F2 fingerprint) |
| D6 | Carrier on 126 / 127 / 131 | Sagebrush Ridge Casualty Company | PASS - one carrier, borrowed correctly |

**Upload 2 is the surviving live form of the client's complaint** for a summary,
proposal, binder or invoice that prints one number for several lines.

---

## 4. What the replay found - current code, none of it fixed

| ID | Defect | Seen at | Root cause, isolated input by input | Builds |
|---|---|---|---|---|
| **NEW-A** | A package policy + hired auto on the package page + a project GL certificate turn the Policy Number question package-wide ("confirm which applies", Auto number vs project GL), strip the Auto and GL numbers from the policies table, give Auto the wrong carrier, and blank the ACORD 25 Auto row | P1-P3, G10 | (1) the hired/non-owned auto dec entry, printed under a PACKAGE heading that names no single line, is indexed under Auto with the package number, so Auto looks like two contracts - drop that one entry and Auto recovers; (2) a number shared by GL + Property is scoped to Property only, so GL has no number of its own, the two GL policies never collide, and with the project certificate both documents' numbers become unplaceable - a package-wide question. Give Property its own number AND drop the hired-auto entry, and the card correctly asks about GL only | both |
| **NEW-B** | A package-wide confirmation is accepted and discarded - "confirmed", no form changes | C1 | the confirmation lands only in the flat `policy_number`, which no section resolver reads any more | current |
| **NEW-C** | Field QA flags the same policy printed two ways | G17 | the checker compares the owning resolver's raw printing (`QPC5519`, `4A82107`) with the stamped canonical printing | current |
| FOUND-1 | Phantom Workers Comp policy numbered with the umbrella's number | P7 | "Employers Liability - Not Scheduled" on the umbrella schedule; "Not Scheduled" is not read as a denial (run 11 handled only "No Coverage") | current |
| FOUND-2 | ACORD 101 prints one carrier on a multi-carrier package | G16 | no resolver owns `Insurer_FullName_A` on 101 | both |
| FOUND-3 | Prior carrier grid splits one prior policy across two rows | G15 | the same prior policy arrives undated (`RENEWAL OF`) and dated (loss run) | both |
| FOUND-6 | Any "... Insurance Company" carrier is cut to "... Insurance" and loses its NAIC; the certificate can list the company twice | P6, G8, G13 | `_HEADER_CARRIER_RE` matches lazily and stops at the FIRST "INSURANCE" | current (regression from the 14 Sep header binding) |
| FOUND-7 | One printed number spreads to every line, certificate rows included | D1-D4 | the per-line fill attributes the page's only number to every line printed on it | both; current also fills the certificate |
| 138 | ACORD 138 (Garage and Dealers) prints the inland marine policy | G8 | `_SECTION_FORM_LINE_PHRASES` still maps 138 to contractors equipment / inland marine | both |

**Measured offline, not reachable with this kit:** two defects in the GL-scoped
confirmation - a number-only confirmation recombines the row (the other company's
name with this company's NAIC, on ACORD 25 too), and a section header can ignore
the confirmed number when the dec index names one. The UI only offers the scoped
confirm when the card is already scoped to one line, and NEW-A turns it
package-wide first.

**Side observations, no box affected here:** the header binder refuses a page whose
header matches two contracts (numbers sharing digit blocks, or a `RENEWAL OF`
line), and a group-brand header can vote as a carrier ("QUILLON INSURANCE") on a
page whose first lines name one contract.

---

## 5. What to send back

For every check: PASS / FAIL / not seen, plus the literal value for any FAIL.
Screenshots: the Data Consistency panel (card + policies table), the pre-download
review list, ACORD 125 page 1 and its prior carrier grid, 126 / 127 / 131 page 1
plus 131's underlying schedule, 140, 138, 25, 101 - before and after Send to
Client.

## 6. How the expectations were measured

`backend/scripts/make_policy_by_line_test_pdfs.py` builds these PDFs and
self-checks them through the pipeline's own text extractor and document
classifier. The measured values come from running that real PDF text through
`merge_facts` -> `map_facts_to_form` -> the Send-to-Client late-stamp -> Field QA ->
the Data Consistency card, on both builds, with extraction output modelled three
ways (page-1 rows handed the next page's number as on the live Orbin runs,
handed the correspondence note's number, and clean). Outcomes were the same
across all three unless a row says otherwise.

**The live extraction will differ.** A box that comes back BLANK where the
replay filled it is usually an extraction miss - check the policies table first.
A box that shows ANOTHER line's number is a real failure whatever extraction did.
