"""
Regression tests for LLM-prompt PII minimization on schedule rows (Figure 32
engineering note: "... and privacy controls for sensitive driver data").

Bug context: services.pdf_service._build_facts_block (the JSON facts block
built once per gap-fill LLM call, used by both the legacy per-form path and
combined_gap_fill - confirmed by reading the code: combined_gap_fill delegates
to _fill_unmatched_with_gpt, which owns _build_facts_block, so there is only
ONE site) only ever excluded whole TOP-LEVEL keys (_PII_EXCLUDE_KEYS: fein,
contact_phone, contact_email, mailing_address, physical_address). auto_drivers
was not in that set, so every driver's DOB and license number were sent to
the LLM in full on every gap-fill call, even though both are already
deterministically stamped onto the form (_resolve_schedule_row, Pass 1) and
are never needed by the LLM. Fixed via _SCHEDULE_ROW_PII_SUBKEYS +
_redact_schedule_rows, which strips just the sensitive sub-keys per row while
preserving the rest of the row (name, hire_date, experience_years,
vehicle_use_percent) for any legitimate narrative gap-fill question.

Run from backend/:
    python -m pytest tests/test_driver_pii_redaction.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pdf_service import _redact_schedule_rows, _SCHEDULE_ROW_PII_SUBKEYS  # noqa: E402


def test_dob_and_license_number_stripped_from_driver_rows():
    rows = [
        {"name": "Erin Royal", "dob": "1985-04-02", "license_number": "94-327-1211",
         "license_state": "CO", "hire_date": "2020-01-01",
         "experience_years": "12", "vehicle_use_percent": "50"},
    ]
    out = _redact_schedule_rows("auto_drivers", rows)
    assert "dob" not in out[0]
    assert "license_number" not in out[0]


def test_non_pii_row_fields_preserved():
    rows = [{"name": "Erin Royal", "dob": "1985-04-02", "license_number": "94-327-1211",
             "hire_date": "2020-01-01", "experience_years": "12", "vehicle_use_percent": "50"}]
    out = _redact_schedule_rows("auto_drivers", rows)
    assert out[0]["name"] == "Erin Royal"
    assert out[0]["hire_date"] == "2020-01-01"
    assert out[0]["experience_years"] == "12"
    assert out[0]["vehicle_use_percent"] == "50"


def test_unregistered_list_key_passes_through_unchanged():
    rows = [{"vin": "ABC123", "make": "Ford"}]
    assert _redact_schedule_rows("auto_vin_schedule", rows) == rows


def test_non_list_input_returns_unchanged():
    assert _redact_schedule_rows("auto_drivers", None) is None
    assert _redact_schedule_rows("auto_drivers", "not a list") == "not a list"


def test_registry_only_covers_auto_drivers_today():
    # Documents current scope - extend this dict (and this assertion) if
    # another schedule ever gains a sensitive per-row sub-key.
    assert set(_SCHEDULE_ROW_PII_SUBKEYS.keys()) == {"auto_drivers"}
    assert _SCHEDULE_ROW_PII_SUBKEYS["auto_drivers"] == {"dob", "license_number"}
