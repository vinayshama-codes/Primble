"""Z37 lane C (24 Oct 2026) - four owner-approved fixes.

1. ACORD 141 is the Crime Section and ACORD 160 the Business Owners Section
   (their templates' own titles): labels and triggers.
2. ACORD 127 USE: a vehicle with its own stated use prints it; otherwise the
   policy-level use (15 Sep ruling). Never mixed.
3. A spreadsheet whose columns are a claims listing is typed loss_run.
4. The policies table marks a client's per-policy answer ("Client").
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from services import form_service as fs
from services import extraction_service as es
from services import pdf_service as ps
from services import cross_form_validator as cfv

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
FORMS_DB = Path(__file__).resolve().parents[1] / "forms_database"


def _recs(facts=None, flags=None, text=""):
    return {m["form_id"]: m for m in fs.match_forms_deterministic(facts or {}, flags or {}, text=text)}


# ── 1. ACORD 141 = Crime, ACORD 160 = Business Owners ────────────────────────

def test_metadata_names_the_templates_own_titles():
    a141 = json.loads((FORMS_DB / "ACORD_141.json").read_text())
    a160 = json.loads((FORMS_DB / "ACORD_160.json").read_text())
    assert a141["form_name"] == "ACORD 141 - Crime Section"
    assert a160["form_name"] == "ACORD 160 - Business Owners Section"
    assert "property" not in a141["coverage_types"] and "has_property_coverage" not in a141["matching_flags"]
    assert "inland_marine" not in a160["coverage_types"] and "has_inland_marine" not in a160["matching_flags"]
    src = Path(fs.__file__).read_text()
    assert '"ACORD 141 - Property Schedule"' not in src
    assert '"ACORD 160 - Inland Marine Application"' not in src


@pytest.mark.parametrize("flags,text", [
    ({"has_property_coverage": True, "has_multiple_locations": True}, ""),
    ({"has_property_coverage": True}, "agreed value coinsurance 90% replacement cost value"),
    ({"has_property_coverage": True}, "commercial property building limit $1,000,000 premium $4,000"),
])
def test_property_alone_never_offers_141(flags, text):
    assert "ACORD_141" not in _recs(flags=flags, text=text)


@pytest.mark.parametrize("facts,flags,text", [
    ({}, {"has_crime": True}, ""),
    ({"crime_coverage_decision": "Requested"}, {}, ""),
    ({"crime_coverage_decision": "Already carried"}, {}, ""),
    ({"crime_limit": "$250,000"}, {}, ""),
    ({}, {}, "commercial crime coverage limit $250,000 premium $800"),
    ({"coverage_lines": [{"line": "Commercial Crime", "carrier": "Chubb", "policy_number": "CR-1",
                          "premium": "$900"}]}, {}, ""),
])
def test_crime_exposure_offers_141_as_the_crime_section(facts, flags, text):
    rec = _recs(facts, flags, text).get("ACORD_141")
    assert rec and rec["form_name"] == "ACORD 141 - Crime Section"
    assert rec["for_line"] == "crime"


@pytest.mark.parametrize("facts", [
    {"crime_coverage_decision": "Declined", "crime_limit": "$250,000"},
    {"crime_coverage_decision": "Not applicable"},
    {"_lines_not_requested": ["crime"], "crime_limit": "$250,000"},
])
def test_a_declined_crime_line_offers_no_141(facts):
    assert "ACORD_141" not in _recs(facts, {"has_crime": True})


@pytest.mark.parametrize("flags,text,facts", [
    ({"has_inland_marine": True}, "inland marine contractor's equipment floater", {}),
    ({}, "installation floater tool floater motor truck cargo", {}),
    ({"has_inland_marine": True}, "", {"inland_marine_total_value": "$250,000"}),
])
def test_inland_marine_never_offers_160(flags, text, facts):
    assert "ACORD_160" not in _recs(facts, flags, text)


@pytest.mark.parametrize("facts,text", [
    ({"coverage_lines": [{"line": "Businessowners", "carrier": "Hartford", "policy_number": "BOP-1",
                          "premium": "$2,400"}]}, ""),
    ({"lines_of_business": ["Business Owners Policy"]}, ""),
    ({"bop_property_limit": "$500,000"}, ""),
    ({}, "businessowners coverage premium $2,400"),
])
def test_a_bop_line_offers_160_as_the_business_owners_section(facts, text):
    rec = _recs(facts, {}, text).get("ACORD_160")
    assert rec and rec["form_name"] == "ACORD 160 - Business Owners Section"


def test_a_denied_bop_row_offers_no_160():
    facts = {"coverage_lines": [{"line": "Businessowners", "premium": "Not Covered"}]}
    assert not fs.bop_line_present(facts)


def test_evidence_tables_follow_the_new_lines():
    assert fs._FORM_EVIDENCE_LINES["ACORD_141"] == frozenset({"crime"})
    assert "inland_marine" not in fs._FORM_EVIDENCE_LINES["ACORD_160"]
    assert [f for f, _ in fs._FORM_EVIDENCE_FACTS["ACORD_141"]["facts"]] == ["crime_limit", "crime_deductible"]
    assert fs._FORM_COVERAGE_GOAL["ACORD_141"] == "Crime"
    assert "ACORD_160" not in fs._CLASS_RELEVANT_FORMS["contractor"]


def test_the_inland_marine_overlap_warning_stands_down():
    facts = {"inland_marine_total_value": "$250,000", "property_bpp_value": "$250,000"}
    assert cfv._check_inland_marine_deduplication(
        facts, {"has_inland_marine": True}, {"ACORD_140", "ACORD_160"}) == []


# ── 2. Per-vehicle USE on ACORD 127 ──────────────────────────────────────────

VIN1, VIN2 = "1FTFW1ET5DFA00001", "1FTFW1ET5DFA00002"


def _docs(use1, use2):
    lines = [f"2019 FORD F150 VIN {VIN1}", f"USE: {use1}" if use1 else "CLASS 7398",
             "", f"2020 FORD TRANSIT VIN {VIN2}", f"USE: {use2}" if use2 else "CLASS 7398"]
    return [{"text": "\n".join(lines)}]


def _rows():
    return [{"year": "2019", "make": "FORD", "model": "F150", "vin": VIN1},
            {"year": "2020", "make": "FORD", "model": "TRANSIT", "vin": VIN2}]


def _ticks(facts, letter):
    return {b for b in ("Pleasure", "Farm", "Commercial", "Retail", "Service", "ForHire", "Other")
            if ps._resolve_vehicle_use_indicator(f"Vehicle_Use_{b}Indicator_{letter}", facts) == "Yes"}


def test_each_vehicle_prints_its_own_stated_use():
    mf = {"auto_vin_schedule": _rows()}
    es._read_vehicle_block_cells(mf, _docs("SERVICE", "COMMERCIAL"))
    rows = mf["auto_vin_schedule"]
    assert [r.get("use") for r in rows] == ["Service", "Commercial"]
    assert "auto_vehicle_use" not in mf             # two readings: no policy-level use
    assert _ticks(mf, "A") == {"Service"} and _ticks(mf, "B") == {"Commercial"}


def test_a_vehicle_with_its_own_use_never_takes_the_policy_one():
    # The policy-level use is a person's answer (one block reading would
    # otherwise become the policy use - the existing 15 Sep rule).
    mf = {"auto_vin_schedule": _rows(), "auto_vehicle_use": {"value": "Pleasure", "source": "producer"}}
    es._read_vehicle_block_cells(mf, _docs("SERVICE", None))
    assert _ticks(mf, "A") == {"Service"}           # its own
    assert _ticks(mf, "B") == {"Pleasure"}          # no use of its own: the policy's


def test_a_vehicles_own_na_is_an_owned_blank_not_the_policy_use():
    # The policy use is the documents' own: a vehicle's NA is an owned blank.
    mf = {"auto_vin_schedule": _rows(), "auto_vehicle_use": {"value": "Service", "source": "ai"}}
    es._read_vehicle_block_cells(mf, _docs("NA", "COMMERCIAL"))
    assert ps._resolve_vehicle_use_indicator("Vehicle_Use_ServiceIndicator_A", mf) is None
    assert _ticks(mf, "B") == {"Commercial"}
    # Review of Z37 (24 Oct): a PERSON's policy-level answer is never blanked by
    # a document's "USE: NA" (the 15 Sep ruling); a real per-vehicle use still wins.
    mf = {"auto_vin_schedule": _rows(), "auto_vehicle_use": {"value": "Service", "source": "producer"}}
    es._read_vehicle_block_cells(mf, _docs("NA", "COMMERCIAL"))
    assert _ticks(mf, "A") == {"Service"}
    assert _ticks(mf, "B") == {"Commercial"}


def test_no_vehicle_use_keeps_the_policy_level_use_on_every_row():
    mf = {"auto_vin_schedule": _rows(), "auto_vehicle_use": {"value": "Service", "source": "ai"}}
    es._read_vehicle_block_cells(mf, _docs(None, None))
    assert all("use" not in r for r in mf["auto_vin_schedule"])
    assert _ticks(mf, "A") == {"Service"} and _ticks(mf, "B") == {"Service"}


def test_a_use_already_on_the_row_is_kept():
    rows = _rows()
    rows[0]["use"] = "Retail"
    mf = {"auto_vin_schedule": rows}
    es._read_vehicle_block_cells(mf, _docs("SERVICE", None))
    assert mf["auto_vin_schedule"][0]["use"] == "Retail"


def test_an_unrecognised_own_use_prints_in_other():
    mf = {"auto_vin_schedule": _rows()}
    es._read_vehicle_block_cells(mf, _docs("CONTRACTOR", "SERVICE"))
    assert _ticks(mf, "A") == {"Other"}
    assert ps._resolve_vehicle_use_other_description("Vehicle_Use_OtherDescription_A", mf) == "Contractor"
    assert ps._resolve_vehicle_use_other_description("Vehicle_Use_OtherDescription_B", mf) is None


# ── 3. A spreadsheet claims listing is a loss run ────────────────────────────

_DL = Path.home() / "Downloads"


@pytest.mark.parametrize("name", ["Choice_Electric_Loss_Runs_2021-2024_TEST.csv",
                                  "Choice_Electric_Loss_Runs_Current_TEST.csv"])
def test_the_real_loss_run_csvs_without_their_title(name):
    path = _DL / name
    if not path.exists():
        pytest.skip("test CSV not on this machine")
    from utils.spreadsheet_text import csv_text
    text = csv_text(str(path)).replace("LOSS RUN REPORT - TEST DATA", "Report")
    cls = es.classify_document(text, filename=name)
    assert cls["doc_type"] == "loss_run" and cls["source"] == "spreadsheet_columns"


@pytest.mark.parametrize("header", [
    "Claim Number | Date of Loss | Description | Paid | Reserve | Incurred",
    "Policy Number | Claim # | Loss Date | Status | Total Incurred",
    "Carrier | Claim No | DOL | Paid Loss | Outstanding",
    "Claim | Accident Date | Vehicle | Paid | Reserves",
])
def test_a_claims_listing_header_is_typed_loss_run(header):
    text = header + "\nC-1 | 03/15/2024 | x | 1000 | 0 | 1000"
    assert es.classify_document(text, filename="claims.xlsx")["doc_type"] == "loss_run"


@pytest.mark.parametrize("text", [
    "Year | Make | Model | VIN | Cost New\n2019 | Ford | F150 | 1FT | 40000",
    "Driver | Date of Birth | License Number | Claims | Paid\nA | 1/1/80 | X1 | 0 | 0",
    "Location | Address | Building Value | BPP\n1 | 1 Main | 100000 | 5000",
    "Claim | Notes\nC-1 | none",                     # no amount column
])
def test_schedules_and_partial_headers_are_not_loss_runs(text):
    assert es.classify_document(text, filename="sheet.xlsx")["doc_type"] != "loss_run"


def test_only_a_spreadsheet_is_read_by_its_columns():
    text = "Claim Number | Date of Loss | Paid | Reserve | Incurred"
    assert es.spreadsheet_claims_listing(text)
    assert es.classify_document(text, filename="claims.pdf")["source"] != "spreadsheet_columns"
    assert es.is_spreadsheet_document("Sheet: Claims\n" + text, None)


# ── 4. The policies table's "Client" mark ────────────────────────────────────

_HELPER = FRONTEND / "utils" / "policyClientMarks.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_client_mark_helper(tmp_path):
    script = tmp_path / "check.mjs"
    script.write_text(f"""
import * as M from {json.dumps(_HELPER.as_uri())};
const row = {{ client_fields: ["policy_number", "carrier_naic"], policy_number: "BA-1", carrier_naic: "",
               carrier_name: "Amerisure", effective_date: "01/01/2026" }};
console.log(JSON.stringify({{
  policy: M.clientMarked(row, "policy"), naic: M.clientMarked(row, "naic"),
  carrier: M.clientMarked(row, "carrier"), term: M.clientMarked(row, "term"),
  added: M.clientMarked({{ ...row, producer_added: true }}, "policy"),
  none: M.clientMarked({{ policy_number: "X" }}, "policy"), text: M.CLIENT_MARK_TEXT }}));
""", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert out == {"policy": True, "naic": False, "carrier": False, "term": False,
                   "added": False, "none": False, "text": "Client"}


def test_the_table_renders_the_mark_in_each_answerable_cell():
    jsx = (FRONTEND / "components" / "form" / "review" / "PoliciesTable.jsx").read_text()
    for col in ("carrier", "naic", "policy", "term", "premium"):
        assert f'<ClientMark r={{r}} column="{col}" />' in jsx
    assert "—" not in (FRONTEND / "utils" / "policyClientMarks.js").read_text()


def test_a_policy_with_no_written_client_answer_has_no_client_field():
    # A held (disagreeing) client answer is never written to the store
    # (`policy_lines.judge` -> HOLD), so the row lists no client field and the
    # cell keeps the documents' value. Written answers: test_build23.
    from services import policy_lines as pl
    rows = [{"line": "Commercial Auto", "carrier": "Amerisure", "policy_number": "BA-1", "premium": "$1"}]
    row = pl.table_rows({"coverage_lines": rows})[0]
    assert row["client_fields"] == [] and row["policy_number"] == "BA-1"


# ── Review fixes (24 Oct 2026) ──────────────────────────────────────────────

def test_the_business_owners_people_are_not_a_bop_line():
    wc = "officers / business owners: john smith, president, 100% owner, excluded, payroll $52,000"
    assert not fs.bop_line_present({}, wc)
    assert fs.bop_line_present({}, "business owners policy declarations premium $2,400")


def test_a_crime_limit_of_none_offers_no_crime_form():
    assert not fs.crime_line_present({"crime_limit": "None"}, {}, "")
    assert not fs.crime_line_present({"crime_limit": "N/A"}, {}, "")
    assert fs.crime_line_present({"crime_limit": "$25,000"}, {}, "")


def test_a_claims_made_column_is_not_a_claims_listing():
    sheet = ("Sheet: Schedule\nLine | Carrier | Policy # | Claims Made / Occurrence | Premium | Paid in Full\n"
             "GL | Travelers | X1 | Occurrence | 5000 | Y")
    assert not es.spreadsheet_claims_listing(sheet)
    assert es.spreadsheet_claims_listing("Sheet: L\nClaim # | Date of Loss | Paid | Reserve\n1 | 1/1/2024 | 100 | 0")


def test_a_persons_policy_use_outranks_a_documents_na_cell():
    facts = {"auto_vin_schedule": [{"vin": "X", "use": "Na", "use_source": "vehicle_block"},
                                   {"vin": "Y", "use": "Commercial", "use_source": "vehicle_block"}],
             "auto_vehicle_use": {"value": "Service", "source": "producer"}}
    assert ps._vehicle_use_statement("A", facts) == "Service"
    assert ps._vehicle_use_statement("B", facts) == "Commercial"      # a real use of its own
    facts["auto_vehicle_use"] = {"value": "Service", "source": "ai"}
    assert ps._vehicle_use_statement("A", facts) is None
    assert ps._vehicle_use_statement("B", facts) == "Commercial"
