"""Choice Electric round 4 (7 Oct 2026) - the CARDS workstream.

1. A COPE card on a package with 2+ location rows opens the location table -
   every COPE card, coded or legacy, pre-form or editor - with the package-level
   items it still misses riding along as typed fields (Brent #18). Reverses
   round 3's "occupancy-only keeps field mode".
2. Recommendation-card reasons: a reason fact belongs to the card's own line
   (ACORD 160 printed a Cyber limit), money prints as money (ACORD 127
   "1,000,000"), and a one-building figure on a 2+ building package prints the
   buildings' total (ACORD 140 printed building 1 alone).
3. The vehicle and driver tables MERGE on save like the location table: a field
   the table has no column for (class code, territory, a driver's relationship)
   is never dropped, and a row is matched by hidden id, identical cells, then a
   UNIQUE VIN / licence number / name + date of birth - never an ambiguous one.

Values are generic stand-ins shaped like the client's session (no client data).
"""

import copy
import json
import os

import pytest

from services import form_service as fs
from services import schedule_capture as sc
from services.issue_registry import (
    build_grouped_view, make_issue, resolution_for,
)
from services.premises_cope import COPE_CARD_CODES, PER_BUILDING_COPE, route_cope_resolution

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMAS = os.path.join(os.path.dirname(_HERE), "forms_schemas")


def _schema(form_id: str) -> dict:
    with open(os.path.join(_SCHEMAS, f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ── 1. COPE cards on a 2+ building package ───────────────────────────────────

def _two_buildings(**package) -> dict:
    """Two buildings at one premises, building 1's figures copied to the
    package facts (the live shape: the package scalar is building 1)."""
    facts = {
        "property_locations": [
            {"location_id": "L1", "location_number": "1", "building_number": "1",
             "premises_label": "Prem. #: 001 Bldg #: 001",            # street redacted (live)
             "construction_type": "FRAME", "building_value": "$700,000", "bpp_value": "$50,000"},
            {"location_id": "L2", "location_number": "1", "building_number": "2",
             "premises_label": "Prem. #: 001 Bldg #: 002",
             "construction_type": "NON-COMBUSTIBLE", "building_value": "$400,000",
             "bpp_value": "$50,000"},
        ],
        "construction_type": "FRAME", "property_building_value": "$700,000",
        "property_bpp_value": "$50,000",
    }
    facts.update(package)
    return facts


def _items(view: dict) -> list:
    clusters = list(view["hard_stops"]) + [c for t in view["warnings"].values() for c in t]
    return [i for c in clusters for i in c["items"]]


def _card(facts: dict, code: str, severity: str = "hard_stop") -> dict:
    msg = {"minimum_viable_cope_missing": "Property submission missing Minimum Viable COPE: occupancy type",
           "carrier_grade_cope_incomplete": "Carrier-Grade COPE detail incomplete - missing: year built"}[code]
    issue = make_issue(code, severity, msg, ["ACORD_140"])
    hard, soft = ([msg], []) if severity == "hard_stop" else ([], [msg])
    return _items(build_grouped_view([issue], hard, soft, facts=facts))[0]["resolution"]


def test_live_shape_occupancy_only_card_is_a_field_window_with_just_occupancy():
    # The live card: only occupancy missing. REVERSED 21 Oct 2026 (Brent 17 Oct
    # item 8, build item b-cope-one-store): it opened the WHOLE two-building
    # table for one submission-wide dropdown - the TEST pinned the 7 Oct rule,
    # which Brent's "ask only what is missing" replaces. It is a field window
    # with just the occupancy box - still never building 1's construction /
    # values as the package's (the round-4 defect: no per-building box at all).
    res = _card(_two_buildings(), "minimum_viable_cope_missing")
    assert res["mode"] == "field"
    assert res["facts"] == ["occupancy_type"]
    assert set(res["controls"]) == {"occupancy_type"} and res["controls"]["occupancy_type"]["options"]
    assert "schedule_key" not in res and "columns" not in res


@pytest.mark.parametrize("code", sorted(COPE_CARD_CODES))
def test_no_per_building_fact_is_ever_one_package_box_on_two_buildings(code):
    base = resolution_for(code)
    for package in ({}, {"occupancy_type": "Office"},
                    {"occupancy_type": "Office", "year_built": "1990", "valuation_method": "RCV"}):
        facts = _two_buildings(**package)
        res = route_cope_resolution(code, copy.deepcopy(base), facts)
        assert not set(res.get("facts") or []) & set(PER_BUILDING_COPE)
        asked = [f for f in base["facts"] if f in PER_BUILDING_COPE]
        # Ask only what is missing (21 Oct 2026, Brent 17 Oct item 8 - the TEST
        # pinned "every asked column, stated or not"): the per-building items
        # the package still misses; with only package-level items missing, a
        # field window; with nothing missing, never an empty window.
        missing = [f for f in asked if not facts.get(f)]
        package_missing = [f for f in base["facts"] if f not in PER_BUILDING_COPE and not package.get(f)]
        if missing:
            assert res["mode"] == "schedule"
            assert res["columns"] == [PER_BUILDING_COPE[f] for f in missing]
        elif package_missing:
            assert res["mode"] == "field" and res["facts"] == package_missing
        else:
            assert res["mode"] == "schedule"
            assert res["columns"] == [PER_BUILDING_COPE[f] for f in asked]
        # every package-level item still missing rides along, nothing stated does
        for f in base["facts"]:
            if f in PER_BUILDING_COPE:
                continue
            stated = bool(package.get(f))
            assert (f in (res.get("facts") or [])) is (not stated)


@pytest.mark.parametrize("code", sorted(COPE_CARD_CODES))
def test_one_building_cards_stay_byte_identical(code):
    base = resolution_for(code)
    for rows in (None, [], [{"location_id": "L1", "construction_type": "FRAME"}]):
        facts = {"occupancy_type": None}
        if rows is not None:
            facts["property_locations"] = rows
        assert route_cope_resolution(code, base, facts) is base


def test_other_codes_and_modes_and_bad_input_pass_through():
    facts = _two_buildings()
    for code in ("per_location_cope_incomplete", "auto_um_uim_not_specified", None, ""):
        res = resolution_for(code) if code else {"mode": "field", "facts": ["year_built"]}
        assert route_cope_resolution(code, res, facts) is res
    sched = {"mode": "schedule", "schedule_key": "property_locations"}
    assert route_cope_resolution("minimum_viable_cope_missing", sched, facts) is sched
    for bad in (None, "x", 5):
        assert route_cope_resolution("minimum_viable_cope_missing", bad, facts) == bad
    base = resolution_for("minimum_viable_cope_missing")
    assert route_cope_resolution("minimum_viable_cope_missing", base, None) is base
    # never a per-building column on a card that asks no per-building fact
    only_pkg = {"mode": "field", "facts": ["occupancy_type"]}
    assert route_cope_resolution("legacy_minimum_viable_cope", only_pkg, facts) is only_pkg


def test_the_legacy_hard_stop_twin_routes_too():
    msg = ("Property Minimum Viable COPE incomplete - missing: occupancy type "
           "Fix: Review and correct this before proceeding.")
    from services.issue_registry import build_structured_from_sources
    view = build_grouped_view(build_structured_from_sources(legacy_hard=[msg]), [msg], [],
                              facts=_two_buildings())
    res = [i for i in _items(view) if "COPE" in i["message"]][0]["resolution"]
    # Only occupancy missing: just that box (21 Oct 2026, Brent 17 Oct item 8 -
    # the TEST pinned the whole-table window his item reverses).
    assert res["mode"] == "field" and res["facts"] == ["occupancy_type"]
    # one building: the legacy twin's own field card
    one = _two_buildings()
    one["property_locations"] = one["property_locations"][:1]
    view1 = build_grouped_view(build_structured_from_sources(legacy_hard=[msg]), [msg], [], facts=one)
    res1 = [i for i in _items(view1) if "COPE" in i["message"]][0]["resolution"]
    assert res1 == resolution_for("legacy_minimum_viable_cope")


def test_answering_the_typed_fact_and_saving_the_table_clears_the_card():
    from services.arq_service import _write_schedule_rows
    from services.sqs_service import evaluate_stops
    flags = {"has_property_coverage": True}
    facts = _two_buildings(locations=["1 Main St, Lowell, MI 49331"])
    hard, soft = evaluate_stops(facts, flags)
    assert any("Minimum Viable COPE incomplete - missing: occupancy" in m for m in hard + soft)
    # the modal: the typed fact first, then the table (one building edited)
    facts["occupancy_type"] = {"value": "Contractor shop or yard", "source": "producer",
                               "confidence": "filled"}
    rows = sc.rows_from_facts("property_locations", facts)
    rows[1]["year_built"] = "2001"
    clean, _ = sc.validate_rows("property_locations", rows)
    _write_schedule_rows(facts, "property_locations", clean, "producer")
    hard, soft = evaluate_stops(facts, flags)
    assert not any("Minimum Viable COPE" in m for m in hard + soft)
    assert facts["property_locations"][1]["year_built"] == "2001"
    assert facts["property_locations"][1]["building_value"] == "$400,000"


# ── 2. Recommendation-card reasons ───────────────────────────────────────────

def test_every_reason_fact_belongs_to_its_cards_line():
    from services.lob_canon import fact_line_family
    for form_id, spec in fs._FORM_EVIDENCE_FACTS.items():
        lines = fs._FORM_EVIDENCE_LINES.get(form_id)
        for key, _label in spec["facts"]:
            fam = fact_line_family(key)
            if fam is None:
                continue
            assert lines, f"{form_id} shows a {fam} fact but declares no line"
            assert fam in lines, f"{form_id} shows {key} ({fam}) - not one of {sorted(lines)}"


def test_160_never_prints_another_lines_value():
    # Z37 (24 Oct 2026): ACORD 160 is the Business Owners section - its
    # evidence is the BOP values, never inland marine / cyber / umbrella.
    facts = {"cyber_limit": "$1,000,000", "umbrella_limit": "$5,000,000",
             "inland_marine_total_value": "250000"}
    assert fs._build_trigger_facts("ACORD_160", facts) == ([], None)
    facts["bop_property_limit"] = "250000"
    trig, suffix = fs._build_trigger_facts("ACORD_160", facts)
    assert suffix == "BOP property limit: $250,000"
    assert [t["code"] for t in trig] == ["bop_property_limit"]


def test_a_misdeclared_fact_is_refused_at_run_time(monkeypatch):
    monkeypatch.setitem(fs._FORM_EVIDENCE_FACTS, "ACORD_127",
                        {"combine": False, "facts": [("cyber_limit", "Cyber limit"),
                                                     ("auto_liability_limit", "Auto liability limit")]})
    trig, suffix = fs._build_trigger_facts("ACORD_127", {"cyber_limit": "$1,000,000",
                                                         "auto_liability_limit": "$1,000,000"})
    assert suffix == "Auto liability limit: $1,000,000"
    assert [t["code"] for t in trig] == ["auto_liability_limit"]


@pytest.mark.parametrize("raw,shown", [
    ("1,000,000", "$1,000,000"), ("1000000", "$1,000,000"), ("$ 1,000,000", "$1,000,000"),
    ("$1,000,000", "$1,000,000"), ("1,000,000.00", "$1,000,000"),
    ("CSL 1,000,000", "CSL 1,000,000"),                      # not a bare amount: as written
    ("1,000,000 / 2,000,000", "1,000,000 / 2,000,000"),
])
def test_money_reasons_print_as_money(raw, shown):
    trig, suffix = fs._build_trigger_facts("ACORD_127", {"auto_liability_limit": raw})
    assert suffix == f"Auto liability limit: {shown}"
    assert trig[0]["value"] == raw                            # the audit keeps the fact


def test_non_money_reasons_are_untouched():
    _t, suffix = fs._build_trigger_facts("ACORD_186", {"percent_subcontracted": "80%"})
    assert suffix == "% subcontracted: 80%"
    _t, suffix = fs._build_trigger_facts("ACORD_101", {"num_claims": "3"})
    assert suffix == "Prior claims: 3"


def test_paired_gl_limits_print_as_money():
    _t, suffix = fs._build_trigger_facts("ACORD_126", {"gl_each_occurrence": "1,000,000",
                                                      "gl_aggregate": "$2,000,000"})
    assert suffix == "limits $1,000,000 / $2,000,000"


def test_building_value_reason_totals_two_buildings():
    trig, suffix = fs._build_trigger_facts("ACORD_140", _two_buildings())
    assert suffix == "Building values: $1,100,000 (2 buildings)"
    assert trig[0]["value"] == "$700,000" and trig[0]["total"] == "$1,100,000"
    assert trig[0]["buildings"] == 2


def test_building_value_reason_edges():
    one = _two_buildings()
    one["property_locations"] = one["property_locations"][:1]
    _t, suffix = fs._build_trigger_facts("ACORD_140", one)
    assert suffix == "Building value: $700,000"                 # one building: as before
    three = _two_buildings()
    three["property_locations"].append({"location_id": "L3", "building_number": "3"})
    _t, suffix = fs._build_trigger_facts("ACORD_140", three)
    assert suffix == "Building values: $1,100,000 (2 of 3 buildings)"
    odd = _two_buildings()
    odd["property_locations"][1]["building_value"] = "Included"
    _t, suffix = fs._build_trigger_facts("ACORD_140", odd)
    assert suffix == "Building value: $700,000"                 # not a plain amount: no total
    none = _two_buildings()
    for r in none["property_locations"]:
        r["building_value"] = None
    _t, suffix = fs._build_trigger_facts("ACORD_140", none)
    assert suffix == "Building value: $700,000"


def test_the_umbrella_layer_reasons_are_unchanged():
    plain = {"umbrella_limit": "$5,000,000"}
    assert fs._build_trigger_facts("ACORD_131", plain)[1] == "Umbrella limit: $5,000,000"
    assert fs._build_trigger_facts("ACORD_131__excess", plain)[1] == "Excess limit: $5,000,000"


def test_match_forms_end_to_end_reasons():
    facts = {"auto_liability_limit": "1,000,000", "cyber_limit": "$1,000,000",
             **_two_buildings()}
    flags = {"has_auto_coverage": True, "has_property_coverage": True}
    text = "commercial auto. inland marine contractors equipment floater. property."
    by_id = {m["form_id"]: m.get("reason_label") or "" for m in
             fs.match_forms_deterministic(facts, flags, text)}
    assert "Cyber" not in by_id.get("ACORD_160", "")
    assert by_id["ACORD_127"].endswith("Auto liability limit: $1,000,000")
    assert by_id["ACORD_140"].endswith("Building values: $1,100,000 (2 buildings)")


# ── 3. Vehicle and driver tables merge on save ───────────────────────────────

def _vin(n: int) -> str:
    return f"1FTFW1ET5DFC{n:05d}"


def _fleet() -> list:
    return [{"year": str(2010 + i), "make": "FORD", "model": f"F-{150 + i}", "vin": _vin(i),
             "body_type": None, "gvw": None, "comp_symbol": "AP", "coll_symbol": "S",
             "class_code": f"0148{i}", "territory": "111", "cost_new": f"{30000 + i}"}
            for i in range(4)]


def _save(facts: dict, list_key: str, rows: list, source: str = "producer"):
    from services.arq_service import _write_schedule_rows
    clean, _ = sc.validate_rows(list_key, rows)
    return _write_schedule_rows(facts, list_key, clean, source)


def test_vehicle_and_driver_tables_are_merge_on_save():
    assert {"auto_vin_schedule", "auto_drivers", "property_locations"} <= sc.MERGE_ON_SAVE
    rows = sc.rows_from_facts("auto_vin_schedule", {"auto_vin_schedule": _fleet()})
    assert [r[sc.ROW_ID_KEY] for r in rows] == ["#0", "#1", "#2", "#3"]
    clean, _ = sc.validate_rows("auto_vin_schedule", rows)
    assert all(sc.ROW_ID_KEY in r for r in clean)               # the id survives validation


def test_editing_one_vin_keeps_every_rows_class_code_and_territory():
    facts = {"auto_vin_schedule": _fleet()}
    rows = sc.rows_from_facts("auto_vin_schedule", facts)
    rows[2]["vin"] = _vin(99)
    _save(facts, "auto_vin_schedule", rows)
    out = facts["auto_vin_schedule"]
    assert len(out) == 4 and out[2]["vin"] == _vin(99)
    assert [r["class_code"] for r in out] == [f"0148{i}" for i in range(4)]
    assert all(r["territory"] == "111" and r["cost_new"] for r in out)
    assert all(sc.ROW_ID_KEY not in r for r in out)             # never a fact
    assert facts[sc.HUMAN_SCHEDULES_KEY]["auto_vin_schedule"]["source"] == "producer"


def test_deleting_and_adding_rows():
    facts = {"auto_vin_schedule": _fleet()}
    rows = sc.rows_from_facts("auto_vin_schedule", facts)
    del rows[1]
    rows.append({"year": "2024", "make": "RAM", "model": "1500", "vin": _vin(50)})
    _save(facts, "auto_vin_schedule", rows)
    out = facts["auto_vin_schedule"]
    assert [r["vin"] for r in out] == [_vin(0), _vin(2), _vin(3), _vin(50)]
    assert [r.get("class_code") for r in out] == ["01480", "01482", "01483", None]


def test_an_import_without_ids_matches_by_unique_vin():
    facts = {"auto_vin_schedule": _fleet()}
    imported = [{"year": str(2010 + i), "make": "Ford Motor", "model": f"F-{150 + i}",
                 "vin": _vin(i).lower()} for i in range(4)]
    _save(facts, "auto_vin_schedule", imported)
    out = facts["auto_vin_schedule"]
    assert [r["class_code"] for r in out] == [f"0148{i}" for i in range(4)]
    assert all(r["make"] == "Ford Motor" for r in out)


def test_duplicate_vins_never_cross_match():
    stored = _fleet()
    stored[1]["vin"] = stored[0]["vin"]                          # two stored rows share a VIN
    facts = {"auto_vin_schedule": stored}
    _save(facts, "auto_vin_schedule", [{"year": "2030", "make": "X", "model": "Y", "vin": _vin(0)}])
    assert facts["auto_vin_schedule"] == [{"year": "2030", "make": "X", "model": "Y", "vin": _vin(0)}]
    # two TYPED rows sharing a stored VIN identify nothing either
    facts = {"auto_vin_schedule": _fleet()}
    twins = [{"year": "2030", "make": "X", "model": "Y", "vin": _vin(0)},
             {"year": "2031", "make": "X", "model": "Z", "vin": _vin(0)}]
    _save(facts, "auto_vin_schedule", twins)
    assert [r.get("class_code") for r in facts["auto_vin_schedule"]] == [None, None]


def test_a_stale_positional_id_yields_to_a_unique_vin():
    facts = {"auto_vin_schedule": _fleet()}
    rows = sc.rows_from_facts("auto_vin_schedule", facts)
    facts["auto_vin_schedule"] = list(reversed(facts["auto_vin_schedule"]))   # re-ordered since
    _save(facts, "auto_vin_schedule", rows[:1])                 # "#0" now sits on vehicle 3
    out = facts["auto_vin_schedule"]
    assert len(out) == 1 and out[0]["vin"] == _vin(0) and out[0]["class_code"] == "01480"


def test_a_vehicle_without_a_vin_keeps_its_fields_by_id():
    # The live package: every VIN redacted.
    fleet = _fleet()
    for r in fleet:
        r["vin"] = None
    facts = {"auto_vin_schedule": fleet}
    rows = sc.rows_from_facts("auto_vin_schedule", facts)
    rows[0]["model"] = "F-150 XL"
    _save(facts, "auto_vin_schedule", rows)
    assert [r["class_code"] for r in facts["auto_vin_schedule"]] == [f"0148{i}" for i in range(4)]
    assert facts["auto_vin_schedule"][0]["model"] == "F-150 XL"


def test_a_client_save_never_writes_or_wipes_the_producer_only_symbols():
    facts = {"auto_vin_schedule": _fleet()}
    client = sc.client_rows("auto_vin_schedule",
                            sc.validate_rows("auto_vin_schedule",
                                             sc.rows_from_facts("auto_vin_schedule", facts))[0])
    assert all("comp_symbol" not in r and sc.ROW_ID_KEY in r for r in client)
    client[0]["comp_symbol"] = "99"                              # a crafted cell is ignored
    client[3]["model"] = "F-999"
    _save(facts, "auto_vin_schedule", client, source="client_arq")
    out = facts["auto_vin_schedule"]
    assert [r["comp_symbol"] for r in out] == ["AP"] * 4
    assert out[3]["model"] == "F-999" and out[3]["class_code"] == "01483"


def _drivers() -> list:
    return [{"name": "Pat Doe", "dob": "01/02/1980", "license_number": "D111-222",
             "license_state": "MI", "relationship": "Employee", "gender": "F"},
            {"name": "Sam Roe", "dob": "03/04/1985", "license_number": "D333444",
             "license_state": "MI", "relationship": "Owner", "gender": "M"},
            {"name": "Lee Poe", "dob": "05/06/1990", "license_number": None,
             "license_state": "OH", "relationship": "Employee", "gender": "M"}]


def test_driver_save_keeps_fields_the_table_does_not_show():
    facts = {"auto_drivers": _drivers()}
    rows = sc.rows_from_facts("auto_drivers", facts)
    rows[1]["license_state"] = "OH"
    _save(facts, "auto_drivers", rows)
    out = facts["auto_drivers"]
    assert [r["relationship"] for r in out] == ["Employee", "Owner", "Employee"]
    assert out[1]["license_state"] == "OH" and out[0]["gender"] == "F"


def test_driver_import_matches_by_licence_then_name_and_birth_date():
    facts = {"auto_drivers": _drivers()}
    imported = [{"name": "Patricia Doe", "license_number": "d111 222"},   # licence, spelled loosely
                {"name": "Lee Poe", "dob": "05/06/1990", "hire_date": "01/01/2020"}]
    _save(facts, "auto_drivers", imported)
    out = facts["auto_drivers"]
    assert out[0]["relationship"] == "Employee" and out[0]["name"] == "Patricia Doe"
    assert out[1]["gender"] == "M" and out[1]["hire_date"] == "01/01/2020"
    assert len(out) == 2                                        # Sam was deleted


def test_ambiguous_driver_identities_never_match():
    stored = _drivers()
    stored.append(dict(stored[2], relationship="Spouse"))       # two Lee Poes, same birth date
    facts = {"auto_drivers": stored}
    _save(facts, "auto_drivers", [{"name": "Lee Poe", "dob": "05/06/1990", "license_state": "IN"}])
    assert facts["auto_drivers"][0].get("relationship") is None


def test_a_vin_edit_restamps_only_its_own_box_on_127():
    from services.arq_service import _restamp_schedule_into_forms
    schema = _schema("ACORD_127")
    facts = {"auto_vin_schedule": _fleet()}
    generated = {"ACORD_127": {"schema": schema, "field_state": {k: "" for k in schema},
                               "confidence": {}, "client_filled_fields": []}}
    _restamp_schedule_into_forms(generated, "auto_vin_schedule", facts, provenance="producer")
    state = generated["ACORD_127"]["field_state"]
    before = dict(state)
    assert any(v == "01482" for k, v in state.items() if k.startswith("Vehicle_RateClassCode_"))
    rows = sc.rows_from_facts("auto_vin_schedule", facts)
    rows[2]["vin"] = _vin(77)
    facts_before, _ = _save(facts, "auto_vin_schedule", rows)
    touched = _restamp_schedule_into_forms(generated, "auto_vin_schedule", facts,
                                           facts_before=facts_before, provenance="producer")
    assert touched == ["ACORD_127"]
    changed = {k for k in schema if state.get(k) != before.get(k)}
    assert changed and all(k.startswith("Vehicle_VINIdentifier_") for k in changed)


def test_the_location_table_rule_is_unchanged_by_the_identity_step():
    # Locations have no `_MERGE_IDENTITIES` entry: street / LOC # / BLDG # as before.
    assert "property_locations" not in sc._MERGE_IDENTITIES
    stored = [{"location_id": "L1", "address_line1": "1 Main St", "county": "Kent",
               "location_number": "1", "building_number": "1"},
              {"location_id": "L2", "address_line1": "9 Elm St", "county": "Ionia",
               "location_number": "2", "building_number": "1"}]
    typed = [{"address_line1": "9 Elm St", "address_city": "Lowell",
              "location_number": "2", "building_number": "1"}]
    clean, _ = sc.validate_rows("property_locations", typed)
    out = sc.merge_saved_rows("property_locations", stored, clean)
    assert out[0]["county"] == "Ionia" and out[0]["location_id"] == "L2"
