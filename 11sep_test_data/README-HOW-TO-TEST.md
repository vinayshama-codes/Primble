# 11 Sep kit - how to test

Two uploads. **Do not merge them.**

| Upload | Files | Insured |
|---|---|---|
| **A** | `expiring_dec.pdf` + `underwriting_narrative.pdf` together | HALVORSEN STRUCTURAL LLC |
| **B** | `control_dec.pdf` alone, a SECOND session | MERIDIAN FABRICATION INC |

Generate forms for **ACORD 125, 126, 127, 131** on both.

---

## THE HEADLINE CHECK

Open **ACORD 126** from upload A and read three boxes.

```
  BROKEN   Employers Mutual Casualty  /  25186  /  IM 7100 06 04
  FIXED    EMC Property & Casualty    /  25186  /  BBC7263 - 26
```

No coverage line on that dec page states a premium - that single property is
what used to switch the whole per-line system off. If those three boxes are
right, the root cause is fixed.

---

## UPLOAD A - 31 checks

### Identity (items 1, 3, 5)

| # | Where | Expect |
|---|---|---|
| 1 | ACORD 126 header | INSURER `EMC Property & Casualty` or `EMC Property and Casualty Company` |
| 2 | ACORD 126 header | NAIC `25186` |
| 3 | ACORD 126 header | POLICY NUMBER `BBC7263 - 26` |
| 4 | ACORD 126 header | EFFECTIVE `07/15/2026`, EXPIRATION `07/15/2027` |
| 5 | ACORD 127 header | `Employers Mutual Casualty` / `21415` / `6E7-40-02---26` |
| 6 | ACORD 131 header | `Employers Mutual Casualty` / `21415` / `6J7-40-02---26` |
| 7 | any form | `25186` NEVER printed beside `Employers Mutual Casualty` |
| 8 | ACORD 125 policy-number box | blank (5 policies - the package has no single number) |
| 9 | anywhere | `IM 7100 06 04` NEVER appears in a policy-number box |
| 10 | ACORD 125 Q4 grid | each line paired with its OWN number; `6E7-40-02---26` and `6E74002` counted as ONE policy |
| 11 | Data Consistency | NO "multiple policy numbers" / "which carrier" card. 5 policies is what a package IS |

### Phantom coverage (item 2)

| # | Where | Expect |
|---|---|---|
| 12 | cover page | Lines of Business lists ONLY General Liability, Business Auto, Inland Marine, Umbrella |
| 13 | cover page | **NOT** Farm, Liquor, Employment-Related Practices, Owners and Contractors Protective, Equipment Breakdown |
| 14 | cover page | **NOT** Property, Crime, Workers Compensation (dec says NO COVERAGE) |
| 15 | ACORD 125 LOB boxes | same four ticked, nothing else |
| 16 | recommendations | no WC / property / crime forms pushed |

### Producer (item 4)

| # | Where | Expect |
|---|---|---|
| 17 | ACORD 125 Producer block | `ThinkSmith Agency` / `Michelle Smith` |
| 18 | ACORD 125 Producer block | **NOT** `Commercial Risk Solutions` / `Terri Wroblewski` |
| 19 | Data Consistency | no producer conflict card |

### Type (items 5, 10)

| # | Where | Expect |
|---|---|---|
| 20 | ACORD 126 | GENERAL AGGREGATE `$2,000,000` in the AMOUNT box |
| 21 | ACORD 126 | the three "applies per POLICY / PROJECT / LOCATION" ticks are NOT driven by that amount |
| 22 | Data Consistency | **NO** card comparing a limit with a Yes/No box, and none comparing Claims Made with `Commercial Liability Umbrella Coverage Form` |
| 23 | Data Consistency | **A card MUST appear** for GL form type: `OCCURRENCE` (dec) vs `claims-made` (narrative). **If this is missing the filter over-reached - that is a failure, not a pass.** |

### Cross-line codes (item 6)

| # | Where | Expect |
|---|---|---|
| 24 | ACORD 127 vehicle row | CLASS is `7383` or blank - **never** `91580` / `91585` |
| 25 | ACORD 127 vehicle row | no `$91,580` or `$350,000` in a vehicle cost/value box |
| 26 | ACORD 126 hazard grid | class codes `91580` / `91585` present and correct |
| 27 | ACORD 126 hazard grid | never `7383` |
| 28 | ACORD 127 | territory `6679` - **KNOWN LIMIT, PRE-MEASURED.** No schedule fact captures a Drive Other Car territory, so there is no witness and the guard cannot fire. If `6679` prints in a territory box, that is the documented gap, not a regression. Record it |

### Parties (item 8)

| # | Where | Expect |
|---|---|---|
| 29 | any Additional Interest / Loss Payee box | `Wells Fargo Equipment Finance, Inc.`, `Kestrel Terminal Authority`, `John A. Smith`, `City of Aurora` all allowed |
| 30 | any party box | `For Informational Purposes Only` and `As Their Interests May Appear` NEVER appear |

### Everything else

| # | Where | Expect |
|---|---|---|
| 31 | form recommendations | `ACORD 137 CO` offered (Needs Confirmation). Item 7 - it is a tier decision, not a bug |
| 32 | client questionnaire | the Subaru is NOT asked for again; no numbered "(Nth vehicle)" cards; no driver beyond the one on the dec |

### BOUNDARY PROBE - record the result, it may legitimately fail

| # | Where | Expect |
|---|---|---|
| 33 | ACORD 125 Q4 grid / Boiler and Machinery | `BM 1234 05 21` is a REAL policy number in ISO edition shape. **PRE-MEASURED: it WILL be blanked** - `_looks_like_a_form_number` cannot tell it from `IM 7100 06 04`. This is the safe direction (blank over wrong), not a correctness failure, and it is here to size the cost. Confirm the blank and note whether any real carrier in Brent's book numbers policies this way |

---

## UPLOAD B - the quiet control, 5 checks

Its job is to fail loudly if a guard is too aggressive. **Everything must fill.**

| # | Where | Expect |
|---|---|---|
| 34 | ACORD 126 / 127 headers | `Great Plains Casualty Company` / `34521` - one carrier, borrowed correctly for every line |
| 35 | ACORD 126 / 127 headers | the right policy number per line (`GPC-GL-55210`, `GPC-BA-55211`) |
| 36 | ACORD 125 Producer block | `Cascade Risk Partners` - **must NOT be wiped.** No submission document names a producer, and an incumbent broker is allowed to be both |
| 37 | cover page | Lines of Business lists General Liability, Business Auto, Commercial Property - the priced path, unchanged |
| 38 | any party box | `Boulder Valley Bank` fills |

**If B comes back with blanks, A's passes were luck.**

---

## What to send back

For each numbered check: PASS / FAIL / not-seen, and for any FAIL the literal
value that printed. Screenshots of ACORD 125 page 1, ACORD 126 page 1, ACORD 127
page 1, the cover page and the Data Consistency panel cover most of it.
