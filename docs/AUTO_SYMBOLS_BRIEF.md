# Covered-Auto Symbols: Reference and Rules In Force

**Last updated:** 2026-08-08
**Code:** `backend/services/auto_symbols.py` - the table and all reasoning helpers.
**Tests:** `backend/tests/test_auto_symbols.py` (46).
**Incident history:** see the "Auto Symbol Warnings Fired On Every Submission" entry
in `CLAUDE.md`. This document is the durable reference, not the post-mortem.

---

## 1. What a covered-auto symbol is

A commercial auto policy never writes out "this coverage applies to these vehicles."
It prints a number next to each coverage line, and that number is a defined term.

**Business Auto (ACORD 137 CA/CO)**

| Symbol | Means |
|---|---|
| 1 | Any auto - owned, hired, borrowed, employees' vehicles, everything |
| 2 | Owned autos only |
| 3 | Owned private passenger autos only |
| 4 | Owned autos other than private passenger only |
| 6 | Owned autos subject to a compulsory uninsured motorists law |
| 7 | Specifically described autos (the ones on the vehicle schedule) |
| 8 | Hired autos only |
| 9 | Non-owned autos only |

**Other families** use the same ideas with their own numbers:

| Family | Numbers | Where the grid lives |
|---|---|---|
| Business Auto | 1, 2, 3, 4, 6, 7, 8, 9 | ACORD 137 CA/CO |
| Garage and Dealers | 21, 22, 23, 24, 26, 27, 28, 29, 30, 31 | ACORD 138 CA/CO, ACORD 160 |
| Truckers | 41, 42, 43, 45, 46, 47, 48, 49, 50 | ACORD 137 CA/CO |
| Motor Carrier | 61, 62, 63, 64, 66, 67, 68, 69, 70, 71 | ACORD 137 CA/CO |

37 symbols in total. The four number ranges are disjoint, so a bare number identifies
its own family with no guessing.

A declarations page reading **Liability 01, Comprehensive 07, Collision 07** means:
*liability protects any vehicle the business touches; physical damage only pays for
the trucks on the schedule.* One digit, a very large coverage consequence.

**The definitions are ACORD's, not ours.** Every description in `auto_symbols.py` is
lifted verbatim from the `/TU` tooltips of the real symbol checkboxes in
`forms_schemas/ACORD_137_*` and `ACORD_138_*`. They were already on disk from schema
generation. `test_every_symbol_description_matches_acord_tooltip` re-reads those
schemas on every build and fails on a one-word drift.

---

## 2. Rules currently in force

| Rule | Fires when | Severity |
|---|---|---|
| `auto_symbols_not_captured` | An auto submission carries no covered-auto symbol anywhere. Worded as a transfer, resolvable inline by entering the symbols. | soft warning |
| `auto_hired_nonowned_symbols_missing` | Hired/non-owned exposure exists AND the known liability symbol genuinely does not reach it. **Symbol 1 satisfies this - it is broader than 8 and 9.** | soft warning |
| `auto_physical_damage_symbols_missing` | Physical damage requested, symbols exist, but none is designated for comprehensive or collision. | soft warning |
| `auto_owned_fleet_not_covered_by_symbol` | Vehicles are on the schedule but the liability symbol only reaches hired/non-owned autos. The fleet has no liability coverage as written. | **hard stop** |
| `auto_doc_symbol_missing` | Drive Other Car is referenced but no driver is marked as covered by it. DOC is an endorsement naming individuals, not a symbol. | soft warning |

All five clear inline: the symbol rules by entering the symbols, DOC by editing the
driver schedule. The carrier has already made the coverage decision, so resolving one
is a **transfer of an existing value, never a new decision**.

---

## 3. Where symbols get stamped

| Form | Field | How |
|---|---|---|
| ACORD 127 | `Vehicle_ComprehensiveSymbolCode_*`, `Vehicle_CollisionSymbolCode_*`, `Vehicle_SymbolCode_*` | Per vehicle row. A row that states its own symbol wins; otherwise it inherits the policy-level symbol for that coverage. Two competing policy-level symbols leave the cell blank. |
| ACORD 137/138/160 | `Vehicle_<Family>Symbol_<Word>Indicator_A` | Liability row only - see limit (b) below. |
| ACORD 25 | `Vehicle_AnyAutoIndicator_A` | Ticked when the liability symbol is an "any auto" symbol. A certificate that leaves this blank on a Symbol 1 policy understates the insured's coverage. |
| ACORD 131 | `UnderlyingCoverage_Coverage_AnyAutoIndicator_A` | Same. ACORD's own tooltip reads "(symbol 1)". |

---

## 4. Deliberate limits - read before "fixing" any of these

**a) ACORD 127 has no liability covered-auto box, and that is ACORD's design.**
Audited all 634 fields. The 127 records liability per vehicle as a checkbox
(`Vehicle_Coverage_LiabilityIndicator_*`); its only symbol fields are the 13
per-vehicle physical damage / comprehensive / collision codes. Symbol 1 lands on the
137 grid, ACORD 25 and ACORD 131. Any message telling a user to "define symbols on
ACORD 127" is pointing at the wrong form.

**b) Only the LIABILITY row of the 137/138 symbol grid is stamped.**
ACORD prints one grid **per coverage line**, stacked as rows A, B, C, E-H, each
offering only the symbols legal for that coverage. Row A is provably liability (the
only row carrying symbols 1 and 9). Row C is provably UM (only row with symbol 6).
**Rows E-H offer identical symbol sets and cannot be told apart from the schema.**
Stamping them would risk printing a liability symbol into a physical-damage row - a
wrong value on a legal document. Rows other than A fall through to gap fill exactly as
before. Mapping them requires reading the printed form layout, not more inference.

**c) ISO Symbols 5 and 19 are absent on purpose.**
They are real symbols but ACORD does not print them on its grid; they belong in the
"Other symbol" box, which we tick whenever an unrecognised symbol is present. Adding
rows for them would make the stamper tick a checkbox that does not exist on the form.

**d) Nothing here uses an LLM.**
A covered-auto symbol is a coverage designation with legal effect. A model inventing a
plausible one is exactly what the standing blank-over-wrong rule exists to prevent.
Every helper declines rather than guesses: `covers()` returns `None` ("cannot say") on
unknown or unrecognised symbols, and **callers must never read `None` as a coverage
gap**. Deterministic lookup also costs nothing to run.

**e) The five phantom facts must never come back.**
`hired_auto_symbol`, `non_owned_symbol`, `auto_physical_damage_comp_symbol`,
`auto_physical_damage_coll_symbol`, `drive_other_car_symbol` were read by two modules
and written by none, which is what made these warnings permanent false positives.
`test_no_check_reads_a_fact_nothing_writes` greps for them and fails the build.

---

## 5. Data shape

`auto_covered_symbols` stores symbols **attributed to their coverage line**:

```json
[{"coverage": "liability", "symbols": [1]},
 {"coverage": "comprehensive", "symbols": [7]},
 {"coverage": "collision", "symbols": [7]}]
```

A bare `[1, 7]` cannot say *which* coverage a number designates, which is the entire
point of a symbol. `auto_symbols.parse_symbols()` is the only parser and still accepts
the legacy bare list, a plain dict, and producer free text ("Liability 1, comp 7") so
older sessions and typed answers keep working.

---

## 6. Open item for Brent

Mapping rows B and E-H of the ACORD 137 grid to their coverage lines. It needs someone
to read the printed form, not a code change. Until then those rows behave exactly as
they did before this work. Tell us if it is worth doing, and whether any rule in
section 2 should be a different severity.
