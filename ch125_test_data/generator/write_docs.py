"""
write_docs.py - the human-readable answer key and the README, written from
CH125_answer_key.json after make_kit.py has built and verified the kit.

    backend/.venv/bin/python ch125_test_data/generator/write_docs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(HERE))
import kit_data as D   # noqa: E402

KEY = json.loads((KIT / "CH125_answer_key.json").read_text(encoding="utf-8"))
FORMS = KEY["_forms"]
FB = KEY["fields_by_form"]

HARD = [
    ("Receiving carrier only through an MGA", "MGA acknowledgement", "the insurer is Ridgeline, not the MGA that administers it; NAIC is in 4.3 pt fine print"),
    ("Superseded values, newest wins", "Aug worksheet vs CFO e-mail 09/30", "effective date 11/15 -> 12/01; Denise's cell 0109 -> 0190; location 3 area 3,400 -> 3,100"),
    ("Requested vs expiring", "GL supplemental, cover e-mail, auto supplemental", "126 rented premises / medical limits, per-location aggregate, PD deductible; 127 vehicle 4 collision deductible, towing added"),
    ("Blank is not No", "125 Q7, Q9; five 126 questions; 127 fleet", "never answered by the insured - and the package contains a customer's Chapter 11, a repossession BY the applicant, fraud and bankruptcy clauses in policy wording"),
    ("A No whose block is tempting", "125 Q8, Q10, Q11, Q14", "a CORRECTED citation; a judgment WON by the applicant; a shareholder's living trust; a drone SOLD in 2025"),
    ("Rescinded notice", "Old Hickory cancellation + rescission", "question 5 is a non-renewal for underwriting - NOT non-payment"),
    ("Answers by an X in a column", "125 supplement, ARU program application", "YES / NO read from the box position"),
    ("Drifting two-column layout", "ARU program application", "labels and values sit 3.6 pt off each other's baselines"),
    ("Riffled cells, abbreviated two-line headers", "premises schedule, hazards, loss runs, certificates", "LOC/BLD/CNTY/CITY LMTS/INT/OCC SF/PUB SF/TOT SF/LSD TO OTH"),
    ("Teletype letter-spacing", "GL and auto declarations", "P O L I C Y  N O ..."),
    ("Form boxes, label above value", "intake worksheet", "values separated from their labels"),
    ("Dates in five formats", "roster YYYYMMDD, MVR YYYY-MM-DD, hire DD-Mon-YYYY, Italian dd/mm/yyyy, prose", "the same date, read right"),
    ("Amounts in $000s and words", "financial statements, CFO e-mail", "15,200 (in $000s) = $15.2 million = $15,200,000"),
    ("OCR-garbled fax text", "Old Hickory 12/31/2025 valuation", "0/O and 1/l confusion on a SUPERSEDED valuation"),
    ("Rotated watermark", "2024 application (2 pages)", "SUPERSEDED - its letters land in the text layer"),
    ("Former name, same insured", "2022 auto claim", "Cumberland Restaurant Supply, LLC = the applicant before conversion - include it"),
    ("Another entity's claim / an old claim", "JV loss run; VF&M 2020 claim", "excluded: a separate LLC; older than five years"),
    ("Latest valuation", "three valuations of one auto claim", "12/31/2025, the August summary, 09/15/2026 - the last wins"),
    ("Two location numberings", "property SOV, GL schedule (insurer 001-004) vs the application (1-3)", "the application's numbers"),
    ("Counting by status", "HR census: HC / P/T / F/T / TMP", "full time, part time, agency temps and head count are four different numbers"),
    ("Percent of what", "CFO e-mail", "18% and 17% of TOTAL SALES; 95% of service CALLS is a decoy"),
    ("Role confusion", "certificate holders, landlord, mortgagee, lienholders, staffing firm, subcontractors", "each has exactly one box - or none"),
    ("Sold / terminated / closed", "auto endorsements, HR, premises footnote", "E-350 and Express sold, Ambrose terminated, Visco Dr closed"),
]

RECOMMENDATIONS = [
    ("Insured", "Answer 125 question 7 (fraud / bribery / arson conviction).", "UNRESOLVED - never answered"),
    ("Insured", "Answer 125 question 9 (foreclosure / repossession / bankruptcy).", "UNRESOLVED - the client's own example"),
    ("Insured", "Answer the 126 recreation facilities, lodging, swimming pool, day care and promotional-literature questions.", "UNRESOLVED"),
    ("Insured / producer", "Answer the 127 question 'are all vehicles part of a fleet?'.", "UNRESOLVED - the agent said it is open"),
    ("Producer", "Request the 2023-24 property premium from Volunteer Fire & Marine (prior carrier year 3).", "client: populate only what is substantiated and REQUEST the rest"),
    ("Producer", "Enter the NPN and the state producer licence.", "client: 'NPN: completed' - Primble's account profile has no field for either (audit gap)"),
    ("Producer", "Agency code / sub-code / customer id - only from the agency's own records.", "Riverbend's AMS prints them; Primble never fills these boxes today"),
    ("Applicant / producer", "Sign and date the applications.", "authorship - never filled by the AI"),
]
NOT_TO_ASK = ["drones (answered: no own, hires a Part 107 vendor)", "loss history (loss runs supplied)",
              "employee counts (HR census)", "revenue by location (CFO e-mail)",
              "safety program (manual, coordinator, OSHA, quarterly meetings)",
              "the proposed term (confirmed 12/01/2026 - 12/01/2027)", "parent company (no)",
              "trust (no)", "vehicles, drivers, garaging, use, radius (schedules supplied)"]


def _v(x, n=90):
    s = str(x).replace("|", "/")
    return s if len(s) <= n else s[:n - 3] + "..."


def key_md() -> str:
    m = KEY["_meta"]
    o = ["# CH125 ANSWER KEY - Cumberland Hearth & Hospitality Supply, Inc.", "",
         f"Document: `{KEY['_doc']}` - **{m['characters']:,} characters** ({m['character_measure']}), "
         f"{m['pages']} pages, text layer only (no scanned images).  ",
         "Machine key: `CH125_answer_key.json` (every box on all three forms). Grade a run with "
         "`ch125_test_data/grade_kit.py`.", "",
         "## The account in one paragraph", "",
         f"{D.NAME} (formerly {D.FORMER_NAME}, converted to a C corporation 01/01/2022; in business since "
         f"{D.START_DATE}) is a Nashville wholesale distributor of commercial kitchen equipment with a "
         f"service subsidiary, {D.SUB['name']}. It owns 40% of {D.JV['name']} (not a subsidiary, not "
         f"insured here). Its new agent, {D.AGENCY}, is submitting NEW BUSINESS for a QUOTE to "
         f"{D.CARRIER} (NAIC {D.CARRIER_NAIC}) through the MGA {D.MGA}, for {D.PROPOSED_EFF} - "
         f"{D.PROPOSED_EXP}: GL, property, business auto and umbrella. The incumbents are {D.OHM} (GL, "
         f"auto), {D.MAG} (property) and {D.CXS} (umbrella).", "",
         "## Totals", "", "| form | expect a value | blank - nothing stated | blank - a rule owns it | not scored |",
         "|---|---|---|---|---|"]
    for f in FORMS:
        c = m["verdict_counts"][f]
        o.append(f"| {f} | {c['expect']} | {c['blank_no_data']} | {c['blank_by_rule']} | {c['not_scored']} |")
    o += ["", "## 1. UNRESOLVED - must stay BLANK and be asked (blank is not No)", "",
          "| form | box | question |", "|---|---|---|"]
    o += [f"| {u['form']} | `{u['field']}` | {u['what']} |" for u in m["unresolved_expected"]]
    o += ["", "## 2. Expected recommendations (what Primble should ask, and of whom)", "",
          "| who | ask | why |", "|---|---|---|"]
    o += [f"| {w} | {a} | {y} |" for w, a, y in RECOMMENDATIONS]
    o += ["", "Primble should **not** ask for: " + "; ".join(NOT_TO_ASK) + ".", ""]
    for f in FORMS:
        o += [f"## {f} - every box that must carry a value", "",
              "| box | expected | match | page(s) | trap / note |", "|---|---|---|---|---|"]
        for fld, v in FB[f].items():
            if v["verdict"] != "expect":
                continue
            pages = ",".join(str(p) for p in v.get("pages", [])) or ("template" if v["source"] == "template"
                                                                      else ("derived" if v["source"] == "derived" else "see note"))
            note = "; ".join(x for x in (v.get("why") or "", ("TRAP: " + v["trap"]) if v.get("trap") else "") if x)
            o.append(f"| `{fld}` | {_v(v['value'])} | {v['match']} | {pages} | {_v(note, 170)} |")
        o += ["", f"### {f} - boxes a RULE owns as blank", "", "| box | rule | trap |", "|---|---|---|"]
        for fld, v in FB[f].items():
            if v["verdict"] == "blank_by_rule":
                o.append(f"| `{fld}` | {_v(v['why'])} | {_v(v.get('trap', ''))} |")
        o += ["", f"### {f} - not scored (grade by hand)", "", "| box | value to look for | why |", "|---|---|---|"]
        for fld, v in FB[f].items():
            if v["verdict"] == "not_scored":
                o.append(f"| `{fld}` | {_v(v['value'])} | {_v(v['why'])} |")
        nd = [fld for fld, v in FB[f].items() if v["verdict"] == "blank_no_data"]
        o += ["", f"### {f} - {len(nd)} boxes the documents never support (must stay blank)", "",
              ", ".join(f"`{x}`" for x in nd), ""]
    o += ["## Decoys - printed in the package, wrong only in the boxes named", "",
          "| form | value | must not appear in | why |", "|---|---|---|---|"]
    for form, lst in (("ACORD_125", D.DECOYS_125), ("ACORD_126", D.DECOYS_126), ("ACORD_127", D.DECOYS_127)):
        o += [f"| {form[-3:]} | `{_v(v)}` | `{s}` | {w} |" for v, s, w in lst]
    o += ["", "## Deliberately never stated", ""] + [f"- {a}" for a in D.ABSENT_BY_DESIGN]
    return "\n".join(o) + "\n"


def readme() -> str:
    m = KEY["_meta"]
    o = ["# CH125 kit - a 300,000-character submission for ACORD 125 (plus 126 / 127)", "",
         f"**Upload:** `{KEY['_doc']}` - exactly **{m['characters']:,} characters** of text "
         f"({m['character_measure']}), {m['pages']} pages, no scanned images.  ",
         "**Key:** `CH125_answer_key.json` (machine, all 548 + 255 + 634 boxes) and `CH125_ANSWER_KEY.md` "
         "(human: every value, its page, its trap, the UNRESOLVED list, the expected recommendations).  ",
         "**Rebuild:** `backend/.venv/bin/python ch125_test_data/generator/make_kit.py && "
         "backend/.venv/bin/python ch125_test_data/generator/write_docs.py` (deterministic).", "",
         "## Run it", "", "```bash",
         "# 1. restart the backend; keep PURGE_DEC_INDEX_AFTER_GENERATION=0 if you want the dec index in the dump",
         "# 2. upload CH125_cumberland_hearth_package.pdf, select ACORD 125 + 126 + 127, generate, change nothing",
         "backend/.venv/bin/python ch125_test_data/grade_kit.py --list",
         "backend/.venv/bin/python ch125_test_data/grade_kit.py --session <id> --label \"CH125 - TEST 1\" "
         "--out ch125_test_data/runs/t1.md",
         "# the 125 alone, in the FR125 report format (extraction ENTITY-CELL + the 23-rule audit too):",
         "backend/.venv/bin/python backend/scripts/dump_a125_run.py <id> > ch125_test_data/runs/t1_dump.json",
         "backend/.venv/bin/python backend/scripts/report_125_run.py --key ch125_test_data/CH125_answer_key.json "
         "--dump ch125_test_data/runs/t1_dump.json --label \"CH125 - TEST 1\"",
         "```", "",
         "Grade from the STORED session, not the downloaded PDF (this Mac's pikepdf can render blank "
         "templates). Row order of losses, drivers and vehicles is not a defect - read the ROW-CELL table.", "",
         "## What makes it hard", "", "| technique | where | what it tests |", "|---|---|---|"]
    o += [f"| {a} | {b} | {c} |" for a, b, c in HARD]
    o += ["", "## Counts", "", "| form | expect | blank (no data) | blank (rule) | not scored |", "|---|---|---|---|---|"]
    for f in FORMS:
        c = m["verdict_counts"][f]
        o.append(f"| {f} | {c['expect']} | {c['blank_no_data']} | {c['blank_by_rule']} | {c['not_scored']} |")
    o += ["", "## Decision points (graded as the client's rule; an owner call may differ)", "",
          "- **126 / 127 header** (carrier, NAIC, effective date, policy number): the key follows the "
          "client's 8-19-26 rule - the policy being applied for (Ridgeline, 12/01/2026, no number). The "
          "15 Sep 'section forms keep the current policy's identity' rule may print the incumbent; that is "
          "a decision, not a fill defect.",
          "- **125 Vehicle / Driver schedule attachment ticks** and the 127 SYM columns: not scored.",
          "- **Producer NPN / licence / agency codes / customer id**: not scored - they depend on the "
          "logged-in account, and Primble has no source for NPN or licence today.", "",
          "## Proved before use", "",
          "- every expected value is printed in the text layer (in some format); every decoy is printed;",
          "- the key scores a perfect form 100% and an empty form with zero violations on all three forms, "
          "through `backend/scripts/score_form_fill.py`;",
          "- the character count is measured on the written PDF, not estimated.", ""]
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    (KIT / "CH125_ANSWER_KEY.md").write_text(key_md(), encoding="utf-8")
    (KIT / "README-CH125-HOW-TO-TEST.md").write_text(readme(), encoding="utf-8")
    print("  wrote CH125_ANSWER_KEY.md and README-CH125-HOW-TO-TEST.md")
