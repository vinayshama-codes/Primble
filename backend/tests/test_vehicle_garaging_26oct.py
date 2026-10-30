"""26 Oct 2026: each vehicle's garaging city / state / ZIP is read off the
dec's vehicle table, not left to the AI (it varied between uploads)."""
from services import pdf_service as ps
from services.extraction_service import read_vehicle_garaging

DOC = {"filename": "auto.pdf", "text": (
    "Veh # | Description:Year,Make,Model | Vehicle Identification | Territory and Garaging Location | Zip Code | Cost New | Stated Amount\n"
    "001 | 2001CHEVROLET EXPRESS G2500 | | 111 DENVER, CO | 80221 | 21,210 | \n"
    "002 | 2012HAULMARK TRAILER | | 112 AURORA, CO | 80010 | 7,500 | \n")}


def _facts():
    return {"auto_vin_schedule": [
        {"year": "2001", "make": "CHEVROLET", "model": "EXPRESS G2500"},
        {"year": "2012", "make": "HAULMARK", "model": "TRAILER"}]}


def test_each_vehicle_takes_its_own_garaging_row():
    f = _facts()
    assert read_vehicle_garaging(f, [DOC])
    rows = f["auto_vin_schedule"]
    assert (rows[0]["garaging_city"], rows[0]["garaging_state"], rows[0]["garaging_zip"]) == ("Denver", "CO", "80221")
    assert (rows[1]["garaging_city"], rows[1]["garaging_zip"]) == ("Aurora", "80010")
    f["_form_id"] = "ACORD_127"
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_CityName_B", f) == "Aurora"
    assert ps._resolve_vehicle_garaging_cell("Vehicle_PhysicalAddress_PostalCode_A", f) == "80221"


def test_no_table_or_an_unmatched_vehicle_changes_nothing():
    f = _facts()
    assert read_vehicle_garaging(f, [{"filename": "x.pdf", "text": "no table here"}]) == []
    g = {"auto_vin_schedule": [{"year": "2020", "make": "FORD", "model": "F150"}]}
    assert read_vehicle_garaging(g, [DOC]) == [] and "garaging_city" not in g["auto_vin_schedule"][0]


def test_a_row_already_holding_garaging_keeps_it():
    f = _facts()
    f["auto_vin_schedule"][0]["garaging_city"] = "Golden"
    read_vehicle_garaging(f, [DOC])
    assert f["auto_vin_schedule"][0]["garaging_city"] == "Golden"
