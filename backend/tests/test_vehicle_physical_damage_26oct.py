"""26 Oct 2026, Choice Electric: vehicles 001 / 002 carry no physical damage
(their rows in the dec's comprehensive / collision table are empty), yet the
ACORD 127 printed the policy-wide $1,000 deductibles on them."""
from services import pdf_service as ps
from services.extraction_service import read_vehicle_physical_damage

VEH = ("Veh # | Description:Year,Make,Model | Vehicle Identification | Territory and Garaging Location | Zip Code | Cost New | Stated Amount\n"
       "001 | 2001CHEVROLET EXPRESS G2500 | | 111 DENVER, CO | 80221 | 21,210 | \n"
       "002 | 2012HAULMARK TRAILER | | 111 DENVER, CO | 80221 | 7,500 | \n")
LIAB = ("-----LIABILITY----- --AUTO MEDICAL PAYMENTS--\n"
        "Veh # Limit Premium *1Deductible Premium\n001 1,000,000 1,251\n002 1,000,000 124 5,000 1\n")
PD = ("--UNINSURED/UNDERINSURED MOTORISTS-- ------COMPREHENSIVE------ --OF LOSS-- ------COLLISION------\n"
      "Veh #Limit Premium *2Deductible *2 Premium *2Deductible *2 Premium\n*3 *4 *5\n"
      "001\n002 1,000,000 0 AP 1,000 47 1,000 24\n--MEDICAL EXPENSE--\n")


def _facts():
    return {"auto_deductible_comp": "1,000", "auto_deductible_collision": "1,000", "_form_id": "ACORD_127",
            "auto_vin_schedule": [{"year": "2001", "make": "CHEVROLET", "model": "EXPRESS G2500"},
                                  {"year": "2012", "make": "HAULMARK", "model": "TRAILER"}]}


def test_a_vehicle_with_an_empty_physical_damage_row_prints_no_deductible():
    f = _facts()
    assert read_vehicle_physical_damage(f, [{"filename": "a.pdf", "text": VEH + LIAB + PD}])
    assert f["auto_vin_schedule"][0]["comp_covered"] is False and f["auto_vin_schedule"][0]["coll_covered"] is False
    assert "comp_covered" not in f["auto_vin_schedule"][1]       # a banner row with values says nothing more
    assert ps._resolve_vehicle_deductible_cell("Vehicle_Collision_DeductibleAmount_A", f) is None
    assert ps._resolve_vehicle_deductible_cell("Vehicle_Collision_DeductibleAmount_B", f) == "1,000"
    assert ps._is_authoritative_blank_field("Vehicle_Collision_DeductibleAmount_A", f)


def test_without_a_comprehensive_collision_table_nothing_changes():
    f = _facts()
    assert read_vehicle_physical_damage(f, [{"filename": "a.pdf", "text": VEH + LIAB}]) == []
    assert ps._resolve_vehicle_deductible_cell("Vehicle_Collision_DeductibleAmount_A", f) == "1,000"


def test_a_table_where_no_vehicle_states_a_value_is_not_read():
    f = _facts()
    empty = PD.replace("002 1,000,000 0 AP 1,000 47 1,000 24", "002")
    assert read_vehicle_physical_damage(f, [{"filename": "a.pdf", "text": VEH + empty}]) == []


NAMED = ("COVERED AUTOS - PHYSICAL DAMAGE AND COVERAGE ELECTIONS\n"
         "NO AUTO LIAB COMP COMP DED COLL COLL DED TOW RENT\n"
         "1 2019 FORD F-250 SUPER DUTY YES YES $500 YES $1,000 NO NO\n"
         "2 2021 CHEVROLET EXPRESS 2500 YES YES $250 NO NO NO NO\n"
         "ADDITIONAL COVERAGE ELECTIONS BY AUTO\n")


def _named_facts():
    return {"auto_deductible_comp": "500", "auto_deductible_collision": "1,000", "_form_id": "ACORD_127",
            "auto_vin_schedule": [{"year": "2019", "make": "FORD", "model": "F-250 SUPER DUTY"},
                                  {"year": "2021", "make": "CHEVROLET", "model": "EXPRESS 2500"}]}


def test_a_named_column_table_gives_each_vehicle_its_own_coverage_and_deductible():
    f = _named_facts()
    assert read_vehicle_physical_damage(f, [{"filename": "m.pdf", "text": NAMED}])
    v1, v2 = f["auto_vin_schedule"]
    assert (v1["comp_covered"], v1["comp_deductible"], v1["coll_covered"], v1["coll_deductible"]) == (True, "500", True, "1,000")
    assert (v2["comp_covered"], v2["comp_deductible"], v2["coll_covered"]) == (True, "250", False)
    r = ps._resolve_vehicle_deductible_cell
    assert r("Vehicle_Coverage_ComprehensiveOrSpecifiedCauseOfLossDeductibleAmount_B", f) == "250"
    assert r("Vehicle_Collision_DeductibleAmount_B", f) is None
    assert ps._resolve_vehicle_coverage_tick("Vehicle_Coverage_CollisionIndicator_B", f) is None


def test_election_lines_say_not_covered_per_vehicle():
    f = _named_facts()
    text = "AUTO 1 COLL: NO   AUTO 2 COMP DED: $1,000"
    read_vehicle_physical_damage(f, [{"filename": "e.txt", "text": text}])
    v1, v2 = f["auto_vin_schedule"]
    assert v1["coll_covered"] is False and v2["comp_deductible"] == "1,000"


def test_prose_naming_both_coverages_is_not_a_table():
    f = _named_facts()
    prose = "Physical damage coverage is requested: comprehensive and collision.\n2024 - Auto - backing collision - $11,400"
    assert read_vehicle_physical_damage(f, [{"filename": "p.txt", "text": prose}]) == []


def test_disagreeing_readings_leave_the_vehicle_alone():
    f = _named_facts()
    read_vehicle_physical_damage(f, [{"filename": "m.pdf", "text": NAMED}, {"filename": "e.txt", "text": "AUTO 1 COMP DED: $2,500"}])
    assert "comp_deductible" not in f["auto_vin_schedule"][0]
