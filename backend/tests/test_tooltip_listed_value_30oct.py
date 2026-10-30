"""Live 6875e80c (30 Oct 2026): ACORD 140's construction box lists "Joisted Masonry"
in its own tooltip, yet the type guard blanked it as a person's name - and the blank
raised the 140 download hard stop. A value the tooltip lists is never a name."""
import json
from pathlib import Path
import pytest
from services.pdf_service import _rejects_declared_type, _tooltip_lists_value

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "forms_schemas/ACORD_140_schema.json").read_text())


def _meta(name):
    fs = SCHEMA.get("fields") or SCHEMA
    if isinstance(fs, dict):
        return fs[name]
    return next(f for f in fs if f.get("name") == name)


@pytest.mark.parametrize("v", ["Joisted Masonry", "joisted masonry", "Masonry Non-Combustible",
                               "Modified Fire Resistive", "Fire Resistive", "Frame"])
def test_listed_construction_types_are_kept(v):
    assert _rejects_declared_type("Construction_ConstructionCode_A", _meta("Construction_ConstructionCode_A"), v) is None


def test_a_real_name_is_still_refused():
    assert _rejects_declared_type("Construction_ConstructionCode_A", _meta("Construction_ConstructionCode_A"),
                                  "Erin Royal") is not None


def test_whole_phrase_only():
    m = {"tu": "Enter code: * Joisted Masonry * Frame"}
    assert _tooltip_lists_value(m, "Joisted Masonry")
    assert not _tooltip_lists_value(m, "Masonry Jo")
    assert not _tooltip_lists_value(m, "Fr")
    assert not _tooltip_lists_value({}, "Frame")
