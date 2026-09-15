"""Live run 10 (session ed191e49, 15 Sep 2026, Orbin policy only).

ACORD 126's OTHER coverage limit line printed "Commercial General Liability /
Commercial Auto Liability" and $1,000. The description is two whole lines of
business - the package's policies, not one coverage the form does not print -
and the amount came from a Pass-1 rule that stamped `gl_deductible` ("$1,000
Each Pollution Incidents", the pollution endorsement's deductible) into a
LIMIT box.
"""
import json
import os

import pytest

import services.pdf_service as ps

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DESC = "GeneralLiability_OtherCoverageDescription_A"
_TICK = "GeneralLiability_OtherCoverageIndicator_A"
_LIMIT_DESC = "GeneralLiability_OtherCoverageLimitDescription_A"
_LIMIT = "GeneralLiability_OtherCoverageLimitAmount_A"
_RUN10_DESC = "Commercial General Liability / Commercial Auto Liability"
_RUN10_DED = {"value": "$1,000 Each Pollution Incidents", "confidence": "ai_high", "source": "ai"}


def _schema(form_id):
    with open(os.path.join(BACKEND, "forms_schemas", f"{form_id}_schema.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _guard(values, form_id="ACORD_126", ai=None):
    mapped = dict(values)
    ps._enforce_post_fill_guards(mapped, _schema(form_id), {"_form_id": form_id},
                                 set(values) if ai is None else set(ai))
    return mapped


def test_a_deductible_never_stamps_the_other_coverage_limit():
    facts = {"gl_deductible": dict(_RUN10_DED), "_form_id": "ACORD_126"}
    with ps._schema_context(_schema("ACORD_126")):
        v = ps._deterministic_map(_LIMIT, facts)
    assert not (isinstance(v, str) and "1,000" in v)
    assert ps.source_fact_for_field(_LIMIT, facts, "ACORD_126") != "gl_deductible"


def test_the_deductible_boxes_still_read_the_deductible():
    facts = {"gl_deductible": {"value": "$1,000", "source": "ai"}, "_form_id": "ACORD_126"}
    assert ps.source_fact_for_field("GeneralLiability_PropertyDamage_DeductibleAmount_A", facts,
                                    "ACORD_126") == "gl_deductible"


@pytest.mark.parametrize("value", [_RUN10_DESC, "Auto and General Liability", "Umbrella; Commercial Auto",
                                   "Commercial General Liability", "General Liability"])
def test_a_list_of_lines_or_the_forms_own_line_is_not_an_other_coverage(value):
    assert _guard({_LIMIT_DESC: value})[_LIMIT_DESC] is None


@pytest.mark.parametrize("value", ["Hired and Non-Owned Auto Liability", "Liquor Liability",
                                   "Employee Benefits Liability", "Limited Pollution Coverage - Work Sites",
                                   "General Liability Elite Extension", "Stop Gap and Employers Liability",
                                   "Employee Benefits Liability, Limited Pollution"])
def test_one_real_other_coverage_survives(value):
    assert _guard({_LIMIT_DESC: value})[_LIMIT_DESC] == value


def test_the_tick_goes_with_its_description():
    out = _guard({_DESC: _RUN10_DESC, _TICK: "Yes"})
    assert out[_DESC] is None and out[_TICK] is None


def test_a_deterministic_description_is_not_judged():
    assert _guard({_LIMIT_DESC: _RUN10_DESC}, ai=set())[_LIMIT_DESC] == _RUN10_DESC


@pytest.mark.parametrize("form_id,field", [("ACORD_160", "GeneralLiability_OtherCoverageDescription_A"),
                                           ("ACORD_141", "CrimeCoverage_OtherCoverage_CoverageDescription_A")])
def test_141_and_160_are_left_alone(form_id, field):
    assert _guard({field: _RUN10_DESC}, form_id=form_id)[field] == _RUN10_DESC


def test_run10s_other_coverage_line_ships_blank_end_to_end():
    facts = {"gl_deductible": dict(_RUN10_DED)}
    m, _c = ps.map_facts_to_form(facts, _schema("ACORD_126"), form_id="ACORD_126", raw_text="",
                                 pre_filled_gpt={"filled_values": {_LIMIT_DESC: _RUN10_DESC},
                                                 "raw_text_fields": set(), "question_grounding": {}},
                                 guard_report=[])
    assert not m.get(_LIMIT_DESC) and not m.get(_LIMIT)
