"""Brent 17 Oct item 8 (21 Oct 2026, build item b-cope-one-store): building
details in ONE place, and the COPE window asks only what is missing.

On a two-building package Brent answered six Property Integrity rows in
Recommendations one at a time (year built, roof year, sprinkler, protection
class, hydrant, fire department). Each saved ONE package value. Then the COPE
hard stop, missing only occupancy type, opened the WHOLE location table, whose
per-building cells could not show those answers. Asked twice, and the second
ask could not show the first.

1. ONE STORE (`premises_cope.per_building_fix`): on a package with 2+ location
   rows every place that asks a per-building COPE item (construction, building
   / BPP value, year built, roof year, sprinkler, protection class) asks it per
   building in the location table - the COPE cards, the Recommendations rows
   (`review_recommendations.fix_route_for_row`) and every stamped
   recommendation card (`answer_routing.stamp_recommendation`: the package
   rows after forms and the editor's ACORD 140 / 141 cards). Location-wide
   (hydrant, fire department) and package-level items (occupancy, valuation,
   coinsurance, BI, period of restoration) stay typed fields. One building:
   byte-identical.
2. ASK ONLY WHAT IS MISSING (`premises_cope.route_cope_resolution`): the
   window shows the per-building items the card still misses (plus each row's
   identity, `show_columns`) and the package-level boxes it misses; with only a
   package-level item missing it is a field window with just those boxes - and
   never a per-building box (the round-4 defect, part K).

Values are generic stand-ins (no client data). Frontend rules run under node.
"""

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services import premises_cope as pc
from services import review_recommendations as rr
from services import schedule_capture as sc
from services.issue_registry import (
    build_grouped_view, build_structured_from_sources, field_resolution, make_issue,
    resolution_for,
)
from services.premises_cope import (
    COPE_CARD_CODES, PER_BUILDING_COPE, PER_LOCATION_CARD_CODES, per_building_fix,
    route_cope_resolution,
)

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend" / "src"
RECS_JS = FRONT / "utils" / "recommendations.js"
FIXWIN_JS = FRONT / "utils" / "fixWindow.js"
MODAL = FRONT / "components" / "form" / "ResolutionModal.jsx"
ACORD = FRONT / "components" / "form" / "AcordModal.jsx"
_NODE = shutil.which("node") is None
needs_node = pytest.mark.skipif(_NODE, reason="node is not installed")

_LOCATION_WIDE = ("distance_to_hydrant", "fire_department_type")
_PACKAGE_LEVEL = ("occupancy_type", "valuation_method", "coinsurance_percentage",
                  "business_income_limit", "period_of_restoration", "locations")


def _rows(n: int = 2, **cells) -> list:
    """`n` buildings at one premises, each with its own construction and values."""
    out = []
    for i in range(n):
        row = {"location_id": f"L{i + 1}", "location_number": "1", "building_number": str(i + 1),
               "address_line1": "100 Main St", "address_city": "Springfield",
               "construction_type": "Frame" if i % 2 == 0 else "Non-Combustible",
               "building_value": f"${(i + 1) * 100000}", "bpp_value": "$50000"}
        row.update(cells)
        out.append(row)
    return out


def _two(**package) -> dict:
    """Two buildings; building 1's construction and values copied to the
    package facts (the live shape: the package scalar is building 1)."""
    facts = {"property_locations": _rows(2), "construction_type": "Frame",
             "property_building_value": "$100000", "property_bpp_value": "$50000"}
    facts.update(package)
    return {k: v for k, v in facts.items() if v is not None}


def _one(**package) -> dict:
    facts = _two(**package)
    facts["property_locations"] = facts["property_locations"][:1]
    return facts


_CARD_MSG = {
    "minimum_viable_cope_missing": "Property submission missing Minimum Viable COPE: occupancy type",
    "legacy_minimum_viable_cope": "Property Minimum Viable COPE incomplete - missing: occupancy type",
    "carrier_grade_cope_incomplete": "Carrier-Grade COPE detail incomplete - missing: roof year, protection class",
    "legacy_carrier_grade_cope": "Carrier-Grade COPE incomplete - Submission Quality Score (SQS) capped at 85. Missing: roof year",
    "per_location_cope_incomplete": "1 of 2 insured locations are missing construction type or building/BPP value.",
}


def _view_items(view: dict) -> list:
    clusters = list(view.get("hard_stops") or []) + [c for t in (view.get("warnings") or {}).values() for c in t]
    return [(c, i) for c in clusters for i in c["items"]]


def _routed_through_the_view(code: str, facts: dict, severity: str = "hard_stop"):
    """The card's resolution as the real grouped view draws it (item, cluster)."""
    msg = _CARD_MSG[code]
    issue = make_issue(code, severity, msg, ["ACORD_140"])
    hard, soft = ([msg], []) if severity == "hard_stop" else ([], [msg])
    view = build_grouped_view([issue], hard, soft, facts=facts)
    cluster, item = next((c, i) for c, i in _view_items(view) if i["code"] == code)
    return item["resolution"], cluster["resolution"]


# ══ 0. Adversarial first: what must NEVER happen ═════════════════════════════

@pytest.mark.parametrize("code", sorted(COPE_CARD_CODES | PER_LOCATION_CARD_CODES))
def test_one_building_or_none_is_byte_identical(code):
    base = resolution_for(code)
    for rows in (None, [], _rows(1), ["not a row", None, 7] + _rows(1)):
        # (28 Oct 2026) A package naming NO premises at all - no address, no
        # location row - is the one case the Minimum Viable card changes: it
        # also shows the premises address box its hard stop checks
        # (`premises_cope._with_premises_box`). A stated address keeps it.
        facts = {"occupancy_type": None, "locations": ["100 Main St"]}
        if rows is not None:
            facts["property_locations"] = rows
        assert route_cope_resolution(code, base, facts) is base
        assert route_cope_resolution(code, base, {**facts, "property_locations":
                                                  {"value": rows, "source": "extracted"}}) is base
        if not rows and code in ("minimum_viable_cope_missing", "legacy_minimum_viable_cope"):
            bare = {k: v for k, v in facts.items() if k != "locations"}
            assert route_cope_resolution(code, base, bare)["facts"] == ["locations"] + base["facts"]
    for fact in PER_BUILDING_COPE:
        assert per_building_fix(fact, _one()) is None
        assert per_building_fix(fact, {}) is None


@pytest.mark.parametrize("code", sorted(COPE_CARD_CODES))
def test_no_per_building_fact_is_ever_a_package_box_on_two_buildings(code):
    """Round 4 (7 Oct, part K): a field window on a two-building package
    printed building 1's construction and values as THE package's. Whatever
    the package states, a window on 2+ buildings never offers a per-building
    fact as a typed box - so nothing of building 1 can be pre-filled as the
    submission's."""
    base = resolution_for(code)
    packages = ({}, {"occupancy_type": "Office"},
                {"occupancy_type": "Office", "year_built": "1990", "valuation_method": "RCV"},
                {"occupancy_type": "Office", "year_built": "1990", "roof_year": "2011",
                 "sprinkler_system": "100", "fire_protection_class": "3",
                 "valuation_method": "RCV", "coinsurance_percentage": "80%"},
                {"construction_type": None, "property_building_value": None, "property_bpp_value": None})
    for package in packages:
        for rows in (_rows(2), _rows(2, construction_type="", building_value="", bpp_value=""), _rows(6)):
            facts = _two(**package)
            facts["property_locations"] = rows
            res = route_cope_resolution(code, copy.deepcopy(base), facts)
            boxes = set(res.get("facts") or []) | set(res.get("controls") or {})
            assert not boxes & set(PER_BUILDING_COPE), (package, res)
            # Never an empty window.
            assert res.get("facts") or res.get("columns"), (package, res)


def test_location_wide_and_package_level_items_stay_typed_fields():
    facts = _two()
    for fact in _LOCATION_WIDE + _PACKAGE_LEVEL + ("", None, "not_a_fact", "construction"):
        assert per_building_fix(fact, facts) is None
        row = {"pillar": "property_integrity", "field": fact}
        res = rr.fix_route_for_row(row, facts)
        if fact in _LOCATION_WIDE + _PACKAGE_LEVEL[:-1]:
            assert res == field_resolution(fact)


def test_the_input_resolution_is_never_mutated():
    for code in sorted(COPE_CARD_CODES | PER_LOCATION_CARD_CODES):
        base = resolution_for(code)
        before = copy.deepcopy(base)
        for package in ({}, {"occupancy_type": "Office"}):
            facts = _two(**package)
            facts["property_locations"][1]["building_value"] = ""
            facts["property_locations"][1]["bpp_value"] = ""
            route_cope_resolution(code, base, facts)
        assert base == before


def test_bad_input_passes_through():
    facts = _two()
    for bad in (None, "x", 5, [], {"mode": "field"}):
        assert route_cope_resolution("minimum_viable_cope_missing", bad, facts) == bad
    base = resolution_for("minimum_viable_cope_missing")
    for bad_facts in (None, [], "x", 3):
        assert route_cope_resolution("minimum_viable_cope_missing", base, bad_facts) is base
        assert per_building_fix("year_built", bad_facts) is None
    for code in ("auto_um_uim_not_specified", None, "", "legacy_valuation_method_missing"):
        res = resolution_for(code) if code else {"mode": "field", "facts": ["year_built"]}
        assert route_cope_resolution(code, res, facts) is res
    # A card that asks no per-building fact keeps its own window.
    only_pkg = {"mode": "field", "facts": ["occupancy_type"]}
    assert route_cope_resolution("legacy_minimum_viable_cope", only_pkg, facts) is only_pkg
    # A schedule-mode COPE card (not the per-location one) is not re-routed.
    sched = {"mode": "schedule", "schedule_key": "property_locations"}
    assert route_cope_resolution("minimum_viable_cope_missing", sched, facts) is sched


# ══ 1. Ask only what is missing ══════════════════════════════════════════════

@pytest.mark.parametrize("code", ["minimum_viable_cope_missing", "legacy_minimum_viable_cope"])
def test_occupancy_only_is_a_field_window_with_just_that_box(code):
    # The live shape of Brent's 19:00 fix: every per-building item stated, only
    # occupancy missing - it used to open the whole two-building table.
    res = route_cope_resolution(code, resolution_for(code), _two())
    assert res["mode"] == "field"
    assert res["facts"] == ["occupancy_type"]
    assert set(res["controls"]) == {"occupancy_type"} and res["controls"]["occupancy_type"]["options"]
    assert "needs" not in res                              # one box: nothing partial to say
    for key in ("schedule_key", "columns", "row_needs", "show_columns", "derives", "note"):
        assert key not in res
    # The real grouped view draws the same window (item and cluster).
    item, cluster = _routed_through_the_view(code, _two())
    assert item == res and cluster == res


def test_the_legacy_twin_from_its_sentence_routes_the_same_way():
    msg = ("Property Minimum Viable COPE incomplete - missing: occupancy type "
           "Fix: Review and correct this before proceeding.")
    view = build_grouped_view(build_structured_from_sources(legacy_hard=[msg]), [msg], [], facts=_two())
    res = [i for _c, i in _view_items(view) if "COPE" in i["message"]][0]["resolution"]
    assert res["mode"] == "field" and res["facts"] == ["occupancy_type"]
    one = build_grouped_view(build_structured_from_sources(legacy_hard=[msg]), [msg], [], facts=_one())
    res1 = [i for _c, i in _view_items(one) if "COPE" in i["message"]][0]["resolution"]
    # One building: its own card, offering only the box that needs fixing
    # (Rule 1 / G1, 30 Oct 2026 - the stated construction and values are not re-asked).
    whole = resolution_for("legacy_minimum_viable_cope")
    assert res1["facts"] == ["occupancy_type"]
    assert {k: v for k, v in res1.items() if k != "facts"} == {k: v for k, v in whole.items() if k != "facts"}


def test_only_the_missing_per_building_columns_are_asked():
    facts = _two(property_building_value=None, property_bpp_value=None)
    facts["property_locations"][1]["building_value"] = ""
    facts["property_locations"][1]["bpp_value"] = ""
    res = route_cope_resolution("minimum_viable_cope_missing", resolution_for("minimum_viable_cope_missing"), facts)
    assert res["mode"] == "schedule" and res["schedule_key"] == "property_locations"
    assert res["columns"] == ["building_value", "bpp_value"]          # construction is stated: not asked
    assert res["row_needs"] == [["building_value", "bpp_value"]]      # either one per building
    assert res["derives"] == ["property_building_value", "property_bpp_value"]
    assert res["facts"] == ["occupancy_type"] and set(res["controls"]) == {"occupancy_type"}
    assert res["per_building"] is True and "2 buildings" in res["note"]


def test_a_typed_package_value_is_never_asked_again():
    # Brent's own state: year built typed once for the package before this
    # change, the rows empty. The window must not ask it a second time.
    facts = _two(occupancy_type="Office", valuation_method="RCV", coinsurance_percentage="80%",
                 year_built={"value": "1990", "source": "producer", "confidence": "filled"})
    for code in ("legacy_carrier_grade_cope", "carrier_grade_cope_incomplete"):
        res = route_cope_resolution(code, resolution_for(code), facts)
        assert res["mode"] == "schedule"
        assert res["columns"] == ["roof_year", "sprinkler", "protection_class"]
        assert "year_built" not in res["columns"] and "year_built" not in res["derives"]
        assert "facts" not in res


def test_a_value_every_building_states_still_opens_its_column_to_carry_it():
    # Documents gave each building its construction but no package construction
    # (the merge derives nothing): the card fires on construction and only a
    # save of the table carries the buildings' values to the submission. The
    # window still offers it - a card must never be impossible to clear.
    facts = _two(construction_type=None, occupancy_type="Office")
    res = route_cope_resolution("minimum_viable_cope_missing", resolution_for("minimum_viable_cope_missing"), facts)
    assert res["mode"] == "schedule" and res["columns"] == ["construction_type"]
    assert res["row_needs"] == [["construction_type"]] and "facts" not in res
    assert res["confirm_columns"] == ["construction_type"]          # the save must carry it
    # Beside the occupancy box too: the window names the cells only its save carries.
    both = route_cope_resolution("minimum_viable_cope_missing", resolution_for("minimum_viable_cope_missing"),
                                 _two(construction_type=None))
    assert both["facts"] == ["occupancy_type"] and both["confirm_columns"] == ["construction_type"]
    # A column some building lacks is asked, never "confirmed".
    gap = _two(construction_type=None)
    gap["property_locations"][1]["construction_type"] = ""
    gap_res = route_cope_resolution("minimum_viable_cope_missing", resolution_for("minimum_viable_cope_missing"), gap)
    assert "confirm_columns" not in gap_res
    # Saving the unchanged table clears the card (the 7 Oct write door).
    from services.arq_service import _write_schedule_rows
    from services.sqs_service import evaluate_stops
    flags = {"has_property_coverage": True}
    facts["locations"] = ["100 Main St, Springfield"]
    hard, _soft = evaluate_stops(facts, flags)
    assert any("missing: construction type" in m for m in hard)
    clean, _ = sc.validate_rows("property_locations", sc.rows_from_facts("property_locations", facts))
    _write_schedule_rows(facts, "property_locations", clean, "producer")
    hard, _soft = evaluate_stops(facts, flags)
    assert not any("Minimum Viable COPE" in m for m in hard)
    assert facts["construction_type"]["value"] == "Frame"              # row 1 = ACORD row A


@pytest.mark.parametrize("code", ["legacy_carrier_grade_cope", "carrier_grade_cope_incomplete"])
def test_package_level_only_carrier_grade_is_a_field_window(code):
    facts = _two(occupancy_type="Office", year_built="1990", roof_year="2011",
                 sprinkler_system="100", fire_protection_class="3")
    res = route_cope_resolution(code, resolution_for(code), facts)
    assert res["mode"] == "field"
    assert res["facts"] == ["valuation_method", "coinsurance_percentage"]
    assert set(res["controls"]) == {"valuation_method", "coinsurance_percentage"}
    if code == "legacy_carrier_grade_cope":                 # its rule needs both
        assert res["needs"] == [["valuation_method"], ["coinsurance_percentage"]]
    else:                                                   # the coded card declares none
        assert "needs" not in res


def test_never_an_empty_window_when_the_rule_reads_a_value_as_missing():
    # The rule counts a boolean False sprinkler as missing; this reading counts
    # it stated. Nothing would be left to ask - the window falls back to every
    # per-building item the card asks, in its own row (the 7 Oct table).
    facts = _two(occupancy_type="Office", year_built="1990", roof_year="2011",
                 sprinkler_system=False, fire_protection_class="3",
                 valuation_method="RCV", coinsurance_percentage="80%")
    res = route_cope_resolution("legacy_carrier_grade_cope", resolution_for("legacy_carrier_grade_cope"), facts)
    assert res["mode"] == "schedule"
    assert res["columns"] == ["year_built", "roof_year", "sprinkler", "protection_class"]


def test_either_group_counts_once():
    res = route_cope_resolution("legacy_minimum_viable_cope", resolution_for("legacy_minimum_viable_cope"),
                                _two(property_building_value=None))      # BPP stated: satisfied
    assert res["mode"] == "field" and res["facts"] == ["occupancy_type"]
    for fact in ("property_building_value", "property_bpp_value"):
        fix = per_building_fix(fact, _two())
        assert fix["columns"] == ["building_value", "bpp_value"]
        assert fix["row_needs"] == [["building_value", "bpp_value"]]
        assert fix["derives"] == ["property_building_value", "property_bpp_value"]


def test_many_buildings_and_an_enveloped_table():
    rows = _rows(5)
    facts = {"property_locations": {"value": rows + ["junk", None], "source": "extracted"}}
    res = route_cope_resolution("minimum_viable_cope_missing", resolution_for("minimum_viable_cope_missing"), facts)
    assert res["mode"] == "schedule" and "5 buildings" in res["note"]
    assert res["columns"] == ["construction_type", "building_value", "bpp_value"]
    assert res["facts"] == ["occupancy_type"]


def test_show_columns_name_each_building_and_hold_every_asked_column():
    cols = {c["key"] for c in sc.SCHEDULE_DEFS["property_locations"]["columns"]}
    identity = list(sc.SCHEDULE_DEFS["property_locations"]["dedup_keys"])
    fix = per_building_fix("year_built", _two())
    assert fix["show_columns"] == ["address_line1", "address_city", "location_number", "building_number",
                                   "year_built"]
    assert set(fix["show_columns"]) <= cols and set(fix["show_columns"]) - {"year_built"} <= set(identity)
    # A redacted street (the live decs): only the identity some row fills is shown.
    facts = _two()
    for r in facts["property_locations"]:
        r.pop("address_line1"), r.pop("address_city")
    fix = per_building_fix("roof_year", facts)
    assert fix["show_columns"] == ["location_number", "building_number", "roof_year"]
    # Rows with no identity at all still show the asked column.
    bare = {"property_locations": [{"construction_type": "Frame"}, {"construction_type": "Frame"}]}
    assert per_building_fix("fire_protection_class", bare)["show_columns"] == ["protection_class"]
    assert per_building_fix("protection_class", bare) is None            # a column is not a fact


# ══ 2. The per-location card asks only the columns some building lacks ═══════

def test_the_per_location_card_asks_only_what_a_building_lacks():
    base = resolution_for("per_location_cope_incomplete")
    facts = _two()
    facts["property_locations"][1]["building_value"] = ""
    facts["property_locations"][1]["bpp_value"] = ""
    res = route_cope_resolution("per_location_cope_incomplete", base, facts)
    assert res["mode"] == "schedule" and res["schedule_key"] == "property_locations"
    assert res["columns"] == ["building_value", "bpp_value"]
    assert res["row_needs"] == [["building_value", "bpp_value"]]
    assert res["derives"] == ["property_building_value", "property_bpp_value"]
    facts["property_locations"][1]["construction_type"] = ""
    res = route_cope_resolution("per_location_cope_incomplete", base, facts)
    assert res["columns"] == ["construction_type", "building_value", "bpp_value"]
    assert res["row_needs"] == [["construction_type"], ["building_value", "bpp_value"]]
    # Its groups ARE Minimum Viable COPE's per-building part (one declaration).
    groups = [[PER_BUILDING_COPE[f] for f in g] for g in resolution_for("minimum_viable_cope_missing")["needs"]
              if all(f in PER_BUILDING_COPE for f in g)]
    assert groups == res["row_needs"]
    # Every building complete (a stale card): its own whole-table window.
    assert route_cope_resolution("per_location_cope_incomplete", base, _two()) is base


def test_a_blank_row_is_not_a_building():
    base = resolution_for("per_location_cope_incomplete")
    facts = _two()
    facts["property_locations"].append({"location_id": "", "address_line1": "", "_row_id": "r9"})
    assert route_cope_resolution("per_location_cope_incomplete", base, facts) is base


# ══ 3. The Recommendations rows and every stamped card: one store ═════════════

@pytest.mark.parametrize("fact", sorted(PER_BUILDING_COPE))
def test_a_recommendations_row_asks_per_building_like_the_cards(fact):
    row = {"pillar": "property_integrity", "field": fact, "answer_mode": "field"}
    res = rr.fix_route_for_row(row, _two())
    assert res == per_building_fix(fact, _two())
    assert res["mode"] == "schedule" and res["schedule_key"] == "property_locations"
    assert set(res["columns"]) == {PER_BUILDING_COPE[f] for f in pc._item_facts(fact)}
    assert res["row_needs"] and res["show_columns"][-len(res["columns"]):] == res["columns"]
    # One building: exactly the field window it always was.
    assert rr.fix_route_for_row(row, _one()) == field_resolution(fact)
    assert rr.fix_route_for_row(dict(row), {}) == field_resolution(fact)


def test_with_fix_routes_routes_only_the_per_building_rows():
    rows = [{"pillar": "property_integrity", "field": f, "answer_mode": "field", "points_available": 1.5}
            for f in ("year_built", "distance_to_hydrant", "occupancy_type", "property_building_value")]
    out = rr.with_fix_routes({"package_sqs_score": 50, "top_recommendations": rows}, _two())
    modes = {r["field"]: r["resolution"]["mode"] for r in out["top_recommendations"]}
    assert modes == {"year_built": "schedule", "distance_to_hydrant": "field",
                     "occupancy_type": "field", "property_building_value": "schedule"}
    one = rr.with_fix_routes({"package_sqs_score": 50, "top_recommendations": rows}, _one())
    assert all(r["resolution"]["mode"] == "field" for r in one["top_recommendations"])
    assert rows[0] == {"pillar": "property_integrity", "field": "year_built", "answer_mode": "field",
                       "points_available": 1.5}                       # input untouched


def test_stamping_routes_a_card_and_takes_its_route_back():
    from services.answer_routing import stamp_recommendation
    rec = {"rec_id": "rec_year_built", "field": "year_built"}
    stamp_recommendation(rec, _two())
    assert rec["answer_mode"] == "schedule" and rec["schedule_key"] == "property_locations"
    assert rec["resolution"] == per_building_fix("year_built", _two())
    # The package lost a building: re-stamped, it is the typed box again and
    # the table route it carried is gone.
    stamp_recommendation(rec, _one())
    assert rec["answer_mode"] == "field" and "resolution" not in rec and "schedule_key" not in rec
    # Never touches a card that is not a per-building COPE fact.
    other = {"rec_id": "rec_x", "field": "distance_to_hydrant"}
    stamp_recommendation(other, _two())
    assert other["answer_mode"] == "field" and "resolution" not in other
    table = {"rec_id": "rec_v", "field": "auto_vin_schedule"}
    stamp_recommendation(table, _two())
    assert table["answer_mode"] == "schedule" and table["schedule_key"] == "auto_vin_schedule"
    assert "resolution" not in table


def _score_package(facts: dict, flags: dict) -> dict:
    from services.cross_form_validator import run_cross_form_validation, split_cross_form_issues
    from services.sqs_service import calculate_package_sqs, evaluate_stops
    fh, fs = evaluate_stops(facts, flags)
    cf = run_cross_form_validation(facts, flags, {"ACORD_125", "ACORD_140"})
    ch, cs, _adv = split_cross_form_issues(cf)
    return calculate_package_sqs(
        facts=facts, flags=flags, form_results=[], cross_issues=cf,
        hard_stops=list(fh) + list(ch), soft_stops=list(fs) + list(cs),
        session_data={"docs": [], "selected_form_ids": ["ACORD_125", "ACORD_140"], "sqs_history": [],
                      "underwriting_consistency": {}},
        form_fill=False)


def _property_facts(**over) -> dict:
    facts = {"applicant_name": "Sample Builders LLC", "mailing_address": "100 Main St, Springfield, IL 62701",
             "effective_date": "01/01/2027", "expiration_date": "01/01/2028",
             "lines_of_business": ["Commercial Property"], "entity_type": "LLC",
             "occupancy_type": "Office", "locations": ["100 Main St, Springfield, IL 62701"],
             "valuation_method": "Replacement Cost", "coinsurance_percentage": "80%",
             "business_income_limit": "$100,000", "period_of_restoration": "12 months"}
    facts.update(_two())
    facts.update(over)
    return facts


def test_the_scored_packages_rows_carry_the_table_and_the_score_does_not_move(monkeypatch):
    flags = {"has_property_coverage": True}
    facts = _property_facts()
    pkg = _score_package(copy.deepcopy(facts), flags)
    rows = {r.get("field"): r for r in pkg["top_recommendations"]
            if isinstance(r, dict) and r.get("pillar") == "property_integrity"}
    for fact in ("year_built", "roof_year", "sprinkler_system", "fire_protection_class"):
        assert rows[fact]["answer_mode"] == "schedule", fact
        assert rows[fact]["resolution"] == per_building_fix(fact, facts)
    for fact in _LOCATION_WIDE:
        assert rows[fact]["answer_mode"] == "field" and "resolution" not in rows[fact]
    # Display only: the same package with the route switched off scores the same.
    monkeypatch.setattr(pc, "per_building_fix", lambda *_a, **_k: None)
    plain = _score_package(copy.deepcopy(facts), flags)
    assert plain["package_sqs_score"] == pkg["package_sqs_score"]
    assert plain["pillars"] == pkg["pillars"]
    assert [r.get("field") for r in plain["top_recommendations"] if isinstance(r, dict)] == \
           [r.get("field") for r in pkg["top_recommendations"] if isinstance(r, dict)]


def test_the_editors_acord_140_cards_open_the_table_on_two_buildings():
    from services.sqs_service import calculate_sqs
    flags = {"has_property_coverage": True}
    for facts, routed in ((_property_facts(), True), (_property_facts(property_locations=_rows(1)), False)):
        res = calculate_sqs(copy.deepcopy(facts), flags, {}, {}, ["ACORD_140"], [], [], 0, form_id="ACORD_140")
        cards = {r["field"]: r for r in res.get("recommendations") or []
                 if isinstance(r, dict) and str(r.get("message") or "").startswith("For Carrier-Grade COPE provide")}
        assert {"year_built", "roof_year", "distance_to_hydrant"} <= set(cards)
        for fact in ("year_built", "roof_year", "sprinkler_system", "fire_protection_class"):
            if fact in cards:
                assert (cards[fact]["answer_mode"] == "schedule") is routed
                assert ("resolution" in cards[fact]) is routed
        assert cards["distance_to_hydrant"]["answer_mode"] == "field"


# ══ 4. One store end to end: per building, never one answer for all ══════════

def test_a_rows_table_answer_counts_only_when_every_building_has_it():
    from services.arq_service import _write_schedule_rows
    from services.sqs_service import property_gap_items
    flags = {"has_property_coverage": True}
    facts = _property_facts()
    assert any(i["fact"] == "year_built" for i in property_gap_items(facts, flags))
    fix = rr.fix_route_for_row({"pillar": "property_integrity", "field": "year_built"}, facts)
    assert fix["columns"] == ["year_built"]
    # Building 1 only ("Save progress"): building 2 stays empty, the gap stays.
    rows = sc.rows_from_facts("property_locations", facts)
    rows[0]["year_built"] = "1998"
    clean, _ = sc.validate_rows("property_locations", rows)
    _write_schedule_rows(facts, "property_locations", clean, "producer")
    assert facts["property_locations"][0]["year_built"] == "1998"
    assert not str(facts["property_locations"][1].get("year_built") or "").strip()
    assert not str((facts.get("year_built") or {}).get("value") or "").strip()
    assert any(i["fact"] == "year_built" for i in property_gap_items(facts, flags))
    # Every building: the submission takes building 1's (ACORD row A), the gap closes.
    rows = sc.rows_from_facts("property_locations", facts)
    rows[1]["year_built"] = "2004"
    clean, _ = sc.validate_rows("property_locations", rows)
    _write_schedule_rows(facts, "property_locations", clean, "producer")
    assert [r["year_built"] for r in facts["property_locations"]] == ["1998", "2004"]
    assert facts["year_built"]["value"] == "1998"
    assert not any(i["fact"] == "year_built" for i in property_gap_items(facts, flags))
    # The other buildings' details were never touched by the save.
    assert facts["property_locations"][1]["building_value"] == "$200000"


def test_a_typed_package_value_is_never_overwritten_by_the_table():
    from services.premises_cope import derive_package_cope
    facts = _two(year_built={"value": "1975", "source": "producer"})
    for r in facts["property_locations"]:
        r["year_built"] = "1990"
    assert derive_package_cope(facts) == []
    assert facts["year_built"]["value"] == "1975"


def test_answering_occupancy_alone_clears_the_hard_stop():
    from services.sqs_service import evaluate_stops
    flags = {"has_property_coverage": True}
    facts = _two(locations=["100 Main St, Springfield"])
    hard, _ = evaluate_stops(facts, flags)
    assert any("missing: occupancy type" in m for m in hard)
    res = route_cope_resolution("legacy_minimum_viable_cope", resolution_for("legacy_minimum_viable_cope"), facts)
    assert res["mode"] == "field" and res["facts"] == ["occupancy_type"]
    facts["occupancy_type"] = {"value": "Contractor shop or yard", "source": "producer", "confidence": "filled"}
    hard, _ = evaluate_stops(facts, flags)
    assert not any("Minimum Viable COPE" in m for m in hard)
    assert [r["building_value"] for r in facts["property_locations"]] == ["$100000", "$200000"]


# ══ 5. The frontend: one to-do, one place; the window shows only its columns ═

def _node(tmp_path, body: str) -> dict:
    script = tmp_path / "check.mjs"
    script.write_text(
        f"import * as R from {json.dumps(RECS_JS.as_uri())};\n"
        f"import * as W from {json.dumps(FIXWIN_JS.as_uri())};\n{body}\n", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _share_row(fact: str, resolution: dict, pts: float = 2.0) -> dict:
    return {"pillar": "property_integrity", "score": 70, "action": fact, "field": fact,
            "points_available": pts, "answer_gain": int(pts), "answer_gain_is_exact": True,
            "closes_with": "type", "resolution": resolution}


@needs_node
def test_the_frontend_lists_each_building_ask_once(tmp_path):
    two = _two(occupancy_type="Office", year_built=None)
    rows = [_share_row(f, per_building_fix(f, two)) for f in ("year_built", "roof_year")]
    rows.append(_share_row("distance_to_hydrant", field_resolution("distance_to_hydrant")))
    card = route_cope_resolution("legacy_carrier_grade_cope", resolution_for("legacy_carrier_grade_cope"),
                                 _two(occupancy_type="Office", valuation_method="RCV",
                                      coinsurance_percentage="80%"))
    grouped = {"hard_stops": [], "warnings": {"binder_followup": [{"cluster": "Property COPE quality",
               "count": 1, "items": [{"code": "legacy_carrier_grade_cope", "message": "COPE",
                                      "resolution": card}]}]}}
    attention = {"forms": [{"form_id": "ACORD_140", "form_label": "ACORD 140", "rows": [
        {"status": "missing", "field": "CommercialStructure_BuiltYear_B", "fact_key": "year_built",
         "label": "Year built (building 2)"}]}]}
    pkg = {"package_sqs_score": 70, "top_recommendations": rows}
    o = _node(tmp_path, (
        f"const pkg = {json.dumps(pkg)};\nconst g = {json.dumps(grouped)};\nconst att = {json.dumps(attention)};\n"
        "const alone = R.scoreItems(pkg, new Set());\n"
        "const withCard = R.scoreItems(pkg, R.onScreenFixKeys(g, null));\n"
        "const after = R.buildRecommendations({packageSqs: pkg, groupedIssues: {hard_stops: [], warnings: {}}, attention: att, formsExist: true});\n"
        "console.log(JSON.stringify({alone: alone.map(s => s.id), keys: alone.map(s => s.keys),\n"
        "  withCard: withCard.map(s => s.id), forms: after.forms.count,\n"
        "  also: after.score.map(s => [s.id, s.alsoOnForms])}));"))
    # Keyed on the fact (review L5): the same id a one-building box row has.
    assert o["alone"] == ["score:property_integrity:fact:year_built",
                          "score:property_integrity:fact:roof_year",
                          "score:property_integrity:fact:distance_to_hydrant"]
    assert o["keys"][0] == ["col:property_locations:year_built", "fact:year_built"]
    # The COPE card asks the same building cells: its rows are not listed twice.
    assert o["withCard"] == ["score:property_integrity:fact:distance_to_hydrant"]
    # After forms the 140's building-2 year-built box is the table row's, not a second to-do.
    assert o["forms"] == 0
    assert dict((k, v) for k, v in o["also"])[o["alone"][0]] == ["ACORD 140"]


@needs_node
def test_the_window_shows_only_its_columns(tmp_path):
    cols = sc.SCHEDULE_DEFS["property_locations"]["columns"]
    fix = per_building_fix("roof_year", _two())
    o = _node(tmp_path, (
        f"const cols = {json.dumps(cols)};\nconst fix = {json.dumps(fix)};\n"
        "const keys = (r) => W.windowColumns(cols, r).map(c => c.key);\n"
        "console.log(JSON.stringify({fix: keys(fix), whole: keys({mode: 'schedule', schedule_key: 'property_locations'}).length,\n"
        "  none: keys(null).length, empty: keys({show_columns: [], columns: []}).length,\n"
        "  unknown: keys({show_columns: ['nope']}).length,\n"
        "  asked: keys({show_columns: ['building_number'], columns: ['year_built']}),\n"
        "  bad: W.windowColumns(null, fix).length}));"))
    assert o["fix"] == ["address_line1", "address_city", "location_number", "building_number", "roof_year"]
    assert o["whole"] == len(cols) and o["none"] == len(cols) and o["empty"] == len(cols)
    assert o["unknown"] == len(cols)                     # never an empty table
    assert o["asked"] == ["building_number", "year_built"]   # an asked column is always shown
    assert o["bad"] == 0


@needs_node
def test_a_typed_box_never_leaves_the_buildings_values_behind(tmp_path):
    confirm = route_cope_resolution("minimum_viable_cope_missing", resolution_for("minimum_viable_cope_missing"),
                                    _two(construction_type=None))
    plain = per_building_fix("roof_year", _two())
    o = _node(tmp_path, (
        f"const confirm = {json.dumps(confirm)};\nconst plain = {json.dumps(plain)};\n"
        "const s = (typedOne, rowsTouched, resolution) => W.tableIsSaved({typedOne, rowsTouched, resolution});\n"
        "console.log(JSON.stringify([s(false, false, plain), s(true, true, plain), s(true, false, plain),\n"
        "  s(true, false, confirm), s(true, false, null), s(false, false, null), W.tableIsSaved()]));"))
    # nothing typed / table edited: saved, as before; a typed box beside an
    # untouched table: not re-saved, unless the window names cells only its save carries
    assert o == [True, True, False, True, False, True, True]


def test_every_route_draws_its_cards_with_the_session_facts():
    """A grouped view built without the facts draws a COPE card's own field
    window - on two buildings the round-4 shape (building 1's values as the
    package's). The editor's confirm-value and policy-line responses did; every
    route call now passes `facts=` and a new one cannot forget it."""
    import ast
    names = {"_grouped_cross_issues_for_panel", "_grouped_cross_issues_or_none",
             "_grouped_with_package_caps", "grouped_with_package_caps", "build_grouped_view"}
    calls, missing = 0, []
    for path in sorted((BACKEND / "routes").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name in names:
                calls += 1
                if "facts" not in {k.arg for k in node.keywords}:
                    missing.append(f"{path.name}:{node.lineno} {name}")
    assert calls >= 15, calls                                # the walk found the sites
    assert not missing, missing


def test_the_windows_are_wired_to_the_routes():
    modal = MODAL.read_text(encoding="utf-8")
    # The loaded schedule is scoped once, so the table, its required-cell check
    # and the per-building check all read the window's own columns.
    assert "setSchedule({ ...match, columns: windowColumns(match.columns, resolution) });" in modal
    assert "const savedTable = tableIsSaved({ typedOne: !!typedOne, rowsTouched: rowsTouched.current, resolution });" in modal
    assert "columns={schedule.columns || []}" in modal
    assert "table: [missingRequiredSummary(rows, schedule.columns || [])," in modal
    assert "rowNeedsSummary(rows, resolution.row_needs, schedule.columns || [], resolution.building_columns)" in modal
    assert "fixedRows={resolution.per_building === true}" in modal
    acord = ACORD.read_text(encoding="utf-8")
    m = re.search(r"const handleOpenRecSchedule = async \(rec\) => \{(.*?)\n  \};", acord, re.S)
    assert m and "rec.resolution" in m.group(1)
    for src in (modal, FIXWIN_JS.read_text(encoding="utf-8"), RECS_JS.read_text(encoding="utf-8")):
        assert "—" not in src                                       # no em-dashes in UI text


# ══ 6. Review fixes (21 Oct 2026) ═════════════════════════════════════════════

# M1 - ONE "is this row a building?" for every gate, the window, the derive and Save progress.
@pytest.mark.parametrize("stub", [{}, {"location_id": "L2"}, {"location_id": "L2", "location_number": "2",
                                                             "building_number": "2", "_row_id": "r2"},
                                  {"county": ""}])
def test_a_stub_row_is_not_a_building(stub):
    facts = _two()
    facts["property_locations"] = facts["property_locations"][:1] + [stub]
    assert pc.building_row_count(facts) == 1 and not pc.is_building_row(stub)
    for code in sorted(COPE_CARD_CODES | PER_LOCATION_CARD_CODES):
        assert route_cope_resolution(code, resolution_for(code), facts) is resolution_for(code) or \
            route_cope_resolution(code, resolution_for(code), facts) == resolution_for(code)
    assert per_building_fix("year_built", facts) is None
    # The one building's value is the package's - the stub never holds it back.
    facts["property_locations"][0]["year_built"] = "1998"
    from services.premises_cope import derive_package_cope
    derive_package_cope(facts)
    assert facts["year_built"]["value"] == "1998"


def test_two_buildings_and_a_stub_count_two_and_derive_over_the_buildings():
    from services.premises_cope import derive_package_cope
    facts = _two()
    facts["property_locations"].append({"location_id": "L3"})
    fix = per_building_fix("year_built", facts)
    assert "2 buildings" in fix["note"] and fix["building_columns"] == pc.building_columns()
    assert "location_number" not in fix["building_columns"] and "year_built" in fix["building_columns"]
    for i, y in ((0, "1998"), (1, "2004")):
        facts["property_locations"][i]["year_built"] = y
    derive_package_cope(facts)
    assert facts["year_built"]["value"] == "1998"


def test_the_note_counts_in_plain_words():
    assert pc._buildings_text(1) == "1 building" and pc._buildings_text(3) == "3 buildings"


@needs_node
def test_save_progress_counts_the_same_buildings(tmp_path):
    fix = per_building_fix("year_built", _two())
    rows = [{"year_built": "1998", "construction_type": "Frame"}, {"location_id": "L2", "location_number": "2"},
            {"construction_type": "Frame"}]
    script = tmp_path / "rn.mjs"
    script.write_text(
        f"import * as P from {json.dumps((FRONT / 'utils' / 'fixProgress.js').as_uri())};\n"
        f"const rows = {json.dumps(rows)};\nconst fix = {json.dumps(fix)};\n"
        "console.log(JSON.stringify([P.rowNeedsSummary(rows, fix.row_needs, [], fix.building_columns),\n"
        "  P.rowNeedsSummary(rows, fix.row_needs, [])]));", encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    with_rule, without = json.loads(run.stdout)
    assert with_rule == "year_built on row 3"          # the stub (row 2) is not a building
    assert without == "year_built on rows 2 and 3"     # the old any-cell rule


# L7 - the either-or value answered per building derives as one item.
def test_building_or_bpp_value_per_building_derives_the_item():
    from services.premises_cope import derive_package_cope
    from services.sqs_service import evaluate_stops
    facts = {"property_locations": [{"construction_type": "Frame", "bpp_value": "$50000"},
                                    {"construction_type": "Frame", "building_value": "$200000"}],
             "occupancy_type": "Office", "construction_type": "Frame", "locations": ["100 Main St"]}
    derive_package_cope(facts)
    assert facts["property_bpp_value"]["value"] == "$50000"          # building 1's own member
    assert not str((facts.get("property_building_value") or {}).get("value") or "")
    hard, _ = evaluate_stops(facts, {"has_property_coverage": True})
    assert not any("Minimum Viable COPE" in m for m in hard)
    # Building 2 loses its value: the item is no longer answered everywhere - retracted.
    facts["property_locations"][1]["building_value"] = ""
    assert derive_package_cope(facts) == ["property_bpp_value"]
    # A value typed for the package wins; nothing is picked beside it.
    typed = {"property_locations": [{"bpp_value": "$1"}, {"building_value": "$2"}],
             "property_building_value": {"value": "$9", "source": "producer"}}
    derive_package_cope(typed)
    assert typed["property_building_value"]["value"] == "$9" and "property_bpp_value" not in typed


# M2 - the producer write doors refuse a typed per-building value on 2+ buildings.
def test_the_producer_write_doors_redirect_to_the_table():
    from services.answer_routing import per_building_redirect
    red = per_building_redirect("year_built", _two())
    assert red["answer_mode"] == "schedule" and red["schedule_key"] == "property_locations"
    assert red["resolution"] == per_building_fix("year_built", _two()) and "2 buildings" in red["message"]
    assert per_building_redirect("year_built", _one()) is None
    assert per_building_redirect("distance_to_hydrant", _two()) is None
    assert per_building_redirect("occupancy_type", _two()) is None
    assert per_building_redirect(None, _two()) is None
    src = (BACKEND / "routes" / "audit_routes.py").read_text(encoding="utf-8")
    for fn in ("async def answer_recommendation(", "async def resolve_issue("):
        body = src[src.index(fn):]
        body = body[:body.index("\n@router", 1) if "\n@router" in body[1:] else len(body)]
        assert "per_building_redirect(" in body, fn
    acord = ACORD.read_text(encoding="utf-8")
    assert "resolution: data.resolution || rec.resolution" in acord


# L3 - the download review folds a card into the table that asks its cells.
def test_the_download_review_reads_the_tables_facts():
    from services import needs_attention as na
    card = route_cope_resolution("carrier_grade_cope_incomplete", resolution_for("carrier_grade_cope_incomplete"),
                                 _two(occupancy_type="Office"))
    keys = na.issue_fix_keys({"resolution": card})
    assert {"year_built", "roof_year", "property_locations"} <= keys
    from services.answer_routing import stamp_recommendation
    rec = stamp_recommendation({"rec_id": "rec_year_built", "field": "year_built"}, _two())
    assert {"year_built", "property_locations"} <= na.card_fix_keys(rec)
    plain = {"rec_id": "rec_year_built", "field": "year_built"}
    assert "property_locations" not in na.card_fix_keys(plain)       # one building: its box


# L4 - a card is filed answered only when the save closed it.
@needs_node
def test_a_card_is_answered_only_when_the_save_closed_it(tmp_path):
    rec = {"rec_id": "rec_year_built"}
    still = {"updated_forms": {"ACORD_140": {"new_sqs": {"recommendations": [rec, {"rec_id": "x"}]}}}}
    gone = {"updated_forms": {"ACORD_140": {"new_sqs": {"recommendations": [{"rec_id": "x"}]}}}}
    o = _node(tmp_path, (
        f"const still = {json.dumps(still)};\nconst gone = {json.dumps(gone)};\n"
        "console.log(JSON.stringify([W.recClosedBySave(still, 'rec_year_built'), W.recClosedBySave(gone, 'rec_year_built'),\n"
        "  W.recClosedBySave({}, 'rec_year_built'), W.recClosedBySave({updated_forms: {A: {}}}, 'rec_year_built'),\n"
        "  W.recClosedBySave(gone, null), W.recClosedBySave(null, 'r')]));"))
    assert o == [False, True, False, False, False, False]
    acord = ACORD.read_text(encoding="utf-8")
    i = acord.index("const _rec = issue?.__rec;")
    assert "if (!recClosedBySave(data, _rec.rec_id)) {" in acord[i:i + 600]


# L6 - a narrowed window never adds, removes or imports a building.
def test_a_narrowed_window_keeps_its_buildings():
    table = (FRONT / "components" / "arq" / "ScheduleTable.jsx").read_text(encoding="utf-8")
    assert "fixedRows = false," in table
    assert "{!fixedRows && <button\n                        type=\"button\"\n                        onClick={() => removeRow(idx)}" in table
    assert "{!fixedRows && <div style={{ marginLeft: 'auto'" in table
    assert "if (fixedRows) { e.preventDefault(); return; }" in table
