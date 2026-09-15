"""Live run 9 (session 07bb6d10, 15 Sep 2026, Orbin policy only).

1. ACORD 127 USE ticked SERVICE: extraction returned auto_vehicle_use =
   "service" (a word the package prints 292 times, so it passed the text
   check) while the auto dec's own cell prints "USE: NA".
2. "Policies in this submission" titled the auto policy with a coverage part,
   "COVERED AUTOS LIABILITY", instead of its line name.
"""
import json
import os

import pytest

import services.pdf_service as ps
import services.extraction_service as es

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = ps._SCHED_SKIP
_AUTO = "6E7-40-02---26"
_EMCC = "EMPLOYERS MUTUAL CASUALTY COMPANY"


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _dec(label, value, section="ITEM THREE - SCHEDULE OF COVERED AUTOS YOU OWN"):
    return {"label": label, "value": value, "section": section, "owner": "policy",
            "policy_number": _AUTO, "line_of_business": "Commercial Auto"}


# Run 9's literal vehicle and the dec's own USE cell.
_VEHICLE = {"year": "2012", "make": "SUBARU", "model": "OUTBACK SEDAN", "vin": "4S4BRCGC9C3217772",
            "body_type": "PRIV PASSENGER", "comp_symbol": "07", "coll_symbol": "07", "class_code": "7383",
            "territory": "111"}
_USE_NA = _dec("USE", "NA")
_BOXES = [f"Vehicle_Use_{b}Indicator_A" for b in ("Service", "Commercial", "Retail", "Pleasure", "Farm",
                                                   "ForHire", "Other")]


def _facts(use=None, source="ai", entries=(_USE_NA,)):
    f = {"auto_vin_schedule": [dict(_VEHICLE)], "dec_page_entries": list(entries), "_form_id": "ACORD_127"}
    if use is not None:
        f["auto_vehicle_use"] = {"value": use, "source": source, "confidence": "ai_high"}
    return f


def _ticks(facts):
    return {b: ps._resolve_vehicle_use_indicator(b, facts) for b in _BOXES}


# ── 1. The 127 USE set ───────────────────────────────────────────────────────

def test_the_decs_own_na_beats_an_inferred_use():
    assert set(_ticks(_facts("service")).values()) == {None}


def test_a_use_class_the_dec_prints_decides_over_the_fact():
    got = _ticks(_facts("commercial", entries=[_dec("USE", "SERVICE")]))
    assert got["Vehicle_Use_ServiceIndicator_A"] == "Yes"
    assert got["Vehicle_Use_CommercialIndicator_A"] == "No"


@pytest.mark.parametrize("source", ["producer", "client_arq"])
def test_a_persons_answer_wins_over_the_dec_cell(source):
    got = _ticks(_facts("commercial", source=source))
    assert got["Vehicle_Use_CommercialIndicator_A"] == "Yes"


def test_without_a_dec_cell_the_fact_stands():
    assert _ticks(_facts("service", entries=()))["Vehicle_Use_ServiceIndicator_A"] == "Yes"


def test_two_different_use_cells_place_nothing():
    got = _ticks(_facts("service", entries=[_dec("USE", "SERVICE"), _dec("USE", "COMMERCIAL")]))
    assert set(got.values()) == {None}


def test_an_unreadable_cell_leaves_the_fact_to_decide():
    assert _ticks(_facts("service", entries=[_dec("USE", "ZQX-9")]))["Vehicle_Use_ServiceIndicator_A"] == "Yes"


@pytest.mark.parametrize("source", ["user_confirmed", "cross_form_conflict"])
def test_a_producers_confirmation_is_a_persons_answer(source):
    got = _ticks(_facts("commercial", source=source, entries=[_dec("USE", "SERVICE")]))
    assert got["Vehicle_Use_CommercialIndicator_A"] == "Yes"


def test_one_cell_printed_twice_is_one_answer():
    cells = [_dec("USE", "SERVICE"), _dec("USE", "Service"), _dec("VEHICLE USE", "service")]
    assert _ticks(_facts(None, entries=cells))["Vehicle_Use_ServiceIndicator_A"] == "Yes"


@pytest.mark.parametrize("cell", ["N/A.", "N / A", "Not Applicable.", "NONE.", "-", "na"])
def test_every_printing_of_a_non_answer_is_a_non_answer(cell):
    assert set(_ticks(_facts("service", entries=[_dec("USE", cell)])).values()) == {None}


@pytest.mark.parametrize("fact", ["service", None])
def test_a_worded_use_the_table_does_not_know_is_other(fact):
    got = _ticks(_facts(fact, entries=[_dec("USE", "BUSINESS")]))
    assert got["Vehicle_Use_OtherIndicator_A"] == "Yes" and got["Vehicle_Use_ServiceIndicator_A"] == "No"


@pytest.mark.parametrize("cell", ["NOT FOR HIRE", "SEE SCHEDULE", "7383", "USE CLASS 01"])
def test_a_negation_reference_or_code_leaves_the_fact(cell):
    assert _ticks(_facts("service", entries=[_dec("USE", cell)]))["Vehicle_Use_ServiceIndicator_A"] == "Yes"


@pytest.mark.parametrize("value,expected", [("NA", ("na", "NA")), ("N/A.", ("na", "NA")), ("--", ("na", "NA")),
                                            ("7383", None), ("LIAB-I", None), ("C-1", None),
                                            ("NOT FOR HIRE", None), ("", None), (None, None),
                                            ("BUSINESS", ("other:business", "BUSINESS"))])
def test_use_cell_reading(value, expected):
    assert ps._use_cell_reading(value) == expected


def test_no_use_anywhere_is_an_owned_blank():
    assert set(_ticks(_facts(None, entries=())).values()) == {None}


def test_run9s_127_prints_no_use_box():
    facts = {k: v for k, v in _facts("service").items() if k != "_form_id"}
    m, _c = ps.map_facts_to_form(facts, _schema("ACORD_127"), form_id="ACORD_127", raw_text="USE: NA",
                                 pre_filled_gpt={"filled_values": {}, "raw_text_fields": set(),
                                                 "question_grounding": {}}, guard_report=[])
    assert not any(str(m.get(b) or "").strip().lower() == "yes" for b in _BOXES)


# ── 2. The policy list names the line ────────────────────────────────────────

def _row(line, number=_AUTO, premium=None):
    return {"line": line, "carrier": _EMCC, "naic": None, "policy_number": number, "premium": premium,
            "effective_date": "07/15/25", "expiration_date": "07/15/26"}


def test_the_policy_list_names_the_line_not_a_coverage_part():
    mf = {"coverage_lines": [_row("Covered Autos Liability", premium="$ 1,496.00"), _row("Commercial Auto"),
                             _row("Automobile", premium="$2,991.00")]}
    recs = [r for r in es._build_line_records(mf) if r["line"] == "auto"]
    assert len(recs) == 1
    assert recs[0]["line_printed"] != "Covered Autos Liability"
    assert ps._names_a_standard_line(recs[0]["line_printed"])


def test_with_no_line_name_the_longest_printing_still_titles_the_record():
    recs = es._build_line_records({"coverage_lines": [_row("Covered Autos Liability", premium="$ 1,496.00")]})
    assert [r["line_printed"] for r in recs] == ["Covered Autos Liability"]


@pytest.mark.parametrize("name,expected", [("Covered Autos Liability", False), ("Business Auto", True),
                                           ("Commercial General Liability", True), ("", False), (None, False)])
def test_names_a_standard_line(name, expected):
    assert ps._names_a_standard_line(name) is expected


def test_the_125_grid_still_keeps_the_lines_own_name():
    rows = [{"line": "Covered Autos Liability", "policy_number": _AUTO},
            {"line": "Business Auto", "policy_number": _AUTO}]
    assert [r["line"] for r in ps._dedupe_rows_by_policy_contract(rows)] == ["Business Auto"]
