"""26 Oct 2026 (live 6c420291): building 2 printed on the dec went missing from one
upload's reading, so the review page saw one building and the download blocked on
ACORD 140's row 2. Buildings are now read from the dec's own Prem # / Bldg # blocks."""
from services.extraction_service import read_premises_buildings

DEC = ("Prem #: 001 Bldg #: 001\nConstruction Type: FRAME\nCOVERAGE: BUILDING\nLIMIT COINSURANCE DEDUCTIBLE\n"
       "$798,556 80% $5,000\nCOVERAGE: BUILDING-EQUIPMENT BREAKDOWN\nINCLUDED $5,000\n"
       "COVERAGE: PERSONAL PROPERTY-INSURED\n$73,008 80% $5,000\n"
       "Prem #: 001 Bldg #: 002\nConstruction Type: NON-COMBUSTIBLE - LIGHT STEEL\nCOVERAGE: BUILDING\n"
       "LIMIT COINSURANCE DEDUCTIBLE\n$421,714 80% $5,000\n")


def _facts(addr="4800 Dahlia St"):
    return {"property_locations": [{"address_line1": addr, "address_city": "Denver", "address_state": "CO",
                                    "premises_number": "001", "building_number": "001", "construction_type": "FRAME"}]}


def _doc(text=DEC, kind="dec_page"):
    return {"filename": "pkg.pdf", "doc_type": kind, "text": text}


def test_a_missing_building_is_added_at_its_premises_address():
    f = _facts()
    assert read_premises_buildings(f, [_doc()])
    rows = f["property_locations"]
    assert len(rows) == 2
    b2 = rows[1]
    assert (b2["building_number"], b2["construction_type"], b2["building_value"]) == ("002", "NON-COMBUSTIBLE - LIGHT STEEL", "$421,714")
    assert b2["address_line1"] == "4800 Dahlia St" and rows[0]["bpp_value"] == "$73,008"
    assert "bpp_value" not in b2                     # building 2's block states no contents here


def test_nothing_a_row_states_is_overwritten_and_rerun_is_stable():
    f = _facts()
    f["property_locations"][0]["building_value"] = "$800,000"
    read_premises_buildings(f, [_doc()])
    assert f["property_locations"][0]["building_value"] == "$800,000"
    n = len(f["property_locations"])
    assert read_premises_buildings(f, [_doc()]) == [] and len(f["property_locations"]) == n


def test_a_reference_is_never_copied_as_an_address():
    f = _facts(addr="SEE SCHEDULE")
    read_premises_buildings(f, [_doc()])
    assert "address_line1" not in f["property_locations"][1]


def test_certificates_tables_without_numbers_and_unknown_premises_change_nothing():
    assert read_premises_buildings(_facts(), [_doc(kind="certificate")]) == []
    assert read_premises_buildings(_facts(), [_doc("Prem. | Bldg. | Limit\nNo. | No. | Coverage")]) == []
    other = DEC.replace("Prem #: 001 Bldg #: 002", "Prem #: 002 Bldg #: 001")
    f = _facts()
    read_premises_buildings(f, [_doc(other)])
    assert len(f["property_locations"]) == 1         # premises 2 is not one the rows know


def test_two_premises_on_the_dec_need_the_row_to_name_its_premises():
    two = DEC + "Prem #: 002 Bldg #: 001\nConstruction Type: MASONRY\nCOVERAGE: BUILDING\n$500,000 80%\n"
    f = _facts(); f["property_locations"][0].pop("premises_number")
    read_premises_buildings(f, [_doc(two)])
    assert f["property_locations"][0]["construction_type"] == "FRAME"   # never filled from premises 2
    assert all(r.get("construction_type") != "MASONRY" for r in f["property_locations"])
