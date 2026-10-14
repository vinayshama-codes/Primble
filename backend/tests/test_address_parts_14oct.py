"""A state and ZIP typed as two parts, a house number typed as its own part, and a
state glued to the city by a comma (owner, 14 Oct 2026, live run 823d58a0).

"402 , dana street , Dnver,CO, 20132" raised "Address missing valid US state"
beside a typed CO, and "..., Denver, CO, 80216" parsed city "CO", state "80216".
Measured on 401 stored document addresses: one parse changed - a stored
"1245 Industrial Blvd, Unit 7, Aurora, CO, 80011" that printed city CO / state
80011 - and no check changed.
"""
from utils.helpers import _parse_address
from utils.validators import validate_address


def test_state_and_zip_as_two_parts():
    assert _parse_address("402 Dana Street, Denver, CO, 80216") == {
        "line1": "402 Dana Street", "city": "Denver", "state": "CO", "zip": "80216"}
    assert _parse_address("1245 Industrial Blvd, Unit 7, Aurora, CO, 80011") == {
        "line1": "1245 Industrial Blvd", "line2": "Unit 7", "city": "Aurora", "state": "CO", "zip": "80011"}


def test_a_house_number_typed_as_its_own_part():
    p = _parse_address("402, Dana Street, Denver, CO 80216")
    assert p["line1"] == "402 Dana Street" and p["city"] == "Denver" and p["state"] == "CO"


def test_the_standard_shapes_are_unchanged():
    assert _parse_address("4800 Washington St, Denver, CO 80216") == {
        "line1": "4800 Washington St", "city": "Denver", "state": "CO", "zip": "80216"}
    assert _parse_address("PO Box 11820, Tacoma, WA 98411")["city"] == "Tacoma"
    # a number that is not a house number before a street, and a non-state before a ZIP, stay as they were
    assert _parse_address("Suite 5, Denver, CO 80216")["line1"] == "Suite 5"
    assert _parse_address("10 Main St, Springfield, Lakeside, 80216")["city"] == "Lakeside"


def test_a_state_glued_to_the_city_is_seen():
    assert validate_address("402 , dana street , Dnver,CO, 20132") == (True, "")
    assert validate_address("402 Dana Street, Denver") == (False, "Address missing valid US state: '402 Dana Street, Denver'")
