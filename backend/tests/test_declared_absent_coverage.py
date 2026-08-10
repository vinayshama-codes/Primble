"""A declarations page states what it does NOT cover, as plainly as what it does.

Client report (ACORD 125, Orbin Contracting) #5:
  "Remove: Commercial Property, Crime, Cyber and Privacy ...
   The declarations expressly show no Commercial Property, Crime/Fidelity or
   Workers' Compensation coverage."

Coverage flags are keyword-presence booleans - `has_crime` is defined in the
extraction prompt as "true if document mentions crime coverage ... fidelity
bond" - and they OR across every chunk and document
(`mg[k] = mg.get(k, False) or v`). So a dec-page row reading
"CRIME AND FIDELITY - NO COVERAGE" set the flag TRUE permanently.

This is the ONLY mechanism allowed to turn a coverage flag off, and it is
deliberately hard to trigger. SILENCE NEVER DOWNGRADES ANYTHING.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "sk-offline-test")

from services.extraction_service import (                # noqa: E402
    apply_declared_absent_downgrades,
    _lines_declared_absent,
    _FLAG_LINE_WORDS,
)

# The client's declarations page, in the shape OCR produces it.
ORBIN_DECS = (
    "COMMON POLICY DECLARATIONS\n"
    "General Liability  $3,954   Inland Marine  $300   "
    "Commercial Auto  $2,991   Umbrella  $3,418\n"
    "Property - No Coverage\n"
    "Crime and Fidelity - No Coverage\n"
    "Workers Compensation - No Coverage"
)

ALL_ON = (
    "has_property_coverage", "has_crime", "has_cyber", "has_general_liability",
    "has_auto_coverage", "has_umbrella", "has_inland_marine", "has_workers_comp",
)


def test_client_declarations_page_downgrades_exactly_the_denied_lines():
    flags = {k: True for k in ALL_ON}
    changed = apply_declared_absent_downgrades(flags, {}, ORBIN_DECS)
    assert sorted(changed) == ["has_crime", "has_property_coverage", "has_workers_comp"]


def test_covered_lines_on_the_same_page_survive():
    """The decisive regression risk. An earlier version downgraded has_umbrella
    because the 40-character window reached back across a NEWLINE into
    "Umbrella $3,418" on the row above - the exact opposite of what the page
    says. A dec page is a grid; a denial belongs to one row."""
    flags = {k: True for k in ALL_ON}
    apply_declared_absent_downgrades(flags, {}, ORBIN_DECS)
    for still_on in ("has_umbrella", "has_general_liability",
                     "has_auto_coverage", "has_inland_marine"):
        assert flags[still_on] is True, f"{still_on} was wrongly downgraded"


@pytest.mark.parametrize("text,expected", [
    ("Crime and Fidelity - No Coverage", "has_crime"),
    ("Property - No Coverage", "has_property_coverage"),
    # Two-column dec layout: the name and the denial are separate cells of one
    # row. Splitting on column whitespace was tried and discarded this case.
    ("Umbrella   $3,418      Property      No Coverage", "has_property_coverage"),
    ("Commercial Property   Not Covered", "has_property_coverage"),
    ("Inland Marine   Coverage Not Provided", "has_inland_marine"),
])
def test_real_denial_shapes_are_recognised(text, expected):
    assert _lines_declared_absent(text) == {expected}


def test_nearest_line_name_owns_the_denial():
    """One row can only silence one line."""
    assert _lines_declared_absent(
        "Property $1,000   Crime   No Coverage") == {"has_crime"}


@pytest.mark.parametrize("text", [
    # An exclusion INSIDE a covered line does not remove the line. This is
    # exactly why "excluded" is not a denial phrase: the client's own GL policy
    # carries a Cyber Incident and Data Privacy exclusion.
    "The General Liability policy contains a Cyber Incident and Data Privacy exclusion.",
    # A denial in its own sentence about something else.
    "Property values are scheduled. Flood is not covered.",
    # Silence.
    "General Liability $3,954 and Commercial Auto $2,991",
    "",
    # Distance - a line name far from an unrelated denial.
    "Property. " + ("x" * 90) + " no coverage",
])
def test_ambiguous_or_unrelated_text_downgrades_nothing(text):
    assert _lines_declared_absent(text) == set()


def test_positive_structured_evidence_vetoes_the_text_scan():
    """`coverage_lines` always beats prose. A document can mention "no coverage"
    for a line in a prior-policy summary while the CURRENT policy covers it."""
    flags = {"has_property_coverage": True}
    facts = {"coverage_lines": [{"line": "Commercial Property", "premium": "$5,000"}]}
    assert apply_declared_absent_downgrades(
        flags, facts, "Property - No Coverage") == []
    assert flags["has_property_coverage"] is True


def test_a_flag_is_never_turned_on():
    """Downgrade-only. This mechanism must never add coverage."""
    flags = {k: False for k in ALL_ON}
    assert apply_declared_absent_downgrades(flags, {}, ORBIN_DECS) == []
    assert not any(flags.values())


def test_a_flag_absent_from_the_dict_is_not_created():
    flags = {}
    apply_declared_absent_downgrades(flags, {}, ORBIN_DECS)
    assert flags == {}


def test_denial_phrases_exclude_the_dangerous_ones():
    """STANDING GUARD. "excluded" and "none" must never become denial phrases:
    an exclusion clause inside a covered line, and the word "none" scattered
    across a dec page, would both silence real coverage."""
    for dangerous in ("Crime excluded", "Crime  none", "Crime: N/A"):
        assert _lines_declared_absent(dangerous) == set(), dangerous


def test_every_configured_flag_is_a_real_coverage_flag():
    """A typo here silently disables the downgrade for that line."""
    from services.extraction_service import _EXTRACT_SCHEMA
    for flag in _FLAG_LINE_WORDS:
        assert f'"{flag}"' in _EXTRACT_SCHEMA, (
            f"{flag} is not a flag the extraction prompt produces"
        )


def test_malformed_inputs_are_survivable():
    for facts in ({}, {"coverage_lines": None}, {"coverage_lines": "x"},
                  {"coverage_lines": [None]}, {"coverage_lines": [{}]}):
        flags = {"has_crime": True}
        apply_declared_absent_downgrades(flags, facts, "Crime - No Coverage")
        assert flags["has_crime"] is False
