"""Build 22 (21 Oct 2026, evening), lane C - Brent's 17 Oct attachment C: the
claims checks (25sepChanges.md Z29-3 C, Z31-C).

His synthetic claims file (`fixtures/brent_synthetic_claims_17oct.xlsx`) holds
12 CONTROL claims and 12 CHALLENGE copies of the SAME claims with planted
mistakes. Nothing read a claim's fields, so the CHALLENGE copy scored exactly
like the CONTROL copy. `services/claim_checks.py` is now the one reader of the
claims and runs seven generic checks; contradictions are Exposure Consistency
deductions, missing details Completeness deductions (Brent's rule, D69), each
named on the loss table's Recommendations card - never a hard stop or a warning
(owner, 21 Oct).

The adversarial cases come first in every section: each rule is shown NOT to
fire on the shapes a real loss run legitimately has (the claimant's car, a sold
vehicle, a street address, a leading year, a loss-only incurred, a recovery,
a line that prints no report dates) before it is shown to fire.

Brent's B2 question (two copies of the same claims in one file) is not ours to
answer: CONTROL rows alone give no finding, CHALLENGE rows alone give every
planted one, and nothing compares the two copies.
"""
from __future__ import annotations

import copy
import html
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-offline")

from services import claim_checks as cc            # noqa: E402
from services import schedule_capture as sc        # noqa: E402
from services import sqs_service as sq             # noqa: E402

_BACKEND = Path(__file__).resolve().parents[1]
_FRONT = _BACKEND.parent / "frontend" / "src"
_FIX = Path(__file__).resolve().parent / "fixtures"
_CLAIMS_XLSX = _FIX / "brent_synthetic_claims_17oct.xlsx"
_CE_FIXTURE = _FIX / "choice_electric_loc_6oct.json"
_EM = ("—", "–")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

_TERM = [{"line": "Commercial Auto", "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}]


def _ctx(**over):
    """A package's schedules for the unit tests (the Choice Electric shapes)."""
    base = {
        "coverage_lines": copy.deepcopy(_TERM),
        "auto_vin_schedule": [
            {"year": "2014", "make": "FORD", "model": "F150 SUPERCREW", "vin": None},
            {"year": "2017", "make": "CHEVROLET", "model": "EXPRESS G2500", "vin": None},
        ],
        "property_locations": [
            {"premises_number": "001", "building_number": "001", "location_number": "1"},
            {"premises_number": "001", "building_number": "002", "location_number": "1"},
        ],
        "wc_class_codes": [{"code": "5190"}, {"code": "8742"}, {"code": "8810"}],
    }
    base.update(over)
    return base


def _claim(**over):
    row = {"claim_number": "C-1", "date": "06/01/2025", "line_of_business": "Business Auto",
           "description": "Collision", "paid": "1000", "reserved_amount": "0"}
    row.update(over)
    return row


def _found(rows, **ctx):
    """[(claim number, check)] the checks report for `rows` on the package."""
    return [(f["claim_number"], f["check"])
            for f in cc.claim_findings(dict(_ctx(**ctx), loss_history=rows))]


def _checks(rows, **ctx):
    return [check for _n, check in _found(rows, **ctx)]


# ── Brent's workbook ─────────────────────────────────────────────────────────

def _xlsx_rows(path):
    """Cells by column letter, shared strings resolved (the file has one sheet)."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            xml = z.read("xl/sharedStrings.xml").decode("utf-8")
            for si in re.findall(r"<si>(.*?)</si>", xml, re.S):
                shared.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    out = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        row = re.sub(r"<c [^>]*/>", "", row)
        cells = {}
        for col, attrs, inner in re.findall(r'<c r="([A-Z]+)\d+"([^>]*)>(.*?)</c>', row, re.S):
            v = re.search(r"<v>(.*?)</v>", inner)
            v = v.group(1) if v else ""
            cells[col] = shared[int(v)] if 't="s"' in attrs else v
        out.append(cells)
    return out


def _serial(v):
    """An Excel 1900 serial as MM/DD/YYYY (the sheet's dates use built-in 58)."""
    return (date(1899, 12, 30) + timedelta(days=int(v))).strftime("%m/%d/%Y")


@lru_cache(maxsize=1)
def _brent():
    rows = _xlsx_rows(_CLAIMS_XLSX)
    head = rows[0]
    out = []
    for r in rows[1:]:
        g = {}
        for col, name in head.items():
            v = r.get(col, "")
            if name in ("loss_date", "reported_date", "first_made_date") and v.isdigit():
                v = _serial(v)
            g[name] = v
        out.append(g)
    return tuple(json.dumps(g) for g in out)


def _brent_rows(dataset):
    return [json.loads(g) for g in _brent() if json.loads(g)["dataset"] == dataset]


# What the rows would carry with every one of his columns captured - the
# reader's own names. (Today nothing captures expense or first-made.)
_EVERY_FIELD = {"synthetic_claim_id": "claim_number", "loss_date": "date", "reported_date": "claim_date",
                "first_made_date": "first_made_date", "status": "status", "line": "line_of_business",
                "description_asset": "description", "paid_usd": "paid", "reserve_usd": "reserved_amount",
                "expense_usd": "expense", "incurred_usd": "incurred"}


def _every_field_rows(dataset):
    return [{key: g.get(src, "") for src, key in _EVERY_FIELD.items()} for g in _brent_rows(dataset)]


def _extracted_rows(dataset):
    """The rows loss-run extraction writes (its RULE 7 keys): amount is the
    total incurred, open_code O / C - and no expense, no date first made."""
    out = []
    for g in _brent_rows(dataset):
        status = g["status"].strip().lower()
        out.append({"date": g["loss_date"], "claim_date": g["reported_date"], "description": g["description_asset"],
                    "amount": g["incurred_usd"], "paid": g["paid_usd"], "reserved_amount": g["reserve_usd"] or None,
                    "claim_number": g["synthetic_claim_id"], "line_of_business": g["line"],
                    "open": status == "open", "open_code": "O" if status == "open" else "C",
                    "subrogation_code": None})
    return out


# The nine planted mistakes, by claim number and check.
_PLANTED = {
    ("SIM-AUTO-003", cc.CHECK_REPORT_BEFORE_LOSS),        # reported 10/24 for an 11/02 loss
    ("SIM-PKG-005", cc.CHECK_INCURRED_MISMATCH),          # 9,200 vs 8,900 + 0 + 400
    ("SIM-AUTO-002", cc.CHECK_VEHICLE_NOT_SCHEDULED),     # V016 as a 2018 Ford Transit 250
    ("SIM-PKG-003", cc.CHECK_BUILDING_NOT_SCHEDULED),     # Prem 001, Bldg 003
    ("SIM-WC-002", cc.CHECK_CLASS_NOT_SCHEDULED),         # 5190 -> 5403
    ("SIM-PKG-002", cc.CHECK_REPORT_DATE_MISSING),        # NOT PROVIDED
    ("SIM-CYB-001", cc.CHECK_REPORT_DATE_MISSING),        # NOT PROVIDED
    ("SIM-EPL-001", cc.CHECK_FIRST_MADE_MISSING),         # NOT PROVIDED
    ("SIM-WC-001", cc.CHECK_RESERVE_MISSING),             # open, reserve blank
}
# What needs a field nothing captures today (expense / date first made).
_NEEDS_EXTRACTION = {("SIM-PKG-005", cc.CHECK_INCURRED_MISMATCH), ("SIM-EPL-001", cc.CHECK_FIRST_MADE_MISSING)}


# ── The real Choice Electric package (its seven decs, merged) ────────────────

@lru_cache(maxsize=1)
def _merged():
    from services import extraction_service as es
    with open(_CE_FIXTURE, encoding="utf-8") as fh:
        docs = [d for d in json.load(fh)["docs"] if not d.get("excluded")]
    mf, flags = es.merge_facts(docs, es.select_primary_truth(docs))
    return json.dumps(mf, default=str), json.dumps(flags, default=str)


# The application's core answers (Tier 1 / Tier 2), so Structural is not held
# at its 0 floor - on the seven decs alone it is, and a floored pillar has no
# points left to take (`_structural_parts`, pinned below).
_CORE = {"applicant_name": "CHOICE ELECTRIC LLC", "mailing_address": "4800 Dahlia St, Denver, CO 80216",
         "entity_type": "LLC", "fein": "84-2210987", "years_in_business": "12", "producer_name": "Broker Inc",
         "operations_description": "Commercial and residential electrical contractor",
         "total_revenue": "6000000", "naics_code": "238210", "contact_name": "Eric Berger",
         "num_employees": "40"}


def _package(rows, core=False):
    mf, flags = (json.loads(x) for x in _merged())
    if core:
        mf.update(copy.deepcopy(_CORE))
    mf["loss_history"] = rows
    return mf, flags


def _score(facts, flags, share_out=False):
    tok = None if share_out else sq.SKIP_SHARE_OUT.set(True)
    try:
        return sq.calculate_package_sqs(
            facts=facts, flags=flags, form_results=[], cross_issues=[], hard_stops=[],
            soft_stops=[], session_data={}, form_fill=False)
    finally:
        if tok is not None:
            sq.SKIP_SHARE_OUT.reset(tok)


# ── node ─────────────────────────────────────────────────────────────────────

def _node(tmp_path, body):
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as S from {json.dumps((_FRONT / 'utils' / 'scheduleImport.js').as_uri())};\n"
        f"import * as R from {json.dumps((_FRONT / 'utils' / 'recommendations.js').as_uri())};\n"
        "import fs from 'node:fs';\n"
        "const out = (v) => console.log(JSON.stringify(v));\n"
        "const file = (p, name) => { const b = fs.readFileSync(p); b.name = name; return b; };\n"
        + body + "\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _cols(list_key):
    return json.loads(json.dumps(sc.SCHEDULE_DEFS))[list_key]["columns"]


# ══════════════════════════════════════════════════════════════════════════════
# 1. ONE reader - both paths, one set of names
# ══════════════════════════════════════════════════════════════════════════════

def test_one_reader_reads_the_extracted_row_and_the_table_row_alike():
    extracted = {"date": "03/13/2025", "claim_date": "03/15/2025", "description": "Collision",
                 "amount": "12000", "paid": "12000", "reserved_amount": "0", "claim_number": "A-1",
                 "line_of_business": "Business Auto", "open": False, "open_code": "C",
                 "subrogation_code": "N"}
    typed = {"date": "03/13/2025", "claim_date": "03/15/2025", "description": "Collision",
             "paid": "$12,000", "reserved_amount": "0", "line_of_business": "Business Auto",
             "open_code": "Closed"}
    sentence = {"date": None, "claim_date": None, "description": "no prior losses or claims in the last five years"}
    recs = cc.claim_records({"loss_history": {"value": [extracted, sentence, typed]}})
    assert len(recs) == 2, "the no-loss sentence is not a claim (loss_history_state.claim_rows)"
    a, b = recs
    assert (a["number"], a["loss_date"], a["report_date"], a["incurred"], a["status"]) == \
        ("A-1", "03/13/2025", "03/15/2025", "12000", "closed")
    assert (b["number"], b["loss_date"], b["report_date"], b["incurred"], b["status"]) == \
        (None, "03/13/2025", "03/15/2025", None, "closed")


@pytest.mark.parametrize("row, expected", [
    ({"open_code": "O"}, "open"), ({"open_code": "C"}, "closed"),
    ({"open_code": "Y"}, "open"), ({"open_code": "N"}, "closed"),          # ACORD's "claim open? Y / N"
    ({"open_code": "Open"}, "open"), ({"open_code": "Closed"}, "closed"),
    ({"status": "Reopened"}, "open"), ({"status": "Settled"}, "closed"),
    ({"status": "Re-opened"}, "open"), ({"status": "Open - in litigation"}, "open"),
    ({"status": "Closed without payment"}, "closed"), ({"status": "Not open"}, None),
    ({"open": True}, "open"), ({"open": False}, "closed"),
    ({"open_code": "C", "open": True}, "closed"),                          # the code outranks the flag
    ({"open_code": "", "open": True}, "open"),
    ({"status": "pending review"}, None), ({}, None),
])
def test_the_status_is_read_from_every_spelling(row, expected):
    assert cc._status(row) == expected


@pytest.mark.parametrize("value", [None, "Yes", {}, [], {"value": None}, "[]", 5])
def test_anything_but_a_list_of_rows_has_no_claims(value):
    # "Yes" is the share-out door's probe answer for a table field.
    assert cc.claim_records({"loss_history": value}) == []
    assert cc.claim_findings({"loss_history": value}) == []
    assert cc.claim_deduction_items({"loss_history": value}) == []


def test_no_facts_at_all_is_no_finding_and_never_raises():
    assert cc.claim_findings(None) == [] and cc.claim_findings({}) == []
    assert cc.claim_findings({"loss_history": [None, "x", 3, {"date": object()}]}) == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. The checks - adversarial first
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. dates out of order ────────────────────────────────────────────────────

@pytest.mark.parametrize("loss, report, fires", [
    ("11/02/2025", "11/04/2025", False),          # reported after the loss
    ("11/02/2025", "11/02/2025", False),          # the same day
    ("11/02/2025", "11/2025", False),             # month only: not known to be before
    ("11/02/2025", "2025", False),                # year only
    ("11/2025", "11/2025", False),
    ("11/02/2025", "see notes", False),           # unreadable: never judged
    ("NOT PROVIDED", "10/24/2025", False),        # no loss date: nothing to compare
    ("11/02/2025", "10/24/2025", True),           # Brent's SIM-AUTO-003
    ("2025-11-02", "2025-10-24", True),
    ("November 2, 2025", "October 24, 2025", True),
    ("11/02/2025", "10/2025", True),              # a month before the loss month
    ("11/2025", "10/24/2025", True),
    ("2025", "12/31/2024", True),
])
def test_a_report_date_before_the_loss_date(loss, report, fires):
    got = _checks([_claim(date=loss, claim_date=report)])
    assert (cc.CHECK_REPORT_BEFORE_LOSS in got) is fires


def test_a_claim_first_made_before_its_loss_is_a_conflict_and_after_is_not():
    epl = dict(line_of_business="Employment Practices Liability", description="Wrongful termination")
    assert _checks([_claim(date="04/10/2025", first_made_date="07/01/2025", **epl)]) == []
    assert _checks([_claim(date="04/10/2025", first_made_date="03/01/2025", **epl)]) == \
        [cc.CHECK_FIRST_MADE_BEFORE_LOSS]


# ── 2. dates not provided ────────────────────────────────────────────────────

def test_a_blank_report_date_is_not_missing_where_the_line_prints_none():
    rows = [_claim(claim_number="A"), _claim(claim_number="B")]
    assert _checks(rows) == []


def test_a_blank_report_date_is_not_missing_because_another_line_prints_them():
    rows = [_claim(claim_number="A", line_of_business="General Liability", claim_date="06/03/2025"),
            _claim(claim_number="B")]
    assert _checks(rows) == []


def test_a_blank_report_date_is_missing_where_the_same_line_prints_them():
    rows = [_claim(claim_number="A", claim_date="06/03/2025"), _claim(claim_number="B")]
    assert _found(rows) == [("B", cc.CHECK_REPORT_DATE_MISSING)]


@pytest.mark.parametrize("value", ["NOT PROVIDED", "not provided", "unknown", "TBD", "not available",
                                   "(unknown)"])
def test_a_report_date_written_as_not_provided_is_missing(value):
    assert _checks([_claim(claim_date=value)]) == [cc.CHECK_REPORT_DATE_MISSING]


@pytest.mark.parametrize("value", ["pending", "see notes", "45731", "N/A", "None", "-", "--"])
def test_a_report_date_that_says_something_else_is_not_called_missing(value):
    # "pending" is a status, not a placeholder (answer_semantics); a stray Excel
    # serial is unreadable; "N/A" / "None" answer the question; a dash is a
    # blank cell - and this line prints no report dates.
    assert _checks([_claim(claim_date=value)]) == []


def test_a_dash_is_a_blank_cell_where_the_line_prints_report_dates():
    rows = [_claim(claim_number="A", claim_date="06/03/2025"), _claim(claim_number="B", claim_date="-")]
    assert _found(rows) == [("B", cc.CHECK_REPORT_DATE_MISSING)]


def test_a_blank_first_made_date_is_never_missing_and_not_provided_is():
    occurrence = [_claim(claim_number="A"), _claim(claim_number="B", first_made_date="07/01/2025")]
    assert _checks(occurrence) == []
    assert _found([_claim(first_made_date="NOT PROVIDED")]) == [("C-1", cc.CHECK_FIRST_MADE_MISSING)]


@pytest.mark.parametrize("value", ["N/A", "n/a", "Not applicable", "None", "-"])
def test_a_first_made_date_of_n_a_on_an_occurrence_claim_is_an_answer(value):
    # Loss runs print "N/A" in the column for every claim that is not claims-made.
    rows = [_claim(claim_number="A", first_made_date=value),
            _claim(claim_number="B", line_of_business="EPL", first_made_date="07/01/2025")]
    assert _checks(rows) == []


# ── 3. an open claim with no reserve ─────────────────────────────────────────

def test_a_closed_claim_with_no_reserve_is_not_missing_one():
    rows = [_claim(claim_number="A", reserved_amount="500", open_code="Open"),
            _claim(claim_number="B", reserved_amount=None, open_code="Closed")]
    assert _checks(rows) == []


def test_an_open_claim_where_the_line_shows_no_reserves_is_not_charged():
    rows = [_claim(claim_number="A", reserved_amount=None, open_code="Open"),
            _claim(claim_number="B", reserved_amount=None, open_code="Closed")]
    assert _checks(rows) == []


def test_a_claim_whose_status_is_unknown_is_not_charged_for_a_reserve():
    rows = [_claim(claim_number="A", reserved_amount="500"), _claim(claim_number="B", reserved_amount="")]
    assert _checks(rows) == []


def test_an_open_claim_with_no_reserve_is_missing_one():
    rows = [_claim(claim_number="A", reserved_amount="0", open_code="C"),
            _claim(claim_number="B", reserved_amount="", open_code="O")]
    assert _found(rows) == [("B", cc.CHECK_RESERVE_MISSING)]
    assert _found([_claim(reserved_amount="NOT PROVIDED", open_code="Y")]) == \
        [("C-1", cc.CHECK_RESERVE_MISSING)]
    assert _found([_claim(reserved_amount="unknown", open_code="Open")]) == \
        [("C-1", cc.CHECK_RESERVE_MISSING)]
    assert _checks([_claim(reserved_amount="0", open_code="Open")]) == []


@pytest.mark.parametrize("value", ["None", "N/A"])
def test_an_open_claims_reserve_written_as_none_is_an_answer(value):
    rows = [_claim(claim_number="A", reserved_amount="500", open_code="Open"),
            _claim(claim_number="B", reserved_amount=value, open_code="Open")]
    assert _checks(rows) == []


# ── 4. incurred against its parts ────────────────────────────────────────────

def _money(**kw):
    base = dict(paid="8900", reserved_amount="0", expense="400", incurred="9300", open_code="Closed")
    base.update(kw)
    return [_claim(**base)]


@pytest.mark.parametrize("over, fires", [
    ({}, False),                                                      # adds up
    ({"incurred": "9301"}, False),                                    # rounding to the dollar
    ({"incurred": "9302"}, False),
    ({"paid": "8900.40", "expense": "400.40", "incurred": "9301"}, False),
    ({"incurred": "8900"}, False),                                    # loss-only incurred, expense beside it
    ({"incurred": "9303"}, True),
    ({"incurred": "9200"}, True),                                     # Brent's SIM-PKG-005
    ({"expense": None}, False),                                       # a part not stated: nothing to add up
    ({"expense": "NOT PROVIDED"}, False),
    ({"incurred": None}, False),
    ({"paid": ""}, False),
    ({"reserved_amount": None, "open_code": "Open"}, False),          # an open claim's reserve is unknown
    ({"reserved_amount": None, "open_code": "Closed"}, False),        # a closed claim holds 0: adds up
    ({"reserved_amount": None, "open_code": "Closed", "incurred": "9200"}, True),
    ({"subrogation_code": "Y", "incurred": "9200"}, False),           # net of a recovery
    ({"recovery": "500", "incurred": "9200"}, False),
    ({"recovery": "0", "incurred": "9200"}, True),
    ({"incurred": "-9200"}, False),                                   # a negative figure: not judged
    ({"incurred": "(9,200)"}, False),
    ({"incurred": "$9,300.00", "paid": "$8,900.00", "expense": "$400.00"}, False),
])
def test_incurred_must_be_paid_plus_reserve_plus_expense(over, fires):
    got = _checks(_money(**over))
    assert (cc.CHECK_INCURRED_MISMATCH in got) is fires, got


def test_a_missing_reserve_is_charged_once_never_also_as_an_incurred_mismatch():
    rows = [_claim(claim_number="A", reserved_amount="0", open_code="C"),
            _claim(claim_number="B", paid="18000", reserved_amount="", expense="1200",
                   incurred="27400", open_code="Open")]
    assert _found(rows) == [("B", cc.CHECK_RESERVE_MISSING)]


def test_the_extracted_amount_is_the_incurred():
    rows = [_claim(paid="8900", reserved_amount="0", expense="400", amount="9200", open_code="C")]
    assert _checks(rows) == [cc.CHECK_INCURRED_MISMATCH]


# ── 5. the vehicle a claim names ─────────────────────────────────────────────

@pytest.mark.parametrize("description", [
    "Insured van rear-ended a 2019 Ford Escape",                      # the claimant's car: no unit marker
    "V016 | 2014 Ford F150 SuperCrew | Alleged third-party bodily injury",
    "V009 | 2017 Chevy Express G2500 | Third-party vehicle property damage",   # "Chevy" = CHEVROLET
    "Unit 16 - 2014 FORD F-150",
    "V016 | 2018 Toyota Tacoma | Collision",                          # a make the schedule does not print
    "V016 | 2014 Ford F150 SuperCrew | rear-ended a 2019 Ford Escape",
    "Rev. 2018 Ford estimate attached",
    # Review fix (21 Oct): "vehicle N" / "Veh N" / "V2" is a police report's
    # numbering of the parties - the claimant as often as the insured.
    "Veh # 3, 2020 Ford Transit",
    "Insured vehicle 1 rear-ended vehicle 2 2018 Ford Transit",
    "V2 2018 Ford Transit 250 struck",
])
def test_a_vehicle_the_schedule_has_or_that_is_not_the_insureds_is_not_a_conflict(description):
    assert _checks([_claim(description=description)]) == []


@pytest.mark.parametrize("description", [
    "V016 | 2018 Ford Transit 250 | Alleged third-party bodily injury",   # Brent's SIM-AUTO-002
    "Unit 9: 2016 Chevrolet Express G2500",
    "Unit #3, 2020 Ford Transit",
])
def test_a_unit_described_as_a_vehicle_the_schedule_does_not_have_is_a_conflict(description):
    assert _checks([_claim(description=description)]) == [cc.CHECK_VEHICLE_NOT_SCHEDULED]


def test_the_vehicle_finding_names_the_unit_and_the_vehicle():
    rows = [_claim(description="V016 | 2018 Ford Transit 250 | Alleged third-party bodily injury")]
    f = cc.claim_findings(dict(_ctx(), loss_history=rows))[0]
    assert f["text"] == "names unit V016 as a 2018 Ford Transit 250, which is not on the vehicle schedule"


def test_a_vehicle_claim_outside_the_current_term_is_not_judged():
    # A vehicle sold before this term is a legitimate claim on a five-year loss run.
    rows = [_claim(date="06/01/2023", description="V016 | 2018 Ford Transit 250 | Collision")]
    assert _checks(rows) == []
    assert _checks([_claim(date="01/01/2026", description="V016 | 2018 Ford Transit | x")]) == []


def test_no_term_no_vehicle_schedule_or_a_liability_claim_is_not_judged():
    row = _claim(description="V016 | 2018 Ford Transit 250 | Collision")
    assert _checks([row], coverage_lines=[]) == []
    assert _checks([row], auto_vin_schedule=[]) == []
    assert _checks([dict(row, line_of_business="General Liability")]) == []


def test_a_term_comes_from_the_expiring_dates_when_no_policy_row_has_one():
    row = _claim(description="V016 | 2018 Ford Transit 250 | Collision")
    prior = {"prior_effective_date": "01/01/2025", "prior_expiration_date": "01/01/2026",
             "effective_date": "01/01/2027", "expiration_date": "01/01/2028"}
    assert _checks([row], coverage_lines=[], **prior) == [cc.CHECK_VEHICLE_NOT_SCHEDULED]
    assert cc.current_term({"coverage_lines": [{"effective_date": "x", "expiration_date": "y"}],
                            "effective_date": "06/01/2025", "expiration_date": "06/01/2026"}) == \
        (date(2025, 6, 1), date(2026, 6, 1))
    assert cc.current_term({"effective_date": "06/01/2026", "expiration_date": "06/01/2025"}) is None
    assert cc.current_term({}) is None


def test_a_vin_the_schedule_does_not_list_is_a_conflict_only_when_it_lists_vins():
    vins = [{"year": "2014", "make": "FORD", "model": "F150", "vin": "1FTFW1ET5DFC10312"}]
    on = _claim(description="Unit 4 | VIN 1FTFW1ET5DFC10312 | Collision")
    off = _claim(description="Unit 4 | VIN 1FTFW1ET5DFC99999 | Collision")
    assert _checks([on], auto_vin_schedule=vins) == []
    assert _checks([off], auto_vin_schedule=vins) == [cc.CHECK_VEHICLE_NOT_SCHEDULED]
    assert _checks([off]) == [], "a schedule with no VINs cannot say a VIN is missing from it"
    assert _checks([_claim(description="Claim 12345678901234567 collision")], auto_vin_schedule=vins) == []


def test_a_vehicle_field_of_its_own_needs_no_unit_marker():
    assert _checks([_claim(vehicle="2018 Ford Transit 250")]) == [cc.CHECK_VEHICLE_NOT_SCHEDULED]
    assert _checks([_claim(vehicle="2014 Ford F150")]) == []


# ── 6. the premises / building a claim names ─────────────────────────────────

def _prop(**kw):
    base = dict(line_of_business="Commercial Package")
    base.update(kw)
    return [_claim(**base)]


@pytest.mark.parametrize("description", [
    "Property | Prem 001, Bldg 002 (light steel) | Hail damage",
    "Property | Prem 001, Bldg 001 (frame) | Interior water damage",
    "Property | Location: 123 Main St | Hail damage",                 # a street, not a heading
    "Property | Hail damage at Prem 001 Bldg 3 roof",                  # a heading inside a sentence
    "General liability | Completed work damaged the customer's Building 3",
    "Property | Premium audit dispute",
    # Review fix (21 Oct): a heading read from a liability claim's description
    # is as often a jobsite as a scheduled premises - never judged.
    "General liability | Loc 5 | Slip and fall",
])
def test_a_premises_the_schedule_has_or_no_heading_at_all_is_not_a_conflict(description):
    assert _checks(_prop(description=description)) == []


@pytest.mark.parametrize("description, printed", [
    ("Property | Prem 001, Bldg 003 | Hail damage", "premises 001, building 003"),   # Brent's SIM-PKG-003
    ("Property | Prem 002, Bldg 001 | Hail damage", "premises 002, building 001"),
    ("Property | Loc 5 | Wind", "premises 5"),
    ("Property | Bldg 3 | Wind", "building 3"),
])
def test_a_premises_or_building_the_schedule_does_not_have_is_a_conflict(description, printed):
    found = cc.claim_findings(dict(_ctx(), loss_history=_prop(description=description)))
    assert [f["check"] for f in found] == [cc.CHECK_BUILDING_NOT_SCHEDULED]
    assert found[0]["text"] == f"names {printed}, which is not on the premises schedule"


def test_a_bare_building_number_on_a_liability_claim_is_never_read():
    assert _checks([_claim(line_of_business="General Liability", description="Building 3 | Slip and fall")]) == []


def test_the_schedule_is_read_from_merged_rows_and_from_a_raw_heading():
    raw = [{"address": "Prem. #: 001 Bldg #: 001", "building_number": "001"},
           {"address": "Prem. #: 001 Bldg #: 002", "building_number": "002"}]
    assert _checks(_prop(description="Property | Prem 001, Bldg 002 | x"), property_locations=raw) == []
    assert _checks(_prop(description="Property | Prem 001, Bldg 003 | x"), property_locations=raw) == \
        [cc.CHECK_BUILDING_NOT_SCHEDULED]


def test_a_schedule_that_numbers_nothing_cannot_be_contradicted():
    streets = [{"address": "4800 Dahlia St, Denver, CO 80216"}]
    assert _checks(_prop(description="Property | Prem 001, Bldg 003 | x"), property_locations=streets) == []
    only_locs = [{"location_number": "1"}, {"location_number": "2"}]
    assert _checks(_prop(description="Property | Prem 002, Bldg 009 | x"), property_locations=only_locs) == []
    assert _checks(_prop(description="Property | Prem 003, Bldg 001 | x"), property_locations=only_locs) == \
        [cc.CHECK_BUILDING_NOT_SCHEDULED]


def test_a_premises_claim_outside_the_term_or_with_its_own_fields():
    assert _checks(_prop(date="03/01/2022", description="Property | Prem 001, Bldg 003 | x")) == []
    assert _checks(_prop(description="Hail", location_number="001", building_number="003")) == \
        [cc.CHECK_BUILDING_NOT_SCHEDULED]


# ── 7. a WC claim's class code ───────────────────────────────────────────────

def _wc(description, **kw):
    return [_claim(line_of_business="Workers' Compensation", description=description, **kw)]


@pytest.mark.parametrize("description", [
    "5190 | Field electrician | Shoulder strain while lifting conduit",
    "2024 | Fell from ladder",                     # a leading year is never a class code
    "Strain lifting 5403 lbs of conduit",          # a number inside the sentence
    "8810-01 | Clerical | Slip",
])
def test_a_class_code_the_wc_rows_rate_or_no_code_at_all_is_not_a_conflict(description):
    assert _checks(_wc(description)) == []


@pytest.mark.parametrize("description", [
    "5403 | Field electrician | Fall from short ladder / ankle injury",   # Brent's SIM-WC-002
    "Class 5403 - carpentry strain",
    "Code: 5645 | framing",
])
def test_a_wc_class_code_the_policy_does_not_rate_is_a_conflict(description):
    assert _checks(_wc(description)) == [cc.CHECK_CLASS_NOT_SCHEDULED]


def test_a_class_code_on_another_line_or_without_wc_rows_or_out_of_term_is_not_judged():
    assert _checks([_claim(line_of_business="General Liability", description="5403 | slip")]) == []
    assert _checks(_wc("5403 | Field electrician"), wc_class_codes=[]) == []
    assert _checks(_wc("5403 | Field electrician", date="07/09/2023")) == []
    assert _checks(_wc("Strain", class_code="5403")) == [cc.CHECK_CLASS_NOT_SCHEDULED]


# ══════════════════════════════════════════════════════════════════════════════
# 3. Brent's file - CONTROL alone, CHALLENGE alone, on every path
# ══════════════════════════════════════════════════════════════════════════════

def _package_found(rows):
    facts, _flags = _package(rows)
    return {(f["claim_number"], f["check"]) for f in cc.claim_findings(facts)}


def test_the_control_claims_raise_nothing():
    assert _package_found(_every_field_rows("CONTROL")) == set()


def test_every_planted_mistake_is_found_in_the_challenge_claims():
    assert _package_found(_every_field_rows("CHALLENGE")) == _PLANTED


def test_both_copies_in_one_list_find_the_challenge_copy_only():
    """Review fix (21 Oct): the copies share claim numbers, so each claim is ONE
    claim (D69). SIM-WC-001's reserve is blank in the CHALLENGE copy and stated
    in the CONTROL copy: the package states it, so it is not missing. The
    "NOT PROVIDED" cells stay missing (a statement, not silence); the two
    copies' values are never compared (B2 is Brent's)."""
    rows = _every_field_rows("CONTROL") + _every_field_rows("CHALLENGE")
    facts, _flags = _package(rows)
    found = cc.claim_findings(facts)
    expected = _PLANTED - {("SIM-WC-001", cc.CHECK_RESERVE_MISSING)}
    assert {(f["claim_number"], f["check"]) for f in found} == expected
    assert len(found) == len(expected) == 8, "no claim is charged twice for being in the file twice"


def test_the_extracted_shape_finds_all_but_what_extraction_does_not_capture():
    # RULE 7 has no expense and no date first made: those two need extraction
    # (owner's call - no prompt change in this build).
    assert _package_found(_extracted_rows("CONTROL")) == set()
    assert _package_found(_extracted_rows("CHALLENGE")) == _PLANTED - _NEEDS_EXTRACTION


def test_the_findings_name_each_claim_by_number_and_loss_date():
    facts, _flags = _package(_every_field_rows("CHALLENGE"))
    labels = {f["label"] for f in cc.claim_findings(facts)}
    assert {
        "SIM-AUTO-003 (11/02/2025) was reported 10/24/2025, before its loss date",
        "SIM-PKG-005 (10/02/2025) shows incurred $9,200, but paid + reserve + expense is $9,300",
        "SIM-AUTO-002 (08/20/2025) names unit V016 as a 2018 Ford Transit 250, which is not on the "
        "vehicle schedule",
        "SIM-PKG-003 (06/28/2025) names premises 001, building 003, which is not on the premises schedule",
        "SIM-WC-002 (07/09/2025) shows class code 5403, which is not on the workers comp class schedule "
        "(5190, 8742, 8810)",
        "SIM-PKG-002 (05/06/2025) has no report date",
        "SIM-CYB-001 (10/11/2025) has no report date",
        "SIM-EPL-001 (04/10/2025) has no date first made",
        "SIM-WC-001 (02/19/2025) is open with no reserve",
    } == labels
    assert not any(d in label for label in labels for d in _EM)


def test_a_claim_with_no_number_is_named_by_its_loss_date_and_line():
    rows = [_claim(claim_number=None, date="11/02/2025", claim_date="10/24/2025")]
    f = cc.claim_findings(dict(_ctx(), loss_history=rows))[0]
    assert f["label"] == "The 11/02/2025 Business Auto claim was reported 10/24/2025, before its loss date"
    assert f["claim"] == "the 11/02/2025 Business Auto claim"


@needs_node
def test_the_table_path_imports_brents_file_and_the_checks_read_it(tmp_path):
    """The real frontend import (header found, aliases, dates) into the loss
    table's real columns, then the backend validation and the checks."""
    o = _node(tmp_path, f"""
const loss = {json.dumps(_cols("loss_history"))};
const m = await S.parseXLSX(file({json.dumps(str(_CLAIMS_XLSX))}, 'claims.xlsx'));
const r = S.rowsFromMatrix(m, loss);
out({{used: r.usedHeader, unmatched: r.unmatched, rows: r.rows}});
""")
    assert o["used"] is True and len(o["rows"]) == 24
    # first_made_date has its own column since 25 Oct 2026 (the claims checks' fields).
    assert set(o["unmatched"]) == {"dataset", "insured", "carrier_reference", "synthetic_claim_id",
                                   "expense_usd", "incurred_usd", "is_simulated"}
    first = o["rows"][0]
    assert first == {"date": "03/13/2025", "line_of_business": "Business Auto",
                     "description": "V009 | 2017 Chevrolet Express G2500 | Third-party vehicle property damage",
                     "paid": "12000", "reserved_amount": "0", "claim_date": "03/15/2025", "open_code": "Closed",
                     "first_made_date": "", "expense": "", "incurred": "", "claim_number": ""}
    clean, report = sc.validate_rows("loss_history", o["rows"])
    stored = sc.rows_for_facts("loss_history", clean)
    control, challenge = stored[:12], stored[12:]
    assert _package_found(control) == set()
    facts, _flags = _package(challenge)
    found = cc.claim_findings(facts)
    # The table has a "Date first made" column since 25 Oct 2026, so the table
    # path now also sees the "NOT PROVIDED" first-made date.
    assert {f["check"] for f in found} == ({c for _n, c in _PLANTED - _NEEDS_EXTRACTION}
                                           | {"first_made_date_missing"})
    assert len(found) == 8       # + the first-made date (its own column since 25 Oct 2026)
    # No claim number column (no ACORD 125 box): the table's claims are named by date.
    assert "The 11/02/2025 Business Auto claim was reported 10/24/2025, before its loss date" in \
        {f["label"] for f in found}
    # The two "NOT PROVIDED" report dates fail the date column's format check
    # (advisory) and are kept as typed.
    assert {k for e in report["errors"].values() for k in e} == {"claim_date", "first_made_date"}


# ══════════════════════════════════════════════════════════════════════════════
# 4. The score - deductions, never stops; one card; points add up
# ══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=1)
def _three_scores():
    out = {}
    for name, rows in (("none", []), ("control", _every_field_rows("CONTROL")),
                       ("challenge", _every_field_rows("CHALLENGE"))):
        facts, flags = _package(rows, core=True)
        out[name] = json.dumps(_score(facts, flags), default=str)
    return out


def _pkg_of(name):
    return json.loads(_three_scores()[name])


def test_the_control_claims_cost_nothing_and_the_challenge_claims_cost_both_pillars():
    none, control, challenge = _pkg_of("none"), _pkg_of("control"), _pkg_of("challenge")
    assert control["pillars"] == none["pillars"] and control["raw_sqs_score"] == none["raw_sqs_score"]
    exp = challenge["category_breakdown"]["exposure_consistency"]
    assert exp["claims"]["label"] == "Claims" and exp["claims"]["deducted"] == cc.CLAIM_CONFLICT_CAP == 15
    assert "claims" not in control["category_breakdown"]["exposure_consistency"]
    assert challenge["pillars"]["exposure_consistency"] == none["pillars"]["exposure_consistency"] - 15
    cov_n = none["category_breakdown"]["structural_completeness"]["coverage_details"]
    cov_c = challenge["category_breakdown"]["structural_completeness"]["coverage_details"]
    assert cov_c["deducted"] - cov_n["deducted"] == 4 * cc.CLAIM_MISSING_POINTS == 8
    assert challenge["pillars"]["structural_completeness"] == none["pillars"]["structural_completeness"] - 8
    assert set(cov_c["missing"]) - set(cov_n["missing"]) == {
        "SIM-PKG-002 (05/06/2025) has no report date", "SIM-CYB-001 (10/11/2025) has no report date",
        "SIM-EPL-001 (04/10/2025) has no date first made", "SIM-WC-001 (02/19/2025) is open with no reserve"}
    assert challenge["raw_sqs_score"] < control["raw_sqs_score"]
    assert challenge["score_trace"]["reconciles"] is True


def test_a_pillar_at_its_floor_lists_the_missing_claims_but_takes_nothing_more():
    """On the seven decs alone (no application answers) Structural is 0: the
    claims' missing details are listed on Coverage Details, its score moves,
    and the pillar - which never goes below 0 - does not."""
    out = {}
    for name, rows in (("none", []), ("challenge", _every_field_rows("CHALLENGE"))):
        facts, flags = _package(rows)
        out[name] = _score(facts, flags)
    n, c = out["none"], out["challenge"]
    assert n["pillars"]["structural_completeness"] == c["pillars"]["structural_completeness"] == 0
    cov_n = n["category_breakdown"]["structural_completeness"]["coverage_details"]
    cov_c = c["category_breakdown"]["structural_completeness"]["coverage_details"]
    assert cov_c["deducted"] == cov_n["deducted"] and cov_c["score"] == cov_n["score"] - 8
    assert "SIM-WC-001 (02/19/2025) is open with no reserve" in cov_c["missing"]
    assert c["pillars"]["exposure_consistency"] == n["pillars"]["exposure_consistency"] - 15
    assert c["score_trace"]["reconciles"] is True


def test_the_claims_hold_no_cap_and_raise_no_stop():
    control, challenge = _pkg_of("control"), _pkg_of("challenge")
    for key in ("cap_applied", "cap_reason", "open_hard_stops", "ready_blockers", "cap_hard_stops"):
        assert challenge.get(key) == control.get(key), key
    facts_c, flags = _package(_every_field_rows("CONTROL"))
    facts_x, _f = _package(_every_field_rows("CHALLENGE"))
    assert sq.evaluate_stops(facts_x, flags) == sq.evaluate_stops(facts_c, flags)


def test_both_pillar_rows_open_the_loss_table_and_name_every_claim():
    rows = [r for r in _pkg_of("challenge")["top_recommendations"] if r.get("field") == "loss_history"]
    assert sorted(r["pillar"] for r in rows) == ["exposure_consistency", "structural_completeness"]
    for r in rows:
        assert r["answer_mode"] == "schedule" and r["schedule_key"] == "loss_history"
        for number, _check in _PLANTED:
            assert number in r["action"], (number, r["pillar"])
        assert r["action"].startswith("Correct these claims in the loss history: ")
        assert "Complete these claims in the loss history: " in r["action"]
        assert not any(d in r["action"] for d in _EM)
    by = {r["pillar"]: r for r in rows}
    assert len(by["exposure_consistency"]["missing"]) == 5
    assert len(by["structural_completeness"]["missing"]) == 4
    from services.review_recommendations import fix_route_for_row
    assert fix_route_for_row(by["exposure_consistency"]) == {"mode": "schedule", "schedule_key": "loss_history"}


def test_no_finding_is_charged_twice():
    facts, flags = _package(_every_field_rows("CHALLENGE"))
    found = cc.claim_findings(facts)
    keys = [(f["claim_number"], f["check"]) for f in found]
    assert len(keys) == len(set(keys))
    exp = sq.exposure_deduction_items(facts, flags, [], [])
    comp = sq.completeness_deduction_items(facts, flags, [], [])
    assert {i["label"] for i in exp} & {i["label"] for i in comp} == set()
    claims_exp = [i for i in exp if i["bucket"] == "claims"]
    claims_comp = [i for i in comp if i["bucket"] == "claims"]
    assert {i["kind"] for i in claims_exp} == {"conflict"} and {i["kind"] for i in claims_comp} == {"missing"}
    assert sum(i["points"] for i in claims_exp) == 15 and sum(i["points"] for i in claims_comp) == 8


@pytest.mark.parametrize("n_conflicts, n_missing", [(1, 0), (3, 1), (5, 4), (20, 0), (0, 30), (16, 7)])
def test_the_points_are_capped_per_kind_and_shared_evenly(n_conflicts, n_missing):
    rows = [_claim(claim_number=f"X{i}", date="11/02/2025", claim_date="10/24/2025") for i in range(n_conflicts)]
    rows += [_claim(claim_number=f"M{i}", claim_date="NOT PROVIDED") for i in range(n_missing)]
    items = cc.claim_deduction_items(dict(_ctx(), loss_history=rows))
    conflict = [i["points"] for i in items if i["kind"] == "conflict"]
    missing = [i["points"] for i in items if i["kind"] == "missing"]
    assert sum(conflict) == min(cc.CLAIM_CONFLICT_CAP, cc.CLAIM_CONFLICT_POINTS * n_conflicts)
    assert sum(missing) == min(cc.CLAIM_MISSING_CAP, cc.CLAIM_MISSING_POINTS * n_missing)
    for pts in (conflict, missing):
        assert not pts or max(pts) - min(pts) <= 1
    assert all(i["fact"] == "loss_history" and i["bucket"] == "claims" for i in items)
    if n_conflicts + n_missing > 10:
        assert items[0]["row_action"].endswith(
            f"And {n_conflicts + n_missing - 10} more claims to check.")


def test_the_share_on_the_card_is_what_fixing_the_table_adds():
    """One number per field (`_unify_card_points` / `_share_out_gains`): both
    rows carry the same share, and it is the score's own lift."""
    facts, flags = _package(_every_field_rows("CHALLENGE"), core=True)
    pkg = _score(facts, flags, share_out=True)
    rows = [r for r in pkg["top_recommendations"] if r.get("field") == "loss_history"]
    gains = {r.get("answer_gain") for r in rows}
    assert len(gains) == 1
    assert gains.pop() == _pkg_of("control")["raw_sqs_score"] - pkg["raw_sqs_score"]


def test_the_share_is_exact_beside_an_attested_no_losses_conflict():
    """Adversarial: the door's placeholder probe ("Yes" for a table) DELETED the
    claims, and with an attested "no losses" beside them that also lifted Loss
    History's 45 conflict cap - the card promised +10 where correcting the
    claims adds +6. The probe is now the same claims marked answered."""
    scores = {}
    for name, rows in (("control", _every_field_rows("CONTROL")), ("challenge", _every_field_rows("CHALLENGE"))):
        facts, flags = _package(rows, core=True)
        facts["loss_history_no_prior_losses_indicator"] = "Yes"
        scores[name] = _score(facts, flags, share_out=(name == "challenge"))
    # The conflict holds - since 23 Oct 2026 at min(45, the value once the claims
    # are confirmed), the owner's "never above the honest answer".
    assert scores["control"]["pillars"]["loss_history_alignment"] <= 45, "the conflict cap holds"
    rows = [r for r in scores["challenge"]["top_recommendations"] if r.get("field") == "loss_history"]
    assert {r.get("answer_gain") for r in rows} == {
        scores["control"]["raw_sqs_score"] - scores["challenge"]["raw_sqs_score"]}


def test_the_probe_mark_is_read_only_by_the_checks_and_never_saved():
    rows = _every_field_rows("CHALLENGE")
    facts = dict(_ctx(), loss_history=rows)
    probed = cc.probe_answer(facts)
    assert all(r[cc.PROBE_MARK] is True for r in probed) and not any(cc.PROBE_MARK in r for r in rows)
    assert cc.claim_findings(dict(facts, loss_history=probed)) == []
    from services.loss_history_state import asserted_claims, claim_rows
    assert len(claim_rows(probed)) == len(claim_rows(rows)) == 12
    assert asserted_claims({"loss_history": probed}) == asserted_claims({"loss_history": rows})
    clean, _report = sc.validate_rows("loss_history", probed)
    assert not any(cc.PROBE_MARK in r for r in sc.rows_for_facts("loss_history", clean))
    assert cc.probe_answer({"loss_history": "Yes"}) == "Yes" and cc.probe_answer({}) is None


@needs_node
def test_the_pre_form_screen_shares_add_up_and_the_recommendations_card_names_the_claims(tmp_path):
    facts, flags = _package(_every_field_rows("CHALLENGE"), core=True)
    row = {"facts": facts, "flags": flags, "docs": [], "recommendations": []}
    pkg = sq.current_package_sqs(row, "t-claims", "u")
    kd = sq.key_details(row["facts"], row["flags"])
    pkg2, _kd2 = sq.complete_screen_shares(row, "t-claims", "u", pkg, kd)
    shown = (sum(int(v[0]) for v in (pkg2.get("screen_shares") or {}).values())
             + sum(int(v[0]) for v in (pkg2.get("screen_card_points") or {}).values())
             + sum(int(v[0]) for v in (pkg2.get("screen_dc_points") or {}).values())
             + sum(int(u["points"]) for u in (pkg2.get("screen_unanswerable") or [])))
    assert shown == 100 - pkg2["package_sqs_score"]
    share = pkg2["screen_shares"]["loss_history"][0]
    assert share >= 1
    from services.review_recommendations import with_fix_routes
    routed = with_fix_routes(pkg2, facts)
    o = _node(tmp_path, f"""
const m = R.buildRecommendations({{ packageSqs: {json.dumps(routed, default=str)}, groupedIssues: null,
  keyDetails: null, attention: null, formsExist: false }});
out(m.score.filter((s) => s.keys.includes('table:loss_history')));
""")
    assert len(o) == 1, "two pillar rows, one table: one card"
    card = o[0]
    assert card["resolution"] == {"mode": "schedule", "schedule_key": "loss_history"}
    assert card["points"]["points"] == share
    for number, _check in _PLANTED:
        assert number in card["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. The loss table and its import
# ══════════════════════════════════════════════════════════════════════════════

def test_the_two_new_columns_are_last_and_bind_live_acord_125_boxes():
    cols = [c["key"] for c in sc.SCHEDULE_DEFS["loss_history"]["columns"]]
    assert cols[:5] == ["date", "line_of_business", "description", "paid", "reserved_amount"]
    assert cols[5:7] == ["claim_date", "open_code"]
    # 25 Oct 2026: the claims checks' own fields, appended after (position imports).
    assert cols[7:] == ["first_made_date", "expense", "incurred", "claim_number"]
    schema = json.loads((_BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text(encoding="utf-8"))
    from services.pdf_service import _SCHEDULE_REGISTRY
    bound = {d.sub_key for base, d in _SCHEDULE_REGISTRY.items()
             if d.list_key == "loss_history" and f"{base}_A" in schema}
    assert {"claim_date", "open_code"} <= bound
    # The insured may state when a claim was reported and whether it is open;
    # the carrier's own figures (first made, expense, incurred, claim #) are the
    # producer's (Z42 review A).
    _po = {c["key"] for c in sc.SCHEDULE_DEFS["loss_history"]["columns"] if c.get("producer_only")}
    assert _po == {"first_made_date", "expense", "incurred", "claim_number"}


def test_a_save_now_keeps_the_report_date_and_status_a_document_gave_the_claim():
    extracted = [{"date": "03/13/2025", "claim_date": "03/15/2025", "description": "Collision",
                  "paid": "12000", "reserved_amount": "0", "line_of_business": "Auto",
                  "open_code": "C", "claim_number": "A-1", "amount": "12000"}]
    table = sc.rows_from_facts("loss_history", {"loss_history": extracted})
    assert table[0]["claim_date"] == "03/15/2025" and table[0]["open_code"] == "C"
    clean, _report = sc.validate_rows("loss_history", table)
    saved = sc.merge_saved_rows("loss_history", extracted, clean)
    assert saved[0]["claim_date"] == "03/15/2025" and saved[0]["open_code"] == "C"


@needs_node
def test_a_header_less_claims_list_still_imports_by_position(tmp_path):
    o = _node(tmp_path, f"""
const loss = {json.dumps(_cols("loss_history"))};
out(S.rowsFromMatrix([['03/15/2022', 'General Liability', 'Slip and fall', '8500', '2000']], loss));
""")
    assert o["usedHeader"] is False
    assert o["rows"] == [{"date": "03/15/2022", "line_of_business": "General Liability",
                          "description": "Slip and fall", "paid": "8500", "reserved_amount": "2000",
                          "claim_date": "", "open_code": "", "first_made_date": "", "expense": "",
                          "incurred": "", "claim_number": ""}]


@needs_node
def test_a_status_cell_never_reads_as_a_header(tmp_path):
    # "Open" / "Outstanding" are a status CELL's words: no bare alias for them.
    o = _node(tmp_path, f"""
const loss = {json.dumps(_cols("loss_history"))};
const m = [['Claims list'], ['Loss Date', 'Status', 'Reserve USD', 'Description'],
           ['01/02/2025', 'Open', '500', 'Slip'], ['02/03/2025', 'Outstanding', '0', 'Wind'],
           ['03/04/2025', 'Open', '100', 'Open']];
const r = S.rowsFromMatrix(m, loss);
out({{header: r.headerRow, n: r.rows.length, inside: r.skippedInside, status: r.rows.map((x) => x.open_code)}});
""")
    assert o == {"header": 1, "n": 3, "inside": 0, "status": ["Open", "Outstanding", "Open"]}


@needs_node
def test_the_wider_aliases_never_send_a_header_to_another_table(tmp_path):
    o = _node(tmp_path, f"""
const defs = {json.dumps(json.loads(json.dumps(sc.SCHEDULE_DEFS)))};
const head = ['Description', 'Status', 'Date Reported', 'Paid USD', 'Reserve USD', 'Description Asset'];
const res = {{}};
for (const k of Object.keys(defs)) res[k] = S.mapHeaders(head, defs[k].columns).mapping;
out(res);
""")
    assert o["loss_history"] == {"description": 0, "open_code": 1, "claim_date": 2, "paid": 3,
                                 "reserved_amount": 4}
    assert o["wc_class_codes"] == {"description": 0}
    for other in ("auto_vin_schedule", "auto_drivers", "property_locations", "wc_officers"):
        assert not ({"open_code", "claim_date", "paid", "reserved_amount"} & set(o.get(other) or {}))


def test_the_alias_table_has_no_dashes_and_the_module_none_in_its_words():
    src = (_FRONT / "utils" / "scheduleImport.js").read_text(encoding="utf-8")
    block = src[src.index("const HEADER_ALIASES = {"):src.index("export function headerCandidates")]
    assert not any(d in block for d in _EM)
    mod = (_BACKEND / "services" / "claim_checks.py").read_text(encoding="utf-8")
    assert not any(d in mod for d in _EM)


# ══════════════════════════════════════════════════════════════════════════════
# 6. The form - the table's status prints as ACORD's Y / N
# ══════════════════════════════════════════════════════════════════════════════

def test_the_typed_status_prints_y_or_n_in_the_claim_open_box():
    from services import pdf_service as ps
    schema = json.loads((_BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text(encoding="utf-8"))
    facts = {"applicant_name": "X LLC", "loss_history": [
        {"date": "03/13/2025", "claim_date": "03/15/2025", "line_of_business": "Business Auto",
         "description": "Collision with a parked car", "paid": "12000", "reserved_amount": "0",
         "open_code": "Closed"},
        {"date": "08/20/2025", "claim_date": "08/21/2025", "line_of_business": "Business Auto",
         "description": "Alleged bodily injury", "paid": "4500", "reserved_amount": "34500",
         "open_code": "Open"}]}
    mapped, _conf = ps.map_facts_to_form(facts, schema, "ACORD_125", raw_text="", allow_llm=False)
    assert mapped.get("LossHistory_ClaimStatus_OpenCode_A") == "N"
    assert mapped.get("LossHistory_ClaimStatus_OpenCode_B") == "Y"
    assert mapped.get("LossHistory_ClaimDate_A") == "03/15/2025"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Review fixes (21 Oct, lane C review) - each finding reproduced, then fixed
# ══════════════════════════════════════════════════════════════════════════════

# ── R1. The same claim held twice is ONE claim (D69) ─────────────────────────

_EARLY = dict(claim_number="88213", date="11/02/2025", claim_date="10/24/2025")


@pytest.mark.parametrize("second", [
    dict(_EARLY),                                                    # identical
    dict(_EARLY, claim_number="88213 "),                             # a trailing space
    dict(_EARLY, claim_number="88-213"),                             # punctuation
    dict(_EARLY, line_of_business="Auto"),                           # "Auto" vs "Business Auto"
    dict(_EARLY, claim_number=None, line_of_business="Auto"),        # a numberless copy
])
def test_the_same_claim_held_twice_is_found_and_charged_once(second):
    rows = [_claim(**_EARLY), _claim(**second)]
    assert _checks(rows) == [cc.CHECK_REPORT_BEFORE_LOSS]
    items = cc.claim_deduction_items(dict(_ctx(), loss_history=rows))
    assert [i["points"] for i in items] == [cc.CLAIM_CONFLICT_POINTS]
    assert items[0]["row_action"].count("88213") == 1


def test_two_different_claims_with_the_same_slip_are_both_charged():
    rows = [_claim(**_EARLY), _claim(**dict(_EARLY, claim_number="88214"))]
    assert _found(rows) == [("88213", cc.CHECK_REPORT_BEFORE_LOSS), ("88214", cc.CHECK_REPORT_BEFORE_LOSS)]
    rows = [_claim(**_EARLY), _claim(**dict(_EARLY, date="12/02/2025", claim_number=None))]
    assert len(_checks(rows)) == 2, "another loss date is another claim"


def test_a_numberless_row_joins_a_numbered_claim_only_when_one_claim_fits():
    # Two numbered claims on the date and line: the numberless row is its own.
    rows = [_claim(**_EARLY), _claim(**dict(_EARLY, claim_number="88214")),
            _claim(**dict(_EARLY, claim_number=None))]
    assert len(_checks(rows)) == 3


def test_a_blank_detail_is_not_missing_when_another_copy_of_the_claim_states_it():
    dated = _claim(claim_number="A", claim_date="06/03/2025")
    rows = [dated, _claim(claim_number="B", claim_date="06/05/2025"), _claim(claim_number="B")]
    assert _checks(rows) == []
    # A copy that SAYS "not provided" is still missing (a statement, not silence).
    rows = [dated, _claim(claim_number="B", claim_date="06/05/2025"),
            _claim(claim_number="B", claim_date="NOT PROVIDED")]
    assert _found(rows) == [("B", cc.CHECK_REPORT_DATE_MISSING)]
    # A blank with no copy stating it stays missing.
    assert _found([dated, _claim(claim_number="B")]) == [("B", cc.CHECK_REPORT_DATE_MISSING)]


def test_an_open_claims_blank_reserve_stated_by_another_copy_is_not_missing():
    rows = [_claim(claim_number="A", reserved_amount="500", open_code="O"),
            _claim(claim_number="B", reserved_amount="800", open_code="O"),
            _claim(claim_number="B", reserved_amount="", open_code="O")]
    assert _checks(rows) == []
    rows = rows[:1] + rows[2:]
    assert _found(rows) == [("B", cc.CHECK_RESERVE_MISSING)]


# ── R2. A partial vehicle schedule never raises "not on the schedule" ─────────

_TRANSIT_CLAIM = "V016 | 2018 Ford Transit 250 | Alleged third-party bodily injury"


@pytest.mark.parametrize("schedule", [
    [{"year": "2014", "make": "FORD", "model": "F150"}, {"year": "", "make": "FORD", "model": "TRANSIT 250"}],
    [{"year": "2014", "make": "FORD", "model": "F150"}, {"year": None, "make": "FORD", "model": None}],
    [{"year": "2014", "make": "FORD", "model": "F150"}, {"year": "2018", "make": "", "model": ""}],
    [{"year": "2014", "make": "FORD", "model": "F150"}, {"vin": "1FTFW1ET5DFC10312"}],          # VIN only
    [{"year": "2014", "make": "FORD", "model": "F150"}, {"cost_new": "41,800", "class_code": "01499"}],
])
def test_a_schedule_row_that_may_be_the_claims_vehicle_stands_the_check_down(schedule):
    assert _checks([_claim(description=_TRANSIT_CLAIM)], auto_vin_schedule=schedule) == []


def test_an_empty_schedule_row_is_no_vehicle_and_a_stated_difference_still_counts():
    schedule = [{"year": "2014", "make": "FORD", "model": "F150"},
                {"year": None, "make": None, "model": None, "vin": None}, {}]
    assert _checks([_claim(description=_TRANSIT_CLAIM)], auto_vin_schedule=schedule) == \
        [cc.CHECK_VEHICLE_NOT_SCHEDULED]
    # Another make with no year rules nothing in for a Ford.
    schedule = [{"year": "2014", "make": "FORD"}, {"year": "", "make": "CHEVROLET"}]
    assert _checks([_claim(description=_TRANSIT_CLAIM)], auto_vin_schedule=schedule) == \
        [cc.CHECK_VEHICLE_NOT_SCHEDULED]


def test_a_vin_is_judged_only_when_every_scheduled_vehicle_has_one():
    claim = _claim(description="Unit 4 | VIN 1FTFW1ET5DFC99999 | Collision")
    one = [{"year": "2014", "make": "FORD", "vin": "1FTFW1ET5DFC10312"},
           {"year": "2017", "make": "CHEVROLET", "vin": None}]
    assert _checks([claim], auto_vin_schedule=one) == []
    both = [one[0], dict(one[1], vin="1GCWGAFP5H1234567")]
    assert _checks([claim], auto_vin_schedule=both) == [cc.CHECK_VEHICLE_NOT_SCHEDULED]


def test_the_same_model_in_another_year_is_still_a_unit_the_schedule_lacks():
    """Not taken from the review: a fleet runs many vans of one model (Choice
    Electric schedules six Express G2500s, 2001 to 2017), so a 2016 Express is
    a unit the schedule does not have - standing down on a model match would
    hide exactly the contradiction Brent planted."""
    fleet = [{"year": str(y), "make": "CHEVROLET", "model": "EXPRESS G2500"} for y in (2013, 2015, 2017)]
    assert _checks([_claim(description="Unit 9: 2016 Chevrolet Express G2500")], auto_vin_schedule=fleet) == \
        [cc.CHECK_VEHICLE_NOT_SCHEDULED]
    assert _checks([_claim(description="Unit 9: 2015 Chevrolet Express G2500")], auto_vin_schedule=fleet) == []


# ── R3. A partly numbered premises schedule ──────────────────────────────────

@pytest.mark.parametrize("schedule, description", [
    ([{"premises_number": "001", "building_number": "001"},
      {"premises_number": "001", "building_number": "", "address_line1": "4800 Dahlia St"}],
     "Property | Prem 001, Bldg 002 | Hail"),                                  # the review's shape
    ([{"premises_number": "001", "building_number": "001"}, {"address": "4800 Dahlia St, Denver, CO"}],
     "Property | Prem 001, Bldg 002 | Hail"),                                  # a row with no numbers
    ([{"premises_number": "001", "building_number": "001"}, {"address": "4800 Dahlia St, Denver, CO"}],
     "Property | Prem 002 | Hail"),                                            # a premises, unnumbered row
    ([{"premises_number": "001", "building_number": "001"}, {"premises_number": "002", "building_number": ""}],
     "Property | Prem 002, Bldg 004 | Hail"),
])
def test_a_premises_row_that_may_be_the_claims_building_stands_the_check_down(schedule, description):
    assert _checks(_prop(description=description), property_locations=schedule) == []


def test_a_fully_numbered_premises_still_contradicts_and_another_premises_too():
    schedule = [{"premises_number": "001", "building_number": "001"},
                {"premises_number": "002", "building_number": ""}]
    # Premises 3 is on no row, and every row numbers its premises.
    assert _checks(_prop(description="Property | Prem 003, Bldg 001 | Hail"), property_locations=schedule) == \
        [cc.CHECK_BUILDING_NOT_SCHEDULED]
    # Premises 1 numbers every building: building 3 is not there (Brent's).
    assert _checks(_prop(description="Property | Prem 001, Bldg 003 | Hail")) == [cc.CHECK_BUILDING_NOT_SCHEDULED]


# ── R4. Blanking a "NOT PROVIDED" does not clear the charge in a person's table

def _persons_table(rows):
    facts = dict(_ctx(), loss_history=rows)
    sc.mark_human_rows(facts, "loss_history", "producer")
    return facts


def test_a_blanked_report_date_in_a_saved_table_is_still_missing():
    rows = [r for r in _every_field_rows("CHALLENGE") if r["claim_number"] in ("SIM-CYB-001", "SIM-AUTO-001")]
    for r in rows:
        if r["claim_number"] == "SIM-CYB-001":
            r["claim_date"] = ""                          # the flagged cell, cleared
    facts, _f = _package(rows)
    assert cc.claim_findings(facts) == [], "the documents' rows: Cyber prints no report dates"
    sc.mark_human_rows(facts, "loss_history", "producer")
    assert [(f["claim_number"], f["check"]) for f in cc.claim_findings(facts)] == \
        [("SIM-CYB-001", cc.CHECK_REPORT_DATE_MISSING)]


def test_a_saved_table_with_no_report_dates_or_a_changed_table_is_not_charged():
    rows = [_claim(claim_number="A"), _claim(claim_number="B", line_of_business="Cyber")]
    assert cc.claim_findings(_persons_table(rows)) == []
    rows = [_claim(claim_number="A", claim_date="06/03/2025"), _claim(claim_number="B", line_of_business="Cyber")]
    facts = _persons_table(rows)
    assert [f["check"] for f in cc.claim_findings(facts)] == [cc.CHECK_REPORT_DATE_MISSING]
    # A document re-merge wrote over the person's table: the line rule again.
    facts["loss_history"] = rows + [_claim(claim_number="C", line_of_business="Cyber")]
    assert cc.claim_findings(facts) == []


def test_a_saved_tables_open_claim_with_no_reserve_is_judged_over_the_table():
    rows = [_claim(claim_number="A", reserved_amount="500", open_code="O"),
            _claim(claim_number="B", line_of_business="Cyber", reserved_amount="", open_code="O")]
    assert _checks(rows) == []
    assert [f["check"] for f in cc.claim_findings(_persons_table(rows))] == [cc.CHECK_RESERVE_MISSING]


# ── R5. A premises number is a heading, never a word inside a sentence ────────

@pytest.mark.parametrize("line, description", [
    ("Commercial Package", "Property | Slip and fall at customer location 3"),
    ("Commercial Package", "Property | Hail damage reported at building 4 of the plant"),
    ("Commercial Package", "Property | Loc 000 | Wind"),             # a policy-level code
    ("Commercial Package", "Property | Prem 000, Bldg 000 | Wind"),
    ("Commercial Package", "Loc 000 | Slip and fall"),
    ("General Liability", "Slip and fall at customer location 3"),
    ("General Liability", "Loc 7 | Slip and fall"),
    ("Business Auto", "Loc 7 | Collision in the yard"),
    ("Workers' Compensation", "5190 | Loc 7 | Strain"),
])
def test_a_premises_word_inside_a_sentence_or_on_another_line_is_never_read(line, description):
    assert _checks([_claim(line_of_business=line, description=description)]) == []


def test_a_claims_own_location_fields_are_judged_on_any_line():
    gl = _claim(line_of_business="General Liability", description="Slip and fall",
                location_number="009")
    assert _checks([gl]) == [cc.CHECK_BUILDING_NOT_SCHEDULED]
    assert _checks([dict(gl, location_number="000")]) == []


# ── R6. The loss table merges on save: nothing a document gave is wiped ──────

_EXTRACTED = [
    {"date": "03/13/2025", "claim_date": "03/15/2025", "description": "Collision with a parked car",
     "amount": "12000", "paid": "12000", "reserved_amount": "0", "claim_number": "A-1",
     "line_of_business": "Business Auto", "open": False, "open_code": "C", "subrogation_code": "Y"},
    {"date": "08/20/2025", "claim_date": None, "description": "Alleged bodily injury", "amount": "39000",
     "paid": "4500", "reserved_amount": "34500", "claim_number": "A-2",
     "line_of_business": "Business Auto", "open": True, "open_code": "O", "subrogation_code": "N"},
]


def _save(edit, facts=None, source="producer"):
    """The real door: the table as served, edited, validated, written."""
    from services.arq_service import _write_schedule_rows
    facts = facts if facts is not None else {"loss_history": copy.deepcopy(_EXTRACTED)}
    table = sc.rows_from_facts("loss_history", facts)
    table = edit(table)
    clean, _report = sc.validate_rows("loss_history", table)
    _write_schedule_rows(facts, "loss_history", clean, source)
    return facts


def test_the_loss_table_carries_a_hidden_row_identity():
    assert "loss_history" in sc.MERGE_ON_SAVE
    table = sc.rows_from_facts("loss_history", {"loss_history": _EXTRACTED})
    assert [r[sc.ROW_ID_KEY] for r in table] == ["#0", "#1"]
    assert not any(sc.ROW_ID_KEY in r for r in sc.rows_for_facts("loss_history", table))


def test_a_save_keeps_the_claim_number_incurred_and_subrogation():
    def edit(t):
        t[1]["claim_date"] = "08/21/2025"
        return t
    rows = _save(edit)["loss_history"]
    assert [r["claim_number"] for r in rows] == ["A-1", "A-2"]
    assert [r["subrogation_code"] for r in rows] == ["Y", "N"]
    assert [r["amount"] for r in rows] == ["12000", "39000"]
    assert rows[1]["claim_date"] == "08/21/2025" and not any(sc.ROW_ID_KEY in r for r in rows)


def test_after_a_save_the_card_still_names_the_claim_by_its_number():
    def edit(t):
        t[1]["claim_date"] = "08/01/2025"                     # before the 08/20 loss
        return t
    facts = _save(edit)
    facts.update({k: v for k, v in _ctx().items()})
    assert [(f["claim_number"], f["check"]) for f in cc.claim_findings(facts)] == \
        [("A-2", cc.CHECK_REPORT_BEFORE_LOSS)]


def test_acord_125_still_prints_the_subrogation_after_a_save():
    from services import pdf_service as ps
    schema = json.loads((_BACKEND / "forms_schemas" / "ACORD_125_schema.json").read_text(encoding="utf-8"))

    def edit(t):
        t[0]["description"] = "Collision with a parked car in the lot"
        return t
    facts = dict(_save(edit), applicant_name="X LLC")
    mapped, _conf = ps.map_facts_to_form(facts, schema, "ACORD_125", raw_text="", allow_llm=False)
    assert mapped.get("LossHistory_ClaimStatus_SubrogationCode_A") == "Y"
    assert mapped.get("LossHistory_ClaimStatus_SubrogationCode_B") == "N"


def test_a_typed_paid_or_reserve_or_status_drops_the_figure_derived_from_it():
    def edit(t):
        t[0]["paid"] = "12500"
        t[1]["open_code"] = "Closed"
        return t
    rows = _save(edit)["loss_history"]
    assert "amount" not in rows[0], "the document's incurred no longer adds up"
    assert rows[0]["claim_number"] == "A-1" and rows[0]["subrogation_code"] == "Y"
    assert rows[1]["amount"] == "39000" and "open" not in rows[1] and rows[1]["open_code"] == "Closed"
    assert cc._status(rows[1]) == "closed"


def test_a_cleared_row_is_deleted_a_dropped_row_too_and_a_new_row_is_added():
    def clear(t):
        for k in list(t[0]):
            if k != sc.ROW_ID_KEY:
                t[0][k] = ""
        return t
    assert [r["claim_number"] for r in _save(clear)["loss_history"]] == ["A-2"]
    assert [r["claim_number"] for r in _save(lambda t: t[1:])["loss_history"]] == ["A-2"]

    def add(t):
        return t + [{"date": "01/05/2026", "line_of_business": "General Liability", "description": "Slip"}]
    rows = _save(add)["loss_history"]
    assert [r.get("claim_number") for r in rows] == ["A-1", "A-2", None]


def test_a_row_that_showed_nothing_from_the_start_is_kept():
    stored = copy.deepcopy(_EXTRACTED) + [{"claim_number": "A-3", "amount": "900"}]
    rows = _save(lambda t: t, facts={"loss_history": stored})["loss_history"]
    assert [r["claim_number"] for r in rows] == ["A-1", "A-2", "A-3"]


def test_a_client_save_merges_too():
    def edit(t):
        t[1]["reserved_amount"] = "30000"
        return t
    rows = _save(edit, source="client_arq")["loss_history"]
    assert rows[1]["claim_number"] == "A-2" and rows[1]["reserved_amount"] == "30000"
    assert "amount" not in rows[1]


def test_an_import_without_ids_keeps_a_claims_hidden_fields_by_date_and_line():
    stored = copy.deepcopy(_EXTRACTED)
    typed = [{k: v for k, v in r.items() if k != sc.ROW_ID_KEY}
             for r in sc.rows_from_facts("loss_history", {"loss_history": stored})]
    typed[1]["claim_date"] = "08/21/2025"
    clean, _r = sc.validate_rows("loss_history", typed)
    rows = sc.merge_saved_rows("loss_history", stored, clean)
    assert [r["claim_number"] for r in rows] == ["A-1", "A-2"] and rows[1]["claim_date"] == "08/21/2025"
    # Two typed rows on one date and line identify nothing (Brent's two copies).
    # (A second copy typed without a claim number - the number is a column since 25 Oct.)
    dup = typed + [dict(typed[1], description="Alleged bodily injury - second copy", claim_number="")]
    clean, _r = sc.validate_rows("loss_history", dup)
    rows = sc.merge_saved_rows("loss_history", stored, clean)
    assert len(rows) == 3 and rows[0]["claim_number"] == "A-1"
    assert sum(1 for r in rows if r.get("claim_number") == "A-2") == 1


# ── R7. The real extraction rows the repo holds raise nothing ────────────────

def _fixture_facts():
    out = []

    def walk(o):
        if isinstance(o, dict):
            lh = o.get("loss_history")
            lh = lh.get("value") if isinstance(lh, dict) and "value" in lh else lh
            if isinstance(lh, list) and lh:
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for path in sorted(_FIX.glob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")))
    return out


def test_the_live_extraction_rows_in_the_fixtures_raise_no_finding():
    found = _fixture_facts()
    assert found, "the fixtures hold live loss-run rows (policy_by_line_live_17sep)"
    for facts in found:
        assert cc.claim_findings(facts) == [], facts.get("loss_history")
        assert cc.claim_findings(dict(_ctx(), **facts)) == []


# ── R8. The small misreads ───────────────────────────────────────────────────

def test_the_line_of_the_schedule_sets_the_term_not_every_policy():
    lines = [{"line": "Cyber", "effective_date": "01/01/2022", "expiration_date": "01/01/2023"},
             {"line": "Commercial Auto", "effective_date": "01/01/2025", "expiration_date": "01/01/2026"}]
    sold = _claim(date="06/01/2022", description=_TRANSIT_CLAIM)
    assert _checks([sold], coverage_lines=lines) == []
    assert _checks([dict(sold, date="06/01/2025")], coverage_lines=lines) == [cc.CHECK_VEHICLE_NOT_SCHEDULED]
    assert cc.current_term({"coverage_lines": lines}) == (date(2022, 1, 1), date(2026, 1, 1))
    assert cc.current_term({"coverage_lines": lines}, "auto") == (date(2025, 1, 1), date(2026, 1, 1))
    # No row of the line and the policies disagree: the package's own term.
    assert cc.current_term({"coverage_lines": lines}, "workers_comp") is None
    assert cc.current_term({"coverage_lines": lines, "prior_effective_date": "03/01/2025",
                            "prior_expiration_date": "03/01/2026"}, "workers_comp") == \
        (date(2025, 3, 1), date(2026, 3, 1))
    wc = [{"line": "Workers' Compensation", "effective_date": "01/01/2022", "expiration_date": "01/01/2023"},
          lines[1]]
    assert _checks(_wc("5403 | Field electrician", date="06/01/2025"), coverage_lines=wc) == []
    assert _checks(_wc("5403 | Field electrician", date="06/01/2022"), coverage_lines=wc) == \
        [cc.CHECK_CLASS_NOT_SCHEDULED]


def test_a_report_date_of_n_a_is_missing_where_the_line_prints_report_dates():
    for value in ("N/A", "None", "n/a"):
        rows = [_claim(claim_number="A", claim_date="06/03/2025"), _claim(claim_number="B", claim_date=value)]
        assert _found(rows) == [("B", cc.CHECK_REPORT_DATE_MISSING)], value
        assert _checks([_claim(claim_date=value)]) == [], "a line that prints none"


@pytest.mark.parametrize("description, text", [
    ("Unit 3 2019 Ford Focus hit pole", "names unit 3 as a 2019 Ford Focus"),
    ("UNIT #3 2019 FORD FOCUS HIT POLE", "names unit 3 as a 2019 FORD FOCUS"),
    ("Unit 9: 2016 Chevrolet Express G2500 backed into gate", "names unit 9 as a 2016 Chevrolet Express G2500"),
    (_TRANSIT_CLAIM, "names unit V016 as a 2018 Ford Transit 250"),
    ("V-016 2018 Ford Transit 250", "names unit V016 as a 2018 Ford Transit 250"),
])
def test_the_card_names_the_unit_once_and_only_the_vehicle(description, text):
    f = cc.claim_findings(dict(_ctx(), loss_history=[_claim(description=description)]))
    assert [x["text"] for x in f] == [f"{text}, which is not on the vehicle schedule"]
