"""
Regression tests for the ACORD 127 driver-schedule field mapping fix in
services.pdf_service._SCHEDULE_REGISTRY / _resolve_schedule_row.

Bug (found during code audit): the registry pointed "Driver_LicenseNumber"
and "Driver_LicenseStateOrProvince" at base names that do not exist in
ACORD_127_schema.json (the real fields are "Driver_LicenseNumberIdentifier"
and "Driver_LicensedStateOrProvinceCode"), so those two columns silently
never stamped. Separately, "Driver_GivenName" received the driver's whole
name string (no Surname mapping existed at all), stuffing "Erin Royal" into
the first-name box. Fixed by pointing at the real field names and splitting
auto_drivers[i]["name"] into given/surname via the "_name_given"/
"_name_surname" sentinel sub-keys.

ACORD 133 (Builders Risk) has an unrelated, pre-existing "Driver_FullName"
field that must keep resolving to the raw full-name string unchanged.

Run from backend/:
    python -m pytest tests/test_driver_schedule_mapping.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import _resolve_schedule_row, _split_driver_name, _SCHED_SKIP  # noqa: E402

_FACTS = {
    "auto_drivers": [
        {"name": "Erin Royal", "dob": "1985-04-02",
         "license_number": "94-327-1211", "license_state": "CO"},
        {"name": "Madonna", "dob": None,
         "license_number": None, "license_state": None},
    ]
}


def test_given_name_resolves_to_first_token_only():
    assert _resolve_schedule_row("Driver_GivenName_A", _FACTS) == "Erin"


def test_surname_resolves_to_last_token():
    assert _resolve_schedule_row("Driver_Surname_A", _FACTS) == "Royal"


def test_single_token_name_has_no_surname():
    assert _resolve_schedule_row("Driver_GivenName_B", _FACTS) == "Madonna"
    assert _resolve_schedule_row("Driver_Surname_B", _FACTS) is None


def test_license_number_identifier_resolves():
    assert _resolve_schedule_row("Driver_LicenseNumberIdentifier_A", _FACTS) == "94-327-1211"


def test_licensed_state_or_province_code_resolves():
    assert _resolve_schedule_row("Driver_LicensedStateOrProvinceCode_A", _FACTS) == "CO"


def test_birth_date_still_resolves_unaffected_by_fix():
    assert _resolve_schedule_row("Driver_BirthDate_A", _FACTS) == "1985-04-02"


def test_old_dead_base_names_no_longer_registered():
    # Confirms the old (never-matching) base names are gone, not just shadowed.
    assert _resolve_schedule_row("Driver_LicenseNumber_A", _FACTS) is _SCHED_SKIP
    assert _resolve_schedule_row("Driver_LicenseStateOrProvince_A", _FACTS) is _SCHED_SKIP


def test_acord133_driver_full_name_unaffected():
    # ACORD 133's Driver_FullName is a distinct, unrelated field — must keep
    # resolving to the raw full-name string, not the split given/surname.
    assert _resolve_schedule_row("Driver_FullName_A", _FACTS) == "Erin Royal"


def test_split_driver_name_helper():
    assert _split_driver_name("Erin Royal") == ("Erin", "Royal")
    assert _split_driver_name("Madonna") == ("Madonna", None)
    assert _split_driver_name("Jean Claude Van Damme") == ("Jean Claude Van", "Damme")
    assert _split_driver_name(None) == (None, None)
    assert _split_driver_name("") == (None, None)
